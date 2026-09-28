# 2026-09-27 — production caught up: games fork, `/party/` shell `7581baa`, arcade AP fix

Status: **LIVE** (deployed by the owner, 2026-09-27 PDT). Verified read-only by Claude Code over
`ssh party` and over the Party WLAN (`curl https://party.avrana.net/…` from the laptop), ~21:30 PDT.
These are server-side and HTTP checks: **no real phone** has launched a game from Party Home on
this release yet. Supersedes the "nothing deployed" state in `2026-09-27-m0-git-baseline.md` and
the production rows of `2026-09-27-party-bluff-boundary.md`.

Linear: AVR-8 (games fork) and AVR-9 (shell) Done.

## What runs now

| Item | Before | Now | Evidence |
|---|---|---|---|
| Games service `avranaparty-games` (:8096) | upstream LAN-Games `5da1764` from `/home/cody/LAN-Games` | games fork **`9696524`** from `/home/cody/avrana-party-games` (clean), via the drop-in `/etc/systemd/system/avranaparty-games.service.d/avrana-fork.conf`; the existing venv; active since 20:50:53 | `systemctl cat`; `git log`/`status` on the Pi |
| `/api/games` | 29 games, no `avranaIntegration` | 30 games including BLUFF; `avranaIntegration: avrana.lan-launch/v1` | curl over the Party WLAN |
| Production checkout `/home/cody/avrana-party` | `459d4cd` | **`7581baa`** (`main`) | `git log` on the Pi |
| `/party/` shell release | `20260926T082511Z-459d4cd19c3a` | **`20260928T035340Z-7581baa24342`** (`version.json` commit `7581baa`, built 03:53:41Z) | `readlink …/web/current` |
| nginx | — | `/etc/nginx/sites-available/avrana-party` is byte-identical to the checkout's `avrana-party.nginx` | `cmp` on the Pi |
| Arcade `avranaparty-arcade` (:8097) | running since 2026-09-26 00:11, old code loaded | restarted by the owner 21:26:38, 0 restarts; `stream.py` runs from the `7581baa` checkout, so the AP fix (PR #8, `9793a51`) is live | `systemctl show`, `journalctl`, `/proc/<pid>/cwd` |

HTTP 200 over the Party WLAN: `/party/`, `/api/games`, `/games/bluff/?avrana=1`,
`/games/poker/?avrana=1`, `/shared/avrana-integration.js`, `/arcade/`.

**AP fix check:** the deployed `ap_addresses()` (extracted from the production `arcade/stream.py`
and run on the Pi) returns `10.42.0.1` (wlan0). The old code read `wlan1`, which no longer exists,
and returned nothing, so `/stats` labelled every phone's path `other`. The fix is diagnostics only.
A real peer's `avrana` label has not been observed yet.

## Rollback (still available)

- Games: remove the drop-in and restart (`docs/runbooks/games-fork-deploy.md`).
  `/home/cody/LAN-Games` is untouched at `5da1764` (clean).
- Shell: `sudo bash ops/install-party-web.sh --rollback`; release `459d4cd` is kept.

## Still not deployed

- Party Core v0 / the session protocol (ADR 0006): no Party service runs, and there is no
  `location /party/api/`. In the browser, `POST /party/api/session/ticket` returns 404, and
  integrated games fall back to today's hello.
- BLUFF's party-session admission (AVR-22, games PR #3): in review, not merged.

## Laptop testing note

With the laptop on both Ethernet and the Party Wi-Fi, `curl https://party.avrana.net/` reaches
`10.42.0.1` over the WLAN. `nslookup` queries the Ethernet-side resolver directly, so it does not
show the Party DNS answer; use curl or a browser to check the WLAN path.
