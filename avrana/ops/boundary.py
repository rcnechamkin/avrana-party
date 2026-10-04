"""Does this host meet the service boundary of ADR 0016? Read-only.

    python3 -m avrana.ops.boundary                     # collect facts here (Linux, systemd) and judge
    python3 -m avrana.ops.boundary --facts FILE.json   # judge recorded facts (any platform)
    python3 -m avrana.ops.boundary --collect           # print the facts as JSON and judge nothing
    python3 -m avrana.ops.boundary --phase 1           # only the rules of migration phase 1

The boundary is contracts/service-boundary.v1.json: one identity per service (a static user for
Party Core, the arcade and the legacy games process; a systemd dynamic user for each native game),
a key store only Party Core can read with every other holder handed its own key as a systemd
credential, code no service can write, state owned by one service, and Unix sockets whose group
says who may connect.

`evaluate` is a pure function of facts and spec. `collect` only reads: `systemctl show`, `stat`,
the user and group databases and `ss`. Seeing another user's listening sockets and a game's
private state directory needs root, so run the collection with sudo once services no longer
share one user. Nothing is changed on the host, and
no key content is ever read: only the ownership and mode of key files.

Exit status: 0 when every rule of the requested phases is met, 1 otherwise, 2 for a usage error.
Stdlib only and free of avrana imports, so the file can be piped to a host's python3 as is.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SPEC_NAME = 'service-boundary.v1.json'
KNOWN_UNITS = {'avrana-party-core.service': 'party', 'avranaparty-games.service': 'legacy-games',
               'avranaparty-arcade.service': 'arcade'}
NATIVE_UNIT = re.compile(r'^avrana-game@([a-z][a-z0-9-]{0,39})\.service$')
KEY_DIR = '/etc/avrana-party/game-keys'
LOOPBACK = ('127.0.0.1', '::1', '[::1]')


def load_spec(path=None):
    path = path or Path(__file__).resolve().parents[2] / 'contracts' / SPEC_NAME
    return json.loads(Path(path).read_text(encoding='utf-8'))


# ---- judgement --------------------------------------------------------------------------------
def _mode(entry):
    return int(entry['mode'], 8)


def can_write(user, groups, entry):
    """Would this identity be allowed to write the file or directory described by `entry`?"""
    mode = _mode(entry)
    return bool((entry['owner'] == user and mode & 0o200)
                or (entry['group'] in groups and mode & 0o020) or mode & 0o002)


def evaluate(facts, spec, phases=(1, 2, 3)):
    """[{rule, phase, ok, subject, detail}] for every rule of ADR 0016 that applies."""
    out = []

    def rule(name, phase, subject, ok, detail=''):
        if phase in phases:
            out.append({'rule': name, 'phase': phase, 'ok': bool(ok), 'subject': subject,
                        'detail': '' if ok else detail})

    users, services = facts.get('users', {}), facts.get('services', [])
    party_user = spec['roles']['party']['user']
    front, games = spec['groups']['front'], spec['groups']['games']
    names = {'party': party_user, 'front': front['name'], 'games': games['name']}
    found = {x['path']: x for x in facts.get('sockets', [])}

    def socket_rule(kind, phase, subject, **fmt):
        want = {k: v.format(**names, **fmt) for k, v in spec['sockets'][kind].items()}
        got = found.get(want['path'])
        ok = got is not None and all(got[k] == want[k] for k in ('owner', 'group', 'mode'))
        rule(f'ipc.socket.{kind}', phase, subject, ok,
             f'{want["path"]}: ' + ('missing' if got is None else f'{got["owner"]}:{got["group"]} {got["mode"]}')
             + f', expected {want["owner"]}:{want["group"]} {want["mode"]}')
    by_user = {}
    for s in services:
        if not s.get('dynamic_user'):
            by_user.setdefault(s['user'], []).append(s['unit'])

    for s in services:
        unit, user, role = s['unit'], s['user'], s['role']
        slug = s.get('slug')
        declared = spec['units'].get(unit, {}).get('keys', [])
        dynamic = bool(s.get('dynamic_user'))
        if role == 'native-game':
            # the template instance is the identity: systemd allocates the uid, nothing names it
            groups = set(s.get('supplementary_groups', []))
            forbidden = sorted(groups & set(spec['forbidden_groups']))
            rule('identity.expected', 1, unit, dynamic,
                 f'runs as the static user {user}, expected DynamicUser=yes')
            rule('identity.distinct', 1, unit, dynamic, f'{user} is a shared static identity')
            rule('identity.unprivileged', 1, unit, not forbidden, f'privileged groups {forbidden}')
            who = None if dynamic else user
        else:
            expected = spec['roles'][role]['user']
            info = users.get(user, {})
            groups = set(info.get('groups', [])) | {user}
            rule('identity.expected', 1, unit, user == expected and not dynamic,
                 f'runs as {"a dynamic user" if dynamic else user}, expected {expected}')
            rule('identity.distinct', 1, unit, by_user.get(user) == [unit],
                 f'{user} also runs {", ".join(u for u in by_user.get(user, []) if u != unit)}')
            forbidden = sorted(groups & set(spec['forbidden_groups']))
            rule('identity.unprivileged', 1, unit,
                 not forbidden and info.get('uid') != 0 and info.get('shell') in spec['no_login_shells'],
                 f'{user}: uid {info.get("uid")}, shell {info.get("shell")}, privileged groups {forbidden}')
            who = user

        # phase 1: what it can touch
        writable = [c['path'] for c in s.get('code', []) if can_write(who, groups, c)]
        rule('code.readonly', 1, unit, not writable,
             f'{user or "the service"} can write {", ".join(writable)}')
        loose = [p['path'] for p in s.get('state', [])
                 if _mode(p) & 0o077 or (not dynamic and p['owner'] != user)]
        rule('state.owned', 1, unit, not loose,
             f'not private to the service with mode 0700: {", ".join(loose)}')
        rule('hardening.base', 1, unit,
             s.get('no_new_privileges') is True and s.get('protect_system') == 'strict',
             f'NoNewPrivileges={s.get("no_new_privileges")}, ProtectSystem={s.get("protect_system")}')

        # phase 1: which keys it is handed. Party Core owns the store and reads it directly;
        # every other holder gets exactly its own keys as credentials and no path to the store
        key_dir = spec['keys']['dir']
        creds = sorted(s.get('credentials', []))
        if role != 'party':
            want = ([f'{key_dir}/{slug}.key'] if role == 'native-game'
                    else sorted(f'{key_dir}/{k}.key' for k in declared))
            rule('keys.credentials', 1, unit, creds == want and not s.get('keys_env'),
                 f'loads {creds or "no credentials"}, expected {want}'
                 + (f'; reads the key directory by path ({s.get("keys_env")})' if s.get('keys_env') else ''))

        # phase 1: no listener beyond this machine
        exposed = [a for a in s.get('tcp', []) if a.rsplit(':', 1)[0] not in LOOPBACK]
        rule('ipc.loopback_only', 1, unit, not exposed, f'listens on {", ".join(exposed)}')

        # phase 2: a native game has one socket the front door and Party may use, and no IP
        if role == 'native-game':
            rule('identity.groups', 2, unit, s.get('supplementary_groups', []) == [games['name']],
                 f'supplementary groups {s.get("supplementary_groups", [])}, expected [{games["name"]}]')
            rule('ipc.no_ip', 2, unit,
                 not s.get('tcp') and s.get('address_families') == ['AF_UNIX'],
                 f'TCP listeners {s.get("tcp", [])}, address families {s.get("address_families")}')
            rule('hardening.native', 2, unit,
                 s.get('protect_home') in ('yes', True) and s.get('private_tmp') is True
                 and s.get('private_devices') is True,
                 f'ProtectHome={s.get("protect_home")}, PrivateTmp={s.get("private_tmp")}, '
                 f'PrivateDevices={s.get("private_devices")}')
            socket_rule('game', 2, unit, slug=slug)

        # phase 2: Party Core's game-facing endpoint and the group that gates game sockets.
        # Its public API stays on loopback TCP (ADR 0016), so no rule asks it to leave
        if role == 'party' and any(x['role'] == 'native-game' for x in services):
            socket_rule('party_internal', 2, unit)
            members = sorted(facts.get('groups', {}).get(front['name'], []))
            rule('groups.front', 2, front['name'], members == sorted(front['members']),
                 f'members {members}, expected {sorted(front["members"])}')

        # phase 3: the shared process is gone
        if role == 'legacy-games':
            rule('legacy.retired', 3, unit, False,
                 'the shared LAN Games process still runs; its games share one identity and one boundary')

    # phase 1: the key files themselves
    k, keys = spec['keys'], facts.get('keys', {})
    d = keys.get('dir')
    owner, group = k['owner'].format(**names), k['group'].format(**names)
    rule('keys.party_owned', 1, k['dir'],
         d is not None and (d['owner'], d['group'], d['mode']) == (owner, group, k['dir_mode'])
         and all((f['owner'], f['group'], f['mode']) == (owner, group, k['file_mode'])
                 for f in keys.get('files', [])),
         f'the key directory and every key must be {owner}:{group}, 0700 and 0600; found '
         + ('no directory' if d is None else f'{d["owner"]}:{d["group"]} {d["mode"]}')
         + ''.join(f'; {Path(f["path"]).name} {f["owner"]}:{f["group"]} {f["mode"]}'
                   for f in keys.get('files', [])))
    known = {s.get('slug') for s in services if s['role'] == 'native-game'}
    for s in services:
        known.update(spec['units'].get(s['unit'], {}).get('keys', []))
    stale = sorted(Path(f['path']).name for f in keys.get('files', [])
                   if Path(f['path']).name.removesuffix('.key') not in known)
    rule('keys.registered', 1, k['dir'], not stale, f'keys with no service: {", ".join(stale)}')
    return out


def report(results):
    lines = []
    for phase in sorted({r['phase'] for r in results}):
        rows = [r for r in results if r['phase'] == phase]
        met = sum(r['ok'] for r in rows)
        lines.append(f'Phase {phase}: {met}/{len(rows)} rules met')
        for r in rows:
            lines.append(f'  {"ok  " if r["ok"] else "FAIL"} {r["rule"]:<26} {r["subject"]}'
                         + (f'\n       {r["detail"]}' if r['detail'] else ''))
    return '\n'.join(lines)


# ---- collection (Linux with systemd; reads only) ------------------------------------------------
def _run(*argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def _stat(path):
    import grp
    import pwd
    st = os.stat(path)

    def name(db, key):
        try:
            return db(key)[0]
        except KeyError:
            return str(key)
    return {'path': str(path), 'owner': name(pwd.getpwuid, st.st_uid),
            'group': name(grp.getgrgid, st.st_gid), 'mode': format(st.st_mode & 0o7777, '04o')}


def _show(unit):
    props = {}
    for line in _run('systemctl', 'show', unit, '--no-pager').splitlines():
        key, _, value = line.partition('=')
        props[key] = value
    return props


def collect():
    import grp
    import pwd
    units = dict(KNOWN_UNITS)
    for line in _run('systemctl', 'list-units', 'avrana-game@*', '--all', '--no-legend', '--plain').splitlines():
        name = line.split()[0] if line.split() else ''
        if NATIVE_UNIT.match(name):
            units[name] = 'native-game'
    listening = {}                                   # pid -> ["addr:port"]
    for line in _run('ss', '-ltnpH').splitlines():
        parts = line.split()
        for pid in re.findall(r'pid=(\d+)', line):
            listening.setdefault(int(pid), []).append(parts[3])
    facts = {'users': {}, 'groups': {}, 'services': [], 'sockets': [],
             'keys': {'dir': None, 'files': []}}
    for unit, role in sorted(units.items()):
        p = _show(unit)
        if p.get('LoadState') != 'loaded':
            continue
        dynamic = p.get('DynamicUser') == 'yes'
        user = p.get('User') or ('' if dynamic else 'root')
        pids = set()
        cgroup = p.get('ControlGroup')
        if cgroup:
            try:
                pids = {int(x) for x in Path('/sys/fs/cgroup' + cgroup, 'cgroup.procs').read_text().split()}
            except (OSError, ValueError):
                pass
        code = {p.get('WorkingDirectory', '').lstrip('!-')}
        for argv in re.findall(r'argv\[\]=([^;]*);', p.get('ExecStart', '')):
            code.update(a for a in argv.split() if a.startswith('/'))
        state = [f'/var/lib/private/{d}' if dynamic else f'/var/lib/{d}'
                 for d in p.get('StateDirectory', '').split()]
        data = Path(p.get('WorkingDirectory', '').lstrip('!-'), 'data')
        if role == 'legacy-games' and data.is_dir():
            state.append(str(data))
        env = dict(e.split('=', 1) for e in p.get('Environment', '').split() if '=' in e)
        service = {
            'unit': unit, 'role': role, 'user': user, 'dynamic_user': dynamic,
            'supplementary_groups': sorted(p.get('SupplementaryGroups', '').split()),
            'no_new_privileges': p.get('NoNewPrivileges') == 'yes',
            'protect_system': p.get('ProtectSystem') or 'no', 'protect_home': p.get('ProtectHome') or 'no',
            'private_tmp': p.get('PrivateTmp') == 'yes', 'private_devices': p.get('PrivateDevices') == 'yes',
            'address_families': sorted(p.get('RestrictAddressFamilies', '').split()),
            'credentials': sorted(c.split(':', 1)[1] for c in p.get('LoadCredential', '').split() if ':' in c),
            'code': [_stat(c) for c in sorted(code) if c and os.path.exists(c)],
            'state': [_stat(s) for s in state if os.path.exists(s)],
            'tcp': sorted({a for pid in pids for a in listening.get(pid, [])}),
        }
        if env.get('AVRANA_PARTY_KEYS', '').startswith('/etc/'):
            service['keys_env'] = env['AVRANA_PARTY_KEYS']
        m = NATIVE_UNIT.match(unit)
        if m:
            service['slug'] = m[1]
        facts['services'].append(service)
        if dynamic:
            continue
        try:
            pw = pwd.getpwnam(user)
            facts['users'][user] = {'uid': pw.pw_uid, 'shell': pw.pw_shell,
                                    'groups': sorted({g.gr_name for g in grp.getgrall() if user in g.gr_mem}
                                                     | {grp.getgrgid(pw.pw_gid).gr_name})}
        except KeyError:
            facts['users'][user] = {'uid': None, 'shell': None, 'groups': []}
    try:
        facts['keys']['dir'] = _stat(KEY_DIR)
        facts['keys']['files'] = [_stat(f) for f in sorted(Path(KEY_DIR).glob('*.key'))]
    except OSError:
        pass                                         # unreadable to this user: reported as facts
    for name in ('avrana-front', 'avrana-games'):
        try:
            facts['groups'][name] = sorted(grp.getgrnam(name).gr_mem)
        except KeyError:
            pass
    for root in ('/run/avrana-games', '/run/avrana-party'):
        for sock in sorted(Path(root).rglob('*.sock')) if os.path.isdir(root) else []:
            facts['sockets'].append(_stat(sock))
    return facts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--facts', help='judge these recorded facts instead of this host')
    ap.add_argument('--collect', action='store_true', help='print this host\'s facts and stop')
    ap.add_argument('--phase', type=int, choices=(1, 2, 3), action='append',
                    help='only this migration phase (repeatable); default all')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    if args.facts:
        facts = json.loads(Path(args.facts).read_text(encoding='utf-8'))
    elif sys.platform.startswith('linux'):
        facts = collect()
    else:
        print('collecting facts needs Linux with systemd; pass --facts FILE', file=sys.stderr)
        return 2
    if args.collect:
        print(json.dumps(facts, indent=1, sort_keys=True))
        return 0
    results = evaluate(facts, load_spec(), tuple(args.phase or (1, 2, 3)))
    print(json.dumps(results, indent=1) if args.json else report(results))
    return 0 if all(r['ok'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
