# Guests browse during setup: the host's spotlight, then a pinned selection (AVR-702)

- **Status:** proposal, 2026-10-26. Nothing is implemented. ADR 0011 is unchanged until the owner amends it. **Owner decisions required** (section 7).
- **Reads with:**
  - [ADR 0011](../../adr/0011-party-console-model.md), decisions 3–4 and the 2026-10-05 amendment, which keeps the Library, the bar and "This phone" off the briefing;
  - `web/party/app.js` `show()` ("Where the Party is decides, never the address");
  - `web/party/lib/party-mode.js` `destination()`;
  - `web/party/lib/frame.js` (`pageOf`: Home, Library, Party and Me are views of one document);
  - the Concept K Figma, frame 112:380 (spotlight) and the Selected Game Indicator;
  - select-then-launch (AVR-701, draft #247), which gives every game a setup, so this matters for every game.

## 1. What is true today

- During `setup`, every member page is sent to Party Home (`destination()`), and Party Home shows the briefing scene (`show('scene')`).
- The bar is hidden (`$('nav').hidden = which !== 'main'`), and the Library, Party and Me cannot be opened.
- The address cannot change this: the screen follows where the Party is.
- The briefing keeps only the top bar (who is here, the Limited mark), plus the Party drawer and the Limited explanation over it (the 2026-10-05 amendment).

That is decision 4's "full-screen scene". Concept K wants the scene to be the **default** during setup, not a cage.

## 2. Proposal: a client-only change

**No Party Core change.** Library, Party and Me are views of the same `/party/` document. `destination()` already returns `null` for Party Home during setup, whatever the fragment. So the whole change is in `app.js`: which screen is shown during setup.

1. **The spotlight.** When the location *becomes* `setup` for a new session, every phone shows the briefing, as today, with the Concept K spotlight entrance (tier-3 motion; reduced motion: a plain fade). This happens once per selection.
2. **Then the phone is free.** During setup, the bar stays visible on the briefing, as Concept K's single four-tab bar. A member may go to Home, Library, Party or Me.
3. **The pinned selection.** On every other view, a pinned **Party selection** row sits above the bar. It shows the game's art and name, "Selected by <host>", and this member's state, and it returns to the briefing:
   - for pregame games: "Choose Play or Watch" until they choose; then "Playing" or "Watching";
   - for select setups (AVR-701): "Waiting for <host>";
   - if voluntary Ready is adopted (AVR-700): a Ready count.
4. **Nothing can strand a choice.** A member who has not chosen still blocks the host's Start, exactly as today, and the host's blocker still names them ("Waiting for Ada to choose Play or Watch"). Their pinned row says so, and is the only highlighted thing on their screen.
5. **The host stays on the briefing by default.** The host may browse too. While the host is away, their pinned row carries **Start** (disabled with the same reason as on the briefing) and **Choose another game**. The host never loses the Start control.
6. **Start moves everyone, from wherever they are.** When the round starts, `destination()` sends every member page to the game, as today, with `location.replace`, from the Library or Me as well as from the briefing. Decision 5 (the game owns the viewport during a round) is unchanged.
7. **"Can't reach the Party" (F10).** The escalation already exists: after `LOST_AFTER_MS` (10 s, `lib/states.js`) of failed tries, the phone says it lost the box, and the briefing shows "Reconnecting" in `#scene-net`. The change is only that the pinned row shows the same state on the other views. This is client-side only.

**What stays off:**
- browsing never starts a game: `tileMode` already returns `starting` (no Start) while a session is live, and a setup is a live session; only its words change, to "The Party is choosing <game>";
- a guest's browsing changes no Party state;
- Party chat stays in the drawer, never on the briefing (the 2026-10-05 amendment).

## 3. What changes, by file (not done here)

| Where | Change |
|---|---|
| `app.js` `show()` and the location handler | in `setup`: show the scene on entry (a new session id), then honour the fragment; the bar shown on the scene |
| new pinned-row component | art, name, this member's state, the host's Start and Choose another game; one source of truth with the briefing's blocker |
| Library tile words | "The Party is choosing <game>" while `tileMode` is `starting` during a setup |
| reconnect | the existing `LOST_AFTER_MS` state, shown in the pinned row too |
| tests | the guest-journey and multi-client setup steps, which assume the scene is the only screen; new: browse during setup, pinned row returns, Start moves a browsing phone to the game, a browsing chooser still blocks Start |
| GAME-UX-CONTRACT Rule 3.2 and UI-DESIGN-SYSTEM | the "Actual vs Proposal" row for AVR-702 |

## 4. Risks

- **A guest wanders off and forgets to choose.** The blocker already names them. The pinned row and the host's "Waiting for Ada" make it visible, and nothing new can stall the Party beyond what an inattentive guest already can.
- **More on screen during setup.** Concept K accepts this. The spotlight keeps the moment.
- **Tests and the Figma file disagree with ADR 0011 until it is amended.** The amendment text below fixes the record.

## 5. The ADR text, if accepted (ready to paste into ADR 0011)

> **Amendment (2026-10-xx, AVR-702): browsing during setup.** Decisions 3 and 4 are amended for `setup` only: the briefing is shown to every member when a selection begins (the spotlight). After that, a member may open Home, the Library, the Party page or Me, with the bar visible on the briefing and a pinned Party selection row on every other view that returns to it and carries this member's choice, or, for the Host, Start and Choose another game. Browsing never moves the Party or starts a game. The host's Start moves every member page to the game wherever it is. Decisions 1, 2 and 5 to 7 are unchanged, and the 2026-10-05 amendment's chat rule stands.

## 6. Exit criteria (AVR-702)

| Criterion | Section |
|---|---|
| The owner accepts or rejects the amendment | 5, 7 |
| If accepted: the spotlight, browsing, and the indicator | 2 (1–3), 3 |
| Host authority, the Start gate, the game owning the viewport | 2 (4–6) |
| The "Can't reach the Party" escalation (F10) | 2 (7) |

## 7. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | May the host browse too? | yes, with Start in the pinned row; no | **yes**, with Start and Choose another game in the row |
| D2 | Spotlight on every selection, or the first of the night? | every selection; first only | **every selection**, short (under 1 s), with a plain fade under reduced motion |
| D3 | F10 escalation after | the existing 10 s; longer | **the existing 10 s** (`LOST_AFTER_MS`), unchanged |
| D4 | Ship with select-then-launch (AVR-701) or alone? | together; alone | **alone is possible** (no Core change), but **together** reads best, since every game then has a setup |
