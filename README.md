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
| `LASTFM_API_KEY` | no | | Last.fm API key — set all three `LASTFM_*` vars to enable [scrobbling](#scrobbling) |
| `LASTFM_API_SECRET` | no | | Last.fm API secret |
| `LASTFM_SESSION_KEY` | no | | Last.fm session key (see [Scrobbling](#scrobbling) for how to get one) |

## Scrobbling

If `LASTFM_API_KEY`, `LASTFM_API_SECRET`, and `LASTFM_SESSION_KEY` are all set, media2mqtt sends a now-playing update to Last.fm as soon as a track starts, then scrobbles it once playback passes the halfway point or 4 minutes (whichever comes first) — the same threshold Last.fm's own clients use. Tracks under 30 seconds are never scrobbled.

Scrobbling is per-app: only apps whose adapter opts in (`scrobble = True` in `media_apps.py`) participate. Music does; Podcasts doesn't, since Last.fm scrobbles are for music tracks (artist/track/album), not podcast episodes.

### Getting a session key

Last.fm's API needs a one-time authorization step to mint a session key — there's no username/password to put in config. Run this once, from the Mac (or anywhere with Python):

1. Create an API account at https://www.last.fm/api/account/create to get an API key and secret.
2. Run:
   ```bash
   python3 lastfm_auth.py <api_key> <api_secret>
   ```
3. It prints a URL. Open it on any device — the Mac itself, or your phone if media2mqtt runs headlessly — and approve access. Last.fm has no way to call back to a script, so the tool polls in the background until it sees the approval, then prints a `LASTFM_SESSION_KEY` to paste into your config alongside the key and secret.

## Adding a New App

Subclass `MediaApp` in `media_apps.py`:

```python
class MyApp(MediaApp):
    app_name = "My App"
    bundle_id = "com.example.myapp"
    scrobble = False  # only relevant for music-like apps; defaults to True

    def poll(self) -> MediaState:
        if not self._app_is_running():
            return MediaState()
        # query state via AppleScript
        return MediaState(player_state=..., is_playing=..., attributes={...})
```

Add it to `AVAILABLE_APPS` at the bottom of the file, then include its key in `ENABLED_APPS`.

## Home Assistant Examples

### media_player entity with title, artist, and transport controls (recommended)

Core Home Assistant has no MQTT discovery schema for `media_player` entities, but the [MQTT Media Player](https://github.com/bkbilly/mqtt_media_player) HACS integration adds one. Install it via HACS (it's not in the default store — add `bkbilly/mqtt_media_player` as a custom repository), and as long as `MQTT_DISCOVERY_PREFIX` is left at its default `homeassistant`, media2mqtt auto-publishes discovery for a real `media_player` entity whenever [playback control](#playback-control) is enabled (i.e. `nowplaying-cli` is installed) — no YAML required. It shows up on the same HA device as the sensors, with live title/artist/album art/duration/position and working play/pause/next/previous controls.

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

### Grouped media_player (multi-Mac)

If you run media2mqtt on multiple Macs, the coordinator aggregates all of them into a single `media_player` entity with album art and transport controls. It auto-discovers devices via retained MQTT discovery messages — no manual device list needed.

The coordinator has no macOS dependencies and can run on any machine with MQTT access (including the HA host itself).

```bash
python3 coordinator.py
```

| Variable | Required | Default | Description |
|---|---|---|---|
| `MQTT_HOST` | yes | | MQTT broker IP address |
| `MQTT_PORT` | no | `1883` | MQTT broker port |
| `MQTT_USERNAME` | no | | MQTT broker username |
| `MQTT_PASSWORD` | no | | MQTT broker password |
| `MQTT_DISCOVERY_PREFIX` | no | `homeassistant` | HA discovery topic prefix |
| `MQTT_TOPIC_PREFIX` | no | `media2mqtt` | State/attribute topic prefix |
| `GROUP_NAME` | no | `Now Playing` | Display name of the grouped entity |
| `GROUP_DEVICE_NAME` | no | `media2mqtt` | Device name in HA device registry |

The grouped entity uses sticky priority: it shows whichever Mac is currently playing. If nothing is playing, it falls back to paused, then idle. Transport commands (play/pause/next/previous) are routed to the active Mac. A `sensor.media2mqtt_source` entity on the same device shows which Mac is currently active.

### iOS Live Activity

Show what's playing on your iPhone lock screen and Dynamic Island using the HA Companion App. This example uses the [grouped media_player](#grouped-media_player-multi-mac) entity, but works with any per-device media_player entity too — just change the `entity_id`.

```yaml
alias: Now Playing - Start/Update Live Activity
triggers:
  - trigger: state
    entity_id: media_player.media2mqtt_now_playing
    to: playing
  - trigger: state
    entity_id: media_player.media2mqtt_now_playing
    attribute: media_title
conditions:
  - condition: state
    entity_id: media_player.media2mqtt_now_playing
    state: playing
actions:
  - delay: '00:00:01'
  - action: notify.mobile_app_<your_iphone>
    data:
      title: "{{ state_attr('media_player.media2mqtt_now_playing', 'media_title') }}{% if state_attr('media_player.media2mqtt_now_playing', 'media_artist') %} — {{ state_attr('media_player.media2mqtt_now_playing', 'media_artist') }}{% endif %}"
      message: Now Playing
      data:
        tag: now-playing
        live_update: true
        chronometer: true
        when: "{{ ((state_attr('media_player.media2mqtt_now_playing', 'media_duration') | float(0)) - (state_attr('media_player.media2mqtt_now_playing', 'media_position') | float(0))) | int }}"
        when_relative: true
        notification_icon: "{% if state_attr('media_player.media2mqtt_now_playing', 'media_content_type') == 'music' %}mdi:music-note{% else %}mdi:podcast{% endif %}"
        notification_icon_color: "{% if state_attr('media_player.media2mqtt_now_playing', 'media_content_type') == 'music' %}#FC3C44{% else %}#8E4EC6{% endif %}"
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
    entity_id: media_player.media2mqtt_now_playing
    from: playing
actions:
  - action: notify.mobile_app_<your_iphone>
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
