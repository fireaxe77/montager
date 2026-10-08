"""V7.4.5 helpers: grade the V2 drops against tests/data/drop_labels_refined.json (0.3 s / 1.0 s), tune vs held-out songs, confidence, fallback count."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFINED = HERE / "data" / "drop_labels_refined.json"


def load_refined():
    return json.load(open(REFINED, encoding="utf-8"))


def held_hash():
    d = load_refined()
    return hashlib.sha1(json.dumps({k: d["songs"][k] for k in sorted(d["held_out_songs"])}, sort_keys=True).encode()).hexdigest()[:12]


def grade(M, cfg, V, songs_only=None, log=None):
    """rows: one per label: {song, set, hard, t, tol, status 0.3/1.0, dist, drops, conf}"""
    d = load_refined()
    songs, _ = V.find_songs(M, cfg, list(d["songs"]))
    rows = []
    for f, tl in d["songs"].items():
        if f not in songs or (songs_only and f not in songs_only):
            continue
        drops, main, m = V.map_drops(M, songs[f])
        v2 = m.get("v2") or {}
        conf = {round(float(x["t"]), 2): x.get("conf") for x in m.get("drops", [])}
        for r in tl:
            if drops:
                n = min(drops, key=lambda x: abs(x - r["t"]))
                dd = n - r["t"]
            else:
                n, dd = None, None
            hit1 = dd is not None and abs(dd) <= 1.0
            hit3 = dd is not None and abs(dd) <= r["tol"] if r["status"] != "unrefined" else hit1
            rows.append({"song": f, "set": "held" if f in d["held_out_songs"] else "tune", "hard": r["hard"], "t": r["t"], "status": r["status"], "tol": r["tol"],
                         "hit03": bool(hit3), "hit10": bool(hit1), "dist": dd, "drops": [round(x, 2) for x in drops], "conf": conf.get(round(n, 2)) if n is not None else None,
                         "snaps": v2.get("drop_snap", [])})
    return rows


def summary(rows):
    out = {}
    for name, sel in (("tune", lambda r: r["set"] == "tune"), ("held", lambda r: r["set"] == "held")):
        rs = [r for r in rows if sel(r) and not r["hard"]]
        out[name] = {"n": len(rs), "hit03": sum(r["hit03"] for r in rs), "hit10": sum(r["hit10"] for r in rs)}
        hs = [r for r in rows if sel(r) and r["hard"]]
        out[name]["hard"] = f"{sum(r['hit10'] for r in hs)}/{len(hs)} at 1.0 s"
    return out


def show(rows, log=print):
    for r in rows:
        log(f"{r['song'][:22]:22} {r['set']:4} {'H' if r['hard'] else ' '} label {r['t']:7.2f}  {'HIT.3' if r['hit03'] else ('hit1 ' if r['hit10'] else 'miss ')}"
            f" {('%+.2f' % r['dist']) if r['dist'] is not None else '  - '}  conf={r['conf']}  drops={r['drops']}")
    log("SUMMARY " + json.dumps(summary(rows)))
