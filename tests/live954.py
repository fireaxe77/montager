r"""V9.5.4 check with the real song "Another Day - Senua, SYNDRA, Flerian": (1) search only, the scoring and the best 3 candidates (nothing is downloaded); (2) with --download N: ONE real download of
candidate N (1-3) through the same function the "Download this" button uses, into a TEMPORARY songs folder; file name, tags, cover and the app's matching are checked and the file is deleted.
python tests/live954.py [--download N]      (MONTAGER_DATA = a folder with a copy of config.json)"""
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
import montage as m                                                                           # noqa: E402
import ytsongs as y                                                                           # noqa: E402

pick = int(sys.argv[sys.argv.index("--download") + 1]) if "--download" in sys.argv else 0
cfg = m.load_config()
csvp, rows, _ = m.read_playlist(cfg)
meta = y.read_meta(csvp)
row = next(r for r in rows if r["title"].lower().startswith("another day") and "senua" in r["artist"].lower())
tg = y.track_tags(row, meta)
print(f"CSV row: {row['title']} | {row['artist']} | {y.fmt_len(row['dur'])} | label {tg['label']} | isrc {tg['isrc']}")
data = os.environ["MONTAGER_DATA"]
cands = y.find_candidates(data, row["title"], row["artist"])
ranked, rej = y.rank(cands, row["title"], [x.strip() for x in row["artist"].split(",")], row["dur"], tg["label"])
for i, c in enumerate(ranked[:3], 1):
    print(f"  {i}. {y.describe(c)} | {'UNCERTAIN' if c['uncertain'] else 'confident'}")
print("  the best is", "UNCERTAIN: not downloaded by the batch" if ranked and ranked[0]["uncertain"] else "confident")
if pick:
    c = ranked[pick - 1]
    td = Path(tempfile.mkdtemp(prefix="live954_"))
    songs = td / "songs"
    songs.mkdir()
    try:
        got = y.download_chosen(row, c["id"], songs, data, meta, old=None, topic=c.get("kind") == "topic")
        f = Path(got["file"])
        print("\ndownloaded:", f.name, f.stat().st_size // 1024, "KB | cover source:", got["cover"])
        from mutagen.id3 import ID3
        from mutagen.mp3 import MP3
        t = ID3(str(f))
        print("expected name:", y.song_filename(row["title"], row["artist"]), "| same:", f.name == y.song_filename(row["title"], row["artist"]))
        print("tags:", {k: str(t[k]) for k in ("TIT2", "TPE1", "TALB", "TCON", "TPUB", "TSRC") if k in t}, "year", str(t.get("TDRC") or t.get("TYER")))
        print("cover:", [(x.type, y.image_size(x.data)) for x in t.getall("APIC")], "| audio:", MP3(str(f)).info.bitrate_mode, MP3(str(f)).info.bitrate // 1000, "kbps")
        audio = m.scan_audio(dict(cfg, mp3_dir=str(songs)), rescan=True)
        mt, un = m.match_playlist(rows, audio, cfg, loose=False)
        print("the app's matching counts it:", [(r["title"], sc) for r, a, sc in mt])
        try:
            y.download_chosen(row, c["id"], songs, data, meta, old=None, topic=False)
        except y.PlaceError as ex:
            print("a second download of the same song is refused (never overwrites):", ex)
    finally:
        shutil.rmtree(td, ignore_errors=True)
        print("temporary folder deleted:", not td.exists())
