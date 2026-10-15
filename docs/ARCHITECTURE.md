# Architecture

This page describes how Avrana Party works as implemented on `main`. It is an overview: each
section links to the decision record or design document that holds the detail. Where the running
appliance differs from `main`, [SYSTEM](SYSTEM.md) is the record of what is deployed.

## The shape of the system

Avrana Party is a Raspberry Pi 4 that runs its own Wi-Fi network and serves everything players
need from the device itself. Phones join the network and use an ordinary browser. There is no
app to install, no account, and no internet connection in the play path.

```
 phones (browser)
     │  Wi-Fi "Avrana Party", local DNS
     ▼
 nginx ── :80   captive-portal probes, legacy games hub, /arcade/
       ── :443  party.avrana.net
       │    /party/          static Party shell (web/party/)
       │    /party/api/  ──► Party Core            127.0.0.1:8191  (avrana/party/)
       │    /games/bluff/…  ► LAN Games fork        127.0.0.1:8096  (separate Games repository)
       │    /games/<id>/  ─► native game            /run/avrana-games/<id>.sock
       │    /arcade/     ──► arcade streamer        127.0.0.1:8097  (arcade/)
       └─ :443  games.avrana.net   game origin: native games only, never /party or /arcade

 Party Core ──signed launch/end──► each game server (loopback TCP or Unix socket)
            ◄──signed "ended" + result envelope──
```

The nginx configuration is one file, [`avrana-party.nginx`](../avrana-party.nginx). Local DNS
(NetworkManager's dnsmasq, configured by [`avrana-captive.conf`](../avrana-captive.conf)) answers
`party.avrana.net` with the Pi's access-point address, so a real certificate for a public domain
name works with no internet connection. The certificate is a Let's Encrypt certificate obtained with
the ACME DNS-01 challenge (`lego`), so the Pi never has to be reachable from the internet. Only
issuance and renewal (`ops/renew-party-certificate.sh` and its systemd timer) need an internet
connection, and play does not. The network setup is in the [network runbook](runbooks/network.md) and the HTTPS setup in
[party-https](runbooks/party-https.md).

## Components

### Party shell (`web/party/`)

The interface every phone sees at `/party/`: Party Home, the Library of games, the Party
(people, host controls, chat) and a System page. It is plain HTML and ES modules with no
framework or bundler. The CSS, icons, avatars and artwork are generated from sources and
committed; [GENERATED](GENERATED.md) lists each output and the command that rebuilds it.

- **Catalog.** `web/party/catalog.json` is generated from the game and appliance contracts in
  `contracts/` (`python3 -m avrana.contracts.catalog`).
- **Capabilities.** The shell probes what this browser can do (`lib/capabilities.js`) and decides,
  per seat, how each game would run on this phone (`lib/evaluate.js`). The same evaluation exists
  in Python (`avrana/contracts/evaluate.py`), and shared vectors keep the two in agreement.
- **Profile.** A player's display name and avatar are kept in the browser. There are no server-side
  player profiles.
- **Chat.** Party chat (`lib/party-chat.js`) still uses the chat service of the LAN Games fork.
- **Offline behavior.** A service worker (`sw.js`) is network-first and caches only the shell, so
  a phone that briefly loses the Pi can show a useful page. It never caches API responses, party
  state or identity.

Releases are built with `python3 -m avrana.web.build` and installed as atomic, versioned
directories under `/var/www/avrana-party/web/` by `ops/install-party-web.sh`.

### Party Core (`avrana/party/`)

The single authority for the party: who is present, who hosts, which game is on, and where every
phone should be. It is a standard-library Python HTTP service on loopback, reached only through
nginx at `/party/api/`.

- `core.py` holds the state machine. It is pure and synchronous, with the clock injected, which is
  what makes the lifecycle exhaustively testable. Rules come from
  [PARTY-LIFECYCLE](design/PARTY-LIFECYCLE.md).
- `service.py` is the HTTP layer. Phones long-poll `GET /party/api/state` (the poll doubles as a
  presence heartbeat), and the host's actions are POSTs guarded by `if_version`. Every request
  must carry an allowed `Host`, every POST an allowed `Origin`, and responses are never cached.
- `identity.py` issues a random device token in an `HttpOnly`, `Secure`, `__Host-` cookie. The
  browser never chooses its identity, and names never authorize anything. Only hashes of device
  tokens are stored on disk; the party itself lives in memory.

**The console model** ([ADR 0011](adr/0011-party-console-model.md)). The party is always in exactly
one place: `home`, `setup`, `game` or `results`. Every phone shows that place and only the host
moves it. Before a round, each member chooses to play or watch, and the host starts the round
([ADR 0010](adr/0010-party-pregame.md)). Game pages load `lib/party-follow.js`, which keeps each
phone where the party is.

### Games and the session protocol

Games are separate servers. Their source is in the separate Games repository, apart from the
in-repo stand-in game used for tests (`avrana/games/standin/`). Party Core talks to every game
over the **party session protocol** ([ADR 0006](adr/0006-party-session-protocol.md)):

- Party Core sends HMAC-signed `launch` and `end` messages to the game server. Each game has its
  own key.
- A phone gets a short-lived, signed **ticket** from Party Core and presents it to the game as
  its first WebSocket message. Games see an opaque per-session participant id, never a device or
  member id.
- When a game finishes it sends a signed `ended` message, optionally with a
  [result envelope](adr/0015-game-result-envelope.md).

`avrana/party/protocol.py` and `result.py` are self-contained so that the Games repository can
vendor them unchanged. Test vectors in `contracts/vectors/` hold both repositories to the same
bytes, and `tools/contract_check.py` checks the declared Party ↔ Games contract
([CROSS-REPO](CROSS-REPO.md), [design](design/PARTY-GAMES-CONTRACT.md)).

Games reach the appliance in one of two ways:

1. **LAN Games fork.** BLUFF, EXPO and the other LAN titles run inside one server on port 8096
   ([LAN Games provider](design/LAN-GAMES-PROVIDER.md)). This is what the appliance runs today.
   [ADR 0014](adr/0014-native-games-isolated-lan-games-retired.md) retires it in favor of native
   games.
2. **Native games.** One process per game, started on demand by the systemd template
   `deploy/games/avrana-game@.service`. The game listens on its own Unix socket, runs under a
   dynamic user, and receives its key through `LoadCredential=`. `ops/provision-game` and
   `ops/prepare-native-games` set this up. Party Core finds these games through a registry
   directory (`avrana/party/registry.py`). An experimental package format, `.avrgame`
   (`avrana/avrgame/`, [design](design/AVRGAME-PACKAGE.md)), is installed by `ops/install-game`,
   which also writes the appliance's effective catalog. This path is in source and tested on
   disposable Linux runners. It is not yet on the appliance.

**Two browser origins** ([ADR 0013](adr/0013-party-and-game-browser-origins.md)). The design keeps
the Party on `party.avrana.net` and game pages on `games.avrana.net`, so a game page can never use
the Party's cookie. A game page talks to the Party only through an invisible bridge frame
(`web/party/bridge.html`, `lib/bridge.js`) using `postMessage` (`avrana.party-bridge/v1`). Game
repositories vendor the matching shim, `web/party/bridge/shim.js`. The nginx server block exists
in source. Bringing the game origin up on the appliance is an owner procedure
([game-origin runbook](runbooks/game-origin.md)).

### Arcade streaming (`arcade/`)

`arcade/stream.py` runs one emulator (RetroArch with a MAME core, in a virtual X display) on the
Pi, encodes it once with the Pi's hardware H.264 encoder, and fans the stream out to each phone
over WebRTC (GStreamer `webrtcbin`). Phones send controls back. These become virtual gamepads
through `uinput` (`avrana/providers/`). Party Core starts and stops the emulator through the same
signed `launch` and `end` messages as any game, on a control port that nginx never exposes
([ADR 0009](adr/0009-arcade-party-provider.md), `avrana/party/managed.py`). Gauntlet II is the
working title. PS1 support (`avrana/providers/ps1.py`, `ps1/`) is experimental.

### Contracts (`contracts/`)

Machine-readable agreements between the Party, games, the appliance and browsers: the capability
vocabulary, one Game Contract per game, the appliance profile, the Party ↔ Games declaration,
the service boundary and the third-party inventory. Every file is strict JSON with a versioned
schema and a validator in `avrana/contracts/`. See [contracts/README](../contracts/README.md) and
[ADR 0004](adr/0004-full-mode-contracts-and-providers.md).

## Operations

- **Deployment.** [`ops/deploy.sh`](../ops/deploy.sh) is the one deployment entry point. The owner
  runs it on the Pi with explicit Party and Games commits. It refuses unsafe states and journals
  each phase. It installs the nginx site, builds code releases under `/opt` and a web release,
  restarts only the services whose code changed, writes a deployment manifest, runs smoke checks
  (`avrana/ops/smoke.py`), and can roll back to the last known good release. Procedure:
  [deploy runbook](runbooks/deploy.md).
- **Status.** `GET /party/api/status` (`avrana/ops/status.py`) reports what is deployed and
  whether each service is healthy ([STATUS-ENDPOINT](design/STATUS-ENDPOINT.md)).
- **Services.** The systemd units are in `deploy/` and `arcade/`. Each unit names its own service
  user. [ADR 0016](adr/0016-service-identities-and-local-trust-boundary.md) defines the intended
  isolation between services, and `python3 -m avrana.ops.boundary` checks a host against it.
- **Telemetry.** `telemetry/` holds power and health checks for the Pi.

## Modes of trust and failure

- **Full Mode** is the normal path: trusted HTTPS on `party.avrana.net`. Party Home needs it,
  because the device cookie is `Secure`.
- **Limited Mode** ([ADR 0012](adr/0012-limited-mode-party-survives-https-loss.md)) keeps the party
  usable over plain HTTP when the certificate is unavailable. Party Core can run a second loopback
  listener that issues only a separate, limited credential and reports `"mode": "limited"`, and
  the shell adapts (`lib/limited.js`). The production nginx site does not route plain HTTP to it.

## Development and tests

No Pi is needed for most work. `npm run dev` starts `avrana.web.devserver`, a local stand-in for
the appliance's HTTPS site; with `--party` it runs a real Party Core behind it. Tests are layered:

- Python unit tests (`tests/unit/`)
- browser-module tests in Node (`tests/offline/*.test.mjs`)
- Playwright suites against the dev server (`playwright.offline.config.ts`,
  `playwright.party.config.ts`)
- cross-repository provider tests (`playwright.provider.config.ts`)
- systemd proofs that run as root on disposable CI machines (`experiments/native-game/`,
  `experiments/service-trust/`)

`npm test` targets a live appliance. [TESTING](TESTING.md) explains each suite and what it does
and does not prove. A test at phone size in a desktop browser is not evidence about a real phone.

## Where to go next

- [ADRs](adr/): the decisions and their reasons
- [Design documents](design/README.md): detailed contracts and mechanisms
- [SYSTEM](SYSTEM.md): what is actually deployed
- [CONTRIBUTING](../CONTRIBUTING.md): how to make and submit a change
