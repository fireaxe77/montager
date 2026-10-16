"""V8.4.5 tool: MEASURE the game audio of a plan against its source clips. No guessing, no listening.
python tests/audio845.py <game> <extra|default> --seed N [--unuse TITLE] [--code <folder with montage.py>] [--out DIR] [--label NAME] [--fix]
  1. builds the plan like the GUI job (plan845.build; --unuse rewinds the used-clip history of a finished job so the SAME plan comes out),
  2. builds the filter graph with the chosen code (the current tree, or a git-archive folder of a tag), keeps only the chains that feed the game-audio concat [gc]
     (no music, no video) and runs ffmpeg once -> OUT/<label>.game.wav (48 kHz stereo float),
  3. decodes every source clip's audio with timestamps honoured (aresample async=1: a hole in the recording stays a gap, like the video),
  4. for every 1.0x segment of every take cross-correlates the rendered audio with the source audio of exactly that range (+-0.6 s search):
     offset (ms), correlation, residual (how much of the rendered segment is NOT explained by the source range = overlay / echo / another clip, dB below the segment),
     left/right delay (ms) in the render vs the source, echo (autocorrelation peak 8-300 ms), and which OTHER take's source range explains the residual best.
Prints the takes that do not match (|offset| > 6 ms, correlation < 0.97 or residual > -20 dB) and a summary line."""
import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
ROOT = _root.find_root()
SR = 48000


def load_code(folder=None, name="montage"):                    # always the name "montage": the song analysis pickles functions by module name
    folder = Path(folder) if folder else ROOT
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, str(folder / "montage.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    sys.path.insert(0, str(folder))
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        spec.loader.exec_module(m)                                       # the folder stays on sys.path: worker processes import `montage` by name
    return m


def unuse(M, title):
    titles = M.load_json(M.USED_TITLES, {})
    drop = {k for k, v in titles.items() if v.get("title") == title}
    keep = M.used_dates
    M.used_dates = lambda: {k: v for k, v in keep().items() if k not in drop}


def audio_subgraph(graph, target="gc"):
    """The chains of a filter graph that (transitively) feed the label [target]."""
    parts = [p.strip() for p in graph.replace("\r", "").split(";") if p.strip()]
    info = []
    for p in parts:
        m_in = re.match(r"^((?:\[[^\]]+\])+)", p)
        m_out = re.search(r"((?:\[[^\]]+\])+)$", p)
        ins = re.findall(r"\[([^\]]+)\]", m_in.group(1)) if m_in else []
        outs = re.findall(r"\[([^\]]+)\]", m_out.group(1)) if m_out else []
        info.append((ins, outs))
    need, keep = {target}, set()
    changed = True
    while changed:
        changed = False
        for i, (ins, outs) in enumerate(info):
            if i not in keep and any(o in need for o in outs):
                keep.add(i)
                need |= set(ins)
                changed = True
    return ";".join(parts[i] for i in sorted(keep))


def render_game_audio(inputs, graph, out_wav, target="gc"):
    sub = audio_subgraph(graph, target)
    fs = Path(out_wav).with_suffix(".filter.txt")
    fs.write_text(sub, encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error"] + inputs + ["-filter_complex_script", str(fs), "-map", f"[{target}]", "-c:a", "pcm_f32le", "-ar", str(SR), "-ac", "2", str(out_wav)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode:
        raise RuntimeError("ffmpeg failed: " + r.stderr.decode("utf-8", "ignore")[-800:])
    return read_wav(out_wav)


def read_wav(path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-acodec", "pcm_f32le", "-ac", "2", "-ar", str(SR), "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.float32).reshape(-1, 2).copy()


_SRC = {}


def source_audio(path, stream=0):
    """The clip's audio with its timestamps honoured: a hole in the recording is silence of the same length (like the video it belongs to)."""
    k = (str(path), stream)
    if k not in _SRC:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", f"0:a:{stream}", "-af", f"aresample={SR}:async=1:first_pts=0,aformat=sample_fmts=flt:channel_layouts=stereo",
                            "-f", "f32le", "-acodec", "pcm_f32le", "-"], capture_output=True)
        _SRC[k] = np.frombuffer(r.stdout, np.float32).reshape(-1, 2).copy()
    return _SRC[k]


def xcorr_lag(x, ref, max_lag):
    """Lag (samples) at which x best matches ref (x[n] ~ ref[n + lag]) in +-max_lag, the normalised peak, via FFT. x and ref mono, ref longer than x by max_lag at both ends."""
    n = len(x)
    L = 1
    while L < n + len(ref):
        L *= 2
    fx, fr = np.fft.rfft(x, L), np.fft.rfft(ref, L)
    c = np.fft.irfft(fr * np.conj(fx), L)[:len(ref) - n + 1]
    cs = np.concatenate([[0.0], np.cumsum(ref.astype(np.float64) ** 2)])
    en = np.sqrt(np.maximum(cs[n:n + len(c)] - cs[:len(c)], 1e-18)) * (np.sqrt(float(np.sum(x.astype(np.float64) ** 2))) + 1e-12)
    nc = c / en
    i = int(np.argmax(nc))
    return i - max_lag, float(nc[i])


def chan_delay(st, max_ms=30):
    """Delay of the right channel against the left in ms (cross-correlation), 0 when the channels are the same or one is silent."""
    l, r = st[:, 0].astype(np.float64), st[:, 1].astype(np.float64)
    if l.std() < 1e-6 or r.std() < 1e-6:
        return 0.0
    m = int(SR * max_ms / 1000)
    best, bl = -2, 0
    for lag in range(-m, m + 1, 2):
        a = l[max(0, -lag):len(l) - max(0, lag)]
        b = r[max(0, lag):len(r) - max(0, -lag)]
        n = min(len(a), len(b))
        v = float(np.dot(a[:n], b[:n]) / (np.linalg.norm(a[:n]) * np.linalg.norm(b[:n]) + 1e-12))
        if v > best:
            best, bl = v, lag
    return bl * 1000.0 / SR


def echo_score(mono):
    """Largest normalised autocorrelation between 8 and 300 ms (a clean recording has none, an echo / a doubled signal has a peak)."""
    x = mono.astype(np.float64) - mono.mean()
    if x.std() < 1e-6 or len(x) < SR // 4:
        return 0.0
    L = 1
    while L < 2 * len(x):
        L *= 2
    f = np.fft.rfft(x, L)
    ac = np.fft.irfft(f * np.conj(f), L)[:len(x)]
    ac = ac / (ac[0] + 1e-12)
    lo, hi = int(SR * 0.008), min(len(ac) - 1, int(SR * 0.3))
    return float(np.max(ac[lo:hi])) if hi > lo else 0.0


def analyse(plan, wav, search=0.6, log=print):
    """Per 1.0x segment: offset, correlation, residual, L/R delay, echo. Returns the list of dicts."""
    rows = []
    for ti, t in enumerate(plan["takes"], 1):
        srcs = t.get("srcs") or [{"path": t["path"], "shift": 0.0, "audio": t.get("audio"), "a_stream": 0}]
        f = 0
        for sg in t["segs"]:
            a, b, sp, n = sg[:4]
            si = sg[4] if len(sg) > 4 and sg[4] < len(srcs) else 0
            sr = srcs[si]
            o0 = (float(t["out_start"]) + f / 60.0)
            f += int(n)
            if sr.get("audio") and not sr.get("mute") and abs(sp - 1.0) > 1e-6 and sp > 0 and n >= 12:          # a speed-changed segment: the loudness envelope of the render against the source range stretched linearly
                x = wav[int(round(o0 * SR)):int(round((o0 + n / 60.0) * SR))]
                src = source_audio(sr["path"], int(sr.get("a_stream") or 0))
                s0, s1 = int(round((a - sr.get("shift", 0.0)) * SR)), int(round((b - sr.get("shift", 0.0)) * SR))
                if len(x) > SR // 10 and s1 > s0 and s1 <= len(src):
                    blk = SR // 50
                    ex = np.sqrt((x[:len(x) // blk * blk].mean(1).reshape(-1, blk) ** 2).mean(1))
                    es = np.sqrt((src[s0:s1].mean(1)[:(s1 - s0) // blk * blk].reshape(-1, blk) ** 2).mean(1))
                    if len(ex) > 3 and len(es) > 3 and ex.std() > 1e-6 and es.std() > 1e-6:
                        es2 = np.interp(np.linspace(0, len(es) - 1, len(ex)), np.arange(len(es)), es)
                        rows.append({"take": ti, "seg": (round(a, 2), round(b, 2)), "out": round(o0, 2), "speed": round(sp, 2), "env_corr": round(float(np.corrcoef(ex, es2)[0, 1]), 3), "src": Path(sr["path"]).name})
                continue
            if abs(sp - 1.0) > 1e-6 or not sr.get("audio") or sr.get("mute") or n < 12:
                continue
            x = wav[int(round(o0 * SR)):int(round((o0 + n / 60.0) * SR))]
            if len(x) < SR // 10:
                continue
            src = source_audio(sr["path"], int(sr.get("a_stream") or 0))
            s0 = int(round((a - sr.get("shift", 0.0)) * SR))
            ml = int(search * SR)
            lo = s0 - ml
            seg = src[max(0, lo):s0 + len(x) + ml]
            pad_l = max(0, -lo)
            ref = np.concatenate([np.zeros((pad_l, 2), np.float32), seg])
            if len(ref) < len(x) + 2 * ml:
                ref = np.concatenate([ref, np.zeros((len(x) + 2 * ml - len(ref), 2), np.float32)])
            xm, rm = x.mean(1), ref.mean(1)
            if float(np.abs(xm).max()) < 1e-5:
                rows.append({"take": ti, "seg": (round(a, 2), round(b, 2)), "silent": True})
                continue
            lag, cor = xcorr_lag(xm, rm, ml)
            a0 = s0 + lag
            ref_al = src[a0:a0 + len(x)] if a0 >= 0 else np.zeros_like(x)
            if len(ref_al) < len(x):
                ref_al = np.concatenate([ref_al, np.zeros((len(x) - len(ref_al), 2), np.float32)])
            g = float(np.dot(xm, ref_al.mean(1)) / (np.dot(ref_al.mean(1), ref_al.mean(1)) + 1e-12))
            res = x - g * ref_al
            res_db = 10 * np.log10((float(np.sum(res ** 2)) + 1e-18) / (float(np.sum(x ** 2)) + 1e-18))
            lL, cL = xcorr_lag(x[:, 0], ref[:, 0], ml)                    # per channel: where does each channel of the render sit in the source?
            lR, cR = xcorr_lag(x[:, 1], ref[:, 1], ml)
            row = {"take": ti, "lagLR_ms": round((lL - lR) * 1000.0 / SR, 2) if min(cL, cR) > 0.8 else 0.0, "seg": (round(a, 2), round(b, 2)), "out": round(o0, 2), "lag_ms": round(lag * 1000.0 / SR, 1), "corr": round(cor, 3), "resid_db": round(res_db, 1),
                   "lr_ms": round(chan_delay(x), 2), "lr_src_ms": round(chan_delay(ref_al), 2), "echo": round(echo_score(xm), 2), "echo_src": round(echo_score(ref_al.mean(1)), 2),
                   "src": Path(sr["path"]).name}
            rows.append(row)
    return rows


def report(rows, label, log=print):
    bad = []
    for r in rows:
        if r.get("silent"):
            continue
        if "env_corr" in r:
            continue                                                      # informational only: atempo (WSOLA) reshapes the envelope, so no pass / fail on it
        if abs(r["lag_ms"]) > 50 or r["corr"] < 0.9 or abs(r["lagLR_ms"]) > 1.0 or r["echo"] > r["echo_src"] + 0.2:
            bad.append(r)
    log(f"== {label}: {len(rows)} segments measured, {len(bad)} do not match the source range")
    for r in bad:
        if "env_corr" in r:
            log(f"   take {r['take']:2d} out {r['out']:6.2f}s source {r['seg']} {r['src'][-30:]}: speed {r['speed']}x, loudness envelope correlation with the source {r['env_corr']:.2f}")
            continue
        log(f"   take {r['take']:2d} out {r['out']:6.2f}s source {r['seg']} {r['src'][-30:]}: offset {r['lag_ms']:+8.1f} ms, correlation {r['corr']:.3f}, residual {r['resid_db']:+.1f} dB, "
            f"L-R lag {r['lagLR_ms']:+.2f} ms, echo {r['echo']:.2f} (source {r['echo_src']:.2f})")
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("effects")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--unuse")
    ap.add_argument("--code")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "audio845"))
    ap.add_argument("--label", default="current")
    ap.add_argument("--song")
    ap.add_argument("--json", help="write the per-segment rows here")
    a = ap.parse_args()
    M = load_code(a.code)
    if a.unuse:
        unuse(M, a.unuse)
    cfg = M.load_config()
    cfg["effects_game"] = dict(cfg.get("effects_game") or {}, **{a.game: a.effects})
    sp = None
    if a.song:
        songs, _, _ = M.song_pool(cfg, cached_only=True)
        sp = [s for s in songs if a.song.lower() in (s["title"] + " " + s["artist"]).lower()][0]["path"]
    plan, _ = M.make_plan(cfg, a.game, None, sp, None, None, a.seed, None, None)
    print(f"plan: {len(plan['takes'])} takes, {plan['duration']:.2f} s, effects {plan.get('effects')}")
    fx = set(M.FX_ALL) | (set(M.XFX_FX) if plan.get("effects") == "extra" else set())
    inputs, graph = M.build_filter(plan, cfg, False, fx)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    wav = render_game_audio(inputs, graph, out / f"{a.label}.game.wav")
    print(f"rendered game audio {len(wav) / SR:.2f} s")
    rows = analyse(plan, wav)
    report(rows, a.label)
    if a.json:
        Path(a.json).write_text(json.dumps(rows), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
