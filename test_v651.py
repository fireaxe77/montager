"""V6.5.1 weekly minimum length + unflagging used clips (generated data, stubbed render, no real render):
   xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v651.py"""
import datetime
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="montager_v651_"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tkinter as tk

import montage as M

FAILS = []


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


# the weekly pick of V6.5 (reference: "exactly as before" when enough unused material exists)
def weekly_pick_ref(events, cfg, target, style, now_ts=None):
    """V6.0 weekly / Auto clip pick: clips already used are never reused; this week's (last 7 days) new clips come first; if they
    do not reach the minimum length, older UNUSED clips of the same game follow - best multikills first, then best singles -
    only as many as needed. Returns (events, notes). No unused material at all = RuntimeError with the reason (skip)."""
    now_ts = now_ts or time.time()
    used = M.used_dates()
    unused = [e for e in events if M._pkey(e["path"]) not in used]
    notes = []
    if len(unused) < len(events):
        notes.append(f"{len({e['path'] for e in events} - {e['path'] for e in unused})} clips already used in a montage are not reused")
    if not unused:
        raise RuntimeError("no unused clips with kills left for this game (every clip with kills is already flagged used) - skipped; "
                           "scan new clips or use 'Include used clips' in Manual")

    def mt(e):
        try:
            return os.path.getmtime(e["path"])
        except OSError:
            return 0.0
    new = [e for e in unused if now_ts - mt(e) <= 7 * 86400]
    old = sorted([e for e in unused if e not in new], key=lambda e: (bool(e.get("plain")), -e["score"]))
    optimal = target in (None, "", "optimal", 0)
    need = M.OPT_RANGE[0] + 8.0 if optimal else float(target) * 1.1
    rn = style if style in M.RECIPES else "hype"
    est = lambda lst: sum(M.take_estimate(e, 0.47, rn) for e in lst)
    pick = list(new)
    if est(pick) < need:
        for e in old:
            if est(pick) >= need:
                break
            pick.append(e)
    n_old = len(pick) - len(new)
    notes.append(f"weekly pick: {len(new)} new clip event(s) this week + {n_old} older unused (best multikills first, then singles)"
                 + (f"; only ~{est(pick):.0f} s of unused material - the montage is shorter (nothing is padded)"
                    if est(pick) < (M.OPT_RANGE[0] if optimal else float(target)) - 0.5 else ""))
    return pick, notes



NOW = time.time()


def ev(k, score=10.0, plain=False):
    return {"path": f"/clips/e{k:03d}.mp4", "times": [10.0, 12.0], "rows": [12.4], "score": score, "plain": plain}


def reset_state():
    for f in (M.USED_FLAGS, M.USED_CLIPS):
        if f.exists():
            f.unlink()


def set_flags(events, date):
    flags = M.load_json(M.USED_FLAGS, {})
    for e in events:
        flags[M._pkey(e["path"])] = date
    M.save_json(M.USED_FLAGS, flags)


def set_history(game, clips, date="2026-09-01"):
    h = M.load_json(M.USED_CLIPS, {})
    h.setdefault(game, []).append({"date": date, "headline": "x", "recipe": "hype", "clips": sorted(clips)})
    M.save_json(M.USED_CLIPS, h)


def est(lst, style="hype"):
    return sum(M.take_estimate(e, 0.47, style) for e in lst)


def t_weekly():
    print("[1] weekly minimum 60 s")
    one = est([ev(0)])
    print(f"      one generated event takes ~{one:.1f} s")
    # (a) enough unused material: identical to the V6.5 pick
    reset_state()
    evs = [ev(k, score=50 - k) for k in range(40)]
    set_flags(evs[30:], "2026-08-01")
    a, na = M.weekly_pick(list(evs), {}, "optimal", "hype", NOW, game="valorant")
    b, nb = weekly_pick_ref(list(evs), {}, "optimal", "hype", NOW)
    check([e["path"] for e in a] == [e["path"] for e in b] and na == nb, f"enough unused material: same events and same notes as before ({len(a)} events, ~{est(a):.0f} s)")
    # (b) only ~23 s unused: reuse the oldest-used best clips, never the previous montage, never twice
    reset_state()
    n_unused = max(1, int(23 / one))
    unused = [ev(k, score=40 - k) for k in range(n_unused)]
    used = [ev(100 + k, score=30 + (k % 7)) for k in range(24)]
    for k, e in enumerate(used):
        set_flags([e], f"2026-0{1 + k // 8}-{10 + (k % 8):02d}")          # three age groups, oldest first
    prev = {used[0]["path"], used[1]["path"], used[2]["path"]}              # the previous montage used the very oldest clips
    set_history("valorant", prev, "2026-10-01")
    before = M.load_json(M.USED_FLAGS, {})
    pick, notes = M.weekly_pick(unused + used, {}, "optimal", "hype", NOW, game="valorant")
    reused = [e for e in pick if e in used]
    paths = [e["path"] for e in pick]
    check(est(unused) < 30, f"only ~{est(unused):.0f} s of unused material in the test")
    check(est(pick) >= 60, f"the pick reaches the 60 s minimum (~{est(pick):.0f} s)")
    check(len(paths) == len(set(paths)), "no clip is placed twice")
    check(not any(e["path"] in prev for e in pick), "no clip of the previous montage of the game is reused")
    dates = [M.used_dates()[M._pkey(e["path"])] for e in reused]
    left = [e for e in used if e not in reused and e["path"] not in prev]
    oldest_left = min((M.used_dates()[M._pkey(e["path"])] for e in left), default="9999")
    check(reused and max(dates) <= oldest_left, f"the reused clips are the oldest-used ones (reused dates {sorted(set(dates))}, oldest not reused {oldest_left})")
    check(any(f"reused {len(reused)} previously used clip(s) to reach the 60 s minimum" == n for n in notes), "the log line 'reused N previously used clip(s) to reach the 60 s minimum' is in the notes")
    check(M.load_json(M.USED_FLAGS, {}) == before, "picking does not change any used flag")
    # (c) the whole library under 60 s
    reset_state()
    small = [ev(k) for k in range(4)]
    set_flags(small[2:], "2026-07-01")
    pick, notes = M.weekly_pick(list(small), {}, "optimal", "hype", NOW, game="valorant")
    txt = " ".join(notes)
    check(len(pick) == 4 and "the whole library only gives" in txt and f"~{est(small):.0f} s" in txt and "2 unused + 2 reused" in txt,
          f"whole library under 60 s: makes what exists and says why with numbers: {notes[-1][:110]}")
    # previous montage excludes reuse even when the library is short
    reset_state()
    set_flags(small, "2026-07-01")
    set_history("valorant", {e["path"] for e in small[:2]}, "2026-10-01")
    pick, notes = M.weekly_pick(list(small), {}, "optimal", "hype", NOW, game="valorant")
    check(len(pick) == 2 and not any(e["path"] in {x["path"] for x in small[:2]} for e in pick), "previous-montage clips stay out even when the library is short")


def t_song():
    print("[1] song that cannot fit 60 s")
    real = M.analyse_song
    ans = {"/s/short.mp3": {"dur": 45.0, "beats": [0.5]}, "/s/long.mp3": {"dur": 150.0, "beats": [0.5]}, "/s/shorter.mp3": {"dur": 30.0, "beats": [0.2]}}
    M.analyse_song = lambda path, bpm=None: ans[path]
    logs = []
    real_out = M.out
    M.out = lambda *a: logs.append(" ".join(map(str, a)))
    try:
        s, an, sc, rn = M.weekly_song_fit({"path": "/s/short.mp3", "title": "Short"}, ans["/s/short.mp3"], {"total": 1},
                                          [({"path": "/s/shorter.mp3", "title": "Shorter"}, {"total": 5}), ({"path": "/s/long.mp3", "title": "Long"}, {"total": 4})])
        check(s["path"] == "/s/long.mp3" and sc == {"total": 4} and any("next best-ranked song" in x for x in logs), "a 45 s song is replaced by the next best-ranked song that fits 60 s")
        s, an, sc, rn = M.weekly_song_fit({"path": "/s/long.mp3", "title": "Long"}, ans["/s/long.mp3"], {"total": 1}, [])
        check(s["path"] == "/s/long.mp3", "a song that fits is kept")
        s, an, sc, rn = M.weekly_song_fit({"path": "/s/short.mp3", "title": "Short"}, ans["/s/short.mp3"], {"total": 1}, [({"path": "/s/shorter.mp3", "title": "Shorter"}, {"total": 5})])
        check(s["path"] == "/s/short.mp3", "no ranked song is long enough: the chosen one stays (logged)")
    finally:
        M.analyse_song = real
        M.out = real_out


def t_render():
    print("[1] used date only after a successful render (stubbed render)")
    reset_state()
    d = Path(tempfile.mkdtemp(prefix="mt_v651_"))
    clip_a, clip_b = "/clips/reuse_a.mp4", "/clips/fresh_b.mp4"
    set_flags([{"path": clip_a}], "2026-01-02")
    plan = {"game": "valorant", "seed": 1, "headline": "h", "recipe": "hype", "duration": 70.0, "song": {"path": "/s/x.mp3", "title": "X", "section_s": 100},
            "takes": [{"path": clip_a}, {"path": clip_b}], "notes": []}
    cfg = dict(M.load_config(), output_root=str(d / "out"), sync_report=False)
    M.save_json(M.CONFIG_PATH, cfg)
    saved = {k: getattr(M, k) for k in ("make_plan", "render_plan", "audio_guard", "quality_check")}
    M.make_plan = lambda *a, **k: (plan, "plan text")
    M.audio_guard = lambda *a, **k: False
    M.quality_check = lambda *a, **k: None

    def bad_render(*a, **k):
        raise RuntimeError("render failed")
    M.render_plan = bad_render
    try:
        r = M.run_job("valorant", "render", force=True, weekly=True)
        check(r is None and M.used_dates()[M._pkey(clip_a)] == "2026-01-02" and M._pkey(clip_b) not in M.used_dates(), "a failed render changes no used date")
        M.render_plan = lambda plan, outfile, *a, **k: Path(outfile).write_bytes(b"video")
        r = M.run_job("valorant", "render", force=True, weekly=True)
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        check(r is not None and M.used_dates()[M._pkey(clip_a)] == today and M.used_dates()[M._pkey(clip_b)] == today, "after a successful render the reused clip gets today's used date")
    finally:
        for k, v in saved.items():
            setattr(M, k, v)


def t_gui():
    print("[2/3] Unflag all and click-to-unflag")
    M.messagebox.askyesno = lambda *a, **k: True
    reset_state()
    M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir=""))
    d = Path(tempfile.mkdtemp(prefix="mt_v651g_"))
    clips = [d / f"c{k}.mp4" for k in range(4)]
    for c in clips:
        c.write_bytes(b"\0" * 10)
    set_flags([{"path": str(clips[0])}, {"path": str(clips[1])}, {"path": str(clips[2])}], "2026-10-06")
    set_history("valorant", {str(clips[0])}, "2026-10-01")
    app = M.App(0)
    root = app.root
    root.geometry("1300x900+0+0")
    app.nb.select(app.tabs["Manual"])
    root.update()
    ud = M.used_dates()
    app.clips = [{"path": str(c), "name": c.name, "folder": "x", "mtime": 1e9 + k, "dur": 10, "kills": 2, "ks": [], "used": ud.get(M._pkey(str(c)), "")} for k, c in enumerate(clips)]
    app.byp = {c["path"]: c for c in app.clips}
    app.ticked = {str(clips[3])}
    app.scan_active = False
    app.apply_filter()
    root.update()
    logs = []
    real_out = M.out
    M.out = lambda *a: (logs.append(" ".join(map(str, a))), real_out(*a))[1]
    tree = app.ctree
    check([tree.set(str(c), "used") for c in clips] == ["2026-10-06"] * 3 + [""], f"the Used column shows the dates: {[tree.set(str(c), 'used') for c in clips]}")
    # click an empty Used cell: nothing
    x, y, w, h = tree.bbox(str(clips[3]), app.USED_COL)
    tree.event_generate("<Button-1>", x=x + w // 2, y=y + h // 2)
    root.update()
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    check(app.ticked == {str(clips[3])} and len(M.used_dates()) == 4 and M.used_dates().get(M._pkey(str(clips[3]))) == today and not any("unflagged" in l for l in logs),
          "clicking an empty Used cell flags the clip with today's date (V6.5.2), no tick change")
    # click a used date: only that clip is unflagged, ticks unchanged
    x, y, w, h = tree.bbox(str(clips[1]), app.USED_COL)
    tree.event_generate("<Button-1>", x=x + w // 2, y=y + h // 2)
    root.update()
    ud = M.used_dates()
    check(M._pkey(str(clips[1])) not in ud and M._pkey(str(clips[0])) in ud and M._pkey(str(clips[2])) in ud, "clicking a used date unflags only that clip (saved)")
    check(tree.set(str(clips[1]), "used") == "" and tree.set(str(clips[0]), "used") == "2026-10-06", "the row is refreshed, the others keep their dates")
    check(app.ticked == {str(clips[3])}, "the click did not tick or untick any row")
    check(any(l == f"unflagged {clips[1].name}" for l in logs), "log line: unflagged <clip>")
    # a flagged clip that only the montage history knows about is unflagged for good as well
    x, y, w, h = tree.bbox(str(clips[0]), app.USED_COL)
    tree.event_generate("<Button-1>", x=x + w // 2, y=y + h // 2)
    root.update()
    check(M._pkey(str(clips[0])) not in M.used_dates(), "a clip flagged by flag AND history stays unflagged")
    # Unflag all: asks, backs up, clears
    set_flags([{"path": str(clips[0])}, {"path": str(clips[1])}], "2026-10-07")
    for c in app.clips:
        c["used"] = M.used_dates().get(M._pkey(c["path"]), "")
    n_before = len(M.used_dates())
    asked = []
    M.messagebox.askyesno = lambda title, msg, **k: (asked.append(msg), False)[1]
    app.unflag_all()
    check(len(M.used_dates()) == n_before and asked and f"Unflag all {n_before} used clips (Valorant and CS2)?" == asked[0], f"No leaves everything as it is; the question reads '{asked[0] if asked else None}'")
    M.messagebox.askyesno = lambda *a, **k: True
    flags_before = M.USED_FLAGS.read_text(encoding="utf-8")
    app.unflag_all()
    root.update()
    backups = sorted(M.USED_FLAGS.parent.glob("used_flags_backup_*.json"))
    check(len(M.used_dates()) == 0 and M.load_json(M.USED_FLAGS, {}) == {}, "Unflag all clears every flag")
    check(len(backups) == 1 and backups[0].read_text(encoding="utf-8") == flags_before, f"a dated backup of the used-flags file was written first ({backups[0].name if backups else None})")
    check(any(l == f"unflagged {n_before} clips (backup: {backups[0].name})" for l in logs), "log line: unflagged N clips (backup: <file name>)")
    check([tree.set(str(c), "used") for c in clips] == [""] * 4, "the list is refreshed (no used dates left)")
    check(app.ticked == {str(clips[3])}, "Unflag all does not change the ticks")
    M.out = real_out
    root.destroy()


SECTIONS = {"weekly": t_weekly, "song": t_song, "render": t_render, "gui": t_gui}

if __name__ == "__main__":
    want = [a for a in sys.argv[1:] if not a.startswith("--")] or list(SECTIONS)
    for k in want:
        SECTIONS[k]()
    print("\nFAILED: %d" % len(FAILS) if FAILS else "\nALL OK")
    sys.exit(1 if FAILS else 0)
