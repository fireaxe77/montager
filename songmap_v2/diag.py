"""V7.1 step 0 diagnosis (read-only, never imported by the app): per song, where the planner put the kills, the independent kick onsets around them,
the V1 / V2 grid phase against those kicks, the chosen section and drop, kick continuity of the planned section. Runs on a COPY of montage_data."""
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def phase_report(beats, kicks, t0, t1, ref_kicks=None):
    """Signed offset of the grid to the kicks inside [t0, t1): median of (kick - nearest beat) in ms and in beats, plus the histogram of the
    kick position inside the beat (quarters)."""
    from songmap_v2 import bench
    b = np.asarray(beats, float)
    k = np.asarray(kicks, float)
    k = k[(k >= t0) & (k < t1)]
    if len(b) < 3 or len(k) < 4:
        return None
    P = float(np.median(np.diff(b)))
    d = -bench.nearest(k, b)                       # kick - nearest beat
    frac = ((k - b[0]) / P) % 1.0
    q = np.histogram(frac, bins=4, range=(0, 1))[0]
    return {"n": int(len(k)), "median_off_ms": round(float(np.median(d)) * 1000, 1), "abs_median_ms": round(float(np.median(np.abs(d))) * 1000, 1),
            "off_beats": round(float(np.median(d)) / P, 3), "beat_ms": round(P * 1000, 1), "quarters": [int(x) for x in q]}


def kick_continuity(kicks, t0, t1, gap=2.0):
    """Longest kick-free stretch (s) and the share of 1 s windows with a kick inside [t0, t1)."""
    k = np.sort(np.asarray(kicks, float))
    k = k[(k >= t0) & (k < t1)]
    pts = np.concatenate([[t0], k, [t1]])
    return {"longest_gap_s": round(float(np.max(np.diff(pts))), 1), "windows_with_kick": round(float(np.mean([np.any((k >= a) & (k < a + 1)) for a in np.arange(t0, t1 - 1, 1.0)])) if t1 - t0 > 1 else 0, 2)}


def main(frags):
    import montage as M
    from songmap_v2 import bench, planbench as PB, timebase
    import songmap_compare as SC
    res = []
    with PB.data_copy(M):
        songs = [s for s in SC.v7_song_list(M, print) if any(f.lower() in s[0].lower() for f in frags)]
        sets = PB.take_sets(M)
        for label, p, csv, why in songs:
            t0 = time.time()
            y, sr = timebase.decode(p)
            kicks = bench.strong_kicks(y, sr)
            dur = len(y) / sr
            v1 = M.build_song_map(p, csv)
            v2 = M.get_songmap(p, csv, version="v2")
            r = {"song": label, "csv": csv, "v1_bpm": v1["bpm"], "v2_bpm": v2["bpm"], "v2_conf": v2["v2"]["grid_confidence"], "dur": round(dur, 1),
                 "v1_drops": [d["t"] for d in v1["drops"]], "v2_drops": [d["t"] for d in v2["drops"]], "modes": {}}
            for mode, mp in (("v1", v1), ("v2", v2)):
                allk, rows = [], []
                for sname, (game, paths) in sets.items():
                    try:
                        plan, _ = PB.run_plan(M, game, paths, p, mode)
                    except Exception as ex:
                        rows.append({"set": sname, "error": f"{type(ex).__name__}: {ex}"})
                        continue
                    kt = PB.kill_times(plan)
                    s0 = float(plan["song"]["start_t"])
                    e0 = s0 + float(plan["duration"])
                    d = [float(bench.nearest([t], kicks)[0]) * 1000 for t, *_ in kt]
                    rows.append({"set": sname, "start": round(s0, 1), "end": round(e0, 1), "kills": [round(t, 2) for t, *_ in kt][:8],
                                 "d_ms": [round(x) for x in d][:8], "median_abs": round(float(np.median(np.abs(d))), 1) if d else None,
                                 "phase_v1": phase_report(v1["beats"], kicks, s0, e0), "phase_v2": phase_report(v2["beats"], kicks, s0, e0),
                                 "cont": kick_continuity(kicks, s0, e0)})
                    allk += [abs(x) for x in d]
                r["modes"][mode] = {"median": round(float(np.median(allk)), 1) if allk else None, "sets": rows}
            r["secs"] = round(time.time() - t0)
            res.append(r)
            print(json.dumps(r, indent=1, default=float))
    out = HERE / "compare_out"
    out.mkdir(exist_ok=True)
    (out / "diag_step0.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
