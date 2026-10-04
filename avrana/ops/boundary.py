"""Does this host meet the service boundary of ADR 0016? Read-only.

    python3 -m avrana.ops.boundary                     # collect facts here (Linux, systemd) and judge
    python3 -m avrana.ops.boundary --facts FILE.json   # judge recorded facts (any platform)
    python3 -m avrana.ops.boundary --collect           # print the facts as JSON and judge nothing
    python3 -m avrana.ops.boundary --phase 1           # only the rules of migration phase 1

The boundary is contracts/service-boundary.v1.json: one Unix identity per service, keys on disk
for root only and handed to a service as a systemd credential, code no service can write, state
owned by one service, and Unix sockets whose ownership says who may connect.

`evaluate` is a pure function of facts and spec. `collect` only reads: `systemctl show`, `stat`,
the user database and `ss`. Seeing another user's listening sockets needs root, so run the
collection with sudo once services no longer share one user. Nothing is changed on the host, and
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
    front = spec['front_door_group']
    by_user = {}
    for s in services:
        by_user.setdefault(s['user'], []).append(s['unit'])

    for s in services:
        unit, user, role = s['unit'], s['user'], s['role']
        slug = s.get('slug')
        declared = spec['units'].get(unit, {}).get('keys', [])
        expected = spec['roles'][role]['user'].format(slug=slug)
        info = users.get(user, {})
        groups = set(info.get('groups', [])) | {user}

        # phase 1: who the service is
        rule('identity.expected', 1, unit, user == expected, f'runs as {user}, expected {expected}')
        rule('identity.distinct', 1, unit, by_user[user] == [unit],
             f'{user} also runs {", ".join(u for u in by_user[user] if u != unit)}')
        forbidden = sorted(groups & set(spec['forbidden_groups']))
        rule('identity.unprivileged', 1, unit,
             not forbidden and info.get('uid') != 0 and info.get('shell') in spec['no_login_shells'],
             f'{user}: uid {info.get("uid")}, shell {info.get("shell")}, privileged groups {forbidden}')

        # phase 1: what it can touch
        writable = [c['path'] for c in s.get('code', []) if can_write(user, groups, c)]
        rule('code.readonly', 1, unit, not writable, f'{user} can write {", ".join(writable)}')
        loose = [p['path'] for p in s.get('state', []) if p['owner'] != user or _mode(p) & 0o077]
        rule('state.owned', 1, unit, not loose,
             f'not owned by {user} with mode 0700: {", ".join(loose)}')
        rule('hardening.base', 1, unit,
             s.get('no_new_privileges') is True and s.get('protect_system') == 'strict',
             f'NoNewPrivileges={s.get("no_new_privileges")}, ProtectSystem={s.get("protect_system")}')

        # phase 1: which keys it is handed
        key_dir = spec['keys']['dir']
        creds = sorted(s.get('credentials', []))
        if role == 'party':
            want = [key_dir]
        elif role == 'native-game':
            want = [f'{key_dir}/{slug}.key']
        else:
            want = sorted(f'{key_dir}/{k}.key' for k in declared)
        rule('keys.credentials', 1, unit, creds == want and not s.get('keys_env'),
             f'loads {creds or "no credentials"}, expected {want}'
             + (f'; reads the key directory by path ({s.get("keys_env")})' if s.get('keys_env') else ''))

        # phase 1: no listener beyond this machine
        exposed = [a for a in s.get('tcp', []) if a.rsplit(':', 1)[0] not in LOOPBACK]
        rule('ipc.loopback_only', 1, unit, not exposed, f'listens on {", ".join(exposed)}')

        # phase 2: a native game speaks over its two sockets and nothing else
        if role == 'native-game':
            rule('ipc.no_ip', 2, unit,
                 not s.get('tcp') and s.get('address_families') == ['AF_UNIX'],
                 f'TCP listeners {s.get("tcp", [])}, address families {s.get("address_families")}')
            rule('hardening.native', 2, unit,
                 s.get('protect_home') in ('yes', True) and s.get('private_tmp') is True
                 and s.get('private_devices') is True,
                 f'ProtectHome={s.get("protect_home")}, PrivateTmp={s.get("private_tmp")}, '
                 f'PrivateDevices={s.get("private_devices")}')
            names = {'party': party_user, 'game': user, 'front': front}
            found = {x['path']: x for x in facts.get('sockets', [])}
            for kind in ('game_control', 'game_public', 'party_report'):
                want_s = {k: v.format(slug=slug, **names) for k, v in spec['sockets'][kind].items()}
                got = found.get(want_s['path'])
                ok = got is not None and all(got[k] == want_s[k] for k in ('owner', 'group', 'mode'))
                rule(f'ipc.socket.{kind}', 2, unit, ok,
                     f'{want_s["path"]}: ' + ('missing' if got is None else
                                              f'{got["owner"]}:{got["group"]} {got["mode"]}')
                     + f', expected {want_s["owner"]}:{want_s["group"]} {want_s["mode"]}')

        # phase 3: nothing rests on loopback
        if role == 'party':
            rule('ipc.party_off_tcp', 3, unit, not s.get('tcp'),
                 f'Party Core still listens on {", ".join(s.get("tcp", []))}')
            want_s = {k: v.format(party=party_user, front=front) for k, v in spec['sockets']['party_api'].items()}
            got = {x['path']: x for x in facts.get('sockets', [])}.get(want_s['path'])
            rule('ipc.socket.party_api', 3, unit,
                 got is not None and all(got[k] == want_s[k] for k in ('owner', 'group', 'mode')),
                 f'{want_s["path"]} missing or not {want_s["owner"]}:{want_s["group"]} {want_s["mode"]}')
        if role == 'legacy-games':
            rule('legacy.retired', 3, unit, False,
                 'the shared LAN Games process still runs; its games share one identity and one boundary')

    # phase 1: the key files themselves
    k, keys = spec['keys'], facts.get('keys', {})
    d = keys.get('dir')
    rule('keys.root_only', 1, k['dir'],
         d is not None and (d['owner'], d['group'], d['mode']) == (k['owner'], k['group'], k['dir_mode'])
         and all((f['owner'], f['group'], f['mode']) == (k['owner'], k['group'], k['file_mode'])
                 for f in keys.get('files', [])),
         'the key directory and every key must be root:root, 0700 and 0600; found '
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
    facts = {'users': {}, 'services': [], 'sockets': [], 'keys': {'dir': None, 'files': []}}
    for unit, role in sorted(units.items()):
        p = _show(unit)
        if p.get('LoadState') != 'loaded':
            continue
        user = p.get('User') or 'root'
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
        state = [f'/var/lib/{d}' for d in p.get('StateDirectory', '').split()]
        data = Path(p.get('WorkingDirectory', '').lstrip('!-'), 'data')
        if role == 'legacy-games' and data.is_dir():
            state.append(str(data))
        env = dict(e.split('=', 1) for e in p.get('Environment', '').split() if '=' in e)
        service = {
            'unit': unit, 'role': role, 'user': user,
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
    for root in ('/run/avrana',):
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
