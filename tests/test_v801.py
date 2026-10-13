"""V8.0.1 tests: R6S works without icon files. FAST unit tests only (seconds; no render, no corpus, no real clips, no OCR engine).
  0) title-bar version V8.0.1; changelog entry on top of both changelogs (and nothing else in them touched)
  1) empty icons folder: the R6S scan reads kills from synthetic OCR rows (no error), the entry is not an error; 'fireaxeO' is my name
  2) with icons present: template rows are used and the OCR rows still fill what the templates missed
  3) a cached icons-missing error is scanned again; selected uncached clips are scanned whatever the count
  4) Preview / Render on uncached selected clips: scan runs before the plan, CANNOT is printed only after it
  5) the Auto cap (R6S_AUTO_MAX) still applies to Auto runs only
  6) a clip that fails to scan is skipped and the rest continue; 0 kills logs 'R6S: no kill rows read'
  7) CS2 / Valorant frozen (V8.0.0 module vs this one)
  p) (V801_PLANS=1, slow) CS2 + Valorant dry plans, same seed, identical to V8.0.0
python tests\\test_v801.py   (parts: V801_PARTS=0,1,2,3,4,5,6,7)"""
import copy
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("t800", str(ROOT / "tests" / "test_v800.py"))
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)                      # reuses the V8.0.0 helpers (check / section / synthetic icons); its own main block does not run
M, cv2, np, check, section, TMP, LOG = T.M, T.cv2, T.np, T.check, T.section, T.TMP, T.LOG
PARTS = [x for x in os.environ.get("V801_PARTS", "0,1,2,3,4,5,6,7").split(",") if x]
CFG = copy.deepcopy(M.DEFAULT_CONFIG)
REGION_W, REGION_H = 806, 400


def synth_frames(n=45, first=3, last=40, text=("fireaxeO", "BuffSledge_25")):
    """Blank killfeed crops; a bright block (the row) is on screen from frame `first` to `last`."""
    out_ = []
    for f in range(n):
        fr = np.zeros((REGION_H, REGION_W, 3), np.uint8) + 25
        if first <= f <= last:
            cv2.rectangle(fr, (100, 100), (700, 128), (255, 255, 255), -1)
        out_.append(fr)
    return out_


def fake_ocr(texts):
    """ocr_frame stand-in: a row [killer] <icon> [victim] whenever the frame holds the bright block."""
    def f(fr):
        if int(fr.max()) < 200:
            return [], []
        boxes = [[110, 100, 250, 124, texts[0], 0.95, "g"], [470, 100, 650, 124, texts[1], 0.95, "r"]]
        blobs = [[300, 98, 70, 28, 0.9]]
        return boxes, blobs
    return f


class Patch:
    """Temporary module attribute swaps (restored on exit)."""
    def __init__(self, **kw):
        self.kw, self.old = kw, {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.old[k] = getattr(M, k)
            setattr(M, k, v)
        return self

    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(M, k, v)


def scan_synth(data_dir, texts=("fireaxeO", "BuffSledge_25"), n=45, frames_fn=None):
    det_keep = M.DATA
    M.DATA = data_dir
    M._R6S_ICON_CACHE.clear()
    try:
        det = M.Detector("r6s")
        fr = frames_fn() if frames_fn else synth_frames(n)
        with Patch(frame_stream=lambda *a, **k: iter(fr), ocr_frame=fake_ocr(texts)):
            return M.scan_clip("x.mp4", {"game": "r6s", "v_off": 0.0}, det, CFG)
    finally:
        M.DATA = det_keep
        M._R6S_ICON_CACHE.clear()


def part0():
    section("0) version + changelog")
    check("APP_VERSION is V8.0.1", M.APP_VERSION == "V8.0.1")
    cl = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    heads = [l for l in cl if l.startswith("## V")]
    check("CHANGELOG.md: V8.0.1 on top, then V7.7.7", heads[0].startswith("## V8.0.1") and heads[1].startswith("## V7.7.7"), str(heads[:2]))
    sm = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8").splitlines()
    sh = [l for l in sm if l.startswith("## V")]
    check("simple changelog: 'Rainbow Six Siege support' on top, then V7.7.7", sh[0].startswith("## V8.0.1") and "Rainbow Six Siege support" in sh[0] and sh[1].startswith("## V7.7.7"), str(sh[:2]))
    body = "\n".join(sm[sm.index(sh[0]):sm.index(sh[1])])
    check("simple entry has no technical words / on-hold blocks", not any(w in body.lower() for w in ("test", "known issue", "abandoned", "on hold", "def ", "r6s_")))


def part1():
    section("1) empty icons folder: OCR-only detection")
    d = TMP / "d1"
    (d / "r6s" / "icons").mkdir(parents=True)
    LOG.clear()
    e = scan_synth(d)
    check("no error entry (icons optional)", not e.get("error") and e.get("mode") == "ocr-only", str({k: e.get(k) for k in ("error", "mode")}))
    a = M.analyse_entry(e, CFG, "r6s")
    check("1 kill from the OCR rows: 'fireaxeO' -> BuffSledge_25", len(a["kills"]) == 1 and a["kills"][0]["victim"] == "BuffSledge_25", str(a["kills"]))
    check("kill time is the row's first appearance (~0.2 s)", abs(a["kills"][0]["t"] - 3 / 15) < 0.35, str(a["kills"][0]["t"]))
    check("the kill record has what the planner needs", all(k in a["kills"][0] for k in ("t", "ks", "hs", "row", "hits", "victim", "weapon", "box", "t_last", "needs_shot")))
    check("'fireaxeO' / 'fireaxe0' / 'flreaxeO' are my name", all(M.r6s_name_score(t) >= 80 for t in ("fireaxeO", "fireaxe0", "flreaxeO")))
    e2 = scan_synth(d, texts=("BuffSledge_25", "fireaxeO"))
    a2 = M.analyse_entry(e2, CFG, "r6s")
    check("my name on the victim side = death, no kill", a2["kills"] == [] and len(a2["deaths"]) == 1)
    e3 = scan_synth(d, texts=("SouthNoupi", "BTW-Parparinos"))
    check("someone else's row = no kill", M.analyse_entry(e3, CFG, "r6s")["kills"] == [])
    e4 = scan_synth(d, n=45, frames_fn=lambda: synth_frames(45, first=0, last=40))
    a4 = M.analyse_entry(e4, CFG, "r6s")
    check("a row already there at 0:00 is a pre-clip reject", a4["kills"] == [] and any("pre-clip" in r["reason"] for r in a4["rej"]))
    e5 = scan_synth(TMP / "nonexistent_data")
    check("a missing icons folder (no montage_data\\r6s at all) is the same: OCR only, no error", not e5.get("error") and len(M.analyse_entry(e5, CFG, "r6s")["kills"]) == 1)
    import json
    check("the entry is JSON-serialisable (kill cache)", bool(json.dumps(e)))
    check("no icon-missing text is logged by the scan itself", not any("icons missing" in l for l in LOG))


def part2():
    section("2) icons present: templates first, OCR as the fallback")
    d = TMP / "d2"
    (d / "r6s" / "icons").mkdir(parents=True)
    ia = d / "r6s" / "icons" / "k.png"
    T.mk_icon(ia, 21)
    icon = cv2.imdecode(np.fromfile(str(ia), np.uint8), cv2.IMREAD_GRAYSCALE)

    def frames():
        out_ = synth_frames(45)
        for f in range(3, 41):
            T.paste(out_[f], icon, 300, 100, seed=7)
        return out_
    reads = {"n": 0}

    def reader(fr_, m):
        reads["n"] += 1
        return [[0, 250, "fireaxe0", 0.95]], [[360, 560, "TplVictim", 0.95]]
    keep = M.r6s_read_band
    M.r6s_read_band = reader
    try:
        e = scan_synth(d, texts=("fireaxeO", "OcrVictim"), frames_fn=frames)
    finally:
        M.r6s_read_band = keep
    check("templates were used", e.get("mode") == "templates+ocr" and len(e["rows"]) >= 1 and reads["n"] >= 1, str(e.get("mode")))
    a = M.analyse_entry(e, CFG, "r6s")
    check("the template row is a kill; the same row read by OCR is not counted twice", len(a["kills"]) == 1 and a["kills"][0]["victim"] == "TplVictim", str([k["victim"] for k in a["kills"]]))
    e["rows"] = []
    a2 = M.analyse_entry(e, CFG, "r6s")
    check("no template hit at all: the OCR path still finds the kill", len(a2["kills"]) == 1 and a2["kills"][0]["victim"] == "OcrVictim")
    ent = {"rows": [T.row(30, 120, 91, T.reads("fireaxe0", "First"))], "ocr": [], "frames": 400, "v_off": 0.0, "game": "r6s"}
    check("template rows alone (no OCR frames) still analyse", len(M.analyse_entry(ent, CFG, "r6s")["kills"]) == 1)


def fake_recs(paths):
    return [{"path": str(p), "name": Path(p).name, "game": "r6s", "w": 1920, "h": 1080, "dur": 30.0, "fps": 60.0, "bars": False} for p in paths]


def run_scan_env(tmp, paths, cache_pre=None, scan_fn=None, auto=False):
    """run_scan on fake clips with a stub scan_clip; returns (list of scanned paths, cache)."""
    d = Path(tmp)
    (d / "r6s" / "icons").mkdir(parents=True, exist_ok=True)
    scanned = []
    recs = fake_recs(paths)
    keep_data, keep_which = M.DATA, M.shutil.which

    def sc(path, rec, det, cfg, scale=None):
        scanned.append(path)
        if scan_fn:
            return scan_fn(path)
        return {"v": M.CACHE_V, "names": ["fireaxe0"], "ocr": [], "rows": [], "frames": 10, "size": [1, 1], "region": det.d["region"], "v_off": 0.0, "game": "r6s",
                "best_name": 0.0, "best_vic": 0.0, "ocr_calls": 0, "secs": 0.0}
    M.DATA = d
    M.shutil.which = lambda x: "ffmpeg"
    M._R6S_ICON_CACHE.clear()
    try:
        with Patch(scan_clips=lambda cfg, rescan=False: recs, ensure_bars=lambda cfg, force=False: None, scan_clip=sc, ocr_engine=lambda: None):
            cache = M.load_kills_cache()
            det = M.Detector("r6s")
            for p, ent in (cache_pre or {}).items():
                r = next(r for r in recs if r["path"] == str(p))
                cache.put(M.kills_key(r, "r6s", det), ent)
            M.run_scan(dict(CFG, scan_workers=1), ["r6s"], [str(p) for p in paths])
            cache2 = M.load_kills_cache()
            return scanned, {Path(r["path"]).name: cache2.get(M.kills_key(r, "r6s", det)) for r in recs}
    finally:
        M.DATA, M.shutil.which = keep_data, keep_which
        M._R6S_ICON_CACHE.clear()


def mkfiles(root, n):
    root.mkdir(parents=True, exist_ok=True)
    ps = []
    for i in range(n):
        p = root / f"R6S clip {i:02d}.mp4"
        p.write_bytes(b"0" * 64)
        ps.append(p)
    return ps


def part3():
    section("3) cached icons-missing error is scanned again; selected clips are all scanned")
    ps = mkfiles(TMP / "p3", 3)
    err = {"error": M.R6S_MISSING_MSG, "rows": [], "ocr": [], "game": "r6s"}
    scanned, cache = run_scan_env(TMP / "d3", ps, cache_pre={ps[0]: err})
    check("the clip cached with the icons-missing error is scanned again", str(ps[0]) in scanned)
    check("... and its cache entry is a real entry now (no error)", cache[ps[0].name] and not cache[ps[0].name].get("error"))
    check("uncached clips are scanned", str(ps[1]) in scanned and str(ps[2]) in scanned)
    good = {"v": M.CACHE_V, "names": ["fireaxe0"], "ocr": [], "rows": [], "frames": 10, "size": [1, 1], "game": "r6s", "v_off": 0.0}
    scanned, _ = run_scan_env(TMP / "d3b", ps, cache_pre={ps[0]: good})
    check("a good cached clip is NOT scanned again", str(ps[0]) not in scanned and len(scanned) == 2)
    many = mkfiles(TMP / "p3many", 30)
    scanned, _ = run_scan_env(TMP / "d3c", many)
    check("30 selected uncached clips: all 30 scanned (no cap on selected clips)", len(scanned) == 30, str(len(scanned)))


def part4():
    section("4) Preview / Render: scan first, CANNOT only after it")
    ps = mkfiles(TMP / "p4", 2)
    order = []
    recs = fake_recs(ps)
    LOG.clear()

    def fake_scan(cfg, games=None, paths=None, *a, **k):
        order.append(("scan", len(paths or [])))
        LOG.append("scan finished")
        return len(paths or [])

    def fake_pool(cfg, game, paths=None):
        order.append(("pool", len(paths or [])))
        raise RuntimeError("0 usable kills (test)")
    keep_cfg = M.CONFIG_PATH
    M.CONFIG_PATH = TMP / "no_cfg.json"
    try:
        for mode in ("dry", "preview", "render"):
            order.clear()
            LOG.clear()
            with Patch(scan_clips=lambda cfg, rescan=False: recs, autodetect_dirs=lambda c: c, run_scan=fake_scan, game_pool=fake_pool):
                M.run_job("r6s", mode, force=True, paths=[str(p) for p in ps], seed=5)
            cannot = [i for i, l in enumerate(LOG) if l.startswith("CANNOT")]
            scan_i = LOG.index("scan finished") if "scan finished" in LOG else -1
            check(f"{mode}: scan of the 2 selected clips ran first, then the plan step", order[:2] == [("scan", 2), ("pool", 2)], str(order))
            check(f"{mode}: CANNOT {mode.upper()} is printed after the scan, not before", bool(cannot) and scan_i >= 0 and cannot[0] > scan_i, str(LOG[:4]))
    finally:
        M.CONFIG_PATH = keep_cfg


def part5():
    section("5) the Auto cap applies to Auto runs only")
    many = mkfiles(TMP / "p5", 30)
    recs = fake_recs(many)
    stubs = [{"path": r["path"], "unprobed": True, "game": "r6s"} for r in recs]
    with Patch(scan_clips=lambda cfg, rescan=False: stubs):
        sel = M.r6s_auto_scan_set(CFG, M.Detector("r6s"), M.load_kills_cache())
    check(f"Auto: at most R6S_AUTO_MAX ({M.R6S_AUTO_MAX}) uncached clips of 30", len(sel) == M.R6S_AUTO_MAX, str(len(sel)))
    scanned, _ = run_scan_env(TMP / "d5", many)
    check("a manual / selected run is not capped", len(scanned) == 30)


def part6():
    section("6) failing clip skipped, 0 kills logged with the region")
    ps = mkfiles(TMP / "p6", 3)

    def fn(path):
        if path.endswith("01.mp4"):
            raise RuntimeError("bad clip")
        return {"v": M.CACHE_V, "names": ["fireaxe0"], "ocr": [], "rows": [], "frames": 10, "size": [806, 400], "region": [0.58, 0.05, 1.0, 0.42], "v_off": 0.0, "game": "r6s",
                "best_name": 0.0, "best_vic": 0.0, "ocr_calls": 0, "secs": 0.0}
    LOG.clear()
    scanned, cache = run_scan_env(TMP / "d6", ps, scan_fn=fn)
    check("the bad clip logs one ERROR line and the other two are cached", sum("ERROR" in l and "01.mp4" in l for l in LOG) == 1 and cache[ps[0].name] and cache[ps[2].name] and not cache[ps[1].name])
    check("0 kills: 'R6S: no kill rows read in <clip>' with the region", sum(l.startswith("R6S: no kill rows read in") and "0.58" in l for l in LOG) == 2, str([l for l in LOG if "no kill rows" in l][:1]))
    check("one 'no icon templates, using OCR-only row detection' line per run", sum(l == "R6S: no icon templates, using OCR-only row detection" for l in LOG) == 1)


def part7():
    section("7) CS2 / Valorant frozen (V8.0.0 module vs this one)")
    T.part9(("V8.0.0-good", "main"), "V8.0")


def partp():
    T.partp("V8.0.0-good")


if __name__ == "__main__":
    for k, fn in (("0", part0), ("1", part1), ("2", part2), ("3", part3), ("4", part4), ("5", part5), ("6", part6), ("7", part7)):
        if k in PARTS:
            try:
                fn()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                check(f"part {k} ran without an exception", False, repr(ex))
    if os.environ.get("V801_PLANS") == "1":
        partp()
    print(f"\n{len(T.FAILS)} FAIL" if T.FAILS else "\nALL OK", f"({time.time() - T.T0:.1f} s)")
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if T.FAILS else 0)
