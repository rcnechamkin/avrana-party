"""Game result envelope v1 (avrana.party.result, ADR 0015): the shared vectors, the envelope
riding the signed `ended` message, and Party Core's single acceptance boundary.
The path over real HTTP is in test_party_session_flow.py."""
import json
import unittest

from avrana import CONTRACTS_DIR
from avrana.party import core, protocol, result
from avrana.party.core import Refused

from test_party_core import BLUFF, make

EXPO = {'id': 'expo', 'min_players': 3, 'max_players': 5, 'late_join': 'spectator_only'}
KEY = bytes(range(32))
SID = 'session-' + '1' * 32


class Vectors(unittest.TestCase):
    """The shared cases pin the rules for the games repository too."""

    def setUp(self):
        self.doc = json.loads((CONTRACTS_DIR / 'vectors' / 'game-result.v1.json').read_text('utf-8'))

    def test_every_case_is_decided_as_recorded(self):
        self.assertEqual(self.doc['schema'], result.SCHEMA)
        self.assertEqual(self.doc['limits'], {'max_bytes': result.MAX_BYTES,
                                              'max_data_bytes': result.MAX_DATA_BYTES,
                                              'max_depth': result.MAX_DEPTH})
        for case in self.doc['cases']:
            with self.subTest(case['name']):
                if case['accept']:
                    self.assertEqual(result.check(case['result'], case['game'], case['players']),
                                     case['result'])
                else:
                    with self.assertRaises(result.Refused) as refused:
                        result.check(case['result'], case['game'], case['players'])
                    self.assertEqual(str(refused.exception), case['reason'])

    def test_the_cases_cover_both_kinds_of_game_and_every_refusal(self):
        names = ' | '.join(c['name'] for c in self.doc['cases'])
        for needed in ('bluff: one winner', 'cooperative success', 'cooperative failure'):
            self.assertIn(needed, names)
        reasons = {c.get('reason') for c in self.doc['cases']}
        self.assertLessEqual({'schema', 'game', 'shape', 'mode', 'participant', 'not_in_session',
                              'incomplete', 'standings', 'rank', 'data_schema', 'data', 'size'}, reasons)


class Build(unittest.TestCase):
    P = ['participant-' + c * 32 for c in 'ab']

    def test_build_returns_what_check_accepts(self):
        r = result.build('bluff', '1.0', 'competitive',
                         [{'participant': self.P[0], 'standing': 'won'},
                          {'participant': self.P[1], 'standing': 'lost'}], self.P,
                         data_schema='bluff.result/v1', data={'steps': 3}, content='base')
        self.assertEqual(result.check(r, 'bluff', self.P), r)
        self.assertEqual(r['game'], {'id': 'bluff', 'build': '1.0', 'content': 'base'})
        self.assertNotIn('data', result.build('bluff', '1.0', 'competitive', r['standings'], self.P))

    def test_a_game_cannot_build_what_the_party_would_refuse(self):
        for kwargs, reason in (({'data': {'x': float('nan')}, 'data_schema': 'a.b/v1'}, 'shape'),
                               ({'data': {'x': 1}}, 'data_schema'),
                               ({'content': 'has space'}, 'game')):
            with self.subTest(reason), self.assertRaises(result.Refused) as refused:
                result.build('bluff', '1.0', 'competitive',
                             [{'participant': p, 'standing': 'draw'} for p in self.P], self.P, **kwargs)
            self.assertEqual(str(refused.exception), reason)

    def test_no_member_or_device_identity_has_a_place_in_the_envelope(self):
        """Per-participant entries take participant, standing and rank; nothing else."""
        for extra in ({'member': 'member-' + 'a' * 32}, {'device': 'device-' + 'a' * 32}, {'name': 'Ana'}):
            with self.subTest(extra), self.assertRaises(result.Refused):
                result.build('bluff', '1.0', 'competitive',
                             [dict({'participant': p, 'standing': 'draw'}, **extra) for p in self.P], self.P)


class Carriage(unittest.TestCase):
    """`ended` carries the result: signed, bound to the session, replay-guarded with it."""

    R = {'schema': result.SCHEMA, 'game': {'id': 'bluff', 'build': '1'}, 'mode': 'competitive',
         'standings': [{'participant': 'participant-' + 'a' * 32, 'standing': 'won'}]}

    def test_the_result_rides_inside_the_signed_message(self):
        msg = protocol.ended_message(KEY, 'bluff', SID, 'completed', result=self.R)
        p = protocol.open_message(KEY, msg, 'ended', 'party', protocol.ReplayGuard())
        self.assertEqual((p['result'], p['sid'], p['iss'], p['v']), (self.R, SID, 'bluff', protocol.VERSION))
        with self.assertRaises(protocol.Invalid):                       # another game's key
            protocol.open_message(bytes(32), msg, 'ended', 'party', protocol.ReplayGuard())

    def test_a_message_without_a_result_is_unchanged(self):
        p = protocol.open_message(KEY, protocol.ended_message(KEY, 'bluff', SID, 'completed'),
                                  'ended', 'party', protocol.ReplayGuard())
        self.assertNotIn('result', p)

    def test_a_tampered_result_breaks_the_signature(self):
        msg = protocol.ended_message(KEY, 'bluff', SID, 'completed', result=self.R)
        other = protocol.ended_message(KEY, 'bluff', SID, 'completed',
                                       result=dict(self.R, mode='cooperative'))
        head, body, mac = msg.split('.')
        forged = '.'.join((head, other.split('.')[1], mac))
        with self.assertRaises(protocol.Invalid) as e:
            protocol.open_message(KEY, forged, 'ended', 'party', protocol.ReplayGuard())
        self.assertEqual(str(e.exception), 'signature')

    def test_the_sender_refuses_a_result_that_cannot_fit_or_is_not_an_object(self):
        with self.assertRaises(ValueError):
            protocol.ended_message(KEY, 'bluff', SID, 'completed', result=['won'])
        with self.assertRaises(ValueError):
            protocol.ended_message(KEY, 'bluff', SID, 'completed', result={'x': 'y' * 9000})

    def test_game_side_keeps_its_session_when_the_report_cannot_be_built(self):
        side = protocol.GameSide(KEY, 'bluff')
        side.on_launch(protocol.launch_message(KEY, 'bluff', SID, []))
        with self.assertRaises(ValueError):
            side.ended('completed', result={'x': 'y' * 9000})
        self.assertEqual(side.sid, SID)                                 # still able to report
        self.assertTrue(side.ended('completed', result=self.R))


class Boundary(unittest.TestCase):
    """PartyCore._accept_result: the one place a result becomes the party's."""

    def setUp(self):
        self.pc, self.clock = make([BLUFF, EXPO])
        self.members = [self.pc.join(f'device-{n}', name)
                        for n, name in enumerate(('Ana', 'Ben', 'Cy'))]

    def active(self, game='bluff'):
        s = self.pc.launch('device-0', game, self.pc.party.version)
        self.pc.launch_accepted(s.id)
        return s, [p.id for p in s.participants.values() if p.role == 'player']

    def bluff(self, pids, **change):
        r = {'schema': result.SCHEMA, 'game': {'id': 'bluff', 'build': 'sha256:abc'},
             'mode': 'competitive',
             'standings': [{'participant': pids[0], 'standing': 'won'}]
             + [{'participant': p, 'standing': 'lost'} for p in pids[1:]],
             'data_schema': 'bluff.result/v1', 'data': {'steps': 12, 'forfeited': [pids[2]]}}
        r.update(change)
        return r

    def test_an_accepted_bluff_result_is_kept_with_the_session_as_the_partys_record(self):
        s, pids = self.active()
        self.pc.game_reported_end(s.id, 'completed', self.bluff(pids))
        self.assertEqual((s.state, s.outcome, s.result_refused), (core.ENDED, 'completed', None))
        r = s.result
        self.assertEqual((r['schema'], r['session'], r['outcome'], r['mode']),
                         (result.SCHEMA, s.id, 'completed', 'competitive'))
        self.assertEqual(r['game'], {'id': 'bluff', 'build': 'sha256:abc'})
        # the party adds what only it knows: which member each participant was
        self.assertEqual([(e['member'], e['standing']) for e in r['standings']],
                         [(self.members[0].id, 'won'), (self.members[1].id, 'lost'),
                          (self.members[2].id, 'lost')])
        self.assertEqual((r['data_schema'], r['data']['steps']), ('bluff.result/v1', 12))

    def test_a_cooperative_expo_shaped_result_needs_no_other_rules(self):
        s, pids = self.active('expo')
        coop = {'schema': result.SCHEMA, 'game': {'id': 'expo', 'build': 'sha256:def', 'content': 'missions-1'},
                'mode': 'cooperative',
                'standings': [{'participant': p, 'standing': 'lost'} for p in pids],
                'data_schema': 'expo.result/v1',
                'data': {'mission': 17, 'status': 'failure', 'attempts': 2}}
        self.pc.game_reported_end(s.id, 'completed', coop)
        self.assertEqual((s.result['mode'], {e['standing'] for e in s.result['standings']}),
                         ('cooperative', {'lost'}))
        self.assertEqual(s.result['data'], coop['data'])
        self.assertEqual(self.pc.location()['at'], 'results')           # lifecycle as without one

    def test_a_refused_result_still_ends_the_session_and_keeps_nothing(self):
        cases = (('schema', lambda r, p: r.update(schema='avrana.game-result/v9')),
                 ('game', lambda r, p: r['game'].update(id='expo')),
                 ('participant', lambda r, p: r['standings'][0].update(participant='nobody')),
                 ('not_in_session', lambda r, p: r['standings'][0].update(participant='participant-' + 'f' * 32)),
                 ('incomplete', lambda r, p: r['standings'].pop()),
                 ('size', lambda r, p: r['data'].update(blob=['x' * 150] * 8)),
                 ('data', lambda r, p: r['data'].update(deep=[[[[[1]]]]])),
                 ('shape', lambda r, p: r.update(member_ids=[m.id for m in self.members])))
        for reason, damage in cases:
            with self.subTest(reason):
                self.setUp()
                s, pids = self.active()
                r = self.bluff(pids)
                damage(r, pids)
                self.pc.game_reported_end(s.id, 'completed', r)
                self.assertEqual((s.state, s.outcome), (core.ENDED, 'completed'))
                self.assertEqual((s.result, s.result_refused), (None, reason))

    def test_a_non_object_result_is_refused_not_guessed(self):
        s, _ = self.active()
        self.pc.game_reported_end(s.id, 'completed', 'ana won')
        self.assertEqual((s.result, s.result_refused, s.outcome), (None, 'shape', 'completed'))

    def test_a_spectator_cannot_be_given_a_standing(self):
        self.pc.join('device-9', 'Dee')                                 # the table is full (3)
        s, pids = self.active()
        late = self.pc.participant_for('device-9')[1]
        self.assertEqual(late.role, 'spectator')
        r = self.bluff(pids)
        r['standings'].append({'participant': late.id, 'standing': 'lost'})
        self.pc.game_reported_end(s.id, 'completed', r)
        self.assertEqual((s.result, s.result_refused), (None, 'not_in_session'))

    def test_an_abandoned_session_has_no_result(self):
        s, pids = self.active()
        self.pc.game_reported_end(s.id, 'abandoned', self.bluff(pids))
        self.assertEqual((s.outcome, s.result, s.result_refused), ('abandoned', None, 'not_completed'))
        self.assertEqual(self.pc.location()['at'], 'home')

    def test_when_the_hosts_end_won_the_race_the_result_is_not_taken(self):
        s, pids = self.active()
        self.pc.begin_end('device-0', self.pc.party.version)
        self.pc.game_reported_end(s.id, 'completed', self.bluff(pids))
        self.assertEqual((s.outcome, s.result, s.result_refused),
                         ('ended_by_host', None, 'not_completed'))

    def test_a_second_result_cannot_replace_the_first(self):
        s, pids = self.active()
        first = self.bluff(pids)
        self.pc.game_reported_end(s.id, 'completed', first)
        kept = json.dumps(s.result, sort_keys=True)
        other = self.bluff(list(reversed(pids)))                        # a different winner
        with self.assertRaises(Refused) as e:
            self.pc.game_reported_end(s.id, 'completed', other)
        self.assertEqual(e.exception.code, 'stale_session')
        self.assertEqual(json.dumps(s.result, sort_keys=True), kept)

    def test_a_result_for_another_session_never_lands(self):
        s1, pids1 = self.active()
        self.pc.game_reported_end(s1.id, 'completed')                   # ended with no result
        self.pc.go_home('device-0', self.pc.party.version)
        s2, _ = self.active()
        with self.assertRaises(Refused):
            self.pc.game_reported_end(s1.id, 'completed', self.bluff(pids1))    # stale session
        self.assertIsNone(s1.result)
        self.pc.game_reported_end(s2.id, 'completed', self.bluff(pids1))         # old participants
        self.assertEqual((s2.result, s2.result_refused), (None, 'not_in_session'))

    def test_a_plain_end_is_exactly_as_before(self):
        s, _ = self.active()
        self.pc.game_reported_end(s.id, 'completed')
        self.assertEqual((s.outcome, s.result, s.result_refused), ('completed', None, None))

    def test_phones_are_not_shown_the_result_record(self):
        """The view is unchanged by this work: what phones see of results is AVR-71's decision."""
        s, pids = self.active()
        self.pc.game_reported_end(s.id, 'completed', self.bluff(pids))
        view = json.dumps(self.pc.view('device-1'))
        self.assertNotIn('standings', view)
        for pid in pids:
            self.assertNotIn(pid, view)


if __name__ == '__main__':
    unittest.main()
