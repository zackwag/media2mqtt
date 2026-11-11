"""Grouped media_player coordinator for multi-Mac media2mqtt setups.

Auto-discovers all media2mqtt media_player entities via MQTT retained
discovery messages, aggregates their state into a single grouped
media_player entity, and routes transport commands to the active device.

No macOS dependencies — runs anywhere with MQTT access.

Env vars:
  MQTT_HOST                 required
  MQTT_PORT                 optional, default 1883
  MQTT_USERNAME             optional
  MQTT_PASSWORD             optional
  MQTT_DISCOVERY_PREFIX     optional, default "homeassistant"
  MQTT_TOPIC_PREFIX         optional, default "media2mqtt"
  GROUP_NAME                optional, default "Now Playing"
  GROUP_DEVICE_NAME         optional, default "media2mqtt". Display-only: entities
                            are keyed on the fixed ID "media2mqtt".
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading

import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger("media2mqtt.coordinator")

_STATE_FIELDS = (
    "state",
    "title",
    "artist",
    "album",
    "duration",
    "position",
    "albumart",
    "mediatype",
    "volume",
)

_APP_SENSORS: dict[str, tuple[str, str]] = {
    "music": ("Music", "mdi:music"),
    "podcast": ("Podcasts", "mdi:podcast"),
}


# There is one coordinator per broker, so its entities are keyed on a fixed ID
# and GROUP_DEVICE_NAME stays display-only.
_GROUP_ID = "media2mqtt"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        _LOGGER.error("Missing required environment variable: %s", name)
        sys.exit(1)
    return value


class DeviceState:
    """Tracked state for a single discovered media2mqtt device."""

    def __init__(self, device_id: str, config: dict):
        self.device_id = device_id
        self.config = config
        self.state: str = "idle"
        self.title: str = ""
        self.artist: str = ""
        self.album: str = ""
        self.duration: str = ""
        self.position: str = ""
        self.albumart: str = ""
        self.mediatype: str = ""
        self.volume: str = ""

    @property
    def command_topics(self) -> dict[str, tuple[str, str]]:
        """Return {action: (topic, payload)} for routable commands."""
        cmds = {}
        for action in ("play", "pause", "next", "previous"):
            topic = self.config.get(f"command_{action}_topic")
            payload = self.config.get(f"command_{action}_payload", action)
            if topic:
                cmds[action] = (topic, payload)
        return cmds

    @property
    def volume_topic(self) -> str | None:
        return self.config.get("command_volume_topic")

    @property
    def seek_topic(self) -> str | None:
        return self.config.get("command_seek_topic")

    @property
    def display_name(self) -> str:
        """The Mac's DEVICE_NAME, from the discovery config's device block."""
        return self.config.get("device", {}).get("name") or self.device_id


class Coordinator:
    def __init__(
        self,
        host: str,
        port: int,
        username: str | None,
        password: str | None,
        discovery_prefix: str,
        topic_prefix: str,
        group_name: str,
        group_device_name: str,
    ):
        self.discovery_prefix = discovery_prefix
        self.topic_prefix = topic_prefix
        self.group_name = group_name
        self.group_device_name = group_device_name

        self._devices: dict[str, DeviceState] = {}
        self._topic_to_device: dict[str, tuple[str, str]] = {}
        self._active_device_id: str | None = None
        # Last payload published per retained grouped topic. Every per-device field
        # update re-runs _update_grouped_state(), which would otherwise republish every
        # grouped topic each time, and each message reaching Home Assistant is a state
        # write, so unchanged payloads are skipped.
        self._last_published: dict[str, str] = {}
        self._lock = threading.Lock()

        self._group_object_id = f"{_GROUP_ID}_grouped"
        self._group_topic = f"{topic_prefix}/grouped"
        self._group_command_topic = f"{self._group_topic}/command"
        self._group_volume_topic = f"{self._group_topic}/volume_set"
        self._group_seek_topic = f"{self._group_topic}/seek"
        self._group_config_topic = f"{discovery_prefix}/media_player/{self._group_object_id}/config"
        self._source_object_id = f"{_GROUP_ID}_source"
        self._source_state_topic = f"{topic_prefix}/grouped/source"
        self._source_config_topic = f"{discovery_prefix}/sensor/{self._source_object_id}/config"

        self._app_sensor_topics: dict[str, str] = {}
        self._app_sensor_config_topics: dict[str, str] = {}
        for mediatype in _APP_SENSORS:
            obj_id = f"{_GROUP_ID}_{mediatype}"
            self._app_sensor_topics[mediatype] = f"{topic_prefix}/grouped/{mediatype}"
            self._app_sensor_config_topics[mediatype] = f"{discovery_prefix}/sensor/{obj_id}/config"

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id="media2mqtt_coordinator"
        )
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)

        try:
            self.client.connect(host, port, keepalive=60)
        except OSError as exc:
            _LOGGER.warning("Cannot reach MQTT broker at %s:%s (%s), will retry", host, port, exc)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            _LOGGER.warning("MQTT connection refused: %s", reason_code)
            return
        _LOGGER.info("Connected to MQTT broker")
        # Republish everything after a (re)connect in case the broker lost its
        # retained messages.
        with self._lock:
            self._last_published.clear()
        discovery_topic = f"{self.discovery_prefix}/media_player/+/config"
        client.subscribe(discovery_topic, qos=1)
        client.subscribe(self._group_command_topic, qos=1)
        client.subscribe(self._group_volume_topic, qos=1)
        client.subscribe(self._group_seek_topic, qos=1)
        for device in self._devices.values():
            self._subscribe_device_topics(device)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            _LOGGER.warning("MQTT disconnected unexpectedly (rc=%s), will reconnect", reason_code)

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace")

        if topic.startswith(f"{self.discovery_prefix}/media_player/") and topic.endswith("/config"):
            self._handle_discovery(topic, payload)
        elif topic == self._group_command_topic:
            self._handle_command(payload)
        elif topic == self._group_volume_topic:
            self._handle_seek_or_volume(payload, "volume_topic")
        elif topic == self._group_seek_topic:
            self._handle_seek_or_volume(payload, "seek_topic")
        else:
            self._handle_state_update(topic, payload)

    def _handle_discovery(self, topic: str, payload: str):
        parts = topic.split("/")
        device_id = parts[-2]

        if device_id == self._group_object_id:
            return

        if not payload or not payload.strip():
            with self._lock:
                if device_id in self._devices:
                    _LOGGER.info("Device removed: %s", device_id)
                    del self._devices[device_id]
                    self._topic_to_device = {
                        t: v for t, v in self._topic_to_device.items() if v[0] != device_id
                    }
                    if self._active_device_id == device_id:
                        self._active_device_id = None
                    self._update_grouped_state()
            return

        try:
            config = json.loads(payload)
        except json.JSONDecodeError:
            return

        identifiers = config.get("device", {}).get("identifiers", [])
        is_media2mqtt = any(isinstance(i, str) and i.startswith("media2mqtt_") for i in identifiers)
        if not is_media2mqtt:
            return

        with self._lock:
            is_new = device_id not in self._devices
            self._devices[device_id] = DeviceState(device_id, config)
            self._register_device_topics(device_id, config)
            if is_new:
                _LOGGER.info(
                    "Discovered device: %s (%s)", device_id, self._devices[device_id].display_name
                )
                self._subscribe_device_topics(self._devices[device_id])

    def _register_device_topics(self, device_id: str, config: dict):
        for field in _STATE_FIELDS:
            topic_key = f"state_{field}_topic"
            topic = config.get(topic_key)
            if topic:
                self._topic_to_device[topic] = (device_id, field)

    def _subscribe_device_topics(self, device: DeviceState):
        for field in _STATE_FIELDS:
            topic_key = f"state_{field}_topic"
            topic = device.config.get(topic_key)
            if topic:
                self.client.subscribe(topic, qos=1)

    def _handle_state_update(self, topic: str, payload: str):
        with self._lock:
            mapping = self._topic_to_device.get(topic)
            if not mapping:
                return
            device_id, field = mapping
            device = self._devices.get(device_id)
            if not device:
                return
            setattr(device, field, payload)
            self._update_grouped_state(position_from=device_id if field == "position" else None)

    def _handle_command(self, payload: str):
        with self._lock:
            if not self._active_device_id:
                return
            device = self._devices.get(self._active_device_id)
            if not device:
                return
            command = payload.strip()
            cmds = device.command_topics
            if command in cmds:
                topic, cmd_payload = cmds[command]
                self.client.publish(topic, cmd_payload, qos=1)

    def _handle_seek_or_volume(self, payload: str, topic_attr: str):
        with self._lock:
            if not self._active_device_id:
                return
            device = self._devices.get(self._active_device_id)
            if not device:
                return
            topic = getattr(device, topic_attr, None)
            if topic:
                self.client.publish(topic, payload.strip(), qos=1)

    def _publish_state_topic(self, topic: str, payload: str, force: bool = False) -> None:
        """Publish a retained state payload, skipping it if unchanged since the last publish.

        force publishes even an unchanged payload, for consumers that react to the
        message arriving rather than to its value.
        """
        if not force and self._last_published.get(topic) == payload:
            return
        self.client.publish(topic, payload, qos=1, retain=True)
        self._last_published[topic] = payload

    def _update_grouped_state(self, position_from: str | None = None):
        """Publish the grouped player's state from the active device.

        position_from is the device whose position message triggered this update.
        media2mqtt only re-sends a playing position to re-anchor it (seek, resume,
        periodic refresh), and the MQTT Media Player integration stamps
        media_position_updated_at on arrival, so the active device's playing position
        is forwarded even when the value is unchanged.
        """
        active = self._active_device_id

        playing = None
        for did, dev in self._devices.items():
            if dev.state == "playing":
                playing = did
                break

        if playing:
            active = playing
        elif active and active in self._devices and self._devices[active].state == "paused":
            pass
        else:
            active = None
            for did, dev in self._devices.items():
                if dev.state == "paused":
                    active = did
                    break

        prev_active = self._active_device_id
        self._active_device_id = active

        t = self._group_topic
        if active and active in self._devices:
            dev = self._devices[active]
            self._publish_state_topic(f"{t}/state", dev.state)
            self._publish_state_topic(f"{t}/title", dev.title)
            self._publish_state_topic(f"{t}/artist", dev.artist)
            self._publish_state_topic(f"{t}/album", dev.album)
            self._publish_state_topic(f"{t}/mediatype", dev.mediatype)
            self._publish_state_topic(f"{t}/duration", dev.duration)
            self._publish_state_topic(
                f"{t}/position",
                dev.position,
                force=position_from == active and dev.state == "playing",
            )
            self._publish_state_topic(f"{t}/vol", dev.volume)
            self._publish_state_topic(f"{t}/albumart", dev.albumart)
            if active != prev_active:
                self._publish_state_topic(self._source_state_topic, dev.display_name)
            for mediatype, state_topic in self._app_sensor_topics.items():
                app_state = dev.state if dev.mediatype == mediatype else "idle"
                self._publish_state_topic(state_topic, app_state)
        else:
            self._publish_state_topic(f"{t}/state", "idle")
            self._publish_state_topic(f"{t}/title", "")
            self._publish_state_topic(f"{t}/artist", "")
            self._publish_state_topic(f"{t}/album", "")
            self._publish_state_topic(f"{t}/mediatype", "")
            self._publish_state_topic(f"{t}/duration", "")
            self._publish_state_topic(f"{t}/position", "")
            self._publish_state_topic(f"{t}/vol", "")
            for state_topic in self._app_sensor_topics.values():
                self._publish_state_topic(state_topic, "idle")
            if prev_active is not None:
                self._publish_state_topic(f"{t}/albumart", "")
                self._publish_state_topic(self._source_state_topic, "")

    def publish_discovery(self):
        t = self._group_topic
        device_block = {
            "identifiers": [f"media2mqtt_{self._group_object_id}"],
            "name": self.group_device_name,
            "manufacturer": "media2mqtt",
            "model": "Grouped Media Player",
        }
        payload = {
            "name": self.group_name,
            "device": device_block,
            "state_state_topic": f"{t}/state",
            "state_title_topic": f"{t}/title",
            "state_artist_topic": f"{t}/artist",
            "state_album_topic": f"{t}/album",
            "state_duration_topic": f"{t}/duration",
            "state_position_topic": f"{t}/position",
            "state_albumart_topic": f"{t}/albumart",
            "state_mediatype_topic": f"{t}/mediatype",
            "state_volume_topic": f"{t}/vol",
            "command_play_topic": self._group_command_topic,
            "command_play_payload": "play",
            "command_pause_topic": self._group_command_topic,
            "command_pause_payload": "pause",
            "command_next_topic": self._group_command_topic,
            "command_next_payload": "next",
            "command_previous_topic": self._group_command_topic,
            "command_previous_payload": "previous",
            "command_volume_topic": self._group_volume_topic,
            "command_seek_topic": self._group_seek_topic,
        }
        self.client.publish(self._group_config_topic, json.dumps(payload), qos=1, retain=True)

        source_payload = {
            "name": f"{self.group_name} Source",
            "unique_id": self._source_object_id,
            "state_topic": self._source_state_topic,
            "icon": "mdi:desktop-mac",
            "device": device_block,
        }
        self.client.publish(
            self._source_config_topic, json.dumps(source_payload), qos=1, retain=True
        )

        for mediatype, (name, icon) in _APP_SENSORS.items():
            obj_id = f"{_GROUP_ID}_{mediatype}"
            app_payload = {
                "name": name,
                "unique_id": obj_id,
                "state_topic": self._app_sensor_topics[mediatype],
                "icon": icon,
                "device": device_block,
            }
            self.client.publish(
                self._app_sensor_config_topics[mediatype],
                json.dumps(app_payload),
                qos=1,
                retain=True,
            )

        _LOGGER.info("Published grouped media_player and sensor discovery")

    def close(self):
        # Leave the retained discovery in place. Clearing it on shutdown left HA with
        # no config to replay if it restarted while the coordinator was down, and the
        # grouped media_player stayed unknown until the coordinator restarted.
        self.client.loop_stop()
        self.client.disconnect()


def main() -> None:
    mqtt_host = _require_env("MQTT_HOST")
    mqtt_port = int(os.environ.get("MQTT_PORT", "1883"))
    mqtt_username = os.environ.get("MQTT_USERNAME")
    mqtt_password = os.environ.get("MQTT_PASSWORD")
    discovery_prefix = os.environ.get("MQTT_DISCOVERY_PREFIX", "homeassistant")
    topic_prefix = os.environ.get("MQTT_TOPIC_PREFIX", "media2mqtt")
    group_name = os.environ.get("GROUP_NAME", "Now Playing")
    group_device_name = os.environ.get("GROUP_DEVICE_NAME", "media2mqtt")

    coordinator = Coordinator(
        host=mqtt_host,
        port=mqtt_port,
        username=mqtt_username,
        password=mqtt_password,
        discovery_prefix=discovery_prefix,
        topic_prefix=topic_prefix,
        group_name=group_name,
        group_device_name=group_device_name,
    )
    coordinator.publish_discovery()

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    _LOGGER.info("Coordinator running, waiting for device discovery...")
    stop.wait()

    _LOGGER.info("Shutting down")
    coordinator.close()


if __name__ == "__main__":
    main()
