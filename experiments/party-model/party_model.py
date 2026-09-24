"""Offline model of the Avrana Party lifecycle — an executable design sketch, NOT a service.

It tests the rules in docs/design/PARTY-LIFECYCLE.md and the identifier invariants in
docs/adr/0003-ids-and-keys.md against awkward sequences (host loss, reconnects, late joiners,
launch failures, duplicate votes, one profile on two devices) before any real party service is
written. No network, no persistence, no threads: every operation is a plain method call with an
injected clock. Nothing in production imports it. Timer values are PROPOSALS, not decisions.

Shape:
  Appliance  — devices and profiles (appliance-scoped) and the ONE active party
  Party      — lobby → launching → in_game → intermission → … → ended
  Presence   — connected / reconnecting (grace) / away / left; kind 'player' or 'screen'
  Seat       — occupied / disconnected (neutral input) / away (reserved); released = gone
"""
import hashlib
import itertools
import secrets
import unicodedata

RESERVED_NAMES = {'system', 'admin', 'host', 'avrana', 'moderator'}
NAME_MAX = 16
HOST_GRACE = 30.0          # s a disconnected host keeps the role
PRESENCE_GRACE = 60.0      # s "reconnecting" before "away"
SEAT_GRACE = 60.0          # s a disconnected seat stays "disconnected" before "away"
SEAT_RELEASE = 300.0       # s an away seat waits before auto-release (open_seat games only)
LAUNCH_TIMEOUT = 60.0      # s for a started game service to report ready
TABLE_ABANDON = 300.0      # s with no occupied seat before the session is abandoned
PARTY_IDLE = 3 * 3600.0    # s with nobody connected before the party ends


class Refused(Exception):
    """The server rejects the request (the real service would answer with an error)."""


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _new_id(kind):
    return f'{kind}-{secrets.token_hex(8)}'     # opaque; never derived from anything


def _name_key(name):
    """Comparison key for reserved/duplicate checks: casefolded letters and digits only."""
    return ''.join(ch for ch in name.casefold() if ch.isalnum())


def clean_name(raw):
    """Display-name rule (proposal): NFKC; drop control/format characters (zero-width, bidi
    overrides); collapse spaces; 1..NAME_MAX characters; letters from one script only (blocks
    look-alikes such as a Cyrillic 'у' inside 'System'); nothing that is or starts with a
    reserved word. Raises ValueError. Names stay display values: they never authorize."""
    text = unicodedata.normalize('NFKC', str(raw))
    text = ''.join(ch for ch in text if unicodedata.category(ch) not in ('Cc', 'Cf'))
    text = ' '.join(text.split())
    if not 1 <= len(text) <= NAME_MAX:
        raise ValueError('name must be 1-16 characters')
    scripts = {unicodedata.name(ch, 'UNKNOWN').split()[0] for ch in text if ch.isalpha()}
    if len(scripts & {'LATIN', 'CYRILLIC', 'GREEK'}) > 1:     # look-alike alphabets only;
        raise ValueError('mixed look-alike scripts')          # e.g. kana + kanji stay allowed
    key = _name_key(text)
    if not key or any(key.startswith(word) for word in RESERVED_NAMES):
        raise ValueError('reserved name')
    return text


class Presence:
    def __init__(self, presence_id, device_id, number, kind, now):
        self.id = presence_id
        self.device_id = device_id
        self.kind = kind                  # 'player' | 'screen' (a TV: never host, seat or voter)
        self.profile_id = None            # None = guest
        self.persona = f'Player {number}' if kind == 'player' else 'Screen'
        self.joined_at = now
        self.conns = []                   # open connection ids; the newest owns seat input
        self.disconnected_at = None
        self.left = False
        self.kicked = False

    @property
    def connected(self):
        return bool(self.conns)

    @property
    def eligible(self):                   # may be host, hold a seat, vote
        return self.kind == 'player' and not self.left

    def state(self, now):
        if self.left:
            return 'left'
        if self.connected:
            return 'connected'
        return 'reconnecting' if now - self.disconnected_at < PRESENCE_GRACE else 'away'


class Seat:
    def __init__(self, presence_id, slot, now, connected):
        self.id = _new_id('seat')
        self.presence_id = presence_id
        self.slot = slot                  # the game's controller/player number: a mapping target only
        self.game_key = secrets.token_urlsafe(16)   # secret; only this participant's client gets it
        self.state = 'occupied' if connected else 'disconnected'
        self.since = now

    @property
    def neutral_input(self):
        return self.state != 'occupied'


class GameSession:
    def __init__(self, manifest):
        self.id = _new_id('game_session')
        self.manifest = manifest          # dict: id, max_players, late_join, launch, open_seat
        self.seats = {}                   # presence_id -> Seat
        self.waiting = []                 # admitted at the next round (late_join=next_round)
        self.round = 1


class Appliance:
    """One appliance hosts ONE active party. Devices and profiles outlive parties."""

    def __init__(self, clock, succession='earliest_joined', rng=None):
        self.clock = clock
        self.succession = succession      # 'earliest_joined' | 'random'
        self.rng = rng
        self.devices = {}                 # token hash -> device_id
        self.profiles = {}                # profile_id -> {'trusted': set(device_id)}
        self.party = Party(self)
        self.past_parties = []

    def issue_device(self):
        """A browser with no valid cookie gets a new server-issued device token."""
        token = secrets.token_urlsafe(32)
        self.devices[_hash(token)] = _new_id('device')
        return token

    def device_of(self, token):
        device_id = self.devices.get(_hash(token))
        if device_id is None:
            raise Refused('unknown device token')   # fabricated tokens never create identity
        return device_id

    def connect(self, token, kind='player'):
        """Open the party page. After a party ended, the next connect starts a new party."""
        self.device_of(token)
        if self.party.state == 'ended':
            self.past_parties.append(self.party)
            self.party = Party(self)
        return self.party.connect(token, kind)

    def tick(self):
        self.party.tick()


class Party:
    def __init__(self, appliance):
        self.appliance = appliance
        self.clock = appliance.clock
        self._numbers = itertools.count(1)
        self._conn_ids = itertools.count(1)
        self.id = _new_id('party')
        self.state = 'lobby'              # lobby | launching | in_game | intermission | ended
        self.version = 0                  # bumps on every committed change (stale-request guard)
        self.presences = {}               # presence_id -> Presence (insertion order = join order)
        self.host_id = None
        self.nav_seq = 0
        self.nav_target = 'home'
        self.game = None
        self.launch = None                # {'id', 'manifest', 'started', 'from'} while launching
        self.last_seating = []            # presence_ids in slot order, carried to the next game
        self.table_empty_since = None
        self.idle_since = None
        self.votes = {}                   # round_id -> {'eligible', 'ballots', 'deadline', 'closed'}
        self.events = []                  # (ts, kind, data, provenance)

    # ---- helpers -------------------------------------------------------------------------
    def _now(self):
        return self.clock()

    def _event(self, kind, provenance='platform_observed', **data):
        self.events.append((self._now(), kind, data, provenance))

    def _system(self, text):
        self._event('system_message', text=text)    # a separate message type, never a player name

    def _commit(self):
        self.version += 1

    def _alive(self):
        if self.state == 'ended':
            raise Refused('party has ended')

    def _by_device(self, device_id):
        return next((p for p in self.presences.values() if p.device_id == device_id), None)

    def _presence_for(self, token):
        """Resolve a credential to a presence — the ONLY way a caller is identified."""
        self._alive()
        p = self._by_device(self.appliance.device_of(token))
        if p is None or p.left:
            raise Refused('device has no presence in this party')
        return p

    def _require_host(self, token, if_version=None):
        p = self._presence_for(token)
        if p.id != self.host_id or not p.connected:
            raise Refused('only the connected host may do that')
        if if_version is not None and if_version != self.version:
            raise Refused('stale request: the party changed')
        return p

    def _eligible_connected(self):
        return [p for p in self.presences.values() if p.eligible and p.connected]

    # ---- presence ----------------------------------------------------------------------------
    def connect(self, token, kind='player'):
        self._alive()
        device_id = self.appliance.device_of(token)
        p = self._by_device(device_id)
        conn = next(self._conn_ids)
        if p is None:
            p = Presence(_new_id('presence'), device_id,
                         next(self._numbers) if kind == 'player' else 0, kind, self._now())
            self.presences[p.id] = p
            p.conns.append(conn)
            self._event('presence_joined', presence=p.id, presence_kind=kind)
            if kind == 'player':
                self._system(f'{p.persona} joined the party.')
                if self.state == 'in_game':
                    self._admit_late(p)
        else:
            if p.kicked:
                raise Refused('removed from this party')
            was_away = not p.connected
            if p.left:
                p.left = False
                self._event('presence_rejoined', presence=p.id)
            p.conns.append(conn)
            if was_away:
                p.disconnected_at = None
                self._event('presence_reconnected', presence=p.id)
                self._return_to_game(p)
        if self.host_id is None and p.eligible:
            self._set_host(p.id, 'first eligible to connect')
        if p.eligible:
            self.idle_since = None                        # a TV alone doesn't keep a party alive
        self._commit()
        return p

    def drop(self, token, conn=None):
        """One tab/socket closed (sleep, reload, network loss). Default: the newest."""
        p = self._presence_for(token)
        if not p.conns:
            return
        p.conns.remove(conn if conn in p.conns else p.conns[-1])
        if not p.conns:
            p.disconnected_at = self._now()
            self._event('presence_disconnected', presence=p.id)
            seat = self.game.seats.get(p.id) if self.game else None
            if seat:
                seat.state, seat.since = 'disconnected', self._now()   # neutral input at once
            if not self._eligible_connected():
                self.idle_since = self._now()
        self._commit()

    def leave(self, token):
        """Explicit 'Leave party'. Seat released; if host, succession happens at once."""
        p = self._presence_for(token)
        self._depart(p)

    def kick(self, token, presence_id):
        """Host removes someone from the current party (how far a kick reaches is OPEN)."""
        self._require_host(token)
        target = self.presences.get(presence_id)
        if target is None or target.id == self.host_id:
            raise Refused('cannot kick that presence')
        target.kicked = True
        self._depart(target)

    def _depart(self, p):
        p.left, p.conns, p.disconnected_at = True, [], self._now()
        if self.game:
            self.game.seats.pop(p.id, None)
            if p.id in self.game.waiting:
                self.game.waiting.remove(p.id)
        self._event('presence_left', presence=p.id)
        if p.id == self.host_id:
            nxt = self._pick_successor()
            self._set_host(nxt.id if nxt else None, 'host left')
        if not self._eligible_connected():
            self.idle_since = self._now()
        self._commit()

    def rename(self, token, name):
        """Set a persona. Duplicates get ' 2', ' 3'… so host menus never show two identical names."""
        p = self._presence_for(token)
        try:
            clean = clean_name(name)
        except ValueError as e:
            raise Refused(str(e))
        taken = {_name_key(o.persona) for o in self.presences.values() if o is not p and not o.left}
        final, n = clean, 2
        while _name_key(final) in taken:
            final = f'{clean[:NAME_MAX - len(str(n)) - 1]} {n}'
            n += 1
        p.persona = final                                 # display value: authorizes nothing
        self._commit()
        return p

    # ---- profiles (only what "same profile on two devices" needs) -----------------------------
    def create_profile(self, token):
        """'Save Player': the guest becomes a saved profile; its records link, not copy."""
        p = self._presence_for(token)
        if p.profile_id or p.kind != 'player':
            raise Refused('cannot save this presence')
        profile_id = _new_id('profile')
        self.appliance.profiles[profile_id] = {'trusted': {p.device_id}}
        p.profile_id = profile_id
        self._event('profile_saved', presence=p.id, profile=profile_id)
        self._commit()
        return profile_id

    def claim_profile(self, token, profile_id):
        """Pick a saved profile from 'Welcome back'. Only a trusted device may take it over."""
        self._alive()
        device_id = self.appliance.device_of(token)
        prof = self.appliance.profiles.get(profile_id)
        if prof is None or device_id not in prof['trusted']:
            raise Refused('this device is not trusted for that profile (PIN flow not modelled)')
        owner = next((p for p in self.presences.values()
                      if p.profile_id == profile_id and not p.left), None)
        mine = self._by_device(device_id)
        if owner is not None and owner is mine:
            return self.connect(token)                   # same phone: just a reconnect/new tab
        if owner and mine:
            raise Refused('this device already has another presence in the party')
        if owner is None:
            mine = self.connect(token)                   # new, rejoining or extra tab
            mine.profile_id = profile_id
            self._commit()
            return mine
        # Same person, new phone: the presence moves; the old device's sockets are closed.
        owner.device_id = device_id
        owner.conns = [next(self._conn_ids)]
        owner.disconnected_at = None
        seat = self.game.seats.get(owner.id) if self.game else None
        if seat:
            seat.state, seat.since = 'occupied', self._now()
            seat.game_key = secrets.token_urlsafe(16)    # the old phone's key dies
        self._event('presence_moved_device', presence=owner.id)
        if self.host_id is None:
            self._set_host(owner.id, 'first eligible to connect')
        self.idle_since = None
        self._commit()
        return owner

    # ---- host ------------------------------------------------------------------------------------
    def _set_host(self, presence_id, why):
        self.host_id = presence_id
        self._event('host_changed', presence=presence_id, reason=why)
        if presence_id:
            self._system(f'{self.presences[presence_id].persona} is now Host.')

    def transfer_host(self, token, to_presence_id):
        self._require_host(token)
        target = self.presences.get(to_presence_id)
        if target is None or not target.eligible or not target.connected:
            raise Refused('can only hand host to a connected player')
        self._set_host(target.id, 'transferred')
        self._commit()

    def _pick_successor(self):
        candidates = [p for p in self._eligible_connected() if p.id != self.host_id]
        if not candidates:
            return None
        rng = self.appliance.rng
        if self.appliance.succession == 'random' and rng is not None:
            return rng.choice(candidates)
        return candidates[0]                              # earliest joined, connected, eligible

    # ---- time ---------------------------------------------------------------------------------------
    def tick(self):
        """Apply timers. The real service would run this from a scheduler."""
        if self.state == 'ended':
            return
        now = self._now()
        host = self.presences.get(self.host_id)
        if host and not host.connected and now - host.disconnected_at >= HOST_GRACE:
            nxt = self._pick_successor()
            self._set_host(nxt.id if nxt else None, 'previous host timed out')
        if self.state == 'launching' and now - self.launch['started'] >= LAUNCH_TIMEOUT:
            self.game_failed(self.launch['id'], 'timed out')
        if self.game:
            for pid, seat in list(self.game.seats.items()):
                if seat.state == 'disconnected' and now - seat.since >= SEAT_GRACE:
                    seat.state, seat.since = 'away', now  # still reserved; the game may autopilot
                elif (seat.state == 'away' and self.game.manifest.get('open_seat')
                      and now - seat.since >= SEAT_RELEASE):
                    del self.game.seats[pid]
                    self._event('seat_released', presence=pid, reason='away too long')
            occupied = any(s.state == 'occupied' for s in self.game.seats.values())
            if occupied:
                self.table_empty_since = None
            elif self.table_empty_since is None:
                self.table_empty_since = now
            elif now - self.table_empty_since >= TABLE_ABANDON:
                self._end_session('abandoned')
        for r in self.votes.values():
            if not r['closed'] and now >= r['deadline']:
                r['closed'] = True
        if self.idle_since is not None and now - self.idle_since >= PARTY_IDLE:
            self._end_party('idle')

    # ---- games, launch and navigation --------------------------------------------------------
    def select_game(self, token, manifest, if_version=None):
        """Host picks a game. Emulated/service games launch first; nav moves only when ready."""
        self._require_host(token, if_version)
        if self.state == 'launching':
            raise Refused(f"starting {self.launch['manifest']['id']}; cancel it first")
        if self.state == 'in_game':
            self._end_session('switched')                # end A before launching B
        self.launch = {'id': _new_id('launch'), 'manifest': manifest, 'started': self._now(),
                       'from': self.state}
        self.state = 'launching'
        self._event('launch_started', game=manifest['id'])
        self._commit()
        launch_id = self.launch['id']
        if manifest.get('launch', 'always_on') == 'always_on':
            self.game_ready(launch_id)
        return launch_id

    def game_ready(self, launch_id):
        """The launcher reports the game service is up. Deal seats and move everyone there."""
        if self.state != 'launching' or self.launch['id'] != launch_id:
            return False                                  # stale/cancelled launch: ignore
        manifest = self.launch['manifest']
        self.launch = None
        self.game = GameSession(manifest)
        now = self._now()
        order = [pid for pid in self.last_seating if pid in self.presences]
        order += [pid for pid in self.presences if pid not in order]
        dealt = [pid for pid in order
                 if self.presences[pid].eligible
                 and self.presences[pid].state(now) in ('connected', 'reconnecting')]
        for slot, pid in enumerate(dealt[:manifest['max_players']], start=1):
            p = self.presences[pid]
            seat = Seat(pid, slot, now, p.connected)
            if not p.connected:
                seat.since = p.disconnected_at        # grace counts from when the phone dropped
            self.game.seats[pid] = seat
        self.state = 'in_game'
        self.table_empty_since = None
        self.nav_seq += 1
        self.nav_target = manifest['id']
        self._event('session_started', session=self.game.id, game=manifest['id'])
        self._commit()
        return True

    def game_failed(self, launch_id, reason):
        """The service could not start (power gate, port busy, timeout). nav never moved."""
        if self.state != 'launching' or self.launch['id'] != launch_id:
            return False
        game_id = self.launch['manifest']['id']
        self.state = self.launch['from'] if self.launch['from'] != 'in_game' else 'intermission'
        self.launch = None
        self._event('launch_failed', game=game_id, reason=reason)
        self._system(f'{game_id} could not start ({reason}).')
        self._commit()
        return True

    def cancel_launch(self, token):
        self._require_host(token)
        if self.state != 'launching':
            raise Refused('nothing is starting')
        self.game_failed(self.launch['id'], 'cancelled by host')

    def _end_session(self, outcome):
        seats = sorted(self.game.seats.values(), key=lambda s: s.slot)
        self.last_seating = [s.presence_id for s in seats]
        self._event('session_ended', session=self.game.id, outcome=outcome)
        self.game = None
        self.state = 'intermission'
        self.nav_seq += 1
        self.nav_target = 'home'
        self._commit()

    def end_game(self, token, outcome='completed'):
        self._require_host(token)
        if self.state != 'in_game':
            raise Refused('no game running')
        self._end_session(outcome)

    def game_crashed(self):
        """Reported by the launcher; back home with the seating kept. Retry is the host's call."""
        if self.state == 'in_game':
            self._end_session('crashed')

    def _free_slots(self):
        used = {s.slot for s in self.game.seats.values()}
        return [n for n in range(1, self.game.manifest['max_players'] + 1) if n not in used]

    def _seat(self, presence_id):
        p = self.presences[presence_id]
        seat = Seat(presence_id, self._free_slots()[0], self._now(), p.connected)
        if not p.connected:
            seat.since = p.disconnected_at
        self.game.seats[presence_id] = seat              # a refill is always a NEW seat and key
        self._event('seat_joined', session=self.game.id, presence=presence_id, slot=seat.slot)

    def _admit_late(self, p):
        """Late joiner: spectator by default; the game's manifest may opt into more."""
        policy = self.game.manifest.get('late_join', 'spectator_only')
        if not p.eligible:
            return
        if policy == 'supported' and self._free_slots():
            self._seat(p.id)
        elif policy == 'next_round' and p.id not in self.game.waiting:
            self.game.waiting.append(p.id)

    def _return_to_game(self, p):
        if not self.game:
            return
        seat = self.game.seats.get(p.id)
        if seat:
            seat.state, seat.since = 'occupied', self._now()   # reclaim: same seat, same slot
        elif p.id not in self.game.waiting:
            self._admit_late(p)                         # seatless return = late-joiner rules

    def next_round(self, token):
        self._require_host(token)
        if self.state != 'in_game':
            raise Refused('no game running')
        self.game.round += 1
        while self.game.waiting and self._free_slots():
            pid = self.game.waiting.pop(0)
            if self.presences[pid].eligible:
                self._seat(pid)
        self._commit()

    def promote_spectator(self, token, presence_id):
        """Host moves a spectator toward a seat, within what the game's policy allows."""
        self._require_host(token)
        p = self.presences.get(presence_id)
        if self.state != 'in_game' or p is None or not p.eligible:
            raise Refused('nothing to promote into')
        if presence_id in self.game.seats:
            raise Refused('already seated')
        policy = self.game.manifest.get('late_join', 'spectator_only')
        if policy == 'spectator_only':
            raise Refused('this game only admits players between games')
        if policy == 'next_round':
            if presence_id not in self.game.waiting:
                self.game.waiting.append(presence_id)
            self._commit()
            return 'queued'
        if not self._free_slots():
            raise Refused('no free seat')
        self._seat(presence_id)
        self._commit()
        return 'seated'

    def remove_seat(self, token, presence_id):
        """Host frees a seat (e.g. someone gone for good). The person becomes a spectator."""
        self._require_host(token)
        if not self.game or self.game.seats.pop(presence_id, None) is None:
            raise Refused('no such seat')
        self._event('seat_released', presence=presence_id, reason='host')
        self._commit()

    def what_is_my_party_doing(self, token):
        """A phone waking from sleep asks this and navigates accordingly (idempotent)."""
        p = self._presence_for(token)
        seat = self.game.seats.get(p.id) if self.game else None
        return {'party_id': self.id, 'state': self.state, 'nav_seq': self.nav_seq,
                'target': self.nav_target, 'is_host': p.id == self.host_id,
                'seat_slot': seat.slot if seat else None,
                'input_owner': seat is not None and bool(p.conns),
                'spectator': self.state == 'in_game' and seat is None}

    def input_connection(self, presence_id):
        """Which of a presence's tabs drives its seat: the newest open one."""
        p = self.presences[presence_id]
        return p.conns[-1] if p.conns else None

    # ---- voting ------------------------------------------------------------------------------------
    def open_vote(self, token, round_id, seconds=60, spectators_vote=False):
        self._require_host(token)
        r = self.votes.get(round_id)
        if r and not r['closed']:
            raise Refused('that vote is still open')
        eligible = {p.id for p in self._eligible_connected()
                    if spectators_vote or not self.game or p.id in self.game.seats}
        self.votes[round_id] = {'eligible': eligible, 'ballots': {}, 'closed': False,
                                'deadline': self._now() + seconds}
        self._commit()

    def vote(self, token, round_id, choice):
        p = self._presence_for(token)
        r = self.votes.get(round_id)
        if r is None or r['closed'] or p.id not in r['eligible']:
            raise Refused('not eligible for this vote')
        r['ballots'][p.id] = choice                    # keyed per presence: a revote replaces
        self._commit()

    def tally(self, round_id):
        counts = {}
        for choice in self.votes[round_id]['ballots'].values():
            counts[choice] = counts.get(choice, 0) + 1
        return counts

    def vote_complete(self, round_id):
        """Done at the deadline, or early once every eligible voter still present has voted."""
        r = self.votes[round_id]
        present = {pid for pid in r['eligible'] if self.presences[pid].connected}
        return r['closed'] or set(r['ballots']) >= present

    # ---- end -------------------------------------------------------------------------------------------
    def end_party(self, token):
        self._require_host(token)
        self._end_party('host ended the party')

    def _end_party(self, why):
        if self.game:
            self._end_session('abandoned')
        self.launch = None
        self.state = 'ended'
        self._event('party_ended', reason=why)
        self.version += 1
