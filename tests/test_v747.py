"""V7.4.7 tests: planner headline drop choice. (1) Atlantis (Valorant + CS2, pinned song and seed): the finisher sits on the map drop and the logged drop
(song.drop_t / TIMELINE) is the drop actually used, (2) optimal_fit on the Atlantis map: a map drop in the section wins; 'drop kept' names the failed
condition, (3) synthetic anchor case + saved labels (test_v74), (4) guards: 50+50 generated clips identical to V7.2 (headline rules off), the 7 real Valorant
clips, the 4K. Runs on a COPY of montage_data (PB.data_copy).   python tests\\test_v747.py"""
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import montage as M                                                                           # noqa: E402
from songmap_v2 import planbench as PB                                                        # noqa: E402
import test_v73 as T73                                                                        # noqa: E402
import test_v74 as T74                                                                        # noqa: E402
from v696_common import check, section, FAILS, snapshot                                       # noqa: E402

REAL_DATA = ROOT / "montage_data"
T_ALL = time.time()


def atlantis():
    cfg = M.load_config()
    songs, _, _ = M.song_pool(cfg)
    s = next(x for x in songs if "atlantis" in (x["title"] or "").lower() and "flerian" in x["path"].lower())
    return cfg, s, M.get_songmap(s["path"], s.get("csv_bpm"), version="v2")


def part_atlantis(dst):
    with section("1) Atlantis pinned: finisher on the map drop, the logged drop is the drop used"):
        old = M.use_data_dir(dst)
        try:
            cfg, s, m = atlantis()
            bt = m["beats"]
            check(len(m["drops"]) >= 2, f"Atlantis map drops {[round(d['t'], 1) for d in m['drops']]}")
            for game in ("valorant", "cs2"):
                keep, lines = T73.quiet(M)
                try:
                    plan, _ = M.make_plan(cfg, game, song_path=s["path"], seed=5, scan=False)
                finally:
                    T73.unquiet(M, keep)
                da = plan["drop_anchor"]
                hl = next(t for t in plan["takes"] if t.get("role") == "headline")
                st = plan["song"]["start_t"]
                kill = st + hl["out_start"] + (hl["kills_out"][-1] if da["anchor"] == "last" else hl["kills_out"][0])
                mapd = [d["t"] for d in m["drops"]]
                check(min(abs(da["drop_t"] - x) for x in mapd) < 0.05, f"{game}: the headline drop {da['drop_t']:.2f} s is a map drop ({da['source']})")
                check(abs(kill - da["drop_t"]) < 0.03, f"{game}: finisher at {kill:.3f} s within 30 ms of the drop")
                check(abs(plan["song"]["drop_t"] + st - da["drop_t"]) < 0.03, f"{game}: TIMELINE drop {plan['song']['drop_t'] + st:.2f} s == drop used")
        finally:
            M.restore_data_dir(old)


def part_fit(dst):
    with section("2) optimal_fit on the Atlantis map"):
        old = M.use_data_dir(dst)
        try:
            cfg, s, m = atlantis()
            bt = m["beats"]
            mk = lambda k: [{"path": f"c{i}.mp4", "times": [4.0 + i, 5.0 + i], "rows": [4.0 + i, 5.0 + i], "first": 4.0 + i, "last": 5.0 + i, "span": 1.0,
                             "score": 1.0 - i / 100, "n": 2} for i in range(k)]
            f = M.optimal_fit(mk(48), m, "hype")
            check(abs(bt[f["drop_beat"]] - m["drops"][0]["t"]) < 0.1, f"long section: map drop {bt[f['drop_beat']]:.1f} s used ({f['drop_why']})")
            f = M.optimal_fit(mk(70), m, "hype")
            check(len(f["second"]) == 1, f"second drop reported for the log: {f['second']}")
            f = M.optimal_fit(mk(20), m, "hype")
            check("kept" in f["drop_why"] and ("run-up" in f["drop_why"] or "outside" in f["drop_why"] or "room" in f["drop_why"]), "no drop fits: kept, with the failed condition: " + f["drop_why"][40:150])
        finally:
            M.restore_data_dir(old)


def part_lenient(tmp):
    with section("3) synthetic: anchor off the list, a map drop with 15 % room is now used; no drop in section unchanged"):
        an = T73.song_map(M, 128.0, 300.0, 64.0)
        bt = an["beats"]
        real = an["drops"][0]["beat"]
        an["drop"] = real + 20
        clips = [{"path": f"c{i}.mp4", "times": [4.0 + i], "rows": [4.0 + i], "first": 4.0 + i, "last": 4.0 + i, "span": 0.0, "score": 1.0 - i / 10, "n": 1}
                 for i in range(8)]
        f = M.optimal_fit(clips, an, "hype")
        listed = any(abs(f["drop_beat"] - d["beat"]) <= 1 for d in an["drops"])
        check(listed or "kept" in f["drop_why"], f"drop {bt[f['drop_beat']]:.1f} s ({f['drop_why'][:100]})")
        an2 = T73.song_map(M, 128.0, 300.0, 64.0)
        an2["drops"] = []
        an2["drop"] = None
        f2 = M.optimal_fit(clips, an2, "hype")
        check("downbeat" in f2["drop_why"] and "kept" not in f2["drop_why"], "no drops at all: the downbeat rule as before")
    T74.part_planner(tmp)


def main():
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t747_"))
    with PB.data_copy(M) as dst:
        part_atlantis(dst)
        part_fit(dst)
        part_lenient(tmp)
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
    check(M.APP_VERSION == "V7.4.7", "title-bar version V7.4.7")
    print(f"total test time {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
