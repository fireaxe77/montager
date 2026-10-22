"""V8.8.4 tests (fast; no montage render, no library scan).
  0) title-bar version V8.8.4; V8.8.4 on top of V8.8.3 in both changelogs
  1) R6S: every kill of a clip / fight group is one fight (no 10 s split, so no second fight lost to 'one event per clip'); Valorant / CS2 fight rules unchanged
  2) the kill row decides: an event's kill times are the kill-row times (a gunshot never sets or moves them); a missing gunshot never rejects a kill (single sighting / stale-row cases kept with a note);
     the death rule unchanged
  3) sky gradient: every family's top and bottom are far apart in brightness; the gradient plane follows each frame's own sky region (0 at its top row, 255 at its lowest), glides over time
  (Valorant / CS2 plans from the same events identical to v8.8.3: tests/guard884_vc.py; the real R6S render check: tests/render884.py)
python tests\\test_v884.py   (parts: V884_PARTS=0,1,2,3)"""
import os
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_src = (HERE / "test_v842.py").read_text(encoding="utf-8")
_ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
exec(compile(_src[:_src.index("def part0")], str(HERE / "test_v842.py"), "exec"), _ns)
T = types.SimpleNamespace(**_ns)
M = T.M
ROOT = T.ROOT
check = T.check
PARTS = [x for x in os.environ.get("V884_PARTS", "0,1,2,3").split(",") if x]
import numpy as np                                                                            # noqa: E402


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.8.4", M.APP_VERSION == "V8.8.4")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.8.4 above V8.8.3", cl[0].startswith("## V8.8.4") and cl[1].startswith("## V8.8.3"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.8.4 above V8.8.3", sm[0].startswith("## V8.8.4") and sm[1].startswith("## V8.8.3"), str(sm[:2]))
    seg = body[body.index("## V8.8.4"):body.index("## V8.8.3")].lower()
    check("simple entry is plain", not any(w in seg for w in ("test", "known issue", "on hold", "def ", "ffmpeg", "cache", "()", "planner", "ledger")))


def part1():
    print("1) R6S: one clip = one fight")
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    i = src.index("def _build_events")
    body = src[i:src.index("\ndef ", i + 10)]
    check("R6S fight gap is unlimited inside a clip / group", 'if game == "r6s" and R6S_ONE_FIGHT[0]:' in body and 'gap_g = float("inf")' in body and M.R6S_ONE_FIGHT[0])
    check("CS2 rule unchanged", 'if game == "cs2" and CS2_ROWID_ON[0]:' in body)
    check("Valorant split unchanged (10 s, 30 s for long clips)", M.FIGHT_SPLIT_S.get("valorant") == 10.0 and M.FIGHT_GAP_LONG_CLIP == 30.0 and M.LONG_CLIP_S == 25.0)
    check("the death rule unchanged", "within {lock:.0f}s after my death" in src and float(M.DEFAULT_CONFIG.get("death_lock_s", 8.0)) == 8.0)


def part2():
    print("2) the kill row is the kill time; a gunshot never rejects")
    it = {"rec": {"path": "x.mp4", "dur": 30.0, "game": "r6s", "v_off": 0.0}, "kills": [], "deaths": [], "vis": []}
    cl = [{"t": 3.90, "src": it, "off": 0.0, "shot_t": 3.70, "shot": True, "victim": "a", "ks": 1.0, "hs": False},
          {"t": 14.00, "src": it, "off": 0.0, "victim": "b", "ks": 1.0, "hs": True}]
    led0 = M.CUR_LEDGER[0]
    M.CUR_LEDGER[0] = None
    try:
        ev = M.make_event(cl, [(it, 0.0)], None, dict(M.DEFAULT_CONFIG), {})
    finally:
        M.CUR_LEDGER[0] = led0
    check(f"kill times = kill-row times ({ev['times'] if ev else None})", ev is not None and ev["times"] == [3.9, 14.0] and ev["rows"] == [3.9, 14.0])
    check("the gunshot does not move the first kill (0.2 s earlier shot)", ev is not None and ev["times"][0] == 3.9)
    keep = M.gun_onsets
    M.gun_onsets = lambda rec, cache=None, cfg=None: []    # a clip with sound but no gunshot anywhere
    try:
        pool = [{"rec": {"path": "y.mp4", "game": g, "audio": False}, "kills": [
                    {"t": 2.0, "ks": 0.8, "needs_shot": True, "victim": "a"},
                    {"t": 5.0, "ks": 1.0, "early_vic": True, "seen_first": 0.5, "victim": "b"},
                    {"t": 9.0, "ks": 1.0, "victim": "c"}], "deaths": [], "revives": [], "rej": []} for g in ("valorant", "cs2", "r6s")]
        st = M.verified_kills(pool, dict(M.DEFAULT_CONFIG))
    finally:
        M.gun_onsets = keep
    for it_ in pool:
        g = it_["rec"]["game"]
        check(f"{g}: no gunshot anywhere, all 3 kill rows kept ({len(it_['kills'])})", len(it_["kills"]) == 3)
        check(f"{g}: every gunshot note is soft (a note, not a rejection)", all(j.get("soft") for j in it_["rej"]))
    pool = [{"rec": {"path": "z.mp4", "game": "r6s", "audio": False}, "kills": [{"t": 6.0, "ks": 1.0, "victim": "a"}], "deaths": [2.0], "revives": [], "rej": []}]
    M.gun_onsets = lambda rec, cache=None, cfg=None: []
    try:
        M.verified_kills(pool, dict(M.DEFAULT_CONFIG))
    finally:
        M.gun_onsets = keep
    check("death rule still removes a kill 4 s after my death", pool[0]["kills"] == [])


def part3():
    print("3) sky gradient clearly top -> bottom")
    for n_, (top, bot, _j) in M.SKY_FAMILIES.items():
        yt, yb = M._rgb_to_yuv(top)[0], M._rgb_to_yuv(bot)[0]
        check(f"{n_}: bottom {yb - yt:.0f} levels brighter than the top", yb - yt >= 45)
    h, w = 120, 40
    sm = []
    for f in range(30):
        m = np.zeros((h, w), np.float32)
        top = 0 if f < 15 else 40                          # the camera turns: the painted region moves down
        m[top:top + 50] = 1.0
        sm.append(m)
    rs = [np.frombuffer(b_, np.uint8).reshape(h, w) for b_ in M.sky_frame_ramps(sm, h, w, 60)]
    check("gradient starts at the region's own top row and ends at its lowest (frame 0)", rs[0][0, 0] == 0 and rs[0][49, 0] >= 250)
    check("after the camera turns the gradient follows the region (frame 29: 0 at row 40, full at row 89)", rs[29][40, 0] < 10 and rs[29][89, 0] >= 250)
    mid = [int(r_[40, 0]) for r_ in rs[10:20]]
    check(f"it glides over the turn (row 40 over frames 10-19: {mid})", all(a_ <= b_ + 1 for a_, b_ in zip(mid[1:], mid)) and len(set(mid)) > 3)


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
    sys.exit(1 if T.FAILS else 0)
