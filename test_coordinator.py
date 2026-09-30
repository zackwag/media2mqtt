from __future__ import annotations

import json
from unittest.mock import patch

from coordinator import Coordinator

SOURCE_TOPIC = "media2mqtt/grouped/source"
CONFIG_TOPIC = "homeassistant/media_player/office_mac_mini_media_media_player/config"
STATE_TOPIC = "media2mqtt/office_mac_mini_media_media_player/state"


def _media_player_config(**overrides) -> dict:
    config = {
        "device": {"identifiers": ["media2mqtt_office_mac_mini_media"], "name": "Office Mac Mini"},
        "state_state_topic": STATE_TOPIC,
    }
    config.update(overrides)
    return config


class TestSourceName:
    @patch("coordinator.mqtt.Client")
    def setup_method(self, method, mock_client=None):
        self.coordinator = Coordinator(
            "broker", 1883, None, None, "homeassistant", "media2mqtt", "Now Playing", "media2mqtt"
        )

    def _play(self, config: dict) -> str:
        self.coordinator._handle_discovery(CONFIG_TOPIC, json.dumps(config))
        self.coordinator._handle_state_update(STATE_TOPIC, "playing")
        published = [
            call.args[1]
            for call in self.coordinator.client.publish.call_args_list
            if call.args[0] == SOURCE_TOPIC
        ]
        return published[-1]

    def test_source_uses_device_name_when_entity_has_no_name(self):
        assert self._play(_media_player_config()) == "Office Mac Mini"

    def test_source_falls_back_to_device_id(self):
        config = _media_player_config()
        del config["device"]["name"]
        assert self._play(config) == "office_mac_mini_media_media_player"


def _coordinator(group_device_name: str = "media2mqtt") -> Coordinator:
    with patch("coordinator.mqtt.Client"):
        return Coordinator(
            "broker",
            1883,
            None,
            None,
            "homeassistant",
            "media2mqtt",
            "Now Playing",
            group_device_name,
        )


def _published(coordinator: Coordinator) -> dict[str, str]:
    return {call.args[0]: call.args[1] for call in coordinator.client.publish.call_args_list}


class TestFixedGroupIdentity:
    def test_group_device_name_is_display_only(self):
        coordinator = _coordinator("Office Grouped Media")
        coordinator.publish_discovery()
        published = _published(coordinator)
        grouped = json.loads(published["homeassistant/media_player/media2mqtt_grouped/config"])
        assert grouped["device"]["name"] == "Office Grouped Media"
        assert grouped["device"]["identifiers"] == ["media2mqtt_media2mqtt_grouped"]
        source = json.loads(published["homeassistant/sensor/media2mqtt_source/config"])
        assert source["unique_id"] == "media2mqtt_source"
        assert "office_grouped" not in json.dumps(list(published)).lower()
