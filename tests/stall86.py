"""V8.6 tool: which clips of the library freeze (picture standing still in gaps >= STALL_GAP_S for more than STALL_MAX_SHARE of the clip)?  python tests/stall86.py [game] -> list + docs/proof_v86/stall_report.txt"""
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

game = sys.argv[1] if len(sys.argv) > 1 else None
cfg = M.load_config()
rows, n = [], 0
for r in M.scan_clips(cfg):
    if r.get("error") or not r.get("w") or (game and r.get("game") != game) or not r.get("fps") or float(r["fps"]) >= M.STALL_CHECK_FPS:
        continue
    n += 1
    sh = M.clip_stall_share(r["path"])
    if sh is not None and sh > M.STALL_MAX_SHARE:
        rows.append((sh, r["game"], Path(r["path"]).name, r["fps"]))
rows.sort(reverse=True)
txt = f"{n} clips under {M.STALL_CHECK_FPS:.0f} fps measured, {len(rows)} frozen for more than {M.STALL_MAX_SHARE * 100:.0f}% of their length (left out of the pools):\n" + "\n".join(f"  {s * 100:4.0f}%  {g:9s} {nm}  ({f} fps avg)" for s, g, nm, f in rows)
print(txt)
(ROOT / "docs" / "proof_v86" / "stall_report.txt").write_text(txt + "\n", encoding="utf-8")
