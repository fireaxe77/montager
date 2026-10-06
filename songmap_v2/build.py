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


def cache_key(path, csv_bpm=None):
    return f"{CACHE_NS}|{ALGO_V}|{file_signature(path)}|{round(float(csv_bpm or 0), 3)}"


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


def build_songmap_v2(path, csv_bpm=None, deadline=None, hook=None):
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
    G = grid.fit_grid(o, F["dt"], bpm, dur)
    chk("grid")
    ev = events.detect(F)
    chk("events")
    beats = np.asarray(G["beats"], float)
    # global phase: strong low-band onsets (kicks) must sit on the grid on average; correct the grid, never the events
    kk = [e for e in ev if e["type"] in ("kick", "bass") and e["strength"] >= 0.5]
    kt = np.array([e["raw_time"] for e in kk])
    ks = np.array([e["strength"] for e in kk])
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
    conf = float(np.clip(G["obs_frac"] * (1.0 - min(G["resid_ms"], 30.0) / 30.0), 0, 1))
    EV = events.associate(ev, beats, bpb)
    chk("associate")
    bars = sections.bar_table(beats, down, dur, y, sr, F["sig"]["low"], EV)
    SEC = sections.analyse(bars, float(np.median([b["t1"] - b["t0"] for b in bars])) if bars else period * bpb)
    SEC["bars"] = bars
    SEC["labels"] = SEC["labels"] if len(SEC["labels"]) == len(bars) else (SEC["labels"] + ["verse"] * len(bars))[:len(bars)]
    chk("sections")
    G.update(bpm=bpm_final, bpb=bpb, down=down, conf=conf, down_conf=dconf, csv_used=csv_used)
    n_on = sum(1 for e in EV if e["on_grid"])
    extras = {"phase_correction_ms": round(phase_corr * 1000, 3), "tempo": tinfo, "events_on_grid": n_on, "events_total": len(EV),
              "pre_intro_beats": int(np.argmax(G["observed"])) if len(G["observed"]) else 0,
              "analysis_s": round(time.time() - t0, 2)}
    m = adapter.to_v1_shape(path, y, sr, G, EV, SEC, csv_bpm, extras)
    return m
