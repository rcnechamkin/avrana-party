# BLUFF in a Party session end to end on the laptop: reconnect, session end, rematch (2026-09-28)

Status: **TESTED (laptop, Windows, Chromium), on the Pi over the Party Wi-Fi, and phone-verified on
an iPhone** (see "Real-phone result") for AVR-23, with AVR-22's review fixes and AVR-24 integrated.
Not deployed, not LIVE: the production HTTPS path is AVR-51's. The Party is authoritative throughout: a network
failure, reload, sleep/wake or an old browser token never changes a Party player's role, seat or
identity by itself.

Code: games integration branch `fix/avr-22-23-24-integration` at `d2798c4` (on games `main`
`e9954a6`), whose tree is identical to the stacked review branches
`fix/avr-24-party-completion` + `fix/avr-23-party-reconnect` (`1102fbe`, then `0ddc6cb` with the
ended-screen fix below); avrana-party
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

## Remote run: the real Pi over the Avrana Party Wi-Fi (desktop browser automation)

Status: **TESTED on the appliance's radio path**, not phone-verified. The dev laptop joined the
Party Wi-Fi (`10.42.0.46`, default route via `10.42.0.1`) and drove the supervised lab harness on
the Pi (`http://10.42.0.1:8190`, runbook step 2, bounded to 60 min, stopped afterwards) with
Playwright: separate Chromium contexts per player (Pixel- and iPhone-sized), so cookies and storage
were isolated. Pi code: games `0ddc6cb` (first runs `1102fbe`), harness `bc81776`. Final run:
**33/33 checks**; the Pi's EVENT log (`~/avrana-lab/playtest/avr23-2026-09-28-0900-laptop-playwright.log`,
kept there, not committed) matches every step.

| Step | What was done | Result |
|---|---|---|
| Setup | two members join; host launches (`players: 2`); both open BLUFF with tickets, ready, start | p1/p2 seated, two cards each, hello carried a ticket and no token |
| R1 | reload A | same Party session, pid, seat, cards; reconnect about 0.4-0.5 s; EVENT `disconnect` then `rejoin p1` |
| R3~ | A's page frozen 20 s (`Page.setWebLifecycleState frozen`, JS and timers stopped), then resumed | same pid/seat/cards; the socket stayed open, so no reconnect was needed. **Not** iOS sleep: the OS did not drop the connection |
| R4 | A offline about 10 s (browser network emulation; the socket then closed) | no socket opened while offline; B saw A `reconnecting`; 4 ticket requests failed (`ERR_INTERNET_DISCONNECTED`) and were retried; reconnect about 0.3 s after the network returned, with a ticket, same pid/seat/cards |
| R5 | close A's tab, open the BLUFF URL in a new tab (same browser, cookie kept) | same participant and role, same seat/cards, game still `playing` |
| E1 | B offline with its socket gone; host ends; B back online | Party `ended_by_host`; B's ticket request got 409 (no game); B shows "This game is over." beside Back to Party with the table hidden; no socket, no rejoin |
| E2 | host launches again | new Party session (`players: 2`); B joined it by itself 0.6-4.8 s later (the 5 s poll), no reload; new session remembered; fresh lobby, no old cards; the first play-through's ticket is refused (`ticket_refused session`) |
| E3 | a third member joins while a game runs, opens BLUFF; host ends and launches | watcher (`welcome watch`, no hand in any frame); the next launch lists 3 players and the watcher becomes a player about 4.8 s later, no reload, no navigation |

No 5xx anywhere. The only non-200 Party answers were the expected 409 "no game" answers after an end.

**Defect found by this run, fixed:** in E1 the page showed the ended note above the last table it
had drawn (the old hand, "Waiting for Ana...", a turn timer), which reads as a game still on. The
protocol was right; the screen was not. games `0ddc6cb` hides the integrated game room in the ended
state and shows it again for the next play-through (node tests; `party-session.spec.ts` asserts it
and fails on `1102fbe`); the rerun on the Pi confirmed it.

**Test harness race found, fixed (test only):** a host action clicked on the lab page while it still
showed "Loading..." carried no `if_version`; the Party answered 409 and the lab page's next poll
overwrote that message, so a test could wait out its timeout on a click that had already been
refused (one intermittent failure in the watcher test). `hostAction` now clicks only once the view
is loaded; the full provider suite then passed three runs in a row.

What desktop automation cannot show, so it stays for real phones: iPhone Safari (WebKit) lock and
wake, where the OS suspends the page and drops its connection; a phone leaving and rejoining the
Party Wi-Fi at the radio level; iOS or Android killing a background tab.

## Real-phone result (owner, iPhone with Safari, 2026-09-28)

On the same Pi lab harness over the Avrana Party Wi-Fi (`http://10.42.0.1:8190`; games `0ddc6cb`,
harness `bc81776`), the three checks desktop automation cannot reproduce all **passed**, as reported
by the owner (device model and iOS version not recorded):

| Check | Result |
|---|---|
| R2: real screen lock about 15 s, then wake | same seat and cards; never a watcher |
| R4 on the phone: Wi-Fi off about 10 s, then on (radio) | same seat and cards |
| E1 with a really locked phone: host ends the game, then wake | "This game is over.", no table |

Not covered: the production HTTPS path (`https://party.avrana.net`, `Secure` cookie, nginx
`location /party/api/`), which needs the Party Core deployment (AVR-51).

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
  `hubnet_party_ticket_test` **26/26** (28/28 at `0ddc6cb`); `hubnet_reconnect_test` **3/3**; `avrana_worker` **3/3**;
  `test_no_private_data`, `export_avrana_catalog --check`, `check_static.sh` clean.
  `ops/test_release_safety.sh` needs `rsync` (not in Git Bash); CI runs it on Linux.
- avrana-party (`563c164` + this branch): provider E2E **19 passed, 7 skipped** (the 7 are the
  party-session tests' planned skip in the iPhone-size project; each test drives both phone
  sizes itself); `party-session.spec.ts` alone **7/7**; offline Playwright **56 passed**;
  `node --test tests/offline/*.test.mjs` **56/56**; unit tests: the 6 known Windows-only failures
  (symlinks, the install script, POSIX signals, a path separator) and nothing else; catalog check
  and `cmp avrana-party.nginx arcade/nginx-site` pass. At games `0ddc6cb` with the `hostAction` fix:
  provider E2E 19 passed, 7 skipped, three runs in a row.

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
