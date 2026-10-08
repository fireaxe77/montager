"""V7.1 report writer (never imported by the app): compare_out/report.md from compare_out/iter_last.json (19-song plan-level run) + auto-style flips V1 -> V2
(the existing `auto_style` on both maps, same rng seed, the material of the pinned takes)."""
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


SAFE = {}


def style_flips(rows):
    import montage as M
    from songmap_v2 import planbench as PB
    flips = {}
    with PB.data_copy(M):
        pool = {str(s["path"]).replace("\\", "/"): s for s in M.song_pool(M.load_config(), cached_only=True)[0]}
        evs = [{"n": 1}] * 6 + [{"n": 2}] * 3
        for r in rows:
            p = r["path"]
            song = pool.get(p.replace("\\", "/"), {})
            csv = r.get("csv")
            try:
                a1 = M.get_songmap(p, csv, version="v1")
                a2 = M.get_songmap(p, csv, version="v2")
                n1, w1 = M.auto_style(a1, song, random.Random(1), evs)
                n2, w2 = M.auto_style(a2, song, random.Random(1), evs)
                flips[r["song"]] = (n1, n2)
                SAFE[r["song"]] = (a2.get("beat_source") == "v1", (a2.get("v2") or {}).get("fallback_reason"))
            except Exception as ex:
                flips[r["song"]] = (f"error {ex}", "")
    return flips


def drophit_table(rows):
    """DROP-HIT: the headline multikill of the pinned 7 real Valorant clips (val7) against the independently found main drop; hit = first kill within 1 beat."""
    L = ["## Drop hit (headline multikill vs the independently detected main drop; hit = first kill within 1 beat)", "",
         "| song | independent drop (conf) | V1 first / last kill (beats) | V1 hit | V2 first / last kill (beats) | V2 hit | planner drop_t V1 / V2 | section start V1 / V2 |", "|---|---|---|---|---|---|---|---|"]
    clear = [r for r in rows if r.get("indep_drop", {}).get("clear")]
    v1h = v2h = both = worse = 0
    for r in sorted(rows, key=lambda r: r["song"]):
        d = r.get("indep_drop") or {}
        a = (r["v1"]["sets"].get("val7") or {})
        b = (r["v2"]["sets"].get("val7") or {})
        da, db = a.get("drophit"), b.get("drophit")
        if not d.get("clear") or not da or not db:
            L.append(f"| {r['song'][:30]} | no clear drop | - | - | - | - | - | - |")
            continue
        v1h += da["hit"]
        v2h += db["hit"]
        both += (not da["hit"]) or db["hit"]
        worse += abs(db["first_beats"]) > abs(da["first_beats"]) + 1
        ha, hb = a["headline"], b["headline"]
        L.append(f"| {r['song'][:30]} | {d['t']} s ({d['conf']}) | {da['first_beats']:+.1f} / {da['last_beats']:+.1f} | {'yes' if da['hit'] else 'no'} | {db['first_beats']:+.1f} / {db['last_beats']:+.1f} | "
                 f"{'yes' if db['hit'] else 'no'} | {ha['plan_drop_t']} / {hb['plan_drop_t']} | {ha['section_start']} / {hb['section_start']} |")
    n = len(clear)
    ok1 = both == sum(1 for r in clear if (r["v1"]["sets"].get("val7") or {}).get("drophit")) if n else True
    r2 = (v2h / n >= 0.7) if n else True
    L += ["", f"Songs with a clear drop: {n}/{len(rows)}. V1 hits {v1h}, V2 hits {v2h}.",
          f"- Rule 1 (V2 hits wherever V1 does): {'PASS' if ok1 else 'FAIL'}",
          f"- Rule 2 (V2 hits >= 70% of the clear-drop songs): {'PASS' if r2 else 'FAIL'} ({v2h}/{n})",
          f"- Rule 3 (no song where V2 is worse than V1 by more than 1 beat): {'PASS' if worse == 0 else 'FAIL'} ({worse} songs)", ""]
    return L


def main():
    rows = json.loads((HERE / "compare_out" / "iter_last.json").read_text(encoding="utf-8"))
    flips = style_flips(rows)
    L = ["# Song map V1 vs V2 - plan-level (V7.1)", "",
         "Kills = first kill of every take + last kill of every multikill (pinned takes: 7 real Valorant clips, CS2 trio, ~15 CS2 singles; same seed / song, existing dry planner), "
         "distance to the nearest independent low-band kick (ms). Lower is better.", "", "## Listen to these first (largest difference)", ""]
    srt = sorted(rows, key=lambda r: -abs(r["v1"]["all"]["median_ms"] - r["v2"]["all"]["median_ms"]))
    for r in srt[:6]:
        a, b = r["v1"]["all"], r["v2"]["all"]
        L.append(f"1. **{r['song']}** - median {a['median_ms']} -> {b['median_ms']} ms: `python montage.py songmapcheck \"{r['song'][:24]}\"`")
    L += ["", "## Per song", "", "| song | V1 median / p95 | V2 median / p95 | V1 BPM -> V2 BPM | drops V1 -> V2 | takes/events V1 -> V2 | auto style V1 -> V2 | V1 beat values (safety) |", "|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["song"]):
        a, b = r["v1"]["all"], r["v2"]["all"]
        n1, n2 = flips.get(r["song"], ("?", "?"))
        L.append(f"| {r['song'][:34]} | {a['median_ms']} / {a['p95_ms']} | {b['median_ms']} / {b['p95_ms']} | {r.get('csv') or '-'}/V1 -> {r['map']['bpm']:.1f} | "
                 f"- -> {len(r['map']['drops'])} | {r['v1']['takes']}/{r['v1']['events']} -> {r['v2']['takes']}/{r['v2']['events']} | {n1} -> {n2}{' **FLIP**' if n1 != n2 else ''} | {'YES: ' + str(SAFE.get(r['song'], (0, ''))[1])[:60] if SAFE.get(r['song'], (0,))[0] else 'no'} |")
    imp = sum(r["v1"]["all"]["median_ms"] - r["v2"]["all"]["median_ms"] >= 15 for r in rows)
    worse = [r["song"] for r in rows if r["v2"]["all"]["median_ms"] > r["v1"]["all"]["median_ms"] + 5 or r["v2"]["all"]["p95_ms"] > r["v1"]["all"]["p95_ms"] + 5]
    L += ["", f"Improved by >= 15 ms (median): {imp}/{len(rows)}. Worse than V1 (median or p95, tolerance 5 ms): {len(worse)}: {', '.join(worse)}", ""]
    L += drophit_table(rows)
    rj = HERE / "compare_out" / "renders.json"
    if rj.exists():
        L += ["## Side-by-side renders (E:\Movies\Montages\_songmap_test\)", ""]
        for x in json.loads(rj.read_text(encoding="utf-8")):
            L.append(f"- `{Path(x['file']).name}`: {x['summary']}")
    (HERE / "compare_out" / "report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:6]), "...", f"-> compare_out/report.md ({len(rows)} songs)")
    print("safety:", [k for k, v in SAFE.items() if v[0]])
    print("style flips:", {k: v for k, v in flips.items() if v[0] != v[1]})


if __name__ == "__main__":
    main()
