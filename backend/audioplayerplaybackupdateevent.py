#!/usr/bin/env python
# -*- coding: utf-8 -*-

from cleep.libs.internals.event import Event


class AudioplayerPlaybackUpdateEvent(Event):
    """
    Audioplayer.playback.update event
    """

    EVENT_NAME = "audioplayer.playback.update"
    EVENT_PARAMS = ["playeruuid", "state", "duration", "track", "metadata", "index"]

    def __init__(self, params):
        """
        Constructor

        Args:
            params (dict): event parameters
        """
        Event.__init__(self, params)
