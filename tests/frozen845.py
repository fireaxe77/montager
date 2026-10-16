"""V8.4.5 tool: scan a rendered montage for takes with frozen / repeated frames.
python tests/frozen845.py <montage.mp4> <plan.json> [--thr 0.6]
Decodes the video at 192x108 grey, 60 fps, takes the mean absolute difference of every frame to the one before, and per take prints how many DISTINCT frames it has (a frame is distinct when it differs
from the previous one by more than --thr grey levels), the longest run of identical frames and its time; takes that look frozen (fewer than 60 % distinct frames outside a deliberate slow-mo) are marked."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np


def frame_diffs(video, w=192, h=108):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps=60,scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"], capture_output=True)
    a = np.frombuffer(r.stdout, np.uint8)
    n = len(a) // (w * h)
    a = a[:n * w * h].reshape(n, h, w).astype(np.int16)
    d = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2))
    return np.concatenate([[99.0], d])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("plan")
    ap.add_argument("--thr", type=float, default=0.6)
    a = ap.parse_args()
    plan = json.load(open(a.plan, encoding="utf-8"))
    d = frame_diffs(a.video)
    print(f"{len(d)} frames decoded ({len(d) / 60:.2f} s)")
    bad = 0
    for i, t in enumerate(plan["takes"], 1):
        f0, nf = int(round(float(t["out_start"]) * 60)), int(t["nf"])
        seg = d[f0:f0 + nf]
        dist = seg > a.thr
        # longest run of identical frames
        best, cur, at = 0, 0, 0
        for j, v in enumerate(dist):
            cur = 0 if v else cur + 1
            if cur > best:
                best, at = cur, j
        slow = min(s[2] for s in t["segs"] if s[2] > 0) if t["segs"] else 1.0
        ratio = float(dist.mean()) if len(dist) else 1.0
        flag = ""
        if ratio < 0.6 and slow >= 0.9:
            flag = "   <-- FROZEN / REPEATED FRAMES"
            bad += 1
        print(f"take {i:2d} {Path(t['path']).name[-36:]:36s} out {f0 / 60:6.2f}-{(f0 + nf) / 60:6.2f}s  {nf:3d} frames, {int(dist.sum()):3d} distinct ({ratio * 100:3.0f}%), longest repeat {best + 1:3d} frames at +{at / 60:.2f}s, "
              f"min speed {slow:.2f}{flag}")
    print(f"{bad} take(s) with frozen / repeated frames")
    return 0


if __name__ == "__main__":
    sys.exit(main())
