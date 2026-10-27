# Contract versioning, compatibility windows and deprecation (AVR-72)

- **Status:** proposal, 2026-10-26. Nothing is implemented. No contract, version string, validator or checker
  changes with this document. **Owner decisions are required** (section 8) before any code is written.
- **Reads with:** `contracts/party-games.v0.json` and Games `provider/avrana-contract.json` (what each side
  implements and requires), `tools/contract_check.py`, [AVRGAME-PACKAGE.md](../AVRGAME-PACKAGE.md) (fail-closed
  `format` and `requires`; the additive `artwork` block, D3),
  [the SDK readiness audit](../../findings/2026-10-20-sdk-readiness-audit.md) item 5.

## 1. What exists today

| Contract | Current version | Kind | How compatibility is checked now |
|---|---|---|---|
| Game Contract | `avrana.game/v0` | declaration | validated unchanged inside every package and repository contract |
| `.avrgame` manifest | `avrana.avrgame/experimental.1` | declaration | `format` must equal exactly; unknown keys refused |
| Device capabilities | `contracts/capabilities.v0.json` | vocabulary | names must equal the browser probe's (a test) |
| Party session protocol | `avrana.party-session/v0` (prefix `aps0`) | wire | package `requires.session` must equal; Games vendors `protocol.py` **pinned by file SHA-256** |
| Game result | `avrana.game-result/v1` | wire | same: exact string, vendored file pinned by SHA-256 |
| Bridge | `avrana.party-bridge/v1` | wire | same |
| Party layer | `avrana.party-layer/v1` | wire, optional | vendored byte for byte |
| Party ↔ Games boundary | `avrana.party-games/v0` | aggregate | `tools/contract_check.py` compares both declarations in both repositories |
| Game kit | `experimental.1` ("moves on any breaking change") | tool | `comply` checks the vendored files' digests |
| Party tools export | `experimental.3` | tool | – |

Three facts follow:
1. **Every check is exact equality.** Any bump of any string makes every existing package uninstallable at once.
2. **Implementation bytes are pinned, not behaviour.** Fixing a comment in `avrana/party/protocol.py` changes the
   digest that Games and the kit pin, although the protocol is unchanged.
3. **Strict JSON makes additive changes one-way.** A Party that predates `artwork` refuses a package that has it
   (correct and safe, but the only message is "unknown key").

None of this is wrong for an experimental platform. It does not scale to outside developers.

## 2. Policy

**V1. Two kinds of contract, two version shapes.**
- **Wire protocols** (session, result, bridge, layer): keep `avrana.<name>/v<MAJOR>`. Within a major, a message
  may only gain **optional** fields, and a receiver must ignore an optional field it does not know **only where the
  protocol says that field class is ignorable**. Everything else stays refused, as today (fail closed).
- **Declarations** (Game Contract, `.avrgame` manifest, capabilities vocabulary): move to
  `avrana.<name>/<MAJOR>.<MINOR>`. A minor adds optional blocks or keys. A major removes or changes meaning.

**V2. A support window, published by Party.** `contracts/party-games.json` (unversioned file name) states for each
contract: `current`, `min_supported` and, for declarations, `max_minor`. For example
`"avrgame": {"current": "1.2", "min_supported": "1.0"}`.
- Party accepts a declaration with the same major and `minor <= max_minor`.
- Party refuses a higher minor with a clear message naming the Party version that adds it, never just "unknown key".
- Party refuses a lower major outside the window with a message naming the migration note.

**V3. Pin behaviour, not bytes.** A vendored reference file is checked against the **vectors** for its version
(`contracts/vectors/<name>.v<MAJOR>.json`), not its SHA-256. A Party-side refactor that keeps every vector passing
breaks nobody. The vectors file is the contract; its digest is what both declarations pin.

**V4. Capability negotiation first, version gates second.**
- Device capabilities are already negotiated per seat (`evaluate.js` and `evaluate.py`). That stays the model.
- Party features that a game may use (for example the Party layer, artwork, a future options mechanism, AVR-678)
  become **named features** in the support file.
- A package declares `requires.features` (refused before install when missing) and `uses.features` (feature-detected
  at run time; never refused).
- A version bump is only for a change that a feature name cannot express.

**V5. Fail before an unsafe launch, also after a Party update.**
- Install time already refuses incompatibility.
- New: Party Core re-checks every install record against the support window **at start**. A game that falls
  outside it is shown to the owner as "needs an update for this Party" and is **never offered for launch**.
- The catalog says so in plain words; guests just do not see the game.

**V6. Older appliance, newer game; newer appliance, older game.**
- **Newer game on an older Party:** refused at install with "needs Party X or newer". It is never half-installed.
- **Older game on a newer Party:** supported for the whole window (V7). Party keeps the previous major's handler
  (session protocol: accept `aps0` while `aps1` is current) until the window ends.

**V7. Windows and experimental expectations.**
- `v0`, `experimental.N`: **no window**. A breaking change is allowed with a release note and a `comply` warning one
  Party release ahead where possible. This is today's behaviour, written down.
- From the first frozen major (an owner act, AVR-37 "Freeze"): the previous major stays supported for **two Party
  releases or 6 months, whichever is longer** (D2).

**V8. Deprecation process.**
1. A contract or feature is marked `"deprecated": {"since": "<party release>", "removal_after": "<date or
   release>", "note": "<migration doc>"}` in the support file.
2. Then:
   - `install_game` prints a warning at install;
   - `comply` reports it as a warning (not a failure);
   - the owner view lists affected installed games.
3. Removal happens only in a new major, only after `removal_after`, and only when the warning shipped in at least
   one release.
4. Nothing is removed by surprise. Removing anything that a frozen major promised needs an ADR.

**V9. Migration guidance.** Every major and every deprecation has a short migration note:
`docs/migrations/<name>-<from>-to-<to>.md`, with before and after for each changed field. Later the kit can offer
`avrana_gamekit migrate`, but the doc comes first.

**V10. Compatibility testing.**
- `contracts/vectors/` keeps the vectors of **every supported major**, not only the current one.
- Party's tests run every supported major's vectors.
- `comply --against <version>` runs a package's conformance checks against each supported version of the support
  file.
- `tools/contract_check.py` checks that both repositories' declarations fall inside each other's windows (instead of
  being byte-equal).

## 3. What changes for the existing contracts (when frozen; not now)

| Contract | Proposed first stable version | Note |
|---|---|---|
| `.avrgame` manifest | `avrana.avrgame/1.0` | `artwork` becomes part of 1.0; the next optional block is 1.1 |
| Game Contract | `avrana.game/1.0` | – |
| Session protocol | `avrana.party-session/v1` (prefix `aps1`) | only if a breaking change is needed; otherwise freeze `v0` as is and call it stable (D3) |
| Result | stays `v1` | already v1 |
| Bridge, layer | stay `v1` | already v1 |
| Kit | `1.0.0` (SemVer for the tool) | the tool versions separately from the contracts it implements; its README states which contract versions it targets |

## 4. Diagnostics the owner and developer see

| Where | What |
|---|---|
| `install_game` refusal | "Courting needs Party 1.4 or newer (`.avrgame` 1.3). This Party supports 1.0–1.2." |
| Owner view, after a Party update | "2 games need an update for this Party: …" with the migration note link |
| `comply` | the target Party window, each requirement's status, and every deprecation warning |
| `/party/diag/` | the support file's `current` and `min_supported` per contract (read-only) |

## 5. Threats and failure modes

- **A tolerant receiver hides an attack.** V1 lets only declared-ignorable optional fields through. Security-relevant
  fields (tickets, grants, ids, origins) are never ignorable.
- **A window kept too long keeps old bugs alive.** A security fix may end a window early. It needs a note and an
  owner decision, never a silent change.
- **Two handlers drift.** Each supported major keeps its own vectors (V10), so the old handler stays tested.

## 6. What this does not cover

- Package signing and update rules (AVR-58, avrana-party#230), which use V2's window for "can this update install".
- The SDK licence and the public/proprietary boundary (AVR-677, AVR-421).
- Game options (AVR-678), except as an example feature name.

## 7. Phasing

1. **Support file and messages:** add `contracts/party-games.json` with windows equal to today's exact versions
   (a window of one), and better refusal messages. No behaviour change.
2. **Vectors instead of digests (V3):** switch the vendored-file checks in `contract_check.py`, Games'
   `test_avrana_contract.py` and the kit's `comply`. This is a paired, cross-repository change (docs/CROSS-REPO.md).
3. **Feature names (V4)** for the layer and artwork.
4. **Start-time re-check (V5)** in Party Core.
5. **Freeze:** the owner act that starts the first window.

## 8. Owner decisions

| # | Question | Options | Suggestion |
|---|---|---|---|
| D1 | Adopt the two-shape versioning (V1)? | yes; SemVer everywhere; keep exact strings | **yes** |
| D2 | Window length after freeze | 1 release; 2 releases or 6 months; 12 months | **2 releases or 6 months, whichever is longer** |
| D3 | Freeze the session protocol as `v0` or bump to `v1` first? | freeze v0; bump | **freeze v0 unchanged** if no breaking change is pending: a new prefix costs every game a migration for nothing |
| D4 | Pin vectors instead of file digests (V3)? | yes; keep digests | **yes**: a comment change should not be a breaking change |
| D5 | When to freeze | after first outside developer; after Pi acceptance; later | **after the first outside developer has built a game with the kit** (AVR-421), not before |
