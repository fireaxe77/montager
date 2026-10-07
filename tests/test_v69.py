"""V6.9: CS2 neighbour-clip pairing (generated clip lists, generated cached kills; no real clips, no renders) + the Valorant guard against
commit 031cb64.
   python test_v69.py          (Linux: python3 test_v69.py)
Only this version's checks + the Valorant guard; older tests are frozen and NOT run. Whole run < 60 s."""
import datetime
import hashlib
import importlib.util
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = __import__("_root").find_root(__file__)          # repo root (tests/_root.py); this file lives in tests/
sys.path.insert(0, str(HERE))
import montage as M                                                                           # noqa: E402

T_ALL = time.time()
REAL_VERIFY_STITCH = M.verify_stitch
FAILS = []
REAL_DATA = HERE / "montage_data"
BASE = datetime.datetime(2025, 2, 8, 19, 48, 57)


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def snapshot(d):
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(d).rglob("*")) if p.is_file()} \
        if Path(d).exists() else {}


def logged(fn, *a, **k):
    lines, real_out, real_lo = [], M.out, M.LOGONLY
    M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        res = fn(*a, **k)
    finally:
        M.out, M.LOGONLY = real_out, real_lo
    return res, lines


def cs2_name(off_s, suffix=""):
    t = BASE + datetime.timedelta(seconds=off_s)
    return f"Counter-strike 2 {t:%Y.%m.%d} - {t:%H.%M.%S}.15.DVR{suffix}.mp4"


class World:
    n = 0
    """Generated CS2 clips (empty files so file keys work), their clip records, cached kill entries and generated kills."""
    def __init__(self, tmp):
        World.n += 1
        self.dir = Path(tmp) / f"clips{World.n}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.recs, self.kills = [], {}
        self.store = M.KillStore()
        self.det = M.Detector("cs2")

    def add(self, name, dur, kills, scanned=True):
        p = self.dir / name
        p.write_bytes(b"x")
        rec = {"path": str(p), "game": "cs2", "w": 1920, "h": 1080, "dur": float(dur), "v_off": 0.0, "bars": False, "bar_sig": ""}
        self.recs.append(rec)
        self.kills[rec["path"]] = list(kills)
        if scanned:
            self.store.put(M.kills_key(rec, "cs2", self.det), {"ocr": [], "frames": 1, "game": "cs2", "v_off": 0.0})
        return rec


def fake_analyse(world):
    def f(rec, entry, cfg, game=None, build=False):
        return {"kills": [{"t": t, "victim": v} for t, v in world.kills.get(rec["path"], [])], "deaths": [], "revives": [], "vis": []}
    return f


def pool_item(rec, kills):
    return {"rec": rec, "kills": [{"t": t, "victim": v, "shot": False, "hs": False} for t, v in kills], "deaths": [], "revives": [], "vis": [],
            "rej": []}


def names(n, seed):
    r = random.Random(seed)
    out_, seen = [], set()
    while len(out_) < n:
        w = "".join(r.choice("abcdefghklmnpqrstuvwxyz") for _ in range(9))
        if w not in seen:
            seen.add(w)
            out_.append(w)
    return out_


def pk(p):
    return M._pkey(p)


def part_pairing(tmp):
    print("== pairing: lookup and qualification ==")
    cfg = M.load_config()
    w = World(tmp)
    M.analyse_clip_entry = fake_analyse(w)
    sel = lambda *recs: [r["path"] for r in recs]
    V = names(30, 3)
    FV = names(30, 77)

    # 1. a 1k at 17.0 s of an 18 s clip + a scanned neighbour starting 3 s after its end with 2 kills -> partner
    A = w.add(cs2_name(0), 18, [(17.0, V[0])])
    B = w.add(cs2_name(21), 15, [(0.5, V[0]), (2.0, V[1])])
    res, lines = logged(M.pairing_run, cfg, w.recs, sel(A))
    check(res is not None and [Path(p["path"]).name for p, _, _ in res["partners"]] == [Path(B["path"]).name], "1k at 17.0 s of 18 s: the scanned neighbour is added as partner")
    check(any(l.startswith(f"pair partner of {Path(A['path']).name}: {Path(B['path']).name} (gap 3.0 s)") for l in lines), "log: 'pair partner of <clip>: <partner> (gap 3.0 s)'")
    check(any(l.startswith("pairing: checked 1 clips, 1 partner(s) added, 0 skipped (0 not scanned / 0 used / 0 no kills / 0 no match") for l in lines)
          and any("gap <= 12 s" in l for l in lines), "log: summary line with the skipped breakdown and the 12 s window note")

    # 2. planner, merge case: the neighbour shows the 1k's victim again plus 2 more kills -> ONE 3k event in the 1k's slot (no stitch needed)
    M.verify_stitch = lambda spans, cut: (True, spans[1]["shift"], "stub: frames match")
    w.kills[B["path"]] = [(0.5, V[0]), (2.0, V[1]), (3.5, V[2])]
    pool = [pool_item(A, [(17.0, V[0])]), pool_item(B, w.kills[B["path"]])]
    single, _ = M.build_events(pool[:1], "cs2", cfg, random.Random(1))
    res, _ = logged(M.pairing_run, cfg, w.recs, sel(A))
    new = M.pairing_replace_events(res, pool, single, "cs2", cfg, 1)
    check(len(single) == 1 and single[0]["n"] == 1 and len(new) == 1 and new[0]["n"] == 3,
          "planner merge: the 1k and its neighbour become ONE 3k event in the 1k's slot (count unchanged)")
    plan = {"takes": [{"path": new[0]["path"], "srcs": [{"path": x["path"]} for x in new[0]["parts"]]}]}
    check(M.pairing_result_line(res, plan) == "pairing result: 1 pair(s) stitched, 0 rejected", "log after the planner: 1 pair stitched, 0 rejected")

    # 2b. real stitch: each clip shows kills the other does not -> two parts, verified by the (stubbed) frame match
    w2 = World(tmp)
    M.analyse_clip_entry = fake_analyse(w2)
    sa = w2.add(cs2_name(9000), 22, [(17.5, V[3]), (19.5, V[0])])
    sb = w2.add(cs2_name(9025), 15, [(0.5, V[0]), (2.0, V[1])])
    spool = [pool_item(sa, w2.kills[sa["path"]]), pool_item(sb, w2.kills[sb["path"]])]
    ssingle, _ = M.build_events(spool[:1], "cs2", cfg, random.Random(1))
    sres, _ = logged(M.pairing_run, cfg, w2.recs, sel(sa))
    snew = M.pairing_replace_events(sres, spool, ssingle, "cs2", cfg, 1)
    check(len(snew) == 1 and snew[0]["n"] == 3 and snew[0]["stitched"] and len(snew[0]["parts"]) == 2, "stitch accepted: one stitched 3k event with both clips as parts")
    splan = {"takes": [{"path": snew[0]["path"], "srcs": [{"path": x["path"]} for x in snew[0]["parts"]]}]}
    check(M.pairing_result_line(sres, splan) == "pairing result: 1 pair(s) stitched, 0 rejected", "result line: 1 pair stitched (the partner is in a take, so it is flagged used)")

    # 3. stitch rejected: the single-clip plan, partner not placed, nothing flagged used
    M.verify_stitch = lambda spans, cut: (False, spans[1]["shift"], "stub: no matching frame")
    new2 = M.pairing_replace_events(sres, spool, ssingle, "cs2", cfg, 1)
    check(new2 == ssingle and new2[0] is ssingle[0], "stitch rejected: the pick is exactly the single-clip event (partner dropped, not placed alone)")
    song = {"path": "x.mp3", "title": "x", "artist": "a"}
    an = M.default_song_map()
    full = M.load_config()
    fill = [w2.add(cs2_name(20000 + i * 1000), 45, [(20.0, FV[3 * i]), (21.2, FV[3 * i + 1]), (22.4, FV[3 * i + 2])]) for i in range(7)]
    fev, _ = M.build_events([pool_item(f, w2.kills[f["path"]]) for f in fill], "cs2", cfg, random.Random(2))
    p_a = M.plan_montage(full, "cs2", ssingle + fev, song, an, 5, "auto", "optimal", [], [])
    p_b = M.plan_montage(full, "cs2", new2 + fev, song, an, 5, "auto", "optimal", [], [])
    tk = lambda p: [(Path(t["path"]).name, [Path(x["path"]).name for x in t["srcs"]]) for t in p["takes"]]
    check(tk(p_a) == tk(p_b) and len(tk(p_b)) > 2 and any(n == Path(sa["path"]).name for n, _ in tk(p_b)) and Path(sb["path"]).name not in str(tk(p_b)),
          "the plan equals the single-clip plan; the partner is in no take")
    used_paths = {t["path"] for t in p_b["takes"]} | {x["path"] for t in p_b["takes"] for x in t.get("srcs", [])}
    check(sb["path"] not in used_paths and M.pairing_result_line(sres, p_b) == "pairing result: 0 pair(s) stitched, 1 rejected",
          "no partner would be flagged used (mark_used takes the take paths); log: 0 pair(s) stitched, 1 rejected")
    # rejected stitch where the planner's fallback would pick the partner (it has more of the kills): still the original event
    spool2 = [spool[0], pool_item(sb, [(0.5, V[0]), (2.0, V[1]), (3.5, V[4])])]
    new3 = M.pairing_replace_events(sres, spool2, ssingle, "cs2", cfg, 1)
    check(new3 == ssingle, "stitch rejected and the partner shows more kills: the partner is still not placed, the original event stays")

    # 4. skip cases
    def one(neigh_kwargs, label, expect_line=None, expect_partners=0, used_flag=False, scanned=True, name_off=21):
        w2 = World(tmp)
        M.analyse_clip_entry = fake_analyse(w2)
        a = w2.add(cs2_name(0), 18, [(17.0, V[0])])
        b = w2.add(neigh_kwargs.get("name", cs2_name(name_off)), 15, neigh_kwargs.get("kills", [(0.5, V[1])]), scanned=scanned)
        flags = Path(M.USED_FLAGS)
        flags.unlink(missing_ok=True)
        if used_flag:
            M.save_json(M.USED_FLAGS, {pk(b["path"]): "2025-02-09"})
        sel_before = [a["path"]]
        r, ls = logged(M.pairing_run, cfg, w2.recs, sel_before)
        flags.unlink(missing_ok=True)
        ok = r is not None and len(r["partners"]) == expect_partners and (expect_line is None or any(l.startswith(expect_line) for l in ls))
        check(ok and sel_before == [a["path"]], label)
        return r, ls
    one({}, "neighbour not scanned: skipped, 'neighbour not scanned: <clip>' logged, selection unchanged", "neighbour not scanned: ", scanned=False)
    one({}, "neighbour already used: skipped, 'neighbour already used: <clip>' logged", "neighbour already used: ", used_flag=True)
    one({"kills": []}, "neighbour with no kills of the player: skipped", "neighbour has no kills")
    one({}, "gap larger than the window (13 s): skipped", None, name_off=18 + 13)
    one({}, "gap exactly 12 s: still inside the window", None, expect_partners=1, name_off=18 + 12)
    one({"name": "weird clip no time in the name.mp4"}, "unparsable neighbour file name: skipped without an error", None)
    w3 = World(tmp)
    M.analyse_clip_entry = fake_analyse(w3)
    a3 = w3.add("clip without a time.mp4", 18, [(17.0, V[0])])
    r3, ls3 = logged(M.pairing_run, cfg, w3.recs, [a3["path"]])
    check(r3 is not None and not r3["partners"] and not any("skipped:" in l for l in ls3), "unparsable name of the SELECTED clip: skipped without an error")
    check(pair_names_share_base(), "'_1' / '_1_1' name variants share the base time")

    # 5. chains
    w4 = World(tmp)
    M.analyse_clip_entry = fake_analyse(w4)
    run = [w4.add(cs2_name(i * 20), 18, [(1.0, V[i]), (16.5, V[i + 8])]) for i in range(6)]          # 6 consecutive clips, 2 s gaps
    r, _ = logged(M.pairing_run, cfg, w4.recs, [run[1]["path"]])
    got = sorted(Path(p["path"]).name for p, _, _ in r["partners"])
    check(got == sorted(Path(x["path"]).name for x in (run[0], run[2], run[3])), "3-clip fight selected via the middle clip pulls in both sides (+1 hop more, 3 extra max)")
    r, _ = logged(M.pairing_run, cfg, w4.recs, [run[0]["path"]])
    check(sorted(Path(p["path"]).name for p, _, _ in r["partners"]) == sorted(Path(x["path"]).name for x in run[1:3]), "6-clip run, first clip selected: at most 2 hops (2 partners)")
    r, _ = logged(M.pairing_run, cfg, w4.recs, [run[2]["path"]])
    idx = {pk(x["path"]): i for i, x in enumerate(run)}
    left = [p for p, _, _ in r["partners"] if idx[pk(p["path"])] < 2]
    right = [p for p, _, _ in r["partners"] if idx[pk(p["path"])] > 2]
    check(len(left) <= 2 and len(right) <= 2 and len(r["partners"]) == 3, f"6-clip run, clip 3 selected: <= 2 hops each way and <= 3 extra clips ({len(left)} left, {len(right)} right)")
    r, _ = logged(M.pairing_run, cfg, w4.recs, [run[2]["path"], run[3]["path"]])
    ps = [pk(p["path"]) for p, _, _ in r["partners"]]
    check(len(ps) == len(set(ps)) and not set(ps) & {pk(run[2]["path"]), pk(run[3]["path"])}, "the same clip is never added twice and a selected clip is never a partner")

    # 6. kills in the middle only: no lookup
    w5 = World(tmp)
    M.analyse_clip_entry = fake_analyse(w5)
    m1 = w5.add(cs2_name(0), 18, [(8.0, V[0]), (9.0, V[1])])
    w5.add(cs2_name(20), 15, [(0.5, V[2])])
    r, _ = logged(M.pairing_run, cfg, w5.recs, [m1["path"]])
    check(r["lookups"] == 0 and not r["partners"], "kills in the middle only (none within 3.0 s of an edge): no lookup")
    w5.kills[m1["path"]] = [(3.5, V[0]), (9.0, V[1])]
    r, _ = logged(M.pairing_run, cfg, w5.recs, [m1["path"]])
    check(r["lookups"] == 0, "two kills, the first 3.5 s from the start (> 3.0 s): no lookup")
    w5.kills[m1["path"]] = [(3.5, V[0])]
    r, _ = logged(M.pairing_run, cfg, w5.recs, [m1["path"]])
    check(r["lookups"] == 1, "a 1k whose single kill is 3.5 s from the start (within 4 s): lookup")

    # 7. target length / count unchanged, other picks not displaced
    w6 = World(tmp)
    M.analyse_clip_entry = fake_analyse(w6)
    clips, items = [], []
    for i in range(8):
        r_ = w6.add(cs2_name(i * 600), 18, [(17.0 if i == 2 else 8.0, V[i])])
        clips.append(r_)
        items.append(pool_item(r_, w6.kills[r_["path"]]))
    n_ = w6.add(cs2_name(2 * 600 + 21), 15, [(0.5, V[2]), (2.0, V[20]), (3.5, V[21])])
    items.append(pool_item(n_, w6.kills[n_["path"]]))
    M.verify_stitch = lambda spans, cut: (True, spans[1]["shift"], "stub: frames match")
    base_ev, _ = M.build_events(items[:8], "cs2", cfg, random.Random(4))
    pick, _ = M.weekly_pick(base_ev, M.load_config(), 60, "auto", game="cs2")
    r, _ = logged(M.pairing_run, cfg, w6.recs, {e["path"] for e in pick})
    new = M.pairing_replace_events(r, items, pick, "cs2", cfg, 4)
    same = [i for i, (a, b) in enumerate(zip(pick, new)) if a is b]
    changed = [i for i in range(len(pick)) if i not in same]
    check(len(new) == len(pick) and len(changed) == 1 and new[changed[0]]["n"] == 3 and pick[changed[0]]["path"] == clips[2]["path"],
          f"pick of {len(pick)} events: same count, only the paired clip's slot changed (now a 3k), the other {len(same)} events untouched")


def pair_names_share_base():
    t = [M.pair_clip_start(f"Counter-strike 2 2025.02.08 - 19.48.57.15.DVR{s}.mp4") for s in ("", "_1", "_1_1")]
    r = M.pair_clip_start("Replay 2026-06-08 23-36-22.mov")
    return t[0] is not None and t[0] == t[1] == t[2] and r == datetime.datetime(2026, 6, 8, 23, 36, 22).timestamp() \
        and M.pair_clip_start("nothing.mp4") is None and M.pair_clip_start("Replay 2026-13-45 99-99-99.mov") is None


def part_guard_and_cap(tmp):
    print("== error handling, 2 s cap, Valorant ==")
    cfg = M.load_config()
    w = World(tmp)
    M.analyse_clip_entry = fake_analyse(w)
    V = names(10, 9)
    A = w.add(cs2_name(0), 18, [(17.0, V[0])])
    w.add(cs2_name(21), 15, [(0.5, V[1])])

    def boom():
        raise RuntimeError("boom")
    M.PAIR_TEST_HOOK[0] = boom
    r, ls = logged(M.pairing_run, cfg, w.recs, [A["path"]])
    check(r is None and ls == ["pairing skipped: RuntimeError: boom"], "an exception inside the step: one 'pairing skipped: <reason>' line, no result (original selection kept)")
    M.PAIR_TEST_HOOK[0] = lambda: time.sleep(3)
    t0 = time.time()
    r, ls = logged(M.pairing_run, cfg, w.recs, [A["path"]])
    dt = time.time() - t0
    check(r is None and len(ls) == 1 and ls[0].startswith("pairing skipped: timeout") and dt < 2.6, f"a 3 s sleep in the step hits the 2 s cap ({dt:.1f} s, '{ls[0] if ls else ''}')")
    M.PAIR_TEST_HOOK[0] = None
    r, ls = logged(M.pairing_run, cfg, w.recs, [])
    check(r is None and not ls, "no selected CS2 clips: the step is skipped completely (no log line)")
    # missing cache: the kill store directory does not exist for the clips
    M.analyse_clip_entry = lambda *a, **k: (_ for _ in ()).throw(ValueError("bad cache"))
    r, ls = logged(M.pairing_run, cfg, w.recs, [A["path"]])
    check(r is None and ls and ls[0].startswith("pairing skipped:"), "unreadable cached kills: 'pairing skipped' and the original selection")
    M.analyse_clip_entry = fake_analyse(w)

    # make_plan level (stubbed scan / pool / songs / planner): selection identical with an exception, Valorant never runs the step
    def harness(mod, game, items, paths):
        seen = {}
        stubs = dict(autodetect_dirs=lambda c: c, load_dets=lambda g=None: {game: object()}, scan_clips=lambda c: [dict(i["rec"], game=game) for i in items],
                     auto_scan_set=lambda c, g: [], run_scan=lambda *a, **k: None, hist_list=lambda *a: [],
                     game_pool=lambda c, g, ps=None: ([i for i in items if ps is None or i["rec"]["path"] in ps],
                                                      {"tagged": len(items), "scanned": len(items), "with_kills": len(items),
                                                       "audio": {"raw": 0, "no_shot": 0, "death_lock": 0, "kept": 0}}),
                     song_pool=lambda c: ([], [], ""), pick_song=lambda *a, **k: ({"path": "x"}, {}, 0, []),
                     weekly_song_fit=lambda s, a, i, r: (s, a, i, r), verify_cutlist=lambda p: [], fmt_plan=lambda *a: "")
        old = {k: getattr(mod, k) for k in stubs}
        old_pm = mod.plan_montage
        for k, v in stubs.items():
            setattr(mod, k, v)
        mod.plan_montage = lambda cfg_, g, evs, *a, **k: seen.setdefault("events", evs) and {"duration": 0, "song": {"section_s": 1e9, "path": "x"}, "takes": [], "notes": []}
        try:
            mod.make_plan(mod.load_config(), game, paths, seed=7)
        finally:
            for k, v in old.items():
                setattr(mod, k, v)
            mod.plan_montage = old_pm
        return seen.get("events", [])
    view = lambda evs: [(Path(e["path"]).name, e["n"], e["times"], e["victims"]) for e in evs]
    w7 = World(tmp)
    M.analyse_clip_entry = fake_analyse(w7)
    a7 = w7.add(cs2_name(0), 18, [(17.0, V[0])])
    b7 = w7.add(cs2_name(21), 15, [(0.5, V[0]), (2.0, V[1]), (3.5, V[2])])
    items7 = [pool_item(a7, [(17.0, V[0])]), pool_item(b7, [(0.5, V[0]), (2.0, V[1]), (3.5, V[2])])]
    M.verify_stitch = lambda spans, cut: (True, spans[1]["shift"], "stub")
    ev_pair, ls = logged(harness, M, "cs2", items7, [a7["path"]])
    check(len(ev_pair) == 1 and ev_pair[0]["n"] == 3 and any(l.startswith("pairing: checked 1 clips") for l in ls), "make_plan (ticked clip): the 1k becomes the stitched 3k, summary logged")
    M.PAIR_TEST_HOOK[0] = boom
    ev_err, ls = logged(harness, M, "cs2", items7, [a7["path"]])
    M.PAIR_TEST_HOOK[0] = None
    M.pairing_run, real_run = (lambda *a, **k: None), M.pairing_run
    ev_orig, _ = logged(harness, M, "cs2", items7, [a7["path"]])
    M.pairing_run = real_run
    check(view(ev_err) == view(ev_orig) and len(ev_err) == 1 and ev_err[0]["n"] == 1 and any(l.startswith("pairing skipped:") for l in ls),
          "make_plan with an exception in the step: the exact original selection / events + 'pairing skipped' line")

    # Valorant: the step does not run; selection and plan identical to commit 031cb64
    M.verify_stitch = REAL_VERIFY_STITCH
    B = load_baseline(tmp, "031cb64")
    if B is None:
        check(False, "git baseline 031cb64 not available (git fetch origin)")
        return
    rng = random.Random(21)
    vnames = names(300, 5)
    vdir = Path(tmp) / "vclips"
    vdir.mkdir()
    items = []
    for i in range(100):
        t0 = datetime.datetime(2026, 3, 1) + datetime.timedelta(minutes=17 * i)
        p = vdir / f"Replay {t0:%Y-%m-%d %H-%M-%S}.mov"
        p.write_bytes(b"x")
        ks = sorted(rng.sample(range(2, 40), rng.randint(1, 4)))
        items.append({"rec": {"path": str(p), "dur": 45.0, "w": 1920, "h": 1080, "v_off": 0.0, "game": "valorant", "bars": False, "bar_sig": ""},
                      "kills": [{"t": float(k), "victim": vnames[3 * i + j], "shot": False, "hs": bool(j % 2)} for j, k in enumerate(ks)],
                      "deaths": [], "revives": [], "vis": [], "rej": []})
    M.pairing_run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("pairing step ran for Valorant"))
    try:
        for mode, paths in (("auto", None), ("ticked", [i["rec"]["path"] for i in items[:40]])):
            evm, _ = logged(harness, M, "valorant", items, paths)
            evb, _ = logged(harness, B, "valorant", items, paths)
            check(len(evm) > 10 and view(evm) == view(evb), f"Valorant {mode}: {len(evm)} selected events identical to 031cb64 (step not run)")
            if view(evm) != view(evb):
                print("    M:", view(evm)[:3], len(evm), "\n    B:", view(evb)[:3], len(evb))
    finally:
        M.pairing_run = real_run
    cfgf = M.load_config()
    song = {"path": "x.mp3", "title": "x", "artist": "a"}
    (evs, _), _ = logged(M.build_events, items[:30], "valorant", cfgf, random.Random(3))
    (evsb, _), _ = logged(B.build_events, items[:30], "valorant", B.load_config(), random.Random(3))
    pm = M.plan_montage(cfgf, "valorant", evs, song, M.default_song_map(), 5, "auto", "optimal", [], [])
    pb = B.plan_montage(B.load_config(), "valorant", evsb, song, B.default_song_map(), 5, "auto", "optimal", [], [])
    tk = lambda p: [(Path(t["path"]).name, round(t["dur"], 3) if "dur" in t else None, [Path(x["path"]).name for x in t["srcs"]]) for t in p["takes"]]
    check(len(pm["takes"]) > 3 and tk(pm) == tk(pb) and round(pm["duration"], 3) == round(pb["duration"], 3),
          f"Valorant plan ({len(pm['takes'])} takes, {pm['duration']:.1f} s) identical to 031cb64")


def load_baseline(tmp, ref):
    r = subprocess.run(["git", "show", f"{ref}:montage.py"], cwd=str(HERE), capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    bdir = Path(tmp) / "base"
    bdir.mkdir(exist_ok=True)
    (bdir / "montage.py").write_bytes(r.stdout)
    data = Path(tmp) / "base_data"
    data.mkdir(exist_ok=True)
    for f in REAL_DATA.glob("detect_*.json"):
        (data / f.name).write_bytes(f.read_bytes())
    os.environ["MONTAGER_DATA"] = str(data)
    try:
        spec = importlib.util.spec_from_file_location("montage_base031", str(bdir / "montage.py"))
        B = importlib.util.module_from_spec(spec)
        sys.modules["montage_base031"] = B
        spec.loader.exec_module(B)
    finally:
        del os.environ["MONTAGER_DATA"]
    return B


def part_pairscan(tmp):
    print("== pairscan (read-only) ==")
    w = World(tmp)
    M.analyse_clip_entry = fake_analyse(w)
    V = names(20, 13)
    w.add(cs2_name(0), 18, [(17.0, V[0])])
    w.add(cs2_name(21), 15, [(0.5, V[0]), (2.0, V[1]), (3.5, V[2])])
    w.add(cs2_name(3000), 18, [(8.0, V[3])])
    w.add(cs2_name(3020), 15, [(7.0, V[4])])
    w.add(cs2_name(6000), 18, [(17.0, V[5])])
    w.add(cs2_name(6020), 15, [(0.5, V[6])], scanned=False)
    paths = [r["path"] for r in w.recs]
    clips_cache = {M.file_key(r["path"]): {k: v for k, v in r.items() if k != "path"} for r in w.recs}
    M.save_json(M.CLIPS_CACHE, clips_cache)
    M.save_json(M.USED_FLAGS, {pk(w.recs[4]["path"]): "2025-02-09"})
    out_dir = Path(tmp) / "app"
    out_dir.mkdir()
    saved = {k: getattr(M, k) for k in ("load_config", "clip_roots", "walk_files", "tag_game", "HERE")}
    M.load_config = lambda: {"output_root": str(tmp)}
    M.clip_roots = lambda c: [str(w.dir)]
    M.walk_files = lambda roots, exts, mn, c: list(paths)
    M.tag_game = lambda p, c: ("cs2", "test")
    M.HERE = out_dir
    before = snapshot(M.DATA)
    clips_before = {p: Path(p).read_bytes() for p in paths}
    try:
        _, lines = logged(lambda: M.cmd_pairscan(type("A", (), {"limit": 30})()))
    finally:
        for k, v in saved.items():
            setattr(M, k, v)
    after = snapshot(M.DATA)
    txt = (out_dir / "pairscan_cs2.txt").read_text(encoding="utf-8") if (out_dir / "pairscan_cs2.txt").exists() else ""
    rows = [l for l in txt.splitlines() if "  +  " in l]
    check(len(rows) == 3 and "qualifies" in rows[0] and "kills 1 + 3" in rows[0] and "no kill within the edge" in rows[1]
          and "not scanned" in rows[2] and "already used" in rows[2], f"pairscan lists the generated pairs sorted by combined kills with the reason ({len(rows)} rows)")
    check(before == after and all(Path(p).read_bytes() == b for p, b in clips_before.items()), "pairscan changed no cache / flag / clip file (byte-identical data folder)")
    check(not any("Counter" in str(p) and p.suffix == ".txt" for p in Path(tmp).rglob("*.txt")) and (out_dir / "pairscan_cs2.txt").exists(), "only pairscan_cs2.txt was written")
    M.USED_FLAGS.unlink(missing_ok=True)
    M.CLIPS_CACHE.unlink(missing_ok=True)


def main():
    real_before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t69_"))
    old = M.use_data_dir(tmp / "data")
    saved = {k: getattr(M, k) for k in ("analyse_clip_entry", "verify_stitch", "pairing_run")}
    try:
        part_pairing(tmp)
        part_guard_and_cap(tmp)
        part_pairscan(tmp)
    finally:
        for k, v in saved.items():
            setattr(M, k, v)
        M.PAIR_TEST_HOOK[0] = None
        M.restore_data_dir(old)
    print("== real montage_data ==")
    check(snapshot(REAL_DATA) == real_before, f"real montage_data byte-identical after the tests ({len(real_before)} files{'; folder absent' if not real_before else ''})")
    total = time.time() - T_ALL
    print(f"total test time {total:.1f} s" + ("" if total < 60 else "  (OVER the 60 s limit)"))
    if total >= 60:
        FAILS.append("over 60 s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
