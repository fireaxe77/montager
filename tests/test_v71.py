"""V7.1: Song map V2 replaces V1 (branch v7.1-songmap). Re-uses the V7 checks (genre suite with known truth, V2 shape / validity / determinism, V1 byte-for-byte
unchanged, fallbacks, V2 cannot touch takes / kills / ledger, Valorant / CS2 guards) and adds: V2 fallback on injected exception and timeout through the plain
'v2' mode, the offbeat-lock regression (hardstyle with reverse bass must lock to the KICK), kick-continuity of the chosen drop, the two-entry dropdown, the
songmapcheck command and a git diff limited to the allowed paths. Needs the Windows PC with the real songs / clips.
   python tests\\test_v71.py          (from the repo root or from tests/)
Ends with ALL OK only if every check ran and passed. Everything runs on a COPY of montage_data."""
import subprocess
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
from test_v7 import M, PB, check, section, songmap_v2, synth, bench                           # noqa: E402

ALLOWED = ("songmap_v2/", "songmap_compare.py", "tests/test_v71.py", "tests/test_v72.py", "tests/test_v7.py", "docs/", "CHANGELOG.md", "CLAUDE.md", ".gitignore")
MONTAGE_PY_OK = ("songmap", "SONGMAP", "sc_", "APP_VERSION")          # the only lines montage.py may change: the dropdown / default constant / CLI wiring of songmapcheck


def part_fallback_v2(tmp, maps):
    with section("8) plain 'Songmap V2': crash safety only (injected exception and time cap -> V1 map + log line)"):
        d = Path(tmp) / "fbdata"
        old = M.use_data_dir(d)
        lines = []
        keep = (M.out, M.LOGONLY)
        M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
        try:
            orig = songmap_v2.build_songmap_v2
            songmap_v2.build_songmap_v2 = lambda *a, **k: (_ for _ in ()).throw(ValueError("boom"))
            try:
                m = M.get_songmap(maps["hiphop87"][1], None, "v2")
            finally:
                songmap_v2.build_songmap_v2 = orig
            check(m.get("songmap_version") == "v1-fallback" and any("songmap v2 fallback" in l and "boom" in l for l in lines) and len(m["beats"]) > 10, f"injected exception -> V1 map + log: {lines[-1:]}")
            lines.clear()
            cap = songmap_v2.ANALYSIS_CAP_S
            songmap_v2.ANALYSIS_CAP_S = 0.001
            try:
                m = M.get_songmap(maps["dnb174"][1], None, "v2")
            finally:
                songmap_v2.ANALYSIS_CAP_S = cap
            check(m.get("songmap_version") == "v1-fallback" and any("songmap v2 fallback" in l for l in lines) and len(m["beats"]) > 10, f"time cap -> V1 map + log: {lines[-1:]}")
            lines.clear()
            m = M.get_songmap(maps["house128"][1], None, "v2")
            check(m.get("songmap_version") == "v2" and not lines or m.get("songmap_version") == "v2", "a normal song gets the V2 map (no fallback)")
        finally:
            M.out, M.LOGONLY = keep
            M.restore_data_dir(old)


def part_offbeat(maps):
    with section("9) offbeat-lock regression: hardstyle with reverse-bass offbeats locks to the KICK"):
        for name in ("hardstyle150", "hardstyle160"):
            m, p, tr = maps[name]
            kicks = np.asarray(tr["kicks"], float)
            d = np.abs(bench.nearest(kicks[3:-3], np.asarray(m["beats"], float))) * 1000
            P = 60.0 / tr["bpm"] * 1000
            check(float(np.median(d)) < 10 and float(np.percentile(d, 95)) < 25, f"{name}: kick-to-grid median {np.median(d):.1f} ms / p95 {np.percentile(d, 95):.1f} ms (beat {P:.0f} ms): not on the offbeat bass")


def part_sections():
    with section("10) sections: drop at the kick entry, kicky planner window, uniformly loud song keeps one capped drop"):
        from songmap_v2 import sections as S
        n = 120
        bars = []
        for k in range(n):
            loud = -30.0 + (14.0 if 40 <= k < 80 else 0.0)
            kick = 0.0 if k < 44 else 1.0                         # the loud part starts 4 bars before the first kick
            bars.append({"beat0": 4 * k, "beat1": 4 * k + 4, "t0": 2.0 * k, "t1": 2.0 * k + 2.0, "loud": loud, "low": loud - 8, "act": 0.0 if k < 44 else 6.0, "kick": kick})
        r = S.analyse(bars, 2.0)
        check(r["drops"] and r["drops"][0]["bar"] == 44, f"drop moved from the loudness rise (bar 40) to the kick entry (bar 44): {[d['bar'] for d in r['drops']]}")
        check(r["drops"] and (r["drops"][0]["kicky"] or r.get("anchor") is not None), "a window around the drop with a continuous kick grid is offered (kicky drop or anchor)")
        flat = [dict(b, loud=-14.0, low=-20.0, act=5.0, kick=1.0) for b in bars]
        r2 = S.analyse(flat, 2.0)
        check(r2["share"] <= S.SHARE_CAP + 1e-9 and sum(1 for l in r2["labels"] if l == "drop") < 0.5 * n, f"uniformly loud song: share of 'drop' {r2['share']:.2f} (cap {S.SHARE_CAP})")


def part_ui():
    with section("11) dropdown = Songmap V1 / V2 only; songmapcheck registered; V1 stays selectable"):
        check(list(M.SONGMAP_CHOICES_UI.values()) == ["Songmap V1", "Songmap V2"], f"dropdown choices {list(M.SONGMAP_CHOICES_UI.values())}")
        check(M.songmap_version({"songmap_version": "v1"}) == "v1" and M.songmap_version({"songmap_version": "v2"}) == "v2", "both values are selectable")
        r = subprocess.run([sys.executable, str(ROOT / "montage.py"), "songmapcheck", "-h"], capture_output=True, text=True, cwd=str(ROOT))
        check(r.returncode == 0 and "song" in r.stdout.lower(), "python montage.py songmapcheck -h works")


def part_diff71():
    with section("12) git diff limited to the allowed paths (montage.py: dropdown / default / CLI wiring lines only)"):
        base = T7.BASE_REF
        r = subprocess.run(["git", "diff", "--name-only", base], cwd=str(ROOT), capture_output=True, text=True)
        u = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=str(ROOT), capture_output=True, text=True)
        files = [f for f in (r.stdout.split() + u.stdout.split()) if f and not f.startswith(("good.mp4", "montage_data_backup", "compare_out"))]
        bad = [f for f in files if not f.startswith(ALLOWED) and f != "montage.py"]
        check(not bad, f"changed / new files all inside the allowed paths (outside: {bad})")
        d = subprocess.run(["git", "diff", "-U0", base, "--", "montage.py"], cwd=str(ROOT), capture_output=True, text=True).stdout
        ch = [l for l in d.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]
        off = [l for l in ch if not any(k in l for k in MONTAGE_PY_OK)]
        check(not off, f"montage.py: {len(ch)} changed lines, all about the song-map dropdown / default / songmapcheck wiring (other: {off[:3]})")


def main():
    real_data = ROOT / "montage_data"
    before = T7.snapshot(real_data)
    tmp = Path(tempfile.mkdtemp(prefix="t71_"))
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
            part_fallback_v2(tmp, maps)
            part_offbeat(maps)
        finally:
            M.restore_data_dir(old)
        part_sections()
        part_ui()
        T7.part_plan(tmp, Bm, real)
        T7.part_guards(tmp, Bm)
        part_diff71()
    with section("real montage_data"):
        after = T7.snapshot(real_data)
        check(after == before, f"real montage_data unchanged by the tests ({len(before)} files)")
    print("section times: " + ", ".join(f"{t.split(')')[0]} {s:.0f}s" for t, s in T7.SECTIONS))
    print(f"total test time {time.time() - T7.T_ALL:.1f} s")
    print("ALL OK" if not T7.FAILS else f"FAILED ({len(T7.FAILS)}):\n  " + "\n  ".join(T7.FAILS))
    return 1 if T7.FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
