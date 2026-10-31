r"""V9.5.1 short test render of a plan's INTRO (first take(s) + the 7 s intro, preview quality) and a motion measurement of its picture (mean grey change between
frames 0.1 s apart, per second of the first 7 s). python tests/introclip951.py <plan.json> <out.mp4>   (MONTAGER_DATA = a COPY of montage_data)"""
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
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

plan = json.load(open(sys.argv[1], encoding="utf-8"))
SKY_KEYS = ("ok", "mask", "grade", "cov", "anim", "beats", "fam", "pattern", "mask_fmt", "frames_src", "horizon", "sky_cut")
for t in plan["takes"]:
    t["xfx"] = [x for x in (t.get("xfx") or []) if x.get("k") != "sky"]
plan["song"]["drop_t"] = 5.0                              # slice_plan then starts at the beginning and keeps the intro
out = Path(sys.argv[2])
M.render_plan(plan, out, M.load_config(), preview=True)
r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-t", "7", "-vf", "fps=10,scale=240:-1,format=gray", "-f", "rawvideo", "-"], capture_output=True)
w, h = 240, int(round(240 * 9 / 16))
buf = np.frombuffer(r.stdout, np.uint8)
n = len(buf) // (240 * h)
fr = buf[:n * 240 * h].reshape(n, h, 240).astype(np.float32)
d = [float(np.abs(fr[i + 1] - fr[i]).mean()) for i in range(n - 1)]
per_s = [round(float(np.mean(d[i * 10:(i + 1) * 10])), 2) for i in range(7)]
print("picture change per output second (0.1 s steps), first 7 s:", per_s, "| frames that did not change at all:", sum(1 for x in d if x < 0.02), "of", len(d))
