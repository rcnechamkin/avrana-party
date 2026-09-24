# BLUFF: multi-agent robustness pass (2026-09-23)

**Game:** BLUFF (working title), the first Avrana-native game: a social bluffing card game
with Coup-style mechanics as a **temporary baseline** and original placeholder roles (Banker,
Agent, Smuggler, Broker, Guardian). Every phone is a complete seat at the table.

**Code:** `~/avrana-lab/avrana-party-games/` on `party`, a local fork of LAN Games (MIT),
`games/bluff/`. Branch `main` at `2cf4831`. **Not yet published**: the public repo
`rcnechamkin/avrana-party-games` still has to be created (see "Publishing" below).
Developer notes: `games/bluff/README.md` in that repo.

## How the pass ran

Six isolated workstreams. Each had its own git worktree, branch and port (8197–8200) on
`party`; the lead integrated everything on `main`. A final review agent then checked the
integrated diff.

| Workstream | Result |
|---|---|
| Rules / state machine | 241 tests (fuzz, 40 bot games, invariants). No rule bugs; P2 hygiene issues found |
| Mobile UX (2–6 players, 4 viewports) | layout broke at 5–6 players and on short Safari screens; fixed |
| Lifecycle (disconnect/reconnect) | abandoned games blocked the room for 22 min to ~2.8 h; countdown refresh lost the seat; pause/autopilot model proposed and adopted |
| Security (hostile client) | no P0/P1; P2 issues (results-screen cut, name impersonation, three core-level issues) |
| Full-game simulator | real WebSocket clients plus a rules oracle, checking invariants on every frame; 0 violations; mutation-tested |
| Code quality | no P0; reconnect banner, localStorage pollution, reduced motion; shaped the lifecycle code |

## Outcomes

- **P0 (privacy, authorization, crash, wrong rulings): none found.**
- **Lifecycle added:**
  - reconnect keeps the seat;
  - a passive autopilot plays for away seats (30 s for prompts, 60 s for your own turn);
  - an empty table pauses, may be taken over by a newcomer after 60 s, and is abandoned
    after 5 min;
  - Leave game and End game;
  - countdown refresh keeps the seat.
- **Protocol:**
  - a prompt `step` counter, so stale answers are rejected;
  - an idle turn takes Income (Coup only at 10+);
  - the results screen can't be cut short;
  - reserved and duplicate names are rewritten, and names are locked mid-game;
  - mid-game spectators are allowed beyond the 6 seats (bounded).
- **UI:**
  - a height-based table layout for 2–6 players;
  - the timer is a pill;
  - a gold "your call" question panel;
  - presence badges, a pause banner and takeover control, and the drawer controls.

## Verification (final code `2cf4831`)

- Full test suite: **1,197 passed** (391 BLUFF + 806 upstream LAN Games).
- Live protocol checks: frame-shape privacy check passed; attack script **24/24 held**;
  lifecycle probe **13/13 + 3/3**.
- Simulator: 10 runs across 2–6 players, including adversarial, spectator and timeout modes.
  **0 violations**; every game finished.
- Screenshots (Chromium): 2–6 players at 390×844, and 6 players at 360×740 and 390×664.
  0 non-modal overlaps, nothing off-screen, all tap targets ≥ 44 px, 0 page errors.
- **Not yet done: real-iPhone Safari testing.**

## Not fixed (framework level, in LAN Games `core/`)

- Oversized WebSocket frames are dropped only after they are received.
- Every message pushes full state to every socket.
- One device can fill all 6 lobby seats with made-up tokens.

## Publishing (blocked on the owner)

The public repo doesn't exist yet. Creating a new push credential on `party` was refused by
the agent's safety policy, so the owner must:

1. Create an **empty** public GitHub repo `rcnechamkin/avrana-party-games`: no README,
   licence or .gitignore, and **not** a GitHub fork. Upstream has moved past our base
   `5da1764`, so a fork would diverge.
2. Give `party` push access, e.g. a deploy key with write access, and push `main` only.
   **Never push `abandoned/classic-diplomacy`**: it contains the abandoned AGPL-dependent
   prototype.
