"""V7.1 report writer (never imported by the app): compare_out/report.md from compare_out/iter_last.json (19-song plan-level run) + auto-style flips V1 -> V2
(the existing `auto_style` on both maps, same rng seed, the material of the pinned takes)."""
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))


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
            except Exception as ex:
                flips[r["song"]] = (f"error {ex}", "")
    return flips


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
    L += ["", "## Per song", "", "| song | V1 median / p95 | V2 median / p95 | V1 BPM -> V2 BPM | drops V1 -> V2 | takes/events V1 -> V2 | auto style V1 -> V2 |", "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["song"]):
        a, b = r["v1"]["all"], r["v2"]["all"]
        n1, n2 = flips.get(r["song"], ("?", "?"))
        L.append(f"| {r['song'][:34]} | {a['median_ms']} / {a['p95_ms']} | {b['median_ms']} / {b['p95_ms']} | {r.get('csv') or '-'}/V1 -> {r['map']['bpm']:.1f} | "
                 f"- -> {len(r['map']['drops'])} | {r['v1']['takes']}/{r['v1']['events']} -> {r['v2']['takes']}/{r['v2']['events']} | {n1} -> {n2}{' **FLIP**' if n1 != n2 else ''} |")
    imp = sum(r["v1"]["all"]["median_ms"] - r["v2"]["all"]["median_ms"] >= 15 for r in rows)
    worse = [r["song"] for r in rows if r["v2"]["all"]["median_ms"] > r["v1"]["all"]["median_ms"] + 5 or r["v2"]["all"]["p95_ms"] > r["v1"]["all"]["p95_ms"] + 5]
    L += ["", f"Improved by >= 15 ms (median): {imp}/{len(rows)}. Worse than V1 (median or p95, tolerance 5 ms): {len(worse)}: {', '.join(worse)}", ""]
    rj = HERE / "compare_out" / "renders.json"
    if rj.exists():
        L += ["## Side-by-side renders (E:\Movies\Montages\_songmap_test\)", ""]
        for x in json.loads(rj.read_text(encoding="utf-8")):
            L.append(f"- `{Path(x['file']).name}`: {x['summary']}")
    (HERE / "compare_out" / "report.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:6]), "...", f"-> compare_out/report.md ({len(rows)} songs)")
    print("style flips:", {k: v for k, v in flips.items() if v[0] != v[1]})


if __name__ == "__main__":
    main()
