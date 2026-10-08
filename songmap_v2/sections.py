"""STAGE 3 - sections / drops. Bar-resolution features judged against the song's own range; a DROP has to be a sustained, bar-aligned jump in
energy AND low-band / onset activity after a build or breakdown (or a hard opening) and must persist; short bumps are labelled "bump"."""
import numpy as np

DROP_MIN_BARS = 8                   # persistence (bars) ...
DROP_MIN_S = 12.0                   # ... or seconds, whichever is longer
DROP_JUMP = 0.22                    # sustained rise of the combined bar score vs the 4 bars before
DROP_LEVEL = 0.5                    # and a high absolute level (0-1, per-song normalised)
DROP_HOLD = 0.8                     # share of the persistence window that must stay above the half-way level
SHARE_CAP = 0.45                    # at most this share of the song may be labelled drop
MIN_RANGE = {"loud": 6.0, "low": 6.0, "act": 1.0}      # a flat song's noise is never stretched to a full 0-1 range
BUMP_RISE = 0.25
EARLY_S = 48.0                      # V7.4: drops this early may come back after a SHORT break / build (no long build-up needed) ...
EARLY_M = 6                         # ... if the new level is sustained for this many bars (a short bump is not a drop)
EARLY_STEP = 0.3                    # immediate step: the new level minus the bar before
EARLY_DIP = 0.4                     # break type: new level minus the quietest bar of the 3 before
EARLY_LOW = 0.2                     # independent evidence: low-band step, or kick density step (EARLY_KICK), or a low-band break
EARLY_KICK = 0.4


def bar_table(beats, down, dur, y, sr, low, events, kick_t=None):
    """Bars between consecutive downbeats: start / end time, beat range and the raw features."""
    nb = len(beats)
    per = float(np.median(np.diff(beats))) if nb > 1 else 0.5
    starts = [int(d) for d in down]
    bars = []
    cs = np.concatenate([[0.0], np.cumsum(y.astype(np.float64) ** 2)])
    cl = np.concatenate([[0.0], np.cumsum(low.astype(np.float64) ** 2)])
    et = np.array([e["raw_time"] for e in events if e["type"] in ("kick", "bass", "snare", "accent")])
    es = np.array([e["strength"] for e in events if e["type"] in ("kick", "bass", "snare", "accent")])
    for k, a in enumerate(starts):
        b = starts[k + 1] if k + 1 < len(starts) else nb
        t0 = float(beats[a])
        t1 = float(beats[b]) if b < nb else min(dur, float(beats[-1]) + per)
        if t1 - t0 < 0.5 * (b - a) * per:
            continue
        i0, i1 = int(t0 * sr), max(int(t0 * sr) + 1, int(t1 * sr))
        i1 = min(i1, len(y))
        if i1 <= i0:
            continue
        # differences of running sums can come out slightly NEGATIVE on digital silence (float cancellation): clamp before the log
        rms = max(0.0, float((cs[i1] - cs[i0]) / (i1 - i0)))
        lw = max(0.0, float((cl[min(i1, len(cl) - 1)] - cl[i0]) / (i1 - i0)))
        m = (et >= t0) & (et < t1)
        ks_ = 0.0
        if kick_t is not None and len(kick_t):                       # V7.1: share of this bar's beats that carry a kick (a bar without kicks is a break)
            bi = np.arange(a, b)
            lo_ = beats[bi] - 0.5 * per
            hi_ = beats[bi] + 0.5 * per
            ks_ = float(np.mean(np.searchsorted(kick_t, hi_) - np.searchsorted(kick_t, lo_) > 0)) if len(bi) else 0.0
        bars.append({"kick": ks_, "beat0": a, "beat1": b, "t0": t0, "t1": t1, "loud": 10 * np.log10(rms + 1e-12), "low": 10 * np.log10(lw + 1e-12),
                     "act": float(es[m].sum() / (t1 - t0)) if len(es) else 0.0})
    return bars


def _norm(x, rng_min):
    x = np.nan_to_num(np.asarray(x, float), nan=-120.0, posinf=0.0, neginf=-120.0)       # never NaN into the change-point logic
    lo, hi = np.percentile(x, 5), np.percentile(x, 95)
    return np.clip((x - lo) / max(hi - lo, rng_min), 0, 1)


def kick_entry(kick_bar, bar, N):
    """The bar where the kick (re)enters around a loudness-detected drop: the first bar in [bar-1, bar+8] from which >= 4 bars (or the window) carry kicks,
    when the drop bar itself is kick-less. A drop bar that already has kicks stays."""
    n = len(kick_bar)
    if kick_bar[bar] >= 0.6 and float(kick_bar[bar:bar + 4].mean()) >= 0.6:
        return bar
    for j in range(max(0, bar - 1), min(n - 3, bar + 9)):
        if float(kick_bar[j:j + 4].min()) >= 0.35 and kick_bar[j] >= 0.6:
            return j
    return bar


PLAN_LEN_S = (20.0, 32.0)           # the montage lengths the continuity test covers (the planner fills ~20-30 s windows)
HEAD_S, TAIL_S = 17.0, 30.0         # seconds of song needed before / after the main drop so that the planner can fill its longest window (V7.2 takes parity)
ANCHOR_LEN_S = 26.0                 # the window length the anchor is computed for
PRE_FRAC = 0.38                     # the planner puts the main drop ~38 % into its window
GAP_BARS = 2                        # two bars in a row without kicks inside the window = a kick-less break


def window_kicky(kick_bar, bar, bar_s, lens=PLAN_LEN_S):
    """True when the windows the planner will fill around a drop at `bar` (drop ~38 % in, for each montage length) contain no kick-less break
    (>= GAP_BARS consecutive bars with almost no kicks) and start / end inside the song."""
    n = len(kick_bar)
    for L in lens:
        nb = max(4, int(round(L / max(bar_s, 0.5))))
        a = bar - int(round(PRE_FRAC * nb))
        b = a + nb
        a, b = max(0, a), min(n, b)
        if b - a < max(4, nb // 2):
            return False
        run = 0
        for k in range(a, b):
            run = run + 1 if kick_bar[k] < 0.35 else 0
            if run >= GAP_BARS:
                return False
    return True


def span_kicky(kick_bar, a, nb, gap=GAP_BARS):
    """bars [a, a+nb) carry a continuous kick grid: no GAP_BARS consecutive kick-less bars and at least 60 % of the bars with kicks."""
    n = len(kick_bar)
    if a < 0 or a + nb > n:
        return False
    w = kick_bar[a:a + nb]
    run = 0
    for v in w:
        run = run + 1 if v < 0.35 else 0
        if run >= gap:
            return False
    return float(np.mean(w >= 0.35)) >= 0.6


def relaxed_drop(S, kick_bar, bar_s, N):
    """Weak drop for songs with no sustained rise: the bar with the biggest local step of the bar score whose planner window is kicky."""
    n = len(S)
    best, bk = 0.12, None
    for i in range(2, n - 4):
        step = float(S[i:i + 4].mean() - S[max(0, i - 4):i].mean())
        if step > best and window_kicky(kick_bar, i, bar_s):
            best, bk = step, i
    if bk is None:
        return None
    return {"bar": bk, "jump": best, "bass_jump": 0.0, "post": float(S[bk:bk + N].mean()), "kicky": True, "strength": float(0.8 * best), "weak": True}


def early_candidates(bars, S, low, kick_bar, level_min):
    """V7.4: drops in the first EARLY_S seconds without the long build-up the normal rule wants. The kick / bass comes back after a short break or build:
    the bar score steps up (by EARLY_STEP vs the bar before, and either EARLY_DIP above the quietest of the 3 bars before or DROP_JUMP above the 4 before),
    stays up for EARLY_M bars (80 % of them above the half-way level) and independent evidence agrees: low-band energy step, kick-density step or a low-band break."""
    n = len(S)
    M = EARLY_M
    res = []
    for i in range(3, n - M + 1):
        if bars[i]["t0"] > EARLY_S:
            break
        win = S[i:i + M]
        post = float(win.mean())
        if post < level_min or post - float(S[i - 1]) < EARLY_STEP:
            continue
        pre = S[max(0, i - 4):i]
        base_dip = float(S[max(0, i - 3):i].min())
        jump = post - float(pre.mean())
        if not (post - base_dip >= EARLY_DIP or jump >= DROP_JUMP):
            continue
        base = float(pre.mean()) if jump >= DROP_JUMP else base_dip
        if float(np.mean(win >= base + 0.5 * (post - base))) < DROP_HOLD:
            continue
        lw = float(low[i:i + M].mean())
        lstep = lw - float(low[max(0, i - 4):i].mean())
        kstep = float(kick_bar[i:i + M].mean()) - float(kick_bar[max(0, i - 4):i].mean())
        lbreak = float(low[max(0, i - 3):i].min()) <= 0.35 * lw
        if not (lstep >= EARLY_LOW or kstep >= EARLY_KICK or lbreak):
            continue
        res.append({"bar": i, "jump": max(jump, post - base_dip), "post": post, "bass_jump": lstep, "early": True})
    keep = []
    for c in sorted(res, key=lambda c: -(c["jump"] + c["post"])):       # one per neighbourhood: the strongest step
        if all(abs(c["bar"] - k["bar"]) > 3 for k in keep):
            keep.append(c)
    return keep


SOFT_PRE_BARS, SOFT_POST_BARS = 4, 6        # V7.4.5 soft drops: >= 4 kick-less bars, then the kick is back for 6 bars
SOFT_JUMP = 0.12                            # small loudness rise allowed (chill / gradual songs)


def soft_candidates(S, low, kick_bar, level_min):
    """V7.4.5: a gradual drop - the kick comes back after a kick-less stretch and the bass / spectral weight stays up for SOFT_POST_BARS bars, even though
    the loudness only rises a little. Short bumps (not sustained) and loud-all-through songs (no kick-less stretch) never qualify."""
    n = len(S)
    res = []
    for i in range(SOFT_PRE_BARS, n - SOFT_POST_BARS + 1):
        pre_k = float(kick_bar[i - SOFT_PRE_BARS:i].mean())
        post_k = float(kick_bar[i:i + SOFT_POST_BARS].mean())
        if pre_k > 0.2 or post_k < 0.55:
            continue
        post = float(S[i:i + SOFT_POST_BARS].mean())
        pre = float(S[i - SOFT_PRE_BARS:i].mean())
        if post < max(0.6 * level_min, 0.45) or post - pre < SOFT_JUMP:
            continue
        if float(np.mean(S[i:i + SOFT_POST_BARS] >= pre + 0.5 * (post - pre))) < DROP_HOLD:
            continue
        lstep = float(low[i:i + SOFT_POST_BARS].mean() - low[i - SOFT_PRE_BARS:i].mean())
        if lstep < 0.1:
            continue
        res.append({"bar": i, "jump": post - pre, "post": post, "bass_jump": lstep, "early": False, "soft": True})
    keep = []
    for c in sorted(res, key=lambda c: -(c["jump"] + c["post"])):
        if all(abs(c["bar"] - k["bar"]) > 3 for k in keep):
            keep.append(c)
    return keep


LATER_DIP = 0.35                    # V7.4.8 later drops: the quietest of the 3 bars before is at least this far under the new level (a real breakdown) ...
LATER_KICK = 0.35                   # ... and the kick is (almost) gone in it
LATER_POST = 0.75                   # ... and comes back for at least this share of the next 6 bars


def later_candidates(bars, S, low, kick_bar, level_min):
    """V7.4.8: a LATER drop after a quiet stretch / breakdown in a song that already has a drop (the caller checks that): the level steps back up and stays up
    for EARLY_M bars, the kick returns (kick-less bar before, kicks in the bars after) and the low band steps up. Added with lower confidence, never moves
    or removes an existing drop, never inside the first EARLY_S seconds (V7.4.5 rules cover those)."""
    n = len(S)
    M_ = EARLY_M
    res = []
    for i in range(3, n - M_ + 1):
        if bars[i]["t0"] <= EARLY_S:
            continue
        win = S[i:i + M_]
        post = float(win.mean())
        pre3 = S[i - 3:i]
        if post < level_min or post - float(S[i - 1]) < EARLY_STEP or float(pre3.min()) > post - LATER_DIP:
            continue
        if float(kick_bar[i - 3:i].min()) > LATER_KICK or float(kick_bar[i:i + M_].mean()) < LATER_POST:
            continue
        base = float(pre3.min())
        if float(np.mean(win >= base + 0.5 * (post - base))) < DROP_HOLD:
            continue
        if float(low[i:i + M_].mean() - low[i - 3:i].min()) < EARLY_LOW:
            continue
        res.append({"bar": i, "jump": post - base, "post": post, "bass_jump": float(low[i:i + M_].mean() - low[i - 3:i].min()), "early": False, "later": True})
    keep = []
    for c in sorted(res, key=lambda c: -(c["jump"] + c["post"])):
        if all(abs(c["bar"] - k["bar"]) > 3 for k in keep):
            keep.append(c)
    return keep


def analyse(bars, bar_s):
    """Returns {"S","drops","labels","share"}; drops = [{"bar","t","strength","jump","bass_jump"}] (V1 field names)."""
    n = len(bars)
    for b in bars:
        for k in ("loud", "low", "act"):
            b[k] = float(np.nan_to_num(b[k], nan=-120.0 if k != "act" else 0.0, posinf=0.0, neginf=-120.0))
    if n < 4:
        return {"S": np.zeros(n), "drops": [], "labels": ["verse"] * n, "share": 0.0, "low_n": np.zeros(n)}
    loud = _norm([b["loud"] for b in bars], MIN_RANGE["loud"])
    low = _norm([b["low"] for b in bars], MIN_RANGE["low"])
    act = _norm([b["act"] for b in bars], MIN_RANGE["act"])
    S = 0.45 * loud + 0.30 * low + 0.25 * act
    N = int(max(DROP_MIN_BARS, np.ceil(DROP_MIN_S / max(bar_s, 0.5))))
    cands = []
    level_min = max(DROP_LEVEL, 0.75 * float(np.percentile(S, 90)))     # a drop is among the song's own loudest parts
    for i in range(0, n):
        opening = i <= 1
        pre_bars = S[max(0, i - 4):i]
        pre = float(pre_bars.mean()) if len(pre_bars) else 0.0
        win = S[i:i + N]
        if len(win) < max(4, int(0.75 * N)):
            continue
        post = float(win.mean())
        jump = post - pre
        if not (post >= level_min and jump >= DROP_JUMP):
            continue
        half = pre + 0.5 * jump
        if float(np.mean(win >= half)) < DROP_HOLD:
            continue
        pre_l = float(low[max(0, i - 4):i].mean()) if i else 0.0
        pre_a = float(act[max(0, i - 4):i].mean()) if i else 0.0
        if not (float(low[i:i + N].mean()) - pre_l >= 0.1 or float(act[i:i + N].mean()) - pre_a >= 0.1):
            continue
        rising = i >= 5 and float(S[i - 1] - S[i - 5]) >= 0.1
        if not (opening or pre <= post - 0.3 or rising):
            continue
        cands.append({"bar": i, "jump": jump, "post": post, "bass_jump": float(low[i:i + N].mean()) - pre_l})
    drops = []
    for c in sorted(cands, key=lambda c: -c["jump"]):
        if all(abs(c["bar"] - d["bar"]) >= max(16, N) for d in drops):
            drops.append(c)
    for d in drops:                                          # start = the bar with the sharpest local step (not one bar early)
        i = d["bar"]
        best, bk = -9.0, i
        for k in range(max(1, i - 2), min(n - 1, i + 2) + 1):
            step = float(S[k:k + 2].mean() - S[max(0, k - 2):k].mean())
            if step > best + 1e-9:
                best, bk = step, k
        d["bar"] = bk
    drops.sort(key=lambda d: d["bar"])
    kick_bar = np.array([b.get("kick", 1.0) for b in bars], float)
    for d in drops:                                          # V7.1: the drop is where the KICK comes back, not where a vocal / pad gets loud a few bars earlier
        d["bar"] = kick_entry(kick_bar, d["bar"], N)
    drops = [d for k, d in enumerate(drops) if all(d["bar"] != e["bar"] for e in drops[:k])]
    t_end = float(bars[-1]["t1"])
    fits = lambda bar: bars[bar]["t0"] >= HEAD_S and t_end - bars[bar]["t0"] >= TAIL_S      # V7.2: room for the longest montage before and after the main drop
    for d in drops:
        d["kicky"] = window_kicky(kick_bar, d["bar"], bar_s) and fits(d["bar"])

    def extent(d):
        i = d["bar"]
        level = d["post"]
        j = i + max(2, N // 2)
        while j < n and not (S[j] < 0.75 * level and (j + 1 >= n or S[j + 1] < 0.8 * level)):
            j += 1
        return i, min(j, n, i + 2 * N)               # V7.1: a uniformly loud song keeps its first drop, labelled for at most 2 x the persistence window
    share = lambda ds: sum(extent(d)[1] - extent(d)[0] for d in ds) / max(1, n)
    while drops and share(drops) > SHARE_CAP:
        drops.remove(min(drops, key=lambda d: d["jump"]))
    for c in early_candidates(bars, S, low, kick_bar, level_min):             # V7.4: added AFTER the cap, so no earlier drop is ever removed by them
        ok = True
        for d in drops:
            dist = abs(c["bar"] - d["bar"])
            if dist >= max(16, N):
                continue
            if dist == 0 or dist < 3 or not (dist >= 8 or c["post"] >= d["post"] + 0.12):
                ok = False
                break
        if ok:
            c["kicky"] = window_kicky(kick_bar, c["bar"], bar_s) and fits(c["bar"])
            drops.append(c)
    for c in soft_candidates(S, low, kick_bar, level_min):                     # V7.4.5: gradual drops, after everything else, never next to an existing drop
        if all(abs(c["bar"] - d["bar"]) >= max(16, N) for d in drops):
            c["kicky"] = window_kicky(kick_bar, c["bar"], bar_s) and fits(c["bar"])
            drops.append(c)
    if drops:                                                                  # V7.4.8: later drops only in a song that already has one
        for c in later_candidates(bars, S, low, kick_bar, level_min):
            if all(abs(c["bar"] - d["bar"]) >= max(16, N) for d in drops):
                c["kicky"] = window_kicky(kick_bar, c["bar"], bar_s) and fits(c["bar"])
                drops.append(c)
    drops.sort(key=lambda d: d["bar"])
    labels = ["verse"] * n
    for d in drops:
        a, b = extent(d)
        for k in range(a, b):
            labels[k] = "drop"
    for d in drops:                                          # build (rising) / breakdown (quiet) before a drop
        i = d["bar"]
        k = i - 1
        while k >= 0 and labels[k] == "verse" and i - k <= 8 and S[k] <= S[k + 1] + 0.02 and S[k] < d["post"] - 0.05:
            labels[k] = "build"
            k -= 1
        while k >= 0 and labels[k] == "verse" and i - k <= 16 and S[k] < d["post"] - 0.3 and S[k] < np.median(S):
            labels[k] = "breakdown"
            k -= 1
    # bumps: short rises above the local baseline that are not drops
    base = np.array([float(np.median(S[max(0, k - 8):k])) if k else float(S[0]) for k in range(n)])
    k = 0
    while k < n:
        if labels[k] == "verse" and S[k] - base[k] >= BUMP_RISE:
            j = k
            while j < n and labels[j] == "verse" and S[j] - base[j] >= BUMP_RISE * 0.6:
                j += 1
            for q in range(k, j):
                labels[q] = "bump"
            k = j
        else:
            k += 1
    first = next((k for k, l in enumerate(labels) if l != "verse"), n)
    med = float(np.median(S))
    for k in range(min(first, 16)):
        if S[k] <= med + 0.02:
            labels[k] = "intro"
        else:
            break
    last = max([k for k, l in enumerate(labels) if l == "drop"], default=-1)
    for k in range(n - 1, max(last, 0), -1):
        if labels[k] == "verse" and S[k] < med and k >= 0.7 * n:
            labels[k] = "outro"
        else:
            break
    out = []
    for d in drops:
        out.append({"early": bool(d.get("early")), "soft": bool(d.get("soft")), "later": bool(d.get("later")), "bar": d["bar"], "jump": d["jump"], "bass_jump": d["bass_jump"], "post": d["post"], "kicky": bool(d["kicky"]),
                    "strength": float(d["jump"] + max(d["bass_jump"], 0.0) + d["post"])})
    anchor = None
    if out and not any(d["kicky"] for d in out):               # V7.1: every real drop sits behind a kick-less build: anchor the planner's window on the kick entry instead
        nb = max(4, int(round(ANCHOR_LEN_S / max(bar_s, 0.5))))
        for d in sorted(out, key=lambda d: -d["strength"]):
            if span_kicky(kick_bar, d["bar"], nb, GAP_BARS + 1) and fits(d["bar"]):            # a 2-bar fill inside a drop is normal
                anchor = d["bar"] + int(round(PRE_FRAC * nb))
                break
    if out and anchor is None and not any(d["kicky"] for d in out):      # still nothing kicky: the planner's main drop = the best kicky step of the song (or none)
        rel = relaxed_drop(S, kick_bar, bar_s, N)
        anchor = rel["bar"] if rel is not None and fits(rel["bar"]) else -1
    return {"S": S, "low_n": low, "drops": out, "labels": labels, "share": share(drops), "kick_bar": kick_bar, "anchor": anchor}
