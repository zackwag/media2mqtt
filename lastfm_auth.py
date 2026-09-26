"""One-time helper to obtain a Last.fm session key for media2mqtt.

Run manually, not as part of the service:

    python3 lastfm_auth.py <api_key> <api_secret>

Get an API key/secret at https://www.last.fm/api/account/create.

This prints an authorization URL - open it on any device (this machine, your
phone, whatever's handy if media2mqtt runs headlessly, since Last.fm has no
mechanism to call back to a script) and approve access there. Meanwhile the
script polls Last.fm until it detects the approval, then prints a
LASTFM_SESSION_KEY to add to your config alongside LASTFM_API_KEY and
LASTFM_API_SECRET.
"""

from __future__ import annotations

import sys
import time

from scrobbler import (
    ERROR_TOKEN_NOT_AUTHORIZED,
    LastfmApiError,
    auth_url,
    get_auth_token,
    get_session_key,
)

_POLL_INTERVAL_SECONDS = 5
_TIMEOUT_SECONDS = 300


def main() -> None:
    if len(sys.argv) != 3:
        print("Usage: python3 lastfm_auth.py <api_key> <api_secret>")
        sys.exit(1)
    api_key, api_secret = sys.argv[1], sys.argv[2]

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
            print("\nApproved. Add these to your config:\n")
            print(f"LASTFM_API_KEY={api_key}")
            print(f"LASTFM_API_SECRET={api_secret}")
            print(f"LASTFM_SESSION_KEY={session_key}")
            return

    print(f"Timed out after {_TIMEOUT_SECONDS}s waiting for approval.")
    sys.exit(1)


if __name__ == "__main__":
    main()
