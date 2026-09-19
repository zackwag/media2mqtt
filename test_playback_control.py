from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from playback_control import PlaybackController


def _result(returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout="", stderr=stderr)


class TestPlaybackController:
    @patch("playback_control.find_nowplaying_cli", return_value="/usr/local/bin/nowplaying-cli")
    def setup_method(self, method, mock_find=None):
        self.controller = PlaybackController()

    @patch("playback_control.find_nowplaying_cli", return_value=None)
    def test_missing_nowplaying_cli(self, mock_find):
        with pytest.raises(RuntimeError):
            PlaybackController()

    @patch("playback_control.subprocess.run")
    def test_valid_command_runs_nowplaying_cli(self, mock_run):
        mock_run.return_value = _result()
        self.controller.handle_command("togglePlayPause")
        mock_run.assert_called_once_with(
            ["/usr/local/bin/nowplaying-cli", "togglePlayPause"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    @patch("playback_control.subprocess.run")
    def test_command_is_stripped(self, mock_run):
        mock_run.return_value = _result()
        self.controller.handle_command("  play\n")
        mock_run.assert_called_once_with(
            ["/usr/local/bin/nowplaying-cli", "play"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

    @patch("playback_control.subprocess.run")
    def test_unknown_command_is_ignored(self, mock_run):
        self.controller.handle_command("shuffle")
        mock_run.assert_not_called()

    @patch("playback_control.subprocess.run")
    def test_nonzero_exit_does_not_raise(self, mock_run):
        mock_run.return_value = _result(returncode=1, stderr="boom")
        self.controller.handle_command("next")

    @patch("playback_control.subprocess.run")
    def test_timeout_does_not_raise(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="nowplaying-cli", timeout=5)
        self.controller.handle_command("previous")
