# Changelog

## [1.10.0](https://github.com/zackwag/media2mqtt/compare/v1.9.2...v1.10.0) (2026-09-25)


### Features

* add volume control and sticky source tracking ([#34](https://github.com/zackwag/media2mqtt/issues/34)) ([e204e99](https://github.com/zackwag/media2mqtt/commit/e204e99f782553230af8801a613706ee97418312))

## [1.9.2](https://github.com/zackwag/media2mqtt/compare/v1.9.1...v1.9.2) (2026-09-22)


### Bug Fixes

* prioritize playing app over paused in now_playing aggregation ([#29](https://github.com/zackwag/media2mqtt/issues/29)) ([76aa7e9](https://github.com/zackwag/media2mqtt/commit/76aa7e9560b2f75f6d087e0f6e9fc38e412a173c))

## [1.9.1](https://github.com/zackwag/media2mqtt/compare/v1.9.0...v1.9.1) (2026-09-21)


### Bug Fixes

* forward albumart when it changes, not just on device switch ([#27](https://github.com/zackwag/media2mqtt/issues/27)) ([d47d058](https://github.com/zackwag/media2mqtt/commit/d47d05852c8ddb4e6294e2c8a5c5c864bf9b2fcf))

## [1.9.0](https://github.com/zackwag/media2mqtt/compare/v1.8.0...v1.9.0) (2026-09-21)


### Features

* add grouped media_player coordinator for multi-Mac setups ([#25](https://github.com/zackwag/media2mqtt/issues/25)) ([67eb7d1](https://github.com/zackwag/media2mqtt/commit/67eb7d1627e29f7c60e3ff25f089e5e57cf39380))

## [1.8.0](https://github.com/zackwag/media2mqtt/compare/v1.7.0...v1.8.0) (2026-09-21)


### Features

* publish album art to the media_player entity ([#23](https://github.com/zackwag/media2mqtt/issues/23)) ([9446753](https://github.com/zackwag/media2mqtt/commit/94467539bce72494870f234609bdf4a81c65464c))

## [1.7.0](https://github.com/zackwag/media2mqtt/compare/v1.6.2...v1.7.0) (2026-09-21)


### Features

* publish MQTT discovery for a real media_player entity ([#21](https://github.com/zackwag/media2mqtt/issues/21)) ([99bee70](https://github.com/zackwag/media2mqtt/commit/99bee702f9e136369d7c23aad0b459776a0667d1))

## [1.6.2](https://github.com/zackwag/media2mqtt/compare/v1.6.1...v1.6.2) (2026-09-19)


### Bug Fixes

* keep now_playing title/artist while paused, not just playing ([#19](https://github.com/zackwag/media2mqtt/issues/19)) ([1208bf3](https://github.com/zackwag/media2mqtt/commit/1208bf36c38c49cbe77cd73f13b5c9a41318de1f))

## [1.6.1](https://github.com/zackwag/media2mqtt/compare/v1.6.0...v1.6.1) (2026-09-19)


### Bug Fixes

* **ci:** rewrite the url version directly, not a nonexistent version field ([#17](https://github.com/zackwag/media2mqtt/issues/17)) ([7bbe1d5](https://github.com/zackwag/media2mqtt/commit/7bbe1d52d06a93a5482fa6cc0ccf57fa3ff644a9))

## [1.6.0](https://github.com/zackwag/media2mqtt/compare/v1.5.0...v1.6.0) (2026-09-19)


### Features

* add MQTT playback control via nowplaying-cli ([#15](https://github.com/zackwag/media2mqtt/issues/15)) ([275080e](https://github.com/zackwag/media2mqtt/commit/275080e10c6d906dd13e39460cc55329b54a6e05))

## [1.5.0](https://github.com/zackwag/media2mqtt/compare/v1.4.2...v1.5.0) (2026-09-17)


### Features

* **ci:** add ruff lint + format check ([#13](https://github.com/zackwag/media2mqtt/issues/13)) ([b198317](https://github.com/zackwag/media2mqtt/commit/b198317401436bd0270d51800f079f08b408c9b3))

## [1.4.2](https://github.com/zackwag/media2mqtt/compare/v1.4.1...v1.4.2) (2026-09-17)


### Bug Fixes

* **ci:** wait for checks to actually register before polling for completion ([#11](https://github.com/zackwag/media2mqtt/issues/11)) ([f7dd6e6](https://github.com/zackwag/media2mqtt/commit/f7dd6e66e7679518d18777385c42781366869029))

## [1.4.1](https://github.com/zackwag/media2mqtt/compare/v1.4.0...v1.4.1) (2026-09-17)


### Bug Fixes

* **ci:** use RELEASE_PLEASE_TOKEN so releases trigger downstream workflows ([#9](https://github.com/zackwag/media2mqtt/issues/9)) ([1f655f4](https://github.com/zackwag/media2mqtt/commit/1f655f4d25e7044d645b398576a018717a2ca4d5))

## [1.4.0](https://github.com/zackwag/media2mqtt/compare/v1.3.0...v1.4.0) (2026-09-17)


### Features

* **ci:** adopt release-please ([#7](https://github.com/zackwag/media2mqtt/issues/7)) ([a45f788](https://github.com/zackwag/media2mqtt/commit/a45f788360f6801e6e325d557632218adb7a687a))


### Bug Fixes

* **ci:** route homebrew-tap update through a PR instead of a direct push ([#6](https://github.com/zackwag/media2mqtt/issues/6)) ([3a47d46](https://github.com/zackwag/media2mqtt/commit/3a47d4679041052c8bf606a97d5b3147aadf1bea))
