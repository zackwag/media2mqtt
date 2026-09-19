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
