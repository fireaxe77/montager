"""V8.22 tests. FAST unit tests only (no render, no scan, no OCR).
  0) title-bar version V8.22; Settings changelog has the V8.22 entry on top of V8.21
  1) Songs list: 'Random pick' button selects one song from the list as shown (search filter), never plays or renders (needs a display)
  2) auto style: scoring still returns a known recipe + the 'AUTO STYLE' log text; a manual style still wins; an unknown style is not auto
  3) post-render checks toggle: default OFF, saved and loaded with the other settings (GUI round trip), run_job returns right after 'rendered <path>'
     when off and runs the quality / sync checks when on
  4) the 'PLAYLIST tracks with no MP3' block is gone from the plan text
python tests\\test_v822.py   (parts: V822_PARTS=0,1,2,3,4)"""
import inspect
import os
import random
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v822_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import montage as M                                                                           # noqa: E402

FAILS = []
PARTS = [x for x in os.environ.get("V822_PARTS", "0,1,2,3,4").split(",") if x]


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def part0():
    print("0) version + changelog")
    check(M.APP_VERSION == "V8.22", f"APP_VERSION {M.APP_VERSION}")
    txt = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    i22, i21 = txt.find("## V8.22"), txt.find("## V8.21")
    check(0 <= i22 < i21, "V8.22 entry sits above V8.21")
    ch = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    check(ch.find("## V8.22") != -1 and ch.find("## V8.22") < ch.find("## V8.21"), "CHANGELOG.md has V8.22 on top")


def part1():
    print("1) Random pick")
    old = M.use_data_dir(TMP / "d1")
    try:
        app = M.App(0, startup=False)
        try:
            check("songs:random_pick" in app.named, "the Random pick button exists next to Play selected song / Song map")
            check(app.named["songs:random_pick"].cget("text") == "Random pick", "button text is 'Random pick'")
            rows = [("a", "Alpha", ("", "", "", "")), ("b", "Bravo", ("", "", "", "")), ("c", "Charlie", ("", "", "", "")), ("d", "Delta", ("", "", "", ""))]
            for k in app.stree.get_children():
                app.stree.delete(k)
            for iid, txt, vals in [("auto", "Auto pick", ("", "", "", ""))] + rows:
                app.stree.insert("", "end", iid=iid, text=txt, values=vals)
            opened = []
            app.open_path = lambda p: opened.append(p)
            picks = set()
            for _ in range(60):
                app.random_song()
                sel = app.stree.selection()
                check(len(sel) == 1 and sel[0] != "auto", "exactly one real song selected") if len(picks) == 0 else None
                picks.add(sel[0])
            check(picks <= {"a", "b", "c", "d"} and len(picks) > 1, f"picks come from the list and vary: {sorted(picks)}")
            check(not opened, "nothing was played / opened")
            for k in ("b", "c", "d"):                              # search filter: only what is shown can be picked
                app.stree.detach(k)
            app.random_song()
            check(app.stree.selection() == ("a",), "only the shown (filtered) songs are picked")
            for k in ("a",):
                app.stree.detach(k)
            app.random_song()
            check(app.stree.selection() == (), "empty list (only Auto pick shown): nothing selected, no error")
        finally:
            app.root.destroy()
            M.LOG_SINK[0] = M.PROGRESS[0] = None
    finally:
        M.restore_data_dir(old)


def part2():
    print("2) auto style")
    an = {"bpm": 103, "drop_strength": 0.39, "drops": [], "steady": 0.64, "energy": [0.5] * 10}
    name, why = M.auto_style(an, {"energy": 0.87}, random.Random(1), None)
    check(name in M.RECIPES, f"auto pick is a known recipe ({name})")
    check(why.startswith(name) and "scores" in why and "BPM" in why, "the reason text keeps its numbers")
    n2, rp, why2 = M.pick_recipe(random.Random(1), "auto", None, an, {"energy": 0.87}, None)
    check(n2 in M.RECIPES and why2 and rp == M.RECIPES[n2], "pick_recipe(auto) returns recipe + reason")
    for st in ("hype", "chill", "aggressive", "smooth", "cinematic"):
        n3, rp3, w3 = M.pick_recipe(random.Random(2), st, None, an, {"energy": 0.87}, None)
        check(n3 == st and w3 == "", f"manual style {st} wins over auto")
    n4, rp4, w4 = M.pick_recipe(random.Random(2), "mix", None, an, {}, None)
    check(n4 == "mix", "mix still works")
    src = inspect.getsource(M.fmt_plan)
    check('AUTO STYLE {plan[\'recipe_why\']}' in src, "plan text still prints the AUTO STYLE line")
    bpm_hi = {"bpm": 170, "drop_strength": 0.5, "drops": [], "steady": 0.5, "energy": [0.9] * 10}
    check(M.auto_style(bpm_hi, {"energy": 0.95}, random.Random(3), None)[0] in ("aggressive", "hype"), "fast high-energy song stays aggressive / hype")


def part3():
    print("3) post-render checks toggle")
    check(M.DEFAULT_CONFIG.get("post_checks") is False, "default is OFF")
    src = inspect.getsource(M.run_job)
    i_off = src.find('if not cfg.get("post_checks", False)')
    i_q, i_s = src.find("quality_check(plan, outfile, cfg)"), src.find("sync_report(plan, outfile, cfg)")
    check(0 < i_off < i_q and i_off < i_s, "the off branch comes before the quality / sync checks")
    seg = src[i_off:i_q]
    check('out(f"rendered {outfile}")' in seg and "return outfile" in seg, "off: prints 'rendered <path>' and returns at once")
    check(src.find("video_ready(outfile)") < i_off, "the video is complete (Open video works) before the toggle is looked at")
    check(src.find("render_plan(plan, outfile, cfg, maxq, False, encoder, effects)") < i_off and src.find("audio_guard(") < i_off,
          "everything before the video is written is unchanged")
    old = M.use_data_dir(TMP / "d3")
    try:
        app = M.App(0, startup=False)
        try:
            check(app.set_post.get() is False, "Settings checkbox starts unticked")
            app.set_post.set(True)
            for _ in range(8):
                app.root.update()
                time.sleep(0.08)
            check(M.load_config().get("post_checks") is True, "ticked: saved to config.json and loaded again")
            app.set_post.set(False)
            for _ in range(8):
                app.root.update()
                time.sleep(0.08)
            check(M.load_config().get("post_checks") is False, "unticked: saved as off")
        finally:
            app.root.destroy()
            M.LOG_SINK[0] = M.PROGRESS[0] = None
    finally:
        M.restore_data_dir(old)


def part4():
    print("4) log cleanup")
    src = inspect.getsource(M.fmt_plan)
    check("PLAYLIST" not in src and "no MP3 yet" not in src, "fmt_plan has no 'PLAYLIST tracks with no MP3' block")
    check("no MP3 yet" not in (ROOT / "montage.py").read_text(encoding="utf-8"), "the text is nowhere in montage.py")


for p in PARTS:
    globals()["part" + p]()
print("\nFAILS:", len(FAILS))
for f in FAILS:
    print(" -", f)
sys.exit(1 if FAILS else 0)
