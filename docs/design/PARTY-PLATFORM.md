# Avrana Party platform: what it is and how it fits together

Status: **design direction (accepted 2026-09-24; locked decisions updated the same night).
Nothing here is built unless marked EXISTS.** This is the hub document; details live in the
focused documents listed below. Decisions: `docs/adr/0002-party-platform.md` (the platform),
`docs/adr/0003-ids-and-keys.md` (identifiers). Sequencing: `docs/ROADMAP.md`, item **N5**.

Read this before designing anything a player touches: a game, a lobby, a login, a chat, a stat.
It is written for someone arriving months from now with no other context.

| Document | Covers |
|---|---|
| **this file** | thesis, principles, locked decisions, concepts, roles, social layer, security summary, open questions |
| `PARTY-LIFECYCLE.md` | state machines (party, presence, host, seat), awkward-state rules, timers |
| `GAME-INTEGRATION.md` | capability manifest v0, runtime vs grant, the party contract, what today's code duplicates |
| `NATIVE-GAMES.md` | "the phone is not just a controller", hook strategy, reusable primitives, fairness, accessibility |
| `PERSONAL-VIEWPORTS.md` | per-phone crops of one shared split-screen stream |
| `ONBOARDING.md` | tap/scan to join, party address, no-app baseline, party LAN vs upstream internet |
| `GAME-INSTALLATION.md` | open installation without a store, trust tiers, emulator profiles |
| `docs/findings/2026-09-24-product-differentiation.md` | why anyone would choose this; where it loses; what to prove first |

---

## 1. The thesis

Avrana Party is **a portable local multiplayer platform whose games plug into a shared Avrana
Party system**. It is not a ROM box, not a LAN Games front end, not a Raspberry Pi project and not
a phone game launcher.

> **The game may change. The party does not.**

Technically, that sentence means: **the Party is a long-lived object that outlives every game
session.** People join the *party* once. Its members, their names and personas, the host, the
seating, teams, chat, queue and running history live in the party layer. A game is a session the
party starts and ends; when it ends, everyone returns to the party, and the next game starts with
the same people already seated — no one re-joins, re-names or re-navigates. (Whether the party
also survives an appliance *reboot* is still open: §16.)

Avrana owns the **party lifecycle, profiles, guests, device recognition, presence, seats, roles,
personas, host and admin authority, synchronized navigation, reconnect, spectators, teams, chat,
voting, stats provenance, achievements and game capability metadata.** Games plug into those
where appropriate.

### What this is not

- **Not a universal gameplay framework.** Rules, state, rendering, netcode and turn logic stay with
  each game. The platform provides *services around* games through a small contract
  (`GAME-INTEGRATION.md`). That is why the roadmap still says "no universal gameplay framework".
- **Not a social network and not cloud accounts.** Local to the appliance, offline, no sign-up.
- **Not a store.** Open installation, no marketplace (`GAME-INSTALLATION.md`).
- **Not captive-portal-dependent and not app-dependent.** Wi-Fi plus a normal browser is the
  baseline (`ONBOARDING.md`).

### Who V1.0 is for

The first real V1.0 is for the owner. Its job is to prove **"can this whole product experience
actually work and be fun?"** A possible later path — working prototype → polished demonstrator →
crowdfunding → appliance for backers — must not distort the immediate roadmap, but the
architecture should avoid obvious dead ends for it (open formats, stable ids, no hard-coded
single-user assumptions, a clean admin/host split).

---

## 2. Product principles

Durable. A design that breaks one needs an explicit, recorded reason.

1. **The game may change. The party does not.**
2. **Browser-first.** The browser is the whole product surface; the captive portal is optional
   convenience, never an architectural dependency.
3. **Guest-first.** Profiles enhance play but are never required. Anonymous guests always work.
4. **Avrana owns player identity; games consume it.**
5. **Device identity is not human identity.** "I recognize this browser" never means "this is Cody".
6. **Seats bind sessions, profiles and controllers temporarily.**
7. **Admin authority is separate from Party Host authority.**
8. **Navigation is synchronized across the party.**
9. **Games plug into shared social, session and progression systems.**
10. **Offline-first.**
11. **Never claim what a game or the platform cannot actually observe.**
12. **No game should reinvent profiles, chat, reconnect, teams, spectators or session lifecycle.**
13. **Reduce social friction; never add account or setup friction.**
14. **The phone is not just a controller.** It is each player's private, dynamic surface; native
    games should use it (`NATIVE-GAMES.md`).
15. **One appliance, one party.** Not a multi-tenant game server.
16. **TV optional.** The core experience works on phones alone; a game may require a TV.
17. **No app required.** Wi-Fi + a normal browser; an app may only add convenience.
18. **Open, not a store.** Anyone may install Avrana-compatible games; trust is the appliance
    owner's decision.

---

## 3. Locked product decisions (2026-09-24)

| Question | Decision |
|---|---|
| Multiple simultaneous parties? | **No.** One appliance hosts one active party. |
| Is a TV mandatory? | **No.** Games may still declare `tv_required`, `tv_optional` or `no_tv_needed`. Target settings include bars, airplanes, cruise ships, hotels, airports, travel, noisy places and players who are apart but nearby. |
| What if the host disappears? | **Host migration.** Reconnect grace, then another eligible player; voluntary transfer anytime; a returning old host doesn't take it back. Keep the selection rule simple. |
| Late joiners? | **Spectator by default.** A game may opt into next-round admission, join-in-progress, deal-in or open-seat filling (manifest `late_join`). |
| Physical seating (rows, table position, left neighbour)? | **Not a platform concept.** A game may define its own spatial idea if it truly helps. |
| A proprietary game store? | **No.** Open installation; no marketplace, payments, reviews or DRM. |
| A native app? | **Not required.** Optional later for onboarding or hardware. |
| Captive portal? | **Not required.** Optional glue only. |
| Phones forming one big distributed display? | **Experimental only** (§14). |

---

## 4. The product surface: browser-first, offline-first

```
Join the Avrana Wi-Fi  →  open the party address  →  the browser is the player's complete interface
```

Over time the browser handles identity/profile selection, the party lobby, navigation, controller
UI, WebRTC video, WebSocket input, chat, private information, voting, achievements and stats,
profile settings and reconnection. Onboarding details, the party address and the party-LAN vs
optional-upstream model are in `ONBOARDING.md`.

- **One canonical origin.** Everything a player uses is served from one host through nginx. A
  different host name (`10.42.0.1` vs `party.local`) gets a separate cookie jar; a different port
  (`:8198`) shares cookies but has separate localStorage and a different Origin. Either way a player
  can look like two devices — two presences, two seats, two votes. Cookies ignore ports, so a dev
  instance on another port of the same host receives production cookies.
- **Which origin is still open**, but the leading option is **`http://10.42.0.1` as the canonical
  origin**, because it always resolves (QR codes carry it) — with `party.local` (mDNS; uneven on
  Android) redirecting to it for people who type the name (`ONBOARDING.md`). Mixing the two without
  a redirect is the thing to avoid.
- **Plain HTTP on a LAN** is a non-secure context: no `Secure` cookies, no secure-context-only APIs,
  no TLS on guests' phones.
- **Captive portal = convenience.** Never select a profile, trust a device or run a game inside the
  captive-portal mini-browser.
- **Per-player accessibility is free here:** every player has a private UI, so larger text,
  handedness, contrast, motion and haptics can change for one person only (`NATIVE-GAMES.md` §7).

---

## 5. Core concepts

Do not collapse "player" into one object. Identifier rules are in ADR 0003.

| Concept | What it is | Lifetime | Key |
|---|---|---|---|
| **Party** | The persistent unit people join: members, host, *seating* (who holds which game slot, carried from one game to the next — never physical position), current game, queue, teams, chat. Exactly one active per appliance. | From first join until ended (reboot survival OPEN) | `party_id` |
| **Device** | A recognized browser installation. | Months; revocable | server-issued random token in a cookie (hash stored) |
| **Profile** | A persistent human identity: name, avatar, preferences, history, stats, achievements. Optional. | Until deleted/merged | `profile_id` |
| **Guest** | A participant with no saved profile ("Player 3", renamed "Megan"). | The party | `presence_id` |
| **Presence** | A profile or guest participating in the party, from one device at a time (possibly several tabs; a profile moving to a new phone closes the old phone's connections). Proposed: a TV joins as a *screen* presence (sees the public view; never host, seat or voter). | The party | `presence_id` |
| **Seat** | A temporary binding: presence → a player/controller slot in the current game session. | One game session; the party's *seating* (who holds which slot) carries forward | `seat_id` |
| **Game session** | One launch of one game by the party. | Until the game ends | `game_session_id` |
| **Role** | Host, Player, Spectator (party roles); Admin (appliance role); game-specific roles. | Varies | — |
| **Persona** | A temporary display identity: profile *Cody*, tonight *Admiral Worm*, in BLUFF *Definitely Not The Duke*. | Party or game | on the presence |
| **Device trust** | Whether a device may pick a saved profile without its PIN. | Until revoked | device↔profile link |
| **Team** | A named group of presences above any single game. | The party | `team_id` |

```
 Device (browser, cookie) ──recognizes──▶ Profile(s) it may offer ("Welcome back")
      │
      └─opens─▶ Presence in THE Party  (profile or guest, with a persona)
                    │
                    ├─ Role in the party: Host? Player? Spectator?
                    ├─ Team membership (optional)
                    └─ Seat in the current game session ──▶ the game's controller/player slot
```

**Invariants (ADR 0003):** device token ≠ device id ≠ profile id ≠ presence id ≠ seat id ≠
controller number. They map to each other; they are never the same value. Ids are opaque and
authorize nothing; only credentials resolved on the server do; names never do.

**What a game sees:** a secret **game key** scoped to (game session, participant) plus the persona
to display — never a device token or profile secret. Where the seat is bound depends on the game
(LAN Games at its countdown; PS1 and the arcade at connect) — see `GAME-INTEGRATION.md`.

---

## 6. Guest-first and saved profiles

- Joining never requires a profile. Default names are **Player 1, Player 2, Player 3**; a guest can
  rename immediately (*Player 3 → Megan*).
- Later: **"Save Megan as a profile?"** If saved, the history Megan gathered as a guest links to the
  new profile with its provenance. Wording: **Save Player**, **Save Profile**, **Keep this player** —
  never "Create Account".
- **Player profile PIN: optional. System Admin PIN: required.**
- A remembered device means *"I recognize this browser"*. A recognized phone shows
  `Welcome back [Cody] [Audrey] [Someone else] [Guest]`. The device token is random and
  server-issued; **never** MAC addresses or fingerprinting.
- A PIN-less profile runs on the honour system (the UI says so); if its owner is already present, a
  second device needs a trusted device (or the PIN, if set) to take it.
- **Lifecycle:** guest→profile promotion · many devices per profile and many profiles per device ·
  aliases/personas · recent players · trusted-device revocation · deletion ("Deleted player" keeps
  others' records true) · admin-only merge (moves history, never access) · export/import without
  secrets · QR pairing with a short-lived single-use code. Stable opaque ids; no cloud identity.
- **Settings categories** (not a UI spec): identity (name, avatar, aliases); access (optional PIN,
  trusted devices); controls (handedness, layout, button size, haptics); accessibility (text size,
  contrast, reduced motion, colour-safe palettes); privacy (stats visibility, playtime, rivalry
  history, recent games); social (chat/whisper preferences, later mute/block); gameplay (per-game
  preferences, favourite games); cosmetics (frames, badges, showcase — later). LAN Games' per-device
  sound/haptics/motion/contrast preferences are the seed.

---

## 7. Admin vs Party Host

Entirely separate. A host can never escalate to admin.

| | **System Admin** | **Party Host** |
|---|---|---|
| What | Persistent privileged appliance identity | Temporary, disposable role inside the party |
| Credential | **PIN required** (no default); v0 is an SSH command-line tool, a PIN-protected web admin comes later (§13) | None |
| Powers | Network, updates, storage, game installation and trust, profile management (merge, delete, reset PINs), **moderation defaults**, kick and revoke/clear guest identities | Select/start games; game rules; pause/restart/end; manage spectators; remove/reassign seats; moderate party chat; rematch/next game; run votes; kick from the current party |
| Cannot | — | Touch profiles, devices, PINs, installation or admin settings; see other players' hidden game state |

- **Host is disposable** (`PARTY-LIFECYCLE.md`): reconnect grace, then succession to another
  eligible connected player (proposed: the earliest-joined; random is acceptable); voluntary
  transfer; a returning old host is an ordinary player; no "claim host" action.
- Normal players always keep authority over their own profile, controls, avatar/persona and
  accessibility preferences.
- **Moderation is configurable, not hard-coded.** The admin eventually sets defaults such as:
  profanity filtering, profile visibility, custom avatar uploads, guest naming rules, whispers, chat
  availability, kicking for the current party, whether persistent profiles can be created, and
  whether saved profiles are shown to guests. A simple preset pair may bundle them — without any
  enterprise role system:
  - **Friends / Private party** (default): the Wi-Fi password is the only gate; no join code in v0.
  - **Public / Demo party:** new presences wait for **host admission** (covers strangers, kick
    evasion and duplicate presences); an optional short party code in the QR's URL fragment with a
    typed fallback; the admin (over SSH in v0) picks the first host, also after idle or reboot; no
    web admin on the guest Wi-Fi.
- **Kick ≠ ban.** A kick removes a presence from the current party and says so publicly. Because a
  private tab is a new device, it is not a ban; only the Wi-Fi password or Public-mode admission
  keeps someone out.

---

## 8. The Party, Party Home and synchronized navigation

The party (illustrative, not a schema): `id · state (lobby | launching | in_game | intermission |
ended) · host · presences · seating · current game session and seats · spectators · teams · queue ·
votes · chat · nav {seq, target} · started_at`. Its state machine and every awkward case are in
`PARTY-LIFECYCLE.md`.

**Party Home** is not just a launcher: who is present, host, ready, spectating; the current game;
recent games; the queue and vote status; party stats; reconnect state.

```
AVRANA PARTY
Cody      Host       Ready
Audrey               Ready
Nick                 Ready
Sam       Spectator

NOW PLAYING   Worms Armageddon
UP NEXT       Bomberman   4 votes
              BLUFF       2 votes
```

**Synchronized navigation.** Today each person clicks into each LAN game separately; that is wrong
for this product.

```
Host selects Bomberman → (streamed games: the service starts; "Starting…") → ready
  → nav.seq += 1, nav.target = bomberman → broadcast → EVERY party browser follows
  → personas, seating and roles persist
```

- Mechanism (proposed): top-level navigation driven by a tiny shared `party.js` holding one party
  socket; not an iframe shell and not a single-page rewrite of every game.
- **"What is my party doing?"** — a phone that slept or reloaded asks on wake and is taken to the
  current state; `nav_seq` makes it idempotent.
- Navigation moves only when a transition has actually happened (a failed launch never moves it).
- Only one emulated game runs at a time on a Pi 4 (CPU, one hardware encoder budget, power).
- **Detours:** someone deliberately in their profile/settings gets a prompt ("The party moved to
  Bomberman — Go"), not a yank. Exact policy OPEN.

---

## 9. Seats, spectators and teams

- **Seats** support disconnect grace, **neutral input while disconnected**, reclaim on reconnect,
  game-specific slot assignment, and team membership. A disconnected or away seat is never "free";
  only a released seat can be refilled (new seat id, new key). Every connection resolves to one
  presence; a controller slot takes input from one connection (the newest tab).
- **Late joiners spectate by default**; games opt into more via `late_join`.
- **Spectators** are a first-class role, not a failed player slot: they see the shared stream or
  public state, chat, optionally vote (party setting, off by default proposed), and can be promoted
  within the game's policy. The server rejects their input.
- **Teams** live above the individual game (Team Purple: Cody, Audrey · Team Orange: Nick, Megan).
  Compatible games reuse them and report team results; others don't participate. **Never fake a
  team result.** Party score example: Bomberman → Purple, BLUFF → Orange, Worms → Purple = 2–1.
- Physical seating is not modelled (§3).

---

## 10. Social layer

- **Chat channels:** public party chat, team chat, private whispers, game-defined channels, and
  **system events** (`SYSTEM: Audrey is now Host.`) — a separate server-only message type rendered
  in its own element, backed by the name rule in §13 (normalization, no look-alike alphabets, no
  reserved words, duplicates numbered) so no player name can pass for it. The host moderates party
  chat within the admin's defaults.
- **Private player panel:** hidden roles, cards, inventory, secret objectives, private prompts, votes
  and decisions on each phone, alongside the shared public view (phones or an optional TV). Private
  data is filtered on the server, never hidden with CSS (`NATIVE-GAMES.md`).
- **Queue and voting:** coordinate what to play next — valuable when players are apart and can't
  talk. Anyone nominates; the party votes; **the host decides** (votes are advisory — see §13 on
  why ballot stuffing is possible and accepted for Friends parties). Public or hidden votes; spectator
  voting per party setting. The list filters itself by player count, TV requirement, control model,
  session length and capability (manifests). Modes: **casual queue**, **vote round** (timed),
  **playlist**. Early completion when every eligible voter present has voted. **Votes belong to
  party presence**, never browser connections: refresh, reconnect or a second tab never adds one.

---

## 11. Progression: stats, achievements, history

| Provenance | Meaning | Example |
|---|---|---|
| `authoritative_game_event` | The game reported it | BLUFF winner, eliminations |
| `platform_observed` | The platform saw it | Cody held Bomberman slot 2 for 14 minutes |
| `manually_recorded` | A person entered it (only if ever supported) | "Purple won Worms", typed by the host |

- Native games can report authoritative events; **emulated games produce no results** unless a
  per-game adapter exists; hot-seat games can't even attribute turns. **Participation is never a
  win.** Flags that change meaning travel with results: bot seats, autopilot, forfeits, abandoned
  games. Community games carry a `community` provenance label.
- **Achievements:** platform (N games, N titles, N people, tournaments), game-defined, and
  social/party (wins across games in one party, team feats, rivalry milestones); may unlock local
  cosmetics; no monetization; only from stats whose provenance supports them.
- **History and rivalries:** games played together, recent players, frequent teammates, trustworthy
  head-to-heads, party-night recaps, favourites. Local history from shared play — not a social
  network.

---

## 12. Games and the platform (summary)

A game touches the platform through three separate things — **capabilities** (the manifest: what
the game is), a **runtime request** (how its code runs) and a **grant** (what the appliance allows)
— and joins the party through four optional pieces: a seat-ticket handshake (first WebSocket
message, bound to one game), an event sink with provenance, the `party.js` follow client, and host
checks. Without them a game keeps working as today. Everything is in `GAME-INTEGRATION.md`; native
game design is in `NATIVE-GAMES.md`; installation is in `GAME-INSTALLATION.md`.

**Hook strategy:** the platform should eventually demonstrate three kinds of hook, not one title:
native Jackbox-like games with no TV; native action/arcade games designed around Avrana; and
emulated multiplayer (including **Personal Viewports**, `PERSONAL-VIEWPORTS.md`). BLUFF is an early
native testbed, not the product.

---

## 13. Security model (proportionate)

Threats: mischievous guests on the same Wi-Fi (impersonation, stat spoiling, double voting, host
grabbing); cookie sniffing on an open or shared-password network; web pages on a phone that also
has mobile data; and — once open installation exists — **a malicious or buggy game**. Anyone with
SD-card or SSH access is an admin by design. Parameters are suggestions to confirm when built.

**Accepted risk (Friends parties):** the party network runs plain HTTP. The party Wi-Fi should
never be open (WPA2 at least — recommended, not yet decided), but **anyone who has the Wi-Fi
password can read and alter other guests' traffic**: hidden roles, device cookies (i.e. that
phone's presence, host included) and any PIN typed over Wi-Fi. That is accepted for a friends
party; client isolation on the AP (`wifi.ap-isolation`, a live change needing approval) is a cheap
extra that blocks guest-to-guest spoofing.

**MUST before profiles ship**
- Server-issued device token (`secrets.token_urlsafe(32)`) in an `HttpOnly; SameSite=Lax` cookie
  scoped to the party path (e.g. `Path=/party/`), and nginx strips the `Cookie` header on every game
  location, so **game servers never receive device tokens** (path scoping keeps cookies from
  servers, not from same-origin JavaScript). Store only its SHA-256; revoke = delete. It unlocks the
  "Welcome back" picker; it never grants admin or skips the admin PIN; on a device the owner chose
  to trust, it skips that profile's PIN.
- One canonical origin (see §4; leading option: `http://10.42.0.1`); nginx allowlists the app's
  host names (also defeats DNS rebinding), while the default server keeps answering the
  captive-portal probe paths exactly as today (returning 444 only for everything else).
- Origin checks on every WebSocket upgrade and POST to party and admin endpoints once identity
  rides on a cookie; GET never mutates. A presence is created only by an explicit **Join** (a POST),
  never on page load or socket open — so captive-portal WebViews don't create ghost presences.
- Authorization only from server-resolved ids; never from names or client-sent ids.
- **Admin:** v0 has **no web admin** — administration is an SSH command-line tool (V1.0 is for the
  owner), so there is nothing for a guest to brute-force or cross-site-request. A later web admin:
  PIN required (no default, ≥ 6 digits, set over SSH); runs on its **own port** (a separate origin,
  so party-page JavaScript can't read its anti-CSRF token and exact Origin checks reject it);
  `frame-ancestors 'none'`; a short backoff capped at ~60 s so a guest can't lock the owner out all
  night; off on the guest Wi-Fi in Public/Demo mode; recovery = delete the PIN file over SSH/SD;
  an SSH `login` command can always issue a one-time link. PIN hash with `hashlib.scrypt` in its own
  0600 file owned by the party service's **own system user** (a unit change needing approval).
- Host ≠ Admin; system messages are a separate server-only type rendered in their own element.
- **Names** (display values only): NFKC-normalize; strip control/format characters (zero-width,
  bidi overrides); collapse spaces; 1–16 characters; no mixing of look-alike alphabets (Latin,
  Cyrillic, Greek); reject anything that is or starts with a reserved word (SYSTEM, Admin, Host,
  Avrana, Moderator), compared on a casefolded letters-and-digits key; duplicates get " 2"; render
  names as text inside `<bdi>`. (Checked in `experiments/party-model`.)
- Votes per round per presence; one controlling connection per seat; spectator input rejected.
- Seat tickets bound to one game (audience). For **sandboxed** third-party games, verify them with
  per-game keys or sockets; built-in LAN Games modules share one process, so that process is their
  real boundary (below).
- Dev instances use a **different cookie name** and never the production host (cookies are keyed by
  name, host and path — not port — so a same-named dev cookie would overwrite production's).

**SHOULD** — optional profile PIN (4–6 digits; scrypt is kept but a short PIN can be cracked
offline in seconds, so file ownership is the real control; the UI says "don't reuse your bank or
phone PIN"); backoff only on **untrusted** devices (trusted ones skip the PIN, so the owner is never
locked out; the owner sees failed attempts); a PIN or honour-system pick lasts this party only
unless "Trust this phone" is ticked; a profile moving to another phone notifies the old phone and
posts a system event. QR pairing with single-use 3-minute codes in the URL fragment, confirmed on
the issuing phone (a photographed QR is not enough), fragment cleared after use. Tokens never in a
URL path or query string or in logs. SQLite with WAL and regular backups (power-loss history).
Store only names, avatars (re-encoded to PNG/JPEG), preferences and stats.

**Honest limits.** Device tokens are free (a private tab is a new device), so: a **kick removes a
presence and says so publicly — it is not a ban**; one person can hold several presences, so a vote
can be stuffed — eligibility freezes when a round opens and **the host decides**, so votes stay
advisory; that is accepted for Friends parties. Only the Wi-Fi password — or host admission in
Public/Demo mode (§7) — keeps someone out. **Built-in games are not isolated from each other:** the
LAN Games fork is one process, so any module could read any game's keys; this is acceptable only
because built-in code is trusted.

**For untrusted games (later):** no untrusted in-process code; every response under an untrusted
game's path gets `Content-Security-Policy: sandbox allow-scripts` and `nosniff`, inside a platform
frame that exposes no host verbs over `postMessage`; game endpoints authenticate by ticket and
accept the sandbox's `null` Origin, while party and admin endpoints reject it; sandboxed games are
second-class (no localStorage, harder fullscreen and audio unlock). Server processes are isolated
with systemd sandboxing and no network (`GAME-INSTALLATION.md`).

**Known gaps today:** the arcade's `/stats` is reachable through nginx and shows peer IPs; PS1's
localhost-only `/stats` check will stop working once PS1 sits behind nginx; PS1 sends its token in
the URL (`?token=`), which nginx would log.

**Deliberately not doing** — TLS on guests' phones, JWTs, token rotation schedules, encrypted
databases, Argon2 dependencies, device fingerprinting, email recovery, CAPTCHAs.

---

## 14. Experimental and future concepts (not MVP)

- **Distributed phone display:** several phones together showing parts of one larger picture.
  Interesting; not built, not planned.
- **Native companion app:** only for onboarding/hardware conveniences (programmatic Wi-Fi join, NFC
  Wi-Fi on iPhone, background reconnect). Never required.
- **BLE discovery/proximity:** only if genuinely useful later (needs an app on iOS).
- **Optional upstream internet** (Ethernet, Wi-Fi client uplink, tether): makes onboarding easier;
  the party must never depend on it (`ONBOARDING.md`).
- **Personal Viewport auto-detection** (menus, player count, layout via title adapters, emulator or
  memory inspection, video analysis): after a manual PoC proves the idea.
- **Emulated-game result adapters:** per-title, only where results can be observed honestly.

---

## 15. What exists today (2026-09-24)

Full audit with file references: `GAME-INTEGRATION.md` §4. In short: identity, reconnect, presence,
seats, spectators, late join, navigation and launch each exist **separately** in two or more places
(LAN Games core, BLUFF, WORDCLASH, the arcade, PS1) with different semantics — at least five grace
behaviours, four token validators, five late-join policies — and **no host authority, no party, no
admin, no cross-game stats**. The LAN Games registry is a proto-manifest; PS1's slot table is the
closest thing to a platform Seat; BLUFF's presence model is the closest thing to platform Presence.

---

## 16. Open questions

**Closed on 2026-09-24:** multiple parties (no) · TV mandatory (no; games may require one) · late
join (spectator by default; games may override) · host loss (migration) · physical seating (not
core) · proprietary store (no) · native app required (no) · captive portal required (no).

**Still open:**
1. Exact party URL/origin layout (`/` = Party Home? LAN Games under a prefix?) — a live nginx change.
   Leading option: `http://10.42.0.1` as the canonical origin with `party.local` redirecting to it (§4).
2. Device-token migration from LAN Games' client-minted `wc-token` without breaking the live service.
3. Whether a party survives an appliance reboot (options in `PARTY-LIFECYCLE.md`).
4. Exact host succession policy (proposal: earliest-joined connected player).
5. Third-party game sandbox/trust model (`GAME-INSTALLATION.md`).
6. Upstream-internet architecture (`ONBOARDING.md`).
7. Packaging format for third-party games.
8. Exact onboarding path across iOS and Android (needs the real-phone tests in `ONBOARDING.md`).
9. Exact Personal Viewport metadata format.
10. How hot-seat emulation attributes results (probably: it doesn't).
11. Final V1 hardware (power, battery, enclosure, display for QR codes).
12. Forced-navigation policy during detours; confirming the proposed TV "screen" presence; how far a
    kick reaches beyond the current party; spectator nominating;
    party teams vs in-game teams; name length/Unicode (LAN Games caps names at 14 ASCII characters);
    profile database location and backups; admin surface on the guest Wi-Fi vs home LAN only;
    host-less kiosk parties.

---

## Glossary

| Term | Meaning |
|---|---|
| **BLUFF** | Working title of the first native Avrana game: a Coup-inspired hidden-role card game, built as a LAN Games module in the Avrana Party Games fork |
| **LAN Games** | The retired-upstream (BEACNpool, MIT) browser party-game server running live on the Pi (~28 games); Avrana maintains a fork |
| **Avrana Party Games** | Avrana's fork of LAN Games, where native games such as BLUFF are developed |
| **WORDCLASH, FIFTH SIGNAL, …** | Individual LAN Games titles (WORDCLASH has its own room engine) |
| **Arcade** | The live Gauntlet II stream: one RetroArch → one hardware H.264 encode → WebRTC to phones |
| **PS1 stream** | The same shared-stream design for PlayStation titles (branch `ps1-emulation`; blocked on power) |
| **Multitap** | A PlayStation adapter that gives one controller port four pads; how 4-player PS1 games get their players |
| **`hello`** | The first WebSocket message a LAN Games client sends; where identity enters a game today |
| **`wc-token`** | LAN Games' browser-held identity token (client-mintable today) |
| **Game key** | The secret per-(game session, participant) key the platform gives a game instead of any device identity (ADR 0003) |
| **Grant** | The appliance's record of what an installed game may do (trust tier, permissions, assigned path) — decided by the admin, never by the game |
| **Fork cutover** | Replacing the live LAN Games service with the fork plus the party bridge (a gated, owner-approved step) |
| **N2, N5, F1–F8** | Roadmap item numbers in `docs/ROADMAP.md` |

---

## References

ADRs `docs/adr/0002-party-platform.md`, `docs/adr/0003-ids-and-keys.md` · roadmap `docs/ROADMAP.md` (N5) · BLUFF
lifecycle/security precedent `docs/findings/2026-09-23-bluff-multi-agent-pass.md` · PS1 slots
`ps1/README.md`, `ps1/stream_ps1.py` (branch `ps1-emulation`) · arcade `arcade/README.md` ·
simulations `experiments/party-model/`, `experiments/viewports/` (branch `experiment/party-sim`).
