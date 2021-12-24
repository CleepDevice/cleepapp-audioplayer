#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import random
import gi
# pylint: disable=C0413
gi.require_version("Gst", "1.0")
from gi.repository import Gst
import magic
from urllib3.util import parse_url
from cleep.exception import MissingParameter, InvalidParameter, CommandError
from cleep.core import CleepModule
from cleep.common import CATEGORIES


class Audioplayer(CleepModule):
    """
    Audioplayer application
    """

    MODULE_AUTHOR = "Cleep"
    MODULE_VERSION = "1.0.0"
    MODULE_DEPS = []
    MODULE_DESCRIPTION = "Enjoy music playback"
    MODULE_LONGDESCRIPTION = (
        "This application provides an common way to play audio media on your device.<br>"
        "Application features: <ul>"
        "<li>Play most used audio formats (mp3, flac, ogg and aac)</li>"
        "<li>Play local file and remote streams</li>"
        "<li>Read audio metadata when available</li>"
        "<li>Implement minimalist player playlist</li>"
        "<li>Propagate significative player events</li>"
        "</ul>"
    )
    MODULE_TAGS = []
    MODULE_CATEGORY = CATEGORIES.MEDIA
    MODULE_URLINFO = "https://github.com/tangb/cleepapp-audioplayer"
    MODULE_URLHELP = None
    MODULE_URLSITE = None
    MODULE_URLBUGS = "https://github.com/tangb/cleepapp-audioplayer/issues"

    MODULE_CONFIG_FILE = "audioplayer.conf"
    DEFAULT_CONFIG = {}

    # Audio pipelines description according to audio type (mime)
    # Order matters: elements will be loaded as they are stored
    AUDIO_PIPELINE_ELEMENTS = {
        # MP3
        "audio/mpeg": {
            "tags": "id3demux",
            "parser": "mpegaudioparse",
            "decoder": "mpg123audiodec",
            "converter": "audioconvert",
            "gain": "rgvolume",
            "converter2": "audioconvert",
            "resampler": "audioresample",
        },
        # FLAC
        "audio/flac": {
            "parser": "flacparse",
            "decoder": "flacdec",
            "converter": "audioconvert",
            "gain": "rgvolume",
            "converter2": "audioconvert",
            "resampler": "audioresample",
        },
        # OGG
        "audio/ogg": {
            "demux": "oggdemux",
            "tags": "oggparse",
            "decoder": "vorbisdec",
            "converter": "audioconvert",
            "gain": "rgvolume",
            "converter2": "audioconvert",
            "resampler": "audioresample",
        },
        # AAC
        "audio/x-hx-aac-adts": {
            "parser": "aacparse",
            "decoder": "faad",
            "converter": "audioconvert",
            "gain": "rgvolume",
            "converter2": "audioconvert",
            "resampler": "audioresample",
        },
        "audio/x-hx-aac-adif": {
            "parser": "aacparse",
            "decoder": "faad",
            "converter": "audioconvert",
            "gain": "rgvolume",
            "converter2": "audioconvert",
            "resampler": "audioresample",
        },
        "audio/aac": {
            "parser": "aacparse",
            "decoder": "faad",
            "converter": "audioconvert",
            "gain": "rgvolume",
            "converter2": "audioconvert",
            "resampler": "audioresample",
        },
    }
    MAX_PLAYLIST_TRACKS = 20

    def __init__(self, bootstrap, debug_enabled):
        """
        Constructor

        Args:
            bootstrap (dict): bootstrap objects
            debug_enabled: debug status
        """
        CleepModule.__init__(self, bootstrap, debug_enabled)

        # list of players ::
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
        Use this function to configure your variables and local stuff that is not blocking.
        At this time other applications are not started and all your command requests will fail.
        """
        Gst.init(None)

    def _on_stop(self):
        """
        Stop module
        """
        # destroy all players
        players_to_delete = [
            player_uuid for player_uuid, player in self.players.items()
        ]
        for player_uuid in players_to_delete:
            self.__destroy_player(self.players[player_uuid])

    def __prepare_player(self, player_uuid, source, audio_format):
        """
        Prepare player for playback

        It returns existing pipeline if possible or create new one

        Args:
            player_uuid (string): existing player id
            source (Gst.ElementFactory): gstreamer source element
            audio_format (string): audio format (mime)

        Returns:
            player (dict): player as returned by __create_player
        """
        if player_uuid not in self.players:
            raise Exception(f'Player "{player_uuid}" does not exist')

        player = self.players[player_uuid]
        self.__reset_player(player)
        self.__build_pipeline(source, audio_format, player)

        return player

    def __create_player(self):
        """
        Create player structure

        Returns:
            dict: player structure::

            {
                uuid (string): player uuid
                state (string): player state (see PLAYER_STATE_XXX)
                player (Gst.Pipeline): direct access to pipeline (aka player) (default None)
                playlist (dict): {
                    current_index (number): current track (default None)
                    tracks (list): list of tracks (default [])
                }
                source (Gst.ElementFactory): direct access to source element (default None)
                volume (Gst.ElementFactory): direct access to volume element (default None)
                pipeline (dict): all pipeline elements (default [])
            }

        """
        return {
            "uuid": self._get_unique_id(),
            "playlist": {
                "index": None,
                "duration": None,
                "tracks": [],
                "repeat": False,
                "volume": 0,
                "metadata": None,
            },
            "player": None,
            "source": None,
            "volume": None,
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": False,
                "last_state": Gst.State.NULL,
            },
        }

    # pylint: disable=R0201
    def __reset_player(self, player):
        """
        Reset existing player deleting gstreamer pipeline elements and resetting some internals flags

        Args:
            player (dict): structure as returned by __create_player
        """
        # make sure player is stopped
        if player["player"]:
            player["player"].set_state(Gst.State.NULL)

        # unlink pipeline elements
        previous = None
        for _, current in reversed(list(enumerate(player["pipeline"]))):
            if not previous:
                # last element linked to nothing, drop it
                previous = current
                continue

            current.unlink(previous)
            previous = current

        # remove elements from pipeline
        pipeline = player["player"]
        for element in player["pipeline"]:
            pipeline.remove(element)

        # finally destroy pipeline and reset player
        del pipeline
        player["pipeline"].clear()
        player["player"] = None
        player["source"] = None
        player["volume"] = None
        player["playlist"]["metadata"] = None
        player["internal"]["tags_sent"] = False
        player["internal"]["last_state"] = Gst.State.NULL

    # pylint: disable=R0201
    def _destroy_player(self, player):
        """
        Set player destroy flag to True to perform safe player deletion during
        process loop
        """
        player["internal"]["to_destroy"] = True

    # pylint: disable=R0201
    def __destroy_player(self, player):
        """
        Destroy player. This method should be exclusively used during app cycle life.
        """
        self.__reset_player(player)
        del self.players[player["uuid"]]

    def __build_pipeline(self, source, audio_format, player):
        """
        Build player gstreamer pipeline

        Args:
            source (Gst.ElementFactory): gstreamer source element
            audio_format (string): audio format (mime type)
            player (dict): player structure as returned by __create_player
        """
        # create default mandatory elements
        pipeline = Gst.Pipeline.new(player["uuid"])
        progress = Gst.ElementFactory.make("progressreport", "progress")
        progress.set_property("update-freq", 15)
        progress.set_property("silent", True)
        volume = Gst.ElementFactory.make("volume", "volume")
        sink = Gst.ElementFactory.make("autoaudiosink", "sink")

        # prepare player pipeline elements
        self.logger.debug("Prepare player %s pipeline", player["uuid"])
        elements = self.AUDIO_PIPELINE_ELEMENTS[audio_format]
        player["pipeline"].append(source)
        player["pipeline"].append(progress)
        for (key, value) in elements.items():
            element = Gst.ElementFactory.make(value, key)
            if not element:
                self.logger.error(
                    'No gstreamer element created for "%s:%s"', key, value
                )
                raise Exception("Error configuring audio player")
            player["pipeline"].append(element)
        player["pipeline"].append(volume)
        player["pipeline"].append(sink)

        # build player pipeline
        self.logger.trace(f'build player {player["uuid"]} pipeline')
        previous_element = player["pipeline"][0]
        pipeline.add(previous_element)
        for current_element in player["pipeline"][1:]:
            pipeline.add(current_element)
            self.logger.trace(" - Link %s to %s", previous_element, current_element)
            previous_element.link(current_element)
            previous_element = current_element

        # set player shortcuts
        player["source"] = source
        player["volume"] = volume
        player["player"] = pipeline

    def _on_process(self):
        """
        On process
        """
        self.__process_players_messages()

        # destroy players
        players_to_delete = [
            player_uuid
            for player_uuid, player in self.players.items()
            if player["internal"]["to_destroy"]
        ]
        if len(players_to_delete) > 0:
            self.logger.debug("Players to delete: %s", players_to_delete)
            for player_uuid in players_to_delete:
                self.__destroy_player(self.players[player_uuid])

    def __process_players_messages(self):
        """
        Process all players messages
        """
        for player_uuid, player in self.players.items():
            try:
                message = player["player"].get_bus().pop()
                while message:
                    self.__process_gstreamer_message(
                        player_uuid, player["player"], message
                    )
                    del message
                    message = player["player"].get_bus().pop()
            except Exception:
                self.logger.exception(
                    'Error processing player "%s" messages', player_uuid
                )

    def __process_gstreamer_message(self, player_uuid, player, message):
        """
        Process gstreamer message

        Args:
            player_uuid (string): player identifier
            player (Gst.Pipeline): player
            message (Gst.Message): message to proces
        """
        message_type = message.type
        self.logger.trace('Player "%s" received message: %s', player_uuid, message_type)
        if message_type == Gst.MessageType.EOS:
            self.logger.debug('Player "%s" EOS: end of stream', player_uuid)
            player.set_state(Gst.State.NULL)
            self.__play_next_track(player_uuid)
            self.__send_playback_event(player_uuid, player)
        elif message_type == Gst.MessageType.STATE_CHANGED:
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
            player (Gst.Pipeline): player
            force (bool): bypass excessive sending control
        """
        # state
        _, current_state, _ = player.get_state(1)
        if not force and current_state in (
            self.players[player_uuid]["internal"]["last_state"],
            Gst.State.READY,
        ):
            return
        player_data = self.players[player_uuid]
        player_data["internal"]["last_state"] = current_state

        # duration
        duration_true, duration = player.query_duration(Gst.Format.TIME)
        duration = int(duration / 1000000000) if duration_true else None
        if duration:
            player_data["playlist"]["duration"] = duration

        playback_info = self.__get_playback_info(player_uuid)
        self.event_playback_update.send(playback_info)

    def __get_playback_info(self, player_uuid):
        """
        Return current player playback info: playing track, track duration, player state...

        Args:
            player_uuid (string): player identifier

        Returns:
            dict: current player info::

            {
                playeruuid (string): player identifier
                track (dict): current track
                metadata (dict): current track metadata
                state (Gst.State): player state
                duration (number): track duration (in seconds)
            }

        """
        if player_uuid not in self.players:
            return {
                "index": 0,
                "playeruuid": player_uuid,
                "track": None,
                "metadata": {},
                "state": Gst.State.NULL,
                "duration": 0,
            }

        player = self.players[player_uuid]
        return {
            "index": player["playlist"]["index"],
            "playeruuid": player_uuid,
            "track": player["playlist"]["tracks"][player["playlist"]["index"]],
            "metadata": player["playlist"]["metadata"],
            "state": player["internal"]["last_state"],
            "duration": player["playlist"]["duration"],
        }

    def __get_audio_metadata(self, tags):
        """
        Get audio tags from message

        Args:
            tags (Gst.TagList): tag list

        Returns:
            tuple: audio metadata::

            (
                boolean: metadata is complete
                dict: list of tags in usable format
            )

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
            self.logger.debug(" => tag name: %s", tag_name)
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
        Return file audio format

        Args:
            filepath (string): full file path

        Returns:
            string: if audio format is supported (mime type)
            None: if audio format is not supported
        """
        try:
            mime = magic.from_file(filepath, mime=True)
            return mime if mime in list(self.AUDIO_PIPELINE_ELEMENTS.keys()) else None
        except Exception:
            self.logger.exception("Error getting file format")
            return None

    @staticmethod
    def _is_filepath(resource):
        """
        Return True if resource is a filepath

        Returns:
            bool: True if url, False otherwise
        """
        if os.path.exists(resource):
            # it's a local file
            return True

        # make sure resource is a valid url
        parse_result = parse_url(resource)
        if parse_result.scheme in ("http", "https"):
            return False

        raise Exception("Resource is invalid (file may not exist)")

    @staticmethod
    def _make_track(resource, audio_format):
        """
        Create track dict

        Returns:
            dict: track object::

            {
                resource (string): audio resource (file or url)
                audio_format (string): resource format (mime)
            }

        """
        return {
            "resource": resource,
            "audio_format": audio_format,
        }

    def add_track(self, player_uuid, resource, audio_format=None, track_index=None):
        """
        Add track in specified player playlist.

        Note:
            A player with no audio resource in playlist is destroyed so take care to call this command before current audio
            resource playing is terminated.

        Args:
            player_uuid (string): player identifier returned by play command
            resource (string): local filepath or url
            audio_format (string): audio format (mime). Mandatory if resource is an url
            track_index (number): add new track to specified playlist position or at end of playlist

        Returns:
            bool: True if track added successfully, False if max playlist tracks reached

        Raises:
            CommandError: if player does not exist
            MissingParameter: if parameters are missing
        """
        if player_uuid not in self.players:
            raise CommandError(f'Player "{player_uuid}" does not exist')
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
        track_index = track_index or len(
            self.players[player_uuid]["playlist"]["tracks"]
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

        Args:
            tracks (list): list of tracks::

                [
                    {
                        resource (string): local filepath or url
                        audio_format (string): audio format (mime). Mandatory if resource is an url, can be None if local file.
                    },
                    ...
                ]

        Raises:
            CommandError: if player does not exist
            MissingParameter: if parameters are missing
            InvalidParameter: if command parameters are invalid
        """
        self._check_parameters([
            {'name': tracks, 'value': tracks, 'type': dict}
        ])

        for track in tracks:
            if not self.add_track(player_uuid, track['resource'], track['audio_format']):
                break

    def remove_track(self, player_uuid, track_index):
        """
        Remove track from player playlist

        Args:
            player_uuid (string): player identifier
            track_index (number): track index (0 is the first playlist track)
        """
        if player_uuid not in self.players:
            raise CommandError(f'Player "{player_uuid}" does not exist')
        if track_index < 0 or track_index >= len(
            self.players[player_uuid]["playlist"]["tracks"]
        ):
            raise CommandError("Track index is invalid")
        if track_index == self.players[player_uuid]["playlist"]["index"]:
            raise CommandError("You can't remove current track")

        removed_track = self.players[player_uuid]["playlist"]["tracks"].pop(track_index)
        self.logger.debug(
            'Player "%s" has track removed: %s', player_uuid, removed_track
        )

    def start_playback(self, resource, audio_format=None, volume=100):
        """
        Create a player and start playing specified resource

        Args:
            resource (string): local filepath or url
            audio_format (string): audio format (mime). Mandatory if resource is an url
            volume (int): player volume (default 100)

        Returns:
            string: player identifier
        """
        player = self.__create_player()
        track = Audioplayer._make_track(resource, audio_format)
        player["playlist"]["index"] = 0
        player["playlist"]["volume"] = volume
        player["playlist"]["tracks"].append(track)
        self.players[player["uuid"]] = player

        try:
            self.__play_track(track, player["uuid"], volume)
            return player["uuid"]
        except Exception as error:
            self.__destroy_player(player)
            raise CommandError("Unable to play resource") from error

    def __play_track(self, track, player_uuid, volume=None):
        """
        Play audio stream to

        Args:
            player_uuid (string): player identifier
            volume (int): player volume
        """
        # prepare player
        if Audioplayer._is_filepath(track["resource"]):
            audio_format = self.__get_file_audio_format(track["resource"])
            if not audio_format:
                raise CommandError("Audio file not supported")
            track["audio_format"] = audio_format
            source = Gst.ElementFactory.make("filesrc", "source")
        else:
            source = Gst.ElementFactory.make("souphttpsrc", "source")
        player = self.__prepare_player(player_uuid, source, track["audio_format"])

        try:
            # configure player
            player["source"].set_property("location", track["resource"])
            volume = volume or self.players[player_uuid]["playlist"]["volume"]
            if volume is not None:
                player["volume"].set_property("volume", float(volume / 100.0))

            # start playback
            player["player"].set_state(Gst.State.PLAYING)
            self.logger.info('Player "%s" is playing %s', player_uuid, track)
        except Exception as error:
            self.logger.exception("Error playing track %s with %s", track, player_uuid)
            raise error

    def _get_track_index(self, player_uuid, track):
        """
        Search track index in player playlist

        Args:
            player_uuid (string): player identifier
            track (dict): track data

        Returns:
            number: track playlist index
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

    def pause_playback(self, player_uuid):
        """
        Toggle pause status for specified player.

        Args:
            player_uuid (string): player identifier

        Returns:
            bool: True if player playback is paused, False if player playback is unpaused

        Raises:
            CommandError: if player does not exist
        """
        if player_uuid not in self.players:
            raise CommandError(f'Player "{player_uuid}" does not exist')

        player = self.players[player_uuid]
        _, current_state, _ = player["player"].get_state(1)
        self.logger.debug("Change player %s state to %s", player_uuid, current_state)
        new_state = (
            Gst.State.PAUSED
            if current_state == Gst.State.PLAYING
            else Gst.State.PLAYING
        )
        player["player"].set_state(new_state)

    def stop_playback(self, player_uuid):
        """
        Stop specified player playback and destroy player.
        The player will not be available anymore after the stop command, the playlist is also deleted.
        You need to call play command to create new player.
        If you want to keep player alive, prefer using pause command.

        Args:
            player_uuid (string): player identifier

        Raises:
            CommandError: if player does not exist
        """
        if player_uuid not in self.players:
            raise CommandError(f'Player "{player_uuid}" does not exist')

        self.players[player_uuid]["player"].set_state(Gst.State.NULL)
        self._destroy_player(self.players[player_uuid])

        self.event_playback_update.send(
            {
                "playeruuid": player_uuid,
                "state": Gst.State.NULL,
            }
        )

    def play_next_track(self, player_uuid):
        """
        Play next track in specified player playlist

        If there is no next track in playlist, current player playback is stopped and player is destroyed.
        You will need to call play command again to create new player.

        Args:
            player_uuid (string): player identifier

        Returns:
            bool: True if next track playback succeed, False otherwise

        Raises:
            CommandError: if player does not exist
        """
        if player_uuid not in self.players:
            raise CommandError(f'Player "{player_uuid}" does not exist')

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

        Args:
            player_uuid (string): player uuid

        Returns:
            bool: True if next track playback succeed, False otherwise
        """
        if player_uuid not in self.players:
            return False
        playlist = self.players[player_uuid]["playlist"]
        if playlist["index"] + 1 >= len(playlist["tracks"]):
            return self.__handle_end_of_playlist(player_uuid)

        # update playlist
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

        Args:
            player_uuid (string): player identifier

        Returns:
            boolean: True if playback continues, False otherwise
        """
        playlist = self.players[player_uuid]["playlist"]
        if playlist["repeat"]:
            # restart playlist
            playlist["index"] = 0
            playlist["duration"] = None
            track = playlist["tracks"][0]
            self.__play_track(track, player_uuid)
            self.logger.debug('Player "%s" restarts playlist', player_uuid)
            return True

        # no more track to play, destroy player
        self.logger.debug(
            'Player "%s" has no more tracks in playlist, destroy it', player_uuid
        )
        self._destroy_player(self.players[player_uuid])
        return False

    def play_previous_track(self, player_uuid):
        """
        Play previous track in specified player playlist
        If there is no previous track, current playback is restarted

        Args:
            player_uuid (string): player identifier

        Returns:
            bool: True if previous track played successfully, False otherwise

        Raises:
            CommandError: if command failed
        """
        if player_uuid not in self.players:
            raise CommandError(f'Player "{player_uuid}" does not exist')
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

    def get_players(self):
        """
        Return list of players

        Returns:
            list: list of players with current playback info::

            {
                playeruuid (string): player identifier
                playback (dict): current track
                    {
                        resource (string): file/url
                        audio_format (string): file format
                    }
                state (Gst.State): player state
                volume (int): player volume
        """
        return [
            self.__get_playback_info(player["uuid"]) for player in self.players.values()
        ]

    def get_playlist(self, player_uuid):
        """
        Return player playlist

        Args:
            player_uuid (string): player identifier

        Returns:
            dict: current playlist::

            {
                tracks (list): list of tracks
                current_index (number): current track index (0 is the first playlist track)
            }

        """
        if player_uuid not in self.players:
            raise CommandError(f'Player "{player_uuid}" does not exist')

        return self.players[player_uuid]["playlist"]

    def set_volume(self, player_uuid, volume):
        """
        Set player volume

        Args:
            player_uuid (string): player identifier
            volume (number): percentage volume

        Raises:
            CommandError: if player does not exist
            InvalidParameter: if volume is invalid
        """
        if player_uuid not in self.players:
            raise CommandError(f'Player "{player_uuid}" does not exist')
        if volume < 0 or volume > 100:
            raise InvalidParameter('Parameter "volume" is invalid')

        self.players[player_uuid]["volume"].set_property(
            "volume", float(volume / 100.0)
        )
        self.players[player_uuid]["playlist"]["volume"] = volume

    def set_repeat(self, player_uuid, repeat):
        """
        Repeat playlist when end of it is reached

        Args:
            player_uuid (string): player identifier
            repeat (boolean): True to repeat playlist, False otherwise

        Raises:
            CommandError: if player does not exist
        """
        if player_uuid not in self.players:
            raise CommandError(f'Player "{player_uuid}" does not exist')

        self.players[player_uuid]["playlist"]["repeat"] = repeat

    def shuffle_playlist(self, player_uuid):
        """
        Shuffle playlist

        Args:
            player_uuid (string): player identifier
        """
        if player_uuid not in self.players:
            raise CommandError(f'Player "{player_uuid}" does not exist')

        tracks = self.players[player_uuid]["playlist"]["tracks"]
        current_track = tracks.pop(self.players[player_uuid]["playlist"]["index"])
        random.shuffle(tracks)
        tracks.insert(0, current_track)
        self.players[player_uuid]["playlist"]["index"] = 0
