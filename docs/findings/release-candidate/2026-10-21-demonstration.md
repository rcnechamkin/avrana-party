# Release candidate demonstration, 2026-10-21 (AVR-699)

Evidence of one run of `tools/release_candidate.py` on a Windows 11 laptop. Nothing was installed, deployed or run on the Pi, and no phone was involved. The process is in [release-candidate](../../runbooks/release-candidate.md).

## The pair

Party `main` `8de7ef20835a1d98ec55cb772c216cbd348084fa` (PR #167) with Games `main` `1dc48d22fc189cc6e92fce23109d639230c471df` (PR #92), named as `origin/main` in each local repository, with no fetch.

| Command | Result | Output |
|---|---|---|
| `assemble --bundle` | exit 0, `CANDIDATE_OK`, **no flags** | [json](2026-10-21-release-candidate.json), [md](2026-10-21-release-candidate.md) |
| `verify` | exit 0, REPRODUCED, bundles re-checked | [txt](2026-10-21-verify.txt) |
| `prereq`, READY fixture, last-known-good fixture, both repositories (re-derived) | exit 0, `CLEARED_FOR_OWNER` (with `CLOCK OVERRIDDEN`), commands printed | [txt](2026-10-21-prereq-ready.txt), [json](2026-10-21-prereq-ready.json) |
| `prereq`, NOT_READY fixture | exit 1, `BLOCKED` by `no_live_session` (FAIL) and `nginx_config` (UNKNOWN), no commands printed | [txt](2026-10-21-prereq-not-ready.txt), [json](2026-10-21-prereq-not-ready.json) |
| `rehearse-rollback`, before pair Party `c59f1c8` / Games `a448972` | exit 0, `REHEARSAL_PASSED`, 7 of 7 steps PASS | [txt](2026-10-21-rehearse-rollback.txt), [json](2026-10-21-rehearse-rollback.json) |

What `assemble` recorded: `tools/contract_check.py` run on the two exact `git archive` trees said `Party <-> Games contract: compatible`; contract `avrana.party-games/v0` on both sides; the Party layer digest Games pins equals the one Party's `web/party/bridge/layer-mount.js` has (`2b60de2d...3088`); Python 3.11 or newer; the optional Node runtime pin 22.22.2; `tools/sbom.py --check` ok (36 components); both commits are ancestors of their `origin/main`. Archive digests: Party `4c02093e...569c`, Games `f9cf133c...56b0`. Bundles (not committed): `party.bundle` sha256 `5a9f63ea...d176`, `games.bundle` sha256 `98d07f23...7ad0`; each holds exactly its SHA as `HEAD` and `refs/heads/release-candidate`.

Re-run after the independent review (same day): the manifest now carries `manifest_sha256`; the archive and bundle digests did not change. `prereq` was also run on the three committed AVR-696 preflight examples (`docs/findings/preflight/` on that branch): the simulated READY clears; the simulated field day is BLOCKED by its nine blocking checks; the dev-server run is BLOCKED, first of all by `mode 'local'`.

## The rehearsal

The candidate's own `ops/deploy.sh` ran from an exported copy of the candidate Party tree, against throwaway clones with local bare origins, with every `AVRANA_*` path inside a scratch root.

- `--party 8de7ef20835a --games 1dc48d22fc18 --dry-run` planned `c59f1c8 -> 8de7ef2` and `a448972 -> 1dc48d2`, ran the contract check on the two exact commits (compatible), exited 0 and ended `dry run: nothing changed`.
- After the scratch checkouts were moved to the candidate (a stand-in for a finished deployment), `--rollback --dry-run` resolved the seeded last-known-good to the before pair, planned `8de7ef2 -> c59f1c8` and `1dc48d2 -> a448972`, and changed nothing.
- The scratch root was byte-for-byte the same after each dry run, no backup, web, `/opt` or nginx file was created, and both real repositories had the same HEAD, branch and status afterwards.
- `ops/deploy.sh` was not modified. Its dry run did not need root: only the certificate-name check says `could not check ... root is needed`, as documented.

## Not shown, and caveats

- **The preflight files are hand-written fixtures** (`tests/fixtures/release_candidate/`), written to the `avrana.preflight/v0` contract the sibling track will produce. The fixture dates are fixed, so `--now 2026-10-21T22:45:00Z` was passed to make the output reproducible; without it the same files are `BLOCKED` as stale. A `CLEARED_FOR_OWNER` here says the arithmetic of the rules holds, not that the Pi is ready.
- The last-known-good record in the rehearsal was seeded with `avrana.ops.manifest`. The real Pi's record was not read.
- Not reproduced: root, systemd, `nginx -t` and reload, real `/opt` releases, the web release flip, smoke, a real rollback, certificates, Wi-Fi and phones.
- The rehearsal and bundle output carry scratch paths and clocks, so a second run differs in those lines only.
- Cosmetic, left alone: in a dry run with Party Core down, `ops/deploy.sh` logs `party core: unknown` and then a second `unknown` line (the busy check echoes twice when `curl` fails under `pipefail`). It does not affect the result.
