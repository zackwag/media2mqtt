"""Resilient MQTT publisher with Home Assistant discovery."""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import subprocess
import threading
import time
from collections.abc import Callable

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

# Sensor attributes that are never published. `elapsed` changes on every poll while
# playing, and Home Assistant's recorder stores a new state row plus a new (never
# deduplicated) attributes row for every change, so it alone grew the database by
# ~2 rows/second per playing Mac. Position lives on the media_player entity instead.
_UNPUBLISHED_SENSOR_ATTRIBUTES = frozenset({"elapsed"})

# A playing track's position advances on its own and Home Assistant extrapolates it
# from media_position_updated_at, so it's only re-sent when it jumps by more than the
# tolerance (a seek), when the state or track changes, or every refresh interval. The
# refresh bounds how stale the retained position can be: the MQTT Media Player
# integration stamps media_position_updated_at when a position message arrives, so
# after an HA or coordinator restart the retained value is treated as current.
_POSITION_DRIFT_TOLERANCE_SECONDS = 3
_POSITION_REFRESH_SECONDS = 60


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
        self._seek_topic: str | None = None
        self._seek_handler: Callable[[str], None] | None = None
        # Last payload published per retained state topic. The poll loop calls the
        # publish_* methods every second whether or not anything changed, and every
        # message reaching Home Assistant is a state write (the MQTT Media Player
        # integration bumps media_position_updated_at even for an identical position),
        # so unchanged payloads are skipped.
        self._last_published: dict[str, str] = {}
        # object_id -> (position in seconds, time.monotonic()) of the last position
        # published while playing; see _should_publish_position.
        self._position_anchors: dict[str, tuple[int, float]] = {}

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
            # Republish everything after a (re)connect in case the broker lost its
            # retained messages.
            self._last_published.clear()
            self._position_anchors.clear()
            if self._command_topic:
                self.client.subscribe(self._command_topic, qos=1)
            if self._volume_topic:
                self.client.subscribe(self._volume_topic, qos=1)
            if self._seek_topic:
                self.client.subscribe(self._seek_topic, qos=1)
        else:
            _LOGGER.warning("MQTT connection refused: %s", reason_code)

    def _on_message(self, client, userdata, msg):
        payload = msg.payload.decode("utf-8", errors="replace")
        if msg.topic == self._volume_topic and self._volume_handler:
            self._command_queue.put(("volume", payload))
            return
        if msg.topic == self._seek_topic and self._seek_handler:
            self._command_queue.put(("seek", payload))
            return
        if msg.topic == self._command_topic and self._command_queue is not None:
            self._command_queue.put(("command", payload))

    def _process_commands(self):
        while True:
            kind, payload = self._command_queue.get()
            handlers = {"volume": self._volume_handler, "seek": self._seek_handler}
            handler = handlers.get(kind, self._command_handler)
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

    def _publish_state_topic(self, topic: str, payload: str, force: bool = False) -> None:
        """Publish a retained state payload, skipping it if unchanged since the last publish.

        force publishes even an unchanged payload, for consumers that react to the
        message arriving rather than to its value.
        """
        if not force and self._last_published.get(topic) == payload:
            return
        self.client.publish(topic, payload, qos=1, retain=True)
        self._last_published[topic] = payload

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
        published = {k: v for k, v in attributes.items() if k not in _UNPUBLISHED_SENSOR_ATTRIBUTES}
        self._publish_state_topic(state_topic, player_state)
        self._publish_state_topic(attrs_topic, json.dumps({**published, "is_playing": is_playing}))

    def command_topic(self) -> str:
        return f"{self.topic_prefix}/{self.device_id}/command"

    def volume_command_topic(self) -> str:
        return f"{self.topic_prefix}/{self.device_id}/volume"

    def seek_command_topic(self) -> str:
        return f"{self.topic_prefix}/{self.device_id}/seek"

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
        seek_command_topic = self.seek_command_topic()
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
            "command_seek_topic": seek_command_topic,
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
        playback_changed = any(
            self._last_published.get(f"{topic}/{field}") != value
            for field, value in (("state", player_state), ("title", title), ("artist", artist))
        )
        self._publish_state_topic(f"{topic}/state", player_state)
        self._publish_state_topic(f"{topic}/title", title)
        self._publish_state_topic(f"{topic}/artist", artist)
        self._publish_state_topic(f"{topic}/mediatype", media_type)
        self._publish_state_topic(f"{topic}/duration", _as_int_str(duration))
        position_str = _as_int_str(position)
        if player_state == "playing" and position_str:
            if self._should_publish_position(object_id, int(position_str), playback_changed):
                # Forced: the MQTT Media Player integration stamps
                # media_position_updated_at on arrival, so re-anchoring must send the
                # message even if the value matches (e.g. resuming at the paused position).
                self._publish_state_topic(f"{topic}/position", position_str, force=True)
        else:
            self._position_anchors.pop(object_id, None)
            self._publish_state_topic(f"{topic}/position", position_str)
        if albumart_b64 is not None:
            self._publish_state_topic(f"{topic}/albumart", albumart_b64)
        if volume is not None:
            self._publish_state_topic(f"{topic}/vol", str(round(volume, 2)))

    def _should_publish_position(
        self, object_id: str, position: int, playback_changed: bool
    ) -> bool:
        """Return whether a playing position needs publishing, re-anchoring it if so.

        Skips positions that match where steady playback from the last published
        position would be, so a playing track costs one Home Assistant state write per
        refresh interval instead of one per poll.
        """
        now = time.monotonic()
        anchor = self._position_anchors.get(object_id)
        if anchor is not None and not playback_changed:
            anchored_position, anchored_at = anchor
            since = now - anchored_at
            expected = anchored_position + since
            if (
                since < _POSITION_REFRESH_SECONDS
                and abs(position - expected) <= _POSITION_DRIFT_TOLERANCE_SECONDS
            ):
                return False
        self._position_anchors[object_id] = (position, now)
        return True

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

    def subscribe_seek(self, handler: Callable[[str], None]) -> str:
        """Subscribe to the device's seek command topic."""
        topic = self.seek_command_topic()
        self._seek_topic = topic
        self._seek_handler = handler
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
