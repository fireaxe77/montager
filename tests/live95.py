r"""V9.5 live check of the whole chain (needs network, yt-dlp, ffmpeg): a temp data folder + CSV + songs folder, then the REAL
App.download_new_songs (stub self) -> search, download, MP3, tags, and the app's own scan / match lists the song. Downloads N tracks.
python tests/live95.py [N]"""
import json
import os
import queue
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _root import find_root
ROOT = find_root(__file__)
sys.path.insert(0, str(ROOT))

TRACKS = [("Angels Fall", "Flerian", 91, "2026-05-02"), ("bpd gf", "EXODIA, AGONY, Silencee", 166, "2026-05-01"),
          ("Hey Mama", "Kanye West", 305, "2020-01-01")]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    td = Path(tempfile.mkdtemp(prefix="live95_"))
    data, songs, pl = td / "data", td / "songs", td / "pl"
    for d in (data, songs, pl):
        d.mkdir()
    os.environ["MONTAGER_DATA"] = str(data)
    (data / "config.json").write_text(json.dumps({"mp3_dir": str(songs), "playlist_dir": str(pl), "output_root": str(td / "out")}), encoding="utf-8")
    with open(pl / "p.csv", "w", encoding="utf-8-sig", newline="") as f:
        f.write("Track URI,Track Name,Artist Name(s),Added At,Duration (ms)\n")
        for i, (t, a, d, ad) in enumerate(TRACKS):
            f.write(f'spotify:track:{i},"{t}","{a.replace(", ", ";")}",{ad}T00:00:00Z,{d * 1000}\n')
    import montage as m

    class Stub:
        q = queue.Queue()
        tasks = []
        load_matches = None
        run_task = lambda self, name, fn, *a: self.tasks.append(name)
        _prog_ui = lambda self, f, t: print("STATUS:", t)
        show_yt_report = lambda self, title, text: print("=== REPORT:", title, "\n" + text)
    st = Stub()
    m.App.download_new_songs(st, n)
    while not st.q.empty():
        k, fn = st.q.get()
        fn()
    print("files:", [p.name for p in songs.iterdir()], "| refresh requested:", st.tasks)
    audio = m.scan_audio(m.load_config(), rescan=True)
    csvp, rows, _ = m.read_playlist(m.load_config())
    matched, unmatched = m.match_playlist(rows, audio, m.load_config())
    print("matched by the app:", [(r["title"], sc) for r, a, sc in matched])
    from mutagen.id3 import ID3
    from mutagen.mp3 import MP3
    for a in audio:
        t = ID3(a["path"])
        info = MP3(a["path"]).info
        print("tags:", str(t["TIT2"]), "|", str(t["TPE1"]), "| bitrate_mode", info.bitrate_mode, "| ~kbps", info.bitrate // 1000, "| length", round(info.length, 1))
    print("data folder:", td)


if __name__ == "__main__":
    main()
