"""V8.8.4 check: one real R6S render (Manual, Optimal, extra effects, sky on for R6S) of the clips whose second kill used to be lost (kills 10 - 12 s apart), the two Siege clips that lost a kill
with only a 'no gunshot heard' note, and R6S multikill clips with a clear sky on the last kill. Prints per clip the kills detected / placed in its take, the sky lines of the render, and writes a frame
sheet of every sky take (top vs bottom colour of the painted sky = the gradient). Run on a COPY of montage_data (MONTAGER_DATA=<copy>).
python tests/render884.py <out dir> [song fragment = Perfect Exceeder] [sky clips = 3]"""
import copy
import subprocess
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
ROOT = _root.find_root()
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")
import montage as M                                                                           # noqa: E402
import numpy as np                                                                            # noqa: E402
import cv2                                                                                    # noqa: E402

outd = Path(sys.argv[1])
outd.mkdir(parents=True, exist_ok=True)
frag = sys.argv[2] if len(sys.argv) > 2 else "Perfect Exceeder"
n_sky = int(sys.argv[3]) if len(sys.argv) > 3 else 3
WANT = ["2023.10.31 - 01.11.17", "2023.11.10 - 20.59.47", "2023.11.13 - 17.11.08", "2023.11.19 - 00.36.31", "2023.11.25 - 02.55.04"]
cfg = dict(M.load_config())
cfg["effects_game"] = dict(cfg.get("effects_game") or {}, r6s="extra")
cfg["sky_game"] = dict(cfg.get("sky_game") or {}, r6s=True)
M.QUIET.on = True
pool, _st = M.game_pool(cfg, "r6s")
M.QUIET.on = False
by = {it["rec"]["path"]: it for it in pool}
picked = [p for p in by if any(w in Path(p).name for w in WANT)]
sky = []
for it in sorted(pool, key=lambda it: -len(it["kills"])):
    if len(sky) >= n_sky or len(it["kills"]) < 2 or it["rec"]["path"] in picked:
        continue
    ev = {"path": it["rec"]["path"], "rec": it["rec"], "times": [max(float(k["t"]) for k in it["kills"])]}
    cov = M.event_sky_cov(ev, cfg)
    if M.sky_clear(cov):
        sky.append(it["rec"]["path"])
print("clips:", [Path(p).name for p in picked], "+ sky clips:", [Path(p).name for p in sky])
songs, _, _ = M.song_pool(cfg, cached_only=True)
song = [s for s in songs if frag.lower() in (s["title"] + " " + Path(s["path"]).name).lower()][0]
M.song_fill_target = lambda *a, **k: None                 # this check renders only the chosen clips (no song fill)
plan, text = M.make_plan(cfg, "r6s", picked + sky, song["path"], "optimal", "hype", 884, None, None, scan=False)
det = {p: sorted(round(float(k["t"]), 2) for k in by[p]["kills"]) for p in picked + sky}
print(f"plan: {len(plan['takes'])} takes, {plan['duration']:.1f} s")
for i, t in enumerate(plan["takes"]):
    srcs = [s["path"] for s in t.get("srcs") or [{"path": t["path"]}]]
    d_ = sorted({x for p in srcs for x in det.get(p, [])})
    print(f"  take {i + 1} {Path(t['path']).name}: {len(t['kills'])} kills placed at {', '.join(f'{x:.2f}' for x in t['kills'])} s (detected in its clip(s): {', '.join(f'{x:.2f}' for x in d_)}); "
          f"take {t['dur']:.2f} s, first kill at {t['kills_out'][0]:.2f} s, last row at {max(t['rows_out']):.2f} s")
out = outd / "r6s_884.mp4"
M.render_plan(plan, out, cfg)
for ln in (M.LOG_DIR / "montage.log").read_text(encoding="utf-8", errors="ignore").splitlines()[-400:]:
    if "SKY recolour" in ln:
        print("  " + ln[20:320])
rows = []
for i, t in enumerate(plan["takes"]):
    for x in t.get("xfx") or []:
        if x.get("k") == "sky" and x.get("ok"):
            t0 = float(t["out_start"]) + float(x["p"])
            fr = []
            for dt in (0.4, 0.8, 1.2):
                r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t0 + dt:.3f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=480:270", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True)
                if len(r.stdout) == 480 * 270 * 3:
                    fr.append(np.frombuffer(r.stdout, np.uint8).reshape(270, 480, 3))
            if fr:
                rows.append(np.concatenate(fr, 1))
                print(f"  sky take {i + 1}: {x.get('hue')} family, frames at +0.4 / +0.8 / +1.2 s after the kill in the sheet")
if rows:
    w_ = max(r.shape[1] for r in rows)
    cv2.imwrite(str(outd / "r6s_884_sky.jpg"), np.concatenate([np.pad(r, ((0, 0), (0, w_ - r.shape[1]), (0, 0))) for r in rows], 0), [cv2.IMWRITE_JPEG_QUALITY, 90])
print("rendered", out)
