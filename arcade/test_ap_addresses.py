"""ap_addresses() finds the party AP by its address, not a hard-coded interface name.
stream.py needs GStreamer to import, so this test runs only that function (extracted with ast).
    python3 arcade/test_ap_addresses.py"""
import ast
import os
import types
import unittest

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'stream.py')


def load(ip_output):
    tree = ast.parse(open(SRC, encoding='utf-8').read())
    keep = [n for n in tree.body if (isinstance(n, ast.FunctionDef) and n.name == 'ap_addresses')
            or (isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == 'PARTY_ADDRESS' for t in n.targets))]
    fake = types.SimpleNamespace(run=lambda *a, **k: types.SimpleNamespace(stdout=ip_output))
    ns = {'subprocess': fake}
    exec(compile(ast.Module(body=keep, type_ignores=[]), SRC, 'exec'), ns)
    return ns['ap_addresses']


IP_NOW = """1: lo    inet 127.0.0.1/8 scope host lo\       valid_lft forever preferred_lft forever
2: eth0    inet 10.0.0.142/24 brd 10.0.0.255 scope global dynamic noprefixroute eth0\       valid_lft 86000sec
3: wlan0    inet 10.42.0.1/24 brd 10.42.0.255 scope global noprefixroute wlan0\       valid_lft forever
3: wlan0    inet6 fe80::9afe:54ff:fe34:e550/64 scope link noprefixroute \       valid_lft forever
"""
IP_OLD = """2: wlan0    inet 10.0.0.143/24 brd 10.0.0.255 scope global wlan0\       valid_lft 86000sec
4: wlan1    inet 10.42.0.1/24 brd 10.42.0.255 scope global wlan1\       valid_lft forever
"""


class ApAddresses(unittest.TestCase):
    def test_internal_radio_as_ap(self):
        self.assertEqual(load(IP_NOW)(), {'10.42.0.1', 'fe80::9afe:54ff:fe34:e550'})

    def test_old_usb_adapter_as_ap(self):
        self.assertEqual(load(IP_OLD)(), {'10.42.0.1'})

    def test_no_party_ap(self):
        self.assertEqual(load('2: eth0    inet 10.0.0.142/24 scope global eth0\n')(), set())


if __name__ == '__main__':
    unittest.main(verbosity=1)
