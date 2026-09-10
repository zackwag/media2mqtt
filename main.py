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
"""
from __future__ import annotations

import logging
import os
import platform
import sys
import time

from media_apps import AVAILABLE_APPS, MediaState
from mqtt_publisher import MqttPublisher

_TITLE_KEYS = {"music": "track", "podcasts": "episode"}

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
    enabled_app_keys = [k.strip().lower() for k in os.environ.get("ENABLED_APPS", "music").split(",")]
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

    _LOGGER.info("Polling %s every %ss", ", ".join(k for k, _ in apps), poll_interval)
    while True:
        states: dict[str, tuple[str, MediaState]] = {}
        for key, app in apps:
            try:
                state = app.poll()
            except Exception:
                _LOGGER.exception("Error polling %s", key)
                continue
            publisher.publish_state(object_ids[key], state.player_state, state.is_playing, state.attributes)
            states[key] = (app.app_name, state)

        active = next(((k, name, s) for k, (name, s) in states.items() if s.is_playing), None)
        if active:
            key, source, state = active
            title_key = _TITLE_KEYS.get(key, "track")
            attrs = {
                "source": source,
                "title": state.attributes.get(title_key, ""),
                "subtitle": state.attributes.get("artist", state.attributes.get("show", "")),
            }
            if "duration" in state.attributes:
                attrs["duration"] = state.attributes["duration"]
            if "elapsed" in state.attributes:
                attrs["elapsed"] = state.attributes["elapsed"]
            publisher.publish_state(now_playing_id, "playing", True, attrs)
        else:
            publisher.publish_state(now_playing_id, "idle", False, {})

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
