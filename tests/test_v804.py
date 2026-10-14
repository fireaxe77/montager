"""V8.0.4 tests: Settings > Killfeed region > 'Scan all new clips (current region)'. FAST unit tests only (seconds; no render, no real scan).
  0) title-bar version V8.0.4; V8.0.4 on top of both changelogs
  1) new-clip selection per game: uncached + errored only; cached clips skipped; R6S unprobed stubs are new
  2) nothing new -> 'No new clips to scan for <game>' and no scan
  3) the job scans with the SAVED region, no cap (30 clips), cached clips skipped, errored ones rescanned, results in the normal cache
  4) one game failing does not stop the others
  5) the button exists in the region section (same style) and queues a background job
  6) frozen vs V8.0.3: CS2 / Valorant / R6S filter graphs + plan text, synthetic rows, tags, gaps (p: V804_PLANS=1 adds the slow dry-plan equality)
python tests\\test_v804.py   (parts: V804_PARTS=0,1,2,3,4,5,6)"""
import copy
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("t803", str(ROOT / "tests" / "test_v803.py"))
T3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T3)
T2, T = T3.T2, T3.T
M, check, section, TMP, LOG = T.M, T.check, T.section, T.TMP, T.LOG
PARTS = [x for x in os.environ.get("V804_PARTS", "0,1,2,3,4,5,6").split(",") if x]
CFG = copy.deepcopy(M.DEFAULT_CONFIG)
REFS = ("V8.0.3-good", "main")


def rec(path, game, **k):
    return dict({"path": str(path), "name": Path(path).name, "game": game, "w": 1920, "h": 1080, "dur": 30.0, "fps": 60.0, "bars": False}, **k)


def files(root, game, n):
    root.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(n):
        p = root / f"{game} clip {i:02d}.mp4"
        p.write_bytes(b"0" * 64)
        out.append(p)
    return out


GOOD = {"v": 5, "names": ["x"], "ocr": [], "rows": [], "frames": 10, "size": [1, 1], "game": "x", "v_off": 0.0}


class Env:
    """Temp data folder + stub scan_clips / scan_clip / ensure_bars; records what run_scan scanned and the region it scanned with."""
    def __init__(self, recs, tag):
        self.recs, self.tag = recs, tag
        self.scanned, self.regions = [], {}
        self.old = {}

    def __enter__(self):
        self.d = TMP / self.tag
        self.d.mkdir(exist_ok=True)
        for k, v in dict(DATA=self.d, scan_clips=lambda cfg, rescan=False: self.recs, ensure_bars=lambda cfg, force=False: None, ocr_engine=lambda: None,
                         scan_clip=self.sc).items():
            self.old[k] = getattr(M, k)
            setattr(M, k, v)
        self.old["which"] = M.shutil.which
        M.shutil.which = lambda x: "ffmpeg"
        M._R6S_ICON_CACHE.clear()
        M._R6S_UTIL_CACHE.clear()
        return self

    def sc(self, path, r, det, cfg, scale=None):
        self.scanned.append((r["game"], Path(path).name))
        self.regions[r["game"]] = list(det.d["region"])
        return dict(GOOD, game=r["game"], region=det.d["region"], best_name=0.0, best_vic=0.0, ocr_calls=0, secs=0.0)

    def __exit__(self, *a):
        for k, v in self.old.items():
            if k == "which":
                M.shutil.which = v
            else:
                setattr(M, k, v)
        M._R6S_ICON_CACHE.clear()
        M._R6S_UTIL_CACHE.clear()


def put(env, r, entry):
    M.load_kills_cache().put(M.kills_key(r, r["game"], M.Detector(r["game"])), entry)


def part0():
    section("0) version + changelog")
    check("APP_VERSION is V8.0.4", M.APP_VERSION == "V8.0.4")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.0.4 then V8.0.3", cl[0].startswith("## V8.0.4") and cl[1].startswith("## V8.0.3"), str(cl[:2]))
    sm = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8").splitlines()
    sh = [l for l in sm if l.startswith("## V")]
    check("simple changelog (Settings text): 'Scan all new clips button', then V8.0.3", "Scan all new clips button" in sh[0] and sh[1].startswith("## V8.0.3"), str(sh[:2]))
    body = "\n".join(sm[sm.index(sh[0]):sm.index(sh[1])]).lower()
    check("entry is plain (no test / function names, no on-hold blocks)", not any(w in body for w in ("test", "known issue", "abandoned", "on hold", "scan_", "def ")))


def part1():
    section("1) new-clip selection")
    ps = {g: files(TMP / f"c1_{g}", g, 4) for g in ("valorant", "cs2", "r6s")}
    recs = []
    for g, lst in ps.items():
        recs += [rec(p, g) for p in lst]
    recs.append({"path": str(ps["r6s"][0]).replace("clip 00", "stub"), "unprobed": True, "game": "r6s"})
    with Env(recs, "d1") as env:
        for g in ("valorant", "cs2", "r6s"):
            r = [x for x in recs if x["game"] == g and x.get("w")]
            put(env, r[0], dict(GOOD, game=g))                                  # cached: skipped
            put(env, r[1], dict(GOOD, game=g, error="icons missing"))           # error entry: listed as error
        for g in ("valorant", "cs2", "r6s"):
            new, err = M.new_clip_paths(CFG, g)
            r = [x for x in recs if x["game"] == g and x.get("w")]
            exp_new = {x["path"] for x in r[2:]} | ({recs[-1]["path"]} if g == "r6s" else set())
            check(f"{g}: only never-scanned clips ({len(exp_new)}) + the errored one", set(new) == exp_new and err == [r[1]["path"]] and r[0]["path"] not in new + err, f"{new} {err}")
        check("another game's clips are never listed", all(Path(p).name.startswith("cs2") for p in M.new_clip_paths(CFG, "cs2")[0]))


def part2():
    section("2) nothing new")
    recs = [rec(p, "valorant") for p in files(TMP / "c2", "valorant", 2)]
    with Env(recs, "d2") as env:
        for r in recs:
            put(env, r, dict(GOOD, game="valorant"))
        LOG.clear()
        M.scan_all_new(CFG, ["valorant"])
        check("logs 'No new clips to scan for valorant'", "No new clips to scan for valorant" in LOG, str(LOG[-3:]))
        check("... and scans nothing", env.scanned == [])
        LOG.clear()
        M.scan_all_new(CFG, ["cs2", "r6s"])
        check("a game without any clip says the same", "No new clips to scan for cs2" in LOG and "No new clips to scan for r6s" in LOG)


def part3():
    section("3) the job: saved region, no cap, cached skipped, errors rescanned, normal cache")
    many = files(TMP / "c3", "r6s", 30)
    val = files(TMP / "c3v", "valorant", 3)
    recs = [rec(p, "r6s") for p in many] + [rec(p, "valorant") for p in val]
    with Env(recs, "d3") as env:
        (env.d).mkdir(exist_ok=True)
        saved = [0.5, 0.1, 0.9, 0.4]
        (env.d / "detect_r6s.json").write_text(json.dumps({"region": saved}), encoding="utf-8")
        put(env, recs[0], dict(GOOD, game="r6s"))                                       # cached
        put(env, recs[1], dict(GOOD, game="r6s", error="icons missing"))                # errored
        put(env, recs[30], dict(GOOD, game="valorant"))                                 # cached
        LOG.clear()
        M.scan_all_new(CFG, ["r6s", "valorant"])
        sc = env.scanned
        check("r6s: 29 clips scanned (28 new + 1 errored), no cap of 12", len([x for x in sc if x[0] == "r6s"]) == 29, str(len(sc)))
        check("the cached clips were not scanned again", ("r6s", "r6s clip 00.mp4") not in sc and ("valorant", "valorant clip 00.mp4") not in sc)
        check("the errored clip was scanned again", ("r6s", "r6s clip 01.mp4") in sc)
        check("valorant: its 2 uncached clips were scanned", len([x for x in sc if x[0] == "valorant"]) == 2)
        check("the scan used the SAVED R6S region", env.regions.get("r6s") == saved, str(env.regions))
        check("valorant used its own (default) region, not R6S's", env.regions.get("valorant") == M.DEFAULT_REGION["valorant"])
        c = M.load_kills_cache()
        ok = all(not (c.get(M.kills_key(r, r["game"], M.Detector(r["game"]))) or {}).get("error") and M.kills_key(r, r["game"], M.Detector(r["game"])) in c for r in recs)
        check("results are in the normal kill cache (every clip has an entry, no error left)", ok)
        check("the normal scan log lines are there ('[n/N] game ...', 'scan finished')", any(l.startswith("[1/") for l in LOG) and any(l.startswith("scan finished:") for l in LOG), str(LOG[:3]))
        LOG.clear()
        env.scanned.clear()
        M.scan_all_new(CFG, ["r6s", "valorant"])
        check("a second press finds nothing new", env.scanned == [] and "No new clips to scan for r6s" in LOG)
        # a clip that fails to scan is skipped, the rest continue
        env.scanned.clear()
        bad = files(TMP / "c3b", "cs2", 3)
        env.recs += [rec(p, "cs2") for p in bad]

        def sc(path, r, det, cfg, scale=None):
            if path.endswith("01.mp4"):
                raise RuntimeError("bad clip")
            return env.sc(path, r, det, cfg)
        keep = M.scan_clip
        M.scan_clip = sc
        LOG.clear()
        try:
            M.scan_all_new(CFG, ["cs2"])
        finally:
            M.scan_clip = keep
        check("a failing clip logs one ERROR line and the others are scanned", sum("ERROR" in l and "01.mp4" in l for l in LOG) == 1 and len(env.scanned) == 2, str(LOG[-4:]))


def part4():
    section("4) one game failing never stops the others")
    calls = []
    keep = (M.run_scan, M.new_clip_paths)

    def fake_new(cfg, g, *a, **k):
        return ([f"/x/{g}.mp4"], [])

    def fake_scan(cfg, games=None, paths=None, *a, **k):
        calls.append(games[0])
        if games[0] == "valorant":
            raise RuntimeError("valorant exploded")
        return 1
    M.run_scan, M.new_clip_paths = fake_scan, fake_new
    LOG.clear()
    try:
        M.scan_all_new(CFG)
    finally:
        M.run_scan, M.new_clip_paths = keep
    check("all three games were tried, in order", calls == ["valorant", "cs2", "r6s"], str(calls))
    check("the failure is one log line naming the game", sum("valorant: scanning new clips failed" in l for l in LOG) == 1, str(LOG))
    M.CANCEL.set()
    calls.clear()
    M.run_scan, M.new_clip_paths = fake_scan, fake_new
    try:
        M.scan_all_new(CFG)
    finally:
        M.run_scan, M.new_clip_paths = keep
        M.CANCEL.clear()
    check("cancel (same flag as every job) stops before the next game", calls == [])


def part5():
    section("5) the button")
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("button in the region section next to the others, same helper (self.btn)", 'self.btn(h, "Scan all new clips (current region)", self.rp_scan_new, name="region:scannew")' in src)
    check("it queues a background job (run_task), then reloads the lists", 'self.run_task("scan new clips", work)' in src and 'self.run_task("clips", self.load_clips)' in src)
    check("no other button / layout line in that section changed (Refresh keeps its place)", src.index('"region:refresh"') < src.index('"region:scannew"'))


def part6():
    section("6) frozen vs V8.0.3")
    T2.part5(REFS)
    T.part9(REFS, "V8.0")


def partp():
    T.partp("V8.0.3-good")


if __name__ == "__main__":
    for k, fn in (("0", part0), ("1", part1), ("2", part2), ("3", part3), ("4", part4), ("5", part5), ("6", part6)):
        if k in PARTS:
            try:
                fn()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                T.check(f"part {k} ran without an exception", False, repr(ex))
    if os.environ.get("V804_PLANS") == "1":
        partp()
    print(f"\n{len(T.FAILS)} FAIL" if T.FAILS else "\nALL OK", f"({time.time() - T.T0:.1f} s)")
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if T.FAILS else 0)
