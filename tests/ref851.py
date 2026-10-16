"""V8.5.1 tool: which version made the reference sky? Renders the sky effect of an OLD montage.py (V8.4.1 / V8.4.2 checked out in a worktree) on a frame of a real clip.
python tests/ref851.py <old montage.py> <clip> <kill time s> <out.png> [hue 0-360 = 38] -> the source frame and the old version's frame at the kill (480x270 each), side by side."""
import importlib.util
import subprocess
import sys
import warnings
from pathlib import Path

import cv2
import numpy as np

warnings.simplefilter("ignore")
old_py, clip, tm, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
hue = int(sys.argv[5]) if len(sys.argv) > 5 else 38
sys.path.insert(0, str(Path(old_py).parent))
spec = importlib.util.spec_from_file_location("m_old", old_py)
M = importlib.util.module_from_spec(spec)
sys.modules["m_old"] = M
spec.loader.exec_module(M)
p = 2.0
zone = list(M.DEFAULT_REGION["cs2"])
zone[3] = zone[1] + 0.55 * (zone[3] - zone[1])
rgb = M.FEEL_RGB_BY_HUE.get(hue, 0xFFB000)
take = {"nf": 240, "xfx": [{"k": "sky", "p": p, "t0": p - 0.25, "t1": p + 0.75, "ok": True, "hue": hue}]}
chains = []
fx = set(M.FX_ALL) | {"sky", "glow", "split", "grade"}
lab = M._xfx_chains(chains, "t0", "[src]", take, fx, False, zone, {"name": "x", "hue": hue, "rgb": rgb})
pre = "scale=1920:1080:flags=lanczos,setsar=1,fps=60,format=yuv420p,setpts=PTS-STARTPTS,trim=end_frame=240,setpts=PTS-STARTPTS"
g = f"[0:v]{pre}[src];" + ";".join(chains) + f";{lab}null[o]"
inp = ["-ss", f"{tm - p:.3f}", "-t", "4.2", "-i", clip]
res = []
for graph in (f"[0:v]{pre}[o]", g):
    fc = graph + ";[o]select='eq(n,%d)',scale=480:270:flags=area,format=rgb24[z]" % int(p * 60 + 3)
    r = subprocess.run(["ffmpeg", "-v", "error", "-y"] + inp + ["-filter_complex", fc, "-map", "[z]", "-vsync", "0", "-f", "rawvideo", "-"], capture_output=True)
    if len(r.stdout) < 480 * 270 * 3:
        raise SystemExit("ffmpeg failed: " + r.stderr.decode("utf-8", "ignore")[-400:])
    res.append(np.frombuffer(r.stdout[:480 * 270 * 3], np.uint8).reshape(270, 480, 3))
cv2.imwrite(out, cv2.cvtColor(np.concatenate(res, 1), cv2.COLOR_RGB2BGR))
print(out)
