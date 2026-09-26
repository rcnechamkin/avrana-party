"""Capability Engine v0: choose a presentation per seat from observed capabilities.

Four inputs, kept apart on purpose:
  game requirement      the contract's presentations, each with required/optional capabilities
  runtime capability    what the appliance's providers offer (appliance.runtime_capabilities)
  device capability     what the guest's browser was observed to do (avrana.capabilities/v0)
  seat                  the role this person has in this game (player or spectator)
and one output, the presentation strategy for that seat, with reasons.

Every seat is decided on its own capabilities only. A weak phone gets a fallback (watch, or an
explanation); it never changes what any other seat gets. Nothing here trusts a report for
security: a capability report only changes the reporting phone's own experience.

The browser runs the same seat evaluation (web/party/lib/evaluate.js). Both are checked against
contracts/vectors/evaluate.v0.json.
"""
STATUSES = ('yes', 'no', 'partial', 'unknown')
OUTCOMES = ('ready', 'limited', 'watch', 'unavailable')


def compile_presentations(contract, runtime_caps):
    """The contract's presentations annotated with what the appliance can serve (in order)."""
    have = set(runtime_caps)
    out = []
    for p in contract['presentations']:
        missing = [c for c in p['requires']['runtime'] if c not in have]
        entry = {'id': p['id'], 'method': p['method'], 'roles': list(p['roles']),
                 'available': not missing, 'runtimeMissing': missing,
                 'requires': {'device': list(p['requires']['device'])},
                 'optional': {'device': list(p['optional']['device']),
                              'runtime': [c for c in p['optional']['runtime'] if c not in have]}}
        if 'viewport' in p:
            entry['viewport'] = p['viewport']
        out.append(entry)
    return out


def _status(caps, name):
    entry = caps.get(name)
    if isinstance(entry, dict):
        entry = entry.get('status')
    return entry if entry in STATUSES else 'unknown'


def _try(presentations, caps, role):
    """First presentation for `role` with no required device capability observed as 'no'."""
    candidates = [p for p in presentations if p['available'] and role in p['roles']]
    best_missing = None
    for p in candidates:
        missing = [c for c in p['requires']['device'] if _status(caps, c) == 'no']
        if not missing:
            return p, candidates, []
        if best_missing is None or len(missing) < len(best_missing):
            best_missing = missing
    return None, candidates, best_missing or []


def evaluate_seat(game, caps, role='player'):
    """Decide one seat. `game` is a catalog entry (compiled presentations, fallback);
    `caps` maps capability name -> 'yes'|'no'|'partial'|'unknown' (or {'status': ...}); names not
    in the report are 'unknown'. A required capability observed as 'no' rules a presentation out;
    'unknown' (not observed) and 'partial' (works with a known limit) keep it, as 'limited'.
    An optional capability observed as 'no' is a degradation. Returns a JSON-safe dict."""
    if role not in ('player', 'spectator'):
        raise ValueError('role must be player or spectator')
    presentations = game['presentations']
    chosen, candidates, missing = _try(presentations, caps, role)
    seat_role = role
    outcome = None
    if chosen is None and role == 'player' and game.get('fallback') == 'spectate':
        watch, _, _ = _try(presentations, caps, 'spectator')
        if watch is not None:
            chosen, seat_role, outcome = watch, 'spectator', 'watch'
    if chosen is None:
        if candidates:
            blocked = 'device'
        elif any(role in p['roles'] for p in presentations):
            blocked = 'runtime'
        else:
            blocked = 'role'
        return {'role': role, 'outcome': 'unavailable', 'seatRole': None, 'presentation': None,
                'method': None, 'blockedBy': blocked, 'missing': sorted(missing), 'unverified': [],
                'partial': [], 'degraded': []}
    unverified = sorted(c for c in chosen['requires']['device'] if _status(caps, c) == 'unknown')
    partial = sorted(c for c in chosen['requires']['device'] if _status(caps, c) == 'partial')
    degraded = sorted(c for c in chosen['optional']['device'] if _status(caps, c) == 'no')
    if outcome is None:
        outcome = 'ready' if not (unverified or partial or degraded) else 'limited'
    return {'role': role, 'outcome': outcome, 'seatRole': seat_role, 'presentation': chosen['id'],
            'method': chosen['method'], 'blockedBy': None, 'missing': sorted(missing),
            'unverified': unverified, 'partial': partial, 'degraded': degraded}


def plan_party(game, seats):
    """Evaluate every seat independently. seats: [{'id', 'role', 'caps'}].

    'canStart' counts seats that got a player presentation; one seat's result never depends on
    another seat's capabilities (a tested property)."""
    results = [{'seat': s['id'], **evaluate_seat(game, s['caps'], s.get('role', 'player'))} for s in seats]
    players = sum(1 for r in results if r['seatRole'] == 'player')
    return {'game': game['id'], 'seats': results, 'players': players,
            'canStart': game['players']['min'] <= players}
