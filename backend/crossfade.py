# -*- coding: utf-8 -*-
"""
Crossfade engine for audioplayer.

GStreamer does not ship a ready-made playlist crossfade element. The standard
approach (Rhythmbox, radio engines, GStreamer discourse) is:

    uridecodebin → convert → resample → volume → queue ─┐
                                                        ├─ audiomixer → sink
    uridecodebin → convert → resample → volume → queue ─┘

This module owns that dual-channel pipeline and animates the two ``volume``
elements so outgoing track fades down while incoming fades up.

Not wired into Audioplayer yet: call ``CrossfadeEngine`` from the player when
``crossfade_ms > 0`` (see README).
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import gi

# pylint: disable=C0413
gi.require_version("Gst", "1.0")
from gi.repository import Gst


class CrossfadeEngine:
    """
    Dual-channel audio mixer with overlapping volume fades.

    Lifecycle:
        engine = CrossfadeEngine(audio_sink="auto", logger=logger)
        engine.play(uri, volume=1.0)
        # later, before end of track (see remaining_ms):
        engine.crossfade_to(next_uri, duration_ms=3000, volume=1.0)
        # from module loop:
        engine.process()
        for msg in engine.poll_messages():
            ...
        engine.stop()
    """

    SLOT_A = "a"
    SLOT_B = "b"

    def __init__(
        self,
        audio_sink: str = "auto",
        alsa_device: str = "default",
        logger=None,
        on_eos: Optional[Callable[[], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_crossfade_done: Optional[Callable[[], None]] = None,
    ):
        """
        Args:
            audio_sink (str): ``auto`` or ``alsa``
            alsa_device (str): ALSA device name when audio_sink is alsa
            logger: optional logger (must support debug/info/warning/error/exception)
            on_eos: called when the active slot reaches EOS and no crossfade is running
            on_error: called with error message string
            on_crossfade_done: called when a crossfade animation completes
        """
        self.logger = logger
        self.on_eos = on_eos
        self.on_error = on_error
        self.on_crossfade_done = on_crossfade_done

        self._audio_sink_name = audio_sink
        self._alsa_device = alsa_device

        self.pipeline: Optional[Gst.Pipeline] = None
        self.mixer: Optional[Gst.Element] = None
        self.sink: Optional[Gst.Element] = None
        self.slots = {
            self.SLOT_A: None,
            self.SLOT_B: None,
        }

        self.active_slot = self.SLOT_A
        self.target_volume = 1.0
        self._crossfade = None  # fade state dict or None
        self._started = False

        self._build_pipeline()

    def _log(self, level: str, msg: str, *args):
        if not self.logger:
            return
        getattr(self.logger, level)(msg, *args)

    def _build_pipeline(self):
        """Create mixer + sink skeleton; slots are filled on demand."""
        self.pipeline = Gst.Pipeline.new("crossfade-pipeline")
        if not self.pipeline:
            raise RuntimeError("Unable to create GStreamer pipeline")

        self.mixer = Gst.ElementFactory.make("audiomixer", "mix")
        if not self.mixer:
            raise RuntimeError(
                "Unable to create audiomixer (install gstreamer1.0-plugins-base)"
            )

        post_convert = Gst.ElementFactory.make("audioconvert", "post-convert")
        post_resample = Gst.ElementFactory.make("audioresample", "post-resample")
        if not post_convert or not post_resample:
            raise RuntimeError("Unable to create audioconvert/audioresample")

        if self._audio_sink_name == "alsa":
            self.sink = Gst.ElementFactory.make("alsasink", "audio-sink")
            if not self.sink:
                raise RuntimeError("Unable to create alsasink")
            self.sink.set_property("device", self._alsa_device)
        else:
            self.sink = Gst.ElementFactory.make("autoaudiosink", "audio-sink")
            if not self.sink:
                raise RuntimeError("Unable to create autoaudiosink")

        self.pipeline.add(self.mixer)
        self.pipeline.add(post_convert)
        self.pipeline.add(post_resample)
        self.pipeline.add(self.sink)

        if not self.mixer.link(post_convert):
            raise RuntimeError("Unable to link audiomixer → audioconvert")
        if not post_convert.link(post_resample):
            raise RuntimeError("Unable to link audioconvert → audioresample")
        if not post_resample.link(self.sink):
            raise RuntimeError("Unable to link audioresample → sink")

        for slot_name in (self.SLOT_A, self.SLOT_B):
            self.slots[slot_name] = self._create_slot(slot_name)

    def _create_slot(self, name: str) -> dict:
        """
        Create one decode → volume → mixer branch.

        Returns:
            dict: slot elements and state
        """
        decode = Gst.ElementFactory.make("uridecodebin", f"decode-{name}")
        convert = Gst.ElementFactory.make("audioconvert", f"convert-{name}")
        resample = Gst.ElementFactory.make("audioresample", f"resample-{name}")
        volume = Gst.ElementFactory.make("volume", f"volume-{name}")
        queue = Gst.ElementFactory.make("queue", f"queue-{name}")

        for element, label in (
            (decode, "uridecodebin"),
            (convert, "audioconvert"),
            (resample, "audioresample"),
            (volume, "volume"),
            (queue, "queue"),
        ):
            if not element:
                raise RuntimeError(f"Unable to create {label} for slot {name}")

        volume.set_property("volume", 0.0)
        # Keep some preroll buffer for smoother mix
        queue.set_property("max-size-time", 2 * Gst.SECOND)
        queue.set_property("max-size-buffers", 0)
        queue.set_property("max-size-bytes", 0)

        for element in (decode, convert, resample, volume, queue):
            self.pipeline.add(element)

        convert.link(resample)
        resample.link(volume)
        volume.link(queue)

        mixer_pad = self.mixer.get_request_pad("sink_%u")
        if not mixer_pad:
            raise RuntimeError(f"Unable to request audiomixer pad for slot {name}")
        queue_src = queue.get_static_pad("src")
        if queue_src.link(mixer_pad) != Gst.PadLinkReturn.OK:
            raise RuntimeError(f"Unable to link slot {name} to audiomixer")

        decode.connect("pad-added", self._on_pad_added, convert)

        return {
            "name": name,
            "decode": decode,
            "convert": convert,
            "resample": resample,
            "volume": volume,
            "queue": queue,
            "mixer_pad": mixer_pad,
            "uri": None,
            "linked": False,
        }

    def _on_pad_added(self, decodebin, pad, convert):
        """Link decoded audio pads only to the slot convert element."""
        caps = pad.get_current_caps() or pad.query_caps(None)
        if not caps or caps.is_empty():
            return
        structure = caps.get_structure(0)
        if not structure or not structure.get_name().startswith("audio/"):
            self._log("debug", "Ignoring non-audio pad from %s", decodebin.get_name())
            return

        sink_pad = convert.get_static_pad("sink")
        if sink_pad.is_linked():
            return
        result = pad.link(sink_pad)
        if result != Gst.PadLinkReturn.OK:
            self._log(
                "error",
                "Failed to link decode pad to convert (%s): %s",
                decodebin.get_name(),
                result,
            )
        else:
            slot = self._slot_for_decode(decodebin)
            if slot:
                slot["linked"] = True

    def _slot_for_decode(self, decodebin) -> Optional[dict]:
        for slot in self.slots.values():
            if slot and slot["decode"] is decodebin:
                return slot
        return None

    def _idle_slot(self) -> str:
        return self.SLOT_B if self.active_slot == self.SLOT_A else self.SLOT_A

    def _set_slot_volume(self, slot_name: str, value: float):
        slot = self.slots[slot_name]
        if slot and slot["volume"]:
            slot["volume"].set_property("volume", max(0.0, float(value)))

    def _prepare_slot(self, slot_name: str, uri: str, start_volume: float):
        """Load URI into slot and set initial volume (pipeline may stay PAUSED/PLAYING)."""
        slot = self.slots[slot_name]
        decode = slot["decode"]

        decode.set_state(Gst.State.NULL)
        # Drop previous link state; pad-added will re-link
        slot["linked"] = False
        slot["uri"] = uri
        decode.set_property("uri", uri)
        self._set_slot_volume(slot_name, start_volume)

        # Sync with parent pipeline state
        decode.sync_state_with_parent()

    def play(self, uri: str, volume: float = 1.0):
        """
        Start (or replace) playback on the active slot without crossfade.

        Args:
            uri (str): file:// or http(s) URI
            volume (float): linear volume 0.0–1.0+
        """
        self._crossfade = None
        self.target_volume = float(volume)

        other = self._idle_slot()
        self._set_slot_volume(other, 0.0)
        other_slot = self.slots[other]
        if other_slot["uri"]:
            other_slot["decode"].set_state(Gst.State.NULL)
            other_slot["uri"] = None

        self._prepare_slot(self.active_slot, uri, self.target_volume)
        self.pipeline.set_state(Gst.State.PLAYING)
        self._started = True
        self._log("info", "CrossfadeEngine playing on slot %s: %s", self.active_slot, uri)

    def crossfade_to(self, uri: str, duration_ms: int, volume: Optional[float] = None):
        """
        Start next URI on idle slot and overlap volumes for ``duration_ms``.

        Args:
            uri (str): next track URI
            duration_ms (int): overlap duration in milliseconds
            volume (float, optional): target volume for incoming track.
                Defaults to current target_volume.
        """
        if volume is not None:
            self.target_volume = float(volume)

        if duration_ms <= 0:
            self.play(uri, self.target_volume)
            return

        incoming = self._idle_slot()
        outgoing = self.active_slot

        self._prepare_slot(incoming, uri, 0.0)
        self.pipeline.set_state(Gst.State.PLAYING)
        self._started = True

        self._crossfade = {
            "outgoing": outgoing,
            "incoming": incoming,
            "start_out": self.slots[outgoing]["volume"].get_property("volume"),
            "end_out": 0.0,
            "start_in": 0.0,
            "end_in": self.target_volume,
            "duration_ms": max(int(duration_ms), 1),
            "started_at": time.monotonic(),
        }
        self._log(
            "info",
            "Crossfade %s → %s (%sms) uri=%s",
            outgoing,
            incoming,
            duration_ms,
            uri,
        )

    def process(self):
        """
        Advance active crossfade. Call from the module process loop.
        """
        fade = self._crossfade
        if not fade:
            return

        now = time.monotonic()
        progress = min(1.0, ((now - fade["started_at"]) * 1000.0) / fade["duration_ms"])
        out_vol = fade["start_out"] + (fade["end_out"] - fade["start_out"]) * progress
        in_vol = fade["start_in"] + (fade["end_in"] - fade["start_in"]) * progress
        self._set_slot_volume(fade["outgoing"], out_vol)
        self._set_slot_volume(fade["incoming"], in_vol)

        if progress >= 1.0:
            self._finish_crossfade()

    def _finish_crossfade(self):
        fade = self._crossfade
        if not fade:
            return

        outgoing = fade["outgoing"]
        incoming = fade["incoming"]
        self._set_slot_volume(outgoing, 0.0)
        self._set_slot_volume(incoming, self.target_volume)

        out_slot = self.slots[outgoing]
        out_slot["decode"].set_state(Gst.State.NULL)
        out_slot["uri"] = None
        out_slot["linked"] = False

        self.active_slot = incoming
        self._crossfade = None
        self._log("debug", "Crossfade done, active slot=%s", self.active_slot)

        if self.on_crossfade_done:
            try:
                self.on_crossfade_done()
            except Exception:
                self._log("exception", "on_crossfade_done failed")

    @property
    def is_crossfading(self) -> bool:
        return self._crossfade is not None

    def remaining_ms(self) -> Optional[float]:
        """
        Milliseconds left on the active (outgoing if crossfading) track.

        Returns:
            float | None: remaining time, or None if unknown
        """
        slot_name = (
            self._crossfade["outgoing"] if self._crossfade else self.active_slot
        )
        slot = self.slots[slot_name]
        decode = slot["decode"]
        try:
            ok_d, duration = decode.query_duration(Gst.Format.TIME)
            ok_p, position = decode.query_position(Gst.Format.TIME)
        except Exception:
            return None
        if not ok_d or not ok_p or duration <= 0 or position < 0:
            return None
        remaining_ns = duration - position
        if remaining_ns < 0:
            return 0.0
        return remaining_ns / Gst.MSECOND

    def should_crossfade(self, crossfade_ms: int) -> bool:
        """
        True when active track is close enough to the end to start a crossfade.

        Args:
            crossfade_ms (int): configured crossfade duration
        """
        if crossfade_ms <= 0 or self.is_crossfading or not self._started:
            return False
        remaining = self.remaining_ms()
        if remaining is None:
            return False
        return remaining <= float(crossfade_ms)

    def set_volume(self, volume: float):
        """Set target volume; applies immediately on active slot if not crossfading."""
        self.target_volume = float(volume)
        if not self.is_crossfading:
            self._set_slot_volume(self.active_slot, self.target_volume)

    def pause(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PAUSED)

    def resume(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.PLAYING)

    def stop(self):
        """Stop pipeline and clear slot URIs."""
        self._crossfade = None
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        for slot in self.slots.values():
            if not slot:
                continue
            slot["uri"] = None
            slot["linked"] = False
            self._set_slot_volume(slot["name"], 0.0)
        self._started = False

    def destroy(self):
        """Release pipeline resources."""
        self.stop()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        self.pipeline = None
        self.mixer = None
        self.sink = None
        self.slots = {self.SLOT_A: None, self.SLOT_B: None}

    def get_state(self) -> str:
        """Return simplified state: stopped | paused | playing."""
        if not self.pipeline or not self._started:
            return "stopped"
        _, state, _ = self.pipeline.get_state(0)
        if state == Gst.State.PLAYING:
            return "playing"
        if state == Gst.State.PAUSED:
            return "paused"
        return "stopped"

    def poll_messages(self, max_messages: int = 32):
        """
        Pop bus messages and dispatch EOS/ERROR.

        Yields:
            Gst.Message: remaining messages for the caller
        """
        if not self.pipeline:
            return
        bus = self.pipeline.get_bus()
        count = 0
        message = bus.pop()
        while message and count < max_messages:
            count += 1
            msg_type = message.type
            if msg_type == Gst.MessageType.EOS:
                self._handle_eos(message)
            elif msg_type == Gst.MessageType.ERROR:
                err, debug = message.parse_error()
                text = f"{err} ({debug})"
                self._log("error", "CrossfadeEngine ERROR: %s", text)
                if self.on_error:
                    try:
                        self.on_error(text)
                    except Exception:
                        self._log("exception", "on_error failed")
            else:
                yield message
            message = bus.pop()

    def _handle_eos(self, message):
        """EOS on outgoing during crossfade is expected; otherwise notify caller."""
        src = message.src
        if self.is_crossfading:
            outgoing = self.slots[self._crossfade["outgoing"]]["decode"]
            if src == outgoing or (src and outgoing and src.get_parent() == outgoing):
                self._log("debug", "EOS on outgoing slot during crossfade (ignored)")
                return
            # EOS on incoming mid-fade: finish fade early
            self._finish_crossfade()
            return

        active_decode = self.slots[self.active_slot]["decode"]
        if src == active_decode or (src and src.get_name().startswith("decode-")):
            self._log("debug", "EOS on active slot")
            if self.on_eos:
                try:
                    self.on_eos()
                except Exception:
                    self._log("exception", "on_eos failed")
