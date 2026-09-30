# AGENTS.md

## Project overview

Publishes macOS media app (Music, Podcasts) playback state to Home Assistant via MQTT Discovery, and optionally scrobbles to Last.fm. Python, polls apps via `osascript`, publishes with `paho-mqtt`. Runs as a macOS launchd service.

## Setup

```sh
pip install -r requirements.txt
pip install pytest
```

## Build / Run

```sh
python3 main.py
```

For persistent background operation on macOS: `./install.sh` (installs `com.media2mqtt.plist` as a launchd service); `./uninstall.sh` to remove it.

## Test

```sh
pytest
```

`test_media_apps.py` covers `media_apps.py` by mocking `osascript` calls; `test_playback_control.py` covers `playback_control.py`; `test_scrobbler.py` covers `scrobbler.py` by mocking `urllib` calls; `test_mqtt_publisher.py` and `test_coordinator.py` cover discovery payloads by mocking the paho client. Note: these suites are **not currently run in CI** — CI runs `conventional-commits.yml`, `lint.yml` (ruff), `release-please.yml`, and `release.yml`.

## Lint

```sh
ruff format --check .
ruff check .
```

Both run in CI (`lint.yml`) on PRs and pushes to `main`. Config is in `ruff.toml` (line length 100).

## Repository structure

- `main.py` — entry point, polling loop
- `media_apps.py` — macOS media app state via `osascript`
- `mqtt_publisher.py` — MQTT Discovery publishing, command topic subscription
- `playback_control.py` — executes `nowplaying-cli` playback commands
- `scrobbler.py` — Last.fm API client and now-playing/scrobble threshold tracking
- `lastfm_auth.py` — one-time manual script to obtain a Last.fm session key
- `coordinator.py` — standalone grouped `media_player` that aggregates multiple Macs (no macOS dependencies)
- `test_media_apps.py` / `test_playback_control.py` / `test_scrobbler.py` / `test_mqtt_publisher.py` / `test_coordinator.py` — pytest suites
- `install.sh` / `uninstall.sh` / `com.media2mqtt.plist` — launchd service management

## Commit and PR conventions

- Commit messages and PR titles must follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `ci:`, `build:`, `perf:`, `style:`, `revert:`), optionally with a scope, e.g. `fix(api): handle null response`.
- This repo squash-merges pull requests only; the PR title becomes the final commit message on `main`.
- A "Conventional Commits" CI check enforces this on both PR titles and direct-push commit messages.
- Branch protection on `main`: no force-pushes, no branch deletion, required status checks must pass.
