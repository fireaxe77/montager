r"""V9.5.2 short test render of one take's sky recolour, before (SKY_EXTEND_ON off) and after, and frames at the kill + dt: python tests/skyrender952.py <plan.json> <take> <out dir> [dt s ...]
(a preview slice of ~20 s starting at that take; MONTAGER_DATA = a COPY of montage_data)"""
import json
import subprocess
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import montage as M                                                                           # noqa: E402

planp, tn, outd = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
dts = [float(v) for v in sys.argv[4:]] or [0.15, 0.4]
outd.mkdir(parents=True, exist_ok=True)
for variant in ("before", "after"):
    M.SKY_EXTEND_ON[0] = variant == "after"
    plan = json.load(open(planp, encoding="utf-8"))
    SKY_KEYS = ("ok", "mask", "grade", "cov", "anim", "beats", "fam", "pattern", "mask_fmt", "frames_src", "horizon", "sky_cut")
    for t in plan["takes"]:
        for x in t.get("xfx") or []:
            if x.get("k") == "sky":
                for k in SKY_KEYS:
                    x.pop(k, None)
    t = plan["takes"][tn - 1]
    plan["song"]["drop_t"] = t["out_start"] + 8.0 + (7.0 if plan.get("intro") else 0.0)
    plan["intro"] = None
    plan["song"]["drop_t"] = t["out_start"] + 8.05
    out = outd / f"take{tn}_{variant}.mp4"
    M.render_plan(plan, out, M.load_config(), preview=True)
    sky = next(x for x in t["xfx"] if x.get("k") == "sky")
    for dt in dts:
        ts = (sky["p"] + dt)
        png = outd / f"take{tn}_{variant}_{dt:.2f}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ts:.3f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=960:-1", str(png)], check=True)
        print(variant, dt, png)
