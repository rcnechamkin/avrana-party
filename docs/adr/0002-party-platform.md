# ADR 0002 — Avrana Party is a party platform; games consume party services

Status: accepted (direction) · proposed (mechanisms) · Date: 2026-09-24
Design reference: `docs/design/PARTY-PLATFORM.md`

## Context

Avrana Party grew as separate runtimes on one Raspberry Pi: LAN Games (28 browser games, live),
the Avrana Party Games fork with the native game BLUFF (in development), the Gauntlet II arcade
stream (live) and the PS1 shared stream (blocked on power). Each owns its own notion of a player:

- LAN Games keys every game, chat and avatar by a `wc-token` that the **browser can mint itself**;
  names and avatars live only in the browser. Any ready player can start a game; anyone can change
  settings or clear chat. Each phone navigates into each game on its own, and a finished game
  returns to *that game's* lobby.
- BLUFF adds presence states, reconnect grace, autopilot and bounded spectators, inside the game.
- The PS1 stream mints its own slot tokens with a 30 s grace period and spectators.
- The arcade has no identity at all: first free slot, freed on disconnect.
- PS1 is served from a different origin (`10.42.0.1:8198`) than everything else.

The owner's product direction (2026-09-24) is that Avrana Party is **one party** that moves
between games — *"the game may change; the party does not"* — and that Avrana owns identity,
session, social, progression, navigation and player management, while games consume them.
Continuing per-game identity would multiply exactly the systems the product is meant to unify.

## Decision

1. **Avrana Party is a party platform.** A persistent *Party* (members, host, seats, current
   game, queue, teams, chat) outlives any single game. Navigation is party-synchronized.
2. **Identity is layered, not one "player" object:** Device (recognized browser) ≠ Profile
   (persistent human, optional) ≠ Presence (in this party) ≠ Seat (in this game) ≠ Role (Host /
   Player / Spectator; Admin is separate) ≠ Persona (display identity). Games receive a **game key
   and persona** (ADR 0003), never a device token or profile secret.
3. **Guest-first, browser-first, offline-first.** Profiles are optional; the captive portal is a
   convenience, not a dependency; nothing needs the internet.
4. **Admin ≠ Host.** The System Admin is a PIN-protected appliance role; the Party Host is a
   temporary, transferable party role with no system powers.
5. **Games integrate through a small, optional contract**, not a framework: a capability manifest,
   a seat-ticket handshake (first WebSocket message), an event sink with provenance, and a tiny
   `party.js` that follows party navigation. A game with none of these keeps working as today.
6. **Provenance on every stat.** `authoritative_game_event` vs `platform_observed` (vs
   `manually_recorded`, if ever). Emulated games produce no results unless a per-game adapter is
   added; participation alone never counts as a win.
7. **Not a universal gameplay framework.** Rules, state, rendering and netcode stay with each game.
   Platform contracts grow only when two consumers need them.

Proposed mechanisms (to be confirmed when built, see ROADMAP N5): a separate small party
service on the same origin as everything else (e.g. `/party/`), a server-issued device cookie,
top-level navigation driven by `party.js` (not an iframe shell, not a single-page rewrite of games),
a thin bridge in the LAN Games fork at the connect handshake and the lifecycle push, and manifests
derived from the existing LAN Games registry.

## Amendment (2026-09-24, same day): locked product decisions

The owner closed several open questions; they refine, not reverse, the decision above:

- **One appliance = one party** (not a multi-tenant server).
- **TV optional**; a game may declare `tv_required` / `tv_optional` / `no_tv_needed`.
- **The host is disposable:** reconnect grace, then simple succession; voluntary transfer; a
  returning former host does not take the role back.
- **Late joiners spectate by default**; games opt into more through their manifest.
- **Physical seating is not a platform concept.**
- **Open installation, no store** (no marketplace, payments, reviews, DRM). Trust for third-party
  games is a separate future design (`docs/design/GAME-INSTALLATION.md`).
- **No app and no captive portal required**; both may exist only as optional conveniences.
- **The phone is not just a controller**: native games should use each player's private screen.
- **V1.0 is for the owner**, to prove the experience; commercialization comes after that proof.

Identifiers and what they authorize: `docs/adr/0003-ids-and-keys.md`. Lifecycle rules:
`docs/design/PARTY-LIFECYCLE.md`.

## Consequences

- New games must not build their own login, profile store, chat, reconnect, team or spectator
  systems; they wait for or contribute to the platform versions.
- BLUFF's identity code is left alone until after its real-phone playtest (ROADMAP N2), so the
  playtest measures the game, not a moving platform.
- A single origin requires an nginx change on a live system; it needs an explicit proposal and
  owner approval (ROADMAP N3).
- LAN Games' client-minted token must eventually be replaced by a server-issued device token; the
  migration has to keep the live service working.
- The platform adds at least one process (the party service) on a Pi with a power problem; it
  must stay small.

## Alternatives considered

- **Status quo (per-game identity).** Rejected: every new game re-implements lobby, reconnect and
  identity, and cross-game party features (teams, history, voting) become impossible.
- **Build the party layer inside the LAN Games server.** Simpler (no cross-process tickets), but the
  party would die with that process and the arcade/PS1 would depend on it. Kept as a fallback.
- **An iframe shell that hosts every game.** Rejected for now: games assume they own the page
  (safe areas, fullscreen, audio unlock, iOS gestures, service worker). May return for overlays
  such as chat on same-origin games.
- **A single-page app that absorbs every game.** Rejected: a rewrite of every game.
- **Cloud accounts.** Rejected: offline-first, no setup friction.
