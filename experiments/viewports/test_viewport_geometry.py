"""Test vectors for Personal Viewports geometry (stdlib only).
    python experiments/viewports/test_viewport_geometry.py
"""
import os
import sys
import unittest
from fractions import Fraction as F

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import viewport_geometry as vg  # noqa: E402

# A 640x480 square-pixel 4:3 capture (today's Xvfb/RetroArch setup for PS1 and the arcade).
PROFILE = {
    'v': 0, 'grid': [640, 480], 'content': [0, 0, 640, 480], 'aspect': '4:3', 'inset': 0,
    'layouts': {
        '2h': {'seats': {'1': [0, 0, 640, 240], '2': [0, 240, 640, 240]}},
        '2v': {'seats': {'1': [0, 0, 320, 480], '2': [320, 0, 320, 480]}},
        '3': {'seats': {'1': [0, 0, 640, 240], '2': [0, 240, 320, 240], '3': [320, 240, 320, 240]}},
        '3q': {'seats': {'1': [0, 0, 320, 240], '2': [320, 0, 320, 240], '3': [0, 240, 320, 240]},
               'shared': {'map': [320, 240, 320, 240]}},
        '4': {'seats': {'1': [0, 0, 320, 240], '2': [320, 0, 320, 240],
                        '3': [0, 240, 320, 240], '4': [320, 240, 320, 240]}},
    },
}
IPHONE_LANDSCAPE = (750, 369)   # usable CSS px on an 844x390 iPhone after safe areas/controls
IPHONE_PORTRAIT = (390, 844)


class Layouts(unittest.TestCase):
    def test_quadrants(self):
        r = vg.seat_rects(PROFILE, '4')
        self.assertEqual(r[1], (0, 0, F(1, 2), F(1, 2)))
        self.assertEqual(r[4], (F(1, 2), F(1, 2), F(1, 2), F(1, 2)))
        self.assertEqual({vg.crop_aspect(v, PROFILE) for v in r.values()}, {F(4, 3)})

    def test_two_player_splits(self):
        h = vg.seat_rects(PROFILE, '2h')
        v = vg.seat_rects(PROFILE, '2v')
        self.assertEqual(vg.crop_aspect(h[1], PROFILE), F(8, 3))     # wide: landscape
        self.assertEqual(vg.crop_aspect(v[2], PROFILE), F(2, 3))     # tall: portrait
        self.assertEqual(vg.orientation(vg.crop_aspect(h[1], PROFILE)), 'landscape')
        self.assertEqual(vg.orientation(vg.crop_aspect(v[1], PROFILE)), 'portrait')

    def test_three_player_asymmetric_and_map(self):
        r = vg.seat_rects(PROFILE, '3')
        self.assertEqual([vg.crop_aspect(r[s], PROFILE) for s in (1, 2, 3)], [F(8, 3), F(4, 3), F(4, 3)])
        q = vg.seat_rects(PROFILE, '3q')
        self.assertEqual(len(q), 3)                          # the shared map is not a seat

    def test_inset_trims_edges(self):
        r = vg.seat_rects(PROFILE, '4', inset=2)
        self.assertEqual(r[1], (F(2, 640), F(2, 480), F(316, 640), F(236, 480)))

    def test_letterboxed_content_area(self):
        boxed = dict(PROFILE, content=[0, 60, 640, 360], aspect='16:9',
                     layouts={'2h': {'seats': {'1': [0, 60, 640, 180], '2': [0, 240, 640, 180]}}})
        r = vg.seat_rects(boxed, '2h')
        self.assertEqual(r[2], (0, F(1, 2), 1, F(1, 2)))
        self.assertEqual(vg.crop_aspect(r[1], boxed), F(32, 9))

    def test_invalid_layouts_rejected(self):
        bad = [
            {'1': [0, 0, 400, 240], '2': [320, 0, 320, 240]},            # overlap
            {'1': [0, 0, 700, 240]},                                    # outside
            {'1': [0, 0, 320, 240], '3': [320, 0, 320, 240]},            # gap in numbering
        ]
        for seats in bad:
            with self.assertRaises(vg.LayoutError):
                vg.seat_rects(dict(PROFILE, layouts={'x': {'seats': seats}}), 'x')
        with self.assertRaises(vg.LayoutError):
            vg.seat_rects(PROFILE, 'nope')


class PhoneFit(unittest.TestCase):
    def test_quadrant_landscape_contain(self):
        w, h, fill = vg.fit(F(4, 3), *IPHONE_LANDSCAPE)
        self.assertEqual((w, h), (492, 369))
        self.assertAlmostEqual(float(fill), 0.656, places=3)

    def test_wide_half_needs_landscape(self):
        _, h_land, fill_land = vg.fit(F(8, 3), *IPHONE_LANDSCAPE)
        _, _, fill_port = vg.fit(F(8, 3), *IPHONE_PORTRAIT)
        self.assertAlmostEqual(float(h_land), 281.25)
        self.assertAlmostEqual(float(fill_land), 0.76, places=2)
        self.assertLess(fill_port, F(1, 5))                   # ~17%: portrait is useless here

    def test_tall_half_prefers_portrait(self):
        _, _, fill_port = vg.fit(F(2, 3), *IPHONE_PORTRAIT)
        _, _, fill_land = vg.fit(F(2, 3), *IPHONE_LANDSCAPE)
        self.assertGreater(fill_port, fill_land)

    def test_cover_reports_what_is_cut(self):
        _, _, lost = vg.fit(F(4, 3), *IPHONE_LANDSCAPE, mode='cover')
        self.assertAlmostEqual(float(lost), 1 - 0.656, places=3)


class ClientCrop(unittest.TestCase):
    def test_css_crop_quadrant(self):
        css = vg.css_crop(vg.seat_rects(PROFILE, '4')[4])
        self.assertEqual(css, {'width': 200, 'height': 200, 'left': -100, 'top': -100})

    def test_css_crop_round_trip(self):
        # The visible window of a video scaled/offset by css_crop is exactly the seat rectangle.
        for key in ('2h', '2v', '3', '4'):
            for rect in vg.seat_rects(PROFILE, key, inset=2).values():
                css = vg.css_crop(rect)
                vis_x = -css['left'] / css['width']
                vis_y = -css['top'] / css['height']
                self.assertEqual((vis_x, vis_y, 100 / css['width'], 100 / css['height']), rect)

    def test_css_crop_with_letterbox(self):
        css = vg.css_crop((0, 0, 1, F(1, 2)), content=(0, F(1, 8), 1, F(3, 4)))
        self.assertEqual(css['top'], -100 * F(1, 8) / F(3, 8))

    def test_canvas_source_rect(self):
        r = vg.seat_rects(PROFILE, '4')[2]
        self.assertEqual(vg.canvas_source(r, 640, 480), (320, 0, 320, 240))
        self.assertEqual(vg.canvas_source(r, 1280, 960), (640, 0, 640, 480))


class EncodeAndDetail(unittest.TestCase):
    def test_macroblock_alignment(self):
        self.assertTrue(vg.split_lines_on_macroblocks(PROFILE, '4', 640, 480)[0])
        self.assertTrue(vg.split_lines_on_macroblocks(PROFILE, '4', 1280, 960)[0])
        ok, bad = vg.split_lines_on_macroblocks(PROFILE, '4', 1280, 720)
        self.assertFalse(ok)
        self.assertIn(('y', 360), bad)                       # 360 is not a multiple of 16
        self.assertFalse(vg.split_lines_on_macroblocks(PROFILE, '2h', 1920, 1080)[0])   # 540

    def test_quadrant_holds_a_quarter_of_native_pixels(self):
        # A 4-player quadrant of a native 320x240 PS1 game is 160x120 native pixels.
        q = vg.seat_rects(PROFILE, '4')[1]
        self.assertEqual(vg.native_pixels(q, 320, 240), (160, 120))


if __name__ == '__main__':
    unittest.main(verbosity=1)
