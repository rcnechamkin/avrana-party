# ADR 0017 — Party-owned messaging: one Party room in Party Core

Status: **accepted · implemented, merged (PR #159) · not deployed** · Date: 2026-10-16

The owner accepted the [AVR-53](https://linear.app/avranakern/issue/AVR-53/define-avrana-platform-messaging-architecture-and-ownership)
proposal on 2026-10-16 with all eight of its proposed defaults. The full design, threat table and
proof list are in [MESSAGING](../design/MESSAGING.md), which this ADR makes binding; this page
records the decision and the answers. Implementation:
[AVR-54](https://linear.app/avranakern/issue/AVR-54/build-party-owned-messaging-service-and-shared-player-surfaces),
[rcnechamkin/avrana-party#159](https://github.com/rcnechamkin/avrana-party/pull/159) (merged 2026-10-16, not deployed).

## Decision

Party Core owns messaging: sender (always the credential's member), membership, order, history,
limits and system lines. One room per Party, `scope: "party"`, in memory, emptied when the Party
ends. Delivered by its own long poll (`GET /party/api/messages`) and sent by
`POST /party/api/messages`, on both the Full and the Limited listener. Games never receive the
room, a member identity or a message verb (MESSAGING decision 9).

## The owner's answers (MESSAGING "Owner decisions")

1. **Chat over a briefing:** no. People only, as GAME-UX-CONTRACT rule 3.2 says.
2. **System lines:** the proposed list: a first join or a return, a leave, a new Host, a rename, a
   round becoming active, a round finishing. At most one per 2 s, the rest counted.
3. **Limits:** 400 code points, 6 messages per 4 s per member (30 per 10 s per Party), history 60.
4. **Limited Mode:** one shared room; the Limited notice covers chat, and Full phones are told
   while a Limited phone is in the Party.
5. **Who v1 is for:** a table of friends. A hostile guest on the Wi-Fi can drown the room; a join
   limit and member cap stay a prerequisite for a table of strangers.
6. **Moderation:** none in v1.
7. **Photos and reactions:** none in v1.
8. **Retirement order:** Party messaging first; the shell stops opening `/chat/ws`; the legacy
   chat retires with its runtime (AVR-222, AVR-228).

## Not decided here

Chat during a game and the in-game Party layer
([AVR-83](https://linear.app/avranakern/issue/AVR-83), [AVR-292](https://linear.app/avranakern/issue/AVR-292);
brief: [2026-10-16 Control Center](../design/proposals/2026-10-16-control-center.md)); team, game
and direct scopes; game messaging policy (AVR-55).

## Consequences

As MESSAGING "Consequences". Deployment still needs the owner's approval, the Pi measurement and
the real-phone checklist ([party-chat-phone-acceptance](../runbooks/party-chat-phone-acceptance.md)).
