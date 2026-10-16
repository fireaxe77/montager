"""V8.6 tool: the CS2 speed ramp on real takes. Plans a short CS2 montage from the given clips (manual, one fixed length), renders it, and writes for the headline / ending takes:
a per-frame speed graph (output frame -> source speed, the kill and the knife marked), a frame strip around the kill (every 0.1 s of OUTPUT time) and a duplicate / frozen frame count of the rendered take.
python tests/ramp86.py <out dir> <clip fragment> [<clip fragment> ...]   (fragments of CS2 clip file names, e.g. "25.12.30 - 23.21.57.21")"""
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
import cv2                                                                                    # noqa: E402
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
cfg = M.load_config()
recs = {r["path"]: r for r in M.scan_clips(cfg) if r.get("game") == "cs2"}
paths = [p for p in recs if any(w in p for w in sys.argv[2:])]
plan, _ = M.make_plan(cfg, "cs2", paths, None, 40, None, 5)
vid = out / "cs2_ramp_full.mp4"
M.render_plan(plan, str(vid), cfg, maxq=False, preview=False, encoder=None, effects=True)
rep = []
cap = cv2.VideoCapture(str(vid))
for ti, t in enumerate(plan["takes"]):
    cr = t.get("cs2ramp")
    if not cr:
        continue
    nf = t["nf"]
    sp = []
    for sg in t["segs"]:
        a, b, v, n = sg[:4]
        sp += [(b - a) * M.OUT_FPS / n if v else 0.0] * int(n)
    kills = t["kills_out"]
    k_f = int(round(kills[-1] * M.OUT_FPS))
    img = np.full((300, 900, 3), 255, np.uint8)
    xs = lambda i: 40 + int(i / max(1, nf - 1) * 840)
    ys = lambda v: 270 - int(min(1.2, v) / 1.2 * 240)
    for i in range(1, nf):
        cv2.line(img, (xs(i - 1), ys(sp[i - 1])), (xs(i), ys(sp[i])), (200, 40, 40), 2)
    cv2.line(img, (xs(k_f), 20), (xs(k_f), 280), (0, 0, 0), 1)
    cv2.putText(img, "kill", (xs(k_f) + 3, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    cv2.line(img, (40, ys(1.0)), (880, ys(1.0)), (150, 150, 150), 1)
    cv2.putText(img, f"{t['role']} take {ti + 1}: {cr.get('why', '')}", (40, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
    cv2.putText(img, "speed 1.0x", (4, ys(1.0) - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (90, 90, 90), 1)
    cv2.imwrite(str(out / f"ramp_take{ti + 1}_speed.png"), img)
    f0 = int(round(t["out_start"] * M.OUT_FPS))
    ims, prev, dups, jumps = [], None, 0, 0
    for i in range(max(0, k_f - 12), min(nf, k_f + 130)):
        cap.set(1, f0 + i)
        ok, im = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(cv2.resize(im, (320, 180)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None:
            d = float(np.abs(g - prev).mean())
            dups += d < 0.02
        prev = g
        if (i - (k_f - 12)) % 6 == 0:
            c = cv2.resize(im, (320, 180))
            cv2.putText(c, f"+{(i - k_f) / 60:.2f}s v={sp[i]:.2f}", (4, 174), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            ims.append(c)
    while len(ims) % 6:
        ims.append(np.zeros_like(ims[0]))
    cv2.imwrite(str(out / f"ramp_take{ti + 1}_strip.jpg"), np.concatenate([np.concatenate(ims[i:i + 6], 1) for i in range(0, len(ims), 6)], 0))
    rep.append(f"take {ti + 1} ({t['role']}): {cr}; rendered frames from the kill to +2 s: {dups} frozen / duplicated (identical to the previous frame); speeds min {min(sp[k_f:]):.2f} max {max(sp[k_f:]):.2f}")
(out / "ramp_report.txt").write_text("\n".join(rep) + "\n", encoding="utf-8")
print("\n".join(rep))
