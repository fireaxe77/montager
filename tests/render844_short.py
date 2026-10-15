"""V8.4.4 tool: a SHORT real render (4 s) through render_plan / build_filter with the EXTRA flash + sky recolour on a real clip, from a dry plan's take structure.
python tests/render844_short.py <clip> <source kill time s> <game> <out.mp4> [sky colour]
Writes the 4 s mp4 and prints the log lines (sky probe, render, one attempt)."""
import copy
import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
ROOT = _root.find_root()
sys.path.insert(0, str(ROOT))
import montage as M                                                                           # noqa: E402


def main(clip, kt, game, outf, colour="red"):
    kt = float(kt)
    game_name = {"cs2": "CS2", "valorant": "Valorant", "r6s": "R6S"}[game]
    dry = sorted(glob.glob(str(ROOT / "montage_data" / "plans" / f"{game_name}_*.dry.json")))[0]
    plan = json.load(open(dry, encoding="utf-8"))
    t = copy.deepcopy(plan["takes"][0])
    import subprocess
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(clip)], capture_output=True, text=True)
    wh = [int(v) for v in pr.stdout.strip().split(",")[:2]]
    a = max(0.0, kt - 1.5)
    t.update({"path": clip, "rect": [0, 0, *wh], "wh": wh, "segs": [[a, a + 4.0, 1.0, 240, 0]], "kills": [kt], "kills_out": [kt - a], "rows_out": [kt - a + 0.1], "out_start": 0.0, "f0": 0,
              "nf": 240, "dur": 4.0, "pulses": [], "ramp": 1.0, "trans": "hard", "role": "headline", "unsure": [False], "audio": False, "rows": [kt + 0.1], "beat0": 0, "beat_end": 8, "ending": True, "n": 1, "slow": False})
    t["srcs"] = [{"path": clip, "shift": 0.0, "rect": [0, 0, *wh], "wh": wh, "audio": False, "a_stream": 0, "gain_db": -6.0}]
    p = kt - a
    t["xfx"] = [{"k": "flash", "p": round(p, 4), "a": 0.5, "t1": M.XFX_FLASH_S}, {"k": "sky", "p": round(p, 4), "t0": round(p - M.XFX_SKY_IN, 4), "t1": round(p + M.XFX_SKY_OUT, 4), "hue": colour, "ok": None, "gp": 0.0}]
    plan.update({"takes": [t], "duration": 4.0, "total_frames": 240, "effects": "extra", "xfx_sky_max": 1, "xfx_sky_hue": {"name": colour, "rgb": M.SKY_PALETTE[colour], "why": "tool"},
                 "xfx_zone": [0.72, 0.0, 1.0, 0.12]})
    import tempfile
    song = Path(tempfile.gettempdir()) / "render844_song.mp3"
    if not song.exists():
        M.synth_song(song, 128.0)                                   # the dry plan's own song file is not on every machine: a synthetic one stands in (only the audio differs)
    plan["song"] = dict(plan["song"], path=str(song), fade_out_start=3.0, start_t=0.0)
    cfg = dict(M.DEFAULT_CONFIG)
    cfg["interpolate_low_fps"] = False
    res = M.render_plan(plan, outf, cfg, preview=False, encoder="fast", effects=True)
    print("rendered", res)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
