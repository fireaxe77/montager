"""V6.5.2: clicking an empty Used cell flags the clip (no render):  xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v652.py"""
import datetime
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="montager_v652_"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import montage as M

FAILS = []


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def main():
    M.messagebox.askyesno = lambda *a, **k: True
    for f in (M.USED_FLAGS, M.USED_CLIPS):
        if f.exists():
            f.unlink()
    M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir=""))
    d = Path(tempfile.mkdtemp(prefix="mt_v652_"))
    clips = [d / f"c{k}.mp4" for k in range(3)]
    for c in clips:
        c.write_bytes(b"\0" * 10)
    app = M.App(0)
    root = app.root
    root.geometry("1300x900+0+0")
    app.nb.select(app.tabs["Manual"])
    root.update()
    app.clips = [{"path": str(c), "name": c.name, "folder": "x", "mtime": 1e9 + k, "dur": 10, "kills": 2, "ks": [], "used": ""} for k, c in enumerate(clips)]
    app.byp = {c["path"]: c for c in app.clips}
    app.ticked = {str(clips[2])}
    app.scan_active = False
    app.apply_filter()
    root.update()
    logs = []
    real_out = M.out
    M.out = lambda *a: (logs.append(" ".join(map(str, a))), real_out(*a))[1]
    tree = app.ctree
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    clock = [10000]

    def click(i):
        clock[0] += 5000                                          # synthetic event time: far apart, so two clicks are never a double-click
        x, y, w, h = tree.bbox(str(clips[i]), app.USED_COL)
        tree.event_generate("<Button-1>", x=x + w // 2, y=y + h // 2, time=clock[0])
        root.update()
    click(0)
    ud = M.used_dates()
    check(ud.get(M._pkey(str(clips[0]))) == today and len(ud) == 1, f"clicking an empty Used cell flags only that clip with today's date ({ud})")
    check(M.load_json(M.USED_FLAGS, {}).get(M._pkey(str(clips[0]))) == today, "the flag is saved in the used-flags file (the same one a render writes)")
    check(tree.set(str(clips[0]), "used") == "flagged by hand" and tree.set(str(clips[1]), "used") == "", "the row shows 'flagged by hand' (V6.7.4; was the date), the others stay empty")
    check(any(l == f"flagged {clips[0].name}" for l in logs), "log line: flagged <clip>")
    check(app.ticked == {str(clips[2])}, "the click did not tick or untick any row")
    # the weekly pick treats it as used
    ev = lambda p, k: {"path": p, "times": [10.0, 12.0], "rows": [12.4], "score": 10.0 + k, "plain": False}
    events = [ev(str(clips[0]), 0), ev(str(clips[1]), 1)] + [ev(f"/clips/z{k}.mp4", 2 + k) for k in range(30)]
    pick, notes = M.weekly_pick(list(events), {}, "optimal", "hype", time.time(), game="valorant")
    check(str(clips[0]) not in [e["path"] for e in pick] and any("already used" in n for n in notes), "the weekly pick treats the hand-flagged clip as used (not picked while unused clips suffice)")
    few = [ev(str(clips[0]), 0), ev(str(clips[1]), 1)]
    pick, notes = M.weekly_pick(list(few), {}, "optimal", "hype", time.time(), game="valorant")
    check(str(clips[0]) in [e["path"] for e in pick] and any("reused 1 previously used clip(s)" in n for n in notes) and M.used_dates()[M._pkey(str(clips[0]))] == today,
          "and the weekly reuse step can reuse it like any used clip (last use = today)")
    # clicking again unflags it
    click(0)
    check(M._pkey(str(clips[0])) not in M.used_dates() and tree.set(str(clips[0]), "used") == "" and any(l == f"unflagged {clips[0].name}" for l in logs),
          "clicking it again unflags it (V6.5.1 behaviour)")
    check(app.ticked == {str(clips[2])}, "ticks never changed")
    # Unflag all clears hand-flagged clips
    click(0)
    click(1)
    check(len(M.used_dates()) == 2, "two clips flagged by hand")
    app.unflag_all()
    for _ in range(8):                                             # a refill waits while the window was just resized (150 ms debounce)
        root.update()
        time.sleep(0.05)
    check(len(M.used_dates()) == 0 and [tree.set(str(c), "used") for c in clips] == [""] * 3, "Unflag all clears hand-flagged clips")
    check(app.ticked == {str(clips[2])}, "ticks still unchanged")
    M.out = real_out
    root.destroy()
    print("\nFAILED: %d" % len(FAILS) if FAILS else "\nALL OK")
    return 1 if FAILS else 0


sys.exit(main())
