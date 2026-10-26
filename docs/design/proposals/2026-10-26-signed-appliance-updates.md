# Signed appliance updates and release provenance (AVR-82)

- **Status:** proposal, 2026-10-26. Nothing is implemented. **Owner decisions required** (section 8).
- **Reads with:**
  - [deploy](../../runbooks/deploy.md) (`ops/deploy.sh`);
  - [release-candidate](../../runbooks/release-candidate.md) (`tools/release_candidate.py`, `avrana.release-candidate/v0`);
  - the package-signing proposal (AVR-58, draft #230): this reuses its statement format and key handling;
  - the offline clock proposal (AVR-79, draft #228);
  - AVR-422 (owner-modifiable mode) and AVR-423 (hardware security).

## 1. What is true today

| Step | What it proves | What it does not |
|---|---|---|
| The owner picks two commit SHAs (Party, Games) | the exact trees (git object hashes) | that Avrana released them |
| `release_candidate.py assemble` writes `release-candidate.json`, sealed with `manifest_sha256` (SHA-256 of its canonical JSON), plus the contract check, the SBOM check and offline git bundles | the pair is compatible, and the file has not been edited since it was sealed | who sealed it: anyone can re-seal an edited file |
| `ops/deploy.sh --party <sha> --games <sha>` on the Pi `git fetch`es from GitHub (or from a bundle), builds `/opt/avrana-party/releases/<sha>`, keeps a last known good, can roll back | the commit is the one named; rollback goes to a recorded pair | transport is GitHub's SSH authentication, and a bundle carries no signature. **The appliance verifies nothing about authorization.** A person with sudo and a SHA can deploy any commit (`--allow-branch` for one not on `main`). |

On the prototype this is deliberate: the owner is the only operator, and the Pi is not a consumer device. It stops being enough once someone other than Avrana's owner holds an appliance, or an update arrives on a USB stick.

## 2. Principles

1. **Transport is not trust.** GitHub, a bundle file, a USB stick and an owner-app courier are all just carriers. The appliance verifies the same signed statement whichever one brought it.
2. **The updater moves slots; the release key authorizes.** An A/B updater (Rugix, if chosen: AVR-67) owns safe switching and boot fallback. It must not be the thing that decides an update is Avrana's.
3. **No release-signing key on any appliance**, and none in CI that runs untrusted code.
4. **Signatures prove integrity and authorization, not confidentiality.** Verified boot does not stop the owner of an unlocked unit from reading its code, and is never sold as doing so.

## 3. The signed release statement

A release is `release-candidate.json` (as today) plus a detached statement `release.sig.json`, in the same shape as AVR-58's package statement (Ed25519 over the RFC 8785 canonical JSON):

```json
{"schema": "avrana.release-statement/v1",
 "release": "2026.11.0",                        // monotonic release version
 "sequence": 42,                                // strictly increasing; the rollback counter
 "party_sha": "…40 hex…", "games_sha": "…40 hex…",
 "archives": {"party.tar": "sha256:…", "games.tar": "sha256:…"},   // the `git archive` digests the Pi stages
 "bundles": {"party.bundle": "sha256:…", "games.bundle": "sha256:…"},
 "candidate_manifest_sha256": "…",              // binds today's sealed manifest
 "hardware": ["pi5-prototype"],                 // which platforms may install it
 "min_from_sequence": 30,                       // oldest release that may update straight to this one
 "sbom": "sha256:…", "notices": "sha256:…",     // the SBOM and NOTICE files of this release
 "issued": "2026-11-02T18:00:00Z", "expires": null,
 "key": "release-2026a", "sig": "base64…"}
```

**Binding:** version → sequence → exact commits → archive and bundle digests → SBOM and notices → allowed hardware.
- The appliance computes each digest itself from what it staged, and refuses on any difference.
- Today's `manifest_sha256` seal stays: the signature covers it.

## 4. Keys

| Role | Where it lives | Signs | Rotation |
|---|---|---|---|
| **Root** | offline: hardware token or paper backup. Owner decision D2. | the key list (`keys.json`: which release keys are valid, from which sequence) | rare. A new root is signed by the old one. Compromise of the root is the one case that needs a person and a re-flash. |
| **Release** | the owner's laptop or a hardware token, never a device or CI | release statements | yearly, or at once on suspicion: root signs a new `keys.json` that ends the old key at a sequence |
| **Package publishers** (AVR-58) | each publisher | `.avrgame` statements | separate from release keys: a game key can never authorize a system update |

- The appliance ships with the root public key in its image and the current `keys.json`.
- A `keys.json` is accepted only if it is signed by root and its own `sequence` is higher than the one held.
- **Revocation:** a revoked release key's statements are refused from the revocation sequence on. A release that is already installed keeps running. It is shown as "signed by a retired key" and replaced by the next update.

## 5. Rollback and downgrade

- The appliance stores `highest_sequence` installed, in the same place as the last known good. The AVR-79 time-floor file is a model: owned by root, written atomically.
- **An update** needs `sequence > highest_sequence` and `highest_sequence >= min_from_sequence`.
- **A rollback to the last known good**, the release that ran before, is always allowed, without a new signature. It is a recovery, not a downgrade. `highest_sequence` is not lowered, so the next update must still be newer than the highest ever installed.
- **Going further back** than the last known good needs a statement with `"allow_downgrade_to": <sequence>`, signed by the release key, for that one step. This is for a release later found broken.
- **Time:** expiry is optional and off by default for releases (D4). An offline appliance must keep updating from a USB stick. Where an expiry is set, it is judged against the AVR-79 floor, never against an unverified clock.

## 6. Offline couriers

A courier carries the files and nothing else:
- `release-candidate.json`;
- `release.sig.json`;
- both bundles;
- `keys.json` if it is newer.

It can be a USB stick, a laptop over SSH, or later the owner app (AVR-63, AVR-64). Verification is byte-for-byte the code path of an online update: the same verifier, the same digests, the same rollback rules. `deploy.sh` would call the verifier before it stops anything, at the point where it reads state and fetches today.

## 7. Owner-modifiable mode (AVR-422)

| State | What the appliance accepts | What it says |
|---|---|---|
| **Official** | only releases signed by a current release key | "Official software, release 2026.11.0" |
| **Unlocked** (the owner chose it deliberately, with a physical step on retail hardware) | any build, signed or not. `highest_sequence` is still recorded. | "Unlocked: this box runs software Avrana did not sign", always on the owner page, never hidden |
| **Relock** | a factory reset to the last official image, or a signed release newer than `highest_sequence`; an owner key never relocks | back to Official |

- Unlocking never reveals or uses Avrana's release key.
- Owner data (configuration, installed games) survives an unlock or relock only through the AVR-81 backup.
- On retail hardware, the recovery image is official and verified. On the Pi prototype, recovery is an SD card re-flash, and its image provenance is the signed statement of the release it was built from.

## 8. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | When to require signed releases on the appliance | now on the Pi; at the first unit held by someone else; at retail | **the first unit held by someone else** (friend-ready). On the Pi: verify and warn, never refuse. |
| D2 | Root key custody | one hardware token plus a paper backup; 2-of-3 threshold | **one token plus paper now; a threshold before retail** (matches AVR-58 D7) |
| D3 | One release key for Party and Games together, or two | one (the pair is released together); two | **one**: the statement already binds the pair |
| D4 | Release statements expire? | no; yes, 1 year | **no** (offline updates must work); revocation uses `keys.json` |
| D5 | Keep `--allow-branch` deploys of unsigned commits on the Pi | yes, with a warning; no | **yes on the prototype**; in Official mode it becomes an Unlocked-only action |
| D6 | SBOM and NOTICE in the statement | required; optional | **required**: `tools/sbom.py --check` already runs in `assemble` |

## 9. Implementation sketch (not done here)

1. `tools/release_candidate.py sign` (laptop only, refuses without a key it can find) and `verify-release` (pure: statement + files + `keys.json` → verdict).
2. `avrana/ops/release_verify.py` on the appliance, called by `deploy.sh` before it changes anything, and by `--recover` and `--rollback` for their own rules.
3. `highest_sequence` next to the last known good, and the owner page line of section 7.
4. Tests:
   - an edited manifest;
   - a statement signed by a game key;
   - a retired key;
   - a replayed older statement;
   - rollback to the last known good with no signature;
   - a downgrade without `allow_downgrade_to`;
   - an archive digest that differs from the one staged;
   - courier and online verification giving identical verdicts.
