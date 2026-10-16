"""V8.6.2 fast tests (no render): python tests/test_v862.py"""
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

FAILS = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {info}" if info else ""))
    if not ok:
        FAILS.append(name)


check("version", M.APP_VERSION == "V8.6.2", M.APP_VERSION)
# 3: no music dip
dm = lambda t: {"t": t, "s": 1.45, "variant": "punch", "dip_s": 0.22, "boom_f1": 52, "boom_f0": 130, "boom_r": 26, "boom_dec": 6.5, "boom_db": -2, "lift_db": 4, "breath": 0.4}
dip, lift, hits = M.drop_audio_filters([dm(37.7), dm(128.1)])
check("drop moment: the music is never touched", dip == "1" and len(hits) == 2 and "clip(" in lift)
# 2: sky grade / animation numbers
g = M.sky_grade_v2(M.SKY_PALETTE["ember"], "dark")
check("sky: only multiplicative darkening (no lift)", all(g[k]["y_mul"] <= 1.0 for k in ("steady", "dark", "surge")))
check("sky: opacity 90 - 95 %", 0.90 <= M.SKY_OPACITY <= 0.95)
a, b = M.sky_anim_params(0.9, 160), M.sky_anim_params(0.2, 80)
check("sky: faster / stronger on an energetic song", a["drift"] > b["drift"] and a["depth"] > b["depth"] and a["surge"] > b["surge"])
fld = list(M.sky_cloud_field(96, 54, 40, 60, a["drift"], a["period"], 5))
mv = float(np.mean([np.abs(fld[i + 1] - fld[i]).mean() for i in range(39)]))
check("sky: the clouds move (density changes between frames)", mv > 0.004, f"mean change {mv:.4f}")
beats = M.sky_take_beats({"song": {"path": "x"}}, {"out_start": 0, "dur": 3}, {"p": 1.0})
check("sky: beats helper survives a missing song map", beats == [])
# 1: walls are not sky
W, H = 768, 432
wall = np.zeros((H, W, 3), np.uint8)
wall[:] = (70, 100, 150)                                   # a smooth dark blue wall (Lab L about 40)
check("a smooth dark blue wall is not a sky", not M.sky_eyedrop(wall)[1]["ok"], M.sky_eyedrop(wall)[1]["why"])
sky = np.zeros((H, W, 3), np.uint8)
sky[:] = (150, 200, 250)
sky[150:] = (90, 80, 70)
check("a bright blue sky over a ground is a sky", M.sky_eyedrop(sky)[1]["ok"])
# 6: speed ramp: slow - fast - slow, always
for kt in (0.6, None):
    r = M.cs2_ramp_speeds(150, M.SLOW_V0, 4.0, kt)
    v = r[0] if r else []
    check(f"ramp ({'knife' if kt else 'no knife'}): slow, up, down, slow ending, release", bool(r) and v[0] <= 0.55 and max(v[6:40]) >= 0.85 and min(v[40:90]) <= 0.55 and v[-1] >= 0.99, str(r[2] if r else None))
    check(f"ramp ({'knife' if kt else 'no knife'}): smooth", bool(r) and max(abs(x - y) for x, y in zip(v, v[1:])) < 0.12)
check("ramp: a short take (30 frames) still gets the phases or the plain release", M.cs2_ramp_speeds(30, M.SLOW_V0, 1.0, None) is None or len(M.cs2_ramp_speeds(30, M.SLOW_V0, 1.0, None)[0]) == 30)
# 7: deathmatch rule
check("deathmatch: two signals needed", M.DM_MIN_SIGNALS == 2)
# 8: log collapse
t = "\n".join(["head"] + [f"NOTE     dead air: clip {i}" for i in range(30)] + ["tail"])
c = M.collapse_log(t)
check("log: a block of 30 lines is collapsed to a count", c.count("\n") < 8 and "28 more" in c and c.startswith("head") and c.endswith("tail"), c.replace("\n", " / ")[:120])
check("log: short messages unchanged", M.collapse_log("a\nb\nc") == "a\nb\nc")
check("stall rule exists", M.STALL_MAX_SHARE <= 0.1)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
