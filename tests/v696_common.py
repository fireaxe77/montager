"""Shared helpers of the V6.9.6 tests (generated media only): check / section bookkeeping, ffmpeg clip generators, plan + render helpers."""
import hashlib
import json
import os
import re
import subprocess
import _run as R                                                                              # noqa: E402  (V6.9.7 shared subprocess helper)
import sys
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

FAILS, SECTIONS = [], []
REAL_OUT, REAL_LO = M.out, M.LOGONLY
BASE_REF = os.environ.get("V696_BASE", "88a9710")          # origin/v6.9.5: the commit v6.9.6 branches from
REAL_DATA = ROOT / "montage_data"


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


class section:
    def __init__(self, title):
        self.title = title

    def __enter__(self):
        self.t = time.time()
        print(f"== {self.title} ==")

    def __exit__(self, *a):
        SECTIONS.append((self.title, time.time() - self.t))
        print(f"   [{self.title}: {time.time() - self.t:.1f} s]")


def logged(fn, *a, **k):
    lines = []
    M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        res = fn(*a, **k)
    finally:
        M.out, M.LOGONLY = REAL_OUT, REAL_LO
    return res, lines


def snapshot(d):
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(d).rglob("*")) if p.is_file()} if Path(d).exists() else {}


def ff(args):
    r = R.run(["ffmpeg", "-y", "-v", "error"] + args, capture_output=True)
    assert r.returncode == 0, r.stderr.decode()[-400:]


def mv(n="N"):
    """geq expression: a thin white bar (6 px) that moves 10 px per frame inside the central region (wraps every 16 frames)."""
    return f"geq=lum='if(between(X,80+mod({n}*10,160),86+mod({n}*10,160))*between(Y,60,120),255,0)':cb=128:cr=128"


def gen_clip(path, vf, fps=60, dur=8, extra=()):
    ff(["-f", "lavfi", "-i", f"color=c=black:s=320x180:r={fps}:d={dur}", "-vf", vf, *extra, "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(path)])
    return str(path)


def mvf(n="N", flash_frames=()):
    """mv() plus a full-frame white flash on the given frame numbers (the timing marker)."""
    fl = "+".join(f"eq(N,{f})" for f in flash_frames) or "0"
    return (f"geq=lum='if({fl},255,if(between(X,80+mod({n}*10,160),86+mod({n}*10,160))*between(Y,60,120),255,0))':cb=128:cr=128")


def clip_info(path):
    r = R.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames,avg_frame_rate,r_frame_rate,start_time:format=duration",
                        "-of", "json", str(path)], capture_output=True)
    j = json.loads(r.stdout)
    s = j["streams"][0]
    return {"n": int(s["nb_read_frames"]), "dur": float(j["format"]["duration"]), "start": float(s.get("start_time") or 0), "avg": s["avg_frame_rate"], "r": s["r_frame_rate"]}


def silent_song(path, secs=10):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(np.zeros(44100 * secs, np.int16).tobytes())
    return str(path)


def mkplan(clip, segs, song, wh=(320, 180)):
    """A one-take plan on a generated 320x180 clip (the real filter graph scales it to 1920x1080)."""
    src = {"path": clip, "shift": 0.0, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh), "audio": False, "a_stream": 0, "gain_db": -6.0}
    nf = sum(s_[3] for s_ in segs)
    return {"takes": [{"path": clip, "srcs": [src], "rect": src["rect"], "wh": src["wh"], "audio": False, "segs": segs, "kills_out": [0.5], "pulses": [], "amp": 0.0,
                       "f0": 0, "nf": nf, "out_start": 0.0, "dur": nf / 60}],
            "duration": nf / 60, "song": {"path": song, "start_t": 0.0, "fade_out_start": max(0.0, nf / 60 - 0.5)}}


def run_graph(plan, out, tmp, fx=None):
    """Encode the plan with the REAL filter graph (build_filter) to a small test file. Returns (inputs, graph text)."""
    inputs, graph = M.build_filter(plan, {}, False, fx if fx is not None else M.FX_ALL)
    gp = Path(tmp) / "graph.txt"
    gp.write_text(graph, encoding="utf-8")
    ff(inputs + ["-filter_complex_script", str(gp), "-map", "[vout]", "-map", "[aout]", "-t", f"{plan['duration']:.3f}", "-c:v", "libx264", "-crf", "12", "-preset", "ultrafast",
                 "-pix_fmt", "yuv420p", "-r", "60", "-c:a", "aac", str(out)])
    return inputs, graph


def out_frames(path):
    r = R.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=160:90,format=gray", "-f", "rawvideo", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(-1, 90, 160).astype(float)


def unique_per_s(path):
    """Distinct pictures per second of an output file (a frame counts when it differs from the previous one)."""
    a = out_frames(path)
    d = np.abs(np.diff(a, axis=0)).mean(axis=(1, 2))
    return float((d > 0.3).sum() / (len(a) / 60.0))


def crisp_per_s(path):
    """Frames per second that show the marker as ONE sharp bar (a blended frame shows two half-bright bars)."""
    a = out_frames(path)
    return float(((a.max(axis=(1, 2)) > 200).sum()) / (len(a) / 60.0))


def first_bright(path, thr=200):
    a = out_frames(path)
    m = a.mean(axis=(1, 2))
    i = int(np.argmax(m > thr)) if (m > thr).any() else -1
    return i / 60.0
