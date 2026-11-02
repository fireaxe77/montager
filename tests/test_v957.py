"""V9.5.7 tests (fast, no render, no network). Parts (V957_PARTS=0,1):
  0) version
  1) a kill row that is already on screen when its clip starts (a stale row of a kill from before the clip) never fails the kill-row check and never drops a clip
python tests\\test_v957.py"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="v957_"))
os.environ["MONTAGER_DATA"] = str(TMP / "data")
import montage as M                                                                           # noqa: E402
from v696_common import check, FAILS                                                          # noqa: E402

PARTS = os.environ.get("V957_PARTS", "0,1").split(",")
PRE = "pre-clip: row already on screen when the clip starts ([fireaxe火茶] gun [Wwpaknb])"


def part0():
    check(M.APP_VERSION == "V9.5.7", f"the title-bar version is V9.5.7 ({M.APP_VERSION})")
    for f in ("START_HERE.txt", "packaging/montager.iss", "packaging/make_release.py"):
        txt = (ROOT / f).read_text(encoding="utf-8", errors="replace")
        check("9.5.7" in txt and "9.5.6" not in txt, f"{f} names 9.5.7 only")


def part1():
    # a 3k clip: the take plays 0.45 .. 14 s; a stale row of mine is on screen from 0.0 to 6.0 s (the first kill is at 2.2 s)
    stale = {"t": 0.0, "t_last": 6.0, "rule": PRE, "clip": "a.mp4", "victim": "Wwpaknb"}
    t = {"segs": [[0.45, 14.0, 1.0, 800, 0]], "kills": [2.2, 9.0, 13.0], "victims": ["x", "y", "z"], "srcs": [{"path": "a.mp4"}],
         "seen": [stale, {"t": 2.2, "t_last": 8.0, "rule": None, "clip": "a.mp4", "victim": "x"}, {"t": 9.0, "t_last": 12.0, "rule": None, "clip": "a.mp4", "victim": "y"},
                  {"t": 13.0, "t_last": 14.0, "rule": None, "clip": "a.mp4", "victim": "z"}]}
    check(not M.seen_rows_audit(t), f"a stale pre-clip row on screen for 5 s does not fail the take ({M.seen_rows_audit(t)})")
    ev = {"times": [2.2, 9.0, 13.0], "seen": t["seen"], "victims": ["x", "y", "z"], "parts": []}
    check(M.seen_rows_doomed(ev) is None, "the multikill is not dropped before planning")
    # a real uncounted row (not pre-clip) still fails, as before
    t2 = dict(t, seen=t["seen"] + [{"t": 4.0, "t_last": 6.0, "rule": "not in the kill list", "clip": "a.mp4", "victim": "q"}])
    check(any(m.startswith("uncounted kill row") for m in M.seen_rows_audit(t2)), "a row that is not a stale one and is not a kill of the take still fails")
    # a stitched event: the later clip's stale row is just ignored as well, whatever its name reads
    t3 = {"segs": [[4.0, 9.0, 1.0, 300, 0], [9.0, 12.0, 1.0, 180, 1]], "kills": [5.0, 10.0], "victims": ["x", "y"], "srcs": [{"path": "c1.mp4"}, {"path": "c2.mp4"}],
          "seen": [{"t": 5.0, "t_last": 6.0, "rule": None, "clip": "c1.mp4", "victim": "gold"},
                   {"t": 9.0, "t_last": 10.4, "rule": PRE, "clip": "c2.mp4", "victim": "g0ld?"}, {"t": 10.0, "t_last": 11.0, "rule": None, "clip": "c2.mp4", "victim": "y"}]}
    check(not M.seen_rows_audit(t3), "a stitched clip's stale row is ignored too")
    # clip_seen_rows leaves stale rows out in both detection layouts
    a = {"border": True, "rows": [{"t": 0.0, "cls": {"verdict": "kill", "name_read": True, "vtext": "v"}, "track": {"id": 1, "first": 0, "last": 5}}],
         "rej": [{"t": 0.0, "reason": PRE}]}
    check(M.clip_seen_rows(a, []) == [], "clip_seen_rows: a pre-clip row is not listed (border layout)")
    b = {"mine": [{"t": 0.0, "verdict": "kill", "row": "x [v]"}], "rej": [{"t": 0.0, "reason": PRE}]}
    check(M.clip_seen_rows(b, []) == [], "clip_seen_rows: a pre-clip row is not listed (name layout)")
    M.SEEN_PRE_IGNORE_ON[0] = False
    check(any(m.startswith("uncounted kill row") for m in M.seen_rows_audit(t)), "switched off: the old check")
    M.SEEN_PRE_IGNORE_ON[0] = True


if __name__ == "__main__":
    for k, fn in (("0", part0), ("1", part1)):
        if k in PARTS:
            fn()
    print("ALL OK" if not FAILS else f"FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)
