# Audioplayer

This application implements a generic audio player to allow your device to play stream or local files.

![alt text](https://github.com/tangb/cleepapp-audioplayer/raw/master/resources/background.jpg)

## Features

* This application does not handle files, it only offers playback capabilities.
* Multiple players can be created, there is no priority on playback for now.
* A playlist per player is created
* Individual player volume control
* Usual player controls are implemented (play, pause, stop, next, previous)

### Supported formats

Mp3, ogg, aac and flac format are supported but technically other formats can be supported thanks to Gstreamer that is used internally.
For more information take a look at [Gstreamer](https://gstreamer.freedesktop.org/) website.

### Audio metadata

The player is able to cast metadata of played resource only. It does not parse audio files specifically to retrieve all metadata.

### Playlist

Minimalist efforts on playlist are available:
* remove track from playlist
* add track on specific playlist position

## Player cycle life

A player is alive until there is no track to play in its playlist.

A player in pause state stays alive indefinitely

