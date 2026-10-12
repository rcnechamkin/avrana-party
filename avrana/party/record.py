"""The one durable fact about a game session (AVR-33): which session Party Core last started at
which game, and has not yet seen the game reset.

Party Core keeps the party in memory, by design (core.py): a restart forgets the session id, while
the game it started still holds it, and for the arcade or PS1 that means a running runtime nobody
manages. This file lets a restarted Party Core send that game the signed `end` it already knows
(avrana.party.sessions) and start clean. Nothing else about the party is kept: no members, no
host, no roster, no tickets.

    {"schema": "avrana.party-active-session/v0", "session": "session-…", "game": "bluff"}

Written (temporary file, fsync, rename, like devices.json) when a launch is sent, and removed once
an `end` for that session was confirmed or answered "not held". A file that cannot be read or
written is never fatal: the party then behaves as it did before this record existed.
"""
import json
import logging
import os
import tempfile

from avrana.party.identity import _fsync_dir

log = logging.getLogger('avrana.party.record')

SCHEMA = 'avrana.party-active-session/v0'


class SessionRecord:
    def __init__(self, path):
        self.path = path

    def write(self, session_id, game_id):
        if not self.path:
            return
        folder = os.path.dirname(os.path.abspath(self.path))
        try:
            fd, tmp = tempfile.mkstemp(dir=folder, prefix='.active-session-')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump({'schema': SCHEMA, 'session': session_id, 'game': game_id}, f)
                    f.flush()
                    os.fsync(f.fileno())
                os.chmod(tmp, 0o600)
                os.replace(tmp, self.path)
                _fsync_dir(folder)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
        except OSError as e:
            log.warning('active-session record %s not written (%s)', self.path, type(e).__name__)

    def read(self):
        """(session id, game id), or None when there is no usable record."""
        if not self.path:
            return None
        try:
            with open(self.path, encoding='utf-8') as f:
                doc = json.load(f)
        except FileNotFoundError:
            return None
        except (OSError, ValueError, RecursionError) as e:
            log.warning('active-session record %s unreadable (%s); ignored', self.path, type(e).__name__)
            return None
        if (not isinstance(doc, dict) or doc.get('schema') != SCHEMA
                or not isinstance(doc.get('session'), str) or not isinstance(doc.get('game'), str)):
            log.warning('active-session record %s is not one of ours; ignored', self.path)
            return None
        return doc['session'], doc['game']

    def clear(self, session_id=None):
        """Remove the record, but only the one for `session_id` when given: a late confirmation of
        an older session must not erase the newer session's record."""
        if not self.path:
            return
        if session_id is not None:
            current = self.read()
            if current is not None and current[0] != session_id:
                return
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        except OSError as e:
            log.warning('active-session record %s not removed (%s)', self.path, type(e).__name__)
