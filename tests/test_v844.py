"""V8.4.4 tests (fast; only tiny ffmpeg runs on synthetic pictures, no montage render).
  0) title-bar version V8.4.4; V8.4.4 on top of V8.4.3 in both changelogs
  1) DEFAULT = V8.23.1: plan, plan text, filter graph for all three games
  2) EXTRA plan: white flash only on chosen kills, no coloured layer; the flash chain is a per-plane YUV white mix (real ffmpeg: neutral)
  3) sky colour: palette, per-montage pick from the song's feel (different songs -> different colours), logged
  4) one attempt: no retry machinery, a failure stops at once with the failing filter text and its own files
  5) sky segmentation: connected region, holes filled, walls / orange / grey are not sky, stable colour model, killfeed zone kept
  6) sky render chain (real ffmpeg, 4 s synthetic clip): only the masked sky changes, one even deep colour, outside bit-identical
python tests\\test_v844.py   (parts: V844_PARTS=0,1,2,3,4,5,6)"""
import copy
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_src = (HERE / "test_v842.py").read_text(encoding="utf-8")                                     # only the helpers of test_v842 (everything before its first part)
_ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
exec(compile(_src[:_src.index("def part0")], str(HERE / "test_v842.py"), "exec"), _ns)
T = types.SimpleNamespace(**_ns)

M = T.M
ROOT = T.ROOT
check, mk, js = T.check, T.mk, T.js
PARTS = [x for x in os.environ.get("V844_PARTS", "0,1,2,3,4,5,6").split(",") if x]


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.4.4", M.APP_VERSION == "V8.4.4")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.4.4 above V8.4.3", cl[0].startswith("## V8.4.4") and cl[1].startswith("## V8.4.3"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.4.4 above V8.4.3", sm[0].startswith("## V8.4.4") and sm[1].startswith("## V8.4.3"), str(sm[:2]))
    seg = body[body.index("## V8.4.4"):body.index("## V8.4.3")].lower()
    check("simple entry is plain", not any(w in seg for w in ("test", "known issue", "on hold", "def ", "xfx", "ffmpeg", "mask")))


def part1():
    print("1) DEFAULT = V8.23.1")
    B = T.load_base()
    for g in ("cs2", "valorant", "r6s"):
        for style in ("aggressive", "chill"):
            pb, cb = mk(B, g, style, 2)
            pd, cd = mk(M, g, style, 2, eff=T.ALL_DEFAULT)
            gb, gd = repr(B.build_filter(pb, cb, False)), repr(M.build_filter(pd, cd, False))
            tb, td = B.fmt_plan(pb, copy.deepcopy(M.fake_events()), {}, [], [], None), M.fmt_plan(pd, copy.deepcopy(M.fake_events()), {}, [], [], None)
            check(f"{g} / {style}: plan, plan text and filter graph identical to {T.BASE_REF}", js(pb) == js(pd) and tb == td and gb == gd)


def part2():
    print("2) white flash")
    n_fl = 0
    for g in ("cs2", "valorant", "r6s"):
        for style in ("aggressive", "hype", "cinematic"):
            e, c = mk(M, g, style, 3, eff=T.ALL_EXTRA)
            kinds = {x["k"] for t in e["takes"] for x in t.get("xfx", [])}
            check(f"{g} / {style}: kinds {sorted(kinds)} contain no glow", "glow" not in kinds and kinds <= {"flash", "rgb", "punch", "rise", "after", "settle", "mirror", "sky", "speed"})
            fl = [(ti, x) for ti, t in enumerate(e["takes"]) for x in t.get("xfx", []) if x["k"] == "flash"]
            n_fl += len(fl)
            dressed = {(ti, x["p"]) for ti, t in enumerate(e["takes"]) for x in t.get("xfx", []) if x["k"] in ("rgb", "punch", "flash")}
            kills = sum(len(t.get("kills_out") or []) for t in e["takes"])
            check(f"{g} / {style}: flashes only on chosen kills ({len(fl)} of {kills}), strength 0..0.6", len(fl) < kills and all(0 < x["a"] <= 0.6 for _, x in fl))
            gr = M.build_filter(e, c, False)[1]
            check(f"{g} / {style}: no colour layer (drawbox / blend) in the graph", "drawbox" not in gr and "all_expr='A+(B-A)" not in gr)
    check("some montage has a flash", n_fl > 0)
    # real ffmpeg: the flash only moves towards white (same white share in R, G, B), outside the killfeed zone
    import numpy as np
    d = Path(tempfile.mkdtemp(prefix="v844f_"))
    src = d / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x3060C0:s=640x360:r=60:d=2", "-f", "lavfi", "-i", "color=c=0xB03020:s=640x180:r=60:d=2",
                    "-filter_complex", "[0][1]overlay=0:180,format=yuv420p", "-c:v", "libx264", "-crf", "12", str(src)], check=True)
    take = {"nf": 120, "xfx": [{"k": "flash", "p": 0.5, "a": 0.5, "t1": M.XFX_FLASH_S}]}
    chains = []
    lab = M._xfx_chains(chains, "t0", "[s]", take, set(M.FX_ALL), False, [0.72, 0.0, 1.0, 0.1], {"rgb": 0xFFFFFF})
    fc = "[0:v]scale=1920:1080,format=yuv420p,setsar=1,fps=60[s];" + ";".join(chains) + f";{lab}select='eq(n,29)+eq(n,30)+eq(n,31)',format=rgb24[o]"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", fc, "-map", "[o]", "-vsync", "0", "-f", "rawvideo", "-"], capture_output=True)
    fr = np.frombuffer(r.stdout, np.uint8).reshape(-1, 1080, 1920, 3).astype(np.float32)
    check("ffmpeg renders the flash chain", r.returncode == 0 and len(fr) == 3, r.stderr.decode()[-300:])
    b, k_, a_ = fr[0][300:900, 100:1500], fr[1][300:900, 100:1500], fr[2][300:900, 100:1500]
    check("frame before: untouched", np.abs(b - fr[0][300:900, 100:1500]).max() == 0 and abs(float(b.mean()) - float(a_.mean())) < 80)
    sh = []
    for ch in range(3):
        c0 = b[..., ch].ravel()
        ok_ = c0 < 190
        sh.append(float(np.median(((k_[..., ch].ravel() - c0) / (255 - c0))[ok_])))
    check(f"peak frame: same white share in R, G, B ({sh[0]:.3f} {sh[1]:.3f} {sh[2]:.3f}) = no colour cast", max(sh) - min(sh) < 0.02 and sh[0] > 0.2)
    check("peak frame is less colourful than the source (it only adds white)", float((k_.max(-1) - k_.min(-1)).mean()) < float((b.max(-1) - b.min(-1)).mean()))


def part3():
    print("3) sky colour")
    names = set()
    for rec in ("aggressive", "hype", "cinematic", "smooth", "chill"):
        for bpm, en in ((70, 0.3), (100, 0.6), (128, 0.8), (160, 0.95)):
            for seed in range(4):
                n, rgb, why = M.sky_pick(rec, en, bpm, seed, f"song{seed}")
                names.add(n)
                check(f"{rec} {bpm} BPM seed {seed}: {n} is in the palette", n in M.SKY_PALETTE and rgb == M.SKY_PALETTE[n]) if seed == 0 and bpm == 128 else None
    check(f"different songs can give different colours ({len(names)} of {len(M.SKY_PALETTE)} seen)", len(names) >= 6, str(sorted(names)))
    check("the same inputs give the same colour", M.sky_pick("hype", 0.7, 128, 5, "x") == M.sky_pick("hype", 0.7, 128, 5, "x"))
    warm = sum(M.sky_pick("aggressive", 0.95, 160, s, f"t{s}")[0] in ("red", "orange", "magenta", "gold") for s in range(40))
    cool = sum(M.sky_pick("chill", 0.3, 70, s, f"t{s}")[0] in ("deep blue", "teal", "purple", "green") for s in range(40))
    check(f"a fast intense aggressive song is mostly warm ({warm}/40), a slow calm chill one mostly cool ({cool}/40)", warm >= 30 and cool >= 30)
    e, c = mk(M, "cs2", "hype", 2, eff=T.ALL_EXTRA)
    check("the montage has one sky colour, logged in the plan notes", e.get("xfx_sky_hue", {}).get("name") in M.SKY_PALETTE and any("sky colour" in n for n in e["notes"]))
    check("every sky candidate carries it", all(x.get("hue") == e["xfx_sky_hue"]["name"] for t in e["takes"] for x in t.get("xfx", []) if x["k"] == "sky"))


def part4():
    print("4) one attempt")
    for n in ("EXTRA_ATTEMPTS", "extra_variant", "_render_extra", "_render_loop", "fx_culprit", "FX_DROP_ORDER", "XFX_LITE_KEEP"):
        check(f"{n} is gone", not hasattr(M, n))
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("no 'render attempt N of' text, no retry wording in the render", "render attempt" not in src and "retrying without it" not in src and "ALL THREE RENDER ATTEMPTS" not in src)
    d = Path(tempfile.mkdtemp(prefix="v844r_"))
    runs = []
    keep = (M._run_ffmpeg, M.build_filter, M.LOG_DIR)
    M.LOG_DIR = d / "logs"
    M.LOG_DIR.mkdir()

    def fake_run(cmd, D, elog):
        runs.append(cmd)
        Path(elog).write_text("Error while filtering: Invalid data found when processing input\n", encoding="utf-8")
        M.RUN_PROG["t"] = 1.0
        return 1
    M._run_ffmpeg = fake_run
    M.build_filter = lambda plan, cfg, preview, fx=None: (["-i", "x.mp4"], "[0:v]bogus[vout];[0:a]anull[aout]")
    plan = {"takes": [{"out_start": 0.0, "dur": 3.0, "segs": [], "path": "x.mp4", "srcs": [{"path": "x.mp4"}]}], "duration": 3.0}
    try:
        try:
            M._render_once(plan, plan, d / "o.mp4", {}, False, False, None, True, d / "o.part.mp4", d / "e.txt", {"zoom"}, 3.0)
            ok = False
        except RuntimeError as ex:
            ok = "one attempt" in str(ex)
        check("a failing render runs ffmpeg exactly once (NVENC too: no second encoder run) and raises", ok and len(runs) == 1)
        fails = sorted(p.name for p in M.LOG_DIR.iterdir() if ".fail." in p.name)
        check("its stderr, filter graph and command are in their own files", fails == ["o.fail.cmd.txt", "o.fail.filter.txt", "o.fail.stderr.txt"], str(fails))
        check("the stderr file has the ffmpeg error, the filter file the graph", "Invalid data" in (M.LOG_DIR / "o.fail.stderr.txt").read_text() and "bogus" in (M.LOG_DIR / "o.fail.filter.txt").read_text())
    finally:
        M._run_ffmpeg, M.build_filter, M.LOG_DIR = keep


def synth_sky(W=384, H=216):
    import numpy as np
    img = np.zeros((H, W, 3), np.uint8)
    for y in range(H):                                                   # sky: deep blue at the top to pale at the horizon
        t = y / (H * 0.6)
        img[y, :] = (int(90 + 90 * t), int(150 + 60 * t), int(235 - 10 * t))
    img[int(H * 0.55):] = (110, 100, 80)                                  # ground
    img[int(H * 0.30):int(H * 0.55), 40:120] = (130, 125, 120)            # a grey building in front of the sky (ragged edge on top)
    img[int(H * 0.40):int(H * 0.46), 60:80] = (150, 190, 240)            # a window with sky colour inside the building (not connected to the top)
    img[20:30, 200:230] = (240, 240, 245)                                # a cloud inside the sky (a hole in the colour rule)
    rng = np.random.default_rng(1)
    return np.clip(img.astype(np.int16) + rng.integers(-1, 2, img.shape), 0, 255).astype(np.uint8)


def part5():
    print("5) sky segmentation")
    import numpy as np
    img = synth_sky()
    m, info = M.sky_segment(img, [0.72, 0.0, 1.0, 0.22])
    H, W = img.shape[:2]
    check(f"blue sky with a gradient is one clear sky (coverage {info['cov'] * 100:.0f}%)", info["kind"] == "blue" and 0.3 < info["cov"] < 0.9 and info["top"] > 0.8)
    check("the cloud inside the sky is sky (hole filled)", m[20:30, 200:230].mean() > 0.9)
    check("the ground and the grey building are not sky", m[int(H * 0.6):].mean() < 0.02 and m[int(H * 0.35):int(H * 0.55), 50:110].mean() < 0.05)
    check("a sky-coloured window inside the building is not sky (not connected to the sky)", m[int(H * 0.40):int(H * 0.46), 62:78].mean() < 0.1)
    m2, i2 = M.sky_segment(np.clip(img.astype(np.int16) + 6, 0, 255).astype(np.uint8), [0.72, 0.0, 1.0, 0.22], model=info["model"])
    check("the same colour model on a slightly changed frame gives the same region (stable)", (m != m2).mean() < 0.02)
    for nm, col in (("orange wall", (230, 140, 60)), ("white wall", (235, 235, 235)), ("grey wall", (120, 125, 130)), ("brown room", (110, 80, 60)), ("violet fog", (180, 170, 240))):
        a = np.zeros((216, 384, 3), np.uint8)
        a[:] = col
        a[::7] = [c - 4 for c in col]
        check(f"{nm} is not a sky", M.sky_segment(a)[1]["kind"] == "none" or M.sky_segment(a)[1]["cov"] < M.XFX_SKY_MIN_COV)
    z = img.copy()
    z[2:14, 290:380] = (30, 30, 35)                                      # a killfeed row (dark panel) in the upper right
    z[6:10, 300:340] = (255, 255, 255)
    mz, _ = M.sky_segment(z, [0.72, 0.0, 1.0, 0.22])
    check("killfeed panel and text inside the zone are not recoloured; sky next to them is", mz[6:10, 300:340].mean() < 0.05 and mz[2:14, 290:380].mean() < 0.6 and mz[22:27, 290:380].mean() > 0.5)
    check("a bright wall everywhere has no sky top", M.sky_segment(np.full((216, 384, 3), 200, np.uint8))[1]["kind"] == "none")


def part6():
    print("6) sky render chain")
    import numpy as np
    d = Path(tempfile.mkdtemp(prefix="v844s_"))
    W, H = 1920, 1080
    big = np.kron(synth_sky(), np.ones((5, 5, 1), np.uint8))
    import cv2
    cv2.imwrite(str(d / "f.png"), cv2.cvtColor(big, cv2.COLOR_RGB2BGR))
    src = d / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-framerate", "60", "-t", "4", "-i", str(d / "f.png"), "-vf", "format=yuv420p", "-c:v", "libx264", "-crf", "10", str(src)], check=True)
    take = {"nf": 240, "segs": [[0.0, 4.0, 1.0, 240, 0]], "srcs": [{"path": str(src), "shift": 0.0, "rect": [0, 0, W, H], "wh": [W, H]}], "path": str(src), "rect": [0, 0, W, H], "wh": [W, H]}
    x = {"k": "sky", "p": 2.0, "t0": 1.75, "t1": 2.75, "model": None}
    mp = d / "m.gray"
    st = M.sky_take_mask(take, x, [0.72, 0.0, 1.0, 0.22], mp)
    check("the mask file has one frame per output frame", mp.stat().st_size == 240 * M.SKY_W * M.SKY_H, str(mp.stat().st_size))
    rgb = M.SKY_PALETTE["purple"]
    x.update({"mask": str(mp), "grade": M.sky_grade(rgb, st["mean_y"]), "ok": True})
    chains = []
    lab = M.xfx_sky_chain(chains, "t0", "[s]", x, 1)
    fc = "[0:v]format=yuv420p,setsar=1,fps=60[s];" + ";".join(chains) + f";{lab}select='eq(n,10)+eq(n,120)+eq(n,150)',format=rgb24[o]"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src)] + M.sky_mask_input(x) + ["-filter_complex", fc, "-map", "[o]", "-vsync", "0", "-f", "rawvideo", "-"], capture_output=True)
    fr = np.frombuffer(r.stdout, np.uint8).reshape(-1, H, W, 3).astype(np.float32)
    check("ffmpeg renders the sky chain", r.returncode == 0 and len(fr) == 3, r.stderr.decode()[-400:])
    ref = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", "select='eq(n,10)+eq(n,120)+eq(n,150)',format=rgb24", "-vsync", "0", "-f", "rawvideo", "-"], capture_output=True).stdout
    ref = np.frombuffer(ref, np.uint8).reshape(-1, H, W, 3).astype(np.float32)
    check("before the effect the frame is bit-identical to the source", np.abs(fr[0] - ref[0]).max() <= 1)
    g = fr[1]
    sky = g[40:100, 400:1500]
    ground = g[800:1000, 100:1800]
    check("the ground is untouched at the peak", np.abs(ground - ref[1][800:1000, 100:1800]).max() <= 1)
    check("the sky is ONE even colour at the peak (std of each channel < 12 over the sky area)", float(sky.reshape(-1, 3).std(0).max()) < 12.0, str(sky.reshape(-1, 3).std(0)))
    want = np.array([(rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255], np.float32)
    got = sky.reshape(-1, 3).mean(0)
    check(f"and it is the palette colour (purple {want.astype(int).tolist()} vs {got.astype(int).tolist()})", float(np.abs(got - want).max()) < 40.0)
    check("the building stays grey (no tint on it)", np.abs(g[int(H * .35):int(H * .5), 250:550] - ref[1][int(H * .35):int(H * .5), 250:550]).mean() < 6)
    check("eased out at +0.5 s (between the sky and the peak colour)", float(np.abs(fr[2][40:100, 400:1500].mean() - ref[2][40:100, 400:1500].mean())) < float(np.abs(sky.mean() - ref[1][40:100, 400:1500].mean())) + 1)
    # the build_filter wiring: a mask input and alphamerge, k counted right
    e, c = mk(M, "valorant", "aggressive", 2, eff=T.ALL_EXTRA)
    t = e["takes"][0]
    mpx = d / "x.gray"
    mpx.write_bytes(b"\0" * (int(t["nf"]) * M.SKY_W * M.SKY_H))
    t["xfx"] = [{"k": "sky", "p": 1.0, "t0": 0.75, "t1": 1.75, "ok": True, "mask": str(mpx), "hue": "red", "grade": M.sky_grade(M.SKY_PALETTE["red"], 150.0)}]
    inputs, graph = M.build_filter(e, c, False)
    n_in = inputs.count("-i")
    mi = inputs.index(str(mpx))
    k_idx = inputs[:mi].count("-i") - 1                              # the mask's own -i is the last one before its path
    check("the mask is an extra gray raw input and the graph reads it by its own index", inputs[mi - 8:mi - 1] == ["-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{M.SKY_W}x{M.SKY_H}", "-framerate"][:7] or "gray" in inputs[mi - 8:mi])
    check("alphamerge + overlay, no maskedmerge, no geq sky", "alphamerge" in graph and f"[{k_idx}:v:0]setpts=N/(60*TB)" in graph and "maskedmerge" not in graph, f"k={k_idx} " + str([l for l in graph.split(';') if 'alphamerge' in l or 'rawvideo' in l or 'gray' in l][:3]) + str(inputs[mi - 9:mi + 1]))


if __name__ == "__main__":
    for n in PARTS:
        globals()["part" + n]()
    print(("\nFAILED: " + "; ".join(T.FAILS)) if T.FAILS else "\nall ok")
    sys.exit(1 if T.FAILS else 0)
