# BLUFF in a Party session end to end on the laptop: reconnect, session end, rematch (2026-09-28)

Status: **TESTED (laptop, Windows, Chromium)** for AVR-23, with AVR-22's review fixes and AVR-24
integrated. Not deployed, not LIVE, not phone-verified: the real-phone check is
`docs/runbooks/bluff-party-reconnect.md` (owner). The Party is authoritative throughout: a network
failure, reload, sleep/wake or an old browser token never changes a Party player's role, seat or
identity by itself.

Code: games integration branch `fix/avr-22-23-24-integration` at `d2798c4` (on games `main`
`e9954a6`), whose tree is identical to the stacked review branches
`fix/avr-24-party-completion` + `fix/avr-23-party-reconnect` (`1102fbe`); avrana-party
`fix/avr-23-party-bluff-reconnect-e2e` (on `main` `563c164`).

## How

`tests/provider/server.py --party-session` (`tests/provider/party_harness.py`) extends the existing
cross-repository provider harness instead of adding a stack: one origin (`127.0.0.1:8183`) serves
the real `/party/` shell, the real games server (BLUFF with a throwaway session key in
`$AVRANA_PARTY_KEYS` and the party's loopback address in `$AVRANA_PARTY_URL`, as the games
service's systemd drop-in sets them on the appliance) and, behind `/party/api/`, the real
`avrana.party.service` with `sessions.HttpGameLink` (proxied with Host, Origin, Cookie and
`X-Forwarded-For`, as nginx will). One origin matters: the device cookie is `Path=/party/`, and
the BLUFF page at `/games/bluff/?avrana=1` fetches its ticket from `/party/api/session/ticket`.
The game's `ended` report goes straight to the party service's loopback port. The E2E lives in
avrana-party because the cross-repository harness does (the games repository cannot import the
Party service, and its CI has no avrana-party checkout).

`tests/provider/party-session.spec.ts` (Playwright, a Pixel-sized and an iPhone-sized context per
test): members Join on a bare harness page, the host launches BLUFF, the phones open the real
BLUFF page (hubnet.js fetches a ticket and says hello with it), ready up and start. An init script
records every frame the page's own socket sends and receives.

| Check | Result |
|---|---|
| Reload: same `pid`, same two cards, same seat order; a fresh ticket in the hello, no `token` in hello or welcome; a `wc-token` pointed at someone else, and then an empty `localStorage`, change nothing | pass |
| Sleep/wake: offline and the socket dropped; the other phone shows `reconnecting`; 8 s later (inside `AWAY_GRACE` = 30 s) back online: same `pid` and cards, never a watcher welcome, other phone shows `here` | pass |
| Wake with the first ticket request lost at the network level | pass (failed before the fix: the player came back as a watcher) |
| A ticket request that times out (7 s, over the 5 s cap), then two network failures, then a ticket: exactly one new socket, with a ticket; same `pid` and cards | pass (fails on the pre-integration client) |
| Another member's own ticket: that member, never the first; a forged ticket: refused and closed; a `wc-token` hello with the first player's token and name: watcher, `me: null`; a stranger with no cookie: watcher, no `cards` anywhere; the second phone's frames only ever carry its own hand | pass |
| Stale: the host ends the session (the games server's `/end` confirms it) and launches again; the old session's ticket is refused | pass (failed before AVR-24's `/end` was integrated: the Party still showed the game as active) |
| Asleep through the end: the phone wakes to "This game is over." beside Back to Party and opens no socket (not a standalone seat, not a watcher); the host's rematch is joined without a reload, as a new Party session with a fresh table | pass (fails on the pre-integration client) |
| A late member watches (spectator); after End and a new launch that lists them, their page becomes a player without a reload | pass (fails on the pre-integration client) |

Games side (fake WebSocket, real BLUFF rules): `tests/test_bluff_party_reconnect.py` (same seat and
hand by a fresh ticket; nothing played for a return inside the grace; no other ticket, token or
spectator ticket takes the seat or sees the hand); `tests/test_party_session_end.py` (completion,
abandonment, `/end`, stale tickets after an end, a launch dropping watchers so the new roster
decides, a rematch as a new session, config needing both halves); `tests/hubnet_party_ticket_test.mjs`
(the client rules, with a fake clock).

## Bugs found and fixed

- **A waking phone came back as a watcher** (AVR-23, games `web/hubnet.js`): a ticket request that
  reached nothing counted as "no party session", so the page sent the ticketless hello, which the
  games server (correctly) treats as a watcher while a party session runs. Now network errors,
  5xx and timeouts retry and never send a ticketless hello.
- **A hung ticket request stalled reconnecting** (AVR-22 review): no timeout. Now 5 s per attempt;
  a timeout is retried like any network failure, not turned into a watcher (the review's first fix
  fell back to a watcher; resolved in favour of retrying). Bounded: after 20 failures in a row the
  page waits for online/visibility.
- **A browser hello racing a launch could be seated** (AVR-22 review, `core/net.py`): classified
  before the lock, joined after the launch. Now refused under the lock while the room belongs to a
  party session (results screen included).
- **A phone asleep through the end rejoined as a standalone player** (AVR-24 open item): the tab now
  remembers its Party session (sessionStorage, a session id, not a secret) and shows the ended
  state; it asks the Party every 5 s while visible and joins the next launch that includes it.
- **A watcher stayed a watcher when a later launch listed them** (AVR-22 review): a launch now drops
  every socket, watchers included; each phone returns with a fresh ticket and the roster decides.
- **The host's End never confirmed** on the pre-AVR-24 games server (no `/end` route): fixed by
  AVR-24's `/end`, adapted to current `main` (no `_refusing`).

## Counts (laptop, 2026-09-28)

- games (integration `d2798c4`): pytest **1334 passed, 2 skipped** (the 2 are the sibling-checkout
  vendoring comparison, which has no `../avrana-party` next to a temporary worktree; the
  cross-repo tests against the real Party service ran, with `AVRANA_PARTY_REPO` set);
  `hubnet_party_ticket_test` **26/26**; `hubnet_reconnect_test` **3/3**; `avrana_worker` **3/3**;
  `test_no_private_data`, `export_avrana_catalog --check`, `check_static.sh` clean.
  `ops/test_release_safety.sh` needs `rsync` (not in Git Bash); CI runs it on Linux.
- avrana-party (`563c164` + this branch): provider E2E **19 passed, 7 skipped** (the 7 are the
  party-session tests' planned skip in the iPhone-size project; each test drives both phone
  sizes itself); `party-session.spec.ts` alone **7/7**; offline Playwright **56 passed**;
  `node --test tests/offline/*.test.mjs` **56/56**; unit tests: the 6 known Windows-only failures
  (symlinks, the install script, POSIX signals, a path separator) and nothing else; catalog check
  and `cmp avrana-party.nginx arcade/nginx-site` pass.

## Open

- Real phones (the runbook): iOS Safari sleep/wake timing, Wi-Fi rejoin, the HTTPS path.
- AVR-25: crash/restart of either service (the Party is memory-only; a games restart forgets the
  session and its roster); back-to-back sessions are covered here only at the game-side reset.
- Deployment (AVR-51): Party Core unit, `location /party/api/` on 443, key files, and the games
  drop-in `deploy/avrana-party-session.conf` (its port 8191 and key path are PROPOSED).
- Tickets are v0 bearer credentials (ADR 0006): a ticket replayed within its 120 s is its own
  participant, never someone else.
- In the lobby (before START) a reload re-joins as a new in-game `pid` with the ready flag cleared,
  as in standalone play; seats exist only once the game starts.
