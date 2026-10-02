# Repository integrity

`npm run check:repo` runs the standard-library Python checker, then the existing UI and catalog
freshness checks. It requires Git, Node, installed lockfile dependencies and Python; it runs
offline, with no Pi, external service or private Games checkout. For structural checks only:

```sh
python3 tools/repo-check.py
python3 -m unittest discover -s tests/unit -p test_repo_check.py
```

The manifest uses JSON to avoid a YAML runtime dependency. It records document authority,
generated-file provenance and an intentional root-entry allowlist. Every tracked or nonignored
new Markdown file must be classified. Untracked ignored caches/data are not traversed.

Checks cover:

- strict JSON (including duplicate keys), required fields, known classes/statuses/authorities;
- safe existing document/source/output paths and complete Markdown coverage;
- unique authority domains; AGENTS, SYSTEM, TESTING, ROADMAP and design index retain their roles;
- Linear is the sole live-work authority; no document may declare that scope;
- archived/research/evidence paths cannot acquire current contract authority;
- valid ISO dates for findings and evidence, explicit status markers for ADRs/design proposals;
- inline/reference Markdown links, images and HTML local links, including Markdown heading
  fragments; code fences and inline-code examples are excluded;
- no conflict markers in small first-party text files; no additional root handoff/log files;
- brief agent compatibility layers link to AGENTS and declare no independent authority;
- generated mappings/check identifiers, GitHub generated/vendor annotations and nginx byte equality;
- retained branch records are noncanonical and forbid wholesale merges.

The checker is deliberately a bounded Markdown link checker, not a full CommonMark renderer:
use ordinary inline/reference links, angle brackets for spaces, and standard heading anchors.
Bare code-span paths and external URLs are not link-checked (branch-only paths and historical
commands often do not exist on main). External URLs are never fetched. It prints paths/line
numbers and rule names, not source lines or secret values. It is not a credential scanner or
proof that narrative claims are true. Human review still checks semantics, evidence and secrets.

Historical quotations remain valid: there is no blanket ban on words such as "next" or "live".
Authority is enforced structurally through class, scope, status and namespace. Do not work around
a failure by making a proposed document canonical. Update the map and evidence together.

Branch deletion is a separate online operation, never part of this checker or CI: refetch main,
check protection/rulesets and active PR heads, verify zero commits ahead and ancestor containment,
exclude retained research/history branches, and compare the ref SHA again before deletion.
Keep dated proof in findings; do not delete divergent refs or local worktrees merely for tidiness.
