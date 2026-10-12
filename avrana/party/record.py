"""The one durable fact about game sessions (AVR-33): which sessions Party Core started at which
game and has not yet seen the game reset. Written only when the `session_recovery.end_orphan_on_start`
switch is on (avrana.party.service).

Party Core keeps the party in memory, by design (core.py): a restart forgets the session id, while
the game it started still holds it, and for the arcade or PS1 that means a running runtime nobody
manages. This file lets a restarted Party Core send that game the signed `end` it already knows
(avrana.party.sessions) and start clean. Nothing else about the party is kept: no members, no
host, no roster, no tickets.

    {"schema": "avrana.party-active-session/v0",
     "sessions": [{"session": "session-…", "game": "bluff"}]}

Entries are keyed by session id: a new launch adds its own entry and never replaces one that has not
been processed yet, so a launch racing the startup recovery cannot hide an orphan (at most MAX_KEPT
are kept, newest last). Written (temporary file, fsync, rename, like devices.json) when a launch is
sent, and an entry is removed once an `end` for that session was confirmed or answered. A file that
cannot be read or written is never fatal: the party then behaves as it did before this record
existed. One lock covers every read and every read-modify-write (a launch, a confirmed end, the
release thread and the startup recovery all use it), so no update can overwrite another's.
A file that is not ours is set aside as `<name>.bad-<time>`, like devices.json, and the record
starts empty.
"""
import json
import logging
import os
import tempfile
import threading
import time

from avrana.party.identity import _fsync_dir

log = logging.getLogger('avrana.party.record')

SCHEMA = 'avrana.party-active-session/v0'
MAX_KEPT = 4


class SessionRecord:
    def __init__(self, path):
        self.path = path
        self._lock = threading.RLock()

    def _save(self, entries):
        folder = os.path.dirname(os.path.abspath(self.path))
        try:
            if not entries:
                try:
                    os.unlink(self.path)
                except FileNotFoundError:
                    pass
                return
            fd, tmp = tempfile.mkstemp(dir=folder, prefix='.active-session-')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump({'schema': SCHEMA, 'sessions': [{'session': s, 'game': g} for s, g in entries]}, f)
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

    def write(self, session_id, game_id):
        """Add this session to the record (an entry for the same session is replaced)."""
        if not self.path:
            return
        with self._lock:
            entries = [e for e in self.read() if e[0] != session_id] + [(session_id, game_id)]
            self._save(entries[-MAX_KEPT:])

    def read(self):
        """[(session id, game id), …], oldest first; [] when there is no usable record."""
        if not self.path:
            return []
        with self._lock:
            try:
                with open(self.path, encoding='utf-8') as f:
                    doc = json.load(f)
            except FileNotFoundError:
                return []
            except (OSError, ValueError, RecursionError) as e:
                self._set_aside(type(e).__name__)
                return []
            rows = doc.get('sessions') if isinstance(doc, dict) and doc.get('schema') == SCHEMA else None
            if not isinstance(rows, list) or not all(
                    isinstance(r, dict) and isinstance(r.get('session'), str) and isinstance(r.get('game'), str)
                    for r in rows):
                self._set_aside('not one of ours')
                return []
            return [(r['session'], r['game']) for r in rows][-MAX_KEPT:]

    def _set_aside(self, why):
        aside = f'{self.path}.bad-{int(time.time())}'
        log.warning('active-session record %s unusable (%s); starting empty, kept as %s', self.path, why, aside)
        try:
            os.replace(self.path, aside)
        except OSError:
            pass

    def clear(self, session_id):
        """Remove this session's entry; any other entry stays (a late confirmation of an older
        session must not erase a newer session's record)."""
        if not self.path:
            return
        with self._lock:
            entries = self.read()
            kept = [e for e in entries if e[0] != session_id]
            if len(kept) != len(entries):
                self._save(kept)
