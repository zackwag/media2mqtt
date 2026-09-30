"""Resilient MQTT publisher with Home Assistant discovery."""

from __future__ import annotations

import hashlib
import json
import logging
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


def get_device_id() -> str:
    """Return this Mac's stable ID: a short hash of its hardware UUID.

    Every unique ID, discovery topic and state/command topic is keyed on this, so
    DEVICE_NAME is display-only and can change freely. Hashed so the raw hardware
    identifier never ends up in MQTT or Home Assistant.
    """
    try:
        result = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Could not run ioreg to read the hardware UUID: {exc}") from exc
    for line in result.stdout.splitlines():
        if '"IOPlatformUUID"' in line:
            uuid = line.split("=", 1)[1].strip().strip('"')
            return hashlib.sha256(uuid.encode()).hexdigest()[:12]
    raise RuntimeError("ioreg output has no IOPlatformUUID")


class MqttPublisher:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        discovery_prefix: str,
        topic_prefix: str,
        device_id: str,
        device_name: str,
    ):
        self.host = host
        self.port = port
        self.discovery_prefix = discovery_prefix
        self.topic_prefix = topic_prefix
        self.device_id = device_id
        self.device_name = device_name
        self._connected = False
        self._command_topic: str | None = None
        self._command_handler: Callable[[str], None] | None = None
        self._command_queue: queue.Queue[str] | None = None
        self._volume_topic: str | None = None
        self._volume_handler: Callable[[str], None] | None = None

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"media2mqtt_{device_id}"
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
            if self._volume_topic:
                self.client.subscribe(self._volume_topic, qos=1)
        else:
            _LOGGER.warning("MQTT connection refused: %s", reason_code)

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace")
        if msg.topic == self._volume_topic and self._volume_handler:
            self._command_queue.put(("volume", payload))
            return
        if msg.topic == self._command_topic and self._command_queue is not None:
            self._command_queue.put(("command", payload))

    def _process_commands(self):
        while True:
            kind, payload = self._command_queue.get()
            handler = self._volume_handler if kind == "volume" else self._command_handler
            if handler is None:
                continue
            try:
                handler(payload)
            except Exception:
                _LOGGER.exception("Error handling %s %r", kind, payload)

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

    def _device_block(self) -> dict:
        return {
            "identifiers": [f"media2mqtt_{self.device_id}"],
            "name": self.device_name,
            "manufacturer": "Apple",
            "model": self._mac_model,
        }

    def _publish_sensor_discovery(self, key: str, name: str, icon: str) -> str:
        object_id = f"{self.device_id}_{key}"
        payload = {
            "name": name,
            "unique_id": object_id,
            "state_topic": f"{self.topic_prefix}/{object_id}/state",
            "json_attributes_topic": f"{self.topic_prefix}/{object_id}/attributes",
            "icon": icon,
            "device": self._device_block(),
        }
        config_topic = f"{self.discovery_prefix}/sensor/{object_id}/config"
        self.client.publish(config_topic, json.dumps(payload), qos=1, retain=True)
        return object_id

    def publish_discovery(self, app_key: str, app_name: str) -> str:
        icon = "mdi:music" if app_key == "music" else "mdi:podcast"
        return self._publish_sensor_discovery(app_key, app_name, icon)

    def publish_now_playing_discovery(self) -> str:
        return self._publish_sensor_discovery("now_playing", "Now Playing", "mdi:play-circle")

    def publish_state(
        self, object_id: str, player_state: str, is_playing: bool, attributes: dict
    ) -> None:
        state_topic = f"{self.topic_prefix}/{object_id}/state"
        attrs_topic = f"{self.topic_prefix}/{object_id}/attributes"
        self.client.publish(state_topic, player_state, qos=1, retain=True)
        self.client.publish(
            attrs_topic, json.dumps({**attributes, "is_playing": is_playing}), qos=1, retain=True
        )

    def command_topic(self) -> str:
        return f"{self.topic_prefix}/{self.device_id}/command"

    def volume_command_topic(self) -> str:
        return f"{self.topic_prefix}/{self.device_id}/volume"

    def publish_media_player_discovery(self) -> str:
        """Publish discovery for the "MQTT Media Player" HACS integration.

        Core Home Assistant's MQTT integration has no discovery schema for
        media_player entities, so this targets a third-party integration instead:
        https://github.com/bkbilly/mqtt_media_player (install via HACS - it isn't
        in the default store, add it as a custom repository). It listens on a
        hardcoded "homeassistant/media_player/#" topic regardless of
        MQTT_DISCOVERY_PREFIX, so this entity is only discovered when that prefix
        is left at its default "homeassistant".

        Reuses the same device block as the sensors, so this entity merges onto
        that device's page instead of creating a separate one, and repoints all
        of its command topics at the existing playback command topic/payloads so
        playback_control.py needs no changes.

        The payload deliberately has no "name": the entity then takes its
        device's name, so renaming the device in Home Assistant's UI renames
        this entity too instead of leaving DEVICE_NAME baked into it.

        The integration takes the entity's unique ID from the discovery topic's
        object ID, so that is keyed on device_id like everything else.
        """
        object_id = f"{self.device_id}_media_player"
        topic = f"{self.topic_prefix}/{object_id}"
        command_topic = self.command_topic()
        vol_command_topic = self.volume_command_topic()
        config_topic = f"{self.discovery_prefix}/media_player/{object_id}/config"
        payload = {
            "device": self._device_block(),
            "state_state_topic": f"{topic}/state",
            "state_title_topic": f"{topic}/title",
            "state_artist_topic": f"{topic}/artist",
            "state_duration_topic": f"{topic}/duration",
            "state_position_topic": f"{topic}/position",
            "state_albumart_topic": f"{topic}/albumart",
            "state_mediatype_topic": f"{topic}/mediatype",
            "state_volume_topic": f"{topic}/vol",
            "command_play_topic": command_topic,
            "command_play_payload": "play",
            "command_pause_topic": command_topic,
            "command_pause_payload": "pause",
            "command_next_topic": command_topic,
            "command_next_payload": "next",
            "command_previous_topic": command_topic,
            "command_previous_payload": "previous",
            "command_volume_topic": vol_command_topic,
        }
        self.client.publish(config_topic, json.dumps(payload), qos=1, retain=True)
        return object_id

    def publish_media_player_state(
        self,
        object_id: str,
        player_state: str,
        title: str = "",
        artist: str = "",
        media_type: str = "",
        duration: str | float | None = None,
        position: str | float | None = None,
        albumart_b64: str | None = None,
        volume: float | None = None,
    ) -> None:
        topic = f"{self.topic_prefix}/{object_id}"
        self.client.publish(f"{topic}/state", player_state, qos=1, retain=True)
        self.client.publish(f"{topic}/title", title, qos=1, retain=True)
        self.client.publish(f"{topic}/artist", artist, qos=1, retain=True)
        self.client.publish(f"{topic}/mediatype", media_type, qos=1, retain=True)
        self.client.publish(f"{topic}/duration", _as_int_str(duration), qos=1, retain=True)
        self.client.publish(f"{topic}/position", _as_int_str(position), qos=1, retain=True)
        if albumart_b64 is not None:
            self.client.publish(f"{topic}/albumart", albumart_b64, qos=1, retain=True)
        if volume is not None:
            self.client.publish(f"{topic}/vol", str(round(volume, 2)), qos=1, retain=True)

    def subscribe_commands(self, handler: Callable[[str], None]) -> str:
        """Subscribe to the device's command topic, invoking handler(payload) for each message.

        Commands run on a dedicated worker thread, one at a time, so a slow or hung
        handler can't block the MQTT network loop (and thus keepalive/publishing).
        Resubscribes automatically after reconnects.
        """
        topic = self.command_topic()
        self._command_topic = topic
        self._command_handler = handler
        if self._command_queue is None:
            self._command_queue = queue.Queue()
            threading.Thread(target=self._process_commands, daemon=True).start()
        if self._connected:
            self.client.subscribe(topic, qos=1)
        return topic

    def subscribe_volume(self, handler: Callable[[str], None]) -> str:
        """Subscribe to the device's volume command topic."""
        topic = self.volume_command_topic()
        self._volume_topic = topic
        self._volume_handler = handler
        if self._command_queue is None:
            self._command_queue = queue.Queue()
            threading.Thread(target=self._process_commands, daemon=True).start()
        if self._connected:
            self.client.subscribe(topic, qos=1)
        return topic

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()


def _as_int_str(value: str | float | None) -> str:
    """Coerce a possibly-fractional duration/position value to an integer-seconds string.

    The MQTT Media Player integration parses these with int(), which raises on
    a fractional string like "452.074005126953" (what nowplaying-cli/AppleScript
    report) - so this rounds down and stringifies instead of passing it through.
    """
    if value is None or value == "":
        return ""
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return ""
