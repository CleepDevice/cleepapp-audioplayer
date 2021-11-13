#!/usr/bin/env python
# -*- coding: utf-8 -*-
import unittest
import logging
import sys
sys.path.append('../')
from backend.audioplayer import Audioplayer
from cleep.exception import InvalidParameter, MissingParameter, CommandError, Unauthorized
from cleep.libs.tests import session
from mock import Mock, patch

class TestAudioplayer(unittest.TestCase):

    def setUp(self):
        logging.basicConfig(level=logging.DEBUG, format=u'%(asctime)s %(name)s:%(lineno)d %(levelname)s : %(message)s')
        self.session = session.TestSession(logging.DEBUG)

    def tearDown(self):
        self.session.clean()

    def init(self, start=True):
        self.module = self.session.setup(Audioplayer)
        if start:
            self.session.start_module(self.module)

    def test_configure(self):
        self.init(False)

        with patch('backend.audioplayer.Gst') as gstMock:
            self.session.start_module(self.module)
            gstMock.init.assert_called_with(None)

    def test_on_stop(self):
        self.init()
        player = {
            'uuid': 'the-uuid',
            'player': 'player-stuff',
        }
        self.module.players = {'the-uuid': player}
        self.module._Audioplayer__destroy_player = Mock()

        self.module._on_stop()

        self.module._Audioplayer__destroy_player.assert_called_with(player)
        self.assertTrue(len(self.module.players.keys()), 0)

    def test__prepare_player(self):
        self.init()
        player = {
            'uuid': 'the-uuid',
            'player': 'player-stuff',
        }
        self.module.players = {'the-uuid': player}
        self.module._Audioplayer__reset_player = Mock()
        self.module._Audioplayer__build_pipeline = Mock()

        result = self.module._Audioplayer__prepare_player('the-uuid', 'source', 'audio-format')

        self.assertEqual(result, player)
        self.module._Audioplayer__reset_player.assert_called_with(player)
        self.module._Audioplayer__build_pipeline.assert_called_with('source', 'audio-format', player)

    def test__prepare_player_no_player(self):
        self.init()

        with self.assertRaises(Exception) as cm:
            self.module._Audioplayer__prepare_player('the-uuid', 'source', 'audio-format')
        self.assertEqual(str(cm.exception), 'Player "the-uuid" does not exist')

    def test__create_player(self):
        self.init()
        self.module._get_unique_id = Mock(return_value='the-uuid')
        player = {
            "uuid": 'the-uuid',
            "playlist": {
                "current_index": None,
                "tracks": [], 
                "repeat": False,
                "volume": 0,
            },  
            "player": None,
            "source": None,
            "volume": None,
            "pipeline": [], 
            "internal": {
                "todestroy": False,
                "tags_sent": False,
            # NOT TESTED
            #    "last_state": Gst.State.NULL,
            },  
        }

        result = self.module._Audioplayer__create_player()

        del result['internal']['last_state']
        self.assertEqual(result, player)

    def test__reset_player(self):
        self.init()
        player = Mock()
        pipeline_elt1 = Mock()
        pipeline_elt2 = Mock()
        pipeline_elt3 = Mock()
        player_data = {
            'uuid': 'the-uuid',
            'playlist': {
                'current_index': 1,
                'tracks': ['track1', 'track2', 'track3'],
                'repeat': True,
                'volume': 55,
            },
            'player': player,
            'source': 'source',
            'volume': 'volume',
            'pipeline': [
                pipeline_elt1,
                pipeline_elt2,
                pipeline_elt3,
            ],
            'internal': {
                'to_destroy': False,
                'tags_sent': True,
                'last_state': 1,
            },
        }
        self.module.players = {'the-uuid': player_data}
        
        self.module._Audioplayer__reset_player(player_data)

        player.set_state.assert_called()
        pipeline_elt1.unlink.assert_called()
        pipeline_elt2.unlink.assert_called()
        self.assertFalse(pipeline_elt3.unlink.called)
        player.remove.assert_any_call(pipeline_elt1)
        player.remove.assert_any_call(pipeline_elt2)
        player.remove.assert_any_call(pipeline_elt3)
        self.assertIsNone(player_data['player'])
        self.assertIsNone(player_data['source'])
        self.assertIsNone(player_data['volume'])
        self.assertEqual(len(player_data['pipeline']), 0)
        self.assertEqual(player_data['playlist']['current_index'], 1)
        self.assertEqual(len(player_data['playlist']['tracks']), 3)
        self.assertEqual(player_data['playlist']['volume'], 55)
        self.assertEqual(player_data['internal']['to_destroy'], False)
        self.assertEqual(player_data['internal']['tags_sent'], False)

    def test_destroy_player(self):
        self.init()
        player_data = {
            'uuid': 'the-uuid',
            'playlist': {
                'current_index': 1,
                'tracks': ['track1', 'track2', 'track3'],
                'repeat': True,
                'volume': 55,
            },
            'player': Mock(),
            'source': 'source',
            'volume': 'volume',
            'pipeline': [Mock()],
            'internal': {
                'to_destroy': False,
                'tags_sent': True,
                'last_state': 1,
            },
        }
        self.module.players = {'the-uuid': player_data}

        self.module._destroy_player(player_data)

        self.assertTrue(player_data['internal']['to_destroy'])

    def test__destroy_player(self):
        self.init()
        player_data = {
            'uuid': 'the-uuid',
            'playlist': {
                'current_index': 1,
                'tracks': ['track1', 'track2', 'track3'],
                'repeat': True,
                'volume': 55,
            },
            'player': Mock(),
            'source': 'source',
            'volume': 'volume',
            'pipeline': [Mock()],
            'internal': {
                'to_destroy': False,
                'tags_sent': True,
                'last_state': 1,
            },
        }
        self.module.players = {'the-uuid': player_data}
        self.module._Audioplayer__reset_player = Mock()

        self.module._Audioplayer__destroy_player(player_data)

        self.module._Audioplayer__reset_player.assert_called_with(player_data)
        self.assertEqual(len(self.module.players), 0)


if __name__ == '__main__':
    # coverage run --omit="*/lib/python*/*","test_*" --concurrency=thread test_audioplayer.py; coverage report -m -i
    unittest.main()
    
