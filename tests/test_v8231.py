"""V8.23.1 tests (R6S only). FAST unit tests only (seconds; no render, no OCR engine).
  0) title-bar version V8.23.1; V8.23.1 on top of V8.23 in both changelogs
  1) a cached R6S row whose weapon icon is small / square in most reads is rejected at plan time as 'utility: ...' (REJECTED ROWS), with NO utility template hit
     stored and no rescan; the label is util
  2) normal gun rows (wide icon) stay kills, also a single read, a tie, and a row with only one small read (no gunshot heard / weak rows are not rejected by shape)
  3) the template path (stored utility hit) still rejects with its own line; the per-clip override still admits shape-rejected rows; switch off = old result
  4) deaths with a square icon stay deaths; other R6S rules (pre-clip, same victim) untouched; CS2 / Valorant analysis identical (not touched)
  r) (V8231_REAL=1) every cached R6S clip: only gun -> util changes, never a new kill
python tests\\test_v8231.py   (parts: V8231_PARTS=0,1,2,3,4)"""
import copy
import glob
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v8231_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import montage as M                                                                           # noqa: E402

PARTS = [x for x in os.environ.get("V8231_PARTS", "0,1,2,3,4").split(",") if x]
FAILS = []
CFG = copy.deepcopy(M.DEFAULT_CONFIG)


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def bx(x0, x1, t, col, y=100):
    return [x0, y, x1, y + 24, t, 0.95, col, 3]


GUN, SQ = [170, 98, 70, 28, 0.9], [170, 98, 26, 26, 0.9]


def entry(blobs, victim="BuffSledge_25", util=None, killer="fireaxeO", vname=None, frames=(30, 36, 42, 50, 60, 70, 80, 90)):
    """one killfeed row; `blobs` = the weapon-icon blob of each OCR frame (list, one per frame)"""
    ocr = []
    for i, f in enumerate(frames):
        k, v = (killer, victim) if vname is None else (victim, killer)
        ocr.append([f, f, [bx(10, 150, k, "g"), bx(340, 520, v, "r")], [blobs[i % len(blobs)]]])
    return {"ocr": ocr, "rows": [], "frames": 200, "v_off": 0.0, "game": "r6s", "util": util or [], "util_sig": ""}


def util_rej(a):
    return [r for r in a["rej"] if r["reason"].startswith("utility:")]


def part0():
    print("0) version + changelog")
    check("APP_VERSION is V8.23.1", M.APP_VERSION == "V8.23.1")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.23.1 above V8.23", cl[0].startswith("## V8.23.1") and cl[1].startswith("## V8.23 "), str(cl[:2]))
    sm = [l for l in (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("simple changelog: V8.23.1 above V8.23", sm[0].startswith("## V8.23.1") and sm[1].startswith("## V8.23"), str(sm[:2]))


def part1():
    print("1) small / square icon = utility, from the stored data")
    e = entry([SQ])
    a = M.analyse_entry(e, CFG, "r6s")
    check("the row is NOT a kill", a["kills"] == [], str(a["kills"]))
    rj = util_rej(a)
    check("listed in REJECTED ROWS as a 'utility:' line", len(rj) == 1 and "small/square weapon icon" in rj[0]["reason"] and "] util [" in rj[0]["reason"], str(a["rej"]))
    check("no utility template hit was needed (entry['util'] is empty)", e["util"] == [])
    check("its visible window is kept like the template path (vis)", len(a["vis"]) == 1)
    check("the stored entry was not changed (no rescan / cache edit)", "gunv" not in json.dumps(e))


def part2():
    print("2) gun rows are never rejected on weak evidence")
    check("wide icon in every read = kill", len(M.analyse_entry(entry([GUN]), CFG, "r6s")["kills"]) == 1)
    a = M.analyse_entry(entry([GUN]), CFG, "r6s")
    check("... labelled gun", a["kills"][0]["weapon"] == "gun" and not a["kills"][0].get("util"))
    check("one small read in a gun row (7 wide + 1 small) stays a kill", len(M.analyse_entry(entry([GUN, GUN, GUN, GUN, GUN, GUN, GUN, SQ]), CFG, "r6s")["kills"]) == 1)
    check("a tie (4 wide / 4 small) stays a kill", len(M.analyse_entry(entry([GUN, SQ]), CFG, "r6s")["kills"]) == 1)
    one = entry([GUN])
    one["ocr"][0][3] = [SQ]                                                  # exactly one small read among wide ones, the rest 'no icon read' would be a gap split
    one["ocr"] = one["ocr"][:1] + [[f, f, [bx(10, 150, "fireaxeO", "g"), bx(340, 520, "BuffSledge_25", "r")], []] for f in (36, 42, 50, 60, 70, 80, 90)]
    check("a row with a single small icon read (others without an icon read) stays a kill (weak evidence)", len(M.analyse_entry(one, CFG, "r6s")["kills"]) == 1)
    check("two small reads out of eight (6 wide) stay a kill", len(M.analyse_entry(entry([GUN, GUN, GUN, SQ]), CFG, "r6s")["kills"]) == 1)
    check("majority small (6 of 8) is rejected", M.analyse_entry(entry([SQ, SQ, SQ, GUN]), CFG, "r6s")["kills"] == [])
    e = entry([[170, 98, 36, 24, 0.9]])                                      # a short gun / pistol-like icon: 1.5 x height exactly = gun
    check("an icon exactly 1.5 x as wide as high is a gun (same threshold as Valorant / CS2)", len(M.analyse_entry(e, CFG, "r6s")["kills"]) == 1)
    nob = entry([[]])
    nob["ocr"] = [[f, f, [bx(10, 150, "fireaxeO", "g"), bx(340, 520, "BuffSledge_25", "r")], []] for f in (30, 36, 42, 50, 60, 70, 80, 90)]
    check("no icon found (split by the gap) is not utility by shape", len(M.analyse_entry(nob, CFG, "r6s")["kills"]) == 1)


def part3():
    print("3) template path, override, switch")
    hit = {"first": 28, "last": 95, "hits": 60, "x": 183, "y": 112, "w": 30, "h": 22, "sc": 0.98, "tpl": "kill_skull.png"}
    a = M.analyse_entry(entry([GUN], util=[hit]), CFG, "r6s")
    rj = util_rej(a)
    check("a stored template hit still rejects with the old line", a["kills"] == [] and len(rj) == 1 and rj[0]["reason"].startswith("utility: gadget kill icon"), str(a["rej"]))
    e = entry([SQ])
    base = M.analyse_entry(e, CFG, "r6s")
    util = M.utility_kill_rows(e, CFG, "r6s", base)
    check("the per-clip override sees the shape-rejected row as a utility kill (same function as Valorant)", len(util) == 1 and util[0].get("util"), str(util))
    M.R6S_SHAPE_UTIL = False
    try:
        a = M.analyse_entry(entry([SQ]), CFG, "r6s")
        check("switch off = the old result (a kill)", len(a["kills"]) == 1 and not util_rej(a))
    finally:
        M.R6S_SHAPE_UTIL = True


def part4():
    print("4) deaths and the other rules unchanged")
    a = M.analyse_entry(entry([SQ], killer="BuffSledge_25", vname=True) if False else entry([SQ], victim="BuffSledge_25", vname=True), CFG, "r6s")
    check("a square icon with my name on the victim side is still my death (not utility)", a["kills"] == [] and len(a["deaths"]) == 1 and not util_rej(a), str(a["rej"]))
    pre = entry([SQ], frames=(0, 1, 2, 30, 40, 50, 60, 70))
    a = M.analyse_entry(pre, CFG, "r6s")
    check("a pre-clip row is still rejected as pre-clip (first rule wins)", any(r["reason"].startswith("pre-clip") for r in a["rej"]) and not util_rej(a), str(a["rej"]))
    for g in ("cs2", "valorant"):
        check(f"{g} analysis does not read R6S shape data", "gunv" not in json.dumps(M.analyse_entry({"ocr": [], "frames": 10, "v_off": 0.0, "game": g}, CFG, g), default=str))


def partr():
    print("r) every cached R6S clip")
    n_same = n_new = n_chg = 0
    for p in sorted(glob.glob(str(ROOT / "montage_data" / "kills_v5" / "*.json"))):
        d = json.load(open(p, encoding="utf-8"))
        if d["key"].split("|")[3] != "r6s" or d["e"].get("error") or not d["e"].get("ocr"):
            continue
        M.R6S_SHAPE_UTIL = False
        b = M.r6s_analyse_entry(d["e"], CFG)
        M.R6S_SHAPE_UTIL = True
        a = M.r6s_analyse_entry(d["e"], CFG)
        kb, ka = {(k["t"], k["row"]) for k in b["kills"]}, {(k["t"], k["row"]) for k in a["kills"]}
        n_new += len(ka - kb)
        n_chg += len(kb - ka)
        n_same += len(ka & kb)
    check(f"no new kills ({n_new}); {n_chg} gun->util, {n_same} unchanged", n_new == 0)


for p in PARTS:
    globals()["part" + p]()
if os.environ.get("V8231_REAL"):
    partr()
print("\nFAILS:", len(FAILS))
for f in FAILS:
    print(" -", f)
sys.exit(1 if FAILS else 0)
