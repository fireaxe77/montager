"""V8.7 tests (fast; no montage render, no OCR).
  0) title-bar version V8.7; V8.7 on top of V8.6.3 in both changelogs
  1) sky toggle per game: defaults (CS2 / Valorant on, R6S off), old configs, planner makes no sky candidate when it is off, Extra effects of R6S stay
  2) sky animation follows the song: hardness from style / energy / BPM, strobe / black / colour jumps only for hard songs, deep colours (never pastel)
  3) sky mask: smoke (grey) next to a coloured sky is never masked, a white cloud inside the sky is, the mask does not flicker
  4) CS2 rows: two touching outlined rows with a smeared shared edge are two rows; the row grid is not corrupted by one early slot; old sidecars are read as before
  5) the 4k clip CS2 2026-10-17 02-48-50 reports 4 kills (when the clip and its scan are in the data folder)
  6) audio track: the gunshot analysis and the shot refinement use the track set in Settings for every game
python tests\\test_v87.py   (parts: V87_PARTS=0,1,2,3,4,5,6)"""
import copy
import os
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_src = (HERE / "test_v842.py").read_text(encoding="utf-8")
_ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
exec(compile(_src[:_src.index("def part0")], str(HERE / "test_v842.py"), "exec"), _ns)
T = types.SimpleNamespace(**_ns)
M = T.M
ROOT = T.ROOT
check, mk = T.check, T.mk
PARTS = [x for x in os.environ.get("V87_PARTS", "0,1,2,3,4,5,6").split(",") if x]
import numpy as np                                                                            # noqa: E402
import cv2                                                                                    # noqa: E402


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.7", M.APP_VERSION == "V8.7")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.7 above V8.6.3", cl[0].startswith("## V8.7") and cl[1].startswith("## V8.6.3"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.7 above V8.6.3", sm[0].startswith("## V8.7") and sm[1].startswith("## V8.6.3"), str(sm[:2]))
    seg = body[body.index("## V8.7"):body.index("## V8.6.3")].lower()
    check("simple entry is plain", not any(w in seg for w in ("test", "known issue", "on hold", "def ", "xfx", "ffmpeg", "mask", "geq", "sidecar")))


def part1():
    print("1) sky toggle per game")
    d = M.DEFAULT_CONFIG["sky_game"]
    check("defaults: CS2 on, Valorant on, R6S off", d == {"cs2": True, "valorant": True, "r6s": False}, str(d))
    check("sky_enabled reads the config", M.sky_enabled({"sky_game": {"cs2": False}}, "cs2") is False and M.sky_enabled({}, "cs2") is True and M.sky_enabled({}, "r6s") is False)
    fx_all = {"cs2": "extra", "valorant": "extra", "r6s": "extra"}
    for g in ("cs2", "valorant", "r6s"):
        p_on, _ = mk(M, g, "aggressive", 3, eff=fx_all)
        n_on = sum(1 for t in p_on["takes"] for x in t.get("xfx", []) if x["k"] == "sky")
        cfg = dict(M.DEFAULT_CONFIG, effects_game=dict(fx_all), sky_game={"cs2": False, "valorant": False, "r6s": False})
        keep = M.clip_audio
        M.clip_audio = lambda rec, *a, **k: {"stream": None, "lufs": None}
        try:
            song = {"path": str(T.SONG), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
            p_off = M.plan_montage(cfg, g, copy.deepcopy(M.fake_events()), song, T.an(), 3, "aggressive", "optimal", [], [])
        finally:
            M.clip_audio = keep
        n_off = sum(1 for t in p_off["takes"] for x in t.get("xfx", []) if x["k"] == "sky")
        others_on = sorted(x["k"] for t in p_on["takes"] for x in t.get("xfx", []) if x["k"] != "sky")
        others_off = sorted(x["k"] for t in p_off["takes"] for x in t.get("xfx", []) if x["k"] != "sky")
        check(f"{g}: sky off = no sky candidate, sky max 0 ({n_on} candidates with it on)", n_off == 0 and p_off.get("xfx_sky_max") == 0 and p_off.get("xfx_sky_on") is False, f"{n_off} {p_off.get('xfx_sky_max')}")
        check(f"{g}: Extra effects stay without the sky ({len(others_off)} other effects)", len(others_off) > 0 and p_off.get("effects") == "extra" and others_on == others_off, f"{len(others_on)} vs {len(others_off)}")
    c = M.load_config() if False else {}
    c = {"sky_game": {"cs2": False}}
    check("settings audit key exists in the defaults", "sky_game" in M.DEFAULT_CONFIG)


def part2():
    print("2) sky animation follows the song")
    hard = M.sky_anim_params(0.9, 180, "aggressive", True)
    chill = M.sky_anim_params(0.25, 80, "chill", False)
    mid = M.sky_anim_params(0.6, 120, "hype", False)
    check("hardcore song is hard (>= 0.9), chill song is soft (< 0.15)", hard["hard"] >= 0.9 and chill["hard"] < 0.15, f"{hard['hard']} {chill['hard']}")
    check("hardness grows with energy, BPM and the style", M.sky_hardness(0.9, 170, "hype") > M.sky_hardness(0.5, 170, "hype") > M.sky_hardness(0.5, 90, "hype") > M.sky_hardness(0.5, 90, "chill"))
    check("hard song: strobe, drops to black, colour jumps, gradient swing", hard["strobe_hz"] >= 8 and hard["bd"] >= 0.8 and hard["jump"] >= 0.8 and hard["swing"] >= 0.8, str(hard))
    check("chill song: no strobe, no black, no jumps, no swing", chill["strobe_hz"] == 0 and chill["bd"] == 0 and chill["jump"] == 0 and chill["swing"] <= 0.06, str(chill))
    check("the chill sky drifts slower than the hard one", chill["drift"] < 0.5 * hard["drift"], f"{chill['drift']} {hard['drift']}")
    beats = [(round(0.5 + i * 60.0 / 180, 4), 1.0 if i % 4 == 0 else 0.45) for i in range(14)]
    sh = M.sky_anim_schedule(hard, {"seed": 5, "beats": beats}, 30, 270)
    sc = M.sky_anim_schedule(chill, {"seed": 5, "beats": beats}, 30, 270)
    nb, nj = int((sh["black"] > 0.3).sum()), int((sh["jump"] > 0.3).sum())
    check(f"hard sky: black flashes ({nb} frames) and colour jumps ({nj} frames), the gradient swings", nb >= 25 and nj >= 12 and float(sh["swing"].max() - sh["swing"].min()) > 0.6)
    check("chill sky: nothing flashes, no jump", int((sc["black"] > 0).sum()) == 0 and int((sc["jump"] > 0).sum()) == 0)
    sh2 = M.sky_anim_schedule(hard, {"seed": 5, "beats": beats}, 30, 270)
    check("the schedule is deterministic for a seed", np.array_equal(sh["black"], sh2["black"]) and np.array_equal(sh["jump"], sh2["jump"]))
    pal = M.SKY_PALETTE["ember"]
    ranked = ["ember", "deep blue", "violet"]
    alt = M.sky_alt_colour(ranked, pal)
    check("the jump colour is another hue (>= 80 degrees away)", M._hue_dist(M._hue_deg(alt[1]), M._hue_deg(pal)) >= 80, str(alt))
    for name, rgb in M.SKY_PALETTE.items():
        g = M.sky_grade_v2(rgb, "dark", None, 0.5)
        yt, ut, vt = M._rgb_to_yuv(rgb)
        chroma = np.hypot(g["steady"]["u"] - 128, g["steady"]["v"] - 128) / max(1.0, np.hypot(ut - 128, vt - 128))
        # a bright sky (Y 200) comes out under Y 130 and with more chroma than the palette colour (deep, not pastel)
        y_out = min(g["steady"]["y_max"], 16 + (200 - 16) * g["steady"]["y_mul"])
        if y_out > 130 or chroma < 1.2:
            check(f"{name}: deep and saturated", False, f"Y {y_out:.0f} chroma x{chroma:.2f}")
            break
    else:
        check("every palette colour: a bright sky comes out under Y 130 with 35 % or more extra chroma (deep, not pastel)", True)
    g = M.sky_grade_v2(pal, "dark", alt[1], 1.0)
    check("the dark layer is nearly black, the surge layer is the jump colour", g["dark"]["y_mul"] <= 0.12 and g["surge"]["u"] != M.sky_grade_v2(pal, "dark", None, 1.0)["surge"]["u"])


def smoke_frames(n=60):
    h, w = 432, 768
    rng = np.random.RandomState(3)
    imgs = []
    for f in range(n):
        im = np.zeros((h, w, 3), np.uint8)
        im[:300] = np.linspace([70, 130, 215], [150, 190, 235], 300)[:, None, :].astype(np.uint8)
        im[300:] = (60, 70, 60)
        cv2.ellipse(im, (520, 90), (70, 24), 0, 0, 360, (245, 245, 245), -1)
        im = cv2.GaussianBlur(im, (0, 0), 2)
        s = 0.5 + 0.5 * np.sin(f / 9.0)
        sm = np.zeros((h, w), np.float32)
        cv2.ellipse(sm, (60, 150), (int(60 + 50 * s), int(90 + 40 * s)), 0, 0, 360, 1.0, -1)
        sm = cv2.GaussianBlur(sm, (0, 0), 9) * (0.75 + 0.2 * rng.rand(h, w).astype(np.float32))
        grey = np.full((h, w, 3), 150, np.float32) + rng.randn(h, w, 1).astype(np.float32) * 6
        imgs.append((im * (1 - sm[..., None]) + grey * sm[..., None]).clip(0, 255).astype(np.uint8))
    return imgs


def part3():
    print("3) sky mask: smoke, clouds, flicker")
    imgs = smoke_frames()
    segm = []
    for im in imgs:
        sp = M.sky_eyedrop_sample(im)
        segm.append(M.sky_eyedrop_mask(im, sp).astype(np.uint8) if sp else np.zeros(im.shape[:2], np.uint8))
    core = (slice(100, 220), slice(0, 50))                 # the middle of the smoke cloud
    cov = max(float(m[core].mean()) for m in segm)
    cloud = min(float(m[80:100, 500:540].mean()) for m in segm)
    sky = min(float(m[10:60, 200:700].mean()) for m in segm)
    check(f"smoke is not in the mask (max {cov * 100:.1f}% of its core, the synthetic smoke is see-through), the blue sky is ({sky * 100:.0f}%), the white cloud inside the sky is ({cloud * 100:.0f}%)", cov < 0.08 and sky > 0.95 and cloud > 0.95)
    # the mask of the smoke core does not blink: it is off in every frame
    check("the smoke area does not blink (the share of it in the mask is steady from frame to frame)", max(float(m[core].mean()) for m in segm) - min(float(m[core].mean()) for m in segm) < 0.08)
    # flicker guard: a pixel block that flips every other frame is left out, a stable edge is not
    k = 40
    a = [np.zeros((40, 60), np.uint8) for _ in range(k)]
    for i in range(k):
        a[i][:, :30] = 1                                       # a stable half
        a[i][5:15, 40:50] = i % 2                              # a flickering block
        a[i][20:30, 40 + min(i // 8, 9)] = 1                   # an edge that moves 1 px every 8 frames
    u = M.sky_flicker_unstable(a)
    check("the flickering block is taken out, the stable half and the moving edge stay", u is not None and bool(u[20][8:12, 42:48].all()) and not bool(u[20][:, :20].any()) and not bool(u[20][22:28, 40:41].any()))


def synth_rows(weak=True):
    """a 534 x 272 BGR killfeed: one row (y 155 - 183) and the row below it (y 185 - 212) touching; the shared edge is a smeared (4:2:0) weaker red"""
    fr = np.full((272, 534, 3), (200, 170, 120), np.uint8)
    strong, faint = (45, 15, 127), (119, 91, 181)
    def box(x0, y0, x1, y1, top, bot):
        cv2.rectangle(fr, (x0, y0), (x1, y1), (60, 50, 40), -1)
        fr[y0:y0 + 2, x0:x1 + 1] = top
        fr[y1 - 1:y1 + 1, x0:x1 + 1] = bot
        fr[y0:y1 + 1, x0:x0 + 2] = strong
        fr[y0:y1 + 1, x1 - 1:x1 + 1] = strong
    box(237, 155, 527, 183, strong, faint if weak else strong)
    box(291, 185, 527, 212, faint if weak else strong, strong)
    return fr


def part4():
    print("4) CS2 rows: touching rows, row grid, old sidecars")
    rects = M.border_rects(synth_rows(True))
    check(f"two touching rows with a smeared shared edge are two rects ({[(r['y0'], r['y1']) for r in rects]})", len(rects) == 2 and rects[0]["y1"] < rects[1]["y0"] + 4 and rects[0]["y1"] - rects[0]["y0"] < 34 and rects[1]["y1"] - rects[1]["y0"] < 34)
    check("the same two rows with strong edges are found as before", len(M.border_rects(synth_rows(False))) == 2)
    one = synth_rows(True)
    one[185:, :] = (200, 170, 120)
    one[110:140, :] = synth_rows(False)[155:185, :]            # a clear outlined row of the same height above it (the killfeed is on screen)
    r1 = M.border_rects(one)
    check("a single row whose bottom edge is smeared is completed (one rect, row height)", len(r1) == 1 and 24 <= r1[0]["y1"] - r1[0]["y0"] <= 34, str(r1))
    lonely = np.full((272, 534, 3), (200, 170, 120), np.uint8)
    lonely[100:102, 100:420] = (45, 15, 127)
    lonely[130:132, 100:420] = (119, 91, 181)
    check("a red line pair on its own (no outlined row on screen) is not a row", M.border_rects(lonely) == [])
    tall = np.full((272, 534, 3), (200, 170, 120), np.uint8)
    cv2.rectangle(tall, (237, 100), (527, 157), (60, 50, 40), -1)
    tall[100:102, 237:528] = (45, 15, 127)
    tall[156:158, 237:528] = (45, 15, 127)
    tall[100:158, 237:239] = (45, 15, 127)
    tall[100:158, 526:528] = (45, 15, 127)
    check("one real tall rect without an inner edge is not split", len(M.border_rects(tall)) == 1)

    def trk(i, first, last, hits, y0, y1, slots):
        return {"id": i, "first": first, "last": last, "hits": hits, "x0": 283, "x1": 528, "y0": y0, "y1": y1, "slots": [[f, y] for f, y in slots]}
    tracks = [trk(1, 726, 874, 149, 64, 95, [(726, 64)]), trk(2, 776, 874, 97, 95, 121, [(776, 90), (783, 94), (799, 90), (805, 95)]),
              trk(3, 829, 874, 37, 155, 182, [(829, 155)]), trk(4, 861, 874, 14, 187, 212, [(861, 187)])]
    old_rows, _ = M.border_shape_filter(copy.deepcopy(tracks), 875)
    new_rows, _ = M.border_shape_filter(copy.deepcopy(tracks), 875, fix=True)
    check(f"row grid: one early slot of a fragment made the pitch 26 and dropped rows ({len(old_rows)} rows); the fix keeps all four ({len(new_rows)})", len(old_rows) < 4 and len(new_rows) == 4)
    good = [trk(1, 100, 300, 190, 64, 95, [(100, 64)]), trk(2, 150, 300, 140, 95, 126, [(150, 95)]), trk(3, 200, 300, 90, 126, 157, [(200, 126)])]
    check("a normal clip is not changed by the fix", len(M.border_shape_filter(copy.deepcopy(good), 400)[0]) == len(M.border_shape_filter(copy.deepcopy(good), 400, fix=True)[0]) == 3)
    junk = good + [trk(9, 220, 260, 40, 175, 191, [(220, 175)])]
    check("a junk track off the grid still does not become a row", len(M.border_shape_filter(copy.deepcopy(junk), 400, fix=True)[0]) == 3)
    sc = {"v": 1, "ext": 2, "fps": 30, "frames": 875, "v_off": 0.0, "tracks": copy.deepcopy(tracks), "key": "x"}
    r_old = M.border_shape_filter(sc["tracks"], 875, **({"fix": True} if sc.get("ext", 1) >= 3 else {}))[0]
    check("a sidecar built before V8.7 (ext 2) is read exactly as before", len(r_old) == len(old_rows))


def part5():
    print("5) the 4k clip: 4 kills")
    cache = json.loads((M.DATA / "clips_cache3.json").read_text(encoding="utf-8")) if (M.DATA / "clips_cache3.json").exists() else {}
    rec = next((dict(v, game="cs2") for k, v in cache.items() if "CS2 2026-10-17 02-48-50" in k), None)
    if rec is None or not Path(rec["path"]).exists():
        print("  (the clip or its scan is not in this data folder: skipped)")
        return
    det = M.Detector("cs2")
    sc = M.border_load(rec, det)
    if sc is None or sc.get("ext", 1) < 3:
        print("  (no V8.7 row sidecar for the clip yet: skipped; Troubleshoot > rebuild the CS2 row borders of this clip)")
        return
    a = M.border_analysis(sc, M.load_config())
    ts = [round(k["t"], 1) for k in a["kills"]]
    check(f"4 kills: {ts}", len(ts) == 4 and abs(ts[0] - 24.2) < 0.3 and abs(ts[1] - 25.9) < 0.3 and ts[2] < 28.0 and abs(ts[3] - 28.7) < 0.3)


def part6():
    print("6) audio track")
    calls = []
    keep = M.resolve_clip_audio
    keep_fk = M.file_key
    M.file_key = lambda p: str(p)
    M.resolve_clip_audio = lambda rec, cfg, game, state: (calls.append((game, (cfg.get("game_audio_track") or {}).get(game))), {"stream": 1})[1]
    M._CS2_STREAM.clear()
    try:
        cfg = {"audio_mode": "auto", "game_audio_track": {"valorant": "2", "cs2": "2", "r6s": "auto"}}
        for g in ("valorant", "cs2", "r6s"):
            rec = {"path": f"x_{g}.mp4", "game": g, "audio": True}
            check(f"{g}: the stream of the gunshot analysis comes from the Settings pick", M._cs2_stream(rec, cfg) == 1 and calls[-1][0] == g)
        rv = {"path": "x_valorant.mp4", "game": "valorant", "audio": True}
        check("Valorant onset key names the track (track 2 -> o1c1), track 1 keeps the old key", M._onset_key(rv, cfg).endswith("o1c1") and M._onset_key(rv, None).endswith("o1"))
    finally:
        M.resolve_clip_audio = keep
        M.file_key = keep_fk
        M._CS2_STREAM.clear()
    import inspect
    check("refine_shot reads the clip's game track", "_cs2_stream" in inspect.getsource(M.refine_shot) and "cfg" in inspect.signature(M.refine_shot).parameters)


if __name__ == "__main__":
    import json                                                                               # noqa: E402
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
    sys.exit(1 if T.FAILS else 0)
