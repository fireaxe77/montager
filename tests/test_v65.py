"""V6.5 song matching (no render):  python3 test_v65.py   (xvfb-run -a for the GUI part)
A file matches a playlist track only when title AND artist agree."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="montager_v65_"))
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))   # repo root (the file lives in tests/)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import montage as M

FAILS = []


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def R(title, artist, k):
    return {"title": title, "artist": artist, "uri": f"u{k}", "dur": 0, "added": "", "tempo": 0.0}


def A(stem, size=5000, title="", artist=""):
    p = f"/songs/{stem}.mp3"
    return {"path": p, "title": title, "artist": artist, "dur": 0, "key": f"{p}|{size}|1700000000"}


def run(rows, audio, cfg=None):
    m, u = M.match_playlist(rows, audio, cfg or M.load_config())
    return {Path(a["path"]).stem: (r["title"], r["artist"], sc, M.match_flag(a["path"], r, sc)) for r, a, sc in m}, m, u


def main():
    cfg = M.load_config()
    cfg.pop("song_overrides", None)
    rows = [R("Atlantis", "Florian, overrated", 0), R("Airhead - S3rl Remix", "DJ Brisk, S3RL", 1), R("Stay", "iamjakehill", 2),
            R("Отпускай", "Три дня дождя", 3),
            R("Беги от меня", "Три дня дождя", 4),
            R("Я САМАЯ", "MIA BOYKA", 5), R("Vertigo", "Florian", 6), R("Everytime", "LIZOT, Rivendale, Axel Cooper", 7),
            R("Stay", "Other Artist", 8)]
    audio = [A("Atlantis - Florian, overrated"), A("Airhead - S3rl Remix - DJ Brisk, S3RL"), A("Stay - iamjakehill"),
             A("Отпускай - Три дня дождя"),
             A("Беги от меня - Три дня дождя"),
             A("American Dream - Mia Vaile"), A("Stay - Other Artist"), A("Unrelated Song - Nobody")]
    res, m, u = run(rows, audio, cfg)
    want = {"Atlantis - Florian, overrated": "Atlantis", "Airhead - S3rl Remix - DJ Brisk, S3RL": "Airhead - S3rl Remix", "Stay - iamjakehill": "Stay",
            "Отпускай - Три дня дождя": "Отпускай",
            "Беги от меня - Три дня дождя": "Беги от меня"}
    for stem, title in want.items():
        got = res.get(stem)
        check(bool(got) and got[0] == title and got[2] == 100 and got[3] == "ok", f"{stem!r} -> {title!r} ok / 100 (got {got})")
    check(res.get("Atlantis - Florian, overrated", (0,))[1] == "Florian, overrated", "Atlantis keeps its own artist list")
    check(res.get("Stay - Other Artist", (None,))[0] == "Stay" and res["Stay - Other Artist"][1] == "Other Artist" and res["Stay - iamjakehill"][1] == "iamjakehill",
          "two tracks with the same title by different artists each get their own file")
    check("American Dream - Mia Vaile" not in res, "'American Dream - Mia Vaile' never matches 'Я САМАЯ - MIA BOYKA'")
    check("Unrelated Song - Nobody" not in res and M.match_flag("/songs/Unrelated Song - Nobody.mp3", None, 0) == "NO MATCH", "a file with no playlist track is NO MATCH")
    check({r["title"] for r in u} >= {"Vertigo", "Everytime", "Я САМАЯ"}, "tracks without a file stay unmatched (no leftover assignment)")
    check(all(sc == 100 for _, _, sc in m), "score 100 only for exact title + artist (no 85 / fuzzy scores)")
    # artist alone / title alone never match
    r2, _, _ = run([R("Vertigo", "Florian", 0)], [A("Atlantis - Florian")], cfg)
    check(not r2, "same artist, different title: NO MATCH")
    r2, _, _ = run([R("Stay", "Somebody", 0)], [A("Stay - Else")], cfg)
    check(not r2, "same title, different artist: NO MATCH")
    # CHECK: artist matches, title equal after removing suffixes
    r2, _, _ = run([R("Song (feat. X)", "Artist", 0), R("Other - Radio Edit", "Artist", 1)], [A("Song - Artist"), A("Other - Artist")], cfg)
    check(r2.get("Song - Artist", (0, 0, 0, ""))[3] == "CHECK (under 85)" and r2.get("Other - Artist", (0, 0, 0, ""))[3] == "CHECK (under 85)",
          f"suffix differences are CHECK (under 85): {r2}")
    # duplicates: the larger file wins, the other is flagged
    d_rows = [R("Atlantis", "Florian", 0)]
    d_audio = [A("Atlantis - Florian", size=1000), A("Atlantis - Florian", size=9000)]
    d_audio[1]["path"] = "/songs/Atlantis - Florian (copy)/Atlantis - Florian.mp3"
    d_audio[1]["key"] = d_audio[1]["path"] + "|9000|1700000000"
    res, m, u = run(d_rows, d_audio, cfg)
    big, small = d_audio[1]["path"], d_audio[0]["path"]
    check(len(m) == 1 and m[0][1]["path"] == big and small in M.SONG_DUPS and M.match_flag(small, None, 0) == "DUPLICATE",
          "two files for one track: the larger is kept, the other is flagged DUPLICATE")
    # normalisation: NFKC, quotes, dashes, case; non-Latin kept
    check(M.norm_song("Don’t – Stop") == "don't - stop" and M.norm_song("ＡＢＣ") == "abc", "NFKC / casefold / quote and dash unification")
    jp = "夜に駆ける"
    check(M.norm_song(jp) == jp and M.norm_song("Беги") == "беги", "Japanese and Cyrillic text is kept")
    r2, _, _ = run([R(jp, "YOASOBI", 0)], [A(f"{jp} - YOASOBI")], cfg)
    check(r2.get(f"{jp} - YOASOBI", (0, 0, 0, ""))[3] == "ok", "a Japanese title matches")
    # tags are used when the name cannot be parsed
    r2, _, _ = run([R("Stay", "iamjakehill", 0)], [A("track01", title="Stay", artist="iamjakehill")], cfg)
    check(r2.get("track01", (0, 0, 0, ""))[3] == "ok", "ID3 tags are used when the file name has no ' - '")
    # manual matches survive and the cache version change
    d = Path(tempfile.mkdtemp(prefix="mt_v65_"))
    M.AUDIO_CACHE, M.MATCH_CACHE = d / "audio_cache.json", d / "match_cache.json"
    import csv as _csv
    with open(d / "playlist.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(["Track URI", "Track Name", "Artist Name(s)", "Added At", "Duration (ms)", "Tempo"])
        w.writerow(["spotify:track:1", "Atlantis", "Florian", "", 0, 120])
        w.writerow(["spotify:track:2", "Vertigo", "Florian", "", 0, 120])
    old = __import__("time").time() - 3600
    paths = []
    for stem in ("Atlantis - Florian", "Weird Name"):
        p = d / f"{stem}.mp3"
        p.write_bytes(b"\0" * 3000)
        os.utime(p, (old, old))
        paths.append(str(p))
    cfg2 = dict(M.load_config(), mp3_dir=str(d), playlist_dir=str(d), output_root=str(d / "_out"),
                song_overrides={paths[1]: "spotify:track:2"})
    M.AUDIO_STABLE_WAIT_S = 0.05
    audio2 = M.scan_audio(cfg2)
    csvp, rows2, _ = M.read_playlist(cfg2)
    M.save_json(M.MATCH_CACHE, {"v": 1, "csv": [csvp.name, 0, 0], "folder": M._folder_sig(audio2), "ov": "x",
                                "pairs": [{"a": audio2[0]["key"], "r": "spotify:track:2", "s": 100}]})        # an old-version cache with a wrong match
    m, u, st = M.match_cached(cfg2, csvp, rows2, audio2)
    got = {Path(a["path"]).stem: r["title"] for r, a, sc in m}
    check(st == "full" and got.get("Atlantis - Florian") == "Atlantis", f"the old cache version is ignored and recomputed once (state {st}, {got})")
    check(got.get("Weird Name") == "Vertigo", "a manual match (Change match) survives the cache version change")
    m, u, st = M.match_cached(cfg2, csvp, rows2, audio2)
    check(st == "hit" and {Path(a["path"]).stem: r["title"] for r, a, sc in m} == got, "the new cache is a hit afterwards with the same matches")
    print("\nFAILED: %d" % len(FAILS) if FAILS else "\nALL OK")
    return 1 if FAILS else 0


sys.exit(main())
