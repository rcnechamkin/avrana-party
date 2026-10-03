# Finding: three focused architecture audits (2026-10-02)

Status: **review and recommendation, not a decision.** Companion to
[2026-10-02-architecture-review.md](2026-10-02-architecture-review.md); it does not repeat that
review and assumes its §1 reconstruction. Same evidence base: `main` `ae102f8`, the
`.work-avr213-games` checkout of the Games fork, ADRs 0001–0011, the design index, Linear on
2026-10-02. The Pi was not touched. Tags: **[E]** read in source, config, a dated finding or
Linear; **[I]** inference; **[R]** recommendation.

Three questions, asked without regard to implementation quality:

1. **Trust model.** Are identity, tickets, authority, replay protection, session ownership, local
   trust, browser trust and future third-party games *modeled* correctly?
2. **Scalability of the product.** What breaks between "BLUFF + Arcade" and "20 first-party games,
   downloadable `.avrgame`s, community content, several hardware generations, an owner app"?
3. **Obsolescence.** Designing today with no sunk cost: keep, replace, postpone.

---

## 1. Protocol and trust-model audit

The model has five principals: **device** (a browser profile on one phone), **member** (a device
that joined this party), **participant** (a member's role in one game session), **host** (one
member), and **game server** (one key per game id). The party service is the only authority for
the first four; a game server is the authority for its room. [E] `core.py`, `identity.py`,
`protocol.py`.

### 1.1 Identity: modeled correctly for what it claims, with one unmodeled principal

- [E] A device is a 256-bit server-minted secret in an `HttpOnly; Secure; Path=/party/;
  SameSite=Lax` cookie; only its hash is stored; a client can never choose its id. A member is
  `device → member` in memory; a participant is `member → participant` per session; tickets carry
  the participant id and role only. Names are display data, cleaned and uniqued server-side, and
  authorise nothing. This is the right layering, and it is unusually clean for a prototype.
- [E] **Membership is network reachability.** `join` has no secret: anyone who can reach the
  origin and send the right Origin header is a member. PARTY-PLATFORM §13 states this ("the Wi-Fi
  must not be open") and accepts it for friends parties. [I] It is the actual root of trust for
  guests: every other guest-side control (Origin, Host allow-list, cookie flags) protects members
  from *each other* and from cross-site pages, not from someone who has the Wi-Fi password.
  [R] Keep it, but write it as the first line of the trust model, because every future mode that
  weakens it (Public/Demo, a guest network, an owner app over the internet) must add a join
  secret (QR code, PIN, host approval) rather than hoping the cookie does the job.
- [E] **"Profile" is not a principal.** Name and avatar live in the phone's `localStorage` (shared
  `wc-name` with LAN Games), are re-sent on every join, and the server persists only
  `hash → device_id`. [I] The thing a guest thinks of as "me" is client-asserted display state;
  the thing the server thinks of as "you" is an opaque device id that authorises nothing. Both
  are correct today, but there is no server-side entity for a *person* yet, so stats, "welcome
  back", trusted devices and the owner app have nothing to attach to. The §13 design (profile,
  trust links, PIN) is the missing principal. [R] Introduce `profile` as a server entity before any
  feature stores anything about a person; do not let the localStorage name become that entity by
  accident.
- [E] **Two identity systems coexist in the Games process.** The browser-minted `wc-token`
  (`localStorage`, `x-wc-token` header) still authenticates players when no party session runs and
  "watch-only" sockets during one (`core/net.py` lines 313–318; `hubnet.js` lines 55–56, 160, 175).
  [I] Correct in effect for BLUFF, but it is a per-game-module invariant ("refuse `wc-token`
  players while a party session runs") enforced inside one file, not a property of the protocol.
  At 20 modules that invariant is 20 places to get wrong. [R] Decide whether standalone play is a
  product mode at all. If yes, model it as "a party session with an implicit roster" so there is
  one admission path; if no, delete the `wc-token` player path.

### 1.2 Tickets: modeled correctly as a capability; two properties are prototype-grade

- [E] A ticket is a typed, audience-bound (`aud = game`), session-bound, 120 s HMAC capability
  that names a participant and a role and nothing else. The game verifies signature → version →
  type → audience → time → session before trusting any field. This is the right shape: the party
  never tells the game who the device is, and the game never learns a secret it could reuse.
- [E] **Bearer and replayable.** Not single-use, not bound to the connection. A copied ticket is
  admitted again; `game_token(sid, pid)` is deterministic, so the second holder *becomes* the same
  seat (ADR 0006 accepts this; AVR-52 open). [I] Because `hubnet.js` fetches a fresh ticket before
  **every** connect, including reconnects (lines 425–456), single-use tickets are nearly free: the
  game keeps a spent set keyed by ticket hash until `exp`, and nothing on the client changes.
  [R] Do it before field test; it removes the one impersonation path a guest has without the
  Wi-Fi password being the attacker's own.
- [E] **Any same-origin page can mint a ticket for whatever game is on.** The ticket route accepts
  an optional `game` and answers 409 for a different game, but a page that omits `game` or names
  the current one gets a ticket (`sessions.py` lines 77–92). [I] Audience binding protects the
  *game* from a ticket meant for another game; it does not protect the *party* from a page that is
  not the game. This is the browser-trust gap in §1.6 showing up inside the protocol. [R] When
  game pages get their own origin, make the ticket route derive `game` from the request's Origin
  (one origin ↔ one game, or the shell's origin for the party's own frames) and refuse mismatches.
- [E] Tickets carry no device, member or name. [I] Correct for privacy and for the trust boundary;
  it also means a game cannot build cross-session stats on its own, which is right: stats belong
  to the party, which is the only side that knows who a participant is. v0 `ended` carries no
  result, so today *nobody* can build stats. See §1.5.

### 1.3 Authority: the split is right; symmetric keys are less of a problem than they look

- [E] Party: mint tickets, launch, end, decide who is host, decide roster. Game: admit, run the
  room, report `ended`. Host actions are server-resolved from the device cookie and gated by
  `if_version` optimistic concurrency; succession is timer-driven, never by request; `transfer_host`
  only to a member who is here. There is no admin principal at runtime at all (SSH only). [I]
  This is correct and deliberately small. "Host ≠ admin" is already true structurally.
- [E] Keys are symmetric per game, readable by the party and that game. The documented consequence
  is "a game can mint tickets for its own sessions". [I] Audit the blast radius: the party only ever
  *accepts* one game-signed thing, `ended`, which the game is entitled to send anyway. Everything
  else the game can forge has `aud = game`, so the only victim of a game forging its own tickets
  is itself. **The asymmetric-key argument is weaker than the main review's §2.16 implies**: the
  protocol already never trusts the game with authority over the party. [R] Keep symmetric keys
  through the consumer product; spend asymmetric cryptography where it earns its cost, which is
  **signing `.avrgame` packages** (§2.4), not tickets.
- [E] The real authority boundary is the Unix user. All three services and all key files are
  `cody`'s, so the key *per game* isolates nothing; any process on the box as `cody` is "the party".
  [I] Loopback and the proxy-header refusal are defence in depth; the key is the credential; the
  uid is the actual trust boundary. [R] One user per service at the next unit change (AVR-134 is
  the natural moment). Nothing in the protocol changes.

### 1.4 Replay protection: correct for messages, deliberately absent for tickets, memory-only

- [E] `launch`/`end`/`ended` carry a 96-bit nonce; `ReplayGuard` remembers nonces until `exp`
  (30 s); `iat` more than 5 s in the future is refused. [I] The guard is in memory on both sides.
  A party restart inside 30 s forgets nonces, but it also forgets the session, and `ended` must
  match the current `sid`, so a replay is refused for a different reason. A game restart inside
  30 s forgets nonces, but a replayed `launch` re-seats the same roster into an empty room, and
  `on_end` requires `sid` to match. [I] Safe today **because the party is memory-only**. When the
  party is persisted (which the main review recommends), a restored session plus a forgotten
  nonce set reopens the window: persist the guard with the session, or persist a "last accepted
  `iat`" floor per game.
- [E] Clock: both ends share one wall clock with no RTC. A backward jump makes every outstanding
  token "from the future" (refused); a forward jump expires everything. [I] Modeled honestly (ADR
  0006), handled by tolerance, not by design. The missing piece is a *policy*: what the appliance
  does with the clock at boot when offline (AVR-79). [R] A persisted clock floor (fake-hwclock
  style) at boot, and a party-wide "clock stepped" event that invalidates tickets and asks phones
  to re-fetch, is cheaper than making tokens clock-independent.

### 1.5 Session ownership: right owner, one hidden limit, one unowned object

- [E] The party owns the session id and lifecycle; the game owns the room; `GameSide` holds one
  `sid`; `participant_for(device, game)` gives one participant per device per session. The
  end-then-launch switch, the 15 s/30 s/60 s bounds, and "never launch over a room that may still
  be running" are correct ownership rules.
- [I] **Hidden limit: one session per game per server, and one session per party.** Two tables of
  the same game, or a party playing two things at once, is impossible by construction, not by
  decision. For a party appliance that is probably right; write it down as a product rule so a
  future "side game while the main game runs" request is recognised as an architecture change.
- [E] **Results are unowned.** `ended` v0 carries outcome only ("completed|abandoned"); the game
  shows its own results screen; the party holds `location = results` until the host moves on.
  [I] Two surfaces display "who won" with no shared source, and nothing can accumulate across
  rounds. At 20 games this becomes the biggest protocol gap. [R] v1 of `ended` (or a separate
  `result` message) carries a small, game-declared result object; the party stores it against
  participants and is the only writer of stats. Decide the schema before the second native game.

### 1.6 Local trust and browser trust: local is modeled, browser is not

- [E] Local: Host allow-list on every request, Origin allow-list on every POST, 8 KiB bodies,
  loopback-and-unproxied on internal routes, signed messages on every server-to-server call,
  control port never proxied. [I] Modeled correctly for one box. It is *loopback-shaped* rather
  than *peer-shaped*: nothing identifies the caller except being local and holding the key. Unix
  sockets with `SO_PEERCRED` would make the peer explicit and survive network namespaces; cheap,
  and the protocol does not change.
- [E] Browser: one origin for the shell, Party Home and every game page; the device cookie is
  path-scoped (servers never see it) but *ambient* to any same-origin JavaScript; game pages read
  the shared `localStorage`; the strict CSP covers `/party/` only. [I] **There is no principal for
  "which code is acting in the browser."** The model knows devices, members and games on the
  server, but on the phone every page is the member. GAME-INSTALLATION.md names the fix
  (sandboxed pages, a platform frame, `postMessage`) and correctly calls this "the real risk".
  [R] The cheapest correct model is **origin = trust tier**: shell origin (device cookie, Party
  API), game origin (tickets only, no cookie, no Party API), later a sandbox origin per untrusted
  game. One SAN on the existing certificate and one `host-record` in dnsmasq buys the first split.
  The protocol already supports it: names reach the game through the launch roster, not through
  shared storage.

### 1.7 Future third-party games: the wire is ready, the box and the browser are not

What the protocol gets right for a game the owner did not write: typed, audience-bound tokens;
a vendorable single-file reference with cross-repo vectors; the party trusts the game with nothing
but `ended`; the game needs no knowledge of devices or members. [E]

What is missing, in order of cost to retrofit later:

1. **Process and user boundary** (above). Today a third-party game would run as `cody` with every
   key readable.
2. **Browser boundary** (above). Today a third-party page is the viewer.
3. **A permission vocabulary.** `contracts/games/*.json` declares what a game *needs*
   (runtime, input, presentation); nothing declares what it *may do* (network egress, storage
   size, Party API access, display surfaces). The trust tiers in GAME-INSTALLATION.md exist only in
   prose. [R] Make the manifest the permission grant and make the appliance enforce it.
4. **Capability negotiation.** `v` is a fixed string; there is no "I speak v0 and v1". Fine until
   the first incompatible change, which §1.5 says is coming. [R] Version the message types, not the
   envelope; let the game advertise supported result schemas in its manifest.
5. **Package authenticity.** Nothing signs a game; the key scheme is for *session* trust. This is
   where a publisher public key belongs (§2.4).

**Verdict.** Identity, authority, session ownership and local trust are modeled correctly for an
appliance and will survive productization. Tickets need single-use before field test. Browser
trust is the one thing modeled wrongly (not weakly: wrongly, because the model has no principal
for it), and its fix is cheapest now. Third-party readiness is a boundary problem, not a protocol
problem.

---

## 2. Product and platform scalability audit

Assumptions that hold at "BLUFF + Arcade" and break along five growth axes.

### 2.1 From 2 games to 20 first-party games

- [E] **One process hosts every browser game.** The Games fork runs ~30 modules, chat and avatars
  in one uvicorn process on one port; its party-capable games are a hard-coded tuple
  (`party_session.py` `GAMES = ("bluff",)`). [I] At 20 party games: one crash takes every game
  down, one key per process in practice, one deploy for any game, and the per-module invariants in
  §1.1 multiply. [R] The monolith is the right *donor*; it is the wrong *platform*. Each party game
  becomes a process (or a small group of processes sharing a runtime) speaking the protocol.
- [E] **Install needs an owner-approved config change.** Party Core reads its game endpoints from
  a static JSON at start; nginx has a hand-written `location` per upstream; keys are files
  provisioned by hand; `avrana-party.nginx` and `arcade/nginx-site` must stay byte-identical by
  policy. [I] Every new game is a Party Core restart, an nginx edit and a key ceremony. Twenty
  times is a process failure, and it is incompatible with downloadable games by definition.
  [R] One generic route (`/games/<slug>/` → a dispatcher, or nginx `map` to per-game unix sockets),
  a games directory Party Core re-reads on `SIGHUP` or a control call, and a `provision-game` tool
  that writes the key and the grant. These are the three enablers of everything below.
- [E] **Six files describe the game list**, and `party-core.json` hand-duplicates min/max players
  and pregame flags from the contracts. [I] Drift is certain at 20. [R] One manifest per game is
  the source; everything else is generated or read at runtime (the repo already forbids hand-edits
  to generated files, so the convention exists).
- [E] Lifecycle bounds are global constants (60 s launch, 15 s end) with a per-endpoint timeout
  override that only the arcade uses. [I] An emulator title that loads a disc image, or a game
  that spins a runtime, will not fit. [R] Per-game bounds declared in the manifest, clamped by the
  party.
- [I] Long poll on a thread-per-connection server: one thread per phone, 20 s waits, one lock. Fine
  to roughly a hundred phones; the AP caps a party far below that. **Not** a 20-game problem.

### 2.2 From first-party to downloadable `.avrgame`

Everything in §2.1 plus:

- [I] **Authenticity and rollback.** A package needs a publisher signature (Ed25519 over a
  manifest hash is enough), a version, and an atomic install into a versioned directory with the
  previous version kept, exactly as GAME-INSTALLATION.md sketches. Run-from-checkout cannot do
  this; the update story (§2.5) and the install story are the same problem.
- [I] **Resource declaration.** Disk, memory, CPU class, display surface, whether it needs the
  emulator slot, whether it needs network egress (should be "never" until an upstream exists).
  The appliance grant file is the right place to say what the box offers; the manifest must say
  what the game asks; the party must refuse what the grant does not cover. The capability engine
  already does the *browser* half of this match; the *box* half does not exist.
- [I] **Package format is a postponable decision** (§3). What is not postponable is that the
  manifest schema becomes a public contract the moment one package leaves the owner's hands.

### 2.3 From curated to community content

- [I] Trust tiers (first-party / trusted / community) exist in prose only. A community game is by
  definition a game the owner did not read. Everything in §1.7 becomes mandatory, in this order:
  per-game user and `PrivateNetwork`, per-game origin, manifest-as-permission, result schema. The
  emulator path also needs the same sandbox: a crafted ROM exploiting a core bug is a community
  content problem too.
- [I] **Moderation surface.** Names are server-cleaned; avatars are re-encoded; chat is designed
  as four layers. Community *games* add arbitrary text and images reaching every phone. The
  sandbox origin is the control; nothing else scales.
- [I] **Support surface.** When a community game breaks a party night, the owner needs to know
  which process did it. Per-game units with journald give this for free; the monolith cannot.

### 2.4 From the Pi 4 to several hardware generations

- [E] One appliance grant file (`avrana-pi4.json`) describes what this box offers; the shape is
  right. [E] The streaming provider is one file that hard-codes `v4l2h264enc`, Xvfb, PulseAudio
  and a 2-player uinput layout; the Pi 5 has no hardware H.264 encoder (main review, unverified
  on hardware). [I] The provider *abstraction* exists on paper (`presentation.shared_stream`);
  the *implementation* is Pi-4-specific and would be rewritten, not ported.
- [E] No RTC on any Pi; the internal AP tops out near 8 stations; USB Wi-Fi caused under-voltage.
  [I] Party size, not game count, is the hardware limit, and it is a Wi-Fi radio problem. A
  consumer unit needs either a board with a better radio or an external AP in the box. This
  constrains the enclosure and power budget before it constrains software.
- [R] Keep the grant file as the hardware abstraction; make the stream provider select an encoder
  from the grant; add `rtc: true|false` and `ap.max_stations` to it so software can adapt and the
  owner app can warn.

### 2.5 Owner app integration

- [E] There is no owner principal at runtime. Administration is SSH. The device cookie is a guest
  identity. [I] An owner app needs three things that do not exist: an authenticated owner
  session (PARTY-PLATFORM §13 designs a PIN-gated web admin on its own port, which is the right
  shape and the app can use the same API); a **control API** (Wi-Fi settings, install/remove,
  update, party status, logs) that AGENTS.md currently reserves to owner-executed SSH steps; and a
  **pairing** story that proves the phone belongs to the owner (first boot, physical button, QR on
  the box).
- [I] The biggest decision hiding here is **local-only vs cloud**. A local owner app over the party
  Wi-Fi fits the offline product boundary and needs no account, no relay and no upstream. A
  remote owner app implies an account, a relay, telemetry, a privacy policy and a security
  surface that the whole architecture was designed to not have. [R] Local-only first; treat any
  cloud feature as a separate product decision with its own ADR.
- [I] **Updates are the owner app's first real feature**, and run-from-checkout is the wrong
  substrate for it. Versioned release directories with a symlink switch and a kept previous
  version is the minimum; A/B root partitions are the consumer answer.

**The three enablers.** Nearly every break above is unblocked by the same three changes: a
generic game route, a runtime-readable games directory with a provisioning tool, and one process
and user per game. They are also what makes the governance rule "no production edits without
owner approval" compatible with a product where the owner installs games from a phone.

---

## 3. Technology obsolescence and replacement audit

Designing Avrana today, no sunk cost, same product: a portable, offline, no-app, no-TV party
appliance that one day ships to strangers.

### 3.1 Would still choose

- **A Linux single-board appliance with systemd units and nginx in front.** Nothing lighter gives
  TLS, static files, path routing and a captive-portal default server in one process.
- **Python for Party Core, and the pure-core + thin-service split.** The state machine is the
  product's logic; it is small, testable and clock-injected. This is the best-engineered part of
  the system.
- **Server-minted `HttpOnly` device cookie** as the guest identity, with `profile` layered on top
  later. The alternative (tokens in `localStorage`) is what LAN Games did and is being removed.
- **Typed HMAC capabilities with audience, session and expiry, never in URLs**, and symmetric
  per-game keys (§1.3). The envelope would look the same.
- **Long poll (or SSE) for party state, WebSocket only inside games.** Phones sleep; HTTP recovers
  for free; the party does not need push.
- **Browser-first PWA shell with a network-first service worker and kill switches.** "No app" is
  the product; the service worker is correctly treated as an enhancement.
- **Contracts as plain JSON (appliance grant, game manifest, provider protocol).** Right idea,
  currently over-split (main review §3.8).
- **RetroArch under Xvfb with uinput pads, WebRTC for the shared stream.** There is no other
  no-install path to a phone screen.
- **Game Contract + Party as the only identity holder.** The product boundary is right.

### 3.2 Would replace, and why the replacement is better rather than prettier

| Today | Greenfield choice | Why |
|---|---|---|
| Party layer available on HTTPS only; `Secure` cookie | Party works on the HTTP origin; HTTPS adds Wake Lock, service worker and a second cookie | The public-cert-on-private-DNS trick is the only way to a secure context on phones without installing a CA, so keep it, but it must be an *enhancement*. Today it is a single point of failure with a date on it (2026-12-25, renewal disabled). |
| One origin for shell and games | Two hostnames from day one (`party.` and `games.`), one certificate | §1.6. Free now, expensive after profiles, stats and chat bind to one origin. |
| Three services, one Unix user | One user per service, keys owned by their game | §1.3. Costs nothing at greenfield; is the real trust boundary. |
| LAN Games monolith as the game platform | First-party games as separate processes speaking the protocol over unix sockets; the monolith as a donor of game logic and UI | §2.1. The accidental platform is the single most expensive thing to unwind later. |
| Three Python web stacks (stdlib threads, FastAPI/uvicorn, aiohttp) | One ASGI framework for party and game servers; keep the pure core framework-free | Fewer failure modes to learn, one way to do WebSockets, one way to do health. Not urgent, but a greenfield design would not choose three. |
| Memory-only party | SQLite WAL for party, session, device store and replay floor | Power-loss history on this hardware; also what makes the replay guard safe once persisted (§1.4). |
| Six catalogue files per game | One manifest per game, everything else derived | §2.1. |
| Run-from-checkout as `cody` | Versioned release directories with a symlink switch and a kept previous version | Enables rollback, package install and the owner app's update feature with one mechanism. |
| Fixed TCP ports per service | Unix sockets under one directory, nginx `map` by slug | Removes port allocation, makes the peer explicit, survives `PrivateNetwork`. |
| Hand-provisioned keys, `write_key` refusing overwrite | A `provision-game` tool that writes key, grant and route in one step | §2.1; rotation becomes a command, not a ceremony. |

### 3.3 Would deliberately postpone

- **The `.avrgame` package format and the sandbox mechanism** (CSP `sandbox` vs separate origin vs
  container). Decide the *boundaries* now (§1.7); choose the mechanism when the first non-owner
  game exists.
- **Asymmetric cryptography anywhere**, until packages leave the owner's hands; then only for
  package signing.
- **An owner app, and anything cloud.** First a PIN-gated local admin API, which the app would use
  anyway.
- **Personal viewports, split-screen metadata, the four-layer chat, the dual-language capability
  evaluator, Graphify as a workflow.** All sound, all ahead of the product that would use them.
- **Pi 5 or any board change**, until the stream provider selects its encoder from the grant and
  the AP limit is measured at a real party.
- **Sunshine/Moonlight, WebTransport, native companion apps.** Each is a bet on a software gap or a
  browser API that is not stable on the phones in the room today.
- **Replacing the stdlib Party service.** It is the simplest of the three stacks and the one with
  the fewest dependencies; it should be the *last* to change, after the game processes have moved
  to the shared framework.

### 3.4 What this says about the current design

The greenfield design is the current design with four changes made earlier: Party on HTTP with
HTTPS as an upgrade, two origins, one user per service, and games as processes instead of
modules. None of the four is a rewrite; all four get more expensive every month because profiles,
stats, chat and the owner app will bind to whichever boundary exists when they ship. The rest of
the stack (nginx, Python, the state machine, the token design, the PWA, RetroArch and WebRTC) is
what a team starting today would still pick.

---

## 4. Decisions this adds to the main review's lists

Freeze now (in addition to the main review §3.4):

- Membership is network reachability; every weaker mode adds a join secret.
- The party is the only writer of anything about a person; games receive participants and names
  through the launch roster only.
- Symmetric per-game session keys stay; asymmetric keys are for package signing only.
- Results, when they exist, cross the boundary in a game-declared schema that the party stores.

Decide before the second native game (ordering matters):

1. Origin strategy for game pages (two hostnames recommended).
2. Process-and-user-per-game, with the generic route and provisioning tool.
3. The `ended`/result schema.
4. Single-use tickets.
5. Standalone play: a product mode with its own admission path, or removed.

Decide before any owner app work: local-only vs cloud; the update substrate.
