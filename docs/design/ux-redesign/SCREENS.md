# Screen concepts: what each one is for

Status: **PROPOSED (2026-10-05, revision 2). Design concepts for owner review; nothing here is implemented or accepted.**

One section per surface. The pictures are kept outside Git, in `concepts/` (see the [README](README.md#pictures-that-are-not-in-git); file names are given per
section; `-390x844` is the main size, `-390x664` and `-360x640` are short-screen checks, and
names starting `r-` were added in [revision 1](REVISION-1.md)) and the
live prototypes are in `prototypes/` (open `prototypes/index.html`). "Today" refers to the
[Party shell audit](audit/PARTY-SHELL-AUDIT.md) and the [EXPO audit](audit/EXPO-AUDIT.md);
backend rows refer to [BACKEND-GAPS](BACKEND-GAPS.md). Game names, lengths and kinds on the
shelves are sample content: Spades and Checkers are not in the catalog, and no title has a
length or a kind today. Art on the concepts is existing first-party or CC0 art and flat CSS
shapes; sources are listed in the [README](README.md#assets-used).

## 1. Home / Play

`01-home-*`, `x-home-guest-*` · `prototypes/home.html` (`?role=guest`)

| | |
|---|---|
| Purpose | Between rounds: who is here, who hosts, what to play next |
| Primary action | Open a game (the last one played, or one that suits the Party) |
| Hierarchy | 1. one sentence: how many are here; 2. names, you, the Host; 3. the last game, large; 4. "Great for four" shelf; 5. "Recently played" shelf |
| Host / everyone else | Same screen. The sentence says "You're hosting" or "Dana is hosting". Nothing on Home launches |
| Responsive | Fits 390 × 844 whole. At 390 × 664 and 360 × 640 the first shelf is visible and the second is a short scroll away. Tablet: centred column |
| Accessibility | Names in `bdi`; the Party control shows three faces and "+1", and its accessible name carries the full count and unread number; covers are links named by their title; seats mark has text |
| States | One person ("Just you so far" with how to join); no history (the hero is the best fit, not "last played"); Limited Mode (section 6); appliance trouble, Host only (section 6); a suggestion arriving (supporting concepts) |
| Changed from today | Today Home is one document about three screens tall with profile, Party panel, chat row, search, filters and every game as a 300 px tile; no complete tile is in the first viewport (PS-1, LIB-2). "Connected", "Secure" and "Profile saved on this browser" are gone (PS-27). Launch buttons are gone from tiles (LIB-12) |
| Backend / state | Existing view for people and Host. Shelf fit from `players`. "You played 25 minutes ago" needs per-device recents (F3) or Party-wide history (D1). Lengths and kinds need R1 |
| Open proposals | The sentence-as-header; whether Home shows "last played" or a recommendation first; per-device or Party-wide recents (decision 9) |

## 2. Party

`02-party-*` · `prototypes/party.html` (`?sheet=profile`)

| | |
|---|---|
| Purpose | The people in the room, and what the Party is doing |
| Primary action | None forced. Look; tap your own face to change your name or avatar |
| Hierarchy | 1. what the Party is doing ("Choosing a game") and who picks; 2. faces with names; 3. state under a name (You, Host, Away); 4. three rows: chat, how to join, hand over hosting |
| Host / everyone else | The Host sees "You pick what's next" and the hand-over row. Everyone else sees who picks |
| Responsive | Three faces across at every phone width; faces shrink on short screens. Six people fit 390 × 844 above the rows; a larger Party scrolls (not drawn) |
| Accessibility | Away is a word, an icon and a dimmed face (today it is opacity only, PS-15). Your own face is a button named "Edit your name and avatar". Tags are text |
| States | Alone; someone away; someone in Limited Mode (a "Limited" tag under the name, ADR 0012 D4); Host away or vacant (not drawn) |
| Changed from today | The roster is pills inside a panel on Home, with a crown for the Host (PS-14). Profile is a permanent block at the top of every visit (PS-7); here it is a sheet you open |
| Backend / state | Existing view. Hand-over uses the existing `POST /party/api/host`; no control for it exists today (PS-20) |
| Open proposals | A deliberate hand-over control at all (PS-20 is an owner question); "Add someone" and "How to join" content (Wi-Fi name, code); whether Limited shows beside a member to everyone (PS-35) |

## 3. Library, medium grid

`03-library-grid-*`, `r-library-filtered-*`, `r-library-filtered-list-*`, `r-library-filtered-sheet-*`,
`r-library-search-empty-*`, `r-library-filter-empty-*`, `r-library-favorites-empty-*` ·
`prototypes/library.html` (`?view=large`, `?view=compact`, `?filter=players4`, `?q=`, `?filter=none`, `?fav=none`)

| | |
|---|---|
| Purpose | Browse everything that can be played, with what suits this Party first |
| Primary action | Open a game's detail page |
| Hierarchy | 1. covers; 2. title; 3. one line (kind, length); seats in the cover's corner. Above: search, filters, view; text tabs for collections; two groups, "Great for four" then "Not for four", so no title appears twice. **Recommending is not filtering**: the Party's size orders and groups the shelf, and nothing is filtered until a person sets a filter |
| Host / everyone else | Identical. Browsing is free for everyone; nothing here launches |
| Responsive | Three covers across (medium), two (large), four (compact, title only). Five across from 700 px. The page scrolls; the top bar and module bar do not |
| Accessibility | A game that does not fit keeps full contrast and gets an amber "Max 2" mark with an icon; it is sorted later, never hidden. Tabs are links with a current state; search has a label; the filter button's name says how many filters are on. At 200% text the grid drops to two columns and the tools wrap (a simulated check, see REVISION-1) |
| States | Default: no filter, no badge, every title shown, Players at "Any". Filtered (drawn for "4 players"): the control shows 4, the button carries a count, the heading says "5 games for 4 players" with Reset beside it, the sheet says "Show 5 games", and one line under the results says "2 games hidden by this filter. Show all". Nothing matches a search: the query stays in the field, with "Clear search". Filters hide everything: the filters are named, with "Reset filters". Empty Favorites. A title that is unavailable on this phone or off for now carries a line under it (section 6). Not drawn: a title that is not installed |
| Changed from today | A single column of 294 to 347 px tiles with 72 px artwork, a people filter that hides mismatches, and a launch button on every tile (LIB-2, LIB-7, LIB-12) |
| Backend / state | Covers for every title (R4). Kind, length and collection tabs need R1. View and filters remembered per device (F2). Fit from existing fields (F4) |
| Open proposals | The tab set (All, Favorites, Recent, Co-op, Versus, Quick, Classics, Arcade); square covers; whether uninstalled titles are listed for players (LIB-22, decision 12) |

## 4. Library, list

`04-library-list-*` · `prototypes/library.html?view=list`

| | |
|---|---|
| Purpose | The same shelf for people who read before they choose |
| Primary action | Open a game; favorite it without opening |
| Hierarchy | 1. title; 2. two-line description; 3. facts with icons and words (players, length, screens); cover at 64 px; favorite at the row's end. One list, "All games, best fit first" |
| Host / everyone else | Identical |
| Responsive | One column at phone width; the description clamps to two lines, the facts wrap |
| Accessibility | Each fact is icon plus words. Mismatch reads "Max 2, you're 4". The favorite is a toggle button with a pressed state and a name per game |
| States | As the grid |
| Changed from today | No list or grid choice exists; favorites exist as a star on the tile |
| Backend / state | As the grid. Favorites are per device (`lg-favorites` exists) |
| Open proposals | Sort order ("best fit first") as the default |

## 5. Game detail and briefing

`05a-game-detail-*`, `05b-briefing-*`, `x-game-mismatch-*`, `x-game-guest-*`,
`x-briefing-guest-*`, `r-game-worms-limited-*`, `r-game-gauntlet-limited-*`, `r-game-gauntlet-degraded-*`,
`r-game-gauntlet-degraded-guest-*`, `r-game-gauntlet-limited-degraded-*`, `r-briefing-gauntlet-limited-*`,
`r-briefing-gauntlet-degraded-*`,
`r-briefing-host-away-*`, `r-briefing-host-moved-*`, `r-briefing-reconnecting-*`, `r-briefing-offline-*`,
`r-game-text200-*`, `r-briefing-text200-*`, `r-briefing-text200-end-*`, `r-briefing-text150-*` ·
`prototypes/game.html` (`?state=briefing`, `?game=expo`, `?role=guest`, `?phone=limited-folded`,
`?box=degraded`, `?host=away`, `?host=moved`, `?net=reconnecting`, `?net=offline`, `?text=200`)

One surface, two moments. The art, title and one-line premise stay where they are; what is
under them changes.

| | Detail (browsing) | Briefing (the Party is here) |
|---|---|---|
| Purpose | Decide whether this is the game. This phone only; the Party stays at Home | Get everyone ready for one round |
| Primary action | Host: "Bring the Party in". Others: favorite, read, (proposal) suggest | Everyone: "Play this round" or "Watch this round". Host: Start game |
| Hierarchy | art; title; premise; three facts (players, length, screens); fit sentence; the action; Quick start; How to play | art; title; premise; the line-up with each person's answer in words and the Host marked by the word; Quick start; one "How to play" row; then, docked: your answer, Start or the waiting line |
| Host / everyone else | Only the Host has "Bring the Party in", with one short line saying what it does to everyone ("Moves everyone to the briefing. Nothing starts yet."). Others see "Dana chooses what the Party plays" | Only the Host has Start, disabled with Party Core's sentence ("Waiting for Sam to choose"). Others see "Waiting for Dana to start" in the same place. The Host also has "Choose another game", in the dock beside the waiting line. The top bar says "Getting ready" and has no back arrow: nobody leaves a briefing alone |
| Bottom bar | present | absent (ADR 0011: the Party is in one place) |
| Responsive | The action is above the fold at 390 × 664 and 360 × 640; Quick start scrolls | The line-up and the dock are always visible; Quick start scrolls under them |
| Accessibility | Facts are value over label; the fit sentence has an icon and words | Each answer is an icon and a word (Playing, Watching, Choosing); your own choice is a pressed button; the blocker is text next to the control |
| States | Fits; does not fit (too many, too few, no watch view; the Host's button stays live and there is no extra confirmation, because whether a launch is refused is Party Core's rule); this phone can only watch it (one line with an icon; the Host's button stays, with "This phone would watch"); the game is off for now (the Host's button is unavailable with the reason beside it; everyone else sees "off for now" and cannot suggest it); reconnecting and out of reach | Nobody has answered; waiting on one person; too many want to play; someone away (does not block); this phone cannot play here (Play disabled with the reason, Watch pressed); a game this phone can neither play nor watch ("Sitting out"); the Host is away (the line-up says Away, Start cannot happen, and the dock says who everyone is waiting for and that hosting passes on); hosting has passed (the new Host gets Start; everyone else is told who hosts now); reconnecting and out of reach |
| Changed from today | There is no detail page. The Host's tile button moves the whole Party at once with no confirmation, and a non-Host's only control is a disabled button (LIB-12, LIB-13) | The setup scene exists and its rules are kept. Changes: crown replaced by the word "Host", answers shown as words not icon-only badges, Quick start on the page. The two choices keep their accepted labels and equal size; the chosen one is marked and reads "Playing this round" or "Watching this round" |
| Backend / state | Length and Quick start are missing (R1, R2). Players, screens, premise exist | All existing: `session/launch`, `choice`, `start`, the blocker sentence |
| Open proposals | The Host's verb ("Bring the Party in"); "Suggest to the Party" (decision 6) | The Party control on the briefing (decision 1); the accepted "Play this round / Watch this round" against the brief's "Ready / Watch" (decision 5); a briefing for games with no pregame (decision 3); whether anyone but the Host has a way out of a briefing (decision 13) |

The mismatch sentence follows the rules that exist: a game with a watch view says how many will
watch; a game without one says who sits out (GAME-UX-CONTRACT rule 4.4a). Whether a launch is
refused is the game's and Party Core's rule, not the page's.

`x-briefing-limited-*` shows a phone that cannot run the game: Play is disabled with the
reason, Watch is already chosen, and the line-up shows it. It uses Worms Armageddon as the
example: a streamed title, which the catalog lets a phone watch, and which has no briefing
today (decision 3).

## 6. Limited and degraded states

`06a-limited-phone-*`, `06b-degraded-host-*`, `x-limited-folded-*`, `x-system-limited-*`,
`x-system-degraded-*`, `x-briefing-limited-*`, `r-library-limited-*`, `r-library-limited-list-*`,
`r-library-degraded-*`, `r-library-degraded-guest-*`, `r-library-limited-degraded-list-*`,
`r-party-limited-*` · `prototypes/home.html?state=limited`, `?state=limited-folded`,
`?state=degraded`, `prototypes/system.html?state=limited`. Every shell page also takes the
composable switches `?phone=limited`, `?phone=limited-folded` and `?box=degraded`

Two different things, treated differently.

| | Limited Mode on this phone | Appliance trouble that changes play |
|---|---|---|
| Purpose | Say what is different on this phone, once | Tell the person who can act |
| Who sees it | That phone, always; the Party sees a "Limited" tag by the member | The notice: the Host only. The "Off for now" line on the affected title: everyone, because a game that cannot start should not look startable (a reading the concept picked; decision 15) |
| Form | One notice on Home with the three facts LIMITED-MODE §3.9 requires, in three lines at 390 px and four at 360 px: "Limited Mode. This connection isn't private. This phone can't play Gauntlet II or Worms. The owner restores Full Mode by renewing the certificate." Then one control, "What this means". Folding it leaves a "Limited" mark in the top bar of every shell page, the briefing included (a warning icon with the word; the icon alone, named for screen readers, under 380 px wide). The notice and the mark are never shown together. The mark and "What this means" open the same sheet over the page that is open (revision 2): the three facts in full, and on a briefing for an affected game, first, what this phone does this round. Nothing navigates, so a briefing keeps its place (`r2-briefing-limited-sheet-*`, `r2-home-limited-sheet-*`, `r2-library-limited-sheet-*`). The System page keeps the same facts as its permanent record | One compact notice on Home: what is off, what is unaffected. Dismissible |
| Primary action | "What this means", and the mark on every page, open the same place: the Limited Mode section of System, which is shown whenever the phone is Limited, folded or not | "What changed" opens System |
| Hierarchy | title; one sentence of impact; link | the same |
| Where the consequences appear | Under each affected title on Home and in the Library (medium and large grids and the list): "Watch only on this phone" for a streamed game that can be watched, "Not on this phone" for one that cannot. On the game's detail page as one line with an icon. On a briefing as a disabled Play with the reason. The compact grid drops its descriptive line and keeps this one, in the same words (revision 2; `r2-library-compact-*`) | Under the affected title on Home and in every Library view, compact included ("Off for now"), and on its detail page, where the Host's button is unavailable with the reason beside it |
| Accessibility | amber plus icon plus words; `role="status"`; the fold button is named | the same |
| Changed from today | A 330 to 375 px banner for every Limited member, not dismissible, leading with transport and certificate (PS-33) | No Host-only notice exists; health words are shown to everyone all the time (PS-27) |
| Backend / state | Existing: `view.mode`, the capability report, seat evaluation (F6) | `/party/api/status` plus `me.host` (F5); impact sentences would be better from the server (D2) |
| Open proposals | Folding instead of dismissing (decision 4). The notice names games where today's banner lists missing browser features; the feature list moves to System. On a briefing the mark leads out to System; a sheet would keep the briefing on screen (decision 16) | Which degraded reasons deserve a notice at all |

Healthy state shows nothing on Home, Party or Library, and one line in System.

## 7. EXPO gameplay

`07a-expo-your-turn-*`, `07b-expo-waiting-*`, `07c-expo-burst-*`, `07d-expo-result-*`,
`x-expo-five-seats-*`, `x-expo-landscape-*`, `x-expo-result-guest-*`, and every `r-expo-*` picture ·
`prototypes/expo.html` (`?state=waiting`, `?state=radio`, `?state=result`, `?ok=1`, `?seats=2|3|5`,
`?hand=10|13|14`, `?hand=tonoja`, `?turn=tonoja`, `?sheet=objectives`, `?goals=7`,
`?net=reconnecting|away`, `?text=150|200`; all compose)

| | |
|---|---|
| Purpose | Play a trick knowing whose turn it is, who is winning it, what the crew still owes, and what you may play |
| Primary action | Choose a card, then "Play blue 6" |
| Hierarchy | 1. whose turn it is and what you may do (the status line on the tray, the amber Turn plate); 2. the trick and who is winning it; 3. your hand; 4. the crew's objectives; 5. mission and counts |
| Direction | A field unit carried through irradiated country. Four things carry it (revision 1): the window, an irradiated dusk behind glass with sight marks and the mission's trick count as a strip of segments along its sill; the housing, powder-coated graphite with a faint grain that never touches a card; the radio, Burst Transmission being the one panel built like equipment; and the result, whose verdict is read against the same land, storm-red or cleared. Cards are flat, full colour and the brightest things on the board. A tuning dial, hazard stripes and a monospace "readout" face in earlier drafts were removed at critique. One typeface, tabular figures. The land is flat CSS shapes and the grain is procedural noise: both hold the place for human-made art (see "EXPO art need" below) |
| Zone 1, mission stage | Mission, trick count, try; the mission's objective as a sentence; rules and the table menu. The trick count is also drawn as one segment per trick along the window's sill (done, now, to come): the same number, nothing new |
| Zone 2, crew strip | Per seat, three lines: avatar and name; the word "Capt" for the Captain and tricks won; burst state as a word ("Ready", "Used") or the card they sent as a small suit-coloured chip with its meaning (a pink "9" chip, then "high"). Turn is an amber plate and a tab with the word "Turn". With five at the table the avatars give way to the names. With two players the dummy hand, Tonoja, has a seat with a stack icon in place of a face, a dashed edge, "You play it", and its face-up and covered counts |
| Zone 3, shared trick | Cards in play order, each over its player's name, the lead tagged. Empty places are outlined; the next one is amber and named. **The current winner has a fixed home**: the line under the trick, "Winning now: Sam, blue 8", and that card is raised and outlined. It is the view's `trick_leading`, nothing computed on the phone |
| Zone 4, objectives | Owner, sentence, and a word only when the state has changed (Done, Failed). The header is a real control, "Objectives, 1 of 4 done" with a "See all 4" button of at least 44 px. It opens the full list as a sheet that rises over the stage, crew and trick and stops at the tray, so the live instruction, the hand and the dock stay in use; a long list scrolls inside it. It works during a burst and with every hand size. How many objectives stay on the board itself is in the table below |
| Zone 5, hand and controls | The one live instruction sits at the top of the tray, beside the cards it is about: "Your turn" and the server's reason. Hands of up to ten are rows of five; larger hands are rows of seven, which is what keeps every card at least 44 px wide at 360 px. With two players a two-option switch, "Yours" and "Tonoja", each with its count, sits above the hand; Tonoja's cards are its face-up cards, with an empty place shown as "Empty" and the covered cards as a count. Burst and Play in the dock; Play names the card and, for Tonoja, says so ("Play blue 7 for Tonoja") |
| Card states | Playable: full colour. Chosen: raised, amber ring. Cannot be played now: darkened but still its own colour, with a struck-circle mark, and the reason as a sentence above. Not your turn: full colour, nothing chosen, Play says who is awaited. Suits are a colour, a drawn shape and a word |
| Burst Transmission | Opens in place of the trick, between tricks. Pick a card in your hand; the panel shows it and the three things you could say; only the true ones are live, with the reason. Cancel and "Send burst to the crew" replace Burst and Play in the dock. The mechanic's full name, "Burst Transmission", appears once as the panel title; everywhere else it is "burst". At 360 × 640 the objectives fold to their header while the panel is open |
| Result | The word first ("Mission failed" or "Mission complete"), then the server's cause in one sentence, then the evidence: the trick that did it, with its winner raised and tagged "Led, won" and the triggering card tagged "Deciding card", the objective it broke, the rest. Every objective's outcome is kept at every size; the evidence scrolls when it does not fit and the actions stay pinned (the first package lost outcomes on short screens because the board's folding rule leaked into the result; fixed in revision 1). What happens next is today's lifecycle, unchanged (revision 2; Games `client.js` `drawResult`): after a failure the Party Host has "Retry same tasks" and "Retry new tasks"; after a success a picker of the open missions and "Next mission"; "End EXPO for everyone" is the Host's; anyone may "Look at the table". Others read "Waiting for Dana (Party Host) to choose what's next." The first package and revision 1 drew "Try mission 7 again", a "Next mission" with no picker and "Party Home"; all three were changes to the lifecycle and are withdrawn |
| Host / everyone else | The Host's End is in the table menu, not beside Play. Result actions are the Host's |
| Responsive | Demonstrated at 360 × 640, 390 × 664, 390 × 844 and 844 × 390 for hands of 8, 10, 13 and 14, two players with Tonoja, five seats, burst open, the objectives sheet and both results: no horizontal overflow, nothing cut off, no target under 44 px (measured in a desktop browser at those viewports; table below). What the larger cases cost is stated in the table, not hidden. Landscape is still a sketch |
| States | Your turn with a card chosen; waiting for someone; Burst Transmission open; mission failed and mission complete (Host and everyone else); five at the table; three players with 13 and 14 cards; two players (your hand, Tonoja's turn, looking at Tonoja's cards on your own turn); the lead of a trick ("No card played yet"); the objectives sheet (short, long, during a burst); reconnecting (the status line says so, the hand stays, Play and Burst are unavailable with the reason, the winner line reads "Last seen winning"); another seat away (the engine's own state: commands refused, "Waiting for the crew to reconnect"); text at 150% and 200%. Not drawn, and unchanged from today: the rules overlay, task selection, distress, and EXPO's own setup before the first deal (the Host's mission choice and "Deal mission N", the clock, agreeing Tonoja's seat) |
| Accessibility | Status, the winner line and the result are live regions; every card has a name ("blue 6, cannot be played now"); nothing is colour alone; text is `rem` (today `px` from 8 px, EX-22). Enlarged text (rebuilt in revision 2): because the board is a fixed-height grid, `rem` alone is not enough, so with larger text the board becomes one scrolling column in this order: mission, crew, every objective, the trick, then the instruction and the hand. Only the action keys are pinned, and nothing scrolls inside anything else. The column opens with the hand just above the keys and the trick above the hand; a burst opens at its instruction. A hand of 13 or 14 and Tonoja's cards keep rows of seven from 360 px wide (six at 320 px), so 14 cards are two rows at any text size; ranks grow with the setting as far as a card allows (28, 31 and 34 px; 28 to 30 px in rows of seven). Burst Transmission is a step in the same column: the instruction, your cards, what to say about the chosen one, with Cancel and Send pinned. On the result only the Host's choice is pinned. Text scaling is not capped. What is still poor is in [REVISION-2](REVISION-2.md#what-is-still-limited). These are simulated checks, not a phone's text setting and not a screen reader |
| Changed from today | Cards were the least prominent thing (58 × 46 to 60 px, hand at half opacity when not acting, EX-3); controls were the LAN Games kit (EX-1); two objectives truncated (EX-7); End beside Play (EX-16); platform wordmark over the game (E-6) |
| Backend / state | Nothing required. Better with D5, D6, D7, and D8 (which Tonoja columns still hide a card). The in-play rules overlay is a decided platform follow-up, not drawn |
| Open proposals | Everything visual, as the brief's §29 says of EXPO's diegesis. By name: status on the tray; the palette; the Captain as a word; fiction words, "Tonoja" among them; landscape (decision 8). Four audit questions are answered by the drawing and need a yes or no (decision 14). Revision 1 adds: the objectives sheet does not block the tray; an open objective reads "In play" in the sheet; with two players on a short screen no objective rows stay on the board (decision 19). Revision 2 withdrew the result-button changes: the result keeps today's controls |

What stays authoritative: legality (`me.legal_cards`), reasons (`me.play_reason`,
`card_reasons`), the winner so far (`trick_leading`), objectives (`tasks[].state`), the result
and its cause, what may be transmitted (`me.communication_options`). The concept decides none of
them.

### EXPO layouts, measured (revision 1)

Each cell: hand-card target, rows of cards · trick card · objectives on the board. Deals are the
engine's: 8 each for five players, 10 for four, 13/13/14 for three, 13 each for two with 14
under Tonoja. Measured by script in a desktop browser at these viewports, not on phones.

| Hand | 360 × 640 | 390 × 664 | 390 × 844 | 844 × 390 |
|---|---|---|---|---|
| 8 | 62 × 54, 2 · 50 × 60 · 1 of 4 | 62 × 56, 2 · 52 × 60 · 2 | 64 × 80, 2 · 72 × 94 · 3 | 46 × 54, 1 · 48 × 60 · 4 |
| 13 and 14 | 44.6 × 54, 2 · 50 × 60 · 1 | 48.8 × 56, 2 · 52 × 60 · 2 | 48.8 × 80, 2 · 72 × 94 · 3 | 59.8 × 46, 2 · 48 × 60 · 4 |
| 13, two players | 44.6 × 54, 2 · 50 × 51 · 0 | 48.8 × 56, 2 · 52 × 57 · 0 | 48.8 × 80, 2 · 72 × 72 · 2 | 59.8 × 46, 2 · 48 × 54 · 4 |

What it costs: above ten cards the hand goes to rows of seven, so cards get narrower, not
shorter, and at 360 px they sit 0.6 px over the 44 px floor. The two-player switch takes a row,
so under 760 px of height no objective stays on the board (the header and the sheet remain) and
the trick cards are shorter. During a burst the board shows 0, 0, 1 and 4 objectives at the four
sizes; the sheet is the way to see them. The two-player trick sizes are for your turn and for
Tonoja's turn; while waiting they are 50 × 54 and 52 × 60.

**The floor.** The fixed board needs about 600 px of height for three to five players and
about 630 px for two (the independent validation found the zones starting to overlap at 590 and
620 px, at 375 px wide), and 350 px of width for a 14-card hand. 360 × 640 is therefore close to
the edge: 10 px of margin with two players. Below that floor, in portrait, the board becomes the
scrolling column built for enlarged text, at normal text size, with only the keys pinned
(`r-expo-below-floor-*`). In that column every objective is on the board, so there is no
sheet to cover anything. What was measured there is in [REVISION-2](REVISION-2.md#revalidation).

### EXPO art need

The brief asks for "a dangerous radiated expedition viewed through rugged field equipment". The
concept can frame that; it cannot paint it. What is in the prototype is CSS only: flat ridges, a
sun, a dead pylon and haze for the land, and procedural noise for the housing's grain. No image
file was added and nothing was generated by an image model.

What a human artist or a licensed source needs to supply:

| Asset | Size and behaviour | Notes |
|---|---|---|
| The land behind the window | wide strip, safe to crop from 360 × 66 to 390 × 118 and to 345 × 62 in landscape, darkest on the left 40% where the mission text sits | at least one per mission arc; the same scene in a "storm" and a "cleared" grade for the two results |
| Housing material | a small seamless tile, low contrast | replaces the procedural grain |
| Burst Transmission panel | optional: grille and fastener detail | CSS today |

Candidate sources, none fetched: a commissioned illustration set; public-domain aerial and
satellite photographs of desert and badland terrain (USGS, NASA); CC0 material libraries for the
housing tile. Whether photographs or illustration suit EXPO is the owner's call.

## Supporting concepts

Extras, documented briefly. Each is identical for the Host and everyone else unless noted, keeps
the shell's responsive and accessibility rules, and is a proposal throughout.

| Concept | Files | Purpose and primary action | Needs |
|---|---|---|---|
| First run | `x-welcome-*`, `prototypes/welcome.html` | Name and a face on one screen; "Join the Party" always in reach. Today the form is 1126 px tall with Save 255 px below the fold (PS-8) | existing profile routes |
| Social drawer | `x-drawer-chat-*`, `x-drawer-people-*`, `r2-briefing-party-*`, `r2-library-party-people-*`, `r2-game-party-people-*` | Read and send chat, see who is here; comes down from the Party control over whatever page is open, the briefing included, and closes back to it (revision 2). Over a briefing it says where the Party is. `?chat=off` shows the first slice: people only | chat needs R3; People works today; over a briefing it needs one sentence changed in GAME-UX-CONTRACT rule 3.2 |
| A suggestion | `x-suggestion-*` | Shows only where a suggestion would land: a toast with View and a dismiss. Host and others get different second lines | C1; the voting model is undecided (brief §29) |
| Filters | `x-library-filters-*` | Players (at "Any" until someone picks, with the Party's size as a hint), length, how you play, kind, screens. The button says how many games will show | R1 |
| Library views | `x-library-view-menu-*`, `x-library-large-*`, `x-library-compact-*` | Four views, remembered per device | F2 |
| Profile | `x-profile-*` | A sheet opened from your own face or from System; Save | existing; in Limited Mode it must also follow ADR 0012 decision 5 (not drawn) |
| System | `x-system-*`, `x-system-limited-*`, `x-system-degraded-*` | Health in one line; this phone's preferences; diagnostics behind a row marked as the owner's. Appliance trouble is shown to the Host only | F5, F8; D2 |
| Arcade shell | `x-arcade-portrait-*`, `x-arcade-landscape-*`, `prototypes/arcade.html` | A sketch only: picture first, one thin bar, controls under the thumbs; landscape puts the picture in the middle and the menu behind one button. The Host's End is in the bar | the controller framework is undecided (brief §29) |

## Known rough edges in the concepts

- With three troubles at once on one title at 360 × 640 (does not fit, Limited phone, arcade
  off) the detail page's action sits at the fold.
- System and Party are plain lists with space under them. They are meant to be quiet; the
  validator read them as "phone settings", which is a fair warning.
- EXPO with two players under 760 px keeps no objective row on the board, and during a burst on
  a short screen none either. The sheet is one tap away; whether that is enough needs a phone.
- EXPO at 200% text on a 360 × 640 screen: the hand, the trick's winner line and the keys are
  on screen together, but the column is two to three screens long, a burst needs one scroll
  between picking a card and reading its options, and in rows of seven the suit word stays at
  12 px. Ranks grow only from 28 to 34 px.
- The compact Library grid keeps the consequence line but drops the "Max 2" seats mark.
- EXPO's fixed board has a floor just under the smallest size tested (see "The floor").
- Two things on the EXPO board carry no information: the sight marks on the window and the
  fasteners on the Burst panel. The pylon in the land was first drawn as a post with a crossbar,
  which read as a grave marker; it was redrawn, and deserves a second look.
- On Home in Limited Mode the Worms tile is the fourth in its row, so its "Watch only on this
  phone" line is off screen until the row is scrolled.
- The EXPO land is flat shapes and the grain is noise. They hold the place for human-made art
  and should not be judged as art.
- The Arcade shell and EXPO landscape are sketches. EXPO landscape passed the layout measure at
  844 × 390 for every hand size; it has not been designed beyond that.
- Enlarged text was checked by scaling the root font size in a desktop browser. No real phone,
  no system text setting, no screen reader.

## Not drawn

Results handing back to the Party (the game's own screen; EXPO's mission result is shown, and it is not a Party `results` location: EXPO replays inside one round), the "Game in
progress, you are not playing this round" state, the in-play rules overlay, a Party layer over
games, destructive confirmation, the TV. The first three are decided or accepted elsewhere and
need design in the implementation slices.

Also not drawn, though named in the state rows above: Home with one person ("Just you so far"),
a Party larger than six, a title that is not installed, and the profile sheet in Limited Mode
(ADR 0012 decision 5: claiming a profile or entering a PIN over HTTP is disabled or labelled as
exposed). Motion, focus handling and real timing for reconnecting and for a Host going away are
specified in words only. EXPO's share card (EX-43) and its standalone lobby (EX-47)
are outside this package.
