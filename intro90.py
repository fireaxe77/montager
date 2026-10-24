"""Montager V9.0: the INTRO's text (title lines, six looks) and its speed profile. Imported by montage.py (lazily); nothing here plans or renders a montage.

The intro itself is built by montage.py (add_intro / build_filter): the first take's footage just before its first kill, heavily blurred and slowed with frame
blending, the song fading in, this module's text over it (look A: a slow fade with a gentle scale 104 % -> 100 %), then the picture unblurs and the speed ramps to the take's own
speed. This module makes (1) the clean title, (2) the look per montage, (3) the text as a short video with alpha (a band of the picture, 60 fps), (4) the speed numbers.
"""
import math
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1920, 1080, 60
K = W / 1280.0                     # the looks were designed on 1280 x 720
INTRO_S = 7.0                      # fixed length of the intro (s)
V0 = 0.30                          # slow-motion speed of the blurred hold
V0_MIN = 0.10                      # the hold may run slower than V0 when the clip has little footage before the take (never below this)
RAMP = 1.0                         # s: unblur + speed ramp (V0 -> the take's own speed)
FADE_IN = 0.5                      # music + picture fade-in
TEXT_IN = 0.8                      # the text starts to appear (look A: a slow 0.9 s fade)
TEXT_FADE_IN, TEXT_FADE_OUT = 0.9, 0.5
SCALE_FROM, SCALE_S = 1.04, 3.2    # look A: the text eases from 104 % to 100 % over this long
HOLD_END = INTRO_S - RAMP          # the text is gone when the unblur starts
FONT_DIR = Path(__file__).resolve().parent / "fonts"
CYR_FALLBACK = ("Oswald-VF.ttf", 700)
FONT_NAMES = {"BebasNeue-Regular.ttf": "Bebas Neue", "Anton-Regular.ttf": "Anton", "Oswald-VF.ttf": "Oswald", "Montserrat-VF.ttf": "Montserrat",
              "PlayfairDisplay-VF.ttf": "Playfair Display", "Unbounded-VF.ttf": "Unbounded"}
# key: (title font, weight), (subline font, weight), title px (at 1280 wide), tracking em, subline tracking em, uppercase
LOOKS = {
    "rgb": (("BebasNeue-Regular.ttf", None), ("BebasNeue-Regular.ttf", None), 150, 0.06, 0.42, True),
    "ext": (("Anton-Regular.ttf", None), ("Anton-Regular.ttf", None), 120, 0.05, 0.42, True),
    "glow": (("Montserrat-VF.ttf", 300), ("Montserrat-VF.ttf", 500), 68, 0.34, 0.42, True),
    "shade": (("Oswald-VF.ttf", 700), ("Oswald-VF.ttf", 500), 118, 0.04, 0.42, True),
    "serif": (("PlayfairDisplay-VF.ttf", 500), ("PlayfairDisplay-VF.ttf", 500), 92, 0.10, 0.36, True),
    "hype": (("Unbounded-VF.ttf", 800), ("Unbounded-VF.ttf", 600), 70, 0.02, 0.30, True),
}
SKY_LOOKS = ("shade", "hype")      # the two looks whose colours follow the montage's sky colour family
LOOK_GROUPS = {"hype": ("rgb", "ext", "hype"), "aggressive": ("rgb", "ext", "hype"), "chill": ("glow", "serif"), "cinematic": ("glow", "serif"), "smooth": ("shade", "serif")}
DEFAULT_PAL = {"shade": dict(top=(255, 255, 255), bot=(255, 196, 70), edge=(14, 14, 22), shadow=(0, 0, 0), alpha=0.7),
               "hype": dict(top=(255, 255, 255), bot=(255, 255, 255), edge=(255, 56, 140), shadow=(0, 0, 0), alpha=0.45, accent=(255, 56, 140), ink=(18, 10, 28))}


def smooth(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


# ------------------------------------------------------------------------------------------------------------ the text
_BR = re.compile(r"\s*(\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}|【[^】]*】|（[^）]*）)")
_TAIL = re.compile(r"\s*[-–—|:]\s*(official\b.*|radio\s+edit\b.*|extended\b.*|sped\s*up\b.*|slowed\b.*|remix\b.*|lyrics?\b.*|audio\b.*|"
                   r"topic\b.*|visuali[sz]er\b.*|music\s+video\b.*)$", re.I)
_FEAT = re.compile(r"\s+(feat\.?|ft\.?|featuring)\s+.*$", re.I)
_JUNK = re.compile(r"\s*\b(official\s+(music\s+)?(video|audio)|lyric\s+video|radio\s+edit|visuali[sz]er|vevo|hd|4k)\b\s*", re.I)


def clean_title(raw, artist=None):
    """the bare song title: no brackets, no feat. / ft. parts, no Radio Edit / Official Video, no artist / channel prefix or suffix, no track number."""
    t = raw or ""
    t = re.sub(r"^\s*\d{1,2}\s*[\.\)]\s+|^\s*\d{1,2}\s+-\s+", "", t)
    for _ in range(4):
        n = _BR.sub(" ", t)
        if n == t:
            break
        t = n
    if re.search(r"[\(\[\{]", t) and not re.search(r"[\)\]\}]", t):
        t = re.sub(r"[\(\[\{].*$", "", t)
    names = [x.strip().casefold() for x in re.split(r",|&| x ", artist or "") if x.strip()]
    if artist:
        for a in [artist] + [x.strip() for x in re.split(r",|&| x ", artist) if x.strip()]:
            t = re.sub(r"^\s*" + re.escape(a) + r"\s*[-–—:|]\s+", "", t, flags=re.I)
            t = re.sub(r"\s+[-–—|]\s+" + re.escape(a) + r"\s*$", "", t, flags=re.I)
    m = re.match(r"^(.{2,80}?)\s+[-–—]\s+(.+)$", t)                 # "Artists - Title" where the left part names the artist(s)
    if m and names and any(n in m.group(1).casefold() for n in names):
        t = m.group(2)
    for _ in range(3):
        t = re.sub(r"\s+[-–—]\s+[^-–—]*\b(remix|version|mix|edit|sped up|slowed)\s*$", "", t, flags=re.I)
        t = _TAIL.sub("", t)
        t = _FEAT.sub("", t)
    t = _JUNK.sub(" ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—|:·")
    t = re.sub(r"\s+[’'`]+$", "", t).strip(" -–—|:·")
    return t or (raw or "").strip()


def pick_look(recipe, ident):
    """the montage's look from its style, deterministic: the same style + ident (seed / song) always gives the same look."""
    grp = LOOK_GROUPS.get(recipe) or LOOK_GROUPS["smooth"]
    h = 0
    for ch in str(ident):
        h = (h * 131 + ord(ch)) % 1000003
    return grp[h % len(grp)]


def _rgb(v):
    return ((v >> 16) & 255, (v >> 8) & 255, v & 255)


def _mix(c, to, k):
    return tuple(int(round(c[i] + (to[i] - c[i]) * k)) for i in range(3))


def fam_palette(fam, families, look):
    """colours of a sky-matched look from the sky colour family `fam` (families = montage.SKY_FAMILIES: fam -> (top, bottom, jump) as 0xRRGGBB): the fill is the family's bright
    (lighter) end, the outline / shadow / echo its dark or saturated end; never the dark end as fill. White family: white text with a dark shadow. Black family: light text with a dark outline."""
    top, bot, _j = (_rgb(v) for v in families[fam])
    if fam == "white":
        p = dict(top=(255, 255, 255), bot=(236, 238, 246), edge=(34, 38, 54), shadow=(0, 0, 0), alpha=0.8, accent=(120, 130, 160), ink=(10, 10, 16))
    elif fam == "black":
        p = dict(top=(246, 246, 250), bot=(214, 216, 228), edge=(6, 6, 10), shadow=(0, 0, 0), alpha=0.8, accent=(60, 60, 72), ink=(246, 246, 250))
    else:
        mid = _mix(top, bot, 0.5)
        p = dict(top=_mix(bot, (255, 255, 255), 0.35), bot=bot, edge=top, shadow=_mix(top, (0, 0, 0), 0.7), alpha=0.75, accent=mid,
                 ink=(18, 10, 28) if sum(mid) > 330 else (255, 255, 255))
    return p


def _font(cache, name, size, weight=None):
    key = (name, round(size, 1), weight)
    if key not in cache:
        f = ImageFont.truetype(str(FONT_DIR / name), max(6, int(round(size))))
        if weight is not None:
            try:
                f.set_variation_by_axes([weight])
            except Exception:                                      # noqa: BLE001
                pass
        cache[key] = f
    return cache[key]


def _has_glyphs(name, text):
    try:
        from fontTools.ttLib import TTFont
        cmap = TTFont(str(FONT_DIR / name)).getBestCmap()
        return all(ord(c) in cmap or c.isspace() for c in text)
    except Exception:                                              # noqa: BLE001
        return all(c.isascii() for c in text)


def _pick_font(spec, text):
    fname, wt = spec
    if _has_glyphs(fname, text):
        return fname, wt, None
    return CYR_FALLBACK[0], CYR_FALLBACK[1], f"{FONT_NAMES[CYR_FALLBACK[0]]} {CYR_FALLBACK[1]} (fallback: {FONT_NAMES[fname]} has no Cyrillic)"


def _spaced(text, font, sp):
    xs, x = [], 0.0
    for i, c in enumerate(text):
        xs.append(x)
        nxt = text[i + 1] if i + 1 < len(text) else ""
        adv = font.getlength(c + nxt) - font.getlength(nxt) if nxt else font.getlength(c)
        x += adv + sp
    return xs, x - sp


def _mask(text, font, sp, cx, cy):
    xs, width = _spaced(text, font, sp)
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    x0 = cx - width / 2
    for c, x in zip(text, xs):
        if c != " ":
            d.text((x0 + x, cy), c, font=font, fill=255, anchor="lm")
    return m


def _shift(m, dx, dy):
    return ImageChops.offset(m, int(round(dx)), int(round(dy)))


def _tint(mask, rgb, alpha=1.0):
    im = Image.new("RGBA", mask.size, tuple(rgb) + (0,))
    im.putalpha(mask.point(lambda v: int(v * alpha)))
    return im


def _over(a, b):
    return Image.alpha_composite(a, b)


def _vgrad(mask, c_top, c_bot):
    bb = mask.getbbox()
    im = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    if not bb:
        return im
    y0, y1 = bb[1], bb[3]
    ar = np.zeros((H, W, 4), np.uint8)
    col = np.clip((np.arange(H) - y0) / max(1, y1 - y0), 0, 1)
    for ch in range(3):
        ar[:, :, ch] = (c_top[ch] + (c_bot[ch] - c_top[ch]) * col)[:, None]
    ar[:, :, 3] = np.asarray(mask)
    return Image.fromarray(ar, "RGBA")


def _line(cache, look, text, fname, wt, size, sp_em, cy, small, pal):
    f = _font(cache, fname, size, wt)
    m = _mask(text, f, sp_em * size, W / 2, cy)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    k = K
    if look == "rgb":
        d = (2.5 if small else 4) * k
        r, b = _shift(m, -d, 0), _shift(m, d, 0)
        out = Image.merge("RGB", (r, m, b)).convert("RGBA")
        out.putalpha(ImageChops.lighter(ImageChops.lighter(r, m), b))
    elif look == "ext":
        depth = int(round((4 if small else 16) * k))
        ex, ey = 0.669, 0.743
        out = _over(out, _tint(_shift(m, depth * ex * 1.3 + 6 * k, depth * ey * 1.3 + 10 * k).filter(ImageFilter.GaussianBlur(9 * k)), (0, 0, 0), 0.55))
        for i in range(depth, 0, -1):
            t = i / depth
            out = _over(out, _tint(_shift(m, ex * i, ey * i), (int(26 + 70 * (1 - t)), int(40 + 100 * (1 - t)), int(80 + 150 * (1 - t)))))
        out = _over(out, _vgrad(m, (255, 255, 255), (205, 215, 235)))
    elif look == "glow":
        kk = (0.6 if small else 1.0) * k
        out = _over(out, _tint(m.filter(ImageFilter.GaussianBlur(16 * kk)), (0, 0, 0), 0.40))
        for rad, al in ((20, 0.9), (9, 0.95), (3, 0.8)):
            out = _over(out, _tint(m.filter(ImageFilter.GaussianBlur(rad * kk)), (130, 200, 255), al))
        out = _over(out, _tint(m, (245, 252, 255)))
    elif look == "shade":
        p = pal or DEFAULT_PAL["shade"]
        stroke = int(round((3 if small else 6) * k))
        dil = m.filter(ImageFilter.MaxFilter(2 * stroke + 1))
        out = _over(out, _tint(_shift(dil, 7 * k, 10 * k).filter(ImageFilter.GaussianBlur(5 * k)), p["shadow"], p["alpha"]))
        out = _over(out, _tint(dil, p["edge"]))
        out = _over(out, _vgrad(m, p["top"], p["bot"]))
    elif look == "serif":
        out = _over(out, _tint(_shift(m, 0, 4 * k).filter(ImageFilter.GaussianBlur(8 * k)), (0, 0, 0), 0.65))
        out = _over(out, _tint(m, (250, 243, 230) if not small else (226, 198, 140)))
    else:                                                          # hype
        p = pal or DEFAULT_PAL["hype"]
        if small:
            bb = m.getbbox()
            pill = Image.new("L", (W, H), 0)
            if bb:
                ImageDraw.Draw(pill).rounded_rectangle((bb[0] - 20 * k, bb[1] - 10 * k, bb[2] + 20 * k, bb[3] + 10 * k), 12 * k, fill=255)
            out = _over(out, _tint(pill, p["accent"]))
            out = _over(out, _tint(m, p["ink"]))
        else:
            ring = ImageChops.subtract(m.filter(ImageFilter.MaxFilter(int(round(7 * k)) | 1)), m)
            out = _over(out, _tint(_shift(ring, 8 * k, 8 * k), p["edge"] if pal else p["accent"]))
            out = _over(out, _tint(_shift(m, 4 * k, 5 * k).filter(ImageFilter.GaussianBlur(5 * k)), p["shadow"], p["alpha"]))
            out = _over(out, _vgrad(m, p["top"], p["bot"]))
    return out


def build_layer(look, title, subline=None, pal=None):
    """-> (RGBA PIL image W x H with the title (+ subline), font note). Static state; the animation is applied by `text_video`."""
    cache = {}
    size, track, strack, upper = LOOKS[look][2], LOOKS[look][3], LOOKS[look][4], LOOKS[look][5]
    tspec, sspec = LOOKS[look][0], LOOKS[look][1]
    t_txt = title.upper() if upper else title
    fname, wt, note = _pick_font(tspec, t_txt)
    sz = size * K
    for _ in range(40):
        _, wd = _spaced(t_txt, _font(cache, fname, sz, wt), track * sz)
        if wd <= 0.78 * W:
            break
        sz *= 0.94
    pal = pal if look in SKY_LOOKS else None
    if subline:
        gs = max(22 * K, min(34 * K, sz * 0.22))
        cy = H * 0.455
        gy = cy + sz * 0.62 + gs * 0.9
        tl = _line(cache, look, t_txt, fname, wt, sz, track, cy, False, pal)
        sf, sw, note2 = _pick_font(sspec, subline)
        sl = _line(cache, look, subline, sf, sw, gs, strack, gy, True, pal)
        if look == "serif":
            r = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(r).rectangle((W / 2 - 70 * K, gy - gs * 1.15, W / 2 + 70 * K, gy - gs * 1.15 + 1.5 * K), fill=(226, 198, 140, 230))
            sl = _over(r, sl)
        note = note or note2
        return _over(tl, sl), note
    return _line(cache, look, t_txt, fname, wt, sz, track, H * 0.5, False, pal), note


def _premult(img, y0, y1):
    a = np.asarray(img.crop((0, y0, W, y1)), np.float32)
    al = a[..., 3:4] / 255.0
    pm = np.concatenate([a[..., :3] * al, a[..., 3:4]], -1).clip(0, 255).astype(np.uint8)
    return [Image.fromarray(pm[..., c], "L") for c in range(4)]


def _xform(chs, s, cx, cy):
    out = []
    for im in chs:
        if abs(s - 1) > 1e-4:
            im = im.transform(im.size, Image.AFFINE, (1 / s, 0, cx - cx / s, 0, 1 / s, cy - cy / s), Image.BICUBIC)
        out.append(np.asarray(im, np.float32) / 255.0)
    return np.stack(out, -1)


def _straight(pm):
    a = pm[..., 3:4]
    rgb = pm[..., :3] / np.maximum(a, 1e-4)
    return np.concatenate([rgb.clip(0, 1), a.clip(0, 1)], -1)


def text_alpha(t):
    if t < TEXT_IN or t >= HOLD_END:
        return 0.0
    return smooth((t - TEXT_IN) / TEXT_FADE_IN) * smooth((HOLD_END - t) / TEXT_FADE_OUT)


def text_scale(t):
    return 1.0 + (SCALE_FROM - 1.0) * (1.0 - smooth((t - TEXT_IN) / SCALE_S))


def text_video(out_path, look, title, subline=None, pal=None, ffmpeg="ffmpeg", cancel=None):
    """the intro text as a video with alpha (qtrle / argb, the picture's width, a band of its height, 60 fps, INTRO_S s): look A = a slow fade with a gentle scale 104 % -> 100 %.
    Returns {"file", "y0", "h", "font"} for the overlay: overlay=0:y0."""
    layer, note = build_layer(look, title, subline, pal)
    ua = np.asarray(layer.getchannel("A"))
    ys = np.where(ua.max(axis=1) > 0)[0]
    marg = int(round(70 * K))
    y0, y1 = max(0, int(ys.min()) - marg) // 2 * 2, min(H, int(ys.max()) + marg) // 2 * 2
    cyb = (int(ys.min()) + int(ys.max())) / 2 - y0
    chs = _premult(layer, y0, y1)
    static_px = _straight(_xform(chs, 1.0, W / 2, cyb))
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-video_size", f"{W}x{y1 - y0}", "-framerate", str(FPS), "-i", "pipe:0",
           "-c:v", "qtrle", "-pix_fmt", "argb", "-t", f"{INTRO_S:.3f}", str(out_path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    blank = np.zeros((y1 - y0, W, 4), np.uint8).tobytes()
    last_s, last_px = None, None
    try:
        for n in range(int(round(INTRO_S * FPS))):
            if cancel is not None and cancel.is_set():
                break
            t = n / FPS
            al = text_alpha(t)
            if al <= 0:
                p.stdin.write(blank)
                continue
            s = round(text_scale(t), 4)
            if s != 1.0:
                if s != last_s:
                    last_px = _straight(_xform(chs, s, W / 2, cyb))
                    last_s = s
                px = last_px
            else:
                px = static_px
            fr = px.copy()
            fr[..., 3] *= al
            p.stdin.write((fr * 255 + 0.5).astype(np.uint8).tobytes())
        p.stdin.close()
    except (BrokenPipeError, OSError):
        pass
    err = p.stderr.read().decode("utf-8", "replace")
    if p.wait() != 0:
        raise RuntimeError("intro text video failed: " + err[-400:])
    return {"file": str(out_path), "y0": int(y0), "h": int(y1 - y0), "font": note or FONT_NAMES[LOOKS[look][0][0]]}


# ----------------------------------------------------------------------------------------------------------- the speed
def speeds(avail, v_end):
    """(ok, v0, hold_s, ramp_s, source seconds used) of the intro for `avail` seconds of safe footage before the take: the blurred hold at V0 (about 0.3x), slower down to V0_MIN when the clip
    has little footage, then a linear speed ramp V0 -> v_end over RAMP s (v_end = the take's own first speed: no jump at the handover)."""
    hold = INTRO_S - RAMP
    v_end = max(0.05, float(v_end))
    ramp_c = (V0 + v_end) / 2 * RAMP
    need = V0 * hold + ramp_c
    if avail >= need:
        return True, V0, hold, RAMP, need
    v0 = (avail - 0.5 * RAMP * v_end) / (hold + 0.5 * RAMP)                # slower hold; the ramp starts from the slower speed
    if v0 < V0_MIN - 1e-9:
        return False, V0_MIN, hold, RAMP, (V0_MIN * hold + (V0_MIN + v_end) / 2 * RAMP)
    return True, v0, hold, RAMP, v0 * hold + (v0 + v_end) / 2 * RAMP
