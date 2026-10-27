"""The owner backup file (avrana.ops.backup_archive, AVR-81): round trip, and hostile files refused."""
import hashlib
import io
import json
import tarfile
import unittest

from avrana.ops import backup_archive as ba

VERSIONS = {'party': 'a' * 40, 'games': 'b' * 40, 'web': 'c' * 12}
ENTRIES = [('O', 'party-core.diff.json', b'{"venue": "Den"}'), ('O', 'covers/tanks.webp', b'RIFF0000WEBP')]
PACKAGES = [{'id': 'tanks', 'version': '0.1.0', 'sha256': 'd' * 64, 'grants': ['party_roster']}]


def tar_of(members):
    """A hand-made archive: [(name, bytes or None for a symlink, type)]."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode='w') as tar:
        for name, data, kind in members:
            info = tarfile.TarInfo(name)
            if kind == 'link':
                info.type, info.linkname = tarfile.SYMTYPE, '/etc/shadow'
                tar.addfile(info)
            elif kind == 'dir':
                info.type = tarfile.DIRTYPE
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def manifest(entries, schema=ba.SCHEMA):
    return json.dumps({'schema': schema, 'versions': VERSIONS, 'packages': [], 'entries': entries}).encode()


def entry(name, data, cls='O'):
    return {'class': cls, 'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


class RoundTrip(unittest.TestCase):
    def test_build_then_read(self):
        data = ba.build(ENTRIES, VERSIONS, PACKAGES, created='2026-10-26T12:00:00Z')
        m, files = ba.read(data)
        self.assertEqual(m['schema'], 'avrana.backup/v1')
        self.assertEqual(m['packages'], PACKAGES)
        self.assertEqual(files, {n: d for _, n, d in ENTRIES})

    def test_deterministic(self):
        self.assertEqual(ba.build(ENTRIES, VERSIONS), ba.build(list(reversed(ENTRIES)), VERSIONS))

    def test_only_owner_state_is_ever_written(self):
        for cls in ('R', 'S', 'E', 'O-secret'):
            with self.assertRaises(ba.Refused, msg=cls):
                ba.build([(cls, 'x.json', b'{}')], VERSIONS)
        with self.assertRaises(ba.Refused):
            ba.build([('O', '/etc/avrana-party/tls/key.pem', b'k')], VERSIONS)
        with self.assertRaises(ba.Refused):
            ba.build([('O', 'a.json', b'1'), ('O', 'a.json', b'2')], VERSIONS)
        with self.assertRaises(ba.Refused):
            ba.build([('O', 'a.json\n', b'1')], VERSIONS)


class Hostile(unittest.TestCase):
    def refused(self, data, words):
        with self.assertRaises(ba.Refused) as ctx:
            ba.read(data)
        self.assertIn(words, str(ctx.exception))

    def test_not_an_archive(self):
        self.refused(b'hello', 'not a tar archive')

    def test_traversal_absolute_and_outside_names(self):
        body = b'x'
        self.refused(tar_of([('manifest.json', manifest([entry('a.json', body)]), 'file'),
                             ('files/a.json', body, 'file'), ('files/../evil', body, 'file')]), 'not in the manifest')
        self.refused(tar_of([('manifest.json', manifest([]), 'file'), ('/etc/passwd', body, 'file')]), 'outside files/')
        self.refused(tar_of([('manifest.json', manifest([entry('../evil', body)]), 'file'),
                             ('files/../evil', body, 'file')]), 'not a logical name')

    def test_links_and_directories(self):
        self.refused(tar_of([('manifest.json', manifest([]), 'file'), ('files/a', None, 'link')]), 'not a regular file')
        self.refused(tar_of([('manifest.json', manifest([]), 'file'), ('files', None, 'dir')]), 'not a regular file')

    def test_wrong_hash_size_missing_and_extra(self):
        good = entry('a.json', b'abc')
        self.refused(tar_of([('manifest.json', manifest([good]), 'file'), ('files/a.json', b'abd', 'file')]), 'hash')
        self.refused(tar_of([('manifest.json', manifest([good]), 'file')]), 'listed but missing')
        self.refused(tar_of([('manifest.json', manifest([]), 'file'), ('files/a.json', b'abc', 'file')]), 'not in the manifest')
        self.refused(tar_of([('manifest.json', manifest([dict(good, size=-1)]), 'file'),
                             ('files/a.json', b'abc', 'file')]), 'bad size')

    def test_unknown_and_forbidden_classes(self):
        for cls, words in (('Z', 'unknown class'), ('S', 'never stored'), ('O-secret', 'never stored')):
            self.refused(tar_of([('manifest.json', manifest([entry('a.json', b'k', cls)]), 'file'),
                                 ('files/a.json', b'k', 'file')]), words)

    def test_oversize_entry(self):
        big = entry('big.bin', b'')
        big['size'] = ba.MAX_ENTRY + 1
        self.refused(tar_of([('manifest.json', manifest([big]), 'file'), ('files/big.bin', b'', 'file')]), 'more than')

    def test_schema_from_the_future_and_no_manifest(self):
        self.refused(tar_of([('manifest.json', manifest([], schema='avrana.backup/v2'), 'file')]), 'newer version')
        self.refused(tar_of([('files/a.json', b'x', 'file')]), 'no manifest')
        self.refused(tar_of([('manifest.json', b'{nope', 'file')]), 'not JSON')

    def test_a_second_manifest_is_refused_not_obeyed(self):
        body = b'x'
        self.refused(tar_of([('manifest.json', manifest([entry('a.json', body)]), 'file'),
                             ('manifest.json', manifest([]), 'file'), ('files/a.json', body, 'file')]),
                     'manifest.json appears twice')

    # -- AVR-741 independent review
    def test_sparse_members_are_refused_before_they_unpack(self):
        # GNU sparse 1.0 in PAX: a 513-byte member that tarfile would unpack to 8 MiB of zeros.
        size = 8 * 1024 * 1024
        data = f'1\n{size - 1}\n1\n'.encode().ljust(512, b'\0') + b'x'
        out = io.BytesIO()
        with tarfile.open(fileobj=out, mode='w', format=tarfile.PAX_FORMAT) as tar:
            raw = manifest([])
            info = tarfile.TarInfo('manifest.json')
            info.size = len(raw)
            tar.addfile(info, io.BytesIO(raw))
            for i in range(3):
                info = tarfile.TarInfo(f'files/e{i}.sparse')
                info.size = len(data)
                info.pax_headers = {'GNU.sparse.major': '1', 'GNU.sparse.minor': '0',
                                    'GNU.sparse.name': f'files/e{i}', 'GNU.sparse.realsize': str(size)}
                tar.addfile(info, io.BytesIO(data))
        self.refused(out.getvalue(), 'not a regular file')

    def test_a_manifest_nested_thousands_deep_is_refused_not_a_crash(self):
        self.refused(tar_of([('manifest.json', b'[' * 100000 + b']' * 100000, 'file')]), 'not JSON')

if __name__ == '__main__':
    unittest.main()
