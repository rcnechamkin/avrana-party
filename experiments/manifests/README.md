# Game capability manifest v0 — experiment (not production)

The smallest useful implementation of the manifest drafted in `docs/design/GAME-INTEGRATION.md` §1.
A manifest says what a game **is and can do**. It never says how to launch it (that is launch data,
e.g. a PS1 title profile in `ps1/titles/*.json`) and it **grants nothing** (grants are the
appliance's decision; not built). Stdlib only; `manifest.py` is the validator.

```bash
python experiments/manifests/test_manifest.py      # 10 tests
```

## Sources

| Source | For | Rule |
|---|---|---|
| `builtin/*.json` | runtimes with no registry: the arcade, PS1 titles | hand-written; file name = id |
| games server `GET /api/games` | LAN Games titles (incl. BLUFF) | **derived, never hand-written** (`derive_lan`); hidden titles skipped; titles without player counts reported, not guessed |
| `lan-overlay.json` | the two things the LAN registry can't express | only `private_player_ui` and `accessibility` per id |

The dev front door (`../party-service/front.py --upstream …`) builds the party's game catalog from
the upstream's own `/api/games` this way, so the party lists exactly what that games server serves.

## Fields (v0)

Only fields with at least two consumers today. `players` = how many people can take part;
`input.slots` = how many seats the party deals (the catalog uses slots when present).

| Field | Values | Default |
|---|---|---|
| `manifest` | `0` | required |
| `id` | `^[a-z][a-z0-9_-]{0,39}$`, not `home`/`party`/`admin` | required |
| `name` | 1–60 printable characters | required |
| `kind` | `native` \| `emulated` \| `other` | required |
| `runtime.type` | `lan_games_module` \| `emulator_profile` \| `external` | required |
| `runtime.start` | `always_on` \| `service` (a launch step that reports *ready*) | `always_on` for LAN modules; required otherwise |
| `runtime.profile` | PS1 title-profile id | required for `emulator_profile`, forbidden otherwise |
| `runtime.entry` | same-origin path like `/games/x/`, or `null` = not reachable on the party origin yet | required |
| `players` | `{min, max}`, 1–32 | required |
| `screen` | `no_tv_needed` \| `tv_optional` \| `tv_required` | required |
| `input` | `{model: browser_native}` or `{model: controller_slots\|hotseat, slots: 1–4}` | required |
| `late_join` | `spectator_only` \| `next_round` \| `supported` | `spectator_only` |
| `spectators` | `none` \| `watch` | `watch` |
| `shared_video`, `private_player_ui` | booleans | `false` |
| `personal_viewports` | `null` only (the format is OPEN) | `null` |
| `accessibility` | `color_independent`, `audio_required`, `text_scalable`, `reduced_motion_respected`, `timing_pressure` — each `true` \| `false` \| `"unknown"` | all `"unknown"` |

Accessibility values are **display-only** in v0: nothing filters or blocks games on them, and
`"unknown"` is always allowed so no author has to guess. Their meanings are in
`docs/design/ACCESSIBILITY.md` (branch `docs/party-platform`).

## What the validator rejects

Duplicate JSON keys, NaN/Infinity, unknown keys at any level, missing required keys, wrong types
(including `true` where an integer belongs), bad enum values, `min > max`, slots on a
`browser_native` game or missing on a slotted one, `slots > players.max`, a native game with an
emulator profile or an emulated LAN module, a non-null `personal_viewports`, non-tri-state
accessibility values, and any `entry` that is not a plain same-origin path ending in `/`
(no scheme or host, no `..`, `?`, `#`, `%`, `\`, upper case, or dot-segments) or that uses a
reserved prefix (`/party/`, `/admin/`, `/shared/`). The file name must equal the id; catalog ids
must be unique. PS1: `cross_check_ps1` requires `id == "ps1-" + profile`, `input.slots ==
stream_slots`, hot-seat ⇒ one slot, and a manifest for every profile (checked against the real
`ps1/titles/*.json` on branch `experiment/ps1-title-profiles`: they agree).

## Decisions taken here (experiment-level; flagged for the docs)

- `runtime.entry` exists only for built-in and derived manifests. For **installed** games the grant
  will assign the path (GAME-INSTALLATION.md) — the design docs say "no URL in the manifest"; this
  is the reconciliation.
- `name`, not `title` (the party service and PS1 profiles already say `name`).
- LAN titles are `late_join: spectator_only` (players lock at the countdown) and `screen` is either
  `tv_required` or `no_tv_needed` (the registry's `tv` flag cannot say "optional").

## Still open (owner decisions; not decided here)

- `ps1-bomberman` declares `late_join: supported` because that is what the code does today (fills a
  free slot); the GAME-INTEGRATION §1 example says `spectator_only`. PARTY-PLATFORM §16 lists it.
- Hot-seat: `ps1-worms` is `players 1–4` on **one** slot; how the party hands one controller around
  is not modelled.

## Not built (deliberately)

Teams, chat, results, stats, achievements, session length, `spectators: participate`, resources,
permissions, SDK versions, grants and trust tiers, an install folder scanner, hashes or signing,
the Personal Viewport format, icons/art/blurbs (they stay in the hub), a JSON-Schema dependency,
and anything that filters games by accessibility.
