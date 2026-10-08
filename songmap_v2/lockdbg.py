"""V7.1 debug: the tempo-lock candidate table of a song, with the CSV tempo and V1 BPM taken from the V1 cache (read-only)."""
import glob, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
from songmap_v2 import build_songmap_v2

c = json.load(open(HERE / "montage_data" / "song_cache.json", encoding="utf-8"))
for frag in sys.argv[1:]:
    k = next(k for k in c if frag.lower() in k.lower() and "|map2|" in k)
    csv = float(k.rsplit("|", 1)[1]) or None
    f = k.split("|")[0]
    v1 = c[k]["bpm"]
    m = build_songmap_v2(f, csv, v1_bpm=v1)
    print(frag, "csv", csv, "v1", v1, "-> V2", m["bpm"], "conf", m["v2"]["grid_confidence"], "tracked", m["v2"]["lock"].get("tracked"))
    for r in m["v2"]["lock"]["candidates"]:
        print("   ", r["bpm"], r["src"], "kf", r["kick_frac"], "hit", r["hit_frac"], "cov", r["coverage"], "score", r["score"])
