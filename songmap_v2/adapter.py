"""STAGE 4 - adapter: the V2 analysis in EXACTLY the dict shape V1's `build_song_map` returns (same keys, same types, sorted times), so the
planner / effects / viewer consume it unchanged. Extra fields (grid, confidences, off-grid flags, section labels per bar, frame indices)
are optional extras under "v2" that existing consumers ignore. Energy is a bar-smoothed visualisation value and is never used for timing."""
import json
import re
import subprocess

import numpy as np

from . import ALGO_V
from .events import use_time

EXTRA_EVENTS_CAP = 6000


def _lufs(path):
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                           capture_output=True, timeout=120)
        m = re.findall(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", r.stderr.decode(errors="replace"))
        if m and m[-1] != "-inf":
            v = float(m[-1])
            return v if v > -70 else None
    except Exception:
        pass
    return None


def _start_time(path):
    try:
        st = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=start_time", "-of", "json",
                                        str(path)], capture_output=True, timeout=30).stdout or b"{}")
        return float((st.get("streams") or [{}])[0].get("start_time") or 0)
    except Exception:
        return 0.0


SNAP_GAP_BEATS = 1.5            # V7.4: a low-band break = no strong, on-grid kick / bass onset for at least this many beats
SNAP_MIN_STRENGTH = 0.8         # "strong": a pickup / ghost note (weaker) never marks the return
SNAP_ON_GRID = 0.25             # on-grid: within this share of a beat of a grid beat (an off-grid 8th-note pickup is not the beat the drop sits on)
SNAP_RETURN_N = 3               # ... and at least this many such onsets in the 2 bars after it (the kick really returns)


def snap_to_return(beats, bars, k, EV):
    """V7.4 beat snap: the beat of drop bar `k` -> the beat where the kick / bass RETURNS: the first strong on-grid low-band onset after a break (gap >= SNAP_GAP_BEATS),
    searched within -1 bar .. +0.5 bar of the detected rise, using the beat grid read-only. Returns (beat index, onset time) or None when there is no break to snap to."""
    b = bars[k]
    per = float(np.median(np.diff(beats)))
    bar_s = max(per, float(b["t1"] - b["t0"]))
    t_bar = float(beats[b["beat0"]])
    lo, hi = t_bar - bar_s, t_bar + 0.5 * bar_s
    low = np.sort(np.array([float(e["raw_time"]) for e in EV if e["type"] in ("kick", "bass") and e["strength"] >= SNAP_MIN_STRENGTH]))
    if len(low):
        j_ = np.clip(np.searchsorted(beats, low), 1, len(beats) - 1)
        near = np.minimum(np.abs(beats[j_] - low), np.abs(beats[j_ - 1] - low))
        low = low[near <= SNAP_ON_GRID * per]
    if len(low) < SNAP_RETURN_N + 1:
        return None
    best = None
    for j, t in enumerate(low):
        if not (lo <= t <= hi):
            continue
        prev = low[j - 1] if j else -1e9
        if t - prev < SNAP_GAP_BEATS * per:
            continue
        if int(np.sum((low > t) & (low <= t + 2 * bar_s))) < SNAP_RETURN_N:
            continue
        if best is None or abs(t - t_bar) < abs(best - t_bar):
            best = float(t)
    if best is None:
        return None
    j = int(np.argmin(np.abs(beats - best)))
    return j, best


def to_v1_shape(path, y, sr, G, EV, SEC, csv_bpm, extras):
    """G = grid dict (beats, bpm, bpb, down, conf ...), EV = associated events, SEC = sections.analyse() + bars."""
    beats = np.asarray(G["beats"], float)
    nb = len(beats)
    dur = len(y) / sr
    per = float(np.median(np.diff(beats)))
    down = [int(i) for i in G["down"]]
    bars = SEC["bars"]
    labels = SEC["labels"]
    S = SEC["S"]
    # per-beat energy / level / section label from the bars
    bar_of_beat = np.zeros(nb, int)
    for k, b in enumerate(bars):
        bar_of_beat[b["beat0"]:b["beat1"]] = k
    if bars:
        bar_of_beat[:bars[0]["beat0"]] = 0
    Ss = np.convolve(S, np.ones(3) / 3, mode="same") if len(S) >= 3 else S
    energy = [round(float(Ss[bar_of_beat[i]]), 3) if len(Ss) else 0.0 for i in range(nb)]
    lab_beat = [labels[bar_of_beat[i]] if len(labels) else "" for i in range(nb)]
    level = [{"drop": 2, "build": 1, "breakdown": 1}.get(l, 0) for l in lab_beat]
    # V1 sections (beat ranges, merged by label)
    sections = []
    for k, b in enumerate(bars):
        l = labels[k]
        a, e = b["beat0"] if k else 0, b["beat1"]
        if sections and sections[-1]["label"] == l:
            sections[-1].update(end=e, end_t=round(float(b["t1"]), 3))
        else:
            sections.append({"label": l, "start": int(a), "end": int(e), "start_t": round(float(beats[a]), 3), "end_t": round(float(b["t1"]), 3),
                             "level": round(float(S[k]), 3)})
    # drops in V1 shape
    drops, snaps, seen = [], [], set()
    keep_rows = []
    for d in SEC["drops"]:
        bt = bars[d["bar"]]["beat0"]
        try:
            sn = snap_to_return(beats, bars, d["bar"], EV)
        except Exception:
            sn = None
        if sn is not None and sn[0] != bt:
            snaps.append({"from": round(float(beats[bt]), 3), "to": round(float(beats[sn[0]]), 3), "delta_s": round(float(beats[sn[0]] - beats[bt]), 3),
                          "onset": round(sn[1], 3), "early": bool(d.get("early"))})
            bt = sn[0]
        if bt in seen:
            continue
        seen.add(bt)
        keep_rows.append(d)
        drops.append({"beat": int(bt), "t": round(float(beats[bt]), 4), "strength": round(float(d["strength"]), 3),
                      "jump": round(float(d["jump"]), 3), "bass_jump": round(float(d["bass_jump"]), 3)})
    kd = [d for d, r in zip(drops, keep_rows) if r.get("kicky")]
    big = max(kd or drops, key=lambda d: d["strength"]) if drops else None      # V7.1: the main drop is the strongest one whose planner window has a continuous kick grid
    main_beat = big["beat"] if big else None
    if SEC.get("anchor") is not None and drops and not kd:        # every drop is behind a kick-less build: the planner's main drop = a point inside the drop that gives it a kicky window
        main_beat = int(bars[SEC["anchor"]]["beat0"]) if SEC["anchor"] >= 0 else None
    # phrases: 4-bar boundaries where the section changes land
    bar_down = [b["beat0"] for b in bars]
    starts = {s["start"] for s in sections[1:]}
    ph4, ph8 = [], []
    if len(bar_down) >= 4:
        q = max(range(4), key=lambda p: sum(1 for i, bd in enumerate(bar_down) if i % 4 == p and bd in starts))
        ph4 = [bd for i, bd in enumerate(bar_down) if i % 4 == q]
        q8 = max(range(2), key=lambda p: sum(1 for j, bd in enumerate(ph4) if j % 2 == p and bd in starts)) if len(ph4) >= 4 else 0
        ph8 = [bd for j, bd in enumerate(ph4) if j % 2 == q8]
    # accents [t, strength, bass_hit], V1 scale (>= 3)
    acc = []
    for e in EV:
        if e["type"] in ("kick", "bass", "snare", "accent") and e["strength"] >= 0.3:
            acc.append([round(float(use_time(e)), 4), round(3.0 + 17.0 * float(e["strength"]), 2), int(e["type"] == "bass")])
    acc.sort(key=lambda a: -a[1])
    acc = sorted(acc[:800])
    # per-beat strength (same recipe as V1, V2 evidence)
    on_b = np.zeros(nb)
    kick_b = np.zeros(nb)
    et = np.array([use_time(e) for e in EV]) if EV else np.array([])
    if len(et):
        j = np.clip(np.searchsorted(beats, et), 1, nb - 1)
        near = np.where(np.abs(beats[j] - et) < np.abs(beats[j - 1] - et), j, j - 1)
        for e, k, t in zip(EV, near, et):
            if abs(beats[k] - t) <= 0.04:
                on_b[k] = max(on_b[k], e["strength"])
                if e["type"] in ("kick", "bass"):
                    kick_b[k] = max(kick_b[k], e["strength"])
    drop_beats = {d["beat"] for d in drops}
    downs, p4, p8 = set(down), set(ph4), set(ph8)
    strength = [round(float(0.3 + 0.25 * (i in downs) + 0.15 * (i in p4) + 0.15 * (i in p8) + 0.8 * (i in drop_beats) + 0.35 * on_b[i]
                            + 0.15 * kick_b[i]), 3) for i in range(nb)]
    # rhythm / pattern / steady / bpm_fit
    obs = float(G.get("obs_frac", 0.0))
    rhythm = float(np.clip(0.6 * min(1.0, float(np.mean(on_b >= 0.3)) * 1.6) + 0.4 * obs, 0, 1))
    bpb = int(G["bpb"])
    slots = 2 * bpb
    pat = np.zeros(8)
    for e in EV:
        if e.get("on_grid") and e.get("grid_position") is not None and e["type"] in ("kick", "bass", "snare", "accent"):
            pos = e["grid_position"] * 2
            if abs(pos - round(pos)) < 1e-6:
                pass
    byslot = {}
    for e in EV:
        if e.get("on_grid") and e.get("beat") is not None and e["type"] in ("kick", "bass", "snare", "accent"):
            frac = (e["grid_position"] - np.floor(e["grid_position"]))
            sl = ((int(e["beat"]) - (down[0] if down else 0)) % bpb) * 2 + (1 if abs(frac - 0.5) < 0.2 else 0)
            byslot.setdefault(min(sl, 7), []).append(e["strength"])
    for k, v in byslot.items():
        pat[k] = float(np.median(v))
    bpm0 = float(G["bpm"])
    bpm_fit = 1.0 if 100 <= bpm0 <= 180 else max(0.0, 1 - min(abs(bpm0 - 100), abs(bpm0 - 180)) / 40)
    steady = float(np.clip(0.5 * float(G["conf"]) + 0.5 * rhythm, 0, 1))
    wv = np.abs(y[: len(y) // 2000 * 2000]).reshape(2000, -1).max(1) if len(y) >= 2000 else np.abs(y)
    m = {"v": ALGO_V, "tracker": "v2grid", "bpm": round(bpm0, 3), "bpm_src": "csv" if G.get("csv_used") else "audio",
         "bpm_librosa": round(bpm0, 1), "period": round(per, 6), "grid_score": round(float(G["conf"]), 3), "librosa_agree_ms": None,
         "beats": [round(float(t), 4) for t in beats], "down": down, "phrase4": [int(i) for i in ph4], "phrase8": [int(i) for i in ph8],
         "sections": sections, "drops": drops, "accents": acc, "strength": strength, "energy": energy, "level": [int(v) for v in level],
         "section_of_beat": lab_beat, "drop": main_beat, "drop_strength": round(big["strength"] / 3, 3) if big else 0.0,
         "rhythm": round(rhythm, 3), "pattern": [round(float(v), 2) for v in pat], "steady": round(steady, 3), "bpm_fit": round(bpm_fit, 2),
         "dur": round(dur, 3), "onsets": [a[0] for a in acc], "wave": [round(float(v), 3) for v in wv], "lufs": _lufs(path),
         "start_time": round(_start_time(path), 6),
         "origin": "first decoded sample (ffmpeg skips the encoder delay); render trims with asetpts=N/SR/TB",
         "songmap_version": "v2"}
    ev_extra = []
    for e in EV[:EXTRA_EVENTS_CAP]:
        ev_extra.append({k: (round(v, 5) if isinstance(v, float) else v) for k, v in e.items()})
    kicky_window = (not drops) or bool(kd) or (SEC.get("anchor") is not None and SEC["anchor"] >= 0)       # no drops at all: nothing for the planner to anchor on, nothing to get wrong
    extras = dict(extras, drop_snap=snaps)
    m["v2"] = dict(extras, kicky_window=kicky_window, algo=ALGO_V, events=ev_extra, bar_labels=list(labels), segments=G["segments"], beats_per_bar=bpb,
                   beat_in_bar=[int((i - (down[0] if down else 0)) % bpb) for i in range(nb)],
                   bar_index=[int(bar_of_beat[i]) for i in range(nb)], beat_segment=[int(x) for x in G["seg"]],
                   downbeat_confidence=round(float(G["down_conf"]), 3), downbeats_low_confidence=bool(G["down_conf"] < 0.6),
                   grid_confidence=round(float(G["conf"]), 3), drop_share=round(float(SEC["share"]), 3), fallback=False)
    return m
