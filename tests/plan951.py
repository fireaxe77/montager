r"""V9.5.1 timing tool: ONE plan built like the GUI job (Force New Full) with the job's STAGES line, optionally under cProfile. Run on a COPY of montage_data (MONTAGER_DATA).
python tests/plan951.py <game> <seed> [--unuse <montage title>] [--profile] [--song <fragment>] [--out plan.json]"""
import argparse
import cProfile
import io
import json
import pstats
import sys
import time
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import montage as M                                                                           # noqa: E402
import plan845                                                                                # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("game")
ap.add_argument("seed", type=int)
ap.add_argument("--unuse")
ap.add_argument("--profile", action="store_true")
ap.add_argument("--song")
ap.add_argument("--out")
a = ap.parse_args()
if a.unuse:
    print("unused again:", plan845.unuse(a.unuse))
cfg = M.load_config()
M.JOB_STAGES.clear()
pr = cProfile.Profile() if a.profile else None
t0 = time.time()
if pr:
    pr.enable()
sp = None
if a.song:
    songs, _, _ = M.song_pool(cfg, cached_only=True)
    sp = [s for s in songs if a.song.lower() in (s["title"] + " " + s["artist"]).lower()][0]["path"]
plan, text = M.make_plan(cfg, a.game, None, sp, None, None, a.seed, None, None, full=True)
if pr:
    pr.disable()
el = time.time() - t0
print(f"plan: {el:.1f} s")
print(M.job_stages_line())
stage_sum = sum(v for k, v in M.JOB_STAGES.items() if k in ("scan", "selection", "pairing", "planning", "repair loop", "song map", "frame checks", "effects"))
print(f"timed stages add up to {stage_sum:.1f} s of {el:.1f} s")
if pr:
    pr.dump_stats(str(HERE.parent / "plan951.prof")) if a.out else None
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("cumulative").print_stats(45)
    print(s.getvalue()[:9000])
if a.out:
    json.dump(plan, open(a.out, "w", encoding="utf-8"), default=str)
