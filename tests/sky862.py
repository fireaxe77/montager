"""V8.6.2 tool: the sky look measured and shown.
python tests/sky862.py strips <clip> <kill time s> <out dir> <style> <energy> <bpm> [song mp3|none] [take s = 5]
    -> strips at the frame before the kill, the kill frame, +3, the middle and the end of the take, the black and white mask under each, and the facts: mask start frame = kill frame, pixels outside the mask changed, the mean sky
       brightness of the output against the source (must be about 35 - 45 %). env SKY86_VIDEO=<out.mp4> also writes the take as a real clip with its sound.
python tests/sky862.py motion <clip> <time s> <out txt> <style> <energy> <bpm> [seconds = 5]
    -> the animation as a number: a STILL picture of the clip (no source motion at all) is given the sky for `seconds` after the kill; "mean change per second" = mean |luma(t + 1 s) - luma(t)| inside the sky mask over the seconds after the
       surge (levels of 255); with the beat pulse on and off. Run with MONTAGER_ROOT=<older worktree> for an older version (the beats are ignored there).
Works with older montage.py files too (functions that do not exist there are skipped)."""
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

W, H = 1920, 1080


def probe_wh(clip):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(clip)], capture_output=True, text=True)
    w, h = (int(x) for x in r.stdout.strip().split(",")[:2])
    return w, h


def frames(inputs, graph, ns, size=(480, 270), label="o"):
    sel = "+".join(f"eq(n,{n})" for n in ns)
    fc = graph + f";[{label}]select='{sel}',scale={size[0]}:{size[1]}:flags=area,format=rgb24[z]"
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


def fake_beats(p, secs, bpm, energy):
    """beats every 60 / bpm from the kill on, every 4th a downbeat (the render uses the song map: sky_take_beats)."""
    out, t, i = [], p, 0
    while t <= secs:
        out.append((round(t, 4), 1.0 if i % 4 == 0 else 0.45))
        t += 60.0 / float(bpm)
        i += 1
    return out


def setup(clip, tm, style, energy, bpm, song, secs):
    wh = probe_wh(clip)
    cz = M.DEFAULT_REGION["cs2"]
    zone = [round(v, 4) for v in (cz[0], cz[1], cz[2], cz[1] + 0.55 * (cz[3] - cz[1]))]
    p = secs / 3
    ss = max(0.0, tm - p)
    nf = int(round(secs * 60))
    img = M.sky_grab_frames(clip, tm, tm + 0.04, [0, 0, wh[0], wh[1]], wh, fps=60)[0]
    _, info = M.sky_eyedrop(img) if hasattr(M, "sky_eyedrop") else M.sky_segment(img, zone)
    ranked, why = M.sky_ranked(style, float(energy), float(bpm))
    cname, crgb, cwhy = M.sky_colour_for(ranked, info.get("sky_rgb"), info.get("scene_hue"))
    gk, gwhy = M.sky_gradient_kind(style, float(energy), float(bpm))
    pal = "song feel only"
    if song and song != "none" and hasattr(M, "sky_cover_colour"):
        cov_rgb, cov_why = M.sky_cover_colour(song)
        if cov_rgb is not None:
            crgb, bl = M.sky_blend_cover(crgb, cov_rgb)
            pal = f"{cov_why}; {bl}"
    return wh, zone, p, ss, nf, info, cname, crgb, cwhy, gk, pal, why


def strips(clip, tm, out_dir, style="hype", energy="0.8", bpm="140", song="none", secs="5"):
    clip, tm, secs = str(clip), float(tm), float(secs)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wh, zone, p, ss, nf, info, cname, crgb, cwhy, gk, pal, why = setup(clip, tm, style, energy, bpm, song, secs)
    name = Path(clip).stem.replace(" ", "_")[:40] + f"_{int(tm)}"
    if not info.get("ok", True):
        print(name, "no clean sky on the kill frame:", info.get("why"))
        return
    kf = int(round(p * 60))
    take = {"nf": nf, "segs": [[ss, ss + secs, 1.0, nf, 0]], "srcs": [{"path": clip, "shift": 0.0, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}], "path": clip, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}
    an = M.sky_anim_params(energy, bpm)
    x = {"k": "sky", "p": p, "t0": p, "t1": secs, "anim": an, "push": an["push"], "seed": 7, "grad_dark": 0.55 if gk == "dark" else 0.25, "beats": fake_beats(p, secs, bpm, energy)}
    mp = Path(tempfile.mkdtemp()) / "mask.yuv"
    st = M.sky_take_mask(take, x, zone, mp, ramp=True)
    if st.get("bad", 0) > M.SKY_MAX_BAD * max(1, st.get("window", 1)):
        print(name, f"skipped: the mask was a wall in {st['bad']} of {st['window']} frames")
        return
    x.update({"mask": str(mp), "grade": M.sky_grade_v2(crgb, gk), "ok": True})
    fs = M.SKY_W * M.SKY_H
    raw = np.fromfile(mp, np.uint8).reshape(nf, 3, fs)
    first = next((f for f in range(nf) if raw[f, 0].any()), None)
    rep = [f"{name}: palette {cname} 0x{crgb:06X} ({pal}); gradient {gk}; animation {an}",
           f"kill frame (output) = {kf}; first frame with a non-zero mask = {first}: " + ("EQUAL" if first == kf else "NOT EQUAL"),
           f"mask coverage: before the kill {raw[kf - 1, 0].mean() / 2.55:.1f}%, kill frame {raw[kf, 0].mean() / 2.55:.1f}%, +3 {raw[kf + 3, 0].mean() / 2.55:.1f}%, middle {raw[(kf + nf) // 2, 0].mean() / 2.55:.1f}%, last {raw[nf - 1, 0].mean() / 2.55:.1f}%; "
           f"checks: {st['ok_frames']} of {st['window']} frames with sky, {st['bad']} wall frames, {st['held']} held"]
    pre = f"scale=1920:1080:flags=lanczos,setsar=1,fps=60,format=yuv420p,setpts=PTS-STARTPTS,trim=end_frame={nf},setpts=PTS-STARTPTS"
    inp = ["-ss", f"{ss:.3f}", "-t", f"{secs + 0.2:.3f}", "-i", clip]
    inp2 = inp + M.sky_mask_input(x)
    chains = []
    nl = M.xfx_sky_chain(chains, "t0", "[src]", x, 1)
    g_new = f"[0:v]{pre}[src];" + ";".join(chains) + f";{nl}null[o]"
    g_src = f"[0:v]{pre}[o]"
    ns = [kf - 1, kf, kf + 3, (kf + nf) // 2, nf - 3]
    tags = ["before kill", "KILL frame", "kill +3", "middle", "end of take"]
    src, new = frames(inp, g_src, ns), frames(inp2, g_new, ns)
    rows = [np.concatenate([label(f, f"SOURCE {t}") for f, t in zip(src, tags)], 1), np.concatenate([label(f, f"SKY {cname} {t}") for f, t in zip(new, tags)], 1),
            np.concatenate([label(cv2.cvtColor(cv2.resize(raw[n, 0].reshape(M.SKY_H, M.SKY_W), (480, 270)), cv2.COLOR_GRAY2RGB), f"MASK {t}") for n, t in zip(ns, tags)], 1)]
    sheet = np.concatenate(rows, 0)
    cv2.imwrite(str(out_dir / f"sky862_{name}_{style}.jpg"), cv2.cvtColor(cv2.resize(sheet, (sheet.shape[1] * 3 // 5, sheet.shape[0] * 3 // 5), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
    big_ns = [kf - 1, kf + 12, (kf + nf) // 2, nf - 3]
    bn, bs = frames(inp2, g_new, big_ns, (W, H)), frames(inp, g_src, big_ns, (W, H))
    ly = lambda a_: (a_.astype(np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32))
    ratios = []
    for k_, n in enumerate(big_ns):
        m = raw[n, 0].reshape(M.SKY_H, M.SKY_W)
        near = cv2.resize(cv2.dilate((m > 0).astype(np.uint8), np.ones((5, 5), np.uint8)), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
        inside = cv2.resize((m > 200).astype(np.uint8), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)
        d = np.abs(bn[k_].astype(np.int16) - bs[k_].astype(np.int16)).max(-1)
        bad = int((d[~near] > 0).sum()) if k_ != 1 else int((d[~cv2.resize(cv2.dilate((m > 0).astype(np.uint8), np.ones((81, 81), np.uint8)), (W, H), interpolation=cv2.INTER_NEAREST).astype(bool)] > 0).sum())
        ratio = float(ly(bn[k_])[inside].mean() / max(1.0, ly(bs[k_])[inside].mean())) if inside.any() else 0.0
        if inside.any() and k_ >= 2:
            ratios.append(ratio)
        rep.append(f"frame {n} ({'surge: the layer is pushed 3 - 6 % and shaken, so the mask area is widened by 40 px' if k_ == 1 else tags[ns.index(n)] if n in ns else ''}): sky pixels {int(inside.sum())}; sky brightness output / source = {ratio * 100:.0f}%; "
                   f"pixels outside the mask area that differ from the source: {bad} (0 = identical)")
    if ratios:
        rep.append(f"mean sky brightness, middle and end of the take: {np.mean(ratios) * 100:.0f}% of the original (target 35 - 45 %)")
    out_v = os.environ.get("SKY86_VIDEO")
    if out_v:
        r = subprocess.run(["ffmpeg", "-v", "error", "-y"] + inp2 + ["-filter_complex", g_new, "-map", "[o]", "-map", "0:a:0?", "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "60",
                                                                       "-c:a", "aac", "-b:a", "160k", "-shortest", out_v], capture_output=True)
        rep.append(f"video: {out_v} (exit {r.returncode})")
    txt = "\n".join(rep)
    (out_dir / f"sky862_{name}_{style}.txt").write_text(txt + "\n", encoding="utf-8")
    print(txt)


def motion(clip, tm, out_txt, style="hype", energy="0.8", bpm="140", secs="5"):
    clip, tm, secs = str(clip), float(tm), float(secs)
    wh, zone, p, ss, nf, info, cname, crgb, cwhy, gk, pal, why = setup(clip, tm, style, energy, bpm, "none", secs)
    still = cv2.cvtColor(M.sky_grab_frames(clip, tm, tm + 0.04, [0, 0, wh[0], wh[1]], wh, size=(1920, 1080), fps=60)[0], cv2.COLOR_RGB2BGR)
    tmp = Path(tempfile.mkdtemp())
    cv2.imwrite(str(tmp / "still.png"), still)
    take = {"nf": nf, "segs": [[tm, tm, 0.0, nf, 0]], "srcs": [{"path": clip, "shift": 0.0, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}], "path": clip, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}
    an = M.sky_anim_params(energy, bpm)
    res = []
    for beats_on in (True, False):
        x = {"k": "sky", "p": p, "t0": p, "t1": secs, "anim": an, "push": an["push"], "seed": 7, "grad_dark": 0.55 if gk == "dark" else 0.25, "beats": fake_beats(p, secs, bpm, energy) if beats_on else []}
        mp = tmp / f"mask{int(beats_on)}.yuv"
        M.sky_take_mask(take, x, zone, mp, ramp=True)
        x.update({"mask": str(mp), "grade": M.sky_grade_v2(crgb, gk), "ok": True})
        chains = []
        nl = M.xfx_sky_chain(chains, "t0", "[src]", x, 1)
        g = f"[0:v]scale=1920:1080,format=yuv420p,setpts=PTS-STARTPTS,trim=end_frame={nf},setpts=PTS-STARTPTS[src];" + ";".join(chains) + f";{nl}null[o]"
        inp = ["-loop", "1", "-framerate", "60", "-t", f"{secs + 0.2:.2f}", "-i", str(tmp / "still.png")] + M.sky_mask_input(x)
        raw = np.fromfile(mp, np.uint8).reshape(nf, 3, M.SKY_W * M.SKY_H)
        kf = int(round(p * 60))
        fl = list(range(kf + 30, nf - 62, 6))
        sel = fl + [f + 60 for f in fl] + [f + 1 for f in fl]
        fr = frames(inp, g, sorted(set(sel)), (480, 270))
        idx = {n: i for i, n in enumerate(sorted(set(sel)))}
        ly = lambda a_: (a_.astype(np.float32) @ np.array([0.2126, 0.7152, 0.0722], np.float32))
        vals, vals1 = [], []
        for f in fl:
            m = cv2.resize(raw[f, 0].reshape(M.SKY_H, M.SKY_W), (480, 270)) > 200
            if m.sum() < 400:
                continue
            vals.append(float(np.abs(ly(fr[idx[f + 60]]) - ly(fr[idx[f]]))[m].mean()))
            vals1.append(float(np.abs(ly(fr[idx[f + 1]]) - ly(fr[idx[f]]))[m].mean()))
        adj = []
        for f in range(kf + 30, nf - 3, 3):
            pass
        res.append((beats_on, float(np.mean(vals)) if vals else 0.0, len(vals), float(np.mean(vals1)) if vals1 else 0.0))
    txt = (f"sky motion on a STILL picture ({Path(clip).name} at {tm:.1f} s: the source has no motion at all, every change is the animation): style {style}, energy {energy}, {bpm} BPM, palette {cname}\n"
           f"frame to frame change inside the sky mask = mean |luma(frame n + 1) - luma(frame n)| averaged over the seconds after the surge (levels of 255, {res[0][2]} measurements):\n"
           f"  with the beat pulse (the default): {res[0][3]:.2f}\n  without the beat pulse (the drifting clouds alone): {res[1][3]:.2f}\n"
           f"change over one second = mean |luma(t + 1 s) - luma(t)|: with the pulse {res[0][1]:.1f}, without {res[1][1]:.1f}\n"
           f"set minimum for the frame to frame change: {MOTION_MIN:.2f}  ->  " + ("OK" if res[0][3] >= MOTION_MIN and res[1][3] >= MOTION_MIN else "TOO WEAK"))
    Path(out_txt).write_text(txt + "\n", encoding="utf-8")
    print(txt)


MOTION_MIN = 0.5

if __name__ == "__main__":
    {"strips": strips, "motion": motion}[sys.argv[1]](*sys.argv[2:])
