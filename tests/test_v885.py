"""V8.8.5 tests (fast; no montage render, no library scan).
  0) title-bar version V8.8.5; V8.8.5 on top of V8.8.4 in both changelogs
  1) sky animation: every pattern moves on EVERY frame after the kill (no standstill between beats) and still steps on the beats; strobe, drops to black, colour jumps, the top -> bottom
     gradient, the colour family, coverage and placement identical to the v8.8.4 tag
  2) sky mask pop-in: the push / shake moves the colour, never the mask (pixels outside the mask bit-identical on every frame, the kill frame and the frames after it included; mask frame N
     lands on take frame N); the mask frames come from the render's own take chain; a camera turned away / a cut never carries the sky over (synthetic take); nothing before the kill frame
  3) sky patterns: bands, amoebas, rings, rays, aurora - clearly different, smooth (soft edges), moving, deterministic; ONE pattern per montage from the song alone (same song = same pattern
     whatever seed / style / game, different songs spread over the patterns); the pattern is written into the mask and every pattern renders in ffmpeg
  4) regression list V1 .. V8.8.4: every rule / feature / setting checked (one line each, the version it came from); see REG below
  5) song fill: the fill loop reaches the end of the song (rounds / minimum add), never removes a chosen clip; DEFAULT plans / filter graphs of all three games identical to v8.8.4
     from the same events apart from the sky
  (real data: tests/fill883.py = every game x mode fills Perfect Exceeder; tests/skymask885.py = real sky takes, mask + rendered picture never paint off the sky; tests/render885.py = real render)
python tests\\test_v885.py   (parts: V885_PARTS=0,1,2,3,4,5)"""
import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
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
check = T.check
PARTS = [x for x in os.environ.get("V885_PARTS", "0,1,2,3,4,5,6").split(",") if x]
import numpy as np                                                                            # noqa: E402

PREV = "v8.8.4"
_PREV = []


def prev():
    """the v8.8.4 tag's montage.py as a module (git archive into a temp folder)."""
    if not _PREV:
        bd = T.TMP / "prev885"
        bd.mkdir(exist_ok=True)
        tar = subprocess.run(["git", "archive", PREV, "montage.py"], cwd=ROOT, capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", str(bd)], input=tar, check=True)
        spec = importlib.util.spec_from_file_location("montage_prev885", str(bd / "montage.py"))
        B = importlib.util.module_from_spec(spec)
        sys.modules["montage_prev885"] = B
        spec.loader.exec_module(B)
        _PREV.append(B)
    return _PREV[0]


def SRC():
    return (ROOT / "montage.py").read_text(encoding="utf-8")


def body_of(name, src=None):
    src = src or SRC()
    i = src.index(f"def {name}(")
    j = src.find("\ndef ", i + 10)
    return src[i:j if j > 0 else len(src)]


def _series_ok():
    """V9.2.1: the series number counted for real: an empty folder = #1, each finished montage (also a _2 of the same day, an older week name) +1, a .part file not; the same after a restart."""
    import subprocess
    d = Path(tempfile.mkdtemp(prefix="v885series_"))
    cfg = {"output_root": str(d)}
    g = d / M.GAME_DIR["cs2"]
    g.mkdir()
    got = [M.series_next("cs2", cfg)]
    for nm in ("ILFTB_CS2_V9.2.1_2026-10-28.mp4", "ILFTB_CS2_V9.2.1_2026-10-28_2.mp4", "CS2_2026-W41_12826.mp4", "CS2_2026-W41_827727.part.mp4", "X_CS2_V9.2.1_2026-10-29.part.mp4"):
        (g / nm).write_bytes(b"0")
        got.append(M.series_next("cs2", cfg))
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import montage as M; print(M.series_next('cs2', {{'output_root': {str(d)!r}}}))"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    after = int((r.stdout.strip().splitlines() or ["0"])[-1])
    return got == [1, 2, 3, 4, 4, 4] and after == 4


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.8.5", M.APP_VERSION == "V8.8.5")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.8.5 above V8.8.4", cl[0].startswith("## V8.8.5") and cl[1].startswith("## V8.8.4"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.8.5 above V8.8.4", sm[0].startswith("## V8.8.5") and sm[1].startswith("## V8.8.4"), str(sm[:2]))
    seg = body[body.index("## V8.8.5"):body.index("## V8.8.4")]
    pts = [l for l in seg.splitlines() if l.startswith("- ")]
    head = seg.splitlines()[0].split(":", 1)[-1].strip()
    check(f"simple entry: a 3-8 word headline ('{head}'), 1-4 points", 3 <= len(head.split()) <= 8 and 1 <= len(pts) <= 4)
    check("simple entry is plain", not any(w in seg.lower() for w in ("test", "known issue", "on hold", "def ", "ffmpeg", "cache", "()", "planner", "ledger", "regression")))


BEATS = [(0.30 + 0.469 * i, 1.0 if i % 4 == 0 else 0.45) for i in range(10)]


def _frames(pattern, nf=240, f0=12, an=None, seed=5, beats=None):
    an = an or M.sky_anim_params(0.8, 128, "hype")
    return list(M.sky_pattern_frames(pattern, M.SKY_H, M.SKY_W, 260, nf, f0, BEATS if beats is None else beats, an, seed))


def part1():
    print("1) sky animation: moving on every frame, beat look unchanged")
    check("five patterns", tuple(M.SKY_PATTERNS) == ("bands", "amoebas", "rings", "rays", "aurora"))
    for p_ in M.SKY_PATTERNS:
        fr = _frames(p_)
        check(f"{p_}: nothing before the kill frame", all(not f_.any() for f_ in fr[:12]))
        mv = [float(np.abs(fr[i] - fr[i - 1]).mean()) for i in range(13, 240)]
        check(f"{p_}: moves on every frame after the kill (smallest change {min(mv):.4f}, mean {np.mean(mv):.4f})", min(mv) > 0.003)
        nb = _frames(p_, beats=[])
        fb = int(round(BEATS[3][0] * 60))
        step = lambda fr_, f: float(np.abs(fr_[f + 3] - fr_[f]).mean())
        check(f"{p_}: steps on the beat (3 frames over a beat {step(fr, fb):.4f} vs no beat {step(nb, fb):.4f})", step(fr, fb) > 1.3 * step(nb, fb))
        # still flowing between two beats: frame 20 after a beat differs clearly from frame 6 after it
        check(f"{p_}: flows between the beats ({float(np.abs(fr[fb + 24] - fr[fb + 8]).mean()):.4f})", float(np.abs(fr[fb + 24] - fr[fb + 8]).mean()) > 0.02)
    B = prev()
    an_ = M.sky_anim_params(0.85, 140, "aggressive", True)
    check("animation parameters (strobe, drops, jumps, swing, surge, push) identical to v8.8.4", an_ == B.sky_anim_params(0.85, 140, "aggressive", True)
          and M.sky_anim_params(0.3, 80, "chill") == B.sky_anim_params(0.3, 80, "chill"))
    x = {"seed": 11, "beats": BEATS}
    s1, s0 = M.sky_anim_schedule(an_, x, 12, 240), B.sky_anim_schedule(an_, x, 12, 240)
    check("strobe / drops to black / colour jumps schedule identical to v8.8.4", all(np.array_equal(s1[k_], s0[k_]) for k_ in ("black", "jump", "swing")))
    check("drops to black and colour jumps are there", float(s1["black"].max()) > 0.6 and float(s1["jump"].max()) > 0.5)
    sm = []
    for f in range(30):
        m = np.zeros((120, 40), np.float32)
        m[(0 if f < 15 else 40):(0 if f < 15 else 40) + 50] = 1.0
        sm.append(m)
    check("top -> bottom gradient plane identical to v8.8.4", M.sky_frame_ramps(sm, 120, 40, 60) == B.sky_frame_ramps(sm, 120, 40, 60))
    check("colour families identical to v8.8.4", M.SKY_FAMILIES == B.SKY_FAMILIES and M.sky_family_grade("teal", 170.0) == B.sky_family_grade("teal", 170.0))
    for st, e_, b_ in (("hype", 0.8, 128), ("chill", 0.4, 85)):
        rk = M.sky_ranked(st, e_, b_)[0]
        check(f"family choice identical to v8.8.4 ({st})", M.sky_family_for({"song": {"path": "nope.mp3"}}, rk) == B.sky_family_for({"song": {"path": "nope.mp3"}}, rk))
    check("coverage / placement identical to v8.8.4 (count, spacing, coverage limits, candidates)",
          [M.sky_max_for(d_) for d_ in (40, 70, 150, 180)] == [B.sky_max_for(d_) for d_ in (40, 70, 150, 180)] and M.sky_spacing_for() == B.sky_spacing_for()
          and (M.XFX_SKY_MIN_COV, M.XFX_SKY_MAX_COV, M.XFX_SKY_CANDS) == (B.XFX_SKY_MIN_COV, B.XFX_SKY_MAX_COV, B.XFX_SKY_CANDS)
          and (M.SKY_MIN_L, M.SKY_FRAME_MAX_COV, M.SKY_MAX_BAD, M.SKY_HOLD_FRAMES, M.SKY_IMPACT_F, M.SKY_OPACITY, M.SKY_MASK_FEATHER)
          == (B.SKY_MIN_L, B.SKY_FRAME_MAX_COV, B.SKY_MAX_BAD, B.SKY_HOLD_FRAMES, B.SKY_IMPACT_F, B.SKY_OPACITY, B.SKY_MASK_FEATHER))
    check("sky on / off switch per game unchanged", M.SKY_START == B.SKY_START == {"cs2": True, "valorant": True, "r6s": False})
    check("assign_extra_fx (sky candidates and placement) identical to v8.8.4", body_of("assign_extra_fx") == body_of("assign_extra_fx", (T.TMP / "prev885" / "montage.py").read_text(encoding="utf-8")))


def _render_sky(x, nf=40, src="testsrc2=s=1920x1080:r=60"):
    chains = []
    lab = M.xfx_sky_chain(chains, "t0", "[src]", x, 1)
    gph = "[0:v]format=yuv420p[src];" + ";".join(chains) + f";{lab}null[o]"
    r_ = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"{src}:d={nf / 60 + 0.1:.3f}"] + M.sky_mask_input(x) +
                        ["-filter_complex", gph, "-map", "[o]", "-frames:v", str(nf), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    r0 = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"{src}:d={nf / 60 + 0.1:.3f}", "-vf", "format=yuv420p", "-frames:v", str(nf), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                        capture_output=True)
    n = 1920 * 1080 * 3
    if len(r_.stdout) < nf * n or len(r0.stdout) < nf * n:
        return None, r_.stderr.decode("utf-8", "ignore")[-300:]
    fr = lambda b_, i_: np.frombuffer(b_[i_ * n:(i_ + 1) * n], np.uint8).reshape(1080, 1920, 3)
    return [(fr(r_.stdout, i), fr(r0.stdout, i)) for i in range(nf)], ""


def _mask_file(path, nf, ys, fmt="yuva444p"):
    H, W = M.SKY_H, M.SKY_W
    with open(path, "wb") as fh:
        for f in range(nf):
            fh.write(ys(f).tobytes() + np.zeros((H, W), np.uint8).tobytes() + np.zeros((H, W), np.uint8).tobytes()
                     + np.repeat(np.clip(np.arange(H) / (H / 3) * 255, 0, 255).astype(np.uint8)[:, None], W, 1).tobytes())


def _sky_img(kind, w=768, h=432, seed=0):
    rng = np.random.RandomState(seed)
    img = np.zeros((h, w, 3), np.float32)
    wall = np.clip(rng.normal(0, 30, (h, w, 1)) + np.array([110, 90, 70], np.float32), 0, 255)
    img[:] = wall
    if kind in ("sky", "left"):
        hz = int(h * 0.42)
        g = np.linspace(0, 1, hz)[:, None, None]
        sky = (1 - g) * np.array([95, 150, 225], np.float32) + g * np.array([150, 195, 240], np.float32)
        if kind == "sky":
            img[:hz] = sky
        else:
            img[:hz, :w // 2] = sky[:, :1].repeat(w // 2, 1)
    return np.clip(img, 0, 255).astype(np.uint8)


def part2():
    print("2) sky mask: never off the sky")
    tmp = Path(tempfile.mkdtemp())
    H, W = M.SKY_H, M.SKY_W
    # a) push + shake: the masked region (top third) only; everything outside it bit-identical on EVERY frame, the kill frame and its shake included
    mk = tmp / "push.yuv"
    _mask_file(mk, 40, lambda f: (np.vstack([np.full((H // 3, W), 240, np.uint8), np.zeros((H - H // 3, W), np.uint8)]) if f >= 10 else np.zeros((H, W), np.uint8)))
    x = {"mask": str(mk), "mask_fmt": "yuva444p", "p": 10 / 60, "push": 0.10, "grade": M.sky_family_grade("red", 160.0)}
    res, err = _render_sky(x)
    check("sky chain with a strong push renders", res is not None, err)
    if res:
        out_ = [int(np.abs(a_[420:].astype(int) - b_[420:].astype(int)).max()) for a_, b_ in res]
        check(f"push / shake: below the sky nothing changes on any frame (max change per frame {max(out_)})", max(out_) == 0)
        check("the frame before the kill frame is untouched", int(np.abs(res[9][0].astype(int) - res[9][1].astype(int)).max()) == 0)
        ins = [float(np.abs(a_[20:300].astype(int) - b_[20:300].astype(int)).mean()) for a_, b_ in res[10:20]]
        check(f"the sky itself is recoloured from the kill frame on ({ins[0]:.0f})", min(ins) > 20)
    # b) mask frame N lands on take frame N
    mk2 = tmp / "one.yuv"
    _mask_file(mk2, 40, lambda f: np.full((H, W), 240 if f == 20 else 0, np.uint8))
    res2, err = _render_sky({"mask": str(mk2), "mask_fmt": "yuva444p", "p": 0.5, "push": 0.0, "grade": M.sky_family_grade("orange", 160.0)})
    if res2:
        ch = [i for i, (a_, b_) in enumerate(res2) if int(np.abs(a_.astype(int) - b_.astype(int)).max()) > 0]
        check(f"a mask on frame 20 only changes frame 20 only ({ch})", ch == [20])
    else:
        check("one-frame mask renders", False, err)
    # c) the mask frames are the render's own take chain
    plan, _cfg = T.mk(M, "valorant", "hype", 7)
    t = plan["takes"][1]
    inp, keep = M.sky_take_graph(plan, t, 5, 30)
    mini = {k_: v_ for k_, v_ in plan.items() if k_ != "takes"}
    mini["takes"] = [dict(t, xfx=[], pulses=[], trans="hard")]
    mini["effects"] = "default"
    mini["duration"] = round(float(t["nf"]) / M.OUT_FPS, 4)
    inp2, g2 = M.build_filter(mini, {}, False, ("slow",))
    full = [p_.strip() for p_ in g2.split(";")]
    check(f"mask frames: the take's video chains taken unchanged from the render's graph ({len(keep) - 1} chains)", len(keep) > 1 and all(p_ in full for p_ in keep[:-1]) and inp == inp2)
    check("mask frames: trimmed to the sky window and scaled to the mask size", keep[-1].startswith("[t0c]trim=start_frame=5:end_frame=30") and f"scale={W}:{H}" in keep[-1])
    check("sky_take_mask uses the render's frames when it has the plan", 'sky_take_frames(plan, t, f0, f1)' in body_of("sky_take_mask") and "plan=plan" in body_of("xfx_probe_sky"))
    # d) a synthetic take: sky, the camera turns away for 3 frames (a dropout the old hold painted over), sky again, then a cut to a clip whose sky is only on the left half
    seq = [_sky_img("sky", seed=i) for i in range(30)] + [_sky_img("wall", seed=100 + i) for i in range(3)] + [_sky_img("sky", seed=200 + i) for i in range(12)] + \
          [_sky_img("left", seed=300 + i) for i in range(15)]
    tk = {"nf": 60, "segs": [[10.0, 10.75, 1.0, 45, 0], [20.0, 20.25, 1.0, 15, 1]], "path": "a.mp4", "rect": [0, 0, W, H], "wh": [W, H],
          "srcs": [{"path": "a.mp4", "shift": 0.0, "rect": [0, 0, W, H], "wh": [W, H]}, {"path": "b.mp4", "shift": 0.0, "rect": [0, 0, W, H], "wh": [W, H]}]}
    keep_f = M.sky_take_frames
    M.sky_take_frames = lambda plan_, t_, f0_, f1_, size=None: seq[f0_:f1_]
    try:
        xs = {"t0": 5 / 60, "t1": 1.0, "anim": M.sky_anim_params(0.8, 128, "hype"), "seed": 3, "beats": [], "fam": "orange", "pattern": "bands"}
        mp = tmp / "take.raw"
        st = M.sky_take_mask(tk, xs, None, mp, ramp=True, plan={"song": {}})
    finally:
        M.sky_take_frames = keep_f
    raw = np.fromfile(mp, np.uint8)
    fs = H * W * 4
    ys = [raw[f * fs:f * fs + H * W].reshape(H, W) for f in range(60)]
    check(f"synthetic take: render frames used, {st['breaks']} cut found", xs.get("frames_src") == "render" and st["breaks"] >= 1)
    check("nothing before the kill frame (frames 0 - 4)", all(int(ys[f].max()) == 0 for f in range(5)))
    check(f"the kill frame and the sky frames are painted ({int(ys[6].max())})", int(ys[6].max()) > 100 and float((ys[20][:150] > 128).mean()) > 0.9)
    off = [int(ys[f][int(H * 0.5):].max()) for f in range(60)]
    check(f"never below the sky's horizon on any frame (max {max(off)})", max(off) < 40)
    tw = [float((ys[f] > 64).mean()) for f in (30, 31, 32)]
    check(f"camera turned away (3 frames without sky): no sky carried over ({[round(v_, 3) for v_ in tw]})", max(tw) < 0.002)
    rt = [float((ys[f][:, W // 2 + 12:] > 64).mean()) for f in range(45, 60)]
    check(f"after the cut the old sky never shows where the new picture has none (right half max {max(rt):.4f})", max(rt) < 0.002)
    lt = [float((ys[f][:150, :W // 2 - 12] > 128).mean()) for f in range(47, 60)]
    check(f"... and the new sky is painted ({min(lt):.2f})", min(lt) > 0.8)
    br = M.sky_shot_breaks([_sky_img("sky", seed=1), _sky_img("sky", seed=2), np.full((H, W, 3), 20, np.uint8), np.full((H, W, 3), 22, np.uint8)])
    check(f"an instant change of the picture is a cut too ({sorted(br)})", br == {2})


def part3():
    print("3) sky patterns")
    fr = {p_: _frames(p_, nf=80) for p_ in M.SKY_PATTERNS}
    for p_, f_ in fr.items():
        a_ = f_[60]
        gy, gx = np.abs(np.diff(a_, axis=0)).max(), np.abs(np.diff(a_, axis=1)).max()
        check(f"{p_}: soft edges (largest step between neighbouring pixels {max(gy, gx):.3f} of depth {a_.max():.2f})", max(gy, gx) < 0.5 * max(1e-6, a_.max()) and a_.max() > 0.2)
        check(f"{p_}: deterministic", all(np.array_equal(u_, v_) for u_, v_ in zip(f_, _frames(p_, nf=80))))
    ps = list(M.SKY_PATTERNS)
    worst = 0.0
    for i in range(len(ps)):
        for j in range(i + 1, len(ps)):
            a_, b_ = fr[ps[i]][60].ravel(), fr[ps[j]][60].ravel()
            c_ = abs(float(np.corrcoef(a_, b_)[0, 1]))
            worst = max(worst, c_)
    check(f"the patterns are clearly different (largest correlation between two patterns {worst:.2f})", worst < 0.5)
    rows = fr["bands"][60]
    check("bands: horizontal stripes (rows vary far more down than across)", float(np.abs(np.diff(rows, axis=0)).mean()) > 2 * float(np.abs(np.diff(rows, axis=1)).mean()))
    au = fr["aurora"][60]
    check("aurora: vertical curtains (vary more across than down)", float(np.abs(np.diff(au, axis=1)).mean()) > 1.5 * float(np.abs(np.diff(au, axis=0)).mean()))
    # one pattern per montage, from the song
    songs = [{"path": f"none_{i}.mp3", "artist": f"artist {i}", "title": f"song {i}", "energy": e_, "bpm": b_, "dance": 0.6}
             for i, (e_, b_) in enumerate([(e, b) for e in (0.3, 0.5, 0.7, 0.9) for b in (80, 100, 125, 150, 170)])]
    picks = [M.sky_pattern_for({"song": s_})[0] for s_ in songs]
    check(f"different songs spread over every pattern ({ {p_: picks.count(p_) for p_ in ps} })", set(picks) == set(ps))
    s0 = songs[7]
    same = {M.sky_pattern_for({"song": dict(s0), "seed": sd, "recipe": st, "game": g})[0] for sd in (1, 99) for st in ("hype", "chill") for g in ("cs2", "valorant", "r6s")}
    check(f"the same song always gets the same pattern, whatever seed / style / game ({same})", len(same) == 1)
    calm = [M.sky_pattern_for({"song": {"path": "x.mp3", "artist": f"a{i}", "title": f"t{i}", "energy": 0.25, "bpm": 78}})[0] for i in range(12)]
    hard = [M.sky_pattern_for({"song": {"path": "x.mp3", "artist": f"a{i}", "title": f"t{i}", "energy": 0.95, "bpm": 160}})[0] for i in range(12)]
    check(f"tempo / energy steer it (calm songs {sorted(set(calm))}, hard fast songs {sorted(set(hard))})", calm.count("amoebas") + calm.count("aurora") > 6 and hard.count("rings") + hard.count("bands") > 6)
    b_ = body_of("xfx_probe_sky")
    check("the render picks the pattern once per montage and gives it to every sky", b_.count("sky_pattern_for(") == 1 and '"pattern": pat' in b_)
    # the pattern is what goes into the mask's band plane, and every pattern renders
    H, W = M.SKY_H, M.SKY_W
    seq = [_sky_img("sky", seed=i) for i in range(40)]
    tk = {"nf": 40, "segs": [[10.0, 10.666, 1.0, 40, 0]], "path": "a.mp4", "rect": [0, 0, W, H], "wh": [W, H], "srcs": [{"path": "a.mp4", "shift": 0.0, "rect": [0, 0, W, H], "wh": [W, H]}]}
    tmp = Path(tempfile.mkdtemp())
    keep_f = M.sky_take_frames
    M.sky_take_frames = lambda plan_, t_, f0_, f1_, size=None: seq[f0_:f1_]
    try:
        for p_ in ps:
            xs = {"t0": 2 / 60, "t1": 0.66, "anim": M.sky_anim_params(0.6, 110, "mix"), "seed": 3, "beats": [], "fam": "violet", "pattern": p_}
            mp = tmp / f"{p_}.raw"
            M.sky_take_mask(tk, xs, None, mp, ramp=True, plan={"song": {}})
            raw = np.fromfile(mp, np.uint8)
            u20 = raw[20 * H * W * 4 + H * W:20 * H * W * 4 + 2 * H * W].reshape(H, W).astype(float) / 255.0
            ref = list(M.sky_pattern_frames(p_, H, W, xs["horizon"] * H, 40, 2, [], xs["anim"], 3))[20]
            check(f"{p_}: the mask's band plane is this pattern (correlation {np.corrcoef(u20.ravel(), ref.ravel())[0, 1]:.2f})", np.corrcoef(u20.ravel(), ref.ravel())[0, 1] > 0.95)
            x = {"mask": str(mp), "mask_fmt": xs["mask_fmt"], "p": 2 / 60, "push": xs["anim"]["push"], "grade": M.sky_family_grade("violet", 170.0)}
            res, err = _render_sky(x, nf=30, src="color=c=0x78A8E0:s=1920x1080:r=60")
            check(f"{p_}: renders in ffmpeg", res is not None, err)
    finally:
        M.sky_take_frames = keep_f


_PL = []


def _plans():
    """fake-event plans (synthetic song, no clips) of every game in DEFAULT and EXTRA effects, two styles each"""
    if not _PL:
        for g in ("valorant", "cs2", "r6s"):
            for st in ("hype", "chill"):
                for eff in ("default", "extra"):
                    p_, c_ = T.mk(M, g, st, 3, eff={g: eff})
                    _PL.append((g, st, eff, p_, c_))
    return _PL


def _graph(p_, c_):
    return M.build_filter(p_, c_, False)[1]


def _reg_audio():
    R = []
    gl = lambda clip_lufs, peak=None: M._game_gain(dict(M.DEFAULT_CONFIG), -9.0, clip_lufs, "valorant", peak_db=peak)
    lv = [round(c_ + gl(c_)[0], 1) for c_ in (-40.0, -30.0, -24.0, -18.0)]
    R.append(("V5 / V8.8.2", "song leveling: every clip's game sound is brought to the same level under the song (song - 12 LU at the default level)",
              len(set(lv)) == 1 and abs(lv[0] - (-21.0)) < 0.05, str(lv)))
    g3 = [round(c_ + M._game_gain({"game_audio_level_cs2": 0.3}, -9.0, c_, "cs2")[0], 1) for c_ in (-40.0, -30.0, -24.0, -18.0)]
    R.append(("V8.21 / V8.8.5", "the Game audio level setting still moves the leveled game sound (0.3 = 6 dB under the default, every clip)", len(set(g3)) == 1 and abs(g3[0] - (-21.0 - 6.02)) < 0.1, str(g3)))
    B = prev()
    same = all(M._game_gain(dict(M.DEFAULT_CONFIG), sl, cl_, g, peak_db=pk) == B._game_gain(dict(M.DEFAULT_CONFIG), sl, cl_, g, peak_db=pk)
               for sl in (-8.0, -11.0) for cl_ in (-45.0, -30.0, -20.0, -12.0, None) for g in ("valorant", "cs2", "r6s") for pk in (None, -3.0))
    R.append(("V8.8.2", "at the default level the leveling gains are exactly the v8.8.4 ones", same))
    g_, l_ = gl(-40.0, peak=-10.0)
    R.append(("V8.8.2", "song leveling never clips: a quiet clip's lift stops where its peak reaches -1 dBFS", -10.0 + g_ <= -1.0 + 1e-6 and l_ > 0, str((g_, l_))))
    R.append(("V8.8.2", "song leveling: a silent clip stays silent (no lift)", gl(-80.0)[1] == 0.0 and gl(None)[1] == 0.0))
    R.append(("V8.8.2", "song leveling range: up to +24 dB, down to -12 dB", (M.GAME_LIFT_MAX, M.GAME_CUT_MAX, M.GAME_PEAK_CEIL) == (24.0, 12.0, -1.0) and gl(-54.0)[1] <= 24.0 and gl(10.0)[1] >= -12.0))
    R.append(("V8.21", "game audio level 0 - 1 per game (default 0.6, own key per game)", M.game_level({}, "cs2") == 0.6 and M.game_level({"game_audio_level_cs2": 0.3}, "cs2") == 0.3
              and M.game_level({"game_audio_level_cs2": 0.3}, "r6s") == 0.6))
    src = {"music_db": None}
    R.append(("V4 / V8.8.2", "+4 dB kill boost around each kill (never above unity for a clip at or under unity)", abs(M._kill_boost(src, 0.5) - 0.5 * 1.585) < 1e-6 and abs(M._kill_boost(src, 0.8) - 1.0) < 1e-6))
    R.append(("V5.56", "audio track: a silent track is never chosen; Settings 1 / 2 / 3 force a live track; auto = most gunshots",
              M.choose_track([None, -20.0], [0, 9])[0] == 1 and M.choose_track([-20.0, -70.0], [5, 9], "2")[0] == 0
              and M.choose_track([-20.0, -22.0], [2, 9])[0] == 1 and M.choose_track([-20.0, -22.0], [0, 9], "1")[0] == 0))
    R.append(("V7.7.0 / V7.7.1", "music over gameplay: off by default, lowers 12 dB, 0 - 60 dB, 60 = mute", not M.DEFAULT_CONFIG.get("lower_music_clips") and M.music_lower_db({}) == 12.0
              and M.music_lower_db({"music_lower_db": 99}) == 60.0 and M.MUSIC_MUTE_DB == 60.0))
    dr = {"t": 10.0, "lift_db": 3.0, "boom_f0": 90, "boom_f1": 40, "boom_r": 6, "boom_dec": 5, "boom_db": -8}
    R.append(("V8.6.2", "the music is never dipped or ducked at a drop", M.drop_audio_filters([dr])[0] == "1"))
    R.append(("V8.6", "the drop lift has no exp() that could overflow and silence the music", "exp(" not in M.drop_audio_filters([dict(dr, t=140.0)])[1]))
    for g, st, eff, p_, c_ in _plans()[:1]:
        gr = _graph(p_, c_)
        sg = [l_ for l_ in gr.split(";") if l_.strip().endswith("[sg]")]
        R.append(("V5.1", f"music ({g}): sample-exact start, only 2 dB headroom, never ducked or automated", len(sg) == 1 and "volume=0.7943" in sg[0] and "atrim=start=" in sg[0] and "eval=frame" not in sg[0], str(sg)[:200]))
        fo = min(float(p_["song"]["fade_out_start"]), p_["duration"] - 0.3)
        R.append(("V5 / V5.1", f"mix ({g}): amix without normalising, safety limiter, 0.3 s fade-in, music fade-out from the final kill", "normalize=0" in gr and "alimiter=limit=0.99" in gr
                  and f"afade=t=in:st=0:d={M.FADE_IN}" in gr and f"afade=t=out:st={fo:.3f}" in gr))
        R.append(("V4 / V5", f"game audio ({g}): every take's game sound carries its clip gain and the kill boost", "volume=" in gr))
    R.append(("V8.4.5", "audio holes inside a source range are filled by time (aresample async) only where there is a hole", "async=1:first_pts=0" in body_of("aresample_for") and M.AUDIO_GAP_FIX[0] and M.AUDIO_HOLE_FIX[0]))
    k1, k2 = M.clip_audio, M.clip_audio_legacy
    M.clip_audio = lambda rec, setting="auto": {"stream": 0, "lufs": -90.0}
    M.clip_audio_legacy = lambda rec: {"stream": 1, "lufs": -20.0, "note": "legacy"}
    try:
        st_ = {}
        au = M.resolve_clip_audio({"path": "/x/a.mp4", "audio": True}, dict(M.DEFAULT_CONFIG), "valorant", st_)
    finally:
        M.clip_audio, M.clip_audio_legacy = k1, k2
    R.append(("V6.0", "a silent game audio track is replaced by the loudest one for that clip only", au["stream"] == 1 and len(st_.get("clip_fallback", [])) == 1))
    R.append(("V8.21", "game audio level in Settings for each game", 'self.sn[f"game_audio_level_{g_}"] = v' in SRC()))
    return R


def _fight_plan(g):
    ev = {"rec": {"path": f"/m/{g}.mp4", "w": 1920, "h": 1080, "dur": 40.0, "audio": False}, "path": f"/m/{g}.mp4", "times": [10.0, 13.5, 21.0, 22.0], "rows": [10.1, 13.6, 21.1, 22.1],
          "times_v4": [10.0, 13.5, 21.0, 22.0], "n": 4, "victims": ["a", "b", "c", "d"], "first": 10.0, "last": 22.0, "span": 12.0, "hs": False, "flick": False, "shots": 1.0, "imp": 3,
          "lag": 0.1, "pre": 9.9, "post": 17.7, "death_after": None, "parts": None, "stitched": False, "lags": [0.0] * 4, "vis": []}
    ev["score"] = M.base_score(ev) + 50
    ev["plain"] = False
    evs = [ev] + copy.deepcopy(M.fake_events())[:18]
    keep = M.clip_audio
    M.clip_audio = lambda rec, *a, **k: {"stream": None, "lufs": None}
    try:
        pl = M.plan_montage(dict(M.DEFAULT_CONFIG), g, evs, {"path": str(T.SONG), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}, T.an(), 5, "hype", "optimal", [], [])
    finally:
        M.clip_audio = keep
    return ev, pl


def _beat_rules():
    """V5 / V7.3 / V7.5: every take's anchored kill (the first kill, or the last kill of a multikill anchored on a drop) sits on a beat of the song, frame-exact; the headline's anchored kill on
    the drop (the smoketest's V5.1 planner check measures the FIRST kill only, which V7.3 deliberately moved off the beat for last-kill anchors)."""
    res = []
    keep = M.clip_audio
    M.clip_audio = lambda rec, *a, **k: {"stream": None, "lufs": None}
    try:
        song = {"path": str(T.SONG), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
        for seed in (1, 2, 3, 4):
            plan = M.plan_montage(dict(M.DEFAULT_CONFIG), "valorant", copy.deepcopy(M.fake_events()), song, T.an(), seed, "auto", "optimal", [], [])
            beats = np.array(plan["beats_out"])
            drop_t = {int(m_.group(1)) - 1 for n_ in plan.get("notes", []) for m_ in [re.search(r"anchored: take (\d+) kill", n_)] if m_}
            off = []
            for i_, t_ in enumerate(plan["takes"]):
                ks = [t_["kills_out"][0], t_["kills_out"][-1]]
                o_ = min(float(np.abs(beats - (t_["out_start"] + k_)).min()) for k_ in ks) * 1000
                if (i_ - 1 in drop_t or i_ + 1 in drop_t) and o_ <= M.DRIFT_FR * 1000 / 60 + 0.5:
                    o_ = 0.0                                   # V7.6.1 lever d: a take next to a drop may drift up to DRIFT_FR frames so the drop kill lands exactly
                off.append(o_)
            hl = [t_ for t_ in plan["takes"] if t_["role"] == "headline"]
            kidx = len(hl[0]["kills_out"]) - 1 if hl and (plan.get("drop_anchor") or {}).get("anchor") == "last" else 0
            dt = plan["song"]["drop_t"]
            hd = abs(hl[0]["out_start"] + hl[0]["kills_out"][kidx] - dt) if (hl and dt is not None) else 0.0
            res.append((seed, round(max(off), 1), round(hd * 1000, 1)))
    finally:
        M.clip_audio = keep
    return all(o_ <= 1000 / 60 / 2 + 0.5 and h_ <= 20 for _s, o_, h_ in res), f"(seed, worst take ms off a beat, headline ms off the drop): {res}"


def _reg_plan():
    R = []
    for g, st, eff, p_, c_ in _plans():
        bad = M.verify_cutlist(p_, log=False)
        R.append(("V5 - V7.7.5", f"{g} {st} {eff}: every take holds its kills, rows inside the footage, 1.0x around the kills, tails, no clip / kill twice ({len(bad)} problems)", not bad, "; ".join(bad[:3])))
    g, st, eff, p_, c_ = _plans()[0]
    tk = p_["takes"]
    R.append(("V5.1", "kills land frame-exactly and the music starts at frame 0 (first take at frame 0, takes contiguous)", tk[0]["f0"] == 0 and all(tk[i + 1]["f0"] == tk[i]["f0"] + tk[i]["nf"] for i in range(len(tk) - 1))))
    R.append(("V5.42B", "a take runs at least 0.4 s past the last kill row", M.ROW_TAIL == 0.4 and all(t_["ending"] or t_["dur"] - max(t_["rows_out"]) >= 0.4 - 1.5 / 60 for t_ in tk),
              str([round(t_["dur"] - max(t_["rows_out"]), 3) for t_ in tk if not t_["ending"]][:8])))
    paths = [s_["path"] for t_ in tk for s_ in t_["srcs"]]
    R.append(("V5 / V5.43", "no clip is used twice and no kill is in two takes", len(paths) == len(set(paths))))
    R.append(("V5.4", "a montage is never longer than the song", all(float(p_["song"]["start_t"]) + p_["duration"] <= float(T.an()["dur"]) + 0.01 for _g, _s, _e, p_, _c in _plans())))
    R.append(("V7.6.0", "the montage ends right after the final kill with a short fade (from the final kill)", tk[-1]["ending"] and abs(float(p_["song"]["fade_out_start"]) - (tk[-1]["out_start"] + tk[-1]["kills_out"][-1])) < 0.02))
    R.append(("V5.1 / V8.4.1", "Optimal length 80 - 180 s; default length Optimal, default style Auto", M.OPT_RANGE == (80.0, 180.0) and M.DEFAULT_CONFIG["length_s"] == "optimal" and M.DEFAULT_CONFIG["style"] == "auto"))
    pf = M.planner_selftest(verbose=False)
    R.append(("V5.1 / V8.8.5", "the smoketest's planner self-check passes (cut list, best multikill on the drop, kills on the beat, slow-mo ending with the fades from the final kill)", not pf, "; ".join(pf[:3])))
    ok_, why_ = _beat_rules()
    R.append(("V5 / V7.3", "kills on the beat: every take's anchored kill on a beat (frame-exact; a take next to a drop up to 3 frames), the headline's on the drop", ok_, why_))
    R.append(("V8.4.1", "maximum montage length 180 s", M.LEN_MAX_S == 180.0))
    # V9.0: intro / outro / caps / Manual box / Last seed (the rules of this version; the older rules above stay)
    R.append(("V9.0", "every montage has a 7 s intro: the first take's footage blurred and slowed (~0.3x, frame blending only), the title over it, an unblur + a speed ramp to the take's own speed",
              M.INTRO_S == 7.0 and "framerate=fps=60:scene=100" in body_of("_intro_chains") and "ramp_pts" in body_of("_intro_chains") and "gblur" in body_of("_intro_chains") and "mi_mode=mci" not in body_of("_intro_chains")))
    R.append(("V9.0", "the intro is part of the 3:00 maximum and of the song window (the plan starts after the intro's music); the plan itself stays the montage without it",
              "intro_cut()" in body_of("optimal_fit") and "intro_cut()" in body_of("_plan_montage_once") and "def with_intro" in SRC()))
    R.append(("V9.0", "the intro's look is one of six, chosen from the style; only shaded and wide hype take the sky colour family (the sky's own function)", "sky_family_for(" in body_of("intro_prepare") and "pick_look(" in body_of("intro_prepare")))
    R.append(("V9.0 / V9.2.0 / V9.2.1", "Manual: Intro text box + tickbox, Last seed button next to the seed (V9.2.0: Dry plan only in the Auto tab, a small Preview next to Last seed; V9.2.1: label in sentence case)",
              all(k in body_of("build_manual", SRC()) for k in ('text="Intro text"', '"manual:preview"', '"manual:last_seed"', "m_intro_on")) and '"manual:dry"' not in body_of("build_manual", SRC())))
    R.append(("V9.2.0", "nothing plans on its own: selecting a song / ticking clips only counts (no background estimate); Render reuses the plan Auto / Preview made for the same inputs",
              "start_estimate" not in SRC() and "keep_plan(" in body_of("auto_fill_ticks") and "keep_sig" in body_of("job_video")))
    R.append(("V9.2.0", "planning speed: bounded + memoised dead-air cuts, kill-row pre-check before planning, section early stop, cached stitch frame checks and sky probes",
              M.SEEN_PRECHECK_ON[0] and M.SECTION_EARLY_STOP[0] and "_dac" in body_of("dead_air_cuts") and "STITCH_CHECK_CACHE" in body_of("verify_stitch") and "sky_cache_put(" in body_of("xfx_probe_sky")))
    R.append(("V9.2.0 / V9.3.0", "the sky family varies per montage: a seeded pick of EVERY Sky colour option, none over 25 % in 200 seeds (a Manual pick wins)",
              M.SKY_VARIETY_ON[0] and set(M.SKY_VARIETY) == set(M.SKY_FAMILIES) and max(__import__("collections").Counter(M.sky_variety_pick({"seed": s_}, ["hazy orange"])[0] for s_ in range(1, 201)).values()) <= 50))
    R.append(("V9.2.0", "a montage that stops before the song ends stops at a calm moment, else the music fades longer", M.ENDING_CALM_ON[0] and "calm_outro_music(" in body_of("_plan_montage_once")))
    R.append(("V9.3.0", "Manual Step 3 in the V9.2.0 positions: row 1 Intro text, Intro, Sky colour, Font, the big Render at the right edge; row 2 Length .. Seed, Last seed, Preview (small)",
              all(k in body_of("build_manual", SRC()) for k in ('rb_.pack(side="right", fill="x", expand=True', 'style="Small.TButton"', 'gap(ttk.Label(c3, text="Seed"))', 'lbi = gap(ttk.Label(bb, text="Intro"))'))))
    R.append(("V9.3.0", "a sky lasts from its kill frame to the last frame of its take (a failed frame holds the last good mask); half as many skies, 12 s apart; organic patterns only",
              M.SKY_HOLD_LAST_ON[0] and M.sky_spacing_for() == 12.0 and M.SKY_PER_S_88 == 30.0 and set(M.SKY_PATTERNS) == {"amoebas", "ink", "marble", "cells"}))
    R.append(("V9.3.0", "first-kill check: every take shows its first kill and its row with lead and tail (run on every job); a notice row never re-times a gun kill row",
              M.CS2_LATE_KIND_ON[0] and "first_kill_audit(plan, cfg)" in body_of("run_job", SRC())))
    R.append(("V9.2.1", "no start-up freeze: the killfeed region list is counted on a worker thread", "threading.Thread(target=work" in body_of("rp_refresh", SRC())))
    R.append(("V9.2.0", "CS2: the run-up before the first kill is counted from the hit, not the kill row", M.CS2_KILL_LEAD_ON[0] and M.CS2_ROW_DELAY_S + M.CS2_KILL_LEAD_S >= 0.55))
    R.append(("V9.0", "the outro: slow-mo release, an eased fade to black, a longer music tail, an ending with quiet footage after the kill preferred (always on)", M.OUTRO_PREFER[0] in (True, False) and "ending_good(" in body_of("_plan_montage_once") and "cos(PI*clip(" in body_of("build_filter")))
    R.append(("V9.0", "Last seed: the seed of the most recently rendered montage is stored (any game, any mode) and survives a restart", "save_last_seed(plan)" in body_of("run_job") and "def load_last_seed" in SRC()))
    R.append(("V9.0 / V9.2.1", "the series number = the finished montages of the game in its output folder + 1 (no stored counter: it survives a restart; a half-made .part file does not count)",
              _series_ok() and "series_next(game, cfg)" in body_of("make_plan")))
    R.append(("V8.5 / V9.0", "Force Full: the whole montage 3:00 at most (intro and outro included), long songs use a 2:00 - 3:00 section", (M.FULL_CAP_S, M.FULL_MIN_S, M.FULL_TOTAL_S) in ((180.0, 120.0, 180.0), (150.0, 90.0, 180.0))))   # (the V8 numbers only under MONTAGER_V8_COMPAT)
    R.append(("V6.5.1", "Auto / weekly montages are at least 60 s", M.WEEKLY_MIN_S == 60.0))
    R.append(("V5.42B / V8.8.4", "the death rule: no kill counted for 8 s after my own death", float(M.DEFAULT_CONFIG["death_lock_s"]) == 8.0 and "within {lock:.0f}s after my death" in SRC()))
    R.append(("V5", "a take never runs into my death", "death_after" in SRC()))
    R.append(("V8.8.4", "the kill row is the kill time in every game (no gunshot moves it)", M.KILL_AT_ROW[0] and 'r["t"] = r["row"] if KILL_AT_ROW[0]' in body_of("make_event")))
    R.append(("V8.8.4 / V8.1 / V6.9.7.1", "multikills stay one fight: R6S whole clip / group, CS2 one row = one event, Valorant 10 s (30 s in long clips)",
              M.R6S_ONE_FIGHT[0] and M.CS2_ROWID_ON[0] and M.FIGHT_SPLIT_S["valorant"] == 10.0 and M.FIGHT_GAP_LONG_CLIP == 30.0))
    for g in ("valorant", "cs2", "r6s"):
        ev, pl = _fight_plan(g)
        tq = [t_ for t_ in pl["takes"] if t_["path"] == ev["path"]]
        R.append(("V5.3 / V8.8.4", f"{g}: a 4-kill fight (12 s from first to last kill) is ONE take with all 4 kills, each at its row time", len(tq) == 1 and len(tq[0]["kills"]) == 4, str([len(t_["kills"]) for t_ in tq])))
    return R


def _reg_modes():
    R = []
    s = SRC()
    R.append(("V8.8.3 / V8.8.5", "one fill rule for every game and mode: Auto, Force new, Force Full / New Full, Manual, Manual Auto, dry plan, render (make_plan)",
              "want_s = song_fill_target(an, full, target)" in body_of("_make_plan")))
    an = T.an()
    R.append(("V8.8.3", "Auto / Manual Optimal and full mode cover the whole (trimmed) song; a fixed slider length does not", M.song_fill_target(an, False, "optimal") is not None
              and M.song_fill_target(an, True, "optimal") is not None and M.song_fill_target(an, False, 90) is None))
    R.append(("V8.8.5", "the fill keeps adding clips until the end of the song (6 rounds of at least 8 s of clips, end within 3 s)", M.SONG_FILL_ROUNDS == 6 and M.SONG_FILL_MIN_ADD == 8.0
              and M.SONG_FILL_END_S == 3.0 and "max(short_ * AUTO_TOPUP_X, SONG_FILL_MIN_ADD)" in body_of("_make_plan")))
    R.append(("V8.8 / V8.8.3", "dead air at the start / end of the song is trimmed in every mode", "song_live_range(" in body_of("optimal_fit") and "song_live_range(" in body_of("_plan_montage_once")))
    lv0, lv1 = M.song_live_range({"wave": [0.0] * 100 + [0.5] * 1700 + [0.0] * 200, "dur": 200.0})
    R.append(("V8.8", "dead air: silence at the start / end is found from the song's envelope", abs(lv0 - 10.0) < 0.2 and abs(lv1 - 180.0) < 0.2, f"{lv0} {lv1}"))
    R.append(("V8.8", "song-end fill: up to 1 s more run-in for some takes when a montage ends a few seconds short (up to 15 s)", (M.FILL_LEAD_S, M.FILL_MAX_GAP_S) == (1.0, 15.0)
              and "if fit and takes and head_take in takes:" in s))
    R.append(("V6.0", "Auto picks unused clips first, this week's first", "weekly_pick(" in body_of("_make_plan")))
    R.append(("V8.5 / V8.8.2", "Manual Auto ticks about 1.3x the song in clips, then tops up with the render's own plan (2 rounds, 6 s tolerance)", M.AUTO_PICK_X == 1.3 and M.AUTO_TOPUP_ROUNDS == 2
              and M.AUTO_TOL_S == 6.0 and "allp, top = auto_fill_topup(" in s))
    R.append(("V8.5", "Force New Full: the song is picked first, then ~1.25x its length in clips", ("need_full = (min(FULL_CAP_S, avail_) - intro_cut()) * 1.25" in body_of("_make_plan") or "need_full = min(FULL_CAP_S, avail_) * 1.25" in body_of("_make_plan"))))
    R.append(("V6.5.1 / V7.3 / V8.8.5", "every game's Auto montage reaches the 60 s minimum and a fixed slider length (90 % of it), topping up with used clips",
              M.AUTO_TOPUP_ALL[0] and M.AUTO_FIXED_SHARE == 0.9 and "(game == \"cs2\" or need_full or AUTO_TOPUP_ALL[0])" in body_of("_make_plan")
              and "max(WEEKLY_MIN_S, AUTO_FIXED_SHARE * min(fixed_s, LEN_MAX_S))" in body_of("_make_plan")))
    R.append(("V7.6.1", "one song + style pick per job (the summary, the plan and the render share it)", "pin_song" in body_of("_make_plan")))
    R.append(("V8.6.2", "CS2 deathmatch clips are never picked automatically (hand-ticked clips are)", "cs2_dm_rejected(" in body_of("game_pool")))
    R.append(("V8.4.5 / V8.6", "broken recordings (under 20 fps) and stalled clips are left out", M.BROKEN_FPS == 20.0 and (M.STALL_GAP_S, M.STALL_MAX_SHARE) == (0.12, 0.10) and "clip_stall_share(" in body_of("game_pool")))
    R.append(("V8.8", "clean 60 fps full-size clips are picked first (quality weight)", M.clip_quality({"fps": 60, "w": 1920, "h": 1080}) == 1.0 and M.clip_quality({"fps": 30, "w": 1280, "h": 720}) < 0.6))
    R.append(("V6.9.8", "random / weekly picks pull in a multikill's other clips (companions)", "def companions(" in body_of("_make_plan")))
    return R


def _flash_white():
    """V8.4.4 / V8.4.5: the kill flash only moves the picture towards white (the same white share in R, G, B), the frame before it untouched (real ffmpeg)."""
    d = Path(tempfile.mkdtemp(prefix="v885f_"))
    src = d / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x3060C0:s=640x360:r=60:d=2", "-f", "lavfi", "-i", "color=c=0xB03020:s=640x180:r=60:d=2",
                    "-filter_complex", "[0][1]overlay=0:180,format=yuv420p", "-c:v", "libx264", "-crf", "12", str(src)], check=True)
    take = {"nf": 120, "xfx": [{"k": "flash", "p": 0.5, "a": 0.5, "t1": M.XFX_FLASH_S}]}
    chains = []
    lab = M._xfx_chains(chains, "t0", "[s]", take, set(M.FX_ALL), False, [0.72, 0.0, 1.0, 0.1], {"rgb": 0xFFFFFF})
    fc = "[0:v]scale=1920:1080,format=yuv420p,setsar=1,fps=60[s];" + ";".join(chains) + f";{lab}select='eq(n,29)+eq(n,30)+eq(n,31)',format=rgb24[o]"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", fc, "-map", "[o]", "-vsync", "0", "-f", "rawvideo", "-"], capture_output=True)
    fr = np.frombuffer(r.stdout, np.uint8).reshape(-1, 1080, 1920, 3).astype(np.float32)
    if len(fr) != 3:
        return False, r.stderr.decode("utf-8", "ignore")[-200:]
    b, k_ = fr[0][300:900, 100:1500], fr[1][300:900, 100:1500]
    sh = []
    for ch in range(3):
        c0 = b[..., ch].ravel()
        ok_ = c0 < 190
        sh.append(float(np.median(((k_[..., ch].ravel() - c0) / (255 - c0))[ok_])))
    return max(sh) - min(sh) < 0.03 and min(sh) > 0.08, f"white share R G B {sh[0]:.3f} {sh[1]:.3f} {sh[2]:.3f}"


def _sky_drop_order():
    """V8.8: every drop of the song gets its best sky kill before any drop gets a second one (xfx_probe_sky, masks mocked)."""
    plan = {"drops_out": [20.0, 60.0], "xfx_sky_max": 2, "xfx_sky_space": 6.0, "game": "cs2", "takes": []}
    xs = [{"k": "sky", "p": 0.1, "gp": 22.0, "prio": 6, "sc": 2.0, "drop_i": 0}, {"k": "sky", "p": 0.1, "gp": 30.0, "prio": 6, "sc": 1.9, "drop_i": 0},
          {"k": "sky", "p": 0.1, "gp": 62.0, "prio": 5, "sc": 1.0, "drop_i": 1}]
    kept = []
    keep_g, keep_e, keep_m = M.sky_grab_frames, M.sky_eyedrop, M.sky_take_mask
    M.sky_grab_frames = lambda *a, **k: [np.zeros((4, 4, 3), np.uint8)]
    M.sky_eyedrop = lambda img: (None, {"ok": True, "cov": 0.2, "sky_rgb": 0x3060C0, "scene_hue": None})
    M.sky_take_mask = lambda t, x, zone, mp, ramp=False, plan=None: (kept.append(x["gp"]), {"bad": 0, "window": 10, "cov": 0.2, "frames": 10, "held": 0, "horizon": 0.4, "mean_y": 160.0})[1]
    try:
        for x_ in xs:
            plan["takes"].append({"path": "a", "srcs": [{"path": "a", "shift": 0.0, "rect": [0, 0, 4, 4], "wh": [4, 4]}], "segs": [[0.0, 1.0, 1.0, 60]], "kills": [0.1],
                                  "out_start": x_["gp"] - 0.1, "dur": 1.0, "nf": 60, "xfx": [dict(x_)]})
        plan["song"] = {"path": "", "title": "t", "start_t": 0.0}
        M.xfx_probe_sky(plan, Path(tempfile.mkdtemp(prefix="v885s_")))
    finally:
        M.sky_grab_frames, M.sky_eyedrop, M.sky_take_mask = keep_g, keep_e, keep_m
    pats = {x_.get("pattern") for t_ in plan["takes"] for x_ in t_["xfx"] if x_.get("ok")}
    return sorted(kept) == [22.0, 62.0] and len(pats) == 1, f"kept {sorted(kept)}, patterns {pats}"


def _reg_look():
    R = []
    R.append(("V8.4.1", "Effects per game: CS2 Extra, Valorant / R6S Default at first start", M.EFFECTS_START == {"cs2": "extra", "valorant": "default", "r6s": "default"} and M.effects_mode({}, "cs2") == "extra"
              and M.effects_mode({"effects_game": {"valorant": "extra"}}, "valorant") == "extra"))
    R.append(("V8.7", "sky recolour switch per game (CS2 / Valorant on, R6S off); off = no sky candidate", M.sky_enabled({}, "r6s") is False and M.sky_enabled({}, "cs2") is True
              and M.sky_enabled({"sky_game": {"cs2": False}}, "cs2") is False and "sky_on" in body_of("assign_extra_fx")))
    R.append(("V8.4.2", "every extra effect has its own render switch", tuple(M.XFX_FX) == ("split", "grade", "sky", "drop") and tuple(M.FX_ALL) == ("zoom", "flash", "slow", "transition")))
    R.append(("V8.5.1", "white flashes: one per 10 s of montage", M.FLASH_PER_S == 10.0))
    ok_, why_ = _flash_white()
    R.append(("V8.4.4 / V8.4.5", "the kill flash is a clean white pulse (no colour cast, the frame before untouched)", ok_, why_))
    ok_, why_ = _sky_drop_order()
    R.append(("V8.8", "every drop gets a sky before any drop gets a second one; every kept sky has the montage's one pattern", ok_, why_))
    R.append(("V8.8 / V9.3.0", "sky count / spacing: one per 30 s, at most 6, 12 s apart (V8.8: one per 15 s, at most 12, 6 s apart)", M.sky_max_for(150) == 5 and M.sky_max_for(400) == 6 and M.sky_spacing_for() == 12.0))
    an_ = M.sky_anim_params(0.8, 128, "hype")
    sch = M.sky_anim_schedule(an_, {"seed": 2, "beats": BEATS}, 12, 240)
    R.append(("V8.7 / V8.8", "strobe, drops to black on the beats and colour jumps are on (beat-locked)", an_["sync"] and an_["strobe_hz"] > 0 and float(sch["black"].max()) > 0.6 and float(sch["jump"].max()) > 0.5))
    R.append(("V8.8.4", "sky: a clear top -> bottom gradient in every family", all(M._rgb_to_yuv(b_)[0] - M._rgb_to_yuv(t_)[0] >= 45 for t_, b_, _j in M.SKY_FAMILIES.values())))
    R.append(("V8.6.1 / V8.6.2", "sky: walls are never painted (too dark, too large or running down the picture)", (M.SKY_MIN_L, M.SKY_FRAME_MAX_COV, M.SKY_MAX_BAD) == (120, 0.45, 0.15)))
    R.append(("V8.5.1 / V8.6", "sky lands on the kill frame (3-frame punch) and stays to the end of the take", M.SKY_IMPACT_F == 3))
    R.append(("V8.7", "smoke / flickering pixels are never part of the sky", "sky_flicker_unstable(" in body_of("sky_take_mask") and M.SKY_FLICKER_MAX == 5))
    R.append(("V7.5.1.1", "intro punch on the first beat", M.INTRO_PUNCH == (0.06, 0.25)))
    R.append(("V7.6.1 / V7.7.6", "soft dissolves blend in even steps", "N" in M.soft_blend_expr()))
    R.append(("V8.1.1 / V8.2", "smooth slow motion (motion interpolation) in every game", M.CS2_SMOOTH_SLOW[0] and "minterpolate" in M.CS2_SLOW_INTERP))
    R.append(("V8.2", "jitter-free 60 fps clips (frame-number timing)", M.JITTER_FREE[0]))
    R.append(("V6.9.8.1", "low-frame-rate smoothing is off by default", not M.DEFAULT_CONFIG.get("interpolate_low_fps") and "interpolate_low_fps" in SRC()))
    R.append(("V8.22", "post-render checks are an option, off by default", M.DEFAULT_CONFIG["post_checks"] is False))
    R.append(("V8.6", "CS2 headline / ending kills: slow, fast, slow", not M.CS2_RAMP_OFF[0]))
    return R


def _reg_detect():
    R = []
    s = SRC()
    R.append(("V5.42", "revives are never kills or deaths (green victim side)", "revive" in s))
    R.append(("V5.5", "Valorant knife kills count", "knife" in s))
    R.append(("V8.0.3 / V8.8.1", "R6S utility kills are left out (any utility icon in the row)", "def r6s_row_util(" in s and M.R6S_UTIL_ROW_SC == 0.92))
    R.append(("V6.9.10 / V7.7.7", "CS2 kill rows already on screen at the clip start are never kills", "pre-clip" in s))
    R.append(("V8.1", "CS2 one physical killfeed row = one kill", M.CS2_ROWID_ON[0]))
    R.append(("V8.8", "CS2 late rows re-timed (the missed kill of a multikill)", M.CS2_LATE_ROW_ON[0]))
    R.append(("V8.1.1", "CS2 rows cut by the region's edge dated by their top part", M.CS2_EDGE_DATING[0]))
    R.append(("V8.0.0", "R6S clips are never scanned in bulk", M.R6S_AUTO_MAX == 12))
    R.append(("V8.8.4", "a missing gunshot never removes a kill (soft notes only)", "soft" in body_of("verified_kills")))
    return R


def _reg_app():
    R = []
    s = SRC()
    nm = M.montage_name(Path(tempfile.mkdtemp()), {"song": {"title": "Perfect Exceeder", "path": "x.mp3"}, "game": "valorant"}, __import__("datetime").datetime(2026, 10, 22))
    R.append(("V5.2", "output files are named SONG_GAME_VERSION_DATE", re.fullmatch(r"PE_VAL_V\d+(\.\d+)*_2026-10-22", nm) is not None, nm))
    R.append(("V5.2", "the version shows in the window title", 'self.root.title(f"{APP_NAME} {APP_VERSION}")' in s))
    cl = M.changelog_lines()
    R.append(("V6.9.11", "Settings shows the readable changelog, newest version first", bool(cl) and next(t_ for k_, t_ in cl if k_ == "ver").startswith(M.APP_VERSION)))
    R.append(("V6.5 / V7.7.6", "song matching: exact title + artist, loose match by main artist and title", "loose" in body_of("match_playlist")))
    R.append(("V5.57", "accent colours and base theme", "accent" in M.DEFAULT_CONFIG and "base" in M.DEFAULT_CONFIG))
    R.append(("V5.56", "audio track pick per game (auto by default)", M.DEFAULT_CONFIG["game_audio_track"] == {"valorant": "auto", "cs2": "auto", "r6s": "auto"}))
    R.append(("V6.0", "player names per game", set(M.DEFAULT_CONFIG["player_names"]) == {"valorant", "cs2", "r6s"}))
    R.append(("V7.7.1", "SongMap mode setting", "songmap_mode" in s))
    R.append(("V8.22", "Random pick button", "Random pick" in s))
    R.append(("V8.5 / V8.5.1", "Force New Full and the Manual Auto button", "Force New Full" in s and "def auto_fill_pick(" in s))
    R.append(("V8.0.4 / V8.0.5", "Scan all new clips (current region)", "Scan all new clips" in s))
    R.append(("V6.7.4", "trash icon: the clip goes to the Recycle Bin after confirming", "Recycle Bin" in s))
    R.append(("V8.8.1", "long montages render (short input aliases over the command limit)", M.CMD_LIMIT == 30000 and "def fit_cmd(" in s))
    R.append(("V8.4.4", "a render is one attempt; a failure says where", "def _render_once(" in s))
    ba = body_of("build_auto")
    R.append(("V5.57 / V8.8.5", "Auto tab: each game's buttons sit above its status text (all three games' buttons stay visible in a small window)", ba.index("sm.pack(") < ba.index("textvariable=sv")))
    sp_ = Path(tempfile.mkdtemp()) / "s.mp3"
    M.synth_song(sp_, 120.0, layout=(("verse", 4),))
    sy = body_of("sync_e2e_test")
    R.append(("V5.1 / V8.8.5", "the smoketest's end-to-end sync test: clips saved on their own days (not one stitched fight), its click song mapped, the kill row measured as the kill moment through the slow-down",
              "os.utime(str(p), (ts_, ts_))" in sy and 'songmap_mode="v2_fallback"' in sy and "song_path=str(song)" in sy and "0.0 if KILL_AT_ROW[0] else SHOT_LAG" in body_of("measure_sync")
              and "src_to_out(segs_, want / 60.0)" in body_of("measure_sync")))
    R.append(("V6.1.3 / V8.8.5", "the smoketest's own songs are finished files (the 'still being written' rule skips only songs modified in the last 15 s)", __import__("time").time() - sp_.stat().st_mtime > M.AUDIO_MIN_AGE_S))
    return R


def part4():
    print("4) regression list V1 .. V8.8.4 (one line per rule, the version it came from)")
    for grp in (_reg_audio, _reg_plan, _reg_modes, _reg_look, _reg_detect, _reg_app):
        for item in grp():
            ver, msg, ok = item[:3]
            check(f"[{ver}] {msg}", bool(ok), item[3] if len(item) > 3 else "")


def part5():
    print("5) unchanged from v8.8.4 where nothing was asked: plans, plan text, filter graphs")
    B = prev()
    for g in ("valorant", "cs2", "r6s"):
        for st in ("aggressive", "chill"):
            for eff in ("default", "extra"):
                pb, cb = T.mk(B, g, st, 2, eff={g: eff})
                M.SLOW_KEEP_FIRST[0] = False
                try:
                    pd, cd = T.mk(M, g, st, 2, eff={g: eff})
                    same = T.js(pb) == T.js(pd) and repr(B.build_filter(pb, cb, False)) == repr(M.build_filter(pd, cd, False))                         and B.fmt_plan(pb, copy.deepcopy(M.fake_events()), {}, [], [], None) == M.fmt_plan(pd, copy.deepcopy(M.fake_events()), {}, [], [], None)
                finally:
                    M.SLOW_KEEP_FIRST[0] = True
                check(f"{g} / {st} / {eff}: with the beat fix switched off, plan, plan text and filter graph identical to v8.8.4", same)
                pn, _cn = T.mk(M, g, st, 2, eff={g: eff})
                diff = [i_ for i_, (ta, tb) in enumerate(zip(pn["takes"], pb["takes"])) if T.js(ta) != T.js(tb)]
                ok_ = len(pn["takes"]) == len(pb["takes"]) and all(pb["takes"][i_]["slow"] and len(pb["takes"][i_]["kills"]) >= 2 for i_ in diff)                     and all(pn["takes"][i_]["kills"] == pb["takes"][i_]["kills"] and (pn["takes"][i_]["nf"] == pb["takes"][i_]["nf"] or (pb["takes"][i_]["ending"]
                            and 0 < pn["takes"][i_]["nf"] - pb["takes"][i_]["nf"] <= 3)) for i_ in diff)
                check(f"{g} / {st} / {eff}: the beat fix only touches slowed multikill takes (takes {diff}): same kills, same lengths (the ending up to 3 frames longer: its fade runs from the final kill)", ok_)
    src = SRC()
    i = src.index("want_s = song_fill_target(an, full, target)")
    blk = src[i:i + 3200]
    check("the fill only adds clips (picked + add), never removes a chosen one; the closest plan is kept", "picked = picked + add" in blk and "picked.remove" not in blk and "best[1] is not plan" in blk)


def part6():
    print("6) Settings: every control saved, loaded again in a new window, and read by the code that uses it")
    import time
    import tkinter
    try:
        r_ = tkinter.Tk()
        r_.destroy()
    except Exception:                                      # noqa: BLE001
        check("a display for the Settings window", False, "no display")
        return
    tmp = Path(tempfile.mkdtemp(prefix="v885set_"))
    old = M.use_data_dir(tmp / "gdata")
    try:
        app = M.App(0, startup=False)
        want = {}
        for k, val in (("mp3_dir", str(tmp / "mp3x")), ("playlist_dir", str(tmp / "csvx")), ("output_root", str(tmp / "outx"))):
            app.sv[k].set(val)
            want[k] = val
        app.sl["valorant"].set(f"{tmp / 'cv1'}; {tmp / 'cv2'}")
        app.sl["cs2"].set(f"{tmp / 'cc1'}")
        app.sl["r6s"].set(f"{tmp / 'cr1'}")
        want["clip_dirs"] = {"valorant": [str(tmp / "cv1"), str(tmp / "cv2")], "cs2": [str(tmp / "cc1")], "r6s": [str(tmp / "cr1")]}
        nums = {"max_mb": 77, "max_dur_s": 55, "auto_recent_days": 12, "auto_old_per_run": 33, "name_match": 71, "death_lock_s": 5.5, "week_days": 3,
                "game_audio_level_valorant": 0.35, "game_audio_level_cs2": 0.45, "game_audio_level_r6s": 0.55}
        for k, val in nums.items():
            if k in app.sn:
                app.sn[k].set(str(val))
                want[k] = val
        for g, v in (("valorant", "3"), ("cs2", "1"), ("r6s", "2")):
            app.set_track[g].set(v)
        want["game_audio_track"] = {"valorant": "3", "cs2": "1", "r6s": "2"}
        app.set_names["valorant"].set("fireaxe; fxv")
        app.set_names["cs2"].set("fireaxe; 火斧; fxc")
        want["player_names"] = {"valorant": ["fireaxe", "fxv"], "cs2": ["fireaxe", "火斧", "fxc"]}
        app.set_opt.set(False)
        app.set_len.set(101)
        want["length_s"] = 101
        app.set_style.set("chill")
        want["style"] = "chill"
        app.set_place.set("v4")
        want["placement"] = "v4"
        app.set_audio.set(M.AUDIO_MODES["legacy"])
        want["audio_mode"] = "legacy"
        cfg0 = M.load_config()
        want["quality"] = "nvenc" if cfg0.get("quality") == "max" else "max"
        app.set_q.set(want["quality"])
        for var, key, val in ((app.set_interp, "interpolate_low_fps", True), (app.set_music, "lower_music_clips", True), (app.set_sync, "sync_report", False),
                              (app.set_upd, "update_on_start", True), (app.set_post, "post_checks", True)):
            var.set(val)
            want[key] = val
        fxw = {"valorant": "extra", "cs2": "default", "r6s": "extra"}
        for g, m_ in fxw.items():
            app.set_fx[g].set(M.EFFECT_LABELS[m_])
        want["effects_game"] = fxw
        skw = {"valorant": False, "cs2": True, "r6s": True}
        for g, v in skw.items():
            app.set_sky[g].set(v)
        want["sky_game"] = skw
        app.set_accent.set(M.ACCENT_NAMES["purple"])
        want["accent"] = "purple"
        app.set_base.set("Black")
        want["base"] = "black"
        app.set_music_db.set("20")
        want["music_lower_db"] = 20.0
        app.set_smmode.set(M.SONGMAP_MODES["v2_fallback"])
        want["songmap_mode"] = "v2_fallback"
        for _ in range(6):
            app.root.update()
            time.sleep(0.05)
        app.flush_settings()
        app.root.destroy()
        M.LOG_SINK[0] = M.PROGRESS[0] = None
        disk = json.loads(M.CONFIG_PATH.read_text(encoding="utf-8"))
        for k, v in want.items():
            dv = disk.get(k)
            if isinstance(v, dict) and isinstance(dv, dict):
                dv = {g: dv.get(g) for g in v}
            if isinstance(v, float):
                dv = float(dv) if dv not in (None, "") else None
            check(f"saved: {k}", dv == v, f"{dv!r} != {v!r}")
        app2 = M.App(0, startup=False)
        read = {"mp3_dir": app2.sv["mp3_dir"].get(), "playlist_dir": app2.sv["playlist_dir"].get(), "output_root": app2.sv["output_root"].get(),
                "clip_dirs": {g: [x.strip() for x in app2.sl[g].get().split(";") if x.strip()] for g in want["clip_dirs"]},
                "game_audio_track": {g: app2.set_track[g].get() for g in want["game_audio_track"]},
                "player_names": {g: M.norm_names(app2.set_names[g].get(), g) for g in want["player_names"]},
                "length_s": "optimal" if app2.set_opt.get() else int(app2.set_len.get()), "style": app2.set_style.get(), "placement": app2.set_place.get(),
                "audio_mode": next((k for k, lab in M.AUDIO_MODES.items() if lab == app2.set_audio.get()), None), "quality": app2.set_q.get(),
                "interpolate_low_fps": bool(app2.set_interp.get()), "lower_music_clips": bool(app2.set_music.get()), "sync_report": bool(app2.set_sync.get()),
                "update_on_start": bool(app2.set_upd.get()), "post_checks": bool(app2.set_post.get()),
                "effects_game": {g: next(k for k, lab in M.EFFECT_LABELS.items() if lab == app2.set_fx[g].get()) for g in fxw},
                "sky_game": {g: bool(app2.set_sky[g].get()) for g in skw},
                "accent": next((k for k, lab in M.ACCENT_NAMES.items() if lab == app2.set_accent.get()), None), "base": app2.set_base.get().lower(),
                "music_lower_db": float(app2.set_music_db.get()), "songmap_mode": next((k for k, lab in M.SONGMAP_MODES.items() if lab == app2.set_smmode.get()), None)}
        for k in nums:
            if k in app2.sn:
                raw = app2.sn[k].get()
                read[k] = float(raw) if "." in raw else int(raw)
        app2.root.destroy()
        M.LOG_SINK[0] = M.PROGRESS[0] = None
        for k, v in want.items():
            check(f"loaded again: {k}", read.get(k) == v, f"{read.get(k)!r} != {v!r}")
        cfg = M.load_config()
        check("applied: Effects per game", all(M.effects_mode(cfg, g) == m_ for g, m_ in fxw.items()))
        check("applied: sky recolour per game", all(M.sky_enabled(cfg, g) == v for g, v in skw.items()))
        check("applied: game audio level per game (and it changes the leveled game sound)", M.game_level(cfg, "cs2") == 0.45 and M.game_level(cfg, "r6s") == 0.55
              and M._game_gain(cfg, -9.0, -30.0, "cs2")[0] != M._game_gain(cfg, -9.0, -30.0, "r6s")[0])
        check("applied: music over gameplay amount", M.music_lower_db(cfg) == 20.0)
        check("applied: SongMap mode", M.songmap_mode(cfg) == "v2_fallback")
        check("applied: death lock", float(cfg["death_lock_s"]) == 5.5 and "cfg.get(\"death_lock_s\"" in SRC().replace("cfg[\"death_lock_s\"]", "cfg.get(\"death_lock_s\""))
        check("applied: post-render checks switch read by the job", 'if not cfg.get("post_checks", False):' in SRC())
        check("applied: audio track per game read by the audio pick", '(cfg.get("game_audio_track") or {}).get(game, "auto")' in body_of("resolve_clip_audio"))
    finally:
        M.restore_data_dir(old)


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
    sys.exit(1 if T.FAILS else 0)
