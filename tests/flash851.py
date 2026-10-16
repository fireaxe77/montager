"""V8.5.1 tool: re-plan the effects of saved montage plans (plan.json of real renders) with the CURRENT assign_extra_fx (same seed, same song feel) and print the flash line.
python tests/flash851.py <plan.json> [more plan.json ...]   -> per plan: style, length, kills, flash count and the budget; writes docs/proof_v851/flash_report.txt"""
import json
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
ROOT = _root.find_root()
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")
import montage as M                                                                           # noqa: E402

lines = []
for f in sys.argv[1:]:
    plan = json.load(open(f, encoding="utf-8"))
    for t in plan["takes"]:
        t.pop("xfx", None)
    notes = []
    M.assign_extra_fx(plan, plan["game"], plan.get("seed", 5), notes, energy=(plan.get("song") or {}).get("energy") or 0.7)
    nk = sum(len(t.get("kills_out") or []) for t in plan["takes"])
    fl = [x for t in plan["takes"] for x in t.get("xfx", []) if x["k"] == "flash"]
    gps = sorted(t["out_start"] + x["p"] for t in plan["takes"] for x in t.get("xfx", []) if x["k"] == "flash")
    gap = min((b - a for a, b in zip(gps, gps[1:])), default=99)
    w = next((n for n in notes if "white flash" in n), "")
    lines.append(f"{Path(f).name.encode('ascii', 'replace').decode()}: game {plan['game']}, style {plan.get('recipe')}, seed {plan.get('seed')}, {plan['duration']:.0f} s, {nk} kills -> {len(fl)} flashes (min gap {gap:.1f} s)\n   {w}")
txt = "\n".join(lines)
print(txt)
Path(ROOT / "docs" / "proof_v851" / "flash_report.txt").write_text(txt + "\n", encoding="utf-8")
