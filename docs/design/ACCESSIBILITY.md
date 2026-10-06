# Accessibility: expectations for the platform and every game

Status: **expectations (2026-09-24); partly implemented.** Implemented and tested: the Party Home
page (`experiments/party-service/index.html`, branch `experiment/party-service`) with a browser
smoke test. Audited, fixes proposed but **not applied**: the LAN Games hub and BLUFF (below).

Accessibility is **product infrastructure**, not polish. Avrana has an advantage most party games
don't: every player holds their own screen, so larger text, higher contrast, less motion or haptic
cues can change **for one person** without changing anyone else's game (`NATIVE-GAMES.md` §7).

## MUST — every page a player uses (platform and games)

[GAME-UX-CONTRACT](GAME-UX-CONTRACT.md) §9 applies these rules to the platform/game boundary
(announced turn state, per-device preferences, reduced motion in play) and §11 to system sound
and haptics; it does not restate the table.

| # | Rule | Check |
|---|---|---|
| 1 | Real controls: `<button>`, `<a href>`, `<input>`, `<select>`. A clickable `<div>` needs `role="button"`, `tabindex="0"`, Enter/Space handling and a name — prefer a `<button>`. | every visible control has an accessible name |
| 2 | Every input has a `<label>` (visible, or `aria-label` for icon buttons). Icons inside buttons get `aria-hidden="true"`. | as above |
| 3 | Touch targets ≥ 44×44 CSS px. | automated (Party Home smoke test) |
| 4 | Text scales: never `user-scalable=no` or `maximum-scale=1`; use `rem` for text; the layout must scroll rather than clip at 200 % text. | manual at large system text |
| 5 | Nothing important is conveyed by colour alone: whose turn, eliminated, targetable, host, disconnected also get a word, icon or shape (e.g. badges "Host", "Away", "OUT"). | review + manifest `color_independent` |
| 6 | Prompts that need an answer are announced: a polite live region for status, assertive only for "your turn / answer now". Toasts and connection banners are `role="status"`. | screen reader walk-through |
| 7 | State pushes must not destroy focus: re-rendering keeps (or restores) the focused control. | test: focus survives a push |
| 8 | Honour `prefers-reduced-motion` (no confetti, no pulsing) and `prefers-contrast`. | CSS media queries present |
| 9 | Contrast ≥ 4.5:1 for text (3:1 for large text and control outlines); visible `:focus-visible` outlines. | spot check |
| 10 | No audio-only information. A sound may accompany a cue, never be the cue. | manifest `audio_required` |
| 11 | Player names are text (`textContent`, inside `<bdi>`), never HTML; system messages are a separate element (never a player name). | security + a11y |
| 12 | `<html lang>` set; no sideways scroll at 375 px width. | automated (Party Home smoke test) |

**SHOULD:** a haptic buzz (where the player allows it) when a prompt appears; timers that show
remaining time as text as well as a bar; a way to extend or pause timers for a player who needs it
(game design — record it honestly in the manifest's `timing_pressure`).

## The manifest's accessibility block (display-only in v0)

Each value is `true`, `false` or `"unknown"`; `"unknown"` is always allowed so no author is forced
to guess (`experiments/manifests/`, branch `experiment/party-service`). Nothing filters or blocks
games on these values yet.

| Key | `true` means |
|---|---|
| `color_independent` | nothing needed to play is conveyed by colour alone |
| `audio_required` | a player who cannot hear misses information needed to play |
| `text_scalable` | the game's text follows the player's text size |
| `reduced_motion_respected` | the game honours `prefers-reduced-motion` (and the hub's motion setting) |
| `timing_pressure` | there are deadlines or real-time play a slower player can miss |

Emulated games (arcade, PS1) are honestly `text_scalable: false` and `reduced_motion_respected:
false`: the platform cannot reflow or slow a video frame.

## Per-player preferences (proposed, not built)

Text size, high contrast, reduced motion, haptics on/off, handedness (which side the main buttons
sit) — stored per device now and per saved profile later, applied by the platform's shared
stylesheet and exposed to games as CSS custom properties and `data-` attributes on `<html>`. The
LAN Games hub already has a contrast toggle and a motion setting (`web/hubnet.js`); those become
the seed.

## Audit: LAN Games hub and BLUFF (2026-09-24, fork `main` @ 2cf4831; read-only)

**Hub — mostly good:** dialogs trap and return focus, icon buttons are labelled, targets ≥ 44 px,
visible focus, reduced motion and a contrast toggle. **Gaps:** filter chips and avatar cells show
selection by colour only (no `aria-pressed`); `--faint` text is ~3.4:1; several 9 px labels; toasts
and the RECONNECTING banner are not live regions.

**BLUFF — ranked by impact (fixes proposed as minimal diffs; not applied):**

1. Prompts are never announced ("Your call: challenge or pass?" is visual only, 20 s to answer) →
   a deduplicated live region + optional haptic buzz.
2. Every state push rebuilds the action bar and drops focus to `<body>` → restore focus by a stable
   `data-k` key after render.
3. Targeting a seat, choosing a card to lose and exchange picks are clickable `<div>`s with no role,
   keyboard access or name; cards read their emoji twice; face-down cards say nothing → a
   `tappable(el, label, fn)` helper, `role="img"` labels for cards.
4. Eliminated / targetable / current-turn seats are shown by opacity, a red pulse and a gold ring
   only → an "OUT" chip, a 🎯 badge plus dashed outline, `aria-current`.
5. Unlabelled drawer ✕ and stepper −/+; the drawer doesn't take or return focus.

Lower: fixed-height, `overflow:hidden` layout clips at large text — check on one phone with large
text during the playtest and record what clips. BLUFF uses no sound, so there are no audio-only
cues (`audio_required: false`).

**Platform defaults to extract** (when a second game needs them — see ROADMAP’s product direction):
`Hub.announce(text)` (deduplicated live region), `Hub.tappable(el, label, fn, pressed)`, focus
restore by `data-k` across renders, `.sr-only` and a default `:focus-visible` ring in the shared
stylesheet, `role="status"` on toasts and the connection banner, `aria-pressed` on chips, `--faint`
raised to ≥ 4.5:1 with an 11–12 px floor, one shared reduced-motion rule.

## How to test

- **Automated (per page):** the Party Home Playwright smoke test (`experiments/party-service/
  party.spec.ts`) checks that every visible control has a name, targets are ≥ 44 px, `lang` is set
  and there is no sideways scroll at 375 px, in Chromium and WebKit. Copy the pattern for new pages.
- **Automated (the Party shell, since UX/UI redesign PR 1.4):** `tests/offline/a11y.spec.ts`
  and `tests/party/a11y.spec.ts` run the helpers in `tests/lib/a11y.ts` over every shell page
  and state: contrast, names, headings, reading order, the focus ring on a Tab walk, reduced
  motion, more contrast, targets and sideways scroll. Chromium only; it replaces none of the
  manual pass below.
- **Manual (per release, 10 minutes):** VoiceOver on an iPhone or TalkBack on Android through one
  full round; the largest system text size; reduced motion on; one colour-blindness simulator pass.
