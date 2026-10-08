"""V7.1 grid-level comparison V1 vs V2 on one song (read-only, never imported by the app): offsets of the independent kicks to each grid in 20 s windows."""
import sys
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


def main(frag):
    import glob
    import montage as M
    from songmap_v2 import bench, timebase, build_songmap_v2
    f = [p for p in glob.glob("E:/CLAUDECODE/Songs/*.mp3") if frag.lower() in p.lower()][0]
    y, sr = timebase.decode(f)
    t, s = bench.indep_kicks(y, sr)
    v1 = M.build_song_map(f, None)
    v2 = build_songmap_v2(f, None, v1_bpm=v1["bpm"])
    print(frag, "v1 bpm", v1["bpm"], "v2 bpm", v2["bpm"], "conf", v2["v2"]["grid_confidence"], "tempo info", v2["v2"]["tempo"], "lock", [(c["bpm_in"], c["src"], c["kick_frac"], c["score"]) for c in v2["v2"]["lock"]["candidates"]])
    for thr in (0.3, 0.6):
        k = t[s >= thr]
        for nm, m in (("V1", v1), ("V2", v2)):
            d = bench.nearest(k, np.asarray(m["beats"], float)) * 1000
            P = np.median(np.diff(m["beats"])) * 1000
            print(f" thr {thr} {nm}: n={len(k)} median|d|={np.median(np.abs(d)):.0f} ms (beat {P:.0f}); within25={np.mean(np.abs(d)<=25):.2f}")
    k = t[s >= 0.6]
    for w0 in range(0, int(len(y) / sr) - 10, 20):
        kk = k[(k >= w0) & (k < w0 + 20)]
        if len(kk) < 6:
            print(f" {w0:3d}s few kicks ({len(kk)})")
            continue
        row = f" {w0:3d}s n={len(kk):3d}"
        for nm, m in (("V1", v1), ("V2", v2)):
            d = bench.nearest(kk, np.asarray(m["beats"], float)) * 1000
            row += f" | {nm} med off {np.median(d):+5.0f} |d| {np.median(np.abs(d)):4.0f} in25 {np.mean(np.abs(d)<=25):.2f}"
        print(row)


if __name__ == "__main__":
    main(sys.argv[1])
