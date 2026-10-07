# Party shell audit: current UI

Status: **audit evidence (2026-10-05); observations of source at origin/main 578534f, design input, not contract.**

Measured against [AVRANA-UX-UI-PRODUCT-BRIEF](../../AVRANA-UX-UI-PRODUCT-BRIEF.md). Observations only; no
proposals. Method: the real pages on `python -m avrana.web.devserver --party --test-controls`
(real Party Core, stub game pages), headless Chromium 1243 on Windows, device scale factor 2,
1 to 4 browser contexts as phones. Numbers are CSS px from computed styles and
`getBoundingClientRect`; contrast is WCAG 2 from computed colours composited over their grounds.
Screenshots are in `current/`, kept outside Git since 2026-10-05 ([README](../README.md#pictures-that-are-not-in-git)), and are cited by file stem (viewport and
`-viewport`/`-full`/`-el` suffix omitted where several exist). Limits of the evidence are in §6.

Categories: **A** visual, **B** information architecture, **C** interaction, **D** accessibility,
**E** backend/state gap, **F** product question (owner decides; no answer proposed).

## 1. Summary

1. Party Home is one document holding identity, Party, chat, library and device checks (`web/party/index.html:17-136`). As Host with 4 members it is 3.0 screens at 390x844, 4.0 at 360x640, 5.3 at 844x390.
2. The first game tile starts at y=794. No complete tile is in the first viewport at any phone size tested; at 360x640 it starts 154 px below the fold.
3. There is no navigation model. Modules are `<details>` rows on one page plus three full-screen swaps driven by Party state (`app.js:350-355`). Profile and connection state hold the top of every visit.
4. The library is a single-column list of dashboard tiles (294 to 347 px each, artwork 72x72 px, about 5% of the tile). No grid, list switch, sort, sections, categories or Party-size awareness.
5. Browsing and launching are the same tap. The Host's tile button is "Start for everyone"; there is no game detail. A non-Host's only tile control is a disabled button at 1.78:1 contrast.
6. Briefing exists only as a Party-wide setup state the Host has already entered, and only for games configured with a setup. Its rules sheet hides "Got it" 294 px below the fold and first-time Play is gated on it.
7. Healthy technical state is foregrounded: "Connected to the party", a lock with "Secure", "Works on this phone" on every installed tile, a 7-row "This phone" checklist, a "Technical details" link.
8. Limited Mode adds a 330 to 375 px amber panel for every member, with copy about privacy, saved pages and the certificate; it is neither Host-only nor dismissible.
9. Text contrast passes AA everywhere except disabled controls (1.78 to 1.80:1). Away is shown by opacity alone. Screen changes move neither focus nor title.
10. Backend gaps the brief's UX would meet: no duration/genre/format metadata, no Party-level recents, no suggestion state, chat on a separate legacy socket that only listens while its row is open.

## 2. Measurements

### 2.1 Document scroll height (px) and screens (scroll height / viewport height)

| State | 390x844 | 360x640 | 375x667 | 844x390 | 820x1180 |
|---|---|---|---|---|---|
| First run, no profile | 2400 / 2.84 | 2449 / 3.83 | 2449 / 3.67 | | |
| First run, profile form open | 3534 / 4.19 | 3523 / 5.50 | 3553 / 5.33 | | |
| Home, Host, 1 member | 2504 / 2.97 | 2528 / 3.95 | 2528 / 3.79 | | |
| Home, Host, 4 members | 2556 / 3.03 | 2580 / 4.03 | 2580 / 3.87 | 2080 / 5.33 | 2080 / 1.76 |
| Home, non-Host, 4 members | 2496 / 2.96 | 2520 / 3.94 | 2520 / 3.78 | | |
| Home, profile editor open | 3638 / 4.31 | 3602 / 5.63 | 3632 / 5.45 | | |
| Home, chat open (1 member) | 2906 / 3.44 | | | | |
| Home, "This phone" open (1 member) | 2785 / 3.30 | | | | |
| Limited Mode home, Host, 1 member | 2907 / 3.44 | 3029 / 4.73 | 3006 / 4.51 | | |
| Limited Mode home, one game blocked, 3 members | 3001 / 3.56 | | | | |
| Setup scene (any role) | 844 / 1.00 | 640 / 1.00 | 667 / 1.00 | 581 / 1.49 | |
| Can't reach the party | 844 / 1.00 | 640 / 1.00 | 667 / 1.00 | | |
| Diagnostics page | 4761 / 5.64 | | | | |
| Arcade page | 844 / 1.00 | 652 / 1.02 | | 453 / 1.16 | |

No horizontal overflow in any state (scrollWidth = innerWidth).

### 2.2 Anatomy of Home (390x844, Host, 4 members; `party-home-host-4-390x844-full`)

| Block | Top y | Height | Note |
|---|---|---|---|
| Title + connection line | 16 | 72 | h1 28 px, status 15 px, lock + "Secure" |
| Identity button | 104 | 78 | 358x78 |
| "Profile saved on this browser." | 198 | 23 | persists after a save |
| Party panel | 233 | 233 | 181 with 1 member, 112 with no profile |
| Party Chat row | 482 | 58 | 460 open |
| Games heading, search, people filter, view switch | 556 | 238 | controls before the first tile |
| Game tiles x5 | 794 | 294, 294, 318, 347, 323 | games section is 1863 px, 73% of the page |
| "This phone" row | 2443 | 57 | 338 open |

First tile top by state: 638 (first run), 742 (Host, 1 member), 794 (Host, 4), 734 (non-Host, 4),
1053 (Limited, 1 member), 1125 (Limited, blocked game, 3 members), 1076 (Limited at 360x640).
Tiles per screen: 2.4 to 2.9 at 844 px, 1.8 to 2.2 at 640 px. Visible words on Home: 238
(320 in Limited Mode). Tab stops before the first game action: 10.

### 2.3 Containers, radii, type, colour (390x844)

| Measure | Home, Host, 4 members | Other states |
|---|---|---|
| Elements with a visible border or radius | 39 | 100 with profile form open; 41 Limited; 13 setup scene |
| Elements bordered on all four sides | 21 | 24 profile open; 11 scene |
| Card-like containers (bordered or filled, rounded, at least 120x40, with children) | 11: identity, Party panel, 2 wide roster pills, chat row, view switch, 5 tiles | 12 Limited; 2 scene (Play, Watch) |
| Max nesting of card-like containers | 2 (Party panel > roster pill) | 1 in first run and scene |
| Framed sub-elements inside tiles | 5 cover frames (72x72, 12 px radius, 1 px accent border), 5 footer dividers | |
| Radius values | 8 px (1), 12 px (14), 16 px (8), pill (4), circle (6) | profile form: 16 px x41, circle x34 |
| Icons | 33 inline line icons | |
| Font stacks (computed) | `ui-rounded, "SF Pro Rounded", system-ui…` on h1 to h3 (10 nodes); `system-ui, -apple-system, "Segoe UI", Roboto…` (55 nodes) | both resolve to Segoe UI on the test machine (h1: Segoe UI Black) |
| Font sizes in use (all shell states) | 13, 14, 15, 16, 17, 18, 19, 20, 24, 28 px | 15 px is 40 of 65 text nodes on Home; body base 17 px is used by 1 |
| Font weights in use | 400, 600, 650, 700, 750, 800 | |
| Distinct colours on Home | 21: 15 neutral tints, 6 chromatic | |
| Chromatic colours, all shell states | primary violet `#765fb8`, lavender icon tint `#b5a0cf`, link lavender `#c5b3e8`, green `#70c696`, amber `#ebbb6e`, red `#e66e6d`, blue `#81afdf`, plus each game's accent (BLUFF `#e879f9`, EXPO `#65e5dd`) | |

### 2.4 Touch targets under 44 px (width or height)

| State | Targets | Under 44 px |
|---|---|---|
| Home (Host or member) | 18 | 0 |
| Profile form open | 53 (32 avatar cells at 75x75) | 0 |
| "This phone" open | 19 | `Technical details` link 107x20 |
| Limited Mode home | 19 to 20 | `Check for the full version` link 165x20 |
| Setup scene | 5 | `How to play` 143x38.4, `Choose another game` 191x38.4 (`btn-sm`, `index.html:150,165`) |
| Rules sheet | 3 | 0 |
| Arcade | 12 | `Other games` link 91x21 |

### 2.5 Contrast

| Pair | Colours | Ratio |
|---|---|---|
| Main text on page | `#edebe5` on `#121218` | 15.65 |
| Main text on panel / on pill | `#edebe5` on `#1b1b23` / `#262730` | 14.35 / 12.45 |
| Secondary text on page / panel / tinted tile (hover or focus) | `#b0afc0` on `#121218` / `#1b1b23` / `#2b2934` | 8.65 / 7.93 / 6.63 |
| Primary button label | `#faf9fe` on `#765fb8` | 4.89 |
| Link | `#c5b3e8` on `#121218` | 9.76 |
| Warning text (Limited heading, "Limited" label) | `#ebbb6e` on `#1b1b23` / `#262730` | 9.67 / 8.38 |
| Away member name (pill at 60% opacity) | `#999897` on `#22222b` | 5.47 |
| Placeholder "Search games" | base content at 50% on `#121218` (from the CSS rule, not sampled) | about 4.7 |
| Disabled button label ("Not installed", "The host starts it") | `#56565a` on `#303036` | **1.78** |
| Disabled "Start game" label and icon | `#4f4f52` on `#28282d` | **1.80** |
| Generic cover icon on an uninstalled tile | `#776b8a` on `#312f3c` | **2.66** (non-text, 3:1 needed) |
| Arcade disabled controls (opacity .45) | `#15132b` on `#655d8a` | 3.02 |

### 2.6 Player-facing strings that name infrastructure

| String | Where |
|---|---|
| "Connected to the party" + lock icon "Secure" (healthy state) | `index.html:23-28`, `app.js:74,468-469` |
| "Connected. Open party.avrana.net for the full experience" | `app.js:470` |
| "Profile saved on this browser." / "Saved on this browser. Shared with the party games." | `lib/profile-ui.js:67`, `index.html:36` |
| "This browser cannot save your profile. Allow local storage and try again." | `lib/profile.js:32` |
| "This connection is not private. Other people on this Wi-Fi could see what this phone sends." | `lib/limited.js:34` |
| "The Party page is not saved on this phone." | `lib/limited.js:27` |
| "The full version comes back when the Party box's owner renews its certificate." | `lib/limited.js:36` |
| "A secure connection", "This page isn't open on the secure Party address.", "Live game video", "The Party's video format", "Game controller support", "Party page saved on this phone" | `catalog.json` labels via `app.js:413-431` |
| "Technical details" (link to a page headed Diagnostics: Capabilities, Provider, Running build, Offline copy, schema names) | `index.html:133`, `diag/index.html` |
| "Experimental · Not installed on this Party box", "Needs a device check before use.", "Games update needed before opening here" | `app.js:152,165` |
| "This browser can't play the Party's video format." | `catalog.json` labels via `lib/evaluate.js:70-85` |
| "Chat is reconnecting…", "Save your profile to chat" | `app.js:492-493` |

## 3. Findings

### 3.1 Party shell

| ID | Area | Observation | Cat | Sev |
|---|---|---|---|---|
| PS-1 | Home | One `<main>` holds, in order: title and connection line, identity, profile form, Limited notice, Party panel, can't-reach panel, chat, library, "This phone" (`index.html:17-136`). | B | high |
| PS-2 | Scrolling | Home as Host with 4 members is 2556 px: 3.03 screens at 390x844, 4.03 at 360x640, 3.87 at 375x667, 5.33 at 844x390 (§2.1). | B | high |
| PS-3 | Scrolling | The first game tile starts at y=794: 50 px of it is in the first viewport at 390x844, none at 360x640 or 375x667, where the first screen ends at the search field (`party-home-host-4-360x640-viewport`). | B | high |
| PS-4 | Home | Home has no region for current activity, resume, recently played or games suited to the Party. The Party panel's only activity text is a role sentence (`app.js:249-251`). | B | high |
| PS-5 | Navigation | No persistent navigation. Movement is page scroll, three `<details>` toggles (profile, chat, this phone) and three full-screen swaps `main` / `scene` / `going` set only by Party state (`app.js:350-355`). Diagnostics is a separate page behind a text link. | B | high |
| PS-6 | Navigation | Home and the setup scene share one URL, one history entry and one `<title>` ("Avrana Party"); `show()` only toggles `hidden` (`app.js:350-355`). The page offers no back affordance. | C | med |
| PS-7 | Profile | Identity is the first element under the connection line on every visit: a 358x78 button reading the player's name and "Your profile" (`index.html:29`, `lib/profile-ui.js:40-45`). | B | high |
| PS-8 | Profile setup | Opening the form inserts a 1126 px panel inline (Home becomes 4.19 screens at 390x844, 5.50 at 360x640). "Save profile" is at y=1099, under a 656 px grid of 32 avatars: 255 px below the fold at 390x844 (`party-profile-setup-390x844-full`). | C | high |
| PS-9 | Profile setup | Every new guest starts with the same preselected avatar, gaze-01 "Pink diamond" (`lib/profile.js:12-16`). Two guests who only typed a name share one avatar (`briefing-host-undecided-844x390-viewport`). | C | med |
| PS-10 | Profile setup | First run asks for the name three ways at once: the identity button ("Choose your name / Pick a name to join a game"), the Party panel ("Choose your name above to join the party.") and each Party tile's button ("Choose your name to play") (`party-firstrun-390x844-full`). | B | med |
| PS-11 | Profile editing | After a save, "Profile saved on this browser." stays under the identity button with no expiry (`lib/profile-ui.js:67`, `index.html:59`). The form also shows "Saved on this browser. Shared with the party games." and "0 favorites · 0 games opened" (`index.html:36`, `lib/profile-ui.js:46`). | B | med |
| PS-12 | Profile editing | The photo crop is three range sliders: Zoom, Left to right, Top to bottom (`index.html:49-51`). Source observation; not captured. | C | low |
| PS-13 | Profile | The name field takes 24 characters (`index.html:39`); Party Core receives the first 16 (`app.js:203`). An uploaded photo is not sent to Party Core (`app.js:201-205`), so the roster and setup show the bundled avatar while the identity button and chat show the photo. | E | med |
| PS-14 | Roster | Members are 44 px pills (avatar, name, optional crown, optional "Limited") in join order inside the Party panel (`party.css:241-249`). Four members wrap to two rows; the panel is 233 px, of which about 100 px is roster (`party-home-host-4-390x844-viewport`). | A | med |
| PS-15 | Presence | Away is shown only by 60% opacity on the pill and on the setup avatar (`party.css:248,280`; `app.js:220`). No word, icon or accessible text (`party-roster-away-panel`). ACCESSIBILITY rule 5 asks for a word, icon or shape. | D | high |
| PS-16 | Presence | At Home a member has two visible states, here and away; away starts after 45 s without a request (`avrana/party/core.py:60`). Ready, Watch and activity exist only inside a setup (`lib/party-mode.js:80-86`). A sleeping phone and a departed guest look the same. | E | med |
| PS-17 | Host | The Host marker is a crown icon in three places: roster pill (`app.js:224`), setup header (`index.html:145`), setup roster (`app.js:330`). | A | med |
| PS-18 | Host | Host-only actions are not grouped. At Home they are one "Start for everyone" button per tile spread through the library (`app.js:181-184`); the Party panel has none. The Host sentence "You're the host: start a game below and everyone goes there together." is permanent (`app.js:250`). | B | med |
| PS-19 | Host | The roster crown is `<span aria-label="host">` around an `aria-hidden` icon, with no role (`app.js:224`); the setup roster uses `role="img"` with a label. | D | low |
| PS-20 | Host | Is there a deliberate hand-over of Host? Today the role moves only by silence: 45 s away plus 30 s grace (`core.py:60-61,263-271`). No verb or control exists. | F | med |
| PS-21 | Chat | Party Chat is a 58 px disclosure row between the Party panel and the library, on Party Home only (`index.html:87-98`). It is absent from the setup scene and from game pages. Open, it is 460 px and pushes the first tile from y=742 to y=1144 (`party-chat-open-mocked`). | B | high |
| PS-22 | Chat | Chat is a separate legacy socket `/chat/ws` with its own token and its own head count ("3 in chat"), not Party Core state (`lib/party-chat.js:15-16,48,65`). It connects only while the row is open (`app.js:546-551`): a closed chat receives nothing and shows no unread or new-message cue. | E | high |
| PS-23 | Chat | A message is avatar, name, text. No time, no marking of the reader's own messages; a shared photo renders as the words "Photo shared" (`app.js:499-503`). The list scrolls inside the page scroll (`max-h-72`, `index.html:91`). | C | med |
| PS-24 | Chat | The closed row's status reads "Open to chat"; other states are "Connecting…", "Chat is reconnecting…", "Save your profile to chat", "Choose your name above to chat" (`app.js:492-493,553`; `party-chat-open-reconnecting`). | B | low |
| PS-25 | Catalog | The library is the fifth block of Home, reached by scrolling or by a skip link visible only on keyboard focus (`index.html:16,100`). Detail in §3.2. | B | high |
| PS-26 | Search/filter | Heading, search field, "People playing" select and the three-way view switch take 238 px before the first tile, for a catalog of 5 titles (§2.2). | A | med |
| PS-27 | Status | The healthy state is announced at the top of every visit: green dot, "Connected to the party", lock icon, "Secure" (`index.html:23-28`). | B | high |
| PS-28 | Status | Every installed tile carries a per-phone verdict row; in the healthy case it reads "Works on this phone" with a green icon, 3 of 3 installed tiles (`app.js:77-88,168`). | B | med |
| PS-29 | Status | "This phone" lists 7 capability checks and links to "Technical details" (`app.js:30,413-431`; `index.html:129-135`; `party-this-phone-open`). Its summary reads "All set" while the page says "Can't reach the party" (`party-cant-reach-390x844-viewport`). | B | med |
| PS-30 | Status | 2 of 5 tiles are uninstalled experimental titles shown to every player with "Experimental · Not installed on this Party box", "Needs a device check before use." and a disabled "Not installed" button: 670 px of scroll (`app.js:143,152,165`; `lib/catalog-view.js:17-19`). | B | med |
| PS-31 | Status | Infrastructure wording reaches players in at least 12 strings (§2.6). The existing wording test bans a different list: seat, session, server, websocket and similar (`tests/offline/party.spec.ts:8`). | B | med |
| PS-32 | Limited | The Limited notice is an amber-bordered panel placed above the Party panel for every member in Limited Mode, Host or not, with no dismiss (`index.html:63-69`, `app.js:232-241`). It is 330 px at 390x844, 353 px at 360x640 (55% of that viewport), 375 px when it names a blocked game. | B | high |
| PS-33 | Limited | Its copy describes the transport and the remedy: privacy on the Wi-Fi, the page not being saved, the owner renewing the certificate (`lib/limited.js:26-36`; `limited-notice`). Player impact is two bullets inside it. | B | high |
| PS-34 | Limited | LIMITED-MODE §3.9 (accepted) specifies one banner that says the connection is not private and that the owner renews the certificate. Brief §13 says explain impact not internals, Host first, dismissible. Which governs the notice? | F | high |
| PS-35 | Limited | ADR 0012 D4 shows "Limited" beside each member to everyone (`app.js:226`; 13 px amber, the smallest text in the shell; `party-roster-limited-member-panel`). Brief §13.1 says degraded notices go normally to the Host. Which governs the roster? | F | med |
| PS-36 | Limited | In Limited Mode each installed tile gains a warning-bar note ("This phone may dim its screen while you play.") and the verdict "Works, with limits"; tiles grow from 294 to 325 px (`limited-library-390x844-viewport`). | A | low |
| PS-37 | Limited | A game page opened in Limited Mode does not follow the Party (LIMITED-MODE §3.7 "Not yet"). Not exercised here. | E | med |
| PS-38 | Loading | While loading, the page shows "Checking the connection…", the identity button, live search, filter and view controls, and two 176 px skeleton blocks (`party-loading-390x844-viewport`). | C | low |
| PS-39 | Error | A failed catalog shows three messages together: "Game list unavailable." with Retry, the count "0 games", and the filter empty state "No games match. Try another search or group size." (`party-catalog-error-390x844-full`; `app.js:400-403`). | B | med |
| PS-40 | Error | Errors are written to two fixed places: `#profile-note` under the identity button (storage and favourite errors, "Choose your Party name before opening a game.", `app.js:129,134,149`) and `#party-note` in the Party panel (launch failures, `app.js:196,259`). A player acting on a tile at y≥794 does not see either. | C | med |
| PS-41 | Error | The "Taking you to EXPO…" screen is a spinner and one line with no timeout or way back (`index.html:181-184`, `app.js:361-366`). With the navigation cancelled it stayed until the test closed it (`party-going`). | C | low |
| PS-42 | Cardification | Home shows 39 bordered or rounded elements, 21 of them boxed on four sides, in 11 card-like containers (§2.3). The pattern is breadth, not depth: max nesting is 2. Every tile also has a framed cover and an internal divider. | A | high |
| PS-43 | Cardification | Every control and container is rounded: 12 px on buttons, inputs and covers, 16 px on panels and tiles, full pills for members, circles for avatars and badges (`party.css:56-59`). | A | med |
| PS-44 | Typography | Headings use `ui-rounded, "SF Pro Rounded", …` (`party.css:73,86`), which the brief (§5.3) says must not remain the platform face. No Geist; the brand line is 28 px weight 800, not a light Helvetica treatment (`index.html:21`). | A | high |
| PS-45 | Typography | 10 sizes between 13 and 28 px and 6 weights are in use; 15/16/17 and 18/19/20 differ by 1 px. 62% of Home's text nodes are 15 px (§2.3). | A | med |
| PS-46 | Colour | Large fills are violet only: one filled violet button per installed tile for the Host, the selected avatar and the selected Play/Watch choice. Neutrals carry a violet cast in 15 tints. State colours appear as icon tints, the amber Limited border and the setup badges (§2.3). | A | low |
| PS-47 | Colour | Game accents reach the shell only as a 1 px cover border and the generic icon tint (`app.js:102`, `party.css:193-198`); the setup scene uses the accent on the 64 px cover only. | A | low |
| PS-48 | Density | A tile averages 315 px for one title; five titles take 1576 px. Disclosure rows are 56 to 58 px; body text is 17 px at 1.5 line height (`party.css:82`). | A | med |
| PS-49 | Responsive | At 844x390 and 820x1180 the page is the same single column capped at 640 px (`party.css:106`); the rail layout starts at 1024 px (`party.css:110`). In phone landscape the first viewport ends inside the Party panel (`party-home-host-4-844x390-viewport`). | B | med |
| PS-50 | Accessibility | Disabled controls are 1.78 to 1.80:1 (§2.5). For a non-Host, the disabled "The host starts it" is the only action on a Party tile (`library-tile-bluff-member`). | D | high |
| PS-51 | Accessibility | Screen swaps manage neither focus nor title: after "Start for everyone" `document.activeElement` is `<body>`, and again after returning Home (`app.js:350-355`; measured). | D | med |
| PS-52 | Accessibility | The favourite star has no `aria-pressed` when off and `aria-pressed=""` when on, because `h()` drops `false` and writes `true` as an empty string (`lib/ui.js:7-11`, `app.js:147`; measured). The label does switch between "Add … to favorites" and "Remove … from favorites". | D | low |
| PS-53 | Accessibility | 9 `role="status"` regions exist in the document; `#game-count` is one and changes on every search keystroke (`index.html:101`). | D | low |
| PS-54 | Accessibility | Two inline text links are 20 px tall: "Technical details" and "Check for the full version" (§2.4). | D | low |
| PS-55 | Empty states | Favourites, recents and no-match each render a dashed box with an icon and one sentence (`app.js:401-403`; `library-favorites-empty`, `library-recent-empty`, `library-empty-search`). Search, filter and view controls stay above an empty list. | A | low |

### 3.2 Library

| ID | Observation | Cat | Sev |
|---|---|---|---|
| LIB-1 | The library is not a destination. It is a section of Home whose heading sits at y=400 to 556 in Full Mode and y=815 to 887 in Limited Mode, depending on what is above it (§2.2). | B | high |
| LIB-2 | One layout: a single-column list, two columns from 1280 px (`index.html:123`). No medium, large or compact grid and no list/grid switch. | B | high |
| LIB-3 | A tile holds up to 12 parts: cover, title, players, screen, star, summary, how-you-play line, device-check line, reason note, divider, per-phone verdict, live or Party line, action (`app.js:155-170`; `library-tile-arcade-gauntlet2-not-on-this-phone`). | A | high |
| LIB-4 | Artwork is 72x72 px, 4.9% of a 358x294 tile, in the top-left corner (`party.css:193-198`). Title and metadata, not artwork, carry the tile. | A | high |
| LIB-5 | 3 of 5 titles have art. EXPO has no `artwork` entry and shows a generic spade line icon; Worms shows a generic gamepad (`catalog.json`; `lib/ui.js:42-46`; `library-top-390x844-viewport`). Gauntlet II and Bomberman use a single Kenney glyph. | A | med |
| LIB-6 | No sections or categories. `collections` is empty; `category` exists on 2 titles (party, cards), is matched by search and is never displayed (`catalog.json`; `lib/catalog-view.js:25`). The only groupings are the views All games, Favorites, Recently opened (`index.html:118-122`). | B | high |
| LIB-7 | The catalog has no play time, no genre or type, no social format (co-op, competitive, teams). Display need exists as `screen` (3 values) and is shown, not filterable. `description` exists on 2 titles and is unused by the page. | E | high |
| LIB-8 | The one filter is a manual select, "People playing", with 1, 2, 3, 4, 5, 6, 8, 10, 12 and a default of "Any group size" (`index.html:110-115`). It is not tied to the Party's size. The largest maximum in the catalog is 6, so 8, 10 and 12 always give the empty state. | C | high |
| LIB-9 | The filter removes non-matching games from the list (`lib/catalog-view.js:27`): with 6 selected only BLUFF remains (`library-filter-6-people`). The brief (§16) keeps mismatched games visible. | B | high |
| LIB-10 | Nothing compares a game's player range with the Party. Tiles show a static "2–6 players"; no ranking, badge or warning uses `view.members.length`. | E | high |
| LIB-11 | Launching a game without a setup with too many members shows no message. Party Core seats the first `max_players` by join order and makes the rest spectators (`core.py:405-420`). For a game with a setup the mismatch appears only after everyone chose: "At most 6 can play; 7 chose to play." (`core.py:441-442`). | E | high |
| LIB-12 | There is no game detail. Cover and title are not links; the summary is one line; "How to play" exists only inside a setup the Host has started (`index.html:150`). | C | high |
| LIB-13 | Browsing and launching are one tap for the Host: the tile button "Start for everyone" calls launch at once, with no confirmation (`app.js:182-197`). For a game with a setup every phone leaves Home for the setup scene; for one without, every phone navigates into the game. | C | high |
| LIB-14 | A non-Host can star a game and nothing else. The tile action is a disabled "The host starts it"; there is no way to read rules, see more, or signal interest (`app.js:185-186`; `library-tile-bluff-member`). | C | high |
| LIB-15 | Host and non-Host tiles differ only in that button. Both carry the line "Everyone plays together: the host starts it" (`app.js:151`), which tells the Host about the Host. | B | low |
| LIB-16 | Compatibility is stated per phone, not per Party: "Works on this phone", "Works, with limits", "You can watch", "Not on this phone" (`app.js:77-82`). A tile that does not fit the phone stacks an amber-barred reason, the verdict, the Party line and a disabled button (`library-tile-arcade-gauntlet2-not-on-this-phone`). | B | med |
| LIB-17 | "Recently opened" cannot fill in Party mode. A game is recorded only by the click handler on non-Party tile links (`app.js:125-135,140-142`); a Host start or a follower's move records nothing. | E | med |
| LIB-18 | Favourites and recents live in this browser's localStorage (`lib/profile.js:52-56,79-89`). View, search text and filter are in memory and reset on reload (`app.js:34,563-572`). No sort exists. | E | med |
| LIB-19 | Search is substring match over name, summary and category (`lib/catalog-view.js:21-26`). | C | low |
| LIB-20 | The count beside the heading ("5 games") includes the 2 uninstalled titles. | B | low |
| LIB-21 | Without Party Core the same tiles become direct links ("Play", "Try anyway") with live text "1 of 2 playing", "Full right now", "Not running right now" refreshed every 15 s (`app.js:110-117,138-143`; `party-catalog-mode-no-party-core`, `library-tile-arcade-gauntlet2-full`). Two launch models share one tile design. | B | med |
| LIB-22 | Should uninstalled or experimental titles be listed for players at all, or only for the owner? | F | med |
| LIB-23 | Are Recently Played and Favorites per device (today), per profile, or per Party? | F | med |
| LIB-24 | Brief §17 lets non-Hosts suggest or vote later. Is a non-Host signal in scope for the first redesign, given that no state for it exists? | F | low |

### 3.3 Briefing / setup scene

| ID | Observation | Cat | Sev |
|---|---|---|---|
| BR-1 | The briefing is a Party state, not a page a player opens. It appears for everyone when the Host starts a game configured with a setup (`core.py:405-414`); in the simulated Party that is BLUFF only. Games without a setup have no briefing. | B | high |
| BR-2 | It shows cover (64 px), title, Host line, one premise paragraph, "How to play", a roster with per-person choice badges, Play/Watch, and for the Host "Start game" and "Choose another game" (`index.html:140-168`). Player range, play time, display need and controls are not shown. | B | med |
| BR-3 | The scene fits one screen at 390x844, 375x667 and 360x640 with the actions at the bottom (`party.css:232-238`). At 844x390 it is 581 px and "Start game" sits at y=430, below the fold (`briefing-host-undecided-844x390-full`). | A | med |
| BR-4 | At 390x844 with 4 members, 254 px between the roster (ends y=347) and the choices (start y=601) is empty (`briefing-host-undecided-390x844-viewport`). | A | low |
| BR-5 | In the rules sheet the whole box scrolls, not the body: content is 1083 px in a 717 px box at 390x844 and 1134 px in 544 px at 360x640. "Got it" is at the end, 294 px below the viewport on open; the title and close button scroll away (`index.html:172-175`; `rules-dialog-390x844-viewport`, `rules-dialog-end`). | C | high |
| BR-6 | A first-time player's Play is gated on that sheet ("Got it, I'll play", `app.js:296,306`), so choosing Play the first time requires scrolling the full rules. | C | high |
| BR-7 | Reopening the sheet keeps the previous scroll offset (measured at 360x640: opened with the close button at y=-198). | C | low |
| BR-8 | Disabled "Start game" is 1.80:1 (§2.5). The reason is a 15 px secondary line under it (`index.html:164`), for example "Waiting for Ada, Bob, Cleo … to choose Play or Watch." or "2 players needed; 1 chose to play." (`briefing-host-undecided`, `briefing-host-too-few`). | D | high |
| BR-9 | The blocker names at most three people then "…", and names the Host in the third person on the Host's own phone (`core.py:436-438`). | C | low |
| BR-10 | Play/Watch selection is a border colour change and a tinted fill on an otherwise identical button (`party.css:284-295`); `aria-pressed` is set, no mark or word changes (`briefing-member-watching`). | D | med |
| BR-11 | Roster state is a 24 px badge with a 16 px icon (play, eye, hourglass), green, blue or grey (`party.css:270-277`). The word is present for screen readers only. Names truncate in 68 px columns ("Barthol…", `party.css:265,279`). | A | med |
| BR-12 | "How to play" and "Choose another game" are 38.4 px tall (§2.4). The party.spec target test covers `main` only, and the scene is outside `main` (`tests/offline/party.spec.ts:89`). | D | med |
| BR-13 | "Choose another game" ends the setup for everyone with no confirmation (`app.js:527-530`). A non-Host has no control but Play/Watch and "How to play", and reads "Waiting for Ada to start". | C | med |
| BR-14 | An away member appears dimmed with an hourglass and is left out of the blocker, since only members who are here must choose (`core.py:423-438`; `briefing-host-away-member`). | E | low |
| BR-15 | A phone is limited to Watch only in Limited Mode (`lib/limited.js:59-61`, `app.js:338-341`). In Full Mode a phone whose tile says "Not on this phone" can still choose Play. | E | med |
| BR-16 | Chat and the wider Party are unreachable from the scene: `main` is hidden while it shows (`app.js:350-353`). | B | med |
| BR-17 | In the game, the Host's fallback control is a text button "End game for everyone" appended to the game's header; a second tap within 4 s confirms (`lib/party-follow.js:87-117`; `game-stub-host-end-control`, `game-stub-host-end-confirm`). Starting has no confirm; ending has one. | C | low |

### 3.4 Arcade (structural only)

| ID | Observation | Cat | Sev |
|---|---|---|---|
| ARC-1 | The page has its own inline stylesheet and palette (`#15132b`, `#c7b8ff`, `#cbc5e0`; system-ui at 14, 16, 18 px; one 12 px radius; every button the same lavender fill) and shares no tokens with the shell (`arcade/index.html:7-20`). | A | high |
| ARC-2 | Portrait 390x844 stacks title and "Other games" (40 px), status line (22), "Enable sound" and "Leave" (48), video 366x275 (33% of the viewport height), controls (164), a hint paragraph, then 183 px unused. Controls sit in flow under the video, not at the thumbs (`arcade-portrait-390x844-viewport`). | B | high |
| ARC-3 | Landscape 844x390: title, status and the sound/leave row take the top 156 px (40%). The video box starts at y=156 and ends at y=406, past the viewport; the page scrolls (453 px). Controls are fixed over the video's lower corners (`arcade/index.html:19`; `arcade-landscape-844x390-viewport`). | B | high |
| ARC-4 | The viewport meta sets `maximum-scale=1,user-scalable=no`, pinch gestures are cancelled and text is sized in px (`arcade/index.html:4,10-16,45`). ACCESSIBILITY rule 4 forbids this. | D | high |
| ARC-5 | Before connecting, the 10 control buttons render at 45% opacity (3.02:1) around one bright "Play Gauntlet II" button over an empty black box. "Other games" is a 91x21 text link. | D | med |
| ARC-6 | The page is one game: "Gauntlet II" is written into the title, heading, button and messages, and the controls are a fixed d-pad plus Fire, Magic, Add coin, Start (`arcade/index.html:6,21,27,29-39,147-154`). | B | med |
| ARC-7 | Status copy is connection-centred: "Ready to play. Tap Play to connect.", "Can't connect right now. Stay on the Avrana Party Wi-Fi, then tap Play.", a home-network warning, "Try your regular browser at …/arcade/" (`arcade/index.html:22-23,167,269`; `arcade-portrait-after-play-no-stream`). | B | low |

## 4. Works today; preserve as behaviour

| Behaviour | Where |
|---|---|
| Presence is automatic once a profile exists; no Join or Leave; reopening restores the member. | `app.js:209-217,509-513` |
| One Party, one place: Home, setup, game; every phone follows; only the Host moves it; stale Host moves are re-checked once. | `lib/party-mode.js:56-66`, `lib/party-client.js:88-99` |
| The Host's Start is disabled with the reason in words beside it. | `app.js:344-347`, `core.py:427-443` |
| Play/Watch can be changed until the Host starts; Watch is never taken away. | `lib/limited.js:40-52` |
| The setup scene fits one phone screen with the decision at the bottom. | `party.css:232-238` |
| Rules open as a native modal `<dialog>`: Esc closes it and focus returns to "How to play" (measured). | `index.html:171-178`, `app.js:289-299` |
| First-time acknowledgement of a game's rules is remembered per game and version. | `app.js:278-286` |
| A re-render replaces only changed tiles, so keyboard focus survives a refresh. | `app.js:404-409` |
| Can't-reach is one panel with one action and recovers on the `online` event without a tap. | `index.html:80-85`, `app.js:575-583` |
| A missing or corrupt catalog never takes Home down; Retry is offered. | `lib/catalog-load.js` |
| Capability verdicts are per seat, with a plain reason; nothing reads the user agent. | `lib/evaluate.js` |
| Limited Mode: the mode comes only from Party Core; no padlock is shown; a blocked phone may still watch. | `lib/limited.js`, `app.js:74` |
| Text is in rem and zoom is allowed on the Party page; no sideways scroll at any tested width. | `index.html:5`, §2.1 |
| Text contrast is at least 4.89:1 for every enabled state; secondary text is at least 6.63:1. | §2.5 |
| All Home targets are at least 44 px; avatar cells are 75 px with a ring and a check. | §2.4, `party.css:164-178` |
| `prefers-reduced-motion` and `prefers-contrast: more` are honoured; focus rings are 3 px. | `party.css:88-96` |
| Every input has a label; icon-only buttons have names; names are set with `textContent`. | `index.html`, `lib/ui.js:9` |
| Offline rule: no remote fonts, icons or scripts; CSP forbids inline style and script. | `docs/UI-DESIGN-SYSTEM.md`, `avrana/web/devserver.py:174-181` |
| Ending a game for everyone needs a second tap within 4 s. | `lib/party-follow.js:27,104-117` |
| Arcade: drop recovery with a few quiet retries, and distinct words for full, idle, down and replaced. | `arcade/index.html:139-174` |

## 5. Screenshot index

Files are `<stem>-<width>x<height>-<kind>.png` in `current/` (outside Git);
kind is `viewport`, `full` (full page) or `el` (one element). "3 phones" means 390x844, 360x640
and 375x667. Files beginning `expo-` in that folder belong to another audit.

| Stem | Sizes and kinds | Shows |
|---|---|---|
| `party-firstrun` | 3 phones, viewport + full | Home with no profile: outlined "Choose your name", empty Party panel, "Choose your name to play" tiles |
| `party-profile-setup` | 3 phones, viewport + full | First-run profile form open: name field, 32 avatars, Save, photo upload |
| `party-profile-setup-filled` | 390, viewport | Form with a name and a chosen avatar (ring + check) |
| `party-profile-edit` | 3 phones, viewport; 390 full | Profile editor reopened by a member; "Profile saved…" note |
| `party-home-host-1` | 3 phones, viewport + full | Home as Host, alone |
| `party-home-host-4` | 3 phones + 844x390 + 820x1180, viewport + full | Home as Host with 4 members (one long name) |
| `party-home-member-4` | 3 phones, viewport; 390 full | Home as non-Host: "Ada is the host and picks the games." |
| `party-roster-away`, `party-roster-away-panel` | 390, viewport / el | A member away after 45 s: dimmed pill only |
| `party-home-member-with-limited-host`, `party-roster-limited-member-panel` | 390, viewport / el | Full Mode member's view of a Host marked "Limited" |
| `party-chat-open-mocked` | 390, viewport | Party Chat open with messages (chat server mocked, see §6) |
| `party-chat-open-reconnecting` | 390, viewport | Party Chat open with no chat server: "Chat is reconnecting…", Send disabled |
| `party-this-phone-open` | 390, viewport | "This phone" checklist and "Technical details" link |
| `party-loading` | 390, viewport + full | Loading: "Checking the connection…", skeleton tiles |
| `party-cant-reach` | 3 phones, viewport; 390 full | `#away`: "Can't reach the party", Try again |
| `party-catalog-error` | 390, viewport + full | Catalog failed: "Game list unavailable.", Retry, 0 games, empty state |
| `party-catalog-mode-no-party-core` | 390, viewport + full | No Party Core: tiles as direct Play links with live counts |
| `party-going` | 390, viewport | "Taking you to EXPO…" in-between screen |
| `library-top` | 3 phones, viewport | Library head as Host: search, people filter, view switch, first tile |
| `library-top-member` | 390, viewport | The same for a non-Host |
| `library-tile-bluff-host`, `-bluff-member`, `-bluff-favorite` | 390, el | BLUFF tile: Host, non-Host, starred |
| `library-tile-arcade-gauntlet2-host`, `-not-on-this-phone`, `-not-running`, `-full` | 390, el | Gauntlet II tile: Host; phone without the video format; arcade down; arcade full (last two without Party Core) |
| `library-tile-ps1-bomberman-host`, `library-tile-ps1-worms-host` | 390, el | Uninstalled experimental tiles |
| `library-not-on-this-phone` | 390, viewport | A tile that does not fit the phone, in context |
| `library-filter-6-people` | 390, viewport | People filter at 6: one game left |
| `library-empty-search`, `library-favorites-empty`, `library-recent-empty`, `library-favorites-one` | 390, viewport | Empty states and a one-item Favorites view |
| `briefing-host-undecided` | 3 phones + 844x390, viewport + full | Setup as Host, nobody chosen, Start disabled with blocker (844x390 run has 2 members) |
| `briefing-member-undecided` | 3 phones, viewport; 390 full | Setup as non-Host before choosing |
| `briefing-host-waiting-on-one` | 3 phones, viewport | Host view, one member still choosing |
| `briefing-host-ready` | 3 phones, viewport; 390 full | Host view, everyone chose, Start enabled |
| `briefing-host-too-few` | 390, viewport | Blocker "2 players needed; 1 chose to play." |
| `briefing-host-away-member` | 390, viewport | Setup with an away member |
| `briefing-member-watching`, `briefing-member-playing` | 3 phones / 390, viewport | Non-Host after choosing: "Waiting for Ada to start" |
| `rules-dialog` | 3 phones, viewport | "How to play BLUFF" sheet as opened |
| `rules-dialog-end` | 390, viewport | The same sheet scrolled to its end: "Got it" |
| `rules-dialog-first-play` | 390, viewport | The sheet as the first-time Play gate |
| `limited-home-host` | 3 phones, viewport + full | Limited Mode home with the notice |
| `limited-home-member-blocked-game` | 390, viewport + full | Limited Mode member whose phone cannot play Gauntlet II |
| `limited-notice` | 390, el | The notice alone |
| `limited-library` | 3 phones, viewport | Library in Limited Mode: "Works, with limits" tiles |
| `limited-this-phone-open` | 390, viewport | "This phone" in Limited Mode: "Some things are limited" |
| `limited-briefing-host` | 390, viewport | Setup scene in Limited Mode |
| `doorway-finding` | 390, viewport | HTTP doorway: "Finding your party…" |
| `game-stub-host-end-control`, `game-stub-host-end-confirm` | 390, viewport | Host's fallback "End game for everyone" and its "Tap again" state on a stub game page |
| `diag` | 390, viewport + full | Diagnostics page behind "Technical details" |
| `arcade-portrait` | 390, viewport + full | Arcade page before connecting |
| `arcade-portrait-after-play-no-stream` | 390, viewport | Arcade after tapping Play with no stream |
| `arcade-landscape` | 844x390, viewport + full | Arcade page in landscape |

## 6. Limits of this evidence

- Chromium on Windows only. `ui-rounded` and `system-ui` both resolved to Segoe UI, so the rounded
  heading face an iPhone shows is not in the screenshots. No real phone, Safari or WebKit run.
- The Party is simulated: real Party Core, stub game pages. Only BLUFF has a setup there. Results,
  Play again and in-game Party chrome are the games repository's and are not covered.
- The dev server has no chat service. `party-chat-open-mocked` uses a mocked `/chat/ws` that speaks
  the ChatHub messages the client expects; the reconnecting shot is the unmocked page.
- The BLUFF briefing text was served from the games repository's `games/bluff/web/onboarding.json`
  by request interception; the dev server returns a stub there.
- Service workers were blocked, so "Party page saved on this phone" and the offline copy were not
  shown. Can't-reach, loading, catalog-error, no-Party-Core and "going" were produced by
  intercepting or cancelling requests.
- Not captured: photo upload and crop, a launch failure note, a vacant Host ("Nobody is hosting
  right now."), "You can watch" and "Try anyway" tiles, host succession, a seat limited to Watch.
