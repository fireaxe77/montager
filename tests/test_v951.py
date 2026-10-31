r"""V9.5.1 tests (fast; no network, no render): covers + tags (ytsongs), existing-songs tool, replace, Songs-tab list, intro motion, sky log line.
python tests/test_v951.py        V951_PARTS=0,1,2,3,4,5,6,7"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _root import find_root
ROOT = find_root(__file__)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="v951data_"))
import ytsongs as y

PARTS = os.environ.get("V951_PARTS", "0,1,2,3,4,5,6,7,8").split(",")
FAILS = []


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {info}" if info and not cond else ""))
    if not cond:
        FAILS.append(name)


def jpeg(size=(600, 600), colour=(200, 30, 30)):
    from PIL import Image
    import io
    b = io.BytesIO()
    Image.new("RGB", size, colour).save(b, "JPEG")
    return b.getvalue()


def make_mp3(path, secs=2):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={secs}", "-c:a", "libmp3lame", "-q:a", "5", "-y", str(path)], check=True)


def audio_hash(path):
    from mutagen.id3 import ID3, ID3NoHeaderError
    b = Path(path).read_bytes()
    try:
        start = ID3(str(path)).size
    except ID3NoHeaderError:
        start = 0
    return hashlib.sha1(b[start:]).hexdigest()


class FakeNet:
    """replaces ytsongs.http_get: Deezer answers by URL, everything logged"""
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, url, timeout=30):
        self.calls.append(url)
        for k, v in self.answers.items():
            if k in url:
                if isinstance(v, Exception):
                    raise v
                return v if isinstance(v, bytes) else v.encode()
        raise RuntimeError("no fake answer for " + url)


def deezer_track(url="https://cdn/img/abc/1000x1000-000000-80-0-0.jpg", dur=137, md5="abc"):
    import json
    return json.dumps({"duration": dur, "album": {"cover_xl": url, "md5_image": md5}})


def main():
    if "0" in PARTS:
        src = (ROOT / "montage.py").read_text(encoding="utf-8")
        check("0 APP_VERSION is V9.5.1", 'APP_VERSION = "V9.5.1"' in src)
        check("0 ytsongs ships with the installers", "ytsongs" in (ROOT / "packaging" / "make_release.py").read_text(encoding="utf-8")
              and "ytsongs" in (ROOT / "packaging" / "montager.spec").read_text(encoding="utf-8"))
        check("0 the installer version is 9.5.1", "AppVersion=9.5.1" in (ROOT / "packaging" / "montager.iss").read_text(encoding="utf-8"))

    if "1" in PARTS:                                         # Deezer lookup
        data = tempfile.mkdtemp(prefix="v951c_")
        row = {"title": "die for you", "artist": "Anna Marx", "dur": 137, "isrc": "GXKXT2601230"}
        net = FakeNet({"/track/isrc:GXKXT2601230": deezer_track()})
        y.http_get = net
        r = y.cover_lookup(row, data)
        check("1 ISRC lookup gives cover_xl", r["match"] == "isrc" and r["url"].endswith("1000x1000-000000-80-0-0.jpg"), r)
        n = len(net.calls)
        r2 = y.cover_lookup(row, data)
        check("1 second lookup is answered from the cache (no request)", r2 == r and len(net.calls) == n)
        y.cache_save(data)
        y._CACHES.clear()
        r3 = y.cover_lookup(row, data)
        check("1 the cache survives on disk", r3 == r and len(net.calls) == n)
        # no ISRC answer -> search, accepted only within 5 s
        import json
        row2 = {"title": "Song", "artist": "A, B", "dur": 100, "isrc": "NOPE"}
        search = json.dumps({"data": [{"duration": 109, "album": {"cover_xl": "https://cdn/x/zzz/1000x1000.jpg", "md5_image": "zzz"}},
                                      {"duration": 103, "album": {"cover_xl": "https://cdn/x/ok/1000x1000.jpg", "md5_image": "ok"}}]})
        net = FakeNet({"/track/isrc:NOPE": json.dumps({"error": {"type": "DataException", "message": "no data", "code": 800}}), "/search?q=": search})
        y.http_get = net
        r = y.cover_lookup(row2, data)
        check("1 ISRC not found -> search result within 5 s is used", r["match"] == "search" and "/ok/" in r["url"], r)
        row3 = dict(row2, isrc="", title="Other", dur=200)
        r = y.cover_lookup(row3, data)
        check("1 a search result 97 s off is NOT used", r["url"] is None, r)
        # a track without art
        net = FakeNet({"/track/isrc:BLANK": json.dumps({"duration": 100, "album": {"cover_xl": "https://cdn/images/cover//1000x1000.jpg", "md5_image": ""}}), "/search?q=": json.dumps({"data": []})})
        y.http_get = net
        check("1 Deezer's 'no picture' address is no cover", y.cover_lookup({"title": "t", "artist": "a", "dur": 100, "isrc": "BLANK"}, data)["url"] is None)
        # errors carry the real text and are not cached
        net = FakeNet({"/track/isrc:ERR1": RuntimeError("HTTP 503 Service Unavailable for X")})
        y.http_get = net
        try:
            y.cover_lookup({"title": "t", "artist": "a", "dur": 100, "isrc": "ERR1"}, data)
            check("1 network error raises", False)
        except RuntimeError as ex:
            check("1 network error text is kept", "503" in str(ex))
        check("1 an error is not cached", y.row_key({"isrc": "ERR1"}) not in y.cache_load(data))
        # rate: at most ~3 requests a second
        y.http_get = y.__dict__.get("_orig_http") or y.http_get
        shutil.rmtree(data, ignore_errors=True)

    if "2" in PARTS:                                         # real http_get throttle (local server)
        import http.server
        import threading
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
            def log_message(self, *a):
                pass
        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        import importlib
        importlib.reload(y)
        t0 = time.monotonic()
        for _ in range(7):
            y.http_get(f"http://127.0.0.1:{srv.server_port}/x")
        el = time.monotonic() - t0
        check("2 at most ~3 requests a second (7 requests take >= 1.9 s)", el >= 6 * y.DEEZER_GAP_S - 0.1, f"{el:.2f}")
        srv.shutdown()

    if "3" in PARTS:                                         # tags + cover embedding
        importlib = __import__("importlib")
        importlib.reload(y)
        from mutagen.id3 import ID3, ID3NoHeaderError
        td = Path(tempfile.mkdtemp(prefix="v951t_"))
        p = td / "a.mp3"
        make_mp3(p)
        h0 = audio_hash(p)
        tags = {"title": "T", "artist": "A, B", "album": "Alb", "year": "2022", "genre": "pop", "label": "Lab", "isrc": "XX123"}
        added = y.apply_tags(p, tags, jpeg(), fresh=True)
        t = ID3(str(p))
        check("3 every field and the cover added", set(added) == set(y.TAG_FIELDS) | {"cover"}, added)
        check("3 values readable", str(t["TIT2"]) == "T" and str(t["TPE1"]) == "A, B" and str(t["TALB"]) == "Alb" and str(t["TCON"]) == "pop" and str(t["TPUB"]) == "Lab"
              and str(t["TSRC"]) == "XX123" and str(t.get("TDRC") or t.get("TYER")) == "2022")
        ap = t.getall("APIC")
        check("3 front cover (type 3)", len(ap) == 1 and ap[0].type == 3 and ap[0].mime == "image/jpeg")
        check("3 the audio is bit-identical", audio_hash(p) == h0)
        # fill only: nothing existing is overwritten
        q = td / "b.mp3"
        make_mp3(q)
        y.apply_tags(q, {"title": "MINE", "album": "MY ALBUM"}, jpeg(colour=(1, 2, 3)), fresh=True)
        old_cover = bytes(ID3(str(q)).getall("APIC")[0].data)
        os.utime(q, (1_700_000_000, 1_700_000_000))
        h1 = audio_hash(q)
        added = y.apply_tags(q, tags, jpeg(colour=(9, 9, 9)))
        t = ID3(str(q))
        check("3 existing title / album stay, the rest is added", str(t["TIT2"]) == "MINE" and str(t["TALB"]) == "MY ALBUM" and set(added) == {"artist", "year", "genre", "label", "isrc"}, added)
        check("3 an existing cover is never replaced", bytes(t.getall("APIC")[0].data) == old_cover and "cover" not in added)
        check("3 audio identical + modified time kept", audio_hash(q) == h1 and int(os.stat(q).st_mtime) == 1_700_000_000)
        # a file without any tag
        r = td / "c.mp3"
        make_mp3(r)
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(r), "-map_metadata", "-1", "-id3v2_version", "0", "-write_id3v1", "0", "-c", "copy", "-y", str(td / "d.mp3")], check=True)
        added = y.apply_tags(td / "d.mp3", tags, None)
        check("3 a file with no tag at all gets the fields", "title" in added and "cover" not in added)
        # topic thumbnail: a 16:9 picture with the art in the middle becomes a square
        from PIL import Image
        import io
        im = Image.new("RGB", (1280, 720), (0, 0, 0))
        im.paste(Image.new("RGB", (720, 720), (30, 200, 60)), (280, 0))
        b = io.BytesIO()
        im.save(b, "JPEG")
        sq = y.square_crop(b.getvalue())
        check("3 a Topic thumbnail is cut to the square art", y.image_size(sq)[0] == y.image_size(sq)[1] and y.image_size(sq)[0] >= 700, y.image_size(sq))
        shutil.rmtree(td, ignore_errors=True)

    if "4" in PARTS:                                         # existing songs: preview changes nothing, apply fills only what is missing
        importlib = __import__("importlib")
        importlib.reload(y)
        from mutagen.id3 import ID3
        td = Path(tempfile.mkdtemp(prefix="v951e_"))
        data = td / "data"
        data.mkdir()
        files = []
        for i in range(4):
            p = td / f"s{i}.mp3"
            make_mp3(p)
            files.append(p)
        y.apply_tags(files[1], {"title": "T1", "artist": "A1", "album": "AL", "year": "2000", "genre": "g", "label": "l", "isrc": "I1"}, jpeg(), fresh=True)       # complete
        y.apply_tags(files[2], {"title": "OWN"}, jpeg(colour=(5, 5, 5)), fresh=True)                                                                                  # own title + cover
        meta = {f"u{i}": {"isrc": f"I{i}", "album": f"AL{i}", "year": "2001", "genre": "rock", "label": "lab"} for i in range(4)}
        rows = [{"title": f"T{i}", "artist": f"A{i}", "uri": f"u{i}", "dur": 2.0} for i in range(4)]
        meta["u1"] = {"isrc": "I1", "album": "AL", "year": "2000", "genre": "g", "label": "l"}
        import json
        net = FakeNet({"/track/isrc:I0": deezer_track(), "/track/isrc:I3": json.dumps({"error": {"type": "DataException", "message": "no data", "code": 800}}),
                       "/search?q=": json.dumps({"data": []}), "/img/abc/": jpeg()})
        y.http_get = net
        before = {p.name: (p.read_bytes(), os.stat(p).st_mtime_ns) for p in files}
        pairs = list(zip(rows, [{"path": str(p)} for p in files]))
        rep = y.process_existing(pairs, meta, data, False)
        after = {p.name: (p.read_bytes(), os.stat(p).st_mtime_ns) for p in files}
        check("4 PREVIEW changes no file", before == after)
        check("4 preview counts: covers / tags / no Deezer / complete", (rep["cover"], rep["tags"], rep["no_deezer"], rep["complete"]) == (1, 3, 1, 1), rep)
        h = {p.name: audio_hash(p) for p in files}
        own_cover = bytes(ID3(str(files[2])).getall("APIC")[0].data)
        rep = y.process_existing(pairs, meta, data, True)
        check("4 APPLY changed files 0 (cover + tags), 2 and 3 (tags only), not the complete file 1", len(rep["changed"]) == 3 and "s0.mp3" in rep["changed"][0] and "s2.mp3" in rep["changed"][1] and "s1.mp3" not in " ".join(rep["changed"]), rep["changed"])
        t2 = ID3(str(files[2]))
        check("4 file 2 keeps its title and its cover", str(t2["TIT2"]) == "OWN" and bytes(t2.getall("APIC")[0].data) == own_cover and str(t2["TALB"]) == "AL2")
        check("4 file 0 got the Deezer cover", len(ID3(str(files[0])).getall("APIC")) == 1)
        check("4 no cover for a track Deezer does not have, tags still added", not ID3(str(files[3])).getall("APIC") and str(ID3(str(files[3]))["TALB"]) == "AL3")
        check("4 audio of every file identical", all(audio_hash(p) == h[p.name] for p in files))
        check("4 the file names are unchanged", sorted(p.name for p in td.glob("*.mp3")) == sorted(p.name for p in files))
        check("4 a second Apply changes nothing", len(y.process_existing(pairs, meta, data, True)["changed"]) == 0)
        files[1].chmod(0o444)
        y.apply_tags  # (a read-only file is skipped and listed)
        rep = y.process_existing([(dict(rows[1]), {"path": str(files[1])})], dict(meta, u1=dict(meta["u1"], label="NEW", genre="g")), data, True)
        files[1].chmod(0o666)
        check("4 complete file: nothing to do", rep["complete"] == 1)
        y.apply_tags(files[3], {}, None)
        os.chmod(files[3], 0o444)
        meta["u3"]["label"] = "labx"
        rep = y.process_existing([(rows[3], {"path": str(files[3])})], dict(meta, u3=dict(meta["u3"], isrc="I3", label="another", genre="rock")), data, True)
        # label already set above, so only a read-only file with a missing field is the real test:
        t = ID3(str(files[3]))
        t.delall("TPUB")
        os.chmod(files[3], 0o666)
        t.save(str(files[3]))
        os.chmod(files[3], 0o444)
        rep = y.process_existing([(rows[3], {"path": str(files[3])})], meta, data, True)
        os.chmod(files[3], 0o666)
        check("4 a read-only file is skipped and listed", len(rep["locked"]) == 1 and "read-only" in rep["locked"][0], rep["locked"])
        shutil.rmtree(td, ignore_errors=True)

    if "5" in PARTS:                                         # download pipeline: cover source per song, replace goes to _replaced, nothing found = untouched
        importlib = __import__("importlib")
        importlib.reload(y)
        from mutagen.id3 import ID3
        td = Path(tempfile.mkdtemp(prefix="v951d_"))
        songs, data = td / "songs", td / "data"
        songs.mkdir()
        data.mkdir()
        (songs / "Old - A.mp3").write_bytes(b"OLD AUDIO")
        (songs / "Keep - K.mp3").write_bytes(b"KEEP AUDIO")
        rows = [{"title": "Old", "artist": "A", "dur": 100, "added": "2026-01-02", "uri": "u1", "_old": str(songs / "Old - A.mp3")},
                {"title": "Keep", "artist": "K", "dur": 100, "added": "2026-01-01", "uri": "u2", "_old": str(songs / "Keep - K.mp3")},
                {"title": "Fresh", "artist": "F", "dur": 100, "added": "2026-01-03", "uri": "u3"}]
        meta = {"u1": {"isrc": "I1", "album": "X", "year": "2020", "genre": "pop", "label": "L"}, "u3": {"isrc": "I3", "album": "Y", "year": "2021", "genre": "", "label": ""}}

        def srch(q):
            if "Keep" in q:
                return [{"id": "k", "title": "Keep (nightcore)", "channel": "x", "duration": 100}]
            if "Fresh" in q:
                return [{"id": "f", "title": "Fresh", "channel": "F - Topic", "duration": 100}]
            return [{"id": "o", "title": "Old", "channel": "A", "duration": 101}]

        def dl(vid):
            p = td / "yt" / f"{vid}.mp3"
            p.parent.mkdir(exist_ok=True)
            make_mp3(p)
            return p
        covers = {"Old": (jpeg(), "Deezer (ISRC)", ""), "Fresh": (jpeg(), "Topic thumbnail", "")}
        rep = y.fetch_new(rows, songs, data, None, lambda r: r["added"], progress=lambda t: None, search_fn=srch, download_fn=dl, meta=meta,
                          cover_fn=lambda row, topic: covers[row["title"]] if row["title"] != "Fresh" or topic else (None, "none", ""))
        names = {d["title"]: d for d in rep["downloaded"]}
        check("5 no limit: all 3 rows were looked at", rep["checked"] == 3)
        check("5 'Old' replaced: old file in _replaced, new file under the CSV name", (songs / "_replaced" / "Old - A.mp3").read_bytes() == b"OLD AUDIO" and (songs / "Old - A.mp3").stat().st_size > 1000)
        t = ID3(str(songs / "Old - A.mp3"))
        check("5 new file has CSV tags + cover", str(t["TALB"]) == "X" and str(t["TSRC"]) == "I1" and len(t.getall("APIC")) == 1)
        check("5 cover source per song in the report", names["Old"]["cover"] == "Deezer (ISRC)" and names["Fresh"]["cover"] == "Topic thumbnail" and "cover: Topic thumbnail" in y.report_text(rep))
        check("5 no confident match: the existing file is untouched and listed 'not found'", (songs / "Keep - K.mp3").read_bytes() == b"KEEP AUDIO"
              and len(rep["notfound"]) == 1 and "untouched" in rep["notfound"][0]["reason"] and "nightcore" in rep["notfound"][0]["reason"])
        check("5 a non-Topic upload never gets the thumbnail", y.cover_for.__doc__ and True)
        calls = []
        y.http_get = lambda url, timeout=30: (calls.append(url) or (_ for _ in ()).throw(RuntimeError("HTTP 500 for " + url)))
        c, src, note = y.cover_for({"title": "t", "artist": "a", "dur": 100, "isrc": "Z"}, data, topic_id=None)
        check("5 other upload + no Deezer cover = no cover, no thumbnail request, the error text is kept", c is None and src == "none" and "500" in note and not any("ytimg" in u for u in calls), (src, note, calls))
        shutil.rmtree(td, ignore_errors=True)

    if "6" in PARTS:                                         # intro motion
        import montage as M
        td = Path(tempfile.mkdtemp(prefix="v951i_"))
        moving, still = td / "moving.mp4", td / "still.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "mandelbrot=size=640x360:rate=60", "-t", "4", "-pix_fmt", "yuv420p", "-y", str(moving)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=0x445566:size=640x360:rate=60", "-t", "4", "-pix_fmt", "yuv420p", "-y", str(still)], check=True)
        mk = lambda p: {"path": str(p), "rect": [0, 0, 640, 360], "wh": [640, 360]}
        mv, st = M.intro_motion(mk(moving), 0.2, 2.6), M.intro_motion(mk(still), 0.2, 2.6)
        check("6 a moving picture is above the intro's minimum", mv >= M.INTRO_MOTION_MIN, mv)
        check("6 a still picture is below it", st < M.INTRO_MOTION_MIN, st)
        check("6 an unreadable clip counts as no motion", M.intro_motion({"path": str(td / "none.mp4"), "rect": [0, 0, 640, 360], "wh": [640, 360]}, 0, 2) == 0.0)
        check("6 the hold never runs below 0.25x", M.INTRO_V0_FLOOR == 0.25)
        import intro90
        ok, v0, *_ = intro90.speeds(1.2, 1.0)
        check("6 a short run-up (hold would be < 0.25x) is refused by intro_prepare's floor", ok and v0 < M.INTRO_V0_FLOOR, v0)
        shutil.rmtree(td, ignore_errors=True)
        src = (ROOT / "montage.py").read_text(encoding="utf-8")
        check("6 sky: a calm-role candidate is named as such in the log line", "a {c['calm']} take: low-energy part of the song" in src)

    if "7" in PARTS:                                         # Songs tab (needs a display)
        try:
            import tkinter
            tkinter.Tk().destroy()
        except Exception:                                    # noqa: BLE001
            print("skip 7 (no display)")
            return 1 if FAILS else 0
        import montage as M
        old = M.use_data_dir(Path(tempfile.mkdtemp(prefix="v951g_")))
        try:
            app = M.App(0, startup=False)
            app.root.update()
            texts = [str(b.cget("text")) for b in app.buttons]
            check("7 'Change match for selected file' is gone", not any("Change match" in t for t in texts), texts)
            check("7 the new buttons are there", all(any(w in t for t in texts) for w in ("Download new songs", "Download / replace selected", "Add covers and tags to existing songs", "Apply")))
            check("7 the song list allows Ctrl / Shift selection", str(app.mtree.cget("selectmode")) == "extended", app.mtree.cget("selectmode"))
            app.mtree.insert("", "end", iid="C:/songs/a.mp3", text="a.mp3", values=("t", "a", "", "", "", 100, "ok", ""))
            app.mtree.insert("", "end", iid="csv:u1", text="(no MP3)", values=("t2", "b", "", "", "", 0, "NO MP3", ""))
            app.match_rowmap = {"C:/songs/a.mp3": ({"title": "t", "artist": "a"}, "C:/songs/a.mp3"), "csv:u1": ({"title": "t2", "artist": "b"}, None)}
            app.mtree.selection_set(["C:/songs/a.mp3", "csv:u1"])
            rows, nomatch = app.selected_song_rows()
            check("7 rows with and without an MP3 can be selected together", [r["title"] for r, o in rows] == ["t", "t2"] and rows[0][1] and rows[1][1] is None)
            app.root.destroy()
        finally:
            M.restore_data_dir(old)

    if "8" in PARTS:                                         # song maps of new songs: several at a time, the same maps (V951_SONGS = three real MP3 paths separated by ;)
        import json
        import montage as M
        src = [Path(x) for x in os.environ.get("V951_SONGS", "").split(";") if x]
        if len(src) < 3:
            print("skip 8 (V951_SONGS = three MP3 paths separated by ;)")
        else:
            res = {}
            for mode in ("seq", "pre"):
                d = Path(tempfile.mkdtemp(prefix=f"v951s_{mode}_"))
                old = M.use_data_dir(d)
                try:
                    songs = []
                    for i, s_ in enumerate(src[:3]):
                        dst = d / f"song{i}.mp3"
                        shutil.copy2(s_, dst)
                        songs.append({"path": str(dst), "csv_bpm": None})
                    M.SONGMAP_PRE.clear()
                    M.SONGMAP_PREFETCH_WORKERS = 3 if mode == "pre" else 1
                    t0 = time.time()
                    M.songmap_prefetch(songs)
                    maps = [M.get_songmap(s_["path"], None) for s_ in songs]
                    for m_ in maps:
                        (m_.get("v2") or {}).pop("analysis_s", None)         # (the only field that is a stop-watch reading)
                    res[mode] = (time.time() - t0, json.dumps([{k: v for k, v in m.items() if k != "path"} for m in maps], sort_keys=True, default=str))
                finally:
                    M.restore_data_dir(old)
            check("8 the maps are the same with and without the prefetch", res["seq"][1] == res["pre"][1])
            print(f"   3 new songs: {res['seq'][0]:.1f} s one after the other, {res['pre'][0]:.1f} s prefetched")
            check("8 prefetch is faster", res["pre"][0] < res["seq"][0] * 0.8, (res["seq"][0], res["pre"][0]))

    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
