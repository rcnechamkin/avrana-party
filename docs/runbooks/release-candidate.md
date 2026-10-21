# Runbook: release candidate, from two commits to the owner's deploy (AVR-699)

Status: **PROPOSED procedure. The laptop steps are tested against throwaway repositories and the real mains; the Pi steps are owner-run and NOT RUN on the appliance** (2026-10-21).

`tools/release_candidate.py` is the paperwork and the rehearsal that come before [deploy](deploy.md). It decides nothing, installs nothing, and never contacts the network or the Pi. The owner still runs `ops/deploy.sh`, with sudo, on the Pi; the field-test gate runbook (an open PR, not yet on `main`) says when. Merged is not deployed; a clear result here is not phone verification.

## The sequence

Work on a laptop with both repositories. **Fetch first, yourself:** the tool uses only refs already present and never fetches.

```bash
git -C ../avrana-party fetch origin && git -C ../avrana-party-games fetch origin
OUT=build/release-candidate/2026-10-21

# 1. Assemble: resolve the SHAs, run tools/contract_check.py on the two exact trees, write the manifest + bundles.
python tools/release_candidate.py assemble --party-repo ../avrana-party --games-repo ../avrana-party-games \
    --party origin/main --games origin/main --out $OUT --bundle

# 2. Verify: re-derive everything from the same two SHAs; any difference is reported (exit 1).
python tools/release_candidate.py verify $OUT/release-candidate.json --party-repo ../avrana-party --games-repo ../avrana-party-games

# 3. Rehearse: ops/deploy.sh --dry-run and --rollback --dry-run in a disposable root (no root needed, nothing real touched).
python tools/release_candidate.py rehearse-rollback $OUT/release-candidate.json --party-repo ../avrana-party \
    --games-repo ../avrana-party-games --before-party <deployed Party sha> --before-games <deployed Games sha>
```

4. **Preflight (read-only).** From the laptop, `python tools/preflight.py --ssh party --json` (AVR-696; it saves under `test-results/preflight/`). The preflight carries the deployed pair and the last known good, so `--status` is optional; when given (`curl -s https://party.avrana.net/party/api/status > status.json`), it must be as fresh as the preflight and name the same deployed pair. Both are good for 60 minutes.
5. **Prerequisites.** `python tools/release_candidate.py prereq $OUT/release-candidate.json --preflight preflight.json --party-repo ../avrana-party --games-repo ../avrana-party-games`. It prints `CLEARED_FOR_OWNER` (exit 0) or `BLOCKED` (exit 1) and, only when cleared, the exact owner commands. It runs none of them.
6. **Owner's dry run (Pi, sudo).** The first printed command pair: `--status`, then `ops/deploy.sh --party <sha> --games <sha> --dry-run`. Take the script from the target commit when the checkout is older ([deploy](deploy.md), "First run"). Stage the Games commit on the Pi first if it is not there: copy `games.bundle` over and `git fetch` from it ([games-fork-deploy](games-fork-deploy.md)); `git clone` of a bundle checks out the exact commit too.
7. **Owner's deploy (Pi, sudo).** The same line without `--dry-run`, with `--require-cert-names` only when native games use the game origin and the certificate-name gate passed (field-test gate runbook, step 2).
8. **Rollback.** `ops/deploy.sh --rollback --dry-run`, then `--rollback`, or the route in [deploy](deploy.md) "Which command next". `prereq` warns when no last known good exists: then `--rollback` has no target.

## Exit codes

| Command | 0 | 1 | 2 |
|---|---|---|---|
| `assemble` | `CANDIDATE_OK` | `CANDIDATE_FLAGGED` (files are still written) | error, nothing written |
| `verify` | reproduced | differences listed | error |
| `prereq` | `CLEARED_FOR_OWNER` only | `BLOCKED`, including a missing or unreadable input | usage |
| `rehearse-rollback` | every step passed | a step failed | could not be set up (3: partial, a step was not reproducible here; not a pass) |

## What `prereq` refuses to trust

- **The manifest.** `assemble` seals it (`manifest_sha256`, the SHA-256 of its canonical JSON); an edited manifest is BLOCKED. Its flags and verdict must be the ones its own facts give. The pair must be `compatible` by `tools/contract_check.py`; `--accept-unchecked` accepts a pair the checker could not run on (an old commit), never one it rejected. With `--party-repo` and `--games-repo` the whole manifest is re-derived, as `verify` does; without them `prereq` says it was not.
- **The preflight.** It must be `mode: appliance` (a `--local` dev-server run never clears), list its checks, carry a time with a zone, and be at most `--max-age-min` old (a positive finite number). A blocking FAIL always blocks; a blocking UNKNOWN blocks unless the operator waived it on the Pi (`--waive`), and the waiver is repeated in the warnings.
- **The clock.** `--now` is for tests and demonstrations: the result then says `CLOCK OVERRIDDEN`.

## What the manifest flags

`FAIL` blocks `prereq`; `WARN` is carried into its output. FAIL: `contract_incompatible` (the checker's own message is recorded), `layer_digest_mismatch` (the Party layer digest Games pins differs from the `layer-mount.js` this Party commit ships; re-vendor with Games `ops/vendor_party.py`), `layer_declaration_drift`, `contract_version_mismatch`. WARN: `party_not_on_origin_main` (`ops/deploy.sh` then refuses unless the owner passes `--allow-branch`; the tool never adds it), `*_origin_main_unknown`, `contract_not_checkable` (a commit predates the checker), `sbom_inventory`, a missing lock file or pin.

## What is proved, and what is not

- Proved: the manifest is re-derivable from the two SHAs; the checker passed on the exact trees; the candidate's own `ops/deploy.sh` plans the candidate pair and plans `--rollback` back to a seeded last known good, exits 0, and changes nothing in the scratch root or either real repository.
- The rehearsal runs the candidate's `ops/deploy.sh` only if it reads every path the rehearsal moves (`AVRANA_PARTY_CHECKOUT`, `..._RELEASES`, `AVRANA_NGINX_SITE` and the rest); an older script that would act on a real path is not run. Children get no inherited `GIT_*` or proxy variables. A step is `NOT_REPRODUCED` only when the script's own last word is a root refusal (`deploy: run as root`); any other failure is a FAIL.
- Not reproduced, so still the owner's: root and `sudo -u`, systemd restarts, `nginx -t` and the reload, real `/opt` releases and the web release flip, the post-deploy smoke, a real rollback, certificates, Wi-Fi, iPhone Safari and every phone. The rehearsal's last-known-good record is seeded with `avrana.ops.manifest`; it stands for an earlier deployment and is not one.
- The archive digest is that of `git -c core.autocrlf=false archive --format=tar`, which is what the Pi stages. A Windows git with `autocrlf=true` would otherwise put CRLF in the archive and change the digest.
- The demonstration on the 2026-10-21 mains is in [findings](../findings/release-candidate/2026-10-21-demonstration.md). Its preflight files are hand-written fixtures, not an appliance's.
