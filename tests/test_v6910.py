"""V6.9.10 tests (small): CS2 stale killfeed rows. A kill row that first appears within 10 s of the clip start and whose victim matches a pre-clip row of the same clip is that
row read again (tracker lost / re-found it) and is dropped ("CS2 stale feed row: already on screen at clip start"). Real clips (E:\\Movies) run on a COPY of montage_data (skipping is a
failure); the real montage_data is compared byte for byte before / after. Ends with ALL OK only if every check ran and passed.
Run from the repo root or tests/:  python tests\\test_v6910.py   (Windows PC with the real clips)"""
import copy
import glob
import json
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ["V697_BASE"] = "3cb6411"                                 # V6.9.9 (main): the guard compares against it
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v697_common import M, check, section, snapshot, REAL_DATA, FAILS, SECTIONS, base_module, rec_of, pool_item, distinct_names, harness      # noqa: E402
from test_v6971 import use_data                                                                                                     # noqa: E402
from test_v6981 import manual_plan, data_copy, norm                                                                                  # noqa: E402
from test_v699 import part_manual                                                                                                    # noqa: E402

ROWS = REAL_DATA / "cs2_rows_v1"
T_ALL = time.time()


def sidecar(key):
    return json.loads(Path(glob.glob(str(ROWS / f"*{key}*"))[0]).read_text(encoding="utf-8"))


def kills_of(sc, on):
    M.CS2_STALE_ON[0] = on
    try:
        return M.border_analysis(copy.deepcopy(sc), M.load_config(), [])
    finally:
        M.CS2_STALE_ON[0] = True


def times(r):
    return [round(k["t"], 1) for k in r["kills"]]


def find(name):
    hits = [p for root in (r"E:\Movies",) for p in Path(root).rglob(name)]
    return hits[0] if hits else None


def part_real(tmp):
    with section("a) real clips (2), (3), (1): cached rows before / after"):
        sc2, sc3, sc1 = sidecar("2026.02.23_-_18.50.59.07"), sidecar("2025.01.06_-_23.13.44.05"), sidecar("2026.02.10_-_19.09.46.22")
        b, a = kills_of(sc2, False), kills_of(sc2, True)
        check(times(b) == [2.8, 13.5] and times(a) == [13.5], f"clip (2): {times(b)} -> {times(a)} (the 2.8 s phantom is gone, the real 13.5 s kill stays)")
        check(any("CS2 stale feed row: already on screen at clip start" in r["reason"] for r in a["rej"]), "the stale row is listed as rejected with the reason")
        b, a = kills_of(sc3, False), kills_of(sc3, True)
        check(times(b) == [2.8, 5.4, 7.6, 9.6, 10.4, 14.2] and times(a) == [7.6, 9.6, 10.4, 14.2], f"clip (3): {times(b)} -> {times(a)} (2.8 and 5.4 gone; Wieczoooor, emila, dz1nky kept)")
        b, a = kills_of(sc1, False), kills_of(sc1, True)
        check(times(b) == times(a) == [2.8, 7.5, 14.5], f"clip (1) unchanged (not stale, separate cause): {times(a)}")
    with section("b) Manual dry path on the data copy"):
        old = use_data(tmp / "data")
        try:
            p2, p3, p1 = (find(f"Counter-strike 2 {n}.DVR.mp4") for n in ("2026.02.23 - 18.50.59.07", "2025.01.06 - 23.13.44.05", "2026.02.10 - 19.09.46.22"))
            check(all([p1, p2, p3]), "real clips present")
            plan, _ = manual_plan("cs2", [p2])
            check(len(plan["takes"]) == 1 and plan["takes"][0]["n"] == 1, f"clip (2): one take with its one real kill ({[t['n'] for t in plan['takes']]})")
            plan, _ = manual_plan("cs2", [p3])
            t = plan["takes"][0]
            first = t["segs"][0][0]
            print(f"     clip (3): {len(plan['takes'])} take(s), source range {first:.2f}-{t['segs'][-1][1]:.2f} s, kills {[round(k, 2) for k in t['kills']]}, victims {t['victims']}")
            check(len(plan["takes"]) == 1 and t["n"] == 3 and [norm(v) for v in t["victims"]][0] == "wieozoooor", f"clip (3): 3 real kills, first is Wieczoooor ({t['victims']})")
            print(f"     clip (3) in the montage: first kill at {t['kills_out'][0]:.2f} s, last kill at {t['kills_out'][-1]:.2f} s of a {t['dur']:.2f} s take")
            check(first <= t["kills"][0] - 1.0 and t["kills_out"][0] >= 1.0 and t["dur"] - t["kills_out"][-1] >= 0.4, "clip (3): run-up before the first real kill (>= 1 s), tail after the last (>= 0.4 s), no kill already in the feed")
            M.CS2_STALE_ON[0] = False
            try:
                off, _ = manual_plan("cs2", [p1])
            finally:
                M.CS2_STALE_ON[0] = True
            on, _ = manual_plan("cs2", [p1])
            check([t_["kills"] for t_ in off["takes"]] == [t_["kills"] for t_ in on["takes"]], "clip (1): plan identical with and without the rule")
            trio = [find(f"Counter-strike 2 2025.02.04 - 09.46.{n}.DVR.mp4") for n in ("13.09", "20.10", "26.11")]
            plan, _ = manual_plan("cs2", trio)
            check(len(plan["takes"]) == 1 and plan["takes"][0]["n"] == 3 and plan["takes"][0]["stitched"], "CS2 trio: ONE stitched take, 3 kills")
        finally:
            old()
    with section("c) known-good multikills and the whole cache: only the 4 reviewed clips change"):
        changed = []
        for f in glob.glob(str(ROWS / "*.json")):
            sc = json.loads(Path(f).read_text(encoding="utf-8"))
            if len(kills_of(sc, False)["kills"]) != len(kills_of(sc, True)["kills"]):
                changed.append(Path(sc["key"].split("|")[0]).name)
        good = ("2025.02.04 - 09.46", "2026.02.12 - 20.19", "2026.02.14 - 23.16.02.02", "2026.02.12 - 19.24.00.20", "2025.02.08 - 19.48.57.15")
        check(not any(g in n for n in changed for g in good), f"none of the known-good multikills changes ({changed})")
        check(len(changed) == 4, f"{len(changed)} of {len(glob.glob(str(ROWS / '*.json')))} clips change (reviewed: 2 phantom 1k+, clip (2), clip (3), 20.20.43.19, 13.53.24.09)")


def part_generated():
    with section("d) generated CS2 sidecars"):
        base = sidecar("2026.02.23_-_18.50.59.07")
        sc = copy.deepcopy(base)
        check(times(kills_of(sc, True)) == [13.5], "pre-clip row + late-read stale row (different spelling zoendd) + one real kill: stale dropped, real kept")
        sc = copy.deepcopy(base)
        sc["tracks"] = [t for t in sc["tracks"] if t["id"] not in (0, 10)]                        # no pre-clip row: the 2.8 s row is a real kill at 2.8 s
        a, b = kills_of(sc, True), kills_of(sc, False)
        check(times(a) == times(b) == [2.8, 13.5], f"no pre-clip row: unchanged ({times(a)})")
        sc = copy.deepcopy(base)
        for t in sc["tracks"]:                                                                      # a different victim 3 s in is a real kill even with a pre-clip row
            if t["id"] in (14, 21, 23):
                for v in t["votes"]:
                    for bx in v["boxes"]:
                        if bx[4].startswith("zo"):
                            bx[4] = "Brandon"
        check(times(kills_of(sc, True)) == [2.8, 13.5], "a different victim 2.8 s in stays a kill")
        sc = copy.deepcopy(base)
        for t in sc["tracks"]:                                                                      # the same victim long after the start (> 10 s) stays (V6.9.8 rule keeps its own limit)
            if t["id"] == 27:
                for v in t["votes"]:
                    for bx in v["boxes"]:
                        if bx[4].startswith("F"):
                            bx[4] = "zoondd"
        check(13.5 in times(kills_of(sc, True)), "the same victim at 13.5 s (> 10 s) is not stale")


def part_guard(tmp):
    with section("e) guard: 50 Valorant + 50 CS2 generated clips (no pre-clip rows) identical to V6.9.9"):
        B = base_module(tmp)
        cfg = M.load_config()
        for game in ("valorant", "cs2"):
            r = random.Random(31 if game == "cs2" else 32)
            vn = distinct_names(400, 41)
            items, vi = [], 0
            for i in range(50):
                dur = r.uniform(9, 24.5)
                ks, t = [], r.uniform(2.0, 4.0)
                while t < dur - 3 and len(ks) < 4:
                    ks.append((round(t, 3), vn[vi]))
                    vi += 1
                    t += r.choice([1.0, 2.5, 4.0, 6.0, 9.0, 11.0])
                items.append(pool_item(rec_of(tmp / f"g10_{game}_{i}.mov", dur, game), ks))
            view = lambda evs: json.dumps([{k: v for k, v in e.items() if k != "rec"} for e in evs], sort_keys=True, default=str)
            evm = M.build_events([dict(x) for x in items], game, cfg, random.Random(3))[0]
            evb = B.build_events([dict(x) for x in items], game, B.load_config(), random.Random(3))[0]
            check(view(evm) == view(evb) and len(evm) > 10, f"{game}: events identical ({len(evm)} events, {sum(e['n'] for e in evm)} kills)")
            plm = harness(M, game, [dict(x) for x in items], None)
            plb = harness(B, game, [dict(x) for x in items], None)
            tk = lambda p: json.dumps([(Path(t["path"]).name, t["segs"], t["kills_out"], t["kills"]) for t in p["takes"]], default=str)
            check(tk(plm) == tk(plb) and len(plm["takes"]) > 2, f"{game}: non-manual make_plan (selection + plan) identical ({len(plm['takes'])} takes)")


def main():
    real_before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t6910_"))
    data_copy(tmp)
    restore0 = use_data(tmp / "gen_data")
    try:
        part_guard(tmp)
    finally:
        restore0()
    part_generated()
    part_real(tmp)
    part_manual(tmp)
    with section("f) real montage_data byte-identical (no excluded files)"):
        after = snapshot(REAL_DATA)
        check(after == real_before, f"real montage_data byte-identical after the tests ({len(real_before)} files; changed: "
                                    f"{sorted(k for k in set(after) | set(real_before) if after.get(k) != real_before.get(k))})")
    print("section times: " + ", ".join(f"{t.split(')')[0]} {s:.0f}s" for t, s in SECTIONS) + f"; total {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
