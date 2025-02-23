import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from enum import Enum
from time import sleep

import denonavr
import requests

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


def set_switch(url: str, on: bool, switch_id: int = 0):
    command_url = f"{url}/rpc/Switch.Set?id={switch_id}&on={str(on).lower()}"
    response = requests.get(command_url)
    if response.status_code != 200:
        raise Exception(f"Failed to set switch state to {on}")


def get_switch_status(url: str, switch_id: int = 0) -> SwitchStatus:
    response = requests.get(f"{url}/rpc/Switch.GetStatus", {"id": switch_id})
    response_json = response.json()
    if response.status_code != 200:
        return SwitchStatus.ERROR
    elif not response_json["output"]:
        return SwitchStatus.OFF
    else:
        return (
            SwitchStatus.IDLE if response_json["apower"] == 0 else SwitchStatus.RUNNING
        )


async def get_denon():
    d = denonavr.DenonAVR(os.getenv("RECEIVER_IP"))
    await d.async_setup()
    await d.async_update()
    return d


async def startup_receiver(d):
    # todo see if we can tighten the timing
    # do we need the delays after boot?
    await d.async_power_on()
    await asyncio.sleep(10)  # wait for receiver to boot and inputs to be hijacked

    # we sleep inbetween commands to allow the receiver to process them
    await d.async_set_input_func(os.getenv("TT_INPUT"))
    await asyncio.sleep(2)
    await d.async_update()  # we want to check the sound mode for the new input

    if d.sound_mode != os.getenv("SOUND_MODE"):  # todo change in Env
        await d.async_set_sound_mode(os.getenv("SOUND_MODE"))
        await asyncio.sleep(2)

    await d.async_set_volume(float(os.getenv("VOLUME")))  # todo change in Env


async def shutdown_receiver(d: denonavr.DenonAVR):
    await d.async_update()
    if d.input_func == os.getenv("TT_INPUT"):
        await d.async_power_off()


async def run():
    tt_url = os.getenv("TT_URL")
    pre_url = os.getenv("PRE_AMP_URL")
    set_switch(tt_url, True)

    # avoid turning off the preamp if the AMP is on the input to prevent pops
    denon = await get_denon()
    await shutdown_receiver(denon)
    set_switch(pre_url, False)

    logger = logging.getLogger()
    logger.info("Starting TT control program")

    db = RecordPlaysDB()
    cur_session_id = db.get_next_session_id()

    program_state = ProgramState.IDLE
    state_start = datetime.now(timezone.utc)
    while True:
        status = get_switch_status(tt_url)
        old_program_state = program_state
        time_in_state = timedelta(
            seconds=int((datetime.now(timezone.utc) - state_start).total_seconds())
        )
        # Check if we need to transition to a new state
        match (program_state, status):
            case (ProgramState.IDLE, SwitchStatus.RUNNING):
                set_switch(pre_url, True)
                await startup_receiver(denon)
                program_state = ProgramState.RUNNING
            case (ProgramState.RUNNING, _):
                if status == SwitchStatus.IDLE:
                    program_state = ProgramState.STANDBY
                    if time_in_state > timedelta(
                        seconds=60
                    ):  # ignore short plays to allow for startup toggles
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
                if status == SwitchStatus.RUNNING:  # resuming playback
                    program_state = ProgramState.RUNNING
                elif time_in_state > timedelta(
                    seconds=int(os.getenv("SHUTDOWN_DELAY"))
                ):
                    await shutdown_receiver(denon)
                    set_switch(pre_url, False)
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

        if status == SwitchStatus.ERROR:
            logger.error(
                "Error getting switch status program state will be static until recovery"
            )

        sleep(2)


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
    asyncio.run(run())
