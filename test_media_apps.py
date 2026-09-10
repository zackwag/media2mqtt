from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from media_apps import MediaState, MusicApp, PodcastsApp

_SEP = "|||"


def _osascript_result(stdout: str, returncode: int = 0):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def _osascript_error():
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="execution error")


class TestMusicApp:
    def setup_method(self):
        self.app = MusicApp()

    @patch("media_apps.subprocess.run")
    def test_app_not_running(self, mock_run):
        mock_run.return_value = _osascript_result("false")
        state = self.app.poll()
        assert state == MediaState()
        assert state.player_state == "idle"
        assert state.is_playing is False
        assert state.attributes == {}

    @patch("media_apps.subprocess.run")
    def test_playing(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            _osascript_result(f"playing{_SEP}Bohemian Rhapsody{_SEP}Queen{_SEP}A Night at the Opera{_SEP}354{_SEP}132.5"),
        ]
        state = self.app.poll()
        assert state.player_state == "playing"
        assert state.is_playing is True
        assert state.attributes == {
            "track": "Bohemian Rhapsody",
            "artist": "Queen",
            "album": "A Night at the Opera",
            "duration": "354",
            "elapsed": "132.5",
        }

    @patch("media_apps.subprocess.run")
    def test_paused(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            _osascript_result(f"paused{_SEP}Track{_SEP}Artist{_SEP}Album{_SEP}200{_SEP}45.0"),
        ]
        state = self.app.poll()
        assert state.player_state == "paused"
        assert state.is_playing is False

    @patch("media_apps.subprocess.run")
    def test_stopped(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            _osascript_result("stopped"),
        ]
        state = self.app.poll()
        assert state.player_state == "stopped"
        assert state.is_playing is False
        assert state.attributes == {}

    @patch("media_apps.subprocess.run")
    def test_applescript_error(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            _osascript_error(),
        ]
        state = self.app.poll()
        assert state == MediaState()

    @patch("media_apps.subprocess.run")
    def test_applescript_timeout(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            subprocess.TimeoutExpired(cmd="osascript", timeout=5),
        ]
        state = self.app.poll()
        assert state == MediaState()

    @patch("media_apps.subprocess.run")
    def test_metadata_with_special_characters(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            _osascript_result(f"playing{_SEP}Don't Stop Me Now{_SEP}Queen{_SEP}Jazz{_SEP}209{_SEP}100.0"),
        ]
        state = self.app.poll()
        assert state.attributes["track"] == "Don't Stop Me Now"


def _nowplaying_json(bundle_id, title, artist, duration, playback_rate, elapsed=0):
    return json.dumps({
        "kMRMediaRemoteNowPlayingInfoClientBundleIdentifier": bundle_id,
        "kMRMediaRemoteNowPlayingInfoTitle": title,
        "kMRMediaRemoteNowPlayingInfoArtist": artist,
        "kMRMediaRemoteNowPlayingInfoDuration": duration,
        "kMRMediaRemoteNowPlayingInfoPlaybackRate": playback_rate,
        "kMRMediaRemoteNowPlayingInfoElapsedTime": elapsed,
    })


class TestPodcastsApp:
    @patch("media_apps.shutil.which", return_value="/usr/local/bin/nowplaying-cli")
    def setup_method(self, method, mock_which=None):
        self.app = PodcastsApp()

    @patch("media_apps.subprocess.run")
    def test_app_not_running(self, mock_run):
        mock_run.return_value = _osascript_result("false")
        state = self.app.poll()
        assert state == MediaState()

    @patch("media_apps.subprocess.run")
    def test_playing(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            _osascript_result(_nowplaying_json("com.apple.podcasts", "Episode 42", "My Podcast", 3600, 1, 1200)),
        ]
        state = self.app.poll()
        assert state.player_state == "playing"
        assert state.is_playing is True
        assert state.attributes == {"episode": "Episode 42", "show": "My Podcast", "duration": "3600", "elapsed": "1200"}

    @patch("media_apps.subprocess.run")
    def test_paused(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            _osascript_result(_nowplaying_json("com.apple.podcasts", "Episode 1", "Some Show", 1800, 0, 500)),
        ]
        state = self.app.poll()
        assert state.player_state == "paused"
        assert state.is_playing is False

    @patch("media_apps.subprocess.run")
    def test_different_app_playing(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            _osascript_result(_nowplaying_json("com.apple.Music", "Song", "Artist", 200, 1, 50)),
        ]
        state = self.app.poll()
        assert state == MediaState()

    @patch("media_apps.subprocess.run")
    def test_nowplaying_error(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            _osascript_error(),
        ]
        state = self.app.poll()
        assert state == MediaState()

    @patch("media_apps.subprocess.run")
    def test_nowplaying_timeout(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            subprocess.TimeoutExpired(cmd="nowplaying-cli", timeout=5),
        ]
        state = self.app.poll()
        assert state == MediaState()

    @patch("os.access", return_value=False)
    @patch("os.path.isfile", return_value=False)
    @patch("media_apps.shutil.which", return_value=None)
    def test_missing_nowplaying_cli(self, mock_which, mock_isfile, mock_access):
        with pytest.raises(RuntimeError):
            PodcastsApp()
