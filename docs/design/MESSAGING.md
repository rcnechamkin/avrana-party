# Party-owned messaging (proposal)

Status: **PROPOSED (2026-10-06) · not accepted · not implemented · not deployed**
This is the [AVR-53](https://linear.app/avranakern/issue/AVR-53/define-avrana-platform-messaging-architecture-and-ownership)
proposal. The owner allowed it to be drafted before the
[AVR-27](https://linear.app/avranakern/issue/AVR-27/four-human-offline-bluff-acceptance) four-human
night; it may not be accepted, and
[AVR-54](https://linear.app/avranakern/issue/AVR-54/build-party-owned-messaging-service-and-shared-player-surfaces)
may not start, until the AVR-27 findings are reconciled with it in writing (the section
"Reconciliation with AVR-27" below is empty on purpose) and the owner accepts it. On
acceptance it becomes ADR 0017; until then it is a design proposal with no authority. Context:
[ADR 0006](../adr/0006-party-session-protocol.md), [ADR 0011](../adr/0011-party-console-model.md),
[ADR 0012](../adr/0012-limited-mode-party-survives-https-loss.md),
[ADR 0013](../adr/0013-party-and-game-browser-origins.md),
[ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md), the
[2026-10-02 review](../findings/2026-10-02-architecture-review.md) and
[COMMUNICATION](COMMUNICATION.md), whose transport section this would replace.

## Context: what is true today

Checked in source on `main` and in Games `origin/main` on 2026-10-06.

- **Party Core has no messaging.** There is no message or event list in a Party, no system
  lines, and no Server-Sent Events or WebSocket. Phones read state through one versioned long
  poll (`GET /party/api/state?since=V&wait=S`) that returns the whole per-viewer view on every
  change. COMMUNICATION's "what exists today" says otherwise for the Party service; that part of
  it never matched Party Core as built.
- **The shell's chat is the legacy Games chat.** The drawer opens `wss://…/chat/ws` on the Games
  runtime. The sender is a browser-minted `wc-token` and a name the browser declares, so a chat
  name can differ from the Party roster name and can be chosen to imitate someone. Any socket can
  clear the room for everyone. Rate limits are per socket and reset on reconnect.
  ([Review](../findings/2026-10-02-architecture-review.md): "any client can clear chat",
  "client-declared name and an unauthenticated clear".)
- **The Chat tab depends on the runtime that is retiring.** It is offered only while the Games
  runtime answers `/api/games`. [ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md) says
  chat needs a Party-owned replacement or a decision to drop it before that runtime can stop.
- **Identity is already strong in Party Core.** A server-issued device credential resolves to a
  member (`member-…`) whose name Core cleans, de-duplicates and never uses to authorize.
- **Core's bounds are small and deliberate.** One lock, one thread per held poll, at most 64
  held polls, 8 KiB request bodies, no rate limit on any route, no cap on members.
- **The review warned about the obvious shortcut.** Putting messages in the view makes every
  message re-send every member's whole view: traffic grows with members squared.
- **A game page has no Party credential.** It sees a closed, pinned bridge view with no roster
  and no messages ([ADR 0013](../adr/0013-party-and-game-browser-origins.md)).

## Decision (proposed)

### 1. Ownership

Party Core owns messaging: who the sender is, who is in the room, order, history, limits and
system lines. The shell owns how it looks on Party pages. A game owns its rules and its own
in-game actions (a clue, a vote, a taunt that is part of play); those are game protocol, not
Party messages, and never enter the Party room.

A game never receives a device identity, a message store or a second presence system. If a game
is later allowed to shape conversation (decision 9), it declares a policy and Party Core enforces
it.

### 2. One room in v1

Each Party has exactly one room. Every member of the Party may read and write it, whatever their
seat: a spectator of a round is a Party member and speaks in the Party room.

Every message carries `scope: "party"`. Game, team and direct scopes are **deferred**, not
modeled further: they need a consumer first (a team game whose hidden information depends on a
private channel), and then a decision of their own. Nothing in v1 may assume a second scope will
be shaped like the first.

### 3. A message

Party Core builds every field except the text.

| Field | Meaning |
|---|---|
| `seq` | Integer, starts at 1 for each Party, rises by one per message. The order and the cursor. |
| `kind` | `member` or `system`. Set by Core; a client cannot choose it. |
| `scope` | `party`. |
| `from` | `member` only: the sender's member id, resolved from the request's credential. |
| `name`, `avatar` | `member` only: the sender's roster name and face **when it was sent**. A later rename does not rewrite old lines. |
| `text` | `member` only: the cleaned text. |
| `event`, `subject` | `system` only: a code from a closed list and the member it is about. No free text. |
| `at` | Server wall-clock milliseconds, for display only. Never used for order. |

There are no photos, reactions, typing indicators, edits or deletes in v1. Nobody, the Host
included, can clear the room in v1.

### 4. System lines

Core writes a system line for: a member joined, a member left, the Host changed, a member
changed their name, a game started, a game ended. The line is a code and a member id; the shell
turns it into words. It is drawn as system text in its own element, never as a person's words, so
no member text can pass for one.

Presence flips (here, away) are **not** lines: they are frequent, they are already in People, and
a phone that sleeps and wakes would fill the room.

### 5. History and what a returning phone gets

Core keeps the last **60** messages of the Party in memory. The room is emptied when the Party
ends, and a Party Core restart also empties it (the Party itself is memory-only, ADR 0006).
Nothing is written to disk, to `/party/api/status`, to a result or to a log: Core logs that a
message was accepted or refused and why, never its text or the sender's name.

A phone keeps a cursor, the highest `seq` it has shown. On any read it sends the cursor and gets
every held message above it, in order, together with the Party id and the lowest `seq` still
held. That gives three plain cases:

- **Away for a while.** It gets what it missed, up to 60 messages.
- **Away for longer than the room holds.** The lowest held `seq` is more than one above the
  cursor. The shell says earlier messages are gone; it does not pretend the history is whole.
- **The Party ended or Core restarted.** The Party id differs. The shell empties its list and
  starts from 0. It never mixes two Parties' messages.

A phone that joins late gets the same 60. A member who left and rejoins is the same member again
(Core keeps the id); a phone whose Limited credential expired, or that changed mode, is a new
member, and its old lines keep the old name.

Unread is counted by the phone: messages above the highest `seq` it has drawn in an open
drawer. Core stores no read state.

### 6. Send, and delivery on its own long poll

Two routes, both member-authenticated, both on the Full and the Limited listener:

- `POST /party/api/messages` with `{text, client_id}`. The answer is the stored message.
  `client_id` is a random string the phone makes per message; Core remembers the last few per
  member and answers a repeat with the message it already stored, so a retry after a lost answer
  never doubles a line.
- `GET /party/api/messages?after=SEQ&wait=S`. It answers at once when there is something above
  `after`, and otherwise holds, like the state poll, until a message arrives or the wait ends.
  The answer is `{party, first, last, messages}`.

Messages are **not** part of the state view and a message does **not** change the Party's
`version`. A message wakes only the message polls, and each gets only the new lines. This is the
direct answer to the review's members-squared warning.

Both routes pass the same guards as every Party POST and GET (Host, Origin, `Sec-Fetch-Site`,
JSON, 8 KiB) and resolve the member from the credential of the listener that received the
request. A request with no credential, or a credential that is not a current member of the
Party, is refused; unlike the state poll, the message poll has no anonymous form.

The cost is a second held request per phone. It has its own cap, separate from the state poll's
64, so a flood of message polls cannot starve state delivery and the reverse. When the cap is
reached a poll is answered at once instead of held, as today.

**Rejected: WebSocket.** Party Core is a standard-library threaded HTTP server. A WebSocket means
a new dependency or hand-written framing in the service that holds identity, plus an nginx
change, to carry a few short lines a minute.
**Rejected: Server-Sent Events.** It holds one thread per phone for as long as the page lives,
needs the proxy timeouts changed, and a mobile browser that sleeps a tab drops it silently; the
long poll already has reconnect, backoff and a tested bound.
**Rejected: an external chat platform** (Matrix, XMPP, Centrifugo and the others AVR-53 lists).
Each brings accounts, federation or a broker to an offline appliance with one room of a dozen
people for one evening. Nothing found shows the existing model is insufficient.
**Kept as the alternative: one combined poll** (state and messages on one held request, each
answered only when it changed). It saves a thread per phone and costs a change to the state
route's shape. Revisit it only if the Pi measurement in "Proof" shows the second poll is a real
cost.

### 7. Limits

| Limit | Value | Why |
|---|---|---|
| Text length | 1 to 400 characters after cleaning | The shell's input and the legacy chat already use 400. |
| Cleaning | Control characters removed, line breaks become one space, runs of space collapsed, direction-override and direction-isolate characters removed. Joiners and variation selectors are kept (emoji need them). | A line cannot fake a second line, hide text or reverse its neighbours. |
| Rate, per member | 6 messages in any 4 seconds | The legacy number, but counted per member, so reconnecting does not reset it. |
| Rate, per Party | A ceiling across all members | A room of colluding or scripted members cannot exceed it. |
| Renames | A rename counts against the same per-member budget | Otherwise a rename loop writes unlimited system lines. |
| History | 60 messages | The shell and the legacy chat already use 60. |
| Held message polls | Own cap, as in decision 6 | Bounded threads. |

A refused send says why (too long, empty, too fast and when to try again) and stores nothing.
The text is always rendered as text, inside its own direction-isolated element, never as HTML.

A member cap for a Party does not exist today and messaging makes its absence matter more (a
script can mint members, each with its own budget). The per-Party ceiling bounds the damage
here; the cap itself belongs to Party Core hardening, not to this proposal.

### 8. Limited Mode

The same two routes are served on the Limited listener with the Limited credential. There is one
room for the whole Party, whichever way each phone is connected.

Two facts follow and the product must say them, not hide them:

- What a Limited phone sends, and **everything it receives**, crosses the Wi-Fi unencrypted.
  Once one Limited phone is in the Party, every message in the room, including those written on
  Full phones, can be read by another guest on the Wi-Fi.
- Someone who reads a Limited credential off the air can write as that member
  (ADR 0012 already accepts this for every other action).

The Limited notice already says the connection is not private; it must cover messages. Whether
Full phones are told that the room is no longer private is a product decision (below).

### 9. Where it is drawn, and games

This proposal decides the service. It does not decide screens:

- **Party pages.** The drawer's Chat tab reads the Party room instead of the legacy socket.
- **Over a briefing.** The accepted rule today is people only
  ([Game UX contract](GAME-UX-CONTRACT.md) rule 3.2, ADR 0011). The service delivers
  regardless; drawing chat there is a separate owner decision.
- **During a game.** Not in v1. A game page has no credential and the bridge carries no roster
  or messages. Whether the trusted Party layer draws the room over a game, and where, belongs to
  [AVR-83](https://linear.app/avranakern/issue/AVR-83) and
  [AVR-292](https://linear.app/avranakern/issue/AVR-292). This proposal requires only that message
  text and other members' names never reach a game origin through the bridge without that
  decision.
- **Game policy.** A game declaring "no chat in this phase", "teams only" or "spectators
  read-only" is deferred until a game needs it. The rule is fixed now: the game declares, Party
  Core enforces, and no capability word or contract field is added before there is a consumer.

### 10. Retiring the legacy chat

1. Party-owned messaging ships and the drawer uses it. The Chat tab no longer depends on the
   Games runtime answering.
2. From that release the shell opens no `/chat/ws` socket.
3. The legacy chat and its media store retire with the runtime
   ([AVR-222](https://linear.app/avranakern/issue/AVR-222),
   [AVR-228](https://linear.app/avranakern/issue/AVR-228)).

There is no adapter, no bridge between the two rooms and no history carried over. Until step 1
the legacy chat stays as it is and gets no new feature. If the runtime retires first, the product
has no chat for that interval; that order is the owner's choice.

## Threats considered

| Threat | Answer |
|---|---|
| Writing as someone else | The sender is the credential's member; the client sends no name or id. |
| A name that imitates another member or the system | Existing name rules (reserved words, one script, de-duplication); system lines are a separate kind and element; a rename writes a line. |
| Clearing or editing the room | No such operation exists. |
| Flooding | Per-member and per-Party rates, counted on the member; 60-line room; 400 characters. |
| Minting members to multiply budgets | Per-Party ceiling; member cap tracked as Core hardening. |
| Rename spam through system lines | Renames share the message budget. |
| Holding polls to exhaust threads | Separate cap; members only; over the cap a poll is answered, not held. |
| Starving state delivery | Messages do not change `version` and use their own poll and cap. |
| Markup or script in text | Rendered as text only; cleaned of control and direction-override characters. |
| Cross-site send | Same Origin and `Sec-Fetch-Site` guards as every Party POST; on Limited the Origin allow-list is the only guard, as ADR 0012 records. |
| A game page reading the room | No credential on a game origin; nothing added to the bridge. |
| Eavesdropping on Limited | Not preventable; stated to the user (decision 8). |
| Text in logs, status or results | Never written there. |
| A stale phone showing another Party's lines | Party id in every answer; the shell resets on a change. |

Not addressed in v1: harassment between members (no mute, block or report). At one table of
people who know each other this is accepted; it is listed below for the owner.

## Proof required of AVR-54

- Unit: sender comes only from the credential; a client-supplied name, id, kind or `seq` is
  ignored or refused; order; the 60-line window; the gap case; Party end and Party id change;
  `client_id` repeat; each limit and its refusal; rename budget; both listeners; no anonymous
  poll; messages never change `version`; no text in logs.
- Browser, several phones: unread counting, no duplicate after a reconnect, a phone that was away
  gets what it missed, the Chat tab with the Games runtime stopped, Limited and Full phones in
  one room.
- On the Pi with a full table: state delivery stays within its bound while the room is busy.
  This is a measurement, not a simulation.
- Phones (human): the iOS and Android keyboard over the composer, new messages announced
  politely and never over "your turn", largest text, names in other scripts.

## Owner decisions needed before acceptance

1. **Chat over a briefing.** Keep people only (accepted today), or allow the Party room there.
   AVR-53's text and slice 3 of the redesign plan ask for it; rule 3.2 forbids it.
2. **System lines.** The list in decision 4, a shorter one (joins, leaves, Host only), or none.
3. **Limits.** 400 characters and 6 per 4 seconds (legacy, proposed), or COMMUNICATION's 200
   characters and 6 per 10 seconds. History of 60 (proposed) or 100.
4. **Limited Mode.** One shared room with the notice extended (proposed), or no chat on Limited
   phones. And whether Full phones are told when a Limited phone makes the room readable.
5. **Moderation in v1.** None (proposed), or the Host can mute a member.
6. **Photos and reactions.** Dropped in v1 (proposed; the shell shows only "Photo shared"
   today), or kept.
7. **Order of retirement.** Party messaging first, then the legacy chat (proposed), or retire
   the runtime first and accept an interval with no chat.

## Reconciliation with AVR-27

Empty until the four-human night has happened. Before acceptance this section records what the
night showed about how people used chat, names and the drawer, and what in this proposal changed
because of it.

## Consequences

- Party Core gains its first route that stores user-written text and its first rate limit.
- Each phone holds a second request while a Party page is open.
- The shell's Chat tab stops depending on the Games runtime, which unblocks its retirement.
- COMMUNICATION's layers 2 to 4 stay as proposed direction; its transport section and its
  account of what exists are replaced by this proposal if it is accepted.
- Team play with private channels, chat during a game and game policy remain undecided and are
  not made easier or harder by v1 beyond the `scope` field.
