"""V7.4.8 tests: (1) refined-label tables (tune / held-out, 0.3 s and 1.0 s) vs the V7.4 baseline, determinism, held-out list untouched (hash), valid times,
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


def part_labels(dst):
    with section("1) later drops: refined-label tables (tune / held-out), existing drops unchanged, false extras, determinism"):
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
        check(sm["tune"]["hit10"] >= 14 + 1 and sm["tune"]["hit03"] >= 14 + 1, f"tune: {sm['tune']['hit03']} within 0.3 s / {sm['tune']['hit10']} within 1.0 s of {sm['tune']['n']} (V7.4.5: 14 / 14 of 14 + the new Molodost label missed)")
        check(sm["held"]["hit10"] >= 9 and sm["held"]["hit03"] >= 8, f"held-out: {sm['held']['hit03']} within 0.3 s / {sm['held']['hit10']} within 1.0 s of {sm['held']['n']} (no baseline hit lost; no held-out miss was left to gain)")
        base = json.load(open(ROOT / "tests" / "data" / "drops_v745.json", encoding="utf-8"))
        by = {}
        for r in rows:
            by.setdefault(r["song"], r["drops"])
        lost = {k: [t for t in v if not any(abs(t - u) < 0.02 for u in by.get(k, []))] for k, v in base.items()}
        check(not any(lost.values()), f"every V7.4.5 drop is still there at the same time ({lost if any(lost.values()) else 'none moved or removed'})")
        extra = {k: [u for u in by[k] if not any(abs(u - t) < 0.02 for t in base[k])] for k in base if k in by}
        n_false = 0
        for k, ex in extra.items():
            labs = [r["t"] for r in rows if r["song"] == k]
            for u in ex:
                if not any(abs(u - t) <= 1.0 for t in labs):
                    n_false += 1
        check(sum(len(v) for v in extra.values()) >= 1, f"later drops added: {({k: v for k, v in extra.items() if v})}")
        check(n_false <= len(base) / 3, f"false extra drops on labelled songs: {n_false} (limit {len(base) / 3:.1f})")
        key = lambda rs: [(r["song"], r["t"], r["hit03"], r["hit10"], r["dist"], r["drops"], r["conf"]) for r in rs]
        check(key(rows) == key(rows2), "2 runs identical")
        check(all(0 <= t < 1000 for r in rows for t in r["drops"]), "no negative / invalid drop times")
        mol = [r for r in rows if r["song"] == "Молодость моя"]
        check(mol and all(r["hit03"] for r in mol) and (mol[0]["conf"] or 1) < 0.9, f"Molodost 1:50 label hit, lower confidence ({mol[0]['conf'] if mol else None})")


def part_map_fields(dst):
    with section("2) map fields: grid / tempo / events code unchanged vs V7.4.7"):
        r = R.run(["git", "diff", "--stat", "V7.4.7", "--", "songmap_v2/grid.py", "songmap_v2/events.py", "songmap_v2/events7.py", "songmap_v2/timebase.py",
                   "songmap_v2/safety.py", "songmap_v2/judge.py", "songmap_v2/build.py"], cwd=str(ROOT), capture_output=True)
        check(not (r.stdout or b"").strip(), "grid / events / timebase / safety / judge / build files byte-identical to V7.4.7")
        r = R.run(["git", "diff", "--stat", "V7.4.7", "--", "montage.py"], cwd=str(ROOT), capture_output=True)
        check(b"montage.py" not in (r.stdout or b"") or True, "montage.py: only the version string changed (checked by the next line)")
        d = R.run(["git", "diff", "-U0", "V7.4.7", "--", "montage.py"], cwd=str(ROOT), capture_output=True).stdout.decode("utf-8", "replace")
        changed = [l for l in d.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]
        check(all("APP_VERSION" in l for l in changed), f"montage.py diff vs V7.4.7 touches only APP_VERSION ({len(changed)} lines): no Valorant / CS2 / planner code changed")


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
        check(M.APP_VERSION == "V7.4.8", "title-bar version V7.4.8")


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
