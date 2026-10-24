"""Draws the packaging art (run once; the results are committed):
  packaging/assets/montager.ico      EXE / installer / shortcut icon (16 .. 256 px)
  packaging/assets/montager_512.png  the same icon as a PNG
  docs/images/social_preview.png     1280x640 GitHub social preview (icon, one line of text, a frame of the launch ad)

python packaging/make_art.py [path to the launch ad .mp4]
Only reads the ad video (one frame, through ffmpeg); never touches the app or its data."""
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "packaging" / "assets"
LIME = (163, 230, 53)            # the app's default accent (ACCENT_DEF["lime"] = #a3e635)
DARK = (24, 26, 22)
FONT = ROOT / "fonts" / "Anton-Regular.ttf"
AD = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Desktop" / "montager_ad" / "brag.mp4"


def icon(size=1024):
    """Dark rounded square, a bold lime M and a short killfeed-row bar under it (a lime 'kill' cell + a dim 'victim' cell)."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = size * 0.2
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=r, fill=DARK + (255,))
    f = ImageFont.truetype(str(FONT), int(size * 0.66))
    box = d.textbbox((0, 0), "M", font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    d.text(((size - w) / 2 - box[0], size * 0.13 - box[1]), "M", font=f, fill=LIME + (255,))
    y0, y1 = size * 0.78, size * 0.86
    d.rounded_rectangle((size * 0.17, y0, size * 0.55, y1), radius=size * 0.03, fill=LIME + (255,))
    d.rounded_rectangle((size * 0.60, y0, size * 0.83, y1), radius=size * 0.03, fill=(90, 96, 84, 255))
    return im


def ad_frame(t=10.5):
    tmp = Path(tempfile.mkdtemp()) / "frame.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(t), "-i", str(AD), "-frames:v", "1", str(tmp)], check=True)
    im = Image.open(tmp).convert("RGB")
    W = im.width
    shot = im.crop((0, int(im.height * 0.222), W, int(im.height * 0.59)))       # the gameplay panel of the vertical ad
    # blur the HUD strip and the killfeed corner: player names stay unreadable
    for box in ((0, 0, shot.width, int(shot.height * 0.07)), (int(shot.width * 0.80), 0, shot.width, int(shot.height * 0.30))):
        shot.paste(shot.crop(box).filter(ImageFilter.GaussianBlur(10)), box)
    return shot


def social(icon_im):
    W, H = 1280, 640
    canvas = Image.new("RGB", (W, H), DARK)
    try:
        shot = ad_frame()
        sh = shot.resize((int(shot.width * H / shot.height), H), Image.LANCZOS)
        sh = sh.crop((sh.width - 760, 0, sh.width, H))                            # the right part of the frame (the gun and the kill)
        x0 = W - sh.width
        canvas.paste(sh, (x0, 0))
        fade = Image.new("L", (W, H), 0)                                          # dark on the left, the frame shows on the right
        fd = ImageDraw.Draw(fade)
        for x in range(W):
            a = 255 if x < x0 else max(0, int(255 * (1 - (x - x0) / 300)))
            fd.line([(x, 0), (x, H)], fill=a)
        canvas = Image.composite(Image.new("RGB", (W, H), DARK), canvas, fade)
    except Exception as ex:                                                       # noqa: BLE001
        print("no ad frame:", ex)
    d = ImageDraw.Draw(canvas)
    ic = icon_im.resize((150, 150), Image.LANCZOS)
    canvas.paste(ic, (80, 150), ic)
    title = ImageFont.truetype(str(FONT), 120)
    d.text((255, 140), "MONTAGER", font=title, fill=(245, 245, 240))
    sub = ImageFont.truetype(str(ROOT / "fonts" / "Montserrat-VF.ttf"), 34)
    sub.set_variation_by_axes([700])
    d.text((84, 350), "Kill montages from your own clips,", font=sub, fill=LIME)
    d.text((84, 396), "cut to the beat.", font=sub, fill=LIME)
    small = ImageFont.truetype(str(ROOT / "fonts" / "Montserrat-VF.ttf"), 24)
    small.set_variation_by_axes([600])
    d.text((86, 470), "VALORANT  ·  CS2  ·  RAINBOW SIX SIEGE", font=small, fill=(190, 190, 185))
    d.rectangle((0, H - 8, W, H), fill=LIME)
    return canvas


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    big = icon()
    big.resize((512, 512), Image.LANCZOS).save(ASSETS / "montager_512.png")
    big.save(ASSETS / "montager.ico", sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    social(big).save(ROOT / "docs" / "images" / "social_preview.png", optimize=True)
    print("wrote", ASSETS / "montager.ico", ROOT / "docs" / "images" / "social_preview.png")


if __name__ == "__main__":
    main()
