# Avrana UI design system (prototype era)

Status (2026-09-27): **TESTED** offline on branch `chore/ui-design-system`; not deployed.
This is a **temporary, replaceable** visual system that makes the current pages coherent and
pleasant on phones. It is **not** the final Avrana brand: no final logo, palette, typeface or
art direction is decided here. When the real identity arrives, replace the theme block and the
`avrana-*` layer; the markup and the build stay.

## Architecture

```
web/src/party.css ──(npm run build:css: Tailwind CSS 4 CLI + daisyUI 5, dev machine only)──► web/party/styles.css
tools/build-icons.mjs ──(npm run build:icons: lucide-static)──────────────────────────────► web/party/lib/icons.js
                                                        both committed ──► git archive ──► nginx /party/
```

- The pages stay static HTML and vanilla ES modules; there is no bundler, framework or runtime
  build. The Pi never runs Node: `ops/install-party-web.sh` publishes committed files only, so the
  two generated files are **committed**.
- `npm run check:ui` (also in the offline CI lane) compiles into a temporary file and runs the icon
  generator in check mode; it fails when either committed file is stale. Workflow:
  `npm ci` → edit → `npm run build:ui` (or `npm run watch:css`) → `npm run check:ui` → commit.
- Tailwind scans only the files that author classes (listed as `@source` lines in `party.css`).
  daisyUI is limited to the components actually used (`include:` list); add a name there before
  using a new daisyUI component. Output: about 60 KB, about 10 KB gzipped.
- Every generated or new file under `web/party/` must be in `SHELL` in `sw.js` (tested).
- The `/party/` CSP forbids inline styles and scripts: no `style=` attributes, no `<style>` or
  inline `<script>`. A per-element value (a game's accent colour) is set through CSSOM
  (`el.style.setProperty`), which the CSP allows.

## Theme `avrana` (daisyUI custom theme, dark only)

| Token | Value | Use |
|---|---|---|
| `base-100` | `oklch(18.5% .012 285)` | page: deep charcoal, faint violet cast, never black |
| `base-200` / `base-300` | 22.5% / 27.5% | raised surface (panels, tiles) / fields, selected segments |
| `base-content` | `oklch(94% .008 85)` | main text, warm off-white |
| `muted` (Tailwind token) | `oklch(76% .025 290)` | secondary text; ≥ 7:1 on the page |
| `line` / `line-strong` | 33% / 42% | borders; layering comes from borders, not shadows |
| `primary` | `oklch(55% .135 293)` | muted cosmic purple; white text on it passes AA |
| `secondary` / `accent` | dusty lavender 74% / 80% | quiet icon tints, links, focus ring |
| `success`, `warning`, `error`, `info` | subdued green, amber, red, blue | state icons only; never large fills |
| radius | field 0.75 rem, box 1 rem, selector 0.5 rem | buttons and inputs / panels and tiles / small selectors |
| control size | `--size-field: .3rem` → 48 px buttons and inputs | touch targets ≥ 44 px (tested) |
| depth, noise | 0 | flat: no gradients, glass or glow |

Type: system fonts only (no web fonts). Headings use `ui-rounded` where the phone has it (iOS),
else the system face. Sizes are rem, so they follow the phone's text size: screen title 1.75 rem,
section title 1.25 rem, game title 1.19 rem, body 1.06 rem, meta 0.94 rem (never smaller for guest
text). Light mode was dropped with this system; `prefers-contrast: more` and
`prefers-reduced-motion` are honoured. Transitions are 150 ms, colour/border only, plus a chevron
turn.

## Components

daisyUI where it is semantic (`btn`, `input`, `select`, `file-input`, `range`, `loading`,
`skeleton`, `table`); Tailwind utilities for layout; a small `avrana-*` layer for patterns the pages
repeat:

| Class | What |
|---|---|
| `avrana-screen` (+ `avrana-split`) | page container with safe-area padding; from 64 rem wide, a left rail (you, chat, this phone) beside the library; DOM order stays phone order |
| `avrana-surface` | one raised, bordered surface level |
| `avrana-section-title` | section heading with quiet meta on the right |
| `avrana-status` | connection line: spinner while checking, dot + words after (text first, colour never the only cue) |
| `avrana-disclosure` | 56 px disclosure row (chat, this phone) with a turning chevron |
| `avrana-avatar` (`sm`, `lg`) | a person's photo or chosen emoji character |
| `avrana-game-card`, `-cover`, `-title`, `-facts` | game library tile |
| `avrana-fit` | what a game means for this phone: icon + words |
| `avrana-empty` | empty state: icon, one sentence |
| `avrana-checks` | checklist rows (this phone) |
| `avrana-table-wrap` | diagnostics tables scroll sideways on phones |
| `avrana-icon` | inline Lucide icon sized to its text |

Hierarchy on the Party page: connection → **you** (the identity button; a new guest's first step,
outlined in primary) → Party Chat (one quiet row) → **games** (the centre of gravity) → this phone
(tertiary, bottom or rail).

**Buttons.** Primary (`btn-primary`): the one main action of a region: Play, Watch, Save profile,
Send, Try again, Copy report. Secondary (`btn-outline` / `btn-ghost`): Try anyway, Cancel, view
switches, diagnostics tools. Destructive (`btn-ghost text-error` or `btn-outline btn-error`):
Remove photo, Remove offline copy; never filled, so it never competes with a primary action.
Icon-only buttons (the favourite star) always carry an `aria-label`.

**Game tiles.** Only catalog metadata: title; the game's own glyph from its registry on a tile
tinted with the catalog's `accent` (a Lucide kind icon when a game has none; no stock or invented
art); players; screen (`Phone only` / `TV optional` / `Needs the TV` from the contract's `screen`);
how you play when it adds something; summary; fit for this phone; live state; Play. One column on
phones and tablets, two from `xl` (tiles need ≈ 400 px). No ratings, prices or store language. There
is no "selected game" concept in the shell yet, so none is drawn; favourites show as a filled star.

**Icons.** Lucide, generated into `lib/icons.js` (only the listed icons ship; ISC notice in the
file). Use them for navigation, connection, players, screen needs, launch, status, warnings and
close/back. Emoji stay where they are content: players' chosen characters and each game's own glyph.
Static markup uses `<span data-icon="name"></span>` placeholders filled by `hydrateIcons()`;
scripts call `icon(name)`.

## Mobile first

Designed from 360 px up; reviewed at 390×844, 430×932, 768×1024 and 1440×900 with no horizontal
overflow (the Party page test also asserts it). Primary controls are 48 px; nothing depends on
hover; safe-area insets are respected; desktop gets the rail layout instead of stretched tiles.

## Offline rule

Everything a page needs comes from the Pi: no CDN CSS or JS, no Google Fonts, no remote icons or
images, no presentation APIs. Tailwind, daisyUI and Lucide exist only on the development machine.
Verified by logging every request of a Chromium session at four viewports, including the
"Can’t reach the party" state with the browser offline: zero non-local requests.

## System UI and game UI

Avrana supplies the system chrome: Party page, navigation back to it, identity, chat, status,
diagnostics. A game (BLUFF, future Spades, a third-party `.avrgame`) keeps its own presentation and
is **not** required to use this stylesheet, Tailwind, daisyUI or these class names. The shared
ground is the language, not the code: dark calm surfaces, one clear primary action, ≥ 44 px
targets, text-first status, Lucide-style line icons for chrome, reduced motion. BLUFF follows it with
hand-written CSS in the games repository.

## Intentionally temporary

The palette values, the `ui-rounded` heading choice, the app icon (`icon.svg`, unchanged), dark-only
theming, the tile layout and the `avrana-*` names. No page or script should hard-code a colour; the
only copies of the page colour outside `web/src/party.css` are `theme-color` in the two HTML heads
and `manifest.json` (`#121218` = `base-100`).
