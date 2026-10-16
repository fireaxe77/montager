"""V8.4.5 tool: render ONE take (or a few consecutive ones) of a saved plan json as a short real clip, through render_plan (one attempt), for checks.
python tests/take845.py <plan.json> <first take 1-based> <count> <out.mp4> [--default] [--interp on|off|auto]
Keeps the take's own cut list, speeds, effects (unless --default) and source clips; the music is a synthetic tone file (the plan's song may not exist here), the output is cut to the takes."""
import argparse
import copy
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
import montage as M                                                                           # noqa: E402


def mini_plan(plan, first, count, default=False, real_song=False):
    takes = [copy.deepcopy(t) for t in plan["takes"][first - 1:first - 1 + count]]
    f0 = takes[0]["f0"]
    t0 = float(takes[0]["out_start"])
    for t in takes:
        t["f0"] -= f0
        t["out_start"] = round(float(t["out_start"]) - t0, 4)
        t["trans"] = "hard"
        if default:
            t.pop("xfx", None)
    takes[0]["trans"] = "hard"
    tf = takes[-1]["f0"] + takes[-1]["nf"]
    p = dict(plan, takes=takes, duration=tf / 60.0, total_frames=tf)
    if default:
        p["effects"] = "default"
        for k in ("xfx_zone", "xfx_feel", "xfx_plan", "xfx_sky_max", "xfx_sky_hue"):
            p.pop(k, None)
    if real_song:                                                   # the plan's own song, from the point of the montage where the first take starts
        p["song"] = dict(plan["song"], start_t=float(plan["song"]["start_t"]) + t0, fade_out_start=max(0.0, tf / 60.0 - 0.8))
    else:
        song = Path(tempfile.gettempdir()) / "take845_song.mp3"
        if not song.exists():
            M.synth_song(song, 128.0)
        p["song"] = dict(plan["song"], path=str(song), fade_out_start=max(0.0, tf / 60.0 - 0.8), start_t=0.0)
    if "xfx_drop" in plan:
        p["xfx_drop"] = [dict(d, t=round(float(d["t"]) - t0, 4)) for d in plan["xfx_drop"] if 0.2 < float(d["t"]) - t0 < tf / 60.0 - 0.1]
    if default:
        p.pop("xfx_drop", None)
    p["notes"] = []
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("first", type=int)
    ap.add_argument("count", type=int)
    ap.add_argument("out")
    ap.add_argument("--default", action="store_true")
    ap.add_argument("--interp", default="auto")
    ap.add_argument("--real-song", action="store_true")
    ap.add_argument("--no-drop", action="store_true", help="keep the other extra effects but remove the drop moments (the A/B reference of the drop proof)")
    ap.add_argument("--no-sky", action="store_true")
    a = ap.parse_args()
    plan = json.load(open(a.plan, encoding="utf-8"))
    p = mini_plan(plan, a.first, a.count, a.default, a.real_song)
    if a.no_drop:
        p["xfx_drop"] = []
    if a.no_sky:
        for t_ in p["takes"]:
            t_["xfx"] = [x for x in t_.get("xfx", []) if x["k"] != "sky"]
    cfg = dict(M.DEFAULT_CONFIG)
    cfg["interpolate_low_fps"] = a.interp == "on"
    M.render_plan(p, a.out, cfg, preview=False, encoder="fast", effects=True)
    print("rendered", a.out, f"{p['duration']:.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
