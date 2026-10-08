"""V7.1 plan-level iteration benchmark (read-only, never imported by the app). Per song, in its own process and on its own COPY of montage_data:
the existing dry planner on the pinned takes (7 real Valorant clips, CS2 trio, ~15 CS2 singles) with the V1 map and the V2 map, same seed / song,
kills judged against the independent kick detector. V1 results are cached in compare_out/iter_v1.json (V1 never changes).
    python -m songmap_v2.iter [--v1] [--jobs N] [--full] <song fragment> ..."""
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

SET8 = ["Silicon XX", "pretty afternoon", "prety - ", "Beautiful Now - Zedd", "life kinda sucks", "too much (hardtekk)", "#eurodab", "ALWAYS BEEN MINE"]
SET19_EXTRA = ["(nendest)", "530 - DONDA", "24 songs - Six Zeta", "AI Slop", "16 - Baby Keem", "A Bar Song", "No Time To Die", "Better Now - Post Malone",
               "2 time zones", "INSONAMIA", "Beautiful Now - Yosuf"]
import os
V1_CACHE = HERE / "compare_out" / ("iter_v1_frozen.json" if os.environ.get("V7_DATA_SRC") else "iter_v1_live.json")      # V1 results belong to the data they were planned on


def _one(args):
    frag, want_v1 = args
    import montage as M
    import songmap_compare as SC
    from songmap_v2 import bench, drophit, planbench as PB, timebase
    t0 = time.time()
    with PB.data_copy(M):                       # EVERYTHING (song listing included) runs on the copy: song_pool() writes its caches
        songs = [s for s in SC.v7_song_list(M, lambda *a: None) if frag.lower() in s[0].lower()]
        if not songs:
            files = sorted(Path(M.load_config().get("mp3_dir")).glob("*.mp3"))
            f = next((p for p in files if frag.lower() in p.name.lower()), None)
            if f is None:
                return {"frag": frag, "error": "song not found"}
            p = str(f).replace("\\", "/")
            pool = {str(s["path"]).replace("\\", "/"): s for s in M.song_pool(M.load_config(), cached_only=True)[0]}
            songs = [(f.stem, p, (pool.get(p) or {}).get("csv_bpm"), "")]
        label, path, csv, _ = songs[0]
        raw = {str(x["path"]).replace("\\", "/"): str(x["path"]) for x in M.song_pool(M.load_config(), cached_only=True)[0]}
        path = raw.get(path, path)                  # the pool's own spelling of the path: the V1 / V2 caches are keyed with it
        res = {"frag": frag, "song": label, "path": path, "csv": csv}
        sets = PB.take_sets(M)
        y, sr = timebase.decode(path)
        kicks = bench.strong_kicks(y, sr)
        res["dur"] = round(len(y) / sr, 1)
        kt_all, ks_all = bench.indep_kicks(y, sr)
        res["indep_drop"] = drophit.independent_drop(y, sr, kt_all[ks_all >= 0.3] if len(kt_all) else kt_all)
        modes = ["v2"] + (["v1"] if want_v1 else [])
        for mode in modes:
            allk, info = [], {"sets": {}}
            for sname, (game, paths) in sets.items():
                try:
                    plan, lines = PB.run_plan(M, game, paths, path, mode)
                except Exception as ex:
                    info["sets"][sname] = {"error": f"{type(ex).__name__}: {ex}"}
                    continue
                mm = PB.measure(plan, kicks, [])
                kt = PB.kill_times(plan)
                mm["kills"] = [round(t, 3) for t, *_ in kt]
                mm["fallback"] = next((l for l in lines if "fallback" in l), None)
                mm["headline"] = drophit.headline(plan)
                mm["drophit"] = drophit.distances(mm["headline"], res["indep_drop"]["t"] if res["indep_drop"]["clear"] else None)
                info["sets"][sname] = mm
                allk += mm["dists"]
            info["all"] = PB.summarize(allk)
            info["takes"] = sum(s.get("takes", 0) for s in info["sets"].values())
            info["events"] = sum(s.get("events", 0) for s in info["sets"].values())
            res[mode] = info
        m = M.get_songmap(path, csv, version="v2")
        res["map"] = {"bpm": m["bpm"], "conf": m["v2"]["grid_confidence"], "drops": [d["t"] for d in m["drops"]], "drop": m["drop"],
                      "drop_strength": m["drop_strength"], "steady": m["steady"]}
    res["secs"] = round(time.time() - t0)
    return res


def run(frags, want_v1=False, jobs=8):
    cache = json.loads(V1_CACHE.read_text(encoding="utf-8")) if V1_CACHE.exists() else {}
    todo = [(f, want_v1 or f not in cache) for f in frags]
    ctx = mp.get_context("spawn")
    with ctx.Pool(min(jobs, len(todo))) as pool:
        out = pool.map(_one, todo)
    rows = []
    for r in out:
        if "error" in r and "song" not in r:
            print(r["frag"], r["error"])
            continue
        if "v1" in r:
            cache[r["frag"]] = {"v1": r["v1"], "csv": r["csv"], "path": r["path"]}
        else:
            r["v1"] = cache[r["frag"]]["v1"]
        rows.append(r)
    V1_CACHE.parent.mkdir(exist_ok=True)
    V1_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return rows


def fmt(rows):
    lines = []
    tot = {"better15": 0, "worse": 0, "n": 0}
    for r in rows:
        a, b = r["v1"]["all"], r["v2"]["all"]
        if not a["n"] or not b["n"]:
            lines.append(f"{r['song'][:30]:30} no data")
            continue
        dm = a["median_ms"] - b["median_ms"]
        dp = a["p95_ms"] - b["p95_ms"]
        tot["n"] += 1
        tot["better15"] += dm >= 15
        tot["worse"] += (dm < -5 or dp < -5)
        same = r["v1"]["takes"] == r["v2"]["takes"] and r["v1"]["events"] == r["v2"]["events"]
        lines.append(f"{r['song'][:30]:30} med {a['median_ms']:6.1f}->{b['median_ms']:6.1f} ({dm:+6.1f}) p95 {a['p95_ms']:7.1f}->{b['p95_ms']:7.1f} "
                     f"w30 {a['within30']:.0%}->{b['within30']:.0%} takes/ev {r['v1']['takes']}/{r['v1']['events']}->{r['v2']['takes']}/{r['v2']['events']}"
                     f"{'' if same else ' DIFF'} bpm {r['map']['bpm']:.1f} conf {r['map']['conf']:.2f} drops {len(r['map']['drops'])}")
    lines.append(f"improved>=15ms: {tot['better15']}/{tot['n']}  worse(>5ms med or p95): {tot['worse']}/{tot['n']}")
    return "\n".join(lines)


if __name__ == "__main__":
    args = sys.argv[1:]
    v1 = "--v1" in args
    jobs = 8
    if "--jobs" in args:
        jobs = int(args[args.index("--jobs") + 1])
        del args[args.index("--jobs"):args.index("--jobs") + 2]
    full = "--full" in args
    frags = [a for a in args if not a.startswith("--")] or (SET8 + (SET19_EXTRA if full else []))
    t0 = time.time()
    rows = run(frags, v1, jobs)
    (HERE / "compare_out" / "iter_last.json").write_text(json.dumps(rows, default=float), encoding="utf-8")
    print(fmt(rows))
    print(f"{time.time() - t0:.0f} s")
