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
        assert payload["command_seek_topic"] == f"media2mqtt/{DEVICE_ID}/seek"
        assert payload["command_mute_topic"] == f"media2mqtt/{DEVICE_ID}/mute"
        assert payload["state_mute_topic"] == f"media2mqtt/{DEVICE_ID}_media_player/mute"

    def test_command_topics(self):
        assert (
            self.publisher.subscribe_commands(lambda _: None) == f"media2mqtt/{DEVICE_ID}/command"
        )
        assert self.publisher.subscribe_volume(lambda _: None) == f"media2mqtt/{DEVICE_ID}/volume"
        assert self.publisher.subscribe_seek(lambda _: None) == f"media2mqtt/{DEVICE_ID}/seek"
        assert self.publisher.subscribe_mute(lambda _: None) == f"media2mqtt/{DEVICE_ID}/mute"

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


class TestUnchangedStateIsNotRepublished:
    """The poll loop publishes every second; only changed payloads should reach the broker.

    Each message is a Home Assistant state write, and the MQTT Media Player integration
    bumps media_position_updated_at even for an identical position, so republishing
    unchanged state floods the recorder.
    """

    def setup_method(self):
        self.publisher = _publisher()
        self.topic = f"media2mqtt/{DEVICE_ID}_media_player"

    def _publish_paused(self, position: str = "88") -> None:
        self.publisher.publish_media_player_state(
            f"{DEVICE_ID}_media_player",
            player_state="paused",
            title="Sorry",
            artist="The English Beat",
            media_type="music",
            duration="152",
            position=position,
            volume=0.76,
        )

    def _published_topics(self) -> list[str]:
        return [call.args[0] for call in self.publisher.client.publish.call_args_list]

    def test_identical_media_player_state_is_skipped(self):
        self._publish_paused()
        self.publisher.client.publish.reset_mock()
        self._publish_paused()
        self.publisher.client.publish.assert_not_called()

    def test_only_changed_fields_are_published(self):
        self._publish_paused(position="88")
        self.publisher.client.publish.reset_mock()
        self._publish_paused(position="89")
        assert self._published_topics() == [f"{self.topic}/position"]

    def test_identical_sensor_state_is_skipped(self):
        self.publisher.publish_state(f"{DEVICE_ID}_music", "paused", False, {"track": "Sorry"})
        self.publisher.client.publish.reset_mock()
        self.publisher.publish_state(f"{DEVICE_ID}_music", "paused", False, {"track": "Sorry"})
        self.publisher.client.publish.assert_not_called()

    def test_reconnect_republishes_everything(self):
        self._publish_paused()
        self.publisher.client.publish.reset_mock()
        self.publisher._on_connect(self.publisher.client, None, None, 0)
        self._publish_paused()
        assert f"{self.topic}/state" in self._published_topics()
        assert f"{self.topic}/position" in self._published_topics()


class TestSensorAttributes:
    """Per-second-changing values must stay out of sensor attributes.

    The recorder stores a state row plus a never-deduplicated attributes row for
    every attribute change, so a live `elapsed` grew the database every second.
    """

    def setup_method(self):
        self.publisher = _publisher()

    def _attributes(self) -> dict:
        topic = f"media2mqtt/{DEVICE_ID}_music/attributes"
        calls = [c for c in self.publisher.client.publish.call_args_list if c.args[0] == topic]
        return json.loads(calls[-1].args[1])

    def test_elapsed_is_not_published(self):
        attrs = {"track": "Dogs", "duration": "1024.9", "elapsed": "811.6"}
        self.publisher.publish_state(f"{DEVICE_ID}_music", "playing", True, attrs)
        assert self._attributes() == {"track": "Dogs", "duration": "1024.9", "is_playing": True}

    def test_elapsed_alone_changing_publishes_nothing(self):
        object_id = f"{DEVICE_ID}_music"
        self.publisher.publish_state(object_id, "playing", True, {"track": "Dogs", "elapsed": "1"})
        self.publisher.client.publish.reset_mock()
        self.publisher.publish_state(object_id, "playing", True, {"track": "Dogs", "elapsed": "2"})
        self.publisher.client.publish.assert_not_called()

    def test_caller_attributes_are_not_mutated(self):
        attrs = {"track": "Dogs", "elapsed": "811.6"}
        self.publisher.publish_state(f"{DEVICE_ID}_music", "playing", True, attrs)
        assert attrs == {"track": "Dogs", "elapsed": "811.6"}


@patch("mqtt_publisher.time.monotonic")
class TestPlayingPositionIsThrottled:
    """A playing position is only re-sent on a seek, a state/track change, or a refresh.

    Home Assistant extrapolates position from media_position_updated_at, so sending
    it every poll only adds a recorder row per second.
    """

    def setup_method(self):
        self.publisher = _publisher()
        self.position_topic = f"media2mqtt/{DEVICE_ID}_media_player/position"

    def _publish(self, position, state: str = "playing", title: str = "Dogs") -> None:
        self.publisher.publish_media_player_state(
            f"{DEVICE_ID}_media_player",
            player_state=state,
            title=title,
            artist="Pink Floyd",
            media_type="music",
            duration="1024",
            position=position,
        )

    def _positions(self) -> list[str]:
        return [
            call.args[1]
            for call in self.publisher.client.publish.call_args_list
            if call.args[0] == self.position_topic
        ]

    def _play(self, mock_monotonic, ticks: list[tuple[float, float]]) -> None:
        for now, position in ticks:
            mock_monotonic.return_value = now
            self._publish(position)

    def test_steady_playback_publishes_once(self, mock_monotonic):
        self._play(mock_monotonic, [(t, 100 + t + 0.4) for t in range(30)])
        assert self._positions() == ["100"]

    def test_seek_is_published(self, mock_monotonic):
        self._play(mock_monotonic, [(0, 100), (1, 101), (2, 500), (3, 501)])
        assert self._positions() == ["100", "500"]

    def test_refreshes_periodically(self, mock_monotonic):
        self._play(mock_monotonic, [(t, 100 + t) for t in range(121)])
        assert self._positions() == ["100", "160", "220"]

    def test_track_change_is_published(self, mock_monotonic):
        self._play(mock_monotonic, [(0, 100), (1, 101)])
        mock_monotonic.return_value = 2
        self._publish(2, title="Pigs (Three Different Ones)")
        assert self._positions() == ["100", "2"]

    def test_resume_at_paused_position_is_forced(self, mock_monotonic):
        # The integration stamps media_position_updated_at on arrival, so resuming
        # must resend the position even though the value is unchanged
        mock_monotonic.return_value = 0
        self._publish(88, state="paused")
        mock_monotonic.return_value = 300
        self._publish(88)
        assert self._positions() == ["88", "88"]

    def test_paused_position_is_deduplicated_not_throttled(self, mock_monotonic):
        mock_monotonic.return_value = 0
        self._publish(88, state="paused")
        self._publish(88, state="paused")
        self._publish(90, state="paused")
        assert self._positions() == ["88", "90"]

    def test_reconnect_republishes_position(self, mock_monotonic):
        self._play(mock_monotonic, [(0, 100), (1, 101)])
        self.publisher._on_connect(self.publisher.client, None, None, 0)
        self._play(mock_monotonic, [(2, 102)])
        assert self._positions() == ["100", "102"]
