r"""V9.5.1 helper: the same real song's map made one after the other vs prefetched, first differing keys. python tests/songmapdiff951.py <mp3> <mp3> <mp3>"""
import os
import shutil
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


def diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append(f"{path}/{k}: only in one")
            else:
                out += diff(a[k], b[k], f"{path}/{k}")
    elif isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
    elif a != b:
        try:
            import numpy as np
            if np.allclose(np.asarray(a, float), np.asarray(b, float), equal_nan=True):
                return out
        except Exception:                                  # noqa: BLE001
            pass
        out.append(f"{path}: {str(a)[:70]} != {str(b)[:70]}")
    return out


res = {}
for mode in ("seq", "pre"):
    d = Path(tempfile.mkdtemp(prefix=f"smd_{mode}_"))
    old = M.use_data_dir(d)
    try:
        songs = []
        for i, s_ in enumerate(sys.argv[1:4]):
            dst = d / f"song{i}.mp3"
            shutil.copy2(s_, dst)
            songs.append({"path": str(dst), "csv_bpm": None})
        M.SONGMAP_PRE.clear()
        M.SONGMAP_PREFETCH_WORKERS = 3 if mode == "pre" else 1
        M.songmap_prefetch(songs)
        res[mode] = [M.get_songmap(s_["path"], None) for s_ in songs]
    finally:
        M.restore_data_dir(old)
for i in range(len(res["seq"])):
    d_ = diff(res["seq"][i], res["pre"][i])
    print(i, len(d_), "differences", d_[:8])
