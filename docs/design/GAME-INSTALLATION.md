# Open game installation (no store)

Status: **conceptual (2026-09-24). Nothing here is built; no package manager, no marketplace.**
The third-party trust/sandbox model is a separate future design problem; this document only makes
sure today's choices don't create dead ends. Context: `GAME-INTEGRATION.md` (capabilities vs
runtime vs grant), `PARTY-PLATFORM.md` §13 (security).

**Reconciled 2026-10-02 with accepted direction (still nothing built):** [ADR 0014](../adr/0014-native-games-isolated-lan-games-retired.md) makes
every native game an independent process with its own service identity, reached by generic
routing from a registry and described by one canonical manifest; [ADR 0013](../adr/0013-party-and-game-browser-origins.md) puts game
clients on a separate browser origin; the LAN Games in-process runtime is legacy and retiring.
This document keeps its conceptual status. It deliberately does **not** freeze the final
`.avrgame` archive format, the exact sandbox or container implementation, or a marketplace or
community workflow; those wait until Checkers and Spades have proven the boundary.

## Accepted direction (2026-10-02)

- **One canonical per-game manifest.** Catalogue, grant validation and runtime registration derive
  from it or are mechanically checked against it; no further competing metadata layer (AVR-229).
- **Independent native-game process, per-game service identity.** A game owns its secrets and its
  state directory and can read nobody else's. "Built-in" is a statement of trust, not permission
  to share a process.
- **Generic routing, local IPC.** The front door routes from a runtime-readable game registry;
  Unix sockets are preferred where appropriate; one provisioning path creates identity, grants,
  keys and registration (AVR-236).
- **Platform-granted permissions.** The package requests; the appliance grants (unchanged).
- **Provenance and signing come later, and are not isolation.** A signature says *who published
  this and that it has not changed*. It never says the code is safe. A signed package still runs
  inside the same process, identity and origin boundaries as an unsigned one. Public-key
  cryptography belongs here, to package/update provenance, not to session tickets (ADR 0003
  amendment).
- **LAN Games runtime is legacy/retiring.** It is donor and reference code, not an installation
  target.

## Philosophy

Avrana does not need a proprietary game store. The intended feel is

> "Sure, install that weird GitHub project."

— install a package, add a trusted repository, add a Git repository, sideload local content, play
community-made Avrana-compatible games. **No** commercial marketplace, payments, reviews, DRM or
app-store backend.

## What exists today (and why it matters)

(Inventory from 2026-09-24. The LAN Games facts are still true of the deployed fork and are the
reason for ADR 0014; they describe the legacy runtime, not the model new games are built on.)

- **LAN Games:** every game is a Python module imported at the top of the registry and run in
  **one process, one event loop, as the platform's user**. One import error stops every game; one
  blocking tick freezes all games and chat; any module can read every session, every device token,
  `venue.json` (which holds the guest Wi-Fi password) and the avatar store; every game's page shares
  one origin and can read the `wc-token` in localStorage. Fine for built-in code; **not** a place for
  untrusted code.
- **Dependencies:** the fork's deploy script already refuses releases that change dependencies,
  because a live virtualenv can't be cleanly rolled back.
- **PS1 titles** (branch `ps1-emulation`) are hard-coded in two places (`run-ps1.sh` and `stream_ps1.py`)
  — *moved to validated `ps1/titles/*.json` profiles on branch `experiment/ps1-title-profiles`, not
  merged*; each title's `.cfg`
  is appended raw to RetroArch; the core is sha256-pinned; ROMs live read-only under `/srv`.

## Three layers, one rule

Capabilities (what the game is), runtime request (how its code runs) and grant (what the appliance
allows) are separate — see `GAME-INTEGRATION.md`. **The package describes and requests; the
appliance decides.** A manifest never sets its own trust tier, URL path or id namespace.

## How files arrive: every route feeds one pipeline

```
inbox → safe extract → staging → validate manifest → Admin confirms (tier + requested permissions)
      → games/<id>/<content-hash>/  + a "current" pointer        (state lives separately: state/<id>/)
```

| Route | Offline? | Notes |
|---|---|---|
| Folder drop-in (USB stick, scp from a laptop) | yes | the simplest; **v0** |
| Archive (zip/tar with a manifest) | yes (USB, phone upload, laptop) | needs path-traversal/symlink/setuid/zip-bomb protection, a size cap and a free-space reserve |
| Git URL + pinned commit | only with upstream internet; otherwise clone on the laptop and carry a `git bundle` | cloning runs no hooks, but build steps (npm, pip) would: **no builds on the Pi** |
| Signed archive (later) | yes | an Ed25519 key pinned at first install; a signature proves *same publisher*, not *safe*, and changes nothing about runtime isolation. A "trusted repository" later = a signed index |

- **Update:** install beside the old version, snapshot state, switch the pointer, keep the
  previous version for rollback. An updated trusted game drops to untrusted until re-approved.
- **Uninstall:** remove code and any unit; the Admin chooses whether to keep saved state.
- **Dependencies:** never run a package manager at install time (no PyPI offline; native wheels
  must match aarch64 and the Python version; building from source runs arbitrary code). A game may
  use the standard library plus a platform-pinned SDK, vendored pure-Python code, or a static
  aarch64 binary.

## Trust tiers (conceptual)

| Tier | Where it comes from | May use |
|---|---|---|
| **Built-in** | ships with the image | the isolated `process` boundary like any other game (target, ADR 0014). In-process LAN Games modules are the legacy runtime of today's built-in titles only |
| **Trusted** | the owner vouched for one specific content hash | a separate process; never in-process with the platform or another game |
| **Community** | anything else (the default) | `emulator_profile`, and later sandboxed `process` / `static_web` only |

An untrusted game must **never**: read other games' state, the platform database, token or PIN
hashes, the admin PIN file, `venue.json` or avatars; receive device tokens or profile ids (it gets
a game key and persona only); reach the internet or the LAN or open a LAN port; run as the platform
user or touch `/dev/uinput`, the display, audio devices or X; write outside its state folder or run
after its session; post system chat or drive party navigation beyond its own session; count toward
cross-game achievements except under a `community` provenance label.

### Isolation that is cheap on a Pi (later; needs owner-approved systemd/nginx changes)

The process and origin *boundaries* are now accepted direction for all games (ADRs 0013/0014).
The specific directives and headers below remain an illustrative sketch of the stronger tier for
untrusted code, not a frozen implementation. The field-test baseline for first-party native games
(`DynamicUser`, a Unix socket, a per-game credential and state directory, no IP sockets) is
proposed in [ADR 0016](../adr/0016-service-identities-and-local-trust-boundary.md); `PrivateNetwork`,
system-call filters and resource ceilings stay in this stronger tier.

- **Server side:** one systemd template unit per game with `DynamicUser`, `PrivateNetwork=yes`
  (loopback only; nginx reaches it over a unix socket — this alone stops exfiltration, LAN scanning
  and mining pools), `ProtectSystem=strict`, `ProtectHome`, `StateDirectory`, `NoNewPrivileges`, a
  system-call filter, and `MemoryMax` / `CPUQuota` / `TasksMax`; running only while the game is
  active.
- **Browser side — the real risk.** HttpOnly stops scripts *reading* the party cookie, but JavaScript
  on the party origin can still *send requests as the viewer* (host controls; even admin actions,
  by fetching an admin page on the same origin and reading its anti-CSRF token). A separate
  **port** is a separate origin for reads and Origin checks (which is why a future web admin should
  live on its own port — `PARTY-PLATFORM.md` §13), but cookies set on either port go to both, so it
  is no cookie boundary; a separate **host name** needs DNS work. **Decided 2026-10-02
  ([ADR 0013](../adr/0013-party-and-game-browser-origins.md)):** that DNS work is worth doing for *all* game pages — a separate game
  hostname under the existing certificate/DNS model is the near-term preference, so no game page,
  trusted or not, holds the member cookie. On top of that, the stronger and cheapest fix for
  *untrusted* game pages:
  - **every** response under an untrusted game's path gets `Content-Security-Policy: sandbox
    allow-scripts` and `X-Content-Type-Options: nosniff` (a single file served without the header —
    a direct link to `/games/x/raw.html`, an uploaded SVG — would run unsandboxed on the party
    origin), plus `default-src 'self'`;
  - the sandbox gives the page an opaque "null" origin: Lax cookies aren't sent. The game's **own**
    endpoints authenticate by seat ticket and accept `Origin: null`; party and admin endpoints reject
    it;
  - embed the page in a platform frame and pass the ticket and storage via `postMessage`; the frame
    exposes **no host verbs**; platform controls stay outside the frame, and PINs are only ever
    entered there (so a game can't fake an "enter admin PIN" prompt);
  - avatars and other uploads are re-encoded (PNG/JPEG), never served as uploaded.

  The trusted Party origin holds identity; game pages hold none (tickets only). The cost: sandboxed games are
  second-class (no localStorage, harder fullscreen and audio unlock — the same drawbacks ADR 0002
  lists for iframes).

## Emulated titles are content plus a small profile

ROMs and BIOS are user-supplied and never packaged. A title profile is **data from an allowlist**:
a content match (serial or sha256), a reference to a platform-pinned core, allowlisted core options,
the slot/port map, `personal_viewports`, and capabilities. **Never** accept a raw RetroArch config
from a community profile: some keys load shared objects (`video_filter`, `audio_dsp_plugin`), open
a UDP command port (`network_cmd_enable`), enable netplay or achievements, or redirect folders —
the platform generates the config from the profile. Cores are never community-supplied. Remaining
risk: a crafted ROM exploiting a core bug; run the emulator in the same kind of sandbox (no network,
read-only ROM view).

## Realistic threats and the minimum to plan for

| Threat | Why it matters here | Plan |
|---|---|---|
| Crypto-miner | heat and power draw throttle a Pi that already has under-voltage history | CPU quota, run only while active, no outbound network |
| Exfiltration once an upstream exists | profiles, device tokens | `PrivateNetwork`; CSP sandbox for pages on phones with mobile data |
| Identity theft | tokens, PIN hashes | no untrusted in-process code; game keys only; sandboxed pages |
| "Bricking" the SD card | realistically a full disk (SQLite corruption, worse with power loss) and wear | safe extraction, free-space reserve, only the state folder writable, no install hooks |
| Code changing under you | a Git project force-pushes | pin hash/commit; updates are explicit |

## v0: the smallest step that creates no dead ends

- Games live in a directory; each has an `avrana.json` manifest; the owner copies them in. The game
  list = built-in manifests (LAN Games derived from its registry) + that folder. (The manifest
  file name and layout here are illustrative; the canonical manifest is AVR-229.)
- Runtimes accepted (as written 2026-09-24): built-in `lan_games_module`, `emulator_profile`, and `external` (today's
  arcade and PS1 servers). *Superseded 2026-10-02:* `lan_games_module` is legacy/retiring; the
  native path is an isolated `process` proven first by Checkers (ADR 0014). **Moving the two hard-coded PS1 title lists into profiles pays off now** (done on
  `experiment/ps1-title-profiles`),
  and it is the path community content will take later.
- Build in from the start: a manifest version; the capabilities/runtime split; platform-assigned
  URL paths; namespaced ids (nothing can shadow a built-in); a grant record; code folder separate
  from state folder; seat tickets bound to one game; the trust tier carried into stats provenance.
- **Deferred:** any untrusted code and both sandboxes; the `postMessage` bridge; an upload/USB import
  screen; git fetch on the Pi; pip and per-game virtualenvs; signing and trusted repositories;
  containers; automatic updates.
