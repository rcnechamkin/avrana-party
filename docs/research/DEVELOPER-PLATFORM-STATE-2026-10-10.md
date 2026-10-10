# State of the developer-platform issues, 2026-10-10

- **Status:** Verified against Linear on 2026-10-10 where stated; otherwise carried over from a 2026-10-09 audit and marked. A point-in-time snapshot that will go stale; Linear is authoritative.
- **Date:** 2026-10-10
- **Sources:** Linear AVR-37, AVR-38, AVR-39, AVR-45, AVR-59, AVR-143, AVR-238, AVR-315, AVR-316, AVR-317 (read 2026-10-10); a 2026-10-09 audit of the same issues (dropped, see below).
- **Related:** `docs/research/AVRGAME-EXPERIMENTAL-DRAFT.md`, `docs/research/DEVELOPER-FRICTION-AUDIT.md`

## Status (read from Linear 2026-10-10)

| Issue | Status | Milestone | Note |
|---|---|---|---|
| AVR-238 Checkers | Done | M6 | Party `defd4a2`, Games `fb711d9`. Real-systemd proof ran on a CI runner, not on the Pi or phones. |
| AVR-37 draft `.avrgame` v0 | Backlog | M6 | Gate text unchanged: drafting after Checkers and its findings exist; no freeze, "even as experimental", until the AVR-27 four-human BLUFF findings are reviewed against the draft in writing and the owner accepts. |
| AVR-38 SDK v0 + Hello Party | Backlog (an experimental slice is on the unmerged branch `feat/avr-38-hello-party-experimental`) | M6 | Must not claim package or SDK shipped, or bypass the Checkers/BLUFF evidence gates. |
| AVR-39 AvrGameProvider validate/install | Backlog | M6 | Must use the AVR-236 `provision-game` path; no second install path. |
| AVR-59 developer workflow | Backlog | M9 | Porting ladder entries are "candidate feasibility", not approved work. |
| AVR-45 owner app, trusted game host, courier | Backlog | M10 | Revised 2026-10-09: first-class commercial readiness requirement; optional for guests; friend-ready 1.0 has no app dependency. Open owner decision: whether retail activation literally requires the app. |
| AVR-143 optional licensed storefront | Backlog | M9 | Decided 2026-10-09: an optional official storefront for licensed games exists alongside open `.avrgame`. Implementation gated on demonstrated demand; not on the 1.0 or prototype critical path. |
| AVR-315 BLE owner pairing and management control plane | Backlog | M10 | Created 2026-10-10. Design only; no phone app, BLE daemon or live Pi changes. |
| AVR-316 licensed publisher delivery and offline entitlement | Backlog | M9 | Created 2026-10-10. Research and architecture contract; commerce is not a 1.0 or Checkers blocker. |
| AVR-317 reconcile canonical and human docs | Backlog | none | Created 2026-10-10. Documentation only. |

## What changed since the 2026-10-09 audit

- The Checkers gate for AVR-37 drafting is satisfied by merge, resolving the earlier ambiguity about whether "exist" meant merged or present on a pull-request branch.
- The freeze gate remains stricter than the drafting gate: AVR-27 BLUFF evidence plus owner acceptance (AVR-37), and Spades boundary validation (ADR 0014 decision 12).
- Commerce and the owner app are now approved direction rather than open product questions. The earlier stance "no commerce work before 1.0" is narrowed to "no commerce or app dependency in friend-ready 1.0 or the native-platform critical path".

## Standing observations still believed true (not re-verified line by line)

- ADR 0014 decision 12 (Checkers and Spades) and AVR-37 (Checkers, then BLUFF humans) state different freeze bars; the stricter should apply to "stable". AVR-312 is a readiness packet, not a port.
- `docs/runbooks/add-a-game.md` routes outsiders to a native path described as having no procedure, while `docs/runbooks/provision-game.md` is a written, not-yet-run-on-Pi procedure. Check whether it has been updated.
- The word "runtime" names three things (ADR 0014 `process` type, the contract's `runtime.type: external`, and the appliance grant `runtime` key). A specification must not reuse it for all three.
- Contract `package` fields are display-only claims until signing exists (`contracts/README.md`); a package cannot assert its own trust tier.
- Games vendors `core/party_protocol.py` and `core/party_result.py` byte-identical with digests in `provider/avrana-contract.json`; the SDK must not expose Avrana internals.
- Open decisions from the Checkers findings (D11-D15) lived in a Games findings note rather than on the issue; whether they were moved is not checked here.

## Dropped from the 2026-10-09 audit

The per-action "what may an agent do" table, the proposed relation changes (P1-P6) and the item-by-item contradictions list were situation-specific working notes tied to unmerged branches and are superseded by the merge and by the revised issues. The Linear issues themselves are the record.
