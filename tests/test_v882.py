"""V8.8.2 tests (fast; no montage render, no library scan).
  0) title-bar version V8.8.2; V8.8.2 on top of V8.8.1 in both changelogs
  1) one universal sky: count, spacing and animation are the same for Valorant, CS2 and R6S; the per-game on / off switch is unchanged
  2) sky look: even mask (holes filled, outline kept), soft clouds (no small blobs), even tint (less of the sky's own brightness variation), hazy orange near the top for every style, more colours
     per montage, white / black only where the picture keeps its contrast, never a neutral as the jump colour; the sky filter chain runs in ffmpeg (a 1 s synthetic take)
  3) dead air: the audible part of Maniac (Conan Gray) ends before its silent last seconds; full mode plans inside the audible part for every game (synthetic song with 4 s of silence at the end)
  4) Manual Auto: a first pick that plans short gets more clips (at most AUTO_TOPUP_ROUNDS re-plans, nothing unticked); a full one is left alone
  5) clip audio: quiet clips lifted past the old +8 dB, loud ones lowered, the peak never above -1 dBFS, silent clips unchanged; the kill boost of clips at or under unity is exactly the old one
  6) render speed: the zoom punch runs only inside its windows (bit-identical frames, real ffmpeg on a synthetic clip); the sky mask made on several threads is byte-identical to one thread
python tests\\test_v882.py   (parts: V882_PARTS=0,1,2,3,4,5,6)"""
import hashlib
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
check = T.check
PARTS = [x for x in os.environ.get("V882_PARTS", "0,1,2,3,4,5,6").split(",") if x]
import numpy as np                                                                            # noqa: E402


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.8.2", M.APP_VERSION == "V8.8.2")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.8.2 above V8.8.1", cl[0].startswith("## V8.8.2") and cl[1].startswith("## V8.8.1"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.8.2 above V8.8.1", sm[0].startswith("## V8.8.2") and sm[1].startswith("## V8.8.1"), str(sm[:2]))
    seg = body[body.index("## V8.8.2"):body.index("## V8.8.1")].lower()
    check("simple entry is plain", not any(w in seg for w in ("test", "known issue", "on hold", "def ", "xfx", "ffmpeg", "cache", "()", "lufs", "thread")))


def part1():
    print("1) one universal sky")
    for d in (40, 70, 110, 180):
        v = {g: M.sky_max_for(d, g) for g in (None, "valorant", "cs2", "r6s")}
        check(f"sky count for {d} s the same in every game ({v['valorant']})", len(set(v.values())) == 1, str(v))
    check("sky spacing the same in every game", len({M.sky_spacing_for(g) for g in (None, "valorant", "cs2", "r6s")}) == 1)
    for args in ((0.9, 150, "aggressive"), (0.4, 85, "chill"), (0.7, 120, "hype")):
        a = [M.sky_anim_params(*args, False, game=g) for g in ("valorant", "cs2", "r6s")]
        check(f"sky animation the same in every game {args}", a[0] == a[1] == a[2] and a[0].get("sync"), str(a[0]))
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("assign_extra_fx: no Valorant-only sky branch", 'sky88 = game != "valorant"' not in src and "sky88 = True" in src)
    check("planner: the sky headline preference is not CS2 / R6S only", 'if game != "valorant" and head_cands and effects_mode' not in src)
    check("per-game sky switch unchanged", M.SKY_START == {"cs2": True, "valorant": True, "r6s": False} and M.sky_enabled({"sky_game": {"valorant": False}}, "valorant") is False)


def part2():
    print("2) sky look")
    m = np.zeros((90, 160), np.uint8)
    m[:40, 10:150] = 1
    m[10:16, 40:48] = 0                                    # a cloud speck inside the sky
    m[5:9, 100:104] = 0
    m[25:40, 70:75] = 0                                    # a gap open to the lower edge of the sky (stays a notch only where it reaches below the sky)
    e = M.sky_mask_even(m)
    check("even mask: enclosed holes filled", e[10:16, 40:48].all() and e[5:9, 100:104].all())
    check("even mask: nothing added below the sky / outside the sides", not e[45:].any() and not e[:, :8].any() and not e[:, 152:].any())
    big = np.zeros((90, 160), np.uint8)
    big[:60, :] = 1
    big[10:50, 20:140] = 0                                 # an enclosed hole bigger than 6 % of the picture: a big object, stays out
    check("even mask: a large enclosed object stays out", not M.sky_mask_even(big)[30, 80])
    hard = list(M.sky_cloud_field(160, 90, 3, 60, 100, 2.0, 7))
    soft = list(M.sky_cloud_field(160, 90, 3, 60, 100, 2.0, 7, soft=M.SKY_CLOUD_SOFT))
    gx = lambda a: float(np.abs(np.diff(a, axis=1)).mean() + np.abs(np.diff(a, axis=0)).mean())
    check(f"soft clouds: much smoother than the old blobs ({gx(soft[0]):.4f} vs {gx(hard[0]):.4f})", gx(soft[0]) < 0.35 * gx(hard[0]))
    check("soft clouds: shallower", M.SKY_CLOUD_SOFT["max"] < M.SKY_CLOUD_MAX)
    g0 = M.sky_grade_v2(M.SKY_PALETTE["ember"], "sunset", None, 0.7)
    g1 = M.sky_grade_v2(M.SKY_PALETTE["ember"], "sunset", None, 0.7, mean_y=180.0, name="ember")
    y = lambda g, v: 16 + (v - 16) * g["y_mul"] + g.get("y_add", 0.0)
    check("even tint: the sky's mean keeps its old brightness", abs(y(g1["steady"], 180) - y(g0["steady"], 180)) < 0.05)
    check("even tint: half the brightness variation (clouds no longer blotch)", abs((y(g1["steady"], 220) - y(g1["steady"], 140)) - 0.5 * (y(g0["steady"], 220) - y(g0["steady"], 140))) < 0.05)
    ho = M.sky_grade_v2(M.SKY_PALETTE["hazy orange"], "sunset", None, 0.7, mean_y=180.0, name="hazy orange")["steady"]
    check(f"hazy orange is light (Y {y(ho, 180):.0f} at a mean sky, the deep colours ~98)", y(ho, 180) > 140)
    for st, e_, b_ in (("aggressive", 0.9, 150), ("hype", 0.8, 128), ("cinematic", 0.6, 110), ("smooth", 0.5, 95), ("chill", 0.4, 85), ("mix", 0.6, 120)):
        r = M.sky_ranked(st, e_, b_)[0]
        check(f"hazy orange in the top 3 for {st}: {r[:4]}", "hazy orange" in r[:3])
    rk = M.sky_ranked("hype", 0.8, 128)[0]
    info = {"scene_y": 100.0, "sample": {"lab": np.array([190.0, 120.0, 100.0])}}
    names = [M.sky_colour_for(rk, 0x6AA0E0, info=info, k=k_)[0] for k_ in range(3)]
    check(f"three skies of one montage get three colours ({names})", len(set(names)) == 3)
    check("never the same colour twice in a row", M.sky_colour_for(rk, 0x6AA0E0, info=info, k=0, prev=names[0])[0] != names[0])
    check("white over a dark scene: allowed", M.sky_neutral_ok("white", {"scene_y": 90.0, "sample": {"lab": [200.0, 128, 110]}})[0])
    check("white over a bright scene: refused (washed out)", not M.sky_neutral_ok("white", {"scene_y": 170.0, "sample": {"lab": [200.0, 128, 110]}})[0])
    check("black over a dark scene: refused (muddy)", not M.sky_neutral_ok("black", {"scene_y": 40.0})[0])
    check("black over a normal scene: allowed", M.sky_neutral_ok("black", {"scene_y": 110.0})[0])
    wr = ["white", "hazy orange", "teal"]
    check("white skipped when it would wash out", M.sky_colour_for(wr, 0x6AA0E0, info={"scene_y": 180.0, "sample": {"lab": [200.0, 128, 110]}})[0] != "white")
    check("a neutral is never the jump colour", M.sky_alt_colour(["white", "black", "teal"], M.SKY_PALETTE["white"])[0] == "teal"
          and M.sky_alt_colour(["black", "violet"], M.SKY_PALETTE["ember"])[0] == "violet")
    wg = M.sky_grade_v2(M.SKY_PALETTE["white"], "sunset", None, 0.5, mean_y=170.0, name="white")["steady"]
    check(f"white sky is bright and colourless (Y {y(wg, 170):.0f})", y(wg, 170) > 190 and wg["u"] == 128.0 and wg["v"] == 128.0)
    # the chain in ffmpeg: 1 s synthetic take + a synthetic mask file (all three planes), the new grade with y_add
    tmp = Path(tempfile.mkdtemp())
    mk = tmp / "m.yuv"
    fr = np.zeros((3, M.SKY_H, M.SKY_W), np.uint8)
    fr[0, :M.SKY_H // 3] = 230
    fr[1] = 60
    with open(mk, "wb") as fh:
        for _ in range(60):
            fh.write(fr.tobytes())
    x = {"mask": str(mk), "mask_fmt": "yuv444p", "p": 0.2, "push": 0.04, "grade": M.sky_grade_v2(M.SKY_PALETTE["hazy orange"], "sunset", M.SKY_PALETTE["teal"], 0.7, mean_y=175.0, name="hazy orange")}
    chains = []
    lab = M.xfx_sky_chain(chains, "t0", "[src]", x, 1)
    g = "[0:v]format=yuv420p[src];" + ";".join(chains) + f";{lab}null[o]"
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x78A8E0:s=1920x1080:r=60:d=1"] + M.sky_mask_input(x) +
                       ["-filter_complex", g, "-map", "[o]", "-frames:v", "60", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    ok = r.returncode == 0 and len(r.stdout) == 60 * 1920 * 1080 * 3
    check("sky chain renders (ffmpeg, 1 s)", ok, r.stderr.decode("utf-8", "ignore")[-300:])
    if ok:
        last = np.frombuffer(r.stdout[-1920 * 1080 * 3:], np.uint8).reshape(1080, 1920, 3)
        top, low = last[60:300, 200:1700].reshape(-1, 3).mean(0), last[700:1000, 200:1700].reshape(-1, 3).mean(0)
        check(f"masked sky turned orange (R {top[0]:.0f} > B {top[2]:.0f}), the rest untouched ({low.round().tolist()})", top[0] > top[2] + 30 and abs(low[2] - 224) < 3)


def part3():
    print("3) dead air at the start / end of the song")
    mp = next((p_ for p_ in (Path(M.load_config().get("mp3_dir") or "."), Path("E:/CLAUDECODE/Songs")) if (p_ / "Maniac - Conan Gray.mp3").exists()), Path(".")) / "Maniac - Conan Gray.mp3"
    if mp.exists():
        an = M.get_songmap(str(mp))
        lv = M.song_live_range(an)
        check(f"Maniac: audible part ends {an['dur'] - lv[1]:.1f} s before the file ends ({lv[0]:.2f} - {lv[1]:.2f} of {an['dur']:.2f} s)", 2.5 <= an["dur"] - lv[1] <= 5.0)
    else:
        print("   (Maniac - Conan Gray.mp3 not on this machine: skipped)")
    bt = [0.25 + 0.5 * i for i in range(240)]              # a 124 s synthetic song: sound 1.0 .. 120 s, silence before / after
    dur = 124.0
    wave = [0.0] * 2000
    for i in range(2000):
        t_ = i * dur / 2000
        if 1.0 <= t_ <= 120.0:
            wave[i] = 0.5
    an = {"beats": bt, "dur": dur, "wave": wave, "down": list(range(0, 240, 4)), "phrase4": list(range(0, 240, 16)), "sections": [], "drops": [], "drop": 100, "energy": [0.5] * 240,
          "level": [1] * 120}
    lv = M.song_live_range(an)
    check(f"synthetic song: audible part {lv}", abs(lv[0] - 1.0) < 0.1 and abs(lv[1] - 120.0) < 0.1)
    clips = [{"path": f"c{i}.mp4", "times": [5.0], "rows": [5.0], "score": 1.0 - i * 0.01} for i in range(40)]
    for g in ("valorant", "cs2"):
        M.FULL_CTX.update(on=True, game=g)
        M.FULL_CTX.pop("live", None)
        try:
            fit = M.optimal_fit(clips, an, "hype")
        finally:
            M.FULL_CTX["on"] = False
            M.FULL_CTX.pop("live", None)
        s_, e_ = bt[fit["start_beat"]], bt[fit["end_beat"]]
        check(f"{g} full mode: section {s_:.2f} - {e_:.2f} s inside the audible part", s_ >= 1.0 - 0.05 and e_ <= 120.0)
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("the planner works out the audible end itself (first pass too)", 'FULL_CTX["live"] = FULL_CTX.get("live") or song_live_range(an)' in src)


def part4():
    print("4) Manual Auto fills the song")
    real = M.make_plan
    an = {"beats": [0.5 * i for i in range(280)], "dur": 140.0, "wave": [0.5] * 2000}
    rest = [{"path": f"r{i}.mp4", "ks": [3.0]} for i in range(30)]
    calls = []

    def fake(cfg, game, paths, *a, **k):
        calls.append(list(paths))
        return {"duration": min(140.0, 4.5 * len(paths))}, ""
    M.make_plan = fake
    try:
        first = [f"p{i}.mp4" for i in range(26)]         # 117 s: about 20 s short of the song
        paths, info = M.auto_fill_topup({}, "valorant", first, "x.mp3", an, "hype", 1, {"rest": list(rest), "bd": 0.5, "rname": "hype"})
        check(f"short first pick: clips added ({info['added']}), planned {info['length']:.0f} of {info['target']:.0f} s", info["added"] > 0 and info["target"] - info["length"] <= M.AUTO_TOL_S)
        check("nothing unticked", all(p_ in paths for p_ in first))
        check(f"at most {M.AUTO_TOPUP_ROUNDS + 1} plans", len(calls) <= M.AUTO_TOPUP_ROUNDS + 1, str(len(calls)))
        calls.clear()
        full = [f"p{i}.mp4" for i in range(31)]
        paths, info = M.auto_fill_topup({}, "valorant", full, "x.mp3", an, "hype", 1, {"rest": list(rest), "bd": 0.5, "rname": "hype"})
        check("a full pick is left alone (one plan, nothing added)", info["added"] == 0 and len(calls) == 1 and paths == full)
    finally:
        M.make_plan = real
    check("the first pick takes more clips than before (x1.3)", M.AUTO_PICK_X >= 1.3)
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("the Auto button runs the top-up", "allp, top = auto_fill_topup(" in src)
    check("song-end fill (longer run-ins) for every game", 'FULL_CTX.get("live") and game != "valorant"' not in src)


def part5():
    print("5) clip audio evened out")
    cfg = {"game_audio_level_valorant": 0.3}
    song = -7.6
    q, lq = M._game_gain(cfg, song, -30.0, "valorant", peak_db=-20.0)
    check(f"a quiet clip (-30 LUFS) is lifted past the old +8 dB (lift {lq:+.1f})", lq > 8.0)
    check(f"... to the common loudness ({-30.0 + q:.1f} vs {song - 12:.1f})", abs(-30.0 + q - (song - 12)) < 0.2)
    p, lp = M._game_gain(cfg, song, -34.0, "valorant", peak_db=-4.0)
    check(f"... but never so far that its peak passes -1 dBFS (peak -4 -> gain {p:+.1f})", -4.0 + p <= -1.0 + 1e-6)
    l_, ll = M._game_gain(cfg, song, -8.0, "valorant", peak_db=0.0)
    check(f"a loud clip (-8 LUFS) is lowered (lift {ll:+.1f})", ll < 0 and abs(-8.0 + l_ - (song - 12)) < 0.2)
    s_, ls = M._game_gain(cfg, song, None, "valorant")
    check("a silent clip is not changed", ls == 0.0)
    check("a clip below the silence line is not lifted", M._game_gain(cfg, song, -60.0, "valorant")[1] == 0.0)
    for gdb in (-20.0, -6.0, -2.5, -1.0, 0.0):            # the clip's gain before the music rule; with the rule the render gets it lowered by music_db
        g = 10 ** (gdb / 20)
        for mdb in (None, -30.0):
            f_ = 10 ** (mdb / 20) if mdb else 1.0
            src = {"music_db": mdb} if mdb else {}
            old = min(1.0, g * 1.585) if not mdb else min(1.0, (g * f_) / f_ * 1.585) * f_          # the V8.8.1 formulas, verbatim
            check(f"kill boost unchanged at {gdb:+.1f} dB (music {mdb})", abs(M._kill_boost(src, g * f_) - old) < 1e-12)
    b = M._kill_boost({"peak_db": -12.0}, 10 ** (8 / 20))
    check(f"a lifted clip keeps a kill boost within its peak ({20 * np.log10(b):+.1f} dB, peak -12 -> at most +11)", 10 ** (8 / 20) <= b <= 10 ** (11 / 20) + 1e-9)
    check("music-over-gameplay rule untouched", M.MUSIC_MUTE_DB == 60 if hasattr(M, "MUSIC_MUTE_DB") else True)


def part6():
    print("6) render speed, identical output")
    z = "(1-1/(1+between((in/60),0.5,0.95)*0.06*exp(-9*((in/60)-0.5))+between((in/60),1.4,1.85)*0.05*exp(-9*((in/60)-1.4))))/2"
    P = f"x0='W*{z}':y0='H*{z}':x1='W-W*{z}':y1='H*{z}':x2='W*{z}':y2='H-H*{z}':x3='W-W*{z}':y3='H-H*{z}':interpolation=cubic:eval=frame"
    EN = "between(t,0.5000,0.9500)+between(t,1.4000,1.8500)"
    res = []
    for pe in ("", f":enable='{EN}'"):
        g = f"[0:v]format=yuv420p,split=2[m][f];[f]perspective={P}{pe},format=yuv420p[e];[m]format=yuv420p[m2];[m2][e]overlay=0:0:eof_action=pass:enable='{EN}'[o]"
        r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=60:d=2.5", "-filter_complex", g, "-map", "[o]", "-f", "framemd5", "-"], capture_output=True, text=True)
        res.append(hashlib.md5(r.stdout.encode()).hexdigest() if r.returncode == 0 and r.stdout.count("\n") > 100 else None)
    check("zoom punch only inside its windows: frames bit-identical", res[0] is not None and res[0] == res[1], str(res))
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("build_filter: the perspective carries the overlay's enable", "interpolation=cubic:eval=frame:enable='{en_}'" in src)
    tmp = Path(tempfile.mkdtemp())
    clip = tmp / "sky.mp4"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x6EA6E6:s=1280x720:r=60:d=2", "-f", "lavfi", "-i", "color=c=0x7A6A50:s=1280x440:r=60:d=2",
                        "-filter_complex", "[0:v][1:v]overlay=x=0:y=280,drawbox=x='200+t*150':y=60:w=90:h=40:c=0x5070A0:t=fill,format=yuv420p", "-c:v", "libx264", "-crf", "12", str(clip)], capture_output=True)
    if r.returncode:
        check("synthetic sky clip", False, r.stderr.decode("utf-8", "ignore")[-300:])
        return
    take = {"nf": 90, "segs": [[0.2, 1.7, 1.0, 90, 0]], "srcs": [{"path": str(clip), "shift": 0.0, "rect": [0, 0, 1280, 720], "wh": [1280, 720]}], "path": str(clip), "rect": [0, 0, 1280, 720], "wh": [1280, 720]}
    an_ = M.sky_anim_params(0.8, 128, "hype", True)
    outs = []
    old = M.SKY_THREADS
    try:
        for th in (1, 8):
            M.SKY_THREADS = th
            x = {"k": "sky", "p": 0.3, "t0": 0.3, "t1": 1.5, "anim": an_, "push": an_["push"], "seed": 3, "grad_dark": 0.25, "beats": [(0.3, 1.0), (0.77, 0.45), (1.24, 0.45)]}
            mp = tmp / f"m{th}.yuv"
            st = M.sky_take_mask(take, x, None, mp, ramp=True)
            outs.append((hashlib.md5(mp.read_bytes()).hexdigest(), st["ok_frames"]))
    finally:
        M.SKY_THREADS = old
    check(f"sky mask on 8 threads byte-identical to 1 thread ({outs[0][1]} sky frames)", outs[0] == outs[1] and outs[0][1] > 30, str(outs))


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
    sys.exit(1 if T.FAILS else 0)
