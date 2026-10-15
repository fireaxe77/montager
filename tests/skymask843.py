"""V8.4.3 tool: what the sky rule sees. For every sky candidate of a plan (the picture at the take's last kill) and for any extra pictures:
the frame, the old mask (V8.4.2: blue-ish or bright grey) and the new mask (V8.4.3: sky-blue colour family only), with the coverage numbers.
python tests/skymask843.py <plan.json> <out.png> [extra.mp4@seconds ...]"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import montage as M                                                                           # noqa: E402


def old_mask(rgb):
    r, g, b = (rgb[..., i].astype(np.int16) for i in (0, 1, 2))
    lum = (r + g + b) / 3.0
    mx, mn = np.maximum(np.maximum(r, g), b), np.minimum(np.minimum(r, g), b)
    m = ((b > r + 22) & (b > g + 4) & (lum > 110)) | ((lum > 185) & ((mx - mn) < 22))
    m[int(rgb.shape[0] * 0.55):] = False
    m[:int(rgb.shape[0] * 0.30), :int(rgb.shape[1] * 0.22)] = False
    return m


def grab(path, tt, crop=""):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, tt):.3f}", "-i", str(path), "-frames:v", "1", "-vf", f"{crop}scale=480:270:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True)
    if len(r.stdout) < 480 * 270 * 3:
        return np.zeros((270, 480, 3), np.uint8)
    return np.frombuffer(r.stdout[:480 * 270 * 3], np.uint8).reshape(270, 480, 3).copy()


def overlay(img, mk, col):
    o = img.copy()
    o[mk] = (0.4 * o[mk] + 0.6 * np.array(col)).astype(np.uint8)
    return o


def main(plan_json, out, *extra):
    plan = json.load(open(plan_json, encoding="utf-8"))
    items = []
    for ti, t in enumerate(plan["takes"]):
        if any(x["k"] == "sky" for x in t.get("xfx") or []):
            srcs = t["srcs"]
            ks = float(t["kills"][-1])
            src = next((s_ for s_ in reversed(srcs) if 0 <= ks - s_["shift"] <= (s_.get("dur") or 1e9)), srcs[0])
            cx, cy, cw, ch = src["rect"]
            crop = f"crop={cw}:{ch}:{cx}:{cy}," if [cx, cy, cw, ch] != [0, 0, src["wh"][0], src["wh"][1]] else ""
            items.append((f"take {ti + 1}", grab(src["path"], ks - src["shift"], crop)))
    for e in extra:
        p, _, s = e.rpartition("@")
        items.append((Path(p).stem[:24] + "@" + s, grab(p, float(s))))
    W, H = 480, 270
    img = Image.new("RGB", (4 * W, ((len(items) + 1) // 2) * H * 1), (0, 0, 0))
    for i, (name, fr) in enumerate(items):
        mo, mn = old_mask(fr), M.sky_mask_np(fr)
        co, cn = float(mo[:int(270 * .55)].mean()), float(mn[:int(270 * .55)].mean())
        top = float(mn[:int(270 * .15)].mean())
        a = Image.fromarray(fr)
        ImageDraw.Draw(a).text((6, 6), name, fill=(255, 255, 0))
        b = Image.fromarray(overlay(fr, mo, (255, 0, 0)))
        ImageDraw.Draw(b).text((6, 6), f"OLD mask {co * 100:.0f}%", fill=(255, 255, 0))
        c = Image.fromarray(overlay(fr, mn, (255, 0, 0)))
        ImageDraw.Draw(c).text((6, 6), f"NEW mask {cn * 100:.0f}% top {top * 100:.0f}%", fill=(255, 255, 0))
        x0, y0 = (i % 2) * 2 * W, (i // 2) * H
        img.paste(a if False else c, (x0 + W, y0))
        img.paste(b if False else a, (x0, y0))
        print(f"{name:34s} old {co * 100:5.1f}%  new {cn * 100:5.1f}%  new-top {top * 100:5.1f}%  -> {'SKY' if M.XFX_SKY_MIN_COV <= cn <= M.XFX_SKY_MAX_COV and top >= M.XFX_SKY_MIN_TOP else 'no sky'}")
    img.save(out)


if __name__ == "__main__":
    main(*sys.argv[1:])
