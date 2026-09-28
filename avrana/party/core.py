"""The party's authoritative state: membership, presence, host and the one game session.

Pure and synchronous: no sockets, no threads, no files. The caller (avrana.party.service) holds
one lock around every call and injects the clock. Callers are identified only by a `device_id`
the service resolved from its own cookie; names never authorize.

Rules come from docs/design/PARTY-LIFECYCLE.md and the lifecycle model (branch
experiment/party-sim, 52 tests + fuzz). What changed for production, and why:

* **Presence is liveness, not a socket.** A member is `here` while any authenticated party
  request (Party Home's poll, a game page's heartbeat, a ticket fetch) arrived within
  LIVE_WINDOW; otherwise `away`. Membership ends only on an explicit Leave, never on silence.
  The experiment tied presence to Party Home's event stream, so walking into a game looked like
  leaving the party.
* **Playing is not leaving.** A member who holds a place in the active game session shows as
  `playing`, and the host role never moves away from a host who is in the game. The game owns
  in-game disconnects (grace, autopilot, pause); the party does not duplicate those timers.
* **One game session at a time**, launching -> active -> ending -> ended. The session carries the
  party-approved roster; each member gets an opaque participant id that exists only inside that
  session, so games never see device or member ids.

Not here (deliberately): persistence across reboot (the party is memory-only; OPEN), kicks, votes,
profiles, teams, seat assignment (the game seats its roster), results and scores.
"""
import itertools
import secrets
import unicodedata

LIVE_WINDOW = 45.0         # s since the last party request before a member counts as away
HOST_GRACE = 30.0          # s an away host keeps the role before succession (PARTY-LIFECYCLE.md)
LAUNCH_TIMEOUT = 60.0      # s for the game to accept a launch
END_TIMEOUT = 15.0         # s for the game to confirm an end before the party stops waiting
PARTY_IDLE = 3 * 3600.0    # s with nobody here and no session before the party ends
NAME_MAX = 16
RESERVED_NAMES = ('system', 'admin', 'host', 'avrana', 'moderator')

# Session states and outcomes. `outcome` is set exactly when the state becomes 'ended'.
LAUNCHING, ACTIVE, ENDING, ENDED = 'launching', 'active', 'ending', 'ended'
OUTCOMES = ('completed', 'abandoned', 'ended_by_host', 'launch_failed')
ROLES = ('player', 'spectator')


class Refused(Exception):
    """The request is not allowed now. `code` is stable for clients; the message is for people."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def new_id(kind):
    return f'{kind}-{secrets.token_hex(16)}'       # 128-bit random; never derived from anything


def _name_key(name):
    return ''.join(ch for ch in name.casefold() if ch.isalnum())


def clean_name(raw):
    """Display-name rule (from the model): NFKC; no control/format characters; spaces collapsed;
    1..NAME_MAX characters; one look-alike script; not a reserved word. Raises Refused."""
    if not isinstance(raw, str):
        raise Refused('bad_name', 'Pick a name.')
    text = unicodedata.normalize('NFKC', raw)
    text = ''.join(ch for ch in text if unicodedata.category(ch) not in ('Cc', 'Cf'))
    text = ' '.join(text.split())
    if not 1 <= len(text) <= NAME_MAX:
        raise Refused('bad_name', f'Names are 1 to {NAME_MAX} characters.')
    scripts = {unicodedata.name(ch, 'UNKNOWN').split()[0] for ch in text if ch.isalpha()}
    if len(scripts & {'LATIN', 'CYRILLIC', 'GREEK'}) > 1:
        raise Refused('bad_name', 'Please use one alphabet in your name.')
    key = _name_key(text)
    if not key or key.startswith(RESERVED_NAMES):
        raise Refused('bad_name', 'Please pick another name.')
    return text


class Member:
    __slots__ = ('id', 'device_id', 'name', 'joined_at', 'last_seen', 'left')

    def __init__(self, device_id, name, now):
        self.id = new_id('member')
        self.device_id = device_id
        self.name = name
        self.joined_at = now
        self.last_seen = now
        self.left = False


class Participant:
    """A member's place in one game session. `id` is what the game sees; it is random, exists
    only in this session, and survives reconnects (the same member always gets the same one)."""
    __slots__ = ('id', 'member_id', 'role')

    def __init__(self, member_id, role):
        self.id = new_id('participant')
        self.member_id = member_id
        self.role = role


class GameSession:
    def __init__(self, game, started_by, now):
        self.id = new_id('session')
        self.game_id = game['id']
        self.late_join = game.get('late_join', 'spectator_only')
        self.started_by = started_by
        self.created_at = now
        self.state = LAUNCHING
        self.state_since = now
        self.outcome = None
        self.detail = None              # e.g. why a launch failed; shown to people
        self.game_confirmed_end = None  # True/False once an end-for-everyone was attempted
        self.participants = {}          # member_id -> Participant (insertion order = roster order)

    def roster(self, members):
        """The game-facing roster: participant id, display name and role only."""
        return [{'participant': p.id, 'name': members[p.member_id].name, 'role': p.role}
                for p in self.participants.values()]


class Party:
    def __init__(self, now):
        self.id = new_id('party')
        self.created_at = now
        self.version = 0
        self.members = {}               # member_id -> Member (insertion order = join order)
        self.host_id = None
        self.session = None             # the current or most recent GameSession
        self.released_at = {}           # member_id -> when their last session ended
        self.idle_since = now
        self.ended = False


class PartyCore:
    """One appliance, one party. Every public method applies due timers first, so a deadline
    holds at the moment someone acts, not only when the background tick runs (model rule R4)."""

    def __init__(self, clock, games):
        self.clock = clock
        self.games = dict(games)        # game_id -> {'id', 'max_players', 'late_join'}
        self.party = Party(clock())
        self._shown = {}                # member_id -> presence last published (timer diffing)

    # ---- helpers ------------------------------------------------------------------------------
    def _commit(self):
        self.party.version += 1
        now = self.clock()
        self._shown = {m.id: self.presence(m, now) for m in self.party.members.values()}

    def _member_of(self, device_id):
        return next((m for m in self.party.members.values() if m.device_id == device_id), None)

    def _require_member(self, device_id):
        m = self._member_of(device_id)
        if m is None or m.left:
            raise Refused('not_member', 'Join the party first.')
        return m

    def _require_host(self, device_id, if_version):
        m = self._require_member(device_id)
        if m.id != self.party.host_id:
            raise Refused('not_host', 'Only the host can do that.')
        if if_version != self.party.version:
            raise Refused('stale', 'The party changed. Have another look and try again.')
        return m

    def _live_session(self):
        s = self.party.session
        return s if s is not None and s.state != ENDED else None

    def _playing(self, member):
        s = self._live_session()
        p = s.participants.get(member.id) if s else None
        return p is not None and s.state == ACTIVE

    def _seen(self, member):
        """Liveness for presence and host grace: a member released from a game counts as seen
        at that moment, so a whole table coming home is not instantly 'away'."""
        return max(member.last_seen, self.party.released_at.get(member.id, member.last_seen))

    def presence(self, member, now=None):
        now = self.clock() if now is None else now
        if member.left:
            return 'left'
        if self._playing(member):
            return 'playing'
        return 'here' if now - self._seen(member) < LIVE_WINDOW else 'away'

    def _here(self, member, now):
        return self.presence(member, now) in ('here', 'playing')

    def _successor(self, now, exclude):
        return next((m for m in self.party.members.values()
                     if not m.left and m.id != exclude and self.presence(m, now) == 'here'), None)

    def _set_host(self, member_id):
        self.party.host_id = member_id

    # ---- timers --------------------------------------------------------------------------------
    def tick(self):
        """Apply every due timer. Returns True when the party changed (the version moved)."""
        before = self.party.version
        self._run_timers()
        return self.party.version != before

    def _run_timers(self):
        party, now = self.party, self.clock()
        if party.ended:
            return
        host = party.members.get(party.host_id)
        if host is not None and not self._playing(host) \
                and now - self._seen(host) >= LIVE_WINDOW + HOST_GRACE:
            nxt = self._successor(now, exclude=host.id)
            self._set_host(nxt.id if nxt else None)           # None = vacant until someone is here
            self._commit()
        s = party.session
        if s is not None and s.state == LAUNCHING and now - s.state_since >= LAUNCH_TIMEOUT:
            self._close(s, 'launch_failed', 'The game did not start in time.')
        if s is not None and s.state == ENDING and now - s.state_since >= END_TIMEOUT:
            s.game_confirmed_end = False
            self._close(s, 'ended_by_host')
        shown = {m.id: self.presence(m, now) for m in party.members.values()}
        if shown != self._shown:                              # here -> away by time alone is a
            self._commit()                                    # change other phones must see
        anyone_here = any(self._here(m, now) for m in party.members.values() if not m.left)
        if anyone_here or self._live_session():
            party.idle_since = None
        elif party.idle_since is None:
            party.idle_since = now
        if party.idle_since is not None and now - party.idle_since >= PARTY_IDLE:
            party.ended = True
            self._commit()

    def _timed(self):
        self._run_timers()
        if self.party.ended:                                  # the next visitor starts afresh
            self.party = Party(self.clock())
            self._shown = {}

    # ---- membership ----------------------------------------------------------------------------
    def join(self, device_id, name):
        """Explicit Join: the only way to become a member. Idempotent for a device that is
        already in; a device that left comes back as the same member."""
        self._timed()
        clean = clean_name(name)
        now = self.clock()
        m = self._member_of(device_id)
        if m is None:
            m = Member(device_id, self._unique(clean, None), now)
            self.party.members[m.id] = m
        else:
            if m.left:
                m.left = False
                m.name = self._unique(clean, m)
            m.last_seen = now
        if self.party.host_id is None:
            self._set_host(m.id)
        self._late_admit(m)
        self._commit()
        return m

    def touch(self, device_id):
        """A heartbeat from Party Home, a game page or a ticket fetch. Observers are ignored:
        looking at the party never joins it."""
        self._timed()
        m = self._member_of(device_id)
        if m is None or m.left:
            return None
        was_here = self._here(m, self.clock())
        m.last_seen = self.clock()
        if self.party.host_id is None:
            self._set_host(m.id)
            self._commit()
        elif not was_here:
            self._commit()                                    # away -> here is visible to others
        return m

    def rename(self, device_id, name):
        self._timed()
        m = self._require_member(device_id)
        m.name = self._unique(clean_name(name), m)
        m.last_seen = self.clock()
        self._commit()
        return m

    def leave(self, device_id):
        """Explicit Leave. The member's place in a live session stays (the game decides what an
        absent seat does); if they were host, the next member who is here takes over at once."""
        self._timed()
        m = self._require_member(device_id)
        m.left = True
        if m.id == self.party.host_id:
            nxt = self._successor(self.clock(), exclude=m.id)
            self._set_host(nxt.id if nxt else None)
        self._commit()

    def transfer_host(self, device_id, to_member_id, if_version):
        self._timed()
        self._require_host(device_id, if_version)
        target = self.party.members.get(to_member_id)
        if target is None or target.left or not self._here(target, self.clock()):
            raise Refused('bad_target', 'You can only hand over to someone who is here.')
        self._set_host(target.id)
        self._commit()

    def _unique(self, clean, me):
        taken = {_name_key(o.name) for o in self.party.members.values() if o is not me and not o.left}
        final, n = clean, 2
        while _name_key(final) in taken:
            final = f'{clean[:NAME_MAX - len(str(n)) - 1]} {n}'
            n += 1
        return final

    # ---- the game session ------------------------------------------------------------------------
    def launch(self, device_id, game_id, if_version):
        """Host starts a game. The party decides the roster now: members who are here become
        players in join order up to the game's maximum; the rest are spectators. The game seats
        its players. Returns the new session, still 'launching' until the game accepts it."""
        self._timed()
        host = self._require_host(device_id, if_version)
        if self._live_session():
            raise Refused('busy', 'A game is already on. End it first.')
        game = self.games.get(game_id)
        if game is None:
            raise Refused('unknown_game', 'That game is not available here.')
        now = self.clock()
        s = GameSession(game, host.id, now)
        here = [m for m in self.party.members.values() if not m.left and self._here(m, now)]
        for i, m in enumerate(here):
            p = Participant(m.id, 'player' if i < game['max_players'] else 'spectator')
            s.participants[m.id] = p
        self.party.session = s
        self._commit()
        return s

    def launch_accepted(self, session_id):
        """The game confirmed the launch. Stale or unknown sessions are ignored (False)."""
        self._timed()
        s = self.party.session
        if s is None or s.id != session_id or s.state != LAUNCHING:
            return False
        s.state, s.state_since = ACTIVE, self.clock()
        self._commit()
        return True

    def launch_failed(self, session_id, detail):
        self._timed()
        s = self.party.session
        if s is None or s.id != session_id or s.state != LAUNCHING:
            return False
        self._close(s, 'launch_failed', detail)
        return True

    def begin_end(self, device_id, if_version):
        """Host ends the game for everyone. Tickets for the session stop at once; the service
        then asks the game to reset and reports back with end_confirmed()."""
        self._timed()
        self._require_host(device_id, if_version)
        s = self._live_session()
        if s is None or s.state == ENDING:
            raise Refused('no_game', 'No game is on.')
        if s.state == LAUNCHING:
            self._close(s, 'launch_failed', 'Cancelled by the host.')
            return s
        s.state, s.state_since = ENDING, self.clock()
        self._commit()
        return s

    def end_confirmed(self, session_id, confirmed):
        self._timed()
        s = self.party.session
        if s is None or s.id != session_id or s.state != ENDING:
            return False
        s.game_confirmed_end = bool(confirmed)
        self._close(s, 'ended_by_host')
        return True

    def game_reported_end(self, session_id, outcome):
        """The game says its session is over ('completed' or 'abandoned'). The caller has already
        authenticated the report as coming from that game's server. Anything but the live, active
        session is refused, so an old report can never end (or resurrect) a newer session."""
        self._timed()
        if outcome not in ('completed', 'abandoned'):
            raise Refused('bad_outcome', 'Unknown outcome.')
        s = self.party.session
        if s is None or s.id != session_id or s.state not in (ACTIVE, ENDING):
            raise Refused('stale_session', 'That game session is not running.')
        if s.state == ENDING:                     # the host's end already won; the game agrees
            s.game_confirmed_end = True
            self._close(s, 'ended_by_host')
        else:
            self._close(s, outcome)
        return s

    def _close(self, s, outcome, detail=None):
        now = self.clock()
        s.state, s.state_since, s.outcome = ENDED, now, outcome
        if detail:
            s.detail = detail
        for member_id in s.participants:
            self.party.released_at[member_id] = now
        self._commit()

    def participant_for(self, device_id):
        """The caller's place in the active session (for a ticket), admitting a member who joined
        after the launch as a spectator. Returns (session, participant)."""
        self._timed()
        m = self._require_member(device_id)
        s = self._live_session()
        if s is None or s.state != ACTIVE:
            raise Refused('no_game', 'No game is on.')
        m.last_seen = self.clock()
        p = s.participants.get(m.id)
        if p is None:
            p = self._late_admit(m)
            self._commit()
        return s, p

    def _late_admit(self, m):
        """Party admission after launch. v0 admits late members as spectators only; a game that
        wants more says so in its contract (late_join) and a later version honours it."""
        s = self._live_session()
        if s is None or s.state != ACTIVE or m.id in s.participants:
            return s.participants.get(m.id) if s else None
        p = Participant(m.id, 'spectator')
        s.participants[m.id] = p
        return p

    # ---- views ---------------------------------------------------------------------------------------
    def view(self, device_id):
        """What one phone may see. No device ids, no participant ids of others, no tickets."""
        self._timed()
        party, now = self.party, self.clock()
        me = self._member_of(device_id) if device_id else None
        if me is not None and me.left:
            me = None
        members = [{'id': m.id, 'name': m.name, 'presence': self.presence(m, now),
                    'host': m.id == party.host_id}
                   for m in party.members.values() if not m.left]
        s = party.session
        session = None
        if s is not None:
            mine = s.participants.get(me.id) if me else None
            session = {'id': s.id, 'game': s.game_id, 'state': s.state, 'outcome': s.outcome,
                       'detail': s.detail,
                       'players': sum(1 for p in s.participants.values() if p.role == 'player'),
                       'my_role': mine.role if mine else None}
        return {'party': party.id, 'version': party.version,
                'state': s.state if s is not None and s.state != ENDED else 'lobby',
                'members': members, 'host': party.host_id,
                'me': ({'id': me.id, 'name': me.name, 'host': me.id == party.host_id}
                       if me else None),
                'session': session,
                'games': sorted(self.games) if me and me.id == party.host_id else []}
