"""V7 benchmark helpers (read-only, never imported by the app). An INDEPENDENT kick detector (a plain zero-phase 35-140 Hz band + steepest
envelope rise, no code shared with grid.py / events.py) so V2 never grades itself, plus the kick-to-grid / kill-to-kick metrics."""
import numpy as np

LOW_HZ = (35.0, 140.0)
KICK_BIAS_S = -0.00325     # calibrated on generated kicks with known onset times (calibrate_bias)


def lowband(y, sr, lo=LOW_HZ[0], hi=LOW_HZ[1]):
    """Zero-phase band-pass (FFT mask with raised-cosine edges): no group delay, so onset times are not shifted."""
    n = len(y)
    Y = np.fft.rfft(y)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    m = np.ones_like(f)
    w = 15.0
    m = np.where(f < lo - w, 0.0, np.where(f < lo + w, 0.5 - 0.5 * np.cos(np.pi * (f - (lo - w)) / (2 * w)), m))
    m = np.where(f > hi + w, 0.0, np.where(f > hi - w, 0.5 + 0.5 * np.cos(np.pi * (f - (hi - w)) / (2 * w)), m))
    return np.fft.irfft(Y * m, n)


def _smooth(x, k):
    k = max(1, int(k))
    h = np.hanning(k + 2)[1:-1]
    return np.convolve(x, h / h.sum(), mode="same")


def indep_kicks(y, sr, min_gap_s=0.10):
    """Low-band onsets (times in s, strengths 0..1) = steepest rises of the 5 ms smoothed low-band envelope, parabolic sub-frame refinement."""
    from scipy.signal import find_peaks
    y = np.asarray(y, np.float64)
    if len(y) < sr:
        return np.array([]), np.array([])
    b = lowband(y, sr)
    from scipy.signal import hilbert
    env = _smooth(np.abs(hilbert(b)), int(0.008 * sr))        # analytic envelope: no 2f ripple of a sustained sub-bass
    r = np.sqrt(env + 1e-9)
    d = np.gradient(_smooth(r, int(0.004 * sr))) * sr
    d[d < 0] = 0
    hop = int(0.01 * sr)
    cm = d[:len(d) // hop * hop].reshape(-1, hop).max(1)
    if not len(cm) or cm.max() <= 0:
        return np.array([]), np.array([])
    ref = float(np.percentile(cm[cm > 0], 90)) if np.any(cm > 0) else 0.0
    pk, _ = find_peaks(d, height=max(0.18 * ref, 1e-6), distance=int(min_gap_s * sr), prominence=0.12 * ref)
    t, s = [], []
    pkh = d[pk]
    keep = np.ones(len(pk), bool)
    for q in range(len(pk)):                         # a smaller peak shortly after a bigger one is the tail of the same kick
        w = (pk < pk[q]) & (pk > pk[q] - int(0.3 * sr))
        if np.any(pkh[w] * 0.6 > pkh[q]):
            keep[q] = False
    for i in pk[keep]:
        if 1 <= i < len(d) - 1:
            a, c, e = d[i - 1], d[i], d[i + 1]
            den = a - 2 * c + e
            off = 0.5 * (a - e) / den if abs(den) > 1e-12 else 0.0
            t.append((i + float(np.clip(off, -1, 1))) / sr - KICK_BIAS_S)
            s.append(c)
    t, s = np.array(t), np.array(s)
    if len(s):
        s = s / s.max()
    return t, s


def strong_kicks(y, sr, thr=0.3):
    t, s = indep_kicks(y, sr)
    return t[s >= thr] if len(t) else t


def nearest(times, ref):
    """Signed distance (s) of every time to the nearest reference time (inf if ref is empty)."""
    times, ref = np.asarray(times, float), np.asarray(ref, float)
    if not len(ref):
        return np.full(len(times), np.inf)
    ref = np.sort(ref)
    j = np.clip(np.searchsorted(ref, times), 1, max(len(ref) - 1, 1))
    a = times - ref[np.clip(j - 1, 0, len(ref) - 1)]
    c = times - ref[np.clip(j, 0, len(ref) - 1)]
    return np.where(np.abs(a) <= np.abs(c), a, c)


def judged_kicks(kicks, grids, window=0.06):
    """The kicks all grids are judged on: within `window` of ANY of the given grids (a kick that is syncopated against every grid is not a grid test)."""
    k = np.asarray(kicks, float)
    keep = np.zeros(len(k), bool)
    for b in grids:
        keep |= np.abs(nearest(k, np.asarray(b, float))) <= window
    return k[keep]


def grid_stats(beats, kicks):
    d = np.abs(nearest(kicks, beats)) * 1000.0
    d = d[np.isfinite(d)]
    if not len(d):
        return {"n": 0, "median_ms": None, "p95_ms": None, "hit30": None}
    return {"n": int(len(d)), "median_ms": round(float(np.median(d)), 2), "p95_ms": round(float(np.percentile(d, 95)), 2),
            "hit30": round(float(np.mean(d <= 30.0)), 3)}


def beat_stats(beats, kicks, frac=0.15):
    """Beat-to-kick error: for every beat that has a strong kick within `frac` of a beat period, the distance to that kick. Syncopated kicks
    never count against the grid; `cov` = share of beats that have such a kick (a grid shifted by more than `frac` of a beat has cov ~ 0)."""
    b = np.asarray(beats, float)
    if len(b) < 3 or not len(kicks):
        return {"n": 0, "median_ms": None, "p95_ms": None, "cov": 0.0}
    P = float(np.median(np.diff(b)))
    d = np.abs(nearest(b, kicks))
    ok = d <= frac * P
    if not ok.any():
        return {"n": 0, "median_ms": None, "p95_ms": None, "cov": 0.0}
    dd = d[ok] * 1000.0
    return {"n": int(ok.sum()), "median_ms": round(float(np.median(dd)), 2), "p95_ms": round(float(np.percentile(dd, 95)), 2),
            "cov": round(float(ok.mean()), 3)}


def f1_stats(beats, kicks, tol=0.025):
    """Octave-fair agreement of a grid with the kicks: precision = share of beats with a kick within +-tol, recall = share of kicks with a beat within
    +-tol, f1 = their harmonic mean (a double-time grid loses precision, a half-time grid loses recall)."""
    b = np.asarray(beats, float)
    k = np.asarray(kicks, float)
    if len(b) < 3 or not len(k):
        return {"prec": 0.0, "rec": 0.0, "f1": 0.0}
    prec = float(np.mean(np.abs(nearest(b, k)) <= tol))
    rec = float(np.mean(np.abs(nearest(k, b)) <= tol))
    f1 = 0.0 if prec + rec == 0 else 2 * prec * rec / (prec + rec)
    return {"prec": round(prec, 3), "rec": round(rec, 3), "f1": round(f1, 3)}


def calibrate_bias(sr=22050):
    """Median (detected - true) over generated kicks (pitch-dropping sine, 1 ms attack) at 90 / 128 / 160 BPM: the detector's own constant lag."""
    errs = []
    for bpm in (90, 128, 160):
        y, truth = gen_kicks(bpm, 40.0, sr)
        t, s = indep_kicks(y, sr)
        d = nearest(truth[2:-2], t)
        errs += list(-d[np.abs(d) < 0.03])
    return float(np.median(errs)) if errs else 0.0


def gen_kicks(bpm, dur, sr=22050, offset=0.5):
    n = int(dur * sr)
    y = np.zeros(n)
    P = 60.0 / bpm
    truth = np.arange(offset, dur - 0.5, P)
    k = int(0.25 * sr)
    tt = np.arange(k) / sr
    ph = 2 * np.pi * (45 * tt + 75 * (1 - np.exp(-tt * 30)) / 30)
    kick = np.sin(ph) * np.exp(-tt * 14) * np.minimum(1.0, tt / 0.001)
    for t0 in truth:
        i = int(round(t0 * sr))
        y[i:i + k] += kick[:max(0, min(k, n - i))]
    return y, truth


# ---------------------------------------------------------------------------------------------------------------- song level
def drops_of(m):
    return [round(float(d["t"]), 1) for d in m.get("drops", [])]


def bench_song(M, path, csv_bpm=None, v2_builder=None, say=None):
    """V1 map, V2 map and the auto choice for one song, all judged on the INDEPENDENT kicks. Never writes caches. Returns a dict."""
    import time
    import songmap_v2
    from songmap_v2 import timebase, build
    r = {"song": path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1], "path": path, "csv_bpm": csv_bpm}
    t0 = time.time()
    v1 = M.build_song_map(path, csv_bpm)
    r["v1_s"] = round(time.time() - t0, 1)
    t0 = time.time()
    try:
        v2 = (v2_builder or songmap_v2.build_songmap_v2)(path, csv_bpm, deadline=time.monotonic() + 120, v1_bpm=v1["bpm"])
        r["v2_s"] = round(time.time() - t0, 1)
    except Exception as ex:                                              # a V2 failure is a V1 result in production
        v2 = None
        r["v2_error"] = f"{type(ex).__name__}: {ex}"
    y, sr = timebase.decode(path)
    kt, ks = indep_kicks(y, sr)
    kicks = kt[ks >= 0.3] if len(kt) else kt
    r["dur"] = round(len(y) / sr, 1)
    r["n_kicks"] = int(len(kicks))
    grids = [np.asarray(v1["beats"], float)] + ([np.asarray(v2["beats"], float)] if v2 else [])
    jk = kicks
    r["n_judged"] = int(len(jk))
    r["v1"] = {"bpm": round(v1["bpm"], 2), "n_beats": len(v1["beats"]), "drops": drops_of(v1), **beat_stats(v1["beats"], jk), **f1_stats(v1["beats"], jk)}
    if v2:
        dec = build.auto_decision(v1, v2)
        r["v2"] = {"bpm": round(v2["bpm"], 2), "n_beats": len(v2["beats"]), "conf": v2["v2"]["grid_confidence"], "drops": drops_of(v2),
                   **beat_stats(v2["beats"], jk), **f1_stats(v2["beats"], jk)}
        r["auto"] = {"choice": dec["choice"], "reason": dec["reason"]}
        src = r["v2"] if dec["choice"] == "v2" else r["v1"]
        r["auto"].update({k: src[k] for k in ("n", "median_ms", "p95_ms", "cov", "prec", "rec", "f1")})
        r["auto"]["gate"] = {k: dec[k] for k in dec if k not in ("choice", "reason")}
    if say:
        say(fmt_row(r))
    return r


def fmt_row(r):
    v1, v2, a = r["v1"], r.get("v2"), r.get("auto")
    f = lambda x: "  -  " if x is None else f"{x:5.1f}"
    s = f"{r['song'][:34]:34} V1 {v1['bpm']:6.1f} med {f(v1['median_ms'])} p95 {f(v1['p95_ms'])} cov {v1['cov']:.2f}"
    if v2:
        s += f" | V2 {v2['bpm']:6.1f} conf {v2['conf']:.2f} med {f(v2['median_ms'])} p95 {f(v2['p95_ms'])} cov {v2['cov']:.2f} | auto {a['choice']} med {f(a['median_ms'])} p95 {f(a['p95_ms'])} cov {a['cov']:.2f}"
    else:
        s += " | V2 ERROR " + r.get("v2_error", "")[:60]
    return s + f" | drops V1 {len(v1['drops'])} V2 {len(v2['drops']) if v2 else '-'} | judged {r['n_judged']}/{r['n_kicks']}"
