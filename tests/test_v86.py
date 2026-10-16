"""V8.6 fast tests (no render): python tests/test_v86.py"""
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


check("version", M.APP_VERSION == "V8.6", M.APP_VERSION)
dm = lambda t: {"t": t, "s": 1.45, "variant": "punch", "dip_s": 0.22, "dip_db": 8, "boom_f1": 52, "boom_f0": 130, "boom_r": 26, "boom_dec": 6.5, "boom_db": -2, "lift_db": 4, "duck_db": 5, "breath": 0.4}
dip = M.drop_audio_filters([dm(37.7), dm(128.1)])[0]
check("music dip: no exp() of a growing number", "max(0,t-" in dip and dip.count("exp(") == dip.count("exp(-7*max(0,"))
# ramp speeds
sp = M.cs2_ramp_speeds(150, M.SLOW_V0, 4.0, 0.65)
check("ramp: with knife", sp is not None and len(sp[0]) == 150 and "second slow-down" in sp[2], str(sp[2] if sp else None))
if sp:
    v = sp[0]
    check("ramp: smooth (no step above 0.12 between frames)", max(abs(a - b) for a, b in zip(v, v[1:])) < 0.12, f"max step {max(abs(a - b) for a, b in zip(v, v[1:])):.3f}")
    check("ramp: slow at the kill, up, down, release", v[0] <= 0.55 and max(v[6:30]) >= 0.85 and min(v[40:70]) <= 0.55 and v[-1] >= 0.99, f"{v[0]:.2f} {max(v[6:30]):.2f} {min(v[40:70]):.2f} {v[-1]:.2f}")
    check("ramp: footage after the kill is enough", sum(v) / 60 <= 4.0 - 0.017, f"{sum(v) / 60:.2f} s of footage")
sp2 = M.cs2_ramp_speeds(150, M.SLOW_V0, 4.0, None)
check("ramp: no knife = no second slow-down", sp2 is not None and "no knife-out" in sp2[2] and max(abs(a - b) for a, b in zip(sp2[0], sp2[0][1:])) < 0.12)
check("ramp: too little footage = None or lower v_hi", M.cs2_ramp_speeds(150, M.SLOW_V0, 1.2, 0.65) is None or M.cs2_ramp_speeds(150, M.SLOW_V0, 1.2, 0.65)[1] < 0.9)
# sky v2
check("sky: impact in <= 3 frames", M.SKY_IMPACT_F <= 3)
check("sky: palette without yellow / acid green / neon", all(not (40 <= M._hue_deg(c) <= 170) for c in M.SKY_PALETTE.values()))
r = M.sky_ranked("hype", 0.8, 140)[0]
check("sky: warm / hype / aggressive = deep red first", r[0] == "ember" and M.sky_ranked("aggressive", 0.9, 150)[0][0] == "ember")
check("sky: calm songs = blue / teal / violet", M.sky_ranked("chill", 0.3, 80)[0][0] in ("deep blue", "teal", "violet"))
g = M.sky_grade_v2(M.SKY_PALETTE["ember"], "dark")
check("sky grade: only multiplicative darkening (no lift)", all(g[k]["y_mul"] <= 1.0 for k in ("steady", "dark")) and g["surge"]["y_mul"] <= 1.0)
b, why = M.sky_blend_cover(M.SKY_PALETTE["ember"], 0x283A59)
check("sky: cover blend keeps it deep", ((b >> 16) & 255) < 220 and "blended" in why, why)
check("sky: yellow cover is refused", M.sky_blend_cover(M.SKY_PALETTE["ember"], 0xA0A020)[0] == M.SKY_PALETTE["ember"])
a = M.sky_anim_params(0.9, 160)
b2 = M.sky_anim_params(0.2, 80)
check("sky: faster song = faster clouds, stronger surge", a["drift"] > b2["drift"] and a["surge"] > b2["surge"])
check("stall rule exists", M.STALL_MAX_SHARE <= 0.1)
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
