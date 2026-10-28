"""V9.2.0 tests (fast; no render, no real clips):
  0) title-bar version V9.2.0, both changelogs carry V9.2.0 on top
  1) speed: the bounded dead-air cuts give the same cuts as the V9.1.4 function; the memo returns the same answer; big caches are saved compact and read back equal;
     a stitched cut's frame check (also an unreadable one) is asked of ffmpeg once; per-stage timings
  2) the kill-row pre-check: a row that stays on screen through the kill is caught before planning, a row outside every take is not
  3) sky colour: the automatic family is a seeded pick of deep blue / teal / hazy orange (no family most of the time; the song's feel only leans), a Manual pick wins
  4) the ending: the loudness rank of the song's end; a section that ends on a peak scores lower; a plan that still ends loud gets the long music fade
  5) CS2 run-up: at least the hit + its lead before the first kill row when the clip has that footage; the old minimum for a short clip and for other games
  6) weekly plan reuse key: the same state = the same key; a used flag written = another key
  7) the Manual tab (needs a display): no Dry plan, Sky colour / Font on the Render row, a small Preview next to Last seed; ticking / choosing never plans; a move while a job runs is put off
python tests\\test_v920.py   (parts: V920_PARTS=0,1,2,3,4,5,6,7)"""
import copy
import os
import random
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v920_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

PARTS = [x for x in os.environ.get("V920_PARTS", "0,1,2,3,4,5,6,7").split(",") if x]
FAILS = []


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def part0():
    print("0) version and changelogs")
    check("title-bar version V9.2.0", M.APP_VERSION == "V9.2.0")
    for f in ("CHANGELOG.md", "docs/CHANGELOG_SIMPLE.md"):
        txt = (ROOT / f).read_text(encoding="utf-8")
        i92 = txt.find("## V9.2.0")
        check(f"{f}: V9.2.0 is the newest entry", i92 >= 0 and all(i92 < txt.find(h) for h in ("## V9.1.4",) if txt.find(h) >= 0))


def _old_dead_air(ev, U, kb, t0=None, lead_override=None):
    """the V9.1.4 dead_air_cuts (walks every tick to the song's end), the reference."""
    import bisect
    times = ev["times"]
    span = times[-1] - times[0]
    allow = ev.get("_allow")
    if allow is None or len(times) < 2 or max(b - a for a, b in zip(times, times[1:])) <= M.GAP_ALLOW[0]:
        return [], span
    cuts, o = [], 0.0
    T0, nt = float(U[kb]) if t0 is None else float(t0), len(U)
    rows = ev.get("rows") or times
    for i, (a, b) in enumerate(zip(times, times[1:])):
        g = b - a
        if g <= allow(T0 + o):
            o += g
            continue
        rd = max(0.0, rows[i] - a) if i < len(rows) else 0.0
        j0 = bisect.bisect_left(U, T0 + o + max(0.4, rd + M.ROW_TAIL) - 1e-6)
        ok = [j for j in range(j0, nt) if U[j] - (T0 + o) <= g - 1.0 - 0.25 and U[j] - (T0 + o) <= 2.5]
        cj = next((j for j in ok if j % 2 == 0), ok[0] if ok else None)
        if cj is None:
            o += g
            continue
        dc = float(U[cj]) - T0
        lead = 1.0
        nxt = [float(U[j]) - float(U[cj]) for j in range(cj + 1, min(nt, cj + 6)) if 0.85 <= U[j] - U[cj] <= 1.15]
        if nxt:
            lead = min(nxt, key=lambda x: abs(x - 1.0))
        if lead_override is not None and lead_override[0] == len(cuts):
            lead = min(float(lead_override[1]), g - (float(U[cj]) - (T0 + o)) - 0.05)
        elif (ev.get("unsure") or [False] * len(times))[i + 1]:
            lead = max(lead, min(lead + M.CS2_UNSURE_LEAD, g - (float(U[cj]) - (T0 + o)) - 0.05))
        cuts.append((dc, b - lead))
        o = dc + lead
    return cuts, (o if cuts else span)


def part1():
    print("1) speed: same answers, less work")
    rng = random.Random(5)
    bad = 0
    for k in range(400):
        bpm = rng.choice([88.0, 128.0, 175.0])
        bt = np.arange(0, 240, 60.0 / bpm)
        U = M._ticks(bt)
        n = rng.randint(2, 5)
        t = sorted(rng.uniform(2, 30) for _ in range(n))
        allow_c = rng.uniform(1.0, 4.0)
        ev = {"times": t, "rows": [x + rng.choice([0.0, 0.1]) for x in t], "_allow": (lambda _t, c=allow_c: c),
              "unsure": [rng.random() < 0.2 for _ in t]}
        kb = rng.randrange(10, len(U) - 200)
        t0 = None if rng.random() < 0.5 else float(U[kb]) + rng.uniform(-0.3, 0.3)
        lo = None if rng.random() < 0.7 else (0, rng.uniform(0.7, 1.25))
        ref = _old_dead_air(copy.deepcopy(ev), U, kb, t0, lo)
        a1 = M.dead_air_cuts(ev, U, kb, t0, lo)
        a2 = M.dead_air_cuts(ev, U, kb, t0, lo)                  # memo hit
        if not (a1 == ref and a2 == ref):
            bad += 1
    check("dead-air cuts: 400 random events give exactly the V9.1.4 answer (first call and memo hit)", bad == 0, f"{bad} differ")
    big = {f"k{i}": {"v": [i, i / 3.0, "x火"]} for i in range(M.SAVE_JSON_BIG + 50)}
    small = {"a": 1}
    M.save_json(TMP / "big.json", big)
    M.save_json(TMP / "small.json", small)
    txt = (TMP / "big.json").read_text(encoding="utf-8")
    check("a big cache is saved compact (one line) and reads back equal", "\n" not in txt.strip() and M.load_json(TMP / "big.json", {}) == big)
    check("a small file (settings) stays readable (indented)", "\n" in (TMP / "small.json").read_text(encoding="utf-8"))
    a, b = TMP / "a.mp4", TMP / "b.mp4"
    a.write_bytes(b"0" * 100)
    b.write_bytes(b"1" * 100)
    calls = []
    keep = M._verify_stitch
    M._verify_stitch = lambda spans, cut: (calls.append(cut), (False, spans[1]["shift"], "could not read frames around the cut"))[1]
    try:
        M._STITCH_MEMO.clear()
        sp = [{"path": str(a), "shift": 0.0}, {"path": str(b), "shift": 3.5}]
        r1 = M.verify_stitch(sp, 7.25)
        r2 = M.verify_stitch(sp, 7.25)
        M._STITCH_MEMO.clear()                                   # a new run: from the cache file
        r3 = M.verify_stitch(sp, 7.25)
    finally:
        M._verify_stitch = keep
    check("an unreadable stitched cut is read once, then answered from the cache (also in the next job)", len(calls) == 1 and r1 == r2 == r3 and not r1[0], f"{len(calls)} reads")
    M.JOB_STAGES.clear()
    with M.jstage("planning"):
        time.sleep(0.02)
    with M.jstage("render"):
        pass
    ln = M.job_stages_line()
    check("per-stage timings: one STAGES line, stages in job order", ln.startswith("STAGES: planning") and "render" in ln, ln)


def part2():
    print("2) kill-row pre-check")
    base = {"times": [10.0, 12.0], "victims": ["a", "b"], "parts": [{"path": "x.mp4", "start": 0.0, "end": 30.0}]}
    pre = dict(base, seen=[{"t": 0.0, "t_last": 11.0, "victim": "zz", "rule": "pre-clip: row already on screen when the clip starts", "clip": "x.mp4"},
                           {"t": 10.0, "t_last": 13.0, "victim": "a", "rule": None, "clip": "x.mp4"}])
    far = dict(base, seen=[{"t": 2.0, "t_last": 4.0, "victim": "zz", "rule": "not in the kill list", "clip": "x.mp4"},
                           {"t": 10.0, "t_last": 13.0, "victim": "a", "rule": None, "clip": "x.mp4"}])
    check("a row on screen through the first kill that is no kill of the event: left out before planning", (M.seen_rows_doomed(pre) or "").startswith("uncounted kill row"))
    check("a row seconds before the first kill: the event is planned (a take may start after it)", M.seen_rows_doomed(far) is None)
    check("an event without kill rows (Valorant): planned", M.seen_rows_doomed(dict(base)) is None)


def part3():
    print("3) sky colour")
    from collections import Counter
    c = Counter(M.sky_variety_pick({"seed": s}, ["hazy orange", "deep blue", "teal"])[0] for s in range(1, 601))
    check("the three families all come up", set(c) == {"blue", "teal", "orange"}, str(c))
    check("no family in most montages (the song's feel only leans: orange here under 50 %)", max(c.values()) < 0.5 * 600, str(c))
    c2 = Counter(M.sky_variety_pick({"seed": s}, ["deep blue", "hazy orange"])[0] for s in range(1, 601))
    check("another feel leans another way (blue first)", c2.most_common(1)[0][0] == "blue", str(c2))
    same = all(M.sky_variety_pick({"seed": s}, ["teal"])[0] == M.sky_variety_pick({"seed": s}, ["teal"])[0] for s in range(1, 50))
    check("the same montage (seed) = the same colour", same)
    fam, why = M.sky_family_for({"seed": 3, "pick_sky": "violet", "song": {}}, ["hazy orange"])
    check("a Manual Sky colour pick wins", fam == "violet" and "Manual" in why)
    fam, why = M.sky_family_for({"seed": 3, "song": {}}, ["hazy orange"])
    check("DEFAULT: one of deep blue / teal / hazy orange", fam in ("blue", "teal", "orange"), fam)


def _an_peak():
    bt = list(np.arange(0.0, 220.0, 0.5))
    en = [0.9 if 150 <= t < 200 else 0.2 for t in bt]
    return {"beats": bt, "energy": en, "dur": 220.0}


def part4():
    print("4) the ending")
    an = _an_peak()
    check("loudness rank: inside the loud part high, in the calm part low",
          M.song_end_rank(an, 177, 180) >= M.ENDING_PEAK_RANK and M.song_end_rank(an, 97, 100) < 0.5)
    keep = M.song_live_range
    M.song_live_range = lambda a: (0.0, 220.0)
    try:
        plan = {"duration": 170.0, "song": {"start_t": 10.0, "fade_out_start": 167.0}, "outro": {"fade_start": 168.0, "fade_len": 2.0}, "notes": []}
        ok = M.calm_outro_music(plan, an, plan["notes"])
        check("a montage that stops on a peak of the song gets the long music fade", ok and abs(plan["duration"] - plan["song"]["fade_out_start"] - M.OUTRO_MUSIC_LONG) < 1e-6
              and plan["outro"].get("music_long"))
        plan2 = {"duration": 80.0, "song": {"start_t": 10.0, "fade_out_start": 77.0}, "outro": {"fade_start": 78.0, "fade_len": 2.0}, "notes": []}
        check("a montage that stops in a calm part keeps the short fade", not M.calm_outro_music(plan2, an) and plan2["song"]["fade_out_start"] == 77.0)
        plan3 = {"duration": 205.0, "song": {"start_t": 14.0, "fade_out_start": 202.0}, "outro": {"fade_start": 203.0, "fade_len": 2.0}, "notes": []}
        check("the song's own end: unchanged", not M.calm_outro_music(plan3, an))
    finally:
        M.song_live_range = keep
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    body = src[src.index("def optimal_fit("):src.index("def leadin_safe(")]
    check("the section choice counts the end's loudness when the montage stops before the song ends", "song_end_rank(an, float(bt[E])" in body and "E != last_b" in body)


def part5():
    print("5) CS2 run-up from the hit")
    cs = {"rec": {"game": "cs2"}, "times": [10.0], "pre": 5.0}
    short = {"rec": {"game": "cs2"}, "times": [10.0], "pre": 0.4}
    val = {"rec": {"game": "valorant"}, "times": [10.0], "pre": 5.0}
    rx = {"rec": {"game": "cs2"}, "times": [10.0], "pre": 5.0, "_rx": {"lead_min": M.LEAD_SOFT}}
    want = M.CS2_ROW_DELAY_S + M.CS2_KILL_LEAD_S
    check(f"CS2: at least {want:.2f} s before the first kill row (the hit + its lead)", abs(M._lead_min(cs) - want) < 1e-9 and want >= 0.55)
    check("CS2 clip with little footage before the kill: what it has (never less than the old minimum)", abs(M._lead_min(short) - 0.4) < 1e-9)
    check("Valorant: the old minimum", M._lead_min(val) == M.LEAD_MIN)
    check("a relaxed take (footage-limited) keeps its relaxed minimum", M._lead_min(rx) == M.LEAD_SOFT)


def part6():
    print("6) weekly plan reuse")
    k1 = M.weekly_plan_key("cs2", False)
    k2 = M.weekly_plan_key("cs2", False)
    check("the same state = the same key", k1 == k2)
    M.DATA.mkdir(parents=True, exist_ok=True)
    time.sleep(0.02)
    M.save_json(M.DATA / "used_clips.json", {"x": time.time()})
    check("a used flag written = another key (a render plans fresh)", M.weekly_plan_key("cs2", False) != k1)
    check("full mode is part of the key", M.weekly_plan_key("cs2", True) != M.weekly_plan_key("cs2", False))


def part7():
    print("7) the Manual tab")
    import tkinter
    try:
        r_ = tkinter.Tk()
        r_.destroy()
    except Exception:                                                                        # noqa: BLE001
        check("a display for the window", False, "no display")
        return
    old = M.use_data_dir(TMP / "gdata")
    try:
        app = M.App(0, startup=False)
        for _ in range(3):
            app.root.update()
        check("no Dry plan button on the Manual tab", "manual:dry" not in app.named)
        pv, rd = app.named.get("manual:preview"), app.named.get("manual:render")
        check("Render is the big button, Preview a small one", rd is not None and "Big" in str(rd.cget("style")) and pv is not None and "Big" not in str(pv.cget("style")))
        check("the small Preview sits next to Last seed", pv is not None and pv.master is app.named["manual:last_seed"].master)
        sk, fo = app.named.get("Sky colour"), app.named.get("Font")
        check("Sky colour and Font sit on the Render row", sk is not None and fo is not None and sk.master is rd.master and fo.master is rd.master)
        check("the status-line estimate is gone (nothing plans on its own)", not hasattr(app, "start_estimate"))
        planned = []
        keep = M.make_plan
        M.make_plan = lambda *a, **k: planned.append(1) or (_ for _ in ()).throw(RuntimeError("no plan"))
        try:
            app.clips = [{"path": "c1.mp4", "name": "c1.mp4", "folder": "V", "mtime": time.time(), "dur": 20, "kills": 3, "ks": [1, 2, 3]}]
            app.byp = {c["path"]: c for c in app.clips}
            app.ticked = {"c1.mp4"}
            app.update_status()
            app.m_style.set("chill")
            for _ in range(20):
                app.root.update()
                time.sleep(0.05)
        finally:
            M.make_plan = keep
        check("ticking clips / changing an option starts no plan", not planned)
        ran = []
        app.busy = True
        app.byp["c1.mp4"]["game"] = "valorant"
        put_off = app.when_idle("c1.mp4", lambda: ran.append(1), "test: put off")
        check("a move while a job runs is not refused: put off, the row gone at once", put_off and "c1.mp4" in app._gone and not ran)
        app.busy = False
        app.run_idle_ops()
        check("... and done when the job ends", ran == [1])
        app.root.destroy()
    finally:
        M.restore_data_dir(old)


for p in PARTS:
    globals()[f"part{p}"]()
print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
sys.exit(1 if FAILS else 0)
