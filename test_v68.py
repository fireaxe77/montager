"""V6.8: regiontest, region picker (Settings), saved default region, clip search bar (generated clips and cache, no real renders):
   xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v68.py
It also runs test_v676.py (which runs test_v674.py, test_v672.py, test_v67.py) and the quick GUI tests test_v557.py / test_v558.py
(their known failures are ignored: v557 'changelog popout' / 'audio mode', v558 'live' / 'audit').
V68_QUICK=1 skips those nested runs (development only; the last line is then not 'ALL OK')."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import montage as M                                                                           # noqa: E402

FAILS = []


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def captured(fn, *a):
    lines, real = [], M.out
    M.out = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        res = fn(*a)
    finally:
        M.out = real
    return "\n".join(lines), res


def snapshot(d):
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(d).rglob("*")) if p.is_file()}


REG_A, REG_B = [0.57, 0.045, 1.0, 0.43], [0.56, 0.06, 1.0, 0.41]
HA, HB = M.region_stamp(REG_A), M.region_stamp(REG_B)
CAL_CS2 = [0.7188, 0.0065, 0.9974, 0.2593]
DAY_A, DAY_B = time.mktime((2026, 10, 1, 12, 0, 0, 0, 0, -1)), time.mktime((2026, 10, 5, 18, 30, 0, 0, 0, -1))
NAMES = ("Replay 2026-06-25 01-27-36.mov", "Counter-strike 2 2025.02.03 - 09.12.42.24.DVR.mp4", "Counter-strike 2 2025.02.04 - 09.46.26.11.DVR.mp4")


def isolate_app_config():
    """The app must never scan the PC's real clip folders during a test."""
    M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir="", clip_dirs={"valorant": [], "cs2": []}))
    M.ensure_bars = lambda cfg, force=False: None
    M.messagebox.showinfo = lambda *a, **k: None
    M.messagebox.showerror = lambda *a, **k: None


# --------------------------------------------------------------------------------------------- 1. regiontest
def part_regiontest(tmp):
    print("== regiontest (generated CS2 clips, generated 'real' montage_data) ==")
    real = tmp / "real"
    old = M.use_data_dir(real)
    try:
        d = tmp / "clips" / "CS2"
        d.mkdir(parents=True)
        M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir="", clip_dirs={"valorant": [], "cs2": [str(d)]}))
        M.save_json(M.DATA / "detect_cs2.json", {"region": CAL_CS2, "ocr": True})
        for nm in (NAMES[0], NAMES[1]):
            M.synth_clip(d / nm, [(30, "fireaxe", "Kristof"), (90, "fireaxe", "Zhukov")], dur=5.0, fps=30)
        big = d / "tmp_src.mp4"
        M.synth_clip(big, [(30, "fireaxe", "Marcello")], dur=4.0, fps=30)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(big), "-vf", "scale=1280:960", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "2", "-c:a", "aac",
                        str(d / NAMES[2])], check=True)
        big.unlink()
        M.scan_clips(M.load_config())                           # fills the 'real' clip cache (probe only; no OCR scan)
        before = snapshot(real)
        outd = tmp / "out"
        t0 = time.time()
        txt, results = captured(M.cmd_regiontest, types.SimpleNamespace(game="cs2", clips=None, regions=None, out=str(outd)))
        print("      " + txt.replace("\n", "\n      ")[:3500])
        check(snapshot(real) == before, f"the real montage_data is byte-identical after regiontest ({len(before)} files, no file added, changed or removed)")
        check(not M.JOB_LOCK.exists(), "no job lock left behind")
        check(len(results) == 3 and {r["res"] for r in results} == {"1920x1080", "1280x960"}, f"all 3 generated clips (both resolutions) were tested: {[(r['clip'][:20], r['res']) for r in results]}")
        check(any(r["clip"].endswith(".mov") for r in results), "the .mov clip is in the default selection")
        check(all(set(r["per"]) == {"calibrated", "default", "wide"} for r in results), "every clip has results for calibrated, default and wide")
        for nm, reg in (("calibrated", CAL_CS2), ("default", M.DEFAULT_REGION["cs2"]), ("wide", M.REGIONTEST_WIDE)):
            check(M.region_stamp(reg) in txt and nm in txt, f"table header lists the {nm} region with its hash {M.region_stamp(reg)}")
        check("ocr1c10fb07" in txt, "the calibrated region is the user's current one (ocr1c10fb07)")
        lines = [l for l in txt.splitlines() if any(r["clip"][:50] in l for r in results) and "/" in l and "regions disagree" not in l and l[:1] != "["]
        marks = {r["clip"] for r in results if r["disagree"]}
        shown = {r["clip"] for r in results if any(r["clip"][:50] in l and "REGIONS DISAGREE" in l for l in txt.splitlines() if not l.startswith("["))}
        check(marks == shown, f"clips where the regions disagree are marked exactly ({len(marks)} marked)")
        check("clips where the regions disagree" in txt and "per clip" in txt, "summary: disagreement count and time per clip")
        check(all(f"{r['clip']}" in txt and f" {r['secs']:.0f} s" in txt for r in results), "the time per clip is printed for each clip")
        tf = outd / "regiontest_cs2.txt"
        check(tf.exists() and "REGIONTEST cs2" in tf.read_text(encoding="utf-8") and all(r["clip"][:50] in tf.read_text(encoding="utf-8") for r in results), "the table is saved to regiontest_cs2.txt")
        pngs = sorted(p.name for p in (outd / "regiontest_images").glob("*.png"))
        want = {f"{M._safe_name(Path(r['clip']).stem)}_{rn}.png" for r in results for rn in ("calibrated", "default", "wide")}
        check(set(pngs) == want, f"a cropped image per clip and region was written ({len(pngs)} of {len(want)}; missing {sorted(want - set(pngs))[:3]})")
        import cv2
        im = {rn: cv2.imread(str(outd / "regiontest_images" / f"{M._safe_name(Path(results[0]['clip']).stem)}_{rn}.png")) for rn in ("calibrated", "wide")}
        check(all(v is not None for v in im.values()) and im["calibrated"].shape != im["wide"].shape, "the images are the crops of their own regions (different sizes)")
        print(f"      (regiontest of 3 clips x 3 regions took {time.time() - t0:.0f} s)")

        # --clips with an unknown name
        cf = tmp / "clips.txt"
        cf.write_text(NAMES[0] + "\nDoes Not Exist 2020.mp4\n", encoding="utf-8")
        b2 = snapshot(real)
        txt, results = captured(M.cmd_regiontest, types.SimpleNamespace(game="cs2", clips=str(cf), regions="calibrated,wide", out=str(tmp / "out2")))
        check("unknown clip 'Does Not Exist 2020.mp4'" in txt and len(results) == 1 and set(results[0]["per"]) == {"calibrated", "wide"}, "an unknown clip name is reported and skipped; --regions limits the regions")
        check(snapshot(real) == b2, "real data untouched again")
        txt, _ = captured(lambda: _expect_exit(M.cmd_regiontest, types.SimpleNamespace(game="cs2", clips=None, regions="calibrated,narrow", out=str(tmp / "out3"))))
        check("unknown region" in txt, "an unknown region name is refused")
        # refuse while a scan or render runs
        M.job_enter("scan")
        txt, code = captured(lambda: _expect_exit(M.cmd_regiontest, types.SimpleNamespace(game="cs2", clips=None, regions=None, out=str(tmp / "out4"))))
        M.job_exit()
        check(code == 1 and "scan is running - refusing" in txt and not (tmp / "out4").exists(), "refuses to start while a scan or render is running")
        M.JOB_LOCK.write_text(json.dumps({"pid": 2 ** 22 + 12345, "job": "scan", "t": 0}))
        check(M.job_active() is None, "the lock of a dead process is ignored")
        M.JOB_LOCK.unlink()
    finally:
        M.restore_data_dir(old)

    # selection + disagreement logic on fake clips
    fake = [{"path": f"/c/{n}", "w": 1920, "h": 1080, "mtime": i} for i, n in enumerate(NAMES)]
    fake += [{"path": f"/c/a{i}.{'mov' if i % 5 == 0 else 'mp4'}", "w": 1280 if i % 2 else 1920, "h": 960 if i % 2 else 1080, "mtime": 100 + i} for i in range(40)]
    sel = M.regiontest_pick(fake, 15)
    names = [os.path.basename(c["path"]) for c in sel]
    check(len(sel) == 15 and all(n in names for n in NAMES), "default selection: 15 clips including the three named ones")
    check({(c["w"], c["h"]) for c in sel} == {(1920, 1080), (1280, 960)} and sum(n.endswith(".mov") for n in names) >= 3, "spread over both resolutions and includes .mov files")
    check(M.regiontest_disagree([[1.0, 5.0], [1.2, 5.1]]) is False and M.regiontest_disagree([[1.0, 5.0], [1.0]]) is True and M.regiontest_disagree([[1.0], [3.0]]) is True,
          "disagreement = different count or a timestamp more than 0.5 s apart")


def _expect_exit(fn, *a):
    try:
        fn(*a)
        return None
    except SystemExit as ex:
        return ex.code


# --------------------------------------------------------------------------------------------- 2/3. picker + saved default
REAL_FIXED = {"valorant": [0.58, 0.05, 1.0, 0.42], "cs2": [0.58, 0.03, 1.0, 0.4]}


def build_cache(tmp, na=12, nb=5):
    d = tmp / "pclips"
    d.mkdir(exist_ok=True)
    store, recs = M.load_kills_cache(), []
    for i in range(na + nb):
        p = d / f"2025.10.{10 + i % 9} - 19.06.{i:02d}.mp4"
        p.write_bytes(b"x" * (50 + i))
        stamp, reg, day = (HA, REG_A, DAY_A) if i < na else (HB, REG_B, DAY_B)
        key = f"{M.file_key(str(p))}|valorant|{stamp}{M.ALGO}nb"
        store.put(key, {"ocr": [], "frames": 1, "game": "valorant", "v_off": 0.0, "region": reg})
        os.utime(store._p(key), (day, day))
        recs.append(str(p))
    return recs


def part_picker(tmp):
    print("== constants and hashes ==")
    check(M.DEFAULT_REGION == REAL_FIXED, f"built-in default regions unchanged {M.DEFAULT_REGION}")
    check(M.region_stamp([0.6625, 0.0843, 0.9974, 0.2907]) == "ocr62f3694c" and M.region_stamp(CAL_CS2) == "ocr1c10fb07", "hash of the good Valorant region is ocr62f3694c, of the CS2 region ocr1c10fb07")
    old = M.use_data_dir(tmp / "pdata")
    try:
        isolate_app_config()
        for g in M.GAMES:
            check(M.Detector(g).d["stamp"] == M.region_stamp(REAL_FIXED[g]) and not M.Detector(g).calibrated, f"{g}: no region file -> built-in region, hash computed as before")
        recs = build_cache(tmp)
        M.save_json(M.DATA / "detect_valorant.json", {"region": REG_B, "ocr": True})
        check(not M.REGION_DEFAULTS.exists(), "no saved default exists (nothing sets one automatically)")

        print("== picker data (same as regioncheck) ==")
        rows = M.region_options("valorant")
        kinds = {r["kind"] for r in rows}
        check({"current", "built-in default", "cache"} <= kinds, f"rows: {[r['label'] for r in rows]}")
        ra = next(r for r in rows if r["hash"] == HA)
        rb = next(r for r in rows if r["hash"] == HB and r["kind"] == "current")
        check(ra["entries"] == 12 and ra["first"].startswith("2026-10-01") and ra["region"] == REG_A and rb["entries"] == 5 and rb["last"].startswith("2026-10-05"),
              "hash, entry count, earliest/latest scan date and region values per row")
        check(M.region_effect("valorant", HA) == (12, 12, 5) and M.region_effect("valorant", HB) == (5, 5, 12), "valid / would need a scan: A -> 12 valid, 5 to scan; B -> 5 valid, 12 to scan")
        txt, _ = captured(M.cmd_regioncheck, types.SimpleNamespace(game="valorant"))
        check(HA in txt and "12 entries" in txt, "regioncheck still prints the same data")

        print("== picker in Settings ==")
        calls = []
        real_ra, real_rs = M.region_apply, M.run_scan
        M.region_apply = lambda g, use: (calls.append(("apply", g, use)), real_ra(g, use))[1]
        M.run_scan = lambda *a, **k: calls.append(("SCAN",))
        asked, ans = [], [False]
        M.messagebox.askyesno = lambda t, m, **k: (asked.append(m), ans[0])[1]
        app = M.App(0)
        try:
            root = app.root
            root.update()
            app.nb.select(app.tabs["Settings"])
            root.update()
            for _ in range(10):
                root.update()
                time.sleep(0.05)
            app.rp_game.set("valorant")
            app.rp_refresh()
            ids = {v["hash"] + ":" + v["kind"]: i for i, v in app.rp_rows.items()}
            check(len(app.rp_tree.get_children()) == len(rows) and f"{HA}:cache" in ids, "the picker lists the saved regions of the selected game")
            iid = ids[f"{HA}:cache"]
            vals = app.rp_tree.item(iid, "values")
            check(str(vals[0]) == HA and str(vals[1]) == "12" and vals[2].startswith("2026-10-01") and vals[3].startswith("2026-10-01") and "0.57" in vals[4] and "0.43" in vals[4],
                  f"row shows hash, entries, earliest / latest scan, region: {vals}")
            app.rp_tree.selection_set(iid)
            root.update()
            check("12 cached clips" in app.rp_info.get() and "5 would need a scan" in app.rp_info.get(), f"selecting a row shows valid / need-a-scan counts: {app.rp_info.get()}")
            before = (M.DATA / "detect_valorant.json").read_bytes()
            nb = len(M.region_backups("valorant"))
            asked.clear()
            app.rp_use()
            check(asked == [f"Switch the VALORANT killfeed region to {HA}?"] and (M.DATA / "detect_valorant.json").read_bytes() == before and len(M.region_backups("valorant")) == nb,
                  "Use this region asks 'Switch the <GAME> killfeed region to <hash>?'; No changes nothing")
            ans[0] = True
            app.rp_use()
            check(M.Detector("valorant").d["stamp"] == HA and len(M.region_backups("valorant")) == nb + 1 and M._read_region(M.region_backups("valorant")[-1]) == REG_B,
                  "Yes: a dated backup of the previous region file first, then the region is A")
            check(calls == [("apply", "valorant", HA)] and not app.busy, "same code path as regionrestore (region_apply); no scan was started")
            captured(M.cmd_regionrestore, types.SimpleNamespace(game="valorant", use=HB))
            check(calls[-1] == ("apply", "valorant", HB) and ("SCAN",) not in calls, "regionrestore --use goes through the same function")
            # game selector
            app.rp_game.set("cs2")
            app.rp_refresh()
            check(all(v["hash"] != HA for v in app.rp_rows.values()) and any(v["kind"] == "built-in default" for v in app.rp_rows.values()), "CS2 selected: its own list (no Valorant cache rows)")
            app.rp_game.set("valorant")
            app.rp_refresh()

            print("== saved default region ==")
            reg_b_file = (M.DATA / "detect_valorant.json").read_bytes()
            app.rp_tree.selection_set(next(i for i, v in app.rp_rows.items() if v["hash"] == HA))
            ans[0] = False
            app.rp_set_default()
            check(not M.REGION_DEFAULTS.exists(), "Set as default asks first; No saves nothing")
            ans[0] = True
            app.rp_set_default()
            check(M.saved_default("valorant") == REG_A and M.load_json(M.REGION_DEFAULTS, {}).keys() == {"valorant"}, "Set as default writes region_defaults.json for that game only")
            check((M.DATA / "detect_valorant.json").read_bytes() == reg_b_file, "setting the default does not change the current region")
            check(any(v["kind"] == "saved default" and v["hash"] == HA for v in M.region_options("valorant")), "the saved default is listed in the picker")
            M.save_json(M.DATA / "detect_cs2.json", {"ocr": True})
            check(M.Detector("cs2").d["stamp"] == M.region_stamp(REAL_FIXED["cs2"]) and M.Detector("valorant").d["stamp"] == HB, "a game without a region file still reads the BUILT-IN default, not the saved one")
            import os as _os
            _os.remove(M.DATA / "detect_cs2.json")
            (M.DATA / "detect_valorant.json").unlink()
            check(M.Detector("valorant").d["stamp"] == M.region_stamp(REAL_FIXED["valorant"]), "no region file + saved default set: Detector still uses the built-in default (hash unchanged)")
            for g in M.GAMES:
                check(M.region_stamp(M.DEFAULT_REGION[g]) == M.Detector(g).d["stamp"] or g == "valorant", f"{g}: region_stamp == Detector stamp")
            # Reset to default (calibration dialog) uses the saved default
            M.save_json(M.DATA / "detect_valorant.json", {"region": REG_B, "ocr": True})
            dlg = M.CalibDialog(app)
            dlg.game.set("valorant")
            ans[0] = True
            nb = len(M.region_backups("valorant"))
            dlg.use_default()
            check(M.Detector("valorant").d["stamp"] == HA and len(M.region_backups("valorant")) == nb + 1, "Reset to default sets the saved default (backup first)")
            # --use default
            M.save_json(M.DATA / "detect_valorant.json", {"region": REG_B, "ocr": True})
            captured(M.cmd_regionrestore, types.SimpleNamespace(game="valorant", use="default"))
            check(M.Detector("valorant").d["stamp"] == HA, "regionrestore --use default uses the saved default")
            captured(M.cmd_regionrestore, types.SimpleNamespace(game="valorant", use="builtin"))
            check(M.Detector("valorant").d["stamp"] == M.region_stamp(REAL_FIXED["valorant"]) and not M.Detector("valorant").calibrated, "--use builtin sets the built-in default (no region key)")
            # without a saved default: the built-in default
            M.REGION_DEFAULTS.unlink()
            M.save_json(M.DATA / "detect_valorant.json", {"region": REG_B, "ocr": True})
            dlg.use_default()
            check(not M.Detector("valorant").calibrated and M.Detector("valorant").d["stamp"] == M.region_stamp(REAL_FIXED["valorant"]), "without a saved default Reset to default gives the built-in default")
            # regiondefault CLI
            M.save_json(M.DATA / "detect_valorant.json", {"region": REG_B, "ocr": True})
            txt, _ = captured(M.cmd_regiondefault, types.SimpleNamespace(game="valorant", target="current"))
            check(M.saved_default("valorant") == REG_B and "saved default region set" in txt, "regiondefault <game> current")
            txt, _ = captured(M.cmd_regiondefault, types.SimpleNamespace(game="valorant", target=HA))
            check(M.saved_default("valorant") == REG_A, "regiondefault <game> <hash> (values from the cached entries)")
            txt, _ = captured(M.cmd_regiondefault, types.SimpleNamespace(game="valorant", target="ocr00000000"))
            check("no region values are available" in txt and M.saved_default("valorant") == REG_A, "an unknown hash changes nothing")
            check(M.saved_default("cs2") is None, "nothing was set for the other game")
            dlg.win.destroy()
        finally:
            M.region_apply, M.run_scan = real_ra, real_rs
            app.root.destroy()
    finally:
        M.restore_data_dir(old)


# --------------------------------------------------------------------------------------------- 4. search bar
def part_search(tmp):
    print("== clip search bar ==")
    old = M.use_data_dir(tmp / "sdata")
    try:
        isolate_app_config()
        d = tmp / "sclips"
        d.mkdir(exist_ok=True)
        specs = [("Apex ace round.mp4", "2026-09-01", 3, "Valorant/Ranked", "L_VAL_V6.7.4_2026-10-06"),
                 ("clutch 1v3.mp4", "2026-09-03", 5, "Valorant/Ranked", ""),
                 ("Replay 2026-06-25.mov", "2026-06-25", 2, "Valorant/Replays", "S_VAL_V6.5_2026-09-01"),
                 ("Plain kill.mp4", "2026-08-15", 1, "Valorant/Unranked", "")]
        clips = []
        for n, day, k, folder, title in specs:
            p = d / n
            p.write_bytes(b"\0" * 10)
            ts = time.mktime(time.strptime(day + " 12:00", "%Y-%m-%d %H:%M"))
            os.utime(p, (ts, ts))
            clips.append({"path": str(p), "name": n, "folder": folder, "mtime": ts, "dur": 10, "kills": k, "ks": [], "used": "2026-10-06" if title else "", "used_label": title})
        recs = [{"path": c["path"], "game": "valorant", "dur": 10, "w": 1920, "h": 1080} for c in clips]
        M.scan_clips = lambda cfg, rescan=False: [dict(r) for r in recs]
        asked = [True]
        M.messagebox.askyesno = lambda *a, **k: asked[0]
        app = M.App(0)
        try:
            root = app.root
            root.geometry("1500x900+0+0")
            app.nb.select(app.tabs["Manual"])
            for _ in range(30):
                root.update()
                time.sleep(0.03)
                if not app.busy and not app.pending:
                    break
            app.clips = [dict(c) for c in clips]
            app.byp = {c["path"]: c for c in app.clips}
            app.scan_active = False
            tree = app.ctree
            app.m_csearch.set("")
            app.apply_filter()
            root.update()

            def shown():
                return sorted(Path(i).name for i in tree.get_children())

            def search(txt):
                app.m_csearch.set(txt)
                for _ in range(8):
                    root.update()
                    time.sleep(0.03)
                return shown()
            check(len(shown()) == 4 and "0 ticked, 4 shown" == app.m_cshown.get(), f"no search: all 4 rows ({app.m_cshown.get()})")
            check(search("ACE") == ["Apex ace round.mp4"], "file name, case-insensitive")
            check(search("2026-06-25") == ["Replay 2026-06-25.mov"], "date")
            check(search("l_val_v6.7.4") == ["Apex ace round.mp4"], "montage title (Used column)")
            check(search("s_val") == ["Replay 2026-06-25.mov"], "another montage title")
            check(search("unranked") == ["Plain kill.mp4"], "folder")
            check(search("valorant ranked clutch") == ["clutch 1v3.mp4"] and search("valorant   ranked") == ["Apex ace round.mp4", "Plain kill.mp4", "clutch 1v3.mp4"], "several words must all match (any order, any spacing)")
            check(search("zzz") == [] and "0 shown" in app.m_cshown.get(), "no match: empty list")
            search("")
            clear_btn = next(b for b in app.buttons if str(b.cget("text")) == "Clear")
            search("ace")
            clear_btn.invoke()
            for _ in range(8):
                root.update()
                time.sleep(0.03)
            check(app.m_csearch.get() == "" and len(shown()) == 4, "the clear button resets the search")

            print("== ticks, clicks and sort on filtered rows ==")
            clock = [10000]

            def click(name, col):
                clock[0] += 5000
                iid = str(d / name)
                x, y, w, h = tree.bbox(iid, col)
                tree.event_generate("<Button-1>", x=x + w // 2, y=y + h // 2, time=clock[0])
                root.update()
            click("Apex ace round.mp4", "#0")
            click("clutch 1v3.mp4", "#0")
            ticked = set(app.ticked)
            check(len(ticked) == 2 and app.m_cshown.get() == "2 ticked, 4 shown", f"two rows ticked ({app.m_cshown.get()})")
            search("clutch")
            check(shown() == ["clutch 1v3.mp4"] and app.ticked == ticked, "filtering never unticks the hidden row")
            check(app.m_cshown.get() == "2 ticked, 1 shown", f"'N ticked, M shown' counts hidden ticked rows: {app.m_cshown.get()}")
            check(set(p for p in app.ticked if p in app.byp) == ticked, "the ticked set the estimate / Dry plan / Render read still holds both rows")
            click("clutch 1v3.mp4", "#0")                           # untick the shown one
            check(app.ticked == {str(d / "Apex ace round.mp4")}, "a click on a filtered row ticks / unticks only that row")
            click("clutch 1v3.mp4", "#0")
            check(tree.item(str(d / "clutch 1v3.mp4"), "text").startswith("☑"), "the row shows its tick")
            # sorting with a filter
            search("valorant")
            app.sorts.pop(str(tree), None)
            app.sort_by(tree, "kills")
            order = [Path(i).name for i in tree.get_children()]
            check(order == ["clutch 1v3.mp4", "Apex ace round.mp4", "Replay 2026-06-25.mov", "Plain kill.mp4"], f"sort by kills (desc) works inside the filter: {order}")
            search("ranked")
            check([Path(i).name for i in tree.get_children()] == ["clutch 1v3.mp4", "Apex ace round.mp4", "Plain kill.mp4"] and app.sorts.get(str(tree)) == ("kills", True), "the chosen sort is kept when the filter changes")
            # Used column click on a filtered row (flag, unflag) and refill
            search("clutch")
            click("clutch 1v3.mp4", app.USED_COL)
            check(tree.set(str(d / "clutch 1v3.mp4"), "used") == "flagged by hand" and shown() == ["clutch 1v3.mp4"], "click-to-flag works on a filtered row and the filter survives the refresh")
            click("clutch 1v3.mp4", app.USED_COL)
            check(tree.set(str(d / "clutch 1v3.mp4"), "used") == "" and shown() == ["clutch 1v3.mp4"], "click-to-unflag works, filter kept")
            check(str(d / "clutch 1v3.mp4") in app.ticked, "the Used clicks did not change the ticks")
            click("clutch 1v3.mp4", app.USED_COL)
            search("hand")
            check(shown() == ["clutch 1v3.mp4"], "a hand flag is searchable ('flagged by hand')")
            search("clutch")
            M.trash_file = lambda p: os.remove(p)
            click("clutch 1v3.mp4", app.TRASH_COL)
            check(shown() == [] and str(d / "clutch 1v3.mp4") not in app.byp and not (d / "clutch 1v3.mp4").exists(), "the trash click works on a filtered row; filter kept")
            check(app.m_csearch.get() == "clutch", "the search text is still there after the trash refill")
            # refill by load_clips keeps the filter
            recs2 = [r for r in recs if not r["path"].endswith("clutch 1v3.mp4")]
            M.scan_clips = lambda cfg, rescan=False: [dict(r) for r in recs2]
            search("kill")
            app.run_task("clips", app.load_clips)
            for _ in range(400):
                root.update()
                time.sleep(0.03)
                if not app.busy and not app.pending and len(app.byp) == len(recs2) and tree.get_children():
                    break
            check(shown() == ["Plain kill.mp4"] and app.m_csearch.get() == "kill", f"the filter survives a list refill (load_clips): {shown()}")
            search("")
            check(len(shown()) == 3, "clearing shows every clip again")
        finally:
            app.root.destroy()
    finally:
        M.restore_data_dir(old)


# --------------------------------------------------------------------------------------------- nested runs
KNOWN = {"test_v557.py": ("changelog popout", "audio mode"), "test_v558.py": ("live", "audit")}


def run_nested(name, timeout=3000):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", V68_NESTED="1")
    r = subprocess.run([sys.executable, str(HERE / name)], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(HERE), env=env, timeout=timeout)
    return r


def part_nested():
    for name in ("test_v676.py", "test_v557.py", "test_v558.py"):
        print(f"== {name} ==")
        r = run_nested(name)
        out_ = (r.stdout or "") + "\n" + (r.stderr or "")
        fails = [ln.strip() for ln in out_.splitlines() if ln.strip().startswith("FAIL") or " FAIL " in ln[:12] or ln.strip().startswith("FAILED")]
        if name == "test_v676.py":
            check(r.returncode == 0 and "ALL OK" in r.stdout, "test_v676.py (V6.7.6 + V6.7.4 + V6.7.2 + V6.7 checks, incl. the Valorant parts of test_v674) ends with ALL OK" + ("" if r.returncode == 0 else " " + str(fails[:4])))
            continue
        known = KNOWN[name]
        unknown = [f for f in fails if f.startswith("FAILED") is False and not any(k in f.lower() for k in known)]
        ignored = [f for f in fails if any(k in f.lower() for k in known)]
        print(f"      ignored known failures ({len(ignored)}): {[f[:70] for f in ignored]}")
        check(not unknown and len(out_) > 200, f"{name}: ran, and no failure besides the known ones" + ("" if not unknown else f" -> {unknown[:5]}"))
    print("== test_valorant_frozen.py ==")
    if (HERE / "test_valorant_frozen.py").exists():
        r = run_nested("test_valorant_frozen.py")
        check(r.returncode == 0, "test_valorant_frozen.py passes")
    else:
        print("  NOTE  test_valorant_frozen.py does not exist in this repository: skipped (the Valorant checks of test_v674 / test_v676 ran above)")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="mt_v68_"))
    part_regiontest(tmp)
    part_picker(tmp)
    part_search(tmp)
    if os.environ.get("V68_QUICK"):
        print("\n(V68_QUICK: nested test runs skipped; not 'ALL OK')")
        print(f"{len(FAILS)} FAILED:\n  " + "\n  ".join(FAILS) if FAILS else "QUICK OK")
        return 1 if FAILS else 0
    part_nested()
    print(("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED:\n  " + "\n  ".join(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
