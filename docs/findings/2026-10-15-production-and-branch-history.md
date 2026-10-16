# Production progression and branch inventory, 2026-09-27 to 2026-10-12

Moved verbatim from [SYSTEM](../SYSTEM.md) on 2026-10-15 so that SYSTEM describes current
deployed state only. Each line keeps the date it was observed; nothing here was re-checked on the
appliance when it moved.


The [retention inventory](../branches.json) records the later GitHub branch audit. The rows below
retain their dated historical context; neither inventory assigns work or establishes deployment.

Production progression is historical evidence, not an instruction to synchronize to main:

- 2026-09-27: `7581baa`, shell and arcade AP fix; Party Core was present as source but inactive
  ([finding](2026-09-27-production-deploy.md)).
- 2026-09-28: Party `15f6322`, BLUFF listed in Party Home; Games `c6199be`.
- 2026-09-29: Party Core deployed and restart/rollback checked at `6bd5af4` / `b345b6d`,
  Games `eeedb19` ([finding](2026-09-29-party-core-deploy.md)).
- Later that day: Party `0e97c2e`, Games `03df5ae` for AVR-128/134
  ([finding](2026-09-29-avr128-134-deploy.md)), then Party `956b968`, Games `c6d7b52`
  for AVR-129 ([finding](2026-09-29-avr129-deploy.md)).
- 2026-09-29 evening to 2026-10-02: the checkout stood at Party `a32b7b4` (merge of PR #29, 20:00 PDT) and
  Games `0b4e9d2` when the AVR-130 finding read the Pi; **no finding records the deployment that put them
  there**. That finding ([2026-10-02-avr130-deploy](2026-10-02-avr130-deploy.md)) stages the next
  deployment and records no after-state.
- 2026-10-06: Party `c59f1c8`, Games `a448972`, deployed 2026-10-06T21:10:48Z by `ops/deploy.sh`, smoke passed
  at 21:10:51Z, restarting `avrana-party-core`, `avranaparty-arcade` and `avranaparty-games`. Evidence: the
  deployment manifest as reported by `/party/api/status` on 2026-10-12
  ([baseline](2026-10-12-deployed-baseline.md)). **No dated deployment finding exists** for the
  deployments between 2026-09-29 and 2026-10-06, nor for this one.
- 2026-10-09 22:59 PDT: an unrecorded reboot, observed after the fact (baseline); all units were active
  afterwards with Ethernet present. Not an offline-boot proof.

Party Core `avrana-party-core` runs at 127.0.0.1:8191 behind nginx `/party/api/`.
BLUFF is granted and listed in Party Home. Experiment rows below retain the 2026-09-27 branch
inventory; the source revision table above governs current main observations.

| Branch | Where | What | Status |
|---|---|---|---|
| `main` | GitHub + Pi production | current source/code/tests; the Pi holds a separately deployed revision | canonical |
| `docs/party-platform` | GitHub | history of the docs now on `main`, plus raw power-measurement evidence that stays out of `main` | park (archive) |
| `experiment/party-service` | GitHub + Pi worktree `~/avrana-lab/party-svc` | party service, device identity, membership, host, presence, lifecycle, manifest v0, service-game launcher (PS1) + seat tickets v1, Party Home reconnect (includes the deleted `fix/party-home-reconnect`) | park: source evidence for Party Core, **not** for a wholesale merge |
| `experiment/party-sim` | GitHub | `experiments/`: party lifecycle model, viewport geometry, Personal Viewports PoC | park (research) |
| `experiment/ps1-title-profiles` | GitHub + Pi dev/test checkout | current PS1 line: title profiles, token-in-hello, Leave, supervised runs, party mode, `--viewports` | park (R&D) |
| `ps1-emulation` | GitHub | older PS1 shared-stream base (superseded by `experiment/ps1-title-profiles`) | park (history) |
