"""Party activity (avrana.activity/v0): structured, closed events, filtered per viewer (AVR-84).

PROTOTYPE for docs/design/proposals/2026-10-26-activity-and-notifications.md; nothing calls it yet. It is
pure state beside the room (avrana.party.messages), in the room's style: one feed per Party, in memory,
emptied with the Party, a `seq` cursor, no wall-clock time kept or sent.

Activity is not messaging. Every item is an event id from a closed list for its source plus a few
template fields; there is never free text, and the Party, not the source, renders the words. `source` is
whatever code path calls `publish` (Party Core passes 'party' or 'appliance'); a game reaches the feed only
through `publish_game`, which fixes the source to `game:<id>`, accepts only templates the game declared,
caps the priority at `notice`, addresses one member and is rate limited. Delivery is filtered per viewer
here, on the server: a member item reaches only that member, a host item only the current host, an owner
item only the owner surface, and a shared display only Party-wide items.

Items with an action ("choose Play or Watch") are deliberately not stored: they are derived from state each
time a view is built (the proposal's section 5), so a reconnecting phone can never replay a stale button.
"""
import collections

SCHEMA = 'avrana.activity/v0'
RING = 50                         # items kept per Party
GAME_EVERY = 5.0                  # s: at most one game notice per member this often
GAME_TEMPLATES_MAX = 8
FIELD_MAX = 80                    # characters in one template field value
PRIORITIES = ('info', 'notice', 'action', 'alert')
# The closed lists (proposal section 3). The seven room events are published here too.
PARTY_EVENTS = ('joined', 'returned', 'left', 'host', 'renamed', 'round_started', 'round_ended',
                'role_needed', 'round_ready', 'party_restarted')
APPLIANCE_EVENTS = ('storage_low', 'certificate_expiring', 'update_ready', 'service_degraded', 'time_unverified')
SOURCES = {'party': PARTY_EVENTS, 'appliance': APPLIANCE_EVENTS}
FIELDS = ('member', 'name', 'game', 'count', 'days', 'percent')
STORED = ('info', 'notice', 'alert')


class Refused(ValueError):
    """An item that the feed will not hold. Never shown to a phone: these are programming errors or a
    misbehaving game, counted by the caller."""


def _fields(fields):
    out = {}
    for key, value in (fields or {}).items():
        if key not in FIELDS:
            raise Refused(f'field {key!r} is not a template field')
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise Refused(f'field {key!r} must be text or a whole number')
        if isinstance(value, str) and len(value) > FIELD_MAX:
            raise Refused(f'field {key!r} is longer than {FIELD_MAX} characters')
        out[key] = value
    return out


def _audience(audience):
    if audience in ('party', 'host', 'owner'):
        return audience
    if isinstance(audience, str) and audience.startswith('member:') and audience[7:] not in ('', 'None'):
        return audience
    raise Refused(f'unknown audience {audience!r}')


class Feed:
    """One Party's activity. `clock` is Party Core's (monotonic)."""

    def __init__(self, party_id, clock):
        self.party = party_id
        self.clock = clock
        self.seq = 0
        self.items = collections.deque(maxlen=RING)
        self._game_last = {}                         # (game, member) -> when its last notice was published
        self.lost = 0                                # the highest seq that has left the ring

    def publish(self, source, event, audience='party', priority='info', fields=None, expires_in=None):
        """A platform item. Returns it. `source` is 'party' or 'appliance', chosen by the calling code."""
        if source not in SOURCES:
            raise Refused(f'unknown source {source!r}; games publish through publish_game')
        if event not in SOURCES[source]:
            raise Refused(f'{event!r} is not a {source} event')
        if priority not in STORED:
            raise Refused(f'priority {priority!r} is not stored (an action is derived from state, never kept)')
        if source == 'appliance' and _audience(audience) != 'owner':
            raise Refused('appliance events go to the owner only')
        return self._keep(source, event, _audience(audience), priority, _fields(fields), expires_in)

    def publish_game(self, game_id, templates, template_id, member_id):
        """A game's notice to one member, from a template it declared. Returns the item, or None when
        it was dropped by the rate limit (a game cannot flood a phone)."""
        if not isinstance(member_id, str) or not member_id:
            raise Refused(f'{game_id}: a notice needs a member id, not {member_id!r}')
        declared = [t.get('id') for t in (templates or [])[:GAME_TEMPLATES_MAX] if isinstance(t, dict)]
        if template_id not in declared:
            raise Refused(f'{game_id} did not declare the notice {template_id!r}')
        now = self.clock()
        last = self._game_last.get((game_id, member_id))
        if last is not None and now - last < GAME_EVERY:
            return None
        self._game_last[(game_id, member_id)] = now
        return self._keep(f'game:{game_id}', template_id, _audience(f'member:{member_id}'), 'notice', {}, 30.0)

    def _keep(self, source, event, audience, priority, fields, expires_in):
        now = self.clock()
        self.seq += 1
        item = {'schema': SCHEMA, 'seq': self.seq, 'party': self.party, 'source': source, 'event': event,
                'audience': audience, 'priority': priority, 'fields': fields, 'at': now,
                'expires': None if expires_in is None else now + float(expires_in)}
        if len(self.items) == self.items.maxlen:
            self.lost = max(self.lost, self.items[0]['seq'])
        self.items.append(item)
        return self._public(item, now)

    # ---- reading --------------------------------------------------------------------------------
    @staticmethod
    def sees(item, viewer):
        """Whether `viewer` ({member, host, owner, display}) receives `item`."""
        audience = item['audience']
        if viewer.get('display'):
            return audience == 'party'
        if audience == 'party':
            return True
        if audience == 'host':
            return bool(viewer.get('host'))
        if audience == 'owner':
            return bool(viewer.get('owner'))
        member = viewer.get('member')
        return isinstance(member, str) and bool(member) and audience == f'member:{member}'

    def after(self, party_id, cursor, viewer):
        """This viewer's items above `cursor`, in order, expired ones left out. A cursor from another
        Party reads from the start (as the room's does)."""
        cursor = cursor if party_id == self.party and isinstance(cursor, int) and cursor >= 0 else 0
        now = self.clock()
        return [self._public(i, now) for i in self.items
                if i['seq'] > cursor and (i['expires'] is None or now < i['expires']) and self.sees(i, viewer)]

    @staticmethod
    def _public(item, now):
        out = {k: v for k, v in item.items() if k not in ('at', 'expires')}
        out['age_ms'] = max(0, int((now - item['at']) * 1000))
        return out
