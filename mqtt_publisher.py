"""Resilient MQTT publisher with Home Assistant discovery."""
from __future__ import annotations

import json
import logging
import socket

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        discovery_prefix: str,
        topic_prefix: str,
    ):
        self.host = host
        self.port = port
        self.discovery_prefix = discovery_prefix
        self.topic_prefix = topic_prefix
        self._connected = False

        self.client = mqtt.Client(client_id="media2mqtt")
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        self._try_connect()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            _LOGGER.info("Connected to MQTT broker at %s:%s", self.host, self.port)
            self._connected = True
        else:
            _LOGGER.warning("MQTT connection refused: %s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = False
        if reason_code != 0:
            _LOGGER.warning("MQTT disconnected unexpectedly (rc=%s), will reconnect", reason_code)

    def _try_connect(self):
        try:
            self.client.connect(self.host, self.port, keepalive=60)
            self.client.loop_start()
        except (OSError, socket.error) as exc:
            _LOGGER.warning("Cannot reach MQTT broker at %s:%s (%s), will retry", self.host, self.port, exc)
            self.client.loop_start()

    def publish_discovery(self, app_key: str, app_name: str, device_name: str) -> str:
        object_id = f"media2mqtt_{app_key}"
        state_topic = f"{self.topic_prefix}/{object_id}/state"
        attrs_topic = f"{self.topic_prefix}/{object_id}/attributes"
        config_topic = f"{self.discovery_prefix}/sensor/{object_id}/config"
        payload = {
            "name": app_name,
            "has_entity_name": True,
            "object_id": object_id,
            "unique_id": object_id,
            "state_topic": state_topic,
            "json_attributes_topic": attrs_topic,
            "icon": "mdi:music" if app_key == "music" else "mdi:podcast",
            "device": {
                "identifiers": [f"media2mqtt_{_slugify(device_name)}"],
                "name": device_name,
                "manufacturer": "Apple",
                "model": "macOS",
            },
        }
        self.client.publish(config_topic, json.dumps(payload), qos=1, retain=True)
        return object_id

    def publish_state(self, object_id: str, player_state: str, is_playing: bool, attributes: dict) -> None:
        state_topic = f"{self.topic_prefix}/{object_id}/state"
        attrs_topic = f"{self.topic_prefix}/{object_id}/attributes"
        self.client.publish(state_topic, player_state, qos=1, retain=True)
        self.client.publish(attrs_topic, json.dumps({**attributes, "is_playing": is_playing}), qos=1, retain=True)

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()


def _slugify(value: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in value).strip("_").lower()
