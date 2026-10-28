"""V9.1.4 tests.
  k) the frozen answer key (tests/answer_key_v914.json): every kill V9.1.3 changed, judged on the frames. For each clip the kill list is computed with the
     current code from the row data in V914_ROWS (default: montage_data\\cs2_rows_v1) and the kill cache of MONTAGER_DATA (a COPY of montage_data), dating memo off.
     Prints expected / got / PASS-FAIL per kill and the pass count; V914_KEY_OUT=<file.json> saves the per-kill result (for baseline comparisons).
  0) title-bar version V9.1.4, packaging / START_HERE, the V9.1.4 entry on top of both changelogs
python tests\\test_v914.py   (parts: V914_PARTS=0,k; k needs MONTAGER_DATA; V914_WORKERS=4)"""
import json
import os
import sys
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")
KEY = json.loads((HERE / "answer_key_v914.json").read_text(encoding="utf-8"))
TOL = float(KEY["tolerance_s"])
FAILS = []


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def _kills_of(names):
    """[clip name] -> {clip: [[t, victim, unsure]]} with the current code (one worker process)."""
    import montage as M
    if os.environ.get("V914_ROWS"):
        M.BORDER_DIR = Path(os.environ["V914_ROWS"])
    M._dating_memo_load = lambda: None
    M._dating_memo_save = lambda: None
    cfg, det, store = M.load_config(), M.Detector("cs2"), M.load_kills_cache()
    recs = {Path(r["path"]).name: r for r in M.scan_clips(cfg) if r.get("game") == "cs2"}
    res = {}
    for n in names:
        M.CS2_DATING_MEMO.clear()
        r = recs.get(n)
        e = store.get(M.kills_key(r, "cs2", det)) if r else None
        if not e:
            res[n] = None
            continue
        a = M.analyse_clip_entry(r, e, cfg, "cs2")
        lock = float(cfg.get("death_lock_s", 8.0))
        ks = [k for k in a["kills"] if (M.CS2_LOCK_ROW_ON[0] and k.get("border") and k.get("name_read"))
              or not any(d < k["t"] <= d + lock for d in a.get("deaths", []))]          # the death lock as verified_kills applies it
        res[n] = [[round(k["t"], 3), k.get("victim"), bool(k.get("t_unsure"))] for k in ks]
    return res


def judge(e, ks):
    """(pass, got text) for one key entry against a clip's kill list."""
    if e["expect"] == "ignore":
        return True, "ignored"
    if ks is None:
        return False, "clip / scan missing"
    ex = e["expect"]
    if ex == "kill":
        near = min(ks, key=lambda k: abs(k[0] - e["t"]), default=None)
        return bool(near and abs(near[0] - e["t"]) <= TOL + 1e-6), (f"{near[0]:.3f}" if near else "none")
    if ex == "no_kill":
        near = [k for k in ks if abs(k[0] - e["at"]) <= 0.15]
        return not near, (f"kill at {near[0][0]:.3f}" if near else "no kill")
    if ex == "kill_unsure":
        near = sorted([k for k in ks if e["row_on_screen_by"] - 0.6 <= k[0] <= e["t_region"] + 0.6], key=lambda k: abs(k[0] - e["t_region"]))
        return bool(near and near[0][2]), (f"{near[0][0]:.3f} unsure={near[0][2]}" if near else "none")
    return True, "ignored"


def partk():
    print("k) frozen answer key: every kill V9.1.3 changed, judged on the frames")
    names = sorted({e["clip"] for e in KEY["kills"] if e["expect"] != "ignore"})
    n = max(1, int(os.environ.get("V914_WORKERS", "4")))
    chunks = [names[i::n] for i in range(n)]
    kills = {}
    with ProcessPoolExecutor(n) as ex:
        for part in ex.map(_kills_of, chunks):
            kills.update(part)
    out, passed, judged = [], 0, 0
    for e in KEY["kills"]:
        ok, got = judge(e, kills.get(e["clip"]))
        if e["expect"] != "ignore":
            judged += 1
            passed += ok
        want = {"kill": lambda: f"{e['t']:.3f}", "no_kill": lambda: f"no kill near {e['at']}", "kill_unsure": lambda: f"kill flagged unsure ({e['t_region']})",
                "ignore": lambda: "ignored"}[e["expect"]]()
        print(f"  #{e['id']:3} {'PASS' if ok else 'FAIL'}  want {want:30} got {got:22} {e['victim']!s:22.22} {e['clip'][:50]}")
        out.append({"id": e["id"], "pass": bool(ok), "got": got})
    print(f"\nanswer key: {passed} of {judged} pass")
    if os.environ.get("V914_KEY_OUT"):
        Path(os.environ["V914_KEY_OUT"]).write_text(json.dumps({"passed": passed, "judged": judged, "kills": out}), encoding="utf-8")
    base = os.environ.get("V914_BASELINE")
    if base:
        b = {x["id"]: x["pass"] for x in json.loads(Path(base).read_text(encoding="utf-8"))["kills"]}
        worse = [x["id"] for x in out if b.get(x["id"]) and not x["pass"]]
        check(f"no kill that passed at baseline fails now ({len(worse)} worse)", not worse, worse)
    check(f"answer key: {passed} of {judged} pass", passed == judged)


def part0():
    import montage as M
    print("0) version, packaging, changelogs")
    check("APP_VERSION = V9.1.4", M.APP_VERSION == "V9.1.4", M.APP_VERSION)
    check("START_HERE names V9.1.4", (ROOT / "START_HERE.txt").read_text(encoding="utf-8").startswith("MONTAGER V9.1.4"))
    check("installer example names 9.1.4", "/DAppVersion=9.1.4 " in (ROOT / "packaging" / "montager.iss").read_text(encoding="utf-8"))
    check("release script example names v9.1.4", "(v9.1.4 for V9.1.4)" in (ROOT / "packaging" / "make_release.py").read_text(encoding="utf-8"))
    simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    check("Settings changelog: V9.1.4 on top of V9.1.3", 0 <= simple.index("## V9.1.4") < simple.index("## V9.1.3"))
    top = simple[simple.index("## V9.1.4"):simple.index("## V9.1.3")]
    check("Settings entry: plain points only", "KNOWN" not in top.upper() and "_" not in top and 1 <= top.count("\n- ") <= 4, top)
    check("CHANGELOG.md: V9.1.4 on top of V9.1.3", 0 <= tech.index("## V9.1.4") < tech.index("## V9.1.3"))


if __name__ == "__main__":
    for p_ in [x for x in os.environ.get("V914_PARTS", "0,k").split(",") if x]:
        {"0": part0, "k": partk}[p_]()
    print("\nV9.1.4 tests:", "ALL OK" if not FAILS else f"{len(FAILS)} FAILED: " + "; ".join(FAILS[:5]))
    sys.exit(1 if FAILS else 0)
