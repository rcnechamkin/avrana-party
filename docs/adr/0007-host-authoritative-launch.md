# ADR 0007 — Host-authoritative launch: Party Home follows Party Core

Status: **proposed** (implemented and TESTED on a laptop on branch `fix/avr-20-127-host-launch`;
not merged, not deployed; no real phone yet). Date: 2026-09-28. Linear AVR-20, AVR-127.
Amends ADR 0006: reverses its deferral of "automatic navigation" for Party Home only.

## Context

Party Core v0 (ADR 0006) already owns membership, presence, host, and the one game session, and it
refuses a launch from anyone but the host. Party Home did not use it: every phone picked a tile
and opened `/games/<slug>/?avrana=1` on its own. For party games that meant nobody's choice was
authoritative, phones could end up in different games, and the host role had no effect.

## Decision

1. **Party mode is progressive enhancement.** Party Home asks `GET /party/api/state` at boot. Only
   a Party Core view (a string `party`, an integer `version`, `members` and `games` arrays) turns
   Party mode on; a 404 or any other answer keeps today's catalog page unchanged. Production has
   no Party service yet (AVR-51), so production behaviour is unchanged. Nothing is decided from
   the user agent.
2. **Party games come from Party Core; where they open comes from the catalog.** `view.games`
   (the configured party games, now visible to every phone, not only the host) marks which
   tiles are party games. Party Home maps a Party Core id to the catalog title by `id`, then by
   the LAN provider's `legacySlug`, and opens it only at `launchTarget()`. No game id is written
   into Party Home.
3. **Only the host starts a party game.** The host's tile says "Start for everyone"
   (`POST /party/api/session/launch` with `if_version`). Others see "The host starts it"
   (disabled); a phone that has not joined sees "Join the party to play". Party Core re-checks
   host rights and the version and refuses otherwise (`not_host`, `stale`, `busy`). If the only
   refusal is `stale` (the party moved on: someone joined, a phone woke), Party Home re-reads the
   state and, if this phone is still the host of an idle party, tries **once** more. Every other
   refusal stands and is shown.
4. **Sync is the existing long poll.** Party Home keeps one `GET /party/api/state?since=V&wait=20`
   open (the service already caps it at 25 s and wakes it on every commit; the poll is also the
   member's heartbeat). No WebSocket or SSE is added: the version-numbered state and the long
   poll already give ordered, idempotent, resumable updates through nginx and the service
   worker's never-cache rule, with nothing new to deploy. An action's own answer always wins
   over a poll that was already in flight; otherwise views only move forward by version.
5. **Followers move only on a committed start** (PARTY-LIFECYCLE R2). When a phone's view shows
   the session `active`, Party Home announces it in a live region ("The host started BLUFF.
   Joining…") and opens the game ~0.9 s later. The game gets its Party identity through the
   existing ticket path (ADR 0006), unchanged.
6. **Reconnect rule.** A page that watched the start happen always enters. A page opened while a
   game is on (reload, new tab, a phone that slept, a late member) enters, **unless this tab
   already entered this session** (`sessionStorage['avrana-party-entered']` = the session id):
   then it came back with Back to Party on purpose, and it only offers "Rejoin". If the tab cannot
   remember (storage blocked), a reopened page only offers, so it can never trap anyone. Old
   memory (another session id) converges on the current session.
7. **While a party game is on** its tile says "Rejoin" and the party panel shows it with
   "Rejoin" (and "End the game for everyone" for the host). Every other party game is closed to
   everyone ("Party is playing BLUFF"); Party Core also answers `busy`. **Standalone titles stay
   exactly as they are**: they never were party games and cannot be mistaken for the party's.
   Leaving is explicit ("Leave the party"); the fixed Back to Party return stays.
8. **Host succession never ends the game.** A player in the active game counts as present, so a
   host who leaves mid-game hands over at once to the earliest-joined present member, including
   players (before, `_successor` skipped `playing` members and the role went vacant until
   someone's Party Home polled). The session, its roster and participant ids do not move.

## Consequences

- Core change: `view.games` for every phone; `_successor` counts `playing` as present. Unit and
  HTTP tests: `tests/unit/test_party_core.py`, `tests/unit/test_party_service.py` (`HostLaunch`).
- Party Home: `web/party/lib/party-mode.js` (pure decisions, `tests/offline/party-mode.test.mjs`),
  `web/party/lib/party-client.js` (the poll and actions), the Party panel in `index.html`/`app.js`.
- Cross-repo E2E with the real Party service, games server and BLUFF page:
  `tests/provider/party-home.spec.ts`.
- One host start moves the version twice (`launching`, then `active` when the game accepts); a
  follower may see both, and moves only on `active`.
- Not changed: the ticket protocol, BLUFF's own ready/countdown lobby, `/games/` pages. A game page
  that shows "This game is over" does not follow the host into a *different* next game on its own;
  its Back to Party link leads to Party Home, which does (a games-side follow is a possible later
  step, not part of this decision). **Superseded in part by ADR 0008 (AVR-128):** pages inside
  games now follow Party Core's committed moves too, and the host can switch games in one step.
- Still needs a real-phone check (Tier 3): the auto-follow on iPhone Safari and Android Chrome,
  sleeping phones, and the long poll through the real nginx `location /party/api/` (AVR-51).
