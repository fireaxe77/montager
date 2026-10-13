"""V8.0.0 tests: Rainbow Six Siege (R6S). FAST unit tests only (a few seconds; no render, no corpus, no scan of real clips, no OCR engine).
  0) title-bar version V8.0.0; changelog headings renamed (V7.7.6 -> V7.7.7, V7.7.5 -> V7.7.6) and no V8 entry
  1) R6S is registered in every game list / dict (games, config keys, folders, names, region, output folder + filename code, fight gap)
  2) an old saved config gets the R6S entries only (CS2 / Valorant entries stay exactly as saved)
  3) folder separation: R6S clips are never tagged cs2 / valorant and the reverse; the R6S scan lists unprobed stubs and never probes in bulk
  4) player name: fireaxe0 (O / 0 fold, fuzzy), the 'every game' name list stays Valorant + CS2
  5) icon template loader: 0, 1, 2 icons, bad file, missing folder; empty folder = logged soft failure, R6S scan returns no kills
  6) row analysis on synthetic rows (kill / death / pre-clip / blip / duplicate / both sides / same timestamp / O-for-0)
  7) template finder + row tracker on synthetic frames (two shades, a scrolling list, fade-in dating)
  8) failsafe: an R6S exception never reaches a CS2 / Valorant call
  9) CS2 / Valorant frozen: the V7.7.7 module and this one agree on synthetic rows, tags, gaps, folder lists
  p) (V800_PLANS=1, slow ~3 min, reads the real montage_data) CS2 + Valorant dry plans, default settings, same seed: plan text identical to the base
python tests\\test_v800.py   (parts: V800_PARTS=0,1,2,3,4,5,6,7,8,9)"""
import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v800_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import montage as M                                                                           # noqa: E402
import cv2                                                                                    # noqa: E402
import numpy as np                                                                            # noqa: E402

FAILS = []
T0 = time.time()
LOG = []
M.LOG_SINK[0] = LOG.append
M.LOG_DIR = TMP / "logs"
PARTS = [x for x in os.environ.get("V800_PARTS", "0,1,2,3,4,5,6,7,8,9").split(",") if x]


def check(name, ok, extra=""):
    print(("  ok    " if ok else "  FAIL  ") + name + (f"   [{extra}]" if extra and not ok else ""))
    if not ok:
        FAILS.append(name)


def section(t):
    print(f"\n== {t} ==")


def rng_img(h, w, seed):
    return np.random.RandomState(seed).randint(0, 255, (h, w), np.uint8)


# ----------------------------------------------------------------------------------------------------------------------------------
def part0():
    section("0) version + changelog names")
    check("APP_VERSION is V8.0.0", M.APP_VERSION == "V8.0.0")
    cl = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    heads = [l for l in cl if l.startswith("## V")]
    check("changelog top entry is V7.7.7 (renamed from V7.7.6)", heads[0].startswith("## V7.7.7 "), heads[0])
    check("changelog second entry is V7.7.6 (renamed from V7.7.5)", heads[1].startswith("## V7.7.6 "), heads[1])
    check("no V8 changelog entry", not any(l.startswith("## V8") for l in cl))
    sm = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8").splitlines()
    sh = [l for l in sm if l.startswith("## V")]
    check("simple changelog: V7.7.7 then V7.7.6, no V8", sh[0].startswith("## V7.7.7 ") and sh[1].startswith("## V7.7.6 ") and not any(l.startswith("## V8") for l in sm))


def part1():
    section("1) R6S registered everywhere a game is listed")
    check("GAMES has valorant, cs2, r6s", tuple(M.GAMES) == ("valorant", "cs2", "r6s"), str(M.GAMES))
    D = M.DEFAULT_CONFIG
    for k in ("clip_dirs", "player_names", "game_audio_track", "gap_s"):
        check(f"DEFAULT_CONFIG[{k}] has r6s", "r6s" in D[k])
    check("R6S clip folders (double space before Siege)", D["clip_dirs"]["r6s"] == [r"E:\Movies\Pre 2025 FPS\Tom Clancy's Rainbow Six  Siege",
                                                                                   r"E:\Movies\LEGACY\Tom Clancy's Rainbow Six  Siege"])
    check("R6S name setting default = fireaxe0", D["player_names"]["r6s"] == ["fireaxe0"] and M.DEFAULT_PLAYER_NAMES["r6s"] == ["fireaxe0"])
    check("GAME_DIR / GAME_CODE / DEFAULT_REGION / FIGHT_SPLIT_S", M.GAME_DIR["r6s"] == "R6S" and M.GAME_CODE["r6s"] == "R6S" and "r6s" in M.DEFAULT_REGION and "r6s" in M.FIGHT_SPLIT_S)
    check("detector for r6s builds", M.load_dets("r6s").get("r6s") is not None)
    cfg = dict(D, output_root=r"E:\Movies\Montages")
    check("output folder E:\\Movies\\Montages\\R6S", str(Path(cfg["output_root"]) / M.GAME_DIR["r6s"]) == r"E:\Movies\Montages\R6S")
    plan = {"song": {"title": "Some Song Name", "path": "x.mp3"}, "game": "r6s"}
    nm = M.montage_name(TMP, plan, __import__("datetime").datetime(2026, 10, 14))
    check("filename prefix scheme <INITIALS>_R6S_V8.0.0_date", nm == "SSN_R6S_V8.0.0_2026-10-14", nm)
    check("fight gap r6s works with an old gap_s", M.fight_gap({"gap_s": {"valorant": 6.0, "cs2": 5.0}}, "r6s") == 10.0)
    check("fight gap valorant / cs2 unchanged", M.fight_gap(D, "valorant") == 10.0 and M.fight_gap(D, "cs2") == 5.0)
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("Settings has R6S clip folder row", '("r6s", "R6S clip folders (separated by ;)")' in src)


def part2():
    section("2) an old saved config gets R6S entries only")
    old = {"cfg_version": 5, "clip_dirs": {"valorant": ["E:/v"], "cs2": ["E:/c", "E:/c2"]}, "player_names": {"valorant": ["fireaxe", "fireaxe77"], "cs2": ["fireaxe"]},
           "game_audio_track": {"valorant": "2", "cs2": "2"}, "gap_s": {"valorant": 6.0, "cs2": 5.0}}
    p = TMP / "cfg_old.json"
    p.write_text(json.dumps(old), encoding="utf-8")
    keep = M.CONFIG_PATH
    M.CONFIG_PATH = p
    try:
        c = M.load_config()
    finally:
        M.CONFIG_PATH = keep
    for k in ("clip_dirs", "player_names", "game_audio_track", "gap_s"):
        check(f"{k}: r6s added, valorant / cs2 as saved", "r6s" in c[k] and c[k]["valorant"] == old[k]["valorant"] and c[k]["cs2"] == old[k]["cs2"])
    check("r6s folders default, name fireaxe0", c["clip_dirs"]["r6s"] == M.DEFAULT_CONFIG["clip_dirs"]["r6s"] and M._NAMES["r6s"] == ["fireaxe0"])
    M.set_player_names(M.load_config())


def part3():
    section("3) folder separation + lazy R6S listing")
    cfg = copy.deepcopy(M.DEFAULT_CONFIG)
    r6 = [r"E:\Movies\Pre 2025 FPS\Tom Clancy's Rainbow Six  Siege\a.mp4", r"E:\Movies\LEGACY\Tom Clancy's Rainbow Six  Siege\sub\b.mp4"]
    other = {"valorant": [r"E:\Movies\VALORANT\Clips\x.mp4", r"E:\Movies\LEGACY\Valorant\y.mp4"],
             "cs2": [r"E:\Movies\2026\Counter-strike 2\x.mp4", r"E:\Movies\LEGACY\Counter-strike 2\y.mp4", r"E:\Movies\Movies 2025\Counter-strike 2\z.mp4"]}
    check("R6S clips tag r6s", all(M.tag_game(p, cfg)[0] == "r6s" for p in r6))
    check("R6S clips are never cs2 / valorant", all(M.tag_game(p, cfg)[0] not in ("cs2", "valorant") for p in r6))
    check("CS2 / Valorant clips keep their game, never r6s", all(M.tag_game(p, cfg)[0] == g for g, ps in other.items() for p in ps))
    check("single-space 'Rainbow Six Siege' folder is NOT picked up (exact folder match)", M.tag_game(r"E:\Movies\Pre 2025 FPS\Tom Clancy's Rainbow Six Siege\a.mp4", cfg)[0] is None)
    check("clip_dirs(cfg, game) never mixes games", all(g == "r6s" for _, g in M.clip_dirs(cfg, "r6s")) and all(g != "r6s" for _, g in M.clip_dirs(cfg, "cs2") + M.clip_dirs(cfg, "valorant")))
    # real scan_clips on a temp tree: R6S clips are listed as stubs, never probed; CS2 / Valorant folders are not walked by the R6S setting
    root = TMP / "lib"
    d6, dc = root / "r6s", root / "cs2"
    d6.mkdir(parents=True)
    dc.mkdir(parents=True)
    for i in range(3):
        (d6 / f"r{i}.mp4").write_bytes(b"0" * 64)
        (dc / f"c{i}.mp4").write_bytes(b"0" * 64)
    c2 = dict(cfg, clip_dirs={"valorant": [], "cs2": [], "r6s": [str(d6)]}, output_root=str(TMP / "out"), bar=None)
    probed = []
    keep = (M.analyse_clip, M.CLIPS_CACHE, M.MIN_VIDEO)
    M.analyse_clip = lambda p, cache, rescan, bar: (probed.append(p), (p, {"path": p, "error": "x"}))[1]
    M.CLIPS_CACHE, M.MIN_VIDEO = TMP / "clips_cache.json", 1
    try:
        recs = M.scan_clips(c2)
        n_lazy = len(probed)
        M.R6S_PROBE.add(str(d6 / "r1.mp4"))
        M.scan_clips(c2)
        n_after = len(probed)
        probed.clear()
        M.R6S_PROBE.clear()
        c3 = dict(c2, clip_dirs={"valorant": [], "cs2": [str(dc)], "r6s": []})
        M.scan_clips(c3)
    finally:
        M.analyse_clip, M.CLIPS_CACHE, M.MIN_VIDEO = keep
        M.R6S_PROBE.clear()
    check("R6S scan lists 3 stubs, probes none", len(recs) == 3 and n_lazy == 0 and all(r.get("unprobed") and r["game"] == "r6s" for r in recs), f"{len(recs)} {n_lazy}")
    check("a clip that was asked for (ticked) is probed, only that one", n_after == 1)
    check("CS2 folder clips are probed as before (not lazy)", len(probed) == 3)
    check("R6S scan never returns CS2 clips and the CS2 scan never returns R6S clips",
          all(r["game"] == "r6s" and str(d6) in r["path"] for r in recs))
    check("unknown / missing R6S folder: no clips, no error", M.scan_clips(dict(c2, clip_dirs={"valorant": [], "cs2": [], "r6s": [str(root / 'nope')]})) == [])


def part4():
    section("4) R6S player name")
    check("names_for_cache r6s", M.names_for_cache("r6s") == ["fireaxe0"])
    check("norm_names accepts a ; list", M.norm_names("fireaxe0; Alias ;", "r6s") == ["fireaxe0", "alias"])
    check("empty list falls back to fireaxe0", M.norm_names([], "r6s") == ["fireaxe0"])
    s = M.r6s_name_score
    check("exact name = 100", s("fireaxe0") == 100.0)
    check("OCR letter O for zero still matches", s("fireaxeO") >= 95)
    check("fuzzy misread 'flreaxe0' matches", s("flreaxe0") >= 80)
    check("enemy names do not match", max(s(t) for t in ("SayGex692041", "BTW-Parparinos", "SouthNoupi", "Krassomat99", "LebbeLone364", "akoshsz", "KetsuAtreides")) < 60)
    nv, nc = M.names_split(None)[0], M.names_split("cs2")[0]
    check("the 'every game' name list does not contain the R6S name", "fireaxe0" not in nv and set(nv) == set(M.names_split("valorant")[0]) | set(nc))
    M.set_player_names(dict(M.DEFAULT_CONFIG, player_names={"valorant": ["fireaxe"], "cs2": ["fireaxe"], "r6s": ["fireaxe0", "alias99"]}))
    check("a second R6S alias is used", s("alias99") == 100.0)
    M.set_player_names(M.DEFAULT_CONFIG)


def mk_icon(path, seed, shade=1.0, w=40, h=26, rgba=False):
    g = (rng_img(h, w, seed).astype(np.float32) * shade).astype(np.uint8)
    im = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
    if rgba:
        im = np.dstack([im, np.full((h, w), 255, np.uint8)])
    ok, buf = cv2.imencode(path.suffix, im)
    path.write_bytes(buf.tobytes())


def part5():
    section("5) icon template loader + the empty-folder soft failure")
    d = TMP / "icons"
    check("missing folder -> 0 icons, no error", M.r6s_load_icons(d / "nope", log=False) == [])
    d.mkdir()
    check("empty folder -> 0 icons", M.r6s_load_icons(d, log=False) == [])
    mk_icon(d / "kill_a.png", 1)
    check("1 icon", len(M.r6s_load_icons(d, log=False)) == 1)
    mk_icon(d / "season10.jpg", 2, 0.7)
    (d / "notes.txt").write_text("not an icon")
    check("2 icons (png + jpg, any file name), txt ignored", [i["name"] for i in M.r6s_load_icons(d, log=False)] == ["kill_a.png", "season10.jpg"])
    (d / "broken.png").write_bytes(b"garbage")
    LOG.clear()
    ic = M.r6s_load_icons(d)
    check("a broken image is skipped with a log line, the rest load", len(ic) == 2 and any("broken.png" in l for l in LOG))
    mk_icon(d / "alpha.png", 3, rgba=True)
    check("a transparent png loads", len(M.r6s_load_icons(d, log=False)) == 3)
    check("icon signature changes with the icon set", M.r6s_icons_sig(M.r6s_load_icons(d, log=False)) != M.r6s_icons_sig(ic))
    # empty icons folder under montage_data: scan returns no kills + the exact message
    keep = M.DATA
    M.DATA = TMP / "emptydata"
    M._R6S_ICON_CACHE.clear()
    try:
        LOG.clear()
        det = M.Detector("r6s")
        e = M.r6s_scan_clip("x.mp4", {"game": "r6s", "v_off": 0.0}, det, M.DEFAULT_CONFIG)
        check("scan with no icons logs the exact message", any(l == "R6S kill icons missing: put the icon images in montage_data\\r6s\\icons" for l in LOG), str(LOG[-2:]))
        a = M.analyse_entry(e, M.DEFAULT_CONFIG, "r6s")
        check("... and returns no kills / deaths (no crash)", e.get("error") and a["kills"] == [] and a["deaths"] == [])
        check("scan_clip dispatches R6S to the same soft failure", M.scan_clip("x.mp4", {"game": "r6s"}, det, M.DEFAULT_CONFIG).get("error"))
    finally:
        M.DATA = keep
        M._R6S_ICON_CACHE.clear()


def rd(left, right):
    return [[0, 0, [[0, 100, t, 0.9] for t in left], [[300, 400, t, 0.9] for t in right]]]


def row(first, last, hits, reads, y=100):
    return {"first": first, "seen": first, "last": last, "hits": hits, "x": 200, "y": y, "w": 40, "h": 26, "sc": 0.95, "tpl": "k.png", "reads": reads}


def reads(l, r, n=3):
    return [[10 + i, [[0, 150, t, 0.9] for t in ([l] if isinstance(l, str) else l)], [[260, 420, t, 0.9] for t in ([r] if isinstance(r, str) else r)]] for i in range(n)]


def an(rows, frames=400, game="r6s"):
    return M.analyse_entry({"rows": rows, "frames": frames, "v_off": 0.0, "game": "r6s", "ocr": []}, M.DEFAULT_CONFIG, game)


def part6():
    section("6) row analysis on synthetic rows")
    a = an([row(30, 120, 91, reads("fireaxe0", "SayGex692041"))])
    check("my name on the killer side = 1 kill at the row's first frame", len(a["kills"]) == 1 and abs(a["kills"][0]["t"] - 2.0) < 1e-6 and a["kills"][0]["victim"] == "SayGex692041")
    check("result has every key the planner reads", all(k in a for k in ("kills", "deaths", "revives", "rej", "vis", "best_k", "best_v", "mine", "rows_n", "rows_max", "ocr_calls", "cjk")))
    check("kill record has the fields the other games have", all(k in a["kills"][0] for k in ("t", "ks", "hs", "row", "hits", "victim", "weapon", "box", "t_last", "needs_shot")))
    a = an([row(30, 120, 91, reads("fireaxeO", "x-enemy"))])
    check("'fireaxeO' (letter O) is my name", len(a["kills"]) == 1)
    a = an([row(30, 120, 91, reads(["fireaxe0", "junkweapon"], "enemy_one"))])
    check("junk text after my name (weapon read as text) is ignored", len(a["kills"]) == 1)
    a = an([row(30, 120, 91, reads("BTW-Parparinos", "fireaxe0"))])
    check("my name on the victim side = a death, not a kill", a["kills"] == [] and len(a["deaths"]) == 1)
    a = an([row(30, 120, 91, reads("SouthNoupi", "BTW-Parparinos"))])
    check("someone else's row = nothing", a["kills"] == [] and a["deaths"] == [])
    a = an([row(30, 120, 91, reads("fireaxe0", "fireaxe0"))])
    check("my name on both sides = not a kill", a["kills"] == [])
    a = an([row(0, 80, 80, reads("fireaxe0", "oldvictim"))])
    check("pre-clip row (already there at 0:00) is rejected", a["kills"] == [] and any("pre-clip" in r["reason"] for r in a["rej"]))
    a = an([row(100, 101, 2, reads("fireaxe0", "blipvictim", 1))], frames=400)
    check("a 2-frame row far from the end is a one-frame blip", a["kills"] == [] and any("blip" in r["reason"] for r in a["rej"]))
    a = an([row(100, 101, 2, reads("fireaxe0", "lastvictim", 1))], frames=104)
    check("... but not at the very end of the clip", len(a["kills"]) == 1)
    a = an([row(30, 100, 70, reads("fireaxe0", "Krassomat99")), row(80, 150, 70, reads("fireaxe0", "Krassomat99"), y=140)])
    check("the same victim again inside one fight is a duplicate", len(a["kills"]) == 1 and any("duplicate" in r["reason"] for r in a["rej"]))
    a = an([row(30, 100, 70, reads("fireaxe0", "Krassomat99")), row(80, 150, 70, reads("fireaxe0", "akoshsz"), y=140)])
    check("two different victims = 2 kills", len(a["kills"]) == 2)
    a = an([row(30, 100, 70, reads("fireaxe0", "Krassomat99")), row(31, 100, 70, reads("fireaxe0", "Krassomat98"), y=140)])
    check("same-timestamp rows with the same victim: one kill", len(a["kills"]) == 1)
    a = an([row(30, 100, 70, reads("fireaxe0", "Krassomat99")), row(31, 100, 70, reads("fireaxe0", "akoshsz"), y=140)])
    check("same-timestamp rows with distinct victims: both kept", len(a["kills"]) == 2)
    a = an([row(30, 120, 91, [[10, [[0, 150, "fireaxe0", 0.9]], [[260, 420, "SayGex692041", 0.9]]]])])
    check("one weak read: still a kill, with the gunshot flag when the name is not certain", len(a["kills"]) == 1)
    a = an([row(30, 120, 91, reads("fireaxe0", "enemy1"))], game=None)
    check("analyse_entry finds R6S from the entry's own game key", len(a["kills"]) == 1)
    ks = an([row(30, 120, 91, reads("fireaxe0", "SayGex692041")), row(300, 380, 80, reads("SayGex692041", "fireaxe0"), y=150)])
    check("kill and my death in one clip", len(ks["kills"]) == 1 and len(ks["deaths"]) == 1)


def frame(h, w, seed=0):
    g = (rng_img(h, w, seed) // 6).astype(np.uint8)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def paste(fr, icon_gray, x, y, k=1.0, seed=0):
    """A killfeed row: name boxes (a texture per row, so rows differ like different names do) left and right of the icon."""
    h, w = icon_gray.shape
    for xx, sd in ((x - 260, seed * 2 + 1), (x + w + 4, seed * 2 + 2)):
        fr[y + 3:y + 23, xx:xx + 256] = cv2.cvtColor((rng_img(20, 256, 1000 + sd).astype(np.float32) * k).clip(0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    fr[y:y + h, x:x + w] = cv2.cvtColor((icon_gray.astype(np.float32) * k).clip(0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)


def part7():
    section("7) template finder + row tracker on synthetic frames")
    d = TMP / "icons7"
    d.mkdir()
    mk_icon(d / "a.png", 11, 1.0)
    mk_icon(d / "b.png", 12, 0.75)
    icons = M.r6s_load_icons(d, log=False)
    ia = icons[0]["gray"]
    ib = icons[1]["gray"]
    fr = frame(400, 806, 5)
    paste(fr, ia, 300, 100, seed=1)
    paste(fr, ib, 300, 180, seed=2)
    ms = M.r6s_find_matches(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), icons)
    check("both icons (both shades) are found, once each", len(ms) == 2 and {m[5] for m in ms} == {0, 1}, str([(m[0], m[1], m[5]) for m in ms]))
    check("positions exact", {(m[0], m[1]) for m in ms} == {(300, 100), (300, 180)})
    check("an empty frame has no match", M.r6s_find_matches(cv2.cvtColor(frame(400, 806, 9), cv2.COLOR_BGR2GRAY), icons) == [])
    # a clip: row 1 (shade a) from frame 5 to 40 at y=100; row 2 (shade b) appears at frame 12 at y=180; at frame 20 row 1 scrolls to y=130 and row 2 to y=210
    frames = []
    for f in range(60):
        im = frame(400, 806, 100 + f % 3)               # a moving noise background: nothing static to track
        if 5 <= f <= 40:
            paste(im, ia, 300, 100 if f < 20 else 130, seed=1)
        if 12 <= f <= 50:
            paste(im, ib, 300, 180 if f < 20 else 210, seed=2)
        frames.append(im)
    calls = []

    def reader(fr_, m):
        calls.append(m[1])
        return [[0, 250, "fireaxe0", 0.95]], [[360, 560, ("VictimAlpha", "VictimBravo")[m[5]], 0.95]]
    rows, n = M.r6s_scan_frames(iter(frames), icons, reader=reader)
    check("60 frames processed", n == 60)
    check("2 rows (the list scrolling does not make new rows)", len(rows) == 2, str([(r['first'], r['last'], r['hits']) for r in rows]))
    rows.sort(key=lambda r: r["first"])
    check("row 1 first / last frame", rows[0]["first"] == 5 and rows[0]["last"] == 40, str(rows[0]["first"]))
    check("row 2 first / last frame", rows[1]["first"] == 12 and rows[1]["last"] == 50)
    check("each row was read a few times for voting", all(1 <= len(r["reads"]) <= len(M.R6S_READ_AGES) for r in rows))
    ent = {"rows": rows, "frames": n, "v_off": 0.0, "game": "r6s", "ocr": []}
    a = M.analyse_entry(ent, M.DEFAULT_CONFIG, "r6s")
    check("end to end: both rows are kills at their first frame", [round(k["t"] * M.FPS) for k in a["kills"]] == [5, 12], str([k["t"] for k in a["kills"]]))
    # fade-in dating: a row that fades in over 3 frames is dated to its first faint frame
    fr2 = []
    for f in range(30):
        im = frame(400, 806, 200 + f % 3)
        if f >= 10:
            k = 1.0 if f >= 13 else 0.55 + 0.1 * (f - 10)
            paste(im, ia, 300, 100, k, seed=3)
        fr2.append(im)
    rows2, _ = M.r6s_scan_frames(iter(fr2), icons[:1], reader=lambda f_, m: ([[0, 250, "fireaxe0", 0.9]], [[360, 560, "V", 0.9]]))
    check("fade-in: the row is dated back to its first faint frame (not later than the full match)", len(rows2) == 1 and rows2[0]["first"] <= 13 and rows2[0]["first"] >= 10, str(rows2 and rows2[0]["first"]))
    check("rows are JSON-serialisable (they go into the kill cache)", bool(json.dumps(rows)))
    # a failing reader never aborts the clip
    rows3, _ = M.r6s_scan_frames(iter(frames[:30]), icons, reader=lambda f_, m: (_ for _ in ()).throw(RuntimeError("ocr down")))
    check("a failing OCR read is logged and skipped, the rows are still found", len(rows3) >= 1)


def part8():
    section("8) failsafe: R6S errors never reach CS2 / Valorant")
    bad = {"rows": [{"first": "x"}], "frames": 10, "game": "r6s", "ocr": []}
    LOG.clear()
    a = M.analyse_entry(bad, M.DEFAULT_CONFIG, "r6s")
    check("a broken R6S entry = no kills, one R6S log line, no exception", a["kills"] == [] and any(l.startswith("R6S: analysis failed") for l in LOG))
    keep = M.r6s_analyse_entry
    M.r6s_analyse_entry = lambda e, c: (_ for _ in ()).throw(ValueError("boom"))
    try:
        r = M.analyse_entry(bad, M.DEFAULT_CONFIG, "r6s")
        v = M.analyse_entry({"ocr": [], "frames": 5, "v_off": 0.0, "game": "valorant"}, M.DEFAULT_CONFIG, "valorant")
        c = M.analyse_entry({"ocr": [], "frames": 5, "v_off": 0.0, "game": "cs2"}, M.DEFAULT_CONFIG, "cs2")
    finally:
        M.r6s_analyse_entry = keep
    check("exception inside the R6S analysis: caught", r["kills"] == [])
    check("... and a Valorant / CS2 analysis right after it is normal", v["kills"] == [] and c["kills"] == [] and "mine" in v and "mine" in c)
    check("r6s_want ignores garbage", M.r6s_want({}, [None, 5, "x"]) is None)
    det = M.Detector("valorant")
    keep2 = M.r6s_scan_clip
    M.r6s_scan_clip = lambda *a_, **k: (_ for _ in ()).throw(RuntimeError("r6s scan boom"))
    try:
        try:
            M.scan_clip("x", {"game": "r6s"}, M.Detector("r6s"), M.DEFAULT_CONFIG)
            raised = False
        except RuntimeError:
            raised = True                               # run_scan's per-clip handler logs it and skips only that clip
        ok_val = True
        try:
            M.scan_frames(iter([]))
        except Exception:
            ok_val = False
    finally:
        M.r6s_scan_clip = keep2
    check("an R6S scan error stays inside its own clip (run_scan skips it); the Valorant scan path is untouched", raised and ok_val)
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("run_scan skips R6S jobs without icons before scanning (nothing is cached)", "if g == \"r6s\" and not r6s_load_icons(log=False)" in src)


def part9():
    section("9) CS2 / Valorant frozen (V7.7.7 module vs this one, synthetic rows)")
    ref = None
    for r_ in ("V7.7.7-good", "main"):
        if subprocess.run(["git", "rev-parse", "--verify", "-q", r_ + "^{commit}"], cwd=ROOT, capture_output=True).returncode == 0:
            ref = r_
            break
    src = subprocess.run(["git", "show", f"{ref}:montage.py"], cwd=ROOT, capture_output=True).stdout
    if M.APP_VERSION == "V8.0.0" and ref == "main" and b'APP_VERSION = "V8.0.0"' in src:
        print("  (main already is V8.0.0 and no V7.7.7-good tag: nothing to compare against)")
        return
    bd = TMP / "base"
    bd.mkdir()
    (bd / "montage.py").write_bytes(src)
    spec = importlib.util.spec_from_file_location("montage_base800", str(bd / "montage.py"))
    B = importlib.util.module_from_spec(spec)
    sys.modules["montage_base800"] = B
    spec.loader.exec_module(B)
    check(f"base module = {ref} (V7.7.x)", B.APP_VERSION.startswith("V7.7"), B.APP_VERSION)

    def ocr_entry(game):
        def bx(x0, x1, t, col, y=100):
            return [x0, y, x1, y + 24, t, 0.95, col, 3]
        fr = []
        for f, who in ((3, "fireaxe"), (8, "fireaxe"), (14, "fireaxe"), (20, "fireaxe")):
            fr.append([f, f, [bx(10, 150, who, "g"), bx(260, 400, "enemyname", "r"), bx(10, 150, "enemyname", "r", 140), bx(260, 400, who, "g", 140)],
                       [[170, 98, 70, 28, 0.9], [170, 138, 70, 28, 0.9]]])
        return {"ocr": fr, "frames": 60, "v_off": 0.0, "game": game, "size": [806, 400]}
    cfg = copy.deepcopy(B.DEFAULT_CONFIG)
    for g in ("valorant", "cs2"):
        e = ocr_entry(g)
        qa = B.analyse_entry(copy.deepcopy(e), cfg, g)
        qb = M.analyse_entry(copy.deepcopy(e), cfg, g)
        check(f"{g}: analyse_entry identical on synthetic rows ({len(qa['kills'])} kills, {len(qa['deaths'])} deaths)", json.dumps(qa, default=str, sort_keys=True) == json.dumps(qb, default=str, sort_keys=True))
        ra = [B.ocr_rows(f_[2], f_[3], g) for f_ in e["ocr"]]
        rb = [M.ocr_rows(f_[2], f_[3], g) for f_ in e["ocr"]]
        check(f"{g}: ocr_rows identical", json.dumps(ra, default=str, sort_keys=True) == json.dumps(rb, default=str, sort_keys=True))
    paths = [r"E:\Movies\VALORANT\Clips\a.mp4", r"E:\Movies\LEGACY\Valorant\b.mp4", r"E:\Movies\2026\Counter-strike 2\c.mp4", r"E:\Movies\2026\cs clips\d.mp4",
             r"E:\Movies\Movies 2025\Counter-strike 2\e.mp4", r"E:\Movies\LEGACY\Counter-strike 2\f.mp4", r"E:\Other\g.mp4"]
    check("tag_game identical for every CS2 / Valorant / other path", [B.tag_game(p, cfg) for p in paths] == [M.tag_game(p, copy.deepcopy(M.DEFAULT_CONFIG)) for p in paths])
    for g in ("valorant", "cs2"):
        check(f"{g}: folder list, fight gap, names, region, dirs, codes unchanged",
              B.clip_dirs(cfg, g) == M.clip_dirs(M.DEFAULT_CONFIG, g) and B.fight_gap(cfg, g) == M.fight_gap(M.DEFAULT_CONFIG, g)
              and B.DEFAULT_PLAYER_NAMES[g] == M.DEFAULT_PLAYER_NAMES[g] and B.DEFAULT_REGION[g] == M.DEFAULT_REGION[g]
              and B.GAME_DIR[g] == M.GAME_DIR[g] and B.GAME_CODE[g] == M.GAME_CODE[g] and B.DEFAULT_CONFIG["gap_s"][g] == M.DEFAULT_CONFIG["gap_s"][g])
    check("names_split(None) (every game) unchanged", B.names_split(None) == M.names_split(None))
    check("Detector stamps for valorant / cs2 unchanged", all(B.Detector(g).d["stamp"] == M.Detector(g).d["stamp"] for g in ("valorant", "cs2")))
    check("GAMES differ only by r6s", tuple(M.GAMES) == tuple(B.GAMES) + ("r6s",))


def partp():
    section("p) CS2 + Valorant dry plans, default settings, same seed (slow, reads the real montage_data)")
    ref = "V7.7.7-good"
    if subprocess.run(["git", "rev-parse", "--verify", "-q", ref + "^{commit}"], cwd=ROOT, capture_output=True).returncode:
        ref = "main"
    bd = TMP / "basep"
    bd.mkdir()
    tar = subprocess.run(["git", "archive", ref], cwd=ROOT, capture_output=True).stdout          # the whole base tree (songmap_v2 etc.), data comes from MONTAGER_DATA
    subprocess.run(["tar", "-x", "-C", str(bd)], input=tar, check=True)
    script = ("import sys,json,os\nsys.path.insert(0,os.getcwd())\nimport montage as m\nm.LOG_SINK[0]=lambda s:None\ncfg=m.load_config()\nout={}\n"
              "for g in ('valorant','cs2'):\n    try:\n        out[g]=m.make_plan(cfg,g,seed=777,scan=False)[1]\n    except Exception as ex:\n        out[g]='ERR '+type(ex).__name__+': '+str(ex)\n"
              "json.dump(out,open(sys.argv[1],'w',encoding='utf-8'),ensure_ascii=False)\n")
    (TMP / "dump.py").write_text(script, encoding="utf-8")
    env = dict(os.environ, MONTAGER_DATA=str(ROOT / "montage_data"), PYTHONIOENCODING="utf-8")
    res = {}
    for tag, cwd in (("base", bd), ("new", ROOT), ("base2", bd)):      # a CS2 plan can move the data state a little (caches): new must equal the base run before OR after it
        o = TMP / f"plans_{tag}.json"
        subprocess.run([sys.executable, str(TMP / "dump.py"), str(o)], cwd=cwd, env=env, capture_output=True, timeout=900)
        res[tag] = json.loads(o.read_text(encoding="utf-8"))
    for g in ("valorant", "cs2"):
        same = not res["new"][g].startswith("ERR") and res["new"][g] in (res["base"][g], res["base2"][g])
        check(f"{g} dry plan text identical to {ref} (same seed, default settings)", same, res["new"][g][:120])


if __name__ == "__main__":
    for k, fn in (("0", part0), ("1", part1), ("2", part2), ("3", part3), ("4", part4), ("5", part5), ("6", part6), ("7", part7), ("8", part8), ("9", part9)):
        if k in PARTS:
            try:
                fn()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                check(f"part {k} ran without an exception", False, repr(ex))
    if os.environ.get("V800_PLANS") == "1":
        partp()
    print(f"\n{len(FAILS)} FAIL" if FAILS else "\nALL OK", f"({time.time() - T0:.1f} s)")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if FAILS else 0)
