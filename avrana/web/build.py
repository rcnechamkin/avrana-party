"""Build an installable copy of the Full Mode web shell (web/party/).

    python3 -m avrana.web.build --out DIR [--build ID] [--commit SHA] [--no-service-worker]

Copies web/party/ to DIR, stamps the build id into sw.js (so browsers see a new worker and a new
cache name) and writes version.json. --no-service-worker produces the self-destruct worker and
tells pages to remove their offline copy (the kill switch). The result is plain static files for
nginx; ops/install-party-web.sh puts it in place on the Pi.
"""
import argparse
import datetime
import json
import re
import shutil
import sys
from pathlib import Path

from avrana import WEB_DIR
from avrana.contracts import strictjson

BUILD_ID = re.compile(r'^[A-Za-z0-9._-]{1,40}$')
BUILD_LINE = "const BUILD = 'dev';"
ENABLED_LINE = 'const ENABLED = true;'
SHELL_LIST = re.compile(r'const SHELL = \[(.*?)\];', re.S)


class BuildError(RuntimeError):
    pass


def shell_list(sw_text):
    """The precache list declared in sw.js (relative to the scope)."""
    match = SHELL_LIST.search(sw_text)
    if not match:
        raise BuildError('sw.js has no SHELL list')
    return re.findall(r"'([^']*)'", match.group(1))


def stamp(sw_text, build, service_worker=True):
    if sw_text.count(BUILD_LINE) != 1 or sw_text.count(ENABLED_LINE) != 1:
        raise BuildError('sw.js must contain the BUILD and ENABLED lines exactly once')
    out = sw_text.replace(BUILD_LINE, f"const BUILD = '{build}';")
    if not service_worker:
        out = out.replace(ENABLED_LINE, 'const ENABLED = false;')
    return out


def check_tree(root):
    """Problems in a web shell tree (source or built)."""
    root = Path(root)
    problems = []
    sw = root / 'sw.js'
    if not sw.is_file():
        return ['sw.js is missing']
    for rel in shell_list(sw.read_text(encoding='utf-8')):
        target = root / rel
        if rel == '' or rel.endswith('/'):
            target = target / 'index.html'
        if not target.is_file():
            problems.append(f'precached {rel!r} does not exist')
    try:
        catalog = strictjson.load_path(root / 'catalog.json')
        if catalog.get('schema') != 'avrana.catalog/v0':
            problems.append('catalog.json has the wrong schema')
    except (OSError, ValueError) as exc:
        problems.append(f'catalog.json: {exc}')
    return problems


def build(out, build_id, commit=None, service_worker=True, source=WEB_DIR, now=None):
    out = Path(out)
    if not BUILD_ID.match(build_id):
        raise BuildError('build id: 1-40 of [A-Za-z0-9._-]')
    if out.exists() and any(out.iterdir()):
        raise BuildError(f'{out} is not empty')
    problems = check_tree(source)
    if problems:
        raise BuildError('; '.join(problems))
    shutil.copytree(source, out, dirs_exist_ok=True)
    sw = out / 'sw.js'
    sw.write_text(stamp(sw.read_text(encoding='utf-8'), build_id, service_worker), encoding='utf-8')
    now = now or datetime.datetime.now(datetime.timezone.utc)
    version = {'schema': 'avrana.web-build/v0', 'build': build_id, 'commit': commit,
               'builtAt': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'serviceWorker': bool(service_worker)}
    (out / 'version.json').write_text(json.dumps(version, indent=2) + '\n', encoding='utf-8')
    return version


def main(argv=None):
    ap = argparse.ArgumentParser(description='Build the Full Mode web shell for nginx.')
    ap.add_argument('--out', required=True)
    ap.add_argument('--build', default=None, help='build id (default: first 12 characters of --commit)')
    ap.add_argument('--commit', default=None)
    ap.add_argument('--no-service-worker', action='store_true', help='kill switch: remove offline copies')
    args = ap.parse_args(argv)
    build_id = args.build or (args.commit or '')[:12]
    if not build_id:
        ap.error('give --build or --commit')
    try:
        version = build(args.out, build_id, args.commit, not args.no_service_worker)
    except BuildError as exc:
        print(f'build failed: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(version))
    return 0


if __name__ == '__main__':
    sys.exit(main())
