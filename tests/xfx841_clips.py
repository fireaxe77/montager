"""V8.4.1 tool: the EXTRA EFFECTS render chains on a short stretch (4 s) of real clips, to look at the frames (no plan, no montage).
python tests/xfx841_clips.py OUT_DIR "<clip>" <kill time s> <game> [style]
Writes OUT_DIR/<name>.mp4 (4 s: the kill at 2.5 s with glow / flash / colour split / sky recolour / drop build-up and afterglow) and a contact sheet of the frames around the kill."""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import montage as M                                                                           # noqa: E402


def main(out_dir, clip, kt, game, style="aggressive", mode="all"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fe = M.feel_hue(style, 0.8, 128)
    feel = {"name": fe[0], "hue": fe[1], "rgb": fe[2]}
    p = 2.5
    take = {"nf": 240, "xfx": [{"k": "glow", "p": p, "a": 0.42, "t1": M.XFX_GLOW_S}, {"k": "flash", "p": p, "a": 0.16, "t1": M.XFX_FLASH_S},
                               {"k": "rgb", "p": p, "px": 8, "t1": M.XFX_RGB_S}, {"k": "rise", "p": p, "t0": 1.5}, {"k": "after", "p": p, "t1": 1.2},
                               {"k": "sky", "p": p, "t0": p - M.XFX_SKY_IN, "t1": p + M.XFX_SKY_OUT, "hue": fe[1], "ok": True}]}
    if mode == "sky":
        take["xfx"] = [x for x in take["xfx"] if x["k"] == "sky"]
    elif mode == "kill":
        take["xfx"] = [x for x in take["xfx"] if x["k"] != "sky"]
    zone = list(M.DEFAULT_REGION[game])
    zone[3] = zone[1] + 0.55 * (zone[3] - zone[1])
    chains = []
    lab = M._xfx_chains(chains, "t0", "[src]", take, M.FX_ALL, False, zone, feel)
    pre = ("[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=60,format=yuv420p,setpts=PTS-STARTPTS,"
           "trim=end_frame=240,setpts=PTS-STARTPTS[src]")
    fc = pre + ";" + ";".join(chains) + f";{lab}null[o]"
    name = Path(clip).stem.replace(" ", "_")[:40] + f"_{game}_{style}_{mode}"
    outf = out_dir / (name + ".mp4")
    ss = max(0.0, float(kt) - p)
    cmd = ["ffmpeg", "-v", "error", "-y", "-ss", f"{ss:.3f}", "-t", "4.2", "-i", clip, "-filter_complex", fc, "-map", "[o]", "-an", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "18", "-frames:v", "240", str(outf)]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode:
        print("ffmpeg failed:", r.stderr.decode("utf-8", "ignore")[-800:])
        return 1
    ref = out_dir / (name + "_orig.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ss:.3f}", "-t", "4.2", "-i", clip, "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=60",
                    "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-frames:v", "240", str(ref)], check=True)
    times = [2.4, 2.5, 2.55, 2.62, 2.72, 2.9, 3.2, 3.55] if mode != "sky" else [2.2, 2.4, 2.5, 2.62, 2.8, 3.0, 3.2, 3.4]
    for tag, f in (("fx", outf), ("orig", ref)):
        sel = "+".join(f"eq(n,{int(round(t * 60))})" for t in times)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-vf", f"select='{sel}',scale=480:270,tile=4x2", "-frames:v", "1", str(out_dir / f"{name}_{tag}.png")], check=True)
    import numpy as np
    g = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{float(kt):.3f}", "-i", clip, "-frames:v", "1", "-vf", "scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2:color=black",
                        "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    mk_ = M.sky_mask_np(np.frombuffer(g[:480 * 270 * 3], np.uint8).reshape(270, 480, 3))
    cov = float(mk_[:int(270 * 0.55)].mean())
    ok = M.XFX_SKY_MIN_COV <= cov <= M.XFX_SKY_MAX_COV and float(mk_[:int(270 * 0.15)].mean()) >= M.XFX_SKY_MIN_TOP
    print(f"{name}: sky coverage {cov * 100:.0f}% of the upper picture -> the real render would " + ("recolour the sky" if ok else "SKIP the sky recolour (no sky here)"))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
