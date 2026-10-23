"""The hosted staging password gate (avrana/ops/hosted_gate.py): the password check, the cookie, the files `set`
writes, and the form over a real HTTP handler."""
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from avrana.ops import hosted_gate as gate  # noqa: E402

FAST = {'n': 2 ** 4, 'r': 1, 'p': 1}       # scrypt parameters that keep the tests quick


def record(password='correct horse'):
    r = gate.new_record(password)
    r['scrypt'] = gate.hash_password(password, **FAST)
    return r


class Password(unittest.TestCase):
    def test_the_right_password_passes_and_any_other_fails(self):
        r = record()
        self.assertTrue(gate.check_password('correct horse', r))
        for wrong in ('correct hors', 'Correct horse', 'correct horse ', ''):
            self.assertFalse(gate.check_password(wrong, r), wrong)

    def test_a_record_holds_a_salted_hash_and_a_random_token_never_the_password(self):
        a, b = gate.new_record('same password'), gate.new_record('same password')
        self.assertNotEqual(a['scrypt']['salt'], b['scrypt']['salt'])
        self.assertNotEqual(a['scrypt']['hash'], b['scrypt']['hash'])
        self.assertNotEqual(a['token'], b['token'])
        self.assertRegex(a['token'], r'^[0-9a-f]{64}$')
        self.assertNotIn('same password', json.dumps(a))

    def test_a_short_password_is_refused(self):
        with self.assertRaises(ValueError):
            gate.new_record('x' * (gate.MIN_LENGTH - 1))

    def test_the_cookie_covers_the_game_origin_and_is_secure_httponly_lax(self):
        r = record()
        header = gate.cookie_header(r)
        self.assertTrue(header.startswith(f'avrana_gate={r["token"]}; '))
        for part in ('Domain=avrana.party', 'Path=/', f'Max-Age={30 * 24 * 3600}', 'Secure', 'HttpOnly', 'SameSite=Lax'):
            self.assertIn(part, header.split('; '))

    def test_the_nginx_map_line_is_the_token_alone(self):
        self.assertEqual(gate.map_text('ab' * 32), f'"{"ab" * 32}" 1;\n')


class SetAndStatus(unittest.TestCase):
    def test_set_writes_both_files_root_only_and_reloads_in_order(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            config, gmap = Path(tmp) / 'gate.json', Path(tmp) / 'gate.map'
            r = gate.set_password(config, gmap, password='a staging password', run=lambda cmd, **kw: calls.append(cmd))
            saved = json.loads(config.read_text(encoding='utf-8'))
            self.assertEqual(saved, r)
            self.assertTrue(gate.check_password('a staging password', saved))
            self.assertEqual(gmap.read_text(encoding='utf-8'), gate.map_text(r['token']))
            if os.name == 'posix':
                for f in (config, gmap):
                    self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600, f)
            self.assertEqual(gate.status(config, gmap), 0)
            gmap.write_text('"stale" 1;\n', encoding='utf-8')
            self.assertEqual(gate.status(config, gmap), 1)
            self.assertEqual(gate.status(Path(tmp) / 'absent.json', gmap), 1)
        self.assertEqual(calls, [['nginx', '-t'], ['systemctl', 'reload', 'nginx'], ['systemctl', 'restart', 'avrana-gate']])

    def test_a_refused_password_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config, gmap = Path(tmp) / 'gate.json', Path(tmp) / 'gate.map'
            with self.assertRaises(SystemExit):
                gate.set_password(config, gmap, password='short', reload=False)
            self.assertFalse(config.exists() or gmap.exists())


class FakeRequest:
    """Enough of a socket for BaseHTTPRequestHandler: one request in, the response collected."""
    def __init__(self, raw):
        self.rfile, self.wfile = io.BytesIO(raw), io.BytesIO()

    def makefile(self, mode, *a, **kw):
        return self.rfile if 'r' in mode else self.wfile

    def sendall(self, data):
        self.wfile.write(data)


def ask(raw, r):
    gate.Handler.record, gate.Handler.delay = r, 0
    req = FakeRequest(raw)
    gate.Handler(req, ('local', 0), None)
    head, _, body = req.wfile.getvalue().partition(b'\r\n\r\n')
    lines = head.decode().split('\r\n')
    headers = {}
    for line in lines[1:]:
        k, _, v = line.partition(': ')
        headers.setdefault(k.lower(), []).append(v)
    return int(lines[0].split()[1]), headers, body


def post(password):
    body = f'password={password}'.encode()
    return (b'POST /__gate/ HTTP/1.1\r\nHost: avrana.party\r\nContent-Type: application/x-www-form-urlencoded\r\n'
            b'Content-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)


class Form(unittest.TestCase):
    def test_the_form_is_served_with_a_strict_policy_and_no_store(self):
        status, headers, body = ask(b'GET /__gate/ HTTP/1.1\r\nHost: avrana.party\r\n\r\n', record())
        self.assertEqual(status, 200)
        self.assertIn(b'type="password"', body)
        self.assertIn(b'action="/__gate/"', body)
        self.assertEqual(headers['cache-control'], ['no-store'])
        self.assertIn("default-src 'none'", headers['content-security-policy'][0])
        self.assertIn("frame-ancestors 'none'", headers['content-security-policy'][0])

    def test_the_right_password_sets_the_cookie_and_goes_to_party_home(self):
        r = record()
        status, headers, _ = ask(post('correct+horse'), r)
        self.assertEqual(status, 303)
        self.assertEqual(headers['location'], ['/party/'])
        self.assertEqual(headers['set-cookie'], [gate.cookie_header(r)])

    def test_a_wrong_password_gets_the_form_again_and_no_cookie(self):
        status, headers, body = ask(post('nope'), record())
        self.assertEqual(status, 401)
        self.assertNotIn('set-cookie', headers)
        self.assertIn(b'not right', body)

    def test_other_paths_and_oversized_bodies_are_refused(self):
        r = record()
        self.assertEqual(ask(b'GET /party/ HTTP/1.1\r\nHost: avrana.party\r\n\r\n', r)[0], 404)
        big = b'POST /__gate/ HTTP/1.1\r\nHost: avrana.party\r\nContent-Length: 999999\r\n\r\n'
        self.assertEqual(ask(big, r)[0], 413)


if __name__ == '__main__':
    unittest.main()
