"""V7.7.1 loudness tool (read-only on the real data; run it on a COPY of montage_data via MONTAGER_DATA).
  python tests/loud771.py plan  <out.json> <game> [song_substring]   : the real planner on a fixed selection (PB.take_sets), plan saved as JSON
  python tests/loud771.py meas  <plan.json> <out.json>               : with the montage.py of MONTAGER_ROOT (default: this repo), the ONE filter graph of the plan is run
        with the final mix split: game stream (before the mix) and music bed (before the mix) are written as wav and measured per take (integrated LUFS over the
        take's own time range, and the plain RMS dBFS). Also writes the md5 of the filter graph, so two versions can be compared byte for byte."""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(os.environ.get("MONTAGER_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402


def lufs_of(path, ss, t):
    r = subprocess.run(["ffmpeg", "-nostats", "-v", "info", "-ss", f"{ss:.3f}", "-t", f"{t:.3f}", "-i", str(path), "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.findall(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", r.stderr)
    return float(m[-1]) if m and m[-1] != "-inf" else None


def rms_db(path, ss, t):
    r = subprocess.run(["ffmpeg", "-nostats", "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{t:.3f}", "-i", str(path), "-f", "f32le", "-ac", "1", "-"], capture_output=True)
    y = np.frombuffer(r.stdout, np.float32)
    return None if len(y) == 0 else round(20 * np.log10(float(np.sqrt(np.mean(np.square(y)))) + 1e-12), 2)


def measure(plan, cfg, tag=""):
    """Per-take game / music levels of plan (see the module doc)."""
    inputs, graph = M.build_filter(plan, cfg, True)
    res = {"version": M.APP_VERSION, "graph_md5": hashlib.md5(graph.encode()).hexdigest(), "inputs_md5": hashlib.md5(" ".join(map(str, inputs)).encode()).hexdigest(),
           "game_audio_level": cfg.get("game_audio_level"), "audio_mode": cfg.get("audio_mode")}
    chains = graph.split(";\n")
    assert "[aout]" in chains[-1], chains[-1][-120:]
    chains[-1] = "[sg]anull[outm];[gh]anull[outg]"
    tmp = Path(tempfile.mkdtemp(prefix="loud771_"))
    gw, mw, gf = tmp / "game.wav", tmp / "music.wav", tmp / "graph.txt"
    gf.write_text(";\n".join(chains), encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-nostats", "-v", "error", *inputs, "-filter_complex_script", str(gf), "-map", "[outg]", "-c:a", "pcm_f32le", str(gw),
           "-map", "[outm]", "-c:a", "pcm_f32le", str(mw), "-map", "[vout]", "-an", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise RuntimeError(r.stderr[-1500:])
    takes = []
    for i, t in enumerate(plan["takes"], 1):
        ss, du = float(t["out_start"]), float(t["dur"])
        takes.append({"take": i, "clip": Path(t["path"]).name, "gain_db": [s["gain_db"] for s in t["srcs"]], "game_lufs": lufs_of(gw, ss, du), "game_rms": rms_db(gw, ss, du),
                      "music_lufs": lufs_of(mw, ss, du), "music_rms": rms_db(mw, ss, du)})
    res["takes"] = takes
    res["total_game_lufs"] = lufs_of(gw, 0, plan["duration"])
    res["total_music_lufs"] = lufs_of(mw, 0, plan["duration"])
    for f_ in (gw, mw, gf):
        f_.unlink(missing_ok=True)
    return res


def main():
    mode = sys.argv[1]
    if mode == "plan":
        from songmap_v2 import planbench as PB
        out_json, game = sys.argv[2], sys.argv[3]
        sub = sys.argv[4] if len(sys.argv) > 4 else "Silicon XX"
        sets = PB.take_sets(M)
        g, paths = sets["val7"] if game == "valorant" else ("cs2", sets["cs2trio"][1] + sets["cs2singles"][1])
        song = next(x["path"] for x in M.song_pool(M.load_config())[0] if sub in str(x["path"]))
        plan, _ = PB.run_plan(M, g, paths, song, "v2")
        Path(out_json).write_text(json.dumps(plan, indent=1, default=str), encoding="utf-8")
        print(f"{game}: {len(plan['takes'])} takes, {plan['duration']:.1f} s, song {plan['song']['title']}")
        return
    plan = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    res = measure(plan, M.load_config())
    Path(sys.argv[3]).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"{M.APP_VERSION}: graph {res['graph_md5']}  game {res['total_game_lufs']} LUFS  music {res['total_music_lufs']} LUFS  ({len(res['takes'])} takes)")


if __name__ == "__main__":
    main()
