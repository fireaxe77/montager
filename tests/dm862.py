"""V8.6.2 tool: the CS2 deathmatch detector over the WHOLE cached CS2 library, with the lists the brief asks for.
python tests/dm862.py <out dir>   -> <out>/dm_candidates.txt (every flagged clip with its signals), dm_candidates.jpg (contact sheet of the flagged clips), and in the same txt a sample of 30 NOT flagged clips with their signal values.
Measured once per clip (OCR of the HUD, cached in montage_data/dm_cache.json): a1 = the chat log says '... points for neutralizing an enemy' (competitive: '+$300 for ...'), a2 = the BONUS WEAPON panel, b = the top bar
with a single timer and a row of points under the player icons. A clip is flagged when at least 2 of the 3 agree."""
import random
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
import numpy as np                                                                            # noqa: E402
import cv2                                                                                    # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
cfg = M.load_config()
recs = [r for r in M.scan_clips(cfg) if r.get("game") == "cs2" and not r.get("error") and r.get("w")]
t0 = time.time()
M.cs2_dm_rejected(cfg, recs, progress=lambda f, m: print(f"{f * 100:3.0f}%  {m}", flush=True))
cache = M.load_json(M.DM_CACHE, {})
rows = [(r, cache.get(M.file_key(r["path"]))) for r in recs]
rows = [(r, d) for r, d in rows if d]
flag = [(r, d) for r, d in rows if d["dm"]]
one = [(r, d) for r, d in rows if not d["dm"] and d["signals"] == 1]
rest = [(r, d) for r, d in rows if d["signals"] == 0]
random.seed(7)
smp = random.sample(rest, min(30, len(rest)))
lines = [f"{len(recs)} CS2 clips, {len(rows)} measured in {time.time() - t0:.0f} s; FLAGGED (>= 2 signals): {len(flag)} = {100.0 * len(flag) / max(1, len(rows)):.1f} %; one signal only (never rejected): {len(one)}; no signal: {len(rest)}", "", "FLAGGED:"]
for r, d in flag:
    lines.append(f"  {Path(r['path']).name}: a1 log {d['a1']}, a2 bonus weapon {d['a2']}, b top bar {d['b']} -> {d['signals']} signals; read: {' / '.join(d['texts'])[:150]}")
lines += ["", "ONE SIGNAL ONLY (kept in the pool, listed so the rule can be checked):"]
for r, d in one:
    lines.append(f"  {Path(r['path']).name}: a1 {d['a1']}, a2 {d['a2']}, b {d['b']}; read: {' / '.join(d['texts'])[:120]}")
lines += ["", "30 CLIPS NOT FLAGGED (signal values):"]
for r, d in smp:
    lines.append(f"  {Path(r['path']).name}: a1 {d['a1']}, a2 {d['a2']}, b {d['b']} -> {d['signals']} signals")
(out / "dm_candidates.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", errors="replace")
tiles = []
for r, d in flag:
    o = subprocess.run(["ffmpeg", "-v", "error", "-ss", "2.0", "-i", r["path"], "-frames:v", "1", "-vf", "scale=480:270", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], capture_output=True).stdout
    if len(o) == 480 * 270 * 3:
        im = np.frombuffer(o, np.uint8).reshape(270, 480, 3).copy()
        cv2.putText(im, Path(r["path"]).name[18:50], (4, 262), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        tiles.append(im)
if tiles:
    while len(tiles) % 4:
        tiles.append(np.zeros_like(tiles[0]))
    cv2.imwrite(str(out / "dm_candidates.jpg"), np.concatenate([np.concatenate(tiles[i:i + 4], 1) for i in range(0, len(tiles), 4)], 0), [cv2.IMWRITE_JPEG_QUALITY, 85])
print("\n".join(lines[:3]))
