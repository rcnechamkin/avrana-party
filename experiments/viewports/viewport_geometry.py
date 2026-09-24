"""Personal Viewports geometry — test vectors for docs/design/PERSONAL-VIEWPORTS.md.

Pure math, stdlib only. No browser, no video, no Pi. It pins down what a per-title viewport
profile means (which rectangle of the ONE shared encoded frame each seat's phone shows) and the
arithmetic a client would use to crop it (CSS or canvas), so the eventual proof of concept has
fixed expectations. Nothing in production imports it.

Profile shape (draft; the real format is still an open question):
    {"v": 0, "grid": [640, 480], "content": [0, 0, 640, 480], "aspect": "4:3", "inset": 2,
     "layouts": {"4": {"seats": {"1": [0, 0, 320, 240], ...}, "shared": {"map": [...]}}}}
Rectangles are [x, y, w, h] in the pixel grid of a reference screenshot of the capture;
"content" is the active picture inside that grid (letterboxing/overscan excluded);
"aspect" is the display aspect of the content area.
"""
from fractions import Fraction


class LayoutError(ValueError):
    pass


def _aspect(text):
    a, b = text.split(':')
    return Fraction(int(a), int(b))


def seat_rects(profile, layout_key, inset=None):
    """Return {seat: (x, y, w, h)} normalized to the CONTENT area (0..1), inset applied.

    Validates the layout: every rectangle inside the content area, seats numbered 1..N with
    no gaps, seat rectangles not overlapping each other.
    """
    gx, gy = profile['grid']
    cx, cy, cw, ch = profile.get('content', [0, 0, gx, gy])
    if not (0 <= cx and 0 <= cy and cx + cw <= gx and cy + ch <= gy):
        raise LayoutError('content area outside the grid')
    layout = profile['layouts'].get(layout_key)
    if layout is None:
        raise LayoutError(f'no layout {layout_key!r}')
    seats = layout['seats']
    if sorted(int(s) for s in seats) != list(range(1, len(seats) + 1)):
        raise LayoutError('seats must be numbered 1..N')
    pad = profile.get('inset', 0) if inset is None else inset
    out = {}
    for seat, (x, y, w, h) in seats.items():
        if x < cx or y < cy or x + w > cx + cw or y + h > cy + ch or w <= 0 or h <= 0:
            raise LayoutError(f'seat {seat} outside the content area')
        if w <= 2 * pad or h <= 2 * pad:
            raise LayoutError(f'seat {seat} smaller than its inset')
        out[int(seat)] = (Fraction(x - cx + pad, cw), Fraction(y - cy + pad, ch),
                          Fraction(w - 2 * pad, cw), Fraction(h - 2 * pad, ch))
    rects = list(seats.values())
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            if a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]:
                raise LayoutError('seat rectangles overlap')
    return out


def crop_aspect(rect, profile):
    """Display aspect of a normalized crop: a = (w / h) * D, D = display aspect of the content."""
    _, _, w, h = rect
    return (w / h) * _aspect(profile['aspect'])


def fit(aspect, box_w, box_h, mode='contain'):
    """Size of the crop on a phone box. Returns (width, height, fraction).

    contain: the whole crop is visible; fraction = share of the box it fills.
    cover:   the box is filled; fraction = share of the crop that is cut off.
    """
    aspect = Fraction(aspect)
    box = Fraction(box_w) / Fraction(box_h)
    share = min(aspect / box, box / aspect)
    if mode == 'contain':
        if aspect > box:
            return Fraction(box_w), Fraction(box_w) / aspect, share
        return Fraction(box_h) * aspect, Fraction(box_h), share
    if mode == 'cover':
        if aspect > box:
            return Fraction(box_h) * aspect, Fraction(box_h), 1 - share
        return Fraction(box_w), Fraction(box_w) / aspect, 1 - share
    raise ValueError(mode)


def orientation(aspect):
    """Recommended phone orientation for a crop: wide crops want landscape."""
    return 'landscape' if aspect > 1 else 'portrait'


def css_crop(rect, content=(0, 0, 1, 1)):
    """CSS for a <video> inside an overflow:hidden container whose aspect equals the crop's.

    `content` is the content area as a normalized rectangle of the whole video frame
    (letterboxing). Returns percentages of the container: the video element is scaled so the
    crop fills the container exactly.
    """
    ax, ay, aw, ah = (Fraction(v) for v in content)
    x, y, w, h = rect
    fx, fy, fw, fh = ax + x * aw, ay + y * ah, w * aw, h * ah   # crop in whole-frame units
    return {'width': 100 / fw, 'height': 100 / fh, 'left': -100 * fx / fw, 'top': -100 * fy / fh}


def canvas_source(rect, video_w, video_h, content=(0, 0, 1, 1)):
    """drawImage source rectangle (sx, sy, sw, sh) in the decoded video's pixels."""
    ax, ay, aw, ah = (Fraction(v) for v in content)
    x, y, w, h = rect
    return ((ax + x * aw) * video_w, (ay + y * ah) * video_h, w * aw * video_w, h * ah * video_h)


def split_lines_on_macroblocks(profile, layout_key, encode_w, encode_h, mb=16):
    """Do the seat boundaries fall on H.264 macroblock edges at this encode size?

    Boundaries inside a macroblock make neighbouring players' pixels share blocks, which
    increases edge bleed at low bitrates. Returns (ok, [offending pixel positions]).
    """
    gx, gy = profile['grid']
    bad = []
    for x, y, w, h in profile['layouts'][layout_key]['seats'].values():
        for px in (x, x + w):
            ex = Fraction(px * encode_w, gx)
            if 0 < ex < encode_w and ex % mb:
                bad.append(('x', ex))
        for py in (y, y + h):
            ey = Fraction(py * encode_h, gy)
            if 0 < ey < encode_h and ey % mb:
                bad.append(('y', ey))
    return (not bad), sorted(set(bad))


def native_pixels(rect, native_w, native_h):
    """How many of the GAME's native pixels a crop contains (e.g. PS1 320x240)."""
    _, _, w, h = rect
    return w * native_w, h * native_h
