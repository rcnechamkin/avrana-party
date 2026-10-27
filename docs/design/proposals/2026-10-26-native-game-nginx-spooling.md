# Native-game nginx location: no spooling to the SD card, slow-reader limits (AVR-508, D3a)

- **Status:** approval packet, 2026-10-26. **Nothing is applied.** The site files and
  `deploy/games/nginx-native-games.location` are unchanged by the pull request that adds this page. Owner decision
  D3a (2026-10-15) approved controlled engineering work; applying it to the Pi needs a separate go-ahead after the
  measurements below.
- **Reads with:** [APPLIANCE-CONTENT-DELIVERY](../APPLIANCE-CONTENT-DELIVERY.md) §7 (D3a, D3b), AVR-501 (content packs,
  Games #81, experimental and unmerged), AVR-139 (the phone sampler), AVR-271 (site file and web build are one unit).

## 1. Today

The native-game location (`deploy/games/nginx-native-games.location`, verbatim in `avrana-party.nginx`,
`arcade/nginx-site` and `deploy/hosted/avrana-party.hosted.nginx`) proxies `/games/<id>/` to the game's Unix socket
with nginx's defaults: `proxy_buffering on`, `proxy_buffers 8 4k|8k`, `proxy_max_temp_file_size 1024m`,
`send_timeout 60s`, no connection limit.

When a phone reads more slowly than the game writes, nginx fills its memory buffers and then **spools the rest of
the answer to `/var/lib/nginx/proxy` on the SD card**. Today's game answers are small, so this is rare. With
content packs (AVR-501) it becomes the normal case: 8 MiB parts, several phones at once. The kit there streams at
most 8 files at once (`MAX_STREAMS`, a 503 with `Retry-After` beyond that; Games #81 only).

## 2. The change (exact diff)

Inside the native-game location, in every file that carries it, plus one zone at the top of each site file
(outside any `server`, which is `http` context because the site file is included there):

```diff
+# Native games: concurrent requests per phone (AVR-508). One zone for the whole site.
+limit_conn_zone $binary_remote_addr zone=avrana_games_client:1m;
+
 server {
 ...
     location ~ "^/games/(?<native_game>[a-z][a-z0-9_-]{0,39})/" {
 ...
         proxy_set_header Cookie "";
         proxy_read_timeout 3600;
+        # Never spool a game's answer to the SD card (AVR-508, D3a): nginx keeps its memory buffers and,
+        # when they are full, waits for the phone instead of writing a temporary file.
+        proxy_max_temp_file_size 0;
+        # A phone that stops reading for 30 s is let go (the default is 60 s); a game's socket slot is
+        # not held by a phone that has walked away.
+        send_timeout 30s;
+        # At most 24 requests at once from one phone address (HTTP/2 counts each stream). A page load
+        # opens many; a WebSocket holds one for its life. Beyond the limit: 503, which the kit's
+        # Retry-After handling already treats as "try again".
+        limit_conn avrana_games_client 24;
+        limit_conn_status 503;
     }
```

`nginx -t` passes with exactly these directives (nginx 1.26.3 on the staging VM, a scratch config with the real
location's `proxy_pass` to a Unix socket). The Pi's nginx must be checked the same way before applying: every
directive here has existed since nginx 1.1.

### Why `proxy_max_temp_file_size 0` and not the alternatives

| Option | SD writes | Game stream slot held by a slow phone | Small answers | Choice |
|---|---|---|---|---|
| `proxy_max_temp_file_size 0` | none | after nginx's memory buffers fill | unchanged (buffered) | **proposed** |
| `proxy_buffering off` | none | from the first byte | each write goes straight out; more syscalls | no |
| `X-Accel-Buffering: no` from the kit, parts only | none for parts | from the first byte, parts only | unchanged | later, if parts need it; it needs a Games change |

The trade-off is the same for all three: a slow phone now holds one of the game's 8 stream slots for longer
instead of nginx absorbing the answer to disk. The memory buffers (8 × 4–8 KiB per request) smooth short stalls.
`send_timeout 30s` bounds the worst case.

### Limits and long-lived connections

- **WebSockets:** `limit_conn` counts an upgraded connection as one for its whole life, so a page's WebSocket uses
  1 of 24. `send_timeout` applies only between two successive writes *to* the phone. A quiet WebSocket is governed
  by `proxy_read_timeout 3600`, which is unchanged. The kit's keepalive pings reach the phone well inside 30 s.
- **Long polls:** the Party's long poll is `/party/api/`, a different location. No limit here touches it. A game's own
  long poll, if one ever exists, is one request of the 24.
- **Hosted staging:** every request arrives through `cloudflared` from `127.0.0.1`, so a per-address limit
  would be shared by every player. **Do not add `limit_conn` to `deploy/hosted/avrana-party.hosted.nginx`.** Only
  `proxy_max_temp_file_size 0` and `send_timeout` go there. The hosted VM's disk is not an SD card, so the hosted
  change is optional.
- **24** is a starting value, not a measurement. A cold page load with content parts must stay under it. The
  sampler run below records the peak concurrent requests per phone, so the value can be set from evidence.

## 3. Measurement plan (the Pi, before and after)

The order follows the 2026-10-15 content-delivery review:
1. Capture the **unmodified** baseline first, with AVR-501's whole-pack test package (D1 approved separately), and
   keep `nginx -T` snapshots.
2. Make only this change.
3. Repeat the same runs.

Do not combine this with AVR-506 (playable first).

| Measure | How | 1 phone | 3 phones |
|---|---|---|---|
| SD sectors written during a cold load | AVR-139 sampler (`~/avr501/avr501-sample.py`): `/proc/diskstats` delta | before / after | before / after |
| Files created in `/var/lib/nginx/proxy` | `inotifywait -m` or a count before and after | must be 0 after | must be 0 after |
| nginx and game CPU, iowait | sampler | | |
| Time to ready per phone | sampler, phone-side timestamp | | |
| Peak concurrent requests per phone | `ss -tn state established '( sport = :443 )'` sampled, or nginx `$connections_active` | sets the 24 | |
| A WebSocket game round still plays and survives a 40 s quiet spell | Checkers on two phones | | |

Pass: no temporary files, SD writes during a cold load drop to the background level, time to ready is not worse
than the baseline by more than noise, and no 503 from `limit_conn` in a normal 3-phone load.

## 4. Applying (after approval only)

- One change, in the source copy and all three site files at once: one deployment unit (AVR-271), checked by
  `tests/unit/test_nginx_site.py`, which compares the copies byte for byte. The hosted file gets the narrower
  version from §2.
- Then `ops/check-party-config.sh`, and a normal `ops/deploy.sh`.
- **Rollback:** remove the added lines and redeploy. On the Pi in an emergency: delete the four lines from
  `/etc/nginx/sites-available/avrana-party`, run `nginx -t`, then `systemctl reload nginx`. `/party/api/status` then
  reports `nginx_site: differs` until the next deploy, which is the intended signal.

## 5. Owner decisions

| # | Decision | Recommendation |
|---|---|---|
| 1 | Approve the baseline-then-change measurement on the Pi | yes, after D1 (hello_content installed) |
| 2 | `proxy_max_temp_file_size 0` over `proxy_buffering off` | yes |
| 3 | `limit_conn 24` per phone on the appliance only (not hosted) | yes, value revisited from the measured peak |
| 4 | Apply to the Pi after the measurements | separate go-ahead |
