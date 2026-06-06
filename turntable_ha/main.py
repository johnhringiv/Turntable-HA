import asyncio
import logging
import os
import sqlite3
from datetime import timedelta
from enum import Enum
from functools import wraps
from time import monotonic

import denonavr
import httpx
from record_plays_db import RecordPlaysDB

logger = logging.getLogger(__name__)


class SwitchStatus(Enum):
    ERROR = 0
    OFF = 1
    IDLE = 2
    RUNNING = 3


class ProgramState(Enum):
    ERROR = 0
    IDLE = 1
    RUNNING = 3
    WARN = 5
    STANDBY = 6


def retry(times, exception):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            func_err = None
            for attempt in range(1, times + 1):
                try:
                    return await func(*args, **kwargs)
                except exception as e:
                    await asyncio.sleep(attempt * 2)
                    func_err = e
            raise func_err

        return wrapper

    return decorator


class SwitchController:
    def __init__(self, url: str, power_threshold: float = 2.0):
        self.url = url
        # Watts above which the plug is considered actively playing. A threshold
        # (rather than an exact ``== 0`` check) absorbs measurement noise and
        # residual draw so the reading does not spuriously flip IDLE<->RUNNING.
        self.power_threshold = power_threshold
        self._status = SwitchStatus.ERROR
        self.client = httpx.AsyncClient(timeout=5.0)

    @retry(3, httpx.HTTPError)
    async def _get(self, path: str, params: dict | None = None):
        return await self.client.get(f"{self.url}{path}", params=params)

    async def async_update_status(self, switch_id: int = 0):
        """Refresh the cached status.

        Sets SwitchStatus.ERROR (never raises) on any network/parse problem so
        the control loop can hold state until the device recovers.
        """
        try:
            response = await self._get(
                "/rpc/Switch.GetStatus", params={"id": switch_id}
            )
            if response.status_code != 200:
                logger.warning(
                    f"Switch status from {self.url}: HTTP {response.status_code}"
                )
                self._status = SwitchStatus.ERROR
                return
            response_json = response.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning(f"Failed to get switch status from {self.url}: {e}")
            self._status = SwitchStatus.ERROR
            return

        output = response_json.get("output")
        apower = response_json.get("apower")
        if output is None or apower is None:
            logger.warning(
                f"Unexpected switch status payload from {self.url}: {response_json}"
            )
            self._status = SwitchStatus.ERROR
        elif not output:
            self._status = SwitchStatus.OFF
        else:
            self._status = (
                SwitchStatus.IDLE
                if apower <= self.power_threshold
                else SwitchStatus.RUNNING
            )

    @retry(3, httpx.HTTPError)
    async def async_set_switch(self, on: bool, switch_id: int = 0):
        command_url = f"{self.url}/rpc/Switch.Set?id={switch_id}&on={str(on).lower()}"
        response = await self.client.get(command_url)
        if response.status_code != 200:
            raise Exception(f"Failed to set switch state to {on}")

    @property
    def status(self):
        return self._status


async def get_denon():
    d = denonavr.DenonAVR(os.getenv("RECEIVER_IP"))
    await d.async_setup()
    return d


async def startup_receiver(d, tt_input: str, sound_mode: str, volume: float):
    # todo see if we can tighten the timing
    # do we need the delays after boot?
    await d.async_update()
    if d.state != "on":
        await d.async_power_on()
        await asyncio.sleep(10)  # wait for receiver to boot and inputs to be hijacked

    # we sleep inbetween commands to allow the receiver to process them
    await d.async_set_input_func(tt_input)
    await asyncio.sleep(2)
    await d.async_update()  # we want to check the sound mode for the new input

    if d.sound_mode != sound_mode:
        await d.async_set_sound_mode(sound_mode)
        await asyncio.sleep(2)

    await d.async_set_volume(volume)


async def shutdown(d: denonavr.DenonAVR, p: SwitchController, tt_input: str):
    # avoid turning off the preamp if the AMP is on the input to prevent pops
    await d.async_update()
    if d.input_func == tt_input:  # don't turn off if in use by another input
        await d.async_power_off()
        await asyncio.sleep(2)

    await p.async_set_switch(False)


# todo make a class and load all ENVs in the constructor
async def run():
    # Parse all configuration once, up front, so a config problem surfaces
    # immediately and is not re-parsed on every loop iteration.
    tt_input = os.getenv("TT_INPUT")
    sound_mode = os.getenv("SOUND_MODE", "STEREO")
    volume = float(os.getenv("VOLUME"))
    shutdown_delay = int(os.getenv("SHUTDOWN_DELAY"))
    power_threshold = float(os.getenv("POWER_THRESHOLD", "2"))

    tt_switch = SwitchController(os.getenv("TT_URL"), power_threshold)
    pre_switch = SwitchController(os.getenv("PRE_AMP_URL"), power_threshold)

    logger.info("Starting TT control program")

    # Retry the initial receiver connection so a transient network/AVR hiccup at
    # boot does not prevent the program from starting.
    denon = None
    while denon is None:
        try:
            denon = await get_denon()
        except Exception as e:
            logger.warning(f"Failed to connect to receiver, retrying in 10s: {e}")
            await asyncio.sleep(10)

    try:
        await asyncio.gather(
            tt_switch.async_set_switch(True), shutdown(denon, pre_switch, tt_input)
        )
    except Exception as e:
        logger.warning(f"Initial startup/shutdown step failed: {e}")

    db = RecordPlaysDB()
    cur_session_id = db.start_session()

    program_state = ProgramState.IDLE
    # monotonic() (not wall clock) so an NTP correction after boot cannot make
    # elapsed time jump and trigger premature/late transitions.
    state_start = monotonic()
    while True:
        await tt_switch.async_update_status()
        status = tt_switch.status
        old_program_state = program_state
        time_in_state = timedelta(seconds=int(monotonic() - state_start))
        # Check if we need to transition to a new state. ERROR status falls
        # through the RUNNING/STANDBY cases (no transition) so we hold state
        # until the device recovers.
        match (program_state, status):
            case (ProgramState.IDLE, SwitchStatus.RUNNING):
                try:
                    await asyncio.gather(
                        pre_switch.async_set_switch(True),
                        startup_receiver(denon, tt_input, sound_mode, volume),
                    )
                    program_state = ProgramState.RUNNING
                except Exception as e:
                    logger.warning(f"Receiver startup failed, will retry: {e}")
            case (ProgramState.RUNNING, _) if status != SwitchStatus.ERROR:
                if status == SwitchStatus.IDLE:
                    program_state = ProgramState.STANDBY
                    if time_in_state > timedelta(
                        seconds=60
                    ):  # ignore short plays to allow for startup toggles and record cleaning
                        try:
                            db.insert_record_play(time_in_state, cur_session_id)
                            total_playtime = timedelta(seconds=db.get_total_runtime())
                            logger.info(
                                f"Recorded playtime of {time_in_state}, total playtime is {total_playtime}"
                            )
                        except sqlite3.Error as e:
                            logger.warning(f"Failed to record play: {e}")
                elif time_in_state > timedelta(minutes=25):
                    logger.info("Stop the TT!!")
                    # todo create warning mechanism
                    program_state = ProgramState.WARN

            case (ProgramState.STANDBY, _) if status != SwitchStatus.ERROR:
                if status == SwitchStatus.RUNNING:  # resuming playback
                    program_state = ProgramState.RUNNING
                elif time_in_state > timedelta(seconds=shutdown_delay):
                    try:
                        await shutdown(denon, pre_switch, tt_input)
                        program_state = ProgramState.IDLE
                    except Exception as e:
                        logger.warning(f"Receiver shutdown failed, will retry: {e}")
                    if program_state == ProgramState.IDLE:
                        try:
                            session_playtime = timedelta(
                                seconds=db.get_session_runtime(cur_session_id)
                            )
                            logger.info(
                                f"Ended session with playtime of {session_playtime}"
                            )
                        except sqlite3.Error as e:
                            logger.warning(f"Failed to read session runtime: {e}")
                        try:
                            cur_session_id = db.start_session()
                        except sqlite3.Error as e:
                            logger.warning(f"Failed to start new session: {e}")
                            cur_session_id += 1
            case (ProgramState.WARN, SwitchStatus.IDLE):
                # todo turn off warning
                program_state = ProgramState.IDLE

        if program_state != old_program_state:
            state_start = monotonic()
            logger.info(f"Transitioning from {old_program_state} to {program_state}")

        if status == SwitchStatus.ERROR:
            logger.error(
                "Error getting switch status program state will be static until recovery"
            )

        await asyncio.sleep(2)


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S %Z",
    )
    # Reduce httpx logging to only show warnings and errors
    logging.getLogger("httpx").setLevel(logging.WARNING)
    asyncio.run(run())
