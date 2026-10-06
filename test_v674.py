"""V6.7.4: Valorant = V6.5.2 (031cb64), cache validity, CS2 + length fix kept, Used column shows the montage title, trash column.
No real renders.  Needs a display for the GUI part:  xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v674.py
With montage_data next to montage.py the REAL cache is checked too; without it only fixtures run (said loudly, and the last line is then
NOT 'ALL OK': it is 'FIXTURES OK ... real-cache checks SKIPPED')."""
import datetime
import json
import os
import random
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REAL = "MONTAGER_DATA" not in os.environ and any((HERE / "montage_data").glob("kills_v*/*.json"))      # an empty folder (made by an import) is not a real cache
import montage as M                                                                           # noqa: E402
import test_v67 as T                                                                          # noqa: E402

FAILS = []
RAN = {"real": False}


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def sig_path(a):
    return T.sig(a), [k["t"] for k in a["kills"]]


# ------------------------------------------------------------------ 1. Valorant interpretation = 031cb64
def part_valorant(old):
    print("== VALORANT interpretation: branch vs 031cb64 ==")
    real = [(k, e) for k, e in T.cached_entries() if e.get("game") == "valorant"] if REAL else []
    diffs = [k for k, e in real if sig_path(old.analyse_entry(e, {}, "valorant")) != sig_path(M.analyse_entry(e, {}, "valorant"))]
    if REAL:
        RAN["real"] = True
        check(bool(real), f"real cache holds Valorant clips ({len(real)})")
        check(not diffs, f"{len(real)} real Valorant clips: kills, timestamps, deaths, revives, rejection reasons identical to 031cb64 ({len(diffs)} differ: {diffs[:3]})")
    else:
        print("  SKIPPED: no montage_data - the real Valorant clips were NOT compared (fixtures and generated clips only)")
    rng = random.Random(674)
    bad = nk = 0
    for _ in range(400):
        e = T.rand_entry(rng)
        for g in ("valorant", None):
            a0, a1 = old.analyse_entry(e, {}, g), M.analyse_entry(e, {}, g)
            nk += len(a1["kills"])
            bad += sig_path(a0) != sig_path(a1)
    check(bad == 0 and nk > 0, f"400 generated Valorant clips x 2 calls ({nk} kills): identical to 031cb64 ({bad} differ)")
    # the onset (gunshot) cache key and the killfeed cache stamp are the V6.5.2 ones
    f = Path(tempfile.mkdtemp(prefix="mt_v674_k_")) / "a.mp4"
    f.write_bytes(b"\0" * 20)
    rec = {"path": str(f), "game": "valorant", "audio": True, "a_stream": 1}
    check(M._onset_key(rec) == old.file_key(str(f)) + "o1", "Valorant gunshot cache key is still '<file>o1' (track a_stream)")
    check(M.ALGO == old.ALGO and M.DEFAULT_REGION["valorant"] == old.DEFAULT_REGION["valorant"], f"cache format {M.ALGO} and Valorant default region unchanged")

    print("== VALORANT fixture rows (knife kill, Clove self-revive, Sage resurrect): both reading paths ==")
    import cv2
    import numpy as np
    for nm in ("valorant_knife_kill.png", "valorant_clove_self_revive.png", "valorant_sage_resurrect.png"):
        im = cv2.imread(str(M.FIXTURES / nm))
        if im is None:
            check(False, f"fixture {nm} missing")
            continue
        big = cv2.resize(im, None, fx=2.4, fy=2.4, interpolation=cv2.INTER_CUBIC)
        canvas = np.full((360, 1100, 3), (70, 78, 86), np.uint8)
        canvas[40:40 + big.shape[0], 1100 - 20 - big.shape[1]:1100 - 20] = big
        kill = M.synth_row_frame("fireaxe", "enemy", w=1100, h=360, y=220)
        frames = [np.full_like(canvas, (70, 78, 86))] * 12 + [canvas] * 24 + [np.where(kill != (70, 78, 86), kill, canvas)] * 30
        o0, n0 = old.scan_frames(iter(frames))
        o1, n1 = M.scan_frames(iter(frames))
        same = json.dumps(o0, default=str, sort_keys=True) == json.dumps(o1, default=str, sort_keys=True) and n0 == n1
        a0 = old.analyse_entry({"ocr": o0, "frames": n0, "v_off": 0.0}, {}, "valorant")
        a1 = M.analyse_entry({"ocr": o1, "frames": n1, "v_off": 0.0}, {}, "valorant")
        check(same and sig_path(a0) == sig_path(a1), f"{nm}: identical raw rows ({len(o1)} OCR frames) and identical result ({len(a1['kills'])} kills, {len(a1['revives'])} revives)")


# ------------------------------------------------------------------ 1c. cache validity
def part_cache(old):
    print("== CACHE validity: entries written by 031cb64 are not rescanned ==")
    tmp = Path(tempfile.mkdtemp(prefix="mt_v674_cache_"))
    clips = []
    for i in range(12):
        p = tmp / f"2025.10.1{i % 10} - 19.06.{i:02d}.mp4"
        p.write_bytes(b"x" * (100 + i))
        clips.append(p)
    odata = Path(old.DATA)
    odata.mkdir(parents=True, exist_ok=True)
    keep = M.use_data_dir(tmp / "data")
    try:
        for label, region in (("default region", None), ("calibrated region", [0.55, 0.04, 1.0, 0.44])):
            for d in (odata, M.DATA):
                for g in ("valorant", "cs2"):
                    (d / f"detect_{g}.json").unlink(missing_ok=True)
                if region:
                    (d / "detect_valorant.json").write_text(json.dumps({"region": region, "ocr": True}), encoding="utf-8")
            shutil.rmtree(M.DATA / f"kills_v{M.CACHE_V}", ignore_errors=True)
            store = M.load_kills_cache()
            od = old.Detector("valorant")
            jobs = []
            for i, p in enumerate(clips):
                rec = {"path": str(p), "w": 1920, "h": 1080, "bars": bool(i % 3 == 0), "bar_sig": f"sig{i}" if i % 3 == 0 else ""}
                store.put(old.kills_key(rec, "valorant", od), {"ocr": [], "frames": 10, "game": "valorant", "v_off": 0.0})     # as 031cb64 wrote it
                jobs.append((rec, "valorant"))
            todo = M._relink_or_explain(jobs, {"valorant": M.Detector("valorant")}, store, {})
            check(not todo, f"{label}: 12 entries written by 031cb64 -> {len(todo)} marked for rescan")
            check(all(M.kills_key(r, "valorant", M.Detector("valorant")) == old.kills_key(r, "valorant", od) for r, _ in jobs), f"{label}: key identical to 031cb64's")
        # control: an entry written under another killfeed region IS marked (the check is not blind)
        (M.DATA / "detect_valorant.json").write_text(json.dumps({"region": [0.5, 0.1, 1.0, 0.5], "ocr": True}), encoding="utf-8")
        todo = M._relink_or_explain(jobs, {"valorant": M.Detector("valorant")}, store, {})
        check(len(todo) == len(jobs), f"control: entries of another region are marked for rescan ({len(todo)}/{len(jobs)})")
    finally:
        M.restore_data_dir(keep)

    if not REAL:
        print("  SKIPPED: no montage_data - the real cache was NOT checked")
        return
    RAN["real"] = True
    idx = M._cache_index()
    cur = M.Detector("valorant")
    detf = M.DATA / "detect_valorant.json"
    if detf.exists():
        shutil.copy2(detf, odata / "detect_valorant.json")
    else:
        (odata / "detect_valorant.json").unlink(missing_ok=True)
    check(old.Detector("valorant").d["stamp"] == cur.d["stamp"], f"real calibration: stamp {cur.d['stamp']} identical in 031cb64 and the branch ({'calibrated ' + str(cur.d['region']) if cur.calibrated else 'default region'})")
    clips_ = {}
    for (name, size, mt, g), lst in idx.items():
        if g == "valorant":
            clips_.setdefault((name, size, mt), []).extend(lst)
    stamps = {}
    for lst in clips_.values():
        for e in lst:
            stamps[e[3]] = stamps.get(e[3], 0) + 1
    default_stamp = "ocr" + __import__("hashlib").md5(repr([round(v, 4) for v in M.DEFAULT_REGION["valorant"]]).encode()).hexdigest()[:8]
    would = [k for k, lst in clips_.items() if not any(e[3] == cur.d["stamp"] and e[4] == M.ALGO[1:] for e in lst)]
    print(f"  real Valorant clips in the kills cache: {len(clips_)}; entries per killfeed-region stamp: {stamps}")
    print(f"  current stamp {cur.d['stamp']} ({'calibrated' if cur.calibrated else 'default region'}), default-region stamp {default_stamp}")
    print(f"  REAL VALORANT CLIPS THAT WOULD RESCAN ON FIRST LAUNCH (no entry under the current stamp): {len(would)} of {len(clips_)}")
    check(True, f"real Valorant clips that would rescan: {len(would)} of {len(clips_)}")


# ------------------------------------------------------------------ 2. CS2 + length fix (test_v672)
def part_cs2():
    print("== CS2 + length fix: every check of test_v672.py (which runs test_v67.py too) ==")
    import test_v672 as V
    keep_fails = (list(V.FAILS), list(T.FAILS))
    rc = V.main()
    check(rc == 0, "test_v672.py: all CS2 checks, the real 8-row Replay clip = 3 kills, slider 150 reaches the planner, Valorant regression")
    return keep_fails


# ------------------------------------------------------------------ 4 + 5. GUI
def part_gui():
    print("== Used column (montage title) and trash column ==")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        check(False, "tkinter missing - the GUI checks could not run")
        return
    tmp = Path(tempfile.mkdtemp(prefix="mt_v674_gui_"))
    keep = M.use_data_dir(tmp / "data")
    try:
        gui(tmp)
    finally:
        M.restore_data_dir(keep)


def gui(tmp):
    M.messagebox.askyesno = lambda *a, **k: True
    M.messagebox.showerror = lambda *a, **k: None
    M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir=""))
    d = tmp / "clips"
    d.mkdir()
    names = ["c0.mp4", "c1.mp4", "c2.mp4", "c3.mp4", "c4.mp4"]
    clips = [d / n for n in names]
    for c in clips:
        c.write_bytes(b"\0" * 10)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    pk = lambda p: M._pkey(str(p))
    # flags: c0 render today (title stored), c1 old flag + history title, c2 old flag without any title, c3 hand flag later, c4 unflagged
    M.mark_used([str(clips[0])], today, title="L_VAL_V6.7.2_2026-10-06")
    M.save_json(M.USED_FLAGS, dict(M.load_json(M.USED_FLAGS, {}), **{pk(clips[1]): "2026-09-01", pk(clips[2]): "2026-08-15"}))
    M.save_json(M.USED_CLIPS, {"valorant": [{"date": "2026-09-01", "headline": "h", "recipe": "r", "clips": [str(clips[1])], "title": "S_VAL_V6.5_2026-09-01"}]})
    info = M.used_info()
    check(info[pk(clips[0])] == (today, "L_VAL_V6.7.2_2026-10-06"), "a rendered flag shows the montage title")
    check(info[pk(clips[1])] == ("2026-09-01", "S_VAL_V6.5_2026-09-01"), "an older flag looks the title up in the montage history")
    check(info[pk(clips[2])] == ("2026-08-15", "2026-08-15"), "no title anywhere: the date")
    check(pk(clips[4]) not in info, "an unflagged clip has no entry")
    M.mark_used([str(clips[2])], "2026-08-20", title="X_VAL_V6.1_2026-08-20")
    M.save_json(M.USED_FLAGS, dict(M.load_json(M.USED_FLAGS, {}), **{pk(clips[2]): "2026-08-15"}))          # an older date than the stored title's: not that montage
    check(M.used_info()[pk(clips[2])][1] == "2026-08-15", "a title is only shown for the date it belongs to")
    M.save_json(M.USED_FLAGS, dict(M.load_json(M.USED_FLAGS, {}), **{pk(clips[2]): "2026-08-15"}))
    M.save_json(M.USED_TITLES, {k: v for k, v in M.load_json(M.USED_TITLES, {}).items() if k != pk(clips[2])})

    app = M.App(0)
    root = app.root
    root.geometry("1500x900+0+0")
    app.nb.select(app.tabs["Manual"])
    root.update()
    tree = app.ctree
    logs = []
    real_out = M.out
    M.out = lambda *a: (logs.append(" ".join(map(str, a))), real_out(*a))[1]
    recs = [{"path": str(c), "game": "valorant", "dur": 10, "w": 1920, "h": 1080, "audio": True} for c in clips]
    real_sc = M.scan_clips
    M.scan_clips = lambda cfg, rescan=False: [dict(r) for r in recs]
    try:
        app.m_game.set("valorant")
        app.run_task("clips", app.load_clips)
        for _ in range(200):
            root.update()
            time.sleep(0.05)
            if not app.busy and len(app.byp) == len(clips):
                break
    finally:
        M.scan_clips = real_sc
    for _ in range(10):
        root.update()
        time.sleep(0.05)
    check(len(app.byp) == len(clips), f"load_clips filled the list with the {len(clips)} clips")
    cell = lambda i: tree.set(str(clips[i]), "used")
    check([cell(i) for i in range(5)] == ["L_VAL_V6.7.2_2026-10-06", "S_VAL_V6.5_2026-09-01", "2026-08-15", "", ""], f"Used column through load_clips: {[cell(i) for i in range(5)]}")
    check(all(tree.set(str(c), "trash") == app.TRASH_GLYPH for c in clips), "every row shows the trash symbol")
    cols = list(tree["columns"])
    check(cols[-1] == "trash" and cols[-2] == "open", f"trash is the last column (columns {cols})")
    check(int(tree.column("used", "width")) >= 200 and int(tree.column("trash", "width")) <= 48, "Used column is wide, trash column is narrow")

    # sorting by Used: by date internally
    app.sort_by(tree, "used")
    asc = [Path(i).name for i in tree.get_children()]
    app.sort_by(tree, "used")
    desc = [Path(i).name for i in tree.get_children()]
    dated = [n for n in desc if n in ("c0.mp4", "c1.mp4", "c2.mp4")]
    check(dated == ["c0.mp4", "c1.mp4", "c2.mp4"] and [n for n in asc if n in ("c0.mp4", "c1.mp4", "c2.mp4")] == ["c2.mp4", "c1.mp4", "c0.mp4"],
          f"sorting by Used follows the date, not the title (up {asc}, down {desc})")
    app.sorts.pop(str(tree), None)
    app.apply_filter()
    root.update()

    clock = [10000]

    def click(i, col):
        clock[0] += 5000
        x, y, w, h = tree.bbox(str(clips[i]), col)
        tree.event_generate("<Button-1>", x=x + w // 2, y=y + h // 2, time=clock[0])
        root.update()
    app.ticked = {str(clips[3])}
    click(4, app.USED_COL)
    check(cell(4) == "flagged by hand" and M.used_info()[pk(clips[4])][1] == "flagged by hand", "a clip flagged by hand shows 'flagged by hand'")
    check(app.ticked == {str(clips[3])}, "the flag click did not tick or untick anything")
    click(4, app.USED_COL)
    check(cell(4) == "" and pk(clips[4]) not in M.used_info(), "click on the title unflags it again")
    click(0, app.USED_COL)
    check(cell(0) == "" and pk(clips[0]) not in M.load_json(M.USED_TITLES, {}), "click-to-unflag works on a titled flag (title entry removed too)")
    click(0, app.USED_COL)
    check(cell(0) == "flagged by hand", "click-to-flag works again")
    n = len(M.used_dates())
    app.unflag_all()
    for _ in range(8):
        root.update()
        time.sleep(0.05)
    bk = sorted(M.DATA.glob("used_flags_backup_*.json"))
    check(len(M.used_dates()) == 0 and [cell(i) for i in range(5)] == [""] * 5 and bk and len(json.loads(bk[-1].read_text())) == n,
          f"Unflag all clears everything and the backup holds the {n} flags")
    check(app.ticked == {str(clips[3])}, "ticks unchanged by every Used click and Unflag all")

    # ---- trash
    M.mark_used([str(clips[1]), str(clips[2])], today, title="T_VAL_V6.7.4_2026-10-06")
    store = M.load_kills_cache()
    rec1 = recs[1]
    fk1 = M.file_key(rec1["path"])
    key1 = M.kills_key(rec1, "valorant", M.Detector("valorant"))
    store.put(key1, {"ocr": [], "frames": 1, "game": "valorant", "v_off": 0.0})
    store.put(M.kills_key(recs[2], "valorant", M.Detector("valorant")), {"ocr": [], "frames": 1, "game": "valorant", "v_off": 0.0})
    M.save_json(M.CLIPS_CACHE, {fk1: dict(rec1), M.file_key(recs[2]["path"]): dict(recs[2])})
    app.apply_filter()
    root.update()
    asked, trashed = [], []
    M.messagebox.askyesno = lambda title, msg, **k: (asked.append(msg), True)[1]

    def stub_ok(path):
        trashed.append(path)
        os.remove(path)                                            # a stub: the file is gone, nothing else
    M.trash_file = stub_ok
    app.ticked = {str(clips[3])}
    logs.clear()
    click(1, app.TRASH_COL)
    check(asked == [f"Move {clips[1].name} to the Recycle Bin?"], f"the question reads 'Move <file name> to the Recycle Bin?' ({asked})")
    check(trashed == [str(clips[1])] and not tree.exists(str(clips[1])) and str(clips[1]) not in app.byp and all(c["path"] != str(clips[1]) for c in app.clips),
          "Yes: the clip went to the (stub) bin and its row is gone")
    check(key1 not in M.load_kills_cache() and fk1 not in M.load_json(M.CLIPS_CACHE, {}), "its scan-cache entries are dropped")
    check(M.kills_key(recs[2], "valorant", M.Detector("valorant")) in M.load_kills_cache() and M.file_key(recs[2]["path"]) in M.load_json(M.CLIPS_CACHE, {}), "other clips' cache entries stay")
    check(pk(clips[1]) not in M.used_dates() and pk(clips[1]) not in M.load_json(M.USED_TITLES, {}) and pk(clips[2]) in M.used_dates(), "its used flag is gone, the others stay")
    check(f"moved to Recycle Bin: {clips[1].name}" in logs, "log line: moved to Recycle Bin: <file name>")
    check(app.ticked == {str(clips[3])}, "the trash click did not tick or untick any row")
    # No keeps everything
    asked.clear()
    M.messagebox.askyesno = lambda *a, **k: (asked.append(a[1]), False)[1]
    click(2, app.TRASH_COL)
    check(tree.exists(str(clips[2])) and clips[2].exists() and len(trashed) == 1, "No: nothing happens")
    # failure keeps the row
    M.messagebox.askyesno = lambda *a, **k: True

    def stub_fail(path):
        raise OSError("access denied (test)")
    M.trash_file = stub_fail
    logs.clear()
    click(2, app.TRASH_COL)
    check(tree.exists(str(clips[2])) and str(clips[2]) in app.byp and clips[2].exists() and pk(clips[2]) in M.used_dates() and
          any("access denied (test)" in l for l in logs) and not any(l.startswith("moved to Recycle Bin") for l in logs), "failure: error logged, row, file and flag kept")
    # refused while a job runs
    M.trash_file = stub_ok
    asked.clear()
    for flag in ("busy", "scan_active"):
        setattr(app, flag, True)
        n0 = len(trashed)
        click(2, app.TRASH_COL)
        check(len(trashed) == n0 and not asked and tree.exists(str(clips[2])), f"refused while a job runs ({flag}): no question, nothing moved")
        setattr(app, flag, False)
    check(app.ticked == {str(clips[3])}, "ticks never changed")
    # the real trash function never deletes permanently
    src = Path(M.__file__).read_text(encoding="utf-8")
    body = src[src.index("def trash_file"):src.index("def forget_clip")]
    check("os.remove" not in body and "unlink" not in body and "rmtree" not in body and "SHFileOperationW" in src and "FOF_ALLOWUNDO" in src,
          "trash_file / the shell fallback use send2trash or SHFileOperationW with FOF_ALLOWUNDO (no os.remove / unlink in them)")
    M.out = real_out
    root.destroy()


def main():
    old = T.load_old()
    part_valorant(old)
    part_cache(old)
    part_gui()
    saved = (list(FAILS),)
    part_cs2()
    if not REAL:
        print("\nNO montage_data HERE: only fixtures and generated data ran; the real-cache checks (real Valorant clips identical to 031cb64, "
              "real rescan count, real 8-row Replay clip) were SKIPPED. Run this test on the PC with montage_data.")
    if FAILS or T.FAILS:
        print(f"\n{len(FAILS) + len(T.FAILS)} FAILED:\n  " + "\n  ".join(FAILS + T.FAILS))
        return 1
    print("\nALL OK" if REAL else "\nFIXTURES OK (real-cache checks SKIPPED - no montage_data; this is not 'ALL OK')")
    return 0


if __name__ == "__main__":
    sys.exit(main())
