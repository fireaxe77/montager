"""V8.8.5 check (real clips, no montage render): the sky mask never shows where the picture has no sky. For real sky takes of one game it makes the take's sky mask twice - the V8.8.4 way
(source frames grabbed by time, plan=None) and the V8.8.5 way (the render's own frames, shot-aware, guarded) - and compares every mask frame with the sky of the very picture the render shows
on that output frame (sky_take_frames + the per-frame eyedropper, grown by GROW mask pixels for the soft edge). Leak = painted pixels (mask > 25 %) outside that sky, as a share of the picture.
Also: the frame before the kill frame is never painted. Run on a COPY of montage_data (MONTAGER_DATA=<copy>).
python tests/skymask885.py [game = valorant] [takes = 4] [song fragment = Perfect Exceeder] [out dir = none: a frame sheet of the worst frames]"""
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
import cv2                                                                                    # noqa: E402

game = sys.argv[1] if len(sys.argv) > 1 else "valorant"
n_takes = int(sys.argv[2]) if len(sys.argv) > 2 else 4
frag = sys.argv[3] if len(sys.argv) > 3 else "Perfect Exceeder"
outd = Path(sys.argv[4]) if len(sys.argv) > 4 else None
GROW = 3
RGROW = 6
LEAK_MAX = 0.002                                           # a leak of more than 0.2 % of the picture on one frame counts as a pop-in

cfg = dict(M.load_config())
cfg["effects_game"] = dict(cfg.get("effects_game") or {}, **{game: "extra"})
cfg["sky_game"] = dict(cfg.get("sky_game") or {}, **{game: True})
M.QUIET.on = True
pool, _st = M.game_pool(cfg, game)
M.QUIET.on = False
sky = []
for it in sorted(pool, key=lambda it: (-len(it["kills"]), it["rec"]["path"])):
    if len(sky) >= n_takes * 3 or not it["kills"]:
        continue
    ev = {"path": it["rec"]["path"], "rec": it["rec"], "times": [max(float(k["t"]) for k in it["kills"])]}
    try:
        if M.sky_clear(M.event_sky_cov(ev, cfg)):
            sky.append(it["rec"]["path"])
    except Exception:                                      # noqa: BLE001
        pass
songs, _, _ = M.song_pool(cfg, cached_only=True)
song = [s for s in songs if frag.lower() in (s["title"] + " " + Path(s["path"]).name).lower()][0]
M.song_fill_target = lambda *a, **k: None
plan, _text = M.make_plan(cfg, game, sky, song["path"], "optimal", "hype", 885, None, None, scan=False)
zone = plan.get("xfx_zone")

def rtruth(tr):
    """the render check allows the mask's soft edge (feather + the bicubic scale-up): RGROW more mask pixels."""
    return cv2.dilate(tr.astype(np.uint8), np.ones((2 * RGROW + 1, 2 * RGROW + 1), np.uint8)) > 0


_OLD = {}


def old_sky_chain():
    """the V8.8.4 sky chain (push + shake applied to the masked layer), from the v8.8.4 tag."""
    if not _OLD:
        import subprocess
        src = subprocess.run(["git", "show", "v8.8.4:montage.py"], cwd=ROOT, capture_output=True).stdout.decode("utf-8")
        i = src.index("def xfx_sky_chain(")
        ns = dict(vars(M))
        exec(src[i:src.index("\ndef ", i + 10)], ns)
        _OLD["f"] = ns["xfx_sky_chain"]
    return _OLD["f"]


def render_take(t, xfx, fx, f0, f1, old_chain=False):
    """frames f0 - 1 .. f1 - 1 of the take rendered alone by build_filter (RGB, SKY_W x SKY_H)."""
    import subprocess
    mini = {k_: v_ for k_, v_ in plan.items() if k_ not in ("takes", "xfx_drop")}
    mini["takes"] = [dict(t, xfx=xfx, pulses=[], trans="hard")]
    mini["effects"] = "extra"
    mini["duration"] = round(float(t["nf"]) / M.OUT_FPS, 4)
    keep = M.xfx_sky_chain
    if old_chain:
        M.xfx_sky_chain = old_sky_chain()
    try:
        inp, graph = M.build_filter(mini, {}, False, fx)
    finally:
        M.xfx_sky_chain = keep
    graph += f";\n[vout]trim=start_frame={max(0, f0 - 1)}:end_frame={f1},setpts=PTS-STARTPTS,scale={M.SKY_W}:{M.SKY_H}:flags=area,format=rgb24[vz]"
    gp = tmp / "g.txt"
    gp.write_text(graph, encoding="utf-8")
    r = subprocess.run(["ffmpeg", "-v", "error"] + inp + ["-filter_complex_script", str(gp), "-map", "[vz]", "-f", "rawvideo", "-pix_fmt", "rgb24", "-", "-map", "[aout]", "-f", "null", "-"],
                       capture_output=True)
    n = M.SKY_W * M.SKY_H * 3
    k = len(r.stdout) // n
    if k < f1 - max(0, f0 - 1):
        raise RuntimeError(r.stderr.decode("utf-8", "ignore")[-400:])
    return [np.frombuffer(r.stdout[i * n:(i + 1) * n], np.uint8).reshape(M.SKY_H, M.SKY_W, 3) for i in range(k)]


cands = [(ti, t, x) for ti, t in enumerate(plan["takes"]) for x in (t.get("xfx") or []) if x.get("k") == "sky"]
print(f"{game}: {len(sky)} clear-sky clips, plan {len(plan['takes'])} takes, {len(cands)} sky candidates")
tmp = Path(tempfile.mkdtemp(prefix="skymask885_"))
an_ = M.sky_anim_params(0.8, 128, "hype")
res = {"old": [], "new": [], "old_r": [], "new_r": []}
sheet = []
done = 0
for ti, t, x in cands:
    if done >= n_takes:
        break
    x0 = dict(x, anim=an_, seed=7, beats=[], fam="orange", pattern="bands", t0=float(x["p"]), t1=float(t["dur"]))
    f0 = int(round(x0["t0"] * M.OUT_FPS))
    nf = int(t["nf"])
    f1 = min(nf, int(round(x0["t1"] * M.OUT_FPS)) + 1)
    try:
        truth_imgs = M.sky_take_frames(plan, t, max(0, f0 - 1), f1)
    except Exception as ex:                                # noqa: BLE001
        print(f"  take {ti + 1}: render frames not readable: {ex}")
        continue
    truth = []
    smp = M.sky_smooth_samples([M.sky_eyedrop_sample(im) for im in truth_imgs])
    for i_, im in enumerate(truth_imgs):                   # the sky of the very picture shown on this output frame: its pixels that look like this take's sky (the smoothed sky colour of this frame
        m = np.zeros(im.shape[:2], np.uint8)               # and of frames up to 15 apart, so a frame where the colour pick dropped out is still judged by the sky's colour), closed / holes filled like the mask
        for sp in {id(smp[q]): smp[q] for q in (i_ - 15, i_ - 10, i_ - 5, i_, i_ + 5, i_ + 10, i_ + 15) if 0 <= q < len(smp) and smp[q] is not None}.values():
            m |= M.sky_eyedrop_mask(im, sp).astype(np.uint8)
        truth.append(cv2.dilate(M.sky_mask_even(m), np.ones((2 * GROW + 1, 2 * GROW + 1), np.uint8)) > 0)
    for kind in ("old", "new"):
        xx = dict(x0)
        mp = tmp / f"{kind}_{ti}.raw"
        try:
            st = M.sky_take_mask(t, xx, zone, mp, ramp=True, plan=plan if kind == "new" else None)
        except Exception as ex:                            # noqa: BLE001
            print(f"  take {ti + 1} {kind}: mask failed: {type(ex).__name__}: {ex}")
            continue
        fsz = M.SKY_W * M.SKY_H * (4 if xx.get("mask_fmt") == "yuva444p" else 3)
        raw = np.fromfile(mp, np.uint8)
        ys = [raw[f * fsz:f * fsz + M.SKY_W * M.SKY_H].reshape(M.SKY_H, M.SKY_W) for f in range(nf)]
        before = int(ys[f0 - 1].max()) if f0 >= 1 else 0
        leaks = [(float(((ys[f] > 64) & ~truth[j_]).mean()), f) for j_, f in enumerate(range(max(0, f0 - 1), f1))]
        worst = max(leaks)
        n_pop = sum(1 for l_, _f in leaks if l_ > LEAK_MAX)
        print(f"  take {ti + 1} {kind:3s} mask  : frames {f0}-{f1 - 1} ({xx.get('frames_src', 'source')}), frame before the kill painted max {before}, "
              f"worst leak {worst[0] * 100:.2f}% on frame {worst[1]}, frames leaking over {LEAK_MAX * 100:.1f}%: {n_pop} of {len(leaks)}"
              + (f" {[f_ for l_, f_ in leaks if l_ > LEAK_MAX]}" if n_pop else "") + f", {st.get('held', 0)} held, {st.get('breaks', 0)} shot break(s)")
        res[kind].append((ti, worst, n_pop, before))
        # the rendered picture: the take rendered with this sky and without it; every pixel that changed must be sky of that very frame
        xx.update({"ok": True, "mask": str(mp), "grade": M.sky_family_grade("orange", st["mean_y"]), "hue": "orange"})
        try:
            with_ = render_take(t, [xx], ("slow", "sky"), f0, f1, old_chain=(kind == "old"))
            without = render_take(t, [], ("slow",), f0, f1)
        except Exception as ex:                            # noqa: BLE001
            print(f"  take {ti + 1} {kind}: render failed: {type(ex).__name__}: {ex}")
            continue
        rl = []
        for j_ in range(min(len(with_), len(without), len(truth))):
            ch = np.abs(with_[j_].astype(np.int16) - without[j_].astype(np.int16)).max(axis=2) > 16
            rl.append((float((ch & ~rtruth(truth[j_])).mean()), max(0, f0 - 1) + j_, ch))
        rw = max(rl, key=lambda r_: r_[0])
        rpop = [r_[1] for r_ in rl if r_[0] > LEAK_MAX]
        before_r = float(rl[0][2].mean()) if f0 >= 1 else 0.0
        print(f"  take {ti + 1} {kind:3s} render: frame before the kill changed {before_r * 100:.2f}%, worst leak {rw[0] * 100:.2f}% on frame {rw[1]}, frames leaking: {len(rpop)} of {len(rl)}"
              + (f" {rpop[:12]}" if rpop else ""))
        res[kind + "_r"].append((ti, rw[0], len(rpop), before_r))
        if outd is not None:
            j_ = rw[1] - max(0, f0 - 1)
            im = without[j_].copy()
            ov = with_[j_].copy()
            ov[rw[2] & ~rtruth(truth[j_])] = (0, 255, 0)
            sheet.append(cv2.resize(np.concatenate([im, ov], 1), (768, 216)))
    done += 1
if outd is not None and sheet:
    outd.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(outd / f"skymask885_{game}.jpg"), cv2.cvtColor(np.concatenate(sheet, 0), cv2.COLOR_RGB2BGR))
bad = [r for r in res["new"] if r[1][0] > LEAK_MAX or r[3] > 0] + [r for r in res["new_r"] if r[1] > LEAK_MAX or r[3] > 0]
print(f"\nV8.8.5: masks clean in {sum(1 for r in res['new'] if r[1][0] <= LEAK_MAX and r[3] == 0)} of {len(res['new'])} takes, rendered sky clean in "
      f"{sum(1 for r in res['new_r'] if r[1] <= LEAK_MAX and r[3] == 0)} of {len(res['new_r'])} takes; V8.8.4: rendered sky leaked in {sum(1 for r in res['old_r'] if r[2])} of {len(res['old_r'])} takes")
sys.exit(1 if bad or not res["new"] else 0)
