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

A current-state audit and an adversarial review, each by a session that did not write this
text, were run on 2026-10-06; the second changed decisions 3 to 8 and the threat table.

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
- **The Chat tab depends on the runtime that is retiring.** It is first offered only while the
  Games runtime answers `/api/games`. [ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md)
  says chat needs a Party-owned replacement or a decision to drop it before that runtime can stop.
- **Identity is already strong in Party Core.** A server-issued device credential resolves to a
  member (`member-…`) whose name Core cleans, de-duplicates and never uses to authorize.
- **Membership is open.** Anyone on the Wi-Fi can join and become a member; a request with no
  credential is given one. There is no cap on members and no rate limit on any route. "Member"
  therefore means "a device Core issued a credential to", not "someone the Host admitted".
- **Core's bounds are small and deliberate.** One lock, one thread per held request, at most 64
  held state polls, 8 KiB request bodies.
- **The review warned about the obvious shortcut.** It says not to put chat on the state view:
  every message would re-send every member's whole view (its estimate, not a measurement).
- **Whether a game page can use the Party credential depends on what is deployed.** Under
  [ADR 0013](../adr/0013-party-and-game-browser-origins.md) a game page is on another origin, has
  no credential and sees a closed, pinned bridge view with no roster and no messages. ADR 0013
  is not deployed: today every game page is served from the Party origin, and in Limited Mode
  first-party games stay on it by design (ADR 0012).

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

Each Party has exactly one room. Every member who has not left may read and write it, whatever
their seat and whether they are here or away: a spectator of a round is a Party member and
speaks in the Party room.

Every message carries `scope: "party"`. Game, team and direct scopes are **deferred**, not
modeled further: they need a consumer first (a team game whose hidden information depends on a
private channel), and then a decision of their own. Nothing in v1 may assume a second scope will
be shaped like the first.

### 3. A message

Party Core builds every field except the text. A client cannot supply or change any other.

| Field | Meaning |
|---|---|
| `seq` | Integer, starts at 1 for each Party, rises by one per line of either kind. The order and the cursor. |
| `kind` | `member` or `system`. |
| `scope` | `party`. |
| `from` | The member the line is from (`member`) or about (`system`). |
| `name`, `avatar` | That member's roster name and face **when the line was written**. Both kinds carry them: the shell never looks a line's member up in the roster, which may not hold them yet or any more. A later rename does not rewrite old lines. |
| `text` | `member` only: the cleaned text. |
| `event` | `system` only: a code from a closed list. No free text. |
| `age_ms` | How long ago Core accepted the line, computed by Core when it answers. The appliance has no trustworthy wall clock, so no timestamp is sent and a phone never compares its own clock with Core's. Never used for order. |

There are no photos, reactions, typing indicators, edits or deletes in v1. Nobody, the Host
included, can clear the room in v1.

Two members can show the same name in the room over an evening (a member who left frees the
name). `from` tells them apart; the shell may use it to keep one person's lines visually
together.

### 4. System lines

Core writes a system line when: a member joins the Party for the first time or returns after
leaving, a member leaves, the Host changes (for any reason), a member's name changes, a round
becomes active, a round finishes (ended or abandoned). Nothing else: not setup, launching, a
failed launch, a switch, going home, or presence.

The line is written inside the same Core operation that changes the state, so it cannot be
missing or duplicated; the two polls are independent, so a phone may see the line slightly
before or after the roster changes, and the name on the line makes that harmless. A join by a
member already present and a rename to the same name write nothing (the shell does both
automatically).

System lines are **metered and kept apart from people's words**, because every one of these
events can be driven in a loop by a script (leave and join, a host passed back and forth, a
round started and stopped):

- They live in their own small ring (**20**), so they can never push a person's message out of
  history. `seq` is shared, so the shell interleaves the two rings in order.
- At most **one system line per 2 seconds** per Party. Events inside that interval are counted,
  not listed: the next line carries the count ("and 3 more changes"). The state itself is never
  delayed or refused; only its announcement is.

System lines are drawn as system text in their own element, never as a person's words, so no
member text can pass for one.

### 5. History and what a returning phone gets

Core keeps the last **60** member messages and the last 20 system lines of the Party in memory.
Both are emptied when the Party ends, and a Party Core restart empties them (the Party itself
is memory-only, ADR 0006). Nothing is written to disk, to `/party/api/status` or to a result.
Core never logs a message's text or a sender's name; refusals are counted and logged as a
rate-limited total, not one line each.

Every read and every send names the Party it is for. A phone keeps the Party id and a cursor,
the highest `seq` it has shown. Core answers with every held line above the cursor, in order,
with the Party id and the lowest `seq` still held. The cases:

- **Away for a while.** It gets what it missed.
- **Away for longer than the room holds.** The lowest held `seq` is more than one above the
  cursor. The shell says earlier messages are gone; it does not pretend the history is whole.
- **The Party ended or Core restarted.** The Party id the phone names is not the current one.
  A read is answered from the start of the current room, if the phone is a member of it. A
  phone that is not a member (the usual case after a Party ends) is refused as not a member:
  the shell empties its list, joins as it already does, and starts from 0. A send that names an
  old Party is refused and stores nothing, so a line typed for one Party never lands in the next.
- **A cursor above anything Core holds** is treated as 0. A negative cursor is 0. A cursor that
  is not a whole number is refused.

A phone that joins late gets the same history. A member who left and rejoins is the same member
again (Core keeps the id, and its rate state with it); a phone whose Limited credential expired,
or that changed mode, is a new member, and its old lines keep the old name.

Unread is counted by the phone: lines from other members above the highest `seq` it has drawn in
an open drawer. Core stores no read state. Counting unread means the phone reads while the
drawer is closed.

### 6. Send, and delivery on its own long poll

Two routes, served by both the Full and the Limited listener, for a credential that is a current
member:

- `POST /party/api/messages` with `{party, text, client_id}`. The answer is the stored line.
  `client_id` is 1 to 36 characters of `A-Z a-z 0-9 _ -`, made by the phone per message. Core
  keeps the last 8 per member and answers a repeat with the line it already stored (its `seq`
  alone if the line has left the ring), before any rate check and at no cost, so a retry after a
  lost answer never doubles a line. The same `client_id` with different text returns the
  original.
- `GET /party/api/messages?party=ID&after=SEQ&wait=S`. It answers at once when there is
  something above `after`, and otherwise holds, like the state poll (at most 25 seconds), until
  a line arrives, the Party ends, the member leaves, or the wait ends. The answer is
  `{party, first, last, messages, retry_ms}`; an empty room has `first` and `last` 0. The
  sender's own line comes back here too; the phone merges by `seq`.

Messages are **not** part of the state view, a message does **not** change the Party's
`version`, and neither route counts as presence (only the state poll is the heartbeat). A
message wakes only the message polls, and each gets only the new lines.

What the implementation must hold to, because Core's model makes each a real failure:

- **Its own wake.** The message polls wait on their own condition. On the existing one, every
  message would wake every state poll and every state change every message poll.
- **Nothing slow under the lock.** Appending and taking the slice to send happen under Core's
  lock; building the JSON and writing to the socket happen after it is released. A slow phone
  must never hold the Party.
- **One held message poll per member.** A second one from the same member releases the first.
  Without this a single credential fills the cap. The message polls have their own cap,
  separate from the state poll's 64, so neither can starve the other.
- **No spinning.** When a poll is answered at once because the cap is reached, or with nothing
  new, the answer carries `retry_ms` and the phone waits that long before asking again. (Today's
  state client asks again immediately after any good answer.)
- **Membership is checked again after every wake**, and the answer is built from the current
  Party, never from one that ended while the request was held.

Guards, stated exactly. The send passes every guard a Party POST passes today: Host, Origin,
`Sec-Fetch-Site`, JSON content type, 8 KiB. The read is a GET and, like every Party GET, has only
the Host check and `Sec-Fetch-Site`; over plain HTTP (Limited) browsers send no `Sec-Fetch-Site`,
so there the read is protected by the Host check, the `SameSite=Lax` credential and the absence
of any cross-origin response header. Unlike the state poll, there is no anonymous read.

Refusals have fixed codes: `not_member` (403), `bad_party`, `bad_client_id`, `bad_query`,
`empty`, `too_long` (400) and `too_fast` (429, with `retry_ms`).

**Rejected: WebSocket.** Party Core is a standard-library threaded HTTP server. A WebSocket means
a new dependency or hand-written framing in the service that holds identity, plus an nginx
change, to carry a few short lines a minute.
**Rejected: Server-Sent Events.** It holds one thread per phone for as long as the page lives,
needs the proxy timeouts changed, and a mobile browser that sleeps a tab drops it silently; the
long poll already has reconnect and backoff.
**Rejected: an external chat platform** (Matrix, XMPP, Centrifugo and the others AVR-53 lists).
Each brings accounts, federation or a broker to an offline appliance with one room of a dozen
people for one evening. Nothing found shows the existing model is insufficient.
**Kept as the alternative: one combined poll** (state and messages on one held request, each
answered only when it changed). It halves the held requests and puts messages into the state
route's shape and into the client the bridge shares. Revisit it only if the Pi measurement in
"Proof" shows the second request is a real cost.

Estimated, not measured: with 12 phones a message costs 12 wake-ups and about 8 KB sent in
total on its own poll, against roughly 40 KB if it rode the state view; with 40 phones, 40
wake-ups and about 28 KB against 240 to 400 KB.

### 7. Limits

| Limit | Value | Why |
|---|---|---|
| Text length | 1 to 400 code points after cleaning; the phone counts the same way | The shell's input and the legacy chat use 400. Counting alike stops the phone cutting an emoji in half. |
| Cleaning | Normalized (NFC). Removed: control, surrogate, private-use and unassigned characters; every invisible formatting character except the two joiners; line and paragraph separators and all runs of white space become one space. More than 4 combining marks in a row are dropped. Text with nothing visible left is `empty`. | A line cannot fake a second line, hide or reverse text, look blank, or stack marks over its neighbours. Joiners and variation selectors stay because emoji and several scripts need them. |
| Rate, per member | 6 messages in any 4 seconds, kept on the member | The legacy number, but leaving, rejoining or reconnecting does not reset it. |
| Rate, per Party | 30 messages in any 10 seconds | Bounds what a room of scripted members can make Core do. |
| System lines | 1 per 2 seconds per Party, own ring of 20 | Decision 4. |
| History | 60 member messages | The shell and the legacy chat already use 60. |
| Held message polls | One per member; own total cap | Decision 6. |
| `client_id` memory | 8 per member, 36 characters each | Bounded. |

A refused send says why and stores nothing. The text is always rendered as text, in its own
direction-isolated element that wraps anywhere and clips, never as HTML.

**What these limits do not do.** Membership is open (Context), so a script on the Wi-Fi can
join many times. The per-Party rate then protects Core, not the conversation: such a script can
use the whole allowance and keep everyone else from being heard. Stopping that needs a limit on
joins and a cap on members, which Party Core lacks today for reasons that go beyond messaging
(every join also grows the roster every phone is sent). This proposal names that as a
**prerequisite for a table of strangers** and an accepted risk for a table of friends; it is the
owner's call which v1 is (below).

### 8. Limited Mode

The same two routes are served on the Limited listener with the Limited credential. There is one
room for the whole Party, whichever way each phone is connected.

Three facts follow and the product must say them, not hide them:

- What a Limited phone sends, and **everything it receives**, crosses the Wi-Fi unencrypted.
  Once one Limited phone is in the Party, every message in the room, including those written on
  Full phones, can be read by another guest on the Wi-Fi. Because anyone on the Wi-Fi can join
  over Limited when it is enabled, the room is only as private as the Wi-Fi.
- Someone who reads a Limited credential off the air can write as that member
  (ADR 0012 already accepts this for every other action; words under a friend's name make it
  more tempting).
- In Limited Mode first-party game pages share the Party origin, so a game page's script could
  read and write the room as the member. ADR 0012 accepts that trust for first-party games; it
  is one more reason third-party games are not offered there.

The Limited notice already says the connection is not private; it must cover messages. Whether
Full phones are told that the room is no longer private is a product decision (below).

### 9. Where it is drawn, and games

This proposal decides the service. It does not decide screens:

- **Party pages.** The drawer's Chat tab reads the Party room instead of the legacy socket.
- **Over a briefing.** The accepted rule today is people only
  ([Game UX contract](GAME-UX-CONTRACT.md) rule 3.2, ADR 0011). The service delivers
  regardless; drawing chat there is a separate owner decision.
- **During a game.** Not in v1. Whether the trusted Party layer draws the room over a game, and
  where, belongs to [AVR-83](https://linear.app/avranakern/issue/AVR-83) and
  [AVR-292](https://linear.app/avranakern/issue/AVR-292). This proposal requires only that no
  message verb, message text or other member's name is added to the bridge without that
  decision. The bridge frame today accepts five verbs and reads only the state route, so a game
  page cannot make it read or send messages; it must stay so.
- **A game page and the credential.** Once ADR 0013 is deployed, a Full Mode game page has no
  credential and cannot reach these routes. Until then, and in Limited Mode, a page served from
  the Party origin can. That is the existing trust in first-party pages, not a new one, and it
  is a reason to deploy ADR 0013 before any third-party game.
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
| Writing as someone else | The sender is the credential's member; the client sends no name, id, kind or `seq`. |
| A name that imitates another member or the system | Existing name rules (reserved words, one script, de-duplication); system lines are a separate kind and element; a rename writes a line. A name freed by a member who left can be taken: `from` differs. |
| Clearing or editing the room | No such operation exists. |
| Flooding by one member | Per-member rate kept on the member; 400 code points. |
| Flooding by many minted members | Per-Party rate protects Core. It does **not** keep the room usable; that needs a join limit and member cap (decision 7). |
| Pushing people's words out with system lines | Own ring; one line per 2 seconds; the rest counted. |
| Loops of leave and join, host passing, round start and stop | Same: announced at most once per 2 seconds. |
| Holding requests to exhaust threads | One held message poll per member; own cap; over the cap an answer with `retry_ms`. This bounds held polls, not connections: Core has no request timeout of its own today, which is existing hardening work and not made worse here. |
| Starving state delivery | Messages do not change `version`, are not presence, and use their own wake and cap. |
| A slow phone stalling the Party | Nothing is written to a socket under the lock. |
| Markup, hidden, reversed or stacked text | Rendered as text only; cleaning in decision 7. |
| Memory growth | Rings of 60 and 20; 8 short `client_id`s per member. Members themselves are not bounded (decision 7). |
| Cross-site send | Origin and `Sec-Fetch-Site` on the POST; on Limited the Origin allow-list alone, as ADR 0012 records. |
| Cross-site read | No cross-origin response headers; `SameSite=Lax`; Host check. No Origin check exists on any Party GET. |
| A game page reading or writing the room | Impossible in Full Mode once ADR 0013 is deployed; possible for same-origin pages before that and in Limited Mode (decisions 8, 9). |
| Eavesdropping on Limited | Not preventable; stated to the user (decision 8). |
| Text in logs, status or results | Never written there; refusals logged as totals. |
| A stale phone mixing two Parties, or posting into the wrong one | Every request names its Party; a send for another Party is refused. |
| A member who left still reading | Membership re-checked after every wake. |
| Clock jumps | No wall-clock time is sent or compared. |

Not addressed in v1: harassment between members (no mute, block or report). At one table of
people who know each other this is accepted; it is listed below for the owner.

## Proof required of AVR-54

- Unit: sender comes only from the credential; a client-supplied name, id, kind or `seq` is
  ignored; order across both rings; each ring's window; the gap case; a read and a send naming
  an old Party; a non-member; cursor values that are negative, too high or not a number;
  `client_id` repeat, repeat with other text, repeat after eviction; each cleaning rule with its
  hostile input; each limit and its code; system lines for each listed event and none for the
  others; the 2-second coalescing under a leave-and-join loop; one held poll per member; the cap
  and `retry_ms`; a held poll released on leave and on Party end; both listeners; no anonymous
  read; messages never change `version` and never count as presence; a slow reader does not
  block a state poll; no text in logs.
- Browser, several phones: unread counting, no duplicate after a reconnect, a phone that was away
  gets what it missed, the Chat tab with the Games runtime stopped, Limited and Full phones in
  one room, no request loop at the cap.
- On the Pi with a full table: state delivery stays within its bound while the room is busy, and
  a Limited phone still loads pages with two requests held (a browser allows few connections to
  one host over plain HTTP). This is a measurement, not a simulation.
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
5. **Who v1 is for.** A table of friends, accepting that a hostile guest on the Wi-Fi can drown
   the room (proposed), or a join limit and member cap in Party Core first.
6. **Moderation in v1.** None (proposed), or the Host can mute a member.
7. **Photos and reactions.** Dropped in v1 (proposed; the shell shows only "Photo shared"
   today), or kept.
8. **Order of retirement.** Party messaging first, then the legacy chat (proposed), or retire
   the runtime first and accept an interval with no chat.

## Reconciliation with AVR-27

Empty until the four-human night has happened. Before acceptance this section records what the
night showed about how people used chat, names and the drawer, and what in this proposal changed
because of it.

## Consequences

- Party Core gains its first route that stores user-written text and its first rate limits.
- Each phone holds a second request while a Party page is open, drawer open or not.
- The shell's Chat tab stops depending on the Games runtime, which unblocks its retirement.
- The absence of a join limit and member cap in Party Core becomes visible to users, not only to
  Core.
- COMMUNICATION's layers 2 to 4 stay as proposed direction; its transport section and its
  account of what exists are replaced by this proposal if it is accepted.
- Team play with private channels, chat during a game and game policy remain undecided and are
  not made easier or harder by v1 beyond the `scope` field.
