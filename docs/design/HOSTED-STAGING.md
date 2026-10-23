# Hosted staging: one Avrana Party, a second deployment target

Status: **architecture approved by the owner (2026-10-22, D1–D5 in §11) · repository work only ·
no VM, tunnel, DNS, Access application or deploy exists; each needs its own owner approval**

Avrana Party gets a second deployment target: a private staging site at `https://avrana.party`,
for platform and gameplay testing between people on different networks. It runs the same Party
Core, Party Home, SDK contracts, game packages and runtimes as the Pi. Only the network edge
differs. The Pi stays the product. It also stays the only place that proves Wi-Fi, the captive
portal, local DNS, offline play and real-phone hardware behavior.

This page is the H1 audit and the approved architecture. Section 0 becomes ADR 0018 when the
hosted site is accepted (H3). Evidence is `file:line` on `main` at Party `aa3d7d4` and Games `9fee527`, plus a
read-only look at the Media host on 2026-10-22.

## 0. Proposed decision (becomes ADR 0018 on approval)

1. **One application.** The same Party Core, Party Home, SDK contracts, game packages,
   `ops/deploy.sh` and systemd units run in both targets. Differences are limited to:
   - deployment configuration (`party-core.json`, a deploy profile);
   - a hosted nginx site rendered from `avrana-party.nginx`;
   - environment-neutral client handling of an authentication redirect.

   Nothing in Core, the SDK or game logic knows which target it runs on.
2. **Isolation.** Staging runs in its own KVM virtual machine on the Media host (Debian 13, like
   the Pi), with its own outbound-only Cloudflare Tunnel. It touches no Media container, nginx
   site, tunnel or data.
3. **Two origins.** `avrana.party` is the Party origin and `games.avrana.party` the game origin,
   as ADR 0013 requires and as native games enforce.
4. **Authentication.** Staging authentication is Cloudflare Access (email allow-list, one-time
   PIN), enforced at the edge and again by `cloudflared` (Access JWT required). It stays separate
   from Party identity: Party Core never reads Access headers.
5. **What is not hosted.** The captive portal, AP, local DNS, Limited Mode, the doorway, the
   arcade and the devserver's test controls.
6. **The appliance stays authoritative.** It is still the only evidence for Wi-Fi, captive
   portal, offline and real-phone hardware behavior. Hosted results never stand in for appliance
   results, and appliance suites are not weakened.

## 1. Findings in one paragraph

Most of Avrana Party is already portable. Its design already separates the pieces a hosted
deployment needs separated:

- Party Core is stdlib Python. It reads the hosts, origins, game origins, games and registry it
  serves from one JSON config (`avrana/party/service.py:866-886`).
- The shell builds every URL from `location.origin`.
- Native games are a systemd template with socket activation, `DynamicUser=` and
  `LoadCredential=` (`deploy/games/avrana-game@.service`). That works on any systemd Linux.
- The Node runtime pin already has an x64 build (`avrana/avrgame/node_pin.py:30`).

**Local experiment (2026-10-22).** Party Core at `main` ran unchanged with a hosted config
(`hosts: ["avrana.party"]`, `origins: ["https://avrana.party"]`, game origin
`https://games.avrana.party`):

| Request | Result |
|---|---|
| Right Host | 200 |
| Host `party.avrana.net` | 421 |
| Join | `__Host-avrana_device` cookie, `Secure; HttpOnly; SameSite=Lax`, no Domain |
| POST with a foreign `Origin` | 403 |
| `/internal/` from a proxied request | 404 |
| `/party/api/bridge` | the configured game origin |

**What does not port is the appliance edge:**

- the access point
- the captive portal and the doorway
- local DNS
- Limited Mode
- the Let's Encrypt certificate
- the arcade (hardware H.264 encoder, `uinput`, and WebRTC bound to the AP)

The legacy LAN Games fork is portable but optional; ADR 0014 retires it.

Three Pi-only assumptions in the tooling also need small adapters: `ops/deploy.sh` unit lists and
the nginx source, the smoke set in `avrana/ops/smoke.py`, and `status` units.

## 2. Dependency map

| Class | Components (evidence) |
|---|---|
| **1. Already portable** | Party Core state machine and HTTP layer (`avrana/party/*`). Device identity: `__Host-` cookie with no Domain, so it works on any HTTPS host (`identity.py:36-41,218-230`). Host, Origin and `Sec-Fetch-Site` guards (`service.py:547-612`). Session protocol: HMAC launch/end, tickets, result envelope (`protocol.py`, `result.py`). Game registry and `.avrgame` packages (`registry.py`, `avrana/avrgame/`). Native-game units (`deploy/games/`). Shell, API client, bridge, layer and service worker, all same-origin and relative (`web/party/lib/party-client.js:21`, `app.js:1194-1207`, `sw.js:51-67`). Shell CSP (`'self'` only). Long-poll transport: every request ≤ 30 s, under Cloudflare's 100 s idle limit (`party-client.js:13,63`). Node x64 pin. Python 3.12 on the host. |
| **2. Configuration only** | `party-core.json`: `hosts`, `origins`, `game_origins`, `games`/`registry`/`packages`, `status.units` (`deploy/party-core/party-core.example.json`). `AVRANA_PARTY_ORIGIN` for native games, which `provision-game` writes from that config. The `frame-ancestors` game host for `bridge.html` and `layer.html` (`avrana-party.nginx:164,177`). Package art and effective-catalog routes (`nginx:187-195`; Party PR #143). `ops/deploy.sh` paths and host, which are already env overrides (`ops/deploy.sh:52-72`). Cloudflare cache bypass for `/party/*`. |
| **3. Small adapters** | **a.** Hosted nginx site rendered from `avrana-party.nginx`, not hand-forked (§6). **b.** `deploy.sh` profile: unit lists (`:74-75`), nginx source (`:434-444`), smoke set. **c.** `smoke.py` hosted set: no captive, DNS, arcade or 8096 checks; the HTTP edge on loopback (`smoke.py:239-256`). **d.** Shell: treat a redirected API response as "sign-in expired" and reload, instead of retrying forever as offline (`party-client.js:19,35`). Neutral on the Pi, whose API never redirects. **e.** Two wording strings that name the Pi (`app.js:1833`, `diag/diag.js:72`). **f.** A hosted Playwright config with a base-URL parameter. **g.** `origin.json` without the private `serverAddr` in the hosted render. |
| **4. Appliance hardware** | AP and NetworkManager, `avrana-captive.conf`, `ops/ap-control/`. Captive probes (`nginx:7-17`) and the doorway (`web/party/doorway/`, `lib/doorway.js`). Limited Mode listener (`service.py:740-766`). Let's Encrypt DNS-01 certificate and timer. Arcade: `arcade/stream.py` (hardware encoder, `uinput`, ICE on the AP, `:137-148`). PS1 provider. Pi telemetry and power watch. `tests/live/*`. Preflight and the release candidate in `mode=appliance` (`tools/release_candidate.py:857`). |
| **5. Must not run hosted** | Devserver and its `/__test__/` controls (`avrana/web/devserver.py`). Party Core `/internal/` and ports 8191/8192 on any non-loopback path. The LAN Games fork with standalone admission on (`AVRANA_STANDALONE_ADMISSION` defaults to open play), its hub and its upload routes. Running the fork at all is optional (D4). It is portable inside the VM, but ADR 0014 retires it. Limited Mode (plain HTTP has no place behind Access). The arcade. |

Games side: §3.

## 3. Games and SDK

Paths in this section are in the Games repository at `9fee527` unless marked "Core".

**The SDK contract is already portable:**

- Keys are per-game HMAC, read from `$CREDENTIALS_DIRECTORY` (`core/party_protocol.py:174-195`,
  `js/party-protocol.mjs:75-96`).
- Tickets live 120 s and server messages 30 s. An NTP clock is enough.
- `launch` and `end` are refused if they carry any forwarded header (`avrana_gamekit/party.py:38,49-52`).
- Results use `avrana.game-result/v1`.
- Return is always `partyOrigin + '/party/'` (`web/avrana-party-bridge.js:90`).

No runtime code names `party.avrana.net`, `games.avrana.net` or `10.42.0.1`. Those names
appear only in comments and tests. WebSocket URLs are built from `location`
(`web/hubnet.js:603-604`).

**Native games need a separate game origin.** This is not optional. Best Guess, Hello, Tanks and
the gamekit scaffold all refuse to run when `partyOrigin` is missing or equals their own origin
(`bestguess/web/bestguess.mjs:241-245`, `hello_party/web/hello.mjs:144`,
`colyseus-tanks/web/avrana.ts:155`, `avrana_gamekit/scaffold.py:581`). Core also refuses a game
origin that equals a Party origin (Core `avrana/contracts/party_config.py:133`). So hosted needs
`games.avrana.party`.

| Game | Runtime | State | Hosted role |
|---|---|---|---|
| Best Guess | Python gamekit, `.avrgame` | merged 2026-10-19; phone, playtest and Pi gates blocked or waived (`bestguess/docs/RELEASE.md`) | **primary showcase, Python** |
| Checkers | Python gamekit, native grant | on main, never deployed | second Python native game |
| Tanks (Colyseus) | Node ≥ 22.12, `.avrgame`, `test_only` | one iPhone match; systemd path never run (`colyseus-tanks/README.md:112-114`) | **only Node game**: experimental coverage |
| BLUFF, EXPO | legacy LAN Games process (FastAPI, :8096, same-origin) | the only titles live on the Pi | optional; portable inside the VM (no Jellyfin clash there) with `AVRANA_STANDALONE_ADMISSION=0` (`server.py:52` defaults to open play) |
| Hello, Hearts | gamekit | test-only and experiment | not deployed |

**Findings that need a change:**

- **Small Games change.** Best Guess's no-bridge message says "Open Best Guess from the Party on
  your Wi-Fi" (`bestguess.mjs:243`). Wording only.
- **Config.** Tanks derives `connect-src` from `X-Forwarded-Proto` (`js/game-app.mjs:163-168`).
  The hosted nginx must send `https` literally, not `$scheme`, because cloudflared reaches it over
  plain HTTP.
- **Config.** Unit paths (`/opt/avrana-party-games`, `/etc/avrana-party/game-keys`) are the same
  in the VM. No change.

## 4. Where it runs: the Media host as it is (read-only, 2026-10-22)

| Fact | Value |
|---|---|
| Host | `avrana` 10.0.0.218: Ubuntu 24.04.3, kernel 6.8, x86_64, 4 cores, 31 GiB RAM (≈23 GiB available), cgroup v2 |
| Disk | root LV 57 G, 50 % used (28 G free), the constraint to respect |
| Workloads | about 40 Docker containers (Jellyfin on host network :8096, Authentik, *arr, Komga, ABS, …), host nginx (Home Assistant proxy only), Plex, libvirt/QEMU (default NAT 192.168.122.0/24), LXD 5.21 installed but never initialized, Podman |
| Cloudflare | two tunnels as user `cody`: `cloudflared-avrana` (the `*.avrana.net` Media hostnames) and `cloudflared` (`comics.avrana.media`); cloudflared 2025.6.1 |
| `avrana.party` | delegated to Cloudflare (same NS pair as `avrana.net`); no address record yet |
| Node | not installed on the host |

**Recommended model: one small KVM virtual machine (Debian 13, like the Pi), managed by the
existing libvirt.** Party runs inside it exactly as on the Pi: systemd units, nginx, `ops/deploy.sh`,
`/opt` releases and ADR 0016 service users. It also runs its own `cloudflared` with its own tunnel.

| Option | Verdict |
|---|---|
| **KVM VM (recommended)** | Same OS family and init as the Pi, so `deploy/` units, systemd sandboxing (`ProtectKernel*`, `PrivateDevices`, `DynamicUser`, `LoadCredential`) and `ops/deploy.sh` run unchanged. A separate kernel and filesystem from Media. Hard CPU and memory ceilings. Snapshots for rollback of the OS layer. No port, nginx site or tunnel on the host. Cost: about 2 GiB RAM and 12 GB thin disk; libvirt is already running. |
| LXD system container | Lighter, and also runs systemd. Needs a first `lxd init` (storage pool, bridge): new persistent host configuration. Some sandboxing directives degrade in unprivileged containers. Second choice. |
| Docker/Compose | Matches the homelab's habit, but Party's units rely on socket activation, `DynamicUser=` and `LoadCredential=`. Re-expressing them in Compose is a second deployment model to maintain, which is the fork we are told not to make. systemd-in-Docker works but fights the defaults. Not recommended. |
| Host systemd services | Would install Party users, units and an nginx site into the Media host's own systemd and nginx, and 8096 is taken. Rejected: touches Media infrastructure. |

## 5. Hosted architecture

```
 tester browser ── HTTPS ──► Cloudflare edge: TLS, Cloudflare Access (email allow-list, OTP)
                                   │   avrana.party, games.avrana.party (one Access application)
                                   ▼  outbound-only tunnel (no inbound port, no router change)
 M700 host (unchanged) ─ libvirt NAT ─► VM "avrana-party-staging" (Debian 13, 2 vCPU, 2 GiB)
                                          cloudflared (own tunnel, own credential, Access JWT required)
                                            │ http://127.0.0.1:8080  (Host preserved)
                                            ▼
                                          nginx (rendered hosted site, loopback only)
                                            /party/             static shell release
                                            /party/api/origin.json  answered by nginx
                                            /party/api/   ──► Party Core 127.0.0.1:8191
                                            /party/pkgart/, catalog.json  static, from install
                                          games.avrana.party (Host) — game origin only
                                            /games/<slug>/ ──► unix:/run/avrana-games/<slug>.sock
                                          Party Core ──signed launch/end──► avrana-game@<slug>
                                                     ◄── ended + result (internal.sock)
```

### Port and routing matrix

| Listener | Where | Exposed to | Routes |
|---|---|---|---|
| Cloudflare edge :443 | Cloudflare | internet, behind Access | `avrana.party`, `games.avrana.party` → tunnel |
| `cloudflared` | VM | outbound 7844 only | both hostnames → `http://127.0.0.1:8080`; catch-all `http_status:404` |
| nginx 127.0.0.1:8080 | VM | cloudflared only | `server_name avrana.party`: `/party/…` as the Pi. `server_name games.avrana.party`: `/games/<slug>/` as the Pi's game origin. Anything else: 404 |
| Party Core 127.0.0.1:8191 | VM | nginx `/party/api/` only | `/internal/` never proxied |
| `/run/avrana-party/internal.sock` | VM | `avrana-games` group | game → Party reports |
| `/run/avrana-games/<slug>.sock` | VM | `avrana-front` group (nginx, Core) | one per game |
| not served hosted | — | — | :80 captive block, `/arcade/`, `/games/(bluff\|expo)` → :8096, Limited listener, devserver |

**Two hostnames, not one.** The brief prefers a single origin, but a single origin cannot run any
native game (§3). ADR 0013 makes the game origin a security boundary: a game page never runs on
the origin whose cookie is the Party credential. The Pi does this with `party.avrana.net` and
`games.avrana.net`, and hosted does the same with `avrana.party` and `games.avrana.party`. These
two hostnames are same-site, so the bridge iframe, CORP `same-site` and cookies work without
third-party-cookie problems. One tunnel and one Access application cover both. Everything is
still one public HTTPS entry with internal routing.

## 6. Code and configuration changes (smallest set)

All changes are environment-neutral or behind deployment configuration. No Core fork, no SDK
change, no hosted flag in game logic.

**Party: H2A, runtime portability (one PR)**

1. `party-client.js`: API fetches use `redirect: 'manual'`. An `opaqueredirect` or cross-origin
   redirect becomes the state `signin-expired`, shown as one "Sign in again" action that does a
   top-level reload. The Pi's API never redirects, so appliance behavior is unchanged. Tested
   offline with a route that answers 302.
2. Wording: `app.js:1833` and `diag/diag.js:72` stop naming `party.avrana.net` and `10.42.0.1`
   when the page is not on them.
3. `avrana/ops/smoke.py --set hosted`: shell, `origin.json`, Party Core through the edge with
   `Host: avrana.party`, game origin 404 for `/party`, native-game socket health, internal port not
   reachable through nginx. The Pi set is unchanged.
4. `ops/deploy.sh --profile hosted`, read from `/etc/avrana-party/deploy.env`: unit lists
   (`avrana-party-core` and provisioned `avrana-game@*`), nginx source (the rendered hosted file),
   host `avrana.party`, smoke set `hosted`. The Pi default is unchanged; existing deploy tests keep
   passing.

**Party: H2B, hosted deployment configuration (one PR)**

5. `tools/render_site.py --target hosted`: renders `deploy/hosted/avrana-party.hosted.nginx` from
   `avrana-party.nginx`. It drops the :80 captive server, `/arcade/` and the 8096 locations. It
   swaps the server names and the `frame-ancestors` game host, listens on `127.0.0.1:8080` without
   TLS, sets `X-Forwarded-Proto https` as a literal (Tanks builds its CSP from it), and replaces `$server_addr` in `origin.json`. The output is
   committed and checked like the other generated files (`docs/GENERATED.md`). A test fails if the
   shared locations drift.
6. `deploy/hosted/`: `party-core.hosted.json`, `cloudflared.yml.example` (no credentials),
   `deploy.env.example`, VM cloud-init (users, packages, nftables egress policy), and the hosted
   runbook (`docs/runbooks/hosted-staging.md`).
7. Package art: adopt the PR #143 `/party/pkgart/` location in the shared source, so both
   targets get it.

**Games: one wording fix.** Best Guess's no-bridge message (`bestguess.mjs:243`) stops saying
"on your Wi-Fi". Games already take the Party origin from `AVRANA_PARTY_ORIGIN`, which
`provision-game` writes from `party-core.json`.

**H3: acceptance harness (one PR)**

8. `playwright.hosted.config.ts`: `BASE_URL` and `GAME_ORIGIN` from the environment, and Cloudflare
   Access service-token headers from the environment (never committed). There is no `webServer`
   and no `/__test__/` control: everything goes through the real UI and API.
9. A game-neutral lifecycle spec driven by a per-game "play script" (a small adapter that makes
   meaningful moves). It runs with two to four independent browser contexts. It is also runnable
   against the Pi (`BASE_URL=https://party.avrana.net`) and the devserver, so the lifecycle tests
   are shared, not duplicated.

## 7. Security and authentication model

| Layer | Decision |
|---|---|
| Who may reach the site | Cloudflare Access application over both hostnames. Allow policy: an explicit email list. One-time PIN login. Session 24 h. A separate service-token policy (non-identity) for the automated harness, scoped to this application only. |
| Direct-origin bypass | None possible by construction: no inbound port, nginx and Core bind loopback in the VM. Additionally `cloudflared` `originRequest.access: {required: true, teamName, audTag}` rejects any request without a valid Access JWT for this application, so a hostname later routed without Access still fails closed. |
| Staging auth vs Party identity | Kept separate. Party Core never reads `Cf-Access-*` headers or the Access email. A tester joins as on the Pi: device cookie, display name, Play/Watch, host rules. |
| Proxy-header spoofing | Core authorizes only by device cookie, Host, Origin and `Sec-Fetch-Site`. Client IP and X-Forwarded-For are never trusted, and `/internal/` refuses any forwarded request (`service.py:678-703`). nginx overwrites `X-Forwarded-*` and `X-Real-IP`. Games get `Cookie: ""` (no device cookie, no `CF_Authorization`). |
| Game endpoints | Only through nginx on the game origin, behind Access. Control paths `/games/*/avrana/` are 404. Sockets are group-restricted. |
| Isolation from Media | Separate VM and kernel. No host bind mounts. VM nftables denies egress to RFC 1918 except the libvirt gateway's DNS; a host-side libvirt `nwfilter` makes that binding (owner-approved host change). Own tunnel credential, own unit, never the `cody` tunnels. |
| WebSockets | Access authorizes the upgrade with the hostname's `CF_Authorization` cookie. An already-open socket survives expiry; the next reconnect gets a redirect, which games treat as a disconnect. The H3 test covers this. |
| Secrets | Tunnel credential, Access service token and game keys live only on the VM or the tester's environment. None go into Git, agent instructions or logs. `avrana/ops/redact.py` covers diagnostics. |

## 8. Appliance vs hosted

| Behavior | Hosted staging | Pi appliance |
|---|---|---|
| Party Home, Library, discovery | Required | Required |
| Core → game launch, multiplayer, return | Required | Required |
| Reconnection, host succession, spectators | Required | Required |
| Captive portal, Wi-Fi onboarding, offline DNS, Limited Mode, doorway | Not applicable | Required |
| Arcade / RetroArch streaming | Not applicable | Required |
| Remote internet play, Access expiry | Required | Not applicable |
| TLS | Cloudflare edge | Let's Encrypt on the Pi |
| Deploy entry point | `ops/deploy.sh --profile hosted` in the VM | `ops/deploy.sh` on the Pi |

Pi suites (`tests/live`, provider, rollback, preflight `mode=appliance`) are not changed or
weakened. Hosted results never count as appliance evidence.

## 9. Deployment, rollback and agent workflow

- **Deploy:** the owner, in the VM, runs
  `sudo ops/deploy.sh --profile hosted --party <sha> --games <sha>`. That gives explicit commits,
  journal, manifest, smoke, last-known-good and `--rollback`, all existing machinery. No deploy on
  push and no GitHub Actions dependency. The verification path is `python3 -m avrana.ops.smoke --set
  hosted` plus the hosted Playwright suite from any laptop with a service token.
- **Reset:** `systemctl restart avrana-party-core` ends the in-memory Party. `--reset-devices`
  also clears hashed device identities. Neither touches anything outside the VM.
- **OS-level rollback:** a libvirt snapshot before each OS change.
- **Agents:** an agent implements, runs local tests, and opens a PR naming the candidate pair. It
  asks the owner for "deploy Party X + Games Y to staging". After the owner runs it, the agent runs
  `npm run test:hosted` with a service token the owner supplies per session. It reports commit,
  results and screenshots. Agents get no SSH key to the host or VM and no Cloudflare credentials.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Access expiry mid-game breaks the bridge iframe (COEP, framed login page) | 24 h session, the `signin-expired` adapter, an H3 test |
| Cloudflare closes idle WebSockets (≈100 s) | Games' own heartbeats (verify per game in H3) |
| Root disk 50 % used | 12 GB thin qcow2, journald caps, keep 3 releases |
| Edge caching of shell files serves stale builds | Cache rule: bypass `/party/*` and `/games/*`; the build-stamped service worker already handles updates |
| Hosted render drifts from the Pi site | Generated file and a drift test |
| Staging mistaken for appliance evidence | The matrix above, and the manifest records `profile: hosted` |
| Tanks' systemd/socket path has never run anywhere | First Node run is an H3 finding, not an assumed pass |
| VM reaching Media services on the LAN | Egress deny, both in the VM and in the host nwfilter |

## 11. Owner decisions (H1 gate, decided 2026-10-22)

- **D1. Approved:** a Debian 13 KVM VM on the existing libvirt host, keeping the Party's systemd
  deployment model. Storage, free space, resource limits, snapshot cost and isolation from Media
  services are checked before the VM is created (`deploy/hosted/vm/host-preflight.sh`).
- **D2. Approved:** `avrana.party` for the Party and `games.avrana.party` for native games. The
  separate-origin contract (ADR 0013) is unchanged.
- **D3. Approved in principle:** Cloudflare Access with an explicit email allow-list, OTP, 24 h
  sessions and one narrowly scoped service token for the harness. At first only the owner's address
  is allowed. Nothing in Cloudflare changes until the owner approves the address and the
  Access configuration.
  **Superseded 2026-10-23 by the owner:** one shared password instead of Access (the password gate:
  `avrana/ops/hosted_gate.py`, runbook step 5c). Trade-off accepted: anyone with the password gets in,
  and there is no per-person sign-in or revocation short of changing the password. Party identity is
  unchanged: the gate cookie is not a member, and Party Core still names people by its device cookie.
- **D4. Approved, staged:** the first wave is Best Guess, Checkers and Tanks (experimental). BLUFF and
  EXPO come in a second wave with standalone admission off; legacy games never block the first. The
  arcade is never hosted.
- **D5. Approved:** H2A, H2B and H3 repository work, local experiments, reviews, documentation, tests
  and draft PRs. Each of these needs its own explicit approval: creating the VM, changing persistent
  host configuration or network filters, the tunnel, DNS, Access, a deploy, merging, and exposing
  anything publicly.

The owner also requires that isolation is tested by attempted connections, not only firewall syntax.
Access must be shown to work across both origins, game frames, reconnects and session expiry. The
Pi deploy path and its tests stay unchanged. Party #143's package-artwork route is used only after
its own approval. Deploys and rollbacks name explicit Party and Games SHAs. An unavailable CI check
is never counted as passing.

## 12. Implementation plan and acceptance

| Step | Work | Gate |
|---|---|---|
| 1 | H2A PR (adapters 1-4) with offline and unit tests | owner review |
| 2 | H2B PR (render, hosted config, cloud-init, runbook) | owner review |
| 3 | Create the VM (no network exposure); deploy; smoke on loopback inside the VM | **owner: VM on M700** |
| 4 | Tunnel, `avrana.party` DNS and the Access application | **owner: Cloudflare changes** |
| 5 | H3 harness PR; run the remote journey and failure cases | owner supplies the service token |

**Acceptance criteria:**

- Smoke `hosted` passes.
- An unauthenticated request to either hostname gets the Access login, and no origin route
  answers without a JWT.
- Two or more remote browsers, then phones on different networks, complete the 14-step journey
  on a Node and a Python game. Host succession, reconnect and repeat launch pass.
- The Pi suites are unchanged and green.
- `deploy --rollback` restores the previous pair.
