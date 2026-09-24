# Party model (offline simulation) — experiment, not a service

An executable sketch of the lifecycle rules in `docs/design/PARTY-LIFECYCLE.md` and the identifier
invariants in `docs/adr/0003-ids-and-keys.md`. It exists to find awkward states **before** a real
party service is written: host loss, reconnects, late joiners, launch failures, duplicate votes,
one profile on two devices, an idle party ending.

- Pure Python standard library; no network, no persistence, no threads; injected clock.
- Nothing in production imports it, and it is **not** the future service's API. What should carry
  over are the **rules, timers-as-proposals and test scenarios**.
- Shape: `Appliance` (devices and profiles outlive parties; exactly one active party) →
  `Party` (lobby → launching → in_game → intermission → … → ended) → `Presence`
  (connected / reconnecting / away / left; `player` or `screen`) → `Seat` (occupied /
  disconnected with neutral input / away-reserved; released = gone).

```bash
python experiments/party-model/test_party_model.py      # 53 tests, ~1 s
```

## What the tests pin down

| Area | Scenarios |
|---|---|
| Identity | guests become Player 1…N (or the name chosen at Join, checked and announced); fabricated tokens get nothing; renames are display-only; the name rule blocks SYSTEM look-alikes (Cyrillic letters, zero-width and bidi characters, fullwidth forms, reserved prefixes) and numbers duplicates; party/device/presence/seat/session ids, device tokens and game keys are all distinct; a TV ("screen" presence) never becomes host, gets a seat or votes |
| Host | reconnect within grace keeps it; after grace the earliest-joined connected player (or a random one) takes over; a returning old host is an ordinary member; everyone gone → first eligible back; a disconnected host can't act; transfer only to a connected player; an explicit leave hands over at once, skipping people who left; stale requests (`if_version`) refused |
| Launch | a service game navigates only when *ready*; late joiners during launch get seats; failure keeps `nav_seq` and reports why; a cancelled launch's late "ready" is ignored; select-while-launching refused; the host leaving mid-launch doesn't stop it; launch timeout |
| Seats | new seats per game, pre-filled from the last game's seating; switching games ends the old session first; extras spectate; disconnect → neutral → away → reclaimed; a phone asleep through a game change still gets a (neutral) seat if it dropped less than `PRESENCE_GRACE` ago (longer asleep → spectator); newest tab owns input; late-join policies (spectator / supported / next round); promoting or queueing a disconnected player gives a neutral seat; a released-and-refilled seat gets a new key and its old owner returns as a spectator; open-seat games auto-release long-away seats; an empty table is abandoned with seating saved; crash → home with seating |
| Votes | refresh / tabs / revote never add a vote; eligibility fixed at open; spectators excluded by default; a disconnected voter doesn't block early completion; deadlines close rounds; a live round can't be reopened |
| Profiles | an untrusted device can't take a saved profile; a trusted one moves the same presence and seat to the new phone and kills the old game key; claiming into a hostless party makes that person host; a profile has at most one live presence (an old phone that rejoins after the profile moved on comes back as a guest); one presence can't hold two profiles |
| Timing | every deadline (vote close, launch timeout, host grace, seat grace/release, table abandon, idle end) is applied **before** each operation, not only by a background tick — a late vote, a late "ready" or an old host's request is refused even if no tick ran; timer-driven changes bump `version`, an idle tick doesn't; the table is abandoned `TABLE_ABANDON` after the **last seat emptied** (ticks in between don't restart it); a TV alone does not keep a party alive |
| Page open | `observe` (opening the page, or a captive-portal WebView loading it) reports the party without creating a presence or changing `version`; only Join does |
| Navigation | `nav_seq` restarts in a new party, so clients key on `(party_id, nav_seq)` |
| End | an ended party refuses every change; after the idle timeout the party ends and the next connect starts a new party with the same device; kicked devices can't rejoin, leavers can |
| Fuzz | 300 seeds × 150 random operations (all of the above, host actions only from the connected host, time jumps up to the idle timeout); invariants after every step: one presence per device; the host is an eligible player, and after a timer tick either connected or within its grace; no connected player without a host; `in_game ⇔ game`; nav target matches the game; unique slots and seat ids within capacity; waiting ∩ seated = ∅; a seat is occupied ⇔ its owner is connected; ballots ⊆ eligible; at most one live presence per profile; `nav_seq` and `version` never go backwards. Mutation-checked: removing succession or ignoring connection state in seats makes it fail; so do (2026-09-24) removing apply-time timers, the timer version bump, the profile unlink on rejoin, the one-profile-per-presence guard, the event-time table timer, or making `observe` join |

## Deliberately not modelled

PINs and QR pairing (trust is granted directly in tests); persistence across reboots (an OPEN
question — see the lifecycle doc's options); teams, chat and stats; the game side of seat
tickets; admin actions; network timing.

## Open decisions the model does not settle (owner)

The model picks a behaviour for each so tests can run; none of these is decided.

- **`if_version` scope.** `version` is party-wide, so a guest joining or a phone reconnecting makes
  the host's in-flight "start game" request stale. Options: keep it (safe, occasionally annoying),
  or a narrower "host-relevant" version (lobby/seat/launch changes only).
- **Succession rule** (earliest-joined vs random) and **every timer value** above.
- **Spectator voting** default (currently off).
- **Old phone after a profile moved:** it rejoins as a guest (current) vs is refused.
- **Overflow rotation** (who plays next when more people than seats) — not modelled.
- **Reboot survival** — not modelled; the lifecycle doc lists the options.

## Is it enough to start building?

For the **rules**, yes: F2a/F3/F4 can port these scenarios. It does **not** model transport
(WebSockets, reconnect back-off, message ordering), cookies/origins (the F3 device-token and
`SameSite` tests), persistence, or concurrency — those need the real dev front, with this model
as the oracle for a differential fuzz test.
