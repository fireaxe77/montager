"""V9.3.2 tests (fast; no real clips):
  0) title-bar version V9.3.2, both changelogs carry V9.3.2 on top
  1) CS2 deathmatch check: an older (V8.6.2) answer with no signal is completed once from the clip's last frames (the points log is on screen after the last kill):
     log text there + the deathmatch top bar -> rejected; a competitive clip ("+$300 ...") stays; answers with the V9.3.2 mark are used as they are
python tests\test_v932.py   (parts: V932_PARTS=0,1)"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v932_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import montage as M                                                                           # noqa: E402

PARTS = [x for x in os.environ.get("V932_PARTS", "0,1").split(",") if x]
FAILS = []


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def part0():
    print("0) version and changelogs")
    check("title-bar version V9.3.2", M.APP_VERSION == "V9.3.2")
    for f in ("CHANGELOG.md", "docs/CHANGELOG_SIMPLE.md"):
        txt = (ROOT / f).read_text(encoding="utf-8")
        check(f"{f}: V9.3.2 is the newest entry", 0 <= txt.find("## V9.3.2") < txt.find("## V9.3.1"))


def part1():
    print("1) deathmatch check: the last frames")
    DUR = 15.0
    rec = {"path": str(TMP / "fake_dm.mp4"), "dur": DUR, "w": 1920, "h": 1080}
    seen = []
    orig = (M.ocr_engine, M._dm_crop, M.content_rect, M.file_key, M.DM_CACHE)
    state = {"log_from": 14.0, "points": True}

    def fake_crop(path, t, box, rect, wh, scale=1.0):
        seen.append((t, box))
        return (t, box)

    class Eng:
        def __call__(self, im):
            t, box = im
            if box == (0.0, 0.72, 0.36, 0.95):                      # the log: only after the last kill (state['log_from'])
                if t >= state["log_from"]:
                    return [[0, "5 points for neutralizing an enemy with the AK-47" if state["points"] else "+$300 for neutralizing an enemy"]], 0
                return [], 0
            if box == (0.25, 0.0, 0.75, 0.12):                       # the top bar: a timer and a row of points
                return [[0, "7:58"]] + [[0, str(100 + i)] for i in range(10)], 0
            return [], 0
    M.ocr_engine, M._dm_crop, M.content_rect, M.file_key = (lambda: Eng()), fake_crop, (lambda r, c: (0, 0, 1920, 1080)), (lambda p: "fake|" + str(p))
    M.DM_CACHE = TMP / "dm_cache.json"
    try:
        M.save_json(M.DM_CACHE, {"fake|" + rec["path"]: {"a1": False, "a2": False, "b": False, "signals": 0, "dm": False, "texts": []}})
        check("an older answer (no mark, no signal) is not final", M.cs2_dm_rejected(M.load_config(), [rec]) == {rec["path"]})
        d = M.load_json(M.DM_CACHE, {})["fake|" + rec["path"]]
        check("...the log in the last frames + the top bar make 2 signals, stored with the mark", d["a1"] and d["b"] and d["signals"] == 2 and d["v"] == M.DM_VER, str(d))
        n = len(seen)
        M.cs2_dm_signals(rec, M.load_config())
        check("a marked answer is used as it is (nothing is looked at again)", len(seen) == n)
        state["points"] = False
        M.save_json(M.DM_CACHE, {"fake|" + rec["path"]: {"a1": False, "a2": False, "b": False, "signals": 0, "dm": False, "texts": []}})
        check("a competitive clip (+$300 log) stays", M.cs2_dm_rejected(M.load_config(), [rec]) == set())
        state["points"] = True
        state["log_from"] = 99.0
        M.save_json(M.DM_CACHE, {})
        n = len(seen)
        check("a new clip is looked at in 4 frames for the log (2 of them at the clip's end)", M.cs2_dm_signals(rec, M.load_config())["a1"] is False
              and sum(1 for t, b in seen[n:] if b == (0.0, 0.72, 0.36, 0.95)) == 4)
    finally:
        M.ocr_engine, M._dm_crop, M.content_rect, M.file_key, M.DM_CACHE = orig


if __name__ == "__main__":
    for p_ in PARTS:
        {"0": part0, "1": part1}[p_]()
    print("\nFAILED: " + "; ".join(FAILS) if FAILS else "\nall ok")
    sys.exit(1 if FAILS else 0)
