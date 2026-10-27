"""V9.1.2 tests (fast, no render).
  0) title-bar version V9.1.2, the version in the packaging / START_HERE, the V9.1.2 entry on top of both changelogs
  1) CS2 2k saved twice (real killfeed data; also the three rows of 'Counter-strike 2 2026.02.06 - 20.25.02.15.DVR.mp4' of 'CS2 2026-10-27 00-26-09.mov' / '00-25-58.mov' in tests/cs2_2k_0026_rows.json): the 2nd kill row (victim 'PASA', 24.13 s) slid up
     one slot (heights 94 -> 92 -> 88 -> 81 -> 64 within 5 frames); the in-between heights made a 19 px row pitch and the row was thrown out as a blob (V9.1.1 rule, ext 3).
     With the V9.1.2 rule (ext 4: a row that slid up into an accepted row's height is a row) it is a row and 00-26-09 has 2 kills; 00-25-58 keeps its one kill (the 1st of the 2k)
  2) nothing else changes: the V9.1.1 filter levels (False / True) and every sidecar read with them give exactly what the v9.1.1 tag gives (fixture + V8.7 test tracks)
  r) real data (MONTAGER_DATA = a COPY of montage_data with the V9.1.2 sidecar of 00-26-09; the clips in E:/Movies): the pair plans as ONE 2k event (00-26-09 @ 17.13 + 24.13,
     the 1st kill merged as a duplicate of 00-25-58 @ 28.53); 'Replay 2026-06-08 23-33-30 -> 23-33-17' and 'Replay 2026-07-19 20-31-38 -> 20-31-37' still merge
  g) real data: every cached CS2 sidecar older than ext 4 gives the same border analysis as v9.1.1; every cached Valorant / R6S clip gives the same kills / rejects as v9.1.1
python tests\\test_v912.py   (parts: V912_PARTS=0,1,2  real data: V912_PARTS=r,g with MONTAGER_DATA)"""
import copy
import json
import os
import random
import sys
import tempfile
import types
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="v912_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
warnings.simplefilter("ignore")
import montage as M                                                                          # noqa: E402
from _run import run as run_                                                                 # noqa: E402

PARTS = [x for x in os.environ.get("V912_PARTS", "0,1,2").split(",") if x]
FAILS = []
FX = json.loads((HERE / "cs2_2k_0026_rows.json").read_text(encoding="utf-8"))
PASA_ID = 7                             # the tracker's id of the 2nd kill row in raw_0026_09
CLIP_A, CLIP_B = "CS2 2026-10-27 00-25-58.mov", "CS2 2026-10-27 00-26-09.mov"


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


_BASE = []


def base():
    """The montage module of the v9.1.1 tag (same data folder)."""
    if not _BASE:
        src = (HERE / "test_v842.py").read_text(encoding="utf-8")
        ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
        exec(compile(src[:src.index("def part0")], str(HERE / "test_v842.py"), "exec"), ns)
        ns["BASE_REF"] = "v9.1.1"
        _BASE.append(ns["load_base"]())
    return _BASE[0]


def kills_of(b):
    return [(round(k["t"], 3), k["victim"]) for k in b["kills"]]


def part0():
    print("0) version, packaging, changelogs")
    check("APP_VERSION = V9.1.2", M.APP_VERSION == "V9.1.2", M.APP_VERSION)
    check("START_HERE names V9.1.2", (ROOT / "START_HERE.txt").read_text(encoding="utf-8").startswith("MONTAGER V9.1.2"))
    check("installer example names 9.1.2", "/DAppVersion=9.1.2 " in (ROOT / "packaging" / "montager.iss").read_text(encoding="utf-8"))
    check("release script example names v9.1.2", "(v9.1.2 for V9.1.2)" in (ROOT / "packaging" / "make_release.py").read_text(encoding="utf-8"))
    simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    check("Settings changelog: V9.1.2 on top of V9.1.1", 0 <= simple.index("## V9.1.2") < simple.index("## V9.1.1"))
    top = simple[simple.index("## V9.1.2"):simple.index("## V9.1.1")]
    check("Settings entry: headline names the 2k, plain points only", "2k" in top.splitlines()[0].lower() and "KNOWN" not in top.upper() and "_" not in top
          and 1 <= top.count("\n- ") <= 4, top)
    check("CHANGELOG.md: V9.1.2 on top of V9.1.1", 0 <= tech.index("## V9.1.2") < tech.index("## V9.1.1"))


def part1():
    print("1) CS2 2k saved twice: the 2nd kill row of 00-26-09 is a row, the clip has 2 kills")
    raw, n = FX["raw_0026_09"]["tracks"], FX["raw_0026_09"]["n"]
    pasa = next(t for t in raw if t["id"] == PASA_ID)
    check("the 2nd row slid up one slot (94 -> 92 -> 88 -> 81 -> 64) into the height of the 1st row", [s[1] for s in pasa["slots"]] == [94, 92, 88, 81, 64]
          and M._slid_into_row(pasa, [t for t in raw if t["id"] == 3]), pasa["slots"])
    old_r, old_b = M.border_shape_filter(copy.deepcopy(raw), n, fix=True)
    new_r, new_b = M.border_shape_filter(copy.deepcopy(raw), n, fix=M.BORDER_FIX)
    check("V9.1.1 rule (ext 3): the 2nd kill row is thrown out as a blob", PASA_ID in [t["id"] for t in old_b] and PASA_ID not in [t["id"] for t in old_r])
    check("V9.1.2 rule (ext 4): the 2nd kill row is a row", PASA_ID in [t["id"] for t in new_r])
    check("V9.1.2 rule: the other rows / blobs stay as they were", sorted(t["id"] for t in new_r) == sorted([t["id"] for t in old_r] + [PASA_ID])
          and [t["id"] for t in new_b] == [t["id"] for t in old_b if t["id"] != PASA_ID], ([t["id"] for t in new_r], [t["id"] for t in new_b]))
    check("a new sidecar is ext 4 and is read with the V9.1.2 rule", M.BORDER_EXT == 4 and M.border_fix_kw({"ext": 4}) == {"fix": M.BORDER_FIX}
          and M.border_fix_kw({"ext": 3}) == {"fix": True} and M.border_fix_kw({"ext": 2}) == {})
    raw3, n3 = FX["raw_2026_02_06"]["tracks"], FX["raw_2026_02_06"]["n"]
    o3 = [t["id"] for t in M.border_shape_filter(copy.deepcopy(raw3), n3, fix=True)[0]]
    r3 = [t["id"] for t in M.border_shape_filter(copy.deepcopy(raw3), n3, fix=M.BORDER_FIX)[0]]
    check("2026.02.06: three kill rows pushed up together (the 2nd one ends in the middle slot): V9.1.1 keeps 1, V9.1.2 all 3", o3 == [0] and sorted(r3) == [0, 1, 2], (o3, r3))
    sc9 = FX["sidecar_0026_09"]
    b9 = M.border_analysis(copy.deepcopy(sc9), M.DEFAULT_CONFIG, [])
    ks = kills_of(b9)
    check("00-26-09: 2 kills, 17.13 s (PKXPJ) and 24.13 s (PASA)", len(ks) == 2 and abs(ks[0][0] - 17.133) < 0.02 and abs(ks[1][0] - 24.133) < 0.02
          and "PKXPJ" in ks[0][1] and ks[1][1] == "PASA", ks)
    check("00-26-09: both kills read my name", all(k["name_read"] for k in b9["kills"]))
    b9_old = M.border_analysis(dict(copy.deepcopy(sc9), ext=3), M.DEFAULT_CONFIG, [])
    check("the same sidecar read with the V9.1.1 rule: 1 kill (the bug)", len(b9_old["kills"]) == 1, kills_of(b9_old))
    b8 = M.border_analysis(copy.deepcopy(FX["sidecar_0025_58"]), M.DEFAULT_CONFIG, [])
    check("00-25-58: one kill, the 1st of the 2k (28.53 s; the duplicate merge with 00-26-09 @ 17.13 is checked in part r)",
          len(b8["kills"]) == 1 and abs(b8["kills"][0]["t"] - 28.533) < 0.02, kills_of(b8))


def part2():
    print("2) older sidecars and the V9.1.1 filter levels are read exactly as v9.1.1 reads them")
    B = base()
    raw, n = FX["raw_0026_09"]["tracks"], FX["raw_0026_09"]["n"]
    for fx in (False, True):
        a = [t["id"] for t in M.border_shape_filter(copy.deepcopy(raw), n, fix=fx)[0]]
        b = [t["id"] for t in B.border_shape_filter(copy.deepcopy(raw), n, fix=fx)[0]]
        check(f"fix={fx}: same rows as v9.1.1", a == b, (a, b))
    v87 = HERE / "test_v87.py"

    def trk(i, first, last, hits, y0, y1, slots):
        return {"id": i, "first": first, "last": last, "hits": hits, "x0": 283, "x1": 528, "y0": y0, "y1": y1, "slots": [[f, y] for f, y in slots]}
    v87_tracks = [trk(1, 726, 874, 149, 64, 95, [(726, 64)]), trk(2, 776, 874, 97, 95, 121, [(776, 90), (783, 94), (799, 90), (805, 95)]),
                  trk(3, 829, 874, 37, 155, 182, [(829, 155)]), trk(4, 861, 874, 14, 187, 212, [(861, 187)])]
    good = [trk(1, 100, 300, 190, 64, 95, [(100, 64)]), trk(2, 150, 300, 140, 95, 126, [(150, 95)]), trk(3, 200, 300, 90, 126, 157, [(200, 126)])]
    junk = good + [trk(9, 220, 260, 40, 175, 191, [(220, 175)])]
    check("V8.7 fragment case: the V9.1.2 rule keeps all four rows too", len(M.border_shape_filter(copy.deepcopy(v87_tracks), 875, fix=M.BORDER_FIX)[0]) == 4)
    check("V8.7 normal clip: 3 rows with the V9.1.2 rule", len(M.border_shape_filter(copy.deepcopy(good), 400, fix=M.BORDER_FIX)[0]) == 3)
    check("V8.7 junk off the grid: still not a row with the V9.1.2 rule", len(M.border_shape_filter(copy.deepcopy(junk), 400, fix=M.BORDER_FIX)[0]) == 3)
    for name, sc in (("00-25-58 (ext 3)", FX["sidecar_0025_58"]), ("00-26-09 read as ext 3", dict(FX["sidecar_0026_09"], ext=3)),
                     ("00-26-09 read as ext 2", dict(FX["sidecar_0026_09"], ext=2))):
        a = M.border_analysis(copy.deepcopy(sc), M.DEFAULT_CONFIG, [])
        b = B.border_analysis(copy.deepcopy(sc), B.DEFAULT_CONFIG, [])
        check(f"{name}: border analysis identical to v9.1.1", kills_of(a) == kills_of(b) and [r["reason"] for r in a["rej"]] == [r["reason"] for r in b["rej"]],
              (kills_of(a), kills_of(b)))
    r = run_([sys.executable, str(v87)], text=True, cwd=str(ROOT), env=dict(os.environ, V87_PARTS="4"), timeout=600)
    check("tests/test_v87.py part 4 (row grid, V8.7) passes", r.ok and "FAIL" not in r.stdout, r.tail(600))


def _events(names):
    """(pool, events, merged): merged = [(clip, t, survivor clip, survivor t)] of the kill ledger's proven duplicates."""
    cfg = M.load_config()
    recs = [r for r in M._cs2_recs(cfg) if Path(r["path"]).name in names]
    pool, _ = M.game_pool(cfg, "cs2", paths=[r["path"] for r in recs])
    evs, _notes = M.build_events(pool, "cs2", cfg, random.Random(1))
    led = M.LAST_LEDGER[0]
    merged = []
    for r in led.rows:
        if r.get("merged"):
            tgt = led.rows[r["merged"]["into"] - 1]
            merged.append((r["clip"], round(r["t"], 1), tgt["clip"], round(tgt["t"], 1)))
    return pool, evs, merged


def partr():
    print("r) real data: the pair plans as one 2k; other duplicate merges stay")
    pool, evs, merged = _events({CLIP_A, CLIP_B})
    kn = {Path(it["rec"]["path"]).name: len(it["kills"]) for it in pool}
    check("clip list: 00-26-09 has 2 kills, 00-25-58 has 1", kn.get(CLIP_B) == 2 and kn.get(CLIP_A) == 1, kn)
    check("the 1st kill is merged as a duplicate (00-26-09 @ 17.1 = 00-25-58 @ 28.5)",
          (CLIP_B, 17.1, CLIP_A, 28.5) in merged, merged)
    check("ONE event, a 2k from 00-26-09 at 17.13 + 24.13", len(evs) == 1 and evs[0]["n"] == 2 and Path(evs[0]["path"]).name == CLIP_B
          and [round(x, 1) for x in evs[0]["times"]] == [17.1, 24.1], [(Path(e["path"]).name, e["n"], e["times"]) for e in evs])
    for a, b in (("Replay 2026-06-08 23-33-30.mov", "Replay 2026-06-08 23-33-17.mov"), ("Replay 2026-07-19 20-31-38.mov", "Replay 2026-07-19 20-31-37.mov")):
        pool, evs, merged = _events({a, b})
        check(f"{a} -> {b} still merges as a duplicate", any(m[0] == a and m[2] == b for m in merged) and len(evs) == 1,
              (merged, [(Path(e["path"]).name, e["n"]) for e in evs]))


def partg():
    print("g) real data: older CS2 sidecars, Valorant and R6S read exactly as v9.1.1")
    B = base()
    cfg = M.load_config()
    n_same = n_all = 0
    for p in sorted(M.BORDER_DIR.glob("*.json")):
        try:
            sc = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            continue
        if sc.get("ext", 1) >= 4:
            continue
        n_all += 1
        a = M.border_analysis(copy.deepcopy(sc), cfg, [])
        b = B.border_analysis(copy.deepcopy(sc), cfg, [])
        if kills_of(a) == kills_of(b) and [r["reason"] for r in a["rej"]] == [r["reason"] for r in b["rej"]]:
            n_same += 1
        else:
            print("     differs:", p.name, kills_of(a), kills_of(b))
    check(f"CS2 sidecars before ext 4: {n_same} of {n_all} identical to v9.1.1", n_all > 0 and n_same == n_all)
    child = TMP / "kills_dump.py"                           # Valorant / R6S: each version in its own process (two montage modules in one process share imported-module state)
    child.write_text(CHILD, encoding="utf-8")
    res = {}
    for name, root in (("v9.1.2", ROOT), ("v9.1.1", Path(B.__file__).parent)):
        out = TMP / f"kills_{name}.json"
        r = run_([sys.executable, str(child), str(root), str(out)], text=True, cwd=str(root), timeout=3600)
        check(f"{name}: Valorant / R6S kill lists computed", r.ok and out.exists(), r.tail(400))
        res[name] = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    for g in ("valorant", "r6s"):
        a, b = res["v9.1.2"].get(g, {}), res["v9.1.1"].get(g, {})
        diff = [p for p in a if a[p] != b.get(p)]
        check(f"{g}: {len(a) - len(diff)} of {len(a)} cached clips give the same kills / rejects as v9.1.1", a and set(a) == set(b) and not diff, diff[:5])


CHILD = """import sys, os, json
sys.path.insert(0, sys.argv[1])
import montage as M
cfg = M.load_config(); store = M.load_kills_cache(); res = {}
for g in ("valorant", "r6s"):
    dg = M.load_dets(g).get(g); res[g] = {}
    for r in M.scan_clips(cfg):
        if r.get("game") != g or r.get("error") or not r.get("w"):
            continue
        e = store.get(M.kills_key(r, g, dg))
        if not e or e.get("error"):
            continue
        a = M.analyse_clip_entry(r, e, cfg, g)
        res[g][r["path"]] = [[[k["t"], k.get("victim")] for k in a["kills"]], [x["reason"] for x in a["rej"]]]
json.dump(res, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)
"""

for p_ in PARTS:
    {"0": part0, "1": part1, "2": part2, "r": partr, "g": partg}[p_]()
print("\nV9.1.2 tests:", "ALL OK" if not FAILS else f"{len(FAILS)} FAILED: " + "; ".join(FAILS))
sys.exit(1 if FAILS else 0)
