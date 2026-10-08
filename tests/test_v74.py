"""V7.4 tests: (1) label table of the V2 drops vs tests/data/drop_labels.json (no baseline hit becomes a miss, hits rise, 2 runs identical, valid times),
(2) planner drop source (headline drop = a map drop / a saved label; unlabelled identical to base), (3) dropcheck prints (2 layers), dropsave,
(4) CS2 Force new top-up also runs when ZERO takes are placed, (5) guards: Valorant Force new identical, 50 + 50 generated clips identical.
Runs on a COPY of montage_data (PB.data_copy); the real folder is only read.   python tests\\test_v74.py   (guards: 50+50 clips vs V7.2-good with the headline rules off, Valorant Force new vs V7.3-good)"""
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
import v74_common as C                                                                        # noqa: E402
from v696_common import check, section, FAILS, snapshot                                       # noqa: E402

REAL_DATA = ROOT / "montage_data"
T_ALL = time.time()
MIN_HITS = 23                                                                                 # measured after the V7.4 drop changes (baseline 17 of 27)


def _txt(r):
    return r.stdout.decode("utf-8", "replace") if isinstance(r.stdout, bytes) else (r.stdout or "")


def part_labels(dst):
    with section("1) label table: V7.4 vs the V7.3 baseline, determinism, valid times"):
        old = M.use_data_dir(dst)
        try:
            cfg = M.load_config()
            rows, missing, songs = C.table(M, cfg)
            rows2, _, _ = C.table(M, cfg)
        finally:
            M.restore_data_dir(old)
        C.print_table(rows, missing)
        base = json.load(open(ROOT / "tests" / "data" / "drop_baseline_v73.json"))
        bh = {(b["song"], b["label"]) for b in base if b["status"] == "hit"}
        nh = {(r["song"], r["label"]) for r in rows if r["status"] == "hit"}
        check(not (bh - nh), f"no baseline hit became a miss ({len(bh)} baseline hits; lost {sorted(bh - nh)})")
        check(len(nh) >= MIN_HITS, f"hits {len(nh)} of {len(rows)} (baseline {len(bh)})")
        key = lambda rs: [(r["song"], r["label"], r["status"], r["dist"], r["drops"]) for r in rs]
        check(key(rows) == key(rows2), "2 runs identical")
        check(all(0 <= t < 1000 for r in rows for t in r["drops"]), "no negative / invalid drop times")


def part_planner(tmp):
    with section("2) planner drop source: headline drop is a map drop; labels replace the list; unlabelled unchanged"):
        an = T73.song_map(M, 128.0, 300.0, 64.0)
        bt = an["beats"]
        real = an["drops"][0]["beat"]
        an["drop"] = real + 20                                   # the planner anchor: main drop ~10 s after the real one, not a map drop
        clips = [{"path": f"c{i}.mp4", "times": [4.0 + i], "rows": [4.0 + i], "first": 4.0 + i, "last": 4.0 + i, "span": 0.0, "score": 1.0 - i / 10, "n": 1}
                 for i in range(8)]
        f = M.optimal_fit(clips, an, "hype")
        check(abs(bt[f["drop_beat"]] - bt[real]) < 0.6 or "kept" in f["drop_why"], f"anchor case: headline drop {bt[f['drop_beat']]:.1f} s (map drop {bt[real]:.1f} s): {f['drop_why']}")
        an2 = T73.song_map(M, 128.0, 300.0, 64.0)
        f2 = M.optimal_fit(clips, an2, "hype")
        check(f2["drop_beat"] == an2["drop"], "main drop is a map drop: unchanged")
        old = M.DATA
        M.DATA = tmp
        try:
            (tmp / "song_drops.json").write_text(json.dumps({"x.mp3": {"drops": [bt[real + 32]]}}), encoding="utf-8")
            f3 = M.optimal_fit(clips, an2, "hype", song_path="y.mp3")
            f4 = M.optimal_fit(clips, an2, "hype", song_path="x.mp3")
        finally:
            M.DATA = old
        check(f3["drop_beat"] == f2["drop_beat"], "unlabelled song identical to base")
        check(abs(bt[f4["drop_beat"]] - bt[real + 32]) < 0.3 or "kept" in f4["drop_why"], f"labelled song uses its labels ({bt[f4['drop_beat']]:.1f} s: {f4['drop_why']})")


def part_dropcheck(dst):
    with section("3) dropcheck prints 2 layers; dropsave"):
        env = dict(os.environ, MONTAGER_DATA=str(dst), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        ok, txt = False, ''
        for pf in sorted((REAL_DATA / "plans").glob("*.dry.json"))[-3:]:
            pl = json.load(open(pf, encoding="utf-8"))
            if pl.get("takes"):
                txt = _txt(R.run([sys.executable, str(ROOT / "montage.py"), "dropcheck", str(pf)], cwd=str(ROOT), capture_output=True, env=env))
                ok = "L1 MAP" in txt and "L2 PLANNER" in txt and "L3" not in txt and "VERDICT" in txt
                break
        check(ok, "dropcheck prints L1 MAP + L2 PLANNER + VERDICT, no kill-delay layer" + ("" if ok else " :: " + txt[:200]))
        R.run([sys.executable, str(ROOT / "montage.py"), "dropsave", "Self Aware", "0:24", "1:25", "2:02"], cwd=str(ROOT), capture_output=True, env=env)
        t2 = _txt(R.run([sys.executable, str(ROOT / "montage.py"), "dropsave", "--list"], cwd=str(ROOT), capture_output=True, env=env))
        check("0:24" in t2 and (dst / "song_drops.json").exists(), "dropsave saved (atomic) and --list shows it")
        (dst / "song_drops.json").unlink()                       # the labels were only for this check (data copy)


def part_zero_take(dst):
    with section("4) CS2 Force new: the top-up also runs when zero takes are placed"):
        old = M.use_data_dir(dst)
        real_wp = M.weekly_pick
        try:
            def zero_pick(events, cfg, target, style, now_ts=None, game=None):
                pick, notes = real_wp(events, cfg, target, style, now_ts, game)
                return [dict(e, times=[0.1], rows=[0.1], first=0.1, last=0.1, span=0.0, n=1) for e in pick[:2]], notes      # kill in the first second: no take
            M.weekly_pick = zero_pick
            try:
                plan, lines = T73.run_make_plan(M, "cs2")
                err = None
            except RuntimeError as ex:
                plan, lines, err = None, [], str(ex)
        finally:
            M.weekly_pick = real_wp
            M.restore_data_dir(old)
        if plan is not None:
            check(plan["duration"] >= 59.5 or any("possible" in x for x in lines), f"zero-take start reaches {plan['duration']:.0f} s (60 s) or logs the exhausted case")
            check(any("planner placed only 0 s" in x for x in lines), "the top-up ran from zero takes: " + next((x for x in lines if "planner placed only" in x), "")[:100])
        else:
            check("tried" in (err or ""), "nothing placeable: CANNOT RENDER keeps a per-event reason: " + (err or "")[:160])


def part_force_new_guard(tmp, Bm, dst):
    with section("5) guard: Valorant Force new identical to base"):
        old = M.use_data_dir(dst)
        try:
            Bm.use_data_dir(dst)
            pv, lv = T73.run_make_plan(M, "valorant")
            pb, lb = T73.run_make_plan(Bm, "valorant")
        finally:
            M.restore_data_dir(old)
        check({t["path"] for t in pv["takes"]} == {t["path"] for t in pb["takes"]} and abs(pv["duration"] - pb["duration"]) < 1.0,
              f"Valorant Force new: same montage as V7.3 ({pb['duration']:.0f} s, {len(pb['takes'])} takes)")


def main():
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t74_"))
    with PB.data_copy(M) as dst:
        part_labels(dst)
        part_planner(tmp)
        part_dropcheck(dst)
        old = M.use_data_dir(tmp / "data")
        try:
            T73.BASE_REF = "V7.2-good"
            B2 = T73.load_base(tmp)
            check(B2 is not None, "V7.2 baseline planner loaded")
            B2.use_data_dir(tmp / "data_b")
            T73.part_guards(tmp, B2)
            T73.BASE_REF = "V7.3-good"
            (tmp / "b3").mkdir()
            Bm = T73.load_base(tmp / "b3")
            check(Bm is not None, "V7.3 baseline planner loaded")
        finally:
            M.restore_data_dir(old)
        part_zero_take(dst)
        part_force_new_guard(tmp, Bm, dst)
        T73.part_util_real(tmp, B2, dst)
    T73.part_real_untouched(before)
    print(f"total test time {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
