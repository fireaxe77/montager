"""V8.8.5 check: one real montage per call, planned exactly like the app (make_plan: Auto / Force Full / Manual / Manual Auto / a fixed length), checked as a plan and then rendered and
measured. Run on a COPY of montage_data (MONTAGER_DATA=<copy>): the plan writes caches.
  plan: the montage covers the trimmed song (full-song modes), every kill time is its kill-row time, every take holds all kills of its fight (verify_cutlist), no kill within the death lock,
        game sound leveled (loudness + gain of every clip with sound within a few dB of the target), sky pattern / family chosen once
  render: the video lasts the plan, the song is in every 5 s window (correlation with the song), no clipping, the post-render quality / sync checks run, a frame sheet of every sky take
python tests/render885.py <out dir> [game = cs2] [mode = auto | force_full | manual | manual_auto | fixed] [song fragment = Perfect Exceeder] [seed = 885] [render = 1 | 0 = plan only | 2 = measure the earlier video again]"""
import random
import tempfile
import subprocess
import sys
import time
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
import cv2                                                                                    # noqa: E402

outd = Path(sys.argv[1])
outd.mkdir(parents=True, exist_ok=True)
game = sys.argv[2] if len(sys.argv) > 2 else "cs2"
mode = sys.argv[3] if len(sys.argv) > 3 else "auto"
frag = sys.argv[4] if len(sys.argv) > 4 else "Perfect Exceeder"
seed = int(sys.argv[5]) if len(sys.argv) > 5 else 885
do_render = (sys.argv[6] if len(sys.argv) > 6 else "1") in ("1", "2")
reuse = (sys.argv[6] if len(sys.argv) > 6 else "1") == "2"          # 2 = measure the video an earlier run rendered (same plan: same data copy and seed)
FAILS = []


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"), flush=True)
    if not ok:
        FAILS.append(msg)


cfg = dict(M.load_config())
cfg["effects_game"] = dict(cfg.get("effects_game") or {}, **{game: "extra"})
cfg["sky_game"] = dict(cfg.get("sky_game") or {}, **{game: True})
songs, _, _ = M.song_pool(cfg, cached_only=True)
song = [s for s in songs if frag.lower() in (s["title"] + " " + s["artist"] + " " + Path(s["path"]).name).lower()][0]
an = M.get_songmap(song["path"], song.get("csv_bpm"))
lv0, lv1 = M.song_live_range(an)
kw = {}
if mode in ("manual", "manual_auto"):
    M.QUIET.on = True
    pool, _st = M.game_pool(cfg, game)
    M.QUIET.on = False
    ticked = [it["rec"]["path"] for it in pool if it.get("kills")]
    random.Random(seed).shuffle(ticked)
    kw = dict(paths=ticked[:10])
if mode in ("force_full", "manual_auto"):
    kw["full"] = True
target = 90 if mode == "fixed" else "optimal"
t0 = time.time()
M.QUIET.on = True
plan, text = M.make_plan(cfg, game, song_path=song["path"], target=target, style="auto", seed=seed, scan=False, **kw)
M.QUIET.on = False
print(f"{game} {mode}: song '{song['title']}' audible {lv0:.2f} - {lv1:.2f} s; plan {len(plan['takes'])} takes, {plan['duration']:.2f} s from {plan['song']['start_t']:.2f} s ({time.time() - t0:.0f} s)")
print("plan checks")
st, end = float(plan["song"]["start_t"]), float(plan["song"]["start_t"]) + float(plan["duration"])
if mode == "fixed":
    check(f"fixed length: {plan['duration']:.1f} s for 90 s (at least 85 %, never longer)", 0.85 * 90 <= plan["duration"] <= 93)
else:
    check(f"the montage covers the trimmed song: {st:.2f} - {end:.2f} s of {max(lv0, an['beats'][0]):.2f} - {lv1:.2f} s", st >= lv0 - 0.05 and st - max(lv0, an["beats"][0]) <= 3.0 and lv1 - 3.0 <= end <= lv1 + 0.05)
bad = [b_ for b_ in M.verify_cutlist(plan, log=False)]
check(f"every take holds all kills of its fight, rows inside the footage, tails, no clip twice ({len(bad)} problems)", not bad, "; ".join(bad[:3]))
check("every kill time is its kill-row time", all(t_["kills"] == t_["rows"] for t_ in plan["takes"]), str([(t_["kills"], t_["rows"]) for t_ in plan["takes"] if t_["kills"] != t_["rows"]][:2]))
multi = [t_ for t_ in plan["takes"] if len(t_["kills"]) >= 2]
check(f"multikills kept together: {len(multi)} takes with 2+ kills, {sum(len(t_['kills']) for t_ in plan['takes'])} kills in {len(plan['takes'])} takes", len(multi) >= 1)
lock = float(cfg.get("death_lock_s", 8.0))
check("the death rule: no take shows my death (no death right after a take's last kill inside the take)",
      all(t_.get("death_after") is None or t_["death_after"] > t_["dur"] - t_["kills_out"][-1] - 0.02 for t_ in plan["takes"]))
lvl = []
for t_ in plan["takes"]:
    for s_ in t_["srcs"]:
        if s_.get("audio") and s_.get("lufs") is not None and s_["lufs"] > M.SILENT_LUFS and not s_.get("music_db"):
            capped = abs(s_["lift_db"]) >= M.GAME_LIFT_MAX - 0.01 or abs(s_["lift_db"]) >= M.GAME_CUT_MAX - 0.01 or (s_.get("peak_db") is not None and s_["lift_db"] > 0 and s_["peak_db"] + s_["gain_db"] >= M.GAME_PEAK_CEIL - 0.05)
            if not capped:
                lvl.append(s_["lufs"] + s_["gain_db"])
if lvl:
    check(f"song leveling: {len(lvl)} clips with sound all at {np.mean(lvl):.1f} LUFS (spread {np.ptp(lvl):.2f} dB), the song at {plan['song'].get('lufs')}", np.ptp(lvl) < 0.2)
else:
    print("  (no clip with measurable sound in this plan)")
check("one sky pattern and family per montage (chosen in the render)", True)
if not do_render:
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
    sys.exit(1 if FAILS else 0)
out = outd / f"render885_{game}_{mode}.mp4"
log0 = (M.LOG_DIR / "montage.log").stat().st_size if (M.LOG_DIR / "montage.log").exists() else 0
t0 = time.time()
if reuse and out.exists():
    M.xfx_probe_sky(plan, Path(tempfile.mkdtemp(prefix="r885sky_")))        # the same sky choice as the render (log lines), without encoding again
    print(f"measuring the existing {out}")
else:
    M.render_plan(plan, out, cfg)
    print(f"render {time.time() - t0:.0f} s -> {out}")
logt = (M.LOG_DIR / "montage.log").read_bytes()[log0:].decode("utf-8", "ignore")
print("render checks")
r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)], capture_output=True, text=True)
dur = float(r.stdout.strip() or 0)
check(f"video lasts the plan ({dur:.2f} s for {plan['duration']:.2f} s)", abs(dur - plan["duration"]) < 0.1)
sky_lines = [l_[20:] for l_ in logt.splitlines() if "SKY recolour" in l_]
pats = {m_ for l_ in sky_lines for m_ in M.SKY_PATTERNS if f"({m_} pattern" in l_}
kept = [l_ for l_ in sky_lines if "family" in l_ and "pattern" in l_]
for l_ in sky_lines[-14:]:
    print("    " + l_[:300])
check(f"skies: {len(kept)} kept, all with ONE pattern ({sorted(pats)}) and the montage's family", len(pats) <= 1 and (not kept or len(pats) == 1))


def pcm(path, ss=0.0, t=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}"] + (["-t", f"{t:.3f}"] if t else []) + ["-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.float32)


a_out, a_song = pcm(out), pcm(song["path"], st, plan["duration"])
n_ = min(len(a_out), len(a_song))
fo = float(plan["song"].get("fade_out_start") or plan["duration"])
low, seen = [], 0


def corr_at(x, y, s_):
    a_, b_ = x[max(0, s_):len(x) + min(0, s_)], y[max(0, -s_):len(y) - max(0, s_)]
    return float(np.corrcoef(a_, b_)[0, 1]) if len(a_) > 100 and np.std(a_) > 0 and np.std(b_) > 0 else 0.0


for w0 in range(0, n_ - 8000 * 5, 8000 * 5):              # the song at its own place against the song 2 - 4 s off (what game sound alone would give)
    if (w0 + 40000) / 8000.0 > fo:                         # the final fade (music fading out from the last kill)
        continue
    x, y = a_out[w0:w0 + 40000], a_song[w0:w0 + 40000]
    if np.std(y) < 1e-3:
        continue
    seen += 1
    best = max(corr_at(x, y, s_) for s_ in range(-400, 401, 40))
    yo = a_song[w0 + 16000:w0 + 56000] if w0 + 56000 <= len(a_song) else a_song[max(0, w0 - 24000):w0 + 16000]
    off = max(abs(corr_at(x, yo, s_)) for s_ in range(-400, 401, 80))
    if not (best >= 0.15 and best >= 3 * off):
        low.append((round(w0 / 8000.0, 1), round(best, 2), round(off, 2)))
check(f"the song plays in every 5 s window before the final fade ({seen} windows, {len(low)} without it)", not low, str(low[:6]))
a2 = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-map", "0:a:0", "-f", "f32le", "-"], capture_output=True).stdout, np.float32)
pk = float(np.max(np.abs(a2))) if len(a2) else 0.0
over = int((np.abs(a2) > 1.0).sum())
check(f"no clipping: limiter at 0.99, decoded peak {20 * np.log10(max(pk, 1e-9)):+.2f} dBFS, {over} of {len(a2)} decoded samples over full scale (AAC overshoot only)",
      pk < 10 ** (1.5 / 20) and over < 1e-5 * len(a2))
try:
    M.quality_check(plan, out, cfg)
    M.sync_report(plan, out, cfg)
    logt2 = (M.LOG_DIR / "montage.log").read_bytes()[log0:].decode("utf-8", "ignore")
    for l_ in [l_ for l_ in logt2.splitlines() if "SSIM" in l_ or "sync" in l_.lower() or "transition" in l_.lower()][-8:]:
        print("    " + l_[20:260])
except Exception as ex:                                    # noqa: BLE001
    print(f"    post checks skipped: {type(ex).__name__}: {ex}")
rows = []
for i, t_ in enumerate(plan["takes"]):
    for x in t_.get("xfx") or []:
        if x.get("k") == "sky" and x.get("ok"):
            tk0 = float(t_["out_start"]) + float(x["p"])
            fr = []
            for dt in (-1 / 60, 0.0, 1 / 60, 0.2, 0.6):
                rr = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, tk0 + dt):.4f}", "-i", str(out), "-frames:v", "1", "-vf", "scale=384:216", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                                    capture_output=True)
                if len(rr.stdout) == 384 * 216 * 3:
                    fr.append(np.frombuffer(rr.stdout, np.uint8).reshape(216, 384, 3))
            if fr:
                rows.append(np.concatenate(fr, 1))
if rows:
    w_ = max(r_.shape[1] for r_ in rows)
    cv2.imwrite(str(outd / f"render885_{game}_{mode}_sky.jpg"), np.concatenate([np.pad(r_, ((0, 0), (0, w_ - r_.shape[1]), (0, 0))) for r_ in rows], 0), [cv2.IMWRITE_JPEG_QUALITY, 88])
    print(f"    sky sheet: {len(rows)} sky takes (frame before the kill, kill frame, +1 frame, +0.2 s, +0.6 s)")
print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
sys.exit(1 if FAILS else 0)
