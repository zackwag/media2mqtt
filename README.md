# media2mqtt

Publishes macOS media app playback state to Home Assistant via MQTT Discovery — currently supports Apple Music and Podcasts. Polls via AppleScript, so it runs natively on the Mac (not in Docker).

## Sensors

Each enabled app gets a `sensor` entity under a shared device in Home Assistant. Entity IDs are derived from `DEVICE_NAME`:

| Sensor | State | Attributes |
|---|---|---|
| `sensor.{device_name}_music` | `playing` / `paused` / `stopped` / `idle` | `track`, `artist`, `album`, `duration`, `elapsed`, `is_playing` |
| `sensor.{device_name}_podcasts` | `playing` / `paused` / `stopped` / `idle` | `episode`, `show`, `duration`, `elapsed`, `is_playing` |
| `sensor.{device_name}_now_playing` | `playing` / `paused` / `idle` | `source`, `title`, `subtitle`, `duration`, `elapsed`, `is_playing` |

For example, with `DEVICE_NAME=Zack's Work MacBook`, the entity ID would be `sensor.zacks_work_macbook_music`.

`idle` means the app isn't running (or, for `now_playing`, that nothing is playing or paused). `is_playing` is a boolean for easy automations.

## Playback control

If [`nowplaying-cli`](https://github.com/kirtan-shah/nowplaying-cli) is installed, media2mqtt subscribes to a command topic and forwards commands to it:

```
media2mqtt/{device_name}/command
```

Publish one of these payloads to control playback (works regardless of which app is playing, since `nowplaying-cli` controls the system-level media session):

| Payload | Effect |
|---|---|
| `play` | Resume playback |
| `pause` | Pause playback |
| `togglePlayPause` | Toggle play/pause |
| `next` | Skip to next track |
| `previous` | Skip to previous track |

For example, with `DEVICE_NAME=Zack's Work MacBook`:

```bash
mosquitto_pub -t "media2mqtt/zacks_work_macbook/command" -m "togglePlayPause"
```

If `nowplaying-cli` isn't installed, playback control is skipped (sensors still work). See [Home Assistant Examples](#home-assistant-examples) below for wiring this up as a `media_player` entity with native transport controls.

## Requirements

- macOS with Apple Music and/or Podcasts
- MQTT broker (e.g. [Mosquitto](https://mosquitto.org/))
- Home Assistant with MQTT integration enabled
- [`nowplaying-cli`](https://github.com/kirtan-shah/nowplaying-cli) (`brew install nowplaying-cli`) — required for Podcasts support and for playback control

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

### media_player entity with title, artist, and transport controls (recommended)

Core Home Assistant has no MQTT discovery schema for `media_player` entities, but the [MQTT Media Player](https://github.com/bkbilly/mqtt_media_player) HACS integration adds one. Install it via HACS (it's not in the default store — add `bkbilly/mqtt_media_player` as a custom repository), and as long as `MQTT_DISCOVERY_PREFIX` is left at its default `homeassistant`, media2mqtt auto-publishes discovery for a real `media_player` entity whenever [playback control](#playback-control) is enabled (i.e. `nowplaying-cli` is installed) — no YAML required. It shows up on the same HA device as the sensors, with live title/artist/duration/position and working play/pause/next/previous controls.

If `MQTT_DISCOVERY_PREFIX` is customized, this integration won't find it — it listens on a hardcoded `homeassistant/media_player/#` topic regardless of that setting.

### media_player entity with transport controls only

If you'd rather not install a third-party integration, the built-in [Universal Media Player](https://www.home-assistant.io/integrations/universal/) platform can wrap the `now_playing` sensor and map its actions back onto the [command topic](#playback-control) via `mqtt.publish`. **This gets you working play/pause/next/previous controls, but not title/artist** — Universal Media Player only lets `attributes:` override a specific subset of properties (`volume_level`, `source`, `sound_mode`, `shuffle`, `repeat`, and a few others), and `media_title`/`media_artist`/`media_duration`/`media_position`/`app_name` aren't in it; those can only come from a real `media_player` child entity. Add to `configuration.yaml`:

```yaml
media_player:
  - platform: universal
    name: "Zack's Work MacBook"
    unique_id: zacks_work_macbook_media_player
    state_template: "{{ states('sensor.zacks_work_macbook_now_playing') }}"
    commands:
      media_play:
        action: mqtt.publish
        data:
          topic: media2mqtt/zacks_work_macbook/command
          payload: play
      media_pause:
        action: mqtt.publish
        data:
          topic: media2mqtt/zacks_work_macbook/command
          payload: pause
      media_play_pause:
        action: mqtt.publish
        data:
          topic: media2mqtt/zacks_work_macbook/command
          payload: togglePlayPause
      media_next_track:
        action: mqtt.publish
        data:
          topic: media2mqtt/zacks_work_macbook/command
          payload: next
      media_previous_track:
        action: mqtt.publish
        data:
          topic: media2mqtt/zacks_work_macbook/command
          payload: previous
```

Replace `zacks_work_macbook` with your device's slug (see [Sensors](#sensors) above).

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
alias: Now Playing - Start/Update Live Activity
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
  - delay: '00:00:01'
  - action: notify.mobile_app_<your_iphone>
    data:
      title: "{{ state_attr('sensor.now_playing', 'title') }}{% if state_attr('sensor.now_playing', 'subtitle') %} — {{ state_attr('sensor.now_playing', 'subtitle') }}{% endif %}"
      message: Now Playing
      data:
        tag: now-playing
        live_update: true
        chronometer: true
        when: "{{ ((state_attr('sensor.now_playing', 'duration') | float(0)) - (state_attr('sensor.now_playing', 'elapsed') | float(0))) | int }}"
        when_relative: true
        notification_icon: "{% if state_attr('sensor.now_playing', 'source') == 'Music' %}mdi:music-note{% else %}mdi:podcast{% endif %}"
        notification_icon_color: "{% if state_attr('sensor.now_playing', 'source') == 'Music' %}#FC3C44{% else %}#8E4EC6{% endif %}"
mode: restart
```

Replace `<your_iphone>` with your device name from **Settings > Companion App > Server & devices** in HA.

This renders similar to

<img width="1311" height="603" alt="Image" src="https://github.com/user-attachments/assets/37cb2eaa-ff33-415b-a399-c0d551f90794" />

Additionally, you probably want an activity to clear on pause/stop:

```yaml
alias: Now Playing - End Live Activity
triggers:
  - trigger: state
    entity_id: sensor.now_playing
    from: playing
actions:
  - action: notify.mobile_app_zack_wagner_s_iphone
    data:
      message: clear_notification
      data:
        tag: now-playing
```

## Notes

- **No Docker**: AppleScript requires access to macOS APIs and running app processes, which aren't available in a Docker container (Docker on Mac runs a Linux VM).
- **Network resilience**: if the MQTT broker is unreachable (e.g. travelling away from the LAN), the client retries with backoff up to 60s and reconnects automatically when the broker is available again. No crash, no data loss.
- **1s polling**: the default poll interval is 1 second to catch song transitions promptly. AppleScript calls are lightweight — each poll is two `osascript` invocations (one to check if the app is running, one to read state).

## License

MIT
