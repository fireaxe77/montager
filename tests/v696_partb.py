"""V6.9.6 part B tests: CS2 pair-partner stitch ORDER (chronological by the recording time in the clip names) + the grouporder command.
Generated clip lists and kills (empty files), stubbed frame-match verification; no real clips."""
import itertools
import random
from pathlib import Path

from v696_common import M, check, section, logged, snapshot, REAL_OUT, REAL_LO, BASE_REF                # noqa: F401
import test_v69 as T9                                                                         # noqa: E402  (World / cs2_name / fake_analyse; its main() is not run)
import test_v693 as T                                                                         # noqa: E402

V = T9.names(12, 5)
# the detected kills of the three clips on the FIGHT timeline (clip starts 0 / 7 / 13 s, lengths 15.4 / 17.0 / 14.0 s); each clip detects what it detected,
# neighbours share one victim, so the planner has to stitch all three
DET = [[(3.0, V[0]), (6.0, V[1]), (9.5, V[2])], [(9.5, V[2]), (13.5, V[3])], [(13.5, V[3]), (18.0, V[4]), (22.0, V[5])]]
STARTS, DURS = (0, 7, 13), (15.4, 17.0, 14.0)


def trio(tmp, sfx=("", "", ""), starts=STARTS, det=DET, durs=DURS):
    w = T9.World(tmp)
    recs, kills = [], []
    for i in range(3):
        ks = [(round(t - starts[i], 2), v) for t, v in det[i]]
        recs.append(w.add(T9.cs2_name(starts[i], sfx[i]), durs[i], ks))
        kills.append(ks)
    return w, recs, kills


def names_of(ev):
    return [Path(p["path"]).name[-22:-12] for p in ev["parts"]]


def part_order(tmp):
    with section("8) pair partners: the stitched order is chronological (1-2-3) whatever the discovery order"):
        cfg = M.load_config()
        saved = (M.verify_stitch, M.analyse_clip_entry)
        M.verify_stitch = lambda spans, cut: (True, spans[1]["shift"], "stub: frames match")
        try:
            w, recs, kills = trio(tmp)
            M.analyse_clip_entry = T9.fake_analyse(w)
            want = [Path(r["path"]).name[-22:-12] for r in recs]
            pool = [T9.pool_item(recs[i], kills[i]) for i in range(3)]
            ok_all, seen = True, []
            for sel_i in range(3):                                    # pulled in via the first, the middle and the last clip
                res, lines = logged(M.pairing_run, cfg, w.recs, [recs[sel_i]["path"]])
                single, _ = M.build_events([pool[sel_i]], "cs2", cfg, random.Random(1))
                for order in itertools.permutations(range(3)):        # shuffled discovery order of the pool
                    pl = [pool[i] for i in order]
                    new = M.pairing_replace_events(res, pl, single, "cs2", cfg, 1)
                    e = new[0]
                    good = names_of(e) == want and e["times"] == sorted(e["times"]) and e["n"] == 6 and e["first"] == e["times"][0] and e["last"] == e["times"][-1]
                    ok_all &= good
                    seen.append(names_of(e))
            check(ok_all, f"3-clip fight pulled in via first / middle / last clip x 6 pool orders: always {want}; kill list, first / last kill follow ({len(seen)} runs)")
            check(res and [Path(p["path"]).name for p, _, _ in res["partners"]] == sorted(Path(p["path"]).name for p, _, _ in res["partners"]),
                  "pair_find returns the partners in chronological order, never in discovery order")
            # the take range: the stitched event covers all three clips in time order
            e = M.pairing_replace_events(res, pool, single, "cs2", cfg, 1)[0]
            st = [p["start"] for p in e["parts"]]
            check(st == sorted(st) and e["pre"] > 0 and e["post"] > 0, f"take range follows the final order (part starts {st}, run-up {e['pre']:.2f} s, tail {e['post']:.2f} s)")

            # DVR / DVR_1 / DVR_1_1: one base time, ordered by the frame match, never by file name or discovery order
            w2, r2, k2 = trio(tmp, sfx=("", "_1", "_1_1"), starts=(0, 0, 0), durs=(12.0, 14.0, 18.0),
                              det=[[(1.0, V[8]), (3.0, V[0]), (6.0, V[1])], [(1.0, V[0]), (4.0, V[1]), (7.0, V[2])], [(2.0, V[2]), (6.0, V[3])]])
            order_truth = [Path(r["path"]).name for r in r2]
            M.verify_stitch = lambda spans, cut: (lambda ok: (ok, spans[1]["shift"], "stub: frames match" if ok else "stub: no match"))(
                order_truth.index(Path(spans[0]["path"]).name) < order_truth.index(Path(spans[1]["path"]).name))
            for order in ((2, 0, 1), (1, 2, 0), (0, 1, 2)):
                evs, _ = M.build_events([T9.pool_item(r2[i], k2[i]) for i in order], "cs2", cfg, random.Random(1))
                e = max(evs, key=lambda x: x["n"])
                got = [Path(p["path"]).name for p in e["parts"]]
                check(e["stitched"] and len(got) == 3 and got == order_truth, f"DVR / DVR_1 / DVR_1_1 (pool order {order}): stitched order {[g[-12:] for g in got]} follows the frame-match verdict")
            # the offsets say B before A (equal start, B ends first) but the frame match says A before B: the swap is decided by the verification
            w3, r3, k3 = trio(tmp, sfx=("", "_1", ""), starts=(0, 0, 40), durs=(15.4, 12.0, 10.0),
                              det=[[(3.0, V[0]), (6.0, V[1]), (9.0, V[4])], [(1.0, V[7]), (3.0, V[0]), (6.0, V[1])], [(1.0, V[9])]])
            truth3 = [Path(r3[0]["path"]).name, Path(r3[1]["path"]).name]
            M.verify_stitch = lambda spans, cut: (lambda ok: (ok, spans[1]["shift"], "stub: match" if ok else "stub: no match"))(
                [Path(spans[0]["path"]).name, Path(spans[1]["path"]).name] == truth3)
            evs3, _ = M.build_events([T9.pool_item(r3[i], k3[i]) for i in (0, 1)], "cs2", cfg, random.Random(1))
            e3 = max(evs3, key=lambda x: x["n"])
            check(e3["stitched"] and [Path(p["path"]).name for p in e3["parts"]] == truth3 and "decided by the frame match" in e3["stitch_note"],
                  f"same base time, wrong first guess: the frame match swaps them ({e3['stitch_note'][:90]})")

            # a rejected stitch still falls back exactly as before: re-plan on the single clip, partner dropped
            M.verify_stitch = lambda spans, cut: (False, spans[1]["shift"], "stub: no clearly matching frame")
            res, _ = logged(M.pairing_run, cfg, w.recs, [recs[1]["path"]])
            single, _ = M.build_events([pool[1]], "cs2", cfg, random.Random(1))
            new = M.pairing_replace_events(res, pool, single, "cs2", cfg, 1)
            check(len(new) == 1 and new[0] is single[0] and not new[0]["stitched"], "stitch rejected by the frame match: the single clip stays, the partners are dropped (as before)")
            evs, _ = M.build_events(pool, "cs2", cfg, random.Random(1))
            check(all(not e["stitched"] and "stitch rejected" in e["stitch_note"] for e in evs if e["stitch_note"]) and len(evs) == 1, f"build_events falls back to one single clip ({evs[0]['stitch_note'][:70]})")

            # the cause: the order came ONLY from the victim-matched offsets. A wrong offset for the middle clip put it after the last one (1-3-2) and a weak
            # frame match (similar frames) did not object.
            DET2 = [[(3.0, V[0]), (6.0, V[1]), (9.5, V[2]), (13.5, V[3])], [(9.5, V[2]), (13.5, V[3]), (16.0, V[6])], [(13.5, V[3]), (18.0, V[4]), (22.0, V[5])]]
            w4, r4, k4 = trio(tmp, det=DET2)
            pool4 = [T9.pool_item(r4[i], k4[i]) for i in range(3)]
            M.verify_stitch = lambda spans, cut: (True, spans[1]["shift"], "stub: frames match")
            real_vo = M._victim_offset

            def wrong(ka, kb, rf=None):
                o = real_vo(ka, kb, rf)
                return None if o is None else (o + 8.0 if len(kb) == 3 and kb[0]["t"] == 2.5 else o)          # the middle clip lands 8 s too late (after the last clip)
            B = T.load_baseline(tmp, BASE_REF)
            M._victim_offset = wrong
            B._victim_offset = wrong
            B.verify_stitch = lambda spans, cut: (True, spans[1]["shift"], "stub: frames match")
            try:
                evs_new, notes = M.build_events(pool4, "cs2", cfg, random.Random(1))
                evs_old, _ = B.build_events([dict(p) for p in pool4], "cs2", B.load_config(), random.Random(1))
            finally:
                M._victim_offset = real_vo
            old_order = [Path(p["path"]).name[-22:-12] for p in max(evs_old, key=lambda e: e["n"])["parts"]] if evs_old else []
            en = max(evs_new, key=lambda e: e["n"])
            w4n = [Path(r["path"]).name[-22:-12] for r in r4]
            check(old_order == [w4n[0], w4n[2], w4n[1]], f"base commit with a wrong middle-clip offset: stitched order {old_order} (the 1-3-2 symptom)")
            check(not en["stitched"] and "disagree with the kill offsets" in en["stitch_note"], f"this version: recording times and offsets disagree -> no wrong stitch, single clip ({en['stitch_note'][:80]})")
        finally:
            M.verify_stitch, M.analyse_clip_entry = saved


def part_group(tmp):
    with section("8b) grouporder: group, start times, overlap / gap, order; read-only"):
        w, recs, kills = trio(tmp)
        for r in recs:
            r["w"], r["h"] = 1920, 1080
        M.analyse_clip_entry = T9.fake_analyse(w)
        paths = [r["path"] for r in recs]
        M.save_json(M.CLIPS_CACHE, {M.file_key(r["path"]): {k: v for k, v in r.items() if k != "path"} for r in recs})
        out_dir = Path(tmp) / "app2"
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
            _, lines = logged(lambda: M.cmd_grouporder(type("A", (), {"game": "cs2", "clip": Path(recs[1]["path"]).name})()))
        finally:
            for k, v in saved.items():
                setattr(M, k, v)
        txt = (out_dir / "grouporder.txt").read_text(encoding="utf-8") if (out_dir / "grouporder.txt").exists() else ""
        rows = [l for l in txt.splitlines() if l.startswith("  ") and ". Counter-strike" in l]
        check(len(rows) == 3 and [Path(r["path"]).name for r in recs] == [x.split(". ")[1].split("  starts")[0] for x in rows], f"grouporder lists the 3 clips of the group in time order ({len(rows)} rows)")
        check("overlaps the previous one by 8.4 s" in txt and "overlaps the previous one by 11.0 s" in txt and "<- the clip asked about" in rows[1] and "(+7.0 s)" in rows[1] and "(+13.0 s)" in rows[2],
              "start offsets and the overlaps (not gaps) of the neighbouring clips")
        check("order the planner will use: 1 -> 2 -> 3" in txt and "chronological by the recording time" in txt, "the order the planner will use and why")
        check(snapshot(M.DATA) == before and all(Path(p).read_bytes() == b for p, b in clips_before.items()) and (out_dir / "grouporder.txt").exists(), "read-only: data folder and clips byte-identical, only grouporder.txt written")
        M.CLIPS_CACHE.unlink(missing_ok=True)


def part_v69():
    with section("8c) the existing tests/test_v69.py (pairing) still ends with ALL OK"):
        import subprocess
        import sys
        import time
        from v696_common import ROOT
        f = ROOT / "tests" / "test_v69.py"
        f = f if f.exists() else ROOT / "test_v69.py"
        t0 = time.time()
        r = subprocess.run([sys.executable, str(f)], capture_output=True, text=True, cwd=str(ROOT), encoding="utf-8", errors="replace")
        lines = (r.stdout or "").strip().splitlines()
        check(r.returncode == 0 and lines and lines[-1].strip() == "ALL OK", f"{f.relative_to(ROOT)} ends with '{lines[-1].strip() if lines else r.stderr[-200:]}' ({time.time() - t0:.1f} s)")


def run(tmp):
    part_order(tmp)
    part_group(tmp)
    part_v69()
