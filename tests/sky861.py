"""V8.6.1 tool: SKY V2 with the eyedropper mask (impact, drifting dark clouds, deep red / song palette) from the KILL frame to the end of a take on a real clip, through the montage render's own chain (xfx_sky_chain).
python tests/sky86.py <clip> <kill time s> <out dir> <style> <energy> <bpm> [song mp3 for the cover art or 'none'] [take seconds = 5]
  -> <out>/sky861_<name>_<style>.jpg: rows SOURCE / SKY V2 / MASK + dark-cloud plane at the frame before the kill, the kill frame, +3 frames, the middle and the end of the take,
     <out>/sky861_<name>_<style>.txt: palette + reason, animation numbers, mask facts, luminance check, the pixel check outside the mask.
The kill is at 1/3 of the take. With env SKY86_VIDEO=<out.mp4> the take is also written as a real clip with its sound."""
import os
import subprocess
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
from sky851 import probe_wh, frames, label                                                    # noqa: E402

W, H = 1920, 1080


def main(clip, tm, out_dir, style="hype", energy="0.8", bpm="140", song="none", secs="5"):
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
    _, info = M.sky_eyedrop(img)
    if not info["ok"]:
        print(name, "NO SKY on the kill frame:", info["why"])
        return
    name = Path(clip).stem.replace(" ", "_")[:40] + f"_{int(tm)}"
    take = {"nf": nf, "segs": [[ss, ss + secs, 1.0, nf, 0]], "srcs": [{"path": clip, "shift": 0.0, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}], "path": clip,
            "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}
    ranked, why = M.sky_ranked(style, float(energy), float(bpm))
    cname, crgb, cwhy = M.sky_colour_for(ranked, info.get("sky_rgb"), info.get("scene_hue"))
    gk, gwhy = M.sky_gradient_kind(style, float(energy), float(bpm))
    if song and song != "none":
        cov_rgb, cov_why = M.sky_cover_colour(song)
    else:
        cov_rgb, cov_why = None, "no song given"
    if cov_rgb is not None:
        crgb, bl_why = M.sky_blend_cover(crgb, cov_rgb)
        pal = f"{cov_why}; {bl_why}"
    else:
        pal = f"{cov_why}: palette from the song feel only"
    an = M.sky_anim_params(energy, bpm)
    rep = [f"{name}: song feel {why}: palette {cname} -> 0x{crgb:06X} ({cwhy}); {pal}; gradient {gk} ({gwhy}); animation drift {an['drift']} px/s, breathing {an['period']} s, surge {an['surge']}, push {an['push']}"]
    x = {"k": "sky", "p": p, "t0": p, "t1": secs, "anim": an, "push": an["push"], "seed": 7, "grad_dark": 0.55 if gk == "dark" else 0.25}
    tmp = Path(tempfile.mkdtemp())
    mp = tmp / "mask.yuv"
    st = M.sky_take_mask(take, x, zone, mp, ramp=True)
    x.update({"mask": str(mp), "grade": M.sky_grade_v2(crgb, gk), "ok": True})
    fs = M.SKY_W * M.SKY_H
    raw = np.fromfile(mp, np.uint8).reshape(nf, 3, fs)
    cov = [float(raw[f, 0].astype(np.float32).mean() / 255.0) for f in range(nf)]
    rep.append(f"mask coverage (share of the picture): frame before the kill {cov[kf - 1] * 100:.1f}%, kill frame {cov[kf] * 100:.1f}%, +1 {cov[kf + 1] * 100:.1f}%, +2 {cov[kf + 2] * 100:.1f}%, +3 {cov[kf + 3] * 100:.1f}%, "
               f"middle {cov[(kf + nf) // 2] * 100:.1f}%, last frame {cov[nf - 1] * 100:.1f}%; frames 0..{kf - 1} all zero: {not raw[:kf, 0].any()}")
    sur = [int(raw[f, 2, 0]) for f in range(kf - 1, kf + 24)]
    rep.append("surge plane (0..255) from the frame before the kill: " + " ".join(str(v) for v in sur))
    m_bin = [raw[f, 0].reshape(M.SKY_H, M.SKY_W) > 128 for f in range(kf + 4, nf)]
    jit = [float(np.logical_xor(a, b).sum() / max(1, a.sum())) for a, b in zip(m_bin, m_bin[1:]) if a.sum() > 0.01 * a.size and b.sum() > 0.01 * a.size] or [0.0]          # frames where the sky is in the picture (> 1 %)
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
    ns = [kf - 1, kf, (kf + nf) // 2, nf - 3]
    tags = ["before kill", "KILL frame", "middle", "end of take"]
    src = frames(inp, g_src, ns)
    new = frames(inp2, g_new, ns)
    rows = [np.concatenate([label(f, f"SOURCE {t}") for f, t in zip(src, tags)], 1),
            np.concatenate([label(f, f"SKY V2 {cname} {t}") for f, t in zip(new, tags)], 1)]
    mrow = []
    for n, t in zip(ns, tags):
        a_ = cv2.cvtColor(cv2.resize(raw[n, 0].reshape(M.SKY_H, M.SKY_W), (480, 270)), cv2.COLOR_GRAY2RGB)
        mrow.append(label(a_, f"SKY MASK {t}"))
    rows.append(np.concatenate(mrow, 1))
    sheet = np.concatenate(rows, 0)
    jp = out_dir / f"sky861_{name}_{style}.jpg"
    cv2.imwrite(str(jp), cv2.cvtColor(cv2.resize(sheet, (sheet.shape[1] * 3 // 5, sheet.shape[0] * 3 // 5), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
    big_ns = [kf - 1, (kf + nf) // 2, nf - 3]
    big_new = frames(inp2, g_new, big_ns, (W, H))
    big_src = frames(inp, g_src, big_ns, (W, H))
    ly = lambda a_: (a_.astype(np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32))
    for k_, n in enumerate(big_ns):
        m = raw[n, 0].reshape(M.SKY_H, M.SKY_W)
        near = cv2.resize(cv2.dilate((m > 0).astype(np.uint8), np.ones((5, 5), np.uint8)), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
        inside = cv2.resize((m > 200).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
        d = np.abs(big_new[k_].astype(np.int16) - big_src[k_].astype(np.int16)).max(-1)
        bad = int((d[~near] > 0).sum())
        dl = float((ly(big_new[k_])[inside] - ly(big_src[k_])[inside]).mean()) if inside.any() else 0.0
        dark = float(np.mean(ly(big_new[k_])[inside] < ly(big_src[k_])[inside] - 4)) if inside.any() else 0.0
        rep.append(f"frame {n / 60:.2f}s ({tags[ns.index(n)] if n in ns else ''}): sky pixels {int(inside.sum())}; mean luminance change inside {dl:+.1f} levels ({dark * 100:.0f}% of the sky pixels darker = the clouds / gradient); pixels outside the mask area that differ: {bad} (0 = identical)")
    out_v = os.environ.get("SKY86_VIDEO")
    if out_v:
        cmd = ["ffmpeg", "-v", "error", "-y"] + inp2[:-0 or None] + ["-filter_complex", g_new.replace("[o]", "[o]"), "-map", "[o]", "-map", "0:a:0?", "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "60",
                                                                      "-c:a", "aac", "-b:a", "160k", "-shortest", out_v]
        r = subprocess.run(cmd, capture_output=True)
        rep.append(f"video: {out_v} (exit {r.returncode}) {r.stderr.decode('utf-8', 'ignore')[-200:]}")
    mp.unlink()
    txt = "\n".join(rep)
    (out_dir / f"sky861_{name}_{style}.txt").write_text(txt + "\n", encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main(*sys.argv[1:])
