"""V6.9.7 part A tests: clip time anchors, proof-based merging, kill ledger + safety net, ledger / timeanchor commands. Generated clips only (real small videos
whose frames depend on the absolute time); no renders."""
import datetime
import json
import os
import random
import re
import sys
import tempfile
import time
from pathlib import Path

from v697_common import *                                                                        # noqa: F401,F403
from v697_common import BASE_REF, STATE, base_module, led, states, distinct_names, M, T, R, check, section, logged, snapshot, REAL_DATA, ROOT, INCIDENT, build_incident, make_clip, view_events, harness, rec_of, pool_item, BASE_DT

def part_anchor(tmp):
    with section("A1) clip time anchors: START or END per naming scheme, modified-time cross-check"):
        d = Path(tmp) / "anc"
        d.mkdir()
        t = lambda *a: datetime.datetime(*a).timestamp()

        def mk(name, mtime):
            p = d / name
            p.write_bytes(b"x")
            os.utime(p, (mtime, mtime))
            return str(p)
        # OBS replay, second resolution: the name is the SAVE time (END); the modified time agrees
        T1 = t(2026, 9, 11, 17, 0, 37)
        a = M.clip_anchor(mk("Replay 2026-09-11 17-00-37.mov", T1), 40.0)
        check(a and a["side"] == "end" and a["verified"] and abs(a["end"] - T1) < 1e-6 and abs(a["start"] - (T1 - 40)) < 1e-6, f"'Replay 2026-09-11 17-00-37.mov' (40 s): END = the name time, start = name - 40 s ({a['how'] if a else None})")
        # ShadowPlay / Outplayed DVR: the name is the START (modified time = name + duration)
        T2 = t(2025, 10, 10, 22, 55, 31)            # the hundredths of the name are not parsed (V6.9: whole seconds)
        a = M.clip_anchor(mk("Valorant 2025.10.10 - 22.55.31.02.DVR.mp4", T2 + 35.0), 35.0)
        check(a and a["side"] == "start" and a["verified"] and abs(a["start"] - T2) < 1e-6 and abs(a["end"] - (T2 + 35)) < 1e-6, f"'Valorant 2025.10.10 - 22.55.31.02.DVR.mp4': START (the modified time = name + duration) ({a['how'] if a else None})")
        a = M.clip_anchor(mk("Counter-strike 2 2025.02.08 - 19.48.57.15.DVR.mp4", t(2025, 2, 8, 19, 48, 57) + 18.0), 18.0)
        check(a and a["side"] == "start" and a["verified"], "'Counter-strike 2 ... .DVR.mp4' (CS2): START, verified by the modified time")
        # the evidence beats the scheme default: a DVR name whose modified time = the name time is an END
        a = M.clip_anchor(mk("Valorant 2025.10.11 - 10.00.00.00.DVR.mp4", t(2025, 10, 11, 10, 0, 0)), 30.0)
        check(a and a["side"] == "end" and a["verified"], f"DVR name with modified time = name time: the evidence makes it an END, not the old START assumption ({a['how'] if a else None})")
        # a copied file (modified time fits neither): the scheme default, marked unverified
        a = M.clip_anchor(mk("Replay 2026-09-11 17-05-00.mov", t(2026, 9, 20, 1, 1, 1)), 40.0)
        check(a and a["side"] == "end" and not a["verified"] and a["provable"], "copied OBS file (modified time unrelated): scheme default END, marked unverified")
        # minute-only names: the modified time (second precision) is the clip time = END
        Tm = t(2026, 10, 3, 2, 45, 0) + 31.0
        a = M.clip_anchor(mk("VALORANT 2026-10-03 02-45.mov", Tm), 40.0)
        check(a and a["side"] == "end" and a["verified"] and abs(a["end"] - Tm) < 1e-6 and abs(a["start"] - (Tm - 40)) < 1e-6, "'VALORANT 2026-10-03 02-45.mov': minute-only -> END = the modified time (second precision)")
        a = M.clip_anchor(mk("VALORANT 2026-10-03 02-50.mov", t(2026, 10, 3, 9, 9, 9)), 40.0)
        check(a and not a["provable"], "minute-only name whose modified time is outside that minute: not provable (never guessed)")
        # '(2)': separate saves, ordered by the modified time, not by the name
        p1 = mk("VALORANT 2026-10-07 03-40 (2).mov", t(2026, 10, 7, 3, 40, 12))
        p2 = mk("VALORANT 2026-10-07 03-40.mov", t(2026, 10, 7, 3, 40, 51))
        a1, a2 = M.clip_anchor(p1, 40.0), M.clip_anchor(p2, 40.0)
        check(a1 and a2 and a1["provable"] and a2["provable"] and a1["start"] < a2["start"] and sorted([p1, p2], key=lambda p: M.clip_anchor(p, 40.0)["start"]) == [p1, p2]
              and M.name_time_info(p1)["seq"] == 2, "'(2)' suffix: ordered by the modified time (the '(2)' file saved first comes first), not by the name")
        a = M.clip_anchor(mk("VALORANT 2026-10-07 03-40-12.mov", t(2026, 10, 7, 3, 40, 12)), 40.0)
        check(a and a["side"] == "end" and a["verified"] and a["res"] == "sec", "'VALORANT 2026-10-07 03-40-12.mov' (seconds): END, verified")
        # unparsable names are skipped without an error
        check(M.clip_anchor(mk("clip final.mp4", 1.0), 40.0) is None and M.name_time_info("Replay 2026-13-45 99-99-99.mov") is None
              and M.clip_anchor(mk("Replay 2026-09-11 17-00-37 b.mov", T1), None) is None, "unparsable names / no duration: None, never an error, never guessed")
        # the CS2 time index: START clips keep the V6.9 values; an OBS replay clip is anchored at its END (old index: start = name time)
        B = base_module(tmp)
        r1 = dict(rec_of(mk("Replay 2026-06-08 23-36-22.mov", t(2026, 6, 8, 23, 36, 22)), 40.0, "cs2"), error=None)
        r2 = dict(rec_of(mk("Replay 2026-06-08 23-37-10.mov", t(2026, 6, 8, 23, 37, 10)), 20.0, "cs2"), error=None)
        r1["w"] = r2["w"] = 1920
        new, _ = M.pair_time_index([r1, r2])
        old, _ = B.pair_time_index([r1, r2])
        gap_new, gap_old = new[1][0] - new[0][2], old[1][0] - old[0][2]
        true_gap = (t(2026, 6, 8, 23, 37, 10) - 20) - t(2026, 6, 8, 23, 36, 22)          # END names: B started 20 s before its name time, A ended at its name time
        check(abs(gap_new - true_gap) < 1e-6 and abs(gap_old - true_gap) > 1.0,
              f"CS2 time index with two OBS replay clips of different length: gap {gap_new:.1f} s now (true {true_gap:.1f} s); the old START-assumption index said {gap_old:.1f} s (it was wrong)")
        dvr = [dict(rec_of(mk(f"Counter-strike 2 2025.02.08 - 19.48.{s}.15.DVR.mp4", t(2025, 2, 8, 19, 48, int(s)) + dd), dd, "cs2"), error=None, w=1920) for s, dd in (("57", 18.0), ("59", 15.0))]
        check([(round(x[0], 3), round(x[2], 3)) for x in M.pair_time_index(dvr)[0]] == [(round(x[0], 3), round(x[2], 3)) for x in B.pair_time_index(dvr)[0]],
              "CS2 DVR clips (START names): the time index is byte-identical to the old one")
        M.use_data_dir(Path(tmp) / "ancdata")
        r, lines = logged(M.cmd_timeanchor, type("A", (), {})())
        STATE["ta"] = lines


def part_proof(tmp):
    with section("A2) proof-based merging: overlap + frame match + kill times; names alone / time alone / chains never merge"):
        cfg = M.load_config()
        d = Path(tmp) / "proof"
        d.mkdir()
        # a) true overlap with matching frames: merged, proof logged
        ca = make_clip(d / "a.mov", 0, 40)
        cb = make_clip(d / "b.mov", 30, 40)
        for p, e in ((ca, 40.0), (cb, 70.0)):
            os.utime(p, (BASE_DT.timestamp() + e, BASE_DT.timestamp() + e))
        nm = lambda p: Path(p).name
        pa = pool_item(rec_of(ca), [(26.0, "zephyr"), (33.0, "kuwax"), (38.0, "mitski")])
        pb = pool_item(rec_of(cb), [(3.0, "kuwax"), (8.0, "mitski"), (14.0, "pandemic")])
        for it, n in ((pa, "VALORANT 2026-10-07 03-40-40.mov"), (pb, "VALORANT 2026-10-07 03-41-10.mov")):
            newp = d / n
            Path(it["rec"]["path"]).rename(newp)
            it["rec"]["path"] = str(newp)
            os.utime(newp, (BASE_DT.timestamp() + (40 if n.endswith("40.mov") else 70),) * 2)
        (evs, notes), lines = logged(M.build_events, [pa, pb], "valorant", cfg, random.Random(1))
        l = led()
        merged = [r for r in l.rows if r["state"] is None and r["merged"]]
        check(len(evs) == 1 and evs[0]["n"] == 4 and evs[0]["stitched"] and len(merged) == 2, f"true overlap + matching frames: ONE stitched 4-kill event, the two boundary duplicates are merged ({view_events(evs)})")
        pr = [p for p in l.proofs if p["proven"]]
        check(pr and pr[0]["offset"] == 30.0 and pr[0]["score"] is not None and pr[0]["score"] < 4.0, f"the proof is logged with pair, offset and match score ({pr[0] if pr else None})")
        # b) different rounds: identical victim names, time ranges overlap and agree with the kill times, but the footage is NOT the same
        cx = make_clip(d / "x.mov", 0, 40, seed=1)
        cy = make_clip(d / "y.mov", 30, 40, seed=2)                    # other rounds: other frames
        px = pool_item(rec_of(cx), [(33.0, "kuwax")])
        py = pool_item(rec_of(cy), [(3.0, "kuwax"), (9.0, "lorreth")])
        for it, n, e in ((px, "VALORANT 2026-10-07 03-50-40.mov", 40), (py, "VALORANT 2026-10-07 03-51-10.mov", 70)):
            newp = d / n
            Path(it["rec"]["path"]).rename(newp)
            it["rec"]["path"] = str(newp)
            os.utime(newp, (BASE_DT.timestamp() + 600 + e,) * 2)
        (evs, notes), lines = logged(M.build_events, [px, py], "valorant", cfg, random.Random(1))
        l = led()
        why = [p["why"] for p in l.proofs if not p["proven"]]
        check(len(evs) == 2 and not any(e["stitched"] for e in evs) and not any(r["merged"] for r in l.rows) and why and "frames do not match" in why[0],
              f"same victim, overlapping clip times, DIFFERENT frames: not merged, both kills stay ({view_events(evs)}; {why[:1]})")
        # c) names only: same victims, the clips are far apart in time: no frame matching is even started; time only: overlapping clips, no shared victim
        calls = []
        real_vs = M.verify_stitch
        M.verify_stitch = lambda spans, cut: calls.append(1) or real_vs(spans, cut)
        try:
            pn1 = pool_item(rec_of(str(d / "VALORANT 2026-10-07 03-50-40.mov")), [(33.0, "kuwax")])
            pn2 = pool_item(rec_of(str(d / "VALORANT 2026-10-07 03-51-10.mov")), [(3.0, "kuwax")])
            pn2["rec"]["path"] = str(d / "VALORANT 2026-10-07 04-30-00.mov")
            Path(pn2["rec"]["path"]).write_bytes(b"x")
            os.utime(pn2["rec"]["path"], (BASE_DT.timestamp() + 3000,) * 2)
            (evs, _), _ = logged(M.build_events, [pn1, pn2], "valorant", cfg, random.Random(1))
            check(len(evs) == 2 and not calls and not any(r["merged"] for r in led().rows), "names only (same victim, 50 min apart): never merged, no frame matching started")
            po1 = pool_item(rec_of(str(d / "VALORANT 2026-10-07 03-50-40.mov")), [(33.0, "kuwax")])
            po2 = pool_item(rec_of(str(d / "VALORANT 2026-10-07 03-51-10.mov")), [(3.0, "zephyr")])
            (evs, _), _ = logged(M.build_events, [po1, po2], "valorant", cfg, random.Random(1))
            check(len(evs) == 2 and not calls and not any(r["merged"] for r in led().rows), "time only (overlapping clips, different victims): never merged, no frame matching started")
        finally:
            M.verify_stitch = real_vs
        # d) a 3-link chain by names / times: A-B and B-C look linked, the frames do not match: nothing merges, no transitive link
        cc = [make_clip(d / f"c{i}.mov", 30 * i, 40, seed=10 + i) for i in range(3)]
        items = []
        for i, p in enumerate(cc):
            n = d / f"VALORANT 2026-10-07 04-{10 + i}-{(30 * i + 40) % 60:02d}.mov"
            Path(p).rename(n)
            os.utime(n, (BASE_DT.timestamp() + 1000 + 30 * i + 40,) * 2)
            items.append(pool_item(rec_of(str(n)), [(33.0 if i == 0 else 3.0, "kuwax"), (36.0 if i < 2 else 9.0, "mitski")]))
        (evs, _), _ = logged(M.build_events, items, "valorant", cfg, random.Random(1))
        check(len(evs) == 3 and not any(e["stitched"] for e in evs) and not any(r["merged"] for r in led().rows), f"3-link chain by names and times (frames differ): nothing merges ({len(evs)} events)")
        # e) a frame-match timeout / error: 'not proven', no crash, within the cap
        M.PROOF_TEST_HOOK[0] = lambda: time.sleep(30)
        old_cap, M.PROOF_CAP_S = M.PROOF_CAP_S, 1.0
        t0 = time.time()
        try:
            (evs, _), lines = logged(M.build_events, [pa, pb], "valorant", cfg, random.Random(1))
        finally:
            M.PROOF_TEST_HOOK[0], M.PROOF_CAP_S = None, old_cap
        dt = time.time() - t0
        p_ = [p for p in led().proofs]
        check(len(evs) == 2 and not any(e["stitched"] for e in evs) and dt < 4 and p_ and not p_[0]["proven"] and "cap" in p_[0]["why"], f"frame-match timeout: 'not proven', the events stay separate, no crash ({dt:.1f} s, {p_[0]['why'] if p_ else ''})")
        M.PROOF_TEST_HOOK[0] = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            (evs, _), _ = logged(M.build_events, [pa, pb], "valorant", cfg, random.Random(1))
        finally:
            M.PROOF_TEST_HOOK[0] = None
        check(len(evs) == 2 and not any(e["stitched"] for e in evs), "an error inside the proof: 'not proven', the events stay separate")


def part_cap(tmp):
    with section("A2b) group cap: a chain of 6 proven-adjacent clips splits into groups of at most 4"):
        cfg = dict(M.load_config())
        cfg["gap_s"] = dict(cfg["gap_s"], valorant=40.0)                 # the whole chain is one fight (no cluster split) so only the cap can split it
        d = Path(tmp) / "cap"
        d.mkdir()
        items = []
        kills = {0: [(35.0, "k0")], 1: [(5.0, "k0"), (35.0, "k1")], 2: [(5.0, "k1"), (35.0, "k2")], 3: [(5.0, "k2"), (35.0, "k3")], 4: [(5.0, "k3"), (35.0, "k4")], 5: [(5.0, "k4"), (20.0, "k5")]}
        for i in range(6):
            p = d / f"VALORANT 2026-10-07 05-{(30 * i + 40) // 60:02d}-{(30 * i + 40) % 60:02d}.mov"
            make_clip(p, 30 * i, 40, mtime=BASE_DT.timestamp() + 7200 + 30 * i + 40)
            items.append(pool_item(rec_of(str(p)), kills[i]))
        (evs, notes), lines = logged(M.build_events, items, "valorant", cfg, random.Random(1))
        sizes = [len(e["parts"]) for e in evs]
        l = led()
        check(evs and max(sizes) <= 4 and len(evs) == 2, f"6 proven-adjacent clips: groups/events of {sizes} clips (max 4)")
        check(any("fight group limit" in n for n in notes) and any("fight group limit" in x for x in l.splits), "the split is logged ('fight group limit ... new group')")
        dup = [r for r in l.rows if r["merged"]]
        check(len(dup) == 5, f"each boundary kill is merged away exactly once, also across the split ({len(dup)} duplicates merged)")
        names = [v for e in evs for v in e["victims"]]
        check(sorted(names) == sorted({"k0", "k1", "k2", "k3", "k4", "k5"}) and len(names) == 6, f"every distinct kill is in exactly one event ({sorted(names)})")


def part_ledger(tmp):
    with section("A3-A5) kill ledger, safety net, loss injection, log lines, ledger command"):
        cfg = M.load_config()
        d = Path(tmp) / "inc"
        items, names = build_incident(d)
        pool = [i for i, _ in items]
        paths = [i["rec"]["path"] for i in pool]
        STATE["inc"] = (items, names, pool, paths)
        # --- the incident
        t0 = time.time()
        plan, lines = logged(harness, M, "valorant", pool, paths)
        l = led()
        ev = [(Path(t["path"]).name, len(t["kills"])) for t in plan["takes"]]
        check(sorted(n for _, n in ev) == [1, 2, 4, 5], f"7 incident clips (minute-only OBS names, two '(2)' files, recurring enemy names): the plan has the 1K, 2K, 4K and the 5-kill Ace as separate takes {ev}")
        ace = max(plan["takes"], key=lambda t: len(t["kills"]))
        k4 = [t for t in plan["takes"] if len(t["kills"]) == 4]
        check(len(ace["srcs"]) == 2 and len(k4) == 1 and len(k4[0]["srcs"]) == 2, "the Ace and the 4K are each ONE stitched take of two clips (the halves were proven)")
        c = states(l)
        check(c.get("PLACED") == 12 and c.get("MERGED_DUP") == 2 and not c.get("LOST") and len(l.rows) == 14, f"ledger: 14 usable rows -> {c} (12 placed, the two boundary duplicates merged with proof, 0 LOST)")
        s_ = [x for x in lines if x.startswith("kill ledger:")]
        check(s_ and re.fullmatch(r"kill ledger: 14 usable, 12 placed, 2 merged as proven duplicates, 0 ranked out, 0 unusable, 0 lost, 0 released by safety net", s_[0]), f"summary line: {s_[0] if s_ else None}")
        md = [x for x in lines if "merged duplicate:" in x]
        check(len(md) == 2 and all("proof:" in x and "offset" in x and "frame match" in x for x in md) and any("mitski" in x for x in md), "one line per MERGED_DUP with its proof (pair, offset, frame match)")
        mit = [r for r in l.rows if r["victim"] == "mitski" and r["merged"]]
        check(any(Path(r["path"]).name == "VALORANT 2026-10-07 03-42.mov" for r in mit), "the 'mitski' boundary duplicate (second half of the 4K) is removed with proof")
        check(len({Path(r["path"]).name for r in l.rows if r["victim"] == "kuwax"}) == 3 and all(e["n"] in (1, 2, 4, 5) for e in M.LAST_LEDGER[0].final_events), "the same enemy names in different rounds are not merged (kuwax in 3 clips, 3 events)")
        # the base commit loses events on the same data (the incident), this version does not
        B = base_module(tmp)
        (evb, _), _ = logged(B.build_events, [dict(i) for i in pool], "valorant", B.load_config(), random.Random(3))
        (evn, _), _ = logged(M.build_events, [dict(i) for i in pool], "valorant", cfg, random.Random(3))
        check(sum(e["n"] for e in evn) == 12 and sum(e["n"] for e in evb) < 12, f"base commit on the same 6 clips: {sum(e['n'] for e in evb)} kills reach events ({len(evb)} events); this version: {sum(e['n'] for e in evn)} ({len(evn)})")
        # --- rejected stitch: members released as independent events, nothing lost
        cnt = {}
        real_vs = M.verify_stitch

        def flaky(spans, cut):                                       # the proof's frame match passes, the stitch's second verification of the same pair does not
            k = (Path(spans[0]["path"]).name, Path(spans[1]["path"]).name)
            cnt[k] = cnt.get(k, 0) + 1
            return real_vs(spans, cut) if cnt[k] == 1 else (False, spans[1]["shift"], "stub: no clearly matching frame")
        M.verify_stitch = flaky
        try:
            (evs, notes), lines = logged(M.build_events, [dict(i) for i in pool], "valorant", cfg, random.Random(3))
        finally:
            M.verify_stitch = real_vs
        l = led()
        rel = [x for x in lines if x.startswith("safety net: released")]
        check(len(rel) >= 1 and all("stitch was rejected" in x for x in rel), f"rejected stitch: the kills it would have dropped are released as independent events ({len(rel)} line(s))")
        l2 = M.ledger_finalize(l, evs, evs, {"takes": [{"path": e["path"], "kills": e["times"]} for e in evs], "fit": {"skipped": []}})
        check(sum(e["n"] for e in evs) == 12 and not [r for r in l2.rows if r["state"] == "LOST"] and sum(1 for r in l2.rows if r["released"]) >= 1, f"rejected stitch: all 12 distinct kills still reach events ({sum(e['n'] for e in evs)}), 0 LOST, released rows marked")
        # --- injected loss: an event dropped in a stage -> the safety net re-queues exactly its rows, logs it, the plan contains it
        def drop_one(evs_, l_):
            i = next(i for i, e in enumerate(evs_) if e["n"] == 2)
            evs_.pop(i)
        M.LEDGER_TEST_HOOK[0] = drop_one
        try:
            plan2, lines2 = logged(harness, M, "valorant", [dict(i) for i in pool], paths)
        finally:
            M.LEDGER_TEST_HOOK[0] = None
        l = led()
        rel = [x for x in lines2 if x.startswith("safety net: released 1 event(s):") and "pandemic" in x or "zephyr" in x]
        check(len(plan2["takes"]) == 4 and any(len(t["kills"]) == 2 for t in plan2["takes"]) and rel, f"injected loss of the 2K: re-queued once, logged ('{rel[0][:150] if rel else None}'), the plan still has all 4 takes")
        sl = [x for x in lines2 if x.startswith("kill ledger:")]
        check(sl and "0 lost, 2 released by safety net" in sl[0], f"ledger after the retry: {sl[0] if sl else None}")
        # --- the retry fails too: loud warning, the run completes
        real_me = M.make_event
        calls = {"n": 0}
        armed = {"on": False}

        def me(cl, parts, *a, **k):
            if armed["on"] and len(parts) == 1 and all(x["victim"] in ("pandemic", "zephyr") for x in cl) and len(cl) == 2:
                return None
            return real_me(cl, parts, *a, **k)

        def arm(evs_, l_):
            armed["on"] = True
            drop_one(evs_, l_)
        M.make_event, M.LEDGER_TEST_HOOK[0] = me, arm
        try:
            plan3, lines3 = logged(harness, M, "valorant", [dict(i) for i in pool], paths)
        finally:
            M.make_event, M.LEDGER_TEST_HOOK[0] = real_me, None
        warn = [x for x in lines3 if "KILL LEDGER WARNING" in x]
        check(plan3 and len(plan3["takes"]) == 3 and warn and any("pandemic" in x for x in lines3 if x.startswith("!!!")) and any("2 lost" in x for x in lines3 if x.startswith("kill ledger:")),
              f"retry fails too: the run completes (3 takes) and prints a loud warning with the rows ({warn[:1]})")
        # --- nothing lost: the safety net never runs
        plan4, lines4 = logged(harness, M, "valorant", [dict(i) for i in pool], paths)
        check(not [x for x in lines4 if x.startswith("safety net")] and len(plan4["takes"]) == 4, f"nothing lost: no safety-net line, the run is untouched ({len(plan4['takes'])} takes)")
        # --- ranked out / unusable states
        l = led()
        a_ = M.ledger_finalize(l, l.final_events[:2], l.final_events[:2], {"takes": [{"path": e["path"], "kills": e["times"]} for e in l.final_events[:1]], "fit": {"skipped": []}})
        c = states(a_)
        check(c.get("RANKED_OUT") and c.get("PLACED") and not c.get("LOST"), f"states RANKED_OUT / PLACED are assigned from the picked and planned events ({c})")


def part_commands(tmp):
    with section("A5b) python montage.py ledger / timeanchor: read-only"):
        data = Path(tmp) / "cmd_data"
        old = M.use_data_dir(data)
        keep = {n: ((ROOT / n).read_bytes() if (ROOT / n).exists() else None) for n in ("ledger.txt", "timeanchor.txt")}      # your own generated files stay as they were
        try:
            items, names, pool, paths = STATE["inc"]
            logged(harness, M, "valorant", [dict(i) for i in pool], paths)
            before = snapshot(data)
            check("ledger_last.json" in before, "a run saves its ledger to montage_data\\ledger_last.json")
            env = dict(os.environ, MONTAGER_DATA=str(data))
            r = R.run([sys.executable, "-W", "ignore", "montage.py", "ledger"], text=True, cwd=ROOT, env=env, timeout=120)
            ok, why = R.require(r, "python montage.py ledger")
            check(ok and "kill ledger: 14 usable" in r.stdout and "MERGED_DUP" in r.stdout and "PLACED" in r.stdout, f"python montage.py ledger reprints the last run's ledger {why}")
            check(snapshot(data) == before, "ledger: the data folder is byte-identical afterwards (no cache, flag or config changed)")
            check((ROOT / "ledger.txt").exists() and "kill ledger: 14 usable" in (ROOT / "ledger.txt").read_text(encoding="utf-8"), "ledger.txt written next to montage.py")
            r = R.run([sys.executable, "-W", "ignore", "montage.py", "timeanchor"], text=True, cwd=ROOT, env=env, timeout=120)
            check(r.returncode == 0 and "timeanchor:" in r.stdout and snapshot(data) == before, "timeanchor: runs read-only (data folder byte-identical)")
            gi = (ROOT / ".gitignore").read_text()
            check("ledger.txt" in gi and "timeanchor.txt" in gi, ".gitignore lists ledger.txt and timeanchor.txt")
        finally:
            M.restore_data_dir(old)
            for n, b in keep.items():
                if b is None:
                    (ROOT / n).unlink(missing_ok=True)
                else:
                    (ROOT / n).write_bytes(b)


def part_guard(tmp):
    with section("A7) nothing lost, nothing flagged: kills, events, plans and render commands identical to the base commit (100 Valorant + 100 CS2 clips)"):
        B = base_module(tmp)
        if B is None:
            check(False, f"base commit {BASE_REF} not available")
            return
        view = lambda mod, e, g: json.dumps(mod.analyse_entry(e, {}, g), sort_keys=True, default=str)
        evview = lambda evs: json.dumps([{k: v for k, v in e.items() if k not in ("rec",)} for e in evs], sort_keys=True, default=str)
        vdir = Path(tmp) / "guard"
        vdir.mkdir()
        vn = distinct_names(500)
        for game in ("valorant", "cs2"):
            ents = T.gen_entries(100, game)
            nd = sum(view(M, e, game) != view(B, e, game) for e in ents)
            check(nd == 0, f"{game}: kills of 100 generated clips identical to the base ({nd} differences)")
            rng = random.Random(21 if game == "valorant" else 22)
            items = []
            for i in range(100):
                p = vdir / (f"Replay 2026-03-01 {i // 4:02d}-{(i % 4) * 14 + 2:02d}-00.mov" if game == "valorant" else f"Counter-strike 2 2025.02.08 - 19.{i // 60 + 10}.{i % 60:02d}.15.DVR.mp4")
                p.write_bytes(b"x")
                ks = sorted(rng.sample(range(2, 40), rng.randint(1, 4)))
                items.append(pool_item(rec_of(str(p), 45.0, game), [(float(k), vn[4 * i + j]) for j, k in enumerate(ks)]))        # one victim name per kill: nothing links
            cfg = M.load_config()
            logged_ev = lambda mod, its, c: logged(mod.build_events, [dict(x) for x in its], game, c, random.Random(3))[0]
            evm, evb = logged_ev(M, items, cfg), logged_ev(B, items, B.load_config())
            check(evview(evm[0]) == evview(evb[0]) and len(evm[0]) > 10, f"{game}: events identical to the base ({len(evm[0])} events, every field)")
            lost = [r for r in led().rows if r["state"] == "LOST"]
            check(not [x for x in logged(M.build_events, [dict(x) for x in items], game, cfg, random.Random(3))[1] if x.startswith("safety net")], f"{game}: nothing lost -> no safety-net line")
            song = {"path": "x.mp3", "title": "x", "artist": "a"}
            pm = M.plan_montage(cfg, game, evm[0], song, M.default_song_map(), 5, "auto", "optimal", [], [])
            pb = B.plan_montage(B.load_config(), game, evb[0], song, B.default_song_map(), 5, "auto", "optimal", [], [])
            tk = lambda p: json.dumps([(Path(t["path"]).name, t["segs"], t["kills_out"], t["kills"]) for t in p["takes"]], default=str)
            check(len(pm["takes"]) > 3 and tk(pm) == tk(pb) and round(pm["duration"], 3) == round(pb["duration"], 3), f"{game}: plan ({len(pm['takes'])} takes) identical to the base")
            try:
                fm, fb = M.build_filter(pm, {}, False, M.FX_ALL), B.build_filter(pb, {}, False, B.FX_ALL)
                check(fm == fb, f"{game}: render command (inputs + filter graph) identical to the base")
            except Exception as ex:
                check(False, f"{game}: render command comparison failed: {type(ex).__name__}: {ex}")


def part_real(tmp):
    with section("A6) the real 7-clip recording (only if its cached data exists on this machine)"):
        clips = {}
        try:
            clips = json.loads((REAL_DATA / "clips_cache.json").read_text(encoding="utf-8")) if (REAL_DATA / "clips_cache.json").exists() else {}
        except Exception:
            clips = {}
        inc = [(k.rsplit("|", 2)[0], v) for k, v in clips.items() if re.search(r"VALORANT 2026-10-0[67] 03-4\d", k)]
        if not inc:
            print("  skip  real montage_data / the 7 incident clips (VALORANT 2026-10-07 03-4x) not found on this machine - only this check is skipped")
            return
        check(False, "real incident clips found but the real-data regression runner is not implemented for this layout")


ORDER = ["part_anchor", "part_proof", "part_cap", "part_ledger", "part_commands", "part_guard", "part_real"]
