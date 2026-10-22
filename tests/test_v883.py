"""V8.8.3 tests (fast; no montage render, no library scan).
  0) title-bar version V8.8.3; V8.8.3 on top of V8.8.2 in both changelogs
  1) sky: one colour family per montage (vibe / cover, chosen once), ten clean families (no muddy / brown ends, the jump colour inside the family), regular beat-locked bands (no blobs: every
     row the same across the sky, periodic, moving only on the beats + a slow drift), the gradient in its own plane, the chain runs in ffmpeg (1 s synthetic take, top darker than bottom, jumps on the beat)
  2) dead air: a synthetic song with silence at the start and the end; the planner stays inside its audible part for every game (Valorant, CS2, R6S) and every planning path (Auto Optimal,
     Manual Optimal, a fixed length, full mode = Force Full / Force New Full / Manual Auto); the same rule for the dry plan and the render (one make_plan)
  3) fill the song: which montages must cover the whole trimmed song (song_fill_target), at most SONG_FILL_ROUNDS re-plans, never a removed clip; the song-end run-in fill for every mode;
     the real-data run per game and mode is tests/fill883.py (montage end within 3 s of the trimmed song end)
python tests\\test_v883.py   (parts: V883_PARTS=0,1,2,3)"""
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
check = T.check
PARTS = [x for x in os.environ.get("V883_PARTS", "0,1,2,3").split(",") if x]
import numpy as np                                                                            # noqa: E402


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.8.3", M.APP_VERSION == "V8.8.3")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.8.3 above V8.8.2", cl[0].startswith("## V8.8.3") and cl[1].startswith("## V8.8.2"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.8.3 above V8.8.2", sm[0].startswith("## V8.8.3") and sm[1].startswith("## V8.8.2"), str(sm[:2]))
    seg = body[body.index("## V8.8.3"):body.index("## V8.8.2")].lower()
    check("simple entry is plain", not any(w in seg for w in ("test", "known issue", "on hold", "def ", "ffmpeg", "cache", "()", "lufs", "thread", "planner")))


def _hsv(rgb):
    import colorsys
    return colorsys.rgb_to_hsv(((rgb >> 16) & 255) / 255, ((rgb >> 8) & 255) / 255, (rgb & 255) / 255)


def part1():
    print("1) sky: one family, clean gradient, regular bands")
    fams = M.SKY_FAMILIES
    check("ten families", set(fams) == {"orange", "red", "rose", "amber", "blue", "teal", "violet", "green", "white", "black"}, str(sorted(fams)))
    for n_, (top, bot, jmp) in fams.items():
        if n_ in ("white", "black"):
            ch = lambda c: max((c >> 16) & 255, (c >> 8) & 255, c & 255) - min((c >> 16) & 255, (c >> 8) & 255, c & 255)
            check(f"{n_}: colourless ends", max(ch(top), ch(bot)) <= 12)
            continue
        h0, s0, v0 = _hsv(top)
        h1, s1, v1 = _hsv(bot)
        hj = _hsv(jmp)[0]
        dh = lambda a, b: min(abs(a - b), 1 - abs(a - b)) * 360
        check(f"{n_}: clean gradient (saturation {s0:.2f} / {s1:.2f}, brightness {v0:.2f} / {v1:.2f}, hue step {dh(h0, h1):.0f} deg)", min(s0, s1) >= 0.55 and min(v0, v1) >= 0.35 and dh(h0, h1) <= 25)
        check(f"{n_}: the beat jump stays in the family ({dh(h0, hj):.0f} deg)", dh(h0, hj) <= 30)
    g = M.sky_family_grade("orange", 180.0)
    y = lambda L, v: 16 + (v - 16) * L["y_mul"] + L["y_add"]
    check("grade: full chroma of the family (nothing mixed with the sky's blue: no grey / brown)", all(L_["haze"] == 1.0 for L_ in (g["top"], g["bot"], g["jump"])))
    check(f"grade: orange top Y {y(g['top'], 180):.0f} < bottom Y {y(g['bot'], 180):.0f} (deep fiery top, light toward yellow below)", y(g["top"], 180) + 20 < y(g["bot"], 180))
    check("grade: the bands / drop layer is near black", y(g["dark"], 180) < 40)
    for st, e_, b_ in (("hype", 0.8, 128), ("chill", 0.4, 85), ("aggressive", 0.9, 150)):
        rk = M.sky_ranked(st, e_, b_)[0]
        f1 = M.sky_family_for({"song": {"path": "nope.mp3"}}, rk)
        f2 = M.sky_family_for({"song": {"path": "nope.mp3"}}, rk)
        check(f"{st}: one family chosen once from the vibe ({f1[0]}: {f1[1]})", f1 == f2 and f1[0] in fams)
    q = [{"info": {"scene_y": 180.0, "sample": {"lab": [200.0, 128, 110]}}}] * 3
    check("white family that would wash out most skies falls back to a coloured family", M.sky_family_for({"song": {"path": "nope.mp3"}}, ["white", "teal"], q)[0] == "teal")
    check("cover hue -> family", [M.sky_family_from_hue(h) for h in (5, 25, 45, 120, 180, 220, 270, 320)] == ["red", "orange", "amber", "green", "teal", "blue", "violet", "rose"])
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    i = src.index("def xfx_probe_sky")
    body = src[i:src.index("\ndef ", i + 10)]
    check("render: the family is chosen once per montage, every sky uses it", body.count("sky_family_for(") == 1 and "sky_colour_for(" not in body and "sky_alt_colour(" not in body)
    an_ = M.sky_anim_params(0.8, 128, "hype", False)
    beats = [(0.5 + 0.469 * i, 1.0 if i % 4 == 0 else 0.45) for i in range(8)]
    rows = M.sky_band_rows(200, 150, 240, 30, beats, an_)
    check("bands: nothing before the kill frame", all(not r_.any() for r_ in rows[:30]))
    r = rows[60]
    sp = np.abs(np.fft.rfft(r[:150] - r[:150].mean()))
    pk = int(np.argmax(sp[1:]) + 1)
    check(f"bands: one clean period (spectral peak {pk} cycles / 150 rows holds {sp[pk] / sp[1:].sum():.0%} of the energy)", sp[pk] / sp[1:].sum() > 0.3)
    check("bands: deterministic", all(np.array_equal(a_, b_) for a_, b_ in zip(rows, M.sky_band_rows(200, 150, 240, 30, beats, an_))))
    f_b = int(round(beats[2][0] * 60))
    mv = lambda f: float(np.abs(rows[f + 1] - rows[f]).mean())
    check(f"bands: step on the beat ({mv(f_b + 3):.4f}) far more than between beats ({mv(f_b + 20):.4f})", mv(f_b + 3) > 4 * mv(f_b + 20))
    # the chain in ffmpeg: synthetic 4-plane mask (sky top third, the family gradient, a band, a jump)
    tmp = Path(tempfile.mkdtemp())
    mk = tmp / "m.yuv"
    H, W = M.SKY_H, M.SKY_W
    with open(mk, "wb") as fh:
        for f in range(60):
            y_ = np.zeros((H, W), np.uint8)
            y_[:H // 3] = 240
            u_ = np.zeros((H, W), np.uint8)
            v_ = np.full((H, W), 255 if 30 <= f < 34 else 0, np.uint8)
            a_ = np.repeat(np.clip(np.arange(H) / (H / 3) * 255, 0, 255).astype(np.uint8)[:, None], W, 1)
            fh.write(y_.tobytes() + u_.tobytes() + v_.tobytes() + a_.tobytes())
    x = {"mask": str(mk), "mask_fmt": "yuva444p", "p": 0.2, "push": 0.0, "grade": M.sky_family_grade("orange", 175.0)}
    chains = []
    lab = M.xfx_sky_chain(chains, "t0", "[src]", x, 1)
    gph = "[0:v]format=yuv420p[src];" + ";".join(chains) + f";{lab}null[o]"
    r_ = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x78A8E0:s=1920x1080:r=60:d=1"] + M.sky_mask_input(x) +
                        ["-filter_complex", gph, "-map", "[o]", "-frames:v", "60", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    ok = r_.returncode == 0 and len(r_.stdout) == 60 * 1920 * 1080 * 3
    check("family sky chain renders (ffmpeg, 1 s)", ok, r_.stderr.decode("utf-8", "ignore")[-300:])
    if ok:
        fr = lambda i_: np.frombuffer(r_.stdout[i_ * 1920 * 1080 * 3:(i_ + 1) * 1920 * 1080 * 3], np.uint8).reshape(1080, 1920, 3)
        a, j = fr(50), fr(31)
        top, mid, low = a[10:40, 300:1600].reshape(-1, 3).mean(0), a[300:340, 300:1600].reshape(-1, 3).mean(0), a[800:1000, 300:1600].reshape(-1, 3).mean(0)
        check(f"orange gradient: top {top.round().tolist()} deeper than the lower sky {mid.round().tolist()}", top[0] > top[2] + 60 and mid.sum() > top.sum() + 40 and mid[1] > top[1])
        check(f"the rest of the picture untouched {low.round().tolist()}", abs(low[2] - 224) < 3)
        jt = j[150:180, 300:1600].reshape(-1, 3).mean(0)
        check(f"beat jump to the family's bright colour {jt.round().tolist()}", jt[1] > a[150:180, 300:1600].reshape(-1, 3).mean(0)[1] + 20 and jt[0] > jt[2] + 60)
    check("sky on / off switch and coverage rules unchanged", M.SKY_START == {"cs2": True, "valorant": True, "r6s": False} and M.XFX_SKY_MIN_COV == 0.03 and M.XFX_SKY_MAX_COV == 0.60)


def _silent_an():
    an = copy.deepcopy(T.an())
    dur = float(an["dur"])
    w = []
    for i in range(2000):
        t = i * dur / 2000
        w.append(0.5 if 2.0 <= t <= dur - 4.0 else 0.0)  # 2 s of silence at the start, 4 s at the end (like Maniac)
    an["wave"] = w
    return an


def part2():
    print("2) dead air trimmed in every game and mode")
    an = _silent_an()
    lv0, lv1 = M.song_live_range(an)
    check(f"synthetic song: audible {lv0:.2f} - {lv1:.2f} of {an['dur']:.2f} s", abs(lv0 - 2.0) < 0.1 and abs(an["dur"] - 4.0 - lv1) < 0.1)
    song = {"path": str(T.SONG), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
    keep = M.clip_audio
    M.clip_audio = lambda rec, *a, **k: {"stream": None, "lufs": None}
    try:
        for game in ("valorant", "cs2", "r6s"):
            for mode, target, manual, full in (("Auto Optimal", "optimal", False, False), ("Manual Optimal", "optimal", True, False), ("fixed 60 s", 60, True, False),
                                               ("Auto fixed 60 s", 60, False, False), ("full (Force Full / Force New Full / Manual Auto)", "optimal", True, True)):
                cfg = dict(M.DEFAULT_CONFIG)
                M.FULL_CTX.update(on=full, game=game)
                M.FULL_CTX.pop("live", None)
                try:
                    plan = M.plan_montage(cfg, game, copy.deepcopy(M.fake_events()), song, an, 7, "hype", target, [], [], manual=manual)
                finally:
                    M.FULL_CTX["on"] = False
                    M.FULL_CTX.pop("live", None)
                s_ = float(plan["song"]["start_t"])
                e_ = s_ + float(plan["duration"])
                check(f"{game} {mode}: song {s_:.2f} - {e_:.2f} s inside the audible part", s_ >= lv0 - 0.03 and e_ <= lv1 + 0.01)
    finally:
        M.clip_audio = keep
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("dry plan and render share the one make_plan (no separate trim path)", src.count("song_end = min(song_end, float(live_[1]) - 0.1)") == 1)


def part3():
    print("3) every full-song montage fills the song")
    an = _silent_an()
    lv0, lv1 = M.song_live_range(an)
    want = M.song_fill_target(an, False, "optimal")
    check(f"Optimal (Auto / Manual / dry plan / render): the whole trimmed song ({want} s)", want is not None and abs(want - (lv1 - 0.1 - max(lv0, an["beats"][0]))) < 0.05)
    check("full mode too", M.song_fill_target(an, True, "optimal") == want)
    check("a fixed length from the slider is not a full-song montage", M.song_fill_target(an, False, 60) is None)
    long_ = dict(an, dur=400.0, wave=[0.5] * 2000, beats=list(np.arange(0.2, 400, 0.47)))
    check("a song longer than the maximum keeps its section (no fill target)", M.song_fill_target(long_, True, "optimal") is None and M.song_fill_target(long_, False, "optimal") is None)
    check(f"at most {M.SONG_FILL_ROUNDS} re-plans; re-plan over {M.AUTO_TOL_S:.0f} s short, the run-in extend rule under it, the end within {M.SONG_FILL_END_S:.0f} s", M.SONG_FILL_ROUNDS == 2 and M.AUTO_TOL_S == 6.0 and M.SONG_FILL_END_S == 3.0)
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    i = src.index("want_s = song_fill_target(an, full, target)")
    blk = src[i:i + 3000]
    check("the fill only adds clips (picked + add), never removes a chosen one", "picked = picked + add" in blk and "picked.remove" not in blk)
    check("the song-end run-in fill runs in every mode (not only full mode)", 'if fit and takes and head_take in takes:' in src)
    check("Manual Auto still tops up its ticks the same way", "allp, top = auto_fill_topup(" in src)


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
    sys.exit(1 if T.FAILS else 0)
