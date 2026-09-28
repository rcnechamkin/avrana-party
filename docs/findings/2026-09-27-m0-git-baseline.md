# M0: canonical Git baseline (2026-09-27)

Status: TESTED (Git state, offline suites, read-only Pi checks). Nothing deployed, no Pi change.
Branch map after this pass: `docs/SYSTEM.md` → "Branches of this repository".

## Git

- `main` = `a2a5682` (PR #7). The laptop's `main` fast-forwarded `a671955` → `a2a5682`; no merge commit.
- The `party-dev` remote (Pi lab clone) holds no commit absent from `origin`.
- Deleted after checking that each is an ancestor of `origin/main` (0 unique commits):
  `chore/cloud-handoff` `0a0e949`, `docs/current-state` `0467f67` (local only), `fix/party-https`
  `0f77786`, `fix/party-shell-assimilation` `85d9dd9`, `fix/lan-games-providerization` `9e5c1fd`,
  `fix/arcade-fatal-exit` `4bdd307`, `claude/dreamy-carson-sja5mq` `0db0556`.
- Deleted `fix/party-home-reconnect` `6a00c4a`: an ancestor of `experiment/party-service` (PR #6).
- `fix/arcade-ap-interface` `92d66bc` was replaced by `fix/arcade-ap-address` (the same patch on
  current `main`, plus its test moved into `tests/unit/` so CI runs it) and deleted.
- Kept (parked, unique work): `experiment/party-service`, `experiment/party-sim`,
  `experiment/ps1-title-profiles`, `ps1-emulation`, `docs/party-platform`.

## `docs/party-platform` reconciliation

Of the 25 files that still differ from `main`, almost all are **superseded**: the branch has older
text that `main` rewrote later (laptop-only workflow, plain-HTTP accepted risk, pre-HTTPS SYSTEM map,
old arcade code). Brought to `main` on `chore/m0-reconcile`:

- `tools/avrana-offline`, `tools/avrana-topology-check`, `tools/radio-watch`: `main`'s network and
  BLUFF-playtest runbooks already told operators to run them, but they existed only on the branch.
  They are needed for the offline acceptance test.
- `install-captive-dns.py`: `main` bounces NetworkManager profile `Avrana Party`. On the Pi that
  profile has no device and autoconnect is off; the AP is `Avrana Party Internal` on `wlan0`. So
  `main`'s installer fails and rolls back. The branch's version names the right profile (overridable)
  and refuses unless it is active.
- Two comments with the Pi's old home-LAN address.

Left on the branch (historical): raw power evidence (`docs/findings/evidence/`, ignored on `main` by
design) and its script.

## Production vs `main` (read on the Pi, 2026-09-27)

- Production checkout `/home/cody/avrana-party` and the installed `/party/` release are both
  `459d4cd` (PR #5). **`main`'s PR #7 (LAN provider launch) is not deployed.**
- `avranaparty-arcade` started 2026-09-26 00:11 PDT; `avranaparty-games` and nginx active; live
  nginx site = production checkout.
- `tools/avrana-topology-check` from a lab copy: all PASS, exit 0 (wlan1 absent, wlan0 AP on
  `10.42.0.1/24`, one AP profile autoconnects, DNS only on the AP, captive probes, nginx parity).

## Tests

| Where | Command | `main` | this pass |
|---|---|---|---|
| laptop (Windows) | `python -m unittest discover -s tests/unit` | 72 run, 6 fail/error | 72 (reconcile) / 76 (AP fix), same 6 |
| Pi lab copy (Linux, `git archive`, no repo) | same | 72 run, 2 fail/error | 76 run, same 2 |
| laptop | `node --test tests/offline/*.test.mjs` | — | 56 pass |
| laptop | `python -m avrana.contracts.catalog --check` | — | clean |

The 6 Windows-only failures are pre-existing (path separators, symlinks, POSIX signals). The 2 Linux
ones come from `test_web_build.InstallScript` needing a real Git checkout. CI (Ubuntu, a checkout)
is the reference run.

## Not done here

- Games fork: its `main` is `3a6c472` (PR #1). The laptop's `main` (`2cf4831`) and the bare backup
  still need a fast-forward, and the merged `fix/avrana-provider-integration` still needs deleting.
  Both left for the owner.
- PRs for `fix/arcade-ap-address` and `chore/m0-reconcile` need opening (the `gh` CLI is not signed
  in here).
