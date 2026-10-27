"""V9.1.3 tests (fast, no render): kill rows of mine are no longer dropped (CS2), and the CUT LIST CHECK catches a take that shows a kill row it does not count.
  0) title-bar version V9.1.3, the version in the packaging / START_HERE, the V9.1.3 entry on top of both changelogs
  1) CS2 row finder on real killfeed frames (tests/v913_frames, the frames the sidecar tracker decodes):
     - CS2 2026-10-17 17-15-59 frame 660: the 3rd kill row ('fireaxe + [Xialongpeek] Ser Skins > I KICK MIDGETS FOR FUN') runs past the region's LEFT edge: V9.1.2 no row, V9.1.3 a row
     - same clip frame 858: the only row on screen ('fireaxe > [BOT] Tom') has one strict-red edge: V9.1.2 no row, V9.1.3 a row (lone-line rescue without a reference row)
     - Counter-strike 2 2023.09.01 - 12.13.31 frames 0 / 6: the Flx row faded in during the first frames: frame 0 does not hold it (f0 < BORDER_F0_SIM) = a kill inside the clip
     - rows that were found before are found the same way
  2) classification / row grid / pre-clip on real row data (tests/v913_rows.json):
     - the Dual Berettas icon read as text ('FP') made a gun kill 'utility' (case A, Han): now a kill
     - a row cut by the left edge is never 'another player's row' (its killer is off-screen)
     - row grid: a slide that paused mid-way is no row level (2023.10.21 - 15.35.26: Mukhammed Abdul, 2026-10-17 17-15-59: Han) and the V9.1.2 / V8.7 fixtures keep their rows
     - the V9.1.3 sidecars of the regression clips give the kills verified on the frames; older sidecars are read exactly as v9.1.2 reads them
     - the dating memo of a rebuilt sidecar never takes a date of the old sidecar's track with the same number
  3) CUT LIST CHECK: a take that shows an uncounted kill row of mine fails (with the clip, time and rule); a take whose kill row appeared before the take start fails;
     a clean take passes; takes without kill rows (Valorant, synthetic) are untouched
  4) R6S '4k ace' (tests/r6s_4k_ace_ocr.json) still has its 4 kills
  r) real data (MONTAGER_DATA = a COPY of montage_data, clips in E:/Movies): a FRESH scan (sidecar rebuilt into a temp folder) of every regression clip gives the kills verified on the frames
  g) real data: Valorant / R6S clips give the same kills / rejects as v9.1.2
python tests\\test_v913.py   (parts: V913_PARTS=0,1,2,3,4  real data: V913_PARTS=r,g with MONTAGER_DATA)"""
import copy
import json
import os
import sys
import tempfile
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="v913_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
warnings.simplefilter("ignore")
import montage as M                                                                          # noqa: E402
from _run import run as run_                                                                 # noqa: E402

PARTS = [x for x in os.environ.get("V913_PARTS", "0,1,2,3,4").split(",") if x]
FAILS = []
FR = HERE / "v913_frames"
FX = json.loads((HERE / "v913_rows.json").read_text(encoding="utf-8"))


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


_BASE = []


def base():
    """The montage module of the v9.1.2 tag (same data folder)."""
    if not _BASE:
        src = (HERE / "test_v842.py").read_text(encoding="utf-8")
        ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
        exec(compile(src[:src.index("def part0")], str(HERE / "test_v842.py"), "exec"), ns)
        ns["BASE_REF"] = "v9.1.2"
        _BASE.append(ns["load_base"]())
    return _BASE[0]


def frame(name):
    import cv2
    import numpy as np
    return cv2.imdecode(np.fromfile(str(FR / f"{name}.png"), np.uint8), cv2.IMREAD_COLOR)


def rects(fr, new=True):
    sw = (M.CS2_OPEN_LEFT_ON, M.CS2_LOOSE_PAIR_ON, M.CS2_LONE_ROW_ON)
    old = [s[0] for s in sw]
    for s in sw:
        s[0] = new
    try:
        return [(r["x0"], r["y0"], r["x1"], r["y1"]) for r in M.border_rects(fr)]
    finally:
        for s, v in zip(sw, old):
            s[0] = v


def kills_of(b):
    return [(round(k["t"], 2), k["victim"]) for k in b["kills"]]


def part0():
    print("0) version, packaging, changelogs")
    check("APP_VERSION = V9.1.3", M.APP_VERSION == "V9.1.3", M.APP_VERSION)
    check("START_HERE names V9.1.3", (ROOT / "START_HERE.txt").read_text(encoding="utf-8").startswith("MONTAGER V9.1.3"))
    check("installer example names 9.1.3", "/DAppVersion=9.1.3 " in (ROOT / "packaging" / "montager.iss").read_text(encoding="utf-8"))
    check("release script example names v9.1.3", "(v9.1.3 for V9.1.3)" in (ROOT / "packaging" / "make_release.py").read_text(encoding="utf-8"))
    simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    check("Settings changelog: V9.1.3 on top of V9.1.2", 0 <= simple.index("## V9.1.3") < simple.index("## V9.1.2"))
    top = simple[simple.index("## V9.1.3"):simple.index("## V9.1.2")]
    check("Settings entry: headline names the missing kills, plain points only", "missing kills" in top.splitlines()[0].lower() and "KNOWN" not in top.upper()
          and "ABANDON" not in top.upper() and "_" not in top and "(" not in top and 1 <= top.count("\n- ") <= 4, top)
    check("CHANGELOG.md: V9.1.3 on top of V9.1.2", 0 <= tech.index("## V9.1.3") < tech.index("## V9.1.2"))


def part1():
    print("1) CS2 row finder on real killfeed frames")
    a660 = frame("caseA_f660")
    o, n = rects(a660, False), rects(a660, True)
    check("17-15-59 f660: V9.1.2 finds the two closed rows only", len(o) == 2 and all(r[0] > 200 for r in o), o)
    check("17-15-59 f660: V9.1.3 also finds the row cut by the region's left edge (x0 = 0, right edge as the others)",
          len(n) == 3 and n[:2] == o and n[2][0] == 0 and abs(n[2][2] - o[0][2]) <= 2, n)
    a858 = frame("caseA_f858")
    o, n = rects(a858, False), rects(a858, True)
    check("17-15-59 f858 (Tom, the only row): V9.1.2 no row, V9.1.3 one row at the killfeed's right edge", o == [] and len(n) == 1 and n[0][2] >= 526, (o, n))
    f0, f6 = frame("caseB_f0"), frame("caseB_f6")
    check("2023.09.01 f0: the pre-clip row (smpampip) is found the same way", rects(f0, False) == rects(f0, True) and len(rects(f0)) == 1, rects(f0))
    r6 = M.border_rects(f6)
    check("2023.09.01 f6: the Flx row is a row", len(r6) == 1, r6)
    if r6:
        d = M.border_desc(f6, r6[0])
        s0, s6 = M.border_seen_f0(f0, r6[0], d), M.border_seen_f0(f6, r6[0], d)
        check(f"2023.09.01: frame 0 does not hold the Flx row (f0 {s0} < {M.BORDER_F0_SIM}), the row's own frame does ({s6})", s0 < M.BORDER_F0_SIM <= s6, (s0, s6))


def part2():
    print("2) classification, row grid, pre-clip, sidecars of the regression clips")
    B = base()
    old_a = FX["caseA_old"]
    fp = next(v for t in old_a["tracks"] for v in t["votes"] if v["f"] == 564)          # 'FP' + 'fireaxo' > '[BOT]Han': the read that called the row utility
    M.CS2_ICON_TEXT_ON[0] = False
    v_off = M.cs2_vote_verdict(M.cs2_track_rows({"votes": [copy.deepcopy(fp)]})[0][1])
    M.CS2_ICON_TEXT_ON[0] = True
    v_on = M.cs2_vote_verdict(M.cs2_track_rows({"votes": [copy.deepcopy(fp)]})[0][1])
    check("case A Han (Dual Berettas read as 'FP'): V9.1.2 'utility', V9.1.3 a kill", v_off[0] == "utility" and v_on[0] == "kill", (v_off, v_on))
    new_a = FX["caseA_new"]
    cut = next(t for t in new_a["tracks"] if t["x0"] <= 1 and t["hits"] > 100)
    c_cut = M.cs2_classify_track(copy.deepcopy(cut))
    c_moved = M.cs2_classify_track(dict(copy.deepcopy(cut), x0=250))
    check("case A cut row: a kill (killer off-screen); the same reads on a closed row would be another player's row",
          c_cut["verdict"] == "kill" and c_moved["verdict"] == "other", (c_cut["verdict"], c_moved["verdict"]))
    for key, keep in (("raw_2023_10_21", "Mukhammed Abdul (13.67 s)"), ("raw_caseA", "Han (15.13 s)")):
        raw, n, tid = FX[key]["tracks"], FX[key]["n"], FX[key]["must_keep"]
        r2 = [t["id"] for t in M.border_shape_filter(copy.deepcopy(raw), n, fix=2)[0]]
        r3 = [t["id"] for t in M.border_shape_filter(copy.deepcopy(raw), n, fix=M.BORDER_FIX)[0]]
        check(f"{key}: the row of {keep} is a row with the V9.1.3 grid (fix {M.BORDER_FIX}); every V9.1.2 row stays", tid in r3 and set(r2) - {tid} <= set(r3), (r2, r3))
    fx12 = json.loads((HERE / "cs2_2k_0026_rows.json").read_text(encoding="utf-8"))
    for key, want in (("raw_0026_09", [3, 4, 7]), ("raw_2026_02_06", [0, 1, 2])):     # 00-26-09 tracks 1 / 2: 3-frame red shapes 82-105 px wide in the 1st second (never a kill): no row now
        got = sorted(t["id"] for t in M.border_shape_filter(copy.deepcopy(fx12[key]["tracks"]), fx12[key]["n"], fix=M.BORDER_FIX)[0])
        check(f"V9.1.2 fixture {key}: every kill row stays a row with the V9.1.3 grid ({want})", got == want, got)
    check("sidecar levels: ext 5 = V9.1.3 rules, ext 4 / 3 / older read as before",
          M.BORDER_EXT == 5 and M.border_fix_kw({"ext": 5}) == {"fix": 3} and M.border_fix_kw({"ext": 4}) == {"fix": 2}
          and M.border_fix_kw({"ext": 3}) == {"fix": True} and M.border_fix_kw({"ext": 2}) == {})
    for name, want in FX["expect"].items():
        sc = FX["sidecars"].get(name)
        if sc is None:
            check(f"{name}: V9.1.3 sidecar in the fixture", False)
            continue
        b = M.border_analysis(copy.deepcopy(sc), M.DEFAULT_CONFIG, [])
        got = [round(k["t"], 1) for k in b["kills"]]
        ok = len(got) == len(want) and all(abs(g - w) <= 0.45 for g, w in zip(got, want))
        check(f"{name}: {len(want)} kills ({', '.join(f'{w:.1f}' for w in want)} s, verified on the frames); the V9.1.3 sidecar gives {got}", ok, kills_of(b))
    for name, sc in FX["old_sidecars"].items():
        a = M.border_analysis(copy.deepcopy(sc), M.DEFAULT_CONFIG, [])
        M.CS2_ICON_TEXT_ON[0] = False
        a_off = M.border_analysis(copy.deepcopy(sc), M.DEFAULT_CONFIG, [])
        M.CS2_ICON_TEXT_ON[0] = True
        b = B.border_analysis(copy.deepcopy(sc), B.DEFAULT_CONFIG, [])
        check(f"{name} (old sidecar, ext {sc.get('ext', 1)}): with the icon read switched off identical to v9.1.2", kills_of(a_off) == kills_of(b), (kills_of(a_off), kills_of(b)))
    sc4 = {"ext": 4, "built": "2026-10-01 10:00:00"}
    sc5a, sc5b = {"ext": 5, "built": "2026-10-27 10:00:00"}, {"ext": 5, "built": "2026-10-27 11:00:00"}
    tr = {"id": 3, "first": 616}
    check("dating memo: older sidecars keep their key; a rebuilt sidecar never shares a key with the old one",
          M._dating_tid(sc4, tr) == "3" and M._dating_tid(sc5a, tr) != M._dating_tid(sc5b, tr) and M._dating_tid(sc5a, tr) != "3"
          and M._dating_tid(sc5a, tr) != M._dating_tid(sc5a, dict(tr, first=460)))


def _take(seen, kills=(10.0,), victims=("A",), segs=((8.5, 11.0),)):
    sg = [[a, b, 1.0, int(round((b - a) * M.OUT_FPS))] for a, b in segs]
    return {"path": "X.mp4", "segs": sg, "kills": list(kills), "victims": list(victims), "seen": seen}


def part3():
    print("3) CUT LIST CHECK: uncounted kill rows of mine inside a take")
    clean = _take([{"t": 10.0, "t_last": 17.5, "victim": "A", "rule": None, "clip": "X.mp4"}])
    check("a take that counts its only kill row: no problem", M.seen_rows_audit(clean) == [], M.seen_rows_audit(clean))
    unc = _take([{"t": 9.0, "t_last": 16.5, "victim": "B", "rule": "pre-clip: row already on screen when the clip starts ([fireaxe] gun [B])", "clip": "X.mp4"},
                 {"t": 10.0, "t_last": 17.5, "victim": "A", "rule": None, "clip": "X.mp4"}])
    m = M.seen_rows_audit(unc)
    check("an uncounted kill row on screen inside the take fails, naming the clip, the time and the rule",
          len(m) == 1 and "uncounted kill row" in m[0] and "X.mp4" in m[0] and "9.00s" in m[0] and "pre-clip" in m[0], m)
    other = _take([{"t": 2.0, "t_last": 9.0, "victim": "C", "rule": None, "clip": "X.mp4"}, {"t": 10.0, "t_last": 17.5, "victim": "A", "rule": None, "clip": "X.mp4"}])
    m = M.seen_rows_audit(other)
    check("a counted kill of the clip that is not in this take, still on screen at its start, fails", len(m) == 1 and "another take" in m[0], m)
    late = _take([{"t": 7.9, "t_last": 15.4, "victim": "A", "rule": None, "clip": "X.mp4"}], kills=(9.4,), segs=((8.4, 11.0),))
    m = M.seen_rows_audit(late)
    check("case B shape: the kill's row is on screen from before the take start, the take 'cuts to' the kill later: fails",
          len(m) == 1 and "before the take starts" in m[0], m)
    brief = _take([{"t": 10.9, "t_last": 18.0, "victim": "D", "rule": "outlined row seen only 9 frames", "clip": "X.mp4"},
                   {"t": 10.0, "t_last": 17.5, "victim": "A", "rule": None, "clip": "X.mp4"}])
    check(f"a row on screen under {M.SEEN_MIN_S} s at the very end of the take does not fail", M.seen_rows_audit(brief) == [], M.seen_rows_audit(brief))
    plan = {"takes": [dict(unc, f0=0, nf=150, beat0=0, beat_end=4, kills_out=[1.5], rows=[10.0], rows_out=[1.5], dur=2.5, n=1, srcs=[{"shift": 0.0}])],
            "total_frames": 150}
    bad = M.verify_cutlist(plan, log=False)
    check("verify_cutlist (the CUT LIST CHECK) lists it as a per-take 'kill row' problem (the planner re-plans that take, the render only warns)",
          any(b.startswith("take 1:") and "uncounted kill row" in b and "kill row" in b for b in bad), bad)
    st = _take([{"t": 10.0, "t_last": 17.5, "victim": "sorrowfully", "rule": None, "clip": "A.mp4"},
                {"t": 15.0, "t_last": 17.5, "victim": "sorrowfully", "rule": "pre-clip: row already on screen when the clip starts", "clip": "B.mp4"}],
               victims=("sorrowfully",), segs=((8.5, 15.0), (15.0, 16.5)))
    st["segs"][0].append(0)
    st["segs"][1].append(1)
    st["srcs"] = [{"path": "X/A.mp4"}, {"path": "X/B.mp4"}]
    check("stitched clips: the 2nd clip's pre-clip row that is the 1st clip's counted row does not fail (TOY dry plan: 2025.02.04 - 06.41.42 + 06.41.49)",
          M.seen_rows_audit(st) == [], M.seen_rows_audit(st))
    st["seen"][1]["victim"] = "someoneelse"
    check("stitched clips: an uncounted row of the 2nd clip in its own footage still fails", len(M.seen_rows_audit(st)) == 1, M.seen_rows_audit(st))
    no = dict(unc)
    no.pop("seen")
    check("a take without kill-row data (Valorant, synthetic events) is untouched", M.seen_rows_audit(no) == [])
    it = {"kills": [{"t": 10.0, "victim": "A", "track": 1, "border": True}], "rej": []}
    a = {"border": True, "kills": it["kills"],
         "rows": [{"t": 10.0, "cls": {"verdict": "kill", "vtext": "A"}, "track": {"id": 1, "first": 300, "last": 525}},
                  {"t": 12.0, "cls": {"verdict": "kill", "vtext": "B"}, "track": {"id": 2, "first": 360, "last": 380}},
                  {"t": 13.0, "cls": {"verdict": "assist", "vtext": "C"}, "track": {"id": 3, "first": 390, "last": 600}},
                  {"t": 14.0, "cls": {"verdict": "kill", "vtext": "D"}, "track": {"id": 4, "first": 420, "last": 640}}],
         "rej": [{"t": 12.0, "reason": "outlined row seen only 9 frames and my name never read ([-] gun [B]): not a kill row"},
                 {"t": 14.0, "reason": "CS2 stale feed row: the same row as one on screen at 10.0 s ([D] matches [A], shifted up in the feed)"}]}
    rows = M.clip_seen_rows(a, it["kills"])
    check("clip_seen_rows: the counted kill, the row dropped by the frames minimum; never assists or copies of a counted row",
          [(r["t"], r["rule"] is None) for r in rows] == [(10.0, True), (12.0, False)], rows)


def part4():
    print("4) R6S '4k ace' keeps its 4 kills")
    e = json.loads((HERE / "r6s_4k_ace_ocr.json").read_text(encoding="utf-8"))
    e = e.get("entry", e)
    a = M.r6s_analyse_entry(e, M.DEFAULT_CONFIG)
    check("4k ace: 4 kills", len(a["kills"]) == 4, [(k["t"], k.get("victim")) for k in a["kills"]])


def partr():
    print("r) real data: a fresh scan of every regression clip gives the kills verified on the frames")
    cfg = M.load_config()
    det = M.Detector("cs2")
    M.BORDER_DIR = TMP / "rows"
    store = M.load_kills_cache()
    recs = {Path(r["path"]).name: r for r in M.scan_clips(cfg) if r.get("game") == "cs2"}
    for name, want in FX["expect"].items():
        rec = next((r for n, r in recs.items() if name in n), None)
        e = store.get(M.kills_key(rec, "cs2", det)) if rec else None
        if rec is None or not e:
            check(f"{name}: clip and its scan found", False)
            continue
        M.border_build(rec, det, cfg)
        a = M.analyse_clip_entry(rec, e, cfg, "cs2")
        got = [round(k["t"], 1) for k in a["kills"]]
        ok = len(got) == len(want) and all(abs(g - w) <= 0.45 for g, w in zip(got, want))
        check(f"{name}: fresh scan {got}, frames {want}", ok, [(k["t"], k.get("victim")) for k in a["kills"]])


def partg():
    print("g) real data: Valorant / R6S read exactly as v9.1.2")
    B = base()
    child = TMP / "kills_dump.py"
    child.write_text(CHILD, encoding="utf-8")
    res = {}
    for name, root in (("v9.1.3", ROOT), ("v9.1.2", Path(B.__file__).parent)):
        out = TMP / f"kills_{name}.json"
        r = run_([sys.executable, str(child), str(root), str(out)], text=True, cwd=str(root), timeout=3600)
        check(f"{name}: Valorant / R6S kill lists computed", r.ok and out.exists(), r.tail(400))
        res[name] = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    for g in ("valorant", "r6s"):
        a, b = res["v9.1.3"].get(g, {}), res["v9.1.2"].get(g, {})
        diff = [p for p in a if a[p] != b.get(p)]
        check(f"{g}: {len(a) - len(diff)} of {len(a)} cached clips give the same kills / rejects as v9.1.2", a and set(a) == set(b) and not diff, diff[:5])


CHILD = """import sys, os, json
sys.path.insert(0, sys.argv[1])
import montage as M
cfg = M.load_config(); store = M.load_kills_cache(); res = {}
for g in ("valorant", "r6s"):
    dg = M.load_dets(g).get(g); res[g] = {}
    for r in M.scan_clips(cfg):
        if r.get("game") != g or r.get("error") or not r.get("w"):
            continue
        e = store.get(M.kills_key(r, g, dg))
        if not e or e.get("error"):
            continue
        a = M.analyse_clip_entry(r, e, cfg, g)
        res[g][r["path"]] = [[[k["t"], k.get("victim")] for k in a["kills"]], [x["reason"] for x in a["rej"]]]
json.dump(res, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
"""

for p_ in PARTS:
    {"0": part0, "1": part1, "2": part2, "3": part3, "4": part4, "r": partr, "g": partg}[p_]()
print("\nV9.1.3 tests:", "ALL OK" if not FAILS else f"{len(FAILS)} FAILED: " + "; ".join(FAILS))
sys.exit(1 if FAILS else 0)
