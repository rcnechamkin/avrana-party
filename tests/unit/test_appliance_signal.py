"""The physical signal state (avrana.ops.appliance_signal): seven states in priority order (AVR-87)."""
import itertools
import unittest

from avrana.ops import appliance_signal as sig


def status(state='ok', members=0, core_ok=True, reasons=()):
    return {'schema': 'avrana.status/v0', 'party_core': {'ok': core_ok, 'members': members},
            'summary': {'state': state, 'reasons': list(reasons), 'notes': []}}


# One way to make each state true; derive() must pick the highest-priority one present.
CONDITIONS = {
    'identify': dict(identify_until=1000.0),
    'recovery': dict(recovery_image=True),
    'updating': dict(deploy={'running': True}),
    'attention': dict(status=status('degraded', reasons=['certificate expired'])),
    'party': dict(status=status(members=3)),
    'ready': dict(status=status()),
}


def run(**kw):
    args = dict(status=status(), deploy=None, identify_until=None, now=500.0, up_since=0.0, recovery_image=False)
    args.update(kw)
    return sig.derive(**args)


class Priority(unittest.TestCase):
    def test_every_pair_resolves_to_the_higher_state(self):
        order = list(CONDITIONS)
        for high, low in itertools.combinations(order, 2):
            kw = {}
            for name in (low, high):                 # the higher one applied last where both set `status`
                kw.update(CONDITIONS[name])
            if 'status' in CONDITIONS[low] and 'status' in CONDITIONS[high]:
                continue                             # two status documents cannot both be true at once
            self.assertEqual(run(**kw)[0], high, (high, low))

    def test_each_state_alone(self):
        for name, kw in CONDITIONS.items():
            self.assertEqual(run(**kw)[0], name, name)

    def test_a_dead_deploy_is_recovery_not_updating(self):
        self.assertEqual(run(deploy={'running': True, 'unrecovered': True})[0], 'recovery')


class NeverFalselyReady(unittest.TestCase):
    def test_unknown_is_attention_never_ready(self):
        state, reason = run(status=status('unknown'))
        self.assertEqual(state, 'attention')
        self.assertIn('not everything could be checked', reason)

    def test_degraded_says_its_first_reason(self):
        self.assertEqual(run(status=status('degraded', reasons=['nginx drift', 'b'])), ('attention', 'nginx drift'))

    def test_booting_then_attention_when_core_never_answers(self):
        for doc in (None, status(core_ok=False), {'schema': 'x'}):
            self.assertEqual(run(status=doc, now=10.0)[0], 'booting')
            self.assertEqual(run(status=doc, now=sig.BOOT_GRACE_S + 1)[0], 'attention')

    def test_a_weird_member_count_is_not_a_party(self):
        for members in (None, True, '3', -1, 0):
            self.assertEqual(run(status=status(members=members))[0], 'ready', members)


class IdentifyAndQuiet(unittest.TestCase):
    def test_identify_expires(self):
        self.assertEqual(run(identify_until=530.0, now=500.0)[0], 'identify')
        self.assertEqual(run(identify_until=530.0, now=530.0)[0], 'ready')

    def test_quiet_hours_never_darken_attention_recovery_or_updating(self):
        for state in sig.STATES:
            level = sig.brightness(state, quiet=True)
            if state == 'identify':
                self.assertEqual(level, 1.0)
            elif state in ('recovery', 'updating', 'attention'):
                self.assertGreater(level, 0.1)
            else:
                self.assertLessEqual(level, 0.1)
            self.assertEqual(sig.brightness(state, quiet=False), 1.0)

    def test_document(self):
        doc = sig.document('attention', 'certificate expired', '2026-10-26T12:00:00Z', quiet=True)
        self.assertEqual(doc['schema'], 'avrana.signal/v0')
        self.assertEqual(doc['level'], 0.3)
        with self.assertRaises(ValueError):
            sig.document('blinking', '', '')


if __name__ == '__main__':
    unittest.main()
