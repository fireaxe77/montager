"""V6.1.2 checks (no render, no smoketest):  xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v612.py [workers audio match theme]
Without arguments every section runs. Exit code 1 when anything fails."""
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="montager_v612_"))
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))   # repo root (the file lives in tests/)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tkinter as tk

import montage as M

MOD = M

FAILS = []


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


# ---------------------------------------------------------------- 1a: workers never touch Tk
def t_workers():
    print("[1a] workers never touch Tk during startup")
    main = threading.main_thread()
    bad = []
    orig = {}

    def guard(cls, name):
        fn = getattr(cls, name)
        orig[(cls, name)] = fn

        def w(self, *a, **k):
            if threading.current_thread() is not main and threading.current_thread().name != "perf-sampler":
                bad.append(f"{cls.__name__}.{name} from {threading.current_thread().name}")
            return fn(self, *a, **k)
        setattr(cls, name, w)
    for nm in ("get", "set"):
        guard(tk.Variable, nm)
    for nm in ("configure", "cget", "winfo_exists", "after", "update_idletasks"):
        guard(tk.Misc, nm)
    guard(tk.Text, "insert")
    M.messagebox.askyesno = lambda *a, **k: False
    app = M.App(0)
    deadline = time.time() + 20
    while (app.busy or app.pending) and time.time() < deadline:
        app.root.update()
        time.sleep(0.02)
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)
    for (cls, name), fn in orig.items():
        setattr(cls, name, fn)
    app.flush_log()
    log = app.log.get("1.0", "end")
    check(not bad, "no worker thread called a Tk variable / widget method" + (": " + "; ".join(sorted(set(bad))[:5]) if bad else ""))
    check("ERROR in clips" not in log and "main thread is not in main loop" not in log, "the first clip load (load_clips) ran without an error")
    check(isinstance(getattr(app, "clips", None), list) and hasattr(app, "byp"), "load_clips handed its result to the UI (app.clips / byp set)")
    check(app._snap.get("m_game") in M.GAMES, f"m_game snapshot = {app._snap.get('m_game')}")
    app.root.destroy()


# ---------------------------------------------------------------- 1b: audio files that are still being written
def t_audio():
    print("[1b] scan_audio and files still being written")
    d = Path(tempfile.mkdtemp(prefix="mt_mp3_"))
    M.AUDIO_CACHE = d / "audio_cache.json"
    M.AUDIO_STABLE_WAIT_S = 0.3
    cfg = dict(M.load_config(), mp3_dir=str(d), output_root=str(d / "_out"))
    old = time.time() - 600
    stable = d / "Artist - Stable.mp3"
    stable.write_bytes(b"\0" * 5000)
    os.utime(stable, (old, old))
    fresh = d / "Artist - Fresh.mp3"
    fresh.write_bytes(b"\0" * 5000)                          # mtime = now
    empty = d / "Artist - Empty.mp3"
    empty.touch()
    os.utime(empty, (old, old))
    growing = d / "Artist - Growing.mp3"
    growing.write_bytes(b"\0" * 1000)
    os.utime(growing, (old, old))
    stop = threading.Event()

    def grow():
        while not stop.is_set():
            with open(growing, "ab") as f:
                f.write(b"\0" * 4096)
            time.sleep(0.05)
    th = threading.Thread(target=grow, daemon=True)
    th.start()
    try:
        recs = M.scan_audio(cfg)
    except Exception as ex:
        recs = None
        check(False, f"scan_audio raised {type(ex).__name__}: {ex}")
    stop.set()
    th.join()
    names = sorted(Path(r["path"]).name for r in (recs or []))
    check(names == ["Artist - Stable.mp3"], f"only the stable file is returned: {names}")
    cache = json.loads(M.AUDIO_CACHE.read_text(encoding="utf-8"))
    check(len(cache) == 1 and all(Path(v["path"]).name == "Artist - Stable.mp3" for v in cache.values()), "only the stable file is cached (no partial file)")
    check(recs and recs[0].get("key") in cache, "the stored key is the cache key (computed once)")
    # a file that disappears between listing and reading must not raise
    real_stat = os.stat
    gone = str(stable)
    calls = {"n": 0}

    def flaky(p, *a, **k):
        if str(p) == gone:
            calls["n"] += 1
            if calls["n"] > 1:
                raise FileNotFoundError(p)
        return real_stat(p, *a, **k)
    os.stat = flaky
    try:
        r2 = M.scan_audio(cfg)
        check(True, f"a file that vanishes after listing does not raise ({len(r2)} record(s))")
    except Exception as ex:
        check(False, f"vanishing file raised {type(ex).__name__}: {ex}")
    finally:
        os.stat = real_stat
    os.utime(fresh, (old, old))                              # no longer fresh -> picked up next time
    r3 = M.scan_audio(cfg)
    check("Artist - Fresh.mp3" in [Path(r["path"]).name for r in r3], "a skipped file is picked up on the next run")


def gen_data(n_tracks, n_files, seed, hard=False):
    import random
    rnd = random.Random(seed)
    words = [w for w in "love night fire heart dream light dark rain sun moon star road home time life world city sky ocean wind gold silver ghost angel devil summer winter blue red black white wild free lost found broken golden crazy sweet bitter slow fast high low deep cold warm river mountain shadow echo midnight morning thunder paradise".split()]
    syl = ["ka", "vo", "ri", "ten", "mar", "lu", "sho", "ped", "quin", "zar", "bel", "dro", "fim", "gus", "hal", "jun", "nor", "pex", "sab", "tuv", "wix", "yor"]
    rare = set()
    while len(rare) < 4200:
        rare.add("".join(rnd.choices(syl, k=rnd.choice((3, 4)))))
    junkw = ["qq" + w for w in sorted(rare)[:300]]                # vocabulary only unrelated files use
    words += sorted(rare)[300:1500]                               # long tail of rare words
    weights = [1.0 / (1 + k) ** 0.9 for k in range(len(words))]
    uniq = sorted(rare)[1500:]
    rnd.shuffle(uniq)
    artists = [" ".join(rnd.choices(words[40:], k=rnd.choice((1, 2)))).title() for _ in range(350)]
    rows = []
    for k in range(n_tracks):
        title = " ".join(rnd.choices(words, weights=weights, k=rnd.choice((1, 2, 2, 3, 4)))).title()
        if not hard:                                             # tie-free data: every title is unique (the old assignment breaks ties arbitrarily)
            title += " " + uniq.pop().title()
        if rnd.random() < 0.08:
            title += " (feat. " + rnd.choice(artists) + ")"
        rows.append({"title": title, "artist": rnd.choice(artists), "added": "", "uri": f"spotify:track:{k}", "dur": rnd.uniform(120, 300),
                     "tempo": 0.0, "energy": None, "dance": None})
    audio = []
    for f in range(n_files):
        if f < int(n_files * 0.85):
            r = rows[rnd.randrange(n_tracks)] if (f >= n_tracks or (hard and rnd.random() < 0.3)) else rows[f]
            t = r["title"]
            kind = rnd.random()
            if kind < 0.35:
                stem = f"{r['artist']} - {t}"
            elif kind < 0.55:
                stem = f"{rnd.randint(1, 99):02d} {t}"
            elif kind < 0.7:
                stem = f"{t} (Official Video)"
            elif kind < 0.8:
                stem = f"{t} - {r['artist']}"
            else:
                stem = t
            dur = r["dur"] + rnd.choice((0, 0, 1, 5))
        else:
            if hard:                                         # junk that shares vocabulary with real tracks
                stem = " ".join(rnd.choices(words, weights=weights, k=rnd.choice((2, 3)))).title() + f" {rnd.randint(0, 9)}"
            else:                                            # unrelated files
                stem = "Unknown " + " ".join(rnd.sample(junkw, 2)) + " Recording"
            dur = rnd.uniform(100, 320)
        audio.append({"path": f"/songs/{f:05d} {stem}.mp3".replace("/songs/%05d " % f, "/songs/"), "artist": "", "title": "", "dur": dur})
    return rows, audio


def t_match():
    print("[2] song matcher (unchanged v6.2 algorithm): titles must match, not only the artist")
    cfg = M.load_config()
    art = "\u0422\u0440\u0438 \u0434\u043d\u044f \u0434\u043e\u0436\u0434\u044f"
    songs = ["\u0411\u0435\u0433\u0438 \u043e\u0442 \u043c\u0435\u043d\u044f", "\u041e\u0442\u043f\u0443\u0441\u043a\u0430\u0439", "\u0414\u043e\u0440\u043e\u0433\u0438",
             "\u0421\u0435\u0440\u0434\u0446\u0435", "\u041d\u043e\u0447\u044c"]
    mk_r = lambda t, k: {"title": t, "artist": art, "dur": 0, "uri": f"u{k}"}
    mk_a = lambda stem: {"path": f"/s/{stem}.mp3", "title": "", "artist": "", "dur": 0}
    # the two reported songs
    rows = [mk_r(songs[0], 0), mk_r(songs[1], 1)]
    audio = [mk_a(f"{songs[1]} - {art}"), mk_a(f"{songs[0]} - {art}")]               # file order differs from the CSV order
    m, u = M.match_playlist(rows, audio, cfg)
    ok = len(m) == 2 and all(Path(a["path"]).name.startswith(r["title"]) for r, a, sc in m)
    check(ok, "each track matches the file with the same title (two songs of one artist): " + "; ".join(f"{r['title']} <- {Path(a['path']).name} ({sc})" for r, a, sc in m))
    # a whole album of one artist, shuffled files
    rows = [mk_r(t_, k) for k, t_ in enumerate(songs)]
    audio = [mk_a(f"{t_} - {art}") for t_ in reversed(songs)]
    m, u = M.match_playlist(rows, audio, cfg)
    check(len(m) == 5 and all(Path(a["path"]).name.startswith(r["title"]) for r, a, sc in m), "5 songs of one artist, files in another order: all 5 match their own title")
    # artist only is not enough: a file of the same artist but another title must not reach 100 against this track
    m, u = M.match_playlist([mk_r(songs[1], 1)], [mk_a(f"{songs[0]} - {art}")], cfg)
    check(not m or m[0][2] < 100, f"same artist, different title: score {m[0][2] if m else 'no match'} (< 100)")
    m, u = M.match_playlist([mk_r(songs[0], 0)], [mk_a(f"{songs[0]} - {art}")], cfg)
    check(m and m[0][2] == 100, "exact artist + title: 100")
    # ID3 title tag instead of the file name
    m, u = M.match_playlist([mk_r(songs[0], 0), mk_r(songs[1], 1)], [dict(mk_a("track02"), title=songs[1], artist=art), dict(mk_a("track01"), title=songs[0], artist=art)], cfg)
    check(len(m) == 2 and all(a["title"] == r["title"] and sc == 100 for r, a, sc in m), "ID3 title + artist tags decide (exact rule) when the file name cannot be parsed")
    # Cyrillic / Japanese text is kept by the normaliser
    check(M.clean(songs[0]) == songs[0].lower(), "Cyrillic text is not stripped by clean()")
    jp = "\u65e5\u672c\u8a9e\u306e\u30bf\u30a4\u30c8\u30eb (Official Video)"
    check(M.clean(jp) == "\u65e5\u672c\u8a9e\u306e\u30bf\u30a4\u30c8\u30eb", f"Japanese text is not stripped by clean(): {M.clean(jp)}")
    rows = [{"title": "\u591c\u306b\u99c6\u3051\u308b", "artist": "YOASOBI", "dur": 0, "uri": "j0"}, {"title": "\u30a2\u30a4\u30c9\u30eb", "artist": "YOASOBI", "dur": 0, "uri": "j1"}]
    audio = [mk_a("\u30a2\u30a4\u30c9\u30eb - YOASOBI"), mk_a("\u591c\u306b\u99c6\u3051\u308b - YOASOBI")]
    m, u = M.match_playlist(rows, audio, cfg)
    check(len(m) == 2 and all(Path(a["path"]).name.startswith(r["title"]) for r, a, sc in m), "Japanese titles of one artist match their own file")


def make_library(n, seed=5, name="lib"):
    """A CSV + mp3 files (old mtimes) in a temp folder; returns (dir, cfg, rows, paths)."""
    import csv as _csv
    d = Path(tempfile.mkdtemp(prefix=f"mt_{name}_"))
    rows, audio = gen_data(n, n, seed)
    old = time.time() - 3600
    with open(d / "playlist.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.writer(f)
        w.writerow(["Track URI", "Track Name", "Artist Name(s)", "Added At", "Duration (ms)", "Tempo"])
        for r in rows:
            w.writerow([r["uri"], r["title"], r["artist"], "2026-09-01T10:00:00Z", int(r["dur"] * 1000), 120])
    paths = []
    for a in audio:
        stem = Path(a["path"]).stem
        p = d / (re.sub(r'[\\/:*?"<>|]', "", stem) + ".mp3")
        p.write_bytes(b"\0" * 3000)
        os.utime(p, (old, old))
        paths.append(p)
    cfg = dict(M.load_config(), mp3_dir=str(d), playlist_dir=str(d), output_root=str(d / "_out"))
    return d, cfg, rows, paths


def t_cache():
    print("[2c] match cache: hit / stale / incremental")
    d, cfg, rows, paths = make_library(300)
    M.AUDIO_CACHE, M.MATCH_CACHE = d / "audio_cache.json", d / "match_cache.json"
    M.AUDIO_STABLE_WAIT_S = 0.05
    calls = []
    real = M.match_playlist

    def spy(r, a, c):
        calls.append((len(r), len(a)))
        return real(r, a, c)
    M.match_playlist = spy
    try:
        s0, _, _ = M.song_pool(cfg, cached_only=True)
        check(s0 == [] and M.SONG_STATE[0] == "none" and not calls, "no cache: cached_only returns an empty list, state none, matcher not run")
        t0 = time.time()
        s1, _, _ = M.song_pool(cfg)
        t1 = time.time() - t0
        exact_ok = all(re.sub(r'[\\/:*?"<>|]', "", f"{x['title']} - {x['artist']}") == Path(x["path"]).stem for x in s1)
        check(M.SONG_STATE[0] == "full" and len(calls) == 1 and len(s1) > 0 and exact_ok,
              f"first run: full match ({calls[-1]}), {len(s1)} songs, every one is a file named 'Title - Artist' of its own track ({t1:.2f}s)")
        calls.clear()
        t0 = time.time()
        s2, _, _ = M.song_pool(cfg)
        check(M.SONG_STATE[0] == "hit" and not calls, f"second run: cache hit, matcher not run ({time.time() - t0:.2f}s)")
        check(sorted((x["path"], x["title"]) for x in s1) == sorted((x["path"], x["title"]) for x in s2), "cache hit returns the same songs")
        # new files appear
        extra = []
        for k in range(3):
            p = d / f"Brand New Artist - Fresh Song {k} Zork.mp3"
            p.write_bytes(b"\0" * 3000)
            os.utime(p, (time.time() - 3000, time.time() - 3000))
            extra.append(p)
        s3, _, _ = M.song_pool(cfg, cached_only=True)
        check(M.SONG_STATE[0] == "stale" and not calls and len(s3) == len(s1), "files added: cached_only shows the cached matches (stale), no matching")
        s4, _, _ = M.song_pool(cfg)
        check(M.SONG_STATE[0] == "full" and calls == [(len(rows), len(paths) + 3)],
              f"files added: the exact matcher recomputes every match once (rows x files = {calls[-1] if calls else None})")
        old_map = {x["path"]: x["title"] for x in s1}
        check(all(old_map[p_] == t_ for p_, t_ in ((x["path"], x["title"]) for x in s4) if p_ in old_map), "incremental run keeps the earlier matches")
        calls.clear()
        M.song_pool(cfg)
        check(M.SONG_STATE[0] == "hit", "after the incremental run the cache is a hit again")
    finally:
        M.match_playlist = real


def t_firstshow():
    print("[2d] first show does not wait for the matcher")
    d, cfg, rows, paths = make_library(120, name="fs")
    M.AUDIO_CACHE, M.MATCH_CACHE = d / "audio_cache.json", d / "match_cache.json"
    M.AUDIO_STABLE_WAIT_S = 0.05
    M.save_json(M.CONFIG_PATH, cfg)
    real = M.match_playlist

    def slow(r, a, c):
        time.sleep(4)
        return real(r, a, c)
    M.match_playlist = slow
    M.messagebox.askyesno = lambda *a, **k: False
    try:
        t0 = time.time()
        app = M.App(0)
        t_show = time.time() - t0
        check(app._shown and t_show < 3.5, f"main window shown after {t_show:.2f}s although the matcher takes 4 s")
        check(app.busy, "the matcher is still running when the window is shown")
        info0 = app.m_info.get()
        check("Matching songs" in info0, f"status line says '{info0}'")
        n0 = len(app.stree.get_children())
        deadline = time.time() + 30
        while (app.busy or app.pending) and time.time() < deadline:
            app.root.update()
            time.sleep(0.02)
        for _ in range(10):
            app.root.update()
        n1 = len(app.stree.get_children())
        check(n1 > n0 and "matched" in app.m_info.get(), f"Songs list filled once the match finished ({n0} -> {n1} rows): {app.m_info.get()[:70]}")
        app.root.destroy()
    finally:
        M.match_playlist = real


def t_open():
    print("[open column] Manual clip list: '\u25b6 Open' cell and double-click")
    d = Path(tempfile.mkdtemp(prefix="mt_open_"))
    M.messagebox.askyesno = lambda *a, **k: False
    M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir=""))
    app = M.App(0)
    root = app.root
    root.geometry("1300x900+0+0")
    app.nb.select(app.tabs["Manual"])
    root.update()
    clip = d / "clip1.mp4"
    clip.write_bytes(b"\0" * 10)
    app.byp = {str(clip): {"path": str(clip), "name": "clip1.mp4", "kills": 2, "used": ""}}
    app.ctree.delete(*app.ctree.get_children())
    app.ctree.insert("", "end", iid=str(clip), text="clip1.mp4", values=("2026-01-01", "0:10", "2", "", "\u25b6 Open"))
    root.update()
    opened = []
    app.open_clip_player = lambda p: opened.append(p)
    tree = app.ctree
    check(tree.item(str(clip), "values")[-1] == "\u25b6 Open", "every row shows '\u25b6 Open' in the last column")
    x0, y0, w, h = tree.bbox(str(clip), app.OPEN_COL)
    tree.event_generate("<Button-1>", x=x0 + w // 2, y=y0 + h // 2)
    root.update()
    check(opened == [str(clip)] and str(clip) not in app.ticked, f"click on the Open cell opens the clip and does not tick the row ({opened})")
    tree.event_generate("<Button-1>", x=x0 + w // 2, y=y0 + h // 2)
    root.update()
    check(str(clip) not in app.ticked and len(opened) == 2, "a second click on the Open cell still does not tick it")
    xc, yc, wc, hc = tree.bbox(str(clip), "#0")
    tree.event_generate("<Button-1>", x=xc + 20, y=yc + hc // 2)
    root.update()
    check(str(clip) in app.ticked and len(opened) == 2, "a click on the clip name still ticks the row")
    app.ticked.clear()
    opened.clear()
    ev = type("E", (), {"x": xc + 20, "y": yc + hc // 2})()
    check(tree.bind("<Double-1>"), "<Double-1> is bound on the clip list")
    app.on_tree_double(ev)
    root.update()
    check(opened == [str(clip)], "double-click on a row opens the clip")
    # the real opener must not block: stub xdg-open
    app2_launch = M.App.open_clip_player
    import subprocess as sp
    calls = []
    real = sp.Popen
    sp.Popen = lambda *a, **k: calls.append((a, k))
    try:
        t0 = time.time()
        app2_launch(app, str(clip))
        check(calls and calls[0][0][0][0] == "xdg-open" and time.time() - t0 < 0.5, "open_clip_player starts xdg-open without waiting")
    finally:
        sp.Popen = real
    root.destroy()


# ---------------------------------------------------------------- 5: Sun Valley fixes that do not change the look
from tkinter import ttk

SEQ = [("lime", "grey"), ("yellow", "black"), ("orange", "grey"), ("red", "black"), ("pink", "grey"), ("purple", "black"),
       ("lime", "black"), ("yellow", "grey"), ("orange", "black"), ("red", "grey"), ("pink", "black"), ("purple", "grey")]


def t_theme():
    print("[5] Sun Valley: one <<ThemeChanged>> handler, each variant sourced once, classic widgets use the Sun Valley background")
    M.messagebox.askyesno = lambda *a, **k: False
    M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir="", accent="lime", base="grey"))
    built = []
    real = M.lime_theme_dir
    M.lime_theme_dir = lambda *a, **k: (built.append(a), real(*a, **k))[1]
    try:
        app = M.App(0)
    finally:
        pass
    root = app.root
    root.geometry("1400x900+0+0")
    root.update()
    st = ttk.Style(root)
    bad_cls, bad_pix, n = [], [], 0
    for rnd in range(2):
        for acc, base in SEQ:
            app.retheme(acc, base)
            for tab in app.tabs:
                app.nb.select(app.tabs[tab])
                root.update()
                time.sleep(0.15)
                root.update()
            sv_bg = str(st.lookup("TFrame", "background")).lower()
            pal = M.make_palette(acc, base)
            if sv_bg != pal["bg"].lower():
                bad_cls.append(f"{acc}/{base}: Sun Valley TFrame background {sv_bg} != app palette {pal['bg']}")
            for w in app._tk_widgets():
                role = app.role_of(w)
                if role in ("window", "label"):
                    n += 1
                    if str(w.cget("bg")).lower() != sv_bg:
                        bad_cls.append(f"{acc}/{base}: {w.winfo_class()} {w} bg={w.cget('bg')} want {sv_bg}")
            try:
                from PIL import ImageGrab
                img = ImageGrab.grab(xdisplay=os.environ.get("DISPLAY"))
                want = tuple(int(sv_bg[i:i + 2], 16) for i in (1, 3, 5))
                todo = [root]
                while todo:
                    w = todo.pop()
                    try:
                        todo.extend(w.winfo_children())
                        if w.winfo_class() in ("TLabel", "TFrame") and w.winfo_viewable() and w.winfo_width() > 12 and w.winfo_height() > 8:
                            x, y = w.winfo_rootx() + 1, w.winfo_rooty() + 1
                            if 0 <= x < img.width and 0 <= y < img.height and root.winfo_containing(x, y) is w and str(w.cget("style")) in ("", "TLabel", "TFrame"):
                                n += 1
                                px = img.getpixel((x, y))[:3]
                                if max(abs(a - b) for a, b in zip(px, want)) > 3:
                                    for _ in range(5):
                                        root.update()
                                        time.sleep(0.2)
                                    px2 = ImageGrab.grab(xdisplay=os.environ.get("DISPLAY")).getpixel((x, y))[:3]
                                    if max(abs(a - b) for a, b in zip(px2, want)) <= 3:
                                        bad_pix.append(f"(late redraw only: {px} -> {px2}) {w}")
                                        continue
                                    bad_pix.append(f"{acc}/{base}: {w.winfo_class()} {w} pixel {px} want {want} [text={str(w.cget('text'))[:25]!r} style={str(w.cget('style'))!r} lookup={st.lookup('TLabel', 'background')} geometry={w.winfo_rootx()},{w.winfo_rooty()} {w.winfo_width()}x{w.winfo_height()} tab={app._visible_tab() if hasattr(app, '_visible_tab') else app.nb.tab(app.nb.select(), 'text')}]")
                    except tk.TclError:
                        continue
            except ImportError:
                pass
    check(not bad_cls, f"classic tk widgets carry the Sun Valley background in all 12 combinations ({n} checks)" + (": " + "; ".join(bad_cls[:3]) if bad_cls else ""))
    check(not bad_pix, "screen pixels of ttk labels / frames equal the classic widgets' background (no black boxes)" + (": " + "; ".join(sorted({b.split(":")[0] + " x" + str(sum(1 for c in bad_pix if c.split(":")[0] == b.split(":")[0])) for b in bad_pix})) + " e.g. " + bad_pix[0] if bad_pix else ""))
    nb = str(root.tk.call("bind", "Tk", "<<ThemeChanged>>")).count("configure_colors")
    check(nb == 1, f"exactly one <<ThemeChanged>> -> configure_colors handler after 24 switches ({nb})")
    check(len(built) <= 12 and len({tuple(b) for b in built}) == len(built), f"each Sun Valley variant is built / sourced at most once ({len(built)} builds for {len(SEQ)} variants x 2 rounds)")
    root.destroy()
    M.lime_theme_dir = real


def t_length():
    print("[length] fixed length 80-150 s")
    for v, want in ((30, 80), (79, 80), (80, 80), (100, 100), (150, 150), (151, 150), (999, 150), ("optimal", "optimal")):
        M.save_json(M.CONFIG_PATH, dict(M.load_config(), length_s=v))
        got = M.load_config()["length_s"]
        check(got == want, f"saved length_s {v!r} loads as {got!r} (want {want!r})")
    M.messagebox.askyesno = lambda *a, **k: False
    M.save_json(M.CONFIG_PATH, dict(M.load_config(), length_s=60, mp3_dir=""))
    app = M.App(0)
    scales = []
    todo = [app.root]
    while todo:
        w = todo.pop()
        todo.extend(w.winfo_children())
        if w.winfo_class() == "TScale":
            scales.append((float(w.cget("from")), float(w.cget("to"))))
    check(len(scales) >= 2 and all(s == (80.0, 150.0) for s in scales), f"Manual and Settings sliders range {scales}")
    check(app.m_len is app.set_len and app.m_len.get() >= 80, f"the two sliders share one variable, value {app.m_len.get()}")
    app.m_opt.set(False)
    app.m_len.set(500)
    check(app.collect_settings(dict(app.cfg))["length_s"] == 150, "collect_settings clamps a too large value to 150")
    app.m_len.set(10)
    check(app.collect_settings(dict(app.cfg))["length_s"] == 80, "collect_settings clamps a too small value to 80")
    app.root.destroy()


# ---------------------------------------------------------------- 7: every window the app can open, normal mode and perflog mode
def _make_wav(path, secs=6, rate=22050):
    import math
    import struct
    import wave
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / rate) * (1 if (i // (rate // 2)) % 2 else 0.4)))
                               for i in range(rate * secs)))


def run_popups(mode):
    import subprocess as sp
    import numpy as np
    print(f"  -- {mode} mode")
    d = Path(tempfile.mkdtemp(prefix="mt_popups_"))
    errors = []
    M.messagebox.askyesno = lambda *a, **k: False
    M.messagebox.showinfo = lambda *a, **k: None
    M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir=str(d), playlist_dir=str(d), output_root=str(d / "_out")))
    app = M.App(0)
    root = app.root
    root.geometry("1300x900+0+0")
    root.update()
    root.report_callback_exception = lambda *a: errors.append("callback: " + "".join(traceback.format_exception(*a))[-400:])

    def pump(n=10, dt=0.05):
        for _ in range(n):
            root.update()
            time.sleep(dt)

    def toplevels():
        return [w for w in root.winfo_children() if w.winfo_class() == "Toplevel"]

    def attempt(name, fn, expect_window=True):
        before = set(map(str, toplevels()))
        try:
            fn()
            pump(4)
            new = [w for w in toplevels() if str(w) not in before]
            if expect_window and not new:
                errors.append(f"{name}: no window opened")
            for w in new:
                w.update_idletasks()
                w.destroy()
            pump(2)
            print(f"     {name}: opened {len(new)} window(s), closed")
        except Exception:
            errors.append(f"{name}: " + traceback.format_exc()[-500:])
            for w in toplevels():
                if str(w) not in before:
                    try:
                        w.destroy()
                    except Exception:
                        pass
    # generated media
    wav = d / "Song One.wav"
    _make_wav(wav)
    clip = d / "clip.mp4"
    sp.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=15:duration=2", "-pix_fmt", "yuv420p", str(clip)], check=True)
    attempt("Calibrate killfeed region", lambda: M.CalibDialog(app))
    attempt("Song map view", lambda: (M.SongMapView(app, str(wav), 120.0), pump(30)))
    attempt("Changelog", app.show_changelog)
    attempt("Date range", app.date_range_dialog)
    # track picker (Songs > Matches > Change match)
    rows = [{"title": "Track A", "artist": "Artist", "uri": "a", "dur": 0}, {"title": "Track B", "artist": "Artist", "uri": "b", "dur": 0}]
    app.match_rows = rows
    app.mtree.insert("", "end", iid=str(wav), text=wav.name, values=("", "", "", 0, "NO MATCH"))
    app.mtree.selection_set(str(wav))
    attempt("Track picker (change match)", app.change_match)
    # Troubleshoot > Clips: killfeed crop window and before/after bar preview
    app.ttree.insert("", "end", iid=str(clip), text=clip.name)
    app.ttree.selection_set(str(clip))
    real = {k: getattr(M, k) for k in ("load_dets", "analyse_clip", "load_kills_cache", "analyse_entry", "grab_kill_crop")}
    fake_det = type("D", (), {"d": {"stamp": "x"}})()
    fake_cache = type("K", (), {"get": lambda self, k, d=None: {"ocr": [(0, 0, [1])]}})()
    M.load_dets = lambda g=None: {g: fake_det}
    M.analyse_clip = lambda p, cache, rescan, bar: (None, {"path": p, "dur": 2.0})
    M.load_kills_cache = lambda: fake_cache
    M.analyse_entry = lambda e, cfg, g: {"kills": [{"t": 1.0}], "deaths": [], "rows_max": 1, "ocr_calls": 1, "best_k": 1.0, "best_v": 0.0, "mine": [], "rej": []}
    M.grab_kill_crop = lambda rec, det, cfg, pick: (np.zeros((120, 400, 3), np.uint8), [])
    try:
        attempt("Killfeed crop (Kill timestamps)", app.show_kills)
    finally:
        for k, v in real.items():
            setattr(M, k, v)
    attempt("Before / after bars preview", app.bar_preview)
    check(not errors, f"{mode}: every popup opens and closes without an exception" + (": " + " | ".join(e.replace(chr(10), " ")[-220:] for e in errors[:3]) if errors else ""))
    app.root.destroy()


def t_popups():
    print("[7] popups: every window the app can open")
    import traceback as tb
    globals()["traceback"] = tb
    run_popups("normal")
    M.PERF = M.PerfLog()
    M.PERF.install()
    run_popups("perflog")


SECTIONS = {"workers": t_workers, "audio": t_audio, "match": t_match, "cache": t_cache, "firstshow": t_firstshow, "open": t_open, "theme": t_theme, "length": t_length, "popups": t_popups}

if __name__ == "__main__":
    want = [a for a in sys.argv[1:] if not a.startswith("--")] or list(SECTIONS)
    for k in want:
        SECTIONS[k]()
    print("\nFAILED: %d" % len(FAILS) if FAILS else "\nALL OK")
    sys.exit(1 if FAILS else 0)
