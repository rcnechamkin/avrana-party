# Documentation map

Start with [README](../README.md), [CONTRIBUTING](../CONTRIBUTING.md) and [AGENTS](../AGENTS.md).
Authority is scoped to the question, not the newest filename. The machine-readable
[manifest](manifest.json) classifies every Markdown document; it contains metadata, not a
second description of product state. [Linear](https://linear.app/avranakern) alone owns live work.

| Document/category | Purpose and authority | Status / limits | Look here instead |
|---|---|---|---|
| [SYSTEM](SYSTEM.md) | Verified deployment/topology | Current reference, observations explicitly dated | GitHub main for source; findings for supporting evidence |
| [TESTING](TESTING.md) | Commands and evidence semantics | Current guide; old counts remain dated results | CI on the actual revision; runbooks for physical checks |
| [ADRs](adr/) | Architectural decisions | Read each actual status and partial amendments | Proposed portions do not override accepted decisions |
| [Design index](design/README.md) | Product contracts and detailed designs | Mix of canonical contracts and explicitly proposed mechanisms | ADRs resolve decisions; SYSTEM establishes deployment |
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

## Maintaining the map

Classes: `canonical`, `decision`, `design`, `strategy`, `runbook`, `evidence`, `research`,
`historical`, `archived`. `current` means maintained reference, not deployed or fully built.
Mixed documents use `mixed` and explicit status notes; proposed sections stay proposed.
Manifest `canonical_for` values are unique domain identifiers, not precedence scores.
Only the external Linear authority has `live-work` scope.

Add a manifest entry with each new document. Keep links relative, date findings, and preserve
status banners. Update classification when promoting/archiving work, with evidence and review.
Run `npm run check:repo`; see [REPOSITORY-GOVERNANCE](REPOSITORY-GOVERNANCE.md) for its scope.
