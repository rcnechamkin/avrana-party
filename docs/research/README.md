# Research: context, not decisions

- [Open-source substrate candidates](AVRANA-OPEN-SOURCE-SUBSTRATE.md)
- [Reference implementations](REFERENCE-IMPLEMENTATIONS.md)

These documents inform investigation. Their matrices do not accept architecture, install
dependencies, change licenses, establish deployment or assign work. Preserve their status
banners and verify dated upstream claims before reuse. Promotion requires an accepted decision.
Use [ADRs](../adr/), [canonical design](../design/README.md), [SYSTEM](../SYSTEM.md), and
[Linear](https://linear.app/avranakern) for their respective domains.

## Developer platform and owner app (2026-10-10)

Preserved from the 2026-10-09 platform-alpha research and brought into line with the owner direction of
2026-10-09 (Linear AVR-143, AVR-45, AVR-315, AVR-316, AVR-317). These are direction and evidence, never contract.

| Document | Status | Summary |
|---|---|---|
| [State of the developer-platform issues](DEVELOPER-PLATFORM-STATE-2026-10-10.md) | Verified against Linear 2026-10-10 | Snapshot of AVR-37/38/39/45/59/143/238/315/316/317 |
| [`.avrgame` v0 experimental draft](AVRGAME-EXPERIMENTAL-DRAFT.md) | Experimental, not a specification | Field-by-field draft derived from current code; AVR-37 owns the spec; freeze gates listed |
| [Developer friction audit](DEVELOPER-FRICTION-AUDIT.md) | Research (2026-10-09 evidence) | What an outside developer hits today |
| [External-game porting checklist](EXTERNAL-GAME-PORTING-CHECKLIST.md) | Proposal | Handoff checklist, not a validated porting tool |
| [Missing public abstractions](MISSING-PUBLIC-ABSTRACTIONS.md) | Proposal | Ranked gaps from Checkers evidence |
| [Hello Party design note](HELLO-PARTY-DESIGN-NOTE.md) | Historical proposal | Short note; the work is tracked in AVR-38 |
| [Owner app architecture](OWNER-APP-ARCHITECTURE.md) | Proposal | Trust boundaries, BLE/Wi-Fi split, courier, certificates; flags needed ADRs |
| [BLE owner control plane proposal](BLE-OWNER-CONTROL-PLANE-SPIKE.md) | Proposal | Threat model, pairing options, hardware verification plan, gates; input to AVR-315 |
| [Mobile store policy research](MOBILE-STORE-POLICY-RESEARCH.md) | Research, unverified where marked | Apple, Google and web-platform constraints; not legal advice |
