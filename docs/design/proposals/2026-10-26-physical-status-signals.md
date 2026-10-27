# Physical status, identify and attention signals (AVR-87)

- **Status:** proposal, 2026-10-26. Nothing is implemented, and no hardware is chosen. **Owner decisions required** (section 6).
- **Reads with:**
  - [STATUS-ENDPOINT.md](../STATUS-ENDPOINT.md) and `avrana/ops/status.py` (`avrana.status/v0`, `GET /party/api/status`);
  - `avrana/ops/preflight.py` and Party Ready (AVR-86, draft #232);
  - the Party continuity proposal (AVR-21, draft #236);
  - the signed-updates proposal (AVR-82, draft #238).
- **There is no owner page yet.** "The owner page" below means the owner surface proposed for AVR-44 and AVR-74; no owner route or Admin PIN session exists in code today. Until one does, the owner reads these facts over SSH.

## 1. Principle: one state, derived from facts the box already has

The box already knows everything a light needs to say. `avrana.status/v0` reports:
- the summary (`ok | degraded | unknown`, with reasons);
- service states and systemd recovery;
- the certificate;
- Party Core (`members`, `session`).

The deploy tool knows when an update is running, and the preflight knows what is unchecked. So the physical signal is **one more reader of those facts**, never a second health system. A small daemon (`avrana-signal`) reads them every 2 s and drives whatever output the hardware has. Nothing in Party Core changes.

## 2. The state set: seven states, one at a time, in priority order

| # | State | Derived from | Meaning for a person nearby |
|---|---|---|---|
| 1 | **identify** | an owner request (section 4), 30 s | "this is the box you picked" |
| 2 | **recovery** | booted into the recovery image, or a deploy run that died and was never recovered (`deploy.sh --status`) | "needs the owner; parties won't start" |
| 3 | **updating** | a deploy or update run in progress (`ops/deploy.sh` holds `/run/lock/avrana-deploy.lock`) | "don't unplug me" |
| 4 | **attention** | `status.summary == degraded` (a failed unit, a restart loop, an expired or expiring certificate inside the AVR-86 horizon), or the time state is unknown (AVR-79) | "works, maybe partly; the owner should look at the owner page" |
| 5 | **party** | `party_core.members > 0` | "a party is on" (count only on a display, never on a light) |
| 6 | **ready** | `summary == ok`, nobody in the party | "ready, join the Wi-Fi" |
| 7 | **booting** | the daemon is up, but Party Core does not answer yet, for up to 3 min, after which it becomes **attention** | "starting" |

- `unknown` (a probe that did not answer) maps to **attention**, never to **ready**. Status never calls an unchecked fact healthy (AVR-31), and neither does the light.
- **Sleeping** is not a state on the Pi, which has no suspend (AVR-21). On hardware that sleeps, it would sit between party and ready, as a slow breath.

## 3. Rendering: the smallest hardware first

| State | One RGB LED or ring (the minimum) | A small display (if present) |
|---|---|---|
| identify | fast white pulse, 2 Hz, 30 s | "This is Avrana · party.avrana.net" + the box's name |
| recovery | solid amber | "Needs attention: open the owner page" |
| updating | slow blue sweep or breathe | "Updating… don't unplug" + step |
| attention | amber, slow blink (1 per 2 s) | the first reason, in Party Ready's words |
| party | soft brand colour, steady | "Party on · 4 people" |
| ready | dim white, steady | the Wi-Fi name and "Join to play" |
| booting | dim white breathe | "Starting…" |

- **Colour is never the only carrier.** Each state also differs in motion (steady, breathe, blink, sweep, pulse), so the set survives colour-blindness and a cheap single-colour LED.
- **Quiet and night:**
  - a setting dims steady states to 10%, or off for ready and party, from 22:00 to 08:00 (owner-set);
  - attention, recovery and updating are never fully dark; they dim to a minimum but stay visible;
  - identify ignores quiet hours.
- **Prototype (Pi 5):** no hardware is needed to start. The Pi's own status LED (`/sys/class/leds/ACT`) can show the motion patterns, monochrome, as a development stand-in. The real enclosure gets a replaceable driver.

## 4. Identify

- The owner page, or the owner app later, sends an identify request: a new route; the name `POST /party/api/owner/identify` is only illustrative. It sits behind owner authentication, which does not exist yet: the Admin PIN session that PARTY-PLATFORM.md requires, then owner keys (AVR-44). Until then, identify is a command run over SSH. The box shows **identify** for 30 s.
- The response contains nothing a guest could use.
- Guests cannot trigger it: a party of guests making every box flash is a nuisance, and it gives away nothing a guest needs.
- With several boxes on a table, the owner page lists each by its name, and Identify lights only the chosen one.

## 5. The hardware-agnostic interface

`avrana-signal` writes the current state to `/run/avrana/signal.json`:

```json
{"schema": "avrana.signal/v0", "state": "attention", "since": "…", "reason": "certificate expires in 3 days", "quiet": false}
```

- A **driver** per hardware reads that file and renders it: the Pi ACT LED now, a ring or a display later.
- A driver never decides a state, so swapping hardware changes no logic.
- The same state appears in `avrana.status/v0` as `signal`, so phones and support see exactly what the box is showing.
- A button, if the enclosure has one, sends "identify" (a short press, local only) and, held 10 s at boot, "boot to recovery" (retail hardware; AVR-44 Q3).

## 6. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | The minimum hardware for friend-ready units | one RGB LED; a ring; a small display | **one RGB LED** (or ring) with the motion patterns; a display only on retail |
| D2 | Show a member count physically? | never; on a display only | **display only** |
| D3 | Quiet hours default | off; 22:00–08:00 dimmed | **22:00–08:00, steady states dimmed, attention never dark** |
| D4 | Identify only from the owner, or also from the host's phone? | owner only; host too | **owner only** |
| D5 | Build the Pi ACT-LED stand-in now? | yes; wait for the enclosure | **yes**: it costs a small daemon, and it exercises the contract on real hardware |

## 7. Exit criteria

| Criterion | Section |
|---|---|
| Small, stable set of states | 2 (seven, in priority order) |
| Understandable without a manual where practical | 3: motion + colour, and display words in Party Ready's language |
| Identify flow | 4 |
| Quiet and night behaviour | 3 |
| Failure and recovery distinguishable | recovery (solid amber) vs attention (amber blink) vs updating (blue) |
| Hardware-agnostic status API | 5 (`avrana.signal/v0`, also in `avrana.status/v0`) |
| Prototype hardware replaceable | 5 (drivers read state, decide nothing) |

## 8. Tests, if built

- A pure function maps a status document, deploy state and owner requests to one state; a table test covers every priority pair.
- `unknown` never maps to ready.
- Quiet hours never darken attention.
- Identify expires after 30 s.
- A dead daemon leaves the LED in its boot default, not in "ready".
