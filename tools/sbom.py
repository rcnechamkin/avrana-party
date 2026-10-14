#!/usr/bin/env python3
"""Third-party inventory check, CycloneDX SBOM and NOTICE generator (AVR-73). Stdlib only, offline.

    python3 tools/sbom.py --check                 # inventory covers what the repository ships
    python3 tools/sbom.py --out build/sbom        # check, then write the SBOM and NOTICE there
    python3 tools/sbom.py --check --root DIR      # another tree (tests)

Inputs: contracts/third-party.v1.json (the hand-kept inventory) and package-lock.json. Outputs
(deterministic: no clock, no randomness; set SOURCE_DATE_EPOCH to stamp the SBOM):
  avrana-party.cdx.json   CycloneDX 1.5 JSON
  NOTICE.txt              attributions, owner-installed and reference-only lists, blockers

--check fails (exit 1) when
  * the inventory breaks its schema, or a component has no license (NOASSERTION is accepted only
    when marked "unverified", and is reported as a warning count);
  * a vendored asset directory (assets/vendor/*, web/party/fonts) is not claimed by a component;
  * a production npm dependency in package-lock.json, a third-party Python import in a shipped
    tree, or a package in deploy/appliance-inventory.json is not claimed by a component;
  * a component's declared path no longer exists (stale entry).
devDependencies are build-time: they need no entry, and appear in the SBOM with scope "excluded".
Policy and vocabulary: docs/design/THIRD-PARTY.md. This is engineering tooling, not legal advice.
"""
import argparse
import ast
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import quote

SCHEMA = 'avrana.third-party/v1'
USAGES = ('embedded', 'separate-process', 'owner-installed', 'reference-only', 'build-time-only')
POSTURES = ('embed-ok', 'separate-process-only', 'redistribute-with-notice', 'owner-installs-do-not-bundle',
            'reference-only', 'avoid-commercial-distribution', 'not-distributed')
SHIPPED_IN = ('appliance-web', 'phones', 'appliance-system', 'none')
VERIFICATION = ('file-read', 'repo-doc', 'unverified')
REQUIRED = ('id', 'name', 'version', 'license', 'license_verification', 'license_source', 'source', 'usage',
            'shipped_in', 'redistribution', 'commercial_blocker', 'note')
OPTIONAL_LISTS = ('paths', 'npm_packages', 'python_modules', 'apt_packages')
VENDOR_ROOTS = ('assets/vendor', 'web/party/fonts')  # children of the first, the second itself
PY_TREES = ('avrana', 'arcade', 'ps1', 'portal', 'ops', 'telemetry', 'deploy')
INVENTORY = 'contracts/third-party.v1.json'
NOTICE_TEXT_LIMIT = 20000


def load_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def validate_inventory(inv):
    """Schema errors for an inventory document (a list of strings)."""
    errors = []
    if not isinstance(inv, dict) or inv.get('schema') != SCHEMA:
        return ['inventory: schema must be ' + SCHEMA]
    comps = inv.get('components')
    if not isinstance(comps, list) or not comps:
        return ['inventory: components must be a non-empty list']
    seen = set()
    for i, c in enumerate(comps):
        label = c.get('id', '#%d' % i) if isinstance(c, dict) else '#%d' % i
        if not isinstance(c, dict):
            errors.append('%s: component must be an object' % label)
            continue
        for key in REQUIRED:
            if key not in c:
                errors.append('%s: missing field %s' % (label, key))
        if label in seen:
            errors.append('%s: duplicate id' % label)
        seen.add(label)
        for key in ('id', 'name', 'version', 'license', 'license_source', 'source', 'note'):
            if key in c and not (isinstance(c[key], str) and c[key].strip()):
                errors.append('%s: %s must be a non-empty string%s' % (
                    label, key, ' (a component without a license cannot ship)' if key == 'license' else ''))
        for key, allowed in (('usage', USAGES), ('redistribution', POSTURES),
                             ('license_verification', VERIFICATION)):
            if key in c and c[key] not in allowed:
                errors.append('%s: %s must be one of %s' % (label, key, ', '.join(allowed)))
        if not isinstance(c.get('commercial_blocker'), bool) and 'commercial_blocker' in c:
            errors.append('%s: commercial_blocker must be true or false' % label)
        shipped = c.get('shipped_in')
        if 'shipped_in' in c and (not isinstance(shipped, list) or not shipped
                                  or any(s not in SHIPPED_IN for s in shipped)):
            errors.append('%s: shipped_in must be a non-empty list of %s' % (label, ', '.join(SHIPPED_IN)))
        if c.get('license') == 'NOASSERTION' and c.get('license_verification') != 'unverified':
            errors.append('%s: NOASSERTION is only allowed with license_verification "unverified"' % label)
        if c.get('license_verification') == 'unverified' and c.get('license') not in (None, 'NOASSERTION'):
            errors.append('%s: an "unverified" component must record license NOASSERTION' % label)
        if c.get('usage') == 'reference-only' and (c.get('redistribution') != 'reference-only'
                                                   or shipped != ['none']):
            errors.append('%s: reference-only usage needs redistribution reference-only and shipped_in [none]' % label)
        if c.get('usage') == 'build-time-only' and shipped != ['none']:
            errors.append('%s: build-time-only usage needs shipped_in [none]' % label)
        if c.get('usage') in ('embedded', 'separate-process', 'owner-installed') and shipped == ['none']:
            errors.append('%s: a used component must say where it ships' % label)
        if c.get('redistribution') == 'avoid-commercial-distribution' and c.get('commercial_blocker') is not True:
            errors.append('%s: avoid-commercial-distribution must set commercial_blocker true' % label)
        for key in OPTIONAL_LISTS:
            if key in c and (not isinstance(c[key], list) or not c[key]
                             or not all(isinstance(x, str) and x for x in c[key])):
                errors.append('%s: %s must be a non-empty list of strings' % (label, key))
        extra = set(c) - set(REQUIRED) - set(OPTIONAL_LISTS)
        if extra:
            errors.append('%s: unknown field %s' % (label, ', '.join(sorted(extra))))
    fp = inv.get('first_party')
    if not isinstance(fp, dict) or not fp.get('license') or not fp.get('name'):
        errors.append('inventory: first_party needs name and license')
    return errors


def lock_packages(lock):
    """[(name, version, dev, license, resolved)] for every installed package except the root."""
    out = []
    for key, meta in sorted((lock.get('packages') or {}).items()):
        if not key:
            continue
        name = key.split('node_modules/')[-1]
        out.append((name, meta.get('version', ''), bool(meta.get('dev') or meta.get('devOptional')),
                    meta.get('license') or 'NOASSERTION', meta.get('resolved', '')))
    return out


def python_third_party(root):
    """{top-level module: [files]} imported by shipped Python that is neither stdlib nor ours."""
    std = set(sys.stdlib_module_names)
    found = {}
    files = [p for t in PY_TREES if (root / t).is_dir() for p in (root / t).rglob('*.py')]
    files += sorted(root.glob('*.py'))
    for path in sorted(files):
        try:
            tree = ast.parse(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            else:
                continue
            for mod in mods:
                top = mod.split('.')[0]
                local = any((d / top).is_dir() or (d / (top + '.py')).is_file() for d in (path.parent, root))
                if top not in std and not local:
                    found.setdefault(top, []).append(path.relative_to(root).as_posix())
    return found


def claimed(inv, key):
    return {x for c in inv['components'] for x in c.get(key, [])}


def check(root, inv, lock):
    """(errors, warnings) comparing the inventory with what the tree ships."""
    errors = validate_inventory(inv)
    if errors:
        return errors, []
    warnings = []
    paths = sorted(claimed(inv, 'paths'))

    def covered(rel):
        return any(rel == p or rel.startswith(p + '/') or p.startswith(rel + '/') for p in paths)

    vendored = []
    base = root / VENDOR_ROOTS[0]
    if base.is_dir():
        vendored += sorted(VENDOR_ROOTS[0] + '/' + d.name for d in base.iterdir() if d.is_dir())
    if (root / VENDOR_ROOTS[1]).is_dir():
        vendored.append(VENDOR_ROOTS[1])
    for rel in vendored:
        if not covered(rel):
            errors.append('vendored directory %s is not claimed by any inventory component (add it to "paths")' % rel)
    for p in paths:
        if not (root / p).exists():
            errors.append('inventory path %s does not exist (stale entry)' % p)
    npm = claimed(inv, 'npm_packages')
    for name, version, dev, _lic, _res in lock_packages(lock):
        if not dev and name not in npm:
            errors.append('production npm dependency %s@%s is not in the inventory' % (name, version))
    py = claimed(inv, 'python_modules')
    for mod, files in sorted(python_third_party(root).items()):
        if mod not in py:
            errors.append('Python import "%s" (%s) is not in the inventory' % (mod, ', '.join(sorted(set(files))[:3])))
    apt = claimed(inv, 'apt_packages')
    ai = root / 'deploy' / 'appliance-inventory.json'
    if ai.is_file():
        for pkg in load_json(ai).get('packages', []):
            if pkg.get('name') not in apt:
                errors.append('system package %s (deploy/appliance-inventory.json) is not in the inventory' % pkg.get('name'))
    unverified = sorted(c['id'] for c in inv['components'] if c['license_verification'] == 'unverified')
    if unverified:
        warnings.append('%d component(s) have an unverified license: %s' % (len(unverified), ', '.join(unverified)))
    blockers = sorted(c['id'] for c in inv['components'] if c['commercial_blocker'])
    if blockers:
        warnings.append('%d commercial blocker(s): %s' % (len(blockers), ', '.join(blockers)))
    if inv['first_party'].get('license') == 'NOASSERTION':
        warnings.append('first-party license is undecided')
    return errors, warnings


def purl_npm(name, version):
    return 'pkg:npm/%s@%s' % (quote(name, safe='/').replace('@', '%40', 1) if name.startswith('@') else name, version)


def license_choice(lic):
    if lic == 'NOASSERTION':
        return []
    if lic.startswith('SEE LICENSE') or lic.startswith('LicenseRef-'):
        return [{'license': {'name': lic}}]
    if any(ch in lic for ch in ' ()'):
        return [{'expression': lic}]
    return [{'license': {'id': lic}}]


def props(c):
    return [{'name': 'avrana:' + k, 'value': v} for k, v in (
        ('commercial-blocker', 'true' if c['commercial_blocker'] else 'false'),
        ('license-verification', c['license_verification']),
        ('redistribution', c['redistribution']), ('usage', c['usage']))]


def scope_of(c):
    return {'embedded': 'required', 'separate-process': 'required', 'owner-installed': 'optional'}.get(c['usage'], 'excluded')


def build_sbom(inv, lock):
    claims = {}
    for c in inv['components']:
        for n in c.get('npm_packages', []):
            claims[n] = c
    comps = []
    for name, version, dev, lic, resolved in lock_packages(lock):
        owner = claims.get(name)
        entry = {'type': 'library', 'bom-ref': 'npm:%s@%s' % (name, version), 'name': name, 'version': version,
                 'purl': purl_npm(name, version), 'scope': 'excluded' if dev else 'required'}
        if owner and 'paths' not in owner:
            lic, usage_props, entry['scope'] = owner['license'], props(owner), scope_of(owner)
        else:
            usage_props = [{'name': 'avrana:usage', 'value': 'build-time-only' if dev else 'embedded'}]
        if license_choice(lic):
            entry['licenses'] = license_choice(lic)
        entry['properties'] = usage_props
        comps.append(entry)
    for c in inv['components']:
        if c['usage'] == 'reference-only' or ('npm_packages' in c and 'paths' not in c):
            continue
        kind = ('file' if c.get('paths') else 'application' if c['usage'] in ('separate-process',) else 'library')
        entry = {'type': kind, 'bom-ref': 'avrana:' + c['id'], 'name': c['name'], 'version': c['version'],
                 'scope': scope_of(c), 'description': c['note'],
                 'externalReferences': [{'type': 'website', 'url': c['source']}]}
        if license_choice(c['license']):
            entry['licenses'] = license_choice(c['license'])
        entry['properties'] = props(c) + [{'name': 'avrana:shipped-in', 'value': ','.join(c['shipped_in'])}]
        if c.get('apt_packages') and kind == 'library':
            entry['purl'] = 'pkg:deb/debian/%s' % c['apt_packages'][0]
        comps.append(entry)
    comps.sort(key=lambda e: e['bom-ref'])
    fp = inv['first_party']
    doc = {'bomFormat': 'CycloneDX', 'specVersion': '1.5', 'version': 1,
           'metadata': {'component': {'type': 'application', 'bom-ref': 'avrana:first-party', 'name': fp['name'],
                                      'licenses': license_choice(fp['license'])},
                        'tools': {'components': [{'type': 'application', 'name': 'tools/sbom.py'}]}},
           'components': comps}
    if not doc['metadata']['component']['licenses']:
        del doc['metadata']['component']['licenses']
    epoch = os.environ.get('SOURCE_DATE_EPOCH')
    if epoch and epoch.isdigit():
        import datetime
        doc['metadata']['timestamp'] = datetime.datetime.fromtimestamp(
            int(epoch), datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    digest = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
    doc['serialNumber'] = 'urn:uuid:%s' % uuid.uuid5(uuid.NAMESPACE_URL, 'avrana-sbom:' + digest)
    return doc


def license_text(root, c):
    src = c['license_source'].split(' ')[0]
    path = root / src
    if '/' in src and path.is_file() and path.stat().st_size <= NOTICE_TEXT_LIMIT:
        return path.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n').strip()
    return None


def build_notice(root, inv):
    comps = sorted(inv['components'], key=lambda c: c['id'])
    out = ['NOTICE: third-party components of Avrana Party', '=' * 44, '',
           'Generated by tools/sbom.py from contracts/third-party.v1.json. Engineering record, not legal advice.', '']

    def block(title, items, texts=False):
        out.extend([title, '-' * len(title)])
        if not items:
            out.extend(['(none)', ''])
        for c in items:
            out.append('%s %s' % (c['name'], c['version']))
            out.append('  License: %s (%s)' % (c['license'], c['license_verification']))
            out.append('  Source:  %s' % c['source'])
            if texts:
                text = license_text(root, c)
                out.append('  License text: ' + ('' if text else 'see ' + c['license_source']))
                if text:
                    out.extend('    ' + line if line else '' for line in text.split('\n'))
            out.append('')

    block('Shipped inside Avrana output (notices must travel with it)',
          [c for c in comps if c['usage'] in ('embedded', 'separate-process') and 'none' not in c['shipped_in']], True)
    block('Installed by the owner, not distributed by Avrana',
          [c for c in comps if c['usage'] == 'owner-installed'])
    block('Build-time only (not in any distributed output)', [c for c in comps if c['usage'] == 'build-time-only'])
    block('Reference only (not used or distributed; not reusable)', [c for c in comps if c['usage'] == 'reference-only'])
    out.extend(['Commercial blockers', '-------------------'])
    blockers = [c for c in comps if c['commercial_blocker']]
    out.extend('- %s: %s' % (c['name'], c['note']) for c in blockers)
    out.extend(['' if blockers else '(none)', 'Unverified licenses (read before any redistribution)',
                '-' * 50])
    out.extend('- ' + c['name'] for c in comps if c['license_verification'] == 'unverified')
    return '\n'.join(out) + '\n'


def write_outputs(root, inv, lock, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    sbom = json.dumps(build_sbom(inv, lock), indent=2, sort_keys=True) + '\n'
    (out_dir / 'avrana-party.cdx.json').write_text(sbom, encoding='utf-8', newline='\n')
    (out_dir / 'NOTICE.txt').write_text(build_notice(root, inv), encoding='utf-8', newline='\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', default=str(Path(__file__).resolve().parent.parent))
    ap.add_argument('--inventory', help='default: <root>/' + INVENTORY)
    ap.add_argument('--lock', help='default: <root>/package-lock.json')
    ap.add_argument('--out', help='directory for avrana-party.cdx.json and NOTICE.txt')
    ap.add_argument('--check', action='store_true', help='verify the inventory covers the tree')
    args = ap.parse_args(argv)
    if not args.check and not args.out:
        ap.error('give --check, --out DIR, or both')
    root = Path(args.root)
    inv = load_json(args.inventory or root / INVENTORY)
    lock_path = Path(args.lock) if args.lock else root / 'package-lock.json'
    lock = load_json(lock_path) if lock_path.is_file() else {'packages': {}}
    errors, warnings = check(root, inv, lock)
    for w in warnings:
        print('WARN  ' + w)
    for e in errors:
        print('FAIL  ' + e)
    if errors:
        print('sbom: %d problem(s); nothing written' % len(errors))
        return 1
    if args.out:
        write_outputs(root, inv, lock, Path(args.out))
        print('sbom: wrote %s and %s' % (Path(args.out) / 'avrana-party.cdx.json', Path(args.out) / 'NOTICE.txt'))
    else:
        print('sbom: inventory OK (%d components)' % len(inv['components']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
