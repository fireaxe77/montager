"""V6.9.7.1 tests (small, fast): save-time linking, fight split rule, utility twin row, interpolation tolerance, guard; the acceptance runs on the REAL clips
in E:\\Movies with a COPY of montage_data (the real data is never written; skipping is a failure). Ends with ALL OK only if every check ran and passed.
Run from the repo root or tests/:  python tests\\test_v6971.py   (Windows PC with the real clips)"""
import json
import os
import random
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("V697_BASE", "8dd1c5c")                       # the V6.9.7 commit: the guard compares against it
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v697_common import M, check, section, snapshot, REAL_DATA, FAILS, SECTIONS, base_module, rec_of, pool_item, distinct_names      # noqa: E402

CLIPS = Path(r"E:\Movies\VALORANT\Clips")
CS2_DIR = Path(r"E:\Movies\LEGACY\Counter-strike 2")
VAL = [f"VALORANT 2026-10-07 {n}.mov" for n in ("03-19", "03-21", "03-31-12", "03-31-20", "03-35-20", "03-40-15", "03-40-20")]
CS2 = [f"Counter-strike 2 2025.02.04 - 09.46.{n}.DVR.mp4" for n in ("13.09", "20.10", "26.11")]
T_ALL = time.time()


def norm(s):
    return M._alnum(str(s).lower())


def use_data(d):
    """use_data_dir plus MATCH_CACHE: montage.py defines it outside DATA_GLOBALS, so use_data_dir leaves it pointing at the REAL montage_data
    (song_pool rewrites match_cache.json there when the CSV / MP3 folder signature changed). Returns the restore closure."""
    old = M.use_data_dir(d)
    old_mc, M.MATCH_CACHE = M.MATCH_CACHE, Path(d) / "match_cache.json"

    def restore():
        M.restore_data_dir(old)
        M.MATCH_CACHE = old_mc
    stray = [k for k, v in vars(M).items() if isinstance(v, Path) and str(v).lower().startswith(str(REAL_DATA).lower())]
    check(not stray, f"every data path of montage.py points at the copy, none at the real montage_data ({stray})")
    return restore


def real_copy(tmp):
    """A copy of the real montage_data (no logs / plans) the tests work on; the used flags of the CS2 trio are cleared in the COPY only."""
    dst = tmp / "data"
    shutil.copytree(REAL_DATA, dst, ignore=shutil.ignore_patterns("logs", "plans", "theme_cache"))
    for f, fn in (("used_flags.json", lambda d: {k: v for k, v in d.items() if "2025.02.04 - 09.46" not in k}),
                  ("used_clips.json", lambda d: {g: [dict(e, clips=[c for c in e.get("clips", []) if "2025.02.04 - 09.46" not in c]) for e in l] for g, l in d.items()})):
        p = dst / f
        p.write_text(json.dumps(fn(json.loads(p.read_text(encoding="utf-8"))), indent=1), encoding="utf-8")
    return dst


def run_real(game, paths, override_on):
    """Same path as the GUI 'Manual dry': make_plan (events + plan + ledger) on the data copy. Returns (plan, ledger)."""
    M.save_json(M.DATA / "clip_overrides.json", {})
    if override_on:
        M.set_clip_override([str(CLIPS / VAL[3])], True)
    plan, _ = M.make_plan(M.load_config(), game, [str(p) for p in paths], seed=1)
    return plan, M.LAST_LEDGER[0]


def takes_view(plan):
    return [(Path(t["path"]).name, t["n"], list(t["victims"]), [round(k, 3) for k in t["kills"]], bool(t.get("stitched"))) for t in plan["takes"]]


def states(led):
    c = {}
    for r in led.rows:
        c[r["state"]] = c.get(r["state"], 0) + 1
    return c


def part_real(tmp):
    with section("1) REAL clips (E:\\Movies), data copy, Manual-dry path: Valorant override OFF / ON, CS2 trio"):
        for p in [CLIPS / n for n in VAL] + [CS2_DIR / n for n in CS2]:
            check(p.exists(), f"real clip present: {p.name}")
        restore = use_data(real_copy(tmp))
        try:
            plan, led = run_real("valorant", [CLIPS / n for n in VAL], False)
            tv = takes_view(plan)
            by = {t[0][-12:]: t for t in tv}
            check(len(tv) == 4, f"override OFF: 4 events/takes ({[(t[0][-12:], t[1]) for t in tv]})")
            check(any(t[0].endswith("03-21.mov") and t[1] == 1 for t in tv), "1K: 03-21")
            t2 = next((t for t in tv if t[0].endswith("03-35-20.mov")), None)
            check(t2 is not None and t2[1] == 2 and [norm(v) for v in t2[2]] == ["louma", "mitski"], "2K: 03-35-20, both kills in ONE event, in kill order")
            t4 = next((t for t in tv if "03-31" in t[0]), None)
            check(t4 is not None and [norm(v) for v in t4[2]] == ["louma", "kurotech", "mitski"], f"4K take (03-31-12 + 03-31-20): 3 distinct kills Louma, Kurotech, mitski in order ({t4 and t4[2]})")
            t5 = next((t for t in tv if "03-40" in t[0]), None)
            check(t5 is not None and t5[1] == 5 and t5[4] and [norm(v) for v in t5[2]] == ["mitski", "louma", "alexandre", "walther", "kurotech"],
                  f"Ace (03-40-15 + 03-40-20 stitched): 5 distinct kills in kill order ({t5 and t5[2]})")
            c = states(led)
            check(c.get("PLACED") == 11 and c.get("MERGED_DUP") == 3 and not c.get("CLIP_UNUSABLE") and not c.get("LOST") and not c.get("OVERRIDE_ADMITTED"),
                  f"ledger: 11 PLACED, 3 MERGED_DUP, 0 CLIP_UNUSABLE, 0 LOST ({c})")
            check(all("saved" in (r["info"].get("reason") or "") and "same victim, abs time match" in r["info"]["reason"] for r in led.rows if r["state"] == "MERGED_DUP"),
                  "every MERGED_DUP carries the reason 'saved N s apart, same victim, abs time match'")
            allk = [(Path(t["path"]).name, round(k, 2)) for t in plan["takes"] for k in t["kills"]]
            check(len(allk) == len(set(allk)) == 11 and all(a < b for t in plan["takes"] for a, b in zip(t["kills"], t["kills"][1:])), "no kill twice in the take list; each fight in kill order")
            plan, led = run_real("valorant", [CLIPS / n for n in VAL], True)
            tv = takes_view(plan)
            t4 = next((t for t in tv if "03-31" in t[0]), None)
            c = states(led)
            check(len(tv) == 4 and t4 and t4[1] == 4 and [norm(v) for v in t4[2]] == ["louma", "kurotech", "mitski", "alexandre"],
                  f"override ON for 03-31-20: the 4K has 4 kills incl. Alexandre ({t4 and t4[2]})")
            check(c.get("OVERRIDE_ADMITTED") == 1 and c.get("PLACED", 0) + c.get("OVERRIDE_ADMITTED", 0) == 12 and c.get("MERGED_DUP") == 3 and not c.get("LOST"), f"ledger ON: 12 placed, 1 OVERRIDE_ADMITTED ({c})")
            M.save_json(M.DATA / "clip_overrides.json", {})
            plan, led = run_real("cs2", [CS2_DIR / CS2[1]], False)
            tv = takes_view(plan)
            check(len(tv) == 1 and tv[0][1] == 3 and tv[0][4] and [norm(v) for v in tv[0][2]] == ["danok3", "purplokush", "novarsaynever"],
                  f"CS2 trio (middle clip ticked): ONE stitched take, kills 1, 2, 3 in order ({tv})")
            check(len(takes_view(run_real("cs2", [CS2_DIR / n for n in CS2], False)[0])) == 1, "CS2 trio (all three ticked): one take")
        finally:
            restore()


def it_of(p, dur, kills=()):
    it = pool_item(rec_of(p, dur, "valorant"), list(kills))
    it["anc"] = M.clip_anchor(str(p), dur)
    return it


def part_link(tmp):
    with section("2) linking by save time: different rounds, 3 minutes apart, adjacent"):
        d = tmp / "link"
        d.mkdir()
        t0 = 1_800_000_000.0

        def mk(name, end, kills):                              # a 40 s clip whose modified time (= save time = END) is `end`
            p = d / name
            p.write_bytes(b"x")
            os.utime(p, (end, end))
            return it_of(p, 40.0, kills)
        a = mk("a.mov", t0, [(30.0, "Louma"), (36.0, "mitski")])
        diff = mk("b_diff.mov", t0 + 27, [(25.0, "Louma"), (31.0, "mitski")])        # kill offset 5 s, save offset 27 s
        lk, why = M.save_time_link(a, diff)
        check(lk is None and "different rounds" in why, f"same victim names, kill offset (5 s) disagrees with the save offset (27 s) by more than 3 s: NOT linked ({why})")
        evs, _ = M.build_events([dict(a), dict(diff)], "valorant", M.load_config(), random.Random(1))
        check(len(evs) == 2 and not any(e["stitched"] for e in evs), "different rounds stay two separate events")
        free = mk("b_free.mov", t0 + 27, [(5.0, "Alexandre")])
        lk, why = M.save_time_link(a, free)
        check(lk is not None and abs(lk["raw_offset"] - 27.0) < 0.01 and lk["pairs"] == 0, f"saved 27 s apart, no shared victim: linked at the save-time offset ({lk and lk['raw_offset']})")
        agree = mk("b_agree.mov", t0 + 27, [(9.5, "mitski")])
        lk, why = M.save_time_link(a, agree)
        check(lk is not None and abs(lk["raw_offset"] - 26.5) < 0.01 and lk["pairs"] == 1, f"shared victim agreeing within 3 s: linked, aligned by the kill pair ({lk and lk['raw_offset']})")
        far = mk("far.mov", t0 + 40 + 180, [(5.0, "Alexandre")])
        lk, why = M.save_time_link(a, far)
        check(lk is None and "gap" in why, f"clip saved 3 min away: NOT linked ({why})")
        evs, _ = M.build_events([dict(a), dict(far)], "valorant", M.load_config(), random.Random(1))
        check(len(evs) == 2 and not any(e["stitched"] for e in evs), "a clip 3 min apart stays its own event")


def part_fight(tmp):
    with section("3) fight split rule: under 25 s unchanged, 25 s or longer up to 30 s"):
        B = base_module(tmp)
        cfg = M.load_config()
        names_ = distinct_names(30, 9)

        def events(mod, dur, ts_):
            rec = rec_of(tmp / f"f{dur}.mov", float(dur), "valorant")
            it = pool_item(rec, list(zip(ts_, names_)))
            evs, _ = mod.build_events([it], "valorant", mod.load_config(), random.Random(1))
            return evs, getattr(mod, "LAST_LEDGER", [None])[0]
        e, _ = events(M, 40, [5.0, 19.4, 32.6, 43.0 - 6])         # real gaps of 14.4 / 13.2 s in a 40 s clip
        check(len(e) == 1 and e[0]["n"] == 4, f"40 s clip, gaps 14.4 / 13.2 / 4.4 s: ONE fight with all 4 kills ({[x['n'] for x in e]})")
        e, led = events(M, 40, [4.0, 33.0])                       # gap 29 s: still one fight
        check(len(e) == 1 and e[0]["n"] == 2, "40 s clip, gap 29 s (<= 30): one fight")
        e, led = events(M, 45, [4.0, 36.0])                       # gap 32 s: split, one event per clip
        check(len(e) == 1 and e[0]["n"] == 1 and sum(1 for r in led.rows if r["unusable"]) == 1, "45 s clip, gap 32 s (> 30): split, the second fight has a ledger reason (old one-event-per-clip rule)")
        for ts_ in ([3.0, 14.5], [2.0, 12.5, 23.0], [3.0, 8.0, 20.0]):       # 24 s clip: today's value (Valorant 10 s)
            em, _ = events(M, 24, ts_)
            eb, _ = events(B, 24, ts_)
            check([(x["n"], x["times"]) for x in em] == [(x["n"], x["times"]) for x in eb], f"24 s clip, kills {ts_}: identical to V6.9.7 ({[x['n'] for x in em]})")


def part_twin(tmp):
    with section("4) utility override: death / revive row twin of the admitted row, and the death-lock exemption"):
        base_a = {"kills": [{"t": 4.4, "victim": "Kurotech", "ks": 1.0}], "deaths": [], "revives": [37.733],
                  "rej": [{"t": 37.7, "reason": "revive: green victim side ('IV' -> 'fireaxe Alexandre') - teammate revive / resurrect, not a kill, not a death", "ks": 0.22},
                          {"t": 37.8, "reason": "utility: small/square weapon icon (grenade, molotov, ability)", "ks": 1.0}]}
        util = [{"t": 37.8, "victim": "Alexandre", "ks": 1.0, "util": True, "row": "[fireaxe] util [Alexandre]"}]
        real = M.utility_kill_rows
        M.utility_kill_rows = lambda *a, **k: [dict(u) for u in util]
        try:
            p = tmp / "twin.mov"
            p.write_bytes(b"x")
            ovs = {M._pkey(str(p)): {"allow_utility_kills": True, "size": 1}}
            rec = rec_of(p, 40.0, "valorant")
            a = M.apply_utility_override(rec, {"x": 1}, json.loads(json.dumps(base_a)), M.load_config(), "valorant", ovs, {})
            check(a["revives"] == [] and "twin" in a["rej"][0]["reason"] and len(a["kills"]) == 2, "revive-looking twin 'IV -> fireaxe Alexandre' within 0.1 s: ignored (no fight split, no lock)")
            d_ = json.loads(json.dumps(base_a))
            d_["revives"], d_["deaths"] = [], [37.7]
            d_["rej"][0]["reason"] = "death: FIREAXE on the victim side ('Alexandre fireaxe' 90)"
            a = M.apply_utility_override(rec, {"x": 1}, d_, M.load_config(), "valorant", ovs, {})
            check(a["deaths"] == [], "death row whose victim text contains the admitted victim, within 0.5 s: ignored for the death window")
            d_ = json.loads(json.dumps(base_a))
            d_["revives"], d_["deaths"] = [], [30.0]
            d_["rej"][0]["reason"] = "death: FIREAXE on the victim side ('Walther fireaxe' 90)"
            d_["rej"][0]["t"] = 30.0
            a = M.apply_utility_override(rec, {"x": 1}, d_, M.load_config(), "valorant", ovs, {})
            check(a["deaths"] == [30.0], "a real death row of another victim is untouched")
            a_off = M.apply_utility_override(rec, {"x": 1}, json.loads(json.dumps(base_a)), M.load_config(), "valorant", {}, {})
            check(a_off["revives"] == [37.733] and len(a_off["kills"]) == 1, "override OFF: identical to before")
        finally:
            M.utility_kill_rows = real
        it = {"rec": dict(rec_of(tmp / "x.mov", 40.0, "valorant"), audio=False), "deaths": [37.0], "revives": [], "rej": [],
              "kills": [{"t": 37.8, "victim": "Alexandre", "ks": 1.0, "util": True}, {"t": 38.0, "victim": "Bob", "ks": 1.0}]}
        st = M.verified_kills([it], M.load_config())
        check([k["victim"] for k in it["kills"]] == ["Alexandre"] and st["death_lock"] == 1, "a row admitted by the override is exempt from the 8 s death window; a normal row is not")


def part_interp(tmp):
    with section("5) interpolation tolerance (one frame of the montage fps + 2 ms)"):
        check(M.interp_duration_ok(1.491, 1.480) and M.interp_duration_ok(2.724, 2.708), "the real failures 1.491 vs 1.480 s and 2.724 vs 2.708 s pass")
        check(not M.interp_duration_ok(1.52, 1.480) and not M.interp_duration_ok(1.45, 1.480), "a segment 40 ms off still fails")


def part_guard(tmp):
    with section("6) guard: 50 Valorant + 50 CS2 generated clips under 25 s: events and plans identical to V6.9.7"):
        B = base_module(tmp)
        cfg = M.load_config()
        for game in ("valorant", "cs2"):
            r = random.Random(11 if game == "cs2" else 12)
            vn = distinct_names(400, 21)
            items, vi = [], 0
            for i in range(50):
                dur = r.uniform(9, 24.5)
                ks, t = [], r.uniform(2.0, 4.0)
                while t < dur - 3 and len(ks) < 4:
                    ks.append((round(t, 3), vn[vi]))
                    vi += 1
                    t += r.choice([1.0, 2.5, 4.0, 6.0, 9.0, 11.0])
                items.append(pool_item(rec_of(tmp / f"g_{game}_{i}.mov", dur, game), ks))
            evm, _ = M.build_events([dict(x) for x in items], game, cfg, random.Random(3))
            evb, _ = B.build_events([dict(x) for x in items], game, B.load_config(), random.Random(3))
            view = lambda evs: json.dumps([{k: v for k, v in e.items() if k != "rec"} for e in evs], sort_keys=True, default=str)
            check(view(evm) == view(evb) and len(evm) > 10, f"{game}: kills and events identical to V6.9.7 ({len(evm)} events, {sum(e['n'] for e in evm)} kills)")
            song = {"path": "x.mp3", "title": "x", "artist": "a"}
            plm = M.plan_montage(cfg, game, evm, song, M.default_song_map(), 5, "auto", "optimal", [], [])
            plb = B.plan_montage(B.load_config(), game, evb, song, B.default_song_map(), 5, "auto", "optimal", [], [])
            tk = lambda p: json.dumps([(Path(t["path"]).name, t["segs"], t["kills_out"], t["kills"]) for t in p["takes"]], default=str)
            check(tk(plm) == tk(plb) and len(plm["takes"]) > 2, f"{game}: plan identical to V6.9.7 ({len(plm['takes'])} takes)")


def main():
    real_before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t6971_"))
    restore = use_data(tmp / "gen_data")
    try:
        for fn in (part_interp, part_twin, part_link, part_fight, part_guard):
            fn(tmp)
    finally:
        restore()
    part_real(tmp)
    with section("7) real montage_data untouched"):
        check(snapshot(REAL_DATA) == real_before, "real montage_data byte-identical after the tests")
    total = time.time() - T_ALL
    print("section times: " + ", ".join(f"{t.split(')')[0]} {s:.0f}s" for t, s in SECTIONS) + f"; total {total:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
