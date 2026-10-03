# ADR 0012 — Party remains usable when trusted HTTPS is unavailable

Status: **accepted (direction) · proposed (mechanisms) · not implemented** · Date: 2026-10-02
Supersedes: the "HTTPS-only Party page" consequence of ADR 0004 D1 (see §Supersession).
Implementation and the detailed identity/continuity design belong to
[AVR-225](https://linear.app/avranakern/issue/AVR-225/define-and-implement-limited-mode-when-trusted-https-is-unavailable);
Linear owns sequencing. Nothing in this ADR is deployed: production still serves `/party/`
HTTPS-only as [SYSTEM](../SYSTEM.md) and [FULL-MODE](../design/FULL-MODE.md) describe.
Context: [ADR 0004](0004-full-mode-contracts-and-providers.md), [ADR 0006](0006-party-session-protocol.md) D3,
[PARTY-PLATFORM](../design/PARTY-PLATFORM.md) §4/§13, [OFFLINE-TRUST-AND-RECOVERY](../OFFLINE-TRUST-AND-RECOVERY.md),
[GAME-PLATFORM-ARCHITECTURE](../GAME-PLATFORM-ARCHITECTURE.md) ("think in capabilities").

## Context

ADR 0004 D1 made `https://party.avrana.net` the canonical origin and declared the Party page
HTTPS-only, with plain HTTP kept for captive probes and a link to the legacy LAN Games hub as the
only fallback. The Party cookie (`avrana_device`, ADR 0006 D3) is `Secure`, so Party identity exists
only in the trusted HTTPS origin.

The appliance is designed to run offline for days or weeks. Its certificate is a public Let's
Encrypt certificate that must be renewed through an upstream connection the Party does not
otherwise need. The [2026-10-02 architecture review](../findings/2026-10-02-architecture-review.md) (Linear AVR-224) concluded
that a product whose core experience disappears when a certificate lapses, when Party DNS is
overridden by a phone's private DNS, or when a browser refuses the chain, has made trusted TLS a
hard dependency that the product principles ("offline-first", "no app", "no Internet") forbid.

At the same time, several real features legitimately need a secure context: Screen Wake Lock,
service workers and the offline copy, `crypto.subtle`, WebRTC without warnings, camera and
microphone, and the `Secure` cookie itself. Those cannot be wished into existence on `http://`.

## Decision

1. **Two product modes, one Party.** *Full Mode* is the Party reached over a browser-trusted
   HTTPS origin; it remains the preferred and default experience. *Limited Mode* is the same
   Party reached when trusted HTTPS is unavailable (expired or untrusted certificate, DNS override,
   a browser that cannot complete the chain, or a deliberate plain-HTTP fallback). Both are
   consumer-facing names for a capability state, not separate code bases or separate parties.
2. **Loss of trusted HTTPS must not disable the Party.** In Limited Mode, as far as the browser
   and platform permit, these keep working: Party membership, presence, host authority and
   succession, synchronized Party navigation (ADR 0011's one location), game selection, launch and
   play of compatible games, and ordinary phone-only Party operation with no TV, no app and no
   Internet.
3. **HTTPS-dependent capabilities degrade individually**, per capability and per seat, in the
   spirit of ADR 0004 D2: wake lock, the offline copy, secure-context-only APIs and games whose
   contract requires `secure_context` fall back, are explained, or are unavailable for that seat.
   The Party never takes the minimum across seats, and a weak seat never downgrades the Party.
4. **Limited Mode is visible and understandable.** The shell says plainly that the connection is
   not secure, which conveniences are missing, and how Full Mode is restored (typically: renew the
   certificate when upstream is available). It never pretends to be Full Mode and never hides the
   browser's warning behind product chrome.
5. **An explicit identity and continuity model is required.** Limited Mode needs its own answer
   to "which device is this and which member is it?" because the `Secure` cookie is not sent over
   plain HTTP and the two schemes are separate origins. That model is designed in AVR-225 and
   recorded here when accepted. Constraints it must satisfy:
   - the existing `Secure` cookie is **never** weakened or renamed to work on HTTP (§Rejected);
   - a Limited Mode credential is a distinct, server-issued credential with its own scope and
     lifetime, mapped to the same `device_id` where the server can establish that safely, otherwise
     treated as a new device (ADR 0003: identifiers are mapped, never derived);
   - member continuity across a mode switch is a product goal, not a guarantee; where it cannot be
     proven, the phone is admitted as a new member and the UI says so;
   - nothing in Limited Mode grants admin authority or elevated Party authority, and PIN entry or
     profile claiming over plain HTTP is either disabled or explicitly labelled as exposed.
6. **The product goals are unchanged.** The no-app, no-TV, no-Internet Party is the baseline and
   must survive certificate failure. Trusted HTTPS makes it better; it is not the licence to run.

## Supersession

- **Superseded in ADR 0004 D1:** the consequence "HTTP is not a recovery path for the Party page,
  which is HTTPS-only; the shell links guests to `http://10.42.0.1/` (the LAN Games hub) when HTTPS
  can't be reached", and the implicit assumption behind FULL-MODE's "Can't reach the party"
  state that a Party without trusted HTTPS is a Party without Party Home. The LAN Games hub is not
  the fallback product (ADR 0014).
- **Still in force from ADR 0004 D1:** `https://party.avrana.net` is canonical; Avrana pages live
  under `/party/`; no HSTS, ever; the TLS key stays on the Pi; no private CA on phones; captive
  probes on port 80 are unchanged. No HSTS is now load-bearing: it is what keeps an expired
  certificate escapable into Limited Mode.
- **Still in force from ADR 0004 D5:** the offline copy is a convenience, not a recovery
  mechanism. Limited Mode is the recovery mechanism.
- ADR 0004's historical text is left as written; this ADR is the dated correction.

## Rejected

- **Dropping `Secure` from `avrana_device`.** It would silently expose the long-lived device
  credential to any peer on the Wi-Fi during HTTP use and collapse two origins into one cookie jar
  by accident. Limited Mode gets an explicit model instead.
- **A private CA or self-signed certificate installed on phones.** Rejected by ADR 0004 and by the
  no-setup principle.
- **HTTP-only Party.** Rejected: Full Mode's secure-context features are real value.
- **An app as the recovery route.** Rejected as a baseline; an app may only add convenience.

## Consequences

- FULL-MODE gains an accepted *target* contract beside its deployed description; SYSTEM continues
  to describe the deployed HTTPS-only behaviour until a verified deployment changes it.
- `contracts/capabilities.v0.json` already names `secure_context`; game contracts that need it
  will declare it, and the catalog/evaluation path reports it per seat. No contract change is made
  by this ADR.
- The nginx port-80 default server will eventually serve Party pages in Limited Mode. That is a
  live-system change requiring an owner-approved deployment (AGENTS); it is not implied here.
- Tests for Limited Mode belong to Tier 2 (real nginx, both schemes) and Tier 3 (a real phone
  with an expired certificate), per ADR 0004 D6.

## Deliberately open

The exact Limited Mode credential, its mapping to `device_id`, how a phone moves between modes
without losing its member, what the HTTP doorway page shows, whether `/` becomes Party Home, and
what the QR code carries (ADR 0004's open items remain open).
