# Avrana Party

**Portable, local-first multiplayer. Phones are the screens and the controllers. The Pi is the console.**

Avrana Party turns a Raspberry Pi into a self-contained multiplayer game system. Players join its Wi-Fi, open a browser on their phones, and start playing.

No app install. No accounts. No internet connection required for core play. A TV is optional.

On a configured appliance, connect to **Avrana Party** Wi-Fi and open:

`https://party.avrana.net/party/`

That address works locally on the Party network. It is not a public website.

**The game may change; the party does not.**

Avrana Party is still in active development. Some parts are already working on the physical appliance, some are further ahead in source, and others are still experiments. [SYSTEM](docs/SYSTEM.md) tracks what has actually been deployed and verified. [TESTING](docs/TESTING.md) explains the difference between automated tests, local simulation, and real-device evidence.

## What Avrana Party does

### Party Home

Party Home is the main interface players see on their phones. It handles the game catalog, player profiles, Party Chat, favorites, recently played games, and navigation through the Party.

### Party Core

Party Core keeps track of the Party itself: who is present, who is hosting, which game is active, and where everyone should be.

The host controls the shared flow through game selection, Play or Watch setup, gameplay, and results.

### Browser games

Avrana Party supports games that run directly in the browser.

BLUFF is currently the main native Avrana testbed, alongside maintained LAN Games titles. Game source lives in the separate, currently private [Games repository](https://github.com/rcnechamkin/avrana-party-games).

### Arcade streaming

The Pi can also run games itself and stream them to phones.

Gauntlet II is the current working example: the game runs on the appliance, video is streamed over WebRTC, and phones act as controllers.

PS1 support and per-phone views into shared-screen games are still experimental.

## How it fits together

A typical Party looks something like this:

1. Turn on the Avrana Party appliance.
2. Players join its local Wi-Fi.
3. Everyone opens Party Home in a browser.
4. The host picks a game.
5. Players choose to play or watch.
6. Party Core moves everyone into the right game or interface.
7. When the game ends, everyone returns to the Party.

The goal is for that flow to stay consistent regardless of what kind of game is running underneath it.

## Run the UI locally

You do not need a Raspberry Pi to work on the Party interface or run the offline test suite.

Install:

- **Node.js 22**
- **npm**
- **Python 3.12 or newer**

Then:

```sh
git clone https://github.com/rcnechamkin/avrana-party.git
cd avrana-party
npm ci
npm run dev
```

Open:

**http://127.0.0.1:8180/party/**

Stop the development server with Ctrl+C.

The local server provides the Party interface along with a stub games hub and simulated arcade status. It does not start Party Core, playable browser games, or an emulator.

Testing complete browser-game sessions requires a Games checkout and the [cross-repository test harness](docs/TESTING.md#lan-games-provider-cross-repository-tests).

### Windows

`npm run dev` currently calls `python3`.

If Python is installed as `python` instead:

```powershell
python -m avrana.web.devserver --port 8180
```

Setting up a physical Pi is a separate process. See the [deployment tools](deploy/README.md) and [network runbook](docs/runbooks/network.md).

## Run the checks

For the main offline development checks:

```sh
npm run check:repo
npx playwright install chromium
npm run test:offline
```

These cover repository structure, documentation links, generated files, Python and JavaScript logic, and browser behavior against a local test server.

Linux CI also runs nginx and logrotate checks.

See [CONTRIBUTING](CONTRIBUTING.md#set-up-and-test-locally) for platform-specific setup and [TESTING](docs/TESTING.md) for the full test layout.

> **Important:** `npm test` targets the live Avrana Party appliance. Use the offline commands above for normal local development.

Browser testing at phone-sized viewports is useful, but it is not considered proof that something works correctly on a real iPhone or Android device.

## Contributing

If you want to work on Avrana Party, start with:

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [AGENTS.md](AGENTS.md)
- [Documentation map](docs/README.md)

Active work, sequencing, blockers, and acceptance criteria live in [Linear](https://linear.app/avranakern). Check that and the [open pull requests](https://github.com/rcnechamkin/avrana-party/pulls) before starting anything substantial.

The [roadmap](docs/ROADMAP.md) covers longer-term direction rather than the current task queue.

| Area | Start here |
|---|---|
| Party interface | `web/party/`, `web/src/` |
| Party Core and game integration | `avrana/`, `contracts/` |
| Arcade streaming | `arcade/` |
| Tests | `tests/` |
| Deployment and maintenance | `deploy/`, `ops/`, `telemetry/` |
| Architecture and design | [docs/](docs/README.md) |

Some assets in the repository are generated rather than edited directly. Before changing built CSS, icons, avatars, artwork, or catalogs, read [GENERATED.md](docs/GENERATED.md).

For bug reports, include:

- device and browser
- steps to reproduce
- expected behavior
- actual behavior
- whether you were using the local development server or a physical Avrana Party appliance

Do not include credentials, secrets, or personal data.

## Sources of truth

There are a few different records in the project, and they deliberately answer different questions.

| Question | Source |
|---|---|
| What does the current code do? | GitHub `main` |
| What is being worked on next? | [Linear](https://linear.app/avranakern) |
| What is actually deployed? | [SYSTEM](docs/SYSTEM.md) |
| What architectural decisions have been accepted? | [ADRs](docs/adr/) |
| How should the system behave? | [Design docs](docs/design/README.md) |
| Where is the project heading? | [ROADMAP](docs/ROADMAP.md) |
| What does each test actually prove? | [TESTING](docs/TESTING.md) |
| What rules should contributors and coding agents follow? | [AGENTS.md](AGENTS.md) |

A merged PR means the source changed. It does not automatically mean that change has been deployed or tested on real hardware.

Historical findings and old handoffs are preserved in the [archive](docs/archive/README.md), but they do not define current work.

## License

The package metadata currently identifies the project as ISC, but the repository does not yet contain a LICENSE file.

Until that discrepancy is resolved, do not assume licensing terms that are not explicitly present in the repository.

See [CONTRIBUTING](CONTRIBUTING.md#licensing-and-sensitive-reports) for the current notice. Existing third-party notices remain in place.
