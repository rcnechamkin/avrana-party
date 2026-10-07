"""The stand-in native game (AVR-236, ADR 0016 sections 4 and 5).

  * StandinLogic: the game's own rules, with no sockets (runs everywhere);
  * Contract: its Game Contract is test-only and the product appliance never grants it;
  * Integration: real Party Core objects over Unix sockets against the real
    `python -m avrana.games.standin` process, handed an inherited socket on fd 3. It needs
    AF_UNIX, which Python on Windows lacks: skipped there, run on Linux CI.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from avrana import CONTRACTS_DIR, REPO_ROOT
from avrana.contracts import appliance, game, party_config, vocabulary
from avrana.games.standin import game as standin
from avrana.party import identity, protocol, registry, result, service, sessions

from test_party_registry import Appliance, unix_post
from test_party_service import HOST, ORIGIN, Phone

UNIX = hasattr(socket, 'AF_UNIX')
GAME = standin.GAME
SID = 'session-' + 'a' * 32
ANA, BEN, CAL = ('participant-' + c * 32 for c in 'abc')
ROSTER = [{'participant': ANA, 'name': 'Ana', 'role': 'player'},
          {'participant': BEN, 'name': 'Ben', 'role': 'player'},
          {'participant': CAL, 'name': 'Cal', 'role': 'spectator'}]
LAUNCH, END = standin.LAUNCH, standin.END
JSON = {'content-type': 'application/json'}


def body(**kw):
    return json.dumps(kw).encode()


class StandinLogic(unittest.TestCase):
    def setUp(self):
        self.key = protocol.new_key()
        self.reports = []
        self.answer = 200
        self.app = standin.Standin(protocol.GameSide(self.key, GAME),
                                   lambda m: (self.reports.append(m), self.answer)[1])

    def call(self, method, path, raw=b'', headers=None):
        status, ctype, out = self.app.handle(method, path, dict(headers or {}), raw)
        return status, (json.loads(out) if ctype == 'application/json' else out)

    def launch(self, sid=SID, headers=None, **kw):
        msg = protocol.launch_message(self.key, GAME, sid, ROSTER, **kw)
        return self.call('POST', LAUNCH, body(message=msg), headers)

    def ticket(self, pid=ANA, role='player', sid=SID, key=None):
        return protocol.mint_ticket(key or self.key, GAME, sid, pid, role)

    def redeem(self, ticket):
        return self.call('POST', standin.REDEEM, body(ticket=ticket))

    def finish(self, token):
        return self.call('POST', standin.FINISH, body(token=token))

    # --- control routes
    def test_control_routes_refuse_every_proxy_header_and_do_nothing(self):
        for header in ('X-Forwarded-For', 'X-Real-IP', 'Forwarded'):
            for path, msg in ((LAUNCH, protocol.launch_message(self.key, GAME, SID, ROSTER)),
                              (END, protocol.end_message(self.key, GAME, SID))):
                self.assertEqual(self.call('POST', path, body(message=msg),
                                           {header.lower(): '10.42.0.23'})[0], 404, (header, path))
        self.assertIsNone(self.app.side.sid)
        self.assertEqual(self.launch()[0], 200)                    # the same message, unproxied
        self.assertEqual(self.app.side.sid, SID)

    def test_a_control_route_is_post_only_and_other_control_paths_are_not_found(self):
        self.assertEqual(self.call('GET', LAUNCH)[0], 404)
        self.assertEqual(self.call('POST', standin.BASE + '/avrana/session/v0/other', b'{}')[0], 404)
        self.assertEqual(self.call('POST', standin.BASE + '/avrana/', b'{}')[0], 404)

    def test_forged_replayed_and_expired_launches_are_refused(self):
        forged = protocol.launch_message(protocol.new_key(), GAME, SID, ROSTER)
        self.assertEqual(self.call('POST', LAUNCH, body(message=forged))[0], 403)
        elsewhere = protocol.launch_message(self.key, 'bluff', SID, ROSTER)       # right key, other game
        self.assertEqual(self.call('POST', LAUNCH, body(message=elsewhere))[0], 403)
        self.assertEqual(self.launch(now=time.time() - 3600)[0], 403)              # expired
        self.assertIsNone(self.app.side.sid)
        msg = protocol.launch_message(self.key, GAME, SID, ROSTER)
        self.assertEqual(self.call('POST', LAUNCH, body(message=msg))[0], 200)
        self.assertEqual(self.call('POST', LAUNCH, body(message=msg))[0], 403)     # replay

    def test_bodies_are_strict_json(self):
        for raw in (b'', b'not json', b'[]', b'{"message": 1}', b'{"message": "x", "extra": "y"}',
                    b'{"message": "a", "message": "b"}', b'{"message": NaN}', b'\xff'):
            self.assertEqual(self.call('POST', LAUNCH, raw)[0], 400, raw)
        for raw in (b'{"ticket": 1}', b'{}', b'{"ticket": "x", "token": "y"}'):
            self.assertEqual(self.call('POST', standin.REDEEM, raw)[0], 400, raw)
        self.assertEqual(self.call('POST', standin.FINISH, b'{"ticket": "x"}')[0], 400)

    def test_end_clears_the_session_and_everything_redeemed(self):
        self.launch()
        _, r = self.redeem(self.ticket())
        end = protocol.end_message(self.key, GAME, SID)
        self.assertEqual(self.call('POST', END, body(message=end))[0], 200)
        self.assertEqual(self.call('POST', END, body(message=end))[0], 403)         # replay
        self.assertEqual(self.finish(r['token'])[0], 403)
        self.assertEqual(self.redeem(self.ticket())[0], 403)
        self.assertEqual(self.reports, [])

    def test_a_new_launch_forgets_the_old_sessions_participants(self):
        self.launch()
        _, r = self.redeem(self.ticket())
        self.launch(sid='session-' + 'b' * 32)
        self.assertEqual(self.finish(r['token'])[0], 403)

    # --- page side
    def test_the_page_is_static_and_other_paths_are_not_found(self):
        status, page = self.call('GET', standin.PAGE, headers={'x-forwarded-for': '10.42.0.2'})
        self.assertEqual(status, 200)
        self.assertNotIn(b'<script', page)
        for method, path in (('GET', '/'), ('GET', standin.BASE), ('GET', standin.BASE + '/nope'),
                             ('POST', standin.PAGE), ('GET', '/games/bluff/'), ('GET', standin.BASE + '/avrana/')):
            self.assertEqual(self.call(method, path, b'{}')[0], 404, (method, path))
        self.assertEqual(self.call('GET', standin.REDEEM)[0], 405)

    def test_redeem_is_single_use_and_shows_only_the_callers_own_view(self):
        self.launch()
        t = self.ticket()
        status, r = self.redeem(t)
        self.assertEqual((status, r['role'], r['view']), (200, 'player', {'you': 'Ana', 'players': 2}))
        for other in ('Ben', 'Cal', BEN, CAL):
            self.assertNotIn(other, json.dumps(r))
        self.assertEqual(self.redeem(t)[0], 403)                                     # single use
        self.assertEqual(self.redeem(self.ticket())[0], 200)                         # a fresh one works

    def test_redeem_refuses_forged_wrong_session_and_early_tickets(self):
        self.assertEqual(self.redeem(self.ticket())[0], 403)                         # nothing launched
        self.launch()
        self.assertEqual(self.redeem(self.ticket(key=protocol.new_key()))[0], 403)
        self.assertEqual(self.redeem(self.ticket(sid='session-' + 'c' * 32))[0], 403)
        self.assertEqual(self.redeem('aps0.x.y')[0], 403)

    def test_finish_needs_a_participant_who_redeemed_in_this_session(self):
        self.assertEqual(self.finish('avr-' + '0' * 40)[0], 403)                     # nothing running
        self.launch()
        self.assertEqual(self.finish('avr-' + '0' * 40)[0], 403)                     # never redeemed
        # the token is derivable only with the key: a participant who did not redeem has none
        self.assertEqual(self.finish(protocol.game_token(self.key, SID, ANA))[0], 403)
        self.assertEqual(self.reports, [])
        _, r = self.redeem(self.ticket(CAL, 'spectator'))
        self.assertEqual(self.finish(r['token'])[0], 403)                            # a spectator cannot
        self.assertEqual(self.reports, [])

    def test_finish_reports_a_valid_signed_ended_with_a_result_once(self):
        self.launch()
        _, r = self.redeem(self.ticket(BEN))
        self.assertEqual(self.finish(r['token']), (200, {'ok': True}))
        self.assertEqual(len(self.reports), 1)
        p = protocol.open_message(self.key, self.reports[0], 'ended', 'party', protocol.ReplayGuard())
        self.assertEqual((p['iss'], p['sid'], p['outcome']), (GAME, SID, 'completed'))
        checked = result.check(p['result'], GAME, [ANA, BEN])
        self.assertEqual({e['participant']: e['standing'] for e in checked['standings']},
                         {ANA: 'lost', BEN: 'won'})
        self.assertEqual((checked['game']['id'], checked['mode']), (GAME, 'competitive'))
        self.assertEqual(self.finish(r['token'])[0], 403)                            # the session is over
        self.assertEqual(len(self.reports), 1)

    def test_a_party_that_does_not_answer_is_a_502_not_a_success(self):
        self.launch()
        _, r = self.redeem(self.ticket())
        self.answer = None
        self.assertEqual(self.finish(r['token'])[0], 502)

    def test_nothing_secret_is_logged(self):
        with self.assertLogs(standin.log, 'INFO') as logs:
            self.launch()
            t = self.ticket()
            _, r = self.redeem(t)
            self.redeem(t)
            self.finish(r['token'])
        text = '\n'.join(logs.output)
        for secret in (t, r['token'], self.key.hex(), self.reports[0]):
            self.assertNotIn(secret, text)

    def test_the_module_opens_no_ip_socket_and_resolves_no_name(self):
        with open(standin.__file__, encoding='utf-8') as f:
            source = f.read()
        for word in ('AF_INET', 'urllib', 'getaddrinfo', 'gethostby', 'create_connection',
                     'HTTPServer', 'ThreadingHTTPServer'):
            self.assertNotIn(word, source, word)


class Contract(unittest.TestCase):
    def test_the_contract_validates_and_is_test_only(self):
        c = game.load(CONTRACTS_DIR / 'games' / 'standin.json', vocabulary.load())
        self.assertEqual((c['id'], c['kind'], c['runtime']['type'], c['runtime']['start']),
                         (GAME, 'native', 'external', 'service'))
        self.assertEqual((c['players']['min'], c['players']['max']), (2, 4))
        self.assertIs(c['extensions']['net.avrana.test']['test_only'], True)
        self.assertEqual(party_config.metadata(c)['pregame'], False)

    def test_the_product_appliance_does_not_grant_it(self):
        pi4 = appliance.load(CONTRACTS_DIR / 'appliances' / 'avrana-pi4.json', vocabulary.load())
        self.assertNotIn(GAME, appliance.grants(pi4))

    def test_only_the_ci_fixture_grants_it_and_says_how_to_run_it(self):
        ci = appliance.load(REPO_ROOT / 'tests/fixtures/appliances/ci-standin.json', vocabulary.load())
        grant = appliance.grants(ci)[GAME]
        self.assertEqual((grant['entry'], grant['tier']), ('/games/standin/', 'builtin'))
        self.assertEqual(grant['runtime']['command'], ['/usr/bin/python3', '-m', 'avrana.games.standin'])


def launcher():
    """What socket activation does for a unit: the listening socket is fd 3 and LISTEN_PID names
    the process. Then run the game exactly as `python3 -m avrana.games.standin` does."""
    return ('import os, runpy, sys\n'
            'os.dup2(int(sys.argv[1]), 3); os.set_inheritable(3, True)\n'
            'os.environ.update(LISTEN_PID=str(os.getpid()), LISTEN_FDS="1")\n'
            'runpy.run_module("avrana.games.standin", run_name="__main__", alter_sys=True)\n')


@unittest.skipUnless(UNIX, 'Unix sockets are not available on this platform (run on Linux CI)')
class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='avr', dir='/tmp')      # short: socket path limit
        self.addCleanup(self.tmp.cleanup)
        self.a = Appliance(self.tmp.name)
        self.game_socket = str(self.a.run / 'game.sock')
        self.internal_socket = str(self.a.run / 'internal.sock')
        self.a.register(GAME, socket=self.game_socket)
        games, self.endpoints = registry.build({}, str(self.a.reg), party_config.load_contracts())
        self.svc = service.PartyService(identity.DeviceStore(None), games,
                                        sessions.HttpGameLink(self.endpoints, share=True))
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
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(self.game_socket)
        listener.listen(16)
        env = dict(os.environ, AVRANA_PARTY_KEYS=str(self.a.keys),
                   AVRANA_PARTY_SOCKET=self.internal_socket, PYTHONPATH=str(REPO_ROOT))
        env.pop('LISTEN_PID', None)
        env.pop('LISTEN_FDS', None)
        proc = subprocess.Popen([sys.executable, '-c', launcher(), str(listener.fileno())],
                                pass_fds=[listener.fileno()], env=env, cwd=str(REPO_ROOT))
        listener.close()                                  # the game holds it now
        self.addCleanup(proc.wait, 10)
        self.addCleanup(proc.terminate)

    def launch(self):
        v = self.ana.state()[1]
        status, v, _ = self.ana.post('session/launch', {'game': GAME, 'if_version': v['version']})
        self.assertEqual((status, v['state']), (200, 'active'), v)
        return v['session']['id']

    def page(self, route, body=None, headers=None):
        return unix_post(self.game_socket, f'{standin.BASE}{route}', body or {}, headers)

    def test_launch_ticket_redeem_finish_and_the_party_accepts_the_result(self):
        self.start_game()
        sid = self.launch()
        _, t, _ = self.ana.post('session/ticket', {'game': GAME})
        self.assertEqual((t['game'], t['session']), (GAME, sid))
        status, r = self.page('/api/redeem', {'ticket': t['ticket']})
        self.assertEqual((status, r['role']), (200, 'player'))
        self.assertEqual(self.page('/api/redeem', {'ticket': t['ticket']})[0], 403)         # single use
        # page traffic arrives through nginx, with proxy headers: still served
        self.assertEqual(self.page('/api/finish', {'token': 'avr-' + '0' * 40},
                                   {'X-Forwarded-For': '10.42.0.23'})[0], 403)
        s = self.svc.core.party.session
        self.assertEqual(self.page('/api/finish', {'token': r['token']}), (200, {'ok': True}))
        self.assertEqual((s.state, s.outcome, s.result['schema'], s.result['game']['id']),
                         ('ended', 'completed', result.SCHEMA, GAME))
        self.assertEqual(sorted(e['standing'] for e in s.result['standings']), ['lost', 'won'])
        self.assertEqual(self.ben.state()[1]['location']['at'], 'results')

    def test_control_messages_through_a_proxy_are_refused_over_the_socket(self):
        self.start_game()
        msg = protocol.launch_message(self.key, GAME, SID, [])
        self.assertEqual(unix_post(self.game_socket, standin.LAUNCH, {'message': msg},
                                   {'X-Forwarded-For': '10.42.0.23'})[0], 404)
        self.assertEqual(unix_post(self.game_socket, standin.LAUNCH, {'message': msg})[0], 200)

    def test_the_hosts_end_reaches_the_game_which_then_forgets_the_session(self):
        self.start_game()
        sid = self.launch()
        _, t, _ = self.ana.post('session/ticket', {'game': GAME})
        _, r = self.page('/api/redeem', {'ticket': t['ticket']})
        v = self.ana.state()[1]
        status, v, _ = self.ana.post('session/end', {'if_version': v['version']})
        s = self.svc.core.party.session
        self.assertEqual((status, s.id, s.outcome, s.game_confirmed_end), (200, sid, 'ended_by_host', True))
        self.assertEqual(self.page('/api/finish', {'token': r['token']})[0], 403)        # nothing to finish
        late = protocol.mint_ticket(self.key, GAME, sid, next(iter(s.participants.values())).id, 'player')
        self.assertEqual(self.page('/api/redeem', {'ticket': late})[0], 403)

    def test_oversize_and_non_json_bodies_are_refused_by_the_server(self):
        self.start_game()
        conn = sessions.UnixHTTPConnection(self.game_socket, 10)
        conn.request('POST', standin.REDEEM, body=b'ticket=x', headers={'Host': 'localhost'})
        self.assertEqual(conn.getresponse().status, 415)
        conn.close()
        conn = sessions.UnixHTTPConnection(self.game_socket, 10)
        conn.request('GET', standin.PAGE, headers={'Host': 'localhost', 'X-Forwarded-For': '10.42.0.2'})
        r = conn.getresponse()
        self.assertEqual((r.status, r.getheader('X-Content-Type-Options')), (200, 'nosniff'))
        conn.close()


if __name__ == '__main__':
    unittest.main()
