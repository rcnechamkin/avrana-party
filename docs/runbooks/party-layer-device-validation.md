# Party layer: device validation (AVR-292, AVR-476)

Status: **PROPOSED owner-run procedure, NOT RUN on a phone or on the Pi** (2026-10-16). The layer
(PR #162, Games #84) passes Tier 2 tests: real Party Core, real BLUFF and EXPO pages, Chromium at
phone size on a laptop. That is not iPhone Safari, Android Chrome, Wi-Fi, the Pi's nginx or a
screen reader. Nothing here deploys or changes the Pi; run it after an approved deploy
([deploy.md](deploy.md)) of a Party build with #162 and a Games build with #84, which must be
deployed together (one merge set).

## Before you start

- Record `/party/version.json` (Party) and the Games SHA, the date, and each phone's model, OS and
  browser version.
- Phones, each with a saved profile, all on the Party Wi-Fi:
  - **A**: the Host, an iPhone with Safari.
  - **B**: an Android phone with Chrome.
  - **C**: a third phone (either), to watch and to type chat.
- Turn on, one run each: default text size, then the largest text size (iOS: Settings > Display >
  Text Size, and Accessibility > Larger Text; Android: Settings > Display > Font size and Display
  size at maximum).
- Screen readers: VoiceOver on A, TalkBack on B, for the lines marked **SR**.
- A laptop on the management network for `/party/api/state` (read only).
- Write PASS / FAIL / NOT RUN for every line, with a note. Photograph or screen-record failures.
  A line you could not run is NOT RUN, never PASS.

## What the source tests already show (do not repeat on a phone, but do not trust for a phone)

| Claim | Evidence | Where |
|---|---|---|
| The button mounts on a live BLUFF and EXPO round and after a reload; people and Host named | `tests/provider/party-layer.spec.ts` (real games server and Party Core) | Chromium 390 x 844 |
| Chat sent in the drawer, unread count on the other phone | same | same |
| BLUFF says nothing while the drawer is open and catches up on close | same | same |
| BLUFF's dialogs do not cover the button; table inert, Escape and focus return work | same, and Games `tests/bluff_layout_test.mjs` | same |
| Host End asks first; End takes everyone home and removes the layer | same | same |
| Offline shows a connection line and recovers | same (`setOffline`) | same |
| Game-origin page mounts the layer from a vendored copy; Host sees only End and Bring everyone back | `tests/offline/bridge.spec.ts` | Chromium, two host names, HTTP |

## 1. Touch gestures (A, then B)

Start a BLUFF round with A, B, C. Do each on the table, then on the results screen.

| # | Step | Expected |
|---|---|---|
| 1.1 | Look at the table | the Party button is visible at the right edge; nothing of BLUFF's controls is under it by default; the button is at least 44 pt |
| 1.2 | Tap it | the drawer opens: people (Host named), a Chat tab; BLUFF's table is still behind it |
| 1.3 | Tap Close | the drawer closes; the button is where it was |
| 1.4 | Long-press the button for about half a second, without moving | it lifts (grows); no iOS magnifier, text selection or "Save image" callout appears |
| 1.5 | Keep holding and drag to the middle of the screen, let go | it follows the finger without lag or page scrolling, and settles on the nearer side |
| 1.6 | Drag it into the left edge, then fling it into the right edge | it tucks into a tab with an arrow each time; tapping the tab brings the button back |
| 1.7 | Quit and reopen the page (reload) | the button is where you left it (per-phone position) |
| 1.8 | Swipe from the left edge of the screen (iOS back) with the button on the left | the button does not start a back navigation; the back gesture still works from the edge |
| 1.9 | Play a move with one hand while the drawer is closed | the button never blocks Income, Foreign Aid, Coup or the prompt buttons at their normal places; if it does, move it and note where |
| 1.10 | Open the drawer, scroll the people list and the chat | only the drawer scrolls; BLUFF's page behind does not move |

## 2. Safe areas and orientation (A: notch or Dynamic Island; B with gesture navigation)

| # | Step | Expected |
|---|---|---|
| 2.1 | Portrait, button at the top of its range | it stays clear of the notch and status bar |
| 2.2 | Portrait, button at the bottom | it stays clear of the home indicator and Android gesture bar |
| 2.3 | Rotate to landscape | the button stays inside the visible area and clear of the side cutouts; the drawer fits; its close button is reachable |
| 2.4 | In landscape open the drawer, then rotate back | still open and usable, nothing clipped |
| 2.5 | iOS Safari: the address bar collapses while you scroll the table, then returns | the button follows the visible viewport and is never half under the bar |

## 3. Enlarged text (largest setting on both phones)

| # | Step | Expected |
|---|---|---|
| 3.1 | Drawer open, People tab | every name readable and not cut off; the Host actions can all be reached by scrolling the drawer |
| 3.2 | Chat tab | the message field is visible above the keyboard (see 4.4) and Send is reachable |
| 3.3 | Host action confirmation (End) | the confirmation text and both buttons are visible without sideways scrolling |
| 3.4 | BLUFF table at the largest text | the Party button does not hide a required control; if it does, the player can move it (1.5) |

## 4. Keyboard, chat and focus

| # | Step | Expected |
|---|---|---|
| 4.1 | C types a message in the drawer's chat | A and B see an unread count on the button without opening the drawer |
| 4.2 | A opens the drawer, Chat | the message is there with C's name; the count clears |
| 4.3 | A sends a message | B and C get it; A's own appears once |
| 4.4 | Tap the message field | the on-screen keyboard rises and the field and Send stay visible (not covered); the page behind does not jump |
| 4.5 | Close the keyboard, close the drawer | the layout returns to normal; focus is on the Party button |
| 4.6 | Bluetooth or desktop keyboard on a phone or a tablet, if available: Tab into the page | focus reaches the Party button; Enter opens the drawer; Tab stays inside the drawer; Escape closes it |

## 5. Screen readers (SR; A with VoiceOver, B with TalkBack)

| # | Step | Expected |
|---|---|---|
| 5.1 | Swipe through BLUFF's table | the Party button is reachable and named "Your Party" (and "N new messages" when there are some) |
| 5.2 | Activate it | the drawer is announced as a dialog "Your Party"; focus moves into it; the table behind is not read |
| 5.3 | While it is open, C makes a BLUFF move | the drawer is not interrupted by the table's live announcements |
| 5.4 | Close the drawer | focus returns to the Party button; the table then announces what happened while the drawer was open (BLUFF catches up) |
| 5.5 | Chat arrives while the drawer is open on Chat | the new message is announced politely, once |
| 5.6 | Open BLUFF's rules (the ? button), then the Party button, then close the drawer | focus returns inside the rules sheet; Close or Escape on the sheet works; focus returns to the ? button |
| 5.7 | VoiceOver rotor / TalkBack reading controls: Host actions | each action is a labelled button; the confirmation is announced when it appears |
| 5.8 | Drag alternative | "Move the button to the other side" and "Tuck the button away" in the drawer work without any drag |

## 6. Host controls and lifecycle (A is Host)

| # | Step | Expected |
|---|---|---|
| 6.1 | A opens the drawer | A sees the Host actions; B and C do not |
| 6.2 | A taps End the round, then No | nothing happens; the round goes on |
| 6.3 | A taps Hand over hosting, picks B, confirms | B is now the Host and sees the actions; A no longer does; the round goes on for everyone |
| 6.4 | B ends the round for everyone (confirm) | every phone goes to Party Home together; the Party button is gone from the game page and does not flash over Party Home |
| 6.5 | Start BLUFF again, play to results | on the results screen the Party button is still there; "Stop hosting and watch" is offered to the Host only here (not mid-round); there is no mid-round Quit & Spectate |
| 6.6 | Host: Play again | everyone is taken to the setup scene; the layer is not shown on Party Home |
| 6.7 | Start EXPO | the button mounts on EXPO; People shows the two seats; End works |

## 7. Reconnect and Limited Mode

| # | Step | Expected |
|---|---|---|
| 7.1 | B: switch to another app for 30 s, come back | B is in the same seat; the button is there; chat caught up |
| 7.2 | B: lock the phone for 2 minutes, unlock | same; no duplicate button, no stuck frame |
| 7.3 | B: turn Wi-Fi off for 20 s with the drawer open, then on | the drawer shows a connection line while it is off, and clears it when Wi-Fi returns; people and chat are current |
| 7.4 | B: turn Wi-Fi off for 20 s with the drawer closed | the game's own reconnect line is shown; the Party button is not stuck over it; when Wi-Fi returns everything is as in 7.1 |
| 7.5 | Limited Mode (plain HTTP: join the Wi-Fi without the Full Mode certificate path) on one phone | the layer works for a first-party game with the same drawer; no bridge is assumed; or: NOT SUPPORTED, noted |
| 7.6 | Limited Mode phone: lose and regain Wi-Fi | as 7.3 |
| 7.7 | iPhone Safari with Private Browsing or "Prevent Cross-Site Tracking" on | the layer works for BLUFF and EXPO (same origin); record the result for a game on the game origin if one is installed |

## 8. Pi load (owner, with Beszel or the usual meter)

| # | Step | Expected |
|---|---|---|
| 8.1 | Four phones in a BLUFF round with the layer, chat active | CPU and temperature within the usual range; no under-voltage events (`vcgencmd get_throttled`, read once at the end, not by polling during the run) |
| 8.2 | Same with the arcade or PS1 **not** running | Arcade has no layer yet (D7): its integration waits for a measured stream cost; do not test it here |

## Sign-off

The layer is accepted for friend-ready play when lines 1.1 to 1.7, 2.1 to 2.3, 3.1 to 3.3, 4.1 to
4.5, 5.1 to 5.4, 6.1 to 6.5 and 7.1 to 7.3 PASS on both phones, and nothing under 8.1 is out of
range. Any FAIL is filed as a bug before sign-off. Record the results in the Linear issue for
AVR-292 and, for the Host's way out of a full-screen game, AVR-476.
