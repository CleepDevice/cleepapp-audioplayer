#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Unit tests for CrossfadeEngine (GStreamer audiomixer dual-channel)."""
import logging
import sys
import unittest
from unittest.mock import Mock, patch, call

sys.path.append("../")

from backend.crossfade import CrossfadeEngine, Gst
from cleep.libs.tests.common import get_log_level

LOG_LEVEL = get_log_level()


def _make_elements(names_cycle=None):
    """
    Build a side_effect for ElementFactory.make that returns distinct mocks
    with get_name / get_static_pad / get_request_pad helpers.
    """
    created = []

    def factory(element_type, name=None):
        el = Mock(name=name or element_type)
        el.get_name.return_value = name or element_type
        sink_pad = Mock(name=f"{name}-sink")
        sink_pad.is_linked.return_value = False
        src_pad = Mock(name=f"{name}-src")
        src_pad.link.return_value = Gst.PadLinkReturn.OK
        el.get_static_pad.side_effect = lambda pad_name: (
            sink_pad if pad_name == "sink" else src_pad
        )
        mixer_pad = Mock(name=f"{name}-mixer-pad")
        el.get_request_pad.return_value = mixer_pad
        el.get_property.return_value = 1.0
        created.append(el)
        return el

    return factory, created


class TestCrossfadeEngine(unittest.TestCase):
    def setUp(self):
        logging.basicConfig(
            level=LOG_LEVEL,
            format="%(asctime)s %(name)s:%(lineno)d %(levelname)s : %(message)s",
        )

    def _build_engine(self, **kwargs):
        pipeline = Mock(name="pipeline")
        pipeline.get_state.return_value = (None, Gst.State.PLAYING, None)
        bus = Mock()
        bus.pop.return_value = None
        pipeline.get_bus.return_value = bus

        factory, created = _make_elements()

        with patch("backend.crossfade.Gst.Pipeline.new", return_value=pipeline), patch(
            "backend.crossfade.Gst.ElementFactory.make", side_effect=factory
        ):
            engine = CrossfadeEngine(logger=logging.getLogger("test"), **kwargs)

        return engine, pipeline, created

    def test_build_pipeline_links_mixer_to_sink(self):
        engine, pipeline, _ = self._build_engine()
        self.assertIsNotNone(engine.pipeline)
        self.assertIsNotNone(engine.mixer)
        self.assertIsNotNone(engine.slots["a"])
        self.assertIsNotNone(engine.slots["b"])
        self.assertEqual(pipeline.add.call_count, 4 + 5 * 2)  # core + 2 slots

    def test_build_pipeline_alsa_sink(self):
        factory, _ = _make_elements()
        pipeline = Mock()
        with patch("backend.crossfade.Gst.Pipeline.new", return_value=pipeline), patch(
            "backend.crossfade.Gst.ElementFactory.make", side_effect=factory
        ):
            engine = CrossfadeEngine(audio_sink="alsa", alsa_device="hw:1,0")

        engine.sink.set_property.assert_any_call("device", "hw:1,0")

    def test_play_prepares_active_slot(self):
        engine, pipeline, _ = self._build_engine()
        decode_a = engine.slots["a"]["decode"]

        engine.play("file:///music/a.mp3", volume=0.8)

        decode_a.set_state.assert_any_call(Gst.State.NULL)
        decode_a.set_property.assert_any_call("uri", "file:///music/a.mp3")
        pipeline.set_state.assert_called_with(Gst.State.PLAYING)
        self.assertEqual(engine.target_volume, 0.8)
        self.assertEqual(engine.active_slot, "a")

    def test_crossfade_to_starts_fade_on_idle_slot(self):
        engine, pipeline, _ = self._build_engine()
        engine.play("file:///a.mp3", volume=1.0)

        engine.crossfade_to("file:///b.mp3", duration_ms=2000, volume=0.9)

        self.assertTrue(engine.is_crossfading)
        self.assertEqual(engine._crossfade["outgoing"], "a")
        self.assertEqual(engine._crossfade["incoming"], "b")
        self.assertEqual(engine.slots["b"]["uri"], "file:///b.mp3")
        pipeline.set_state.assert_called_with(Gst.State.PLAYING)

    def test_crossfade_to_zero_duration_falls_back_to_play(self):
        engine, _, _ = self._build_engine()
        engine.play("file:///a.mp3")
        engine.play = Mock()

        engine.crossfade_to("file:///b.mp3", duration_ms=0)

        engine.play.assert_called_with("file:///b.mp3", engine.target_volume)

    def test_process_completes_crossfade(self):
        engine, _, _ = self._build_engine()
        done = Mock()
        engine.on_crossfade_done = done
        engine.play("file:///a.mp3", volume=1.0)
        engine.crossfade_to("file:///b.mp3", duration_ms=100)

        # Force fade to be expired
        engine._crossfade["started_at"] -= 1.0
        engine.process()

        self.assertFalse(engine.is_crossfading)
        self.assertEqual(engine.active_slot, "b")
        engine.slots["a"]["decode"].set_state.assert_called_with(Gst.State.NULL)
        done.assert_called_once()

    def test_should_crossfade(self):
        engine, _, _ = self._build_engine()
        engine.play("file:///a.mp3")
        engine.remaining_ms = Mock(return_value=2500.0)

        self.assertTrue(engine.should_crossfade(3000))
        self.assertFalse(engine.should_crossfade(2000))
        self.assertFalse(engine.should_crossfade(0))

        engine._crossfade = {"outgoing": "a", "incoming": "b"}
        self.assertFalse(engine.should_crossfade(3000))

    def test_remaining_ms(self):
        engine, _, _ = self._build_engine()
        engine.play("file:///a.mp3")
        decode = engine.slots["a"]["decode"]
        decode.query_duration.return_value = (True, 10 * Gst.SECOND)
        decode.query_position.return_value = (True, 7 * Gst.SECOND)

        remaining = engine.remaining_ms()

        self.assertAlmostEqual(remaining, 3000.0, places=0)

    def test_remaining_ms_unknown(self):
        engine, _, _ = self._build_engine()
        engine.play("file:///a.mp3")
        decode = engine.slots["a"]["decode"]
        decode.query_duration.return_value = (False, 0)

        self.assertIsNone(engine.remaining_ms())

    def test_pause_resume_stop(self):
        engine, pipeline, _ = self._build_engine()
        engine.play("file:///a.mp3")

        engine.pause()
        pipeline.set_state.assert_called_with(Gst.State.PAUSED)

        engine.resume()
        pipeline.set_state.assert_called_with(Gst.State.PLAYING)

        engine.stop()
        self.assertFalse(engine._started)
        self.assertIsNone(engine._crossfade)

    def test_set_volume_applies_when_idle(self):
        engine, _, _ = self._build_engine()
        engine.play("file:///a.mp3", volume=0.5)
        vol_el = engine.slots["a"]["volume"]
        vol_el.reset_mock()

        engine.set_volume(0.7)

        vol_el.set_property.assert_called_with("volume", 0.7)

    def test_on_pad_added_links_audio_only(self):
        engine, _, _ = self._build_engine()
        convert = engine.slots["a"]["convert"]
        sink_pad = convert.get_static_pad("sink")
        sink_pad.is_linked.return_value = False

        pad = Mock()
        caps = Mock()
        caps.is_empty.return_value = False
        structure = Mock()
        structure.get_name.return_value = "audio/x-raw"
        caps.get_structure.return_value = structure
        pad.get_current_caps.return_value = caps
        pad.link.return_value = Gst.PadLinkReturn.OK

        engine._on_pad_added(engine.slots["a"]["decode"], pad, convert)

        pad.link.assert_called_with(sink_pad)
        self.assertTrue(engine.slots["a"]["linked"])

    def test_on_pad_added_ignores_video(self):
        engine, _, _ = self._build_engine()
        convert = engine.slots["a"]["convert"]
        pad = Mock()
        caps = Mock()
        caps.is_empty.return_value = False
        structure = Mock()
        structure.get_name.return_value = "video/x-raw"
        caps.get_structure.return_value = structure
        pad.get_current_caps.return_value = caps

        engine._on_pad_added(engine.slots["a"]["decode"], pad, convert)

        pad.link.assert_not_called()

    def test_poll_messages_eos_calls_on_eos(self):
        on_eos = Mock()
        engine, pipeline, _ = self._build_engine(on_eos=on_eos)
        engine.play("file:///a.mp3")

        msg = Mock()
        msg.type = Gst.MessageType.EOS
        msg.src = engine.slots["a"]["decode"]
        bus = pipeline.get_bus.return_value
        bus.pop.side_effect = [msg, None]

        list(engine.poll_messages())

        on_eos.assert_called_once()

    def test_poll_messages_eos_during_crossfade_ignored_for_outgoing(self):
        on_eos = Mock()
        engine, pipeline, _ = self._build_engine(on_eos=on_eos)
        engine.play("file:///a.mp3")
        engine.crossfade_to("file:///b.mp3", duration_ms=1000)

        msg = Mock()
        msg.type = Gst.MessageType.EOS
        msg.src = engine.slots["a"]["decode"]
        bus = pipeline.get_bus.return_value
        bus.pop.side_effect = [msg, None]

        list(engine.poll_messages())

        on_eos.assert_not_called()
        self.assertTrue(engine.is_crossfading)

    def test_destroy(self):
        engine, pipeline, _ = self._build_engine()
        engine.play("file:///a.mp3")

        engine.destroy()

        self.assertIsNone(engine.pipeline)
        pipeline.set_state.assert_called_with(Gst.State.NULL)


if __name__ == "__main__":
    unittest.main()
