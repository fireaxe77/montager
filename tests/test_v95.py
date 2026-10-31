r"""V9.5 tests (fast, no network, no render): Songs tab > Download new songs (ytsongs.py) with a fake yt-dlp.
python tests/test_v95.py"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _root import find_root
ROOT = find_root(__file__)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="v95data_"))
import ytsongs as y

FAILS = []


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {info}" if info and not cond else ""))
    if not cond:
        FAILS.append(name)


def C(title, channel, dur, vid="x"):
    return {"id": vid, "title": title, "channel": channel, "duration": dur}


def main():
    # 0 version
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("0 APP_VERSION is V9.5", 'APP_VERSION = "V9.5"' in src)
    check("0 Songs tab has the button and the box", "Download new songs" in src and "Newest songs to check" in src and 'tk.StringVar(value="10")' in src)

    # 1 pick rules
    art = ["Anna Marx"]
    want = 137
    check("1 length within 5 s passes", y.judge(C("Anna Marx - die for you", "Anna Marx", 142), "die for you", art, want) is None)
    check("1 length 6 s off is rejected", y.judge(C("die for you", "Anna Marx", 143), "die for you", art, want) is not None)
    check("1 hour-long mix is rejected", y.judge(C("die for you 1 hour", "x", 3600), "die for you", art, want) is not None)
    for bad in ("slowed", "sped up", "speed up", "nightcore", "reverb", "8D", "live", "remix", "cover", "instrumental", "karaoke"):
        check(f"1 banned word '{bad}'", y.judge(C(f"die for you ({bad})", "x", 137), "die for you", art, want) is not None)
    check("1 banned word in the Spotify title is allowed", y.judge(C("Live Forever (Live)", "x", 137), "Live Forever", art, 137) is None)
    check("1 'delivered' / 'discover' are not 'live' / 'cover'", y.judge(C("Delivered discover", "x", 137), "Delivered discover", art, 137) is None)
    check("1 'Speed Up' also needs to be in the Spotify title", y.judge(C("Song (Speed Up)", "x", 137), "Song (Speed Up)", art, 137) is None)

    # 2 preference: Topic > artist's channel > other
    cands = [C("a", "Random Guy", 137, "o"), C("a", "Anna Marx", 137, "ar"), C("a", "Anna Marx - Topic", 135, "t")]
    b, _ = y.pick(cands, "die for you", art, want)
    check("2 Topic upload wins", b and b["id"] == "t" and b["kind"] == "topic")
    b, _ = y.pick(cands[:2], "die for you", art, want)
    check("2 artist channel beats other", b and b["id"] == "ar" and b["kind"] == "artist")
    b, _ = y.pick(cands[:1], "die for you", art, want)
    check("2 other channel as last resort", b and b["id"] == "o")
    check("2 'Anna Marx Official' / VEVO count as the artist", y.channel_kind("AnnaMarxVEVO", art) == "artist" and y.channel_kind("Anna Marx Official", art) == "artist")
    check("2 a different channel is 'other'", y.channel_kind("Anna Marxist Radio", art) == "other")

    # 3 not found reports the best candidate
    b, why = y.pick([C("Mix", "DJ", 3600), C("die for you nightcore", "Fan", 137)], "die for you", art, want)
    check("3 nothing passes -> None", b is None)
    check("3 reason names title, channel and lengths", "die for you nightcore" in why and "Fan" in why and "2:17" in why, why)
    b, why = y.pick([], "x", art, 100)
    check("3 no results -> reason", b is None and why == "no results")

    # 4 file name matches the app's song match
    import montage as m
    fn = y.song_filename('Why? Not: "this"', "Anna Marx, Три дня дождя")
    check("4 file name has no forbidden characters", not any(c in fn for c in '\\/:*?"<>|'), fn)
    a = {"path": fn, "title": "", "artist": ""}
    t, ars = m.parse_song_file(a)
    check("4 app parses the name back to the CSV title + artists", t == m.norm_song('Why? Not: "this"') and ars == m._artists_of("Anna Marx, Три дня дождя"), (t, ars))

    # 5 whole chain with a fake yt-dlp (no overwrite, tags from CSV, temp cleanup, newest first, not found, failure text)
    from mutagen.id3 import ID3
    import shutil
    import subprocess
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        songs, data = td / "songs", td / "data"
        songs.mkdir()
        data.mkdir()
        rows = [{"title": "Old", "artist": "A", "dur": 100, "added": "2020-01-01"},
                {"title": "New One", "artist": "B, C", "dur": 120, "added": "2026-05-01"},
                {"title": "Gone", "artist": "D", "dur": 130, "added": "2026-04-01"},
                {"title": "Broken", "artist": "E", "dur": 140, "added": "2026-03-01"},
                {"title": "Exists", "artist": "F", "dur": 150, "added": "2026-02-01"}]
        (songs / "Exists - F.mp3").write_bytes(b"keep me")
        searched = []

        def fake_search(q):
            searched.append(q)
            if "New One" in q:
                return [C("New One (slowed)", "B - Topic", 120, "bad"), C("New One", "B - Topic", 121, "good")]
            if "Gone" in q:
                return [C("Gone", "Someone", 400, "long")]
            if "Broken" in q:
                return [C("Broken", "E", 140, "brk")]
            if "Exists" in q:
                return [C("Exists", "F - Topic", 150, "ex")]
            return [C("Old", "A", 100, "old")]

        def fake_dl(vid):
            if vid == "brk":
                raise RuntimeError("ERROR: Sign in to confirm you are not a bot")
            tmp = data / "yt_tmp"
            tmp.mkdir(exist_ok=True)
            p = tmp / f"{vid}.mp3"
            ff = shutil.which("ffmpeg")
            subprocess.run([ff, "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "1", "-y", str(p)], check=True)
            return p

        key = lambda r: r["added"]
        rep = y.fetch_new(rows, songs, data, 4, key, progress=lambda t: None, search_fn=fake_search, download_fn=fake_dl)
        check("5 only the 4 newest are checked (Old is not)", rep["checked"] == 4 and not any("Old" in q for q in searched), searched)
        check("5 one download", len(rep["downloaded"]) == 1 and rep["downloaded"][0]["video"] == "New One")
        f = songs / y.song_filename("New One", "B, C")
        check("5 file exists in the songs folder", f.is_file())
        tg = ID3(str(f))
        check("5 ID3 title + artist come from the CSV", str(tg["TIT2"]) == "New One" and str(tg["TPE1"]) == "B, C")
        check("5 not found lists the 400 s video", len(rep["notfound"]) == 1 and "6:40" in rep["notfound"][0]["reason"] and "Someone" in rep["notfound"][0]["reason"])
        check("5 failed download shows the real error text", any("not a bot" in x["reason"] for x in rep["failed"]))
        check("5 existing file is never overwritten", (songs / "Exists - F.mp3").read_bytes() == b"keep me"
              and any("already exists" in x["reason"] for x in rep["failed"]))
        check("5 temp folder cleaned", not (data / "yt_tmp").exists())
        check("5 report text", "DOWNLOADED" in y.report_text(rep) and "NOT FOUND" in y.report_text(rep) and "FAILED" in y.report_text(rep))
        # the app's own scan + match counts it as a normal song
        cfg = {"mp3_dir": str(songs), "output_root": str(td / "out"), "skip_dirs": []}
        try:
            audio = m.scan_audio(cfg, rescan=True)
            matched, _un = m.match_playlist([dict(r, uri="") for r in rows], audio, cfg)
            names = {r["title"] for r, a, sc in matched}
            check("5 the app's scan lists the new file at once and matches it", "New One" in names, (len(audio), names))
        except Exception as ex:
            check("5 app scan + match", False, repr(ex))
        check("5 no length in CSV -> not found", y.fetch_new([{"title": "T", "artist": "A", "dur": 0, "added": ""}], songs, data, 1, key,
                                                           progress=lambda t: None, search_fn=fake_search, download_fn=fake_dl)["notfound"] != [])

    # 6 search errors are shown, not skipped
    def boom(q):
        raise RuntimeError("yt-dlp search failed (exit 1): HTTP Error 429")
    with tempfile.TemporaryDirectory() as td:
        rep = y.fetch_new([{"title": "T", "artist": "A", "dur": 100, "added": ""}], td, td, 1, lambda r: 0, progress=lambda t: None, search_fn=boom)
        check("6 a failed search is reported with its text", rep["failed"] and "429" in rep["failed"][0]["reason"])

    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
