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

from media_apps import AVAILABLE_APPS
from mqtt_publisher import MqttPublisher

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

    _LOGGER.info("Polling %s every %ss", ", ".join(k for k, _ in apps), poll_interval)
    while True:
        for key, app in apps:
            try:
                state = app.poll()
            except Exception:
                _LOGGER.exception("Error polling %s", key)
                continue
            publisher.publish_state(object_ids[key], state.player_state, state.is_playing, state.attributes)
        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
