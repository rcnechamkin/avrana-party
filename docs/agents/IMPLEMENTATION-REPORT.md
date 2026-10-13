# Concise implementation handoff

Write this **once** in the PR description. In chat, link the PR and state the
one next action; do not paste the PR body or test transcript again.

```markdown
**Change:** one sentence about observable behavior.
**Proof:** exact relevant commands and pass/fail; note anything not run.
**Risks:** blockers, affected contract/security boundary, and missing phone/Pi proof (or "none known").
**Next:** what the owner should review, merge, or physically test.
```

For paired Party/Games changes, link both PRs and state merge order in "Next".
Do not invent test evidence, declare physical tests complete from simulation,
or mark Linear Done before acceptance. High-risk changes need independent
review and the relevant integration/security suite; the concise handoff
does not relax those requirements.

Do not write a second detailed final sprint report, generate retrospective
documents, or open follow-up tickets without an owner request.
