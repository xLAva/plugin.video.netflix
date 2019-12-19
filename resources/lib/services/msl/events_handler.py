# -*- coding: utf-8 -*-
"""
    Copyright (C) 2017 Sebastian Golasch (plugin.video.netflix)
    Copyright (C) 2019 Stefano Gottardo - @CastagnaIT (original implementation module)
    Handle and build Netflix events

    SPDX-License-Identifier: MIT
    See LICENSES/MIT.md for more information.
"""
from __future__ import absolute_import, division, unicode_literals

import time

from resources.lib import common
from resources.lib.services.msl import event_tag_builder

EVENT_START = 'start'    # events/start : Video starts (seem also after a ff/rw)
EVENT_STOP = 'stop'      # events/stop : Video stops (seem also after a ff/rw)
EVENT_ENGAGE = 'engage'  # events/engage : Used when ff/rw a video?
EVENT_BIND = 'bind'      # events/bind : ?


class EventsHandler(object):
    """Handle and build Netflix event requests"""

    def __init__(self):
        self.data_events = {}  # Todo: Store events data by video id value
        self.session_id = None  # Common to all events
        self.app_id = None  # Common to all events

    def build_event_data(self, event_type, player_state, playback_init_data):
        """Build an event data request"""
        videoid = common.VideoId.from_dict(playback_init_data['videoid'])
        # Get previous elaborated data of the same video id
        # Some tags must remain unchanged between events
        previous_data = self.data_events.get(videoid.value, {})
        timestamp = int(time.time() * 10000)

        track_id = ''  # Todo

        # Context location, known values: homeScreen, WATCHNOW, MyListAsGallery
        # Can be easily viewed from tag data-ui-tracking-context of a preview box in website html
        # Todo: switch values to better match the context with addon/nf menus and Kodi library
        play_ctx_location = 'homeScreen'

        params = {
            'event': event_type,
            'xid': previous_data.get('xid', str(timestamp + 1610)),
            'position': player_state['elapsed_seconds'] * 1000,  # Video time elapsed
            'clientTime': timestamp,
            'sessionStartTime': previous_data.get('sessionStartTime', timestamp),
            'mediaId': event_tag_builder.get_media_id(videoid, player_state),
            'trackId': track_id,
            'sessionId': self.session_id,
            'appId': self.app_id or self.session_id,
            'playTimes': event_tag_builder.get_play_times(videoid, player_state),
            'sessionParams': previous_data.get('sessionParams', {
                'isUIAutoPlay': False,
                'supportsPreReleasePin': True,
                'supportsWatermark': True,
                'preferUnletterboxed': True,
                'uiplaycontext': {
                    'list_id': None,  # Todo: get id from current menu or my list, to test perhaps can be also Empty
                    'lolomo_id': None,  # Todo: get _ROOT lolomo, to test perhaps can be also Empty
                    'location': play_ctx_location,
                    'rank': 0,  # purpose not known, to now always 0
                    'request_id': '',  # Todo
                    'row': 0,  # purpose not known, to now always 0
                    # 'top_node_id': '',  # I think it is not necessary
                    'track_id': track_id,
                    'trailer_compute_id': None,
                    'video_id': videoid.value
                }
            })
        }

        if event_type == EVENT_ENGAGE:
            params['action'] = 'User_Interaction'

        return params
