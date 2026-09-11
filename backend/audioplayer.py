#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import random
import time
from pathlib import Path
from urllib.parse import urlparse
import gi

# pylint: disable=C0413
gi.require_version("Gst", "1.0")
from gi.repository import Gst
import magic
from cleep.exception import (
    MissingParameter,
    InvalidParameter,
    CommandError,
    CommandInfo,
)
from cleep.core import CleepModule
from cleep.common import CATEGORIES


class Audioplayer(CleepModule):
    """
    Audioplayer application

    Generic audio player based on GStreamer playbin.
    Players stay alive while paused for fast resume; stop destroys the player.
    """

    MODULE_AUTHOR = "Cleep"
    MODULE_VERSION = "1.4.0"
    MODULE_DEPS = []
    MODULE_DESCRIPTION = "Enjoy music playback"
    MODULE_LONGDESCRIPTION = (
        "This application provides a common way to play audio media on your device.<br>"
        "Application features: <ul>"
        "<li>Play most used audio formats (mp3, flac, ogg and aac)</li>"
        "<li>Play local file and remote streams</li>"
        "<li>Read audio metadata when available</li>"
        "<li>Implement minimalist player playlist</li>"
        "<li>Fade in/out support</li>"
        "<li>Propagate significative player events</li>"
        "</ul>"
    )
    MODULE_TAGS = ["audio", "music", "playback", "player"]
    MODULE_CATEGORY = CATEGORIES.MEDIA
    MODULE_URLINFO = "https://github.com/CleepDevice/cleepapp-audioplayer"
    MODULE_URLHELP = None
    MODULE_URLSITE = None
    MODULE_URLBUGS = "https://github.com/CleepDevice/cleepapp-audioplayer/issues"

    MODULE_CONFIG_FILE = "audioplayer.conf"
    DEFAULT_CONFIG = {
        "audio_sink": "auto",  # auto | alsa
        "alsa_device": "default",
        "fade_in_ms": 0,
        "fade_out_ms": 0,
    }

    # Supported audio formats (mime). playbin decodes them; list is used for validation.
    SUPPORTED_AUDIO_FORMATS = [
        "audio/mpeg",
        "audio/flac",
        "audio/ogg",
        "audio/x-hx-aac-adts",
        "audio/x-hx-aac-adif",
        "audio/aac",
    ]
    # Backward-compatible alias used by older callers/tests
    AUDIO_PIPELINE_ELEMENTS = {fmt: True for fmt in SUPPORTED_AUDIO_FORMATS}

    MAX_PLAYLIST_TRACKS = 20

    # playbin flags: AUDIO | SOFT_VOLUME (enables playbin volume property)
    PLAYBIN_FLAGS = 0x00000002 | 0x00000010

    PLAYER_STATES = {
        Gst.State.VOID_PENDING: "stopped",
        Gst.State.NULL: "stopped",
        Gst.State.READY: "stopped",
        Gst.State.PAUSED: "paused",
        Gst.State.PLAYING: "playing",
    }

    def __init__(self, bootstrap, debug_enabled):
        """
        Constructor

        Args:
            bootstrap (dict): bootstrap objects
            debug_enabled: debug status
        """
        CleepModule.__init__(self, bootstrap, debug_enabled)

        # list of players. Players are volatile data and must be hold by creator::
        #   {
        #       player_uuid (string): {
        #           see list of fields in __create_player
        #       },
        #       ...
        #   }
        self.players = {}
        self.event_playback_update = self._get_event("audioplayer.playback.update")

    def _configure(self):
        """
        Configure module.
        """
        Gst.init(None)

    def _on_stop(self):
        """
        Stop module
        """
        players_to_delete = list(self.players.keys())
        self.logger.debug("Players to delete: %s", players_to_delete)
        for player_uuid in players_to_delete:
            self.__destroy_player(self.players[player_uuid])

    def __create_player(self):
        """
        Create player structure with a ready playbin instance

        Returns:
            dict: player structure
        """
        player = {
            "uuid": self._get_unique_id(),
            "playlist": {
                "index": None,
                "duration": None,
                "tracks": [],
                "repeat": False,
                "shuffle": False,
                "volume": 0,
                "metadata": None,
            },
            "player": None,
            "internal": {
                "to_destroy": False,
                "tags_sent": False,
                "last_state": Gst.State.NULL,
                "target_volume": 1.0,
                "fade": None,
            },
        }
        self.__create_playbin(player)
        return player

    def __create_playbin(self, player):
        """
        Create and configure GStreamer playbin for player

        Args:
            player (dict): player structure
        """
        playbin = Gst.ElementFactory.make("playbin", player["uuid"])
        if not playbin:
            raise Exception("Unable to create GStreamer playbin")

        playbin.set_property("flags", self.PLAYBIN_FLAGS)

        audio_sink_name = self._get_config_field("audio_sink")
        if audio_sink_name == "alsa":
            audio_sink = Gst.ElementFactory.make("alsasink", "audio-sink")
            if not audio_sink:
                raise Exception("Unable to create alsasink")
            audio_sink.set_property("device", self._get_config_field("alsa_device"))
        else:
            audio_sink = Gst.ElementFactory.make("autoaudiosink", "audio-sink")
            if not audio_sink:
                raise Exception("Unable to create autoaudiosink")
        playbin.set_property("audio-sink", audio_sink)

        video_sink = Gst.ElementFactory.make("fakesink", "video-sink")
        if video_sink:
            playbin.set_property("video-sink", video_sink)

        player["player"] = playbin

    # pylint: disable=R0201
    def _destroy_player(self, player):
        """
        Set player destroy flag to True to perform safe player deletion during
        process loop
        """
        player["internal"]["fade"] = None
        player["internal"]["to_destroy"] = True

    def __destroy_player(self, player):
        """
        Destroy player. This method should be exclusively used during app cycle life.
        """
        player["internal"]["fade"] = None
        if player["player"]:
            player["player"].set_state(Gst.State.NULL)
            player["player"] = None
        if player["uuid"] in self.players:
            del self.players[player["uuid"]]

    def _on_process(self):
        """
        On process
        """
        self.__process_fades()
        self.__process_players_messages()

        players_to_delete = [
            player_uuid
            for player_uuid, player in self.players.items()
            if player["internal"]["to_destroy"]
        ]
        if players_to_delete:
            self.logger.debug("Players to delete: %s", players_to_delete)
            for player_uuid in players_to_delete:
                if player_uuid in self.players:
                    self.__destroy_player(self.players[player_uuid])

    def __process_fades(self):
        """
        Advance active volume fades
        """
        now = time.monotonic()
        for player_uuid, player in list(self.players.items()):
            fade = player["internal"].get("fade")
            if not fade or not player["player"]:
                continue

            duration_ms = max(fade["duration_ms"], 1)
            progress = min(1.0, ((now - fade["started_at"]) * 1000.0) / duration_ms)
            volume = fade["start"] + (fade["end"] - fade["start"]) * progress
            try:
                player["player"].set_property("volume", max(0.0, volume))
            except Exception:
                self.logger.exception(
                    'Unable to apply fade volume on player "%s"', player_uuid
                )
                player["internal"]["fade"] = None
                continue

            if progress >= 1.0:
                on_complete = fade.get("on_complete")
                player["internal"]["fade"] = None
                if on_complete:
                    try:
                        on_complete()
                    except Exception:
                        self.logger.exception(
                            'Fade completion failed for player "%s"', player_uuid
                        )

    def __start_fade(self, player_uuid, start, end, duration_ms, on_complete=None):
        """
        Start volume fade on player

        Args:
            player_uuid (str): player identifier
            start (float): start volume (0.0-1.0+)
            end (float): end volume
            duration_ms (int): fade duration in milliseconds
            on_complete (callable): optional callback when fade ends
        """
        if duration_ms <= 0 or player_uuid not in self.players:
            if on_complete:
                on_complete()
            return

        player = self.players[player_uuid]
        player["internal"]["fade"] = {
            "start": start,
            "end": end,
            "duration_ms": duration_ms,
            "started_at": time.monotonic(),
            "on_complete": on_complete,
        }
        if player["player"]:
            player["player"].set_property("volume", start)

    def __cancel_fade(self, player_uuid):
        """
        Cancel active fade if any
        """
        if player_uuid in self.players:
            self.players[player_uuid]["internal"]["fade"] = None

    def __process_players_messages(self):
        """
        Process all players messages
        """
        for player_uuid, player in list(self.players.items()):
            if not player["player"] or player["internal"]["to_destroy"]:
                continue
            try:
                bus = player["player"].get_bus()
                message = bus.pop()
                while message:
                    self.__process_gstreamer_message(
                        player_uuid, player["player"], message
                    )
                    del message
                    message = bus.pop()
            except Exception:
                self.logger.exception(
                    'Error processing player "%s" messages', player_uuid
                )

    def __process_gstreamer_message(self, player_uuid, player, message):
        """
        Process gstreamer message

        Args:
            player_uuid (string): player identifier
            player (Gst.Element): playbin
            message (Gst.Message): message to process
        """
        message_type = message.type
        self.logger.trace('Player "%s" received message: %s', player_uuid, message_type)
        if message_type == Gst.MessageType.EOS:
            self.logger.debug('Player "%s" EOS: end of stream', player_uuid)
            player.set_state(Gst.State.NULL)
            self.__play_next_track(player_uuid)
            self.__send_playback_event(player_uuid, player)
        elif message_type == Gst.MessageType.STATE_CHANGED:
            # only handle messages from playbin itself (src may be unset in tests)
            if getattr(message, "src", None) in (None, player):
                self.__send_playback_event(player_uuid, player)
        elif message_type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            self.logger.error(
                'Player "%s" ERROR: error=%s debug=%s', player_uuid, error, debug
            )
            player.set_state(Gst.State.NULL)
            self.__send_playback_event(player_uuid, player)
        elif (
            message_type == Gst.MessageType.TAG
            and player_uuid in self.players
            and not self.players[player_uuid]["internal"]["tags_sent"]
        ):
            tags = message.parse_tag()
            complete, metadata = self.__get_audio_metadata(tags)
            self.logger.debug(
                'Player "%s" TAG [complete=%s]: %s', player_uuid, complete, metadata
            )
            if complete:
                self.players[player_uuid]["playlist"]["metadata"] = metadata
                self.__send_playback_event(player_uuid, player, force=True)
                self.players[player_uuid]["internal"]["tags_sent"] = complete
        elif message_type == Gst.MessageType.DURATION_CHANGED:
            self.logger.debug('Player "%s" DURATION_CHANGED', player_uuid)
            self.__send_playback_event(player_uuid, player)

    def __send_playback_event(self, player_uuid, player, force=False):
        """
        Send current playback state using event

        Args:
            player_uuid (string): player identifier
            player (Gst.Element): playbin
            force (bool): bypass excessive sending control
        """
        if player_uuid not in self.players:
            return

        _, current_state, _ = player.get_state(1)
        if not force and current_state in (
            self.players[player_uuid]["internal"]["last_state"],
            Gst.State.READY,
        ):
            return
        player_data = self.players[player_uuid]
        player_data["internal"]["last_state"] = current_state

        duration_true, duration = player.query_duration(Gst.Format.TIME)
        duration = int(duration / 1000000000) if duration_true else None
        if duration:
            player_data["playlist"]["duration"] = duration

        playback_info = self.__get_playback_info(player_uuid)
        self.event_playback_update.send(playback_info)

    def __get_playback_info(self, player_uuid):
        """
        Return current player playback info
        """
        if player_uuid not in self.players:
            return {
                "index": 0,
                "playeruuid": player_uuid,
                "track": None,
                "metadata": {},
                "state": self._get_player_state(Gst.State.NULL),
                "duration": 0,
            }

        player = self.players[player_uuid]
        index = player["playlist"]["index"]
        track = None
        if index is not None and 0 <= index < len(player["playlist"]["tracks"]):
            track = player["playlist"]["tracks"][index]

        return {
            "index": index,
            "playeruuid": player_uuid,
            "track": track,
            "metadata": player["playlist"]["metadata"],
            "state": self._get_player_state(player["internal"]["last_state"]),
            "duration": player["playlist"]["duration"],
        }

    def __get_audio_metadata(self, tags):
        """
        Get audio tags from message
        """
        metadata = {
            "album": None,
            "artist": None,
            "year": None,
            "genre": None,
            "track": None,
            "title": None,
            "channels": None,
            "bitratemin": None,
            "bitratemax": None,
            "bitrateavg": None,
        }

        self.logger.trace("All tags: %s", tags.to_string())
        for index in range(tags.n_tags()):
            tag_name = tags.nth_tag_name(index)
            self.logger.trace(" => tag name: %s", tag_name)
            if tag_name in ("artist", "album-artist"):
                metadata["artist"] = tags.get_string(tag_name)[1]
            elif tag_name == "album":
                metadata["album"] = tags.get_string(tag_name)[1]
            elif tag_name == "title":
                metadata["title"] = tags.get_string(tag_name)[1]
            elif tag_name == "genre":
                metadata["genre"] = tags.get_string(tag_name)[1]
            elif tag_name == "track-number":
                tracktrue, track = tags.get_uint(tag_name)
                if not tracktrue:
                    tracktrue, track = tags.get_string(tag_name)
                if tracktrue and track:
                    metadata["track"] = track
            elif tag_name == "datetime":
                datetrue, datetime = tags.get_date_time(tag_name)
                if datetrue and datetime.has_year():
                    metadata["year"] = datetime.get_year()
            elif tag_name == "channel-mode":
                metadata["channels"] = tags.get_string(tag_name)[1]
            elif tag_name == "minimum-bitrate":
                bitratetrue, bitrate = tags.get_uint(tag_name)
                if bitratetrue:
                    metadata["bitratemin"] = bitrate
            elif tag_name == "maximum-bitrate":
                bitratetrue, bitrate = tags.get_uint(tag_name)
                if bitratetrue:
                    metadata["bitratemax"] = bitrate
            elif tag_name == "bitrate":
                bitratetrue, bitrate = tags.get_uint(tag_name)
                if bitratetrue:
                    metadata["bitrateavg"] = bitrate

        return metadata["bitrateavg"] is not None, metadata

    def __get_file_audio_format(self, filepath):
        """
        Return file audio format if supported
        """
        try:
            mime = magic.from_file(filepath, mime=True)
            return mime if mime in self.SUPPORTED_AUDIO_FORMATS else None
        except Exception:
            self.logger.exception("Error getting file format")
            return None

    def __is_supported_audio_format(self, audio_format):
        """
        Return True if audio format is supported (None allowed)
        """
        return audio_format is None or audio_format in self.SUPPORTED_AUDIO_FORMATS

    @staticmethod
    def _is_filepath(resource):
        """
        Return True if resource is a filepath
        """
        if os.path.exists(resource):
            return True

        if urlparse(resource).scheme in ("http", "https"):
            return False

        raise Exception("Resource is invalid (file may not exist)")

    @staticmethod
    def _make_track(resource, audio_format):
        """
        Create track dict
        """
        return {
            "resource": resource,
            "audio_format": audio_format,
        }

    def __resource_to_uri(self, resource):
        """
        Convert resource path/url to playbin URI
        """
        if Audioplayer._is_filepath(resource):
            return Path(os.path.abspath(resource)).as_uri()
        return resource

    def _set_audio_sink(self, audio_sink, alsa_device=None):
        """
        Internal helper to configure audio sink used by new players.
        Not exposed as a public command: hardware apps will drive this later.

        Args:
            audio_sink (str): "auto" or "alsa"
            alsa_device (str): ALSA device name when audio_sink is alsa
        """
        if audio_sink not in ("auto", "alsa"):
            raise InvalidParameter('Audio sink must be "auto" or "alsa"')
        self._set_config_field("audio_sink", audio_sink)
        if alsa_device is not None:
            self._set_config_field("alsa_device", alsa_device)

    def set_fade(self, fade_in_ms, fade_out_ms):
        """
        Configure default fade durations

        Args:
            fade_in_ms (int): fade-in duration in milliseconds (0 disables)
            fade_out_ms (int): fade-out duration in milliseconds (0 disables)
        """
        self._check_parameters(
            [
                {
                    "name": "fade_in_ms",
                    "value": fade_in_ms,
                    "type": int,
                    "validator": lambda v: v >= 0,
                    "message": "fade_in_ms must be >= 0",
                },
                {
                    "name": "fade_out_ms",
                    "value": fade_out_ms,
                    "type": int,
                    "validator": lambda v: v >= 0,
                    "message": "fade_out_ms must be >= 0",
                },
            ]
        )
        self._set_config_field("fade_in_ms", fade_in_ms)
        self._set_config_field("fade_out_ms", fade_out_ms)

    def add_track(self, player_uuid, resource, audio_format=None, track_index=None):
        """
        Add track in specified player playlist.
        """
        self._check_parameters(
            [
                {
                    "name": "player_uuid",
                    "value": player_uuid,
                    "type": str,
                    "validator": lambda v: v in self.players,
                    "message": f'Player "{player_uuid}" does not exist',
                },
                {"name": "resource", "value": resource, "type": str},
                {
                    "name": "audio_format",
                    "value": audio_format,
                    "type": str,
                    "none": True,
                    "validator": self.__is_supported_audio_format,
                    "message": f'Audio format "{audio_format}" is not supported',
                },
                {
                    "name": "track_number",
                    "value": track_index,
                    "type": int,
                    "none": True,
                },
            ]
        )
        if not Audioplayer._is_filepath(resource) and not audio_format:
            raise MissingParameter("Url resource must have audio_format specified")

        if (
            len(self.players[player_uuid]["playlist"]["tracks"])
            > self.MAX_PLAYLIST_TRACKS
        ):
            return False

        self.logger.info(
            'Audio resource "%s" added to player "%s" playlist at position %s',
            resource,
            player_uuid,
            track_index,
        )
        track = Audioplayer._make_track(resource, audio_format)
        track_index = (
            track_index
            if track_index is not None
            else len(self.players[player_uuid]["playlist"]["tracks"])
        )
        self.players[player_uuid]["playlist"]["tracks"].insert(track_index, track)
        self.logger.debug(
            'Player "%s" playlist: %s',
            player_uuid,
            self.players[player_uuid]["playlist"],
        )

        return True

    def add_tracks(self, player_uuid, tracks):
        """
        Add multiple tracks at once
        """
        self._check_parameters([{"name": "tracks", "value": tracks, "type": list}])

        for track in tracks:
            if not self.add_track(
                player_uuid, track["resource"], track["audio_format"]
            ):
                raise CommandInfo("All tracks were not added (playlist limit reached)")

    def remove_track(self, player_uuid, track_index):
        """
        Remove track from player playlist
        """
        self._check_parameters(
            [
                {
                    "name": "player_uuid",
                    "value": player_uuid,
                    "type": str,
                    "validator": lambda v: v in self.players,
                    "message": f'Player "{player_uuid}" does not exist',
                },
                {
                    "name": "track_index",
                    "value": track_index,
                    "type": int,
                    "validator": lambda v: 0
                    <= v
                    < len(self.players[player_uuid]["playlist"]["tracks"]),
                    "message": "Track index is invalid",
                },
                {
                    "name": "track_index",
                    "value": track_index,
                    "type": int,
                    "validator": lambda v: v
                    != self.players[player_uuid]["playlist"]["index"],
                    "message": "You can't remove current track",
                },
            ]
        )

        removed_track = self.players[player_uuid]["playlist"]["tracks"].pop(track_index)
        self.logger.debug(
            'Player "%s" has track removed: %s', player_uuid, removed_track
        )

    def start_playback(
        self,
        resource,
        audio_format=None,
        volume=100,
        paused=False,
        repeat=False,
        shuffle=False,
    ):
        """
        Create a player and start playing specified resource

        Returns:
            string: player identifier
        """
        self._check_parameters(
            [
                {"name": "resource", "value": resource, "type": str, "none": True},
                {
                    "name": "audio_format",
                    "value": audio_format,
                    "type": str,
                    "none": True,
                    "validator": self.__is_supported_audio_format,
                    "message": f"Audio format {audio_format} is not supported",
                },
                {
                    "name": "volume",
                    "value": volume,
                    "type": int,
                    "validator": lambda v: 0 < v <= 100,
                    "message": "Volume must be between 1 and 100",
                },
                {"name": "paused", "value": paused, "type": bool},
                {"name": "repeat", "value": repeat, "type": bool},
                {"name": "shuffle", "value": shuffle, "type": bool},
            ]
        )

        player = self.__create_player()
        track = Audioplayer._make_track(resource, audio_format)
        player["playlist"]["index"] = 0
        player["playlist"]["volume"] = volume
        player["playlist"]["tracks"].append(track)
        self.players[player["uuid"]] = player

        self.set_repeat(player["uuid"], repeat, shuffle)

        try:
            self.__play_track(track, player["uuid"], volume, paused)
            return player["uuid"]
        except Exception as error:
            self.logger.exception("Unable to play resource %s", resource)
            self.__destroy_player(player)
            raise CommandError("Unable to play resource") from error

    def __play_track(self, track, player_uuid, volume=None, paused=False):
        """
        Play track on existing playbin (reuses playbin, only changes URI)
        """
        if player_uuid not in self.players:
            raise CommandError(f'Player "{player_uuid}" does not exist')

        player = self.players[player_uuid]
        playbin = player["player"]
        if not playbin:
            self.__create_playbin(player)
            playbin = player["player"]

        self.__cancel_fade(player_uuid)

        if Audioplayer._is_filepath(track["resource"]):
            audio_format = self.__get_file_audio_format(track["resource"])
            if not audio_format:
                raise CommandError("Audio file not supported")
            track["audio_format"] = audio_format

        try:
            playbin.set_state(Gst.State.NULL)

            uri = self.__resource_to_uri(track["resource"])
            playbin.set_property("uri", uri)

            volume = volume if volume is not None else player["playlist"]["volume"]
            target_volume = float(volume / 100.0)
            player["internal"]["target_volume"] = target_volume
            player["playlist"]["volume"] = volume
            player["playlist"]["metadata"] = None
            player["internal"]["tags_sent"] = False
            player["playlist"]["duration"] = None
            player["internal"]["last_state"] = Gst.State.NULL

            fade_in_ms = self._get_config_field("fade_in_ms")
            if paused:
                playbin.set_property("volume", target_volume)
                playbin.set_state(Gst.State.PAUSED)
                player["internal"]["last_state"] = Gst.State.PAUSED
                self.logger.info(
                    'Player "%s" created paused for %s', player_uuid, track
                )
            elif fade_in_ms > 0:
                playbin.set_property("volume", 0.0)
                playbin.set_state(Gst.State.PLAYING)
                player["internal"]["last_state"] = Gst.State.PLAYING
                self.__start_fade(player_uuid, 0.0, target_volume, fade_in_ms)
                self.logger.info('Player "%s" is playing %s (fade-in)', player_uuid, track)
            else:
                playbin.set_property("volume", target_volume)
                playbin.set_state(Gst.State.PLAYING)
                player["internal"]["last_state"] = Gst.State.PLAYING
                self.logger.info('Player "%s" is playing %s', player_uuid, track)
        except Exception as error:
            self.logger.exception("Error playing track %s with %s", track, player_uuid)
            raise error

    def _get_track_index(self, player_uuid, track):
        """
        Search track index in player playlist
        """
        return next(
            (
                index
                for index, atrack in enumerate(
                    self.players[player_uuid]["playlist"]["tracks"]
                )
                if atrack["resource"] == track["resource"]
            ),
            0,
        )

    def pause_playback(
        self, player_uuid, force_pause=False, force_play=False, volume=None
    ):
        """
        Toggle pause status for specified player.
        Player stays alive: resume is fast (no playbin rebuild).
        """
        self._check_parameters(
            [
                {
                    "name": "player_uuid",
                    "value": player_uuid,
                    "type": str,
                    "validator": lambda v: v in self.players,
                    "message": f'Player "{player_uuid}" does not exist',
                },
                {
                    "name": "volume",
                    "value": volume,
                    "type": int,
                    "none": True,
                    "validator": lambda v: 0 < v <= 100,
                    "message": "Volume must be between 1 and 100",
                },
                {"name": "force_pause", "value": force_pause, "type": bool},
                {"name": "force_play", "value": force_play, "type": bool},
            ]
        )

        if volume:
            self._set_volume(player_uuid, volume)

        player = self.players[player_uuid]
        playbin = player["player"]
        new_state = Gst.State.PAUSED if force_pause else Gst.State.PLAYING
        if (force_pause and force_play) or (not force_pause and not force_play):
            _, current_state, _ = playbin.get_state(1)
            self.logger.debug(
                "Change player %s state from %s", player_uuid, current_state
            )
            new_state = (
                Gst.State.PAUSED
                if current_state == Gst.State.PLAYING
                else Gst.State.PLAYING
            )

        self.__cancel_fade(player_uuid)
        fade_in_ms = self._get_config_field("fade_in_ms")
        fade_out_ms = self._get_config_field("fade_out_ms")
        target_volume = player["internal"].get("target_volume", 1.0)

        if new_state == Gst.State.PAUSED and fade_out_ms > 0:
            current_volume = playbin.get_property("volume")

            def on_fade_out_done():
                if player_uuid not in self.players:
                    return
                self.players[player_uuid]["player"].set_state(Gst.State.PAUSED)
                self.players[player_uuid]["player"].set_property(
                    "volume", target_volume
                )
                self.players[player_uuid]["internal"]["last_state"] = Gst.State.PAUSED

            self.__start_fade(
                player_uuid,
                current_volume,
                0.0,
                fade_out_ms,
                on_complete=on_fade_out_done,
            )
            return self._get_player_state(Gst.State.PAUSED)

        if new_state == Gst.State.PLAYING and fade_in_ms > 0:
            playbin.set_property("volume", 0.0)
            playbin.set_state(Gst.State.PLAYING)
            player["internal"]["last_state"] = Gst.State.PLAYING
            self.__start_fade(player_uuid, 0.0, target_volume, fade_in_ms)
            return self._get_player_state(Gst.State.PLAYING)

        playbin.set_state(new_state)
        player["internal"]["last_state"] = new_state
        return self._get_player_state(new_state)

    def stop_playback(self, player_uuid):
        """
        Stop specified player playback and destroy player.
        Prefer pause_playback to keep player alive for fast resume.
        """
        self._check_parameters(
            [
                {
                    "name": "player_uuid",
                    "value": player_uuid,
                    "type": str,
                    "validator": lambda v: v in self.players,
                    "message": f'Player "{player_uuid}" does not exist',
                },
            ]
        )

        fade_out_ms = self._get_config_field("fade_out_ms")
        player = self.players[player_uuid]
        playbin = player["player"]

        def do_stop():
            if player_uuid not in self.players:
                return
            self.players[player_uuid]["player"].set_state(Gst.State.NULL)
            self._destroy_player(self.players[player_uuid])
            self.event_playback_update.send(
                {
                    "playeruuid": player_uuid,
                    "state": self._get_player_state(Gst.State.NULL),
                }
            )

        self.__cancel_fade(player_uuid)
        if fade_out_ms > 0 and playbin:
            current_volume = playbin.get_property("volume")
            self.__start_fade(
                player_uuid,
                current_volume,
                0.0,
                fade_out_ms,
                on_complete=do_stop,
            )
        else:
            do_stop()

    def play_next_track(self, player_uuid):
        """
        Play next track in specified player playlist
        """
        self._check_parameters(
            [
                {
                    "name": "player_uuid",
                    "value": player_uuid,
                    "type": str,
                    "validator": lambda v: v in self.players,
                    "message": f'Player "{player_uuid}" does not exist',
                },
            ]
        )

        playlist = self.players[player_uuid]["playlist"]
        if playlist["index"] + 1 >= len(playlist["tracks"]) and not playlist["repeat"]:
            self.logger.debug(
                'Player "%s" is already playing last playlist track', player_uuid
            )
            return False

        if not self.__play_next_track(player_uuid):
            raise CommandError("Error playing next track")
        return True

    def __play_next_track(self, player_uuid):
        """
        Play next resource if any
        """
        if player_uuid not in self.players:
            return False
        playlist = self.players[player_uuid]["playlist"]
        if playlist["index"] + 1 >= len(playlist["tracks"]):
            return self.__handle_end_of_playlist(player_uuid)

        playlist["index"] += 1
        playlist["duration"] = None
        next_track = playlist["tracks"][playlist["index"]]
        self.logger.debug(
            'Found next track to play on player "%s": %s', player_uuid, next_track
        )
        try:
            self.__play_track(next_track, player_uuid)
        except Exception:
            self.logger.exception("Error playing next track %s", next_track)
            return False

        return True

    def __handle_end_of_playlist(self, player_uuid):
        """
        Handle end of playlist according to player configuration
        """
        playlist = self.players[player_uuid]["playlist"]
        if playlist["repeat"]:
            if playlist["shuffle"]:
                self.shuffle_playlist(player_uuid)
            playlist["index"] = 0
            playlist["duration"] = None
            track = playlist["tracks"][0]
            self.__play_track(track, player_uuid)
            self.logger.debug('Player "%s" restarts playlist', player_uuid)
            return True

        self.logger.debug(
            'Player "%s" has no more tracks in playlist, destroy it', player_uuid
        )
        self._destroy_player(self.players[player_uuid])
        return False

    def play_previous_track(self, player_uuid):
        """
        Play previous track in specified player playlist
        """
        self._check_parameters(
            [
                {
                    "name": "player_uuid",
                    "value": player_uuid,
                    "type": str,
                    "validator": lambda v: v in self.players,
                    "message": f'Player "{player_uuid}" does not exist',
                },
            ]
        )

        playlist = self.players[player_uuid]["playlist"]
        self.logger.debug('Player "%s" playlist: %s', player_uuid, playlist)
        if playlist["index"] == 0:
            self.logger.debug(
                'Player "%s" has no previous track in playlist', player_uuid
            )
            return False

        playlist["index"] -= 1
        playlist["duration"] = None
        previous_track = playlist["tracks"][playlist["index"]]
        self.__play_track(previous_track, player_uuid)

        return True

    def play_track(self, player_uuid, track_index):
        """
        Play track at specified index
        """
        if player_uuid not in self.players:
            self.logger.warning("Cant play track: player %s does not exist", player_uuid)
            return False
        playlist = self.players[player_uuid]["playlist"]
        if (
            track_index is None
            or track_index < 0
            or track_index >= len(playlist["tracks"])
        ):
            self.logger.warning(
                "Cant play track: invalid track index %s specified", track_index
            )
            return False

        playlist["index"] = track_index
        playlist["duration"] = None
        next_track = playlist["tracks"][playlist["index"]]
        self.logger.debug(
            'Found next track to play on player "%s": %s', player_uuid, next_track
        )
        try:
            self.__play_track(next_track, player_uuid)
        except Exception:
            self.logger.exception(
                "Error playing track %s at index %s", next_track, track_index
            )
            return False

        return True

    def get_players(self):
        """
        Return list of players
        """
        return [
            self.__get_playback_info(player["uuid"]) for player in self.players.values()
        ]

    def get_playlist(self, player_uuid):
        """
        Return player playlist
        """
        self._check_parameters(
            [
                {
                    "name": "player_uuid",
                    "value": player_uuid,
                    "type": str,
                    "validator": lambda v: v in self.players,
                    "message": f'Player "{player_uuid}" does not exist',
                },
            ]
        )

        return self.players[player_uuid]["playlist"]

    def set_volume(self, player_uuid, volume):
        """
        Set player volume
        """
        self._check_parameters(
            [
                {
                    "name": "player_uuid",
                    "value": player_uuid,
                    "type": str,
                    "validator": lambda v: v in self.players,
                    "message": f'Player "{player_uuid}" does not exist',
                },
                {
                    "name": "volume",
                    "value": volume,
                    "type": int,
                    "none": True,
                    "validator": lambda v: 0 < v <= 100,
                    "message": "Volume must be between 1 and 100",
                },
            ]
        )

        self._set_volume(player_uuid, volume)

    def _set_volume(self, player_uuid, volume):
        """
        Set player volume on playbin
        """
        self.logger.debug("Set player %s volume to %s", player_uuid, volume)
        self.__cancel_fade(player_uuid)
        target = float(volume / 100.0)
        self.players[player_uuid]["internal"]["target_volume"] = target
        self.players[player_uuid]["playlist"]["volume"] = volume
        if self.players[player_uuid]["player"]:
            self.players[player_uuid]["player"].set_property("volume", target)

    def set_repeat(self, player_uuid, repeat, shuffle=False):
        """
        Repeat playlist when end of it is reached
        """
        self._check_parameters(
            [
                {
                    "name": "player_uuid",
                    "value": player_uuid,
                    "type": str,
                    "validator": lambda v: v in self.players,
                    "message": f'Player "{player_uuid}" does not exist',
                },
                {"name": "repeat", "value": repeat, "type": bool},
                {
                    "name": "shuffle",
                    "value": shuffle,
                    "type": bool,
                },
            ]
        )
        self.logger.debug(
            "set_repeat: player_uuid=%s, repeat=%s, shuffle=%s",
            player_uuid,
            repeat,
            shuffle,
        )

        self.players[player_uuid]["playlist"]["repeat"] = repeat
        self.players[player_uuid]["playlist"]["shuffle"] = shuffle

    def shuffle_playlist(self, player_uuid):
        """
        Shuffle playlist
        """
        if player_uuid not in self.players:
            raise CommandError(f'Player "{player_uuid}" does not exist')

        tracks = self.players[player_uuid]["playlist"]["tracks"]
        current_track = tracks.pop(self.players[player_uuid]["playlist"]["index"])
        random.shuffle(tracks)
        tracks.insert(0, current_track)
        self.players[player_uuid]["playlist"]["index"] = 0

    def _get_player_state(self, gst_state):
        """
        Return human readable player state
        """
        return self.PLAYER_STATES[gst_state]
