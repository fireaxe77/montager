"""python montage.py songmapcompare [--auto N] [<song or list.txt>] [--songs-dir DIR] [--out DIR]    (V6.9.5)

Finds the songs where SONGMAP V1 and V2 disagree most and writes material to JUDGE BY EAR: side-by-side PNGs, 20 s listening clips
(original / V1 clicks / V2 clicks) around the first drop and around the most suspicious region, full-length click WAVs, report.md / report.json.
Read-only: it builds both maps in memory (never through the cache), never writes caches, flags, config or the songs folder; everything goes
to compare_out/ (git-ignored)."""
import importlib
import json
import math
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

CLIP_S = 20.0
POOL_CAP = 40
TIME_BUDGET_S = 900.0
KICK_WINDOW = 0.06


def _montage():
    m = sys.modules.get("__main__")
    if m is not None and hasattr(m, "build_song_map") and hasattr(m, "analyse_song"):
        return m
    return importlib.import_module("montage")


# ------------------------------------------------------------------------------------------------------------- analysis
def analyse_pair(M, path, csv_bpm=None):
    """(V1 map, V2 map, y, sr) built in memory only. Raises if either fails."""
    import songmap_v2
    from songmap_v2 import timebase
    v1 = M.build_song_map(str(path), csv_bpm)
    v2 = songmap_v2.build_songmap_v2(str(path), csv_bpm, deadline=time.monotonic() + max(120.0, songmap_v2.ANALYSIS_CAP_S * 2))
    y, sr = timebase.decode(str(path))
    return v1, v2, y, sr


def kick_times(v2):
    return np.array(sorted(e["raw_time"] for e in v2["v2"]["events"] if e["type"] in ("kick", "bass") and e["strength"] >= 0.5))


def offsets(beats, kicks, window=KICK_WINDOW):
    from songmap_v2 import grid
    return grid.kick_offsets(np.asarray(beats, float), kicks, window)


def eval_kicks(v1, v2, kicks):
    """The kicks both maps are judged on: every kick within 60 ms of EITHER grid. Each map's offset is then measured to ITS nearest beat
    without a window, so a grid that drifted off the kicks is not hidden by a window (a kick the grid misses counts with its real distance)."""
    k = np.asarray(kicks, float)
    if not len(k):
        return k
    keep = np.zeros(len(k), bool)
    for m in (v1, v2):
        b = np.asarray(m["beats"], float)
        j = np.clip(np.searchsorted(b, k), 1, len(b) - 1)
        d = np.minimum(np.abs(b[j] - k), np.abs(b[j - 1] - k))
        keep |= d <= KICK_WINDOW
    return k[keep]


def stats(off):
    if not len(off):
        return {"n": 0, "median_ms": None, "p95_ms": None}
    a = np.abs(off) * 1000
    return {"n": int(len(off)), "median_ms": round(float(np.median(a)), 2), "p95_ms": round(float(np.percentile(a, 95)), 2)}


def on_grid_share(m):
    """Share of the strong events (accents) that sit on the beat / subdivision grid of the map itself (same rule for V1 and V2)."""
    from songmap_v2 import events
    acc = [{"raw_time": a[0], "band": "x", "type": "accent", "strength": 1.0} for a in m.get("accents", [])]
    if not acc or len(m["beats"]) < 4:
        return None
    ev = events.associate(acc, m["beats"])
    return round(sum(1 for e in ev if e["on_grid"]) / len(ev), 3)


def drop_sections(m):
    """[(start_t, end_t)] of the sections labelled drop."""
    return [(s["start_t"], s["end_t"]) for s in m.get("sections", []) if s["label"] == "drop"]


def drop_share(m):
    return sum(b - a for a, b in drop_sections(m)) / max(1.0, float(m["dur"]))


def compare(v1, v2, name):
    from songmap_v2 import sections
    per = float(np.median(np.diff(v2["beats"])))
    bar = 4 * per
    t1 = [d["t"] for d in v1["drops"]]
    t2 = [d["t"] for d in v2["drops"]]
    near = lambda t, L: min([abs(t - x) for x in L], default=1e9)
    unmatched1 = [t for t in t1 if near(t, t2) > 2 * bar]
    unmatched2 = [t for t in t2 if near(t, t1) > 2 * bar]

    def v1_len(t):                                               # length of the drop section that contains the V1 drop
        for a, b in drop_sections(v1):
            if a - 0.5 <= t <= b:
                return b - a
        return 0.0
    short_rejected = [t for t in unmatched1 if v1_len(t) < sections.DROP_MIN_S]
    k = eval_kicks(v1, v2, kick_times(v2))
    o1, o2 = stats(offsets(v1["beats"], k, 10.0)), stats(offsets(v2["beats"], k, 10.0))
    s1, s2 = drop_share(v1), drop_share(v2)
    cap = sections.SHARE_CAP
    over1 = max(0.0, s1 - cap) / (1 - cap)
    spread = abs((o1["p95_ms"] or 0) - (o2["p95_ms"] or 0))
    score = (abs(len(t1) - len(t2)) + 1.5 * (len(unmatched1) + len(unmatched2)) + 1.5 * len(short_rejected)
             + 4.0 * over1 + min(5.0, spread / 10.0))
    sanity = lambda ts, m, sh: sum(1 for t in ts if (lambda L: L < sections.DROP_MIN_S)(next((b - a for a, b in drop_sections(m) if a - 0.5 <= t <= b), 0.0))) + (1 if sh > cap else 0)
    san1, san2 = sanity(t1, v1, s1), sanity(t2, v2, s2)
    p1, p2 = o1["p95_ms"], o2["p95_ms"]
    if p1 is not None and p2 is not None and p2 <= 0.8 * p1 and san2 <= san1:
        verdict = "V2 better"
    elif p1 is not None and p2 is not None and p1 <= 0.8 * p2 and san1 <= san2:
        verdict = "V1 better"
    else:
        verdict = "unclear"
    why = (f"kick-to-grid p95 V1 {p1} ms vs V2 {p2} ms, drops V1 {len(t1)} / V2 {len(t2)}, drop share V1 {s1:.0%} / V2 {s2:.0%}, "
           f"drop sanity problems V1 {san1} / V2 {san2}")
    return {"song": name, "bpm": v2["bpm"], "beats": len(v2["beats"]), "grid_confidence": v2["v2"]["grid_confidence"],
            "downbeat_confidence": v2["v2"]["downbeat_confidence"], "drops_v1": [round(t, 2) for t in t1], "drops_v2": [round(t, 2) for t in t2],
            "rejected_v1_drops": [round(t, 2) for t in short_rejected], "unmatched_v1": [round(t, 2) for t in unmatched1],
            "unmatched_v2": [round(t, 2) for t in unmatched2], "events_on_grid_v1": on_grid_share(v1), "events_on_grid_v2": on_grid_share(v2),
            "kick_offset_v1": o1, "kick_offset_v2": o2, "drop_share_v1": round(s1, 3), "drop_share_v2": round(s2, 3),
            "disagreement_score": round(float(score), 2), "verdict": verdict, "verdict_why": why, "bpm_v1": v1["bpm"]}


# ------------------------------------------------------------------------------------------------------------- audio material
def _tone(sr, hz, dur, amp, decay=None):
    n = int(sr * dur)
    t = np.arange(n) / sr
    env = np.exp(-t / (decay or dur / 3.0))
    return (np.sin(2 * np.pi * np.atleast_1d(hz)[:, None] * t[None, :]).sum(0) * env * amp / len(np.atleast_1d(hz))).astype(np.float32)


def clicks(m, sr, length_s, n=None):
    """Click track of a map on the render timebase: soft tick on every beat, downbeat, accent, bass hit, drop tones all differ in pitch."""
    n = int(n if n is not None else length_s * sr)
    y = np.zeros(n, np.float32)

    def put(sig, t):
        s = int(round(t * sr))
        if 0 <= s < n:
            e = min(n, s + len(sig))
            y[s:e] += sig[:e - s]
    beat_tick, down_tick = _tone(sr, 1200, 0.012, 0.18), _tone(sr, 1760, 0.03, 0.6)
    acc_tick, bass_tick = _tone(sr, 3200, 0.012, 0.45), _tone(sr, 330, 0.06, 0.7, 0.03)
    drop_tone = _tone(sr, [880, 1320, 1760], 0.4, 0.9, 0.15)
    downs = set(m["down"])
    for i, t in enumerate(m["beats"]):
        put(down_tick if i in downs else beat_tick, t)
    for t, s, bass in m.get("accents", []):
        put(bass_tick if bass else acc_tick, t)
    for d in m.get("drops", []):
        put(drop_tone, d["t"])
    return np.clip(y, -1, 1)


def write_wav(path, y, sr):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())


def clip_bounds(center, dur, length=CLIP_S):
    a = max(0.0, min(center - 8.0, dur - length))
    return a, min(dur, a + length)


def suspicious_time(res, v1, v2, kicks):
    un = [(t, 2) for t in res["unmatched_v1"]] + [(t, 2) for t in res["unmatched_v2"]]
    if un:
        return float(un[0][0])
    best, bt = -1.0, None
    for a in np.arange(0, float(v2["dur"]) - 10, 5.0):
        sel = kicks[(kicks >= a) & (kicks < a + 10)]
        if len(sel) < 4:
            continue
        d = abs(float(np.mean(np.abs(offsets(v1["beats"], sel))) if len(offsets(v1["beats"], sel)) else 0.05)
                - float(np.mean(np.abs(offsets(v2["beats"], sel))) if len(offsets(v2["beats"], sel)) else 0.05))
        if d > best:
            best, bt = d, a + 5
    return float(bt if bt is not None else float(v2["dur"]) / 2)


# ------------------------------------------------------------------------------------------------------------- plots
COL = {"intro": "#9db4d6", "verse": "#a8d5a2", "build": "#f2c46d", "drop": "#ef6f6c", "breakdown": "#b49ad8", "outro": "#9fa6ad", "bump": "#f5d0a9"}


def _lane(ax, m, title, t0=None, t1=None, grid_lines=False):
    for s in m.get("sections", []):
        ax.axvspan(s["start_t"], s["end_t"], color=COL.get(s["label"], "#ddd"), alpha=0.35, lw=0)
    downs = set(m["down"])
    for i, t in enumerate(m["beats"]):
        if t0 is not None and not (t0 <= t <= t1):
            continue
        ax.vlines(t, 0, 1.0 if i in downs else 0.45, color="#222" if i in downs else "#777", lw=1.2 if i in downs else 0.5)
        if grid_lines:
            ax.axvline(t, color="#2a6fdb", lw=0.3, alpha=0.4)
    for t, s, bass in m.get("accents", []):
        if t0 is None or t0 <= t <= t1:
            ax.plot([t], [1.15], "o", ms=3 + min(4, s / 5), mfc="#222" if bass else "none", mec="#222")
    for d in m.get("drops", []):
        ax.axvline(d["t"], color="#d00000", lw=2.5)
    ax.set_ylim(0, 1.4)
    ax.set_yticks([])
    ax.set_ylabel(title, rotation=0, ha="right", va="center")


def plot_pair(path, name, v1, v2, y, sr, window=None, title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dur = float(v2["dur"])
    t0, t1 = window if window else (0.0, dur)
    fig, axs = plt.subplots(3, 1, figsize=(18 if not window else 14, 6.5), sharex=True, gridspec_kw={"height_ratios": [2, 1.4, 1.4]})
    seg = y[int(t0 * sr):int(t1 * sr)]
    k = max(1, len(seg) // 6000)
    env = np.abs(seg[:len(seg) // k * k]).reshape(-1, k).max(1) if len(seg) >= k else np.abs(seg)
    axs[0].fill_between(np.linspace(t0, t1, len(env)), -env, env, color="#555", lw=0)
    axs[0].set_ylabel("waveform", rotation=0, ha="right", va="center")
    _lane(axs[1], v1, "V1", t0 if window else None, t1, False)
    _lane(axs[2], v2, "V2 (+grid)", t0 if window else None, t1, True)
    axs[2].set_xlim(t0, t1)
    axs[2].set_xlabel("seconds (render timebase)")
    fig.suptitle(title or name, fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=80)
    plt.close(fig)


def first_drop(m):
    return m["drops"][0]["t"] if m.get("drops") else None


# ------------------------------------------------------------------------------------------------------------- selection
def collect_songs(M, args, notes):
    """Candidate pool: songs from past montages (used songs) first, then the songs folder; read-only; capped at POOL_CAP."""
    cfg = M.load_config()
    exts = {e for e in M.AUDIO_EXT}
    pool, seen = [], set()

    def add(p, why):
        p = str(p)
        k = M._pkey(p)
        if k not in seen and Path(p).is_file() and Path(p).suffix.lower() in exts:
            seen.add(k)
            pool.append({"path": p, "why": why})
    if args.target:
        t = Path(args.target)
        if t.suffix.lower() == ".txt":
            for line in t.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    add(line.strip().strip('"'), "list")
        else:
            add(t, "given")
        return pool
    folder = args.songs_dir or cfg.get("mp3_dir")
    used = M.load_json(M.USED_SONGS, {}) if not args.songs_dir else {}
    hist = []
    for game_hist in used.values() if isinstance(used, dict) else []:
        for h in game_hist if isinstance(game_hist, list) else []:
            if h.get("path"):
                hist.append((h.get("date", ""), h["path"]))
    for d, p in sorted(hist, reverse=True):
        add(p, "used in a montage " + d)
    if not hist:
        notes.append("No used-song records available (montage_data/used_songs.json is empty or missing): candidates come from the songs folder only.")
    if folder and Path(folder).is_dir():
        for p in sorted(M.walk_files([str(folder)], exts, 0, cfg)):
            if len(pool) >= POOL_CAP:
                break
            add(p, "songs folder")
    else:
        notes.append(f"Songs folder not found ({folder!r}); use --songs-dir.")
    return pool[:POOL_CAP]


def safe(s):
    return re.sub(r"[^\w.\-]+", "_", s)[:60]


# ------------------------------------------------------------------------------------------------------------- main
def run(M, pool, n_keep, out_dir, say=print):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.time()
    results, maps = [], {}
    for i, c in enumerate(pool, 1):
        if time.time() - t_start > TIME_BUDGET_S:
            say(f"  time budget reached after {i - 1} songs")
            break
        say(f"[{i}/{len(pool)}] analysing {Path(c['path']).name} ...")
        try:
            v1, v2, y, sr = analyse_pair(M, c["path"])
            res = compare(v1, v2, Path(c["path"]).name)
            res.update(path=c["path"], why_candidate=c["why"])
            results.append(res)
            maps[c["path"]] = (v1, v2, y, sr)
            say(f"      score {res['disagreement_score']}  {res['verdict']}")
        except Exception as ex:
            say(f"      skipped ({type(ex).__name__}: {ex})")
    results.sort(key=lambda r: -r["disagreement_score"])
    top = results[:n_keep]
    for r in top:
        v1, v2, y, sr = maps[r["path"]]
        base = safe(Path(r["path"]).stem)
        files = {}
        plot_pair(out_dir / f"{base}_compare.png", r["song"], v1, v2, y, sr, None, f"{r['song']}   V1 vs V2   score {r['disagreement_score']}")
        files["png"] = f"{base}_compare.png"
        fd = first_drop(v2) if first_drop(v2) is not None else first_drop(v1)
        per = float(np.median(np.diff(v2["beats"])))
        zc = fd if fd is not None else float(v2["dur"]) / 2
        plot_pair(out_dir / f"{base}_zoom.png", r["song"], v1, v2, y, sr, (max(0.0, zc - 2 * 4 * per), zc + 6 * 4 * per),
                  f"{r['song']}   8 bars around the first drop ({zc:.1f} s)")
        files["zoom"] = f"{base}_zoom.png"
        k = kick_times(v2)
        sus = suspicious_time(r, v1, v2, k)
        for tag, center in (("firstdrop", zc), ("suspect", sus)):
            a, b = clip_bounds(center, float(v2["dur"]))
            seg = y[int(a * sr):int(b * sr)]
            write_wav(out_dir / f"{base}_{tag}_original.wav", seg, sr)
            for ver, m in (("v1", v1), ("v2", v2)):
                ck = clicks(m, sr, 0, len(y))[int(a * sr):int(b * sr)]
                write_wav(out_dir / f"{base}_{tag}_{ver}_clicks.wav", np.clip(seg * 0.7 + ck, -1, 1), sr)
            files[tag] = {"center_s": round(center, 2), "from_s": round(a, 2), "to_s": round(b, 2),
                          "files": [f"{base}_{tag}_original.wav", f"{base}_{tag}_v1_clicks.wav", f"{base}_{tag}_v2_clicks.wav"]}
        for ver, m in (("v1", v1), ("v2", v2)):
            write_wav(out_dir / f"{base}_full_{ver}_clicks.wav", clicks(m, sr, 0, len(y)), sr)
            files[f"full_{ver}"] = f"{base}_full_{ver}_clicks.wav"
        r["files"] = files
    return results, top


def write_reports(out_dir, results, top, notes):
    out_dir = Path(out_dir)
    (out_dir / "report.json").write_text(json.dumps({"notes": notes, "songs": top, "analysed": len(results)}, indent=1), encoding="utf-8")
    L = ["# SONGMAP V1 vs V2 - listening report", "", f"{len(results)} songs analysed, the {len(top)} most suspicious are listed (highest disagreement first).", ""]
    for n in notes:
        L.append(f"> {n}")
    L += ["", "## Listen to these first", ""]
    for i, r in enumerate(top[:5], 1):
        f = r["files"]
        L.append(f"{i}. **{r['song']}** (score {r['disagreement_score']}, {r['verdict']})")
        L.append(f"   - around the first drop ({f['firstdrop']['center_s']} s): `{f['firstdrop']['files'][0]}`, `{f['firstdrop']['files'][1]}`, `{f['firstdrop']['files'][2]}`")
        L.append(f"   - most suspicious region ({f['suspect']['center_s']} s): `{f['suspect']['files'][0]}`, `{f['suspect']['files'][1]}`, `{f['suspect']['files'][2]}`")
    L += ["", "Listen to the original, then the V1 clicks, then the V2 clicks: the clicks should sit exactly on the kicks / the beat. "
          "Pitches: soft high tick = beat, 1760 Hz = downbeat, 3200 Hz = accent, low 330 Hz = bass hit, three-tone chord = drop.", ""]
    for r in top:
        o1, o2 = r["kick_offset_v1"], r["kick_offset_v2"]
        L += [f"## {r['song']}", "", f"- verdict: **{r['verdict']}** - {r['verdict_why']}",
              f"- disagreement score {r['disagreement_score']}; BPM {r['bpm']} (V1 {r['bpm_v1']}); {r['beats']} beats; grid confidence {r['grid_confidence']}, downbeat confidence {r['downbeat_confidence']}",
              f"- drops V1: {r['drops_v1']}  |  V2: {r['drops_v2']}  |  V1 drops V2 rejected: {r['rejected_v1_drops']}",
              f"- kick-to-grid offset: V1 median {o1['median_ms']} ms, p95 {o1['p95_ms']} ms  |  V2 median {o2['median_ms']} ms, p95 {o2['p95_ms']} ms",
              f"- events on grid: V1 {r['events_on_grid_v1']}  |  V2 {r['events_on_grid_v2']}; share of song labelled drop: V1 {r['drop_share_v1']:.0%} / V2 {r['drop_share_v2']:.0%}",
              f"- plots: `{r['files']['png']}`, `{r['files']['zoom']}`; full click tracks: `{r['files']['full_v1']}`, `{r['files']['full_v2']}`", ""]
    (out_dir / "report.md").write_text("\n".join(L), encoding="utf-8")
    return "\n".join(L)


def main(args, say=print):
    M = _montage()
    notes = []
    out_dir = Path(args.out) if getattr(args, "out", None) else Path(M.HERE) / "compare_out"
    n = args.auto if getattr(args, "auto", None) is not None else 10
    pool = collect_songs(M, args, notes)
    if not pool:
        say("songmapcompare: no songs found. " + " ".join(notes))
        return 1
    if getattr(args, "target", None):
        n = len(pool)
    say(f"songmapcompare: {len(pool)} candidate song(s); keeping the {n} with the largest V1/V2 disagreement")
    results, top = run(M, pool, n, out_dir, say)
    text = write_reports(out_dir, results, top, notes)
    say("\n" + text)
    say(f"\nwritten to {out_dir} (report.md, report.json, PNGs, WAVs). Nothing else was changed.")
    return 0
