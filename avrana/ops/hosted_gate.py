"""The hosted staging password gate: one shared password in front of avrana.party and games.avrana.party.

    sudo python3 -m avrana.ops.hosted_gate set       # choose the password (asked twice, never echoed); signs everyone out
    sudo python3 -m avrana.ops.hosted_gate status    # whether a password is set (prints no secret)
    python3 -m avrana.ops.hosted_gate serve --socket /run/avrana-gate/gate.sock --config gate.json   # the unit runs this

The owner chose this over Cloudflare Access on 2026-10-23 (docs/runbooks/hosted-staging.md, "Password gate"). The
tunnel reaches nginx on the gate port (127.0.0.1:8081). There every request needs the gate cookie, whose value nginx
compares with the token in /etc/avrana-party/gate.map; without it the answer is a redirect to /__gate/ on the
Party host, which this service answers. The VM-local port (8080: smoke, deploy checks) is not gated, and nothing
outside the VM reaches it.

- `set` stores an scrypt hash of the password and a fresh random token in /etc/avrana-party/gate.json, the token
  alone in gate.map (both root, 0600), then reloads nginx and restarts the service. A new password is a new token,
  so every phone has to unlock again.
- `serve` shows the password form (GET /__gate/) and checks a submitted password (POST). A right one gets the cookie:
  Domain=<party host> (so the game origin, a subdomain, has it too), Secure, HttpOnly, SameSite=Lax, 30 days. A wrong
  one waits a second before the form comes back; nginx also limits the rate.
- The gate is not Party identity: Party Core never sees the cookie's meaning, and its device cookie is unchanged.
"""
import argparse
import getpass
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import secrets
import socketserver
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs

CONFIG = Path('/etc/avrana-party/gate.json')
MAP = Path('/etc/avrana-party/gate.map')
COOKIE = 'avrana_gate'
MAX_AGE = 30 * 24 * 3600
PARTY_HOST = 'avrana.party'
NEXT = '/party/'
MIN_LENGTH = 6
MAX_BODY = 4096
WRONG_DELAY = 1.0
SCRYPT = {'n': 2 ** 14, 'r': 8, 'p': 1}


def hash_password(password, salt=None, n=SCRYPT['n'], r=SCRYPT['r'], p=SCRYPT['p']):
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=n, r=r, p=p, dklen=32)
    return {'salt': salt.hex(), 'n': n, 'r': r, 'p': p, 'hash': digest.hex()}


def check_password(password, record):
    s = record['scrypt']
    got = hash_password(password, bytes.fromhex(s['salt']), s['n'], s['r'], s['p'])['hash']
    return hmac.compare_digest(got, s['hash'])


def new_record(password, domain=PARTY_HOST):
    if len(password) < MIN_LENGTH:
        raise ValueError(f'the password needs at least {MIN_LENGTH} characters')
    return {'schema': 'avrana.gate/v0', 'domain': domain, 'scrypt': hash_password(password),
            'token': secrets.token_hex(16)}      # 128 bits; 32 characters fit nginx's default map_hash_bucket_size


def map_text(token):
    return f'"{token}" 1;\n'


def write_private(path, text):
    """Write `text` to `path` as root-only 0600, atomically (a reader sees the old file or the new one)."""
    path = Path(path)
    tmp = path.with_name(f'.{path.name}.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def cookie_header(record):
    return (f'{COOKIE}={record["token"]}; Domain={record["domain"]}; Path=/; Max-Age={MAX_AGE}; '
            'Secure; HttpOnly; SameSite=Lax')


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Avrana Party staging</title>
<style>
:root {{ color-scheme: light dark; --bg: #f6f4ef; --fg: #1b1a18; --muted: #6b675f; --line: #d9d4c9; --accent: #3c5bd6; --bad: #b3261e; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #121214; --fg: #edeae4; --muted: #aeaba7; --line: #34332f; --accent: #8ea2ff; --bad: #ffb4ab; }} }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--bg); color: var(--fg);
  font: 16px/1.5 "Plus Jakarta Sans", system-ui, -apple-system, "Segoe UI", sans-serif; padding: 24px 16px; }}
main {{ width: 100%; max-width: 360px; display: grid; gap: 16px; }}
h1 {{ font-size: 1.4rem; margin: 0; }}
p {{ margin: 0; color: var(--muted); }}
form {{ display: grid; gap: 12px; }}
label {{ font-weight: 600; }}
input {{ font: inherit; padding: 12px 14px; border: 1px solid var(--line); border-radius: 10px; background: transparent; color: inherit; }}
input:focus {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
button {{ font: inherit; font-weight: 600; padding: 12px 14px; border: 0; border-radius: 10px; background: var(--accent); color: var(--bg); }}
.bad {{ color: var(--bad); }}
</style>
</head>
<body>
<main>
<h1>Avrana Party staging</h1>
<p>This is a testing site. Enter the password you were given.</p>
{message}
<form method="post" action="/__gate/">
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Unlock</button>
</form>
</main>
</body>
</html>
"""
CSP = ("default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")


def page(message=''):
    msg = f'<p class="bad" role="alert">{html.escape(message)}</p>' if message else ''
    return PAGE.format(message=msg).encode('utf-8')


class Handler(BaseHTTPRequestHandler):
    server_version = 'avrana-gate'
    sys_version = ''
    record = None           # set by serve()
    delay = WRONG_DELAY

    def log_message(self, fmt, *args):          # journald gets the outcome, never a password or a token
        pass

    def _send(self, status, body=b'', headers=()):
        self.send_response(status)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', CSP)
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        for k, v in headers:
            self.send_header(k, v)
        if body:
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if body and self.command != 'HEAD':
            self.wfile.write(body)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if self.path.split('?', 1)[0] != '/__gate/':
            return self._send(404)
        self._send(200, page())

    def do_POST(self):
        if self.path.split('?', 1)[0] != '/__gate/':
            return self._send(404)
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            return self._send(413)
        form = parse_qs(self.rfile.read(length).decode('utf-8', 'replace'), max_num_fields=4)
        password = (form.get('password') or [''])[0]
        if self.record and password and check_password(password, self.record):
            print('gate: unlocked', flush=True)
            return self._send(303, headers=(('Location', NEXT), ('Set-Cookie', cookie_header(self.record))))
        print('gate: wrong password', flush=True)
        time.sleep(self.delay)
        self._send(401, page('That password is not right.'))


def serve(socket_path, config_path):
    record = json.loads(Path(config_path).read_text(encoding='utf-8'))
    if record.get('schema') != 'avrana.gate/v0' or not record.get('token'):
        raise SystemExit(f'gate: {config_path} is not an avrana.gate/v0 record')

    class UnixHTTPServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):   # Linux only (the VM)
        daemon_threads = True

        def get_request(self):
            sock, _ = super().get_request()
            return sock, ('local', 0)       # BaseHTTPRequestHandler wants an address pair

    Handler.record = record
    sock = Path(socket_path)
    if sock.exists():
        sock.unlink()
    server = UnixHTTPServer(str(sock), Handler)
    os.chmod(sock, 0o666)       # nginx (www-data) connects; the socket only checks a password
    print(f'gate: serving {sock}', flush=True)
    server.serve_forever()


def set_password(config=CONFIG, gate_map=MAP, domain=PARTY_HOST, password=None, reload=True, run=subprocess.run):
    if password is None:
        password = getpass.getpass('New staging password: ')
        if getpass.getpass('Again: ') != password:
            raise SystemExit('gate: the two passwords differ; nothing changed')
    try:
        record = new_record(password, domain)
    except ValueError as e:
        raise SystemExit(f'gate: {e}; nothing changed')
    before = {p: Path(p).read_text(encoding='utf-8') if Path(p).exists() else None for p in (config, gate_map)}
    write_private(config, json.dumps(record, indent=2) + '\n')
    write_private(gate_map, map_text(record['token']))
    if reload:
        test = run(['nginx', '-t'], capture_output=True, text=True)
        if test.returncode != 0:            # put the files back, so nginx can still reload what it had
            for p, text in before.items():
                write_private(p, text) if text is not None else Path(p).unlink(missing_ok=True)
            raise SystemExit(f'gate: nginx refused the new map, nothing changed:\n{test.stderr}')
        run(['systemctl', 'reload', 'nginx'], check=True)
        run(['systemctl', 'restart', 'avrana-gate'], check=True)
    print('gate: password set; every phone has to unlock again')
    return record


def status(config=CONFIG, gate_map=MAP):
    if not Path(config).exists():
        print('gate: no password is set; the site is closed to everyone (set one: sudo python3 -m avrana.ops.hosted_gate set)')
        return 1
    record = json.loads(Path(config).read_text(encoding='utf-8'))
    in_map = Path(gate_map).exists() and Path(gate_map).read_text(encoding='utf-8') == map_text(record['token'])
    print(f'gate: a password is set for {record["domain"]}; nginx map {"agrees" if in_map else "DIFFERS: run set again"}')
    return 0 if in_map else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('serve')
    s.add_argument('--socket', default='/run/avrana-gate/gate.sock')
    s.add_argument('--config', default=str(CONFIG))
    p = sub.add_parser('set')
    p.add_argument('--domain', default=PARTY_HOST)
    sub.add_parser('status')
    a = ap.parse_args(argv)
    if a.cmd == 'serve':
        serve(a.socket, a.config)
        return 0
    if os.geteuid() != 0:
        print(f'gate: {a.cmd} needs root (sudo)', file=sys.stderr)
        return 1
    if a.cmd == 'set':
        set_password(domain=a.domain)
        return 0
    return status()


if __name__ == '__main__':
    sys.exit(main())
