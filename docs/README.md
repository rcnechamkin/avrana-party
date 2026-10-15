# Documentation

New to the project? Read the [README](../README.md), then [ARCHITECTURE](ARCHITECTURE.md), then
[CONTRIBUTING](../CONTRIBUTING.md). The sections below go from overview to detail.

Several documents describe accepted designs that are not built or deployed yet. Each one says so
in a status line at the top. When a document and the code disagree, the code on `main` describes
what the software does, and [SYSTEM](SYSTEM.md) describes what is running on the appliance.

## Understand the system

| Document | What it answers |
|---|---|
| [ARCHITECTURE](ARCHITECTURE.md) | How the appliance, Party Core, the shell, games and the arcade fit together |
| [Architecture decision records](adr/) | What was decided and why. Each ADR states whether it is implemented and deployed |
| [Design documents](design/README.md) | Detailed contracts and mechanisms: party lifecycle, Party ↔ Games contract, browser origins, Limited Mode, native games, packages, game UX |
| [contracts/](../contracts/README.md) | The machine-readable schemas and test vectors behind those contracts |
| [UI design system](UI-DESIGN-SYSTEM.md) | How the Party shell's interface is built and themed |

## Develop and test

| Document | What it answers |
|---|---|
| [CONTRIBUTING](../CONTRIBUTING.md) | Local setup, branches, pull requests, what not to commit |
| [TESTING](TESTING.md) | Every test suite, how to run it, and what it does and does not prove |
| [GENERATED](GENERATED.md) | Which files are generated, from what, and how to rebuild them |
| [CROSS-REPO](CROSS-REPO.md) | Changes that span this repository and the Games repository |
| [WORKFLOW](WORKFLOW.md) | What CI runs on a pull request and what runs only on request |
| [Repository checks](REPOSITORY-GOVERNANCE.md) | What `npm run check:repo` enforces, including the document manifest |
| [Agent tooling](agents/) | Setup notes for coding-agent environments; the rules are in [AGENTS](../AGENTS.md) |

## Operate the appliance

| Document | What it answers |
|---|---|
| [SYSTEM](SYSTEM.md) | What is deployed on the Pi, on which machines, services and ports |
| [Deploy](runbooks/deploy.md) | Releasing a Party/Games pair with `ops/deploy.sh`, and rolling back |
| [Network](runbooks/network.md), [Party HTTPS](runbooks/party-https.md) | The Wi-Fi access point, local DNS and the certificate |
| [Service recovery](runbooks/service-recovery.md), [logs and retention](runbooks/logs-and-retention.md) | Diagnosing and recovering services |
| [Install a game](runbooks/install-game.md), [provision a game](runbooks/provision-game.md), [prepare native games](runbooks/prepare-native-games.md) | Native-game and package installation (not yet used on the appliance) |
| [Rebuild](runbooks/rebuild.md) | Building an appliance from a clean device (procedure, not yet run on hardware) |
| [All runbooks](runbooks/) | Including physical acceptance checklists for real phones and the Pi |

Runbooks describe procedures. Running one on the appliance is the owner's decision.

## Direction

| Document | What it answers |
|---|---|
| [ROADMAP](ROADMAP.md) | Product direction and milestones. Current tasks are tracked in [Linear](https://linear.app/avranakern) |
| [Game platform](GAME-PLATFORM-ARCHITECTURE.md), [offline trust and recovery](OFFLINE-TRUST-AND-RECOVERY.md), [personal viewports and emulation](PERSONAL-VIEWPORT-AND-EMULATION.md), [experience](AVRANA-EXPERIENCE.md) | Longer-term design direction; not a description of what is built |
| [Research](research/) | Background studies and candidate technologies; no decisions |

## History

| Location | What it holds |
|---|---|
| [Findings](findings/) | Dated measurements, audits and deployment observations. Never edited after the fact |
| [Archive](archive/) | Superseded material kept as history; it gives no current instructions |
| [Branch inventory](branches.json) | Long-lived research branches that are kept but never merged wholesale |

## Adding or moving a document

Every Markdown file has an entry in [manifest.json](manifest.json) that records its class and
status. Add one with each new document, keep links relative, and run `npm run check:repo`.
[Repository checks](REPOSITORY-GOVERNANCE.md) describes the rules.
