"""V9.3.0 tests (fast; no render, no real clips):
  0) title-bar version V9.3.0, both changelogs carry V9.3.0 on top
  1) sky colour: 200 seeds -> every Sky colour option comes up, none over 25 % (the distribution is printed); a Manual pick wins
  2) intro: the ext look's extruded edge follows the sky family (another family = another edge, the letters stay white); every other look draws exactly as in V9.2.1
  3) skies: half as many (one per 30 s, 12 s apart); organic patterns only (no bands / rings / rays / aurora), each moving on every frame; a sky lasts to its take's last frame
     (a failed frame holds the last good mask); white / black are flat (no gradient) with a visible pattern; the animation follows the song's local energy
  4) first kill: the check flags a take whose first kill (or its row) is outside the footage it shows, passes one that shows it with lead and tail; a notice row read as
     'util' never re-times a gun kill row (the 2026.01.20 - 13.13.35.15 case)
  5) the Manual Step 3 panel (needs a display): the V9.2.0 positions, Render the only big button (right edge), Intro label left of its tickbox, the three dropdowns one width,
     Last seed / Preview one size and apart, every control one height, nothing clipped or overlapping at 920 x 640 and 1600 x 900, the panel no taller than V9.2.0
  6) the PC stays usable: a job runs at below-normal priority on all but 2 physical cores and puts both back afterwards; the render's parts never above below-normal
python tests\\test_v930.py   (parts: V930_PARTS=0,1,2,3,4,5,6)"""
import copy
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v930_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402
import intro90 as I                                                                           # noqa: E402

PARTS = [x for x in os.environ.get("V930_PARTS", "0,1,2,3,4,5,6").split(",") if x]
FAILS = []


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def part0():
    print("0) version and changelogs")
    check("title-bar version V9.3.0", M.APP_VERSION == "V9.3.0")
    for f in ("CHANGELOG.md", "docs/CHANGELOG_SIMPLE.md"):
        txt = (ROOT / f).read_text(encoding="utf-8")
        i_ = txt.find("## V9.3.0")
        check(f"{f}: V9.3.0 is the newest entry", 0 <= i_ < txt.find("## V9.2.1"))


def part1():
    print("1) sky colour")
    for lean in (["hazy orange"], ["deep blue"], []):
        c = Counter(M.sky_variety_pick({"seed": s_}, lean)[0] for s_ in range(1, 201))
        print("     200 seeds, the song leans", lean or "nowhere", "->", dict(sorted(c.items(), key=lambda kv: -kv[1])))
        check(f"every option comes up, none over 25 % (lean {lean or '-'})", set(c) == set(M.manual_pick_choices("sky")[1:]) and max(c.values()) <= 50, str(c))
    fam, why = M.sky_family_for({"seed": 3, "pick_sky": "violet", "song": {}}, ["hazy orange"])
    check("a Manual Sky colour pick wins", fam == "violet" and "Manual" in why)


def _load_base_intro():
    d = TMP / "base921"
    d.mkdir(exist_ok=True)
    src = subprocess.run(["git", "show", "v9.2.1:intro90.py"], cwd=ROOT, capture_output=True).stdout
    (d / "intro90_921.py").write_bytes(src)
    spec = importlib.util.spec_from_file_location("intro90_921", str(d / "intro90_921.py"))
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    B.FONT_DIR = I.FONT_DIR
    return B


def part2():
    print("2) intro colour (ext look only)")
    edges = {}
    for fam in M.SKY_FAMILIES:
        lay, _n = I.build_layer("ext", "Аутоагрессия", "CS2 · SERIES #3", I.fam_palette(fam, M.SKY_FAMILIES, "ext"))
        a = np.asarray(lay)
        px_ = a[a[..., 3] > 250][:, :3].astype(int)
        edge_ = px_[px_.min(1) < 190]                      # the extruded edge (the letters are white)
        edges[fam] = tuple(int(x) for x in np.median(edge_, 0))
    check("every sky family gives the ext edge its own colour", len(set(edges.values())) == len(edges), str(edges))
    lay0, _n = I.build_layer("ext", "ILFTB", None, I.fam_palette("orange", M.SKY_FAMILIES, "ext"))
    a0 = np.asarray(lay0)
    check("the ext letters stay white (the brightest pixels are white / near white)", int(np.percentile(a0[a0[..., 3] > 250][:, :3].min(1), 99)) >= 200)
    B = _load_base_intro()
    pal = I.fam_palette("teal", M.SKY_FAMILIES, "hype")
    same = True
    for look in ("rgb", "glow", "serif", "shade", "hype"):
        a1 = np.asarray(I.build_layer(look, "Test Title", "CS2 · SERIES #3", pal)[0])
        b1 = np.asarray(B.build_layer(look, "Test Title", "CS2 · SERIES #3", pal)[0])
        same = same and np.array_equal(a1, b1)
    check("every other look draws exactly as in V9.2.1", same)


def part3():
    print("3) skies")
    check("half as many: one per 30 s, at most 6, at least 12 s apart", (M.SKY_PER_S_88, M.SKY_MAX_N_88, M.sky_spacing_for()) == (30.0, 6, 12.0) and M.sky_max_for(180) == 6)
    check("organic patterns only (no bands, rings, rays, aurora)", set(M.SKY_PATTERNS) == {"amoebas", "ink", "marble", "cells"})
    h, w = 108, 192
    an = M.sky_anim_params(0.6, 120, "hype", False)
    ok_move = True
    for pat in M.SKY_PATTERNS:
        g = M.sky_pattern_frames(pat, h, w, 60, 40, 5, [(0.2, 1.0)], an, seed=3)
        frs = [next(g) for _ in range(40)]
        ok_move = ok_move and not frs[0].any() and all(not np.array_equal(frs[i], frs[i + 1]) for i in range(6, 39)) and max(float(f.max()) for f in frs) > 0.1
    check("every pattern is zero before the kill, then moves on every frame", ok_move)
    for fam in ("white", "black"):
        gr = M.sky_family_grade(fam, 160)
        check(f"{fam} sky: flat (no gradient) with a pattern of another tone", gr["top"] == gr["bot"] and abs(gr["dark"]["y_add"] - gr["top"]["y_add"]) >= 25)
    check("a sky lasts to the end of its take (a failed frame holds the last good mask)", M.SKY_HOLD_LAST_ON[0] and "last_ = segm[i]" in (ROOT / "montage.py").read_text(encoding="utf-8"))
    keep = M.get_songmap
    bt = list(np.arange(0, 200, 0.5))
    M.get_songmap = lambda *a, **k: {"beats": bt, "energy": [0.9 if 100 <= t < 150 else 0.1 for t in bt]}
    try:
        calm = M.sky_local_feel({"song": {"path": "x.mp3", "start_t": 10.0}}, {"out_start": 20.0, "dur": 4.0})
        loud = M.sky_local_feel({"song": {"path": "x.mp3", "start_t": 10.0}}, {"out_start": 110.0, "dur": 4.0})
    finally:
        M.get_songmap = keep
    check("the animation follows the song's local energy (a calm stretch calm, a loud one hard)", calm[0] < 0.5 < loud[0] and calm[1] < loud[1], f"{calm} {loud}")


def part4():
    print("4) first kill")
    t_bad = {"path": "c.mp4", "kills": [3.13, 10.77], "rows": [3.13, 10.77], "victims": ["Ramzes", "sTmtry"],
             "segs": [[0.78, 3.92, 1.0, 188, 0], [9.77, 11.35, 1.0, 95, 0]]}
    t_ok = dict(t_bad, kills=[6.77, 10.77], rows=[6.77, 10.77], segs=[[6.2, 7.6, 1.0, 84, 0], [9.77, 11.35, 1.0, 95, 0]])
    keep = M._fk_clip_kills
    M._fk_clip_kills = lambda path, cfg: [(6.767, "Ramzes"), (10.767, "sTmtry")]
    try:
        bad = M.first_kill_audit({"takes": [t_bad]}, {"x": 1})
        ok = M.first_kill_audit({"takes": [t_ok]}, {"x": 1})
    finally:
        M._fk_clip_kills = keep
    check("a take that ends before its first kill (the analysis says 6.77 s, the plan 3.13 s) is flagged", len(bad) == 1 and "6.77" in bad[0], str(bad))
    check("a take that shows the kill with lead and tail passes", ok == [], str(ok))
    a = {"kills": [{"t": 3.133, "ks": 1.0, "victim": "Ramzes", "weapon": "util"}]}
    b = {"kills": [{"t": 6.867, "ks": 1.0, "victim": "Ramzes", "weapon": "gun"}]}
    M.cs2_late_rows_retime(a, b, "test")
    check("a notice row read as 'util' never re-times a gun kill row", b["kills"][0]["t"] == 6.867)
    a2 = {"kills": [{"t": 3.133, "ks": 1.0, "victim": "Ramzes", "weapon": "gun"}]}
    b2 = {"kills": [{"t": 6.867, "ks": 1.0, "victim": "Ramzes", "weapon": "gun"}]}
    M.cs2_late_rows_retime(a2, b2, "test")
    check("a real late-picked row of the same kind is still re-timed (V8.8 rule kept)", b2["kills"][0]["t"] == 3.133)


def part5():
    print("5) the Manual Step 3 panel")
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
        rb = app.named["manual:render"]
        row1, row2 = rb.master, app.named["Style"].master
        s3 = row1.master
        names1 = [str(w.cget("text")) if "text" in w.keys() else w.winfo_class() for w in row1.pack_slaves()]
        check("Render is the only big button", "Big" in str(rb.cget("style")) and all("Big" not in str(app.named[n].cget("style")) for n in ("manual:last_seed", "manual:preview")))
        for W, H in ((920, 640), (1600, 900)):
            app.root.geometry(f"{W}x{H}")
            for _ in range(25):
                app.root.update()
                time.sleep(0.01)
            x_ = lambda n: app.named[n].winfo_rootx()
            lab_x = {str(w.cget("text")): w.winfo_rootx() for f_ in (row1, row2) for w in f_.winfo_children() if isinstance(w, ttk.Label) and str(w.cget("text"))}
            order1 = [lab_x["Intro text"], x_("Intro text"), lab_x["Intro"], x_("Intro tickbox"), lab_x["Sky colour"], x_("Sky colour"), lab_x["Font"], x_("Font"), x_("manual:render")]
            seed = next(w for w in row2.winfo_children() if isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox))
            order2 = [lab_x["Length"], x_("Optimal length"), app.m_len_sc.winfo_rootx(), lab_x["Style"], x_("Style"), lab_x["Quality"], lab_x["Seed"], seed.winfo_rootx(),
                      x_("manual:last_seed"), x_("manual:preview")]
            check(f"{W}x{H}: row 1 in the V9.2.0 order (Intro text, Intro, Sky colour, Font, Render at the right)", order1 == sorted(order1), str(order1))
            check(f"{W}x{H}: row 2 in the V9.2.0 order (Length, Optimal, slider, Style, Quality, Seed, Last seed, Preview)", order2 == sorted(order2), str(order2))
            check(f"{W}x{H}: Render reaches the panel's right edge", abs((rb.winfo_rootx() + rb.winfo_width()) - (row1.winfo_rootx() + row1.winfo_width())) <= 1)
            ws = [app.named[n].winfo_width() for n in ("Sky colour", "Font", "Style")]
            check(f"{W}x{H}: the three dropdowns one width", max(ws) - min(ws) <= 1, str(ws))
            b1, b2 = app.named["manual:last_seed"], app.named["manual:preview"]
            check(f"{W}x{H}: Last seed and Preview one size, apart from each other", abs(b1.winfo_width() - b2.winfo_width()) <= 1 and b2.winfo_rootx() - (b1.winfo_rootx() + b1.winfo_width()) >= 3)
            hs = [app.named[n].winfo_height() for n in ("Intro text", "Sky colour", "Font", "Style")] + [seed.winfo_height()]
            check(f"{W}x{H}: the boxes one height", max(hs) - min(hs) <= 2, str(hs))
            clip = [w for f_ in (row1, row2) for w in f_.pack_slaves() if w.winfo_width() < w.winfo_reqwidth() - 1]
            check(f"{W}x{H}: nothing clipped", not clip and row2.winfo_reqwidth() <= row2.winfo_width(), str([str(w) for w in clip]))
            bx = [(w.winfo_rootx(), w.winfo_rootx() + w.winfo_width(), w.winfo_rooty(), w.winfo_rooty() + w.winfo_height()) for f_ in (row1, row2) for w in f_.pack_slaves()]
            over = [(a, b) for i, a in enumerate(bx) for b in bx[i + 1:] if a[0] < b[1] - 1 and b[0] < a[1] - 1 and a[2] < b[3] - 1 and b[2] < a[3] - 1]
            check(f"{W}x{H}: nothing overlaps", not over)
            check(f"{W}x{H}: the panel no taller than V9.2.0 (136 px)", s3.winfo_height() <= 136, str(s3.winfo_height()))
        app.root.destroy()
    finally:
        M.restore_data_dir(old)


def part6():
    print("6) the PC stays usable")
    import psutil
    me = psutil.Process()
    n0, a0 = me.nice(), me.cpu_affinity()
    M.job_quiet(True)
    n1, a1 = me.nice(), me.cpu_affinity()
    M.job_quiet(False)
    n2, a2 = me.nice(), me.cpu_affinity()
    n_log, n_phys = psutil.cpu_count(), psutil.cpu_count(logical=False)
    check("during a job: below-normal priority", os.name != "nt" or n1 == psutil.BELOW_NORMAL_PRIORITY_CLASS)
    check("during a job: 2 physical cores left free", len(a1) <= n_log - 2 * max(1, n_log // n_phys), f"{len(a1)} of {n_log}")
    check("afterwards: priority and cores as before", n2 == n0 and a2 == a0)
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("the render's parts / encoder never above below-normal (0x4000 / idle 0x40)", "SetPriorityClass(int(pr._handle), 0x4000)" in src and "0x8000" not in src)
    check("the final encode uses the p4 preset", M.NVENC_PRESET == "p4" and "p4" in M.enc_args(False, False, True))


for p in PARTS:
    globals()[f"part{p}"]()
print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
sys.exit(1 if FAILS else 0)
