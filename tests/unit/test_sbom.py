"""Tier 1: third-party inventory, lock parsing, coverage check and SBOM/NOTICE output (AVR-73).

    python3 -m unittest discover -s tests/unit -p test_sbom.py
"""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
spec = importlib.util.spec_from_file_location('sbom', ROOT / 'tools' / 'sbom.py')
sbom = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sbom)


def comp(id_, **over):
    c = {'id': id_, 'name': id_, 'version': '1', 'license': 'MIT', 'license_verification': 'file-read',
         'license_source': 'x/LICENSE', 'source': 'https://example.test/' + id_, 'usage': 'embedded',
         'shipped_in': ['appliance-web'], 'redistribution': 'redistribute-with-notice',
         'commercial_blocker': False, 'note': 'n'}
    c.update(over)
    return c


def inventory(*components):
    return {'schema': sbom.SCHEMA, 'first_party': {'name': 'App', 'license': 'NOASSERTION'},
            'components': list(components)}


LOCK = {'packages': {
    '': {'name': 'app'},
    'node_modules/leftpad': {'version': '1.0.0', 'license': 'MIT'},
    'node_modules/@s/devtool': {'version': '2.0.0', 'dev': True, 'license': 'ISC'}}}


class RealInventory(unittest.TestCase):
    def test_repository_inventory_is_valid_and_complete(self):
        inv = sbom.load_json(ROOT / sbom.INVENTORY)
        self.assertEqual(sbom.validate_inventory(inv), [])
        lock = sbom.load_json(ROOT / 'package-lock.json')
        errors, _ = sbom.check(ROOT, inv, lock)
        self.assertEqual(errors, [])

    def test_known_blockers_are_flagged(self):
        by_id = {c['id']: c for c in sbom.load_json(ROOT / sbom.INVENTORY)['components']}
        for key in ('libretro-mame2010', 'libretro-fbneo', 'owner-supplied-content'):
            self.assertTrue(by_id[key]['commercial_blocker'], key)
        self.assertEqual(by_id['ref-moonlight-web']['redistribution'], 'reference-only')
        self.assertEqual(by_id['retroarch']['redistribution'], 'separate-process-only')


class Schema(unittest.TestCase):
    def test_missing_license_is_an_error(self):
        c = comp('a')
        del c['license']
        self.assertTrue(any('missing field license' in e for e in sbom.validate_inventory(inventory(c))))
        self.assertTrue(any('license' in e for e in sbom.validate_inventory(inventory(comp('a', license='')))))

    def test_noassertion_needs_unverified(self):
        errors = sbom.validate_inventory(inventory(comp('a', license='NOASSERTION')))
        self.assertTrue(any('NOASSERTION' in e for e in errors))
        ok = comp('a', license='NOASSERTION', license_verification='unverified')
        self.assertEqual(sbom.validate_inventory(inventory(ok)), [])

    def test_vocabulary_and_rules(self):
        bad = [comp('a', usage='vendored'), comp('a', redistribution='yolo'), comp('a', unknown=1),
               comp('a', usage='reference-only'), comp('a', shipped_in=['none']),
               comp('a', redistribution='avoid-commercial-distribution'), comp('a', paths=[])]
        for c in bad:
            self.assertTrue(sbom.validate_inventory(inventory(c)), c)
        self.assertTrue(sbom.validate_inventory(inventory(comp('a'), comp('a'))))


class Lock(unittest.TestCase):
    def test_parse_marks_dev(self):
        got = sbom.lock_packages(LOCK)
        self.assertEqual(got[0][:3], ('@s/devtool', '2.0.0', True))
        self.assertEqual(got[1][:3], ('leftpad', '1.0.0', False))
        self.assertEqual(len(got), 2)


class Coverage(unittest.TestCase):
    def tree(self, files):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for rel, text in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding='utf-8')
        return root

    def test_planted_vendor_dir_is_detected(self):
        root = self.tree({'assets/vendor/new-pack/a.svg': '<svg/>', 'assets/vendor/old/b.svg': ''})
        inv = inventory(comp('old', paths=['assets/vendor/old']))
        errors, _ = sbom.check(root, inv, {'packages': {}})
        self.assertEqual(len(errors), 1)
        self.assertIn('assets/vendor/new-pack', errors[0])
        inv['components'].append(comp('new', paths=['assets/vendor/new-pack']))
        self.assertEqual(sbom.check(root, inv, {'packages': {}})[0], [])

    def test_stale_path_is_detected(self):
        errors, _ = sbom.check(self.tree({}), inventory(comp('a', paths=['gone/dir'])), {'packages': {}})
        self.assertTrue(any('stale' in e for e in errors))

    def test_runtime_npm_dependency_is_detected_but_dev_is_not(self):
        root = self.tree({})
        errors, _ = sbom.check(root, inventory(comp('a')), LOCK)
        self.assertEqual(len(errors), 1)
        self.assertIn('leftpad', errors[0])
        inv = inventory(comp('a', npm_packages=['leftpad']))
        self.assertEqual(sbom.check(root, inv, LOCK)[0], [])

    def test_third_party_python_import_is_detected(self):
        root = self.tree({'arcade/svc.py': 'import json\nimport mystery\nfrom helper import x\n',
                          'arcade/helper.py': 'import os\n', 'avrana/m.py': 'from avrana import q\nimport os\n'})
        errors, _ = sbom.check(root, inventory(comp('a')), {'packages': {}})
        self.assertEqual(len(errors), 1)
        self.assertIn('mystery', errors[0])
        inv = inventory(comp('a', python_modules=['mystery']))
        self.assertEqual(sbom.check(root, inv, {'packages': {}})[0], [])

    def test_system_package_is_detected(self):
        root = self.tree({'deploy/appliance-inventory.json': json.dumps({'packages': [{'name': 'nginx'}]})})
        errors, _ = sbom.check(root, inventory(comp('a')), {'packages': {}})
        self.assertIn('nginx', errors[0])
        self.assertEqual(sbom.check(root, inventory(comp('a', apt_packages=['nginx'])), {'packages': {}})[0], [])

    def test_warnings_report_unverified_and_blockers(self):
        inv = inventory(comp('a', license='NOASSERTION', license_verification='unverified'),
                        comp('b', commercial_blocker=True))
        _, warnings = sbom.check(self.tree({}), inv, {'packages': {}})
        text = '\n'.join(warnings)
        self.assertIn('unverified', text)
        self.assertIn('commercial blocker', text)
        self.assertIn('first-party', text)


class Output(unittest.TestCase):
    def setUp(self):
        self.inv = inventory(
            comp('font', paths=['f']), comp('tw', npm_packages=['leftpad'], usage='build-time-only',
                                            shipped_in=['none'], redistribution='not-distributed'),
            comp('core', usage='owner-installed', commercial_blocker=True, license='LicenseRef-nc',
                 redistribution='avoid-commercial-distribution', shipped_in=['appliance-system']),
            comp('ref', usage='reference-only', redistribution='reference-only', shipped_in=['none']))

    def test_cyclonedx_shape_and_scopes(self):
        doc = sbom.build_sbom(self.inv, LOCK)
        self.assertEqual((doc['bomFormat'], doc['specVersion']), ('CycloneDX', '1.5'))
        self.assertTrue(doc['serialNumber'].startswith('urn:uuid:'))
        refs = {c['bom-ref']: c for c in doc['components']}
        self.assertEqual(refs['npm:@s/devtool@2.0.0']['scope'], 'excluded')
        self.assertEqual(refs['npm:@s/devtool@2.0.0']['purl'], 'pkg:npm/%40s/devtool@2.0.0')
        self.assertEqual(refs['npm:leftpad@1.0.0']['scope'], 'excluded')
        self.assertEqual(refs['avrana:font']['scope'], 'required')
        self.assertEqual(refs['avrana:core']['scope'], 'optional')
        self.assertNotIn('avrana:ref', refs)
        self.assertEqual(refs['avrana:core']['licenses'], [{'license': {'name': 'LicenseRef-nc'}}])

    def test_output_is_deterministic_and_written(self):
        self.assertEqual(json.dumps(sbom.build_sbom(self.inv, LOCK)),
                         json.dumps(sbom.build_sbom(copy.deepcopy(self.inv), LOCK)))
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for out in (a, b):
                sbom.write_outputs(Path(a), self.inv, LOCK, Path(out) / 'o')
            for name in ('avrana-party.cdx.json', 'NOTICE.txt'):
                self.assertEqual((Path(a) / 'o' / name).read_bytes(), (Path(b) / 'o' / name).read_bytes())

    def test_notice_sections(self):
        text = sbom.build_notice(Path('.'), self.inv)
        self.assertIn('Shipped inside Avrana output', text)
        self.assertIn('Commercial blockers\n-------------------\n- core', text)
        self.assertIn('Reference only', text)

    def test_main_refuses_to_write_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'contracts').mkdir()
            (root / sbom.INVENTORY).write_text(json.dumps(inventory(comp('a'))), encoding='utf-8')
            (root / 'package-lock.json').write_text(json.dumps(LOCK), encoding='utf-8')
            out = root / 'out'
            self.assertEqual(sbom.main(['--root', str(root), '--out', str(out)]), 1)
            self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
