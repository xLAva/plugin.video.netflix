# -*- coding: utf-8 -*-
"""
    Copyright (C) 2017 Sebastian Golasch (plugin.video.netflix)
    Copyright (C) 2017 Trummerjo (original implementation module)
    Proxy service to convert manifest and provide license data

    SPDX-License-Identifier: MIT
    See LICENSES/MIT.md for more information.
"""
from __future__ import absolute_import, division, unicode_literals

import json
import time

import xbmcaddon

import resources.lib.cache as cache
import resources.lib.common as common
from resources.lib.globals import g
from resources.lib.services.msl.converter import convert_to_dash
from resources.lib.services.msl.msl_handler_base import (MSLHandlerBase, display_error_info,
                                                         ENDPOINTS)
from resources.lib.services.msl.profiles import enabled_profiles

try:  # Python 2
    unicode
except NameError:  # Python 3
    unicode = str  # pylint: disable=redefined-builtin


class MSLHandler(MSLHandlerBase):
    """Handles session management and crypto for license, manifest and event requests"""

    @display_error_info
    @common.time_execution(immediate=True)
    def load_manifest(self, viewable_id):
        """
        Loads the manifets for the given viewable_id and
        returns a mpd-XML-Manifest

        :param viewable_id: The id of of the viewable
        :return: MPD XML Manifest or False if no success
        """
        manifest = self._load_manifest(viewable_id, g.get_esn())
        # Disable 1080p Unlock for now, as it is broken due to Netflix changes
        # if (g.ADDON.getSettingBool('enable_1080p_unlock') and
        #         not g.ADDON.getSettingBool('enable_vp9_profiles') and
        #         not has_1080p(manifest)):
        #     common.debug('Manifest has no 1080p viewables, trying unlock')
        #     manifest = self.get_edge_manifest(viewable_id, manifest)
        return self.__tranform_to_dash(manifest)

    def get_edge_manifest(self, viewable_id, chrome_manifest):
        """Load a manifest with an EDGE ESN and replace playback_context and
        drm_context"""
        common.debug('Loading EDGE manifest')
        esn = g.get_edge_esn()
        common.debug('Switching MSL data to EDGE')
        self.perform_key_handshake(esn)
        manifest = self._load_manifest(viewable_id, esn)
        manifest['playbackContextId'] = chrome_manifest['playbackContextId']
        manifest['drmContextId'] = chrome_manifest['drmContextId']
        common.debug('Successfully loaded EDGE manifest')
        common.debug('Resetting MSL data to Chrome')
        self.perform_key_handshake()
        return manifest

    @common.time_execution(immediate=True)
    def _load_manifest(self, viewable_id, esn):
        cache_identifier = esn + '_' + unicode(viewable_id)
        try:
            # The manifest must be requested once and maintained for its entire duration
            manifest = g.CACHE.get(cache.CACHE_MANIFESTS, cache_identifier, False)
            common.debug('Manifest for {} with ESN {} obtained from the cache', viewable_id, esn)
            # Save the manifest to disk as reference
            common.save_file('manifest.json', json.dumps(manifest).encode('utf-8'))
            return manifest
        except cache.CacheMiss:
            pass
        common.debug('Requesting manifest for {} with ESN {}', viewable_id, esn)
        profiles = enabled_profiles()
        import pprint
        common.info('Requested profiles:\n{}', pprint.pformat(profiles, indent=2))

        ia_addon = xbmcaddon.Addon('inputstream.adaptive')
        hdcp = ia_addon is not None and ia_addon.getSetting('HDCPOVERRIDE') == 'true'

        # TODO: Future implementation when available,
        #       request the HDCP version from Kodi through a function
        #       in CryptoSession currently not implemented
        #       so there will be no more need to use the HDCPOVERRIDE = true

        hdcp_version = []
        if not g.ADDON.getSettingBool('enable_force_hdcp') and hdcp:
            hdcp_version = ['1.4']
        if g.ADDON.getSettingBool('enable_force_hdcp') and hdcp:
            hdcp_version = ['2.2']

        params = {
            'type': 'standard',
            'viewableId': [viewable_id],
            'profiles': profiles,
            'flavor': 'PRE_FETCH',
            'drmType': 'widevine',
            'drmVersion': 25,
            'usePsshBox': True,
            'isBranching': False,
            'isNonMember': False,
            'isUIAutoPlay': False,
            'useHttpsStreams': True,
            'imageSubtitleHeight': 1080,
            'uiVersion': 'shakti-v93016808',
            'uiPlatform': 'SHAKTI',
            'clientVersion': '6.0016.426.011',
            'desiredVmaf': 'plus_lts',  # phone_plus_exp can be used to mobile, not tested
            'supportsPreReleasePin': True,
            'supportsWatermark': True,
            'supportsUnequalizedDownloadables': True,
            'showAllSubDubTracks': False,
            'titleSpecificData': {
                viewable_id: {
                    'unletterboxed': True
                }
            },
            'videoOutputInfo': [{
                'type': 'DigitalVideoOutputDescriptor',
                'outputType': 'unknown',
                'supportedHdcpVersions': hdcp_version,
                'isHdcpEngaged': hdcp
            }],
            'preferAssistiveAudio': False
        }

        # Get and check mastertoken validity
        mt_validity = self.check_mastertoken_validity()

        manifest = self.chunked_request(ENDPOINTS['manifest'],
                                        self.build_request_data('/manifest', params),
                                        esn,
                                        mt_validity)
        # Save the manifest to disk as reference
        common.save_file('manifest.json', json.dumps(manifest).encode('utf-8'))
        # Save the manifest to the cache to retrieve it during its validity
        expiration = int(manifest['expiration'] / 1000)
        g.CACHE.add(cache.CACHE_MANIFESTS, cache_identifier, manifest, eol=expiration)
        if 'result' in manifest:
            return manifest['result']
        return manifest

    @display_error_info
    @common.time_execution(immediate=True)
    def get_license(self, challenge, sid):
        """
        Requests and returns a license for the given challenge and sid
        :param challenge: The base64 encoded challenge
        :param sid: The sid paired to the challenge
        :return: Base64 representation of the license key or False unsuccessful
        """
        common.debug('Requesting license')

        timestamp = int(time.time() * 10000)
        params = [{
            'sessionId': sid,
            'clientTime': int(timestamp / 10000),
            'challengeBase64': challenge,
            'xid': str(timestamp + 1610)
        }]
        # Todo: get last license url by last item of events list
        url = self.last_license_url

        response = self.chunked_request(ENDPOINTS['license'],
                                        self.build_request_data(url, params, 'sessionId'),
                                        g.get_esn())
        return response[0]['licenseResponseBase64']

    @common.time_execution(immediate=True)
    def __tranform_to_dash(self, manifest):
        self.last_license_url = manifest['links']['license']['href']
        self.last_playback_context = manifest['playbackContextId']
        self.last_drm_context = manifest['drmContextId']
        return convert_to_dash(manifest)


def has_1080p(manifest):
    """Return True if any of the video tracks in manifest have a 1080p profile
    available, else False"""
    return any(video['width'] >= 1920
               for video in manifest['videoTracks'][0]['downloadables'])
