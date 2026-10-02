# diplomacy/diplomacy on the Avrana Party Pi: validation (2026-09-22)

> **ABANDONED EXPERIMENT (2026-09-23).** Classic map-based Diplomacy is **not** the
> Avrana target; it was pursued from a misunderstanding. The target is a Coup-inspired
> bluffing card game (see `docs/ROADMAP.md`). This record is kept only for reference; don't
> build on it.

**Result: works.** The engine runs on the Pi and adjudicates correctly. It is fast enough
that performance is a non-issue for a 7-player game.

## Setup (isolated)

- Host `party`: Raspberry Pi 4 Model B Rev 1.5, Debian 13 (trixie), **Python 3.13.5,
  aarch64**.
- Directory `~/avrana-lab/diplomacy-spike/` with its own venv. It is outside the repo and
  touches no live service, venv, nginx, dnsmasq, systemd or networking.
- Engine: `https://github.com/diplomacy/diplomacy` pinned at **`df1d089`**
  (2020-06-01, the tip of `main`; package version 1.1.2). Installed with
  `pip install ./engine-src` in about 32 s.
- Dependencies resolved: tornado 6.5.10, ujson 6.0.0, bcrypt 5.0.0, coloredlogs 15.0.1,
  tqdm 4.70.1, all with prebuilt arm64 wheels.
- Script: `experiments/archive/diplomacy/validate_engine.py`. Raw output:
  `experiments/archive/diplomacy/pi-validation-2026-09-22.json`.

## Checks (12/12 pass)

| # | Check | Result |
|---|---|---|
| 1 | Create standard game | `S1901M` |
| 2 | Seven powers | AUS ENG FRA GER ITA RUS TUR |
| 3 | Legal orders | e.g. France BRE 9, MAR 10, PAR 11 options from `get_all_possible_orders()` |
| 4 | Submit valid Spring 1901 orders (all 7 powers) | all accepted (`get_orders` echoes them) |
| 5 | Adjudicate | → `F1901M` |
| 6 | Support vs bounce | `A PAR - BUR` + `A MAR S A PAR - BUR` beats `A MUN - BUR` (MUN: *bounce*); F SEV / F ANK → BLA mutual bounce |
| 7 | Save/restore | `to_saved_game_format` → JSON (4,695 B) → restore; phase, units and centres identical |
| 8 | SVG render | 104,249 B (`render(incl_orders=False)`) |
| 10 | Invalid orders | never accepted (details below) |
| + | Retreat phase | constructed dislodgement → `S1901R`; options `A BUR R BEL/GAS/MAR/PIC`, `A BUR D`; `R GAS` executed |
| + | Build phase | Germany takes DEN → `W1901A`; build options `A/F BER`, `A/F KIE`, `A MUN`; `A BER B` executed → `S1902M` |

**The engine's own test suites on the Pi:** 160 DATC tests pass (9.8 s), and **521 tests
pass in total** (DATC, DATC-no-check, DATC-no-expand, game, map).

## Timings on the Pi (median of 5 unless noted)

| Operation | ms |
|---|---|
| `Game()` new game | 2.9 (first ever: ~320, loading the map) |
| `get_all_possible_orders()` | 3.5 |
| `process()` Spring 1901, 7 powers | 3.8 (single run) |
| `render()` SVG | 76.5 (max 218) |

## Invalid orders: exact behaviour

With `set_orders(power, [...])` after a valid `A PAR H`:

| Probe | Raised? | Orders after | `game.error` message |
|---|---|---|---|
| non-adjacent `A PAR - MUN` | no | unchanged (`A PAR H`) | `CONVOYING UNIT MUST REACH COAST` (misleading: the engine tried to read it as a convoy) |
| other power's unit `A MUN - BUR` | no | unchanged | `UNORDERABLE UNIT` |
| no unit there `A GAS - SPA` | no | unchanged | `UNORDERABLE UNIT` |
| fleet inland `F BRE - PAR` | no | unchanged | `CONVOYING UNIT MUST REACH COAST` |
| free-text garbage | **`IndexError`** | unchanged | `UNKNOWN POWER OR PLACENAME` |

**Design consequences:**
1. The phone offers **only** orders from `get_all_possible_orders()`, keyed by the player's
   own orderable locations.
2. The server validates each submitted order *by membership* in that list before calling
   `set_orders`, and never passes free text through.
3. Wrap engine calls in `try/except`. The service must never crash on input.
4. After every submission, re-read `get_orders(power)` and show **that** back as the
   confirmed order set.
5. Don't surface the engine's error strings to players verbatim.

**Consequences for the "every phone is a full client" model** (ROADMAP decisions 8–9):

6. `render(incl_orders=False)` draws the **public** board only: units, centres and map.
   It's safe to send to every phone, at ~80 ms / ~100 KB per phase.
   **`render(incl_orders=True)` includes every power's pending orders and must never be
   sent to any client before the phase is adjudicated.**
7. Per-player masking happens server-side. A client's payload is built from public state
   plus `get_orders(<its own power>)` only. Never serialise `get_orders()` (all powers) or
   the full `to_saved_game_format` blob to a client mid-phase.
8. Readiness (`set_wait`) can be public; order contents cannot.

## Compatibility notes

- One deprecation warning: `datetime.utcfromtimestamp()` at `diplomacy/utils/common.py:32`.
  It will break on a future Python and is a trivial patch if we vendor the engine.
- `diplomacy.__version__` is not exposed; the installed package reports 1.1.2.
- The engine's network server (Tornado, 88 `gen.coroutine` uses) and React web UI were not
  used or needed.

## Reproduce

```sh
ssh party
cd ~/avrana-lab/diplomacy-spike
.venv/bin/python validate_engine.py > pi-validation.json   # all_passed: true
cd engine-src && ../.venv/bin/python -m pytest -q diplomacy/tests/test_datc.py
```
