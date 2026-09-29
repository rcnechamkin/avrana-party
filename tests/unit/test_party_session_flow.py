"""The session protocol end to end over real HTTP on 127.0.0.1: Party Core + a reference game
server built on protocol.GameSide (the shape the games repository will implement next)."""
import http.client
import http.server
import json
import threading
import unittest

from avrana.party import protocol, sessions
from avrana.party.protocol import Invalid

from test_party_service import HOST, ORIGIN, BLUFF, Phone, ServiceCase

KEY = protocol.new_key()


class ReferenceGame:
    """A stand-in game server: the two protocol routes, a hello, and an ended report."""

    def __init__(self, party_port):
        self.side = protocol.GameSide(KEY, 'bluff')
        self.party_port = party_port
        self.launches, self.ends = [], []
        game = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                try:
                    if self.path == sessions.LAUNCH_PATH:
                        game.launches.append(game.side.on_launch(body['message']))
                    elif self.path == sessions.END_PATH:
                        game.ends.append(game.side.on_end(body['message']))
                    else:
                        raise Invalid('route')
                    out, status = {'ok': True}, 200
                except Invalid as e:
                    out, status = {'ok': False, 'message': str(e)}, 403
                data = json.dumps(out).encode()
                self.send_response(status)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def hello(self, ticket):
        """What core/net.py will do with {"t": "hello", "ticket": …}."""
        return self.side.admit(ticket)

    def report(self, message, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.party_port, timeout=10)
        h = {'Content-Type': 'application/json'}
        h.update(headers or {})
        conn.request('POST', sessions.ENDED_ROUTE, json.dumps({'message': message}), h)
        r = conn.getresponse()
        out = r.status, json.loads(r.read() or b'{}')
        conn.close()
        return out

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class LinkTimeouts(unittest.TestCase):
    """AVR-134: a game whose launch starts a heavy runtime gets its own link timeout."""

    def test_each_endpoint_uses_its_own_timeout(self):
        from unittest import mock
        seen = []

        class Reply:
            status = 200

            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout):
            seen.append((req.full_url, timeout))
            return Reply()
        eps = {'bluff': sessions.GameEndpoint('bluff', 'http://127.0.0.1:1', KEY),
               'arcade-gauntlet2': sessions.GameEndpoint('arcade-gauntlet2', 'http://127.0.0.1:2', KEY, 25)}
        link = sessions.HttpGameLink(eps, timeout=5)
        with mock.patch.object(sessions.urllib.request, 'urlopen', urlopen):
            for gid in eps:
                s = type('S', (), {'game_id': gid, 'id': 'session-' + 'a' * 32})()
                self.assertEqual(link.launch(s, []), (True, None))
                self.assertTrue(link.end(s))
        self.assertEqual([t for _, t in seen], [5, 5, 25, 25])
        self.assertEqual(seen[2][0], 'http://127.0.0.1:2' + sessions.LAUNCH_PATH)


class Flow(ServiceCase):
    def setUp(self):
        super().setUp()
        self.server.shutdown()                       # rebuild with the protocol routes attached
        self.server.server_close()
        from avrana.party import service
        self.game = ReferenceGame(0)
        endpoints = {'bluff': sessions.GameEndpoint('bluff', self.game.url, KEY)}
        self.svc.link = sessions.HttpGameLink(endpoints, timeout=5)
        extra, internal = sessions.routes(self.svc, endpoints)
        cfg = service.Config({HOST}, {ORIGIN}, secure_cookie=True)
        self.server = service.make_server(self.svc, cfg, port=0, extra_routes=extra,
                                          internal_routes=internal)
        self.port = self.server.server_address[1]
        self.game.party_port = self.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.ana, self.ben = self.phone(), self.phone()
        self.ana.post('join', {'name': 'Ana'})
        self.ben.post('join', {'name': 'Ben'})

    def tearDown(self):
        self.game.stop()
        super().tearDown()

    def launch(self):
        _, v, _ = self.ana.state()
        status, v, _ = self.ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((status, v['state']), (200, 'active'), v)
        return v['session']['id']

    def ticket(self, phone):
        return phone.post('session/ticket')

    def end_for_everyone(self):
        _, v, _ = self.ana.state()
        return self.ana.post('session/end', {'if_version': v['version']})

    # ---- launch and admission -------------------------------------------------------------------
    def test_launch_sends_only_the_roster_the_game_needs(self):
        sid = self.launch()
        self.assertEqual(self.game.side.sid, sid)
        roster = self.game.launches[0]
        self.assertEqual([(r['name'], r['role']) for r in roster], [('Ana', 'player'), ('Ben', 'player')])
        text = json.dumps(roster)
        for secret in (self.ana.cookie, self.ben.cookie, 'member-', 'device-'):
            self.assertNotIn(secret, text)

    def test_ticket_admits_and_reconnect_restores_the_same_game_identity(self):
        self.launch()
        status, t1, r = self.ticket(self.ben)
        self.assertEqual((status, t1['role'], t1['protocol']), (200, 'player', protocol.VERSION))
        self.assertEqual(r.getheader('Cache-Control'), 'no-store')
        tok1, role = self.game.hello(t1['ticket'])
        _, t2, _ = self.ticket(self.ben)                 # the phone slept, reloaded, came back
        self.assertEqual(self.game.hello(t2['ticket']), (tok1, role))
        _, ta, _ = self.ticket(self.ana)
        self.assertNotEqual(self.game.hello(ta['ticket'])[0], tok1)
        self.assertNotIn(self.ben.cookie, json.dumps([t1, t2]))

    def test_late_member_gets_a_spectator_ticket(self):
        self.launch()
        cy = self.phone()
        cy.post('join', {'name': 'Cy'})
        _, t, _ = self.ticket(cy)
        self.assertEqual(self.game.hello(t['ticket'])[1], 'spectator')

    def test_a_page_naming_another_game_gets_no_ticket_and_starts_nothing(self):
        sid = self.launch()                                  # AVR-128: a direct or stale URL
        status, body, _ = self.ben.post('session/ticket', {'game': 'bomber'})
        self.assertEqual((status, body['error']), (409, 'no_game'))
        status, t, _ = self.ben.post('session/ticket', {'game': 'bluff'})
        self.assertEqual((status, t['session']), (200, sid))
        self.assertEqual(len(self.game.launches), 1)
        _, v, _ = self.ben.state()
        self.assertEqual((v['state'], v['session']['id']), ('active', sid))

    def test_switch_resets_the_old_game_before_its_next_session_and_old_tickets_die(self):
        sid = self.launch()
        _, old, _ = self.ticket(self.ben)
        _, v, _ = self.ana.state()
        status, v, _ = self.ana.post('session/switch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((status, v['state']), (200, 'active'))
        new = v['session']['id']
        self.assertNotEqual(new, sid)
        self.assertEqual(self.game.ends, [sid])
        self.assertEqual(len(self.game.launches), 2)         # end, then the next launch
        self.assertEqual(self.game.side.sid, new)
        with self.assertRaises(Invalid):
            self.game.hello(old['ticket'])                   # the old session's ticket is dead
        _, t, _ = self.ticket(self.ben)
        self.assertEqual(t['session'], new)

    def test_no_ticket_without_membership_or_a_game(self):
        self.assertEqual(self.ticket(self.ana)[0], 409)                  # no game on
        self.launch()
        stranger = self.phone()
        self.assertEqual(self.ticket(stranger)[0], 403)
        self.assertEqual(self.ticket(self.phone(origin='https://evil.example'))[0], 403)

    def test_tickets_ride_in_the_hello_never_the_url(self):
        self.launch()
        status, _, _ = self.ana.req('GET', sessions.TICKET_ROUTE)
        self.assertEqual(status, 404)                                    # POST only, body only

    # ---- completion -------------------------------------------------------------------------------
    def test_game_reports_completed_server_to_server(self):
        sid = self.launch()
        status, body = self.game.report(self.game.side.ended('completed'))
        self.assertEqual((status, body), (200, {'ok': True}))
        _, v, _ = self.ben.state()
        self.assertEqual((v['state'], v['session']['id'], v['session']['outcome']),
                         ('lobby', sid, 'completed'))

    def test_abandoned_is_distinct(self):
        self.launch()
        self.game.report(self.game.side.ended('abandoned'))
        self.assertEqual(self.ben.state()[1]['session']['outcome'], 'abandoned')

    def test_a_browser_cannot_forge_completion(self):
        sid = self.launch()
        # 1. Through the reverse proxy (as a phone would arrive): the route does not exist.
        forged = protocol.ended_message(KEY, 'bluff', sid, 'completed')
        status, _ = self.game.report(forged, headers={'X-Forwarded-For': '10.42.0.23'})
        self.assertEqual(status, 404)
        # 2. On /party/api/ with the phone's own cookie: no such route.
        self.assertEqual(self.ana.post('session/ended', {'message': forged})[0], 404)
        # 3. Without the key: a ticket, a guess or a message signed with another key.
        _, t, _ = self.ticket(self.ana)
        for bad in (t['ticket'], 'aps0.e30.AAAA', 'aps0.x.y', 'aps0.e30.AA+A',
                    protocol.ended_message(protocol.new_key(), 'bluff', sid, 'completed'),
                    protocol.ended_message(KEY, 'spades', sid, 'completed')):
            with self.subTest(bad=bad[:30]):
                self.assertEqual(self.game.report(bad)[0], 403)
        self.assertEqual(self.ben.state()[1]['state'], 'active')          # nothing ended

    def test_stale_and_replayed_reports_are_refused(self):
        sid1 = self.launch()
        report = self.game.side.ended('completed')
        self.assertEqual(self.game.report(report)[0], 200)
        self.assertEqual(self.game.report(report)[0], 403)                 # replay
        self.launch()
        late = protocol.ended_message(KEY, 'bluff', sid1, 'abandoned')     # old session, valid sig
        self.assertEqual(self.game.report(late)[0], 409)
        self.assertEqual(self.ben.state()[1]['state'], 'active')          # the new game runs on

    # ---- end for everyone ---------------------------------------------------------------------------
    def test_end_for_everyone_resets_the_game_and_kills_tickets(self):
        sid = self.launch()
        _, t, _ = self.ticket(self.ben)
        status, v, _ = self.end_for_everyone()
        self.assertEqual((status, v['state'], v['session']['outcome']), (200, 'lobby', 'ended_by_host'))
        self.assertEqual(self.game.ends, [sid])
        self.assertIsNone(self.game.side.sid)                              # non-running
        with self.assertRaises(Invalid):
            self.game.hello(t['ticket'])                                   # old tickets are dead
        self.assertEqual(self.ticket(self.ben)[0], 409)                    # and no new ones
        self.assertEqual(self.game.report(protocol.ended_message(KEY, 'bluff', sid, 'completed'))[0], 409)
        self.assertEqual(self.ben.state()[1]['state'], 'lobby')           # nothing resurrected

    def test_game_down_launch_fails_readably_and_end_still_ends(self):
        self.game.stop()
        _, v, _ = self.ana.state()
        _, v, _ = self.ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((v['state'], v['session']['outcome']), ('lobby', 'launch_failed'))
        self.assertIn('did not answer', v['session']['detail'])
        self.game = ReferenceGame(self.port)                               # for tearDown


    def test_end_unconfirmed_when_the_game_is_gone(self):
        """If the game is gone when the host ends it, the party still returns home, and says so."""
        self.launch()
        self.game.stop()
        _, v, _ = self.end_for_everyone()
        self.assertEqual((v['state'], v['session']['outcome']), ('lobby', 'ended_by_host'))
        self.assertFalse(self.svc.core.party.session.game_confirmed_end)
        self.game = ReferenceGame(self.port)


if __name__ == '__main__':
    unittest.main()
