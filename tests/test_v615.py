"""V6.1.5 check (no render):  xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v615.py
The Manual status is ONE fixed-height line; the full summary goes to the log, once per change."""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="montager_v615_"))
import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))   # repo root (the file lives in tests/)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import montage as M

FAILS = []


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def main():
    M.messagebox.askyesno = lambda *a, **k: False
    M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir=""))
    app = M.App(0)
    root = app.root
    root.geometry("1300x900+0+0")
    app.nb.select(app.tabs["Manual"])

    def pump(sec):
        t_end = time.time() + sec
        while time.time() < t_end:
            root.update()
            time.sleep(0.03)

    def log_text():
        app.flush_log()
        return app.log.get("1.0", "end")

    def geo():
        return (app.m_status_lbl.winfo_height(), app.vpane.winfo_height(), app.log.winfo_height(), app.nb.winfo_height(),
                app.m_status_lbl.master.winfo_height(), root.winfo_width(), root.winfo_height())
    clips = []
    for k in range(30):
        c = {"path": f"/clips/clip{k:02d}.mp4", "name": f"clip{k:02d}.mp4", "kills": 4, "used": ""}
        clips.append(c)
    app.byp = {c["path"]: c for c in clips}
    long_plan = {"duration": 150.0, "recipe": "hype", "takes": [], "song": {"title": "Atlantis", "path": "/s/Atlantis.mp3", "section_s": 209.0},
                 "fit": {"usable": 26, "optimal": True, "song_short": ["clipA.mp4", "clipB.mp4", "clipC.mp4", "clipD.mp4", "clipE.mp4"],
                         "skipped": [(f"clip{k}.mp4", "no run-up / tail fits the song's beats") for k in range(4)]}}
    real = M.make_plan
    M.make_plan = lambda *a, **k: (long_plan, None)
    pump(0.5)
    app.ticked = set()
    app.update_status()
    pump(0.3)
    g0 = geo()
    print("  geometry with the empty status:", g0)
    app.ticked = {c["path"] for c in clips}
    app.update_status()
    pump(0.4)
    g1 = geo()
    short_est = app.m_status_disp.get()
    pump(3.0)                                                      # the estimate runs 700 ms later in a worker
    g2 = geo()
    final = app.m_status_disp.get()
    full_status = app.m_status.get()
    log = log_text()
    print("  one-line status:", final)
    check(g0 == g1 == g2, f"widget heights unchanged from short to long summary: {g0} / {g1} / {g2}")
    check("\n" not in final and len(final) < 200, "the status is one line without a line break")
    check("30 clips ticked" in final and "montage 150 s" in final and "Atlantis" in final and "hype" in final, "short text carries clips, kills, length, song and style")
    check("didn't fit" in log and "can't form a take" in log and "song section 209 s" in log and "26 usable events" in log,
          "the full summary (didn't fit, can't form a take and why, song section, usable events) is in the log")
    check("no run-up / tail fits the song's beats" in log, "the reason is in the log")
    n1 = log.count("ticked clips didn't fit")
    # identical summary again: not repeated
    app.update_status()
    pump(3.0)
    check(n1 == 1 and log_text().count("ticked clips didn't fit") == 1, "an identical summary is not written twice in a row")
    # a changed summary is written again
    long_plan["duration"] = 120.0
    app.update_status()
    pump(3.0)
    check(log_text().count("montage 120 s") == 1 and log_text().count("ticked clips didn't fit") == 2, "a changed summary is logged again")
    # a very long text is cut with an ellipsis on one line, height still the same
    app.m_status.set("x " * 600)
    pump(0.3)
    g3 = geo()
    disp = app.m_status_disp.get()
    check(g3 == g2 and disp.endswith("…") and "\n" not in disp, f"a 1200-character text is cut with an ellipsis, heights unchanged ({len(disp)} chars shown)")
    # narrow window: still one line
    root.geometry("1000x900+0+0")
    pump(0.5)
    app.m_status.set(full_status)
    pump(0.3)
    check(app.m_status_lbl.winfo_height() == g0[0], "the label stays one line in a narrow window")
    M.make_plan = real
    root.destroy()


main()
print("\nFAILED: %d" % len(FAILS) if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
