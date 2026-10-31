r"""V9.5.2 diagnosis: for a take of a saved plan, the sky mask of its kill frame (what the recolour covers) over the picture, and the rows where the mask's lower edge is a straight line.
python tests/skyline952.py <plan.json> <take number> <out.png>   (MONTAGER_DATA = a COPY of montage_data)"""
import json
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import cv2                                                                                    # noqa: E402
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

plan = json.load(open(sys.argv[1], encoding="utf-8"))
ti = int(sys.argv[2]) - 1
t = plan["takes"][ti]
x = next(x for x in t["xfx"] if x.get("k") == "sky")
f0 = int(round(float(x["p"]) * M.OUT_FPS))
fr = M.sky_src_frames(t, f0, f0 + 1)
si, st = fr[0]
src = t["srcs"][si]
img = M.sky_grab_frames(src["path"], st, st + 0.04, src["rect"], src["wh"], fps=60)[0]
mk, info = M.sky_eyedrop(img)
h, w = img.shape[:2]
rows = np.where(mk.any(1))[0]
print("mask size", (w, h), "coverage", round(float(mk.mean()), 3), "lowest mask row", int(rows.max()) if len(rows) else None, f"= {rows.max() / h:.0%}" if len(rows) else "")
# per-row mask width: a straight cut = a row band where the mask width drops from large to ~0 over very few rows
cnt = mk.sum(1).astype(float)
d = cnt[:-1] - cnt[1:]
j = int(np.argmax(d))
print(f"largest row-to-row drop of the mask width: rows {j}->{j + 1} ({j / h:.0%} of the height): {int(cnt[j])} -> {int(cnt[j + 1])} px of {w}")
import os
if os.environ.get("SKY_EXTEND", "1") == "1":
    mk2 = M.sky_extend_mask(img, mk, M.sky_eyedrop_sample(img))
    rows2 = np.where(mk2.any(1))[0]
    print("extended: coverage", round(float(mk2.mean()), 3), "lowest row", f"{rows2.max() / h:.0%}")
    mk = mk2
ov = img.copy()
ov[mk] = (0.5 * ov[mk] + 0.5 * np.array([255, 0, 255])).astype(np.uint8)
cv2.imwrite(sys.argv[3], cv2.cvtColor(np.hstack([img, ov]), cv2.COLOR_RGB2BGR))
