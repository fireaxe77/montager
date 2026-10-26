"""V9.0.3 tests (fast, no render): every drop's kill lands exactly on the STORED drop time, its drop effects too.
  0) title-bar version V9.0.3, the version in the packaging / START_HERE, the V9.0.3 entry on top of both changelogs
  1) plans for Valorant, CS2 and R6S (synthetic events + a generated song): every drop of the map inside the montage is anchored on its stored time (within half a frame), also when the
     audible-onset refinement would have moved it (it is no longer used for placement); the drop effects (drop moment, rise, after, flash) sit on the same time
  r) All That She Wants (real files on disk: the saved plan of ATSW_CS2_V9.0.1_2026-10-26_2 and montage.log): the stored drops 29.490 / 68.740 were placed on 29.008 / 68.556 by V9.0.1;
     anchoring that plan's takes now puts a kill exactly on 29.490 and 68.740, and the drop effects land there too. Skipped (said so) when the files are not on this machine.
python tests\\test_v903.py   (parts: V903_PARTS=0,1,r)"""
import copy
import os
import json
import re
import sys
import tempfile
import types
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="v903_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
warnings.simplefilter("ignore")
import montage as M                                                                          # noqa: E402

PARTS = [x for x in os.environ.get("V903_PARTS", "0,1,r").split(",") if x]
FAILS = []
HALF_FRAME_MS = 1000.0 / M.OUT_FPS / 2 + 0.05
ATSW_PLAN = Path(r"E:/Movies/Montages/CS2/logs/ATSW_CS2_V9.0.1_2026-10-26_2.plan.json")
ATSW_LOG = Path(os.environ.get("V903_LOG", str(ROOT / "montage_data" / "logs" / "montage.log")))


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def helpers():
    src = (HERE / "test_v842.py").read_text(encoding="utf-8")
    ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
    exec(compile(src[:src.index("def part0")], str(HERE / "test_v842.py"), "exec"), ns)
    return types.SimpleNamespace(**ns)


def drop_fx_times(plan):
    """output times (s, without the intro) of the drop effects: the drop moments and every rise / after / breath effect"""
    t_ = [float(d["t"]) for d in plan.get("xfx_drop") or []]
    for t in plan["takes"]:
        for x in t.get("xfx") or []:
            if x.get("k") in ("rise", "after", "breath"):
                t_.append(t["f0"] / M.OUT_FPS + float(x["p"]))
    return t_


def part0():
    print("0) version, packaging, changelogs")
    check("APP_VERSION = V9.0.3", M.APP_VERSION == "V9.0.3", M.APP_VERSION)
    check("START_HERE names V9.0.3", (ROOT / "START_HERE.txt").read_text(encoding="utf-8").startswith("MONTAGER V9.0.3"))
    check("installer example names 9.0.3", "/DAppVersion=9.0.3 " in (ROOT / "packaging" / "montager.iss").read_text(encoding="utf-8"))
    check("release script example names v9.0.3", "(v9.0.3 for V9.0.3)" in (ROOT / "packaging" / "make_release.py").read_text(encoding="utf-8"))
    simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    check("Settings changelog: V9.0.3 on top of V9.0.2", 0 <= simple.index("## V9.0.3") < simple.index("## V9.0.2"))
    top = simple[simple.index("## V9.0.3"):simple.index("## V9.0.2")]
    check("Settings entry: plain points only (no KNOWN ISSUE / function names)", "KNOWN" not in top.upper() and "_" not in top and 1 <= top.count("\n- ") <= 4, top)
    check("CHANGELOG.md: V9.0.3 on top of V9.0.2", 0 <= tech.index("## V9.0.3") < tech.index("## V9.0.2"))


def part1():
    print("1) every game: kills and drop effects on the stored drop times")
    T = helpers()
    an = T.an()
    stored = sorted(float(d["t"]) for d in an.get("drops") or [])
    check("the generated song has stored drops", len(stored) >= 2, str(stored))
    keep = M.refine_drop_anchors
    M.refine_drop_anchors = lambda song_path, drops: ([(float(t) - 0.48, s, src) for t, s, src in drops], ["anchor refined (test: 480 ms earlier)"])   # the old step, made obvious
    n_drops = 0
    try:
        for game in ("valorant", "cs2", "r6s"):
            for style, seed in (("hype", 3), ("aggressive", 11), ("chill", 7)):
                for intro_on in (False, True):
                    M.INTRO_CTX.update({"on": intro_on, "text": None, "series": 1, "manual": False})
                    try:
                        plan, _ = T.mk(M, game, style, seed, eff={"valorant": "extra", "cs2": "extra", "r6s": "extra"})
                    except RuntimeError as ex:
                        print("  (not planned:", str(ex)[:60], ")")
                        continue
                    s0, D = float(plan["song"]["start_t"]), float(plan["duration"])
                    inside = [t for t in stored if s0 + 0.5 < t < s0 + D - 1.0]
                    ds = plan.get("drop_sync") or []
                    tag = f"{game} {style} seed {seed} intro {'on' if intro_on else 'off'}"
                    on_stored = sorted(round(x["drop"], 3) for x in ds) == sorted(round(t, 3) for t in inside)
                    exact = all(x.get("take") and abs(float(x["impact"]) - float(x["drop"])) * 1000 <= HALF_FRAME_MS for x in ds if not x.get("intro_zone"))
                    n_drops += len(ds)
                    check(f"{tag}: {len(inside)} drop(s), each anchored with a kill on its stored time (within half a frame)", on_stored and exact,
                          str([(x["drop"], x.get("impact"), x.get("why", "")[:60]) for x in ds]))
                    check(f"{tag}: no 'anchor refined' step in the plan", not any("anchor refined" in n for n in plan["notes"]))
                    fx = drop_fx_times(plan)
                    want = [float(x["drop"]) - s0 for x in ds if x.get("take")]
                    check(f"{tag}: the drop moments land on those same times", all(any(abs(f - w) * 1000 <= HALF_FRAME_MS for w in want)
                                                                                   for f in (float(d["t"]) for d in plan.get("xfx_drop") or [])) and
                          len(plan.get("xfx_drop") or []) >= len(want), f"fx {fx} want {want}")
    finally:
        M.refine_drop_anchors = keep
        M.INTRO_CTX.update({"on": False, "text": None, "series": None, "manual": False})
    check("drops were checked in all three games", n_drops > 0)


def part_r():
    print("r) All That She Wants: the saved V9.0.1 plan and montage.log")
    if not ATSW_PLAN.exists() or not ATSW_LOG.exists():
        print(f"  skipped: {ATSW_PLAN} or {ATSW_LOG} is not on this machine (set V903_LOG to montage.log)")
        return
    log = ATSW_LOG.read_text(encoding="utf-8", errors="replace")
    ref = {float(a): float(b) for a, b in re.findall(r"anchor refined: (29\.490|68\.740) -> ([0-9.]+)", log)}
    check("montage.log: V9.0.1 moved the stored drops 29.490 -> 29.008 and 68.740 -> 68.556", ref.get(29.49) == 29.008 and ref.get(68.74) == 68.556, str(ref))
    plan = json.loads(ATSW_PLAN.read_text(encoding="utf-8"))
    old = {round(x["drop"], 3): x for x in plan.get("drop_sync") or []}
    check("the saved V9.0.1 plan has its drop kills on the moved times (the bug)", set(old) == {29.008, 68.556}, str(sorted(old)))
    q = copy.deepcopy(plan)
    q.pop("drop_sync", None)
    notes = []
    M.INTRO_CTX["on"] = True
    try:
        M.anchor_all_drops(q, [(29.49, 2.0, "map"), (68.74, 1.7, "map")], "cs2", notes)
    finally:
        M.INTRO_CTX["on"] = False
    ds = {round(x["drop"], 3): x for x in q["drop_sync"]}
    for t in (29.49, 68.74):
        x = ds.get(t) or {}
        check(f"drop {t:.3f}: a kill exactly on the stored time ({x.get('err_ms')} ms, under half a frame)", bool(x.get("take")) and abs(float(x.get("err_ms") or 99)) <= HALF_FRAME_MS, str(x))
    s0 = float(q["song"]["start_t"])
    for t in q["takes"]:
        t["xfx"] = []
    M.assign_extra_fx(q, "cs2", int(q.get("seed") or 1), [], energy=0.83, sky_on=False)
    fx = [float(d["t"]) + s0 for d in q.get("xfx_drop") or []]
    check("the drop effects land on 29.490 and 68.740", all(any(abs(f - t) * 1000 <= HALF_FRAME_MS for f in fx) for t in (29.49, 68.74)), str(fx))


if __name__ == "__main__":
    for p_ in PARTS:
        (part_r if p_ == "r" else globals()["part" + p_])()
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
    sys.exit(1 if FAILS else 0)
