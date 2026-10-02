# LAN Games assimilation

Status reconciled 2026-10-01: **implemented and merged** (Party PR #5), deployed with the shell;
see [SYSTEM](../SYSTEM.md). The parts audit below preserves the pre-implementation inventory.
ADRs 0006–0011 subsequently add Party authority and console behavior; their contracts govern
current flow. ADR 0011 is merged source with deployment/phone proof pending AVR-212.

LAN Games is legacy MVP infrastructure undergoing assimilation into Avrana Party.
It is not an independent product boundary. New cross-game identity, profile, chat,
presence, favorites, history, navigation, and catalog functionality belongs to Avrana Party.
LAN Games supplies game pages and temporarily supplies shared service transports.

## Parts donor audit (before implementation)

Sources: live donor `5da1764b41d32bfb965637a1850344f8f23beb32` (read-only),
games fork `2cf4831064de709feeb31865c5022a3f048e49ef`.
Reviewed registry, server routes, hub.js, hubnet.js, core/chat.py and core/avatars.py.
The live registry has 28 visible built-in titles plus WORDCLASH; the hidden template
is excluded. The fork also has BLUFF, which is not installed on the live donor.

| Piece | Avrana ownership / direct reuse | Temporary boundary / legacy remainder |
| --- | --- | --- |
| Browser game library | Individual entries and validated Game Contracts | Existing /games/<slug>/ clients and game servers remain |
| Metadata | Versioned public metadata snapshot with donor SHA | Live /api/games verifies presence, never grants arbitrary URLs |
| Player filtering / search | Shell uses min/max, title and category | Legacy hub filters remain until its navigation is retired |
| Cards | Avrana cards use the Capability Engine | Legacy art, tilt and game sheets stay on old pages |
| Profile / character | Same wc-token, wc-name, wc-avatar, wc-pfp backing keys | Adapter replaces importing the globally side-effectful hubnet.js |
| Photo / crop | Same /api/avatar store, token header, server EXIF stripping and square WebP | Existing legacy drag/pinch crop stays; shell supplies focused framing controls |
| Favorites / history | Same lg-favorites, lg-recent, lg-play-total store; cross-game ownership | Slugs retained for LAN compatibility; launch history, not verified play/results |
| Presence | Consume existing chat count | Chat connections are not the Party roster, players or seats |
| Lobby chat | Party Chat consumes /chat/ws hello/history/msg/presence | Same process-wide rolling 60-message store; no new backend or persistent store |
| Chat media / reactions | Existing transport remains reusable | Rich uploads, reactions, typing and legacy clear stay out of this focused shell pass |
| Persistence | Existing localStorage and avatar files | No database, account system or new identity authority |

Do not copy the legacy root service-worker registration, global navigation, branding or
profile/chat singleton into /party/. Integrated Games pages already gate legacy global UI via
ADR 0005; ADR 0011 source follows Party location and hides Party chrome during a round.
Keep game-specific controls, rules, private hands and spectator UI; standalone compatibility
retains its own lobby and return controls.

## Identity and chat limits

One local player identity per browser origin, backed by the existing compatibility keys.
This is not authentication, a cloud account, or an authoritative seat/roster.
HTTP and HTTPS localStorage are different origins: this adapter cannot silently recover
a profile from http://party.local or a private IP. Existing profiles on the same HTTPS
origin are retained; an explicit cross-origin export/import remains future work.

Party Chat temporarily uses the donor's singleton channel for this appliance. Its token
travels in the WebSocket hello body or avatar upload header, never the URL. Name/photo
changes reconnect for future messages. Existing messages keep their original authors.
The donor lacks a session-scoped roster and strong authorization (including its legacy
clear command); extracting and hardening this transport is a later task. The shell
does not expose clear or mistake a chat count for Party-wide presence.

## Catalog and PS1 provenance

`contracts/catalogs/lan-games.json` stores sanitized public metadata only. Contracts
are normalized and validated with the existing v0 vocabulary. Appliance grants remain
separate. Snapshot titles require a matching visible live API slug before launching;
an API failure means unavailable, not an invented working game.

PS1 metadata sources inspected read-only:
- `experiment/ps1-title-profiles` at `4b8fa60afecb4868be0816f4b908b752bc33296d`:
  ps1/titles/bomberman.json, ps1/titles/worms.json, ps1/README.md.
- `experiment/party-service` at `59ac8ab7fd8992def20df97042e3cae66686bf9b`:
  experiments/manifests/builtin/ps1-bomberman.json and ps1-worms.json.
- `ps1-emulation` at `21a16c272b0d765592cefb98adf5fe33fb5a92ce`:
  tree inspected for predecessor metadata.

Bomberman Party Edition (SLUS-01189): four streamed controller slots, Multitap port 2.
Worms Armageddon (SLUS-00888): one controller, 1–4 players taking turns.
These are experimental catalog entries without installed grants or launch URLs.
Shared-stream and optional crop Personal Viewport contracts describe requirements;
they do not claim runtime availability or hardware validation. No ROM paths, runtime
implementation or experiment services are imported.

## Validation evidence and subsequent integration

Cloud tests cover compatibility keys, safe photo paths, transport protocol/reconnect,
multiple providers, metadata validation, per-seat capabilities and shell interaction.
They cannot validate real phone chat/photo flows, legacy game joins, PS1 execution,
TV or streaming hardware. No Pi deployment in this sprint.

Providerization has landed; do not repeat the original donor-navigation migration. Party Core
now owns roster/session authority. The chat transport still has legacy authorization/clear debt;
any further extraction has scope, acceptance and sequencing in Linear.

Catalog attribution: [LAN Games notice](../references/LAN-GAMES-NOTICE.md).
Validation: [sprint findings](../findings/2026-09-26-shell-assimilation.md).

Providerization now builds on this completed sprint. See [LAN Games provider boundary](LAN-GAMES-PROVIDER.md) and ADR 0005 for direct launch, canonical library aliases and integration mode. Do not repeat assimilation or introduce parallel stores.
