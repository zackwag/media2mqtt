"""Resilient MQTT publisher with Home Assistant discovery."""

from __future__ import annotations

import json
import logging
import platform
import queue
import subprocess
import threading
from collections.abc import Callable

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)


def _get_mac_model() -> str:
    try:
        result = subprocess.run(
            ["system_profiler", "SPHardwareDataType"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in result.stdout.splitlines():
            if "Model Name" in line:
                return line.split(":", 1)[1].strip()
    except Exception as exc:  # noqa: BLE001 - cosmetic device name, always fall back to "Mac"
        _LOGGER.debug("Could not determine Mac model: %s", exc)
    return "Mac"


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
        self._command_topic: str | None = None
        self._command_handler: Callable[[str], None] | None = None
        self._command_queue: queue.Queue[str] | None = None

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"media2mqtt_{_slugify(platform.node())}"
        )
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        self._mac_model = _get_mac_model()
        self._try_connect()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            _LOGGER.info("Connected to MQTT broker at %s:%s", self.host, self.port)
            self._connected = True
            if self._command_topic:
                self.client.subscribe(self._command_topic, qos=1)
        else:
            _LOGGER.warning("MQTT connection refused: %s", reason_code)

    def _on_message(self, client, userdata, msg):
        if msg.topic != self._command_topic or self._command_queue is None:
            return
        payload = msg.payload.decode("utf-8", errors="replace")
        self._command_queue.put(payload)

    def _process_commands(self):
        while True:
            payload = self._command_queue.get()
            handler = self._command_handler
            if handler is None:
                continue
            try:
                handler(payload)
            except Exception:
                _LOGGER.exception("Error handling command %r", payload)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = False
        if reason_code != 0:
            _LOGGER.warning("MQTT disconnected unexpectedly (rc=%s), will reconnect", reason_code)

    def _try_connect(self):
        try:
            self.client.connect(self.host, self.port, keepalive=60)
            self.client.loop_start()
        except OSError as exc:
            _LOGGER.warning(
                "Cannot reach MQTT broker at %s:%s (%s), will retry", self.host, self.port, exc
            )
            self.client.loop_start()

    def _device_block(self, device_name: str) -> dict:
        device_slug = _slugify(device_name)
        return {
            "identifiers": [f"media2mqtt_{device_slug}"],
            "name": device_name,
            "manufacturer": "Apple",
            "model": self._mac_model,
        }

    def _publish_sensor_discovery(
        self, object_id: str, name: str, icon: str, device_name: str
    ) -> str:
        state_topic = f"{self.topic_prefix}/{object_id}/state"
        attrs_topic = f"{self.topic_prefix}/{object_id}/attributes"
        config_topic = f"{self.discovery_prefix}/sensor/{object_id}/config"
        payload = {
            "name": name,
            "object_id": object_id,
            "unique_id": object_id,
            "state_topic": state_topic,
            "json_attributes_topic": attrs_topic,
            "icon": icon,
            "device": self._device_block(device_name),
        }
        self.client.publish(config_topic, json.dumps(payload), qos=1, retain=True)
        return object_id

    def publish_discovery(self, app_key: str, app_name: str, device_name: str) -> str:
        device_slug = _slugify(device_name)
        object_id = f"{device_slug}_{app_key}"
        icon = "mdi:music" if app_key == "music" else "mdi:podcast"
        return self._publish_sensor_discovery(
            object_id, f"{device_name} {app_name}", icon, device_name
        )

    def publish_now_playing_discovery(self, device_name: str) -> str:
        device_slug = _slugify(device_name)
        object_id = f"{device_slug}_now_playing"
        return self._publish_sensor_discovery(
            object_id, f"{device_name} Now Playing", "mdi:play-circle", device_name
        )

    def publish_state(
        self, object_id: str, player_state: str, is_playing: bool, attributes: dict
    ) -> None:
        state_topic = f"{self.topic_prefix}/{object_id}/state"
        attrs_topic = f"{self.topic_prefix}/{object_id}/attributes"
        self.client.publish(state_topic, player_state, qos=1, retain=True)
        self.client.publish(
            attrs_topic, json.dumps({**attributes, "is_playing": is_playing}), qos=1, retain=True
        )

    def command_topic(self, device_name: str) -> str:
        return f"{self.topic_prefix}/{_slugify(device_name)}/command"

    def subscribe_commands(self, device_name: str, handler: Callable[[str], None]) -> str:
        """Subscribe to the device's command topic, invoking handler(payload) for each message.

        Commands run on a dedicated worker thread, one at a time, so a slow or hung
        handler can't block the MQTT network loop (and thus keepalive/publishing).
        Resubscribes automatically after reconnects.
        """
        topic = self.command_topic(device_name)
        self._command_topic = topic
        self._command_handler = handler
        if self._command_queue is None:
            self._command_queue = queue.Queue()
            threading.Thread(target=self._process_commands, daemon=True).start()
        if self._connected:
            self.client.subscribe(topic, qos=1)
        return topic

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()


def _slugify(value: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in value).strip("_").lower()
