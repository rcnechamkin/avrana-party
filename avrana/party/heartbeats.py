"""Per-member heartbeat diagnostics (AVR-302), off unless party-core.json sets
`diagnostics.heartbeats: true`.

A member's poll of /party/api/state (and every other Party request) is their heartbeat
(core.touch). This records, per member, the gap between one heartbeat and the next, so a network
test on a real phone can tell a stall on the way (long gaps, late beats, rejoins) from a stall in
the box (`/party/api/status`, the Pi's own health). It observes only: nothing in Party Core reads
it back, and when it is off Party Core holds no instance and does nothing extra.

Read with GET /party/api/diagnostics/heartbeats from the box itself (loopback only). Members are
numbered in the order they were first seen; the document never carries a name, device id, member
id, address or anything else a person could be recognised by.
"""
import threading

# Upper edges of the gap histogram, s. The long poll waits up to 25 s, so a healthy phone's gaps
# sit under ~26 s; LIVE_WINDOW (45 s) is where a member starts to show as away.
BUCKETS = (5.0, 15.0, 30.0, 45.0, 90.0)
LATE_S = 30.0          # a gap longer than one long poll and its slack
MAX_MEMBERS = 64       # a party is never bigger; past this, new members are not tracked
ROUTE = '/party/api/diagnostics/heartbeats'


class Heartbeats:
    def __init__(self):
        self._lock = threading.Lock()
        self._members = {}             # member_id -> stats (insertion order = first seen)

    def _stats(self, member_id):
        s = self._members.get(member_id)
        if s is None and len(self._members) < MAX_MEMBERS:
            s = self._members[member_id] = {'beats': 0, 'last': None, 'gaps': [0] * (len(BUCKETS) + 1),
                                            'late': 0, 'longest_s': 0.0, 'rejoins': 0}
        return s

    def beat(self, member_id, now):
        with self._lock:
            s = self._stats(member_id)
            if s is None:
                return
            if s['last'] is not None:
                gap = max(0.0, now - s['last'])
                s['gaps'][sum(1 for edge in BUCKETS if gap > edge)] += 1
                s['late'] += gap > LATE_S
                s['longest_s'] = max(s['longest_s'], gap)
            s['beats'] += 1
            s['last'] = now

    def rejoin(self, member_id):
        """A member that already existed joined again (a reload, a new tab, a reconnect)."""
        with self._lock:
            s = self._stats(member_id)
            if s is not None:
                s['rejoins'] += 1

    def document(self, now):
        labels = [f'<= {edge:g} s' for edge in BUCKETS] + [f'> {BUCKETS[-1]:g} s']
        with self._lock:
            members = [{'member': i + 1, 'beats': s['beats'], 'late': s['late'], 'rejoins': s['rejoins'],
                        'longest_gap_s': round(s['longest_s'], 1),
                        'since_last_s': None if s['last'] is None else round(max(0.0, now - s['last']), 1),
                        'gaps': dict(zip(labels, s['gaps']))}
                       for i, s in enumerate(self._members.values())]
        return {'schema': 'avrana.heartbeats/v0', 'late_s': LATE_S, 'members': members}


def route(service):
    """('GET', ROUTE) -> handler, for make_server's extra_routes: peers on the box itself only (a
    request nginx forwarded from a phone carries X-Forwarded-For and is refused like any stranger)."""
    from avrana.party.service import _send

    def handler(h, device, body):
        proxied = any(h.headers.get(k) for k in ('X-Forwarded-For', 'X-Real-IP', 'Forwarded'))
        if proxied or not h._local_peer():
            return _send(h, 404, {'error': 'not_found'})
        return _send(h, 200, service.core.heartbeats.document(service.core.clock()))

    return {('GET', ROUTE): handler}
