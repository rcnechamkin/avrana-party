# Runbook: switch production games from upstream LAN-Games to the Avrana Party Games fork

Status: **RUN 2026-09-27** by the owner: the fork `9696524` serves production and the shell followed
(`docs/findings/2026-09-27-production-deploy.md`). Kept as the procedure and the rollback
reference. Prepared 2026-09-27. Every production step needs `sudo`, so the owner types it. Order matters: this comes **before** any `/party/` shell newer than `459d4cd`. PR #7's
shell disables LAN launches ("Games update needed") unless `/api/games` advertises
`avrana.lan-launch/v1`, and today's upstream server does not.

**Note 2026-10-02:** the fork this runbook deployed is still the production games runtime
([SYSTEM](../SYSTEM.md)), so the procedure and rollback below remain valid. It is also retiring:
[ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md) keeps LAN Games as
donor/reference code and moves native games to isolated processes. That retirement is not
performed; nothing here authorizes it. "Retire `/home/cody/LAN-Games`" at the end of this runbook
refers to the upstream rollback checkout, not to that architectural retirement.

## Before-state (read on the Pi, 2026-09-27)

| Item | Value |
|---|---|
| Unit | `/etc/systemd/system/avranaparty-games.service`, `User=cody`, `WorkingDirectory=/home/cody/LAN-Games`, `ExecStart=/home/cody/LAN-Games/.venv/bin/python /home/cody/LAN-Games/server.py`, `Restart=on-failure`; no drop-ins |
| Code | `/home/cody/LAN-Games` = BEACNpool upstream `5da1764` (retired), clean; **never edited** |
| API | 29 games + external `wordclash`; no `avranaIntegration` |
| Runtime data | `data/avatars/` and `data/chatmedia/` are empty; no `venue.json`. Nothing to migrate |
| Dependencies | the fork's `requirements.txt` is identical to upstream's, so the existing venv runs the fork |

## Which revision

Games-fork GitHub `main`, at an explicit SHA: **`9696524`** as of 2026-09-27 (games PR #2 merged
the hubnet reconnect fix and lifecycle log lines onto `3a6c472`). Its tree is identical to the tested
`ac7d6c7`; games CI (pytest + static) passed on the PR.

Laptop evidence for `3a6c472` and `fix/reconnect-lineage` (`ac7d6c7`), 2026-09-27:
- pytest 1200 / 1201 pass.
- `hubnet_reconnect_test` passes (it fails against `main`'s `hubnet.js`).
- The cross-repo provider E2E passes 12/12 on both.
- A local server lists all 29 production slugs plus `bluff`; every `/games/<slug>/` returns 200;
  `/api/games` advertises `avrana.lan-launch/v1`.
- BLUFF is served but not granted in Avrana's appliance profile, so `/party/` does not list it.
  (Superseded by AVR-91: `contracts/appliances/avrana-pi4.json` now grants `bluff` at
  `/games/bluff/`, so Party Home lists it and launches `/games/bluff/?avrana=1`.)

## 1. Stage (no sudo, no effect on the live service)

The Pi's GitHub key (`github-avrana`) reads only `avrana-party`, not the private games repo, so the
code travels from the laptop as a bundle:

```bash
# laptop, in the games checkout, after `git fetch`:
git bundle create avrana-party-games.bundle origin/main && scp avrana-party-games.bundle party:
# Pi:
cd /home/cody && git clone ~/avrana-party-games.bundle avrana-party-games && rm ~/avrana-party-games.bundle
cd /home/cody/avrana-party-games && git switch --detach <GAMES_SHA> && git status --short   # empty
```

Smoke-test it on a spare port with the live venv. From Games `11811ff` (2026-10-02, AVR-222) the
server listens on loopback unless `LANGAMES_HOST` says otherwise; an older commit binds every
interface, so stop it right after either way:

```bash
cd /home/cody/avrana-party-games && LANGAMES_PORT=8296 /home/cody/LAN-Games/.venv/bin/python server.py &
curl -s http://127.0.0.1:8296/api/games | grep -o '"avranaIntegration":"[^"]*"'
kill %1
```

## 2. Switch (owner, sudo)

A drop-in keeps the original unit file untouched, so removing it is the rollback.

```bash
sudo install -d /etc/systemd/system/avranaparty-games.service.d
sudo tee /etc/systemd/system/avranaparty-games.service.d/avrana-fork.conf >/dev/null <<'EOF'
[Service]
WorkingDirectory=/home/cody/avrana-party-games
ExecStart=
ExecStart=/home/cody/LAN-Games/.venv/bin/python /home/cody/avrana-party-games/server.py
EOF
sudo systemctl daemon-reload && sudo systemctl restart avranaparty-games
```

## 3. Verify

```bash
systemctl is-active avranaparty-games && systemctl show -p WorkingDirectory avranaparty-games
curl -s http://127.0.0.1:8096/api/games | grep -o '"avranaIntegration":"[^"]*"'      # avrana.lan-launch/v1
curl -s http://127.0.0.1:8096/api/games | grep -o '"slug":"[^"]*"' | wc -l          # 30 (+ wordclash under external)
for s in $(curl -s http://127.0.0.1:8096/api/games | grep -o '"slug":"[^"]*"' | cut -d'"' -f4); do
  c=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8096/games/$s/); [ "$c" = 200 ] || echo "$s $c"; done
journalctl -u avranaparty-games --since '-5 min' --no-pager | grep -iE 'error|traceback' || echo 'no errors'
ss -Hlnt 'sport = :8096'                                                            # 127.0.0.1:8096 only (AVR-272)
systemctl show -p Environment avranaparty-games | grep -o 'LANGAMES_HOST=[^ ]*'      # nothing, or 127.0.0.1
```

**The runtime must not be reachable from the LAN (AVR-272).** Port 8096 is an upstream of nginx
only. As of 2026-10-04 the appliance runs Games `c6d7b52`, which predates the loopback default
and binds `0.0.0.0:8096` (`docs/SYSTEM.md`): any device on the party Wi-Fi or the management LAN
can reach the runtime without going through nginx. Deploying a Games commit at or after `11811ff` closes that,
provided no unit or drop-in on the appliance sets `LANGAMES_HOST=0.0.0.0`. Owner decision
2026-10-04: the appliance changes by an ordinary deployment of current Games `main`, performed by
the owner, not by waiting for the service-users migration. The phase-1 unit in the Games
repository additionally states `LANGAMES_HOST=127.0.0.1` and an `IPAddressDeny=any` /
`IPAddressAllow=localhost` filter; those apply only once that unit is installed by the migration
([service-users-migration](service-users-migration.md)). The topology check
below asserts the listener from the appliance; the owner confirms it from outside:

- from a phone on the party Wi-Fi, `http://10.42.0.1:8096/` does not load;
- from a machine on the management LAN, `curl -m 3 http://<eth0 address>:8096/` fails to connect;
- BLUFF and EXPO still open from `/party/` on port 80 and on 443.

Then run `tools/avrana-topology-check` (read-only). "HTTP root at http://10.42.0.1/ -> 200" must
still pass, and so must "games runtime (:8096) listens on loopback only" and the two "does not
answer on" lines. On one phone, open BLUFF from `/party/` (the old hub page is no longer served, AVR-259). Only after that, update
`docs/SYSTEM.md` (port 8096 row) in a commit.

## Rollback (owner, sudo; about 10 s)

```bash
sudo rm /etc/systemd/system/avranaparty-games.service.d/avrana-fork.conf
sudo systemctl daemon-reload && sudo systemctl restart avranaparty-games
curl -s http://127.0.0.1:8096/api/games | grep -c avranaIntegration                  # 0: upstream again
```

`/home/cody/LAN-Games` was never changed, so this returns exactly to `5da1764`. Phones that loaded
the fork's root service worker pick up upstream's on their next visit.

## 4. Afterwards, not before: the `/party/` shell

Only once step 3 shows `avrana.lan-launch/v1`:
1. Fast-forward `/home/cody/avrana-party` to the reviewed `main` commit (`git pull --ff-only`).
2. `sudo bash ops/install-party-web.sh /home/cody/avrana-party`, then the checks in
   `party-https.md`.

Rollback: `sudo bash ops/install-party-web.sh --rollback` (release `459d4cd` is kept). The arcade
reads the production checkout too, so restarting `avranaparty-arcade` is a separate owner call.

Later (not needed for this switch): give the fork its own venv, and retire `/home/cody/LAN-Games`
once the fork has run cleanly through a real party.
