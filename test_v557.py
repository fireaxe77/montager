"""V5.57 targeted checks (GUI, config, audio-mode selection). No rendering, no OCR, no full smoketest.

    python test_v557.py              (Windows: needs the normal desktop)
    xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v557.py        (Linux)

Each check prints PASS / FAIL; the exit code is 1 when anything failed.
"""
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="montager_v557_"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tkinter as tk
from tkinter import ttk

import montage as M

SIZES = ((920, 640), (1220, 920), (1920, 1040))


def pump(root, n=6, dt=0.05):
    for _ in range(n):
        root.update()
        time.sleep(dt)


def new_app(cfg=None):
    d = Path(tempfile.mkdtemp(prefix="montager_t_"))
    old = M.use_data_dir(d)
    if cfg:
        M.save_json(M.CONFIG_PATH, dict(M.load_config(), **cfg))
    app = M.App(0, startup=False)
    app.root.geometry("1220x920+0+0")
    pump(app.root)
    return app, old


def close_app(app, old):
    try:
        app.root.tk.eval("foreach id [after info] {after cancel $id}")
        app.root.destroy()
    except Exception:
        pass
    M.restore_data_dir(old)


def walk(w):
    for c in w.winfo_children():
        yield c
        yield from walk(c)


def is_anc(a, b):
    while b is not None:
        if b is a:
            return True
        b = getattr(b, "master", None)
    return False


def value_of(w):
    return str(w.get())


# ---------------------------------------------------------------- 1. mouse wheel
def test_wheel():
    fails = []
    app, old = new_app()
    try:
        root = app.root
        root.geometry("920x640+0+0")
        n_checked = 0
        for tname, tab in app.tabs.items():
            app.nb.select(tab)
            pump(root, 4)
            guarded = [w for w in walk(tab) if w.winfo_class() in M.App.WHEEL_GUARDED]
            for w in guarded:
                before = value_of(w)
                canv = app.set_canvas if tname == "Settings" else None
                for seq, kw in (("<MouseWheel>", {"delta": -120}), ("<MouseWheel>", {"delta": 120}),
                                ("<Button-4>", {}), ("<Button-5>", {})):
                    if canv is not None:
                        canv.yview_moveto(0.3)
                        root.update()
                    y0 = canv.yview()[0] if canv is not None else None
                    try:
                        w.event_generate(seq, x=3, y=3, **kw)
                    except tk.TclError as ex:
                        fails.append(f"{tname}: cannot send {seq} to {w}: {ex}")
                        continue
                    root.update()
                    if value_of(w) != before:
                        fails.append(f"{tname}: wheel ({seq}) changed {w.winfo_class()} {w} from {before!r} to {value_of(w)!r}")
                    if canv is not None and canv.yview()[0] == y0:
                        fails.append(f"{tname}: wheel over {w.winfo_class()} {w} did not scroll the page")
                n_checked += 1
        seen = {w.winfo_class() for t in app.tabs.values() for w in walk(t)}
        for cls in ("TCombobox", "TSpinbox", "TScale"):
            if cls not in seen:
                fails.append(f"no {cls} found to test")
        # the game audio track box in Settings specifically
        for g, v in app.set_track.items():
            if v.get() != "auto":
                fails.append(f"game audio track {g} changed to {v.get()}")
        print(f"   {n_checked} widgets x 4 wheel events over all tabs")
    finally:
        close_app(app, old)
    return fails


# ---------------------------------------------------------------- 2./3. settings layout + footer
def boxes(app):
    inner = app.set_inner
    ox, oy = inner.winfo_rootx(), inner.winfo_rooty()
    res = []
    for w in walk(inner):
        if w.winfo_width() < 2 or w.winfo_height() < 2:
            continue
        res.append((w, w.winfo_rootx() - ox, w.winfo_rooty() - oy, w.winfo_width(), w.winfo_height()))
    return res


def collisions(bs):
    bad = []
    for i in range(len(bs)):
        a, ax, ay, aw, ah = bs[i]
        for j in range(i + 1, len(bs)):
            b, bx, by, bw, bh = bs[j]
            if is_anc(a, b) or is_anc(b, a):
                continue
            gx = max(bx - (ax + aw), ax - (bx + bw))
            gy = max(by - (ay + ah), ay - (by + bh))
            if gx < 1 and gy < 1:
                bad.append(f"{a.winfo_class()} {a} and {b.winfo_class()} {b} overlap or touch (gap x {gx}, y {gy})")
    return bad


def test_settings_layout():
    fails = []
    app, old = new_app()
    try:
        root = app.root
        app.nb.select(app.tabs["Settings"])
        for W, H in SIZES:
            root.geometry(f"{W}x{H}+0+0")
            pump(root, 8, 0.08)
            bs = boxes(app)
            bad = collisions(bs)
            fails += [f"{W}x{H}: {b}" for b in bad[:6]]
            # footer: the extra check on the footer widgets, always visible and right-aligned
            sb, lb = app.b_save, app.save_label
            rx, ry, rw, rh = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
            if not sb.winfo_viewable() or sb.winfo_rooty() + sb.winfo_height() > ry + rh + 1:
                fails.append(f"{W}x{H}: the Save settings button is not fully visible")
            tab = app.tabs["Settings"]
            if sb.winfo_rootx() + sb.winfo_width() < tab.winfo_rootx() + tab.winfo_width() - 40:
                fails.append(f"{W}x{H}: the Save settings button is not right-aligned")
            if lb.winfo_rootx() + lb.winfo_width() > sb.winfo_rootx() - 1 or lb.winfo_rootx() + lb.winfo_width() >= sb.winfo_rootx():
                fails.append(f"{W}x{H}: status label overlaps / touches the Save button")
            if is_anc(app.set_canvas, sb):
                fails.append("the Save button is inside the scrolled area")
            # scrolling the page must not move the footer
            y_before = sb.winfo_rooty()
            app.set_canvas.yview_moveto(1.0)
            root.update()
            if sb.winfo_rooty() != y_before:
                fails.append(f"{W}x{H}: the footer moved when the page scrolled")
            app.set_canvas.yview_moveto(0.0)
            # padding rules: rows at least 6 px apart vertically (labels in column 0)
            labs = sorted((y, h) for w, x, y, ww, h in bs if w.winfo_class() == "TLabel" and x < 30)
            print(f"   {W}x{H}: {len(bs)} widgets compared, {len(bad)} collisions")
        # save status text + autosave
        app.b_save.invoke()
        pump(root, 2, 0.05)
        if app.save_status.get() != "Saved ✓":
            fails.append(f"status after Save is {app.save_status.get()!r}")
        pump(root, 40, 0.05)
        if app.save_status.get() != "All changes saved":
            fails.append(f"status 2 s later is {app.save_status.get()!r}")
        app.sn["max_mb"].set("1234")
        pump(root, 8, 0.06)
        if M.load_json(M.CONFIG_PATH, {}).get("max_mb") != 1234:
            fails.append("autosave did not write the changed value")
    finally:
        close_app(app, old)
    return fails


# ---------------------------------------------------------------- 4. themes
def test_themes():
    fails = []
    for acc in M.ACCENTS:
        for base in M.BASES:
            app, old = new_app({"accent": acc, "base": base})
            try:
                pal = app.pal
                if not M.SV_THEME[0]:
                    fails.append(f"{acc}/{base}: Sun Valley theme did not load (fallback in use)")
                for a, b, mn in (("fg", "bg", 7), ("fg", "field", 7), ("fg", "head", 7), ("acc_fg", "acc", 4.5), ("sel_fg", "sel", 4.5),
                                 ("dim", "bg", 4.5), ("acc", "bg", 3)):
                    c = M.contrast(pal[a], pal[b])
                    if c < mn:
                        fails.append(f"{acc}/{base}: {a} on {b} contrast {c:.1f} < {mn}")
                if pal["acc"] != M.ACCENT_DEF[acc][0]:
                    fails.append(f"{acc}/{base}: palette accent is {pal['acc']}")
                tcl = (M.lime_theme_dir(acc, base) / "theme" / "dark.tcl").read_text(encoding="utf-8").lower()
                if M.ACCENT_DEF[acc][0] not in tcl:
                    fails.append(f"{acc}/{base}: accent {M.ACCENT_DEF[acc][0]} missing from the theme")
                if "#57c8ff" in tcl or "#2f60d8" in tcl:
                    fails.append(f"{acc}/{base}: original blue left in the theme")
                bg_theme = ttk.Style(app.root).lookup("TFrame", "background")
                want = pal["bg"] if base == "grey" else None
                for tname in app.tabs:
                    app.nb.select(app.tabs[tname])
                    pump(app.root, 2, 0.02)
                # config persists and reloads
                app.flush_settings()
                cfg = M.load_json(M.CONFIG_PATH, {})
                if cfg.get("accent") != acc or cfg.get("base") != base:
                    fails.append(f"{acc}/{base}: config has {cfg.get('accent')}/{cfg.get('base')}")
            except Exception:
                fails.append(f"{acc}/{base}: " + traceback.format_exc()[-300:])
            finally:
                close_app(app, old)
    # default stays grey + lime
    if M.DEFAULT_CONFIG["accent"] != "lime" or M.DEFAULT_CONFIG["base"] != "grey" or M.PAL["acc"].lower() != "#a3e635" or M.PAL["bg"] != "#343434":
        fails.append("default theme is not grey + lime")
    # the settings controls change the config
    app, old = new_app()
    try:
        app.set_accent.set("Purple")
        app.set_base.set("Black")
        app.flush_settings()
        cfg = M.load_json(M.CONFIG_PATH, {})
        if (cfg.get("accent"), cfg.get("base")) != ("purple", "black"):
            fails.append(f"settings controls saved {cfg.get('accent')}/{cfg.get('base')}")
    finally:
        close_app(app, old)
    print(f"   {len(M.ACCENTS) * len(M.BASES)} combinations built")
    return fails


# ---------------------------------------------------------------- manual tab fixtures
def fake_clips(app, n=40, used=10):
    clips = []
    for i in range(n):
        p = f"x/clip{i:02d}.mp4"
        clips.append({"path": p, "name": f"clip{i:02d}.mp4", "folder": "VALORANT" if i % 2 else "Other", "mtime": time.time() - i * 60,
                      "dur": 20, "kills": 2, "ks": [3.0, 4.0], "used": "2026-10-01" if i < used else ""})
    app.clips, app.byp = clips, {c["path"]: c for c in clips}
    app.m_used.set("All clips")
    app.apply_filter()
    pump(app.root, 8, 0.08)


# ---------------------------------------------------------------- 5. dropdown
def test_dropdown():
    fails = []
    app, old = new_app()
    try:
        root = app.root
        app.nb.select(app.tabs["Manual"])
        for W, H in SIZES:
            root.geometry(f"{W}x{H}+0+0")
            pump(root, 6, 0.08)
            fake_clips(app)
            app.apply_layout({})
            pump(root, 4, 0.05)
            cb = app.b_more
            show = app.named["Used filter"]
            if cb.winfo_class() != show.winfo_class() or str(cb.cget("state")) != str(show.cget("state")) or cb.cget("style") != show.cget("style"):
                fails.append("More filters is not the same widget / style as Show")
            if not cb.winfo_viewable() or cb.winfo_rootx() + cb.winfo_width() > root.winfo_rootx() + root.winfo_width():
                fails.append(f"{W}x{H}: the dropdown is not fully visible")
            w0, h0, c0, y0 = root.winfo_width(), root.winfo_height(), app.ctree.winfo_height(), app.ctree.winfo_rooty()
            for _ in range(2):
                root.tk.call("ttk::combobox::Post", str(cb))
                pump(root, 4, 0.05)
                pop = str(root.tk.call("ttk::combobox::PopdownWindow", str(cb)))
                if not int(root.tk.call("winfo", "viewable", pop)):
                    fails.append(f"{W}x{H}: the list did not open")
                if (root.winfo_width(), root.winfo_height(), app.ctree.winfo_height(), app.ctree.winfo_rooty()) != (w0, h0, c0, y0):
                    fails.append(f"{W}x{H}: opening the list changed the window / clip list size")
                root.tk.call("ttk::combobox::Unpost", str(cb))
                pump(root, 4, 0.05)
                if (root.winfo_width(), root.winfo_height(), app.ctree.winfo_height(), app.ctree.winfo_rooty()) != (w0, h0, c0, y0):
                    fails.append(f"{W}x{H}: closing the list changed the window / clip list size")
            print(f"   {W}x{H}: window {w0}x{h0}, clip list {c0} px, unchanged by open / close")
        # items
        app.folder_names = ["All folders"] + sorted({c["folder"] for c in app.clips})
        app.fill_more()
        items = [i.strip() for i in app.b_more.cget("values")]
        for want in ("Date: Last 7 days", "Date range...", "Folder: VALORANT", "Tick whole folder", "Exclude ticked from montages"):
            if not any(want in i for i in items):
                fails.append(f"dropdown item missing: {want}")
        # selecting runs the action / sets the filter and the label returns
        n_all = len(app.ctree.get_children())
        app.b_more.set("    Folder: VALORANT")
        app.b_more.event_generate("<<ComboboxSelected>>")
        pump(root, 8, 0.08)
        n_f = len(app.ctree.get_children())
        if app.m_folder.get() != "VALORANT" or not (0 < n_f < n_all):
            fails.append(f"folder item: folder {app.m_folder.get()}, rows {n_f} of {n_all}")
        if app.m_more.get() != M.MORE_LABEL:
            fails.append("the dropdown label did not return after a selection")
        app.ticked = set()
        app.b_more.set("    Tick whole folder")
        app.b_more.event_generate("<<ComboboxSelected>>")
        pump(root, 3, 0.05)
        if not app.ticked or any(app.byp[p]["folder"] != "VALORANT" for p in app.ticked):
            fails.append(f"'Tick whole folder' item ticked {len(app.ticked)} clips")
        app.m_folder.set("All folders")
        app.b_more.set("    Date: Last 7 days")
        app.b_more.event_generate("<<ComboboxSelected>>")
        pump(root, 2, 0.05)
        if app.m_date.get() != "Last 7 days":
            fails.append("date item did not set the date filter")
    finally:
        close_app(app, old)
    return fails


# ---------------------------------------------------------------- 6. button feedback
def test_feedback():
    fails = []
    app, old = new_app()
    try:
        root = app.root
        app.nb.select(app.tabs["Manual"])
        fake_clips(app)
        b = app.named["Tick newest"]
        app.ticked = set()
        b.invoke()
        pump(root, 2, 0.02)
        txt = str(b.cget("text"))
        if txt == "Tick newest":
            fails.append("no result feedback on the button after the click")
        if app.plabel.get() == "Idle" and txt == "Done ✓":
            pass
        pump(root, 36, 0.05)
        if str(b.cget("text")) != "Tick newest":
            fails.append(f"button text not restored after 1.5 s ({b.cget('text')!r})")
        # busy state for a long action: disabled, 'Working...', then 'Done'
        fr = ttk.Frame(root)
        done = []

        def slow():
            time.sleep(0.4)
            done.append(1)
        lb = app.btn(fr, "Long action", lambda: app.run_task("slow", slow), name="Long action test")
        lb.pack()
        other = app.named["Reload list"]
        lb.invoke()
        pump(root, 2, 0.02)
        if "disabled" not in lb.state() or str(lb.cget("text")) != "Working...":
            fails.append(f"no busy state while the action runs (state {lb.state()}, text {lb.cget('text')!r})")
        if "disabled" not in other.state():
            fails.append("other buttons stay enabled during a long action (double click possible)")
        t0 = time.time()
        while not done and time.time() - t0 < 5:
            pump(root, 1, 0.05)
        pump(root, 8, 0.05)
        if "disabled" in lb.state() or str(lb.cget("text")) != "Done ✓":
            fails.append(f"no 'Done' confirmation (state {lb.state()}, text {lb.cget('text')!r})")
        pump(root, 36, 0.05)
        if str(lb.cget("text")) != "Long action":
            fails.append("button text not restored after the confirmation")
    finally:
        close_app(app, old)
    return fails


# ---------------------------------------------------------------- 7. random pick
def test_random_pick():
    fails = []
    app, old = new_app()
    try:
        root = app.root
        app.nb.select(app.tabs["Manual"])
        app.run_task = lambda name, fn, *a: fn(*a)                 # run inline; the result still goes through the app's queue
        fake_clips(app, 40, used=10)
        if app.m_rand_n is app.m_n or app.m_rand_n.get() != "15":
            fails.append("Random pick has no own number box defaulting to 15")
        app.m_rand_n.set("12")
        app.m_n.set("5")
        app.ticked = set()
        app.named["Random pick"].invoke()
        pump(root, 8, 0.08)
        if len(app.ticked) != 12:
            fails.append(f"Random pick N=12 ticked {len(app.ticked)}")
        if any(app.byp[p]["used"] for p in app.ticked):
            fails.append("Random pick ticked used clips without 'Include used clips'")
        if (app.m_rand_n.get(), app.m_n.get()) != ("12", "5"):
            fails.append("the click changed a number box")
        app.m_n.set("9")
        if app.m_rand_n.get() != "12":
            fails.append("changing 'Tick newest' changed the Random pick box")
        app.m_rand_n.set("7")
        if app.m_n.get() != "9":
            fails.append("changing the Random pick box changed 'Tick newest'")
        # Tick newest uses its own box
        app.ticked = set()
        app.named["Tick newest"].invoke()
        pump(root, 2, 0.02)
        if len(app.ticked) != 9:
            fails.append(f"Tick newest N=9 ticked {len(app.ticked)}")
        # include used clips + fewer eligible than N
        app.m_incl_used.set(True)
        app.m_rand_n.set("25")
        app.ticked = set()
        app.named["Random pick"].invoke()
        pump(root, 8, 0.08)
        if len(app.ticked) != 25:
            fails.append(f"include used, N=25 ticked {len(app.ticked)}")
        app.m_incl_used.set(False)
        app.m_rand_n.set("100")
        app.ticked = set()
        app.named["Random pick"].invoke()
        pump(root, 8, 0.08)
        if len(app.ticked) != 30 or "only 30 eligible" not in app.plabel.get():
            fails.append(f"fewer eligible than N: ticked {len(app.ticked)}, status {app.plabel.get()!r}")
        # filter respected (folder)
        app.m_folder.set("VALORANT")
        app.apply_filter()
        pump(root, 8, 0.08)
        app.m_rand_n.set("8")
        app.ticked = set()
        app.named["Random pick"].invoke()
        pump(root, 8, 0.08)
        if len(app.ticked) != 8 or any(app.byp[p]["folder"] != "VALORANT" for p in app.ticked):
            fails.append(f"folder filter not respected: {len(app.ticked)} ticked")
        # empty box = Optimal estimate (still ticks something, never the shared box)
        app.m_folder.set("All folders")
        app.apply_filter()
        pump(root, 8, 0.08)
        app.m_rand_n.set("")
        app.ticked = set()
        app.named["Random pick"].invoke()
        pump(root, 15, 0.1)
        if not app.ticked:
            fails.append("empty box: the Optimal estimate ticked nothing")
    finally:
        close_app(app, old)
    return fails


# ---------------------------------------------------------------- 8. changelog
def test_changelog():
    fails = []
    app, old = new_app()
    cwd = os.getcwd()
    try:
        root = app.root
        text = M.CHANGELOG_PATH.read_text(encoding="utf-8")
        heads = [l[3:].strip() for l in text.splitlines() if l.startswith("## ")]
        for need in ("V5.57", "V5.56", "V5.55", "V5.5 ", "V5.44", "V5.43", "V5.42B", "V5.42 ", "V5.41", "V5.4 ", "V5.3", "V5.2", "V5.1", "V5 ",
                     "V4", "V3"):
            if not any((h + " ").startswith(need if need.endswith(" ") else need + " ") for h in heads):
                fails.append(f"CHANGELOG.md has no entry for {need.strip()}")
        if not heads or not heads[0].startswith("V5.57"):
            fails.append(f"first entry is {heads[:1]}, expected V5.57")
        os.chdir(tempfile.gettempdir())                             # works from any working folder
        app.nb.select(app.tabs["Settings"])
        app.named["Changelog"].invoke()
        pump(root, 4, 0.05)
        wins = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        if len(wins) != 1:
            fails.append(f"{len(wins)} popout windows after the click")
        else:
            w = wins[0]
            if w.resizable() != (True, True) if isinstance(w.resizable(), tuple) else False:
                fails.append("the popout is not resizable")
            body = app.cl_text.get("1.0", "end").strip().splitlines()
            if not body or not body[0].startswith("V5.57"):
                fails.append(f"popout starts with {body[:1]}")
            ranges = app.cl_text.tag_ranges("ver")
            if len(ranges) < 2 * 10:
                fails.append("version headings are not tagged")
            app.cl_text.yview_moveto(1.0)
            if app.cl_text.yview()[0] <= 0.0:
                fails.append("the popout does not scroll")
            app.named["Changelog"].invoke()                          # second click re-uses the window
            pump(root, 2, 0.05)
            if len([x for x in root.winfo_children() if isinstance(x, tk.Toplevel)]) != 1:
                fails.append("a second click opened a second window")
            w.destroy()
            pump(root, 2, 0.05)
            if [x for x in root.winfo_children() if isinstance(x, tk.Toplevel)]:
                fails.append("the popout did not close cleanly")
        print(f"   {len(heads)} versions in CHANGELOG.md, latest {heads[0]}")
    finally:
        os.chdir(cwd)
        close_app(app, old)
    return fails


# ---------------------------------------------------------------- 10. audio mode
def test_audio_mode():
    fails = []
    # setting saves and reloads
    app, old = new_app()
    try:
        if app.set_audio.get() != "Auto (V5.56)" or M.load_config()["audio_mode"] != "auto":
            fails.append("default audio mode is not Auto (V5.56)")
        app.set_audio.set("Legacy (V5.55)")
        app.flush_settings()
        if M.load_json(M.CONFIG_PATH, {}).get("audio_mode") != "legacy":
            fails.append("Legacy was not saved to the config")
        cfgpath = M.CONFIG_PATH
        # next to the V4/V5 placement option, same widget type
        cbs = [w for w in walk(app.set_inner) if isinstance(w, ttk.Combobox)]
        pl = next(w for w in cbs if str(w.cget("textvariable")) == str(app.set_place))
        au = next(w for w in cbs if str(w.cget("textvariable")) == str(app.set_audio))
        if abs(pl.winfo_rooty() - au.winfo_rooty()) > 120 or pl.winfo_class() != au.winfo_class():
            fails.append("Audio mode is not next to the placement option in the same style")
        app.root.tk.eval("foreach id [after info] {after cancel $id}")
        app.root.destroy()
        app2 = M.App(0, startup=False)
        pump(app2.root, 3)
        if app2.set_audio.get() != "Legacy (V5.55)":
            fails.append(f"reloaded audio mode is {app2.set_audio.get()}")
        app2.root.tk.eval("foreach id [after info] {after cancel $id}")
        app2.root.destroy()
    finally:
        M.restore_data_dir(old)
    # code path selection
    calls = []
    real_auto, real_leg = M.clip_audio_auto, M.clip_audio_legacy
    rec = {"path": "/fake/a.mp4", "audio": True}
    try:
        M.clip_audio_auto = lambda r, setting="auto": (calls.append(("auto", setting)), {"stream": 1, "lufs": -20.0, "note": "auto"})[1]
        M.clip_audio_legacy = lambda r: (calls.append(("legacy",)), {"stream": 0, "lufs": -18.0, "note": "legacy"})[1]
        cfg = dict(M.DEFAULT_CONFIG, game_audio_track={"valorant": "2", "cs2": "auto"})
        st = {}
        au = M.resolve_clip_audio(rec, dict(cfg, audio_mode="auto"), "valorant", st)
        if calls != [("auto", "2")] or au["note"] != "auto" or st.get("mode") != "auto":
            fails.append(f"auto mode path: calls {calls}, state {st}")
        calls.clear()
        st = {}
        au = M.resolve_clip_audio(rec, dict(cfg, audio_mode="legacy"), "valorant", st)
        if calls != [("legacy",)] or st.get("mode") != "legacy":
            fails.append(f"legacy mode path (track setting must be ignored): calls {calls}, state {st}")
        # error in Auto -> fallback
        calls.clear()
        st = {}

        def boom(r, setting="auto"):
            calls.append(("auto-error",))
            raise RuntimeError("simulated failure")
        M.clip_audio_auto = boom
        au = M.resolve_clip_audio(rec, dict(cfg, audio_mode="auto"), "cs2", st)
        if calls != [("auto-error",), ("legacy",)] or st.get("mode") != "legacy" or "simulated failure" not in " ".join(st.get("fallback", [])):
            fails.append(f"auto error did not fall back: calls {calls}, state {st}")
        # silent / missing result in Auto -> fallback
        for bad in ({"stream": 0, "lufs": None}, {"stream": None, "lufs": None}, {"stream": 0, "lufs": -80.0}):
            calls.clear()
            st = {}
            M.clip_audio_auto = lambda r, setting="auto", bad=bad: bad
            M.resolve_clip_audio(rec, dict(cfg, audio_mode="auto"), "cs2", st)
            if calls != [("legacy",)] or st.get("mode") != "legacy":
                fails.append(f"unusable Auto result {bad} did not fall back: {calls}")
        # a clip without sound never triggers anything
        calls.clear()
        M.resolve_clip_audio({"path": "x", "audio": False}, cfg, "cs2", {})
        if calls:
            fails.append("a clip without audio called an audio path")
    finally:
        M.clip_audio_auto, M.clip_audio_legacy = real_auto, real_leg
    # the V5.55 path is byte-for-byte the V5.55 function (loudest track), found in git history when available
    import inspect
    src = inspect.getsource(M.clip_audio_legacy)
    for needle in ("v > best[\"lufs\"]", "range(min(ns, 4))", "best.update(stream=i, lufs=v)"):
        if needle not in src:
            fails.append(f"legacy path lost V5.55 logic: {needle}")
    # plan log shows the mode; fallback after a silent output (guard) is logged
    try:
        import numpy as np
        tmpd = Path(tempfile.mkdtemp(prefix="montager_plan_"))
        old = M.use_data_dir(tmpd / "data")
        try:
            sp = tmpd / "t.mp3"
            M.synth_song(sp, 128.0)
            an = M.analyse_song(str(sp), 128.0)
            evs = M.fake_events()
            song = {"path": str(sp), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
            for mode, tag in (("auto", "[audio: auto V5.56]"), ("legacy", "[audio: legacy V5.55]")):
                plan = M.plan_montage(dict(M.DEFAULT_CONFIG, audio_mode=mode), "valorant", evs, song, an, 1, "auto", "optimal", [], [])
                txt = M.fmt_plan(plan, evs, None, [], [], None)
                if tag not in txt or (AUDIO_OTHER := M.AUDIO_TAGS["legacy" if mode == "auto" else "auto"]) in txt:
                    fails.append(f"plan log for {mode}: expected {tag}")
                if plan.get("audio_mode") != mode:
                    fails.append(f"plan audio_mode {plan.get('audio_mode')} != {mode}")
            # guard: a silent output re-renders once with Legacy and the plan says so
            plan = M.plan_montage(dict(M.DEFAULT_CONFIG, audio_mode="auto"), "valorant", evs, song, an, 1, "auto", "optimal", [], [])
            for tk_ in plan["takes"]:
                for sd in tk_["srcs"]:
                    sd["audio"] = True
            real_l, real_c = M.ebur128_lufs, M.clip_audio_legacy
            M.ebur128_lufs = lambda p, stream=None: None
            M.clip_audio_legacy = lambda r: {"stream": 1, "lufs": -19.0, "note": "legacy V5.55: loudest track"}
            redone = []
            try:
                ran = M.audio_guard(plan, "/fake/out.mp4", dict(M.DEFAULT_CONFIG), lambda: redone.append(1))
            finally:
                M.ebur128_lufs, M.clip_audio_legacy = real_l, real_c
            txt = M.fmt_plan_audio(M.fmt_plan(plan, evs, None, [], [], None), plan)
            if not ran or redone != [1] or plan["audio_mode"] != "legacy" or "[audio: legacy V5.55]" not in txt or \
                    "Auto audio failed, used Legacy V5.55" not in txt:
                fails.append(f"silent output did not trigger the Legacy fallback (ran {ran}, mode {plan['audio_mode']})")
            if any(sd["a_stream"] != 1 for tk_ in plan["takes"] for sd in tk_["srcs"]):
                fails.append("fallback did not switch the render's audio streams to the Legacy pick")
        finally:
            M.restore_data_dir(old)
    except Exception:
        fails.append("plan log check raised: " + traceback.format_exc()[-400:])
    return fails


CHECKS = (("1 mouse wheel", test_wheel), ("2/3 settings layout + footer", test_settings_layout), ("4 themes (12 combinations)", test_themes),
          ("5 more filters dropdown", test_dropdown), ("6 button feedback", test_feedback), ("7 random pick", test_random_pick),
          ("8 changelog popout", test_changelog), ("10 audio mode", test_audio_mode))


def main(only=None):
    bad = 0
    for name, fn in CHECKS:
        if only and not any(name.startswith(o) for o in only):
            continue
        t0 = time.time()
        try:
            fails = fn()
        except Exception:
            fails = ["raised: " + traceback.format_exc()[-600:]]
        print(f"{'PASS' if not fails else 'FAIL'}  {name}  ({time.time() - t0:.1f} s)")
        for f in fails[:12]:
            print("      -", f)
        bad += bool(fails)
    print("ALL PASSED" if not bad else f"{bad} CHECK(S) FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or None))
