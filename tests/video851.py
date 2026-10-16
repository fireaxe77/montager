"""V8.5.1 tool: a short REAL clip (about 10 s) with the new sky recolour, rendered through the montage render's own chain (mask file + xfx_sky_chain), with the clip's sound.
python tests/video851.py <clip> <kill time s> <out.mp4> [style energy bpm] [seconds = 10]   (the sky lands on the kill frame, 1/3 into the take, and stays to the end)"""
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import montage as M                                                                           # noqa: E402
import sky851                                                                                 # noqa: E402

clip, tm, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
style, energy, bpm = (sys.argv[4:7] + ["hype", "0.74", "150"][len(sys.argv[4:7]):])[:3]
secs = float(sys.argv[7]) if len(sys.argv) > 7 else 10.0
wh = sky851.probe_wh(clip)
cz = M.DEFAULT_REGION["cs2"]
zone = [cz[0], cz[1], cz[2], cz[1] + 0.55 * (cz[3] - cz[1])]
p = secs / 3
ss = max(0.0, tm - p)
nf = int(round(secs * 60))
take = {"nf": nf, "segs": [[ss, ss + secs, 1.0, nf, 0]], "srcs": [{"path": clip, "shift": 0.0, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}], "path": clip, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}
img = M.sky_grab_frames(clip, tm, tm + 0.04, [0, 0, wh[0], wh[1]], wh, fps=60)[0]
_, info = M.sky_segment(img, zone)
ranked, _w = M.sky_ranked(style, float(energy), float(bpm))
cname, crgb, _cw = M.sky_colour_for(ranked, info.get("sky_rgb"), info.get("scene_hue"))
gk, _g = M.sky_gradient_kind(style, float(energy), float(bpm))
top_, hor_ = M.sky_gradient(crgb, gk)
x = {"k": "sky", "p": p, "t0": p, "t1": secs}
tmp = Path(tempfile.mkdtemp())
mp = tmp / "mask.yuv"
st = M.sky_take_mask(take, x, zone, mp, ramp=True)
x.update({"mask": str(mp), "grade": M.sky_grade(crgb, st["mean_y"], (top_, hor_), gk), "ok": True})
pre = f"scale=1920:1080:flags=lanczos,setsar=1,fps=60,format=yuv420p,setpts=PTS-STARTPTS,trim=end_frame={nf},setpts=PTS-STARTPTS"
chains = []
nl = M.xfx_sky_chain(chains, "t0", "[src]", x, 1)
fc = f"[0:v]{pre}[src];" + ";".join(chains) + f";{nl}null[o]"
cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{ss:.3f}", "-t", f"{secs:.3f}", "-i", clip] + M.sky_mask_input(x) + [
    "-filter_complex", fc, "-map", "[o]", "-map", "0:a:0?", "-c:v", "libx264", "-crf", "22", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "60", "-c:a", "aac", "-b:a", "160k", "-shortest", out]
r = subprocess.run(cmd, capture_output=True)
print("ffmpeg exit", r.returncode, r.stderr.decode("utf-8", "ignore")[-300:], f"sky colour {cname} gradient {gk}; wrote {out} ({Path(out).stat().st_size / 1e6:.1f} MB)")
mp.unlink()
