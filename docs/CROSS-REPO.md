# Cross-repository work: Party and Games

Avrana Party is two repositories with one boundary. [`avrana-party`](https://github.com/rcnechamkin/avrana-party)
owns the platform (Party Core, shell, contracts, arcade, operations);
[`avrana-party-games`](https://github.com/rcnechamkin/avrana-party-games) owns game servers and the
provider integration. The boundary is declared in both and machine-checked:
[PARTY-GAMES-CONTRACT](design/PARTY-GAMES-CONTRACT.md).

## Branch naming

`<type>/avr-<N>-<short-description>`, lowercase, in both repositories:
`fix/avr-130-arcade-seat-reconnect`, `feat/avr-129-party-pregame`, `chore/avr-230-agent-workflow`,
`docs/avr-213-...`, `experiment/...`. The AVR number is what pairs branches across repositories;
Linear's suggested `cnechamkin/avr-N-...` names also pair, since only the `avr-N` token is matched.
Branches without an issue use a descriptive scope and pair with `main`.

## What CI does with the other repository

| Trigger | Lane | Other repository at |
|---|---|---|
| Party PR / push to `main` | `Cross-repo contract` (`.github/workflows/cross-repo.yml`) | the Games branch whose name carries the same `avr-N`, else `main` |
| Games PR / push to `main` | `cross-repo` job in `.github/workflows/test.yml` | the Party branch whose name carries the same `avr-N`, else `main` |

Each lane runs `tools/contract_check.py` (both declarations against both code bases and each
other), Games' `tests/test_party_session_cross_repo.py` (the real Party service driving the real
games server; it fails rather than skips in CI) and, on the Party side, the browser provider suite.
A failure names the component that drifted.

Consequences:

- a Party change that breaks the vendored protocol, a route, the launch advertisement or the
  catalog snapshot fails on the Party PR against Games `main`, before merge;
- a Games change that needs a Party change passes only once the paired Party branch exists with
  the same `avr-N`; both PRs link each other and merge Party first (Games CI then passes against
  `main`), unless the change is Games-only backwards-compatible;
- the other way round: when Party's own checks need the Games change (a Party test that drives
  the real games server, or a checker that now requires something of the Games declaration) and
  the Games change passes against Party `main`, Games merges first. Both PR bodies say so;
- after both merge, `main` against `main` is checked again on the push.

## Paired PRs

1. Open both branches with the same `avr-N`. CI pairs them automatically.
2. Each PR body links the other and says which merges first.
3. The deployment names both SHAs explicitly ([deploy runbook](runbooks/deploy.md)); the
   [deployment manifest](design/DEPLOYMENT-MANIFEST.md) and `/party/api/status` then report both.

## Local

```sh
python3 tools/contract_check.py --games ../avrana-party-games
AVRANA_PARTY_REPO=../avrana-party python -m pytest tests/test_party_session_cross_repo.py   # in Games
AVRANA_GAMES_REPO=../avrana-party-games npx playwright test -c playwright.provider.config.ts  # in Party
```

## Private repositories and the read token (AVR-428)

Both repositories are private, so a workflow in one cannot read the other anonymously, and the
job's own `github.token` reaches only its own repository. Same-repository git operations (the
base-commit fetch in `offline-checks.yml`) use `github.token`, passed to that one step and never
written to `.git/config`. Every read of the other repository (branch listing with `git ls-remote`,
and `actions/checkout`) uses one secret, `AVRANA_CROSS_REPO_READ_TOKEN`. If it is missing the job
fails first, with an error naming it; a failure to list the other repository's branches still fails
the job (no fallback to `main`). Secrets are not given to workflows run from forks; every PR here
is from a branch of the same repository.

Owner setup (once, then on rotation):

1. GitHub, Settings, Developer settings, Personal access tokens, **Fine-grained tokens**, Generate.
   Resource owner `rcnechamkin`; Repository access: **Only select repositories**, both
   `avrana-party` and `avrana-party-games`; Repository permissions: **Contents: Read-only**,
   **Metadata: Read-only**; nothing else. Choose an expiry (90 days or less is sensible).
2. Store it in both repositories, reading the value from the prompt (never paste it in chat or a file):

   ```sh
   gh secret set AVRANA_CROSS_REPO_READ_TOKEN --repo rcnechamkin/avrana-party
   gh secret set AVRANA_CROSS_REPO_READ_TOKEN --repo rcnechamkin/avrana-party-games
   ```

3. Rotation: when the token nears its expiry, generate a new one with the same scope and rerun both
   commands. An expired token shows as the same checkout or `ls-remote` authentication failure.
