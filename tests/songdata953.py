r"""V9.5.3 diagnosis (READ-ONLY): the song data of a montage_data COPY against the songs folder as it is now.
python tests/songdata953.py <data copy> [--before <older copy of montage_data>] [--since "2026-10-31 08:01"]"""
import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
ap = argparse.ArgumentParser()
ap.add_argument("data")
ap.add_argument("--before")
ap.add_argument("--since", default="2026-10-31 08:01")
a = ap.parse_args()
D = Path(a.data)
os.environ["MONTAGER_DATA"] = str(D)
import montage as M                                                                           # noqa: E402
import songmap_v2.build as B                                                                  # noqa: E402
if os.environ.get("SONGID_DIAG") == "1":
    M.songid_install()

cfg = M.load_config()
audio = M.scan_audio(cfg, rescan=False)
print(f"songs folder: {len(audio)} audio files")


def load(name, base=D):
    try:
        return json.load(open(Path(base) / name, encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---- 1. where song data lives
print("\n== files that hold song data (copy) ==")
for f in ("song_cache_v2.json", "song_cache.json", "repeat_cache.json", "song_drops.json", "match_cache.json", "audio_cache.json", "used_songs.json", "loud_cache.json", "refine_cache.json", "onsets_cache.json"):
    p = D / f
    if p.exists():
        d = load(f)
        print(f"  {f}: {len(d) if hasattr(d, '__len__') else '?'} entries, modified {datetime.datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d %H:%M}")

# ---- 2. the V2 song-map cache: which entries still belong to a file as it is now
sigs = {}
for r in audio:
    try:
        sigs[B.file_signature(r["path"])] = r
    except OSError:
        pass
v2 = load("song_cache_v2.json") or {}
parts = {}
for k, v in v2.items():
    m = re.match(r"songmap_v2\|[^|]+\|([^|]+)\|", k)
    if m:
        parts.setdefault(m.group(1), []).append((k, v))
cur = {s for s in parts if s in sigs}
orph = {s for s in parts if s not in sigs}
print(f"\n== V2 song maps: {len(v2)} cache entries for {len(parts)} different file signatures ==")
print(f"  signature still equal to a file now: {len(cur)} | orphaned (no file has this size / start / end any more): {len(orph)}")
by_mt = {}
for r in audio:
    try:
        by_mt.setdefault(int(os.stat(r["path"]).st_mtime), []).append(r)
    except OSError:
        pass
mapped, ambiguous, none = 0, 0, 0
mp_files = {}
for s in orph:
    size, mt, _h = s.split("-", 2)
    ent = next((v for k, v in parts[s] if isinstance(v, dict) and v.get("dur")), None)
    cand = by_mt.get(int(mt), [])
    if ent:
        cand = [r for r in cand if abs(float(r.get("dur") or 0) - float(ent["dur"])) < 1.0]
    if len(cand) == 1:
        mapped += 1
        mp_files[s] = cand[0]["path"]
    elif len(cand) > 1:
        ambiguous += 1
    else:
        none += 1
print(f"  orphans that can be tied to ONE current file by modified time + duration: {mapped} | ambiguous: {ambiguous} | no file: {none}")
files_with_map = {r["path"] for s, r in sigs.items() if s in cur}
print(f"  files with a V2 map under their current signature: {len(files_with_map)}; files that would be re-analysed when picked: {len(audio) - len(files_with_map) - mapped}"
      f" (+{mapped} if the orphan maps are re-keyed)")

# ---- 3. hand-labelled drops / strong beats
dr = load("song_drops.json") or {}
names = {Path(r["path"]).name for r in audio}
print(f"\n== hand labels (song_drops.json, keyed by FILE NAME): {len(dr)} songs ==")
print(f"  with drops: {sum(1 for v in dr.values() if v.get('drops'))}, with strong beats: {sum(1 for v in dr.values() if v.get('strong_beats'))}")
print(f"  file name still in the songs folder: {sum(1 for n in dr if n in names)}; no file of that name: {[n for n in dr if n not in names]}")
rf = _root.find_root() / "tests" / "data"
for f in ("drop_labels.json", "drop_labels_refined.json", "drops_v745.json", "drop_baseline_v73.json"):
    p = rf / f
    if p.exists():
        print(f"  tests/data/{f}: reference data in the repo (not read by the app's plans)")

# ---- 4. V1 maps, repeat drops
v1 = load("song_cache.json") or {}
cur_paths = {r["path"] for r in audio}
v1_now = sum(1 for k in v1 if k.split("|")[0] in cur_paths)
print(f"\n== V1 song maps: {len(v1)} entries; their file path exists in the songs folder: {v1_now} (the rest point at the old folder C:\\...\\Songs) ==")
rp = load("repeat_cache.json") or {}
rcur = sum(1 for k in rp if k.split("|")[1] in sigs)
print(f"== repeat drops: {len(rp)} entries, {rcur} still match a file signature ==")
mc = load("match_cache.json") or {}
print(f"== match cache: folder signature {mc.get('folder')} ==")

# ---- 5. modified after the Apply / compared with an older copy
since = datetime.datetime.strptime(a.since, "%Y-%m-%d %H:%M").timestamp()
print(f"\n== files of the copy modified after {a.since} ==")
for p in sorted(D.glob("*.json")):
    if p.stat().st_mtime >= since and re.search(r"song|repeat|drop|match|audio|beat", p.name):
        print("  ", p.name, datetime.datetime.fromtimestamp(p.stat().st_mtime).strftime("%H:%M"))
if a.before:
    Bf = Path(a.before)
    print(f"\n== compared with the older copy {Bf} ==")
    b2 = load("song_cache_v2.json", Bf) or {}
    gone = [k for k in b2 if k not in v2]
    changed = [k for k in b2 if k in v2 and json.dumps(b2[k], sort_keys=True) != json.dumps(v2[k], sort_keys=True)]
    print(f"  V2 maps: {len(b2)} then, {len(v2)} now; removed {len(gone)}; changed under the same key {len(changed)}; added {len(v2) - len(b2) + len(gone)}")
    bd = load("song_drops.json", Bf) or {}
    print(f"  hand labels: identical to the older copy: {bd == dr} ({len(bd)} then, {len(dr)} now)")
    for f in ("repeat_cache.json", "song_cache.json"):
        x, y = load(f, Bf) or {}, load(f) or {}
        print(f"  {f}: {len(x)} then, {len(y)} now, removed {len([k for k in x if k not in y])}, changed {len([k for k in x if k in y and x[k] != y[k]])}")
    # any hand-labelled song whose map changed?
    fn = {Path(r["path"]).name: r for r in audio}
    print("  entries added after the older copy that belong to hand-labelled songs: see the re-key list of the migration")
