# Sprint 04: SDK clean-room adaptation validation

- **Status:** **COMPLETED (2026-10-20); technical conclusions approved by the owner, SDK experimental.** Results and the closure decisions: [findings](../../findings/2026-10-20-sdk-clean-room-hearts.md).
- **Reads with:** [SDK readiness audit](../../findings/2026-10-20-sdk-readiness-audit.md),
  Games `docs/DEVELOPING-A-GAME.md`, [ADR 0011](../../adr/0011-party-console-model.md),
  [ADR 0013](../../adr/0013-party-and-game-browser-origins.md), AVR-676 (this sprint), AVR-512, AVR-421, AVR-59.

## 1. Question

Can an agent that knows only what the kit documents adapt an existing, legally reusable game into
an `.avrgame`, validate it and run it against a real Party, without help and without changing Party
Core? Where it cannot, is the missing piece a gap in the game-neutral kit, a per-title patch, or a
Party defect?

AVR-512 asks the same question for an external Node/Colyseus server (Tanks). This sprint asks it for
the common case: a turn-based Python game already in the Games repository. Together they are the
"second unrelated architecture" AVR-512 requires before any abstraction is promoted.

## 2. Shape

| Role | Who | Has |
|---|---|---|
| Adapter | a fresh agent, no prompt history | a fresh clone of both repositories at pinned commits, the kit export, the Party tools export, the chosen game's legacy source; read access only to documented paths |
| Observer | the orchestrating session | the adapter's log; answers nothing the docs do not answer; records each intervention as a gap |
| Reviewer | an independent agent | the result, the log and the gap list; checks the classification |

Rules:
- Anything the adapter needs that is not written down is logged as an **intervention**, answered
  minimally, and becomes a docs or kit change, never a silent hint.
- Game-specific presentation (art, copy, layout) stays in the game's directory. Anything the
  adapter wants in the kit must be needed by a second game (or AVR-512) to be promoted.
- No Party Core change unless a defect is demonstrated by a failing test that does not depend on the
  game. Any such change is its own PR.
- No Pi, no deploy, no owner install. "Installed" means validated and installed into a throwaway
  Party data directory (needs gap 3 decided) or, failing that, validated only, stated as such.

## 3. Deliverables

1. The adapted game as an `.avrgame` built by the documented commands, passing `comply`, the Party
   validator and the real-Party harness, with a multi-browser session played to an ended result.
2. The adapter's log: every step, command, tool version, intervention and elapsed effort.
3. A gap table: documented vs undocumented steps; per-title patches vs reusable kit changes;
   Party defects (expected: none).
4. Small PRs for the reusable kit and docs changes, each with its gap number. No speculative kit
   rewrite.
5. A second clean-room run of the revised instructions (a different fresh agent). Passing it is the
   sprint's acceptance.

## 4. Candidate games

All are in Games `games/`, under the repository's MIT licence (BEACNpool). Provenance is clear at
repository level only, so each still needs a per-file check of art, word lists and copied rules text.

| Game | Why | Concern |
|---|---|---|
| **Hearts** (recommended) | Turn-based, 4 players, hidden hands, bots exist (`bots.py`): exercises private views, turn order, reconnect and the result report. Card games are a common adaptation. | Needs card art, or text cards. |
| Werewolf | Roles, secret information, phases, a narrator: stresses the Party/Game boundary (who runs the night). | Phase timers interact with `TABLE_ABANDON`. |
| Bingo | Simplest; good as a fast first pass for the docs gaps. | Too easy to find kit gaps in private state. |
| Four in a Row (`connect4`) | Two players, small. | Must not be named "Connect 4" (trademark). |
| Spades | Close to Hearts. | Open owner decisions and the friends field-test freeze (`docs/findings/2026-10-07-spades-native-readiness.md`). Not this sprint. |

Avoid: Battleship, Family Feud, Trivia and Charades (trademark or content rights), and Chess
(python-chess is GPL).

## 5. Dependencies

Before the adapter starts (from the audit, §2):
- **Gap 1, discovery:** Games docs only. Without it the first finding is just "could not find the
  kit", which is already known.
- **Gap 2, the Party layer for kit games:** an owner decision (§6), so the adapter knows whether a
  Party button is expected.
- **Gap 3, install rehearsal:** a decision on what "installed" means for this sprint.
- **Gap 4, the tools version in the guide:** one line.

Not needed first: gaps 5–10 are things the sprint is expected to find and fix.

Also:
- Games #88 and Party #175 merged or explicitly deferred, so the adapter's pinned commits are stable.
- Party #176 (provider ordering fix) merged, so the real-Party harness runs clean in any order.

## 6. Owner decisions (taken 2026-10-20)

1. **Sprint approved, with Hearts as the donor game.** It tests the adaptation pipeline and the SDK. It is
   not a commitment to ship Hearts as a supported Party title.
2. **Party layer:** SDK games should support the existing Party System Interface through an explicit,
   versioned opt-in. First-party opt-in does not authorize arbitrary untrusted community games. The
   approved origin, credential, sandbox and trust boundaries stay. Unresolved policy is documented, not
   silently widened.
3. **Installed:** beyond package validation. A disposable, reproducible environment exercises the real
   install, catalog-registration and removal/rollback code, with no second installer. What cannot be
   reproduced safely is documented, and no full install acceptance is claimed. No Pi operations or
   production deployment.
4. **Donor code:** the adapter may read Hearts in the legacy Games repository as donor source only, not as a
   supported runtime. Provenance and licensing are verified and kept; no standalone LAN Games behavior is
   maintained.
5. **Independence:** a fresh adapter agent works from documented SDK materials and the donor source only.
   Every undocumented intervention is recorded, and a second independent agent reproduces the result from
   the corrected instructions. Title-specific work is kept apart from reusable SDK fixes.
6. **Sequencing and limits:** merge the Sprint 03 PRs first, then the small discovery and documentation
   fixes, then the adaptation, multi-browser test, packaging, disposable install and reproduction. The SDK
   is not frozen and third-party readiness is not claimed from this one exercise; AVR-512 provides the
   external Node/Colyseus validation. Sprint 04 implementation PRs are not merged without approval.
