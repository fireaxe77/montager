"""V8.4.4 tool: the EXTRA effects (white kill flash, sky recolour) on SHORT stretches (4 s) of real clips, through the same render chains as the montage render. No plan, no montage.
python tests/fx844_clips.py flash OUT "<clip or png>" <kill time s> <game> [strength 0.2-0.55]
    -> OUT/flash_<name>.png: frames before / peak / after the flash (top row), the same frames of the source (middle), the killfeed zone enlarged (bottom: flash frame, source frame);
       prints the white share of each colour channel (a neutral white flash has the same share in R, G and B) and the colour cast.
python tests/fx844_clips.py sky OUT "<clip>" <time s> [colour] [seed]
    -> OUT/sky_<name>.png: three rows, source / old method (V8.4.3: colour mask per pixel) / new method (V8.4.4: connected sky region, one deep colour), plus the mask row; prints the sky coverage.
Frames are read with sky_grab_frames (raises on a failed read: no silent black tiles)."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
ROOT = _root.find_root()
sys.path.insert(0, str(ROOT))
import montage as M                                                                           # noqa: E402
import numpy as np                                                                            # noqa: E402
import cv2                                                                                    # noqa: E402

W, H = 1920, 1080
PRE = "scale=1920:1080:flags=lanczos,setsar=1,fps=60,format=yuv420p,setpts=PTS-STARTPTS,trim=end_frame=240,setpts=PTS-STARTPTS"


def probe_wh(clip):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(clip)], capture_output=True, text=True)
    w, h = (int(x) for x in r.stdout.strip().split(",")[:2])
    return w, h


def frames(graph_inputs, graph, ns, label="o"):
    """Frames n of a filter graph's output (list of RGB arrays); the ffmpeg error is raised, never swallowed."""
    sel = "+".join(f"eq(n,{n})" for n in ns)
    fc = graph + f";[{label}]select='{sel}',scale=480:270:flags=area,format=rgb24[z]"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y"] + graph_inputs + ["-filter_complex", fc, "-map", "[z]", "-vsync", "0", "-f", "rawvideo", "-"], capture_output=True)
    if r.returncode or len(r.stdout) < 480 * 270 * 3 * len(ns):
        raise RuntimeError("ffmpeg failed: " + r.stderr.decode("utf-8", "ignore")[-600:])
    return [np.frombuffer(r.stdout[i * 480 * 270 * 3:(i + 1) * 480 * 270 * 3], np.uint8).reshape(270, 480, 3).copy() for i in range(len(ns))]


def full_frames(graph_inputs, graph, ns, label="o"):
    sel = "+".join(f"eq(n,{n})" for n in ns)
    fc = graph + f";[{label}]select='{sel}',format=rgb24[z]"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y"] + graph_inputs + ["-filter_complex", fc, "-map", "[z]", "-vsync", "0", "-f", "rawvideo", "-"], capture_output=True)
    if r.returncode or len(r.stdout) < W * H * 3 * len(ns):
        raise RuntimeError("ffmpeg failed: " + r.stderr.decode("utf-8", "ignore")[-600:])
    return [np.frombuffer(r.stdout[i * W * H * 3:(i + 1) * W * H * 3], np.uint8).reshape(H, W, 3).copy() for i in range(len(ns))]


def label(img, txt):
    im = img.copy()
    cv2.putText(im, txt, (6, 262), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
    cv2.putText(im, txt, (6, 262), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
    return im


def clip_inputs(clip, ss):
    if str(clip).lower().endswith((".png", ".jpg")):
        return ["-loop", "1", "-framerate", "60", "-t", "4.2", "-i", str(clip)]
    return ["-ss", f"{ss:.3f}", "-t", "4.2", "-i", str(clip)]


def flash(out_dir, clip, kt, game, a=0.34):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    kt, a = float(kt), float(a)
    p = 2.0
    zone = list(M.DEFAULT_REGION[game])
    zone[3] = zone[1] + 0.55 * (zone[3] - zone[1])
    take = {"nf": 240, "xfx": [{"k": "flash", "p": p, "a": a, "t1": M.XFX_FLASH_S}]}               # V8.4.5: the stylised pulse (vignette + bloom, peak a <= FLASH_A_MAX)
    chains = []
    lab = M._xfx_chains(chains, "t0", "[src]", take, M.FX_ALL, False, zone, {"name": "x", "hue": 0, "rgb": 0xFFFFFF})
    inp = clip_inputs(clip, kt - p)
    g_fx = f"[0:v]{PRE}[src];" + ";".join(chains) + f";{lab}null[o]"
    g_src = f"[0:v]{PRE}[o]"
    f0 = int(round(p * 60))
    ns = [f0 - 6, f0, f0 + 1, f0 + 2, f0 + 4, f0 + 10, f0 + 20, f0 + 40]
    names = ["before", "peak", "+1 frame", "+2", "+4", "+10", "+20", "+40"]
    fx_big = full_frames(inp, g_fx, ns[:4] + ns[5:6])
    src_big = full_frames(inp, g_src, ns[:4] + ns[5:6])
    fx_s = frames(inp, g_fx, ns)
    src_s = frames(inp, g_src, ns)
    top = np.concatenate([label(f, f"FLASH {n}") for f, n in zip(fx_s[:4], names[:4])], 1)
    top2 = np.concatenate([label(f, f"FLASH {n}") for f, n in zip(fx_s[4:], names[4:])], 1)
    mid = np.concatenate([label(f, f"SOURCE {n}") for f, n in zip(src_s[:4], names[:4])], 1)
    mid2 = np.concatenate([label(f, f"SOURCE {n}") for f, n in zip(src_s[4:], names[4:])], 1)
    x0, y0, x1, y1 = zone
    cx0, cx1, cy0, cy1 = int(x0 * W), int(x1 * W), int(y0 * H), int(min(1.0, y1 + 0.02) * H)
    crops = []
    for big, tag in ((fx_big[1], "flash peak"), (src_big[1], "source"), (fx_big[3], "flash +2"), (fx_big[4], "flash +10")):
        c = cv2.resize(big[cy0:cy1, cx0:cx1], (480, int(480 * (cy1 - cy0) / (cx1 - cx0))))
        cv2.putText(c, tag, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)
        crops.append(c)
    hh = max(c.shape[0] for c in crops)
    crops = [np.pad(c, ((0, hh - c.shape[0]), (0, 0), (0, 0))) for c in crops]
    sheet = np.concatenate([top, top2, mid, mid2, np.concatenate(crops, 1)], 0)
    name = Path(clip).stem.replace(" ", "_")[:40]
    cv2.imwrite(str(out_dir / f"flash_{name}_{game}.png"), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR))
    # the white share per channel on the peak frame, outside the killfeed zone, on pixels that are not already near white
    fxp, srp = fx_big[1].astype(np.float32), src_big[1].astype(np.float32)
    mask = np.ones((H, W), bool)
    mask[cy0:cy1, cx0:cx1] = False
    shares = []
    for ch in range(3):
        c0, c1 = srp[..., ch][mask], fxp[..., ch][mask]
        ok = c0 < 190
        shares.append(float(np.median((c1[ok] - c0[ok]) / (255.0 - c0[ok]))))
    cast = max(shares) - min(shares)
    mean_d = [float((fxp[..., ch][mask] - srp[..., ch][mask]).mean()) for ch in range(3)]
    sat0 = float(np.mean(srp[mask].max(1) - srp[mask].min(1)))
    sat1 = float(np.mean(fxp[mask].max(1) - fxp[mask].min(1)))
    ly0 = srp @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    ly1 = fxp @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    print(f"{name} ({game}): peak frame mean luma {float(ly0[mask].mean()):.0f} -> {float(ly1[mask].mean()):.0f} (+{float(ly1[mask].mean() - ly0[mask].mean()):.0f}), brightest 1 % of pixels {float(np.percentile(ly1[mask], 99)):.0f} (white = 255), "
          f"centre +{float((ly1 - ly0)[300:700, 700:1200].mean()):.0f}, edges +{float((ly1 - ly0)[:, :300][mask[:, :300]].mean()):.0f}; white share R {shares[0]:.3f} G {shares[1]:.3f} B {shares[2]:.3f} (cast {cast:.3f}); mean change RGB {mean_d[0]:+.1f} {mean_d[1]:+.1f} {mean_d[2]:+.1f}; "
          f"colourfulness {sat0:.1f} -> {sat1:.1f}; " + ("NEUTRAL WHITE" if cast < 0.02 and sat1 <= sat0 + 1 else "CAST!"))
    return 0 if cast < 0.02 else 1


def old_module():
    """The V8.4.3 montage.py (git tag / commit 03aa48e) for the old-method column."""
    p = Path(tempfile.gettempdir()) / "montage_v843_old.py"
    if not p.exists():
        src = subprocess.run(["git", "show", "03aa48e:montage.py"], cwd=str(ROOT), capture_output=True).stdout
        p.write_bytes(src)
    spec = importlib.util.spec_from_file_location("m843old", str(p))
    m = importlib.util.module_from_spec(spec)
    sys.modules["m843old"] = m
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        spec.loader.exec_module(m)
    return m


def sky(out_dir, clip, tm, colour="auto:hype:0.74:150", seed="1"):
    """colour = a palette name, or auto:<style>:<energy>:<bpm> = the V8.4.5 choice from the song's feel against the clip's own sky and scene colours."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tm = float(tm)
    p = 2.5
    wh = probe_wh(clip)
    zone = [round(v, 4) for v in (M.DEFAULT_REGION["cs2"][0], M.DEFAULT_REGION["cs2"][1], M.DEFAULT_REGION["cs2"][2], M.DEFAULT_REGION["cs2"][1] + 0.55 * (M.DEFAULT_REGION["cs2"][3] - M.DEFAULT_REGION["cs2"][1]))]
    # coverage on the kill frame
    img = M.sky_grab_frames(clip, tm, tm + 0.04, [0, 0, wh[0], wh[1]], wh, fps=60)[0]
    mk, info = M.sky_segment(img, zone)
    cov, top = info["cov"], info["top"]
    qualifies = M.XFX_SKY_MIN_COV <= cov <= M.XFX_SKY_MAX_COV and top >= M.XFX_SKY_MIN_TOP and info["kind"] in ("blue", "warm")
    name = Path(clip).stem.replace(" ", "_")[:40] + f"_{int(tm)}"
    print(f"{name}: sky coverage {cov * 100:.0f}% of the upper picture (top strip {top * 100:.0f}%, kind {info['kind']}) -> the render would " + ("RECOLOUR the sky" if qualifies else "SKIP the sky (no clear sky)"))
    if not qualifies:
        return 2
    ss = max(0.0, tm - p)
    take = {"nf": 240, "segs": [[ss, ss + 4.0, 1.0, 240, 0]], "srcs": [{"path": str(clip), "shift": 0.0, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}], "path": str(clip),
            "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}
    x = {"k": "sky", "p": p, "t0": p - M.XFX_SKY_IN, "t1": p + M.XFX_SKY_OUT, "model": None}
    mp = out_dir / f"{name}.mask.gray"
    st = M.sky_take_mask(take, x, zone, mp)
    if colour.startswith("auto"):
        _, style, en, bpm = colour.split(":")
        ranked, why = M.sky_ranked(style, float(en), float(bpm))
        cname, crgb, cwhy = M.sky_colour_for(ranked, info.get("sky_rgb"), info.get("scene_hue"))
        print(f"  song feel {why}: family {', '.join(ranked[:3])}; sky {info['sky_rgb']:06X}, scene hue {info.get('scene_hue')}: colour {cname} ({cwhy})")
    else:
        cname, crgb = colour, M.SKY_PALETTE[colour]
    x.update({"mask": str(mp), "grade": M.sky_grade(crgb, st["mean_y"]), "ok": True})
    inp = clip_inputs(clip, ss)
    chains = []
    nl = M.xfx_sky_chain(chains, "t0", "[src]", x, 1)
    g_new = f"[0:v]{PRE}[src];" + ";".join(chains) + f";{nl}null[o]"
    old = old_module()
    fe = old.feel_hue("hype", 0.7, 128)
    oldx = {"k": "sky", "p": p, "t0": p - old.XFX_SKY_IN, "t1": p + old.XFX_SKY_OUT, "hue": fe[1], "ok": True}
    ochains = []
    ol = old._xfx_chains(ochains, "t0", "[src]", {"nf": 240, "xfx": [oldx]}, set(old.FX_ALL) | {"sky"}, False, zone, {"name": fe[0], "hue": fe[1], "rgb": fe[2]})
    g_old = f"[0:v]{PRE}[src];" + ";".join(ochains) + f";{ol}null[o]"
    g_src = f"[0:v]{PRE}[o]"
    ns = [int((p - 0.3) * 60), int(p * 60), int((p + 0.12) * 60), int((p + 0.4) * 60)]
    inp2 = inp + ["-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{M.SKY_W}x{M.SKY_H}", "-framerate", "60", "-i", str(mp)]
    rows = []
    for tag, g, ii in (("SOURCE", g_src, inp), ("OLD V8.4.3", g_old, inp), (f"NEW V8.4.5 {cname}", g_new, inp2)):
        fr = frames(ii, g, ns)
        rows.append(np.concatenate([label(f, f"{tag} {n / 60 - p:+.2f}s") for f, n in zip(fr, ns)], 1))
    raw = np.fromfile(mp, np.uint8)
    fsz = M.SKY_W * M.SKY_H
    mrow = []
    for n in ns:
        y = raw[n * fsz:(n + 1) * fsz].reshape(M.SKY_H, M.SKY_W)
        mrow.append(label(cv2.cvtColor(cv2.resize(y, (480, 270)), cv2.COLOR_GRAY2RGB), f"MASK {n / 60 - p:+.2f}s"))
    rows.append(np.concatenate(mrow, 1))
    cv2.imwrite(str(out_dir / f"sky_{name}.jpg"), cv2.cvtColor(np.concatenate(rows, 0), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
    # pixel check at full size: outside the sky mask the picture is IDENTICAL to the render without the sky effect
    nsel = [int(p * 60), int((p + 0.12) * 60)]
    with_sky = full_frames(inp2, g_new, nsel)
    without = full_frames(inp, g_src, nsel)
    bad_total, in_total, changed_in = 0, 0, 0
    for k_, n in enumerate(nsel):
        m = raw[n * fsz:(n + 1) * fsz].reshape(M.SKY_H, M.SKY_W)
        mm = cv2.dilate((m > 0).astype(np.uint8), np.ones((5, 5), np.uint8))                      # the mask pixels and their 2-pixel neighbourhood: where the bicubic up-scaling may reach
        big = cv2.resize(mm, (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
        d = np.abs(with_sky[k_].astype(np.int16) - without[k_].astype(np.int16)).max(-1)
        bad_total += int((d[~big] > 0).sum())
        in_total += int(big.sum())
        changed_in += int((d[big] > 8).sum())
    print(f"  mask: mean coverage in the window {st['cov'] * 100:.0f}% of the upper picture; PIXEL CHECK at the peak and +0.12 s: {bad_total} pixels outside the mask area differ from the render without the sky effect "
          f"(0 = identical); inside the mask area {changed_in} of {in_total} pixels changed by more than 8 levels; colour {cname} 0x{crgb:06X}")
    mp.unlink()
    return 0 if bad_total == 0 else 3


if __name__ == "__main__":
    mode = sys.argv[1]
    sys.exit(flash(*sys.argv[2:]) if mode == "flash" else sky(*sys.argv[2:]))
