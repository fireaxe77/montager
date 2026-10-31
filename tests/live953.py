r"""V9.5.3 real-data check on a COPY of montage_data and TEMPORARY COPIES of 20 real songs (the real library and the real montage_data are only read):
the migration, then the tags + covers of the 20 copies are rewritten (sizes and first bytes change) and every song must still find its song map (no rebuild) and its hand labels.
python tests/live953.py <montage_data copy>      (the copy is changed: make it with cp -r montage_data <copy>)"""
import io
import json
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
D = Path(sys.argv[1])
os.environ["MONTAGER_DATA"] = str(D)
import montage as M                                                                           # noqa: E402
import songid                                                                                 # noqa: E402
import ytsongs as y                                                                           # noqa: E402
import songmap_v2.build as B                                                                  # noqa: E402
from PIL import Image                                                                         # noqa: E402

cfg = M.load_config()
real_audio = M.scan_audio(cfg)                                    # the real songs folder, read only
files = [{"path": a["path"], "dur": float(a.get("dur") or 0), "mtime": int(os.stat(a["path"]).st_mtime), "size": os.stat(a["path"]).st_size} for a in real_audio]
v2 = json.load(open(D / "song_cache_v2.json", encoding="utf-8"))
sigs = {}
for k, v in v2.items():
    sp = songid.split_v2_key(k)
    if sp and isinstance(v, dict):
        sigs.setdefault(sp[1], float(v.get("dur") or 0))
ok, bad = songid.tie_orphans(sigs, files)
hand = json.load(open(D / "song_drops.json", encoding="utf-8"))
tied_by_path = {}
for sig, f in ok.items():
    tied_by_path.setdefault(f["path"], []).append(sig)
hand_paths = [f["path"] for f in files if Path(f["path"]).name in hand and f["path"] in tied_by_path]
others = [p for p in tied_by_path if p not in hand_paths]
pick = hand_paths[:10] + others[:20 - len(hand_paths[:10])]
print(f"real folder: {len(files)} songs; V2 map signatures {len(sigs)}, tied to a file {len(ok)}; hand-labelled songs {len(hand)} (with a file AND a map: {len(hand_paths)})")
td = Path(tempfile.mkdtemp(prefix="live953_"))
songs = td / "songs"
songs.mkdir()
for p in pick:
    shutil.copy2(p, songs / Path(p).name)                           # (the modified time is copied, as a tag writer keeps it)
cfg = dict(cfg, mp3_dir=str(songs))
M.save_json(M.CONFIG_PATH, cfg)
before_entries = {}
for p in pick:
    for sig in tied_by_path[p]:
        for k, v in v2.items():
            sp = songid.split_v2_key(k)
            if sp and sp[1] == sig:
                before_entries[(Path(p).name, k)] = json.dumps(v, sort_keys=True)
print(f"temporary copies: {len(pick)} songs ({len([p for p in pick if p in hand_paths])} hand-labelled), {len(before_entries)} V2 entries belong to them")
hand_bytes = (D / "song_drops.json").read_bytes()
txt = M.songdata_migrate(M.load_config(), force=True)
print("\n--- migration report (only the 20 copies are in the songs folder, so entries of other songs count as 'no file') ---")
print(txt)
ids_before = {p: songid.audio_id(songs / Path(p).name, D) for p in pick}
sizes_before = {p: (songs / Path(p).name).stat().st_size for p in pick}
for p in pick:
    f = songs / Path(p).name
    st = os.stat(f)
    buf = io.BytesIO()
    Image.new("RGB", (800, 800), (7, 90, 160)).save(buf, "JPEG")
    y.apply_tags(f, {"title": "rewritten", "artist": "x", "album": "Rewritten Album", "year": "2031", "genre": "g", "label": "l", "isrc": "ZZ0000000001"}, buf.getvalue(), fresh=True)
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
changed = sum(1 for p in pick if (songs / Path(p).name).stat().st_size != sizes_before[p])
same_id = sum(1 for p in pick if songid.audio_id(songs / Path(p).name, D) == ids_before[p])
print(f"after rewriting tags + covers: {changed} of {len(pick)} files changed size; identity unchanged for {same_id}")
calls = []
B.build_songmap_v2 = lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(RuntimeError("REBUILD"))
new = json.load(open(D / "song_cache_v2.json", encoding="utf-8"))
M.songid_install()
found = missing = equal = 0
lost = []
for (nm, k), val in before_entries.items():
    sp = songid.split_v2_key(k)
    f = songs / nm
    nk = f"{sp[0]}{songid.audio_id(f, D)}|{sp[2]}"
    if nk in new:
        found += 1
        equal += json.dumps(new[nk], sort_keys=True) == val
    else:
        missing += 1
        lost.append((nm, k))
print(f"V2 entries of the copies found under the new identity: {found}; missing: {missing}; content identical to before: {equal}; rebuild calls: {len(calls)}")
names_h = [Path(p).name for p in pick if Path(p).name in hand]
lab_ok = sum(1 for n in names_h if M.song_drop_labels(str(songs / n)) == sorted(hand[n].get("drops") or []))
sb_n = sum(1 for n in names_h if hand[n].get("strong_beats"))
sb_ok = sum(1 for n in names_h if hand[n].get("strong_beats") and M.song_strong_beats(str(songs / n)) == sorted(hand[n]["strong_beats"]))
print(f"hand-labelled copies: {len(names_h)}; drop labels found: {lab_ok}; strong beats found: {sb_ok} of {sb_n}; song_drops.json byte-identical: {(D / 'song_drops.json').read_bytes() == hand_bytes}")
a = songs / Path(pick[0]).name
if names_h:
    n0 = names_h[0]
    g = songs / ("renamed " + n0)
    (songs / n0).rename(g)
    print("a hand-labelled copy RENAMED still has its labels:", M.song_drop_labels(str(g)) == sorted(hand[n0]["drops"]))
    a = g
b = songs / "twin.mp3"
shutil.copy2(a, b)
y.apply_tags(b, {"title": "other", "album": "other album"}, None, fresh=True)
print("two files with identical audio but different tags / cover share one identity:", songid.audio_id(a, D) == songid.audio_id(b, D), "| sizes", a.stat().st_size, b.stat().st_size)
if lost:
    print("NOT FOUND:", lost[:5])
shutil.rmtree(td, ignore_errors=True)
print("temporary copies deleted:", not td.exists())
