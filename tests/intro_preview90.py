"""V9.0 intro PREVIEW sheet (standalone; touches no app code, no planning / detection / render / settings).

Concept: the first take's lead-in (the source BEFORE the take's first kept frame, so before its first kill) is shown heavily
blurred and slowed (frame blending only, no optical flow), the song fades in (0.5 s), the title text appears (~0.8 s), holds, fades
out, then the picture unblurs and the speed ramps up to 1x and plays on into the real take, seamless (the source time never jumps).

Renders short samples from the newest real Valorant and CS2 plan in montage_data\\plans (first take + the plan's own song):
  * lengths 4 / 5 / 6 s (same text, same style: bold condensed + RGB split, static)
  * 5 text looks x {static, animated} at 5 s
and one contact sheet (contact_sheet.png) with frames of every sample. Nothing is rendered as a full montage.

    python tests\\intro_preview90.py [--out DIR] [--games valorant,cs2] [--quick]

Output default: <output_root>\\intro_preview_v90 (output_root from montage_data\\config.json).
Fonts (all SIL OFL) are fetched once into <out>\\fonts from github.com/google/fonts if missing.
Environment: MONTAGER_DATA overrides the data folder, MONTAGER_ROOT the repo root (as in the other tests).
"""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _root import find_root  # noqa: E402

ROOT = find_root(__file__)
DATA = Path(os.environ.get("MONTAGER_DATA") or (ROOT / "montage_data")).resolve()

W, H, FPS = 1280, 720, 60
V0 = 0.30            # slow-motion speed of the blurred hold
RAMP = 1.0           # s: unblur + speed ramp V0 -> 1x
CONT = 2.0           # s of the real take shown after the intro
FADE_IN = 0.5        # music / picture fade-in
TEXT_IN = 0.8        # text starts appearing
TEXT_FADE = 0.5      # text fade in / fade out length
GAME_NAMES = {"valorant": "VALORANT", "cs2": "COUNTER-STRIKE 2", "r6s": "RAINBOW SIX SIEGE"}

FONT_BASE = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
FONT_FILES = {   # local name -> path below FONT_BASE
    "BebasNeue-Regular.ttf": "bebasneue/BebasNeue-Regular.ttf",
    "Anton-Regular.ttf": "anton/Anton-Regular.ttf",
    "Oswald-VF.ttf": "oswald/Oswald%5Bwght%5D.ttf",
    "Montserrat-VF.ttf": "montserrat/Montserrat%5Bwght%5D.ttf",
}

# look -> (key, label, font file, variable weight or None, fallback (file, weight) when the font lacks a glyph of the title,
#          title size px, tracking em, uppercase)
STYLES = [
    ("rgb", "Bold condensed + RGB split", "BebasNeue-Regular.ttf", None, ("Oswald-VF.ttf", 700), 150, 0.06, True),
    ("ext", "3D extruded", "Anton-Regular.ttf", None, ("Oswald-VF.ttf", 700), 120, 0.05, True),
    ("glow", "Thin wide-tracked + soft glow", "Montserrat-VF.ttf", 200, None, 66, 0.34, True),
    ("shade", "Shaded / outlined + drop shadow", "Oswald-VF.ttf", 700, None, 118, 0.04, True),
    ("plain", "Clean modern sans, plain", "Montserrat-VF.ttf", 600, None, 84, 0.03, False),
]
STYLE = {s[0]: s for s in STYLES}
FONT_NAMES = {"BebasNeue-Regular.ttf": "Bebas Neue", "Anton-Regular.ttf": "Anton", "Oswald-VF.ttf": "Oswald",
              "Montserrat-VF.ttf": "Montserrat"}


# ----------------------------------------------------------------------------------------------------------------- setup
def ffbin(name):
    p = shutil.which(name)
    if not p:
        sys.exit(f"{name} not found on PATH")
    return p


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, **kw)
    if r.returncode != 0:
        sys.exit("command failed: " + " ".join(map(str, cmd[:6])) + " ...\n" + r.stderr.decode("utf-8", "replace")[-1500:])
    return r


def ensure_fonts(fdir):
    fdir.mkdir(parents=True, exist_ok=True)
    for local, rel in FONT_FILES.items():
        if not (fdir / local).exists():
            print(f"fetching font {local} (SIL OFL) from github.com/google/fonts")
            urllib.request.urlretrieve(FONT_BASE + rel, fdir / local)


def song_file(song):
    p = Path(song["path"])
    if p.exists():
        return p
    cfg = json.loads((DATA / "config.json").read_text(encoding="utf-8"))
    cand = Path(cfg.get("mp3_dir", "")) / p.name
    if cand.exists():
        return cand
    t = song.get("title", "").lower()                  # file names in the song folder are "<title> - <artist>.mp3"
    hits = sorted(Path(cfg.get("mp3_dir", "")).glob("*.mp3")) if t else []
    hits = [h for h in hits if h.name.lower().startswith(t + " - ") or h.name.lower() == t + ".mp3"]
    return hits[0] if hits else None


def need_for(L):
    """source seconds the intro consumes: slow hold at V0, then the ramp V0 -> 1."""
    return V0 * (L - RAMP) + (V0 + 1) / 2 * RAMP


def pick_plan(game, min_lead):
    """newest dry plan of `game` whose first take's clip exists, whose song file is found, and whose first take starts late
    enough in its clip to leave room for the longest intro."""
    fs = sorted((DATA / "plans").glob("*.dry.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in fs:
        d = json.loads(f.read_text(encoding="utf-8"))
        if d.get("game") != game or not d.get("takes"):
            continue
        t = d["takes"][0]
        if not Path(t["path"]).exists() or not t.get("segs"):
            continue
        if song_file(d["song"]) is None:
            continue
        t0 = t["segs"][0][0]
        if t0 < min_lead or t0 + CONT + 0.3 > t["srcs"][0].get("dur", 0):
            continue
        return f, d
    return None, None


def clean_title(t):
    t = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", t)
    t = re.sub(r"\s*[-–]\s*(radio edit|sped up|slowed.*|remix|extended.*)\s*$", "", t, flags=re.I)
    return t.strip() or t


# --------------------------------------------------------------------------------------------------------- base video
def smooth(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def build_base(game, plan, L, out):
    """intro (no text) + CONT s of the take, with music; video: remapped time (slow hold -> ramp -> 1x), frame blend, blur ramp."""
    take = plan["takes"][0]
    t0 = take["segs"][0][0]
    need = need_for(L)
    a = t0 - need
    hold = L - RAMP
    d1, d2 = V0 * hold, (V0 + 1) / 2 * RAMP
    k = (1 - V0) / (2 * RAMP)
    ST = "T"
    u = f"(({ST}-{hold})/{RAMP})"
    w = f"if(lt({ST},{hold}),1,if(gt({ST},{L}),0,1-(3*{u}*{u}-2*{u}*{u}*{u})))"
    fg = (
        f"[0:v]fps={FPS},scale={W}:{H}:flags=bicubic,setsar=1,format=yuv420p,split=3[v0][v1][v2];"
        f"[v0]trim=0:{d1:.6f},setpts=(PTS-STARTPTS)/{V0},minterpolate=fps={FPS}:mi_mode=blend[s0];"
        f"[v1]trim={d1:.6f}:{d1 + d2:.6f},setpts=(-{V0}+sqrt({V0 * V0}+4*{k}*(PTS-STARTPTS)*TB))/(2*{k})/TB,"
        f"minterpolate=fps={FPS}:mi_mode=blend[s1];"
        f"[v2]trim={d1 + d2:.6f}:{d1 + d2 + CONT:.6f},setpts=PTS-STARTPTS[s2];"
        f"[s0][s1][s2]concat=n=3:v=1:a=0,fps={FPS},split=3[a][m0][b0];"
        f"[m0]scale=640:360,gblur=sigma=4,scale={W}:{H},eq=brightness=-0.05[m];"
        f"[b0]scale=640:360,gblur=sigma=14,scale={W}:{H},eq=brightness=-0.16:saturation=0.85[b];"
        f"[m][b]blend=all_expr='A*(1-clip(2*{w}-1,0,1))+B*clip(2*{w}-1,0,1)'[x];"
        f"[a][x]blend=all_expr='A*(1-min(1,2*{w}))+B*min(1,2*{w})',fade=t=in:st=0:d={FADE_IN},format=yuv420p[v]"
    )
    sg = song_file(plan["song"])
    s0 = plan["song"]["start_t"]
    total = L + CONT
    fgp = out.with_suffix(".graph.txt")
    fgp.write_text(fg + f";[1:a]afade=t=in:st=0:d={FADE_IN},afade=t=out:st={total - 0.4:.3f}:d=0.4[aud]", encoding="utf-8")
    cmd = [ffbin("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
           "-ss", f"{a:.4f}", "-t", f"{need + CONT + 0.2:.3f}", "-i", take["path"],
           "-ss", f"{s0:.4f}", "-t", f"{total:.3f}", "-i", str(sg),
           "-filter_complex_script", str(fgp), "-map", "[v]", "-map", "[aud]", "-t", f"{total:.3f}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p", "-r", str(FPS),
           "-c:a", "pcm_s16le", "-ar", "48000", str(out)]
    run(cmd)
    fgp.unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------------------------ text layer
_fonts = {}


def get_font(fdir, fname, size, weight=None):
    key = (fname, round(size, 1), weight)
    if key not in _fonts:
        f = ImageFont.truetype(str(fdir / fname), max(6, int(round(size))))
        if weight is not None:
            try:
                f.set_variation_by_axes([weight])
            except Exception:
                pass
        _fonts[key] = f
    return _fonts[key]


def has_glyphs(fdir, fname, text):
    try:
        from fontTools.ttLib import TTFont
        cmap = TTFont(str(fdir / fname)).getBestCmap()
        return all(ord(c) in cmap or c.isspace() for c in text)
    except Exception:
        return all(c.isascii() for c in text)


def spaced_positions(text, font, sp):
    xs, x = [], 0.0
    for i, c in enumerate(text):
        xs.append(x)
        nxt = text[i + 1] if i + 1 < len(text) else ""
        adv = font.getlength(c + nxt) - font.getlength(nxt) if nxt else font.getlength(c)
        x += adv + sp
    return xs, x - sp


def line_mask(text, font, sp, cx, cy, dx=0, dy=0):
    """L-mode full-canvas mask of `text` letter-spaced, centred on (cx, cy)."""
    xs, width = spaced_positions(text, font, sp)
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    x0 = cx - width / 2 + dx
    for c, x in zip(text, xs):
        if c != " ":
            d.text((x0 + x, cy + dy), c, font=font, fill=255, anchor="lm")
    return m


def shift(m, dx, dy):
    return ImageChops.offset(m, int(round(dx)), int(round(dy)))


def tint(mask, rgb, alpha=1.0):
    im = Image.new("RGBA", mask.size, tuple(rgb) + (0,))
    im.putalpha(mask.point(lambda v: int(v * alpha)))
    return im


def over(base, top):
    return Image.alpha_composite(base, top)


def vgrad(mask, c_top, c_bot):
    """fill `mask` with a vertical gradient between its own top and bottom."""
    bb = mask.getbbox()
    im = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    if not bb:
        return im
    y0, y1 = bb[1], bb[3]
    ar = np.zeros((H, W, 4), np.uint8)
    for ch in range(3):
        col = np.clip((np.arange(H) - y0) / max(1, y1 - y0), 0, 1)
        ar[:, :, ch] = (c_top[ch] + (c_bot[ch] - c_top[ch]) * col)[:, None]
    ar[:, :, 3] = np.asarray(mask)
    return Image.fromarray(ar, "RGBA")


class TextLook:
    """renders the centred two-line text (song title main, game small) for one look at one animation state."""

    def __init__(self, fdir, style, title, game_name):
        key, _, fname, wt, fb, size, track, upper = STYLE[style]
        self.fdir, self.style, self.track = fdir, key, track
        self.title = title.upper() if upper else title
        self.game = game_name
        self.font_file, self.weight = fname, wt
        self.font_note = FONT_NAMES[fname] + (f" {wt}" if wt else "")
        if fb and not has_glyphs(fdir, fname, self.title):
            self.font_file, self.weight = fb
            self.font_note = FONT_NAMES[self.font_file] + f" {self.weight} (fallback, {FONT_NAMES[fname]} lacks these letters)"
        # shrink to fit 78 % of the width
        self.size = size
        for _ in range(30):
            f = get_font(fdir, self.font_file, self.size, self.weight)
            _, wd = spaced_positions(self.title, f, track * self.size)
            if wd <= 0.78 * W:
                break
            self.size *= 0.94
        self.gsize = max(22, min(34, self.size * 0.22))

    def state(self, prog, animated):
        if not animated:
            return dict(sp=1.0, sc=1.0, dy=0.0, e=1.0, anim=False)
        e = smooth(prog)
        return dict(sp=1.0 + 0.30 * (1 - e), sc=1.0 + 0.03 * (1 - e), dy=10.0 * (1 - e), e=e, anim=True)

    # one line, one look -> RGBA layer
    def line(self, text, size, sp_em, cy, st, small=False):
        s = size * st["sc"]
        f = get_font(self.fdir, self.font_file, s, self.weight if not small else (self.weight if self.weight and self.weight < 400 else None))
        sp = sp_em * st["sp"] * s
        cx = W / 2
        cy = cy + st["dy"]
        k = self.style
        m = line_mask(text, f, sp, cx, cy)
        out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        e = st["e"]
        if k == "rgb":
            d = (2.5 if small else 4) + (0 if not st["anim"] else 10 * (1 - e))
            r, g, b = shift(m, -d, 0), m, shift(m, d, 0)
            zero = Image.new("L", (W, H), 0)
            rgb = Image.merge("RGB", (r, g, b))
            a = ImageChops.lighter(ImageChops.lighter(r, g), b)
            out = rgb.convert("RGBA")
            out.putalpha(a)
        elif k == "ext":
            depth = 4 if small else 16
            ang = math.radians(48 + (0 if not st["anim"] else 22 * (1 - e)))
            ex, ey = math.cos(ang), math.sin(ang)
            sh = shift(m, depth * ex * 1.3 + 6, depth * ey * 1.3 + 10).filter(ImageFilter.GaussianBlur(9))
            out = over(out, tint(sh, (0, 0, 0), 0.55))
            for i in range(depth, 0, -1):
                t = i / depth
                col = (int(26 + 70 * (1 - t)), int(40 + 100 * (1 - t)), int(80 + 150 * (1 - t)))
                out = over(out, tint(shift(m, ex * i, ey * i), col))
            out = over(out, vgrad(m, (255, 255, 255), (205, 215, 235)))
        elif k == "glow":
            gk = 0.45 + 0.55 * e if st["anim"] else 1.0
            for rad, al in ((20, 0.9), (9, 0.9), (3, 0.7)):
                out = over(out, tint(m.filter(ImageFilter.GaussianBlur(rad * (0.6 if small else 1))), (120, 190, 255), min(1, al * gk)))
            out = over(out, tint(m, (240, 250, 255)))
        elif k == "shade":
            stroke = 3 if small else 6
            dil = m.filter(ImageFilter.MaxFilter(2 * stroke + 1))
            sd = 0.0 + 1.0 * (e if st["anim"] else 1.0)
            sh = shift(dil, 7 * sd, 10 * sd).filter(ImageFilter.GaussianBlur(5))
            out = over(out, tint(sh, (0, 0, 0), 0.7))
            out = over(out, tint(dil, (14, 14, 22)))
            out = over(out, vgrad(m, (255, 255, 255), (255, 196, 70)))
        else:  # plain
            out = tint(m, (255, 255, 255))
        if small:
            out.putalpha(out.getchannel("A").point(lambda v: int(v * 0.88)))
        return out

    def frame(self, prog, animated):
        st = self.state(prog, animated)
        cy = H * 0.455
        main = self.line(self.title, self.size, self.track, cy, st)
        gy = cy + self.size * 0.62 + self.gsize * 0.9
        sub = self.line(self.game, self.gsize, 0.42, gy, st, small=True)
        return np.asarray(over(main, sub)).copy()


def label_chip(fdir, text):
    f = get_font(fdir, "Montserrat-VF.ttf", 17, 600)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    wd = d.textlength(text, font=f)
    d.rounded_rectangle((14, 12, 14 + wd + 20, 12 + 32), 6, fill=(0, 0, 0, 150))
    d.text((24, 28), text, font=f, fill=(255, 255, 255, 235), anchor="lm")
    return np.asarray(im).copy()


def text_alpha(t, L):
    """text envelope: fade in from TEXT_IN, hold, fade out ending when the unblur starts."""
    hold_end = L - RAMP
    if t < TEXT_IN or t >= hold_end:
        return 0.0
    if t < TEXT_IN + TEXT_FADE:
        return smooth((t - TEXT_IN) / TEXT_FADE)
    if t > hold_end - TEXT_FADE:
        return smooth((hold_end - t) / TEXT_FADE)
    return 1.0


def render_sample(fdir, base, out, L, look, animated, title, game_name, label):
    tl = TextLook(fdir, look, title, game_name)
    total = L + CONT
    nf = int(round(total * FPS))
    hold_end = L - RAMP
    chip = label_chip(fdir, label)
    chip_box = (slice(0, 60), slice(0, 700))
    cmd = [ffbin("ffmpeg"), "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(base),
           "-f", "rawvideo", "-pix_fmt", "rgba", "-video_size", f"{W}x{H}", "-framerate", str(FPS), "-i", "pipe:0",
           "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto:eof_action=pass,format=yuv420p[v]",
           "-map", "[v]", "-map", "0:a", "-t", f"{total:.3f}",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    static_img = tl.frame(1.0, False) if not animated else None
    blank = np.zeros((H, W, 4), np.uint8)
    try:
        for n in range(nf):
            t = n / FPS
            al = text_alpha(t, L)
            if al <= 0:
                fr = blank.copy()
            else:
                img = static_img if static_img is not None else tl.frame((t - TEXT_IN) / (hold_end - TEXT_IN), True)
                fr = img.copy()
                fr[:, :, 3] = (fr[:, :, 3].astype(np.float32) * al).astype(np.uint8)
            reg = fr[chip_box]
            reg[chip[chip_box][:, :, 3] > 0] = chip[chip_box][chip[chip_box][:, :, 3] > 0]
            p.stdin.write(fr.tobytes())
        p.stdin.close()
    except BrokenPipeError:
        pass
    err = p.stderr.read().decode("utf-8", "replace")
    if p.wait() != 0:
        sys.exit("overlay encode failed:\n" + err[-1500:])
    return tl.font_note


# --------------------------------------------------------------------------------------------------------- contact sheet
def grab(video, t, size):
    r = subprocess.run([ffbin("ffmpeg"), "-hide_banner", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", str(video),
                        "-frames:v", "1", "-vf", f"scale={size[0]}:{size[1]}", "-f", "image2pipe", "-vcodec", "png", "-"],
                       capture_output=True)
    import io
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")


def contact_sheet(rows, fdir, path):
    """rows: list of ('H', header) or ('S', label lines, video path, L)."""
    cw, ch, gap, lab = 320, 180, 6, 470
    cols = 5
    hf = get_font(fdir, "Montserrat-VF.ttf", 26, 700)
    lf = get_font(fdir, "Montserrat-VF.ttf", 19, 600)
    sf = get_font(fdir, "Montserrat-VF.ttf", 15, 400)
    width = lab + cols * (cw + gap) + gap
    ys, y = [], gap
    for r in rows:
        ys.append(y)
        y += (46 if r[0] == "H" else ch + gap)
    sheet = Image.new("RGB", (width, y + gap), (18, 18, 22))
    d = ImageDraw.Draw(sheet)
    for r, y0 in zip(rows, ys):
        if r[0] == "H":
            d.text((gap + 4, y0 + 22), r[1], font=hf, fill=(255, 208, 90), anchor="lm")
            continue
        _, lines, vid, L = r
        hold_end = L - RAMP
        times = [0.35, TEXT_IN + TEXT_FADE + 0.15, (TEXT_IN + hold_end) / 2 + 0.2, hold_end + 0.45, L + 0.9]
        for i, tt in enumerate(times):
            sheet.paste(grab(vid, tt, (cw, ch)), (lab + gap + i * (cw + gap), y0))
        yy = y0 + 8
        for j, ln in enumerate(lines):
            d.text((gap + 6, yy), ln, font=lf if j == 0 else sf, fill=(255, 255, 255) if j == 0 else (190, 195, 205))
            yy += 28 if j == 0 else 22
    sheet.save(path)


# ---------------------------------------------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--games", default="valorant,cs2")
    ap.add_argument("--resume", action="store_true", help="keep samples that already exist")
    ap.add_argument("--quick", action="store_true", help="Valorant lengths + 1 look only (smoke check)")
    a = ap.parse_args()
    cfg = json.loads((DATA / "config.json").read_text(encoding="utf-8"))
    out = Path(a.out) if a.out else Path(cfg.get("output_root", str(ROOT))) / "intro_preview_v90"
    out.mkdir(parents=True, exist_ok=True)
    fdir = out / "fonts"
    ensure_fonts(fdir)
    tmp = out / "_base"
    tmp.mkdir(exist_ok=True)
    rows, info = [], []
    for game in [g.strip() for g in a.games.split(",") if g.strip()]:
        pf, plan = pick_plan(game, need_for(6) + 0.2)
        if not plan:
            print(f"no usable {game} plan (clip + song present, long enough lead-in): skipped")
            continue
        take = plan["takes"][0]
        title = clean_title(plan["song"]["title"])
        gname = GAME_NAMES.get(game, game.upper())
        gtag = {"valorant": "val", "cs2": "cs2"}.get(game, game)
        info.append(f"{game}: plan {pf.name}; first take {Path(take['path']).name} from {take['segs'][0][0]:.2f}s "
                    f"(first kill at {take['kills'][0]:.2f}s); song '{plan['song']['title']}' from {plan['song']['start_t']:.1f}s")
        print(info[-1])
        bases = {}

        def base_for(L):
            if L not in bases:
                b = tmp / f"{gtag}_{L}s.mkv"
                print(f"  base {gtag} {L}s ...", flush=True)
                build_base(game, plan, L, b)
                bases[L] = b
            return bases[L]

        done = {}

        def sample(L, look, animated):
            key = (L, look, animated)
            if key in done:
                return done[key]
            fn = f"{gtag}_{L}s_{look}_{'animated' if animated else 'static'}.mp4"
            lab = f"{game.upper()} | {L} s | {STYLE[look][1]} | {'animated' if animated else 'static'}"
            print(f"  render {fn}", flush=True)
            if a.resume and (out / fn).exists():
                note = TextLook(fdir, look, title, gname).font_note
            else:
                note = render_sample(fdir, base_for(L), out / fn, L, look, animated, title, gname, lab)
            done[key] = (out / fn, lab, note)
            return done[key]

        rows.append(("H", f"{game.upper()}: intro LENGTH (same text + look: bold condensed + RGB split, static)"))
        for L in (4, 5, 6):
            v, lab, note = sample(L, "rgb", False)
            rows.append(("S", [f"{L} s intro", f"{STYLE['rgb'][1]}, static", f"font: {note}"], v, L))
        if a.quick:
            continue
        rows.append(("H", f"{game.upper()}: TEXT LOOKS at 5 s (static, then animated)"))
        for look in STYLES:
            for anim in (False, True):
                v, lab, note = sample(5, look[0], anim)
                rows.append(("S", [f"{look[1]}", f"{'animated' if anim else 'static'}, 5 s", f"font: {note}"], v, 5))
    if rows:
        contact_sheet(rows, fdir, out / "contact_sheet.png")
    shutil.rmtree(tmp, ignore_errors=True)
    (out / "README.txt").write_text(
        "V9.0 intro preview (standalone, no app change)\n" + "\n".join(info) + "\n\n"
        "Per sample: lead-in of the first take blurred (sigma ~28 px at 1280x720) + slowed to 0.3x with frame blending only,\n"
        "music fades in 0.5 s, text in at 0.8 s (0.5 s fade), hold, 0.5 s fade out, then 1 s unblur + speed ramp 0.3x -> 1x,\n"
        "then 2 s of the real take at 1x (source time continuous). 1280x720 @60, music only (no game audio).\n"
        "Fonts (SIL OFL): Bebas Neue, Anton, Oswald, Montserrat (Cyrillic titles fall back to Oswald where Bebas / Anton lack the letters).\n",
        encoding="utf-8")
    print("done:", out)


if __name__ == "__main__":
    main()
