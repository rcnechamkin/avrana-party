---
name: avrana-ux-ui
description: Avrana Party UX/UI guardrails and routing. Use before designing, reviewing or implementing any Avrana UI - the Avrana Party frontend, Party Core UX, Home / Play, Party, Library and discovery, game detail and briefing, chat and the social overlay, Host UI, Limited Mode and degraded states, the Arcade shell, the EXPO frontend and presentation, shared game UI, and accessibility or design review. Points to the owner-approved product brief and says which external design skill fits which phase.
---

# Avrana UX/UI

This skill routes and guards; it holds no product direction of its own. It defers to
[AGENTS.md](../../../AGENTS.md) for every repository rule.

## Read first

Before designing, reviewing or implementing Avrana UI, read the whole brief:

`docs/design/AVRANA-UX-UI-PRODUCT-BRIEF.md`
([open](../../../docs/design/AVRANA-UX-UI-PRODUCT-BRIEF.md))

Its §29 lists what is deliberately undecided. Propose options there; never settle them.
Then read only what the task touches:
[GAME-UX-CONTRACT](../../../docs/design/GAME-UX-CONTRACT.md) (platform versus game),
[ACCESSIBILITY](../../../docs/design/ACCESSIBILITY.md), and
[UI-DESIGN-SYSTEM](../../../docs/UI-DESIGN-SYSTEM.md), which documents the prototype visual
system now in source: a build and behavior reference, not the visual foundation of the redesign.

## Conflict precedence

1. the current explicit owner instruction
2. `AVRANA-UX-UI-PRODUCT-BRIEF.md`
3. accepted ADRs and contracts
4. this skill
5. external design skills
6. agent aesthetic preference

When external skills disagree, do not average them. Follow the brief and use the one external
skill that fits the current phase. A generic skill's taste (bold palettes, distinctive display
fonts, gradients, glass, heavy motion) never overrides the brief. If the brief and an accepted
ADR or contract conflict, stop and ask the owner.

## Non-negotiables (summary; the brief is the text)

- Party is the console; games are the cartridges.
- Playful, inviting, accessible, modern, streamlined.
- Not childish, cutesy, SaaS, sysadmin or generic-AI UI.
- Compact and low-scroll; not one long page of big rounded cards.
- A restrained monochromatic shell. Atomic Purple is a subtle smoky, translucent accent and
  material reference, never a purple interface, and never literal retro styling.
- Type: Helvetica Light for the "Avrana Party" brand text (temporary); Geist for general UI.
- Bottom navigation: Home / Party / Library / System.
- Social, chat and presence are a separate global layer, not a module or an embedded card.
- Healthy technical infrastructure stays mostly invisible; degraded notices state player impact.
- The Host is a representative holding the remote: no crown, king or admin framing.
- The Library is artwork-first and console-style, with several views (grids and list).
- Non-hosts may browse freely; only the Host moves the Party into a game.
- Games that do not fit the current Party stay visible, with a warning at launch.
- Games share accessibility and system behavior; they are not forced into one visual theme.
- EXPO may be rebuilt visually almost completely and must shed LAN Games aesthetics, while
  keeping its five-zone information model (mission stage, crew strip, shared trick, crew
  objectives, private hand and controls).
- No AI-generated imagery, final or placeholder.
- The first UX phase is design only: audit, information architecture, phone-sized concepts.
  Stop for owner approval before any large implementation.

## Which skill, when

Use the smallest relevant set. Do not invoke every design skill for every task: generic advice
drowns out product intent.

| Phase | Use |
|---|---|
| Research and references | this skill; `ui-radar`; the existing product, screenshots and components |
| Initial shape and concepts | this skill; `/impeccable shape`; `frontend-design`; `ui-design` |
| Critique | `/impeccable critique`; `anti-ui-slop` |
| Refinement | `/impeccable distill`, `typeset`, `layout`, `polish` |
| Final engineering-quality review | `web-design-guidelines`; `/impeccable audit`; `anti-ui-slop`; real-device screenshots and playtest |

Installing the external skills and what each is for:
[design skills](../../../docs/agents/design-skills.md).
