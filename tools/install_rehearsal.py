#!/usr/bin/env python3
"""Rehearse installing an EXPERIMENTAL `.avrgame` package, in a disposable appliance root (AVR-676).

    python tools/install_rehearsal.py <file.avrgame> [--grant PERM ...] [--keep DIR] [--json]

Not a second installer. Every step runs the appliance's own code, `avrana.ops.install_game.main`
(validate, stage, write the install record, provision, publish the effective catalog, verify,
list, remove), against a scratch directory laid out like the appliance's paths
(/etc/avrana-party, /opt/avrana-games, /run/avrana-games, /var/lib/..., /etc/systemd/system). The
effects that need root or a live appliance are injected instead of performed, exactly as the
installer's own tests do:

- `systemctl` is recorded, never run (no unit is enabled, started or reloaded);
- file ownership is not changed, and the staged tree's owner is not checked (no root);
- Party Core is "not running", so `remove` sees no session (connection refused).

What it rehearses, each step checked against the scratch root and reported PASS or FAIL:

 1. `install --dry-run` says what it would do and writes nothing.
 2. `install` stages the tree, writes the record, key, registry entry and the instance drop-in, asks
    for the systemctl calls a real install makes (daemon-reload, the socket, a Party Core reload),
    and publishes a catalog with the package's row (catalog registration, the AVR-337 overlay).
 3. `verify` finds every staged file as recorded; `list --json` names the package.
 4. A second `install` of the same id is refused (upgrade is not implemented: AVR-58/AVR-60).
 5. A failed install is undone: on a fresh clean root, the first `systemctl` call fails after the
    files are written, and the root is back to exactly what it was before (the install ledger's
    rollback). Only that failure point is rehearsed; a failure while publishing the catalog is not.
 6. `remove` takes everything off again: the root is back to exactly what it was before (only the
    records and catalog directories stay, empty), and the catalog overlay no longer exists.

What it cannot reproduce is printed every run (see NOT_REPRODUCED). A PASS here is not install
acceptance on an appliance.

Exit 0 when every step passed, 1 when one failed, 2 on usage.
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from avrana.avrgame import installed                     # noqa: E402
from avrana.ops import install_game as ig                 # noqa: E402
from avrana.ops import provision_game as pg               # noqa: E402

ORIGIN = 'https://party.rehearsal.test'
HOST = 'party.rehearsal.test'
LOCK_NAME = 'install-game.lock'                          # outside the root: a real flock leaves the file
# Made by the first install and kept, empty, by remove (an appliance keeps them). Nothing else may stay.
KEPT_DIRS = ('etc/avrana-party/packages.d', 'var/lib/avrana-party/catalog')

NOT_REPRODUCED = (
    'root: nothing runs as root, files are not chowned, and the root-ownership checks of the staged tree, '
    'the games root, the records directory, the interpreter and the command are skipped (trusted_path)',
    'file modes and fsync: not checked on Windows',
    'systemd: no unit is enabled, started, reloaded or sandboxed (DynamicUser, the hardened template); '
    'the systemctl calls are recorded only',
    'the game process: it is not started from the installed tree through socket activation',
    'Party Core: none runs, so its reload, its reading of the registry and of the install record, '
    'and a refusal to remove during a session are not exercised; the install checks that Party Core '
    'reads the registry and records run only in the dry run, against a party-core.json written here',
    'a node-runtime package needs the node executable on this host, or the install is refused',
    'nginx: the effective catalog and /party/pkgart/ artwork are written but not served to a phone',
    'the appliance itself: real paths, the SD card, power loss mid-install, a second concurrent run',
)


def layout_args(root, lock):
    """The installer's hidden layout options, pointing at the scratch root."""
    r = Path(root)
    return ['--key-dir', str(r / 'etc/avrana-party/game-keys'), '--registry-dir', str(r / 'etc/avrana-party/games.d'),
            '--socket-dir', str(r / 'run/avrana-games'), '--state-dir', str(r / 'var/lib/avrana-games'),
            '--unit-dir', str(r / 'etc/systemd/system'), '--template-dir', str(REPO / 'deploy/games'),
            '--party-config', str(r / 'etc/avrana-party/party-core.json'),
            '--records-dir', str(r / 'etc/avrana-party/packages.d'), '--games-root', str(r / 'opt/avrana-games'),
            '--lock-file', str(lock), '--visible-root', '/opt/avrana-games',
            '--catalog-dir', str(r / 'var/lib/avrana-party/catalog'),
            '--catalog-base', str(r / 'var/www/avrana-party/web/current/catalog.json')]


def make_root(root):
    """An empty appliance: the directories install-game expects, the shared template units already
    installed, Party Core's configuration, and the release catalog nginx would otherwise serve."""
    r = Path(root)
    for d in ('etc/avrana-party/game-keys', 'etc/avrana-party/games.d', 'etc/systemd/system', 'run/avrana-games',
              'var/lib/avrana-games', 'opt/avrana-games', 'var/lib/avrana-party', 'var/www/avrana-party/web/current'):
        (r / d).mkdir(parents=True, exist_ok=True)
    for name in pg.TEMPLATES:
        shutil.copyfile(REPO / 'deploy/games' / name, r / 'etc/systemd/system' / name)
    (r / 'etc/avrana-party/party-core.json').write_text(json.dumps(
        {'origins': [ORIGIN], 'hosts': [HOST], 'registry': str(r / 'etc/avrana-party/games.d'),
         'packages': str(r / 'etc/avrana-party/packages.d')}, indent=2) + '\n', encoding='utf-8')
    shutil.copyfile(REPO / 'web/party/catalog.json', r / 'var/www/avrana-party/web/current/catalog.json')


def snapshot(root):
    """Every path under the root, with the digest of each file."""
    out = {}
    for p in sorted(Path(root).rglob('*')):
        rel = p.relative_to(root).as_posix()
        out[rel] = 'dir' if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def diff(before, after):
    added = sorted(set(after) - set(before))
    gone = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    return added, gone, changed


class Recorder:
    """`run` for the installer: records each argv; can fail the n-th systemctl call."""

    def __init__(self, fail_at=None, root=None):
        self.calls, self.fail_at, self.root, self.at_failure = [], fail_at, root, None

    def __call__(self, argv):
        self.calls.append([str(a) for a in argv])
        if self.fail_at is not None and len(self.calls) == self.fail_at:
            if self.root is not None:
                self.at_failure = snapshot(self.root)       # what the install had written by then
            raise subprocess.CalledProcessError(1, argv)


def no_party(target, timeout):
    """Party Core is not running on this scratch host: a status query is refused."""
    raise urllib.error.URLError(ConnectionRefusedError(111, 'Connection refused'))


def installer(argv, run):
    """Run install-game's own main with the scratch effects; returns (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = ig.main(argv, run=run, own=lambda target: None, is_root=True, opener=no_party, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def rehearse(package, grants=(), keep=None):
    """Run every step; returns a report dict."""
    package = str(Path(package).resolve())
    work = Path(keep) if keep else Path(tempfile.mkdtemp(prefix='avrana-rehearsal-'))
    work.mkdir(parents=True, exist_ok=True)
    steps = []
    report = {'package': package, 'root': str(work / 'root'), 'steps': steps, 'not_reproduced': list(NOT_REPRODUCED)}

    def step(name, ok, detail=''):
        steps.append({'step': name, 'result': 'PASS' if ok else 'FAIL', 'detail': detail})
        return ok

    saved = installed.EXPECTED_OWNER
    installed.EXPECTED_OWNER = None                      # scratch files belong to whoever runs this
    try:
        root, lock = work / 'root', work / LOCK_NAME
        make_root(root)
        base = layout_args(root, lock)
        grant = [x for g in grants for x in ('--grant', g)]
        clean = snapshot(root)

        # 1. dry run
        rec = Recorder()
        code, out, err = installer(['install', package, *grant, '--dry-run', *base], rec)
        step('install --dry-run writes nothing', code == 0 and snapshot(root) == clean and not rec.calls,
             (out or err).strip())
        if code != 0:
            return report

        # 2. install
        rec = Recorder()
        code, out, err = installer(['install', package, *grant, *base], rec)
        pid = out.split(':', 1)[0].strip() if code == 0 else None
        step('install', code == 0, (out or err).strip())
        if code != 0:
            return report
        report['id'], report['systemctl'] = pid, rec.calls
        added, _, _ = diff(clean, snapshot(root))
        rel = lambda *parts: '/'.join(parts)
        expect = {
            'install record': rel('etc/avrana-party/packages.d', f'{pid}.json'),
            'registry entry': rel('etc/avrana-party/games.d', f'{pid}.json'),
            'game key': rel('etc/avrana-party/game-keys', f'{pid}.key'),
            'staged tree': rel('opt/avrana-games', pid),
            'effective catalog': 'var/lib/avrana-party/catalog/catalog.json',
        }
        missing = [f'{k} ({v})' for k, v in expect.items() if v not in added]
        step('install wrote record, registry entry, key, staged tree and catalog overlay', not missing,
             'missing: ' + ', '.join(missing) if missing else f'{len(added)} paths added')
        overlay = root / expect['effective catalog']
        catalog = json.loads(overlay.read_text(encoding='utf-8')) if overlay.is_file() else {}
        row = next((g for g in catalog.get('games', []) if g.get('id') == pid), None)
        step('catalog registration: the effective catalog lists the package', row is not None,
             json.dumps({k: row.get(k) for k in ('id', 'name', 'kind', 'players')}) if row else 'no row')
        units = sorted(p for p in added if p.startswith('etc/systemd/system/'))
        report['units'] = units
        asked = [' '.join(c) for c in rec.calls]
        dropin, socket = f'etc/systemd/system/avrana-game@{pid}.service.d/', f'avrana-game@{pid}.socket'
        step('provisioning wrote the drop-in and asked for daemon-reload, the socket and a Party Core reload',
             any(u.startswith(dropin) for u in units)
             and any('systemctl' in a and 'daemon-reload' in a for a in asked)
             and any('enable' in a and socket in a for a in asked)
             and any('reload' in a and pg.PARTY_UNIT in a for a in asked),
             'units: ' + ', '.join(units) + '; asked: ' + '; '.join(asked))

        # 3. verify and list
        code, out, err = installer(['verify', pid, *base], Recorder())
        step('verify', code == 0, (out or err).strip())
        code, out, err = installer(['list', '--json', *base], Recorder())
        listed = json.loads(out).get('installed', []) if code == 0 else []
        step('list --json names the package', any(r.get('id') == pid for r in listed), f'{len(listed)} installed')

        # 4. a second install is refused (no upgrade path yet)
        before = snapshot(root)
        code, out, err = installer(['install', package, *grant, *base], Recorder())
        step('a second install of the same id is refused and changes nothing',
             code != 0 and 'already installed' in err and snapshot(root) == before, err.strip().splitlines()[-1] if err.strip() else out.strip())

        # 5. a failed install is rolled back (on a fresh clean root)
        broken, broken_lock = work / 'rollback-root', work / ('rollback-' + LOCK_NAME)
        make_root(broken)
        broken_clean = snapshot(broken)
        failing = Recorder(fail_at=1, root=broken)
        code, out, err = installer(['install', package, *grant, *layout_args(broken, broken_lock)], failing)
        added_b, gone_b, changed_b = diff(broken_clean, snapshot(broken))
        written = diff(broken_clean, failing.at_failure)[0] if failing.at_failure is not None else []
        # Not vacuous: the injected systemctl failure stopped it, after files had been written.
        step('a failed install is undone: the root is exactly as before',
             code != 0 and 'exited 1' in err and bool(written) and not (added_b or gone_b or changed_b),
             (err.strip().splitlines() or [''])[0] + f'; {len(written)} paths written before the failure'
             + (f'; left: {added_b + gone_b + changed_b}' if added_b or gone_b or changed_b else ''))

        # 6. remove
        rec = Recorder()
        code, out, err = installer(['remove', pid, *base], rec)
        added_r, gone_r, changed_r = diff(clean, snapshot(root))
        step('remove', code == 0, (out or err).strip())
        kept = [p for p in added_r if p in KEPT_DIRS and (root / p).is_dir() and not any((root / p).iterdir())]
        left = [p for p in added_r if p not in kept] + gone_r + changed_r
        step('after remove every file is as before install (no record, tree, key, units or overlay)',
             not left, f'left: {left}' if left else (f'empty directories kept: {", ".join(kept)}' if kept else ''))
        report['systemctl_remove'] = rec.calls
        return report
    finally:
        installed.EXPECTED_OWNER = saved
        report['ok'] = bool(steps) and all(s['result'] == 'PASS' for s in steps)
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
            report['root'] += ' (deleted)'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('package')
    ap.add_argument('--grant', action='append', default=[], metavar='PERM')
    ap.add_argument('--keep', metavar='DIR', help='rehearse in DIR and keep it (default: a temporary directory, deleted)')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)
    if not Path(a.package).is_file():
        print(f'install-rehearsal: no such file: {a.package}', file=sys.stderr)
        return 2
    report = rehearse(a.package, a.grant, a.keep)
    if a.json:
        json.dump(report, sys.stdout, indent=2)
        sys.stdout.write('\n')
    else:
        print(f'install rehearsal of {report["package"]} in {report["root"]}')
        for s in report['steps']:
            print(f'  {s["result"]}  {s["step"]}')
            if s['result'] == 'FAIL' and s['detail']:
                print('        ' + s['detail'].replace('\n', '\n        '))
        print('NOT reproduced here (an appliance install still needs these):')
        for item in report['not_reproduced']:
            print(f'  - {item}')
        print('OK: every step passed' if report['ok'] else 'FAILED')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
