"""V8.0.5 tests: 'Scan all new clips (current region)' scans ONLY the selected game. FAST unit tests (seconds; no real scan).
  0) title-bar version V8.0.5; V8.0.5 on top of both changelogs
  1) game=r6s / valorant / cs2: the scanned clips are only that game's, with that game's saved region; the start log line names the game; nothing new -> 'No new clips to scan for <game>'
  2) the old three-game path is gone; the button reads the game of its own region section
  3) frozen vs V8.0.4 (filter graphs + plan text, synthetic rows, tags, gaps); V805_PLANS=1 adds the slow dry-plan equality
python tests\test_v805.py   (parts: V805_PARTS=0,1,2,3)"""
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
spec = importlib.util.spec_from_file_location("t804", str(ROOT / "tests" / "test_v804.py"))
T4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T4)
T2, T = T4.T2, T4.T
M, check, section, TMP, LOG = T.M, T.check, T.section, T.TMP, T.LOG
PARTS = [x for x in os.environ.get("V805_PARTS", "0,1,2,3").split(",") if x]
CFG = copy.deepcopy(M.DEFAULT_CONFIG)
REFS = ("V8.0.4-good", "main")


def part0():
    section("0) version + changelog")
    check("APP_VERSION is V8.0.5", M.APP_VERSION == "V8.0.5")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.0.5 then V8.0.4", cl[0].startswith("## V8.0.5") and cl[1].startswith("## V8.0.4"), str(cl[:2]))
    sm = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8").splitlines()
    sh = [l for l in sm if l.startswith("## V")]
    check("simple changelog (Settings text): 'Scan button uses the selected game', then V8.0.4", "Scan button uses the selected game" in sh[0] and sh[1].startswith("## V8.0.4"), str(sh[:2]))


def part1():
    section("1) one game only")
    f = {g: T4.files(TMP / f"c_{g}", g, 3) for g in ("valorant", "cs2", "r6s")}
    recs = [T4.rec(p, g) for g, l in f.items() for p in l]
    saved = {"valorant": [0.1, 0.1, 0.9, 0.4], "cs2": [0.2, 0.1, 0.9, 0.4], "r6s": [0.3, 0.1, 0.9, 0.4]}
    for g in ("r6s", "valorant", "cs2"):
        with T4.Env(list(recs), f"d5_{g}") as env:
            (env.d / f"detect_{g}.json").write_text(json.dumps({"region": saved[g]}), encoding="utf-8")
            LOG.clear()
            M.scan_all_new(g, CFG)
            sc = env.scanned
            check(f"{g}: only {g} clips were scanned ({len(sc)})", len(sc) == 3 and all(x[0] == g for x in sc), str(sc))
            check(f"{g}: with the saved {g} region", env.regions == {g: saved[g]}, str(env.regions))
            check(f"{g}: the first log line names the game, the count and the region", LOG[0] == f"Scan all new clips: {g}, 3 new, region {saved[g]}", LOG[0])
            check(f"{g}: the scan log says 3 clips in scope (not another game's)", any("scanning 3  (of 3 clips in scope)" in l for l in LOG), str([l for l in LOG if "in scope" in l]))
            LOG.clear()
            M.scan_all_new(g, CFG)
            check(f"{g}: nothing new -> 'No new clips to scan for {g}'", f"No new clips to scan for {g}" in LOG)
    LOG.clear()
    M.scan_all_new("nope", CFG)
    check("an unknown game scans nothing", any("unknown game" in l for l in LOG))


def part2():
    section("2) the old three-game path is gone; the button uses its own game")
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    body = src[src.index("def scan_all_new("):src.index("def cmd_scan(args):")]
    check("scan_all_new takes ONE game (no loop over GAMES, no games list)", "for g in" not in body and "games or" not in body and "games=" not in body and body.startswith("def scan_all_new(game, cfg=None):"))
    check("the button reads self.rp_game (the region fields' own game variable) on the UI thread", "g = self.rp_game.get()" in src and "scan_all_new(g, load_config())" in src)
    check("no caller passes a games list any more", "scan_all_new(load_config())" not in src and "scan_all_new(cfg, [" not in src)


def part3():
    section("3) frozen vs V8.0.4")
    T2.part5(REFS)
    T.part9(REFS, "V8.0")


if __name__ == "__main__":
    for k, fn in (("0", part0), ("1", part1), ("2", part2), ("3", part3)):
        if k in PARTS:
            try:
                fn()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                T.check(f"part {k} ran without an exception", False, repr(ex))
    if os.environ.get("V805_PLANS") == "1":
        T.partp("V8.0.4-good")
    print(f"\n{len(T.FAILS)} FAIL" if T.FAILS else "\nALL OK", f"({time.time() - T.T0:.1f} s)")
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if T.FAILS else 0)
