"""Writes tests/data/drop_labels_refined.json from drop_labels.json using drop_refine (run on a data copy: MONTAGER_DATA)."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
import montage as M, v74_common as C, drop_refine as DR
ANCHOR = {("Beautiful Now", 56.8): 56.8, ("pretty afternoon", 34.0): 34.6}
HARD = {("Rave Dream", 30.0), ("All The Things She Said", 39.0), ("pretty afternoon", 92.0), ("Les", 93.0)}
HELD = ["Ouch", "Tattoo", "Self Aware", "If I Lose Myself"]
cfg = M.load_config()
tol, lab = C.load_labels()
songs, missing = C.find_songs(M, cfg, list(lab))
out = {"held_out_songs": HELD, "songs": {}}
for f, tl in lab.items():
    if f not in songs: continue
    y, sr = M.decode_mono(songs[f]["path"], 22050)
    env = DR.low_env(y, sr)
    rows = []
    for t in tl:
        t = float(t["t"] if isinstance(t, dict) else t)
        key = (f, t)
        if key in ANCHOR:
            rows.append({"typed": t, "t": ANCHOR[key], "shift": round(ANCHOR[key] - t, 2), "status": "anchor", "tol": 0.25, "hard": False}); continue
        r, step = DR.refine(env, t)
        hard = key in HARD
        if r is None:
            rows.append({"typed": t, "t": t, "shift": 0.0, "status": "unrefined", "tol": 1.0, "step_db": step, "hard": hard})
        else:
            rows.append({"typed": t, "t": r, "shift": round(r - t, 2), "status": "refined", "tol": 0.3, "step_db": step, "hard": hard})
    out["songs"][f] = rows
    print(f, [(x["typed"], x["t"], x["status"]) for x in rows])
json.dump(out, open(HERE / "data" / "drop_labels_refined.json", "w"), indent=1)
