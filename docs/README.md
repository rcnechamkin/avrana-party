# Documentation map

Start with [README](../README.md), [CONTRIBUTING](../CONTRIBUTING.md) and [AGENTS](../AGENTS.md).
Authority is scoped to the question, not the newest filename. The machine-readable
[manifest](manifest.json) classifies every Markdown document; it contains metadata, not a
second description of product state. [Linear](https://linear.app/avranakern) alone owns live work.

| Document/category | Purpose and authority | Status / limits | Look here instead |
|---|---|---|---|
| [WORKFLOW](WORKFLOW.md) | The development loop from a Linear issue to a playtested deployment; Linear state mapping; issue structure; what CI enforces | Current reference | [AGENTS](../AGENTS.md) for agent rules; Linear for live work |
| [CROSS-REPO](CROSS-REPO.md) | Branch pairing, paired PRs and what each CI runs against the other repository | Current reference | [Party ↔ Games contract](design/PARTY-GAMES-CONTRACT.md) for the interface itself |
| [Implementation report](agents/IMPLEMENTATION-REPORT.md) | The one completion-report format | Current reference | AGENTS for what Done means |
| [SYSTEM](SYSTEM.md) | Verified deployment/topology | Current reference, observations explicitly dated | GitHub main for source; findings for supporting evidence |
| [TESTING](TESTING.md) | Commands and evidence semantics | Current guide; old counts remain dated results | CI on the actual revision; runbooks for physical checks |
| [ADRs](adr/) | Architectural decisions | Read each actual status and partial amendments | Proposed portions do not override accepted decisions |
| ADRs [0012](adr/0012-limited-mode-party-survives-https-loss.md), [0013](adr/0013-party-and-game-browser-origins.md), [0014](adr/0014-native-games-isolated-lan-games-retired.md) (2026-10-02) | Limited Mode; Party origin vs game origin; isolated native games and LAN Games retirement. They amend ADRs 0002–0006 and 0011 by dated amendment | Accepted direction, **not implemented or deployed** | SYSTEM for what runs today; Linear for sequencing |
| ADR [0015](adr/0015-game-result-envelope.md) (2026-10-03) | Game result envelope v1: what a game reports about how a session finished, and the party's acceptance boundary | Accepted; history and stats are AVR-71 | The ADR for the contract; SYSTEM for what is deployed |
| ADR [0016](adr/0016-service-identities-and-local-trust-boundary.md) (2026-10-03) | Field-test service identities, secret and state ownership, local IPC and what the first appliance outside the owner's hands promises | Accepted, **not implemented or deployed**: every service still runs as one user | SYSTEM for what runs; AVR-236 for the implementation |
| ADR [0017](adr/0017-party-owned-messaging.md) (2026-10-06) | Party-owned messaging: sender identity, one Party room, history, limits, delivery, Limited Mode and the end of the legacy chat (AVR-53) | **Proposed, not accepted**; nothing is built | The shell and Games source for the chat that runs today |
| [Design index](design/README.md) | Product contracts and detailed designs | Mix of canonical contracts and explicitly proposed mechanisms | ADRs resolve decisions; SYSTEM establishes deployment |
| [Game UX contract](design/GAME-UX-CONTRACT.md) | Platform-owned versus game-owned UX: briefing, Ready/Watch/Start, rules access, unavailable-action explanations, interaction floors, system cues, art slots (AVR-56) | Mixed: every rule labelled implemented, accepted or proposed; not validated on phones; changes no machine contract | [UI design system](UI-DESIGN-SYSTEM.md) for the Party theme; [ACCESSIBILITY](design/ACCESSIBILITY.md) for the MUST table; ADRs 0010/0011 for the location model |
| [UX/UI product brief](design/AVRANA-UX-UI-PRODUCT-BRIEF.md) | Owner-approved UX/UI direction for the shell, Library, shared game UX, Arcade and EXPO presentation (2026-10-05) | Accepted direction for the redesign, **not implemented**; its §29 lists what is undecided | UI design system for what source does today; [design skills](agents/design-skills.md) for the tooling |
| [UI design system](UI-DESIGN-SYSTEM.md) | Current source UI contract and build guide | Prototype visual system, not a final brand decision | [Generated sources](GENERATED.md) |
| [ROADMAP](ROADMAP.md) | Strategic direction/milestone outcomes | Current strategy, no assignments | Linear for next task, blockers, acceptance and ownership |
| [Runbooks](runbooks/) | Procedures and verification checklists | Some historical/experimental; no authorization to execute | SYSTEM for state, dated findings for outcomes |
| [Findings](findings/) | Dated observations, measurements and audits | Historical evidence; never a live queue | SYSTEM for consolidated verified deployment |
| [Research](research/) | Substrate/reference candidates | Context only, authority: none | Accepted ADRs and canonical design sections |
| [Platform direction](GAME-PLATFORM-ARCHITECTURE.md), [trust/recovery](OFFLINE-TRUST-AND-RECOVERY.md), [emulation](PERSONAL-VIEWPORT-AND-EMULATION.md), [experience](AVRANA-EXPERIENCE.md) | Broad design direction/product aspirations | Draft/proposed scope as labeled; not a built SDK | ADRs and design index for current contracts |
| [Archive](archive/) | Preserved handoffs/publication drafts | Non-authoritative history | AGENTS and Linear; never execute old next-step instructions |
| [Agent environments](agents/) | Vendor/environment setup differences | Current tooling guidance only | AGENTS for all shared operational invariants |
| [Branch inventory](branches.json) | Retention roles for divergent branches | Dated snapshot, canonical: false | GitHub refs for current source, Linear for active work |
| [Deployment index](../deploy/README.md) | Configuration and operations file map | Source assets; no deployment claim | SYSTEM and relevant runbook |
| [Rebuild runbook](runbooks/rebuild.md) and [appliance inventory](../deploy/appliance-inventory.json) (AVR-32) | What a clean target needs and the order to install it: automated steps, secret handoffs, owner-only actions, phone checks, rollback, and what the repository cannot say | Proposed procedure, **not run on any device**; the simulated rehearsal in the tests is not hardware evidence | SYSTEM for what is deployed; [deploy](runbooks/deploy.md) for a routine release |

## Maintaining the map

Classes: `canonical`, `decision`, `design`, `strategy`, `runbook`, `evidence`, `research`,
`historical`, `archived`. `current` means maintained reference, not deployed or fully built.
Mixed documents use `mixed` and explicit status notes; proposed sections stay proposed.
Manifest `canonical_for` values are unique domain identifiers, not precedence scores.
Only the external Linear authority has `live-work` scope.

Add a manifest entry with each new document. Keep links relative, date findings, and preserve
status banners. Update classification when promoting/archiving work, with evidence and review.
Run `npm run check:repo`; see [REPOSITORY-GOVERNANCE](REPOSITORY-GOVERNANCE.md) for its scope.

Optional manifest fields: `supersedes` (a list of archived/historical documents this one
replaces) and `last_verified` (the date someone last checked the document against code). Both are
validated; an old `last_verified` is reported, never failed.

[Graphify](GRAPHIFY.md) documents derived navigation context only; it adds no authority domain.
