"""PS1 title profiles (ps1/profiles.py): the data must reproduce the pre-profile per-title files
byte for byte, and the validator must refuse anything outside the allowlist.
Runs anywhere (stdlib; no emulator, no Pi).   python ps1/tests/test_profiles.py
"""
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

PS1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden')
sys.path.insert(0, PS1)
import profiles  # noqa: E402

# The cue paths exactly as run-ps1.sh hard-coded them before profiles existed (21a16c2).
OLD_CUES = {
    'worms': 'Worms Armageddon (USA)/Worms Armageddon (USA)/Worms Armageddon (USA).cue',
    'bomberman': 'Bomberman - Party Edition (USA)/Bomberman - Party Edition (USA)/'
                 'Bomberman - Party Edition (USA).cue',
}
OLD_SLOTS = {'worms': 1, 'bomberman': 4}          # stream_ps1.GAMES before profiles


def cfg_keys(text):
    return dict(re.findall(r'^\s*([A-Za-z0-9_]+)\s*=\s*"([^"]*)"', text, re.M))


class SameBehaviourAsBefore(unittest.TestCase):
    def test_titles_and_slots(self):
        self.assertEqual(profiles.available(), sorted(OLD_SLOTS))
        self.assertEqual(profiles.stream_slots(), OLD_SLOTS)

    def test_core_options_are_byte_identical(self):
        for t in OLD_SLOTS:
            with open(os.path.join(GOLDEN, f'{t}.opt'), 'rb') as f:
                self.assertEqual(profiles.core_options(profiles.load(t)).encode(), f.read(), t)

    def test_retroarch_override_sets_the_same_keys(self):
        for t in OLD_SLOTS:
            with open(os.path.join(GOLDEN, f'{t}.cfg'), encoding='utf-8') as f:
                old = cfg_keys(f.read())
            self.assertEqual(cfg_keys(profiles.retroarch_override(profiles.load(t))), old, t)

    def test_cue_paths_match_the_old_hard_coded_ones(self):
        with tempfile.TemporaryDirectory() as roms:
            for t, rel in OLD_CUES.items():
                self.assertEqual(profiles.cue_path(profiles.load(t), roms),
                                 os.path.realpath(os.path.join(roms, *rel.split('/'))))

    def test_write_produces_both_files_with_lf(self):
        with tempfile.TemporaryDirectory() as run:
            profiles.write(profiles.load('bomberman'), run)
            with open(os.path.join(run, 'core-options.opt'), 'rb') as f:
                opt = f.read()
            with open(os.path.join(run, 'game.cfg'), 'rb') as f:
                cfg = f.read()
            self.assertNotIn(b'\r', opt + cfg)
            self.assertIn(b'input_max_users = "5"', cfg)

    def test_cli(self):
        run = lambda *a: subprocess.run([sys.executable, os.path.join(PS1, 'profiles.py'), *a],
                                        capture_output=True, text=True)
        self.assertEqual(run('list').stdout.split(), sorted(OLD_SLOTS))
        self.assertEqual(run('slots', 'bomberman').stdout.strip(), '4')
        bad = run('cue', 'nope', '--roms', '/x')
        self.assertEqual(bad.returncode, 1)
        self.assertIn('unknown title', bad.stderr)
        self.assertEqual(run().returncode, 2)

    def test_no_title_is_hard_coded_in_code_any_more(self):
        for name in ('run-ps1.sh', 'stream_ps1.py'):
            with open(os.path.join(PS1, name), encoding='utf-8') as f:
                code = f.read()
            self.assertNotIn('Worms Armageddon', code, name)
            self.assertNotIn("'worms': 1", code, name)
        self.assertFalse(os.path.exists(os.path.join(PS1, 'games')), 'raw per-title config is gone')


class Validation(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        with open(os.path.join(PS1, 'titles', 'bomberman.json'), encoding='utf-8') as f:
            self.good = json.load(f)

    def tearDown(self):
        for f in os.listdir(self.dir):
            os.remove(os.path.join(self.dir, f))
        os.rmdir(self.dir)

    def put(self, title_id='bomberman', raw=None, **changes):
        data = dict(self.good, **changes)
        with io.open(os.path.join(self.dir, title_id + '.json'), 'w', encoding='utf-8') as f:
            f.write(raw if raw is not None else json.dumps(data))

    def refused(self, title_id='bomberman', why=''):
        with self.assertRaises(profiles.ProfileError) as e:
            profiles.load(title_id, self.dir)
        self.assertIn(why, str(e.exception))

    def test_good_profile_loads(self):
        self.put()
        self.assertEqual(profiles.load('bomberman', self.dir)['stream_slots'], 4)

    def test_raw_retroarch_keys_are_refused(self):
        for key in ('video_filter', 'network_cmd_enable', 'input_player2_up', 'savefile_directory'):
            self.put(**{key: 'x'})
            self.refused(why='unknown keys')

    def test_values_outside_the_allowlist(self):
        cases = [
            (dict(multitap='port 1'), 'multitap'),            # untested on hardware
            (dict(retroarch_users=6), 'retroarch_users'),
            (dict(stream_slots=5), 'stream_slots'),
            (dict(stream_slots=True), 'stream_slots'),
            (dict(retroarch_users=2, stream_slots=3), 'exceeds'),
            (dict(version=2), 'version'),
            (dict(id='worms'), 'does not match'),
            (dict(cue='../../etc/passwd.cue'), 'relative path'),
            (dict(cue='/srv/x.cue'), 'relative path'),
            (dict(cue='C:/x.cue'), 'relative path'),
            (dict(cue='game.bin'), 'relative path'),
        ]
        for change, why in cases:
            self.put(**change)
            self.refused(why=why)

    def test_structure_errors(self):
        self.put(raw='{"version": 1, "version": 1}')
        self.refused(why='duplicate key')
        self.put(raw='[1, 2]')
        self.refused(why='must be an object')
        self.put(raw='{not json')
        self.refused(why='invalid JSON')
        data = dict(self.good)
        del data['cue']
        self.put(raw=json.dumps(data))
        self.refused(why='missing keys')
        for bad_id in ('../x', 'Worms', '', 'a' * 40):
            with self.assertRaises(profiles.ProfileError):
                profiles.load(bad_id, self.dir)


if __name__ == '__main__':
    unittest.main(verbosity=1)
