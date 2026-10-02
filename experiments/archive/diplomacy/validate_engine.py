"""Validate the diplomacy/diplomacy engine on the Avrana Party Pi.

Isolated spike: run with the spike venv, e.g.
    ~/avrana-lab/diplomacy-spike/.venv/bin/python validate_engine.py
Prints a JSON report. Touches nothing outside the current directory.
"""
import json
import platform
import statistics
import time

import diplomacy
from diplomacy import Game
from diplomacy.utils.export import from_saved_game_format, to_saved_game_format

report = {"python": platform.python_version(), "machine": platform.machine(),
          "engine_version": getattr(diplomacy, "__version__", "?")}
checks = {}


def timed(fn, n=5):
    samples = []
    for _ in range(n):
        t = time.perf_counter()
        out = fn()
        samples.append((time.perf_counter() - t) * 1000)
    return out, round(statistics.median(samples), 1), round(max(samples), 1)


# 1-2. Create a standard game; the seven powers.
g, t_new, t_new_max = timed(lambda: Game(map_name="standard"))
checks["1_create"] = g.get_current_phase() == "S1901M"
checks["2_seven_powers"] = sorted(g.powers) == ["AUSTRIA", "ENGLAND", "FRANCE", "GERMANY",
                                                "ITALY", "RUSSIA", "TURKEY"]
report["phase_at_start"] = g.get_current_phase()

# 3. Legal orders.
possible, t_poss, t_poss_max = timed(g.get_all_possible_orders)
fr_locs = g.get_orderable_locations("FRANCE")
report["france_orderable"] = fr_locs
report["legal_orders_per_france_unit"] = {loc: len(possible[loc]) for loc in fr_locs}
checks["3_legal_orders"] = all(len(possible[loc]) > 1 for loc in fr_locs)

# 4-6. Valid Spring 1901 orders incl. a supported move (France->BUR) vs a bounce (Germany MUN->BUR).
orders = {
    "ENGLAND": ["F LON - NTH", "F EDI - NWG", "A LVP - YOR"],
    "FRANCE": ["A PAR - BUR", "A MAR S A PAR - BUR", "F BRE - MAO"],
    "GERMANY": ["A MUN - BUR", "A BER - KIE", "F KIE - DEN"],
    "ITALY": ["A VEN H", "F NAP - ION", "A ROM - APU"],
    "AUSTRIA": ["A VIE - GAL", "F TRI - ALB", "A BUD - SER"],
    "RUSSIA": ["A MOS - UKR", "F SEV - BLA", "A WAR - GAL", "F STP/SC - BOT"],
    "TURKEY": ["F ANK - BLA", "A CON - BUL", "A SMY - ARM"],
}
for power, o in orders.items():
    g.set_orders(power, o)
checks["4_orders_accepted"] = all(len(g.get_orders(p)) == len(o) for p, o in orders.items())
t = time.perf_counter()
g.process()
t_proc = round((time.perf_counter() - t) * 1000, 1)
res = g.get_phase_history()[-1].results
report["spring_results_nonempty"] = {k: [str(x) for x in v] for k, v in res.items() if v}
checks["5_adjudicated"] = g.get_current_phase() == "F1901M"
checks["6_support_beats_bounce"] = ("A BUR" in g.get_units("FRANCE")
                                    and "A MUN" in g.get_units("GERMANY")
                                    and [str(x) for x in res.get("A MUN", [])] == ["bounce"])
checks["6b_mutual_bounce_BLA"] = ([str(x) for x in res.get("F SEV", [])] == ["bounce"]
                                  and [str(x) for x in res.get("F ANK", [])] == ["bounce"])

# 7. Save / restore round trip.
saved = to_saved_game_format(g)
blob = json.dumps(saved)
g2 = from_saved_game_format(json.loads(blob))
checks["7_save_restore"] = (g2.get_current_phase() == g.get_current_phase()
                            and g2.get_units() == g.get_units()
                            and g2.get_centers() == g.get_centers())
report["saved_game_bytes"] = len(blob)

# 8. SVG render (with and without orders).
svg, t_render, t_render_max = timed(lambda: g.render(incl_orders=False))
checks["8_svg_render"] = svg.lstrip().startswith("<?xml") or "<svg" in svg[:500]
report["svg_bytes"] = len(svg)

# 10. Invalid orders: what does the engine do with each kind?
inv = Game(map_name="standard")
probes = {
    "non_adjacent_move": ("FRANCE", ["A PAR - MUN"]),
    "other_powers_unit": ("FRANCE", ["A MUN - BUR"]),
    "no_unit_there": ("FRANCE", ["A GAS - SPA"]),
    "garbage_syntax": ("FRANCE", ["this is not an order"]),
    "fleet_inland": ("FRANCE", ["F BRE - PAR"]),
}
invalid = {}
inv.set_orders("FRANCE", ["A PAR H"])
for name, (power, o) in probes.items():
    before = list(inv.get_orders(power))
    raised = None
    try:
        inv.set_orders(power, o)
    except Exception as exc:  # noqa: BLE001 - we want to record any behaviour
        raised = f"{type(exc).__name__}: {exc}"
    invalid[name] = {"raised": raised, "orders_before": before,
                     "orders_after": list(inv.get_orders(power)),
                     "engine_error_attr": [str(e) for e in getattr(inv, "error", [])][-2:]}
    inv.clear_orders(power)
    inv.set_orders(power, ["A PAR H"])
report["invalid_orders"] = invalid
checks["10_invalid_orders_never_accepted"] = all(
    v["orders_after"] == v["orders_before"] for v in invalid.values())

# Extra: retreat + build phases on a constructed position.
r = Game(map_name="standard")
r.set_units("FRANCE", ["A BUR", "A PAR", "F BRE"], reset=True)
r.set_units("GERMANY", ["A MUN", "A RUH", "F KIE"], reset=True)
r.set_orders("FRANCE", ["A BUR H", "A PAR H", "F BRE H"])
r.set_orders("GERMANY", ["A MUN - BUR", "A RUH S A MUN - BUR", "F KIE - DEN"])
r.process()
report["retreat_phase"] = r.get_current_phase()
report["retreat_orderable_france"] = r.get_orderable_locations("FRANCE")
report["retreat_options"] = sorted(r.get_all_possible_orders().get("BUR", []))
r.set_orders("FRANCE", ["A BUR R GAS"])
r.process()
checks["extra_retreat"] = report["retreat_phase"] == "S1901R" and "A GAS" in r.get_units("FRANCE")
# Fall: hold everything, Germany F DEN holds -> gains DEN at winter.
for p in ("FRANCE", "GERMANY"):
    r.set_orders(p, [f"{u} H" for u in r.get_units(p)])
r.process()
report["winter_phase"] = r.get_current_phase()
report["germany_centers"] = r.get_centers("GERMANY")
report["germany_build_options"] = sorted(o for loc, os_ in r.get_all_possible_orders().items()
                                         for o in os_ if " B" in o and loc in ("BER", "KIE", "MUN"))
r.set_orders("GERMANY", ["A BER B"])
r.process()
checks["extra_build"] = "A BER" in r.get_units("GERMANY")
report["after_build_phase"] = r.get_current_phase()

report["timings_ms_median_max"] = {
    "new_game": [t_new, t_new_max], "all_possible_orders": [t_poss, t_poss_max],
    "process_spring_1901": [t_proc], "render_svg": [t_render, t_render_max]}
report["checks"] = checks
report["all_passed"] = all(checks.values())
print(json.dumps(report, indent=1, default=str))
