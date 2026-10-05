"""V6.7.2: (A) CS2 over-count on real garbled reads, (B) the length slider's 150 s reaches the planner.   python3 test_v672.py
Fixtures always run. If montage_data exists (the user's PC) the REAL cached rows are checked too: the 'Replay 2026-06-25 01-27-36.mov'
clip must give exactly 3 kills, every changed CS2 clip is listed before/after, and every cached Valorant clip must give the identical
kill count and timestamps as origin/main (any difference fails). Without montage_data those real checks are SKIPPED (said loudly)."""
import os
import random
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import montage as M                                                                           # noqa: E402
import test_v67 as T                                                                          # noqa: E402

FAILS = []
check = lambda ok, msg: (print(("  ok   " if ok else "  FAIL ") + msg), None if ok else FAILS.append(msg))[0]
FPS, PITCH, RH = M.FPS, 34, 26


# ---------------------------------------------------------------- Part A fixture: the 8 real stored reads
def feed_entry(rows, dur_s, others=(), miss=0.25, seed=5, newest_top=True):
    """Raw OCR frames of a killfeed whose list shifts when a row arrives (newest row on top, older rows pushed DOWN), with OCR misses
    (a row is sometimes not read at all in a frame). rows / others: {'start','end','k':[reads],'v':[reads]}; others = rows of other
    players (they shift the list but are never mine)."""
    rng = random.Random(seed)
    allr = [dict(r, mine=True) for r in rows] + [dict(r, mine=False) for r in others]
    ocr, prev, last_y = [], None, {}
    for f in range(0, int(dur_s * FPS), 4):
        vis = sorted((r for r in allr if r["start"] <= f < r["end"]), key=lambda r: r["start"], reverse=newest_top)
        boxes, blobs = [], []
        for rank, r in enumerate(vis):
            y = 40 + rank * PITCH
            moved = last_y.get(id(r)) not in (None, y)
            first = prev is None or prev < r["start"]
            last_y[id(r)] = y
            if rng.random() < miss and not first:
                continue
            appear = f if (first or moved) else max(r["start"], prev)
            kt = r["k"][(f // 4 + rank) % len(r["k"])]
            vt = r["v"][(f // 4 + 2 * rank) % len(r["v"])]
            boxes.append([100, y - RH // 2, 100 + 14 * len(kt), y + RH // 2, kt, 0.95, "", appear])
            blobs.append([330, y - 10, 90, 20, 0.7])
            boxes.append([450, y - RH // 2, 450 + 14 * len(vt), y + RH // 2, vt, 0.9, "", appear])
        ocr.append([f, f, boxes, blobs])
        prev = f
    return {"ocr": ocr, "frames": int(dur_s * FPS), "v_off": 0.0, "game": "cs2", "v": M.CACHE_V}


def rw(a, b, **kw):
    return dict({"start": int(a * FPS), "end": int(b * FPS)}, **kw)


def replay_real(seed=5, miss=0.25):
    A = rw(10.1, 19.0, k=["fireaxm", "fireaxm", "fireaxe", "fireaxn", "fireaxe"], v=["OO TEKAAB", "due TaKAan", "due TaKAan", "ouO TaKAOD", "OuG TaKAaB"])
    B = rw(11.1, 19.0, k=["fireaxa", "fireaxe", "fireaxe", "fireaxe"], v=["aapn3akAaM", "aapn3akAaM", "aapa3kAeM", "3apaa9KAaM"])
    C = rw(15.8, 24.0, k=["fireaxe +locopazzo", "fireaxe +locopazzo"], v=["Ruat Cohle (Loving Hus...)", "Ruat Cohle (Loving Hus...)"])
    other = rw(14.3, 22.0, k=["Gus", "Gus"], v=["Bob", "Bob"])
    return feed_entry([A, B, C], 27.0, [other], miss, seed)


def part_a(old):
    print("== PART A: CS2 over-count on the real reads of 'Replay 2026-06-25 01-27-36.mov' ==")
    res = []
    for seed in range(8):
        for miss in (0.0, 0.25, 0.4):
            e = replay_real(seed, miss)
            b, a = len(T.kills_of(old, e, "cs2")), len(T.kills_of(M, e, "cs2"))
            res.append((b, a))
    check(all(a == 3 for _, a in res), f"8 stored reads (A x4, B x3, C): exactly 3 kills in all {len(res)} OCR-miss variants "
                                      f"(origin/main gave {sorted(set(b for b, _ in res))}, now {sorted(set(a for _, a in res))})")
    # shifting the other way (newest row at the bottom) and no shift at all
    A = rw(10.1, 19.0, k=["fireaxm", "fireaxe"], v=["OO TEKAAB", "due TaKAan", "ouO TaKAOD", "OuG TaKAaB"])
    B = rw(11.1, 19.0, k=["fireaxa", "fireaxe"], v=["aapn3akAaM", "aapa3kAeM", "3apaa9KAaM"])
    C = rw(15.8, 24.0, k=["fireaxe"], v=["Ruat Cohle"])
    n = len(T.kills_of(M, feed_entry([A, B, C], 27.0, [rw(14.3, 22.0, k=["Gus"], v=["Bob"])], 0.25, 2, newest_top=False), "cs2"))
    check(n == 3, f"same reads, list growing the other way: {n} kills")
    for nm, ra, rb in (("Kristof / Kristina", "Kristof", "Kristina"), ("Nika / Mika", "Nika", "Mika"), ("player1 / player2", "player1", "player2")):
        e = feed_entry([rw(3.0, 11.0, k=["fireaxe"], v=[ra]), rw(6.0, 14.0, k=["fireaxe"], v=[rb])], 16.0, [], 0.0)
        e2 = T.build_entry([T.row(3.0, 11.0, [ra], ["fireaxe"], 0), T.row(6.0, 14.0, [rb], ["fireaxe"], 1)], 16.0, False)
        check(len(T.kills_of(M, e, "cs2")) == 2 and len(T.kills_of(M, e2, "cs2")) == 2, f"{nm}: two kills")
    check(not M.cs2_same_victim("Kristof", "Kristina") and not M.cs2_same_victim("Nika", "Mika") and not M.cs2_same_victim("player1", "player2"),
          "cs2_same_victim keeps Kristof/Kristina, Nika/Mika, player1/player2 apart")
    for a, b in (("OO TEKAAB", "due TaKAan"), ("due TaKAan", "ouO TaKAOD"), ("aapn3akAaM", "aapa3kAeM"), ("aapa3kAeM", "3apaa9KAaM")):
        check(M.cs2_same_victim(a, b), f"garbled reads of one victim join: '{a}' ~ '{b}'")
    check(not M.cs2_same_victim("OO TEKAAB", "aapn3akAaM") and not M.cs2_same_victim("Ruat Cohle", "due TaKAan"), "different garbled victims stay apart")


# ---------------------------------------------------------------- Part B: length
def part_b():
    print("== PART B: length slider 150 s reaches the planner ==")
    import numpy as np
    check(M.LEN_MIN_S == 80 and M.LEN_MAX_S == 150 and M.OPT_RANGE == (80.0, 150.0), "range 80-150 everywhere (LEN_MIN_S/LEN_MAX_S/OPT_RANGE)")
    tmpd = Path(tempfile.mkdtemp(prefix="mt_v672_"))
    old = M.use_data_dir(tmpd / "data")
    real_ca = M.clip_audio
    M.clip_audio = lambda rec, *a, **k: {"stream": None, "lufs": None}
    try:
        for v, want in ((150, 150), (200, 150), (60, 80), (80, 80), (120, 120)):
            M.save_json(M.CONFIG_PATH, dict(M.DEFAULT_CONFIG, length_s=v))
            check(M.load_config()["length_s"] == want, f"saved slider {v} -> load_config {M.load_config()['length_s']} (expected {want})")
        M.save_json(M.CONFIG_PATH, dict(M.DEFAULT_CONFIG, length_s=150))
        check(M.load_config()["length_s"] == 150, "config length_s 150 survives load_config")
        sp = tmpd / "long.mp3"
        M.synth_song(sp, 128.0, layout=(("intro", 8), ("verse", 16), ("build", 4), ("drop", 16), ("breakdown", 8), ("build", 4), ("drop", 16),
                                        ("verse", 8), ("drop", 16), ("outro", 8)))
        an = M.analyse_song(str(sp), 128.0)
        song = {"path": str(sp), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
        seen = {}
        real_pm = M.plan_montage

        def spy(cfg, game, events, song, an, seed, style, target_s, *a, **k):
            seen["target"] = target_s
            return real_pm(cfg, game, events, song, an, seed, style, target_s, *a, **k)
        M.plan_montage = spy
        try:
            def plan(n, tg, manual=True):
                return M.plan_montage(dict(M.DEFAULT_CONFIG), "valorant", M.fake_events(n), song, an, 5, "auto", tg, [], [], manual=manual)
            p150 = plan(90, 150)
            check(seen["target"] == 150, f"planner received target {seen['target']} for slider 150")
            line = next(n for n in p150["notes"] if "FIXED LENGTH" in n)
            print("        " + line[:110])
            check("(slider 150 s)" in line, "plan log says 'slider 150 s'")
            check(p150["duration"] >= 140 and p150["duration"] <= 150.5, f"fixed 150 s with 90 events: plan is {p150['duration']:.0f} s")
            p80 = plan(90, 80)
            check("(slider 80 s)" in next(n for n in p80["notes"] if "FIXED LENGTH" in n) and 70 <= p80["duration"] <= 84,
                  f"slider 80 still works: {p80['duration']:.0f} s")
            p120 = plan(90, 120)
            check(110 <= p120["duration"] <= 120.5, f"slider 120 gives {p120['duration']:.0f} s (not changed)")
            pf = plan(4, 150)
            check(pf["duration"] < 100, f"fixed 150 s with only 4 events stays short, no padding: {pf['duration']:.0f} s")
            for n, mg in ((90, True), (20, True), (90, False)):
                po = plan(n, "optimal", manual=mg)
                check(po["duration"] <= M.OPT_RANGE[1] + 0.05, f"Optimal ({n} events, manual={mg}) never exceeds 150 s: {po['duration']:.0f} s")
        finally:
            M.plan_montage = real_pm
    finally:
        M.clip_audio = real_ca
        M.restore_data_dir(old)
        shutil.rmtree(tmpd, ignore_errors=True)


# ---------------------------------------------------------------- real cache
def real_checks(old):
    entries = T.cached_entries()
    print("== REAL CACHE ==")
    if not entries:
        print("  SKIPPED: no montage_data kills cache here - the real-clip checks (Replay = 3 kills, CS2 before/after table, "
              "VALORANT identical to origin/main) did NOT run. Run this test on the PC with montage_data.")
        return
    cs2 = [(k, e) for k, e in entries if e.get("game") == "cs2"]
    val = [(k, e) for k, e in entries if e.get("game") == "valorant"]
    name = lambda k: k.split("|")[0]
    rep = [(k, e) for k, e in cs2 if "Replay 2026-06-25 01-27-36" in name(k) or "Replay 2026-06-25 01-27-36" in str(e.get("path", ""))]
    check(bool(rep), "the 'Replay 2026-06-25 01-27-36.mov' clip is in the cache")
    for k, e in rep:
        ks = [round(x, 1) for x in T.kills_of(M, e, "cs2")]
        check(len(ks) == 3, f"REAL 'Replay 2026-06-25 01-27-36.mov': {len(ks)} kills {ks} (origin/main: {len(T.kills_of(old, e, 'cs2'))})")
    print(f"  CS2 clips whose kill count changed ({len(cs2)} cached):")
    ch = 0
    for k, e in cs2:
        b, a = len(T.kills_of(old, e, "cs2")), len(T.kills_of(M, e, "cs2"))
        if a != b:
            ch += 1
            print(f"    {name(k)[-70:]:70s} {b} -> {a}")
    print(f"    ({ch} changed)")
    diffs = []
    for k, e in val:
        a0, a1 = old.analyse_entry(e, {}, "valorant"), M.analyse_entry(e, {}, "valorant")
        if T.sig(a0) != T.sig(a1) or [x["t"] for x in a0["kills"]] != [x["t"] for x in a1["kills"]]:
            diffs.append(name(k))
    check(not diffs, f"VALORANT: {len(val)} real clips, kill count and every timestamp identical to origin/main ({len(diffs)} differ: {diffs[:5]})")


def main():
    old = T.load_old("origin/main")                         # the version before this one (V6.7)
    part_a(old)
    part_b()
    print("== VALORANT regression (generated) ==")
    T.valorant_regression(old)
    real_checks(old)
    print("== test_v67.py ==")
    import subprocess
    r = subprocess.run([sys.executable, str(HERE / "test_v67.py")], capture_output=True, text=True, cwd=str(HERE))
    check(r.returncode == 0 and "ALL OK" in r.stdout, "test_v67.py still passes" + ("" if r.returncode == 0 else "\n" + r.stdout[-800:]))
    print(("\nALL OK" if not FAILS and not T.FAILS else f"\n{len(FAILS) + len(T.FAILS)} FAILED:\n  " + "\n  ".join(FAILS + T.FAILS)))
    return 1 if (FAILS or T.FAILS) else 0


if __name__ == "__main__":
    sys.exit(main())
