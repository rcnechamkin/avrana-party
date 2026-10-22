#!/usr/bin/env python3
"""One verdict for the CI lanes a pull request needs (AVR-305).

    python3 tools/ci_verdict.py scope   --base SHA --head SHA            # prints platform=true|false
    python3 tools/ci_verdict.py verdict --base SHA --head SHA \
        --offline R --cross-repo R --trust R --native-game R              # exit 1 with reasons

R is one of success, failure, cancelled, skipped, not-run (an empty string counts as not-run).
`.github/workflows/ci-verdict.yml` runs this in its final job. The decision is a pure function
(`decide`); only `changed_paths` touches git. Stdlib only; no network.
"""
import argparse
import os
import subprocess
import sys

SUCCESS, FAILURE, CANCELLED, SKIPPED, NOT_RUN = 'success', 'failure', 'cancelled', 'skipped', 'not-run'
RESULTS = (SUCCESS, FAILURE, CANCELLED, SKIPPED, NOT_RUN)

# The paths whose change makes the systemd lanes of `Service trust proof` apply. This is the
# `paths:` filter that used to gate .github/workflows/service-trust-proof.yml on pull requests,
# copied entry for entry (it is a superset of the five areas named in AVR-305: avrana/,
# contracts/, deploy/, ops/provision-game, experiments/). A trailing `/**` means "anything below".
# tests/unit/test_ci_verdict.py compares this list with the workflow's own filter if it still has one.
PLATFORM_PATHS = (
    'avrana/**',
    'contracts/**',
    'deploy/**',
    'ops/provision-game',
    'ops/prepare-native-games',
    'ops/install-game',
    'ops/install-node-runtime',
    'tests/fixtures/node-game/**',
    'ops/catalog-overlay',
    'ops/install-party-web.sh',
    'experiments/**',
    'tests/package/**',
    'avrana-party.nginx',
    'web/party/**',
    'tests/fixtures/appliances/**',
    '.github/workflows/service-trust-proof.yml',
)


def _matches(path, pattern):
    if pattern.endswith('/**'):
        return path.startswith(pattern[:-2])
    return path == pattern


def is_platform_path(path):
    path = path.replace(chr(92), '/')
    if path.startswith('./'):
        path = path[2:]
    return any(_matches(path, p) for p in PLATFORM_PATHS)


def touches_platform(changed_paths):
    return any(is_platform_path(p) for p in changed_paths)


# Owner decision 2026-10-14 (AVR-305): the 10-minute native-game job is not yet mandatory. It becomes
# required for platform changes once Actions billing, runner availability and a hosted verification
# run are resolved; flip this and pass `native_game: true` in ci-verdict.yml together. Until then a
# native-game run (manual dispatch) that fails still fails the verdict.
NATIVE_GAME_REQUIRED = False


def _norm(result):
    result = (result or '').strip().lower()
    return NOT_RUN if result == '' else result


def decide(changed_paths, offline, cross_repo, trust, native_game):
    """(ok, reasons). Each lane result is one of RESULTS.

    Offline checks and Cross-repo contract apply to every pull request: they must have succeeded.
    The Service trust proof workflow applies when a platform path changed: then it must have
    succeeded, and so must its native-game job when NATIVE_GAME_REQUIRED (deferred for now). When no platform path changed they are not required, but if one
    ran anyway and did not succeed that is still a failure.
    """
    lanes = (('Offline checks', _norm(offline), True),
             ('Cross-repo contract', _norm(cross_repo), True))
    platform = touches_platform(changed_paths)
    lanes += (('Service trust proof', _norm(trust), platform),
              ('Service trust proof / native-game', _norm(native_game), platform and NATIVE_GAME_REQUIRED))
    reasons = []
    for name, result, required in lanes:
        if result not in RESULTS:
            reasons.append(f'{name}: unknown result {result!r}')
        elif result in (FAILURE, CANCELLED):
            reasons.append(f'{name}: {result}')
        elif result != SUCCESS and required:
            why = 'applies to every pull request' if name in ('Offline checks', 'Cross-repo contract') \
                else 'this change touches a platform path'
            reasons.append(f'{name}: required ({why}) but {"did not run" if result in (SKIPPED, NOT_RUN) else result}')
    return (not reasons, reasons)


def changed_paths(base, head, cwd=None):
    out = subprocess.run(['git', 'diff', '--name-only', '-z', f'{base}...{head}'], cwd=cwd, check=True,
                         capture_output=True).stdout.decode('utf-8')
    return [p for p in out.split('\0') if p]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    for name in ('scope', 'verdict'):
        p = sub.add_parser(name)
        p.add_argument('--base', required=True)
        p.add_argument('--head', required=True)
        if name == 'verdict':
            for lane in ('offline', 'cross-repo', 'trust', 'native-game'):
                p.add_argument(f'--{lane}', default='')
    args = ap.parse_args(argv)
    paths = changed_paths(args.base, args.head)
    if args.cmd == 'scope':
        line = f'platform={"true" if touches_platform(paths) else "false"}'
        print(line)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        return 0
    ok, reasons = decide(paths, args.offline, args.cross_repo, args.trust, args.native_game)
    print(f'{len(paths)} changed path(s); platform paths touched: {touches_platform(paths)}')
    for r in reasons:
        print(f'FAIL {r}')
    print('CI verdict: ok' if ok else 'CI verdict: NOT ok')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
