# Avrana Party and the Design Foundation

Status: **PROPOSED (2026-10-11, AVR-424). A mapping of what is in source to the foundation's names. It changes no token, class or page, and decides nothing the product brief leaves open.**

The [foundation](README.md) names roles and contracts; this file says where Party already
implements each one. The owner-approved direction is the
[UX/UI product brief](../AVRANA-UX-UI-PRODUCT-BRIEF.md); how the shell is built is
[UI-DESIGN-SYSTEM](../../UI-DESIGN-SYSTEM.md). Source read: `origin/main` at `04c5844`.

## Architecture this foundation leaves alone

- The guest experience stays in the browser with nothing to install: static HTML, vanilla ES
  modules, Tailwind CSS 4 and daisyUI 5 at build time only, Lucide icons, one bundled font.
- Everything a guest needs is served by the appliance and works with no internet.
- Games, native games and `.avrgame` packages do not depend on the shell's stylesheet or on
  whatever framework a future owner app uses
  ([GAME-UX-CONTRACT](../GAME-UX-CONTRACT.md) owns that boundary).
- A Flutter owner app is a candidate only; its feasibility finding and prototype are a separate
  change under AVR-424 (`experiments/owner-app-flutter/`).

## Colour roles

| Foundation role | Party token (`web/src/party.css`) | Value |
|---|---|---|
| `surface` | `--color-base-100` (Concept K `ink`, AVR-706) | `#121214` |
| `surface_low` | `--color-base-200` | `#161618` |
| `surface_raised` | `--color-base-300`, `--color-neutral` | `#1e1e21` |
| `on_surface` | `--color-base-content` | `#edeae4` |
| `on_surface_muted` | `--color-muted` | `#aeaba7` |
| `on_surface_faint` | `--color-faint` | `#8f8c89` |
| `outline_quiet` | `--color-line` | white at 9% |
| `outline_control` | `--color-control` | `#6e6c72` |
| `outline_strong` | `--color-line-strong` | white at 18% |
| `action` / `on_action` | `--color-primary` / `--color-primary-content` | `#edeae4` / `#121214` |
| `accent` | `--color-secondary`, `--color-accent` | `#b9a9e8` |
| `selected` | `--color-select` | accent at 16% |
| `focus_ring` | `:focus-visible` in the base layer | 2px accent, 2px offset |
| `status_ok` / `warn` / `error` / `info` | `--color-success` / `warning` / `error` / `info` | see `tokens.json` |
| `scrim` | `::backdrop` of the drawer and sheets | `rgb(4 4 6 / 0.6)` |
| Party only | `--color-material`, `-solid`, `-edge` | the smoky violet of bars, drawer and sheets |

**One difference to settle.** The approved direction names `#1e1e21` as the raised surface.
Source uses two steps: `#161618` for tiles and notices and `#1e1e21` for fields and selected
segments. The foundation records both (`surface_low`, `surface_raised`) and changes neither.
Whether the shell keeps two steps or moves to one is an owner decision.

Copies of the palette outside the stylesheet, to change together with it: `theme-color` in
`web/party/index.html`, `diag/index.html` and `doorway/index.html`, and two entries in
`web/party/manifest.json`. The Games repository's pre-game layer still carries the earlier palette
(AVR-291).

## Type, space, shape

| Foundation | Party today |
|---|---|
| brand | `--font-brand`, Plus Jakarta Sans weight 300, the words "Avrana Party" only (Concept K dropped the Helvetica treatment, 2026-10-21) |
| headline 1.75rem | `.avrana-lede`, a game's `h1`, the briefing's `h2` |
| title 1.375rem | `.avrana-top-title` |
| section 1.0625rem | `.avrana-sec h2`, `.avrana-section-title`, sheet headings |
| body 0.9375rem | `body` |
| supporting 0.8125rem | `.avrana-helper`, list values, counts |
| caption 0.6875rem | bar labels, `.avrana-tag` |
| space scale | written as rem multiples of 0.125; most gaps already land on 4, 8, 12, 16 |
| compact window | the design target; at 44rem (704px) the same column is centred, max 42.5rem |
| control radius | `--radius-field`, `--radius-box` 0.625rem; marks 0.25rem; sheets 1.125rem |
| targets | `--size-field` gives 48px controls; 44px floor is tested |

## Contracts already met

| Foundation section | Where |
|---|---|
| bottom navigation, `aria-current`, focus to the title on change | `.avrana-nav`, `lib/frame.js` |
| dialog, sheet and drawer as native `<dialog>` with `showModal()` | `.avrana-drawer`, `.avrana-sheet` |
| selected is two cues plus `aria-pressed` | `.avrana-choice`, `.avrana-seg`, `.avrana-avatar-choice` |
| disconnected in two steps, last-known content kept | `lib/states.js`, `renderLink` |
| degraded says what still works; a title stays listed with a reason | `renderBox`, the Library's consequence line |
| empty says why and the way back | `.avrana-blank` |
| reduced motion and more contrast | base layer media queries |
| automated contrast, names, order, targets, Tab walk, 200% text, planted faults | `tests/lib/a11y.ts`, `tests/offline/a11y.spec.ts`, `tests/party/a11y.spec.ts` |

Where source differs from a contract, the
[2026-10-11 audit](../../findings/2026-10-11-design-foundation-party-ux-audit.md) lists it.
