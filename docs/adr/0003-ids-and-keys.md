# ADR 0003 — Identifiers, credentials and what they authorize (F1)

Status: accepted as invariants · proposed for formats and storage · Date: 2026-09-24
Context documents: `docs/design/PARTY-PLATFORM.md` §5 (concepts), `docs/adr/0002-party-platform.md`.

## Context

Today every runtime uses one string for everything:

- **LAN Games** keys each game, chat and the avatar store by a `wc-token` that the browser can
  mint itself and the server accepts if it is well-formed. That token is at once the device, the
  person, the player key and the reconnect credential.
- **PS1** mints a per-slot token server-side and uses it as the reclaim credential.
- **The arcade** has no identifier at all: first free slot.

The party platform (ADR 0002) separates Device, Profile, Presence, Seat, Role and Persona. That
only works if the *keys* are separated too, and if it is written down which key may authorize
what. Getting this wrong is expensive later: every record, stat and game session would carry the
wrong key. This ADR fixes the **invariants** and leaves formats and storage open.

## Decision

### 1. Three kinds of value, never mixed

| Kind | Examples | Secret? | May authorize anything? |
|---|---|---|---|
| **Identifier** (stable, opaque, server-issued) | `party_id`, `device_id`, `profile_id`, `presence_id`, `seat_id`, `game_session_id`, `team_id` | No | **No.** Knowing an id grants nothing. |
| **Credential** (bearer secret or knowledge factor) | device token, seat ticket, game key, pairing code, admin session, profile PIN, admin PIN | **Yes** | Yes, and only what the table in §3 says |
| **Display value** | display name, persona, avatar, "Player 3", controller / slot number, team colour | No | **Never** |

### 2. Invariants

1. **device token ≠ device_id ≠ profile_id ≠ presence_id ≠ seat_id ≠ controller slot number.**
   They may be *mapped* to each other; they are never the same value and never derived from
   each other.
2. **Identifiers are opaque and random** (e.g. 128-bit random or UUIDv4). They are never derived
   from names, MAC addresses, IP addresses, timestamps, device fingerprints or other ids.
3. **Authorization only through credentials resolved on the server.** A client may *mention* an
   id (e.g. "I vote for seat X"); the server decides who the client *is* only from a credential.
   Display values never authorize.
4. **Secrets never leave their lane.** Credentials never appear in a URL path or query string
   (a short-lived pairing code in the URL *fragment*, which browsers don't send, is allowed), logs,
   exports, other players' payloads, TV views, or game servers that don't need them. The device
   token never reaches a game server: its cookie is scoped to the party path and nginx strips
   cookies on game locations. The server stores only a hash of long-lived bearer secrets (device
   token) and a slow hash of PINs.
5. **Games receive a game key and a persona, nothing else of identity.** The game key is an
   opaque **secret** scoped to one (game session, participant): it is only ever sent to that
   participant's own client, because in LAN Games the token a client presents *is* its
   credential. Seats are bound where the game binds them (LAN Games at its countdown; PS1 and the
   arcade at connect time) and reported back as `seat_id`. For party-launched sessions a game must
   **not** accept arbitrary client-supplied tokens (the legacy path); it accepts a seat ticket and
   uses the game key the platform binds to it.
6. **One active party per appliance.** `party_id` still exists (history, events, recaps name the
   party), but at most one party is active at a time. There is no party selector and no
   multi-tenant routing.
7. **Records reference identifiers, never display values,** and every stat/event carries
   provenance (`authoritative_game_event` | `platform_observed` | `manually_recorded`).
8. **Guests are presences without a profile.** Their records reference `presence_id`; promoting a
   guest to a saved profile *links* those records to the new `profile_id` without rewriting them.
9. **Merges never move credentials.** A merged profile keeps its id with a `merged_into` pointer;
   its devices, trust links and PIN are dropped, not transferred.

### 3. What each value is, and what it authorizes

| Value | Scope | Lifetime | Issued by | Authorizes | May appear in |
|---|---|---|---|---|---|
| `device_id` | appliance | until the device is forgotten/revoked | platform | nothing | admin UI, device lists |
| **device token** (cookie) | one browser | long (e.g. ~400 days), revocable | platform | "this is device X": offer its trusted profiles, resume its presence | cookie only (HttpOnly, party path only; never sent to game servers) |
| `profile_id` | appliance | until deleted or merged | platform | nothing | records, exports |
| **profile PIN** (optional) | one profile | until changed | the person | claim the profile on an untrusted device | never stored in clear |
| `presence_id` | one party | the party (whether it survives a reboot is OPEN) | platform | nothing | party state, records |
| `party_id` | appliance | the party | platform | nothing | records, recaps |
| `game_session_id` | one launch of one game | until the game ends | platform | nothing | events, records |
| `seat_id` | one game session | the game session | platform | nothing | party state, events |
| **seat ticket** | one presence → one game (audience `game_id`) | short (seconds to minutes), single use | platform | "this connection is presence P in game G" | first WebSocket message only |
| **game key** | one (game session, participant) | the game session | platform (via the bridge) | the game's own per-player key | that participant's own client and the game server only |
| controller / slot number | one game | the game session | the game | nothing (it is a *mapping* target) | anywhere |
| **pairing code** | one profile → one new device | ~3 minutes, single use | a trusted device's request | link a new browser to a profile | URL fragment or typed; never logged |
| **admin session** | appliance | short (idle ~15 min, max ~2 h) | admin PIN login | admin actions only | cookie on the admin path only |
| **admin PIN** | appliance | until changed | owner at first setup | open an admin session | never stored in clear |

Host is **not** a credential: it is a role flag on a presence, checked server-side on every host
action. Spectator is the absence of a seat.

### 4. Relationships (cardinality)

```
device *──* profile            (trust links; many devices per profile, many profiles per device)
device 1──* presence           (over time; within one party a device normally has one presence,
                                a hot-seat party setting may allow more)
profile 0..1──* presence        (a guest presence has no profile; a profile has at most one
                                presence in the active party)
presence *──1 party             (exactly one party)
presence 0..1──* seat           (at most one seat per game session; none = spectator)
seat 1──1 game_session          (seats are per game session; the party's *seating* carries forward)
seat 0..1──1 controller slot     (a seat maps to at most one game slot; hot-seat games map several
                                presences to one slot and cannot attribute results)
presence 0..1──1 team           (per party)
```

### 5. Mapping today's tokens

| Today | Becomes |
|---|---|
| LAN Games `wc-token` (client-minted; device + person + player key + reconnect; also keys avatar photos and chat identity) | Replaced for party-launched sessions by a per-(session, participant) **game key** issued through the bridge, which also maps photo and chat keys; the device role moves to the platform's device token. Standalone (non-party) play keeps working as today until the fork cutover. |
| PS1 slot token (server-minted, reclaim credential, 30 s grace) | The **seat ticket** / game-key pair; PS1's `claim()` validates a ticket instead of minting. |
| Arcade (none: first free slot) | Accepts a seat ticket (first message) and maps seat → controller slot. |
| LAN Games player name (client-asserted) | A **persona** set through the platform; still a display value. |

## Consequences

- The fork bridge (implemented for Party sessions, ADR 0006) must disable the arbitrary-token path for party-launched
  sessions, or a client could present someone else's game key as its "token".
- Seat tickets carry an audience (`game_id`). Sandboxed third-party games verify them with a
  per-game key or a per-game unix socket, never one key shared by every game (which would let any
  game mint tickets for any other). **Built-in LAN Games modules share one process**, so per-game
  keys add nothing there: any module could read any game's keys. That is acceptable only because
  built-in code is trusted; the process is the real boundary.
- Device tokens are free (a private tab is a new device), so device-level identity can't stop one
  person holding several presences. Kicks are not bans, and votes are advisory (the host decides);
  admission control belongs to the Public/Demo preset (`docs/design/PARTY-PLATFORM.md` §7).
- Games that persist anything about players must key it by `seat_id`/`presence_id` handed to them
  as opaque strings, not by names or their own tokens.
- Stats/achievements stay attributable after renames, persona changes, guest promotion and merges.
- Nothing here chooses a database, a table layout or an id encoding.

## Deliberately open

Exact id encoding (UUID vs base32 random) · storage (SQLite tables, JSON) · device-token
migration from `wc-token` · whether presences and the party survive an appliance reboot ·
exact host-succession policy · hot-seat attribution.

## Amendment (2026-10-02): single-use tickets, profile principal, symmetric capabilities

Dated clarification; the invariants and the historical token mapping in §5 are unchanged.

- **Single-use remains the accepted invariant for seat/session tickets** (§3: "short … single
  use"). ADR 0006's `avrana.party-session/v0` temporarily implemented *replayable* bearer tickets
  within their 120 s lifetime and recorded that as a deferral. AVR-52 closes that implementation
  gap; it is not a new decision.
- **Reconnect obtains a fresh ticket.** A ticket is spent on admission; a reconnecting browser
  fetches a new one for the same member and session, which carries the same participant id.
- **Profile is an optional, durable, server-side person principal.** Before Avrana stores
  persistent information about a person it must have an explicit Profile/People entity
  (`profile_id`, §3). Party live identity (device, presence) and the durable Profile remain
  separate concepts; invariant 8 (guests are presences without a profile) stands.
- **Display name and avatar are never identity authority.** The browser-stored name/Gaze avatar
  that ADR 0011 uses for automatic presence is a display value (§1), not a Profile and not a
  durable human identity; nothing persistent may be keyed by it.
- **HMAC remains correct for Party/game session capabilities.** Tickets and session messages
  stay symmetric, per-game-keyed HMAC capabilities on one appliance (ADR 0006 D5). Asymmetric
  cryptography is not being introduced for ordinary session tickets.
- **Public-key cryptography is reserved for package and update provenance**, where a signature
  that outlives the appliance's secrets has actual value (GAME-INSTALLATION, when built).
- **§5 mapping, first row:** "Standalone (non-party) play keeps working as today until the fork
  cutover" is historical. The cutover happened on 2026-09-27, and
  [ADR 0014](0014-native-games-isolated-lan-games-retired.md) retires standalone LAN Games play and
  `wc-token` player admission instead of preserving them.
- **Consequences, second bullet:** per-game keys "add nothing" for built-in LAN modules only
  while they share a process. Under ADR 0014 each native game is its own process with its own key,
  so the per-game key becomes a real boundary for built-in games too.
