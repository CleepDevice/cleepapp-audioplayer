# Audioplayer [![Coverage Status](https://coveralls.io/repos/github/CleepDevice/cleepapp-audioplayer/badge.svg?branch=master)](https://coveralls.io/github/CleepDevice/cleepapp-audioplayer?branch=master)

This application implements a generic audio player to allow your device to play stream or local files.

![alt text](https://github.com/CleepDevice/cleepapp-audioplayer/raw/master/resources/background.jpg)

## Features

* This application does not handle files, it only offers playback capabilities.
* Multiple players can be created, there is no priority on playback for now.
* A playlist per player is created
* Individual player volume control
* Usual player controls are implemented (play, pause, stop, next, previous)
* Pause keeps the player alive for fast resume (stop destroys it)
* Optional fade-in / fade-out
* Optional playlist crossfade (`crossfade_ms`): overlapping track transitions via audiomixer

### Supported formats

Mp3, ogg, aac and flac formats are supported through GStreamer playbin.
For more information take a look at [Gstreamer](https://gstreamer.freedesktop.org/) website.

### Crossfade

When `crossfade_ms` is greater than 0 (config UI or `set_crossfade` command),
players use a dual-channel `audiomixer` engine instead of playbin for playback.
Near the end of a track, the next playlist item is started while the current
one fades out (true overlap). Set to `0` to keep hard cuts on playbin.

Requires `gstreamer1.0-plugins-base` (`audiomixer`).

### Audio metadata

The player is able to cast metadata of played resource only. It does not parse audio files specifically to retrieve all metadata.

### Playlist

Some playlist features are available:
* remove track from playlist
* add track on specific playlist position
* shuffle tracks
* repeat playlist when end reached

## Player lifecycle

A player is alive until there is no track to play in its playlist.

A player in pause state stays alive indefinitely.

A player with repeat enabled on playlist will play forever.

