"""STAGE 2 - events. Onsets per band (low = kick / bass, mid = snare / clap, high = hats / transients) plus a full-band strong-transient
channel. Time = the transient START (50 % point of the amplitude rise, parabolic sub-frame interpolation of the detection peak), not the
peak maximum. Every event is then associated with the grid (nearest subdivision) WITHOUT ever moving the grid; an event further from the
grid than the tolerance is `off_grid` and keeps its raw time."""
import numpy as np
from scipy.signal import find_peaks

OFF_GRID_MS = 35.0                  # absolute tolerance
OFF_GRID_FRAC = 0.15                # ... or this share of the subdivision, whichever is smaller
SUBDIVISIONS = (1.0, 0.5, 0.25, 0.125)
MIN_DIST_S = {"low": 0.06, "mid": 0.05, "high": 0.035}
MIN_RISE = 0.9                      # log-energy rise (nats) for a detection peak
REL_STRENGTH = 0.10                 # events weaker than this share of the song's strong ones are dropped
BASS_SUSTAIN = 0.22                 # low-band energy kept 80-250 ms after the hit (share of the hit) = bass hit, else kick
FPS = 60.0


def _parabolic(a, i):
    if i <= 0 or i >= len(a) - 1:
        return float(i)
    y0, y1, y2 = a[i - 1], a[i], a[i + 1]
    d = y0 - 2 * y1 + y2
    return float(i) if d == 0 else float(i + 0.5 * (y0 - y2) / d)


def refine_start(R, pk, dt, back=16, fwd=16):
    """Transient start: the 50 % crossing of the ENERGY rise (a centred window's mean-square ramps linearly across a step onset, so its
    50 % point is the onset itself) around detection peak `pk`, linear interpolation. Returns (time_s, rise) with rise = height of the
    rise in linear amplitude (sqrt of the energy levels)."""
    lo = max(0, pk - back)
    hi = min(len(R), pk + fwd + 1)
    seg = R[lo:hi]
    base = float(seg[: back + 1].min()) if pk - lo > 0 else float(seg.min())
    j_top = lo + int(np.argmax(R[max(0, pk - 2):hi])) + (max(0, pk - 2) - lo)
    j_top = max(j_top, lo)
    top = float(R[min(len(R) - 1, max(0, j_top))])
    rise_e = top - base
    rise = float(np.sqrt(max(top, 0.0)) - np.sqrt(max(base, 0.0)))
    if rise_e <= 0:
        return pk * dt, 0.0
    tgt = base + 0.5 * rise_e
    j = lo
    while j < j_top and R[j] < tgt:
        j += 1
    if j <= lo:
        return j * dt, rise
    r0, r1 = R[j - 1], R[j]
    f = 0.0 if r1 == r0 else (tgt - r0) / (r1 - r0)
    return (j - 1 + float(np.clip(f, 0, 1))) * dt, rise


def detect(F):
    """Raw events from the band attack envelopes. Returns a list of dicts (raw_time, band, type, strength, ...) sorted by time."""
    dt = F["dt"]
    cand = []
    for b in ("low", "mid", "high"):
        A, R = F["A"][b], F["E"][b]
        dist = max(1, int(MIN_DIST_S[b] / dt))
        pk, _ = find_peaks(A, height=MIN_RISE, distance=dist)
        for p in pk:
            t, rise = refine_start(R, int(p), dt)
            cand.append((b, t, rise, int(p)))
    if not cand:
        return []
    ev = []
    lm = np.array([c[2] for c in cand if c[0] in ("low", "mid")])
    ref = float(np.percentile(lm, 95)) + 1e-12 if len(lm) else float(max(c[2] for c in cand)) + 1e-12      # ONE reference for all bands
    hi_by = {}
    for (bb, t, rise, p) in cand:
        s = min(1.0, rise / ref)
        if s < REL_STRENGTH:
            continue
        ev.append({"raw_time": float(t), "band": bb, "strength": float(s), "_p": p})
    # full-band strong transients: a strong combined rise that no low / mid event already explains
    full = F["A"]["low"] + F["A"]["mid"] + F["A"]["high"]
    pk, _ = find_peaks(full, height=2.5 * MIN_RISE, distance=int(0.05 / dt))
    have = np.array(sorted(e["raw_time"] for e in ev))
    Rf = F["E"]["low"] + F["E"]["mid"] + F["E"]["high"]
    rf, allr = [], []
    for p in pk:
        t, rise = refine_start(Rf, int(p), dt)
        allr.append(rise)
        if len(have) and np.min(np.abs(have - t)) < 0.03:
            continue
        rf.append((t, rise, int(p)))
    if rf:
        ref = float(np.percentile(allr, 95)) + 1e-12            # the same reference as the explained hits: a quiet hat is not "strong"
        for t, rise, p in rf:
            st = float(min(1.0, rise / ref))
            if st >= 0.3:
                ev.append({"raw_time": float(t), "band": "full", "strength": st, "_p": p})
    ev.sort(key=lambda e: e["raw_time"])
    # one hit shows up in several bands: keep the dominant one (a mid / high event inside 25 ms of a stronger lower-band event is its echo)
    rank = {"low": 0, "mid": 1, "high": 2, "full": 3}
    keep = []
    for e in ev:
        dup = False
        for o in ev:
            if o is e or abs(o["raw_time"] - e["raw_time"]) > 0.025 or rank[o["band"]] >= rank[e["band"]]:
                continue
            if o["band"] == "low" and e["strength"] < 0.5 * o["strength"]:
                dup = True
            elif o["band"] == "mid" and e["band"] in ("high", "full"):
                dup = True
            if dup:
                break
        if not dup:
            keep.append(e)
    ev = keep
    # classify
    El = F["E"]["low"]
    for e in ev:
        p = e.pop("_p")
        if e["band"] == "low":
            a = El[p:p + int(0.05 / dt)]
            b = El[p + int(0.08 / dt):p + int(0.25 / dt)]
            sustain = (float(b.mean()) / (float(a.max()) + 1e-12)) if len(a) and len(b) else 0.0
            e["type"] = "bass" if sustain >= BASS_SUSTAIN else "kick"
        elif e["band"] == "mid":
            Em = F["E"]["mid"]
            peak = float(Em[p:p + int(0.012 / dt)].max(initial=0)) + 1e-12
            tail = Em[p + int(0.015 / dt):p + int(0.05 / dt)]
            e["type"] = "snare" if (len(tail) and float(tail.mean()) / peak >= 0.08) else "hat"
        elif e["band"] == "high":
            e["type"] = "hat"
        else:
            e["type"] = "accent"
    return ev


def beat_position(t, beats):
    """Fractional beat index of time t on the (piecewise) grid."""
    return float(np.interp(t, beats, np.arange(len(beats)), left=np.nan, right=np.nan)) if beats[0] <= t <= beats[-1] else float("nan")


def associate(events, beats, bpb=4):
    """Attach grid position / offset / snapped time / frame index to every event. The grid never moves."""
    beats = np.asarray(beats, float)
    n = len(beats)
    per = np.diff(beats, append=beats[-1] + (beats[-1] - beats[-2]))
    out = []
    for e in events:
        t = e["raw_time"]
        e = dict(e)
        e["frame"] = int(round(t * FPS))
        e.update(grid_position=None, offset_ms=None, snapped_time=None, on_grid=False, beat=None)
        if t < beats[0] - 0.05 or t > beats[-1] + per[-1]:
            out.append(e)
            continue
        k = int(np.clip(np.searchsorted(beats, t, side="right") - 1, 0, n - 1))
        P = float(per[k])
        x = (t - beats[k]) / P                                   # position inside beat k, in beats
        best = None
        for sub in SUBDIVISIONS:
            m = round(x / sub) * sub
            off = (x - m) * P
            tol = min(OFF_GRID_MS / 1000.0, OFF_GRID_FRAC * sub * P)
            if abs(off) <= tol:
                best = (sub, m, off)
                break
        if best is None:                                          # triplet only if it fits clearly better than the eighth grid
            m3 = round(x * 3) / 3.0
            off3 = (x - m3) * P
            off8 = (x - round(x * 8) / 8.0) * P
            if abs(off3) <= min(OFF_GRID_MS / 1000.0, OFF_GRID_FRAC * P / 3) and abs(off3) < 0.5 * abs(off8):
                best = ("triplet", m3, off3)
        if best is not None:
            sub, m, off = best
            kk = k + int(np.floor(m + 1e-9))
            frac = m - np.floor(m + 1e-9)
            kk = min(kk, n - 1)
            tb = beats[kk] + frac * (per[kk] if kk < n else P)
            e.update(grid_position=float(k + m), offset_ms=round(off * 1000.0, 2), snapped_time=float(tb), on_grid=True, beat=int(kk),
                     subdivision=sub if sub == "triplet" else float(sub), frame=int(round(tb * FPS)))
        else:
            e.update(grid_position=float(k + x), offset_ms=round(((x - round(x * 8) / 8.0) * P) * 1000.0, 2), on_grid=False, beat=int(k))
        out.append(e)
    return out


def use_time(e):
    """Consumers use the snapped time when the event is on the grid, else the raw time."""
    return e["snapped_time"] if e.get("on_grid") and e.get("snapped_time") is not None else e["raw_time"]
