# -*- coding: utf-8 -*-
# pylint: disable=unused-import
"""Miscellanneous utility functions"""
from __future__ import unicode_literals

import traceback
from datetime import datetime
from urllib import urlencode
from functools import wraps
from time import clock
import gzip
import base64
from StringIO import StringIO

import xbmc
import xbmcgui

from resources.lib.globals import g
from .logging import debug, info, error
from .kodiops import get_local_string


def find(value_to_find, attribute, search_space):
    """Find a video with matching id in a dict or list"""
    for video in search_space:
        if video[attribute] == value_to_find:
            return video
    raise KeyError('Metadata for {} does not exist'.format(value_to_find))


def find_episode_metadata(videoid, metadata):
    """Find metadata for a specific episode within a show metadata dict"""
    season = find(int(videoid.seasonid), 'id', metadata['seasons'])
    return (find(int(videoid.episodeid), 'id', season.get('episodes', {})),
            season)


def select_port():
    """Select a port for a server and store it in the settings"""
    port = select_unused_port()
    g.ADDON.setSetting('msl_service_port', str(port))
    info('[MSL] Picked Port: {}'.format(port))
    return port


def select_unused_port():
    """
    Helper function to select an unused port on the host machine

    :return: int - Free port
    """
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', 0))
    _, port = sock.getsockname()
    sock.close()
    return port


def get_class_methods(class_item=None):
    """
    Returns the class methods of agiven class object

    :param class_item: Class item to introspect
    :type class_item: object
    :returns: list -- Class methods
    """
    from types import FunctionType
    _type = FunctionType
    return [x
            for x, y in class_item.__dict__.iteritems()
            if isinstance(y, _type)]


def get_user_agent():
    """
    Determines the user agent string for the current platform.
    Needed to retrieve a valid ESN (except for Android, where the ESN can
    be generated locally)

    :returns: str -- User agent string
    """
    import platform
    chrome_version = 'Chrome/59.0.3071.115'
    base = 'Mozilla/5.0 '
    base += '%PL% '
    base += 'AppleWebKit/537.36 (KHTML, like Gecko) '
    base += '%CH_VER% Safari/537.36'.replace('%CH_VER%', chrome_version)
    system = platform.system()
    # Mac OSX
    if system == 'Darwin':
        return base.replace('%PL%', '(Macintosh; Intel Mac OS X 10_10_1)')
    # Windows
    if system == 'Windows':
        return base.replace('%PL%', '(Windows NT 6.1; WOW64)')
    # ARM based Linux
    if platform.machine().startswith('arm'):
        return base.replace('%PL%', '(X11; CrOS armv7l 7647.78.0)')
    # x86 Linux
    return base.replace('%PL%', '(X11; Linux x86_64)')


def build_url(pathitems=None, videoid=None, params=None, mode=None):
    """Build a plugin URL from pathitems and query parameters.
    Add videoid to the path if it's present."""
    if not (pathitems or videoid):
        raise ValueError('Either pathitems or videoid must be set.')
    path = '{netloc}/{path}/{qs}'.format(
        netloc=g.BASE_URL,
        path='/'.join(_expand_mode(mode) +
                      (pathitems or []) +
                      _expand_videoid(videoid)),
        qs=_encode_params(params))
    return path


def _expand_mode(mode):
    return [mode] if mode else []


def _expand_videoid(videoid):
    return videoid.to_path() if videoid else []


def _encode_params(params):
    return ('?' + urlencode(params)) if params else ''


def is_numeric(string):
    """Return true if string represents an integer, else false"""
    try:
        int(string)
    except ValueError:
        return False
    return True


def strp(value, form):
    """
    Helper function to safely create datetime objects from strings

    :return: datetime - parsed datetime object
    """
    # pylint: disable=broad-except
    from time import strptime
    def_value = datetime.utcfromtimestamp(0)
    try:
        return datetime.strptime(value, form)
    except TypeError:
        try:
            return datetime(*(strptime(value, form)[0:6]))
        except ValueError:
            return def_value
    except Exception:
        return def_value


def execute_tasks(title, tasks, task_handler, **kwargs):
    """Run all tasks through task_handler and display a progress
    dialog in the GUI. Additional kwargs will be passed into task_handler
    on each invocation.
    Returns a list of errors that occured during execution of tasks."""
    errors = []
    notify_errors = kwargs.pop('notify_errors', False)
    progress = xbmcgui.DialogProgress()
    progress.create(title)
    for task_num, task in enumerate(tasks):
        # pylint: disable=broad-except
        task_title = task.get('title', 'Unknown Task')
        progress.update(percent=int(task_num / len(tasks) * 100),
                        line1=task_title)
        xbmc.sleep(25)
        if progress.iscanceled():
            break
        try:
            task_handler(task, **kwargs)
        except Exception as exc:
            error(traceback.format_exc())
            errors.append({
                'task_title': task_title,
                'error': '{}: {}'.format(type(exc).__name__, exc)})
    _show_errors(notify_errors, errors)
    return errors


def _show_errors(notify_errors, errors):
    if notify_errors and errors:
        xbmcgui.Dialog().ok(get_local_string(0),
                            '\n'.join(['{} ({})'.format(err['task_title'],
                                                        err['error'])
                                       for err in errors]))


def compress_data(data):
    """GZIP and b64 encode data"""
    out = StringIO()
    with gzip.GzipFile(fileobj=out, mode='w') as outh:
        outh.write(data)
    return base64.standard_b64encode(out.getvalue())


def merge_dicts(dict_to_merge, merged_dict):
    """Recursively merge the contents of dict_to_merge into merged_dict.
    Values that are already present in merged_dict will not be overwritten
    if they are also present in dict_to_merge"""
    for key, value in dict_to_merge.iteritems():
        if isinstance(merged_dict.get(key), dict):
            merge_dicts(value, merged_dict[key])
        else:
            merged_dict[key] = value
    return merged_dict


def any_value_except(mapping, excluded_key):
    """Return a random value from a dict that is not associated with
    excluded_key. Raises StopIteration if there are no other keys than
    excluded_key"""
    return next(mapping[key] for key in mapping if key != excluded_key)


def time_execution(immediate):
    """A decorator that wraps a function call and times its execution"""
    # pylint: disable=missing-docstring
    def time_execution_decorator(func):
        @wraps(func)
        def timing_wrapper(*args, **kwargs):
            g.add_time_trace_level()
            start = clock()
            try:
                return func(*args, **kwargs)
            finally:
                if g.TIME_TRACE_ENABLED:
                    execution_time = int((clock() - start) * 1000)
                    if immediate:
                        debug('Call to {} took {}ms'
                              .format(func.func_name, execution_time))
                    else:
                        g.TIME_TRACE.append([func.func_name, execution_time,
                                             g.time_trace_level])
                g.remove_time_trace_level()
        return timing_wrapper
    return time_execution_decorator


def log_time_trace():
    """Write the time tracing info to the debug log"""
    if not g.TIME_TRACE_ENABLED:
        return

    time_trace = ['Execution time info for this run:\n']
    g.TIME_TRACE.reverse()
    for trace in g.TIME_TRACE:
        time_trace.append(' ' * trace[2])
        time_trace.append(format(trace[0], '<30'))
        time_trace.append('{:>5} ms\n'.format(trace[1]))
    debug(''.join(time_trace))
    g.reset_time_trace()
