# AGENTS.md

## Project overview

Publishes macOS media app (Music, Podcasts) playback state to Home Assistant via MQTT Discovery. Python, polls apps via `osascript`, publishes with `paho-mqtt`. Runs as a macOS launchd service.

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

`test_media_apps.py` covers `media_apps.py` by mocking `osascript` calls. Note: this suite exists but is **not currently run in CI** — only `conventional-commits.yml` and `release.yml` run on this repo.

## Repository structure

- `main.py` — entry point, polling loop
- `media_apps.py` — macOS media app state via `osascript`
- `mqtt_publisher.py` — MQTT Discovery publishing, command topic subscription
- `playback_control.py` — executes `nowplaying-cli` playback commands
- `test_media_apps.py` — pytest suite for `media_apps.py`
- `install.sh` / `uninstall.sh` / `com.media2mqtt.plist` — launchd service management

## Commit and PR conventions

- Commit messages and PR titles must follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`, `ci:`, `build:`, `perf:`, `style:`, `revert:`), optionally with a scope, e.g. `fix(api): handle null response`.
- This repo squash-merges pull requests only; the PR title becomes the final commit message on `main`.
- A "Conventional Commits" CI check enforces this on both PR titles and direct-push commit messages.
- Branch protection on `main`: no force-pushes, no branch deletion, required status checks must pass.
