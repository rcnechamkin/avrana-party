# Party shell against the Design Foundation, 2026-10-11

Status: **audit evidence (2026-10-11, AVR-424); observations of source at `origin/main` `04c5844` and of the local development server. Design input, not contract. Nothing was changed.**

An audit of the Party shell (`web/party/`, `web/src/party.css`) against the proposed
[Design Foundation](../design/foundation/README.md). It does not repeat the 2026-10-05 redesign
audits under `docs/design/ux-redesign/audit/`; it looks only at where today's source meets or
misses the foundation's contracts. The games' own screens are out of scope.

## Method and limits

- Read: `web/party/index.html`, `web/src/party.css` (656 lines), `web/party/app.js`,
  `web/party/lib/`, `docs/UI-DESIGN-SYSTEM.md`, the product brief, `tests/offline/` and `tests/lib/a11y.ts`.
- Ran: `python -m avrana.web.devserver --port 8180 --party --test-controls` from this checkout and
  opened `/party/` in Chromium at 375 by 812: Home, Library and System with no profile; then
  stopped the server and watched Home for 16 seconds; then reloaded with the server still down.
- Computed: WCAG 2 contrast for every Party colour role against the ground, both raised surfaces
  and the violet material.
- Not done: no real phone, no Safari, no screen reader, no 200% text run by hand (the suite
  covers 200% in Chromium), no Limited Mode run, no briefing or in-game screens.

## What already meets the foundation (keep unchanged)

| Kept | Evidence |
|---|---|
| The frame and its four places; `aria-current`, focus to the title, Back works | `index.html:232-237`, `lib/frame.js`; seen in the browser |
| Native `<dialog>` with `showModal()` for the drawer and sheets | `index.html:242`, `265`, `277`, `306`; `app.js:547`, `1298`, `1331-1332` |
| Two-step disconnect that keeps what was last known | after the server stopped, Home showed "This phone lost the Party box / Check it's on the Avrana Party Wi-Fi." with Try again, hid the connection line, and kept the shelves |
| The offline copy | a reload with the server down drew Home with its covers and the same notice |
| Selected is two cues plus `aria-pressed` | `.avrana-choice`, `.avrana-seg`, `.avrana-avatar-choice` (`party.css:339-344`, `478`, `627-628`) |
| Text-first status; colour never alone | `.avrana-tag`, the Library's "Not installed" line with its icon (seen) |
| Enlarged text handled by container queries measured in text size | `party.css:161-163`, `433-437`, `532`, `538-542` |
| Contrast | every text role is 4.9:1 or better on every surface; `--color-control` is 3.2:1 or better |
| The accessibility suite with planted faults | `tests/lib/a11y.ts`, `tests/offline/a11y.spec.ts`, `tests/party/a11y.spec.ts` |
| Ink as the primary action; Atomic Purple only for selection, focus and links | `party.css:55-61`; seen |
| No remote assets, no inline styles, no bundler | `docs/UI-DESIGN-SYSTEM.md`, "Offline rule" |

## 1. Immediate, low risk

No visible change is intended by any of these; each is checked by `npm run check:ui` and the
existing screenshot and accessibility suites.

| # | Finding | Evidence | Suggested change |
|---|---|---|---|
| 1.1 | Type sizes are repeated as one-off utilities instead of named roles | `text-[0.9375rem]` 18 times and `text-[0.8125rem]` 3 times across `index.html`, `app.js` and `lib/`; `text-lg`, `text-xl`, `text-2xl`, `text-sm`, `text-base` used ad hoc; `party.css` itself writes 11 distinct sizes | name the foundation's type roles as `@theme` text tokens and use them; same pixels |
| 1.2 | Motion values are literals | `150ms ease` in `party.css:335` and `624`; `transition-colors` on `index.html:108` | name one duration and easing token; same values |
| 1.3 | Five copies of the ground colour sit outside the stylesheet with nothing checking them | `theme-color` in `index.html:6`, `diag/index.html:6`, `doorway/index.html:6`; two entries in `manifest.json:9-10` | have `tools/check-ui.mjs` fail when one differs from `--color-base-100` |
| 1.4 | One recovery action is worded differently | "Retry" at `index.html:154`; "Try again" at `35`, `41`, `217` | "Try again" everywhere (a test may pin the word) |
| 1.5 | Nothing ties the stylesheet to the foundation's token file | new in this change | done here: `tests/unit/test_design_foundation.py` compares `party.css` with `tokens.json` |

## 2. Needs a focused design review

Each changes something a person sees or hears, so each needs the owner or a design pass first.

| # | Finding | Evidence | Question |
|---|---|---|---|
| 2.1 | Home shows a healthy connection line with a lock and the word "Secure" | `index.html:58-63`; `app.js:92-96`, `1155`; seen: "Connected to the party" and "Secure" under the lede | the brief (section 13) says healthy state is mostly invisible and TLS is not foregrounded; `UI-DESIGN-SYSTEM` lists the line as part of Home. Hide it when healthy, keep it, or move it to System? |
| 2.2 | The raised surface is two steps where the approved direction names one | `--color-base-200` `#161618` (tiles, notices) and `--color-base-300` `#1e1e21` (fields, segments), `party.css:50-52` | keep two steps (`surface_low`, `surface_raised`) or move to one? |
| 2.3 | Two kinds of bottom sheet | How to play is daisyUI `modal modal-bottom` on `bg-base-200` (`index.html:319-320`); the other three sheets are `avrana-sheet` on the violet material (`265`, `277`, `306`) | move How to play onto `avrana-sheet`? It changes its colour, radius and backdrop |
| 2.4 | The same recovery action is drawn four ways | `btn` (`index.html:35`), `btn btn-primary btn-wide` (`41`), `btn btn-primary` (`154`), `btn btn-block` (`217`) | one rule: outlined inside a notice, primary only when it is the one action on the screen |
| 2.5 | Tabs are drawn as tabs and announced as toggle buttons | `role="group"` with `aria-pressed` buttons for All / Favorites / Recent (`index.html:162-166`) and Chat / People (`245-248`); underline drawn at `party.css:602-603` | keep toggles (simple, tested) or adopt the tab pattern (`tablist`, arrow keys)? Either meets the foundation if chosen deliberately |
| 2.6 | Nine font weights | `party.css`: 100, 300, 400, 450, 500, 550 (22 uses), 600, 650, 750; `font-extrabold` on diagnostics | collapse to four roles (brand 300, body 400, label 550, strong 600)? 650 and 750 would step down slightly |
| 2.7 | Three notice blocks repeat one layout with a coloured left stripe | `.avrana-health` (`party.css:263-270`), `.avrana-limited` (`562-572`), `.avrana-detail .why` (`358`) | one notice component with variants; is the stripe the wanted mark, or icon and title alone? |
| 2.8 | The profile editor is a `<details>` with a hidden `<summary>`, opened by a separate button | `index.html:108-110`; `lib/profile-ui.js:56-60` | the brief has profile recede after onboarding; is a sheet the better home? |

## 3. Future redesign

| # | Opportunity | Evidence | Where it belongs |
|---|---|---|---|
| 3.1 | Medium and expanded windows get the phone column centred; no rail, no landscape layout | `party.css:178-180`, `533-535` | with the TV and landscape shell the brief leaves undecided (section 29); small square handhelds are AVR-332 |
| 3.2 | Sheets and the drawer appear without transition | no transition on `.avrana-drawer`, `.avrana-sheet` | after the owner sets motion timings (brief section 29) |
| 3.3 | Diagnostics and the doorway keep the older layout on the new tokens | `diag/index.html:16-18`; `UI-DESIGN-SYSTEM` status note | their own redesign slice under AVR-281 |
| 3.4 | Games' copies of the platform palette | `UI-DESIGN-SYSTEM`, "Intentionally temporary" | AVR-291 |
| 3.5 | Per-player preferences (text size, contrast, motion, handedness) | `docs/design/ACCESSIBILITY.md`, proposed and not built | its own issue when scheduled |
| 3.6 | Real-phone and screen-reader proof of the redesigned shell | the suite is Chromium only | AVR-295 |

## 4. Reject

| # | Idea | Why not |
|---|---|---|
| 4.1 | Adopt Material Web or Material Components Web components in the shell | Material Web is in maintenance mode with no maintainer; Material Components Web was archived on 2025-01-13. Either adds a runtime dependency and a build step to a shell whose rule is static files and no bundler |
| 4.2 | Rebuild the guest shell in Flutter for the web | guests are browser-first and install-free on the appliance's own Wi-Fi; the shell is about 13 KB of CSS gzipped and plain modules, already tested for offline use, text scaling and screen-reader semantics |
| 4.3 | Material's tonal colour system (tinted surfaces, filled tonal buttons) | the brief: a restrained monochrome shell, never a purple interface |
| 4.4 | Floating action button, elevation shadows | one primary action per region is already docked within thumb reach; the system is flat by decision |
| 4.5 | Replace native `<dialog>` with a script modal library | the browser already gives focus trapping, Escape and focus return, and the suite proves it |
| 4.6 | Replace Lucide with Material Symbols | no gain; the icon build and the semantic-match rule are in place |
| 4.7 | Bring back a light theme | dropped with the prototype system; `prefers-contrast` is honoured instead |

## Existing work this touches

AVR-281 (redesign and its slices), AVR-291 (Games palette), AVR-295 (phone acceptance), AVR-332
(small handhelds), AVR-83 (system layer in games). Section 1 is small enough for one follow-up
issue; section 2 is a set of owner questions, not a backlog.
