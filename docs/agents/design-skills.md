# Design skills (Claude Code)

Tooling notes for UX/UI work. This file adds no product direction and no rule: [AGENTS.md](../../AGENTS.md)
holds the repository rules, and the owner-approved
[UX/UI product brief](../design/AVRANA-UX-UI-PRODUCT-BRIEF.md) holds the design direction.
Generic design skills never override the brief.

## What is installed

Everything is project scope, under `.claude/` of the checkout. Only the Avrana skill is tracked;
the third-party skills are gitignored and reproduced by one command, so each checkout or worktree
that does design work runs it once:

```sh
npm run setup:design-skills
```

| Skill | Source | Role | Tracked |
|---|---|---|---|
| `avrana-ux-ui` | this repository, [SKILL.md](../../.claude/skills/avrana-ux-ui/SKILL.md) | Routing and guardrails; sends the agent to the brief | yes |
| `impeccable` | `npx impeccable@4.1.0` ([pbakaus/impeccable](https://github.com/pbakaus/impeccable), Apache-2.0) | One skill, used as `/impeccable <command>`: `init`, `shape`, `critique`, `distill`, `typeset`, `layout`, `audit`, `polish` and others | no |
| `ui-design`, `anti-ui-slop`, `ui-radar` | `https://uizze.com` ([uizze/uizze](https://github.com/uizze/uizze)) | Concepts, slop critique and finish gate, reference research | no |
| `web-design-guidelines` | [vercel-labs/agent-skills](https://github.com/vercel-labs/agent-skills) | Final interface and accessibility review; not a visual identity | no |
| `frontend-design` | [anthropics/skills](https://github.com/anthropics/skills) (Apache-2.0) | Concept-phase craft guidance | no |

The installer is `tools/install-design-skills.mjs`. `skills-lock.json` is ignored on purpose: the
`skills` CLI cannot restore the UIZZE entries from it.

## Things to know before using them

- Impeccable is installed with `--no-hooks`: no detector hook runs after edits. It also places
  four `impeccable-*` subagents in `.claude/agents/` (ignored) and a native engine binary in its
  skill folder. `/impeccable init` writes `PRODUCT.md`, `document` writes `DESIGN.md`, and `live`
  starts a local helper server. None of these has been run; a new root file needs the manifest's
  root allowlist, and `PRODUCT.md` must not become a second product brief.
- `web-design-guidelines` fetches its rules from GitHub at review time, and `ui-radar` sends search
  queries to `uizze.com`. Both need internet; neither runs on the appliance.
- The paid UIZZE MCP is not connected and is not needed. Ignore the upsell line `ui-radar` may add.
- `frontend-design` and Impeccable push toward bold, distinctive choices. In Avrana that energy
  goes into hierarchy, density and restraint as the brief defines them, not into palette or type.
- Reference screens found through `ui-radar` are structure references. The brief forbids
  AI-generated imagery and visual cloning of another product.

## Workflow

Use the smallest relevant set for the phase. Do not invoke every design skill for every task.

| Phase | Use |
|---|---|
| Research and references | `avrana-ux-ui`; `ui-radar`; the existing product, screenshots and components |
| Initial shape and concepts | `avrana-ux-ui`; `/impeccable shape`; `frontend-design`; `ui-design` |
| Critique | `/impeccable critique`; `anti-ui-slop` |
| Refinement | `/impeccable distill`, `typeset`, `layout`, `polish` |
| Final engineering-quality review | `web-design-guidelines`; `/impeccable audit`; `anti-ui-slop`; real-device screenshots and playtest |

Conflict precedence, highest first: the current explicit owner instruction; the product brief;
accepted ADRs and contracts; the `avrana-ux-ui` skill; external design skills; agent aesthetic
preference. When external skills disagree, do not average them: follow the brief and the one
skill that fits the phase.

The first UX phase is design only (brief §27): audit, information architecture and phone-sized
concepts, then stop for owner approval before any large implementation.
