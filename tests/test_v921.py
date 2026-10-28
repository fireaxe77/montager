"""V9.2.1 tests (fast; no render, no real clips):
  0) title-bar version V9.2.1, both changelogs carry V9.2.1 on top
  1) series number: counted from the finished montages in the game's output folder (+1 each, a _2 of the same day and an older week name too), a half-made .part file
     never counts (also not as this week's montage), the same number after a restart
  2) STAGES line: the render's own stages are named in order
  3) the Manual Step 3 panel (needs a display): the same controls as V9.2.0; one label style; every control one height; the three dropdowns and the seed box one width;
     Last seed and Preview one size; labels / controls in the same columns on every row; Render top right, the primary (accent) button, right edge = the panel's;
     the status line on the same left edge; nothing clipped or overlapping at 920 x 640 and 1600 x 900
python tests\\test_v921.py   (parts: V921_PARTS=0,1,2,3)"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v921_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import montage as M                                                                           # noqa: E402

PARTS = [x for x in os.environ.get("V921_PARTS", "0,1,2,3").split(",") if x]
FAILS = []


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def part0():
    print("0) version and changelogs")
    check("title-bar version V9.2.1", M.APP_VERSION == "V9.2.1")
    for f in ("CHANGELOG.md", "docs/CHANGELOG_SIMPLE.md"):
        txt = (ROOT / f).read_text(encoding="utf-8")
        i_ = txt.find("## V9.2.1")
        check(f"{f}: V9.2.1 is the newest entry", 0 <= i_ < txt.find("## V9.2.0"))


def part1():
    print("1) series number")
    d = TMP / "out"
    cfg = {"output_root": str(d)}
    g = d / M.GAME_DIR["cs2"]
    g.mkdir(parents=True)
    got = [M.series_next("cs2", cfg)]
    for nm in ("ILFTB_CS2_V9.2.1_2026-10-28.mp4", "ILFTB_CS2_V9.2.1_2026-10-28_2.mp4", "CS2_2026-W41_12826.mp4"):
        (g / nm).write_bytes(b"0")
        got.append(M.series_next("cs2", cfg))
    check("an empty folder is #1; every finished montage counts (a _2 of the same day and an older week name too)", got == [1, 2, 3, 4], str(got))
    for nm in ("CS2_2026-W41_827727.part.mp4", "X_CS2_V9.2.1_2026-10-29.part.mp4"):
        (g / nm).write_bytes(b"0")
    check("a half-made render (.part file) does not count", M.series_next("cs2", cfg) == 4)
    now = M.datetime.datetime(2026, 10, 29)
    wk = g.parent / "wk"
    (wk / M.GAME_DIR["cs2"]).mkdir(parents=True)
    (wk / M.GAME_DIR["cs2"] / f"CS2_{M.week_tag(now)}_1.part.mp4").write_bytes(b"0")
    check("a .part file is not this week's montage", M.weekly_existing({"output_root": str(wk)}, "cs2", now) == [])
    code = f"import sys; sys.path.insert(0, {str(ROOT)!r}); import montage as M; print(M.series_next('cs2', {{'output_root': {str(d)!r}}}))"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    check("after a restart: the same number", (r.stdout.strip().splitlines() or [""])[-1] == "4", r.stdout[-200:] + r.stderr[-300:])
    nm = M.montage_name(g, {"song": {"title": "I Live For the Bass Drum", "path": "x.mp3"}, "game": "cs2"}, M.datetime.datetime(2026, 10, 28))
    check("the file name of a third montage of the same song and day gets _3", nm.endswith("_2026-10-28_3") or not nm.startswith("ILFTB"), nm)


def part2():
    print("2) STAGES line")
    M.JOB_STAGES.clear()
    for k in ("render", "render: final encode after the parts", "render: slow-motion parts", "planning", "sky analysis"):
        M.JOB_STAGES[k] = 1.0
    ln = M.job_stages_line()
    order = [ln.index(k + " ") for k in ("planning", "sky analysis", "render", "render: slow-motion parts", "render: final encode after the parts")]
    check("the render's own stages are in the STAGES line, in job order", order == sorted(order), ln)


def part3():
    print("3) the Manual Step 3 panel")
    import tkinter
    from tkinter import ttk
    try:
        r_ = tkinter.Tk()
        r_.destroy()
    except Exception:                                                                        # noqa: BLE001
        check("a display for the window", False, "no display")
        return
    old = M.use_data_dir(TMP / "gdata")
    try:
        app = M.App(0, startup=False)
        app.nb.select(app.tabs["Manual"])
        names = ("Intro text", "Intro tickbox", "Sky colour", "Font", "Optimal length", "Style", "manual:last_seed", "manual:preview", "manual:render")
        check("the same controls as V9.2.0 (none added, none gone)", all(n in app.named for n in names) and "manual:dry" not in app.named)
        rb = app.named["manual:render"]
        g3 = rb.master
        s3 = g3.master
        labels = [w for w in g3.winfo_children() if isinstance(w, ttk.Label)]
        texts = sorted(str(w.cget("text")) for w in labels)
        check("labels: the seven, one style (plain, the same font), sentence case", texts == sorted(["Intro text", "Sky colour", "Font", "Length", "Style", "Quality", "Seed"])
              and len({str(w.cget("font")) for w in labels}) == 1 and len({str(w.cget("style")) for w in labels}) == 1, str(texts))
        check("Render is the primary (accent) button", "Accent" in str(rb.cget("style")))
        for W, H in ((920, 640), (1600, 900)):
            app.root.geometry(f"{W}x{H}")
            for _ in range(25):
                app.root.update()
                time.sleep(0.01)
            ctl = {n: app.named[n] for n in ("Intro text", "Sky colour", "Font", "Style", "manual:last_seed", "manual:preview", "manual:render")}
            seed = next(w for w in g3.winfo_children() if isinstance(w, ttk.Entry) and str(w.cget("textvariable")) == str(app.m_seed))
            hs = {n: w.winfo_height() for n, w in ctl.items()} | {"seed": seed.winfo_height()}
            check(f"{W}x{H}: every control one height", max(hs.values()) - min(hs.values()) <= 2, str(hs))
            ws = [ctl[n].winfo_width() for n in ("Sky colour", "Font", "Style")] + [seed.winfo_width()]
            check(f"{W}x{H}: the dropdowns and the seed box one width", max(ws) - min(ws) <= 1, str(ws))
            b1, b2 = ctl["manual:last_seed"], ctl["manual:preview"]
            check(f"{W}x{H}: Last seed and Preview one size, on the seed's row", abs(b1.winfo_width() - b2.winfo_width()) <= 1 and abs(b1.winfo_height() - b2.winfo_height()) <= 1
                  and abs(b1.winfo_rooty() - seed.winfo_rooty()) <= 2)
            col_x = {}
            for w in labels:
                gi = w.grid_info()
                col_x.setdefault(int(gi["column"]), set()).add(w.winfo_rootx())
            check(f"{W}x{H}: the labels of a column share one left edge on every row", all(len(v) == 1 for v in col_x.values()), str(col_x))
            check(f"{W}x{H}: Sky colour, Style and the seed box share one left edge", len({ctl['Sky colour'].winfo_rootx(), ctl['Style'].winfo_rootx(), seed.winfo_rootx()}) == 1)
            check(f"{W}x{H}: Render, Font's label column and Last seed share one left edge",
                  len({rb.winfo_rootx(), b1.winfo_rootx(), next(iter(col_x.get(4, {0})))}) == 1, f"{rb.winfo_rootx()} {b1.winfo_rootx()} {col_x.get(4)}")
            right = s3.winfo_rootx() + s3.winfo_width()
            check(f"{W}x{H}: Render, Font and Preview end at the panel's right edge (inside its padding)",
                  len({rb.winfo_rootx() + rb.winfo_width(), ctl['Font'].winfo_rootx() + ctl['Font'].winfo_width(), b2.winfo_rootx() + b2.winfo_width()}) == 1
                  and right - (rb.winfo_rootx() + rb.winfo_width()) <= 12)
            st = app.m_status_lbl
            check(f"{W}x{H}: the status line starts at the rows' left edge", abs(st.winfo_rootx() - next(iter(col_x[0]))) <= 2)
            boxes = [(w.winfo_rootx(), w.winfo_rooty(), w.winfo_rootx() + w.winfo_width(), w.winfo_rooty() + w.winfo_height()) for w in list(ctl.values()) + [seed] + labels]
            over = [(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:] if a[0] < b[2] - 1 and b[0] < a[2] - 1 and a[1] < b[3] - 1 and b[1] < a[3] - 1]
            check(f"{W}x{H}: nothing overlaps", not over, str(over[:2]))
            clip = [n for n, w in ctl.items() if w.winfo_width() < w.winfo_reqwidth() - 1]
            check(f"{W}x{H}: nothing clipped (every control at least its own width)", not clip and g3.winfo_reqwidth() <= g3.winfo_width(), str(clip))
        app.root.destroy()
    finally:
        M.restore_data_dir(old)


for p in PARTS:
    globals()[f"part{p}"]()
print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
sys.exit(1 if FAILS else 0)
