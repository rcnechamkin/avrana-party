# Claude Code Cloud guide

Use current GitHub main for source and the current [Linear](https://linear.app/avranakern) issue
for live scope, sequencing, blockers, acceptance and ownership. Read [CLAUDE.md](CLAUDE.md),
[README](README.md), [SYSTEM](docs/SYSTEM.md), [TESTING](docs/TESTING.md) and relevant
[ADRs](docs/adr/) / [design docs](docs/design/README.md). [ROADMAP](docs/ROADMAP.md) owns strategy.

The old 2026-09-25/26 synchronization/provider sprint notes remain in Git history and dated
findings. They do not assign a first Cloud task or require a provider review that already landed.

GitHub main may be ahead of production. Party PR #34 / Games PR #13 are merged source for
ADR 0011; AVR-212 owns deployment and Tier 3 phone proof. SYSTEM retains verified deployed
revisions. Do not infer deployment from a merged PR, source fast-forward or successful CI.

Clone from GitHub, verify current main, create an issue-scoped branch, run offline checks, inspect
the diff for secrets/runtime data, then push and open a PR. Never develop in production checkouts.
Merge and deployment are separate decisions; live configuration/restarts require owner approval.

`npm ci` installs tooling. `npm run test:offline`, `npm run check:ui` and catalog freshness are
offline; commands and environment requirements are in TESTING. Cloud may use
`PW_CHROMIUM_EXECUTABLE=/opt/pw-browsers/chromium` if its installed Chromium is the supported
binary. Real nginx/logrotate checks require those Linux binaries; CI requires them. Games has
independent CI; combined tests require explicit local checkouts of both private repos.

`npm test`, soak and fault target the appliance on Party Wi-Fi. Cloud cannot prove real iPhone
Safari/Android behavior, AP capacity, hardware encoding, emulator performance, power or truly
offline phone recovery. Use bounded owner-approved Pi/phone validation and record dated evidence;
phone-size Chromium and Linux WebKit are not physical acceptance. No handoff authorizes deployment.
