"""Party activity (avrana.party.activity): closed lists, source authority, per-viewer delivery, cursors."""
import unittest

from avrana.party import activity, messages

ADA, BOB = {'member': 'member-ada', 'host': True}, {'member': 'member-bob'}
OWNER, TV = {'owner': True}, {'display': True}
TEMPLATES = [{'id': 'your_turn', 'text': "It's your turn", 'audience': 'member'}]


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Feed(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.feed = activity.Feed('party-1', self.clock)

    def test_the_room_events_are_party_events(self):
        for event in messages.EVENTS:
            self.assertIn(event, activity.PARTY_EVENTS)

    def test_closed_lists_and_no_free_text(self):
        with self.assertRaises(activity.Refused):
            self.feed.publish('party', 'free_text_please')
        with self.assertRaises(activity.Refused):
            self.feed.publish('party', 'joined', fields={'text': 'hello'})          # not a template field
        with self.assertRaises(activity.Refused):
            self.feed.publish('party', 'joined', fields={'name': 'x' * 81})
        with self.assertRaises(activity.Refused):
            self.feed.publish('party', 'joined', fields={'count': True})
        with self.assertRaises(activity.Refused):
            self.feed.publish('game:bluff', 'joined')                             # games use publish_game
        with self.assertRaises(activity.Refused):
            self.feed.publish('party', 'storage_low')                             # an appliance event
        with self.assertRaises(activity.Refused):
            self.feed.publish('party', 'joined', audience='everyone')

    def test_actions_are_never_stored(self):
        with self.assertRaises(activity.Refused) as ctx:
            self.feed.publish('party', 'role_needed', audience='member:member-bob', priority='action')
        self.assertIn('derived from state', str(ctx.exception))

    def test_appliance_events_reach_the_owner_only(self):
        with self.assertRaises(activity.Refused):
            self.feed.publish('appliance', 'storage_low', audience='host')
        self.feed.publish('appliance', 'storage_low', audience='owner', priority='alert', fields={'percent': 3})
        self.assertEqual(len(self.feed.after('party-1', 0, OWNER)), 1)
        for viewer in (ADA, BOB, TV):
            self.assertEqual(self.feed.after('party-1', 0, viewer), [])

    def test_per_viewer_delivery(self):
        self.feed.publish('party', 'joined', fields={'member': 'member-bob', 'name': 'Bob'})
        self.feed.publish('party', 'role_needed', audience='member:member-bob', priority='notice')
        self.feed.publish('party', 'round_ready', audience='host', priority='notice')
        ids = lambda viewer: [i['event'] for i in self.feed.after('party-1', 0, viewer)]
        self.assertEqual(ids(BOB), ['joined', 'role_needed'])
        self.assertEqual(ids(ADA), ['joined', 'round_ready'])
        self.assertEqual(ids(TV), ['joined'])                                     # a shared screen: Party-wide only
        self.assertEqual(ids({'member': 'member-cleo'}), ['joined'])

    def test_a_viewer_without_a_member_id_never_gets_a_member_item(self):
        for bad in ('member:', 'member:None'):
            with self.assertRaises(activity.Refused, msg=bad):
                self.feed.publish('party', 'role_needed', audience=bad, priority='notice')
        item = {'audience': 'member:None'}
        self.assertFalse(activity.Feed.sees(item, {'owner': True}))
        self.assertFalse(activity.Feed.sees(item, {'member': None}))

    def test_cursor_and_another_partys_cursor(self):
        self.feed.publish('party', 'joined')
        second = self.feed.publish('party', 'left')
        self.assertEqual([i['event'] for i in self.feed.after('party-1', 1, BOB)], ['left'])
        self.assertEqual(self.feed.after('party-1', second['seq'], BOB), [])
        self.assertEqual(len(self.feed.after('party-OLD', 99, BOB)), 2)           # read from the start
        self.assertEqual(len(self.feed.after('party-1', -5, BOB)), 2)

    def test_expiry_and_age(self):
        self.feed.publish('party', 'round_ready', audience='host', priority='notice', expires_in=30)
        self.clock.t += 10
        item = self.feed.after('party-1', 0, ADA)[0]
        self.assertEqual(item['age_ms'], 10000)
        self.assertNotIn('at', item)
        self.clock.t += 21
        self.assertEqual(self.feed.after('party-1', 0, ADA), [])

    def test_the_ring_is_bounded_and_says_what_it_lost(self):
        for _ in range(activity.RING + 5):
            self.feed.publish('party', 'joined')
        self.assertEqual(len(self.feed.items), activity.RING)
        self.assertEqual(self.feed.lost, 5)


class GameNotices(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.feed = activity.Feed('party-1', self.clock)

    def test_a_declared_notice_reaches_its_member_only_and_the_game_is_named(self):
        item = self.feed.publish_game('bestguess', TEMPLATES, 'your_turn', 'member-bob')
        self.assertEqual((item['source'], item['priority'], item['audience']), ('game:bestguess', 'notice', 'member:member-bob'))
        self.assertEqual(len(self.feed.after('party-1', 0, BOB)), 1)
        self.assertEqual(self.feed.after('party-1', 0, ADA), [])
        self.assertEqual(self.feed.after('party-1', 0, TV), [])
        for bad in (None, '', 7):
            with self.assertRaises(activity.Refused, msg=repr(bad)):
                self.feed.publish_game('bestguess', TEMPLATES, 'your_turn', bad)

    def test_undeclared_notices_and_platform_sources_are_refused(self):
        with self.assertRaises(activity.Refused):
            self.feed.publish_game('bestguess', TEMPLATES, 'host', 'member-bob')
        with self.assertRaises(activity.Refused):
            self.feed.publish_game('bestguess', [], 'your_turn', 'member-bob')
        many = [{'id': f't{i}'} for i in range(12)]
        with self.assertRaises(activity.Refused):
            self.feed.publish_game('bestguess', many, 't10', 'member-bob')      # only the first 8 count

    def test_a_game_cannot_flood_a_phone(self):
        self.assertIsNotNone(self.feed.publish_game('bestguess', TEMPLATES, 'your_turn', 'member-bob'))
        self.assertIsNone(self.feed.publish_game('bestguess', TEMPLATES, 'your_turn', 'member-bob'))
        self.assertIsNotNone(self.feed.publish_game('bestguess', TEMPLATES, 'your_turn', 'member-ada'))
        self.clock.t += activity.GAME_EVERY
        self.assertIsNotNone(self.feed.publish_game('bestguess', TEMPLATES, 'your_turn', 'member-bob'))

    def test_game_notices_expire(self):
        self.feed.publish_game('bestguess', TEMPLATES, 'your_turn', 'member-bob')
        self.clock.t += 31
        self.assertEqual(self.feed.after('party-1', 0, BOB), [])


if __name__ == '__main__':
    unittest.main()
