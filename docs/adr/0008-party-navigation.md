# ADR 0008 — Party navigation: one activity, host switch, pages inside games follow

Status: **proposed**. Implemented and TESTED on a laptop on branches `fix/avr-128-party-navigation`
(this repository) and `fix/avr-128-follow-party` (games). Not merged, not deployed, and not yet
tried on a real phone. Date: 2026-09-29. Linear AVR-128. Extends ADR 0007, which covered Party Home
only.

## Context

ADR 0007 made the Party Host's start authoritative, but only Party Home followed it. A phone
already inside a game (BLUFF, the arcade, a standalone LAN title) never saw a later host move.
Three problems followed:

- The host could not move the party to another game in one step. They had to End, then Start.
- Nothing stopped a phone from drifting away. Players who stayed in a game after the host ended it
  had to find their own way back.
- The one-session rule was enforced only as "busy". A switch had no defined ordering, so nothing
  stopped the next game's runtime from starting while the old one was still resetting.

Real-phone testing on 2026-09-29 confirmed this gap. The rules were already written:
PARTY-LIFECYCLE R2 and R5, the `in_game → launching` switch, and "Switching between emulated games".

## Decision

1. **Party Core says where the party is.** Every view carries
   `nav = {seq, to: 'game'|'home', game, session, from}`.
   - `seq` rises only on a committed transition (R2):
     - a session became `active` (`to: 'game'`);
     - the Party Host ended it (`to: 'home'`, `from` = that game);
     - a start that replaced a running game failed (`to: 'home'`).
   - Intent never moves `nav`: launching, a switch that is still ending, a cancelled or failed start from the lobby.
   - A game that ends by its own rules (`completed`/`abandoned`) also leaves `nav` alone. Its end screen is the intermission; the host's next start moves everyone.
   - `nav` restarts in a new party, so clients compare `(party, seq)` (R5).
2. **One Party activity, enforced by the server.** There is at most one live session: `launching`, `active` or `ending`.
   - `launch` from anything but the lobby is refused with `busy`.
   - Only the current Party Host may start, switch or end, and only with the current `if_version`. Anyone else gets `not_host`, `not_member` or `stale`.
   - A ticket request that names its game (`{game}`) gets `409 no_game` while the party plays another game. So a direct or stale URL can neither join nor start a party game.
   - Standalone titles are unchanged: they are not Party activities.
3. **Switching is end, then launch.** `POST /party/api/session/switch {game, if_version}` (host only, from `active`):
   1. The current session goes to `ending`, with `switching_to` set. Tickets for it stop at once.
   2. The service asks that game's server to reset, and waits for the answer or the timeout.
   3. In one locked step, Party Core closes the old session and opens the next one (`launching`).
   4. The next game's server is told to launch.

   Nothing can start in between. If the old game does not confirm its end, the switch stops there: `nav` goes home and the view says why. Nothing is started on top of a game that may still be running. A switch to the same game is a fresh round (a new session).
4. **Pages inside games follow Party Core.** `web/party/lib/party-follow.js` is loaded, when the page is a secure context, by:
   - every integrated LAN game page (the games fork's `avrana-integration.js`);
   - the arcade page.

   It long-polls `/party/api/state` like Party Home, using the same client, and applies `follow()` (`party-mode.js`):
   - `to: 'game'`: go to that game's catalog launch target, unless this page already is that game.
   - `to: 'home'`: go to Party Home, only if this page is the game that was ended. The arcade and standalone titles follow a start, never an end.
   - The page moves only on a move it watched in this party. Opening or reloading a page never moves anyone; the page shows "Your party is playing X · Join them".
   - Someone who is not a member never moves: Leave stays personal.
   - Moves are announced in a live region and happen after about 0.9 s. A move overtaken by a newer one is dropped.
   - On a move, the page records the session in `avrana-party-entered`, Party Home's reconnect memory (ADR 0007 §6).
5. **The Party Host has the controls where they are.**
   - Party Home offers the host "Switch everyone to this" on the other party games, where others still see "Party is playing X".
   - A game page offers the host "End for everyone". The first tap arms it and the second ends it, so a stray tap never moves the party.
   - Back to Party stays a personal link. It moves only this phone, and Party Home then offers Rejoin (ADR 0007).

## Consequences

**Where the code and tests are:**
- **Core:** `avrana/party/core.py` (`nav`, `pending`, `begin_switch`, `launch_pending`, `participant_for(game)`).
- **Service:** `avrana/party/service.py` (`switch`, `/party/api/session/switch`) and `avrana/party/sessions.py` (the ticket's `{game}`).
- **Tests:**
  - `tests/unit/test_party_core.py` `Navigation`, plus the fuzz with switches: `nav.seq` never goes backwards, and `nav` never points at a game other than the active one.
  - `tests/unit/test_party_service.py` `PartyNavigation` and `UnconfirmedSwitch`: runtime ordering with a recording provider link, concurrent and stale host tabs, followers' long polls.
  - `tests/unit/test_party_session_flow.py`: old tickets die on a switch, and a ticket for another game is refused.
  - `tests/offline/party-mode.test.mjs` and `tests/offline/party-follow.test.mjs`.
  - `tests/provider/party-home.spec.ts` (AVR-128 cases).

**What this does not do:**
- **The arcade is not a Party activity yet.** The emulator runs as an always-on service (`avranaparty-arcade`), which Party Core does not start or stop. Stopping it is an owner step (ROADMAP N4). An arcade page follows the party into a party game, but Gauntlet II and a party game can still run at the same time. Making the arcade a Party-launched provider means giving it the launch/end half of the session protocol and letting Party Core stop it. That is a separate, owner-approved change (unit and privileges), tracked as Linear AVR-134.
  **Update:** ADR 0009 (AVR-134) does this without new privileges. Party Core starts and stops the
  arcade's runtime through the session protocol, on a loopback control port.
- **Order of deployment.** The follower ships in the Party web release (`/party/lib/party-follow.js`) and the games fork loads it. Either can deploy first:
  - a game page with no follower module, or no Party Core, is unchanged;
  - an older Party Core has no `nav`, so the follower never moves anyone;
  - an older Party Core ignores the ticket's `{game}`.
- **Not verified:** real phones (Tier 3). The in-game follow on iPhone Safari and Android Chrome, sleeping phones and the host's in-game End still need a real-phone check.
