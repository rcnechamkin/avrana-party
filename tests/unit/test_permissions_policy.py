"""The appliance's Permissions-Policy for game pages (avrana.ops.permissions_policy, AVR-62 section 4)."""
import re
import unittest

from avrana.contracts import game as game_contract
from avrana.ops import permissions_policy as pp


def policy(value):
    return dict(part.split('=', 1) for part in value.split(', '))


class Header(unittest.TestCase):
    def test_nothing_granted_denies_every_feature(self):
        p = policy(pp.DENY_ALL)
        for feature in pp.FEATURES:
            self.assertEqual(p[feature], '()', feature)
        self.assertEqual(p['fullscreen'], '(self)')

    def test_a_grant_opens_only_its_features_to_the_game_itself(self):
        p = policy(pp.header(['camera', 'controllers']))
        self.assertEqual((p['camera'], p['gamepad']), ('(self)', '(self)'))
        self.assertEqual((p['microphone'], p['gyroscope']), ('()', '()'))
        self.assertNotIn('*', pp.header(['camera']))                       # never another origin

    def test_motion_sensors_opens_the_three_sensors(self):
        p = policy(pp.header(['motion_sensors']))
        self.assertEqual({p['accelerometer'], p['gyroscope'], p['magnetometer']}, {'(self)'})

    def test_never_grantable_features_stay_closed_whatever_is_asked(self):
        p = policy(pp.header(list(game_contract.PERMISSIONS) + ['geolocation', 'usb', 'payment', 'everything']))
        for feature in pp.NEVER:
            self.assertEqual(p[feature], '()', feature)

    def test_server_side_permissions_open_nothing_in_the_browser(self):
        for name in ('persistent_storage', 'party_roster', 'local_network', 'internet', 'host_devices'):
            self.assertEqual(pp.header([name]), pp.DENY_ALL, name)

    def test_every_contract_browser_permission_is_mapped(self):
        browser = {'camera', 'microphone', 'controllers'}
        self.assertTrue(browser <= set(game_contract.PERMISSIONS))
        self.assertTrue(browser <= set(pp.OPENS))

    def test_the_header_is_stable(self):
        self.assertEqual(pp.header(['controllers', 'camera']), pp.header(['camera', 'controllers']))


class NginxMap(unittest.TestCase):
    def test_default_deny_and_one_line_per_game_that_opens_something(self):
        text = pp.nginx_map({'tanks': ['controllers'], 'bestguess': ['party_roster'], 'mic': ['microphone']})
        self.assertTrue(text.startswith('map $native_game $avrana_permissions_policy {\n'))
        self.assertIn(f'    default "{pp.DENY_ALL}";', text)
        self.assertIn('    tanks "', text)
        self.assertIn('    mic "', text)
        self.assertNotIn('bestguess', text)                                 # it opens nothing: the default covers it
        self.assertEqual(text.index('mic'), min(text.index('mic'), text.index('tanks')))   # sorted

    def test_a_strange_game_id_is_refused_not_written(self):
        for bad in ('x"; add_header A b; "', 'Tanks', '../x', 'a b', '', 'tanks\n'):
            with self.assertRaises(ValueError, msg=bad):
                pp.nginx_map({bad: ['camera']})

    def test_values_hold_only_safe_characters(self):
        value = pp.header(['camera', 'microphone', 'motion_sensors', 'controllers'])
        self.assertRegex(value, r'^[a-z=(), -]+$')
        for quoted in re.findall(r'"([^"]*)"', pp.nginx_map({'g': ['camera']})):
            self.assertRegex(quoted, r'^[a-z=(), -]+$')


if __name__ == '__main__':
    unittest.main()
