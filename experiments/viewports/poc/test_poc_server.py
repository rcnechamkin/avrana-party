"""Unit tests for the Personal Viewports PoC server (stdlib only; binds 127.0.0.1 on a free port).
    python experiments/viewports/poc/test_poc_server.py
"""
import json
import os
import re
import sys
import threading
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import serve  # noqa: E402


class Server(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = serve.make_server('127.0.0.1', 0)
        cls.base = f'http://127.0.0.1:{cls.srv.server_address[1]}'
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        serve.SEATS.by_layout.clear()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.status, r.read(), r.headers

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_seats_are_distinct_and_stable_across_reconnects(self):
        seats = [self.post('/claim', {'client': f'client-{i:04d}', 'layout': '4'})[1]['seat']
                 for i in range(4)]
        self.assertEqual(seats, [1, 2, 3, 4])
        for i in range(4):                     # a reload/reconnect = the same id claims again
            self.assertEqual(self.post('/claim', {'client': f'client-{i:04d}', 'layout': '4'})[1]['seat'],
                             seats[i])

    def test_fifth_viewer_is_a_spectator_and_release_frees_a_seat(self):
        for i in range(4):
            self.post('/claim', {'client': f'client-{i:04d}', 'layout': '4'})
        self.assertIsNone(self.post('/claim', {'client': 'late-viewer', 'layout': '4'})[1]['seat'])
        self.assertEqual(self.post('/release', {'client': 'client-0001'})[1]['released'], 2)
        self.assertEqual(self.post('/claim', {'client': 'late-viewer', 'layout': '4'})[1]['seat'], 2)

    def test_layout_endpoint_serves_the_tested_geometry(self):
        _, body, _ = self.get('/layout?key=4&seat=2')
        lay = json.loads(body)
        # The 2-px inset makes the crop 316x236 = 79:59 (1.339), within 1% of 4:3.
        self.assertEqual(lay['aspect_text'], '79:59')
        self.assertAlmostEqual(lay['aspect'], 4 / 3, delta=4 / 3 * 0.01)
        self.assertAlmostEqual(lay['rect'][0], 322 / 640)      # inset 2 px from the 320 split
        self.assertAlmostEqual(lay['css']['left'], -100 * (322 / 640) / (316 / 640))
        _, body, _ = self.get('/layout?key=2h&seat=1')
        self.assertEqual(json.loads(body)['orientation'], 'landscape')
        _, body, _ = self.get('/layout?key=2v&seat=1')
        self.assertEqual(json.loads(body)['orientation'], 'portrait')

    def test_bad_requests_are_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.get('/layout?key=4&seat=9')
        self.assertEqual(e.exception.code, 404)
        self.assertEqual(self.post('/claim', {'client': 'short'})[0], 400)
        self.assertEqual(self.post('/claim', {'client': 'client-0000', 'layout': 'nope'})[0], 404)
        req = urllib.request.Request(self.base + '/claim', data=b'not json')
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 400)

    def test_page_is_served_and_self_contained(self):
        status, body, headers = self.get('/')
        self.assertEqual(status, 200)
        html = body.decode()
        # Offline-first: no external scripts, styles, fonts or images.
        self.assertFalse(re.search(r'(src|href)\s*=\s*["\']?(https?:)?//', html), 'external resource')
        self.assertIn('no-store', headers['Cache-Control'])


if __name__ == '__main__':
    unittest.main(verbosity=1)
