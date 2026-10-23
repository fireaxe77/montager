"""V9.0 intro PREVIEW sheet, round 2 (standalone; touches no app code, no planning / detection / render / settings).

Same concept and same real first takes + songs as round 1 (tests/intro_preview90.py, imported for the shared intro video), all samples 7 s:
  * six looks: bold condensed + RGB split (Bebas Neue), 3D extruded (Anton), thin wide-tracked + glow (Montserrat 300),
    shaded / outlined + drop shadow (Oswald Bold), cinematic serif (Playfair Display), modern wide hype (Unbounded)
  * four calm versions each: static | A slow fade + scale 104 % -> 100 % | B focus pull (blur -> sharp while fading in) |
    C title then subline one after the other with ~10 px upward drift
  * main line = cleaned song title, small subline "VALORANT · SERIES #14" / "CS2 · SERIES #9"
  * README with the raw filename and the cleaned title of 15 library songs; one contact sheet.

    python tests\\intro_preview90b.py [--out DIR] [--fonts DIR] [--jobs N] [--resume] [--games valorant,cs2]

Output default: <output_root>\\intro_preview_v90_round2 (round 1's folder is never touched; its fonts folder is reused).
"""
import argparse
import json
import os
import re
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import intro_preview90 as r1  # noqa: E402
from intro_preview90 import (DATA, FPS, H, RAMP, TEXT_FADE, TEXT_IN, W, build_base, ffbin, get_font, has_glyphs,  # noqa: E402
                             grab, line_mask, need_for, over, shift, smooth, song_file, spaced_positions, tint, vgrad)

L = 7
HOLD_END = L - RAMP          # text is gone when the unblur starts
TOTAL = L + r1.CONT
PLANS = {"valorant": "Valorant_2026-W42_909624.dry.json", "cs2": "CS2_2026-W41_40176.dry.json"}   # round 1's takes
SERIES = {"valorant": ("VALORANT", 14), "cs2": ("CS2", 9)}
GTAG = {"valorant": "val", "cs2": "cs2"}

r1.FONT_FILES.update({
    "PlayfairDisplay-VF.ttf": "playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
    "Unbounded-VF.ttf": "unbounded/Unbounded%5Bwght%5D.ttf",
})
FONT_NAMES = dict(r1.FONT_NAMES, **{"PlayfairDisplay-VF.ttf": "Playfair Display", "Unbounded-VF.ttf": "Unbounded"})
CYR_FALLBACK = ("Oswald-VF.ttf", 700)

# key, label, (title font, weight), (subline font, weight), title px, tracking em, subline tracking em, uppercase
LOOKS = [
    ("rgb", "Bold condensed + RGB split", ("BebasNeue-Regular.ttf", None), ("BebasNeue-Regular.ttf", None), 150, 0.06, 0.42, True),
    ("ext", "3D extruded", ("Anton-Regular.ttf", None), ("Anton-Regular.ttf", None), 120, 0.05, 0.42, True),
    ("glow", "Thin wide-tracked + glow", ("Montserrat-VF.ttf", 300), ("Montserrat-VF.ttf", 500), 68, 0.34, 0.42, True),
    ("shade", "Shaded / outlined + drop shadow", ("Oswald-VF.ttf", 700), ("Oswald-VF.ttf", 500), 118, 0.04, 0.42, True),
    ("serif", "Cinematic serif", ("PlayfairDisplay-VF.ttf", 500), ("PlayfairDisplay-VF.ttf", 500), 92, 0.10, 0.36, True),
    ("hype", "Modern wide hype", ("Unbounded-VF.ttf", 800), ("Unbounded-VF.ttf", 600), 70, 0.02, 0.30, True),
]
LOOK = {k[0]: k for k in LOOKS}
VERSIONS = [("static", "static (fade in / out only)"), ("A", "A: slow fade + scale 104% -> 100%"),
            ("B", "B: focus pull (blur -> sharp)"), ("C", "C: title, then subline, ~10 px upward drift")]


# ---------------------------------------------------------------------------------- sky colour family (gold look only)
GOLD_LOOK = "shade"          # the look whose text is gold in the sheet: white -> gold gradient fill (255, 196, 70), dark outline + shadow
GOLD_DEFAULT = dict(top=(255, 255, 255), bot=(255, 196, 70), edge=(14, 14, 22), shadow=(0, 0, 0), alpha=0.7)
_montage = []


def montage_mod():
    """the app's own module, imported only to CALL its sky colour choice (no second choice is made here, nothing of it is changed)."""
    if not _montage:
        sys.path.insert(0, str(r1.ROOT))
        os.environ.setdefault("MONTAGER_DATA", str(DATA))
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import montage
        _montage.append(montage)
    return _montage[0]


def _rgb(v):
    return ((v >> 16) & 255, (v >> 8) & 255, v & 255)


def _mix(c, to, k):
    return tuple(int(round(c[i] + (to[i] - c[i]) * k)) for i in range(3))


def fam_palette(fam):
    """text colours of the gold look for a sky colour family: fill = the family's bright (lighter) end, edge / shadow = its dark / saturated end.
    White family: white text, dark shadow. Black family: light text, dark outline. The dark end is never a fill."""
    top, bot, _ = (_rgb(v) for v in montage_mod().SKY_FAMILIES[fam])
    if fam == "white":
        return dict(top=(255, 255, 255), bot=(236, 238, 246), edge=(34, 38, 54), shadow=(0, 0, 0), alpha=0.8)
    if fam == "black":
        return dict(top=(246, 246, 250), bot=(214, 216, 228), edge=(6, 6, 10), shadow=(0, 0, 0), alpha=0.8)
    return dict(top=_mix(bot, (255, 255, 255), 0.35), bot=bot, edge=top, shadow=_mix(top, (0, 0, 0), 0.7), alpha=0.75)


def sky_family_of(plan, cfg):
    """the montage's sky colour family = montage.sky_family_for() called with the real song (album cover if the MP3 has one, else the song's vibe).
    The vibe order is the plan's own xfx_sky_rank; a plan made without extra effects has none, so it is computed exactly as the planner does
    (sky_ranked(recipe, energy from the playlist csv, bpm))."""
    m = montage_mod()
    song = dict(plan["song"])
    sp = song_file(song)
    if sp is not None:
        song["path"] = str(sp)                                  # the plan's own path may be from another folder: same file, found here
    pl = dict(plan, song=song)
    rk = (plan.get("xfx_sky_rank") or {}).get("names")
    src = "plan xfx_sky_rank"
    if not rk:
        en = None
        try:
            _, rows, _c = m.read_playlist(cfg)
            tt = m.clean(song.get("title"))
            for r in rows:
                if m.clean(r["title"]) == tt and (not song.get("artist") or m.clean(song["artist"])[:6] in m.clean(r["artist"])):
                    en = r["energy"]
                    break
        except Exception:                                      # noqa: BLE001
            en = None
        rk, _w = m.sky_ranked(plan.get("recipe"), en, song.get("bpm"))
        src = f"sky_ranked(recipe {plan.get('recipe')}, energy {en}, bpm {song.get('bpm')})"
    fam, why = m.sky_family_for(pl, rk, None)
    return fam, f"{why} [ranking: {src}]"


# ------------------------------------------------------------------------------------------------------- title cleaning
_BR = re.compile(r"\s*(\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}|【[^】]*】|（[^）]*）)")
_TAIL = re.compile(r"\s*[-–—|:]\s*(official\b.*|radio\s+edit\b.*|extended\b.*|sped\s*up\b.*|slowed\b.*|remix\b.*|lyrics?\b.*|audio\b.*|"
                   r"topic\b.*|visuali[sz]er\b.*|music\s+video\b.*)$", re.I)
_FEAT = re.compile(r"\s+(feat\.?|ft\.?|featuring)\s+.*$", re.I)
_JUNK = re.compile(r"\s*\b(official\s+(music\s+)?(video|audio)|lyric\s+video|radio\s+edit|visuali[sz]er|vevo|hd|4k)\b\s*", re.I)


def clean_title(raw, artist=None):
    """song title for the intro: no brackets, no feat./ft. parts, no Radio Edit / Official Video, no artist / channel prefix."""
    t = raw
    t = re.sub(r"^\s*\d{1,2}\s*[\.\)]\s+|^\s*\d{1,2}\s+-\s+", "", t)         # track number
    for _ in range(4):
        n = _BR.sub(" ", t)
        if n == t:
            break
        t = n
    t = re.sub(r"[\(\[\{].*$", "", t) if re.search(r"[\(\[\{]", t) and not re.search(r"[\)\]\}]", t) else t
    if artist:
        for a in [artist] + [x.strip() for x in re.split(r",|&| x ", artist) if x.strip()]:
            t = re.sub(r"^\s*" + re.escape(a) + r"\s*[-–—:|]\s+", "", t, flags=re.I)      # "Artist - Title"
            t = re.sub(r"\s+[-–—|]\s+" + re.escape(a) + r"\s*$", "", t, flags=re.I)       # "Title - Artist"
    # "Artists - Title" / "Artists – Title" where the left part names the file's artist(s) (artist / channel prefix)
    names = [x.strip().casefold() for x in re.split(r",|&| x ", artist or "") if x.strip()]
    m = re.match(r"^(.{2,80}?)\s+[-–—]\s+(.+)$", t)
    if m and names and any(n in m.group(1).casefold() for n in names):
        t = m.group(2)
    for _ in range(3):
        t = re.sub(r"\s+[-–—]\s+[^-–—]*\b(remix|version|mix|edit|sped up|slowed)\s*$", "", t, flags=re.I)
        t = _TAIL.sub("", t)
        t = _FEAT.sub("", t)
    t = _JUNK.sub(" ", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—|:·")
    t = re.sub(r"\s+[’'`]+$", "", t) if re.search(r"\s[’'`]+$", t) else re.sub(r"[’`]+$", "", t) if t.endswith("’") and t.count("’") == 1 and "'" not in t[:-1] and len(t) > 3 and not t[-2].isalpha() else t
    t = t.strip(" -–—|:·")
    return t or raw.strip()


def title_from_filename(stem):
    """library files are '<title> - <artist(s)>.mp3': the part after the LAST ' - ' is the artist."""
    if " - " in stem:
        title, artist = stem.rsplit(" - ", 1)
        return clean_title(title, artist), artist
    return clean_title(stem), ""


def pick_songs(mp3_dir, n=15):
    files = sorted(p.name for p in Path(mp3_dir).glob("*.mp3"))
    cyr = [f for f in files if re.search("[А-Яа-яЁё]", f)]
    brk = [f for f in files if re.search(r"[\(\[]", f) or re.search(r"\b(feat|ft)\b\.?", f, re.I)]
    cyb = [f for f in cyr if re.search(r"[\(\[]", f)]
    jnk = [f for f in files if re.search(r"official|radio edit|remix|sped up|slowed", f, re.I)]
    out = []

    def take(lst, k):
        step = max(1, len(lst) // (k + 1))
        for f in lst[step - 1::step]:
            if f not in out and k > 0:
                out.append(f)
                k -= 1

    take(cyb, 3)
    take(cyr, 4)
    take(brk, 4)
    take(jnk, 2)
    take(files, n - len(out) + 2)
    return out[:n]


# --------------------------------------------------------------------------------------------------------------- looks
def pick_font(fdir, spec, text):
    fname, wt = spec
    if has_glyphs(fdir, fname, text):
        return fname, wt, None
    return CYR_FALLBACK[0], CYR_FALLBACK[1], f"{FONT_NAMES[CYR_FALLBACK[0]]} {CYR_FALLBACK[1]} (fallback: {FONT_NAMES[fname]} has no Cyrillic)"


def render_line(fdir, look, text, fname, wt, size, sp_em, cy, small, pal=None):
    f = get_font(fdir, fname, size, wt)
    m = line_mask(text, f, sp_em * size, W / 2, cy)
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if look == "rgb":
        d = 2.5 if small else 4
        r, b = shift(m, -d, 0), shift(m, d, 0)
        out = Image.merge("RGB", (r, m, b)).convert("RGBA")
        out.putalpha(ImageChops.lighter(ImageChops.lighter(r, m), b))
    elif look == "ext":
        depth = 4 if small else 16
        ex, ey = 0.669, 0.743
        out = over(out, tint(shift(m, depth * ex * 1.3 + 6, depth * ey * 1.3 + 10).filter(ImageFilter.GaussianBlur(9)), (0, 0, 0), 0.55))
        for i in range(depth, 0, -1):
            t = i / depth
            out = over(out, tint(shift(m, ex * i, ey * i), (int(26 + 70 * (1 - t)), int(40 + 100 * (1 - t)), int(80 + 150 * (1 - t)))))
        out = over(out, vgrad(m, (255, 255, 255), (205, 215, 235)))
    elif look == "glow":
        k = 0.6 if small else 1.0
        out = over(out, tint(m.filter(ImageFilter.GaussianBlur(16 * k)), (0, 0, 0), 0.40))          # dark underlay: legible over the blur
        for rad, al in ((20, 0.9), (9, 0.95), (3, 0.8)):
            out = over(out, tint(m.filter(ImageFilter.GaussianBlur(rad * k)), (130, 200, 255), al))
        out = over(out, tint(m, (245, 252, 255)))
    elif look == "shade":
        stroke = 3 if small else 6
        dil = m.filter(ImageFilter.MaxFilter(2 * stroke + 1))
        pal = pal or GOLD_DEFAULT
        out = over(out, tint(shift(dil, 7, 10).filter(ImageFilter.GaussianBlur(5)), pal["shadow"], pal["alpha"]))
        out = over(out, tint(dil, pal["edge"]))
        out = over(out, vgrad(m, pal["top"], pal["bot"]))
    elif look == "serif":
        out = over(out, tint(shift(m, 0, 4).filter(ImageFilter.GaussianBlur(8)), (0, 0, 0), 0.65))
        out = over(out, tint(m, (250, 243, 230) if not small else (226, 198, 140)))
    else:  # hype
        if small:
            bb = m.getbbox()
            pill = Image.new("L", (W, H), 0)
            if bb:
                ImageDraw.Draw(pill).rounded_rectangle((bb[0] - 20, bb[1] - 10, bb[2] + 20, bb[3] + 10), 12, fill=255)
            out = over(out, tint(pill, (255, 56, 140)))
            out = over(out, tint(m, (18, 10, 28)))
        else:
            ring = ImageChops.subtract(m.filter(ImageFilter.MaxFilter(7)), m)
            out = over(out, tint(shift(ring, 8, 8), (255, 56, 140)))
            out = over(out, tint(shift(m, 4, 5).filter(ImageFilter.GaussianBlur(5)), (0, 0, 0), 0.45))
            out = over(out, tint(m, (255, 255, 255)))
    return out


def rule_layer(look, cy):
    """cinematic serif: thin gold rule between the two lines"""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if look == "serif":
        ImageDraw.Draw(im).rectangle((W / 2 - 70, cy, W / 2 + 70, cy + 1), fill=(226, 198, 140, 230))
    return im


def build_layers(fdir, look, title, subline, fam=None):
    """-> (title RGBA, subline RGBA, notes) full canvas, static state."""
    _, _, tspec, sspec, size, track, strack, upper = LOOK[look]
    t_txt = title.upper() if upper else title
    fname, wt, note1 = pick_font(fdir, tspec, t_txt)
    sz = size
    for _ in range(40):
        _, wd = spaced_positions(t_txt, get_font(fdir, fname, sz, wt), track * sz)
        if wd <= 0.78 * W:
            break
        sz *= 0.94
    gs = max(22, min(34, sz * 0.22))
    sf, sw, note2 = pick_font(fdir, sspec, subline)
    cy = H * 0.455
    gy = cy + sz * 0.62 + gs * 0.9
    pal = fam_palette(fam) if (fam and look == GOLD_LOOK) else None
    tl = render_line(fdir, look, t_txt, fname, wt, sz, track, cy, False, pal)
    sl = render_line(fdir, look, subline, sf, sw, gs, strack, gy, True, pal)
    sl = over(rule_layer(look, gy - gs * 1.15), sl)
    notes = [n for n in (note1, note2) if n]
    base = f"{FONT_NAMES[tspec[0]]}" + (f" {tspec[1]}" if tspec[1] else "")
    return tl, sl, (notes[0] if notes else base)


def premult_band(img, y0, y1):
    a = np.asarray(img.crop((0, y0, W, y1)), np.float32)
    al = a[..., 3:4] / 255.0
    pm = np.concatenate([a[..., :3] * al, a[..., 3:4]], -1).clip(0, 255).astype(np.uint8)
    return [Image.fromarray(pm[..., c], "L") for c in range(4)]


def xform(chs, s, ty, blur, cx, cy):
    out = []
    for im in chs:
        if abs(s - 1) > 1e-4 or abs(ty) > 1e-3:
            im = im.transform(im.size, Image.AFFINE, (1 / s, 0, cx - cx / s, 0, 1 / s, cy - (cy + ty) / s), Image.BICUBIC)
        if blur > 0.3:
            im = im.filter(ImageFilter.GaussianBlur(blur))
        out.append(np.asarray(im, np.float32) / 255.0)
    return np.stack(out, -1)


def to_straight(pm):
    a = pm[..., 3:4]
    rgb = pm[..., :3] / np.maximum(a, 1e-4)
    return np.concatenate([rgb.clip(0, 1), a.clip(0, 1)], -1)


def env_out(t):
    return smooth((HOLD_END - t) / TEXT_FADE)


def params(version, t):
    """per line (title, subline): (alpha, scale, ty, blur); every version is calm: no tracking / flicker / shake."""
    out = env_out(t)
    if version == "static":
        a = smooth((t - TEXT_IN) / 0.5) * out
        return (a, 1, 0, 0), (a, 1, 0, 0)
    if version == "A":
        a = smooth((t - TEXT_IN) / 0.9) * out
        s = 1 + 0.04 * (1 - smooth((t - TEXT_IN) / 3.2))
        return (a, s, 0, 0), (a, s, 0, 0)
    if version == "B":
        a = smooth((t - TEXT_IN) / 0.5) * out
        bl = 18 * (1 - smooth((t - TEXT_IN) / 1.1))
        return (a, 1, 0, bl), (a, 1, 0, bl)
    ta, sa = (smooth((t - TEXT_IN) / 0.6), smooth((t - TEXT_IN - 0.7) / 0.6))
    return (ta * out, 1, 10 * (1 - ta), 0), (sa * out, 1, 10 * (1 - sa), 0)


def chip_png(fdir, lines, path):
    f = get_font(fdir, "Montserrat-VF.ttf", 17, 600)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    wd = max(d.textlength(x, font=f) for x in lines)
    d.rounded_rectangle((14, 12, 14 + wd + 20, 12 + 12 + 25 * len(lines)), 6, fill=(0, 0, 0, 150))
    for i, x in enumerate(lines):
        d.text((24, 29 + 25 * i), x, font=f, fill=(255, 255, 255, 235), anchor="lm")
    im.save(path)


def render_sample(job):
    import subprocess
    fdir, base, out, look, version, title, subline, label = (Path(job[0]), Path(job[1]), Path(job[2]), job[3], job[4], job[5], job[6], job[7])
    tl, sl, note = build_layers(fdir, look, title, subline, job[8])
    ua = np.maximum(np.asarray(tl.getchannel("A")), np.asarray(sl.getchannel("A")))
    ys = np.where(ua.max(axis=1) > 0)[0]
    y0, y1 = max(0, int(ys.min()) - 90), min(H, int(ys.max()) + 90)
    cyb = (int(ys.min()) + int(ys.max())) / 2 - y0
    pt, ps = premult_band(tl, y0, y1), premult_band(sl, y0, y1)
    base_pm = xform(pt, 1, 0, 0, W / 2, cyb), xform(ps, 1, 0, 0, W / 2, cyb)
    static_pm = base_pm[0] + base_pm[1] * (1 - base_pm[0][..., 3:4])
    static_px = to_straight(static_pm)
    chip = out.with_suffix(".chip.png")
    chip_png(fdir, label, chip)
    cmd = [ffbin("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error", "-i", str(base),
           "-loop", "1", "-framerate", str(FPS), "-i", str(chip),
           "-f", "rawvideo", "-pix_fmt", "rgba", "-video_size", f"{W}x{y1 - y0}", "-framerate", str(FPS), "-i", "pipe:0",
           "-filter_complex", f"[0:v][1:v]overlay=0:0:format=auto[x];[x][2:v]overlay=0:{y0}:format=auto:eof_action=pass,format=yuv420p[v]",
           "-map", "[v]", "-map", "0:a", "-t", f"{TOTAL:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
           "-pix_fmt", "yuv420p", "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    blank = np.zeros((y1 - y0, W, 4), np.uint8).tobytes()
    try:
        for n in range(int(round(TOTAL * FPS))):
            t = n / FPS
            (ta, ts, tty, tb), (sa, ss, sty, sb) = params(version, t)
            if ta <= 0 and sa <= 0:
                p.stdin.write(blank)
                continue
            if version in ("static",) or (ts == 1 and ss == 1 and tty == 0 and sty == 0 and tb == 0 and sb == 0 and abs(ta - sa) < 1e-6):
                px = static_px.copy()
                px[..., 3] *= ta
            else:
                a = xform(pt, ts, tty, tb, W / 2, cyb) * ta
                b = xform(ps, ss, sty, sb, W / 2, cyb) * sa
                px = to_straight(a + b * (1 - a[..., 3:4]))
            p.stdin.write((px * 255 + 0.5).astype(np.uint8).tobytes())
        p.stdin.close()
    except BrokenPipeError:
        pass
    err = p.stderr.read().decode("utf-8", "replace")
    chip.unlink(missing_ok=True)
    if p.wait() != 0:
        raise RuntimeError(f"encode failed {out.name}: {err[-800:]}")
    return str(out), note


# ------------------------------------------------------------------------------------------------------- contact sheet
def contact_sheet(rows, fdir, path, games):
    cw, ch, gap, pad = 288, 162, 4, 8
    times = [1.0, 1.6, 3.5, 5.75]
    hf = get_font(fdir, "Montserrat-VF.ttf", 26, 700)
    lf = get_font(fdir, "Montserrat-VF.ttf", 17, 600)
    block = len(times) * (cw + gap)
    width = pad * 2 + len(games) * block + (len(games) - 1) * 16
    ys, y = [], pad
    for r in rows:
        ys.append(y)
        y += 44 if r[0] == "H" else (r[1][0][1].height + 30 if r[0] == "F" else ch + 30)
    sheet = Image.new("RGB", (width, y + pad), (18, 18, 22))
    d = ImageDraw.Draw(sheet)
    for r, y0 in zip(rows, ys):
        if r[0] == "H":
            d.text((pad, y0 + 22), r[1], font=hf, fill=(255, 208, 90), anchor="lm")
            continue
        if r[0] == "F":
            for i, (name, im) in enumerate(r[1]):
                x0 = pad + i * (im.width + gap)
                sheet.paste(im, (x0, y0))
                d.rounded_rectangle((x0 + 4, y0 + 4, x0 + 12 + d.textlength(name, font=lf), y0 + 28), 4, fill=(0, 0, 0))
                d.text((x0 + 8, y0 + 7), name, font=lf, fill=(255, 255, 255))
            d.text((pad, y0 + r[1][0][1].height + 6), r[2], font=lf, fill=(235, 238, 245))
            continue
        _, vids, cap = r
        for gi, v in enumerate(vids):
            for i, tt in enumerate(times):
                sheet.paste(grab(v, tt, (cw, ch)), (pad + gi * (block + 16) + i * (cw + gap), y0))
        d.text((pad, y0 + ch + 6), cap, font=lf, fill=(235, 238, 245))
    sheet.save(path)


# ---------------------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--fonts", default="")
    ap.add_argument("--games", default="valorant,cs2")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    cfg = json.loads((DATA / "config.json").read_text(encoding="utf-8"))
    root_out = Path(cfg.get("output_root", str(r1.ROOT)))
    out = Path(a.out) if a.out else root_out / "intro_preview_v90_round2"
    out.mkdir(parents=True, exist_ok=True)
    fdir = Path(a.fonts) if a.fonts else (root_out / "intro_preview_v90" / "fonts")
    r1.ensure_fonts(fdir)
    tmp = out / "_base"
    tmp.mkdir(exist_ok=True)
    games, jobs, meta, info = [g.strip() for g in a.games.split(",") if g.strip()], [], {}, []
    fams, bases, meta_titles = {}, {}, {}
    for g in games:
        pf = DATA / "plans" / PLANS[g]
        if pf.exists():
            plan = json.loads(pf.read_text(encoding="utf-8"))
        else:
            pf, plan = r1.pick_plan(g, need_for(L) + 0.2)
        take = plan["takes"][0]
        raw_title = plan["song"]["title"]
        title = clean_title(raw_title, plan["song"].get("artist"))
        fam, fam_why = sky_family_of(plan, cfg)
        fams[g] = (fam, fam_why)
        gname, num = SERIES[g]
        sub = f"{gname} · SERIES #{num}"
        meta_titles[g] = (title, sub)
        info.append(f"{g}: plan {Path(pf).name}; first take {Path(take['path']).name} from {take['segs'][0][0]:.2f}s (first kill {take['kills'][0]:.2f}s); "
                    f"sky colour family {fam} ({fam_why}); song file {song_file(plan['song']).name}; tag title '{raw_title}' -> '{title}'; subline '{sub}'")
        print(info[-1])
        b = tmp / f"{GTAG[g]}_{L}s.mkv"
        bases[g] = b
        if not (a.resume and b.exists()):
            print(f"  base {g} ...", flush=True)
            build_base(g, plan, L, b)
        for look in LOOKS:
            for ver, _ in VERSIONS:
                fn = out / f"{GTAG[g]}_{look[0]}_{ver}.mp4"
                label = [f"{g.upper()} | {look[1]} | {dict(VERSIONS)[ver]}"]
                gold = look[0] == GOLD_LOOK
                note = build_layers(fdir, look[0], title, sub, fam if gold else None)[2]
                if gold:
                    label[0] += f" | sky family: {fam}"
                if "fallback" in note:
                    label.append(f"font: {note}")
                meta[(g, look[0], ver)] = (fn, note)
                if not (a.resume and fn.exists()):
                    jobs.append((str(fdir), str(b), str(fn), look[0], ver, title, sub, label, fam if gold else None))
    print(f"{len(jobs)} samples to render with {a.jobs} workers", flush=True)
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for res in ex.map(render_sample, jobs):
            print("  done", Path(res[0]).name, flush=True)
    rows = []
    for look in LOOKS:
        rows.append(("H", look[1]))
        for ver, vname in VERSIONS:
            vids = [meta[(g, look[0], ver)][0] for g in games]
            fonts = " | ".join(f"{GTAG[g]}: {meta[(g, look[0], ver)][1]}" for g in games)
            famtxt = ("   sky family: " + ", ".join(f"{GTAG[g]} {fams[g][0]}" for g in games)) if look[0] == GOLD_LOOK else ""
            rows.append(("S", vids, f"{look[1]} - {vname}   ({fonts}){famtxt}"))
    # extra row: the gold look in all ten colour families, same text, over the blurred footage of the first game
    g0 = games[0]
    frame = grab(bases[g0], 3.5, (W, H)).convert("RGBA")
    cells = []
    for fam in montage_mod().SKY_FAMILIES:
        tl, sl, _n = build_layers(fdir, GOLD_LOOK, meta_titles[g0][0], meta_titles[g0][1], fam)
        cells.append((fam + (" *" if fam == fams[g0][0] else ""), over(over(frame, tl), sl).convert("RGB").resize((224, 126), Image.LANCZOS)))
    rows.append(("H", f"{LOOK[GOLD_LOOK][1]}: all ten sky colour families (same text, {g0}; * = this montage's family)"))
    rows.append(("F", cells, "fill = the family's bright end, edge / shadow = its dark end; white: white + dark shadow; black: light text + dark outline"))
    contact_sheet(rows, fdir, out / "contact_sheet.png", games)
    shutil.rmtree(tmp, ignore_errors=True)
    lines = ["V9.0 intro preview, round 2 (standalone, no app change)", ""] + info + ["",
             "All samples 7 s, 1280x720 @60, music only. Timeline: music + picture fade-in 0.5 s, text in at 0.8 s, hold, 0.5 s fade out ending at 6 s,",
             "1 s unblur + speed ramp 0.3x -> 1x (6-7 s), then 2 s of the real take at 1x.",
             "Versions: static = fade in/out only; A = slow fade + scale 104% -> 100%; B = focus pull (blur 18 px -> sharp in 1.1 s while fading in);",
             "C = title fades in, subline 0.7 s later, both drift up ~10 px. No tracking change, no flicker, no shake in any version.",
             "GOLD LOOK (" + LOOK[GOLD_LOOK][1] + ") ONLY takes its colours from the montage's sky colour family (montage.sky_family_for with the real song, no second choice): "
             + "; ".join(f"{g}: {fams[g][0]}" for g in games) + ". Fill = the family's bright end, edge / shadow = its dark / saturated end. All other looks keep their fixed colours.",
             "Fonts (SIL OFL): " + ", ".join(sorted(set(FONT_NAMES.values()))) +
             f". Where a title has letters the look's font lacks (Bebas Neue / Anton have no Cyrillic) Oswald Bold is used and the label says so.", "",
             "TITLE CLEANING CHECK (library file name -> main line). Rules: bracket groups ( ) [ ] { } removed; trailing / inline feat. / ft. / featuring",
             "removed (a 'with ...' part is only removed when it is in brackets); ' - Radio Edit', 'Official (Music) Video / Audio', Lyric Video, Visualizer,",
             "Remix / Extended / Sped up / Slowed tails and VEVO / Topic removed; leading track number removed; the artist(s) after the last ' - '",
             "of the file name (library convention '<title> - <artists>.mp3') are dropped, and an 'Artist - ' prefix too when the artist is known.", ""]
    for f in pick_songs(cfg.get("mp3_dir", "")):
        t, art = title_from_filename(Path(f).stem)
        lines.append(f"  {f}\n      -> {t}      [artist part: {art or '-'}]")
    (out / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("done:", out)


if __name__ == "__main__":
    main()
