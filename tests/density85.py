"""V8.5 tool: effect density of the V8.4.4 plan rules against the current ones on the SAME saved plans (montage plan.json files of earlier renders): the effects are stripped from every take and
assigned again by both versions' assign_extra_fx (same seeds). Prints per version: kill effects (flash + colour split + punch), dressed kills (a kill with at least one of them), cut effects
(settle / mirror), drop effects, sky candidates, per plan and the average per 100 s of montage.
python tests/density85.py <old montage.py> <plans folder or glob> [out.txt]    (old = `git show 5f48bdf:montage.py > old.py`, the V8.4.4 file)"""
import collections
import glob
import importlib.util
import json
import os
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
ROOT = _root.find_root()
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, str(path))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def measure(M, plan_file, seed):
    plan = json.load(open(plan_file, encoding="utf-8"))
    for t in plan["takes"]:
        t.pop("xfx", None)
    M.assign_extra_fx(plan, plan["game"], seed, [], energy=(plan.get("song") or {}).get("energy") or 0.7)
    c = collections.Counter(x["k"] for t in plan["takes"] for x in t.get("xfx", []))
    kills = [(ti, k) for ti, t in enumerate(plan["takes"]) for k in (t.get("kills_out") or [])]
    kfx = ("rgb", "punch", "flash")
    dressed = sum(1 for ti, k in kills if any(x["k"] in kfx and abs(x.get("p", -9) - k) < 0.06 for x in plan["takes"][ti].get("xfx", [])))
    return {"dur": plan["duration"], "kills": len(kills), "dressed": dressed, "kill_fx": sum(c[k] for k in kfx), "flash": c["flash"], "cut_fx": c["settle"] + c["mirror"],
            "drop_fx": c["rise"] + c["after"] + c["breath"], "sky_cand": c["sky"]}


if __name__ == "__main__":
    old = load(sys.argv[1], "m_old")
    new = load(os.environ.get("DENSITY_NEW") or ROOT / "montage.py", "m_new")
    files = sorted(glob.glob(sys.argv[2]) if not os.path.isdir(sys.argv[2]) else glob.glob(str(Path(sys.argv[2]) / "*.plan.json")))
    lines, tot = [], {"old": collections.Counter(), "new": collections.Counter()}
    for f in files:
        for seed in (3, 11, 29):
            for tag, M in (("old", old), ("new", new)):
                try:
                    r = measure(M, f, seed)
                except Exception as ex:                                                       # noqa: BLE001
                    lines.append(f"{os.path.basename(f)} seed {seed} {tag}: {type(ex).__name__}: {ex}")
                    break
                for k, v in r.items():
                    tot[tag][k] += v
    for tag, name in (("old", "V8.4.4"), ("new", "now")):
        t = tot[tag]
        d = max(1.0, t["dur"]) / 100.0
        lines.append(f"{name}: per 100 s of montage: kill effects {t['kill_fx'] / d:.1f} (flash {t['flash'] / d:.1f}), dressed kills {t['dressed'] / d:.1f} = {100.0 * t['dressed'] / max(1, t['kills']):.0f}% of the kills, "
                     f"cut effects {t['cut_fx'] / d:.1f}, drop effects {t['drop_fx'] / d:.1f}, sky candidates {t['sky_cand'] / d:.1f}  ({len(files)} plans x 3 seeds)")
    txt = "\n".join(lines)
    print(txt)
    if len(sys.argv) > 3:
        Path(sys.argv[3]).write_text(txt + "\n", encoding="utf-8")
