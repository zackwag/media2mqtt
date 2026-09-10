"""Media app adapters that poll macOS apps via AppleScript or nowplaying-cli."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field

_LOGGER = logging.getLogger(__name__)

_SEPARATOR = "|||"


@dataclass
class MediaState:
    player_state: str = "idle"
    is_playing: bool = False
    attributes: dict[str, str] = field(default_factory=dict)


class MediaApp:
    """Base class for a macOS media app adapter."""

    app_name: str
    bundle_id: str

    def poll(self) -> MediaState:
        raise NotImplementedError

    def _app_is_running(self) -> bool:
        result = subprocess.run(
            ["osascript", "-e", f'application "{self.app_name}" is running'],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip().lower() == "true"

    def _run_applescript(self, script: str) -> str | None:
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            _LOGGER.warning("%s AppleScript timed out", self.app_name)
            return None


class MusicApp(MediaApp):
    app_name = "Music"
    bundle_id = "com.apple.Music"

    def poll(self) -> MediaState:
        if not self._app_is_running():
            return MediaState()

        script = f'''
            tell application "Music"
                set pState to player state as string
                if player state is not stopped then
                    set tName to name of current track
                    set tArtist to artist of current track
                    set tAlbum to album of current track
                    set tDuration to duration of current track
                    set tPosition to player position
                    return pState & "{_SEPARATOR}" & tName & "{_SEPARATOR}" & tArtist & "{_SEPARATOR}" & tAlbum & "{_SEPARATOR}" & tDuration & "{_SEPARATOR}" & tPosition
                else
                    return pState
                end if
            end tell
        '''
        raw = self._run_applescript(script)
        if not raw:
            return MediaState()

        parts = raw.split(_SEPARATOR)
        player_state = parts[0].strip().lower()
        is_playing = player_state == "playing"

        attrs: dict[str, str] = {}
        if len(parts) >= 6:
            attrs["track"] = parts[1].strip()
            attrs["artist"] = parts[2].strip()
            attrs["album"] = parts[3].strip()
            attrs["duration"] = parts[4].strip()
            attrs["elapsed"] = parts[5].strip()

        return MediaState(player_state=player_state, is_playing=is_playing, attributes=attrs)


class PodcastsApp(MediaApp):
    """Uses nowplaying-cli since Podcasts.app has no AppleScript playback API."""

    app_name = "Podcasts"
    bundle_id = "com.apple.podcasts"

    def __init__(self):
        import os
        self._nowplaying_bin = shutil.which("nowplaying-cli")
        if not self._nowplaying_bin:
            for path in ["/opt/homebrew/bin/nowplaying-cli", "/usr/local/bin/nowplaying-cli"]:
                if os.path.isfile(path) and os.access(path, os.X_OK):
                    self._nowplaying_bin = path
                    break
        if not self._nowplaying_bin:
            raise RuntimeError("nowplaying-cli is required for Podcasts support: brew install nowplaying-cli")

    def poll(self) -> MediaState:
        if not self._app_is_running():
            return MediaState()

        try:
            result = subprocess.run(
                [self._nowplaying_bin, "get-raw"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return MediaState()
        except subprocess.TimeoutExpired:
            _LOGGER.warning("nowplaying-cli timed out")
            return MediaState()

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return MediaState()

        bundle = data.get("kMRMediaRemoteNowPlayingInfoClientBundleIdentifier", "")
        if bundle != self.bundle_id:
            return MediaState()

        playback_rate = data.get("kMRMediaRemoteNowPlayingInfoPlaybackRate", 0)
        is_playing = playback_rate == 1
        player_state = "playing" if is_playing else "paused"

        title = data.get("kMRMediaRemoteNowPlayingInfoTitle", "")
        show = data.get("kMRMediaRemoteNowPlayingInfoArtist", "")
        duration = data.get("kMRMediaRemoteNowPlayingInfoDuration", "")
        elapsed = data.get("kMRMediaRemoteNowPlayingInfoElapsedTime", "")

        attrs: dict[str, str] = {}
        if title:
            attrs["episode"] = title
        if show:
            attrs["show"] = show
        if duration:
            attrs["duration"] = str(duration)
        if elapsed:
            attrs["elapsed"] = str(elapsed)

        return MediaState(player_state=player_state, is_playing=is_playing, attributes=attrs)


AVAILABLE_APPS: dict[str, type[MediaApp]] = {
    "music": MusicApp,
    "podcasts": PodcastsApp,
}
