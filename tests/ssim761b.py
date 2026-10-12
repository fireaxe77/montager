"""V7.6.1: per-take picture quality of a REAL render, independent of timing: every output frame of a clean 1.0x stretch is compared with the best-matching of the source frames around it
(source cropped / scaled by the renderer's own rule), SSIM on the luma at 960x540.   python tests\\ssim761b.py <montage.mp4> [<plan.json>] [take numbers...]"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
import cv2                                                                                    # noqa: E402
import numpy as np                                                                            # noqa: E402
import ssim761 as S1                                                                          # noqa: E402

W, H = 960, 540


def ssim_gray(a, b):
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    c1, c2 = 6.5025, 58.5225
    mu_a, mu_b = cv2.GaussianBlur(a, (11, 11), 1.5), cv2.GaussianBlur(b, (11, 11), 1.5)
    saa = cv2.GaussianBlur(a * a, (11, 11), 1.5) - mu_a ** 2
    sbb = cv2.GaussianBlur(b * b, (11, 11), 1.5) - mu_b ** 2
    sab = cv2.GaussianBlur(a * b, (11, 11), 1.5) - mu_a * mu_b
    m = ((2 * mu_a * mu_b + c1) * (2 * sab + c2)) / ((mu_a ** 2 + mu_b ** 2 + c1) * (saa + sbb + c2))
    return float(m.mean())


def frames(path, ss, d, vf, fps=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, ss):.4f}", "-t", f"{d:.4f}", "-i", str(path), "-an", "-vf", vf + (f",fps={fps}" if fps else "") + f",scale={W}:{H}:flags=area,format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W)


def audit(video, plan, only=None):
    rows = []
    for i, t in enumerate(plan["takes"], 1):
        if only and i not in only:
            continue
        st = S1.stretch(t)
        if not st:
            continue
        g0, s0, sg = st
        src = t["srcs"][sg[4] if len(sg) > 4 else 0]
        s0 -= src["shift"]
        cx, cy, cw, ch = src["rect"]
        crop = f"crop={cw}:{ch}:{cx}:{cy}," if [cx, cy, cw, ch] != [0, 0, src["wh"][0], src["wh"][1]] else ""
        ref = f"{crop}scale=1920:1080:flags=lanczos"
        out = frames(video, g0, 0.4, "null")
        srcf = frames(src["path"], s0 - 0.1, 0.65, ref)                         # every source frame (native rate) around the window, scaled like the renderer does
        if not len(out) or not len(srcf):
            continue
        best = []
        for o in out[:20]:
            best.append(max(ssim_gray(o, s) for s in srcf))
        pr = S1.probe(src["path"])
        rows.append({"take": i, "clip": Path(src["path"]).name, "src": pr, "wh": src["wh"], "rect": src["rect"], "ssim_min": round(min(best), 4), "ssim_mean": round(float(np.mean(best)), 4)})
    return rows


if __name__ == "__main__":
    vid = Path(sys.argv[1])
    pj = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].endswith(".json") else vid.parent / "logs" / (vid.stem + ".plan.json")
    only = {int(x) for x in sys.argv[2:] if x.isdigit()} or None
    plan = json.load(open(pj, encoding="utf-8"))
    for r in audit(vid, plan, only):
        print(f"take {r['take']:2d} {r['clip'][-34:]:34s} {str(r['wh']):12s} rect {str(r['rect']):18s} src {r['src']}  best-frame SSIM mean {r['ssim_mean']:.3f} min {r['ssim_min']:.3f}")
