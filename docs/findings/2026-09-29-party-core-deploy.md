# 2026-09-29: Party Core deployed; arcade watchdog and log retention live

Status: **LIVE, server-side verified.** Party Core v0 (AVR-51), the arcade video-stall watchdog
(AVR-92) and log/telemetry retention (AVR-30) run in production. Nothing here was checked on a
phone; the phone checks are Tier 3 and still open.

## Revisions

| Thing | Before | After |
|---|---|---|
| Production checkout `/home/cody/avrana-party` | `15f6322` | **`6bd5af4`** (`main`, PR #26) |
| Games checkout `/home/cody/avrana-party-games` | `c6199be` | **`eeedb19`** (games `main`, PR #10; staged from a laptop bundle, detached) |
| `/party/` web release | `20260929T030813Z-15f6322efc7d` | **`20260929T183713Z-6bd5af43ff96`** |
| Party Core `avrana-party-core` | not installed | active since 11:37:05 PDT, `127.0.0.1:8191` only |
| Games service | fork drop-in only | + `avrana-party-session.conf` (key dir and `AVRANA_PARTY_URL`); restarted 11:37:10 |
| Arcade | restarted by the owner at 02:31 | restarted 11:37:14 on the watchdog code |
| nginx site | no `/party/api/` | `location /party/api/` added; live site == repo (`cmp`); backup `/root/avrana-party-site.20260929T183701Z` |

**How it was run:**
- I fast-forwarded both checkouts; that step needs no sudo.
- The owner ran one script, `sudo bash ~/avrana-deploy-20260929.sh`, which follows the runbook steps in order:
  1. BLUFF key: created, 0600, owner `cody`, never printed.
  2. Party Core config and unit, `enable --now`.
  3. Games Party-session drop-in, then a games restart.
  4. `install-party-web.sh`.
  5. nginx: backup, `nginx -t`, reload, then a `cmp` against the repo.
  6. Arcade restart.
  7. Telemetry installer and journald drop-in.

All steps succeeded.

## Server-side verification (read on the Pi)

- **Services:** `avrana-party-core`, `avranaparty-games`, `avranaparty-arcade`, `nginx`,
  `pi-throttle-check.timer` and `systemd-journald` are all active, with 0 restarts.
- **Listening ports:** 8191 on loopback only, 8097 on loopback only, 8096 unchanged.
- **Routes through the real HTTPS nginx** (`--resolve party.avrana.net:443:127.0.0.1`):
  - `/party/api/state` returns 200 JSON with `Cache-Control: no-store` and `games: ["bluff"]`.
  - `/party/api/origin.json` returns 200 (still answered by nginx).
  - `/party/` returns 200.
  - `/internal/party-session/v0/ended` returns 404: it goes to the games hub, never the Party.
  - `/party/api/internal/...` returns 404.
- **Party Host and follower flow**, with two throwaway cookie jars through the HTTPS path; both left afterwards and the Party ended empty:
  1. Two joins: the first joiner became Party Host.
  2. The follower's start was refused with `not_host` (403).
  3. The Party Host's start went to `bluff/active` in one transition (v4). The follower saw `active` with role `player`.
  4. The follower's ticket came back: `avrana.party-session/v0`, role `player`, `expires_in` 120.
  5. End for everyone returned both to `lobby`.
  6. Both left: the Party is empty.
- **Logs:**
  - Party Core's log records method, path and status only, no tokens. It shows the 403 and 200s above.
  - The games server logged `party_launch` (2 players), `party_end` and `party_release`, and the signed launch and end POSTs returned 200. So the shared key and the signed protocol work in production.
- **Arcade:**
  - `/stats` now carries `sample_age_s`, which read `{video: 0.0, audio: 0.0}`.
  - `video_frames` rose 5659 → 5841 in 3 s (about 60 fps), with `error: null` and the emulator running.
  - An `XIO fatal IO error` at 11:37:14 was the old process shutting down in the restart.
  - The watchdog has not fired: nothing stalled. Its behaviour on a real stall is proven only by unit tests. Watch `NRestarts` and `journalctl -u avranaparty-arcade | grep -E "No encoded video|Fatal"`.
- **Retention:**
  - `/etc/logrotate.d/avrana-telemetry` and `/etc/systemd/journald.conf.d/avrana.conf` are installed.
  - journald's effective config shows `SystemMaxUse=256M`, `SystemKeepFree=1G`, `RuntimeMaxUse=64M` and `MaxFileSec=1week`. The journal is 24.3 MB.
  - The `logrotate -d` dry run parses the rule as: weekly, or earlier past 10 MB, 8 rotations, only `pi-throttle.jsonl`. `baseline.jsonl` is untouched.
  - The daily `logrotate.timer` applies the rule.

## Not verified (open)

- **Phones (Tier 3):**
  - Party Home in Party mode on real iPhone and Android.
  - Automatic follow into BLUFF.
  - The BLUFF briefing on a phone.
  - Gauntlet II picture and controls.
- **The arcade watchdog on a real encoder stall.**

## Restart and rollback verification (11:50 PDT, owner-run script, 0 failures)

Production was first fast-forwarded to `b345b6d` (docs only). The owner then ran one sudo
script, and every check passed:

- **Clean restart:** Party Core is active again, and a restart starts a new, empty Party (memory-only
  by design). The device store is kept (`/var/lib/avrana-party-core`, 0700).
- **Crash:** after `systemctl kill -s KILL`, systemd brought it back by itself (`NRestarts` 0 → 1) and
  `/party/api/state` answered 200 again.
- **Rollback, in runbook order:**
  1. The nginx backup was restored, and `/party/api/state` became the static 404 again, as before the deploy.
  2. `install-party-web.sh --rollback` switched `current` back to `15f6322`, and `/party/` stayed 200.
  3. The games Party-session drop-in was removed, and games became standalone and active. The BLUFF page answered 200.
  4. Party Core was stopped and disabled.
- **Roll forward:** the repo site was installed (live site == repo, `nginx -t` ok, reload), web
  release `20260929T185048Z-b345b6d6f3bf` went in, the games drop-in came back and games restarted,
  and Party Core was enabled. All health checks passed. The arcade was untouched and active throughout.
- **Afterwards (my read-only checks, plus the flow with two test cookie jars through HTTPS):**
  - All services active and enabled; 8191 and 8097 on loopback only.
  - Both checkouts clean.
  - Non-host start refused (`not_host`). The Party Host's start went to `active` in one transition; the follower
    saw it as `player` and got a ticket. End returned both to the lobby, and both left.
  - Arcade at about 60 fps with `sample_age_s` 0.0; `throttled=0x0`; disk at 8%.
