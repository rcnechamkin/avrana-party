"""The session protocol end to end over real HTTP on 127.0.0.1: Party Core + a reference game
server built on protocol.GameSide (the shape the games repository will implement next)."""
import http.client
import http.server
import json
import threading
import unittest

from avrana.party import core, protocol, result, sessions
from avrana.party.protocol import Invalid

from test_party_service import HOST, ORIGIN, BLUFF, Phone, ServiceCase

KEY = protocol.new_key()


class ReferenceGame:
    """A stand-in game server: the two protocol routes, a hello, and an ended report."""

    def __init__(self, party_port):
        self.side = protocol.GameSide(KEY, 'bluff')
        self.party_port = party_port
        self.launches, self.ends, self.end_posts = [], [], 0
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
                        game.end_posts += 1
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
        # AVR-223: an `end` never waits longer than Party Core's own END_TIMEOUT, so a game that
        # does not stop is reported unconfirmed (and a switch says why) before the party gives up
        self.assertEqual([t for _, t in seen], [5, 5, 25, sessions.END_LINK_TIMEOUT])
        self.assertLess(sessions.END_LINK_TIMEOUT, core.END_TIMEOUT)
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

    def test_abandoned_is_distinct_and_releases_the_game(self):
        self.launch()
        self.game.report(self.game.side.ended('abandoned'))
        _, v, _ = self.ben.state()
        self.assertEqual((v['session']['outcome'], v['location']['at']), ('abandoned', 'home'))
        # AVR-223: nothing is held on an abandoned round, so the party ends it at the game too
        # (the game already forgot the session, so it refuses; the party does not mind)
        self.assertEqual(self.game.end_posts, 1)

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

    # ---- structured results (ADR 0015) ---------------------------------------------------------------
    def result_for(self, winner=0, **change):
        pids = [r['participant'] for r in self.game.launches[-1] if r['role'] == 'player']
        r = {'schema': result.SCHEMA, 'game': {'id': 'bluff', 'build': 'sha256:abc'},
             'mode': 'competitive',
             'standings': [{'participant': p, 'standing': 'won' if i == winner else 'lost'}
                           for i, p in enumerate(pids)],
             'data_schema': 'bluff.result/v1', 'data': {'steps': 9}}
        r.update(change)
        return r

    def test_the_game_server_reports_a_result_and_the_party_keeps_it(self):
        sid = self.launch()
        status, body = self.game.report(self.game.side.ended('completed', result=self.result_for()))
        self.assertEqual((status, body), (200, {'ok': True, 'result': 'accepted'}))
        s = self.svc.core.party.session
        self.assertEqual((s.id, s.outcome, s.result['session'], s.result['mode']),
                         (sid, 'completed', sid, 'competitive'))
        members = {m['name']: m['id'] for m in self.ben.state()[1]['members']}
        self.assertEqual({e['member']: e['standing'] for e in s.result['standings']},
                         {members['Ana']: 'won', members['Ben']: 'lost'})
        self.assertEqual(self.ben.state()[1]['location']['at'], 'results')    # lifecycle unchanged

    def test_a_refused_result_is_reported_as_refused_and_the_session_still_ends(self):
        self.launch()
        bad = self.result_for(schema='avrana.game-result/v2')
        status, body = self.game.report(self.game.side.ended('completed', result=bad))
        self.assertEqual((status, body), (200, {'ok': True, 'result': 'refused', 'reason': 'schema'}))
        s = self.svc.core.party.session
        self.assertEqual((s.outcome, s.result, s.result_refused), ('completed', None, 'schema'))

    def test_a_replayed_or_second_result_never_replaces_the_first(self):
        sid = self.launch()
        first = protocol.ended_message(KEY, 'bluff', sid, 'completed', result=self.result_for(0))
        self.assertEqual(self.game.report(first)[1].get('result'), 'accepted')
        kept = json.dumps(self.svc.core.party.session.result, sort_keys=True)
        self.assertEqual(self.game.report(first)[0], 403)                       # replay
        second = protocol.ended_message(KEY, 'bluff', sid, 'completed', result=self.result_for(1))
        self.assertEqual(self.game.report(second)[0], 409)                      # the session is over
        self.assertEqual(json.dumps(self.svc.core.party.session.result, sort_keys=True), kept)

    def test_a_result_for_a_stale_session_is_refused_whole(self):
        sid1 = self.launch()
        old = self.result_for()
        self.game.report(self.game.side.ended('abandoned'))
        self.launch()
        late = protocol.ended_message(KEY, 'bluff', sid1, 'completed', result=old)
        self.assertEqual(self.game.report(late)[0], 409)
        s = self.svc.core.party.session
        self.assertEqual((s.state, s.result), ('active', None))                 # the new game runs on

    def test_a_result_from_the_wrong_issuer_or_key_is_refused_whole(self):
        sid = self.launch()
        r = self.result_for()
        for bad in (protocol.ended_message(protocol.new_key(), 'bluff', sid, 'completed', result=r),
                    protocol.ended_message(KEY, 'spades', sid, 'completed', result=r)):
            self.assertEqual(self.game.report(bad)[0], 403)
        s = self.svc.core.party.session
        self.assertEqual((s.state, s.result), ('active', None))

    def test_a_browser_cannot_submit_or_forge_a_result(self):
        sid = self.launch()
        r = self.result_for()
        signed = protocol.ended_message(KEY, 'bluff', sid, 'completed', result=r)
        # through the reverse proxy the route does not exist, even with a correctly signed message
        self.assertEqual(self.game.report(signed, headers={'X-Forwarded-For': '10.42.0.23'})[0], 404)
        # the phone's own API has no route that takes a result, signed or bare
        for route, body in (('session/ended', {'message': signed}), ('session/result', {'result': r}),
                            ('session/ticket', {'result': r})):
            status, _, _ = self.ana.post(route, body)
            self.assertIn(status, (200, 404), route)                            # ticket: field ignored
        # a ticket is not a report, and an unsigned result is nothing
        _, t, _ = self.ticket(self.ana)
        for bad in (t['ticket'], json.dumps(r)):
            self.assertEqual(self.game.report(bad)[0], 403)
        s = self.svc.core.party.session
        self.assertEqual((s.state, s.result), ('active', None))

    def test_an_oversized_report_is_refused_before_it_is_read_as_a_message(self):
        self.launch()
        status, _ = self.game.report('aps0.' + 'A' * 9000 + '.AAAA')
        self.assertEqual(status, 413)
        self.assertEqual(self.svc.core.party.session.state, 'active')

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


PREGAME_BLUFF = {'bluff': {'id': 'bluff', 'min_players': 2, 'max_players': 6,
                           'late_join': 'spectator_only', 'pregame': True}}


class PregameFlow(Flow):
    """AVR-129: every Flow test again, with BLUFF opening in the Party's setup: Ana and Ben
    choose to play and the host starts the round; plus the pregame's own protocol checks."""
    games = PREGAME_BLUFF

    def launch(self, choices=(('ana', 'player'), ('ben', 'player'))):
        _, v, _ = self.ana.state()
        status, v, _ = self.ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((status, v['state']), (200, 'setup'), v)
        for who, choice in choices:
            status, _, _ = getattr(self, who).post('session/choice', {'choice': choice})
            self.assertEqual(status, 200)
        _, v, _ = self.ana.state()
        status, v, _ = self.ana.post('session/start', {'if_version': v['version']})
        self.assertEqual((status, v['state']), (200, 'active'), v)
        return v['session']['id']

    def test_switch_resets_the_old_game_before_its_next_session_and_old_tickets_die(self):
        sid = self.launch()
        _, old, _ = self.ticket(self.ben)
        _, v, _ = self.ana.state()
        status, v, _ = self.ana.post('session/switch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual((status, v['state']), (200, 'setup'))    # the next round is set up first
        self.assertEqual(self.game.ends, [sid])
        self.assertEqual(len(self.game.launches), 1)              # nothing launched yet
        with self.assertRaises(Invalid):
            self.game.hello(old['ticket'])
        self.assertEqual(self.ben.post('session/ticket', {'game': 'bluff'})[1]['error'], 'setup')

    def test_game_down_launch_fails_readably_and_end_still_ends(self):
        self.game.stop()
        _, v, _ = self.ana.state()
        self.ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.ana.post('session/choice', {'choice': 'player'})
        self.ben.post('session/choice', {'choice': 'player'})
        _, v, _ = self.ana.state()
        _, v, _ = self.ana.post('session/start', {'if_version': v['version']})
        self.assertEqual((v['state'], v['session']['outcome'], v['nav']['to']), ('lobby', 'launch_failed', 'home'))
        self.assertIn('did not answer', v['session']['detail'])
        self.game = ReferenceGame(self.port)

    # ---- the pregame's own checks --------------------------------------------------------------
    def test_the_game_hears_nothing_until_the_host_starts_and_then_gets_the_chosen_roles(self):
        _, v, _ = self.ana.state()
        self.ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        self.assertEqual(self.game.launches, [])
        status, body, _ = self.ben.post('session/ticket', {'game': 'bluff'})
        self.assertEqual((status, body['error']), (409, 'setup'))   # the page waits, never joins alone
        self.ana.post('session/choice', {'choice': 'player'})
        self.ben.post('session/choice', {'choice': 'spectator'})
        _, v, _ = self.ben.state()
        status, body, _ = self.ben.post('session/start', {'if_version': v['version']})
        self.assertEqual((status, body['error']), (403, 'not_host'))
        status, body, _ = self.ana.post('session/start', {'if_version': v['version']})
        self.assertEqual((status, body['error']), (409, 'player_count'))  # one player; BLUFF needs 2
        self.assertEqual(self.game.launches, [])
        cy = self.phone()
        cy.post('join', {'name': 'Cy'})
        _, v, _ = self.ana.state()
        status, body, _ = self.ana.post('session/start', {'if_version': v['version']})
        self.assertEqual((status, body['error']), (409, 'unresolved'))
        self.assertIn('Cy', body['message'])
        cy.post('session/choice', {'choice': 'player'})
        _, v, _ = self.ana.state()
        status, v, _ = self.ana.post('session/start', {'if_version': v['version']})
        self.assertEqual((status, v['state']), (200, 'active'))
        roster = self.game.launches[0]
        self.assertEqual([(r['name'], r['role']) for r in roster],
                         [('Ana', 'player'), ('Cy', 'player'), ('Ben', 'spectator')])   # players first
        _, t, _ = self.ticket(self.ben)
        self.assertEqual(self.game.hello(t['ticket'])[1], 'spectator')
        status, body, _ = self.ben.post('session/choice', {'choice': 'player'})
        self.assertEqual((status, body['error']), (409, 'round_on'))    # next round, not this one
        _, t, _ = self.ticket(self.ben)
        self.assertEqual(self.game.hello(t['ticket'])[1], 'spectator')

    def test_host_end_during_setup_never_reaches_the_game(self):
        _, v, _ = self.ana.state()
        self.ana.post('session/launch', {'game': 'bluff', 'if_version': v['version']})
        _, v, _ = self.end_for_everyone()
        self.assertEqual((v['state'], v['nav']['to'], self.game.launches, self.game.ends),
                         ('lobby', 'home', [], []))


if __name__ == '__main__':
    unittest.main()
