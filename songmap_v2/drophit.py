"""V7.2 DROP-HIT metric (benchmark only, never imported by the app). The song's MAIN DROP is found INDEPENDENTLY of both song maps, on the render-timebase audio:
the strongest sustained loudness rise (mean of the next ~14 s, about 8 bars, minus the previous ~14 s, in dB) that coincides with the kick returning (kicks per
second after vs before, from bench.indep_kicks). A song without a rise of at least RISE_MIN_DB with a returning kick is 'no clear drop' and excluded. Then the
headline multikill of a plan (the take the planner places on the drop) is measured: distance of its first and of its last kill to that drop, in ms and in beats."""
import numpy as np

HOP_S = 0.5
WIN_S = 14.0
RISE_MIN_DB = 3.0
KICK_AFTER_MIN = 0.8              # kicks / s in the 10 s after the drop
KICK_RATIO_MAX = 0.65             # kicks / s before the drop must be below this share of those after (the kick RETURNS)


def loudness_db(y, sr):
    n = int(HOP_S * sr)
    m = len(y) // n
    x = np.asarray(y[:m * n], np.float64).reshape(m, n)
    return 10 * np.log10((x ** 2).mean(1) + 1e-10)


def independent_drop(y, sr, kick_t):
    """{"t", "rise_db", "kick_after", "kick_before", "conf", "clear"} (t = time of the first kick of the returned kick pattern)."""
    L = loudness_db(y, sr)
    k = int(WIN_S / HOP_S)
    kt = np.sort(np.asarray(kick_t, float))
    best = None
    for i in range(k, len(L) - k):
        rise = float(L[i:i + k].mean() - L[i - k:i].mean())
        if rise < RISE_MIN_DB * 0.5:
            continue
        t = i * HOP_S
        after = float(np.sum((kt >= t) & (kt < t + 10.0))) / 10.0
        before = float(np.sum((kt >= t - 10.0) & (kt < t))) / 10.0
        if after < KICK_AFTER_MIN or before > KICK_RATIO_MAX * after:
            continue
        score = rise * (1.0 - before / max(after, 1e-9))
        if best is None or score > best[0]:
            best = (score, t, rise, after, before)
    if best is None:
        return {"clear": False, "t": None, "conf": 0.0}
    score, t, rise, after, before = best
    first = kt[(kt >= t - 2.0) & (kt <= t + 4.0)]
    t_kick = float(first[0]) if len(first) else t
    conf = float(np.clip(score / 8.0, 0.0, 1.0))
    return {"clear": bool(rise >= RISE_MIN_DB and conf >= 0.3), "t": round(t_kick, 2), "rise_db": round(rise, 1), "kick_after": round(after, 2),
            "kick_before": round(before, 2), "conf": round(conf, 2)}


def headline(plan):
    """First / last kill (song time) of the headline multikill of a plan, the beat length (s) and what the planner read as the drop."""
    tk = next((t for t in plan["takes"] if t.get("role") == "headline"), None) or max(plan["takes"], key=lambda t: int(t["n"]))
    s0 = float(plan["song"]["start_t"]) + float(tk["out_start"])
    ks = tk["kills_out"]
    beat = 60.0 / float(plan["song"].get("bpm") or 120.0)
    return {"first": round(s0 + float(ks[0]), 3), "last": round(s0 + float(ks[-1]), 3), "n": int(tk["n"]), "beat_s": round(beat, 4),
            "plan_drop_t": plan["song"].get("drop_t"), "section_start": round(float(plan["song"]["start_t"]), 2)}


def distances(hl, drop_t):
    if drop_t is None or hl is None:
        return None
    b = hl["beat_s"]
    f, l = hl["first"] - drop_t, hl["last"] - drop_t
    return {"first_ms": round(f * 1000), "last_ms": round(l * 1000), "first_beats": round(f / b, 2), "last_beats": round(l / b, 2),
            "hit": bool(abs(f) / b <= 1.0)}
