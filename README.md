# Avrana Party

Avrana Party is a multiplayer game system for people in the same room. A Raspberry Pi 4
hosts the games and its own Wi-Fi network. Players connect their phones and open a browser;
each phone becomes a screen, a controller, or both. Core play needs no internet connection,
account, or app installation. A TV is optional.

On a configured appliance, connect to **Avrana Party** Wi-Fi and open
`https://party.avrana.net/party/`. That address works on the Party network; it is not a public
website.

## What's in the project

- **Party Home:** a game catalog, player profiles, chat, favorites, and recently played games.
- **Party Core:** keeps track of the players, the host, and the current game. In current source,
  the host moves the group through game selection, Play or Watch setup, play, and results.
- **Browser games:** maintained LAN Games titles and BLUFF, a bluffing card game. Their source
  lives in the separate, currently private [Games repository](https://github.com/rcnechamkin/avrana-party-games).
- **Arcade streaming:** Gauntlet II runs on the Pi and streams to phones over WebRTC, with two
  controller slots.

PS1 support and per-phone views of a shared screen remain experiments. Some features on `main`
have not been verified on the deployed appliance or on real phones. [SYSTEM](docs/SYSTEM.md)
records verified deployments; [TESTING](docs/TESTING.md) explains what each kind of test proves.

## Run the UI locally

You can work on the interface and run offline tests without a Pi. Install **Node.js 22**,
**npm**, and **Python 3.12 or newer**, then:

```sh
git clone https://github.com/rcnechamkin/avrana-party.git
cd avrana-party
npm ci
npm run dev
```

Open **http://127.0.0.1:8180/party/**. Stop the server with Ctrl+C.

The development server serves the Party interface with a stub games hub and simulated arcade
status. It does not start Party Core, playable browser games, or an emulator. Testing complete
browser-game sessions requires a Games checkout and the
[cross-repository test harness](docs/TESTING.md#lan-games-provider-cross-repository-tests).

`npm run dev` calls `python3`. On Windows, if Python is available as `python` instead, use:

```powershell
python -m avrana.web.devserver --port 8180
```

Setting up a Pi is a separate process. See the [deployment files and tools](deploy/README.md)
and [network runbook](docs/runbooks/network.md). The local preview does not configure an appliance.

## Run the checks

With the dependencies above installed and `python3` available:

```sh
npm run check:repo
npx playwright install chromium
npm run test:offline
```

These check repository structure, documentation links, generated files, Python and JavaScript
logic, and browser behavior against a local test server. Linux CI also runs nginx and logrotate
checks. See [CONTRIBUTING](CONTRIBUTING.md#set-up-and-test-locally) for Windows commands and
[TESTING](docs/TESTING.md) for individual suites and setup details.

**`npm test` targets the live Pi.** Use the offline commands above for local development.
Browser tests at phone-sized viewports do not replace testing on real iPhones or Android phones.

## Contribute

Start with [CONTRIBUTING](CONTRIBUTING.md). Check [Linear](https://linear.app/avranakern) for active
work and [open pull requests](https://github.com/rcnechamkin/avrana-party/pulls) for changes already
underway. If you cannot access Linear, ask the maintainer to confirm the scope before starting.
The [roadmap](docs/ROADMAP.md) describes longer-term plans.

| Area | Where to look |
|---|---|
| Party interface | `web/party/`; CSS source in `web/src/` |
| Party service and game integration | `avrana/`, `contracts/` |
| Arcade streaming | `arcade/` |
| Tests | `tests/` |
| Deployment and maintenance | `deploy/`, `ops/`, `telemetry/` |
| Architecture, procedures, and findings | [Documentation map](docs/README.md) |

Before editing built CSS, icons, avatars, artwork, or catalogs, read the
[generated-file guide](docs/GENERATED.md). Change the source and regenerate the output.
For bug reports, include the device/browser, steps to reproduce, expected and actual results,
and whether you used the local preview or an appliance. Leave out credentials and personal data.

## Project records

GitHub `main` holds current source and tests. Linear holds current assignments. SYSTEM records
verified deployed state. Accepted [architecture decisions](docs/adr/) and
[design documents](docs/design/README.md) describe the contracts; proposals and historical notes
keep their own status labels. A merged change is not evidence of deployment.

[AGENTS.md](AGENTS.md) contains the shared rules for contributors and coding agents, including
production access and handling secrets. Old handoffs are preserved in the
[archive](docs/archive/README.md) and do not assign current work.

## License

The package metadata currently says ISC, but the repository has no LICENSE file. The owner
has not resolved that discrepancy. See [CONTRIBUTING](CONTRIBUTING.md#licensing-and-sensitive-reports)
for the current notice; existing third-party notices remain in place.
