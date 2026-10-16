"""V8.4.5 tool: the length of every take's game-audio chain [t<i>a] of a plan's graph (one ffmpeg run, one wav per take) against the take's planned length; names the takes that are short / long.
python tests/audiolen845.py <game> <extra|default> --seed N [--code DIR]   (MONTAGER_DATA / the rewound data copy as for audio845)"""
import argparse
import sys
import tempfile
from pathlib import Path

import audio845 as A

SR = A.SR


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("effects")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--code")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "audiolen845"))
    a = ap.parse_args()
    M = A.load_code(a.code)
    cfg = M.load_config()
    cfg["effects_game"] = dict(cfg.get("effects_game") or {}, **{a.game: a.effects})
    plan, _ = M.make_plan(cfg, a.game, None, None, None, None, a.seed, None, None)
    fx = set(M.FX_ALL) | (set(M.XFX_FX) if plan.get("effects") == "extra" else set())
    inputs, graph = M.build_filter(plan, cfg, False, fx)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    n = len(plan["takes"])
    # one chain set that feeds all [t<i>a]
    sub = ";".join(A.audio_subgraph(graph, f"t{i}a") for i in range(n))
    parts = []
    seen = set()
    for p in sub.split(";"):
        if p not in seen:
            seen.add(p)
            parts.append(p)
    fs = out / "len.filter.txt"
    fs.write_text(";".join(parts), encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error"] + inputs + ["-filter_complex_script", str(fs)]
    for i in range(n):
        cmd += ["-map", f"[t{i}a]", "-c:a", "pcm_f32le", str(out / f"t{i}.wav")]
    import subprocess
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode:
        print(r.stderr.decode("utf-8", "ignore")[-800:])
        return 1
    tot = 0.0
    for i, t in enumerate(plan["takes"]):
        w = A.read_wav(out / f"t{i}.wav")
        d = len(w) / SR
        tot += d
        flag = "" if abs(d - t["dur"]) < 0.02 else "   <-- DOES NOT MATCH"
        print(f"take {i + 1:2d}: planned {t['dur']:6.3f} s ({t['nf']} frames), audio {d:6.3f} s, diff {d - t['dur']:+.3f} s, srcs {len(t.get('srcs') or [1])}, speeds {sorted({round(s[2], 2) for s in t['segs']})}{flag}")
    print(f"total planned {plan['duration']:.3f} s, audio {tot:.3f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
