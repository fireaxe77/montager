"""STAGE 1 - beat grid. Onset-strength envelope from a percussive-weighted mix (low band + mid band + a little high band, attack = rise of
the log band energy), beat tracking with the CSV tempo as a PRIOR only (half / double time is checked against onset support), then a
constant-tempo least-squares fit per segment so individual loud peaks cannot move the grid. Events never move the grid."""
import numpy as np
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.signal import butter, find_peaks, sosfiltfilt

HOP = 32                                  # attack-envelope hop in samples (1.45 ms at 22050 Hz): finer than the 256 required
BAND_WIN = {"low": 384, "mid": 192, "high": 96}          # timing windows (samples)
BAND_W = {"low": 1.0, "mid": 0.8, "high": 0.35}          # weights in the grid's onset-strength mix
TEMPO_RANGE = (70.0, 190.0)               # range of the comb estimate
TEMPO_MIN, TEMPO_MAX = 60.0, 200.0        # V6.9.5.2: the grid never has a tempo (or a segment tempo) outside this range
ON_GRID_S = 0.025                         # a kick is "on the grid" within +-25 ms
MERGE_FRAC = 0.015                        # candidate tempos closer than this are one candidate
LOCAL_FRAC = 0.03                         # local tempo refinement range around a candidate (+-3 %)
FAST_PEN = (180.0, 0.002)                 # score penalty per BPM above 180 (200 BPM = -0.04)
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


def n_frames(n_samples):
    """Number of hop-HOP frames covering n_samples: ceil(n / HOP). (The 6.9.5 code used n // HOP + 1, one frame too many whenever the sample
    count is an exact multiple of HOP, so the band envelopes (ceil) and the mix array (floor + 1) were one frame apart -> ValueError.)"""
    return (int(n_samples) + HOP - 1) // HOP


def _env(x, w, n):
    """Centered mean-square envelope sampled every HOP samples, exactly n frames (padded with the last value if the slice is short)."""
    e = uniform_filter1d(x.astype(np.float64) ** 2, w, mode="constant")
    e = np.maximum(e[::HOP][:n], 0.0)
    if len(e) < n:
        e = np.concatenate([e, np.full(n - len(e), e[-1] if len(e) else 0.0)])
    return e


def features(y, sr):
    """Per band: linear RMS envelope R (timing), log-energy rise A (detection), at hop HOP. All arrays have the same length."""
    n = n_frames(len(y))
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


def candidate_tempos(est, v1_bpm=None, csv_bpm=None):
    """Tempo hypotheses: the V2 estimate, the V1 BPM and the CSV tempo, each at 0.5x / 1x / 2x, only 60-200 BPM, candidates within 1.5 % merged.
    Returns [{"bpm", "src": [...]}] sorted by BPM."""
    raw = []
    for src, b in (("v2", est), ("v1", v1_bpm), ("csv", csv_bpm)):
        try:
            b = float(b)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(b) or b <= 0:
            continue
        for f in (0.5, 1.0, 2.0):
            if TEMPO_MIN <= b * f <= TEMPO_MAX:
                raw.append((b * f, f"{src}{'' if f == 1.0 else ' x' + format(f, 'g')}"))
    raw.sort()
    groups = []
    for b, src in raw:
        if groups and b / groups[-1][-1][0] - 1 <= MERGE_FRAC:
            groups[-1].append((b, src))
        else:
            groups.append([(b, src)])
    return [{"bpm": float(np.mean([g[0] for g in grp])), "src": [g[1] for g in grp]} for grp in groups]


def _rayleigh(t, w, bpm, frac=LOCAL_FRAC, step=0.0001):
    """Phase-coherence scan of the onset times over tempo bpm*(1 +- frac): returns (period, first_beat_time) of the most coherent grid."""
    lo, hi = max(bpm * (1 - frac), TEMPO_MIN), min(bpm * (1 + frac), TEMPO_MAX)
    bpms = np.arange(lo, hi + 1e-9, bpm * step)
    per = 60.0 / bpms
    best, bz, bp = -1.0, 0j, per[0]
    for s in range(0, len(per), 150):                                   # chunks keep the (kicks x tempos) matrix small
        pp = per[s:s + 150]
        z = (w[:, None] * np.exp(2j * np.pi * t[:, None] / pp[None, :])).sum(0)
        j = int(np.argmax(np.abs(z)))
        if abs(z[j]) > best:
            best, bz, bp = float(abs(z[j])), z[j], float(pp[j])
    return bp, float(np.angle(bz) / (2 * np.pi) * bp)


def _refine(t, w, a, P, bpm0, tols=(0.04, 0.03, ON_GRID_S)):
    """Least squares of beat index against onset time (onsets within a shrinking tolerance of the grid), tempo kept within +-3 % of the candidate."""
    for tol in tols:
        k = np.round((t - a) / P)
        m = np.abs(t - (a + k * P)) <= tol
        if m.sum() < 4 or np.ptp(k[m]) < 3:
            break
        sw = np.sqrt(w[m])
        sol = np.linalg.lstsq(np.vstack([np.ones(m.sum()), k[m]]).T * sw[:, None], t[m] * sw, rcond=None)[0]
        a2, P2 = float(sol[0]), float(sol[1])
        if not (60.0 / (bpm0 * (1 + LOCAL_FRAC)) <= P2 <= 60.0 / (bpm0 * (1 - LOCAL_FRAC))):
            break
        a, P = a2, P2
    return a, P


def _near(times, ref):
    """Signed distance of every time to the nearest reference time."""
    if not len(times) or not len(ref):
        return np.array([])
    j = np.clip(np.searchsorted(ref, times), 1, len(ref) - 1)
    d0, d1 = times - ref[j - 1], times - ref[j]
    return np.where(np.abs(d0) <= np.abs(d1), d0, d1)


def _grid_times(a, P, dur):
    k0 = int(np.ceil((-0.02 - a) / P))
    k1 = int(np.floor((dur - a) / P))
    return a + P * np.arange(k0, k1 + 1)


def score_candidate(a, P, kick_t, hit_t, dur):
    """On-grid kick fraction (+-25 ms), on-grid share of all strong low / mid hits (snares too), beat hit rate (share of the beats inside the
    active span with such a hit on them) and the penalised score (0.6 / 0.2 / 0.2). A faster tempo has to explain MORE kicks than the slower one to win (double time is penalised above 180 BPM)."""
    g = _grid_times(a, P, dur)
    bpm = 60.0 / P
    kf = float(np.mean(np.abs(_near(kick_t, g)) <= ON_GRID_S)) if len(kick_t) else 0.0
    lo, hi = (float(kick_t.min()), float(kick_t.max())) if len(kick_t) else (0.0, dur)
    span = g[(g >= lo - 0.5 * P) & (g <= hi + 0.5 * P)]
    cov = float(np.mean(np.abs(_near(span, hit_t)) <= ON_GRID_S)) if len(span) and len(hit_t) else 0.0
    hf = float(np.mean(np.abs(_near(hit_t, g)) <= ON_GRID_S)) if len(hit_t) else 0.0
    pen = FAST_PEN[1] * max(0.0, bpm - FAST_PEN[0]) + 0.003 * max(0.0, 75.0 - bpm)
    prior = 0.01 * (np.log2(min(bpm, 180.0)) - np.log2(120.0))      # tie-breaker only: between equal explanations the faster (<= 180) wins
    return {"kick_frac": kf, "hit_frac": hf, "coverage": cov, "penalty": float(pen), "score": float(0.6 * kf + 0.2 * hf + 0.2 * cov + prior - pen)}


def _fit_span(kt, ks, bpm0, t0, t1):
    """Tempo / phase of the kicks inside [t0, t1): coherence scan within +-3 % of bpm0 (60-200 only), then the least-squares refinement."""
    m = (kt >= t0) & (kt < t1)
    if m.sum() < 8:
        return None
    P, a = _rayleigh(kt[m], ks[m], bpm0)
    return _refine(kt[m], ks[m], a, P, bpm0)


def tempo_segments(kt, ks, a, P, dur):
    """Tempo changes: windows of 24 beats are locked on their own kicks (+-25 % around the global tempo, 60-200 BPM only); consecutive windows
    that agree within 2 % form a segment, windows that fit badly (a change happens inside them) are skipped. Returns [(t_start, a, P)] with the
    segment's own line, or [] when the song is one steady tempo. Segments outside 60-200 BPM are never created."""
    bpm0 = 60.0 / P
    win = 24 * P
    wins = []
    for t0 in np.arange(0.0, max(dur - win, 0.0) + 1e-9, 8 * P):
        m = (kt >= t0) & (kt < t0 + win)
        if m.sum() < 12:
            continue
        Pw, aw = _rayleigh(kt[m], ks[m], bpm0, frac=0.25)
        aw, Pw = _refine(kt[m], ks[m], aw, Pw, 60.0 / Pw)
        kf = float(np.mean(np.abs(_near(kt[m], aw + Pw * np.arange(-2, int(win / Pw) + 4) + np.floor((t0 - aw) / Pw) * Pw)) <= ON_GRID_S))
        if kf >= 0.8 and TEMPO_MIN <= 60.0 / Pw <= TEMPO_MAX:
            wins.append((t0, t0 + win, 60.0 / Pw))
    groups = []
    for w in wins:
        if groups and abs(w[2] / np.median([x[2] for x in groups[-1]]) - 1) <= 0.02:
            groups[-1].append(w)
        else:
            groups.append([w])
    groups = [g for g in groups if len(g) >= 2]                       # one window alone is not a segment (>= 32 beats of agreement)
    if len(groups) < 2:
        return []
    out = []
    for i, g in enumerate(groups):
        t0 = 0.0 if i == 0 else 0.5 * (groups[i - 1][-1][1] + g[0][0])
        t1 = dur if i == len(groups) - 1 else 0.5 * (g[-1][1] + groups[i + 1][0][0])
        fit = _fit_span(kt, ks, float(np.median([x[2] for x in g])), t0, t1)
        if fit is None or not (TEMPO_MIN <= 60.0 / fit[1] <= TEMPO_MAX):
            return []
        out.append((t0, fit[0], fit[1]))
    return out


def _assemble(lines, dur):
    """Beat times from per-segment lines [(t_start, a, P)]: every segment lays beats a + k P from its start; a segment's first beat is the first
    of its line that is a plausible beat after the previous segment's last. None when the result is not a plausible beat sequence (an interval
    outside 60-200 BPM)."""
    t_all, seg_all = [], []
    for s, (t0, a_, P_) in enumerate(lines):
        t1 = lines[s + 1][0] if s + 1 < len(lines) else dur + 1.0
        k0 = int(np.ceil((max(t0, -0.02) - a_) / P_))
        if t_all and len(t_all[-1]):
            k0 = max(k0, int(np.ceil((t_all[-1][-1] + 0.6 * P_ - a_) / P_)))
        k1 = int(np.floor((min(t1 - 1e-9, dur) - a_) / P_))
        if k1 < k0:
            continue
        t_all.append(a_ + P_ * np.arange(k0, k1 + 1))
        seg_all.append(np.full(k1 - k0 + 1, s))
    if not t_all:
        return None
    t, sid = np.concatenate(t_all), np.concatenate(seg_all)
    d = np.diff(t)
    if len(t) < 16 or np.any(d < 60.0 / TEMPO_MAX * 0.93) or np.any(d > 60.0 / TEMPO_MIN * 1.07):
        return None
    keep = (t >= -0.02) & (t <= dur)
    return t[keep], sid[keep]


def lock_grid(kick_t, kick_s, hit_t, dur, est_bpm, v1_bpm=None, csv_bpm=None):
    """V6.9.5.2 tempo lock. Candidates (V2 estimate, V1 BPM, CSV tempo; x0.5 / x1 / x2; 60-200 only; merged within 1.5 %) -> for each the phase from
    the kick onsets (coherence scan), local tempo refinement (+-3 %, least squares of beat index vs onset time), score = on-grid kick fraction
    (+-25 ms) blended with the beat hit rate, penalised above 180 BPM. The best candidate is split into tempo segments only where the evidence
    asks for it (never outside 60-200 BPM). Returns (beats, seg ids, segments, info)."""
    kt = np.asarray(kick_t, float)
    ks = np.asarray(kick_s, float)
    if len(kt) < 8:
        raise RuntimeError("no steady beat found")
    cands = candidate_tempos(est_bpm, v1_bpm, csv_bpm) or [{"bpm": float(np.clip(est_bpm, TEMPO_MIN, TEMPO_MAX)), "src": ["v2 clipped"]}]
    best = None
    table = []
    for c in cands:
        P, a = _rayleigh(kt, ks, c["bpm"])
        a, P = _refine(kt, ks, a, P, c["bpm"])
        sc = score_candidate(a, P, kt, hit_t, dur)
        row = {"bpm_in": round(c["bpm"], 3), "src": c["src"], "bpm": round(60.0 / P, 3), **{k: round(v, 4) for k, v in sc.items()}}
        table.append(row)
        if best is None or sc["score"] > best[0]:
            best = (sc["score"], a, P)
    _, a, P = best
    lines = [(0.0, a, P)]
    kf1 = float(np.mean(np.abs(_near(kt, _grid_times(a, P, dur))) <= ON_GRID_S))
    seg_lines = tempo_segments(kt, ks, a, P, dur) if kf1 < 0.97 else []       # a grid that already explains the kicks is one steady tempo
    asm = None
    if seg_lines:
        asm = _assemble(seg_lines, dur)
        if asm is not None and float(np.mean(np.abs(_near(kt, asm[0])) <= ON_GRID_S)) >= kf1 + 0.05:      # clearly more kicks explained
            lines = seg_lines
        else:
            asm = None
    if asm is None:
        lines = [(0.0, a, P)]
        asm = _assemble(lines, dur)
        if asm is None:
            raise RuntimeError("no steady beat found")
    beats, sid = asm
    segments = []
    for s, (_, a_, b_) in enumerate(lines):
        sel = np.where(sid == s)[0]
        if len(sel):
            segments.append({"id": s, "start_beat": int(sel[0]), "end_beat": int(sel[-1]) + 1, "bpm": round(60.0 / b_, 3),
                             "start_t": round(float(beats[sel[0]]), 4), "inlier": round(float(np.mean(np.abs(_near(kt, beats)) <= ON_GRID_S)), 3)})
    return beats, sid, segments, {"candidates": table, "chosen_bpm": round(60.0 / P, 3)}


def periodicity(o, dt, period, tol=ON_GRID_S):
    """Periodicity of the onset envelope at the chosen tempo: the normalised autocorrelation of the (mean-removed) envelope at the beat period,
    two beats and a bar (4 beats), each taken at its best lag within +-25 ms; the largest of the three, 0..1."""
    x = np.asarray(o, float)
    if len(x) < 64 or period <= 0:
        return 0.0
    x = x - x.mean()
    e0 = float(np.dot(x, x))
    if e0 <= 1e-12:
        return 0.0
    n = 1 << int(np.ceil(np.log2(2 * len(x))))
    f = np.fft.rfft(x, n)
    ac = np.fft.irfft(f * np.conj(f), n)[:len(x)] / e0
    w = max(1, int(round(tol / dt)))
    best = 0.0
    for mult in (1, 2, 4):
        L = int(round(mult * period / dt))
        if L + w >= len(ac):
            continue
        best = max(best, float(ac[max(1, L - w):L + w + 1].max()))
    return float(np.clip(best, 0.0, 1.0))


def grid_confidence(beats, kick_t, o, dt):
    """HONEST confidence in 0..1: 0.7 x the share of the strong low-band onsets (kicks / bass) that land within +-25 ms of the grid, 0.3 x the
    periodicity of the onset envelope `o` at the grid's tempo (see periodicity()). Returns (confidence, components)."""
    beats = np.asarray(beats, float)
    kt = np.asarray(kick_t, float)
    kf = float(np.mean(np.abs(_near(kt, beats)) <= ON_GRID_S)) if len(kt) and len(beats) > 1 else 0.0
    per = periodicity(o, dt, float(np.median(np.diff(beats)))) if len(beats) > 3 else 0.0
    conf = float(np.clip(0.7 * kf + 0.3 * per, 0.0, 1.0))
    return conf, {"kick_on_grid": round(kf, 4), "periodicity": round(per, 4), "n_kicks": int(len(kt))}


def kick_grid_stats(beats, kick_t):
    """Median / p95 distance (ms) of the kicks to their nearest beat (no window)."""
    d = np.abs(_near(np.asarray(kick_t, float), np.asarray(beats, float))) * 1000.0
    if not len(d):
        return {"n": 0, "median_ms": None, "p95_ms": None}
    return {"n": int(len(d)), "median_ms": round(float(np.median(d)), 2), "p95_ms": round(float(np.percentile(d, 95)), 2)}


def fit_grid(o, dt, bpm, dur, kick_t=None, kick_s=None, hit_t=None, v1_bpm=None, csv_bpm=None):
    """Onset envelope + tempo estimate (+ optional kick onsets, V1 BPM, CSV tempo) -> the locked grid as a dict (beats, seg, segments, observed,
    strength, resid_ms, obs_frac, lock). Without kick onsets the peaks of the envelope are used."""
    if kick_t is None:
        pk, _ = find_peaks(o, height=float(np.percentile(o, 90)) if len(o) else 1.0, distance=max(1, int(0.06 / dt)))
        kick_t, kick_s = pk * dt, np.asarray(o)[pk]
    kt = np.asarray(kick_t, float)
    ks = np.asarray(kick_s, float) if kick_s is not None else np.ones(len(kt))
    ht = np.asarray(hit_t if hit_t is not None else kt, float)
    beats, sid, segments, lock = lock_grid(kt, ks, ht, dur, bpm, v1_bpm, csv_bpm)
    d = np.abs(_near(kt, beats))
    near_ok = np.zeros(len(beats), bool)
    stren = np.zeros(len(beats))
    if len(kt):
        j = np.clip(np.searchsorted(beats, kt), 1, len(beats) - 1)
        nb = np.where(np.abs(beats[j] - kt) < np.abs(beats[j - 1] - kt), j, j - 1)
        okk = np.abs(beats[nb] - kt) <= ON_GRID_S
        near_ok[nb[okk]] = True
        np.maximum.at(stren, nb[okk], ks[okk])
    return {"beats": beats, "seg": sid, "observed": near_ok, "strength": stren, "segments": segments,
            "resid_ms": float(np.median(d) * 1000) if len(d) else 0.0, "obs_frac": float(np.mean(near_ok)), "lock": lock}


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
