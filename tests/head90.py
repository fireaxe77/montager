"""V9.0 helper: render only the first N takes of a saved plan (dry .json or a montage's .plan.json), with its intro, to check the intro and the handover into the first take quickly.
    python tests\\head90.py <plan.json> <out.mp4> [N=4]      (run on a COPY of montage_data: MONTAGER_DATA)
The plan is cut after N takes (the last one is not an ending: it is cut at its own end), the song fade starts 1 s before the end; everything else is the real render path (render_plan)."""
import json
import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _root import find_root  # noqa: E402

ROOT = find_root(__file__)
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")
import montage as m  # noqa: E402


def head_plan(plan, n):
    takes = [dict(t) for t in plan["takes"][:n]]
    for t in takes:
        t["ending"] = False
    tf = takes[-1]["f0"] + takes[-1]["nf"]
    p = dict(plan, takes=takes, total_frames=tf, duration=round(tf / m.OUT_FPS, 4), ending=False, outro=None, drop_sync=[], drop_anchor=None)
    p["song"] = dict(plan["song"], fade_out_start=max(0.0, tf / m.OUT_FPS - 1.0))
    p["xfx_drop"] = [d for d in (plan.get("xfx_drop") or []) if float(d["t"]) < tf / m.OUT_FPS - 0.5]
    return p


def tail_plan(plan, n):
    """the LAST n takes (the ending and its outro, no intro), re-based to 0."""
    takes = [dict(t) for t in plan["takes"][-n:]]
    base = takes[0]["f0"]
    b = base / m.OUT_FPS
    for t in takes:
        t["f0"] -= base
        t["out_start"] = round(t["out_start"] - b, 4)
    sg = dict(plan["song"], start_t=round(plan["song"]["start_t"] + b, 6), fade_out_start=round(plan["song"]["fade_out_start"] - b, 4), fade_in=0.3)
    o = plan.get("outro")
    p = dict(plan, takes=takes, song=sg, total_frames=plan["total_frames"] - base, duration=round(plan["duration"] - b, 4), intro=None, drop_sync=[], drop_anchor=None,
             outro=dict(o, fade_start=round(o["fade_start"] - b, 4)) if o else None,
             beats_out=[round(x - b, 4) for x in plan.get("beats_out", []) if x >= b], drops_out=[round(x - b, 4) for x in plan.get("drops_out", []) if x >= b],
             xfx_drop=[dict(d, t=round(float(d["t"]) - b, 4)) for d in (plan.get("xfx_drop") or []) if float(d["t"]) >= b])
    return p


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src, dst = Path(args[0]), Path(args[1])
    n = int(args[2]) if len(args) > 2 else 4
    plan = json.loads(src.read_text(encoding="utf-8"))
    cfg = m.load_config()
    p = tail_plan(plan, n) if "--tail" in sys.argv else head_plan(plan, n)
    print("intro:", bool(p.get("intro")), "takes:", len(p["takes"]), "duration", p["duration"])
    m.render_plan(p, dst, cfg, False, False, None, True)
    print("done", dst)


if __name__ == "__main__":
    main()
