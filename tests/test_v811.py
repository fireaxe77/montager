"""V8.1.1 tests: CS2 cuts land on the real kills, smoother CS2 slow-mo. FAST (no render).
  0) title-bar version V8.1.1; V8.1.1 on top of both changelogs; the Settings changelog names the old V8.1 entry V8.10 (its text unchanged)
  1) row identity: a fragment of another player's row never joins my row read only as a jumbled name; '+ name' = unread killer, not
     another player; a fragment lost under a second and back in the same place is the same row
  2) dating: a row scrolling up gets its template where it IS; a row cut by the region's lower edge is found by its top part
     (synthetic frames); the planner hooks for a kill whose time may be late (no slow-mo / ending / slowed tail / zoom, more run-in)
  3) filter graphs: Valorant / R6S identical to V8.1; CS2 differs only in the slowed pieces (motion interpolation instead of blending)
  r) (real data, on a copy, ~3 min) the three clips of I_CS2_V8.1_2026-10-14: 2026.02.11 18.25.49 kills 10.7 / 13.7 (no grenade row);
     Replay 2026-04-29 02-04-58 kills 16.4 / 16.6 (no fake late kill); 2025.01.06 23.32.19 last kill 13.8 (not 15.0)
  g) (real data, on copies, ~3 min) guard: Valorant and R6S pools + events byte-identical to V8.1
python tests\\test_v811.py   (parts: V811_PARTS=0,1,2,3,r,g; V7_DATA_SRC = the montage_data to copy)"""
import copy
import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("t810", str(ROOT / "tests" / "test_v810.py"))
T10 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T10)
T = T10.T
M, check, section, TMP = T.M, T.check, T.section, T.TMP
from _run import run, require                                                                 # noqa: E402
PARTS = [x for x in os.environ.get("V811_PARTS", "0,1,2,3,r,g").split(",") if x]
REFS = ("V8.1", "main")


def part0():
    section("0) version + changelogs")
    check("APP_VERSION is V8.1.1", M.APP_VERSION == "V8.1.1")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.1.1 then V8.1", cl[0].startswith("## V8.1.1 ") and cl[1].startswith("## V8.1 "), str(cl[:2]))
    sm = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sh = [l for l in sm.splitlines() if l.startswith("## V")]
    check("Settings changelog: V8.1.1 'CS2 cuts land on the real kills, smoother slow-mo' first", sh[0] == "## V8.1.1 - 2026-10-15: CS2 cuts land on the real kills, smoother slow-mo", sh[0])
    check("Settings changelog: the old V8.1 entry is now V8.10, same headline", sh[1] == "## V8.10 - 2026-10-14: CS2 kills now found by the red border", sh[1])
    old = "- Every CS2 kill is now detected by the red border around your row in the killfeed\n- Misread names no longer create phantom kills or lose real ones\n" \
          "- Multikills and almost-aces show all their kills\n- Assists are no longer counted as kills\n- Valorant and R6S unchanged\n"
    check("the V8.10 entry text is unchanged", sm.split(sh[1] + "\n", 1)[1].startswith(old))
    check("the V8.1.1 entry has the 5 points", sm.split(sh[0] + "\n", 1)[1].startswith(
        "- Takes no longer start on grenade rows or skip the first real kill\n- No more long empty stretches after the last kill\n"
        "- Slow-mo and effects only play where a kill actually happens\n- Slow-motion looks smoother\n- Valorant and R6S unchanged\n"))


trk, cls = T10.trk, T10.cls


def part1():
    section("1) row identity")
    R = M._cs2_row_relation
    a, b = trk(1, 9.63, 9.9, 93, w=242, hits=4), trk(2, 10.87, 11.27, 93, w=249, hits=13)
    other = {"verdict": "other", "name_read": False, "vtext": "Le1t0", "ktext": "5ggcs.ru", "votes": [("other", 1, "", "5ggcs.ru", "Le1t0")] * 2}
    mine = {"verdict": "kill", "name_read": False, "vtext": "v2", "ktext": "firoaxo", "votes": [("kill?", 1, "", "firoaxo", "v2")] * 3}
    check("another player's row ('5ggcs.ru > Le1t0') never joins my row read only as 'firoaxo' (18.25.49)", R(a, b, other, mine, [a, b]) == "distinct")
    saved = M.CS2_ROWID_V811[0]
    try:
        M.CS2_ROWID_V811[0] = False
        check("switch off = V8.1 (the two joined)", R(a, b, other, mine, [a, b]) != "distinct")
    finally:
        M.CS2_ROWID_V811[0] = saved
    a, b = trk(1, 16.67, 21.33, 124, w=292), trk(2, 21.37, 21.4, 123, w=300, hits=2)
    check("a fragment lost for one frame and back in the same place is the same row", R(a, b, cls([]), cls([]), [a, b]) == "same")
    a, b = trk(1, 12.0, 13.0, 93, w=292), trk(2, 13.5, 15.0, 160, w=300)
    check("... but not when it comes back lower (a new row)", R(a, b, cls([]), cls([]), [a, b]) != "same")
    check("'+ sashadidntwakeup' (killer unread) is not read as another player's name: names_me helper sees the jumbled reads",
          M._cs2_names_me({"name_read": False, "votes": [("kill?", 1, "", "firoaxo", "v2")]}))
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("cs2_classify_track only calls a read 'other' when the part BEFORE '+' is a readable name",
          '_alnum((r.get("ktext") or "").split("+")[0] if CS2_ROWID_V811[0] else (r.get("ktext") or ""))' in src)


def frames_edge(scroll=False):
    """Synthetic killfeed frames (272 x 534): a textured row fades in at the bottom edge (cut by it) and later scrolls up."""
    import numpy as np
    import cv2
    rng = np.random.RandomState(3)
    tex = (rng.rand(20, 260) * 200 + 30).astype(np.uint8)
    out = []
    for f in range(70):
        fr = np.full((272, 534, 3), 90, np.uint8)
        if f >= 20:
            y = 250 if f < 50 else max(216, 250 - (f - 50) * 4)
            a = min(1.0, (f - 19) / 3.0)
            y0 = y
            fr[y0:min(272, y0 + 28), 255:529] = (20, 20, 40)
            band = fr[y0 + 4:min(272, y0 + 24), 262:522]
            t_ = cv2.cvtColor(tex[:band.shape[0], :band.shape[1]], cv2.COLOR_GRAY2BGR)
            band[:] = (a * t_ + (1 - a) * band).astype(np.uint8)
            cv2.rectangle(fr, (255, y0), (528, y0 + 27), (30, 30, 190), 2)
        out.append(fr)
    return out


def part2():
    section("2) dating + planner hooks")
    fr = frames_edge()
    rc = {"x0": 255, "x1": 528, "y0": 246, "y1": 273}             # first tracked at frame 51 (y 246, the list starts scrolling); 3 frames on it is at y 234
    j = M.cs2_dating_walk(fr, rc, 51, 30.0, (), {}, 234)
    check("a row first tracked while scrolling up, cut by the lower edge before: dated to its fade-in at the edge (frame 20-23)", j is not None and j >= 0 and 19 <= j <= 23, str(j))
    saved = M.CS2_EDGE_DATING[0]
    try:
        M.CS2_EDGE_DATING[0] = False
        j0 = M.cs2_dating_walk(fr, rc, 51, 30.0, (), {})
        check("switch off = V8.1 (not dated back to the edge)", j0 is None or j0 < 0 or j0 > 40, str(j0))
    finally:
        M.CS2_EDGE_DATING[0] = saved
    ev = {"times": [5.0, 9.0], "rows": [5.1, 9.1], "pre": 5.0, "post": 3.0, "death_after": None, "unsure": [False, True]}
    check("an event whose last kill time may be late is never the slow-mo ending", not M.ending_safe(ev))
    check("... and the same event without the flag can be", M.ending_safe({k: v for k, v in ev.items() if k != "unsure"}))
    check("first kill unsure: CS2_UNSURE_LEAD more run-in (within the footage)", abs(M._lead_min(dict(ev, unsure=[True, False])) - min(M.LEAD_MIN + M.CS2_UNSURE_LEAD, 5.0)) < 1e-9)
    check("no flag: the run-in minimum is unchanged", M._lead_min({"pre": 5.0}) == M.LEAD_MIN)
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("geom: no slow-mo / ending on an unsure last kill", 'if (slow or ending) and (ev.get("unsure") or [False])[-1]:' in src)
    check("geom: no slowed (fit) tail after an unsure last kill", 'D < _min_take_s(ev) or (ev.get("unsure") or [False])[-1]:' in src)
    check("zoom punches skip unsure kills without changing the random draws", "and rng.random() < rp[\"zoom_p\"] * 0.6 and not u2:" in src)


def part3():
    section("3) filter graphs vs V8.1 (synthetic plan with ramp + slow-mo)")
    B, ref = T10.T2.load_base(REFS)
    check(f"base module = {ref}", B.APP_VERSION == "V8.1", B.APP_VERSION)
    sp = TMP / "song.mp3"
    M.synth_song(sp, 128.0)
    an = M.analyse_song(str(sp), 128.0)
    keep = (M.clip_audio, B.clip_audio)
    M.clip_audio = B.clip_audio = lambda rec, *a, **k: {"stream": None, "lufs": None}
    try:
        evs = M.fake_events()
        song = {"path": str(sp), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
        res = {}
        for g in ("cs2", "valorant", "r6s"):
            for tag, mod in (("old", B), ("new", M)):
                cfg = dict(mod.DEFAULT_CONFIG)
                plan = mod.plan_montage(cfg, g, copy.deepcopy(evs), song, an, 2, "aggressive", "optimal", [], [])
                res[(g, tag)] = (repr(mod.build_filter(plan, cfg, False)), mod.fmt_plan(plan, copy.deepcopy(evs), {}, [], [], None), plan)
    finally:
        M.clip_audio, B.clip_audio = keep
    for g in ("valorant", "r6s"):
        check(f"{g}: filter graph identical to {ref}", res[(g, "old")][0] == res[(g, "new")][0])
        check(f"{g}: plan text identical to {ref}", res[(g, "old")][1] == res[(g, "new")][1])
    o, n = res[("cs2", "old")], res[("cs2", "new")]
    check("cs2: plan text identical (the synthetic events carry no uncertain kill)", o[1] == n[1])
    check("cs2: the plan has slow-mo pieces", any(0 < s[2] < 0.999 for t in n[2]["takes"] for s in t["segs"]))
    check("cs2: slowed pieces use motion interpolation", M.CS2_SLOW_INTERP in n[0])
    check("cs2: the graph equals V8.1 once the slowed pieces' filter is put back (normal-speed pieces untouched)",
          n[0].replace(M.CS2_SLOW_INTERP, "framerate=fps=60:scene=100") == o[0])


SCRIPT_R = r'''
import sys, json, os
sys.path.insert(0, os.getcwd())
import montage as M
from pathlib import Path
M.LOG_SINK[0] = lambda s: None
cfg = M.load_config()
det = M.Detector("cs2")
store = M.load_kills_cache()
res = {}
for r in M._cs2_recs(cfg, only_scanned=True, det=det):
    n = Path(r["path"]).name
    if any(k in n for k in ("2026.02.11 - 18.25.49", "Replay 2026-04-29 02-04-58", "2025.01.06 - 23.32.19", "2026.02.12 - 19.24")):
        a = M.analyse_clip_entry(r, store.get(M.kills_key(r, "cs2", det)), cfg, "cs2")
        res[n] = [k["t"] for k in a["kills"]]
json.dump(res, open(sys.argv[1], "w", encoding="utf-8"))
'''
EXPECT = {"2026.02.11 - 18.25.49": [10.87, 13.7], "Replay 2026-04-29 02-04-58": [16.4, 16.67], "2025.01.06 - 23.32.19": [1.43, 10.53, 12.03, 13.77],
          "2026.02.12 - 19.24": [4.8, 7.73, 13.63]}


def partr():
    section("r) the three problem clips of I_CS2_V8.1_2026-10-14 (+ 19.24), real data on a copy")
    d = T10.data_copy("r811")
    (TMP / "r811.py").write_text(SCRIPT_R, encoding="utf-8")
    o = TMP / "r811.json"
    res = run([sys.executable, str(TMP / "r811.py"), str(o)], text=True, cwd=ROOT, env=dict(os.environ, MONTAGER_DATA=str(d)), timeout=3600)
    ok, why = require(res, "CS2 run")
    check("the CS2 run finished", ok, why)
    if not ok:
        return
    j = json.loads(o.read_text(encoding="utf-8"))
    for k, ks in EXPECT.items():
        hit = [n for n in j if k in n]
        got = j[hit[0]] if hit else None
        check(f"{k}: kills {ks}", got is not None and len(got) == len(ks) and all(abs(a - b) <= 0.2 for a, b in zip(got, ks)), str(got and [round(x, 2) for x in got]))


def partg():
    section("g) guard: Valorant + R6S pools and events identical to V8.1")
    T10.REFS = REFS
    T10.partg()


if __name__ == "__main__":
    for k, fn in (("0", part0), ("1", part1), ("2", part2), ("3", part3), ("r", partr), ("g", partg)):
        if k in PARTS:
            try:
                fn()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                T.check(f"part {k} ran without an exception", False, repr(ex))
    print(f"\n{len(T.FAILS)} FAIL" if T.FAILS else "\nALL OK", f"({time.time() - T.T0:.1f} s)")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if T.FAILS else 0)
