# Game messaging policy: the game declares, Party Core enforces (AVR-55)

- **Status:** proposal, 2026-10-27. Nothing is implemented, and no contract field, capability word or protocol message is added by this document. **Owner decisions required** (section 7).
- **Reads with:**
  - [ADR 0017](../../adr/0017-party-owned-messaging.md) and [MESSAGING](../MESSAGING.md), especially decision 9: "the game declares, Party Core enforces, and no capability word or contract field is added before there is a consumer";
  - [ADR 0006](../../adr/0006-party-session-protocol.md) and `avrana/party/protocol.py` (`avrana.party-session/v0`, the signed game ⇄ party messages and the ticket's `pid` and `role`);
  - `web/party/lib/layer-app.js` (the Party layer draws the Party room over a game: `createPartyChat`);
  - Games `bestguess/docs/EXPERIENCE.md` (what each role may see) and `bestguess/docs/PARTY-LAYER.md` (Best Guess mounts the layer, chat included, on the appliance).

## 1. What is true today

- One room per Party, `scope: "party"`, owned by Party Core. Every member who has not left reads and writes it, whatever their seat (MESSAGING decision 2).
- The Party layer (AVR-292) now draws that room **over a running game**, so chat during a round exists in practice even though ADR 0017 left "chat during a game" undecided.
- A game has no say: no declaration, no protocol message, and the bridge has no message verb. That is deliberate (MESSAGING decision 9). A game page in Full Mode, once ADR 0013 is deployed, cannot reach the message routes at all.

## 2. The first consumer, and the contrast

Decision 9 asks for a consumer before any field. There now is one, and a game that needs nothing:

| Game | What it needs | Why |
|---|---|---|
| **Best Guess** (cooperative clue game, Party layer mounted) | During **writing** and **review**, the Guesser must not read the Party room. The writers may still talk. | EXPERIENCE.md: the Guesser never sees the word or any clue before the guess. A writer typing the word, or a clue, into Party chat, which the layer draws on the Guesser's phone, defeats the round. In the room people can just say it aloud, but the screen should not do it for them. |
| **Coup** (hidden roles, bluffing) | Nothing. | Table talk is the game. Open Party chat is right in every phase. |

So the proof the issue asks for ("at least two contrasting game models") is one restrictive game and one that declares nothing. That also tests "simple games need no custom messaging code".

## 3. Proposal

### 3.1 The game declares a closed vocabulary (manifest, at install)

An optional extension in the game contract, read by Party Core and never granted by a package:

```json
"net.avrana.messaging": {
  "groups": ["guesser", "writer"],
  "policies": {
    "open":   {},
    "quiet_for_guesser": { "guesser": "hidden" }
  }
}
```

- `groups`: up to 8 opaque labels (`^[a-z][a-z0-9_]{0,15}$`). They mean nothing to Party Core and are never shown.
- `policies`: up to 8 named policies. Each maps a group to one of **`open`** (read and write; the default), **`read_only`** (reads, cannot send) or **`hidden`** (neither reads nor sends while the policy holds; the layer says "Chat is paused for this part of the game"). There is no fourth word in v1: no team rooms, no direct messages, no game-written lines.
- Party Core validates the declaration with the contract (`game.validate`). An unknown word, group or policy refuses the contract. A game with no extension is exactly today: one open room.

### 3.2 The game server chooses, by name, during a session (session protocol)

A new signed message `typ: "talk"`, game → party, in the existing `aps0` envelope (`iss` the game id, `aud` "party", `sid` the session):

```json
{ "policy": "quiet_for_guesser", "groups": { "participant-1f…": "guesser", "participant-9a…": "writer" } }
```

- `policy` must be one of the names declared in 3.1. `groups` maps the `pid`s the game already received in tickets for **this** session to declared groups. A `pid` from another session, an undeclared group, or more members than the session has refuses the whole message (Invalid), and the policy in force stays as it was.
- The game sends a new `talk` at each phase change (Best Guess: `quiet_for_guesser` at writing, `open` at reveal). Nothing reloads: the next message poll answers with the new state.
- When the session ends, for any reason, the policy is dropped and the room is open. A Party with no session has no policy.

### 3.3 Party Core enforces; the client is told, never trusted

- Party Core maps `pid` → member through the session's own participants. The game never learns a member id, a name or the room.
- `hidden` for a member: the message poll returns `{"paused": true}` with no lines and no count, and a send is refused (`409 paused`). Lines written meanwhile are **not delivered to that member later**. They are not in history for them, because history is the point of the leak. System lines stay visible, since they hold no member text.
- `read_only`: lines are delivered, and a send is refused (`409 read_only`).
- A member not named in `groups` (a spectator, a late joiner, a member who never took a ticket) is `open`. A game that wants spectators read-only names them.
- The Host has no exemption. A policy cannot reach any other Party, game or session, cannot change who a sender is, and cannot add, edit or remove a line.

## 4. What this keeps from MESSAGING

- The sender is still always the credential's member. The game supplies no text, name or kind.
- The game gets no message verb on the bridge, no room, and no member identity.
- Limits, cleaning, order and system lines are unchanged.
- In Limited Mode the policy is enforced the same way. Eavesdropping on plain HTTP was never preventable, and that stays stated.

## 5. Negative tests required before anything ships

| # | Test |
|---|---|
| N1 | A `talk` naming an undeclared policy, an undeclared group, a `pid` from another session, or a game id other than the session's is refused, and the policy in force is unchanged. |
| N2 | A `talk` with a bad MAC, a replayed nonce or an expired `exp` is refused (the existing protocol rules). |
| N3 | A `hidden` member's message poll carries no line, no count and no name written while hidden, also after a reload, a new device credential for the same member, and a long poll held across the change. |
| N4 | A `hidden` member's send is refused; a `read_only` member's send is refused; the refusal text says why. |
| N5 | When the policy goes back to `open`, the formerly hidden member receives only lines written after that, plus system lines. Nothing written while hidden is in their history. |
| N6 | A stale subscription (a poll begun before `hidden`, answered after) does not deliver a line written after `hidden`. |
| N7 | Session end, a game Party Core closes as lost (AVR-33 `close_lost_game`), and a game switch all clear the policy. A new session starts open. |
| N8 | A game with no `net.avrana.messaging` behaves byte-for-byte like today (the existing messaging suite, unchanged). |
| N9 | No bridge verb, layer message or game page can read or set the policy (the bridge allow-list test). |
| N10 | A package that declares the extension is validated the same way as a first-party contract, and an install record cannot widen it. |

## 6. Rejected alternatives

- **The game page sets the policy over the bridge.** The page runs on a phone, and a writer's phone could lift the Guesser's restriction. Policy must come from the game server, signed.
- **Per-message filtering by content** (e.g. hide lines containing the word). Party Core would have to learn the secret, and fuzzy matching leaks anyway.
- **Team and direct rooms now.** No consumer has them (MESSAGING decision 2). The vocabulary in 3.1 leaves room for a later `room` word without changing `open | read_only | hidden`.
- **Pausing chat for everyone.** Coup and most games want table talk, and Best Guess writers benefit from it.

## 7. Owner decisions

| # | Decision | Recommendation |
|---|---|---|
| D1 | Accept Best Guess's Guesser leak as the decision-9 consumer that unlocks the first field? | Yes |
| D2 | Is the vocabulary `open | read_only | hidden` per declared group, with no rooms, enough for v1? | Yes |
| D3 | Should lines written while a member was `hidden` stay out of that member's history for good (N5)? The alternative is to deliver them when the policy lifts. | Out for good: delivering them later is the leak |
| D4 | The policy travels as a new session-protocol message `talk` (a protocol addition: older games never send it). Approve the addition to `avrana.party-session/v0` as an optional message, or require a `v1`? | Optional v0 message, vectors added |
| D5 | Order: implement after ADR 0013 is deployed (so no game page can reach the message routes), or now? | After ADR 0013 for third-party games; first-party Best Guess may go first |
