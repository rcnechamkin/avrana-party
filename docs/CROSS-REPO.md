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

## Private repositories and the read keys (AVR-428)

Both repositories are private. The job's own `github.token` reaches only the repository the workflow
runs in, so every read of the *other* repository uses a **read-only deploy key** over SSH, one per
direction, each valid for exactly one repository, bound to no user and without an expiry:

| Secret | Stored in | Private half of a deploy key that is added (read-only) to |
|---|---|---|
| `AVRANA_GAMES_READ_KEY` | `avrana-party` | `avrana-party-games` |
| `AVRANA_PARTY_READ_KEY` | `avrana-party-games` | `avrana-party` |

How the jobs use them:

- Every job that reads the other repository starts with a step named *Access check - read the ...
  repository*, which runs `.github/ci/peer-access.sh` (the same file in both repositories). It
  lists the other repository's branches over SSH with the key, which proves access, and picks the
  paired branch. A failure there is printed as `ACCESS PROBLEM (credentials, not a test failure)`,
  names the secret and this section, and says which case it is: secret empty or unset, secret from a
  fork run (GitHub withholds secrets from forks), key rejected or not a deploy key on that
  repository, secret not a usable key, or the pinned GitHub host keys out of date. Those steps come
  before any test step, so a red job whose first red step is the access check is never a test result.
- `actions/checkout` then reads the same repository with `ssh-key:`, `persist-credentials: false`
  (the key is removed from the runner when the step ends). The script keeps the key in a private
  temporary directory it deletes on exit. GitHub's SSH host keys are pinned in the script
  (`https://api.github.com/meta`, `ssh_keys`); nothing is trusted on first use.
- Same-repository operations use `github.token` (the base-commit fetch in `offline-checks.yml`, passed to
  that one step as a masked header, never written to `.git/config`).
- Games' `graphify.yml` calls Party's reusable `graphify-refresh.yml` at a pinned commit. Two
  things are needed, and today neither is in place. (1) Party's Settings, Actions, General,
  **Access** must be "Accessible from repositories owned by 'rcnechamkin' user" (it is `none`; with
  `none` the workflow cannot even be loaded). That setting lets other repositories use Party's
  actions and reusable workflows; it does not let them check out Party's files. (2) The checkouts
  inside `graphify-refresh.yml` now take an optional `PARTY_READ_KEY` secret, but Games' pin
  (`9cbce3a`, equal to `toolkit_revision` in Games' `.graphify.json`, which the Graphify check
  enforces) predates it. Moving the pin to a Party `main` commit that has it, together with
  `.graphify.json`, `test.yml` and `toolkit_ref`, and passing
  `PARTY_READ_KEY: ${{ secrets.AVRANA_PARTY_READ_KEY }}`, is a separate step after this merges.
- Known limit: a deploy key opens git, not the REST API. `tools/reconcile.py` (weekly, advisory,
  never fails) also reads the other repository's pull requests and branches through the API with
  the job token; against a private repository those reads are refused and the report records
  "GitHub unreachable or refused" instead of the PR/branch checks.

### Who can run what

| Who | Pull request or push in this repository | Cross-repository lanes |
|---|---|---|
| The owner, and anyone pushing a branch of the repository (agents included) | everything runs | run, with the secrets of that repository |
| A contributor from a **fork** (future) | `Offline checks` and `Test` jobs that read only their own repository run; secrets are absent | the access check fails fast with the fork message above; the rest of that job does not run |

For a fork contribution a maintainer reviews the diff, then pushes it as a branch of the repository
(or asks the contributor to rebase onto a branch the maintainer creates) so the cross-repository
lanes run with secrets. These workflows never use `pull_request_target`, so a fork's code is never
run with a secret; do not add it. Whether the `.avrgame` development contract is open to third
parties while Party internals stay proprietary (AVR-420, AVR-421) is **undecided**; this section
describes only how CI behaves today.

### Owner setup (once; run on your own machine, values never in chat, a file in the repository or a ticket)

```sh
cd "$(mktemp -d)"
ssh-keygen -q -t ed25519 -N '' -C avrana-ci-read-games -f games_read
ssh-keygen -q -t ed25519 -N '' -C avrana-ci-read-party -f party_read
# public halves become READ-ONLY deploy keys (gh adds a read-only key unless you pass --allow-write)
gh repo deploy-key add games_read.pub -R rcnechamkin/avrana-party-games -t "CI read from avrana-party"
gh repo deploy-key add party_read.pub -R rcnechamkin/avrana-party -t "CI read from avrana-party-games"
# private halves become secrets, read from the file, not typed or printed
gh secret set AVRANA_GAMES_READ_KEY -R rcnechamkin/avrana-party < games_read
gh secret set AVRANA_PARTY_READ_KEY -R rcnechamkin/avrana-party-games < party_read
# let Games load Party's reusable workflow (graphify)
gh api -X PUT repos/rcnechamkin/avrana-party/actions/permissions/access -f access_level=user
rm -f games_read games_read.pub party_read party_read.pub
```

Verify: re-run the failed jobs of Party PR "AVR-428" (`Cross-repo contract`, `Service trust proof`)
and Games PR `Test`; green means the *Access check* step prints "Access to ... verified" and the
later steps run. Then `gh workflow run graphify.yml -R rcnechamkin/avrana-party-games` and
`gh workflow run reconcile.yml -R rcnechamkin/avrana-party`.

Rotation and revocation: there is no expiry. To rotate or if a key may have leaked, delete the
deploy key (`gh repo deploy-key list -R <repo>`, then `gh repo deploy-key delete <id> -R <repo>`),
delete the secret, and repeat the setup for that direction. Deleting the deploy key revokes it at
once; all jobs of that direction then fail at the access check.
