# Runbook: bring up the game origin, `games.avrana.net` (ADR 0013, BROWSER-ORIGINS section 4 step 4, AVR-319)

Status: **PROPOSED procedure, NOT RUN on the appliance** (2026-10-10). Written from source; nothing here is authorized or run.

Running any step on the Pi is an owner action: nothing in CI, in an agent's task or in this document
authorizes it. Real nginx on a Linux runner proves the site file's behavior with stand-in upstreams
(`tests/unit/test_nginx_site.py`); it proves neither the certificate, nor DNS, nor a phone.

Why: a native game page (Checkers, AVR-238) refuses to run on the Party's own origin, so it cannot seat
anyone until `https://games.avrana.net` exists. This is the one reviewed order for that, built from
what the repository now holds. Design and the rollout steps: [BROWSER-ORIGINS](../design/BROWSER-ORIGINS.md)
(sections 3 and 4), [ADR 0013](../adr/0013-party-and-game-browser-origins.md).

## What the repository now provides

| Piece | File | Behavior |
|---|---|---|
| Server block | `avrana-party.nginx` (and its byte-identical copy `arcade/nginx-site`) | third `server`, `server_name games.avrana.net`, HTTPS only, never the default server. Serves the native-game rules of `deploy/games/nginx-native-games.location` (Cookie cleared to the game); `/party*` and `/arcade*` and everything else are nginx's own 404. No LAN Games runtime, no HSTS, no `Service-Worker-Allowed` |
| Bridge framing | same file, `location = /party/bridge.html` on the **Party** host | the bridge page's `frame-ancestors` names `https://games.avrana.net`; every other Party page keeps `'none'`. Party Core sets no such header (it serves no pages), so nginx is the only place |
| DNS | `avrana-captive.conf` | `host-record=games.avrana.net,10.42.0.1` beside the Party's |
| Certificate | `ops/install-party-certificate.sh`, `ops/renew-party-certificate.sh` | the installer notes (or, with `AVRANA_REQUIRE_GAME_NAME=1`, refuses) a certificate without `games.avrana.net`. Renewal needed no change: `lego renew` re-requests every name of the certificate it renews, and now prints them |
| Config check | `python3 -m avrana.contracts.party_config --check` | validates `game_origins` (an object, not a list) |

`provision-game` is unchanged and **still** hands every game `AVRANA_PARTY_ORIGIN=https://party.avrana.net`
(the one bare entry of `origins`; `game_origins` is a different key it does not read). That is correct:
the game origin is the game's own, the Party origin is where its bridge frame lives. Do not change it.

## Safe in any order, and the one that matters

The site file is safe to install on an appliance whose certificate has only `party.avrana.net`: nginx
loads a certificate without checking that it names the host (`nginx -t` passes; the test suite
runs the block with exactly such a certificate), and only a browser refuses `games.avrana.net`. The DNS
record is likewise harmless alone. What sends a phone to the game origin is **`game_origins` in
Party Core's config**, so it comes last, and Party Home does not move anyone before then.

## Before

1. The reviewed commit is merged and checked out clean in `/home/cody/avrana-party` (`git status
   --porcelain` empty; record `git rev-parse HEAD`); the web build of **the same commit** is installed
   (`sudo bash ops/install-party-web.sh /home/cody/avrana-party`, see [party-core-deploy](party-core-deploy.md)).
   The bridge location serves `bridge.html` from that build.
2. [prepare-native-games](prepare-native-games.md) and [provision-game](provision-game.md) for Checkers are done
   (or not yet: this runbook does not need them, but a page only loads once the game runs).
3. **No party is running** (see "Party Core" below: the last step restarts it). The DNS step bounces the AP.
4. Internet from the Pi (ACME) and the Cloudflare token the renewal already uses
   (`/etc/avrana-party/cloudflare.env`: `CF_DNS_API_TOKEN`, `ACME_EMAIL`; root `0600`). Never print or copy it.
   Without the token, issue with `--dns manual` as [party-https](party-https.md) describes, adding
   **two** `_acme-challenge` TXT records (one per name).
5. Back up what you change:
   ```sh
   stamp=$(date -u +%Y%m%dT%H%M%SZ)
   sudo install -d -m 0700 "/root/avrana-game-origin-backups/$stamp"
   sudo cp -a /etc/nginx/sites-available/avrana-party /etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf \
     /etc/avrana-party/party-core.json "/root/avrana-game-origin-backups/$stamp/"
   sudo cp -a /var/lib/avrana-party/lego "/root/avrana-game-origin-backups/$stamp/lego"
   sudo cp -aL /etc/avrana-party/tls/current "/root/avrana-game-origin-backups/$stamp/tls-current"
   cmp /home/cody/avrana-party/avrana-party.nginx /home/cody/avrana-party/arcade/nginx-site
   ```
   The backup holds private keys: never download it.

## Steps

### 1. Certificate with both names

An appliance with the one-name certificate keeps working while you do this; the installer switches
`current` atomically, runs `nginx -t`, reloads, and puts the old link back if either fails. The issuance is a
**new** certificate (one `lego run`; renewal alone never adds a name), written over the same lego file names:

```sh
sudo bash -c 'set -euo pipefail; umask 077; source /etc/avrana-party/cloudflare.env; export CF_DNS_API_TOKEN
  exec /usr/local/bin/lego --accept-tos --email "$ACME_EMAIL" --dns cloudflare \
    --domains party.avrana.net --domains games.avrana.net --path /var/lib/avrana-party/lego run'
sudo env AVRANA_REQUIRE_GAME_NAME=1 bash /home/cody/avrana-party/ops/install-party-certificate.sh \
  /var/lib/avrana-party/lego/certificates/party.avrana.net.crt /var/lib/avrana-party/lego/certificates/party.avrana.net.key
```

Use the checkout's installer, not the older copy in `/usr/local/libexec/avrana-party/` (it does not know the
second name). Check: `openssl x509 -in /etc/avrana-party/tls/current/fullchain.pem -noout -ext subjectAltName`
must list `DNS:party.avrana.net` and `DNS:games.avrana.net`, and `-dates` must be in the future. Optional, so the daily
timer runs the same code: `sudo install -m 0755 /home/cody/avrana-party/ops/{install,renew}-party-certificate.sh
/usr/local/libexec/avrana-party/` (the renewal then logs the names it renewed). Remaining validity is still what
`python3 -m avrana.ops.smoke` and `/party/api/status` check; they do not check names, so use the commands above.

### 2. DNS

`install-captive-dns.py` tests the file, keeps a backup under `backups/` of the checkout, installs it, and
brings the AP profile down and up (it refuses if the profile is not active, and restores the old file on failure).
**Party Wi-Fi drops for several seconds and phones rejoin**, hence no party running.

```sh
cd /home/cody/avrana-party && sudo python3 install-captive-dns.py
dig +short @10.42.0.1 games.avrana.net            # 10.42.0.1 ; and party.avrana.net still 10.42.0.1
```

### 3. Site file

```sh
sudo cp /home/cody/avrana-party/avrana-party.nginx /etc/nginx/sites-available/avrana-party
sudo nginx -t && sudo systemctl reload nginx
cmp /home/cody/avrana-party/avrana-party.nginx /etc/nginx/sites-available/avrana-party
```

This installs the whole site file of the commit, as every site-file install does ([deploy](deploy.md): the site
file and the web build are one unit). Check before going on (from the Pi; `--resolve` keeps the real host name
so the certificate is verified, no `-k`):

```sh
g() { curl --noproxy '*' -s --resolve games.avrana.net:443:127.0.0.1 "$@"; }
g -o /dev/null -w '%{http_code}\n' https://games.avrana.net/party/            # 404
g -o /dev/null -w '%{http_code}\n' https://games.avrana.net/party/api/state   # 404
g -o /dev/null -w '%{http_code}\n' https://games.avrana.net/arcade/           # 404
g -o /dev/null -w '%{http_code}\n' https://games.avrana.net/games/checkers/   # 200 if Checkers runs, else 502
curl --noproxy '*' -sI https://party.avrana.net/party/bridge.html | grep -i content-security-policy   # ends frame-ancestors https://games.avrana.net
curl --noproxy '*' -sI https://party.avrana.net/party/ | grep -i content-security-policy             # still frame-ancestors 'none'
g -I https://games.avrana.net/games/checkers/ | grep -ci -e strict-transport -e service-worker-allowed   # 0
```

If the certificate still has one name, the `games.avrana.net` lines fail verification (as a browser would): do step 1 first.

### 4. `game_origins`, then Party Core

Add one member to `/etc/avrana-party/party-core.json` (`sudoedit`; keep the file's other members as they are):

```json
{
  "game_origins": {"https://games.avrana.net": ["checkers"]}
}
```

It is an object keyed by origin, not a list: `"*"` instead of the list would register the origin for every
game, which BLUFF and the arcade are not ready for. Add a game id to the list when it moves. Check, from the deployed tree:

```sh
cd /opt/avrana-party/current && python3 -m avrana.contracts.party_config --check /etc/avrana-party/party-core.json
```

**Restart, not reload.** `systemctl reload` (a `SIGHUP`) re-reads only the game registry; `game_origins` is read once at
start. A restart forgets the in-memory party (members join again, devices are kept, a running game ends), so first:

```sh
curl -s --noproxy '*' -H 'Host: party.avrana.net' http://127.0.0.1:8191/party/api/status | python3 -c \
  'import json,sys; c=json.load(sys.stdin)["party_core"]; print("members:", c.get("members"), "session:", c.get("session"))'
sudo systemctl restart avrana-party-core && systemctl is-active avrana-party-core
```

Proceed only if `session` is `None`. Party Home now takes a member who opens Checkers to the game origin
(`web/party/lib/game-origins.js`, from Party Core's `GET /party/api/bridge`).

## Verify

From the Pi: `curl --noproxy '*' -s https://party.avrana.net/party/api/bridge` shows `{"origins": {"https://games.avrana.net": ["checkers"]}}`;
the step 3 checks still hold.

From a phone on the Party Wi-Fi (not a laptop on the management LAN): open `https://party.avrana.net/party/`,
join, start Checkers from **Party Home**. The address bar must show `games.avrana.net` with no certificate warning, the
page must seat the player, and the other phone must too. Then run the checks of BROWSER-ORIGINS section 4,
"What step 5 must validate on a real iPhone"; the bridge is not relied on for field testing until they pass.
Record phones, OS versions and results in a dated finding.

Known limits (not blockers of this runbook): a member who is already on a Party-origin game page (BLUFF, the arcade)
when the host starts Checkers is not moved to the game origin automatically (AVR-307); start Checkers from Party Home.
BLUFF, EXPO and the arcade stay on the Party origin.

## Reverse, in this order

1. **`game_origins`**: restore the backed-up `party-core.json` (or delete the member), then restart Party Core with no party running.
   Party Home then opens games same-origin again, and Checkers shows "Open Checkers from Party Home" until the origin is back.
2. **Site file**: `sudo cp /root/avrana-game-origin-backups/<stamp>/avrana-party /etc/nginx/sites-available/avrana-party && sudo nginx -t && sudo systemctl reload nginx`.
3. **DNS** (optional; the record is harmless alone): put back `/root/avrana-game-origin-backups/<stamp>/avrana-captive.conf` as
   `/etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf` and bounce the AP as `install-captive-dns.py` does (or run it from a checkout without the record).
4. **Certificate** (optional; the two-name certificate serves the Party exactly as before): point `current` at the earlier release,
   `ls /etc/avrana-party/tls/releases`, then `cd /etc/avrana-party/tls && sudo ln -s releases/<earlier> .n && sudo mv -Tf .n current && sudo nginx -t && sudo systemctl reload nginx`;
   put `lego` back from the backup copy if you want the one-name lineage again.

## Related

[BROWSER-ORIGINS](../design/BROWSER-ORIGINS.md), [ADR 0013](../adr/0013-party-and-game-browser-origins.md),
[party-https](party-https.md), [prepare-native-games](prepare-native-games.md), [provision-game](provision-game.md),
[party-core-deploy](party-core-deploy.md), [network](network.md), `avrana-party.nginx`, `avrana-captive.conf`,
`ops/install-party-certificate.sh`, `ops/renew-party-certificate.sh`.
