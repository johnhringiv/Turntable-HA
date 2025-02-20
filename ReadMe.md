# Turntable Home Automation

![Python](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/docker-local-blue?logo=docker&logoColor=white)
![Ruff](https://img.shields.io/badge/ruff-blue?logo=ruff&logoColor=white)
## Motivation
Vinyl playback is already a process and noby wants to fiddle with multiple devices and settings. 
Additionally, my pre-amp, Schiit Skoll, lacks an accessible power button.

## Overview
This application automates the home theater setup required for turntable (TT) playback.
When the TT is powered on we power on the pre-amplifier (PreAmp) and set the receiver to the correct input, volume, and sound mode.
Devices are powered off after a specified delay when the TT is not in use.

This code is unlikely to be of direct use to anyone else but serves as a reference for similar projects.

## Implementation
The TT and PreAMP are connected to Shelly smart plugs with power monitoring. 
The receiver is a Denon AVR connected to the network.
Devices are controlled and monitored using HTTP requests.


## Running the Program

### Clone the repository:
 ```sh
 git clone <repository-url>
 cd <repository-directory>
 ```

### Configuration
The following environment variables are required. They can be set in a `.env` file for Python or the Dockerfile for Docker.
Hardcoded values exist in the DockerFile as there's no sensitive information.
```env
RECEIVER_IP=<your_receiver_ip>
TT_URL=<your_turntable_url>
PRE_AMP_URL=<your_pre_amp_url>
TT_INPUT=<your_tt_input>
SOUND_MODE=<your_sound_mode>
VOLUME=<your_volume_level>
SHUTDOWN_DELAY=<your_shutdown_delay_in_seconds>
```

### Run With Python
 ```sh
 pip install -r requirements.txt
 python src/main.py
 ```

### Build and Run With Docker
 ```sh
 docker build -t turntable-home-automation .
 docker save -o turntable-home-automation turntable-home-automation # (optional)
 docker run turntable-home-automation
 ```

## Future Work
* Use Philips Hue to blink lights in warning mode
* Record play history (useful for stylus life)