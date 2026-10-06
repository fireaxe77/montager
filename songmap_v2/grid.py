"""STAGE 1 - beat grid. Onset-strength envelope from a percussive-weighted mix (low band + mid band + a little high band, attack = rise of
the log band energy), beat tracking with the CSV tempo as a PRIOR only (half / double time is checked against onset support), then a
constant-tempo least-squares fit per segment so individual loud peaks cannot move the grid. Events never move the grid."""
import numpy as np
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.signal import butter, find_peaks, sosfiltfilt

HOP = 32                                  # attack-envelope hop in samples (1.45 ms at 22050 Hz): finer than the 256 required
BAND_WIN = {"low": 384, "mid": 192, "high": 96}          # timing windows (samples)
BAND_W = {"low": 1.0, "mid": 0.8, "high": 0.35}          # weights in the grid's onset-strength mix
TEMPO_RANGE = (70.0, 190.0)
MIN_SEG_BEATS = 24                        # a tempo segment needs at least this many observed beats
SEG_SLOPE_TOL = 0.015                     # tempo change smaller than 1.5 % is not a new segment
BEAT_WIN_FRAC = 0.22                      # beat search window (fraction of the period) while tracking
CSV_NEAR = 0.04


def band_signals(y, sr):
    out = {}
    out["low"] = sosfiltfilt(butter(4, 150, "low", fs=sr, output="sos"), y)
    out["mid"] = sosfiltfilt(butter(4, [200, 3000], "band", fs=sr, output="sos"), y)
    out["high"] = sosfiltfilt(butter(4, 4000, "high", fs=sr, output="sos"), y)
    return out


def _env(x, w, n):
    """Centered mean-square envelope sampled every HOP samples."""
    e = uniform_filter1d(x.astype(np.float64) ** 2, w, mode="constant")
    return np.maximum(e[::HOP][:n], 0.0)


def features(y, sr):
    """Per band: linear RMS envelope R (timing), log-energy rise A (detection), at hop HOP. All arrays have the same length."""
    n = len(y) // HOP + 1
    sig = band_signals(y, sr)
    F = {"sr": sr, "dt": HOP / sr, "n": n, "sig": sig, "R": {}, "A": {}, "E": {}}
    for b, x in sig.items():
        e = _env(x, BAND_WIN[b], n)
        floor = max(1e-10, 1e-3 * float(np.percentile(e, 99.5)))
        L = np.log(e + floor)
        lag = max(1, BAND_WIN[b] // (2 * HOP))
        A = np.maximum(0.0, L - np.concatenate([np.full(lag, L[0]), L[:-lag]]))
        F["A"][b] = uniform_filter1d(A, 3)
        F["R"][b] = np.sqrt(e)
        F["E"][b] = e
    return F


def onset_mix(F, bands=None):
    """Grid onset strength at hop HOP: weighted sum of the per-band rises, each scaled by its own 95th percentile."""
    o = np.zeros(F["n"])
    for b, a in F["A"].items():
        if bands and b not in bands:
            continue
        s = float(np.percentile(a, 95)) + 1e-9
        o += BAND_W[b] * np.minimum(a / s, 3.0)
    return o


def onset_linear(F, bands=("low", "mid")):
    """Amplitude (not log) rise of the given bands: a loud hit counts more than a quiet hat. Used for the half / double-time decision."""
    o = np.zeros(F["n"])
    for b in bands:
        R = F["R"][b]
        k = 6
        d = np.maximum(0.0, np.concatenate([R[k:], np.full(k, R[-1])]) - np.concatenate([np.full(k, R[0]), R[:-k]]))
        o += d
    return o


def _coarse(o, ratio=8):
    """Max-pooled copy at hop 256 samples (the analysis rate of the tempo search)."""
    m = len(o) // ratio * ratio
    return o[:m].reshape(-1, ratio).max(1), ratio


def estimate_tempo(o, dt, csv_bpm=None, o_lm=None):
    """Comb search on the coarse envelope + half / double-time check by onset support. Returns (bpm, info)."""
    c, ratio = _coarse(o)
    hop_t = dt * ratio
    cm = maximum_filter1d(c, 3)
    cl = maximum_filter1d(_coarse(o_lm if o_lm is not None else o)[0], 3)        # low + mid only: hats alone never make a beat
    nfr = len(cm)
    bpms = np.arange(TEMPO_RANGE[0], TEMPO_RANGE[1] + 0.001, 0.25)
    sc = np.zeros(len(bpms))
    for i, bpm in enumerate(bpms):
        P = 60.0 / bpm / hop_t
        nb = int((nfr - 1) / P)
        k = np.arange(nb)
        ph = np.arange(0.0, P, 1.0)
        idx = np.clip(np.round(ph[:, None] + P * k[None, :]).astype(int), 0, nfr - 1)
        sc[i] = cm[idx].mean(1).max()
    prior = np.exp(-0.5 * (np.log2(bpms / 125.0) / 0.9) ** 2)
    if csv_bpm:
        near = np.zeros(len(bpms))
        for f in (0.5, 1.0, 2.0):
            near = np.maximum(near, np.exp(-0.5 * ((bpms / (csv_bpm * f) - 1) / 0.03) ** 2))
        prior = prior * (0.6 + 0.8 * near)
    tot = sc * prior
    i0 = int(np.argmax(tot))
    # refine to a local maximum of the raw comb score
    lo, hi = max(0, i0 - 8), min(len(bpms), i0 + 9)
    bpm = float(bpms[lo + int(np.argmax(sc[lo:hi]))])

    def support(b, offset):
        P = 60.0 / b / hop_t
        nb = int((nfr - 1) / P)
        k = np.arange(nb)
        best = -1.0
        bph = 0.0
        for ph in np.arange(0.0, P, 1.0):
            v = cl[np.clip(np.round(ph + P * k).astype(int), 0, nfr - 1)].mean()
            if v > best:
                best, bph = v, ph
        pos = np.clip(np.round(bph + P * (k + offset)).astype(int), 0, nfr - 1)
        return best, float(cl[pos].mean())
    info = {"first": bpm}
    for _ in range(2):                                     # fix half time (upwards) and double time (downwards)
        main, half = support(bpm, 0.5)
        near_double = csv_bpm and abs(bpm * 2 / csv_bpm - 1) < CSV_NEAR
        if bpm * 2 <= TEMPO_RANGE[1] + 0.001 and half >= (0.2 if near_double else 0.25) * main and half > 0.15 * float(np.percentile(cl, 99)):
            bpm *= 2
            info["fixed"] = "double"
            continue
        break
    return bpm, info


def _peak_near(a, i, w):
    lo, hi = max(0, i - w), min(len(a), i + w + 1)
    if hi <= lo:
        return None
    j = lo + int(np.argmax(a[lo:hi]))
    return j


def track_beats(o, dt, bpm, n_total):
    """Beat tracking by prediction + local peak search; the period adapts so tempo changes are followed. Returns (times, strengths, observed)."""
    P0 = 60.0 / bpm
    oS = maximum_filter1d(o, 5)
    # anchor: the strongest onset-comb position of the global tempo
    nfr = len(o)
    Pf = P0 / dt
    best, a0 = -1.0, 0
    for ph in range(0, int(Pf)):
        v = oS[np.clip(np.round(ph + Pf * np.arange(int((nfr - ph) / Pf))).astype(int), 0, nfr - 1)].mean()
        if v > best:
            best, a0 = v, ph
    # move the anchor onto the strongest beat of the song
    ks = np.arange(int((nfr - a0) / Pf))
    pos = np.clip(np.round(a0 + Pf * ks).astype(int), 0, nfr - 1)
    anchor = int(pos[int(np.argmax(oS[pos]))])
    anchor = _peak_near(o, anchor, int(0.05 / dt))
    floor = 0.25 * float(np.percentile(o[o > 0], 90)) if np.any(o > 0) else 1.0

    def walk(direction):
        t, P = anchor * dt, P0
        res = []
        last_obs = []
        while True:
            pred = t + direction * P
            i = int(round(pred / dt))
            if i < 0 or i >= nfr:
                break
            w = int(BEAT_WIN_FRAC * P / dt)
            lo, hi = max(0, i - w), min(nfr, i + w + 1)
            seg = o[lo:hi] * (1.0 - 0.5 * np.abs(np.arange(lo, hi) - i) / max(w, 1))
            j = lo + int(np.argmax(seg))
            if o[j] >= floor:
                tn = j * dt
                obs = True
                step = abs(tn - t)
                last_obs.append(step)
                P = 0.5 * P + 0.5 * float(np.clip(step, 0.7 * P, 1.4 * P)) if len(last_obs) > 3 else P
                # a long run of agreeing intervals pins the period
                if len(last_obs) >= 8:
                    P = float(np.median(last_obs[-8:])) * 0.5 + P * 0.5
            else:
                tn, obs = pred, False
            res.append((tn, float(o[j]) if obs else 0.0, obs))
            t = tn
        return res
    fwd = walk(+1)
    bwd = walk(-1)[::-1]
    allb = bwd + [(anchor * dt, float(o[anchor]), True)] + fwd
    t = np.array([a[0] for a in allb])
    s = np.array([a[1] for a in allb])
    ob = np.array([a[2] for a in allb])
    return t, s, ob


def _robust_line(i, t, w=None, iters=3, tol=0.025):
    """Weighted least squares t = a + b*i with outlier rejection (residual > tol seconds)."""
    w = np.ones(len(i)) if w is None else np.asarray(w, float)
    m = np.ones(len(i), bool)
    a = b = 0.0
    for _ in range(iters):
        if m.sum() < 2:
            break
        A = np.vstack([np.ones(m.sum()), i[m]]).T
        W = np.sqrt(w[m])
        sol = np.linalg.lstsq(A * W[:, None], t[m] * W, rcond=None)[0]
        a, b = float(sol[0]), float(sol[1])
        r = t - (a + b * i)
        m = np.abs(r) <= tol
    return a, b, m


def _split(i, t, w, lo, hi, depth=0):
    """Binary segmentation of the observed beats [lo, hi): split where two lines fit clearly better than one."""
    n = hi - lo
    if n < 2 * MIN_SEG_BEATS or depth > 4:
        return [(lo, hi)]
    a, b, m = _robust_line(i[lo:hi], t[lo:hi], w[lo:hi])
    res0 = np.abs(t[lo:hi] - (a + b * i[lo:hi]))
    sse0 = float(np.sum(np.minimum(res0, 0.1) ** 2))
    if np.median(res0) < 0.006 and sse0 < 0.0004 * n:
        return [(lo, hi)]
    best = None
    for k in range(lo + MIN_SEG_BEATS, hi - MIN_SEG_BEATS + 1, 2):
        a1, b1, _ = _robust_line(i[lo:k], t[lo:k], w[lo:k])
        a2, b2, _ = _robust_line(i[k:hi], t[k:hi], w[k:hi])
        r = np.concatenate([np.abs(t[lo:k] - (a1 + b1 * i[lo:k])), np.abs(t[k:hi] - (a2 + b2 * i[k:hi]))])
        sse = float(np.sum(np.minimum(r, 0.1) ** 2))
        if best is None or sse < best[0]:
            best = (sse, k, b1, b2)
    if best and best[0] < 0.5 * sse0 and abs(best[2] / best[3] - 1) > SEG_SLOPE_TOL:
        return _split(i, t, w, lo, best[1], depth + 1) + _split(i, t, w, best[1], hi, depth + 1)
    return [(lo, hi)]


def fit_grid(o, dt, bpm, dur):
    """Tracker -> robust per-segment constant-tempo fit -> final beat times. Returns a dict (beats, seg, segments, conf, observed...)."""
    t, s, ob = track_beats(o, dt, bpm, len(o))
    idx = np.arange(len(t), dtype=float)
    oi = np.where(ob)[0]
    if len(oi) < 8:
        raise RuntimeError("no steady beat found")
    # observed beats only
    segs = _split(idx[oi], t[oi], s[oi] + 1e-6, 0, len(oi))
    lines = []
    for lo, hi in segs:
        a, b, m = _robust_line(idx[oi][lo:hi], t[oi][lo:hi], s[oi][lo:hi] + 1e-6)
        lines.append((int(oi[lo]), int(oi[hi - 1]), a, b, float(np.mean(m))))
    # segment boundaries in beat-index space: midway between the last beat of one segment and the first of the next
    bounds = [0] + [int((lines[k][1] + lines[k + 1][0]) // 2) + 1 for k in range(len(lines) - 1)] + [len(t)]
    new_t = np.zeros(len(t))
    seg_id = np.zeros(len(t), int)
    for k, (f, l, a, b, _) in enumerate(lines):
        for i in range(bounds[k], bounds[k + 1]):
            new_t[i] = a + b * i
            seg_id[i] = k
    # keep the beat list inside the song; beats before 0 / after the end are dropped, indices renumbered
    keep = (new_t >= -0.02) & (new_t <= dur)
    new_t, seg_id, ob2, s2 = new_t[keep], seg_id[keep], ob[keep], s[keep]
    if len(new_t) < 16:
        raise RuntimeError("no steady beat found")
    segments = []
    for k, (f, l, a, b, frac) in enumerate(lines):
        sel = np.where(seg_id == k)[0]
        if len(sel):
            segments.append({"id": k, "start_beat": int(sel[0]), "end_beat": int(sel[-1]) + 1, "bpm": round(60.0 / b, 3),
                             "start_t": round(float(new_t[sel[0]]), 4), "inlier": round(frac, 3)})
    # residual of the observed beats against their final line
    final_full = np.zeros(len(t))
    for k in range(len(lines)):
        for i in range(bounds[k], bounds[k + 1]):
            final_full[i] = lines[k][2] + lines[k][3] * i
    resid = np.abs(t[ob] - final_full[ob])
    obs_frac = float(np.mean(ob[keep])) if keep.any() else 0.0
    return {"beats": new_t, "seg": seg_id, "observed": ob2, "strength": s2, "segments": segments,
            "resid_ms": float(np.median(resid) * 1000), "obs_frac": obs_frac}


def kick_offsets(beats, kick_times, window=0.06):
    """Signed offset (s) of each kick to the nearest beat, kicks within `window` only."""
    if not len(kick_times) or not len(beats):
        return np.array([])
    j = np.clip(np.searchsorted(beats, kick_times), 1, len(beats) - 1)
    near = np.where(np.abs(beats[j] - kick_times) < np.abs(beats[j - 1] - kick_times), beats[j], beats[j - 1])
    off = kick_times - near
    return off[np.abs(off) <= window]


def bars_and_downbeats(beats, F, kick_times, kick_strength, bpb=4):
    """Bar phase from the accumulated low-band onset evidence per beat position, in windows over the song. Returns
    (phase, confidence, per_window_phases). Low confidence is reported, never hidden."""
    nb = len(beats)
    ev = np.zeros(nb)
    if len(kick_times):
        j = np.clip(np.searchsorted(beats, kick_times), 1, nb - 1)
        near = np.where(np.abs(beats[j] - kick_times) < np.abs(beats[j - 1] - kick_times), j, j - 1)
        ok = np.abs(beats[near] - kick_times) < 0.08
        np.add.at(ev, near[ok], kick_strength[ok])
    low = F["A"]["low"]
    ful = sum(F["A"].values())
    idx = np.clip((beats / F["dt"]).astype(int), 0, F["n"] - 1)
    ev2 = np.array([ful[max(0, k - 4):k + 5].max() for k in idx])
    feat = ev / (ev.mean() + 1e-9) + 0.4 * ev2 / (ev2.mean() + 1e-9)
    scores = np.array([feat[p::bpb].mean() for p in range(bpb)])
    tot = scores.sum() + 1e-9
    order = np.argsort(-scores)
    phase = int(order[0])
    margin = float((scores[order[0]] - scores[order[1]]) / tot) * bpb
    wins = []
    W = bpb * 8
    for a in range(0, max(1, nb - W // 2), W // 2):
        ww = np.array([feat[a:a + W][(p - a) % bpb::bpb].mean() if len(feat[a:a + W][(p - a) % bpb::bpb]) else 0 for p in range(bpb)])
        if ww.sum() > 0:
            wins.append(int(np.argmax(ww)))
    agree = float(np.mean([w == phase for w in wins])) if wins else 0.0
    conf = float(np.clip(0.55 * min(1.0, margin / 0.35) + 0.45 * agree, 0, 1))
    return phase, conf, wins
