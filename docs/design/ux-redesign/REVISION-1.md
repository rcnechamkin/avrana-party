# UX/UI redesign: revision 1 after the first owner review

Status: **PROPOSED (2026-10-05). Design revision; the owner approved its visual direction on 2026-10-05. Nothing here is implemented by this document.**

The owner kept the shell direction and asked for six gaps to be closed before final approval.
This file says what was found, what was done about it, and what is still limited. The owner
then approved the direction and asked for a cleanup pass: see [REVISION-2](REVISION-2.md), which
supersedes rows 4c and 6d, the result buttons in row 1 and the Host rule in row 6b. It changes
prototypes, screenshots and design documents only. The rest of the package is indexed in the
[README](README.md).

## Where to look

Overview sheets, four screens each, in `screenshots/`:

| Sheet | Shows |
|---|---|
| [overview-1-shell](screenshots/overview-1-shell.png) | Home, Party, Library grid (now unfiltered by default), Library list |
| [overview-2-game-and-states](screenshots/overview-2-game-and-states.png) | game detail, briefing, the tightened Limited notice, the Host-only notice |
| [overview-3-expo](screenshots/overview-3-expo.png) | EXPO with the field-unit treatment: your turn, waiting, burst, result |
| [overview-4-expo-large-hands](screenshots/overview-4-expo-large-hands.png) | 14 cards at 360 × 640 and 390 × 844, playing for Tonoja at 390 × 664, 14 cards with a burst open at 360 × 640 |
| [overview-5-expo-results-objectives](screenshots/overview-5-expo-results-objectives.png) | the result at 360 × 640 and, scrolled, at 390 × 664; the objectives sheet at 360 × 640 in play and during a burst |
| [overview-6-library-unavailable](screenshots/overview-6-library-unavailable.png) | the filtered Library, the Library on a Limited phone, detail on a Limited phone, detail with the arcade off |
| [overview-7-missing-states](screenshots/overview-7-missing-states.png) | reconnecting on Home, the Host away on a briefing, a search with no match, reconnecting in EXPO |
| [overview-8-enlarged-text](screenshots/overview-8-enlarged-text.png) | 200% text: briefing and Library at 360 × 640, EXPO at 390 × 844 and 360 × 640 |

Every revision picture is in `concepts/`, kept outside Git ([README](README.md#pictures-that-are-not-in-git)), with a name starting `r-` (111 pictures;
the 60 from the first package were re-taken). The live review board, `prototypes/index.html`,
has a new wall, "Revision 1: the demanding cases".

## Findings, resolutions, limits

| # | Finding | Resolution | Evidence | What is still limited |
|---|---|---|---|---|
| 1 | EXPO result lost objective outcomes on short screens: all of "The rest" at 360 × 640, all but one at 390 × 664 | The board's folding rule leaked into the result. It is now scoped to the gameplay board. The result keeps every outcome at every size; the evidence scrolls and the actions stay pinned. A success verdict is drawn too | `r-expo-result-failed-*` (four sizes), `r-expo-result-failed-end-*`, `r-expo-result-success-*`, `r-expo-result-guest-*` | Landscape result is two columns and only sketched |
| 2a | Only an 8-card hand was shown; real hands reach 13 and 14 | Hands of 10, 13 and 14 drawn from the engine's real deals. Above ten cards the hand is rows of seven. Every card is a target of at least 44 px at all four sizes | `r-expo-hand-10-*`, `r-expo-hand-13-*`, `r-expo-hand-14-*`, `r-expo-hand-14-waiting-*`, `r-expo-hand-14-burst-*`; the table in [SCREENS](SCREENS.md#expo-layouts-measured-revision-1) | At 360 px cards are 44.6 px wide: 0.6 px of margin. Measured by script in a desktop browser, not on a phone |
| 2b | The two-player game with Tonoja was not shown | Tonoja has a seat that is plainly not a person; a "Yours / Tonoja" switch sits above the hand; Tonoja's face-up cards, empty places and a covered count are shown; the status line and the Play key say when you are playing for Tonoja | `r-expo-two-yours-*`, `r-expo-two-tonoja-turn-*`, `r-expo-two-peek-tonoja-*`, `r-expo-two-burst-*` | Under 760 px of height no objective row stays on the board in this mode. The view does not say which columns still hide a card, so covered cards are a count (D8). "Tonoja" is today's word; its name in the fiction is open |
| 2c | No way was shown to read every objective on a short screen, or during a burst | The objectives header is a control ("See all 4"). It opens the whole list as a sheet over the upper board that stops at the tray, so the hand and the dock stay in use. It works during a burst, with 14 cards, with two players, and scrolls for a long list | `r-expo-objectives-sheet-*`, `-burst-*`, `-burst-14-*`, `-long-*`, `-long-end-*`, `-two-*` | The sheet's focus handling is specified, not built. During a burst on short screens the board itself shows no objective; the sheet is the only way |
| 2d | "The board fits" was claimed beyond what was shown | The claim is replaced by a measured table for hands of 8, 13 and 14 and two players at 360 × 640, 390 × 664, 390 × 844 and 844 × 390, with what each case costs | [SCREENS](SCREENS.md#expo-layouts-measured-revision-1) | The fixed board has a floor just under the smallest tested size: about 600 px of height for three to five players, 630 px for two, 350 px of width for 14 cards. Below it the board falls back to a scrolling column (`r-expo-below-floor-*`), which was looked at in three pictures and not measured. Landscape passes the measure and is still a sketch. Task selection, distress and the in-game setup are not drawn |
| 3 | The default Library showed a filter badge and "4" selected while listing all seven games | Recommending and filtering are separated. Default: no badge, Players at "Any", all seven shown, grouped "Great for four" and "Not for four". A separate filtered state: the control, the badge, the heading, the sheet's button and the results all say five, with Reset beside the results and "2 games hidden by this filter. Show all" | `03-library-grid-*`, `x-library-filters-*`, `r-library-filtered-*`, `r-library-filtered-list-*`, `r-library-filtered-sheet-*` | Only the Players filter is wired in the prototype; the other controls are drawn |
| 4a | Limited and degraded consequences stopped at Home | They now appear under the affected titles in the Library (medium, large, list) and as a line on the game's detail page, and they compose. On detail the Host's button stays when others can still play and is unavailable, with the reason, when the game is off | `r-library-limited-*`, `r-library-limited-list-*`, `r-library-degraded-*`, `r-library-degraded-guest-*`, `r-library-limited-degraded-list-*`, `r-game-worms-limited-*`, `r-game-gauntlet-limited-*`, `r-game-gauntlet-degraded-*`, `r-game-gauntlet-degraded-guest-*`, `r-game-gauntlet-limited-degraded-*`, `r-briefing-gauntlet-limited-*`, `r-briefing-gauntlet-degraded-*` | The compact grid has no text line and shows nothing. Showing "Off for now" to non-Hosts is a reading the concept picked (decision 15) |
| 4b | The Limited notice was five lines | Three lines at 390 px and four at 360 px, plus one link, keeping all three required facts: not private, what this phone cannot play, how Full Mode returns | `06a-limited-phone-*` | The copy names games; today's banner lists missing browser features, which move to System |
| 4c | After folding, the explanation was reachable from Home only | The "Limited" mark is in the top bar of every shell page and the briefing, always leading to the Limited Mode section of System, which shows whenever the phone is Limited | `x-limited-folded-*`, `r-party-limited-*`, `r-library-limited-*`, `x-briefing-limited-*`, `x-system-limited-*` | On a briefing the mark leaves the briefing page; a sheet would be better (decision 16) |
| 5 | EXPO read as a graphite dashboard, not an expedition | One treatment, in CSS: the window as an irradiated dusk behind glass with sight marks and the trick count along its sill; a faint powder-coat grain on the housing, never on cards; Burst Transmission as the one panel built like equipment; the result read against the same land, storm-red or cleared. Cards are untouched and still the brightest things | `07a` to `07d`, `overview-3-expo` | It says "equipment" a little and "dangerous radiated expedition" only faintly: that needs art. The sight marks and the fasteners are decoration. The pylon was first drawn as a post with a crossbar, which read as a grave marker, and was redrawn. No suitable licensed environmental art exists in the repository and none was fetched. The land is flat shapes and the grain is procedural noise; both are stand-ins. The asset need is written down in [SCREENS](SCREENS.md#expo-art-need) |
| 6a | No reconnecting state | Shell: a quiet line, content kept and marked as possibly out of date, then a notice with what to check and "Try again". EXPO: the status line says so, the hand stays, Play and Burst are unavailable with the reason | `r-home-reconnecting-*`, `r-home-offline-*`, `r-briefing-reconnecting-*`, `r-briefing-offline-*`, `r-expo-reconnecting-*`, `r-expo-seat-away-*` | The step from "reconnecting" to "lost" is a client timer the concept invented (decision 18). EXPO promises no pause; today's client silently drops what is sent |
| 6b | No Host-unavailable state | Drawn from the real rule: the Host shows as Away, a briefing says who everyone is waiting for and that hosting passes on, and the hand-over is announced to the new Host and to everyone else | `r-home-host-away-*`, `r-party-host-away-*`, `r-briefing-host-away-*`, `r-home-host-moved-*`, `r-home-host-moved-guest-*`, `r-briefing-host-moved-*` | The copy cannot say when or to whom, because the view carries neither (D9). The rule itself is awkward: 75 s of a sleeping phone loses hosting on Home or a briefing, though never during a round (corrected in revision 2; decision 17) |
| 6c | No empty search or filter results | Both drawn, each naming what was asked for and offering the one action that undoes it; empty Favorites too | `r-library-search-empty-*`, `r-library-filter-empty-*`, `r-library-favorites-empty-*` | Canned in the prototype |
| 6d | Enlarged text unproven; `rem` alone does not prove a fixed-height board | Shell: checked at 150% and 200% at 390 × 844 and 360 × 640; grids drop a column, pairs stack, the briefing dock joins the page; no horizontal overflow and no clipped text found. EXPO: the board becomes a scrolling column with the tray pinned and every objective listed | `r-home-text200-*`, `r-library-text200-*`, `r-library-list-text200-*`, `r-game-text200-*`, `r-briefing-text200-*`, `r-briefing-text200-end-*`, `r-filters-text200-*`, `r-party-text200-*`, `r-home-text150-*`, `r-briefing-text150-*`, `r-expo-text150-play-*`, `r-expo-text200-*` | See "What kind of check this was". EXPO at 200% on 360 × 640 is reachable but cramped (the tray takes 55% to 80% of the height, and at 80% it scrolls inside itself); card ranks do not scale; 125%, 390 × 664 and landscape were not checked; how the product detects the threshold is unspecified |

## Recommendations on the consequential decisions

These are proposals. The reasoning and what each would change in an accepted document are in
[BACKEND-GAPS](BACKEND-GAPS.md#recommendations-on-the-three-consequential-decisions-revision-1).

| Decision | Recommendation | First implementation |
|---|---|---|
| Social access during a briefing | Yes, through the Party control only; no bottom bar, no embedded chat | the control opens the drawer over the briefing; people only until Party-owned chat exists |
| Briefings for Arcade and PS1 titles | Yes, as the second slice | those titles keep going straight to the game, and the detail page says so |
| A Party layer during play | Later | nothing is drawn over a game; decide the geometry and the bridge verbs in an ADR amendment first |

New questions this revision raised are decisions 15 to 20 in
[BACKEND-GAPS](BACKEND-GAPS.md#open-owner-decisions).

## What kind of check this was

| Check | How | What it does not show |
|---|---|---|
| Layout at phone sizes | Chromium on a desktop at 360 × 640, 390 × 664, 390 × 844 and 844 × 390; a script flagged horizontal overflow, clipped boxes, off-screen controls, overlapping zones and targets under 44 px | real phones, Safari, notches and browser bars, thumbs |
| Enlarged text | the root font size scaled to 150% and 200% in the same browser | a phone's own text-size setting, iOS Dynamic Type, Android font scale, zoom |
| Accessibility | contrast computed from the stylesheet; names, roles and live regions read in the markup | any screen reader, switch control, keyboard-only run |
| Unavailable, reconnecting and Host states | static pictures of each state | timing, motion, what happens between states |

Nothing in this package has been tried on a real phone or with assistive technology.

## Revalidation

Two independent checks ran on the revised package. Neither fixed anything; both reported.

**Design validation** (a separate agent that did not build the revision, with its own measuring
script: 288 page loads in Chromium at the four sizes). Verdict: fit for the owner gate after
listed fixes. Heuristic score 31 / 40 (first draft 26, first package 29), no P0.

What it confirmed with its own numbers:

- Result, failed and success, Host and guest, four sizes: four of four outcome rows present
  every time, the Host's buttons or the waiting line on screen, no horizontal overflow.
- Hands of 13 and 14: cards 44.6 × 54, 48.8 × 56, 48.8 × 80 and 59.8 × 46 at the four sizes,
  matching the table. In 64 board cases no card, status line or dock key was clipped, covered or
  off screen, no zones overlapped and no target was under 44 px.
- The objectives sheet, 24 cases: every row reachable, never over the tray or the dock, Close
  44 × 44, Close and Escape work, the hand stays usable underneath.
- The Library agrees with itself in every state; the Limited notice is three lines at 390 px and
  four at 360 px with all three required facts; the Limited mark is on every shell page and the
  briefing; no image file exists in `prototypes/`.

What it found, and what was done afterwards:

| Found | Done |
|---|---|
| An undeclared height floor: zones overlap from about 590 px (620 px with two players) at 375 px wide; a 14-card hand overflows at 320 px wide | Declared in SCREENS, and the board now falls back to the scrolling column below 630 px of height or 350 px of width |
| Two-player trick sizes in the table were the waiting state's | Corrected |
| "About 60%" understated the tray at 200% text on 360 × 640: 55% to 80% | Corrected everywhere |
| The mast in the land read as a cross, and over "Mission failed" as a grave marker | Redrawn as a leaning pylon; the owner should still look at it |
| The dot grille beside "1 burst left" could be read as a level meter | Removed |
| The result's land was close to invisible under its overlay | Overlay lightened on the right; sun and pylon moved clear of the text |
| A briefing for a game that goes off said nothing; a game that cannot be watched showed someone "Watching" | Both drawn (`r-briefing-gauntlet-degraded-*`, `r-briefing-gauntlet-limited-*`) |
| Stale lines in the documents; decision 3 did not name what it reverses; decision 20 did not name its conflict | Corrected |

The fixes in the right-hand column were checked by the author with new pictures. The validator
did not measure them again.

Left as found:

- The fallback below the floor is a picture-level check at two sizes; there the objectives sheet
  covers the tray.
- The sheet does not move focus into itself, and with a long list there is no tappable area
  outside it at 360 × 640.
- On Home in Limited Mode the fourth tile's line is off screen until the row is scrolled.
- First run has no top bar and so no Limited mark.
- The sight marks and the fasteners remain decoration.
- The recommendation for Arcade briefings (second slice) and the drawn flow (briefings for
  Worms and Gauntlet II) describe different slices.

**Repository checks** (a separate verifier): `repo-check`, the generated-asset and catalog
checks, the contract check (Party side), the repo-check unit tests (25) and the offline module
tests (124) all pass. Nothing outside `docs/` changed. Not run: browser suites, the full unit
suite, the cross-repository contract check. One thing to decide before any commit: the
screenshots are about 33 MB (171 concept pictures, 215 pictures of today's UI, 8 overview
sheets) in a repository whose tracked files total about 4 MB.
