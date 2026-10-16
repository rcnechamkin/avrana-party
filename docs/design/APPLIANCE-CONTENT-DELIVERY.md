# Appliance content delivery: a game's data to a fresh phone, automatically

- **Status:** **PROPOSED (2026-10-15, AVR-500/AVR-501). Experimental code exists in the Games repository
  (content packs, PR linked from AVR-501); nothing is deployed; no ADR is changed.** Decisions that need the
  owner are listed in section 7 and nowhere else.
- **Reads with:** [AVRGAME-PACKAGE](AVRGAME-PACKAGE.md) "Browser client contract" (AVR-135, unchanged),
  [PORTABLE-GAME-CLIENT-DELIVERY](PORTABLE-GAME-CLIENT-DELIVERY.md), ADRs 0013, 0014, 0016. Product
  boundary: AVR-499. Phone proof: AVR-139.

## 1. The requirement and its boundary

A guest joins the Wi-Fi, opens the Party in Safari or Chrome, and plays a supported game with no app, no
Internet, no file to choose and nothing to import. The appliance holds the canonical installed game; a
phone's copy is a disposable cache. A phone still downloads and may keep bytes: that is the point, not a
violation.

## 2. What already exists (traced on `main`, 2026-10-15)

| Step | Where | Fact |
|---|---|---|
| Package | `avrana/avrgame/common.py:15-18` | at most 2000 files, 16 MiB per file, 64 MiB in total and per archive |
| Install | `avrana/ops/install_game.py:544-554`, `installed.py:129-146` | staged under `/opt/avrana-games/<id>/<version>-<sha12>/`, sealed 0644/0755, a sha256 per file in `/etc/avrana-party/packages.d/<id>.json`; `install-game verify` re-hashes; no in-place upgrade (remove then install) |
| Serve | `deploy/games/nginx-native-games.location` | nginx proxies `/games/<id>/` to the game's own Unix socket; it serves no package file itself and adds no cache header; default proxy buffering |
| Game process | Games `avrana_gamekit/app.py`, `runtime.py` | the kit serves the client files with AVR-135's cache classes (`no-cache` + strong ETag, 304) and a build identity; community tier: `MemoryMax=256M`, `CPUQuota=100%`, `PrivateNetwork=yes` |
| Browser | AVR-135 | no game Service Worker (nginx refuses), one shared game origin (storage shared between games: stated temporary limitation) |
| Player data | Games `js/avrana-byod.mjs` (AVR-470) | a player's own files imported into OPFS; not served by the appliance |

So the client code of any installed game already reaches a fresh phone automatically. What was missing is a
game's **data** when it is larger than the client: the kit held every served file in memory, nothing could
resume or verify a large download, and the package limits stop at 64 MiB.

## 3. Four kinds of bytes, kept apart

| Kind | Canonical copy | Reaches a phone | May a phone keep it |
|---|---|---|---|
| Client code and small assets | installed package | the game's process, AVR-135 cache classes | yes, disposable |
| Content pack (rights-cleared game data) | installed package, per-file sha256 in the install record | the game's process streams declared parts | yes, in OPFS, disposable |
| A player's own data (BYOD, e.g. OpenCE maps) | the player's device | never from the appliance | the player's own browser only |
| Session state, tickets, tokens, results | Party Core and the game process | `no-store` answers only | never |

## 4. The design (smallest change)

**A content pack is part of the package.** A directory with `manifest.json` and `parts/<sha256>`, every
part at most 16 MiB (today's per-file limit), built deterministically by the kit. No new package field:
the installer stages and records it like any file, `verify` covers it, remove deletes it.

**The game's own process serves it** (ADR 0014 unchanged): the manifest as an ordinary file, each declared
part streamed from disk with `sendfile`, `no-cache` and the part's digest as a strong ETag (AVR-135's class,
unchanged). Nothing else under the pack is reachable. No nginx alias, no second file server, no Party Core
change.

**The page fetches what it lacks** (`avrana-content.mjs`): quota first, every part's SHA-256 checked before
it is kept, parts kept in OPFS by digest, resume at the part, only changed parts after an update or a
rollback, a completion marker written last. Without OPFS a small pack (<=64 MiB) is held in memory. No
Service Worker, no Cache Storage: the bundle stays host-neutral.

Rejected for now, with reasons: nginx serving the package tree directly (faster, but a new security
boundary and per-version config writes: decision D3b); a Service Worker (refused by AVR-135); relying on the
HTTP cache alone (per-entry limits and eviction on phones make a 300 MB set unreliable; parts are fetched
`no-store` precisely so they are not stored twice); a custom sync protocol (unneeded).

## 5. Rights gate

Storing data on the appliance, transmitting it to guests, and letting guests' browsers cache it are three
separate rights (AVR-73, AVR-316). A content pack exercises all three. Only data with all three may be
packed: Avrana's own, freely licensed, or synthetic. **OpenCE's Halo data has none of them established:
OpenCE stays bring-your-own-data, an experimental path, not the guest default.** Owning a disc is not a
redistribution right.

## 6. Evidence so far (simulated) and what is still unknown

Measured in desktop Chromium on one machine, loopback only (Games `docs/content-delivery.md`): a 304 MB
synthetic pack ready in 7.5 s cold, 0.3 s warm with 0 bytes, 55.6 s with Chromium throttled to 46 Mbit/s,
three browsers at once about 23 s each; the game process stayed at about 25 MiB resident. Earlier real
Wi-Fi evidence (finding 2026-10-06): about 46 Mbit/s TCP downlink to one tablet on channel 36, and
round-trip p99 near 600 ms under full download load. So a 300 MB pack is roughly a minute for one phone in
ideal conditions, longer when phones share the radio, and must not be downloaded during play.

Unknown until measured on real hardware (AVR-139): phone OPFS quotas and eviction (Safari especially),
WebCrypto speed on phones, the Pi's CPU cost per byte through Python, nginx and TLS, and concurrent-phone
airtime.

## 7. Owner decisions (approval packets)

| # | Decision | Why | Risk | Reversal |
|---|---|---|---|---|
| D1 | Install the test package `hello_content` on the appliance (the 56 MiB synthetic build) and add `hello_content` to `game_origins` for `https://games.avrana.net`, for AVR-139 phone and multi-phone runs | the only way to measure real phones and the Pi's Wi-Fi; within today's package limits, no code deploy | a test game appears in the Library while installed; shares the radio during tests | `install-game remove hello_content`, restore the config backup, restart Party Core |
| D2 | Package limit for declared content: keep 16 MiB per file, raise the total and archive limits (for example to 1 GiB) and make the archive reader stream instead of reading the archive into memory | a 300 MB pack cannot be installed today; parts already respect the per-file limit | SD space, install time, a larger validation surface; it is a package-format change (paired Party + Games, AVR-472) | lower the constants again; installed packages unaffected |
| D3a | `proxy_max_temp_file_size 0;` (or `proxy_buffering off;`) in the native-game location | with default buffering nginx spools a large answer to a temporary file on the SD card when a phone is slower than the game | very low: the game process already streams | remove the line |
| D3b | (later, only if the Pi's CPU is the bottleneck) nginx serves content parts directly from a sealed, content-addressed copy, as the `pkgart` draft does for artwork | sendfile and TLS in nginx instead of Python | a new static-serving boundary; needs its own security review | remove the location |
| D4 | Per-game browser storage isolation | today any game's page can read or delete another game's parts (never forge one that passes a fresh check) | needed before licensed content or public community packages | ADR 0013 amendment, out of this sprint |
| D5 | An owner "offline-ready" indicator per game = installed and `verify` clean, never phone caches | AVR-86/AVR-60 | none | n/a |

## 8. Acceptance matrix

| Case | Simulated (CI) | Real Pi + phones (AVR-139) |
|---|---|---|
| Fresh browser, no WAN, no import | yes | pending D1 |
| Warm relaunch, close/reopen | yes | pending |
| Eviction recovers from the appliance | yes | pending |
| Interrupted transfer resumes | yes (blocked part) | pending (Wi-Fi off and on) |
| Damaged or undeclared part never used | yes | n/a |
| Low quota explained before download | yes (patched estimate) | if a full phone is available |
| Update and rollback fetch only changed parts | yes | pending |
| 1 and 3 concurrent guests; timings, Pi CPU | 1 and 3 on one desktop | pending |
| No secrets in caches | yes (OPFS holds only parts and marker) | pending |
| Writer without `createWritable`/`move` (older Safari path: Worker + sync access handles) | yes (Chromium with both removed) | pending (real Safari) |

## 9. Security review checklist (for any reviewer)

- Only parts named in the manifest are served; no listing; GET only; parts must be regular files of the
  declared size (no links) at load.
- Every byte a phone keeps was checked against the manifest's digest when it arrived.
- Parts carry `no-cache` and a digest ETag; the manifest is a client file; nothing with a token is cacheable.
- The pack is inside the package, so it is covered by the install record and `install-game verify`.
- No new Party route, nginx location, Party Core code or service identity in the experimental proof.
- The shared-origin storage limitation is stated, not solved (D4).
