"""V8.6.1 tool: Manual Auto (auto_fill_verified) for a game and a song, then the check the render would print: the same make_plan on the ticked clips (same seed, same song, Optimal + Force New Full cap) must
place EVERY ticked clip (no "didn't fit", no "could not be fitted", no NOT PLACED line).
python tests/auto861.py <game> <song fragment> [seed = 4242] [out.txt]"""
import random
import sys
import time
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
ROOT = _root.find_root()
sys.path.insert(0, str(ROOT))
warnings.simplefilter("ignore")
import montage as M                                                                           # noqa: E402

game, frag = sys.argv[1], sys.argv[2]
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 4242
cfg = M.load_config()
songs, _, _ = M.song_pool(cfg, cached_only=True)
song = [s for s in songs if frag.lower() in (s["title"] + " " + s["artist"] + " " + Path(s["path"]).name).lower()][0]
an = M.get_songmap(song["path"], song.get("csv_bpm"))
used = M.used_dates()
cands = []
if game == "r6s":
    for r in M.scan_clips(cfg):
        if r.get("game") == "r6s" and not r.get("error") and r.get("w"):
            cands.append({"path": r["path"], "ks": None, "kills": None, "used": used.get(M._pkey(r["path"]), "")})
else:
    pool, _st = M.game_pool(cfg, game)
    for it in pool:
        ks = sorted({round(float(k["t"]), 3) for k in it["kills"]}) if it.get("kills") else []
        if ks:
            cands.append({"path": it["rec"]["path"], "ks": ks, "kills": ks, "used": used.get(M._pkey(it["rec"]["path"]), "")})
random.seed(seed)
t0 = time.time()
M.QUIET.on = True
paths, info = M.auto_fill_verified(cfg, game, cands, song["path"], an, "auto", seed, rng=random.Random(seed))
M.QUIET.on = False
rep = [f"{game} / '{song['title']}' ({info['target']:.0f} s target): {len(cands)} candidate clips -> {len(paths)} ticked, planned {info['length']:.0f} s, {info['rounds']} rounds, {info['dropped']} unplaceable dropped, {info['added']} added, {time.time() - t0:.0f} s"]
M.QUIET.on = True
plan, text = M.make_plan(cfg, game, paths, song["path"], "optimal", "auto", seed, None, None, scan=(game == "r6s"), full=True)
M.QUIET.on = False
summ = M.plan_summary_text(plan, len(paths))
bad = [ln for ln in (text + "\n" + summ).splitlines() if "didn't fit" in ln or "could not be fitted" in ln or "NOT PLACED" in ln or "didn't fit" in ln]
placed = M.plan_placed_paths(plan)
rep.append(f"the render's own plan of that selection: {plan['duration']:.0f} s, {len(plan['takes'])} takes, {len(paths)} ticked / {len([p for p in paths if p in placed])} placed; summary: {summ[:200]}")
rep.append("lines the render would print about clips that do not fit: " + (str(len(bad)) + "\n   " + "\n   ".join(b[:200] for b in bad[:10]) if bad else "none"))
out = "\n".join(rep)
print(out)
if len(sys.argv) > 4:
    Path(sys.argv[4]).write_text(out + "\n", encoding="utf-8")
