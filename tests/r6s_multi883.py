"""V8.8.3 check (R6S, no rescans, detection untouched): do montage takes cut off multikills?
For every R6S clip with cached kills: the kills detection found (analyse_clip_entry), the rows it rejected, the kills that survive the audio / death rules (game_pool), the events build_events makes
(kills of neighbouring companion clips joined), and whether the planner can form a take that holds every kill of each event (place + the relaxation ladder, on a real song's beat grid).
A detected fight = detected kills of one clip (or of clips joined into one event) no more than FIGHT_S apart. Listed:
  A  a fight whose kills land in more than one event (split across takes)
  B  a fight with a detected kill that is in no event (and why: rejected row / death rule / outside the footage / duplicate of another clip's row)
  C  an event with 2+ kills that cannot form a take (why_no_take) -> the planner leaves the whole fight out
  D  clips with 2+ detected kills whose best event uses only 1 kill (and why)
Then N real dry plans (Auto, R6S) are checked take by take: every take holds all kills of its event, the last kill row is readable before the take ends, and no fight is split across takes.
Run on a COPY of montage_data (MONTAGER_DATA=<copy>).   python tests/r6s_multi883.py [song fragment = Perfect Exceeder] [dry plans = 3] [out.txt]"""
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
import numpy as np                                                                            # noqa: E402

FIGHT_S = 10.0
frag = sys.argv[1] if len(sys.argv) > 1 else "Perfect Exceeder"
n_plans = int(sys.argv[2]) if len(sys.argv) > 2 else 3
outp = sys.argv[3] if len(sys.argv) > 3 else None
cfg = M.load_config()
det = M.load_dets("r6s").get("r6s")
cache = M.load_kills_cache()
rep = []
P = lambda *a: (print(*a), rep.append(" ".join(str(x) for x in a)))
nm = lambda p: Path(p).name
mmss = lambda t: f"{int(t // 60)}:{t % 60:04.1f}"

# 1) detection as it stands (cached; nothing is rescanned)
detected, rejected = {}, {}
for r in M.scan_clips(cfg):
    if r.get("game") != "r6s" or r.get("error") or not r.get("w"):
        continue
    e = cache.get(M.kills_key(r, "r6s", det))
    if not e or e.get("error"):
        continue
    a = M.analyse_clip_entry(r, e, cfg, "r6s")
    detected[r["path"]] = sorted(float(k["t"]) for k in a["kills"])
    rejected[r["path"]] = [(float(j.get("t", -1)), j["reason"]) for j in a["rej"]]
M.QUIET.on = True
pool, st = M.game_pool(cfg, "r6s")
events, _notes = M.build_events(pool, "r6s", cfg, random.Random(1))
M.QUIET.on = False
led = M.LAST_LEDGER[0]
in_pool = {it["rec"]["path"]: sorted(float(k["t"]) for k in it["kills"]) for it in pool}
pool_rej = {it["rec"]["path"]: [(float(j.get("t", -1)), j["reason"]) for j in it.get("rej", [])] for it in pool}
row_ev = {}
for i_, ev in enumerate(events):
    for rid in (led.events.get(led.evkey(ev)) or []):
        row_ev.setdefault(rid, set()).add(i_)
rows_by = {}
for row in led.rows:
    rows_by.setdefault(row["path"], []).append(row)


def why_missing(path, t):
    for t_, why in pool_rej.get(path, []) + rejected.get(path, []):
        if abs(t_ - t) < 0.6:
            return why
    row = next((r_ for r_ in rows_by.get(path, []) if abs(r_["t"] - t) < 0.05), None)
    if row is None:
        return "dropped by the audio / death rules (not in the pool)"
    for k_ in ("unusable", "gone", "merged"):
        if row.get(k_):
            return f"{k_}: {row[k_]}" if k_ != "merged" else "the same kill row of another clip is used instead (duplicate)"
    return "in no event (reason not recorded)"


# 2) fights: detected kills of a clip, split on gaps over FIGHT_S; joined with the clips their event joins
A, B, C, D = [], [], [], []
n_fights = n_ok = 0
for path, ks in sorted(detected.items()):
    if len(ks) < 2:
        continue
    fights, cur = [], [ks[0]]
    for t in ks[1:]:
        if t - cur[-1] > FIGHT_S:
            fights.append(cur)
            cur = [t]
        else:
            cur.append(t)
    fights.append(cur)
    for f in fights:
        if len(f) < 2:
            continue
        n_fights += 1
        evs, miss = set(), []
        for t in f:
            row = next((r_ for r_ in rows_by.get(path, []) if abs(r_["t"] - t) < 0.05), None)
            ids = row_ev.get(row["id"], set()) if row else set()
            if not ids and row and row.get("merged"):
                ids = row_ev.get((row["merged"] or {}).get("into") if isinstance(row["merged"], dict) else -1, set())
            if not ids:
                miss.append((t, why_missing(path, t)))
            evs |= ids
        fine = True
        if len(evs) > 1:
            A.append(f"{nm(path)}: fight {', '.join(mmss(t) for t in f)} split into {len(evs)} events")
            fine = False
        if miss:
            B.append(f"{nm(path)}: fight {', '.join(mmss(t) for t in f)}: " + "; ".join(f"{mmss(t)} {w}" for t, w in miss))
            fine = False
        n_ok += fine
    best = max((len(events[i]["times"]) for r_ in rows_by.get(path, []) for i in row_ev.get(r_["id"], ())), default=0)
    if best == 1:
        why = sorted({why_missing(path, t) for t in ks if not any(abs(r_["t"] - t) < 0.05 and row_ev.get(r_["id"]) for r_ in rows_by.get(path, []))})
        D.append(f"{nm(path)}: {len(ks)} detected kills at {', '.join(mmss(t) for t in ks)}, best event 1 kill - " + ("; ".join(why) if why else f"kills more than {FIGHT_S:.0f} s apart (separate fights)"))

# 3) can each 2+ kill event form a take (the planner's own test, on a real beat grid)?
songs, _, _ = M.song_pool(cfg, cached_only=True)
song = [s for s in songs if frag.lower() in (s["title"] + " " + s["artist"] + " " + Path(s["path"]).name).lower()][0]
an = M.get_songmap(song["path"], song.get("csv_bpm"))
bt = np.array(an["beats"], float)
U, down, rp = M._ticks(bt), set(an["down"]), M.RECIPES["hype"]
for e in events:
    if e["n"] < 2:
        continue
    e["_allow"] = lambda t, _an=an: M.gap_allowance(_an, "hype", t)
    ok_ = False
    for rx_ in M.RX_LADDER:
        e["_rx"] = dict(rx_)
        if M.place(e, U, down, rp, c=16):
            ok_ = True
            break
    if not ok_:
        e["_rx"] = {}
        C.append(f"{nm(e['path'])}: {e['n']} kills at {', '.join(mmss(t) for t in e['times'])}" + (" (+ " + ", ".join(nm(p_['path']) for p_ in e['parts'][1:]) + ")" if len(e.get("parts") or []) > 1 else "")
                 + f" - {M.why_no_take(e)}")

P(f"R6S library: {len(detected)} clips with cached kills, {sum(1 for v in detected.values() if len(v) >= 2)} with 2+ detected kills, {len(events)} events "
  f"({sum(1 for e in events if e['n'] >= 2)} multikill, {sum(1 for e in events if len(e.get('parts') or []) > 1)} joined across companion clips)")
P(f"fights with 2+ detected kills checked: {n_fights}, fine (all kills in one event): {n_ok}")
for title, lst in (("A  fight split across events", A), ("B  detected kill of a fight in no event", B), ("C  multikill event that cannot form a take", C), ("D  2+ kills detected, best event 1 kill", D)):
    P(f"\n{title}: {len(lst)}")
    for x in lst:
        P("   " + x)

# 4) real dry plans: every take holds every kill of its event, the last row is readable inside the take, no kill of a placed fight left out (the planner's own kill ledger)
P(f"\nDRY PLANS (Auto, R6S, song {song['title']}):")
for sd in range(n_plans):
    t0 = time.time()
    M.QUIET.on = True
    try:
        plan, _t = M.make_plan(cfg, "r6s", song_path=song["path"], target="optimal", style="auto", seed=1000 + sd, scan=False)
    except Exception as ex:                                # noqa: BLE001
        M.QUIET.on = False
        P(f"  seed {1000 + sd}: plan failed ({type(ex).__name__}: {ex})")
        continue
    M.QUIET.on = False
    bad, n_multi = [], 0
    for i, t in enumerate(plan["takes"]):
        if len(t["kills"]) >= 2:
            n_multi += 1
        if len(t["kills_out"]) != len(t["kills"]) or max(t["kills_out"]) > t["dur"]:
            bad.append(f"take {i + 1} {nm(t['path'])}: {len(t['kills'])} kills, {sum(1 for k_ in t['kills_out'] if k_ <= t['dur'])} inside the take")
        last_row = max(t.get("rows_out") or t["kills_out"])
        if last_row + M.ROW_TAIL - 0.02 > t["dur"]:
            bad.append(f"take {i + 1} {nm(t['path'])}: last kill row at {last_row:.2f} s, take ends at {t['dur']:.2f} s (row readable {t['dur'] - last_row:.2f} s)")
    led2 = M.LAST_LEDGER[0]                                # the planner's own record of every usable kill row: PLACED / MERGED_DUP / RANKED_OUT / CLIP_UNUSABLE / LOST
    by_clip = {}
    for r_ in (led2.rows if led2 else []):
        by_clip.setdefault(r_["path"], []).append(r_)
    for path, rs in by_clip.items():
        placed_t = [r_["t"] for r_ in rs if r_["state"] in ("PLACED", "OVERRIDE_ADMITTED")]
        if not placed_t:
            continue
        for r_ in rs:
            if r_["state"] not in ("PLACED", "OVERRIDE_ADMITTED", "MERGED_DUP") and any(abs(r_["t"] - pt) <= FIGHT_S for pt in placed_t):
                bad.append(f"{nm(path)}: kill {mmss(r_['t'])} of a placed fight not in the montage: {r_['state']} ({(r_.get('info') or {}).get('reason', '')})")
        for t_ in detected.get(path, []):                  # detected but never a usable row (rejected / death / audio rule) next to a placed kill
            if not any(abs(r_["t"] - t_) < 0.05 for r_ in rs) and any(abs(t_ - pt) <= FIGHT_S for pt in placed_t):
                bad.append(f"{nm(path)}: detected kill {mmss(t_)} of a placed fight never usable: {why_missing(path, t_)}")
    P(f"  seed {1000 + sd}: {len(plan['takes'])} takes ({n_multi} multikill), {time.time() - t0:.0f} s: " + ("every take holds all kills of its fight, rows readable" if not bad else f"{len(bad)} finding(s)"))
    for b_ in bad:
        P("     " + b_)
if outp:
    Path(outp).write_text("\n".join(rep) + "\n", encoding="utf-8")
