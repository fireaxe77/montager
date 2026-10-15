"""V8.4.3 tests (fast; only tiny ffmpeg runs on synthetic files, no montage render).
  0) title-bar version V8.4.3; V8.4.3 on top of V8.4.2 in both changelogs
  1) DEFAULT = V8.23.1: plan, plan text, filter graph for all three games (clips without an audio hole build the identical graph)
  2) no glow / flash effects in any EXTRA plan; only effects that do not cover the picture are left
  3) audio hole: detected on a synthetic clip with a gap in its audio, the OLD chain fails on it ("Invalid data"), the silence chain renders
  4) sky rule: sky-blue only (teal / purple / white / orange walls rejected), real sky accepted
  5) retries: 3 attempts at most, variants restore the takes, the last one is the plain DEFAULT plan
python tests\\test_v843.py   (parts: V843_PARTS=0,1,2,3,4,5)"""
import copy
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import types                                                                                  # noqa: E402
_src = (HERE / "test_v842.py").read_text(encoding="utf-8")                                     # only the helpers of test_v842 (everything before its first part), not its test run
_ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
exec(compile(_src[:_src.index("def part0")], str(HERE / "test_v842.py"), "exec"), _ns)
T = types.SimpleNamespace(**_ns)

M = T.M
ROOT = T.ROOT
check, mk, js = T.check, T.mk, T.js
PARTS = [x for x in os.environ.get("V843_PARTS", "0,1,2,3,4,5").split(",") if x]


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.4.3", M.APP_VERSION == "V8.4.3")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.4.3 above V8.4.2", cl[0].startswith("## V8.4.3") and cl[1].startswith("## V8.4.2"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.4.3 above V8.4.2", sm[0].startswith("## V8.4.3") and sm[1].startswith("## V8.4.2"), str(sm[:2]))
    seg = body[body.index("## V8.4.3"):body.index("## V8.4.2")].lower()
    check("simple entry is plain", not any(w in seg for w in ("test", "known issue", "on hold", "def ", "xfx", "ffmpeg")))


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
    print("2) no glow / flash")
    for g in ("cs2", "valorant", "r6s"):
        for style in ("aggressive", "hype", "chill"):
            e, c = mk(M, g, style, 2, eff=T.ALL_EXTRA)
            kinds = {x["k"] for t in e["takes"] for x in t.get("xfx", [])}
            check(f"{g} / {style}: kinds {sorted(kinds)} are split / punch / grade / cut / sky only", kinds <= {"rgb", "punch", "rise", "after", "settle", "mirror", "sky", "speed"})
            gr = M.build_filter(e, c, False)[1]
            check(f"{g} / {style}: no colour glow layer in the graph (no glow blend with a drawbox colour)", "color=0x" not in gr)


def part3():
    print("3) audio hole")
    d = T.TMP / "hole"
    d.mkdir(exist_ok=True)
    base, gap = d / "base.mp4", d / "gap.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=60:duration=10", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=10",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(base)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(base), "-c", "copy", "-bsf:a", "setts=pts='if(gt(PTS,96000),PTS+192000,PTS)':dts='if(gt(DTS,96000),DTS+192000,DTS)'", str(gap)], check=True)
    M._APKT.clear()
    check("a range inside the hole is a hole", M.audio_hole(gap, 0, 3.0, 1.3))
    check("ranges with sound are not", not M.audio_hole(gap, 0, 0.5, 1.0) and not M.audio_hole(gap, 0, 6.5, 2.0) and not M.audio_hole(base, 0, 3.0, 1.3))
    check("an unreadable file is not a hole (old chain kept)", not M.audio_hole(d / "nope.mp4", 0, 1.0, 1.0))

    def run_chain(silent):
        a0 = ("anullsrc=r=48000:cl=stereo,atrim=duration=1.0,asetpts=PTS-STARTPTS[a0]" if silent else
              "[0:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,apad,atrim=duration=1.0[a0]")
        fc = a0 + ";[1:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,apad,atrim=duration=1.8[a1];[a0][a1]concat=n=2:v=0:a=1[o]"
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", "3", "-t", "1.3", "-i", str(gap), "-ss", "6.5", "-t", "2", "-i", str(gap), "-filter_complex", fc, "-map", "[o]", "-f", "null", "-"]
        return subprocess.run(cmd, capture_output=True).returncode
    check("the OLD chain on the hole segment fails (Invalid data), the silence chain renders", run_chain(False) != 0 and run_chain(True) == 0)
    p, c = mk(M, "valorant", "aggressive", 2)
    for t in p["takes"]:
        t["audio"] = True
        for sr in t.get("srcs") or []:
            sr["audio"] = True
    g0 = M.build_filter(p, c, False)[1]
    keep = M.audio_hole
    M.audio_hole = lambda *a, **k: True
    try:
        g1 = M.build_filter(p, c, False)[1]
    finally:
        M.audio_hole = keep
    check("when ranges are holes the game audio of those takes becomes anullsrc silence", g1.count("anullsrc") > g0.count("anullsrc"))


def part4():
    print("4) sky rule")
    import numpy as np

    def cov(rgb):
        a = np.zeros((270, 480, 3), np.uint8)
        a[:] = (40, 40, 40)
        a[:100, 150:] = rgb
        return float(M.sky_mask_np(a)[:int(270 * .55)].mean())
    check("sky blue is sky", cov((110, 170, 235)) > 0.3 and cov((150, 175, 215)) > 0.3)
    check("teal wall, purple light, white wall, orange wall are not", all(cov(c) < 0.01 for c in ((60, 180, 190), (130, 120, 255), (235, 235, 235), (220, 150, 80))))
    check("the radar corner is never sky", not M.sky_mask_np(np.full((270, 480, 3), (110, 170, 235), np.uint8))[:80, :100].any())


def part5():
    print("5) retries")
    check("three attempts at most", len(M.EXTRA_ATTEMPTS) == 3)
    e, c = mk(M, "valorant", "aggressive", 2, eff=T.ALL_EXTRA)
    check("takes remember their pre-effect values", all("xfx0" in t for t in e["takes"]))
    v1, v2 = M.extra_variant(e, 1), M.extra_variant(e, 2)
    check("attempt 2 keeps no sky / split / grade / punch / settle / speed", all(x["k"] == "mirror" for t in v1["takes"] for x in t.get("xfx", [])))
    check("attempt 3 is a DEFAULT plan: no extra data, effects default", v2["effects"] == "default" and not any("xfx" in t or "xfx0" in t for t in v2["takes"]))
    d, cd = mk(M, "valorant", "aggressive", 2, eff=T.ALL_DEFAULT)
    check("attempt 3 restores segments / ramps / kill punch of the plain plan (same seed)", all(a["segs"] == b["segs"] and a.get("ramp") == b.get("ramp") and a.get("amp") == b.get("amp") for a, b in zip(d["takes"], v2["takes"])))
    check("attempt 3 graph equals the DEFAULT graph of the same plan", M.build_filter(v2, c, False, set(M.FX_ALL))[1] == M.build_filter(d, cd, False)[1])
    check("attempt 1 is the plan itself", M.extra_variant(e, 0) is e)


if __name__ == "__main__":
    for n in PARTS:
        globals()["part" + n]()
    print(("\nFAILED: " + "; ".join(T.FAILS)) if T.FAILS else "\nall ok")
    sys.exit(1 if T.FAILS else 0)
