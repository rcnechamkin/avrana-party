# Avrana Party — Offline Trust, HTTPS, Limited Operation, and Recovery

> **Status: design direction, not deployed implementation.** The live appliance currently
> serves local HTTP. Read `ROADMAP.md` and `runbooks/network.md` before treating any
> certificate or app recovery path below as available.

## Purpose

This document defines the current trust and recovery model for Avrana Party.

It is intended primarily for LLMs and engineering agents.

The goal is not merely to “make HTTPS work.” The goal is to preserve a consumer-friendly, local-first gaming appliance even when certificates expire, Internet access disappears, phones have different capabilities, or maintenance has not occurred for an extended period.

---

## Core Principle

**Offline is not an error state.**

Avrana Party is expected to function without Internet access.

Internet connectivity may be used for:

- certificate renewal
- firmware availability checks
- game update availability
- optional downloads
- account or cloud features if they ever exist

But ordinary local gameplay must not depend on Internet access.

---

## Why HTTPS Matters

HTTPS provides two separate benefits:

1. **Transport trust/security**
   - encryption
   - authenticated server identity
   - integrity against in-transit modification

2. **Secure browser context**
   - unlocks browser APIs intentionally restricted to trusted origins

The second category is strategically important.

Relevant secure-context-only or secure-context-dependent capabilities may include:

- Service Workers
- managed offline caching
- persistent-storage requests
- installable PWA behavior
- Gamepad API
- WebGPU
- WebCodecs
- Screen Wake Lock
- camera/microphone APIs
- WebHID
- WebUSB
- Web Bluetooth
- other advanced browser/device APIs

Therefore HTTPS is not merely “the feature that lets us download games.”

It enables the browser to behave more like a trusted application runtime.

---

## What Plain HTTP Can Still Do

HTTP does not automatically make Avrana Party unusable.

Depending on browser support, games may still use:

- HTML/CSS/JavaScript
- Canvas
- ordinary WebGL
- WebAssembly
- touch controls
- HTTP asset loading
- ordinary WebSockets
- room/lobby systems
- authoritative realtime multiplayer
- turn-based multiplayer
- local storage mechanisms with reduced guarantees
- centrally streamed experiences that do not require secure-only browser APIs

Many simple browser-native party games may function almost identically over HTTP.

This is why recovery should degrade selectively rather than globally.

---

## Consumer-Facing States

Consumer-facing states may remain simple.

### Full Mode

Trusted HTTPS is healthy and all required secure-browser features are available.

### Offline Mode

No Internet is available, but local HTTPS and all expected capabilities remain healthy.

This should appear normal.

Do not show an ominous “OFFLINE” warning merely because the Internet is absent.

### Recovery / Limited Mode

One or more capabilities are degraded.

Possible triggers:

- expired or invalid public certificate
- corrupted package
- incompatible game version
- failed system update
- insufficient storage
- crash-looping game runtime
- missing content pack
- database failure
- thermal/performance restriction
- client-specific capability loss

Consumer language should explain:

1. what happened
2. what still works
3. what Avrana already did automatically
4. what the user must do, if anything

Avoid raw PKI/browser terminology unless the user opens Technical Details.

---

## Internal Model: Capabilities, Not Modes

Internally, do not implement one global boolean such as:

```text
limited_mode = true
```

The system should evaluate:

### Device capabilities

Examples:

- public HTTPS healthy?
- clock valid?
- certificate valid through what date?
- Internet currently available?
- native app repair material available?
- CPU/GPU capacity?
- encoder capacity?
- package storage healthy?

### Seat capabilities

Examples:

- native Avrana app?
- browser?
- secure browser context?
- WebAssembly?
- Gamepad API?
- WebGPU?
- WebCodecs?
- persistent storage?
- capable of local emulation?
- capable of local game runtime?
- controller attached?

### Game requirements

Examples:

- secure context required?
- service worker required?
- native app required?
- local execution available?
- central streaming fallback?
- maximum players by execution path?
- controller requirement?
- personal viewport support?

The capability scheduler should combine all three.

---

## Mixed-Capability Party Example

Party:

- Seat 1: Avrana native app
- Seat 2: Avrana native app
- Seat 3: Avrana native app
- Seat 4: browser over HTTP because the public certificate is expired

Game supports:

- local native execution
- central streamed fallback

Preferred result:

- Seats 1–3 execute locally
- Seat 4 receives a centrally rendered fallback stream

Do not downgrade all four players to the weakest execution path.

---

## Avrana.net Prototype Trust Model

The user currently owns `avrana.net`.

This is suitable for prototype HTTPS work.

Conceptual prototype hostname:

```text
party.avrana.net
```

or:

```text
<device-id>.party.avrana.net
```

Local Avrana DNS resolves that hostname to the Avrana Party device's local IP.

Example:

```text
A7K2.party.avrana.net
        ↓ local DNS
192.168.x.x
```

The traffic can remain entirely local while the browser sees a publicly trusted hostname/certificate.

Final commercial branding may use a different domain without changing the architecture.

---

## Certificate Identity vs Device Identity

Treat these as separate trust systems.

### Public Browser Identity

Purpose:

- trusted HTTPS for Safari/Chrome/etc.
- short-lived public certificate
- browser secure context

This identity expires and must be renewed.

### Permanent Device Identity

Purpose:

- identify the physical Avrana Party device
- authenticate to the Avrana app/backend
- enable recovery even if the public browser certificate is expired
- survive browser-certificate lifecycle changes

This should use a long-lived device keypair or equivalent secure identity.

An expired browser certificate must not mean the physical device has lost its identity.

---

## Do Not Share One Retail Private Key

A prototype may use a single certificate.

A commercial fleet should not ship every device with the same wildcard private key.

If one unit exposes that shared key, every unit would inherit the compromise.

Preferred future direction:

```text
Device A7K2
- unique device identity
- unique key material
- device-specific public browser certificate

Device B91F
- unique device identity
- unique key material
- device-specific public browser certificate
```

Exact provisioning design is open.

---

## Offline Safety Reserve

Do not define a device as healthy merely because its certificate has not expired yet.

Instead track:

**Full Offline Runway**

Question:

> If Internet disappears right now, how long can Avrana guarantee trusted Full Mode?

Avrana should renew before the actual expiration boundary.

Conceptual rule:

```text
certificate remaining life > configured offline reserve
    → healthy

certificate remaining life <= configured offline reserve
    → renew automatically when Internet is available
```

A reserve around 10–14 days is conceptually attractive for normal flights, cruises, camping, trips, conventions, etc., but the exact number should be validated against current CA renewal policies.

The system should attempt renewal whenever:

- Internet becomes available
- renewal is permitted
- remaining offline runway is below target

The user should not need to press a “renew certificate” button.

---

## Consumer Telemetry

Default UI can simply show:

```text
Offline Ready ✓
```

Advanced UI may show:

```text
Full Offline Mode available through:
October 18
```

or:

```text
Public HTTPS:
Healthy

Offline runway:
17 days

Last maintenance sync:
September 25
```

This gives technically interested users visibility without forcing the information on everyone.

---

## Automatic Security Restoration

If the Avrana Party device itself gains Internet access, it should automatically perform maintenance necessary to restore expected secure operation.

Examples:

- correct clock/time
- check certificate state
- renew certificate if needed
- install renewed certificate
- reload/restart only the required web service where possible
- restore Full Mode

Do not ask:

> Would you like to renew your TLS certificate?

Ordinary users should never act as PKI administrators.

If a full system reboot is truly required, ask only at the point where the disruptive action is needed.

---

## Update Consent Boundary

Preferred rule:

**Security restoration is automatic. Product-changing updates require consent.**

### Automatic

Examples:

- certificate renewal
- trust-chain maintenance
- time synchronization
- small security metadata required for basic operation
- repair actions that restore the existing expected state without materially changing behavior

### Ask First

Examples:

- firmware/OS version upgrades
- game updates
- new games
- large content packs
- substantial behavior changes
- operations requiring meaningful downtime
- operations consuming substantial storage/bandwidth

---

## Avrana App as Offline Maintenance Courier

The native Avrana app may act as a data courier.

While the phone has Internet:

```text
Avrana App
  ↓
downloads:
- firmware packages
- game packages
- compatibility metadata
- recovery metadata
- device-specific material when possible
```

Later, with no Internet:

```text
Phone
  ↓ local Wi-Fi / peer connection
Avrana Party
```

The app transfers the cached material.

This supports a deliberately isolated appliance.

---

## Important Certificate Constraint

Ordinary firmware/game packages can be cached indefinitely.

Public TLS certificates cannot be treated as timeless update packages.

They expire.

Therefore:

- the app can carry a fresh certificate for a known device if it obtained one while online
- the app cannot manufacture a new publicly trusted certificate offline for an unknown device
- the app itself may still authenticate an expired device using the permanent device identity

---

## Drawer-for-a-Year Scenario

Example:

- Avrana Party sits unused for one year
- public browser certificate expires
- user takes it onto an airplane
- no Internet is available

Possible cases:

### Case A — App already knows the device and has fresh device-specific recovery material

The app can:

- authenticate the device using permanent device identity
- push firmware/game updates
- push a fresh certificate if one was acquired beforehand
- restore browser Full Mode

### Case B — App knows the device but has no current certificate material

The app can still:

- authenticate it
- update it
- diagnose it
- run native-app-capable experiences

But browser Full Mode cannot be restored without obtaining a new public certificate.

### Case C — Unknown device + expired cert + no Internet

The native app may still pair/authenticate using the permanent device identity, depending on pairing design.

However, a new publicly trusted browser certificate cannot be generated from nothing while offline.

Browser-only users remain in a degraded capability state until a valid certificate can be obtained.

---

## Recovery Paths

There should be multiple recovery options.

### Path 1 — No recovery needed

Device has no Internet but HTTPS is still healthy.

Operate normally.

### Path 2 — Give Avrana Party Internet

Possible sources:

- home Wi-Fi
- Ethernet
- phone hotspot
- other Internet-enabled network

Avrana automatically repairs security/trust state.

### Path 3 — Native App Courier

The Avrana Party remains isolated.

An Internet-prepared Avrana app transports available maintenance material to it later.

---

## Recovery UX

Example consumer-friendly presentation:

```text
Some browser features are temporarily unavailable.

You can still play compatible games.

Available now:
- 14 games for all 6 players
- 5 more games for up to 4 players

To restore everything:
Connect Avrana Party to the Internet briefly,
or use an Internet-prepared Avrana app.
```

Technical details may be available separately.

---

## Game-Level Degradation Metadata

Games should describe capability requirements and fallbacks.

Conceptual example:

```yaml
requirements:
  secure_context: false
  service_worker: optional
  gamepad: optional
  webgpu: false

fallbacks:
  http_browser:
    supported: true
    max_players: 6
    disabled_features:
      - managed_offline_install
      - browser_gamepad
```

Another game may say:

```yaml
requirements:
  secure_context: true
  webgpu: true

fallbacks:
  central_stream:
    supported: true
    max_players: 4
```

Avrana computes actual availability from the party's current capability graph.

---

## Consumer Availability Categories

Prefer simple labels.

### Ready

Works normally.

### Limited

Playable, but one or more features differ.

Examples:

- touch controls only
- fewer seats
- central streaming instead of local execution
- no install/cache persistence
- no spectators
- reduced resolution

### Requires Full Mode

No acceptable fallback currently exists.

The UI should explain the specific reason in normal language.

---

## Current Trust/Recovery Requirements

Treat these as high-priority requirements:

1. prove trusted HTTPS on the local Avrana network
2. prove browser secure-context behavior on real iPhone and Android devices
3. prove automatic certificate renewal when Internet appears
4. track offline runway, not only expiry
5. prove app-to-device maintenance transfer without Internet
6. prove an expired public cert does not prevent native app recovery
7. prove mixed app/browser seats can use different execution paths
8. prove Limited/Recovery UI accurately reflects actual per-seat capabilities

---

## Strong Current Principles

- Offline is normal.
- No Internet banner should appear merely because Internet is absent.
- Public browser trust and permanent device identity are separate.
- Certificate repair should be automatic where safe.
- The system should renew before the edge of expiry.
- One weak seat should not degrade the whole party.
- Recovery should preserve as many games/seats as possible.
- Consumers should see consequences and remedies, not PKI jargon.
- Expert users may inspect detailed telemetry.
