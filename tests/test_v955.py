"""V9.5.5 tests (fast, no render, no network; everything runs on temporary folders, the real library and montage_data are never touched). Parts (V955_PARTS=0,1,2,3,4,5):
  0) version, packaging, an empty CSV folder means no CSV
  1) the swapped-order / local-file-row match (FWMC, TERMIK, Ye - WW3), nothing that matched before changes, the match cache is completed in place
  2) songs without a CSV row: no CSV at all, a CSV with no row for a file; '(analysis)' in the log; the picker takes them
  3) setup_check / Settings wording: a missing CSV is no problem
  4) published montages: record, rebuild from the log, preview changes nothing, Apply moves 5 temp clips, Unmark brings them back, exclusion, caches
  5) the Songs tab with and without a CSV (needs a display)
python tests\\test_v955.py"""
import csv
import datetime
import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="v955_"))
os.environ["MONTAGER_DATA"] = str(TMP / "data")
import montage as M                                                                           # noqa: E402
import published as P                                                                         # noqa: E402
from v696_common import check, section, FAILS                                                 # noqa: E402

PARTS = os.environ.get("V955_PARTS", "0,1,2,3,4,5").split(",")


def A(path, dur, artist="", title=""):
    return {"path": path, "artist": artist, "title": title or Path(path).stem, "dur": dur, "key": f"{path}|1000|1"}


def R(title, artist, dur, uri="spotify:track:x", added="2026-01-01T00:00:00Z"):
    return {"title": title, "artist": artist, "added": added, "uri": uri, "dur": dur, "tempo": 0.0, "energy": 0.0, "dance": 0.0}


def mp3(path, sec=3, hz=300):
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f={hz}:d={sec}", "-c:a", "libmp3lame", "-b:a", "32k", str(path)], capture_output=True)
    assert r.returncode == 0, r.stderr.decode()[-200:]
    t = time.time() - 900                                                       # the scan skips files that may still be written
    os.utime(path, (t, t))


def part0():
    with section("0) version, packaging, no CSV folder"):
        check(M.APP_VERSION == "V9.5.5", f"APP_VERSION is V9.5.5 ({M.APP_VERSION})")
        rel = (ROOT / "packaging" / "make_release.py").read_text(encoding="utf-8")
        check(rel.count("published.py") >= 2 and '"published"' in rel, "published.py is in the release file lists and module list")
        check(M.newest_csv({"playlist_dir": ""}) is None and M.newest_csv({"playlist_dir": "   "}) is None, "an empty playlist folder setting is no CSV (it never means the current folder)")
        (TMP / "emptydir").mkdir(exist_ok=True)
        cfg = dict(M.DEFAULT_CONFIG, playlist_dir=str(TMP / "emptydir"))
        check(M.read_playlist(cfg) == (None, [], {}), "a folder without a CSV: read_playlist gives no rows and no error")


def part1():
    with section("1) swapped-order / local-file-row match"):
        audio = [A("/s/FWMC - Mixed Personalities.mp3", 230.5), A("/s/TERMIK, Goodscandal, PACANI - The Riddle.mp3", 135.8), A("/s/Ye - WW3.mp3", 101.8),
                 A("/s/Artist One - Plain Song.mp3", 200.0), A("/s/Laura Welsh  Break The Fall.mp3", 281.5)]
        rows = [R("FWMC - Mixed Personalities", "", 230.0, "spotify:local:::FWMC+-+Mixed+Personalities:230"), R("The Riddle", "Xd", 143.709),
                R("WW3", "Ye", 101.0), R("Plain Song", "Artist One", 200.0), R("Laura Welsh  Break The Fall", "", 281.0, "spotify:local:::Laura:281"),
                R("Other Track", "Nobody", 180.0)]
        cfg = dict(M.DEFAULT_CONFIG, song_overrides={})
        m0, u0 = M.match_playlist(rows, audio, cfg, swap=False)
        m1, u1 = M.match_playlist(rows, audio, cfg)
        names = lambda m: {Path(a["path"]).name: (r["artist"], r["title"]) for r, a, sc in m}
        n0, n1 = names(m0), names(m1)
        check("FWMC - Mixed Personalities.mp3" not in n0 and "FWMC - Mixed Personalities.mp3" in n1, "FWMC - Mixed Personalities: not matched before, matched to its CSV row now (local-file row, 230.5 s vs 230 s)")
        check("Ye - WW3.mp3" in n1 and n1["Ye - WW3.mp3"] == ("Ye", "WW3"), "'Artist - Title' file name vs a CSV row Title / Artist: matched on title + artist + length")
        check("Laura Welsh  Break The Fall.mp3" in n1, "a local-file row whose whole title is the file's whole name matches (length within 3 s)")
        check("TERMIK, Goodscandal, PACANI - The Riddle.mp3" not in n1, "TERMIK - The Riddle: stays unmatched (the CSV row is 'The Riddle' by 'Xd', 143.7 s vs 135.8 s: other artist, 8 s off)")
        check(all(n1.get(k) == v for k, v in n0.items()), "every match that existed before is unchanged")
        check(len(m1) == len(m0) + 2 and len(M.SWAP_NEW) == 2 and {Path(a["path"]).name for r, a in M.SWAP_NEW} == {"FWMC - Mixed Personalities.mp3", "Laura Welsh  Break The Fall.mp3"},
              f"the swapped tier adds exactly the two local-file rows ({len(m0)} -> {len(m1)}; the loose tier already had Ye - WW3 here)")
        # the length rule: 4 s off = not accepted
        a2 = [A("/s/FWMC - Mixed Personalities.mp3", 234.5)]
        mm, _u = M.match_playlist(rows[:1], a2, cfg)
        check(mm == [], "a length 4 s away is refused (the limit is 3 s)")
        # two rows that could both be the file: the closer length decides; equal lengths stay unmatched and are listed
        rows2 = [R("WW3", "Ye", 101.0, "u1"), R("WW3", "Ye", 103.0, "u2")]
        mm, _u = M.match_playlist(rows2, [A("/s/Ye - WW3.mp3", 101.2)], cfg)
        check(len(mm) == 1 and mm[0][0]["uri"] == "u1", "two possible rows: the one with the closer length is taken")
        rows3 = [R("WW3", "Ye", 101.0, "u1"), R("WW3", "Ye", 101.1, "u2")]
        mm, _u = M.match_playlist(rows3, [A("/s/Ye - WW3.mp3", 101.05)], cfg)
        check(mm == [] and M.SWAP_AMBIG, f"two rows with the same length: not matched, listed ({M.SWAP_AMBIG})")
        # the cache: an old cache (no 'sw' mark) is completed in place, the other matches stay
        lib, pl = TMP / "songs1", TMP / "pl1"
        lib.mkdir()
        pl.mkdir()
        mp3(lib / "Ye - WW3.mp3", 3, 300)
        mp3(lib / "Plain Artist - Plain Song.mp3", 4, 400)
        with open(pl / "l.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Track URI", "Track Name", "Artist Name(s)", "Duration (ms)", "Added At"])
            w.writerow(["spotify:track:1", "WW3", "Ye", 3000, "2026-01-01T00:00:00Z"])
            w.writerow(["spotify:track:2", "Plain Song", "Plain Artist", 4000, "2026-01-02T00:00:00Z"])
        cfg = dict(M.DEFAULT_CONFIG, mp3_dir=str(lib), playlist_dir=str(pl), song_overrides={}, output_root=str(TMP / "out"))
        aud = M.scan_audio(cfg)
        csvp, rws, _c = M.read_playlist(cfg)
        real_swap = M.swap_match
        M.swap_match = lambda *a, **k: []
        try:
            mA, _u, stA = M.match_cached(cfg, csvp, rws, aud)
        finally:
            M.swap_match = real_swap
        cache = json.loads(M.MATCH_CACHE.read_text(encoding="utf-8"))
        cache.pop("sw", None)                                                   # = a cache written by V9.5.4
        M.MATCH_CACHE.write_text(json.dumps(cache), encoding="utf-8")
        mB, _u, stB = M.match_cached(cfg, csvp, rws, aud)
        c2 = json.loads(M.MATCH_CACHE.read_text(encoding="utf-8"))
        check(stA == "full" and stB == "hit", f"the second call is a cache hit (no rematch): {stA} then {stB}")
        check(len(mB) >= len(mA) and {(r["uri"], a["path"]) for r, a, s in mA} <= {(r["uri"], a["path"]) for r, a, s in mB}, "the old matches are all still there")
        check(c2.get("sw") == M.SWAP_VER and c2.get("v") == M.MATCH_CACHE_VER, "the cache is completed in place (swap mark added, MATCH_CACHE_VER unchanged)")
        check(not any(p.suffix in (".mp3",) and p.name != p.name.strip() for p in lib.iterdir()) and sorted(p.name for p in lib.iterdir()) == ["Plain Artist - Plain Song.mp3", "Ye - WW3.mp3"], "no file was renamed")


def part2():
    with section("2) songs without a CSV row (case B) and without any CSV (case C)"):
        lib = TMP / "songs2"
        lib.mkdir()
        for i, n in enumerate(("Alpha Artist - Alpha Song.mp3", "Beta Song - Beta Artist.mp3", "just a name.mp3")):
            mp3(lib / n, 3 + i, 250 + 60 * i)
        out = TMP / "out2"
        cfg = dict(M.DEFAULT_CONFIG, mp3_dir=str(lib), playlist_dir="", output_root=str(out), song_overrides={})
        songs, un, csvn = M.song_pool(cfg)
        check(len(songs) == 3 and un == [] and csvn is None, f"no CSV: all 3 songs of the folder are songs, nothing 'without MP3', no CSV name ({len(songs)}, {un}, {csvn})")
        check(all(s.get("no_csv") and s["csv_bpm"] is None and s["energy"] is None and s["dance"] is None for s in songs), "tempo / energy / danceability stay empty: the song analysis supplies them")
        check(all(s["added"] and abs((datetime.datetime.now() - s["added"]).total_seconds()) < 3600 for s in songs), "'added' = the file's creation date")
        check(all(s["title"] and s["dur"] > 2 for s in songs), "title (tags / file name) and length (file) are filled")
        # case B: a CSV with a row for one file only
        pl = TMP / "pl2"
        pl.mkdir()
        with open(pl / "l.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Track URI", "Track Name", "Artist Name(s)", "Duration (ms)", "Added At", "Energy", "Tempo"])
            w.writerow(["spotify:track:1", "Alpha Song", "Alpha Artist", 3000, "2026-10-30T00:00:00Z", 0.9, 150.0])
        cfg2 = dict(cfg, playlist_dir=str(pl))
        songs2, un2, _c = M.song_pool(cfg2)
        by = {Path(s["path"]).name: s for s in songs2}
        check(len(songs2) == 3 and not by["Alpha Artist - Alpha Song.mp3"].get("no_csv") and by["Alpha Artist - Alpha Song.mp3"]["csv_bpm"] == 150.0, "a CSV with one row: that song keeps its CSV values")
        check(by["Beta Song - Beta Artist.mp3"].get("no_csv") and by["just a name.mp3"].get("no_csv"), "the files without a row are normal songs too (every mode)")
        # the log wording
        an = {"energy": [0.5] * 10, "bpm": 128, "drop_strength": 0.3, "drops": [], "steady": 0.8}
        _n, why = M.auto_style(an, {"energy": None}, random.Random(1))
        _n2, why2 = M.auto_style(an, {"energy": 0.7}, random.Random(1))
        check("(analysis)" in why and "(CSV)" not in why and "(CSV)" in why2, "the style line says (analysis) for a song without CSV data and (CSV) for one with it")
        # the picker handles a song with no CSV fields
        real_gs, real_pf = M.get_songmap, M.songmap_prefetch
        fake = {"energy": [0.6] * 20, "steady": 0.9, "drop_strength": 0.5, "bpm_fit": 1.0, "bpm": 128.0, "dur": 120.0, "beats": [0.5, 1.0], "drops": []}
        M.get_songmap, M.songmap_prefetch = (lambda p, c=None, v=None: dict(fake)), (lambda *a, **k: None)
        try:
            s, an2, info, runners = M.pick_song(cfg, "valorant", songs)
        finally:
            M.get_songmap, M.songmap_prefetch = real_gs, real_pf
        check(s.get("no_csv") and info["fit"] > 0, f"pick_song scores and picks a song with no CSV fields ({Path(s['path']).name}, fit {info['fit']})")


def part3():
    with section("3) no CSV: setup check and Settings wording"):
        sc = (ROOT / "setup_check.py").read_text(encoding="utf-8")
        check("(optional)" in sc and 'bad(f"no Exportify CSV' not in sc and 'bad(f"Exportify CSV folder not found' not in sc, "setup_check no longer reports a missing CSV as a problem")
        src = (ROOT / "montage.py").read_text(encoding="utf-8")
        check('"Playlist CSV folder (optional)"' in src and '"Exportify CSV folder"' not in src, "Settings: 'Playlist CSV folder (optional)'")
        check(M.match_flag("/x.mp3", None, 0) == "not in CSV" and M.match_flag("/x.mp3", None, 0, csv_on=False) == "" and M.match_flag("/x.mp3", {"a": 1}, 100) == "ok", "flags: 'not in CSV' (not NO MATCH) with a CSV, none without")


def part4():
    with section("4) published montages"):
        data, lib, root = TMP / "pdata", TMP / "clips", TMP / "pub"
        data.mkdir()
        (lib / "a").mkdir(parents=True)
        (lib / "b").mkdir()
        files, hashes = [], {}
        for i in range(5):
            f = lib / ("a" if i < 3 else "b") / f"Clip {i}.mp4"
            f.write_bytes(os.urandom(2000 + i))
            files.append(str(f))
            hashes[str(f)] = hashlib.md5(f.read_bytes()).hexdigest()
        other = lib / "a" / "Not in montage.mp4"
        other.write_bytes(os.urandom(777))
        plan = {"game": "valorant", "headline": "h", "song": {"title": "S", "path": "s.mp3"},
                "takes": [{"path": files[0], "dur": 3}, {"path": files[1], "dur": 3, "srcs": [{"path": files[1]}, {"path": files[2]}]}, {"path": files[3], "dur": 3}, {"path": files[4], "dur": 3}]}
        video = TMP / "out" / "Valorant" / "V_VAL_V9.5.5_2026-11-02.mp4"
        video.parent.mkdir(parents=True)
        video.write_bytes(b"x")
        P.save_record(data, plan, video)
        rec = P.find_record(data, video)
        check(rec and sorted(rec["clips"]) == sorted(files) and rec["game"] == "valorant" and rec["song"] == "S", "the record lists the 5 clip files really in the cut list (stitched take's files included), game, song")
        check(str(other) not in rec["clips"], "a clip that was not placed is not in the record")
        pv = P.preview(data, rec, str(root), M.GAME_DIR)
        check(len(pv["moves"]) == 5 and all(os.path.exists(f) for f in files) and not root.exists() and not (data / P.PUB_FILE).exists(), "the PREVIEW lists 5 clips and changes nothing (no file moved, no folder, no record written)")
        # a record rebuilt from the log (older montage, no plan.json)
        video2 = TMP / "out" / "Valorant" / "Old_montage.mp4"
        video2.write_bytes(b"y")
        names = [Path(f).name for f in files[:3]]
        (data / "logs").mkdir()
        log = ["2026-10-01 10:00:00 something", "CUT LIST (3 takes)"] + [f"  {i + 1}.   0.00s  252f [calm    ] first kill @  0.60s tail 0.48s  3k  {n} @ 0:09.0, 0:12.0   | game -9.2 dB" for i, n in enumerate(names)]
        log += ["", f"2026-10-01 10:30:00 rendered {video2} (100.00 s = plan 100.00 s)", f"2026-10-01 10:30:01 rendered {video2}"]
        (data / "logs" / "montage.log").write_text("\n".join(log) + "\n", encoding="utf-8")
        rec2 = P.find_record(data, video2, files + [str(other)])
        check(rec2 and rec2["source"] == "montage.log" and sorted(rec2["clips"]) == sorted(files[:3]), "an older montage: the clip list is rebuilt from the cut list printed before its 'rendered' line")
        dup = lib / "b" / "Clip 0.mp4"
        dup.write_bytes(b"z")
        rec3 = P.find_record(data, video2, files + [str(other), str(dup)])
        check(len(rec3["clips"]) == 2 and rec3["unresolved"] == ["Clip 0.mp4"], "a file name that exists twice in the library is never guessed (listed as unresolved)")
        dup.unlink()
        # a name collision in the target folder never overwrites
        (root / "Valorant").mkdir(parents=True)
        (root / "Valorant" / "Clip 0.mp4").write_bytes(b"already here")
        res = P.apply(data, rec, str(root), M.GAME_DIR)
        check(len(res["moved"]) == 5 and not res["failed"] and not any(os.path.exists(f) for f in files), "Apply moved the 5 clips")
        check((root / "Valorant" / "Clip 0.mp4").read_bytes() == b"already here" and (root / "Valorant" / "Clip 0 (2).mp4").exists(), "a name that is taken gets a suffix, the file there is untouched")
        check(other.exists(), "the clip that was not in the montage stays where it is")
        pub = json.loads((data / P.PUB_FILE).read_text(encoding="utf-8"))
        check(len(next(iter(pub["montages"].values()))["moves"]) == 5, "a record of every moved clip (original path, new path)")
        check(all(P.is_published(data, f) for f in files) and not P.is_published(data, str(other)), "the moved clips are excluded, the other clip is not")
        again = lib / "a" / "Clip 1.mp4"
        again.write_bytes(os.urandom(2001))
        check(P.is_published(data, str(again)), "a copy of a published clip that appears in a scanned folder again is still excluded (same name and size)")
        again.unlink()
        check(len(P.keep_cache_keys(data)) == 5, "the scan cache keeps the entries of the moved clips (nothing to analyse again on Unmark)")
        # the scan must not list them, and must not enter the published folder
        cfgw = dict(M.DEFAULT_CONFIG, output_root=str(TMP / "out"), published_dir=str(root))
        listed = list(M.walk_files([str(TMP)], {".mp4"}, 0, cfgw))
        check(not any(str(root) in p for p in listed), "walk_files never enters the published folder")
        # Unmark
        res = P.unmark(data, str(video))
        check(len(res["restored"]) == 5 and all(os.path.exists(f) and hashlib.md5(Path(f).read_bytes()).hexdigest() == hashes[f] for f in files), "Unmark: the 5 files are back at their ORIGINAL paths, byte for byte")
        check(not P.excluded(data)[0] and not any(P.is_published(data, f) for f in files), "the exclusion is lifted")
        check(json.loads((data / P.PUB_FILE).read_text(encoding="utf-8"))["montages"] == {}, "the record of the montage is gone")
        lg = (data / "logs" / P.LOG_NAME).read_text(encoding="utf-8")
        check(lg.count("APPLY ") >= 5 and lg.count("UNMARK ") >= 5, "every Apply and Unmark is in the log")
        # Unmark never overwrites a file that took the original place
        P.apply(data, rec, str(root), M.GAME_DIR)
        Path(files[0]).write_bytes(b"new owner")
        res = P.unmark(data, str(video))
        check(Path(files[0]).read_bytes() == b"new owner" and len(res["failed"]) == 1 and len(res["restored"]) == 4, "Unmark does not overwrite a file that is at the original path (that clip stays excluded)")
        pv2 = P.preview(data, rec, str(root), M.GAME_DIR)
        check(len(pv2["already"]) == 1, "...and a second Apply would not move it again")


def part5():
    with section("5) the Songs tab with and without a CSV (needs a display)"):
        try:
            import tkinter  # noqa: F401
            tkinter.Tk().destroy()
        except Exception as ex:
            check(False, f"no display / tkinter: {ex}")
            return
        lib = TMP / "songs5"
        lib.mkdir()
        mp3(lib / "Alpha Artist - Alpha Song.mp3", 3, 250)
        mp3(lib / "Loose File.mp3", 4, 400)
        pl = TMP / "pl5"
        pl.mkdir()
        with open(pl / "l.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Track URI", "Track Name", "Artist Name(s)", "Duration (ms)", "Added At"])
            w.writerow(["spotify:track:1", "Alpha Song", "Alpha Artist", 3000, "2026-10-30T00:00:00Z"])
            w.writerow(["spotify:track:2", "Missing Song", "Nobody", 5000, "2026-10-30T00:00:00Z"])
        real_sc, real_eb = M.scan_clips, M.ensure_bars
        M.scan_clips = lambda cfg, rescan=False: []
        M.ensure_bars = lambda cfg, force=False: None
        try:
            for use_csv in (False, True):
                cfg = dict(M.load_config(), mp3_dir=str(lib), playlist_dir=str(pl) if use_csv else "", clip_dirs={"valorant": [], "cs2": []}, song_overrides={}, output_root=str(TMP / "o5"))
                M.save_json(M.CONFIG_PATH, cfg)
                app = M.App(0)
                root = app.root
                try:
                    app.nb.select(app.tabs["Songs"])
                    app.run_task("matches", app.load_matches)
                    for _ in range(400):
                        root.update()
                        time.sleep(0.03)
                        if not app.busy and not app.pending and getattr(app, "_matched_once", False):
                            break
                    for _ in range(40):
                        root.update()
                        time.sleep(0.03)
                    rows = [(i, app.mtree.item(i, "text"), app.mtree.set(i, "flag")) for i in app.mtree.get_children()]
                    dc = list(app.mtree["displaycolumns"])
                    txt = " ".join(str(x) for x in (app.s_head.get(), app.m_info.get(), [app.mtree.heading(c)["text"] for c in app.mtree["columns"] if c in dc]))
                    if use_csv:
                        flags = {Path(i).name: f for i, n, f in rows if not i.startswith("csv:")}
                        check(flags.get("Loose File.mp3") == "not in CSV" and "NO MATCH" not in [f for _i, _n, f in rows], f"with a CSV: a song without a row shows 'not in CSV' (no NO MATCH) {flags}")
                        check("track" in dc and "flag" in dc and any(n == "(no MP3)" for _i, n, _f in rows), "with a CSV: the track / score / flag columns and the '(no MP3)' rows are there")
                        check(app.m_bar2.winfo_manager() != "", "with a CSV: Download new songs / covers and tags are shown")
                    else:
                        check(len(rows) == 2 and not any(n == "(no MP3)" for _i, n, _f in rows) and all(f == "" for _i, _n, f in rows), f"no CSV: the folder's songs are listed directly, no '(no MP3)' rows, no flags ({rows})")
                        check("track" not in dc and "score" not in dc and "flag" not in dc and "Matched playlist track" not in txt, f"no CSV: no track / score / flag columns ({dc})")
                        check(not any(w in txt.lower() for w in ("spotify", "playlist", "csv", "no match")), f"no CSV: neutral words only ({app.s_head.get()!r} / {app.m_info.get()!r})")
                        check(app.m_bar2.winfo_manager() == "" and app.m_open_csv.winfo_manager() == "", "no CSV: the CSV tools (Download new songs, covers and tags, Open song_matches.csv) are hidden")
                        check(app.m_trash_col == "#%d" % (dc.index("trash") + 1), "no CSV: the trash click column follows the hidden columns")
                finally:
                    try:
                        root.destroy()
                    except Exception:
                        pass
        finally:
            M.scan_clips, M.ensure_bars = real_sc, real_eb


if __name__ == "__main__":
    for k, fn in (("0", part0), ("1", part1), ("2", part2), ("3", part3), ("4", part4), ("5", part5)):
        if k in PARTS:
            fn()
    print("ALL OK" if not FAILS else f"FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)
