"""Last.fm scrobbling via the Audioscrobbler API (https://www.last.fm/api).

Uses the "desktop application" auth flow: a token is authorized by the user
in a browser, then exchanged for a permanent session key. See
lastfm_auth.py for the one-time setup script that does this.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

_LOGGER = logging.getLogger(__name__)

_API_URL = "https://ws.audioscrobbler.com/2.0/"
_AUTH_URL = "https://www.last.fm/api/auth/"
_TIMEOUT = 10

# https://www.last.fm/api/errorcodes
ERROR_TOKEN_NOT_AUTHORIZED = 14


class LastfmApiError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"Last.fm API error {code}: {message}")
        self.code = code
        self.message = message


def _sign(params: dict[str, str], api_secret: str) -> str:
    """Sign params per the Last.fm API spec: sorted key+value pairs, secret appended, md5'd.

    "format" and "api_sig" itself are excluded from the signed string, so callers
    must sign before adding those.
    """
    base = "".join(f"{key}{params[key]}" for key in sorted(params))
    return hashlib.md5((base + api_secret).encode("utf-8")).hexdigest()


def _request(params: dict[str, str], api_secret: str, *, post: bool) -> dict:
    signed = {**params, "api_sig": _sign(params, api_secret), "format": "json"}
    encoded = urllib.parse.urlencode(signed)
    request = (
        urllib.request.Request(_API_URL, data=encoded.encode("utf-8"), method="POST")
        if post
        else urllib.request.Request(f"{_API_URL}?{encoded}")
    )
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        body = json.loads(response.read())
    if "error" in body:
        raise LastfmApiError(body["error"], body.get("message", ""))
    return body


def get_auth_token(api_key: str, api_secret: str) -> str:
    """Fetch a fresh, unauthorized request token (auth.getToken)."""
    body = _request({"method": "auth.getToken", "api_key": api_key}, api_secret, post=False)
    return body["token"]


def auth_url(api_key: str, token: str) -> str:
    """URL the user must open and approve before the token can be exchanged."""
    return f"{_AUTH_URL}?{urllib.parse.urlencode({'api_key': api_key, 'token': token})}"


def get_session_key(api_key: str, api_secret: str, token: str) -> str:
    """Exchange an approved token for a permanent session key (auth.getSession).

    Raises LastfmApiError with code ERROR_TOKEN_NOT_AUTHORIZED if the user
    hasn't approved the token yet - callers doing a headless flow should
    catch that and poll.
    """
    body = _request(
        {"method": "auth.getSession", "api_key": api_key, "token": token}, api_secret, post=False
    )
    return body["session"]["key"]


class LastfmScrobbler:
    """Submits now-playing updates and scrobbles for one authorized session."""

    def __init__(self, api_key: str, api_secret: str, session_key: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session_key = session_key

    def _call(self, method: str, params: dict[str, str]) -> bool:
        full_params = {**params, "method": method, "api_key": self.api_key, "sk": self.session_key}
        try:
            _request(full_params, self.api_secret, post=True)
            return True
        except LastfmApiError as exc:
            _LOGGER.warning("Last.fm %s rejected: %s", method, exc)
            return False
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            _LOGGER.warning("Last.fm %s failed: %s", method, exc)
            return False

    def update_now_playing(
        self, artist: str, track: str, album: str = "", duration: int | None = None
    ) -> bool:
        params = {"artist": artist, "track": track}
        if album:
            params["album"] = album
        if duration:
            params["duration"] = str(duration)
        return self._call("track.updateNowPlaying", params)

    def scrobble(
        self,
        artist: str,
        track: str,
        timestamp: int,
        album: str = "",
        duration: int | None = None,
    ) -> bool:
        params = {"artist": artist, "track": track, "timestamp": str(timestamp)}
        if album:
            params["album"] = album
        if duration:
            params["duration"] = str(duration)
        return self._call("track.scrobble", params)


class ScrobbleTracker:
    """Decides when to announce now-playing and when to scrobble the active track.

    Follows Last.fm's scrobbling rules (https://www.last.fm/api/scrobbling):
    a track must run at least 30s, and is scrobbled once playback passes the
    halfway point or 4 minutes, whichever comes first.
    """

    _MIN_DURATION_SECONDS = 30
    _MAX_THRESHOLD_SECONDS = 240

    def __init__(self, scrobbler: LastfmScrobbler):
        self._scrobbler = scrobbler
        self._track_key: tuple[str, str, str] | None = None
        self._started_at = 0.0
        self._announced = False
        self._scrobbled = False

    def update(
        self,
        artist: str,
        track: str,
        album: str,
        duration: float | None,
        elapsed: float | None,
        is_playing: bool,
    ) -> None:
        if not artist or not track:
            self.clear()
            return

        track_key = (artist, track, album)
        if track_key != self._track_key:
            self._track_key = track_key
            self._started_at = time.time() - (elapsed or 0)
            self._announced = False
            self._scrobbled = False

        if not is_playing:
            return

        if not self._announced:
            self._announced = self._scrobbler.update_now_playing(
                artist, track, album, _int_or_none(duration)
            )

        if self._scrobbled or not duration or duration < self._MIN_DURATION_SECONDS:
            return

        threshold = min(duration / 2, self._MAX_THRESHOLD_SECONDS)
        if (elapsed or 0) >= threshold:
            self._scrobbled = self._scrobbler.scrobble(
                artist, track, int(self._started_at), album, _int_or_none(duration)
            )

    def clear(self) -> None:
        self._track_key = None
        self._started_at = 0.0
        self._announced = False
        self._scrobbled = False


def _int_or_none(value: float | None) -> int | None:
    return None if value is None else int(value)
