# Avrana UI design system (prototype era)

Status reconciled 2026-10-01: prototype system **merged** in Party PR #19 and present in the
verified shell release (SYSTEM). The 2026-09-28 offline branch evidence remains historical;
newer ADR 0011 setup/results UI is merged source with deployment/phone proof pending AVR-212.
This is a **temporary, replaceable** visual system that makes the current pages coherent and
pleasant on phones. It is **not** the final Avrana brand: no final logo, palette, typeface or
art direction is decided here. When the real identity arrives, replace the theme block and the
`avrana-*` layer; the markup and the build stay.

## Architecture

```
web/src/party.css ──(npm run build:css: Tailwind CSS 4 CLI + daisyUI 5)──────────────► web/party/styles.css
tools/build-icons.mjs ──(npm run build:icons: lucide-static)─────────────────────────► web/party/lib/icons.js
tools/build-avatars.mjs ──(npm run build:avatars: @dicebear/core + styles)──────────► web/party/avatars/*.svg, lib/avatars.js
tools/build-art.mjs ──(npm run build:art: contracts/artwork.json + assets/vendor/)──► web/party/art/*.svg
                                         all committed ──► git archive ──► nginx /party/  (dev machine only)
```

- The pages stay static HTML and vanilla ES modules; there is no bundler, framework or runtime
  build. The Pi never runs Node: `ops/install-party-web.sh` publishes committed files only, so the
  generated files are **committed**.
- `npm run check:ui` (also in the offline CI lane) rebuilds everything above into memory or a
  temporary file and fails when any committed output is stale. Workflow:
  `npm ci` → edit → `npm run build:ui` (or `npm run watch:css`) → `npm run check:ui` → commit.
  `.gitattributes` pins these files to LF so the check is independent of `core.autocrlf`.
- Tailwind scans only the files that author classes (listed as `@source` lines in `party.css`).
  daisyUI is limited to the components actually used (`include:` list); add a name there before
  using a new daisyUI component. Output: about 61 KB, about 10 KB gzipped.
- Every generated or new file under `web/party/` must be in `SHELL` in `sw.js` (tested).
- The `/party/` CSP forbids inline styles and scripts: no `style=` attributes, no `<style>` or
  inline `<script>`. A per-element value (a game's accent colour) is set through CSSOM
  (`el.style.setProperty`), which the CSP allows. Artwork SVGs carry no styles or scripts either.

## Theme `avrana` (daisyUI custom theme, dark only)

| Token | Value | Use |
|---|---|---|
| `base-100` | `oklch(18.5% .012 285)` = `#121218` | page: deep charcoal, faint violet cast, never black |
| `base-200` / `base-300` | 22.5% / 27.5% | raised surface (panels, tiles) / fields, selected segments |
| `base-content` | `oklch(94% .008 85)` | main text, warm off-white |
| `muted` (Tailwind token) | `oklch(76% .025 290)` | secondary text; ≥ 7:1 on the page |
| `line` / `line-strong` | 33% / 42% | borders; layering comes from borders, not shadows |
| `primary` | `oklch(55% .135 293)` = `#765fb8` | muted cosmic purple; white text on it passes AA |
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
| `avrana-avatar` (`sm`, `lg`) | a person's photo or Gaze avatar (older chat entries: their emoji) |
| `avrana-avatar-choice` | avatar picker cell: ring **and** check badge when chosen, `aria-pressed` |
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

**Game tiles.** Only catalog metadata: title; the title's artwork (below); players; screen
(`Phone only` / `TV optional` / `Needs the TV` from the contract's `screen`); how you play when it
adds something; summary; fit for this phone; live state; Play. One column on phones and tablets, two
from `xl` (tiles need ≈ 400 px). No ratings, prices or store language. Favourites show as a filled
star. ADR 0011 source uses automatic profile-backed presence and authoritative location;
there are no normal Join/Leave or Rejoin offers. At home the host chooses a Party game. Setup
is a full-screen Party scene with roster, Play/Watch, How to play and host-only Start (or a
follower’s waiting state). Game/results own the viewport; host End, Play again and Party Home
live in game chrome. These console changes await AVR-212 deployment/phone proof.

## Player avatars

- **Source:** DiceBear style **Gaze** (CC0 1.0, by DiceBear), official preset **Night Shift**
  (`backgroundColor: ['16161a']`, verbatim from dicebear.com/styles/gaze/presets), @dicebear/core
  10.7.0 + @dicebear/styles 10.6.0 (dev dependencies only).
- **Generation:** `tools/build-avatars.mjs` walks seeds `avrana-gaze-1, 2, …` and keeps a candidate
  only when it adds a new shape + body colour pair within per-shape/colour/eye limits, until 32.
  Output: `web/party/avatars/gaze-01..32.svg` (60 KB) and `lib/avatars.js` (ids + unique names such
  as "Green egg" for accessible labels). Deterministic for the pinned versions; never fetched at runtime.
- **Storage:** the donor's own `wc-avatar` key holds the stable id (`gaze-17`), never SVG or a URL.
  A legacy emoji reads as the Gaze avatar at the same position in the donor's former list (unknown →
  `gaze-01`); reads never rewrite storage; the next save stores the id. An uploaded photo still wins.
- **Games:** the games repository vendors the same files (`web/avatars/`, served at
  `/shared/avatars/`). Its `core/looks.py` turns a chosen id into the player's `pfp` (so lobbies,
  cards and chat draw it) and the emoji at the same position as the text `avatar`, for the places that
  print or draw avatars as text. The standalone join picker offers the same 32. Known gaps: ORBIT RIOT
  and WORDCLASH do not send `pfp` in their own player data and still show the text fallback.

## Game artwork

Fallback order: **the title's own art → curated art that genuinely depicts it → a generic icon.**

- **Own art:** each LAN title's GameArt scene (`avrana-party-games` `web/gameart.js`), exported by its
  `ops/export_game_art.mjs` as square, self-contained SVGs (presentation attributes only, frozen) into
  `assets/vendor/lan-games-art/`; `--check` reports drift. 30 titles, 71 KB.
- **Curated:** Kenney Board Game Icons (CC0) only where the icon depicts the game: Gauntlet II
  (sword), Bomberman (explosion). Loose metaphors (a flag for Battleship) were tried and rejected.
- **Generic:** a Lucide kind icon (Worms).
- `contracts/artwork.json` maps game id → `lan:<slug>` or `kenney:<icon>`; `tools/build-art.mjs`
  writes `web/party/art/`; the catalog validates references and emits `artwork`. Provenance:
  `assets/vendor/README.md`.

## Iconography

**Semantic match over stylistic consistency.** An icon must say the right thing first; a consistent
set that says the wrong thing is worse than no icon.

- **System controls** (navigation, connection, sound, photo, TV, status, warnings, close/back): Lucide.
  Party pages: `lib/icons.js`. Games' shared shell: the subset embedded in `web/hubnet.js`, used via
  `<span data-icon="…">` or upgraded in place for controls whose games still write an emoji
  (sound, photo, back). Icon-only controls always have an accessible name.
- **Game art** (roles, coins, pieces, actions, results): the game's own artwork. BLUFF uses one Kenney
  family chosen per concept (`avrana-party-games` `docs/ASSETS.md`).
- **Kept as text:** players' chosen characters where a game has no picture (identity), game notation
  (poker's text suits, orbitriot's ①②③), typographic marks (‹, →, ✓ in words).
- Decoration never breaks behaviour: the games' icon code needs a real DOM and swallows its own errors.

## Mobile first

Designed from 360 px up; reviewed at 390×844, 430×932, 768×1024 and 1440×900 with no horizontal
overflow (the Party page test also asserts it). Primary controls are 48 px, game pre-game options
44 px; nothing depends on hover; safe-area insets are respected; desktop gets the rail layout
instead of stretched tiles.

## Offline rule

Everything a page needs comes from the Pi: no CDN CSS or JS, no Google Fonts, no remote icons,
images or avatar services, no presentation APIs. Tailwind, daisyUI, Lucide, DiceBear and the Kenney
originals exist only on the development machine. Verified by logging every request of Chromium
sessions (Party page at four viewports including the offline state; every LAN game's pre-game
screens; a full BLUFF game): zero non-local requests.

## Platform UX and game identity

| Owned by Avrana (the platform) | Owned by each game |
|---|---|
| Party page, library, identity/avatars, chat, status, diagnostics | gameplay screens, tables, boards, pieces |
| the Back to Party bar and ended-session state (`avrana-integration.css`) | the wordmark and key art on its join screen |
| **the pre-game shell**: every LAN game's `#scr-join` / `#scr-lobby` (who is here, rules, options, the one start/ready button) via the scoped layer at the end of the games' `web/shared.css` | its accent colours inside that shell (e.g. Gridiron's green, FIFTH SIGNAL's teal) and its own state styling |
| system icons and toasts | game art (BLUFF's roles, coins, actions) |

The pre-game layer overrides tokens only inside those two screens and is scoped with
`:root :is(#scr-join, #scr-lobby)`, so it outranks per-game sheets without editing them; gameplay
screens are untouched. A third-party `.avrgame` is **not** required to use this stylesheet, Tailwind,
daisyUI or these class names; the shared ground is the language: dark calm surfaces, one clear
primary action, ≥ 44 px targets, text-first status, line icons for chrome, reduced motion.

## Intentionally temporary

The palette values, the `ui-rounded` heading choice, the app icon (`icon.svg`, unchanged), dark-only
theming, the tile layout and the `avrana-*` names. No Party page or script hard-codes a colour; the
copies of the palette outside `web/src/party.css` are `theme-color` in the two HTML heads,
`manifest.json`, and the games' pre-game layer and Back to Party bar (hex values of the same tokens).
