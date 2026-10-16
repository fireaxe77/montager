"""V8.6.2 tool: how much footage exists after the kill of every CS2 headline / ending candidate, and in how many of them is a knife-out visible?
python tests/knife862.py [candidates = 250] [out.txt]
Candidates = the CS2 kill events (build_events on the whole scanned library) with the highest scores (the headline and ending are always taken from the top of this list). For each: `post` = seconds of source footage
after its last kill (up to my death), and the knife-out measured by cs2_knife_out (the weapon HUD's ammo counter gone for 0.3 s after the kill); `ok` = the knife is seen and the footage after it covers the second slow-down."""
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

n = int(sys.argv[1]) if len(sys.argv) > 1 else 250
cfg = M.load_config()
M.QUIET.on = True
pool, st = M.game_pool(cfg, "cs2")
events, _notes = M.build_events(pool, "cs2", cfg, random.Random(1))
M.QUIET.on = False
events = sorted(events, key=lambda e: -e["score"])[:n]
t0 = time.time()
rows, buckets, seen, ok = [], {"< 0.6 s": 0, "0.6 - 1.1 s": 0, "1.1 - 2 s": 0, "2 - 3.5 s": 0, ">= 3.5 s": 0}, 0, 0
by_post_knife = {k: 0 for k in buckets}
reasons = {}
for e in events:
    kn = M.cs2_event_knife(e, cfg)
    post = float(kn["post"] if kn["post"] is not None else e["post"])
    b = "< 0.6 s" if post < 0.6 else "0.6 - 1.1 s" if post < 1.1 else "1.1 - 2 s" if post < 2.0 else "2 - 3.5 s" if post < 3.5 else ">= 3.5 s"
    buckets[b] += 1
    if kn["hud_t"] is not None:
        seen += 1
        by_post_knife[b] += 1
    if kn["ok"]:
        ok += 1
    else:
        key = kn["why"].split(" (")[0][:70] if kn["hud_t"] is None else "knife seen, not enough footage after it"
        reasons[key] = reasons.get(key, 0) + 1
    rows.append((e["score"], post, kn, Path(e["path"]).name))
txt = [f"{len(events)} top-scoring CS2 events of {len(pool)} clips ({time.time() - t0:.0f} s)",
       "footage after the last kill (source seconds):"]
for k in buckets:
    txt.append(f"   {k:12s}: {buckets[k]:4d} events, knife-out seen in {by_post_knife[k]}")
txt += [f"knife-out visible in {seen} of {len(events)} events; knife seen AND enough footage after it for the second slow-down (ok): {ok}",
        "why the others have no knife slow-down: " + "; ".join(f"{k}: {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])),
        "", "the 25 best-scored events:"]
for sc, post, kn, nm in rows[:25]:
    txt.append(f"   score {sc:5.1f}  footage after the kill {post:4.2f} s  knife-out " + (f"at +{kn['hud_t']:.2f} s" if kn["hud_t"] is not None else "not seen") + f"  ok={kn['ok']}  {nm}")
out = "\n".join(txt)
print(out)
if len(sys.argv) > 2:
    Path(sys.argv[2]).write_text(out + "\n", encoding="utf-8", errors="replace")
