"""V8.2 tests. FAST unit tests only (no real render, no corpus, no OCR engine).
  0) title-bar version + both changelogs
  1) R6S utility filter: the third icon (screenshot) matches in its own killfeed crop, the older icons do not match it; a row with a hit is rejected 'utility: ...'
     (REJECTED ROWS format of Valorant), the per-clip override admits it; a plain gun row is untouched; no generic small-icon rule
  2) jitter-free retime: 60 fps clips are retimed by frame number, other rates keep the old expression, the switch off = old graph; slow-mo uses the interpolator in every game
  3) per-game audio level: 0 = old gain, offsets add on top
  4) video-ready callback, Changelog button not in the disabled list, folder-scan memo
python tests\\test_v820.py   (parts: V820_PARTS=0,1,2,3,4)"""
import copy
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.argv = [sys.argv[0]]
import cv2  # noqa: E402
import montage as M  # noqa: E402

PARTS = [x for x in os.environ.get("V820_PARTS", "0,1,2,3,4").split(",") if x]
FAILS = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILS.append(name)


def section(t):
    print("\n" + t)


CFG = copy.deepcopy(M.DEFAULT_CONFIG)


def bx(x0, x1, t, col, y=100):
    return [x0, y, x1, y + 24, t, 0.95, col, 3]


def entry(util=None, victim="BuffSledge_25", frames=(30, 36, 42, 50, 60, 70, 80, 90)):
    ocr = [[f, f, [bx(10, 150, "fireaxeO", "g"), bx(340, 520, victim, "r")], [[170, 98, 70, 28, 0.9]]] for f in frames]
    return {"ocr": ocr, "rows": [], "frames": 200, "v_off": 0.0, "game": "r6s", "util": util or [], "util_sig": ""}


def hit(tpl="kill_gadget3.png"):
    return {"first": 28, "last": 95, "hits": 60, "x": 250, "y": 112, "w": 26, "h": 25, "sc": 1.0, "tpl": tpl}


def part0():
    section("0) version + changelog")
    check("APP_VERSION is V8.2", M.APP_VERSION == "V8.2")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.2 on top, then V8.1.1", cl[0].startswith("## V8.2") and cl[1].startswith("## V8.1.1"), str(cl[:2]))
    sm = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8").splitlines()
    sh = [l for l in sm if l.startswith("## V")]
    check("simple changelog: V8.2 headline on top", "Smoother cuts, utility kills filtered, faster rendering" in sh[0], str(sh[:2]))
    body = "\n".join(sm[sm.index(sh[0]):sm.index(sh[1])]).lower()
    check("simple entry: 7 plain points, no frame-check line", body.count("\n- ") == 7 and "checked against the plan" not in body, body)


def part1():
    section("1) R6S utility filter")
    feed = cv2.imread(str(ROOT / "tests" / "fixtures" / "r6s_gadget3_feed.png"))
    icon = ROOT / "tests" / "fixtures" / "r6s_gadget3_row.png"
    d = Path(tempfile.mkdtemp()) / "u"
    d.mkdir()
    check("empty folder -> no template", M.r6s_load_icons(d, log=False) == [])
    shutil.copy(icon, d / "third.png")
    t3 = M.r6s_load_icons(d, log=False)
    g = cv2.cvtColor(feed, cv2.COLOR_BGR2GRAY)
    m3 = M.r6s_find_matches(g, t3, M.R6S_SCALES, M.R6S_UTIL_THR)
    check("third icon matches its own killfeed crop (score >= 0.97)", bool(m3) and m3[0][4] >= 0.97, str(m3[:1]))
    older = [i for i in M.r6s_load_util_icons(log=False) if i["name"] != "kill_gadget3.png"]
    check("the older icons do NOT match the third (no generic small-icon rule)", not M.r6s_find_matches(g, older, M.R6S_SCALES, M.R6S_UTIL_THR))
    a = M.r6s_analyse_entry(entry([hit()]), CFG)
    check("row with the icon hit is rejected, no kill", not a["kills"] and any(r["reason"].startswith("utility:") for r in a["rej"]), str(a["rej"]))
    a0 = M.r6s_analyse_entry(entry([]), CFG)
    check("the same row without a hit is a kill", len(a0["kills"]) == 1, str(a0["rej"]))
    M._UTIL_LOCAL.on = True
    try:
        a1 = M.r6s_analyse_entry(entry([hit()]), CFG)
    finally:
        M._UTIL_LOCAL.on = False
    check("override admits it as a kill (util flag)", len(a1["kills"]) == 1 and a1["kills"][0].get("util"), str(a1["kills"]))
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("utilclip CLI takes --game r6s", '"--game", choices=("valorant", "r6s")' in src)


def part2():
    section("2) jitter-free retime + slow-mo for every game")
    seg = [[2.0, 3.0, 1.0, 60, 0], [3.0, 3.5, 0.5, 60, 0], [3.5, 5.5, 1.0, 120, 0]]
    plan = {"game": "valorant", "placement": "v5", "duration": 4.0, "song": {"path": "x.mp3", "start_t": 0.0, "fade_out_start": 3.0},
            "takes": [{"path": "a.mp4", "rect": [0, 0, 1920, 1080], "wh": [1920, 1080], "audio": False, "kills": [1.0], "kills_out": [1.0], "pulses": [], "amp": 0.08,
                       "trans": "hard", "flash": None, "nf": 240, "util": False, "out_start": 0.0, "f0": 0, "tail": None,
                       "srcs": [{"path": "a.mp4", "shift": 0.0, "rect": [0, 0, 1920, 1080], "wh": [1920, 1080], "audio": False, "a_stream": 0, "gain_db": -6.0}],
                       "segs": seg}]}
    M._FPS60_CACHE["a.mp4"] = True
    _i, g = M.build_filter(plan, CFG, False, M.FX_ALL)
    check("60 fps clip: frame-number retime", "setpts=STARTPTS+N/(60*TB),fps=60:start_time=0" in g, g[:400])
    check("slow-mo uses the interpolator (Valorant)", M.CS2_SLOW_INTERP in g)
    M._FPS60_CACHE["a.mp4"] = False
    _i, g2 = M.build_filter(plan, CFG, False, M.FX_ALL)
    check("other frame rate: old expression", "setpts=PTS/1.0000,fps=60:start_time=0" in g2 and "STARTPTS+N" not in g2)
    M._FPS60_CACHE["a.mp4"] = True
    M.JITTER_FREE[0] = False
    _i, g3 = M.build_filter(plan, CFG, False, M.FX_ALL)
    M.JITTER_FREE[0] = True
    check("switch off = old graph", g3 == g2)
    plan["game"] = "r6s"
    _i, g4 = M.build_filter(plan, CFG, False, M.FX_ALL)
    check("slow-mo uses the interpolator (R6S)", M.CS2_SLOW_INTERP in g4)
    M._FPS60_CACHE.pop("a.mp4", None)


def part3():
    section("3) per-game audio level")
    cfg = dict(CFG)
    check("no setting = 0 dB for every game", all(M.game_level_db(cfg, g) == 0.0 for g in M.GAMES))
    cfg["game_level_db"] = {"cs2": 3.0, "valorant": -4.0, "r6s": 99}
    check("offsets per game, clamped", M.game_level_db(cfg, "cs2") == 3.0 and M.game_level_db(cfg, "valorant") == -4.0 and M.game_level_db(cfg, "r6s") == M.GAME_LEVEL_RANGE[1])
    check("garbage setting = 0", M.game_level_db({"game_level_db": "oops"}, "cs2") == 0.0)


def part4():
    section("4) video-ready, buttons, scan memo")
    got = []
    M.VIDEO_READY[0] = got.append
    M.video_ready("x.mp4")
    M.VIDEO_READY[0] = lambda p: 1 / 0
    M.video_ready("x.mp4")
    M.VIDEO_READY[0] = None
    check("callback gets the path; a failing one is swallowed", got == [Path("x.mp4")])
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("Changelog button is not in the disabled-while-busy list", 'self.buttons.remove(self.named["Changelog"])' in src)
    i = src.index("video_ready(outfile)")
    check("run_job: Open video before the checks", i < src.index("quality_check(plan, outfile, cfg)", i))
    d = Path(tempfile.mkdtemp())
    (d / "sub").mkdir()
    cfg = dict(CFG, output_root=str(d / "out"))
    s1 = M._scan_signature(cfg, [str(d)])
    s2 = M._scan_signature(cfg, [str(d)])
    (d / "sub" / "new").mkdir()
    s3 = M._scan_signature(cfg, [str(d)])
    check("scan signature stable, changes when a folder appears", s1 is not None and s1 == s2 and s1 != s3)


for p in PARTS:
    globals()["part" + p]()
print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
