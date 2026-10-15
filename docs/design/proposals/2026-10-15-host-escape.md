# The Host's way out of a full-screen game

- **Status:** **PARTLY BUILT (2026-10-15, AVR-476).** Part 1 (the browser's Back reaches the Party's
  way out) is in source with Tier 2 tests; not deployed, not tried on a phone. Part 2 (a visible
  Party-owned control over game content) is **PROPOSED**: it amends ADR 0011 decision 5 and needs the
  AVR-83 geometry, so nothing of it is built.
- **Reads with:** [ADR 0011](../../adr/0011-party-console-model.md) (decision 5 and the 2026-10-02
  amendment: the Host's way out), [ADR 0013](../../adr/0013-party-and-game-browser-origins.md)
  (origins, the bridge), [GAME-UX-CONTRACT](../GAME-UX-CONTRACT.md), AVR-83 (system layer, geometry),
  AVR-292 (Slice 5, the in-game Party layer), AVR-132 (Quit & Spectate, done).

## 1. The problem

On the appliance (AVR-467, 2026-10-14) OpenCE's canvas filled the page and covered the Host's End.
The harness had to click it through JavaScript. Any game that takes the whole viewport can do the
same, by accident or on purpose.

## 2. Audit: who draws what during a round

| Surface | Origin | Who renders it | Can the game cover or fake it? |
|---|---|---|---|
| Game page | the game's registered origin (`games.avrana.net`), top-level document | the game | it is the game |
| Host End on a game page: BLUFF's button, EXPO's, the kit's `window.AvranaParty` controls, the integration bar's fallback End (ADR 0011 decision 5) | the game's origin | the game's page, with Party-authored code (shim, `party-follow.js`) where used | yes: it is DOM in the game's document. Authority is safe (Party Core refuses a non-Host's `end` with 403), but **reachability is the game's** |
| The bridge (`bridge.html`) | the Party origin, invisible frame inside the game page | the Party | the game decides whether, where and how big the frame is |
| Party Home, including the Host's way out (`#going-host`: Return / Bring everyone back, confirmed) | the Party origin, top-level | the Party | no: a different document |
| Browser chrome: Back, the address bar, the tab switcher; Esc or the back gesture to leave browser full screen | the browser | the browser | no |

Findings:

1. While the game page is the top-level document, **the Party cannot draw anything the game cannot
   cover.** The browser gives the top document the whole viewport, and an element in browser full
   screen hides everything outside it, including any Party frame.
2. A **trusted way out already exists**, on Party Home (ADR 0011 amendment, `hostReturn`). It was
   reachable only if the Host found their way back to Party Home.
3. Party Home moved every phone into the round with `location.replace`. A Host who started straight
   from Party Home (a fresh tab, Play again, the setup scene) therefore had **no Party page behind the
   game**: Back left the Party. A Host who went through the Library's pages had some, by accident.
4. Games must not own the authority (ADR 0011 decision 7; AVR-83 boundaries). They do not: every
   host verb is decided by Party Core. Only the control's **presence** is the game's.

## 3. Part 1, built: Back is the Host's way out

Party Home leaves itself in the history **for the Host only** (`location.assign`). Everyone else
keeps `location.replace`, so a follower's Back never bounces them through Party Home. The Host's Back
(the browser's, the Android back gesture, an iPhone edge swipe, Alt+Left) returns to Party Home,
whose existing way out shows. From there Return goes back to the game, and Back still works next
time. Bring everyone back is confirmed ("This ends the round for everyone."). Nothing about the
round changes until the Host chooses. Location, roles, lifecycle and the bridge protocol are
untouched.

Tested (Tier 2, `tests/party/host-escape.spec.ts`; the cross-origin case is in
`tests/party/follow-origin.spec.ts`):
- the page's End covered by a full-screen canvas, the way out reached by Back and used by touch;
- Return and Back again;
- a follower's Back and a follower on Party Home: no way out offered, Party Core's 403;
- keyboard only;
- a 320 × 568 phone: on screen, thumb-sized, nothing sideways;
- the round ended elsewhere while the way out is shown;
- offline End: says so, nothing changes, works after reconnecting.

The key tests fail without the change.

Limits:
- **A Host who becomes Host mid-round** (succession) has no Party Home behind their game page; they
  reach the way out by opening Party Home (address bar, home-screen icon). Part 2 would cover them.
- **Browser full screen:** on a phone the first back gesture may only leave full screen; a second
  one goes back. That is the browser's, and only a phone shows it (Tier 3).
- **A game's own history entries** (`pushState`) come before Party Home in the Back order.
- Not tried on iPhone Safari or Android Chrome, nor through nginx and HTTPS.

## 4. Part 2, proposed: a visible Party control over the game

Back is reliable but not discoverable. AVR-83 and AVR-292 already call a persistent, trusted Party
layer during play a friend-ready 1.0 requirement. Three shapes are possible; each needs a decision.

| Option | What | Cost | Trust |
|---|---|---|---|
| A. Party is the top-level document; the game is a full-viewport frame | Party Home draws its control above the frame | the largest change: ADR 0011 decision 5, ADR 0013 (`frame-ancestors`, the bridge becomes the parent), every game's full-screen use, Limited Mode | strongest: nothing the game does can cover it |
| B. The bridge frame becomes a small visible Party control | the shim places the frame in a fixed corner; the Party renders it | moderate: bridge v2 (geometry, show/hide), vendored shim, games keep the corner free (GAME-UX-CONTRACT) | medium: the Party renders it and a game cannot forge its clicks, but the game can still cover or hide it, including by element full screen |
| C. Game Contract rule: a game must keep the Host's End reachable | contract and conformance check only | small | weakest: the game owns it |

**Recommendation:**
- Keep Part 1 as the guaranteed way out.
- Choose **B** for discoverability, behind a bridge capability so a game without it still works.
- Pair B with **C** as a conformance check: the shim's corner, or the game's own End, must be
  hit-testable during play. The kit's `comply --boot` can check that in a browser.
- Leave **A** to AVR-83's longer design.

None of this is built.

**Owner decisions needed:**
1. Amend ADR 0011 decision 5 ("the game owns the viewport") to reserve a Party control.
2. The geometry: a corner, an edge, its size and its safe-area rules (AVR-83 owns this).
3. Bridge v2 and the paired Games change.

## 5. Not changed

Party Core and its lifecycle, `nav` and location, the session and bridge protocols, game pages,
Limited Mode's follower and ADR 0011's End / Party Home / Play again are all unchanged.
