r"""V9.5.1 timing render: one saved plan rendered with render_plan, the job's STAGES line printed. Run on a COPY of montage_data (MONTAGER_DATA).
python tests/render951.py <plan.json> <out.mp4> [label]      (env MONTAGER_KEEP_TMP=1 keeps the temp folder with the parts)"""
import json
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

planp, outp = Path(sys.argv[1]), Path(sys.argv[2])
plan = json.load(open(planp, encoding="utf-8"))
SKY_KEYS = ("ok", "mask", "grade", "cov", "anim", "beats", "fam", "pattern", "mask_fmt", "frames_src", "horizon", "sky_cut")
for t in plan["takes"]:
    for x in t.get("xfx") or []:
        if x.get("k") == "sky":
            for k in SKY_KEYS:
                x.pop(k, None)
M.JOB_STAGES.clear()
if __import__('os').environ.get('RENDER951_QUIET'):
    M.job_quiet(True)                                    # as in the app: below-normal priority, 2 cores free
t0 = time.time()
M.render_plan(plan, outp, M.load_config())
print(f"{sys.argv[3] if len(sys.argv) > 3 else 'render'}: {time.time() - t0:.1f} s")
print(M.job_stages_line())
