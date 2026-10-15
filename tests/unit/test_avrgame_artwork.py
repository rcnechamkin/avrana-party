"""EXPERIMENTAL bundled artwork (the optional `artwork` block) of the .avrgame package format: the
validator and the packer. Cross-platform, standard library only; the images are generated here.

    python -m unittest tests.unit.test_avrgame_artwork

The contract is the "Bundled artwork" section of docs/design/AVRGAME-PACKAGE.md.
"""
import hashlib
import json
import os
import stat
import struct
import unittest
import zlib

from avrana import avrgame
from avrana.avrgame import artwork

from test_avrgame_package import BASE_FILES, Tmp, good_manifest, make_zip, problems_of


# ---- tiny images, built from the specifications ------------------------------------------------------------------

def png_chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)


def png(w=256, h=256, pad=0, extra=(), raw=None, color=0, depth=8, trailing=b'', crc_fault=False):
    ihdr = struct.pack('>IIBBBBB', w, h, depth, color, 0, 0, 0)
    if raw is None:
        raw = (b'\x00' + b'\x00' * w) * h
    out = b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', ihdr)
    for kind, body in extra:
        out += png_chunk(kind, body)
    if pad:
        out += png_chunk(b'prVt', b'\x00' * pad)
    out += png_chunk(b'IDAT', zlib.compress(raw)) + png_chunk(b'IEND', b'')
    if crc_fault:
        out = out[:-1] + bytes([out[-1] ^ 1])
    return out + trailing


def jpeg(w=256, h=256, app1=None, trailing=b'', eoi=True):
    sof = struct.pack('>BHHB', 8, h, w, 1) + bytes([1, 0x11, 0])
    sos = bytes([1, 1, 0, 0, 63, 0])
    out = b'\xff\xd8'
    if app1:
        out += b'\xff\xe1' + struct.pack('>H', len(app1) + 2) + app1
    out += b'\xff\xc0' + struct.pack('>H', len(sof) + 2) + sof
    out += b'\xff\xda' + struct.pack('>H', len(sos) + 2) + sos + b'\x12\x34\x56\x00\xff\x00'
    if eoi:
        out += b'\xff\xd9'
    return out + trailing


def riff(chunks, size_delta=0):
    body = b'WEBP'
    for kind, data in chunks:
        body += kind + struct.pack('<I', len(data)) + data + (b'\x00' if len(data) & 1 else b'')
    return b'RIFF' + struct.pack('<I', len(body) + size_delta) + body


def vp8l(w, h):
    return b'\x2f' + struct.pack('<I', (w - 1) | ((h - 1) << 14))


def vp8(w, h):
    return b'\x10\x00\x00\x9d\x01\x2a' + struct.pack('<HH', w, h) + b'\x00\x00'


def vp8x(w, h, flags=0):
    return bytes([flags, 0, 0, 0]) + (w - 1).to_bytes(3, 'little') + (h - 1).to_bytes(3, 'little')


def webp(w=256, h=256, size_delta=0):
    return riff([(b'VP8L', vp8l(w, h))], size_delta)


D = 'game_pkg/artwork/'
COVER = D + 'cover.webp'


def with_art(block, **over):
    return good_manifest(artwork=block, **over)


def art_zip(block, images, extra=(), **over):
    """A package whose manifest carries `block` and whose files are BASE_FILES plus `images`."""
    files = dict(BASE_FILES)
    files.update(images)
    return make_zip(files=files, manifest=json.dumps(with_art(block, **over)).encode(), extra=extra)


def shot(path, alt='x'):
    return {'path': path, 'alt': alt}


class ManifestBlock(unittest.TestCase):
    def bad(self, block, expect):
        text = '\n'.join(problems_of(with_art(block)))
        self.assertIn(expect, text)

    def test_the_block_and_every_key_are_optional(self):
        for block in ({}, {'cover': COVER}, {'icon': COVER}, {'screenshots': []}):
            self.assertEqual(avrgame.validate_manifest(with_art(block))['artwork'], block)
        self.assertNotIn('artwork', avrgame.validate_manifest(good_manifest()))

    def test_the_format_string_is_unchanged(self):
        self.assertEqual(avrgame.FORMAT, 'avrana.avrgame/experimental.1')
        self.assertEqual(avrgame.validate_manifest(with_art({'cover': COVER}))['format'], avrgame.FORMAT)

    def test_unknown_keys_are_refused_and_there_is_no_credit_field(self):
        self.bad({'poster': COVER}, "artwork: unknown key 'poster'")
        self.bad({'credit': 'Someone'}, "unknown key 'credit'")
        self.bad({'screenshots': [{'path': COVER, 'alt': 'a', 'title': 'b'}]}, "unknown key 'title'")

    def test_paths_are_relative_normalised_local_and_typed(self):
        self.bad({'cover': '/etc/cover.png'}, 'absolute path')
        self.bad({'cover': 'https://example.invalid/c.png'}, 'remote URL')
        self.bad({'cover': 'data:image/png;base64,AAAA'}, 'remote URL or scheme')
        self.bad({'cover': '//example.invalid/c.png'}, 'remote URL or scheme')
        self.bad({'cover': 'game_pkg/../cover.png'}, '".." segments')
        self.bad({'cover': 'artwork\\cover.png'}, 'backslash')
        self.bad({'cover': 'C:/cover.png'}, 'drive letter')
        self.bad({'cover': 'artwork//cover.png'}, 'empty path segment')
        self.bad({'cover': ''}, 'empty name')
        self.bad({'cover': 7}, 'must be a path string')
        self.bad({'cover': 'artwork/cover.svg'}, 'SVG is not accepted')
        self.bad({'cover': 'artwork/cover.avif'}, 'AVIF is not accepted')
        self.bad({'cover': 'artwork/cover.gif'}, 'GIF is not accepted')
        self.bad({'cover': 'artwork/cover.bmp'}, 'must end in .webp, .png, .jpg or .jpeg')
        self.bad({'cover': 'artwork/cover'}, 'must end in')

    def test_images_may_not_live_under_client_root(self):
        self.bad({'cover': 'game_pkg/web/cover.png'}, 'outside client.root')
        self.bad({'icon': 'GAME_PKG/WEB/x/icon.png'}, 'outside client.root')
        self.assertEqual(avrgame.validate_manifest(with_art({'cover': 'game_pkg/webby/c.png'}))['artwork'],
                         {'cover': 'game_pkg/webby/c.png'})

    def test_screenshots_are_a_bounded_list_with_required_alt(self):
        shots = [shot(f'{D}s{i}.png', 'The arena') for i in range(5)]
        self.assertEqual(len(avrgame.validate_manifest(with_art({'screenshots': shots}))['artwork']['screenshots']), 5)
        self.bad({'screenshots': shots + [shot(D + 's5.png')]}, 'at most 5')
        self.bad({'screenshots': 'x'}, 'must be a list')
        self.bad({'screenshots': ['x']}, 'must be an object')
        self.bad({'screenshots': [{'path': COVER}]}, "missing 'alt'")
        self.bad({'screenshots': [{'alt': 'x'}]}, "missing 'path'")
        for alt in ('', 'x' * 126, ' padded ', 'a\nb', 'a\u202eb', 7):
            self.bad({'screenshots': [shot(COVER, alt)]}, 'alt: 1-125 printable')
        ok = avrgame.validate_manifest(with_art({'screenshots': [shot(COVER, 'x' * 125)]}))
        self.assertEqual(len(ok['artwork']['screenshots'][0]['alt']), 125)

    def test_a_block_that_is_not_an_object_is_refused(self):
        for bad in ([], 'x', None, 3):
            self.bad(bad, 'artwork: must be an object')


class ImageParsers(unittest.TestCase):
    def bad(self, name, data, expect):
        with self.assertRaises(artwork._Bad) as ctx:
            artwork.inspect_image(name, data)
        self.assertIn(expect, str(ctx.exception))

    def test_dimensions_come_from_the_headers(self):
        self.assertEqual(artwork.inspect_image('a.png', png(200, 100))[:3], ('png', 200, 100))
        self.assertEqual(artwork.inspect_image('a.jpg', jpeg(300, 150))[:3], ('jpeg', 300, 150))
        self.assertEqual(artwork.inspect_image('a.jpeg', jpeg(33, 44))[:3], ('jpeg', 33, 44))
        self.assertEqual(artwork.inspect_image('a.webp', webp(640, 360))[:3], ('webp', 640, 360))
        self.assertEqual(artwork.inspect_image('a.webp', riff([(b'VP8 ', vp8(120, 90))]))[:3], ('webp', 120, 90))
        ext = riff([(b'VP8X', vp8x(70, 80)), (b'VP8L', vp8l(70, 80)), (b'EXIF', b'abcd')])
        self.assertEqual(artwork.inspect_image('a.webp', ext)[:3], ('webp', 70, 80))
        self.assertEqual(artwork.inspect_image('a.webp', ext)[3], ['EXIF'])

    def test_png_variants(self):
        rgba = png(8, 8, color=6, raw=(b'\x00' + b'\x00' * 32) * 8)
        self.assertEqual(artwork.inspect_image('a.png', rgba)[:3], ('png', 8, 8))
        bits = png(9, 3, depth=1, raw=(b'\x00' + b'\x00\x00') * 3)
        self.assertEqual(artwork.inspect_image('a.png', bits)[:3], ('png', 9, 3))

    def test_png_structure_is_walked(self):
        for label, data, expect in (
                ('crc', png(crc_fault=True), 'bad checksum'),
                ('trailing', png(trailing=b'\x00'), 'bytes after'),
                ('short data', png(raw=b'\x00' * 100), 'does not match'),
                ('long data', png(raw=b'\x00' * 70000), 'more PNG image data'),
                ('no iend', png()[:-12], 'no PNG IEND'),
                ('truncated', png()[:60], 'runs past'),
                ('apng', png(extra=[(b'acTL', struct.pack('>II', 2, 0))]), 'animated PNG'),
                ('palette missing', png(color=3, raw=b'\x00' * 2 * 256), 'PLTE'),
                ('bad color', png(color=1), 'invalid PNG color type'),
                ('too short', b'\x89PNG\r\n\x1a\n', 'too short')):
            with self.subTest(label):
                self.bad('a.png', data, expect)

    def test_pixel_limit_is_checked_before_the_data_is_looked_at(self):
        ihdr = png_chunk(b'IHDR', struct.pack('>IIBBBBB', 3000, 3000, 8, 0, 0, 0, 0))
        self.bad('a.png', b'\x89PNG\r\n\x1a\n' + ihdr + b'\x00' * 32, '2097152 pixels')
        self.bad('a.jpg', jpeg(2000, 2000), 'pixels')
        self.bad('a.webp', webp(2000, 2000), 'pixels')
        self.bad('a.webp', riff([(b'VP8X', vp8x(2000, 2000)), (b'VP8L', vp8l(2000, 2000))]), 'pixels')
        self.bad('a.webp', webp(2048, 1025), 'pixels')
        self.assertEqual(artwork.inspect_image('a.webp', webp(2048, 1024))[:3], ('webp', 2048, 1024))

    def test_jpeg_and_webp_structure(self):
        for label, name, data, expect in (
                ('no eoi', 'a.jpg', jpeg(eoi=False), 'EOI'),
                ('trailing', 'a.jpg', jpeg(trailing=b'\x00'), 'EOI'),
                ('truncated', 'a.jpg', jpeg()[:20], 'EOI'),
                ('no frame', 'a.jpg', b'\xff\xd8\xff\xfe\x00\x02\xff\xd9', 'no JPEG frame'),
                ('riff size', 'a.webp', webp(size_delta=2), 'RIFF size'),
                ('unknown first', 'a.webp', riff([(b'ABCD', b'1234')]), 'does not start'),
                ('no image', 'a.webp', riff([(b'VP8X', vp8x(8, 8)), (b'EXIF', b'ab')]), 'no WebP image'),
                ('canvas mismatch', 'a.webp', riff([(b'VP8X', vp8x(9, 9)), (b'VP8L', vp8l(8, 8))]), 'differs'),
                ('animated flag', 'a.webp', riff([(b'VP8X', vp8x(8, 8, flags=2)), (b'VP8L', vp8l(8, 8))]), 'animated WebP'),
                ('anim chunk', 'a.webp', riff([(b'VP8X', vp8x(8, 8)), (b'ANIM', b'\x00' * 6), (b'ANMF', b'\x00' * 16)]),
                 'animated WebP'),
                ('bad vp8l', 'a.webp', riff([(b'VP8L', b'\x00\x00\x00\x00\x00')]), 'VP8L')):
            with self.subTest(label):
                self.bad(name, data, expect)

    def test_a_long_run_of_fill_bytes_in_a_scan_is_linear(self):
        # Review of PR #140: FF+ in the end-of-scan search was quadratic on a long FF run (30 KB took
        # 10 s). A run larger than any allowed image must still be decided in well under a second.
        import time
        head = jpeg(eoi=False)
        for tail in (b'\x00\xff\xd9', b'\x12\xff\xd9', b'\xff\xd9'):
            data = head + b'\xff' * 300_000 + tail
            started = time.perf_counter()
            try:
                artwork.parse_jpeg(data)
            except artwork._Bad:
                pass
            self.assertLess(time.perf_counter() - started, 1.0, tail)
        self.assertEqual(artwork.parse_jpeg(head + b'\xff' * 1000 + b'\xff\xd9')[:2], (256, 256))


class ValidatorOnArchives(Tmp):
    def refuse(self, block, images, expect, extra=()):
        return self.refused(art_zip(block, images, extra), expect)

    def test_a_package_without_artwork_is_unchanged(self):
        package = avrgame.read(self.write_zip(make_zip()))
        self.assertNotIn('artwork', package.manifest)
        self.assertEqual([f.path for f in package.files], sorted(['avrgame.json', *BASE_FILES]))

    def test_valid_cover_and_icon_round_trip(self):
        block = {'cover': D + 'cover.webp', 'icon': D + 'icon.png'}
        path = self.write_zip(art_zip(block, {D + 'cover.webp': webp(512, 512), D + 'icon.png': png(128, 128)}))
        package = avrgame.read(path)
        self.assertEqual(package.manifest['artwork'], block)
        self.assertIn(D + 'cover.webp', [f.path for f in package.files])
        dest = self.tmp / 'out'
        avrgame.extract(path, dest)
        self.assertEqual((dest / D / 'icon.png').read_bytes(), png(128, 128))

    def test_every_role_and_every_format_validates(self):
        shots = [shot(f'{D}s{i}.jpg', f'Screen {i}') for i in range(3)]
        block = {'cover': D + 'c.jpg', 'icon': D + 'i.webp', 'banner': D + 'b.png', 'screenshots': shots}
        images = {D + 'c.jpg': jpeg(512, 512), D + 'i.webp': webp(64, 64), D + 'b.png': png(1280, 720),
                  D + 's0.jpg': jpeg(1080, 1920), D + 's1.jpg': jpeg(1920, 1080), D + 's2.jpg': jpeg(400, 400)}
        avrgame.read(self.write_zip(art_zip(block, images)))

    def test_role_dimensions(self):
        c, i, b, s = D + 'c.png', D + 'i.png', D + 'b.png', D + 's.png'
        self.refuse({'cover': c}, {c: png(256, 300)}, 'must be square')
        self.refuse({'cover': c}, {c: png(128, 128)}, '256 to 1024')
        self.refuse({'icon': i}, {i: png(32, 32)}, '64 to 512')
        self.refuse({'icon': D + 'i.webp'}, {D + 'i.webp': webp(513, 513)}, '64 to 512')
        self.refuse({'banner': b}, {b: png(800, 800)}, '16:9')
        self.refuse({'banner': b}, {b: png(320, 180)}, '640x360 to 1920x1080')
        self.refuse({'banner': b}, {b: png(1280, 760)}, '16:9')
        self.refuse({'screenshots': [shot(s)]}, {s: png(100, 400)}, 'between 9:16 and 16:9')
        self.refuse({'screenshots': [shot(D + 's.webp')]}, {D + 's.webp': webp(1081, 1921)}, '1920 pixels on its long side')
        avrgame.read(self.write_zip(art_zip({'banner': b}, {b: png(1280, 726)})))        # within 2%

    def test_missing_file_is_refused_and_every_problem_is_listed(self):
        problems = self.refuse({'cover': COVER, 'icon': D + 'icon.png'}, {}, 'the package has no file')
        self.assertEqual(len([p for p in problems if 'has no file' in p]), 2)

    def test_malformed_images_are_refused(self):
        self.refuse({'cover': COVER}, {COVER: b'not an image at all'}, 'not a WebP, PNG or JPEG image')
        self.refuse({'cover': COVER}, {COVER: webp(256, 256)[:-3]}, 'RIFF size')
        self.refuse({'cover': COVER}, {COVER: b''}, 'not a WebP, PNG or JPEG image')
        self.refuse({'cover': D + 'cover.png'}, {D + 'cover.png': png(crc_fault=True)}, 'bad checksum')

    def test_oversized_files_are_refused(self):
        self.refuse({'cover': D + 'c.png'}, {D + 'c.png': png(256, 256, pad=256 * 1024)}, 'at most 262144 bytes')
        self.refuse({'icon': D + 'i.png'}, {D + 'i.png': png(64, 64, pad=64 * 1024)}, 'at most 65536 bytes')
        self.refuse({'screenshots': [shot(D + 's.png')]}, {D + 's.png': png(400, 400, pad=384 * 1024)},
                    'at most 393216 bytes')

    def test_too_many_pixels_is_refused(self):
        self.refuse({'cover': D + 'c.png'}, {D + 'c.png': png(1500, 1500)}, '2097152 pixels')

    def test_total_artwork_bytes_are_capped(self):
        names = [f'{D}s{i}.png' for i in range(5)]
        images = {n: png(400, 400, pad=360 * 1024) for n in names}
        images[D + 'b.png'] = png(1280, 720, pad=370 * 1024)
        block = {'banner': D + 'b.png', 'screenshots': [shot(n) for n in names]}
        self.refuse(block, images, 'bytes in total; at most 2097152')
        images.pop(names[4])
        block['screenshots'] = block['screenshots'][:4]
        avrgame.read(self.write_zip(art_zip(block, images)))

    def test_a_file_declared_twice_counts_once(self):
        avrgame.read(self.write_zip(art_zip({'cover': D + 'a.png', 'screenshots': [shot(D + 'a.png')]},
                                            {D + 'a.png': png(256, 256)})))

    def test_type_must_agree_with_the_extension(self):
        self.refuse({'cover': D + 'c.webp'}, {D + 'c.webp': png(256, 256)}, 'is a PNG image but its name ends in .webp')
        self.refuse({'cover': D + 'c.png'}, {D + 'c.png': jpeg(256, 256)}, 'is a JPEG image but its name ends in .png')
        self.refuse({'cover': D + 'c.jpg'}, {D + 'c.jpg': webp(256, 256)}, 'is a WebP image but its name ends in .jpg')

    def test_svg_avif_gif_animated_webp_and_apng_are_refused(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><script>1</script></svg>'
        p = D + 'c.png'
        self.refuse({'cover': p}, {p: svg}, 'is an SVG')
        self.refuse({'cover': p}, {p: b'<?xml version="1.0"?>\n' + svg}, 'is an SVG')
        self.refuse({'cover': p}, {p: b'GIF89a\x01\x00\x01\x00\x00\x00\x00;'}, 'is a GIF')
        self.refuse({'cover': p}, {p: b'\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1'}, 'is an AVIF')
        self.refuse({'cover': p}, {p: png(256, 256, extra=[(b'acTL', struct.pack('>II', 2, 0))])}, 'animated PNG')
        anim = riff([(b'VP8X', vp8x(256, 256, flags=2)), (b'ANIM', b'\x00' * 6),
                     (b'ANMF', b'\x00' * 16 + vp8l(256, 256))])
        self.refuse({'cover': D + 'c.webp'}, {D + 'c.webp': anim}, 'animated WebP')
        for ext, name in (('svg', 'SVG'), ('avif', 'AVIF'), ('gif', 'GIF')):
            self.refuse({'cover': f'{D}c.{ext}'}, {f'{D}c.{ext}': svg}, f'{name} is not accepted')

    def test_paths_that_escape_or_point_away_are_refused_in_an_archive_too(self):
        for path, expect in (('/abs/c.png', 'absolute path'), ('http://example.invalid/c.png', 'remote URL'),
                             ('game_pkg/../c.png', '".." segments'), ('game_pkg\\c.png', 'backslash')):
            with self.subTest(path):
                self.refuse({'cover': path}, {}, expect)

    def test_a_symbolic_link_entry_is_refused(self):
        link = (stat.S_IFLNK | 0o777) << 16
        self.refuse({'cover': D + 'c.png'}, {}, 'only regular files and directories',
                    extra=[(D + 'c.png', b'../../../etc/passwd', link)])

    def test_an_image_under_client_root_is_refused(self):
        self.refuse({'cover': 'game_pkg/web/cover.png'}, {'game_pkg/web/cover.png': png(256, 256)}, 'outside client.root')

    def test_a_directory_is_not_an_image(self):
        self.refuse({'cover': 'game_pkg/artwork'}, {D + 'x.png': png(64, 64)}, 'must end in')


class Packer(Tmp):
    PINNED_ARTLESS_SHA256 = 'e3cda9392a54113107e92e87dd9c9c6cb64e9917fc9c77cf2891877ea64d1b79'
    PACKAGE = {'version': '0.1.0', 'publisher': 'Example Studio', 'license': 'MIT'}

    def tree(self, files, manifest):
        root = self.tmp / 'src'
        for name, data in {**BASE_FILES, **files}.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        mpath = root / 'avrgame.json'
        mpath.write_bytes(json.dumps(manifest, indent=2).encode())
        return root, mpath

    def test_an_artless_package_packs_to_the_same_bytes_as_before(self):
        # The digest was taken from the packer as it was before the artwork block existed.
        root, mpath = self.tree({}, good_manifest(package=self.PACKAGE))
        self.assertEqual(hashlib.sha256(avrgame.build_bytes(root, mpath, ['game_pkg'])).hexdigest(),
                         self.PINNED_ARTLESS_SHA256)

    def test_declared_artwork_is_packed_with_or_without_being_included(self):
        files = {COVER: webp(512, 512), 'extra/icon.png': png(96, 96)}
        block = {'cover': COVER, 'icon': 'extra/icon.png'}
        root, mpath = self.tree(files, with_art(block))
        out = self.tmp / 'x.avrgame'
        package = avrgame.pack(root, mpath, ['game_pkg'], out)        # extra/ is not in the includes
        self.assertEqual(package.manifest['artwork'], block)
        self.assertIn('extra/icon.png', [f.path for f in package.files])
        self.assertEqual(out.read_bytes(), avrgame.build_bytes(root, mpath, ['game_pkg', 'extra']))
        dest = self.tmp / 'out'
        avrgame.extract(out, dest)
        self.assertEqual((dest / 'extra' / 'icon.png').read_bytes(), png(96, 96))

    def test_the_packer_refuses_what_the_reader_refuses(self):
        root, mpath = self.tree({}, with_art({'cover': COVER}))
        with self.assertRaises(avrgame.Refused) as ctx:
            avrgame.build_bytes(root, mpath, ['game_pkg'])
        self.assertIn('the package has no file', '\n'.join(ctx.exception.problems))

    def test_a_declared_file_of_the_wrong_type_is_refused_by_the_packer(self):
        root, mpath = self.tree({COVER: png(256, 256)}, with_art({'cover': COVER}))
        with self.assertRaises(avrgame.Refused) as ctx:
            avrgame.build_bytes(root, mpath, ['game_pkg'])
        self.assertIn('is a PNG image but its name ends in .webp', '\n'.join(ctx.exception.problems))

    def test_a_linked_artwork_file_is_refused(self):
        real = self.tmp / 'real.webp'
        real.write_bytes(webp(256, 256))
        root, mpath = self.tree({}, with_art({'cover': COVER}))
        link = root / COVER
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(real, link)
        except (OSError, NotImplementedError):
            self.skipTest('symbolic links are not available here')
        with self.assertRaises(avrgame.Refused) as ctx:
            avrgame.build_bytes(root, mpath, ['game_pkg'])
        self.assertIn('symbolic links are refused', '\n'.join(ctx.exception.problems))

    def test_metadata_in_an_image_is_a_warning_not_a_refusal(self):
        p = D + 'c.jpg'
        root, mpath = self.tree({p: jpeg(256, 256, app1=b'Exif\x00\x00II*\x00')}, with_art({'cover': p}))
        notes = []
        self.assertTrue(avrgame.build_bytes(root, mpath, ['game_pkg'], warnings=notes))
        self.assertEqual(len(notes), 1)
        self.assertIn('EXIF', notes[0])
        root, mpath = self.tree({p: jpeg(256, 256)}, with_art({'cover': p}))
        quiet = []
        avrgame.build_bytes(root, mpath, ['game_pkg'], warnings=quiet)
        self.assertEqual(quiet, [])


if __name__ == '__main__':
    unittest.main()
