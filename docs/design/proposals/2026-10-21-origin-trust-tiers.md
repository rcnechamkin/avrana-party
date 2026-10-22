# Game origin trust tiers (AVR-680)

- **Status:** PROPOSAL for owner decision, 2026-10-21. Nothing here is deployed, enabled or implemented, and it
  widens no authorization. Sections marked **Current** describe `main` (8de7ef2); sections marked
  **Proposal** do not exist.
- **Builds on:** [ADR 0013](../../adr/0013-party-and-game-browser-origins.md) (D1: one shared game origin now, per-game later
  as configuration), [ADR 0011](../../adr/0011-party-console-model.md) (host controls),
  [BROWSER-ORIGINS](../BROWSER-ORIGINS.md), [cross-origin layer finding](../../findings/2026-10-20-cross-origin-party-layer.md),
  [launch authority finding](../../findings/2026-10-20-launch-authority-and-membership.md). Owner rule of 2026-10-20
  ([sdk-clean-room-validation](2026-10-20-sdk-clean-room-validation.md) section 6.2): first-party opt-in never admits
  community games.

## 1. Invariants (Current, kept)

1. **Party Core alone registers origins.** `Config.game_origins` (`avrana/party/service.py:456`) is read from the
   operator's config; the installer neither reads nor writes it (no `game_origins` in `avrana/ops/install_game.py`).
   A game origin may not also be a Party origin (`service.py:457-459`).
2. **A manifest requests, never grants.** `avrana/avrgame/manifest.py` rejects `tier`, `grant`, `entry` and friends;
   the tier is a constant the installer writes (`avrana/avrgame/installed.py:47`).
3. **Trust is an operator action recorded outside the package.** Today the only record is root-owned
   (`installed.py:12-14`, re-checked on every load).
4. **A game page holds no Party authority** (ADR 0013 D2): bridge v1 is a closed verb set (`ticket`, `view`,
   `navigate`, `end`, `home`, `playAgain`); `navigate` goes only to Party Home; across origins the Host sees only
   End and Party Home (`web/party/lib/layer.js:126-134`).

## 2. The three tiers

**Current:** one tier word exists for installs, `community` (`installed.py:47`, forced again at `installed.py:280`);
first-party games come from the repository, not an install record. `avrana/contracts/appliance.py:21` already
admits `builtin`, `trusted`, `community` as vocabulary, but nothing yields `trusted`. Origins today are one shared
`games.avrana.net` for everything (D1). **Proposal:** make the three tiers real and let an origin follow the tier.

| | First-party | Owner-trusted | Untrusted community |
|---|---|---|---|
| Who | Avrana's own games (repo contracts) | package an owner installed and vouched for | any other installed `.avrgame` |
| Origin | shared game origin (Current: `games.avrana.net`); same-origin Party in Limited Mode | **Proposal:** shared game origin, separate from community | **Proposal:** its own origin per game |
| Party layer (floating button) | allowed if the page opts in | not by default; owner decision D3 | never |
| Bridge v1 actions | all six verbs | `ticket`, `view`, `end`, `home`, `playAgain`; navigate to Party Home only | `ticket`, `view`; End/lobby only if D3 says yes |
| Host controls over it | End and Party Home | same | none until D3 |
| Cookies | none on the game origin (Party cookie is host-only `__Host-`, `Path=/`; nginx also clears `Cookie` to game servers, `avrana-party.nginx:402`) | none | none |
| Storage | origin-partitioned, shared by first-party games on that origin | partitioned from first-party | one origin each, so no cross-game reads |
| CSP | **Gap:** the games server block sets none (no `add_header` after `avrana-party.nginx:342`) | **Proposal:** appliance CSP | **Proposal:** strictest appliance CSP, no override |
| `persistent_storage` | n/a (first-party servers) | grantable | grantable, owner-confirmed |
| `party_roster` | delivered | grantable | grantable |
| DNS and certificate | existing name | one extra name | per-game name or wildcard (section 4) |
| Install-time checks | repo review and CI | package checks plus signed owner vouch record | package checks only, tier forced `community` |

Grants today are limited to `persistent_storage` and `party_roster` (`installed.py:50-52`,
`install_game.py:383-413`); every other permission is refused because the sandbox cannot provide it. This proposal
adds no permission.

## 3. Enforced today versus convention

| Claim | Status | Where |
|---|---|---|
| Party Core registers game origins; POSTs need a Party `Origin` | **Enforced** | `service.py:608`, `service.py:456` |
| Ticket route checks `Origin` against `game_allowed(origin, game)` | **Enforced** | `avrana/party/sessions.py:310`; `service.py:461` |
| Browser-marked cross-site requests to the Party API are refused | **Enforced** (browsers that send `Sec-Fetch-Site` over HTTPS) | `service.py:557-559` |
| Bridge and layer frames answer only registered origins | **Enforced** in frame JS | `web/party/lib/bridge.js:52`, `layer-app.js:33-49`; `frame-ancestors` names only `games.avrana.net` (`avrana-party.nginx:164,177`) |
| Package tier is `community`, whatever the manifest says | **Enforced** | `installed.py:47,280` |
| No Service Worker from a native game; game sees no Party cookie | **Enforced** at nginx | `avrana-party.nginx:372-403` |
| Installing a package registers or avoids a game origin | **Not a thing.** Origins are hand-edited config. | `party_config.py:113-137` (validation only) |
| Origin follows tier | **Not enforced.** `game_origins` maps `'*'` or an id list; with `'*'` any installed package on that origin is admitted to bridge and layer. | `service.py:461-463` |
| Layer opt-in excludes community | **Convention.** The opt-in is the page's own attribute (`party-follow.js:234-235`, gamekit `data-avrana-party-layer`); Party Core never looks at tier when admitting a layer. The Games contract pins `mounted_by: ["bluff","expo"]` as a declaration only. | `layer-app.js:49` |
| Grants enforced at launch | **Not enforced** by Party Core; the installer refuses what the sandbox cannot give | `installed.py:50-52` |
| CSP on game origin | **Absent** | `avrana-party.nginx:342-430` |

## 4. Per-game origin versus one shared games origin

| Property | One shared origin (Current) | One origin per game (Proposal) |
|---|---|---|
| Cookies | none set by Party; a game page can still set its own, visible to every game on the origin | host-only per game; a sibling cannot read or overwrite another game's (parent-domain planting remains, so `__Host-` names stay mandatory on the Party side, BROWSER-ORIGINS section 2) |
| `localStorage`, IndexedDB, OPFS | shared: one game can read or fill another's | partitioned |
| Service workers | refused for all by nginx | refused for all; scope also isolated if ever allowed |
| Bridge/layer registration | `'*'` or a list on one entry | one `game_origins` entry per game, exact id; natural fit for the existing mapping |
| Certificate | one extra SAN, already designed (AVR-319) | SAN per game (reissue at each install) or a wildcard `*.games.avrana.net` (DNS-01, one issuance, one key serving every game) |
| DNS on the LAN | one `host-record` in dnsmasq | dnsmasq `address=/games.avrana.net/10.42.0.1` wildcard (host-record is exact-name only), no per-install DNS edit |
| mDNS | not used; phones resolve through the AP's dnsmasq | still not used; do not rely on `.local` for HTTPS names |

Recommendation: keep the shared origin for first-party games; give each community game its own origin under a
wildcard (`<id>.community.avrana.net`), a different label tree so the first-party wildcard exposure does not
overlap. Owner-trusted games may share one origin (`trusted.avrana.net`).

## 5. Gaps

The unenforced rows of section 3 are the gaps: no CSP, `'*'` admits any package, layer admission is the page's own
choice, `trusted` has no record or command, and nothing has run on a real phone (ADR 0013 amendment).

## 6. Minimal staged plan (Proposal; each stage is owner-gated)

1. **Stage 0, policy only (this document):** owner picks tier names, D1 to D4 below. No code.
2. **Stage 1, make `'*'` unnecessary:** `game_origins` lists exact ids for first-party games only; community games
   are absent from it, so they get no bridge or layer. No new authority, only narrower config; add a unit test that
   an installed package id is never admitted.
3. **Stage 2, CSP on the game origin:** an appliance-set header on `games.avrana.net`, for review before any live change.
4. **Stage 3, tier as operator record:** a root-owned trust file (for example `/etc/avrana-party/trust.d/<id>.json`)
   written by an `install-game vouch` step; the installer, not the package, produces `trusted`; the loader re-checks it.
5. **Stage 4, per-game community origins:** wildcard certificate, dnsmasq wildcard, one nginx server block with a
   `$host`-derived slug check, and an install-time `game_origins` proposal printed for the owner to apply (never
   self-applied).

## 7. Owner decisions needed

- **D1:** adopt the three-tier vocabulary (`builtin`, `trusted`, `community`) as policy?
- **D2:** should community games ever get any bridge verb beyond `ticket` and `view`? (Default: no.)
- **D3:** may owner-trusted games mount the Party layer? (Default: no.)
- **D4:** accept a wildcard certificate and dnsmasq wildcard for community origins, or stay on one shared origin with
  `'*'` removed and CSP added (Stages 1 and 2 only)?
