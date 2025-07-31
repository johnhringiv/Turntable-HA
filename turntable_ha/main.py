import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import wraps

import denonavr
import httpx
from record_plays_db import RecordPlaysDB


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
    def __init__(self, url: str):
        self.url = url
        self._status = None
        self.client = httpx.AsyncClient(timeout=5.0)

    @retry(3, httpx.TimeoutException)
    async def async_update_status(self, switch_id: int = 0):
        response = await self.client.get(
            f"{self.url}/rpc/Switch.GetStatus", params={"id": switch_id}
        )
        response_json = response.json()
        if response.status_code != 200:
            self._status = SwitchStatus.ERROR
        elif not response_json["output"]:
            self._status = SwitchStatus.OFF
        else:
            self._status = (
                SwitchStatus.IDLE
                if response_json["apower"] == 0
                else SwitchStatus.RUNNING
            )

    @retry(3, httpx.TimeoutException)
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


async def startup_receiver(d):
    # todo see if we can tighten the timing
    # do we need the delays after boot?
    await d.async_update()
    if d.state != "on":
        await d.async_power_on()
        await asyncio.sleep(10)  # wait for receiver to boot and inputs to be hijacked

    # we sleep inbetween commands to allow the receiver to process them
    await d.async_set_input_func(os.getenv("TT_INPUT"))
    await asyncio.sleep(2)
    await d.async_update()  # we want to check the sound mode for the new input

    if d.sound_mode != os.getenv("SOUND_MODE"):
        await d.async_set_sound_mode(os.getenv("SOUND_MODE"))
        await asyncio.sleep(2)

    await d.async_set_volume(float(os.getenv("VOLUME")))


async def shutdown(d: denonavr.DenonAVR, p: SwitchController):
    # avoid turning off the preamp if the AMP is on the input to prevent pops
    await d.async_update()
    if d.input_func == os.getenv(
        "TT_INPUT"
    ):  # don't turn off if in use by another input
        await d.async_power_off()
        await asyncio.sleep(2)

    await p.async_set_switch(False)


# todo make a class and load all ENVs in the constructor
async def run():
    tt_switch = SwitchController(os.getenv("TT_URL"))
    pre_switch = SwitchController(os.getenv("PRE_AMP_URL"))

    denon = await get_denon()
    await asyncio.gather(tt_switch.async_set_switch(True), shutdown(denon, pre_switch))

    logger = logging.getLogger()
    logger.info("Starting TT control program")

    db = RecordPlaysDB()
    cur_session_id = db.get_next_session_id()

    program_state = ProgramState.IDLE
    state_start = datetime.now(timezone.utc)
    while True:
        await tt_switch.async_update_status()
        old_program_state = program_state
        time_in_state = timedelta(
            seconds=int((datetime.now(timezone.utc) - state_start).total_seconds())
        )
        # Check if we need to transition to a new state
        match (program_state, tt_switch.status):
            case (ProgramState.IDLE, SwitchStatus.RUNNING):
                await asyncio.gather(
                    pre_switch.async_set_switch(True), startup_receiver(denon)
                )
                program_state = ProgramState.RUNNING
            case (ProgramState.RUNNING, _):
                if tt_switch.status == SwitchStatus.IDLE:
                    program_state = ProgramState.STANDBY
                    if (
                        time_in_state > timedelta(seconds=60)
                    ):  # ignore short plays to allow for startup toggles and record cleaning
                        db.insert_record_play(time_in_state, cur_session_id)
                        total_playtime = timedelta(seconds=db.get_total_runtime())
                        logger.info(
                            f"Recorded playtime of {time_in_state}, total playtime is {total_playtime}"
                        )
                elif time_in_state > timedelta(minutes=25):
                    logger.info("Stop the TT!!")
                    # todo create warning mechanism
                    program_state = ProgramState.WARN

            case (ProgramState.STANDBY, _):
                if tt_switch.status == SwitchStatus.RUNNING:  # resuming playback
                    program_state = ProgramState.RUNNING
                elif time_in_state > timedelta(
                    seconds=int(os.getenv("SHUTDOWN_DELAY"))
                ):
                    await shutdown(denon, pre_switch)
                    session_playtime = timedelta(
                        seconds=db.get_session_runtime(cur_session_id)
                    )
                    logger.info(f"Ended session with playtime of {session_playtime}")
                    cur_session_id += 1
                    program_state = ProgramState.IDLE
            case (ProgramState.WARN, SwitchStatus.IDLE):
                # todo turn off warning
                program_state = ProgramState.IDLE

        if program_state != old_program_state:
            state_start = datetime.now(timezone.utc)
            logger.info(f"Transitioning from {old_program_state} to {program_state}")

        if tt_switch.status == SwitchStatus.ERROR:
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
