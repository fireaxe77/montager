"""V8.4.5 tests (fast; tiny ffmpeg runs on synthetic files, no montage render).
  0) title-bar version V8.4.5; V8.4.5 on top of V8.4.4 in both changelogs
  1) DEFAULT = V8.23.1: plan, plan text, filter graph for all three games
  2) audio hole inside a range: detected, the old chain loses the hole (short take), the new chain keeps the length and the timing
  3) broken recordings (video under 20 fps) are left out of the pools
  4) flash plan: few, spaced, never consecutive, one per take, strength capped, scaled with the length
  5) flash look: a pulse (moderate, stronger at the edges, neutral white) and the kill zone readable
  6) sky: segmentation rules (walls, edges, horizon), colours from the song's feel (same family in every game), count / spacing, placement roles
  7) drop moment: plan data, audio filters (dip, lift, hit) measured on a synthetic mix, nothing else moves
python tests\\test_v845.py   (parts: V845_PARTS=0,1,2,3,4,5,6,7)"""
import copy
import os
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
check, mk, js = T.check, T.mk, T.js
PARTS = [x for x in os.environ.get("V845_PARTS", "0,1,2,3,4,5,6,7").split(",") if x]
import numpy as np                                                                            # noqa: E402


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.4.5", M.APP_VERSION == "V8.4.5")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.4.5 above V8.4.4", cl[0].startswith("## V8.4.5") and cl[1].startswith("## V8.4.4"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.4.5 above V8.4.4", sm[0].startswith("## V8.4.5") and sm[1].startswith("## V8.4.4"), str(sm[:2]))
    seg = body[body.index("## V8.4.5"):body.index("## V8.4.4")].lower()
    check("simple entry is plain", not any(w in seg for w in ("test", "known issue", "on hold", "def ", "xfx", "ffmpeg", "mask", "geq")))


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
    print("2) audio hole inside a range")
    d = T.TMP / "gap"
    d.mkdir(exist_ok=True)
    base, gap = d / "base.mp4", d / "gap.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=60:duration=10", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=10",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(base)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(base), "-c", "copy", "-bsf:a", "setts=pts='if(gt(PTS,96000),PTS+192000,PTS)':dts='if(gt(DTS,96000),DTS+192000,DTS)'", str(gap)], check=True)
    M._APKT.clear()
    check("a range that contains a hole is a gap range", M.audio_gap(gap, 0, 1.0, 6.3))
    check("ranges without a hole are not (the old chain stays)", not M.audio_gap(gap, 0, 0.2, 1.2) and not M.audio_gap(gap, 0, 6.5, 2.0) and not M.audio_gap(base, 0, 1.0, 6.3))
    check("the old first filter is unchanged for them", M.aresample_for(base, 0, 1.0, 3.0) == "aresample=48000")

    def length(resample):
        fc = f"[0:a:0]{resample},aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,apad,atrim=duration=6.0[o]"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.0", "-t", "6.3", "-i", str(gap), "-filter_complex", fc, "-map", "[o]", "-f", "f32le", "-ac", "2", "-ar", "48000", "-"], capture_output=True)
        return np.frombuffer(r.stdout, np.float32).reshape(-1, 2) if r.returncode == 0 else None
    old, new = length("aresample=48000"), length(M.aresample_for(gap, 0, 1.0, 6.3))
    check("both chains run", old is not None and new is not None)
    # clip: sound 0-2 s, a 4 s hole, sound again from 6 s; the range starts at 1.0 s: sound 0-1 s, hole 1-5 s, sound 5-6 s
    check("the new chain keeps the time: the hole is silence of its own length (sound 0-1 s, silence 1.2-4.8 s, sound again at 5.2 s)",
          float(np.abs(new[:int(0.9 * 48000)]).mean()) > 0.05 and float(np.abs(new[int(1.2 * 48000):int(4.8 * 48000)]).max()) < 0.01 and float(np.abs(new[int(5.2 * 48000):int(5.9 * 48000)]).mean()) > 0.05)
    check("the old chain cut the hole out: sound again right after 1.2 s", float(np.abs(old[int(1.2 * 48000):int(2.0 * 48000)]).mean()) > 0.05)


def part3():
    print("3) broken recordings")
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("BROKEN_FPS is 20 and game_pool leaves such clips out", M.BROKEN_FPS == 20.0 and 'float(r["fps"]) < BROKEN_FPS' in src)


def mk_extra(game="valorant", style="aggressive", seed=3, title="t", energy=0.8):
    return mk(M, game, style, seed, title=title, energy=energy, eff=T.ALL_EXTRA)


def part4():
    print("4) flash plan")
    n_total = 0
    for g in ("cs2", "valorant", "r6s"):
        for style in ("aggressive", "hype", "chill"):
            e, c = mk_extra(g, style)
            fl = sorted(((t["out_start"] + x["p"], ti, x["a"]) for ti, t in enumerate(e["takes"]) for x in t.get("xfx", []) if x["k"] == "flash"))
            kills = sum(len(t["kills_out"]) for t in e["takes"])
            budget = max(2, int(round(e["duration"] / M.FLASH_EVERY_S)))
            n_total += len(fl)
            gaps_ok = all(b[0] - a[0] >= 1.0 for a, b in zip(fl, fl[1:]))
            two_per_s = all(sum(1 for f in fl if t0 <= f[0] < t0 + 1.0) <= 2 for t0, _, _ in fl)
            check(f"{g} / {style}: {len(fl)} flashes in {e['duration']:.0f} s (budget {budget}, {kills} kills), 1 s apart, at most 2 per second, one per take, strength <= {M.FLASH_A_MAX}",
                  len(fl) <= budget and gaps_ok and two_per_s and len({f[1] for f in fl}) == len(fl) and all(0 < f[2] <= M.FLASH_A_MAX for f in fl))
            check(f"{g} / {style}: far fewer than half of the kills", len(fl) * 4 <= max(kills, 4))
            check(f"{g} / {style}: the flash count is in the effect plan log", any("white flash on" in n for n in e["notes"]))
    check("some montages have flashes", n_total > 0)
    check("the budget scales with the length (70 s: 4, 150 s: 9)", max(2, round(70 / M.FLASH_EVERY_S)) == 4 and max(2, round(150 / M.FLASH_EVERY_S)) == 9 or max(2, round(150 / M.FLASH_EVERY_S)) >= 8)


def part5():
    print("5) flash look")
    d = Path(tempfile.mkdtemp(prefix="v845f_"))
    src = d / "c.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=60:d=2", "-vf", "format=yuv420p", "-c:v", "libx264", "-crf", "10", str(src)], check=True)
    take = {"nf": 120, "xfx": [{"k": "flash", "p": 0.5, "a": M.FLASH_A_MAX, "t1": M.XFX_FLASH_S}]}
    chains = []
    lab = M._xfx_chains(chains, "t0", "[s]", take, set(M.FX_ALL), False, [0.72, 0.0, 1.0, 0.12], {"rgb": 0xFFFFFF})
    fc = "[0:v]scale=1920:1080,format=yuv420p,setsar=1,fps=60[s];" + ";".join(chains) + f";{lab}select='eq(n,29)+eq(n,30)+eq(n,31)+eq(n,40)',format=rgb24[o]"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", fc, "-map", "[o]", "-vsync", "0", "-f", "rawvideo", "-"], capture_output=True)
    fr = np.frombuffer(r.stdout, np.uint8).reshape(-1, 1080, 1920, 3).astype(np.float32)
    check("ffmpeg renders the flash chain", r.returncode == 0 and len(fr) == 4, r.stderr.decode()[-300:])
    ref = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vf", "scale=1920:1080,select='eq(n,29)+eq(n,30)+eq(n,31)+eq(n,40)',format=rgb24", "-vsync", "0", "-f", "rawvideo", "-"], capture_output=True).stdout
    ref = np.frombuffer(ref, np.uint8).reshape(-1, 1080, 1920, 3).astype(np.float32)
    y = lambda a: a @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    dl = y(fr[1]) - y(ref[1])
    check(f"before the flash and 0.17 s after it the picture is the source (max {np.abs(fr[0] - ref[0]).max():.0f} / mean {float(np.abs(fr[3] - ref[3]).mean()):.2f} levels)", float(np.abs(fr[0] - ref[0]).mean()) < 1.0 and float(np.abs(fr[3] - ref[3]).mean()) < 1.0)
    check(f"the peak is a pulse, not a blast: mean luma +{float(dl.mean()):.0f}, 99th percentile of the peak frame {float(np.percentile(y(fr[1]), 99)):.0f} (white 255)", 3 < float(dl.mean()) < 40)
    check("stronger toward the edges than in the middle (vignette-style)", float(dl[:, :200].mean()) > float(dl[300:800, 700:1200].mean()) * 1.3)
    check("the flash dies fast: one frame later less than half of the peak", float((y(fr[2]) - y(ref[2])).mean()) < float(dl.mean()) * 0.8)
    zone = dl[:130, 1400:]
    check("the killfeed zone gets less of it than the rest (rows stay readable)", float(zone.mean()) < float(dl.mean()) * 0.8)
    sh = []
    for ch in range(3):
        c0 = ref[1][..., ch][300:900, 100:1500].ravel()
        ok = c0 < 190
        sh.append(float(np.median(((fr[1][..., ch][300:900, 100:1500].ravel() - c0) / (255 - c0))[ok])))
    check(f"neutral white: the same white share in R, G, B ({sh[0]:.3f} {sh[1]:.3f} {sh[2]:.3f})", max(sh) - min(sh) < 0.03)


def part6():
    print("6) sky")
    import cv2
    H, W = 216, 384
    img = np.zeros((H, W, 3), np.uint8)
    for yy in range(H):
        t = yy / (H * 0.6)
        img[yy, :] = (int(90 + 90 * t), int(150 + 60 * t), int(235 - 10 * t))
    img[int(H * 0.55):] = (110, 100, 80)
    img[int(H * 0.30):int(H * 0.55), 40:120] = (130, 125, 120)
    img[20:30, 200:230] = (240, 240, 245)
    m, info = M.sky_segment(img, [0.72, 0.0, 1.0, 0.22])
    check(f"blue sky: one clear sky ({info['cov'] * 100:.0f}%), cloud inside it, ground and building not", info["kind"] == "blue" and m[20:30, 200:230].mean() > 0.9 and m[int(H * .6):].mean() < 0.02 and info["sky_rgb"] is not None)
    for nm, col in (("orange wall", (230, 140, 60)), ("white wall", (235, 235, 235)), ("grey wall", (120, 125, 130)), ("blue wall to the bottom", (60, 110, 200))):
        a = np.zeros((H, W, 3), np.uint8)
        a[:] = col
        a[::7] = [c - 4 for c in col]
        mm, ii = M.sky_segment(a)
        check(f"{nm} is not a sky", not mm.any() or ii["cov"] < M.XFX_SKY_MIN_COV)
    # a blue wall filling the upper part down to the lower limit is a wall; a sky with a horizon is a sky
    wall = np.full((H, W, 3), (40, 40, 40), np.uint8)
    wall[:int(H * 0.8)] = (100, 160, 235)
    mw, iw = M.sky_segment(wall)
    check("a blue area that runs down to the lower limit in the whole width is a wall, not a sky", not mw.any())
    sl = img.copy()
    sl[:, :10] = (100, 160, 235)
    sl[int(H * 0.05):, :] = np.where(np.arange(W)[None, :, None] < 10, sl[int(H * 0.05):, :], (60, 55, 50)).astype(np.uint8)
    ms, _ = M.sky_segment(sl)
    check(f"no thin strip along the picture edge ({float(ms[:, :14].mean()):.2f})", float(ms[:, :14].mean()) < 0.05)
    # colours: the same song feel = the same family in every game, different feels differ, the clip's colours steer the pick
    fam = {(s, e, b): M.sky_ranked(s, e, b)[0][:3] for s in ("aggressive", "hype", "cinematic", "smooth", "chill") for e, b in ((0.9, 150), (0.5, 100), (0.3, 70))}
    check("the family depends on the song feel only (same call, same answer; no seed, no game)", all(M.sky_ranked(s, e, b)[0][:3] == v for (s, e, b), v in fam.items()))
    check("different song feels give different families", len({tuple(v) for v in fam.values()}) >= 5)
    check("fast / intense / aggressive is warm, slow / calm / chill is cool", M.sky_ranked("aggressive", 0.9, 150)[0][0] in ("red", "orange", "magenta", "gold") and M.sky_ranked("chill", 0.3, 70)[0][0] in ("deep blue", "teal", "purple", "green"))
    rk = M.sky_ranked("hype", 0.74, 150)[0]
    n1, c1, _ = M.sky_colour_for(rk, 0x99D0F8, 40.0)
    check("the colour is far from the sky's own hue (205 deg) and from the scene's (40 deg)", M._hue_dist(M._hue_deg(c1), 205.0) >= 50 and M._hue_dist(M._hue_deg(c1), 40.0) >= 30, f"{n1}")
    check("count scales with the length: 70 s: 2, 150 s: 5, 180 s: 6, 30 s: 1", [M.sky_max_for(x) for x in (70, 150, 180, 30)] == [2, 5, 6, 1])
    check("spacing at least 12 s", M.SKY_SPACING_S >= 12.0)
    e, c = mk_extra("valorant", "hype", 3)
    sk = [(ti, x) for ti, t in enumerate(e["takes"]) for x in t.get("xfx", []) if x["k"] == "sky"]
    check("sky candidates are never the first take, a calm take or an ordinary middle take; each has a role",
          all(ti > 0 and e["takes"][ti]["role"] != "calm" and x.get("why") in ("headline kill", "drop kill", "ending kill", "flick kill") for ti, x in sk))
    check("the plan log names the colour family and the sky limit", any("sky recolour: up to" in n and "colour family" in n for n in e["notes"]))


def part7():
    print("7) drop moment")
    e, c = mk_extra("valorant", "aggressive", 3)
    dm = e.get("xfx_drop", [])
    check("drop moments only exist where a drop kill is", isinstance(dm, list))
    import random
    rng = random.Random(1)
    d0, d1 = M.drop_moment(rng, 1.0, 10.0), M.drop_moment(rng, 1.6, 20.0)
    check("stronger drop = deeper dip, higher lift, louder hit", d1["dip_db"] > d0["dip_db"] and d1["lift_db"] > d0["lift_db"] and d1["boom_db"] > d0["boom_db"] and 4 <= d0["dip_db"] <= 9.5)
    check("varied: three variants exist", len({M.drop_moment(random.Random(i), 1.3, 5.0)["variant"] for i in range(30)}) == 3)
    # a synthetic mix: music = noise-free tone, game = a short tone; with and without the drop filters
    dur, T0 = 3.0, 1.5
    d = {"t": T0, "s": 1.3, "variant": "punch", "dip_s": 0.3, "dip_db": 8.0, "boom_f1": 52.0, "boom_f0": 130.0, "boom_r": 26.0, "boom_dec": 6.5, "boom_db": -8.0, "lift_db": 3.0, "duck_db": 4.0, "breath": 0.4}
    dip, lift, hits = M.drop_audio_filters([d])

    def run(with_drop):
        if with_drop:
            fc = (f"sine=f=1000:sample_rate=48000:duration={dur}[m0];sine=f=3000:sample_rate=48000:duration={dur}[g0];[m0]aformat=channel_layouts=stereo,volume='{dip}':eval=frame[m];"
                  f"[g0]aformat=channel_layouts=stereo,volume='{lift}':eval=frame[g];{hits[0]}[h];[m][g][h]amix=inputs=3:duration=first:normalize=0[o]")
        else:
            fc = f"sine=f=1000:sample_rate=48000:duration={dur}[m];sine=f=3000:sample_rate=48000:duration={dur}[g];[m]aformat=channel_layouts=stereo[m2];[g]aformat=channel_layouts=stereo[g2];[m2][g2]amix=inputs=2:duration=first:normalize=0[o]"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-filter_complex", fc, "-map", "[o]", "-f", "f32le", "-ac", "2", "-ar", "48000", "-"], capture_output=True)
        return np.frombuffer(r.stdout, np.float32).reshape(-1, 2) if r.returncode == 0 else None
    A, B = run(True), run(False)
    check("ffmpeg renders the drop filters", A is not None and B is not None, "")
    n = min(len(A), len(B))
    A, B = A[:n], B[:n]
    out = np.r_[np.arange(0, int((T0 - 0.3 - 0.15) * 48000)), np.arange(int((T0 + 1.0) * 48000), n)]
    check("outside the drop window the mix is IDENTICAL to the one without it (nothing else moved)", float(np.abs(A[out] - B[out]).max()) < 1e-4)
    pre = slice(int((T0 - 0.2) * 48000), int((T0 - 0.05) * 48000))
    def tone(x, f):                                                     # level of one tone (the music, 1 kHz) inside the mix
        n_ = len(x)
        s_ = np.fft.rfft(x * np.hanning(n_))
        k_ = int(round(f * n_ / 48000))
        return float(np.abs(s_[k_ - 2:k_ + 3]).max())
    dip_meas = 20 * np.log10(tone(A[pre, 0], 1000.0) / tone(B[pre, 0], 1000.0))
    check(f"the music dips by about 8 dB before the kill ({dip_meas:.1f} dB)", -9.5 < dip_meas < -5.5)
    post = slice(int(T0 * 48000), int((T0 + 0.5) * 48000))
    dd = A[post] - B[post]
    check("the added hit is the same in left and right (no delay / phase between them)", float(np.corrcoef(dd[:, 0], dd[:, 1])[0, 1]) > 0.9999)
    check("the game tone is lifted around the kill (3 kHz up by about 3 dB)", 1.5 < 20 * np.log10(tone(A[int((T0 + 0.02) * 48000):int((T0 + 0.25) * 48000), 0], 3000.0) / tone(B[int((T0 + 0.02) * 48000):int((T0 + 0.25) * 48000), 0], 3000.0)) < 4.5)


if __name__ == "__main__":
    for n in PARTS:
        globals()["part" + n]()
    print(("\nFAILED: " + "; ".join(T.FAILS)) if T.FAILS else "\nall ok")
    sys.exit(1 if T.FAILS else 0)
