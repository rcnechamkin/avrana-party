# Avrana contracts (v0)

These are machine-readable agreements between Avrana, its games, the Party box and the guests'
browsers. Decisions: ADR 0004. Status: TESTED (Tier 1 and 2) on branch `claude/dreamy-carson-sja5mq`;
foundation merged in PR #3; deployment is a separate action.

| File | Schema | Validated by |
|---|---|---|
| `capabilities.v0.json` | `avrana.capability-vocabulary/v0` | `avrana/contracts/vocabulary.py` |
| `games/<id>.json` | `avrana.game/v0` (Game Contract) | `avrana/contracts/game.py` |
| `appliances/<id>.json` | `avrana.appliance/v0` | `avrana/contracts/appliance.py` |
| `vectors/evaluate.v0.json` | shared test vectors | `tests/unit/test_evaluate.py`, `tests/offline/evaluate.test.mjs` |
| → `web/party/catalog.json` | `avrana.catalog/v0` (generated) | `python3 -m avrana.contracts.catalog [--check]` |

```sh
python3 -m avrana.contracts.catalog           # rebuild the catalog after editing anything here
python3 -m unittest discover -s tests/unit    # all Tier 1 checks
```

**Rules for every file:**
- Strict JSON: a duplicate key, NaN or Infinity is an error.
- An unknown key is an error, and the error names it.
- A new field needs a new schema version. Extensions go in `extensions` under a reverse-DNS key.

## Capability vocabulary

There is one list of names, in two scopes.

**`device`** is what a guest's browser was **observed** to do. Each entry has:
- `probe`: `presence`, `functional` or `permission`;
- `summary`: text for developers;
- `label` and `missing`: guest words, with no machinery terms (tested).

**`runtime`** is what the Party box can do. Names are namespaced as `runtime.*`, `input.*` or
`presentation.*`. Providers offer them.

A status is `yes`, `no`, `partial` or `unknown`. **`unknown` means "not observed", never "no".**
The browser probe (`web/party/lib/capabilities.js`) must emit exactly the device names (tested).

## Game Contract v0 (`avrana.game/v0`)

A contract says what a game **is**, what it **needs**, and how each seat can **see** it. It requests;
it never grants. URL paths, health checks, tier, trust and granted permissions belong to the
appliance, and the validator rejects them by name.

| Field | Values | Default |
|---|---|---|
| `contract` | `"avrana.game/v0"` | required |
| `id` | `^[a-z][a-z0-9_-]{0,39}$`, not `home/party/admin/shared/diag/api`; equals the file name | required |
| `name` | 1–60 printable characters | required |
| `summary` | 1–140 printable characters (guest words) | — |
| `kind` | `native` \| `emulated` \| `other` | required |
| `players` | `{min, max}`, integers 1–32 | required |
| `screen` | `no_tv_needed` \| `tv_optional` \| `tv_required` | required |
| `input.model` | `browser_native` \| `controller_slots` \| `hotseat` | required |
| `input.slots` | 1–8, ≤ `players.max`; required for controller models, `1` for hotseat | — |
| `input.buttons` | ≤ 12 names `^[a-z][a-z0-9_]{0,15}$` (the phone controller layout; must not reuse d-pad names) | — |
| `input.directions` | `none` \| `dpad` \| `analog` | `dpad` |
| `late_join` | `spectator_only` \| `next_round` \| `supported` | `spectator_only` |
| `spectators` | `none` \| `watch` | `watch` |
| `private_player_ui` | boolean; needs a player presentation rendered on the phone | `false` |
| `runtime.type` | `lan_games_module` (legacy/retiring, [ADR 0014](../docs/adr/0014-native-games-isolated-lan-games-retired.md); not for new games) \| `emulator_profile` \| `external` | required |
| `runtime.start` | `always_on` \| `service` | `always_on` for LAN modules, otherwise required |
| `runtime.profile` | the emulator title profile; only for `emulator_profile` | — |
| `runtime.resources` | `emulator_slot`, `hw_encoder`, `host_rendering`, `hdmi` (capacity, not authority) | `[]` |
| `runtime.permissions` | requested authority, deny by default: `persistent_storage`, `party_roster`, `controllers`, `microphone`, `camera`, `local_network`, `internet`, `host_devices` | `[]` |
| `presentations` | 1–8 entries, **most preferred first** (below) | required |
| `fallback` | `explain` \| `spectate` (a player seat with no fitting presentation watches) | `explain` |
| `package` | `{version, platforms, publisher?, license (SPDX)?, source?, revision?}`; `platforms` = `["any"]` or `linux/arm64` / `linux/amd64`. Display-only claims until signing exists | — |
| `accessibility` | `color_independent`, `audio_required`, `text_scalable`, `reduced_motion_respected`, `timing_pressure`: `true`/`false`/`"unknown"` (display-only) | all `"unknown"` |
| `extensions` | `{ "net.example.key": any }` (unknown keys are ignored by Avrana core; the `net.avrana.*` keys below are read) | `{}` |

**What Party Core reads (AVR-229).** Party Core takes its per-game facts from the contract, not
from its own config: `players.min`/`players.max`, `late_join`, and
`extensions["net.avrana.party"].pregame` (boolean, default `false`; ADR 0010). That extension
allows no other key. `/etc/avrana-party/party-core.json` names only what the appliance owns (`url`,
`key_file`, `timeout`); a config that still repeats a contract field must agree with it or the
service refuses to start. `python3 -m avrana.contracts.party_config --check <config>` runs the
same comparison; `--show` prints the result. `pregame` is an extension only because v0 is frozen
("a new field needs a new schema version"); the next contract version should make it a field.

**Presentation:**
`{id, method, viewport?, roles, requires: {device?, runtime?}, optional: {device?, runtime?}}`.

- `method` is one of `browser_native`, `shared_stream`, `personal_viewport`, `controller_only` or
  `app_native`.
- `viewport` is required for `personal_viewport` and forbidden otherwise. It is one of `crop`,
  `dedicated_stream`, `browser_renderer` or `private_panel`. **A Personal Viewport is an
  independently addressable visual output for a seat.** Cropping is one method among four.
- `roles` is a subset of `player` and `spectator`. A game with `spectators: "none"` can't list
  `spectator`, and a game that allows watchers must offer a spectator presentation. The exception
  is a game whose picture is only on the TV: when every presentation is `controller_only`,
  watchers watch the TV.
- A method that needs an appliance presenter must require it: `shared_stream` requires
  `presentation.shared_stream`; `controller_only` requires `presentation.tv`; `personal_viewport`
  with `crop` or `dedicated_stream` requires the matching `presentation.personal_viewport.*`.

**Examples:**
- `arcade-gauntlet2`: a shared stream with a phone controller.
- `ps1-bomberman`: a shared stream first; TV controls for a phone that can't decode the video;
  watching as the fallback.
- `bluff`: browser-native with a private hand.

**From manifest v0** (branch `experiment/party-service`): `game.lift_manifest_v0(m)` returns
`(contract, {"entry": …})`. The entry path moves to the appliance grant, and presentations are
derived from `input.model` and `shared_video`. The two schemas have different discriminators
(`"manifest": 0` and `"contract": "avrana.game/v0"`), so both can coexist while the party service
moves over.

## Appliance profile (`avrana.appliance/v0`)

- **`providers[]`:** `{id, kind: runtime|input|presentation, offers[], status: live|experiment|planned,
  adapter: "module:Class"|null, implementation}`.
  - The runtime capabilities of this box are the `offers` of its `live` providers.
    `--include-experiments` also counts `experiment` providers, but only for a lab catalog.
  - An `adapter` must import, and its `info` must match (tested).
- **`installed[]`:** the grants, `{game, entry, health?, tier: builtin|trusted|community,
  permissions_granted[]}`.
  - The entry is a same-origin path ending in `/`, outside `/party/`, `/admin/` and `/shared/`.
  - A grant can't give a permission its contract didn't request.
  - An installed game must be presentable to players on this box.
- **`collections[]`:** hubs that are not games themselves (LAN Games at `/`).

## Seat evaluation (Capability Engine v0)

`evaluate_seat(game, caps, role)` (Python), mirrored by `evaluateSeat` (JS).

1. The candidates are this game's presentations for `role` that the appliance can serve.
2. The **first** candidate with no required device capability observed as `no` wins.
3. A required capability that is `unknown` or `partial` keeps the presentation, but marks it
   `limited`. An optional capability that is `no` is a `degraded` entry, also `limited`.
4. If no player presentation fits and the game's `fallback` is `spectate`, the seat is evaluated as
   a spectator. The outcome is `watch`, and `missing` still explains why.
5. Otherwise the outcome is `unavailable`, with `blockedBy` set to `device`, `runtime` or `role`.
   `missing` is the candidate with the fewest gaps.

The result is `{role, outcome: ready|limited|watch|unavailable, seatRole, presentation, method, blockedBy,
missing[], unverified[], partial[], degraded[]}`. `plan_party(game, seats)` evaluates each seat
independently. A tested property holds: adding a weak seat never changes another seat's result.

## Provider catalog metadata

The default catalog also normalizes `catalogs/lan-games.json` through
`avrana/contracts/lan_catalog.py`. Its public donor snapshot includes a source
commit; hidden/template titles and live/personal data are excluded. Each title
passes the same Game Contract v0 validator. Installation paths/permissions remain
in the appliance profile. `net.avrana.catalog` supplies display metadata
(provider, legacySlug, icon/category, experimental status and validation warning),
never grants. PS1 contracts record authoritative experiment metadata under
`net.avrana.ps1`; no installed grant or executable runtime is imported.
See `docs/design/LAN-GAMES-ASSIMILATION.md`.
