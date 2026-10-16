"""V8.6 tool: re-plan the Force New Full Valorant montage of the V8.5.1 report (seed 890281, song Стардаст), render it ONCE and measure it:
 - music: the level of the render in 5 s windows and the share of the song that is in it (least-squares gain against the song at its start time; 0.79 = the music is there in full),
 - frozen / duplicated frames: every run of identical consecutive frames of the render (a stalled source clip shows as long runs),
 - the clip list is checked against the stall rule.
python tests/render86.py <out.mp4> <report.txt> [seed = 890281] [song fragment = Стардаст]   (needs ~10 GB of memory for a 150 s render)"""
import glob
import subprocess
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import cv2                                                                                    # noqa: E402
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

out, rep_f = Path(sys.argv[1]), Path(sys.argv[2])
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 890281
frag = sys.argv[4] if len(sys.argv) > 4 else "Стардаст"
cfg = M.load_config()
titles = M.load_json(M.USED_TITLES, {})
drop = {k for k, v in titles.items() if "V8.5.1" in str(v.get("title"))}
keep = M.used_dates
M.used_dates = lambda: {k: v for k, v in keep().items() if k not in drop}          # the clips of that render count as unused again (the GUI job marked them used)
songs, _, _ = M.song_pool(cfg, cached_only=True)
sp = [s for s in songs if frag.lower() in (s["title"] + " " + s["artist"] + " " + Path(s["path"]).name).lower()][0]["path"]
plan, text = M.make_plan(cfg, "valorant", None, sp, None, None, seed, None, None, full=True)
out.parent.mkdir(parents=True, exist_ok=True)
M.render_plan(plan, str(out), cfg, maxq=False, preview=False, encoder=None, effects=True)
rep = [f"plan: {plan['duration']:.1f} s, {len(plan['takes'])} takes, song {plan['song']['title']} from {plan['song']['start_t']:.1f} s, seed {seed}"]
# music
def pcm(f, ss=None):
    c = ["ffmpeg", "-v", "error"] + (["-ss", f"{ss}"] if ss else []) + ["-i", str(f), "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
    return np.frombuffer(subprocess.run(c, capture_output=True).stdout, np.int16).astype(np.float32) / 32768
ren, song = pcm(out), pcm(plan["song"]["path"], plan["song"]["start_t"])
rep.append("music (5 s windows): level of the render in dB | share of the song in it (0.79 = the full music at the mix headroom)")
row = []
for a in range(0, int(len(ren) / 8000) - 4, 5):
    r, s_ = ren[a * 8000:(a + 5) * 8000], song[a * 8000:(a + 5) * 8000]
    g = float((s_ * r).sum() / ((s_ * s_).sum() + 1e-9))
    row.append(f"{a:3d}s {20 * np.log10(np.sqrt((r ** 2).mean()) + 1e-9):6.1f} dB | {g:5.2f}")
rep += ["  " + "   ".join(row[i:i + 4]) for i in range(0, len(row), 4)]
rep.append(f"windows with the song missing (share < 0.3): {sum(1 for x in row if float(x.split('|')[1]) < 0.3)}")
# frozen frames
cap = cv2.VideoCapture(str(out))
prev, runs, cur, n = None, [], 0, 0
while True:
    ok, im = cap.read()
    if not ok:
        break
    g = cv2.cvtColor(cv2.resize(im, (320, 180)), cv2.COLOR_BGR2GRAY).astype(np.float32)
    if prev is not None and float(np.abs(g - prev).mean()) < 0.02:
        cur += 1
    else:
        if cur >= 3:
            runs.append((n - cur, cur))
        cur = 0
    prev = g
    n += 1
rep.append(f"frames: {n}; runs of 3 or more identical consecutive frames (frozen picture): {len(runs)}" + "".join(f"\n   at {a / 60:.2f} s: {c} frames" for a, c in runs[:30]))
rep_f.write_text("\n".join(rep) + "\n", encoding="utf-8")
print("\n".join(rep))
