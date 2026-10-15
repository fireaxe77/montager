"""V8.4.3 tool: frame strips of a rendered EXTRA montage (and of the same moments in the source clips).
python tests/strips843.py <plan.json> <montage.mp4> <outdir>
Writes per sky kill   sky_take<N>.png   (rows 1-2 = the montage before / during / after the recolour, rows 3-4 = the same moments in the source clip),
and per effect kill   kill_take<N>_<k>.png (the montage around that kill, with the source frames below) for every kill that has a colour split / punch / drop build-up."""
import json
import subprocess
import sys
from pathlib import Path

FPS = 60.0


def src_time(t, o):
    """Source time of the moment `o` s into the take (None when it cannot be told)."""
    f = o * FPS
    f0 = 0.0
    for sg in t["segs"]:
        a, b, sp, n = sg[:4]
        if f < f0 + n:
            if sp == 0.0:
                return a
            return a + (f - f0) / max(1, n) * (b - a)
        f0 += n
    return None


def grab(path, tt, w=480, h=270):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, tt):.3f}", "-i", str(path), "-frames:v", "1", "-vf",
                        f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    import numpy as np
    b = r.stdout
    if len(b) < w * h * 3:
        return np.zeros((h, w, 3), np.uint8)
    return np.frombuffer(b[:w * h * 3], np.uint8).reshape(h, w, 3).copy()


def sheet(plan, ti, video, times, out, label_fx):
    import numpy as np
    from PIL import Image, ImageDraw
    t = plan["takes"][ti]
    tiles_fx, tiles_src = [], []
    for o in times:
        tiles_fx.append((o, grab(video, t["out_start"] + o)))
        st = src_time(t, o)
        src = t["srcs"][0]["path"] if t.get("srcs") else t["path"]
        sh = (t["srcs"][0].get("shift", 0.0) if t.get("srcs") else 0.0)
        tiles_src.append((o, grab(src, (st - sh) if st is not None else 0.0)))
    cols = 4
    n = len(times)
    rows = (n + cols - 1) // cols
    W, H = 480, 270
    img = Image.new("RGB", (cols * W, rows * H * 2), (0, 0, 0))
    for blk, tiles in enumerate((tiles_fx, tiles_src)):
        for i, (o, a) in enumerate(tiles):
            im = Image.fromarray(a)
            ImageDraw.Draw(im).text((6, 250), f"{'MONTAGE' if blk == 0 else 'SOURCE '} {o:+.2f}s", fill=(255, 255, 0))
            img.paste(im, ((i % cols) * W, (blk * rows + i // cols) * H))
    img.save(out)


def main(plan_json, video, outdir):
    plan = json.load(open(plan_json, encoding="utf-8"))
    import re
    lg = Path(plan_json).with_name("render.log")                    # the plan json is written before the render: the kept sky kills are in the render log
    kept = {int(m.group(1)) for m in re.finditer(r"SKY recolour take (\d+): .*-> recoloured", lg.read_text(encoding="utf-8", errors="replace"))} if lg.exists() else set()
    for ti_, t_ in enumerate(plan["takes"]):
        for x_ in t_.get("xfx") or []:
            if x_["k"] == "sky" and (ti_ + 1) in kept:
                x_["ok"] = True
    od = Path(outdir)
    od.mkdir(parents=True, exist_ok=True)
    for ti, t in enumerate(plan["takes"]):
        for x in t.get("xfx") or []:
            if x["k"] == "sky" and x.get("ok"):
                p = x["p"]
                times = [p - 0.45, p - 0.25, p - 0.1, p, p + 0.15, p + 0.35, p + 0.6, p + 0.9]
                times = [max(0.0, min(float(t["dur"]) - 0.02, v)) for v in times]
                sheet(plan, ti, video, times, od / f"sky_take{ti + 1}.png", "sky")
                print("sky strip: take", ti + 1, "kill at", round(t["out_start"] + p, 2), "s")
        done = set()
        for x in t.get("xfx") or []:
            if x["k"] in ("rgb", "punch", "rise", "after") and round(x["p"], 2) not in done:
                p = x["p"]
                done.add(round(p, 2))
                ks = sorted({y["k"] for y in t["xfx"] if y.get("p") is not None and abs(y["p"] - p) < 1e-6 and y["k"] != "sky"})
                if t.get("role") == "headline" or "punch" in ks:
                    times = [p - 0.1, p - 0.02, p + 0.04, p + 0.1, p + 0.18, p + 0.3, p + 0.5, p + 0.9]
                    times = [max(0.0, min(float(t["dur"]) - 0.02, v)) for v in times]
                    sheet(plan, ti, video, times, od / f"kill_take{ti + 1}_{'+'.join(ks)}_{p:.2f}.png", "kill")
                    print("kill strip: take", ti + 1, ks, "at", round(t["out_start"] + p, 2), "s")


if __name__ == "__main__":
    main(*sys.argv[1:4])
