"""Bundled artwork of an experimental .avrgame package: the optional `artwork` manifest block.

EXPERIMENTAL: names and limits may change. Standard library only. An image is UNTRUSTED INPUT even
when it validates: nothing here decodes pixels, executes or evaluates anything. The type comes from
the magic bytes and must agree with the file extension, dimensions come from the header, and the
structure of the file is walked (PNG chunks and CRCs and a bounded inflate of the image data, JPEG
segments from SOI to EOI, WebP RIFF chunks). SVG, AVIF, GIF, animated WebP and APNG are refused.

The block is additive and optional: a package without it is validated exactly as before.
"""
import re
import struct
import zlib

from .common import clip, name_problem, text_ok

MAX_ART_PIXELS = 2097152            # per image
MAX_ART_TOTAL_BYTES = 2 * 1024 * 1024
MAX_SCREENSHOTS = 5
MAX_ALT = 125
MAX_JPEG_SEGMENTS = 512
MAX_CHUNKS = 512

KEYS = ('cover', 'icon', 'banner', 'screenshots')
# role -> (max bytes, min side, max side); cover and icon are exactly 1:1
COVER_LIMITS = (256 * 1024, 256, 1024)
ICON_LIMITS = (64 * 1024, 64, 512)
BANNER_LIMITS = (384 * 1024, 640, 1920)       # 16:9 within 2%; width 640..1920 and height 360..1080
BANNER_MAX_HEIGHT = 1080
BANNER_MIN_HEIGHT = 360
BANNER_TOLERANCE_PERCENT = 2
SCREENSHOT_MAX_BYTES = 384 * 1024
SCREENSHOT_MAX_LONG_SIDE = 1920

EXTENSIONS = {'.webp': 'webp', '.png': 'png', '.jpg': 'jpeg', '.jpeg': 'jpeg'}
REFUSED_EXTENSIONS = {
    '.svg': 'SVG', '.svgz': 'SVG', '.avif': 'AVIF', '.gif': 'GIF', '.apng': 'APNG',
}
KIND_NAMES = {'webp': 'WebP', 'png': 'PNG', 'jpeg': 'JPEG'}
SCHEME = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]+:')


class _Bad(Exception):
    """One image problem, as a sentence."""


# ---- the manifest block ------------------------------------------------------------------------------------------

def path_problem(value, where, client_root=None):
    """Why `value` cannot name a bundled image, or None."""
    if not isinstance(value, str):
        return f'{where}: must be a path string'
    if SCHEME.match(value) or value.startswith('//'):
        return (f'{where} {clip(value)}: a remote URL or scheme is not allowed; '
                'bundled artwork is a file inside the package')
    why = name_problem(value, where)
    if why:
        return why
    ext = '.' + value.rsplit('.', 1)[-1].lower() if '.' in value.rsplit('/', 1)[-1] else ''
    if ext in REFUSED_EXTENSIONS:
        return f'{where} {clip(value)}: {REFUSED_EXTENSIONS[ext]} is not accepted; use WebP, PNG or JPEG'
    if ext not in EXTENSIONS:
        return f'{where} {clip(value)}: the name must end in .webp, .png, .jpg or .jpeg'
    if isinstance(client_root, str) and client_root:
        low, root = value.lower(), client_root.lower().rstrip('/')
        if low == root or low.startswith(root + '/'):
            return f'{where} {clip(value)}: must be outside client.root (the game server never serves package artwork)'
    return None


def validate_block(block, client_root, problems):
    """Check the shape of the `artwork` block and return its normalised copy (or None when it is not
    an object). Adds every problem to `problems`; reads no file."""
    if not isinstance(block, dict):
        problems.add('artwork: must be an object')
        return None
    out = {}
    for key in sorted(block):
        if key == 'credit':
            problems.add("artwork: unknown key 'credit' (there is no credit field; credit wording belongs in the "
                         'publisher documentation)')
        elif key not in KEYS:
            problems.add(f'artwork: unknown key {clip(key)}')
    for key in ('cover', 'icon', 'banner'):
        if key in block:
            why = path_problem(block[key], f'artwork.{key}', client_root)
            if why:
                problems.add(why)
            else:
                out[key] = block[key]
    if 'screenshots' in block:
        shots = block['screenshots']
        if not isinstance(shots, list):
            problems.add('artwork.screenshots: must be a list')
        else:
            if len(shots) > MAX_SCREENSHOTS:
                problems.add(f'artwork.screenshots: {len(shots)} entries; at most {MAX_SCREENSHOTS} are allowed')
            kept = []
            for i, item in enumerate(shots[:MAX_SCREENSHOTS]):
                where = f'artwork.screenshots[{i}]'
                if not isinstance(item, dict):
                    problems.add(f'{where}: must be an object with "path" and "alt"')
                    continue
                for k in sorted(set(item) - {'path', 'alt'}):
                    problems.add(f'{where}: unknown key {clip(k)}')
                for k in ('path', 'alt'):
                    if k not in item:
                        problems.add(f'{where}: missing {k!r}')
                if 'path' in item:
                    why = path_problem(item['path'], f'{where}.path', client_root)
                    if why:
                        problems.add(why)
                if 'alt' in item and not text_ok(item['alt'], 1, MAX_ALT):
                    problems.add(f'{where}.alt: 1-{MAX_ALT} printable characters')
                if (isinstance(item.get('path'), str) and isinstance(item.get('alt'), str)
                        and 'path' in item and 'alt' in item):
                    kept.append({'path': item['path'], 'alt': item['alt']})
            out['screenshots'] = kept
    return out


def declared(block):
    """[(role, path)] for every image the normalised block declares, in a fixed order."""
    out = [(key, block[key]) for key in ('cover', 'icon', 'banner') if key in block]
    out.extend((f'screenshots[{i}]', s['path']) for i, s in enumerate(block.get('screenshots', ())))
    return out


def declared_paths(block):
    return sorted({path for _, path in declared(block)})


def missing_problems(block, names):
    """One problem per declared image that is not a file of the package."""
    return [f'artwork.{role}: the package has no file {clip(path)}'
            for role, path in declared(block) if path not in names]


# ---- image parsing -----------------------------------------------------------------------------------------------

def _pixels(width, height):
    if width < 1 or height < 1:
        raise _Bad('has a zero dimension')
    if width * height > MAX_ART_PIXELS:
        raise _Bad(f'is {width}x{height}; at most {MAX_ART_PIXELS} pixels are allowed')


def sniff(data):
    """'png' | 'jpeg' | 'webp' for an accepted type, else raises _Bad naming what it looks like."""
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return 'png'
    if data[:3] == b'\xff\xd8\xff':
        return 'jpeg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    if data[:4] == b'GIF8':
        raise _Bad('is a GIF; GIF is not accepted (use WebP, PNG or JPEG)')
    if data[4:8] == b'ftyp' and data[8:12] in (b'avif', b'avis'):
        raise _Bad('is an AVIF image; AVIF is not accepted (use WebP, PNG or JPEG)')
    head = data[:512].lstrip(b'\xef\xbb\xbf \t\r\n').lower()
    if head.startswith((b'<svg', b'<?xml', b'<!doctype svg', b'<!--')) or b'<svg' in head:
        raise _Bad('is an SVG; SVG is not accepted (use WebP, PNG or JPEG)')
    raise _Bad('is not a WebP, PNG or JPEG image (the content decides the type, not the file name)')


PNG_CHANNELS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
PNG_SAMPLES = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _png_raw_size(width, height, color, depth, interlace):
    bits = PNG_SAMPLES[color] * depth

    def rows(w, h):
        return 0 if w == 0 or h == 0 else h * (1 + (w * bits + 7) // 8)
    if not interlace:
        return rows(width, height)
    total = 0
    for x0, y0, dx, dy in ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
                           (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)):
        total += rows((width - x0 + dx - 1) // dx, (height - y0 + dy - 1) // dy)
    return total


def parse_png(data):
    """(width, height, notes) for a static PNG, or raises _Bad."""
    if len(data) < 8 + 25 + 12:
        raise _Bad('is too short to be a PNG')
    pos, count = 8, 0
    size = width = height = 0
    expected = 0
    inflater = None
    produced = 0
    idat_state = 0              # 0 none yet, 1 inside the run of IDAT chunks, 2 run finished
    seen_iend = False
    notes = []
    palette = False
    color = depth = 0
    while pos < len(data):
        count += 1
        if count > MAX_CHUNKS:
            raise _Bad(f'has more than {MAX_CHUNKS} PNG chunks')
        if pos + 8 > len(data):
            raise _Bad('has a truncated PNG chunk header')
        length, kind = struct.unpack('>I4s', data[pos:pos + 8])
        if length > 0x7fffffff or pos + 12 + length > len(data):
            raise _Bad('has a PNG chunk that runs past the end of the file')
        body = data[pos + 8:pos + 8 + length]
        (crc,) = struct.unpack('>I', data[pos + 8 + length:pos + 12 + length])
        if count == 1:
            if kind != b'IHDR' or length != 13:
                raise _Bad('does not start with a PNG IHDR chunk')
            width, height, depth, color, comp, filt, interlace = struct.unpack('>IIBBBBB', body)
            _pixels(width, height)                      # before any other work
            if color not in PNG_CHANNELS or depth not in PNG_CHANNELS[color]:
                raise _Bad('has an invalid PNG color type or bit depth')
            if comp != 0 or filt != 0 or interlace not in (0, 1):
                raise _Bad('has an invalid PNG compression, filter or interlace method')
            expected = _png_raw_size(width, height, color, depth, interlace)
            inflater = zlib.decompressobj()
        if zlib.crc32(kind + body) & 0xffffffff != crc:
            raise _Bad(f'has a PNG chunk {clip(kind.decode("latin-1"), 12)} with a bad checksum')
        if kind == b'acTL' or kind == b'fcTL' or kind == b'fdAT':
            raise _Bad('is an animated PNG (APNG); animation is not accepted')
        if kind == b'IHDR' and count != 1:
            raise _Bad('has a second PNG IHDR chunk')
        if kind == b'PLTE':
            palette = True
        if kind == b'eXIf' or (kind in (b'iTXt', b'tEXt', b'zTXt') and b'XML:com.adobe.xmp' in body[:32]):
            notes.append('EXIF' if kind == b'eXIf' else 'XMP')
        if kind == b'IDAT':
            if idat_state == 2:
                raise _Bad('has PNG image data in separate runs')
            if color == 3 and not palette:
                raise _Bad('has a palette PNG without a PLTE chunk before its image data')
            idat_state = 1
            try:
                out = inflater.decompress(body, expected - produced + 1)
            except zlib.error:
                raise _Bad('has PNG image data that does not inflate') from None
            produced += len(out)
            if produced > expected or inflater.unconsumed_tail:
                raise _Bad('has more PNG image data than its header implies')
        else:
            if idat_state == 1:
                idat_state = 2
        pos += 12 + length
        if kind == b'IEND':
            if length != 0:
                raise _Bad('has a PNG IEND chunk with content')
            seen_iend = True
            break
    if not seen_iend:
        raise _Bad('has no PNG IEND chunk')
    if pos != len(data):
        raise _Bad('has bytes after the PNG IEND chunk')
    if idat_state == 0:
        raise _Bad('has no PNG image data')
    if not inflater.eof or inflater.unused_data:
        raise _Bad('has PNG image data that is incomplete or has trailing bytes')
    if produced != expected:
        raise _Bad('has PNG image data whose size does not match its header')
    return width, height, sorted(set(notes))


SOF_ACCEPTED = (0xC0, 0xC1, 0xC2)
SOF_ALL = tuple(m for m in range(0xC0, 0xD0) if m not in (0xC4, 0xC8, 0xCC))
_ENTROPY_END = re.compile(rb'\xff+([\x01-\xcf\xd8-\xfe])')


def parse_jpeg(data):
    """(width, height, notes) for a JPEG, or raises _Bad. Pixels are not decoded."""
    if len(data) < 4 or data[:2] != b'\xff\xd8':
        raise _Bad('does not start with a JPEG SOI marker')
    if data[-2:] != b'\xff\xd9':
        raise _Bad('does not end with a JPEG EOI marker')
    pos, count = 2, 0
    width = height = 0
    scans = 0
    notes = []
    while True:
        # a marker: FF, optional FF fill, then the code
        if pos >= len(data) or data[pos] != 0xFF:
            raise _Bad('has a malformed JPEG marker')
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            raise _Bad('has a truncated JPEG')
        marker = data[pos]
        pos += 1
        if marker == 0xD9:
            if pos != len(data):
                raise _Bad('has bytes after the JPEG EOI marker')
            break
        count += 1
        if count > MAX_JPEG_SEGMENTS:
            raise _Bad(f'has more than {MAX_JPEG_SEGMENTS} JPEG segments')
        if marker in (0x00, 0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            raise _Bad('has an unexpected JPEG marker')
        if pos + 2 > len(data):
            raise _Bad('has a truncated JPEG segment')
        (length,) = struct.unpack('>H', data[pos:pos + 2])
        if length < 2 or pos + length > len(data):
            raise _Bad('has a JPEG segment that runs past the end of the file')
        seg = data[pos + 2:pos + length]
        if marker in SOF_ALL:
            if marker not in SOF_ACCEPTED:
                raise _Bad('uses a JPEG process that is not accepted (baseline, extended or progressive only)')
            if width:
                raise _Bad('has two JPEG frame headers')
            if len(seg) < 6:
                raise _Bad('has a truncated JPEG frame header')
            precision, height, width, comps = struct.unpack('>BHHB', seg[:6])
            if precision != 8 or comps not in (1, 3) or len(seg) != 6 + 3 * comps:
                raise _Bad('has an unsupported JPEG precision or component count')
            _pixels(width, height)
        elif marker == 0xE1:
            if seg.startswith(b'Exif\x00\x00'):
                notes.append('EXIF')
            elif seg.startswith(b'http://ns.adobe.com/xap/1.0/\x00'):
                notes.append('XMP')
        elif marker == 0xDA:
            if not width:
                raise _Bad('has a JPEG scan before its frame header')
            scans += 1
            pos += length
            found = _ENTROPY_END.search(data, pos)
            if not found:
                raise _Bad('has a JPEG scan that never ends')
            pos = found.start()
            continue
        pos += length
    if not width or not scans:
        raise _Bad('has no JPEG frame or scan')
    return width, height, sorted(set(notes))


def _le(data, start, n):
    return int.from_bytes(data[start:start + n], 'little')


def _vp8_size(body):
    if len(body) < 10 or body[3:6] != b'\x9d\x01\x2a':
        raise _Bad('has a malformed WebP VP8 header')
    if body[0] & 1:
        raise _Bad('has a WebP VP8 frame that is not a key frame')
    return _le(body, 6, 2) & 0x3fff, _le(body, 8, 2) & 0x3fff


def _vp8l_size(body):
    if len(body) < 5 or body[0] != 0x2f:
        raise _Bad('has a malformed WebP VP8L header')
    bits = _le(body, 1, 4)
    if bits >> 29:
        raise _Bad('has an unsupported WebP VP8L version')
    return (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1


def parse_webp(data):
    """(width, height, notes) for a static WebP, or raises _Bad."""
    if len(data) < 20:
        raise _Bad('is too short to be a WebP')
    if _le(data, 4, 4) + 8 != len(data):
        raise _Bad('has a WebP RIFF size that does not equal the file length')
    pos, count = 12, 0
    canvas = None
    frame = None
    first = True
    notes = []
    while pos < len(data):
        count += 1
        if count > MAX_CHUNKS:
            raise _Bad(f'has more than {MAX_CHUNKS} WebP chunks')
        if pos + 8 > len(data):
            raise _Bad('has a truncated WebP chunk header')
        kind, size = data[pos:pos + 4], _le(data, pos + 4, 4)
        body_end = pos + 8 + size
        if body_end > len(data):
            raise _Bad('has a WebP chunk that runs past the end of the file')
        body = data[pos + 8:body_end]
        if kind in (b'ANIM', b'ANMF'):
            raise _Bad('is an animated WebP; animation is not accepted')
        if first:
            if kind not in (b'VP8 ', b'VP8L', b'VP8X'):
                raise _Bad('does not start with a WebP VP8, VP8L or VP8X chunk')
            first = False
        if kind == b'VP8X':
            if count != 1 or size != 10:
                raise _Bad('has a malformed WebP VP8X chunk')
            if body[0] & 0x02:
                raise _Bad('is an animated WebP; animation is not accepted')
            canvas = (_le(body, 4, 3) + 1, _le(body, 7, 3) + 1)
            _pixels(*canvas)                              # before the rest of the walk
        elif kind in (b'VP8 ', b'VP8L'):
            if frame is not None:
                raise _Bad('has more than one WebP image chunk')
            frame = _vp8_size(body) if kind == b'VP8 ' else _vp8l_size(body)
            _pixels(*frame)
        elif kind == b'EXIF':
            notes.append('EXIF')
        elif kind == b'XMP ':
            notes.append('XMP')
        pos = body_end + (size & 1)
    if pos != len(data):
        raise _Bad('has a WebP chunk whose padding runs past the end of the file')
    if frame is None:
        raise _Bad('has no WebP image chunk')
    if canvas is not None and canvas != frame:
        raise _Bad('has a WebP canvas size that differs from its image size')
    return frame[0], frame[1], sorted(set(notes))


PARSERS = {'png': parse_png, 'jpeg': parse_jpeg, 'webp': parse_webp}


def inspect_image(path, data):
    """(kind, width, height, notes) for the bytes of the file named `path`, or raises _Bad. The type is
    taken from the content and must agree with the extension."""
    kind = sniff(data)
    ext = '.' + path.rsplit('.', 1)[-1].lower()
    if EXTENSIONS.get(ext) != kind:
        raise _Bad(f'is a {KIND_NAMES[kind]} image but its name ends in {ext}')
    width, height, notes = PARSERS[kind](data)
    return kind, width, height, notes


# ---- shape and size rules per role -------------------------------------------------------------------------------

def _role_rule(role, width, height):
    """Raises _Bad when the dimensions do not suit the role."""
    if role in ('cover', 'icon'):
        _, low, high = COVER_LIMITS if role == 'cover' else ICON_LIMITS
        if width != height:
            raise _Bad(f'is {width}x{height}; a {role} must be square (1:1)')
        if not low <= width <= high:
            raise _Bad(f'is {width}x{height}; a {role} is {low} to {high} pixels on a side')
    elif role == 'banner':
        if abs(width * 9 - height * 16) * 100 > BANNER_TOLERANCE_PERCENT * height * 16:
            raise _Bad(f'is {width}x{height}; a banner is 16:9 within {BANNER_TOLERANCE_PERCENT}%')
        if not (BANNER_LIMITS[1] <= width <= BANNER_LIMITS[2] and BANNER_MIN_HEIGHT <= height <= BANNER_MAX_HEIGHT):
            raise _Bad(f'is {width}x{height}; a banner is 640x360 to 1920x1080')
    else:
        if width * 9 > height * 16 or width * 16 < height * 9:
            raise _Bad(f'is {width}x{height}; a screenshot is between 9:16 and 16:9')
        if max(width, height) > SCREENSHOT_MAX_LONG_SIDE:
            raise _Bad(f'is {width}x{height}; a screenshot is at most {SCREENSHOT_MAX_LONG_SIDE} pixels on its long side')


def _byte_limit(role):
    if role == 'cover':
        return COVER_LIMITS[0]
    if role == 'icon':
        return ICON_LIMITS[0]
    if role == 'banner':
        return BANNER_LIMITS[0]
    return SCREENSHOT_MAX_BYTES


def file_problems(block, sizes, read):
    """Check every declared image against the package's files. `sizes` maps a file name to its size in
    bytes and `read(name)` returns its bytes (called only for a file within its byte limit). Returns
    (problems, notes) where notes is {path: [metadata kinds]} for the pack-time warning."""
    problems, notes = [], {}
    total = 0
    counted = set()
    results = {}
    for role, path in declared(block):
        where = f'artwork.{role} {clip(path)}'
        if path not in sizes:
            continue                                    # reported by missing_problems
        size = sizes[path]
        if path not in counted:
            counted.add(path)
            total += size
        if size > _byte_limit(role):
            problems.append(f'{where}: {size} bytes; a {role.split("[")[0]} is at most {_byte_limit(role)} bytes')
            continue
        try:
            if path not in results:
                results[path] = inspect_image(path, read(path))
            _, width, height, found = results[path]
            _role_rule(role, width, height)
            if found:
                notes[path] = found
        except _Bad as exc:
            problems.append(f'{where}: {exc}')
    if total > MAX_ART_TOTAL_BYTES:
        problems.append(f'artwork: {total} bytes in total; at most {MAX_ART_TOTAL_BYTES} are allowed')
    return problems, notes


def metadata_warnings(notes):
    """Sentences for `pack`: EXIF/GPS or XMP in a bundled image is allowed but worth removing."""
    return [f'artwork {clip(path)}: carries {" and ".join(kinds)} metadata (GPS and camera details may be in it); '
            'consider stripping it' for path, kinds in sorted(notes.items())]
