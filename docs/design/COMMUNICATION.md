# Communication as a platform capability

Status: **PROPOSED (2026-09-24).** Design only; no backend change. A frontend-only prototype of the
default HUD exists: `experiments/party-service/prototypes/hud-chat.html` (branch
`experiment/party-service`). Product rules: `PARTY-PLATFORM.md`; words and tone: the owner's
AVRANA-EXPERIENCE contract (a feature is done when it is understandable, responsive, consistent,
accessible and graceful — not when it merely works).

> **Checked 2026-10-06 (AVR-53).** The "Party service" facts under "What exists today" and the
> transport in Layer 1 do not match Party Core as built: it has no event list, no system
> messages and no Server-Sent Events. The [messaging proposal](MESSAGING.md)
> records what exists and proposes the transport, identity and limits; where the two
> differ, read the proposal. Layers 2 to 4 here remain proposed direction.

## The idea

Every game gets ordinary **Party chat** for free. A game may **declare a policy** that narrows or
reshapes it (teams, read-only phases, rate limits, no chat at all) and may add **game-native
actions** (a clue, a vote, an accusation) that are *not* chat. The platform owns identity, delivery,
safety and the default presentation; the game owns rules and its own actions.

Four layers, kept separate so each can change without the others:

| Layer | Owns | Does not own |
|---|---|---|
| 1. Transport and state | channels, append-only message log per channel, delivery, history window | who may speak |
| 2. Authorization and policy | who can read / write which channel, when; rate limits; mutes | how it looks |
| 3. Presentation | HUD, full feed, composer, notifications, accessibility | rules |
| 4. Game-native actions | clues, votes, accusations — the game's protocol and its UI | ordinary chat |

## What exists today (facts; see the survey in this doc's history)

- **Party service:** server-generated **system messages only** (join/leave, host changes, game
  start/end), kept in the party's event list, the last 10 sent in every per-viewer view over
  Server-Sent Events; rendered as text. Identity is strong: a server-issued device token resolves to a
  presence whose display name is de-duplicated and **authorizes nothing**.
- **LAN Games hub chat** (games fork `core/chat.py`): one global WebSocket room, 60-message ring buffer,
  6 messages / 4 s per socket, 400-character cap, fixed reaction set, media only from its own upload
  path, rendered with `textContent`. Weak spots: the **name is client-declared** (spoofable) and any
  client may **clear the room** for everyone. No per-game or per-team channels.

Reusable: LAN chat's limits and ring buffer; the party's identity, provenance (`system` vs human)
and text-only rendering. Not reusable: client-declared names, unauthenticated `clear`.

## Layer 1 — transport and state

- **Channel** = `party` (default), and later `team:<id>`, `spectators`, `dm:<a>:<b>`, `game:<id>`.
- **Message** = `{id, channel, at, from: presence_id | "system", text, kind: "chat" | "system"}` —
  `from` and the display name are stamped **by the server** from the sender's presence; clients never
  send a name. `kind` gives provenance (system messages can never be forged by a client: the
  existing "SYSTEM" rejection generalises).
- **History:** in memory, per channel, a ring of 100 messages for the party's lifetime; a
  reconnecting phone gets the recent window in its first snapshot. No persistence (offline-first,
  nothing to leak after the party).
- **Transport: the existing party transport is enough for v1.** POST to send, the party's
  Server-Sent Events stream to receive. One change: chat must not ride the full-view resend (today
  every change re-serialises the whole view); add an **incremental `event: chat`** carrying only new
  messages. SSE through the same front door keeps one origin, one identity cookie, no new port.
  *(2026-10-02: "one origin, one identity cookie" is the current implementation assumption only.
  [ADR 0013](../adr/0013-party-and-game-browser-origins.md) supersedes it as architecture: Party
  surfaces keep the Party origin and its cookie; game pages move to a game origin that does not
  carry it. Chat rendered on Party surfaces is unaffected.)*
  A WebSocket (or anything heavier: Socket.IO, Matrix, XMPP, Centrifugo) is **not justified** until
  there is a need for typing indicators or reactions at game speed; revisit then, measured.
- **Inside games:** the PS1 page already keeps a party event stream open (to follow navigation), so
  it can render party chat without the game server knowing chat exists. LAN Games modules get the same
  via the planned `party.js` follow client.
  *(2026-10-02: this relies on the game page sharing the Party origin and cookie. Under ADR 0013
  a game page cannot open the Party's stream as the member. How Party chat appears during a round
  — and by which cross-origin mechanism — is not chosen here; it belongs to AVR-226. LAN Games
  modules are the legacy runtime
  ([ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md)), not the model for new
  games.)*

## Layer 2 — authorization and policy

- Default policy: every present player and spectator **reads and writes** `party`; 1 message / 1.5 s
  and 6 / 10 s per presence (server-enforced; the UI explains in plain words: "Slow down a little.");
  200 characters; text only in v1.
- A game may declare, in its manifest (future field `communication`, added only when the first game
  consumes it):
  ```json
  "communication": {"default": "party",
    "roles": {"spymaster": {"party": "read"}, "spectator": {"party": "write", "team:*": "none"}},
    "phases": {"clue": {"party": "read"}}, "rate": {"spectator": "1/10s"}}
  ```
  and may switch phases at run time through the party contract (an event the game emits with its
  grant; provenance from the grant, never from the game's claim — `GAME-INTEGRATION.md` §3.2).
- The server enforces; the client only presents the result ("You're the spymaster: you can read your
  team's chat"). A refused send gets a sentence, never an error code.
- Moderation v1: the host can mute a presence in `party` (kick ≠ ban stays as decided); clearing
  history is host-only (fixes the LAN Games gap).

## Layer 3 — presentation (default Party chat)

- **HUD:** the 2–4 most recent messages, bottom-left, over the game but never over its centre; each
  fades after ~5 s (instant with reduced motion); tapping the HUD opens the feed. On the PS1 page the
  HUD must sit outside the picture where possible (the side gutters in landscape).
- **Feed:** a sheet with the full window and a composer; closing returns straight to the game.
- **System messages** look different (★, italic, a distinct colour) and never carry a player's name
  slot; **human messages** show the sender's name in their avatar colour — never colour alone.
- **Accessibility:** the feed is a `role="log"` live region (polite); HUD lines are `aria-hidden`
  (the log announces them once); 44 px targets; text scales with the phone.
- A game can replace the presentation (its own chat panel) while keeping layers 1–2.

## Layer 4 — game-native communication actions

Clues, votes, accusations, emotes are **game actions**: sent over the game's own protocol, validated
by the game's rules, rendered as game elements. They may *also* post a system line ("Ana gave the
clue."), but they are never chat messages and chat policy does not govern them.

**Codenames, worked through:** the spymaster's clue is a game action (one per turn, validated,
pinned on the board); during the clue phase the spymaster's `party` access is `read`, the opposing
team keeps `write` at `1/10s`; the composer is replaced by "You're the spymaster: give your clue
with the Clue button. You can read your team's chat." (all three shown in the prototype).

## Phasing

1. **v1 (next, small):** Party chat on Party Home and the PS1 page — layers 1–3 with the default
   policy, incremental SSE event, HUD + feed from the prototype. Consumers: Party Home, PS1.
2. **v2:** game-declared policy (roles, phases, rate) — only when a native game needs it.
3. **v3:** team channels, spectator channel, direct messages — when a game needs teams.

## Open questions

Is chat on by default for spectators (the product lock says late joiners spectate; can they talk)?
Does the TV screen presence show the HUD? Profanity filtering (local word list, off by default)?
Message retention after a party ends (proposal: none)?
