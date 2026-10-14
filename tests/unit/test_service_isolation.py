"""One service failing does not stop the others, and repeated failure stays bounded (AVR-33).

The appliance's systemd units, read as text: no unit makes its start or its life depend on another
service (only a native game instance requires its own socket), every long-running service restarts
only on failure and never with systemd's start limit switched off. What systemd then does is
Tier 2 on a Linux runner and Tier 3 on the Pi; this pins the files those runs depend on."""
import unittest

from avrana import REPO_ROOT
from test_native_game_units import unit

SERVICES = {
    'avrana-party-core.service': REPO_ROOT / 'deploy' / 'party-core' / 'avrana-party-core.service',
    'avrana-game@.service': REPO_ROOT / 'deploy' / 'games' / 'avrana-game@.service',
    'avranaparty-arcade.service': REPO_ROOT / 'arcade' / 'avranaparty-arcade.service',
}
SOCKETS = {
    'avrana-party-core.socket': REPO_ROOT / 'deploy' / 'party-core' / 'avrana-party-core.socket',
    'avrana-game@.socket': REPO_ROOT / 'deploy' / 'games' / 'avrana-game@.socket',
}
HARD = ('Requires', 'Requisite', 'BindsTo', 'PartOf', 'Upholds')
# The only hard dependency allowed: a native game instance on its own socket (ADR 0016 section 5).
ALLOWED = {'avrana-game@.service': {'Requires': ['avrana-game@%i.socket']}}


def words(values):
    return [w for v in values for w in v.split()]


class NoServiceStrandsAnother(unittest.TestCase):
    def test_the_only_hard_dependency_is_a_game_on_its_own_socket(self):
        for name, path in {**SERVICES, **SOCKETS}.items():
            head = unit(path).get('Unit', {})
            for key in HARD:
                with self.subTest(unit=name, key=key):
                    self.assertEqual(words(head.get(key, [])), ALLOWED.get(name, {}).get(key, []))

    def test_party_core_only_wants_its_socket(self):
        head = unit(SERVICES['avrana-party-core.service'])['Unit']
        self.assertEqual(words(head['Wants']), ['avrana-party-core.socket'])
        self.assertNotIn('avranaparty-games', ' '.join(words(head.get('After', []))))

    def test_no_unit_stops_or_restarts_another_on_failure(self):
        for name, path in {**SERVICES, **SOCKETS}.items():
            u = unit(path)
            for key in ('OnFailure', 'OnSuccess', 'PropagatesStopTo', 'PropagatesReloadTo', 'StopPropagatedFrom'):
                with self.subTest(unit=name, key=key):
                    self.assertNotIn(key, u.get('Unit', {}))

    def test_a_game_socket_belongs_to_one_game(self):
        socket = unit(SOCKETS['avrana-game@.socket'])
        self.assertEqual(socket['Socket']['ListenStream'], ['/run/avrana-games/%i.sock'])
        self.assertNotIn('Service', socket['Socket'])        # activates its own instance only


class RepeatedFailureIsBounded(unittest.TestCase):
    def test_every_service_restarts_on_failure_only_with_the_start_limit_left_on(self):
        for name, path in SERVICES.items():
            u = unit(path)
            with self.subTest(unit=name):
                self.assertEqual(u['Service']['Restart'], ['on-failure'])     # a clean stop is not fought
                for key in ('StartLimitIntervalSec', 'StartLimitBurst'):
                    for value in u.get('Unit', {}).get(key, []) + u['Service'].get(key, []):
                        self.assertNotIn(value, ('0', 'infinity'), f'{key}={value} switches the limit off')
                self.assertNotIn('StartLimitAction', u.get('Unit', {}))    # never reboots the appliance

    def test_party_core_and_the_arcade_wait_between_restarts(self):
        """RestartSec=3 bounds a crash loop to one start per 3 s. It also means systemd's default
        start limit (5 starts in 10 s) is never reached, so a loop shows as `activating`, not
        `failed`: avrana.ops.status reports it from NRestarts (docs/runbooks/service-recovery.md)."""
        for name in ('avrana-party-core.service', 'avranaparty-arcade.service'):
            with self.subTest(unit=name):
                self.assertEqual(unit(SERVICES[name])['Service']['RestartSec'], ['3'])

    def test_a_native_game_that_keeps_failing_ends_failed(self):
        """No RestartSec: systemd's 100 ms default, so five quick failures reach the default start
        limit and the instance (and its socket) end `failed`, which status reports."""
        service = unit(SERVICES['avrana-game@.service'])['Service']
        self.assertNotIn('RestartSec', service)


if __name__ == '__main__':
    unittest.main()
