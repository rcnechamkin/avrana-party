"""python -m avrana.avrgame: validate, pack and inspect EXPERIMENTAL .avrgame packages.

    validate <file.avrgame | directory-with-avrgame.build.json | recipe file>
    pack <path/to/avrgame.build.json> [--out FILE] [--deflate]
    inspect <file.avrgame> [--json]
    extract <file.avrgame> <dest>         validate, then unpack into a new or empty directory

Exit 0 on success, 1 when the package or its inputs are refused (one problem per line on stderr),
2 on bad usage. There is no install command here. Names may change; this is not a stable CLI.
"""
import argparse
import json
import os
import sys

from . import archive, build
from .common import RECIPE_NAME, Refused


def _summary(p):
    return (f'id: {p.id}\nversion: {p.version}\nfiles: {len(p.files)}\nbytes: {p.total_bytes}\n'
            f'sha256: {p.sha256}')


def _describe(p):
    m = p.manifest
    return {
        'format': m['format'], 'id': p.id, 'name': p.game['name'], 'version': p.version,
        'publisher': m['package']['publisher'], 'license': m['package']['license'],
        **({'source': m['package']['source']} if 'source' in m['package'] else {}),
        'requires': m['requires'], 'server': m['server'], 'client': m['client'],
        'sha256': p.sha256, 'archive_bytes': p.size, 'total_bytes': p.total_bytes,
        'files': [{'path': f.path, 'size': f.size, 'sha256': f.sha256} for f in p.files],
    }


def _validate(target):
    if os.path.isdir(target):
        return build.validate_recipe(os.path.join(target, RECIPE_NAME))
    if target.endswith('.json'):
        return build.validate_recipe(target)
    return archive.read(target)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m avrana.avrgame', description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    v = sub.add_parser('validate', help='validate an archive, or the package a recipe would build')
    v.add_argument('target')
    p = sub.add_parser('pack', help='build an archive from an avrgame.build.json recipe')
    p.add_argument('recipe')
    p.add_argument('--out', default=None, help='default: <id>-<version>.avrgame in the current directory')
    p.add_argument('--deflate', action='store_true',
                   help='deflate (smaller; the sha256 then depends on the zlib build). Default: stored, identical bytes everywhere')
    x = sub.add_parser('extract', help='validate an archive, then unpack it into a new or empty directory')
    x.add_argument('archive')
    x.add_argument('dest')
    i = sub.add_parser('inspect', help='show the manifest summary and file list of an archive')
    i.add_argument('archive')
    i.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'validate':
            print(_summary(_validate(args.target)))
        elif args.command == 'pack':
            package = build.pack_recipe(args.recipe, args.out, compress=args.deflate)
            print(f'{package.path}\nsha256: {package.sha256}')
        elif args.command == 'extract':
            package = archive.extract(args.archive, args.dest)
            print(f'{package.id} {package.version}: {len(package.files)} files into {args.dest}')
        else:
            package = archive.read(args.archive)
            if args.json:
                print(json.dumps(_describe(package), indent=2))
            else:
                d = _describe(package)
                print(f'{d["id"]} {d["version"]}  ({d["name"]})\nformat: {d["format"]}\n'
                      f'publisher: {d["publisher"]} (claim)\nlicense: {d["license"]} (claim)\n'
                      f'server: {d["server"]["interpreter"]} {" ".join(d["server"]["args"])}\n'
                      f'client: {d["client"]["root"]}\nsha256: {d["sha256"]}\n'
                      f'files ({len(d["files"])}, {d["total_bytes"]} bytes):')
                for f in d['files']:
                    print(f'  {f["size"]:>9}  {f["path"]}')
    except Refused as exc:
        for problem in exc.problems:
            print(problem, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
