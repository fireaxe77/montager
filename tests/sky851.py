"""V8.5.1 tool: the sky recolour from the KILL frame to the end of a take on a real clip, through the montage render's chain (xfx_sky_chain), next to the old V8.4.1 method and the reference screenshot.
python tests/sky851.py <clip> <kill time s> <out dir> <style> <energy> <bpm> [take seconds = 5] [old montage.py = V8.4.1 file] [reference png]
  -> <out>/sky851_<name>_<style>.jpg: rows SOURCE / OLD V8.4.1 / NEW V8.5.1 / MASK at the frame before the kill, the kill frame, +3 frames, the middle and the end of the take (reference screenshot first column),
     <out>/sky851_<name>_<style>.txt: mask facts (frame before the kill = 0, edge movement between frames, lowest row, pixel check outside the mask).
The kill is at 1/3 of the take."""
import importlib.util
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


def main(clip, tm, out_dir, style="hype", energy="0.74", bpm="150", secs="5", old_py=None, ref_png=None):
    clip, tm, secs = str(clip), float(tm), float(secs)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wh = probe_wh(clip)
    cz = M.DEFAULT_REGION["cs2"]
    zone = [round(v, 4) for v in (cz[0], cz[1], cz[2], cz[1] + 0.55 * (cz[3] - cz[1]))]
    p = secs / 3
    ss = max(0.0, tm - p)
    nf = int(round(secs * 60))
    kf = int(round(p * 60))
    img = M.sky_grab_frames(clip, tm, tm + 0.04, [0, 0, wh[0], wh[1]], wh, fps=60)[0]
    _, info = M.sky_segment(img, zone)
    name = Path(clip).stem.replace(" ", "_")[:40] + f"_{int(tm)}"
    take = {"nf": nf, "segs": [[ss, ss + secs, 1.0, nf, 0]], "srcs": [{"path": clip, "shift": 0.0, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}], "path": clip,
            "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}
    ranked, why = M.sky_ranked(style, float(energy), float(bpm))
    cname, crgb, cwhy = M.sky_colour_for(ranked, info.get("sky_rgb"), info.get("scene_hue"))
    gk, gwhy = M.sky_gradient_kind(style, float(energy), float(bpm))
    top_, hor_ = M.sky_gradient(crgb, gk)
    rep = [f"{name}: song feel {why}: colour {cname} 0x{crgb:06X} ({cwhy}); gradient {gk} ({gwhy})"]
    x = {"k": "sky", "p": p, "t0": p, "t1": secs}
    mp = out_dir / f"{name}.mask.yuv"
    st = M.sky_take_mask(take, x, zone, mp, ramp=True)
    x.update({"mask": str(mp), "grade": M.sky_grade(crgb, st["mean_y"], (top_, hor_), gk), "ok": True})
    fs = M.SKY_W * M.SKY_H
    raw = np.fromfile(mp, np.uint8).reshape(nf, 3, fs)
    cov = [float(raw[f, 0].astype(np.float32).mean() / 255.0) for f in range(nf)]
    rep.append(f"mask coverage (share of the picture): frame before the kill {cov[kf - 1] * 100:.1f}%, kill frame {cov[kf] * 100:.1f}%, +1 {cov[kf + 1] * 100:.1f}%, +2 {cov[kf + 2] * 100:.1f}%, +3 {cov[kf + 3] * 100:.1f}%, "
               f"middle {cov[(kf + nf) // 2] * 100:.1f}%, last frame {cov[nf - 1] * 100:.1f}%; frames 0..{kf - 1} all zero: {not raw[:kf, 0].any()}")
    m_bin = [raw[f, 0].reshape(M.SKY_H, M.SKY_W) > 128 for f in range(kf + 4, nf)]
    jit = [float(np.logical_xor(a, b).sum() / max(1, a.sum())) for a, b in zip(m_bin, m_bin[1:])]
    rep.append(f"edge movement between neighbouring frames (area that changes / mask area): mean {np.mean(jit) * 100:.1f}%, worst {np.max(jit) * 100:.1f}%; held dropout frames {st['held']}")
    low = max((int(np.where(raw[f, 0].reshape(M.SKY_H, M.SKY_W).max(1) > 0)[0].max()) if raw[f, 0].any() else 0) for f in range(nf))
    rep.append(f"lowest mask row: {low} of {M.SKY_H} = {low / M.SKY_H * 100:.1f}% of the height (limit {M.SKY_MAX_ROW * 100:.0f}%): " + ("OK" if low < M.SKY_H * M.SKY_MAX_ROW else "TOO LOW"))
    pre = f"scale=1920:1080:flags=lanczos,setsar=1,fps=60,format=yuv420p,setpts=PTS-STARTPTS,trim=end_frame={nf},setpts=PTS-STARTPTS"
    inp = ["-ss", f"{ss:.3f}", "-t", f"{secs + 0.2:.3f}", "-i", clip]
    inp2 = inp + M.sky_mask_input(x)
    chains = []
    nl = M.xfx_sky_chain(chains, "t0", "[src]", x, 1)
    g_new = f"[0:v]{pre}[src];" + ";".join(chains) + f";{nl}null[o]"
    g_src = f"[0:v]{pre}[o]"
    ns = [kf - 1, kf, kf + 3, (kf + nf) // 2, nf - 3]
    tags = ["before kill", "KILL frame", "kill +3", "middle", "end of take"]
    src = frames(inp, g_src, ns)
    new = frames(inp2, g_new, ns)
    rows = [np.concatenate([label(f, f"SOURCE {t}") for f, t in zip(src, tags)], 1)]
    old_row = None
    if old_py:
        sys.path.insert(0, str(Path(old_py).parent))
        spec = importlib.util.spec_from_file_location("m_old851", str(old_py))
        O = importlib.util.module_from_spec(spec)
        sys.modules["m_old851"] = O
        spec.loader.exec_module(O)
        hue = 38
        ox = {"k": "sky", "p": p, "t0": p - O.XFX_SKY_IN, "t1": p + O.XFX_SKY_OUT, "ok": True, "hue": hue}
        oc = []
        ol = O._xfx_chains(oc, "t0", "[src]", {"nf": nf, "xfx": [ox]}, set(O.FX_ALL) | {"sky", "glow", "split", "grade"}, False, zone, {"name": "amber", "hue": hue, "rgb": 0xFFB000})
        g_old = f"[0:v]{pre}[src];" + ";".join(oc) + f";{ol}null[o]"
        old = frames(inp, g_old, ns)
        old_row = np.concatenate([label(f, f"OLD V8.4.1 {t}") for f, t in zip(old, tags)], 1)
        rows.append(old_row)
    rows.append(np.concatenate([label(f, f"NEW V8.5.1 {cname} {t}") for f, t in zip(new, tags)], 1))
    mrow = [label(cv2.cvtColor(cv2.resize(raw[n, 0].reshape(M.SKY_H, M.SKY_W), (480, 270)), cv2.COLOR_GRAY2RGB), f"MASK {t}") for n, t in zip(ns, tags)]
    rows.append(np.concatenate(mrow, 1))
    sheet = np.concatenate(rows, 0)
    if ref_png:
        ref = cv2.cvtColor(cv2.imread(str(ref_png)), cv2.COLOR_BGR2RGB)
        col = np.zeros((sheet.shape[0], 480, 3), np.uint8)
        col[:270] = cv2.resize(ref, (480, 270))
        cv2.putText(col, "REFERENCE (your screenshot)", (6, 262), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
        sheet = np.concatenate([col, sheet], 1)
    jp = out_dir / f"sky851_{name}_{style}.jpg"
    cv2.imwrite(str(jp), cv2.cvtColor(cv2.resize(sheet, (sheet.shape[1] * 3 // 5, sheet.shape[0] * 3 // 5), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
    big_ns = [kf - 1, kf + 6, nf - 3]
    big_new = frames(inp2, g_new, big_ns, (W, H))
    big_src = frames(inp, g_src, big_ns, (W, H))
    for k_, n in enumerate(big_ns):
        m = raw[n, 0].reshape(M.SKY_H, M.SKY_W)
        inside = cv2.resize((m > 200).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
        near = cv2.resize(cv2.dilate((m > 0).astype(np.uint8), np.ones((5, 5), np.uint8)), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
        d = np.abs(big_new[k_].astype(np.int16) - big_src[k_].astype(np.int16)).max(-1)
        bad = int((d[~near] > 0).sum())
        ly = lambda a_: (a_.astype(np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32))
        dl = float(np.abs(ly(big_new[k_])[inside] - ly(big_src[k_])[inside]).mean()) if inside.any() else 0.0
        rep.append(f"frame {n / 60:.2f}s: sky pixels {int(inside.sum())}; mean luminance change inside the mask {dl:.1f} levels (colour only: 0 = luminance kept); pixels outside the mask area that differ: {bad} (0 = identical)")
    mp.unlink()
    txt = "\n".join(rep)
    (out_dir / f"sky851_{name}_{style}.txt").write_text(txt + "\n", encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main(*sys.argv[1:])
