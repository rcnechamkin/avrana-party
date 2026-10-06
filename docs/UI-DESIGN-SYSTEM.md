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
The brand face is **temporary** (the brief's Helvetica-style treatment); no final logo or art
direction is decided here. When the real identity arrives, replace the theme block and the
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
| `base-100` | `#0d0d0f` | the ground: near-black neutral, never pure black |
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

Type: **Geist** (SIL OFL 1.1), one variable file bundled at `web/party/fonts/` and served by the Pi
like every other file (provenance: `assets/vendor/README.md`); the system face shows until it loads
(`font-display: swap`) and if it never does. The words "Avrana Party" alone use the `brand` face:
a light Helvetica where the phone really has one (`local()` only, so Android and Windows never
fall back to Arial), Geist Light elsewhere. Sizes are rem, so they follow the phone's text size;
body is 0.9375 rem; supporting lines (a sender's name in chat, a value on a list row, counts) are
0.8125 rem; the bottom bar's labels and the word tags are 0.6875 rem, the floor.
Light mode was dropped with the prototype system; `prefers-contrast: more` and
`prefers-reduced-motion` are honoured. Transitions are 150 ms, colour/border only, plus a chevron
turn.

## Components

daisyUI where it is semantic (`btn`, `input`, `select`, `file-input`, `range`, `loading`,
`skeleton`, `table`); Tailwind utilities for layout; a small `avrana-*` layer for patterns the pages
repeat:

| Class | What |
|---|---|
| `avrana-app` | **the frame** (`#main`): `avrana-top` (the place's title, the Limited Mode mark, the Party control), `avrana-main` (the one part that scrolls) and `avrana-nav` (Home, Party, Library, System); safe-area padding on the bars |
| `avrana-hud` | the Party control: up to three faces and a count; opens the Party drawer. Collapses to one face in a narrow or enlarged-text bar (container query) |
| `avrana-limmark` | the Limited Mode mark in the top bar: icon + the word; opens the "About Limited Mode" sheet |
| `avrana-drawer`, `avrana-sheet` | native `<dialog>`s on the material: the Party drawer (People / Chat, `avrana-tabs`) and a bottom sheet. Opened with `showModal()`, so focus is held inside, Escape closes, and focus returns to the opener |
| `avrana-lede`, `avrana-sub` | Home's sentence about who is here, and the quieter lines under it |
| `avrana-list` | 52 px rows that lead somewhere (a place, a sheet), chevron on the right |
| `avrana-faces`, `avrana-people` | people as faces with names (Party page) and as rows (drawer) |
| `avrana-tag` (`mode`, `quiet`) | a word beside a name: Host, Limited, Away. Words, never colour or an icon alone |
| `avrana-screen` | page container with safe-area padding, for diagnostics |
| `avrana-scene` | one full screen with one thing on it: the way to a game, and the doorway |
| `avrana-brief`, `avrana-dock` | the briefing (a round's setup) under the frame's top bar: what and who scroll, the decision stays at the bottom. Under 32rem of height (512 px, or 1024 px at 200% text) the dock un-pins and the whole briefing scrolls |
| `avrana-lineup` | the briefing's people: a face, the name, the word "Host", and the answer as an icon and a word (Playing, Watching, Choosing) |
| `avrana-choice` | Play this round / Watch this round: two equal buttons; the chosen one has a tick, a fill and a stronger edge (`aria-pressed`), and its words do not change |
| `avrana-back` | the way back in the top bar of a game's page: a chevron and the name of the place it returns to |
| `avrana-surface` | one raised, bordered surface level |
| `avrana-section-title` | section heading with quiet meta on the right |
| `avrana-status` | connection line: spinner while checking, dot + words after (text first, colour never the only cue) |
| `avrana-notice` (`warn`, `quiet`) | something a person should know now, at the top of a page: an icon, a title, one sentence, and at most one action or a Dismiss. `warn` has the amber edge; `quiet` is one line with no surface (Reconnecting) |
| `avrana-state` | one quiet line under a page's lede that says a state in words with an icon (the Host is away; hosting passed on) |
| `avrana-health` (`warn`) | System's opening block: how the Party box and this phone are, in a title and a sentence |
| `avrana-avatar` (`sm`, `lg`) | a person's photo or Gaze avatar (older chat entries: their emoji) |
| `avrana-avatar-choice` | avatar picker cell: ring **and** check badge when chosen, `aria-pressed` |
| `avrana-detail`, `avrana-premise`, `avrana-game-facts`, `avrana-line` (`quiet`, `warn`), `avrana-act`, `avrana-helper` | a game's own page: wide cover, name, what it is, facts as icon and words, whether it suits the people here and this phone, its one button with the heart, and a line saying what the button does |
| `avrana-tools` | the Library's top row: search, the Filters button (with a count of filters that are on) and the View button |
| `avrana-shelf`, `avrana-sec` | the Library's shelves and a shelf's heading (its count, or Reset while a filter is on) |
| `avrana-grid` (`large`, `medium`, `compact`), `avrana-rows` | the four Library views: three grids of covers, and a list of rows |
| `avrana-tile`, `avrana-row`, `avrana-cover` | a title on a shelf: its cover (own art, else its kind icon on its own colour), name, where it is seen, and a warning line when something stands in the way. A link to the game's own page; it never starts one. `wide` on a cover is the 16:9 shape of Home's lead, a game's page and the briefing |
| `avrana-hero`, `avrana-rail` | Home's lead cover, and Home's shelves that scroll sideways inside themselves |
| `avrana-fav` | the heart: keep or drop a favourite (`aria-pressed`, a name per game) |
| `avrana-blank`, `avrana-hid` | the Library with nothing to show (why, and the way back), and the line that says how many titles a filter left out |
| `avrana-seg`, `avrana-choices` | a sheet's choices: segments (one of a few, `aria-pressed`) and a list with a tick |
| `avrana-fit` | what a game means for this phone: icon + words |
| `avrana-empty` | empty state: icon, one sentence |
| `avrana-checks` | checklist rows (this phone) |
| `avrana-table-wrap` | diagnostics tables scroll sideways on phones |
| `avrana-icon` | inline Lucide icon sized to its text |

**The frame and its four places.** `/party/` is one document. Its places are views chosen by
the address's fragment (`#home`, `#party`, `#library`, `#system`; anything else is Home), so
moving between them loads nothing, the phone's Back works, and a reload stays put
(`lib/frame.js`, pure and tested). Changing place moves focus to the title in the top bar and
sets the document title. A game's own page is a fifth view (`#game/<id>`, below); it is not a
place in the bar. **Where the Party is always wins over the frame**: when the Host takes everyone
to a briefing, the middle of the frame and the bar of places give way to it and only the top bar
stays; on the way to a game the whole frame leaves the screen. Whatever was open (drawer, sheet,
rules) closes when the Party moves (to a briefing, to another round's briefing, to a game, or
home), and the frame comes back in the same place, a game's page included.

- **Home**: who is here, in a sentence; the connection line; the Limited Mode notice in full when
  it applies, until it is folded away (below); a nameless phone's first step; then the games: a lead cover (the last title played
  on this phone, else the first that suits the party), a shelf of the rest that suit it
  ("Great for four", or "Games" when there is no party to suit), and "Recently played" once
  something has been.
- **Party**: you (the identity button and its form), everyone here as faces, chat's row.
- **Library**: the games (the centre of gravity): search, two filters, four views, and the
  All / Favorites / Recent tabs (below).
- **System**: how things are, in one block (below); this phone's checklist; the way to
  diagnostics.

The Party drawer (People, and Chat while today's chat exists) opens from the Party control on
any of the four. Today's chat is served by the old games runtime that ADR 0014 retires: it is
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
- **A cover is a link to the game's own page** (`#game/<id>`, PR 1.3). Nothing on a shelf starts
  a game.

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
Limited phone, the Party control): the game's wide art, its name, its premise, the "How to play"
row, then the line-up. A dock at the bottom holds the two choices, the Host's "Start game", one
status line (Party Core's reason for the Host, "Waiting for {Host} to start" for a guest) and the
Host's "Choose another game". There is no bar of places, no Library, no chat and no "This phone"
on it, and no link that leaves it. Who hosts is the word "Host" in the line-up and, for a guest,
the status line; with no Host the line says "Nobody is hosting right now." The separate "You're
the host / Hosted by Ana" line of the older scene is gone.

- **Over it**, the Party control opens the drawer with the people only (no tabs, no chat, a line
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

The brand face (Helvetica-style, per the UX/UI brief), the app icon (`icon.svg`, unchanged), dark-only
theming, the tile layout and the `avrana-*` names. No Party page or script hard-codes a colour; the
copies of the palette outside `web/src/party.css` are `theme-color` in the three HTML heads (the page, diagnostics, the doorway) and
`manifest.json` (updated with the tokens), and the games' pre-game layer and Back to Party bar,
which **still carry the earlier palette's hex values** until the Games repository takes the new
tokens (the redesign plan, follow-up F3).
