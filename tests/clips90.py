"""V9.0 helper: from a rendered montage make (1) the first 12 s and the last 12 s as separate short files, (2) a frame sheet of the intro (blur, text, unblur, handover) and one of the outro
(release, fade to black), (3) the frame-to-frame change around the handover (a jump would show as one huge value), (4) the music level over the last seconds.
    python tests\\clips90.py <montage.mp4> <out_dir> <name>
Writes <out_dir>\\<name>_first12.mp4, <name>_last12.mp4, <name>_intro_sheet.png, <name>_outro_sheet.png and prints the numbers."""
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def ff(args, **kw):
    return subprocess.run(["ffmpeg", "-v", "error", "-y"] + args, capture_output=True, **kw)


def duration(v):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(v)], capture_output=True, text=True)
    return float(r.stdout.strip())


def grab(v, t, w=480, h=270):
    import io
    r = ff(["-ss", f"{t:.3f}", "-i", str(v), "-frames:v", "1", "-vf", f"scale={w}:{h}", "-f", "image2pipe", "-vcodec", "png", "-"])
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")


def sheet(v, times, path, cols=4):
    ims = []
    for t in times:
        im = grab(v, t)
        ImageDraw.Draw(im).text((6, 6), f"t = {t:.2f} s", fill=(255, 255, 0))
        ims.append(im)
    rows = (len(ims) + cols - 1) // cols
    sh = Image.new("RGB", (cols * 484, rows * 274), (20, 20, 20))
    for i, im in enumerate(ims):
        sh.paste(im, ((i % cols) * 484, (i // cols) * 274))
    sh.save(path)


def main():
    v, out, name = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    out.mkdir(parents=True, exist_ok=True)
    D = duration(v)
    enc = ["-c:v", "libx264", "-preset", "fast", "-crf", "14", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    ff(["-i", str(v), "-t", "12"] + enc + [str(out / f"{name}_first12.mp4")])
    ff(["-ss", f"{D - 12:.3f}", "-i", str(v)] + enc + [str(out / f"{name}_last12.mp4")])
    sheet(v, [0.3, 1.0, 2.0, 4.0, 5.6, 6.3, 6.8, 7.0, 7.2, 7.6, 8.5, 10.0], out / f"{name}_intro_sheet.png")
    sheet(v, [D - x for x in (7.0, 5.0, 4.0, 3.2, 2.6, 2.0, 1.4, 1.0, 0.6, 0.3, 0.1)], out / f"{name}_outro_sheet.png")
    # frame-to-frame change around the handover
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="clips90_"))
    ff(["-ss", "6.5", "-t", "1.0", "-i", str(v), "-vf", "scale=320:180", str(tmp / "f_%03d.png")])
    fr = [np.asarray(Image.open(p).convert("L"), np.float32) for p in sorted(tmp.glob("f_*.png"))]
    d = [float(np.abs(fr[i + 1] - fr[i]).mean()) for i in range(len(fr) - 1)]
    near = d[int(0.35 * 60):int(0.65 * 60)]
    print(f"{name}: duration {D:.2f} s; frame change around the handover (6.85 - 7.15 s): max {max(near):.1f}, median {float(np.median(d)):.1f}, frames repeated (change < 0.05): {sum(1 for x in near if x < 0.05)}")
    # music level at the end
    levels = []
    for a, b in ((D - 4.0, 0.5), (D - 3.0, 0.5), (D - 2.0, 0.5), (D - 1.0, 0.5), (D - 0.5, 0.4)):
        r = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{a:.2f}", "-t", f"{b}", "-i", str(v), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
        m = re.search(r"mean_volume: (-?[\d.]+|-inf) dB", r.stderr)
        levels.append(m.group(1) if m else "?")
    print(f"{name}: music level (dB) at -4.0 / -3.0 / -2.0 / -1.0 / -0.5 s before the end: {levels}")
    # the last picture is black
    last = np.asarray(grab(v, D - 0.05, 160, 90).convert("L"), np.float32)
    print(f"{name}: brightness of the last frame {last.mean():.1f} (0 = black)")
    # first-frame fade-in
    first = np.asarray(grab(v, 0.0, 160, 90).convert("L"), np.float32)
    print(f"{name}: brightness of the first frame {first.mean():.1f} (fade-in from black)")


if __name__ == "__main__":
    main()
