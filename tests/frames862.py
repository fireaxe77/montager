"""V8.6.2 tool: render the SAME automatic plan (game, seed) twice, once with MONTAGE_NO_RO=1 (the old json loading) and once normally, and compare 20 evenly sampled frames (and the audio length).
python tests/frames862.py <game> <seed> <out dir>"""
import os
import subprocess
import sys
from pathlib import Path

game, seed, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
code = r'''
import sys, warnings, random
warnings.simplefilter("ignore")
sys.path.insert(0, ".")
import montage as M
cfg = M.load_config()
M.QUIET.on = True
plan, text = M.make_plan(cfg, sys.argv[1], scan=False, seed=int(sys.argv[2]))
M.QUIET.on = False
M.render_plan(plan, sys.argv[3], cfg, maxq=False, preview=False, encoder=None, effects=True)
'''
vids = []
for tag, env in (("old", {"MONTAGE_NO_RO": "1"}), ("new", {})):
    f = out / f"{game}_{seed}_{tag}.mp4"
    r = subprocess.run([sys.executable, "-W", "ignore", "-c", code, game, seed, str(f)], env={**os.environ, **env, "PYTHONIOENCODING": "utf-8"}, capture_output=True)
    print(tag, "exit", r.returncode, f.stat().st_size if f.exists() else None, flush=True)
    vids.append(f)
import cv2
import numpy as np
a, b = cv2.VideoCapture(str(vids[0])), cv2.VideoCapture(str(vids[1]))
n = int(min(a.get(7), b.get(7)))
bad, mx = 0, 0.0
for i in np.linspace(5, n - 5, 20).astype(int):
    a.set(1, int(i)); b.set(1, int(i))
    ok1, f1 = a.read(); ok2, f2 = b.read()
    d = float(np.abs(f1.astype(np.int16) - f2.astype(np.int16)).max()) if ok1 and ok2 else 999
    mx = max(mx, d)
    bad += d > 0
la = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(vids[0])], capture_output=True, text=True).stdout.strip()
lb = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(vids[1])], capture_output=True, text=True).stdout.strip()
txt = f"{game} seed {seed}: frames {int(a.get(7))} vs {int(b.get(7))}; 20 sampled frames: {bad} differ (largest pixel difference {mx:.0f}); duration {la} vs {lb}"
print(txt)
(out / f"frames_{game}_{seed}.txt").write_text(txt + "\n")
