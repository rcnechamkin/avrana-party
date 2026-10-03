# ADR 0011 — The console model: one party, one place, the host moves it

Status: **accepted; implementation merged to main** in
[Party PR #34](https://github.com/rcnechamkin/avrana-party/pull/34) and companion
[Games PR #13](https://github.com/rcnechamkin/avrana-party-games/pull/13). Tier 1–2 source
verification is recorded below. Production deployment and Tier 3 real-phone validation remain
pending [AVR-212](https://linear.app/avranakern/issue/AVR-212/deploy-and-real-phone-verify-adr-0011-console-model).
Latest verified production remains Party `956b968` / Games `c6d7b52`; see [SYSTEM](../SYSTEM.md).
Status reconciled 2026-10-01; the decision below is unchanged.
Date: 2026-09-29. Supersedes the "offer, don't bounce" reconnect rule of ADR 0007 §6, the
"follow only moves you watched" rule and the in-game Party panel of ADR 0008, and moves the setup
panel of ADR 0010 off the game page. Keeps everything else of ADRs 0006–0010.

## Context

A real-device test (2026-09-29) showed Avrana behaving like several websites loosely following
each other, not one shared console:

- A browser was "connected to the party" and then had to press **Join the party**.
- A phone could read "Your party is playing BLUFF" and at the same time open and configure
  Backgammon. Followers had **Back to Party** inside a game and wandered off.
- Moves were offers ("Rejoin", "Join them") or depended on the page having watched them happen, so
  a reloaded or reopened phone could sit in the wrong place.
- BLUFF's setup was Party UI stacked above the live table, with an onboarding carousel on top of
  that: unreadable, overlapping controls on a phone.
- Party-state narration ("Setting up BLUFF", "0 playing · 0 watching", role-lock prose) sat above
  the game during play.

## Decision

1. **One location.** Party Core has one authoritative location, in every view:
   `location = {at: home | setup | game | results, game, session}` (derived from the committed
   `nav` of ADR 0008 and the session state). `setup` covers a round being set up and starting;
   `game` a round on; `results` a round the game itself finished, **held** until the host moves
   on. Only the Party Host moves it: start a game (→ setup, or → game for a game without a
   pregame), start the round (→ game), End (→ home), and from the results **Play again** (→ a new
   setup) or **Party Home** (`POST /party/api/home`, host-only; → home, and the game's held
   results room is released with the protocol's `end`). A follower's own actions never change it.
2. **Presence is automatic.** A phone with an Avrana profile (name, Gaze avatar) is in the party:
   Party Home and every game page call `join` on their own, on load, after a Party Core restart
   and when the profile is saved (rename). There is no Join and no Leave button. Members carry
   their bundled Gaze avatar id (validated `gaze-NN`; anything else shows the default).
3. **Every member page is where the party is — always.** `destination(view, here)`
   (`web/party/lib/party-mode.js`) is the one rule: home and setup are Party Home; a round and
   its results are the game's page. Party Home, each game page (`party-follow.js`, loaded by the
   games' integration script) and the arcade apply it on load, on reconnect and on every change,
   with `location.replace` — no offers, no banners, no "Rejoin", no memory of what the tab did.
   Party Home cannot be browsed and no other game can be opened during a round; a standalone
   title may stay open while the party is home (a personal game) and is left the moment the host
   moves the party. A move that arrives while the phone is offline waits for the network.
4. **The setup is the Party's own full-screen scene** on Party Home (`#scene`), in the Party Home
   design system (Tailwind v4 + daisyUI v5 `avrana` theme, Lucide, DiceBear Gaze): the game's art
   and title, who hosts, a one-line premise, one **How to play** entry, the round's roster (Gaze
   avatars with a Play/Watch/choosing badge), two large **Play this round / Watch this round**
   choices, and in the same place either the host's **Start game** (disabled with one concise
   reason) or the followers' **Waiting for <host> to start**; the host also has a quiet **Choose
   another game**. The game's table is not on screen until the round starts. The game supplies
   the content as data: `onboarding.json` beside its entry (`avrana.onboarding/v0`: premise,
   `rules` sections with `{fact}` placeholders, and the acknowledgement key). How to play is one
   sheet (a daisyUI modal), open and closed without touching the setup; a first-timer's Play opens
   it first and "Got it, I'll play" is their Play.
5. **The game owns the viewport during a round.** In a Party, the games' integration bar (and so
   Back to Party) is hidden for everyone; the page shows no Party prose. Host controls live in the
   game's own chrome through `window.AvranaParty` (`isHost`, `hostName`, `end`, `goHome`,
   `playAgain`, `onChange`): BLUFF adds an End button beside its `?` (confirmed in its own
   dialog) and, on its results screen, **Play again / Party Home** for the host and **Waiting for
   <host>** for everyone else. A game without such a shell gets one host-only End in its bar.
6. **Rounds are the host's to end.** In a Party round BLUFF refuses its own `end_game` and
   empty-table takeover (players and spectators alike); its per-player forfeit stays (it changes
   no one's location). A Party round's results are held (no 20 s timer back to a lobby of the
   game's own).
7. Unchanged: Party Core as the authority for host, roles and roster; the Play/Watch pregame
   rules and role boundary (ADR 0010); spectator privacy (only Party spectator sockets get
   BLUFF's omniscient view; players and TVs never); tickets, seats, reconnects; standalone play
   (no Party Core, no profile, or plain HTTP: the pages are exactly what they were).

## Amendment (2026-10-02): one Standard Mode activity

The decision above is unchanged. This adds the product-level invariant it already implied:

- **Standard Mode has exactly one authoritative Party activity/location.** One appliance, one
  Party, one active activity at a time; `location` is singular by design, not by current
  limitation.
- **Simultaneous games or tables are not a Standard Mode product feature.** Standard Mode
  architecture (Party Core, routing, the registry, results) is not shaped around side games.
- **Any future Developer Mode relaxation is explicitly separate.** If multi-activity
  experimentation is ever exposed to technical users, it is a distinct mode that must not add
  states, UI or protocol surface to Standard Mode ([ADR 0014](0014-native-games-isolated-lan-games-retired.md) decision 10).
- Decision 3's "a standalone title may stay open while the party is home (a personal game)" and
  decision 7's "standalone play" describe LAN Games standalone compatibility, which ADR 0014
  retires as a product mode; they remain true of current source until that retirement lands.
- Decision 5's `window.AvranaParty` host controls keep their product meaning; their same-origin
  transport is revisited by [ADR 0013](0013-party-and-game-browser-origins.md).

## Consequences

- Party Core: `location()`, `go_home()`, member `avatar` (`avrana/party/core.py`), `POST
  /party/api/home` and `{avatar}` on join/rename (`service.py`). Tests: `test_party_core`
  `ConsoleLocation`.
- Party Home: `web/party/index.html`, `app.js` (presence, routing, the scene), `party-mode.js`
  (`destination`, `roster`, `setupPanel`), `party-client.js` (`join/rename` with avatar,
  `goHome`), `party-follow.js` (routing, presence, the `AvranaParty` API), theme components in
  `web/src/party.css` (`avrana-scene`, `avrana-lineup`, `avrana-choice`, `avrana-rules`; daisyUI
  `modal`), Lucide `crown` and `hourglass`.
- Games: `web/avrana-integration.js/.css` (no bar in a Party), `web/hubnet.js` (a Party's
  "Round over" with the host's choices on reconnect during results), `core/session.py` (held
  results), `core/net.py` (a held results room released with its own outcome),
  `games/bluff/{game.py, web/client.js, web/index.html, web/table.css, web/onboarding.json}`.
- Tests: unit (Party Core location, host-only home, avatars; games: held results, host-only end,
  onboarding facts pinned to the rules), modules (the destination matrix; the follower's routing,
  presence and host API), provider E2E at 390x844 (`party-pregame.spec.ts`: presence, the setup
  scene, layout geometry and screenshots, host-only Start, blocked follower navigation, reconnect,
  privacy, host End; `party-home.spec.ts`: the same for a direct game; `party-session.spec.ts`).
- Old sessions' tabs, sessionStorage memories and offers are simply ignored: the location decides.
- Not verified on real phones (Tier 3). A phone asleep through a move lands where the party is on
  wake; iOS/Android back-button behaviour after `location.replace` is untested.

## Amendments

- **2026-10-02 (AVR-223, lifecycle edge cases from the hostile audit).** `results` is held only
  for a round the game reports as `completed`. An `abandoned` round (the game, or a managed
  runtime, gave up) has no results screen worth standing on: the party goes home at once and the
  session is ended at the game so nothing is held. A host switch moves `nav` to the next session as
  soon as it exists (location `setup` while it launches) instead of passing through Party Home. An
  end that the game does not confirm within `END_TIMEOUT` records a `detail` (and names the dropped
  switch); the link's `end` gives up before that timer does. A launch that succeeds after the party
  cancelled or timed it out is ended at the game. PARTY-LIFECYCLE.md already described the
  abandoned → home behaviour; Core now matches it.
