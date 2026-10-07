"""V7 event detector (build.py uses it instead of events.detect; events.py itself stays exactly as in V6.9.5.1). Same as events.detect plus: (1) a
linear-amplitude low-band pass for kicks on top of a bass that never goes quiet (hardstyle, 808s), (2) a `sharp` value per low / mid event (share of
the rise that happens within 12 ms) and (3) kick / bass classification that calls a sharp low-band hit a kick whatever its tail (long hardstyle kicks)
and a swelling hit a bass note."""
import numpy as np
from scipy.signal import find_peaks

from .events import (BASS_SUSTAIN, MIN_DIST_S, MIN_RISE, REL_STRENGTH, refine_start)

SHARP_MIN = 0.45                    # share of a hit's rise that happens within 12 ms: a kick / snare crack is sharp, a swelling (reverse) bass is not
LIN_REL = 0.12                      # linear low-band rise (kick on top of sustained bass) needs this share of the loud-hit level
LIN_DEDUP_S = 0.045


def sharpness(R, p, dt):
    """V7: how much of the rise of a hit happens in its first 12 ms (R = sqrt energy envelope). ~0.7-1 for a kick or snare, ~0.1-0.3 for a swell."""
    k = max(1, int(round(0.012 / dt)))
    n = len(R)
    lo = max(0, p - 2 * k)
    base = float(R[lo:p + 1].min())
    top = float(R[p:min(n, p + int(0.15 / dt))].max())
    if top - base <= 1e-12:
        return 0.0
    return float(np.clip((float(R[min(n - 1, p + k)]) - base) / (top - base), 0.0, 1.0))


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
    # V7: a kick on top of a bass that never goes quiet (hardstyle, 808s) barely changes the LOG energy; its linear amplitude rise still shows
    Rl = F["R"]["low"]
    k = max(1, int(round(0.012 / dt)))
    if len(Rl) > 4 * k:
        lin = np.maximum(0.0, np.concatenate([Rl[k:], np.full(k, Rl[-1])]) - np.concatenate([np.full(k, Rl[0]), Rl[:-k]]))
        ref_l = float(np.percentile(Rl, 95)) + 1e-12
        have_low = np.array(sorted(c[1] for c in cand if c[0] == "low"))
        pk, _ = find_peaks(lin, height=LIN_REL * ref_l, distance=max(1, int(0.06 / dt)))
        for p in pk:
            p = int(p)
            t, rise = refine_start(F["E"]["low"], p, dt)
            if len(have_low) and np.min(np.abs(have_low - t)) < LIN_DEDUP_S:
                continue
            cand.append(("low", t, rise, p))
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
        if e["band"] in ("low", "mid"):
            e["sharp"] = round(sharpness(F["R"][e["band"]], p, dt), 3)
        if e["band"] == "low":
            a = El[p:p + int(0.05 / dt)]
            b = El[p + int(0.08 / dt):p + int(0.25 / dt)]
            sustain = (float(b.mean()) / (float(a.max()) + 1e-12)) if len(a) and len(b) else 0.0
            e["type"] = "kick" if e["sharp"] >= SHARP_MIN else ("bass" if sustain >= BASS_SUSTAIN else "kick")
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
