"""V8.6.2 tool: is the clip game audio bass-boosted by OUR chain, or is that in the source clips?
python tests/audio862.py <plan.json> <out dir> [takes = 5] [first takes to render = 14] [out.txt]
The first takes of a saved plan are rendered again through the montage's own render (render_plan) with the music replaced by SILENCE, so the render holds ONLY the game audio exactly as our chain makes it
(aresample, aformat, [atempo], volume = the clip's gain + lift + kill boost, concat, the 2 dB headroom, the limiter; no EQ and no loudness step exists in the chain). For N takes (a 1.0x stretch of 1 - 2 s,
one source clip, game audio) the low-end share (energy 20 - 200 Hz relative to 200 Hz - 4 kHz, in dB) of the SOURCE clip audio at that moment is compared with the same moment in that render."""
import json
import subprocess
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

plan_f, out_dir = sys.argv[1], Path(sys.argv[2])
n_takes = int(sys.argv[3]) if len(sys.argv) > 3 else 5
n_first = int(sys.argv[4]) if len(sys.argv) > 4 else 14
out_dir.mkdir(parents=True, exist_ok=True)
plan = json.load(open(plan_f, encoding="utf-8"))
sub = dict(plan)
sub["takes"] = [dict(t, xfx=[x for x in (t.get("xfx") or []) if x.get("k") != "sky"]) for t in plan["takes"][:n_first]]
sub["xfx_drop"] = []
sub["duration"] = sub["takes"][-1]["out_start"] + sub["takes"][-1]["dur"]
sub["total_frames"] = sum(int(t["nf"]) for t in sub["takes"])
sil = out_dir / "silence.wav"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", str(float(plan["song"]["start_t"]) + sub["duration"] + 30), str(sil)], check=True)
sub["song"] = dict(plan["song"], path=str(sil))
render = out_dir / "game_only.mp4"
M.render_plan(sub, str(render), M.load_config(), maxq=False, preview=False, encoder=None, effects=True)
plan = sub
SR = 48000


def pcm(path, ss, dur, stream=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, ss):.3f}", "-t", f"{dur:.3f}", "-i", str(path)] + (["-map", f"0:a:{stream}"] if stream is not None else []) + ["-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.float32)


def bands(x):
    n = len(x)
    if n < SR // 2:
        return None
    w = np.hanning(8192)
    acc = None
    for i in range(0, n - 8192, 4096):
        sp = np.abs(np.fft.rfft(x[i:i + 8192] * w)) ** 2
        acc = sp if acc is None else acc + sp
    f = np.fft.rfftfreq(8192, 1.0 / SR)
    lo = acc[(f >= 20) & (f < 200)].sum()
    mid = acc[(f >= 200) & (f < 4000)].sum()
    return 10 * np.log10((lo + 1e-12) / (mid + 1e-12))


rows, deltas = [], []
song_start = float(plan["song"]["start_t"])
drops = [float(d["t"]) for d in (plan.get("xfx_drop") or [])]
for ti, t in enumerate(plan["takes"]):
    if len(rows) >= n_takes:
        break
    if len(t.get("srcs") or [1]) != 1 or not t["srcs"][0].get("audio") or t["srcs"][0].get("mute"):
        continue
    src = t["srcs"][0]
    o = 0
    for sg in t["segs"]:
        a, b, sp, n = sg[:4]
        if abs(sp - (b - a) * 60.0 / n) < 1e-3 and abs(sp - 1.0) < 0.02 and n >= 75:
            d = min(2.0, n / 60.0 - 0.1)
            t_out = t["out_start"] + o / 60.0 + 0.05
            if any(abs(t_out + d / 2 - x) < d / 2 + 1.0 for x in drops):
                break
            s_pcm = pcm(src["path"], a - src["shift"] + 0.05, d, int(src.get("a_stream") or 0))
            r_pcm = pcm(render, t_out, d)
            k = min(len(s_pcm), len(r_pcm))
            if k < SR:
                break
            s_pcm, game = s_pcm[:k], r_pcm[:k]
            bs, bg = bands(s_pcm), bands(game)
            if bs is None or bg is None or np.sqrt((s_pcm ** 2).mean()) < 1e-4:
                break
            rows.append(f"take {ti + 1:2d} ({Path(src['path']).name[:44]}): source low-end share {bs:+6.1f} dB | render game audio {bg:+6.1f} dB | difference {bg - bs:+5.1f} dB | chain: clip gain {src['gain_db']} dB (lift {src.get('lift_db')})")
            deltas.append(bg - bs)
            break
        o += n
txt = f"{plan['game']}: {len(rows)} takes\n" + "\n".join(rows) + (f"\nmean difference render - source: {np.mean(deltas):+.1f} dB (positive = our chain adds low end)" if deltas else "")
print(txt)
if len(sys.argv) > 5:
    Path(sys.argv[5]).write_text(txt + "\n", encoding="utf-8", errors="replace")
