"""V8.23 tests (R6S only). FAST unit tests only (seconds; no render, no real clips, no OCR engine).
  0) title-bar version V8.23; V8.23 on top of V8.22 in both changelogs
  1) the new gadget icon (fixtures/r6s_kill_gadget4.png, cut from the supplied screenshot) is in the utility icon folder and loads with the old three
  2) a frame with the screenshot's killfeed row: the utility pass finds the new icon, the analysis rejects the row as 'utility: gadget kill icon'
  3) the old utility icons still match themselves with the same score; the new icon does not hit on them and they do not hit on it
  4) normal weapon icons (synthetic gun / knife shapes) get no utility hit with all four icons; thresholds / constants unchanged
python tests\\test_v823.py   (parts: V823_PARTS=0,1,2,3,4)"""
import copy
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v823_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import cv2                                                                                    # noqa: E402
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402

PARTS = [x for x in os.environ.get("V823_PARTS", "0,1,2,3,4").split(",") if x]
FAILS = []
CFG = copy.deepcopy(M.DEFAULT_CONFIG)
FIX = ROOT / "fixtures"
REAL = ROOT / "montage_data" / "r6s" / "utility_icons"
OLD = ("kill_gadget3.png", "kill_season10.png", "kill_skull.png")


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def folder(with_new=True, only_new=False):
    d = TMP / f"icons_{int(with_new)}{int(only_new)}"
    d.mkdir(exist_ok=True)
    if not only_new:
        for n in OLD:
            if (REAL / n).exists():
                shutil.copy(REAL / n, d / n)
    if with_new or only_new:
        shutil.copy(FIX / "r6s_kill_gadget4.png", d / "kill_gadget4.png")
    return d


def canvas():
    rng = np.random.default_rng(3)
    return np.clip(rng.normal(70, 12, (140, 460, 3)), 0, 255).astype(np.uint8)


def scan(icons, paste, n=10, at=(40, 80)):
    fr = canvas()
    y, x = at
    fr[y:y + paste.shape[0], x:x + paste.shape[1]] = paste
    sc = M.R6SUtilScan(icons)
    for f in range(n):
        sc.step(f, fr)
    return [h for h in sc.hits]


def real(hits):
    return [h for h in hits if h["hits"] >= M.R6S_UTIL_MIN_F]


def part0():
    print("0) version + changelog")
    check("APP_VERSION is V8.23", M.APP_VERSION == "V8.23")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.23 above V8.22", [x[:8] for x in cl[:2]] == ["## V8.23", "## V8.22"], str(cl[:2]))
    sm = [l for l in (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("simple changelog: V8.23 above V8.22", sm[0].startswith("## V8.23") and sm[1].startswith("## V8.22"), str(sm[:2]))


def part1():
    print("1) icon installed + loads")
    check("fixture icon exists", (FIX / "r6s_kill_gadget4.png").exists())
    if REAL.is_dir():
        check("kill_gadget4.png is in montage_data\\r6s\\utility_icons", (REAL / "kill_gadget4.png").exists())
        check("installed icon equals the fixture", (REAL / "kill_gadget4.png").read_bytes() == (FIX / "r6s_kill_gadget4.png").read_bytes())
    icons = M.r6s_load_util_icons(folder(), log=False)
    names = [i["name"] for i in icons]
    check("loads together with the old icons", "kill_gadget4.png" in names and all(n in names for n in OLD if (REAL / n).exists()), str(names))


def part2():
    print("2) the screenshot row is rejected as utility")
    row = cv2.imread(str(FIX / "r6s_gadget4_row.png"))
    icons = M.r6s_load_util_icons(folder(), log=False)
    hits = scan(icons, row)
    mine = [h for h in real(hits) if h["tpl"] == "kill_gadget4.png"]
    check("the utility pass finds the new icon on the row", len(mine) == 1, str(hits))
    old_only = M.r6s_load_util_icons(folder(with_new=False), log=False)
    check("without the new icon the row is not caught (so the new icon is what catches it)", not real(scan(old_only, row)))
    if not mine:
        return
    h = mine[0]
    hx, hy = h["x"], h["y"]

    def box(x0, x1, t, c):
        return [x0, hy - 12, x1, hy + 12, t, 0.95, c, 3]
    frames = (30, 36, 42, 50, 60, 70, 80, 90)
    ent = {"ocr": [[f, f, [box(hx - 160, hx - 30, "fireaxeO", "g"), box(hx + 30, hx + 190, "Lomopoly", "r")], [[hx - 14, hy - 14, 28, 28, 0.9]]] for f in frames],
           "rows": [], "frames": 200, "v_off": 0.0, "game": "r6s", "util": [dict(h, first=28, last=95, hits=60)], "util_sig": ""}
    a = M.analyse_entry(ent, CFG, "r6s")
    check("analysis: not a kill", a["kills"] == [], str(a["kills"]))
    check("analysis: listed as 'utility: gadget kill icon' in the rejected rows", any(r["reason"].startswith("utility: gadget kill icon") for r in a["rej"]), str(a["rej"]))
    ent["util"] = []
    check("the same row without the utility hit stays a normal kill (nothing else changed)", len(M.analyse_entry(ent, CFG, "r6s")["kills"]) == 1)


def part3():
    print("3) old utility icons unchanged")
    have = [n for n in OLD if (REAL / n).exists()]
    if not have:
        print("  (old icons not installed here: skipped)")
        return
    old, both = M.r6s_load_util_icons(folder(with_new=False), log=False), M.r6s_load_util_icons(folder(), log=False)
    newo = M.r6s_load_util_icons(folder(only_new=True), log=False)
    for n in have:
        pad = cv2.copyMakeBorder(cv2.imread(str(REAL / n)), 6, 6, 10, 10, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        h0, h1 = real(scan(old, pad)), real(scan(both, pad))
        check(f"{n}: still found with the new icon added, same template, same score",
              len(h0) == 1 and len(h1) == 1 and h0[0]["tpl"] == h1[0]["tpl"] == n and abs(h0[0]["sc"] - h1[0]["sc"]) < 1e-6, f"{h0} / {h1}")
        check(f"{n}: the new icon alone does not fire on it", not real(scan(newo, pad)))
    pad = cv2.copyMakeBorder(cv2.imread(str(FIX / "r6s_kill_gadget4.png")), 6, 6, 10, 10, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    check("the old icons do not fire on the new icon", not real(scan(old, pad)))


def part4():
    print("4) weapon icons + constants")
    icons = M.r6s_load_util_icons(folder(), log=False)
    gun = np.zeros((24, 70, 3), np.uint8)
    cv2.rectangle(gun, (4, 8), (60, 16), (230, 230, 230), -1)
    cv2.rectangle(gun, (44, 14), (52, 22), (230, 230, 230), -1)
    cv2.line(gun, (60, 12), (68, 12), (230, 230, 230), 2)
    knife = np.zeros((24, 50, 3), np.uint8)
    cv2.line(knife, (4, 20), (44, 6), (240, 240, 240), 3)
    for nm, im in (("gun", gun), ("knife", knife)):
        check(f"a normal {nm} icon gets no utility hit", not real(scan(icons, im)))
    check("utility threshold / min frames / match threshold unchanged", (M.R6S_UTIL_THR, M.R6S_UTIL_MIN_F, M.R6S_MATCH_THR) == (0.90, 5, 0.85))


for p in PARTS:
    globals()["part" + p]()
print("\nFAILS:", len(FAILS))
for f in FAILS:
    print(" -", f)
sys.exit(1 if FAILS else 0)
