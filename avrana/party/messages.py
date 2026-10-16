"""The Party room: Party-owned messaging (docs/design/MESSAGING.md, AVR-53 / AVR-54).

One room per Party, held in memory and emptied with the Party. Party Core builds every field of a
line except a member's text: the sender is the credential's member, never anything the phone says.
People's words and system lines live in two rings that share one `seq`, so system lines can never
push a person's message out of history. Nothing here is written to disk or to a log.

This module is pure state. Locking, waking long polls and HTTP belong to avrana.party.service.
"""
import collections
import re
import unicodedata

SCOPE = 'party'
MEMBER_RING = 60            # member messages kept
SYSTEM_RING = 20            # system lines kept, in their own ring
TEXT_MAX = 400              # code points after cleaning
MARKS_MAX = 4               # combining marks in a row; more are dropped
MEMBER_RATE = (6, 4.0)      # messages per seconds, per member, kept on the member
PARTY_RATE = (30, 10.0)     # messages per seconds, per Party
SYSTEM_EVERY = 2.0          # s: at most one system line this often; events inside are counted
CLIENT_IDS = 8              # remembered client_ids per member
CLIENT_ID = re.compile(r'^[A-Za-z0-9_-]{1,36}$')
# The closed list of system events (MESSAGING.md decision 4). No free text ever.
EVENTS = ('joined', 'returned', 'left', 'host', 'renamed', 'round_started', 'round_ended')
_JOINERS = ('‌', '‍')                     # ZWNJ, ZWJ: emoji and several scripts need them
_SPACES = (' ', ' ')                      # line / paragraph separators become a space


class Refused(Exception):
    """A refused message request. `code` is stable for clients; `retry_ms` is set for too_fast."""

    def __init__(self, code, message, retry_ms=None):
        super().__init__(message)
        self.code = code
        self.retry_ms = retry_ms


def clean_text(raw):
    """A member's text as the room keeps it, or Refused('empty' | 'too_long' | 'bad_text').

    NFC; control, surrogate, private-use, unassigned and invisible formatting characters removed
    (the two joiners kept); line/paragraph separators and runs of white space become one space;
    more than MARKS_MAX combining marks in a row dropped. Counted in code points, as the phone
    counts."""
    if not isinstance(raw, str):
        raise Refused('bad_text', 'Type a message.')
    text = unicodedata.normalize('NFC', raw)
    out, marks = [], 0
    for ch in text:
        if ch in _SPACES:
            out.append(' ')
            marks = 0
            continue
        cat = unicodedata.category(ch)
        if cat in ('Cc', 'Cs', 'Co', 'Cn'):
            if ch in ('\t', '\n', '\r', '\x0b', '\x0c'):
                out.append(' ')
                marks = 0
            continue
        if cat == 'Cf' and ch not in _JOINERS:
            continue
        if cat.startswith('M'):
            marks += 1
            if marks > MARKS_MAX:
                continue
        else:
            marks = 0
        out.append(ch)
    text = ' '.join(''.join(out).split())
    visible = [ch for ch in text if not ch.isspace() and ch not in _JOINERS
               and not unicodedata.category(ch).startswith('M')
               and not 0xFE00 <= ord(ch) <= 0xFE0F]
    if not visible:
        raise Refused('empty', 'Type a message.')
    if len(text) > TEXT_MAX:
        raise Refused('too_long', f'Messages are at most {TEXT_MAX} characters.')
    return text


class _Window:
    """At most `n` events in any `span` seconds (a sliding window of times)."""
    __slots__ = ('n', 'span', 'times')

    def __init__(self, n, span):
        self.n, self.span, self.times = n, span, collections.deque()

    def wait(self, now):
        """Seconds until one more event is allowed (0 when it is allowed now)."""
        while self.times and now - self.times[0] >= self.span:
            self.times.popleft()
        return 0.0 if len(self.times) < self.n else self.span - (now - self.times[0])

    def add(self, now):
        self.times.append(now)


class Room:
    """One Party's room. `clock` is Party Core's (monotonic); no wall-clock time is kept or sent."""

    def __init__(self, clock):
        self.clock = clock
        self.seq = 0                                 # the last seq given to any line
        self.people = collections.deque(maxlen=MEMBER_RING)
        self.system_lines = collections.deque(maxlen=SYSTEM_RING)
        self._rates = {}                             # member id -> _Window (kept while the Party is)
        self._party_rate = _Window(*PARTY_RATE)
        self._sent = {}                              # member id -> OrderedDict client_id -> line
        self._last_system = None                     # when the last system line was written
        self._untold = 0                             # events since then that were counted, not written
        self.refusals = collections.Counter()        # code -> count; never text or names
        self.lost = 0                                # the highest seq that has left either ring

    # ---- reading --------------------------------------------------------------------------------
    def _keep(self, ring, line):
        if len(ring) == ring.maxlen:                 # the oldest line leaves: say so to readers
            self.lost = max(self.lost, ring[0]['seq'])
        ring.append(line)

    def first(self):
        """The lowest seq still held (0 for an empty room). With two rings this alone cannot say
        whether lines are missing (a quiet system ring keeps old lines); `lost` says that."""
        held = [ring[0]['seq'] for ring in (self.people, self.system_lines) if ring]
        return min(held) if held else 0

    def after(self, cursor):
        """Every held line above `cursor`, in order, each with its age (ms) as of now."""
        now = self.clock()
        lines = [line for ring in (self.people, self.system_lines) for line in ring
                 if line['seq'] > cursor]
        lines.sort(key=lambda line: line['seq'])
        return [self._public(line, now) for line in lines]

    @staticmethod
    def _public(line, now):
        out = {k: v for k, v in line.items() if k != 'at'}
        out['age_ms'] = max(0, int((now - line['at']) * 1000))
        return out

    # ---- writing --------------------------------------------------------------------------------
    def send(self, member, text, client_id):
        """A member's line. Returns (line, repeated). A repeated client_id answers with the line
        already stored (or its seq alone when it has left the ring), before any rate check."""
        if not isinstance(client_id, str) or not CLIENT_ID.match(client_id):
            raise self._refuse(Refused('bad_client_id', 'Send the message again.'))
        sent = self._sent.setdefault(member.id, collections.OrderedDict())
        if client_id in sent:
            line = sent[client_id]
            held = any(line is kept for kept in self.people)
            return (self._public(line, self.clock()) if held else {'seq': line['seq']}), True
        try:
            clean = clean_text(text)
        except Refused as e:
            raise self._refuse(e)
        now = self.clock()
        mine = self._rates.setdefault(member.id, _Window(*MEMBER_RATE))
        wait = max(mine.wait(now), self._party_rate.wait(now))
        if wait > 0:
            raise self._refuse(Refused('too_fast', 'Slow down a little.', int(wait * 1000) + 1))
        mine.add(now)
        self._party_rate.add(now)
        self.seq += 1
        line = {'seq': self.seq, 'kind': 'member', 'scope': SCOPE, 'from': member.id,
                'name': member.name, 'avatar': member.avatar, 'text': clean, 'at': now}
        self._keep(self.people, line)
        sent[client_id] = line
        while len(sent) > CLIENT_IDS:
            sent.popitem(last=False)
        return self._public(line, now), False

    def system(self, event, member, **extra):
        """A system line about `member`, metered: at most one per SYSTEM_EVERY seconds. An event
        inside that interval is counted; the next line written carries the count as `more`.
        Returns the line written, or None when it was counted."""
        if event not in EVENTS:
            raise ValueError(f'unknown system event {event!r}')
        now = self.clock()
        if self._last_system is not None and now - self._last_system < SYSTEM_EVERY:
            self._untold += 1
            return None
        self._last_system = now
        self.seq += 1
        line = {'seq': self.seq, 'kind': 'system', 'scope': SCOPE, 'from': member.id,
                'name': member.name, 'avatar': member.avatar, 'event': event, 'at': now}
        line.update({k: v for k, v in extra.items() if v is not None})
        if self._untold:
            line['more'], self._untold = self._untold, 0
        self._keep(self.system_lines, line)
        return line

    def _refuse(self, e):
        self.refusals[e.code] += 1
        return e
