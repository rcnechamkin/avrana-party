# LAN Games provider boundary

Status: audited 2026-09-26 before implementation. Review branch only; not deployed.
Base: Avrana 459d4cd, games fork 2cf4831. Builds on merged assimilation PR #5.

## Concrete ownership audit

| Area / actual implementation | Classification / boundary |
| --- | --- |
| games/registry.py REGISTRY and EXTERNAL | Provider-owned authoritative generic title, icon, blurb/tagline, category, counts, solo, TV and art. Venue overrides are local customization, not canonical metadata. |
| server.py static mounts; WORDCLASH wc_app | Provider-owned /games/<slug>/ and game WebSocket routes. All visible entries have pages; hidden template is excluded. EXTERNAL WORDCLASH is actually mounted in-process. |
| Avrana contracts, appliance grants, catalog and capability evaluation | Canonical Avrana. Metadata describes titles; appliance alone grants installation and paths. BLUFF already has ID bluff and an explicit private-hand contract; do not create lan-bluff. |
| web/party/lib/profile.js and Hub.identity; WORDCLASH localStorage getters | Compatibility adapter: same wc-token/name/avatar/pfp. No copied profile or second token. Token is legacy resume/upload/chat credential, not implemented future device identity separation. |
| /api/avatar, core/avatars.py, data/avatars | Provider transport/storage; canonical Avrana profile owns editing. Public hashed WebP paths, x-wc-token header, EXIF stripped. Runtime photos stay out of Git. |
| lg-favorites, lg-recent, lg-play-total in hub.js / profile.js | Canonical Avrana library backed by existing lists. Legacy LAN slug is the compatibility storage identity for canonical lan-<slug>; other IDs use avrana:<id>. Known aliases must collapse without losing unknown entries. History means opened, not verified play. |
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

## Decisions to implement

Avrana owns discovery, launch identity, global navigation, profile, library and Party
Chat. LAN Games owns game-specific rules, lobbies, hands, controls and assets.
Standalone / remains a compatibility/dev entry, not a second canonical product.
Integrated launch uses a versioned non-secret URL marker, advertised by the donor
API. The shell must explain an unsupported donor rather than silently entering its
old global UI. Return is fixed /party/ on the same origin, resolving to the canonical
https://party.avrana.net/party/ in production; no arbitrary return URL is accepted.

HTTP/IP/.local profiles remain separate origins; no unsafe storage recovery.
Existing legacy identity authorization and chat clear semantics remain debt.
Authoritative roster/session state, Party Home, per-game chat and PS1 execution
promotion are outside this sprint.
