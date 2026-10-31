r"""V9.5.4 tests (fast, no network): hand picks of the YouTube downloader (candidate buttons, pasted links, never overwriting, _replaced). The picker is built on a WITHDRAWN window (nothing shows).
python tests/test_v954.py"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _root import find_root
ROOT = find_root(__file__)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="v954data_"))
import ytsongs as y

FAILS = []


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {info}" if info and not cond else ""))
    if not cond:
        FAILS.append(name)


def C(title, channel, dur, views=0, vid="x"):
    return {"id": vid, "title": title, "channel": channel, "duration": dur, "views": views, "verified": False}


def main():
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("0 APP_VERSION is V9.5.4", 'APP_VERSION = "V9.5.4"' in src)
    check("1 links: watch?v=, youtu.be, shorts, bare id; junk is refused", [y.parse_video_id(x) for x in ("https://www.youtube.com/watch?v=lyRUUshYqDM&t=3", "https://youtu.be/lyRUUshYqDM?si=a",
          "https://youtube.com/shorts/lyRUUshYqDM", "lyRUUshYqDM", "hello", "")] == ["lyRUUshYqDM"] * 4 + [None, None])
    # the scoring is unchanged: the same candidates, the same UNCERTAIN marks
    cands = [C("Another Day - Senua (feat. Flerian & SYNDRA)", "Daniel Hardman", 149, 60, "a"), C("senua, flerian & syndra - another day (frenchcore)", "vmp", 147, 7598, "b")]
    ranked, _ = y.rank(cands, "Another Day", ["Senua", "SYNDRA", "Flerian"], 146, "ASCENT653 RECORDS")
    check("2 scoring unchanged: both UNCERTAIN, the clean title first", [c["id"] for c in ranked] == ["a", "b"] and all(c["uncertain"] for c in ranked))
    td = Path(tempfile.mkdtemp(prefix="v954_"))
    songs, data = td / "songs", td / "data"
    songs.mkdir()
    data.mkdir()
    row = {"title": "Another Day", "artist": "Senua, SYNDRA", "dur": 146, "added": "2026-01-01", "uri": "u1"}
    meta = {"u1": {"isrc": "I1", "album": "AL", "year": "2025", "genre": "g", "label": "L"}}
    calls = []

    def dl(vid):
        calls.append(vid)
        p = td / f"{vid}.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={300 + 100 * len(calls)}:duration=1", "-y", str(p)], check=True)
        return p
    noc = lambda r, t: (None, "none", "")
    try:
        got = y.download_chosen(row, "vidAAAAAAAA", songs, data, meta, dl=dl, cover_fn=noc)
        from mutagen.id3 import ID3
        t = ID3(got["file"])
        check("3 the chosen video is downloaded with the file name and tags from the CSV", Path(got["file"]).name == y.song_filename("Another Day", "Senua, SYNDRA") and str(t["TALB"]) == "AL" and str(t["TSRC"]) == "I1")
        try:
            y.download_chosen(row, "vidBBBBBBBB", songs, data, meta, dl=dl, cover_fn=noc)
            check("3 an existing file is never overwritten", False)
        except y.PlaceError as ex:
            check("3 an existing file is never overwritten (error names it)", "already exists" in str(ex))
        old_bytes = Path(got["file"]).read_bytes()
        got2 = y.download_chosen(row, "vidBBBBBBBB", songs, data, meta, old=got["file"], dl=dl, cover_fn=noc)
        check("3 with the old file given it moves to _replaced (kept, byte-identical) and the new one takes its place",
              (songs / "_replaced" / Path(got["file"]).name).read_bytes() == old_bytes and got2["replaced"] and Path(got2["file"]).read_bytes() != old_bytes)
        check("3 the temp download folder is cleaned", not (data / "yt_tmp").exists())
        # the picker (withdrawn window)
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
        except Exception:                                    # noqa: BLE001
            print("skip 4 (no Tk)")
        else:
            import montage as M
            win = tk.Toplevel(root)
            win.withdraw()
            ent = {"title": "Another Day", "artist": "Senua, SYNDRA", "row": row, "old": None, "items": ranked}
            nf = {"title": "Lost", "artist": "Nobody", "row": dict(row, title="Lost"), "old": None, "reason": "no results"}
            rep = {"uncertain": [ent], "notfound": [nf], "failed": [], "downloaded": []}
            picks, opened = [], []
            M.build_yt_picker(win, "report", rep, lambda e, v, topic, s: picks.append((e["title"], v, topic)), opened.append)
            win.update_idletasks()

            def buttons(w):
                for c in w.winfo_children():
                    if c.winfo_class() == "TButton":
                        yield c
                    yield from buttons(c)
            btns = {}
            for b in buttons(win):
                btns.setdefault(str(b.cget("text")), []).append(b)
            check("4 every candidate has 'Open' and 'Download this' (2 candidates)", len(btns.get("Download this", [])) == 2 and len(btns.get("Open", [])) >= 2)
            check("4 every song to choose by hand has a 'Download link' (uncertain + not found)", len(btns.get("Download link", [])) == 2)
            btns["Download this"][1].invoke()
            btns["Open"][0].invoke()
            check("4 'Download this' hands over that candidate's id, 'Open' its link", picks == [("Another Day", "b", False)] and opened == ["https://youtu.be/a"], (picks, opened))
            ents = [w for w in win.winfo_children()]
            entries = []

            def find(w, cls):
                for c in w.winfo_children():
                    if c.winfo_class() == cls:
                        entries.append(c)
                    find(c, cls)
            find(win, "TEntry")
            entries[0].insert(0, "not a link")
            btns["Download link"][0].invoke()
            check("4 a pasted junk link is refused (nothing downloaded)", len(picks) == 1)
            entries[0].delete(0, "end")
            entries[0].insert(0, "https://youtu.be/lyRUUshYqDM")
            btns["Download link"][0].invoke()
            check("4 a pasted link is downloaded by id", picks[-1] == ("Another Day", "lyRUUshYqDM", False), picks)
            win.destroy()
            root.destroy()
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
