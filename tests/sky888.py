"""V8.8.8 check (real clip, short renders): every sky pattern and every colour family on one real sky take.
python tests/sky888.py <plan.json> <take number (1-based) with a sky> <out dir>   (run on a COPY of montage_data: MONTAGER_DATA=<copy>)
For each of the 5 patterns (family fixed) and each of the 10 colour families (pattern fixed) the take is prepared exactly as a render prepares it (xfx_probe_sky,
build_filter) and the take alone is rendered (split_take_graphs: the same chains). Checks per run:
  mask    the picture changes only where the sky mask is (changed pixels outside the grown mask < 0.3 % of the picture), and it does change (> 2 % inside)
  colour  the sky's mean colour is near the family's colours (hue distance to the closest of its 3 colours < 40 degrees, or the family is white / black)
  gradient the top third of the sky region differs from its bottom third (the top -> bottom ramp)
  motion  the sky region changes from frame to frame (the animation) while the rest stays the picture
and one sheet per run (<out dir>/<pattern>_<family>.jpg: source above, sky below)."""
import copy
import colorsys
import json
import subprocess
import sys
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

planp, take_no, outd = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
outd.mkdir(parents=True, exist_ok=True)
W, H = 480, 270
FAILS = []


def check(name, ok, info=""):
    print(("  ok   " if ok else "  FAIL ") + name + (f"  [{info}]" if info else ""))
    if not ok:
        FAILS.append(name)


def sliced(plan, ti):
    """The plan cut to take ti and the take after it (frame exact, like the preview slice)."""
    takes = plan["takes"]
    t0 = takes[ti]["f0"]
    sel = takes[ti:ti + 2]
    nt = [dict(copy.deepcopy(t), f0=t["f0"] - t0, out_start=round((t["f0"] - t0) / M.OUT_FPS, 4)) for t in sel]
    nt[0]["trans"] = "hard"
    sg = dict(plan["song"], start_t=plan["song"]["start_t"] + t0 / M.OUT_FPS)
    tf = nt[-1]["f0"] + nt[-1]["nf"]
    sg["fade_out_start"] = max(0.0, tf / M.OUT_FPS - 1.0)
    p = dict(copy.deepcopy(plan), takes=nt, song=sg, duration=tf / M.OUT_FPS, total_frames=tf, preview=True)
    p.pop("xfx_drop", None)
    for t in p["takes"]:
        for x in t.get("xfx") or []:
            if x.get("k") == "sky":
                for k in ("ok", "mask", "grade", "cov", "anim", "beats", "fam", "pattern", "mask_fmt", "frames_src", "horizon", "sky_cut"):
                    x.pop(k, None)
    p["takes"][1]["xfx"] = [x for x in p["takes"][1].get("xfx") or [] if x.get("k") != "sky"]
    return p


def take_frames(p, cfg, fx, work):
    pr_ = M.interp_prepare(p, cfg, work, fx)
    inputs, graph = M.build_filter(pr_, cfg, False, fx)
    jobs, _f, _g = M.split_take_graphs(inputs, graph)
    j = next(j_ for j_ in jobs if j_["ti"] == 0)
    gp = work / "take.txt"
    gp.write_text(";\n".join(j["chains"]) + ";\n[t0v]scale=%d:%d:flags=area,format=rgb24[z]" % (W, H), encoding="utf-8")
    cmd = ["ffmpeg", "-v", "error", "-y"] + [a for g in j["groups"] for a in g] + ["-filter_complex_script", str(gp), "-map", "[z]", "-f", "rawvideo", "-"]
    for l_, k_ in j["outs"]:
        if l_ != "t0v":
            cmd += ["-map", f"[{l_}]", "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True)
    n = W * H * 3
    k = len(r.stdout) // n
    if k < 2:
        raise RuntimeError("ffmpeg failed: " + r.stderr.decode("utf-8", "ignore")[-600:])
    return np.frombuffer(r.stdout[:k * n], np.uint8).reshape(k, H, W, 3)


def mask_frames(x, nf):
    """The take's mask file (yuva444p SKY_W x SKY_H): Y plane = where the sky is, per output frame of the sky window."""
    raw = Path(x["mask"]).read_bytes()
    fs = M.SKY_W * M.SKY_H * 4
    k = len(raw) // fs
    ys = [np.frombuffer(raw[i * fs:i * fs + M.SKY_W * M.SKY_H], np.uint8).reshape(M.SKY_H, M.SKY_W) for i in range(k)]
    return [cv2.resize(y, (W, H), interpolation=cv2.INTER_AREA) for y in ys]


def hue_deg(rgb):
    r, g, b = [c / 255.0 for c in rgb]
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360.0


cfg = dict(M.load_config())
plan0 = json.load(open(planp, encoding="utf-8"))
ti = take_no - 1
fx = set(M.FX_ALL) | set(M.XFX_FX)
work = outd / "_work"
work.mkdir(parents=True, exist_ok=True)
base = sliced(plan0, ti)
for t in base["takes"]:
    t["xfx"] = [x for x in t.get("xfx") or [] if x.get("k") != "sky"]
ref = take_frames(base, cfg, fx, work)
runs = [(p_, "red") for p_ in M.SKY_PATTERNS] + [("bands", f_) for f_ in M.SKY_FAMILIES if f_ != "red"]
orig_pat, orig_fam = M.sky_pattern_for, M.sky_family_for
summary = []
for pat, fam in runs:
    print(f"\n{pat} / {fam}")
    M.sky_pattern_for = lambda plan, pat=pat: (pat, "test")
    M.sky_family_for = lambda plan, ranked, qual=None, fam=fam: (fam, "test")
    try:
        p = sliced(plan0, ti)
        M.xfx_probe_sky(p, work / f"sky_{pat}_{fam}")
        x = next((x_ for x_ in p["takes"][0].get("xfx") or [] if x_.get("k") == "sky"), None)
        if not x or not x.get("ok"):
            check(f"{pat}/{fam}: the sky was made for the take", False, "no sky")
            continue
        fr = take_frames(p, cfg, fx, work)
    finally:
        M.sky_pattern_for, M.sky_family_for = orig_pat, orig_fam
    n = min(len(fr), len(ref))
    ms = mask_frames(x, n)
    out_share, in_share, motion, still, grad, hues = [], [], [], [], [], []
    sky_f = []
    for f in range(n):
        d = np.abs(fr[f].astype(int) - ref[f].astype(int)).max(axis=2) > 12
        m = ms[f] if f < len(ms) else np.zeros((H, W), np.uint8)       # one mask frame per output frame of the take
        grown = cv2.dilate((m > 8).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        out_share.append(float((d & ~grown).mean()))
        sky = m > 128
        if sky.sum() > 0.02 * W * H:
            in_share.append(float(d[sky].mean()))
            sky_f.append(f)
            ys_ = np.nonzero(sky)[0]
            lo, hi = np.percentile(ys_, 20), np.percentile(ys_, 80)
            top = fr[f][sky & (np.arange(H)[:, None] <= lo)].mean(axis=0)
            bot = fr[f][sky & (np.arange(H)[:, None] >= hi)].mean(axis=0)
            grad.append(float(np.abs(top - bot).sum()))
            hues.append(fr[f][sky].mean(axis=0))
    for a, b in zip(sky_f, sky_f[1:]):
        if b == a + 1:
            sk = ms[b] > 128
            motion.append(float(np.abs(fr[b].astype(int) - fr[a].astype(int))[sk].mean()))
    check(f"{pat}/{fam}: only the sky changes (worst frame {max(out_share) * 100:.2f}% of the picture outside the mask)", max(out_share) < 0.003)
    check(f"{pat}/{fam}: the sky is recoloured ({np.mean(in_share) * 100 if in_share else 0:.0f}% of the sky pixels changed, {len(sky_f)} sky frames)", bool(in_share) and np.mean(in_share) > 0.02)
    check(f"{pat}/{fam}: gradient top -> bottom (mean colour step {np.mean(grad) if grad else 0:.0f})", bool(grad) and np.mean(grad) > 6)
    check(f"{pat}/{fam}: animated (mean change frame to frame inside the sky {np.mean(motion) if motion else 0:.1f})", bool(motion) and np.mean(motion) > 0.8)
    fc = M.SKY_FAMILIES[fam]
    if fam not in ("white", "black"):
        mh = hue_deg(np.mean(hues, axis=0)) if hues else 0
        fh = [hue_deg(((c >> 16) & 255, (c >> 8) & 255, c & 255)) for c in fc[:3]]
        dist = min(min(abs(mh - h_), 360 - abs(mh - h_)) for h_ in fh)
        check(f"{pat}/{fam}: colour near the family (sky hue {mh:.0f}, family {', '.join(f'{h_:.0f}' for h_ in fh)}: {dist:.0f} degrees)", dist < 40)
    pick = sky_f[::max(1, len(sky_f) // 5)][:5] if sky_f else list(range(0, n, max(1, n // 5)))[:5]
    sheet = np.concatenate([np.concatenate([ref[f] for f in pick], axis=1), np.concatenate([fr[f] for f in pick], axis=1)], axis=0)
    cv2.imwrite(str(outd / f"{pat}_{fam}.jpg"), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    summary.append((pat, fam, len(sky_f)))
print("\nsheets:", outd)
print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
sys.exit(1 if FAILS else 0)
