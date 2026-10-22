"""V8.8.3 check (real data, plans only, no render): every game x every planning mode with one song; each plan must start inside the song's audible part and end within 3 s of its trimmed end
and start within 3 s of its trimmed start (when the trimmed song fits the maximum length). Modes: auto (Auto / Force new / dry plan / render: make_plan without ticked clips), force_full (Force Full / Force New Full: full=True),
manual (ticked clips, Optimal), manual_auto (ticked clips, full=True). Run on a COPY of montage_data (MONTAGER_DATA=<copy>): plans write caches.
python tests/fill883.py [song fragment = Perfect Exceeder] [games = valorant,cs2,r6s] [modes = auto,force_full,manual,manual_auto] [seed = 4242]"""
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

frag = sys.argv[1] if len(sys.argv) > 1 else "Perfect Exceeder"
games = (sys.argv[2] if len(sys.argv) > 2 else "valorant,cs2,r6s").split(",")
modes = (sys.argv[3] if len(sys.argv) > 3 else "auto,force_full,manual,manual_auto").split(",")
seed = int(sys.argv[4]) if len(sys.argv) > 4 else 4242
cfg = M.load_config()
songs, _, _ = M.song_pool(cfg, cached_only=True)
song = [s for s in songs if frag.lower() in (s["title"] + " " + s["artist"] + " " + Path(s["path"]).name).lower()][0]
an = M.get_songmap(song["path"], song.get("csv_bpm"))
lv0, lv1 = M.song_live_range(an)
print(f"song '{song['title']}': {an['dur']:.2f} s, audible {lv0:.2f} - {lv1:.2f} s")
res = []
for g in games:
    pool, _st = M.game_pool(cfg, g)
    ticked = [it["rec"]["path"] for it in pool if it.get("kills")]
    random.Random(seed).shuffle(ticked)
    ticked = ticked[:8]                                    # a hand pick of 8 clips: far too few for the whole song, the fill must add more
    for mode in modes:
        kw = {"auto": dict(), "force_full": dict(full=True), "manual": dict(paths=ticked), "manual_auto": dict(paths=ticked, full=True)}[mode]
        t0 = time.time()
        M.QUIET.on = True
        try:
            plan, text = M.make_plan(cfg, g, song_path=song["path"], target="optimal", style="auto", seed=seed, scan=False, **kw)
        except Exception as ex:                            # noqa: BLE001
            M.QUIET.on = False
            res.append((g, mode, False, f"plan failed: {type(ex).__name__}: {ex}"))
            print(res[-1])
            continue
        M.QUIET.on = False
        st = float(plan["song"]["start_t"])
        end = st + float(plan["duration"])
        s0 = max(lv0, float(an["beats"][0]))
        ok = st >= lv0 - 0.05 and st - s0 <= 3.0 and end <= lv1 + 0.05 and lv1 - end <= 3.0
        fills = [ln.strip()[:160] for ln in text.splitlines() if "song fill" in ln or "song filled" in ln or "short at the end" in ln]
        res.append((g, mode, ok, f"song {st:.2f} - {end:.2f} s (trimmed start {s0:.2f}: {st - s0:+.2f} s, trimmed end {lv1:.2f}: {lv1 - end:+.2f} s), {len(plan['takes'])} takes, {time.time() - t0:.0f} s; " + " | ".join(fills[:3])))
        print(("ok   " if ok else "FAIL ") + f"{g} {mode}: {res[-1][3]}")
bad = [r for r in res if not r[2]]
print(f"\n{len(res) - len(bad)} of {len(res)} ok" + ("" if not bad else "; FAILED: " + ", ".join(f"{g} {m}" for g, m, _o, _w in bad)))
sys.exit(1 if bad else 0)
