# -*- coding: utf-8 -*-
"""
    Copyright (C) 2017 Sebastian Golasch (plugin.video.netflix)
    Copyright (C) 2019 Stefano Gottardo - @CastagnaIT (original implementation module)
    Manages events to send to the netflix service for the progress of the played video

    SPDX-License-Identifier: MIT
    See LICENSES/MIT.md for more information.
"""
from __future__ import absolute_import, division, unicode_literals

import resources.lib.common as common

from .action_manager import PlaybackActionManager
from resources.lib.services.msl.events_handler import (EVENT_START, EVENT_STOP, EVENT_KEEP_ALIVE,
                                                       EVENT_ENGAGE)


class ProgressManager(PlaybackActionManager):
    """Detect the progress of the played video and send the data to the netflix service"""

    def __init__(self):  # pylint: disable=super-on-old-class
        super(ProgressManager, self).__init__()
        self.current_videoid = None
        self.tick_elapsed = 0
        self.last_video_elapsed_seconds = 0
        self.last_player_state = {}
        self.ignore_ticks = True
        self.event_data = {}

    def _initialize(self, data):
        videoid = common.VideoId.from_dict(data['videoid'])
        if videoid.mediatype not in [common.VideoId.MOVIE, common.VideoId.EPISODE]:
            self.enabled = False
            return
        self.current_videoid = videoid \
            if videoid.mediatype == common.VideoId.MOVIE \
            else videoid.derive_parent(0)
        self.event_data = data['event_data']

    def _on_playback_started(self, player_state):
        # Todo: safe clear queue events
        self.tick_elapsed = 0
        self.last_video_elapsed_seconds = 0
        self.start_event_requested = False
        self.ignore_ticks = False

    def _on_tick(self, player_state):
        if self.ignore_ticks:
            return
        if not self.start_event_requested and self.tick_elapsed == 2:
            # Before request 'start' event we have to wait a possible values changed
            # by stream_continuity, so is needed to wait at least 2 seconds
            self._send_event(EVENT_START, player_state)
            self.start_event_requested = True
            # Wait at least 1 minute before send keep alive events request after 'start' event
            self.tick_elapsed = 0
        elif self.tick_elapsed >= 60:
            # Send event requests to Netflix service every minute
            if (self.last_video_elapsed_seconds - player_state['elapsed_seconds']) >= 10 or \
               (self.last_video_elapsed_seconds - player_state['elapsed_seconds']) <= 10:
                # Possible fast forward / rewind, so do nothing
                pass
            else:
                self._send_event(EVENT_KEEP_ALIVE, player_state)
            self.tick_elapsed = 0
        self.last_player_state = player_state
        self.tick_elapsed += 1  # One tick is one second
        self.last_video_elapsed_seconds = player_state['elapsed_seconds']

    def _on_playback_pause(self, player_state):
        self._send_event(EVENT_ENGAGE, player_state)

    def _on_playback_seek(self, player_state):
        self.ignore_ticks = True
        self._send_event(EVENT_ENGAGE, player_state)
        self._send_event(EVENT_STOP, player_state)
        self.start_event_requested = False
        self.tick_elapsed = 0
        self.ignore_ticks = False

    def _on_playback_stopped(self):
        self._send_event(EVENT_STOP, self.last_player_state)

    def _send_event(self, event_type, player_state):
        """Send an event request"""
        # Todo: send event
        pass
