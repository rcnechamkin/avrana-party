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
* **One place for everyone** (AVR-128). `nav` says where the party is: a game (its session became
  active) or home (the host ended it, or a switch's next game failed to start). It moves only on
  those committed transitions (PARTY-LIFECYCLE R2), keyed by (party, seq) (R5). Party Home and
  every integrated game page follow it. A game that ends by its own rules leaves `nav` alone: its
  end screen is the intermission, and the host's next start moves everyone on.
* **Pregame is the party's** (AVR-129, ADR 0010). A game configured with `pregame` opens in
  `setup`: the party is already on the game's page, nothing runs at the game yet, and every member
  who is here chooses to play or to watch this round. Only the host starts the round, and only
  once the game's minimum is met and everyone here has chosen; the choices become the roster's
  roles. Roles change only at that boundary: during a round a choice is refused, and a member who
  arrives late watches until the next setup.
* **One location** (ADR 0011, the console model). Every view carries `location`: where the
  whole party is right now, `home`, `setup` (a round being set up), `game` (a round on) or
  `results` (a round that ended by the game's own rules, held until the host moves on). Every
  member's phone renders that location; only the host moves it (start, round start, end, Party
  Home, play again). Presence is automatic: a phone with a profile joins on its own.
* **Switching is end, then launch.** The host's switch ends the game that is on (the service
  waits for that game's server to reset) before the next session exists, so two party games never
  run at once. If the old game does not confirm its end, the switch stops there: nothing new starts
  on top of a game that may still be running.

* **Two modes, one party** (ADR 0012, AVR-225). A member reached over trusted HTTPS is in
  `full` mode; one reached over the plain-HTTP fallback is in `limited` mode. The service says
  which when the member joins (it knows which listener the request arrived on); the mode is
  shown beside each member and never changes for that member, because a phone that changes
  mode is a new device. A Limited member has every party right, the host role included. When
  the role moves by succession, a Full Mode member who is here is preferred; a host who is
  here is never displaced, whatever their mode.

Not here (deliberately): persistence across reboot (the party is memory-only; OPEN), kicks, votes,
profiles, teams, seat assignment (the game seats its roster), results and scores.
"""
import itertools
import re
import secrets
import unicodedata

from avrana.party import result as game_result

LIVE_WINDOW = 45.0         # s since the last party request before a member counts as away
HOST_GRACE = 30.0          # s an away host keeps the role before succession (PARTY-LIFECYCLE.md)
LAUNCH_TIMEOUT = 60.0      # s for the game to accept a launch
END_TIMEOUT = 15.0         # s for the game to confirm an end before the party stops waiting
PARTY_IDLE = 3 * 3600.0    # s with nobody here and no session before the party ends
NAME_MAX = 16
RESERVED_NAMES = ('system', 'admin', 'host', 'avrana', 'moderator')
AVATAR = re.compile(r'^gaze-\d\d$')     # a bundled DiceBear Gaze avatar id (web/party/avatars/)

# Session states and outcomes. `outcome` is set exactly when the state becomes 'ended'.
LAUNCHING, ACTIVE, ENDING, ENDED = 'launching', 'active', 'ending', 'ended'
SETUP = 'setup'                 # pregame (AVR-129): members choose to play or watch; host starts
CHOICES = ('player', 'spectator')
OUTCOMES = ('completed', 'abandoned', 'ended_by_host', 'launch_failed')
ROLES = ('player', 'spectator')
FULL, LIMITED = 'full', 'limited'    # how a member's phone reaches the party (ADR 0012)
MODES = (FULL, LIMITED)


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


def clean_avatar(raw):
    """A profile avatar: only a bundled Gaze id is kept; anything else shows the default."""
    return raw if isinstance(raw, str) and AVATAR.match(raw) else None


class Member:
    __slots__ = ('id', 'device_id', 'name', 'avatar', 'joined_at', 'last_seen', 'left', 'mode')

    def __init__(self, device_id, name, now, avatar=None, mode=FULL):
        self.id = new_id('member')
        self.device_id = device_id
        self.name = name
        self.avatar = avatar
        self.mode = mode
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
        self.result = None              # the accepted game result (ADR 0015), or None
        self.result_refused = None      # why a reported result was not accepted, or None
        self.detail = None              # e.g. why a launch failed; shown to people
        self.game_confirmed_end = None  # True/False once an end-for-everyone was attempted
        self.replaced = None            # the session a host switch ended for this one (AVR-128)
        self.pregame = bool(game.get('pregame'))   # opened in setup (AVR-129)
        self.min_players = game.get('min_players', 1)
        self.max_players = game['max_players']
        self.choices = {}               # member_id -> 'player' | 'spectator' (setup only)
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
        self.nav = {'seq': 0, 'to': 'home', 'game': None, 'session': None, 'from': None}
        self.pending = None             # the game a host switch moves to, while the old one ends


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
        """The earliest-joined member who is present. Playing counts as present: a player in the
        active game can take over (AVR-127), so a host leaving mid-game never leaves it vacant.
        A Full Mode member is preferred over a Limited Mode one (ADR 0012 D4): the role is safer
        on a connection other guests cannot read. With nobody in Full Mode, Limited serves."""
        here = [m for m in self.party.members.values()
                if not m.left and m.id != exclude and self._here(m, now)]
        return next((m for m in here if m.mode == FULL), here[0] if here else None)

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
            switching = party.pending is not None
            party.pending = None                  # a switch never starts over a game that
            self._close(s, 'ended_by_host',       # did not confirm its end (AVR-223: say so)
                        'The last game did not stop, so the next one did not start.' if switching
                        else 'The game did not confirm the end in time.')
        if party.pending is not None and s is not None and s.state == ENDED \
                and now - s.state_since >= END_TIMEOUT:
            party.pending = None                  # nobody opened the next game: drop the switch
            self._home_unless_live()
            self._commit()
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
    def join(self, device_id, name, avatar=None, mode=FULL):
        """Become present. Phones call this on their own as soon as they have a profile (ADR
        0011: no Join ceremony); it is idempotent for a device that is already in, and a device
        that left comes back as the same member. `mode` is the service's word for how this
        device reaches the party; it is set when the member is created and kept."""
        if mode not in MODES:
            raise ValueError(f'unknown mode {mode!r}')
        self._timed()
        clean = clean_name(name)
        now = self.clock()
        m = self._member_of(device_id)
        if m is None:
            m = Member(device_id, self._unique(clean, None), now, clean_avatar(avatar), mode)
            self.party.members[m.id] = m
        else:
            if m.left:
                m.left = False
                m.name = self._unique(clean, m)
            if avatar is not None:
                m.avatar = clean_avatar(avatar)
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

    def rename(self, device_id, name, avatar=None):
        self._timed()
        m = self._require_member(device_id)
        m.name = self._unique(clean_name(name), m)
        if avatar is not None:
            m.avatar = clean_avatar(avatar)
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
        return self._open_session(host, self._game(game_id))

    def _game(self, game_id):
        game = self.games.get(game_id)
        if game is None:
            raise Refused('unknown_game', 'That game is not available here.')
        return game

    def _open_session(self, host, game):
        now = self.clock()
        s = GameSession(game, host.id, now)
        self.party.session = s
        if s.pregame:
            # the party goes to the game's page for its setup; nothing runs at the game yet
            s.state, s.state_since = SETUP, now
            self._navigate('game', s)
            self._commit()
            return s
        here = [m for m in self.party.members.values() if not m.left and self._here(m, now)]
        for i, m in enumerate(here):
            p = Participant(m.id, 'player' if i < game['max_players'] else 'spectator')
            s.participants[m.id] = p
        self._commit()
        return s

    # ---- pregame (AVR-129) ------------------------------------------------------------------------
    def _eligible(self, now):
        """Who must choose before the round can start: every member who is here now."""
        return [m for m in self.party.members.values() if not m.left and self._here(m, now)]

    def setup_status(self, s, now=None):
        """(players, spectators, waiting, blocker) for a session in setup. `waiting` are members
        who are here and have not chosen; `blocker` is why the host cannot start yet, or None."""
        now = self.clock() if now is None else now
        eligible = self._eligible(now)
        players = [m for m in eligible if s.choices.get(m.id) == 'player']
        spectators = [m for m in eligible if s.choices.get(m.id) == 'spectator']
        waiting = [m for m in eligible if m.id not in s.choices]
        blocker = None
        if waiting:
            names = ', '.join(m.name for m in waiting[:3]) + (' …' if len(waiting) > 3 else '')
            blocker = f'Waiting for {names} to choose Play or Watch.'
        elif len(players) < s.min_players:
            blocker = f'{s.min_players} players needed; {len(players)} chose to play.'
        elif len(players) > s.max_players:
            blocker = f'At most {s.max_players} can play; {len(players)} chose to play.'
        return players, spectators, waiting, blocker

    def choose(self, device_id, choice):
        """A member's own choice for the round being set up: 'player' or 'spectator'. Any member,
        any number of times, until the host starts. Roles never change during a round."""
        self._timed()
        m = self._require_member(device_id)
        if choice not in CHOICES:
            raise Refused('bad_choice', 'Choose Play or Watch.')
        s = self._live_session()
        if s is None:
            raise Refused('no_game', 'No game is being set up.')
        if s.state != SETUP:
            raise Refused('round_on', 'Roles change between rounds. You can choose again when '
                                      'the host sets up the next round.')
        m.last_seen = self.clock()
        if s.choices.get(m.id) != choice:
            s.choices[m.id] = choice
            self._commit()
        return s

    def start_round(self, device_id, if_version):
        """The host starts the round set up: the choices become the roster (players in join order,
        then spectators). Refused until every member who is here has chosen and the game's minimum
        (and maximum) holds. Returns the session, now 'launching'."""
        self._timed()
        self._require_host(device_id, if_version)
        s = self._live_session()
        if s is None or s.state != SETUP:
            raise Refused('no_setup', 'No round is being set up.')
        players, spectators, waiting, blocker = self.setup_status(s)
        if blocker:
            raise Refused('unresolved' if waiting else 'player_count', blocker)
        for m in players:
            s.participants[m.id] = Participant(m.id, 'player')
        for m in spectators:
            s.participants[m.id] = Participant(m.id, 'spectator')
        s.state, s.state_since = LAUNCHING, self.clock()
        self._commit()
        return s

    def launch_accepted(self, session_id):
        """The game confirmed the launch. Stale or unknown sessions are ignored (False)."""
        self._timed()
        s = self.party.session
        if s is None or s.id != session_id or s.state != LAUNCHING:
            return False
        s.state, s.state_since = ACTIVE, self.clock()
        if self.party.nav['session'] != s.id:  # a pregame session: the party is already there
            self._navigate('game', s)
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
        if s.state == SETUP:                  # nothing runs at the game: close it here
            self._close(s, 'ended_by_host', 'The host cancelled the round.')
            return s
        if s.state == LAUNCHING:
            self._close(s, 'launch_failed', 'Cancelled by the host.')
            return s
        s.state, s.state_since = ENDING, self.clock()
        self._home_unless_live()
        self._commit()
        return s

    def begin_switch(self, device_id, game_id, if_version):
        """Host moves the party from the game that is on to another one (or a fresh round of the
        same). Starts ending the current session and returns it; the service ends it at the game,
        then calls launch_pending(). Until then the old session is still live (ending), so nothing
        else can start, and `nav` stays where it is: followers go straight to the next game."""
        self._timed()
        self._require_host(device_id, if_version)
        game = self._game(game_id)
        s = self._live_session()
        if s is None:
            raise Refused('no_game', 'No game is on. Start one instead.')
        if s.state not in (ACTIVE, SETUP) or self.party.pending is not None:
            raise Refused('busy', 'The party is already changing games. Wait a moment.')
        self.party.pending = game['id']
        if s.state == SETUP:                  # nothing runs at the game: it is ended already
            s.game_confirmed_end = True
            self._close(s, 'ended_by_host')
            return s
        s.state, s.state_since = ENDING, self.clock()
        self._commit()
        return s

    def launch_pending(self):
        """After a switch's old session closed: open the next game's session (launching) for the
        current host, or return None when the switch stops here. It stops when the old game did
        not confirm its end (it may still be running), or when nobody is host any more; the party
        then goes home and says why."""
        self._timed()
        game_id, self.party.pending = self.party.pending, None
        old = self.party.session
        if game_id is None or self._live_session() is not None:
            return None
        host = self.party.members.get(self.party.host_id)
        if not old.game_confirmed_end or host is None or host.left:
            old.detail = ('The last game did not stop, so the next one did not start.'
                          if not old.game_confirmed_end
                          else 'Nobody is hosting, so the next game did not start.')
            self._home_unless_live()
            self._commit()
            return None
        s = self._open_session(host, self.games[game_id])
        s.replaced = old.id                   # a failed start now sends everyone home
        if self.party.nav['session'] != s.id:
            # AVR-223: followers were at the old game; `nav` moves straight to the next session
            # (location `setup` while it launches) instead of bouncing through Party Home
            self._navigate('game', s)
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

    def game_reported_end(self, session_id, outcome, result=None):
        """The game says its session is over ('completed' or 'abandoned'). The caller has already
        authenticated the report as coming from that game's server. Anything but the live, active
        session is refused, so an old report can never end (or resurrect) a newer session.

        `result` is the structured result the report carried, if any (ADR 0015). The end and the
        result are judged separately: an authentic report ends the session whatever its result
        looks like, and a result that is not acceptable is dropped (`s.result_refused` says why),
        never repaired. A session ends once, so it has at most one result."""
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
        if result is not None:
            self._accept_result(s, result)
        return s

    def _accept_result(self, s, reported):
        """THE boundary for game results (ADR 0015): the only place a result becomes the party's.
        It runs once per session, after the session closed, on a report already authenticated and
        bound to this session. An accepted result is kept on the session as the party's own
        record: the game's checked result plus what only the party knows (which member each
        participant was). History, stats and retention (AVR-71) start from this record; nothing
        is persisted here."""
        if s.outcome != 'completed':
            s.result_refused = 'not_completed'     # abandoned, or the host's end won the race
            return
        players = [p.id for p in s.participants.values() if p.role == 'player']
        try:
            checked = game_result.check(reported, s.game_id, players)
        except game_result.Refused as e:
            s.result_refused = str(e)
            return
        member_of = {p.id: p.member_id for p in s.participants.values()}
        record = {'schema': checked['schema'], 'session': s.id, 'game': checked['game'],
                  'outcome': s.outcome, 'mode': checked['mode'],
                  'standings': [dict(entry, member=member_of[entry['participant']])
                                for entry in checked['standings']]}
        if 'data' in checked:
            record['data_schema'], record['data'] = checked['data_schema'], checked['data']
        s.result = record

    def _close(self, s, outcome, detail=None):
        now = self.clock()
        s.state, s.state_since, s.outcome = ENDED, now, outcome
        if detail:
            s.detail = detail
        for member_id in s.participants:
            self.party.released_at[member_id] = now
        moved = outcome in ('ended_by_host', 'abandoned') or (outcome == 'launch_failed'
                                                              and (s.replaced or s.pregame))
        if moved and self.party.pending is None:
            self._home_unless_live()          # the host's end, or a failed switch: everyone home
        self._commit()

    def go_home(self, device_id, if_version):
        """Host: from a round's results back to Party Home, for everyone (ADR 0011). Returns the
        finished session, so the service can release the game's held results screen."""
        self._timed()
        self._require_host(device_id, if_version)
        if self.location()['at'] != 'results':
            raise Refused('not_results', 'The party is not on a results screen.')
        s = self.party.session
        self._navigate('home')
        self._commit()
        return s

    def location(self):
        """Where the whole party is: {'at': 'home'|'setup'|'game'|'results', 'game', 'session'}.
        It follows `nav` (committed moves only): a round being set up or starting is `setup`; a
        round on (or ending in a switch) is `game`; a round the game itself finished is
        `results` until the host moves on. An abandoned round (the game or its runtime gave up)
        has no results screen to hold: the party is home (AVR-223)."""
        n, s = self.party.nav, self.party.session
        if n['to'] != 'game' or s is None or s.id != n['session']:
            return {'at': 'home', 'game': None, 'session': None}
        at = {SETUP: 'setup', LAUNCHING: 'setup', ACTIVE: 'game', ENDING: 'game'}.get(s.state)
        if at is None:
            at = 'results' if s.outcome == 'completed' else 'home'
        if at == 'home':
            return {'at': 'home', 'game': None, 'session': None}
        return {'at': at, 'game': s.game_id, 'session': s.id}

    # ---- navigation (AVR-128) --------------------------------------------------------------------
    def _navigate(self, to, session=None):
        n = self.party.nav
        self.party.nav = {'seq': n['seq'] + 1, 'to': to,
                          'game': session.game_id if session else None,
                          'session': session.id if session else None,
                          'from': n['game'] if to == 'home' else None}

    def _home_unless_live(self):
        """Send `nav` home when it points at a game session that is no longer on."""
        n, s = self.party.nav, self._live_session()
        on = s is not None and s.id == n['session'] and s.state in (SETUP, LAUNCHING, ACTIVE)
        if n['to'] == 'game' and not on:
            self._navigate('home')

    def participant_for(self, device_id, game_id=None):
        """The caller's place in the active session (for a ticket), admitting a member who joined
        after the launch as a spectator. Returns (session, participant). A page that names its game
        gets nothing for another one: a direct or stale URL never joins, or starts, a party game."""
        self._timed()
        m = self._require_member(device_id)
        s = self._live_session()
        if s is not None and game_id is not None and game_id == s.game_id \
                and s.state in (SETUP, LAUNCHING):
            # the game's page waits for the host's start instead of joining a room on its own
            raise Refused('setup', 'The round is being set up.')
        if s is None or s.state != ACTIVE:
            raise Refused('no_game', 'No game is on.')
        if game_id is not None and game_id != s.game_id:
            raise Refused('no_game', 'The party is playing another game.')
        m.last_seen = self.clock()
        p = s.participants.get(m.id)
        if p is None:
            p = self._late_admit(m)
            self._commit()
        return s, p

    def is_host(self, session_id, participant_id):
        """Whether that participant of the active session is the party's host at this moment:
        True or False, or None when that session is not the one running (or has no such
        participant). For a game that is about to act on a ticket's host claim."""
        self._timed()
        s = self._live_session()
        if s is None or s.state != ACTIVE or s.id != session_id:
            return None
        p = next((p for p in s.participants.values() if p.id == participant_id), None)
        if p is None:
            return None
        return self.party.host_id is not None and p.member_id == self.party.host_id

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
        members = [{'id': m.id, 'name': m.name, 'avatar': m.avatar, 'mode': m.mode,
                    'presence': self.presence(m, now), 'host': m.id == party.host_id}
                   for m in party.members.values() if not m.left]
        s = party.session
        session = None
        if s is not None:
            mine = s.participants.get(me.id) if me else None
            session = {'id': s.id, 'game': s.game_id, 'state': s.state, 'outcome': s.outcome,
                       'detail': s.detail,
                       'players': sum(1 for p in s.participants.values() if p.role == 'player'),
                       'my_role': mine.role if mine else None}
            if s.state == SETUP:
                players, spectators, waiting, blocker = self.setup_status(s, now)
                session['setup'] = {
                    'min': s.min_players, 'max': s.max_players,
                    'choices': {mid: c for mid, c in s.choices.items()
                                if mid in party.members and not party.members[mid].left},
                    'players': len(players), 'spectators': len(spectators),
                    'waiting': [m.id for m in waiting],
                    'blocker': blocker,
                    'mine': s.choices.get(me.id) if me else None}
        return {'party': party.id, 'version': party.version,
                'state': s.state if s is not None and s.state != ENDED else 'lobby',
                'members': members, 'host': party.host_id,
                'me': ({'id': me.id, 'name': me.name, 'host': me.id == party.host_id,
                        'mode': me.mode}
                       if me else None),
                'session': session,
                'nav': dict(party.nav),
                'location': self.location(),
                'switching_to': party.pending,
                # the party's games, for every phone: Party Home must know which titles the host
                # starts for everyone. Authority is me.host, re-checked on every host action.
                'games': sorted(self.games)}
