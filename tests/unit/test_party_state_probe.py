"""PROTOTYPE (AVR-673 phase 1): the signed state probe, its counting in Party Core, and the
service asking a real (stub) game over loopback. A flag only: no round is ever closed by it."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading
import unittest

from avrana.contracts import party_config
from avrana.party import core, identity, protocol, service, sessions, state_probe
from test_party_core import BLUFF, make, play

KEY = b'k' * 32
SID = 'session-' + '0' * 32
DECLARED = dict(BLUFF, state_probe=True)


class Messages(unittest.TestCase):
    def test_a_question_and_its_answer_round_trip(self):
        asked = state_probe.open_question(KEY, state_probe.question(KEY, 'bluff', SID), 'bluff')
        for holds in (True, False):
            token = state_probe.answer(KEY, asked, holds)
            self.assertIs(state_probe.read_answer(KEY, token, 'bluff', asked), holds)

    def test_an_answer_proves_nothing_unless_it_answers_exactly_this_question(self):
        asked = state_probe.open_question(KEY, state_probe.question(KEY, 'bluff', SID), 'bluff')
        other = state_probe.open_question(KEY, state_probe.question(KEY, 'bluff', SID), 'bluff')
        cases = {'another question': state_probe.answer(KEY, other, True),
                 'another key': state_probe.answer(b'x' * 32, asked, True),
                 'another game': state_probe.answer(KEY, dict(asked, aud='expo'), True),
                 'a ticket': protocol.mint_ticket(KEY, 'bluff', SID, 'participant-' + '1' * 32, 'player')}
        for name, token in cases.items():
            with self.subTest(name):
                with self.assertRaises(protocol.Invalid):
                    state_probe.read_answer(KEY, token, 'bluff', asked)

    def test_the_contract_opts_in_and_nothing_else_does(self):
        base = {'id': 'tiles', 'players': {'min': 2, 'max': 4}, 'late_join': 'next_round'}
        self.assertNotIn('state_probe', party_config.metadata(dict(base, extensions={})))
        on = dict(base, extensions={'net.avrana.party': {'state': True}})
        self.assertTrue(party_config.metadata(on)['state_probe'])
        with self.assertRaises(party_config.ConfigError):
            party_config.metadata(dict(base, extensions={'net.avrana.party': {'state': 'yes'}}))


class Counting(unittest.TestCase):
    def active(self, game=DECLARED):
        pc, clock = make([game])
        pc.join('device-a', 'Ana')
        pc.join('device-b', 'Ben')
        s = pc.launch('device-a', 'bluff', pc.party.version)
        pc.launch_accepted(s.id)
        return pc, clock, s

    def test_a_game_that_says_it_holds_nothing_is_flagged_and_the_round_goes_on(self):
        pc, clock, s = self.active()
        self.assertTrue(pc.view('device-a')['session']['game_answering'])
        self.assertFalse(pc.state_answer(s.id, 'not_holds'))
        clock.advance(core.STATE_NOT_HOLDS_SPAN)
        self.assertTrue(pc.state_answer(s.id, 'not_holds'))
        self.assertEqual((s.state, s.game_answering), (core.ACTIVE, False))
        self.assertFalse(pc.view('device-b')['session']['game_answering'])
        play(pc, clock, 600, 'device-a', 'device-b')             # ten minutes of a table still playing
        pc.tick()
        self.assertEqual(s.state, core.ACTIVE)                   # phase 1 never closes a round
        self.assertTrue(pc.state_answer(s.id, 'holds'))          # and one good answer clears it
        self.assertTrue(s.game_answering)

    def test_silence_needs_more_misses_over_a_longer_span(self):
        pc, clock, s = self.active()
        for _ in range(core.STATE_SILENT_FAILS):
            pc.state_answer(s.id, 'silent')
            clock.advance(core.STATE_SILENT_SPAN / core.STATE_SILENT_FAILS)
        self.assertTrue(s.game_answering)                        # three misses inside 15 s: not yet
        pc.state_answer(s.id, 'silent')
        self.assertFalse(s.game_answering)

    def test_ignored_answers_and_undeclared_games_change_nothing(self):
        pc, clock, s = self.active()
        for _ in range(5):
            clock.advance(10)
            self.assertFalse(pc.state_answer(s.id, 'ignored'))
        self.assertTrue(s.game_answering)
        pc, clock, s = self.active(BLUFF)
        self.assertNotIn('game_answering', pc.view('device-a')['session'])   # the view is as before
        clock.advance(10)
        self.assertFalse(pc.state_answer(s.id, 'not_holds'))
        clock.advance(10)
        self.assertFalse(pc.state_answer(s.id, 'not_holds'))
        self.assertIsNone(s.game_answering)


class StubGame:
    """A game on loopback: answers the state question as told, or accepts and never answers."""

    def __init__(self, mode):
        self.mode, self.asked = mode, 0
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                stub.asked += 1
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if stub.mode == '404':
                    self.send_response(404)
                    self.end_headers()
                    return
                asked = state_probe.open_question(KEY, body['message'], 'bluff')
                reply = json.dumps({'message': state_probe.answer(KEY, asked, stub.mode == 'holds')}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

        if mode == 'wedged':                  # listens, accepts, never reads or answers
            self.sock = socket.socket()
            self.sock.bind(('127.0.0.1', 0))
            self.sock.listen(8)
            self.port = self.sock.getsockname()[1]
            self.close = self.sock.close
        else:
            self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            self.port = self.server.server_address[1]
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
            self.close = lambda: (self.server.shutdown(), self.server.server_close())

    def link(self):
        ep = sessions.GameEndpoint('bluff', f'http://127.0.0.1:{self.port}', KEY, timeout=0.5)
        return sessions.HttpGameLink({'bluff': ep})


class OverLoopback(unittest.TestCase):
    def outcome(self, mode):
        game = StubGame(mode)
        self.addCleanup(game.close)
        s = core.GameSession(DECLARED, 'member-a', 0.0)
        s.id = SID
        return state_probe.ask(game.link(), s)

    def test_each_kind_of_game_gives_its_outcome(self):
        self.assertEqual(self.outcome('holds'), state_probe.HOLDS)
        self.assertEqual(self.outcome('not'), state_probe.NOT_HOLDS)
        self.assertEqual(self.outcome('404'), state_probe.IGNORED)        # declared but does not answer the route
        self.assertEqual(self.outcome('wedged'), state_probe.SILENT)     # the gap the connect check misses

    def test_the_service_flags_a_wedged_game_that_declared_the_probe(self):
        game = StubGame('wedged')
        self.addCleanup(game.close)
        clock = [1000.0]
        svc = service.PartyService(identity.DeviceStore(None), {'bluff': DECLARED}, game.link(),
                                   clock=lambda: clock[0])
        svc.core.join('device-a', 'Ana')
        svc.core.join('device-b', 'Ben')
        s = svc.core.launch('device-a', 'bluff', svc.core.party.version)
        svc.core.launch_accepted(s.id)
        outcomes = []
        for _ in range(core.STATE_SILENT_FAILS + 1):
            outcomes.append(svc.ask_state(wait=True))
            self.assertIsNone(svc.ask_state(wait=True))           # never more often than STATE_EVERY
            clock[0] += service.STATE_EVERY
        self.assertEqual(outcomes, [state_probe.SILENT] * (core.STATE_SILENT_FAILS + 1))
        self.assertEqual((s.state, s.game_answering), (core.ACTIVE, False))


if __name__ == '__main__':
    unittest.main()
