# Party activity, notifications and actionable system events (AVR-84)

- **Status:** proposal, 2026-10-26. Nothing is implemented. **Owner decisions required** (section 8).
- **Reads with:**
  - [MESSAGING.md](../MESSAGING.md) and `avrana/party/messages.py` (the Party room and its system lines);
  - `avrana/party/core.py` (`_commit` derives system lines);
  - `avrana/ops/status.py` (`avrana.status/v0`);
  - the physical-signals proposal (AVR-87, draft #240), the permissions proposal (AVR-62, draft #239) and the continuity proposal (AVR-21, draft #236).

## 1. What exists today

| Thing | What it is | Limits |
|---|---|---|
| **System lines in the Party room** | `messages.Room.system(event, member)`. A **closed list** of seven events (`joined`, `returned`, `left`, `host`, `renamed`, `round_started`, `round_ended`), derived inside `_commit` from what the commit changed, so they can be neither missing nor doubled. No free text, ever. At most one line per 2 s, with the rest counted as `more`. Kept in their own ring of 20. In memory only. | Everyone in the Party sees every line. There is no priority, action or expiry. It lives inside chat. |
| **View fields** | `location`, `me.host`, `me.leave` (the Leave impact), presence, the session | state, not events: a phone sees what is true now, not what happened |
| **`avrana.status/v0`** | the appliance's health (summary, services, certificate, recovery) | not shown to guests; the owner reads it on the owner page or by `curl` |
| **Game → Party** | bridge v1: `result`, `end`, `navigate` to `party`, `ticket` | a game cannot raise any event, and cannot post to chat (AVR-62) |

The room's system lines already embody the most important rule: **platform words come only from Core, from a closed list**. This proposal widens that into an event model without loosening it.

## 2. Activity is not messaging

- **Messaging** (MESSAGING.md) is people talking. Free text, from a member, shown as theirs.
- **Activity** is the Party or the box saying something happened or needs doing. It is structured and closed: a template id plus fields, rendered by the Party in the Party's words.
- An activity item is never rendered as a chat bubble.
- A chat line is never rendered as a notice.
- The existing seven system lines keep their place in the chat feed as context ("Bob joined"). They are also published as activity items, so a phone that does not show chat still gets them.

## 3. The event

```json
{"schema": "avrana.activity/v0", "id": "act-…", "seq": 41, "party": "party-…",
 "event": "host_changed", "source": "party",              // party | appliance | game:<id>
 "audience": "party",                                      // party | member:<member-id> | host | owner
 "priority": "info",                                       // info | notice | action | alert
 "action": null,                                           // or {"kind": "choose_role", "until_seq": …}
 "fields": {"member": "member-…", "name": "Bob"},          // template fields; never free text
 "expires_at": null, "at": "…"}
```

- **`event` is from a closed list per source.**
  - Party: the seven existing events plus `role_needed` (setup: choose Play or Watch), `round_ready` (the host can start) and `party_restarted` (AVR-21 option A).
  - Appliance: `storage_low`, `certificate_expiring`, `update_ready`, `service_degraded`, `time_unverified`.
  - Game: section 6.
- **`source` is set by Core**, from which code path raised the event. A game cannot claim `party` or `appliance`.
- **Rendering is the Party's.** Each event id has one template in the client. A game-sourced event is always shown with the game's name as its label ("Best Guess: it's your turn"), in a visually distinct style from platform events.

## 4. Audience and privacy

| Audience | Who receives it | Examples |
|---|---|---|
| `party` | every member's view | joined, left, host changed, round started or ended |
| `member:<id>` | only that member | "choose Play or Watch", "it's your turn" (game) |
| `host` | only the current host | "everyone has chosen: you can start", "a game did not confirm its end" |
| `owner` | only the owner page, never a guest phone | storage low, certificate expiring, update ready, a degraded service |

- Delivery is filtered **on the server**, per viewer, like every other per-seat fact.
- An event never carries another member's private game state. A game event addressed to a member carries only its template id and fields the game declared public, and a shared display (the TV) receives `party` events only.
- Appliance events never reach guests. A guest sees only the consequence, through the AVR-87 signal or Party Home's plain words when something stops working.

## 5. Priority, action, expiry, and reconnect

| Priority | Presentation | Lifetime |
|---|---|---|
| `info` | the activity feed only (and the chat context line, for the seven) | ring of 50 per Party, in memory |
| `notice` | a toast, once, and the feed | until seen or 30 s |
| `action` | a persistent card or banner with the action button, which takes the phone to where the action is | until the action is done, its `until_seq` passes, or `expires_at` |
| `alert` | the owner page's banner; for guests, only the Party Home line that explains the effect | until the condition clears (it is derived from status, not stored) |

**No duplicates or replays on reconnect:**
- Activity uses the room's cursor model: `(party, seq)`, with "a cursor for another Party reads from the start".
- An `action` item is **state-derived**. "Choose Play or Watch" exists exactly while the member has no choice in an open setup. A reconnecting phone recomputes it from the view and never replays a stale button.
- A completed action disappears on every phone at the next view.
- A toast is keyed by `id`, and the phone remembers the ids it has shown, in memory only. A reload may show a `notice` once more; an `action` is re-derived rather than replayed.

## 6. Game events (SDK path)

**Bridge v2**, gated by the AVR-62 permission `party_notices`:
- A game may declare up to 8 notice templates in its contract:
  `"notices": [{"id": "your_turn", "text": "It's your turn", "audience": "member"}, …]`.
  The text is checked like a display name: no URLs and no platform words, so not "Avrana", "System", "Host" or "Admin". It is shown on the install summary.
- At runtime the game sends `notice {id, participant?}` through the bridge. Core maps the participant to a member, rate-limits it (1 per 5 s per member), and publishes it with `source: "game:<id>"`.
- The game never chooses priority above `notice`. It cannot raise `action` or `alert`, and cannot address `party` or `owner`.
- Until v2, games keep their own in-page turn cues, which is what they do today.

## 7. Exit criteria

| Criterion | Section |
|---|---|
| Event schema and source authority | 3 (Core sets `source`; closed list per source) |
| Priority, action, expiry | 5 |
| Audience and privacy | 4 |
| Messaging vs activity | 2 |
| Full feed vs transient | 5 |
| Reconnect without duplicates or replays | 5 (cursor; actions derived from state) |
| Game SDK path | 6 |

## 8. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | Keep the seven system lines in chat as well as in activity? | both; activity only | **both** (chat context is liked; activity is for phones without chat open) |
| D2 | Add a feed screen for guests now? | yes; later | **later**. First, the three transient things guests need: role needed, host can start, Party restarted. |
| D3 | Owner alerts on the owner page only, or also on the host's phone? | owner page; also host | **owner page only**. A guest host is not the owner. |
| D4 | Game notices (bridge v2) | yes, templated and permission-gated; never | **yes, later**, behind AVR-62 `party_notices` |
| D5 | Persist activity across a restart? | no; yes | **no** (AVR-21 option A). `party_restarted` is the one item a new Party starts with. |

## 9. Implementation sketch (not done here)

1. `avrana/party/activity.py`: a pure ring with a cursor, plus per-viewer filtering, alongside `messages.py`.
2. `_commit` publishes the seven events. Setup derives `role_needed` and `round_ready`. `status.py` facts feed the owner alerts.
3. `GET /party/api/activity?party=&after=` (long-poll, like messages).
4. Tests:
   - a member event never appears in another member's view;
   - a game cannot set `source`;
   - an action disappears everywhere when done;
   - a reconnect with an old cursor gets no stale action;
   - a cursor from another Party reads from the start.
