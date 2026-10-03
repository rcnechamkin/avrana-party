# Party HTTPS deployment and recovery

Status: **LIVE on the Pi from `fix/party-https` as of 2026-09-25; a Party Wi-Fi
phone check passed, while laptop Wi-Fi validation and automatic renewal remain
open.** This runbook records the baseline and the narrow deployment path.
GitHub `main` remains unchanged until the branch is fully validated and reviewed.

**Note 2026-10-02:** this runbook deploys and verifies Full Mode (trusted HTTPS), and its
HTTPS-only `/party/` is the deployed behavior. [ADR 0012](../adr/0012-limited-mode-party-survives-https-loss.md)
accepts a Limited Mode in which the Party stays usable when trusted HTTPS is unavailable; it is
not implemented, and no step below provides it. "Recovery" in this runbook means restoring the
certificate, not Limited Mode. No HSTS remains a hard rule. References to LAN Games describe the
games runtime behind nginx (upstream at this runbook's baseline, the fork since 2026-09-27),
which is still deployed and is retiring as a runtime
([ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md)).

## Baseline and intended behavior

- The Pi is `RaspberryPi`, with `eth0` at `10.0.0.142/24` for management and
  `wlan0` at `10.42.0.1/24` for Party clients. No inbound WAN access is needed.
- NetworkManager's shared dnsmasq listens on `10.42.0.1:53` and loads
  `/etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf`.
- nginx currently serves HTTP on port 80. `party.local` remains an Avahi name.
- Apple captive probes at `/hotspot-detect.html` return literal `Success` on HTTP,
  so iOS joins without a captive popup. Android, Windows and Firefox intercepted
  probe hosts currently receive HTTP 404. Keep these results unchanged. The old
  `portal/index.html` is not served.
- `party.avrana.net` is the real, owned Full Mode hostname. Cloudflare is
  authoritative for `avrana.net`; public DNS has no A record for this hostname.
  The Party dnsmasq adds an exact local A record pointing it to `10.42.0.1`.
  It does not replace captive host overrides or Avahi `party.local`.
- The new nginx 443 block serves the existing `/` and `/arcade/` upstreams with
  their WebSocket headers. HTTP port 80 remains in place without a global
  redirect. Guests open `https://party.avrana.net/` in a normal browser after
  joining Wi-Fi. The captive mini-browser is not the game client.
- At baseline the LAN Games upstream at `127.0.0.1:8096` was active; the arcade
  service at `127.0.0.1:8097` was inactive, so `/arcade/` returned 502 before
  this change. Do not claim arcade regression or success without starting and
  validating that service separately.

## Trust and key custody

Use Let's Encrypt ACME **DNS-01** for the single hostname. `lego` is the ACME
client. The Party generates and retains its own account and certificate keys;
never transfer private keys, ACME account state or a Cloudflare token to the
laptop, GitHub, `avrana` or any other host. A Companion courier could later
transport a CSR and the returned certificate while the key remains on the Pi.

For manual issuance without a Cloudflare API token, run `lego --dns manual` on
the Pi and add the exact `_acme-challenge.party.avrana.net` TXT record that it
prints in Cloudflare. Wait for `dig TXT` against both Cloudflare authoritative
nameservers to return the same value, then continue lego. **Do not use HTTP-01.**
Manual DNS cannot renew unattended.

For automatic renewal, create a Cloudflare API token limited to the `avrana.net`
zone with DNS edit and zone read. Place `CF_DNS_API_TOKEN` and `ACME_EMAIL` only
in `/etc/avrana-party/cloudflare.env` on the Pi, root-owned mode `0600`. The
token is a necessary Pi-only renewal secret. `ops/renew-party-certificate.sh`
runs lego DNS-01 with that token. Do not enable its timer until the token,
state directory and first live certificate are verified.

The lego account and certificate state belongs at `/var/lib/avrana-party/lego`
with root-only access. nginx reads the active pair through
`/etc/avrana-party/tls/current/{fullchain,privkey}.pem`. The install script
checks hostname, validity, chain and key pairing, copies into a new root-only
release directory, atomically switches `current`, runs `nginx -t`, and reloads
nginx. On validation or reload failure it restores the previous symlink.
Released certificate directories remain available for rollback.

The systemd `avrana-party-certificate.timer` checks daily with up to two hours
of jitter. Lego renews when 30 days or fewer remain, then the install script
validates and reloads nginx. If DNS, Cloudflare or ACME is unavailable, renewal
fails without removing the currently installed certificate. Monitor timer
failures and remaining validity; an expired certificate ends trusted Full Mode.

## Pre-deployment and backup

Do not use the old `install-captive-dns.py`: it can reactivate the AP and uses
historical assumptions. Keep `eth0` management active. Record `git rev-parse
HEAD`, `ip -br addr`, `ss -lntup`, `nginx -T`, `dig @10.42.0.1` for the captive
hosts, and the HTTP probe status/body before touching live files. Confirm the
production checkout is clean. Do not deploy the nginx 443 block until a valid
certificate exists on the Pi.

As root on the Pi, save the affected live files into a dated root-only backup:

```sh
stamp=$(date -u +%Y%m%dT%H%M%SZ)
sudo install -d -m 0700 "/root/avrana-party-https-backups/$stamp"
sudo cp -a /etc/nginx/sites-available/avrana-party \
  /etc/NetworkManager/dnsmasq-shared.d/avrana-captive.conf \
  "/root/avrana-party-https-backups/$stamp/"
sudo cp -a /etc/avrana-party/tls "/root/avrana-party-https-backups/$stamp/" # if present
```

The backup contains private key material once HTTPS is live; never download it.
Record the backup directory in the deployment notes. Validate the repository
nginx files are byte-identical (`cmp avrana-party.nginx arcade/nginx-site`).
Validate the candidate site with `nginx -t` on the Pi after the certificate is
installed, and dnsmasq with `dnsmasq --test --conf-file=<candidate>` before
replacing its drop-in. Check both files against the repository before reload.

Installing the dnsmasq drop-in may require reactivation of the NetworkManager
AP connection, briefly disconnecting Party clients. Have a client rejoin and
verify DHCP, probe DNS and the new exact A record before proceeding. Do not
touch the upstream `eth0` connection. Install nginx only after DNS, certificate
and backups are ready; use `nginx -t` before `systemctl reload nginx`.

For this branch's validation deployment, transfer the committed branch to the
clean Pi checkout without publishing it first, check out that exact commit,
then run `sudo bash ops/deploy-party-https.sh /home/cody/avrana-party
/home/cody/avrana-lab/https/lego-state` on the Pi. The script makes its own
root-only backup, moves ACME state into `/var/lib/avrana-party/lego`, installs
the certificate, updates the local DNS drop-in with a bounded AP reactivation,
validates nginx and reloads it. Its error trap restores prior nginx, DNS and
active certificate configuration. Inspect its printed backup path. The
production checkout should match the tested repository config byte for byte.

After successful live validation and a scoped Cloudflare token is available,
create the root-only credential file, install the two systemd units from
`ops/`, run the renewal service once, check its result, then enable the timer.
The initial manual certificate remains valid without a token, but automatic
renewal is blocked until that step. Remove the temporary DNS challenge TXT
record after issuance; renewal with the API creates its own challenge records.

## Validation from a Party-connected laptop

Use the laptop's Party Wi-Fi DNS, not a hosts-file override, for the final DNS
check. Bypass any configured HTTP proxy during direct Pi checks.

```sh
nslookup party.avrana.net 10.42.0.1
curl --noproxy '*' -Iv https://party.avrana.net/
curl --noproxy '*' -fsS https://party.avrana.net/ >/dev/null
curl --noproxy '*' -i -H 'Host: captive.apple.com' \
  http://10.42.0.1/hotspot-detect.html
openssl s_client -connect 10.42.0.1:443 -servername party.avrana.net \
  -verify_hostname party.avrana.net -verify_return_error </dev/null
```

`curl` must succeed with ordinary certificate verification, **without `-k`**.
Inspect `openssl x509 -in /etc/avrana-party/tls/current/fullchain.pem -noout
-dates -subject -issuer` on the Pi. In a regular browser, check no warning,
`window.isSecureContext`, `navigator.serviceWorker`, `crypto.subtle`,
`navigator.wakeLock`, `navigator.mediaDevices` and `navigator.getGamepads`.
Presence of an API does not prove permission or hardware support. Validate
HTTPS WebSocket upgrades and the active service routes; validate arcade when
its service is running. Rejoin Party Wi-Fi on a phone to confirm the original
HTTP captive behavior. Check `journalctl -u nginx`, NetworkManager/dnsmasq
logs, and certificate timer status after deployment.

`node ops/check-browser-origin.mjs` runs headless Chromium against the real
hostname using system DNS. For a management-LAN check before a Party Wi-Fi
client is available, pass the Pi's management address as its argument; the
script keeps the real hostname and TLS verification but bypasses local DNS.
Do not treat that override as a Party Wi-Fi validation.

### Deployment evidence (2026-09-25)

- Pi production checkout and live nginx/dnsmasq files matched the branch
  candidate after deployment. nginx listens on 80 and 443; LAN Games,
  NetworkManager, nginx and Avahi remained active.
- The Let's Encrypt `YE1` certificate for `party.avrana.net` is valid from
  `2026-09-26 00:11:17 UTC` until `2026-12-25 00:11:16 UTC`. Pi curl verified
  the chain and hostname without `-k`; laptop headless Chromium also loaded
  the origin without bypassing certificate checks.
- Local dnsmasq answered `party.avrana.net` and existing captive hosts with
  `10.42.0.1`; Avahi still answered `party.local` with `10.42.0.1`.
- HTTP Apple probe remained 200; Android, Windows and Firefox remained 404;
  `party.local` root remained 200. HTTPS hub, `/games/brickade/`, shared CSS
  and manifest returned 200. `/chat/ws` upgraded to 101 over WSS.
- Laptop Chromium over the management route reported `isSecureContext`,
  `serviceWorker`, `crypto.subtle`, `wakeLock`, `mediaDevices`, and
  `getGamepads` present, with a WSS connection opened. This records API
  presence, not permissions or device support.
- Arcade was inactive before and after; `/arcade/` remains 502. No arcade
  restart or stream validation was attempted.
- The owner confirmed a phone joined Avrana Party Wi-Fi normally and loaded
  the normal UI at `https://party.avrana.net/` without a certificate warning.
  The laptop could not join Party Wi-Fi during this session, so its direct
  Party-network DNS/browser check remains pending. The Cloudflare DNS API
  token was unavailable, so the renewal timer is staged but not enabled.
  The initial certificate was issued by manual DNS-01.

## Rollback

If a live check fails, restore the backed-up nginx and dnsmasq files and the
previous `tls/current` symlink, run `nginx -t`, then reload nginx. Reapply the
previous dnsmasq drop-in with the same controlled AP reactivation needed for
deployment. Recheck HTTP Apple, Android, Windows and Firefox probe behavior,
Party Wi-Fi join, `party.local`, LAN Games, and the existing service status.
Keep the new certificate and ACME state on the Pi for diagnosis unless they
caused the failure; do not copy keys off the Pi.

## Full Mode web shell (`/party/`): deploy, check, roll back

Status: **LIVE** — release `459d4cd` (PR #5) under `/var/www/avrana-party/web/releases/`, read on the
Pi 2026-09-27; later `main` commits are not deployed until the owner runs this again (ADR 0004,
`docs/design/FULL-MODE.md`). It adds three `location` blocks to the **443 server only**:
`= /party`, `= /party/api/origin.json` and `/party/`. The port 80 server is byte-for-byte
unchanged, which `tests/unit/test_nginx_site.py` checks against a real nginx. The files are static;
there is no service, port or unit.

Owner steps on the Pi, one time. Every step needs `sudo`, so the owner types it.

1. Put the reviewed commit in a clean checkout: the production checkout after the merge, or a lab
   checkout for a pre-merge test (`git status --porcelain` must be empty). Record `git rev-parse HEAD`.
2. Back up the live site as in "Pre-deployment and backup", then check the copies:
   `cmp avrana-party.nginx arcade/nginx-site`.
3. Install the static files. This builds a release, stamps it and switches the atomic `current`:
   `sudo bash ops/install-party-web.sh <checkout>`.
4. Install the site and reload only after a successful test:
   `sudo cp <checkout>/avrana-party.nginx /etc/nginx/sites-available/avrana-party && sudo nginx -t && sudo systemctl reload nginx`.
   Then `cmp` the live file against the repository.
5. Checks from a Party-connected machine, without `-k` and without a proxy:
   ```sh
   curl --noproxy '*' -sI https://party.avrana.net/party/ | grep -iE '^(HTTP|cache-control|content-security-policy)'
   curl --noproxy '*' -s  https://party.avrana.net/party/api/origin.json      # "serverAddr":"10.42.0.1"
   curl --noproxy '*' -s  https://party.avrana.net/party/version.json         # the commit you installed
   curl --noproxy '*' -i -H 'Host: captive.apple.com' http://10.42.0.1/hotspot-detect.html   # still Success
   ```
6. Phone checks: the checklist below.

Later releases need only step 3. To roll back the files to the previous release:
`sudo bash ops/install-party-web.sh --rollback`. To remove offline copies from phones:
`sudo bash ops/install-party-web.sh --kill <checkout>`. That sets `version.json`
`serviceWorker:false` and installs a self-destruct worker; open phones clean up on their next visit.
To remove the feature, restore the backed-up site, run `nginx -t` and reload. Releases live under
`/var/www/avrana-party/web/releases/`, and the newest five are kept.

**When the arcade changes go live.** This does not depend on the shell deploy above.
- `arcade/stream.py` reads `index.html` from the production checkout on every request. So once
  `/home/cody/avrana-party` is fast-forwarded to a commit with this branch, the arcade *phone page*
  changes at once if the arcade service is running: keep-awake, "full" versus "lost" messages,
  quiet reconnect, and the "Leave" label.
- The refactored `stream.py` (provider adapters, `/stats` `providers` block) runs after the next
  start of the service, and that includes a crash restart or a reboot.
- The arcade was stopped at the 2026-09-25 deploy. Treat the fast-forward itself as the arcade
  deploy step, and run the arcade checks in the phone checklist (and `npm test` from the Party
  Wi-Fi) the next time it runs.
- Keep-awake needs the shell, because the page loads `/party/lib/keep-awake.js`. Without the shell
  it is silently off.

### Phone checklist (Tier 3; record the results in `docs/findings/`)

1. On Party Wi-Fi, open `https://party.avrana.net/party/`. Expect no certificate warning, "Connected
   to the party · 🔒 Secure", and the Gauntlet II and Party games cards.
2. Open "This phone". Record every line on both an iPhone (Safari) and an Android phone (Chrome).
3. On `/party/diag/`, tap "Copy report" and paste the `avrana.diagnostics/v0` JSON into a finding.
   This records the first real `video.h264`, `wake_lock` and `gamepad` observations.
4. Tap "Test keep-awake" on the diagnostics page. Expect "on", and the screen should not dim for
   longer than the auto-lock time. Then release.
5. Reload the page twice (the offline copy installs), then switch the phone to another Wi-Fi or
   mobile data and reload. Expect "Can’t reach the party" (not a browser error). Rejoin Avrana
   Party: the page should recover by itself.
6. If the arcade runs on the new code: Play, lock the phone for 20 s, unlock. Expect
   "Reconnecting…" and then "Player N connected", with the screen staying on while playing. With
   two controllers in use, a third phone should read "Both controllers are in use".
7. Confirm the captive behaviour is unchanged: forget and rejoin the Wi-Fi on the iPhone, and expect
   no popup.
