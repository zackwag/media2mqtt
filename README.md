# media2mqtt

Publishes macOS media app playback state to Home Assistant via MQTT Discovery — currently supports Apple Music and Podcasts. Polls via AppleScript, so it runs natively on the Mac (not in Docker).

## Sensors

Each enabled app gets a `sensor` entity under a shared device in Home Assistant. Entity IDs are derived from `DEVICE_NAME`:

| Sensor | State | Attributes |
|---|---|---|
| `sensor.{device_name}_music` | `playing` / `paused` / `stopped` / `idle` | `track`, `artist`, `album`, `duration`, `elapsed`, `is_playing` |
| `sensor.{device_name}_podcasts` | `playing` / `paused` / `stopped` / `idle` | `episode`, `show`, `duration`, `elapsed`, `is_playing` |
| `sensor.{device_name}_now_playing` | `playing` / `idle` | `source`, `title`, `subtitle`, `duration`, `elapsed`, `is_playing` |

For example, with `DEVICE_NAME=Zack's Work MacBook`, the entity ID would be `sensor.zacks_work_macbook_music`.

`idle` means the app isn't running. `is_playing` is a boolean for easy automations.

## Requirements

- macOS with Apple Music and/or Podcasts
- MQTT broker (e.g. [Mosquitto](https://mosquitto.org/))
- Home Assistant with MQTT integration enabled

## Install

```bash
brew install zackwag/tap/media2mqtt
```

Edit the config with your MQTT broker details:

```bash
nano /opt/homebrew/etc/media2mqtt/config
```

Start the service:

```bash
brew services start media2mqtt
```

That's it. The service runs at login and restarts automatically.

```bash
brew services stop media2mqtt     # stop
brew services restart media2mqtt  # restart
brew upgrade media2mqtt           # upgrade
```

Logs: `/opt/homebrew/var/log/media2mqtt.log`

### Manual Install

If you prefer not to use Homebrew, `install.sh` and `uninstall.sh` are included for manual setup via launchd.

## Configuration

Located at `/opt/homebrew/etc/media2mqtt/config` (Homebrew) or `~/.local/share/media2mqtt/.env` (manual):

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

## Home Assistant Examples

### Grouped Now Playing sensor

If you run media2mqtt on multiple Macs, a template sensor can aggregate them into a single "Now Playing" entity. Add to `configuration.yaml`:

```yaml
template:
  - sensor:
      - name: "Now Playing"
        icon: mdi:play-circle
        state: >
          {% set sensors = [
            states('sensor.office_mac_mini_now_playing'),
            states('sensor.zacks_work_macbook_now_playing'),
          ] %}
          {% if 'playing' in sensors %}
            playing
          {% else %}
            idle
          {% endif %}
        attributes:
          source: >
            {% if is_state('sensor.office_mac_mini_now_playing', 'playing') %}
              {{ state_attr('sensor.office_mac_mini_now_playing', 'source') }}
            {% elif is_state('sensor.zacks_work_macbook_now_playing', 'playing') %}
              {{ state_attr('sensor.zacks_work_macbook_now_playing', 'source') }}
            {% endif %}
          device: >
            {% if is_state('sensor.office_mac_mini_now_playing', 'playing') %}
              Office Mac Mini
            {% elif is_state('sensor.zacks_work_macbook_now_playing', 'playing') %}
              Zack's Work MacBook
            {% endif %}
          title: >
            {% if is_state('sensor.office_mac_mini_now_playing', 'playing') %}
              {{ state_attr('sensor.office_mac_mini_now_playing', 'title') }}
            {% elif is_state('sensor.zacks_work_macbook_now_playing', 'playing') %}
              {{ state_attr('sensor.zacks_work_macbook_now_playing', 'title') }}
            {% endif %}
          subtitle: >
            {% if is_state('sensor.office_mac_mini_now_playing', 'playing') %}
              {{ state_attr('sensor.office_mac_mini_now_playing', 'subtitle') }}
            {% elif is_state('sensor.zacks_work_macbook_now_playing', 'playing') %}
              {{ state_attr('sensor.zacks_work_macbook_now_playing', 'subtitle') }}
            {% endif %}
```

The first device listed takes priority when both are playing simultaneously.

### iOS Live Activity

Show what's playing on your iPhone lock screen and Dynamic Island using the HA Companion App:

```yaml
automation:
  - alias: "Now Playing - Start/Update Live Activity"
    mode: restart
    triggers:
      - trigger: state
        entity_id: sensor.now_playing
        to: playing
      - trigger: state
        entity_id: sensor.now_playing
        attribute: title
      - trigger: state
        entity_id: sensor.now_playing
        attribute: source
    conditions:
      - condition: state
        entity_id: sensor.now_playing
        state: playing
    actions:
      - delay: "00:00:01"
      - action: notify.mobile_app_<your_iphone>
        data:
          title: Now Playing
          message: >-
            {% set t = state_attr('sensor.now_playing', 'title') %}
            {%- set a = state_attr('sensor.now_playing', 'subtitle') -%}
            {{ t }}{% if a %} — {{ a }}{% endif %}
          data:
            tag: now-playing
            live_update: true
            notification_icon: >
              {% if state_attr('sensor.now_playing', 'source') == 'Music' %}
                mdi:music
              {% else %}
                mdi:podcast
              {% endif %}
            notification_icon_color: >
              {% if state_attr('sensor.now_playing', 'source') == 'Music' %}
                #FC3C44
              {% else %}
                #8E4EC6
              {% endif %}
            progress: >
              {{ state_attr('sensor.now_playing', 'elapsed') | float(0) | round(0) | int }}
            progress_max: >
              {{ state_attr('sensor.now_playing', 'duration') | float(0) | round(0) | int }}

  - alias: "Now Playing - End Live Activity"
    triggers:
      - trigger: state
        entity_id: sensor.now_playing
        from: playing
    actions:
      - action: notify.mobile_app_<your_iphone>
        data:
          message: clear_notification
          data:
            tag: now-playing
```

Replace `<your_iphone>` with your device name from **Settings > Companion App > Server & devices** in HA.

## Notes

- **No Docker**: AppleScript requires access to macOS APIs and running app processes, which aren't available in a Docker container (Docker on Mac runs a Linux VM).
- **Network resilience**: if the MQTT broker is unreachable (e.g. travelling away from the LAN), the client retries with backoff up to 60s and reconnects automatically when the broker is available again. No crash, no data loss.
- **1s polling**: the default poll interval is 1 second to catch song transitions promptly. AppleScript calls are lightweight — each poll is two `osascript` invocations (one to check if the app is running, one to read state).

## License

MIT
