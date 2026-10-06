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


def bar_table(beats, down, dur, y, sr, low, events):
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
        rms = (cs[i1] - cs[i0]) / (i1 - i0)
        lw = (cl[min(i1, len(cl) - 1)] - cl[i0]) / (i1 - i0)
        m = (et >= t0) & (et < t1)
        bars.append({"beat0": a, "beat1": b, "t0": t0, "t1": t1, "loud": 10 * np.log10(rms + 1e-12), "low": 10 * np.log10(lw + 1e-12),
                     "act": float(es[m].sum() / (t1 - t0)) if len(es) else 0.0})
    return bars


def _norm(x, rng_min):
    x = np.asarray(x, float)
    lo, hi = np.percentile(x, 5), np.percentile(x, 95)
    return np.clip((x - lo) / max(hi - lo, rng_min), 0, 1)


def analyse(bars, bar_s):
    """Returns {"S","drops","labels","share"}; drops = [{"bar","t","strength","jump","bass_jump"}] (V1 field names)."""
    n = len(bars)
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

    def extent(d):
        i = d["bar"]
        level = d["post"]
        j = i + max(2, N // 2)
        while j < n and not (S[j] < 0.75 * level and (j + 1 >= n or S[j + 1] < 0.8 * level)):
            j += 1
        return i, min(j, n)
    share = lambda ds: sum(extent(d)[1] - extent(d)[0] for d in ds) / max(1, n)
    while drops and share(drops) > SHARE_CAP:
        drops.remove(min(drops, key=lambda d: d["jump"]))
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
        out.append({"bar": d["bar"], "jump": d["jump"], "bass_jump": d["bass_jump"], "post": d["post"],
                    "strength": float(d["jump"] + max(d["bass_jump"], 0.0) + d["post"])})
    return {"S": S, "low_n": low, "drops": out, "labels": labels, "share": share(drops)}
