"""V6.9.8 tests (small, fast): (1) CS2 phantom / re-read kill fix + the duplicate-source-range check, (2) multipart companion inclusion for random / weekly picks
in BOTH games. Real-clip checks (E:\\Movies) run on a COPY of montage_data (skipping is a failure); the real montage_data is compared byte for byte before / after
the whole test, no excluded files. Ends with ALL OK only if every check ran and passed.
Run from the repo root or tests/:  python tests\\test_v698.py   (Windows PC with the real clips)"""
import json
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ["V697_BASE"] = "700975a"                                 # V6.9.7.2: the guard compares against it
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v697_common import M, check, section, snapshot, REAL_DATA, FAILS, SECTIONS, base_module, rec_of, pool_item, distinct_names      # noqa: E402
from test_v6971 import use_data                                                                                                     # noqa: E402

VAL_DIR = Path(r"E:\Movies\VALORANT\Clips")
CS2_DIR = Path(r"E:\Movies\LEGACY\Counter-strike 2")
VAL = {k: VAL_DIR / f"VALORANT 2026-10-07 {k}.mov" for k in ("03-19", "03-21", "03-31-12", "03-31-20", "03-35-20", "03-40-15", "03-40-20")}
TRIO = [CS2_DIR / f"Counter-strike 2 2025.02.04 - 09.46.{n}.DVR.mp4" for n in ("13.09", "20.10", "26.11")]
LOGS = Path(r"E:\Movies\Montages\CS2\logs")
LKS_PLAN = LOGS / "LKS_CS2_V6.9.7.1_2026-10-07.plan.json"          # the latest random CS2 montage the bug was reported on (31 takes, 51 planned kills)
LKS_CLIP = Path(r"E:\Movies\2026\cs clips\Replay 2026-06-25 00-58-01.mov")        # its last take: the P250 2K (Tgr0k_obito, BriskBrain) + one phantom re-read
T_ALL = time.time()


class Stop(Exception):
    pass


def norm(s):
    return M._alnum(str(s).lower())


def data_copy(tmp):
    """Copy of the real montage_data; the used flags / history of every clip this test works with are cleared in the COPY only."""
    dst = tmp / "data"
    shutil.copytree(REAL_DATA, dst, ignore=shutil.ignore_patterns("logs", "plans", "theme_cache"))
    mine = [Path(p).name.lower() for p in list(VAL.values()) + TRIO + [LKS_CLIP]]
    gone = lambda c: any(n in str(c).lower() for n in mine)
    for f, fn in (("used_flags.json", lambda d: {k: v for k, v in d.items() if not gone(k)}),
                  ("used_clips.json", lambda d: {g: [dict(e, clips=[c for c in e.get("clips", []) if not gone(c)]) for e in l] for g, l in d.items()})):
        p = dst / f
        p.write_text(json.dumps(fn(json.loads(p.read_text(encoding="utf-8"))), indent=1), encoding="utf-8")
    M.save_json(dst / "clip_overrides.json", {})
    return dst


def weekly_run(game, pool_paths, picked, extra_events=()):
    """The REAL non-manual make_plan (random / weekly share it) with the scan stubbed out and the pool limited to pool_paths. weekly_pick is replaced by
    `picked` (clip paths picked ALONE, as single-clip events) unless picked is None (the real weekly_pick). plan_montage is stopped after recording what it got.
    Returns (events handed to the planner, notes, pairing log lines)."""
    seen, lines = {}, []
    orig = {k: getattr(M, k) for k in ("auto_scan_set", "run_scan", "game_pool", "weekly_pick", "plan_montage", "out", "LOGONLY")}
    ps = {str(p) for p in pool_paths}
    holder = {}

    def gp(cfg, g, paths=None):
        r = orig["game_pool"](cfg, g, ps)
        holder["pool"] = r[0]
        return r

    def wp(events, cfg, target, style, now_ts=None, game=None):
        if picked is None:
            return orig["weekly_pick"](events, cfg, target, style, now_ts, game)
        singles = []
        for p in picked:
            it = [i for i in holder["pool"] if i["rec"]["path"] == str(p)]
            evs, _ = M.build_events([dict(i) for i in it], game, cfg, random.Random(1))
            singles += evs
        return singles + list(extra_events), []

    def pm(cfg, g, evs, song, an, seed, style, target, *a, **k):
        seen.update(events=list(evs), target=target, style=style)
        raise Stop()
    M.auto_scan_set, M.run_scan, M.game_pool, M.weekly_pick, M.plan_montage = (lambda c, g: []), (lambda *a, **k: None), gp, wp, pm
    M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        try:
            M.make_plan(M.load_config(), game, None, seed=1)
        except Stop:
            pass
    finally:
        for k, v in orig.items():
            setattr(M, k, v)
    return seen, lines


def evs_view(evs):
    return [(sorted(Path(p["path"]).name for p in (e.get("parts") or [{"path": e["path"]}])), [norm(v) for v in e["victims"]], bool(e.get("stitched"))) for e in evs]


def part_bug(tmp):
    with section("1) CS2 bug: phantom re-read kill, duplicate source ranges"):
        check(LKS_PLAN.exists() and LKS_CLIP.exists(), "real latest random CS2 plan + its P250 2K clip present")
        plan = json.loads(LKS_PLAN.read_text(encoding="utf-8"))
        check(len(plan["takes"]) == 31 and sum(t["n"] for t in plan["takes"]) == 51, "the reported plan: 31 takes, 51 planned kills")
        check(M.plan_duplicate_ranges(plan) == [], "no source range is covered twice in the whole reported plan (footage is never replayed; the doubled kill is a phantom kill)")
        newest = max(LOGS.glob("*.plan.json"), key=lambda p: p.stat().st_mtime)
        check(M.plan_duplicate_ranges(json.loads(newest.read_text(encoding="utf-8"))) == [], f"newest CS2 plan ({newest.name}): no source range covered twice")
        old = M.use_data_dir(tmp / "data")
        try:
            pool, _ = M.game_pool(M.load_config(), "cs2", {str(LKS_CLIP), str(CS2_DIR / TRIO[0].name)})
            it = next(i for i in pool if i["rec"]["path"] == str(LKS_CLIP))
            check([norm(k["victim"]) for k in it["kills"]][-3:] == ["tgr0kcobito", "tgrokcobito", "briskbraln"], "detector output unchanged: 3 rows (Tgr0kc obito 13.8, Tgrok_c obito 15.7, BriskBraln 15.7)")
            evs, _ = M.build_events([it], "cs2", M.load_config(), random.Random(1))
            e = max(evs, key=lambda x: x["last"])
            check(e["n"] == 2 and [norm(v) for v in e["victims"]] == ["tgr0kcobito", "briskbraln"], f"P250 2K: the re-read of the first victim is ONE kill, the event has the 2 real kills ({e['victims']})")
            check(any(r["merged"] and "re-read" in r["merged"].get("reason", "") for r in M.LAST_LEDGER[0].rows), "ledger: MERGED_DUP with the reason 'CS2 victim re-read'")
            pl, _ = M.make_plan(M.load_config(), "cs2", [str(LKS_CLIP)], seed=1)               # the same path as the GUI Manual dry
            t = pl["takes"][0]
            check(len(pl["takes"]) == 1 and t["n"] == 2 and len(set(t["kills_out"])) == 2 and M.plan_duplicate_ranges(pl) == [],
                  f"its take (Manual dry): 2 kills at distinct times {t['kills_out']}, slow-mo never replays a used range")
        finally:
            M.restore_data_dir(old)
        B = base_module(tmp)
        song = {"path": "x.mp3", "title": "x", "artist": "a"}
        cfg = M.load_config()
        ks = [(13.77, "Tgr0kc obito"), (15.73, "Tgrok_c obito"), (15.73, "BriskBraln")]
        for game, want in (("cs2", 2), ("valorant", 3)):
            rec = rec_of(tmp / f"rep_{game}.mov", 17.0, game)
            ev = M.build_events([pool_item(rec, ks)], game, cfg, random.Random(1))[0]
            evb = B.build_events([pool_item(rec, ks)], game, B.load_config(), random.Random(1))[0]
            check(ev[0]["n"] == want and (game == "cs2" or ev[0]["times"] == evb[0]["times"]), f"generated replica, {game}: {ev[0]['n']} kills (CS2 {want}, Valorant unchanged = base {evb[0]['n']})")
        rec = rec_of(tmp / "rep3.mov", 20.0, "cs2")
        ev = M.build_events([pool_item(rec, [(5.0, "Alpha11"), (8.0, "Bravo22"), (11.0, "Charlie33")])], "cs2", cfg, random.Random(1))[0]
        check(ev[0]["n"] == 3, "CS2 3K with three different victims stays a 3K")


def part_trio(tmp):
    with section("2) CS2 trio (09.46.13 / 09.46.20 / 09.46.26): any one pulls the other two into ONE take"):
        old = use_data(tmp / "data")
        try:
            for pick in TRIO:
                seen, lines = weekly_run("cs2", TRIO, [pick])
                ev = seen["events"]
                check(len(ev) == 1 and ev[0]["stitched"] and len(ev[0]["parts"]) == 3 and [norm(v) for v in ev[0]["victims"]] == ["danok3", "purplokush", "novarsaynever"],
                      f"picked {pick.name[-18:]}: ONE stitched take with the other two, kills 1, 2, 3 in order ({evs_view(ev)})")
                check(any("pair partner of" in l for l in lines), "partners flagged in the log as 'pair partner of <clip>'")
            seen, _ = weekly_run("cs2", TRIO, None)                                        # the REAL weekly_pick (whole pool; the pool-level link and the pairing step both lead to ONE event)
            check(any(len(e.get("parts") or []) == 3 for e in seen["events"]), "real weekly_pick: the trio comes out as one 3-part event")
        finally:
            old()


def part_valorant(tmp):
    with section("3) Valorant on the real clips: companions of the 4K and the Ace (random / weekly path)"):
        old = use_data(tmp / "data")
        try:
            g1, g2 = {VAL["03-31-12"], VAL["03-31-20"]}, {VAL["03-40-15"], VAL["03-40-20"]}
            for pick in (VAL["03-40-15"], VAL["03-40-20"]):                                  # the Ace: the two clips are both needed (2 + 4 rows, one duplicate)
                seen, lines = weekly_run("valorant", sorted(g2), [pick])
                ev = seen["events"]
                names = {Path(p["path"]).name for p in ev[0].get("parts", [])} if ev else set()
                check(len(ev) == 1 and names == {p.name for p in g2} and ev[0]["n"] == 5, f"picked {pick.name}: its partner is pulled, ONE stitched Ace with 5 kills")
            for pick in (VAL["03-31-12"], VAL["03-31-20"]):                                 # the 4K (override OFF): 03-31-12 shows all 3 kills, 03-31-20 adds none
                seen, lines = weekly_run("valorant", sorted(g1), [pick])
                v = evs_view(seen["events"])
                check(len(v) == 1 and v[0][1] == ["louma", "kurotech", "mitski"], f"picked {pick.name[-12:]}: the whole 4K fight (Louma, Kurotech, mitski), companion's rows merged ({v[0][1]})")
            M.set_clip_override([str(VAL["03-31-20"])], True)                               # override ON: 03-31-20 holds the 4th kill (Alexandre), so it IS required
            try:
                for pick in (VAL["03-31-12"], VAL["03-31-20"]):
                    seen, lines = weekly_run("valorant", sorted(g1), [pick])
                    ev = seen["events"]
                    check(len(ev) == 1 and ev[0]["n"] == 4 and len(ev[0]["parts"]) == 2 and any("pair partner of" in l for l in lines),
                          f"override ON, picked {pick.name[-12:]}: the companion is pulled, ONE stitched 4K with 4 kills")
            finally:
                M.set_clip_override([str(VAL["03-31-20"])], False)
            seen, _ = weekly_run("valorant", sorted(g1 | g2), [VAL["03-31-12"], VAL["03-40-20"]])
            v = evs_view(seen["events"])
            check(len(v) == 2 and sorted(len(x[1]) for x in v) == [3, 5], f"the 4K and the Ace stay two separate events ({[len(x[1]) for x in v]} kills)")
            seen, _ = weekly_run("valorant", sorted(g2), None)                              # the REAL weekly_pick
            check(any(len(e.get("parts") or []) == 2 for e in seen["events"]), "real weekly_pick: the Ace comes out as one 2-part event")
            # (e) no multipart: pulls nothing;  (f) targets / slots unchanged, nobody displaced
            decoys = [VAL["03-21"], VAL["03-35-20"]]
            seen, lines = weekly_run("valorant", decoys, decoys)
            check(len(seen["events"]) == 2 and all(len(e.get("parts") or [1]) == 1 for e in seen["events"]) and not any("pair partner of" in l for l in lines), "a clip with no multipart pulls nothing")
            seen, _ = weekly_run("valorant", sorted(g1) + decoys, [VAL["03-31-12"]] + decoys)
            v = evs_view(seen["events"])
            check(len(v) == 3 and sum(1 for x in v if len(x[1]) == 3) == 1 and sorted(x[0][0][-9:] for x in v if len(x[1]) < 3) == ["03-21.mov", "35-20.mov"],
                  "3 picked clips -> 3 events: the 4K replaces its slot, the decoys are still there (nothing displaced)")
            seen0, _ = weekly_run("valorant", decoys, decoys)
            check((seen["target"], seen["style"]) == (seen0["target"], seen0["style"]), "length target / style handed to the planner unchanged")
        finally:
            old()


def part_guard(tmp):
    with section("4) guard: 50 Valorant + 50 CS2 generated clips without multipart: events, plans and selection identical to V6.9.7.2"):
        from v697_common import harness
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
                items.append(pool_item(rec_of(tmp / f"g8_{game}_{i}.mov", dur, game), ks))
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
    tmp = Path(tempfile.mkdtemp(prefix="t698_"))
    tmp.mkdir(exist_ok=True)
    restore0 = use_data(tmp / "gen_data")
    try:
        part_guard(tmp)
    finally:
        restore0()
    shutil.rmtree(tmp / "gen_data", ignore_errors=True)
    data_copy(tmp)
    with section("0) data copy"):
        check((tmp / "data" / "config.json").exists(), "working on a copy of montage_data")
    restore = use_data(tmp / "data")
    try:
        part_bug(tmp)
    finally:
        restore()
    part_trio(tmp)
    part_valorant(tmp)
    with section("5) real montage_data byte-identical (no excluded files)"):
        after = snapshot(REAL_DATA)                                    # V6.9.8.1: on a mismatch the message names the changed files (the guard itself is unchanged)
        changed = sorted(k for k in set(after) | set(real_before) if after.get(k) != real_before.get(k))
        check(after == real_before, f"real montage_data byte-identical after the tests ({len(real_before)} files; changed: {changed})")
    total = time.time() - T_ALL
    print("section times: " + ", ".join(f"{t.split(')')[0]} {s:.0f}s" for t, s in SECTIONS) + f"; total {total:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
