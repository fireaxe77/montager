"""V8.8.6 check (real clips, audio only): does the drop moment lower the music? The montage's own audio graph (build_filter, [aout] and every chain it needs; no video) is rendered
twice for a saved plan - with the drop effect and without it ('drop' left out of the effect switches) - and in both the music's gain over time is measured: per 100 ms window the
projection of the montage audio onto the clean song (same start), relative to the montage's median. The drop effect must not lower the music: over the first 0.5 s within 0.3 dB of the same render without the drop
effect, and no 100 ms window more than 0.5 dB deeper. For context it prints how the music sits after every kill (the gunshots alone meeting the safety limiter). Writes nothing into montage_data except the usual caches; run on a COPY (MONTAGER_DATA=<copy>).
python tests/dropaudio886.py <plan.json> [<plan.json> ...]"""
import json
import re
import subprocess
import sys
import tempfile
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

SR = 16000
LAB = re.compile(r"\[([^\]]+)\]")


def audio_graph(plan, fx):
    """(inputs, graph text) of the montage's audio only: [aout] and the chains it needs."""
    inputs, graph = M.build_filter(plan, {}, False, fx)
    chains = [c.strip() for c in graph.split(";") if c.strip()]
    outs = {}
    for i, c in enumerate(chains):
        m = re.search(r"((?:\[[^\]]+\])+)$", c)
        for lab in LAB.findall(m.group(1)) if m else []:
            outs[lab] = i
    need, todo = set(), ["aout"]
    while todo:
        lab = todo.pop()
        i = outs.get(lab)
        if i is None or i in need:
            continue
        need.add(i)
        c = chains[i]
        m = re.match(r"((?:\[[^\]]+\])+)", c)
        todo += LAB.findall(m.group(1)) if m else []
    return inputs, ";\n".join(chains[i] for i in sorted(need))


def render_audio(plan, fx, path):
    inputs, g = audio_graph(plan, fx)
    gp = Path(tempfile.mkstemp(suffix=".txt")[1])
    gp.write_text(g, encoding="utf-8")
    r = subprocess.run(["ffmpeg", "-y", "-v", "error"] + inputs + ["-filter_complex_script", str(gp), "-map", "[aout]", "-c:a", "pcm_f32le", str(path)], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[-500:])


def pcm(path, ss=0.0, t=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{ss:.4f}"] + (["-t", f"{t:.3f}"] if t else []) + ["-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.float32)


def music_gain(audio_path, plan):
    r = pcm(audio_path)
    s = pcm(plan["song"]["path"], float(plan["song"]["start_t"]), float(plan["duration"]))
    n = min(len(r), len(s))
    w = int(0.1 * SR)
    g = []
    for i in range(0, n - w, w):
        a, b = r[i:i + w], s[i:i + w]
        e = float(np.dot(b, b))
        g.append(20 * np.log10(max(1e-6, float(np.dot(a, b)) / e)) if e > 1e-4 else np.nan)
    g = np.array(g)
    return g - float(np.nanmedian(g))


def main():
    fails = 0
    for pp in sys.argv[1:]:
        plan = json.load(open(pp, encoding="utf-8"))
        for t in plan["takes"]:
            t["xfx"] = [x for x in (t.get("xfx") or []) if x.get("k") != "sky"]        # audio only: the sky needs mask files that are not kept
        fx_all = tuple(M.FX_ALL) + (tuple(M.XFX_FX) if plan.get("effects") == "extra" else ())
        tmp = Path(tempfile.mkdtemp(prefix="dropaudio886_"))
        res = {}
        for kind, fx in (("with the drop effect", fx_all), ("without it", tuple(f for f in fx_all if f != "drop"))):
            ap = tmp / f"{len(res)}.wav"
            render_audio(plan, fx, ap)
            res[kind] = music_gain(ap, plan)
        ko = [float(t["out_start"]) + float(k) for t in plan["takes"] for k in (t.get("kills_out") or [])]
        b_ = res["without it"]
        kd = [float(np.nanmean(b_[int(k / 0.1):int(k / 0.1) + 5])) for k in ko if int(k / 0.1) + 5 < len(b_)]
        print(Path(pp).name, f"(every kill, no drop effect: music over the first 0.5 s after a kill median {np.median(kd):+.2f} dB, 10 % of kills under {np.percentile(kd, 10):+.2f} dB: the gunshots meeting the limiter)")
        for d in plan.get("xfx_drop") or []:
            i = int(float(d["t"]) / 0.1)
            line = []
            for kind, g in res.items():
                at, mn = float(np.nanmean(g[i:i + 5])), float(np.nanmin(g[max(0, i - 10):i + 15]))
                line.append(f"{kind}: first 0.5 s {at:+.2f} dB, lowest 100 ms in -1..+1.5 s {mn:+.2f} dB")
            a = res["with the drop effect"]
            b = res["without it"]
            ok = float(np.nanmean(a[i:i + 5])) >= float(np.nanmean(b[i:i + 5])) - 0.3 and float(np.nanmin(a[max(0, i - 10):i + 15])) >= float(np.nanmin(b[max(0, i - 10):i + 15])) - 0.5
            fails += not ok
            print(("  ok   " if ok else "  FAIL ") + f"drop {float(d['t']):7.2f} s: " + " | ".join(line))
    print("\nall drops keep the music level" if not fails else f"\n{fails} drop(s) lower the music")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
