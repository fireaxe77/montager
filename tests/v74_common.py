"""V7.4 helpers: label table of the V2 map drops vs tests/data/drop_labels.json. Runs on a COPY of montage_data (MONTAGER_DATA)."""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LABELS = HERE / "data" / "drop_labels.json"


def load_labels():
    raw = json.load(open(LABELS, encoding="utf-8"))
    return float(raw.get("tolerance_s", 1.0)), raw["songs"]


def find_songs(M, cfg, frags):
    songs, _, _ = M.song_pool(cfg)
    res, missing = {}, []
    for f in frags:
        hit = [s for s in songs if f.lower() in (s["title"] or "").lower() or f.lower() in Path(s["path"]).stem.lower()]
        if f == "Les":                                      # 'Les' is a substring of many titles: whole-word / exact title only
            hit = [s for s in songs if (s["title"] or "").strip().lower() == "les"] or [s for s in songs if Path(s["path"]).stem.lower().endswith(" les")]
        if hit:
            res[f] = hit[0] if len(hit) == 1 else sorted(hit, key=lambda s: len(s["title"] or ""))[0]
            res[f]["_n"] = len(hit)
        else:
            missing.append(f)
    return res, missing


def map_drops(M, song):
    m = M.get_songmap(song["path"], song.get("csv_bpm"), version="v2")
    bt = m["beats"]
    return [float(d["t"]) for d in m.get("drops", [])], (float(bt[m["drop"]]) if m.get("drop") is not None else None), m


def classify(label_t, drops, tol):
    """('hit'|'early'|'late'|'missed', signed distance of the nearest map drop - label)."""
    if not drops:
        return "missed", None
    n = min(drops, key=lambda d: abs(d - label_t))
    dd = n - label_t
    if abs(dd) <= tol:
        return "hit", dd
    return ("early" if dd < 0 else "late") if abs(dd) <= 3.0 else "missed", dd


def table(M, cfg, log=print):
    tol, lab = load_labels()
    songs, missing = find_songs(M, cfg, list(lab))
    rows = []
    for f, tl in lab.items():
        if f not in songs:
            continue
        s = songs[f]
        drops, main, m = map_drops(M, s)
        for t in tl:
            if isinstance(t, dict):
                cands = [t["t"]] + list(t.get("alt", []))
                t0 = min(cands, key=lambda c: min([abs(c - d) for d in drops] or [999]))
                note = f"ambiguous, reading {t0:.0f}s used" if len(cands) > 1 else ""
            else:
                t0, note = float(t), ""
            st, dd = classify(t0, drops, tol)
            rows.append({"snaps": (m.get("v2") or {}).get("drop_snap", []), "song": f, "title": s["title"], "label": t0, "status": st, "dist": dd, "note": note, "drops": [round(d, 1) for d in drops]})
    return rows, missing, songs


def print_table(rows, missing, log=print):
    shown = set()
    for r in rows:
        if r["song"] not in shown:
            shown.add(r["song"])
            for sn in r.get("snaps", []):
                log(f"  snap {r['song'][:22]}: {sn['from']:.2f} -> {sn['to']:.2f} ({sn['delta_s']:+.2f} s){' [early drop]' if sn.get('early') else ''}")
    for r in rows:
        log(f"{r['song'][:24]:24} label {int(r['label'] // 60)}:{r['label'] % 60:04.1f}  {r['status']:6} " + (f"{r['dist']:+.1f}s" if r['dist'] is not None else "  -  ")
            + f"  {r['note']}  drops={r['drops']}")
    hits = sum(r["status"] == "hit" for r in rows)
    log(f"HITS {hits} of {len(rows)}" + (f"; songs not found: {missing}" if missing else ""))
    return hits
