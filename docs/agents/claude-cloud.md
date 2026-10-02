# Claude Code Cloud environment

Read [AGENTS](../../AGENTS.md) first; project truth and safety rules live there.
Use [TESTING](../TESTING.md) for current commands and [CONTRIBUTING](../../CONTRIBUTING.md)
for the contribution workflow. This page only describes environment differences.

- Install locked development dependencies with `npm ci` in the selected checkout.
- Install Chromium with Playwright when available. `PW_CHROMIUM_EXECUTABLE` may select an
  existing compatible binary; verify it exists rather than assuming a Cloud image path.
- Linux nginx/logrotate gates require those binaries; CI installs and requires them. Cloud
  cannot reproduce Pi media hardware or reach the Party Wi-Fi. Use only localhost test configs.
- Cross-repository tests require explicit local Party and Games checkouts; no production donor.
- Historical Cloud handoffs are preserved in Git history. They assign no first/next Cloud task.
