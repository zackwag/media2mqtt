"""Media app adapters that poll macOS apps via AppleScript."""
from __future__ import annotations

import logging
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
                    return pState & "{_SEPARATOR}" & tName & "{_SEPARATOR}" & tArtist & "{_SEPARATOR}" & tAlbum & "{_SEPARATOR}" & tDuration
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
        if len(parts) >= 5:
            attrs["track"] = parts[1].strip()
            attrs["artist"] = parts[2].strip()
            attrs["album"] = parts[3].strip()
            attrs["duration"] = parts[4].strip()

        return MediaState(player_state=player_state, is_playing=is_playing, attributes=attrs)


class PodcastsApp(MediaApp):
    app_name = "Podcasts"
    bundle_id = "com.apple.podcasts"

    def poll(self) -> MediaState:
        if not self._app_is_running():
            return MediaState()

        script = f'''
            tell application "Podcasts"
                set pState to player state as string
                if player state is not stopped then
                    set eName to name of current episode
                    set sName to name of show of current episode
                    return pState & "{_SEPARATOR}" & eName & "{_SEPARATOR}" & sName
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
        if len(parts) >= 3:
            attrs["episode"] = parts[1].strip()
            attrs["show"] = parts[2].strip()

        return MediaState(player_state=player_state, is_playing=is_playing, attributes=attrs)


AVAILABLE_APPS: dict[str, type[MediaApp]] = {
    "music": MusicApp,
    "podcasts": PodcastsApp,
}
