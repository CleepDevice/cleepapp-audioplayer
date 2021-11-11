#!/usr/bin/env python
# -*- coding: utf-8 -*-

import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib
import magic
import os
from urllib3.util import parse_url
from cleep.exception import MissingParameter, InvalidParameter, CommandError
from cleep.core import CleepModule


class Audioplayer(CleepModule):
    """
    Audioplayer application
    """

    MODULE_AUTHOR = "Cleep"
    MODULE_VERSION = "0.0.0"
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
    MODULE_CATEGORY = "TODO"
    MODULE_URLINFO = "https://www.google.com"
    MODULE_URLHELP = None
    MODULE_URLSITE = None
    MODULE_URLBUGS = None

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
            "converter": "audioconvert",
            "resampler": "audioresample",
        },
        # FLAC
        "audio/flac": {
            "parser": "flacparse",
            "decoder": "flacdec",
            "converter": "audioconvert",
            "gain": "rgvolume",
            "converter": "audioconvert",
            "resampler": "audioresample",
        },
        # OGG
        "audio/ogg": {
            "demux": "oggdemux",
            "tags": "oggparse",
            "decoder": "vorbisdec",
            "convert": "audioconvert",
            "gain": "rgvolume",
            "convert": "audioconvert",
            "resampler": "audioresample",
        },
        # AAC
        "audio/x-hx-aac-adts": {
            "parser": "aacparse",
            "decoder": "faad",
            "converter": "audioconvert",
            "gain": "rgvolume",
            "converter": "audioconvert",
            "resampler": "audioresample",
        },
        "audio/x-hx-aac-adif": {
            "parser": "aacparse",
            "decoder": "faad",
            "converter": "audioconvert",
            "gain": "rgvolume",
            "converter": "audioconvert",
            "resampler": "audioresample",
        },
        "audio/aac": {
            "parser": "aacparse",
            "decoder": "faad",
            "converter": "audioconvert",
            "gain": "rgvolume",
            "converter": "audioconvert",
            "resampler": "audioresample",
        },
    }
    PLAYER_STATE_STOPPED = "stopped"
    PLAYER_STATE_PAUSED = "paused"
    PLAYER_STATE_PLAYING = "playing"

    def __init__(self, bootstrap, debug_enabled):
        """
        Constructor

        Args:
            bootstrap (dict): bootstrap objects
            debug_enabled: debug status
        """
        CleepModule.__init__(self, bootstrap, True)

        # list of players ::
        #   {
        #       player_uuid (string): {
        #           see list of fields in _get_player
        #       },
        #       ...
        #   }
        self.players = {}
        self.event_metadata_update = self._get_event("audioplayer.metadata.update")
        self.event_playback_update = self._get_event("audioplayer.playback.update")
        # self.event_duration_update = self._get_event('audioplayer.duration.update')

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

    def _get_player(self, source, audio_format, player_uuid=None):
        """
        Get pipeline for playback

        It returns existing pipeline if possible or create new one

        Args:
            source (Gst.ElementFactory): gstreamer source element
            audio_format (string): audio format (mime)
            player_uuid (string): existing player id

        Returns:
            dict: player struct as returned bu _create_player
            None: if problem occured
        """
        if player_uuid and player_uuid not in self.players:
            # no player found while it should (uuid specified)
            return None

        # get existing player if possible
        player = None
        if player_uuid:
            player = self.players[player_uuid]

        # create new player or reset existing one
        if not player:
            self.logger.debug("Create new player")
            player = self.__create_player()
            self.players[player["uuid"]] = player
        else:
            self.logger.debug("Reset existing player")
            self.__reset_player(player)

        # build player pipeline
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
                    previous_tracks (list): list of previous tracks (default [])
                    current_track (dict): current track (default None)
                    next_tracks (list): list of next tracks (default [])
                }
                source (Gst.ElementFactory): direct access to source element (default None)
                volume (Gst.ElementFactory): direct access to volume element (default None)
                pipeline (dict): all pipeline elements (default [])
            }

        """
        return {
            "uuid": self._get_unique_id(),
            "playlist": {
                "previous_tracks": [],
                "current_track": None,
                "next_tracks": [],
            },
            "player": None,
            "source": None,
            "volume": None,
            "pipeline": [],
            "internal": {
                "todestroy": False,
                "tags_sent": False,
                "last_state": Gst.State.NULL,
            },
        }

    def __reset_player(self, player):
        """
        Reset existing player stuff

        Args:
            player (dict): structure as returned by __create_player
        """
        # make sure player is stopped
        player["player"].set_state(Gst.State.NULL)

        # unlink pipeline elements
        previous = None
        for index, current in reversed(list(enumerate(player["pipeline"]))):
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
        player["internal"]["tags_sent"] = False
        player["internal"]["last_state"] = Gst.State.NULL

    def _destroy_player(self, player):
        """
        Set player destroy flag to True to perform safe player deletion during
        process loop
        """
        player["internal"]["todestroy"] = True

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
        self.logger.debug("Prepare player %s pipeline" % player["uuid"])
        elements = self.AUDIO_PIPELINE_ELEMENTS[audio_format]
        player["pipeline"].append(source)
        player["pipeline"].append(progress)
        for (key, value) in elements.items():
            element = Gst.ElementFactory.make(value, key)
            if not element:
                self.logger.error(
                    'No gstreamer element created for "%s:%s"' % (key, value)
                )
                raise Exception("Error configuring music player")
            player["pipeline"].append(element)
        player["pipeline"].append(volume)
        player["pipeline"].append(sink)

        # build player pipeline
        self.logger.debug("build player %s pipeline" % player["uuid"])
        previous_element = player["pipeline"][0]
        pipeline.add(previous_element)
        for current_element in player["pipeline"][1:]:
            pipeline.add(current_element)
            self.logger.debug(" - Link %s to %s" % (previous_element, current_element))
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
            if player["internal"]["todestroy"]
        ]
        if len(players_to_delete) > 0:
            self.logger.debug("Players to delete: %s" % players_to_delete)
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
            except Exception as error:
                self.logger.exception("Error processing player messages:")

    def __process_gstreamer_message(self, player_uuid, player, message):
        """
        Process gstreamer message

        Args:
            player_uuid (string): player identifier
            player (Gst.Pipeline): player
            message (Gst.Message): message to proces
        """
        message_type = message.type
        self.logger.trace(
            "Player %s received message: %s" % (player_uuid, message_type)
        )
        if message_type == Gst.MessageType.EOS:
            self.logger.debug("Player %s EOS: end of stream" % player_uuid)
            player.set_state(Gst.State.NULL)
            self.__play_next_track(player_uuid)
            self.__send_playback_event(player_uuid, player)
        elif message_type == Gst.MessageType.STATE_CHANGED:
            (
                old_state,
                new_state,
                pending,
            ) = parsed_message = message.parse_state_changed()
            self.logger.trace(
                "Player %s STATE_CHANGED: oldstate=%s newstate=%s pending=%s"
                % (player_uuid, old_state, new_state, pending)
            )
            self.__send_playback_event(player_uuid, player)
        elif message_type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            self.logger.error("Player %s ERROR: %s | %s" % (player_uuid, error, debug))
            player.set_state(Gst.State.NULL)
            self.__send_playback_event(player_uuid, player)
        elif (
            message_type == Gst.MessageType.TAG
            and not self.players[player_uuid]["internal"]["tags_sent"]
        ):
            tags = message.parse_tag()
            metadata = self.__get_audio_metadata(tags)
            self.logger.debug("Player %s TAG: %s" % (player_uuid, metadata))
            metadata.update({"playeruuid": player_uuid})
            self.event_metadata_update.send(metadata)
            self.players[player_uuid]["internal"]["tags_sent"] = True
        elif message_type == Gst.MessageType.DURATION_CHANGED:
            durationtrue, duration = player.query_duration(Gst.Format.TIME)
            if durationtrue:
                duration = int(duration / 1000000000)
                self.logger.debug(
                    "Player %s DURATION_CHANGED: %s seconds" % (player_uuid, duration)
                )
                # TODO send another event
                # self.__send_playback_event(player_uuid, player, duration)

    def __send_playback_event(self, player_uuid, player):
        """
        Send current playback state using event

        Args:
            player_uuid (string): player identifier
            player (Gst.Pipeline): player
        """
        _, current_state, _ = player.get_state(1)
        if (
            self.players[player_uuid]["internal"]["last_state"] == current_state
            or current_state == Gst.State.READY
        ):
            return

        self.players[player_uuid]["internal"]["last_state"] = current_state
        self.event_playback_update.send(
            {
                "playeruuid": player_uuid,
                "state": current_state,
            }
        )

    def __get_audio_metadata(self, tags):
        """
        Get audio tags from message

        Args:
            tags (Gst.TagList): tag list

        Returns:
            dict: list of tags in usable format
        """
        metadata = {
            "album": None,
            "artist": None,
            "year": None,
            "genre": None,
            "track": None,
            "title": None,
            "channel": None,
            "bitratemin": None,
            "bitratemax": None,
            "bitrateavg": None,
        }

        for index in range(tags.n_tags()):
            tag_name = tags.nth_tag_name(index)
            self.logger.trace(" => tag name: %s" % tag_name)
            # self.logger.debug('All tags: %s' % tags.to_string())
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
                metadata["channel"] = tags.get_string(tag_name)[1]
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

        return metadata

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
        except:
            self.logger.exception("Error getting file format")
            return None

    def __is_filepath(self, resource):
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

    def __make_track(self, resource, audio_format):
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

    def add_track(self, player_uuid, resource, audio_format=None, track_index=0):
        """
        Add track in specified player playlist.

        Note:
            A player with no audio resource in playlist is destroyed so take care to call this command before current audio
            resource playing is terminated.

        Args:
            player_uuid (string): player identifier returned by play command
            resource (string): local filepath or url
            audio_format (string): audio format (mime). Mandatory if resource is an url
            track_index (number): add new track to specified playlist position
        """
        if player_uuid not in self.players:
            raise CommandError('Player "%s" does not exists' % player_uuid)
        if self.__is_filepath(resource) and not audio_format:
            raise MissingParameter("Url resource must have audio_format specified")

        self.logger.info(
            'Audio resource "%s" added to player "%s" playlist at position %s'
            % (resource, player_uuid, track_index)
        )
        track = self.__make_track(resource, audio_format)
        self.players[player_uuid]["playlist"]["next_tracks"].append(track)
        self.logger.debug(
            "Player %s playlist: %s"
            % (player_uuid, self.players[player_uuid]["playlist"])
        )

    def remove_track(self, player_uuid, track_index):
        """
        Remove track from player playlist

        Args:
            player_uuid (string): player identifier
            track_index (number): track index (0 is the first playlist track)
        """
        if player_uuid not in self.players:
            raise CommandError('Player "%s" does not exists' % player_uuid)
        playlist = self.get_playlist(player_uuid)
        if track_index < 0 or track_index >= len(playlist["tracks"]):
            raise CommandError("Track index is invalid")
        if track_index == playlist["current"]:
            raise CommandError("You can't remove current track")

        if track_index < playlist["current"]:
            self.players[player_uuid]["playlist"]["previous_tracks"].pop(track_index)
        else:
            previous_len = len(self.players[player_uuid]["playlist"]["previous_tracks"])
            removed_track = self.players[player_uuid]["playlist"]["next_tracks"].pop(
                track_index - previous_len - 1
            )
            self.logger.debug(
                "Player %s has track removed: %s" % (player_uuid, removed_track)
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
        if self.__is_filepath(resource):
            player_uuid = self.__play_file(resource, volume)
        else:
            player_uuid = self.__play_url(resource, audio_format, volume)
        self.logger.info('Player "%s" is playing "%s"' % (player_uuid, resource))

        return player_uuid

    def __play_file(self, filepath, volume=None, player_uuid=None):
        """
        Play audio stream to

        Args:
            filepath (string): full file path to play
            volume (int): player volume
            player_uuid (string): player identifier

        Returns:
            string: player uuid
        """
        self.logger.debug('Play file "%s" on player "%s"' % (filepath, player_uuid))
        audio_format = self.__get_file_audio_format(filepath)
        if not audio_format:
            raise CommandError("Audio file not supported")

        # get player
        source = Gst.ElementFactory.make("filesrc", "source")
        player = self._get_player(source, audio_format, player_uuid)
        self.logger.debug("Player: %s" % player)
        if not player:
            raise CommandError("Player %s does not exist" % player_uuid)

        # configure player
        player["source"].set_property("location", filepath)
        if volume is not None:
            player["volume"].set_property("volume", float(volume / 100.0))
        track = self.__make_track(filepath, audio_format)
        player["playlist"]["current_track"] = track
        self.logger.debug("Player %s playlist: %s" % (player_uuid, player["playlist"]))

        player["player"].set_state(Gst.State.PLAYING)

        return player["uuid"]

    def __play_url(self, url, audio_format, volume=None, player_uuid=None):
        """
        Play specified stream from url

        Args:
            url (string): url
            audio_format (string): audio format (mime type)
            player_uuid (string): player identifier

        Returns:
            string: player uuid
        """
        self.logger.debug('Play url "%s" on player "%s"' % (url, player_uuid))
        if audio_format not in list(self.AUDIO_PIPELINE_ELEMENTS.keys()):
            raise CommandError("Audio file not supported")

        # get player
        source = Gst.ElementFactory.make("souphttpsrc", "source")
        player = self._get_player(source, audio_format, player_uuid)
        self.logger.debug("Player: %s" % player)
        if not player:
            raise CommandError("Player %s does not exist" % player_uuid)

        # configure player
        player["source"].set_property("location", url)
        if volume is not None:
            player["volume"].set_property("volume", float(volume / 100.0))
        track = self.__make_track(url, audio_format)
        player["playlist"]["current_track"] = track
        self.logger.debug(
            "Player %s playlist: %s"
            % (player["uuid"], self.players[player["uuid"]]["playlist"])
        )

        player["player"].set_state(Gst.State.PLAYING)

        return player["uuid"]

    def pause_playback(self, player_uuid):
        """
        Toggle pause status for specified player.

        Args:
            player_uuid (string): player identifier

        Returns:
            bool: True if player playback is paused, False if player playback is unpaused

        Raises:
            CommandError: if player does not exists
        """
        if player_uuid not in self.players:
            raise CommandError('Player "%s" does not exists' % player_uuid)

        player = self.players[player_uuid]
        _, current_state, _ = player["player"].get_state(1)
        self.logger.debug("Change player %s state to %s" % (player_uuid, current_state))
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
            CommandError: if player does not exists
        """
        if player_uuid not in self.players:
            raise CommandError('Player "%s" does not exists' % player_uuid)

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
            CommandError: if player does not exists
        """
        if player_uuid not in self.players:
            raise CommandError('Player "%s" does not exists' % player_uuid)
        next_tracks = self.players[player_uuid]["playlist"]["next_tracks"]
        if len(next_tracks) == 0:
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

        next_tracks = self.players[player_uuid]["playlist"]["next_tracks"]
        if len(next_tracks) == 0:
            # no more track to play destroy player
            self.logger.debug(
                "Player %s has no more tracks in playlist, destroy it" % player_uuid
            )
            self._destroy_player(self.players[player_uuid])
            return False

        current_track = self.players[player_uuid]["playlist"]["current_track"]
        next_track = next_tracks.pop(0)
        self.logger.debug(
            'Found next track to play on player "%s": %s' % (player_uuid, next_track)
        )
        try:
            self.players[player_uuid]["playlist"]["previous_tracks"].append(
                current_track
            )
            self.players[player_uuid]["playlist"]["current_track"] = next_track
            if self.__is_filepath(next_track["resource"]):
                self.__play_file(next_track["resource"], player_uuid=player_uuid)
            else:
                self.__play_url(
                    next_track["resource"],
                    next_track["audio_format"],
                    player_uuid=player_uuid,
                )
            self.logger.info(
                'Player "%s" is playing "%s"' % (player_uuid, next_track["resource"])
            )
        except:
            self.logger.exception(
                "Error playing next track with player %s: %s"
                % (player_uuid, next_track)
            )
            return False

        return True

    def play_previous_track(self, player_uuid):
        """
        Play previous track in specified player playlist
        If there is no previous track, current playback is restarted

        Args:
            player_uuid (string): player identifier

        Raises:
            CommandError: if command failed
        """
        if player_uuid not in self.players:
            raise CommandError('Player "%s" does not exists' % player_uuid)

        previous_tracks = self.players[player_uuid]["playlist"]["previous_tracks"]
        if len(previous_tracks) == 0:
            self.logger.debug(
                "Player %s has no previous track in playlist" % player_uuid
            )
            return False

        current_track = self.players[player_uuid]["playlist"]["current_track"]
        previous_track = previous_tracks.pop()
        self.logger.debug(
            'Found previous track to play on player "%s": %s'
            % (player_uuid, previous_track)
        )
        try:
            self.players[player_uuid]["playlist"]["next_tracks"].insert(
                0, current_track
            )
            self.players[player_uuid]["playlist"]["current_track"] = previous_track
            if self.__is_filepath(previous_track["resource"]):
                self.__play_file(previous_track["resource"], player_uuid=player_uuid)
            else:
                self.__play_url(
                    previous_track["resource"],
                    previous_track["audio_format"],
                    player_uuid=player_uuid,
                )
            self.logger.info(
                'Player "%s" is playing "%s"'
                % (player_uuid, previous_track["resource"])
            )
        except:
            self.logger.exception(
                "Error playing previous track with player %s: %s"
                % (player_uuid, previous_track)
            )
            return False

        return True

    def get_players(self):
        """
        Return list of players

        Returns:
            list: list of players identifiers
        """
        return [
            {
                "playeruuid": player["uuid"],
                "playback": player["playlist"]["current_track"],
                "state": player["internal"]["last_state"],
            }
            for player in self.players.values()
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
                current (number): current track index (0 is the first playlist track)
            }
        """
        if player_uuid not in self.players:
            raise CommandError('Player "%s" does not exists' % player_uuid)

        tracks = (
            self.players[player_uuid]["playlist"]["previous_tracks"]
            + [self.players[player_uuid]["playlist"]["current_track"]]
            + self.players[player_uuid]["playlist"]["next_tracks"]
        )
        return {
            "tracks": tracks,
            "current": len(self.players[player_uuid]["playlist"]["previous_tracks"]),
        }

    def set_volume(self, player_uuid, volume):
        """
        Set player volume

        Args:
            player_uuid (string): player identifier
            volume (number): percentage volume
        """
        if player_uuid not in self.players:
            raise CommandError('Player "%s" does not exists' % player_uuid)
        if volume < 0 or volume > 100:
            raise InvalidParameter('Parameter "volume" is invalid')

        self.players[player_uuid]["volume"].set_property(
            "volume", float(volume / 100.0)
        )
