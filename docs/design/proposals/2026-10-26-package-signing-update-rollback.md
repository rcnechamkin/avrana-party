# Package signing, provenance, update and rollback for `.avrgame` (AVR-58)

- **Status:** proposal, 2026-10-26. Nothing is implemented. The `.avrgame` format, the installer and the
  reserved manifest names are unchanged by this document. **Owner decisions are required** (section 10)
  before any code is written.
- **Reads with:** [AVRGAME-PACKAGE.md](../AVRGAME-PACKAGE.md) (format, install lifecycle, "Explicitly
  deferred"), [GAME-INSTALLATION.md](../GAME-INSTALLATION.md) (accepted direction 2026-10-02),
  `avrana/avrgame/manifest.py` (`RESERVED`), `avrana/ops/install_game.py`.
- **Related open proposals (draft PRs, not merged):** the offline clock policy (AVR-79, avrana-party#228:
  time floor, rules R4 and R5) and owner backup and restore (AVR-81, avrana-party#227: decision D1, keep the
  installed archive).

## 1. What exists today

| Fact | Source |
|---|---|
| The format is `avrana.avrgame/experimental.1`. Packing is reproducible: the same recipe gives identical bytes. | AVRGAME-PACKAGE.md "API and CLI"; pack determinism tests |
| `publisher`, `license` and `source` are display-only claims. No trust derives from them. | AVRGAME-PACKAGE.md "Manifest" |
| `signature`, `provenance`, `entitlement` and `publisher_key` are reserved and **refused**, so an ignored signature can never look like a checked one | `manifest.py` `RESERVED` |
| `requires.session`, `.bridge` and `.result` must equal what this Party implements; compatibility fails closed | `manifest.py` |
| Installing an id that is already installed is refused: upgrade and rollback are not implemented | AVRGAME-PACKAGE.md "Install lifecycle" step 1 |
| The install record keeps `id`, `version`, archive `sha256`, files, contract, grant and claims. The archive itself is not kept. | same, "Record schema" |
| Every installed package is tier `community`; the operator grants permissions; nothing is enforced at launch yet | same; AVR-336 |
| **Accepted direction:** a signature proves *same publisher and unchanged*, never *safe*; it changes nothing about isolation. Public-key cryptography belongs to package and update provenance, not to session tickets. A signed archive uses an Ed25519 key pinned at first install. A trusted repository is a signed index. | GAME-INSTALLATION.md (2026-10-02) |

## 2. Principles (all from accepted records or the AVR-58 constraints)

1. **Transport is not trust.** USB, a phone upload, a Companion courier and a download are all the same untrusted
   bytes until verified.
2. **A signature proves continuity and integrity, not safety.** A signed package still runs as `community` with
   operator-granted permissions.
3. **One install path.** Verification is a step inside `install_game`, never a second installer.
4. **No registry service on the appliance.** The appliance verifies files it is handed. It never serves,
   mirrors or polls a repository.
5. **Unsigned stays possible** for an owner's own or a friend's package (AVR-37: "no store, account or signature
   required"). Unsigned is shown as such, and the update rules below are stricter for it.
6. **Offline is first-class.** Nothing needs the internet at install time, and time is judged by the AVR-79
   floor, not by the wall clock.

## 3. What gets signed

**A detached signed statement, not a field inside the archive.** Signing the archive's own bytes from inside
the archive is circular. A detached statement keeps packing reproducible and the archive format unchanged.

`<name>.avrgame.sig` is strict JSON:

```json
{
  "schema": "avrana.avrgame-signature/v1",
  "statement": {
    "id": "courting", "version": "0.1.0",
    "archive_sha256": "6be09ff1…",
    "format": "avrana.avrgame/experimental.1",
    "requires": {"session": "…", "bridge": "…", "result": "…"},
    "platform": {"arch": "any"},
    "issued": "2026-10-26T09:00:00Z",
    "key": "ed25519:<base64url public key>"
  },
  "sig": "<base64url Ed25519 signature over the RFC 8785 canonical JSON of statement>"
}
```

- `statement` repeats what the installer will also read from the archive. Any disagreement refuses the install.
- `key` is the public key itself, not a URL or a name, so verification needs nothing else. The key id shown to
  people is the first 16 hex characters of the SHA-256 of the raw key.
- `issued` is the publisher's claim. Section 6 says what it may do (raise the floor) and what it may not do
  (be trusted when the floor is lower).
- No expiry on a package statement. A publisher's "I published these bytes" does not go stale. Freshness belongs
  to repository metadata (section 7) and revocation (section 8).
- The reserved manifest names stay refused. Nothing is added to `avrgame.json`.

Tools: `python -m avrana.avrgame sign <file> --key <private key file>`, which writes the sidecar, and
`verify <file> [<sig>]`, which reports the key id and the result. Both are offline and need no root. The private key
never touches the appliance.

## 4. Trust on the appliance

| Package state | First install | Update (same id) |
|---|---|---|
| **Signed, key new to this unit** | allowed after the owner confirms "publisher key `ab12…` is new to this Party"; the key is **pinned** in the install record | – |
| **Signed by the pinned key** | – | allowed (section 5 rules); no new key prompt |
| **Signed by a different key** | – | **refused**, unless a rotation statement signed by the pinned key names the new key (AVR-78), or the owner removes the game first (its state is then kept only if they choose) |
| **Unsigned** | allowed after the owner confirms "publisher not verified" | allowed only with the same confirmation every time; never silent; shown as unsigned in the owner view |
| **Signed, then an unsigned update** | – | **refused** (a downgrade of trust); the owner can remove and reinstall |

**First-party packages** (built-in games, future official ones) are signed by an Avrana publisher key that the
appliance ships with, so they need no first-install prompt. That key is itself delegated from an offline Avrana
root key (section 7), never kept online.

The install record gains:

```json
"provenance": {"signed": true, "key": "ed25519:…", "key_id": "ab12…", "pinned_at": "…", "issued": "…",
               "highest_version": "0.1.0", "verified_with_time_state": "floor"}
```

## 5. Update, downgrade and rollback

| Action | Rule |
|---|---|
| **Update** | `version` strictly greater (SemVer 2.0 precedence) **and** different `archive_sha256`. The same version with different bytes is refused: a republished version is a new version. |
| **Permissions** | An update requesting a permission the current grant does not hold is staged but **not activated** until the owner grants it. Permissions are never carried over silently, and a dropped request is dropped from the grant. |
| **Install beside, then switch** | As GAME-INSTALLATION.md already says: stage `/opt/avrana-games/<id>/<version>-<sha12>`, snapshot the state directory, write the new record, then reload. A failure at any step leaves the old version running (the guarantee `install_game` already gives for a first install). |
| **Keep the previous version** | The previous staged tree, its archive and its state snapshot stay (**N = 1 previous**, D3), so a local rollback needs no file from outside. This also gives AVR-81 its archives (that proposal's D1 b). |
| **Rollback (owner action)** | Switch back to the kept previous version **and** its state snapshot. Allowed even though the version is lower, because these exact bytes were already accepted on this unit. The record keeps `highest_version`. |
| **Downgrade to bytes never installed here** | **Refused** for signed packages (rollback attack: an old, vulnerable but validly signed version). Unsigned: refused unless the owner forces it with a warning. |
| **Never during a party** | Update and rollback wait until no session of that game is running (`install_game` already checks the active set for remove). |
| **Compatibility** | An update whose `requires` or `platform` the unit does not meet is refused before staging, exactly as for a first install. |

## 6. Freeze and rollback protection

- **Per package:** `highest_version` in the record only rises. That is the downgrade check in section 5.
- **Per key:** the pin, plus rotation only through a statement from the old key (AVR-78).
- **Time:**
  - A verified statement's `issued` may raise the AVR-79 floor (rule R5 there), capped by that proposal's D4.
  - A statement whose `issued` is in the future beyond the floor plus the cap is accepted as a signature but
    **raises nothing**, and the owner view says "date not verified".
  - No package statement expires (section 3), so a wrong clock can neither make a valid package fail nor make a
    stale one pass.
- **Repository metadata** (section 7) is where freshness and freeze attacks matter. That is TUF's model, and
  it is adopted as is.

## 7. Repositories and couriers (no service on the appliance)

A repository (AVR-57) is a **directory of files**, served by anyone or carried on a USB stick or by a Companion
(AVR-63). It holds a TUF-shaped metadata set:

| Role | Signed by | Expiry (proposal, D5) | Holds |
|---|---|---|---|
| `root` | the offline Avrana root key (later a threshold of keys) | 1 year | the keys of the other roles |
| `targets` | the targets key; delegations to publisher keys by id prefix | 3 months | for each package: id, version, `archive_sha256`, length, and the delegated publisher key |
| `snapshot` | the snapshot key | 1 week | the versions of every targets file (prevents mix-and-match) |
| `timestamp` | the timestamp key | 1 day online; **ignored offline** (D6) | the current snapshot version |

How the appliance uses it:

- It verifies a carried metadata set with python-tuf's metadata API or an equivalent small verifier. It needs no
  network and runs no update loop.
- A package listed in valid targets metadata is installed with the targets-delegated key as its pin. The
  sidecar `.sig` is then optional.
- **Offline staleness** (judged against the AVR-79 floor):
  - `root` and `targets` past expiry → refuse repository installs and say so;
  - `snapshot` past expiry → installs allowed, marked "repository freshness not verified";
  - `timestamp` is not required offline.
  - Revocations published after the carried snapshot cannot be known. The owner view says so, and the next online
    or courier refresh applies them.
- Metadata version numbers only rise (TUF). The appliance keeps the highest version seen of each role, so a
  courier cannot hand it older metadata later.

## 8. Revocation and compromise

| Event | Response |
|---|---|
| A publisher key is compromised | The publisher (or Avrana, for a delegated key) publishes a revocation in `targets`. Units that receive it refuse new installs and updates under that key. Already-installed packages keep running, and the owner is told. |
| A specific version is bad | It is removed from `targets` and a higher version is published. `highest_version` prevents going back to it. |
| The Avrana targets or snapshot key is compromised | Rotated by a new `root` signed by the old root (TUF root rotation). |
| The root key is compromised | Only a firmware or appliance update signed under the AVR-82 chain can replace the shipped root. That is why root stays offline, and later becomes a threshold. |

## 9. Compatibility metadata and install-time risk presentation

- **Compatibility:**
  - `requires` (exists) plus a new `platform` in the statement and, later, the manifest:
    `{"arch": "any" | "arm64" | "x86_64", "runtimes": {"python3": ">=3.11"} | {"node": "<pinned major>"}}`.
  - Pure-Python and pure-JavaScript packages say `any`. A package with a native binary must name its arch.
  - The installer refuses a mismatch before staging (fail closed, as `requires` does today).
- **Risk presentation (AVR-62):** the owner prompt is computed by the appliance, never written by the package
  (the Home Assistant add-on idea). The appliance sums up:
  - the signature state (first-party / pinned publisher / new key / unsigned);
  - the requested permissions in plain words;
  - the tier (`community`) and its resource ceilings;
  - whether the game ships a server process;
  - the size.

  Nothing in the manifest can raise its own rating.

## 10. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | Keep unsigned packages installable? | yes, with confirmation; no | **yes**, with a confirmation every time (AVR-37 direction) |
| D2 | Signature format | detached Ed25519 statement (this proposal); signify/minisign files; Sigstore | **detached Ed25519 statement**: offline, one small dependency or none (`cryptography`'s Ed25519 is already packaged on Raspberry Pi OS; to be confirmed on the Pi), no transparency log needed |
| D3 | How many previous versions to keep | 1; 2 | **1**: SD card space; with AVR-81 backups covering the rest |
| D4 | First-install key prompt wording and who may confirm | owner credential only (AVR-44) | **owner only**; never the Party Host |
| D5 | Repository metadata expiries (section 7) | as proposed; longer for couriers | **as proposed**, revisit after the first courier test |
| D6 | Require `timestamp` freshness when online? | yes; no | **yes online, ignored offline**, as section 7 says |
| D7 | Who holds the Avrana root key, and how | a single offline key now; a 2-of-3 threshold before retail | **single offline key** for the prototype (on paper and in a hardware token), a **threshold before any retail unit** |

## 11. Phasing

1. **P1 — sign and verify, no behaviour change on the appliance.** The `sign` and `verify` commands; the sidecar
   schema; tests. `install_game` reports signature state in `--dry-run` and the record, but still refuses an
   installed id.
2. **P2 — pin and update.** Pinning, the section 4 table, update/rollback per section 5 (with AVR-60 for the
   owner-facing words), and keeping the previous archive (AVR-81 D1).
3. **P3 — repositories.** TUF metadata verification for couriered and downloaded sets (AVR-57, AVR-63).
4. **P4 — appliance updates.** The same root, with an `updates` delegation for the signed appliance update chain
   (AVR-82).

Each phase is a separate PR with its own owner gate. P1 touches only `avrana/avrgame/` and tests.

## 12. Tests to write with P1 and P2

- Round trip: sign a reproducible pack, then verify; flip one byte of the archive, then of the statement, then of
  the signature → each is refused with a distinct reason.
- Statement and archive disagree (id, version, `requires`, `platform`) → refused.
- Canonical JSON: a statement re-serialised with other spacing or key order still verifies; a duplicate key is
  refused (`strictjson`).
- Pinning: a first install pins the key; an update by the same key passes; a different key is refused; a rotation
  statement from the old key passes; a rotation statement from the new key alone is refused.
- Versions: update to a higher version passes; the same version with different bytes is refused; downgrade to
  never-installed bytes is refused; rollback to the kept previous version passes and restores its state snapshot.
- Permissions: an update requesting a new permission stages but does not activate until granted.
- Time: a future `issued` beyond the cap verifies but does not raise the floor.
- Failure injection at every step of update and rollback leaves the previous version running with byte-identical
  files (the `install_rehearsal.py` method).

## 13. What this does not cover

- Runtime isolation and trust tiers (AVR-69), per-game browser origins (AVR-509): a signature changes none of it.
- Storefronts, entitlements and licensed delivery (AVR-143, AVR-316).
- Dependency bundles (AVR-77).
- The owner app's transport (AVR-45, AVR-63) beyond "it hands the installer files".
