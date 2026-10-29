"""timing run: python timing.py <label> <on|off>  (on = V9.3.1 speed-ups, off = V9.3.0 behaviour); MONTAGER_DATA = a fresh COPY"""
import os, sys, time, warnings, re
sys.path.insert(0, os.getcwd())
warnings.simplefilter("ignore")
import montage as M
label, mode = sys.argv[1], sys.argv[2]
M.HEAVY_FIRST[0] = M.AUDIO_PREFETCH[0] = (mode == "on")
cfg = M.load_config()
cfg["effects_game"] = dict(cfg.get("effects_game") or {}, cs2="extra")
songs, _, _ = M.song_pool(cfg, cached_only=True)
sp = [s for s in songs if "fan service" in (s["title"] + " " + s["artist"] + " " + M.Path(s["path"]).name).lower()][0]["path"]
out = M.Path(r"E:\Movies\Montages\_timing931") / f"{label}.mp4"
out.parent.mkdir(parents=True, exist_ok=True)
t0 = time.time()
M.quiet_job(M.run_job)("cs2", mode="render", seed=7, song_path=sp, outfile=out)
print("TOTAL %s %.1f s" % (label, time.time() - t0), flush=True)
