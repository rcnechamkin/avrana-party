# BLE owner control plane: implementation-ready proposal and hardware verification plan

- **Status:** Proposal, written as input to AVR-315 (design only) and to a possible follow-up spike issue. Nothing built, nothing decided, nothing run. Derived from an earlier 2026-10-09 spike definition, revised to match the owner direction recorded in AVR-45 and AVR-315.
- **Date:** 2026-10-10
- **Sources:** Linear AVR-45 (revised 2026-10-09), AVR-315 (created 2026-10-10), AVR-44, AVR-63, AVR-65, AVR-83, AVR-317; ADR 0004 D1 (TLS key stays on the Pi), ADR 0012 (Limited Mode), ADR 0016 (service identities); `docs/design/PARTY-PLATFORM.md` section 7 (Admin versus Host); Apple, Android and caniuse pages cited in `MOBILE-STORE-POLICY-RESEARCH.md` (research, unverified where marked there).
- **Related:** `docs/research/OWNER-APP-ARCHITECTURE.md`, `docs/research/MOBILE-STORE-POLICY-RESEARCH.md`

## 0. What changed from the 2026-10-09 spike definition

| Earlier draft | This proposal | Reason |
|---|---|---|
| Spike delivered a signed 1 MiB blob over BLE and staged it in quarantine | **Removed.** BLE carries commands, status, events and an opaque transfer ticket only | AVR-315: BLE is "not game traffic, video, packages or certificate payloads"; Wi-Fi carries larger transfers |
| Required an iPhone, an Android phone and a spare Pi 4 | Hardware is tiered; each gate states the minimum hardware, and gates that cannot be run are reported as **not run** | Not all hardware is guaranteed to be available |
| Treated the owner app as optional | Owner app is a commercial-launch requirement; mandatory activation is still an **open owner decision** | AVR-45, AVR-315 |
| Time box 10 days | 8 working days after approval and hardware availability | The blob-staging stages were removed |

AVR-315 itself is architecture only ("no phone app, BLE daemon, live Pi changes"). The spike below is a **separate, later activity** that needs its own approved issue; this document is the design input to it, not authorization to start it.

## 1. Scope

**In scope for the control plane:**

1. Discover an appliance (minimal advertising, "claimable" state bit, no venue or owner identity).
2. Prove physical ownership and claim an unclaimed appliance (commissioning).
3. Authenticated, signed, replay-protected commands: read status and health, read and set Wi-Fi/AP configuration, list and revoke owner credentials, open or close a Party-admission state if that is later allowed, request a **transfer ticket** (an opaque short-lived token naming a Wi-Fi staging slot, no payload), request certificate renewal (returns a ticket, no certificate on BLE).
4. Recovery: second-owner revocation, recovery code, physical reset, safe mode.
5. Ownership transfer and credential rotation, with the physical-presence steps each requires.

**Out of scope (hard):** game traffic, state, video, input; package bytes; certificate requests or certificates; any install or activation logic (the appliance owns validation and installation); Wi-Fi bulk transfer; production Pi changes; ACME; storefront or entitlement logic; background BLE operation (foreground sessions only); store submission; a formal security audit.

## 2. Security assumptions and threat model

**Assumptions**

- The appliance is the root of trust for what runs. The phone app proves *who the owner is* (a key), never *what is safe*, and is never authoritative for game state, trust installation or administrative commands merely because it transports data (AVR-45).
- The TLS private key never leaves the Pi (ADR 0004 D1). No private CA on phones (ADR 0012).
- Guests are untrusted browsers on Wi-Fi. They never reach BLE management or owner APIs, and the BLE surface is not reachable from the Party LAN. Game scripts cannot acquire owner BLE or platform privileges.
- Link-layer BLE encryption is necessary but **not sufficient**. No trust is derived from advertising identity or proximity alone (AVR-315). Every command carries an application-layer signature and a counter.
- Out of scope threats: root compromise of the Pi, physical access to unencrypted storage (ADR 0016 "not promised"), a compromised phone OS.

**Threats and required defences**

| Threat | Adversary | Required defence |
|---|---|---|
| Unowned appliance claimed by a stranger in range | bar patron, neighbour | Claim only while a physical-presence window is open; one owner at a time; window length and attempt counters bounded |
| Man in the middle during claim | active radio attacker | Application-layer PAKE bound to a code obtained out of band; never Just Works alone; transcript bound to both public identities |
| Replay or relay of commands | in-range or relaying attacker | Per-session appliance nonce, monotonic counter, short-lived session keys, command expiry |
| Rogue nearby phone sending commands | stranger | Unsigned or unknown-key commands rejected with no information beyond a generic error; rate limit per connection and globally |
| Lost or stolen phone | thief | Owner key in secure hardware (Android Keystore/StrongBox where available, iOS Secure Enclave), gated by device unlock; revocation by a second owner key, recovery code or physical reset |
| Compromised or counterfeit app | store, phishing | The app can only request; the appliance validates and may refuse; appliance shows what it is about to do |
| Reseller or previous owner retains control | second-hand sale | Physical factory reset clears owner keys, Wi-Fi and certificate state |
| Resource exhaustion over BLE | nearby attacker | Connection limits, command rate limits, bounded frame size, no unauthenticated state allocation beyond a fixed small table |
| BLE load disturbs the Wi-Fi AP | self-inflicted | Measured coexistence (section 6); control sessions are foreground and short |

### 2.1 Authority matrix (appliance admin, Party host, guest)

| Action | Guest (browser) | Party host (per-party role) | Appliance owner (BLE, app) |
|---|---|---|---|
| Join and play | yes | yes | yes (as any participant) |
| Start, end, manage a party | no | yes | optionally, via Admin path (open design question, AVR-44) |
| Read appliance status and health | no | limited, as today | yes |
| Change Wi-Fi/AP, certificate renewal request, install confirmation | no | no | yes, signed |
| List, add or revoke owner credentials | no | no | yes, signed; adding a new owner key requires physical presence |
| Factory reset | no | no | physical action only |

A Host can never escalate to owner, and the owner credential is independent of any web Admin PIN until AVR-44 decides otherwise (PARTY-PLATFORM section 7).

## 3. Pairing and physical-presence options

| Option | How | Strengths | Weaknesses | Hardware needed |
|---|---|---|---|---|
| A. One-time code from the appliance plus a power-cycle claim window | Code shown on a console/HDMI line or printed on a case label; claim accepted only for N minutes after boot, only while unclaimed; code is PAKE input | Works on a bare Pi 4; no extra parts | A printed label can be read by whoever holds the unit; weak alone, so claim once then rotate and invalidate the code | none |
| B. GPIO button or jumper opens a 120 s claim window | Press or bridge two header pins | Strong physical proof; testable on a bare Pi with a jumper wire; button on a shipped case | Needs a case/HAT button for retail | jumper wire for the spike, button for product |
| C. NFC tag (AVR-76) | Tap the phone to a tag on the unit | Good UX | Extra hardware; iOS/Android NFC behaviour differs | NFC tag/reader (not assumed available) |
| D. Wi-Fi-first claim via QR code on the AP | Phone joins the Party AP, claims over HTTPS or local API | No BLE needed to claim | Exposes a claim API to every device on the AP; Internet loss on the phone; against the BLE-as-management-plane direction | none |

**Recommended default [Proposal]:** A for the Pi-class prototype combined with B where a jumper or button is available (both the code and the window must be satisfied), and B as the requirement for any retail unit. After a successful claim the code is invalidated, the phone enrols its owner public key, and a printed **recovery code** (stored only as a hash on the appliance) is shown once. Option C is deferred until NFC hardware is on hand; D is retained only as the independent fallback commissioning path under "app-default commissioning with independent recovery", not as the normal path. PAKE suite (SPAKE2+ or an equivalent) and library are to be chosen and recorded by the spike; BLE bonding is a convenience, not the trust anchor.

## 4. Protocol shape (versioned, least privilege)

One primary GATT service `Avrana Owner`, versioned in `Info`.

| Characteristic | Properties | Content |
|---|---|---|
| `Info` | read, unauthenticated | protocol version, short appliance public id, state (unclaimed / claim window open / claimed), firmware build. No secrets or owner data |
| `PairControl` | write, indicate | PAKE messages; active only while a claim window is open |
| `Command` | write | framed, signed requests with counter and session nonce |
| `Response` | indicate | framed, chunked replies with sequence numbers; frame size capped well below any payload use |
| `Event` | notify | health: certificate days left, update ready, storage low, tamper/reset notices |

There is deliberately **no bulk characteristic**. Frames larger than a small cap (suggest 1 KiB per command and per response) are rejected, which also makes accidental payload use detectable. API versioning: a major version bump invalidates sessions; unknown commands return a generic unsupported error.

## 5. Recovery routes (must not weaken guest boundaries)

| Situation | Route |
|---|---|
| Phone lost or replaced | A second owner key revokes the old one; otherwise recovery code over a physical-presence window; otherwise physical reset |
| App uninstalled | Reinstall and re-authenticate with an enrolled key if the key survived; otherwise as lost phone |
| BLE unavailable or broken | Independent commissioning fallback (console/web Admin over the AP, or physical reset). The Party, Limited Mode and guest play never depend on BLE or the app |
| Expired certificate | Appliance falls back to Limited Mode (ADR 0012); renewal courier restores Full Mode |
| Factory reset | Physical action only; clears owner keys, Wi-Fi secret and certificate state |
| Safe mode | Defined by AVR-44; must not enable unauthenticated BLE commands |

## 6. Hardware verification plan

**Rules.** The production Pi and any deployed appliance are never touched, flashed or measured. Verification uses a spare board. One measurement activity at a time; no SSH polling during power measurements; read `vcgencmd get_throttled` once per phase. Tests that need hardware which is not available are reported as **not run**, never as passed.

| Tier | Needs | What it can establish |
|---|---|---|
| H0 | Any development machine | Frame parsing, counter/replay logic, PAKE transcript binding, signature verification, rate limits and window logic against an in-memory transport. Negative tests. No radio |
| H1 | Any BLE-capable Linux host able to act as a peripheral (laptop with BlueZ, or any spare board) and one Android 12+ phone with a debug build | Discovery, claim, signed commands, revocation, MTU/throughput/latency on Android, pairing prompts and permissions |
| H2 | Spare Raspberry Pi 4 (same radio chip as the appliance) running the same OS family, a known-good power supply and a way to read supply health, one extra client device | AP and BLE coexistence, throughput effect, throttle/under-voltage events |
| H3 | One iPhone (iOS 18+ if AccessorySetupKit is to be tried) with a signed development build | iOS claim flow, Core Bluetooth foreground behaviour, permissions |

Prerequisites needing the owner: designate the spare board as disposable; supply phones; create any developer account (an owner action; credentials are never entered by an agent); set the AP-throughput regression threshold (suggested under 20%, owner decides).

### Gates (stop on a failed gate)

| Gate | Tier | Pass |
|---|---|---|
| G0 Host logic | H0 | All negative tests produce zero accepted unauthorized commands; frames over the cap rejected; counter and nonce replay rejected |
| G1 Radio sanity | H1/H2 | Peripheral discoverable by a generic BLE app and the test app; the Wi-Fi AP stays up; baseline recorded |
| G2 Claim | H1, H3 | Claim completes within a 60 s median per OS **with** the physical proof; no claim possible with the window closed or the wrong code; second phone refused after a claim |
| G3 Signed commands | H1, H3 | Signed `status`, `ping`, ticket request succeed; wrong key, replayed counter, stale nonce, tampered frame rejected |
| G4 Revocation and reset | H1, H3 | Revoked key refused; second-owner revocation works; recovery code works exactly once; physical reset returns to unclaimed |
| G5 Coexistence | H2 | AP client throughput change with BLE active recorded against the owner's threshold; no BLE-attributable under-voltage or AP instability |
| G6 iOS feasibility | H3 | Foreground flow works with only the permissions listed in `MOBILE-STORE-POLICY-RESEARCH.md` (A6-A8); no Local Network prompt needed for BLE |

**Fail or redesign triggers:** iOS cannot sustain a foreground claim or needs a permission set the owner finds unacceptable (consider NFC or a Wi-Fi-first claim for iOS only); an authenticated pairing association cannot be achieved on one OS (rely on app-layer PAKE and state it); coexistence destabilizes the AP or causes under-voltage (escalate before any BLE work on the appliance; consider disabling the AP during management or a separate radio); any accepted unauthorized action (stop; the design is unsound as drawn).

### Measurements

Time to claim (cold, warm) per OS, median of 10; commands round-trip p50/p95; negotiated MTU and throughput per OS (informational, since payloads are out of scope); pairing prompts and permissions shown per OS (screenshots); AP client throughput with and without BLE load; throttle flags, supply voltage events and temperature, read once per phase; daemon CPU and memory by snapshot; phone battery drain over a 5 minute foreground session (indicative); negative-test accept count (must be 0); library footprint and licences.

### Time box

8 working days after approval, hardware availability and the preconditions above: days 1-2 H0 and radio sanity; 3-4 claim and commands on Android; 5 iOS if available; 6 revocation, recovery and reset; 7 coexistence and power; 8 report. Stop at day 8 with whichever gates have been run.

### Deliverable

One dated finding under `docs/findings/` with a per-gate verdict (pass, fail, not run), the measurements, the library choices, and an explicit statement that the production Pi was not touched. Raw logs are not committed. The finding informs: whether BLE is the management transport or only the claim channel; which physical-presence proof ships; whether the owner-authority ADR can proceed; whether the Pi 4 radio can host AP and BLE in the field; and the assumptions AVR-63, AVR-65 and AVR-44 may make about BLE.

## 7. Proposed follow-up issue (not created)

Title: **Spike: BLE-only owner claim and signed command channel on a disposable board.** Outcome: a dated finding as above. Out of scope: everything in section 1 "Out of scope". Repository: Party only, under `experiments/owner-ble/`, throwaway and marked non-production, no secrets. Tests: host-side unit tests for frame, counter, replay and window logic (no hardware); a scripted negative-test suite; real-device gates recorded as human validation. Open decisions: none for the spike itself; the owner settles the preconditions (disposable board, experiments location, developer account, throughput threshold) before the issue is ready.

## 8. Questions this proposal does not answer

- Whether retail activation literally requires the app (AVR-45, AVR-315: open owner decision).
- Whether a paired owner may mint a short-lived web Admin session (AVR-44).
- PAKE suite and library; ownership-transfer UX; safe-mode content (AVR-44).
- A formal review of the cryptography. Findings from the spike are indicative, not an audit.
