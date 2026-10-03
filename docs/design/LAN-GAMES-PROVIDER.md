# LAN Games provider boundary

Status reconciled 2026-10-01: **implemented and merged** (Party PR #7 / Games PR #1), deployed
with the fork/shell cutover; [SYSTEM](../SYSTEM.md) owns verified revisions. Builds on assimilation
PR #5. The ownership audit retains the 2026-09-26 baseline (Party `459d4cd`, Games `2cf4831`);
then-missing Party Home/roster/BLUFF grants are historical observations. ADRs 0006–0011 add those
capabilities; current main follows authoritative Party location, with no normal Join/Leave UI
and host controls in game chrome. ADR 0011 deployment/phone proof remains AVR-212.

> **Status banner (2026-10-02): historical and currently-deployed provider boundary, being
> superseded by [ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md).** LAN Games is retiring as an Avrana runtime; standalone LAN
> Games is not a supported product mode; `wc-token` player admission is retiring; game clients
> move off the Party origin ([ADR 0013](../adr/0013-party-and-game-browser-origins.md)). The operational facts below (catalog export,
> launch marker, shared keys, service-worker scoping, deployment dependency) remain true of
> production and must be respected until the runtime is actually removed and that removal is
> verified in [SYSTEM](../SYSTEM.md). Phrases such as "standalone remains supported" and "return
> is fixed `/party/` on the same origin" are deployed behaviour, not forward architecture.

## Historical concrete ownership audit (2026-09-26)

| Area / actual implementation | Classification / boundary |
| --- | --- |
| games/registry.py REGISTRY and EXTERNAL | Provider-owned authoritative generic title, icon, blurb/tagline, category, counts, solo, TV and art. Venue overrides are local customization, not canonical metadata. |
| server.py static mounts; WORDCLASH wc_app | Provider-owned /games/<slug>/ and game WebSocket routes. All visible entries have pages; hidden template is excluded. EXTERNAL WORDCLASH is actually mounted in-process. |
| Avrana contracts, appliance grants, catalog and capability evaluation | Canonical Avrana. Metadata describes titles; appliance alone grants installation and paths. BLUFF already has ID bluff and an explicit private-hand contract; do not create lan-bluff. |
| web/party/lib/profile.js and Hub.identity; WORDCLASH localStorage getters | Compatibility adapter: same wc-token/name/avatar/pfp. No copied profile or second token. Token is legacy resume/upload/chat credential, not implemented future device identity separation. |
| /api/avatar, core/avatars.py, data/avatars | Provider transport/storage; canonical Avrana profile owns editing. Public hashed WebP paths, x-wc-token header, EXIF stripped. Runtime photos stay out of Git. |
| lg-favorites, lg-recent, lg-play-total in hub.js / profile.js | Canonical Avrana library backed by existing lists. Canonical IDs use avrana:<GameContract ID> in those same lists. Legacy LAN slugs/bare IDs collapse lazily; unknown entries survive. Standalone hub reads both forms. History means opened, not verified play. |
| /chat/ws, core/chat.py, hub.js, party-chat.js | Temporary transport adapter, one process-wide rolling 60-message conversation. Avrana owns entry/UI; standalone hub retains compatibility UI. Individual game pages have no separate global chat socket. |
| ChatHub presence, game session humans | Connection counts and game seats, respectively; neither is authoritative Party membership. No canonical roster service implemented. |
| Root hub.html/hub.js search/cards/profile/chat/library | Legacy standalone global shell. Do not enter it in Avrana launch mode or add global product features there. |
| hubnet.js manifest/brand/root SW/installGameShell | Temporary duplicate global shell effects; gate explicitly by integrated launch context. Keep game art, feedback and game-specific preferences. |
| Individual HTML root anchors; BLUFF home button | Legacy navigation needs declarative canonical return targets, including active play/reload. No history-only escape hatch. |
| WORDCLASH app.js profile modal/local getters | Separate implementation of the same keys, not a second identity. Gate profile editor in integrated mode; retain standalone/game controls. |
| Donor /sw.js scope /; Avrana /party/sw.js scope /party/ | Separate cache ownership. Integrated pages must not register the donor root worker; donor worker must neither intercept /party/ nor delete foreign caches. |
| wc-muted, lg-haptics/motion/contrast | Provider-owned shared game feedback preferences; preserve them. |
| lg-booted sessionStorage in hub.js | Legacy hub animation only. No new session-storage launch authority. |
| IndexedDB / cookies | No identity/library ownership found there; localStorage is the shared client backing store. |
| Query parameters | Existing dev hub filter and game-specific tv mode; preserve. Add a versioned non-secret integration marker, never identity credentials. |
| Server state | Game sessions and chat are process memory; avatars/media/venue are ignored runtime files. No new database. |
| TV QR links | Game-owned join links. Preserve secure protocol and integrated marker when linking to the phone game. |

## Implemented provider contract (with subsequent Party amendments)

Avrana owns discovery, launch identity, global navigation, profile, library and Party
Chat. LAN Games owns game-specific rules, lobbies, hands, controls and assets.
Standalone / remains a compatibility/dev entry, not a second canonical product.
Integrated launch uses a versioned non-secret URL marker, advertised by the donor
API. The shell must explain an unsupported donor rather than silently entering its
old global UI. Return is fixed /party/ on the same origin, resolving to the canonical
https://party.avrana.net/party/ in production; no arbitrary return URL is accepted.

HTTP/IP/.local profiles remain separate origins; no unsafe storage recovery.
Existing legacy identity authorization and chat clear semantics remain debt.
Party Core now owns authoritative roster/session state and Party Home is implemented.
Per-game chat and PS1 execution promotion remain outside this provider contract.

## Deterministic metadata flow

Private donor repository: https://github.com/rcnechamkin/avrana-party-games.
Authoritative registry -> ops/export_avrana_catalog.py -> provider/catalog.json
-> platform contracts/catalogs/lan-games.json -> python -m avrana.contracts.catalog.
The export is avrana.lan-catalog/v1, includes
30 visible titles and validates each direct page. It contains title, stable ID,
description/tagline, counts, category, solo/TV, art/icon/accent, and exact launch
path; no venue data, live state, grants or secrets. Source.commit records the
reviewed metadata revision and registrySha256 detects drift (normalized newlines).
--check preserves source.commit and compares every field/digest. After registry
changes, regenerate/review/copy this public JSON and rebuild Avrana; do not edit
provider-owned fields by hand. Both repos have drift/normalization tests.

BLUFF retains existing ID bluff and its explicit private-hand/spectator contract.
Its public name/summary/counts come from the provider; BLUFF is granted and listed in
Party Home since AVR-91 (2026-09-28).
The 29 existing LAN grants are unchanged. PS1/RetroArch experimental entries and
arcade grants remain unchanged. Unknown late-join/spectator/private-hand facts
remain flagged for review instead of invented from registry metadata.

Routes stay in the provider descriptor and compiled browser catalog, outside Game
Contracts. The compiler rejects a granted path that disagrees with its descriptor.
The donor never grants installation or overrides capabilities. /api/games only
confirms known visible slugs and advertises avranaIntegration=avrana.lan-launch/v1.
Its URLs or requirements cannot inject launch authority.

## Direct launch and compatibility

A granted browser title launches /games/<slug>/?avrana=1. /party/ requires the
advertised version; old donor versions show Games update needed and disable their
launches. This is a visible deployment dependency, not a fallback into the old hub.
The shell asks for a saved Party name and persistable identity before launching.
The marker contains no credentials and survives refresh. Unknown markers remain
standalone. No arbitrary return URL is supported.

The donor bootstrap loads before clients, including WORDCLASH. Source-declared
data-avrana-* controls gate global profile/photo/avatar entries and old hub links.
Outside a Party round, a Back to Party control occupies normal document flow. During a Party
round ADR 0011 hides that bar and follows authoritative location; only the host moves the
Party via game chrome. A contained game room retains height for controls and overlays. Game-specific UI is preserved. Existing global profile
name is read-only in integrated game joins; editing lives in /party/.
Standalone remains supported for development and old links. TV links/QRs preserve
HTTPS and the marker; this is navigation compatibility, not TV execution validation.

Integrated clients do not register the root donor SW. Updated standalone worker
bypasses /party/ and integrated navigation/client assets, and deletes only its own
lan-games-shell-* caches. Versioned shared chrome URLs avoid pre-contract cached
scripts. Existing old root registrations still require their normal update/refresh;
include an already-used browser in hardware checks. Avrana worker scope stays
/party/, with no nginx or networking changes.

## State boundaries and remaining debt

Shared keys remain wc-token/name/avatar/pfp and lg-favorites/recent/play-total.
Library keys use avrana:<canonical ID>. Reads collapse known slug/bare-ID aliases
without modifying storage; the next library edit writes normalized lists. Unknown
entries and other-provider favorites/history survive. Reloading a game does not
record a second opening. Counts mean opened, not proven played or completed.

Chat remains the same donor singleton channel/history. Integrated games neither
show competing global chat nor open a second chat socket. Returning to Party
reconnects to that same rolling history. Chat counts remain connections, not roster.
Identity is local origin-scoped compatibility, not accounts. HTTP/.local/IP storage
cannot be recovered across origins. Legacy token authorization and chat clear
semantics, per-game chat, deeper extraction,
PS1 execution, TV/Personal Viewport and Companion remain later work.

## Historical coordinated review / deployment order (2026-09-26 sprint)

The PRs and initial cutover below have landed. This is historical dependency rationale, not
the current task queue; Linear owns live work and SYSTEM owns deployed revisions.

1. Review and merge donor PR first; standalone remains backward compatible.
2. Review and merge platform PR second. It refuses unsupported donor launches.
3. Separately plan an owner-approved donor and shell release, preserving runtime
   data and existing production configuration. This sprint does not deploy either.
4. Perform the hardware checklist in the sprint findings before claiming device
   acceptance. Repository revision alone is not a deployed release.

Cloud tests require no Pi. Each repo has standalone CI; the full two-private-repo
browser harness requires explicit local checkouts. Automatic coordinated CI needs
a narrowly scoped read credential or artifact delivery; none is introduced here.
