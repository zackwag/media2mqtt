"""media2mqtt: publishes macOS media app state to Home Assistant via MQTT.

Env vars:
  MQTT_HOST                 required
  MQTT_PORT                 optional, default 1883
  MQTT_USERNAME             optional
  MQTT_PASSWORD             optional
  MQTT_DISCOVERY_PREFIX     optional, default "homeassistant"
  MQTT_TOPIC_PREFIX         optional, default "media2mqtt"
  DEVICE_NAME               optional, default is the Mac's hostname
  ENABLED_APPS              optional, comma-separated, default "music"
                            choices: music, podcasts
  POLL_INTERVAL_SECONDS     optional, default 1

Playback control:
  If nowplaying-cli is installed (`brew install nowplaying-cli`), media2mqtt
  subscribes to a command topic (MQTT_TOPIC_PREFIX/{device}/command) and runs
  play/pause/togglePlayPause/next/previous against it. nowplaying-cli controls
  playback at the system level, so this works regardless of which app is
  playing. If it's not installed, playback control is skipped and only
  sensors are published.

  When playback control is enabled, media2mqtt also publishes MQTT discovery
  for a real `media_player` entity (title/artist/transport controls) via the
  "MQTT Media Player" HACS integration: https://github.com/bkbilly/mqtt_media_player
  Core Home Assistant has no native MQTT discovery schema for media_player, so
  this requires that third-party integration to be installed, and only works
  when MQTT_DISCOVERY_PREFIX is left at its default "homeassistant".
"""

from __future__ import annotations

import logging
import os
import platform
import sys
import time

from media_apps import AVAILABLE_APPS, MediaState, find_nowplaying_cli, get_artwork_b64
from mqtt_publisher import MqttPublisher
from playback_control import PlaybackController

_TITLE_KEYS = {"music": "track", "podcasts": "episode"}
_MEDIA_TYPES = {"music": "music", "podcasts": "podcast"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger("media2mqtt")


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        _LOGGER.error("Missing required environment variable: %s", name)
        sys.exit(1)
    return value


def main() -> None:
    mqtt_host = _require_env("MQTT_HOST")
    mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))
    mqtt_username = os.environ.get("MQTT_USERNAME")
    mqtt_password = os.environ.get("MQTT_PASSWORD")
    discovery_prefix = os.environ.get("MQTT_DISCOVERY_PREFIX", "homeassistant")
    topic_prefix = os.environ.get("MQTT_TOPIC_PREFIX", "media2mqtt")
    device_name = os.environ.get("DEVICE_NAME", platform.node())
    enabled_app_keys = [
        k.strip().lower() for k in os.environ.get("ENABLED_APPS", "music").split(",")
    ]
    poll_interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "1"))

    apps = []
    for key in enabled_app_keys:
        cls = AVAILABLE_APPS.get(key)
        if cls is None:
            _LOGGER.error("Unknown app %r. Available: %s", key, ", ".join(AVAILABLE_APPS))
            sys.exit(1)
        apps.append((key, cls()))

    publisher = MqttPublisher(
        host=mqtt_host,
        port=mqtt_port,
        username=mqtt_username,
        password=mqtt_password,
        discovery_prefix=discovery_prefix,
        topic_prefix=topic_prefix,
    )

    object_ids: dict[str, str] = {}
    for key, app in apps:
        object_ids[key] = publisher.publish_discovery(key, app.app_name, device_name)
    now_playing_id = publisher.publish_now_playing_discovery(device_name)

    media_player_id: str | None = None
    nowplaying_bin: str | None = None
    try:
        controller = PlaybackController()
    except RuntimeError as exc:
        _LOGGER.warning("Playback control disabled: %s", exc)
    else:
        command_topic = publisher.subscribe_commands(device_name, controller.handle_command)
        _LOGGER.info("Playback control enabled, listening on %s", command_topic)
        media_player_id = publisher.publish_media_player_discovery(device_name)
        nowplaying_bin = find_nowplaying_cli()

    last_artwork_key: tuple[str, str] | None = None
    last_artwork_b64: str = ""

    _LOGGER.info("Polling %s every %ss", ", ".join(k for k, _ in apps), poll_interval)
    while True:
        states: dict[str, tuple[str, MediaState]] = {}
        for key, app in apps:
            try:
                state = app.poll()
            except Exception:
                _LOGGER.exception("Error polling %s", key)
                continue
            publisher.publish_state(
                object_ids[key], state.player_state, state.is_playing, state.attributes
            )
            states[key] = (app.app_name, state)

        active = next(
            ((k, name, s) for k, (name, s) in states.items() if s.player_state == "playing"),
            None,
        ) or next(
            ((k, name, s) for k, (name, s) in states.items() if s.player_state == "paused"),
            None,
        )
        if active:
            key, source, state = active
            title = state.attributes.get(_TITLE_KEYS.get(key, "track"), "")
            subtitle = state.attributes.get("artist", state.attributes.get("show", ""))
            attrs = {"source": source, "title": title, "subtitle": subtitle}
            if "duration" in state.attributes:
                attrs["duration"] = state.attributes["duration"]
            if "elapsed" in state.attributes:
                attrs["elapsed"] = state.attributes["elapsed"]
            publisher.publish_state(now_playing_id, state.player_state, state.is_playing, attrs)
            if media_player_id:
                artwork_key = (title, subtitle)
                albumart_b64: str | None = None
                if artwork_key != last_artwork_key and nowplaying_bin:
                    last_artwork_b64 = get_artwork_b64(nowplaying_bin)
                    last_artwork_key = artwork_key
                    albumart_b64 = last_artwork_b64
                publisher.publish_media_player_state(
                    media_player_id,
                    player_state=state.player_state,
                    title=title,
                    artist=subtitle,
                    media_type=_MEDIA_TYPES.get(key, "music"),
                    duration=state.attributes.get("duration"),
                    position=state.attributes.get("elapsed"),
                    albumart_b64=albumart_b64,
                )
        else:
            publisher.publish_state(now_playing_id, "idle", False, {})
            if media_player_id:
                albumart_b64 = "" if last_artwork_key is not None else None
                last_artwork_key = None
                last_artwork_b64 = ""
                publisher.publish_media_player_state(
                    media_player_id, player_state="idle", albumart_b64=albumart_b64
                )

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
