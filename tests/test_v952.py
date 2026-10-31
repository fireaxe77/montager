r"""V9.5.2 tests (fast; no network, no render): match cache vs rewritten tags, candidate scoring, cover thumbnails, interpolation default, sky extension, changelog.
python tests/test_v952.py        V952_PARTS=0,1,2,3,4,5,6"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _root import find_root
ROOT = find_root(__file__)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="v952data_"))
import ytsongs as y

PARTS = os.environ.get("V952_PARTS", "0,1,2,3,4,5,6").split(",")
FAILS = []


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {info}" if info and not cond else ""))
    if not cond:
        FAILS.append(name)


def C(title, channel, dur, views=0, verified=False, vid="x"):
    return {"id": vid, "title": title, "channel": channel, "duration": dur, "views": views, "verified": verified}


def main():
    if "0" in PARTS:
        src = (ROOT / "montage.py").read_text(encoding="utf-8")
        check("0 APP_VERSION is V9.5.2", 'APP_VERSION = "V9.5.2"' in src)
        check("0 installer version 9.5.2", "AppVersion=9.5.2" in (ROOT / "packaging" / "montager.iss").read_text(encoding="utf-8"))

    if "1" in PARTS:                                         # tags rewritten (sizes change, modified times stay): the match is still found
        import montage as M
        td = Path(tempfile.mkdtemp(prefix="v952m_"))
        old = M.use_data_dir(td / "data")
        try:
            songs = td / "songs"
            songs.mkdir()
            rows = [{"title": f"Song {i}", "artist": f"Artist {i}", "added": "2026-01-01", "uri": f"u{i}", "dur": 100.0, "tempo": 0.0, "energy": None, "dance": None} for i in range(3)]
            paths = []
            for i in range(3):
                p = songs / f"Song {i} - Artist {i}.mp3"
                p.write_bytes(b"A" * (1000 + i))
                os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
                paths.append(p)
            csvp = td / "p.csv"
            csvp.write_text("x", encoding="utf-8")
            cfg = {"mp3_dir": str(songs), "output_root": str(td / "out"), "skip_dirs": [], "song_overrides": {}, "match_floor": 60}

            def audio():
                out = []
                for p in paths:
                    st = os.stat(p)
                    out.append({"path": str(p), "artist": "", "title": "", "dur": 5.0, "key": f"{p}|{st.st_size}|{int(st.st_mtime)}"})
                return out
            m1, un1, st1 = M.match_cached(cfg, csvp, rows, audio())
            check("1 first match finds 3 songs", len(m1) == 3 and st1 == "full", (len(m1), st1))
            m2, un2, st2 = M.match_cached(cfg, csvp, rows, audio())
            check("1 same files: answered from the cache", len(m2) == 3 and st2 == "hit", st2)
            for i, p in enumerate(paths):                    # a tag writer: bigger files, the same modified times
                st = os.stat(p)
                p.write_bytes(b"B" * (5000 + i))
                os.utime(p, (st.st_atime, st.st_mtime))
            m3, un3, st3 = M.match_cached(cfg, csvp, rows, audio())
            check("1 files whose size changed (same modified time) still match", len(m3) == 3 and st3 == "full", (len(m3), st3))
            check("1 the folder signature includes the sizes", len(M._folder_sig(audio())) == 3)
        finally:
            M.restore_data_dir(old)

    if "2" in PARTS:                                         # candidate scoring
        artists, label = ["LUM!X", "PIA MARIA"], "Spinnin' Records"
        cands = [C("Halo (Eurovision 2022, Austria) (8-Bit LUM!X & Pia Maria Emulation)", "8-Bit Arcade - Topic", 162, 500000, False, "bad"),
                 C("LUM!X - Halo (feat. PIA MARIA) [Official Audio]", "Spinnin' Records", 162, 1984700, True, "good"),
                 C("LUM!X ft. Pia Maria - Halo (Lyrics)", "A t l a s", 163, 1712, False, "atlas"),
                 C("LUM!X feat. Pia Maria - Halo - Austria - Official Music Video - Eurovision 2022", "Eurovision Song Contest", 175, 6694042, True, "video")]
        ranked, rej = y.rank(cands, "Halo (feat. PIA MARIA)", artists, 160, label)
        check("2 the official label upload is the pick", ranked and ranked[0]["id"] == "good" and not ranked[0]["uncertain"], [c["id"] for c in ranked])
        check("2 8-bit / emulation title is a hard reject", any(c["id"] == "bad" for _w, c in rej) and "8-bit" in " ".join(w for w, c in rej if c["id"] == "bad"))
        check("2 15 s off is a hard reject", any(c["id"] == "video" and "length" in w for w, c in rej))
        check("2 runner-up is the next clean title", len(ranked) > 1 and ranked[1]["id"] == "atlas")
        for w in ("8-bit", "8 bit", "8bit", "chiptune", "emulation", "midi", "piano version", "acoustic", "tribute", "mashup", "bass boosted", "type beat", "reaction", "tutorial",
                  "slowed", "sped up", "speed up", "nightcore", "reverb", "8D", "live", "remix", "cover", "instrumental", "karaoke"):
            check(f"2 hard reject '{w}'", y.judge(C(f"Song ({w})", "x", 100), "Song", ["A"], 100) is not None)
        check("2 a banned word that the Spotify title has is allowed", y.judge(C("Song (Acoustic)", "x", 100), "Song (Acoustic)", ["A"], 100) is None)
        ex = y.extra_words("LUM!X - Halo (feat. PIA MARIA) [Official Audio]", "Halo (feat. PIA MARIA)", artists)
        check("2 no extra words in a clean title", ex == [], ex)
        ex = y.extra_words("Halo (melancholia, Album 2023 remastered)", "Halo", ["X"])
        check("2 album / year words are extra, allowlist words are not", ex == ["melancholia", "2023"], ex)
        # fewer extra words beat a better channel; channel beats views; views break ties
        r, _ = y.rank([C("T extra words here", "A", 100, 9, True, "a"), C("T", "Nobody", 100, 1, False, "b")], "T", ["A"], 100)
        check("2 fewest extra words come first", r[0]["id"] == "b")
        r, _ = y.rank([C("T", "Nobody", 100, 999, False, "a"), C("T", "A", 100, 1, False, "b")], "T", ["A"], 100)
        check("2 then the channel score", r[0]["id"] == "b")
        r, _ = y.rank([C("T", "A", 100, 5, False, "a"), C("T", "A", 100, 50, False, "b")], "T", ["A"], 100)
        check("2 then the views (not the search order)", r[0]["id"] == "b")
        check("2 a Topic channel with an unrelated name is not official", y.channel_score("8-Bit Arcade - Topic", artists, label) == y.CH_OTHER)
        check("2 a Topic channel of the artist / of the label is the best", y.channel_score("LUM!X - Topic", artists, label) == y.CH_TOPIC_OWN and y.channel_score("Spinnin' Records - Topic", artists, label) == y.CH_TOPIC_OWN)
        check("2 the label's own channel", y.channel_score("Spinnin' Records", artists, label) == y.CH_NAMED)
        check("2 verified beats other", y.channel_score("Someone", artists, label, True) == y.CH_VERIFIED)
        r, _ = y.rank([C("T extra", "A", 100, 5, False, "a")], "T", ["A"], 100)
        check("2 extra words left = UNCERTAIN", r[0]["uncertain"])
        r, _ = y.rank([C("T", "Nobody", 100, 5, False, "a")], "T", ["A"], 100)
        check("2 an 'other' channel = UNCERTAIN", r[0]["uncertain"])
        import shutil
        import subprocess as sp
        td = Path(tempfile.mkdtemp(prefix="v952u_"))
        songs, data = td / "songs", td / "data"
        songs.mkdir()
        data.mkdir()
        calls = []

        def dl(vid):
            calls.append(vid)
            p = td / f"{vid}.mp3"
            sp.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", "-y", str(p)], check=True)
            return p
        rows = [{"title": "T", "artist": "A", "dur": 100, "added": "2026-01-01", "uri": "u1"}, {"title": "U", "artist": "B", "dur": 100, "added": "2026-01-02", "uri": "u2"}]

        def srch(q):
            return [C("U extra words", "Nobody", 100, 5, False, "u1")] if "U" in q.split()[-1:] or " U" in q else [C("T", "A", 100, 5, False, "t1"), C("T (Official Audio)", "A", 100, 2, False, "t2")]
        rep = y.fetch_new(rows, songs, data, None, lambda r: r["added"], progress=lambda t: None, search_fn=srch, download_fn=dl, cover_fn=lambda r, t: (None, "none", ""))
        check("2 an uncertain song is NOT downloaded and is listed with its best candidates", calls == ["t1"] and len(rep["uncertain"]) == 1 and rep["uncertain"][0]["top"], (calls, rep["uncertain"]))
        txt = y.report_text(rep)
        check("2 the result names the chosen video and the runner-up", "chosen:" in txt and "runner-up:" in txt and "UNCERTAIN" in txt)
        shutil.rmtree(td, ignore_errors=True)

    if "3" in PARTS:                                         # thumbnails
        import montage as M
        from PIL import Image
        import io
        td = Path(tempfile.mkdtemp(prefix="v952t_"))
        old = M.use_data_dir(td / "data")
        try:
            a, b = td / "a.mp3", td / "b.mp3"
            for p in (a, b):
                subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", "-y", str(p)], check=True)
            buf = io.BytesIO()
            Image.new("RGB", (640, 480), (10, 200, 30)).save(buf, "JPEG")
            y.apply_tags(a, {"title": "t"}, buf.getvalue(), fresh=True)
            pa = M.song_thumb(str(a), 24)
            check("3 a song with a cover gets a 24 x 24 PNG", pa and Image.open(pa).size == (24, 24))
            check("3 a song without a cover has none (and it is remembered)", M.song_thumb(str(b), 24) is None and any((M.DATA / "thumbs" / "24").glob("*.none")))
            t0 = os.stat(pa).st_mtime_ns
            check("3 the second call uses the disk cache", M.song_thumb(str(a), 24) == pa and os.stat(pa).st_mtime_ns == t0)
            y.apply_tags(a, {"album": "x"}, None)            # the file changes: a new key
        finally:
            M.restore_data_dir(old)
        try:
            import tkinter
            tkinter.Tk().destroy()
        except Exception:                                    # noqa: BLE001
            print("skip 3 (GUI part: no display)")
        else:
            old = M.use_data_dir(Path(tempfile.mkdtemp(prefix="v952g_")))
            try:
                app = M.App(0, startup=False)
                app.root.update()
                rh = int(M.ttk.Style().lookup("Treeview", "rowheight"))
                for name, tree, tab in (("Songs tab", app.mtree, "Songs"), ("picker", app.stree, "Manual")):
                    app.nb.select(app.tabs[tab])
                    tree.insert("", "end", iid="C:/x/plain.mp3", text="plain", values=())
                    tree.insert("", "end", iid="C:/x/none.mp3", text="none.mp3", values=(), image=app.thumb_image(tree, "C:/x/none.mp3"))
                    app.root.update()
                    b0, b1 = tree.bbox("C:/x/plain.mp3"), tree.bbox("C:/x/none.mp3")
                    check(f"3 {name}: a row with the square is exactly as tall as one without ({rh})", b0 and b1 and b1[3] == b0[3] and b1[3] <= rh + 1, (b0, b1))
                check("3 both lists use the same square size and blank image", app.thumb_image(app.mtree, "z") is app.thumb_image(app.stree, "z"))
                app.root.destroy()
            finally:
                M.restore_data_dir(old)

    if "4" in PARTS:                                         # interpolation off by default, once
        import json
        import montage as M
        td = Path(tempfile.mkdtemp(prefix="v952i_"))
        old = M.use_data_dir(td)
        try:
            (td / "config.json").write_text(json.dumps({"interpolate_low_fps": True, "interp50_v94": True, "cfg_version": 4}), encoding="utf-8")
            c = M.load_config()
            check("4 a saved config with interpolation on is switched off once", c["interpolate_low_fps"] is False)
            check("4 and saved that way", json.loads((td / "config.json").read_text(encoding="utf-8"))["interpolate_low_fps"] is False)
            d = json.loads((td / "config.json").read_text(encoding="utf-8"))
            d["interpolate_low_fps"] = True
            (td / "config.json").write_text(json.dumps(d), encoding="utf-8")
            check("4 the Settings checkbox still works afterwards (not switched off again)", M.load_config()["interpolate_low_fps"] is True)
            (td / "config.json").unlink()
            check("4 a fresh install has it off", M.load_config()["interpolate_low_fps"] is False)
        finally:
            M.restore_data_dir(old)

    if "5" in PARTS:                                         # the sky paint follows the sky down its gradient
        import cv2
        import numpy as np
        import montage as M
        H, W = 432, 768
        img = np.zeros((H, W, 3), np.uint8)
        top = np.array([60, 140, 230], np.float32)               # deep blue at the top
        low = np.array([170, 210, 240], np.float32)              # pale hazy blue towards the horizon
        for yy in range(int(H * 0.62)):
            k = yy / (H * 0.62)
            img[yy] = (top * (1 - k) + low * k).astype(np.uint8)
        rng = np.random.default_rng(1)
        wall = (np.array([150, 110, 70]) + rng.integers(-25, 25, (H - int(H * 0.62), W, 3))).clip(0, 255).astype(np.uint8)
        img[int(H * 0.62):] = wall
        sample = M.sky_eyedrop_sample(img)
        m0 = M.sky_eyedrop_mask(img, sample)
        m1 = M.sky_extend_mask(img, m0, sample)
        r0, r1 = np.where(m0.any(1))[0].max(), np.where(m1.any(1))[0].max()
        check("5 the eyedropper alone stops before the pale lower sky", r0 < 0.55 * H, r0 / H)
        check("5 the extended mask reaches the sky's real boundary (the wall)", 0.55 * H < r1 <= 0.64 * H, r1 / H)
        check("5 it never enters the wall", not m1[int(H * 0.66):].any())
        check("5 the original mask is kept inside the new one", bool((m0 <= m1).all()))
        check("5 no straight cut: the lower edge of the paint is the wall line (a pale sky on a dark picture is not cut mid-sky)", abs(r1 - int(H * 0.62)) <= 8, (r1, int(H * 0.62)))

    if "6" in PARTS:                                         # the Settings changelog
        txt = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
        heads = re.findall(r"^## (V[\d.]+)\b[^\n]*", txt, re.M)
        check("6 a V9.5.2 entry is at the top", heads[0] == "V9.5.2")
        check("6 R6S support is under the V8 entry, V8.0.1 is about the icon files", "V8" in heads and "Rainbow Six Siege is the third game" in txt.split("## V8 - ")[1].split("\n## ")[0]
              and "third game" not in txt.split("## V8.0.1")[1].split("\n## ")[0])
        tags = subprocess.run(["git", "tag", "--list"], capture_output=True, text=True, cwd=str(ROOT)).stdout.split()
        base = {re.sub(r"-good$", "", t).lstrip("v") for t in tags if re.match(r"^v\d", t)}
        have = {h.lstrip("V") for h in heads} | {"8.1"}      # (the V8.1 entry is named V8.10 on purpose)
        check("6 every tagged version has an entry", not (base - have), sorted(base - have))

    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
