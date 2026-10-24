"""V9.0 real Manual renders: the same ticked Valorant clips with the intro text typed and the tickbox ON, and with the tickbox OFF (no intro at all).
    python tests\\render90_manual.py <out_dir> [plan.json]      (MONTAGER_DATA = a COPY of montage_data; the clips are the first takes' clips of a saved plan)
Writes <out_dir>\\manual_intro_on.mp4 and manual_intro_off.mp4 (+ the plan texts) and prints the plan lines about the intro."""
import json
import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _root import find_root  # noqa: E402

ROOT = find_root(__file__)
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")
import montage as m  # noqa: E402


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    pj = Path(sys.argv[2]) if len(sys.argv) > 2 else next(iter(sorted((m.DATA / "plans").glob("Valorant_*.dry.json"), key=lambda p: p.stat().st_mtime, reverse=True)))
    plan = json.loads(pj.read_text(encoding="utf-8"))
    paths, seen = [], set()
    for t in plan["takes"]:
        for s in t["srcs"]:
            if s["path"] not in seen and len(paths) < 8:
                seen.add(s["path"])
                paths.append(s["path"])
    print("ticked clips:", len(paths))
    for name, on in (("manual_intro_on", True), ("manual_intro_off", False)):
        f = m.run_job("valorant", mode="render", force=True, paths=list(paths), target="optimal", style="hype", seed=4242, outfile=out / (name + ".mp4"),
                      intro=on, intro_text=("MY CUSTOM TITLE" if on else ""))
        print(name, "->", f)
        pl = m.LAST_PLAN.get("valorant")
        if pl:
            print("  intro in plan:", bool(pl.get("intro")), (pl.get("intro") or {}).get("title"), "| subline:", (pl.get("intro") or {}).get("subline"), "| duration", pl["duration"])


if __name__ == "__main__":
    main()
