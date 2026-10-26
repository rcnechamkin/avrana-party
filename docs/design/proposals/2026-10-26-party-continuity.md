# Party continuity across sleep, restart, reboot and power loss (AVR-21)

- **Status:** proposal, 2026-10-26. Nothing is implemented and no persistence is added. **Owner decisions required** (section 7).
- **Reads with:**
  - `avrana/party/core.py` (module doc: "the party is memory-only; OPEN") and `identity.py` (`DeviceStore`);
  - [PARTY-LIFECYCLE.md](../PARTY-LIFECYCLE.md) (the failure table);
  - `deploy/party-core/avrana-party-core.service` and `deploy/games/avrana-game@.service` (`Restart=on-failure`);
  - the offline clock proposal (AVR-79, draft #228);
  - the backup proposal (AVR-81, draft #227);
  - the wedged-game health work (AVR-673).

## 1. Two kinds of continuity

They are kept apart in everything below:

- **Party continuity:**
  - who is in the party, who hosts, each member's mode (Full or Limited);
  - where the party is (home, setup, game, results);
  - the Party room's messages.
- **Game-state continuity:**
  - the round itself: cards, scores, whose turn;
  - the game's own seat tokens.
  This state lives in the game's process, never in Party Core.

## 2. What happens today (Party `main` 8a7e578)

| Interruption | Party continuity | Game-state continuity | Source |
|---|---|---|---|
| **A phone sleeps or loses Wi-Fi** | Kept. The member shows `away` after 45 s (`LIVE_WINDOW`) and stays a member until an explicit Leave. An away host keeps the role for another 30 s (`HOST_GRACE`), then the role passes, preferring a Full Mode member who is here. The party ends after 3 h with nobody here and no round (`PARTY_IDLE`). | Owned by the game (its grace, autopilot or pause). The Party's one bound: when every player's page has been silent 5 min past `LIVE_WINDOW` (`TABLE_ABANDON`), the round ends `abandoned`. | `core.py` |
| **The appliance sleeps** | Not a state the Pi has: there is no suspend. The commercial unit may add one. | — | — |
| **Party Core restarts** (crash, deploy, `systemctl restart`) | **Lost.** A new, empty Party starts. Phones keep their identity (`DeviceStore`, 0600 JSON, written atomically) and their profile (name and avatar, in the phone's own storage). Each phone rejoins on its own; the first to arrive is host; Party chat starts empty (`party-chat.js`: "nothing from the old room is kept"). | **Orphaned.** The game process keeps its old session until the new Party launches a game; a newer launch replaces the old session (`party_protocol.on_launch`). Its result for the old session reaches a Core that does not know it. | `core.py`, `identity.py`, `service.py`, runbook `arcade-party-provider.md` ("a restart starts a new, empty Party") |
| **A game process restarts** | Kept; the round is on. | **Lost.** The new process holds no session and refuses the round's tickets. Core's reachability check cannot see a restart (the socket answers), so the round stays open until the host ends it, `TABLE_ABANDON`, or AVR-673's health answer. | `sessions.py` `reachable()` doc |
| **Reboot** | As a Core restart; every unit starts fresh. | Lost. | — |
| **Power loss** | As a reboot. `DeviceStore` survives: its atomic replace leaves the old file or the new one. The clock may be wrong at boot (AVR-79 G1/G2). | Lost. | `identity.py` |

The appliance already recovers well from the commonest case, a phone that sleeps. A restart costs the party's shape (members, host, location, chat). It never costs the phones' identities or profiles, so getting back is one tap at most and usually none.

## 3. Options

### A. Ephemeral Party, with honest recovery UX (today's model, finished)

Keep the Party in memory. Add only what makes a restart understandable:

1. **Say it.** A phone whose next view has a different `party` id after it had one shows a single line: "The Avrana box restarted. A new party started; you are in it." It shows after a reload too, if the phone held that party id in memory. The clients already detect the change (`app.js` line ~1159, `party-chat.js`); only the words are missing.
2. **Host after a restart.** Today the first phone back becomes host. Proposed alternative: for 60 s after a restart, the host role waits for the device that hosted before. This needs one fact on disk: the previous host's `device_id`, which the box already knows. If that device does not return within 60 s, the first member becomes host. This is optional (D2).
3. **The orphaned game.** On start, Core sends a signed `end` for the old session to every game it launched before. That needs the old session ids on disk, which is option B's file. Without them, the next launch replaces the session anyway. Leave this as is under A.
4. **The owner page** shows "Started at 21:14 (after a restart)" with the reason if systemd gives one (`Restart=on-failure`, a deploy, a boot).

Complexity: small, a client string plus one optional owner line. Security: nothing new at rest. Every case: a new party, with an explanation.

### B. Limited persistence: the Party's shape, never its content

On each committed change (debounced to one write per 2 s), write a 0600 JSON snapshot next to `devices.json`:

```json
{"schema": "avrana.party-snapshot/v0", "party": "party-…", "saved_at": "…", "boot_id": "…",
 "host_device": "<device_id>", "members": [{"device": "<device_id>", "mode": "full", "joined_at": "…"}],
 "location": "home", "last_session": {"id": "session-…", "game": "bestguess"}}
```

- **Not in it:**
  - names and avatars (the phone has them, and sends them again when it joins);
  - Party room messages;
  - tickets, keys, cursors;
  - any game state.
- **On start:** a snapshot younger than `RESUME_WINDOW` (proposed 15 min, D3) whose clock can be trusted (AVR-79 "synced" or "floor" state, never "unknown") is offered. It is not applied silently:
  - the owner page and the first returning phone of the old host see "Resume the last party? (4 people, Ada was host)";
  - **Resume** restores membership, host and modes, and puts the party at **home**;
  - **Start fresh** deletes the file.
  If nobody answers within the window, the box starts fresh, as under A.
- **The old round is never resumed.**
  - The party lands at home with one system line: "The box restarted, so the Best Guess round ended." The outcome is recorded as `abandoned`.
  - Core sends the old game the signed `end` for `last_session`, so it does not keep a ghost session.

Complexity: medium.
- Code: a writer and a loader in `service.py` (Core stays pure: a `snapshot()` and a `restore()` on `PartyCore`), plus the prompt.
- Tests: the debounce, a torn write, an old file, an untrusted clock, a device that never returns, a restore that names a device that has since been forgotten.

Security and privacy:
- The file links device ids into a group with times. That is personal data at rest; today it is only in memory.
- It holds no names. AVR-81 D4 already keeps phone identities out of backups, and this file stays out too.
- The field-session redactor already drops `device` keys.
- The file is deleted on Start fresh, when the party ends by its own rules (`PARTY_IDLE`, everyone left), and on factory reset.

### C. Full restoration, including the round

Option B, plus games that can suspend and resume their own state:

- The Party asks the game for a snapshot at safe points.
- On start, it relaunches the same session id, with the old roster and the snapshot.

Each game would need:
- an encrypted, integrity-checked state file;
- a versioned state format, kept across game updates (the update and rollback rules of AVR-58 then meet saved games);
- per-seat token re-issue;
- a rule for players who never return.

Complexity: large. It touches the session protocol (a `resume` message), the kit, every game, and the AVR-72 compatibility window. Security: game state at rest, possibly hidden information (hands, roles), so it must be encrypted to the game's key.

## 4. Candidate game recovery metadata (not binding)

A manifest field a game may declare. The Party reads it only once option C exists. Until then every game is `none` whatever it says:

```json
"recovery": "none"           // default: an interruption ends the round
"recovery": "restart-round"  // the party may relaunch the same game and roster, fresh
"recovery": "resumable"      // the game can save and resume (needs the C protocol); implies restart-round
```

- `restart-round` is the cheap useful middle. Under B, a resumed party could offer the host "Start Best Guess again with the same players" when the old round's game declares it.
- `comply` would check that a `resumable` game implements the resume message, and would refuse the declaration otherwise.

## 5. Sleep and wake, reboot, power loss

| Event | A | B | C |
|---|---|---|---|
| Phone sleep (any length) | kept, as today | kept | kept |
| Appliance sleep and wake (future hardware; memory kept) | kept: the process never stopped. Timers judge by monotonic time, so a long sleep makes every phone `away` and may trigger succession on wake. Proposed: Core treats a wall-clock jump larger than its monotonic one as a sleep, and gives everyone `LIVE_WINDOW` again (a later implementation note, not needed on the Pi). | same | same |
| Core restart, deploy | new party + message | offer to resume (shape only), round abandoned | resume the round where the game supports it |
| Reboot | new party + message | offer to resume if within the window and the clock is trusted | as B, plus rounds |
| Power loss | as reboot; `DeviceStore` intact | as reboot; a torn snapshot is ignored (atomic replace, schema check) | as B; a game snapshot older than its last acknowledged move is refused |

## 6. Recommendation

- **M2 (friend-ready): option A**, items 1 and 4, plus item 2 if you want the old host back (D2).
  - It is what the box already almost does.
  - It costs a string and an owner line.
  - It adds no personal data at rest.
  - A friend's party survives what usually happens (phones sleeping). A rare restart becomes understandable instead of confusing.
- **M3 (retail): decide B** after the AVR-33 restart drills on the Pi show how often Core actually restarts in a party.
  - If restarts mostly come from deploys, the fix is to not deploy during a party (the deploy tool can refuse while a party has members), not persistence.
- **Defer C** until a game needs it and the session protocol is frozen (AVR-72). Record the `recovery` vocabulary now so games do not invent their own.

## 7. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | Continuity for M2 | A; B; C | **A** |
| D2 | After a restart, wait for the previous host? | no (first back is host); wait 60 s | **wait 60 s** (one device id on disk) |
| D3 | If B later: resume window | 5 / 15 / 60 min | **15 min**, and only with a trusted clock |
| D4 | If B later: who confirms a resume | owner page only; owner page or previous host's phone; automatic | **owner page or previous host** |
| D5 | Should the deploy tool refuse while a party has members? | yes, with `--force`; no | **yes, with `--force`** |
| D6 | Adopt the `recovery` vocabulary now, without enforcing it? | yes; later | **yes** |

## 8. What would be tested, if built

Not implemented here. Tests for A:
- a view with a new `party` id shows the restart line once, and not after an ordinary Leave and rejoin;
- the previous host regains the role within 60 s, and the first member gets it after 60 s;
- the owner page names the restart cause when systemd gives one.

For B, add:
- the debounce;
- a torn or old file;
- an untrusted clock;
- Resume and Start fresh;
- a forgotten device;
- the old game receiving `end`.

The AVR-33 restart drills on the Pi are the owner's.
