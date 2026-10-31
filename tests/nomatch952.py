r"""V9.5.2 diagnosis (READ-ONLY on the library): which songs matched before the Apply of covers and tags (montage_data\match_cache.json of 07:28, or --cache) and do not match now.
python tests/nomatch952.py [--cache <match_cache.json>] [--show 10]      (MONTAGER_DATA = a folder with a COPY of config.json: caches are written there)"""
import argparse
import json
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import montage as m                                                                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--cache", default=str(_root.find_root() / "montage_data" / "match_cache.json"))
ap.add_argument("--show", type=int, default=10)
a_ = ap.parse_args()
cfg = m.load_config()
csvp, rows, _ = m.read_playlist(cfg)
audio = m.scan_audio(cfg, rescan=True)
matched, unmatched = m.match_playlist(rows, audio, cfg)
now = {Path(a["path"]).name: (r, sc) for r, a, sc in matched}
old = json.load(open(a_.cache, encoding="utf-8"))
byrank = {}
for r in rows:
    byrank.setdefault(m._rank_key(r), r)
before = {}
for e in old["pairs"]:
    name = Path(e["a"].rsplit("|", 2)[0]).name
    before[name] = (byrank.get(e["r"]), e["s"])
print(f"files {len(audio)}; matched now {len(matched)}; matched before (cache) {len(before)}")
lost = [n for n in before if n not in now]
print(f"{len(lost)} songs matched before and do not now")
by_name = {Path(a["path"]).name: a for a in audio}
for n in lost[:a_.show]:
    a = by_name.get(n)
    r = before[n][0]
    tags = m.read_tags(a["path"]) if a else None
    print("-", n)
    print("    tags now (artist | title):", (tags[0], tags[1]) if tags else None)
    print("    matcher from the file name :", m.parse_song_file(a) if a else None)
    print("    cached CSV row             :", (r["title"], r["artist"]) if r else None, "score", before[n][1])
mt = {a["path"] for r, a, sc in matched}
left = [a for a in audio if a["path"] not in mt]
print(f"{len(left)} file(s) with no CSV match now:")
for a in left:
    print("  -", Path(a["path"]).name, "| file-name parse:", m.parse_song_file(a), "| tags:", m.read_tags(a["path"])[:2])
