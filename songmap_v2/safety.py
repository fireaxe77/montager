"""V7.2 internal safety (not a mode): when V2 cannot lock a song better than V1 does, V2 must not invent beats. For that song the V1 beat values
(tempo, phase, beats, downbeats) AND sections / drops are returned in the same output, with a log line. The test is a plan-level proxy on kicks found by
`judge.py` (a detector that shares no code with the grid builder): where the planner will put its window (the main drop ~38 % in, for 20 s and 32 s montages)
every beat and half beat is a possible kill position; V2 is kept only if the distance of those positions to the nearest kick is clearly smaller than V1's
(median >= 2 ms better, p95 not worse than +3 ms) and the grid confidence is not tiny. V1 is only READ (its cache, else computed in memory)."""
import sys
from pathlib import Path

import numpy as np

from .bench import nearest

LENS = (20.0, 32.0)
PRE = 0.38
MIN_GAIN_MS = 2.0
P95_SLACK_MS = 3.0
MIN_CONF = 0.12


def _montage():
    for n in ("montage", "__main__"):
        m = sys.modules.get(n)
        if m is not None and hasattr(m, "build_song_map") and hasattr(m, "SONG_CACHE"):
            return m
    return None


def log(msg):
    M = _montage()
    try:
        (M.out if M is not None else print)(msg)
    except Exception:
        print(msg)


def v1_map(path, csv_bpm):
    """The V1 map of the song: from the V1 cache if it is there (read-only), else computed in memory (never written). None if V1 is not reachable."""
    M = _montage()
    if M is None:
        return None
    try:
        import os
        st = os.stat(path)
        key = f"{path}|{int(st.st_mtime)}|{st.st_size}|{M.SONGMAP_V}|{round(float(csv_bpm or 0), 3)}"
        hit = M.load_json(M.SONG_CACHE, {}).get(key)
        return hit if hit else M.build_song_map(path, csv_bpm)
    except Exception:
        return None


def positions(m, kicks, dur):
    """Kill positions the planner can choose (beats and half beats) inside its windows around the main drop; the whole song when there is no main drop."""
    b = np.asarray(m["beats"], float)
    if len(b) < 8:
        return np.array([])
    U = np.sort(np.concatenate([b, 0.5 * (b[1:] + b[:-1])]))
    d = m.get("drop")
    if d is None or not (0 <= int(d) < len(b)):
        return U
    td = float(b[int(d)])
    out = []
    for L in LENS:
        s0 = min(max(0.0, td - PRE * L), max(0.0, dur - L))
        out.append(U[(U >= s0) & (U <= s0 + L)])
    return np.concatenate(out)


def proxy(m, kicks, dur):
    p = positions(m, kicks, dur)
    if not len(p) or not len(kicks):
        return {"median": 9999.0, "p95": 9999.0, "n": 0}
    d = np.abs(nearest(p, kicks)) * 1000.0
    return {"median": float(np.median(d)), "p95": float(np.percentile(d, 95)), "n": int(len(p))}


def apply(m2, path, csv_bpm, kicks, dur, say=log):
    """m2 = the finished V2 map. Returns m2 itself, or the V1 map (same shape) flagged fallback when V2 does not clearly lock better than V1."""
    import os
    if os.environ.get("SONGMAP_V2_NO_SAFETY"):                  # diagnosis only: the raw V2 map
        return m2
    conf = float(m2["v2"]["grid_confidence"])
    v1 = v1_map(path, csv_bpm)
    if v1 is None:
        m2["v2"]["safety"] = {"checked": False}
        return m2
    k = np.asarray(kicks, float)
    p1, p2 = proxy(v1, k, dur), proxy(m2, k, dur)
    from . import judge
    g1, g2 = judge.beat_stats(v1["beats"], k), judge.beat_stats(m2["beats"], k)
    why = None
    if conf < MIN_CONF:
        why = f"grid confidence {conf:.2f}"
    elif not m2["v2"].get("kicky_window", True):
        why = "no window with a continuous kick grid for the planner"
    elif g2["median_ms"] is None or len(k) < 40:
        why = "too few kicks to judge the grid"
    elif g1["median_ms"] is not None and g2["median_ms"] > g1["median_ms"] + 1.0 and g2["p95_ms"] > g1["p95_ms"] + 3.0:
        why = f"kick-to-grid median {g2['median_ms']:.0f} / p95 {g2['p95_ms']:.0f} ms vs V1 {g1['median_ms']:.0f} / {g1['p95_ms']:.0f} ms"
    elif g1["median_ms"] is not None and g2["f1"] < g1["f1"] - 0.03:
        why = f"kick agreement F1 {g2['f1']:.2f} vs V1 {g1['f1']:.2f}"
    info = {"checked": True, "v1_median_ms": round(p1["median"], 1), "v1_p95_ms": round(p1["p95"], 1), "v2_median_ms": round(p2["median"], 1),
            "v2_p95_ms": round(p2["p95"], 1), "grid_v1": g1, "grid_v2": g2, "reason": why}
    if why is None:
        m2["v2"]["safety"] = dict(info, used="v2")
        return m2
    say(f"songmap v2: {Path(path).name} low confidence, using V1 beat values ({why})")
    out = dict(v1)
    out["songmap_version"] = "v2"
    out["beat_source"] = "v1"
    out["v2"] = dict(m2["v2"], events=[], fallback=True, fallback_reason=why, safety=dict(info, used="v1"), v2_bpm=m2["bpm"])
    return out
