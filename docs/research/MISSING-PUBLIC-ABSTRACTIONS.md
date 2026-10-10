# Missing public abstractions, prioritized

- **Status:** Proposal / Research (ranking from Checkers evidence; nothing built or decided).
- **Date:** 2026-10-10
- **Sources:** Checkers findings F1-F14 and D1-D15 (Games `docs/findings/2026-10-07-checkers-native-findings.md`; Party `docs/findings/2026-10-08-checkers-party-integration.md`); `docs/design/NATIVE-GAMES.md`; ADR 0014, ADR 0016; Linear AVR-37, AVR-38, AVR-40, AVR-71, AVR-72, AVR-137.
- **Related:** `docs/research/DEVELOPER-FRICTION-AUDIT.md`, `docs/research/HELLO-PARTY-DESIGN-NOTE.md`, `docs/research/AVRGAME-EXPERIMENTAL-DRAFT.md`

Ranking by impact and evidence. "Evidence" cites the Checkers findings (`F-games` = Games
`docs/findings/2026-10-07-checkers-native-findings.md`, F1-F14, D1-D15; `F-party` = Party
`docs/findings/2026-10-08-checkers-party-integration.md`). All entries are **proposals**; none is built or decided. Promotion follows
NATIVE-GAMES `docs/design/NATIVE-GAMES.md:112-114` ("only on repeated evidence"), D5 (Checkers findings 3.3: not promoted on two copies; a
third native game is the trigger) and ADR 0014 d12 (unfrozen). Priority is for the owner's scheduling; it does not lift any gate. With the Checkers pair merged (2026-10-10), Checkers is the second native consumer after the stand-in; the "third native game" trigger from D5 is not yet met.

Evidence strength: 2 = stand-in + Checkers (+ the fork), 1 = one game, 0 = reasoned.

| Rank | Missing abstraction | Impact | Evidence | Cited by |
|---|---|---|---|---|
| 1 | **Game-side protocol helper** (launch/end verification, ticket redeem, token, `ended` delivery) behind one public, language-neutral spec. Today: two vendored Python files copied byte for byte, plus eleven hand-written pieces duplicated three times (stand-in, Checkers, fork). Includes the strict-JSON, proxy-header and quiet-logging defaults | H: every game, every language | 2 | F-games 3.1, 3.2 (two defects found in copies), F2, F9, D4, D5 |
| 2 | **Inherited-socket server runtime** (serve on fd 3, correct address family, `listen_fds`, key + env loading, clean idle exit) | H: a game that works locally does not start under the unit | 2 | F1, F7, F8, ADR 0016:337 |
| 3 | **Dev harness / Party simulator** usable on Windows/macOS/Linux without a Pi or systemd: fake Party Core that launches your process, mints tickets, accepts `ended`, with an explicit dev transport instead of per-game test seams | H: gates third-party testing and AVR-40 | 2 | F8, D10, F-party (provider harness is POSIX only, `tests/provider/native_runtime.py`), developer friction audit steps 4, 13 |
| 4 | **Session lifecycle semantics**: `end` after `ended` acknowledged; `ended` idempotent/verdict-on-replay; read-only admission after `ended`; launch of a new session visible to the page (session epoch); roster vs late tickets | H: first-player experience (reload at results shows nothing; stale board) | 2 for F3, 1 for F4/F5/F11/F12 | F3, F4, F5, F11, F12, D12, D13 |
| 5 | **Page-side bridge client** (a game-facing JS helper wrapping the shim: origin discovery, ticket, seat, retries, reconnect levels, Host verbs) and platform serving of shim/origin route/CSP | M-H | 2 (stand-in, Checkers, fork `/api/avrana`) | F10, F12, D1 note (`frame-ancestors`) |
| 6 | **Build identity** for a native unit (what `game.build` is, who computes it, test that it changes with the code) | M: results' provenance | 1 (+ the fork's digest) | F6, D15, ADR 0015:59,137-148 |
| 7 | **Package manifest + single-package validator CLI** (the thing AVR-37/39 would define); today only whole-catalog validation | M-H, but gated | 0 for format, 2 for contract fields | `AVRGAME-EXPERIMENTAL-DRAFT.md`; `contracts/README.md`; F-games 5 |
| 8 | **Presence/roster signal in the bridge view** (who is here; opponent away; late joiner) | M | 1 | F12 (presence note), F11, F14 |
| 9 | **Onboarding content contract** (objective, actions, stable section ids, show policy, platform rules control in play) | M | 1 (Checkers; BLUFF, EXPO have their own sheets) | F13, UX 4.15, AVR-37 text, AVR-293 |
| 10 | **Ended reporter as a library**: retry within message life, off the lock, verdict word handling | M | 2 | F5, 3.1 second table |
| 11 | **Logging convention** (quiet by default, no credentials, one-line errors, journal-friendly) | M, cheap | 2 | F9 |
| 12 | **Player-bounds / pregame semantics** (`pregame: false` implications: who plays, `min_players`, refusal sentence shown to Host) | M | 1 | F14, D11 |
| 13 | **Result visibility to phones after the round** (generic result summary) | M | 1 | F4, D12, F-party (generic `result_summary` allowlist added in PR #94; `AVR-71` owns history) |
| 14 | **Resource ceilings and idle definition** measured on a Pi | M | 0 (unmeasured) | F7, D14, ADR 0016:244-246, AVR-138, AVR-261 |
| 15 | **Late-join announcement** to game and page | L-M | 1 | F11 |
| 16 | **Artwork/cover intake** for third-party games | L | 0 | `contracts/artwork.json`, AVR-294 |
| 17 | **Normalized input intents / seat bindings** | M, other issue | 0 here | AVR-137 |
| 18 | **Compatibility/deprecation policy** | M, other issue | 0 | AVR-72 |

## Notes

- Ranks 1 to 3 are the same cost for any game and are what an outsider hits within the first day (developer friction audit steps 4, 5, 7). They also already have two independent copies each, so they are the strongest candidates once a third native game exists (Hello Party, designed in `HELLO-PARTY-DESIGN-NOTE.md` and now being implemented under AVR-38, or the Spades lane).
- Ranks 4 and 6 need paired changes to digest-pinned vendored files (D13, `provider/avrana-contract.json:7-8,15-16`) and are Party-lane decisions.
- Nothing here argues for exposing Python `GameSession` as the SDK (AVR-38 explicitly says not).
- Owner guardrail: no abstraction here may make the game the top-level browser document or mandate a transport (rank 5 must keep the shell free to frame a game viewport).
- Direction constraint (AVR-143, AVR-316, 2026-10-09): none of these abstractions may require official commerce, accounts or storefront services. Publisher identity, signing and entitlement evidence are tracked by AVR-58, AVR-316 and AVR-73, not here; a package manifest (rank 7) should leave room for them without defining them.
