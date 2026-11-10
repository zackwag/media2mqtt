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


class TestClose:
    def test_close_keeps_retained_discovery(self):
        coordinator = _coordinator()
        coordinator.publish_discovery()
        coordinator.client.publish.reset_mock()
        coordinator.close()
        coordinator.client.publish.assert_not_called()
        coordinator.client.disconnect.assert_called_once()


POSITION_TOPIC = "media2mqtt/office_mac_mini_media_media_player/position"
GROUPED_POSITION_TOPIC = "media2mqtt/grouped/position"


class TestUnchangedGroupedStateIsNotRepublished:
    """Every per-device field update re-runs _update_grouped_state().

    Only grouped topics whose payload actually changed should be published; each
    message is a Home Assistant state write.
    """

    def setup_method(self):
        self.coordinator = _coordinator()
        config = _media_player_config(state_position_topic=POSITION_TOPIC)
        self.coordinator._handle_discovery(CONFIG_TOPIC, json.dumps(config))
        self.coordinator._handle_state_update(STATE_TOPIC, "paused")
        self.coordinator._handle_state_update(POSITION_TOPIC, "88")
        self.coordinator.client.publish.reset_mock()

    def _published_topics(self) -> list[str]:
        return [call.args[0] for call in self.coordinator.client.publish.call_args_list]

    def test_identical_device_update_publishes_nothing(self):
        self.coordinator._handle_state_update(STATE_TOPIC, "paused")
        self.coordinator._handle_state_update(POSITION_TOPIC, "88")
        self.coordinator.client.publish.assert_not_called()

    def test_only_changed_grouped_topic_is_published(self):
        self.coordinator._handle_state_update(POSITION_TOPIC, "89")
        assert self._published_topics() == [GROUPED_POSITION_TOPIC]

    def test_reconnect_republishes_everything(self):
        self.coordinator._on_connect(self.coordinator.client, None, None, 0)
        self.coordinator._handle_state_update(STATE_TOPIC, "paused")
        assert "media2mqtt/grouped/state" in self._published_topics()
        assert GROUPED_POSITION_TOPIC in self._published_topics()

    def test_playing_position_resend_is_forwarded(self):
        # media2mqtt re-sends an identical position to re-anchor it on resume; the
        # integration stamps media_position_updated_at on arrival, so it must pass through
        self.coordinator._handle_state_update(STATE_TOPIC, "playing")
        self.coordinator.client.publish.reset_mock()
        self.coordinator._handle_state_update(POSITION_TOPIC, "88")
        assert self._published_topics() == [GROUPED_POSITION_TOPIC]

    def test_state_update_while_playing_does_not_resend_position(self):
        self.coordinator._handle_state_update(STATE_TOPIC, "playing")
        self.coordinator.client.publish.reset_mock()
        self.coordinator._handle_state_update(STATE_TOPIC, "playing")
        self.coordinator.client.publish.assert_not_called()
