"""V9.0.1 tests (fast): drops after the intro. A drop is never skipped silently because the intro uses the start of the song.
  0) title-bar version V9.0.1, constants, the V9.0.1 entry in both changelogs (the two hotfixes named in the technical one)
  1) anchor_all_drops: a drop inside the intro's music / right at the first take is recorded with its exact reason; without an intro nothing is added
  2) the first take after the intro may have a run-up as short as INTRO_LEAD_MIN (rx.lead_min), nowhere else
  3) _extend_first: first take longer, later takes later, None when the footage does not last
  r) real data (MONTAGER_DATA = a COPY of montage_data): R6S "Sometimes", every drop anchored or told why
python tests\\test_v901.py   (parts: V901_PARTS=0,1,2,3,r)"""
import os
import sys
import tempfile
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="v901_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
warnings.simplefilter("ignore")
import montage as M                                                                          # noqa: E402
from test_v90 import fake_plan                                                               # noqa: E402

PARTS = [x for x in os.environ.get("V901_PARTS", "0,1,2,3").split(",") if x]
FAILS = []


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def part0():
    print("0) version, constants, changelogs")
    check("APP_VERSION = V9.0.1", M.APP_VERSION == "V9.0.1", M.APP_VERSION)
    check("first take run-up minimum 0.05 s (the usual one stays 0.3 s)", M.INTRO_LEAD_MIN == 0.05 and M.LEAD_MIN == 0.3)
    simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    check("Settings changelog: V9.0.1 on top of V9.0", simple.index("## V9.0.1") < simple.index("## V9.0 "))
    check("CHANGELOG.md: V9.0.1 on top of V9.0, both hotfixes named", tech.index("## V9.0.1") < tech.index("## V9.0 (") and "ENDING_HOLD_SLOW" in tech and "V1 / V2" in tech)


def part1():
    print("1) a drop near the intro is recorded, never skipped silently")
    p = fake_plan(intro=False)
    s0 = float(p["song"]["start_t"])
    notes = []
    M.INTRO_CTX["on"] = True
    try:
        M.anchor_all_drops(p, [(s0 - 3.0, 1.0, "label"), (s0 + 0.05, 1.0, "label")], "valorant", notes)
    finally:
        M.INTRO_CTX["on"] = False
    ds = {round(x["drop"], 1): x for x in p["drop_sync"]}
    a, b = ds[round(s0 - 3.0, 1)], ds[round(s0 + 0.05, 1)]
    check("a drop 3 s before the first take: recorded, inside the intro's music", a["take"] is None and "inside the intro" in a["why"], str(a))
    check("a drop 0.05 s after the first take starts: recorded with its reason", b["take"] is None and "after the first take starts" in b["why"], str(b))
    check("both are in the plan notes", sum(1 for n in notes if "not anchorable" in n) == 2)
    p2 = fake_plan(intro=False)
    n2 = []
    M.anchor_all_drops(p2, [(s0 - 3.0, 1.0, "label")], "valorant", n2)
    check("without an intro nothing is added (V9.0 plans stay as they are)", not p2.get("drop_sync") and not n2)


def part2():
    print("2) the first take's run-up")
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    body = src[src.index("def anchor_all_drops("):src.index("\n\nSERIES_FILE")]
    check("only the first take (f0 == 0, no rx yet) may use the short run-up, and only after the normal levers failed", 'ti == 0 and INTRO_CTX.get("on")' in body and '"rx" not in plan["takes"][0]' in body)
    fl = src[src.index("def flex_lead("):src.index("def flex_tail(")]
    check("flex_lead reads rx.lead_min (so the cut list check and the render accept it)", '(tk.get("rx") or {}).get("lead_min", LEAD_MIN)' in fl)


def part3():
    print("3) _extend_first")
    import numpy as np
    U = np.arange(0, 400) * 0.2
    ev = {"times": [10.0], "post": 5.0, "death_after": None, "path": "a", "pre": 20.0}

    def mk(c, kb, end, **k):
        return dict({"ev": dict(ev, path=f"p{c}"), "c": c, "kb": kb, "end": end, "lead_t": 1.0, "ramp": 1.0, "slow": False, "ending": False, "dur": float(U[end or c] - U[c])}, **k)
    t0 = mk(10, 15, 20)
    short = dict(t0, ev=dict(t0["ev"], post=0.3))
    check("no footage after the first take's last kill for the longer tail: None", M._extend_first([short, mk(20, 25, 30)], 2, U, 1e9) is None)
    end_t = dict(mk(30, 35, None), ending=True, fade_end=40)
    r = M._extend_first([t0, end_t], 2, U, 1e9)
    check("the first take's end moves 2 ticks, the ending's fade end too", r is None or (r[0]["end"] == 22 and r[1]["fade_end"] == 42), str(r and (r[0]["end"], r[1].get("fade_end"))))
    check("the ending's fade must still end inside the song", M._extend_first([t0, end_t], 2, U, float(U[41])) is None)


def partr():
    print("r) real data: R6S 'Sometimes'")
    cfg = M.load_config()
    for seed in (1, 7):
        plan, _ = M.make_plan(cfg, "r6s", seed=seed, song_path="E:/CLAUDECODE/Songs\\Sometimes - sozer.mp3")
        ds = plan.get("drop_sync") or []
        check(f"seed {seed}: every drop is anchored or has its reason ({sum(1 for x in ds if x['take'])} of {len(ds)})", all(x["take"] or x.get("why") for x in ds))


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
    sys.exit(1 if FAILS else 0)
