"""V5.58 targeted checks (GUI + settings audit). No rendering, no OCR, no full smoketest.

    python test_v558.py              (Windows: needs the normal desktop)
    xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v558.py        (Linux)

    python test_v558.py live tabs audit      (run only some of the three groups)

1. live    - all 12 accent x base combinations in ONE running window: no error, no widget keeps an old colour, contrast readable.
2. tabs    - tab switching only shows / hides: same widget objects, no list refill, each switch < 150 ms (Linux).
3. audit   - every setting of the Settings and Manual tab: saves + reloads, is read by the code, changes the plan / render parameters.
"""
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="montager_v558_"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tkinter as tk
from tkinter import ttk

import montage as M
import test_v557 as T

AUDIT = []                                  # (setting, saves, read, changes, how)


def audit(setting, saves, read, changes, how):
    AUDIT.append((setting, saves, read, changes, how))


def patched(obj, **kw):
    """Context-free patching helper: returns (restore function)."""
    old = {k: getattr(obj, k) for k in kw}
    for k, v in kw.items():
        setattr(obj, k, v)
    return lambda: [setattr(obj, k, v) for k, v in old.items()]


# ================================================================ 1. live theme
def test_live_theme():
    fails = []
    app, old = T.new_app()
    logs = []
    M.LOG_SINK[0] = logs.append
    try:
        app.show_changelog()
        T.pump(app.root, 3, 0.02)
        combos = [(a, b) for a in M.ACCENTS for b in M.BASES]
        all_vals = {v.lower() for a, b in combos for v in M.make_palette(a, b).values()}
        widgets_before = {id(w) for w in T.walk(app.root)}
        for acc, base in combos:
            tag = f"{acc}/{base}"
            try:
                app.set_accent.set(M.ACCENT_NAMES[acc])
                app.set_base.set(base.capitalize())
                for tname in app.tabs:                                     # every tab visible once with the new theme
                    app.nb.select(app.tabs[tname])
                    T.pump(app.root, 1, 0.01)
                T.pump(app.root, 2, 0.02)
                pal = app.pal
                st = ttk.Style(app.root)
                if pal != M.make_palette(acc, base):
                    fails.append(f"{tag}: palette not switched")
                if not M.SV_THEME[0] or st.theme_use() != f"mt-{acc}_{base}":
                    fails.append(f"{tag}: ttk theme is {st.theme_use()}")
                for a, b, mn in (("fg", "bg", 7), ("fg", "field", 7), ("fg", "head", 7), ("acc_fg", "acc", 4.5), ("sel_fg", "sel", 4.5),
                                 ("dim", "bg", 4.5), ("acc", "bg", 3), ("acc", "field", 3)):
                    c = M.contrast(pal[a], pal[b])
                    if c < mn:
                        fails.append(f"{tag}: {a} on {b} contrast {c:.1f} < {mn}")
                # no classic tk widget (log, canvases, dividers, pop-downs, changelog) keeps a colour of another combination
                stale = all_vals - {v.lower() for v in pal.values()}
                for w in app._tk_widgets():
                    for opt in app.COLOR_OPTS:
                        try:
                            v = str(w.cget(opt)).lower()
                        except tk.TclError:
                            continue
                        if v in stale:
                            fails.append(f"{tag}: {w} {opt} = {v} (old palette colour)")
                want = {(app.root, "bg"): pal["bg"], (app.log, "bg"): pal["field"], (app.log, "fg"): pal["fg"],
                        (app.log, "selectbackground"): pal["sel"], (app.vpane, "bg"): pal["border"], (app.set_canvas, "bg"): pal["bg"],
                        (app.cl_text, "bg"): pal["field"], (app.cl_text.master.master, "bg"): pal["bg"]}
                for (w, opt), v in want.items():
                    if str(w.cget(opt)).lower() != v.lower():
                        fails.append(f"{tag}: {w} {opt} = {w.cget(opt)}, expected {v}")
                if str(app.cl_text.tag_cget("ver", "foreground")).lower() != pal["acc"].lower():
                    fails.append(f"{tag}: changelog heading colour {app.cl_text.tag_cget('ver', 'foreground')} != {pal['acc']}")
                for sty, opt, key in (("Section.TLabel", "foreground", "acc"), ("Dim.TLabel", "foreground", "dim"),
                                      ("TLabelframe.Label", "foreground", "acc")):
                    if st.lookup(sty, opt).lower() != pal[key].lower():
                        fails.append(f"{tag}: ttk {sty} {opt} = {st.lookup(sty, opt)}, expected {pal[key]}")
                if M.PAL["acc"] != pal["acc"]:
                    fails.append(f"{tag}: module PAL not updated")
                app.flush_settings()
                cfg = M.load_json(M.CONFIG_PATH, {})
                if (cfg.get("accent"), cfg.get("base")) != (acc, base):
                    fails.append(f"{tag}: config has {cfg.get('accent')}/{cfg.get('base')}")
            except Exception:
                fails.append(f"{tag}: " + traceback.format_exc()[-300:])
        errs = [m for m in logs if "not applied" in m or "Traceback" in m]
        if errs:
            fails.append("errors logged: " + "; ".join(errs[:3]))
        if {id(w) for w in T.walk(app.root)} - widgets_before - {id(w) for w in T.walk(app.root) if str(w).startswith(str(app.cl_win))}:
            fails.append("a theme switch created new widgets")
        if "Applies after restart" in " ".join(str(w.cget("text")) for w in T.walk(app.set_inner) if w.winfo_class() == "TLabel"
                                                 and w.winfo_manager() and "Accent" in str(w.master.grid_slaves(column=0))):
            pass
        print(f"   {len(combos)} combinations switched live in one window")
    finally:
        M.LOG_SINK[0] = None
        T.close_app(app, old)
    return fails


# ================================================================ 2. tabs
def test_tabs():
    fails = []
    app, old = T.new_app()
    try:
        T.fake_clips(app, 60)
        T.pump(app.root, 4, 0.05)
        if M.APP_VERSION != "V5.58" or M.APP_VERSION not in app.root.title():
            fails.append(f"window title '{app.root.title()}' does not show V5.58")
        ids = {n: {id(w) for w in T.walk(f)} | {id(f)} for n, f in app.tabs.items()}
        before = list(app.nb.tabs())
        calls = {"apply_filter": 0, "fill_chunked": 0, "refresh_songs": 0, "load_clips": 0}
        for k in calls:
            orig = getattr(app, k)
            setattr(app, k, (lambda orig, k: lambda *a, **kw: (calls.__setitem__(k, calls[k] + 1), orig(*a, **kw))[1])(orig, k))
        times = {}
        for _ in range(5):
            for n, f in app.tabs.items():
                t = time.perf_counter()
                app.nb.select(f)
                app.root.update_idletasks()
                app.root.update()
                times.setdefault(n, []).append((time.perf_counter() - t) * 1000)
        for n, f in app.tabs.items():
            if {id(w) for w in T.walk(f)} | {id(f)} != ids[n]:
                fails.append(f"tab {n}: widgets were recreated or removed")
        if list(app.nb.tabs()) != before:
            fails.append("the notebook tab list changed")
        if any(calls.values()):
            fails.append(f"a tab switch refilled something: {calls}")
        slow = {n: round(max(v), 1) for n, v in times.items() if max(v) >= 150}
        if slow and sys.platform.startswith("linux"):
            fails.append(f"tab switch >= 150 ms: {slow}")
        if not app.switch_ms:
            fails.append("tab switch time not measured (switch_ms empty)")
        print("   max switch ms per tab: " + ", ".join(f"{n} {max(v):.0f}" for n, v in times.items()) +
              f"   (app.switch_ms recorded {len(app.switch_ms)} switches)")
        # the same data is never filled again
        app.apply_filter()
        T.pump(app.root, 3, 0.02)
        tok = app._fill_token[app.ctree]
        ch = app.ctree.get_children()
        app.apply_filter()
        T.pump(app.root, 3, 0.02)
        if app._fill_token[app.ctree] is not tok or app.ctree.get_children() != ch:
            fails.append("apply_filter with unchanged data refilled the clip list")
        app.clips[0]["used"] = "2026-10-05"                                  # changed data: filled again
        app.apply_filter()
        T.pump(app.root, 3, 0.02)
        if app._fill_token[app.ctree] is tok:
            fails.append("changed data did not refill the clip list")
    finally:
        T.close_app(app, old)
    return fails


# ================================================================ 3. settings audit
def _planner_setup(tmp):
    """Generated song + synthetic events (no clips, no OCR); make_plan runs on them with the detection / scan steps stubbed."""
    sp = tmp / "plan test.mp3"
    M.synth_song(sp, 128.0)
    an = M.analyse_song(str(sp), 128.0)
    song = {"path": str(sp), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
    return an, song


def _stub_make_plan_inputs(an, song, evs):
    return patched(M, autodetect_dirs=lambda c: c, load_dets=lambda *a, **k: {"valorant": object(), "cs2": object()},
                   scan_clips=lambda c, *a, **k: [{"game": "valorant", "path": "/fake/c.mp4"}],
                   game_pool=lambda c, g, p=None: ([{"rec": {"path": "/fake/c.mp4"}}],
                                                   {"tagged": 1, "scanned": 1, "with_kills": 1,
                                                    "audio": {"raw": 1, "no_shot": 0, "death_lock": 0, "kept": 1}}),
                   build_events=lambda pool, g, c, rng, **k: (list(evs), []),
                   song_pool=lambda c: ([song], [], "x.csv"),
                   pick_song=lambda c, g, songs, now=None, forced=None: (song, an, {"recency": 0, "fit": 20, "fit_parts": {}, "penalty": 0,
                                                                                    "total": 20, "days": None}, []),
                   analyse_song_v4=lambda *a, **k: an, fmt_plan=lambda *a, **k: "plan text")


def test_audit():
    fails = []
    tmp = Path(tempfile.mkdtemp(prefix="montager_audit_"))
    old = M.use_data_dir(tmp / "data")
    try:
        fails += _audit_gui(tmp)
        fails += _audit_planner(tmp)
        fails += _audit_engine(tmp)
    finally:
        M.restore_data_dir(old)
    return fails


def _audit_gui(tmp):
    """(a) every Settings / Manual control saves and reloads; the Manual controls reach the job arguments."""
    fails = []
    app, old = T.new_app()
    try:
        S = {"mp3_dir": "D:/m", "playlist_dir": "D:/p", "output_root": "D:/o"}
        for k, v in S.items():
            app.sv[k].set(v)
        app.sl["valorant"].set("D:/v1; D:/v2")
        app.sl["cs2"].set("D:/c1")
        N = {"max_mb": "77", "max_dur_s": "55", "auto_recent_days": "12", "auto_old_per_run": "33", "name_match": "71", "death_lock_s": "4.5",
             "week_days": "9", "game_audio_level": "0.35", "ui_scale": "1.25"}
        for k, v in N.items():
            app.sn[k].set(v)
        app.set_track["valorant"].set("2")
        app.set_track["cs2"].set("3")
        app.set_opt.set(False)
        app.set_len.set(73)
        app.set_style.set("chill")
        app.set_place.set("v4")
        app.set_audio.set(M.AUDIO_MODES["legacy"])
        app.set_q.set("max")
        app.set_sync.set(False)
        app.set_upd.set(True)
        app.set_accent.set("Pink")
        app.set_base.set("Black")
        app.flush_settings()
        cfg = M.load_config()
        want = {**S, **{k: (float(v) if "." in v else int(v)) for k, v in N.items()}, "length_s": 73, "style": "chill", "placement": "v4",
                "audio_mode": "legacy", "quality": "max", "sync_report": False, "update_on_start": True, "accent": "pink", "base": "black",
                "game_audio_track": {"valorant": "2", "cs2": "3"}, "clip_dirs": {"valorant": ["D:/v1", "D:/v2"], "cs2": ["D:/c1"]}}
        for k, v in want.items():
            if cfg.get(k) != v:
                fails.append(f"saves: {k} = {cfg.get(k)!r}, expected {v!r}")
        app.root.destroy()
        app2 = M.App(0, startup=False)                                      # reload into a fresh window
        try:
            got = {"mp3_dir": app2.sv["mp3_dir"].get(), "length": app2.set_len.get(), "opt": app2.set_opt.get(), "style": app2.set_style.get(),
                   "place": app2.set_place.get(), "audio": app2.set_audio.get(), "q": app2.m_q.get(), "sync": app2.set_sync.get(),
                   "upd": app2.set_upd.get(), "accent": app2.set_accent.get(), "base": app2.set_base.get(), "mm": app2.sn["max_mb"].get(),
                   "vt": app2.set_track["valorant"].get(), "ct": app2.set_track["cs2"].get(), "gl": app2.sn["game_audio_level"].get(),
                   "v": app2.sl["valorant"].get()}
            exp = {"mp3_dir": "D:/m", "length": 73, "opt": False, "style": "chill", "place": "v4", "audio": M.AUDIO_MODES["legacy"], "q": "max",
                   "sync": False, "upd": True, "accent": "Pink", "base": "Black", "mm": "77", "vt": "2", "ct": "3", "gl": "0.35", "v": "D:/v1; D:/v2"}
            for k, v in exp.items():
                if got[k] != v:
                    fails.append(f"reload: {k} = {got[k]!r}, expected {v!r}")
            if M.ttk.Style(app2.root).theme_use() != "mt-pink_black":
                fails.append("reload: the saved theme is not the one in use")
            # Manual tab: the controls reach the job (run_task / job_video captured, nothing runs)
            cap = {}
            app2.ticked = {"x/a.mp4"}
            app2.byp = {"x/a.mp4": {"kills": 2}}
            app2.m_opt.set(False)
            app2.m_len.set(88)
            app2.m_style.set("hype")
            app2.m_q.set("nvenc")
            app2.m_seed.set("4242")
            app2.m_game.set("cs2")
            app2.job_video = lambda game, **kw: cap.update(game=game, **kw)
            app2.run_task = lambda *a, **k: None
            app2.manual("render")
            exp = {"game": "cs2", "target": 88, "style": "hype", "seed": 4242, "maxq": False, "mode": "render", "paths": ["x/a.mp4"]}
            for k, v in exp.items():
                if cap.get(k) != v:
                    fails.append(f"Manual -> job: {k} = {cap.get(k)!r}, expected {v!r}")
            app2.m_opt.set(True)
            app2.m_q.set("max")
            app2.manual("dry")
            if cap.get("target") != "optimal" or cap.get("maxq") is not True:
                fails.append(f"Manual -> job: Optimal / Max quality not passed ({cap.get('target')}, {cap.get('maxq')})")
            # Manual list controls change the list / ticks
            T.fake_clips(app2, 40, 10)
            n_all = len(app2.ctree.get_children())
            app2.m_used.set("Unused")
            app2.apply_filter()
            T.pump(app2.root, 6, 0.05)
            n_unused = len(app2.ctree.get_children())
            app2.m_used.set("All clips")
            app2.m_folder.set("VALORANT")
            app2.apply_filter()
            T.pump(app2.root, 6, 0.05)
            n_fold = len(app2.ctree.get_children())
            app2.m_folder.set("All folders")
            app2.m_date.set("Last 7 days")
            app2.apply_filter()
            T.pump(app2.root, 6, 0.05)
            if not (n_all == 40 and n_unused == 30 and n_fold == 20):
                fails.append(f"Manual filters: all {n_all}, unused {n_unused}, folder {n_fold} (expected 40 / 30 / 20)")
            app2.m_date.set("All dates")
            app2.apply_filter()
            app2.ticked.clear()
            app2.m_n.set("7")
            app2.tick("newest")
            n7 = len(app2.ticked)
            app2.ticked.clear()
            app2.m_n.set("3")
            app2.tick("newest")
            if (n7, len(app2.ticked)) != (7, 3):
                fails.append(f"Tick newest N: {n7} / {len(app2.ticked)} (expected 7 / 3)")
        finally:
            T.close_app(app2, old)
            old = None
    finally:
        if old is not None:
            T.close_app(app, old)
    for s in ("Folders (mp3 / csv / output / clip folders)", "Scanning numbers (max MB, max s, recent days, old per run, name match, death lock, week days)",
              "Game audio level + track", "Length / Optimal / Style / Placement / Audio mode / Quality / Reports", "Accent / Base / UI scale", "Updates"):
        audit(s, "yes" if not [f for f in fails if f.startswith(("saves", "reload"))] else "NO", "-", "-",
              "test_v558 _audit_gui: set controls, flush, load_config, reopen a new App, compare")
    return fails


def _plan(cfg, an, song, evs, **kw):
    restore = _stub_make_plan_inputs(an, song, evs)
    try:
        return M.make_plan(cfg, "valorant", scan=False, **kw)[0]
    finally:
        restore()


def _audit_planner(tmp):
    fails = []
    an, song = _planner_setup(tmp)
    evs = M.fake_events(26)
    base = dict(M.DEFAULT_CONFIG)
    # length_s (cfg -> make_plan when the caller gives no target) + Manual target
    p_a = _plan(dict(base, length_s=32), an, song, evs)
    p_b = _plan(dict(base, length_s=44), an, song, evs)
    if not (p_a["duration"] < p_b["duration"] and abs(p_a["duration"] - 32) < 10):
        fails.append(f"length_s: 32 -> {p_a['duration']:.1f} s, 44 -> {p_b['duration']:.1f} s")
    audit("length_s (Default length / Optimal / Manual length)", "yes", "make_plan: cfg.length_s", f"{p_a['duration']:.0f} s -> {p_b['duration']:.0f} s",
          "make_plan on generated song + synthetic events, 32 vs 44")
    # style
    p_h = _plan(dict(base, style="hype"), an, song, evs, seed=3)
    p_c = _plan(dict(base, style="chill"), an, song, evs, seed=3)
    if (p_h["recipe"], p_c["recipe"]) != ("hype", "chill"):
        fails.append(f"style: hype -> {p_h['recipe']}, chill -> {p_c['recipe']}")
    audit("style (Default style / Manual Style)", "yes", "make_plan: cfg.style", f"recipe {p_h['recipe']} -> {p_c['recipe']}", "make_plan, same seed")
    # placement
    p_5 = _plan(dict(base, placement="v5"), an, song, [dict(e) for e in evs], seed=3)
    p_4 = _plan(dict(base, placement="v4"), an, song, [dict(e) for e in evs], seed=3)
    sig = lambda p: [(tuple(t["kills"]), t["f0"]) for t in p["takes"]]
    if (p_5["placement"], p_4["placement"]) != ("v5", "v4") or sig(p_5) == sig(p_4):
        fails.append(f"placement: labelled {p_5['placement']}/{p_4['placement']}, kill timing identical: {sig(p_5) == sig(p_4)}")
    audit("placement (Kill placement v5 / v4)", "yes", "make_plan: cfg.placement", "plan['placement'] + kill times (V4 times) differ", "make_plan v5 vs v4, same seed")
    # game audio level -> gain in the plan -> volume in the ffmpeg filter graph (built, not run)
    rest = patched(M, clip_audio_auto=lambda rec, track="auto": {"stream": 0, "lufs": -30.0, "note": "t", "_track": track},
                   audio_unusable=lambda rec, au: None)
    try:
        evs_a = M.fake_events(6)
        for e in evs_a:
            e["rec"]["audio"] = True
        pl = _plan(dict(base, game_audio_level=0.3), an, song, evs_a, seed=2, target=60)
        ph = _plan(dict(base, game_audio_level=0.9), an, song, evs_a, seed=2, target=60)
        gl = pl["takes"][0]["srcs"][0]["gain_db"]
        gh = ph["takes"][0]["srcs"][0]["gain_db"]
        if not gl < gh:
            fails.append(f"game_audio_level: gain {gl} dB (0.3) vs {gh} dB (0.9)")
        try:
            _, g1 = M.build_filter(pl, dict(base, game_audio_level=0.3), False)
            _, g2 = M.build_filter(ph, dict(base, game_audio_level=0.9), False)
            if g1 == g2:
                fails.append("game_audio_level: the ffmpeg filter graph is identical for 0.3 and 0.9")
        except Exception as ex:
            fails.append(f"game_audio_level: build_filter failed: {ex}")
        audit("game_audio_level", "yes", "_game_gain via finish_plan", f"plan gain {gl:+.1f} -> {gh:+.1f} dB; filter graph differs",
              "plan_montage + build_filter (built, not run)")
        # game audio track + audio mode reach the audio pick
        seen = []
        rest2 = patched(M, clip_audio_auto=lambda rec, track="auto": seen.append(track) or {"stream": 0, "lufs": -30.0, "note": ""},
                        clip_audio_legacy=lambda rec: seen.append("LEGACY") or {"stream": 1, "lufs": -30.0, "note": "legacy"})
        try:
            rec = {"path": "/fake/c.mp4", "audio": [{}]}
            for cfgx, game in ((dict(base, game_audio_track={"valorant": "2", "cs2": "3"}), "valorant"),
                               (dict(base, game_audio_track={"valorant": "2", "cs2": "3"}), "cs2"),
                               (dict(base, audio_mode="legacy"), "valorant")):
                st = {}
                M.resolve_clip_audio(rec, cfgx, game, st)
            if seen != ["2", "3", "LEGACY"]:
                fails.append(f"game_audio_track / audio_mode: audio pick received {seen}, expected ['2', '3', 'LEGACY']")
        finally:
            rest2()
        audit("game_audio_track (Valorant / CS2)", "yes", "resolve_clip_audio -> clip_audio_auto(track)", "the chosen track reaches the pick", "stub of the pick, call resolve_clip_audio")
        audit("audio_mode (Auto / Legacy)", "yes", "resolve_clip_audio", "legacy path used", "same stubs; full mode logic also in test_v557")
    finally:
        rest()
    # week_days: which songs count as "this week" in pick_song
    songs = [dict(song, added=M.datetime.datetime.now() - M.datetime.timedelta(days=10), path=song["path"])]
    msgs = []
    M.LOG_SINK[0] = msgs.append
    r2 = patched(M, analyse_song=lambda *a, **k: an)
    try:
        res = {}
        for wd in (7, 14):
            msgs.clear()
            M.pick_song(dict(base, week_days=wd), "valorant", songs)
            res[wd] = " ".join(msgs)
    finally:
        r2()
        M.LOG_SINK[0] = None
    if res[7] == res[14]:
        fails.append("week_days: pick_song output identical for 7 and 14 days")
    audit("week_days ('This week' = last N days)", "yes", "pick_song, song_pool", "song counted as this week only when N >= its age", "pick_song with a 10-day-old song, N=7 vs 14")
    return fails


def _audit_engine(tmp):
    fails = []
    base = dict(M.DEFAULT_CONFIG)
    # --- scanning limits
    d = tmp / "clips"
    d.mkdir()
    for n, mb in (("a.mp4", 2), ("b.mp4", 5)):
        with open(d / n, "wb") as f:
            f.truncate(mb * 1024 * 1024)
    durs = {"a.mp4": 30.0, "b.mp4": 90.0}
    r = patched(M, analyse_clip=lambda p, cache, rescan, bar: (p, {"path": p, "dur": durs[Path(p).name], "w": 1920, "h": 1080}),
                walk_files=lambda roots, exts, min_size, cfg: iter(sorted(str(x) for x in d.glob("*.mp4"))))
    M.CLIPS_CACHE.unlink(missing_ok=True)
    try:
        cfg = dict(base, clip_dirs={"valorant": [str(d)], "cs2": []}, clip_root=str(d), cfg_version=5)
        n = lambda **kw: len(M.scan_clips(dict(cfg, **kw)))
        n_big, n_small = n(max_mb=10, max_dur_s=200), n(max_mb=3, max_dur_s=200)
        n_dur = n(max_mb=10, max_dur_s=60)
        if (n_big, n_small, n_dur) != (2, 1, 1):
            fails.append(f"max_mb / max_dur_s: scan counts {n_big}, {n_small}, {n_dur} (expected 2, 1, 1)")
    except Exception:
        fails.append("max_mb / max_dur_s: " + traceback.format_exc()[-300:])
    finally:
        r()
    audit("max_mb / max_dur_s (Skip files larger / clips longer)", "yes", "scan_clips", "2 -> 1 clip (size), 2 -> 1 clip (duration)", "scan_clips with stubbed probe on 2 MB / 5 MB files")
    # --- auto scan set
    recs, now = [], time.time()
    for i, age in enumerate((1, 2, 3, 40, 50, 60, 70)):
        p = tmp / f"auto{i}.mp4"
        p.write_bytes(b"x")
        os.utime(p, (now - age * 86400, now - age * 86400))
        recs.append({"path": str(p), "game": "valorant", "w": 1920})
    r = patched(M, scan_clips=lambda c, *a, **k: recs, load_dets=lambda *a, **k: {"valorant": object()}, load_kills_cache=lambda: {},
                kills_key=lambda *a: "k")
    try:
        s1 = M.auto_scan_set(dict(base, auto_recent_days=30, auto_old_per_run=2), "valorant")
        s2 = M.auto_scan_set(dict(base, auto_recent_days=30, auto_old_per_run=4), "valorant")
        s3 = M.auto_scan_set(dict(base, auto_recent_days=2.5, auto_old_per_run=0), "valorant")
        if (len(s1), len(s2), len(s3)) != (5, 7, 2):
            fails.append(f"auto_recent_days / auto_old_per_run: {len(s1)}, {len(s2)}, {len(s3)} (expected 5, 7, 2)")
    finally:
        r()
    audit("auto_recent_days / auto_old_per_run", "yes", "auto_scan_set", "5 / 7 / 2 clips for 3 settings", "auto_scan_set on 7 files with set mtimes")
    # --- death lock
    r = patched(M, gun_onsets=lambda rec, cache: [(9.9, 1.0)], load_kills_cache=lambda: {})
    try:
        def lock(sec):
            pool = [{"rec": {"path": "/fake/a.mp4"}, "kills": [{"t": 10.0, "ks": 1.0}], "deaths": [6.0], "revives": [], "rej": []}]
            return M.verified_kills(pool, dict(base, death_lock_s=sec))["death_lock"]
        a_, b_ = lock(8.0), lock(2.0)
        if (a_, b_) != (1, 0):
            fails.append(f"death_lock_s: dropped {a_} (8 s) / {b_} (2 s), expected 1 / 0")
    except Exception:
        fails.append("death_lock_s: " + traceback.format_exc()[-300:])
    finally:
        r()
    audit("death_lock_s", "yes", "verified_kills", "kill after own death dropped at 8 s, kept at 2 s", "verified_kills on a synthetic pool (gunshot analysis stubbed)")
    # --- name_match: the same OCR row is a kill at 70, nothing at 95 (detection code unchanged, only called)
    row = {"ks": 82.0, "vs": 10.0, "ktext": "fireaxe", "vtext": "enemy", "split": "icon", "gun": True, "before": "", "icon": (0, 0, 9, 9), "game": "valorant"}
    try:
        v_lo = [x[0] for x in M.classify_row(dict(row), dict(base, name_match=70))]
        v_hi = [x[0] for x in M.classify_row(dict(row), dict(base, name_match=95))]
        if v_lo == v_hi:
            fails.append(f"name_match: classify_row gives {v_lo} for 70 and {v_hi} for 95")
        audit("name_match", "yes", "classify_row / analyse_entry", f"{v_lo} -> {v_hi}", "classify_row with one synthetic row")
    except Exception:
        audit("name_match", "yes", "analyse_entry (cfg.name_match) - see report", "NOT TESTED (needs OCR rows)", "classify_row needs a full OCR row: " + traceback.format_exc()[-120:].replace("\n", " "))
    # --- quality / sync_report / output_root through run_job (plan + render stubbed, nothing rendered)
    seen = {}
    fake_plan = {"game": "valorant", "seed": 1, "duration": 10.0, "takes": [], "audio_mode": "legacy", "headline": "h", "recipe": "hype",
                 "song": {"path": "x", "section_s": 100}}
    outd = tmp / "outroot"
    r = patched(M, make_plan=lambda *a, **k: (fake_plan, "plan"),
                render_plan=lambda plan, outfile, cfg, maxq=False, preview=False, encoder=None, effects=True: seen.update(maxq=maxq, out=Path(outfile)) or Path(outfile),
                quality_check=lambda *a, **k: None, record_history=lambda p: None, montage_name=lambda *a: "m",
                sync_report=lambda *a, **k: seen.__setitem__("sync", True))
    try:
        for q, sync in (("max", False), ("nvenc", True)):
            seen.clear()
            M.save_json(M.CONFIG_PATH, dict(M.load_config(), quality=q, sync_report=sync, output_root=str(outd)))
            M.run_job("valorant", "render", paths=["/fake/a.mp4"])
            if seen.get("maxq") != (q == "max") or bool(seen.get("sync")) != sync or seen.get("out") != outd / "Valorant" / "m.mp4":
                fails.append(f"run_job quality={q} sync_report={sync}: got {seen}")
    except Exception:
        fails.append("run_job: " + traceback.format_exc()[-300:])
    finally:
        r()
    a1, a2 = M.enc_args(True, False, True), M.enc_args(False, False, True)
    if a1 == a2 or "libx264" not in a1 or "h264_nvenc" not in a2:
        fails.append("quality: enc_args(max) and enc_args(nvenc) do not differ as labelled")
    audit("quality (Fast NVENC / Max x264 CRF15)", "yes", "run_job -> render_plan(maxq) -> enc_args", "ffmpeg encoder args: h264_nvenc p7 -> libx264 crf15", "run_job with plan + render stubbed; enc_args built, not run")
    audit("sync_report", "yes", "run_job", "sync_report() called only when on", "run_job with stubs")
    audit("output_root", "yes", "run_job (outfile path)", "render target = output_root/Valorant/<name>.mp4", "run_job with stubs")
    # --- ui_scale
    try:
        M.apply_theme  # noqa
        root = tk.Tk()
        f10 = (M.apply_theme(root, 1.0), M.F(10))[1]
        f20 = (M.apply_theme(root, 2.0), M.F(10))[1]
        rh = ttk.Style(root).lookup("Treeview", "rowheight")
        root.destroy()
        M.UI_SCALE[0] = 1.0
        if not (f20 > f10 and int(rh) > 30):
            fails.append(f"ui_scale: F(10) {f10} -> {f20}, row height {rh}")
    except Exception:
        fails.append("ui_scale: " + traceback.format_exc()[-300:])
    audit("ui_scale", "yes", "apply_theme (at start)", "font size 10 -> 20, Treeview row height scales", "apply_theme(1.0) vs (2.0); still applies after restart only")
    # --- update_on_start
    calls = []
    fake_here = tmp / "repo"
    (fake_here / ".git").mkdir(parents=True)
    r = patched(M, HERE=fake_here)
    r_sub = patched(M.subprocess, run=lambda cmd, **kw: calls.append(cmd[3:]) or type("R", (), {"returncode": 0, "stdout": "abc", "stderr": ""})())
    r_wh = patched(M.shutil, which=lambda n: "git")
    try:
        for flag in (False, True):
            calls.clear()
            M.save_json(M.CONFIG_PATH, dict(M.load_config(), update_on_start=flag))
            M.update_on_start()
            if bool(calls) != flag or (flag and ["pull", "--ff-only"] not in calls):
                fails.append(f"update_on_start={flag}: git calls {calls}")
    finally:
        r_wh()
        r_sub()
        r()
    audit("update_on_start", "yes", "update_on_start()", "git pull runs only when on", "update_on_start with git stubbed")
    # --- folders
    c1 = dict(base, clip_dirs={"valorant": ["/a"], "cs2": ["/b", "/c"]})
    c2 = dict(base, clip_dirs={"valorant": [], "cs2": ["/z"]})
    if M.clip_dirs(c1) != [("/a", "valorant"), ("/b", "cs2"), ("/c", "cs2")] or M.clip_dirs(c2) != [("/z", "cs2")]:
        fails.append("clip_dirs: the folder lists do not drive clip_dirs()")
    audit("clip folders (Valorant / CS2)", "yes", "clip_dirs -> scan_clips / tag_game", "folder list decides which clips (and which game)", "clip_dirs() on two configs")
    audit("mp3_dir / playlist_dir", "yes", "scan_audio / read_playlist (song_pool)", "NOT behaviour-tested here", "read by song_pool; covered by the Windows smoketest only")
    return fails


# ================================================================ runner
def main():
    groups = {"live": test_live_theme, "tabs": test_tabs, "audit": test_audit}
    want = [a for a in sys.argv[1:] if a in groups] or list(groups)
    bad = 0
    for name in want:
        t = time.time()
        try:
            fails = groups[name]()
        except Exception:
            fails = [traceback.format_exc()[-600:]]
        print(f"{'PASS' if not fails else 'FAIL'}  {name}  ({time.time() - t:.1f} s)")
        for f in fails:
            print("      - " + f)
        bad += bool(fails)
    if AUDIT:
        print("\nsetting | saves | read by code | changes plan / render params | how verified")
        for row in AUDIT:
            print(" | ".join(row))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
