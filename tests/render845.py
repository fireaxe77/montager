"""V8.4.5 tool: build a GUI job's plan (plan845.build) and render it ONCE, in full, through render_plan (one attempt); writes the plan json next to the video.
python tests/render845.py <game> <extra|default> --seed N [--unuse TITLE] --out <video.mp4>
Needs a lot of memory (a 70 s montage peaks at ~10 GB in ffmpeg); do not run other heavy jobs at the same time."""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import plan845                                                                                  # noqa: E402

M = plan845.M


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("effects")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--unuse")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    plan, text, cfg = plan845.build(a.game, a.effects, a.seed, None, unuse_title=a.unuse)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".plan.json").write_text(json.dumps(plan, default=str), encoding="utf-8")
    print(plan845.table(plan))
    M.render_plan(plan, str(out), cfg, maxq=False, preview=False, encoder=None, effects=True)
    print("rendered", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
