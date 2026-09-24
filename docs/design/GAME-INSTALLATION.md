# Open game installation (no store)

Status: **conceptual (2026-09-24). Nothing here is built; no package manager, no marketplace.**
The third-party trust/sandbox model is a separate future design problem; this document only makes
sure today's choices don't create dead ends. Context: `GAME-INTEGRATION.md` (capabilities vs
runtime vs grant), `PARTY-PLATFORM.md` §15 (security).

## Philosophy

Avrana does not need a proprietary game store. The intended feel is

> "Sure, install that weird GitHub project."

— install a package, add a trusted repository, add a Git repository, sideload local content, play
community-made Avrana-compatible games. **No** commercial marketplace, payments, reviews, DRM or
app-store backend.

## What exists today (and why it matters)

- **LAN Games:** every game is a Python module imported at the top of the registry and run in
  **one process, one event loop, as the platform's user**. One import error stops every game; one
  blocking tick freezes all games and chat; any module can read every session, every device token,
  `venue.json` (which holds the guest Wi-Fi password) and the avatar store; every game's page shares
  one origin and can read the `wc-token` in localStorage. Fine for built-in code; **not** a place for
  untrusted code.
- **Dependencies:** the fork's deploy script already refuses releases that change dependencies,
  because a live virtualenv can't be cleanly rolled back.
- **PS1 titles** are hard-coded in two places (`run-ps1.sh` and `stream_ps1.py`); each title's `.cfg`
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
| Signed archive (later) | yes | an Ed25519 key pinned at first install; a signature proves *same publisher*, not *safe*. A "trusted repository" later = a signed index |

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
| **Built-in** | ships with the image | any runtime, including in-process LAN Games modules |
| **Trusted** | the owner vouched for one specific content hash | prefer a separate process; in-process only with a plain warning that it can see everything |
| **Community** | anything else (the default) | `emulator_profile`, and later sandboxed `process` / `static_web` only |

An untrusted game must **never**: read other games' state, the platform database, token or PIN
hashes, the admin PIN file, `venue.json` or avatars; receive device tokens or profile ids (it gets
a game key and persona only); reach the internet or the LAN or open a LAN port; run as the platform
user or touch `/dev/uinput`, the display, audio devices or X; write outside its state folder or run
after its session; post system chat or drive party navigation beyond its own session; count toward
cross-game achievements except under a `community` provenance label.

### Isolation that is cheap on a Pi (later; needs owner-approved systemd/nginx changes)

- **Server side:** one systemd template unit per game with `DynamicUser`, `PrivateNetwork=yes`
  (loopback only; nginx reaches it over a unix socket — this alone stops exfiltration, LAN scanning
  and mining pools), `ProtectSystem=strict`, `ProtectHome`, `StateDirectory`, `NoNewPrivileges`, a
  system-call filter, and `MemoryMax` / `CPUQuota` / `TasksMax`; running only while the game is
  active.
- **Browser side — the real risk.** HttpOnly stops scripts *reading* the party cookie, but JavaScript
  on the party origin can still *send requests as the viewer* (host controls; even admin actions,
  by fetching the admin page and reading its anti-CSRF token). A separate **port** doesn't help
  (cookies ignore ports); a separate **host name** needs DNS work. The cheapest fix: serve untrusted
  game pages with `Content-Security-Policy: sandbox allow-scripts` (an opaque "null" origin: Lax
  cookies aren't sent and `Origin: null` fails the Origin checks) plus `default-src 'self'`, embed
  them in a platform frame, and pass the seat ticket and storage via `postMessage`. The single origin
  still holds identity; untrusted pages hold none. Keep platform controls outside the frame and only
  ever take PINs there, so a game can't fake an "enter admin PIN" prompt.

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
  list = built-in manifests (LAN Games derived from its registry) + that folder.
- Runtimes accepted: built-in `lan_games_module`, `emulator_profile`, and `external` (today's
  arcade and PS1 servers). **Moving the two hard-coded PS1 title lists into profiles pays off now**,
  and it is the path community content will take later.
- Build in from the start: a manifest version; the capabilities/runtime split; platform-assigned
  URL paths; namespaced ids (nothing can shadow a built-in); a grant record; code folder separate
  from state folder; seat tickets bound to one game; the trust tier carried into stats provenance.
- **Deferred:** any untrusted code and both sandboxes; the `postMessage` bridge; an upload/USB import
  screen; git fetch on the Pi; pip and per-game virtualenvs; signing and trusted repositories;
  containers; automatic updates.
