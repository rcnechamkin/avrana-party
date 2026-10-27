# Game options: a versioned, declarative, Party-validated mechanism (AVR-678)

- **Status:** proposal, 2026-10-27. Nothing is implemented. The session protocol, the Game Contract and the result
  envelope are unchanged until the owner approves (section 9).
- **Why:** both clean-room Hearts adaptations had to drop the donor's target score (50 or 100), bot level and turn
  clock (r1 G-11, r2 G05). Today a launch carries only the roster.
- **Reads with:**
  - `avrana/party/protocol.py` (`launch_message`, `open_message`) and its Games copies (`core/party_protocol.py`,
    `avrana_gamekit/js/party-protocol.mjs`);
  - `avrana/contracts/game.py` (extensions) and `avrana/contracts/party_config.py` (`net.avrana.party`);
  - `avrana/party/result.py` (the result envelope);
  - [ADR 0010](../../adr/0010-party-pregame.md) (pregame), [ADR 0011](../../adr/0011-party-console-model.md)
    decision 4 (the setup scene);
  - [select, then launch](2026-10-26-select-then-launch.md) (a setup for every game, behind a default-off option);
  - Games `docs/findings/2026-10-27-python-kit-wakeups.md` (a turn clock also needs the kit's timers).

## 1. Two facts that decide the design (probed on `main` 6c5b3c7)

1. **An older game ignores an extra top-level key in a launch.** A launch sealed with an added `options` object
   opens cleanly in Party's `protocol.open_message` and in the Games Node kit's `openMessage`. Both check `roster`
   and the common claims, and nothing else. The Python kit vendors the same file. So the launch can carry options
   **without a protocol version bump**, and an older game simply never reads them.
2. **An older Party refuses an unknown key inside `extensions["net.avrana.party"]`, but ignores an unknown
   extension namespace.** `party_config.party_extension` raises `unknown key` for anything outside `pregame`,
   `state`, `launch_timeout_s` and `end_timeout_s`. That makes the whole game unlaunchable. `game.py` only checks
   that other extension names are reverse-DNS. So a declaration under `net.avrana.party` would break every
   older appliance. **The declaration therefore gets its own namespace:** `net.avrana.options`.

## 2. Declaration (Game Contract)

```json
"extensions": {
  "net.avrana.options": {
    "v": "avrana.game-options/v1",
    "options": [
      {"id": "target", "label": "Play to", "type": "enum", "default": "100",
       "choices": [{"value": "50", "label": "50 points"}, {"value": "100", "label": "100 points"}]},
      {"id": "bots", "label": "Computer players", "type": "int", "default": 0, "min": 0, "max": 3,
       "unit": "players"},
      {"id": "clock", "label": "Turn clock", "type": "bool", "default": true}
    ]
  }
}
```

The rules are checked by a registered `EXTENSION_CHECKS` entry, so a bad declaration fails wherever contracts
are checked, including the `.avrgame` validator and the kit's pre-flight:

- `v` is exactly `avrana.game-options/v1`. A Party that does not know a later `v` treats the game as having no
  options (section 5).
- `options`: 1-8 entries. `id` matches `^[a-z][a-z0-9_]{0,23}$` and is unique. `label` is 1-40 characters.
  Every entry has a `default`.
- **Types: a closed set of three.**
  - `enum`: 2-8 `choices`. Each `value` matches the `id` pattern, and each has a label of 1-40 characters.
  - `int`: `min` ≤ `default` ≤ `max`, all integers within ±10 000, at most 101 steps. The optional `unit` label
    is 1-16 characters.
  - `bool`.
- **Not supported:** free text, numbers with fractions, lists, nested objects, per-seat options, options that
  depend on other options, and options that change the player count. Player count stays `players.min/max`.
- Labels are display text only. They are never sent to the game, which gets ids and values.

## 3. The launch

The Party adds one key to the launch payload. The payload keeps `v: "avrana.party-session/v0"`:

```json
"options": {"v": "avrana.game-options/v1", "values": {"target": "100", "bots": 1, "clock": true}}
```

- It is sent **only** when the game's contract declares `net.avrana.options` with a `v` this Party knows.
  `values` then holds **every** declared option, with the Host's choice or the default. No unknown id is ever
  sent.
- `launch_message(key, game, sid, roster, now=None, options=None)` gains the keyword. Without it the payload is
  byte for byte what it is today.
- The MAC already covers the payload, so the values can't be changed on the way.

**The game re-validates.** The kit's `on_launch` returns the roster as today. A new
`GameSide.options(declaration)` returns the values checked against the game's own declaration:

- an unknown id is dropped;
- a wrong type or a value out of range falls back to the default;
- a missing id gets the default;
- a launch without `options` gives all the defaults.

It never raises, so **an option can never break a launch** (the ticket's rule).

## 4. Host configuration

- **Where:** the setup scene (ADR 0011 decision 4). For a game with `pregame`, options sit under the Play/Watch
  list. For a game without it, they need the setup that [select, then launch](2026-10-26-select-then-launch.md)
  proposes. Until that is on, a game without pregame launches with its defaults. This proposal does not add a
  second setup.
- **Who:** only the Host changes them. Every member sees the current choices read-only in the setup ("Play to
  100 · 1 computer player · Turn clock on"), so nobody is surprised.
- **Validation:** Party Core checks the Host's change against the declaration (the same rules as section 3)
  and refuses anything else with 400. It is an `if_version` write like other setup changes.
- **Persistence:** choices are kept **for the life of the Party, per game**. "Play again" and the next round of
  the same game reuse them. Ending the Party forgets them. Nothing is written to disk, which fits the
  continuity rules being decided in AVR-21. A changed contract after an update re-validates: a stored value
  the new declaration does not accept reverts to its default.

## 5. Compatibility matrix

| Party | Game | Result |
|---|---|---|
| without the feature | no declaration | as today |
| without the feature | declares `net.avrana.options` | the game installs and launches (unknown namespace ignored); no `options` in the launch; the game uses its defaults |
| with the feature | no declaration | as today; no `options` key, no setup controls |
| with the feature | declares v1 | setup controls; launch carries `options`; the game re-validates |
| with the feature | declares an unknown later `v` | treated as no declaration; the game uses its defaults; the Party logs it once |
| with the feature | an older game build that ignores `options` | the key is ignored (probed, section 1); the game plays its own defaults, though the setup showed choices. Mitigation: the setup shows options only from the *installed* contract, so this happens only if the contract declares options the server code does not read, which `comply` catches (section 7) |
| without the feature (older Party) | a game whose declaration is invalid | the invalid declaration is still ignored by the older Party; the new validator refuses it at install or `comply` time |

## 6. Results

- The result envelope (`avrana.game-result/v1`) is **unchanged**. Its key set is closed (`result.py` refuses
  anything else).
- The **Party** records the values it launched with, beside the session in its own history (see the
  results-history provenance proposal). It knows what it sent, so it does not need to trust the game's echo.
- A game may also put them in its own `data` under its `data_schema`, for its own score screens. The Party
  never interprets `data`.

## 7. SDK and conformance

- **The kit's stand-in Party** (`avrana_gamekit/devparty.py` and the Node twin) sends `options`. The default is
  every option's default; `--option id=value` sets one.
- **The fixture:** `Fixture.options = {...}` is passed into the launch. `session.options` is a read-only mapping
  in both kits. In Python, `new_session(roster, options)` is used when the function accepts a second parameter.
- **`play --script`:** a top-level `"options": {...}`.
- **`comply` and the conformance run:**
  - the declaration validates;
  - a launch without `options` works and gives the defaults;
  - a launch with each `enum` choice and each `int` bound works;
  - a launch with an unknown id, a wrong type and an out-of-range value works and gives defaults;
  - every declared id is read by the session, checked by launching with a non-default value and looking for a
    visible difference in at least one view. When nothing differs, `comply` warns ("option `clock` changed
    nothing a player could see").

**Conformance tests to add:**

- Party:
  - O1: an invalid declaration is refused with the field named.
  - O2: the launch carries every declared id and nothing else.
  - O3: a Host change outside the declaration gets 400.
  - O4: a non-Host change gets 403.
  - O5: choices persist across "Play again" and are forgotten at Party end.
  - O6: an unknown `v` sends nothing.
  - O7: a launch without options is byte for byte today's (golden vector).
- Protocol vectors: one new vector with `options`. The existing vectors are unchanged.
- Kits:
  - K1: the defaults when absent.
  - K2: an unknown id is dropped.
  - K3: a wrong type gets the default.
  - K4: out of range gets the default.
  - K5: an old Party's launch (no key) works.
- Cross-repo: `tools/contract_check.py` learns the `net.avrana.options` check, so both repositories agree on the
  declaration rules.

## 8. Security and privacy

- Values are **public to the table**. Every member sees them in setup, and they carry no identity: no
  participant ids, names or per-seat values.
- They are bounded and typed (at most 8 options; ids and enum values from a fixed pattern; small integers), so a
  launch stays small. Labels never reach the game.
- They are signed with the launch by the existing per-game key. A game cannot set or change another game's
  options.
- Nothing is stored past the Party's life.

## 9. Owner decisions (approval gate)

1. Approve the declaration under a **new namespace** `net.avrana.options` rather than `net.avrana.party`. This
   is recommended, because older Parties refuse unknown `net.avrana.party` keys.
2. Approve adding `options` to the launch **without** a protocol version bump. This is safe by the probe in
   section 1. The alternative is `avrana.party-session/v1`, which would require every game to move.
3. Options for games without pregame: wait for select-then-launch (recommended), or add controls to the Host's
   game card now.
4. Persistence: keep choices for the life of the Party (recommended), or reset them every round.
5. Which game adopts it first? The Hearts adaptation, which also needs the Python kit timers (AVR-679) for its
   turn clock.

**Estimate once approved:**

| Part | Effort |
|---|---|
| Contract check and cross-repo check | 0.5 day |
| Party Core storage, validation and launch | 1 day |
| Setup UI, including the read-only member view | 1-1.5 days |
| Both kits, stand-in Party, `play`, `comply` and conformance | 1.5 days |
| First game adoption | 0.5 day |
