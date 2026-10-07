"""V6.9.8.1 tests (small): (a) companions of RANDOM-pick (App.random_pick_ticks, then the Manual plan of what it ticked) and weekly / Force-new picks (make_plan non-manual)
on the real clips (E:\\Movies) with a COPY of montage_data and the REAL used flags (companions are used clips); (b) interpolation default; (c) 50 + 50 generated clips
without multipart identical to V6.9.8. The real montage_data is compared byte for byte before / after (no excluded files). Ends with ALL OK only if every check ran and passed.
Run from the repo root or tests/:  python tests\\test_v6981.py   (Windows PC with the real clips)"""
import json
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

os.environ["V697_BASE"] = "977a35d"                                 # V6.9.8: the guard compares against it
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v697_common import M, check, section, snapshot, REAL_DATA, FAILS, SECTIONS, base_module, rec_of, pool_item, distinct_names, harness      # noqa: E402
from test_v6971 import use_data                                                                                                     # noqa: E402

VAL_DIR = Path(r"E:\Movies\VALORANT\Clips")
VLEG = Path(r"E:\Movies\LEGACY\Valorant")
CS2_DIR = Path(r"E:\Movies\LEGACY\Counter-strike 2")
TRIO = [CS2_DIR / f"Counter-strike 2 2025.02.04 - 09.46.{n}.DVR.mp4" for n in ("13.09", "20.10", "26.11")]
V4 = [VLEG / f"Valorant 2025.10.24 - 19.44.{n}.DVR.mp4" for n in ("11.02", "38.03", "44.04")]
V4K = {VAL_DIR / f"VALORANT 2026-10-07 {a}.mov": VAL_DIR / f"VALORANT 2026-10-07 {b}.mov" for a, b in (("03-31-12", "03-31-20"), ("03-31-20", "03-31-12"),
                                                                                                     ("03-40-15", "03-40-20"), ("03-40-20", "03-40-15"))}
DECOYS = [VAL_DIR / f"VALORANT 2026-10-07 {k}.mov" for k in ("03-21", "03-35-20")]
T_ALL = time.time()


class Stop(Exception):
    pass


def norm(s):
    return M._alnum(str(s).lower())


def lines_of(fn, *a, **k):
    lines = []
    ro, rl = M.out, M.LOGONLY
    M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        res = fn(*a, **k)
    finally:
        M.out, M.LOGONLY = ro, rl
    return res, lines


def random_pick(game, picked, include_used=True):
    """The REAL App.random_pick_ticks (GUI method) on a stand-in self whose candidate list is exactly `picked`; random.sample picks them all.
    Returns (ticked paths, log lines)."""
    cands = {str(p): {"path": str(p), "kills": 2, "used": "x"} for p in picked}
    s = mock.MagicMock()
    s.m_incl_used.get.return_value = include_used
    s.ctree.get_children.return_value = list(cands)
    s.byp = cands
    s.pick_count.return_value = len(cands)
    s.stree.selection.return_value = ()
    s.songs = []
    s.m_style.get.return_value = "auto"
    s._snap = {"m_game": game}
    s.run_task = lambda name, fn, *a: fn(*a)
    s.q.put = lambda item: item[1]()
    s.ticked = set()
    _, lines = lines_of(M.App.random_pick_ticks, s)
    return {str(p) for p in s.ticked}, lines


def manual_plan(game, paths, seed=1):
    (plan, _), lines = lines_of(M.make_plan, M.load_config(), game, [str(p) for p in paths], seed=seed)
    return plan, lines


def take_names(t):
    srcs = t.get("srcs") or []
    return [Path(x["path"]).name for x in srcs] if srcs else [Path(t["path"]).name]


def weekly_run(game, pool_paths, picked):
    """The real non-manual make_plan (weekly / Auto / Force new share it): scan stubbed, pool limited, the pick = `picked` clips alone (as weekly_pick returns them);
    the REAL planner runs. Returns (events handed to the planner, plan, log lines)."""
    seen, lines = {}, []
    orig = {k: getattr(M, k) for k in ("auto_scan_set", "run_scan", "game_pool", "weekly_pick", "out", "LOGONLY", "plan_montage")}
    ps = {str(p) for p in pool_paths}
    holder = {}

    def gp(cfg, g, paths=None):
        r = orig["game_pool"](cfg, g, ps)
        holder["pool"] = r[0]
        return r

    def wp(events, cfg, target, style, now_ts=None, game=None):
        singles = []
        for p in picked:
            it = [i for i in holder["pool"] if i["rec"]["path"] == str(p)]
            singles += M.build_events([dict(i) for i in it], game, cfg, random.Random(1))[0]
        return singles, []

    def pm(cfg, g, evs, *a, **k):
        seen["events"] = list(evs)
        seen["plan"] = orig["plan_montage"](cfg, g, evs, *a, **k)
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
    return seen["events"], seen.get("plan"), lines


def data_copy(tmp):
    dst = tmp / "data"
    shutil.copytree(REAL_DATA, dst, ignore=shutil.ignore_patterns("logs", "plans", "theme_cache"))      # real used flags kept
    M.save_json(dst / "clip_overrides.json", {})
    return dst


def part_companions(tmp):
    flags = json.loads((REAL_DATA / "used_flags.json").read_text(encoding="utf-8"))
    used = lambda p: M._pkey(str(p)) in {M._pkey(k) for k in flags}
    with section("a1) CS2 trio: Random pick (real GUI method) ticks all three, the Manual plan renders ONE 3-kill take in order; companions are USED clips"):
        old = use_data(tmp / "data")
        try:
            check(all(used(p) for p in TRIO), "real used flags: all three trio clips are flagged used")
            for pick in TRIO:
                ticked, lines = random_pick("cs2", [pick])
                check(ticked == {str(p) for p in TRIO}, f"random pick of {pick.name[-18:-8]} ticks the whole trio ({sorted(Path(t).name[-18:-8] for t in ticked)})")
                check(any(l.startswith("companion already used, added to keep the multikill together:") for l in lines)
                      and any(l.startswith("random pick: added 2 companion clip(s)") for l in lines), "log: 'companion already used, added ...' + 'random pick: added 2 companion clip(s)'")
                plan, plines = manual_plan("cs2", ticked)
                t = plan["takes"]
                check(len(t) == 1 and take_names(t[0]) == [p.name for p in TRIO] and t[0]["n"] == 3, f"render plan of the ticked list: ONE take, {len(t)} take(s) {[take_names(x) for x in t]}, {t[0]['n']} kills")
            plan, plines = manual_plan("cs2", [TRIO[1]])                                      # hand-ticked: unchanged (companion step is NOT run for it, used neighbours skipped)
            check(len(plan["takes"]) == 1 and len(take_names(plan["takes"][0])) == 1 and not any("companion" in l for l in plines), "hand-ticked 09.46.20 alone: unchanged (lone take, no companion logic)")
        finally:
            old()
    with section("a2) Valorant: Random pick pulls the partners (used clips) into one take"):
        old = use_data(tmp / "data")
        try:
            for pick in (V4[1], V4[2]):
                ticked, lines = random_pick("valorant", [pick])
                check(ticked == {str(p) for p in V4}, f"random pick of {pick.name[-18:-8]} pulls 19.44.11.02 ({sorted(Path(t).name[-18:-8] for t in ticked)})")
                plan, _ = manual_plan("valorant", ticked)
                t = plan["takes"]
                # 19.44.11.02's only kill is 22.9 s before the fight of the other two (> the 12 s window): build_events (frozen) keeps it as a separate fight of the group,
                # so the render is the 3-kill take 38.03 + 44.04; the companion IS pulled (ticked above) and is in the pool
                check(len(t) == 1 and t[0]["n"] == 3 and len(take_names(t[0])) == 2, f"ONE take, {t[0]['n']} kills, clips {take_names(t[0])} (the 4th kill is a separate fight, gap 22.9 s)")
            for pick, partner in V4K.items():
                ticked, lines = random_pick("valorant", [pick])
                check(ticked == {str(pick), str(partner)}, f"random pick of {pick.name[-8:]} pulls {partner.name[-8:]}")
            ticked, lines = random_pick("valorant", DECOYS)
            check(ticked == {str(p) for p in DECOYS} and not any("companion" in l for l in lines), "clips without a multipart pull nothing")
        finally:
            old()
    with section("a3) weekly / Force new (make_plan non-manual, real planner): companions added even though used; targets / slots unchanged"):
        old = use_data(tmp / "data")
        try:
            for pick in TRIO:
                evs, plan, lines = weekly_run("cs2", TRIO, [pick])
                check(len(evs) == 1 and len(evs[0].get("parts") or []) == 3 and [norm(v) for v in evs[0]["victims"]] == ["danok3", "purplokush", "novarsaynever"]
                      and any(l.startswith("companion already used, added to keep the multikill together:") for l in lines), f"CS2 weekly pick {pick.name[-18:-8]}: ONE 3-part event, log line present")
                check(len(plan["takes"]) == 1 and plan["takes"][0]["n"] == 3 and len(take_names(plan["takes"][0])) == 3, "the real planner keeps it as one 3-kill take")
            for pick in (V4[1], V4[2]):
                evs, plan, lines = weekly_run("valorant", V4, [pick])
                check(len(evs) == 1 and evs[0]["n"] == 3 and any(l.startswith("companion already used, added to keep the multikill together:") and "19.44.11.02" in l for l in lines),
                      f"Valorant weekly pick {pick.name[-18:-8]}: used companion 19.44.11.02 added (log), ONE event, {evs[0]['n']} kills (its kill is a separate fight, gap 22.9 s)")
                check(len(plan["takes"]) == 1 and plan["takes"][0]["n"] == 3, "the real planner keeps it as one take")
            for pick, partner in V4K.items():
                evs, _, lines = weekly_run("valorant", [pick, partner], [pick])
                need = 2 if "03-40" in pick.name else 1                      # 03-31-20 shows no kill that 03-31-12 lacks (override off): one clip carries the 3K
                check(len(evs) == 1 and len(evs[0].get("parts") or [1]) >= need and any("pair partner of" in l for l in lines),
                      f"Valorant weekly pick {pick.name[-8:]}: partner pulled ('pair partner of'), one event, {evs[0]['n']} kills")
            evs, _, lines = weekly_run("valorant", DECOYS, DECOYS)
            check(len(evs) == 2 and not any("companion" in l for l in lines), "weekly: a clip without a multipart pulls nothing")
        finally:
            old()


def part_interp(tmp):
    with section("b) interpolation default"):
        for cfg in ({}, {"interpolate_low_fps": False}):
            plan = {"takes": []}
            res, lines = lines_of(M.interp_prepare, plan, dict(cfg), tmp)
            check(res is plan and any("interpolation off" in l for l in lines), f"config {cfg}: off (nothing probed)")
        try:
            _, lines = lines_of(M.interp_prepare, {"takes": []}, {"interpolate_low_fps": True}, tmp)
        except Exception as ex:                                                          # an empty plan may stop later; only the 'off' line matters
            lines = [f"stopped after the switch: {ex}"]
        check(not any("interpolation off" in l for l in lines), "an existing config value true is respected")
        src = Path(M.__file__).read_text(encoding="utf-8")
        check('BooleanVar(value=bool(self.cfg.get("interpolate_low_fps", False)))' in src, "Settings checkbox defaults to unchecked when the key is missing")
        check(M.DEFAULT_CONFIG.get("interpolate_low_fps", False) is False, "DEFAULT_CONFIG has no true default")


def part_guard(tmp):
    with section("c) guard: 50 Valorant + 50 CS2 generated clips without multipart: events, plans and selection identical to V6.9.8"):
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
                items.append(pool_item(rec_of(tmp / f"g81_{game}_{i}.mov", dur, game), ks))
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
    tmp = Path(tempfile.mkdtemp(prefix="t6981_"))
    restore0 = use_data(tmp / "gen_data")
    try:
        part_interp(tmp)
        part_guard(tmp)
    finally:
        restore0()
    shutil.rmtree(tmp / "gen_data", ignore_errors=True)
    data_copy(tmp)
    part_companions(tmp)
    with section("d) real montage_data byte-identical (no excluded files)"):
        after = snapshot(REAL_DATA)
        check(after == real_before, f"real montage_data byte-identical after the tests ({len(real_before)} files; changed: "
                                    f"{sorted(k for k in set(after) | set(real_before) if after.get(k) != real_before.get(k))})")
    print("section times: " + ", ".join(f"{t.split(')')[0]} {s:.0f}s" for t, s in SECTIONS) + f"; total {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
