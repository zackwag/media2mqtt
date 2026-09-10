# media2mqtt

Publishes macOS media app playback state to Home Assistant via MQTT Discovery — currently supports Apple Music and Podcasts. Polls via AppleScript, so it runs natively on the Mac (not in Docker).

## Sensors

Each enabled app gets a `sensor` entity under a shared device in Home Assistant:

| Sensor | State | Attributes |
|---|---|---|
| `sensor.media2mqtt_music` | `playing` / `paused` / `stopped` / `idle` | `track`, `artist`, `album`, `duration`, `is_playing` |
| `sensor.media2mqtt_podcasts` | `playing` / `paused` / `stopped` / `idle` | `episode`, `show`, `is_playing` |

`idle` means the app isn't running. `is_playing` is a boolean for easy automations.

## Requirements

- macOS with Apple Music and/or Podcasts
- Python 3.10+
- MQTT broker (e.g. [Mosquitto](https://mosquitto.org/))
- Home Assistant with MQTT integration enabled

## Install

```bash
./install.sh
```

On first run this creates a `.env` file at `~/.local/share/media2mqtt/.env` — fill in at least `MQTT_HOST`, then run `./install.sh` again to finish setup.

To start the service:

```bash
launchctl load ~/Library/LaunchAgents/com.media2mqtt.plist
```

To check status:

```bash
launchctl list | grep media2mqtt
```

Logs: `~/.local/share/media2mqtt/media2mqtt.log`

## Uninstall

```bash
./uninstall.sh
```

Stops the service, removes the plist, and optionally deletes the install directory.

## Environment Variables

Configured in `~/.local/share/media2mqtt/.env` (created by `install.sh`):

| Variable | Required | Default | Description |
|---|---|---|---|
| `MQTT_HOST` | yes | | MQTT broker IP address |
| `MQTT_PORT` | no | `1883` | MQTT broker port |
| `MQTT_USERNAME` | no | | MQTT broker username |
| `MQTT_PASSWORD` | no | | MQTT broker password |
| `MQTT_DISCOVERY_PREFIX` | no | `homeassistant` | HA discovery topic prefix |
| `MQTT_TOPIC_PREFIX` | no | `media2mqtt` | State/attribute topic prefix |
| `DEVICE_NAME` | no | Mac hostname | Device name in Home Assistant |
| `ENABLED_APPS` | no | `music` | Comma-separated: `music`, `podcasts` |
| `POLL_INTERVAL_SECONDS` | no | `1` | Poll interval in seconds |

## Adding a New App

Subclass `MediaApp` in `media_apps.py`:

```python
class MyApp(MediaApp):
    app_name = "My App"
    bundle_id = "com.example.myapp"

    def poll(self) -> MediaState:
        if not self._app_is_running():
            return MediaState()
        # query state via AppleScript
        return MediaState(player_state=..., is_playing=..., attributes={...})
```

Add it to `AVAILABLE_APPS` at the bottom of the file, then include its key in `ENABLED_APPS`.

## Notes

- **No Docker**: AppleScript requires access to macOS APIs and running app processes, which aren't available in a Docker container (Docker on Mac runs a Linux VM).
- **Network resilience**: if the MQTT broker is unreachable (e.g. travelling away from the LAN), the client retries with backoff up to 60s and reconnects automatically when the broker is available again. No crash, no data loss.
- **1s polling**: the default poll interval is 1 second to catch song transitions promptly. AppleScript calls are lightweight — each poll is two `osascript` invocations (one to check if the app is running, one to read state).

## License

MIT
