"""V7.7.6 helper: ONE real render in its own process on a COPY of montage_data, with the montage.py of a git ref ('new' = the working tree).
   python tests\render776.py <new|V7.7.5> <out dir> <cs2|valorant> [clip path ...]   -> prints the log lines of the sync report (no clip paths = Auto weekly + force, seed 776)"""
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
import montage as M                                                                           # noqa: E402
from songmap_v2 import planbench as PB                                                        # noqa: E402

which, out_dir, game, paths = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
with PB.data_copy(M):
    X = M
    if which != "new":
        src = subprocess.run(["git", "show", f"{which}:montage.py"], cwd=ROOT, capture_output=True).stdout
        d = Path(tempfile.mkdtemp(prefix="r776_"))
        (d / "montage.py").write_bytes(src)
        spec = importlib.util.spec_from_file_location("montage_ref", str(d / "montage.py"))
        X = importlib.util.module_from_spec(spec)
        sys.modules["montage_ref"] = X
        spec.loader.exec_module(X)
    cfg = X.load_config()
    cfg.update(output_root=out_dir, sync_report=True)
    X.save_json(X.CONFIG_PATH, cfg)
    lines = []
    X.out = lambda *a: lines.append(" ".join(map(str, a)))
    if paths:
        X.run_job(game, "render", force=True, paths=paths, seed=776)
    else:
        X.run_job(game, "render", weekly=True, force=True, seed=776)
    for l in lines:
        if l.startswith(("  take", "SYNC", "TRANSITION", "rendered", "KILL WINDOW", "late read", "CUT LIST", "cuts:")) or "late read" in l or "KILL WINDOW" in l:
            print(l[:260])
