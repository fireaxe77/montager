"""V8.5.1 fast tests (no render): python tests/test_v851.py"""
import glob
import json
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import montage as M                                                                           # noqa: E402

FAILS = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {info}" if info else ""))
    if not ok:
        FAILS.append(name)


check("version", M.APP_VERSION == "V8.5.1", M.APP_VERSION)
for f in sorted(glob.glob("E:/Movies/Montages/*/logs/*V8.5_*.plan.json"))[:3]:
    plan = json.load(open(f, encoding="utf-8"))
    for t in plan["takes"]:
        t.pop("xfx", None)
    M.assign_extra_fx(plan, plan["game"], plan.get("seed", 5), [], energy=0.8)
    fl = sorted(t["out_start"] + x["p"] for t in plan["takes"] for x in t.get("xfx", []) if x["k"] == "flash")
    budget = max(1, round(plan["duration"] / M.FLASH_PER_S))
    check(f"flash budget {Path(f).name[:3]}", len(fl) <= budget and len(fl) >= budget - 3, f"{len(fl)} flashes, budget {budget} for {plan['duration']:.0f} s")
    check("flash spacing >= 3.5 s", all(b - a >= 3.45 for a, b in zip(fl, fl[1:])))
    sk = [x for t in plan["takes"] for x in t.get("xfx", []) if x["k"] == "sky"]
    check("sky window = kill frame .. end of take", all(abs(x["t0"] - x["p"]) < 1e-3 and x["t1"] > x["t0"] for x in sk), f"{len(sk)} candidates")
check("sky fade-in at most 3 frames", M.SKY_EASE_IN <= 3 / 60 + 1e-9)
check("sky never below the middle", M.SKY_MAX_ROW <= 0.5)
check("sky luminance kept (opacity 1, no veil)", M.SKY_OPACITY == 1.0)
g = M.sky_grade(M.SKY_PALETTE["amber"], 150.0, M.sky_gradient(M.SKY_PALETTE["amber"], "sunset"), "sunset")
check("grade keeps luminance", g["top"]["y_mul"] == 1.0 and g["hor"]["y_mul"] == 1.0 and g["top"]["y_add"] == 0.0)
r = M.sky_ranked("hype", 0.8, 150)[0]
check("hype / aggressive: orange first", r[0] == "amber" and M.sky_ranked("aggressive", 0.9, 150)[0][0] == "amber")
check("scene hue never swaps the orange", M.sky_colour_for(r, 0x98C8F0, 30.0)[0] == "amber")
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
