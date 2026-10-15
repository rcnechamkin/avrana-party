# Physical check: an abandoned table (AVR-475) and the Host's way out (AVR-476)

Status: **PROPOSED owner-run procedure, NOT RUN on the appliance or on a phone** (2026-10-15). Both
changes pass Tier 2 tests in source. Neither is deployed. Run this after an approved deploy of a
Party build containing PR #149 (AVR-475) and the AVR-476 change, by the deployment runbook
([deploy.md](deploy.md)). Nothing here changes the Pi.

## Before you start

- Record the Party commit the appliance runs (`/party/version.json`) and the date.
- Phones:
  - **A**: the Host; an iPhone with Safari if one is available.
  - **B**: an Android phone with Chrome.
  - **C**: any third phone, to watch.
  - All on the Party Wi-Fi, each with a saved profile.
- A laptop on the management network for `/party/api/state` (read only).
- Keep the time of each step. Write PASS / FAIL / NOT RUN for each line, with a note.

## Part 1: AVR-475, every player leaves mid-round

| # | Step | Expected |
|---|---|---|
| 1.1 | A starts a game that keeps running while nobody plays (OpenCE if installed, else BLUFF or EXPO). B plays, C watches | everyone is on the game |
| 1.2 | Close the game tab on A and on B (or lock both phones, or put them in flight mode). C closes too | — |
| 1.3 | At **+2 min**, read `/party/api/state` | still `active`, members `playing`: too early |
| 1.4 | At **+6 min 15 s** (45 s + 5 min + slack), read it again | session `ended`, outcome `abandoned`, detail "Everyone left the game.", location `home` |
| 1.5 | Check that the game stopped: the OpenCE or arcade runtime is idle, or BLUFF shows no running table | the game was told `end` |
| 1.6 | A fourth phone D (or C reopening Party Home) arrives | D (or the first member here) becomes Host and can start a new round |
| 1.7 | Control: start a round, keep **one** player's game page open and in front for 15 min | the round is never abandoned |
| 1.8 | Control: one phone loads the game page while Party Wi-Fi drops for about 20 s | it still follows: its member shows `playing`, and the round is not abandoned 6 min later |

AVR-475 can close when 1.4 to 1.7 pass. File a bug for any failure.

## Part 2: AVR-476, the Host's way out during a full-screen game

| # | Step | Expected |
|---|---|---|
| 2.1 | On A, open Party Home **in a new tab** and start a game from Home straight away (no Library pages). Make the game fill the screen (OpenCE; or a game with a full-screen button) | — |
| 2.2 | A: browser Back (iPhone: swipe from the left edge; Android: the back gesture; desktop: Alt+Left) | A leaves the game for Party Home and sees "<game> is on." with **Return to <game>** and **Bring everyone back to the Party**. If the game was in browser full screen, the first gesture may only leave full screen: note it |
| 2.3 | A: Return to <game> | back in the game; B and C saw nothing happen |
| 2.4 | A: Back again, then Bring everyone back, then **Keep playing** | the round continues |
| 2.5 | A: Back, Bring everyone back, **End the round** | every phone goes to Party Home |
| 2.6 | B (not Host) during a round: Back | B is **not** shown Return or Bring everyone back; B leaves the Party or returns to the game, never sees an End |
| 2.7 | B opens Party Home by hand during a round | B is taken back to the game |
| 2.8 | A with VoiceOver or TalkBack on: steps 2.2 and 2.5 | the way out is announced; every button is reachable and labelled |
| 2.9 | A with the largest text size: step 2.2 | buttons fit, nothing sideways, the notch does not cover them |
| 2.10 | A: at step 2.5, turn on flight mode before End the round | an error is shown and nothing ends; turn flight mode off, then End the round works |
| 2.11 | Host succession: A leaves; B becomes Host mid-round; B tries Back | known limit: B may have no Party page behind the game. B can still open Party Home by hand and gets the way out. Record what happens |

AVR-476 Part 1 is accepted when 2.2 to 2.7 and 2.10 pass on the iPhone and on Android. Part 2 (a
visible Party control) waits for the owner decisions in
[the proposal](../design/proposals/2026-10-15-host-escape.md).

## After

Paste the results into AVR-475 and AVR-476, with the Party commit, the phones, their OS and browser
versions, and the times.
