# Runbook: a service failed or will not recover (AVR-33)

For the owner at the Pi when a party stops working part way. What systemd and Party Core already do
on their own, how to see what did not recover, and the one command for each case. It deploys
nothing and changes no configuration.

**Evidence.** Party Core restart, crash and rollback recovery were verified on the Pi on 2026-09-29
(Party PR #29). Everything else here is source and Tier 1-2 tests (`tests/unit/test_service_isolation.py`,
`test_ops_status.py` `FailedRecovery`, `test_party_recovery.py`) and the local failure-injection harness
below (`test_failure_injection.py`, real processes, synthetic games). The Games, arcade, nginx and network
recovery runs on the appliance are **NOT RUN** (AVR-33, owner).

## What happens without you

| Fails | Automatic | The rest of the appliance |
|---|---|---|
| `avrana-party-core` | restarts after 3 s (`Restart=on-failure`). The party is memory-only (ADR 0006): members, host and the round are gone; phones rejoin with their device cookie, and the first to rejoin is host. A game it was running keeps that orphan session until a host launches that game again | games, arcade and nginx keep running (no unit depends on Party Core) |
| `avranaparty-games` (BLUFF, EXPO, ...) | restarts (`Restart=on-failure`); the new process holds no session. The delay is **not verified on the appliance**: its unit file is in the games repository, which marks it reconstructed and its `RestartSec=3` as still to be checked there (`systemctl cat avranaparty-games`) | Party Home and Party Core keep running |
| `avranaparty-arcade` | restarts after 3 s | the same |
| one native game, `avrana-game@<slug>` | its socket starts it again on the next connection. Five quick failures hit systemd's start limit: the instance **and its socket** end `failed` and that game is refused | other games, Party Core and nginx are untouched |
| any game, while a round is on | phones keep being sent to the game and bounce. With `session_recovery.close_lost_game` on (default off), three failed checks within the window (at least 10 s, and three of the game's connect timeouts + 2 s: 17 s at the default 5 s, 77 s for the arcade's 25 s; about 4 s when the game refuses connections outright and phones ask every 2 s) close the round as `abandoned` / `game_lost` and send everyone home | |

A crash loop is bounded to one start per 3 s and never stops on its own: with `RestartSec=3` the
default start limit (5 in 10 s) is never reached, so the unit shows `activating`, not `failed`.

## 1. Look

```sh
curl -s -H 'Host: party.avrana.net' http://127.0.0.1:8191/party/api/status | python3 -m json.tool
systemctl --no-pager status avrana-party-core avranaparty-games avranaparty-arcade nginx
systemctl --no-pager list-units --all --state=failed 'avrana-game@*'
journalctl -u <unit> -n 100 --no-pager
```

`summary.reasons` names what did not recover: `<unit> is restarting after failures (N automatic
restarts)` (a crash loop), `<unit> stopped restarting (start limit hit)`, `avrana-game@<slug>.socket
is failed and its game is in the live session`. A failed native game that no live session uses is only a note
(`avrana-game@<slug>.socket is failed but no live session uses it: sudo systemctl reset-failed ...`), so it never
fails a deploy's smoke check or triggers `--auto-rollback`; clear it when convenient with the command below. `recovery.units` gives each unit's restart count. A note `<unit> came back after N
automatic restart(s)` means it recovered; the cause is still in its journal. No answer from the
status URL means Party Core itself is down: use `systemctl status avrana-party-core`.

**The journal is volatile** (lost at reboot, [logs-and-retention](logs-and-retention.md)): copy what
you need (`journalctl -u <unit> --since -1h > ~/avr-<unit>-$(date +%F-%H%M).log`) **before** any reboot.

## 2. Recover

| Case | Do this |
|---|---|
| A round is stuck: phones bounce, the game says it is not running | the host brings everyone home (Party Home's way home, or End), then Start. No service restart is needed. End may be reported unconfirmed after a game restart; that is expected |
| A unit in a crash loop | read its journal first. A bad config or missing file never heals: fix it, then `sudo systemctl restart <unit>`. To stop the loop while you look: `sudo systemctl stop <unit>` |
| `start limit hit`, or a failed native game | `sudo systemctl reset-failed avrana-game@<slug>.service avrana-game@<slug>.socket` then `sudo systemctl start avrana-game@<slug>.socket` (for another unit: `reset-failed <unit>`, then `start <unit>`) |
| Party Core restarted mid-round | phones rejoin by themselves; the host role goes to the first to rejoin (hand it back in Party Home). The old game's session is replaced at the next Start of that game |
| A game uses all CPU and does not stop on `systemctl stop` | see "A stopped journal" below; `sudo systemctl kill -s KILL <unit>` ends it, and `TimeoutStopSec` does the same after its timeout |
| It started after a deploy | `ops/deploy.sh --rollback` returns to the last known good pair ([deploy](deploy.md)) |

After any of these, the status `summary.state` should be `ok` (or list only notes), and one phone
should complete Join, Start and End.

## Failure-injection harness (local, not the appliance)

`python3 -m unittest discover -s tests/unit -p test_failure_injection.py` (AVR-33, about 90 s). Party
Core runs as its own process from a config file, as on the Pi; each game is its own process: a
**synthetic stand-in** (`tests/fixtures/failure/game_process.py`) that speaks the real session protocol.
It is not BLUFF, the Games server or the arcade, and nothing here is systemd or nginx. Kills are real
(SIGKILL), a freeze is SIGSTOP (Linux only) and a hang is a process that accepts connections and never
answers. On 2026-10-19 it showed, for a game killed, hung, frozen, down at Start, crash-looping five
times, and for Party Core killed mid-round:

- other phones' `/party/api/state` stays under 1 s while a game is dead or silent: Party Core calls
  games outside its lock;
- the host's End returns within one end call (the game's link timeout, capped at `END_LINK_TIMEOUT`,
  12 s: 5 s for BLUFF, 12 s for the arcade on the appliance) and everyone is home;
- a Start against a game that is down, or a wedged arcade slot, fails within the launch timeout plus
  the rollback `end` (on the appliance up to 25 + 12 s for the arcade, still under Party Core's own
  60 s launch limit) with a reason, and leaves nothing launching or orphaned (the late `end` lands
  after the late launch);
- after five crash-and-restart cycles there is one host, one session at the game, versions only rise,
  and (Linux) Party Core's thread count stays within 4 of where it started;
- a restarted Party Core comes back clean; the old host's stale request is refused; the next Start
  replaces the game's orphan.

It also pins the two limitations in "Not decided here": a restarted game refuses Party tickets until
the host ends the round (followers bounce), and a game that is wedged but still listening is never
counted as lost, because the lost-game check is a TCP connect. Party Core's rollback of a failed Start
assumes a game handles launch and end one at a time, so the rollback `end` lands after a late launch.
The managed arcade runtime does (`avrana.party.managed` holds a lock), and its own start timeout (15 s)
ends before Party Core's link gives up (25 s). The gamekit and the Games server live in the games
repository: the gamekit serves on threads under its own lock, and neither was checked for this
ordering here (AVR-673 follow-up). The stand-in serializes like the arcade; a game that handled them
concurrently could keep a late launch as an orphan until the next Start replaces it.

## A stopped journal and native Node games

Until Games PR #71, a Node game (`avrana_gamekit/js/game-runtime.mjs`) whose stdout or stderr broke
(EPIPE, for example while journald restarted) spun at 100% CPU and did not act on SIGTERM. A
`systemctl restart systemd-journald`, or journald dying, could therefore leave a native Node game
hot and unstoppable until its stop timeout or a KILL. Check the Games release on the Pi includes
PR #71 (`/party/api/status`, `games.deployed_sha`); until it does, restart journald only with no
round on, and check `top` for a Node process afterwards.

## Not decided here

Turning `close_lost_game` on (C-08 in [offline-acceptance](offline-acceptance.md) first), ending a
restarted Party Core's orphan session at startup, and reading a game's "no such session" refusal as
ended are owner decisions recorded in
[the session-probe proposal](../design/proposals/2026-10-12-session-probe.md) section 5. Whether
Party Core, Games and the arcade get an explicit `StartLimitIntervalSec`/`StartLimitBurst` is also the
owner's (AVR-33): today a crash loop retries indefinitely, which favours self-healing over stopping.

The lost-game check counts a refused connection, not a game that accepts connections and never
answers: making a wedged game count needs an application-level health answer from games, a
Party↔game contract change (AVR-33 follow-up), not built here.

