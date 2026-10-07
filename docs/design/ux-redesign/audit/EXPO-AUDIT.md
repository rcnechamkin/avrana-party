# EXPO frontend audit (current state)

Status: **audit evidence (2026-10-05); observations of avrana-party-games origin/main a448972, design input, not contract.**

Scope: the EXPO phone client as built (`games/expo/web/`), the view it draws (`games/expo/engine.py`,
`games/expo/game.py`) and the LAN Games donor files it loads (`web/shared.css`, `web/hubnet.js`,
`web/brag.js`, `web/avrana-integration.*`). Evidence is `file:line` in that export, or a screenshot in
`current/`, kept outside Git since 2026-10-05 ([README](../README.md#pictures-that-are-not-in-git); named `expo-NN-…-WxH.png`; method in section 7).
Pixel figures are measured in headless Chromium from the real client drawing real engine views.
Nothing here is a design proposal. Categories: **A** visual, **B** information architecture,
**C** interaction, **D** accessibility, **E** backend/state gap, **F** product question for the owner.

## 1. Summary

1. The state boundary is sound and worth keeping: one server view, intent-only sends, a fenced presentation director, server-worded reasons, and the current winner of an unfinished trick as the public field `trick_leading`.
2. The look is the LAN Games kit recoloured: Sora and JetBrains Mono, the cyan-to-violet gradient primary button, navy secondary buttons, the pill toast and the pink reconnect banner all come from `web/shared.css` and `web/hubnet.js`; `expo.css` overrides sizes, not identity.
3. The AVR-267 "wasteland" layer is a placeholder gradient, ridge polygon and haze inside the mission stage only (15.5 to 18 % of the screen). No field-equipment framing exists anywhere. It is far from the brief's direction.
4. Cards are not the primary object today: hand cards are 58 x 46 to 60 px with a 20 to 23 px rank, and the whole hand is drawn at 50 % opacity whenever the player cannot play (most of the time).
5. The five zones exist, in order, and fit one viewport at 390x844, 375x667 and 360x640. Zone D shows two tasks (one on screens of 700 px or less), truncated; everything else about tasks is in a sheet.
6. Landscape is broken: at 844x390 the trick zone collapses to 0 px and the dock (Play, Radio, Begin) is below the viewport and cannot be reached.
7. Text is sized in `px` from 8 to 28 px; 8.5 to 11 px text carries names, counts, radio state, the WINNING/LEAD/WON tags and the reason line. Dimmed states fall to 2.4 to 4.0:1 contrast.
8. Burst Transmission works and is server-listed, but the server gives no reason when it is unavailable, and the shared mission objective has no server text or state.
9. Party chrome is absent in play (correct); the host's End sits in the dock beside Play and confirms by tap-again, not Cancel / End Game.
10. Screenshots were captured (87 files, 28 scenes); two are simulated overlays and are named so.

## 2. Five zones as built

Order is fixed by a six-row grid whose only flexible row is the trick (`games/expo/web/expo.css:81`). Above the grid sit the top bar and status strip (`games/expo/web/index.html:31-44`). Shares are of viewport height, measured on a 4-seat table mid-trick (`expo-07-play-trick-in-progress-my-turn-*.png`).

| Zone | DOM | 390x844 | 360x640 | Shows | Hidden, or in a sheet |
|---|---|---|---|---|---|
| (chrome) | `.topbar`, `.status-strip` | 48 px + 30 px (9.3 %) | 48 px (7.5 %); the status line moves inside the top bar, 240 px wide (`expo.css:338`) | menu button, "AVRANA PARTY / EXPO" wordmark, help button; the one live instruction; connection dot and word | wordmark and the word "Connected" are removed at 700 px or less (`expo.css:337`, `:341`) |
| 1. Mission stage | `#mission-stage` (`index.html:69-89`) | 152 px, 18.0 % | 99 px, 15.5 % | "Mission N", trick counter, timer pill, one objective line, conditions chip (Attempt N / Clock running / Distress active / result), radio chip, newest two events as one clipped line; placeholder sky, ridge, haze, glow under a scrim | objective line is one line under 760 px (`expo.css:100`, `:371`); a long status sentence covers the line, chips and news (`expo.css:49-54`); difficulty, attempt detail and the full objective are in the Tasks sheet |
| 2. Crew strip | `#seats` (`index.html:91`) | 53 px, 6.3 % | 53 px, 8.3 % | per seat: turn mark, captain crown, name, Party Host tag, cards and tricks, radio state or the transmitted card | role words removed at 700 px or less (`expo.css:346`); with 4 or 5 seats counts become "7c · 0t" and the tag "H" (`client.js:743-759`); tasks per seat, full radio wording and "away" detail are in the Crew sheet (`client.js:1266-1285`) |
| 3. Shared trick | `#stage` (`index.html:92`) | 201 px, 23.8 % (card 74 x 137) | 144 px, 22.4 % (card 64 x 80) | a slot per seat in play order from the lead: order number, name, card; LEAD, WINNING, WON tags; caption with lead suit and who is awaited. Replaced in place by task selection, predictions, "Ready to move out", distress, a crew decision, or the radio console (`client.js:768-779`) | the previous trick is in the Log sheet (latest trick only, `client.js:1300-1313`); replacement panels scroll inside this zone (`expo.css:171`) |
| 4. Crew objectives | `.ops` > `#objectives`, Log tab (`index.html:94-97`) | 53 px, 6.3 % (two rows) | 46 px, 7.2 % (one row) | up to two rows: owner, task text (one line, ellipsis), state pill; done/total; the whole panel is one button | second row removed at 700 px or less (`expo.css:351`); all other tasks, difficulty and predictions are in the Tasks sheet (`client.js:1287-1298`) |
| 5. Hand and controls | `#hand-panel`, `#dock` (`index.html:99-108`) | 165 px + 78 px, 28.8 % (10 cards, 58 x 60) | 137 px + 78 px, 33.6 % (58 x 46) | hand title or Yours/Tonoja switch, reason line, cards in one row (up to 7) or two; dock left: table control (Party Host or crew); dock right: Radio and Play, or Agree/Decline | suit word on cards removed at 700 px or less (`expo.css:347`); cards 44 px high at 610 px or less (`expo.css:354`) |

At 375x667: stage 103 px (15.5 %), crew 53, trick 166 (24.9 %), objectives 46, hand 137, dock 78. Gaps and padding take the remaining 13 to 17 %. At 844x390 see EX-17.

Sheets (`#sheet`, `index.html:111-117`, max 82 % height, `expo.css:271`): Crew, Mission tasks, Log, Table (menu), help. The result is a full-screen `alertdialog` (`index.html:119`).

## 3. Authoritative vs presentation-only

"Public" is `Engine.view()` (`games/expo/engine.py:1325-1384`) plus the adapter's additions (`games/expo/game.py:373-392`), the same for every viewer. "Private" is `view.me`, sent only to that seat. "Envelope" is `GameSession.state_for` (`core/session.py:469-491`, `games/expo/game.py:394-400`).

### 3.1 Current trick winner

There is a visual location and it is authoritative. The server sends `trick_leading` in every view:

```python
# games/expo/engine.py:664-675
def trick_leading(self):
    s = self.s
    if not s['trick'] or s['result'] or s['resolving'] or s['phase'] != 'in_trick':
        return None
    return winner(s['trick'])
```

`winner()` is the one function that resolves a completed trick (`games/expo/rules.py:22-27`). The client compares seats with the field and reads no card: `seat === g.trick_leading` puts the word WINNING and an outline on that slot (`games/expo/web/client.js:842`, `:817`; `expo.css:162-165`), and the live region appends "`name` is winning the trick." (`client.js:600`). It is `None` before the first card, during the resolving hold, on a result and in setup (`engine.py:1191`). Screenshots: `expo-07-…`, `expo-10-…`, `expo-11-…`.

### 3.2 Table

| Shown | Where | Source | Flag |
|---|---|---|---|
| Mission number, difficulty, "fixed tasks" | stage title, Tasks sheet | public `mission.id`, `mission.target`, `mission.fixed` | the count "4 fixed tasks" is a client literal (`client.js:1289`) |
| Trick n / total | stage pill | public `trick_number`, `planned_tricks` | |
| Timer | stage pill | public `expiry` minus the synced clock (`client.js:1376-1382`) | client-derived countdown; "clock at zero" is claimed client-side, the outcome is not (`client.js:535`) |
| Objective line (task missions) | stage | client sentence from `tasks.length` and count of `tasks[].state == COMPLETED` (`client.js:660-662`) | |
| Objective line and state (shared-objective missions 8, 21, 23, 27) | stage, objectives, Tasks sheet, result | key from public `mission.objective`; **text from the client's `OBJECTIVES` table** (`client.js:27-32`); **state inferred by the client** from `result.status` and `cause.kind` (`client.js:683`) | **rule text and state are client-owned (EX-31)** |
| Conditions chip | stage | client mapping of public `result`, `expiry`, `distress`, `attempts` (`client.js:640-645`) | |
| Radio chip and rule sentence | stage, radio console, Crew sheet | public `communication`, `shared_sonar`; **rule sentences are the client's `RADIO` table** (`client.js:47-52`) | rule wording client-owned |
| Latest news line | stage, live region | public `events[]` worded by `sayEvent` (`client.js:610-635`) | wording client-side, facts server-side |
| Seat order, names | crew strip, trick | public `seats`; envelope `players[].name` | |
| Captain | crown, dock label | public `captain` | |
| Party Host tag | crew strip, Crew sheet | Party's `hostName()` **matched to a seat by display name** (`client.js:204-208`) | **identity by name (EX-35)** |
| Whose turn | status line, crew tile, trick slot, caption | public `turn`, `trick`, `stage` | "your turn for Tonoja" uses `captain == me.seat` (`client.js:548`, `:511`), a client copy of `Engine.controller` (EX-33) |
| Cards and tricks per seat | crew strip, Crew sheet | public `hand_counts`, `trick_counts` | |
| Radio state per seat; transmitted card | crew strip, hand marker, Crew sheet | public `sonar_spent`, `shared_sonar`, `exposures[]` (`assertion` omitted for other seats in `currents`, `engine.py:1330-1333`) | |
| Away / reconnecting | crew strip, status | public `away` | |
| Cards on the table, play order | trick slots | public `trick[]`, `leader`, `seats` (rotation in `client.js:828`) | order is `seats` rotated to `leader`: presentation |
| **Seat winning the unfinished trick** | WINNING tag, live region | **public `trick_leading`** | authoritative (3.1) |
| Resolved trick and its winner | trick zone, Log sheet, result | public `last_trick{index,leader,winner,plays}`, `resolving{trick,until}` | |
| Lead suit named in the caption | trick caption | suit of `trick[0].card` read from the card id (`client.js:821`, `:843`) | reading a card's own suit, no rule |
| Tasks: text, owner, difficulty, state, prediction | objectives, Tasks sheet, selection | public `tasks[]{id,text,difficulty,owner,status,state,eligible_owners,prediction_required,prediction_committed,prediction?}`; `state` from `Engine.objective_state` (`engine.py:1309-1323`) | sort order and "n/m done" are client (`client.js:678`, `:703`); a task has no order or sequence field |
| Task selection controls and why not | trick zone | public `selector`, `controller`, `mission.allocation`; private `me.task_reasons`, `me.pass_task_reason`, `me.volunteer_reasons`, `me.offer_reason`, `me.offer_owner_reasons`, `me.predict_reasons` | |
| Hand | hand panel | private `me.hand`; public `tonoja` (face-up tops, `null` for a gap) | |
| Legal / illegal card | hand | private `me.card_reasons[card]`, `me.play_reason` (`client.js:1004`); `me.legal_cards` is also sent | authoritative |
| Reason line by the hand | `#hand-reason` | server sentence when every showing card shares one; otherwise **client hint "Follow `suit` if you can" / "Lead any card"** from `trick[0]` (`client.js:1046-1053`) | **client-worded rule hint (EX-34)** |
| What may be transmitted, and as what | radio console, lit cards | private `me.communication_options{card:[assertion]}` (`engine.py:677-688`) | authoritative |
| Why nothing can be transmitted | radio console | **client sentence** (`client.js:869-872`) | **no server reason (EX-30)** |
| Distress buttons offered | "Ready to move out" | **client condition: no Tonoja in `seats`** (`client.js:977`), mirroring `len(humans) > 2` (`engine.py:696`) | **client-encoded rule (EX-32)** |
| Crew decision: question, votes, who is asked | trick zone, dock, status | public `proposal{payload,votes,recipient}`; question text and "who still must answer" are client (`client.js:515-531`) | voters re-derived client-side (EX-33) |
| Begin / Retry / Next availability and reason | dock, result | public `lifecycle`, `lifecycle_reasons{begin,retry,next}`, `begin_at`, `lifecycle_transitional` | authoritative; who is drawn the control uses Party `isHost()` (display only, `client.js:183-189`) |
| Setup: offered mission, clock, Tonoja seat, why not | setup screen | public `setup{mission,timed,tonoja,tonoja_seat,waiting,seat_waiting,seat_proposal,missions[{id,enabled,reason}]}` (`engine.py:1177-1203`) | `missions[].reason` is internal text (EX-38) |
| Result: success / failure | result title, mark, status | public `result.status`; title words client (`client.js:1193`) | |
| Result: reason | result | public `result.reason` | authoritative |
| Result: what failed, deciding play, whose | result facts | public `cause{kind,objective,failure,state,affected_seat,trigger_seat,trigger_controller,trigger_card,cards,trick}` (`engine.py:149-179`); labels and the `FAILURE` sentences are client (`client.js:1150-1175`) | facts server, wording client |
| Result: line of fiction | result | client `FICTION` keyed by `cause.failure` (`client.js:1158-1161`) | presentation only, placeholder |
| Logbook | Log sheet | public `log[]{mission,attempts,distress}` | |
| Status sentence | `#status` | **client-composed** from the fields above (`client.js:540-564`) | no rule decided; see EX-33 |
| Connection | dot, word, banner | socket state (`client.js:1383-1391`, `web/hubnet.js:532-551`) | |

Not used by the client though sent: `me.legal_cards`, `me.may_pass_task`, `me.may_decline_volunteer`, `players[].color`, `cause.action`, `cause.mission`.

## 4. Findings

### 4.1 Inherited from LAN Games vs made for EXPO

| Inherited (file) | What reaches the EXPO screen |
|---|---|
| `web/shared.css:4-15`, `:32-33` | both typefaces: Sora (UI) and JetBrains Mono (card ranks, tags, counts, timer) |
| `web/shared.css:17-37` | `--text` #e8edf9 (all primary text), `--raised` #161e33 (every secondary button), `--grad`, `--cyan`, `--danger`; `expo.css:12-13` redefines only `--bg`, `--muted`, `--surface`, `--line` and adds its own |
| `web/shared.css:74-102` | `.btn`, `.btn-primary` (cyan to violet gradient with a violet glow: Play, Transmit, Begin, Deal, Next, Agree), `.btn-go` (pulsing green "Begin expedition" in the lobby); `expo.css:63-68` changes size and adds `.quiet`, `.armed`, `.on` only |
| `web/shared.css:82` | the focus ring on every `.btn`: 2 px cyan #22d3ee. It outranks EXPO's 3 px `--sea` ring (`expo.css:59`), which applies to cards, seats and icon buttons only |
| `web/shared.css:121-136`, `web/hubnet.js:330-360` | avatar grid and photo button (standalone lobby) |
| `web/shared.css:162-176`, `web/hubnet.js:406-418` | toast: navy pill, 13 px, one line, 3.2 s; used for every refused action (`client.js:65-68`) |
| `web/shared.css:178-185`, `web/hubnet.js:532-551`, `:596` | "RECONNECTING…" banner: pink, mono, blinking, fixed 14 px from the bottom |
| `web/shared.css:187-197`, `index.html:121` | 3-2-1 countdown overlay: 120 px gradient digits on a blurred navy veil |
| `web/hubnet.js:77-135` | per-browser sound, haptics, motion and contrast flags; haptic call |
| `web/hubnet.js:43-52` | injects `gameart.css` and `brand.js` into the page (no visible effect in EXPO) |
| `web/brag.js`, `client.js:1247` | "BRAG ABOUT IT" share-card button on a success, card branded "LAN Games" (`web/brag.js:15`) |
| `web/hubnet.js:685-712`, `web/avrana-integration.css:52-61` | "Round over" panel after the Party ends the round (Avrana system colours) |
| `index.html:122` | `canvas#confetti` is in the page; EXPO never calls it |

Made for EXPO: the warm palette and slot variables (`expo.css:12-22`), the five-zone grid, mission stage art placeholders (`index.html:14-24`, `expo.css:84-116`), crew tiles, trick slots and tags, the objectives button, the card face, the radio console, the dock, sheets, the result takeover, short-screen rules (`expo.css:334-380`), the director and slots.

What the AVR-267 layer does today: a gradient sky, an SVG ridge polygon, two haze bands and a glow that changes tint with `data-env` (calm, storm, distress, lost, clear; `expo.css:92-95`), all under a scrim of 44 to 82 % black (`expo.css:91`); a faint ground gradient behind the board (`expo.css:19`, `:35`); two line icons (radio, hazard); fiction names for the radio states; a five-line text briefing at the high tier. Every slot is declared a placeholder (`games/expo/web/slots.js:17-29`). Against the brief's "rugged field equipment, clean enough that the cards stay primary": no equipment framing, material, instrument typography or texture exists in any zone; the art is confined to one box; the controls are the donor's; and the cards are the smallest, dimmest elements on the board (EX-3).

### 4.2 Findings table

| ID | Observation and evidence | Cat | Sev |
|---|---|---|---|
| EX-1 | Primary and secondary controls are LAN Games primitives on a warm board: cyan-to-violet gradient Play/Transmit/Begin/Deal/Next, navy #161e33 End/Radio/Take/Distress, cool-white text. `web/shared.css:74-102`; `expo-05-…`, `expo-07-…`, `expo-23-…` | A | High |
| EX-2 | The wasteland layer is placeholder art in the mission stage only and is darkened by a scrim; the rest of the board is flat panels with 1 px #4a4030 edges. `expo.css:84-95`, `slots.js:17-29`; `expo-07-…-390x844.png` | A | Med |
| EX-3 | The hand is the least prominent zone content. Cards are 58 x 60 (390x844), 58 x 46 (360x640, 375x667), 44 high at 610 px or less; rank 20 to 23 px, symbol 13 px. Every card is `disabled` at `opacity:.5` whenever the server gives a reason, which is whenever it is not this player's turn and all through task selection, predictions and "Ready to move out", when players read their hand to choose. `expo.css:231-246`, `:335`, `:354`; `client.js:1004`; `expo-04-…`, `expo-16-…` | A | High |
| EX-4 | In the trick the frame grows but the face does not: a 74 x 137 card carries the same 23 px rank and 13 px symbol. LEAD and WINNING tags (8.5 px) sit on the card's lower face; they cover the suit word, and on short screens the suit symbol (Ava's 9 in `expo-10-play-five-seats-360x640.png` shows no symbol). `expo.css:153`, `:160-164`, `:239-241` | A | Med |
| EX-5 | Two focus rings: cyan 2 px on buttons, `--sea` 3 px elsewhere (4.1). `expo-22-…` vs `expo-17-…` | A | Low |
| EX-6 | Entering a Party round shows the donor's countdown overlay and the lobby panel ("The crew is boarding…"); the setup that follows is the same lobby panel. `index.html:46-64`, `:121`; `client.js:365-384` | A | Med |
| EX-7 | Zone 4 shows at most two tasks, one at 700 px or less, each on one line with an ellipsis ("Priya · Capture no color …" at 360 px). With three or more tasks the rest are reachable only through the sheet. `expo.css:212-214`, `:351`; `client.js:693`; `expo-07-…-360x640.png` | B | High |
| EX-8 | A crew tile holds five facts at 10 to 13 px. With four or five seats it becomes codes ("7c · 0t", "H", "ready"); a transmitted card is the code "9○●" (rank, suit symbol, meaning glyph) in 10.5 px mono. No avatar is drawn on the board. `client.js:710-713`, `:743-759`; `expo-10-…`, `expo-16-…` | B | Med |
| EX-9 | The one instruction changes place with screen height: its own strip above 700 px, inside the top bar between two buttons at 700 px or less (12 px, three-line clamp), and over the mission stage when long, hiding the objective line, chips and news. `expo.css:44-54`, `:338-340`; `client.js:582-593` | B | Med |
| EX-10 | Result order is mark, title, a line of placeholder fiction, the server's reason, then the cause. "What failed" repeats the reason word for word when the reason is the task's text. A success shows no task recap, attempts or distress although `log` and the `MISSION_SUCCESS` event carry them. `client.js:1193-1203`, `:1168`; `engine.py:524-531`; `expo-22-…`, `expo-24-…` | B | Med |
| EX-11 | Task selection, predictions and "Ready to move out" are scroll boxes inside the trick zone with no scroll cue: at 360x640 the box is 142 px with 122 to 126 px hidden for a two-task mission (164 px with 100 to 104 hidden at 375x667, 199 px with 65 to 69 hidden at 390x844); the Distress buttons are cut and their explanation is below the fold. `expo.css:171`; `expo-04-…-360x640.png`, `expo-05-…-360x640.png` | B | Med |
| EX-12 | The menu button draws a house, is labelled "Table menu" and opens roles, End and Effects. Help is seven unstructured paragraphs, one of them about source-rule conflicts. `index.html:32-36`; `client.js:33-41`, `:1315-1354`; `expo-20-…`, `expo-21-…` | B | Low |
| EX-13 | In-EXPO setup is a native select of 50 entries ("Mission N", "Deep dive N") with no name, difficulty or description; the clock checkbox is shown for every mission and applies to mission 16 only. `client.js:425-449`; `expo-02-…` | B | Med |
| EX-14 | The mission stage names the mission by number only; "Attempt 1" wears the hazard icon; the news line is one clipped 11.5 px line. `client.js:657-665`; `expo.css:107` | B | Low |
| EX-15 | Landscape 844x390: the board keeps a 560 px portrait column, the trick zone is 0 px high, trick slots draw over the crew strip and objectives, and the dock starts at y = 388 with 70 px clipped: Play, Radio, Begin and End cannot be reached and nothing scrolls. `expo.css:34`, `:81`; `expo-07-…-844x390.png`, `expo-14-…-844x390.png` | C | High |
| EX-16 | The Party Host's End EXPO is a full-size button in the dock beside Radio and Play (and beside Deal in setup). It confirms by a second tap within 4 s with no Cancel; the decided form is Cancel / End Game (GAME-UX-CONTRACT §8, P-8). `client.js:218-232`, `:1076`, `:499`; `expo-07-…`, `expo-02-…` | C | Med |
| EX-17 | On a failed result the non-primary "Retry same tasks" comes first and takes initial focus; the primary "Retry new tasks" is second. At 360x640 the host's result card scrolls and "Look at the table" is cut. `client.js:1229`, `:1177-1180`; `expo-23-…-360x640.png` | C | Low |
| EX-18 | Burst Transmission (as operated): Radio in the dock, always enabled; the console replaces the trick; the board dims to 50 % but stays tappable; lit cards get a 1 px ring and a 3 px lift, the rest drop to 40 %; choosing a card lists its meanings (a single meaning is preselected); Transmit names card and meaning and is irreversible, with no undo and no confirmation beyond that label. `client.js:852-885`, `:1104-1119`; `expo.css:193-203`; `expo-13-…`, `expo-14-…`, `expo-15-…`, `expo-16-…` | C | Med |
| EX-19 | After a send, input is locked for up to 4 s by a `pending` flag with no visible busy state; further taps are dropped silently. `client.js:123-133` | C | Low |
| EX-20 | Hand cards are narrower than 44 px with 13 or 14 cards: 41.7 px at 360 wide, 43.8 px at 375 (the playtest floor is 40 px, `tests/_expo_phone.mjs`). All other controls measured 44 px or more. `expo.css:231`; `client.js:1025`; `expo-11-…-360x640.png`, `expo-26-…-360x640.png` | C | Med |
| EX-21 | A refused action is the donor toast: fixed 64 px from the top, over the mission title and trick counter, one line with an ellipsis at 92 vw (a long server sentence is cut), gone in 3.2 s. A lost connection is said twice: in the status line and by the donor's blinking banner, which covers the dock. `web/shared.css:162-185`; `expo-27-refusal-toast-SIMULATED-…`, `expo-28-reconnecting-SIMULATED-…` | C | Med |
| EX-22 | All text is `px` (no `rem`), and the page is `position:fixed; overflow:hidden`, so enlarged text clips. Sizes declared in `expo.css`: 8, 8.5, 9, 9.5, 10, 10.5, 11, 11.5, 12, 12.5, 13, 14, 15, 16, 17, 18, 19, 20, 21, 23, 27, 28. On the play screen 8.5 px: host tag, LEAD/WON/WINNING; 9 px: order number, turn mark, suit word, wordmark; 10 to 10.5 px: seat counts, radio state, pills, empty slot; 11 px: slot names, reason line, dock labels, chips. The Game Contract declares `text_scalable: true` (`contracts/games/expo.json:37`, this repo). `expo.css:28` | D | High |
| EX-23 | Colour-only or near colour-only state: "this is me" is the name's colour (`expo.css:122`, `:152`); a suit is colour plus a 13 px symbol, and the word is removed at 700 px or less and on a transmitted card (`expo.css:347`, `:250`); cards the cause names on the result are a gold glow (`expo.css:307`); cannot-play is opacity alone on the card, with the sentence beside the hand. Turn, winner, lead, away and task state all carry a word | D | Med |
| EX-24 | Contrast computed from the CSS: normal text 8 to 15:1. Disabled cards 3.1 to 4.0:1; unlit cards in radio mode 2.4:1; disabled primary label 2.4 to 3.2:1; `--muted` text in the dimmed radio-mode board 2.9:1; panel and control edges (#4a4030 on #1d1912) 1.7:1 | D | Med |
| EX-25 | One polite `role="status"` region carries the instruction, the news and the leading seat and may be re-read whole on every change; toasts and the reconnect banner are not live regions; no screen reader has been listened to. `index.html:42`; `web/hubnet.js:406-418`; `games/expo/docs/PRESENTATION.md` ("Not built") | D | Med |
| EX-26 | With a mixed hand, each illegal card's own server sentence exists only as a `title`; the visible line is the client hint. `client.js:149`, `:1050-1053` | D | Low |
| EX-27 | The server sentence under the hand outside play is "This is not a card-play phase." (system vocabulary). `engine.py:1237`; `expo-04-…` | B | Low |
| EX-28 | Fiction and vocabulary disagree: a wasteland expedition whose trump suit is "submarine" / "sub", missions above 32 are "Deep dive", server sentences say "sonar token", the share card icon is a wave, tokens are `--sea`, `--deep`, `--foam`. `client.js:25-26`, `:35`, `:371`, `:1247`; `engine.py:923-924`; `expo.css:12` | A | Low |
| EX-29 | Cards in the trick, the Log and the result are `div`s carrying an `aria-label` with no role, so the label may not be exposed; labels read suit before rank ("green 8"). `client.js:144-151` | D | Low |
| EX-30 | No reason is sent when nothing can be transmitted: `me.communication_options` is `{}` and the client shows one generic sentence listing every condition. `engine.py:677-688`; `client.js:869-872` | E | Med |
| EX-31 | A shared mission objective has no text and no state in the view; both are client-side (3.2). `client.js:27-32`, `:683` | E | Med |
| EX-32 | Distress availability is decided by a client condition with no field or reason. `client.js:977`; `engine.py:695-697` | E | Low |
| EX-33 | The view does not say who controls the seat on turn or who must still answer a decision; the client re-derives both (captain plays Tonoja; all humans vote, or the one recipient). `client.js:511`, `:524-531`, `:548`; `engine.py:266-267`, `:795-799` | E | Low |
| EX-34 | The "Follow `suit` if you can" hint is client-worded from the lead card. `client.js:1046-1053` | E | Low |
| EX-35 | The Party names its host by display name only; the client matches it to a seat, and two equal names get no tag. `client.js:204-208` | E | Med |
| EX-36 | No semantic event exists for a task being taken or assigned, a crew decision opening or closing, the distress pass exchange, a Tonoja card being uncovered, or a seat going away; presentation can only diff views for these. `engine.py` `_emit` call sites (`:134-141`, `:207`, `:231`, `:257`, `:509-527`, `:563-661`, `:810-819`, `:932`) | E | Low |
| EX-37 | Only the latest resolved trick and its events reach a viewer, also after the result: no recap of an attempt can be drawn. `engine.py:1285-1307` | E | Low |
| EX-38 | Mission content is a number and rule switches (`games/expo/content.py:22-56`): no name or brief. The reason a mission is unavailable is internal text shown to players in setup, for example "C02: supplied mission difficulty conflicts with VTT". `content.py:7-14`; `client.js:434`, `:444` | E | Med |
| EX-39 | On plain HTTP the integration bar ("Back to Party") is not hidden before the Party answers and is hidden in a Party only by an attribute set through the bridge or the secure-only follow module; whether an HTTP (Limited Mode) EXPO round shows it above the board was not run. `web/avrana-integration.js:149`, `:158-160`, `:175-180`; `web/avrana-integration.css:47-49` | E | Low |
| EX-40 | Question: in the wasteland fiction, what are the trump suit, the dummy ("Tonoja"), the missions above 32 and the "sonar" token called? (EX-28) | F | |
| EX-41 | Question: does the Party Host's End belong in the persistent play dock, or only in the table menu and on the result? (EX-16) | F | |
| EX-42 | Question: is the "AVRANA PARTY" wordmark wanted above the game's name during play? (`index.html:35`; GAME-UX-CONTRACT E-6) | F | |
| EX-43 | Question: does the LAN Games "Brag" share card stay on an EXPO success? (4.1) | F | |
| EX-44 | Question: is landscape supported, refused with a notice, or a separate layout? (EX-15) | F | |
| EX-45 | Question: should "cannot act now" look the same as "this card is illegal"? Today both are the one muted state. (EX-3) | F | |
| EX-46 | Question: are Party identity pictures wanted on the board? The slot `crew.portrait` is empty and the setup roster drew the donor's default avatars in this audit's harness (`core/session.py:349-366`); a live Party round was not run. | F | |
| EX-47 | Question: is the standalone lobby (name, avatar grid, photo, Ready/Begin) in scope, given it is a development path? (`index.html:46-64`; GAME-UX-CONTRACT E-8) | F | |
| EX-48 | Question: do missions get names and briefs (content), which the stage, setup and briefing would need? (EX-38) | F | |

## 5. Behaviors to preserve

Authority and legality
- The view is the only source of game meaning; the client sends intents stamped with `attempt`, `revision` and a request id (`client.js:6-7`, `:129-133`; `engine.py:990-1036`).
- Referee, not oracle: every legal card looks the same; there is no style for a risky card (`expo.css:243-247`; `client.js:1032-1033`).
- A control is disabled exactly when the view gives a reason, and the server's sentence is shown as words (`client.js:115-122`; `engine.py:1216-1283`; `game.py:285-299`).
- `trick_leading` and `last_trick.winner` come from the server; the page never reads a card to decide anything (`client.js:806-808`).
- The director is optional, read-only and fenced: a frozen copy of the view, no connection, three throws and it stands down (`client.js:72-102`; `games/expo/web/director.js:1-20`).

Interaction
- Select a card, then Play in the dock; a selection is dropped when the moment changes (`client.js:506-513`, `:1121-1127`).
- A decision's answers replace Radio and Play in the dock; on the result and in setup they stay under the question (`client.js:784-803`, `:1091-1098`).
- One viewport: the page never scrolls; anything that is not this turn opens as a sheet; one modal at a time, background inert, Tab trapped, Escape closes, focus returns to the opener (`expo.css:24-36`; `client.js:268-308`).
- Focus and typed values survive every redraw through `data-key` (`client.js:320-352`).
- The result takes the screen, can be put away with "Look at the table", and holds the dock while away (`client.js:1133-1142`, `:1248`).
- The status sentence is always whole; it names one person and counts the rest (`client.js:140-142`, `:537-593`).
- Every meaning is also words; colour and motion repeat it (`games/expo/docs/PRESENTATION.md`, "Meaning is always words").

Privacy
- A spectator gets the public view and no hand (`game.py:394-397`; `client.js:1041`).
- In `currents` the meaning of a transmission goes to its author only, in the view and in the event (`engine.py:1330-1333`, `:930-935`; `client.js:154-161`).
- A secret prediction is sealed until the result (`engine.py:1344-1346`; `client.js:1294`).
- Only the latest resolved trick may be looked at again (`engine.py:1285-1307`; `client.js:1308`).
- Tonoja's covered cards are never sent; a gap is `null` (`engine.py:1363`; `client.js:1031`). Distress passes stay sealed until all have chosen (`client.js:986-991`).

Lifecycle
- Two authorities: the Party Host begins, retries, moves on and ends, proven by a fresh single-use ticket per action; the captain has only what the rules give (`client.js:14-19`, `:209-216`; `web/hubnet.js:748-754`; `game.py:248-262`, `:301-315`).
- EXPO draws the host's controls itself (`data-avrana-party-shell`, `index.html:30`), so the platform adds no bar and no fallback End (`web/avrana-integration.js:92-106`); there is no link to the old hub (`index.html:25-29`).
- Setup happens inside EXPO before the first deal; Tonoja's seat is the two players' to agree (`client.js:386-502`; `engine.py:1177-1203`).
- The crew's moment to ask for distress: Begin stays closed for 4 s and counts down from `begin_at` (`game.py:33-34`; `client.js:201`, `:1075`).
- A resolved trick is held 0.8 s, stays on the table until the next card, and no seat acts meanwhile (`game.py:44`; `client.js:829-836`).
- A seat that is away pauses the table and is said in words; a reconnect settles to the state without replaying effects (`engine.py:1211`; `client.js:63`, `:541`; `director.js:352`).
- End goes through the Party's own verb; the round's results are held until the host acts (`client.js:218-232`).
- Asset slots are placeholders; final art, audio and haptics are human-made or licensed (`games/expo/web/slots.js:1-12`).

## 6. Motion: today, and what existing events and state support

Today (`games/expo/web/director.js`): Web Animations on `transform` and `opacity` only. Three tiers: high (movement, pulses, ambient haze and glow, cinematic beats), medium (opacity pulses), low (nothing). Reduced motion, from the system or the per-browser flag, forces low (`director.js:49-55`); `expo.css:381` also removes all CSS animation and the selected-card lift. Nothing disables, covers or delays a control; a tap or key ends a cinematic beat (`director.js:275-278`, `:354`). Events are consumed once by `seq`; a first view, a gap, a hidden tab, a backlog or a new attempt settle with no replay (`director.js:65-83`). Sound slots are all empty; haptic slots hold short patterns (`slots.js:30-42`). Sheets, the radio console, the hand switch, the result's put-away and stage changes are instant.

| Event or state (fields) | Animated today | Also available in the same data |
|---|---|---|
| `CARD_PLAYED` (`seat`, `controller`, `card`, `position`, `lead_suit`) | card travels from its hand place or the player's tile to its slot, 300 ms; hand closes the gap; tile pulse | origin and destination rects for every seat; `position` in the trick |
| `TRICK_RESOLVED` (`winner`, `leader`, `winning_card`, `plays`, `lead_suit`) with `resolving.until` (0.8 s hold) | lead-suit slots pulse, winner scales forward, others tuck, ring on the winner; at most 700 ms inside the hold | winner's crew tile and `trick_counts` (no collection toward the winner is drawn); `last_trick` stays for a hand-off to the next lead |
| `trick_leading` (view field, no event) | none; the tag appears | the change of leading seat between two views |
| `TURN_STARTED` (`seat`, `controller`, `lead`) | tile pulse; hand panel pulse and haptic when mine | `me.card_reasons` clearing at the same moment (hand becomes playable) |
| `COMMUNICATION_SENT` (`seat`, `card`, `assertion` or hidden, `mode`, `token`) | two rings on the sender's tile, radio chip pulse, marker pops on the author's card, stage pulse for others | the card itself and its meaning are public; token spent (`sonar_spent`, `shared_sonar`) |
| `OBJECTIVE_PROGRESS` / `COMPLETED` / `FAILED` (`objective`, `scope`, `owner`, `failure`, `state`, `trigger_seat`, `affected_seat`, `cards`) | objectives zone pulse, the row blinks | the deciding cards in the trick (`cards`), the owner's tile, the state change Standby to Active to Done or Failed |
| `MISSION_MODIFIER_ACTIVATED` (`modifier`: communication, allocation, objective, distress, timer, sonar; `value`; `drawn`) | mission stage pulse; `data-env` and `data-radio` switch the glow tint | which condition changed and to what; pass direction for distress; timer length |
| `MISSION_SUCCESS` / `MISSION_FAILURE` (`reason`, `cause`, `attempts`, `distress`) | result overlay flicker or glow, card rises, mark pops, facts stagger (2.6 s, non-blocking) | `cause.kind`, `cause.failure`, `trigger_card` in `last_trick`, `affected_seat` |
| Mission start (synthetic, from the view: mission, captain, conditions, task count) | 5.6 s text briefing in the stage (2.2 s on a retry), crew tiles and hand cards fade in, ring on the captain | `tasks[]`, `mission.target`, `communication` |
| `PLAYER_RECONNECTED` (`seat`); `away` (view) | tile pulse | going away has no event (EX-36) |
| View changes with no event | none | `stage` transitions, `proposal` opening and closing, `tasks[].owner` being set, `me.pass_locked`, the distress exchange changing `me.hand`, a `tonoja` gap filling, `begin_at` and `expiry` countdowns |

## 7. Screenshot index

Method: `current/expo-*.png` (outside Git), device scale factor 2, at 390x844, 360x640 and 375x667 (scenes 07, 14 and 22 also at 844x390). No game server was run (the machine's Python has no FastAPI). The real `ExpoSession` and engine from the export were driven in-process to produce per-viewer states; the unmodified client files were served by request interception in one headless Chromium, with a stub socket and, for Party rounds, a stub `window.AvranaParty` (host "Ava"). Effects were set to the still tier (`expo-fx=low`), so no animation is captured. Not a live Party session: the Party bridge, tickets and real reconnects were not exercised. Scenes 27 and 28 are simulated overlays (the real toast and banner code, triggered by hand).

| File prefix | Scene |
|---|---|
| `expo-01-lobby-standalone` | standalone lobby (development path) |
| `expo-02-setup-party-host`, `expo-03-setup-party-guest` | in-EXPO setup before the first deal |
| `expo-04-task-selection-my-pick` | task selection in the trick's place |
| `expo-05-before-first-trick-host`, `expo-06-before-first-trick-guest` | "Ready to move out", distress, Begin |
| `expo-07-play-trick-in-progress-my-turn` | trick in progress, WINNING and LEAD tags, must follow (also landscape) |
| `expo-08-play-must-follow-card-selected` | selected card and "Play …" in the dock |
| `expo-09-play-waiting-not-my-turn` | hand dimmed, another seat's turn |
| `expo-10-play-five-seats` | five seats, degraded radio |
| `expo-11-play-two-players-tonoja` | two players with Tonoja, hand switch |
| `expo-12-trick-resolved` | resolved trick resting, WON |
| `expo-13-radio-open`, `expo-14-radio-card-chosen` | Burst Transmission console (14 also landscape) |
| `expo-15-radio-sent-author`, `expo-16-radio-sent-other-phone` | transmitted card marker; tile code |
| `expo-17-sheet-tasks`, `expo-18-sheet-crew`, `expo-19-sheet-log`, `expo-20-sheet-table-menu-host`, `expo-21-sheet-help` | the five sheets |
| `expo-22-result-failed-guest`, `expo-23-result-failed-host`, `expo-24-result-success-host` | results (22 also landscape) |
| `expo-25-result-put-away` | result put away, dock button to return |
| `expo-26-crew-decision-answer-in-dock` | crew decision, answers in the dock (standalone) |
| `expo-27-refusal-toast-SIMULATED`, `expo-28-reconnecting-SIMULATED` | donor toast and reconnect banner over the board |
