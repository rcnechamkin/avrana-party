# Runbook: native Checkers real-device acceptance (AVR-261)

Status: **PROPOSED owner-run procedure, NOT RUN on the appliance** (2026-10-09).

The procedure for [AVR-261](https://linear.app/avranakern/issue/AVR-261/play-checkers-on-real-phones-over-the-pis-wi-fi)
now lives in one place, with the release pair, backups, deploy, nginx, native-game preparation,
provisioning, the two-phone Checkers scenarios, rollback and the record sheet:
[friend-ready-acceptance](friend-ready-acceptance.md) (step 7 and the AVR-261 record table).
This is Session B of that packet, and it is blocked: Checkers needs the game origin (Linear AVR-319, runbook `docs/runbooks/game-origin.md`, arrives with that issue). This file no longer carries its own copy, so the two cannot drift.

The merge prerequisites this file used to list are done: Games PR #54 (`fb711d9`), Party PR #94
(`b5a484c`) and the AVR-314 nginx cookie fix, PR #95 (`defd4a2`). A merge is not a deployment:
nothing here has been deployed or run, and CI, Chromium and disposable-runner systemd evidence
do not prove Raspberry Pi or phone readiness. Accepted architecture is
[ADR 0013](../adr/0013-party-and-game-browser-origins.md), [ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md)
and [ADR 0016](../adr/0016-service-identities-and-local-trust-boundary.md); [SYSTEM](../SYSTEM.md) and live
`/party/api/status` state what is deployed. An agent cannot close AVR-261.
