"""V8.8.8 check (real render): one saved plan rendered the old way (one ffmpeg run) and the new way (the takes in parallel, streamed to the encoder), the two videos
decoded and compared frame by frame (every picture frame and every sound packet: framemd5) and against an earlier video of the same plan if given.
Run on a COPY of montage_data (MONTAGER_DATA=<copy>): the sky check writes caches.
python tests/render888.py <plan.json> <out dir> [earlier video = none] [which = both | fast | old] [sky spread = 0 | 1]
  sky spread 0 (default) = the V8.8.7 sky pattern / colour choice, so a video made by V8.8.7 from this plan must come out identical.
Note: the old one-run render pairs a dissolve's frames by ffmpeg's thread timing, so two old renders of one plan can differ in a dissolve frame (and NVENC's 32-frame
look-ahead spreads that over the frames before it); the new render is the same on every run. With an earlier video the check is earlier == new."""
import json
import subprocess
import sys
import time
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
ROOT = _root.find_root()
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")
import montage as M                                                                           # noqa: E402

planp, outd = Path(sys.argv[1]), Path(sys.argv[2])
earlier = Path(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3] not in ("", "none") else None
which = sys.argv[4] if len(sys.argv) > 4 else "both"
M.SKY_PICK_SPREAD[0] = len(sys.argv) > 5 and sys.argv[5] == "1"
outd.mkdir(parents=True, exist_ok=True)
SKY_KEYS = ("ok", "mask", "grade", "cov", "anim", "beats", "fam", "pattern", "mask_fmt", "frames_src", "horizon", "sky_cut")


def load_plan():
    plan = json.load(open(planp, encoding="utf-8"))
    for t in plan["takes"]:
        for x in t.get("xfx") or []:
            if x.get("k") == "sky":
                for k in SKY_KEYS:
                    x.pop(k, None)                         # the sky is checked and its masks made again, as in a real render
    return plan


def md5s(p):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "framemd5", "-"], capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if not l.startswith("#")]


res = {}
for mode in (["old", "fast"] if which == "both" else [which]):
    M.FAST_RENDER[0] = mode == "fast"
    out = outd / f"{planp.stem.replace('.plan', '')}_{mode}.mp4"
    logs = []
    keep = M.LOGONLY
    M.LOGONLY = lambda m, keep=keep: (logs.append(str(m)), keep(m))[1]
    t0 = time.time()
    try:
        M.render_plan(load_plan(), out, M.load_config())
    finally:
        M.LOGONLY = keep
    el = time.time() - t0
    res[mode] = (out, el, md5s(out), M.probe_duration(out))
    print(f"{mode}: {el:.1f} s, {res[mode][3]:.3f} s long, {len(res[mode][2])} frames + sound packets")
    for l_ in logs:
        if "fast render" in l_:
            print("   ", l_)
FAILS = []
if len(res) == 2:
    a, b = res["old"][2], res["fast"][2]
    nd = sum(1 for x, y in zip(a, b) if x != y) + abs(len(a) - len(b))
    print(f"old vs fast: {nd} of {len(a)} frames / sound packets differ; render {res['old'][1]:.0f} s -> {res['fast'][1]:.0f} s")
    if nd and not earlier:
        FAILS.append("old vs fast")
if earlier:
    e = md5s(earlier)
    for mode, (_o, _el, h, _d) in res.items():
        nd = sum(1 for x, y in zip(e, h) if x != y) + abs(len(e) - len(h))
        print(f"{earlier.name} vs {mode}: {nd} of {len(e)} differ")
        if mode == "fast" and nd:
            FAILS.append(f"{earlier.name} vs fast")
print("FAILED: " + ", ".join(FAILS) if FAILS else "identical")
sys.exit(1 if FAILS else 0)
