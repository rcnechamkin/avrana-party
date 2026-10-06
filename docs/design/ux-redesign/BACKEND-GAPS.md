# UX redesign: backend and state implications, and open owner decisions

Status: **PROPOSED (2026-10-05, revision 2). Design-phase list for owner review; no backend change is made or scheduled by this file.**

What the [screen concepts](SCREENS.md) need from Party Core, the catalog and EXPO, sorted by
whether it exists. Evidence for every "exists" and "missing" is in the
[state inventory](audit/STATE-INVENTORY.md) (source at Party `578534f`, Games `a448972`) and the
[EXPO audit](audit/EXPO-AUDIT.md). Nothing here is implemented, and nothing here invents
architecture beyond the smallest change the screen needs.

## Required: the concept cannot be built without it

| # | Need | Used by | Smallest change | Today |
|---|---|---|---|---|
| R1 | Game metadata for the Library: approximate length, kind of game, how you play (co-op, versus, teams, free-for-all), and the shelf tags Quick and Classics | Library tiles, list, filters, tabs; game detail facts | optional descriptive fields per Game Contract, copied into the catalog by `avrana/contracts/catalog.py`; a closed, short vocabulary | no field exists for any of them. Players (`players.min/max`) and display (`screen`) exist |
| R2 | A Quick Start per game (three short steps) and structured rules | game detail, briefing | adopt the drafted `avrana.onboarding/v1` (GAME-UX-CONTRACT §5.2) or a subset; EXPO ships no `onboarding.json` at all | v0 (`premise`, `rules`) exists for BLUFF only |
| R3 | Party-owned chat | social drawer, unread count on the Party control | chat state and routes in Party Core, with Party identity | Party Home talks to the retiring LAN Games chat hub (`/chat/ws`), which has its own identity and no moderation; Core has no chat |
| R4 | Cover art for every title | Library, Home, detail | human-made or licensed covers in the existing square slot (`contracts/artwork.json`) | 3 of 5 catalog titles have artwork; EXPO has none |

R3 is required only for the chat half of the social layer. Presence, the People tab and the
Party control work from the existing view.

## Required only if the owner wants the feature

| # | Need | Used by | Smallest change | Today |
|---|---|---|---|---|
| C1 | Suggestions ("Sam wants to play EXPO") | detail page for non-Hosts, toast, chat stream | one advisory record per member in Party Core, cleared when the Party moves; it never moves the Party (ADR 0011 decision 1) | nothing exists; the voting model is undecided (brief §29) |
| C2 | A briefing for games that declare no pregame (arcade and PS1 titles) | the flow Library, detail, Ready / Watch, Host Start | `pregame: true` on those contracts, or a decision that they keep launching straight from the detail page | ADR 0011 decision 1: "→ game for a game without a pregame" |
| C3 | A Party layer during play (chat, presence over a game) | not drawn in the concepts | amend ADR 0011 decision 5; add roster and chat to the bridge's verb set (ADR 0013) | the game owns the viewport; the bridge carries no roster or chat |

## Desirable: the concept works without it, and is better with it

| # | Need | Why | Today |
|---|---|---|---|
| D1 | Party-wide "recently played" with a time | Home can say "You played 25 minutes ago" for the whole Party, and a phone that just joined sees it | Core keeps one session, in memory, with no timestamps. A per-device list is possible without it (F3) |
| D2 | A player-impact sentence for each degraded reason in `/party/api/status` | the Host notice should not be assembled from operator strings ("arcade unreachable") on the phone | `summary.reasons` are operator strings; the diagnostics page is the only reader |
| D3 | Each member's round role in the view during play and results | the People tab can say who is playing and who is watching | roles are in the view only during `setup` |
| D4 | Per-device preferences handed to game pages | reduce motion, sound and vibration set in System reach a game on another origin | games read their own per-browser flags; ADR 0013 keeps storage separate per origin |
| D5 | EXPO: the mission's objective sentence and its state from the server | the mission stage shows it; today the client owns that text (EXPO audit EX-31) | client-owned |
| D6 | EXPO: a server sentence for why Burst Transmission is unavailable | the Burst key's disabled reason (EX-30) | no reason is sent |
| D7 | EXPO: identify the Party Host's seat by id, not display name (EX-35) | the Host tag in the crew sheet | matched by name |
| D8 | EXPO: which of Tonoja's columns still hide a card | the Tonoja hand could draw each covered card where it is; today the concept can only give a count ("6 up, 6 covered") | the view sends face-up cards and `null` gaps only |
| D9 | When the Host went away, and who is next | "Hosting passes to Sam in 20 seconds" instead of "if Dana isn't back soon" | the view carries neither. The rule: a Host with no Party request for 45 s shows as Away; 30 s later the role passes to the earliest-joined member who is present, a Full Mode member first (`core.py:60-61,244-251,263-271`). **Exception: a Host who holds a place in the round that is on, as a player or as a watcher, counts as playing, never as Away, and keeps the role however long their phone is silent** (`core.py:15-17,223-226,237-238,268`); the game owns that disconnect. The exception covers a round that is on (`active`), not a briefing, a start in progress or held results. With nobody present the role is vacant until the next member arrives (`core.py:271,343-345`); an explicit Leave passes it at once (`core.py:360-369`); a Host who comes back does not get it back unless it is handed back (`POST /party/api/host`), falls vacant, or passes on again by the same rule |

## Frontend or per-device only

| # | What | Note |
|---|---|---|
| F1 | Bottom navigation, the Party control, the drawer's People tab, the briefing layout, the System page | all from the existing view: `members`, `me`, `host`, `location`, `mode` |
| F2 | Library view (large, medium, compact, list), sort and filters remembered per browser | `localStorage`; none is stored today |
| F3 | Favorites and a per-device "recently played" | `lg-favorites` exists; `lg-recent` exists but misses Party rounds, so the shell would record a round when the location changes |
| F4 | "Great for four", fit sorting, the seats mark, the mismatch sentence | `players.min/max`, `spectators` and the member count are in hand |
| F5 | Host-only, dismissible degraded notice | `/party/api/status` plus `me.host`; dismissal kept per browser. Host-only is presentation, not access control |
| F6 | Limited Mode tag, folded notice, per-game "watch-only here" | `view.mode`, the capability report and seat evaluation exist |
| F7 | Neutral Host tag, receding profile, first-run page | presentation |
| F8 | Motion, sound and vibration switches on the Party pages | system media queries are honoured today; switches are new, per device |
| F9 | EXPO presentation | every fact on the concept is already in the view |
| F10 | Reconnecting and out-of-reach states | the shell already knows when its long poll fails; the step from "reconnecting" to "can't reach the Party box" is a client timer (proposal). EXPO's client today keeps the last view and silently drops what is sent; the concept disables Play and Burst and says why |
| F11 | Unavailable-game lines in the Library and on detail | from the same capability report and status the Home notice uses (F5, F6) |
| F12 | Enlarged-text layouts | CSS; the product needs a real threshold (an `em`-based query), which the prototypes fake with a switch |

## Already supported

- Presence, Host, hand-over of hosting (`POST /party/api/host`), member mode, one location.
- Ready / Watch choices, the start blocker sentence, Host Start, Choose another game, End.
- Player-count and display facts per game; the per-phone fit sentence.
- EXPO: `trick_leading` (the engine's own winner of the cards so far), `last_trick`,
  `resolving`, `tasks[].state`, `result {status, reason}`, `cause {…}` with the objective, the
  triggering seat and card, `me.legal_cards`, `me.play_reason`, `me.communication_options`,
  `lifecycle_reasons`. The EXPO concept needs no engine change.

## Where the brief and an accepted decision meet

The concepts were drawn to stay inside accepted decisions wherever the brief allows it. Each
row below is a place where they pull apart; none is resolved here.

| # | Brief | Accepted decision | What the concept shows |
|---|---|---|---|
| X1 | Chat reachable from briefings (§11) | ADR 0011 decision 4: the setup is a "full-screen scene"; GAME-UX-CONTRACT rule 3.2: the library, chat row and "This phone" "MUST NOT be visible in it" | no bottom bar and no embedded chat on the briefing; the Party control stays in the top bar |
| X2 | Chat and presence over games (§10.1, §11) | ADR 0011 decision 5: "The game owns the viewport during a round"; ADR 0013: the bridge has a closed verb set | nothing drawn over EXPO |
| X3 | Library, detail, Ready / Watch, Host Start for a game (§17) | ADR 0011 decision 1: a game without a pregame goes straight to the game | the briefing is drawn for a pregame title (BLUFF); see C2 |
| X4 | Degraded notices normally Host-only and dismissible (§13.1) | ADR 0012 decision 4: "Limited Mode is visible and understandable... never pretends to be Full Mode"; D4: each member's mode is visible to the party | a phone's own Limited Mode is always marked on that phone and can only be folded, not dismissed; the notice keeps the three facts LIMITED-MODE §3.9 requires (not private, what is missing, how Full Mode returns); appliance trouble is Host-only and dismissible |
| X5 | "Ready / Watch" (§10, §17) | ADR 0011 decision 4: "Play this round / Watch this round" | the accepted labels, "Play this round" and "Watch this round", at equal size; the chosen one reads "Playing this round" or "Watching this round"; the line-up says Playing, Watching, Choosing |
| X6 | Continue or resume on Home (§8) | ADR 0011 decision 3: no offers, no "Rejoin"; Party Home cannot be browsed during a round | Home only exists between rounds, so it offers what to play next, not a way back into a round |
| X7 | Favorites, preferences, profile (§9, §14.2) | AGENTS: a browser-stored name and avatar is not a durable Profile; ADR 0012 D3: a Limited phone "joins again as a new device" | everything personal is per device and described that way |

## Recommendations on the three consequential decisions (revision 1)

Proposals, not decisions. Each names what it would change in an accepted document.

**Decision 1, social access during a briefing. Recommended: yes, through the Party control
only.** A briefing is the moment people ask each other "are you in?". The control opens the
drawer over the briefing and moves nobody; the bottom bar, the Library and "This phone" stay
absent, so the screen still reads as the game's pre-round screen. (Drawn in revision 2,
at the owner's direction: `r2-briefing-party-*`.) It needs one changed sentence
in GAME-UX-CONTRACT rule 3.2 (today the chat row "MUST NOT be visible" there) and no change to
ADR 0011's one-location rule. Until Party-owned chat exists (R3) the control shows people only.
The alternative is to leave briefings with no Party chrome, as accepted today; the cost is that
chat goes quiet exactly when the Party is deciding.

**Decision 3, briefings for Arcade and PS1 titles. Recommended: yes, but as the second slice.**
Seats are scarcest there (Gauntlet II seats two of four), a Limited phone needs its Watch
answer before the stream starts (ADR 0012 decision 3), and "TV or phone, which controller" is
worth one screen. One flow for every title is also simpler to learn. Declaring a pregame on
those titles reverses nothing: ADR 0011 decision 1 already sends a pregame title to a briefing
and any other straight to the game. Only requiring a briefing of every title would reverse it
and the game UX contract's Q10 ("Must every title have a briefing? No"), and that is not
proposed. It costs `pregame: true`
on three contracts and a check of how arcade seats follow Play and Watch answers (ADR 0009 and
0010), so it should not hold up the first slice. In the first implementation those titles keep
the accepted behaviour (the Host's start goes straight to the game) and the detail page says so
on the button's line. That wording is not drawn. The prototypes do draw briefings for Worms
and Gauntlet II, to show Limited Mode and an off game on a briefing; those pictures belong to
the second slice. The alternative is to keep the accepted behaviour for good.

**Decision 2, a Party layer during play. Recommended: later, not in the first implementation.**
It needs an amendment to ADR 0011 decision 5 ("the game owns the viewport"), new verbs on the
ADR 0013 bridge, a geometry the brief leaves undecided (§29), and a chat backend that does not
exist yet. The first implementation already carries the shell, the Library and EXPO. Until
then nothing is drawn over a game, the Host's End stays in the game's own menu, and unread chat
waits for the result or the return to Home. What can be done early is the decision itself: an
ADR amendment that fixes the geometry and the verbs before any game is built against it.

## Open owner decisions

Only what the concepts could not settle from the brief, the ADRs or the code.

**Owner answers of 2026-10-05, for slice 1** (recorded in the plan's
[slice 0](IMPLEMENTATION-PLAN.md#slice-0-decisions-and-wording)): decision 1 is settled and its
wording change is made (Rule 3.2, ADR 0011 amendment); decision 12 is settled as today's
behaviour (listed, marked "Not installed"); decision 16 is settled. Decision 2's geometry is a
separate design task and nothing in slice 1 waits for it. As of that date, decisions 4, 7, 9, 15 and 18 were
**not answered** (the next paragraph is later): slice 1 was approved as drawn, so it builds them as drawn, provisionally, and
each is raised again in the pull request that builds it. Decision 4 reads an accepted ADR and
wants an explicit yes before PR 1.4 folds the notice. Everything else below is open as well.

**Owner answers of 2026-10-06** (the questions and the owner's words are in the plan's
[slice 0](IMPLEMENTATION-PLAN.md#owner-answers-of-2026-10-06)): decision 7 is settled, the top
edge. Decision 4's reading, "notice on Home, small mark everywhere else", is "Correct"; the
folded notice and the Host's notice were asked in the same breath, so PR 1.4 states them again
before building them. Decisions 9 and 15 are built in PR 1.2 as its issue (AVR-285) directs,
per phone and shown to everyone, and are disclosed there. Decision 18 is still not answered.

1. **The Party control on the briefing** (X1). Owner direction (revision 2): keep it, and it
   opens over the briefing. The wording change in GAME-UX-CONTRACT Rule 3.2 and the dated note on
   ADR 0011 decision 4 are written in the slice 0 pull request, which is the owner's to merge.
2. **A Party layer during play** (X2, C3). Wanted for the first implementation, or later? It
   needs an ADR amendment either way, and its geometry is a brief §29 item.
3. **Does every game get a briefing** (X3, C2), or do games without a pregame keep going
   straight from the detail page into play?
4. **Limited Mode visibility** (X4, audit PS-34). *Owner, 2026-10-06: "Correct", to "notice on Home, small mark everywhere else"; the fold and the Host's notice are restated in PR 1.4.* Is "always marked on the affected phone,
   foldable, with the three required facts in plain words; appliance trouble Host-only and
   dismissible" the right reading of both the brief and ADR 0012? The "Limited" tag is drawn
   under your own face on the Party page; beside other members' names (PS-35, ADR 0012 D4) it is
   not drawn and stays as accepted.
5. **The round-choice words** (X5). "Play this round / Watch this round" as accepted, or the
   brief's "Ready / Watch"?
6. **Suggestions** (C1). Show "Suggest to the Party" in the first implementation as a plain,
   advisory nudge, or leave the control out until the voting model is designed?
7. **Where the social layer opens from.** *Settled, 2026-10-06: the owner, "Top edge".* The concept brings it down from the top edge; a bottom
   sheet is the alternative. This touches the undecided Party HUD geometry.
8. **EXPO direction.** Three departures from the build that the owner should accept or reject by
   name: the live status line moves from above the board to the top of the hand tray; the
   palette moves from warm dusk gradients to matte graphite with one amber signal colour and
   full-colour cards; the Captain is the word "Capt" in the crew strip. The EXPO audit
   also raises content questions the concept cannot answer: what the trump suit, the dummy
   seat and the radio token are called in the expedition fiction (EX-40; the concept keeps
   today's "submarine" and "burst"), whether missions get names (EX-48), and whether landscape
   is supported (EX-44; a split layout is sketched in the prototype).
9. **Recently played**: per device (free) or Party-wide (D1)? *Built per device in PR 1.2, as
   its issue (AVR-285) directs; Party-wide stays D1, for later.*
10. **Library metadata vocabulary** (R1): the owner or game authors need to name the short list
    of kinds and the length for each title before filters mean anything.
11. **A deliberate hand-over of hosting** (Party shell audit PS-20). The route exists
    (`POST /party/api/host`) and no control does. The concept draws a row on the Party page,
    "Hand hosting to someone else", for the Host only. Wanted?
12. **Titles that are not installed or not running** (LIB-22). List them for players as
    unavailable, or show only what can be played tonight? Not drawn.
13. **Leaving a briefing.** The concept gives only the Host a way out ("Choose another game");
    everyone else can choose Watch but cannot go back to browsing while the Party is on a
    briefing, which is what ADR 0011 says today. Keep it that way?

14. **EXPO questions the drawing answers.** The EXPO audit raised these as owner questions; a
    board cannot be drawn without picking one answer each, so each needs a yes or no:
    the Host's End lives in the table menu and on the result, not beside Play (EX-41); the
    "AVRANA PARTY" wordmark is not shown during play (EX-42; the game UX contract's E-6 already
    points this way); "not your turn" keeps the hand in full colour while "this card is
    illegal" darkens it (EX-45); Party avatars appear on the board (EX-46).

15. **An unavailable game and everyone who is not the Host.** *Built in PR 1.2 as its issue
    (AVR-285) directs: "Off for now" under the title, for everyone.* The brief sends degraded notices
    to the Host. The concept keeps the notice Host-only but shows "Off for now" under the
    affected title to everyone, and stops a non-Host suggesting it, so that a game that cannot
    start does not look startable. Right reading?
16. **The Limited mark on a briefing.** Settled in the drawing at the owner's direction
    (revision 2): the mark opens a sheet over the page that is open, on every shell page and
    the briefing, and nothing navigates.
17. **The Host going away.** Drawn from today's rule, which this pass preserves: a Host with no Party request for 45 s shows as Away; 30 s later the role passes to the earliest-joined member who is present, a Full Mode member first (`core.py:60-61,244-251,263-271`). **Exception: a Host who holds a place in the round that is on, as a player or as a watcher, counts as playing, never as Away, and keeps the role however long their phone is silent** (`core.py:15-17,223-226,237-238,268`); the game owns that disconnect. The exception covers a round that is on (`active`), not a briefing, a start in progress or held results.
    So a Host whose phone sleeps for 75 s on Home or on a briefing loses hosting, and gets it
    back only if it is handed back, falls vacant or passes on again. A Host whose phone sleeps
    during a round keeps it, and until they return no member can end the round or move the
    Party; only the game ending the round by its own rules does (EXPO waits for the seat;
    BLUFF plays it on autopilot, can reach a winner, and abandons an empty table). Once a
    round is over and its results are held, the exception has ended and the 75 s run from the
    round's close. The drawn
    states are Home, the Party page and the briefing, where the rule applies; in a round an
    absent Host is drawn as an absent seat (`r-expo-seat-away-*`) with no hand-over line. Open
    questions, not changes: should the view carry the countdown and the successor (D9), and is
    the in-round exception the behaviour wanted when a Host leaves for good? Related to
    decision 11.
18. **Reconnecting.** *Not answered; provisional in slice 1.* How long before "Reconnecting" becomes "This phone lost the Party box" is
    a client timer the concept invented (F10).
19. **EXPO revision choices.** The objectives sheet does not block the tray; an open objective
    reads "In play" (today "Active"); with two players on a short screen no objective rows stay
    on the board. Revision 2 withdrew two lifecycle changes the earlier drawings made without
    approval: the result again offers today's "Retry same tasks" / "Retry new tasks" after a
    failure and today's mission picker with "Next mission" after a success, and ending EXPO is
    "End EXPO for everyone", not a "Party Home" button (EXPO's mission result is not a Party
    `results` location). Any change to these needs separate approval.
20. **Enlarged text in EXPO.** Settled at the owner's direction (revision 2): text scaling is
    not capped. The layout was rebuilt as one scrolling column with only the keys pinned, which
    satisfies ACCESSIBILITY MUST 4 ("the layout must scroll rather than clip at 200 % text").
    What remains poor at 200% on the smallest screen is listed in REVISION-2.

Where the other audit questions went: LIB-23 is decision 9 and LIB-24 is decision 6. EXPO's
share card (EX-43) and standalone lobby (EX-47) are not touched by this package and stay open
in the [EXPO audit](audit/EXPO-AUDIT.md).
