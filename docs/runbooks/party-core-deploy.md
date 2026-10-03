# Runbook: deploy Party Core v0 to the appliance (AVR-51)

Status: **RUN 2026-09-29** (production `6bd5af4`, games `eeedb19`; `docs/findings/2026-09-29-party-core-deploy.md`). The owner ran the sudo steps
as one script; everything verified server-side. Restart, crash recovery and the full rollback/roll-forward were
exercised the same day with 0 failures. Phone checks remain open.

## What this deploys

Party Core v0 (`avrana/party/`, ADR 0006) behind `https://party.avrana.net/party/api/`, wired to
the games server so BLUFF runs as a Party session. Once it's live, Party Home shows the authoritative
party instead of catalog-only mode. That happens only if the deployed revision contains the Party
Home integration (AVR-20/AVR-127).

| Piece | Where | Source |
|---|---|---|
| Party Core service `avrana-party-core`, loopback `127.0.0.1:8191`, user `cody` | `/etc/systemd/system/avrana-party-core.service` | `deploy/party-core/avrana-party-core.service` |
| Its config (hosts, origins, games; paths only, no secrets). Per game it names only `url`, `key_file` and `timeout`; player counts, late join and pregame come from `contracts/games/<id>.json` in the checkout the service runs from (AVR-229). Check an edited file with `python3 -m avrana.contracts.party_config --check /etc/avrana-party/party-core.json` before restarting: the service refuses to start on a disagreement | `/etc/avrana-party/party-core.json` (root, 0644) | `deploy/party-core/party-core.example.json` |
| Device store (hashed tokens) | `/var/lib/avrana-party-core/devices.json` (systemd `StateDirectory`, 0700 `cody`) | created by the service |
| Per-game session key (BLUFF) | `/etc/avrana-party/game-keys/bluff.key` (0600 `cody`, dir 0700) | `ops/provision-party-game-key.sh bluff` |
| nginx `location /party/api/` on the 443 server only | both tracked site files and `/etc/nginx/sites-available/avrana-party` | `deploy/party-core/nginx-party-api.location` |
| Games server party-session drop-in (`AVRANA_PARTY_KEYS`, `AVRANA_PARTY_URL=http://127.0.0.1:8191`) | `/etc/systemd/system/avranaparty-games.service.d/avrana-party-session.conf` | games repo `deploy/avrana-party-session.conf` |
| Party Home with the Party API client | `/var/www/avrana-party/web/current` | `ops/install-party-web.sh` |

Not in scope: party persistence across reboot (the party is memory-only; a restart starts a new
party, device identities survive), BLUFF rules changes, `.avrgame`.

## Before the deploy (development side, no Pi changes)

1. **Merged and reviewed:**
   - avrana-party `main` contains Party Core, the Party Home integration (AVR-20/127) and this package.
   - games `main` contains the party side (AVR-22/23/24) and, for AVR-27, AVR-25/AVR-90.
   - Write both SHAs down: they are the **reviewed revisions** this deploy is about.
2. **nginx:** `deploy/party-core/nginx-party-api.location` is committed verbatim in **both**
   `avrana-party.nginx` and `arcade/nginx-site`, right after the
   `location = /party/api/origin.json` block. The two files stay identical (`cmp`; CI checks it).
   `tests/unit/test_nginx_site.py` runs CI's real nginx with the real party service behind that
   block. From that merge until step 6 below, `main`'s site differs from the live site. That is
   expected: the live site is installed only in step 6.
3. **CI green** on both repos.

## Deploy (owner, on the Pi, in this order)

The order keeps every intermediate state safe:
- Until nginx forwards `/party/api/`, phones see today's catalog-mode Party Home.
- Until the games drop-in is in, BLUFF runs standalone.

```bash
# 0. Record what is live now (for the matrix and for rollback)
git -C /home/cody/avrana-party log -1 --format='%h %s'
git -C /home/cody/avrana-party-games log -1 --format='%h %s'
readlink -f /var/www/avrana-party/web/current

# 1. Code: fast-forward both production checkouts to the reviewed revisions
cd /home/cody/avrana-party && git pull --ff-only          # expect <reviewed avrana-party sha>
cd /home/cody/avrana-party-games && git fetch && git checkout --detach <reviewed games sha>

# 2. Key (never printed; refuses to overwrite)
sudo bash /home/cody/avrana-party/ops/provision-party-game-key.sh bluff

# 3. Config, then the service (loopback only)
#    Since AVR-134 the example config also lists arcade-gauntlet2 (on 127.0.0.1:8098). Install
#    it only after docs/runbooks/arcade-party-provider.md steps 1-2, or drop that entry.
sudo install -m 0644 /home/cody/avrana-party/deploy/party-core/party-core.example.json /etc/avrana-party/party-core.json
sudo install -m 0644 /home/cody/avrana-party/deploy/party-core/avrana-party-core.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now avrana-party-core
systemctl is-active avrana-party-core
ss -ltn | grep ':8191 '                                   # must be 127.0.0.1:8191 only
curl -s -H 'Host: party.avrana.net' http://127.0.0.1:8191/party/api/state   # {"party": ...,"me": null,...}

# 4. Games server: party sessions on (the arcade is untouched)
sudo install -D -m 0644 /home/cody/avrana-party-games/deploy/avrana-party-session.conf \
  /etc/systemd/system/avranaparty-games.service.d/avrana-party-session.conf
sudo systemctl daemon-reload && sudo systemctl restart avranaparty-games
systemctl is-active avranaparty-games
journalctl -u avranaparty-games -n 30 --no-pager         # no "party session key ... unusable"

# 5. Party Home (static; atomic switch; keeps 5 releases)
sudo bash /home/cody/avrana-party/ops/install-party-web.sh /home/cody/avrana-party

# 6. nginx: back up, install the reviewed site, test, reload
sudo cp -a /etc/nginx/sites-available/avrana-party /root/avrana-party-site.$(date -u +%Y%m%dT%H%M%SZ)
cmp /home/cody/avrana-party/avrana-party.nginx /home/cody/avrana-party/arcade/nginx-site
sudo cp /home/cody/avrana-party/avrana-party.nginx /etc/nginx/sites-available/avrana-party
sudo nginx -t && sudo systemctl reload nginx
cmp /home/cody/avrana-party/avrana-party.nginx /etc/nginx/sites-available/avrana-party
```

## Verify

**On the Pi:**
- `curl -sk --resolve party.avrana.net:443:127.0.0.1 https://party.avrana.net/party/api/state`
  returns the party JSON with `Cache-Control: no-store`.
- `https://party.avrana.net/internal/party-session/v0/ended` must **not** reach the party: nginx
  sends it to the games hub (`location /`). The party answers only on loopback, without proxy headers.
- `sudo systemctl restart avrana-party-core`: the service comes back within about 3 s
  (`Restart=on-failure`). A restart starts a new party; phones re-Join, keeping their devices.

**On phones on the Party Wi-Fi.** This is Tier 3; management-LAN success is not Party-WLAN evidence.
1. Two phones open `https://party.avrana.net/party/` and Join.
2. The first phone is the Party Host.
3. The Party Host picks BLUFF. The other phone follows into BLUFF without choosing it.
4. Both get their hands.
5. Reload one phone: it keeps its seat and hand.
6. End the game for everyone: both phones see the end, and Back to Party returns them to Party Home.
7. Record the result in `docs/findings/` and the revisions in `docs/SYSTEM.md` (the deployment matrix).

## Rollback (reverse order; each step is independent)

```bash
# nginx: restore the backup (phones fall back to catalog-mode Party Home; /party/api/ -> 404)
sudo cp -a /root/avrana-party-site.<stamp> /etc/nginx/sites-available/avrana-party
sudo nginx -t && sudo systemctl reload nginx
# Party Home: previous release
sudo bash /home/cody/avrana-party/ops/install-party-web.sh --rollback
# Games: party sessions off (BLUFF standalone again)
sudo rm /etc/systemd/system/avranaparty-games.service.d/avrana-party-session.conf
sudo systemctl daemon-reload && sudo systemctl restart avranaparty-games
# Party Core off (config and key can stay; they are inert without the service)
sudo systemctl disable --now avrana-party-core
```

What each rollback step is backed by:
- **nginx:** without the block, `/party/api/*` is the static 404 that
  `tests/unit/test_nginx_site.py` pins, which is today's live behaviour.
- **Party Home:** its no-API fallback is tested offline, in the AVR-20/127 tests.
- **On the Pi:** the rollback itself is not yet exercised there (Tier 3, owner).

## Security notes

- The key file is the only secret. The script never prints it, and it never appears in the
  config, unit, logs or the repository.
- The device token lives only in the `HttpOnly; Secure; SameSite=Lax; Path=/party/` cookie.
- The service refuses:
  - a Host header other than `party.avrana.net`;
  - a POST whose Origin is not `https://party.avrana.net`;
  - bodies over 8 KiB;
  - any `/internal/` request that carries proxy headers.
- nginx forwards only `/party/api/`. It adds no HSTS and no `Service-Worker-Allowed`.
