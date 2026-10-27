# Game-origin trust tiers for community packages (AVR-680)

- **Status:** proposal, 2026-10-27. Nothing is implemented, and no authorisation is widened. The owner's direction
  (2026-10-20) is:
  - Party Core keeps authority over origin registration;
  - a community package cannot authorise its own origin;
  - per-game isolation is preferred for untrusted community games.
- **Reads with:**
  - [ADR 0013](../../adr/0013-party-and-game-browser-origins.md) and [BROWSER-ORIGINS](../BROWSER-ORIGINS.md)
    (decisions D1-D5);
  - [GAME-INSTALLATION](../GAME-INSTALLATION.md) ("Trust tiers (conceptual)");
  - [ADR 0016](../../adr/0016-service-identities-and-local-trust-boundary.md) (service identities);
  - `avrana/contracts/party_config.py` (`check_game_origins`);
  - `web/party/lib/bridge.js` (`originAllows`) and `web/party/lib/layer-app.js` (`allowed`);
  - `avrana/avrgame/installed.py` (install records, `TIER`).
- **Related, not decided here:** AVR-509 (the design of real per-game origin and storage isolation, which is
  escalated before implementing). The play-shell drafts (ADR 0018 r3, Party #262, Games #105/AVR-766) put the
  game in a frame inside `/party/`, which changes what a page can cover (section 2, D3).

## 1. What is true on `main` (6c5b3c7)

- **Registration is the owner's.** `game_origins` in Party Core's config maps a bare origin to `"*"` or a list of
  game ids. `check_game_origins` refuses Party origins and non-bare values. The bridge and the layer frame answer
  only their own origin or `originAllows(origins, origin, game)`. The hosted example lists ids
  (`checkers`, `bestguess`, `colyseus-tanks`), not `*`.
- **A package is always `community`.** Its install record's grant has `tier: "community"` and
  `entry: "/games/<id>/"`, and both are re-checked on every load. Its server is its own `DynamicUser` process on
  a Unix socket (ADR 0016). Its page is served on the **shared** game origin with every other native game.
- **The kit's layer opt-in grants nothing.** `data-avrana-party-layer` is a request. Only a registered origin
  is answered.
- **D3:** over a game origin, the drawer offers only End and Party Home (and Leave, AVR-580), because the page
  owns the viewport and could cover the frame.
- **Storage on the game origin is shared by all games**, and no native game may control a Service Worker
  (AVR-135; BROWSER-ORIGINS §6 update).
- **Gap probed on `main`: a package may *ask* for anything in `extensions`, and nothing refuses it.** The
  contract validator accepts an unregistered `net.avrana.origins` object, and accepts
  `net.avrana.catalog: {provider, integration}` self-labels. Both pass `game.validate`. Nothing reads an origin
  claim today, so it is inert. But the owner's rule that an install must refuse a package that tries to
  configure its own origin is **not** enforced, and the catalog's `provider` label can be self-asserted.

## 2. The tiers

| | 1. First-party, Party origin | 2. First-party, shared game origin | 3. Community, trusted by the owner | 4. Community, untrusted (default) |
|---|---|---|---|---|
| Examples | Party Home, Party layer, arcade page | Checkers, Best Guess, Tanks, BLUFF/EXPO | a package the owner vouched for, by content hash | any other installed `.avrgame` |
| Browser origin | the Party origin | `games.<domain>` (shared) | shared game origin **or** its own (owner's choice) | **its own origin per game id** (section 4); until then not launchable on a hosted appliance, or launchable only with the owner's explicit `*`-free listing and a warning |
| `game_origins` entry | n/a | owner lists the id | owner lists the id | owner lists the id **on its own origin only**; `*` never covers it |
| Party layer | native | frame from the Party origin | frame from the Party origin | frame from the Party origin |
| Drawer verbs over the page (D3) | all | End, Party Home, Leave | End, Party Home, Leave | End, Party Home, Leave; in the play shell (ADR 0018), the frame is the Party's own page and cannot be covered |
| Bridge capabilities | n/a | ticket, view, navigate, end, home, playAgain (closed set) | same | same; nothing more is ever granted per tier |
| CSP | Party's own | kit page policy: `frame-src <party>`, `frame-ancestors 'none'` (or the Party origin in the shell) | same | same; **no CSP `sandbox`**: without `allow-same-origin` the page's origin is `null`, which the bridge cannot register, and with it the sandbox adds nothing, so the per-game origin is the containment |
| Storage / Service Worker | Party's | shared with other tier 2/3 games; no SW | shared (shared origin) or own | own origin only; no SW |
| Server process | Party service | own `DynamicUser`, Unix socket | same | same, plus `PrivateNetwork`, a system-call filter and resource ceilings (GAME-INSTALLATION "Isolation that is cheap on a Pi") |
| Who sets the tier | the image | the image | the owner, per content hash; an update drops it to tier 4 until re-approved | the installer, always |

The tiers never change the bridge's verb set, the ticket or the session protocol. A tier only decides **where**
a page lives and **how strongly** it is contained.

## 3. Registration rules

1. **Only Party Core's configuration, written by the owner, registers an origin.** No manifest, contract,
   extension, install record or package file can add, widen or name one.
2. **A package may not even ask** in a way that looks like configuration. At install time, and on every load of
   an install record, refuse a package contract that carries:
   - an unregistered `net.avrana.*` extension namespace;
   - `net.avrana.catalog`, whose provider and integration labels are the appliance's to set;
   - `net.avrana.party` keys outside the registered set (already refused by `party_config`);
   - any top-level or extension key named `origin`, `origins`, `game_origins`, `frame_ancestors`, `csp` or
     `host`.

   Third-party namespaces (`com.example.*`) stay allowed and inert.
3. **`*` covers tiers 2 and 3 only.** `check_game_origins` gains a rule: an origin whose value is `*` may not be
   the origin a tier-4 game is served from. A tier-4 game must be listed by id on its own origin.
4. **Trust is per content hash.** Promoting a package to tier 3 records the archive's `sha256` in the owner's
   config, not in the package. An update installs as tier 4.

## 4. Per-game isolation for untrusted games

**Naming:** `<id>.games.<domain>`, for example `wordclash.games.avrana.net`. Per BROWSER-ORIGINS §2, a sibling
host is the **same site**, so:

- Storage, Service Workers and `Origin` separate by origin. That is the point.
- Cookies do not. A page can set `Domain=games.avrana.net` or `Domain=avrana.net` and plant a cookie on its
  siblings. Kit games authenticate by `game_token` in the request body, not by cookie, so this cannot seat
  anyone. The `__Host-` device cookie (D3) is refused by browsers when set with a `Domain`. **Requirement:** the
  game hosts' nginx strips `Cookie` toward game servers, as the arcade already does (AVR-318).

**What each new name costs:**

| Item | Cost |
|---|---|
| Certificate | one wildcard `*.games.<domain>` via the DNS challenge (one more name, not one per game); renewal is unchanged (party-https runbook); **offline install of a new game needs no new certificate** |
| DNS | Party DNS answers `*.games.<domain>` with the appliance address (one wildcard record) |
| nginx | one `server` block with a `server_name ~^(?<game>[a-z0-9-]+)\.games\.` map to `/games/<game>/`, refusing an id that is not installed; no per-game file |
| `game_origins` | one entry per tier-4 game, written by the owner's install confirmation (the owner approves the install, the tool writes the entry, Party Core reloads) |
| Appliance resources | none at rest; per-origin browser storage on phones; one more DNS answer per game |

Limited Mode (ADR 0012, plain HTTP, no names) cannot separate origins by name. Tier 4 is **not launchable in
Limited Mode** unless the owner accepts a port-per-game fallback. A port is not a cookie boundary, but it is an
origin boundary.

## 5. Requirements and tests

| # | Requirement | Test | Exists? |
|---|---|---|---|
| R1 | An unregistered origin gets nothing from the bridge or the layer | `tests/offline/party-layer.test.mjs`, bridge tests | **yes** |
| R2 | A package carrying an origin-like key, `net.avrana.catalog` or an unregistered `net.avrana.*` namespace is refused at install and on load | new: install and `installed.load` unit tests with each key | no (probed: accepted today) |
| R3 | `*` never covers a tier-4 game's origin | new: `check_game_origins` with tier information | no |
| R4 | The frame refuses a forged origin (a page on origin A claiming game B) | `originAllows` unit test plus a Playwright two-origin case | partly (unit) |
| R5 | A tier-4 game cannot read another game's storage | new Tier 2 test: two per-game hosts, `localStorage` and IndexedDB written on one, absent on the other | no |
| R6 | A tier-4 game cannot reach another game's server | new: nginx config test (host to `/games/<id>/` map refuses a mismatched id) | no |
| R7 | No `Cookie` reaches any game server | extend the AVR-318 nginx assertion to every game host | partly (arcade) |
| R8 | An update drops tier 3 to tier 4 | new: install-record test (hash mismatch, so the tier is refused) | no |
| R9 | A tier-4 page's `frame-ancestors` names only the Party origin, and its `frame-src` only the Party origin | new: page-header test in the kit (`helpers.page_headers`) | partly (kit policy) |
| R10 | Tier is shown to the owner and never to a package | new: catalog entry carries a `tier` set by the appliance; package input ignored | no |

**Catalog and overlay fields:** the catalog entry gains `tier` (from the grant, never the contract) and
`origin` (from `game_origins`, never the contract). The overlay keeps its rule that a record is re-checked whole
on every load.

**Phasing out `*`:**
1. Add R3 now; it changes nothing for today's tier-2 listing.
2. Have the deploy example and preflight warn on `*` (the hosted example already lists ids).
3. Refuse `*` once every first-party game is listed by id.

## 6. Owner questions

1. Until per-game hosts exist, should a tier-4 game be **refused** on a hosted appliance (recommended), or
   allowed on the shared origin with a warning?
2. Naming: `<id>.games.<domain>` under one wildcard certificate (recommended), or a separate registrable domain
   for community games (true cross-site separation, at the cost of a second domain and certificate)?
3. Should an install confirmation write the `game_origins` entry for the owner (recommended, one step), or
   should the owner edit the config by hand?
4. Should R2 refuse unknown `net.avrana.*` namespaces outright (recommended), or warn for one release?
5. Limited Mode: no tier-4 games (recommended), or a port per game?

**Estimate once approved:**

| Part | Effort |
|---|---|
| R2 + R3 + R8 + R10 | 1 day |
| R9 and the kit header | 0.5 day |
| Wildcard host, nginx map, R5-R7 Tier 2 tests | 2 days, plus an owner-run certificate and DNS step |
| Real-phone storage-separation proof (Tier 3) | owner-gated |
