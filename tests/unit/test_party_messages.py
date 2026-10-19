"""The Party room (AVR-54, docs/design/MESSAGING.md): pure room rules, system lines from Party
Core, and the two routes over real HTTP on both the Full and the Limited listener."""
import http.client
import io
import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr

from avrana.party import core, identity, messages, service

FULL_HOST, FULL_ORIGIN = 'party.test', 'https://party.test'
LIMITED_HOST, LIMITED_ORIGIN = '10.42.0.1', 'http://10.42.0.1'
BLUFF = {'bluff': {'id': 'bluff', 'max_players': 6, 'late_join': 'spectator_only'}}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class M:
    """A stand-in member for pure room tests."""

    def __init__(self, mid, name='Ana', avatar=None):
        self.id, self.name, self.avatar = mid, name, avatar


# ---- cleaning --------------------------------------------------------------------------------------
class Cleaning(unittest.TestCase):
    def clean(self, s):
        return messages.clean_text(s)

    def refused(self, s):
        with self.assertRaises(messages.Refused) as e:
            messages.clean_text(s)
        return e.exception.code

    def test_white_space_and_separators_become_one_space(self):
        self.assertEqual(self.clean('  hi\n\nthere\t you  '), 'hi there you')

    def test_control_bidi_and_invisible_formatting_are_removed(self):
        self.assertEqual(self.clean('a‮b​c⁦d\x07e'), 'abcde')

    def test_joiners_and_variation_selectors_stay(self):
        family = '\U0001F468‍\U0001F469‍\U0001F467'
        self.assertEqual(self.clean(family), family)
        self.assertEqual(self.clean('❤️'), '❤️')

    def test_private_use_surrogate_and_unassigned_are_removed(self):
        self.assertEqual(self.clean('ab\U0010ffffc'), 'abc')

    def test_stacked_marks_are_cut_to_four(self):
        self.assertEqual(self.clean('x' + '́' * 30), 'x' + '́' * 4)

    def test_nfc(self):
        self.assertEqual(self.clean('é'), 'é')

    def test_nothing_visible_is_empty(self):
        for s in ('', '   ', '‍‌', '‮', '️', '\n\t'):
            self.assertEqual(self.refused(s), 'empty', repr(s))

    def test_length_is_code_points_after_cleaning(self):
        self.assertEqual(len(self.clean('x' * 400)), 400)
        self.assertEqual(len(self.clean('\U0001F600' * 400)), 400)        # an emoji is one
        self.assertEqual(self.refused('x' * 401), 'too_long')
        self.assertEqual(len(self.clean('x' * 400 + '​' * 50)), 400)  # cleaned first

    def test_not_a_string(self):
        for s in (None, 3, ['hi'], {'t': 'x'}):
            self.assertEqual(self.refused(s), 'bad_text')

    def test_markup_is_kept_as_text(self):
        self.assertEqual(self.clean('<img src=x onerror=alert(1)>'), '<img src=x onerror=alert(1)>')


# ---- the room ---------------------------------------------------------------------------------------
class Room(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.room = messages.Room(self.clock)
        self.ana, self.ben = M('member-a', 'Ana', 'gaze-01'), M('member-b', 'Ben')

    def send(self, who, text='hi', cid=None):
        cid = cid or f'c{self.room.seq + 1}{who.id[-1]}{int(self.clock.t * 1000)}'
        return self.room.send(who, text, cid)

    def test_the_line_is_built_by_the_room(self):
        line, repeated = self.room.send(self.ana, 'hello', 'abc')
        self.assertFalse(repeated)
        self.assertEqual(line, {'seq': 1, 'kind': 'member', 'scope': 'party', 'from': 'member-a',
                                'name': 'Ana', 'avatar': 'gaze-01', 'text': 'hello', 'age_ms': 0})

    def test_a_rename_does_not_rewrite_old_lines(self):
        self.send(self.ana)
        self.ana.name = 'Anna'
        self.assertEqual(self.room.after(0)[0]['name'], 'Ana')

    def test_seq_is_shared_and_order_interleaves_both_rings(self):
        self.send(self.ana)
        self.room.system('joined', self.ben)
        self.clock.advance(1)
        self.send(self.ben)
        self.assertEqual([(l['seq'], l['kind']) for l in self.room.after(0)],
                         [(1, 'member'), (2, 'system'), (3, 'member')])
        self.assertEqual([l['seq'] for l in self.room.after(2)], [3])

    def test_age_is_relative_and_no_wall_clock_is_sent(self):
        self.send(self.ana)
        self.clock.advance(2.5)
        line = self.room.after(0)[0]
        self.assertEqual(line['age_ms'], 2500)
        self.assertNotIn('at', line)
        self.assertNotIn('ts', line)

    def test_member_ring_keeps_sixty_and_first_says_what_is_gone(self):
        for i in range(70):
            self.clock.advance(1)
            self.send(self.ana if i % 2 else self.ben, f'm{i}')
        held = self.room.after(0)
        self.assertEqual(len(held), 60)
        self.assertEqual(self.room.first(), 11)
        self.assertEqual(held[0]['text'], 'm10')

    def test_lost_says_what_left_either_ring_even_when_first_stays_low(self):
        self.room.system('joined', self.ben)                 # a quiet system ring keeps seq 1
        for i in range(80):
            self.clock.advance(1)
            self.send(self.ana, f'm{i}')
        self.assertEqual(self.room.first(), 1)
        self.assertEqual(self.room.lost, 21)                 # people 2..21 are gone
        self.assertEqual(messages.Room(self.clock).lost, 0)

    def test_system_lines_never_push_people_out(self):
        self.send(self.ana, 'keep me')
        for i in range(50):
            self.clock.advance(3)
            self.room.system('joined', M(f'member-{i}', f'P{i}'))
        kinds = [l['kind'] for l in self.room.after(0)]
        self.assertEqual(kinds.count('system'), 20)
        self.assertEqual(self.room.after(0)[0]['text'], 'keep me')

    def test_system_lines_are_metered_and_counted(self):
        self.assertIsNotNone(self.room.system('left', self.ana))
        for _ in range(5):
            self.assertIsNone(self.room.system('returned', self.ana))
            self.clock.advance(0.3)
        self.clock.advance(1)
        line = self.room.system('host', self.ben)
        self.assertEqual(line['more'], 5)
        self.assertEqual(len(self.room.system_lines), 2)

    def test_system_events_are_a_closed_list(self):
        with self.assertRaises(ValueError):
            self.room.system('anything you like', self.ana)

    def test_member_rate_six_in_four_seconds(self):
        for _ in range(6):
            self.send(self.ana)
        with self.assertRaises(messages.Refused) as e:
            self.send(self.ana)
        self.assertEqual(e.exception.code, 'too_fast')
        self.assertGreater(e.exception.retry_ms, 0)
        self.assertEqual(self.room.refusals['too_fast'], 1)
        self.send(self.ben)                                  # someone else is not limited
        self.clock.advance(4)
        self.send(self.ana)

    def test_party_rate_thirty_in_ten_seconds(self):
        people = [M(f'member-{i}', f'P{i}') for i in range(10)]
        for i in range(30):
            self.send(people[i % 10])
        with self.assertRaises(messages.Refused) as e:
            self.send(M('member-new', 'New'))
        self.assertEqual(e.exception.code, 'too_fast')

    def test_a_refused_send_stores_nothing(self):
        for text in ('', 'x' * 401):
            with self.assertRaises(messages.Refused):
                self.room.send(self.ana, text, 'abc')
        self.assertEqual(self.room.seq, 0)
        self.assertEqual(self.room.after(0), [])
        self.assertEqual(self.room.refusals['empty'], 1)

    def test_client_id_repeat_returns_the_stored_line_before_any_rate_check(self):
        first, _ = self.room.send(self.ana, 'once', 'retry-1')
        for _ in range(5):
            self.send(self.ana)
        again, repeated = self.room.send(self.ana, 'once', 'retry-1')     # at the rate limit
        self.assertTrue(repeated)
        self.assertEqual(again['seq'], first['seq'])
        other, repeated = self.room.send(self.ana, 'different text', 'retry-1')
        self.assertTrue(repeated)
        self.assertEqual(other['text'], 'once')
        self.assertEqual(self.room.seq, 6)

    def test_client_ids_are_per_member(self):
        a, _ = self.room.send(self.ana, 'from ana', 'same')
        b, repeated = self.room.send(self.ben, 'from ben', 'same')
        self.assertFalse(repeated)
        self.assertNotEqual(a['seq'], b['seq'])

    def test_client_id_repeat_after_the_line_left_the_ring_gives_its_seq(self):
        first, _ = self.room.send(self.ana, 'old', 'keep')
        for i in range(61):
            self.clock.advance(1)
            self.send(self.ben, f'm{i}')
        again, repeated = self.room.send(self.ana, 'old', 'keep')
        self.assertTrue(repeated)
        self.assertEqual(again, {'seq': first['seq']})

    def test_only_eight_client_ids_are_remembered(self):
        for i in range(9):
            self.clock.advance(1)
            self.room.send(self.ana, f'm{i}', f'id{i}')
        _, repeated = self.room.send(self.ana, 'again', 'id0')
        self.assertFalse(repeated)

    def test_bad_client_ids(self):
        for cid in (None, '', 'x' * 37, 'has space', 'émoji', 7, '../x'):
            with self.assertRaises(messages.Refused) as e:
                self.room.send(self.ana, 'hi', cid)
            self.assertEqual(e.exception.code, 'bad_client_id', repr(cid))


# ---- system lines from Party Core ----------------------------------------------------------------------
class SystemLines(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.core = core.PartyCore(self.clock, BLUFF)

    def lines(self):
        return [(l['event'], l['name']) + ((l['was'],) if 'was' in l else ())
                for l in self.core.party.room.after(0) if l['kind'] == 'system']

    def step(self):
        self.clock.advance(3)                    # past the 2-second meter

    def test_each_listed_event_writes_one_line(self):
        c = self.core
        c.join('d-ana', 'Ana'); self.step()
        c.join('d-ben', 'Ben'); self.step()
        c.rename('d-ben', 'Benji'); self.step()
        c.transfer_host('d-ana', c._member_of('d-ben').id, c.party.version); self.step()
        c.leave('d-ana'); self.step()
        c.reconnect('d-ana', 'Ana'); self.step()
        self.assertEqual(self.lines(), [('joined', 'Ana'), ('joined', 'Ben'), ('renamed', 'Benji', 'Ben'),
                                        ('host', 'Benji'), ('left', 'Ana'), ('returned', 'Ana')])

    def test_the_first_member_becoming_host_is_the_join_not_a_host_change(self):
        self.core.join('d-ana', 'Ana')
        self.step()
        self.core.join('d-ben', 'Ben')
        self.assertEqual(self.lines(), [('joined', 'Ana'), ('joined', 'Ben')])
        self.assertNotIn('more', self.core.party.room.after(0)[-1])

    def test_no_op_rejoin_rename_and_presence_write_nothing(self):
        c = self.core
        c.join('d-ana', 'Ana'); self.step()
        c.join('d-ana', 'Ana'); self.step()
        c.rename('d-ana', 'Ana'); self.step()
        c.touch('d-ana'); self.step()
        self.clock.advance(core.LIVE_WINDOW + 1)
        c.tick()                                   # here -> away is a commit, not a line
        self.assertEqual(self.lines(), [('joined', 'Ana')])

    def test_a_round_becoming_active_and_finishing(self):
        c = self.core
        c.join('d-ana', 'Ana'); c.join('d-ben', 'Ben'); self.step()
        s = c.launch('d-ana', 'bluff', c.party.version); self.step()
        self.assertEqual(self.lines()[-1][0], 'joined')            # launching is not announced
        c.launch_accepted(s.id); self.step()
        c.game_reported_end(s.id, 'completed'); self.step()
        sys = [l for l in c.party.room.after(0) if l['kind'] == 'system']
        self.assertEqual([(l['event'], l.get('game'), l.get('outcome')) for l in sys[-2:]],
                         [('round_started', 'bluff', None), ('round_ended', 'bluff', 'completed')])

    def test_a_failed_or_cancelled_launch_is_not_announced(self):
        c = self.core
        c.join('d-ana', 'Ana'); self.step()
        s = c.launch('d-ana', 'bluff', c.party.version); self.step()
        c.launch_failed(s.id, 'nope'); self.step()
        self.assertEqual(self.lines(), [('joined', 'Ana')])

    def test_a_leave_and_join_loop_is_coalesced(self):
        c = self.core
        c.join('d-ana', 'Ana'); c.join('d-ben', 'Ben'); self.step()
        for _ in range(20):
            c.leave('d-ben'); c.reconnect('d-ben', 'Ben')
            self.clock.advance(0.1)
        system = [l for l in c.party.room.after(0) if l['kind'] == 'system']
        self.assertEqual(len(system), 2)                          # Ana's join, then one line
        self.step()
        c.rename('d-ana', 'Anna')
        self.assertEqual(c.party.room.after(0)[-1]['more'], 39)

    def test_messages_never_change_version_and_are_not_presence(self):
        c = self.core
        c.join('d-ana', 'Ana')
        m = c._member_of('d-ana')
        v, seen = c.party.version, m.last_seen
        self.clock.advance(10)
        c.party.room.send(m, 'hi', 'x1')
        self.assertEqual((c.party.version, m.last_seen), (v, seen))

    def test_the_room_ends_with_the_party(self):
        c = self.core
        c.join('d-ana', 'Ana')
        c.party.room.send(c._member_of('d-ana'), 'hi', 'x1')
        old = c.party.id
        c.leave('d-ana')
        c.tick()
        self.clock.advance(core.PARTY_IDLE + 1)
        c.tick()
        c.view(None)                               # the next visitor starts afresh
        self.assertNotEqual(c.party.id, old)
        self.assertEqual(c.party.room.after(0), [])


# ---- over HTTP, Full and Limited listeners on one Party ---------------------------------------------
_IDS = (f'c{n}' for n in range(10**9))


class Phone:
    def __init__(self, port, host, origin):
        self.port, self.host, self.origin = port, host, origin
        self.jar = {}

    def req(self, method, path, body=None, headers=None, timeout=40):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=timeout)
        h = {'Host': self.host}
        if self.jar:
            h['Cookie'] = '; '.join(f'{k}={v}' for k, v in self.jar.items())
        data = None
        if method == 'POST':
            data = json.dumps(body or {}).encode()
            h.update({'Origin': self.origin, 'Content-Type': 'application/json'})
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        r = conn.getresponse()
        raw = r.read()
        sc = r.getheader('Set-Cookie')
        if sc:
            name, value = sc.split(';')[0].split('=', 1)
            self.jar[name] = value
        conn.close()
        return r.status, (json.loads(raw) if raw else None)

    def join(self, name):
        status, view = self.req('POST', '/party/api/join', {'name': name})
        assert status == 200, view
        self.party = view['party']
        self.me = view['me']['id']
        return view

    def read(self, after=0, wait=0, party=None, **kw):
        q = f'party={party or self.party}&after={after}&wait={wait}'
        return self.req('GET', f'/party/api/messages?{q}', **kw)

    def say(self, text, cid=None, party=None, **kw):
        return self.req('POST', '/party/api/messages',
                        {'party': party or self.party, 'text': text,
                         'client_id': cid or next(_IDS)}, **kw)


class Http(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        store = identity.DeviceStore(os.path.join(self.tmp.name, 'devices.json'))
        self.svc = service.PartyService(store, BLUFF, service.NoGameLink())
        self.full_cfg = service.Config({FULL_HOST}, {FULL_ORIGIN})
        lim = service.Config({LIMITED_HOST}, {LIMITED_ORIGIN}, mode=core.LIMITED)
        self.log = io.StringIO()
        self._err = redirect_stderr(self.log)
        self._err.__enter__()
        self.servers = [service.make_server(self.svc, self.full_cfg, port=0),
                        service.make_server(self.svc, lim, port=0)]
        for s in self.servers:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        self.full_port = self.servers[0].server_address[1]
        self.limited_port = self.servers[1].server_address[1]

    def tearDown(self):
        for s in self.servers:
            s.shutdown()
            s.server_close()
        self._err.__exit__(None, None, None)
        self.tmp.cleanup()

    def full(self):
        return Phone(self.full_port, FULL_HOST, FULL_ORIGIN)

    def limited(self):
        return Phone(self.limited_port, LIMITED_HOST, LIMITED_ORIGIN)

    def test_sender_comes_only_from_the_credential(self):
        ana, ben = self.full(), self.full()
        ana.join('Ana'); ben.join('Ben')
        status, out = ben.req('POST', '/party/api/messages',
                              {'party': ben.party, 'text': 'I am Ana', 'client_id': 'x1',
                               'from': ana.me, 'name': 'Ana', 'kind': 'system', 'seq': 999,
                               'scope': 'team', 'event': 'host', 'avatar': 'gaze-02'})
        self.assertEqual(status, 200)
        line = out['message']
        self.assertEqual((line['from'], line['name'], line['kind'], line['scope']),
                         (ben.me, 'Ben', 'member', 'party'))
        self.assertNotIn('event', line)
        self.assertNotEqual(line['seq'], 999)

    def test_two_phones_see_one_ordered_room(self):
        ana, ben = self.full(), self.full()
        ana.join('Ana'); ben.join('Ben')
        ana.say('one'); ben.say('two'); ana.say('three')
        for p in (ana, ben):
            _, out = p.read()
            texts = [l['text'] for l in out['messages'] if l['kind'] == 'member']
            self.assertEqual(texts, ['one', 'two', 'three'])
            seqs = [l['seq'] for l in out['messages']]
            self.assertEqual(seqs, sorted(seqs))
            self.assertEqual(out['last'], seqs[-1])

    def test_full_and_limited_phones_share_one_room(self):
        ana, lim = self.full(), self.limited()
        ana.join('Ana'); lim.join('Lee')
        self.assertEqual(ana.party, lim.party)
        lim.say('over http')
        ana.say('over https')
        for p in (ana, lim):
            _, out = p.read()
            self.assertEqual([l['text'] for l in out['messages'] if l['kind'] == 'member'],
                             ['over http', 'over https'])

    def test_no_anonymous_read_and_no_send_without_membership(self):
        stranger = self.full()
        ana = self.full()
        ana.join('Ana')
        status, out = stranger.read(party=ana.party)
        self.assertEqual((status, out['error']), (403, 'not_member'))
        status, out = stranger.say('hi', party=ana.party)
        self.assertEqual((status, out['error']), (403, 'not_member'))

    def test_a_member_who_left_cannot_read_or_send(self):
        ana, ben = self.full(), self.full()
        ana.join('Ana'); ben.join('Ben')
        ben.req('POST', '/party/api/leave', {})
        self.assertEqual(ben.read()[0], 403)
        self.assertEqual(ben.say('still here?')[0], 403)

    def test_a_send_naming_another_party_is_refused_and_stores_nothing(self):
        ana = self.full()
        ana.join('Ana')
        status, out = ana.say('typed for last night', party='party-' + '0' * 32)
        self.assertEqual((status, out['error']), (400, 'bad_party'))
        _, out = ana.read()
        self.assertFalse([l for l in out['messages'] if l['kind'] == 'member'])

    def test_a_read_naming_another_party_reads_the_current_room_from_the_start(self):
        ana = self.full()
        ana.join('Ana')
        ana.say('hello')
        status, out = ana.read(after=50, party='party-old')
        self.assertEqual(status, 200)
        self.assertEqual(out['party'], ana.party)
        self.assertIn('hello', [l.get('text') for l in out['messages']])

    def test_cursor_values(self):
        ana = self.full()
        ana.join('Ana')
        ana.say('a')
        _, high = ana.read(after=10**9)
        _, neg = ana.read(after=-5)
        _, zero = ana.read(after=0)
        seqs = lambda out: [l['seq'] for l in out['messages']]
        self.assertEqual(seqs(high), seqs(zero))
        self.assertEqual(seqs(neg), seqs(zero))
        for bad in ('1.5', 'x', '-', '--5', '-+5', '+5', '%EF%BC%91', '99999999999999999999'):
            status, out = ana.req('GET', f'/party/api/messages?party={ana.party}&after={bad}')
            self.assertEqual((status, out['error']), (400, 'bad_query'), bad)
        for bad in ('nan', 'inf', 'soon'):
            status, out = ana.req('GET', f'/party/api/messages?party={ana.party}&wait={bad}')
            self.assertEqual((status, out['error']), (400, 'bad_query'), bad)
        status, out = ana.req('GET', '/party/api/messages?after=0')
        self.assertEqual((status, out['error']), (400, 'bad_party'))

    def test_refusal_codes(self):
        ana = self.full()
        ana.join('Ana')
        self.assertEqual(ana.say('   ')[1]['error'], 'empty')
        self.assertEqual(ana.say('x' * 401)[1]['error'], 'too_long')
        self.assertEqual(ana.say('hi', cid='bad id')[1]['error'], 'bad_client_id')
        status, out = ana.req('POST', '/party/api/messages', {'party': 5, 'text': 'x', 'client_id': 'a'})
        self.assertEqual((status, out['error']), (400, 'bad_party'))
        for _ in range(6):
            self.assertEqual(ana.say('flood')[0], 200)
        status, out = ana.say('flood')
        self.assertEqual((status, out['error']), (429, 'too_fast'))
        self.assertGreater(out['retry_ms'], 0)

    def test_the_rate_survives_leaving_and_rejoining(self):
        ana = self.full()
        ana.join('Ana')
        for _ in range(6):
            ana.say('x')
        ana.req('POST', '/party/api/leave', {})
        ana.req('POST', '/party/api/reconnect', {'name': 'Ana'})
        self.assertEqual(ana.say('x')[0], 429)

    def test_a_retry_after_a_lost_answer_never_doubles_a_line(self):
        ana, ben = self.full(), self.full()
        ana.join('Ana'); ben.join('Ben')
        a = ana.say('only once', cid='lost-answer')[1]['message']
        b = ana.say('only once', cid='lost-answer')[1]['message']
        self.assertEqual(a['seq'], b['seq'])
        _, out = ben.read()
        self.assertEqual([l['text'] for l in out['messages'] if l['kind'] == 'member'], ['only once'])

    def test_the_send_guards_of_every_party_post(self):
        ana = self.full()
        ana.join('Ana')
        body = {'party': ana.party, 'text': 'x', 'client_id': 'g1'}
        self.assertEqual(ana.req('POST', '/party/api/messages', body,
                                 headers={'Origin': 'https://evil.test'})[1]['error'], 'bad_origin')
        self.assertEqual(ana.req('POST', '/party/api/messages', body,
                                 headers={'Sec-Fetch-Site': 'cross-site'})[1]['error'], 'cross_origin')
        self.assertEqual(ana.req('POST', '/party/api/messages', body,
                                 headers={'Content-Type': 'text/plain'})[1]['error'], 'json_only')
        self.assertEqual(ana.req('POST', '/party/api/messages', body,
                                 headers={'Host': 'evil.test'})[0], 421)
        self.assertEqual(ana.req('GET', f'/party/api/messages?party={ana.party}',
                                 headers={'Sec-Fetch-Site': 'same-site'})[0], 403)

    def test_a_held_poll_answers_when_a_line_arrives(self):
        ana, ben = self.full(), self.full()
        ana.join('Ana'); ben.join('Ben')
        _, now = ben.read()
        got = {}

        def wait():
            started = time.monotonic()
            got['out'] = ben.read(after=now['last'], wait=10)[1]
            got['took'] = time.monotonic() - started
        t = threading.Thread(target=wait)
        t.start()
        time.sleep(0.3)
        ana.say('wake up')
        t.join(5)
        self.assertEqual([l['text'] for l in got['out']['messages']], ['wake up'])
        self.assertLess(got['took'], 3)

    def test_a_message_does_not_wake_a_state_poll_or_change_version(self):
        ana, ben = self.full(), self.full()
        ana.join('Ana'); ben.join('Ben')
        _, view = ben.req('GET', '/party/api/state')
        got = {}

        def wait():
            started = time.monotonic()
            got['view'] = ben.req('GET', f"/party/api/state?since={view['version']}&wait=1.5")[1]
            got['took'] = time.monotonic() - started
        t = threading.Thread(target=wait)
        t.start()
        time.sleep(0.2)
        ana.say('quiet')
        t.join(5)
        self.assertGreater(got['took'], 1.2)
        self.assertEqual(got['view']['version'], view['version'])

    def test_a_slow_message_reader_does_not_hold_the_party(self):
        ana, ben = self.full(), self.full()
        ana.join('Ana'); ben.join('Ben')
        last = ben.read()[1]['last']
        threads = [threading.Thread(target=ben.read, kwargs={'after': last, 'wait': 3}) for _ in range(3)]
        for t in threads:
            t.start()
        time.sleep(0.2)
        started = time.monotonic()
        self.assertEqual(ana.req('GET', '/party/api/state')[0], 200)
        self.assertEqual(ana.req('POST', '/party/api/rename', {'name': 'Anna'})[0], 200)
        self.assertLess(time.monotonic() - started, 1)
        for t in threads:
            t.join(5)

    def test_one_held_poll_per_member(self):
        ana = self.full()
        ana.join('Ana')
        last = ana.read()[1]['last']
        first = {}

        def hold():
            started = time.monotonic()
            first['out'] = ana.read(after=last, wait=10)[1]
            first['took'] = time.monotonic() - started
        t = threading.Thread(target=hold)
        t.start()
        time.sleep(0.3)
        second = {}
        t2 = threading.Thread(target=lambda: second.update(out=ana.read(after=last, wait=1)[1]))
        t2.start()
        t.join(5)
        t2.join(5)
        self.assertLess(first['took'], 3)                     # released by the newer poll
        self.assertEqual(first['out']['retry_ms'], service.MSG_BUSY_RETRY_MS)
        self.assertEqual(self.svc.msg_waiters, 0)

    def test_the_cap_answers_at_once_with_retry_ms(self):
        old = service.MAX_MSG_WAITERS
        service.MAX_MSG_WAITERS = 1
        try:
            ana, ben = self.full(), self.full()
            ana.join('Ana'); ben.join('Ben')
            t = threading.Thread(target=ana.read, kwargs={'after': ana.read()[1]['last'], 'wait': 2})
            t.start()
            time.sleep(0.3)
            started = time.monotonic()
            _, out = ben.read(after=ben.read()[1]['last'], wait=10)
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(out['retry_ms'], service.MSG_BUSY_RETRY_MS)
            t.join(5)
        finally:
            service.MAX_MSG_WAITERS = old

    def test_an_immediate_empty_answer_says_when_to_ask_again(self):
        ana = self.full()
        ana.join('Ana')
        _, out = ana.read(after=ana.read()[1]['last'], wait=0)
        self.assertEqual(out['messages'], [])
        self.assertEqual(out['retry_ms'], service.MSG_RETRY_MS)

    def test_a_held_poll_is_released_on_leave(self):
        ana, ben = self.full(), self.full()
        ana.join('Ana'); ben.join('Ben')
        last = ben.read()[1]['last']
        got = {}

        def hold():
            started = time.monotonic()
            got['status'] = ben.read(after=last, wait=10)[0]
            got['took'] = time.monotonic() - started
        t = threading.Thread(target=hold)
        t.start()
        time.sleep(0.3)
        # the leave is seen by the held poll even when its system line is metered away
        with self.svc.lock:
            self.svc.core.party.room._last_system = self.svc.core.clock()
        ben2 = Phone(self.full_port, FULL_HOST, FULL_ORIGIN)
        ben2.jar = dict(ben.jar)
        ben2.req('POST', '/party/api/leave', {})
        t.join(5)
        self.assertLess(got['took'], 3)
        self.assertEqual(got['status'], 403)

    def test_message_text_never_reaches_the_log_or_the_state_view(self):
        ana = self.full()
        ana.join('Ana')
        ana.say('secret plans for later')
        _, view = ana.req('GET', '/party/api/state')
        self.assertNotIn('secret plans', json.dumps(view))
        self.assertNotIn('secret plans', self.log.getvalue())


if __name__ == '__main__':
    unittest.main()
