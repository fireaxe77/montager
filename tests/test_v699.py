"""V6.9.9 tests (small): (a) back-to-back stitched clips (23.05.17.12 + 31.13 + 50.14) plan with a clean cut list (no footage outside a clip, every kill once, in order);
21.04.36.03 (+ 21.04.50.04) analysed; (b) generated stitch with missing footage between the clips; (c) the per-take skip fallback; (d) ledger accounting (weekly path, companions added:
rows of clips that were not selected are RANKED_OUT, never LOST); (e) Valorant 2026-10-07 manual picks unchanged; (f) guard: 50 + 50 generated clips identical to V6.9.8.1.
Real-clip checks (E:\\Movies) run on a COPY of montage_data (skipping is a failure); the real montage_data is compared byte for byte before / after (no excluded files).
Run from the repo root or tests/:  python tests\\test_v699.py   (Windows PC with the real clips)"""
import json
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ["V697_BASE"] = "2bd6273"                                 # V6.9.8.1 (main): the guard compares against it
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v697_common import M, check, section, snapshot, REAL_DATA, FAILS, SECTIONS, base_module, rec_of, pool_item, distinct_names, harness      # noqa: E402
from test_v6971 import use_data, run_real, takes_view, states, VAL, CLIPS                                                                       # noqa: E402
from test_v6981 import lines_of, manual_plan, data_copy, norm                                                                                    # noqa: E402

VLEG = Path(r"E:\Movies\LEGACY\Valorant")
A = [VLEG / f"Valorant 2025.10.15 - {x}.DVR.mp4" for x in ("23.05.17.12", "23.05.31.13", "23.05.50.14")]
B = [VLEG / f"Valorant 2025.10.15 - {x}.DVR.mp4" for x in ("21.04.36.03", "21.04.50.04")]
SEEDS = (497538, 538302, 731155)
T_ALL = time.time()


def full_plan(game, pool_paths, picked, seed):
    """The REAL non-manual make_plan (weekly / Force new): scan stubbed, weekly_pick pinned to `picked` (clip singles) + the real pairing / companion step, the REAL planner
    and cut-list repair. pool_paths None = the whole game's pool (all other rows are not selected). Returns (plan, ledger, log lines)."""
    lines = []
    orig = {k: getattr(M, k) for k in ("auto_scan_set", "run_scan", "weekly_pick", "out", "LOGONLY")}
    ps = None if pool_paths is None else {str(p) for p in pool_paths}
    og = M.game_pool
    holder = {}

    def gp(cfg, g, paths=None):
        r = og(cfg, g, ps)
        holder["pool"] = r[0]
        return r

    def wp(events, cfg, target, style, now_ts=None, game=None):
        singles = []
        for p in picked:
            it = [i for i in holder["pool"] if i["rec"]["path"] == str(p)]
            M.LEDGER_SUBCALL[0] = True                      # the real weekly_pick does not rebuild events: keep the main run's ledger
            try:
                singles += M.build_events([dict(i) for i in it], game, cfg, random.Random(1))[0]
            finally:
                M.LEDGER_SUBCALL[0] = False
        return singles, []
    M.auto_scan_set, M.run_scan, M.weekly_pick, M.game_pool = (lambda c, g: []), (lambda *a, **k: None), wp, gp
    M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        plan, _ = M.make_plan(M.load_config(), game, None, seed=seed)
    finally:
        for k, v in orig.items():
            setattr(M, k, v)
        M.game_pool = og
    return plan, M.LAST_LEDGER[0], lines


def kills_ok(plan):
    """every take: all its kills inside the first / last part's footage window, strictly increasing, every (clip, time) once."""
    for t in plan["takes"]:
        if t["kills"] != sorted(t["kills"]) or len(set(t["kills"])) != len(t["kills"]):
            return False
        for k in t["rows"]:
            if not any(sg[0] - 1e-3 <= k <= sg[1] + 1e-3 for sg in t["segs"] if sg[2] > 0):
                return False
    return True


def part_real(tmp):
    with section("a) REAL clips: 23.05.17.12 + 31.13 + 50.14 and 21.04.36.03 + 21.04.50.04 (Manual dry path)"):
        for p in A + B:
            check(p.exists(), f"real clip present: {p.name}")
        old = use_data(tmp / "data")
        try:
            plan, lines = manual_plan("valorant", A)
            check(M.verify_cutlist(plan) == [], f"cut list check OK for 23.05.17.12 + 31.13 + 50.14 ({M.verify_cutlist(plan)})")
            t = plan["takes"][0]
            check(len(plan["takes"]) == 1 and t["n"] == 4 and [norm(v) for v in t["victims"]] == ["farli", "oskir27", "davus", "josanjar"] and t["stitched"],
                  f"one stitched take, kills FARLI, Oskir27, Davus, Josanjar once and in order ({t['victims']})")
            check(all(-0.01 <= sg[0] - t["srcs"][sg[4]]["shift"] and sg[1] - t["srcs"][sg[4]]["shift"] <= t["srcs"][sg[4]]["dur"] for sg in t["segs"]), "every segment lies inside its own clip")
            check(kills_ok(plan) and any("missing footage" in (t.get("stitch_note") or "") for t in plan["takes"]), "kills in order inside the footage; the closed gap is logged in the stitch note")
            check(M.ts(-1.8).startswith("-0:01"), f"negative times are shown as -0:01.8, not -1:58.2 ({M.ts(-1.8)})")
            old_rt = M.verify_cutlist
            try:
                plan2, lines2 = manual_plan("valorant", B)
                v = M.verify_cutlist(plan2)
                check(v == [], f"21.04.36.03 (+ 04.50.04) Manual: if it forms a take the cut list is OK ({v}, {len(plan2['takes'])} take(s))")
            except RuntimeError as ex:
                check("no kill event has enough footage" in str(ex), f"21.04.36.03 (+ 04.50.04): the planner says why no take forms ({ex}); not a cut-list problem")
        finally:
            old()


def part_weekly(tmp):
    with section("b) weekly / Force new: the failed seeds, companions added, cut list OK, ledger 0 lost + large 'ranked out'"):
        old = use_data(tmp / "data")
        try:
            for seed in SEEDS:
                plan, led, lines = full_plan("valorant", None, [A[1], B[0]], seed)
                c = states(led)
                check(M.verify_cutlist(plan) == [], f"seed {seed}: cut list OK ({M.verify_cutlist(plan)}), {len(plan['takes'])} take(s)")
                check(not c.get("LOST") and c.get("RANKED_OUT", 0) > 50, f"seed {seed}: ledger 0 lost, {c.get('RANKED_OUT', 0)} ranked out ({c})")
                check(kills_ok(plan), f"seed {seed}: no kill outside its footage, kills in order")
        finally:
            old()


def part_generated(tmp):
    with section("c) generated: a kill at negative time (previous clip) with the stitch; no footage outside any clip, no kill lost"):
        cfg = M.load_config()
        r0 = rec_of(tmp / "gA.mov", 15.0, "valorant")
        r1 = rec_of(tmp / "gB.mov", 13.6, "valorant")
        base = 1_760_000_000.0
        for r, end in ((r0, base + 15.0), (r1, base + 15.0 + 14.0)):
            r["mtime"] = end
        for r, p in ((r0, tmp / "gA.mov"), (r1, tmp / "gB.mov")):
            p.write_bytes(b"x")
            os.utime(p, (r["mtime"], r["mtime"]))
        items = [pool_item(r0, [(13.6, "Alphaone")]), pool_item(r1, [(0.7, "Bravotwo"), (9.5, "Charliethr")])]
        evs, _ = M.build_events([dict(i) for i in items], "valorant", cfg, random.Random(1))
        check(sum(e["n"] for e in evs) == 3 and all(e["times"] == sorted(e["times"]) for e in evs), f"generated: 3 kills, none lost ({[e['n'] for e in evs]})")
        for e in evs:
            if e.get("stitched"):
                ps_ = e["parts"]
                check(all(ps_[i + 1]["start"] <= ps_[i]["end"] + 1e-6 for i in range(len(ps_) - 1)), "a stitched event has no footage missing between its parts")
                check(all(ps_[0]["start"] - 1e-6 <= t_ <= ps_[-1]["end"] + 1e-6 for t_ in e["times"]), "every kill lies inside the footage of its parts")
    with section("d) take-skip fallback: a take with a cut-list problem is dropped and re-planned alone, the rest renders"):
        real = M.verify_cutlist
        calls = {"n": 0}

        def fake(plan):
            calls["n"] += 1
            bad = real(plan)
            if calls["n"] == 1 and len(plan["takes"]) > 1:
                bad = bad + ["take 2: footage -0.45--0.15s is outside its clip"]
            return bad
        old = use_data(tmp / "data")
        M.verify_cutlist = fake
        try:
            plan, lines = manual_plan("valorant", [CLIPS / f"VALORANT 2026-10-07 {n}.mov" for n in ("03-19", "03-21", "03-35-20", "03-40-15", "03-40-20")])
            check(any(l.startswith("take skipped: ") and "outside its clip" in l for l in lines), "log 'take skipped: <clip> (<reason>)'")
            check(len(plan["takes"]) >= 2 and real(plan) == [], f"the rest is planned and clean ({len(plan['takes'])} takes)")
        finally:
            M.verify_cutlist = real
            old()


def part_manual(tmp):
    with section("e) Valorant 2026-10-07 manual picks unchanged"):
        restore = use_data(tmp / "data")
        try:
            plan, led = run_real("valorant", [CLIPS / n for n in VAL], False)
            tv, c = takes_view(plan), states(led)
            check(len(tv) == 4 and c.get("PLACED") == 11 and c.get("MERGED_DUP") == 3 and not c.get("LOST"), f"override OFF: 4 events, 11 placed, 3 merged, 0 lost ({c})")
            plan, led = run_real("valorant", [CLIPS / n for n in VAL], True)
            tv = takes_view(plan)
            t4 = next((t for t in tv if "03-31" in t[0]), None)
            check(len(tv) == 4 and t4 and t4[1] == 4 and not states(led).get("LOST"), f"override ON: the 4K has 4 kills ({t4 and t4[2]})")
            M.save_json(M.DATA / "clip_overrides.json", {})
        finally:
            restore()


def part_guard(tmp):
    with section("f) guard: 50 Valorant + 50 CS2 generated clips without multipart: events, plans and selection identical to V6.9.8.1"):
        Bm = base_module(tmp)
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
                items.append(pool_item(rec_of(tmp / f"g9_{game}_{i}.mov", dur, game), ks))
            view = lambda evs: json.dumps([{k: v for k, v in e.items() if k != "rec"} for e in evs], sort_keys=True, default=str)
            evm = M.build_events([dict(x) for x in items], game, cfg, random.Random(3))[0]
            evb = Bm.build_events([dict(x) for x in items], game, Bm.load_config(), random.Random(3))[0]
            check(view(evm) == view(evb) and len(evm) > 10, f"{game}: events identical ({len(evm)} events, {sum(e['n'] for e in evm)} kills)")
            plm = harness(M, game, [dict(x) for x in items], None)
            plb = harness(Bm, game, [dict(x) for x in items], None)
            tk = lambda p: json.dumps([(Path(t["path"]).name, t["segs"], t["kills_out"], t["kills"]) for t in p["takes"]], default=str)
            check(tk(plm) == tk(plb) and len(plm["takes"]) > 2, f"{game}: non-manual make_plan (selection + plan) identical ({len(plm['takes'])} takes)")


def main():
    real_before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t699_"))
    data_copy(tmp)
    restore0 = use_data(tmp / "gen_data")
    try:
        part_guard(tmp)
        part_generated(tmp)
    finally:
        restore0()
    shutil.rmtree(tmp / "gen_data", ignore_errors=True)
    part_real(tmp)
    part_weekly(tmp)
    part_manual(tmp)
    with section("g) real montage_data byte-identical (no excluded files)"):
        after = snapshot(REAL_DATA)
        check(after == real_before, f"real montage_data byte-identical after the tests ({len(real_before)} files; changed: "
                                    f"{sorted(k for k in set(after) | set(real_before) if after.get(k) != real_before.get(k))})")
    print("section times: " + ", ".join(f"{t.split(')')[0]} {s:.0f}s" for t, s in SECTIONS) + f"; total {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
