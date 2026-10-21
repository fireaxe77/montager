"""V8.7 tool: the sky animation as pictures and numbers.
python tests/sky87.py sheet <clip> <kill time s> <out jpg> <style> <energy> <bpm> [seconds = 4] [every n frames = 6]
    -> a contact sheet of the sky take: one frame every n output frames from the kill on (a hard song strobes, drops to black and jumps colour; a chill one stays calm), and the numbers of the animation planes
       (frames with a black flash, frames with a colour jump, mean frame-to-frame change inside the mask)
python tests/sky87.py smoke <out jpg>
    -> a synthetic test of the smoke rule: a blue sky with a grey smoke cloud drifting in and out at the left edge (and a white cloud inside the sky); the mask must cover the sky and the white cloud, never the smoke, and
       must not flicker (the count of mask pixels that change state more than twice in 31 frames)"""
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
import sky862 as S                                                                            # noqa: E402


def sheet(clip, tm, out_jpg, style="aggressive", energy="0.85", bpm="180", secs="4", every="6"):
    clip, tm, secs, every = str(clip), float(tm), float(secs), int(every)
    wh, zone, p, ss, nf, info, cname, crgb, cwhy, gk, pal, why = S.setup(clip, tm, style, energy, bpm, "none", secs)
    if not info.get("ok", True):
        print("no clean sky on the kill frame:", info.get("why"))
        return
    kf = int(round(p * 60))
    take = {"nf": nf, "segs": [[ss, ss + secs, 1.0, nf, 0]], "srcs": [{"path": clip, "shift": 0.0, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}], "path": clip, "rect": [0, 0, wh[0], wh[1]], "wh": list(wh)}
    an = M.sky_anim_params(energy, bpm, style, False)
    ranked, _ = M.sky_ranked(style, float(energy), float(bpm))
    alt_name, alt_rgb = M.sky_alt_colour(ranked, crgb) if an["jump"] > 0 else (None, None)
    x = {"k": "sky", "p": p, "t0": p, "t1": secs, "anim": an, "push": an["push"], "seed": 7, "grad_dark": 0.55 if gk == "dark" else 0.25, "beats": S.fake_beats(p, secs, bpm, energy)}
    mp = Path(tempfile.mkdtemp()) / "mask.yuv"
    M.sky_take_mask(take, x, zone, mp, ramp=True)
    x.update({"mask": str(mp), "grade": M.sky_grade_v2(crgb, gk, alt_rgb, an["hard"]), "ok": True})
    raw = np.fromfile(mp, np.uint8).reshape(nf, 3, M.SKY_W * M.SKY_H)
    pre = f"scale=1920:1080:flags=lanczos,setsar=1,fps=60,format=yuv420p,setpts=PTS-STARTPTS,trim=end_frame={nf},setpts=PTS-STARTPTS"
    inp2 = ["-ss", f"{ss:.3f}", "-t", f"{secs + 0.2:.3f}", "-i", clip] + M.sky_mask_input(x)
    chains = []
    nl = M.xfx_sky_chain(chains, "t0", "[src]", x, 1)
    g_new = f"[0:v]{pre}[src];" + ";".join(chains) + f";{nl}null[o]"
    ns = list(range(kf - 1, nf - 2, every))[:20]
    fr = S.frames(inp2, g_new, ns, (384, 216))
    cols = 5
    rows = [np.concatenate([S.label(f, f"{(n - kf) / 60:+.2f}s") for f in fr[i:i + cols]] + [np.zeros_like(fr[0])] * (cols - len(fr[i:i + cols])), 1) for i, n in zip(range(0, len(fr), cols), ns[::cols])]
    img = np.concatenate(rows, 0)
    cv2.imwrite(str(out_jpg), cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
    dens = raw[:, 1].astype(np.float32)
    jump = raw[:, 2].astype(np.float32)
    dm = dens.mean(axis=1)
    black = int((dm[kf + 6:] > np.median(dm[kf + 6:]) + 40).sum())
    chg = float(np.abs(np.diff(dm[kf + 6:])).mean())
    print(f"{style} energy {energy} bpm {bpm}: hardness {an['hard']}  strobe {an['strobe_hz']}/s  jump {an['jump']}  drops to black {an['bd']}  swing {an['swing']}  alt colour {alt_name}")
    print(f"  frames with a black flash (density > median + 40): {black} of {nf - kf - 6}; frames with a colour jump (surge plane > 150 after the impact): {int((jump[kf + 24:].mean(axis=1) > 150).sum())}; mean frame-to-frame change of the density plane {chg:.1f}")


def smoke(out_jpg):
    """a blue sky (top), a grey smoke blob at the left that comes and goes, a white cloud inside the sky, a dark wall below"""
    h, w = 432, 768
    n = 90
    imgs = []
    rng = np.random.RandomState(3)
    for f in range(n):
        im = np.zeros((h, w, 3), np.uint8)
        top = np.linspace([70, 130, 215], [150, 190, 235], 300)[:, None, :]
        im[:300] = top.astype(np.uint8)
        im[300:] = (60, 70, 60)
        cv2.ellipse(im, (520, 90), (70, 24), 0, 0, 360, (245, 245, 245), -1)               # a white cloud inside the sky
        im = cv2.GaussianBlur(im, (0, 0), 2)
        s = 0.5 + 0.5 * np.sin(f / 9.0)                                                      # the smoke grows and thins
        sm = np.zeros((h, w), np.float32)
        cv2.ellipse(sm, (60, 150), (int(60 + 50 * s), int(90 + 40 * s)), 0, 0, 360, 1.0, -1)
        sm = cv2.GaussianBlur(sm, (0, 0), 9) * (0.75 + 0.2 * rng.rand(h, w).astype(np.float32))
        grey = np.full((h, w, 3), 150, np.float32) + rng.randn(h, w, 1).astype(np.float32) * 6
        im = (im * (1 - sm[..., None]) + grey * sm[..., None]).clip(0, 255).astype(np.uint8)
        imgs.append(im)
    segm = []
    for im in imgs:
        sp = M.sky_eyedrop_sample(im)
        segm.append(M.sky_eyedrop_mask(im, sp).astype(np.uint8) if sp else np.zeros((h, w), np.uint8))
    smoke_zone = (slice(60, 260), slice(0, 120))
    cover = [float(m[smoke_zone].mean()) for m in segm]
    cloud_ok = [float(m[80:100, 500:540].mean()) for m in segm]
    unst = M.sky_flicker_unstable(segm)
    fl = int(sum(int(u.sum()) for u in unst)) if unst else 0
    print(f"smoke area covered by the mask: max {max(cover) * 100:.1f}% (must be ~0), white cloud inside the sky covered: min {min(cloud_ok) * 100:.0f}% (must be ~100), flicker pixels left out: {fl}")
    cv2.imwrite(str(out_jpg), cv2.cvtColor(np.concatenate([np.concatenate([imgs[i], np.repeat((segm[i] * 255)[..., None], 3, 2)], 1) for i in (0, 30, 60)], 0), cv2.COLOR_RGB2BGR))


if __name__ == "__main__":
    {"sheet": sheet, "smoke": smoke}[sys.argv[1]](*sys.argv[2:])
