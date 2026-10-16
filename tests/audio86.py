"""V8.6 tool: the music-dip expression of the drop moments (drop_audio_filters) applied to a steady tone over a 150 s montage with drops at 37.7 s and 128.1 s: level per 5 s window, the V8.5.1 expression
(exp() of a large positive number -> inf, 0 * inf = NaN: silence) next to the fixed one.   python tests/audio86.py [out.txt]"""
import re
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
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

dm = lambda t: {"t": t, "s": 1.45, "variant": "punch", "dip_s": 0.22, "dip_db": 8, "boom_f1": 52, "boom_f0": 130, "boom_r": 26, "boom_dec": 6.5, "boom_db": -2, "lift_db": 4, "duck_db": 5, "breath": 0.4}
dip = M.drop_audio_filters([dm(37.7343), dm(128.1209)])[0]
old = re.sub(r"max\(0,(t-[0-9.]+)\)", r"(\1)", dip)


def levels(expr):
    cmd = ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:r=48000:d=150", "-af", f"volume='{expr}':eval=frame", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
    a = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.int16).astype(np.float32) / 32768
    return [20 * np.log10(np.sqrt((a[i:i + 40000] ** 2).mean()) + 1e-9) for i in range(0, len(a) - 39999, 40000)]


lo, ln = levels(old), levels(dip)
rows = ["window   V8.5.1 expression   fixed expression   (a steady tone; its own level when nothing touches it)"]
for i, (a, b) in enumerate(zip(lo, ln)):
    rows.append(f"{i * 5:3d}-{i * 5 + 5:3d} s   {a:8.1f} dB        {b:8.1f} dB" + ("   <- silent" if a < -60 else ""))
base = float(np.median(ln))
rows.append(f"silent windows (below -60 dB): V8.5.1 {sum(1 for v in lo if v < -60)}, fixed {sum(1 for v in ln if v < -60)}; windows below the steady level ({base:.1f} dB) by more than 0.1 dB, fixed: "
            + ", ".join(f"{i * 5}-{i * 5 + 5} s" for i, v in enumerate(ln) if v < base - 0.1) + " (the two drops only)")
txt = "\n".join(rows)
print(txt)
if len(sys.argv) > 1:
    Path(sys.argv[1]).write_text(txt + "\n", encoding="utf-8")
