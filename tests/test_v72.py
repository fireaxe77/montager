"""V7.2: Song map V2 replaces V1 (branch v7.1-songmap). Runs everything of test_v71 / test_v7 (genre suite incl. hardstyle reverse-bass, shape, determinism, V1
byte-for-byte, fallbacks, V2 cannot touch takes / kills / ledger, Valorant / CS2 guards, 7 real clips: 4 events, 11 placed, 3 merged, 0 lost) and adds: the
internal safety (V2 returns the V1 beat values + log line when it cannot lock better than V1: low confidence, noisy song), takes / events parity and the
regression numbers of the problem songs on a COPY of montage_data.
   python tests\test_v72.py          (from the repo root or from tests/)
Ends with ALL OK only if every check ran and passed."""
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import numpy as np                                                                            # noqa: E402
import test_v7 as T7                                                                          # noqa: E402
import test_v71 as T71                                                                        # noqa: E402
from test_v7 import M, PB, check, section, songmap_v2, synth, bench                           # noqa: E402
from songmap_v2 import safety, judge                                                          # noqa: E402

REGRESSION = ["Silicon XX", "Beautiful Now - Zedd", "(nendest)", "2 time zones", "Six Zeta", "prety - "]


def part_safety(tmp, maps):
    with section("13) internal safety: V2 never invents beats it cannot lock better than V1"):
        m, p, tr = maps["house128"]
        y, sr = songmap_v2.timebase.decode(p)
        kicks = judge.strong(y, sr)
        lines = []
        low = songmap_v2.build_songmap_v2(p, None)
        low["v2"]["grid_confidence"] = 0.05                                    # a low-confidence V2 grid
        out = safety.apply(low, p, None, kicks, len(y) / sr, say=lines.append)
        v1 = M.build_song_map(p, None)
        check(out["v2"].get("fallback") is True and out["beats"] == v1["beats"] and out["down"] == v1["down"] and out["bpm"] == v1["bpm"],
              "low confidence -> the V1 beat values (tempo, beats, downbeats) in the V2 output")
        check(any("low confidence, using V1 beat values" in l and Path(p).name in l for l in lines), f"log line: {lines[-1:]}")
        good = songmap_v2.build_songmap_v2(p, None)
        check(not good["v2"].get("fallback") and good["v2"]["safety"].get("used") in ("v2", None), "a locked song keeps its V2 grid")
        amb, _ = synth.make_song_file("ambient", tmp)
        mm = M.get_songmap(amb, None, "v2")
        check(str(mm.get("songmap_version", "")).startswith("v1") or mm.get("beat_source") == "v1", f"ambient / no-percussion song -> V1 beat values ({mm.get('songmap_version')})")
        seen = [m_ for m_ in (out, good) if all(np.isfinite(np.asarray(m_["beats"], float)))]
        check(len(seen) == 2, "no NaN in either output")


def part_regression():
    with section("14) the problem songs on a copy: regression numbers and takes / events parity (plan level, 3 pinned sets)"):
        from songmap_v2 import iter as IT
        rows = IT.run(REGRESSION, want_v1=True, jobs=6)
        for r in rows:
            a, b = r["v1"]["all"], r["v2"]["all"]
            name = r["song"][:28]
            if r["frag"] in ("Silicon XX", "Beautiful Now - Zedd", "(nendest)"):
                check(a["median_ms"] - b["median_ms"] >= 15, f"{name}: median {a['median_ms']} -> {b['median_ms']} ms (>= 15 ms better)")
            check(b["median_ms"] <= a["median_ms"] + 5 and b["p95_ms"] <= a["p95_ms"] + 5, f"{name}: never worse than V1 (median {a['median_ms']} -> {b['median_ms']}, p95 {a['p95_ms']} -> {b['p95_ms']})")
            check(r["v2"]["takes"] >= r["v1"]["takes"] and r["v2"]["events"] >= r["v1"]["events"], f"{name}: takes/events V1 {r['v1']['takes']}/{r['v1']['events']} -> V2 {r['v2']['takes']}/{r['v2']['events']} (never fewer)")


def main():
    real_data = ROOT / "montage_data"
    before = T7.snapshot(real_data)
    tmp = Path(tempfile.mkdtemp(prefix="t72_"))
    with PB.data_copy(M):
        real = T7.real_songs()
        old = M.use_data_dir(tmp / "data")
        try:
            maps = T7.part_genre(tmp)
            T7.part_validity(tmp, maps, real)
            Bm = T7.load_base(tmp)
            check(Bm is not None, f"base module loaded from {T7.BASE_REF}")
            T7.part_v1(tmp, Bm, real, maps)
            T7.part_gate(tmp, maps)
            T71.part_fallback_v2(tmp, maps)
            T71.part_offbeat(maps)
            part_safety(tmp, maps)
        finally:
            M.restore_data_dir(old)
        T71.part_sections()
        T71.part_ui()
        T7.part_plan(tmp, Bm, real)
        T7.part_guards(tmp, Bm)
        T71.part_diff71()
    part_regression()
    with section("real montage_data"):
        after = T7.snapshot(real_data)
        check(after == before, f"real montage_data unchanged by the tests ({len(before)} files; the running Montager app refreshes some caches itself)")
    print("section times: " + ", ".join(f"{t.split(')')[0]} {s:.0f}s" for t, s in T7.SECTIONS))
    print(f"total test time {time.time() - T7.T_ALL:.1f} s")
    print("ALL OK" if not T7.FAILS else f"FAILED ({len(T7.FAILS)}):\n  " + "\n  ".join(T7.FAILS))
    return 1 if T7.FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
