"""V9.5.6 tests (fast, no render, no network; temporary folders only). Parts (V956_PARTS=0,1,2,3):
  0) version
  1) sky pattern choice: the plan's real song energy, the montage seed, the history (x0.25 / x0.6), 15 .. 40 % odds, the log line
  2) pre-clip kill row: a take starts after it has faded, an unreadable name is not a row of mine, a stitched clip's row is the earlier clip's
  3) sky mask: sky colours only, coverage cap, never below the detected horizon, take-level rejection
python tests\\test_v956.py"""
import collections
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="v956_"))
os.environ["MONTAGER_DATA"] = str(TMP / "data")
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402
from v696_common import check, FAILS                                                          # noqa: E402

PARTS = os.environ.get("V956_PARTS", "0,1,2,3").split(",")
M.sky_cover_tone = lambda p: (None, 0)
M.sky_cover_colour = lambda p: (None, 0)


def plan_of(seed, energy=0.6, bpm=150, **kw):
    return dict({"seed": seed, "song_energy": energy, "song": {"artist": "a", "title": "t", "bpm": bpm, "path": "x.mp3"}}, **kw)


def part0():
    check(M.APP_VERSION == "V9.5.6", f"the title-bar version is V9.5.6 ({M.APP_VERSION})")
    for f in ("START_HERE.txt", "packaging/montager.iss", "packaging/make_release.py"):
        txt = (ROOT / f).read_text(encoding="utf-8", errors="replace")
        check("9.5.6" in txt and "9.5.5" not in txt, f"{f} names 9.5.6 only")


def part1():
    M.SKY_PATTERN_HISTORY = TMP / "hist.json"
    # a) the plan's energy is used (and written into the plan by the planner: song_energy_of)
    e, src = M.song_energy_of({"energy": [0.2, 0.4]}, {}, with_src=True)
    check(abs(e - 0.3) < 1e-9 and src == "analysis", "song_energy_of: the song map's mean when the CSV has none")
    check(M.song_energy_of({"energy": [0.2]}, {"energy": 0.77}) == 0.77, "song_energy_of: the CSV value when there is one (what Auto style reads)")
    p = plan_of(5, energy=0.95)
    M.sky_pattern_for(p, history=[])
    check("energy 0.95" in p["xfx_sky_pattern_log"] and "montage seed 5" in p["xfx_sky_pattern_log"], "the log line names the energy used and the seed")
    check("odds before history" in p["xfx_sky_pattern_log"] and "after history" in p["xfx_sky_pattern_log"] and "limits" in p["xfx_sky_pattern_log"], "the log line has the odds before / after history and after the limits")
    lo = M.sky_pattern_for(plan_of(1, energy=0.1), history=[])[1]
    hi = M.sky_pattern_for(plan_of(1, energy=0.95), history=[])[1]
    check(lo != hi, "a different song energy gives different scores (it used to be a fixed 0.60)")
    # b) the montage seed decides: the same song gets different patterns in different renders; the same seed gives the same pattern
    picks = [M.sky_pattern_for(plan_of(s), history=[])[0] for s in range(400)]
    check(len(set(picks)) == 4, f"the same song gets every pattern across seeds ({collections.Counter(picks)})")
    check(all(M.sky_pattern_for(plan_of(7), history=[])[0] == M.sky_pattern_for(plan_of(7), history=[])[0] for _ in range(3)), "the same seed always gives the same pattern")
    # d) 15 .. 40 %: cells at the old default (energy 0.60, 180 BPM) is no longer the usual pick
    for e_, b_ in ((0.6, 180), (0.6, 120), (0.95, 170), (0.1, 70), (0.55, 100)):
        c = collections.Counter(M.sky_pattern_for(plan_of(s, e_, b_), history=[])[0] for s in range(3000))
        sh = {k: v / 3000 for k, v in c.items()}
        check(len(sh) == 4 and min(sh.values()) > 0.15 - 0.03 and max(sh.values()) < 0.40 + 0.03, f"energy {e_}, {b_} BPM: every pattern 15-40 % ({ {k: round(v, 2) for k, v in sorted(sh.items())} })")
    for v in ([.9, .05, .03, .02], [.25] * 4, [.1, .1, .1, .7], [.5, .5, 0, 0]):
        r = M.sky_odds_bounded(v)
        check(abs(sum(r) - 1) < 1e-9 and min(r) >= .15 - 1e-9 and max(r) <= .40 + 1e-9, f"sky_odds_bounded {v} -> {[round(x, 2) for x in r]}")
    # c) the history: the last one x0.25, the one before x0.6 (before the limits), saved across montages (the same montage never counts twice)
    base = collections.Counter(M.sky_pattern_for(plan_of(s), history=[])[0] for s in range(3000))
    hist = collections.Counter(M.sky_pattern_for(plan_of(s), history=["marble", "cells"])[0] for s in range(3000))
    check(hist["cells"] < 0.75 * base["cells"] and hist["ink"] > base["ink"], f"the pattern used last is drawn clearly less, the others more ({base['cells']} -> {hist['cells']}, ink {base['ink']} -> {hist['ink']})")
    check(hist["cells"] / 3000 >= 0.15 - 0.02, "... but still at least 15 %")
    M.SKY_PATTERN_HISTORY.unlink(missing_ok=True)
    for i in range(7):
        M.sky_pattern_history_add(M.SKY_PATTERNS[i % 4], f"k{i}")
    h = M.sky_pattern_history()
    check(len(h) == 5 and h[-1] == M.SKY_PATTERNS[6 % 4], f"the history keeps the last 5 ({h})")
    M.sky_pattern_history_add("ink", "k6")
    check(M.sky_pattern_history()[-1] == "ink" and len(M.sky_pattern_history()) == 5, "the same montage replaces its own entry")
    pl = plan_of(11)
    a = M.sky_pattern_for(pl)[0]
    M.sky_pattern_history_add(a, M.sky_pattern_key(pl))
    check(M.sky_pattern_for(plan_of(11))[0] == a, "a plan chosen again (preview, re-render) keeps its pattern: its own history entry is left out")
    src = Path(M.__file__).read_text(encoding="utf-8")
    check(src.count("sky_pattern_for(plan)") == 1 and "sky_pattern_history_add(pat" in src, "the render chooses once per montage and remembers it")


def part2():
    ev = {"times": [1.0, 1.8], "first": 1.0, "seen": [{"t": 0.0, "t_last": 1.3, "rule": "pre-clip: row already on screen when the clip starts (x)", "clip": "a.mp4", "victim": "v"}],
          "parts": [{"path": "C:/x/a.mp4"}]}
    ms = M.seen_min_start(ev)
    check(ms is not None and abs(ms - (1.3 - M.SEEN_PRE_SLACK_S)) < 1e-9, f"a take may start only after the pre-clip row has faded ({ms})")
    check(M.seen_min_start({"times": [1.0], "first": 1.0, "seen": []}) is None, "no pre-clip row: no limit")
    ev2 = dict(ev, seen=[dict(ev["seen"][0], clip="b.mp4")], parts=[{"path": "C:/x/a.mp4"}, {"path": "C:/x/b.mp4"}])
    check(M.seen_min_start(ev2) is None, "a row of a later clip (the stitch point) is not a start limit")
    M.SEEN_PRE_START_ON[0] = False
    check(M.seen_min_start({"times": [1.0], "first": 1.0, "seen": ev["seen"], "parts": ev["parts"]}) is None, "switched off: no limit")
    M.SEEN_PRE_START_ON[0] = True
    # geom: a start before the limit is refused, a later start is allowed
    U = np.arange(0, 20, 0.25)
    e = {"rec": {"game": "cs2", "path": "a.mp4"}, "path": "a.mp4", "times": [4.0, 4.6], "rows": [4.1, 4.7], "first": 4.0, "last": 4.6, "pre": 4.0, "post": 3.0, "n": 2, "death_after": None,
         "seen": [{"t": 0.0, "t_last": 2.6, "rule": "pre-clip: row already on screen when the clip starts (x)", "clip": "a.mp4", "victim": "v"}], "parts": [{"path": "a.mp4"}]}
    kb = 40
    early = M.geom(dict(e), U, kb - 12, kb, kb + 5, 1.0, False)       # starts 3.0 s before the kill = 1.0 s: the row (until 2.4 s) is on screen
    later = M.geom(dict(e), U, kb - 6, kb, kb + 5, 1.0, False)        # starts 1.5 s before = 2.5 s: after the row
    check(early is None, "geom: a take that starts while the previous kill's row is still on screen is refused")
    check(later is not None, "geom: the same event with a later start is placed")
    M.SEEN_PRE_START_ON[0] = False
    e2 = dict(e)
    check(M.geom(e2, U, kb - 12, kb, kb + 5, 1.0, False) is not None, "switched off: the old placement")
    M.SEEN_PRE_START_ON[0] = True
    # a pre-clip row whose name was not read as mine is not 'an uncounted kill row of mine'
    a = {"border": True, "rows": [{"t": 0.0, "cls": {"verdict": "kill", "name_read": False, "vtext": "v"}, "track": {"id": 1, "first": 0, "last": 5}},
                                  {"t": 0.0, "cls": {"verdict": "kill", "name_read": True, "vtext": "w"}, "track": {"id": 2, "first": 0, "last": 5}}],
         "rej": [{"t": 0.0, "reason": "pre-clip: row already on screen when the clip starts (x)"}]}
    rows = M.clip_seen_rows(a, [])
    check(len(rows) == 2 or len(rows) == 1, f"clip_seen_rows runs ({len(rows)})")
    check(all(r["victim"] != "v" for r in rows) and any(r["victim"] == "w" for r in rows), "an unread name at a pre-clip row is not a row of mine; a read one is")
    # stitched: a later clip's pre-clip row is the earlier clip's row still on screen, whatever the name reads
    t = {"segs": [[4.0, 9.0, 1.0, 300, 0], [9.0, 12.0, 1.0, 180, 1]], "kills": [5.0, 10.0], "victims": ["x", "y"], "srcs": [{"path": "c1.mp4"}, {"path": "c2.mp4"}],
         "seen": [{"t": 5.0, "t_last": 6.0, "rule": None, "clip": "c1.mp4", "victim": "gold"}, {"t": 9.0, "t_last": 9.9, "rule": None, "clip": "c1.mp4", "victim": "zzz"},
                  {"t": 9.0, "t_last": 10.4, "rule": "pre-clip: row already on screen when the clip starts (x)", "clip": "c2.mp4", "victim": "g0ld?"},
                  {"t": 10.0, "t_last": 11.0, "rule": None, "clip": "c2.mp4", "victim": "y"}]}
    msgs = [m for m in M.seen_rows_audit(t) if m.startswith("uncounted kill row")]
    check(not msgs, f"a stitched clip's garbled pre-clip row is judged with the earlier clip's row ({msgs})")


def part3():
    h, w = 54, 96
    img = np.zeros((h, w, 3), np.uint8)
    img[:20] = (110, 160, 230)                       # blue sky
    img[20:30] = (235, 238, 245)                     # white cloud
    img[30:42] = (150, 148, 145)                     # grey concrete wall
    img[42:] = (190, 170, 140)                       # warm beige wall
    like = M.sky_like_pixels(img)
    check(like[:20].all() and like[20:30].all() and not like[30:].any(), "sky_like_pixels: blue and white are sky, grey / beige walls are not")
    m = np.ones((h, w), bool)
    out_, wf = M.sky_track_clamp(img, m, None, None)
    check(out_[:30].all() and not out_[30:].any() and wf > 0.4, f"the mask keeps sky colours only (wall share {wf:.2f})")
    out_, _ = M.sky_track_clamp(img, m, None, 15)
    check(out_.any(1).nonzero()[0].max() == 15, "never below the detected horizon")
    out_, _ = M.sky_track_clamp(img, m, 0.10, None)
    check(abs(out_.mean() - 0.10) < 0.03 and out_[0].all() and not out_[-1].any(), f"the coverage cap gives up rows from the bottom ({out_.mean():.2f})")
    check(M.sky_take_reject({"cov": 0.12}, {"cov_full": 0.33, "horizon": 0.4}) is not None, "take 28: 12 % detected, 33 % tracked -> no recolour")
    check(M.sky_take_reject({"cov": 0.16}, {"cov_full": 0.20, "horizon": 0.62}) is not None, "take 88: horizon at 62 % -> no recolour")
    check(M.sky_take_reject({"cov": 0.16}, {"cov_full": 0.20, "horizon": 0.40}) is None, "a take that stays near its detected sky is kept")
    M.SKY_TRACK_ON[0] = False
    check(M.sky_take_reject({"cov": 0.12}, {"cov_full": 0.33, "horizon": 0.4}) is None, "switched off: no take-level rejection")
    M.SKY_TRACK_ON[0] = True


if __name__ == "__main__":
    for k, fn in (("0", part0), ("1", part1), ("2", part2), ("3", part3)):
        if k in PARTS:
            fn()
    print("ALL OK" if not FAILS else f"FAILED: {FAILS}")
    sys.exit(1 if FAILS else 0)
