"""Montager setup check (standalone, read-only).

Checks that this PC has everything Montager needs and that the basic settings are filled in, and says in plain language
what is missing and how to fix it. It never changes a file, a setting or a cache: it only reads.
It is not used by the app or by a render; Start_Montager.bat runs it before starting Montager.

    python setup_check.py            (exit code 0 = ready, 2 = ready with warnings, 1 = something must be fixed first)
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FROZEN = bool(getattr(sys, "frozen", False))            # inside the packaged Montager.exe (Python and every package are bundled)
REINSTALL = "reinstall Montager from https://github.com/fireaxe77/montager/releases/latest"
DATA = Path(os.environ.get("MONTAGER_DATA") or (HERE / "montage_data")).resolve()     # the same rule as montage.py
CONFIG = DATA / "config.json"
GAMES = (("valorant", "Valorant"), ("cs2", "CS2"), ("r6s", "Rainbow Six Siege"))
AUDIO_EXT = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus"}
VIDEO_EXT = {".mov", ".mp4", ".mkv"}
PLACEHOLDER_NAMES = {"yourname", "your_name", "yourname0", ""}
DEV_NAMES = {"fireaxe", "fireaxe0"}                    # the names the app falls back to when none are set

REQUIRED = [("numpy", "numpy"), ("cv2", "opencv-python"), ("PIL", "Pillow"), ("librosa", "librosa"), ("soundfile", "soundfile"),
            ("scipy", "scipy"), ("mutagen", "mutagen"), ("rapidfuzz", "rapidfuzz"), ("rapidocr_onnxruntime", "rapidocr-onnxruntime")]
RECOMMENDED = [("sv_ttk", "sv-ttk", "the dark Sun Valley look (without it a plain theme is used)"),
               ("psutil", "psutil", "free-memory readings during a render"),
               ("fontTools", "fonttools", "picks a fallback font for intro titles in other alphabets")]
OPTIONAL = [("send2trash", "Send2Trash", "the clip list's trash icon uses the Windows Recycle Bin through it (works without it too)")]

problems, warnings = [], []

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:                                      # noqa: BLE001
    pass


def ok(msg, fix=None):
    print(f"  [OK]      {msg}")


def warn(msg, fix=None):
    warnings.append(msg)
    print(f"  [WARN]    {msg}")
    if fix:
        print(f"            Fix: {fix}")


def bad(msg, fix=None):
    problems.append(msg)
    print(f"  [PROBLEM] {msg}")
    if fix:
        print(f"            Fix: {fix}")


def section(title):
    print(f"\n== {title} ==")


def run(cmd, timeout=60):
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:                                  # noqa: BLE001
        return None


def tool(name):
    """ffmpeg / ffprobe from PATH, or from montage_data\\bin (the app adds that folder to PATH itself)."""
    local = DATA / "bin" / (name + (".exe" if os.name == "nt" else ""))
    if local.is_file():
        return str(local)
    return shutil.which(name)


def check_python():
    section("Python")
    if FROZEN:
        ok(f"bundled Python {sys.version.split()[0]} (nothing to install)")
        return
    v = sys.version_info
    bits = 64 if sys.maxsize > 2 ** 32 else 32
    txt = f"Python {v.major}.{v.minor}.{v.micro} ({bits}-bit) at {sys.executable}"
    if (v.major, v.minor) < (3, 10):
        bad(txt + ": too old", "install Python 3.12 (64-bit) from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'")
    elif bits != 64:
        bad(txt + ": 32-bit Python cannot run the OCR engine", "install the 64-bit Python 3.12 from python.org")
    elif (v.major, v.minor) != (3, 12):
        warn(txt + ": works, but Montager is developed and tested on Python 3.12")
    else:
        ok(txt)
    try:
        import tkinter                                 # noqa: F401
        ok("tkinter (the window toolkit)")
    except Exception:                                  # noqa: BLE001
        bad("tkinter is missing (Montager's window cannot open)",
            "re-run the python.org installer, choose Modify and tick 'tcl/tk and IDLE'")


def check_packages():
    section("Python packages")
    missing = []
    for mod, pip in REQUIRED:
        try:
            __import__(mod)
            ok(f"{pip}")
        except Exception as ex:                        # noqa: BLE001
            missing.append(pip)
            bad(f"{pip} is missing or broken ({type(ex).__name__})")
    if missing:
        print(f"            Fix: {REINSTALL}" if FROZEN else f"            Fix: python -m pip install --user {' '.join(missing)}")
    rec = []
    for mod, pip, why in RECOMMENDED:
        try:
            __import__(mod)
            ok(f"{pip}")
        except Exception:                              # noqa: BLE001
            rec.append(pip)
            warn(f"{pip} not installed: recommended for {why}")
    if rec and not FROZEN:
        print(f"            Fix: python -m pip install --user {' '.join(rec)}")
    for mod, pip, why in OPTIONAL:
        try:
            __import__(mod)
            ok(f"{pip} (optional)")
        except Exception:                              # noqa: BLE001
            print(f"  [info]    {pip} (optional) not installed: {why}")


def check_ffmpeg():
    section("FFmpeg and GPU encoder")
    fixes = ("winget install --id Gyan.FFmpeg -e --scope user   (then open a NEW terminal)\n"
             "                 or download 'ffmpeg-release-essentials' from https://www.gyan.dev/ffmpeg/builds/ and copy\n"
             f"                 ffmpeg.exe + ffprobe.exe into {DATA / 'bin'}")
    ff, fp = tool("ffmpeg"), tool("ffprobe")
    for name, p in (("ffmpeg", ff), ("ffprobe", fp)):
        if not p:
            bad(f"{name} not found", fixes)
            continue
        r = run([p, "-version"])
        first = (r.stdout.decode(errors="replace").splitlines() or ["?"])[0] if r else "?"
        ok(f"{name}: {first[:90]}")
    if not ff:
        return
    r = run([ff, "-hide_banner", "-encoders"])
    enc = r.stdout.decode(errors="replace") if r else ""
    if "libx264" in enc:
        ok("libx264 encoder (Quality: Max)")
    else:
        bad("this ffmpeg has no libx264 encoder", "use the gyan.dev 'essentials' or 'full' build (see above)")
    if "h264_nvenc" not in enc:
        warn("no NVIDIA encoder (h264_nvenc) in this ffmpeg: renders use x264 on the CPU - slower, same result")
        return
    r = run([ff, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30:d=0.2",
             "-c:v", "h264_nvenc", "-f", "null", "-"])
    if r is not None and r.returncode == 0:
        ok("NVIDIA GPU encoder works (Quality: Fast (NVENC))")
    else:
        warn("no working NVIDIA GPU encoder (no NVIDIA GPU, or an old driver)" + (": Montager renders with x264 on the CPU instead (slower, same result)" if FROZEN else ""),
             "nothing to do; with an NVIDIA GPU, update its driver: https://www.nvidia.com/Download/index.aspx" if FROZEN else "update the NVIDIA driver, or use Quality 'Max (x264)' in Montager")


def check_ocr():
    section("OCR engine (reads the killfeed)")
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as ex:                            # noqa: BLE001
        bad(f"RapidOCR cannot be loaded ({type(ex).__name__}: {str(ex)[:120]})",
            REINSTALL if FROZEN else "python -m pip install --user rapidocr-onnxruntime")
        return
    try:
        import numpy as np
        import cv2
        img = np.zeros((90, 420, 3), np.uint8)
        cv2.putText(img, "MONTAGER 123", (12, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3, cv2.LINE_AA)
        res, _ = RapidOCR()(img)
        txt = " ".join(r[1] for r in (res or []))
        if "MONTAGER" in txt.upper().replace(" ", "") or "MONTAGER" in txt.upper():
            ok(f"RapidOCR reads a test image ('{txt.strip()}')")
        else:
            warn(f"RapidOCR runs but read '{txt.strip() or 'nothing'}' on a test image",
                 "reinstall it: python -m pip install --user --force-reinstall rapidocr-onnxruntime")
    except Exception as ex:                            # noqa: BLE001
        bad(f"RapidOCR failed on a test image ({type(ex).__name__}: {str(ex)[:120]})",
            REINSTALL if FROZEN else "python -m pip install --user --force-reinstall rapidocr-onnxruntime onnxruntime")


def load_cfg():
    if not CONFIG.is_file():
        return None
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception as ex:                            # noqa: BLE001
        bad(f"{CONFIG} cannot be read ({ex})", "fix the file, or rename it and copy config.example.json in its place")
        return {}


def count_files(root, exts, limit=50000, depth=6):
    n = 0
    base = len(Path(root).parts)
    for r, dirs, files in os.walk(root):
        if len(Path(r).parts) - base >= depth:
            dirs[:] = []
        n += sum(1 for f in files if os.path.splitext(f)[1].lower() in exts)
        if n >= limit:
            break
    return n


def unexpanded(cfg):
    """Paths still holding %USERPROFILE% (config.example.json copied by hand): the app does not expand them."""
    vals = [cfg.get(k) for k in ("mp3_dir", "playlist_dir", "output_root", "clip_root")]
    vals += [d for lst in (cfg.get("clip_dirs") or {}).values() if isinstance(lst, list) for d in lst]
    return [v for v in vals if isinstance(v, str) and "%" in v]


def check_settings():
    section("Settings (montage_data\\config.json)")
    cfg = load_cfg()
    if cfg is None:
        if FROZEN:
            bad(f"no settings saved yet ({CONFIG} does not exist)",
                "start Montager once from the Start menu: it creates your settings, then fill them in on its Settings tab")
            return
        bad(f"no settings saved yet ({CONFIG} does not exist): Montager would start with the developer's own example folders and names",
            "start Montager with Start_Montager.bat (it creates the file from config.example.json), or copy config.example.json "
            "to montage_data\\config.json, then fill in Settings")
        return
    print(f"  settings file: {CONFIG}")
    for v in unexpanded(cfg):
        bad(f"a folder still contains a placeholder: {v}",
            "replace %USERPROFILE% with your real folder (for example C:\\Users\\<you>) in Settings > Folders")

    section("Clip folders")
    dirs = cfg.get("clip_dirs") if isinstance(cfg.get("clip_dirs"), dict) else {}
    any_ok = False
    for g, label in GAMES:
        lst = [d for d in (dirs.get(g) or []) if str(d).strip()]
        if not lst:
            print(f"  [info]    {label}: no clip folder set (fine if you do not play it)")
            continue
        for d in lst:
            if os.path.isdir(d):
                n = count_files(d, VIDEO_EXT)
                any_ok = any_ok or n > 0
                (ok if n else warn)(f"{label}: {d}  ({n} video file{'s' if n != 1 else ''})")
            else:
                warn(f"{label}: folder not found: {d}", "fix it in Settings > Folders (or plug in that drive)")
    if not any_ok:
        bad("no clip folder with videos is set for any game",
            "Settings > Folders > '<game> clip folders' > Add folder (the folder your recorder saves clips to)")

    section("Songs")
    mp3 = str(cfg.get("mp3_dir") or "").strip()
    if not mp3:
        bad("no MP3 folder set", "Settings > Folders > MP3 folder: the folder with your songs (<title> - <artists>.mp3)")
    elif not os.path.isdir(mp3):
        bad(f"MP3 folder not found: {mp3}", "Settings > Folders > MP3 folder")
    else:
        n = count_files(mp3, AUDIO_EXT)
        (ok if n else bad)(f"MP3 folder: {mp3}  ({n} song file{'s' if n != 1 else ''})",
                           None if n else "put your songs there (mp3 / flac / m4a / wav / ogg / opus)")
    pl = str(cfg.get("playlist_dir") or "").strip() or str(DATA / "playlist")
    csvs = sorted(Path(pl).glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True) if os.path.isdir(pl) else []
    if not os.path.isdir(pl):
        bad(f"Exportify CSV folder not found: {pl}", "Settings > Folders > Exportify CSV folder (see README: Songs)")
    elif not csvs:
        bad(f"no Exportify CSV in {pl}", "export your Spotify playlist at https://exportify.app and save the .csv there")
    else:
        ok(f"Exportify CSV: {csvs[0].name} (the newest .csv in {pl} is used)")

    section("Output")
    outr = str(cfg.get("output_root") or "").strip()
    if not outr:
        warn("no output folder set", "Settings > Folders > Output folder")
    else:
        drive = os.path.splitdrive(outr)[0]
        if drive and not os.path.isdir(drive + os.sep):
            bad(f"output folder is on a drive that does not exist: {outr}", "Settings > Folders > Output folder")
        else:
            ok(f"montages are saved under {outr}" + ("" if os.path.isdir(outr) else " (created on the first render)"))

    section("Player names")
    pn = cfg.get("player_names") if isinstance(cfg.get("player_names"), dict) else {}
    used = [g for g, _ in GAMES if any(str(d).strip() for d in (dirs.get(g) or []))] or [g for g, _ in GAMES]
    for g, label in GAMES:
        names = [str(n).strip() for n in (pn.get(g) or []) if str(n).strip()]
        low = {n.lower() for n in names}
        if g not in used:
            continue
        if not names:
            bad(f"{label}: no player name set: the app falls back to the developer's name and finds none of YOUR kills",
                "Settings > Player names: your in-game name exactly as the killfeed shows it")
        elif low <= PLACEHOLDER_NAMES:
            bad(f"{label}: player name is still the placeholder '{names[0]}'",
                "Settings > Player names: your in-game name exactly as the killfeed shows it")
        else:
            ok(f"{label}: {'; '.join(names)}")
            if low & DEV_NAMES:
                print("            (this is the developer's name: change it if it is not yours)")


def main():
    print("Montager setup check (read-only: nothing is changed)")
    print(f"  app folder:  {HERE}")
    print(f"  data folder: {DATA}")
    if not FROZEN and not (HERE / "montage.py").is_file():
        bad("montage.py is not next to this script", "unzip the whole Montager folder and run this from inside it")
    check_python()
    check_packages()
    check_ffmpeg()
    check_ocr()
    check_settings()
    print()
    if problems:
        print(f"RESULT: {len(problems)} problem(s) to fix" + (f", {len(warnings)} warning(s)" if warnings else "") + ".")
        print("Montager can still open (Settings is where most of these are fixed), but it cannot make a montage until they are fixed.")
        return 1
    print("RESULT: ready" + (f" ({len(warnings)} warning(s), see above)" if warnings else "") + ".")
    return 2 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
