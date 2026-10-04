"""Native games over Unix sockets and the game registry (AVR-258, ADR 0016 §3, §4, §8).

Three parts:
  * Registry: the registry directory and party-core.json's `games` become Party Core's game set
    all at once or not at all; a reload changes the games and nothing about the party. These run
    everywhere.
  * UnixFlow: a stand-in game process that serves an inherited socket (tests/fixtures/
    standin_game.py) is launched, admits a ticket, is ended, and reports `ended` with a result,
    all over Unix sockets.
  * InternalSocket: what the party's internal socket accepts and refuses.
The last two need AF_UNIX, which Python on Windows does not have: they are skipped there and
run on Linux CI.
"""
import copy
import http.client
import json
import logging
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from avrana import REPO_ROOT
from avrana.contracts import party_config
from avrana.party import identity, protocol, registry, result, service, sessions

from test_party_service import HOST, ORIGIN, Phone

UNIX = hasattr(socket, 'AF_UNIX')
GAME = 'standin'
STANDIN = REPO_ROOT / 'tests/fixtures/standin_game.py'


def contracts():
    """The real contracts plus one for the stand-in (BLUFF's shape: 2 to 6 players)."""
    real = party_config.load_contracts()
    made = copy.deepcopy(real['bluff'])
    made['id'] = GAME
    made.get('extensions', {}).pop(party_config.EXTENSION, None)        # no setup scene
    return dict(real, **{GAME: made})


class Appliance:
    """A temporary /etc and /run: a key directory, a registry directory and a party-core.json."""

    def __init__(self, tmp, config_games=None):
        self.root = Path(tmp)
        self.keys, self.reg, self.run = self.root / 'keys', self.root / 'games.d', self.root / 'run'
        for d in (self.keys, self.reg, self.run):
            d.mkdir()
        self.config = self.root / 'party-core.json'
        self.write_config(config_games or {})

    def write_config(self, games):
        self.config.write_text(json.dumps({'games': games, 'registry': str(self.reg)}), encoding='utf-8')

    def key(self, game):
        path = self.keys / f'{game}.key'
        if not path.exists():
            protocol.write_key(str(path), protocol.new_key())
        return str(path)

    def register(self, game=GAME, name=None, **more):
        entry = {'id': game, 'socket': f'/run/avrana-games/{game}.sock', 'key_file': self.key(game)}
        entry.update(more)
        (self.reg / f'{name or game}.json').write_text(json.dumps(entry), encoding='utf-8')
        return entry


class Registry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a = Appliance(self.tmp.name)
        self.contracts = contracts()

    def build(self, config_games=None):
        return registry.build(config_games or {}, str(self.a.reg), self.contracts)

    def problems(self, config_games=None):
        with self.assertRaises(registry.RegistryError) as e:
            self.build(config_games)
        return e.exception.problems

    def test_a_registry_entry_becomes_a_game_reached_over_its_socket(self):
        self.a.register(timeout=7)
        games, endpoints = self.build()
        self.assertEqual(games[GAME], {'id': GAME, 'min_players': 2, 'max_players': 6,
                                       'late_join': games[GAME]['late_join'], 'pregame': False})
        ep = endpoints[GAME]
        self.assertEqual((ep.socket_path, ep.url, ep.timeout),
                         (f'/run/avrana-games/{GAME}.sock', f'http://localhost/games/{GAME}', 7))
        self.assertEqual(len(ep.key), 32)

    def test_tcp_games_in_the_config_are_exactly_as_before(self):
        self.a.register()
        games, endpoints = self.build({'bluff': {'url': 'http://127.0.0.1:8096/games/bluff',
                                                 'key_file': self.a.key('bluff')}})
        self.assertEqual(sorted(games), ['bluff', GAME])
        self.assertEqual((endpoints['bluff'].url, endpoints['bluff'].socket_path),
                         ('http://127.0.0.1:8096/games/bluff', None))

    def test_no_registry_directory_is_an_empty_registry(self):
        self.assertEqual(registry.read_directory(str(self.a.root / 'missing')), {})
        self.assertEqual(registry.build({}, None, self.contracts), ({}, {}))

    def test_the_registry_holds_no_secret(self):
        entry = self.a.register()
        text = (self.a.reg / f'{GAME}.json').read_text(encoding='utf-8')
        key = Path(entry['key_file']).read_text(encoding='ascii').strip()
        self.assertNotIn(key, text)
        self.assertEqual(set(json.loads(text)), {'id', 'socket', 'key_file'})

    def test_a_game_registered_twice_refuses_the_whole_registry(self):
        self.a.register()
        got = self.problems({GAME: {'url': 'http://127.0.0.1:1', 'key_file': self.a.key(GAME)}})
        self.assertIn(f'{GAME}: registered twice (party-core.json and the registry directory)', got)
        self.a.register('bluff')
        self.a.register('bluff', name='also-bluff')                      # the same id in two files
        got = self.problems()
        self.assertTrue(any(p.startswith('bluff: registered twice') for p in got), got)
        self.assertTrue(any('must be named bluff.json' in p for p in got), got)

    def test_an_entry_with_no_game_contract_refuses_the_whole_registry(self):
        self.a.register()
        self.a.register('nocontract')
        got = self.problems()
        self.assertEqual([p for p in got if p.startswith('nocontract')],
                         ['nocontract: no Game Contract (contracts/games/nocontract.json)'])

    def test_malformed_entries_are_named(self):
        cases = {'unreadable': 'not json', 'list': '[]', 'noid': '{"socket": "/x", "key_file": "/k"}',
                 'relative': json.dumps({'id': 'relative', 'socket': 'run/x.sock', 'key_file': '/k'}),
                 'nokey': json.dumps({'id': 'nokey', 'socket': '/run/x.sock'}),
                 'extra': json.dumps({'id': 'extra', 'socket': '/run/x.sock', 'key_file': '/k', 'key': 'abc'}),
                 'slow': json.dumps({'id': 'slow', 'socket': '/run/x.sock', 'key_file': '/k', 'timeout': 900})}
        for name, text in cases.items():
            (self.a.reg / f'{name}.json').write_text(text, encoding='utf-8')
        got = ' | '.join(self.problems())
        for want in ('unreadable: unreadable.json is unreadable', 'list: list.json must hold one JSON object',
                     'noid: noid.json has no valid "id"', 'relative: "socket" must be an absolute path',
                     'nokey: "key_file" is required', "extra: unknown key 'key'", 'slow: "timeout"'):
            self.assertIn(want, got)

    def test_an_unusable_key_is_reported_without_its_content(self):
        entry = self.a.register()
        Path(entry['key_file']).write_text('not-a-key-but-secret-looking-0123456789', encoding='ascii')
        got = self.problems()
        self.assertEqual(got, [f'{GAME}: its key file cannot be used (ValueError)'])
        self.assertNotIn('secret-looking', ' '.join(got))


class Reload(unittest.TestCase):
    """A running Party Core picks up a new game and the party does not notice."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.a = Appliance(self.tmp.name, {'bluff': {'url': 'http://127.0.0.1:1', 'key_file': None}})
        self.a.write_config({'bluff': {'url': 'http://127.0.0.1:1', 'key_file': self.a.key('bluff')}})
        self.contracts = contracts()
        self.store = identity.DeviceStore(str(Path(self.tmp.name) / 'devices.json'))
        games, self.endpoints = registry.build(json.loads(self.a.config.read_text())['games'],
                                               str(self.a.reg), self.contracts)
        self.link = sessions.HttpGameLink(self.endpoints, share=True)
        self.svc = service.PartyService(self.store, games, self.link)
        extra, internal = sessions.routes(self.svc, self.endpoints)
        self.server = service.make_server(self.svc, service.Config({HOST}, {ORIGIN}), port=0,
                                          extra_routes=extra, internal_routes=internal)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        port = self.server.server_address[1]
        self.ana, self.ben = Phone(port), Phone(port)
        self.ana.post('join', {'name': 'Ana'})
        self.ben.post('join', {'name': 'Ben'})

    def reload(self):
        return registry.reload(self.svc, self.endpoints, str(self.a.config), self.contracts)

    def party(self):
        v = self.ana.state()[1]
        return (v['party'], v['host'], sorted((m['id'], m['name'], m['host']) for m in v['members']),
                v['me']['id'], dict(self.store.by_hash))

    def test_one_reload_makes_a_new_game_launchable_and_the_party_is_unchanged(self):
        before, version = self.party(), self.ana.state()[1]['version']
        self.assertEqual(self.ana.state()[1]['games'], ['bluff'])
        self.a.register()                                            # an entry and its key appear
        self.assertEqual(self.ana.state()[1]['games'], ['bluff'])    # nothing until the reload
        self.assertTrue(self.reload())
        view = self.ana.state()[1]
        self.assertEqual(view['games'], ['bluff', GAME])
        self.assertGreater(view['version'], version)                 # phones are told
        self.assertEqual(self.party(), before)                       # same party, host, members, devices
        self.assertEqual(self.ben.state()[1]['me']['name'], 'Ben')   # Ben's cookie is still Ben
        # the link and the session routes both know the new game: one shared registry
        self.assertIs(self.link.endpoints, self.endpoints)
        self.assertEqual(self.endpoints[GAME].socket_path, f'/run/avrana-games/{GAME}.sock')
        # and the host can start it (it fails readably here only because nothing listens there)
        status, v, _ = self.ana.post('session/launch', {'game': GAME, 'if_version': view['version']})
        self.assertEqual(status, 200)
        self.assertEqual((v['session']['game'], v['session']['outcome']), (GAME, 'launch_failed'))

    def test_a_refused_reload_keeps_the_previous_registry_and_logs_the_slug(self):
        self.a.register()
        self.assertTrue(self.reload())
        before = self.party()
        for name, setup, want in (
                ('duplicate', lambda: self.a.write_config({
                    'bluff': {'url': 'http://127.0.0.1:1', 'key_file': self.a.key('bluff')},
                    GAME: {'url': 'http://127.0.0.1:2', 'key_file': self.a.key(GAME)}}),
                 f'{GAME}: registered twice'),
                ('no contract', lambda: self.a.register('ghost'), 'ghost: no Game Contract'),
                ('unreadable config', lambda: self.a.config.write_text('{', encoding='utf-8'),
                 'the config is unreadable')):
            with self.subTest(name):
                setup()
                with self.assertLogs('avrana.party.registry', logging.ERROR) as logs:
                    self.assertFalse(self.reload())
                self.assertIn(want, ' '.join(logs.output))
                self.assertEqual(sorted(self.endpoints), ['bluff', GAME])
                self.assertEqual(self.ana.state()[1]['games'], ['bluff', GAME])
                self.assertEqual(self.party(), before)
                # put the appliance right again for the next case
                self.a.write_config({'bluff': {'url': 'http://127.0.0.1:1', 'key_file': self.a.key('bluff')}})
                for stray in self.a.reg.glob('ghost.json'):
                    stray.unlink()

    def test_a_game_is_removed_by_a_reload_but_not_while_its_session_runs(self):
        self.a.register()
        self.assertTrue(self.reload())
        self.svc.link = type('Accepting', (), {'launch': lambda s, sess, roster: (True, None),
                                               'end': lambda s, sess: True})()
        v = self.ana.state()[1]
        status, v, _ = self.ana.post('session/launch', {'game': GAME, 'if_version': v['version']})
        self.assertEqual((status, v['state']), (200, 'active'))
        (self.a.reg / f'{GAME}.json').unlink()
        with self.assertLogs('avrana.party.registry', logging.ERROR) as logs:
            self.assertFalse(self.reload())
        self.assertIn(f'{GAME}: has a session running', ' '.join(logs.output))
        self.assertEqual(self.ana.state()[1]['state'], 'active')
        self.ana.post('session/end', {'if_version': self.ana.state()[1]['version']})
        self.assertTrue(self.reload())                               # now it goes
        self.assertEqual(self.ana.state()[1]['games'], ['bluff'])

    def test_sd_listen_fds(self):
        self.assertEqual(service.listen_fds({'LISTEN_PID': '42', 'LISTEN_FDS': '1'}, pid=42), [3])
        self.assertEqual(service.listen_fds({'LISTEN_PID': '42', 'LISTEN_FDS': '2'}, pid=42), [3, 4])
        self.assertEqual(service.listen_fds({'LISTEN_PID': '41', 'LISTEN_FDS': '1'}, pid=42), [])   # another process's
        self.assertEqual(service.listen_fds({}, pid=42), [])
        self.assertEqual(service.listen_fds({'LISTEN_PID': 'x', 'LISTEN_FDS': '1'}, pid=42), [])


def unix_post(path, route, body, headers=None):
    conn = sessions.UnixHTTPConnection(path, 10)
    try:
        h = {'Content-Type': 'application/json', 'Host': 'localhost'}
        h.update(headers or {})
        conn.request('POST', route, body=json.dumps(body).encode(), headers=h)
        r = conn.getresponse()
        return r.status, json.loads(r.read() or b'{}')
    finally:
        conn.close()


@unittest.skipUnless(UNIX, 'Unix sockets are not available on this platform (run on Linux CI)')
class UnixCase(unittest.TestCase):
    """Party Core with a registry entry for the stand-in game, its internal socket, and the
    stand-in process serving a socket it inherited."""

    def setUp(self):
        # A short directory: a Unix socket path is limited to about 100 bytes.
        self.tmp = tempfile.TemporaryDirectory(prefix='avr', dir='/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.a = Appliance(self.tmp.name)
        self.game_socket = str(self.a.run / 'game.sock')
        self.internal_socket = str(self.a.run / 'internal.sock')
        self.a.register(socket=self.game_socket)
        games, self.endpoints = registry.build({}, str(self.a.reg), contracts())
        self.store = identity.DeviceStore(None)
        self.svc = service.PartyService(self.store, games, sessions.HttpGameLink(self.endpoints, share=True))
        extra, internal = sessions.routes(self.svc, self.endpoints)
        self.server = service.make_server(self.svc, service.Config({HOST}, {ORIGIN}), port=0,
                                          extra_routes=extra, internal_routes=internal)
        self.internal = service.make_internal_server(self.svc, internal, self.internal_socket)
        for s in (self.server, self.internal):
            threading.Thread(target=s.serve_forever, daemon=True).start()
            self.addCleanup(s.server_close)
            self.addCleanup(s.shutdown)
        port = self.server.server_address[1]
        self.ana, self.ben = Phone(port), Phone(port)
        self.ana.post('join', {'name': 'Ana'})
        self.ben.post('join', {'name': 'Ben'})
        self.key = self.endpoints[GAME].key

    def start_game(self):
        """What the socket unit and systemd do: bind the socket, then hand it to the game."""
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(self.game_socket)
        listener.listen(16)
        env = dict(os.environ, AVRANA_PARTY_KEYS=str(self.a.keys), STANDIN_GAME=GAME,
                   STANDIN_PARTY_SOCKET=self.internal_socket)
        env.pop('LISTEN_PID', None)
        env.pop('LISTEN_FDS', None)
        proc = subprocess.Popen([sys.executable, str(STANDIN), '--activate', str(listener.fileno())],
                                pass_fds=[listener.fileno()], env=env)
        listener.close()                                  # the game holds it now
        self.addCleanup(proc.wait, 10)
        self.addCleanup(proc.terminate)
        return proc

    def launch(self):
        v = self.ana.state()[1]
        status, v, _ = self.ana.post('session/launch', {'game': GAME, 'if_version': v['version']})
        self.assertEqual((status, v['state']), (200, 'active'), v)
        return v['session']['id']

    def game(self, route, body, headers=None):
        return unix_post(self.game_socket, f'/games/{GAME}{route}', body, headers)


class UnixFlow(UnixCase):
    def test_launch_ticket_and_a_reported_result_all_over_unix_sockets(self):
        self.start_game()
        sid = self.launch()
        # the ticket still comes from the party's API; the game redeems it once
        _, t, _ = self.ana.post('session/ticket', {'game': GAME})
        self.assertEqual((t['game'], t['session']), (GAME, sid))
        status, hello = self.game('/hello', {'ticket': t['ticket']})
        self.assertEqual((status, hello['role']), (200, 'player'))
        self.assertEqual(self.game('/hello', {'ticket': t['ticket']})[0], 403)      # single use
        # the game finishes and reports, with a result, to the party's internal socket
        s = self.svc.core.party.session
        winner = next(p.id for p in s.participants.values())
        status, done = self.game('/test/finish', {'outcome': 'completed', 'winner': winner})
        self.assertEqual((status, done['party_status'], done['party']),
                         (200, 200, {'ok': True, 'result': 'accepted'}))
        self.assertEqual((s.state, s.outcome, s.result['schema'], s.result['game']['id']),
                         ('ended', 'completed', result.SCHEMA, GAME))
        self.assertEqual([e['standing'] for e in s.result['standings']], ['won', 'lost'])
        self.assertEqual(self.ben.state()[1]['location']['at'], 'results')

    def test_the_hosts_end_reaches_the_game_over_its_socket(self):
        self.start_game()
        sid = self.launch()
        v = self.ana.state()[1]
        status, v, _ = self.ana.post('session/end', {'if_version': v['version']})
        s = self.svc.core.party.session
        self.assertEqual((status, s.id, s.outcome, s.game_confirmed_end), (200, sid, 'ended_by_host', True))
        # the game forgot the session: a ticket for it no longer admits
        late = protocol.mint_ticket(self.key, GAME, sid, next(iter(s.participants.values())).id, 'player')
        self.assertEqual(self.game('/hello', {'ticket': late})[0], 403)

    def test_an_abandoned_game_reports_without_a_result(self):
        self.start_game()
        self.launch()
        status, done = self.game('/test/finish', {'outcome': 'abandoned'})
        self.assertEqual((done['party_status'], done['party']), (200, {'ok': True}))
        s = self.svc.core.party.session
        self.assertEqual((s.outcome, s.result), ('abandoned', None))

    def test_the_game_refuses_control_messages_that_came_through_a_proxy(self):
        self.start_game()
        message = protocol.launch_message(self.key, GAME, 'session-' + 'a' * 32, [])
        self.assertEqual(self.game(sessions.LAUNCH_PATH, {'message': message},
                                   {'X-Forwarded-For': '10.42.0.23'})[0], 404)
        self.assertEqual(self.game(sessions.LAUNCH_PATH, {'message': message})[0], 200)

    def test_a_game_that_is_not_running_fails_the_launch_readably(self):
        v = self.ana.state()[1]                            # nothing listens on the game's socket
        status, v, _ = self.ana.post('session/launch', {'game': GAME, 'if_version': v['version']})
        self.assertEqual((status, v['session']['outcome']), (200, 'launch_failed'))
        self.assertIn('did not answer', v['session']['detail'])


class InternalSocket(UnixCase):
    def report(self, message, headers=None, route=sessions.ENDED_ROUTE):
        return unix_post(self.internal_socket, route, {'message': message}, headers)

    def test_the_socket_is_a_socket_closed_to_others(self):
        st = os.stat(self.internal_socket)
        self.assertTrue(stat.S_ISSOCK(st.st_mode))
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o660)

    def test_a_signed_report_from_the_sessions_game_is_accepted(self):
        sid = self.launch_with_accepting_link()
        self.assertEqual(self.report(protocol.ended_message(self.key, GAME, sid, 'completed')),
                         (200, {'ok': True}))
        self.assertEqual(self.svc.core.party.session.outcome, 'completed')

    def launch_with_accepting_link(self):
        self.svc.link = type('Accepting', (), {'launch': lambda s, sess, roster: (True, None),
                                               'end': lambda s, sess: True})()
        return self.launch()

    def test_a_report_whose_issuer_is_not_the_game_whose_key_verified_it_is_refused(self):
        sid = self.launch_with_accepting_link()
        forged = protocol.ended_message(self.key, 'bluff', sid, 'completed')        # the right key, another name
        status, body = self.report(forged)
        self.assertEqual((status, body['reason']), (403, 'issuer'))
        self.assertEqual(self.svc.core.party.session.state, 'active')

    def test_a_bad_signature_a_stale_session_and_a_replay_are_refused(self):
        sid = self.launch_with_accepting_link()
        self.assertEqual(self.report(protocol.ended_message(protocol.new_key(), GAME, sid, 'completed'))[0], 403)
        self.assertEqual(self.report(protocol.ended_message(self.key, GAME, 'session-' + 'f' * 32, 'completed'))[0], 409)
        good = protocol.ended_message(self.key, GAME, sid, 'completed')
        self.assertEqual(self.report(good)[0], 200)
        self.assertEqual(self.report(good)[0], 403)                                  # replay

    def test_nothing_but_the_internal_route_is_served_there(self):
        sid = self.launch_with_accepting_link()
        good = protocol.ended_message(self.key, GAME, sid, 'completed')
        self.assertEqual(self.report(good, route='/party/api/join')[0], 404)        # no API on this socket
        self.assertEqual(self.report(good, route='/internal/other')[0], 404)
        self.assertEqual(self.report(good, headers={'X-Forwarded-For': '10.42.0.9'})[0], 404)   # never proxied
        conn = sessions.UnixHTTPConnection(self.internal_socket, 5)
        conn.request('GET', '/party/api/state', headers={'Host': 'localhost'})
        self.assertEqual(conn.getresponse().status, 404)
        conn.close()
        self.assertEqual(self.svc.core.party.session.state, 'active')

    def test_the_loopback_route_still_works_for_tcp_games(self):
        sid = self.launch_with_accepting_link()
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=10)
        conn.request('POST', sessions.ENDED_ROUTE,
                     json.dumps({'message': protocol.ended_message(self.key, GAME, sid, 'abandoned')}),
                     {'Content-Type': 'application/json'})
        self.assertEqual(conn.getresponse().status, 200)
        conn.close()

    def test_a_stale_socket_file_is_replaced_and_a_real_file_is_not(self):
        path = str(self.a.run / 'again.sock')
        first = service.make_internal_server(self.svc, {}, path)
        first.server_close()                               # leaves the socket file behind
        second = service.make_internal_server(self.svc, {}, path)
        second.server_close()
        plain = self.a.run / 'not-a-socket'
        plain.write_text('x')
        with self.assertRaises(OSError):
            service.make_internal_server(self.svc, {}, str(plain))
        self.assertEqual(plain.read_text(), 'x')

    def test_an_inherited_socket_is_served_as_it_is(self):
        """Production: the socket unit made it (ownership and mode are systemd's)."""
        path = str(self.a.run / 'inherited.sock')
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(path)
        os.chmod(path, 0o600)
        listener.listen(8)
        _, internal = sessions.routes(self.svc, self.endpoints)
        server = service.make_internal_server(self.svc, internal, fd=listener.detach())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)             # untouched
        sid = self.launch_with_accepting_link()
        self.assertEqual(unix_post(path, sessions.ENDED_ROUTE,
                                   {'message': protocol.ended_message(self.key, GAME, sid, 'completed')})[0], 200)


if __name__ == '__main__':
    unittest.main()
