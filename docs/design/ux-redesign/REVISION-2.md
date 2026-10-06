# UX/UI redesign: revision 2, the cleanup pass

Status: **PROPOSED (2026-10-05). Design cleanup awaiting owner review; nothing here is implemented, accepted or scheduled.**

The owner approved revision 1's visual direction (the shell, the Library hierarchy and the EXPO
direction) and asked for one focused cleanup pass and an implementation plan. This file is the
pass: what changed, what was measured again, and what is still limited. The plan is
[IMPLEMENTATION-PLAN](IMPLEMENTATION-PLAN.md). Only prototypes, pictures and design documents
changed. The rest of the package is indexed in the [README](README.md).

## Where to look

| Sheet | Shows |
|---|---|
| [overview-9-cleanup-shell](screenshots/overview-9-cleanup-shell.png) | people over a briefing; the Limited sheet over a briefing; the compact grid on a Limited phone and with the arcade off |
| [overview-10-expo-enlarged-text](screenshots/overview-10-expo-enlarged-text.png) | EXPO at 200% text on 360 × 640: 14 cards, a burst, playing for Tonoja, the failed result |
| [overview-3-expo](screenshots/overview-3-expo.png), [overview-5-expo-results-objectives](screenshots/overview-5-expo-results-objectives.png), [overview-8-enlarged-text](screenshots/overview-8-enlarged-text.png) | rebuilt, because the result's controls and the enlarged-text layout changed |

New pictures are in `concepts/`, kept outside Git ([README](README.md#pictures-that-are-not-in-git)), with names starting `r2-` (37). Twenty-seven
earlier pictures were re-taken because what they show changed: every EXPO result, every EXPO
enlarged-text picture and the three below-the-floor pictures. One was removed
(`r-expo-text200-play-end`, which the new default view replaces). The review board,
`prototypes/index.html`, has a wall "Revision 2: the cleanup pass".

## What was asked, and what was done

| # | Asked | Done | Evidence |
|---|---|---|---|
| 1 | Party access and the Limited explanation open over the briefing, preserving its location | Both open in place on every shell page, the briefing included; nothing navigates. The Party control brings the drawer down over the page and says, on a briefing, "The Party is getting ready for BLUFF. Close this to answer." The Limited mark, and "What this means" on Home's notice, open one sheet: on a briefing for an affected game, first what this phone does this round, then the three required facts. Closing either returns to the same page at the same place; focus goes into what opened and back to the control that opened it. `?chat=off` shows the first slice, people only | `r2-briefing-party-people-*`, `-guest-*`, `-chat-*`, `-host-away-*`, `-text200-*`; `r2-briefing-limited-sheet-*`, `-gauntlet-*`, `-bluff-*`, `-text200-*`; `r2-home-limited-sheet-*`, `r2-library-limited-sheet-*`, `r2-library-party-people-*`, `r2-game-party-people-*` |
| 2 | Unavailable games shown consistently in the compact grid | Compact drops the descriptive line and keeps the consequence line, in the same words as every other view: "Watch only on this phone", "Not on this phone", "Off for now" | `r2-library-compact-limited-*`, `-degraded-*`, `-degraded-guest-*`, `-limited-degraded-*`, `-text200-*` |
| 3 | EXPO's enlarged-text layout improved, with no cap on text scaling | Rebuilt. One scrolling column (mission, crew, every objective, the trick, then the instruction and the hand) with only the action keys pinned. Nothing scrolls inside anything else. It opens with the hand just above the keys and the trick above the hand; a burst opens at its instruction, with your cards under it and the choices under them. Hands of 13 and 14 and Tonoja's cards keep rows of seven from 360 px wide, so 14 cards are two rows at any text size. Ranks grow with the setting (28, 31, 34 px). A burst is a step in the same column with Cancel and Send pinned. On the result only the Host's choice is pinned; "Look at the table" and "End EXPO for everyone" follow the evidence. The order is set in the document, not only on screen. The below-the-floor fallback uses the same column | `r-expo-text150-*`, `r-expo-text200-*`, `r2-expo-text150-*`, `r2-expo-text200-*`, `r-expo-below-floor-*` |
| 4 | The Host hand-over description corrected to include the active-game exception; existing lifecycle preserved, mission selection included | **The rule, as built:** a Host with no Party request for 45 s shows as Away, and 30 s later the role passes to the earliest-joined member who is present, a Full Mode member first. **The exception:** a Host who holds a place in the round that is on, as a player or a watcher, counts as playing, is never Away, and keeps the role however long their phone is silent (`avrana/party/core.py:15-17,223-226,237-238,268`). It covers a round that is on, not a briefing, a start in progress or held results. The drawn states (Home, the Party page, the briefing) are ones where the rule applies; it also applies on held results, which are the game's page and are not drawn. In a round an absent Host is an absent seat with no hand-over line, and no member can end the round for them: only the game ending it by its own rules moves the Party. Nothing about the lifecycle is proposed to change. **Mission selection:** the first package and revision 1 had drawn "Try mission 7 again", a "Next mission" with no picker and a "Party Home" button on EXPO's result. All three changed today's lifecycle and are withdrawn. The result again offers what the game offers: "Retry same tasks" and "Retry new tasks" after a failure; a picker of the open missions and "Next mission" after a success; "End EXPO for everyone" for the Host; "Look at the table" for anyone; "Waiting for Dana (Party Host) to choose what's next." for the rest (`client.js` `drawResult`, Games `a448972`). EXPO's own setup before the first deal is not drawn and stays as built | [BACKEND-GAPS](BACKEND-GAPS.md) D9 and decisions 17 and 19; [SCREENS](SCREENS.md) section 7; `07d-expo-result-*`, `r-expo-result-*`, `r2-expo-result-success-*` |
| 5 | The changed cases revalidated and the report updated | See [Revalidation](#revalidation) | |

## What is still limited

- **A briefing with the drawer open is not a briefing you can answer.** The scrim covers Play
  and Watch. If the Host starts while someone has the drawer open, the product must close it;
  that is specified, not drawn.
- **The Party control on a briefing still contradicts two accepted documents** until they are
  amended: GAME-UX-CONTRACT rule 3.2 and ADR 0011 decision 4. The owner's direction settles the
  design; the wording is slice 0 of the plan.
- **In the first slice the drawer has people only over a briefing.** Chat there waits for
  Party-owned chat.
- **Compact tiles get taller where a consequence wraps.** "Watch only on this phone" is two
  lines under a four-across cover; rows stay aligned and nothing is cut.
- **Limited Mode's consequence lines depend on what each phone reports**, not on the mode
  alone. No title requires a secure context today, so on most Limited phones no title is
  blocked. The pictures show the case where two are.
- **EXPO at 200% on 360 × 640 is better, not good.** The hand, the winner line and the keys
  are together on screen, but the column is two to three screens long, so mission, crew and
  objectives are a swipe away. A burst shows its instruction and every card on opening, and
  the choices for the chosen card are one scroll below. Ranks grow only from 28 to 34 px, and
  in rows of seven the suit word stays 12 px, so the rank and the shape carry the suit. At
  320 px wide a 14-card hand is three rows of six. The result's pinned choice takes 21 to 25%
  of the screen.
- **The compact grid still drops the "Max 2" seats mark.** There the "Not for four" heading
  is the only sign that a title does not fit.
- **The result is not the real client line for line.** The controls and what they do are
  today's. Left out or different in presentation: the line "You are the Party Host: you choose
  what happens next.", the share button after a success (EX-43), the order of the two quiet
  controls, and End's confirmation step, which the owner has decided should become Cancel /
  End Game (GAME-UX-CONTRACT Q6) and is not drawn.
- **EXPO's undrawn states** (its own setup, task selection, predictions, distress, menus) have
  no enlarged-text design yet. The plan makes that a design step before slice 2.
- **Still open from revision 1 and untouched here:** Home's fourth tile in a Limited row is off
  screen until scrolled; the first-run page has no Limited mark; EXPO's objectives sheet does
  not move focus at normal text size; EXPO's identity still wants human-made or licensed art;
  the pylon in the window deserves the owner's eye.

## What kind of check this was

Pictures and measurements were taken in desktop Chromium at phone sizes. Enlarged text is a
scaled root font size, not a phone's text setting. Nothing was tried on a real phone, in Safari
or with a screen reader. The plan lists those checks per slice.

## Revalidation

Three independent checks ran. None of the agents that ran them built the revision, and none
changed a file.

**The changed prototype cases** were measured by a separate agent with its own script: 458
page loads in desktop Chromium at 390 × 844, 390 × 664, 360 × 640, 844 × 390 and 320 × 568, and
564 real open-and-close cycles of the drawer and the sheet. Verdict: all four changes largely
hold; no P0 or P1, five P2 and eight P3.

What it confirmed with its own numbers:

- **Over the briefing.** No navigation or reload in any cycle. The briefing stayed rendered
  behind, and its scroll position was identical after all 564 closes. Close, the scrim and
  Escape each closed it every time. Focus moved to the opened heading every time. The Limited
  sheet held all three facts in 76 of 76 loads, and the this-round line was on screen on opening
  for Worms and Gauntlet II and absent for BLUFF. Home, Library, Party, System and game detail
  behave the same way.
- **Compact grid.** The same words as the medium and large grids in every case, at both sizes,
  for the Host and everyone else, at 100% and 200%; 11 px (22 px at 200%), two lines, never cut.
- **EXPO at enlarged text.** One vertical scroller in 101 of 102 loads (the exception is the
  objectives sheet opened by its switch, which has no control at enlarged text). No horizontal
  overflow. Document order matched visual and focus order in 84 of 84. Every card could be
  brought above the keys. Cards at least 44.6 × 60; 14 cards are seven and seven at 360 and
  390 px, and six, six and two at 320 px. At 200% on 360 × 640 the pinned keys take 15.8 to
  17.3% of the screen with no inner scroll: **the 55 to 80% self-scrolling tray is gone.**
- **EXPO at normal text did not regress** (68 loads): no zone overlap, nothing clipped or off
  screen. The below-the-floor column at 375 × 553 and 320 × 568 (34 loads): one scroller, cards
  at least 46 × 54. That fallback had only been looked at in pictures before.
- **The result.** The controls and labels match the real client's `drawResult` for the Host and
  for everyone else, after a failure and after a success; no "Party Home" and no "Try mission
  again". All four outcome rows reachable at five sizes.

What it found, and what was done afterwards:

| Found | Done |
|---|---|
| P2. At 200% the result's verdict text painted over the Retry keys on a 320 × 568 screen, and cleared them by only 12 px at 360 × 640 | The pinned block now sits above the page and holds only the Host's choice; the two quiet controls follow the evidence. Re-measured by the author: no key covered at either size; the pinned share fell from about 33% to 21 to 25% |
| P2. At enlarged text a burst opened on its choices with the hand cut off above and the instruction off screen | A burst now opens at its instruction. Re-measured by the author at 150% and 200% on three sizes: the instruction is on screen in 12 of 12, every card is whole in 11 of 12 (12 of 14 with 14 cards at 200% on 320 × 568) |
| P2. The Party page's "Party chat" row went to Home, and showed even with no chat | It opens the drawer in place and is absent while there is no chat |
| P2. Closing by the scrim dropped focus, and Tab could reach the page behind | Focus returns to the control that opened it, and Tab stays inside. Author-checked on seven page-and-control pairs |
| P2. The "Limited" tag was cut off in the people list at 200% on 360 px | The row wraps |
| P3. The Limited mark's hit area was 42 px tall | 46 px (44 px where only the icon shows) |
| P3. A link inside chat could take a phone off a briefing | No link there on a briefing |
| P3. With a title both off and unplayable on this phone, the list showed two lines and the grids one | The list shows one, as the grids do |

The right-hand column was checked by the author with a small script and new pictures. The
validator did not measure those fixes again.

Left as found: the Limited sheet at 200% leaves only a 40 px strip of scrim to tap, though Close
and "Back to the briefing" are both there; enlarged text enlarges card ranks only a little; the
compact grid drops the "Max 2" mark; the Burst panel scrolls 4 px inside itself at normal text
on 360 × 640; the presentation differences on the result listed above. Not checked by anyone:
landscape at enlarged text, safe-area insets, the on-screen keyboard over the message field.

**The plan and the corrected descriptions** were checked against both repositories by a second
agent, read-only. It found every cited location real and most claims sound, and these errors,
all corrected: the plan had promised a Quick start in slice 1 although no game ships those
steps; it had called an EXPO stand-in cover free although covers go through
`contracts/artwork.json`; it listed arcade seating by role as missing although the arcade
already does it; the Host rule said nobody could end a round while the Host was away, which is
true of members and false of the game itself (BLUFF can finish or abandon a round); and
BACKEND-GAPS said briefings for Arcade titles would reverse ADR 0011 decision 1, which they
would not. It confirmed the Host rule's numbers and exception, the EXPO result's labels, that
slices 1 and 2 need no server or engine change, and the bridge's verb list.

**Repository check.** `python tools/repo-check.py` passes. Nothing outside `docs/` changed. No
test suite was run for this pass, because no product file changed.
