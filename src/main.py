import os
import logging
from datetime import datetime, timedelta
import xml.etree.ElementTree as ET

from enum import Enum
from time import sleep

import requests


class SwitchStatus(Enum):
    ERROR = 0
    OFF = 1
    IDLE = 2
    RUNNING = 3


class PROGRAM_STATE(Enum):
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

def get_switch_status(url: str, switch_id: int = 0):
    response = requests.get(f"{url}/rpc/Switch.GetStatus", {"id": switch_id})
    response_json = response.json()
    if response.status_code != 200:
        return SwitchStatus.ERROR
    elif not response_json["output"]:
        return SwitchStatus.OFF
    else:
        return SwitchStatus.IDLE if response_json["apower"] == 0 else SwitchStatus.RUNNING


def send_denon_command(command: str):
    receiver_ip = os.getenv("RECEIVER_IP")
    response = requests.get(f"http://{receiver_ip}:8080/goform/formiPhoneAppDirect.xml?{command}")
    print(response.url)
    if response.status_code != 200:
        raise Exception(f"Failed to turn on Denon receiver. Status code: {response.status_code}")

def startup_receiver():
    commands = [
        f"SI{os.getenv('TT_INPUT')}",
        "MSSTEREO",  # Direct modes are toggles set to another mode then target to ensure correct mode
        f"MS{os.getenv("SOUND_MODE")}",
        "MV" + str(80 - int(os.getenv("VOLUME"))), # 80 = 0DB in Denon
        f"SI{os.getenv('TT_INPUT')}",
    ]

    for cmd in commands:
        send_denon_command(cmd)
        sleep(2)

def shutdown_receiver():
    status = get_denon_status()
    if status["InputFuncSelect"] == os.getenv("TT_INPUT"):
        send_denon_command("PWSTANDBY")


#todo add disconnect recovery
def run():
    # turn on TT plug and turn off PreAMP plug
    tt_url = os.getenv("TT_URL")
    pre_url = os.getenv("PRE_AMP_URL")
    set_switch(tt_url, True)
    set_switch(pre_url, False)
    logger = logging.getLogger()
    logger.info("Starting TT control program")

    program_state = PROGRAM_STATE.IDLE
    state_start = datetime.now()
    while True:
        status = get_switch_status(tt_url)
        old_program_state = program_state
        # Check if we need to transition to a new state
        match program_state:
            case PROGRAM_STATE.IDLE:
                if status == SwitchStatus.RUNNING:
                    startup_receiver()
                    set_switch(pre_url, True)
                    program_state = PROGRAM_STATE.RUNNING
            case PROGRAM_STATE.RUNNING:
                if status == SwitchStatus.IDLE:
                    program_state = PROGRAM_STATE.STANDBY
                elif datetime.now() - state_start > timedelta(minutes=25):
                    logger.info("Stop the TT!!")
                    # todo create warning mechanism
                    program_state = PROGRAM_STATE.WARN
            case PROGRAM_STATE.STANDBY:
                if status == SwitchStatus.RUNNING: # resuming playback
                    state_start = datetime.now()
                    program_state = PROGRAM_STATE.RUNNING
                elif datetime.now() - state_start > timedelta(seconds=int(os.getenv("SHUTDOWN_DELAY"))):
                    shutdown_receiver()
                    set_switch(pre_url, False)
                    program_state = PROGRAM_STATE.IDLE
            case PROGRAM_STATE.WARN:
                if status == SwitchStatus.IDLE:
                    # todo turn off warning
                    program_state = PROGRAM_STATE.IDLE

        if program_state != old_program_state:
            state_start = datetime.now()
            logger.info(f"Transitioning from {old_program_state} to {program_state}")

        sleep(5)

def get_denon_status():
    url = f"http://{os.getenv('RECEIVER_IP')}:8080/goform/formMainZone_MainZoneXmlStatusLite.xml"
    response = requests.get(url)
    root = ET.fromstring(response.text)
    print(response.text)
    status = {
        "PowerOn": root.find("Power")[0].text == "ON",
        "InputFuncSelect": root.find("InputFuncSelect")[0].text,
        "MasterVolume": float(root.find("MasterVolume")[0].text),
        "Mute": root.find("Mute")[0].text != 'off'
    }
    return status

if __name__ == '__main__':
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    run()
