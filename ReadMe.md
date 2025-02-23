# Turntable Home Automation

![Python](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/docker-local-blue?logo=docker&logoColor=white)
![Ruff](https://img.shields.io/badge/ruff-blue?logo=ruff&logoColor=white)
## Motivation
Vinyl playback is already a process and nobody wants to fiddle with multiple devices and settings. 
Additionally, my pre-amp, Schiit Skoll, lacks an accessible power button.
As a bonus we can monitor playback time to infer stylus life.

### Features
* Power on pre-amp when turntable is powered on
* Set receiver to correct input, volume, and sound mode when turntable is powered on
* Power off devices after a delay when turntable is not in use
  * Receiver is not powered off if it is in use by another device
* Record playback time in a SQLite database

This code is unlikely to be of direct use to anyone else but serves as a reference for similar projects.


## Implementation
The TT and PreAMP are connected to Shelly smart plugs with power monitoring.
The receiver is a Denon AVR connected to the network.
Devices are controlled and monitored using HTTP requests.
Additional connectivity on the Shelly devices (Access Point, Cloud, MQTT, Bluetooth) is disabled for security and congestion reasons.

The Python script monitors the state of the TT plug and configures the other devices accordingly.


## Running the Program

### Clone the repository:
 ```sh
 git clone <repository-url>
 cd <repository-directory>
 ```

### Configuration
The following environment variables are required. They can be set in a `.env` file for Python or the Dockerfile for Docker.
Hardcoded values exist in the DockerFile as there's no sensitive information.
See the [denonavr](https://github.com/ol-iver/denonavr/tree/main) package for valid receiver configuration values.

| Variable         | Description                        | Example Value           |
|------------------|------------------------------------|-------------------------|
| `RECEIVER_IP`    | The IP address of your receiver    | `192.168.55.22`         |
| `TT_URL`         | The URL of your turntable plug     | `http://192.168.55.203` |
| `PRE_AMP_URL`    | The URL of your pre-amplifier plug | `http://192.168.55.205` |
| `TT_INPUT`       | The input for the turntable        | `CD`                    |
| `SOUND_MODE`     | The sound mode for the receiver    | `PURE DIRECT`           |
| `VOLUME`         | The volume level for the receiver  | `-30`                   |
| `SHUTDOWN_DELAY` | The shutdown delay in seconds      | `300`                   |
 | `DB_FOLDER`      | The folder to store the database   | `/data`                 |


### Run With Python
```sh
 pip install -r requirements.txt
 python src/main.py
 ```

### Build and Run With Docker
 ```sh
 docker build -t turntable-home-automation:latest .
 docker save -o turntable-home-automation turntable-home-automation:latest # (optional)
 docker run  --volume path/to/db_folder:/data turntable-home-automation:latest
 ```
Note the volume mount required to persist the SQLite database.

## Future Work
* Use Philips Hue to blink lights in warning mode