# Graphify: derived architectural context

Graphify is a navigation aid, never a source of truth. Linear owns live work/status/priorities,
ownership, blockers and acceptance. Canonical GitHub docs and ADRs own decisions and intended
architecture. Code/tests own implementation. Read each ADR's actual status and amendments.
See [AGENTS](../AGENTS.md), [documentation map](README.md) and [generated-file guide](GENERATED.md).

## Implementation plan and scope

- Index tracked and nonignored first-party code/tests/configuration using local AST extraction.
  Include maintained Markdown in a separate interactive semantic corpus. The Party manifest
  excludes evidence, archives and research; proposed/mixed design keeps its original status.
- Games uses the same toolkit, pinned to a Party commit, and separately refreshes current Party
  main documentation under `party-docs/`. No canonical source is rewritten or copied back from Graphify.
- Query Linear's explicitly scoped AvranaKern projects, including The Team II adaptation,
  read-only and with complete pagination. The separate Avrana Game project is excluded.
  Both repos use the same project scope because Party/provider work crosses repository boundaries.
- Regenerate on local commits/checkouts/merges, in watch mode after input changes or snapshot
  expiry, and in CI after main pushes, every six hours and manual dispatch.
- Commit configuration, tooling, instructions, and optionally reviewed portable semantic graphs
  plus their generated receipts. Everything containing Linear state stays ignored/local.
- Detect stale context with SHA256 input/output hashes, toolkit/config/version metadata, Graphify
  extraction coverage, and a six-hour Linear timestamp. Missing/failed refreshes never claim freshness.

## Verified upstream behavior and deliberate deviations

The official package is `graphifyy==0.9.74`; the command is `graphify`.
[Upstream installation and CLI](https://github.com/Graphify-Labs/graphify/tree/v8)
and [team version-control recommendations](https://github.com/Graphify-Labs/graphify#team-setup)
were verified on 2026-10-02. Upstream supports `.graphifyignore`, local AST `extract --code-only`,
interactive semantic extraction, and optional sharing of portable graph products.

Upstream Git hooks update ASTs after commit/checkout, but do not maintain Linear or guarantee
semantic freshness after documentation edits. Avrana uses one small wrapper for those boundaries,
post-merge support and validation. `extract` builds the graph; the official
`cluster-only --no-label --no-viz` step generates its report without semantic model calls. Do not additionally install upstream Git hooks over these hooks.
Codex uses AGENTS instructions: upstream's Codex PreToolUse hook is intentionally a no-op.
Claude's project PreToolUse hook gives a nonblocking freshness reminder before searches.

**No model API credential or paid unattended semantic extraction is required or used.** CI builds
ASTs with `--code-only` and reports semantic documentation as stale when appropriate. Interactive
Graphify sessions use the existing host agent; neither the wrapper nor CI selects a model backend.
Linear state is generated as agent-readable JSON/Markdown, rather than pretending AST extraction
understands issue text semantically. Consult this snapshot alongside graphs, and live Linear for decisions.

## Local setup and automatic refresh

Install the pinned tool in an isolated environment and run these commands using that environment's
Python, so `python -m graphify` resolves the same installation:

```sh
python -m venv .venv
# Activate .venv using your shell, then:
python -m pip install graphifyy==0.9.74
python tools/graphify_context.py check-config
python tools/graphify_context.py refresh --architecture
python tools/graphify_context.py install-hooks
python tools/graphify_context.py watch --architecture
```

`install-hooks` is opt-in per clone: it preserves existing shell hooks and the Games pre-push
privacy guard. Hooks contain local interpreter paths and remain untracked. Worktree hooks resolve
the current checkout; branches predating this integration are skipped. Reinstall after changing
interpreters; the installer replaces only its marked block. Hook errors are visible but do not block commits.
Hooks refresh architecture without credentials; if `LINEAR_API_KEY` is available they refresh the
private Linear context too. Watch mode checks every 30 seconds; stop it with Ctrl+C.

For complete local derived work context, set `LINEAR_API_KEY` privately in the environment:

```sh
python tools/graphify_context.py refresh
python tools/graphify_context.py status
python tools/graphify_context.py query "Which modules own provider launch?"
```

Without a Linear credential, use `ensure --architecture`, `status --architecture` and
`query "question" --architecture`. This makes no claim about Linear freshness. Use the connected
Linear app for current work decisions. After pulls or any unsaved/uncommitted edits, `ensure`
checks hashes and regenerates when needed; a targeted read/test does not need a Graphify detour.
For broad searches, query first where useful, then read original source paths. Inferred edges are
hypotheses, not verified architecture. If semantic context is stale, read canonical docs directly.

## Interactive semantic documentation refresh

```sh
python tools/graphify_context.py prepare-semantic
```

Install the upstream assistant skill once with `graphify install --platform windows` (Claude Code
on Windows), `--platform claude` on other Claude hosts, or `--platform codex` for Codex. Prefer a
user-level skill install; review any upstream changes to project instructions rather than letting
them replace Avrana's authority hierarchy. In the interactive session, invoke `/graphify` (Claude)
or `$graphify` (Codex) on `.graphify-context/semantic-input`. Instruct it to use host-agent semantic
extraction and write that corpus's `graphify-out`; **do not invoke a headless API backend**.
The corpus contains maintained docs and the authority warning, never Linear state or runtime data.

```sh
python tools/graphify_context.py accept-semantic
python tools/graphify_context.py check-semantic --require-semantic
git diff -- context/graphify
```

Acceptance validates the request/input hashes, per-document semantic coverage, and portable source
paths. It generates `context/graphify/semantic-graph.json` and `semantic-receipt.json` with warnings,
version and hashes. Review those products for accuracy and sensitive content before committing.
Never hand-edit either file or a receipt to bypass stale warnings. Until a real interactive session
has completed, these files are absent and CI explicitly flags semantic context as stale.
CI warnings do not prevent unrelated code work; use `check-semantic --require-semantic` for a strict gate.

For Graphify to reason semantically over private Linear state as well, synchronize with `refresh`,
then run `prepare-semantic --with-linear`. Invoke interactive Graphify on
`.graphify-context/semantic-work-input`, then `accept-semantic --with-linear`. This publishes only
to ignored `.graphify-context/private-semantic/`; **never commit or upload it**. The fingerprint
includes relevant Linear content, and its usability also requires an unexpired snapshot.
`check-semantic --with-linear --require-semantic` checks this private layer. Full `query` uses it
when current; otherwise it flags stale semantics and the generated Linear snapshot remains
agent-readable alongside the architecture graph. Public semantics never include Linear state.

## Generated state and confidentiality

| Output | Policy |
|---|---|
| `graphify-public/` | Ignored code graph/report/manifest/freshness metadata; CI uploads only these four portable products |
| `graphify-out/` | Ignored local AST/work-context freshness metadata; never uploaded |
| `.graphify-context/linear.json`, `LINEAR-CONTEXT.md` | Generated private read-only snapshot; never edit, commit or upload |
| `.graphify-context/` | Ignored corpora, caches, locks, pinned toolkit checkout and interactive staging |
| `context/graphify/semantic-graph.json`, `semantic-receipt.json` | Optional reviewed shared semantic products; regenerate together |

Input copying uses Git's tracked/nonignored inventory and explicit exclusions. No ROMs, media,
runtime state, secrets or dependency trees are included. The Linear export omits descriptions,
comments, attachments and emails; even its minimal title/status/owner metadata is private.
Linear keys are stripped before the Graphify subprocess runs; model credential variables are
also removed. Failures do not print API responses or model/source text into CI logs.

## CI and final verification

The existing offline/test workflows run configuration and fixture checks with no credentials.
`Graphify derived context` calls the single reusable Party refresh workflow; Games pins that workflow
and toolkit to the same immutable commit. Canonical Party documentation uses a separate current-main
checkout, refreshed by CI every run and by local ensure/hooks/watch at most every six hours.
Thus documentation freshness does not depend on updating the executable toolkit pin. Changes to
shared tooling require deliberately updating both Games pins. Public architecture artifacts contain no Linear state or machine path sidecars.
The read-only job has `contents: read` and cannot commit, merge, deploy or mutate Linear.

Add **only `LINEAR_API_KEY`** to GitHub Actions secrets in each repo (or a repository-selected
organization secret). Create a read-only Linear key limited to AvranaKern and the configured
projects where Linear's access controls permit. The script sends queries only, not mutations;
credential privileges must be scoped by the owner. No Anthropic/OpenAI/Gemini secret is needed.
See [Linear authentication](https://linear.app/developers/graphql#authentication).

Scheduled/main refreshes skip Linear with a visible warning and job summary when the secret is
missing. Manual dispatch and integration-branch push verification require it and fail clearly. API errors, incomplete pagination/coverage,
concurrent changes or expired snapshots fail without publishing a fresh context claim.
Linear changes are detected within the six-hour polling interval; no webhook receiver is introduced.
Semantic freshness and Linear freshness are separate, explicit checks.

For end-to-end verification before merging, add the secret first, then push the integration
branches. Both workflows explicitly run on this branch and require successful Linear sync.
Party must be pushed first so Games' pinned toolkit/workflow commit is fetchable:

```sh
git -C ../avrana-party.graphify push origin chore/graphify-derived-context
git -C ../avrana-party-games.graphify push origin chore/graphify-derived-context
gh run list --repo rcnechamkin/avrana-party --workflow graphify.yml
gh run list --repo rcnechamkin/avrana-party-games --workflow graphify.yml
# Use the returned run ID in each repository:
gh run watch RUN_ID --repo OWNER/REPOSITORY --exit-status
```

If a branch run already failed because the secret was missing, add it and use
`gh run rerun RUN_ID --repo OWNER/REPOSITORY`, then watch the rerun. This needs no merge or empty
commit. After the workflows eventually exist on main, they can also be manually dispatched with
`gh workflow run graphify.yml --repo OWNER/REPOSITORY --ref BRANCH`. GitHub requires that
default-branch prerequisite for dispatch; the initial push trigger avoids it. You can also run
local `refresh` and `status` with the key. Verify public AST artifacts, successful private Linear
sync, and the explicit semantic warning/current check. No production acceptance is implied.

Offline tests: `python -m unittest discover -s tests/context -v`. They cover pagination, partial
GraphQL errors, rate limiting, missing credentials, stale hashes/TTL, failed extraction, concurrent
edits, semantic acceptance, input exclusions and hook preservation. Live Linear and interactive
semantic extraction remain separate final checks; synthetic fixtures never claim real synchronization.
