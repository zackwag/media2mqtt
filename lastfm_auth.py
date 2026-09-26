"""One-time helper to obtain a Last.fm session key for media2mqtt.

Run manually, not as part of the service:

    python3 lastfm_auth.py

Uses media2mqtt's shared Last.fm application credentials by default (see
DEFAULT_API_KEY in scrobbler.py). If you'd rather use your own Last.fm API
account (from https://www.last.fm/api/account/create), pass it explicitly:

    python3 lastfm_auth.py <api_key> <api_secret>

This prints an authorization URL - open it on any device (this machine, your
phone, whatever's handy if media2mqtt runs headlessly, since Last.fm has no
mechanism to call back to a script) and approve access there. Meanwhile the
script polls Last.fm until it detects the approval, then prints a
LASTFM_SESSION_KEY to add to your config.
"""

from __future__ import annotations

import sys
import time

from scrobbler import (
    DEFAULT_API_KEY,
    DEFAULT_API_SECRET,
    ERROR_TOKEN_NOT_AUTHORIZED,
    LastfmApiError,
    auth_url,
    get_auth_token,
    get_session_key,
)

_POLL_INTERVAL_SECONDS = 5
_TIMEOUT_SECONDS = 300


def main() -> None:
    if len(sys.argv) == 1:
        api_key, api_secret = DEFAULT_API_KEY, DEFAULT_API_SECRET
    elif len(sys.argv) == 3:
        api_key, api_secret = sys.argv[1], sys.argv[2]
    else:
        print("Usage: python3 lastfm_auth.py [api_key api_secret]")
        sys.exit(1)

    token = get_auth_token(api_key, api_secret)
    print("Open this URL and approve access, then leave this running:\n")
    print(f"  {auth_url(api_key, token)}\n")
    print(f"Waiting for approval (polling every {_POLL_INTERVAL_SECONDS}s)...")

    deadline = time.monotonic() + _TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            session_key = get_session_key(api_key, api_secret, token)
        except LastfmApiError as exc:
            if exc.code == ERROR_TOKEN_NOT_AUTHORIZED:
                time.sleep(_POLL_INTERVAL_SECONDS)
                continue
            print(f"Last.fm rejected the request: {exc}")
            sys.exit(1)
        else:
            print("\nApproved. Add this to your config:\n")
            print(f"LASTFM_SESSION_KEY={session_key}")
            if api_key != DEFAULT_API_KEY:
                print(f"LASTFM_API_KEY={api_key}")
                print(f"LASTFM_API_SECRET={api_secret}")
            return

    print(f"Timed out after {_TIMEOUT_SECONDS}s waiting for approval.")
    sys.exit(1)


if __name__ == "__main__":
    main()
