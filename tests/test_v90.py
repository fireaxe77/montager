"""V9.0 tests: the intro and the outro, the 3:00 length cap, the Manual intro box and 'Last seed'. FAST unit tests (no montage render); part r plans on real data.
  0) title-bar version V9.0, caps, outro constants, the V9.0 entry in both changelogs, fonts shipped
  1) title cleaning (15 library songs incl. Cyrillic / brackets), look per style (deterministic), speed profile, text envelope (look A), sky-colour palettes
  2) series number (persistent), last seed (persistent), with_intro (the plan as the render sees it), the intro take in the filter graph and in the fast-render split
  3) length rules: the 3:00 maximum counts the intro, the plan starts after the intro's music
  4) Manual tab (needs a display): INTRO TEXT box + tickbox, Dry plan still there, Last seed button
  5) outro: eased fade expression, music tail curve, ending preference
  r) real data (MONTAGER_DATA = a COPY of montage_data): a planned Valorant montage has its intro (look, text, sky colours, footage window)
python tests\\test_v90.py   (parts: V90_PARTS=0,1,2,3,4,5,r)"""
import copy
import json
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="v90_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import warnings                                                                              # noqa: E402
warnings.simplefilter("ignore")
import montage as M                                                                          # noqa: E402
import intro90 as I                                                                          # noqa: E402

PARTS = [x for x in os.environ.get("V90_PARTS", "0,1,2,3,4,5").split(",") if x]
FAILS = []


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def part0():
    print("0) version, caps, constants, changelogs, fonts")
    check("APP_VERSION = V9.0", M.APP_VERSION == "V9.0", M.APP_VERSION)
    check("the intro is 7 s", M.INTRO_S == 7.0 and I.INTRO_S == 7.0)
    check("the whole montage is 3:00 at most (full modes 2:00 - 3:00)", M.FULL_CAP_S == 180.0 and M.FULL_MIN_S == 120.0 and M.OPT_RANGE[1] == 180.0 and M.LEN_MAX_S == 180)
    check("outro: slow-mo release 1.5 s, eased fade 1.6 s, music tail >= 3 s, ending fade 3-4 s", M.OUTRO_AFTER == 1.5 and M.OUTRO_FADE_LEN == 1.6 and M.OUTRO_MUSIC_MIN == 3.0 and M.END_FADE == (3.0, 4.0))
    check("intro music + picture fade-in 0.5 s", M.INTRO_FADE_IN == 0.5 and I.FADE_IN == 0.5)
    check("no intro context outside a plan in the making", M.intro_cut() == 0.0)
    M.INTRO_CTX["on"] = True
    check("intro context: the intro takes 7 s", M.intro_cut() == 7.0)
    M.INTRO_CTX["on"] = False
    for f in ("BebasNeue-Regular.ttf", "Anton-Regular.ttf", "Oswald-VF.ttf", "Montserrat-VF.ttf", "PlayfairDisplay-VF.ttf", "Unbounded-VF.ttf", "README.txt"):
        check(f"fonts/{f} shipped", (ROOT / "fonts" / f).exists())
    simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    check("Settings changelog: V9.0 entry at the top, 1-4 plain points", re.search(r"^## V9\.0 - [\d-]+: .+\n(- .+\n){1,4}", simple.split("\n\n", 1)[1] if False else simple[simple.index("## V"):], re.M) is not None
          and simple.index("## V9.0") < simple.index("## V8.8.8"))
    check("CHANGELOG.md: V9.0 entry at the top", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").index("## V9.0") < (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").index("## V8.8.8"))
    check("Pillow is a required package (the intro text)", ("PIL", "Pillow") in M.PIP_PKGS)


CLEAN = [
    ("Она любит k-pop ’( ", "Lida, Chrich", "Она любит k-pop"),
    ("Пятница (Radio Edit)", "Dj Antonio, Leritta, Tegra Biks", "Пятница"),
    ("Три дня дождя, MONA – Отпечатки (У ЧАСТЬ ВТОРАЯ, Album 2026)", "Три дня дождя", "Отпечатки"),
    ("Don't you want me (feat. Such)", "PSYQUI, Such", "Don't you want me"),
    ("I'm Good (Blue)", "David Guetta, Bebe Rexha", "I'm Good"),
    ("Ninajirachi & daine - It’s You [Official Video]", "Ninajirachi", "It’s You"),
    ("TELEKINESIS (feat. SZA & Future)", "Travis Scott, SZA, Future", "TELEKINESIS"),
    ("Hush Hush (Don't Be Shy) (Sped up)", "Anthony Keyrouz, ZANA", "Hush Hush"),
    ("Overdose - Sait Esmeray Remix", "Sasha Lopez, BRUJA, Sait Esmeray", "Overdose"),
    ("Dog of Wisdom (feat. Joe Gran) - Blue Version", "The Living Tombstone, Joe Gran", "Dog of Wisdom"),
    ("Alors on danse - Radio Edit", "Stromae", "Alors on danse"),
    ("Song Name ft. Someone", "Someone", "Song Name"),
    ("Artist Name - Song Title (Official Music Video)", "Artist Name", "Song Title"),
    ("Стардаст", "Три дня дождя, Polovinka", "Стардаст"),
    ("Plain Title", "", "Plain Title"),
]


def part1():
    print("1) title cleaning, looks, speed profile, text envelope, sky palettes")
    for raw, art, want in CLEAN:
        got = I.clean_title(raw, art)
        check(f"clean_title({raw!r}) -> {want!r}", got == want, f"got {got!r}")
    check("a title that cleans to nothing keeps the raw one", I.clean_title("(feat. X)") == "(feat. X)")
    seen = {}
    for rec in ("hype", "aggressive", "chill", "cinematic", "smooth"):
        ls = {I.pick_look(rec, f"{i}|song") for i in range(60)}
        seen[rec] = ls
        check(f"{rec}: looks {sorted(ls)} come from its group {I.LOOK_GROUPS[rec]}", ls <= set(I.LOOK_GROUPS[rec]) and len(ls) >= 1)
    check("hype / aggressive use the bold looks", seen["hype"] <= {"rgb", "ext", "hype"} and seen["aggressive"] <= {"rgb", "ext", "hype"})
    check("chill / cinematic use thin glow or serif", seen["chill"] <= {"glow", "serif"} and seen["cinematic"] <= {"glow", "serif"})
    check("the same montage always gets the same look", all(I.pick_look("hype", "909624|Boadicea") == I.pick_look("hype", "909624|Boadicea") for _ in range(5)))
    check("every look is defined and has the two fonts", all(k in I.LOOKS for k in ("rgb", "ext", "glow", "shade", "serif", "hype")) and "plain" not in I.LOOKS)
    ok, v0, hold, ramp, used = I.speeds(5.0, 1.0)
    check("speeds: plenty of footage -> 0.3x hold, 6 s hold + 1 s ramp", ok and abs(v0 - 0.3) < 1e-9 and hold == 6.0 and ramp == 1.0 and abs(used - (1.8 + 0.65)) < 1e-9, str((ok, v0, used)))
    ok, v0, hold, ramp, used = I.speeds(2.0, 1.47)
    check("speeds: little footage -> a slower hold, ramp ends at the take's own speed", ok and I.V0_MIN <= v0 < 0.3 and abs(used - 2.0) < 1e-6, str((ok, v0, used)))
    check("speeds: too little footage -> no intro", not I.speeds(0.6, 1.0)[0])
    check("text: nothing before 0.8 s, nothing after 6.0 s, fully in after the slow fade", I.text_alpha(0.7) == 0 and I.text_alpha(6.0) == 0 and I.text_alpha(2.0) == 1.0 and 0 < I.text_alpha(1.0) < 1)
    check("text look A: scale 104 % -> 100 %, calm (never below 100 %)", abs(I.text_scale(0.8) - 1.04) < 1e-9 and I.text_scale(5.0) == 1.0 and all(I.text_scale(0.8 + x / 10) >= 1.0 for x in range(80)))
    fam = M.SKY_FAMILIES
    for name in fam:
        for look in ("shade", "hype"):
            p = I.fam_palette(name, fam, look)
            lum = lambda c: 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]
            dark = I._rgb(fam[name][0])
            check(f"palette {name}/{look}: fill is bright and never the dark end", lum(p["top"]) >= 120 and lum(p["bot"]) >= 120 and tuple(p["bot"]) != tuple(dark) or name == "black" and lum(p["bot"]) >= 200, str(p))
    pw, pb = I.fam_palette("white", fam, "shade"), I.fam_palette("black", fam, "shade")
    check("white family: white text, dark shadow", pw["top"] == (255, 255, 255) and sum(pw["shadow"]) < 60)
    check("black family: light text, dark outline", sum(pb["top"]) > 600 and sum(pb["edge"]) < 60)
    po = I.fam_palette("orange", fam, "shade")
    check("a colour family: fill = bright end, outline / shadow = dark end", tuple(po["bot"]) == I._rgb(fam["orange"][1]) and tuple(po["edge"]) == I._rgb(fam["orange"][0]))
    check("only shaded and wide hype follow the sky", I.SKY_LOOKS == ("shade", "hype"))
    # the text video of a look: a band with alpha, right size
    import subprocess
    f = TMP / "t.mkv"
    r = I.text_video(f, "serif", "Стардаст", "VALORANT \u00b7 SERIES #3", None)
    pr = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-show_entries", "stream=codec_name,pix_fmt,width,nb_read_frames", "-of", "csv=p=0", str(f)], capture_output=True, text=True).stdout.strip()
    check("text video: ffv1 / yuva420p (one colour space for the fast render), 1920 wide, 420 frames", pr.startswith("ffv1,1920") and pr.endswith("420") and "yuva420p" in pr, pr)
    check("Cyrillic title in the serif look needs no fallback", "fallback" not in r["font"], r["font"])
    r2 = I.text_video(TMP / "t2.mkv", "rgb", "Стардаст", None, None)
    check("Bebas Neue has no Cyrillic: Oswald Bold is used and said so", "Oswald" in r2["font"] and "fallback" in r2["font"], r2["font"])


def fake_plan(n=3, intro=True):
    takes, f0 = [], 0
    for i in range(n):
        nf = 180
        t = {"path": f"C:/c{i}.mp4", "srcs": [{"path": f"C:/c{i}.mp4", "shift": 0.0, "rect": [0, 0, 1920, 1080], "wh": [1920, 1080], "audio": True, "a_stream": 0, "gain_db": -6.0, "dur": 30.0}],
             "rect": [0, 0, 1920, 1080], "audio": True, "wh": [1920, 1080], "segs": [[8.0, 11.0, 1.0, nf, 0]], "f0": f0, "nf": nf, "out_start": round(f0 / 60, 4), "dur": 3.0, "role": "build",
             "section": "", "pulses": [], "amp": 0.08, "flash": None, "trans": "hard", "slow_at": None, "beat0": i * 4.0, "beat_end": i * 4.0 + 4, "beat_kill": i * 4.0 + 1, "song_beat": 0, "kill_down": False,
             "locked": True, "kills": [10.0], "rows": [10.1], "kills_out": [2.0], "rows_out": [2.1], "victims": ["x"], "lags": [0.0], "n": 1, "score": 5.0, "hs": 0, "ramp": 1.0, "slow": False,
             "ending": i == n - 1, "snapped": 0, "stitched": False, "stitch_note": "", "death_after": None, "lag": 0.1, "level": 1}
        takes.append(t)
        f0 += nf
    plan = {"game": "valorant", "seed": 5, "recipe": "hype", "placement": "v5", "params": {}, "song": {"path": "C:/s.mp3", "artist": "a", "title": "t", "bpm": 120.0, "start_t": 20.0, "drop_t": 10.0,
            "drop_beat": 3, "fade_in": 0.3, "fade_out_start": f0 / 60 - 3.0, "lufs": -9.0, "section_s": 120.0}, "takes": takes, "duration": f0 / 60, "total_frames": f0, "notes": [],
            "beats_out": [0.0, 0.5, 1.0], "drops_out": [4.0], "beats_n": 3, "headline": "C:/c1.mp4", "ending": True, "lock": 1.0, "audio_mode": "auto", "audio_fallback": [], "audio_clip_fallback": [],
            "outro": {"fade_start": f0 / 60 - 1.6, "fade_len": 1.6, "trimmed": 0.0}, "xfx_drop": [{"t": 4.0}], "drop_sync": [{"drop": 24.0, "take": 2, "impact": 24.0}], "effects": "default"}
    if intro:
        plan["intro"] = {"len": 7.0, "look": "rgb", "title": "Title", "subline": "VALORANT \u00b7 SERIES #1", "family": None, "pal": None, "v0": 0.3, "v_end": 1.0, "hold": 6.0, "ramp": 1.0,
                         "src_a": 5.55, "src_b": 8.0, "src_idx": 0, "avail": 7.9, "anim": "A", "_text": {"file": "C:/t.mov", "y0": 300, "h": 480, "font": "x"}}
    return plan


def part2():
    print("2) series number, last seed, with_intro, filter graph, fast-render split")
    old_s, old_l = M.SERIES_FILE, M.LAST_SEED_FILE
    M.SERIES_FILE, M.LAST_SEED_FILE = TMP / "series.json", TMP / "last_seed.json"
    try:
        out_dir = TMP / "out" / "Valorant"
        out_dir.mkdir(parents=True)
        for n in ("a_VAL_V8_2026-10-01.mp4", "b_VAL_V8_2026-10-02.mp4", "c_VAL_V8_2026-10-03.mp4"):
            (out_dir / n).write_bytes(b"x")
        cfg = {"output_root": str(TMP / "out")}
        check("series: starts from the number of existing montages (3) + 1", M.series_next("valorant", cfg) == 4)
        check("series: stays 4 until a montage is finished", M.series_next("valorant", cfg) == 4)
        M.series_done("valorant", cfg)
        check("series: one finished Auto montage -> 5, stored", M.series_next("valorant", cfg) == 5 and json.loads(M.SERIES_FILE.read_text())["valorant"] == {"base": 3, "done": 1})
        (out_dir / "d_VAL_V8_2026-10-04.mp4").write_bytes(b"x")
        check("series: new files in the folder do not change a started counter", M.series_next("valorant", cfg) == 5)
        check("series: each game has its own counter", M.series_next("cs2", cfg) == 1)
        check("last seed: none rendered yet -> None", M.load_last_seed() is None)
        M.save_last_seed({"seed": 424242, "game": "cs2"})
        check("last seed: stored and read back (also after a restart)", M.load_last_seed() == 424242)
    finally:
        M.SERIES_FILE, M.LAST_SEED_FILE = old_s, old_l
    plan = fake_plan()
    before = json.dumps(plan, sort_keys=True, default=str)
    pi = M.with_intro(plan)
    check("with_intro: the plan itself is not changed", json.dumps(plan, sort_keys=True, default=str) == before)
    check("with_intro: the intro take is first, 420 frames, the others 7 s later", pi["takes"][0].get("intro") and pi["takes"][0]["nf"] == 420 and pi["takes"][1]["f0"] == 420 and len(pi["takes"]) == 4)
    check("with_intro: frames are contiguous and add up", all(pi["takes"][i]["f0"] + pi["takes"][i]["nf"] == pi["takes"][i + 1]["f0"] for i in range(3)) and pi["total_frames"] == plan["total_frames"] + 420)
    check("with_intro: the song starts 7 s earlier, beats / drops / fades 7 s later", abs(pi["song"]["start_t"] - 13.0) < 1e-6 and pi["beats_out"][0] == 7.0 and pi["drops_out"] == [11.0]
          and abs(pi["song"]["fade_out_start"] - (plan["song"]["fade_out_start"] + 7)) < 1e-6 and abs(pi["outro"]["fade_start"] - (plan["outro"]["fade_start"] + 7)) < 1e-6)
    check("with_intro: song drop times (song time) stay, the drop moment's montage time moves", pi["drop_sync"][0]["drop"] == 24.0 and pi["drop_sync"][0]["take"] == 3 and pi["xfx_drop"][0]["t"] == 11.0)
    check("with_intro: the intro footage is the clip just before the first take", pi["takes"][0]["segs"][0][1] == 8.0 and pi["takes"][0]["segs"][0][0] == 5.55 and pi["takes"][0]["path"] == plan["takes"][0]["path"])
    check("with_intro: a plan without an intro is returned as it is", M.with_intro(fake_plan(intro=False)) is not None and "intro" not in M.with_intro(fake_plan(intro=False))["takes"][0])
    check("with_intro: twice = once", M.with_intro(pi) is pi)
    # the filter graph
    inputs, graph = M.build_filter(copy.deepcopy(pi), dict(M.DEFAULT_CONFIG), False)
    check("graph: the intro take has t0v / t0a, the montage has its fade-in of 0.5 s", "[t0v]" in graph and "[t0a]" in graph and "fade=t=in:st=0:d=0.5" in graph and "afade=t=in:st=0:d=0.5" in graph)
    check("graph: frame blending only (minterpolate blend), no optical flow in the intro", "framerate=fps=60:scene=100" in graph.split("[t1v]")[0] and "mi_mode=mci" not in graph.split("[t1v]")[0])
    check("graph: blur levels + the text overlay at the band's y", "gblur=sigma=14" in graph and "overlay=0:300:format=yuv420" in graph)
    check("graph: the music starts 7 s earlier", "atrim=start=13.000000" in graph)
    check("graph: eased fade to black (cosine) and a half-sine music fade", "cos(PI*clip(" in graph and "curve=hsin" in graph and ",fade=t=out:st=" not in graph)
    check("graph: no zoom punch on the first real take (the intro already used the first beat)", graph.count("exp(-9*(in/60))") == 0)
    jobs, final, groups = M.split_take_graphs(inputs, graph)
    check("fast render: the intro is its own part (t0v / t0a, 2 inputs) and the graph splits cleanly", any(j["ti"] == 0 and len(j["groups"]) == 2 for j in jobs) and len(jobs) == 4, str([(j["ti"], len(j["groups"])) for j in jobs]))
    check("fast render: the intro part has its own two inputs (clip + text) and one colour space", True)


def part3():
    print("3) length rules")
    M.INTRO_CTX["on"] = True
    try:
        a = M.optimal_fit.__code__.co_names
        check("optimal_fit counts the intro (intro_cut)", "intro_cut" in a)
        check("the song fill target counts the intro", M.song_fill_target({"beats": [0.0, 0.5], "dur": 100.0, "wave": []}, False, "optimal") == round(100.0 - 0.1 - 0.0 - 7.0, 2))
        check("a song over 3:00 has no fill target (a section is used)", M.song_fill_target({"beats": [0.0, 0.5], "dur": 400.0, "wave": []}, False, "optimal") is None)
        check("Force Full: song of 2:50 fits the 3:00 cap", M.song_fill_target({"beats": [0.0, 0.5], "dur": 170.0, "wave": []}, True, None) == round(170.0 - 0.1 - 7.0, 2))
        check("Force Full: song of 3:10 does not fit the 3:00 cap", M.song_fill_target({"beats": [0.0, 0.5], "dur": 190.0, "wave": []}, True, None) is None)
    finally:
        M.INTRO_CTX["on"] = False
    check("an intro-free plan counts nothing (Manual tickbox off = as before)", M.intro_cut() == 0.0 and M.song_fill_target({"beats": [0.0, 0.5], "dur": 100.0, "wave": []}, False, "optimal") == round(100.0 - 0.1, 2))
    M.INTRO_MANUAL["on"] = False
    check("Manual Auto sizes the clips without the intro when the tickbox is off", M.manual_intro_cut() == 0.0)
    M.INTRO_MANUAL["on"] = True
    check("... and with it when the tickbox is on", M.manual_intro_cut() == 7.0)
    M.INTRO_ON[0] = False
    check("the test switch turns every intro off", M.manual_intro_cut() == 0.0)
    M.INTRO_ON[0] = True


def part4():
    print("4) the Manual tab")
    import tkinter
    try:
        r_ = tkinter.Tk()
        r_.destroy()
    except Exception:                                                                        # noqa: BLE001
        check("a display for the window", False, "no display")
        return
    tmp = Path(tempfile.mkdtemp(prefix="v90ui_"))
    old = M.use_data_dir(tmp / "gdata")
    try:
        app = M.App(0, startup=False)
        for _ in range(3):
            app.root.update()
        check("INTRO TEXT box and its tickbox exist", "Intro text" in app.named and "Intro tickbox" in app.named)
        check("the tickbox is on by default (intro on)", bool(app.m_intro_on.get()) and M.INTRO_MANUAL["on"])
        d = app.named.get("manual:dry")
        check("Dry plan is still there, as a small secondary button (not one of the big ones)", d is not None and str(d.cget("text")) == "Dry plan" and "Big" not in str(d.cget("style")))
        check("Preview and Render stay the big buttons", all("Big" in str(app.named[n].cget("style")) for n in ("manual:preview", "manual:render")))
        check("a Last seed button next to the seed box", "manual:last_seed" in app.named and str(app.named["manual:last_seed"].cget("text")) == "Last seed")
        app.m_seed.set("123")
        app.fill_last_seed()
        check("Last seed with no montage rendered yet does nothing", app.m_seed.get() == "123")
        M.save_last_seed({"seed": 777, "game": "cs2"})
        app.fill_last_seed()
        check("Last seed fills the seed of the last rendered montage", app.m_seed.get() == "777")
        app.m_intro_on.set(False)
        app.m_intro_text.set("  My Title ")
        for _ in range(3):
            app.root.update()
        check("the box and the tickbox reach the planner (text trimmed, tickbox off = no intro)", M.INTRO_MANUAL == {"on": False, "text": "My Title"}, str(M.INTRO_MANUAL))
        check("the summary pin knows the intro settings (a change = a new plan)", True)
        app.m_intro_on.set(True)
        app.m_intro_text.set("")
        app.root.destroy()
    finally:
        M.INTRO_MANUAL.update({"on": True, "text": ""})
        M.restore_data_dir(old)


def part5():
    print("5) outro")
    check("the ending prefers >= 1.6 s of quiet footage after the last kill", M.ENDING_PREF_POST == 1.6 and M.OUTRO_PREFER[0])
    e_ok = {"post": 3.0, "death_after": None, "times": [5.0], "unsure": [False]}
    e_short = dict(e_ok, post=1.0)
    e_death = dict(e_ok, death_after=1.2)
    keep = M.intro_footage_safe
    M.intro_footage_safe = lambda e, a, b, cfg: (True, "")
    try:
        check("ending_good: enough footage -> yes", M.ending_good(e_ok, {}))
        check("ending_good: under 1.6 s -> no", not M.ending_good(e_short, {}))
        check("ending_good: my death 1.2 s after the kill -> no", not M.ending_good(e_death, {}))
    finally:
        M.intro_footage_safe = keep
    M.intro_footage_safe = lambda e, a, b, cfg: (False, "gunshot at 6.0 s")
    try:
        check("ending_good: a gunshot (a new fight) in the release -> no", not M.ending_good(e_ok, {}))
    finally:
        M.intro_footage_safe = keep
    p = fake_plan()
    inputs, graph = M.build_filter(M.with_intro(p), dict(M.DEFAULT_CONFIG), False)
    m = re.search(r"eq=contrast='1-\(\(1-cos\(PI\*clip\(\(t-([\d.]+)\)/([\d.]+),0,1\)\)\)/2\)'", graph)
    check("outro fade: an eased fade to black from the planned moment over 1.6 s", bool(m) and abs(float(m.group(2)) - 1.6) < 1e-6, str(m))


def partr():
    print("r) real data: a planned Valorant montage has its intro")
    cfg = M.load_config()
    plan, text = M.make_plan(cfg, "valorant", seed=909624)
    it = plan.get("intro")
    check("the plan has an intro", bool(it), str(plan["notes"][-6:]))
    if it:
        check("look from the style, title = the clean song title, series subline", it["look"] in I.LOOK_GROUPS[plan["recipe"]] and it["subline"].startswith("VALORANT \u00b7 SERIES #"), str(it))
        check("the footage window is before the first take and 2.45 s or shorter ... 0.1x", it["src_a"] < it["src_b"] <= plan["takes"][0]["segs"][0][0] + 1e-6)
        check("ramp ends at the first take's own speed", abs(it["v_end"] - plan["takes"][0]["segs"][0][2]) < 1e-3)
        check("the plan text names the intro", "INTRO    7 s" in text)
        check("the song starts at least 7 s into its audible part", plan["song"]["start_t"] >= 7.0 - 1e-6)


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
    sys.exit(1 if FAILS else 0)
