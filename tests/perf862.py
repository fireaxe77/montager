"""V8.6.2 tool: timing + identity of the speed work.
python tests/perf862.py auto <game> <song fragment> <seed> <out.json>   -> Manual Auto selection (paths) and its time; run with MONTAGE_NO_RO=1 for the old behaviour and compare the two json files.
python tests/perf862.py plan <game> <seed> <out.json>                    -> one automatic plan (make_plan scan=False): its text (without the lines that differ by time) + the time; compare before / after.
python tests/perf862.py cmp <a.json> <b.json>                            -> same selection / same plan text?"""
import json
import random
import sys
import time
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import montage as M                                                                           # noqa: E402

mode = sys.argv[1]
if mode == "auto":
    game, frag, seed, outp = sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
    cfg = M.load_config()
    songs, _, _ = M.song_pool(cfg, cached_only=True)
    song = [s for s in songs if frag.lower() in (s["title"] + " " + s["artist"] + " " + Path(s["path"]).name).lower()][0]
    an = M.get_songmap(song["path"], song.get("csv_bpm"))
    used = M.used_dates()
    pool, _st = M.game_pool(cfg, game)
    cands = []
    for it in pool:
        ks = sorted({round(float(k["t"]), 3) for k in it["kills"]}) if it.get("kills") else []
        if ks:
            cands.append({"path": it["rec"]["path"], "ks": ks, "kills": ks, "used": used.get(M._pkey(it["rec"]["path"]), "")})
    M.QUIET.on = True
    t0 = time.time()
    paths, info = M.auto_fill_verified(cfg, game, cands, song["path"], an, "auto", seed, rng=random.Random(seed))
    dt = time.time() - t0
    M.QUIET.on = False
    json.dump({"paths": sorted(paths), "seconds": round(dt, 1), "rounds": info["rounds"], "planned": round(info["length"], 1)}, open(outp, "w", encoding="utf-8"))
    print(f"auto {game}: {len(paths)} clips, planned {info['length']:.0f} s, {info['rounds']} rounds, {dt:.1f} s ({dt / max(1, info['rounds'] + 1):.1f} s per planning round)")
elif mode == "plan":
    game, seed, outp = sys.argv[2], int(sys.argv[3]), sys.argv[4]
    cfg = M.load_config()
    M.QUIET.on = True
    t0 = time.time()
    plan, text = M.make_plan(cfg, game, scan=False, seed=seed)
    dt = time.time() - t0
    M.QUIET.on = False
    json.dump({"text": text, "seconds": round(dt, 1), "duration": plan["duration"], "takes": [(t["path"], t["out_start"], t["dur"], [x["k"] for x in t.get("xfx", [])]) for t in plan["takes"]]}, open(outp, "w", encoding="utf-8"))
    print(f"plan {game} seed {seed}: {plan['duration']:.0f} s, {len(plan['takes'])} takes, {dt:.1f} s")
else:
    a, b = json.load(open(sys.argv[2], encoding="utf-8")), json.load(open(sys.argv[3], encoding="utf-8"))
    if "paths" in a:
        print("same selection:", a["paths"] == b["paths"], f"({len(a['paths'])} vs {len(b['paths'])} clips); seconds {a['seconds']} -> {b['seconds']}")
    else:
        la, lb = a["text"].splitlines(), b["text"].splitlines()
        diff = [x for x in zip(la, lb) if x[0] != x[1]]
        print("same plan text:", la == lb, f"({len(la)} lines, {len(diff)} differ); same takes:", a["takes"] == b["takes"], f"; seconds {a['seconds']} -> {b['seconds']}")
        for x, y in diff[:6]:
            print("   -", x[:160], "\n   +", y[:160])
