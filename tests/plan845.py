"""V8.4.5 tool: build ONE plan exactly like the GUI job (game, seed, song fragment, effects mode) and save it as JSON; prints the take table.
python tests/plan845.py <game> <extra|default> <out.json> --seed N --song "<fragment>"
The plan is made with make_plan (auto pick of style when none is given), so the same seed + song + clips give the same plan as the GUI."""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
import montage as M                                                                           # noqa: E402


def unuse(title):
    """Pretend the clips a given montage used (used_titles.json title) are unused again: the plan of that job can then be rebuilt (the job marks its clips used when it finishes)."""
    titles = M.load_json(M.USED_TITLES, {})
    drop = {k for k, v in titles.items() if v.get("title") == title}
    keep = M.used_dates
    M.used_dates = lambda: {k: v for k, v in keep().items() if k not in drop}
    return len(drop)


def build(game, effects, seed, song, cfg=None, unuse_title=None):
    if unuse_title:
        unuse(unuse_title)
    cfg = cfg or M.load_config()
    cfg["effects_game"] = dict(cfg.get("effects_game") or {}, **{game: effects})
    sp = None                                                      # no --song = the planner's own auto pick (what the GUI job does)
    if song:
        songs, _, _ = M.song_pool(cfg, cached_only=True)
        sp = [s for s in songs if song.lower() in (s["title"] + " " + s["artist"] + " " + Path(s["path"]).name).lower()][0]["path"]
    plan, text = M.make_plan(cfg, game, None, sp, None, None, seed, None, None)
    return plan, text, cfg


def table(plan):
    rows = []
    for i, t in enumerate(plan["takes"]):
        name = Path(t["path"]).name
        rows.append(f"{i + 1:2d} {t['out_start']:6.2f}+{t['dur']:5.2f}s {t.get('role', ''):9s} srcs {len(t.get('srcs') or [1])} ramp {t.get('ramp')} "
                    f"speeds {sorted({round(s[2], 2) for s in t['segs']})} xfx {sorted({x['k'] for x in t.get('xfx', [])})} {name}")
    return "\n".join(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("effects")
    ap.add_argument("out")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--song")
    ap.add_argument("--unuse", help="used_titles.json title whose clips count as unused again")
    a = ap.parse_args()
    plan, text, cfg = build(a.game, a.effects, a.seed, a.song, unuse_title=a.unuse)
    Path(a.out).write_text(json.dumps(plan, default=str), encoding="utf-8")
    print(f"{len(plan['takes'])} takes, {plan['duration']:.2f} s, recipe {plan.get('recipe')}, effects {plan.get('effects')}")
    print(table(plan))
    for n in plan.get("notes", []):
        if str(n).startswith("EFFECT PLAN"):
            print(n)
