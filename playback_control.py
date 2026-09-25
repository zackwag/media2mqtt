"""Executes nowplaying-cli playback commands received over MQTT.

nowplaying-cli controls playback at the system level (via MediaRemote), so it
works regardless of which app currently owns the media session.
"""

from __future__ import annotations

import logging
import subprocess

from media_apps import find_nowplaying_cli

_LOGGER = logging.getLogger(__name__)

COMMANDS = ("play", "pause", "togglePlayPause", "next", "previous")


class PlaybackController:
    def __init__(self):
        self._nowplaying_bin = find_nowplaying_cli()
        if not self._nowplaying_bin:
            raise RuntimeError(
                "nowplaying-cli is required for playback control: brew install nowplaying-cli"
            )

    def handle_command(self, command: str) -> None:
        command = command.strip()
        if command not in COMMANDS:
            _LOGGER.warning("Ignoring unknown playback command: %r", command)
            return

        try:
            result = subprocess.run(
                [self._nowplaying_bin, command],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode != 0:
                _LOGGER.warning("nowplaying-cli %s failed: %s", command, result.stderr.strip())
        except subprocess.TimeoutExpired:
            _LOGGER.warning("nowplaying-cli %s timed out", command)

    def handle_volume_command(self, payload: str) -> None:
        payload = payload.strip()
        try:
            level = float(payload)
        except (ValueError, TypeError):
            _LOGGER.warning("Ignoring invalid volume payload: %r", payload)
            return
        level = max(0.0, min(1.0, level))
        mac_vol = round(level * 100)
        try:
            result = subprocess.run(
                ["osascript", "-e", f"set volume output volume {mac_vol}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            if result.returncode != 0:
                _LOGGER.warning("set volume failed: %s", result.stderr.strip())
        except subprocess.TimeoutExpired:
            _LOGGER.warning("set volume timed out")


def get_volume() -> float:
    """Return the current macOS output volume as a float 0.0–1.0."""
    try:
        result = subprocess.run(
            ["osascript", "-e", "output volume of (get volume settings)"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip()) / 100.0
    except (subprocess.TimeoutExpired, ValueError):
        pass
    return 0.0
