"""V9.1.1 tests (fast, no render).
  0) title-bar version V9.1.1, the version in the packaging / START_HERE, the V9.1.1 entry on top of both changelogs
  1) R6S quick 4k ('4k ace.mp4', its cached OCR frames in tests/r6s_4k_ace_ocr.json): the 4th row (victim name 'IIIIIIIIIIII', read as nothing) is a kill, so the clip is a 4k
     (3k with the V9.1.1 switch off); a blank read that is the slide-in of a named row is not a second kill; the event ends a montage with all four kills inside the take,
     the fade to black after the 4th kill, and the cut-list check reports a fade that starts before the last kill
  2) sky: the same plan stamped as Valorant, CS2 and R6S gets the same sky candidates, budget, spacing, calm-take gating and kept skies; the mask opacity does not depend on the game
python tests\\test_v911.py   (parts: V911_PARTS=0,1,2)"""
import copy
import inspect
import json
import os
import sys
import tempfile
import types
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="v911_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
warnings.simplefilter("ignore")
import numpy as np                                                                           # noqa: E402
import montage as M                                                                          # noqa: E402

PARTS = [x for x in os.environ.get("V911_PARTS", "0,1,2").split(",") if x]
FAILS = []
OCR_FRAME_S = 1.0 / M.FPS
ACE = json.loads((HERE / "r6s_4k_ace_ocr.json").read_text(encoding="utf-8"))
ACE_ROW4_S = 13.70                      # the 4th row is fully on screen from about 13.70 s (60 fps frames of the source, checked by eye)


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def helpers():
    src = (HERE / "test_v842.py").read_text(encoding="utf-8")
    ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
    exec(compile(src[:src.index("def part0")], str(HERE / "test_v842.py"), "exec"), ns)
    return types.SimpleNamespace(**ns)


def part0():
    print("0) version, packaging, changelogs")
    check("APP_VERSION = V9.1.1", M.APP_VERSION == "V9.1.1", M.APP_VERSION)
    check("START_HERE names V9.1.1", (ROOT / "START_HERE.txt").read_text(encoding="utf-8").startswith("MONTAGER V9.1.1"))
    check("installer example names 9.1.1", "/DAppVersion=9.1.1 " in (ROOT / "packaging" / "montager.iss").read_text(encoding="utf-8"))
    check("release script example names v9.1.1", "(v9.1.1 for V9.1.1)" in (ROOT / "packaging" / "make_release.py").read_text(encoding="utf-8"))
    simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    check("Settings changelog: V9.1.1 on top of V9.1.0", 0 <= simple.index("## V9.1.1") < simple.index("## V9.1.0"))
    top = simple[simple.index("## V9.1.1"):simple.index("## V9.1.0")]
    check("Settings entry: headline names the quick 4k, plain points only", "4k" in top.splitlines()[0].lower() and "KNOWN" not in top.upper() and "_" not in top
          and 1 <= top.count("\n- ") <= 4, top)
    check("CHANGELOG.md: V9.1.1 on top of V9.1.0", 0 <= tech.index("## V9.1.1") < tech.index("## V9.1.0"))


def ace_event(kills):
    """the kill event the planner gets for '4k ace.mp4' (same fields as M.fake_events, kill times = the kill rows)"""
    times = [k["t"] for k in kills]
    dur = float(ACE["dur"])
    rec = {"path": "/fake/4k ace.mp4", "w": 1920, "h": 1080, "dur": dur, "audio": False}
    ev = {"rec": rec, "path": rec["path"], "times": times, "rows": list(times), "times_v4": list(times), "n": len(times), "victims": [k["victim"] for k in kills],
          "first": times[0], "last": times[-1], "span": times[-1] - times[0], "hs": False, "flick": False, "shots": 1.0, "imp": len(times) - 1, "lag": 0.0,
          "pre": times[0] - 0.05, "post": dur - times[-1] - 0.3, "death_after": None, "parts": None, "stitched": False, "lags": [0.0] * len(times), "vis": []}
    ev["score"] = M.base_score(ev)
    ev["plain"] = False
    return ev


def part1():
    print("1) R6S quick 4k: the 4th row (unreadable victim name) is found, the ending keeps it")
    a = M.r6s_analyse_entry(ACE, {})
    ks = a["kills"]
    check("4k ace: 4 kills found", len(ks) == 4, str([(k["t"], k["victim"]) for k in ks]))
    want = [8.867, 11.2, 12.133]
    check("the first three kills are unchanged (LengeneiChrigu 8.867, Dosenananas 11.2, Timeless- 12.133)",
          [k["t"] for k in ks[:3]] == want and [k["victim"] for k in ks[:3]] == ["LengeneiChrigu", "Dosenananas", "Timeless-"], str(ks[:3]))
    if len(ks) == 4:
        k4 = ks[3]
        check(f"the 4th kill is the row at {ACE_ROW4_S:.2f} s (within one OCR frame): {k4['t']:.3f} s, my name read {k4['ks']:.2f}, {k4['hits']} frames",
              abs(k4["t"] - ACE_ROW4_S) <= OCR_FRAME_S + 1e-6 and k4["ks"] >= 0.9 and k4["hits"] >= M.R6S_BLIP_F, str(k4))
    keep = M.R6S_BLANK_VICTIM[0]
    M.R6S_BLANK_VICTIM[0] = False
    try:
        a_off = M.r6s_analyse_entry(ACE, {})
    finally:
        M.R6S_BLANK_VICTIM[0] = keep
    check("switch off: 3 kills (the bug: the row was dropped for its empty victim side)", len(a_off["kills"]) == 3, str(len(a_off["kills"])))
    one = copy.deepcopy(ACE)                                     # the blank row read only once (its 2nd read removed): one blank read is no kill
    one["ocr"] = [f_ for f_ in one["ocr"] if f_[0] != 222]
    check("a row read blank only once is not a kill", len(M.r6s_analyse_entry(one, {})["kills"]) == 3)
    slide = copy.deepcopy(ACE)                                   # frame 222 shows the same row WITH a victim name: the blank read at 207 was it sliding in
    for f_ in slide["ocr"]:
        if f_[0] == 222:
            f_[2].append([500, 217, 600, 236, "Somebody", 0.98])
    ks_s = M.r6s_analyse_entry(slide, {})["kills"]
    check("a blank read followed by the same row with a name = one kill (the named one), not two", len(ks_s) == 4 and ks_s[3]["victim"] == "Somebody", str([(k["t"], k["victim"]) for k in ks_s]))

    T = helpers()
    evs = copy.deepcopy(M.fake_events())
    ace = ace_event(ks)
    head = max(evs, key=lambda e: e["score"])
    ace["score"] = head["score"] - 0.01
    for e in evs:
        if e is not head:
            e["post"] = 0.4                                       # nothing else may end the montage: the 4k is the ending
    evs = sorted(evs + [ace], key=lambda e: -e["score"])
    cfg = dict(M.DEFAULT_CONFIG)
    keep_audio = M.clip_audio
    M.clip_audio = lambda rec, *a_, **k_: {"stream": None, "lufs": None}
    try:
        song = {"path": str(T.SONG), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
        plan = M.plan_montage(cfg, "r6s", evs, song, T.an(), 5, "hype", "optimal", [], [])
    finally:
        M.clip_audio = keep_audio
    tk = [t for t in plan["takes"] if t["path"] == ace["path"]]
    check("the 4k is in the montage", len(tk) == 1)
    if tk:
        t = tk[0]
        last = plan["takes"][-1]
        check("it is the ending take", t is last and t.get("ending"), str(t.get("role")))
        check("the ending take holds all 4 kills (inside its footage, in order)", t["n"] == 4 and len(t["kills_out"]) == 4 and not M.kill_window_audit(t), str(M.kill_window_audit(t)))
        ko = t["f0"] / M.OUT_FPS + t["kills_out"][-1]
        fs, fl = M.outro_fade(plan)
        tail = plan["duration"] - ko
        check(f"the fade to black starts after the 4th kill (kill {ko:.2f} s, fade {fs:.2f} s over {fl:.2f} s, video ends {plan['duration']:.2f} s)", fs >= ko + M.OUTRO_ROW_READ - 1e-3, f"{fs} {ko}")
        check(f"the 4th kill keeps its ending tail ({tail:.2f} s after it, at least the fade)", tail >= fl - 1e-3 and tail >= M.ENDING_MIN_POST - 0.05, f"{tail}")
        check("the cut list check is clean", not M.verify_cutlist(plan, log=False), str(M.verify_cutlist(plan, log=False)))
        bad = copy.deepcopy(plan)
        bad["outro"]["fade_start"] = round(ko - 0.3, 4)
        check("the cut list check reports a fade that starts before the last kill", any("fades to black" in b for b in M.verify_cutlist(bad, log=False)),
              str(M.verify_cutlist(bad, log=False)))


def part2():
    print("2) sky: one set of rules for Valorant, CS2 and R6S")
    T = helpers()
    base, _ = T.mk(M, "valorant", "aggressive", 11, eff={"valorant": "extra", "cs2": "extra", "r6s": "extra"})
    keep = {n: getattr(M, n) for n in ("sky_src_frames", "sky_grab_frames", "sky_eyedrop", "sky_take_mask")}
    M.sky_src_frames = lambda t, f0, f1: None
    M.sky_grab_frames = lambda *a_, **k_: [np.zeros((54, 96, 3), np.uint8)]
    M.sky_eyedrop = lambda img: (None, {"ok": True, "cov": 0.2})
    M.sky_take_mask = lambda t, x, zone, path, ramp=False, plan=None: {"bad": 0, "window": 10, "mean_y": 120.0, "cov": 0.2, "held": 0, "frames": 10, "horizon": 0.4}
    par = M.SKY_MASK_PAR[0]
    M.SKY_MASK_PAR[0] = False
    res = {}
    try:
        for g in ("valorant", "cs2", "r6s"):
            q = copy.deepcopy(base)
            q["game"] = g
            for t in q["takes"]:
                t["xfx"] = []
            M.assign_extra_fx(q, g, int(q.get("seed") or 1), [], energy=0.8, sky_on=True)
            cands = [(ti, x["p"], x.get("why")) for ti, t in enumerate(q["takes"]) for x in t.get("xfx") or [] if x["k"] == "sky"]
            M.xfx_probe_sky(q, tmpdir=str(TMP / f"sky_{g}"))
            kept = [ti for ti, t in enumerate(q["takes"]) for x in t.get("xfx") or [] if x["k"] == "sky" and x.get("ok")]
            res[g] = {"cands": cands, "max": q["xfx_sky_max"], "space": q["xfx_sky_space"], "kept": kept, "roles": [q["takes"][i].get("role") for i in kept],
                      "calm_cands": sum(1 for ti, _p, _w in cands if q["takes"][ti].get("role") == "calm"),
                      "gaps": [b - a for a, b in zip(*(lambda gp: (gp, gp[1:]))(sorted(q["takes"][i]["f0"] / M.OUT_FPS + x["p"] for i in kept for x in q["takes"][i]["xfx"] if x["k"] == "sky")))]}
    finally:
        for n, v in keep.items():
            setattr(M, n, v)
        M.SKY_MASK_PAR[0] = par
    v = res["valorant"]
    print(f"  (valorant: {len(v['cands'])} candidates, {v['calm_cands']} of them calm, budget {v['max']}, {v['space']:.0f} s apart, kept takes {[i + 1 for i in v['kept']]} {v['roles']})")
    for g in ("cs2", "r6s"):
        check(f"{g}: the same sky candidates, budget and spacing as Valorant", (res[g]["cands"], res[g]["max"], res[g]["space"]) == (v["cands"], v["max"], v["space"]))
        check(f"{g}: the same kept skies as Valorant", res[g]["kept"] == v["kept"], f"{res[g]['kept']} vs {v['kept']}")
    for g, r in res.items():
        check(f"{g}: calm takes were candidates ({r['calm_cands']}) but none keeps a sky; kept roles {r['roles']}", r["calm_cands"] > 0 and r["kept"] and "calm" not in r["roles"], str(r["roles"]))
        check(f"{g}: at most {r['max']} skies, at least {r['space']:.0f} s apart", len(r["kept"]) <= r["max"] and all(d_ >= r["space"] - 1e-6 for d_ in r["gaps"]), str(r["gaps"]))
    t_ = {"role": "calm"}
    check("sky_role_ok: calm no, build / drop / headline / ending yes (no game input)", not M.sky_role_ok(t_) and all(M.sky_role_ok({"role": r_}) for r_ in ("build", "drop", "headline"))
          and M.sky_role_ok({"role": "calm", "ending": True}) and list(inspect.signature(M.sky_role_ok).parameters) == ["t"])
    check("budget and spacing ignore the game", len({M.sky_max_for(150, g) for g in ("valorant", "cs2", "r6s", None)}) == 1 and len({M.sky_spacing_for(g) for g in ("valorant", "cs2", "r6s", None)}) == 1)
    src = inspect.getsource(M.sky_take_mask)
    check("the mask opacity (solid family colour) has no game input", M.SKY_FAM_OPACITY == 1.0 and "game" not in src and "SKY_FAM_OPACITY" in src)


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
    sys.exit(1 if FAILS else 0)
