"""V8.4 tests: Effects setting (DEFAULT / EXTRA EFFECTS). FAST unit tests only (no montage render, no OCR, no real clips).
  0) title-bar version V8.4; V8.4 on top of V8.23.1 in both changelogs; docs/reference_fiverr48.md exists with the measured / guessed marks
  1) the setting: default "default", saved and loaded with the other settings (GUI round trip), unknown value = default
  2) DEFAULT = V8.23.1: same inputs, same plan (json), same plan text, same filter graph (all three games); no extra keys in the plan, no 'xfx' on a take
  3) EXTRA only adds look data: segments, kills, rows, cut timing, beat fields, durations, song, drops identical to DEFAULT; extra effects obey the safety rules
  4) the render chains (real ffmpeg on a synthetic picture): frames outside every effect window are bit-identical; the killfeed zone is untouched inside flash / shake windows;
     no black edges on a shake; the mirror frames are a real zoom-out; default graph has none of the extra filters
  5) checks know the extra windows (only in EXTRA)
python tests\\test_v84.py   (parts: V84_PARTS=0,1,2,3,4,5)"""
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v84_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

PARTS = [x for x in os.environ.get("V84_PARTS", "0,1,2,3,4,5").split(",") if x]
FAILS = []
BASE_REF = "V8.23.1"


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def load_base():
    bd = TMP / "base"
    bd.mkdir(exist_ok=True)
    tar = subprocess.run(["git", "archive", BASE_REF], cwd=ROOT, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(bd)], input=tar, check=True)
    spec = importlib.util.spec_from_file_location("montage_base84", str(bd / "montage.py"))
    B = importlib.util.module_from_spec(spec)
    sys.modules["montage_base84"] = B
    sys.path.insert(0, str(bd))
    spec.loader.exec_module(B)
    sys.path.remove(str(bd))
    return B


_PLANS = {}


def plans():
    """(base, default, extra) plan + filter graph + text for each game, same inputs (synthetic song + events), cached."""
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
            for tag, mod, eff in (("base", B, None), ("default", M, "default"), ("extra", M, "extra")):
                cfg = dict(mod.DEFAULT_CONFIG)
                if eff:
                    cfg["effects"] = eff
                plan = mod.plan_montage(cfg, g, copy.deepcopy(evs), song, an, 2, "aggressive", "optimal", [], [])
                _PLANS[(g, tag)] = {"plan": plan, "graph": repr(mod.build_filter(plan, cfg, False)),
                                    "text": mod.fmt_plan(plan, copy.deepcopy(evs), {}, [], [], None)}
    finally:
        M.clip_audio, B.clip_audio = keep
    return _PLANS


def js(x):
    return json.dumps(x, sort_keys=True, default=str)


def part0():
    print("0) version, changelogs, notes file")
    check("APP_VERSION is V8.4", M.APP_VERSION == "V8.4")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.4 above V8.23.1", cl[0].startswith("## V8.4 ") and cl[1].startswith("## V8.23.1"), str(cl[:2]))
    sm = [l for l in (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("simple changelog: V8.4 above V8.23.1", sm[0].startswith("## V8.4 ") and sm[1].startswith("## V8.23.1"), str(sm[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    seg = body[body.index("## V8.4 "):body.index("## V8.23.1")].lower()
    check("simple entry is plain (no test / function names, no known-issue list)", not any(w in seg for w in ("test", "known issue", "on hold", "def ", "xfx", "ffmpeg")))
    n = (ROOT / "docs" / "reference_fiverr48.md").read_text(encoding="utf-8")
    check("reference notes exist with [measured] and [guess] marks and a 'not built' list", all(k in n for k in ("[measured]", "[guess]", "[seen]", "Not built")), "")


def part1():
    print("1) the setting")
    check("default config: effects = default", M.DEFAULT_CONFIG.get("effects") == "default")
    check("effects_mode: unknown / missing = default", M.effects_mode({}) == "default" and M.effects_mode({"effects": "weird"}) == "default"
          and M.effects_mode({"effects": "EXTRA"}) == "extra")
    old = M.use_data_dir(TMP / "d1")
    try:
        app = M.App(0, startup=False)
        try:
            check("Settings 'Effects' starts on Default", app.set_fx.get() == M.EFFECT_LABELS["default"])
            app.set_fx.set(M.EFFECT_LABELS["extra"])
            for _ in range(8):
                app.root.update()
                time.sleep(0.08)
            check("Extra effects: saved to config.json and loaded again", M.load_config().get("effects") == "extra")
            app.set_fx.set(M.EFFECT_LABELS["default"])
            for _ in range(8):
                app.root.update()
                time.sleep(0.08)
            check("back to Default: saved", M.load_config().get("effects") == "default")
        finally:
            app.root.destroy()
            M.LOG_SINK[0] = M.PROGRESS[0] = None
    finally:
        M.restore_data_dir(old)


def part2():
    print("2) DEFAULT = V8.23.1")
    P = plans()
    for g in ("cs2", "valorant", "r6s"):
        b, d = P[(g, "base")], P[(g, "default")]
        check(f"{g}: plan identical to {BASE_REF} (json)", js(b["plan"]) == js(d["plan"]))
        check(f"{g}: plan text identical", b["text"] == d["text"])
        check(f"{g}: filter graph identical", b["graph"] == d["graph"])
        check(f"{g}: no 'effects' / 'xfx_zone' key in the plan and no 'xfx' on a take", "effects" not in d["plan"] and "xfx_zone" not in d["plan"]
              and not any("xfx" in t for t in d["plan"]["takes"]))
    check("the plan has takes with zoom pulses (the comparison is not empty)", any(t["pulses"] for t in P[("cs2", "default")]["plan"]["takes"]))


def part3():
    print("3) EXTRA only adds look data")
    P = plans()
    for g in ("cs2", "valorant", "r6s"):
        d, e = P[(g, "default")]["plan"], P[(g, "extra")]["plan"]
        strip = lambda t: {k: v for k, v in t.items() if k not in ("xfx", "amp")}
        check(f"{g}: every take identical except xfx / amp (segments, kills, rows, beat fields, durations)", js([strip(t) for t in d["takes"]]) == js([strip(t) for t in e["takes"]]))
        check(f"{g}: zoom pulses identical (the default effects' random draws are untouched)", [t["pulses"] for t in d["takes"]] == [t["pulses"] for t in e["takes"]])
        keys = set(d) | set(e)
        diff = [k for k in keys if js(d.get(k)) != js(e.get(k))]
        check(f"{g}: the plan differs only in effects / xfx_zone / notes / takes", set(diff) <= {"effects", "xfx_zone", "notes", "takes"}, str(diff))
        check(f"{g}: notes differ by exactly the 'EFFECTS extra' line", [n for n in e["notes"] if not n.startswith("EFFECTS extra")] == d["notes"])
        check(f"{g}: plan['effects'] = extra and the line is in the plan text", e.get("effects") == "extra" and "EFFECTS extra" in P[(g, "extra")]["text"])
        check(f"{g}: duration / frames / song / beats identical", all(js(d[k]) == js(e[k]) for k in ("duration", "total_frames", "song", "beats_out", "drops_out")))
    e = P[("cs2", "extra")]["plan"]
    xs = [(i, x) for i, t in enumerate(e["takes"]) for x in t.get("xfx", [])]
    kinds = {x["k"] for _, x in xs}
    check("extra adds effects to the synthetic plan (settle and at least one kill effect)", "settle" in kinds and bool(kinds & {"flash", "shake", "mirror"}), str(kinds))
    for i, x in xs:
        t = e["takes"][i]
        first = t["kills_out"][0]
        if x["k"] in ("settle", "mirror"):
            check(f"take {i + 1} {x['k']}: not on the first take, kill row >= {M.XFX_MIN_LEAD} s away, window {x['t1']:.3f} s", i > 0 and first >= M.XFX_MIN_LEAD and x["t1"] <= M.XFX_SETTLE_S + 1e-9)
        else:
            check(f"take {i + 1} {x['k']}: only on a punched kill, window ends {x['t1']} s after it, shake <= {M.XFX_SHAKE_PX_MAX} px",
                  x["p"] in t["pulses"] and x["t1"] <= 0.30 + 1e-9 and (x["k"] != "shake" or x["px"] <= M.XFX_SHAKE_PX_MAX))
    mir = [i for i, x in xs if x["k"] == "mirror"]
    check("no two mirror cuts in a row", all(b - a >= 2 for a, b in zip(mir, mir[1:])))
    check("a mirror frame is only planned on a hard cut (never into a dissolve)", all(e["takes"][i]["trans"] == "hard" for i in mir))
    d = P[("cs2", "default")]["plan"]
    sc = lambda t: M.xfx_strength(t)
    ratios = [(sc(t), te["amp"] / t["amp"]) for t, te in zip(d["takes"], e["takes"]) if t.get("amp")]
    ratios.sort()
    check("beat strength: the punch grows with it (weaker take never gets a bigger factor)", all(a[1] <= b[1] + 1e-9 for a, b in zip(ratios, ratios[1:])), str(ratios))
    check("the punch amount stays within the cap", all(t["amp"] <= 0.14 + 1e-9 for t in e["takes"]))
    hp = copy.deepcopy(P[("cs2", "default")]["plan"])                  # force hard cuts (real plans have them on drops): mirror frames appear, with the same rules
    for t in hp["takes"]:
        t["trans"] = "hard"
    M.assign_extra_fx(hp, "cs2", 2)
    mh = [i for i, t in enumerate(hp["takes"]) for x in t.get("xfx", []) if x["k"] == "mirror"]
    check("with hard cuts the strong takes get mirror frames (never the first take, never two in a row)", len(mh) >= 1 and 0 not in mh and all(b - a >= 2 for a, b in zip(mh, mh[1:])), str(mh))
    check("mirror: zoom-out factor between 0.7 and 0.9, 2 frames", all(0.7 <= x["z"] <= 0.9 and abs(x["t1"] - 2 / 60) < 1e-3 for t in hp["takes"] for x in t.get("xfx", []) if x["k"] == "mirror"))
    a, b = plans(), None
    M.synth_song  # deterministic: a second plan with the same inputs gives the same effects
    sp = TMP / "song.mp3"
    an = M.analyse_song(str(sp), 128.0)
    keep = M.clip_audio
    M.clip_audio = lambda rec, *a_, **k: {"stream": None, "lufs": None}
    try:
        cfg = dict(M.DEFAULT_CONFIG, effects="extra")
        song = {"path": str(sp), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
        p2 = M.plan_montage(cfg, "cs2", copy.deepcopy(M.fake_events()), song, an, 2, "aggressive", "optimal", [], [])
    finally:
        M.clip_audio = keep
    check("same inputs = same effects", js([t.get("xfx") for t in p2["takes"]]) == js([t.get("xfx") for t in e["takes"]]))


def run_chain(take, ti=1, soft_in=False, zone=None, n=90):
    """Run _xfx_chains on a synthetic 1920x1080 picture (frame number written into the picture by a pattern) through real ffmpeg; returns (orig, out) arrays of the frames."""
    chains = []
    fx = M.FX_ALL
    lab = M._xfx_chains(chains, "t0", "[src]", take, fx, soft_in, zone or [0.58, 0.03, 1.0, 0.40])
    base = f"testsrc2=s=1920x1080:r=60:d={n / 60},format=yuv420p,setpts=PTS-STARTPTS"
    graphs = {"out": base + "[src];" + ";".join(chains) + f";{lab}null[o]", "ref": base + ",null[o]"}
    res = {}
    for name, fc in graphs.items():
        cmd = ["ffmpeg", "-v", "error", "-filter_complex", fc, "-map", "[o]", "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "gray", "-"]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode != 0:
            return None, r.stderr.decode("utf-8", "ignore")[-400:]
        res[name] = np.frombuffer(r.stdout, np.uint8).reshape(-1, 1080, 1920)
    return res, ""


def part4():
    print("4) render chains on a synthetic picture (real ffmpeg)")
    take = {"xfx": [{"k": "mirror", "z": 0.8, "t0": 0.0, "t1": round(2 / 60, 4)},
                    {"k": "flash", "p": 0.5, "a": 0.15, "t1": 0.16}, {"k": "shake", "p": 1.0, "px": 18, "t1": 0.30}]}
    res, err = run_chain(take)
    check("the chains run in ffmpeg", res is not None, err)
    if res is None:
        return
    o, r = res["out"], res["ref"]
    check("same number of frames out as in", len(o) == len(r) == 90, f"{len(o)} {len(r)}")
    wins = [(0.0, 2 / 60), (0.48, 0.5 + 0.16), (0.98, 1.0 + 0.30)]
    inside = lambda i: any(a - 1.5 / 60 <= i / 60 <= b + 1.5 / 60 for a, b in wins)
    same = [i for i in range(len(o)) if not inside(i)]
    check(f"frames outside every window are bit-identical ({len(same)} frames)", all(np.array_equal(o[i], r[i]) for i in same))
    check("the mirror frames differ from the picture and are a zoom-out (the centre is smaller: its border is mirrored, not black)",
          not np.array_equal(o[0], r[0]) and o[0][:20].mean() > 5 and np.array_equal(o[3], r[3]))
    zx, zy, zw, zh = int(0.58 * 1920) & ~1, int(0.03 * 1080) & ~1, int(0.42 * 1920) & ~1, int(0.37 * 1080) & ~1
    for i in range(30, 45):                                             # flash window (0.5 s = frame 30)
        if 31 <= i <= 38:
            check(f"flash frame {i}: brighter picture, killfeed zone unchanged", o[i].mean() > r[i].mean() + 3 and np.array_equal(o[i][zy:zy + zh, zx:zx + zw], r[i][zy:zy + zh, zx:zx + zw]))
            break
    moved = [i for i in range(60, 78) if not np.array_equal(o[i], r[i])]
    check("shake frames differ from the picture", len(moved) >= 6, str(moved))
    check("shake: killfeed zone identical in every shake frame", all(np.array_equal(o[i][zy:zy + zh, zx:zx + zw], r[i][zy:zy + zh, zx:zx + zw]) for i in moved))
    check("shake: no black edges (the picture is mirror-padded: the border rows keep their brightness)", all(o[i][:4].mean() > 0.5 * r[i][:4].mean() for i in moved))
    P = plans()
    check("default filter graph has none of the extra filters", all(k not in P[("cs2", "default")]["graph"] for k in ("fillborders", "eq=brightness", "mode=mirror")))
    check("extra filter graph carries them", all(k in P[("cs2", "extra")]["graph"] for k in ("settle",)) or "fillborders" in P[("cs2", "extra")]["graph"] or "exp(-9*" in P[("cs2", "extra")]["graph"])
    take2 = {"xfx": [{"k": "settle", "a": 0.05, "t0": 0.0, "t1": 0.25}, {"k": "mirror", "z": 0.8, "t0": 0.0, "t1": 0.0334}]}
    chains = []
    lab = M._xfx_chains(chains, "t0", "[src]", take2, M.FX_ALL, True, None)
    check("a soft (dissolve) cut gets no mirror frames", lab == "[src]" and not chains)


def part5():
    print("5) the checks know the extra windows")
    P = plans()
    d, e = P[("cs2", "default")]["plan"], P[("cs2", "extra")]["plan"]
    wd, we = M._fx_windows(d), M._fx_windows(e)
    check("DEFAULT: windows unchanged (zoom pulses only)", wd == [[(p - 0.02, p + 0.47) for p in t["pulses"]] for t in d["takes"]])
    check("EXTRA: more windows than DEFAULT in at least one take, none fewer", all(len(b) >= len(a) for a, b in zip(wd, we)) and any(len(b) > len(a) for a, b in zip(wd, we)))
    check("windows start at 0 or at a punched kill (never in the middle of a run-up)", all(w[0] <= 0.0 + 1e-9 or any(abs(w[0] - (p - 0.02)) < 1e-6 for p in t["pulses"]) for t, ws in zip(e["takes"], we) for w in ws))


for p in PARTS:
    globals()["part" + p]()
print("\nFAILS:", len(FAILS))
for f in FAILS:
    print(" -", f)
sys.exit(1 if FAILS else 0)
