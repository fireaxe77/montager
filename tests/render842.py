"""V8.4.2 tool: a real render of one montage with its time and peak memory (all ffmpeg processes together), written to a scratch folder.
python tests/render842.py <game> <effects: extra|default> <outdir> [--seed N] [--song "<fragment>"] [--max-takes N] [--dry]
Plans like Auto (clips + song picked by the planner), sets the Effects mode of that game for this run only (the saved settings are not touched), prints the effect plan, renders,
prints the render time and the peak memory. The plan and the log go to <outdir>."""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import montage as M                                                                           # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("game")
    ap.add_argument("effects")
    ap.add_argument("outdir")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--song", default=None)
    ap.add_argument("--target", type=float, default=None)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--max-takes", type=int, default=0)
    ap.add_argument("--paths", default=None, help="JSON list of clip paths (like ticking those clips in Manual)")
    a = ap.parse_args()
    out_dir = Path(a.outdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = open(out_dir / "render.log", "w", encoding="utf-8", buffering=1)

    def sink(s):
        log.write(s + "\n")
        if any(k in s for k in ("EFFECTS", "SKY", "ffmpeg failed", "rendered", "CANNOT", "effect '", "TIMING", "PICK")):
            print(s[:400], flush=True)
    M.LOG_SINK[0] = sink
    cfg = M.load_config()
    cfg["effects_game"] = dict(cfg["effects_game"], **{a.game: a.effects})
    song_path = None
    if a.song:
        songs, _, _ = M.song_pool(cfg, cached_only=True)
        m = [s for s in songs if a.song.lower() in (s["title"] + " " + s["artist"]).lower()]
        if not m:
            raise SystemExit(f"song '{a.song}' not found")
        song_path = m[0]["path"]
    paths = json.load(open(a.paths, encoding="utf-8")) if a.paths else None
    plan, text = M.make_plan(cfg, a.game, paths, song_path, a.target, None, a.seed, None, None)
    (out_dir / "plan.txt").write_text(text, encoding="utf-8")
    print(f"PLAN {a.game}/{a.effects}: {len(plan['takes'])} takes, {plan['duration']:.1f} s, song {plan['pick']['title']}, style {plan['pick']['style']}, seed {plan['seed']}, effects {plan.get('effects', 'default')}", flush=True)
    for n in plan["notes"]:
        if n.startswith("EFFECTS"):
            print(n, flush=True)
    json.dump(plan, open(out_dir / "plan.json", "w", encoding="utf-8"), default=str)
    if a.dry:
        return 0
    if a.max_takes:
        plan = dict(plan, takes=plan["takes"][:a.max_takes])
        tf = plan["takes"][-1]["f0"] + plan["takes"][-1]["nf"]
        plan["duration"], plan["total_frames"] = tf / 60.0, tf
        plan["song"] = dict(plan["song"], fade_out_start=max(0.0, tf / 60.0 - 1.0))
    import psutil
    peak = [0, 0]
    stop = threading.Event()

    def watch():
        me = psutil.Process()
        while not stop.is_set():
            try:
                tot = sum(p.memory_info().rss for p in me.children(recursive=True) if "ffmpeg" in p.name().lower())
                peak[0] = max(peak[0], tot)
                peak[1] = max(peak[1], me.memory_info().rss)
            except Exception:
                pass
            time.sleep(0.5)
    th = threading.Thread(target=watch, daemon=True)
    th.start()
    outf = out_dir / f"{a.game}_{a.effects}.mp4"
    t0 = time.time()
    try:
        M.render_plan(plan, outf, cfg, False, False, None, True)
        ok = outf.exists()
    except Exception as ex:                                                                   # noqa: BLE001
        print("RENDER ERROR:", ex, flush=True)
        ok = False
    dt = time.time() - t0
    stop.set()
    print(f"RESULT {a.game}/{a.effects}: {'OK' if ok else 'FAILED'} render {dt:.0f} s for {plan['duration']:.0f} s of video, peak ffmpeg memory {peak[0] / 2 ** 30:.2f} GB, python {peak[1] / 2 ** 30:.2f} GB, fx failed: {plan.get('fx_failed')}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
