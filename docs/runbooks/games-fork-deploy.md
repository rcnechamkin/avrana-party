# Runbook: switch production games from upstream LAN-Games to the Avrana Party Games fork

Status: **READY, not run** (prepared 2026-09-27). Every production step needs `sudo`, so the owner
types it. Order matters: this comes **before** any `/party/` shell newer than `459d4cd`. PR #7's
shell disables LAN launches ("Games update needed") unless `/api/games` advertises
`avrana.lan-launch/v1`, and today's upstream server does not.

## Before-state (read on the Pi, 2026-09-27)

| Item | Value |
|---|---|
| Unit | `/etc/systemd/system/avranaparty-games.service`, `User=cody`, `WorkingDirectory=/home/cody/LAN-Games`, `ExecStart=/home/cody/LAN-Games/.venv/bin/python /home/cody/LAN-Games/server.py`, `Restart=on-failure`; no drop-ins |
| Code | `/home/cody/LAN-Games` = BEACNpool upstream `5da1764` (retired), clean; **never edited** |
| API | 29 games + external `wordclash`; no `avranaIntegration` |
| Runtime data | `data/avatars/` and `data/chatmedia/` are empty; no `venue.json`. Nothing to migrate |
| Dependencies | the fork's `requirements.txt` is identical to upstream's, so the existing venv runs the fork |

## Which revision

Games-fork GitHub `main`, at an explicit SHA. Prefer the `main` that includes
`fix/reconnect-lineage` (the hubnet reconnect fix and lifecycle log lines). If that PR is not merged
yet, `3a6c472` is acceptable: it is no worse than production on reconnect, because upstream has
the same bug.

Laptop evidence for `3a6c472` and `fix/reconnect-lineage` (`ac7d6c7`), 2026-09-27:
- pytest 1200 / 1201 pass.
- `hubnet_reconnect_test` passes (it fails against `main`'s `hubnet.js`).
- The cross-repo provider E2E passes 12/12 on both.
- A local server lists all 29 production slugs plus `bluff`; every `/games/<slug>/` returns 200;
  `/api/games` advertises `avrana.lan-launch/v1`.
- BLUFF is served but not granted in Avrana's appliance profile, so `/party/` does not list it.

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

Smoke-test it on a spare port with the live venv (it binds all interfaces, so stop it right after):

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
```

Then run `tools/avrana-topology-check` (read-only). "HTTP hub at http://10.42.0.1/ -> 200" must
still pass. On one phone, open a game from the old hub and from `/party/`. Only after that, update
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
