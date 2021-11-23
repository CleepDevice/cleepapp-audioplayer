#!/usr/bin/env python
# -*- coding: utf-8 -*-

from cleep.libs.internals.event import Event


class AudioplayerMetadataUpdateEvent(Event):
    """
    Audioplayer.metadata.update event
    """

    EVENT_NAME = "audioplayer.metadata.update"
    EVENT_PARAMS = [
        "playeruuid",
        "artist",
        "album",
        "year",
        "genre",
        "track",
        "title",
        "channels",
        "bitratemin",
        "bitratemax",
        "bitrateavg",
    ]

    def __init__(self, params):
        """
        Constructor

        Args:
            params (dict): event parameters
        """
        Event.__init__(self, params)
