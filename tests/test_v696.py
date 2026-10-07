"""V6.9.6: (A) effective-fps interpolation + fpscontent / interpbench, (B) CS2 pair-partner order + grouporder, (C) repository declutter round 2.
All media generated (320x180 clips); no real clips, no real renders. Prints the time of every section.
   python tests/test_v696.py            (also works from inside tests/)
Only this version's checks + the Valorant / CS2 guards; the long older suites are not run."""
import importlib
import json
import random
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from v696_common import *                                                                    # noqa: F401,F403,E402
import v696_common as C                                                                       # noqa: E402
from v696_common import M, check, section, snapshot, ROOT, REAL_DATA, FAILS, SECTIONS          # noqa: E402

T_ALL = time.time()


def part_guards(tmp):
    with section("10) Valorant / CS2 guards: kills, timestamps and plans on 100 generated clips each identical to the base"):
        import test_v693 as T
        B = T.load_baseline(tmp, C.BASE_REF)
        if B is None:
            check(False, "base commit not available")
            return
        view = lambda mod, e, g: json.dumps(mod.analyse_entry(e, {}, g), sort_keys=True, default=str)
        for game in ("valorant", "cs2"):
            ents = T.gen_entries(100, game)
            nd = sum(view(M, e, game) != view(B, e, game) for e in ents)
            kn = sum(len(M.analyse_entry(e, {}, game)["kills"]) for e in ents)
            check(nd == 0 and kn > 20, f"{game}: kills, timestamps, deaths, revives of 100 generated clips identical to the base ({nd} differences, {kn} kills)")
        vdir = Path(tmp) / "gv"
        vdir.mkdir()
        rng = random.Random(21)
        vn = T.names(400, 5)
        for game in ("valorant", "cs2"):
            items = []
            for i in range(100):
                p = vdir / f"{game}_{i}.mov"
                p.write_bytes(b"x")
                ks = sorted(rng.sample(range(2, 40), rng.randint(1, 4)))
                items.append(T.pool_item(T.rec_of(p, 45, game), [(float(k), vn[3 * i + j]) for j, k in enumerate(ks)]))
                items[-1]["rec"]["path"] = str(p)
            cfg = M.load_config()
            M.verify_stitch = T.REAL_VS
            ev, _ = C.logged(M.build_events, items[:30], game, cfg, random.Random(3))
            evb, _ = C.logged(B.build_events, items[:30], game, B.load_config(), random.Random(3))
            song = {"path": "x.mp3", "title": "x", "artist": "a"}
            pm = M.plan_montage(cfg, game, ev[0], song, M.default_song_map(), 5, "auto", "optimal", [], [])
            pb = B.plan_montage(B.load_config(), game, evb[0], song, B.default_song_map(), 5, "auto", "optimal", [], [])
            tk = lambda p: [(Path(t["path"]).name, t["segs"], t["kills_out"]) for t in p["takes"]]
            check(len(pm["takes"]) > 3 and tk(pm) == tk(pb) and round(pm["duration"], 3) == round(pb["duration"], 3), f"{game}: events and plan ({len(pm['takes'])} takes) identical to the base")


def main():
    real_before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t696_"))
    old = M.use_data_dir(tmp / "data")
    try:
        for name in ("v696_parta", "v696_partb", "v696_partc"):
            if (HERE / f"{name}.py").exists():
                importlib.import_module(name).run(tmp)
        part_guards(tmp)
    finally:
        M.restore_data_dir(old)
    with section("real montage_data"):
        check(snapshot(REAL_DATA) == real_before, f"real montage_data byte-identical after the tests ({len(real_before)} files{'; folder absent' if not real_before else ''})")
    total = time.time() - T_ALL
    print("section times: " + ", ".join(f"{t.split(')')[0]} {s:.0f}s" for t, s in SECTIONS))
    print(f"total test time {total:.1f} s" + ("" if total < 180 else "  (OVER the 3 minute limit)"))
    if total >= 180:
        FAILS.append("over 3 minutes")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
