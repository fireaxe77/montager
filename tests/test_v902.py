"""V9.0.2 tests (fast): Manual Sky colour / Font dropdowns, CS2 kill timing frame math, version.
  0) title-bar version V9.0.2, the version in the packaging / START_HERE, the V9.0.2 entry on top of both changelogs
  1) the dropdown entries: DEFAULT first, then every sky colour family / every intro font; manual_pick maps DEFAULT / unknown to None (= automatic)
  2) sky_family_for: DEFAULT gives exactly the automatic choice, a pick (plan or Manual context) replaces it
  3) plans: a Manual plan with DEFAULT = the automatic plan (identical JSON); a Font pick changes only the intro look (+ its colours), a Sky pick only the sky family;
     make_plan passes the picks to Manual plans only (Auto / weekly / Force New Full never see them) and stores the sky pick in the plan for the render
  4) frame math: a kill's source time -> its frame in the rendered video (intro, run-up ramp, stitched second clip, slow-mo), the same for CS2 and Valorant
  5) the Manual tab (needs a display): both dropdowns exist, DEFAULT pre-selected, a pick reaches the planner, the summary pin knows it
python tests\\test_v902.py   (parts: V902_PARTS=0,1,2,3,4,5)"""
import copy
import json
import os
import sys
import tempfile
import types
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="v902_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
warnings.simplefilter("ignore")
import montage as M                                                                          # noqa: E402
import intro90                                                                               # noqa: E402

PARTS = [x for x in os.environ.get("V902_PARTS", "0,1,2,3,4,5").split(",") if x]
FAILS = []


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def helpers():
    """the planner helpers of test_v842 (fake events, a song analysis) without loading a base version"""
    src = (HERE / "test_v842.py").read_text(encoding="utf-8")
    ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
    exec(compile(src[:src.index("def part0")], str(HERE / "test_v842.py"), "exec"), ns)
    return types.SimpleNamespace(**ns)


def part0():
    print("0) version, packaging, changelogs")
    check("APP_VERSION = V9.0.2", M.APP_VERSION == "V9.0.2", M.APP_VERSION)
    check("START_HERE names V9.0.2", (ROOT / "START_HERE.txt").read_text(encoding="utf-8").startswith("MONTAGER V9.0.2"))
    check("installer example names 9.0.2", "/DAppVersion=9.0.2 " in (ROOT / "packaging" / "montager.iss").read_text(encoding="utf-8"))
    check("release script example names v9.0.2", "(v9.0.2 for V9.0.2)" in (ROOT / "packaging" / "make_release.py").read_text(encoding="utf-8"))
    simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    check("Settings changelog: V9.0.2 on top of V9.0.1", 0 <= simple.index("## V9.0.2") < simple.index("## V9.0.1"))
    top = simple[simple.index("## V9.0.2"):simple.index("## V9.0.1")]
    check("Settings entry: plain points only (no KNOWN ISSUE / function names)", "KNOWN" not in top.upper() and "_" not in top and 1 <= top.count("\n- ") <= 4, top)
    check("CHANGELOG.md: V9.0.2 on top of V9.0.1", 0 <= tech.index("## V9.0.2") < tech.index("## V9.0.1"))


def part1():
    print("1) the dropdown entries")
    sky, font = M.manual_pick_choices("sky"), M.manual_pick_choices("font")
    check("Sky colour: DEFAULT first, then every sky colour family", sky == ["DEFAULT"] + list(M.SKY_FAMILIES), str(sky))
    check("Font: DEFAULT first, then the font of every intro look", font[0] == "DEFAULT" and len(font) == len(intro90.LOOKS) + 1 and len(set(font)) == len(font), str(font))
    keep = dict(M.MANUAL_PICK)
    try:
        check("DEFAULT is the pre-set value of both", keep == {"sky": "DEFAULT", "font": "DEFAULT"}, str(keep))
        check("DEFAULT = no pick", M.manual_pick("sky") is None and M.manual_pick("font") is None)
        M.MANUAL_PICK.update({"sky": "teal", "font": "Playfair Display"})
        check("a sky pick = that family, a font pick = the look that uses that font", M.manual_pick("sky") == "teal" and M.manual_pick("font") == "serif")
        ok = True
        for name in font[1:]:
            M.MANUAL_PICK["font"] = name
            lk = M.manual_pick("font")
            ok = ok and lk in intro90.LOOKS and intro90.FONT_NAMES[intro90.LOOKS[lk][0][0]] == name
        check("every font entry maps to the look that draws the title in it", ok)
        M.MANUAL_PICK.update({"sky": "nope", "font": "nope"})
        check("an unknown entry = the automatic choice", M.manual_pick("sky") is None and M.manual_pick("font") is None)
    finally:
        M.MANUAL_PICK.clear()
        M.MANUAL_PICK.update(keep)


def part2():
    print("2) sky colour family: DEFAULT = automatic, a pick replaces it")
    ok = True
    for ranked in (["hazy orange", "ember", "rose"], ["deep blue", "teal"], ["emerald", "violet"], ["white", "teal"]):
        auto = M.sky_family_for({"song": {"path": "nope.mp3", "title": "x"}}, ranked)
        M.INTRO_CTX.update({"sky_pick": None})
        dflt = M.sky_family_for({"song": {"path": "nope.mp3", "title": "x"}}, ranked)
        ok = ok and auto == dflt
    check("DEFAULT (no pick) gives the identical family and reason as before", ok)
    check("a pick stored in the plan is used (the render)", M.sky_family_for({"song": {"path": "nope.mp3"}, "pick_sky": "violet"}, ["hazy orange"])[0] == "violet")
    M.INTRO_CTX["sky_pick"] = "green"
    try:
        check("a pick in the Manual planning context is used (the intro colours)", M.sky_family_for({"song": {"path": "nope.mp3"}}, ["hazy orange"])[0] == "green")
    finally:
        M.INTRO_CTX["sky_pick"] = None
    check("a white pick is kept even where the automatic rule would replace it", M.sky_family_for({"song": {"path": "nope.mp3"}, "pick_sky": "white"}, ["white", "teal"],
                                                                                                     [{"info": None}] * 5)[0] == "white")


def part3():
    print("3) plans: DEFAULT identical, a pick changes only its own choice; Manual only")
    T = helpers()
    js = lambda p: json.dumps({k: v for k, v in p.items() if k != "notes"}, sort_keys=True, default=str)
    looks_seen, n_same = set(), 0
    for game, style, seed in (("cs2", "hype", 3), ("valorant", "chill", 7), ("r6s", "cinematic", 21), ("cs2", "aggressive", 11)):
        M.INTRO_CTX.update({"on": True, "text": None, "series": 1, "manual": False, "sky_pick": None, "font_pick": None})
        a, _ = T.mk(M, game, style, seed)
        M.INTRO_CTX.update({"manual": True, "text": None})
        b, _ = T.mk(M, game, style, seed)
        M.INTRO_CTX.update({"manual": False})
        if not a.get("intro"):
            check(f"{game} {style}: the fake plan has an intro to compare", False, "no intro")
            continue
        ia, ib = dict(a["intro"]), dict(b["intro"])
        ib["subline"] = ia["subline"]                     # a Manual intro has no 'SERIES #' subline (V9.0)
        same = js(dict(a, intro=None)) == js(dict(b, intro=None)) and ia == ib
        n_same += same
        check(f"{game} {style} seed {seed}: Manual with DEFAULT = the automatic plan (takes, intro look and colours)", same)
        pick = "serif" if a["intro"]["look"] != "serif" else "hype"
        M.INTRO_CTX.update({"manual": True, "font_pick": pick})
        c, _ = T.mk(M, game, style, seed)
        M.INTRO_CTX.update({"manual": False, "font_pick": None})
        looks_seen.add(c["intro"]["look"])
        rest_same = js(dict(b, intro=None)) == js(dict(c, intro=None))
        check(f"{game} {style}: a Font pick ({pick}) is applied and changes nothing else", c["intro"]["look"] == pick and rest_same,
              f"{c['intro']['look']} rest_same={rest_same}")
        M.INTRO_CTX.update({"manual": True, "font_pick": "shade", "sky_pick": "teal"})
        d, _ = T.mk(M, game, style, seed)
        M.INTRO_CTX.update({"manual": False, "font_pick": None, "sky_pick": None})
        check(f"{game} {style}: a Sky pick colours the sky-family look (shade) with that family", d["intro"]["look"] == "shade" and d["intro"]["family"] == "teal"
              and d["intro"]["pal"] == intro90.fam_palette("teal", M.SKY_FAMILIES, "shade"), str(d["intro"].get("family")))
    M.INTRO_CTX.update({"on": False, "text": None, "series": None, "manual": False, "sky_pick": None, "font_pick": None})
    # make_plan: what reaches the planner, and what the plan keeps for the render
    seen = []
    keep = (M._make_plan, M.series_next, dict(M.MANUAL_PICK))
    M._make_plan = lambda *a, **k: (seen.append(dict(M.INTRO_CTX)) or ({"takes": []}, "text"))
    M.series_next = lambda game, cfg: 5
    try:
        r0 = M.make_plan({}, "cs2", paths=["a.mp4"])
        check("Manual with DEFAULT: no pick reaches the planner, the plan gets no pick key", seen[-1]["sky_pick"] is None and seen[-1]["font_pick"] is None and "pick_sky" not in r0[0])
        M.MANUAL_PICK.update({"sky": "rose", "font": "Anton"})
        r1 = M.make_plan({}, "cs2", paths=["a.mp4"])
        check("Manual with picks: both reach the planner, the sky pick is stored in the plan", seen[-1]["sky_pick"] == "rose" and seen[-1]["font_pick"] == "ext" and r1[0].get("pick_sky") == "rose")
        r2 = M.make_plan({}, "cs2", paths=None)
        r3 = M.make_plan({}, "cs2", paths=None, full=True)
        check("Auto / weekly / Force New Full (no ticked clips): the dropdowns are never used", all(s_["sky_pick"] is None and s_["font_pick"] is None for s_ in seen[-2:])
              and "pick_sky" not in r2[0] and "pick_sky" not in r3[0])
        check("the context is cleared after each plan", M.INTRO_CTX.get("sky_pick") is None and M.INTRO_CTX.get("font_pick") is None)
    finally:
        M._make_plan, M.series_next = keep[0], keep[1]
        M.MANUAL_PICK.clear()
        M.MANUAL_PICK.update(keep[2])


def part4():
    print("4) frame math: kill source time -> frame of the rendered video")
    fps = M.OUT_FPS
    nf_i = int(round(M.INTRO_S * fps))
    # a take: 72 frames of run-up at 1.6x (source 10.0 .. 11.92), then 1.0x; a stitched second clip (event time = its own time + shift 15.0); a slow-mo piece at 0.5x
    segs = [[10.0, 11.92, 1.6, 72, 0], [11.92, 13.92, 1.0, 120, 0], [27.0, 28.0, 1.0, 60, 1], [28.0, 28.5, 0.5, 60, 1], [28.5, 29.0, 1.0, 30, 1]]
    cases = [(11.0, 37.5), (12.92, 132), (27.5, 222), (28.25, 282), (28.75, 327)]       # (kill source time, its frame inside the take)
    ok = all(abs(M.src_to_out(segs, k) * fps - f) < 1e-6 for k, f in cases)
    check("src_to_out: ramp, 1.0x, stitched second clip, slow-mo -> exact frames", ok, str([(k, M.src_to_out(segs, k) * fps) for k, _ in cases]))
    for game in ("cs2", "valorant"):
        p = {"game": game, "takes": [{"path": "C:/a.mp4", "srcs": [{"path": "C:/a.mp4", "shift": 0.0, "rect": [0, 0, 1920, 1080], "wh": [1920, 1080]},
                                                                    {"path": "C:/b.mp4", "shift": 15.0, "rect": [0, 0, 1920, 1080], "wh": [1920, 1080]}],
                                      "segs": segs, "kills": [k for k, _ in cases], "f0": 600, "nf": 342, "out_start": 10.0, "dur": 5.7}],
             "song": {"start_t": 20.0, "section_s": 60.0, "fade_out_start": 50.0}, "duration": 60.0, "total_frames": 3600,
             "intro": {"len": M.INTRO_S, "src_a": 2.0, "src_b": 9.0, "src_idx": 0}}
        r = M.with_intro(p)
        t = r["takes"][1]
        frames = [t["f0"] + M.src_to_out(t["segs"], k) * fps for k in t["kills"]]
        want = [nf_i + 600 + f for _, f in cases]
        song_ok = abs(float(r["song"]["start_t"]) + frames[1] / fps - (20.0 + (600 + 132) / fps)) < 1e-6
        check(f"{game}: render frame = intro frames + take start + frame inside the take; the song time of a kill is unchanged by the intro",
              all(abs(a - b) < 1e-6 for a, b in zip(frames, want)) and song_ok, str(frames))
    tk = p["takes"][0]
    file_t = [float(sg[0]) - float(M._src_of(tk, sg)["shift"]) for sg in segs]
    check("each piece is read from its own file at event time - that file's shift (the stitched clip from 12.0 s of b.mp4)",
          [round(x, 6) for x in file_t] == [10.0, 11.92, 12.0, 13.0, 13.5] and [M._src_of(tk, sg).get("path") for sg in segs][2] == "C:/b.mp4", str(file_t))


def part5():
    print("5) the Manual tab")
    import tkinter
    try:
        r_ = tkinter.Tk()
        r_.destroy()
    except Exception:                                                                        # noqa: BLE001
        check("a display for the window", False, "no display")
        return
    tmp = Path(tempfile.mkdtemp(prefix="v902ui_"))
    old = M.use_data_dir(tmp / "gdata")
    keep = dict(M.MANUAL_PICK)
    try:
        app = M.App(0, startup=False)
        for _ in range(3):
            app.root.update()
        sk, fo = app.named.get("Sky colour"), app.named.get("Font")
        check("both dropdowns exist in Manual", sk is not None and fo is not None)
        check("DEFAULT is first and pre-selected in both", list(sk.cget("values"))[0] == "DEFAULT" and list(fo.cget("values"))[0] == "DEFAULT"
              and app.m_pick["sky"].get() == "DEFAULT" and app.m_pick["font"].get() == "DEFAULT")
        check("they list the sky families / the intro fonts", list(sk.cget("values")) == M.manual_pick_choices("sky") and list(fo.cget("values")) == M.manual_pick_choices("font"))
        sig0 = app.pin_sig([])
        app.m_pick["sky"].set("blue")
        app.m_pick["font"].set("Oswald")
        for _ in range(3):
            app.root.update()
        check("a pick reaches the planner", M.manual_pick("sky") == "blue" and M.manual_pick("font") == "shade", str(M.MANUAL_PICK))
        check("the summary pin knows the picks (a change = a new plan)", app.pin_sig([]) != sig0)
        app.m_pick["sky"].set("DEFAULT")
        app.m_pick["font"].set("DEFAULT")
        app.root.update()
        check("back to DEFAULT = the automatic choice again", M.manual_pick("sky") is None and M.manual_pick("font") is None)
        app.root.destroy()
    finally:
        M.MANUAL_PICK.clear()
        M.MANUAL_PICK.update(keep)
        M.restore_data_dir(old)


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
    sys.exit(1 if FAILS else 0)
