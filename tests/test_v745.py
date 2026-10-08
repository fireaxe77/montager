"""V7.4.5 tests: (1) refined-label tables (tune / held-out, 0.3 s and 1.0 s) vs the V7.4 baseline, determinism, held-out list untouched (hash), valid times,
(2) confidence field present and grid / tempo / V1-side code unchanged vs V7.4, (3) dropcheck prints the per-drop lines, (4) guards: 50+50 generated clips identical
to V7.2 (headline rules off), the 7 real Valorant clips and the 4K. Runs on a COPY of montage_data (PB.data_copy).   python tests\test_v745.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import _run as R                                                                              # noqa: E402
import montage as M                                                                           # noqa: E402
from songmap_v2 import planbench as PB                                                        # noqa: E402
import test_v73 as T73                                                                        # noqa: E402
import v74_common as V                                                                        # noqa: E402
import v745_common as C                                                                       # noqa: E402
from v696_common import check, section, FAILS, snapshot                                       # noqa: E402

REAL_DATA = ROOT / "montage_data"
T_ALL = time.time()
HELD_HASH = "f159b58bc81b"                                                           # sha1 of the held-out labels, fixed before tuning
BASE = {"tune": (7, 13), "held": (6, 9)}                                                      # V7.4 baseline: (hits within 0.3 s, within 1.0 s) of 14 / 9 non-hard labels


def part_labels(dst):
    with section("1) refined-label tables: tune vs held-out, baseline V7.4, determinism"):
        check(C.held_hash() == HELD_HASH, f"held-out labels untouched (hash {C.held_hash()})")
        old = M.use_data_dir(dst)
        try:
            cfg = M.load_config()
            rows = C.grade(M, cfg, V)
            rows2 = C.grade(M, cfg, V)
        finally:
            M.restore_data_dir(old)
        C.show(rows)
        sm = C.summary(rows)
        for k in ("tune", "held"):
            check(sm[k]["hit10"] >= BASE[k][1], f"{k}: within 1.0 s {sm[k]['hit10']} of {sm[k]['n']} (baseline {BASE[k][1]}): no baseline hit lost")
            check(sm[k]["hit03"] >= BASE[k][0] + 1, f"{k}: within 0.3 s {sm[k]['hit03']} of {sm[k]['n']} (baseline {BASE[k][0]})")
        key = lambda rs: [(r["song"], r["t"], r["hit03"], r["hit10"], r["dist"], r["drops"], r["conf"]) for r in rs]
        check(key(rows) == key(rows2), "2 runs identical")
        check(all(0 <= t < 1000 for r in rows for t in r["drops"]), "no negative / invalid drop times")
        check(all(r["conf"] is None or 0.0 <= r["conf"] <= 1.0 for r in rows), "confidence in 0..1")
        check(sum(r["conf"] is not None for r in rows if r["hit10"]) == sum(1 for r in rows if r["hit10"]), "every matched drop has a confidence")
        return rows


def part_map_fields(dst):
    with section("2) map fields: confidence added, grid / tempo / events code unchanged vs V7.4"):
        r = R.run(["git", "diff", "--stat", "V7.4-good", "--", "songmap_v2/grid.py", "songmap_v2/events.py", "songmap_v2/events7.py", "songmap_v2/timebase.py",
                   "songmap_v2/safety.py", "songmap_v2/judge.py"], cwd=str(ROOT), capture_output=True)
        check(not (r.stdout or b"").strip(), "grid / events / timebase / safety / judge files byte-identical to V7.4")
        old = M.use_data_dir(dst)
        try:
            cfg = M.load_config()
            songs, _ = V.find_songs(M, cfg, ["Self Aware"])
            m = M.get_songmap(songs["Self Aware"]["path"], songs["Self Aware"].get("csv_bpm"), version="v2")
        finally:
            M.restore_data_dir(old)
        check(all("conf" in d and 0 <= d["conf"] <= 1 for d in m["drops"]), "every drop has a confidence")
        check(all(k in m for k in ("beats", "down", "bpm", "drops", "drop", "sections", "phrase4")) and all(d["beat"] == int(d["beat"]) for d in m["drops"]), "V1-shaped map keys intact")


def part_dropcheck(dst):
    with section("3) dropcheck: per-drop lines with confidence"):
        env = dict(os.environ, MONTAGER_DATA=str(dst), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        ok, txt = False, ""
        for pf in sorted((REAL_DATA / "plans").glob("*.dry.json"))[-3:]:
            txt = R.run([sys.executable, str(ROOT / "montage.py"), "dropcheck", str(pf)], cwd=str(ROOT), capture_output=True, env=env).stdout
            txt = txt.decode("utf-8", "replace") if isinstance(txt, bytes) else txt
            ok = "L1 MAP" in txt and "L2 PLANNER" in txt and "VERDICT" in txt and "L3" not in txt
            break
        check(ok, "dropcheck still prints the two layers")
        check(M.APP_VERSION == "V7.4.5", "title-bar version V7.4.5")


def main():
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t745_"))
    with PB.data_copy(M) as dst:
        part_labels(dst)
        part_map_fields(dst)
        part_dropcheck(dst)
        old = M.use_data_dir(tmp / "data")
        try:
            T73.BASE_REF = "V7.2-good"
            B2 = T73.load_base(tmp)
            check(B2 is not None, "V7.2 baseline planner loaded")
            B2.use_data_dir(tmp / "data_b")
            T73.part_guards(tmp, B2)
        finally:
            M.restore_data_dir(old)
        T73.part_util_real(tmp, B2, dst)
    T73.part_real_untouched(before)
    print(f"total test time {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
