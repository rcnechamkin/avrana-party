# ADR 0004: Full Mode origin, platform contracts and provider boundaries

Date: 2026-09-26. Branch: `claude/dreamy-carson-sja5mq` (merged as PR #3, `a671955`).

Status:
- **D1 is ACCEPTED**: it restates the owner's sprint brief of 2026-09-26, which treats the HTTPS
  origin as established architecture.
- **D2–D6 are PROPOSED**: they are built and tested on this branch, and become decisions when it is
  merged.
- Nothing in this ADR is deployed.

Context: `docs/runbooks/party-https.md` (HTTPS is LIVE since 2026-09-25), `docs/design/PARTY-PLATFORM.md`
§4/§16.1 (written before HTTPS and now partly superseded), ADR 0002/0003, `docs/design/GAME-INTEGRATION.md`,
`docs/research/AVRANA-OPEN-SOURCE-SUBSTRATE.md` (see its 2026-09-26 decision matrix) and the research summary
in `docs/findings/2026-09-26-architecture-sprint.md`.

## D1. The canonical Avrana origin is `https://party.avrana.net` (ACCEPTED, owner brief)

- **Avrana-owned pages live under `/party/` on the 443 server only.** That covers the Full Mode shell today
  and Party Home when it ships.
- **The port 80 default server is unchanged:**
  - Apple probes still get `Success`.
  - Other probe paths still reach LAN Games, as before.
  - There is no global redirect.
  - HTTP is not a recovery path for the Party page, which is HTTPS-only; the shell links guests to
    `http://10.42.0.1/` (the LAN Games hub) when HTTPS can't be reached.
- **No HSTS, ever,** on `party.avrana.net` or `avrana.net`. An expired certificate must stay
  escapable.
- **Credentials stay on the Pi.** The TLS key never leaves it, and there is no private CA on phones.
- **Consequences:**
  - HTTP and HTTPS are separate origins (cookies, storage, service workers), so a phone that
    switches between them looks like two devices.
  - Party identity (F3) is therefore scoped to the HTTPS origin, and the cookie gains `Secure`.
  - The experiment branches' HTTP-only Origin checks must accept `https://party.avrana.net`
    before they can run there: `experiments/party-service/service.py:325` and
    `ps1/stream_ps1.py:549` (`docs/findings/2026-09-26-architecture-sprint.md`).
- **Still OPEN:**
  - the HTTP "doorway" (an HTTP page that probes HTTPS and hands off);
  - a Host-specific redirect of `http://party.avrana.net/`;
  - whether `/` itself becomes Party Home.

## D2. Capability Engine v0: per seat, observed, never user-agent based

Five inputs stay separate: device capability (observed in the browser), seat (role in this game),
runtime capability (what the appliance's providers offer), game requirement (the contract) and the
output, a presentation strategy per seat.

- Four statuses: `yes`, `no`, `partial` and `unknown`. **`unknown` is never treated as `no`.**
- Probes never prompt. Camera and microphone are read from the Permissions API only, and `persist()`
  is never called.
- A weak phone changes only its own seat: it gets a fallback (watch, TV controls) or a plain
  explanation. The party never takes the minimum across seats. Only runtime limits can affect
  every seat.
- The capability report is advisory UX, never an authorization input.

Names are in `contracts/capabilities.v0.json`. The evaluation is implemented twice and pinned by
shared vectors:
- `avrana/contracts/evaluate.py` (the server side, for the future seat scheduler);
- `web/party/lib/evaluate.js` (advisory, in the browser).

## D3. Game Contract v0 replaces manifest v0 as the contract on `main`

- **Source:** `contracts/games/*.json`, validated by `avrana/contracts/game.py`. It grows from the
  experimental manifest v0: same ids, enums and strictness, and `lift_manifest_v0()` converts v0
  manifests.
- **What it adds:**
  - ordered **presentations** (`browser_native`, `shared_stream`, `personal_viewport`,
    `controller_only`, `app_native`), each with required and optional device and runtime
    capabilities and roles;
  - a per-seat **fallback**;
  - requested `runtime.permissions` and `resources`;
  - an optional `package` block and reverse-DNS `extensions`.
- **A Personal Viewport is a method with a `viewport` kind** (`crop`, `dedicated_stream`,
  `browser_renderer` or `private_panel`), never a synonym for cropping.
- **The package describes and requests; the appliance decides.**
  - `contracts/appliances/*.json` holds the grants: entry path, health path, tier and granted
    permissions.
  - The contract validator rejects grant-side keys by name (`entry`, `path`, `tier`, `trust`,
    `namespace`, `signature`, …).
  - A grant can't give a permission the contract didn't request (checked at catalog build).

## D4. Three provider boundaries, policy stays in Avrana

`avrana/providers/base.py` defines them as `typing.Protocol` (no framework, no registry object):

| Boundary | Today (arcade, LIVE code) | In view |
|---|---|---|
| **RuntimeProvider**: `start`, `running`, `stop`, `status` | `RetroArchRuntime` (child process; its network command port stays off) | PS1 launcher (`runtimes.py`, experiment); later a headless-GPU display (spike S1) |
| **InputProvider** + **VirtualController**: `open`, `set_state` (a full snapshot), `neutralize`, `close`, plus `isolation` | `UInputGamepadProvider` (isolation: global) | XTest key banks for PS1 (isolation: private) |
| **PresentationProvider**: `request_keyframe`, `status` (the attach/set_view/detach surface is documented, not built) | `arcade/stream.py` `Stream` (one shared encode) | client crop (PS1), dedicated streams (spike S2), Selkies/pixelflux (spike S3) |

Each provider declares the runtime capabilities it offers, and the appliance profile lists the
installed providers with `live`, `experiment` or `planned` status.

**These stay in Avrana:** seat → slot, seat tickets, input staleness and background release, rate
limits, Personal Viewport policy, the encoder budget, lifecycle UX, and the rule never to expose
an emulator control port.

## D5. The offline copy is a convenience, not a recovery mechanism

The service worker at `/party/sw.js` is scoped to `/party/` (no `Service-Worker-Allowed` header).
- It is network-first for everything, so a phone on the Party Wi-Fi always runs the current build.
- The cache only answers when the Pi can't be reached, and the page then says so.
- It never caches the hub, the arcade, `/party/api/*`, any party state or identity.

Kill switches, from least to most drastic:
- `version.json` says `serviceWorker: false`;
- a self-destruct `sw.js` build, installed with `ops/install-party-web.sh --kill`;
- a manual "Remove offline copy" on `/party/diag/`.

**Limits:**
- An installed worker may still render the cached page with an expired certificate, but every
  live call then fails.
- Safari evicts worker storage after about 7 days without use.

So the HTTP recovery origin and, later, the app path remain the real recovery routes (research D,
§5.3).

## D6. Test tiers

- **Tier 1**: pure, no appliance.
- **Tier 2**: a simulated Party on localhost. Real nginx with the committed site and stand-in
  upstreams, and real Chromium against `avrana/web/devserver.py`.
- **Tier 3**: the Pi, phones, AP, HDMI and encoder.

CI runs Tier 1 and Tier 2. Tier 3 stays manual, and results from a lower tier are never reported as
hardware validation.

## Consequences

- Deploying the shell is a one-time, owner-approved nginx change (443 block only) plus
  `sudo bash ops/install-party-web.sh <checkout>`. Rollback is `--rollback`, and the kill switch is `--kill`.
- `arcade/stream.py` now imports `avrana/` from the repository root, which the production checkout
  contains. `/stats` gains a `providers` block. The arcade *page* changes go live with the
  production fast-forward, because `stream.py` serves `index.html` from the checkout on every
  request. The server refactor runs on its next start.
- **Follow-ups:**
  - Party Home should adopt `web/party/lib/*` (capabilities, keep-awake, shell), and its service
    should own the dynamic `/party/` routes, while nginx keeps serving the static files.
  - Seat ticket v2 must bind the seat generation, not the slot.
  - The arcade `watch()` should exit on a fatal error so systemd restarts it (research B).

## Amendments (2026-10-02)

The text above is left as written. Two later decisions change parts of D1:

- **[ADR 0012](0012-limited-mode-party-survives-https-loss.md)** supersedes "HTTP is not a recovery
  path for the Party page, which is HTTPS-only; the shell links guests to `http://10.42.0.1/` (the
  LAN Games hub) when HTTPS can't be reached". The accepted target is a Limited Mode in which the
  Party itself stays usable without trusted HTTPS. The canonical origin, no HSTS, credentials on
  the Pi and unchanged captive probes all stand. The `Secure` Party cookie stands and is not
  weakened; Limited Mode gets an explicit identity model. Production remains HTTPS-only until a
  verified deployment says otherwise ([SYSTEM](../SYSTEM.md)).
- **[ADR 0013](0013-party-and-game-browser-origins.md)** keeps `https://party.avrana.net` as the
  trusted Party origin and moves game clients to a separate browser origin; "one origin for
  everything" is no longer the target.
- D5's last line ("the HTTP recovery origin and, later, the app path remain the real recovery
  routes") is read with ADR 0012: the recovery route is Limited Mode, not the LAN Games hub.
