"""V8.5 tool: the sky recolour over a WHOLE take of a real clip, through the same chain as the montage render (xfx_sky_chain), with the proof strips.
python tests/sky85.py <clip> <kill time s> <out dir> [style] [energy] [bpm] [take seconds]
  -> <out>/sky85_<name>_<style>.jpg: rows SOURCE / V8.5 (hazy sky) / MASK at the start, the middle and the end of the take (+ 2 more frames), and
     <out>/sky85_<name>_<style>.txt: per-second mask coverage over the take (the V8.4.5 window of 1 s next to the V8.5 window of the whole take), the lowest mask row (must stay above the middle),
     the sky's mean colour in the output, the pixel check (outside the mask area the picture is identical to the source).
The take is `take seconds` (default 6) of the clip around the kill (kill at 1/2 of it)."""
import subprocess
import sys
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


def probe_wh(clip):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(clip)], capture_output=True, text=True)
    w, h = (int(x) for x in r.stdout.strip().split(",")[:2])
    return w, h


def frames(inputs, graph, ns, size=(480, 270)):
    sel = "+".join(f"eq(n,{n})" for n in ns)
    fc = graph + f";[o]select='{sel}',scale={size[0]}:{size[1]}:flags=area,format=rgb24[z]"
    r = subprocess.run(["ffmpeg", "-v", "error", "-y"] + inputs + ["-filter_complex", fc, "-map", "[z]", "-vsync", "0", "-f", "rawvideo", "-"], capture_output=True)
    n = size[0] * size[1] * 3
    if r.returncode or len(r.stdout) < n * len(ns):
        raise RuntimeError("ffmpeg failed: " + r.stderr.decode("utf-8", "ignore")[-800:])
    return [np.frombuffer(r.stdout[i * n:(i + 1) * n], np.uint8).reshape(size[1], size[0], 3).copy() for i in range(len(ns))]


def label(img, txt):
    im = img.copy()
    cv2.putText(im, txt, (6, im.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3)
    cv2.putText(im, txt, (6, im.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
    return im


def main(clip, tm, out_dir, style="hype", energy="0.74", bpm="150", secs="6"):
    clip, tm, secs = str(clip), float(tm), float(secs)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wh = probe_wh(clip)
    zone = [round(v, 4) for v in (M.DEFAULT_REGION["cs2"][0], M.DEFAULT_REGION["cs2"][1], M.DEFAULT_REGION["cs2"][2],
                                  M.DEFAULT_REGION["cs2"][1] + 0.55 * (M.DEFAULT_REGION["cs2"][3] - M.DEFAULT_REGION["cs2"][1]))]
    p = secs / 2
    ss = max(0.0, tm - p)
    nf = int(round(secs * 60))
    img = M.sky_grab_frames(clip, tm, tm + 0.04, [0, 0, wh[0], wh[1]], wh, fps=60)[0]
    mk, info = M.sky_segment(img, zone)
    name = Path(clip).stem.replace(" ", "_")[:40] + f"_{int(tm)}"
    take = {"nf": nf, "segs": [[ss, ss + secs, 1.0, nf, 0]], "srcs": [{"path": clip, "shift": 0.0, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}], "path": clip,
            "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}
    ranked, why = M.sky_ranked(style, float(energy), float(bpm))
    cname, crgb, cwhy = M.sky_colour_for(ranked, info.get("sky_rgb"), info.get("scene_hue"))
    gk, gwhy = M.sky_gradient_kind(style, float(energy), float(bpm))
    top_, hor_ = M.sky_gradient(crgb, gk)
    rep = [f"{name}: kill frame sky coverage {info['cov'] * 100:.0f}% of the upper picture (kind {info['kind']}); song feel {why}: family {', '.join(ranked[:3])}; colour {cname} 0x{crgb:06X} ({cwhy}); "
           f"gradient {gk} ({gwhy}): top 0x{top_:06X}, horizon 0x{hor_:06X}"]
    # the V8.4.5 window (1 s around the kill) against the whole take
    x_old = {"k": "sky", "p": p, "t0": p - 0.25, "t1": p + 0.75, "model": None}
    mp_old = out_dir / "old.gray"
    M.sky_take_mask(take, x_old, zone, mp_old, ramp=False)
    x = {"k": "sky", "p": p, "t0": 0.0, "t1": secs, "model": None}
    mp = out_dir / f"{name}.mask.yuv"
    st = M.sky_take_mask(take, x, zone, mp, ramp=True)
    x.update({"mask": str(mp), "grade": M.sky_grade(crgb, st["mean_y"], (top_, hor_)), "ok": True})
    fs = M.SKY_W * M.SKY_H
    raw_old = np.fromfile(mp_old, np.uint8)
    raw = np.fromfile(mp, np.uint8).reshape(nf, 3, fs)
    per_s = lambda getter: [float(np.mean([getter(f) for f in range(int(s_ * 60), min(nf, int((s_ + 1) * 60)))])) for s_ in range(int(secs))]
    cov_old = per_s(lambda f: raw_old[f * fs:(f + 1) * fs].astype(np.float32).mean() / 255.0)
    cov_new = per_s(lambda f: raw[f, 0].astype(np.float32).mean() / 255.0)
    rep.append("mask coverage per second of the take (share of the whole picture): V8.4.5 window  " + "  ".join(f"{v * 100:4.1f}%" for v in cov_old))
    rep.append("                                                                   V8.5 whole take " + "  ".join(f"{v * 100:4.1f}%" for v in cov_new))
    low = max((int(np.where(raw[f, 0].reshape(M.SKY_H, M.SKY_W).max(1) > 0)[0].max()) if raw[f, 0].any() else 0) for f in range(nf))
    rep.append(f"lowest mask row over the whole take: {low} of {M.SKY_H} = {low / M.SKY_H * 100:.1f}% of the height (limit {M.SKY_MAX_ROW * 100:.0f}%): " + ("OK" if low < M.SKY_H * M.SKY_MAX_ROW else "TOO LOW"))
    rep.append(f"mask: mean coverage of the upper picture {st['cov'] * 100:.0f}%, {st['held']} dropout frame(s) held, horizon at {st['horizon'] * 100:.0f}% of the height, mean sky luma {st['mean_y']:.0f}")
    pre = f"scale=1920:1080:flags=lanczos,setsar=1,fps=60,format=yuv420p,setpts=PTS-STARTPTS,trim=end_frame={nf},setpts=PTS-STARTPTS"
    inp = ["-ss", f"{ss:.3f}", "-t", f"{secs + 0.2:.3f}", "-i", clip]
    inp2 = inp + M.sky_mask_input(x)
    chains = []
    nl = M.xfx_sky_chain(chains, "t0", "[src]", x, 1)
    g_new = f"[0:v]{pre}[src];" + ";".join(chains) + f";{nl}null[o]"
    g_src = f"[0:v]{pre}[o]"
    ns = [2, nf // 6, nf // 3, nf // 2, 2 * nf // 3, 5 * nf // 6, nf - 3]
    tags = [f"{n / 60:.2f}s" for n in ns]
    src = frames(inp, g_src, ns)
    new = frames(inp2, g_new, ns)
    mrow = []
    for n in ns:
        y = raw[n, 0].reshape(M.SKY_H, M.SKY_W)
        mrow.append(label(cv2.cvtColor(cv2.resize(y, (480, 270)), cv2.COLOR_GRAY2RGB), f"MASK {n / 60:.2f}s"))
    rows = [np.concatenate([label(f, f"SOURCE {t}") for f, t in zip(src, tags)], 1),
            np.concatenate([label(f, f"V8.5 {cname} {t}") for f, t in zip(new, tags)], 1), np.concatenate(mrow, 1)]
    sheet = np.concatenate(rows, 0)
    jp = out_dir / f"sky85_{name}_{style}.jpg"
    cv2.imwrite(str(jp), cv2.cvtColor(cv2.resize(sheet, (sheet.shape[1] * 2 // 3, sheet.shape[0] * 2 // 3), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
    # sky colour in the output + pixel check at full size on the first, middle and last frame
    big_ns = [2, nf // 2, nf - 3]
    big_new = frames(inp2, g_new, big_ns, (W, H))
    big_src = frames(inp, g_src, big_ns, (W, H))
    for k_, n in enumerate(big_ns):
        m = raw[n, 0].reshape(M.SKY_H, M.SKY_W)
        inside = cv2.resize((m > 128).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
        near = cv2.resize(cv2.dilate((m > 0).astype(np.uint8), np.ones((5, 5), np.uint8)), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
        d = np.abs(big_new[k_].astype(np.int16) - big_src[k_].astype(np.int16)).max(-1)
        bad = int((d[~near] > 0).sum())
        col = big_new[k_][inside].mean(0) if inside.any() else np.zeros(3)
        col0 = big_src[k_][inside].mean(0) if inside.any() else np.zeros(3)
        rep.append(f"frame {n / 60:.2f}s: sky pixels {int(inside.sum())} ({inside.mean() * 100:.0f}% of the picture); mean sky colour source RGB {tuple(int(v) for v in col0)} -> output {tuple(int(v) for v in col)}; "
                   f"pixels outside the mask area that differ from the source: {bad} (0 = identical)")
    mp.unlink()
    mp_old.unlink()
    txt = "\n".join(rep)
    (out_dir / f"sky85_{name}_{style}.txt").write_text(txt + "\n", encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main(*sys.argv[1:])
