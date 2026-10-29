"""V9.3.3 tests (fast): the deathmatch answers are saved in batches and a refused write (Windows 'Access is denied') neither stops the check nor loses answers.
python tests\test_v933.py"""
import os
import sys
import tempfile
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v933_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import montage as M                                                                           # noqa: E402

FAILS = []


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


check("title-bar version V9.3.3", M.APP_VERSION == "V9.3.3")
txt = (ROOT / "docs/CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
check("Settings changelog: V9.3.3 on top", 0 <= txt.find("## V9.3.3") < txt.find("## V9.3.2"))
M.DM_CACHE = TMP / "dm_cache.json"
M.DM_FLUSH_EVERY = 10
M._DM_MEM.clear()
M._DM_NEW[0] = 0
saves = []
orig = M.save_json
fail = {"n": 0}


def flaky(p, obj):
    saves.append(len(obj))
    if fail["n"] > 0:
        fail["n"] -= 1
        raise PermissionError(13, "Access is denied")
    return orig(p, obj)


M.save_json = flaky
M.time.sleep = lambda s: None
try:
    def put(i):
        with M._DM_LOCK:
            M._DM_MEM[f"k{i}"] = {"dm": False, "v": 2}
            M._DM_NEW[0] += 1
            if M._DM_NEW[0] >= M.DM_FLUSH_EVERY:
                M._dm_flush()
    ts = [threading.Thread(target=put, args=(i,)) for i in range(35)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("35 answers from 35 threads -> 3 batched writes, not 35", len(saves) == 3, str(saves))
    with M._DM_LOCK:
        M._dm_flush()
    check("the rest is written at the end; the file holds all 35", len(M.load_json(M.DM_CACHE, {})) == 35)
    M._DM_MEM["x"] = {"dm": True, "v": 2}
    fail["n"] = 3
    with M._DM_LOCK:
        M._dm_flush()
    check("a refused write is retried and then succeeds", "x" in M.load_json(M.DM_CACHE, {}) and not M._DM_MEM)
    M._DM_MEM["y"] = {"dm": False, "v": 2}
    fail["n"] = 99
    with M._DM_LOCK:
        M._dm_flush()
    check("a write refused every time raises nothing and keeps the answer in memory", "y" in M._DM_MEM and "y" in M._dm_view())
    fail["n"] = 0
    with M._DM_LOCK:
        M._dm_flush()
    check("...and the next flush saves it", "y" in M.load_json(M.DM_CACHE, {}) and not M._DM_MEM)
finally:
    M.save_json = orig
print("\nFAILED: " + "; ".join(FAILS) if FAILS else "\nall ok")
sys.exit(1 if FAILS else 0)
