"""build_songmap_v2(): decode on the render timebase -> grid -> events -> sections -> adapter. Cooperative time cap (`deadline`)."""
import hashlib
import os
import time

import numpy as np

from . import ALGO_V, ANALYSIS_CAP_S, CACHE_NS, adapter, events, grid, sections, timebase


def file_signature(path):
    """Cheap file identity: size + mtime + hash of the first / last 64 KB (no full read)."""
    st = os.stat(path)
    h = hashlib.sha1()
    with open(path, "rb") as f:
        h.update(f.read(65536))
        if st.st_size > 131072:
            f.seek(-65536, 2)
            h.update(f.read(65536))
    return f"{st.st_size}-{int(st.st_mtime)}-{h.hexdigest()[:12]}"


ALGO_REV = "tempolock1"        # V6.9.5.2: invalidates ONLY the V2 cache entries made by the 6.9.5 / 6.9.5.1 grid (ALGO_V in __init__.py is untouched)


def cache_key(path, csv_bpm=None, v1_bpm=None):
    """V2 cache key. The V1 BPM (read-only, a candidate of the tempo lock) is part of the key only when it was used."""
    return f"{CACHE_NS}|{ALGO_V}|{file_signature(path)}|{round(float(csv_bpm or 0), 3)}|{ALGO_REV}" + (f"|v1:{round(float(v1_bpm), 2)}" if v1_bpm else "")


AUTO_MIN_CONF = 0.8             # 'Songmap V2 (auto, V1 fallback)' uses V2 only if ALL three hold (V6.9.5.2)
AUTO_MAX_P95_MS = 40.0
AUTO_WINDOW_S = 0.06            # the kicks both grids are judged on: within 60 ms of EITHER grid (the same rule as the compare tool)


def auto_decision(v1, v2):
    """Per-song choice between the V1 map and the V2 map. V2 wins only if (1) its grid confidence >= 0.8, (2) its kick-to-grid p95 <= 40 ms and
    (3) its kick-to-grid median <= V1's median, all measured on the strong kicks of V2's own events against each map's beats.
    Returns a JSON-able dict: choice ("v1" / "v2"), reason, conf and the numbers."""
    conf = float(v2["v2"]["grid_confidence"])
    kicks = np.array(sorted(e["raw_time"] for e in v2["v2"]["events"] if e["type"] in ("kick", "bass") and e["strength"] >= 0.5))
    b1, b2 = np.asarray(v1["beats"], float), np.asarray(v2["beats"], float)
    if len(kicks) and len(b1) > 1 and len(b2) > 1:
        keep = (np.abs(grid._near(kicks, b1)) <= AUTO_WINDOW_S) | (np.abs(grid._near(kicks, b2)) <= AUTO_WINDOW_S)
        kicks = kicks[keep]
    s1, s2 = grid.kick_grid_stats(b1, kicks), grid.kick_grid_stats(b2, kicks)
    dec = {"conf": round(conf, 3), "n_kicks": s2["n"], "v2_median_ms": s2["median_ms"], "v2_p95_ms": s2["p95_ms"],
           "v1_median_ms": s1["median_ms"], "v1_p95_ms": s1["p95_ms"], "v2_bpm": v2["bpm"], "v1_bpm": v1["bpm"]}
    why = []
    if s2["n"] < 8:
        why.append(f"only {s2['n']} kicks to judge the grid on")
    else:
        if conf < AUTO_MIN_CONF:
            why.append(f"grid confidence {conf:.2f} < {AUTO_MIN_CONF}")
        if s2["p95_ms"] > AUTO_MAX_P95_MS:
            why.append(f"kick p95 {s2['p95_ms']:.0f} ms > {AUTO_MAX_P95_MS:.0f} ms")
        if s2["median_ms"] > s1["median_ms"]:
            why.append(f"kick median {s2['median_ms']:.0f} ms worse than V1 {s1['median_ms']:.0f} ms")
    dec["choice"] = "v1" if why else "v2"
    dec["reason"] = "; ".join(why) if why else "all three conditions hold"
    return dec


def auto_line(dec):
    """The tail of the per-song log line: 'V2 (conf 0.93, median 2 ms vs V1 47 ms)' or 'V1 (reason)'."""
    if dec["choice"] == "v2":
        return f"V2 (conf {dec['conf']:.2f}, median {dec['v2_median_ms']:.0f} ms vs V1 {dec['v1_median_ms']:.0f} ms)"
    return f"V1 ({dec['reason']})"


class Cap(Exception):
    pass


def choose_bpb(beats, F, kick_t, kick_s):
    """4 or 3 beats per bar from how strongly the low-band evidence concentrates on one beat position."""
    best = {}
    for bpb in (4, 3):
        phase, conf, _ = grid.bars_and_downbeats(beats, F, kick_t, kick_s, bpb)
        nb = len(beats)
        ev = np.zeros(nb)
        if len(kick_t):
            j = np.clip(np.searchsorted(beats, kick_t), 1, nb - 1)
            near = np.where(np.abs(beats[j] - kick_t) < np.abs(beats[j - 1] - kick_t), j, j - 1)
            ok = np.abs(beats[near] - kick_t) < 0.08
            np.add.at(ev, near[ok], kick_s[ok])
        m = np.array([ev[p::bpb].mean() for p in range(bpb)])
        best[bpb] = float(m.max() / (m.mean() + 1e-9) - 1.0) / (bpb - 1)
    return 3 if best[3] > best[4] + 0.15 else 4


def build_songmap_v2(path, csv_bpm=None, deadline=None, hook=None, v1_bpm=None):
    """Returns the V1-shaped map (with the optional "v2" extras). Raises on any problem; the dispatcher turns that into a V1 fallback."""
    t0 = time.time()

    def chk(stage):
        if deadline is not None and time.monotonic() > deadline:
            raise Cap(f"analysis cap reached in {stage}")
    if hook:
        hook()
    y, sr = timebase.decode(path)
    if len(y) < sr * 20:
        raise RuntimeError("audio too short / undecodable")
    dur = len(y) / sr
    chk("decode")
    F = grid.features(y, sr)
    chk("features")
    o = grid.onset_mix(F)
    o_lm = grid.onset_linear(F)
    bpm, tinfo = grid.estimate_tempo(o, F["dt"], csv_bpm, o_lm)
    chk("tempo")
    ev = events.detect(F)                       # onsets never depend on the grid, so they feed the tempo lock
    chk("events")
    kk = [e for e in ev if e["type"] in ("kick", "bass") and e["strength"] >= 0.5]
    kt = np.array([e["raw_time"] for e in kk])
    ks = np.array([e["strength"] for e in kk])
    hit = np.array([e["raw_time"] for e in ev if e["type"] in ("kick", "bass", "snare", "accent") and e["strength"] >= 0.1])
    if len(kt) < 8:                             # no kick / bass at all: every strong low / mid onset takes their place
        kk = [e for e in ev if e["type"] in ("kick", "bass", "snare", "accent") and e["strength"] >= 0.5]
        kt, ks = np.array([e["raw_time"] for e in kk]), np.array([e["strength"] for e in kk])
    G = grid.fit_grid(o, F["dt"], bpm, dur, kt, ks, hit, v1_bpm, csv_bpm)
    chk("grid")
    beats = np.asarray(G["beats"], float)
    # global phase: strong low-band onsets (kicks) must sit on the grid on average; correct the grid, never the events
    phase_corr = 0.0
    if len(kt) >= 8:
        off = grid.kick_offsets(beats, kt)
        if len(off) >= 8 and abs(float(np.median(off))) > 0.0003:
            phase_corr = float(np.median(off))
            beats = beats + phase_corr
    G["beats"] = beats
    bpb = choose_bpb(beats, F, kt, ks)
    phase, dconf, wins = grid.bars_and_downbeats(beats, F, kt, ks, bpb)
    down = [i for i in range(len(beats)) if i % bpb == phase]
    period = float(np.median(np.diff(beats)))
    bpm_final = 60.0 / period
    csv_used = bool(csv_bpm and any(abs(bpm_final / (csv_bpm * f) - 1) < 0.04 for f in (0.5, 1.0, 2.0)))
    conf, conf_parts = grid.grid_confidence(beats, kt, grid.onset_mix(F, ("low", "mid")), F["dt"])
    conf_parts["kick_stats"] = grid.kick_grid_stats(beats, kt)
    log_line = (f"grid confidence {conf:.3f} = 0.7 x kicks on grid {conf_parts['kick_on_grid']:.3f} + 0.3 x periodicity {conf_parts['periodicity']:.3f} "
                f"({conf_parts['n_kicks']} kicks), tempo {bpm_final:.2f}")
    EV = events.associate(ev, beats, bpb)
    chk("associate")
    bars = sections.bar_table(beats, down, dur, y, sr, F["sig"]["low"], EV)
    SEC = sections.analyse(bars, float(np.median([b["t1"] - b["t0"] for b in bars])) if bars else period * bpb)
    SEC["bars"] = bars
    SEC["labels"] = SEC["labels"] if len(SEC["labels"]) == len(bars) else (SEC["labels"] + ["verse"] * len(bars))[:len(bars)]
    chk("sections")
    G.update(bpm=bpm_final, bpb=bpb, down=down, conf=conf, down_conf=dconf, csv_used=csv_used)
    n_on = sum(1 for e in EV if e["on_grid"])
    extras = {"phase_correction_ms": round(phase_corr * 1000, 3), "tempo": tinfo, "lock": G["lock"], "confidence_parts": conf_parts, "confidence_log": log_line, "events_on_grid": n_on, "events_total": len(EV),
              "pre_intro_beats": int(np.argmax(G["observed"])) if len(G["observed"]) else 0,
              "analysis_s": round(time.time() - t0, 2)}
    m = adapter.to_v1_shape(path, y, sr, G, EV, SEC, csv_bpm, extras)
    return m
