# -*- coding: utf-8 -*-
"""
    Copyright (C) 2017 Sebastian Golasch (plugin.video.netflix)
    Copyright (C) 2019 Stefano Gottardo - @CastagnaIT (original implementation module)
    Handle and build Netflix events

    SPDX-License-Identifier: MIT
    See LICENSES/MIT.md for more information.
"""
from __future__ import absolute_import, division, unicode_literals

import collections
import random
import threading
import time

import xbmc

import resources.lib.cache as cache
from resources.lib import common
from resources.lib.globals import g
from resources.lib.services.msl import event_tag_builder
from resources.lib.services.msl.msl_handler_base import build_request_data

try:
    import Queue as queue
except ImportError:  # Python 3
    import queue

EVENT_START = 'start'      # events/start : Video starts (seem also after a ff/rw)
EVENT_STOP = 'stop'        # events/stop : Video stops (seem also after a ff/rw)
EVENT_KEEP_ALIVE = 'keepAlive'  # events/keepAlive : Update progress status
EVENT_ENGAGE = 'engage'    # events/engage : After user interaction (e.g. before send stop)
EVENT_BIND = 'bind'        # events/bind : ?


class Event(object):
    """Object representing an event request to be processed"""

    def __init__(self, event_data):
        self.event_type = event_data['params']['event']
        common.debug('Event type {} added to queue: {}', self.event_type, event_data)
        self.status = 'IN_QUEUE'
        self.request_data = event_data
        self.response_data = None
        self.req_attempt = 0

    def get_event_id(self):
        return self.request_data['xid']

    def set_response(self, response):
        self.response_data = response
        common.debug('Event type {} response: {}', self.event_type, response)
        # Todo check for possible error in response and set right status
        self.status = 'RESPONSE_ERROR'
        self.status = 'RESPONSE_SUCCESS'

    def is_response_success(self):
        return self.status == 'RESPONSE_SUCCESS'

    def is_attempts_granted(self):
        """Returns True if you can make new request attempts"""
        self.req_attempt += 1
        return True if self.req_attempt <= 3 else False

    def __str__(self):
        return self.event_type


class EventsHandler(threading.Thread):
    """Handle and build Netflix event requests"""

    def __init__(self, chunked_request):
        super(EventsHandler, self).__init__()
        self.chunked_request = chunked_request
        # session_id, app_id are common to all events
        self.session_id = int(time.time()) * 10000 + random.randint(1, 10001)
        self.app_id = None
        self.queue_events = queue.Queue(maxsize=10)
        self.cache_data_events = {}
        self.banned_events_ids = []

    def run(self):
        """Monitor and process the event queue"""
        monitor = xbmc.Monitor()
        while not monitor.abortRequested():
            try:
                # Take the first queued item
                event = self.queue_events.get_nowait()
                # Process the request
                continue_queue = self._process_event_request(event)
                if not continue_queue:
                    # Ban future requests from this event id
                    self.banned_events_ids += [event.get_event_id()]
            except queue.Empty:
                pass
            monitor.waitForAbort(0.5)

    def _process_event_request(self, event):
        """Do the event post request"""
        event.status = 'REQUESTED'
        # Request attempts can be made up to a maximum of 3 times per event
        while event.is_attempts_granted():
            common.error('Perform "{}" event request (attempt {})', event, event.req_attempt)
            params = {'reqAttempt': event.req_attempt,
                      'reqPriority': 0,
                      'reqName': 'events/{}'.format(event)}
            try:
                # Todo pass params
                # response = self.chunked_request(ENDPOINTS['events'], params, esn)
                # event.set_response(response)
                break
            except Exception as exc:
                common.error('Event "{}" request failed: {}', event, exc)
        if event == EVENT_STOP:
            self.clear_queue()
        if event == EVENT_START and not event.is_response_success():
            # If 'start' event was unsuccessful,
            # no longer make any future requests from this event id
            return False
        return True

    def add_event_to_queue(self, event_type, event_data, player_state):
        """Adds an event in the queue of events to be processed"""
        videoid = common.VideoId.from_dict(event_data['videoid'])
        previous_data = self.cache_data_events.get(videoid.value, {})
        manifest = get_manifest(videoid)
        url = manifest['links']['events']['href']

        if previous_data.get('xid') in self.banned_events_ids:
            common.warn('Event "{}" not added, is banned for a previous request event error',
                        event_type)
            return

        event_data = build_request_data(url, self._build_event_params(event_type,
                                                                      event_data,
                                                                      player_state,
                                                                      manifest))
        try:
            self.queue_events.put_nowait(Event(event_data))
        except queue.Full:
            common.warn('Events queue is full, event "{}" not queued', event_type)

    def clear_queue(self):
        """Clear all queued events"""
        with self.queue_events.mutex:
            self.queue_events.queue.clear()
        self.cache_data_events = {}
        self.banned_events_ids = []

    def _build_event_params(self, event_type, event_data, player_state, manifest):
        """Build data params for an event request"""
        videoid = common.VideoId.from_dict(event_data['videoid'])
        # Get previous elaborated data of the same video id
        # Some tags must remain unchanged between events
        previous_data = self.cache_data_events.get(videoid.value, {})
        timestamp = int(time.time() * 10000)

        # Context location values can be easily viewed from tag data-ui-tracking-context
        # of a preview box in website html
        play_ctx_location = 'MyListAsGallery' if event_data['is_in_mylist'] else 'browseTitles'

        params = {
            'event': event_type,
            'xid': previous_data.get('xid', str(timestamp + 1610)),
            'position': player_state['elapsed_seconds'] * 1000,  # Video time elapsed
            'clientTime': timestamp,
            'sessionStartTime': previous_data.get('sessionStartTime', timestamp),
            'mediaId': event_tag_builder.get_media_id(videoid, player_state, manifest),
            'trackId': event_data['track_id'],
            'sessionId': self.session_id,
            'appId': self.app_id or self.session_id,
            'playTimes': event_tag_builder.get_play_times(videoid, player_state, manifest),
            'sessionParams': previous_data.get('sessionParams', {
                'isUIAutoPlay': False,  # Should be set equal to the one in the manifest
                'supportsPreReleasePin': True,  # Should be set equal to the one in the manifest
                'supportsWatermark': True,  # Should be set equal to the one in the manifest
                'preferUnletterboxed': True,  # Should be set equal to the one in the manifest
                'uiplaycontext': {
                    'list_id': None,  # Todo: get id from current menu or my list, to test perhaps can be also Empty
                    'lolomo_id': None,  # Todo: get _ROOT lolomo, to test perhaps can be also Empty
                    'location': play_ctx_location,
                    'rank': 0,  # purpose not known, to now always 0
                    'request_id': event_data['request_id'],
                    'row': 0,  # purpose not known, to now always 0
                    # 'top_node_id': '',  # I think it is not necessary
                    'track_id': event_data['track_id'],
                    'trailer_compute_id': None,
                    'video_id': videoid.value
                }
            })
        }

        if event_type == EVENT_ENGAGE:
            params['action'] = 'User_Interaction'

        self.cache_data_events[videoid.value] = params
        return params


def get_manifest(videoid):
    """Get the manifest from cache"""
    cache_identifier = g.get_esn() + '_' + videoid.value
    return g.CACHE.get(cache.CACHE_MANIFESTS, cache_identifier, False)
