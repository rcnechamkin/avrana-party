# Runbook: a service failed or will not recover (AVR-33)

For the owner at the Pi when a party stops working part way. What systemd and Party Core already do
on their own, how to see what did not recover, and the one command for each case. It deploys
nothing and changes no configuration.

**Evidence.** Party Core restart, crash and rollback recovery were verified on the Pi on 2026-09-29
(Party PR #29). Everything else here is source and Tier 1-2 tests (`tests/unit/test_service_isolation.py`,
`test_ops_status.py` `FailedRecovery`, `test_party_recovery.py`). The Games, arcade, nginx and network
recovery runs on the appliance are **NOT RUN** (AVR-33, owner).

## What happens without you

| Fails | Automatic | The rest of the appliance |
|---|---|---|
| `avrana-party-core` | restarts after 3 s (`Restart=on-failure`). The party is memory-only (ADR 0006): members, host and the round are gone; phones rejoin with their device cookie, and the first to rejoin is host. A game it was running keeps that orphan session until a host launches that game again | games, arcade and nginx keep running (no unit depends on Party Core) |
| `avranaparty-games` (BLUFF, EXPO, ...) | restarts (`Restart=on-failure`); the new process holds no session. The delay is **not verified on the appliance**: its unit file is in the games repository, which marks it reconstructed and its `RestartSec=3` as still to be checked there (`systemctl cat avranaparty-games`) | Party Home and Party Core keep running |
| `avranaparty-arcade` | restarts after 3 s | the same |
| one native game, `avrana-game@<slug>` | its socket starts it again on the next connection. Five quick failures hit systemd's start limit: the instance **and its socket** end `failed` and that game is refused | other games, Party Core and nginx are untouched |
| any game, while a round is on | phones keep being sent to the game and bounce. With `session_recovery.close_lost_game` on (default off), three failed checks within the window (10 s, or 17 s when each check waits out the 5 s connect timeout; about 4 s when the game refuses connections outright) close the round as `abandoned` / `game_lost` and send everyone home | |

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
is failed`. `recovery.units` gives each unit's restart count. A note `<unit> came back after N
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
