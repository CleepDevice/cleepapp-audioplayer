# CHANGELOG

## [UNRELEASED]
### Fixed
- Fix documentation

### Updated
- Migrate to Cleep components

## [1.2.0] - 2023-03-11
### Fixed
- When playback stopped on UI, player stays alive

### Added
- Add way to configure repeat/shuffle playlist options at player creation
- Add function to start playback of specific playlist track

## [1.1.0] - 2022-01-14
### Added
_ Create player silently (do not start music after player created)
_ Add shuffle playlist option after playlist repeated
_ Improve command parameters checking
_ Add force_play and force_pause to pause_playback command to force player state
_ Add volume parameter to pause_playback to change player volume at once
_ Update event returns internal state instead of Gst state

### Fixed
- Fix issue checking parameters of add_tracks command

## [1.0.0] - 2021-11-26
### Added
- First release

