"""V8.6.1 fast tests (no render): python tests/test_v861.py"""
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

FAILS = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {info}" if info else ""))
    if not ok:
        FAILS.append(name)


check("version", M.APP_VERSION == "V8.6.1", M.APP_VERSION)
# a synthetic picture: blue sky gradient to a pale horizon, a white cloud blob, a dark roof, a wire, a pole, a textured wall low down
W, H = 768, 432
img = np.zeros((H, W, 3), np.uint8)
for y in range(H):
    t = y / H
    img[y, :] = (int(95 + 50 * t), int(155 + 40 * t), int(235 - 10 * t))          # RGB: deep blue at the top, paler lower
img[:60, :] = img[60, :]                                                           # the very top rows are the same sky
cv2.circle(img, (200, 120), 28, (245, 245, 250), -1)                              # a cloud (a compact blob inside the sky)
cv2.fillPoly(img, [np.array([[0, 300], [0, 230], [300, 250], [768, 270], [768, 432], [0, 432]])], (110, 90, 80))      # roof / ground: its edge is the horizon
cv2.line(img, (0, 40), (768, 90), (30, 30, 30), 2)                                 # a wire
cv2.line(img, (500, 0), (500, 250), (40, 40, 40), 3)                               # a pole
rng = np.random.RandomState(1)
img[300:, :] = np.clip(img[300:, :].astype(int) + rng.randint(-25, 25, (H - 300, W, 3)), 0, 255).astype(np.uint8)      # texture on the ground
m, info = M.sky_eyedrop(img)
check("eyedropper finds the sky", info["ok"] and 0.2 < info["cov"] < 0.6, f"cov {info['cov']:.2f} {info['why']}")
check("sky goes below the middle (no cap)", bool(m[int(H * 0.5):int(H * 0.52)].any()))
check("nothing below the horizon is sky", float(m[262:].mean()) < 0.01)
check("the cloud blob is filled", bool(m[120, 200]))
check("the wire stays cut out", not m[65, 384] and bool(m[90, 384]), f"wire {m[65, 384]} next to it {m[90, 384]}")
check("the pole stays cut out", not m[200, 500] and bool(m[200, 480]))
check("the ground is not sky", not m[400, 300])
check("no HUD / radar carve-out in the code", "radar" not in M.sky_eyedrop_mask.__doc__.lower().split("no cap")[0])
check("opacity 90 - 95 %", 0.90 <= M.SKY_OPACITY <= 0.95, str(M.SKY_OPACITY))
check("steady layer darkens multiplicatively", M.sky_grade_v2(M.SKY_PALETTE["ember"], "dark")["steady"]["y_mul"] <= 0.5)
check("sky detection threshold lowered", M.XFX_SKY_MIN_COV <= 0.03)
# the eyedropper must not paint a warm wall
wall = np.zeros((H, W, 3), np.uint8)
wall[:] = (200, 160, 110)
check("a warm smooth wall is not a sky", not M.sky_eyedrop(wall)[1]["ok"])
# auto helpers
plan = {"takes": [{"path": "a.mp4", "srcs": [{"path": "a.mp4"}, {"path": "b.mp4"}]}, {"path": "c.mp4"}]}
check("placed paths include stitched clips", M.plan_placed_paths(plan) == {"a.mp4", "b.mp4", "c.mp4"})
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
sys.exit(1 if FAILS else 0)
