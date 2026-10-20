# Sprint 04 findings: a clean-room Hearts adaptation on the game kit

- **Status:** evidence of one exercise (AVR-676, 2026-10-20). The owner approved its technical conclusions at
  closure (§7); the SDK stays experimental. It freezes no SDK and claims no v1 readiness, no redistribution
  clearance and no physical acceptance. AVR-512 (an external Node/Colyseus server) is the complementary validation.
- **Reads with:** [the Sprint 04 proposal](../design/proposals/2026-10-20-sdk-clean-room-validation.md) (§6 has the
  owner decisions), [the SDK readiness audit](2026-10-20-sdk-readiness-audit.md),
  [install-game runbook](../runbooks/install-game.md) ("Rehearsal").

## 1. Answer

A fresh agent with only the two developer bundles and the Hearts donor source produced a valid, deterministic
`.avrgame` with **no interventions**. That package (r1) passes the kit's checks, the Party validator, a
real-Party browser run on Linux and the disposable install rehearsal.

A second fresh agent (r2), given the corrected instructions, repeated the exercise independently, also with no
interventions (§5). It built its own Hearts, a different package with a different sha256. Its package also
passes the kit's checks, the validator, the rehearsal and the real-Party Linux run, after one harness fix (§4).

What it does not show: install on an appliance, systemd, real phones, Safari, or that a third party with a
different kind of game would get as far.

No Party Core defect was found in what was run.

## 2. What was run

| Run | Who | Given | Result |
|---|---|---|---|
| r1 | fresh agent | kit bundle `experimental.1` (Games 37cbbf2), tools `experimental.3` (Party 66453d6), donor | `hearts-0.1.0.avrgame`, sha256 `26b3dac1bcac…`, 28 files; 18 gaps; 0 interventions |
| r2 | second fresh agent (Sonnet) | kit bundle from Games 9231ec7 (PR #91, the corrected instructions), the same tools and donor | `hearts-0.1.0.avrgame`, sha256 `b49a0fb591aa…`, 31 files; 14 gaps; 0 interventions |

Each run worked in its own directory with no repository access. Their logs, gaps, provenance and decisions
are in Games `experiments/avr-676-hearts/records/` and `experiments/avr-676-hearts/r2/records/` (PR #92), in
their own words.

## 3. Verification (by the orchestrator, not the adapter)

| Check | Windows (Chromium) | Linux (cloud container, Ubuntu 24.04) |
|---|---|---|
| Bundles verify; `check`; `comply` (r1 `--quick` 8/8; r2 `--tools --boot` 9/9, and 8/8 at 1 and at 4 players) | pass, both | not run |
| `play --script`, result accepted by the Party's check; the adapter's own tests (r1 15, r2 7) | pass, both | not run |
| `match --browsers 2` (stand-in Party) | pass, both | not run |
| Party validator; re-pack from the committed source gives the same sha256 | pass, both | same sha256, both |
| Real Party, real catalog overlay (`native-package.spec.ts`, Party PR #180), 3 repeats | not run | r1: 6/6 (seats, isolated origin, reload, Host End; a whole game to a recorded round). r2: 6/6, after the harness learned the Party pregame (Party 3753f4e); r1 6/6 again there |
| Install rehearsal (Party PR #179): install, list, catalog, reinstall refusal, remove, injected rollback | 11/11, both | r1: 11/11; `test_install_*` 79 OK, 1 skipped (root) |

Hosted CI was unavailable (billing). That is missing CI evidence, not a code failure.

**What the real-Party runs cover, and what they do not** (Linux, Chromium at phone size, Party #180):
- **A full game by two people:** in test 2 Ana and Ben play a whole Hearts game through the page, against
  the game's two bots, and the Party records a completed round with two players. Each package passed it 3
  times.
- **Four-player seating:** in test 1 four phones are seated as players through the real bridge (Hearts'
  `players.max` is 4) and a fifth watches. No four-person game was played to the end on the real Party; r2's
  own four-browser `match` used the stand-in Party and was not re-run by the orchestrator.
- **The Party layer over a kit game:** Party #182 runs it on a fresh kit scaffold that opts in, 3/3. The Hearts
  pages do not opt in.
- **Physical devices:** none. No iPhone, Android, Safari, installed PWA, touch, screen reader, real Wi-Fi,
  nginx, TLS, systemd or appliance.

The rehearsal calls the real `install_game.main` against a scratch root with the system calls injected. It is
not install acceptance: its `NOT_REPRODUCED` list (systemd, real ownership and modes, trusted-path checks, the
Node runtime, Party reads in dry-run) is printed with every run.

## 4. Gaps, by kind

r1 recorded 18. Each is fixed by a reusable change, documented but not built, title-specific, or waiting for an
owner decision (§7).

**Reusable, fixed in Games PR #91** (kit: G-03 `dev_args` in `match`/`--boot`, G-08 `play` flushes, G-16
`strings()` check; guide: G-01, G-02, G-04, G-05, G-06, G-07, G-10, G-12 (in part), G-13, G-14).

**Reusable, fixed in Games PR #90:** the Party layer for kit games, an explicit versioned opt-in
(`data-avrana-party-layer="avrana.party-layer/v1"`). Opting in grants nothing: the Party's frame still answers
only its own origin or a game origin the owner registered (ADR 0013).

**Reusable, documented but not built:**
- G-09: the Python kit has no timer or `changed()` hook. The guide now says timed games use Node.
- G-11: a launch carries no game options. The guide now says so; a channel is an owner decision (§7).
- G-15: no tool dispatches the `avrana-party-layer` event to a page. Needs a stand-in layer frame.
- G-18: two packing recipes (the tools README, in this repository, and the guide). Low.

**Title-specific (Hearts only, stays in `experiments/`):** G-17 (the fourth "hold" hand in a short run); the
fixed target score; bots seated by the game; the test driver `verify/hearts-driver.mjs`.

**Harness and test fixes found on the way:**
- Party #180, 9101336: the real-Party spec assumed two seats.
- Games a140b73: the r1 Hearts driver waited on stale elements.
- Party #180, 3753f4e: the spec assumed no Party pregame. r2 turned the pregame on (its decision D12) and all 6
  of its Linux runs failed until the spec learned the Party's Play/Watch setup. The package and the Party were
  not at fault. r2 chose the pregame without the Game UX contract (r2 G04), so whether a kit game should ask
  for one is a guidance question for the guide, not a defect.

## 5. Reproduction (r2)

r2 was a different fresh agent with the same brief, the same donor and tools bundle, and a kit bundle built
from Games 9231ec7, which is #91 with the corrected guide. It did not see r1's work. It built a working Hearts of
its own design and recorded 14 gaps, none of them blocking.

**r1 gaps r2 exercised and did not hit:** G-01 (r2 G12 calls the 3-character rule clear), G-03 (r2's fixture
`dev_args` applied in its runs), G-04 (r2 ran `comply` at 1 and 4 players with watchers), G-16 (r2 uses
`strings()`). These fixes held.

**r1 gaps r2 did not exercise, so this run says nothing about them:**
- G-06: selenium and Chrome were already present;
- G-08: r2 never piped `play`;
- G-13 and G-14: r2 reported nothing either way.

G-10 (bots) partly recurred: r2 G04 asks what the Party shows for a bot.

**r1 gaps that recurred:**
- the Python timer (r1 G-09, r2 G06);
- game options (r1 G-11, r2 G05);
- licence files in a package (r1 G-12, r2 G09): the scaffold's recipe still omits the kit's `LICENSE`;
- fixture hooks at other table sizes (r1 G-05, r2 G03): now documented, but the runner's error is still a bare traceback.

**Fixed at once in #91 (3bd6095, 234fb31):**
- r2 G02 is the rest of r1 G-02. The dev-flag example #91 added did not show how the option reaches the Session.
  It is now complete, and it was checked by pasting it into a scaffolded game and running `comply`.
- r2 G08 is new: Hello Party fails `comply` by design, and the guide did not say so.

**New in r2, left as follow-ups (reusable, not done):**
- G01: how `expected_standings` handles a random deal;
- G03: name the fixture hook that raised;
- G04: five "read first" documents are not in the bundle;
- G07: `check` should warn about CRLF line endings, as `pack` does;
- G10: the `match --timeout` documentation;
- G11: a quieter `play --script`;
- G12: a card-hand example of the path form;
- G14: a click-through script inside `comply --boot`.

**Title-specific:** G13, what the people see when a bot wins.

## 6. Interventions

None in either run. Neither agent was blocked or asked a question. r2 had one tool permission denial, when it read a file outside its directory. It re-ran the job with the output inside its own directory, which is the brief's rule working.

## 7. Owner decisions (2026-10-20, at closure)

The technical conclusions are approved; the SDK stays experimental. Each direction below is approved and
nothing is built until its own proposal is approved:
1. **Redistribution:** a narrowly scoped redistribution of the public SDK and runtime parts; Party Core stays
   proprietary. First an audit of copyright, third-party licences, notices and exactly which files a package
   carries, then a proposed SDK licence and packaging policy. No licence change and no external distribution
   without a separate final approval. Until then no package goes to a third party.
2. **Game options:** a versioned, declarative, Party-validated options mechanism. A focused proposal covers Host
   configuration, value types, defaults, capability negotiation and backward compatibility. The launch protocol
   is not changed yet.
3. **Python timers:** a bounded wake-up or timer mechanism for turn clocks, disconnection recovery and
   asynchronous progress. A review of scheduling, cancellation, state-change reporting, process safety and
   testability comes first, with no speculative runtime rewrite.
4. **Community origins:** Party Core keeps authority over origin registration, and a community package cannot
   authorise its own origin. Per-game isolation is preferred for untrusted community games. The trust-tier
   policy and its implementation requirements are to be documented.
5. **Pregame:** optional, declared from a game's setup needs. The Party owns Play/Watch and the launch. The
   guide now says when to ask for it (Games #91).

The tracking issues are linked from AVR-676.

**The evidence format in Games #92:** the two tested packages, pinned by sha256, the game's own source,
the records and the drivers. The kit trees copied beside each game are dropped: they could not be rebuilt
once the kit PRs are squash-merged, and the packages hold their bytes. `verify/check_packages.py` checks that
the committed game files are the ones the packages carry.

## 8. PRs (none merged; all owner-gated)

| Repo | PR | What |
|---|---|---|
| Party | #177 | audit, proposal, owner decisions |
| Party | #179 | disposable install rehearsal |
| Party | #180 | real-Party harness for a native package |
| Party | #182 | the Party layer over a packaged kit game, real Party (on #180) |
| Party | #181 | this note (on #177) |
| Games | #89 | discovery and stale-doc fixes |
| Games | #90 | Party layer opt-in for kit games (on #89) |
| Games | #91 | reusable kit and guide fixes (on #90) |
| Games | #92 | the Hearts experiment and the adapter's records |
