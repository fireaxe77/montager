"""V7.6.1 marker harness: generated clips with a white flash frame AND a 1 kHz click at the exact SHOT time of every kill (the killfeed row is 0.1 s later, as in real
clips), different sizes / frame rates / containers / VFR, planned by the real planner, rendered by the real pipeline, measured on the OUTPUT FILE (flash frame, click
sample) and compared with the planned output time of the kill.  Independent of the kill detector.
   python tests\\marker761.py          (prints the table)"""
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402
import test_v73 as T73                                                                        # noqa: E402
import test_v693 as T                                                                         # noqa: E402

ROW_LAG = 0.1                      # the planner dates a kill without a detected gunshot at row - 0.1 s
SPECS = [  # name, w, h, fps, ext, vfr
    ("p1080", 1920, 1080, 60, "mp4", False),
    ("p1080_50mov", 1920, 1080, 50, "mov", False),
    ("p1440", 2560, 1440, 60, "mp4", False),
    ("p2160", 3840, 2160, 60, "mp4", False),
    ("p960", 1280, 960, 60, "mp4", False),
    ("p1080_30", 1920, 1080, 30, "mp4", False),
    ("p1080_vfr", 1920, 1080, 60, "mp4", True),
    ("p720_120", 1280, 720, 120, "mp4", False),
]


def gen_marker_clip(path, w, h, fps, shots, dur=16.0, vfr=False):
    """White flash on the frame at each shot time (snapped to the clip's frame grid) + a 5 ms 1 kHz click at exactly that frame time. Returns the snapped times."""
    snapped = [round(s * fps) / fps for s in shots]
    wid = max(1, int(round(fps / 30.0)))                                     # flash lasts 1/30 s (a 120 fps source would otherwise lose it when decimated to 60)
    n_on = "+".join(f"between(n,{int(round(s * fps))},{int(round(s * fps)) + wid - 1})" for s in snapped)
    clicks = "+".join(f"between(t,{s:.6f},{s + 0.005:.6f})" for s in snapped)
    # a tiny moving detail so nothing is a perfectly flat picture (the encoder must really code frames)
    vf = (f"drawbox=x=0:y=0:w=iw:h=ih:color=white:t=fill:enable='{n_on}',"
          f"drawbox=x='mod(t*400,iw-40)':y=ih/2:w=40:h=40:color=0x808080:t=fill")
    if vfr:                                                                  # drop every 9th frame (not the flash frames): real timestamp gaps = VFR
        keepf = "+".join(f"between(n,{int(round(s_ * fps))},{int(round(s_ * fps)) + wid - 1})" for s_ in snapped)
        vf += f",select='if({keepf},1,not(eq(mod(n,9),4)))'"
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x202020:s={w}x{h}:r={fps}:d={dur}",
           "-f", "lavfi", "-i", f"aevalsrc='0.9*sin(2*PI*1000*t)*({clicks})':s=48000:c=stereo:d={dur}",
           "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", "-pix_fmt", "yuv420p", "-g", "120", "-c:a", "aac", "-b:a", "192k"]
    if vfr:
        cmd += ["-fps_mode", "vfr"]
    cmd += [str(path)]
    r = subprocess.run(cmd, capture_output=True)
    assert r.returncode == 0, r.stderr.decode()[-400:]
    return snapped


def build(tmp, specs=None, n=None, seed=7):
    """Marker clips -> events -> pool items. Returns (items, truth {path: [shot times]})."""
    specs = specs or SPECS
    n = n or len(specs)
    d = Path(tmp) / "mk761"
    d.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(seed)
    items, truth = [], {}
    V = T.names(4 * n + 5, seed)
    vi = 0
    for i in range(n):
        nm, w, h, fps, ext, vfr = specs[i % len(specs)]
        p = d / f"Replay 2026-09-{(i % 28) + 1:02d} {(i // 28) * 5 + 3:02d}-10-00.{ext}"
        k_n = rnd.choice([1, 2, 3, 3])
        t, shots = rnd.uniform(3.5, 5.5), []
        for _ in range(k_n):
            shots.append(t)
            t += rnd.uniform(0.9, 2.4)
        snapped = gen_marker_clip(p, w, h, fps, shots, vfr=vfr)
        mt = time.mktime((2026, 9, (i % 28) + 1, (i // 28) * 5 + 3, 10, 0, 0, 0, -1)) + 16
        os.utime(p, (mt, mt))
        rec = T.rec_of(p, 16, "cs2")
        rec.update(w=w, h=h, fps=float(fps), audio=True)
        kl = []
        for s in snapped:
            kl.append((round(s + ROW_LAG, 3), V[vi]))
            vi += 1
        items.append(T.pool_item(rec, kl))
        truth[str(p)] = snapped
    return items, truth


def planned_out_times(plan, truth):
    """[(take index, kill index, planned output seconds, source shot time)] for every kill that is a marker shot."""
    rows = []
    for ti, t in enumerate(plan["takes"]):
        tl = []
        for src in (t.get("srcs") or [{"path": t["path"], "shift": 0.0}]):
            tl.append(truth.get(str(src["path"])))
        base = truth.get(str(t["path"])) or []
        for ki, k in enumerate(t["kills"]):
            near = min(base, key=lambda s: abs(s - k)) if base else None
            if near is None or abs(near - k) > 0.02:
                continue
            o = M.src_to_out(t["segs"], k)
            rows.append((ti, ki, (t["f0"] + int(round(o * 60))) / 60.0, near))
    return rows


def measure(outf, total_frames):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(outf), "-vf", "scale=32:18,format=gray", "-f", "rawvideo", "-"], capture_output=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, 18 * 32).mean(axis=1)
    flash = [i for i in range(len(fr)) if fr[i] > 70 and (i == 0 or fr[i - 1] <= 70)]
    ar = subprocess.run(["ffmpeg", "-v", "error", "-i", str(outf), "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], capture_output=True).stdout
    a = np.abs(np.frombuffer(ar, np.float32))
    idx = np.where(a > 0.12)[0]
    clicks = []
    last = -10 ** 9
    for i in idx:
        if i - last > 48000 * 0.25:
            clicks.append(i / 48000.0)
        last = i
    return len(fr), flash, clicks


def table(plan, truth, nfr, flash, clicks):
    """Per kill: video error in output frames and audio error in ms (nearest measured marker within 0.25 s of the plan)."""
    res = []
    for ti, ki, pt, s in planned_out_times(plan, truth):
        vf = min(flash, key=lambda f: abs(f / 60.0 - pt)) if flash else None
        ac = min(clicks, key=lambda c: abs(c - pt)) if clicks else None
        ve = None if vf is None or abs(vf / 60.0 - pt) > 0.25 else vf - round(pt * 60)
        ae = None if ac is None or abs(ac - pt) > 0.25 else (ac - pt) * 1000
        res.append({"take": ti, "kill": ki, "planned": pt, "v_err_frames": ve, "a_err_ms": ae})
    return res


def stitch_one(plan, truth, tmp):
    """Turn the first take with two segments into a STITCHED take: its second segment comes from a second file B (A trimmed from X, shift = X)."""
    for t in plan["takes"]:
        if len(t["segs"]) >= 2 and len(t.get("srcs") or []) <= 1 and abs(t["segs"][1][2] - 1.0) < 1e-6 and not t.get("util"):
            a1 = t["segs"][1][0]
            X = round((a1 - 1.0) * 60) / 60.0
            B = Path(tmp) / "mk761" / f"stitchB_{abs(hash(t['path'])) % 10**6}.mp4"
            r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{X:.4f}", "-i", t["path"], "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", "-c:a", "aac", str(B)], capture_output=True)
            assert r.returncode == 0, r.stderr.decode()[-300:]
            s0 = {"path": t["path"], "shift": 0.0, "rect": t["rect"], "wh": t["wh"], "audio": t["audio"], "a_stream": 0, "gain_db": -6.0}
            s1 = dict(s0, path=str(B), shift=X)
            t["srcs"] = [s0, s1]
            sg = list(t["segs"][1])
            sg = sg[:4] + [1]
            t["segs"][1] = sg
            plan["_stitched"] = plan.get("_stitched", 0) + 1
            return


def run(tmp, specs=None, n=None, seed=7, style="aggressive", nd=2, fx=None, post=None, encoder="fast", length=5):
    """Plan with the real planner and render with the real pipeline. `post(plan, truth, tmp)` may edit the plan before the render (e.g. stitch a take)."""
    items, truth = build(tmp, specs, n, seed)
    ev, _ = T73.events_of(M, "cs2", items)
    an = T73.song_map(M, 128.0, 300.0, 64.0)
    bt = an["beats"]
    base = an["drops"][0]["beat"]
    an["drops"] = [{"beat": base + 32 * i, "t": float(bt[base + 32 * i]) + 0.21 + 0.03 * i, "strength": 1.0 - 0.1 * i} for i in range(nd)]
    an["drop"] = base
    keep = dict(M.RECIPES[style])
    M.RECIPES[style].update(lead=(4, 6), ramp_p=1.0)
    try:
        plan = T73.plan_of(M, "cs2", ev, an, length, style=style)
    finally:
        M.RECIPES[style].clear()
        M.RECIPES[style].update(keep)
    song = Path(tmp) / "mk761" / "silence.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "300", "-c:a", "aac", str(song)], capture_output=True)
    plan["song"]["path"] = str(song)
    if post:
        post(plan, truth, Path(tmp))
    outf = Path(tmp) / "mk761" / "out.mp4"
    cfg = dict(M.load_config(), sync_report=False)
    M.render_plan(plan, outf, cfg, encoder=encoder)
    nfr, flash, clicks = measure(outf, plan["total_frames"])
    return plan, truth, table(plan, truth, nfr, flash, clicks), (nfr, flash, clicks)


def report(plan, tb, nfr, flash, clicks, title):
    ok_v = [r["v_err_frames"] for r in tb if r["v_err_frames"] is not None]
    ok_a = [r["a_err_ms"] for r in tb if r["a_err_ms"] is not None]
    print(f"== {title}: frames {nfr} (plan {plan['total_frames']}), takes {len(plan['takes'])}, kills {len(tb)}, flashes {len(flash)}, clicks {len(clicks)}, stitched {plan.get('_stitched', 0)}")
    print(f"   video error frames: min {min(ok_v)} max {max(ok_v)} (measured {len(ok_v)}/{len(tb)});  audio error ms: min {min(ok_a):.1f} max {max(ok_a):.1f} (measured {len(ok_a)}/{len(tb)})")
    return ok_v, ok_a


if __name__ == "__main__":
    from songmap_v2 import planbench as PB
    tmp = Path(tempfile.mkdtemp(prefix="m761_"))
    with PB.data_copy(M):
        old = M.use_data_dir(tmp / "do")
        try:
            for title, kw in (("mixed sources", {}), ("stitched + 16 clips", {"n": 16, "post": stitch_one, "length": 5})):
                plan, truth, tb, (nfr, flash, clicks) = run(tmp, **kw)
                report(plan, tb, nfr, flash, clicks, title)
                for r in tb:
                    t = plan["takes"][r["take"]]
                    print(f"   take {r['take']:2d} kill {r['kill']} planned {r['planned']:7.3f}  video {r['v_err_frames']}  audio {None if r['a_err_ms'] is None else round(r['a_err_ms'], 1)} ms  "
                          f"{Path(t['path']).suffix} {t['wh']} srcs {len(t.get('srcs') or [])} segs {[(round(s[0], 2), round(s[2], 2)) for s in t['segs']]}")
        finally:
            M.restore_data_dir(old)
