# Contributing to media2mqtt

Thanks for your interest in improving media2mqtt, which publishes macOS media app playback state to Home Assistant via MQTT Discovery.

## Getting started

```sh
git clone https://github.com/zackwag/media2mqtt.git
cd media2mqtt
pip install -r requirements.txt
pip install pytest
```

## Development

The app polls macOS media apps (Music, Podcasts) via `osascript` and publishes state over MQTT. Core logic lives in `media_apps.py` and `mqtt_publisher.py`, entry point is `main.py`.

Run the test suite:

```sh
pytest
```

`install.sh` / `uninstall.sh` manage the launchd service (`com.media2mqtt.plist`) for running this persistently on macOS.

## Commit messages and pull requests

This repo uses [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`, etc.). Pull requests are squash-merged, and the **PR title** becomes the commit on `main` — so PR titles must follow this format. This is enforced automatically by the "Conventional Commits" check.

Direct pushes to `main` are allowed but must also use a Conventional Commits-formatted commit message (validated by the same check).

## Opening a pull request

1. Fork the repo and create a branch off `main`.
2. Make your changes.
3. Open a pull request with a Conventional Commits-formatted title.
4. Wait for CI to pass — required checks must be green before merge.

## Reporting issues

Use [GitHub Issues](../../issues) for bugs and feature requests.
