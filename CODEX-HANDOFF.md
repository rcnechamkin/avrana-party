# Codex handoff — LAN Games Providerization & Direct-Launch

Updated: 2026-09-26. This file is the durable continuation record.
Status: implementation complete; coordinated review PRs open. No merge or deployment.

## Current goal

Continue the original LAN Games Providerization & Direct-Launch sprint exactly as
specified by the owner, building on completed shell assimilation. Implement, test,
document and open coordinated review PRs if both repositories change. Do not merge
or deploy. Physical iPhone/Android acceptance is owned by the user and is not a
development gate.

Acceptance: direct individual launches from /party/, one shared local profile and
library, explicit integrated vs standalone mode, no competing global chat or hub,
and reload-safe return to /party/. Deterministic authoritative metadata and
cross-repository behavioral tests must pin this boundary. No merge or deployment.

## Current branch / repositories

- Platform: C:/Users/cnech/Projects/avrana-party
- Branch: fix/lan-games-providerization
- Starting GitHub main: 459d4cd19c3a638f6d9fce54eaea675ba0f8890e
- Prior assimilation branch: fix/party-shell-assimilation, final
  85d9dd99142606e5edc71039d99a815d4b32bd63; merged by the owner as PR #5.
- Separate games repository: laptop bare backup
  C:/Users/cnech/avrana-party-games.git, main
  2cf4831064de709feeb31865c5022a3f048e49ef.
  Development checkout: C:/Users/cnech/Projects/avrana-party-games; branch
  fix/avrana-provider-integration, created from main 2cf4831.
  Private canonical origin is now https://github.com/rcnechamkin/avrana-party-games.
  Existing main 2cf4831 published only; no experiment/abandoned refs.
  Laptop bare backup remains a separate read-only remote; never push to Pi.
- Production donor /home/cody/LAN-Games is never edited.
- Party Home / Claude Cloud worktrees and experiment branches are isolated:
  do not edit, merge, deploy or use them as the sprint implementation.

## Completed work

1. Inspected current Git status, recent commits, project handoffs and audit records.
2. Verified PR #5 is MERGED at 459d4cd, final Offline checks SUCCESS:
   https://github.com/rcnechamkin/avrana-party/actions/runs/36226221830
3. Read-only SSH inspection of the Pi:
   - production checkout clean at 459d4cd19c3a638f6d9fce54eaea675ba0f8890e;
   - installed shell symlink resolves to
     /var/www/avrana-party/web/releases/20260926T082511Z-459d4cd19c3a;
   - served version.json identifies that commit, build 459d4cd19c3a,
     builtAt 2026-09-26T08:25:11Z, serviceWorker true;
   - /party/ HTTP 200, no-cache, nosniff and existing CSP;
   - trusted TLS GETs without insecure mode return the matching version and
     avrana.catalog/v0 with 33 contracts and lan-games/arcade/retroarch-ps1 entries;
   - origin endpoint reports HTTPS / TLSv1.3;
   - nginx, avranaparty-games and avranaparty-arcade are active.
   These checks used the hostname with --resolve to Pi loopback. They do not
   constitute a physical phone or Party Wi-Fi acceptance test.
4. Fetched canonical main locally and created this dedicated feature branch.
5. Created this handoff before any substantive implementation changes.

## Architectural decisions already established

- Preserve PR #3 capability/contract/provider architecture and PR #5 assimilation.
- Avrana owns global profile, chat, catalog, favorites/history and navigation.
- Existing wc-* identity/photo and lg-* library keys remain the shared backing
  stores. Party Chat wraps the existing /chat/ws channel; do not create duplicates.
- Keep individual legacy game implementations working during gradual migration.
- PS1 metadata is experimental, not installed or execution-validated by Cloud.
- Do not change networking, HTTPS/certificates, production services or live config.
- GitHub is canonical; Pi is inspection/deployment/test target, not a workspace.
- Never include private keys, tokens, photos, ROMs, runtime data or databases in Git.
- Do not touch the abandoned Classic Diplomacy branch.
- Read docs/design/LAN-GAMES-ASSIMILATION.md for the completed donor audit.
- Versioned non-secret launch context will be advertised by /api/games; old donors
  must not silently launch with duplicate chrome. Standalone access remains supported.
- Root donor worker must not register in integration mode or delete Avrana caches.
- Existing identity and lists remain the backing stores; normalize known aliases
  within those lists, never introduce a second store or destructive migration.

## Uncommitted state

Platform implementation committed as 6c6917e (catalog) and 60c7db4 (launch/library).
Documentation and cross-repository harness committed (code validation at da313c6).
Donor exporter febd546; integration ce13795; navigation context cff9958.
Final standalone unknown-ID preservation fix and this handoff are the closing
checkpoint. Run git status and git rev-parse HEAD for final review heads.
No production, networking, certificate, Party Home or experiment changes.

## Tests already run

Verified prior PR #5 CI results (not rerun in this continuation):
- 72 Python tests, including real nginx checks, passed on Linux.
- 54 browser-module tests passed.
- 54 simulated-browser tests passed (two Chromium phone sizes).
- 10 soak-metrics tests passed.
- Catalog consistency and nginx byte-identity checks passed.

Continuation checks: PR status/CI, clean Pi source checkout, installed release,
trusted TLS HTTP HEAD/GET, served version/catalog/origin and service active state.
These were baseline checks; complete sprint results follow below. No physical-device acceptance attempted.

## Unresolved failures / limitations

- Linux-only gates fail locally on Windows: symlinks, bash process/path checks,
  two arcade subprocess lifecycle tests; real nginx is skipped. Validate current
  PR with Linux CI before merging. Linux CI run 36261333271 passed these gates;
  donor run 36261284527 passed release-safety including rsync.
- History privacy scan found only old branding/filesystem paths; retained privately.
  Current tree privacy gate passed; no credential/private-key pattern matches.
- An initial SSH curl command lost wildcard quoting through PowerShell and treated
  local filenames as hostnames, producing DNS errors. Simple hostname-specific
  --noproxy GETs subsequently succeeded with normal TLS verification.
- A local historical-text extraction initially hit Windows stdout encoding;
  retry with UTF-8 succeeded. No feature defect or production change resulted.
- Historical Windows-only Linux test failures were resolved by successful Linux CI.
- No physical phone acceptance required before development; the owner handles it.

## Sprint validation

- Games full Python suite: 1200 passed (206.92 seconds).
- Games provider worker behavior: Node 3 passed; metadata drift check passed.
- Platform Node modules: 56 passed; contracts/assimilation: 27 passed.
- Cross-repository real donor + shell Chromium: 12 passed, two phone sizes;
  all 30 authoritative pages, actual shared identity hello, one chat history,
  reload return, viewport separation, standalone canonical favorites/cache scope.
- Soak metric math: 10 passed. nginx source hashes identical.
- Canonical favorite-alias regression failed against actual origin/main profile.js;
  current implementation passes. This is evidence the new test pins a real defect.
- Final offline Chromium suite: 56 passed after updating one old raw-href assertion.
- Full Windows unit run: 72 total, 61 pass, 5 failures/2 errors/4 skips, Linux-only
  paths/process/symlink/nginx gates. Existing prior PR #5 Linux CI all passed;
  sprint Linux CI also passed all 72 tests and real nginx checks (run 36261333271).
- Initial cross-repo failures were assertion mistakes: a game-specific suite-home
  class already routed correctly, hidden first standalone link, duplicate legacy
  tile matches and absent aria-pressed. Fixed assertions target actual behavior.
- Windows local socket shutdown logs can report ConnectionResetError during page
  changes; browser pageerror checks pass. No production service was touched.

## Cross-repository dependency state

Donor support first, backward-compatible standalone. Platform version-gates launches
and refuses unsupported donor behavior. Both feature PRs are open;
no merge/deploy. Each private repo runs independent CI; automatic combined checkout
would need narrowly scoped read credentials/artifact delivery, not added here.

## Review links and closing checkpoint

- Donor PR: https://github.com/rcnechamkin/avrana-party-games/pull/1
- Platform PR: https://github.com/rcnechamkin/avrana-party/pull/7
- Initial donor Linux CI SUCCESS: run 36261284527 (1200 Python, privacy/export,
  static syntax, worker behavior and release-safety).
- Initial platform Linux CI SUCCESS: run 36261333271 (72 Python including nginx,
  56 Node modules, 56 offline browser, 10 pure soak metrics, catalog/byte identity).
- Final cross-repo suite: 12/12, no browser page errors across 30 titles.
- Final unknown/future library-ID preservation regression: 2/2 at both phone sizes.
  Standalone now normalizes only titles actually present in its registry. Unknown
  canonical IDs stay byte-for-byte intact when editing a known favorite.
- This closing checkpoint reruns each PR's independent CI; PR head checks are the
  current authority. No further feature work is authorized by this handoff.

## Exact next action

Owner reviews donor PR #1 first, platform PR #7 second, and checks each current
head's CI. Neither is merged or deployed. After review, separately plan donor and
shell releases and run the exact Pi/iPhone/Android/multi-phone/legacy-worker/game/
profile/library/return checklist in the findings document. Do not touch Party Home.
Next migration should address shared transport ownership and authoritative session/
roster separately; scoped chat, PS1 runtime, TV/viewport and Companion are deferred.
