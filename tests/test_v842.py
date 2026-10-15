"""V8.4.2 tests: the render failure fix and the per-montage EFFECT PLAN. FAST unit tests only (no montage render, no OCR, no real clips).
  0) title-bar version V8.4.2; V8.4.2 on top of V8.4.1 in both changelogs
  1) DEFAULT = V8.23.1: plan, plan text, filter graph (default fx argument too) for all three games; the old retry rule is unchanged without extra effects
  2) the effect plan is selective: only a share of the kills is dressed, calm takes mostly clean, one / two / three effects per kill, the drop kill gets the most, the plan is logged
  3) montages differ: other seed / song / style = other signature, counts and parameters; the same inputs = the same plan
  4) the plan only changes the look: cut timing, kills, beats identical; the cut list verifies
  5) sky: a few candidates, probe keeps only clear-sky kills (at most the montage's number, spaced apart), none = no sky at all, never most clips
  6) retry list: every extra effect has its own switch; a failing effect is dropped on its own (order, error text) and the others stay; the old rule for DEFAULT
  7) render chains on a synthetic picture (real ffmpeg): outside the windows bit-identical, killfeed zone kept, glow colours, no buffering structure
python tests\\test_v842.py   (parts: V842_PARTS=0,1,2,3,4,5,6,7)"""
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v842_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

PARTS = [x for x in os.environ.get("V842_PARTS", "0,1,2,3,4,5,6,7").split(",") if x]
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
    spec = importlib.util.spec_from_file_location("montage_base842", str(bd / "montage.py"))
    B = importlib.util.module_from_spec(spec)
    sys.modules["montage_base842"] = B
    sys.path.insert(0, str(bd))
    spec.loader.exec_module(B)
    sys.path.remove(str(bd))
    return B


SONG = TMP / "song.mp3"
_AN = []


def an():
    if not _AN:
        M.synth_song(SONG, 128.0)
        _AN.append(M.analyse_song(str(SONG), 128.0))
    return _AN[0]


def mk(mod, game, style, seed, title="t", energy=0.8, eff=None):
    cfg = dict(mod.DEFAULT_CONFIG)
    if eff:
        cfg["effects_game"] = dict(eff)
    keep = mod.clip_audio
    mod.clip_audio = lambda rec, *a, **k: {"stream": None, "lufs": None}
    try:
        song = {"path": str(SONG), "artist": "a", "title": title, "energy": energy, "dance": 0.7}
        plan = mod.plan_montage(cfg, game, copy.deepcopy(M.fake_events()), song, an(), seed, style, "optimal", [], [])
        return plan, cfg
    finally:
        mod.clip_audio = keep


def js(x):
    return json.dumps(x, sort_keys=True, default=str)


def kill_effects(plan):
    """{(take, kill index): [kinds]} of the per-kill effects"""
    res = {}
    for ti, t in enumerate(plan["takes"]):
        for x in t.get("xfx", []):
            if x["k"] in ("glow", "flash", "rgb", "punch"):
                for i, p in enumerate(t["kills_out"]):
                    if abs(x["p"] - p) < 0.02:
                        res.setdefault((ti, i), []).append(x["k"])
    return res


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.4.2", M.APP_VERSION == "V8.4.2")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.4.2 above V8.4.1", cl[0].startswith("## V8.4.2") and cl[1].startswith("## V8.4.1"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.4.2 above V8.4.1", sm[0].startswith("## V8.4.2") and sm[1].startswith("## V8.4.1"), str(sm[:2]))
    seg = body[body.index("## V8.4.2"):body.index("## V8.4.1")].lower()
    check("simple entry is plain (no test / function names, no known-issue list)", not any(w in seg for w in ("test", "known issue", "on hold", "def ", "xfx", "ffmpeg")))


def part1():
    print("1) DEFAULT = V8.23.1")
    B = load_base()
    for g in ("cs2", "valorant", "r6s"):
        for style in ("aggressive", "chill"):
            pb, cb = mk(B, g, style, 2)
            pd, cd = mk(M, g, style, 2, eff=ALL_DEFAULT)
            gb, gd = repr(B.build_filter(pb, cb, False)), repr(M.build_filter(pd, cd, False))
            tb, td = B.fmt_plan(pb, copy.deepcopy(M.fake_events()), {}, [], [], None), M.fmt_plan(pd, copy.deepcopy(M.fake_events()), {}, [], [], None)
            check(f"{g} / {style}: plan, plan text and filter graph identical to {BASE_REF}", js(pb) == js(pd) and tb == td and gb == gd)
            check(f"{g} / {style}: build_filter with the old fx tuple gives the same graph as with the default argument", repr(M.build_filter(pd, cd, False, M.FX_ALL)) == gd)
    check("the old retry rule is unchanged without extra effects", M.fx_culprit("error in overlay", {"zoom", "slow", "flash", "transition"}) == "zoom"
          and M.fx_culprit("blend failed", {"zoom", "slow", "flash", "transition"}) == "transition" and M.fx_culprit("drawbox", {"zoom", "slow", "flash", "transition"}) == "flash"
          and M.fx_culprit("???", {"zoom", "slow", "flash", "transition"}) == "transition" and M.fx_culprit("???", {"slow"}) == "slow")


def part2():
    print("2) the effect plan is selective")
    for style, share_max in (("aggressive", 0.8), ("hype", 0.8), ("chill", 0.45)):
        plan, _ = mk(M, "cs2", style, 2, eff=ALL_EXTRA)
        ke = kill_effects(plan)
        n = sum(len(t["kills_out"]) for t in plan["takes"])
        sp = plan["xfx_plan"]
        check(f"{style}: only a share of the kills is dressed ({len(ke)} of {n})", 0 < len(ke) <= share_max * n and len(ke) < n, str(sp))
        check(f"{style}: the plan's numbers equal what is in the takes", sp["dressed"] >= len(ke) - 1 and sp["glow"] == sum(1 for v in ke.values() for k in v if k == "glow"))
    plan, _ = mk(M, "cs2", "aggressive", 2, eff=ALL_EXTRA)
    ke = kill_effects(plan)
    cnts = [len(v) for v in ke.values()]
    check("kills get 1, 2 or 3 effects (variety in how many)", len(set(cnts)) >= 2 and max(cnts) >= 3, str(sorted(set(cnts))))
    clean = [(ti, i) for ti, t in enumerate(plan["takes"]) for i in range(len(t["kills_out"])) if (ti, i) not in ke and not any(abs(q - t["kills_out"][i]) < 0.02 for q in t["pulses"])]
    check("kills without any effect exist (clean kills)", len(clean) >= 3)
    head = [ti for ti, t in enumerate(plan["takes"]) if t["role"] == "headline"][0]
    hk = [k for k in plan["takes"][head]["xfx"]]
    kinds = {x["k"] for x in hk}
    check("the drop / headline kill gets the full burst (glow, flash, split, punch or zoom pulse, build-up, afterglow)", {"glow", "flash", "rgb", "rise", "after"} <= kinds, str(kinds))
    calm = [(ti, i) for ti, t in enumerate(plan["takes"]) if t["role"] == "calm" for i in range(len(t["kills_out"]))]
    dressed_calm = [c for c in calm if c in ke]
    other = [(ti, i) for ti, t in enumerate(plan["takes"]) if t["role"] in ("drop", "headline") for i in range(len(t["kills_out"]))]
    dressed_other = [c for c in other if c in ke]
    check("calm takes are dressed less than drop takes", not calm or not other or len(dressed_calm) / len(calm) < len(dressed_other) / len(other), f"{len(dressed_calm)}/{len(calm)} vs {len(dressed_other)}/{len(other)}")
    multi = [t for t in plan["takes"] if len(t["kills_out"]) >= 3]
    mid_dressed = [1 for ti, t in enumerate(plan["takes"]) if len(t["kills_out"]) >= 3 for i in range(len(t["kills_out"])) if (ti, i) in ke]
    check("a multikill is not dressed on every kill", bool(multi) and len(mid_dressed) < sum(len(t["kills_out"]) for t in multi))
    close = 0
    for ti, t in enumerate(plan["takes"]):
        ks = [(i, t["out_start"] + p) for i, p in enumerate(t["kills_out"]) if (ti, i) in ke]
        close += sum(1 for a, b in zip(ks, ks[1:]) if b[1] - a[1] < 0.5 and t["role"] != "headline")
    check("no two dressed kills within 0.5 s of each other (a spray is not spammed)", close == 0, str(close))
    lines = [n for n in plan["notes"] if n.startswith("EFFECT PLAN")]
    check("the effect plan is in the plan notes: feel / style, signature, counts per effect, sky, run-ups", len(lines) == 2 and "signature" in lines[0] and "kills dressed" in lines[1] and "sky recolour" in lines[1] and "glow" in lines[1])
    check("... and the song feel colour with its reason", "song feel" in lines[0] and "style aggressive" in lines[0])


def part3():
    print("3) montages differ")
    sigs = set()
    vecs = set()
    for seed in (2, 5, 9, 14, 21, 33):
        plan, _ = mk(M, "valorant", "aggressive", seed, title=f"song{seed}", eff=ALL_EXTRA)
        sp = plan["xfx_plan"]
        sigs.add(tuple(sp["signature"]))
        vecs.add((sp["glow"], sp["flash"], sp["split"], sp["punch"], sp["dressed"]))
    check(f"6 seeds / songs: at least 3 different signatures ({len(sigs)}) and 5 different count vectors ({len(vecs)})", len(sigs) >= 3 and len(vecs) >= 5, str(sigs))
    a, _ = mk(M, "valorant", "aggressive", 2, title="one", eff=ALL_EXTRA)
    b, _ = mk(M, "valorant", "aggressive", 2, title="two", eff=ALL_EXTRA)
    c, _ = mk(M, "valorant", "aggressive", 2, title="one", eff=ALL_EXTRA)
    check("the same inputs = the same effect plan", js([t.get("xfx") for t in a["takes"]]) == js([t.get("xfx") for t in c["takes"]]) and js(a["xfx_plan"]) == js(c["xfx_plan"]))
    check("another song (same seed, same clips) = another plan", js(a["xfx_plan"]) != js(b["xfx_plan"]) or js([t.get("xfx") for t in a["takes"]]) != js([t.get("xfx") for t in b["takes"]]))
    cm, _ = mk(M, "valorant", "chill", 2, energy=0.3, eff=ALL_EXTRA)
    ag, _ = mk(M, "valorant", "aggressive", 2, energy=0.95, eff=ALL_EXTRA)
    check("a calm song is dressed less than an aggressive one", cm["xfx_plan"]["dressed"] < ag["xfx_plan"]["dressed"], f"{cm['xfx_plan']['dressed']} vs {ag['xfx_plan']['dressed']}")
    check("the colour follows the feel (chill = blue, aggressive = red)", cm["xfx_feel"]["name"] == "blue" and ag["xfx_feel"]["name"] == "red")
    kinds_c = {x["k"] for t in cm["takes"] for x in t.get("xfx", [])}
    check("a chill montage uses few kinds of effect (no flash / split outside the drop kill)", sum(1 for t in cm["takes"] for x in t.get("xfx", []) if x["k"] in ("flash", "rgb")) <= 2, str(kinds_c))


def part4():
    print("4) only the look changes")
    keys = ("f0", "nf", "out_start", "dur", "kills", "kills_out", "rows_out", "beat0", "beat_end", "beat_kill", "song_beat", "path", "role", "level", "trans", "pulses", "n", "score")
    for g in ("cs2", "valorant", "r6s"):
        for style in ("aggressive", "chill"):
            d, _ = mk(M, g, style, 2, eff=ALL_DEFAULT)
            e, _ = mk(M, g, style, 2, eff=ALL_EXTRA)
            bad = [(i, k) for i, (a, b) in enumerate(zip(d["takes"], e["takes"])) for k in keys if js(a.get(k)) != js(b.get(k))]
            check(f"{g} / {style}: cut timing, kills, rows, beats identical; output frames per take identical; cut list verifies",
                  not bad and all(sum(s[3] for s in a["segs"]) == sum(s[3] for s in b["segs"]) for a, b in zip(d["takes"], e["takes"])) and M.verify_cutlist(e, log=False) == [] and M.plan_duplicate_ranges(e) == [], str(bad[:3]))
    e, _ = mk(M, "cs2", "aggressive", 2, eff=ALL_EXTRA)
    check("no shake, no unknown effect kinds", {x["k"] for t in e["takes"] for x in t.get("xfx", [])} <= {"glow", "flash", "rgb", "punch", "rise", "after", "settle", "mirror", "sky", "speed"})
    check("every window lies inside its take", all(-0.05 <= a and b <= t["dur"] + 0.01 for t in e["takes"] for a, b in M.xfx_windows(t, 0, False)))


def part5():
    print("5) sky")
    plan, _ = mk(M, "valorant", "aggressive", 2, eff=ALL_EXTRA)
    sky = [(t["out_start"] + x["gp"] - t["out_start"], ti) for ti, t in enumerate(plan["takes"]) for x in t.get("xfx", []) if x["k"] == "sky"]
    gps = sorted(x["gp"] for t in plan["takes"] for x in t.get("xfx", []) if x["k"] == "sky")
    check(f"at most {M.XFX_SKY_CANDS} sky candidates, 8 s apart, on strong takes' last kill", 0 < len(gps) <= M.XFX_SKY_CANDS and all(b - a >= 8.0 for a, b in zip(gps, gps[1:])))
    check("sky is never planned for most clips (candidates < half the takes)", len(gps) < len(plan["takes"]) / 2 + 1)
    check("the montage's sky number is set from the feel (aggressive up to 3, chill 1)", 1 <= plan["xfx_sky_max"] <= 3 and mk(M, "valorant", "chill", 2, eff=ALL_EXTRA)[0]["xfx_sky_max"] == 1)
    img = {"v": None}

    class R:
        pass
    h, w = 270, 480
    sky_img = np.full((h, w, 3), (122, 106, 85), np.uint8)
    sky_img[:90] = (110, 168, 220)
    room = np.full((h, w, 3), (138, 122, 106), np.uint8)
    keep = M.run, M.out
    try:
        def probe(images):
            it = iter(images)

            def fake_run(*a, **k):
                r = R()
                r.stdout = next(it).tobytes()
                return r
            M.run = fake_run
            logs = []
            M.out = lambda s: logs.append(s)
            pl = copy.deepcopy(plan)
            for t in pl["takes"]:
                t["srcs"] = [{"path": "x.mp4", "shift": 0.0, "dur": 99, "rect": [0, 0, 1920, 1080], "wh": [1920, 1080]}]
            M.xfx_probe_sky(pl)
            return pl, logs
        n_c = len(gps)
        pl, logs = probe([sky_img] * n_c)
        ok = sorted(x["gp"] for t in pl["takes"] for x in t.get("xfx", []) if x["k"] == "sky" and x["ok"])
        check(f"all candidates have a clear sky: at most the montage's number is kept ({len(ok)} <= {plan['xfx_sky_max']}), at least {M.XFX_SKY_SPACING:.0f} s apart",
              1 <= len(ok) <= plan["xfx_sky_max"] and all(b - a >= M.XFX_SKY_SPACING for a, b in zip(ok, ok[1:])), str(ok))
        check("every candidate has a log line, and a summary line", len(logs) == n_c + 1 and "SKY recolour:" in logs[-1], str(logs[-2:]))
        pl, logs = probe([room] * n_c)
        check("no clear sky anywhere (indoors): no sky recolour at all", not any(x["ok"] for t in pl["takes"] for x in t.get("xfx", []) if x["k"] == "sky") and "0 of" in logs[-1], str(logs[-1:]))
    finally:
        M.run, M.out = keep
    check("a bright wall everywhere is not sky (coverage cap 0.60)", M.XFX_SKY_MAX_COV == 0.60 and float(M.sky_mask_np(np.full((270, 480, 3), 200, np.uint8))[:148].mean()) > 0.6)


def part6():
    print("6) retry list")
    allfx = set(M.FX_ALL) | set(M.XFX_FX)
    check("every extra effect has its own switch (glow, split, grade, sky) next to the old four", set(M.XFX_FX) == {"glow", "split", "grade", "sky"} and set(M.FX_ALL) == {"zoom", "flash", "slow", "transition"})
    order = []
    fx = set(allfx)
    while fx:
        c = M.fx_culprit("invalid data", fx)
        order.append(c)
        fx.discard(c)
    check("an unnamed failure drops one effect at a time, the extra ones first, nothing is dropped twice", order == list(M.FX_DROP_ORDER), str(order))
    check("the error text names the effect: geq -> sky, chromashift -> split, drawbox / blend -> glow", M.fx_culprit("Error in geq", set(allfx)) == "sky" and M.fx_culprit("chromashift", set(allfx)) == "split"
          and M.fx_culprit("drawbox", set(allfx)) == "glow" and M.fx_culprit("blend", set(allfx)) == "glow")
    plan, cfg = mk(M, "valorant", "aggressive", 2, eff=ALL_EXTRA)
    for t in plan["takes"]:
        for x in t.get("xfx", []):
            if x["k"] == "sky":
                x["ok"] = True
    full = M.build_filter(plan, cfg, False)[1]
    check("all effects on: the graph has glow (drawbox + blend), split (chromashift), grade (eq contrast), sky (geq)", all(k in full for k in ("drawbox", "chromashift", "eq=contrast", "geq=")))
    glow_key = f"color=0x{plan['xfx_feel']['rgb']:06X}"
    check("all effects on: the glow layer carries the feel colour", glow_key in full)
    for drop, key in (("glow", glow_key), ("split", "chromashift"), ("grade", "eq=contrast"), ("sky", "geq=")):
        g = M.build_filter(plan, cfg, False, tuple(set(allfx) - {drop}))[1]
        others = [k for k in ("drawbox", "chromashift", "eq=contrast", "geq=") if k != key]
        check(f"without '{drop}' only that effect is gone ({key}); the others stay", key not in g and all(k in g for k in others if k in full), key)
    g = M.build_filter(plan, cfg, False, ("slow",))[1]
    check("with only 'slow' left the graph carries no extra effect at all", not any(k in g for k in ("drawbox", "chromashift", "eq=contrast", "geq=", "fillborders")))
    p0 = copy.deepcopy(plan)
    for t in p0["takes"]:
        t.pop("xfx", None)
    p0.pop("effects", None)
    check("a plan without extra data renders with the old fx set only", "chromashift" not in M.build_filter(p0, cfg, False)[1])
    # the render loop: low memory = wait and retry with the same effects; a plain failure drops one effect at a time and finishes
    def loop(rcs, mems):
        calls, logs = [], []
        tmpf, elog, gp = TMP / "o.part.mp4", TMP / "e.txt", TMP / "g.txt"
        keep = (M._run_ffmpeg, M.probe_duration, M.out, M.time.sleep, M.os.replace)
        seq = iter(zip(rcs, mems))

        def fake_run(cmd, D, el):
            rc, mem = next(seq)
            calls.append(" ".join(cmd))
            M.RUN_MEM["min_free"], M.RUN_MEM["total"] = mem, 24.0
            Path(el).write_text("Error while filtering: Invalid data found when processing input" if rc else "", encoding="utf-8")
            if rc == 0:
                tmpf.write_bytes(b"x")
            return rc
        M._run_ffmpeg, M.probe_duration, M.out, M.time.sleep, M.os.replace = fake_run, (lambda p_: plan["duration"]), logs.append, (lambda s_: None), (lambda a_, b_: None)
        failed = []
        fxs = set(M.FX_ALL) | set(M.XFX_FX)
        try:
            M._render_loop(plan, plan, plan, TMP / "out.mp4", cfg, False, False, "fast", True, False, tmpf, elog, gp, fxs, failed, plan["duration"])
            return failed, fxs, calls, logs, None
        except RuntimeError as ex:
            return failed, fxs, calls, logs, str(ex)
        finally:
            M._run_ffmpeg, M.probe_duration, M.out, M.time.sleep, M.os.replace = keep
    failed, fxs, calls, logs, err = loop([1, 1, 0], [0.4, 0.5, 6.0])
    check("ffmpeg dies while memory is nearly out: it waits and retries with the SAME effects (nothing dropped), then finishes", err is None and failed == [] and len(calls) == 3 and sum("waiting 30 s" in l for l in logs) == 2, str((failed, len(calls), err)))
    failed, fxs, calls, logs, err = loop([1, 1, 0], [8.0, 8.0, 8.0])
    check("a plain failure drops one effect at a time (sky, then split) and the render finishes", err is None and failed == ["sky", "split"] and "sky" not in fxs and "split" not in fxs and "glow" in fxs, str((failed, err)))
    failed, fxs, calls, logs, err = loop([1] * 12, [8.0] * 12)
    check("if every attempt fails, every effect is tried out one by one (all 8) and the error names the logs", err is not None and len(failed) == 8 and len(calls) == 9, str((len(failed), len(calls), err)))
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("render_plan switches the extra effects on only for an extra plan", 'set(XFX_FX) if p.get("effects") == "extra"' in src)


def run_chain(take, n=150, zone=None, base="testsrc2=s=1920x1080:r=60:d=2.5", feel=None, fx=None):
    chains = []
    lab = M._xfx_chains(chains, "t0", "[src]", take, fx or (set(M.FX_ALL) | set(M.XFX_FX)), False, zone or [0.58, 0.03, 1.0, 0.25], feel or {"rgb": 0xFF2A18})
    res, fc_fx = {}, ""
    for name, fc in (("fx", base + ",format=yuv420p,setpts=PTS-STARTPTS[src];" + ";".join(chains) + f";{lab}null[o]"), ("ref", base + ",format=yuv420p,setpts=PTS-STARTPTS,null[o]")):
        r = subprocess.run(["ffmpeg", "-v", "error", "-filter_complex", fc, "-map", "[o]", "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "yuv420p", "-"], capture_output=True)
        if r.returncode != 0:
            return None, r.stderr.decode("utf-8", "ignore")[-500:], fc
        res[name] = np.frombuffer(r.stdout, np.uint8).reshape(-1, 1080 * 3 // 2, 1920)
        if name == "fx":
            fc_fx = fc
    return res, "", fc_fx


def part7():
    print("7) render chains on a synthetic picture (real ffmpeg)")
    take = {"nf": 150, "xfx": [{"k": "glow", "p": 0.6, "a": 0.4, "t1": 0.26, "fall": 7.0}, {"k": "glow", "p": 1.5, "a": 0.4, "t1": 0.26, "rgb": 0x18C8D8},
                               {"k": "flash", "p": 0.6, "a": 0.2, "t1": 0.14}, {"k": "rgb", "p": 0.6, "px": 8, "t1": 0.12}]}
    res, err, fc = run_chain(take)
    check("the chains run in ffmpeg", res is not None, err)
    if res is None:
        return
    o, r = res["fx"], res["ref"]
    wins = [(0.595, 0.86), (1.495, 1.76)]
    inside = lambda i: any(a - 1.5 / 60 <= i / 60 <= b + 1.5 / 60 for a, b in wins)
    check("frames outside every window are bit-identical", all(np.array_equal(o[i], r[i]) for i in range(len(o)) if not inside(i)))
    zy, zx = int(0.06 * 1080), int(0.62 * 1920)
    zone = lambda a: a[zy:zy + 150, zx:zx + 600]
    check("glow / flash: the picture changes, the killfeed zone does not", all(not np.array_equal(o[i][:1080], r[i][:1080]) and np.array_equal(zone(o[i]), zone(r[i])) for i in range(37, 45)))
    check("a second glow with another colour (the drop accent) gets its own layer", fc.count("drawbox") >= 3 and not np.array_equal(o[91][:1080], r[91][:1080]))
    check("nothing is split off and held back (no trim of later windows, no separate colour source)", "trim=start_frame" not in fc and "color=c=" not in fc and "setpts=PTS+" not in fc)
    only_split = run_chain(take, fx={"zoom", "split"})[0]
    check("fx without glow / flash: those layers are not built, the split stays", only_split is not None and not np.array_equal(only_split["fx"][38], only_split["ref"][38]) and
          np.array_equal(only_split["fx"][38][:1080], only_split["ref"][38][:1080]))


for p in PARTS:
    globals()["part" + p]()
print("\nFAILS:", len(FAILS))
for f in FAILS:
    print(" -", f)
sys.exit(1 if FAILS else 0)
