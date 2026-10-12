"""V7.6.1 per-take SSIM audit of a REAL render: python tests\\ssim761.py <montage.mp4> [<plan.json>]
For every take one clean stretch (1.0x, no zoom pulse, no dissolve) of 0.5 s is compared with (a) the quality-check reference (source cropped + scaled + fps=60, best of +-3 frames) and
(b) the ideal chain of the renderer (same crop / scale, setpts=PTS/sp, fps=60:start_time=0, aligned) - so a low value says whether the picture is bad or the reference is."""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
import montage as M                                                                           # noqa: E402


def ssim(cmd):
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    m = re.findall(r"All:([\d.]+)", r.stderr.decode(errors="replace"))
    return float(m[-1]) if m else None


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate,codec_name,width,height,pix_fmt", "-of", "json", path], capture_output=True)
    try:
        s = json.loads(r.stdout)["streams"][0]
        n, _, d = s["avg_frame_rate"].partition("/")
        return {"fps": round(float(n) / float(d), 2) if d and float(d) else 0.0, "codec": s["codec_name"], "wh": f"{s['width']}x{s['height']}"}
    except Exception:
        return {}


def stretch(t):
    off = 0
    for sg in t["segs"]:
        a, b, sp, n = sg[:4]
        if sp == 1.0 and n >= 45:
            for st in (0.45, 0.8):
                s_ = off / 60 + st
                if s_ + 0.5 <= (off + n) / 60 and not any(s_ - 0.5 < x < s_ + 0.6 for x in t["pulses"]):
                    return t["out_start"] + s_, a + (s_ - off / 60), sg
        off += sg[3]
    return None


def audit(video, plan, only=None):
    rows = []
    for i, t in enumerate(plan["takes"], 1):
        if only and i not in only:
            continue
        st = stretch(t)
        if not st:
            continue
        g0, s0, sg = st
        src = t["srcs"][sg[4] if len(sg) > 4 else 0]
        s0 -= src["shift"]
        cx, cy, cw, ch = src["rect"]
        crop = f"crop={cw}:{ch}:{cx}:{cy}," if [cx, cy, cw, ch] != [0, 0, src["wh"][0], src["wh"][1]] else ""
        ref = f"{crop}scale=1920:1080:flags=lanczos," if (crop or list(src["wh"]) != [1920, 1080]) else ""
        best = (-1, 0)
        for k in range(-3, 4):
            v = ssim(["ffmpeg", "-hide_banner", "-ss", f"{max(0, g0 + k / 60):.4f}", "-t", "0.5", "-i", str(video), "-ss", f"{max(0, s0):.4f}", "-t", "0.5", "-i", src["path"], "-filter_complex",
                      f"[0:v]setpts=PTS-STARTPTS,format=yuv420p[a];[1:v]{ref}fps=60,setpts=PTS-STARTPTS,format=yuv420p[b];[a][b]ssim", "-f", "null", "-"])
            if v is not None and v > best[0]:
                best = (v, k)
        ideal = ssim(["ffmpeg", "-hide_banner", "-ss", f"{g0:.4f}", "-t", "0.5", "-i", str(video), "-ss", f"{max(0, s0):.4f}", "-t", "0.6", "-i", src["path"], "-filter_complex",
                      f"[0:v]setpts=PTS-STARTPTS,format=yuv420p[a];[1:v]{ref}setsar=1,setpts=PTS/1.0,fps=60:start_time=0,trim=end_frame=30,setpts=PTS-STARTPTS,format=yuv420p[b];[a]trim=end_frame=30[a2];[a2][b]ssim",
                      "-f", "null", "-"])
        pr = probe(src["path"])
        rows.append({"take": i, "clip": Path(src["path"]).name, "src": pr, "wh": src["wh"], "rect": src["rect"], "ref_ssim": best[0], "ref_align": best[1], "ideal_ssim": ideal})
    return rows


if __name__ == "__main__":
    vid = Path(sys.argv[1])
    pj = Path(sys.argv[2]) if len(sys.argv) > 2 else vid.parent / "logs" / (vid.stem + ".plan.json")
    plan = json.load(open(pj, encoding="utf-8"))
    for r in audit(vid, plan):
        print(f"take {r['take']:2d} {r['clip'][-34:]:34s} {r['wh']} rect {r['rect']} src {r['src']}  quality-check reference {r['ref_ssim']:.3f} (align {r['ref_align']:+d})  ideal chain {r['ideal_ssim']}")
