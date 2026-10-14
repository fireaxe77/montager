"""V8.1 tests: CS2 kills found by the red border, one physical killfeed row = one event.
  0) title-bar version V8.1; V8.1 on top of both changelogs
  1) row identity on synthetic tracks: fragments of one row (gap of any length inside a row's life, victim alike / unread with the same
     outline) are one row; a row lower than before, a clearly different victim, two places at once, longer apart than a row lives = two rows;
     born in one place at one frame / standing in one place at one time = one row (also a copy that later hops to the next row);
     another player's row never joins mine
  2) names: jumbled / misread versions of fireaxe on the killer side are mine, other players' names are not; a victim that only CONTAINS
     'fire' ('SkyFire') is not my death
  3) planner (CS2 only): the kills of one clip are one fight; clips of one fight group join the take across a few unsaved seconds
  4) frozen: CS2 / Valorant filter graphs + plan text, synthetic rows, tags, gaps vs V8.0.5
  r) (real data, ~5 min) the 21 ground-truth clips: kills / assists / deaths and their times; the stitched 3-kill fight of 2026.03.02 23.33
  g) (real data, ~10 min) guard: Valorant and R6S pools + events byte-identical to V8.0.5
Parts r and g run on a COPY of montage_data (V7_DATA_SRC picks the folder; the real folder is only read).
python tests\\test_v810.py   (parts: V810_PARTS=0,1,2,3,4,r,g)"""
import copy
import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("t805", str(ROOT / "tests" / "test_v805.py"))
T5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T5)
T2, T = T5.T2, T5.T
M, check, section, TMP, LOG = T.M, T.check, T.section, T.TMP, T.LOG
from _run import run, require                                                                 # noqa: E402
PARTS = [x for x in os.environ.get("V810_PARTS", "0,1,2,3,4,r,g").split(",") if x]
REFS = ("V8.0.5-good", "main")


def part0():
    section("0) version + changelog")
    check("APP_VERSION is V8.1", M.APP_VERSION == "V8.1")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.1 then V8.0.5", cl[0].startswith("## V8.1 ") and cl[1].startswith("## V8.0.5"), str(cl[:2]))
    sm = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8").splitlines()
    sh = [l for l in sm if l.startswith("## V")]
    check("simple changelog: 'CS2 kills now found by the red border', then V8.0.5", "CS2 kills now found by the red border" in sh[0] and sh[1].startswith("## V8.0.5"), str(sh[:2]))


def trk(i, t0, t1, y, w=300, hits=None, y_moves=()):
    f0, f1 = int(round(t0 * 30)), int(round(t1 * 30))
    slots = [[f0, y, 0]] + [[int(round(t * 30)), yy, 0] for t, yy in y_moves]
    return {"id": i, "first": f0, "last": f1, "hits": hits if hits is not None else f1 - f0 + 1, "x0": 533 - w, "x1": 533, "y0": y, "y1": y + 26, "slots": slots}


def cls(victims, verdict="kill", name_read=True, ktext="fireaxe"):
    return {"verdict": verdict, "name_read": name_read, "vtext": victims[0] if victims else "", "ktext": ktext,
            "votes": [(verdict, 3 if name_read else 1, "", ktext, v) for v in victims]}


def part1():
    section("1) row identity (synthetic tracks)")
    R = M._cs2_row_relation
    a, b = trk(1, 1.5, 1.6, 63), trk(2, 3.2, 4.2, 63)
    check("same row found again 1.6 s later, same place, victim read alike ('chararaoing(supromo]' / 'chararaoing (supromo]')",
          R(a, b, cls(["chararaoing(supromo]"]), cls(["chararaoing (supromo]"]), [a, b]) == "same")
    a, b = trk(1, 4.3, 4.9, 63), trk(2, 9.0, 12.0, 63)
    check("NL7 row lost for 4 s and found again in its slot: one row", R(a, b, cls(["NL7"]), cls(["NL7"]), [a, b]) == "same")
    c = trk(3, 12.2, 15.4, 123)
    check("the next row enters LOWER (NLS, 12.2 s): a new row", R(b, c, cls(["NL7"]), cls(["NLS"]), [a, b, c]) == "distinct")
    a, b = trk(1, 3.0, 5.4, 63, w=360), trk(2, 6.9, 10.7, 63, w=362)
    check("victim unread in the first fragment, same outline width: one row (miura)", R(a, b, cls([]), cls(["miura"]), [a, b]) == "same")
    a, b = trk(1, 0.5, 2.0, 63), trk(2, 9.5, 12.0, 63)
    check("same victim 9 s later (DM re-kill): longer apart than a row lives = two rows", R(a, b, cls(["Hexvenus"]), cls(["Hexvenus"]), [a, b]) == "distinct")
    a, b = trk(1, 3.9, 11.6, 63), trk(2, 10.8, 14.8, 93)
    check("two places at the same time with different victims: two rows", R(a, b, cls(["Magzatkioporator"]), cls(["xyecoc"]), [a, b]) == "distinct")
    a, b = trk(1, 9.5, 15.2, 63), trk(2, 14.8, 15.2, 160, hits=13)
    check("DM: the same victim twice at once, the second at the bottom of the feed: two rows", R(a, b, cls(["Berserk"]), cls(["Borsork"]), [a, b]) == "distinct")
    a, b = trk(1, 15.73, 16.3, 143, hits=16, y_moves=((16.23, 94),)), trk(2, 15.73, 16.7, 148, hits=16)
    check("born in one place at one frame (one copy later hops to the row above): one row", R(a, b, cls(["Tgrok_c obito"]), cls(["BriskBraln"]), [a, b]) == "same")
    a, b = trk(1, 9.67, 15.07, 93, y_moves=((13.5, 64),)), trk(2, 11.53, 15.1, 93)
    check("a track that starts where another row stands at that moment is that row", R(a, b, cls(["Zbigniew Zubr"]), cls(["krispo98"]), [a, b]) == "same")
    a, b = trk(1, 6.97, 7.2, 89, hits=3), trk(2, 8.73, 9.2, 89, hits=3)
    check("another player's row (killer 'fufel', no read of my name) never joins my row", R(a, b, cls(["BADZIDRA"], "other", False, "fufel"), cls(["xyecoc"]), [a, b]) == "distinct")
    a, b = trk(1, 3.1, 10.6, 123), trk(2, 3.3, 3.4, 63, hits=3)
    old = trk(0, 0.0, 7.4, 140)
    check("a 3-frame stray copy of a row above an older row (not at the bottom of the feed): one row",
          R(a, b, cls(["HErOAAM!"]), cls(["HErOAAA!"]), [old, a, b]) == "same")
    saved = M.CS2_ROWID_ON[0]
    try:
        M.CS2_ROWID_ON[0] = False
        a, b = trk(1, 4.3, 4.9, 63), trk(2, 9.0, 12.0, 63)
        check("switch off (CS2_ROWID_ON) = the V8.0.5 relation (gap > 1 s = distinct)", M._border_relation(a, b, cls(["NL7"]), cls(["NL7"])) == "distinct")
    finally:
        M.CS2_ROWID_ON[0] = saved


def part2():
    section("2) names")
    for w in ("fireaxe", "flreaxe", "Tiroaxo", "Tlrea", "lraxo", "Tir#EX#", "FiroaX RiclWiidborrioa", "火斧", "Fire"):
        check(f"'{w}' on the killer side is my name", M.cs2_me_jumbled(w))
    for w in ("THINK", "nd27", "DerKanalreiniger", "fufel", "halla", "nonliz", "sexymew", "Grockstein", "Meigl", "Vardaturan", "darulinekk", "Homie", ""):
        check(f"'{w}' is not my name", not M.cs2_me_jumbled(w))
    check("victim 'fireaxe火斧' is me", M.cs2_victim_is_me("fireaxe火斧"))
    check("victim 'flreaxe' is me", M.cs2_victim_is_me("flreaxe"))
    check("victim 'SkyFire' is not me", not M.cs2_victim_is_me("SkyFire"))


def part3():
    section("3) planner (CS2 only)")
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    body = src[src.index("def _build_events("):src.index("def make_event(")]
    check("CS2: the kills of one clip / group are one fight (gap = FIGHT_GAP_LONG_CLIP), gated on game == 'cs2'",
          'if game == "cs2" and CS2_ROWID_ON[0]:' in body and "gap_g = max(gap_g, FIGHT_GAP_LONG_CLIP)" in body)
    me = src[src.index("def make_event("):src.index("def make_event(") + 9000]
    check("CS2: the stitch joins clips up to the fight-group window apart (gated on cs2)",
          'if getattr(PAIR_CTX, "game", None) == "cs2" and CS2_ROWID_ON[0]:' in me and 'sgap = pair_gap("cs2")' in me)


def part4():
    section("4) frozen vs V8.0.5")
    T2.part5(REFS)
    T.part9(REFS, "V8.0")


GT = {   # clip -> kills (s), assists, deaths. Checked frame by frame against the footage (V8.1); times +- 0.35 s
    "2025.02.08 - 19.53": ([1.53, 8.67], [], [10.8]),
    "2025.08.05 - 12.56": ([0.53, 2.47, 6.93, 9.53, 13.7, 14.83], [], []),
    "2025.02.07 - 20.34": ([3.9, 7.33, 14.4], [], []),
    "2026.02.12 - 19.24": ([4.8, 7.73, 14.6], [], []),
    "2026-06-25 01-27-36": ([10.1, 11.43, 16.0], [], []),
    "2026-06-25 00-58-01": ([8.17, 13.77, 15.73], [], []),
    "2026-04-18 04-56-45": ([3.0, 10.37, 17.4], [], []),
    "2026.03.02 - 23.33": ([8.17, 13.73], [], []),
    "2026.02.25 - 00.03": ([7.3, 9.83, 14.07], [], []),
    "2026.02.11 - 18.41": ([5.7, 14.2], [], []),
    "2026.02.06 - 21.01": ([7.47, 14.23], [], []),
    "2026.02.05 - 22.56": ([4.33, 12.17, 14.47], [], []),
    "2026.01.31 - 23.53": ([11.0, 11.5, 13.03], [], [13.67]),
    "2026.01.30 - 20.03": ([4.1, 4.97, 12.13, 14.57], [9.63], []),
    "2026.01.14 - 23.42": ([2.23, 4.77, 11.13, 14.67], [], []),
    "2025.12.30 - 23.24": ([3.07, 7.93, 14.63], [], []),
    "2025.01.07 - 17.42": ([13.5, 14.83], [], []),
    "2025.01.06 - 23.32.19": ([1.8, 10.53, 12.03, 15.0], [], []),
    "2025.01.06 - 23.32.22": ([], [], []),
    "2025.01.06 - 23.13": ([7.6, 10.4, 14.23], [], []),          # KNOWN: a 4th kill (dz1nky, ~13.4 s) is below the killfeed region
    "2026-06-21 23-24-16": ([13.93, 15.27, 17.13], [], []),
    "2026-06-20 02-55-28": ([1.97, 14.4], [], []),
}
EVENTS = {"2026.03.02 - 23.33": 3, "2026.01.30 - 20.03": 4, "2026.01.14 - 23.42": 4, "2025.01.06 - 23.32.19": 4}

SCRIPT_R = r'''
import sys, json, random, os
sys.path.insert(0, os.getcwd())
import montage as M
from pathlib import Path
M.LOG_SINK[0] = lambda s: None
cfg = M.load_config()
pool, st = M.game_pool(cfg, "cs2")
det = M.Detector("cs2")
store = M.load_kills_cache()
by = {it["rec"]["path"]: it for it in pool}
res = {"clips": {}, "events": []}
for r in M._cs2_recs(cfg, only_scanned=True, det=det):
    e = store.get(M.kills_key(r, "cs2", det))
    a = M.analyse_clip_entry(r, e, cfg, "cs2")
    it = by.get(r["path"])
    res["clips"][Path(r["path"]).name] = {"kills": [k["t"] for k in (it["kills"] if it else [])], "deaths": a["deaths"],
                                          "assists": [j["t"] for j in a["rej"] if "assist" in j["reason"]]}
evs, notes = M.build_events(pool, "cs2", cfg, random.Random(1))
for e in evs:
    res["events"].append({"n": e["n"], "files": [Path(e["rec"]["path"]).name] + [Path(x["path"]).name for x in e.get("group", [])]})
json.dump(res, open(sys.argv[1], "w", encoding="utf-8"), ensure_ascii=False)
'''

SCRIPT_G = r'''
import sys, json, random, os
sys.path.insert(0, os.getcwd())
import montage as M
M.LOG_SINK[0] = lambda s: None
cfg = M.load_config()
res = {}
for g in ("valorant", "r6s"):
    pool, st = M.game_pool(cfg, g)
    pk = [(it["rec"]["path"], [(round(k["t"], 4), k.get("victim")) for k in it["kills"]], it.get("deaths"), [(j["t"], j["reason"]) for j in it["rej"]]) for it in pool]
    evs, notes = M.build_events(pool, g, cfg, random.Random(7))
    res[g] = {"pool": pk, "events": [(e["path"], e["times"], e["rows"], e["victims"], round(e["score"], 6)) for e in evs], "notes": notes}
open(sys.argv[1], "w", encoding="utf-8").write(json.dumps(res, sort_keys=True, default=str))
'''


def data_copy(tag):
    src = Path(os.environ.get("V7_DATA_SRC") or (ROOT / "montage_data"))
    d = TMP / f"data_{tag}"
    if not d.exists():
        shutil.copytree(src, d, ignore=shutil.ignore_patterns("logs", "plans", "theme_cache", "*_backup_*"))
    return d


def partr():
    section("r) the 21 ground-truth CS2 clips (real data, on a copy)")
    d = data_copy("r")
    (TMP / "r.py").write_text(SCRIPT_R, encoding="utf-8")
    o = TMP / "r.json"
    res = run([sys.executable, str(TMP / "r.py"), str(o)], text=True, cwd=ROOT, env=dict(os.environ, MONTAGER_DATA=str(d)), timeout=3600)
    ok, why = require(res, "CS2 ground-truth run")
    check("the CS2 run finished", ok, why)
    if not ok:
        return
    j = json.loads(o.read_text(encoding="utf-8"))
    near = lambda a, b: len(a) == len(b) and all(abs(x - y) <= 0.35 for x, y in zip(sorted(a), sorted(b)))
    for k, (ks, asl, ds) in GT.items():
        hit = [n for n in j["clips"] if k in n]
        if not hit:
            check(f"{k}: clip found", False)
            continue
        c = j["clips"][hit[0]]
        check(f"{k}: kills {ks}", near(c["kills"], ks), str([round(x, 2) for x in c["kills"]]))
        check(f"{k}: assists {asl}", near(c["assists"], asl), str([round(x, 2) for x in c["assists"]]))
        if ds:
            check(f"{k}: deaths {ds}", near(c["deaths"], ds), str([round(x, 2) for x in c["deaths"]]))
    for k, n in EVENTS.items():
        evs = [e for e in j["events"] if any(k in f for f in e["files"])]
        check(f"{k}: one fight of {n} kills (pre-clip row counted once)", len(evs) == 1 and evs[0]["n"] == n, str(evs))


def partg():
    section("g) guard: Valorant + R6S pools and events identical to V8.0.5 (real data, on copies)")
    ref = next((r_ for r_ in REFS if run(["git", "rev-parse", "--verify", "-q", r_ + "^{commit}"], cwd=ROOT).returncode == 0), "main")
    bd = TMP / "base_g"
    bd.mkdir(exist_ok=True)
    tar = run(["git", "archive", ref], cwd=ROOT).stdout
    run(["tar", "-x", "-C", str(bd)], input=tar, check=True)
    (TMP / "g.py").write_text(SCRIPT_G, encoding="utf-8")
    out = {}
    for tag, cwd in (("base", bd), ("new", ROOT)):
        d = data_copy("g_" + tag)
        o = TMP / f"g_{tag}.json"
        res = run([sys.executable, str(TMP / "g.py"), str(o)], text=True, cwd=cwd, env=dict(os.environ, MONTAGER_DATA=str(d)), timeout=3600)
        ok, why = require(res, f"guard run ({tag})")
        check(f"guard run {tag} ({ref if tag == 'base' else 'this tree'}) finished", ok, why)
        if not ok:
            return
        out[tag] = json.loads(o.read_text(encoding="utf-8"))
    for g in ("valorant", "r6s"):
        a, b = out["base"][g], out["new"][g]
        check(f"{g}: pool identical ({len(b['pool'])} clips with kills, every kill, death and rejected row)", a["pool"] == b["pool"])
        check(f"{g}: events identical ({len(b['events'])} events: times, rows, victims, scores)", a["events"] == b["events"])
        check(f"{g}: planner notes identical", a["notes"] == b["notes"])


if __name__ == "__main__":
    for k, fn in (("0", part0), ("1", part1), ("2", part2), ("3", part3), ("4", part4), ("r", partr), ("g", partg)):
        if k in PARTS:
            try:
                fn()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                T.check(f"part {k} ran without an exception", False, repr(ex))
    print(f"\n{len(T.FAILS)} FAIL" if T.FAILS else "\nALL OK", f"({time.time() - T.T0:.1f} s)")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if T.FAILS else 0)
