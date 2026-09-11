#!/usr/bin/env python
# -*- coding: utf-8 -*-
from cleep.libs.tests import session
import unittest
import logging
import sys

sys.path.append("../")
from backend.audioplayer import Audioplayer
from backend.audioplayer import Gst
from backend.audioplayerplaybackupdateevent import AudioplayerPlaybackUpdateEvent
from cleep.exception import (
    InvalidParameter,
    MissingParameter,
    CommandError,
    Unauthorized,
    CommandInfo,
)
from unittest.mock import Mock, patch, MagicMock
from cleep.libs.tests.common import get_log_level

LOG_LEVEL = get_log_level()

class GstreamerMsg:
    pass


class ParseUrlResult:
    pass


class TestAudioplayer(unittest.TestCase):
    def setUp(self):
        logging.basicConfig(
            level=LOG_LEVEL,
            format=u"%(asctime)s %(name)s:%(lineno)d %(levelname)s : %(message)s",
        )
        self.session = session.TestSession(self)

    def tearDown(self):
        self.session.clean()

    def init(self, start=True, mock_on_stop=True):
        self.module = self.session.setup(Audioplayer, mock_on_stop=mock_on_stop)
        if start:
            self.session.start_module(self.module)

    def test_configure(self):
        self.init(False)

        with patch("backend.audioplayer.Gst") as gstMock:
            self.session.start_module(self.module)
            gstMock.init.assert_called_with(None)

    def test_on_stop(self):
        self.init(mock_on_stop=False)
        player = {
            "uuid": "the-uuid",
            "player": "player-stuff",
        }
        self.module.players = {"the-uuid": player}
        self.module._Audioplayer__destroy_player = Mock()

        self.module._on_stop()

        self.module._Audioplayer__destroy_player.assert_called_with(player)
        self.assertTrue(len(self.module.players.keys()), 0)

    def test__create_playbin(self):
        self.init()
        playbin = Mock()
        audio_sink = Mock()
        video_sink = Mock()
        player_data = {
            "uuid": "the-uuid",
            "player": None,
            "internal": {},
        }

        with patch("backend.audioplayer.Gst.ElementFactory.make") as make_mock:
            make_mock.side_effect = [playbin, audio_sink, video_sink]
            self.module._Audioplayer__create_playbin(player_data)

        playbin.set_property.assert_any_call("flags", Audioplayer.PLAYBIN_FLAGS)
        playbin.set_property.assert_any_call("audio-sink", audio_sink)
        playbin.set_property.assert_any_call("video-sink", video_sink)
        self.assertEqual(player_data["player"], playbin)

    def test__create_playbin_alsa_sink(self):
        self.init()
        self.module._set_config_field("audio_sink", "alsa")
        self.module._set_config_field("alsa_device", "hw:0,0")
        playbin = Mock()
        audio_sink = Mock()
        video_sink = Mock()
        player_data = {"uuid": "the-uuid", "player": None, "internal": {}}

        with patch("backend.audioplayer.Gst.ElementFactory.make") as make_mock:
            make_mock.side_effect = [playbin, audio_sink, video_sink]
            self.module._Audioplayer__create_playbin(player_data)

        audio_sink.set_property.assert_called_with("device", "hw:0,0")
        playbin.set_property.assert_any_call("audio-sink", audio_sink)

    def test__create_player(self):
        self.init()
        self.module._get_unique_id = Mock(return_value="the-uuid")
        self.module._Audioplayer__create_playbin = Mock()

        result = self.module._Audioplayer__create_player()

        self.assertEqual(result["uuid"], "the-uuid")
        self.assertEqual(result["playlist"]["tracks"], [])
        self.assertFalse(result["internal"]["to_destroy"])
        self.assertIsNone(result["internal"]["fade"])
        self.module._Audioplayer__create_playbin.assert_called_with(result)

    def test_destroy_player(self):
        self.init()
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": ["track1", "track2", "track3"],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
                "fade": {"active": True},
            },
        }
        self.module.players = {"the-uuid": player_data}

        self.module._destroy_player(player_data)

        self.assertTrue(player_data["internal"]["to_destroy"])
        self.assertIsNone(player_data["internal"]["fade"])

    def test__destroy_player(self):
        self.init()
        playbin = Mock()
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": ["track1"],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": playbin,
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
                "fade": None,
            },
        }
        self.module.players = {"the-uuid": player_data}

        self.module._Audioplayer__destroy_player(player_data)

        playbin.set_state.assert_called_with(Gst.State.NULL)
        self.assertEqual(len(self.module.players), 0)
        self.assertIsNone(player_data["player"])

    def test_set_audio_sink_and_fade(self):
        self.init()

        self.module._set_audio_sink("alsa", "hw:1,0")
        self.module.set_fade(1500, 2000)

        self.assertEqual(self.module._get_config_field("audio_sink"), "alsa")
        self.assertEqual(self.module._get_config_field("alsa_device"), "hw:1,0")
        self.assertEqual(self.module._get_config_field("fade_in_ms"), 1500)
        self.assertEqual(self.module._get_config_field("fade_out_ms"), 2000)

    def test_on_process(self):
        self.init()
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": ["track1", "track2", "track3"],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": None,
            "source": None,
            "volume": None,
            "pipeline": [],
            "internal": {
                "to_destroy": True,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__process_players_messages = Mock()
        self.module._Audioplayer__process_fades = Mock()
        self.module._Audioplayer__destroy_player = Mock()

        self.module._on_process()

        self.module._Audioplayer__process_fades.assert_called_once()
        self.module._Audioplayer__process_players_messages.assert_called_once()
        self.module._Audioplayer__destroy_player.assert_called_once_with(player_data)

    def test_on_process_no_player_to_destroy(self):
        self.init()
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": ["track1", "track2", "track3"],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": None,
            "source": None,
            "volume": None,
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__process_players_messages = Mock()
        self.module._Audioplayer__process_fades = Mock()
        self.module._Audioplayer__destroy_player = Mock()

        self.module._on_process()

        self.module._Audioplayer__process_fades.assert_called_once()
        self.module._Audioplayer__process_players_messages.assert_called_once()
        self.assertEqual(self.module._Audioplayer__destroy_player.call_count, 0)

    def test_on_process_no_player(self):
        self.init()
        self.module._Audioplayer__process_players_messages = Mock()
        self.module._Audioplayer__process_fades = Mock()
        self.module._Audioplayer__destroy_player = Mock()

        self.module._on_process()

        self.module._Audioplayer__process_fades.assert_called_once()
        self.module._Audioplayer__process_players_messages.assert_called_once()
        self.assertEqual(self.module._Audioplayer__destroy_player.call_count, 0)

    def test__process_players_messages(self):
        self.init()
        player1_mock = Mock()
        player1_mock.get_bus.return_value.pop.side_effect = ["msg1", "msg2", None]
        player2_mock = Mock()
        player2_mock.get_bus.return_value.pop.side_effect = ["msg3", None]
        self.module.players = {
            "uuid1": {
                "uuid": "uuid1",
                "player": player1_mock,
                "pipeline": [],
                "internal": {
                    "to_destroy": False,
                },
            },
            "uuid2": {
                "uuid": "uuid2",
                "player": player2_mock,
                "pipeline": [],
                "internal": {
                    "to_destroy": False,
                },
            },
        }
        self.module._Audioplayer__process_gstreamer_message = Mock()

        self.module._Audioplayer__process_players_messages()

        self.module._Audioplayer__process_gstreamer_message.assert_any_call(
            "uuid1", session.AnyArg(), "msg1"
        )
        self.module._Audioplayer__process_gstreamer_message.assert_any_call(
            "uuid1", session.AnyArg(), "msg2"
        )
        self.module._Audioplayer__process_gstreamer_message.assert_any_call(
            "uuid2", session.AnyArg(), "msg3"
        )

    def test__process_players_messages_no_player(self):
        self.init()
        self.module._Audioplayer__process_gstreamer_message = Mock()

        self.module._Audioplayer__process_players_messages()

        self.module._Audioplayer__process_gstreamer_message.assert_not_called()

    def test__process_players_messages_exception(self):
        self.init()
        player1_mock = Mock()
        player1_mock.get_bus.return_value.pop.side_effect = Exception("Test exception")
        self.module.players = {
            "uuid1": {
                "uuid": "uuid1",
                "player": player1_mock,
                "pipeline": [],
                "internal": {
                    "to_destroy": False,
                },
            },
        }
        self.module._Audioplayer__process_gstreamer_message = Mock()
        self.module.logger.exception = Mock()

        self.module._Audioplayer__process_players_messages()

        self.module.logger.exception.assert_called_with(
            'Error processing player "%s" messages', "uuid1"
        )

    def test__process_gstreamer_message_eos(self):
        self.init()
        msg = GstreamerMsg()
        msg.type = Gst.MessageType.EOS
        player = Mock()
        self.module._Audioplayer__play_next_track = Mock()
        self.module._Audioplayer__send_playback_event = Mock()

        self.module._Audioplayer__process_gstreamer_message("the-uuid", player, msg)

        player.set_state.assert_called_with(Gst.State.NULL)
        self.module._Audioplayer__play_next_track.assert_called_with("the-uuid")
        self.module._Audioplayer__send_playback_event.assert_called_with(
            "the-uuid", player
        )

    def test__process_gstreamer_message_state_changed(self):
        self.init()
        msg = GstreamerMsg()
        msg.type = Gst.MessageType.STATE_CHANGED
        player = Mock()
        self.module._Audioplayer__play_next_track = Mock()
        self.module._Audioplayer__send_playback_event = Mock()

        self.module._Audioplayer__process_gstreamer_message("the-uuid", player, msg)

        player.set_state.assert_not_called()
        self.module._Audioplayer__play_next_track.assert_not_called()
        self.module._Audioplayer__send_playback_event.assert_called_with(
            "the-uuid", player
        )

    def test__process_gstreamer_message_error(self):
        self.init()
        msg = GstreamerMsg()
        msg.type = Gst.MessageType.ERROR
        msg.parse_error = Mock(return_value=("error", "debug"))
        player = Mock()
        self.module._Audioplayer__play_next_track = Mock()
        self.module._Audioplayer__send_playback_event = Mock()

        self.module._Audioplayer__process_gstreamer_message("the-uuid", player, msg)

        player.set_state.assert_called_with(Gst.State.NULL)
        msg.parse_error.assert_called()
        self.module._Audioplayer__play_next_track.assert_not_called()
        self.module._Audioplayer__send_playback_event.assert_called_with(
            "the-uuid", player
        )

    def test__process_gstreamer_message_tag_with_metadata_complete(self):
        self.init()
        msg = GstreamerMsg()
        msg.type = Gst.MessageType.TAG
        tag = {"album": "dummy"}
        msg.parse_tag = Mock(return_value=tag)
        player = Mock()
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "playlist": {"metadata": {}},
                "pipeline": [],
                "internal": {
                    "tags_sent": False,
                    "to_destroy": False,
                },
            }
        }
        self.module._Audioplayer__play_next_track = Mock()
        self.module._Audioplayer__send_playback_event = Mock()
        self.module._Audioplayer__get_audio_metadata = Mock(return_value=(True, tag))

        self.module._Audioplayer__process_gstreamer_message("the-uuid", player, msg)

        player.set_state.assert_not_called()
        msg.parse_tag.assert_called()
        self.module._Audioplayer__get_audio_metadata.assert_called_with(tag)
        self.module._Audioplayer__play_next_track.assert_not_called()
        self.module._Audioplayer__send_playback_event.assert_called()
        self.assertTrue(self.module.players["the-uuid"]["internal"]["tags_sent"])

        # call another time to check tags are not read again
        msg.parse_tag.reset_mock()
        self.module._Audioplayer__process_gstreamer_message("the-uuid", player, msg)
        msg.parse_tag.assert_not_called()

    def test__process_gstreamer_message_tag_with_metadata_incomplete(self):
        self.init()
        msg = GstreamerMsg()
        msg.type = Gst.MessageType.TAG
        tag = {"album": "dummy"}
        msg.parse_tag = Mock(return_value=tag)
        player = Mock()
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "playlist": {"metadata": {}},
                "pipeline": [],
                "internal": {
                    "tags_sent": False,
                    "to_destroy": False,
                },
            }
        }
        self.module._Audioplayer__play_next_track = Mock()
        self.module._Audioplayer__send_playback_event = Mock()
        self.module._Audioplayer__get_audio_metadata = Mock(return_value=(False, tag))

        self.module._Audioplayer__process_gstreamer_message("the-uuid", player, msg)

        player.set_state.assert_not_called()
        msg.parse_tag.assert_called()
        self.module._Audioplayer__get_audio_metadata.assert_called_with(tag)
        self.module._Audioplayer__play_next_track.assert_not_called()
        self.module._Audioplayer__send_playback_event.assert_not_called()
        self.assertFalse(self.module.players["the-uuid"]["internal"]["tags_sent"])

        # call another time to check tags are not read again
        self.module._Audioplayer__process_gstreamer_message("the-uuid", player, msg)
        msg.parse_tag.assert_called()
        self.assertFalse(self.module.players["the-uuid"]["internal"]["tags_sent"])

    def test__process_gstreamer_message_duration_changed(self):
        self.init()
        msg = GstreamerMsg()
        msg.type = Gst.MessageType.DURATION_CHANGED
        player = Mock()
        self.module._Audioplayer__play_next_track = Mock()
        self.module._Audioplayer__send_playback_event = Mock()

        self.module._Audioplayer__process_gstreamer_message("the-uuid", player, msg)

        player.set_state.assert_not_called()
        self.module._Audioplayer__play_next_track.assert_not_called()
        self.module._Audioplayer__send_playback_event.assert_called()

    def test__send_playback_event(self):
        self.init()
        player = Mock()
        player.get_state.return_value = ("dummy", Gst.State.PAUSED, "dummy")
        player.query_duration.return_value = (True, 666000000000)
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "internal": {
                    "tags_sent": False,
                    "to_destroy": False,
                    "last_state": None,
                },
                "playlist": {
                    "index": 0,
                    "metadata": {},
                    "tracks": ["track1"],
                    "duration": 123,
                },
            }
        }

        self.module._Audioplayer__send_playback_event("the-uuid", player)

        self.assertEqual(
            self.module.players["the-uuid"]["internal"]["last_state"], Gst.State.PAUSED
        )
        self.session.assert_event_called_with(
            "audioplayer.playback.update",
            {
                "playeruuid": "the-uuid",
                "state": "paused",
                "index": 0,
                "duration": 666,
                "metadata": {},
                "track": "track1",
            },
        )

    def test__send_playback_event_no_duration(self):
        self.init()
        player = Mock()
        player.get_state.return_value = ("dummy", Gst.State.PAUSED, "dummy")
        player.query_duration.return_value = (False, 0)
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "internal": {
                    "tags_sent": False,
                    "to_destroy": False,
                    "last_state": None,
                },
                "playlist": {
                    "index": 0,
                    "metadata": {},
                    "tracks": ["track1"],
                    "duration": 123,
                },
            }
        }

        self.module._Audioplayer__send_playback_event("the-uuid", player)

        self.assertEqual(
            self.module.players["the-uuid"]["internal"]["last_state"], Gst.State.PAUSED
        )
        self.session.assert_event_called_with(
            "audioplayer.playback.update",
            {
                "playeruuid": "the-uuid",
                "state": "paused",
                "index": 0,
                "duration": 123,
                "metadata": {},
                "track": "track1",
            },
        )

    def test__send_playback_event_same_state(self):
        self.init()
        player = Mock()
        player.get_state = Mock(return_value=("dummy", Gst.State.PAUSED, "dummy"))
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "internal": {
                    "tags_sent": False,
                    "to_destroy": False,
                    "last_state": Gst.State.PAUSED,
                },
            }
        }

        self.module._Audioplayer__send_playback_event("the-uuid", player)

        self.assertEqual(
            self.module.players["the-uuid"]["internal"]["last_state"], Gst.State.PAUSED
        )
        self.assertEqual(
            self.session.event_call_count("audioplayer.playback.update"), 0
        )

    def test__send_playback_event_same_state_but_forced(self):
        self.init()
        player = Mock()
        player.get_state = Mock(return_value=("dummy", Gst.State.PAUSED, "dummy"))
        player.query_duration.return_value = (False, 0)
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "internal": {
                    "tags_sent": False,
                    "to_destroy": False,
                    "last_state": Gst.State.PAUSED,
                },
                "playlist": {
                    "metadata": {},
                    "index": 0,
                    "tracks": ["track1"],
                    "volume": 12,
                    "duration": 123,
                },
            }
        }

        self.module._Audioplayer__send_playback_event("the-uuid", player, force=True)

        self.assertEqual(
            self.module.players["the-uuid"]["internal"]["last_state"], Gst.State.PAUSED
        )
        self.assertEqual(
            self.session.event_call_count("audioplayer.playback.update"), 1
        )

    def test__send_playback_event_ready_state(self):
        self.init()
        player = Mock()
        player.get_state = Mock(return_value=("dummy", Gst.State.READY, "dummy"))
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "internal": {
                    "tags_sent": False,
                    "to_destroy": False,
                    "last_state": Gst.State.PAUSED,
                },
            }
        }

        self.module._Audioplayer__send_playback_event("the-uuid", player)

        self.assertEqual(
            self.module.players["the-uuid"]["internal"]["last_state"], Gst.State.PAUSED
        )
        self.assertEqual(
            self.session.event_call_count("audioplayer.playback.update"), 0
        )

    def test__get_playback_info(self):
        self.init()
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "internal": {
                    "tags_sent": False,
                    "to_destroy": False,
                    "last_state": Gst.State.PAUSED,
                },
                "playlist": {
                    "duration": 123,
                    "index": 0,
                    "tracks": ["track1"],
                    "volume": 50,
                    "metadata": {},
                },
            }
        }

        result = self.module._Audioplayer__get_playback_info("the-uuid")
        logging.debug("Playback info: %s", result)

        self.assertDictEqual(
            result,
            {
                "index": 0,
                "playeruuid": "the-uuid",
                "track": "track1",
                "metadata": {},
                "state": "paused",
                "duration": 123,
            },
        )

    def test__get_playback_info_player_not_found(self):
        self.init()
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "internal": {
                    "tags_sent": False,
                    "to_destroy": False,
                    "last_state": Gst.State.PAUSED,
                },
                "playlist": {
                    "duration": 123,
                    "index": 0,
                    "tracks": ["track1"],
                    "volume": 50,
                    "metadata": {},
                },
            }
        }

        result = self.module._Audioplayer__get_playback_info("dummy")
        logging.debug("Playback info: %s", result)

        self.assertDictEqual(
            result,
            {
                "index": 0,
                "playeruuid": "dummy",
                "track": None,
                "metadata": {},
                "state": "stopped",
                "duration": 0,
            },
        )

    def test__get_audio_metadata(self):
        self.init()
        tags = Mock()
        tags.to_string.return_value = "all-tags"
        tags.nth_tag_name.side_effect = [
            "artist",
            "album-artist",
            "album",
            "title",
            "genre",
            "track-number",
            "datetime",
            "channel-mode",
            "minimum-bitrate",
            "maximum-bitrate",
            "bitrate",
        ]
        tags.get_string.side_effect = [
            (True, "[artist]"),
            (True, "[album-artist]"),
            (True, "[album]"),
            (True, "[title]"),
            (True, "[genre]"),
            (True, "[channel-mode]"),
        ]
        tags.get_uint.side_effect = [
            (True, 2),  # track-number
            (True, 333),  # min bitrate
            (True, 999),  # max bitrate
            (True, 666),  # bitrate
        ]
        date_time = Mock()
        date_time.has_year.return_value = True
        date_time.get_year.return_value = 2021
        tags.get_date_time.return_value = (True, date_time)
        tags.n_tags.return_value = 11

        complete, metadata = self.module._Audioplayer__get_audio_metadata(tags)
        logging.debug("Metadata: %s", metadata)

        self.assertTrue(complete)
        self.assertDictEqual(
            metadata,
            {
                "artist": "[album-artist]",
                "album": "[album]",
                "title": "[title]",
                "genre": "[genre]",
                "year": 2021,
                "track": 2,
                "channels": "[channel-mode]",
                "bitratemin": 333,
                "bitratemax": 999,
                "bitrateavg": 666,
            },
        )

    def test__get_audio_metadata_track_string(self):
        self.init()
        tags = Mock()
        tags.to_string.return_value = "all-tags"
        tags.nth_tag_name.side_effect = [
            "track-number",
        ]
        tags.get_string.side_effect = [
            (True, "3"),
        ]
        tags.get_uint.side_effect = [
            (False, 2),  # track-number
        ]
        tags.n_tags.return_value = 1

        complete, metadata = self.module._Audioplayer__get_audio_metadata(tags)
        logging.debug("Metadata: %s", metadata)

        self.assertFalse(complete)
        self.assertDictEqual(
            metadata,
            {
                "artist": None,
                "album": None,
                "title": None,
                "genre": None,
                "year": None,
                "track": "3",
                "channels": None,
                "bitratemin": None,
                "bitratemax": None,
                "bitrateavg": None,
            },
        )

    @patch("backend.audioplayer.magic.from_file")
    def test__get_file_audio_format(self, mock_from_file):
        self.init()
        mock_from_file.return_value = "audio/mpeg"

        result = self.module._Audioplayer__get_file_audio_format("/audio/file/path.mp3")
        logging.debug("Format: %s" % result)

        self.assertEqual(result, "audio/mpeg")

    @patch("backend.audioplayer.magic.from_file")
    def test__get_file_audio_format_unknown_format(self, mock_from_file):
        self.init()
        mock_from_file.return_value = "audio/dummy"

        result = self.module._Audioplayer__get_file_audio_format("/audio/file/path.mp3")
        logging.debug("Format: %s" % result)

        self.assertIsNone(result)

    @patch("backend.audioplayer.magic.from_file")
    def test__get_file_audio_format_exception(self, mock_from_file):
        self.init()
        mock_from_file.side_effect = Exception("Test exception")

        result = self.module._Audioplayer__get_file_audio_format("/audio/file/path.mp3")
        logging.debug("Format: %s" % result)

        self.assertIsNone(result)

    def test_is_filepath(self):
        self.init()

        with patch("backend.audioplayer.os.path.exists") as exists_mock:
            exists_mock.return_value = True

            self.assertTrue(self.module._is_filepath("/dummy/resource"))

        with patch("backend.audioplayer.os.path.exists") as exists_mock:
            with patch("backend.audioplayer.urlparse") as url_parse_mock:
                exists_mock.return_value = False
                result = ParseUrlResult()
                result.scheme = "https"
                url_parse_mock.return_value = result

                self.assertFalse(self.module._is_filepath("/dummy/resource"))

        with patch("backend.audioplayer.os.path.exists") as exists_mock:
            with patch("backend.audioplayer.urlparse") as url_parse_mock:
                exists_mock.return_value = False
                result = ParseUrlResult()
                result.scheme = "dummy"
                url_parse_mock.return_value = result

                with self.assertRaises(Exception) as cm:
                    self.assertFalse(self.module._is_filepath("/dummy/resource"))
                self.assertEqual(
                    str(cm.exception), "Resource is invalid (file may not exist)"
                )

    def test_make_track(self):
        self.init()

        result = self.module._make_track("/dummy/resource", "audio/dummy")

        self.assertDictEqual(
            result,
            {
                "resource": "/dummy/resource",
                "audio_format": "audio/dummy",
            },
        )

    def test_add_track(self):
        self.init()
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "playlist": {
                    "tracks": ["track1"],
                    "index": 0,
                },
                "internal": {
                    "to_destroy": False,
                },
            }
        }
        track = self.module._make_track("/dummy/resource", "audio/mpeg")

        with patch("backend.audioplayer.os.path.exists") as exists_mock:
            exists_mock.return_value = True

            self.module.add_track("the-uuid", "/dummy/resource", "audio/mpeg")

            self.assertDictEqual(
                self.module.players["the-uuid"]["playlist"]["tracks"][-1], track
            )

    def test_add_track_playlist_limit_reached(self):
        self.init()
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "playlist": {
                    "tracks": ["track1"],
                    "index": 0,
                },
                "internal": {
                    "to_destroy": False,
                },
            }
        }
        self.module.MAX_PLAYLIST_TRACKS = 3

        with patch("backend.audioplayer.os.path.exists") as exists_mock:
            exists_mock.return_value = True

            self.assertTrue(
                self.module.add_track("the-uuid", "/dummy/resource", "audio/mpeg")
            )
            self.assertTrue(
                self.module.add_track("the-uuid", "/dummy/resource", "audio/mpeg")
            )
            self.assertTrue(
                self.module.add_track("the-uuid", "/dummy/resource", "audio/mpeg")
            )
            self.assertFalse(
                self.module.add_track("the-uuid", "/dummy/resource", "audio/mpeg")
            )

    def test_add_track_exception(self):
        self.init()
        self.module.players = {}

        with self.assertRaises(Exception) as cm:
            self.module.add_track("the-uuid", "/dummy/resource", "audio/dummy")
        self.assertEqual(str(cm.exception), 'Player "the-uuid" does not exist')

        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "internal": {"to_destroy": False},
            }
        }
        with patch("backend.audioplayer.os.path.exists") as exists_mock:
            with patch("backend.audioplayer.urlparse") as url_parse_mock:
                exists_mock.return_value = False
                result = ParseUrlResult()
                result.scheme = "http"
                url_parse_mock.return_value = result

                with self.assertRaises(MissingParameter) as cm:
                    self.module.add_track("the-uuid", "/dummy/resource/url")
                self.assertEqual(
                    str(cm.exception), "Url resource must have audio_format specified"
                )

                with self.assertRaises(Exception) as cm:
                    self.module.add_track("the-uuid", "/dummy/resource", "audio/dummy")
                self.assertEqual(
                    str(cm.exception), 'Audio format "audio/dummy" is not supported'
                )

    def test_add_tracks(self):
        self.init()
        track = self.module._make_track("/dummy/resource", "audio/dummy")
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "playlist": {
                    "tracks": [track],
                    "index": 0,
                },
                "internal": {
                    "to_destroy": False,
                },
            }
        }
        self.module.add_track = Mock(return_value=True)

        self.module.add_tracks("the-uuid", [track, track, track])

        self.assertEqual(self.module.add_track.call_count, 3)

    def test_add_tracks_playlist_limit_reached(self):
        self.init()
        track = self.module._make_track("/dummy/resource", "audio/dummy")
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "playlist": {
                    "tracks": [track],
                    "index": 0,
                },
                "internal": {
                    "to_destroy": False,
                },
            }
        }
        self.module.add_track = Mock(side_effect=[True, True, False])

        with self.assertRaises(CommandInfo) as cm:
            self.module.add_tracks("the-uuid", [track, track, track, track])
        self.assertEqual(
            str(cm.exception), "All tracks were not added (playlist limit reached)"
        )

    def test_remove_track_middle(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        track3 = self.module._make_track("/resource/track3", "audio/dummy")
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "playlist": {
                    "tracks": [track1, track2, track3],
                    "index": 0,
                },
                "internal": {
                    "to_destroy": False,
                },
            }
        }

        self.module.remove_track("the-uuid", 1)
        logging.debug(
            "Playlist tracks:%s" % self.module.players["the-uuid"]["playlist"]["tracks"]
        )

        self.assertListEqual(
            self.module.players["the-uuid"]["playlist"]["tracks"], [track1, track3]
        )

    def test_remove_track_last(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        track3 = self.module._make_track("/resource/track3", "audio/dummy")
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "playlist": {
                    "tracks": [track1, track2, track3],
                    "index": 0,
                },
                "internal": {
                    "to_destroy": False,
                },
            }
        }

        self.module.remove_track("the-uuid", 2)
        logging.debug(
            "Playlist tracks:%s" % self.module.players["the-uuid"]["playlist"]["tracks"]
        )

        self.assertListEqual(
            self.module.players["the-uuid"]["playlist"]["tracks"], [track1, track2]
        )

    def test_remove_track_first(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        track3 = self.module._make_track("/resource/track3", "audio/dummy")
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "playlist": {
                    "tracks": [track1, track2, track3],
                    "index": 1,
                },
                "internal": {
                    "to_destroy": False,
                },
            }
        }

        self.module.remove_track("the-uuid", 0)
        logging.debug(
            "Playlist tracks:%s" % self.module.players["the-uuid"]["playlist"]["tracks"]
        )

        self.assertListEqual(
            self.module.players["the-uuid"]["playlist"]["tracks"], [track2, track3]
        )

    def test_remove_track_exception(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        track3 = self.module._make_track("/resource/track3", "audio/dummy")
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "playlist": {
                    "tracks": [track1, track2, track3],
                    "index": 0,
                },
                "internal": {
                    "to_destroy": False,
                },
            }
        }

        with self.assertRaises(InvalidParameter) as cm:
            self.module.remove_track("the-uuid", 0)
        self.assertEqual(str(cm.exception), "You can't remove current track")

        with self.assertRaises(InvalidParameter) as cm:
            self.module.remove_track("the-uuid", -1)
        self.assertEqual(str(cm.exception), "Track index is invalid")

        with self.assertRaises(InvalidParameter) as cm:
            self.module.remove_track("the-uuid", 3)
        self.assertEqual(str(cm.exception), "Track index is invalid")

        with self.assertRaises(InvalidParameter) as cm:
            self.module.remove_track("dummy", 1)
        self.assertEqual(str(cm.exception), 'Player "dummy" does not exist')

    def test_start_playback(self):
        self.init()
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [],
                "repeat": False,
                "volume": None,
                "metadata": {},
            },
            "player": None,
            "source": None,
            "volume": None,
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": False,
                "last_state": None,
            },
        }
        self.module._Audioplayer__play_track = Mock()
        self.module._Audioplayer__destroy_player = Mock()
        self.module._Audioplayer__create_player = Mock(return_value=player_data)

        result = self.module.start_playback("/resource/dummy")

        self.module._Audioplayer__create_player.assert_called()
        self.module._Audioplayer__play_track.assert_called_with(
            {"resource": "/resource/dummy", "audio_format": None},
            "the-uuid",
            100,
            False,
        )
        self.assertEqual(result, player_data["uuid"])
        self.module._Audioplayer__destroy_player.assert_not_called()

    def test_start_playback_exception(self):
        self.init()
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [],
                "repeat": False,
                "volume": None,
                "metadata": {},
            },
            "player": None,
            "source": None,
            "volume": None,
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": False,
                "last_state": None,
            },
        }
        self.module._Audioplayer__play_track = Mock(
            side_effect=Exception("Test exception")
        )
        self.module._Audioplayer__destroy_player = Mock()
        self.module._Audioplayer__create_player = Mock(return_value=player_data)

        with self.assertRaises(CommandError) as cm:
            self.module.start_playback("/resource/dummy")
        self.assertEqual(str(cm.exception), "Unable to play resource")

        self.module._Audioplayer__create_player.assert_called()
        self.module._Audioplayer__play_track.assert_called_with(
            {"resource": "/resource/dummy", "audio_format": None},
            "the-uuid",
            100,
            False,
        )
        self.module._Audioplayer__destroy_player.assert_called_with(player_data)

    @patch("backend.audioplayer.Audioplayer._is_filepath")
    def test__play_track_with_file(self, is_filepath_mock):
        self.init()
        is_filepath_mock.return_value = True
        playbin = Mock()
        track = self.module._make_track("/resource/dummy", "audio/mpeg")
        self.module._Audioplayer__get_file_audio_format = Mock(
            return_value="audio/mpeg"
        )
        self.module._Audioplayer__resource_to_uri = Mock(return_value="file:///resource/dummy")
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": playbin,
                "playlist": {
                    "tracks": [],
                    "index": 0,
                    "volume": 50,
                    "metadata": None,
                    "duration": None,
                },
                "internal": {
                    "to_destroy": False,
                    "tags_sent": False,
                    "last_state": Gst.State.NULL,
                    "target_volume": 1.0,
                    "fade": None,
                },
            }
        }

        self.module._Audioplayer__play_track(track, "the-uuid")

        self.module._Audioplayer__get_file_audio_format.assert_called_with(
            "/resource/dummy"
        )
        playbin.set_property.assert_any_call("uri", "file:///resource/dummy")
        playbin.set_property.assert_any_call("volume", 0.5)
        playbin.set_state.assert_any_call(Gst.State.PLAYING)

    @patch("backend.audioplayer.Audioplayer._is_filepath")
    def test__play_track_with_url(self, is_filepath_mock):
        self.init()
        is_filepath_mock.return_value = False
        playbin = Mock()
        track = self.module._make_track("http://example/stream", "audio/mpeg")
        self.module._Audioplayer__get_file_audio_format = Mock()
        self.module._Audioplayer__resource_to_uri = Mock(return_value="http://example/stream")
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": playbin,
                "playlist": {
                    "tracks": [],
                    "index": 0,
                    "volume": 50,
                    "metadata": None,
                    "duration": None,
                },
                "internal": {
                    "to_destroy": False,
                    "tags_sent": False,
                    "last_state": Gst.State.NULL,
                    "target_volume": 1.0,
                    "fade": None,
                },
            }
        }

        self.module._Audioplayer__play_track(track, "the-uuid")

        self.module._Audioplayer__get_file_audio_format.assert_not_called()
        playbin.set_property.assert_any_call("uri", "http://example/stream")
        playbin.set_state.assert_any_call(Gst.State.PLAYING)

    @patch("backend.audioplayer.Audioplayer._is_filepath")
    def test__play_track_with_volume(self, is_filepath_mock):
        self.init()
        is_filepath_mock.return_value = True
        playbin = Mock()
        track = self.module._make_track("/resource/dummy", "audio/mpeg")
        self.module._Audioplayer__get_file_audio_format = Mock(
            return_value="audio/mpeg"
        )
        self.module._Audioplayer__resource_to_uri = Mock(return_value="file:///resource/dummy")
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": playbin,
                "playlist": {
                    "tracks": [],
                    "index": 0,
                    "volume": 50,
                    "metadata": None,
                    "duration": None,
                },
                "internal": {
                    "to_destroy": False,
                    "tags_sent": False,
                    "last_state": Gst.State.NULL,
                    "target_volume": 1.0,
                    "fade": None,
                },
            }
        }

        self.module._Audioplayer__play_track(track, "the-uuid", 66)

        playbin.set_property.assert_any_call("volume", 0.66)
        self.assertEqual(self.module.players["the-uuid"]["playlist"]["volume"], 66)

    @patch("backend.audioplayer.Audioplayer._is_filepath")
    def test__play_track_get_audio_format_failed(self, is_filepath_mock):
        self.init()
        is_filepath_mock.return_value = True
        playbin = Mock()
        track = self.module._make_track("/resource/dummy", "audio/mpeg")
        self.module._Audioplayer__get_file_audio_format = Mock(return_value=None)
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": playbin,
                "playlist": {
                    "tracks": [],
                    "index": 0,
                    "volume": 50,
                },
                "internal": {
                    "to_destroy": False,
                    "fade": None,
                },
            }
        }

        with self.assertRaises(CommandError) as cm:
            self.module._Audioplayer__play_track(track, "the-uuid")
        self.assertEqual(str(cm.exception), "Audio file not supported")

    @patch("backend.audioplayer.Audioplayer._is_filepath")
    def test__play_track_exception(self, is_filepath_mock):
        self.init()
        is_filepath_mock.return_value = True
        playbin = Mock()
        playbin.set_property.side_effect = Exception("Test exception")
        track = self.module._make_track("/resource/dummy", "audio/mpeg")
        self.module._Audioplayer__get_file_audio_format = Mock(
            return_value="audio/mpeg"
        )
        self.module._Audioplayer__resource_to_uri = Mock(return_value="file:///resource/dummy")
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": playbin,
                "playlist": {
                    "tracks": [],
                    "index": 0,
                    "volume": 50,
                    "metadata": None,
                    "duration": None,
                },
                "internal": {
                    "to_destroy": False,
                    "tags_sent": False,
                    "last_state": Gst.State.NULL,
                    "target_volume": 1.0,
                    "fade": None,
                },
            }
        }

        with self.assertRaises(Exception) as cm:
            self.module._Audioplayer__play_track(track, "the-uuid")
        self.assertEqual(str(cm.exception), "Test exception")

    def test_get_track_index(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        track3 = self.module._make_track("/resource/track3", "audio/dummy")
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "playlist": {
                    "tracks": [track1, track2, track3],
                    "index": 0,
                },
                "internal": {
                    "to_destroy": False,
                },
            }
        }

        index = self.module._get_track_index("the-uuid", track1)
        self.assertEqual(index, 0)

        index = self.module._get_track_index("the-uuid", track3)
        self.assertEqual(index, 2)

        index = self.module._get_track_index("the-uuid", track2)
        self.assertEqual(index, 1)

    def test_get_track_index_unknown_track(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        track3 = self.module._make_track("/resource/track3", "audio/dummy")
        self.module.players = {
            "the-uuid": {
                "uuid": "the-uuid",
                "player": None,
                "pipeline": [],
                "playlist": {
                    "tracks": [track1, track3],
                    "index": 0,
                },
                "internal": {
                    "to_destroy": False,
                },
            }
        }

        index = self.module._get_track_index("the-uuid", track2)
        self.assertEqual(index, 0)

    def test_pause_playback_while_playing(self):
        self.init()
        player = Mock()
        player.get_state.return_value = ("dummy", Gst.State.PLAYING, "dummy")
        player.set_state.return_value = Gst.StateChangeReturn.SUCCESS
        player.query_position.return_value = (True, 123456789)
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": player,
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
                "target_volume": 0.55,
                "fade": None,
                "position": None,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._set_volume = Mock()

        self.module.pause_playback("the-uuid")

        player.get_state.assert_any_call(1)
        player.set_state.assert_called_with(Gst.State.PAUSED)
        self.assertEqual(player_data["internal"]["position"], 123456789)
        self.module._set_volume.assert_not_called()

    def test_pause_playback_with_volume(self):
        self.init()
        player = Mock()
        player.get_state.return_value = ("dummy", Gst.State.PLAYING, "dummy")
        player.set_state.return_value = Gst.StateChangeReturn.SUCCESS
        player.query_position.return_value = (True, 1)
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": player,
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
                "target_volume": 0.55,
                "fade": None,
                "position": None,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._set_volume = Mock()

        self.module.pause_playback("the-uuid", volume=66)

        self.module._set_volume.assert_called_with("the-uuid", 66)

    def test_pause_playback_force_play(self):
        self.init()
        player = Mock()
        player.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.PLAYING,
            Gst.State.VOID_PENDING,
        )
        player.set_state.return_value = Gst.StateChangeReturn.SUCCESS
        player.query_position.return_value = (True, 42)
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": player,
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PAUSED,
                "target_volume": 0.55,
                "fade": None,
                "position": 42,
            },
        }
        self.module.players = {"the-uuid": player_data}

        self.module.pause_playback("the-uuid", force_play=True)

        player.set_state.assert_called_with(Gst.State.PLAYING)

    def test_pause_playback_force_pause(self):
        self.init()
        player = Mock()
        player.get_state.return_value = ("dummy", Gst.State.PLAYING, "dummy")
        player.set_state.return_value = Gst.StateChangeReturn.SUCCESS
        player.query_position.return_value = (True, 99)
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": player,
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
                "target_volume": 0.55,
                "fade": None,
                "position": None,
            },
        }
        self.module.players = {"the-uuid": player_data}

        self.module.pause_playback("the-uuid", force_pause=True)

        player.set_state.assert_called_with(Gst.State.PAUSED)

    def test_pause_playback_while_paused(self):
        self.init()
        player = Mock()
        player.get_state.side_effect = [
            ("dummy", Gst.State.PAUSED, "dummy"),
            (
                Gst.StateChangeReturn.SUCCESS,
                Gst.State.PLAYING,
                Gst.State.VOID_PENDING,
            ),
        ]
        player.set_state.return_value = Gst.StateChangeReturn.SUCCESS
        player.query_position.return_value = (True, 42)
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": player,
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PAUSED,
                "target_volume": 0.55,
                "fade": None,
                "position": 42,
            },
        }
        self.module.players = {"the-uuid": player_data}

        self.module.pause_playback("the-uuid")

        player.get_state.assert_any_call(1)
        player.set_state.assert_called_with(Gst.State.PLAYING)

    def test_pause_playback_resume_recreates_on_failure(self):
        self.init()
        player = Mock()
        player.get_state.side_effect = [
            ("dummy", Gst.State.PAUSED, "dummy"),
            (
                Gst.StateChangeReturn.FAILURE,
                Gst.State.NULL,
                Gst.State.VOID_PENDING,
            ),
        ]
        player.set_state.return_value = Gst.StateChangeReturn.FAILURE
        player.query_position.return_value = (True, 5000)
        track1 = self.module._make_track("/resource/track1", "audio/mpeg")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1],
                "repeat": False,
                "volume": 80,
                "metadata": {},
            },
            "player": player,
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PAUSED,
                "target_volume": 0.8,
                "fade": None,
                "position": 5000,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__recreate_playback = Mock(return_value="playing")

        result = self.module.pause_playback("the-uuid", force_play=True)

        self.module._Audioplayer__recreate_playback.assert_called_with(
            "the-uuid", playing=True
        )
        self.assertEqual(result, "playing")

    def test_pause_playback_invalid_params(self):
        self.init()

        with self.assertRaises(InvalidParameter) as cm:
            self.module.pause_playback("dummy")
        self.assertEqual(str(cm.exception), 'Player "dummy" does not exist')

    def test_stop_playback(self):
        self.init()
        player = Mock()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1],
                "repeat": True,
                "volume": 55,
                "metadata": {},
                "duration": 12,
            },
            "player": player,
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._destroy_player = Mock()

        self.module.stop_playback("the-uuid")

        player.set_state.assert_called_with(Gst.State.NULL)
        self.module._destroy_player.assert_called_with(player_data)
        self.session.assert_event_called_with(
            "audioplayer.playback.update",
            {
                "playeruuid": "the-uuid",
                "state": "stopped",
            },
        )

    def test_stop_playback_invalid_params(self):
        self.init()

        with self.assertRaises(InvalidParameter) as cm:
            self.module.stop_playback("dummy")
        self.assertEqual(str(cm.exception), 'Player "dummy" does not exist')

    def test_play_next_track(self):
        self.init()
        player = Mock()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1, track2],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": player,
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__play_next_track = Mock(return_value=True)

        result = self.module.play_next_track("the-uuid")

        self.assertTrue(result)
        self.module._Audioplayer__play_next_track.assert_called_with("the-uuid")

    def test_play_next_track_no_more_track(self):
        self.init()
        player = Mock()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1, track2],
                "repeat": False,
                "volume": 55,
                "metadata": {},
            },
            "player": player,
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__play_next_track = Mock(return_value=True)

        result = self.module.play_next_track("the-uuid")

        self.assertFalse(result)
        self.module._Audioplayer__play_next_track.assert_not_called()

    def test_play_next_track_no_more_track_but_repeat_enabled(self):
        self.init()
        player = Mock()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1, track2],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": player,
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__play_next_track = Mock(return_value=True)

        result = self.module.play_next_track("the-uuid")

        self.assertTrue(result)
        self.module._Audioplayer__play_next_track.assert_called_with("the-uuid")

    def test_play_next_track_error_playing_track(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1, track2],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__play_next_track = Mock(return_value=False)

        with self.assertRaises(CommandError) as cm:
            self.module.play_next_track("the-uuid")
        self.assertEqual(str(cm.exception), "Error playing next track")

    def test_play_next_track_invalid_params(self):
        self.init()

        with self.assertRaises(InvalidParameter) as cm:
            self.module.play_next_track("dummy")
        self.assertEqual(str(cm.exception), 'Player "dummy" does not exist')

    def test__play_next_track(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1, track2],
                "repeat": False,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__handle_end_of_playlist = Mock()
        self.module._Audioplayer__play_track = Mock()

        result = self.module._Audioplayer__play_next_track("the-uuid")

        self.assertTrue(result)
        self.module._Audioplayer__handle_end_of_playlist.assert_not_called()
        self.module._Audioplayer__play_track.assert_called_with(track2, "the-uuid")
        self.assertEqual(player_data["playlist"]["index"], 1)

    def test__play_next_track_exception(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1, track2],
                "repeat": False,
                "volume": 55,
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__handle_end_of_playlist = Mock()
        self.module._Audioplayer__play_track = Mock(
            side_effect=Exception("Test exception")
        )

        result = self.module._Audioplayer__play_next_track("the-uuid")

        self.assertFalse(result)
        self.module._Audioplayer__handle_end_of_playlist.assert_not_called()

    def test__play_next_track_handle_end_of_playlist(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1, track2],
                "repeat": False,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}

        self.module._Audioplayer__handle_end_of_playlist = Mock(return_value=False)
        result = self.module._Audioplayer__play_next_track("the-uuid")
        self.assertFalse(result)

        self.module._Audioplayer__handle_end_of_playlist.return_value = True
        result = self.module._Audioplayer__play_next_track("the-uuid")
        self.assertTrue(result)

    def test__play_next_track_invalid_params(self):
        self.init()

        self.assertFalse(self.module._Audioplayer__play_next_track("dummy"))

    def test__handle_end_of_playlist(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1, track2],
                "repeat": False,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._destroy_player = Mock()

        result = self.module._Audioplayer__handle_end_of_playlist("the-uuid")

        self.assertFalse(result)
        self.module._destroy_player.assert_called_with(player_data)

    def test__handle_end_of_playlist_repeat_enabled(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1, track2],
                "repeat": True,
                "shuffle": False,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._destroy_player = Mock()
        self.module._Audioplayer__play_track = Mock()
        self.module.shuffle_playlist = Mock()

        result = self.module._Audioplayer__handle_end_of_playlist("the-uuid")

        self.assertTrue(result)
        self.module._destroy_player.assert_not_called()
        self.module._Audioplayer__play_track.assert_called_with(track1, "the-uuid")
        self.module.shuffle_playlist.assert_not_called()

    def test__handle_end_of_playlist_shuffle_enabled(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1, track2],
                "repeat": True,
                "shuffle": True,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._destroy_player = Mock()
        self.module._Audioplayer__play_track = Mock()
        self.module.shuffle_playlist = Mock()

        result = self.module._Audioplayer__handle_end_of_playlist("the-uuid")

        self.assertTrue(result)
        self.module._destroy_player.assert_not_called()
        self.module._Audioplayer__play_track.assert_called_with(track1, "the-uuid")
        self.module.shuffle_playlist.assert_called()

    def test_play_previous_track(self):
        self.init()
        player = Mock()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1, track2],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": player,
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__play_track = Mock()

        result = self.module.play_previous_track("the-uuid")

        self.assertTrue(result)
        self.assertEqual(player_data["playlist"]["index"], 0)
        self.module._Audioplayer__play_track.assert_called_with(track1, "the-uuid")

    def test_play_previous_track_first_track(self):
        self.init()
        player = Mock()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1, track2],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": player,
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__play_track = Mock(return_value=True)

        result = self.module.play_previous_track("the-uuid")

        self.assertFalse(result)
        self.assertEqual(player_data["playlist"]["index"], 0)
        self.module._Audioplayer__play_track.assert_not_called()

    def test_play_previous_track_error_playing_track(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1, track2],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": 1,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__play_track = Mock(
            side_effect=Exception("Test exception")
        )

        with self.assertRaises(Exception) as cm:
            self.module.play_previous_track("the-uuid")
        self.assertEqual(str(cm.exception), "Test exception")

    def test_play_previous_track_invalid_params(self):
        self.init()

        with self.assertRaises(InvalidParameter) as cm:
            self.module.play_previous_track("dummy")
        self.assertEqual(str(cm.exception), 'Player "dummy" does not exist')

    def test_play_track(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1, track2],
                "repeat": True,
                "volume": 55,
                "metadata": {},
                "duration": 666,
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__play_track = Mock()

        result = self.module.play_track("the-uuid", 1)

        self.assertTrue(result)
        self.module._Audioplayer__play_track.assert_called_with(track2, "the-uuid")

    def test_play_track_invalid_track_index(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1, track2],
                "repeat": True,
                "volume": 55,
                "metadata": {},
                "duration": 666,
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__play_track = Mock()

        result = self.module.play_track("the-uuid", 2)
        self.assertFalse(result)

        result = self.module.play_track("the-uuid", -1)
        self.assertFalse(result)

        self.assertEqual(self.module._Audioplayer__play_track.call_count, 0)

    def test_play_track_invalid_player(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1, track2],
                "repeat": True,
                "volume": 55,
                "metadata": {},
                "duration": 666,
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__play_track = Mock()

        result = self.module.play_track("an-uuid", 1)

        self.assertFalse(result)
        self.assertEqual(self.module._Audioplayer__play_track.call_count, 0)

    def test_play_track_play_track_failed(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1, track2],
                "repeat": True,
                "volume": 55,
                "metadata": {},
                "duration": 666,
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
            },
        }
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__play_track = Mock(
            side_effect=Exception("Test exception")
        )

        result = self.module.play_track("the-uuid", 1)

        self.assertFalse(result)

    def test_get_players(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1, track2],
                "repeat": True,
                "volume": 55,
                "metadata": {},
                "duration": 666,
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
            },
        }
        self.module.players = {"the-uuid": player_data}

        players = self.module.get_players()
        logging.debug("Players: %s", players)

        self.assertListEqual(
            players,
            [
                {
                    "playeruuid": "the-uuid",
                    "track": track2,
                    "state": "playing",
                    "duration": 666,
                    "index": 1,
                    "metadata": {},
                }
            ],
        )

    def test_get_playlist(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 1,
                "tracks": [track1, track2],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
            },
        }
        self.module.players = {"the-uuid": player_data}

        playlist = self.module.get_playlist("the-uuid")
        logging.debug("Playlist: %s", playlist)

        self.assertEqual(playlist["index"], 1)
        self.assertListEqual(playlist["tracks"], [track1, track2])

    def test_get_playlist_invalid_params(self):
        self.init()

        with self.assertRaises(InvalidParameter) as cm:
            self.module.get_playlist("dummy")
        self.assertEqual(str(cm.exception), 'Player "dummy" does not exist')

    def test_set_volume(self):
        self.init()
        playbin = Mock()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": playbin,
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
                "target_volume": 0.55,
                "fade": None,
            },
        }
        self.module.players = {"the-uuid": player_data}

        self.module.set_volume("the-uuid", 1)
        self.module.set_volume("the-uuid", 100)
        self.module.set_volume("the-uuid", 66)

        self.assertEqual(player_data["playlist"]["volume"], 66)
        playbin.set_property.assert_called_with("volume", 0.66)

    def test_set_volume_invalid_params(self):
        self.init()
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [{}],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
            },
        }
        self.module.players = {"the-uuid": player_data}

        with self.assertRaises(InvalidParameter) as cm:
            self.module.set_volume("dummy", 50)
        self.assertEqual(str(cm.exception), 'Player "dummy" does not exist')

        with self.assertRaises(InvalidParameter) as cm:
            self.module.set_volume("the-uuid", -1)
        self.assertEqual(str(cm.exception), "Volume must be between 1 and 100")

        with self.assertRaises(InvalidParameter) as cm:
            self.module.set_volume("the-uuid", 101)
        self.assertEqual(str(cm.exception), "Volume must be between 1 and 100")

    def test_set_repeat(self):
        self.init()
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [{}],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
            },
        }
        self.module.players = {"the-uuid": player_data}

        self.module.set_repeat("the-uuid", False)
        self.assertFalse(player_data["playlist"]["repeat"])

        self.module.set_repeat("the-uuid", True)
        self.assertTrue(player_data["playlist"]["repeat"])

    def test_set_repeat_invalid_params(self):
        self.init()

        with self.assertRaises(InvalidParameter) as cm:
            self.module.set_repeat("dummy", True)
        self.assertEqual(str(cm.exception), 'Player "dummy" does not exist')

    def test_shuffle_playlist_first_track_playing(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        track3 = self.module._make_track("/resource/track3", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track1, track2, track3],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
            },
        }
        self.module.players = {"the-uuid": player_data}

        self.module.shuffle_playlist("the-uuid")

        self.assertDictEqual(player_data["playlist"]["tracks"][0], track1)
        self.assertEqual(player_data["playlist"]["index"], 0)

    def test_shuffle_playlist_last_track_playing(self):
        self.init()
        track1 = self.module._make_track("/resource/track1", "audio/dummy")
        track2 = self.module._make_track("/resource/track2", "audio/dummy")
        track3 = self.module._make_track("/resource/track3", "audio/dummy")
        player_data = {
            "uuid": "the-uuid",
            "playlist": {
                "index": 2,
                "tracks": [track1, track2, track3],
                "repeat": True,
                "volume": 55,
                "metadata": {},
            },
            "player": Mock(),
            "source": Mock(),
            "volume": Mock(),
            "pipeline": [],
            "internal": {
                "to_destroy": False,
                "tags_sent": True,
                "last_state": Gst.State.PLAYING,
            },
        }
        self.module.players = {"the-uuid": player_data}

        self.module.shuffle_playlist("the-uuid")

        self.assertDictEqual(player_data["playlist"]["tracks"][0], track3)
        self.assertEqual(player_data["playlist"]["index"], 0)

    def test_shuffle_playlist_invalid_params(self):
        self.init()

        with self.assertRaises(CommandError) as cm:
            self.module.shuffle_playlist("dummy")
        self.assertEqual(str(cm.exception), 'Player "dummy" does not exist')

    def test__create_playbin_fails_when_playbin_unavailable(self):
        self.init()
        player_data = {"uuid": "the-uuid", "player": None, "internal": {}}

        with patch("backend.audioplayer.Gst.ElementFactory.make", return_value=None):
            with self.assertRaisesRegex(Exception, "Unable to create GStreamer playbin"):
                self.module._Audioplayer__create_playbin(player_data)

    def test__create_playbin_fails_when_autoaudiosink_unavailable(self):
        self.init()
        playbin = Mock()
        player_data = {"uuid": "the-uuid", "player": None, "internal": {}}

        with patch("backend.audioplayer.Gst.ElementFactory.make") as make_mock:
            make_mock.side_effect = [playbin, None]
            with self.assertRaisesRegex(Exception, "Unable to create autoaudiosink"):
                self.module._Audioplayer__create_playbin(player_data)

    def test__create_playbin_fails_when_alsasink_unavailable(self):
        self.init()
        self.module._set_config_field("audio_sink", "alsa")
        playbin = Mock()
        player_data = {"uuid": "the-uuid", "player": None, "internal": {}}

        with patch("backend.audioplayer.Gst.ElementFactory.make") as make_mock:
            make_mock.side_effect = [playbin, None]
            with self.assertRaisesRegex(Exception, "Unable to create alsasink"):
                self.module._Audioplayer__create_playbin(player_data)

    def test_set_audio_sink_invalid(self):
        self.init()

        with self.assertRaises(InvalidParameter):
            self.module._set_audio_sink("pulse")

    def test_set_fade_invalid_params(self):
        self.init()

        with self.assertRaises(InvalidParameter):
            self.module.set_fade(-1, 0)
        with self.assertRaises(InvalidParameter):
            self.module.set_fade(0, -5)

    def test__process_players_messages_skips_destroyed_players(self):
        self.init()
        player = Mock()
        self.module.players = {
            "the-uuid": {
                "player": player,
                "internal": {"to_destroy": True},
            }
        }
        self.module._Audioplayer__process_gstreamer_message = Mock()

        self.module._Audioplayer__process_players_messages()

        player.get_bus.assert_not_called()
        self.module._Audioplayer__process_gstreamer_message.assert_not_called()

    def test__send_playback_event_unknown_player(self):
        self.init()
        player = Mock()

        self.module._Audioplayer__send_playback_event("unknown", player)

        player.get_state.assert_not_called()

    def test__resource_to_uri_filepath_and_url(self):
        self.init()

        with patch.object(Audioplayer, "_is_filepath", return_value=True):
            uri = self.module._Audioplayer__resource_to_uri("/tmp/track.mp3")
        self.assertTrue(uri.startswith("file://"))
        self.assertIn("track.mp3", uri)

        with patch.object(Audioplayer, "_is_filepath", return_value=False):
            url = "https://example.com/stream.mp3"
            self.assertEqual(self.module._Audioplayer__resource_to_uri(url), url)

    def test__start_fade_zero_duration_calls_on_complete(self):
        self.init()
        on_complete = Mock()

        self.module._Audioplayer__start_fade("missing", 0.0, 1.0, 0, on_complete)

        on_complete.assert_called_once()

    def test__start_fade_sets_fade_state(self):
        self.init()
        playbin = Mock()
        self.module.players = {
            "the-uuid": {
                "player": playbin,
                "internal": {"fade": None},
            }
        }

        with patch("backend.audioplayer.time.monotonic", return_value=10.0):
            self.module._Audioplayer__start_fade("the-uuid", 0.1, 0.8, 500)

        fade = self.module.players["the-uuid"]["internal"]["fade"]
        self.assertEqual(fade["start"], 0.1)
        self.assertEqual(fade["end"], 0.8)
        self.assertEqual(fade["duration_ms"], 500)
        self.assertEqual(fade["started_at"], 10.0)
        playbin.set_property.assert_called_with("volume", 0.1)

    def test__cancel_fade(self):
        self.init()
        self.module.players = {
            "the-uuid": {"internal": {"fade": {"start": 0}}}
        }

        self.module._Audioplayer__cancel_fade("the-uuid")

        self.assertIsNone(self.module.players["the-uuid"]["internal"]["fade"])

    def test__process_fades_applies_volume_and_completes(self):
        self.init()
        playbin = Mock()
        on_complete = Mock()
        self.module.players = {
            "the-uuid": {
                "player": playbin,
                "internal": {
                    "fade": {
                        "start": 0.0,
                        "end": 1.0,
                        "duration_ms": 1000,
                        "started_at": 0.0,
                        "on_complete": on_complete,
                    }
                },
            }
        }

        with patch("backend.audioplayer.time.monotonic", return_value=1.5):
            self.module._Audioplayer__process_fades()

        playbin.set_property.assert_called_with("volume", 1.0)
        self.assertIsNone(self.module.players["the-uuid"]["internal"]["fade"])
        on_complete.assert_called_once()

    def test__process_fades_handles_set_property_exception(self):
        self.init()
        playbin = Mock()
        playbin.set_property.side_effect = Exception("volume fail")
        self.module.players = {
            "the-uuid": {
                "player": playbin,
                "internal": {
                    "fade": {
                        "start": 0.0,
                        "end": 1.0,
                        "duration_ms": 1000,
                        "started_at": 0.0,
                        "on_complete": Mock(),
                    }
                },
            }
        }

        with patch("backend.audioplayer.time.monotonic", return_value=0.2):
            self.module._Audioplayer__process_fades()

        self.assertIsNone(self.module.players["the-uuid"]["internal"]["fade"])

    def test__process_fades_handles_on_complete_exception(self):
        self.init()
        playbin = Mock()
        on_complete = Mock(side_effect=Exception("done fail"))
        self.module.players = {
            "the-uuid": {
                "player": playbin,
                "internal": {
                    "fade": {
                        "start": 0.0,
                        "end": 1.0,
                        "duration_ms": 100,
                        "started_at": 0.0,
                        "on_complete": on_complete,
                    }
                },
            }
        }

        with patch("backend.audioplayer.time.monotonic", return_value=2.0):
            self.module._Audioplayer__process_fades()

        on_complete.assert_called_once()
        self.assertIsNone(self.module.players["the-uuid"]["internal"]["fade"])

    def test__process_fades_skips_when_no_fade(self):
        self.init()
        playbin = Mock()
        self.module.players = {
            "the-uuid": {"player": playbin, "internal": {"fade": None}}
        }

        self.module._Audioplayer__process_fades()

        playbin.set_property.assert_not_called()

    def test__get_position_ns(self):
        self.init()
        self.assertIsNone(self.module._Audioplayer__get_position_ns(None))

        playbin = Mock()
        playbin.query_position.return_value = (True, 42)
        self.assertEqual(self.module._Audioplayer__get_position_ns(playbin), 42)

        playbin.query_position.return_value = (False, 0)
        self.assertIsNone(self.module._Audioplayer__get_position_ns(playbin))

        playbin.query_position.side_effect = Exception("boom")
        self.assertIsNone(self.module._Audioplayer__get_position_ns(playbin))

    def test__seek_ns(self):
        self.init()
        self.assertFalse(self.module._Audioplayer__seek_ns(None, 10))
        self.assertFalse(self.module._Audioplayer__seek_ns(Mock(), None))
        self.assertFalse(self.module._Audioplayer__seek_ns(Mock(), 0))

        playbin = Mock()
        playbin.seek_simple.return_value = True
        self.assertTrue(self.module._Audioplayer__seek_ns(playbin, 123))
        playbin.seek_simple.assert_called()

        playbin.seek_simple.side_effect = Exception("seek fail")
        self.assertFalse(self.module._Audioplayer__seek_ns(playbin, 123))

    def test__try_set_state(self):
        self.init()
        self.assertFalse(self.module._Audioplayer__try_set_state(None, Gst.State.PLAYING))

        playbin = Mock()
        playbin.set_state.side_effect = Exception("fail")
        self.assertFalse(self.module._Audioplayer__try_set_state(playbin, Gst.State.PLAYING))

        playbin = Mock()
        playbin.set_state.return_value = Gst.StateChangeReturn.FAILURE
        self.assertFalse(self.module._Audioplayer__try_set_state(playbin, Gst.State.PLAYING))

        playbin = Mock()
        playbin.set_state.return_value = Gst.StateChangeReturn.ASYNC
        playbin.get_state.side_effect = Exception("wait fail")
        self.assertFalse(self.module._Audioplayer__try_set_state(playbin, Gst.State.PLAYING))

        playbin = Mock()
        playbin.set_state.return_value = Gst.StateChangeReturn.ASYNC
        playbin.get_state.return_value = (
            Gst.StateChangeReturn.FAILURE,
            Gst.State.NULL,
            Gst.State.VOID_PENDING,
        )
        self.assertFalse(self.module._Audioplayer__try_set_state(playbin, Gst.State.PLAYING))

        playbin = Mock()
        playbin.set_state.return_value = Gst.StateChangeReturn.ASYNC
        playbin.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.NULL,
            Gst.State.VOID_PENDING,
        )
        self.assertFalse(self.module._Audioplayer__try_set_state(playbin, Gst.State.PLAYING))

        playbin = Mock()
        playbin.set_state.return_value = Gst.StateChangeReturn.SUCCESS
        playbin.get_state.return_value = (
            Gst.StateChangeReturn.SUCCESS,
            Gst.State.PLAYING,
            Gst.State.VOID_PENDING,
        )
        self.assertTrue(self.module._Audioplayer__try_set_state(playbin, Gst.State.PLAYING))

        playbin = Mock()
        playbin.set_state.return_value = Gst.StateChangeReturn.ASYNC
        playbin.get_state.return_value = (
            Gst.StateChangeReturn.ASYNC,
            Gst.State.PAUSED,
            Gst.State.PLAYING,
        )
        self.assertTrue(self.module._Audioplayer__try_set_state(playbin, Gst.State.PLAYING))

    def _build_player(self, playbin, **internal_overrides):
        track = self.module._make_track("/resource/track1", "audio/mpeg")
        internal = {
            "to_destroy": False,
            "tags_sent": False,
            "last_state": Gst.State.PAUSED,
            "target_volume": 0.5,
            "fade": None,
            "position": 1000,
        }
        internal.update(internal_overrides)
        return {
            "uuid": "the-uuid",
            "playlist": {
                "index": 0,
                "tracks": [track],
                "repeat": False,
                "volume": 50,
                "metadata": {},
                "duration": None,
            },
            "player": playbin,
            "internal": internal,
        }

    def test__play_track_unknown_player(self):
        self.init()
        track = self.module._make_track("https://x/a.mp3", "audio/mpeg")

        with self.assertRaises(CommandError):
            self.module._Audioplayer__play_track(track, "missing")

    @patch.object(Audioplayer, "_is_filepath", return_value=False)
    def test__play_track_creates_playbin_when_missing(self, _is_filepath_mock):
        self.init()
        track = self.module._make_track("https://x/a.mp3", "audio/mpeg")
        player_data = self._build_player(None)
        self.module.players = {"the-uuid": player_data}
        playbin = Mock()
        self.module._Audioplayer__create_playbin = Mock(
            side_effect=lambda p: p.update({"player": playbin})
        )

        self.module._Audioplayer__play_track(track, "the-uuid")

        self.module._Audioplayer__create_playbin.assert_called_once()
        playbin.set_property.assert_any_call("uri", "https://x/a.mp3")
        playbin.set_state.assert_called_with(Gst.State.PLAYING)

    @patch.object(Audioplayer, "_is_filepath", return_value=False)
    def test__play_track_paused_and_fade_in(self, _is_filepath_mock):
        self.init()
        track = self.module._make_track("https://x/a.mp3", "audio/mpeg")
        playbin = Mock()
        player_data = self._build_player(playbin)
        self.module.players = {"the-uuid": player_data}

        self.module._Audioplayer__play_track(track, "the-uuid", paused=True)
        playbin.set_state.assert_called_with(Gst.State.PAUSED)
        self.assertEqual(player_data["internal"]["last_state"], Gst.State.PAUSED)

        self.module._set_config_field("fade_in_ms", 300)
        self.module._Audioplayer__start_fade = Mock()
        self.module._Audioplayer__play_track(track, "the-uuid", paused=False)
        playbin.set_property.assert_any_call("volume", 0.0)
        self.module._Audioplayer__start_fade.assert_called()
        self.assertEqual(player_data["internal"]["last_state"], Gst.State.PLAYING)

    def test__recreate_playback_success(self):
        self.init()
        old_playbin = Mock()
        new_playbin = Mock()
        player_data = self._build_player(old_playbin, position=555)
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__create_playbin = Mock(
            side_effect=lambda p: p.update({"player": new_playbin})
        )
        self.module._Audioplayer__play_track = Mock()
        self.module._Audioplayer__seek_ns = Mock(return_value=True)
        self.module._Audioplayer__try_set_state = Mock(return_value=True)

        result = self.module._Audioplayer__recreate_playback("the-uuid", playing=True)

        old_playbin.set_state.assert_called_with(Gst.State.NULL)
        self.module._Audioplayer__play_track.assert_called()
        self.module._Audioplayer__seek_ns.assert_called_with(new_playbin, 555)
        self.module._Audioplayer__try_set_state.assert_called_with(
            new_playbin, Gst.State.PLAYING
        )
        self.assertEqual(result, self.module._get_player_state(Gst.State.PLAYING))

    def test__recreate_playback_paused_and_with_fade(self):
        self.init()
        playbin = Mock()
        player_data = self._build_player(playbin, position=10)
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__create_playbin = Mock(
            side_effect=lambda p: p.update({"player": playbin})
        )
        self.module._Audioplayer__play_track = Mock()
        self.module._Audioplayer__seek_ns = Mock()
        self.module._Audioplayer__try_set_state = Mock(return_value=True)
        self.module._Audioplayer__start_fade = Mock()

        result = self.module._Audioplayer__recreate_playback("the-uuid", playing=False)
        self.assertEqual(result, self.module._get_player_state(Gst.State.PAUSED))

        self.module._set_config_field("fade_in_ms", 200)
        result = self.module._Audioplayer__recreate_playback("the-uuid", playing=True)
        self.module._Audioplayer__start_fade.assert_called()
        self.assertEqual(result, self.module._get_player_state(Gst.State.PLAYING))

    def test__recreate_playback_errors(self):
        self.init()

        with self.assertRaises(CommandError):
            self.module._Audioplayer__recreate_playback("missing")

        playbin = Mock()
        player_data = self._build_player(playbin)
        player_data["playlist"]["index"] = None
        self.module.players = {"the-uuid": player_data}
        with self.assertRaises(CommandError):
            self.module._Audioplayer__recreate_playback("the-uuid")

        player_data = self._build_player(playbin)
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__create_playbin = Mock(
            side_effect=lambda p: p.update({"player": playbin})
        )
        self.module._Audioplayer__play_track = Mock()
        self.module._Audioplayer__seek_ns = Mock()
        self.module._Audioplayer__try_set_state = Mock(return_value=False)
        with self.assertRaises(CommandError):
            self.module._Audioplayer__recreate_playback("the-uuid", playing=True)

        self.module._set_config_field("fade_in_ms", 100)
        with self.assertRaises(CommandError):
            self.module._Audioplayer__recreate_playback("the-uuid", playing=True)

    def test__recreate_playback_handles_old_playbin_stop_exception(self):
        self.init()
        old_playbin = Mock()
        old_playbin.set_state.side_effect = Exception("stop fail")
        new_playbin = Mock()
        player_data = self._build_player(old_playbin, position=None)
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__get_position_ns = Mock(return_value=None)
        self.module._Audioplayer__create_playbin = Mock(
            side_effect=lambda p: p.update({"player": new_playbin})
        )
        self.module._Audioplayer__play_track = Mock()
        self.module._Audioplayer__try_set_state = Mock(return_value=True)

        result = self.module._Audioplayer__recreate_playback("the-uuid", playing=True)

        self.assertEqual(result, self.module._get_player_state(Gst.State.PLAYING))

    def test__resume_playback_without_playbin(self):
        self.init()
        player_data = self._build_player(None)
        self.module.players = {"the-uuid": player_data}
        self.module._Audioplayer__recreate_playback = Mock(return_value="playing")

        result = self.module._Audioplayer__resume_playback("the-uuid")

        self.module._Audioplayer__recreate_playback.assert_called_with(
            "the-uuid", playing=True
        )
        self.assertEqual(result, "playing")

    def test__resume_playback_with_fade_in(self):
        self.init()
        playbin = Mock()
        playbin.query_position.return_value = (True, 77)
        player_data = self._build_player(playbin)
        self.module.players = {"the-uuid": player_data}
        self.module._set_config_field("fade_in_ms", 250)
        self.module._Audioplayer__try_set_state = Mock(return_value=True)
        self.module._Audioplayer__start_fade = Mock()

        result = self.module._Audioplayer__resume_playback("the-uuid")

        playbin.set_property.assert_called_with("volume", 0.0)
        self.module._Audioplayer__start_fade.assert_called()
        self.assertEqual(result, self.module._get_player_state(Gst.State.PLAYING))
        self.assertEqual(player_data["internal"]["position"], 77)

    def test__resume_playback_fade_in_set_volume_fails_recreates(self):
        self.init()
        playbin = Mock()
        playbin.set_property.side_effect = Exception("volume fail")
        player_data = self._build_player(playbin)
        self.module.players = {"the-uuid": player_data}
        self.module._set_config_field("fade_in_ms", 250)
        self.module._Audioplayer__recreate_playback = Mock(return_value="playing")

        result = self.module._Audioplayer__resume_playback("the-uuid")

        self.module._Audioplayer__recreate_playback.assert_called_with(
            "the-uuid", playing=True
        )
        self.assertEqual(result, "playing")

    def test__resume_playback_fade_in_set_state_fails_recreates(self):
        self.init()
        playbin = Mock()
        player_data = self._build_player(playbin)
        self.module.players = {"the-uuid": player_data}
        self.module._set_config_field("fade_in_ms", 250)
        self.module._Audioplayer__try_set_state = Mock(return_value=False)
        self.module._Audioplayer__recreate_playback = Mock(return_value="playing")

        result = self.module._Audioplayer__resume_playback("the-uuid")

        self.module._Audioplayer__recreate_playback.assert_called_with(
            "the-uuid", playing=True
        )
        self.assertEqual(result, "playing")

    def test_pause_playback_without_playbin(self):
        self.init()
        player_data = self._build_player(None, last_state=Gst.State.PLAYING)
        self.module.players = {"the-uuid": player_data}

        result = self.module.pause_playback("the-uuid")

        self.assertEqual(result, self.module._get_player_state(Gst.State.PAUSED))
        self.assertEqual(player_data["internal"]["last_state"], Gst.State.PAUSED)

    def test_pause_playback_with_fade_out(self):
        self.init()
        playbin = Mock()
        playbin.get_state.return_value = ("dummy", Gst.State.PLAYING, "dummy")
        playbin.get_property.return_value = 0.7
        playbin.query_position.return_value = (True, 9)
        player_data = self._build_player(playbin, last_state=Gst.State.PLAYING)
        self.module.players = {"the-uuid": player_data}
        self.module._set_config_field("fade_out_ms", 100)
        self.module._Audioplayer__start_fade = Mock()

        result = self.module.pause_playback("the-uuid", force_pause=True)

        self.assertEqual(result, self.module._get_player_state(Gst.State.PAUSED))
        self.module._Audioplayer__start_fade.assert_called()
        args = self.module._Audioplayer__start_fade.call_args
        self.assertEqual(args[0][0], "the-uuid")
        self.assertEqual(args[0][1], 0.7)
        self.assertEqual(args[0][2], 0.0)
        on_complete = args[1]["on_complete"] if "on_complete" in args[1] else args[0][4]

        # Execute fade completion callback
        self.module._Audioplayer__try_set_state = Mock(return_value=True)
        on_complete()
        self.module._Audioplayer__try_set_state.assert_called_with(
            playbin, Gst.State.PAUSED
        )
        playbin.set_property.assert_called_with("volume", 0.5)
        self.assertEqual(player_data["internal"]["last_state"], Gst.State.PAUSED)

        # Callback safety when player already gone / playbin gone
        del self.module.players["the-uuid"]
        on_complete()
        self.module.players = {"the-uuid": self._build_player(None)}
        on_complete()

    def test_stop_playback_with_fade_out(self):
        self.init()
        playbin = Mock()
        playbin.get_property.return_value = 0.4
        player_data = self._build_player(playbin)
        self.module.players = {"the-uuid": player_data}
        self.module._set_config_field("fade_out_ms", 150)
        self.module._Audioplayer__start_fade = Mock()
        self.module._destroy_player = Mock()
        self.module.event_playback_update = Mock()

        self.module.stop_playback("the-uuid")

        self.module._Audioplayer__start_fade.assert_called()
        on_complete = self.module._Audioplayer__start_fade.call_args[1].get(
            "on_complete"
        ) or self.module._Audioplayer__start_fade.call_args[0][4]

        on_complete()
        playbin.set_state.assert_called_with(Gst.State.NULL)
        self.module._destroy_player.assert_called()
        self.module.event_playback_update.send.assert_called()

        # do_stop no-op if player already removed
        self.module.players = {}
        on_complete()


class TestAudioplayerPlaybackUpdateEvent(unittest.TestCase):
    def setUp(self):
        logging.basicConfig(
            level=LOG_LEVEL,
            format="%(asctime)s %(name)s:%(lineno)d %(levelname)s : %(message)s",
        )
        self.session = session.TestSession(self)
        self.event = self.session.setup_event(AudioplayerPlaybackUpdateEvent)

    def test_event_params(self):
        self.assertEqual(
            self.event.EVENT_PARAMS,
            [
                "playeruuid",
                "state",
                "duration",
                "track",
                "metadata",
                "index",
            ],
        )


if __name__ == "__main__":
    # coverage run --omit="*/lib/python*/*","test_*" --concurrency=thread test_audioplayer.py; coverage report -m -i
    unittest.main()
