# Owner app architecture (proposal)

- **Status:** Proposal, feeding AVR-45 and AVR-315 (and, for entitlement placement, AVR-316). Not an ADR, not a decision, nothing built. Contains labelled external facts; those marked unverified are unverified.
- **Date:** 2026-10-10
- **Sources:** Linear AVR-45, AVR-143, AVR-315, AVR-316, AVR-317 (read 2026-10-10) and AVR-37, AVR-39, AVR-44, AVR-63, AVR-65, AVR-79; ADR 0002, 0004, 0012, 0013, 0014, 0016; `docs/design/PARTY-PLATFORM.md`, `docs/design/GAME-INSTALLATION.md`, `docs/design/ONBOARDING.md`; Let's Encrypt rate-limit and lifetime documentation (cited in the 2026-10-09 draft).
- **Related:** `docs/research/BLE-OWNER-CONTROL-PLANE-SPIKE.md`, `docs/research/MOBILE-STORE-POLICY-RESEARCH.md`, `docs/research/AVRGAME-EXPERIMENTAL-DRAFT.md`

## Reading guide

Labels: **[A]** accepted (ADR or owner decision on record), **[D]** described as deployed in canonical docs at the time of the 2026-10-09 draft (not re-checked), **[P]** proposed here, **[unverified]** not confirmed from a primary source. Owner statements in Linear on 2026-10-09 and 2026-10-10 are marked **[Approved direction]**.

## Where this proposal needs new ADRs or amendments

This document is a proposal and creates no authority. If adopted, it would require:

1. **A new ADR for owner authority, pairing and BLE management.** A new radio surface and trust boundary (owner keys, claim window, command signing) that no accepted ADR covers. ADR 0004 and ADR 0012 do not mention it.
2. **Amendments to ADR 0004 (D1: TLS key stays on the Pi) only if** a per-appliance hostname scheme (certificate option B, section 7) is chosen; that also amends ADR 0013's host plan. No amendment is needed for option A.
3. **An amendment or successor to ADR 0002's "Open installation, no store ... no marketplace, payments, reviews, DRM" and "No app ... required"** to record the approved optional storefront and commercial owner app (AVR-143, AVR-45, AVR-317). The "no app required for guests" rule is unchanged.
4. **A note in ADR 0014** that the "community/marketplace workflow" it left undecided is now partly directed by AVR-143 and AVR-316.
5. **Possibly an ADR for the entitlement boundary** (AVR-316) once offline entitlement approaches have been evaluated.

## 0. Position in one paragraph

Guests keep playing in a phone browser over the appliance Wi-Fi [A: AGENTS, ADR 0004 D2, ADR 0012
decision 6]; they never need an app. The owner app is a **separate native product for the person who owns the
appliance**. Per AVR-45 (revised 2026-10-09) it is a first-class requirement for commercial launch and the intended
normal owner management experience **[Approved direction]**, while friend-ready 1.0 has no app dependency. It never
carries gameplay. It does four jobs: first-run setup and out-of-band control
over BLE; carrying signed things (packages, certificates, updates) between the Internet and an
offline appliance over Wi-Fi or USB; surfacing the optional official storefront (AVR-143); and hosting a cached
game client in a trusted viewport (AVR-45, sequenced after the other three). The **appliance validates, installs and owns everything**; the app is a courier and a
remote control, never a root of trust for code [A: AVR-45, AVR-63, AVR-143 owner text 2026-10-06].

## 1. Reconciliation with Linear records (as read 2026-10-10)

- **AVR-45** (commercial owner app, trusted game host, offline courier) was revised on 2026-10-09: the app is a first-class commercial-readiness requirement and the intended normal owner interface, optional for every guest, never authoritative for game state, trust installation or administrative commands. BLE is "a deliberately narrow low-bandwidth management/control plane, never as game streaming transport". Open owner decision: whether retail activation literally requires the app, versus app-default commissioning with independent recovery. **This document does not decide it** (see section 5.4).
- **AVR-315** (secure BLE owner pairing and management control plane) now exists and owns the BLE design. It excludes packages and certificate payloads from BLE. The implementation-ready proposal is in `BLE-OWNER-CONTROL-PLANE-SPIKE.md`.
- **AVR-316** (licensed publisher delivery and offline entitlement boundaries) owns the entitlement research; section 6 here only fixes where entitlement verification sits.
- **AVR-143** is decided: an optional official storefront for licensed games coexists with open `.avrgame` installation. The earlier "AVR-143 must be decided before any commerce design" no longer applies; implementation remains gated on demonstrated demand and is off the friend-ready 1.0 critical path.
- **AVR-63** courier trust contract, **AVR-64** LocalSend-style prototype, **AVR-65** CSR certificate courier, **AVR-79** offline clock: these define the Wi-Fi courier. Section 7 adds two constraints AVR-65 should absorb.
- **AVR-44** owner onboarding/recovery/administration, **AVR-76** QR/NFC onboarding, **AVR-60** owner install/update/rollback UX, **AVR-86** Party Ready, **AVR-74** Health: the app is their likely surface; this document supplies a transport (BLE control) and an identity (owner key) they have not defined.
- **AVR-37** `.avrgame` v0, **AVR-39** AvrGameProvider, **AVR-58** signed metadata, **AVR-78** key rotation/revocation, **AVR-62/69** permissions and trust tiers, **AVR-82** signed appliance updates: nothing here defines the package. AVR-39 is the single install path and the app only hands it bytes (section 6).
- Done: **AVR-225** Limited Mode (the certificate-expiry fallback), **AVR-226** origins, **AVR-236/259** provisioning and routing (the install primitive), **AVR-238** Checkers. **AVR-31** certificate renewal timer: Todo as of 2026-10-09.
- Canonical docs still say BLE is deferred ("BLE is deferred until genuinely useful" in ONBOARDING; "BLE discovery only if useful later" in PARTY-PLATFORM). That conflict is listed for AVR-317.

## 2. Platform facts that shape the design

- Appliance: **Raspberry Pi 4**, Debian 13, `eth0` management, `wlan0` AP 10.42.0.1 [D: SYSTEM]. On-board
  BLE 5.0 on the same radio chip as the AP **[unverified: hardware spec, SYSTEM never mentions
  Bluetooth]**; coexistence must be measured (see `BLE-OWNER-CONTROL-PLANE-SPIKE.md`). No extra USB radios: one cured under-voltage.
- TLS key stays on the Pi, no private CA, no HSTS [A: ADR 0004 D1, ADR 0012]. Cert is public Let's Encrypt,
  DNS-01 via lego, Cloudflare token Pi-only; the renewal timer is optional and not installed (AVR-31) [D].
- Services get separate identities [A: ADR 0016, not deployed]. Admin is separate from Host and a host
  can never escalate [A: PARTY-PLATFORM §7].

## 3. Trust-boundary diagram

```mermaid
flowchart LR
  ST[Internet: catalog, publishers, ACME + DNS] -- HTTPS, app online --> APP
  APP[Owner phone app: courier + remote control<br/>holds owner private key, cached signed blobs]
  subgraph PI[Appliance - root of trust]
    BLE[owner BLE service, pairing, commands] --> ADM[owner public keys, trust roots]
    ADM --> INST[validate + install: AVR-39 -> provision-game]
    ADM --> CERT[cert store + TLS key, never leaves Pi]
    INST --> GAMES[avrana-game@slug, DynamicUser, Unix sockets]
    CORE[Party Core: identity, lobby, results] <--> GAMES
  end
  APP -- BLE: control and transfer tickets only --> BLE
  APP -. local Wi-Fi HTTPS, ticketed bulk .-> INST
  GUEST[Guest phones: browser only] -- Wi-Fi: party.avrana.net, games.avrana.net --> CORE
```

Trust rules, in order: (1) only the appliance decides what runs; (2) the app proves *who the owner
is* (a key), never *what is safe*; (3) a package signature proves publisher identity and integrity,
never safety (GAME-INSTALLATION already says so [A]); (4) guests are untrusted browsers and
never reach BLE or owner APIs; (5) Wi-Fi guests and the BLE radio are disjoint attack surfaces.

## 4. BLE for management, and why not Wi-Fi

**Why BLE for control [P]:**
- It works when Wi-Fi is not yet configured or has failed (first run, bad Wi-Fi secret, AP down,
  `wlan0` misrouted). The Pi's own AP is the thing being managed; managing it over itself is circular.
- It gives **proximity as a security signal**: radio range of a few metres plus a physical-presence
  proof (§5) without putting management APIs on the guest-reachable LAN.
- It avoids the iOS Local Network permission prompt and Wi-Fi switching (the phone often prefers
  mobile data on a no-Internet AP; owner must manually keep the Party Wi-Fi). See `MOBILE-STORE-POLICY-RESEARCH.md`.
- Guests on the same Wi-Fi cannot see a BLE-only management surface.

**Why not BLE for bulk [P, aligned with AVR-315]:** BLE throughput is kilobytes per second; a game package is tens to
hundreds of MB. BLE carries owner commands, status and health events, and a one-time **transfer ticket** that names a
staging slot. Packages, certificate requests and certificates, manifests and any other payload go over local Wi-Fi to an
owner-authenticated, short-lived HTTPS endpoint (section 6), or over USB/file import. This follows AVR-315: BLE is not for
"game traffic, video, packages or certificate payloads". An earlier draft allowed small signed blobs over BLE; that is withdrawn.

**Why not Wi-Fi-only management:** needs the phone joined to the Party AP (kills phone Internet,
the very thing the courier needs), exposes an admin port to every guest, and cannot bootstrap.

**GATT service outline [P], one primary service `Avrana Owner`:**

| Characteristic | Properties | Content |
|---|---|---|
| `Info` | read, unauth | protocol version, appliance public id (short hash of identity key), state (unclaimed / claimed / pairing window open), firmware build. No secrets, no owner data |
| `PairControl` | write, indicate | pairing messages (§5.1); only active while a physical window is open |
| `Command` | write (encrypted + authenticated link, plus app-layer signature) | framed requests: status, set Wi-Fi/AP, open/close Party, open a staging slot (returns a ticket, no payload), confirm install of an already-verified staged package, request certificate renewal (returns a ticket), list/revoke owner keys |
| `Response` | indicate | framed replies, chunked, with sequence numbers |
| `Event` | notify | health: cert days left, update ready, storage low (feeds AVR-74/AVR-84 models) |

Rules: link-layer encryption is necessary but **not sufficient**; every `Command` carries an
application-layer signature by the owner key and a monotonic counter so BLE bonding quirks and
replays cannot grant authority. Advertising is minimal (appliance id, "claimable" bit); the name
never carries the venue or owner.

## 5. Secure pairing

### 5.1 Threat model

| Threat | Adversary | Required defence |
|---|---|---|
| Stranger in radio range claims an unowned appliance | bar patron, neighbour | claim only while a **physical-presence window** is open (§5.2); one owner at a time |
| Man-in-the-middle during pairing | active radio attacker | LE Secure Connections with an authenticated association model, or an OOB secret, never Just Works alone; app-layer key exchange bound to a code shown on the device or printed |
| Replay or relay of owner commands | in-range or relayed radio | signed commands with counter and appliance-nonce; short session keys |
| Lost or stolen phone | thief | owner key in the phone's secure hardware, gated by device unlock/biometric; **revocation from a second owner key, a recovery code, or a physical reset** |
| Malicious guest uses Party Wi-Fi to reach owner functions | guest | owner functions are not on the LAN-reachable APIs; Host/Admin web roles stay as defined |
| Compromised app update or fake app | store, phishing | app is never a root of trust; worst case it asks the appliance for things the appliance can refuse; appliance shows what it is about to do |
| Reseller or previous owner retains control | second-hand sale | factory reset by physical action clears owner keys and Wi-Fi/Cert state |
| Out of scope | root on the Pi, physical storage access | [A: ADR 0016 "not promised": storage unencrypted] |

### 5.2 Physical-presence proof (options, one to choose in the spike)

1. **Hardware button / GPIO press** opens a 120 s claim window. Strongest; the Pi 4 has no button, so it
   needs a case/HAT **[open: product hardware]**.
2. **One-time code shown by the appliance** (HDMI, or a label on the case) used as PAKE/OOB input. A
   printed label is cheap, but whoever holds it can claim an unclaimed unit: claim once, then rotate.
3. **Power-cycle window** (claim only N minutes after boot): weak alone, a useful gate. NFC tag (AVR-76)
   is a fourth option that adds a hardware item.

Recommendation [P]: code from (2) plus window from (3) for the Pi-class unit now; (1) for any
shipped unit. The pairing messages run **SPAKE2+ or a similar PAKE [unverified choice]** over
`PairControl`, giving a session key that does not depend on BLE's own pairing quality, then the
phone enrols its **owner public key**. BLE bonding is a convenience on top, not the trust anchor.

### 5.3 Owner key on the appliance

- The app creates an asymmetric keypair in the phone secure element/Keystore/Secure Enclave
  (non-exportable where the platform allows). Public key is stored on the appliance in a root-owned
  `owner-keys` file with label, created-at, last-used, and a role.
- Roles [P]: `owner` (can add/revoke keys, install, rotate cert, factory reset) and optionally
  `courier` (may stage signed blobs only). Multiple owner keys allowed, so a lost phone is revoked by
  another phone, a recovery code held offline, or physical reset.
- **Relation to Admin vs Host [A: PARTY-PLATFORM §7]:** Owner is an *appliance role* like
  Owner/Admin/Developer ("bind to admin sessions, never to a presence"), carried by a key rather than a
  PIN. Host stays a per-party game role and **cannot escalate**. The owner app is the Admin
  transport, not a new tier above them. Whether the web Admin PIN continues to exist, and
  whether a paired owner can mint a short-lived Admin session for the web shell, is a **design
  question for AVR-44**; keep the two credentials independent until decided.
- Recovery: printed recovery code at claim time (stored hashed on the appliance); loss of all keys
  and the code means physical reset. State this in the product, not in docs only.

### 5.4 Mandatory activation (open owner decision; not decided here)

AVR-45 and AVR-315 leave open whether retail activation literally requires the app. Two shapes, for the owner to choose:

| Shape | Effect | Risk |
|---|---|---|
| App-default commissioning with independent recovery | The app is the normal and documented path; a documented non-app path (physical reset, console or web Admin) can also commission | Weaker commercial lock-in to the app; matches the "no cloud account to play" principle |
| Activation requires the app | The appliance cannot be claimed without the app | A lost or banned app, a store-policy change or an unsupported phone strands an owner; recovery must still exist, so a non-app path exists anyway |

Recommended default for the owner's consideration **[P]**: app-default commissioning with independent recovery, because recovery without a functioning app is already required (AVR-45 exit criteria, AVR-315 acceptance) and the second shape still needs that path.

## 6. Appliance-owned installation and the offline courier

**Principle [A: AVR-45, AVR-63, AVR-143]:** the courier transports; it has no authority to install,
trust or activate. This design therefore specifies *no* install logic in the app.

Flow [P], using the not-yet-existing `.avrgame` only as "an opaque signed bundle":

1. App online: fetches `bundle + signed metadata` (TUF-style roles per AVR-58 and AVR-63) from the
   official catalog, a publisher, or any source, and caches them.
2. App near appliance: connects over BLE, authenticates with the owner key, and asks the appliance
   to open a **staging slot**; the appliance returns a one-time transfer ticket and its current
   trust state (installed versions, clock policy, revoked keys).
3. All package bytes go over local Wi-Fi (appliance staging endpoint, ticket-bound) or USB; none go over BLE.
   Appliance writes only to a quarantine directory, owned by an unprivileged identity. (Joining the Party AP costs the phone its
   Internet path and triggers the iOS Local Network prompt; this is a usability cost to be measured in AVR-63/AVR-64, not solved here.)
4. **Appliance verifies**: signature chain against *appliance-held* trust roots, rollback/freeze
   counters, hash, compatibility (Game Contract), requested permissions vs the appliance grant
   (ADR 0004 D3: package requests, appliance decides).
5. Appliance shows an install summary to the owner (in app via BLE `Event`, and optionally the web
   Admin surface) and installs through **AVR-39 -> `provision-game`** (root, DynamicUser template).
   Nothing is activated before the owner confirms with a signed `install` command.
6. Rollback: appliance keeps the previous version (GAME-INSTALLATION already requires it).

**Entitlements [P, research owned by AVR-316; not designed here]:** a paid title is a normal signed bundle plus a separate
signed **entitlement token** bound to an appliance id or owner key and verified offline. Preserving
offline play after purchase (AVR-143 criterion) means verification needs no server call; revocation
only propagates when a courier next reaches the Internet (state this to the owner). Not
buildable before AVR-316 has evaluated at least two offline entitlement approaches and the offline clock policy (AVR-79) is decided. This document does not choose an approach, and does not assume permanent-online checks or DRM.

**Trust tiers and sideload [P, builds on GAME-INSTALLATION tiers and AVR-69]:**

| Tier | Source | Appliance behaviour | Label shown to the owner |
|---|---|---|---|
| Built-in | shipped in the release tree | root-owned, normal isolation | "Avrana" |
| Official | signed by Avrana store root | signature + entitlement verified | "Avrana catalog" (curated, **not** a safety claim) |
| Publisher | signed by a key the owner has pinned | same isolation as unsigned; update only by same key | "Publisher X (key abc123)" |
| Sideload | unsigned or unknown key, any source | owner confirms permissions and a hash; runs in the strictest tier; updates drop to unapproved until re-confirmed (already in GAME-INSTALLATION) | "Not reviewed by Avrana. Runs only on this appliance." |

The unrestricted technical sideload path **never routes code through the phone's app store policy**
because the code is not run on the phone (it runs on the appliance as a native process). To remain
true: sideload must also be possible with **no app at all** (USB file, web Admin upload, SSH),
so the app is never the only door. Whether the *app* may carry sideloaded bundles at all is a
store-policy question for counsel (`MOBILE-STORE-POLICY-RESEARCH.md` §A).

## 7. Certificate delivery to an offline appliance

Facts [carried from the 2026-10-09 draft, which cited the Let's Encrypt documentation; not re-verified on 2026-10-10]: Let's Encrypt allows **5 duplicate certificates per 7 days with no
override**, and 50 per registered domain per week (override available for that one) (Let's Encrypt
rate limits). Default lifetime falls to 64 days on 2027-02-10 and 45 days on 2028-02-16 (Let's
Encrypt, 2025-12-02), so an offline trip longer than ~3 weeks will eventually outlive the
cert. DNS-PERSIST-01 is announced for 2026 **[unverified availability]**.

**Constraint from accepted ADRs:** the TLS private key stays on the Pi and no private CA on phones
[A: ADR 0004 D1, ADR 0012]. The earlier runbook already anticipates "a Companion courier could
transport a CSR and the returned certificate" [D: party-https runbook]. This design keeps that.

| Option | Who holds the key | How it works | Risk | Verdict |
|---|---|---|---|---|
| A. CSR courier, one shared hostname (AVR-65) | Pi | Pi makes key + CSR; app fetches the CSR over Wi-Fi and relays it to an ACME client that has DNS authority (Avrana-run service or the owner's lego/Cloudflare token); signed chain returns to the appliance over Wi-Fi via the app (never over BLE) | **A fleet of appliances all asking for `party.avrana.net` hits the 5/week duplicate cap with no override. Cannot scale past a handful of owners** | OK for field test; not for commerce |
| B. Per-appliance hostname (for example `<id>.party.avrana.net`) | Pi | A + a unique name per appliance; DNS-01 delegation via a CNAME to an Avrana-run ACME zone | Changes the canonical origin of ADR 0004 D1 and ADR 0013 (`games.` hosts); rate limit then 50/week/domain, overridable; wildcard hosts for games | **Needs a new ADR**; likely the right commercial answer |
| C. Avrana holds one shared key and ships the cert + key to every unit via the app | Avrana + every phone + every Pi | Simple | Contradicts ADR 0004 (key leaves the Pi); one extracted key lets anyone with DNS control impersonate `party.avrana.net` on any LAN; CA must revoke on disclosure, all units break | **Reject** |
| D. Wildcard on a parent, key shipped | as C | | as C, larger blast radius | Reject |
| E. Private CA installed by the app | the owner | profile install on phones | Rejected by ADR 0004 and 0012, and an iOS profile is a platform trust prompt guests would face | Reject |

Recommended [P]: **A for the field test, B designed for scale**, with the app as an *ACME transport
and DNS-delegation helper*, never a key holder. The ACME account key and the TLS key stay on the
Pi; the app relays signed ACME requests and never sees key material. Expiry handling:

- Appliance reports `days_left` over BLE `Event`; the app nags the owner while online and can
  pre-fetch a renewal at departure ("Party Ready", AVR-86).
- Short-lived-certificate profiles reduce exposure but raise the courier frequency; do not adopt
  until a measured trip length is known.
- **At expiry the appliance falls to Limited Mode `http://10.42.0.1`** [A: ADR 0012]. No HSTS makes
  this escapable. The app can restore Full Mode later by courier. The product must never make Limited
  Mode depend on the app or a certificate.
- Clock: an offline Pi without RTC may judge validity wrongly (AVR-79); courier must carry signed
  time evidence or the Pi must have an RTC. Open.

## 8. Wi-Fi for gameplay, and portable game-client hosting

Gameplay is **unchanged** [A]: Wi-Fi AP, `https://party.avrana.net` (Full) or
`http://10.42.0.1` (Limited), game origin `games.avrana.net`, guests in a browser, no app, no
account. This design adds nothing to that path.

Portable game-client hosting (AVR-45 scope) is a **sequencing question, not a scope reduction** [P]: it is part of the
approved product, and AVR-45 asks for its specification, but it is not required for the first owner-app milestone. When built: the appliance stays the only source of client bundles; the app fetches them over local Wi-Fi,
caches by hash and shows them in a WebView with no native APIs added; Avrana's shell owns the Party layer,
the game owns only its viewport (policy risks: `MOBILE-STORE-POLICY-RESEARCH.md` A1, A2, B2). Recommendation: **build owner management and the courier first and the client host after**, once AVR-139 shows cached browser relaunch on real phones. Store policy for the host mode is in `MOBILE-STORE-POLICY-RESEARCH.md`.

## 9. Assets x holders

| Asset | Appliance | Owner phone (app) | Guest phone | Avrana cloud / store | Publisher |
|---|---|---|---|---|---|
| TLS private key | **yes (only)** | no | no | no | no |
| TLS key, ACME account key, DNS token | **yes** (token optional) | no | no | Avrana-run ACME zone only under option B | no |
| Owner private key | no | **yes (secure hardware)** | no | no | no |
| Owner public keys, roles | **yes** | yes | no | no | no |
| Trust roots for signatures | **yes (root-owned)** | cached copy for display only | no | holds store root private key | holds own signing key |
| Signed package bytes | quarantine, then installed | cached while online | client bundle only | origin | origin |
| Entitlement tokens | **yes** (verifies) | carries | no | issues | no |
| Party cookie; game session keys | Party Core (+ that game) [A: ADR 0016] | no | cookie only | no | no |
| Wi-Fi/AP secret | **yes** | may display via BLE after owner auth | learns by QR/typing | no | no |
| Recovery code | hash only | owner stores plaintext offline | no | no | no |

## 10. Phasing and new ADRs

0 BLE spike (`BLE-OWNER-CONTROL-PLANE-SPIKE.md`, requires its own approved issue). 1 BLE claim, status, health events (needs ADR a). 2 Courier of signed packages over Wi-Fi (after
AVR-37/39/58, AVR-63, AVR-79). 3 Certificate courier (AVR-65; ADR b if option B). 4 Storefront client and
entitlements (AVR-143 direction, AVR-316 research, counsel; gated on demonstrated demand). 5 Trusted client-host mode (AVR-45 specification; AVR-139 evidence).
None of these phases is on the friend-ready 1.0 critical path.

**New ADRs or amendments required (see the list at the top):** (a) owner authority, pairing and BLE management: a new trust boundary and
radio surface; it states the app is optional for play. (b) per-appliance hostnames if cert option B:
amends ADR 0004 D1 and ADR 0013's host plan. **No conflict** with ADRs 0012/0013/0014/0016 provided
option C is rejected and Limited Mode never depends on the app. **ADR 0004 D1 (key stays on the Pi) is
the binding constraint.**

## 11. Explicit non-goals

- No gameplay, chat, lobby or identity through the app; guests never need it.
- No game authority, rules or server code on the phone; no native downloaded code on the phone.
- No private key export from the Pi; no private CA or profile on guest phones.
- No cloud account required to pair, run, sideload or play; no payment code in the appliance.
- No remote (Internet) management of the appliance in this design; courier only when the owner is present.
- No claim that a signature, curation or entitlement makes a game safe.
- No change to Host/Admin separation, `/party/` scope, HSTS (never), or the `Secure` cookie.
- No modification of the production Pi by agents; owner runs any deploy.
