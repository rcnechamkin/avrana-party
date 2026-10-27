"""The physical signal state (avrana.signal/v0): one of seven states from facts the box already has (AVR-87).

PROTOTYPE for docs/design/proposals/2026-10-26-physical-status-signals.md (owner decisions open). This is
the pure mapping the proposal's daemon would run every 2 s, and nothing else: no daemon, no driver, no LED,
no route and no status field. A driver renders a state and never decides one.

Seven states, one at a time, in priority order (proposal section 2): identify, recovery, updating,
attention, party, ready, booting. `unknown` facts map to attention, never to ready (AVR-31): a light never
calls an unchecked box healthy. Booting lasts at most BOOT_GRACE_S; after that a Party Core that still does
not answer is attention. Quiet hours dim steady states but never darken attention, recovery or updating,
and identify ignores them.
"""
SCHEMA = 'avrana.signal/v0'
STATES = ('identify', 'recovery', 'updating', 'attention', 'party', 'ready', 'booting')
IDENTIFY_S = 30.0
BOOT_GRACE_S = 180.0
NEVER_DARK = ('identify', 'recovery', 'updating', 'attention')


def derive(status, deploy=None, identify_until=None, now=0.0, up_since=0.0, recovery_image=False):
    """(state, reason) from an avrana.status/v0 document (or None when it could not be read), the deploy
    state ({'running': bool, 'unrecovered': bool} from `deploy.sh --status`), an owner identify request
    (until a monotonic time), the daemon's monotonic `now` and when it started."""
    deploy = deploy if isinstance(deploy, dict) else {}
    if identify_until is not None and now < identify_until:
        return 'identify', 'the owner asked which box this is'
    if recovery_image:
        return 'recovery', 'booted into the recovery image'
    if deploy.get('unrecovered'):
        return 'recovery', 'a deploy run died and was not recovered'
    if deploy.get('running'):
        return 'updating', 'an update is running'
    core = status.get('party_core') if isinstance(status, dict) else None
    if not isinstance(core, dict) or not core.get('ok'):
        if now - up_since < BOOT_GRACE_S:
            return 'booting', 'Party Core is not answering yet'
        return 'attention', 'Party Core is not answering'
    summary = status.get('summary')
    summary = summary if isinstance(summary, dict) else {}
    state = summary.get('state')
    if state != 'ok':
        reasons = summary.get('reasons')
        if state == 'degraded' and isinstance(reasons, list) and reasons:
            return 'attention', str(reasons[0])
        return 'attention', 'not everything could be checked' if state == 'unknown' else f'status is {state!r}'
    members = core.get('members')
    if isinstance(members, int) and not isinstance(members, bool) and members > 0:
        return 'party', 'a party is on'
    return 'ready', 'ready; nobody here yet'


def brightness(state, quiet):
    """The level a driver should use: 1.0, or dimmed in quiet hours (never dark for NEVER_DARK states)."""
    if not quiet or state == 'identify':
        return 1.0
    if state in NEVER_DARK:
        return 0.3
    return 0.1


def document(state, reason, since, quiet=False):
    """The /run/avrana/signal.json document a driver reads."""
    if state not in STATES:
        raise ValueError(f'unknown signal state {state!r}')
    return {'schema': SCHEMA, 'state': state, 'since': since, 'reason': reason, 'quiet': bool(quiet),
            'level': brightness(state, quiet)}
