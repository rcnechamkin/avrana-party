# Native Checkers: Party integration completion checkpoint

Observed 2026-10-08 on the AVR-238 paired branches. Historical engineering evidence, not an
architecture instruction, deployment record or physical acceptance. Party main baseline:
`5ae52d75c860d8a2d8b6f3de8309895147b7f9cc`; Games candidate:
`76ec4873bb6a53098b7e6eb9afe95defc67d442a`.

## What the native path required

The existing contract, appliance grant, registry transport and generic game-origin navigation
support Checkers as data: `contracts/games/checkers.json`, the native grant in `avrana-pi4.json`
and the generated catalog. No Checkers branch was needed in Party Core. AVR-303 on main supplies
origin navigation; AVR-304 PR #92 supplies the owner-run appliance bootstrap. Neither merged
source nor these candidate branches establish production installation.

The provider harness previously ran only the donor runtime. `tests/provider/native_runtime.py`
now starts the grant-declared child with an inherited Unix listening socket; the real Party
internal Unix server accepts its signed result. Activation also precedes Host End after a child
exit, and teardown is serialized with activation. The tests record an unconfirmed end after
process state is lost; they do not pretend the child recovered its match. This subprocess
fixture is not a substitute for DynamicUser, LoadCredential or systemd sandbox evidence.

ADR 0015 already accepts and attributes results, but Party Home had no display projection.
AVR-238's requested display required a generic member-only `result_summary` allowlist: names,
standing and optional rank, game and mode. Game-owned data and authority ids stay private; the
game bridge drops the whole summary. The summary lives only as long as the current session
object; persistent history and Profile attribution remain AVR-71.

Two test drafts needed correction before execution: spectators receive 403 for attempted moves
(not a player's 409), and reconnect must prove a fresh successful server poll and restored
controls, not equality with a cached board. The provider UI helper selects actual movable/target
cells and accounts for a branch choice submitting a complete multi-jump.

## Evidence boundary

Windows: result projection 26 tests passed, bridge 28 passed, session flow 61 passed; metadata
2 passed and real native process tests 4 skipped. Repository integrity and paired contract
checks passed. Independent scoped result review passed, including two detected privacy
mutations. Games final candidate independent review passed with zero Important findings.
The PR implementation reports carry final CI results; no Linux/native/browser success is
asserted here before execution.

Checkers provisioning under real systemd and `boundary --phase 2` with Checkers remain pending.
PR #92's stand-in systemd proof is bootstrap evidence, not Checkers evidence. No Pi operation,
origin cutover, deployment, merge or real-phone validation occurred. AVR-261 remains the owner
acceptance step. This checkpoint does not freeze SDK or `.avrgame` design.
