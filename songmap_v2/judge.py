"""V7 gate judge: a kick-onset detector that shares NOTHING with the grid builder (events.py / grid.py): a log-compressed spectral flux (SuperFlux style,
max-filtered reference frame) over the 35-140 Hz STFT bins, peak picked, parabolic sub-frame time, one constant lag calibrated on generated kicks with
known onset times. The per-song gate in build.py (V2 vs V1) judges both grids with it. (The benchmark in bench.py grades with yet another detector.)"""
import numpy as np
from scipy.ndimage import maximum_filter1d
from scipy.signal import find_peaks

N_FFT = 2048
HOP = 128
LO_HZ, HI_HZ = 35.0, 140.0
LAG_S = -0.0357                   # constant calibrated by calibrate_lag() on generated kicks with known onset times (the flux peak leads the onset by ~35 ms)
STRONG = 0.5                     # relative strength of a judge kick


def flux(y, sr):
    """Low-band superflux onset strength at hop HOP (array) and its frame times."""
    y = np.asarray(y, np.float32)
    n = (len(y) - N_FFT) // HOP + 1
    if n < 8:
        return np.zeros(0), np.zeros(0)
    win = np.hanning(N_FFT).astype(np.float32)
    k0, k1 = int(np.floor(LO_HZ * N_FFT / sr)), int(np.ceil(HI_HZ * N_FFT / sr)) + 1
    idx = np.arange(n)[:, None] * HOP + np.arange(N_FFT)[None, :]
    out = np.empty((n, k1 - k0), np.float32)
    for s in range(0, n, 4096):                                   # chunks keep the frame matrix small
        e = min(n, s + 4096)
        X = np.abs(np.fft.rfft(y[idx[s:e]] * win, axis=1))[:, k0:k1]
        out[s:e] = np.log1p(100.0 * X)
    ref = maximum_filter1d(out, size=3, axis=1)                   # vibrato / bass-note glide suppression
    lag = max(1, int(round(0.012 * sr / HOP)))
    prev = np.vstack([np.repeat(ref[:1], lag, 0), ref[:-lag]])
    f = np.maximum(0.0, out - prev).sum(1)
    return f, (np.arange(n) * HOP + N_FFT / 2) / sr


def kicks(y, sr):
    """(times, strengths 0..1) of the low-band onsets."""
    f, t = flux(y, sr)
    if not len(f) or f.max() <= 0:
        return np.array([]), np.array([])
    ref = float(np.percentile(f, 95)) + 1e-9
    pk, _ = find_peaks(f, height=0.15 * ref, distance=max(1, int(0.09 * sr / HOP)), prominence=0.1 * ref)
    out_t, out_s = [], []
    for i in pk:
        off = 0.0
        if 1 <= i < len(f) - 1:
            a, c, e = f[i - 1], f[i], f[i + 1]
            den = a - 2 * c + e
            off = 0.5 * (a - e) / den if abs(den) > 1e-12 else 0.0
        out_t.append(float(t[i] + np.clip(off, -1, 1) * HOP / sr) - LAG_S)
        out_s.append(float(f[i]))
    out_t, out_s = np.array(out_t), np.array(out_s)
    if len(out_s):
        out_s = np.minimum(1.0, out_s / ref)                       # 1.0 = as strong as the 95th percentile of the flux
    return out_t, out_s


def strong(y, sr, thr=STRONG):
    t, s = kicks(y, sr)
    return t[s >= thr] if len(t) else t


def _near(times, ref):
    times, ref = np.asarray(times, float), np.sort(np.asarray(ref, float))
    if not len(ref):
        return np.full(len(times), np.inf)
    j = np.clip(np.searchsorted(ref, times), 1, max(len(ref) - 1, 1))
    a = times - ref[np.clip(j - 1, 0, len(ref) - 1)]
    c = times - ref[np.clip(j, 0, len(ref) - 1)]
    return np.where(np.abs(a) <= np.abs(c), a, c)


def beat_stats(beats, kick_t, tol=0.025, frac=0.15):
    """Judge numbers of one grid: median / p95 distance (ms) of the beats that have a judge kick within `frac` of a beat period, and the octave-fair
    F1 of (beats with a kick within tol, kicks with a beat within tol)."""
    b = np.asarray(beats, float)
    k = np.asarray(kick_t, float)
    r = {"n_kicks": int(len(k)), "median_ms": None, "p95_ms": None, "f1": 0.0}
    if len(b) < 4 or len(k) < 8:
        return r
    P = float(np.median(np.diff(b)))
    d = np.abs(_near(b, k))
    ok = d <= frac * P
    if ok.any():
        dd = d[ok] * 1000.0
        r["median_ms"], r["p95_ms"] = round(float(np.median(dd)), 2), round(float(np.percentile(dd, 95)), 2)
    prec = float(np.mean(d <= tol))
    rec = float(np.mean(np.abs(_near(k, b)) <= tol))
    r["f1"] = 0.0 if prec + rec == 0 else round(2 * prec * rec / (prec + rec), 3)
    return r


def calibrate_lag(sr=22050):
    """Median (detected - true) over generated kicks with known onsets (pitch-dropping sine, 1 ms attack) at 90 / 128 / 160 BPM."""
    from .bench import gen_kicks
    errs = []
    for bpm in (90, 128, 160):
        y, truth = gen_kicks(bpm, 40.0, sr)
        t, s = kicks(y, sr)
        if len(t):
            d = -_near(truth[2:-2], t)
            errs += list(d[np.abs(d) < 0.05])
    return float(np.median(errs)) if errs else 0.0
