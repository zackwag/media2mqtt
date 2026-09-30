@AGENTS.md

# Claude notes

Things that aren't obvious from reading a single file. `AGENTS.md` above covers setup, commands, structure, and commit conventions.

## Before committing

Run `ruff format . && ruff check . && pytest`. Ruff is enforced in CI; pytest is not, so it's on you.

## Entity identity is derived from `DEVICE_NAME`

Every discovery object ID, `unique_id`, device identifier (`media2mqtt_<slug>`), and state/command topic is built from `_slugify(DEVICE_NAME)` (defaults to the Mac's hostname). Changing the slug scheme or topic layout orphans existing Home Assistant entities and creates new ones — treat it as a breaking change. All discovery and state messages are published `retain=True`, `qos=1`; discovery must stay retained because both HA and the coordinator rely on replaying it.

## The `media_player` entity is not core Home Assistant

Core HA MQTT has no `media_player` discovery schema. `publish_media_player_discovery` targets the third-party HACS integration [bkbilly/mqtt_media_player](https://github.com/bkbilly/mqtt_media_player), which has its own quirks:

- It listens on a hardcoded `homeassistant/media_player/#`, so the entity only appears when `MQTT_DISCOVERY_PREFIX` is the default.
- It ignores any `unique_id` in the payload; the entity's unique ID is the topic segment before `/config` (our `object_id`).
- It parses duration/position with `int()`, hence `_as_int_str` — don't send raw fractional seconds.
- Renaming one of its entity IDs in HA stops the entity updating until HA restarts. This is an upstream bug (fix proposed in bkbilly/mqtt_media_player#7), not a media2mqtt bug.
- Reloading its config entry clears our retained discovery config (its `async_unload_entry` publishes an empty payload, meant for entry deletion), and media2mqtt only publishes discovery at startup. After a reload, restart media2mqtt. Don't suggest reload as a workaround. Also fixed in bkbilly/mqtt_media_player#7.

Sensors (`sensor.*`) use core HA MQTT discovery and have none of these issues.

## Coordinator contract

`coordinator.py` finds devices by subscribing to `<discovery_prefix>/media_player/+/config` and keeping any payload whose `device.identifiers` starts with `media2mqtt_`. It then reads the `state_*_topic` / `command_*_topic` keys from that payload to route state and commands. Renaming those keys in `mqtt_publisher.py` breaks the coordinator.

`coordinator.py` is intentionally self-contained (only depends on `paho-mqtt`, duplicates `_slugify`) because it ships as a separate Homebrew formula and runs on non-Mac hosts. Don't import from the other modules.

## Threading

paho's network loop runs on its own thread. `_on_message` only enqueues; commands and volume changes run one at a time on a worker thread (`_process_commands`) so a slow `nowplaying-cli` call can't stall keepalive. Keep handlers off the network thread.

## Last.fm credentials

`DEFAULT_API_KEY` / `DEFAULT_API_SECRET` in `scrobbler.py` are media2mqtt's shared Last.fm app credentials, committed on purpose and allowlisted in `.gitguardian.yaml` — don't "fix" them. A user's `LASTFM_SESSION_KEY` is a real per-account secret: never commit, log, or publish it to MQTT. Scrobbling is per-Mac only; the coordinator never scrobbles.

## Distribution and releases

- Primary install path is Homebrew (`zackwag/tap/media2mqtt` and `media2mqtt-coordinator`), formulas live in the separate `zackwag/homebrew-tap` repo. `install.sh` is the manual launchd alternative and copies an explicit file list — add any new runtime module there.
- Versioning is release-please (`release-type: simple`): don't hand-edit `CHANGELOG.md` or `.release-please-manifest.json`. Merging the release PR tags `vX.Y.Z`, and `release.yml` then opens and auto-merges a PR bumping both formulas in the tap.
- Commit type drives the version bump: `feat:` → minor, `fix:` → patch.
