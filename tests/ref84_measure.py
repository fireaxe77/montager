"""V8.4 reference measurement: per-frame video features of a finished montage (no GUI, no montager code needed).
python tests/ref84_measure.py "E:\\Movies\\Montages\\Fiverr 48 (2).mp4" OUT.npz
Pipes the video downscaled to 320x180 at its own frame rate and stores, per frame: mean B,G,R, luma mean / std, saturation, frame difference,
global motion (translation tx, ty, scale s, rotation) by sparse optical flow, sharpness (Laplacian variance), red-pixel count in the top-right killfeed region."""
import subprocess
import sys
import time

import cv2
import numpy as np

W, H = 320, 180


def main(src, dst, fps=60):
    cmd = ["ffmpeg", "-v", "error", "-i", src, "-an", "-vf", f"fps={fps},scale={W}:{H}:flags=area", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=W * H * 3 * 8)
    n = W * H * 3
    feats = []
    prev_g = None
    t0 = time.time()
    i = 0
    lk = dict(winSize=(15, 15), maxLevel=2, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 10, 0.03))
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        fr = np.frombuffer(b, np.uint8).reshape(H, W, 3)
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(fr, cv2.COLOR_BGR2HSV)
        bm, gm, rm = (float(fr[..., c].mean()) for c in range(3))
        diff = float(np.abs(g.astype(np.int16) - prev_g.astype(np.int16)).mean()) if prev_g is not None else 0.0
        tx = ty = rot = 0.0
        sc = 1.0
        nfe = 0
        if prev_g is not None:
            pts = cv2.goodFeaturesToTrack(prev_g, 120, 0.01, 8)
            if pts is not None and len(pts) >= 8:
                nxt, st, _ = cv2.calcOpticalFlowPyrLK(prev_g, g, pts, None, **lk)
                ok = st.ravel() == 1
                if ok.sum() >= 8:
                    M, inl = cv2.estimateAffinePartial2D(pts[ok], nxt[ok], method=cv2.RANSAC, ransacReprojThreshold=1.5)
                    if M is not None:
                        sc = float(np.hypot(M[0, 0], M[1, 0]))
                        rot = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
                        tx, ty = float(M[0, 2]), float(M[1, 2])
                        nfe = int(inl.sum()) if inl is not None else 0
        lap = float(cv2.Laplacian(g, cv2.CV_64F).var())
        kf = fr[0:int(H * 0.30), int(W * 0.58):]                  # top-right killfeed region
        red = int(((kf[..., 2] > 170) & (kf[..., 1] < 70) & (kf[..., 0] < 70)).sum())
        feats.append((bm, gm, rm, float(g.mean()), float(g.std()), float(hsv[..., 1].mean()), diff, tx, ty, sc, rot, nfe, lap, red))
        prev_g = g
        i += 1
        if i % 1500 == 0:
            print(f"{i} frames, {time.time() - t0:.0f}s", flush=True)
    p.wait()
    a = np.array(feats, np.float32)
    np.savez(dst, feats=a, fps=fps, cols=np.array("b g r luma lstd sat diff tx ty scale rot nfe lap red".split()))
    print("frames", len(a), "->", dst)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
