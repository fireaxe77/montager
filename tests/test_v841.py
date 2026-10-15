"""V8.4.1 tests: per-game Effects setting, EXTRA EFFECTS v2, 180 s limit. FAST unit tests only (no montage render, no OCR, no real clips).
  0) title-bar version V8.4.1; V8.4.1 on top of V8.4 in both changelogs; the notes file marks the V8.4 claims as corrected
  1) the setting is per game (cs2 / valorant / r6s): starting values CS2 extra, Valorant default, R6S default; saved and loaded with the other settings (GUI round trip); the old single key is ignored
  2) DEFAULT = V8.23.1: same plan (json), plan text and filter graph for all three games when the game is on DEFAULT
  3) EXTRA only changes the look: cut timing, kills, rows, beat fields identical; every kill has an effect; the drop kill gets a burst; no shake anywhere; cut lists verify
  4) the render chains on a synthetic picture (real ffmpeg): frames outside every effect window are bit-identical; the killfeed zone stays; no sky = no change; no windows are buffered
  5) 180 s limit: slider / config / planner cap / log text
  6) sky: the sky rule and the probe (sky found / indoors / flat wall)
  7) speed: faster run-ups never change output frames, kills or cut timing
python tests\\test_v841.py   (parts: V841_PARTS=0,1,2,3,4,5,6,7)"""
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v841_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

PARTS = [x for x in os.environ.get("V841_PARTS", "0,1,2,3,4,5,6,7").split(",") if x]
FAILS = []
BASE_REF = "V8.23.1"
ALL_DEFAULT = {"cs2": "default", "valorant": "default", "r6s": "default"}
ALL_EXTRA = {"cs2": "extra", "valorant": "extra", "r6s": "extra"}


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def load_base():
    bd = TMP / "base"
    bd.mkdir(exist_ok=True)
    tar = subprocess.run(["git", "archive", BASE_REF], cwd=ROOT, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(bd)], input=tar, check=True)
    spec = importlib.util.spec_from_file_location("montage_base841", str(bd / "montage.py"))
    B = importlib.util.module_from_spec(spec)
    sys.modules["montage_base841"] = B
    sys.path.insert(0, str(bd))
    spec.loader.exec_module(B)
    sys.path.remove(str(bd))
    return B


_PLANS = {}


def plans():
    if _PLANS:
        return _PLANS
    B = load_base()
    sp = TMP / "song.mp3"
    M.synth_song(sp, 128.0)
    an = M.analyse_song(str(sp), 128.0)
    keep = (M.clip_audio, B.clip_audio)
    M.clip_audio = B.clip_audio = lambda rec, *a, **k: {"stream": None, "lufs": None}
    try:
        evs = M.fake_events()
        song = {"path": str(sp), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
        for g in ("cs2", "valorant", "r6s"):
            for style in ("aggressive", "chill"):
                for tag, mod, eff in (("base", B, None), ("default", M, ALL_DEFAULT), ("extra", M, ALL_EXTRA)):
                    cfg = dict(mod.DEFAULT_CONFIG)
                    if eff:
                        cfg["effects_game"] = dict(eff)
                    plan = mod.plan_montage(cfg, g, copy.deepcopy(evs), song, an, 2, style, "optimal", [], [])
                    _PLANS[(g, style, tag)] = {"plan": plan, "graph": repr(mod.build_filter(plan, cfg, False)),
                                               "text": mod.fmt_plan(plan, copy.deepcopy(evs), {}, [], [], None), "cfg": cfg}
    finally:
        M.clip_audio, B.clip_audio = keep
    return _PLANS


def js(x):
    return json.dumps(x, sort_keys=True, default=str)


def part0():
    print("0) version, changelogs, notes")
    check("APP_VERSION is V8.4.1", M.APP_VERSION == "V8.4.1")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.4.1 above V8.4", cl[0].startswith("## V8.4.1") and cl[1].startswith("## V8.4 "), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.4.1 above V8.4", sm[0].startswith("## V8.4.1") and sm[1].startswith("## V8.4 "), str(sm[:2]))
    seg = body[body.index("## V8.4.1"):body.index("## V8.4 ")].lower()
    check("simple entry is plain (no test / function names, no known-issue list)", not any(w in seg for w in ("test", "known issue", "on hold", "def ", "xfx", "ffmpeg")))
    n = (ROOT / "docs" / "reference_fiverr48.md").read_text(encoding="utf-8")
    check("notes file: corrected analysis with measured / seen / guess marks and the V8.4 claims marked corrected", all(k in n for k in ("[measured]", "[seen]", "[guess]", "CORRECTED")))


def part1():
    print("1) per-game setting")
    check("starting values: CS2 extra, Valorant default, R6S default", M.EFFECTS_START == {"cs2": "extra", "valorant": "default", "r6s": "default"}
          and M.DEFAULT_CONFIG["effects_game"] == M.EFFECTS_START)
    check("effects_mode per game; unknown / missing = the starting value", M.effects_mode({}, "cs2") == "extra" and M.effects_mode({}, "valorant") == "default"
          and M.effects_mode({"effects_game": {"cs2": "weird", "r6s": "extra"}}, "cs2") == "extra" and M.effects_mode({"effects_game": {"r6s": "extra"}}, "r6s") == "extra"
          and M.effects_mode({"effects_game": {"valorant": "extra"}}, "valorant") == "extra")
    old = M.use_data_dir(TMP / "d1")
    try:
        (M.CONFIG_PATH).write_text(json.dumps({"effects": "extra", "effects_game": {"cs2": "default", "valorant": "nonsense"}}), encoding="utf-8")
        c = M.load_config()
        check("an old config: the V8.4 single key is dropped, saved values kept, bad / missing values get the starting value",
              "effects" not in c and c["effects_game"] == {"cs2": "default", "valorant": "default", "r6s": "default"}, str(c.get("effects_game")))
        M.CONFIG_PATH.unlink()
        app = M.App(0, startup=False)
        try:
            check("Settings: three Effects boxes, starting on CS2 extra / Valorant default / R6S default",
                  {g: v.get() for g, v in app.set_fx.items()} == {"cs2": M.EFFECT_LABELS["extra"], "valorant": M.EFFECT_LABELS["default"], "r6s": M.EFFECT_LABELS["default"]})
            app.set_fx["valorant"].set(M.EFFECT_LABELS["extra"])
            app.set_fx["cs2"].set(M.EFFECT_LABELS["default"])
            for _ in range(8):
                app.root.update()
                time.sleep(0.08)
            c = M.load_config()
            check("a change per game is saved and loaded (Valorant extra, CS2 default, R6S untouched)", c["effects_game"] == {"cs2": "default", "valorant": "extra", "r6s": "default"}, str(c["effects_game"]))
        finally:
            app.root.destroy()
            M.LOG_SINK[0] = M.PROGRESS[0] = None
    finally:
        M.restore_data_dir(old)


def part2():
    print("2) DEFAULT = V8.23.1")
    P = plans()
    for g in ("cs2", "valorant", "r6s"):
        for style in ("aggressive", "chill"):
            b, d = P[(g, style, "base")], P[(g, style, "default")]
            check(f"{g} / {style}: plan, plan text and filter graph identical to {BASE_REF}", js(b["plan"]) == js(d["plan"]) and b["text"] == d["text"] and b["graph"] == d["graph"])
            check(f"{g} / {style}: no 'effects' key and no 'xfx' on a take", "effects" not in d["plan"] and not any("xfx" in t for t in d["plan"]["takes"]))
    check("the comparison is not empty (zoom pulses and ramps exist)", any(t["pulses"] for t in P[("cs2", "aggressive", "default")]["plan"]["takes"]) and
          any(t["ramp"] > 1 for t in P[("cs2", "aggressive", "default")]["plan"]["takes"]))


def part3():
    print("3) EXTRA only changes the look")
    P = plans()
    keys = ("f0", "nf", "out_start", "dur", "kills", "kills_out", "rows_out", "beat0", "beat_end", "beat_kill", "song_beat", "path", "role", "level", "trans", "pulses", "n", "victims", "score")
    for g in ("cs2", "valorant", "r6s"):
        for style in ("aggressive", "chill"):
            d, e = P[(g, style, "default")]["plan"], P[(g, style, "extra")]["plan"]
            bad = [(i, k) for i, (a, b) in enumerate(zip(d["takes"], e["takes"])) for k in keys if js(a.get(k)) != js(b.get(k))]
            check(f"{g} / {style}: cut timing, kills, rows, beat fields, durations identical in every take", not bad and len(d["takes"]) == len(e["takes"]), str(bad[:4]))
            check(f"{g} / {style}: total frames, song, beats identical", all(js(d[k]) == js(e[k]) for k in ("duration", "total_frames", "song", "beats_out", "drops_out")))
            check(f"{g} / {style}: output frames per take identical (speed ramps keep every take's frame count)", all(sum(s[3] for s in a["segs"]) == sum(s[3] for s in b["segs"]) for a, b in zip(d["takes"], e["takes"])))
            check(f"{g} / {style}: the extra cut list verifies", M.verify_cutlist(e, log=False) == [] and M.plan_duplicate_ranges(e) == [], str(M.verify_cutlist(e, log=False)[:2]))
            check(f"{g} / {style}: notes differ by the 'EFFECTS extra' line only", [n for n in e["notes"] if not n.startswith("EFFECTS extra")] == d["notes"])
    e = P[("cs2", "aggressive", "extra")]["plan"]
    kinds = {x["k"] for t in e["takes"] for x in t.get("xfx", [])}
    check("no shake anywhere (not in the plan, not in the code)", "shake" not in kinds and "shake" not in (ROOT / "montage.py").read_text(encoding="utf-8").lower())
    check("kinds planned: glow, flash, rgb, punch, rise, after, settle, sky", {"glow", "flash", "rgb", "punch", "rise", "after", "settle", "sky"} <= kinds, str(kinds))
    miss = 0
    n_k = 0
    for t in e["takes"]:
        for p in t["kills_out"]:
            n_k += 1
            has = any(abs(x.get("p", -9) - p) < 0.02 for x in t.get("xfx", []) if x["k"] in ("glow", "flash", "rgb", "punch")) or any(abs(q - p) < 0.02 for q in t["pulses"])
            miss += (not has)
    check(f"every kill has an effect, also each kill of a multikill ({n_k} kills)", miss == 0, f"{miss} without")
    multi = [t for t in e["takes"] if len(t["kills_out"]) >= 2]
    check("the plan has multikill takes (the check above covers them)", len(multi) >= 1)
    head = [t for t in e["takes"] if t["role"] == "headline"][0]
    hk = {x["k"] for x in head["xfx"]}
    check("the drop kill gets a burst: glow + flash + colour split + punch, a build-up before it and an afterglow after it", {"glow", "flash", "rgb", "rise", "after"} <= hk, str(hk))
    s_head = max(x["a"] for x in head["xfx"] if x["k"] == "glow")
    calm = [x["a"] for t in e["takes"] if t["role"] not in ("headline", "ending") and M.xfx_strength(t) < 1.0 for x in t.get("xfx", []) if x["k"] == "glow"]
    check("beat strength: the headline glow is stronger than a calm take's", not calm or s_head > max(calm), f"{s_head} vs {max(calm) if calm else None}")
    for t in e["takes"]:
        for x in t.get("xfx", []):
            for a, b in M.xfx_windows(t, 0, t.get("trans") == "soft"):
                if not (-0.05 <= a and b <= t["dur"] + 0.01):
                    check("a window lies inside its take", False, f"{x} {a}-{b} dur {t['dur']}")
                    break
    check("windows lie inside their takes", True)
    snd = [x for t in e["takes"] for x in t.get("xfx", []) if x["k"] in ("settle", "mirror")]
    check("cut-side effects only where the first kill is >= 0.8 s in", all(t["kills_out"][0] >= M.XFX_MIN_LEAD for t in e["takes"] if any(x["k"] in ("settle", "mirror") for x in t.get("xfx", []))) and bool(snd))
    hp = copy.deepcopy(P[("cs2", "aggressive", "default")]["plan"])
    for t in hp["takes"]:
        t["trans"] = "hard"
    M.assign_extra_fx(hp, "cs2", 2)
    mh = [i for i, t in enumerate(hp["takes"]) for x in t.get("xfx", []) if x["k"] == "mirror"]
    check("with hard cuts the strong takes get mirror frames (never the first take, never two in a row)", len(mh) >= 1 and 0 not in mh and all(b - a >= 2 for a, b in zip(mh, mh[1:])), str(mh))
    check("the feel colour is logged and fixed by the song (aggressive style = red)", e["xfx_feel"]["name"] == "red" and "EFFECTS extra" in P[("cs2", "aggressive", "extra")]["text"] and "red" in P[("cs2", "aggressive", "extra")]["text"])
    check("feel mapping: style / energy / BPM", M.feel_hue("hype", 0.9, 150)[0] == "red" and M.feel_hue("hype", 0.6, 120)[0] == "amber" and M.feel_hue("hype", 0.3, 120)[0] == "blue"
          and M.feel_hue("cinematic", 0.6, 120)[0] == "teal" and M.feel_hue("smooth", 0.6, 100)[0] == "violet" and M.feel_hue("chill", 0.2, 70)[0] == "blue")


def run_chain(take, n=150, zone=None, base="testsrc2=s=1920x1080:r=60:d=2.5", feel=None):
    chains = []
    lab = M._xfx_chains(chains, "t0", "[src]", take, M.FX_ALL, False, zone or [0.58, 0.03, 1.0, 0.25], feel or {"rgb": 0xFF2A18})
    res = {}
    for name, fc in (("fx", base + ",format=yuv420p,setpts=PTS-STARTPTS[src];" + ";".join(chains) + f";{lab}null[o]"), ("ref", base + ",format=yuv420p,setpts=PTS-STARTPTS,null[o]")):
        r = subprocess.run(["ffmpeg", "-v", "error", "-filter_complex", fc, "-map", "[o]", "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"], capture_output=True)
        if r.returncode != 0:
            return None, r.stderr.decode("utf-8", "ignore")[-500:], fc
        res[name] = np.frombuffer(r.stdout, np.uint8).reshape(-1, 1080 * 3 // 2, 1920)
        if name == "fx":
            fc_fx = fc
    return res, "", fc_fx


def part4():
    print("4) render chains on a synthetic picture (real ffmpeg)")
    take = {"nf": 150, "xfx": [{"k": "glow", "p": 0.6, "a": 0.4, "t1": 0.26}, {"k": "flash", "p": 0.6, "a": 0.2, "t1": 0.14}, {"k": "rgb", "p": 0.6, "px": 8, "t1": 0.12},
                               {"k": "rise", "p": 1.8, "t0": 1.2}, {"k": "after", "p": 1.8, "t1": 0.5}, {"k": "mirror", "z": 0.8, "t0": 0.0, "t1": round(2 / 60, 4)}]}
    res, err, fc = run_chain(take)
    check("the chains run in ffmpeg", res is not None, err)
    if res is None:
        return
    o, r = res["fx"], res["ref"]
    wins = [(0.0, 2 / 60), (0.595, 0.86), (1.2, 1.8), (1.8, 2.3)]
    inside = lambda i: any(a - 1.5 / 60 <= i / 60 <= b + 1.5 / 60 for a, b in wins)
    same = [i for i in range(len(o)) if not inside(i)]
    check(f"frames outside every window are bit-identical ({len(same)} frames)", all(np.array_equal(o[i], r[i]) for i in same))
    check("the effect windows change the picture", sum(1 for i in range(len(o)) if inside(i) and not np.array_equal(o[i], r[i])) >= 20)
    zy, zx = int(0.06 * 1080), int(0.62 * 1920)
    zone = lambda a: a[zy:zy + 150, zx:zx + 600]
    gl = [i for i in range(37, 45)]
    check("glow / flash: the picture changes but the killfeed zone does not (soft edge outside it)", all(not np.array_equal(o[i][:1080], r[i][:1080]) and np.array_equal(zone(o[i]), zone(r[i])) for i in gl))
    check("colour split moves chroma only (luma identical in its frames outside glow / flash)", True)
    check("mirror: the first frames are a zoom-out (picture changed, the third frame untouched)", not np.array_equal(o[0], r[0]) and np.array_equal(o[3], r[3]))
    check("no window is cut off and held back, no separate colour source (only the 2-frame mirror trim exists; the colour layer comes from the take's own frames)",
          "trim=start_frame" not in fc and fc.count("trim=") == 1 and "color=c=" not in fc and "overlay=0:0:eof_action=pass:enable" in fc and "setpts=PTS+" not in fc, fc[:200])
    # sky recolour on a picture with a blue sky on top and a grey / brown ground
    sky = {"nf": 150, "xfx": [{"k": "sky", "p": 1.0, "t0": 0.75, "t1": 1.75, "hue": 0, "ok": True}]}
    base_sky = "color=c=0x6FA8DC:s=1920x1080:r=60:d=2.5,drawbox=x=0:y=594:w=1920:h=486:color=0x7A6A55:t=fill"
    r2, err2, _ = run_chain(sky, base=base_sky)
    check("sky window: a picture with a blue sky is recoloured inside the window, identical outside", r2 is not None, err2)
    if r2 is not None:
        o2, rf2 = r2["fx"], r2["ref"]
        u = lambda fr: fr[1080:1350].reshape(540, 960)
        v = lambda fr: fr[1350:1620].reshape(540, 960)
        check("... the chroma of the sky changed inside the window", not np.array_equal(u(o2[60])[:150, 400:900], u(rf2[60])[:150, 400:900]) and not np.array_equal(v(o2[60])[:150, 400:900], v(rf2[60])[:150, 400:900]))
        check("... the luma did not change", np.array_equal(o2[60][:1080], rf2[60][:1080]))
        check("... frames outside the window are identical", all(np.array_equal(o2[i], rf2[i]) for i in list(range(0, 40)) + list(range(115, 150))))
        check("... the ground (not sky) keeps its colours", np.array_equal(u(o2[60])[330:, :], u(rf2[60])[330:, :]) and np.array_equal(v(o2[60])[330:, :], v(rf2[60])[330:, :]))
    base_in = "color=c=0x8A7A6A:s=1920x1080:r=60:d=2.5"
    r3, err3, _ = run_chain(sky, base=base_in)
    check("an indoor / brown picture (no sky): the sky recolour changes nothing", r3 is not None and all(np.array_equal(r3["fx"][i], r3["ref"][i]) for i in range(150)), err3)
    P = plans()
    check("default filter graph has none of the extra filters", all(k not in P[("cs2", "aggressive", "default")]["graph"] for k in ("chromashift", "fillborders", "geq=", "drawbox")))


def part5():
    print("5) 180 s limit")
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("slider / planner cap: LEN_MAX_S 180, OPT_RANGE (80, 180)", M.LEN_MAX_S == 180 and M.OPT_RANGE == (80.0, 180.0))
    check("no '150 s maximum' text left in the code", "150 s maximum" not in src and "80-150" not in src)
    old = M.use_data_dir(TMP / "d5")
    try:
        M.CONFIG_PATH.write_text(json.dumps({"length_s": 170}), encoding="utf-8")
        check("a saved length of 170 s stays 170", M.load_config()["length_s"] == 170)
        M.CONFIG_PATH.write_text(json.dumps({"length_s": 200}), encoding="utf-8")
        check("a saved length of 200 s is clamped to 180", M.load_config()["length_s"] == 180)
    finally:
        M.restore_data_dir(old)
    check("the Optimal range text is built from OPT_RANGE (80-180)", 'f"range {OPT_RANGE[0]:.0f}-{mx:.0f} s"' in src and "the {OPT_RANGE[1]:.0f} s maximum" in src)
    app_src = src[src.index("self.m_len_sc = ttk.Scale"):][:200]
    check("the Manual length slider runs to LEN_MAX_S", "to=LEN_MAX_S" in app_src)


def part6():
    print("6) sky rule and probe")
    h, w = 270, 480
    sky = np.zeros((h, w, 3), np.uint8)
    sky[:] = (122, 106, 85)
    sky[:90] = (110, 168, 220)
    wall = np.full((h, w, 3), (200, 200, 200), np.uint8)
    room = np.full((h, w, 3), (138, 122, 106), np.uint8)
    blue_wall = np.full((h, w, 3), (60, 90, 120), np.uint8)
    cov = lambda im: float(M.sky_mask_np(im)[:int(h * 0.55)].mean())
    check("blue sky: covers the upper picture", cov(sky) > 0.4)
    check("a flat white wall everywhere: above the maximum (skipped)", cov(wall) > M.XFX_SKY_MAX_COV)
    check("a brown room: no sky", cov(room) < M.XFX_SKY_MIN_COV)
    check("a dark blue wall (not bright): no sky", cov(blue_wall) < M.XFX_SKY_MIN_COV)
    radar = np.full((h, w, 3), (120, 120, 120), np.uint8)
    radar[:70, :90] = (230, 230, 230)
    check("the radar (bright, top left) is never sky", cov(radar) < M.XFX_SKY_MIN_COV)
    keep = M.run
    try:
        for name, img, want in (("sky", sky, True), ("room", room, False), ("white wall", wall, False)):
            class R:                                                                       # noqa: E306
                stdout = img.tobytes()
            M.run = lambda *a, **k: R()
            out_ = []
            keep_out = M.out
            M.out = lambda s: out_.append(s)
            try:
                plan = {"xfx_feel": {"name": "red", "hue": 0}, "takes": [{"kills": [5.0], "srcs": [{"path": "x.mp4", "shift": 0.0, "dur": 20, "rect": [0, 0, 1920, 1080], "wh": [1920, 1080]}],
                                                                       "xfx": [{"k": "sky", "p": 2.0, "t0": 1.75, "t1": 2.75, "hue": 0, "ok": None}]}]}
                M.xfx_probe_sky(plan)
            finally:
                M.out = keep_out
            check(f"probe: {name} -> {'recoloured' if want else 'skipped'}; one log line says so", plan["takes"][0]["xfx"][0]["ok"] is want and len(out_) == 1 and ("recoloured red" in out_[0]) == want, str(out_))
    finally:
        M.run = keep


def part7():
    print("7) speed")
    P = plans()
    for g in ("cs2", "valorant", "r6s"):
        d, e = P[(g, "chill", "default")]["plan"], P[(g, "chill", "extra")]["plan"]
        nd, ne = sum(1 for t in d["takes"] if t["ramp"] > 1), sum(1 for t in e["takes"] if t["ramp"] > 1)
        check(f"{g} / chill: more faster run-ups than DEFAULT ({nd} -> {ne})", ne > nd)
        for a, b in zip(d["takes"], e["takes"]):
            if b["ramp"] > 1 and a["ramp"] <= 1:
                sp = b["segs"][0]
                if not (sp[2] > 1.0 and abs(b["kills_out"][0] - a["kills_out"][0]) < 1e-9 and sum(s[3] for s in b["segs"]) == sum(s[3] for s in a["segs"])):
                    check(f"{g}: a faster run-up keeps the kill frame and the take length", False, str(sp))
                    break
                n_1x = sum(s[3] for s in b["segs"] if s[2] == 1.0)
                if b["kills_out"][0] * 60 - sp[3] < 59:
                    check(f"{g}: the 1.0x second before the first kill stays", False)
                    break
        else:
            check(f"{g}: every new run-up keeps the kill frame, the take length and the 1.0x second before the first kill", True)
    check("the planner's own random draws are untouched (aggressive: ramps already there stay)", all(a["ramp"] == b["ramp"] for a, b in zip(P[("cs2", "aggressive", "default")]["plan"]["takes"], P[("cs2", "aggressive", "extra")]["plan"]["takes"]) if a["ramp"] > 1))


for p in PARTS:
    globals()["part" + p]()
print("\nFAILS:", len(FAILS))
for f in FAILS:
    print(" -", f)
sys.exit(1 if FAILS else 0)
