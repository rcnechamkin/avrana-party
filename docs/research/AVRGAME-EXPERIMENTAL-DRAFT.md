# `.avrgame` v0: EXPERIMENTAL DRAFT (not a specification, not accepted)

- **Status:** Experimental finding. **EXPERIMENTAL DRAFT.** Not a specification. Not accepted. Not frozen. Not implemented: no validator, installer, SDK or provider exists. AVR-37 owns the `.avrgame` v0 specification; this text is evidence input to it and a record of what the current system already does, never a contract.
- **Date:** 2026-10-10
- **Sources:** Linear AVR-37 (gate text, owner 2026-10-07), AVR-38, AVR-39, AVR-45, AVR-135, AVR-143, AVR-316; ADR 0013, 0014 (decision 12), 0015, 0016; `contracts/README.md`; Checkers findings; `docs/runbooks/provision-game.md`.
- **Related:** `docs/research/DEVELOPER-FRICTION-AUDIT.md`, `docs/research/MISSING-PUBLIC-ABSTRACTIONS.md`, `docs/research/DEVELOPER-PLATFORM-STATE-2026-10-10.md`

**Freeze gates (all required before any name in this file may be called stable).**

1. Checkers integration: **met for drafting.** The Checkers pair merged (Party `defd4a2`, Games `fb711d9`; AVR-238 and AVR-314 Done on 2026-10-10).
2. Review of the AVR-27 four-human BLUFF evidence against this text, in writing, plus owner acceptance. **Not met.**
3. Spades boundary validation per ADR 0014 decision 12 ("until Checkers and Spades have proven the boundary"). AVR-312 produced only a readiness packet and no port, so Spades has **not** proven anything. **Not met.**

A freeze in the AVR-37 sense is an explicit owner act. Until then, no document, comment or code may describe `.avrgame` as v0 stable.

## Reading guide

Legend per field: **P** proven by the stand-in (`avrana/games/standin`, test only) **and** Checkers; **S** shown by the
stand-in or Checkers individually, or only in CI or against a fake Party; **A** assumed (no code or evidence); **O** open
(the owner or another issue decides). "Proven" never means real phones or the Pi: neither has run (AVR-261).
Everything is derived from what exists today; nothing is invented that a game does not already do. This text
was written against the Checkers branches and has not been re-checked against merged `main` line by line.

## Direction constraints added 2026-10-10 (approved direction; the draft below predates them)

- **One open format, one appliance-side install path.** Official storefront, owner app and open sources all hand a package to the same appliance validate/install path (AVR-143, AVR-316). A package must remain installable and playable with no official commerce infrastructure and no account. Nothing in this draft may be read as requiring a store.
- **Publisher identity, signature and entitlement evidence are out of scope here** (AVR-58, AVR-316, AVR-73). The manifest should be able to carry such metadata later without a second package format or a parallel installer. A publisher may choose store-only licensing without changing the technical format.
- **Phone-side material is portable browser content only.** `client/` is HTML, JavaScript, browser-hosted WASM and assets served from the appliance. A package must not rely on downloaded native iOS or Android code (AVR-45). Eligibility to run inside a native owner app may be stricter than eligibility to install on the appliance; that policy layer is separate from this format.
- **The appliance is authoritative.** Server-side game state and any native server process stay on the appliance. A courier or phone app transports bytes and holds no install authority (AVR-45, AVR-63).
- **Friend-ready 1.0 does not depend on any of this.** The format is not a 1.0 blocker.

## 1. Package layout (A, shaped by Checkers' tree)

```
<id>/                       directory name = game id
  avrgame.json              manifest (section 2)
  server/ ...               OPTIONAL authoritative process, run by the appliance as a native game
  client/                   portable browser bundle (HTML/JS/CSS, optional WASM/Workers/assets)
    index.html
    onboarding.json         avrana.onboarding/v0 (P: Checkers; shown by Party's library)
    icon.svg                (S: Checkers only; real artwork path is open, see 2.4)
  NOTICE / LICENSE
```

Checkers today is `checkers/` (Python, stdlib only) with `web/` and no manifest of its own: its manifest is
Party-side `contracts/games/checkers.json` plus a grant in `contracts/appliances/avrana-pi4.json`. A package
manifest would **replace nothing yet**; it is the thing that would generate those two. O: whether `client/` and
`server/` are separate roots (AVR-37 text) or Checkers' single tree stays valid.
Rule: the complete package is installed on the appliance; phone caches are disposable (AVR-37). A client bundle
must not require that it is the top-level document or that a specific transport is used (owner guardrail). Today
Checkers' own server sets `frame-ancestors 'none'` (Games `checkers/server.py:89` (as of 2026-10-09)); that is a property of one game's server, not of this package.

## 2. Manifest fields

### 2.1 Identity and compatibility

| Field | Maps to today | Mark |
|---|---|---|
| `format`: `avrana.avrgame/v0` | new; contracts say "a new field needs a new schema version" (`contracts/README.md:28`) | A |
| `id` | Game Contract `id`: `^[a-z][a-z0-9_-]{0,39}$`, not `home/party/admin/shared/diag/api`, equals contract file name | P |
| `name`, `summary` | contract `name` 1-60, `summary` 1-140 chars | P |
| `package.version`, `publisher`, `license` (SPDX), `source`, `revision`, `platforms` | contract `package`, "display-only claims until signing exists" | S (stand-in has them; no enforcement) |
| `requires.format` / `requires.party` (contract + session protocol + bridge + result versions) | `avrana.game/v0`, `avrana.party-session/v0`, `avrana.party-bridge/v1`, `avrana.game-result/v1`; Games pins digests in `provider/avrana-contract.json` | S: pinned by digest in Checkers; no general negotiation. **Fails closed** (AVR-37 AC): unknown version = refuse. O: compatibility/deprecation policy is AVR-72 |
| `build` | `game.build` in result (ADR 0015 s6). Checkers: hand-kept constant `checkers-0.1.1` (`checkers/party.py:48`) | O (Checkers D15: constant vs provisioning digest vs self digest) |

### 2.2 What the game is (the Game Contract, unchanged)

`kind`, `players{min,max}`, `screen`, `input`, `late_join`, `spectators`, `private_player_ui`, `presentations[]`,
`fallback`, `accessibility`, `extensions` are exactly the `avrana.game/v0` fields (`contracts/README.md:51-76`) and keep
their validator (`avrana/contracts/game.py`). Mark **P** for the field set as used by standin + Checkers; **A** that one
file can carry both. `extensions["net.avrana.party"].pregame` is read by Party Core (README: next version "should make it a field"); Checkers uses `false`: O (Checkers D11, who plays with no pregame). A request is never a grant: `tier`, health, URL paths and granted permissions are appliance-owned (validator rejects them by name; P).

### 2.3 Runtime (how the appliance starts the server)

| Field | Maps to today | Mark |
|---|---|---|
| `server.command` array, `server.working_directory` | grant `runtime{command[], working_directory}`, absolute, no `.`/`..`/`//`, root-owned path, exactly two keys (`contracts/README.md:127-135`, provision-game runbook step 3) | S: stand-in proven in real systemd on CI; Checkers by subprocess harness and CI, **not** under systemd when this draft was written; a real-systemd run on a CI runner was later recorded in `docs/findings/2026-10-09-checkers-systemd-proof.md` |
| Launch handoff (appliance-set, not manifest): fd 3 listener (`LISTEN_FDS`/`LISTEN_PID`), key credential at `$AVRANA_PARTY_KEYS/<id>.key`, `$AVRANA_PARTY_SOCKET`, `$AVRANA_PARTY_ORIGIN`, `$STATE_DIRECTORY` | `standin/game.py:5-17`; ADR 0016 s5 calls it "a field-test runtime convention, not an SDK ... may change before `.avrgame`" (`0016:248-251`) | P as convention; **O** as public contract |
| Session protocol routes `POST .../avrana/session/v0/launch` and `/end`, signed, never proxied, ticket redeem, `ended` with `avrana.game-result/v1` | `standin/game.py:19-29`, Checkers `server.py` | P |
| `end` after own `ended` is acknowledged | Checkers yes, stand-in 403 | O (Checkers F3/D13) |
| Idle stop | ADR 0016 s4 requires; Checkers exits after 60 s without session (follow-up note); stand-in none | S, O (D14) |
| `runtime.permissions` (`persistent_storage`, `party_roster`, ...) | contract; grant may not exceed request | S: Checkers asks `party_roster` only |
| Resource ceilings | unit comment: "come from measuring a real game (AVR-238)" | O (not measured) |
| No IP sockets, no DNS, no hardcoded address family | unit filter `AF_UNIX` | S (Checkers F1: needs a socket built on the inherited fd) |

### 2.4 Client, onboarding, artwork

| Field | Today | Mark |
|---|---|---|
| `client.entry` same-origin path ending `/` outside `/party/ /admin/ /shared/` | grant `entry` | P |
| Uses the Party bridge only; no Party cookie, no direct Party API | ADR 0013; `avrana-party-bridge.js` (shim, vendored, pinned by digest); Checkers test `tests/test_checkers_web.py:163-199` | S: proven with fake bridge/DOM; real iPhone validation pending (ADR 0013:130-133) |
| Bridge shim and "where is Party" route served by the runtime, not each game | Checkers/stand-in/fork each serve them (F10) | O |
| `client.onboarding`: `avrana.onboarding/v0` (premise, `ack`, facts, sections) | Checkers `onboarding.json`; v1 (`GAME-UX-CONTRACT.md:455-523`) proposed, not built; objective, actions list, section ids, show policy absent | S for v0; **O** for AVR-37's requested shape |
| Icon / cover | Checkers `icon.svg` + `net.avrana.catalog`; Party `contracts/artwork.json` maps only `lan:`/`kenney:` sources; covers live under owner covers folder (`avrana/web/covers.py`) | O (AVR-294 human/licensed art) |
| Capabilities: `presentations[].requires/optional.device` (e.g. `wake_lock`, `websocket`) | contract | P |
| Loading profile, critical vs deferred assets, cache size, seat-ready signal | AVR-37/135 text; nothing built | A/O |

## 3. Install and validate lifecycle (A: nothing implemented; all of it is existing `provision-game` behavior or absent)

1. **Validate (offline, no root):** manifest schema, unknown key = error, duplicate key = error (README rules), contract valid, `format`/`requires` known, grant request <= contract request, files present, no path escapes, size bounds. Today only the contract and catalog validators exist; there is **no** single-package validator or CLI (`python3 -m avrana.contracts.catalog` validates all contracts).
2. **Stage:** unpack to a root-owned release tree (`/opt/...`), never a home directory (provision-game step 3). Today done by `ops/deploy.sh` for the Games release, not by a package tool.
3. **Provision:** `python3 -m avrana.ops.provision_game <id>` (key, registry entry `games.d/<id>.json`, template units, drop-in, socket, Party Core reload). Requires a grant with `runtime` in the appliance profile (a manual repo edit today).
4. **Catalog:** generated from contract + grant (`python3 -m avrana.contracts.catalog`).
5. **Remove:** `provision_game <id> --remove [--keep-state]` (refused during a session).
Install must be staged enough to leave no half-installed catalog entry (AVR-39 AC): the provision command reconciles and is re-runnable, but atomic staging of the *package* is **O**. Install is the same path as first-party games (AVR-39); **no second install path**.

## 4. Trust rules (S/A)

- A package requests; only the appliance grants (tier, permissions, key). A manifest cannot assert `builtin`/`trusted` (A; contract `package` is display-only).
- Package bytes on the appliance are canonical; native game code runs only root-owned, as its own `DynamicUser`, with its own key, on its own Unix socket (ADR 0016; P for stand-in under systemd in CI).
- Treat everything from phones as untrusted: strict bounded JSON, lone-surrogate/non-ASCII token handling (Checkers `party.py:69-114`; stand-in lacks it), constant-time token compare as UTF-8 bytes. Refuse control traffic that carries any proxy header (presence, not value; Checkers F-3.2).
- Never send private state to a client because the UI hides it; each phone gets only its seat's view (P: Checkers `session.py` per-seat view).
- A game never learns a member or device id; only the session participant id (ADR 0015).
- Compatibility fails closed. Signing, provenance, community source, update/rollback: **deferred** (AVR-57, 58, 60, 62).

## 5. Explicit non-goals

Archive format and compression; signing/PKI; marketplace and community repository; emulated games (separate provider);
native-binary porting; WKWebView-specific APIs; mandating WebSocket vs long poll (Checkers uses a 25 s long poll, BLUFF still uses the fork's hubnet transport, ADR 0014 Consequences); a rules engine;
mandating that the game is the top-level browser document or how the Party layer is presented (AVR-83, AVR-292); a mobile-app host (AVR-45), though `client/` must stay portable;
durable results history (AVR-71); a Python SDK class; a freeze of any name in this file.

## 6. What this draft cannot yet say

Needs more than one native game of different shape (teams, hidden hands, clocks: AVR-312 packet lists them), BLUFF human findings (AVR-27), real-phone/Pi measurement (AVR-261, AVR-138), AVR-135 execution/cache contract, and owner answers on D11 to D15.
