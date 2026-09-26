# Codex handoff — LAN Games Providerization & Direct-Launch

Updated: 2026-09-26. This file is the durable continuation record.
Status: baseline verified; original specification received; cross-repository audit underway.

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
  Its only configured origin is ssh://party/home/cody/avrana-lab/avrana-party-games,
  not a GitHub remote. The canonical games GitHub target must be established
  before coordinated PR creation; do not push development work to the Pi origin.
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

Before this handoff was created, the feature branch was clean at starting main.
This handoff is saved as a standalone documentation checkpoint commit.
No uncommitted feature/code/config edits; run git status to verify on recovery.
No games repository, experimental branch/worktree or Pi files were changed.

## Tests already run

Verified prior PR #5 CI results (not rerun in this continuation):
- 72 Python tests, including real nginx checks, passed on Linux.
- 54 browser-module tests passed.
- 54 simulated-browser tests passed (two Chromium phone sizes).
- 10 soak-metrics tests passed.
- Catalog consistency and nginx byte-identity checks passed.

Continuation checks: PR status/CI, clean Pi source checkout, installed release,
trusted TLS HTTP HEAD/GET, served version/catalog/origin and service active state.
No new implementation tests yet; no physical-device acceptance test attempted.

## Unresolved failures / limitations

- Games GitHub repository rcnechamkin/avrana-party-games currently returns 404;
  establish a safe private canonical remote before coordinated PR creation.
- An initial SSH curl command lost wildcard quoting through PowerShell and treated
  local filenames as hostnames, producing DNS errors. Simple hostname-specific
  --noproxy GETs subsequently succeeded with normal TLS verification.
- A local historical-text extraction initially hit Windows stdout encoding;
  retry with UTF-8 succeeded. No feature defect or production change resulted.
- Historical Windows-only Linux test failures were resolved by successful Linux CI.
- No physical phone acceptance required before development; the owner handles it.

## Exact next action

Finish the concrete cross-repository ownership audit and save it before refactoring.
Implement a versioned provider export and explicit integration bootstrap, including
WORDCLASH, declarative return links, standalone compatibility and shared storage.
Then exercise actual donor pages with local cross-repo browser tests, run existing
suites, document dependency order and hardware checklist, scan before publishing.

## Cross-repository dependency state

No code changes yet. Donor support lands first and remains standalone compatible;
platform activation must require the advertised version. Neither PR is merged or
production-deployed. Party Home remains isolated.
