#!/usr/bin/env python3
"""One-command local test gate, for when GitHub Actions cannot run (billing).

    python tools/acceptance/local_gate.py --games <Games checkout> [--games-python <python with Games deps>]
                                          [--games-deployed <Games checkout at the Pi's SHA>] [--chromium] [--quick]

Runs, in order, and stops at nothing (every step is reported): Python unit suite, repo-check, the
Party/Games contract check (against each Games checkout given), the four-player journey (against
each), and with --chromium the Party multi-client browser suite. Writes gate-<stamp>.md/.json under
test-results/acceptance/ with the Party and Games SHAs. Exit 0 only if every step passed.
This is local evidence (Tier 1 to 2); it is not CI and not a physical result.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    r = subprocess.run(["git", "-C", str(path), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or "unknown"


def step(rows, name, cmd, cwd=ROOT, env=None, timeout=1800):
    t0 = time.time()
    print(f"==> {name}", flush=True)
    try:
        p = subprocess.run(cmd, cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True, timeout=timeout)
        ok, tail = p.returncode == 0, (p.stdout + p.stderr).strip().splitlines()[-3:]
    except subprocess.TimeoutExpired:
        ok, tail = False, ["timed out"]
    rows.append({"step": name, "status": "PASS" if ok else "FAIL", "seconds": round(time.time() - t0),
                 "tail": " | ".join(tail)[:300]})
    print(f"    {rows[-1]['status']} ({rows[-1]['seconds']} s)", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--games", required=True)
    ap.add_argument("--games-python", default=sys.executable)
    ap.add_argument("--games-deployed", help="Games checkout at the SHA running on the Pi")
    ap.add_argument("--chromium", action="store_true", help="also run the Party multi-client browser suite")
    ap.add_argument("--quick", action="store_true", help="skip the unit suite and repo-check")
    ap.add_argument("--out", default=str(ROOT / "test-results" / "acceptance"))
    args = ap.parse_args(argv)
    py = sys.executable
    games = [("Games", args.games)] + ([("deployed Games", args.games_deployed)] if args.games_deployed else [])
    rows = []
    if not args.quick:
        step(rows, "unit suite", [py, "-m", "unittest", "discover", "-s", "tests/unit"], env={"AVRANA_PYTHON": py})
        step(rows, "repo-check", [py, "-m", "unittest", "tests.unit.test_repo_check"], env={"AVRANA_PYTHON": py})
    for label, g in games:
        step(rows, f"contract vs {label}", [py, "tools/contract_check.py", "--party", ".", "--games", g])
        step(rows, f"four-player journey vs {label}",
             [args.games_python, "tools/acceptance/four_player_journey.py", "--games", g, "--out", args.out])
    if args.chromium:
        npx = "npx.cmd" if sys.platform == "win32" else "npx"
        step(rows, "Party multi-client Chromium suite", [npx, "playwright", "test", "-c", "playwright.party.config.ts",
             "--reporter=line"], env={"AVRANA_PYTHON": py}, timeout=3600)
    meta = {"party_sha": sha(ROOT), "games_sha": sha(args.games),
            "games_deployed_sha": sha(args.games_deployed) if args.games_deployed else None,
            "when_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "platform": sys.platform,
            "level": "local (Tier 1 to 2); not CI, not physical"}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (out / f"gate-{stamp}.json").write_text(json.dumps({"meta": meta, "steps": rows}, indent=2))
    md = ["# Local gate", "", *[f"- {k}: `{v}`" for k, v in meta.items()], "",
          "| Step | Result | Seconds | Last lines |", "|---|---|---|---|",
          *[f"| {r['step']} | {r['status']} | {r['seconds']} | {r['tail'].replace('|', '/')} |" for r in rows]]
    (out / f"gate-{stamp}.md").write_text("\n".join(md) + "\n")
    bad = [r for r in rows if r["status"] != "PASS"]
    print(f"\n{len(rows) - len(bad)} passed, {len(bad)} failed -> {out / f'gate-{stamp}.md'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
