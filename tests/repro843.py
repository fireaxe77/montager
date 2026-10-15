"""V8.4.3 tool: build one plan (seed/song/game) and run ffmpeg on its EXTRA graph directly; keeps the FIRST failure's stderr, graph and command in <outdir>.
python tests/repro843.py <game> <extra|default> <outdir> --seed N --song "<fragment>" [--no <fx,...>]"""
import argparse, subprocess, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import montage as M                                                                           # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game"); ap.add_argument("effects"); ap.add_argument("outdir")
    ap.add_argument("--seed", type=int); ap.add_argument("--song"); ap.add_argument("--no", default="")
    ap.add_argument("--nvenc", default="1"); ap.add_argument("--max-takes", type=int, default=0); ap.add_argument("--first", type=int, default=0); ap.add_argument("--null", action="store_true")
    a = ap.parse_args()
    od = Path(a.outdir); od.mkdir(parents=True, exist_ok=True)
    cfg = M.load_config()
    cfg["effects_game"] = dict(cfg["effects_game"], **{a.game: a.effects})
    songs, _, _ = M.song_pool(cfg, cached_only=True)
    sp = [s for s in songs if a.song.lower() in (s["title"] + " " + s["artist"]).lower()][0]["path"]
    plan, text = M.make_plan(cfg, a.game, None, sp, None, None, a.seed, None, None)
    if a.max_takes:
        plan = dict(plan, takes=plan["takes"][:a.max_takes])
        tf = plan["takes"][-1]["f0"] + plan["takes"][-1]["nf"]
        plan["duration"], plan["total_frames"] = tf / 60.0, tf
        plan["song"] = dict(plan["song"], fade_out_start=max(0.0, tf / 60.0 - 1.0))
    M.xfx_probe_sky(plan) if plan.get("effects") == "extra" else None
    fx = set(M.FX_ALL) | (set(M.XFX_FX) if plan.get("effects") == "extra" else set())
    fx -= set(x for x in a.no.split(",") if x)
    inputs, graph = M.build_filter(plan, cfg, False, fx)
    gp = od / "graph.txt"; gp.write_text(graph, encoding="utf-8")
    (od / "inputs.txt").write_text("\n".join(map(str, inputs)), encoding="utf-8")
    D = plan["duration"]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "warning", "-nostats", "-progress", "pipe:1"] + inputs + ["-filter_complex_script", str(gp), "-map", "[vout]", "-map", "[aout]", "-t", f"{D:.4f}"] + \
          (M.enc_args(False, False, a.nvenc == "1") if not a.null else ["-c:v", "rawvideo", "-c:a", "pcm_s16le"]) + ([str(od / "out.mp4")] if not a.null else ["-f", "null", "-"])
    (od / "cmd.txt").write_text(" ".join(f'"{c}"' for c in cmd), encoding="utf-8")
    t0 = time.time(); last = ""
    with open(od / "stderr.txt", "w", encoding="utf-8") as ef:
        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ef, text=True)
        for line in pr.stdout:
            if line.startswith("out_time="): last = line.strip()
        pr.wait()
    print("rc", pr.returncode, last, f"{time.time()-t0:.0f}s of plan {D:.1f}s", flush=True)
    return pr.returncode

if __name__ == "__main__":
    sys.exit(main())
