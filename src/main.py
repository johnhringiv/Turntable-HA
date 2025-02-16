import os
import logging
from datetime import datetime, timedelta

from enum import Enum
from time import sleep, time

import requests


# startup: TT Plug on, PreAMP Plug off (output state)

class SwitchStatus(Enum):
    ERROR = 0
    OFF = 1
    IDLE = 2
    RUNNING = 3


class PROGRAM_STATE(Enum):
    ERROR = 0
    IDLE = 1
    STARTUP = 2
    RUNNING = 3
    WARN_SETUP = 4 # not needed
    # if we have warn setup we'd also need warn shutdown
    WARN = 5
    STANDBY = 6
    SHUTDOWN = 7

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

# def send_denon_command(command: str):
#     receiver_url = os.getenv("RECEIVER_URL")
#     timestamp = time() * 1000
#     command_url = f"{receiver_url}/ajax/globals/set_config?{command}&_={timestamp}"
#     response = requests.get(command_url, verify=False)
#     if response.status_code != 200:
#         raise Exception(f"Failed to turn on Denon receiver. Status code: {response.status_code}")
def send_denon_command(command: str):
    receiver_ip = os.getenv("RECEIVER_IP")
    response = requests.get(f"http://{receiver_ip}:8080/goform/formiPhoneAppDirect.xml?{command}")
    print(response.text)
    if response.status_code != 200:
        raise Exception(f"Failed to turn on Denon receiver. Status code: {response.status_code}")

def startup_receiver():
    for cmd in ["PWON", "SICD", "MV45", "MSPURE%20DIRECT"]:
        send_denon_command(cmd)
    # power_on = "type=4&data=<MainZone><Power>1</Power></MainZone>" # 3 is off
    # send_denon_command(power_on)
    # sleep(2)

    # todo mode = prue direct, volume = 45
    # change_input_url = f'https://192.168.55.22:10443/ajax/globals/set_config?type=7&data=%3CSource%20zone%3D%221%22%20index%3D%229%22%3E%3C%2FSource%3E&_={timestamp}'
    # set_input_cd = 'type=7&data=<Source zone="1" index="9"></Source>'
    # volume = 'type=7&data=<MasterVolume><Value>45</Value></MasterVolume>'
    # send_denon_command(set_input_cd)
    # send_denon_command(volume)

def shutdown_receiver():
    # todo skip if input is not CD
    send_denon_command("PWSTANDBY")
    # power_off = "type=4&data=<MainZone><Power>1</Power></MainZone>"
    # send_denon_command(power_off)
#
# http://192.168.55.22:8080/goform/formiPhoneAppDirect.xml?SICD
# http://192.168.55.22:8080/goform/formiPhoneAppDirect.xml?MV45
#http://192.168.55.22:8080/goform/formiPhoneAppDirect.xml?MSPURE%20DIRECT
#todo add disconnect recovery
def run():
    # turn on TT plug and turn off PreAMP plug
    set_switch(tt_url, True)
    set_switch(amp_url, False)
    run_start = datetime.now() # todo might be cleaner to set this to last state change time
    logger = logging.getLogger()

    # if we want to keep the tranisitions seperate from actions we can make action enum
    # actions: None, Startup, Start Warn, Stop Warn, Shutdown
    program_state = PROGRAM_STATE.IDLE
    while True:
        status = get_switch_status(tt_url)
        old_program_state = program_state
        # Check if we need to transition to a new state
        match program_state:
            case PROGRAM_STATE.IDLE:
                if status == SwitchStatus.RUNNING:
                    # todo put startup code here change state to running
                    program_state = PROGRAM_STATE.STARTUP
            case PROGRAM_STATE.RUNNING:
                if status == SwitchStatus.IDLE:
                    program_state = PROGRAM_STATE.STANDBY
                elif datetime.now() - run_start > timedelta(minutes=25):
                    # todo put warn code here change state to warn
                    program_state = PROGRAM_STATE.WARN_SETUP
            case PROGRAM_STATE.STANDBY:
                # resuming playback
                if status == SwitchStatus.RUNNING:
                    # todo reset run start
                    program_state = PROGRAM_STATE.RUNNING
                # todo this check seems wong
                elif datetime.now() - run_start > timedelta(seconds=int(os.getenv("SHUTDOWN_DELAY"))):
                    #todo do shutdown here set state to idle
                    program_state = PROGRAM_STATE.SHUTDOWN
            case PROGRAM_STATE.WARN:
                if status == SwitchStatus.IDLE:
                    # todo turn off warning
                    program_state = PROGRAM_STATE.IDLE

        if program_state != old_program_state:
            logger.info(f"Transitioning from {old_program_state} to {program_state}")


        # Perform state actions
        match program_state:
            case PROGRAM_STATE.STARTUP:
                # todo start denon
                set_switch(amp_url, True)
                run_start = datetime.now()
                program_state = PROGRAM_STATE.RUNNING
                logger.info("Started preamp")
            case PROGRAM_STATE.SHUTDOWN:
                # todo shutdown denon
                set_switch(amp_url, False)
                logger.info("Shutdown preamp")
        sleep(5)

def get_denon_status():
    url = f"http://{os.getenv('RECEIVER_IP')}:8080/goform/formMainZone_MainZoneXmlStatusLite.xml"
    response = requests.get(url)
    import xml.etree.ElementTree as ET
    print(response.text)
    root = ET.fromstring(response.text)
    # root = tree.find("Power")
    for x in root.find("Power"):
        print(x.text)
    # print(response.json())

if __name__ == '__main__':
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    #log to stdout
    logging.basicConfig(level=logging.INFO)
    amp_url = os.getenv("PRE_AMP_URL")
    tt_url = os.getenv("TT_URL")
    get_denon_status()