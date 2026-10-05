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


# ---------------------------------------------------------------- 2b: the OLD matcher kept as the reference (V6.1: dense WRatio matrix + assignment)
def match_playlist_ref(rows, audio, cfg):
    """ONE-TO-ONE best global assignment of MP3 files to CSV rows. Each file (ID3 title if present, else the filename) is compared
    with 'Track', 'Artist - Track' and 'Track - Artist' using rapidfuzz WRatio; duration within 3 s adds a little."""
    import numpy as np
    from rapidfuzz import fuzz, process
    from scipy.optimize import linear_sum_assignment
    if not rows or not audio:
        return [], list(rows)
    names = []
    for a in audio:
        stem = re.sub(r"^\s*\d{1,3}[\s._-]+", "", Path(a["path"]).stem)
        names.append(MOD.clean(a.get("title", "")) or MOD.clean(stem) or stem.lower())
    t1 = [MOD.clean(r["title"]) or r["title"].lower() for r in rows]
    t2 = [MOD.clean(f"{r['artist']} - {r['title']}") for r in rows]
    t3 = [MOD.clean(f"{r['title']} - {r['artist']}") for r in rows]
    M = np.zeros((len(audio), len(rows)))
    for i, nm in enumerate(names):
        M[i] = np.maximum.reduce([process.cdist([nm], t, scorer=fuzz.WRatio)[0] for t in (t1, t2, t3)])
        da = audio[i].get("dur") or 0
        if da:
            for j, r in enumerate(rows):
                if r.get("dur") and abs(da - r["dur"]) <= 3:
                    M[i, j] += 2.0
    rk = lambda r: r.get("uri") or f"{r['artist']} - {r['title']}"
    idx = {a["path"]: i for i, a in enumerate(audio)}
    for path, key in cfg.get("song_overrides", {}).items():              # manual overrides from the Songs view
        i = idx.get(path)
        j = next((k for k, r in enumerate(rows) if rk(r) == key), None)
        if i is not None and j is not None:
            M[i, :], M[:, j] = -1, -1
            M[i, j] = 1000
    ri, ci = linear_sum_assignment(-M)
    matched, got = [], set()
    for i, j in zip(ri, ci):
        sc = M[i, j]
        if sc >= cfg.get("match_floor", 60):
            matched.append((rows[j], audio[i], int(min(sc, 100) if sc < 1000 else 100)))
            got.add(j)
    return matched, [r for j, r in enumerate(rows) if j not in got]


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
    print("[2b] match_playlist: new matcher vs the old algorithm (reference kept in this test)")
    cfg = M.load_config()
    for n, seed, hard in ((300, 1, False), (300, 2, False), (600, 3, False), (300, 4, True)):
        rows, audio = gen_data(n, n + n // 10, seed, hard)
        t0 = time.time()
        old_m, old_u = match_playlist_ref(rows, audio, cfg)
        t_old = time.time() - t0
        t0 = time.time()
        new_m, new_u = M.match_playlist(rows, audio, cfg)
        t_new = time.time() - t0
        so = sorted((r["uri"], a["path"], sc) for r, a, sc in old_m)
        sn = sorted((r["uri"], a["path"], sc) for r, a, sc in new_m)
        diff_ = set(so) ^ set(sn)
        same = len(set(so) & set(sn)) / max(1, len(set(so) | set(sn)))
        strict = (n, seed) == (300, 1)
        ok = (so == sn) if strict else (same >= 0.98 or hard)
        check(ok, f"{n} tracks x {len(audio)} files seed {seed}{' (HARD: duplicate files + junk sharing vocabulary; informational)' if hard else ''}: "
              f"{'identical' if so == sn else f'{len(diff_)} pair(s) differ ({same * 100:.1f} % identical)'} ({len(so)} matched); old {t_old:.2f}s new {t_new:.2f}s"
              + (f"; e.g. {sorted(diff_)[:2]}" if diff_ and not strict else ""))
        if strict:
            check(sorted(r["uri"] for r in old_u) == sorted(r["uri"] for r in new_u), f"{n}: identical unmatched list")

    rows, audio = gen_data(2000, 2000, 7)
    t0 = time.time()
    m, u = M.match_playlist(rows, audio, cfg)
    t_full = time.time() - t0
    check(t_full < 2.0, f"2000 tracks x 2000 files: {t_full:.2f}s (< 2 s), {len(m)} matched")
    if "--ref-full" in sys.argv:
        t0 = time.time()
        om, _ = match_playlist_ref(rows, audio, cfg)
        so = sorted((r["uri"], a["path"], sc) for r, a, sc in om)
        sn = sorted((r["uri"], a["path"], sc) for r, a, sc in m)
        same = len(set(so) & set(sn)) / max(1, len(set(so) | set(sn)))
        check(same >= 0.98, f"full 2000x2000: {same * 100:.1f} % of the pairs identical to the old algorithm ({len(set(so) ^ set(sn))} differ of {len(so)}; old took {time.time() - t0:.1f}s)")


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
        check(M.SONG_STATE[0] == "full" and len(calls) == 1 and len(s1) > 200, f"first run: full match ({calls[-1]}), {len(s1)} songs, {t1:.2f}s")
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
        check(M.SONG_STATE[0] == "incremental" and len(calls) == 1 and calls[0][1] < 100 and calls[0][0] < 100,
              f"files added: only new / unmatched files are matched (rows x files = {calls[-1] if calls else None} instead of {len(rows)} x {len(paths) + 3})")
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


# ---------------------------------------------------------------- 6: one palette, no leftover colours (every engine)
from tkinter import ttk

SEQ = [("lime", "grey"), ("yellow", "black"), ("orange", "grey"), ("red", "black"), ("pink", "grey"), ("purple", "black"),
       ("lime", "black"), ("yellow", "grey"), ("orange", "black"), ("red", "grey"), ("pink", "black"), ("purple", "grey")]
CLS_EXPECT = {"window": {"bg": "bg", "highlightbackground": "bg"}, "label": {"bg": "bg", "fg": "fg", "highlightbackground": "bg"},
              "text": {"bg": "field", "fg": "fg", "highlightbackground": "border"}, "entry": {"bg": "field", "fg": "fg", "highlightbackground": "border"},
              "pane": {"bg": "border"}}
CLS_ROLE = {"Tk": "window", "Toplevel": "window", "Frame": "window", "Canvas": "window", "Label": "label", "Text": "text",
            "Entry": "entry", "Spinbox": "entry", "Listbox": "text", "Panedwindow": "pane"}
# ttk style option -> palette key that EVERY engine must deliver (looked up through ttk.Style.lookup)
TTK_EXPECT = {"TFrame": {"background": "bg"}, "TLabel": {"background": "bg", "foreground": "fg"},
              "TCheckbutton": {"background": "bg", "foreground": "fg"}, "TRadiobutton": {"background": "bg", "foreground": "fg"},
              "TLabelframe": {"background": "bg"}, "TLabelframe.Label": {"background": "bg"}, "TNotebook": {"background": "bg"},
              "Dim.TLabel": {"foreground": "dim"}, "Section.TLabel": {"foreground": "acc"},
              "TEntry": {"foreground": "fg"}, "TCombobox": {"foreground": "fg"}, "Treeview": {"foreground": "fg"}}


def stale_counts(app, pal, engine, pixels=True):
    """(classic stale, ttk stale, pixel stale, widgets checked) for the CURRENT combination."""
    classic, ttkbad, pix, n = [], [], [], 0
    reg = getattr(app, "_reg", {})
    for w in app._tk_widgets():
        role = reg.get(str(w)) or CLS_ROLE.get(w.winfo_class())
        if role is None or role in ("fixed", "list", "menu"):
            continue
        for opt, key in CLS_EXPECT.get(role, {}).items():
            try:
                v = str(w.cget(opt)).lower()
            except tk.TclError:
                continue
            n += 1
            if v != pal[key].lower():
                classic.append(f"{w.winfo_class()} {w} {opt}={v} want {pal[key]}")
    st = ttk.Style(app.root)
    for style, opts in TTK_EXPECT.items():
        for opt, key in opts.items():
            n += 1
            v = str(st.lookup(style, opt)).lower()
            if v != pal[key].lower():
                ttkbad.append(f"{style} {opt}={v} want {pal[key]}")
    if pixels:
        try:
            from PIL import ImageGrab
            app.root.update()
            img = ImageGrab.grab(xdisplay=os.environ.get("DISPLAY"))
            want = tuple(int(pal["bg"][i:i + 2], 16) for i in (1, 3, 5))
            seen = 0
            for w in app._all_widgets() if hasattr(app, "_all_widgets") else []:
                pass
            todo = [app.root]
            while todo:
                w = todo.pop()
                try:
                    todo.extend(w.winfo_children())
                    cls = w.winfo_class()
                    if cls in ("TLabel", "TFrame") and w.winfo_ismapped() and w.winfo_viewable() and w.winfo_width() > 12 and w.winfo_height() > 8:
                        x, y = w.winfo_rootx() + 1, w.winfo_rooty() + 1
                        if not (0 <= x < img.width and 0 <= y < img.height) or app.root.winfo_containing(x, y) is not w:
                            continue                                 # clipped (scrolled page) or covered by a child: not a sample of this widget
                        px = img.getpixel((x, y))[:3]
                        seen += 1
                        n += 1
                        if str(w.cget("style")) in ("", "TLabel", "TFrame", "Dim.TLabel", "Section.TLabel") and max(abs(a - b) for a, b in zip(px, want)) > 3:
                            pix.append(f"{cls} {w} pixel {px} want {want}")
                except tk.TclError:
                    continue
            if seen == 0:
                pix.append("no mapped TLabel / TFrame found to sample")
        except ImportError:
            pass
    return classic, ttkbad, pix, n


def t_theme():
    print("[6] one palette: 12 combinations in ONE window, every engine")
    d = Path(tempfile.mkdtemp(prefix="mt_theme_"))
    M.messagebox.askyesno = lambda *a, **k: False
    engines = [e for e in ("fast", "lite", "full") if e in getattr(M, "THEME_ENGINES", {"fast": 1})] or ["fast"]
    for eng in engines:
        cfg = dict(M.load_config(), theme_engine=eng, mp3_dir="", accent="lime", base="grey")
        M.save_json(M.CONFIG_PATH, cfg)
        app = M.App(0)
        root = app.root
        root.geometry("1400x900+0+0")
        root.update()
        tot = [0, 0, 0, 0]
        first = []
        for acc, base in SEQ:
            t0 = time.perf_counter()
            app.retheme(acc, base)
            ms = (time.perf_counter() - t0) * 1000
            pal = M.make_palette(acc, base)
            for tab in app.tabs:                                  # other tabs are refreshed the first time they are shown
                app.nb.select(app.tabs[tab])
                root.update()
            c, t_, p_, n = stale_counts(app, pal, eng)
            tot = [tot[0] + len(c), tot[1] + len(t_), tot[2] + len(p_), tot[3] + n]
            if (c or t_ or p_) and len(first) < 4:
                first += (c + t_ + p_)[:2]
            print(f"      {eng:5} {acc:6} {base:5} retheme {ms:6.0f} ms  stale classic={len(c)} ttk={len(t_)} pixel={len(p_)} of {n}")
        check(tot[0] == 0 and tot[1] == 0 and tot[2] == 0, f"engine {eng}: stale classic {tot[0]}, ttk styles {tot[1]}, pixels {tot[2]} (of {tot[3]} checks)"
              + (": " + "; ".join(first[:3]) if first else ""))
        root.destroy()


SECTIONS = {"workers": t_workers, "audio": t_audio, "match": t_match, "cache": t_cache, "firstshow": t_firstshow, "theme": t_theme}

if __name__ == "__main__":
    want = [a for a in sys.argv[1:] if not a.startswith("--")] or list(SECTIONS)
    for k in want:
        SECTIONS[k]()
    print("\nFAILED: %d" % len(FAILS) if FAILS else "\nALL OK")
    sys.exit(1 if FAILS else 0)
