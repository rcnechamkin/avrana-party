# Claude Code Cloud as a reproducible workspace; first offline CI lane

Date: 2026-09-26. Starting `main`: `512b63440916b390355ced9b7e44848172d4642d` (clean tree).
Scope: workspace validation only. No dependency, lockfile, application or deployment change; no Pi,
phone, Wi-Fi, streaming, emulator or power work.

Labels: **TESTED** = run in the Cloud container · **EXPECTED** = not yet observed in GitHub Actions.

## TESTED (Cloud container, Linux x86-64)

- Toolchain: Node **v22.22.2**, npm **10.9.7**, Python 3.11.15 (not needed by the lane).
- `npm ci` from the committed lockfile (lockfileVersion 3; `@playwright/test` 1.63.0,
  `@types/node` 26.6.2): 5 packages, 0 vulnerabilities; the lockfile and tree stayed unchanged.
- `npx playwright test tests/soak-metrics.spec.ts`: **10 pass** (5 tests × `chromium` and
  `iphone-safari` projects), ~2 s. Also passes with `CI=1` and with `PLAYWRIGHT_BROWSERS_PATH`
  pointed at an empty directory: the spec launches no browser.
- `cmp avrana-party.nginx arcade/nginx-site`: identical.
- Reproducibility: after deleting `node_modules/`, `test-results/`, `playwright-report/` and the
  npm cache, and again in a fresh `git clone` of the branch, the same three commands passed.
- Live-appliance specs, one bounded run of `smoke`, `captive` and `stats` (`--project=chromium
  --retries=0`): 6 fail, all on `getaddrinfo ENOTFOUND party.avrana`; the one `page` test also
  reports that Playwright 1.63's `chromium_headless_shell-1243` is not installed (the image ships
  revision 1194). Environment, not product: no request reached application code.

## Reproducibility notes

- The repo pins no Node version (`.nvmrc`, `engines`); the Playwright packages require Node ≥ 20.
  The workflow pins `22.22.2` explicitly. `@types/node` 26 is types-only; nothing type-checks
  (Playwright transpiles TypeScript without `tsc`).
- `playwright.config.ts` reads `CI`: GitHub sets it, so CI runs with 2 retries and `forbidOnly`.
- Browser suites need `npx playwright install` for 1.63 in Cloud; the lane does not.

## EXPECTED

The "Offline checks" workflow runs the same three commands on `ubuntu-24.04` with
`actions/setup-node@v7` (Node 22.22.2, npm cache keyed on `package-lock.json`) and is expected to
pass from a clean checkout. Confirm on the first pull-request run.
