"""Party session protocol v0 (avrana.party.protocol): envelope, tickets, messages, GameSide."""
import json
import os
import struct
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


class Encoding(unittest.TestCase):
    """A malformed segment is refused as Invalid('encoding'), never a stray binascii.Error: callers
    catch only Invalid, so anything else becomes a 500."""
    BAD = ('aps0.x.y',                      # length 1 mod 4: urlsafe_b64decode raises
           'aps0.e30.abcde',                # signature 1 mod 4
           'aps0.abcde.' + 'A' * 43,        # payload 1 mod 4 (signature fails first: still refused)
           'aps0.e30.AA+A',                 # outside the URL-safe alphabet
           'aps0.e30.AA=A',                 # padding is never on the wire
           'aps0.e30.éAAA')           # non-ASCII

    def test_unseal(self):
        for bad in self.BAD[:2] + self.BAD[3:]:
            with self.subTest(bad=bad), self.assertRaises(Invalid) as e:
                P.unseal(KEY, bad, 'ticket', 'bluff', now=NOW)
            self.assertEqual(str(e.exception), 'encoding')
        with self.assertRaises(Invalid):
            P.unseal(KEY, self.BAD[2], 'ticket', 'bluff', now=NOW)

    def test_verify_ticket(self):
        for bad in self.BAD:
            with self.subTest(bad=bad), self.assertRaises(Invalid):
                P.verify_ticket(KEY, bad, 'bluff', SID, now=NOW)
        with self.assertRaises(Invalid) as e:
            P.verify_ticket(KEY, 'aps0.x.y', 'bluff', SID, now=NOW)
        self.assertEqual(str(e.exception), 'encoding')

    def test_open_message(self):
        for typ, aud in (('launch', 'bluff'), ('end', 'bluff'), ('ended', 'party')):
            for bad in self.BAD:
                with self.subTest(typ=typ, bad=bad), self.assertRaises(Invalid):
                    P.open_message(KEY, bad, typ, aud, P.ReplayGuard(), now=NOW)
            with self.assertRaises(Invalid) as e:
                P.open_message(KEY, 'aps0.x.y', typ, aud, P.ReplayGuard(), now=NOW)
            self.assertEqual(str(e.exception), 'encoding')


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
        self.assertEqual(got, {'participant': PID, 'role': 'player', 'sid': SID, 'host': None})

    def test_carries_no_identity_beyond_the_participant(self):
        payload = P.unseal(KEY, self.ticket(), 'ticket', 'bluff', now=NOW + 1)
        self.assertEqual(set(payload), {'v', 'typ', 'iss', 'aud', 'sid', 'iat', 'exp', 'pid', 'role', 'jti'})   # jti: random, no identity

    def test_the_host_claim_is_the_partys_word_or_absent(self):
        """True, False, or nothing: a ticket that does not say is never read as either."""
        for said, read in ((True, True), (False, False), (None, None)):
            ticket = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW, host=said)
            self.assertIs(P.verify_ticket(KEY, ticket, 'bluff', SID, now=NOW + 1)['host'], read)
            self.assertEqual('host' in P.unseal(KEY, ticket, 'ticket', 'bluff', now=NOW + 1), said is not None)
        for forged in (1, 'true', [True], {'host': True}):       # only a JSON boolean is a claim
            payload = P.unseal(KEY, self.ticket(), 'ticket', 'bluff', now=NOW + 1)
            payload['host'] = forged
            self.assertIsNone(P.verify_ticket(KEY, P.seal(KEY, payload), 'bluff', SID, now=NOW + 1)['host'])

    def test_expired(self):
        self.refused(self.ticket(), 'expired', now=NOW + P.TICKET_TTL)

    def test_issued_in_the_future(self):
        self.refused(self.ticket(now=NOW + 60), 'clock', now=NOW)

    def test_skew_boundary(self):
        self.refused(self.ticket(now=NOW + P.CLOCK_SKEW + 1), 'clock', now=NOW)
        P.verify_ticket(KEY, self.ticket(now=NOW + P.CLOCK_SKEW), 'bluff', SID, now=NOW)

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

    def launched(self):
        side = P.GameSide(KEY, 'bluff')
        side.on_launch(P.launch_message(KEY, 'bluff', SID, ROSTER, now=NOW), now=NOW)
        return side

    def test_ticket_is_single_use(self):
        side = self.launched()
        t = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW)
        side.admit(t, now=NOW + 1)
        with self.assertRaises(Invalid) as e:
            side.admit(t, now=NOW + 2)
        self.assertEqual(str(e.exception), 'replay')

    def test_fresh_tickets_for_one_participant_both_admit(self):
        side = self.launched()
        a = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW)
        b = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW + 10)
        self.assertEqual(side.admit(a, now=NOW + 11), side.admit(b, now=NOW + 11))

    def test_two_tickets_in_the_same_second_are_distinct(self):
        """iat is whole seconds; a reconnect right after a connect must not look like a replay."""
        side = self.launched()
        a = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW)
        b = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW)
        self.assertNotEqual(a, b)
        self.assertEqual(side.admit(a, now=NOW + 1), side.admit(b, now=NOW + 1))

    def test_present_reads_the_host_claim_from_one_spent_ticket(self):
        """A host action carries its own fresh ticket: the claim is read once and the ticket dies."""
        side = self.launched()
        t = P.mint_ticket(KEY, 'bluff', SID, PID, 'spectator', now=NOW, host=True)
        self.assertEqual(side.present(t, now=NOW + 1),
                         {'token': P.game_token(KEY, SID, PID), 'role': 'spectator',
                          'participant': PID, 'host': True})
        with self.assertRaises(Invalid) as e:
            side.present(t, now=NOW + 2)
        self.assertEqual(str(e.exception), 'replay')
        plain = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW)
        self.assertIsNone(side.present(plain, now=NOW + 1)['host'])
        other = P.mint_ticket(KEY, 'bluff', SID2, PID, 'player', now=NOW, host=True)
        with self.assertRaises(Invalid):
            side.present(other, now=NOW + 1)                 # another session's host is nobody here

    def test_refused_ticket_is_not_spent(self):
        side = self.launched()
        t = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW)
        with self.assertRaises(Invalid):
            side.admit(t, now=NOW + P.TICKET_TTL)
        self.assertEqual(side.spent.spent, {})

    def test_spent_set_is_pruned_after_exp(self):
        side = self.launched()
        t = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW)
        side.admit(t, now=NOW + 1)
        self.assertEqual(len(side.spent.spent), 1)
        t2 = P.mint_ticket(KEY, 'bluff', SID, PID2, 'player', now=NOW + 500)
        side.admit(t2, now=NOW + 501)
        self.assertEqual(len(side.spent.spent), 1)

    def test_launch_resets_spent_set(self):
        side = self.launched()
        t = P.mint_ticket(KEY, 'bluff', SID, PID, 'player', now=NOW)
        side.admit(t, now=NOW + 1)
        side.on_launch(P.launch_message(KEY, 'bluff', SID, ROSTER, now=NOW + 2), now=NOW + 2)
        self.assertEqual(side.spent.spent, {})
        side.admit(t, now=NOW + 3)

    def test_standalone_spent_tickets(self):
        s = P.SpentTickets()
        s.spend('x', NOW + 5, now=NOW)
        with self.assertRaises(Invalid):
            s.spend('x', NOW + 5, now=NOW + 1)
        s.spend('x', NOW + 50, now=NOW + 5)

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


def acl(*entries):
    """A raw `system.posix_acl_access` value: version 2, then (tag, perm, id) entries."""
    return struct.pack('<I', 2) + b''.join(struct.pack('<HHI', *e) for e in entries)


OWNER, USER, GROUP_OBJ, GROUP, MASK, OTHER_TAG = 0x01, 0x02, 0x04, 0x08, 0x10, 0x20
NO_ID = 0xFFFFFFFF
ME, ROOT, SOMEONE = 993, 0, 1000
R, RW = 4, 6


def credential_acl(reader=ME, owner=R, group=0, mask=R, other=0, extra=()):
    """What systemd writes for a LoadCredential file it could not chown: owner root may read, one
    named user may read, the owning group and everyone else get nothing."""
    return acl((OWNER, owner, NO_ID), (USER, R, reader), *extra, (GROUP_OBJ, group, NO_ID),
               (MASK, mask, NO_ID), (OTHER_TAG, other, NO_ID))


class KeyFilePermissions(unittest.TestCase):
    """Which key files read_key accepts (AVR-253). The rule: nobody but the file's owner and this
    process may be able to read the key, and nobody may be able to change it but its owner.

    A file with no group or other permission bits satisfies that by its mode. A systemd
    LoadCredential file does too, but its mode says 0440: the "group" bits of a file with a POSIX
    ACL are the ACL mask, not the group's rights. So such a file is accepted only when the ACL
    itself proves the rule."""

    def ok(self, mode, owner, acl_bytes=None, uid=ME):
        return P.key_file_problem(mode, owner, uid, acl_bytes) is None

    # ---- accepted ----------------------------------------------------------------------------
    def test_a_private_file_is_accepted_as_before(self):
        for mode in (0o600, 0o400):
            for owner in (ME, ROOT, SOMEONE):                 # ownership was never part of this check
                self.assertTrue(self.ok(mode, owner), (oct(mode), owner))

    def test_a_systemd_credential_with_an_acl_for_this_user_is_accepted(self):
        self.assertTrue(self.ok(0o440, ROOT, credential_acl()))
        self.assertTrue(self.ok(0o440, ME, credential_acl()))       # the same shape, self-owned

    # ---- still refused -----------------------------------------------------------------------
    def test_a_plainly_group_readable_key_is_still_refused(self):
        """0440 or 0640 with no ACL is real group access, whoever owns the file."""
        for mode in (0o440, 0o640, 0o460, 0o450):
            for owner in (ROOT, ME):
                self.assertFalse(self.ok(mode, owner), (oct(mode), owner))

    def test_anything_readable_or_writable_by_others_is_refused_even_with_a_good_acl(self):
        for mode in (0o444, 0o644, 0o604, 0o442, 0o441, 0o666):
            self.assertFalse(self.ok(mode, ROOT, credential_acl()), oct(mode))

    def test_group_bits_other_than_read_are_refused(self):
        for mode in (0o460, 0o450, 0o470, 0o420, 0o410):
            self.assertFalse(self.ok(mode, ROOT, credential_acl()), oct(mode))

    def test_an_acl_that_lets_the_owning_group_read_is_refused(self):
        self.assertFalse(self.ok(0o440, ROOT, credential_acl(group=R)))

    def test_an_acl_naming_another_user_is_refused(self):
        self.assertFalse(self.ok(0o440, ROOT, credential_acl(reader=SOMEONE)))
        self.assertFalse(self.ok(0o440, ROOT, credential_acl(extra=((USER, R, SOMEONE),))))

    def test_an_acl_naming_any_group_is_refused(self):
        self.assertFalse(self.ok(0o440, ROOT, credential_acl(extra=((GROUP, R, 33),))))
        self.assertFalse(self.ok(0o440, ROOT, credential_acl(extra=((GROUP, 0, 33),))))

    def test_an_acl_that_lets_anyone_write_is_refused(self):
        self.assertFalse(self.ok(0o440, ROOT, acl((OWNER, R, NO_ID), (USER, RW, ME), (GROUP_OBJ, 0, NO_ID),
                                                  (MASK, RW, NO_ID), (OTHER_TAG, 0, NO_ID))))
        self.assertFalse(self.ok(0o440, ROOT, credential_acl(owner=RW)))
        self.assertFalse(self.ok(0o440, ROOT, credential_acl(mask=RW)))
        self.assertFalse(self.ok(0o440, ROOT, credential_acl(other=R)))

    def test_an_acl_with_no_named_user_explains_nothing_and_is_refused(self):
        self.assertFalse(self.ok(0o440, ROOT, acl((OWNER, R, NO_ID), (GROUP_OBJ, 0, NO_ID),
                                                  (MASK, R, NO_ID), (OTHER_TAG, 0, NO_ID))))

    def test_a_credential_owned_by_a_third_user_is_refused(self):
        self.assertFalse(self.ok(0o440, SOMEONE, credential_acl()))

    def test_a_malformed_unknown_or_missing_acl_is_refused(self):
        good = credential_acl()
        for bad in (None, b'', good[:-3], struct.pack('<I', 1) + good[4:], good + b'\0' * 8,
                    acl((0x40, R, NO_ID)), b'not an acl at all!!!'):
            self.assertFalse(self.ok(0o440, ROOT, bad), bad)

    def test_the_refusal_names_the_file_and_not_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'bluff.key')
            P.write_key(path, KEY)
            if os.name != 'posix':
                self.skipTest('file modes are not enforced here')
            os.chmod(path, 0o640)
            with self.assertRaises(ValueError) as e:
                P.read_key(path)
            self.assertIn(path, str(e.exception))
            self.assertNotIn(KEY.hex(), str(e.exception))

    @unittest.skipUnless(hasattr(os, 'setxattr'), 'POSIX ACLs need Linux')
    def test_read_key_on_a_real_file_with_a_real_acl(self):
        """The same decisions made by read_key itself, on a file whose ACL the kernel holds."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'bluff.key')
            P.write_key(path, KEY)
            me = os.geteuid()
            try:
                os.setxattr(path, P.ACL_XATTR, credential_acl(reader=me))
            except OSError:
                self.skipTest('this filesystem does not store POSIX ACLs')
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o440)      # the mask shows as group
            self.assertEqual(P.read_key(path), KEY)
            os.setxattr(path, P.ACL_XATTR, credential_acl(reader=me, group=R))
            with self.assertRaises(ValueError):
                P.read_key(path)                                          # the group really can read
            os.setxattr(path, P.ACL_XATTR, credential_acl(reader=me, extra=((USER, R, me + 1),)))
            with self.assertRaises(ValueError):
                P.read_key(path)                                          # so can somebody else
            os.removexattr(path, P.ACL_XATTR)
            os.chmod(path, 0o440)
            with self.assertRaises(ValueError):
                P.read_key(path)                                          # plain 0440: no ACL


if __name__ == '__main__':
    unittest.main()
