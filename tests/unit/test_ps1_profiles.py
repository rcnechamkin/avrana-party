"""Tier 1: PS1 title profiles (avrana/providers/ps1.py over ps1/titles/*.json).

The data reproduces the per-title files the hardware runs used, the loader refuses anything outside
its allowlist with a named error, and a profile cannot disagree with its Game Contract. Recovered
from the donor's ps1/tests/test_profiles.py (branch experiment/ps1-title-profiles, 4b8fa60); the
golden files under tests/fixtures/ps1/golden/ are the donor's, byte for byte. Stdlib only: no
emulator, no Pi, and no ROM, BIOS or core anywhere.
"""
import copy
import hashlib
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from avrana import REPO_ROOT
from avrana.providers import ps1

GOLDEN = REPO_ROOT / 'tests/fixtures/ps1/golden'

# The cue paths exactly as the donor's run-ps1.sh hard-coded them before profiles existed (21a16c2).
OLD_CUES = {
    'worms': 'Worms Armageddon (USA)/Worms Armageddon (USA)/Worms Armageddon (USA).cue',
    'bomberman': 'Bomberman - Party Edition (USA)/Bomberman - Party Edition (USA)/'
                 'Bomberman - Party Edition (USA).cue',
}
OLD_SLOTS = {'worms': 1, 'bomberman': 4}          # stream_ps1.GAMES before profiles

# The donor branch's ps1/tests/golden/ files, hashed as the donor commit has them. The fixtures here are
# copies of them: editing one to make a generator change pass fails this test first.
DONOR_COMMIT = '4b8fa60afecb4868be0816f4b908b752bc33296d'
DONOR_GOLDEN_SHA256 = {
    'bomberman.opt': '6ec9c89418e32735541adf562230bd2b5c85247a4ef44afee72715256b02c1b3',
    'bomberman.cfg': '7e7f20287be605c95b13af59cb6d090e31a6a240565c1b011fc989920726b129',
    'worms.opt': 'd59729cbae789e8b74f33fe778dc44d449bd384e767bc79e9e5d281ce0ba897b',
    'worms.cfg': '71be472837f10dbb16002982769f3080a44397c981cb69c3de04b89fd004de12',
}


def settings(data):
    """The lines RetroArch acts on, as bytes: comments and blank lines dropped."""
    return b''.join(line + b'\n' for line in data.split(b'\n') if line and not line.startswith(b'#'))


def cfg_keys(text):
    return dict(re.findall(r'^\s*([A-Za-z0-9_]+)\s*=\s*"([^"]*)"', text, re.M))


def link_directory(target, link):
    """Make `link` lead to the directory `target`: a symbolic link, or on Windows a junction, which
    needs no privilege. Skips the test on a host that can make neither."""
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if os.name == 'nt':
        made = subprocess.run(['cmd', '/c', 'mklink', '/J', link, target], capture_output=True)
        if made.returncode == 0:
            return
    raise unittest.SkipTest('this host can create neither a symbolic link nor a junction')


class SameBehaviourAsBefore(unittest.TestCase):
    def test_titles_and_slots(self):
        self.assertEqual(ps1.available(), sorted(OLD_SLOTS))
        self.assertEqual(ps1.stream_slots(), OLD_SLOTS)

    def test_the_golden_files_are_the_donors(self):
        self.assertEqual(sorted(p.name for p in GOLDEN.iterdir()), sorted(DONOR_GOLDEN_SHA256))
        for name, digest in DONOR_GOLDEN_SHA256.items():
            self.assertEqual(hashlib.sha256((GOLDEN / name).read_bytes()).hexdigest(), digest, name)

    def test_core_options_are_byte_identical_to_the_golden_files(self):
        expected_multitap = {'bomberman': 'pcsx_rearmed_multitap = "port 2"\n',
                             'worms': 'pcsx_rearmed_multitap = "disabled"\n'}
        for title in OLD_SLOTS:
            generated = ps1.core_options(ps1.load(title)).encode('utf-8')
            self.assertEqual(generated, (GOLDEN / f'{title}.opt').read_bytes(), title)
            self.assertIn(expected_multitap[title].encode(), generated)

    def test_retroarch_config_has_the_golden_settings_byte_for_byte(self):
        """The donor's golden .cfg files keep the hand-written comment header of the pre-profile files,
        which the donor's generator never reproduced (its own test compared the settings only). So the
        settings are compared byte for byte, and the generated header is pinned below."""
        for title, users in (('bomberman', '5'), ('worms', '1')):
            golden = (GOLDEN / f'{title}.cfg').read_bytes()
            generated = ps1.retroarch_config(ps1.load(title)).encode('utf-8')
            self.assertEqual(settings(generated), settings(golden), title)
            self.assertEqual(settings(generated), f'input_max_users = "{users}"\n'.encode())
            self.assertEqual(cfg_keys(generated.decode()), cfg_keys(golden.decode()), title)

    def test_the_generated_header_is_pinned(self):
        self.assertEqual(
            ps1.retroarch_config(ps1.load('bomberman')),
            '# Bomberman - Party Edition (USA) SLUS-01189 \u2014 generated from ps1/titles/bomberman.json; '
            'do not edit\ninput_max_users = "5"\n')
        self.assertEqual(
            ps1.retroarch_config(ps1.load('worms')),
            '# Worms Armageddon (USA) SLUS-00888 \u2014 generated from ps1/titles/worms.json; '
            'do not edit\ninput_max_users = "1"\n')

    def test_generated_text_is_lf_and_never_more_than_a_comment_and_the_user_count(self):
        for title in OLD_SLOTS:
            profile = ps1.load(title)
            for text in (ps1.core_options(profile), ps1.retroarch_config(profile)):
                self.assertNotIn('\r', text)
                self.assertTrue(text.endswith('\n'))
            lines = ps1.retroarch_config(profile).splitlines()
            self.assertEqual(len(lines), 2)
            self.assertTrue(lines[0].startswith('# '))
            self.assertRegex(lines[1], r'^input_max_users = "[1-5]"$')

    def test_the_multitap_line_sits_where_the_donor_put_it(self):
        lines = ps1.core_options(ps1.load('bomberman')).splitlines()
        self.assertEqual(lines[ps1.MULTITAP_LINE], 'pcsx_rearmed_multitap = "port 2"')
        self.assertEqual(lines[-1], 'pcsx_rearmed_memcard2 = "none"')

    def test_cue_paths_match_the_old_hard_coded_ones(self):
        with tempfile.TemporaryDirectory() as roms:
            for title, rel in OLD_CUES.items():
                self.assertEqual(str(ps1.cue_path(ps1.load(title), roms)),
                                 os.path.realpath(os.path.join(roms, *rel.split('/'))))

    def test_no_title_is_hard_coded_in_code(self):
        code = (REPO_ROOT / 'avrana/providers/ps1.py').read_text(encoding='utf-8')
        for title in ('Worms', 'Bomberman', 'SLUS-01189', 'SLUS-00888', "'worms'", "'bomberman'"):
            self.assertNotIn(title, code)
        self.assertEqual(ps1.available(), ['bomberman', 'worms'])        # the data is the only list


class Validation(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = temp.name
        self.good = json.loads((ps1.TITLES / 'bomberman.json').read_text(encoding='utf-8'))

    def put(self, title_id='bomberman', raw=None, **changes):
        """Write a profile: the good one with `changes`, or `raw` text or bytes as they are."""
        path = os.path.join(self.dir, title_id + '.json')
        if isinstance(raw, bytes):
            with open(path, 'wb') as f:
                f.write(raw)
        else:
            with open(path, 'w', encoding='utf-8', newline='') as f:
                f.write(raw if raw is not None else json.dumps(dict(self.good, **changes)))

    def refused(self, error=ps1.ProfileError, why='', title_id='bomberman'):
        """The profile is refused with exactly this named error (not merely a subclass of it)."""
        with self.assertRaises(error) as caught:
            ps1.load(title_id, self.dir)
        self.assertIs(type(caught.exception), error)
        self.assertIn(why, str(caught.exception))
        self.assertIsInstance(caught.exception, ValueError)

    def test_good_profile_loads(self):
        self.put()
        self.assertEqual(ps1.load('bomberman', self.dir), self.good)
        self.assertEqual(ps1.load('bomberman', self.dir)['stream_slots'], 4)

    def test_the_committed_profiles_load_and_say_what_the_donor_said(self):
        bomberman, worms = ps1.load('bomberman'), ps1.load('worms')
        self.assertEqual((bomberman['serial'], bomberman['retroarch_users'], bomberman['stream_slots'],
                          bomberman['multitap']), ('SLUS-01189', 5, 4, 'port 2'))
        self.assertEqual((worms['serial'], worms['retroarch_users'], worms['stream_slots'],
                          worms['multitap']), ('SLUS-00888', 1, 1, 'disabled'))

    def test_raw_retroarch_keys_are_refused(self):
        for key in ('video_filter', 'network_cmd_enable', 'input_player2_up', 'savefile_directory',
                    'audio_dsp_plugin', 'core_options_path'):
            with self.subTest(key=key):
                self.put(**{key: 'x'})
                self.refused(ps1.UnknownKeysError, 'unknown keys')

    def test_content_paths_that_are_absolute_or_climb_are_refused(self):
        for cue in ('../../etc/passwd.cue', 'a/../../b.cue', '..\\x.cue', '/srv/x.cue', '\\\\host\\share\\x.cue',
                    'C:/x.cue', 'c:x.cue', 'game.bin', 'x.cue/', '', 7, None, 'a\x00b.cue', 'a\nb.cue',
                    'x' * 600 + '.cue'):
            with self.subTest(cue=cue):
                self.put(cue=cue)
                self.refused(ps1.ContentPathError, 'relative path')
        for cue in ('a/b.cue', 'A B (USA)/A B (USA)/A B (USA).cue', 'x.cue', 'a..b/c.cue'):
            with self.subTest(cue=cue):
                self.put(cue=cue)
                self.assertEqual(ps1.load('bomberman', self.dir)['cue'], cue)

    def test_more_seats_than_retroarch_users_is_refused(self):
        self.put(retroarch_users=2, stream_slots=3)
        self.refused(ps1.SlotsExceedUsersError, 'exceeds')
        self.put(retroarch_users=4, stream_slots=4)         # equal is fine
        self.assertEqual(ps1.load('bomberman', self.dir)['stream_slots'], 4)

    def test_multitap_only_takes_the_two_values_the_hardware_verified(self):
        for value in ('port 1', 'port 3', 'Disabled', '', None, 2, ['port 2'], True):
            with self.subTest(multitap=value):
                self.put(multitap=value)
                self.refused(ps1.MultitapError, 'multitap')
        for value in ('disabled', 'port 2'):
            self.put(multitap=value)
            self.assertEqual(ps1.load('bomberman', self.dir)['multitap'], value)

    def test_other_values_outside_the_allowlist(self):
        cases = [
            (dict(retroarch_users=6), 'retroarch_users'),
            (dict(retroarch_users=0), 'retroarch_users'),
            (dict(retroarch_users=True), 'retroarch_users'),
            (dict(stream_slots=5), 'stream_slots'),
            (dict(stream_slots=0), 'stream_slots'),
            (dict(stream_slots=True), 'stream_slots'),
            (dict(stream_slots=2.0), 'stream_slots'),
            (dict(stream_slots='4'), 'stream_slots'),
            (dict(version=2), 'version'),
            (dict(version=True), 'version'),
            (dict(version=1.0), 'version'),
            (dict(id='worms'), 'does not match'),
            (dict(id='Bomberman'), 'bad id'),
            (dict(serial='slus-01189'), 'serial'),
            (dict(serial='SLUS-1189'), 'serial'),
            (dict(serial='SLUS-01189\n'), 'serial'),
            (dict(serial=11189), 'serial'),
            (dict(title=''), 'title'),
            (dict(title='x' * 41), 'title'),
            (dict(name=''), 'name'),
            (dict(name='x' * 81), 'name'),
            (dict(name=None), 'name'),
            (dict(notes=3), 'notes'),
        ]
        for change, why in cases:
            with self.subTest(change=change):
                self.put(**change)
                self.refused(why=why)

    def test_a_text_field_cannot_carry_a_second_config_line(self):
        """name and serial reach the generated file's header comment: a newline there would add a
        setting of the profile author's choosing (network_cmd_enable, say)."""
        for field in ('name', 'title', 'notes'):
            for bad in ('x\nnetwork_cmd_enable = "true"', 'x\rnetwork_cmd_enable = "true"', 'x\u2028y', 'x\x00y',
                        'x\x85y', 'x\u202ey', 'tab\there'):
                with self.subTest(field=field, bad=bad):
                    self.put(**{field: bad})
                    self.refused(why=field)

    def test_the_generators_validate_their_input_too(self):
        evil = dict(self.good, name='x\nnetwork_cmd_enable = "true"')
        for generate in (ps1.core_options, ps1.retroarch_config):
            with self.assertRaises(ps1.ProfileError):
                generate(evil)
            with self.assertRaises(ps1.MultitapError):
                generate(dict(self.good, multitap='port 1'))
            with self.assertRaises(ps1.ProfileError):
                generate({'multitap': 'port 2'})
            with self.assertRaises(ps1.ProfileError):
                generate(None)
        with self.assertRaises(ps1.ContentPathError):
            ps1.cue_path(dict(self.good, cue='../x.cue'), self.dir)

    def test_a_cue_cannot_leave_the_content_root_through_a_link(self):
        """validate() refuses '..' and absolute paths; a link inside the root is the one way left out."""
        with tempfile.TemporaryDirectory() as outside, tempfile.TemporaryDirectory() as root:
            link_directory(outside, os.path.join(root, 'disc'))
            with self.assertRaisesRegex(ps1.ContentPathError, 'escapes the content root'):
                ps1.cue_path(dict(self.good, cue='disc/game.cue'), root)
            os.mkdir(os.path.join(root, 'real'))
            link_directory(os.path.join(root, 'real'), os.path.join(root, 'alias'))     # inside: allowed
            self.assertEqual(ps1.cue_path(dict(self.good, cue='alias/game.cue'), root),
                             (Path(root).resolve() / 'real' / 'game.cue'))

    def test_duplicate_keys_are_refused_by_name(self):
        self.put(raw='{"version": 1, "version": 1}')
        self.refused(ps1.DuplicateKeyError, 'duplicate key')
        self.put(raw=json.dumps(self.good)[:-1] + ', "multitap": "disabled"}')   # the second one would have won
        self.refused(ps1.DuplicateKeyError, 'duplicate key')

    def test_structure_errors(self):
        self.put(raw='[1, 2]')
        self.refused(why='must be an object')
        self.put(raw='{not json')
        self.refused(why='invalid JSON')
        self.put(raw='')
        self.refused(why='invalid JSON')
        self.put(raw='{"version": NaN}')
        self.refused(why='invalid JSON')
        self.put(raw=b'\xff\xfe{"version": 1}')
        self.refused(why='not UTF-8')
        self.put(raw=json.dumps(dict(self.good, notes='x' * (ps1.MAX_PROFILE_BYTES + 1))))
        self.refused(why='at most')
        data = dict(self.good)
        del data['cue']
        self.put(raw=json.dumps(data))
        self.refused(why='missing keys')
        self.refused(why='unknown title', title_id='absent')
        for bad_id in ('../x', 'Worms', '', 'a' * 40, 'a\n', 'x.json', None, 7):
            with self.subTest(bad_id=bad_id), self.assertRaisesRegex(ps1.ProfileError, 'bad title id'):
                ps1.load(bad_id, self.dir)

    def test_one_named_error_per_refusal(self):
        names = [ps1.DuplicateKeyError, ps1.UnknownKeysError, ps1.ContentPathError, ps1.SlotsExceedUsersError,
                 ps1.MultitapError, ps1.ContractMismatchError]
        self.assertEqual(len({cls.__name__ for cls in names}), len(names))
        for cls in names:
            self.assertTrue(issubclass(cls, ps1.ProfileError))
            self.assertTrue(cls.__doc__)
        self.assertEqual(ps1.MAX_SLOTS, len(ps1.BANKS))
        self.assertEqual((ps1.MAX_USERS, ps1.MAX_SLOTS), (5, 4))

    def test_a_broken_profile_makes_the_whole_list_fail_loudly(self):
        self.put()
        self.put('worms', raw='{"version": 1}')
        with self.assertRaises(ps1.ProfileError):
            ps1.available(self.dir)
        with self.assertRaises(ps1.ProfileError):
            ps1.stream_slots(self.dir)


class ContractCrossCheck(unittest.TestCase):
    """The Game Contract owns serial, stream slots and multitap; a profile that disagrees is an error."""

    def mismatch(self, title, profile=None, contract=None, error=ps1.ContractMismatchError):
        p = dict(ps1.load(title), **(profile or {}))
        c = copy.deepcopy(ps1.load_contract(title))
        if contract:
            contract(c)
        with self.assertRaises(error) as caught:
            ps1.cross_check(p, c)
        self.assertIs(type(caught.exception), error)
        return str(caught.exception)

    def test_both_committed_titles_agree_with_their_contracts(self):
        for title in OLD_SLOTS:
            with self.subTest(title=title):
                self.assertIsNone(ps1.cross_check(ps1.load(title), ps1.load_contract(title)))
                self.assertEqual(ps1.load_checked(title), ps1.load(title))

    def test_the_contract_files_are_read_by_profile_id(self):
        self.assertEqual(ps1.load_contract('bomberman')['id'], 'ps1-bomberman')
        self.assertEqual(ps1.load_contract('worms')['id'], 'ps1-worms')
        meta = ps1.load_contract('bomberman')['extensions']['net.avrana.ps1']
        self.assertEqual((meta['serial'], meta['stream_slots'], meta['multitap_port']), ('SLUS-01189', 4, 2))
        meta = ps1.load_contract('worms')['extensions']['net.avrana.ps1']
        self.assertEqual((meta['serial'], meta['stream_slots'], meta['multitap']), ('SLUS-00888', 1, 'disabled'))

    def test_a_different_serial_is_an_error_from_either_side(self):
        self.assertIn('serial', self.mismatch('bomberman', profile={'serial': 'SLUS-01188'}))
        self.assertIn('serial', self.mismatch('worms', contract=lambda c: c['extensions']['net.avrana.ps1']
                                              .update(serial='SLUS-00889')))
        profile = ps1.load('worms')
        del profile['serial']
        with self.assertRaisesRegex(ps1.ContractMismatchError, 'serial'):
            ps1.cross_check(profile, ps1.load_contract('worms'))

    def test_different_stream_slots_are_an_error_from_either_side(self):
        self.assertIn('stream_slots', self.mismatch('bomberman', profile={'stream_slots': 3}))
        self.assertIn('stream_slots', self.mismatch('worms', profile={'stream_slots': 2, 'retroarch_users': 2}))

        def three_seats(c):
            c['extensions']['net.avrana.ps1']['stream_slots'] = 3
            c['input']['slots'] = 3
        self.assertIn('stream_slots', self.mismatch('bomberman', contract=three_seats))

    def test_a_different_multitap_is_an_error_from_either_side(self):
        self.assertIn('multitap', self.mismatch('bomberman', profile={'multitap': 'disabled'}))
        self.assertIn('multitap', self.mismatch('worms', profile={'multitap': 'port 2'}))

        def no_multitap(c):
            del c['extensions']['net.avrana.ps1']['multitap_port']
            c['extensions']['net.avrana.ps1']['multitap'] = 'disabled'
        # a controller_slots contract must have its port: the catalog's own validator refuses this one
        self.assertIn('not a valid PS1 contract', self.mismatch('bomberman', contract=no_multitap))

        def both(c):
            c['extensions']['net.avrana.ps1']['multitap'] = 'disabled'
        self.assertIn('multitap', self.mismatch('bomberman', contract=both))      # port 2 and disabled at once

    def test_every_difference_is_named_in_one_message(self):
        message = self.mismatch('bomberman', profile={'serial': 'SLUS-00000', 'stream_slots': 2, 'multitap': 'disabled'})
        for field in ('serial', 'stream_slots', 'multitap', 'ps1-bomberman'):
            self.assertIn(field, message)

    def test_a_profile_for_another_title_is_an_error(self):
        message = self.mismatch('bomberman', profile={'id': 'worms'})
        self.assertIn('title', message)

    def test_a_contract_that_is_not_a_ps1_contract_is_an_error(self):
        for mutate in (lambda c: c.pop('extensions'), lambda c: c.pop('input'), lambda c: c.update(runtime={}),
                       lambda c: c['extensions']['net.avrana.ps1'].update(serial='invented'),
                       lambda c: c['extensions']['net.avrana.ps1'].update(multitap_port=1)):
            with self.subTest(mutate=mutate):
                self.assertIn('not a valid PS1 contract', self.mismatch('bomberman', contract=mutate))
        with self.assertRaisesRegex(ps1.ContractMismatchError, 'not a valid PS1 contract'):
            ps1.cross_check(ps1.load('bomberman'), {})

    def test_a_missing_or_unreadable_contract_is_an_error(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaisesRegex(ps1.ContractMismatchError, 'no Game Contract'):
                ps1.load_contract('bomberman', empty)
            with self.assertRaises(ps1.ContractMismatchError):
                ps1.load_checked('bomberman', contracts_dir=empty)
            with open(os.path.join(empty, 'ps1-bomberman.json'), 'w', encoding='utf-8') as f:
                f.write('{"id": 1, "id": 2}')
            with self.assertRaisesRegex(ps1.ContractMismatchError, 'cannot be read'):
                ps1.load_contract('bomberman', empty)
        with self.assertRaisesRegex(ps1.ProfileError, 'bad title id'):
            ps1.load_contract('../worms')

    def test_load_checked_refuses_a_profile_directory_that_disagrees(self):
        with tempfile.TemporaryDirectory() as titles:
            data = json.loads((ps1.TITLES / 'bomberman.json').read_text(encoding='utf-8'))
            data['stream_slots'] = 3
            with open(os.path.join(titles, 'bomberman.json'), 'w', encoding='utf-8') as f:
                json.dump(data, f)
            self.assertEqual(ps1.load('bomberman', titles)['stream_slots'], 3)       # a valid profile on its own
            with self.assertRaisesRegex(ps1.ContractMismatchError, 'stream_slots'):
                ps1.load_checked('bomberman', titles)


class CommittedData(unittest.TestCase):
    """Facts about the committed files that the generators and the launcher will rely on."""

    def read_cfg(self, name):
        return cfg_keys((ps1.PS1_DIR / name).read_text(encoding='utf-8'))

    def test_the_base_config_leaves_no_remote_control_surface(self):
        base = self.read_cfg('retroarch.cfg')
        for key in ('network_cmd_enable', 'stdin_cmd_enable', 'netplay_nat_traversal', 'config_save_on_exit',
                    'auto_overrides_enable', 'auto_remaps_enable', 'savestate_auto_save'):
            self.assertEqual(base.get(key), 'false', key)
        self.assertEqual(base.get('input_autodetect_enable'), 'false')

    def test_the_headless_mode_keeps_pads_out_and_hotkeys_gated(self):
        mode = self.read_cfg('mode-xvfb.cfg')
        self.assertEqual((mode['input_driver'], mode['input_joypad_driver']), ('x', 'null'))
        for user in range(1, ps1.MAX_USERS + 1):
            self.assertEqual(mode[f'input_player{user}_joypad_index'], '15', user)
        self.assertEqual(mode['input_enable_hotkey'], 'scroll_lock')
        self.assertEqual(mode['input_menu_toggle'], 'nul')
        self.assertEqual(mode['input_exit_emulator'], 'nul')

    def test_no_owner_content_is_committed(self):
        """ROMs, BIOS images, cores, saves and states never enter the repository (AGENTS.md)."""
        allowed = {'.json', '.cfg', '.opt', '.md'}
        for folder in (ps1.PS1_DIR, REPO_ROOT / 'tests/fixtures/ps1'):
            for path in folder.rglob('*'):
                if path.is_file():
                    with self.subTest(path=path.relative_to(REPO_ROOT).as_posix()):
                        self.assertIn(path.suffix, allowed)
                        self.assertLess(path.stat().st_size, 64 * 1024)
                        self.assertNotIn(b'\x00', path.read_bytes())

    def test_the_profiles_come_from_the_donor_commit_the_contracts_name(self):
        for title in OLD_SLOTS:
            source = ps1.load_contract(title)['extensions']['net.avrana.ps1']['metadataSource']['titleProfiles']
            self.assertEqual(source, {'ref': 'experiment/ps1-title-profiles', 'commit': DONOR_COMMIT})


if __name__ == '__main__':
    unittest.main()
