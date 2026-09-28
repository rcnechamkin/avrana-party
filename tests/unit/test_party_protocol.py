"""Party session protocol v0 (avrana.party.protocol): envelope, tickets, messages, GameSide."""
import json
import os
import tempfile
import unittest

from avrana import CONTRACTS_DIR
from avrana.party import protocol as P
from avrana.party.protocol import Invalid

KEY = bytes(range(32))
OTHER = bytes(32)
SID = 'session-' + 'a' * 32
SID2 = 'session-' + 'b' * 32
PID = 'participant-' + 'c' * 32
PID2 = 'participant-' + 'd' * 32
NOW = 2_000_000_000
ROSTER = [{'participant': PID, 'name': 'Ana', 'role': 'player'},
          {'participant': PID2, 'name': 'Ben', 'role': 'spectator'}]


class Vectors(unittest.TestCase):
    """The shared vectors pin the wire format for the games repository too."""

    def test_vectors(self):
        doc = json.loads((CONTRACTS_DIR / 'vectors' / 'party-session.v0.json').read_text('utf-8'))
        key = bytes.fromhex(doc['key_hex'])
        self.assertEqual(doc['protocol'], P.VERSION)
        for v in doc['vectors']:
            with self.subTest(v['name']):
                self.assertEqual(P.seal(key, v['payload']), v['token'])
                aud = v['payload']['aud']
                self.assertEqual(P.unseal(key, v['token'], v['name'], aud, now=doc['now']), v['payload'])
        g = doc['game_token']
        self.assertEqual(P.game_token(key, g['sid'], g['participant']), g['token'])


class Tickets(unittest.TestCase):
    def ticket(self, **kw):
        args = dict(key=KEY, game='bluff', sid=SID, participant=PID, role='player', now=NOW)
        args.update(kw)
        return P.mint_ticket(args['key'], args['game'], args['sid'], args['participant'],
                             args['role'], now=args['now'])

    def refused(self, ticket, reason, game='bluff', sid=SID, now=NOW + 1, key=KEY):
        with self.assertRaises(Invalid) as e:
            P.verify_ticket(key, ticket, game, sid, now=now)
        self.assertEqual(str(e.exception), reason)

    def test_valid(self):
        got = P.verify_ticket(KEY, self.ticket(), 'bluff', SID, now=NOW + 1)
        self.assertEqual(got, {'participant': PID, 'role': 'player', 'sid': SID})

    def test_carries_no_identity_beyond_the_participant(self):
        payload = P.unseal(KEY, self.ticket(), 'ticket', 'bluff', now=NOW + 1)
        self.assertEqual(set(payload), {'v', 'typ', 'iss', 'aud', 'sid', 'iat', 'exp', 'pid', 'role'})

    def test_expired(self):
        self.refused(self.ticket(), 'expired', now=NOW + P.TICKET_TTL)

    def test_issued_in_the_future(self):
        self.refused(self.ticket(now=NOW + 60), 'expired', now=NOW)

    def test_wrong_audience(self):
        self.refused(self.ticket(game='spades'), 'audience')

    def test_wrong_session_or_none_running(self):
        self.refused(self.ticket(), 'session', sid=SID2)
        self.refused(self.ticket(), 'session', sid=None)

    def test_wrong_key(self):
        self.refused(self.ticket(key=OTHER), 'signature')

    def test_tampering(self):
        t = self.ticket()
        head, body, mac = t.split('.')
        payload = json.loads(P._unb64(body))
        payload['role'] = 'player'
        payload['pid'] = PID2                              # take someone else's seat
        forged = f'{head}.{P._b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())}.{mac}'
        self.refused(forged, 'signature')
        self.refused(t[:-2] + ('AA' if not t.endswith('AA') else 'BB'), 'signature')
        for junk in ('', 'aps0', 'aps0..', 'x.y.z', 'aps1.' + body + '.' + mac, None, 7, 'a' * 9000):
            with self.subTest(junk=str(junk)[:20]):
                with self.assertRaises(Invalid):
                    P.verify_ticket(KEY, junk, 'bluff', SID, now=NOW + 1)

    def test_a_message_is_never_a_ticket(self):
        launch = P.launch_message(KEY, 'bluff', SID, ROSTER, now=NOW)
        self.refused(launch, 'type')

    def test_bad_fields_are_not_minted(self):
        for bad in (dict(role='host'), dict(participant='member-' + 'c' * 32), dict(game='Bluff!')):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    self.ticket(**bad)


class GameToken(unittest.TestCase):
    def test_stable_per_participant_and_session_and_unguessable(self):
        a = P.game_token(KEY, SID, PID)
        self.assertEqual(a, P.game_token(KEY, SID, PID))              # reconnect: same token
        self.assertNotEqual(a, P.game_token(KEY, SID, PID2))
        self.assertNotEqual(a, P.game_token(KEY, SID2, PID))          # next session: unrelated
        self.assertNotEqual(a, P.game_token(OTHER, SID, PID))         # needs the key
        self.assertNotIn(PID[-32:], a)


class Messages(unittest.TestCase):
    def test_launch_roundtrip_and_replay(self):
        guard = P.ReplayGuard()
        m = P.launch_message(KEY, 'bluff', SID, ROSTER, now=NOW)
        p = P.open_message(KEY, m, 'launch', 'bluff', guard, now=NOW + 1)
        self.assertEqual(p['roster'], ROSTER)
        with self.assertRaises(Invalid) as e:
            P.open_message(KEY, m, 'launch', 'bluff', guard, now=NOW + 2)
        self.assertEqual(str(e.exception), 'replay')

    def test_roster_entries_are_exactly_three_fields(self):
        with self.assertRaises(ValueError):
            P.launch_message(KEY, 'bluff', SID, [dict(ROSTER[0], device='device-1')], now=NOW)
        with self.assertRaises(ValueError):
            P.launch_message(KEY, 'bluff', SID, [dict(ROSTER[0], role='host')], now=NOW)

    def test_ended_direction_and_outcomes(self):
        guard = P.ReplayGuard()
        m = P.ended_message(KEY, 'bluff', SID, 'abandoned', now=NOW)
        p = P.open_message(KEY, m, 'ended', 'party', guard, now=NOW + 1)
        self.assertEqual((p['iss'], p['outcome']), ('bluff', 'abandoned'))
        with self.assertRaises(ValueError):
            P.ended_message(KEY, 'bluff', SID, 'won', now=NOW)
        with self.assertRaises(Invalid):                              # an 'ended' is not an 'end'
            P.open_message(KEY, m, 'end', 'bluff', P.ReplayGuard(), now=NOW + 1)
        end = P.end_message(KEY, 'bluff', SID, now=NOW)
        with self.assertRaises(Invalid):                              # party->game never game->party
            P.open_message(KEY, end, 'ended', 'party', P.ReplayGuard(), now=NOW + 1)

    def test_messages_expire(self):
        m = P.end_message(KEY, 'bluff', SID, now=NOW)
        with self.assertRaises(Invalid):
            P.open_message(KEY, m, 'end', 'bluff', P.ReplayGuard(), now=NOW + P.MESSAGE_TTL)


class GameSideLifecycle(unittest.TestCase):
    def test_launch_admit_reconnect_end(self):
        side = P.GameSide(KEY, 'bluff')
        ticket = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW)
        with self.assertRaises(Invalid):
            side.admit(ticket, now=NOW + 1)                          # no session yet
        self.assertEqual(side.on_launch(P.launch_message(KEY, 'bluff', SID, ROSTER, now=NOW),
                                        now=NOW + 1), ROSTER)
        tok, role = side.admit(ticket, now=NOW + 1)
        again = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW + 500)
        self.assertEqual(side.admit(again, now=NOW + 501), (tok, role))   # reconnect: same token
        with self.assertRaises(Invalid):                              # an end for another session
            side.on_end(P.end_message(KEY, 'bluff', SID2, now=NOW + 2), now=NOW + 3)
        side.on_end(P.end_message(KEY, 'bluff', SID, now=NOW + 2), now=NOW + 3)
        with self.assertRaises(Invalid):
            side.admit(again, now=NOW + 4)                            # ended: tickets are dead
        with self.assertRaises(Invalid):
            side.ended('completed')                                   # nothing to report

    def test_a_new_launch_replaces_the_old_session(self):
        side = P.GameSide(KEY, 'bluff')
        side.on_launch(P.launch_message(KEY, 'bluff', SID, ROSTER, now=NOW), now=NOW)
        side.on_launch(P.launch_message(KEY, 'bluff', SID2, ROSTER, now=NOW), now=NOW)
        old = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW)
        with self.assertRaises(Invalid):
            side.admit(old, now=NOW + 1)

    def test_ended_report_closes_admission(self):
        side = P.GameSide(KEY, 'bluff')
        side.on_launch(P.launch_message(KEY, 'bluff', SID, ROSTER, now=NOW), now=NOW)
        report = side.ended('completed', now=NOW + 5)
        p = P.open_message(KEY, report, 'ended', 'party', P.ReplayGuard(), now=NOW + 6)
        self.assertEqual((p['sid'], p['outcome']), (SID, 'completed'))
        self.assertIsNone(side.sid)


class Keys(unittest.TestCase):
    def test_key_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'bluff.key')
            key = P.new_key()
            P.write_key(path, key)
            self.assertEqual(P.read_key(path), key)
            with self.assertRaises(FileExistsError):
                P.write_key(path, P.new_key())                        # never silently rotated
            if os.name == 'posix':
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
                os.chmod(path, 0o644)
                with self.assertRaises(ValueError):
                    P.read_key(path)


if __name__ == '__main__':
    unittest.main()
