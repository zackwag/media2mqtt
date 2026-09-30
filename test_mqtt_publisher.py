from __future__ import annotations

import hashlib
import json
import subprocess
from unittest.mock import patch

import pytest

from mqtt_publisher import MqttPublisher, get_device_id

DEVICE_NAME = "Office Mac Mini Media"
DEVICE_ID = "3f9a1c0e7b2d"


def _publisher() -> MqttPublisher:
    with (
        patch("mqtt_publisher._get_mac_model", return_value="Mac mini"),
        patch("mqtt_publisher.mqtt.Client"),
    ):
        return MqttPublisher(
            "broker", 1883, None, None, "homeassistant", "media2mqtt", DEVICE_ID, DEVICE_NAME
        )


def _discovery_payloads(publisher: MqttPublisher) -> dict[str, dict]:
    """Return {config_topic: payload} for every discovery config published."""
    return {
        call.args[0]: json.loads(call.args[1])
        for call in publisher.client.publish.call_args_list
        if call.args[0].endswith("/config")
    }


class TestDiscoveryNames:
    """Entity names must not embed the device name.

    Home Assistant composes the displayed name (and entity IDs from "Recreate
    entity IDs") from the device name plus the entity name. If the entity name
    also contains DEVICE_NAME, renaming the device in HA's UI leaves the old
    name baked into every entity.
    """

    def setup_method(self):
        self.publisher = _publisher()

    def test_app_sensor_name_is_app_name_only(self):
        self.publisher.publish_discovery("music", "Music")
        payload = _discovery_payloads(self.publisher)[
            f"homeassistant/sensor/{DEVICE_ID}_music/config"
        ]
        assert payload["name"] == "Music"
        assert payload["device"]["name"] == DEVICE_NAME

    def test_now_playing_sensor_name_is_short(self):
        self.publisher.publish_now_playing_discovery()
        payload = _discovery_payloads(self.publisher)[
            f"homeassistant/sensor/{DEVICE_ID}_now_playing/config"
        ]
        assert payload["name"] == "Now Playing"
        assert payload["device"]["name"] == DEVICE_NAME

    def test_media_player_has_no_entity_name(self):
        self.publisher.publish_media_player_discovery()
        payload = _discovery_payloads(self.publisher)[
            f"homeassistant/media_player/{DEVICE_ID}_media_player/config"
        ]
        assert "name" not in payload
        assert payload["device"]["name"] == DEVICE_NAME


class TestIdentityKeyedOnDeviceId:
    """DEVICE_NAME is display-only; every ID and topic is keyed on device_id."""

    def setup_method(self):
        self.publisher = _publisher()

    def test_sensor_ids_and_topics(self):
        object_id = self.publisher.publish_discovery("music", "Music")
        payload = _discovery_payloads(self.publisher)[
            f"homeassistant/sensor/{DEVICE_ID}_music/config"
        ]
        assert object_id == f"{DEVICE_ID}_music"
        assert payload["unique_id"] == f"{DEVICE_ID}_music"
        assert payload["state_topic"] == f"media2mqtt/{DEVICE_ID}_music/state"
        assert payload["json_attributes_topic"] == f"media2mqtt/{DEVICE_ID}_music/attributes"
        assert payload["device"]["identifiers"] == [f"media2mqtt_{DEVICE_ID}"]

    def test_media_player_ids_and_topics(self):
        # The MQTT Media Player integration takes its unique ID from the topic's object ID
        object_id = self.publisher.publish_media_player_discovery()
        payload = _discovery_payloads(self.publisher)[
            f"homeassistant/media_player/{DEVICE_ID}_media_player/config"
        ]
        assert object_id == f"{DEVICE_ID}_media_player"
        assert payload["state_state_topic"] == f"media2mqtt/{DEVICE_ID}_media_player/state"
        assert payload["command_play_topic"] == f"media2mqtt/{DEVICE_ID}/command"
        assert payload["command_volume_topic"] == f"media2mqtt/{DEVICE_ID}/volume"

    def test_command_topics(self):
        assert (
            self.publisher.subscribe_commands(lambda _: None) == f"media2mqtt/{DEVICE_ID}/command"
        )
        assert self.publisher.subscribe_volume(lambda _: None) == f"media2mqtt/{DEVICE_ID}/volume"

    def test_nothing_is_derived_from_device_name(self):
        self.publisher.publish_discovery("music", "Music")
        self.publisher.publish_now_playing_discovery()
        self.publisher.publish_media_player_discovery()
        published = json.dumps([call.args for call in self.publisher.client.publish.call_args_list])
        assert "office_mac_mini" not in published.lower()


IOREG_OUTPUT = """+-o J274AP  <class IOPlatformExpertDevice>
    {
      "IOPlatformSerialNumber" = "XXXXXXXXXX"
      "IOPlatformUUID" = "12345678-ABCD-4EF0-9876-0123456789AB"
    }
"""


def _ioreg(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


class TestGetDeviceId:
    @patch("mqtt_publisher.subprocess.run", return_value=_ioreg(IOREG_OUTPUT))
    def test_hashes_hardware_uuid(self, mock_run):
        expected = hashlib.sha256(b"12345678-ABCD-4EF0-9876-0123456789AB").hexdigest()[:12]
        assert get_device_id() == expected

    @patch("mqtt_publisher.subprocess.run", return_value=_ioreg(IOREG_OUTPUT))
    def test_does_not_expose_raw_uuid(self, mock_run):
        assert "12345678" not in get_device_id().upper()

    @patch("mqtt_publisher.subprocess.run", side_effect=FileNotFoundError("ioreg"))
    def test_raises_without_ioreg(self, mock_run):
        # A name-based fallback would silently create duplicate HA entities
        with pytest.raises(RuntimeError):
            get_device_id()

    @patch("mqtt_publisher.subprocess.run", return_value=_ioreg(""))
    def test_raises_without_uuid(self, mock_run):
        with pytest.raises(RuntimeError):
            get_device_id()
