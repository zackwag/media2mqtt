from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from scrobbler import (
    ERROR_TOKEN_NOT_AUTHORIZED,
    LastfmApiError,
    LastfmScrobbler,
    ScrobbleTracker,
    auth_url,
    get_auth_token,
    get_session_key,
)


@contextmanager
def _response(body: dict):
    class _FakeResponse:
        def read(self):
            return json.dumps(body).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    yield _FakeResponse()


class TestAuthFlow:
    @patch("scrobbler.urllib.request.urlopen")
    def test_get_auth_token(self, mock_urlopen):
        mock_urlopen.return_value = _response({"token": "tok123"}).__enter__()
        token = get_auth_token("key", "secret")
        assert token == "tok123"

    def test_auth_url(self):
        url = auth_url("key", "tok123")
        assert url == "https://www.last.fm/api/auth/?api_key=key&token=tok123"

    @patch("scrobbler.urllib.request.urlopen")
    def test_get_session_key(self, mock_urlopen):
        mock_urlopen.return_value = _response({"session": {"key": "sess123"}}).__enter__()
        session_key = get_session_key("key", "secret", "tok123")
        assert session_key == "sess123"

    @patch("scrobbler.urllib.request.urlopen")
    def test_get_session_key_not_yet_authorized(self, mock_urlopen):
        mock_urlopen.return_value = _response(
            {"error": ERROR_TOKEN_NOT_AUTHORIZED, "message": "This token has not been authorized"}
        ).__enter__()
        with pytest.raises(LastfmApiError) as exc_info:
            get_session_key("key", "secret", "tok123")
        assert exc_info.value.code == ERROR_TOKEN_NOT_AUTHORIZED


class TestLastfmScrobbler:
    def setup_method(self):
        self.scrobbler = LastfmScrobbler("key", "secret", "session")

    @patch("scrobbler.urllib.request.urlopen")
    def test_update_now_playing_success(self, mock_urlopen):
        mock_urlopen.return_value = _response({}).__enter__()
        assert self.scrobbler.update_now_playing("Queen", "Bohemian Rhapsody") is True

    @patch("scrobbler.urllib.request.urlopen")
    def test_scrobble_success(self, mock_urlopen):
        mock_urlopen.return_value = _response({}).__enter__()
        assert self.scrobbler.scrobble("Queen", "Bohemian Rhapsody", 1700000000) is True

    @patch("scrobbler.urllib.request.urlopen")
    def test_scrobble_api_error_returns_false(self, mock_urlopen):
        mock_urlopen.return_value = _response({"error": 9, "message": "Invalid session key"}).__enter__()
        assert self.scrobbler.scrobble("Queen", "Bohemian Rhapsody", 1700000000) is False

    @patch("scrobbler.urllib.request.urlopen", side_effect=OSError("network unreachable"))
    def test_scrobble_network_error_returns_false(self, mock_urlopen):
        assert self.scrobbler.scrobble("Queen", "Bohemian Rhapsody", 1700000000) is False


class TestScrobbleTracker:
    def setup_method(self):
        self.scrobbler = LastfmScrobbler("key", "secret", "session")
        self.tracker = ScrobbleTracker(self.scrobbler)

    @patch("scrobbler.LastfmScrobbler.update_now_playing", return_value=True)
    @patch("scrobbler.LastfmScrobbler.scrobble", return_value=True)
    def test_new_track_announces_now_playing(self, mock_scrobble, mock_now_playing):
        self.tracker.update(
            artist="Queen",
            track="Bohemian Rhapsody",
            album="A Night at the Opera",
            duration=354,
            elapsed=1.0,
            is_playing=True,
        )
        mock_now_playing.assert_called_once_with(
            "Queen", "Bohemian Rhapsody", "A Night at the Opera", 354
        )
        mock_scrobble.assert_not_called()

    @patch("scrobbler.LastfmScrobbler.update_now_playing", return_value=True)
    @patch("scrobbler.LastfmScrobbler.scrobble", return_value=True)
    def test_scrobbles_once_past_threshold(self, mock_scrobble, mock_now_playing):
        self.tracker.update("Queen", "Bohemian Rhapsody", "A Night at the Opera", 354, 1.0, True)
        self.tracker.update("Queen", "Bohemian Rhapsody", "A Night at the Opera", 354, 177.0, True)
        assert mock_scrobble.call_count == 1
        # Further updates past the threshold shouldn't scrobble again.
        self.tracker.update("Queen", "Bohemian Rhapsody", "A Night at the Opera", 354, 200.0, True)
        assert mock_scrobble.call_count == 1

    @patch("scrobbler.LastfmScrobbler.update_now_playing", return_value=True)
    @patch("scrobbler.LastfmScrobbler.scrobble", return_value=True)
    def test_uses_four_minute_cap_for_long_tracks(self, mock_scrobble, mock_now_playing):
        # Half of a 20-minute track is 10 minutes, but the cap is 4 minutes (240s).
        self.tracker.update("Artist", "Long Track", "", 1200, 239.0, True)
        mock_scrobble.assert_not_called()
        self.tracker.update("Artist", "Long Track", "", 1200, 240.0, True)
        mock_scrobble.assert_called_once()

    @patch("scrobbler.LastfmScrobbler.update_now_playing", return_value=True)
    @patch("scrobbler.LastfmScrobbler.scrobble", return_value=True)
    def test_short_track_never_scrobbles(self, mock_scrobble, mock_now_playing):
        self.tracker.update("Artist", "Short Track", "", 20, 15.0, True)
        mock_scrobble.assert_not_called()

    @patch("scrobbler.LastfmScrobbler.update_now_playing", return_value=True)
    @patch("scrobbler.LastfmScrobbler.scrobble", return_value=True)
    def test_paused_track_does_not_scrobble(self, mock_scrobble, mock_now_playing):
        self.tracker.update("Queen", "Bohemian Rhapsody", "A Night at the Opera", 354, 200.0, False)
        mock_now_playing.assert_not_called()
        mock_scrobble.assert_not_called()

    @patch("scrobbler.LastfmScrobbler.update_now_playing", return_value=True)
    @patch("scrobbler.LastfmScrobbler.scrobble", return_value=True)
    def test_track_change_resets_scrobbled_state(self, mock_scrobble, mock_now_playing):
        self.tracker.update("Queen", "Bohemian Rhapsody", "A Night at the Opera", 354, 200.0, True)
        assert mock_scrobble.call_count == 1
        self.tracker.update("Queen", "Another One Bites the Dust", "The Game", 215, 1.0, True)
        assert mock_now_playing.call_count == 2
        mock_scrobble.assert_called_once()

    @patch("scrobbler.LastfmScrobbler.update_now_playing", return_value=True)
    @patch("scrobbler.LastfmScrobbler.scrobble", return_value=True)
    def test_missing_metadata_clears_state(self, mock_scrobble, mock_now_playing):
        self.tracker.update("Queen", "Bohemian Rhapsody", "A Night at the Opera", 354, 1.0, True)
        self.tracker.update("", "", "", None, None, False)
        # Track "restarting" after a clear should announce now-playing again.
        self.tracker.update("Queen", "Bohemian Rhapsody", "A Night at the Opera", 354, 1.0, True)
        assert mock_now_playing.call_count == 2

    @patch("scrobbler.LastfmScrobbler.update_now_playing", return_value=False)
    def test_failed_now_playing_retries_next_update(self, mock_now_playing):
        self.tracker.update("Queen", "Bohemian Rhapsody", "A Night at the Opera", 354, 1.0, True)
        self.tracker.update("Queen", "Bohemian Rhapsody", "A Night at the Opera", 354, 2.0, True)
        assert mock_now_playing.call_count == 2

    def test_clear_resets_state(self):
        self.tracker._track_key = ("Queen", "Bohemian Rhapsody", "Album")
        self.tracker._announced = True
        self.tracker._scrobbled = True
        self.tracker.clear()
        assert self.tracker._track_key is None
        assert self.tracker._announced is False
        assert self.tracker._scrobbled is False
