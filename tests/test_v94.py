r"""V9.4 tests (fast; generated clips; part r = real data, needs V94_REAL=1 and MONTAGER_DATA = a COPY of montage_data).
python tests\test_v94.py        V94_PARTS=0,1,2,3,r
0 version / switches   1 drops only on a take's first or last kill   2 interpolation of 50 fps clips only   3 the sky recolour leaves with the sky   r the 1v2.mp4 second kill's dating"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="v94_"))
if not os.environ.get("V94_REAL"):
    os.environ["MONTAGER_DATA"] = str(TMP / "data")
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

FAILS = []
PARTS = os.environ.get("V94_PARTS", "0,1,2,3").split(",")


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def ff(args):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error"] + args, capture_output=True)
    assert r.returncode == 0, r.stderr.decode(errors="replace")[-400:]


if "0" in PARTS:
    print("== 0) version / switches ==")
    check("title-bar version V9.4", M.APP_VERSION == "V9.4", M.APP_VERSION)
    txt = (ROOT / "docs/CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    check("Settings changelog: V9.4 on top, V9.3.3 below it", 0 <= txt.find("## V9.4") < txt.find("## V9.3.3"))
    check("switches exist", all(isinstance(x, list) for x in (M.DROP_FIRST_LAST_ONLY, M.INTERP_ONLY_50, M.SKY_HOLD_OWN, M.CS2_DATING_EXT_SLOT)))

if "1" in PARTS:
    print("== 1) a drop lands only on the first or last kill of a take ==")
    tk = [{"path": f"c{i}.mp4", "role": "calm", "kills": [1.0, 2.0, 3.0, 4.0], "kills_out": [1, 2, 3, 4], "ev": {}} for i in range(2)]
    plan = {"takes": tk, "total_frames": 1200, "duration": 20.0, "song": {"start_t": 0.0, "drop_t": None}}
    tried = []
    o_imp, o_mv, o_re, o_on = M.impact_time, M.move_kill, M.reorder_for_drop, M.DROP_ANCHOR_ON[0]
    M.impact_time = lambda p, ti, kj: 5.0 + 10.0 * ti + kj           # take 0 kills at 5, 6, 7, 8; take 1 at 15 .. 18
    M.move_kill = lambda p, ti, kj, t, fps, protected=frozenset(): (tried.append((ti, kj)), (None, "", "no"))[1]
    M.reorder_for_drop = lambda *a, **k: (None, None, None, "no")
    M.DROP_ANCHOR_ON[0] = True
    try:
        for flag in (True, False):
            tried.clear()
            M.DROP_FIRST_LAST_ONLY[0] = flag
            notes = []
            M.anchor_all_drops(plan, [(7.0, 1.0, "map")], "cs2", notes)
            mids = [x for x in tried if x[1] in (1, 2)]
            check(f"drop at the 3rd kill, rule {'on' if flag else 'off'}: middle kills {'never tried' if flag else 'are candidates (the old behaviour)'}", (not mids) if flag else bool(mids), str(tried))
            if flag:
                check("...and it is said as not anchorable, never moved to a middle kill", any("not anchorable" in n for n in notes), str(notes))
    finally:
        M.impact_time, M.move_kill, M.reorder_for_drop, M.DROP_ANCHOR_ON[0] = o_imp, o_mv, o_re, o_on
        M.DROP_FIRST_LAST_ONLY[0] = True

if "2" in PARTS:
    print("== 2) interpolation: 50 fps clips only ==")
    from v696_common import gen_clip, mkplan, mv, logged, silent_song                          # noqa: E402
    d = TMP / "interp"
    d.mkdir()
    song = silent_song(d / "song.wav")
    clips = {"c50": gen_clip(d / "c50.mp4", mv(), fps=50), "c60": gen_clip(d / "c60.mp4", mv()), "c30": gen_clip(d / "c30.mp4", mv(), fps=30)}
    cfg = {"interpolate_low_fps": True}
    for nm, fps_expect in (("c50", True), ("c60", False), ("c30", False)):
        plan = mkplan(clips[nm], [[2.0, 5.0, 1.0, 180]], song)
        newp, lines = logged(M.interp_prepare, plan, cfg, d / f"t_{nm}")
        done = any(l.startswith("interpolated ") for l in lines)
        check(f"{nm}: {'interpolated' if fps_expect else 'left untouched (same plan object)'}", done if fps_expect else (newp is plan and not done), str(lines[-2:]))
    plan = mkplan(clips["c60"], [[2.0, 4.0, 0.5, 240]], song)
    newp, lines = logged(M.interp_prepare, plan, cfg, d / "t_slow")
    check("a 60 fps clip in slow-motion is not interpolated here (its slow-motion has its own interpolation)", newp is plan and not any(l.startswith("interpolated ") for l in lines), str(lines[-2:]))
    plan = mkplan(clips["c50"], [[2.0, 5.0, 1.0, 180]], song)
    newp, lines = logged(M.interp_prepare, plan, {}, d / "t_off")
    check("the Settings switch off: nothing is probed or changed", newp is plan and any("interpolation off" in l for l in lines), str(lines))
    plan = mkplan(clips["c50"], [[2.0, 5.0, 1.0, 180]], song)
    newp, lines = logged(M.interp_prepare, plan, cfg, d / "t_plan")
    check("the plan itself (kill times, segments, frames) is not touched", newp["takes"][0]["segs"] == plan["takes"][0]["segs"] and newp["takes"][0]["kills_out"] == plan["takes"][0]["kills_out"]
          and newp["takes"][0]["nf"] == plan["takes"][0]["nf"])

if "3" in PARTS:
    print("== 3) the sky recolour leaves with the sky ==")
    d = TMP / "sky"
    d.mkdir()
    w, h = 320, 180
    expr = "if(lt(N,60)*lt(Y,80),{c0},{c1}+70*random(0))"
    vf = ("format=rgb24,geq=r='" + expr.format(c0=100, c1=110) + "':g='" + expr.format(c0=170, c1=100) + "':b='" + expr.format(c0=235, c1=80) + "',format=yuv420p")
    clip = d / "sky.mp4"
    ff(["-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r=60:d=2", "-vf", vf, "-c:v", "libx264", "-crf", "10", "-pix_fmt", "yuv420p", str(clip)])
    src = {"path": str(clip), "shift": 0.0, "rect": [0, 0, w, h], "wh": [w, h], "audio": False, "a_stream": 0, "gain_db": -6.0}
    take = {"path": str(clip), "srcs": [src], "rect": src["rect"], "wh": src["wh"], "segs": [[0.0, 2.0, 1.0, 120]], "nf": 120, "f0": 0}
    res = {}
    for label, own in (("new", True), ("old", False)):
        M.SKY_HOLD_OWN[0] = own
        p = d / f"m_{label}.raw"
        M.sky_take_mask(take, {"t0": 0.0, "t1": 119 / 60.0}, None, str(p))
        raw = np.frombuffer(p.read_bytes(), np.uint8)
        sz = M.SKY_W * M.SKY_H
        res[label] = [float((raw[i * sz:(i + 1) * sz] > 128).mean()) for i in range(len(raw) // sz)]
    M.SKY_HOLD_OWN[0] = True
    check("while the sky is in the picture the mask covers it", np.mean(res["new"][5:50]) > 0.15, f"{np.mean(res['new'][5:50]):.2f}")
    check("once the camera has left the sky (frames 70 .. 119) the new mask is gone", max(res["new"][70:]) < 0.01, f"{max(res['new'][70:]):.3f}")
    check("(V9.3.3 held the last mask there: the test clip shows the bug)", max(res["old"][70:]) > 0.05, f"{max(res['old'][70:]):.3f}")

if "r" in PARTS and os.environ.get("V94_REAL"):
    print("== r) the second kill of 1v2.mp4 (take 39 of the 2026-10-29 ILFTB montage) ==")
    import json
    sc = [p for p in (M.DATA / "cs2_rows_v1").glob("1v2_*.json") if "1hp" not in p.name]
    if sc:
        d_ = json.loads(sc[0].read_text(encoding="utf-8"))
        cc = M.load_json(M.CLIPS_CACHE, {})
        rec = next((v for v in cc.values() if v.get("path", "").replace("\\", "/").endswith("/1v2.mp4")), None)
        tr = next(t for t in d_["tracks"] if t["id"] == 23)
        M.CS2_DATING_MEMO.clear()
        M.CS2_DATING_MEMO["_loaded_" + str(M.DATA)] = True
        f = M.cs2_row_first_frame(rec, M.Detector("cs2"), {}, d_, tr)
        check("the Vilkko row is dated at its real first appearance (13.77 s, not 13.37 s)", f is not None and abs(f / 30.0 - 13.77) <= 0.1, str(f))
    else:
        print("  (no sidecar of 1v2.mp4 in this data folder: skipped)")

print("\nFAILED: " + "; ".join(FAILS) if FAILS else "\nall ok")
sys.exit(1 if FAILS else 0)
