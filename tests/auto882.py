"""V8.8.2 tool: Manual Auto as the Auto button does it (auto_fill_pick + companions, then auto_fill_topup), for a game and a song; prints the planned length of the first pick and after the top-up,
and the render's own plan of the final selection (length, end against the song's audible end). Run on a COPY of montage_data (MONTAGER_DATA=<copy>).
python tests/auto882.py <game> <song fragment> [seed = 4242] [style = auto]"""
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
style = sys.argv[4] if len(sys.argv) > 4 else "auto"
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
cands = M.cs2_dm_filter_cands(cfg, cands, game)
import os
if os.environ.get("AUTO_PICK_X"):
    M.AUTO_PICK_X = float(os.environ["AUTO_PICK_X"])          # e.g. 1.15 = the V8.8.1 pick
t0 = time.time()
paths, info = M.auto_fill_pick(cands, an, style, rng=random.Random(seed), game=game)
extra, _pl = M.random_companions(cfg, game, paths)
first = list(paths) + [e for e in extra if e not in paths]
M.QUIET.on = True
p1, _ = M.make_plan(cfg, game, first, song["path"], "optimal", style, seed, None, None, scan=False, full=True)
M.QUIET.on = False
notes = []
allp, top = M.auto_fill_topup(cfg, game, first, song["path"], an, style, seed, info, note=notes.append)
M.QUIET.on = True
plan, text = M.make_plan(cfg, game, allp, song["path"], "optimal", style, seed, None, None, scan=False, full=True)
M.QUIET.on = False
lv = M.song_live_range(an)
end_s = plan["song"]["start_t"] + plan["duration"]
print(f"{game} / '{song['title']}': song {an['dur']:.1f} s, audible {lv[0]:.2f} - {lv[1]:.2f} s; {len(cands)} candidates")
print(f"first pick: {len(first)} clips -> planned {p1['duration']:.1f} s (song {p1['song']['start_t']:.1f} - {p1['song']['start_t'] + p1['duration']:.1f} s)")
for n_ in notes:
    print("  " + n_)
print(f"after the top-up: {len(allp)} clips ({top['added']} added, {top['rounds']} rounds, {time.time() - t0:.0f} s) -> planned {plan['duration']:.1f} s of target {top['target']:.1f} s; "
      f"song {plan['song']['start_t']:.2f} - {end_s:.2f} s (audible end {lv[1]:.2f}: {'inside' if end_s <= lv[1] + 0.05 else 'PAST IT'}); {len(plan['takes'])} takes")
for ln in text.splitlines():
    if "song filled to the end" in ln or "short at the end" in ln:
        print("  " + ln.strip()[:300])
