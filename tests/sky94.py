r"""V9.4: does the sky recolour stay on after the sky has left the picture? Real clip, no render.
python tests\sky94.py <clip> <source start s> <source end s> [w h]   (default 1280 960)
Builds a take that plays the clip range at speed 1 and writes its sky mask exactly as a render does (sky_take_mask, window = the whole take), then compares every frame's mask
with a plain 'is there sky here' reading of the same frame (blue, bright pixels in the upper picture). Prints the frames where the mask covers more than 2 % of the picture while
the frame has no real sky (< 0.3 % blue) - the recolour on something that is not sky - and returns 1 when there are any."""
import os
import sys
import tempfile
import warnings
from pathlib import Path

from _root import find_root
ROOT = find_root()
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402


def main():
    if os.environ.get("V94_OLD"):                           # the V9.3.3 behaviour, to compare
        M.SKY_HOLD_OWN[0], M.SKY_WARM_FRAME_B = False, 8.0
    clip, a, b = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    w = int(sys.argv[4]) if len(sys.argv) > 4 else 1280
    h = int(sys.argv[5]) if len(sys.argv) > 5 else 960
    nf = int(round((b - a) * 60))
    src = {"path": clip, "shift": 0.0, "rect": [0, 0, w, h], "wh": [w, h], "audio": False, "a_stream": 0, "gain_db": -6.0}
    t = {"path": clip, "srcs": [src], "rect": src["rect"], "wh": src["wh"], "segs": [[a, b, 1.0, nf]], "nf": nf, "f0": 0}
    x = {"t0": 0.0, "t1": (nf - 1) / 60.0}
    with tempfile.TemporaryDirectory(prefix="sky94_") as td:
        p = Path(td) / "mask.raw"
        st = M.sky_take_mask(t, x, None, str(p))
        raw = p.read_bytes()
    sz = M.SKY_W * M.SKY_H
    k = len(raw) // sz
    masks = np.frombuffer(raw[:k * sz], np.uint8).reshape(k, M.SKY_H, M.SKY_W)
    imgs = M.sky_grab_frames(clip, a, b + 0.05, [0, 0, w, h], [w, h], fps=60)
    bad = []
    for i in range(min(k, len(imgs))):
        cov = float((masks[i] > 128).mean())
        im = imgs[i].astype(int)
        blue = (im[..., 2] > im[..., 0] + 25) & (im[..., 2] > 120)
        blue[int(0.75 * M.SKY_H):] = False
        real = float(blue.mean())
        if cov > 0.02 and real < 0.003:
            bad.append((i, cov, real))
    print(f"{Path(clip).name} {a:.2f}-{b:.2f} s: {k} frames, mask stats {st}")
    print(f"frames with a mask over {2}% of the picture and no real sky: {len(bad)}" + (f" (first {bad[0][0]}, last {bad[-1][0]}; e.g. frame {bad[0][0]}: mask {bad[0][1] * 100:.0f} %, blue {bad[0][2] * 100:.1f} %)" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
