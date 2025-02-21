import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from enum import Enum
from time import sleep

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


def send_denon_command(command: str):
    receiver_ip = os.getenv("RECEIVER_IP")
    response = requests.get(
        f"http://{receiver_ip}:8080/goform/formiPhoneAppDirect.xml?{command}"
    )
    if response.status_code != 200:
        raise Exception(
            f"Failed to turn on Denon receiver. Status code: {response.status_code}"
        )


def startup_receiver():
    commands = [
        f"SI{os.getenv('TT_INPUT')}",
        "MSSTEREO",  # Direct modes are toggles set to another mode then target to ensure correct mode
        f"MS{os.getenv('SOUND_MODE')}",
        "MV" + str(80 - int(os.getenv("VOLUME"))),  # 80 = 0DB in Denon
        f"SI{os.getenv('TT_INPUT')}",  # stop other devices from hijacking the input
    ]

    for cmd in commands:
        send_denon_command(cmd)
        sleep(2)


def shutdown_receiver():
    status = get_denon_status()
    if status["InputFuncSelect"] == os.getenv("TT_INPUT"):
        send_denon_command("PWSTANDBY")


def run():
    # turn on TT plug and turn off PreAMP plug
    tt_url = os.getenv("TT_URL")
    pre_url = os.getenv("PRE_AMP_URL")
    set_switch(tt_url, True)
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
                startup_receiver()
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
                    shutdown_receiver()
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

        sleep(5)


def get_denon_status():
    url = f"http://{os.getenv('RECEIVER_IP')}:8080/goform/formMainZone_MainZoneXmlStatusLite.xml"
    response = requests.get(url)
    root = ET.fromstring(response.text)
    status = {
        "PowerOn": root.find("Power")[0].text == "ON",
        "InputFuncSelect": root.find("InputFuncSelect")[0].text,
        "MasterVolume": float(root.find("MasterVolume")[0].text),
        "Mute": root.find("Mute")[0].text != "off",
    }
    return status


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
    run()
