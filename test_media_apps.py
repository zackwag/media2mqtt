from __future__ import annotations

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
            _osascript_result(f"playing{_SEP}Bohemian Rhapsody{_SEP}Queen{_SEP}A Night at the Opera{_SEP}354"),
        ]
        state = self.app.poll()
        assert state.player_state == "playing"
        assert state.is_playing is True
        assert state.attributes == {
            "track": "Bohemian Rhapsody",
            "artist": "Queen",
            "album": "A Night at the Opera",
            "duration": "354",
        }

    @patch("media_apps.subprocess.run")
    def test_paused(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            _osascript_result(f"paused{_SEP}Track{_SEP}Artist{_SEP}Album{_SEP}200"),
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
            _osascript_result(f"playing{_SEP}Don't Stop Me Now{_SEP}Queen{_SEP}Jazz{_SEP}209"),
        ]
        state = self.app.poll()
        assert state.attributes["track"] == "Don't Stop Me Now"


class TestPodcastsApp:
    def setup_method(self):
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
            _osascript_result(f"playing{_SEP}Episode 42{_SEP}My Podcast"),
        ]
        state = self.app.poll()
        assert state.player_state == "playing"
        assert state.is_playing is True
        assert state.attributes == {"episode": "Episode 42", "show": "My Podcast"}

    @patch("media_apps.subprocess.run")
    def test_paused(self, mock_run):
        mock_run.side_effect = [
            _osascript_result("true"),
            _osascript_result(f"paused{_SEP}Episode 1{_SEP}Some Show"),
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
