# Avrana UI design system (prototype era)

Status reconciled 2026-10-01: prototype system **merged** in Party PR #19 and present in the
verified shell release (SYSTEM). The 2026-09-28 offline branch evidence remains historical;
newer ADR 0011 setup/results UI is merged source with deployment/phone proof pending AVR-212.
**2026-10-05: the UX/UI redesign's slice 1 began in source** (owner-approved direction,
design package and implementation plan under `docs/design/ux-redesign/`, which arrive with the
slice 0 documents PR):
the tokens, the type and the Party shell's frame below are the redesign's; nothing of it is
deployed or checked on a real phone. The diagnostics page and the games still carry the older
layout on the new tokens until their own slices.
**2026-10-21: Concept K · Avrana Console** (owner: "I love the UI") is the direction now being
built, slice by slice (AVR-705; style kit `avrana-console-style/`, Figma section `108:198`). Its
foundations (AVR-706) are below: the ground is `ink #121214`, Plus Jakarta Sans is the only face
(the brand words included), and liquid glass is a single utility for the shell's three floating
controls. No final logo or art direction is decided here. When the real identity arrives, replace the theme block and the
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
  using a new daisyUI component. Output: about 79 KB, about 13 KB gzipped.
- Every generated or new file under `web/party/` must be in `SHELL` in `sw.js` (tested).
- The `/party/` CSP forbids inline styles and scripts: no `style=` attributes, no `<style>` or
  inline `<script>`. A per-element value (a game's accent colour) is set through CSSOM
  (`el.style.setProperty`), which the CSP allows. Artwork SVGs carry no styles or scripts either.

## Theme `avrana` (daisyUI custom theme, dark only)

| Token | Value | Use |
|---|---|---|
| `base-100` | `#121214` | the ground (Concept K `ink`): near-black neutral, never pure black; `#0d0d0f` (`depth`) stays for what sits behind sheets |
| `base-200` / `base-300` | `#161618` / `#1e1e21` | raised surface (tiles, notices) / fields, selected segments |
| `base-content` | `#edeae4` | main text, warm off-white |
| `muted` / `faint` (Tailwind tokens) | `#aeaba7` / `#8f8c89` | secondary text / quiet labels and counts |
| `line` / `line-strong` | white at 9% / 18% | rules between rows; layering comes from lines, not shadows |
| `control` | `#6e6c72` | the edge of anything you can press: 3:1 on the ground and on the material |
| `primary` | `#edeae4` on `#121214` | **ink, not a colour**: the one main action of a region |
| `secondary` / `accent` | `#b9a9e8` (Atomic Purple) | selection, focus ring, links, quiet icon tints; never a fill for a region |
| `material`, `material-solid`, `material-edge`, `select` | smoky violet at 78%, the same violet solid, its edge, the selected tint | the bottom bar is the translucent colour over `backdrop-filter` (a phone without it shows the 78% colour unblurred); the drawer and sheets are the solid colour |
| `success`, `warning`, `error`, `info` | green, `#e6b862`, `#f08a7e`, blue | state icons and marks only, always beside a word; never large fills |
| radius | field and box 0.625 rem, selector 0.25 rem | one radius for anything you press or read in a block; a small one for marks |
| control size | `--size-field: .3rem` → 48 px buttons and inputs | touch targets ≥ 44 px (tested, bars included) |
| depth, noise | 0 | flat: no gradients or glow |

Type: **Plus Jakarta Sans** (SIL OFL 1.1), two variable files (Latin and Latin Extended) bundled at `web/party/fonts/` and served by the Pi
like every other file (provenance: `assets/vendor/README.md`); the system face shows until it loads
(`font-display: swap`) and if it never does. The words "Avrana Party" are Plus Jakarta Sans Light
(`--font-brand`); the temporary Helvetica treatment was dropped with Concept K (owner, 2026-10-21:
Plus Jakarta Sans everywhere). Sizes are rem, so they follow the phone's text size;
body is 0.9375 rem; supporting lines (a sender's name in chat, a value on a list row, counts) are
0.8125 rem; the bottom bar's labels and the word tags are 0.6875 rem, the floor. These sizes are
named type roles in `party.css`'s `@theme` (AVR-425; the Design Foundation's roles): `headline`
1.75, `title` 1.375, `section` 1.0625, `body` 0.9375, `supporting` 0.8125 and `caption` 0.6875 rem,
used as `var(--text-body)` in the stylesheet and `text-body` in markup; write a role, not a
`text-[…rem]` value. A role sets a size only, never a line height.
Light mode was dropped with the prototype system; `prefers-contrast: more` and
`prefers-reduced-motion` are honoured. Transitions are 150 ms, colour/border only, plus a chevron
turn; the stylesheet names them `--motion-quick` and `--ease-standard`. `npm run check:ui` also
fails when a page's `theme-color` or a colour in `manifest.json` is not `--color-base-100`.

**Type roles** (`@theme`, each also a `text-<role>` utility): `caption` 11 px, `supporting` 13 px, `body` 15 px, `section` 17 px, `title` 22 px and `headline` 28 px.
These are the existing names and values on main; the coherence pass does not replace the scale. Weights: 400 to read, 500 for a control's
word, 600 for a name or a heading, 300 for the brand line only. Write a role, not a number.

**What is chosen** looks the same everywhere: the Atomic tint (`--color-select`), a heavier word
and a mark or an edge, with `aria-pressed` or `aria-current`. The bottom bar, `avrana-tabs`,
`avrana-seg`, `avrana-choices` and the avatar picker all follow it.

**Motion** (proposed, AVR-429): `--motion-quick` 150 ms for a state change (colour, edge, a
pressed cover), `--motion-surface` 220 ms for a sheet or the drawer arriving from its own edge,
`--ease-standard` for both. Leaving is immediate. Under reduced motion nothing moves.

### Concept K foundations (AVR-706)

`@theme` also names Concept K's tokens, so code and Figma say the same word. The daisyUI names above
remain what markup uses; these are aliases plus the few the design adds.

| Group | Tokens |
|---|---|
| Colour | `depth #0d0d0f`, `ink #121214` (= `base-100`), `surface #161618`, `raised #1e1e21`, `graphite #5e5b57` (decorative fallback title only, 2.7:1), `ash #8f8c89`, `stone #aeaba7`, `cream #edeae4`, `purple #b9a9e8`, `purple-deep #5a439d`, `purple-selected` (purple at 22%), `ready #34d399`, `warn #f59e0b`, `danger #ef4444` |
| Type roles | `display` 48 Light, `display-fallback` 44 Light, `page` 28 Regular, `shelf` 20 Regular, `button` 17, `secondary` 14, `eyebrow` 12 Medium caps +16%; classes `avrana-display`, `-page-title`, `-shelf-title`, `-eyebrow` (`.selected` is purple), `-meta` |
| Shape | `radius-preview` 20, `-panel` 16, `-button` 14, `-control` 12, `-chip` 8; `spacing-gutter` 16, `-gutter-hero` 20 |
| Motion | tier 1 `--motion-1` 150 ms; tier 2 `--motion-2` 300 ms with `--ease-responsive`; tier 3 `--motion-3` **200 ms** with `--ease-meaningful` (Concept K's 600 ms waits in `--motion-3-proposal` until AVR-704 amends GAME-UX-CONTRACT rule 11.5); the bar's lens uses `--ease-spring` (stiffness 420, damping 28, as `linear()`) over `--motion-spring` 480 ms. Reduced motion shortens tiers 2–3 and the spring to 150 ms, and the base rule still stops every transition. |
| Glass | `.avrana-glass`: ink at 58% over a 28 px backdrop blur, a masked top-lit rim, the drop and inner shadows of Figma's "Liquid glass (dark)". It sets `overflow: hidden` and `isolation: isolate` itself so the blur clips to the element's radius. Without backdrop blur, with `prefers-reduced-transparency` or with `prefers-contrast: more` it is opaque `raised` with a `line-strong` edge. `.avrana-lens` is the selected tab's capsule. **Only three elements may wear glass**: the bottom bar, the top-right utility and the top-left Home button (owner, 2026-10-21). |

Contrast on the new ground (WCAG 2): `cream` 15.6:1, `stone` 8.2:1, `ash` 5.6:1, `control` 3.6:1,
`purple` 8.8:1, `warning` 10.2:1, `error` 7.7:1.

## Components

daisyUI where it is semantic (`btn`, `input`, `select`, `file-input`, `range`, `loading`,
`skeleton`, `table`); Tailwind utilities for layout; a small `avrana-*` layer for patterns the pages
repeat:

| Class | What |
|---|---|
| `avrana-app` | **the frame** (`#main`, Concept K, AVR-707): `avrana-main` (the one part that scrolls) fills the screen and scrolls under the shell's floating controls: `avrana-top` (on Home the `avrana-homebtn` Spire-A Home button, elsewhere the place's title; on the right the `avrana-utility` capsule), and `avrana-nav` (Home, Party, Library, Me) floating 24 px above the bottom. `--avrana-end` keeps the last row 16 px above the bar at the end of a scroll; a dim fades what passes under the bar |
| `avrana-homebtn`, `avrana-utility`, `avrana-nav` | the only three `avrana-glass` elements. The utility holds Search (to the Library's field), Filters and View on the Library, and the Limited mark. The bar's `avrana-lens` slides to `data-at` on a spring; Me shows this phone's avatar; the Party tab carries the chat's unread count |
| `avrana-presence` | the compact presence row: up to five 32 px faces ringed in ink, then "4 here" / "4 here · Riley away". On the briefing it opens the people (only) over it |
| `avrana-limmark` | the Limited Mode mark in the top bar: icon + the word; opens the "About Limited Mode" sheet |
| `avrana-drawer`, `avrana-sheet` | native `<dialog>`s on the material: the Party drawer (People / Chat, `avrana-tabs`) and a bottom sheet (Filters, View, How to play, About Limited Mode), which is a centred panel from 44rem. Opened with `showModal()`, so focus is held inside, Escape closes, and focus returns to the opener |
| `avrana-sub` | a quieter line under a heading (the Host line on the Party page) |
| `avrana-list` | 52 px rows that lead somewhere (a place, a sheet), chevron on the right |
| `avrana-faces`, `avrana-people` | people as faces with names (Party page) and as rows (drawer) |
| `avrana-tag` (`mode`, `quiet`) | a word beside a name: Host, Limited, Away. Words, never colour or an icon alone |
| `avrana-screen` | page container with safe-area padding, for diagnostics |
| `avrana-scene` | one full screen with one thing on it: the way to a game, and the doorway |
| `avrana-brief`, `avrana-dock` | the briefing (a round's setup, Concept K's K1) under the frame's top bar: what and who scroll, the decision stays at the bottom in an opaque dock (glass is the shell's three controls only). Under 32rem of height (512 px, or 1024 px at 200% text) the dock un-pins and the whole briefing scrolls |
| `avrana-stage` (`compact`), `avrana-eyebrow` (`selected`) | the briefing's stage: the game's art under the top row (200–280 px; under 650 px tall it gives its room to the words), "Selected for Party" in purple with a 3 px bar (the game is chosen: Home's "Featured" never looks like this), the name, "2–6 players · Ada hosts" |
| `avrana-panel` | rows in one opaque panel, each a 32 px well and two lines: on the briefing, this phone's own check ("This phone can play" / "can watch" / "Checking this phone", never another phone's) with the fit, then "Playing 2 · Watching 1 · Choosing 1" and who is still choosing by name. On Home's K3, "Round over" |
| `avrana-lineup` | the briefing's people: a face, the name, the word "Host", and the answer as an icon and a word (Playing, Watching, Choosing) |
| `avrana-choice` | Play this round / Watch this round: two equal buttons; the chosen one has a tick, a fill and a stronger edge (`aria-pressed`), and its words do not change |
| `avrana-back` | the way back in the top bar of a game's page: a chevron and the name of the place it returns to |
| `avrana-surface` | one raised, bordered surface level |
| `avrana-section-title` | section heading with quiet meta on the right |
| `avrana-status` | connection line: spinner while checking, dot + words after (text first, colour never the only cue). Connected, secure and not Limited (`data-quiet="true"`): kept for screen readers and not drawn (proposed, AVR-429) |
| `avrana-notice` (`warn`, `quiet`) | something a person should know now, at the top of a page: an icon, a title, one sentence, and at most one action or a Dismiss. `warn` tints the icon amber; `quiet` is one line with no surface (Reconnecting). The one recovery pattern: its action is an outlined "Try again" (lost the Party box, game list unavailable). Limited Mode and System's health blocks are the same hairline box, never a side stripe |
| `avrana-state` | one quiet line under a page's lede that says a state in words with an icon (the Host is away; hosting passed on) |
| `avrana-health` (`warn`) | System's opening block: how the Party box and this phone are, in a title and a sentence |
| `avrana-avatar` (`sm`, `lg`) | a person's photo or Gaze avatar (older chat entries: their emoji) |
| `avrana-avatar-choice` | avatar picker cell: ring **and** check badge when chosen, `aria-pressed` |
| `avrana-detail`, `avrana-premise`, `avrana-game-facts`, `avrana-line` (`quiet`, `warn`), `avrana-act`, `avrana-helper` | a game's own page: wide cover, name, what it is, facts as icon and words, whether it suits the people here and this phone, its one button with the heart, and a line saying what the button does |
| `avrana-tools` | the Library's top row: search, the Filters button (with a count of filters that are on) and the View button |
| `avrana-shelf`, `avrana-sec` | the Library's shelves and a shelf's heading (its count, or Reset while a filter is on) |
| `avrana-grid` (`large`, `medium`, `compact`), `avrana-rows` | the four Library views: three grids of covers, and a list of rows |
| `avrana-tile`, `avrana-row`, `avrana-cover` | a title on a shelf: its cover (own art, else its kind icon on its own colour), name, where it is seen, and a warning line when something stands in the way. A link to the game's own page; it never starts one. `wide` on a cover is the 16:9 shape of a game's page and the briefing; `tall` is the 3:4 cover of Home's rail and the preview's thumbnail; `stage` fills Home's stage |
| `avrana-stage` | **Home's stage** (Concept K K0, AVR-708): the Featured title full bleed under the top row (468 px tall on a 844 px phone, never under 280), its eyebrow ("Featured", `stone`: a recommendation, never styled as "Selected for Party"), its name at display size, one line of facts ("3–8 players · Fits your 4 · Phone only"). Two fixed ink gradients (top 150 px 78% → 0; bottom 300 px 0 → 82% at 55% → ink) keep its words legible over any art. With no picture it is the title's name, 44 Light `graphite`, on `surface` |
| `avrana-stage-actions` | the stage's one primary action (the Host's **Select for Party**, which is today's Host start) and **Preview**. A member who is not the Host has Preview only. Dimmed to 30% and inert while a preview is open |
| `avrana-presence` (`home`) | who is here, in a row under the stage: up to five faces then "+n", "4 here · Riley away", and a purple HOST tag for the Host (dropped under 650 px tall). It opens the Party tab |
| `avrana-rail` (`cards`), `avrana-card` | Home's rail: portrait covers 2.2 to a row; a cover is a button that opens its facts in place (`aria-expanded`), never a page and never a selection |
| `avrana-preview` | a game's facts opened in place, under the stage or under the rail it was opened from: thumbnail, name, facts as chips, this phone's own check ("This phone can play"; an answer not known yet never blocks), the Host's Select, How to play, and "More about <game>" to its page. Focus goes to its title and back to what opened it; Esc, X, a swipe down or the same art again put it away. The art flies between the cover and the thumbnail (a same-document View Transition, tier 2; none under Reduce Motion) |
| `avrana-fav` | the heart: keep or drop a favourite (`aria-pressed`, a name per game) |
| `avrana-blank`, `avrana-hid` | the Library with nothing to show (why, and the way back), and the line that says how many titles a filter left out |
| `avrana-seg`, `avrana-choices` | a sheet's choices: segments (one of a few, `aria-pressed`) and a list with a tick |
| `avrana-fit` | what a game means for this phone: icon + words |
| `avrana-empty` | empty state: icon, one sentence |
| `avrana-checks` | checklist rows (this phone) |
| `avrana-table-wrap` | diagnostics tables scroll sideways on phones |
| `avrana-icon` | inline Lucide icon sized to its text |

**The frame and its four places.** `/party/` is one document. Its places are views chosen by
the address's fragment (`#home`, `#party`, `#library`, `#me`; `#system`, the place's old name, lands on Me; anything else is Home), so
moving between them loads nothing, the phone's Back works, and a reload stays put
(`lib/frame.js`, pure and tested). Changing place moves focus to the title in the top bar and
sets the document title. A game's own page is a fifth view (`#game/<id>`, below); it is not a
place in the bar. **Where the Party is always wins over the frame**: when the Host takes everyone
to a briefing, the middle of the frame and the bar of places give way to it and only the top bar
stays; on the way to a game the whole frame leaves the screen. Whatever was open (drawer, sheet,
rules) closes when the Party moves (to a briefing, to another round's briefing, to a game, or
home), and the frame comes back in the same place, a game's page included.

- **Home** (Concept K K0, AVR-708): the stage (the last title played on this phone, else the
  first that suits the party: Featured), its actions, who is here in a row; the connection line
  when it is not fine; the Limited Mode notice in full when it applies, until it is folded away
  (below); a nameless phone's first step; then the rail of the rest that suit the party ("Also
  fits your 4", or "Games" when there is no party to suit) and "Recently played" once something
  has been. K0 and K3 exist today. **K3 "Just played"** (AVR-709) is the round this tab was
  taken to, once Party Core says the Party is home again (`justPlayed`, lib/party-mode.js): the
  game on the stage, "3 in the Party", a "Round over" panel and who chooses next; the Host has
  **Play again** (today's Host start of the same game) and **Choose another game** (this phone's
  Home goes back to Featured). Nothing about how the round went: "Played by", scores and winners
  need results (AVR-71). K1 on Home (select-then-launch) needs AVR-701 and K2 (Home during a
  round) needs AVR-703; until then K1 is the briefing (below).
- **Party**: everyone here as faces, the Chat row (with the unread count), Leave Party.
- **Library**: the games (the centre of gravity): search, two filters, four views, and the
  All / Favorites / Recent tabs (below).
- **Me** (was System; Concept K, AVR-707): you (the identity button and its form), how things
  are, in one block (below); this phone's checklist; the way to diagnostics.

The Party drawer (Chat, and People) opens from the Party page's Chat row (Concept K retired the
Party control at the top: what is new in the chat is a count on the Party tab). Today's chat is served by the old games runtime that ADR 0014 retires: it is
offered only while that runtime answers, connects only while the drawer's Chat side is on
screen, gives up and says so after six tries in a row (opening the side again tries again), and
when the runtime is gone the control and the row are simply not there
(the redesign plan, "Today's chat and the runtime it depends on").
A phone in Limited Mode has the full notice on Home and the mark in the top bar everywhere else.

**Buttons.** Primary (`btn-primary`, ink on the ground): the one main action of a region: Play, Watch, Save profile,
Send, Try again, Copy report. Secondary (`btn-outline` / `btn-ghost`): Try anyway, Cancel, view
switches, diagnostics tools. Destructive (`btn-ghost text-error` or `btn-outline btn-error`):
Remove photo, Remove offline copy; never filled, so it never competes with a primary action.
Icon-only buttons (the favourite heart, Filters, View, Close) always carry an `aria-label`.

**The Library** (`lib/library.js`, pure and tested; AVR-285). **Recommending is not filtering.**
The number of people at the party orders and groups the shelf ("Great for four", then "Not for
four") and never leaves a title out; only a search, a filter, Favorites or Recent does, and then
the page says so: the heading counts what is shown ("4 games for 4 players") with Reset beside
it, the Filters button carries the number of filters that are on and names them to a screen
reader, and a line under the shelf counts what was left out ("1 game hidden by this filter. Show
all"). Nothing to show always says why and offers the way back.

- **Four views**, chosen in the View sheet and kept on this phone
  (`localStorage['avrana-library-view']`): large, medium (the default) and compact grids, and a
  list. A view changes how much is said per title, never which titles are listed. The compact
  grid drops the plain facts and keeps every warning.
- **Two filters**, in the Filters sheet, and only because the catalog really says both: Players
  (Any, 1 to 5, and 6+, which means a title with room for six or more) and Screens (Any, Phone only, TV optional, Needs the TV: the tiles' own
  words). They are for now, not for ever: a reload starts with every game on the shelf. There is
  no length, kind or "quick start" filter because no title carries that data.
- **A cover's corner** carries the player range, or a warning with words when the party does not
  fit ("Max 2", "Needs 3").
- **One consequence line per title**, the same words in every view, with an icon (never colour
  alone), the most decisive first: `Not installed`, `Off for now`, `Not on this phone`,
  `Watch only on this phone`. A title that is off or not installed stays on the shelf, for
  everyone. "Off for now" needs an answer that says so: a phone whose question got no answer at
  all (out of range, a slow box) says nothing about the game on its cover.
- **Favorites and Recent** are this phone's own lists, the ones the games have always written
  (`lg-favorites`, `lg-recent`). A Party round that takes this phone to a game is added to
  Recent once per round (`localStorage['avrana-recent-round']` holds the last round recorded),
  on a phone that played in it and not on one that watched (the owner, 2026-10-06; Party Core's
  `session.my_role`); held results are not a round.
- **"The party" is everyone in it**, the same number the Party page shows, including someone
  whose phone has gone quiet but who has not left (the owner, 2026-10-06: redesign decision 21).
- **Home never repeats a title**: the lead is not listed again under "Recently played", and a
  shelf with nothing on it has no heading.
- **A cover is a link to the game's own page** (`#game/<id>`, PR 1.3) in the Library; on Home it
  opens the game's facts in place, which link to that page. Nothing on a shelf starts a game: only
  the Host's own button does (Select for Party on Home, Start for everyone on a game's page).

**A game's page** (AVR-286; `detailNodes`, `renderDetail`, `gameOf` in `lib/frame.js`). Browsing
only: the Party stays where it is. The top bar holds the way back, named for the place the page
was opened from ("Library", "Home"); the bar of places keeps that place marked
(`aria-current="page"` on a place the page belongs to, not on the page itself); the game's name
is the page's one heading and takes focus. Where it was opened from is put in its history
entry at the tap itself (`openFrom`), so the phone's Forward and a reload still know, and a Back
pressed at once cannot lose it. Back (the bar's link, the phone's Back or the bar of
places) returns to the same cover at the same scroll. A reload stays on the page; a typed
address has nowhere to return to and its Back is a link to the Library; an address that names no
title on the shelf is the Library. The page shows only what the catalog and the game
supply: the title's artwork, name, the catalog's summary, under it the game's own premise when
its `onboarding.json` has one (asked only of a game served from `/games/<slug>/`; it arrives a
moment after the page and replaces nothing), players, screen (`Phone only` / `TV optional` / `Needs the TV`), how you play
when it adds something, a device-check line where the catalog asks for one, fit for this phone
with its reason, and live state. With a party of two or more it adds one sentence on whether the
game suits them (`fitLine` in `lib/library.js`): "Room for all four of you.", or what happens to
the rest ("Up to 2 play; two of you sit out."; "watch" where the game has a watch view), with a
mark and never colour alone. No length, kind, rating, "quick start" or suggestion is shown,
because no title carries that data.

- **One button, and only the Host's moves the Party.** The Host's button keeps its accepted
  words, "Start for everyone" (ADR 0007), and a line under it says what it does: "Moves everyone
  to this game." While a start is on its way the button says it is busy (`aria-disabled`) and
  keeps its place and the focus. A guest has no button: a sentence says "The host starts it. {Host} chooses what
  the Party plays." (ADR 0009's words first). Outside a party the button is Play, Watch or "Try
  anyway", as it has always been.
- **How to play** is a row on the page when the game ships onboarding; it opens the same rules
  sheet as the briefing. "Got it" there records that the rules were read; closing does not.
- The heart keeps or drops a favourite and keeps focus.
- A start that fails says why at the top of the page, which scrolls into sight.

**The briefing** (ADR 0011 decision 4 and its 2026-10-05 amendment; GAME-UX-CONTRACT rule 3.2;
`#scene`, `renderScene`, `show()`). The lifecycle is unchanged: Party Core decides who is where,
who may start, and why a start waits. Under the top bar ("Getting ready", the Limited mark on a
Limited phone): the compact stage ("Selected for Party", the name, players and who hosts), its
premise, the presence row (with the HOST tag for the Host), the panel (this phone's check and the
fit; who has chosen what), the "How to play" row, then the line-up. A dock at the bottom holds the
two choices, the Host's "Start {game}" (Party Core's blocker sentence under it while it is off), one
status line (Party Core's reason for the Host, "Waiting for {Host} to start" for a guest) and the
Host's "Choose another game". There is no bar of places, no Library, no chat and no "This phone"
on it, and no link that leaves it. Who hosts is the word "Host" in the line-up and, for a guest,
the status line; with no Host the line says "Nobody is hosting right now." The separate "You're
the host / Hosted by Ana" line of the older scene is gone.

- **Over it**, the presence row opens the drawer with the people only (no tabs, no chat, a line
  "Getting ready for {game}."), and the Limited mark opens the explanation without its "Check for
  the full version" link. Both are native modal dialogs: focus goes in and stays in, the briefing
  behind is inert, and Escape, Close or a tap outside gives focus back to what opened it with the
  briefing at the same scroll. Someone's answer arriving does not close them; the Party moving does.
- **A first-timer's Play** opens the rules first ("Got it, I’ll play" is the Play); leaving the
  rules any other way chooses nothing.
- After "Choose another game" each phone is back in the place it was in; the Host is on the
  game's page they started from.
**States** (AVR-287; `lib/states.js`, pure and tested, and `renderLink`, `renderHostNote`,
`renderBox` in `app.js`). Every sentence here is made from what Party Core and the status
endpoint already say; the phone invents one number, and it is the owner's.

- **This phone and the Party box.** A question to the box that fails puts a quiet line at the
  top of the page at once: "Reconnecting. What you see may be out of date." After
  **10 seconds** without an answer (`LOST_AFTER_MS`; the owner, 2026-10-06) it becomes a notice:
  "This phone lost the Party box / Check it’s on the Avrana Party Wi-Fi." with "Try again"; a
  box that answers but refuses says "The Party box isn’t answering / It may be restarting."
  The Host's phone adds "Hosting passes on if it stays away." The phone keeps asking the whole
  time, asks at once when the page is shown again or the network returns, and after a failed
  try does not wait on the box before the next. When an answer comes the notice goes and the
  page is where the Party is, wherever that moved meanwhile. The connection line is not shown
  while the phone is out of touch, so nothing says "Connected" over a stale page.
- **On a briefing** the same two steps are in the dock: "Reconnecting. Your answer stays as it
  is for now." under the choices, then the choices and Start give way to the sentence and "Try
  again", which takes focus when focus was on what gave way. On recovery the choices return and
  focus, if it was on "Try again", goes to the title.
- **The Host is away** (Party Core marks them so after 45 s of silence): the host line says "Ada
  is the host, and is away." and a line under it "Hosting passes to someone here if Ada isn’t
  back soon." on Home and the Party page; the briefing's status line says "Ada, the Host, is
  away, so the game can’t start yet. Hosting passes to someone here if Ada isn’t back soon."
  No countdown and no name for who is next: the view carries neither.
- **Hosting passed on.** The new Host gets a notice with Dismiss, "You’re hosting now / Ada has
  been away, so you pick what the Party plays."; everyone else reads "Bob is hosting now. Ada
  has been away." It is said once and cleared when the Party next moves, or when the phone
  finds itself in a new Party. On a briefing it leads
  the status line ("You’re hosting now. …") and the Host's buttons appear.
- **Never during a round**: a Host who holds a place in the round that is on keeps the role and
  is not shown as away (Party Core's rule), so none of the above appears.
- **Trouble on the box, for the Host only** (ADR 0012; the owner, 2026-10-06). When the status
  endpoint says a part that changes what can be played is off, the Host's Home carries one
  notice, the most serious only: "Arcade games are off right now / Card and party games play as
  usual.", a link "What changed" to System, and Dismiss. Dismissed, it stays away for the visit
  and comes back if the trouble does after a spell of health (losing touch with the box for a
  moment is not a spell of health). If the shelf marks a title off for a reason the box's
  account does not name, the Host gets no notice and System says what the shelf says. Guests never see it: they see
  "Off for now" on the title, as before.
- **System opens with how things are**: "Everything’s working / The Party box and this phone
  are fine.", or what is off. The Host reads the box's own account ("The arcade part of the
  Party box isn’t answering. Gauntlet II can’t be played. Card and party games are not
  affected."); a guest reads only what their shelf already shows ("Gauntlet II is off for now /
  Every other game plays as usual."); a Limited phone reads the three Limited facts.
- **The Limited notice folds** (ADR 0012; the owner, 2026-10-06). Its corner button "Fold this
  notice away" hides it for the visit; Home then carries the mark in the top bar like every
  other page, and the mark opens the same explanation. A new visit shows the notice in full
  again. A phone that cannot keep the choice simply shows the notice.

**Accessibility, checked by the suite** (`tests/lib/a11y.ts`, `tests/offline/a11y.spec.ts`,
`tests/party/a11y.spec.ts`, and the fold in `tests/offline/limited.spec.ts`). On every page, the
Library's sheets and empty states, and every state above: text contrast (4.5:1), the edges of
fields and outlined buttons (3:1), a name on every control, and reading order against visual
order; then the same screen as a phone that asks for more contrast (7:1) and for less motion
(nothing may move) draws it. One top heading, no skipped level, 44 px targets and no sideways
scroll are checked on every Party screen and state by the Party spec, and elsewhere by the
suites that came before it. A Tab walk, with a visible ring required at every stop, covers the
four places, a game's page, the briefing, the drawer, the rules and every state above, and
must reach each state's own button ("Try again", Dismiss, the fold); the Library's sheets and
empty states are not Tab-walked. The checks are first run against planted faults (a dim line, a
nameless faint button, a broken label, a control drawn out of order, a ring taken away,
something moving) and must catch each. This is Chromium: no screen reader, no Safari and no
phone setting has been tried (AVR-295).

- ADR 0011 source uses automatic profile-backed presence and authoritative location; there are no
  normal Join/Leave or Rejoin offers. Game/results own the viewport; host End, Play again and
  Party Home live in game chrome. These console changes await AVR-212 deployment/phone proof.

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

Fallback order: **a cover the owner supplied → the title's own art → curated art that genuinely
depicts it → a generic icon.**

**Implemented, experimental, not deployed (AVR-466 phase C; owner decisions 2026-10-14).** Packages are to be able to bundle
their own artwork, which adds two steps to this order: **owner cover → the package's cover → the
package's icon → the title's own art → curated art → a generic icon.** The shell draws the ladder (`web/party/lib/cover-art.js`; a list row prefers the icon to the cover; a picture that fails to
load falls to the next rung), but a phone is served the images only once the separately gated nginx `/party/pkgart/`
location is deployed; until then each answers 404 and the tile draws what it drew before. The contract is in
[`.avrgame` package, bundled artwork](design/AVRGAME-PACKAGE.md#bundled-artwork-avr-466-experimental).

- **The owner's cover (AVR-306):** a picture the owner has a copy of (box art), one per game,
  **never committed**. It is a file named for the game (`<game id>.jpg`, `.jpeg`, `.png`, `.webp`
  or `.avif`) in one folder: `web/party/covers/` on a development machine (ignored by Git; only
  an empty `index.json` is tracked) and `/srv/avrana/covers` on the Pi, beside the owner's ROM.
  The build and the dev server pass only plain picture files of at most 1 MB with a game-id
  name, never a link, and publish each under the extension of what it really is (a WebP saved
  as `.jpg` is served as WebP); they write `covers/index.json`, which is all the shell reads, so
  a page never guesses at a file (`avrana/web/covers.py`, `loadCovers` in
  `lib/catalog-load.js`). A cover fills a square tile, is shown whole in a wide frame
  (`own-art`), and is decoration (`alt=""`): the name beside it stays text. A cover that does
  not load gives way to the art below, and is not asked for again until the page next starts
  or the Party box answers again after a break.
  Covers are not in the offline copy. How they reach the Pi:
  [deploy runbook](runbooks/deploy.md#game-covers-the-owners-never-committed).

- **A package's cover and icon (PLANNED, AVR-466; not implemented):** WebP, PNG or JPEG, never SVG,
  declared in the package's manifest and validated when it is packed and installed (a declared image
  that is invalid refuses the package). The cover is **1:1** (recommended 512 px, at most 256 KiB)
  and fills the tile as the owner's cover does; the icon is 1:1 (recommended 256 px, at most 64 KiB)
  and is used in list rows and, with no cover, centred on the tile in the existing `icon-art` style.
  The limits are starting values, to be measured on the Pi. Both are decoration (`alt=""`, the name
  stays text), lazy, with width and height set, and give way through the same `onerror` fallback.
  **The owner's cover always wins over a publisher's.** They are served from the Party origin at
  `/party/pkgart/` by a new nginx location (deploying it needs separate owner approval) with no CSP
  change, and are not in the offline copy or the service worker's precache: a phone out of range
  shows the placeholder. The placeholder stays the kind icon and the visible title; no generated
  imagery. A package's banner and screenshots are validated but not shown until a game-page design
  pass; screenshots will need `alt` text.

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

Designed from 360 px up; no horizontal overflow in any of the four places, at 100% and at 200%
text on a 360×640 phone (tested, the frame's scrolling middle included). Primary controls are
48 px, game pre-game options 44 px; nothing depends on hover; safe-area insets are respected. A
wide screen gets the same phone-width column, centred (max 42.5 rem): the earlier desktop rail is
retired, since the product is a phone at a table. Real phones have not checked any of this yet
(the redesign plan, follow-up F4).

## Offline rule

Everything a page needs comes from the Pi: no CDN CSS or JS, no Google Fonts or other remote
fonts (the one font is a committed file in the offline copy's list), no remote icons,
images or avatar services, no presentation APIs. Tailwind, daisyUI, Lucide, DiceBear and the Kenney
originals exist only on the development machine. Verified by logging every request of Chromium
sessions (Party page at four viewports including the offline state; every LAN game's pre-game
screens; a full BLUFF game): zero non-local requests.

## Platform UX and game identity

The behavioural boundary (briefing, rules access, host controls, unavailable actions, system
cues, art slots) is owned by [GAME-UX-CONTRACT](design/GAME-UX-CONTRACT.md). This section keeps
only the visual ownership of the surfaces this system styles.

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

The app icon (`icon.svg`, unchanged), dark-only
theming, the tile layout and the `avrana-*` names. No Party page or script hard-codes a colour; the
copies of the palette outside `web/src/party.css` are `theme-color` in the three HTML heads (the page, diagnostics, the doorway) and
`manifest.json` (updated with the tokens), and the games' pre-game layer and Back to Party bar,
which **still carry the earlier palette's hex values** until the Games repository takes the new
tokens (the redesign plan, follow-up F3).
