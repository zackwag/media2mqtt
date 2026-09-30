from __future__ import annotations

import json
from unittest.mock import patch

from mqtt_publisher import MqttPublisher

DEVICE_NAME = "Office Mac Mini Media"


def _discovery_payloads(publisher: MqttPublisher) -> dict[str, dict]:
    """Return {config_topic: payload} for every discovery config published so far."""
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

    @patch("mqtt_publisher._get_mac_model", return_value="Mac mini")
    @patch("mqtt_publisher.mqtt.Client")
    def setup_method(self, method, mock_client=None, mock_model=None):
        self.publisher = MqttPublisher("broker", 1883, None, None, "homeassistant", "media2mqtt")

    def test_app_sensor_name_is_app_name_only(self):
        self.publisher.publish_discovery("music", "Music", DEVICE_NAME)
        payload = _discovery_payloads(self.publisher)[
            "homeassistant/sensor/office_mac_mini_media_music/config"
        ]
        assert payload["name"] == "Music"
        assert payload["device"]["name"] == DEVICE_NAME

    def test_now_playing_sensor_name_is_short(self):
        self.publisher.publish_now_playing_discovery(DEVICE_NAME)
        payload = _discovery_payloads(self.publisher)[
            "homeassistant/sensor/office_mac_mini_media_now_playing/config"
        ]
        assert payload["name"] == "Now Playing"
        assert payload["device"]["name"] == DEVICE_NAME

    def test_media_player_has_no_entity_name(self):
        self.publisher.publish_media_player_discovery(DEVICE_NAME)
        payload = _discovery_payloads(self.publisher)[
            "homeassistant/media_player/office_mac_mini_media_media_player/config"
        ]
        assert "name" not in payload
        assert payload["device"]["name"] == DEVICE_NAME

    def test_unique_ids_are_unchanged(self):
        """Renaming entities must not orphan existing HA entities."""
        self.publisher.publish_discovery("music", "Music", DEVICE_NAME)
        self.publisher.publish_now_playing_discovery(DEVICE_NAME)
        payloads = _discovery_payloads(self.publisher)
        assert {p["unique_id"] for p in payloads.values()} == {
            "office_mac_mini_media_music",
            "office_mac_mini_media_now_playing",
        }
