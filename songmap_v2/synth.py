"""V7 genre suite (B1): songs generated in code with known beats / downbeats / kicks (every sound placed at an exact sample time). Read-only helpers,
never imported by the app."""
import subprocess
import wave
from pathlib import Path

import numpy as np

from .bench import nearest

SR = 22050
SPEC = {"chill70": 70, "hiphop87": 87, "country100": 100, "house128": 128, "dubstep140": 140, "hardstyle150": 150, "hardstyle160": 160,
        "dnb174": 174, "bpm127_3": 127.3, "waltz120": 120, "tempochange": 100, "odd_intro": 124, "ambient": 90, "mp3delay": 128}
SUITE = list(SPEC)
SWING = {"hiphop87": 0.18, "country100": 0.33}
BASSLINE = ("house128", "bpm127_3", "mp3delay", "tempochange", "odd_intro")
LOOSE = ("hiphop87", "country100")          # swing / drift: looser targets (20 / 40 ms)


def _env(n, atk, dec):
    t = np.arange(n) / SR
    return np.minimum(1.0, t / max(atk, 1e-4)) * np.exp(-t / dec)


def _kick(amp=1.0, dur=0.28, f0=48, sweep=80, long_tail=False):
    n = int(dur * SR)
    t = np.arange(n) / SR
    ph = 2 * np.pi * (f0 * t + sweep * (1 - np.exp(-t * 30)) / 30)
    return amp * np.sin(ph) * _env(n, 0.001, 0.12 if long_tail else 0.06)


def _snare(amp, rng):
    n = int(0.22 * SR)
    t = np.arange(n) / SR
    return amp * (rng.standard_normal(n) * 0.7 + np.sin(2 * np.pi * 190 * t)) * _env(n, 0.001, 0.05)


def _hat(amp, rng, dec=0.02):
    n = int(0.08 * SR)
    x = rng.standard_normal(n)
    x = x - np.concatenate([[0], x[:-1]])
    return amp * x * _env(n, 0.0005, dec)


def _bass_note(dur, f=55.0, amp=0.35):
    n = int(dur * SR)
    t = np.arange(n) / SR
    return amp * np.sin(2 * np.pi * f * t) * np.minimum(1.0, t / 0.06) * np.minimum(1.0, (dur - t) / 0.1)


def _put(y, t0, s):
    i = int(round(t0 * SR))
    if 0 <= i < len(y):
        e = min(len(s), len(y) - i)
        y[i:i + e] += s[:e]


def gen_song(name, dur=75.0, seed=1):
    """(audio float32 @22050, truth). truth = beats, down (bar starts), bpm, kicks, bpb, segs [(t0, bpm)], ambient flag."""
    rng = np.random.default_rng(seed)
    y = np.zeros(int(dur * SR) + SR)
    kicks, beats, down = [], [], []
    bpm0 = SPEC[name]
    bpb = 3 if name == "waltz120" else 4
    t = 7.37 if name == "odd_intro" else 0.4
    bpm, drift, beat_i = bpm0, 0.0, 0
    segs = [(t, bpm0)]
    kk, kk_soft, kk_long = _kick(), _kick(0.35, 0.3, 45, 50), _kick(1.0, 0.3, 50, 90, True)
    if name in ("chill70", "ambient", "odd_intro"):
        tt = np.arange(len(y)) / SR
        for f in (110.0, 164.8, 220.0):
            y += 0.06 * np.sin(2 * np.pi * f * tt) * (0.7 + 0.3 * np.sin(2 * np.pi * 0.07 * tt))
    if name == "ambient":
        return (y / np.abs(y).max() * 0.5).astype(np.float32), {"beats": [], "down": [], "bpm": None, "kicks": [], "bpb": 4, "segs": [], "ambient": True, "name": name}
    while t < dur - 0.5:
        if name == "tempochange" and t > 38.0:
            bpm = 124.0
            if segs[-1][1] != bpm:
                segs.append((t, bpm))
        if name == "country100":
            drift = float(np.clip(drift + rng.normal(0, 0.004), -0.03, 0.03))
        P = 60.0 / bpm * (1 + drift)
        pos = beat_i % bpb
        beats.append(t)
        if pos == 0:
            down.append(t)
        sw = SWING.get(name, 0.0)
        half = t + P * (0.5 + sw / 2)
        if name == "chill70":
            if pos in (0, 2):
                _put(y, t, kk_soft * (1.5 if pos == 0 else 1.0)); kicks.append(t)
            if pos in (1, 3):
                _put(y, t, _snare(0.12, rng))
            _put(y, half, _hat(0.04, rng))
        elif name == "hiphop87":
            b8 = beat_i % 8
            if pos == 0 or b8 == 2 or b8 == 7:
                _put(y, t, kk); kicks.append(t)
            if pos in (1, 3):
                _put(y, t, _snare(0.5, rng))
            _put(y, t, _hat(0.15, rng)); _put(y, half, _hat(0.1, rng))
        elif name == "country100":
            if pos in (0, 2):
                _put(y, t, kk); kicks.append(t)
            if pos in (1, 3):
                _put(y, t, _snare(0.45, rng))
            _put(y, t, _hat(0.12, rng)); _put(y, half, _hat(0.1, rng))
        elif name in ("house128", "bpm127_3", "mp3delay", "tempochange", "odd_intro"):
            _put(y, t, kk); kicks.append(t)
            if pos in (1, 3):
                _put(y, t, _snare(0.35, rng))
            _put(y, half, _hat(0.25, rng, 0.05))
            if beat_i % 16 == 0:                                   # crash on the first beat of every 4th bar (a bar-start marker: four on the floor has none)
                _put(y, t, _hat(0.5, rng, 0.35))
        elif name == "dubstep140":
            b8 = beat_i % 8
            if b8 == 0:
                _put(y, t, kk_long); kicks.append(t)
            if b8 == 4:
                _put(y, t, _snare(0.7, rng))
            if b8 == 2 and (beat_i // 8) % 2:
                _put(y, t, kk); kicks.append(t)
            _put(y, t, _hat(0.12, rng)); _put(y, t + P * 0.5, _hat(0.12, rng))
        elif name in ("hardstyle150", "hardstyle160"):
            _put(y, t, kk_long); kicks.append(t)
            tt = np.arange(int(P * 0.5 * SR)) / SR
            rb = 0.3 * np.sign(np.sin(2 * np.pi * 98 * tt)) * np.minimum(1.0, (tt / (P * 0.5)) ** 1.5 + 0.2)
            _put(y, t + P * 0.5, np.convolve(rb, np.ones(20) / 20, mode="same"))
            if pos in (1, 3):
                _put(y, t + P * 0.5, _hat(0.25, rng, 0.05))
            if pos == 0:                                           # a lead stab on the first beat of every bar (the bar-start cue of this genre)
                n_ = int(0.35 * SR)
                tt_ = np.arange(n_) / SR
                _put(y, t, 0.3 * (np.sin(2 * np.pi * 880 * tt_) + np.sin(2 * np.pi * 1318 * tt_)) * _env(n_, 0.002, 0.15))
        elif name == "dnb174":
            if pos == 0:
                _put(y, t, kk); kicks.append(t)
            if pos == 2:
                _put(y, t + P * 0.5, kk); kicks.append(t + P * 0.5)
            if pos in (1, 3):
                _put(y, t, _snare(0.65, rng))
            for q in (0, 0.25, 0.5, 0.75):
                _put(y, t + P * q, _hat(0.08, rng))
        elif name == "waltz120":
            if pos == 0:
                _put(y, t, kk); kicks.append(t)
            else:
                _put(y, t, _snare(0.3, rng))
            _put(y, half, _hat(0.1, rng))
        if pos == 0 and name in BASSLINE:                             # the bass root note changes with every bar: the usual bar-start cue of four-on-the-floor music
            _put(y, t, _bass_note(P * bpb * 0.9))
        beat_i += 1
        t += P
    y = (y / np.abs(y).max() * 0.8).astype(np.float32)
    return y, {"beats": beats, "down": down, "bpm": bpm0, "kicks": kicks, "bpb": bpb, "segs": segs, "ambient": False, "name": name}


def write_wav(path, y, sr=SR):
    a = (np.clip(y, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(a.tobytes())


def make_song_file(name, folder, seed=1, dur=75.0):
    """Writes the generated song (a wav; 'mp3delay' as a LAME mp3 with its encoder delay) and returns (path, truth)."""
    y, truth = gen_song(name, dur, seed)
    wav = Path(folder) / f"{name}.wav"
    write_wav(wav, y)
    if name == "mp3delay":
        mp3 = Path(folder) / f"{name}.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)], check=True)
        return str(mp3), truth
    return str(wav), truth


def octave_ok(bpm, true_bpm, tol=0.01):
    """Tempo within `tol` of the truth or its 0.5x / 2x, and inside 60..200 BPM."""
    if bpm is None or not (59.5 <= bpm <= 200.5):
        return False
    return any(abs(bpm / (true_bpm * f) - 1) <= tol for f in (1.0, 0.5, 2.0))


def eval_synth(m, truth):
    """Grid error of the TRUE beats against the map's nearest beat (a 2x grid hits every true beat), tempo check, downbeat phase, NaN check."""
    r = {"nan": False, "bpm": None}
    b = np.asarray(m["beats"], float)
    r["nan"] = bool(not np.all(np.isfinite(b)) or not np.isfinite(float(m["bpm"])) or any(not np.isfinite(float(x)) for x in np.asarray(m["energy"], float)))
    r["bpm"] = round(float(m["bpm"]), 2)
    if truth.get("ambient"):
        return r
    tb = np.asarray(truth["beats"], float)
    ratio = float(m["bpm"]) / float(truth["bpm"])
    ref = tb
    if truth["name"] != "tempochange" and abs(ratio / 2 - 1) < 0.1:          # a double-time grid also lays beats on the half beats
        ref = np.sort(np.concatenate([tb, 0.5 * (tb[1:] + tb[:-1])]))
    span = (b >= tb[0] - 0.1) & (b <= tb[-1] + 0.1)
    d = np.abs(nearest(b[span], ref)) * 1000 if span.any() else np.array([np.inf])
    r["median_ms"] = round(float(np.median(d)), 1)
    r["p95_ms"] = round(float(np.percentile(d, 95)), 1)
    if truth["name"] == "tempochange":
        r["tempo_ok"] = octave_ok(float(m["bpm"]), 100.0, 0.25) or octave_ok(float(m["bpm"]), 124.0, 0.25)
    else:
        r["tempo_ok"] = octave_ok(float(m["bpm"]), float(truth["bpm"]), 0.01 if truth["name"] != "country100" else 0.04)
    down = np.asarray([m["beats"][i] for i in m.get("down", []) if i < len(m["beats"])], float)
    td = np.asarray(truth["down"], float)
    r["down_ok_frac"] = round(float((np.abs(nearest(down, td)) <= 0.035).mean()), 3) if len(down) and len(td) else 0.0
    return r


def targets(name):
    """(median_ms, p95_ms) targets of B1."""
    return (20.0, 40.0) if name in LOOSE else (10.0, 25.0)
