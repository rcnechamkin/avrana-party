# Offline clock policy: what the appliance may believe about the time (AVR-79)

- **Status:** proposal, 2026-10-26. Nothing is implemented. No file, unit or tool changes with this document.
  **Owner decisions are required** (section 6) before any code is written.
- **Answers:** inventory unknown U10 (`deploy/appliance-inventory.json`) and the AVR-79 exit criteria.
- **Reads with:** [the 2026-10-12 deployed baseline](../../findings/2026-10-12-deployed-baseline.md) (clock rows),
  `avrana/party/protocol.py` (the "Clock" note, `CLOCK_SKEW`, `SpentTickets`),
  `avrana/ops/status.py` (`_certificate`), [ADR 0006](../../adr/0006-party-session-protocol.md),
  [ADR 0012](../../adr/0012-limited-mode-party-survives-https-loss.md) (Limited Mode).

## 1. What is known

| Fact | Source | Kind |
|---|---|---|
| The Pi 4 has no RTC (`/sys/class/rtc` empty) | baseline | OBSERVED 2026-10-12 |
| `systemd-timesyncd` is enabled and active; `fake-hwclock` and `chrony` are not installed | baseline | OBSERVED |
| timesyncd's saved-clock file `/var/lib/systemd/timesync/clock` exists (0 bytes; its **mtime** is the saved time) | baseline | OBSERVED |
| At the one recorded boot the clock started about 37 h behind and stepped forward when NTP answered over Ethernet. Party Core started **before** the step. | baseline | OBSERVED |
| With no upstream the clock would stay at the saved value (not 1970) and no step would follow | baseline | INFERENCE, not observed |
| An offline cold boot has never been tested | AVR-79 | NOT RUN |
| Nothing in either repository configures or checks time | inventory U10 | OBSERVED by search |

So the realistic failure is not "the clock reads 1970". It is "**the clock is behind by however long the
unit was switched off**, and may jump forward later if a network appears".

## 2. Who actually depends on the appliance's clock

The key observation: **phones check the HTTPS certificate with their own clocks, not the Pi's.** A phone's
clock comes from its carrier or its own NTP and is almost always right. A wrong Pi clock does not make
phones reject a valid certificate.

| Consumer | What it reads | Effect of a clock that is behind by B | Effect of a forward step of S | Today |
|---|---|---|---|---|
| Party tickets (`iat`, `exp`, TTL 120 s) | Party and game read **the same** clock | none: both ends agree | tickets in flight read `expired`; the browser fetches a fresh one | handled (protocol.py "Clock") |
| Backward step (rare: only if the saved clock is ahead) | – | `iat` ahead by more than `CLOCK_SKEW` (5 s) is refused as `clock`; `SpentTickets` keeps a high-water mark so a spent ticket never comes back | – | handled |
| Limited Mode credential (12 h) | `time.monotonic` on the Pi (`identity.py` `LimitedStore`) and a relative cookie `Max-Age` the phone measures | none | none: monotonic time does not step | handled |
| Certificate status (`status.py` `_certificate`) | `not_after - now` on the Pi | shows **more** days left than true; can show `ok` for a certificate the phones already see as expired | corrects itself | **gap** (G1): wrong in the safe-looking direction |
| ACME renewal (lego) | Pi clock plus Let's Encrypt | needs internet anyway; with internet NTP has already stepped | – | not a concern offline |
| Last-known-good record, telemetry, journal, rebuild backup names (`rebuild-<UTC>`) | Pi clock | timestamps from before the step are wrong; ordering across a step breaks | – | **gap** (G2): cosmetic but misleads support |
| `.avrgame` packages | – | no expiry or signature time today (`avrana.avrgame/experimental.1`) | – | not affected yet |
| Future signed updates or TUF-style metadata (AVR-58, AVR-82) | Pi clock | an attacker who controls the clock (or a long power-off) can make **expired metadata look fresh** (freeze attack) or fresh metadata look not-yet-valid | – | design rule needed now (R4, R5) |

## 3. The policy (proposal)

**R1. Trusted sources, in order.**
1. NTP over the WAN uplink (timesyncd, as today). This is the only source that may *set* the time.
2. The persisted **floor**: the latest time the unit has ever trusted (R2). It may only move the clock
   *forward*, never back.
3. Nothing else. In particular a phone's reported time, an HTTP `Date` header from a phone, a browser's
   `Date.now()` or a Companion (AVR-48) claim **never** sets the appliance clock.

**R2. A persisted floor.** Keep timesyncd's saved clock, and additionally record a floor file
(`/var/lib/avrana-party/time-floor`, root-owned, a single UTC instant) written:
- when timesyncd reports synchronised (`timedatectl show -p NTPSynchronized`), and
- every hour while running, and at clean shutdown.

At boot, before Party Core starts, the clock is set to `max(now, floor)` if it is behind. This is what
timesyncd's saved clock already does; the floor exists so Avrana can **read** it, compare and report.

**R3. A time state, reported, not hidden.** Status gains `time: {state, floor, synced_at}` with three states:
- `synced`: NTP synchronised this boot.
- `floor`: not synchronised; running from the floor. Time is **at least** right, probably behind.
- `unknown`: no floor, or the floor is in the future by more than a day (a rollback or a corrupted file).

The owner status page (and `avrana.ops.status`) shows the state. Phones are not told.

**R4. Never silently accept an expiry while the time state is not `synced`.** A future check that
depends on "has X expired?" (signed metadata, update manifests, an entitlement) must:
- in `synced`: decide normally;
- in `floor`: accept only items whose validity **started before the floor** and has not ended by the floor,
  and say "time not verified" next to the result;
- in `unknown`: refuse anything that requires freshness, and say why.
The rule is "the floor is a lower bound": an item that has expired by the floor has definitely expired.

**R5. Freshness for stale metadata.** When signed metadata arrives (AVR-58), it carries its own
`issued` time. The appliance raises its floor to `issued` only after the signature verifies. That makes
every verified update a time source that can only move the floor forward, and it defeats a rollback
attack: once metadata issued at T has been accepted, the unit will never again accept metadata that expired
before T. How long stale metadata stays usable offline is an owner decision (D3).

**R6. Courier and Companion delays.** A package or update carried in by hand (USB, a Companion) is
judged by R4 and R5 like any other: its `issued` time may raise the floor; its age is measured against the
floor, never against the courier's claim.

**R7. The status certificate line in `floor` and `unknown`.** `days_left` is computed against the floor
and labelled "at most N days" (the true value can only be smaller). In `unknown` it reads "cannot tell".
This fixes G1 without trusting phone time.

**R8. Durations use monotonic time.** Anything that means "N seconds from now" on the appliance (a lifetime,
a timeout, a cache) uses `time.monotonic`, as the Limited Mode store and the status cache already do. Wall
time is only for instants that leave the process (tickets shared with a game, records, expiry checks under R4).

**R9. Timestamps across a step.** Records written before the first sync of a boot (journal aside) carry
`"time_state": "floor"`. Support tooling treats their times as lower bounds. This addresses G2 without
rewriting history.

## 4. Clock rollback attacks

| Attack | Mitigation |
|---|---|
| Someone with physical access powers the unit off for a long time, then boots it offline | R2 and R3: the clock starts at the floor, state `floor`; R4 refuses to call anything fresh that was not already valid by then |
| A rogue NTP server on the uplink sets the clock back | timesyncd plus R2: the clock never goes below the floor, so the attacker can only hold time still, not reverse it. A large backward correction is logged and leaves the state `unknown` until the owner looks |
| A rogue NTP server sets the clock forward | tickets in flight expire (they are refetched); Limited credentials are unaffected (monotonic); certificate status could read `expired` early (fail-safe). The floor would advance: a cap on how far one sync may move the floor ahead (D4) limits the damage |
| A phone lies about the time | R1: phone time is never a source |
| Replayed old signed metadata | R5: the floor rises to every verified `issued`, so older expired metadata is refused |

## 5. Hardware for a commercial unit

A battery-backed RTC (a Pi 5 has one built in and needs only a battery; a Pi 4 needs an I²C module such as a DS3231) turns the
`floor` state into "probably right" after a long power-off. It does **not** remove the need for R2–R5,
because an RTC can be reset or wrong. Cost is small (a coin cell and a few dollars of parts) but it adds a
battery to shipping and safety paperwork (AVR-444 compliance). Recommendation in D5.

## 6. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | Must the first prototype work fully offline after a long power-off? | a) yes, fully; b) yes for parties and games, with a "time not verified" note on the owner page; c) no, require one network sync first | **b**: parties and games do not need true time (section 2); only freshness checks do, and those already wait for AVR-58 |
| D2 | Add the floor file and time state (R2, R3) now, or wait for signed updates? | now; with AVR-58 | **now**: small, and it makes the status certificate line honest (R7) |
| D3 | How long may verified metadata stay usable offline (R5)? | 7 days; 30 days; until the next expiry it states | **its own stated expiry, judged against the floor**; no extra grace |
| D4 | Cap on one forward step of the floor | none; 1 year; 30 days | **30 days** beyond the previous floor, unless NTP agrees on two consecutive syncs |
| D5 | Require an RTC on commercial hardware? | yes; no; optional SKU | **yes** if the unit's BOM allows it (AVR-441); the software policy stays the same either way |
| D6 | Run the offline cold-boot test (inventory U10) | owner, on the Pi | **yes**: unplug Ethernet, power off overnight, boot, record `timedatectl`, what the owner page shows, and whether a party and a game work. This is the one row in section 1 that is NOT RUN |

## 7. Tests to write with the implementation

- Floor: boot with the clock behind the floor → clock raised to the floor; with the clock ahead → untouched;
  with a floor more than a day in the future → state `unknown`, clock untouched.
- Status: certificate `days_left` in each state, including "at most" wording and the `unknown` refusal.
- R4 decision table: an item valid before the floor, one that expired before the floor, one that starts after
  it, in each of the three states.
- R8: a search-based check that new lifetime and timeout code in `avrana/` takes a monotonic clock.
- Rollback: after accepting metadata issued at T, metadata that expired before T is refused even with the
  wall clock set back.
- Phone time: no endpoint, header or message changes the floor (a search-based test like the existing
  boundary checks).

## 8. What this does not cover

- Time zones and displayed local times (a UI matter; the appliance keeps UTC).
- Game-level timers in the Games repository (not audited here; R8 is the rule they should follow).
- Certificate issuance itself (the party-https runbook) and Limited Mode's real-phone tests (ADR 0012 step 4).
