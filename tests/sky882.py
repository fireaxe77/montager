"""V8.8.2 tool: one sky take on a real clip, as a picture sheet (the render's own mask, colour pick, grade and filter chain).
python tests/sky882.py <clip> <kill time s> <out jpg> [style = hype] [energy = 0.8] [bpm = 128] [colour = auto | a palette name] [k = 0] [seconds = 3] [song mp3 = none]
    -> 2 rows of 5 frames from the kill on (source above, sky below) and the facts: colour + why, mask frames, the time the mask took, the mean |frame - blurred frame| inside the sky (blotchiness).
Works with older montage.py files (MONTAGER_ROOT=<older worktree>): missing V8.8.2 arguments are left out."""
import inspect
import os
import subprocess
import sys
import tempfile
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


def probe_wh(clip):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(clip)], capture_output=True, text=True)
    return [int(v) for v in r.stdout.strip().split(",")[:2]]


def frames(inputs, graph, nf, size=(384, 216)):
    fc = graph + f";[o]scale={size[0]}:{size[1]}:flags=area,format=rgb24[z]"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y"] + inputs + ["-filter_complex", fc, "-map", "[z]", "-frames:v", str(nf), "-f", "rawvideo", "-"], capture_output=True)
    n = size[0] * size[1] * 3
    k = len(r.stdout) // n
    if k < 1:
        raise RuntimeError("ffmpeg failed: " + r.stderr.decode("utf-8", "ignore")[-800:])
    return [np.frombuffer(r.stdout[i * n:(i + 1) * n], np.uint8).reshape(size[1], size[0], 3) for i in range(k)]


def label(img, txt):
    im = img.copy()
    cv2.putText(im, txt, (6, im.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 3)
    cv2.putText(im, txt, (6, im.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)
    return im


def kw(fn, **k):
    ps = inspect.signature(fn).parameters
    return {a: b for a, b in k.items() if a in ps}


def main(clip, tm, out_jpg, style="hype", energy="0.8", bpm="128", colour="auto", k="0", secs="3", song="none"):
    tm, secs, k = float(tm), float(secs), int(k)
    wh = probe_wh(clip)
    rect = [0, 0, wh[0], wh[1]]
    cz = M.DEFAULT_REGION["cs2"]
    zone = [cz[0], cz[1], cz[2], cz[1] + 0.55 * (cz[3] - cz[1])]
    p = 0.5
    ss = max(0.0, tm - p)
    nf = int(round(secs * 60))
    img = M.sky_grab_frames(clip, tm, tm + 0.04, rect, wh, fps=60)[0]
    _m, info = M.sky_eyedrop(img)
    print(f"sky on the kill frame: {'yes' if info['ok'] else 'no'} ({info.get('why') or 'clear'}), cover {info['cov'] * 100:.0f}%, scene Y {info.get('scene_y')}")
    if not info["ok"]:
        return
    ranked, rwhy = M.sky_ranked(style, float(energy), float(bpm))
    fams = getattr(M, "SKY_FAMILIES", {})
    if colour in fams or (fams and colour == "family"):                              # V8.8.3: one colour family (forced, or chosen like the render: cover / song vibe)
        name, cwhy = (colour, "forced") if colour in fams else M.sky_family_for({"song": {"path": song}}, M.sky_ranked(style, float(energy), float(bpm))[0])
        rgb = fams[name][0]
    elif colour != "auto":
        name, rgb, cwhy = colour, M.SKY_PALETTE[colour], "forced"
    else:
        name, rgb, cwhy = M.sky_colour_for(ranked, info.get("sky_rgb"), info.get("scene_hue"), **kw(M.sky_colour_for, info=info, k=k))
    if song != "none" and name not in getattr(M, "SKY_NEUTRAL", ()) and name not in fams:
        cr, _w = M.sky_cover_colour(song)
        if cr is not None:
            rgb, _b = M.sky_blend_cover(rgb, cr)
    gk, _gw = M.sky_gradient_kind(style, float(energy), float(bpm))
    an = M.sky_anim_params(energy, bpm, style, True, **kw(M.sky_anim_params, game="cs2"))
    alt_name, alt_rgb = M.sky_alt_colour(ranked, rgb) if an["jump"] > 0 else (None, None)
    beats, b, i = [], p, 0
    while b <= secs:
        beats.append((round(b, 4), 1.0 if i % 4 == 0 else 0.45))
        b += 60.0 / float(bpm)
        i += 1
    take = {"nf": nf, "segs": [[ss, ss + secs, 1.0, nf, 0]], "srcs": [{"path": clip, "shift": 0.0, "rect": rect, "wh": wh}], "path": clip, "rect": rect, "wh": wh}
    x = {"k": "sky", "p": p, "t0": p, "t1": secs, "anim": an, "push": an["push"], "seed": 7, "grad_dark": 0.55 if gk == "dark" else 0.25, "beats": beats}
    if name in fams:
        x["fam"] = name
    mp = Path(tempfile.mkdtemp()) / "mask.yuv"
    t0 = time.time()
    st = M.sky_take_mask(take, x, zone, mp, ramp=True)
    tmask = time.time() - t0
    x.update({"mask": str(mp), "ok": True, "grade": M.sky_family_grade(name, st["mean_y"]) if name in fams else M.sky_grade_v2(rgb, gk, alt_rgb, an["hard"], **kw(M.sky_grade_v2, mean_y=st["mean_y"], name=name))})
    pre = f"scale=1920:1080:flags=lanczos,setsar=1,fps=60,format=yuv420p,setpts=PTS-STARTPTS,trim=end_frame={nf},setpts=PTS-STARTPTS"
    inp = ["-ss", f"{ss:.3f}", "-t", f"{secs + 0.2:.3f}", "-i", clip]
    chains = []
    nl = M.xfx_sky_chain(chains, "t0", "[src]", x, 1)
    new = frames(inp + M.sky_mask_input(x), f"[0:v]{pre}[src];" + ";".join(chains) + f";{nl}null[o]", nf)
    src = frames(inp, f"[0:v]{pre}[o]", nf)
    kf = int(round(p * 60))
    ns = [n for n in ([kf, kf + 6, kf + 20, kf + 45, nf - 2] if os.environ.get("SKY_SHEET") != "beats" else range(kf + 4, nf, 6)) if n < min(len(new), len(src))][:10]
    raw = np.fromfile(mp, np.uint8).reshape(nf, -1, M.SKY_H, M.SKY_W)
    blot = []
    for n in ns[1:]:
        m_ = cv2.resize(raw[n, 0], (384, 216)) > 200
        g = cv2.cvtColor(new[n], cv2.COLOR_RGB2GRAY).astype(np.float32)
        if m_.sum() > 50:
            blot.append(float(np.abs(g - cv2.GaussianBlur(g, (0, 0), 6))[m_].mean()))
    rows = [np.concatenate([label(src[n], f"SRC {(n - kf) / 60:+.2f}s") for n in ns[:5]], 1)] +         [np.concatenate([label(new[n], f"{name} {(n - kf) / 60:+.2f}s") for n in ns[i_:i_ + 5]] + [np.zeros_like(new[0])] * (5 - len(ns[i_:i_ + 5])), 1) for i_ in range(0, len(ns), 5)]
    cv2.imwrite(str(out_jpg), cv2.cvtColor(np.concatenate(rows, 0), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
    print(f"colour {name} 0x{rgb:06X} ({cwhy}); alt {alt_name}; ranked {ranked[:6]}")
    print(f"mask: {st['window']} frames in {tmask:.1f} s ({tmask / max(1, st['window']) * 1000:.0f} ms a frame), mean coverage {st['cov'] * 100:.0f}%, {st['held']} held, {st['bad']} wall frames")
    print(f"blotchiness inside the sky (mean |frame - blurred frame|, lower = more even): {np.mean(blot) if blot else float('nan'):.2f}")


if __name__ == "__main__":
    main(*sys.argv[1:])
