"""V8.4.5 tool: proof of a drop moment from two short renders of the same take, with (A) and without (B, --no-drop) the drop moment.
python tests/dropproof845.py <A.mp4> <B.mp4> <drop kill time s in the clip> <out prefix> [--dip-s 0.3 --dip-db 7]
Writes <prefix>_audio.png (loudness of A and B around the drop, the difference, the low band), <prefix>_frames.png (the drop kill: frames before, at and after, A above B) and prints numbers:
- the difference A - B outside the drop window (must be silent: nothing else moved: no delay, overlap or phase change),
- the music dip (dB before the kill), the low hit (dB gained in 30-120 Hz after the kill), the gunshot lift,
- A against B cross-correlation lag outside the window (must be 0 samples) and the left / right equality of the added sound."""
import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

SR = 48000


def wav(path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "2", "-ar", str(SR), "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.float32).reshape(-1, 2)


def rms_db(x, blk=SR // 50):
    n = len(x) // blk
    m = x[:n * blk].mean(1).reshape(n, blk) if x.ndim == 2 else x[:n * blk].reshape(n, blk)
    return 20 * np.log10(np.sqrt((m.astype(np.float64) ** 2).mean(1)) + 1e-9)


def band(x, lo, hi):
    f = np.fft.rfft(x.mean(1))
    fr = np.fft.rfftfreq(len(x), 1.0 / SR)
    f[(fr < lo) | (fr > hi)] = 0
    return np.fft.irfft(f, len(x))


def frames(video, times, w=480):
    out = []
    for t in times:
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1", "-vf", f"scale={w}:-2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
        h = len(r.stdout) // (w * 3)
        if h < 10:
            raise RuntimeError(f"no frame of {video} at {t:.2f} s: " + r.stderr.decode("utf-8", "ignore")[-200:])
        out.append(np.frombuffer(r.stdout, np.uint8).reshape(h, w, 3).copy())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("t", type=float)
    ap.add_argument("prefix")
    ap.add_argument("--dip-s", type=float, default=0.3)
    a = ap.parse_args()
    A, B = wav(a.a), wav(a.b)
    n = min(len(A), len(B))
    A, B = A[:n], B[:n]
    T, L = a.t, a.dip_s
    D = A - B
    t_all = np.arange(n) / SR
    out = (t_all < T - L - 0.15) | (t_all > T + 1.0)
    d_out = 20 * np.log10(np.sqrt((D[out].astype(np.float64) ** 2).mean()) + 1e-12)
    ref = 20 * np.log10(np.sqrt((B.astype(np.float64) ** 2).mean()) + 1e-12)
    print(f"difference A - B outside the drop window: {d_out:.1f} dBFS (the clip itself: {ref:.1f} dBFS) -> {'nothing else moved' if d_out < ref - 60 else 'SOMETHING ELSE CHANGED'}")
    pre = (t_all > T - 0.20) & (t_all < T - 0.03)
    dip = 20 * np.log10(np.sqrt((A[pre].astype(np.float64) ** 2).mean()) / (np.sqrt((B[pre].astype(np.float64) ** 2).mean()) + 1e-12) + 1e-12)
    print(f"music + game level just before the kill, A against B: {dip:+.1f} dB (the dip)")
    post = (t_all > T) & (t_all < T + 0.6)
    la, lb = rms_db(band(A, 25, 60)[post]), rms_db(band(B, 25, 60)[post])
    k5 = len(la) // 2
    print(f"25-60 Hz band in the 0.5 s after the kill, A against B per 20 ms: best {float(np.max((la - lb)[:25])):+.1f} dB, mean {float(np.mean((la - lb)[:25])):+.1f} dB (the low hit; the full-band level there is "
          f"already at the limiter: A peak {20 * np.log10(np.abs(A[post]).max()):.1f} dBFS, B peak {20 * np.log10(np.abs(B[post]).max()):.1f} dBFS)")
    sh = (t_all > T - 0.05) & (t_all < T + 0.3)
    a_, b_ = rms_db(A[sh]), rms_db(B[sh])
    print(f"level in the 0.35 s around the kill, A against B: {float(np.max(a_) - np.max(b_)):+.1f} dB at the peak (the gunshot lift + the hit)")
    seg = (t_all > 0.2) & (t_all < T - L - 0.15)
    x, y = A[seg].mean(1).astype(np.float64), B[seg].mean(1).astype(np.float64)
    L2 = 1
    while L2 < 2 * len(x):
        L2 *= 2
    cc = np.fft.irfft(np.fft.rfft(x, L2) * np.conj(np.fft.rfft(y, L2)), L2)
    lag = int(np.argmax(np.concatenate([cc[-2000:], cc[:2000]]))) - 2000
    print(f"A against B before the drop window: lag {lag} samples, correlation {float(np.corrcoef(x, y)[0, 1]):.4f}")
    dd = D[post]
    print(f"added sound in the 0.6 s after the kill: left / right correlation {float(np.corrcoef(dd[:, 0], dd[:, 1])[0, 1]):.4f} (1.0 = the same in both channels: no phase / delay between left and right)")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    lo, hi = max(0.0, T - 1.5), min(n / SR, T + 1.5)
    ta = np.arange(int(lo * 50), int(hi * 50)) / 50.0
    fig, ax = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    ra, rb = rms_db(A), rms_db(B)
    ax[0].plot(ta, rb[int(lo * 50):int(hi * 50)][:len(ta)], label="without the drop moment (B)", color="#888")
    ax[0].plot(ta, ra[int(lo * 50):int(hi * 50)][:len(ta)], label="with it (A)", color="#d33")
    ax[0].axvspan(T - L, T, color="#fc0", alpha=.25, label="music dip")
    ax[0].axvline(T, color="k", lw=1)
    ax[0].set_ylabel("level, dBFS (20 ms)")
    ax[0].legend(loc="lower left")
    ax[0].set_title("loudness around the drop kill")
    ax[1].plot(ta, rms_db(band(B, 25, 60))[int(lo * 50):int(hi * 50)][:len(ta)], color="#888", label="B 25-60 Hz")
    ax[1].plot(ta, rms_db(band(A, 25, 60))[int(lo * 50):int(hi * 50)][:len(ta)], color="#d33", label="A 25-60 Hz")
    ax[1].axvline(T, color="k", lw=1)
    ax[1].set_ylabel("low band, dBFS")
    ax[1].legend(loc="lower left")
    ax[2].plot(ta, rms_db(D)[int(lo * 50):int(hi * 50)][:len(ta)], color="#36c")
    ax[2].axvline(T, color="k", lw=1)
    ax[2].set_ylabel("A - B, dBFS")
    ax[2].set_xlabel("time in the clip, s")
    fig.tight_layout()
    fig.savefig(a.prefix + "_audio.png", dpi=90)
    ts = [T - 0.9, T - 0.4, T - 0.15, T, T + 0.034, T + 0.1, T + 0.4]
    fa, fb = frames(a.a, ts), frames(a.b, ts)
    import cv2
    rowa = np.concatenate([cv2.putText(f.copy(), f"A {t - T:+.2f}s", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 0), 2) for f, t in zip(fa, ts)], 1)
    rowb = np.concatenate([cv2.putText(f.copy(), f"B {t - T:+.2f}s", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 0), 2) for f, t in zip(fb, ts)], 1)
    cv2.imwrite(a.prefix + "_frames.png", cv2.cvtColor(np.concatenate([rowa, rowb], 0), cv2.COLOR_RGB2BGR))
    return 0


if __name__ == "__main__":
    sys.exit(main())
