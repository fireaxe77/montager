"""V6.7.6: Valorant killfeed region recovery and protection (generated data, no OCR needed, no render):
   xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v676.py
Also runs test_v674.py (which runs test_v672.py / test_v67.py) so every V6.7.4 check is repeated."""
import json
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

HERE = __import__("_root").find_root(__file__)          # repo root (tests/_root.py); this file lives in tests/
sys.path.insert(0, str(HERE))
import montage as M                                                                           # noqa: E402

FAILS = []


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


REG_A, REG_B = [0.57, 0.045, 1.0, 0.43], [0.56, 0.06, 1.0, 0.41]
HA, HB = M.region_stamp(REG_A), M.region_stamp(REG_B)
DAY_A, DAY_B = time.mktime((2026, 10, 1, 12, 0, 0, 0, 0, -1)), time.mktime((2026, 10, 5, 18, 30, 0, 0, 0, -1))


def build_cache(tmp, na=12, nb=5, store_region=True):
    """na clips with entries under hash A, nb other clips under hash B (current region B). Returns the clip records."""
    d = tmp / "clips"
    d.mkdir(exist_ok=True)
    recs, store = [], M.load_kills_cache()
    for i in range(na + nb):
        p = d / f"2025.10.{10 + i % 9} - 19.06.{i:02d}.mp4"
        p.write_bytes(b"x" * (50 + i))
        rec = {"path": str(p), "w": 1920, "h": 1080, "game": "valorant", "dur": 10}
        stamp, reg, day = (HA, REG_A, DAY_A) if i < na else (HB, REG_B, DAY_B)
        key = f"{M.file_key(str(p))}|valorant|{stamp}{M.ALGO}nb"
        e = {"ocr": [], "frames": 1, "game": "valorant", "v_off": 0.0, "marker": f"old{i}"}
        if store_region:
            e["region"] = reg
        store.put(key, e)
        os.utime(store._p(key), (day, day))
        recs.append(rec)
    return recs


def region_file(game="valorant"):
    return M.DATA / f"detect_{game}.json"


def set_region(reg):
    M.save_json(region_file(), {"region": reg, "ocr": True})


def captured(fn, *a):
    lines, real = [], M.out
    M.out = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        fn(*a)
    finally:
        M.out = real
    return "\n".join(lines)


def entry_files():
    return sorted(p.name for d in M.DATA.glob("kills_v*") for p in d.glob("*.json"))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="mt_v676_"))
    old = M.use_data_dir(tmp / "data")
    try:
        body(tmp)
    finally:
        M.restore_data_dir(old)
    if os.environ.get("V676_QUICK"):                          # development shortcut only
        print("(V676_QUICK: V6.7.4 checks skipped)")
        return 1 if FAILS else 0
    print("== V6.7.4 checks (test_v674.py, includes test_v672.py and test_v67.py) ==")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(HERE / "tests" / "test_v674.py")], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(HERE), env=env)
    fl = [ln for ln in r.stdout.splitlines() if "FAIL" in ln]
    check(r.returncode == 0 and "FAILED" not in r.stdout and ("ALL OK" in r.stdout or "FIXTURES OK" in r.stdout), "test_v674.py still passes" + ("" if r.returncode == 0 else " " + str(fl[:4]) + r.stderr[-300:]))
    print(("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED:\n  " + "\n  ".join(FAILS)))
    return 1 if FAILS else 0


def body(tmp):
    print("== where the region lives ==")
    set_region(REG_A)
    check(M.Detector("valorant").d["stamp"] == HA, "region_stamp(region) == Detector stamp (the hash inside every cache key)")
    recs = build_cache(tmp)
    set_region(REG_B)
    det = M.Detector("valorant")
    check(det.d["stamp"] == HB and len(entry_files()) == 17, "generated cache: 12 entries under hash A, 5 under B, current region B")

    print("== regioncheck ==")
    txt = captured(M.cmd_regioncheck, types.SimpleNamespace(game="valorant"))
    print("      " + txt.replace("\n", "\n      "))
    la = next((l for l in txt.splitlines() if HA in l and "entries" in l), "")
    lb = next((l for l in txt.splitlines() if HB in l and "entries" in l), "")
    check("12 entries" in la and "2026-10-01" in la and "STALE" in la and str(REG_A) in la, "group A: 12 entries, scan dates, region, marked stale")
    check("5 entries" in lb and "2026-10-05" in lb and "CURRENT" in lb and str(REG_B) in lb, "group B: 5 entries, scan dates, marked as the current region")
    check(f"hash {HB}" in txt and "default region" in txt and M.region_stamp(M.DEFAULT_REGION["valorant"]) in txt, "current region + hash and default region + hash printed")

    print("== regionrestore without --use changes nothing ==")
    before = (region_file().read_bytes(), entry_files(), sorted(p.name for p in M.DATA.glob("detect_*")))
    txt = captured(M.cmd_regionrestore, types.SimpleNamespace(game="valorant", use=None))
    after = (region_file().read_bytes(), entry_files(), sorted(p.name for p in M.DATA.glob("detect_*")))
    check(before == after and HA in txt and HB in txt and "default" in txt, "options listed (A, B, default), region file, entries and backups unchanged")

    print("== regionrestore --use A ==")
    txt = captured(M.cmd_regionrestore, types.SimpleNamespace(game="valorant", use=HA))
    print("      " + txt.replace("\n", "\n      "))
    bks = M.region_backups("valorant")
    check(M.Detector("valorant").d["stamp"] == HA and M._read_region(region_file()) == REG_A, "region is now A")
    check(len(bks) == 1 and M._read_region(bks[0]) == REG_B, "a dated backup of the previous (B) region file was written first")
    check("valid under this region: 12" in txt and "need a rescan: 5" in txt, "reports 12 valid / 5 to rescan")
    check(len(entry_files()) == 17, "no entry was deleted")
    txt = captured(M.cmd_regionrestore, types.SimpleNamespace(game="valorant", use="ocr00000000"))
    check("no region values are available" in txt and M._read_region(region_file()) == REG_A and len(M.region_backups("valorant")) == 1, "unknown hash: says so, changes nothing")
    txt = captured(M.cmd_regionrestore, types.SimpleNamespace(game="valorant", use="backup:" + bks[0].name))
    check(M._read_region(region_file()) == REG_B, "--use backup:<file> sets that file's region")
    txt = captured(M.cmd_regionrestore, types.SimpleNamespace(game="valorant", use="default"))
    check(M._read_region(region_file()) is None and len(M.region_backups("valorant")) == 3, "--use default resets (with a backup each time)")
    set_region(REG_B)

    print("== stale entries, no automatic Valorant rescan ==")
    held_calls = []
    M.REGION_PROMPT[0] = lambda held, cur: held_calls.append((len(held), cur))
    stale_jobs = [(r, "valorant") for r in recs[:12]]                  # scanned under A, current region B
    dets = {"valorant": M.Detector("valorant")}
    store = M.load_kills_cache()
    files0 = entry_files()
    txt = captured(lambda: setattr(sys.modules[__name__], "_todo", M._relink_or_explain(stale_jobs, dets, store, {})))
    check(_todo == [] and len(M.REGION_HELD) == 12 and held_calls == [(12, HB)] and "NOT rescanning" in txt and HA in txt and "12 clips" in txt,
          "calibration changed: nothing is rescanned, the prompt gets 12 clips and the hashes")
    check(entry_files() == files0, "stale entries survive (all 17 files still there)")
    todo = M._relink_or_explain(stale_jobs, dets, store, {}, region_ok=True)
    check(len(todo) == 12 and entry_files() == files0, "after an explicit confirmation they are rescanned; even then the old entries stay on disk")

    scans = []
    M.scan_clip = lambda path, rec, det, cfg: (scans.append(path), {"ocr": [], "frames": 1, "game": rec["game"], "v_off": 0.0, "secs": 0, "region": det.d["region"], "marker": "new"})[1]
    M.scan_clips = lambda cfg, rescan=False: [dict(r) for r in recs]
    M.ensure_bars = lambda cfg, force=False: None
    M.ocr_engine = lambda: None
    M.analyse_entry_real = M.analyse_entry
    n = captured(lambda: M.run_scan({}, ["valorant"], None, 0, False))
    check(scans == [] and len(entry_files()) == 17, "run_scan without confirmation scans no Valorant clip and deletes nothing")
    captured(lambda: M.run_scan({}, ["valorant"], [r["path"] for r in recs[:12]], 0, False, True))
    check(len(scans) == 12 and len(entry_files()) == 29, "run_scan with the confirmation scans the 12 and ADDS entries (17 -> 29), the stale ones stay")

    print("== backup of overwritten Valorant entries ==")
    r0 = recs[12]                                                       # under B = the current region: a forced rescan overwrites it
    key0 = M.kills_key(r0, "valorant", M.Detector("valorant"))
    first = store.get(key0)
    captured(lambda: M.run_scan({}, ["valorant"], [r0["path"]], 0, True))
    bk = M.load_json(M.VAL_BACKUP, {})
    clip = "|".join(key0.split("|")[:3])
    check(clip in bk and bk[clip]["e"].get("marker") == first["marker"] and store.get(key0)["marker"] == "new", "the old entry was copied to valorant_cache_backup.json before it was overwritten")
    store.put(key0, {"ocr": [], "frames": 1, "game": "valorant", "v_off": 0.0, "marker": "second"})
    captured(lambda: M.run_scan({}, ["valorant"], [r0["path"]], 0, True))
    bk2 = M.load_json(M.VAL_BACKUP, {})
    check(bk2[clip]["e"].get("marker") == first["marker"] and len(bk2) == 1, "the backup keeps the FIRST copy per clip and is never overwritten")

    print("== calibration dialog ==")
    try:
        import tkinter  # noqa: F401
    except ImportError:
        check(False, "tkinter missing - dialog checks did not run")
        return
    asked, ans = [], [False]
    M.messagebox.askyesno = lambda t, m, **k: (asked.append(m), ans[0])[1]
    M.messagebox.showinfo = lambda *a, **k: None
    M.messagebox.showerror = lambda *a, **k: None
    M.test_frame = lambda g, img, cfg=None: ([], [], [])
    M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir=""))
    app = M.App(0)
    app.root.update()
    dlg = M.CalibDialog(app)
    dlg.game.set("valorant")
    dlg.show_game()
    check("VALORANT" in dlg.big.get(), f"selected game shown in large text: '{dlg.big.get()}'")
    dlg.game.set("cs2")
    dlg.show_game()
    check("CS2" in dlg.big.get(), "the large label follows the selection")
    import numpy as np
    dlg.game.set("valorant")
    dlg.base, dlg.region = np.full((M.NORM_H, M.NORM_W, 3), 80, np.uint8), (1100, 60, 800, 400)
    set_region(REG_B)
    b0, n0 = region_file().read_bytes(), len(M.region_backups("valorant"))
    ans = [False]
    asked.clear()
    dlg.do_save()
    check(asked == ["Save this box as the VALORANT killfeed region?"] and region_file().read_bytes() == b0 and len(M.region_backups("valorant")) == n0, "No: nothing saved, no backup")
    ans = [True]
    dlg.do_save()
    check(M._read_region(region_file()) != REG_B and len(M.region_backups("valorant")) == n0 + 1 and M._read_region(M.region_backups("valorant")[-1]) == REG_B,
          "Yes: saved, and a dated backup of the previous region file was kept first")
    ans = [False]
    b1, n1 = region_file().read_bytes(), len(M.region_backups("valorant"))
    dlg.use_default()
    check(region_file().read_bytes() == b1 and len(M.region_backups("valorant")) == n1, "Reset to default asks first; No changes nothing")
    ans = [True]
    dlg.use_default()
    check(M._read_region(region_file()) is None and len(M.region_backups("valorant")) == n1 + 1, "Reset to default: back to the default region, with a backup")

    print("== GUI prompt for a held Valorant rescan ==")
    set_region(REG_B)
    for r in recs[:12]:                                                # make A-clips stale again: drop the entries written above under B
        M.load_kills_cache()._p(M.kills_key(r, "valorant", M.Detector("valorant"))).unlink(missing_ok=True)
    M.REGION_PROMPT[0] = app.region_prompt
    scans.clear()
    ans = [False]
    asked.clear()
    captured(lambda: M.run_scan({}, ["valorant"], None, 0, False))
    for _ in range(30):
        app.root.update()
        time.sleep(0.02)
    check(len(asked) == 1 and "12 Valorant clip(s)" in asked[0] and HA in asked[0] and HB in asked[0] and scans == [], "the prompt lists the clip count and the hashes; No = no scan")
    ans = [True]
    app._region_asked = None
    captured(lambda: M.run_scan({}, ["valorant"], None, 0, False))
    for _ in range(100):
        app.root.update()
        time.sleep(0.05)
        if len(scans) >= 12 and not app.busy:
            break
    check(len(scans) == 12, f"Yes: only then the 12 clips are rescanned ({len(scans)})")
    app.root.destroy()


if __name__ == "__main__":
    sys.exit(main())
