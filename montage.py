r"""
montage.py - Valorant / CS2 kill-montage builder synced to a song. One file + montage_data\ folder. Personal use.
Never modifies source clips. No network at runtime (only the optional one-click pip install). No admin needed.

GET IT RUNNING (Windows 11, Python 3.12) - in cmd.exe:
    cd C:\Users\fireaxe\Desktop\CLAUDECODE
    git clone https://github.com/fireaxe77/montager.git montager      (later updates: cd montager && git pull origin main)
    cd montager
    python -m pip install --user numpy opencv-python librosa soundfile scipy mutagen rapidfuzz rapidocr-onnxruntime sv-ttk
    python montage.py                    <- opens the GUI (Montager) (the app also offers a one-click install of missing packages)
    ffmpeg missing?  winget install --id Gyan.FFmpeg -e --scope user   (open a new terminal afterwards)

FIRST 3 THINGS TO CLICK:
  1. Troubleshoot > "Selfcheck"  -> every line should say OK (ffmpeg, NVENC, packages, OCR test).
  2. Troubleshoot > "Self-test detection" after a few clips are scanned: rows found, the OCR text of your rows, verdicts.
     (Optional: "Calibrate killfeed region" if your killfeed is not in the default top-right area.)
  3. Settings: check the Valorant / CS2 clip folder lists. Then Auto tab > "Dry plan": first run scans every clip once (cached
     forever), then prints the song + map, recipe, lock level, ranked kills and the cut list. Then "Preview" and "Make this week's montage".

NOTES (V5): clips come from the explicit folder lists in Settings (the list decides the game). Kills are read with OCR (RapidOCR,
  offline) from the killfeed; KILL = FIREAXE first on the killer side, assists / utility kills never reach a montage (knife kills count), OCR
  variants of one row are merged, a single sighting under 90 needs a gunshot. Each kill is refined to the FIRST frame its row is
  visible. Every song gets a cached SONG MAP (beat grid locked to the CSV Tempo, downbeats, 4/8-bar phrases, sections, all drops,
  accents, loudness; Songs tab > Song map). The montage is built FROM the map: first kills land on the beat (how many are locked
  depends on the style recipe + the song's rhythm, printed as the lock level), every drop gets a strong clip, the last take ends in
  slow-mo with the music + video fade. Duplicate / continuation clips are merged (and stitched into one take when needed); no clip is
  used twice. Game audio is loudness-normalised per clip and mixed ~4 dB under the music, which ducks ~4 dB around kills.
  "python montage.py smoketest" = GUI + OCR + planner + a real render whose sync is measured from the file (< 3 min).
  "python montage.py detectcheck" = V4 vs V5 kill classification on all cached OCR data.

CLI (same engine):  python montage.py auto [--game valorant|cs2] [--force] [--dry] [--preview] [--max-quality] [--seed N]
                    python montage.py plan --game cs2        (dry plan only)     python montage.py pick   (GUI, Manual tab)
                    python montage.py selfcheck | selftest | smoketest | detectcheck | inventory | scan | verify <game> | calibrate-bars | tag <path> <game>
Data: montage_data\ (config.json, caches, calibration, plans, logs\montage.log). Output: E:\Movies\Montages\<Game>\<SONG INITIALS>_<VAL|CS2>_<version>_<date>.mp4 (+ logs\ with its plan .txt/.json).
"""
import argparse
import atexit
import functools
import base64
import datetime
import hashlib
import math
import queue
import random
import threading
import traceback
import csv
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PERF_T0 = time.perf_counter()                    # ~process start (after the stdlib imports above); perflog times count from here

APP_VERSION = "V6.9.7"
ACCENTS = ("lime", "yellow", "orange", "red", "pink", "purple")      # V5.57 theme choices
BASES = ("grey", "black")
AUDIO_MODES = {"auto": "Auto (V5.56)", "legacy": "Legacy (V5.55)"}
AUDIO_TAGS = {"auto": "[audio: auto V5.56]", "legacy": "[audio: legacy V5.55]"}
HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("MONTAGER_DATA") or (HERE / "montage_data")).resolve()    # V5.56: always next to montage.py (absolute), never the working folder (the env var is only for tests)
CONFIG_PATH = DATA / "config.json"
CLIPS_CACHE = DATA / "clips_cache3.json"
AUDIO_CACHE = DATA / "audio_cache.json"
KILLS_CACHE = DATA / "kills_cache3.json"

VIDEO_EXT = {".mov", ".mp4", ".mkv"}
AUDIO_EXT = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus"}
MIN_VIDEO = 1 * 1024 * 1024
SKIP_DIR_NAMES = {"windows", "program files", "program files (x86)", "appdata", "programdata", "snipping tool",
                  "$recycle.bin", "system volume information", "montage_data", "node_modules", ".git"}
BAR_THRESHOLD = 12        # pixel brightness (0-255) counted as content
BAR_FRAMES = 24
GAMES = ("valorant", "cs2")

LEN_MIN_S, LEN_MAX_S = 80, 150                      # V6.1.3: fixed-length range = the Optimal rule of V5.42B (80-150 s)
DEFAULT_CONFIG = {
    "playlist_dir": str(DATA / "playlist"),
    "mp3_dir": "",
    "output_root": r"E:\Movies\Montages",
    "clip_root": r"E:\Movies",
    "bar": None,                    # fixed black-bar crop {"src":[W,H],"rect":[x,y,w,h]}, set by calibrate-bars
    "week_days": 7,
    "window_min_s": 45,
    "window_max_s": 90,
    "game_audio_level": 0.6,        # game audio under the music (linear; V4 was 0.5), +4 dB around kills; quiet clips lifted <= 8 dB
    "cfg_version": 5,
    "include_valorant": ["VALORANT"],   # only folders whose name matches are used (any depth under clip_root)
    "include_cs": ["CS", "COUNTER STRIKE"],
    "max_mb": 60,
    "max_dur_s": 60,
    "auto_recent_days": 30,
    "auto_old_per_run": 150,
    "name_match": 80,               # V4 OCR: rapidfuzz partial_ratio needed for FIREAXE (killer side = kill, victim side = death)
    "death_lock_s": 8.0,            # no kills counted this long after my own death
    "sync_report": True,
    "gap_s": {"valorant": 6.0, "cs2": 5.0},
    "game_overrides": {},           # path prefix -> game
    "match_threshold": 85,
    "length_s": "optimal",          # "optimal" (default) or seconds (80-150, like Optimal)
    "ui_layout": {},                # V5.55: remembered window size + divider positions (GUI only)
    "update_on_start": False,       # V5.5: run `git pull` when the app starts (Settings; off by default)
    "style": "auto",                # auto (default) | hype | aggressive | smooth | cinematic | chill | mix | random
    "placement": "v5",              # v5 = frame-exact kill moments on the song-map grid; v4 = V4 timing (see synccompare)
    "quality": "nvenc",             # nvenc | max
    "scan_workers": 2,              # clips OCR-scanned in parallel
    # V5: explicit clip folders; the game comes from the list a folder is in (replaces folder-name matching)
    "clip_dirs": {"valorant": [r"E:\Movies\VALORANT\Clips", r"E:\Movies\LEGACY\Valorant"],
                  "cs2": [r"E:\Movies\2026\Counter-strike 2", r"E:\Movies\2026\cs clips",
                          r"E:\Movies\Movies 2025\Counter-strike 2", r"E:\Movies\LEGACY\Counter-strike 2"]},
    "player_names": {"valorant": ["fireaxe"], "cs2": ["fireaxe", "火斧"]},      # V6.0: Settings > Player names (; separated)
    "game_audio_track": {"valorant": "auto", "cs2": "auto"},     # V5.56: which audio track of a clip is the game sound: auto | 1 | 2 | 3
    "ui_scale": 1.0,                # GUI font / row height scale
    "audio_mode": "auto",           # V5.57: auto = V5.56 track pick | legacy = the exact V5.55 audio path
    "accent": "lime",               # V5.57: lime | yellow | orange | red | pink | purple
    "base": "grey",                 # V5.57: grey | black
}


# ----------------------------------------------------------------- utilities
LOG_DIR = DATA / "logs"
LOG_SINK = [None]       # GUI sets callable(str)
PROGRESS = [None]       # GUI sets callable(frac, text)
CANCEL = threading.Event()
PROCS = []              # running ffmpeg processes, killed on cancel


def LOGONLY(msg):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "montage.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


QUIET = threading.local()               # QUIET.on = True: this thread logs nothing (the Manual status-line estimate)


def out(*a):
    if getattr(QUIET, "on", False):
        return
    msg = " ".join(str(x) for x in a)
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_DIR / "montage.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass
    if LOG_SINK[0]:
        LOG_SINK[0](msg)
    else:
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:                         # a console without UTF-8 ('火斧' in CS2 rows)
            enc = getattr(sys.stdout, "encoding", None) or "ascii"
            print(msg.encode(enc, errors="replace").decode(enc, errors="replace"), flush=True)


def progress(frac, text=""):
    if PROGRESS[0] and not getattr(QUIET, "on", False):
        PROGRESS[0](frac, text)


def load_json(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(p, obj):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_json(CONFIG_PATH, {}))
    if cfg.get("cfg_version", 1) < 2:                 # one-time migration of Stage 0 defaults
        cfg["game_audio_level"], cfg["cfg_version"] = 0.5, 2
        try:
            save_json(CONFIG_PATH, cfg)
        except Exception:
            pass
    if cfg.get("cfg_version", 1) < 4:                 # V5: explicit clip folder lists
        cfg["clip_dirs"] = cfg.get("clip_dirs") or DEFAULT_CONFIG["clip_dirs"]
    if cfg.get("cfg_version", 1) < 3:
        cfg["cfg_version"] = 3
    cfg.pop("theme", None)                            # V5.56: one theme only
    cfg.pop("duck_db", None)                          # never read by the engine
    cfg.pop("game_under_music_db", None)
    if not isinstance(cfg.get("game_audio_track"), dict):
        cfg["game_audio_track"] = dict(DEFAULT_CONFIG["game_audio_track"])
    if cfg.get("audio_mode") not in ("auto", "legacy"):            # V5.57
        cfg["audio_mode"] = "auto"
    if not isinstance(cfg.get("player_names"), dict):
        cfg["player_names"] = {g: list(v) for g, v in DEFAULT_PLAYER_NAMES.items()}
    set_player_names(cfg)                                          # V6.0
    if isinstance(cfg.get("length_s"), (int, float)) and not isinstance(cfg.get("length_s"), bool):
        cfg["length_s"] = max(LEN_MIN_S, min(LEN_MAX_S, int(round(cfg["length_s"]))))      # V6.1.3: fixed length 80-150 s
    if cfg.get("accent") not in ACCENTS:
        cfg["accent"] = "lime"
    if cfg.get("base") not in BASES:
        cfg["base"] = "grey"
    if cfg["cfg_version"] < 5:                        # V5.1: Optimal length + Auto style defaults, game audio slightly louder
        if cfg.get("length_s") in (85, None):
            cfg["length_s"] = "optimal"
        cfg.setdefault("style", "auto")
        if float(cfg.get("game_audio_level", 0.5)) <= 0.5:
            cfg["game_audio_level"] = 0.6
    if cfg["cfg_version"] < 5:
        cfg["cfg_version"] = 5
        try:
            if CONFIG_PATH.exists():
                save_json(CONFIG_PATH, cfg)
        except Exception:
            pass
    return cfg


def clip_dirs(cfg, game=None):
    """[(dir, game), ...] from Settings (explicit lists)."""
    d = cfg.get("clip_dirs") or {}
    return [(p, g) for g in GAMES if game in (None, g) for p in d.get(g, []) if p]


def setup_path():
    """Let a ffmpeg dropped in montage_data\\bin work without touching system PATH."""
    b = DATA / "bin"
    if b.is_dir():
        os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")


def run(cmd, timeout=120, **kw):
    return subprocess.run(cmd, capture_output=True, timeout=timeout, **kw)


def file_key(p):
    st = os.stat(p)
    return f"{p}|{st.st_size}|{int(st.st_mtime)}"


# ------------------------------------------------------------------ discovery
def norm(p):
    return os.path.normcase(os.path.normpath(p))


def walk_files(roots, exts, min_size, cfg):
    skip_out = norm(cfg["output_root"])
    for root in roots:
        stack = [root]
        while stack:
            d = stack.pop()
            try:
                it = os.scandir(d)
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            nl = e.name.lower()
                            if nl in SKIP_DIR_NAMES or norm(e.path) == skip_out or norm(e.path).startswith(skip_out + os.sep):
                                continue
                            stack.append(e.path)
                        elif e.is_file(follow_symlinks=False):
                            if os.path.splitext(e.name)[1].lower() in exts:
                                if e.stat().st_size >= min_size:
                                    yield e.path
                    except OSError:
                        continue


def folder_match(part, entries):
    p = re.sub(r"[^a-z0-9]+", " ", part.lower()).strip()
    toks = p.split()
    for e in entries:
        el = re.sub(r"[^a-z0-9]+", " ", str(e).lower()).strip()
        if not el:
            continue
        if " " in el:
            if el in p or el.replace(" ", "") in p.replace(" ", ""):
                return True
        elif any(t.startswith(el) for t in toks):
            return True
    return False


def tag_game(path, cfg):
    """Game from the explicit folder lists (Settings): the list a clip's folder is in decides the game. None = ignored clip."""
    pl = norm(path)
    best = None
    for pre, g in cfg.get("game_overrides", {}).items():
        n = norm(pre)
        if (pl == n or pl.startswith(n + os.sep)) and (best is None or len(n) > best[0]):
            best = (len(n), g)
    if best and best[1] in GAMES:
        return best[1], "override"
    if cfg.get("clip_dirs"):
        hit = None
        for d, g in clip_dirs(cfg):
            n = norm(d)
            if pl.startswith(n + os.sep) and (hit is None or len(n) > hit[0]):
                hit = (len(n), g)
        return (hit[1], "folder list") if hit else (None, "not in a listed clip folder")
    try:
        rel = os.path.relpath(path, cfg["clip_root"])
    except ValueError:
        return None, "outside"
    if rel.startswith(".."):
        return None, "outside"
    for part in reversed(Path(rel).parts[:-1]):
        if folder_match(part, cfg.get("include_valorant", [])):
            return "valorant", "folder"
        if folder_match(part, cfg.get("include_cs", [])):
            return "cs2", "folder"
    return None, "not in an included folder"


# --------------------------------------------------------------------- video
def probe_video(path):
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,codec_name,width,height,avg_frame_rate,pix_fmt,start_time:format=duration,start_time",
             "-of", "json", path])
    j = json.loads(r.stdout or b"{}")
    st = j.get("streams") or []
    v = next((x for x in st if x.get("codec_type") == "video"), {})
    a = next((x for x in st if x.get("codec_type") == "audio"), None)
    n, _, d = (v.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(n) / float(d) if d and float(d) else 0.0

    def f(x, dflt=0.0):
        try:
            return float(x)
        except (TypeError, ValueError):
            return dflt
    fmt0 = f((j.get("format") or {}).get("start_time"))
    return {"codec": v.get("codec_name"), "w": v.get("width"), "h": v.get("height"),
            "fps": round(fps, 2), "pix_fmt": v.get("pix_fmt"), "audio": a is not None,
            "v_off": round(f(v.get("start_time")) - fmt0, 4), "a_off": round(f(a.get("start_time")) - fmt0, 4) if a else 0.0,
            "dur": f((j.get("format") or {}).get("duration"))}


def grab_gray(path, t, w, h):
    r = run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
             "-vf", "format=gray", "-f", "rawvideo", "-"], timeout=60)
    if len(r.stdout) < w * h:
        return None
    import numpy as np
    return np.frombuffer(r.stdout[:w * h], np.uint8).reshape(h, w)


def detect_rect(path, info):
    """Median content rectangle over ~24 frames. Returns (rect|None, note)."""
    import numpy as np
    w, h, dur = info["w"], info["h"], info["dur"]
    if not (w and h and dur > 0):
        return None, "no video info"
    boxes = []
    for i in range(BAR_FRAMES):
        t = dur * (i + 0.5) / BAR_FRAMES
        g = grab_gray(path, t, w, h)
        if g is None:
            continue
        m = g > BAR_THRESHOLD
        if m.mean() < 0.01:       # near-black frame
            continue
        cols = np.flatnonzero(m.sum(axis=0) >= 3)
        rows = np.flatnonzero(m.sum(axis=1) >= 3)
        if len(cols) == 0 or len(rows) == 0:
            continue
        boxes.append((cols[0], rows[0], cols[-1] + 1, rows[-1] + 1))
    if len(boxes) < 3:
        return None, f"only {len(boxes)} usable frames"
    l, t, r, b = (int(statistics.median(x[k] for x in boxes)) for k in range(4))
    cw, ch = (r - l) & ~1, (b - t) & ~1
    if cw * ch < 0.5 * w * h:
        return None, f"content box {cw}x{ch} covers <50% of {w}x{h}"
    ar = cw / ch if ch else 0
    if not 1.3 <= ar <= 2.4:
        return None, f"implausible aspect {ar:.2f} ({cw}x{ch})"
    l, t = l & ~1, t & ~1
    return [l, t, cw, ch], "ok"


def outside_dark(g, rect):
    """True if everything outside rect [x,y,w,h] is black (bars present at the stored positions)."""
    import numpy as np
    x, y, w, h = rect
    m = np.ones(g.shape, bool)
    m[y:y + h, x:x + w] = False
    return m.any() and (g[m] <= BAR_THRESHOLD).mean() >= 0.995


def bars_present(path, info, bar):
    """Cheap 3-frame check: are the stored bar positions black in this clip?"""
    if not bar or [info["w"], info["h"]] != bar["src"]:
        return False
    hits = 0
    for f in (0.25, 0.5, 0.75):
        g = grab_gray(path, info["dur"] * f, info["w"], info["h"])
        hits += g is not None and outside_dark(g, bar["rect"])
    return hits >= 2


def analyse_clip(path, cache, rescan, bar):
    key = file_key(path)
    rec = None if rescan else cache.get(key)
    if rec is None:
        rec = {"path": path}
        try:
            rec.update(probe_video(path))
        except Exception as ex:
            rec["error"] = f"{type(ex).__name__}: {ex}"
    sig = json.dumps(bar)
    if "error" not in rec and rec.get("bar_sig") != sig:
        try:
            rec["bars"] = bool(bars_present(path, rec, bar))
        except Exception:
            rec["bars"] = False
        rec["bar_sig"] = sig
    cache[key] = rec
    return path, rec


def clip_roots(cfg):
    roots = [d for d, _ in clip_dirs(cfg)] if cfg.get("clip_dirs") else [cfg["clip_root"]]
    return [d for d in roots if os.path.isdir(d)]


def clip_folder(path, cfg):
    """Folder label for the Manual filter: '<listed folder name>/<subfolder>'."""
    for d, _ in clip_dirs(cfg):
        if norm(path).startswith(norm(d) + os.sep):
            rel = os.path.relpath(os.path.dirname(path), d)
            return Path(d).name + ("" if rel == "." else os.sep + rel)
    try:
        return str(Path(os.path.relpath(path, cfg["clip_root"])).parent)
    except ValueError:
        return Path(path).parent.name


def scan_clips(cfg, rescan=False):
    roots = clip_roots(cfg)
    out(f"Scanning {'; '.join(roots) or '(no clip folder found - check Settings)'} ...")
    max_b = int(cfg.get("max_mb", 60)) * 1024 * 1024
    paths = []
    with pstage("  scan_clips: walk + stat clips + tag_game"):
        for p in sorted(set(walk_files(roots, VIDEO_EXT, MIN_VIDEO, cfg))):
            try:
                if tag_game(p, cfg)[0] and os.path.getsize(p) <= max_b:
                    paths.append(p)
            except OSError:
                pass
        paths.sort()
    with pstage("  scan_clips: read clips cache"):
        cache = {} if rescan else load_json(CLIPS_CACHE, {})
    with pstage("  scan_clips: cache check (file_key stat per clip)"):
        todo = [p for p in paths if rescan or file_key(p) not in cache or cache[file_key(p)].get("bar_sig") != json.dumps(cfg["bar"])]
    out(f"  {len(paths)} clips found" + (f", {len(todo)} new/changed to probe" if todo else " (all cached)"))
    recs = []
    with pstage("  scan_clips: analyse_clip loop (6 threads)"):
        with ThreadPoolExecutor(max_workers=6) as ex:
            for i, (p, rec) in enumerate(ex.map(lambda p: analyse_clip(p, cache, rescan, cfg["bar"]), paths), 1):
                recs.append(rec)
                progress(i / max(1, len(paths)), f"Scanning {i} / {len(paths)}")
                if todo and i % 50 == 0:
                    out(f"    {i}/{len(paths)}")
    with pstage("  scan_clips: save clips cache"):
        live = {file_key(p) for p in paths}
        save_json(CLIPS_CACHE, {k: v for k, v in cache.items() if k in live})
    maxd = float(cfg.get("max_dur_s", 60))
    keep = []
    for r in recs:
        r["game"], r["game_src"] = tag_game(r["path"], cfg)
        if not r.get("error") and r.get("dur", 0) > maxd:
            continue                                    # longer than the limit: not a replay-buffer clip
        keep.append(r)
    return keep


# --------------------------------------------------------------------- audio
def read_tags(path):
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
        if f is not None and f.tags:
            a = (f.tags.get("artist") or [""])[0]
            t = (f.tags.get("title") or [""])[0]
            dur = getattr(f.info, "length", 0)
            return a, t, dur
        return "", "", getattr(getattr(f, "info", None), "length", 0) if f else 0
    except Exception:
        return "", "", 0


def parse_filename(path):
    stem = Path(path).stem
    stem = re.sub(r"^\s*\d{1,3}[\s._-]+", "", stem)
    if " - " in stem:
        a, t = stem.split(" - ", 1)
        return a.strip(), t.strip()
    return "", stem.strip()


AUDIO_MIN_AGE_S = 15.0                         # V6.1.2: a file modified less than this long ago may still be being written
AUDIO_STABLE_WAIT_S = 0.5


def scan_audio(cfg, rescan=False):
    """V6.1.2: the cache key of every file is computed ONCE (when it is listed) and stored in the record (rec["key"]); the cache is saved
    with those keys (no second stat, so a file that changes meanwhile can no longer raise). New files that are still being written
    (modified < 15 s ago, size 0, or size / mtime changing over 0.5 s) are skipped this run and never cached; one unreadable file never aborts."""
    mp3 = cfg.get("mp3_dir")
    paths = sorted(walk_files([mp3], AUDIO_EXT, 0, cfg)) if mp3 and os.path.isdir(mp3) else []
    cache = {} if rescan else load_json(AUDIO_CACHE, {})
    listed = []                                    # (path, key, size, mtime)
    for p in paths:
        try:
            st = os.stat(p)
            listed.append((p, f"{p}|{st.st_size}|{int(st.st_mtime)}", st.st_size, st.st_mtime))
        except OSError:
            continue
    now, skipped, fresh, ok = time.time(), 0, [], []
    for it in listed:
        if it[1] in cache:
            ok.append(it)
        elif it[2] <= 0 or now - it[3] < AUDIO_MIN_AGE_S:
            skipped += 1
        else:
            fresh.append(it)
    if fresh:
        time.sleep(AUDIO_STABLE_WAIT_S)
        for p, k, size, mt in fresh:
            try:
                st = os.stat(p)
            except OSError:
                skipped += 1
                continue
            if st.st_size != size or st.st_mtime != mt:
                skipped += 1
            else:
                ok.append((p, k, size, mt))
    recs, newc = [], {}
    for p, k, _, _ in sorted(ok):
        try:
            if k not in cache:
                a, t, d = read_tags(p)
                if not t:
                    fa, ft = parse_filename(p)
                    a, t = a or fa, ft
                cache[k] = {"path": p, "artist": a, "title": t, "dur": d}
            newc[k] = cache[k]
            recs.append(dict(cache[k], key=k))
        except Exception:
            skipped += 1
    if skipped:
        out(f"songs: {skipped} file(s) still being written, skipped this run")
    try:
        save_json(AUDIO_CACHE, newc)
    except Exception as ex:
        out(f"songs: cache not saved ({ex})")
    return recs


# ------------------------------------------------------------------ playlist
HEADER_ALIASES = {
    "title": ["track name", "track", "title", "name", "song"],
    "artist": ["artist name(s)", "artist names", "artist name", "artists", "artist"],
    "added": ["added at", "added", "date added"],
    "uri": ["track uri", "uri", "track id"],
    "dur": ["duration (ms)", "duration_ms", "duration ms", "duration"],
    "tempo": ["tempo", "bpm"],
    "energy": ["energy"],
    "dance": ["danceability"],
}


def newest_csv(cfg):
    d = Path(cfg["playlist_dir"])
    files = sorted(d.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True) if d.is_dir() else []
    return files[0] if files else None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _ms(v):
    try:
        return float(v) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def read_playlist(cfg):
    p = newest_csv(cfg)
    if not p:
        return None, [], {}
    with open(p, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        heads = {h.strip().lower(): h for h in (rd.fieldnames or [])}
        col = {}
        for k, names in HEADER_ALIASES.items():
            col[k] = next((heads[n] for n in names if n in heads), None)
        rows = []
        for r in rd:
            title = (r.get(col["title"]) or "").strip() if col["title"] else ""
            if not title:
                continue
            artist = (r.get(col["artist"]) or "").replace(";", ", ").strip() if col["artist"] else ""
            rows.append({"title": title, "artist": artist,
                         "added": (r.get(col["added"]) or "").strip() if col["added"] else "",
                         "uri": (r.get(col["uri"]) or "").strip() if col["uri"] else "",
                         "dur": _ms(r.get(col["dur"])) if col["dur"] else 0.0,
                         "tempo": _f(r.get(col["tempo"])) if col["tempo"] else 0.0,
                         "energy": _f(r.get(col["energy"])) if col["energy"] else None,
                         "dance": _f(r.get(col["dance"])) if col["dance"] else None})
    return p, rows, col


_TAGWORDS = re.compile(r"\b(remix|slowed|reverb|sped up|speed up|nightcore|remaster(?:ed)?(?: \d{4})?|official(?: music)?(?: video| audio)?|"
                       r"lyrics?(?: video)?|audio|video|version|radio edit|edit|extended|original mix|mono|stereo|hd|hq|bass boosted)\b")


def clean(s):
    """Lowercase; drop feat./ft., bracketed text, remix/slowed/remaster/official tags and punctuation."""
    s = (s or "").lower()
    s = re.sub(r"\(.*?\)|\[.*?\]|\{.*?\}", " ", s)
    s = re.sub(r"\b(feat|ft|featuring)\b\.?.*", " ", s)
    s = _TAGWORDS.sub(" ", s)
    s = re.sub(r"[^\w\s]|_", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def audio_titles(a):
    """Normalised title candidates for a file: filename (title only), tag title, and the part after 'Artist - '."""
    stem = re.sub(r"^\s*\d{1,3}[\s._-]+", "", Path(a["path"]).stem)
    c = {clean(stem), clean(a.get("title", ""))}
    if " - " in stem:
        c.add(clean(stem.split(" - ", 1)[1]))
    return [x for x in c if x]


def _rank_key(r):
    return r.get("uri") or f"{r['artist']} - {r['title']}"


def _rank_key(r):
    return r.get("uri") or f"{r['artist']} - {r['title']}"


SONG_DUPS = set()                      # V6.5: files that exactly match a track another (larger) file already has (Flag column: DUPLICATE)
_FN_BAD = re.compile(r'[\\/:*?"<>|]')    # characters Windows cannot keep in a file name: dropped on both sides before comparing
_SPLIT_ARTISTS = re.compile(r", | & ")


def norm_song(s):
    """Both sides of the song match are normalised the same way: NFKC, casefold, one kind of quote and dash, no characters a file name
    cannot hold, single spaces, trimmed. Every other character (Cyrillic, Japanese, ...) is kept."""
    import unicodedata
    s = unicodedata.normalize("NFKC", str(s or "")).casefold()
    s = re.sub("[\u2018\u2019\u201a\u201b\u2032\u00b4`]", "'", s)
    s = re.sub("[\u201c\u201d\u201e\u201f\u2033]", '"', s)
    s = re.sub("[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]", "-", s)
    s = _FN_BAD.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def _artists_of(s):
    return {x for x in (norm_song(a) for a in _SPLIT_ARTISTS.split(str(s or ""))) if x}


def parse_song_file(a):
    """(title, artists) of an MP3: the file name split on its LAST ' - ' (before = title, after = artist list split on ', ' and ' & ');
    when the name cannot be parsed the title / artist tags are used. (None, set()) when neither works."""
    stem = Path(a["path"]).stem
    if " - " in stem:
        t, ar = stem.rsplit(" - ", 1)
        if norm_song(t) and _artists_of(ar):
            return norm_song(t), _artists_of(ar)
    if norm_song(a.get("title", "")) and _artists_of(a.get("artist", "")):
        return norm_song(a["title"]), _artists_of(a["artist"])
    return None, set()


def _title_core(t):
    """A normalised title without bracketed parts and without a dash suffix: '(feat. X)', '- Radio Edit', '- Remix', '(Sped Up)'."""
    t = re.sub(r"\(.*?\)|\[.*?\]|\{.*?\}", " ", t)
    t = t.split(" - ")[0]
    return re.sub(r"\s+", " ", t).strip()


def _file_size(a):
    try:
        return int(_akey(a).rsplit("|", 2)[1])
    except (IndexError, ValueError):
        try:
            return os.path.getsize(a["path"])
        except OSError:
            return 0


def match_playlist(rows, audio, cfg):
    """V6.5: a file matches a playlist track only when BOTH the title and an artist agree (nothing fuzzy, no leftover assignments).
    ok (100): normalised title identical AND at least one normalised artist identical. CHECK (80): an artist matches and the title is the
    same once bracketed / dash suffixes are removed. Everything else: no match. One file per track: of several files that match a track
    exactly the larger one is kept and the others are listed in SONG_DUPS (flag DUPLICATE). Manual matches (song_overrides) come first."""
    SONG_DUPS.clear()
    if not rows or not audio:
        return [], list(rows)
    rk = _rank_key
    taken_r, taken_a, matched = set(), set(), []
    idx = {a["path"]: i for i, a in enumerate(audio)}
    for path, key in cfg.get("song_overrides", {}).items():              # manual matches from "Change match" are kept
        i = idx.get(path)
        j = next((k for k, r in enumerate(rows) if rk(r) == key and k not in taken_r), None)
        if i is not None and j is not None and i not in taken_a:
            taken_a.add(i)
            taken_r.add(j)
            matched.append((i, j, 100))
    by_title = {}
    for j, r in enumerate(rows):
        if j in taken_r:
            continue
        by_title.setdefault(norm_song(r["title"]), []).append((j, _artists_of(r["artist"])))
    parsed = [parse_song_file(a) if i not in taken_a else (None, set()) for i, a in enumerate(audio)]
    sizes = [_file_size(a) for a in audio]
    exact = {}                                                           # track -> [file indexes]
    for i, (t, ars) in enumerate(parsed):
        if t is None:
            continue
        for j, rars in by_title.get(t, ()):
            if ars & rars:
                exact.setdefault(j, []).append(i)
    exact_files = set()
    for j in sorted(exact):
        files = sorted(exact[j], key=lambda i: (-sizes[i], audio[i]["path"].lower()))
        free = [i for i in files if i not in taken_a]
        if not free:
            continue
        keep = free[0]
        taken_a.add(keep)
        taken_r.add(j)
        matched.append((keep, j, 100))
        for i in files:
            if i != keep:
                if i not in exact_files:
                    SONG_DUPS.add(audio[i]["path"])
            exact_files.add(i)
    # a file that matched exactly (or is another file's duplicate) never becomes somebody's CHECK candidate
    cores = {}
    for j, r in enumerate(rows):
        if j in taken_r:
            continue
        cores.setdefault(_title_core(norm_song(r["title"])), []).append((j, _artists_of(r["artist"]), norm_song(r["title"])))
    cand = []
    for i, (t, ars) in enumerate(parsed):
        if t is None or i in taken_a or i in exact_files:
            continue
        for j, rars, rt in cores.get(_title_core(t), ()):
            if ars & rars and _title_core(t):
                cand.append((abs(len(rt) - len(t)), -sizes[i], audio[i]["path"].lower(), i, j))
    for _, _, _, i, j in sorted(cand):
        if i not in taken_a and j not in taken_r:
            taken_a.add(i)
            taken_r.add(j)
            matched.append((i, j, 80))
    matched.sort()
    return [(rows[j], audio[i], sc) for i, j, sc in matched], [r for j, r in enumerate(rows) if j not in taken_r]


def match_flag(path, r, sc):
    """The Flag column of the song match: ok | CHECK (under 85) | DUPLICATE | NO MATCH."""
    if not r:
        return "DUPLICATE" if path in SONG_DUPS else "NO MATCH"
    return "CHECK (under 85)" if sc < 85 else "ok"


def write_song_matches(audio, matched):
    """montage_data\\song_matches.csv: file, matched track, score, flag (under 85 = check it)."""
    by = {a["path"]: (r, sc) for r, a, sc in matched}
    with open(DATA / "song_matches.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["file", "matched track", "artist", "score", "flag"])
        for a in sorted(audio, key=lambda a: a["path"].lower()):
            r, sc = by.get(a["path"], (None, 0))
            w.writerow([a["path"], r["title"] if r else "", r["artist"] if r else "", sc, match_flag(a["path"], r, sc)])


# ------------------------------------------------------------- kill detection
# V4: OCR (RapidOCR, offline) on the killfeed region. No name template, no scale search.
NORM_W, NORM_H = 1920, 1080     # every clip is normalised to this (content rect stretched)
FPS = 15                        # killfeed sampling rate
OCR_MAX_PER_S = 4               # at most this many OCR calls per second of clip
OCR_GAP = int(math.ceil(FPS / OCR_MAX_PER_S))      # frames between two OCR calls (4 -> 3.75/s)
OCR_HEARTBEAT = FPS             # OCR at least once a second even if nothing changed (every row is seen twice)
DIFF_THR = 0.035                # share of changed 'bright text' pixels in a band that counts as a change
TRACK_KEEP_S = 8.0              # a killfeed row is remembered this long (so it is never counted twice)
CACHE_V = 5                     # bump when the cached per-frame format changes (5 = raw OCR boxes)
ALGO = f"v{CACHE_V}"
MY_NAME = "fireaxe"
MY_NAME_CS2 = "火斧"               # V5.42B: CS2 renders my name 'fireaxe火斧'; OCR garbles 'fireaxe' but reads these two reliably
NAME_MIN = 80                   # rapidfuzz partial_ratio needed for FIREAXE
# V6.0: Settings > Player names. Latin names match fuzzily (as 'fireaxe' always did); a name with non-ASCII letters (CJK) is found as exact
# text and makes the row mine when the Latin read is garbled (as '火斧' in CS2 always did). Defaults = exactly what V5.x hardcoded.
DEFAULT_PLAYER_NAMES = {"valorant": [MY_NAME], "cs2": [MY_NAME, MY_NAME_CS2]}
_NAMES = {g: list(v) for g, v in DEFAULT_PLAYER_NAMES.items()}


def norm_names(lst, game):
    """Clean list (lower case, no blanks / duplicates). An empty list = the defaults."""
    if isinstance(lst, str):
        lst = lst.split(";")
    out_ = []
    for n in lst or []:
        n = str(n).strip().lower()
        if n and n not in out_:
            out_.append(n)
    return out_ or list(DEFAULT_PLAYER_NAMES.get(game, [MY_NAME]))


def set_player_names(cfg):
    pn = cfg.get("player_names") if isinstance(cfg.get("player_names"), dict) else {}
    for g in DEFAULT_PLAYER_NAMES:
        _NAMES[g] = norm_names(pn.get(g), g)


def names_split(game=None):
    """(Latin names, non-ASCII names) for one game; game None = every game's names together."""
    ns = [n for g in ([game] if game in _NAMES else list(_NAMES)) for n in _NAMES[g]]
    ns = list(dict.fromkeys(ns))
    return [n for n in ns if n.isascii()], [n for n in ns if not n.isascii()]


def names_for_cache(game):
    return sorted(_NAMES.get(game, [MY_NAME]))


def entry_names(entry, game):
    """Names a cached kill entry was scanned with; entries with no record count as scanned with the DEFAULT names."""
    n = entry.get("names") if isinstance(entry, dict) else None
    return sorted(norm_names(n, game)) if n else sorted(DEFAULT_PLAYER_NAMES.get(game, [MY_NAME]))


def names_stale(entry, game):
    return entry_names(entry, game) != names_for_cache(game)
DEFAULT_REGION = {"valorant": [0.58, 0.05, 1.0, 0.42], "cs2": [0.58, 0.03, 1.0, 0.40]}   # fractions of the content rect


def read_img(path):
    import cv2
    import numpy as np
    img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"cannot read image {path}")
    return img


def content_rect(rec, cfg):
    """[x,y,w,h] of the real picture inside a clip: the fixed bar crop when the clip has those bars."""
    if rec.get("bars") and cfg.get("bar"):
        return cfg["bar"]["rect"]
    return [0, 0, rec["w"], rec["h"]]


def norm_image(img, cfg):
    import cv2
    h, w = img.shape[:2]
    bar = cfg.get("bar")
    if bar and [w, h] == bar["src"] and outside_dark(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), bar["rect"]):
        x, y, cw, ch = bar["rect"]
        img = img[y:y + ch, x:x + cw]
    return cv2.resize(img, (NORM_W, NORM_H), interpolation=cv2.INTER_AREA if img.shape[1] >= NORM_W else cv2.INTER_CUBIC)


def pick_roi(img, title):
    import cv2
    h, w = img.shape[:2]
    s = min(1500 / w, 850 / h)
    disp = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_CUBIC if s > 1 else cv2.INTER_AREA)
    out(f"  {title}   (drag, then press ENTER)")
    x, y, rw, rh = cv2.selectROI(title, disp, showCrosshair=False, fromCenter=False)
    cv2.destroyAllWindows()
    if rw < 2 or rh < 2:
        raise SystemExit("no selection made")
    return int(x / s), int(y / s), max(2, int(round(rw / s))), max(2, int(round(rh / s)))


_OCR = threading.local()


def ocr_engine():
    """One RapidOCR engine per thread (models ship inside the pip package: fully offline)."""
    if getattr(_OCR, "e", None) is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            raise RuntimeError("RapidOCR missing: python -m pip install --user rapidocr-onnxruntime")
        import logging
        logging.getLogger("RapidOCR").setLevel(logging.ERROR)
        with pstage("OCR engine creation (RapidOCR())"):
            _OCR.e = RapidOCR()
    return _OCR.e


def bright_mask(bgr):
    """White HUD pixels (killfeed text and weapon icons): bright and unsaturated."""
    import cv2
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return (hsv[..., 2] >= 185) & (hsv[..., 1] <= 70)


def weapon_blobs(bgr, th):
    """White icon candidates sized like a killfeed icon (th = text box height). Wide = gun/knife, squarish = utility."""
    import cv2
    import numpy as np
    m = bright_mask(bgr).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, _, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    res = []
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        if h < 0.45 * th or h > 2.6 * th or w < 0.5 * h or a < 0.18 * w * h or w > 12 * th:
            continue
        res.append([x, y, w, h, round(a / float(w * h), 2)])
    return res


def _ocr_raw(img, det=True):
    e = ocr_engine()
    if det:
        r, _ = e(img, use_cls=False)
        res = []
        for box, text, conf in r or []:
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            res.append([int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)), str(text).strip(), round(float(conf), 3)])
        return res
    r, _ = e(img, use_det=False, use_cls=False)
    return (str(r[0][0]).strip(), float(r[0][1])) if r else ("", 0.0)


def ocr_frame(bgr):
    """RAW OCR of one killfeed crop: text boxes [x0,y0,x1,y1,text,conf] + white icon blobs [x,y,w,h].
    A box that swallowed a gun-sized icon is split there and both halves re-read."""
    import numpy as np
    boxes = _ocr_raw(bgr)
    if not boxes:
        return [], []
    th = float(np.median([b[3] - b[1] for b in boxes]))
    blobs = weapon_blobs(bgr, th)
    outb = []
    for b in boxes:
        bh = b[3] - b[1]
        inner = [g for g in blobs if g[2] >= 2 * g[3] and g[4] >= 0.5 and g[3] >= 0.55 * bh and g[0] - b[0] >= 0.8 * bh
                 and b[2] - (g[0] + g[2]) >= 0.8 * bh and abs((g[1] + g[3] / 2) - (b[1] + b[3]) / 2) <= 0.5 * bh]
        if not inner:
            outb.append(b)
            continue
        g = max(inner, key=lambda g: g[2])
        halves = [(xa, xb) + _ocr_raw(bgr[b[1]:b[3], xa:xb], det=False) for xa, xb in ((b[0], g[0] - 1), (g[0] + g[2] + 1, b[2]))]
        if all(len(_alnum(t)) >= 3 and c >= 0.6 for _, _, t, c in halves):
            outb += [[xa, b[1], xb, b[3], t, round(c, 3)] for xa, xb, t, c in halves]
        else:
            outb.append(b)
    for b in outb:                                         # V5.42: background colour of the box (Valorant team colour)
        b.append(side_colour(bgr, b))
    return outb, blobs


def side_colour(bgr, b):
    """'r' (enemy red), 'g' (teammate green / teal) or '' (unknown / dark) behind a killfeed name box, text pixels excluded."""
    import numpy as np
    x0, y0, x1, y1 = (max(0, int(v)) for v in b[:4])
    roi = bgr[y0:y1 + 1, x0:x1 + 1]
    if roi.size == 0:
        return ""
    px = roi[~bright_mask(roi)].astype(int)
    px = px[px.sum(1) >= 150]
    if len(px) < 0.15 * roi.shape[0] * roi.shape[1]:          # pale highlight (my own row): text-like pixels, minus pure white
        px = roi.reshape(-1, 3).astype(int)
        px = px[(px.sum(1) >= 150) & (px.min(1) < 235)]
        if len(px) < 0.15 * roi.shape[0] * roi.shape[1]:
            return ""
    bl, g, r = (float(np.median(px[:, i])) for i in range(3))
    if r > g + 40 and r > bl + 30:
        return "r"
    if g > r + 15:
        return "g"
    return ""


def _box_appear(b):
    return next((v for v in b[6:] if not isinstance(v, str)), 0)


def _box_col(b):
    return next((v for v in b[6:] if isinstance(v, str)), "")


def _alnum(s):
    return re.sub(r"[\W_]+", "", s or "")


def _name_match1(t, name):
    from rapidfuzz import fuzz
    if len(_alnum(t)) < 5:
        return float(fuzz.ratio(_alnum(t), name)), 0
    if len(t) <= len(name):
        return float(fuzz.ratio(t, name)), 0
    al = fuzz.partial_ratio_alignment(name, t)
    return float(al.score), int(al.dest_start)


def name_match(text, game=None, with_name=False):
    """(score 0-100, start index in text) of the best FIREAXE match (V6.0: best of the game's Latin player names). rapidfuzz
    partial_ratio, case-insensitive; a text shorter than 5 letters must match as a whole (so 'fire' or 'axe' alone never counts)."""
    t = (text or "").lower()
    best = None
    for nm_ in names_split(game)[0] or [MY_NAME]:
        r = _name_match1(t, nm_) + (nm_,)
        if best is None or r[0] > best[0]:
            best = r
    return best if with_name else best[:2]


def _side_col(bx):
    cs = [_box_col(b) for b in bx if _box_col(b)]
    return max(set(cs), key=cs.count) if cs else ""


def ocr_rows(boxes, blobs, game=None):
    """Group OCR boxes into killfeed rows (by y-centre), find each row's weapon icon (white blob between the texts, else the
    largest horizontal gap) and split into killer side / victim side. CS2 (V5.42B): the weapon is the largest LONG icon -
    a square modifier icon next to it (through-smoke, wallbang, no-scope, blind, headshot) is never taken for the weapon."""
    import numpy as np
    good = [b for b in boxes if len(_alnum(b[4])) >= 2 and b[5] >= 0.5]
    if not good:
        return []
    th = float(np.median([b[3] - b[1] for b in good]))
    # boxes that are really the icon (OCR read the silhouette as text)
    def ov(b, g):
        ix = max(0, min(b[2], g[0] + g[2]) - max(b[0], g[0]))
        iy = max(0, min(b[3], g[1] + g[3]) - max(b[1], g[1]))
        return ix * iy
    good = [b for b in good if not ((b[5] < 0.75 or len(_alnum(b[4])) <= 2) and
                                    any(ov(b, g) > 0.5 * (b[2] - b[0]) * (b[3] - b[1]) and g[2] >= 1.2 * g[3] for g in blobs))]
    rows = []
    for b in sorted(good, key=lambda b: (b[1] + b[3]) / 2):
        cy = (b[1] + b[3]) / 2
        if rows and abs(cy - rows[-1]["cy"]) <= 0.45 * max(th, b[3] - b[1]):
            r = rows[-1]
            r["boxes"].append(b)
            r["cy"] = float(np.mean([(x[1] + x[3]) / 2 for x in r["boxes"]]))
        else:
            rows.append({"cy": cy, "boxes": [b]})
    res = []
    for r in rows:
        bx = sorted(r["boxes"], key=lambda b: b[0])
        rh = float(np.median([b[3] - b[1] for b in bx]))
        y0, y1 = min(b[1] for b in bx), max(b[3] for b in bx)
        free = [g for g in blobs if abs(g[1] + g[3] / 2 - r["cy"]) <= 0.6 * max(rh, g[3])
                and not any(ov(b, g) > 0.5 * g[2] * g[3] for b in bx)]
        between = [g for g in free if bx[0][0] < g[0] + g[2] / 2 < bx[-1][2]]
        icon, split = None, None
        if between or free:
            pick = between or free
            if game == "cs2" and any(g[2] >= 1.5 * g[3] for g in pick):
                pick = [g for g in pick if g[2] >= 1.5 * g[3]]
            icon = max(pick, key=lambda g: g[2] * g[3])
            split = "icon"
            cut = icon[0] + icon[2] / 2
        elif len(bx) >= 2:
            gaps = [(bx[i + 1][0] - bx[i][2], i) for i in range(len(bx) - 1)]
            gw, gi = max(gaps)
            if gw >= 0.8 * rh:
                split = "gap"
                cut = (bx[gi][2] + bx[gi + 1][0]) / 2
                icon = [int(bx[gi][2] + 0.15 * rh), int(r["cy"] - 0.6 * rh), int(max(1, gw - 0.3 * rh)), int(1.2 * rh)]
        if split is None:
            res.append({"y": int(r["cy"]), "y0": y0, "y1": y1, "th": rh, "killer": [], "victim": [], "icon": None, "gun": False,
                        "split": None, "hs": False, "boxes": bx, "appear": min(_box_appear(b) for b in bx),
                        "appear_max": max(_box_appear(b) for b in bx), "kcol": "", "vcol": ""})
            continue
        kil = [b for b in bx if (b[0] + b[2]) / 2 < cut]
        vic = [b for b in bx if (b[0] + b[2]) / 2 >= cut]
        gun = icon[2] >= 1.5 * icon[3] if split == "icon" else icon[2] >= 1.9 * rh
        hs = split == "icon" and any(g is not icon and 0 <= g[0] - (icon[0] + icon[2]) <= 1.5 * rh and 0.6 <= g[2] / max(1, g[3]) <= 1.6
                                     and (not vic or g[0] + g[2] <= vic[0][0] + 2) for g in free)
        res.append({"y": int(r["cy"]), "y0": y0, "y1": y1, "th": rh, "killer": kil, "victim": vic, "icon": icon, "gun": bool(gun),
                    "split": split, "hs": bool(hs), "boxes": bx, "appear": min(_box_appear(b) for b in bx),
                    "appear_max": max(_box_appear(b) for b in bx), "kcol": _side_col(kil), "vcol": _side_col(vic)})
    for d in res:
        d["game"] = game
        d["ktext"] = " ".join(b[4] for b in d["killer"])
        d["vtext"] = " ".join(b[4] for b in d["victim"])
        d["ks"], kpos = name_match(d["ktext"], game) if d["killer"] else (0.0, 0)
        d["vs"], _ = name_match(d["vtext"], game) if d["victim"] else (0.0, 0)
        if names_split(game)[1]:                           # V5.42B: '火斧' is my name too (garbled 'fireaxe' before it is part of it)
            for side in ("k", "v"):
                txt = d[side + "text"]
                i = min([x for x in (txt.find(c_) for c_ in names_split(game)[1]) if x >= 0], default=-1)
                if i < 0 or d[side + "s"] >= 100:
                    continue
                if d[side + "s"] < NAME_MIN:
                    d["cjk"] = True                        # only '火斧' makes this row mine
                    if side == "k":
                        j = txt.rfind("+", 0, i)           # 'killer + fireaxe火斧' = my assist; otherwise all of it is my name
                        kpos = j + 1 if j >= 0 else 0
                d[side + "s"] = 100.0
        pre = d["ktext"][:kpos]
        d["before"] = pre.strip() if ("+" in pre or len(_alnum(pre)) >= 3) else ""
    return res


def classify_row(r, cfg=None, lg=0.0, game=None):
    """THE rule set, used identically by the crop view, Dry plan, Render, sync report and Self-test.
    Returns [(verdict, reason), ...]: verdict in kill / death / reject / none (one row can be both kill and death).
    V5.42B: the knife and revive / resurrect rules are VALORANT ONLY (its icons and team colours); in CS2 a row is a kill,
    a death, a utility kill (small square icon only) or an assist."""
    out_ = []
    thr = float((cfg or {}).get("name_match", NAME_MIN))
    val = (game or r.get("game")) != "cs2"
    if r.get("split") is None and max(r.get("ks", 0), r.get("vs", 0)) >= thr:
        return [("none", "FIREAXE seen but no weapon icon / gap to split the row")]
    if val and r.get("vcol") == "g" and max(r.get("ks", 0), r.get("vs", 0)) >= thr and r.get("kcol") != "r":
        # V5.42 colour first: a GREEN (teammate) victim side with no red killer = Clove self-revive / Sage resurrect (of me or a
        # teammate). Never a kill, never a death. (My real death: red killer side, me on the green victim side.)
        return [("revive", f"revive: green victim side ('{r['ktext'] or '-'}' -> '{r.get('vtext') or '-'}') - teammate revive / "
                           "resurrect, not a kill, not a death")]
    if not val and r.get("ks", 0) >= thr and r.get("vs", 0) >= thr:
        return [("none", f"CS2: FIREAXE on both sides ('{r['ktext']}' -> '{r.get('vtext') or '-'}') - not a kill")]
    if val and r.get("ks", 0) >= thr and (r.get("vs", 0) >= thr or (not r.get("vtext") and not r["gun"])):
        # Clove self-revive: FIREAXE with an ability icon and no victim, or FIREAXE on both sides. Never a kill, never a death.
        return [("revive", f"revive: FIREAXE self-revive row ('{r['ktext']}' -> '{r.get('vtext') or '-'}') - not a kill")]
    if r.get("vs", 0) >= thr:
        out_.append(("death", f"death: FIREAXE on the victim side ('{r['vtext']}' {r['vs']:.0f})"))
    if r.get("ks", 0) >= thr:
        w = "weapon icon" if r["split"] == "icon" else "gap"
        if not r["gun"]:
            out_.append(("reject", f"utility: small/square {w} (grenade, molotov, ability)"))
        elif r.get("before"):
            out_.append(("reject", f"assist: '{r['before']}' comes before FIREAXE on the killer side"))
        else:
            out_.append(("kill", f"kill: FIREAXE first on the killer side ('{r['ktext']}' {r['ks']:.0f}, split by {w})"))
    return out_ or [("none", "no FIREAXE in this row")]


def row_desc(r):
    v = classify_row(r)
    return f"[{r['ktext'] or '-'}] {'=gun=' if r['gun'] else '=util=' if r['icon'] else '=?='} [{r['vtext'] or '-'}] -> " + \
        " + ".join(f"{a.upper()} ({b})" for a, b in v)


def region_px(rec, det, cfg):
    """Killfeed crop in source pixels (x, y, w, h) from the region fractions of the content rect."""
    cx, cy, cw, ch = content_rect(rec, cfg)
    x0, y0, x1, y1 = det.d["region"]
    rx, ry = int(cx + x0 * cw) & ~1, int(cy + y0 * ch) & ~1
    rw, rh = max(2, int((x1 - x0) * cw) & ~1), max(2, int((y1 - y0) * ch) & ~1)
    return rx, ry, min(rw, rec["w"] - rx) & ~1, min(rh, rec["h"] - ry) & ~1


def region_filter(rec, det, cfg):
    """ffmpeg filter that cuts the killfeed region out of the content rect and stretches it to 1920x1080 space."""
    rx, ry, rw, rh = region_px(rec, det, cfg)
    return f"crop={rw}:{rh}:{rx}:{ry},scale={det.dw}:{det.dh}:flags=bicubic,format=bgr24"


class Detector:
    """Killfeed REGION per game (fractions of the content rect). Calibration is optional: defaults are top-right."""
    def __init__(self, game):
        d = load_json(DATA / f"detect_{game}.json", None) or {}
        reg = d.get("region") or DEFAULT_REGION[game]
        self.game, self.calibrated = game, bool(d.get("region"))
        self.d = {"region": [float(v) for v in reg]}
        self.d["stamp"] = "ocr" + hashlib.md5(repr([round(v, 4) for v in self.d["region"]]).encode()).hexdigest()[:8]
        self.dw = max(16, int(round((reg[2] - reg[0]) * NORM_W)) & ~1)
        self.dh = max(16, int(round((reg[3] - reg[1]) * NORM_H)) & ~1)

    def crop_norm(self, img):
        """Killfeed crop out of a 1920x1080 normalised frame."""
        x0, y0, x1, y1 = self.d["region"]
        return img[int(y0 * NORM_H):int(y0 * NORM_H) + self.dh, int(x0 * NORM_W):int(x0 * NORM_W) + self.dw]


def frame_stream(path, rec, det, cfg, fps, use_hw=True):
    """Yield killfeed-region frames (BGR) at `fps`. ffmpeg decodes (NVDEC if possible), numpy receives."""
    import numpy as np
    n = det.dw * det.dh * 3
    vf = f"fps={fps}," + region_filter(rec, det, cfg)
    for hw in ((True, False) if use_hw else (False,)):
        cmd = ["ffmpeg", "-v", "error"] + (["-hwaccel", "cuda"] if hw else []) + \
              ["-i", path, "-an", "-sn", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=n * 2)
        got = 0
        PROCS.append(p)
        try:
            while not CANCEL.is_set():
                b = p.stdout.read(n)
                if len(b) < n:
                    break
                got += 1
                yield np.frombuffer(b, np.uint8).reshape(det.dh, det.dw, 3)
        finally:
            p.kill()
            p.wait()
            if p in PROCS:
                PROCS.remove(p)
        if got or CANCEL.is_set():
            return


ONSET_CACHE = DATA / "onsets_cache.json"
SCALES = DATA / "scales.json"          # V3 leftover; only deleted by Clear cache


class KillStore:
    """One small JSON file per scanned clip (written atomically the moment the clip finishes): resumable, never rescans."""
    def __init__(self):
        self.dir = DATA / f"kills_v{CACHE_V}"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _p(self, key):
        fkey = "|".join(key.split("|")[:3])
        return self.dir / (hashlib.md5(fkey.encode()).hexdigest()[:12] + "_" + hashlib.md5(key.encode()).hexdigest()[:12] + ".json")

    def __contains__(self, key):
        return self._p(key).exists()

    def get(self, key, default=None):
        try:
            return json.loads(self._p(key).read_text(encoding="utf-8")).get("e", default)
        except Exception:
            return default

    def put(self, key, entry):
        p = self._p(key)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"key": key, "e": entry}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

    def drop_file(self, fkey):
        pre = hashlib.md5(fkey.encode()).hexdigest()[:12] + "_"
        for p in self.dir.glob(pre + "*.json"):
            try:
                p.unlink()
            except OSError:
                pass

    def clear_all(self):
        for d in DATA.glob("kills_v*"):
            shutil.rmtree(d, ignore_errors=True)
        self.dir.mkdir(parents=True, exist_ok=True)


def load_kills_cache():
    return KillStore()


def _cache_index():
    """V5.5: {(name, size, mtime, game): [(file, dir, path, stamp, algo, bars)]} of every cached kill entry (key read from the
    first bytes of each file - the OCR payload is never loaded)."""
    idx = {}
    for d in DATA.glob("kills_v*"):
        for p in d.glob("*.json"):
            try:
                with open(p, "rb") as f:
                    head = f.read(3000).decode("utf-8", "ignore")
                key = json.loads('"' + re.match(r'\{"key": "((?:[^"\\]|\\.)*)"', head).group(1) + '"')
                path, size, mt, game, tail = key.split("|")[:5]
                m = re.match(r"(ocr[0-9a-f]{8})v(\d+)(.*)$", tail)
                idx.setdefault((os.path.basename(path).lower(), size, mt, game), []).append((p, d.name, path, m.group(1), m.group(2), m.group(3)))
            except Exception:
                continue
    return idx


REGION_HELD = []                       # V6.7.6: [(path, [stored region hashes], current hash)] Valorant clips held back from a "calibration changed" rescan
REGION_PROMPT = [None]                 # V6.7.6: hook(held, current_hash) the GUI sets: asks the user; nothing here ever rescans Valorant by itself
REGION_CHANGED = "calibration changed (killfeed region)"


def region_hold_text(held, cur):
    """V6.7.6: the prompt / log text for held-back Valorant clips: how many, and the region hashes involved."""
    per = {}
    for _, stamps, _c in held:
        for h in stamps:
            per[h] = per.get(h, 0) + 1
    return (f"{len(held)} Valorant clip(s) have kill entries scanned with another killfeed region. Current region hash: {cur}. "
            f"Hashes stored for these clips: " + ", ".join(f"{h} ({n} clips)" for h, n in sorted(per.items())) +
            ". The old entries are kept either way (python montage.py regioncheck valorant / regionrestore valorant --use <hash> "
            "can make them valid again).")


def _relink_or_explain(jobs, dets, cache, cfg, region_ok=False):
    """V5.5: a kill cache survives updates. For every clip with no entry under today's key: a cached entry of the same file
    (name, size, time) with the same calibration + bars (the clip folder moved) is re-linked, not rescanned; the rest are
    rescanned and the log says WHY (calibration changed / black-bar crop changed / cache format changed / clip file changed /
    new clip). Returns the jobs that really need a scan."""
    idx = _cache_index()
    paths = {e[2].lower() for v in idx.values() for e in v}
    todo, why, linked, held = [], {}, 0, []
    for r, g in jobs:
        try:
            fk = file_key(r["path"])
        except OSError:
            todo.append((r, g))
            continue
        path, size, mt = fk.split("|")[:3]
        key = kills_key(r, g, dets[g])
        tail = key.split("|")[4]
        st, (algo, bars) = tail[:11], re.match(r"v(\d+)(.*)$", tail[11:]).groups()
        same = idx.get((os.path.basename(path).lower(), size, mt, g), [])
        hit = next((e for e in same if e[3] == st and e[4] == algo and e[5] == bars), None)
        if hit is not None:
            try:
                cache.put(key, json.loads(Path(hit[0]).read_text(encoding="utf-8"))["e"])
                linked += 1
                continue
            except Exception:
                pass
        if not same:
            reason = "clip file changed (size / time)" if path.lower() in paths else "new clip, never scanned"
        elif all(e[3] != st for e in same):
            reason = "calibration changed (killfeed region)"
        elif all(e[4] != algo for e in same):
            reason = f"cache format changed (v{same[0][4]} -> v{algo})"
        else:
            reason = "black-bar crop changed"
        if g == "valorant" and reason == REGION_CHANGED and not region_ok:
            held.append((path, sorted({e[3] for e in same}), st))         # V6.7.6: never automatic for Valorant; the old entries stay on disk
            continue
        why.setdefault(reason, []).append(Path(path).name)
        todo.append((r, g))
    if linked:
        out(f"kill cache: {linked} clip(s) re-linked (same file, new folder / path) - not rescanned")
    REGION_HELD[:] = held
    if held:
        txt = region_hold_text(held, held[0][2])
        out("NOT rescanning (needs your confirmation): " + txt)
        if REGION_PROMPT[0]:
            try:
                REGION_PROMPT[0](list(held), held[0][2])
            except Exception as ex:
                out(f"region prompt failed: {ex}")
    if why:
        out("rescanning: " + "; ".join(f"{k} ({len(v)})" for k, v in why.items()))
        for k, v in why.items():
            for n in v[:15]:
                out(f"  rescanning {n}: {k}")
    return todo


def cached_names(store, key, game):
    """Names a cached entry was scanned with, read from the first bytes of its file (the OCR payload is not loaded). No record =
    the default names (V6.0: old caches stay valid)."""
    try:
        with open(store._p(key), "rb") as f:
            head = f.read(4000).decode("utf-8", "ignore")
        head = head.split('"ocr":')[0]
        m = re.search(r'"names": (\[[^\]]*\])', head)
        return sorted(norm_names(json.loads(m.group(1)), game)) if m else sorted(DEFAULT_PLAYER_NAMES.get(game, [MY_NAME]))
    except Exception:
        return sorted(DEFAULT_PLAYER_NAMES.get(game, [MY_NAME]))


def stale_name_clips(cfg=None):
    """V6.0: clips whose cached scan used other player names than Settings has now (needs no OCR, never rescans by itself).
    Returns [(path, game)]."""
    set_player_names(cfg or load_config())
    dets = load_dets()
    store = load_kills_cache()
    res = []
    for r in scan_clips(cfg or load_config()):
        g = r.get("game")
        if r.get("error") or not r.get("w") or g not in dets:
            continue
        key = kills_key(r, g, dets[g])
        if key in store and cached_names(store, key, g) != names_for_cache(g):
            res.append((r["path"], g))
    return res


def rescan_stale_names(cfg=None):
    """Rescan only the name-stale clips (run in the background; cancel = CANCEL; the clips already done stay done, so a later
    call resumes with the rest)."""
    cfg = cfg or load_config()
    stale = stale_name_clips(cfg)
    out(f"player names changed: {len(stale)} clip(s) were scanned with other names")
    if not stale:
        return 0
    # the old entry stays until its rescan finishes (run_scan's put replaces the file): cancelled = still stale = resumable
    return run_scan(cfg, None, [p for p, _ in stale], 0, True)


def _band_changed(m, last):
    """Cheap pixel diff of the bright-text mask vs the last OCR'd frame, per horizontal band (~a killfeed row)."""
    d = m != last
    H = d.shape[0]
    bh = max(4, H // 12)
    return any(d[i:i + bh].mean() >= DIFF_THR for i in range(0, H, bh))


def _appear(box, buf, gray):
    """First buffered frame in which this text box already looked like it does now (= the frame the row became visible)."""
    import cv2
    import numpy as np
    x0, y0, x1, y1 = max(0, box[0]), max(0, box[1]), box[2], box[3]
    p = gray[y0:y1, x0:x1].astype(np.float32)
    if p.size < 16 or p.std() < 3:
        return buf[-1][0]
    for f, g in buf:
        q = g[y0:y1, x0:x1].astype(np.float32)
        if q.shape != p.shape:
            continue
        r = float(cv2.matchTemplate(q, p, cv2.TM_CCOEFF_NORMED)[0, 0]) if q.std() >= 3 else 0.0
        if r == r and r >= 0.8 and float(np.abs(q - p).mean()) <= 28:
            return f
    return buf[-1][0]


def scan_frames(frames):
    """OCR only when the killfeed changed (bright-pixel diff vs the last OCR'd frame), at most OCR_MAX_PER_S per second, plus a
    1 s heartbeat. Returns RAW results: [[frame, change_frame, boxes(+appear frame), blobs], ...] and the frame count."""
    import cv2
    import numpy as np
    res, last_m, last_f, since, buf, n = [], None, -10 ** 6, None, [], 0
    for f, fr in enumerate(frames):
        n += 1
        small = cv2.resize(fr, (max(8, fr.shape[1] // 3), max(8, fr.shape[0] // 3)), interpolation=cv2.INTER_AREA)
        m = bright_mask(small)
        gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        buf.append((f, gray))
        if last_m is not None and since is None and _band_changed(m, last_m):
            since = f
        if last_m is None or (since is not None and f - last_f >= OCR_GAP) or f - last_f >= OCR_HEARTBEAT:
            boxes, blobs = ocr_frame(np.ascontiguousarray(fr))
            for b in boxes:
                b.append(_appear(b, buf, gray) if last_m is not None else f)
            res.append([f, f if since is None else since, boxes, blobs])
            last_m, last_f, since, buf = m, f, None, [(f, gray)]
        elif len(buf) > 2 * FPS:
            buf = buf[:1] + buf[-FPS:]
    return res, n


def scan_clip(path, rec, det, cfg, scale=None):
    """Full 15 fps pass over the killfeed crop. Stores RAW per-frame OCR results (boxes, text, confidence, icon blobs) so any
    later logic or threshold change needs no rescan."""
    t0 = time.time()
    ocr, n = scan_frames(frame_stream(path, rec, det, cfg, FPS))
    e = {"v": CACHE_V, "names": names_for_cache(rec.get("game")), "ocr": ocr, "frames": n, "size": [det.dw, det.dh], "region": det.d["region"],
         "v_off": rec.get("v_off", 0.0), "ocr_calls": len(ocr), "secs": round(time.time() - t0, 1), "game": rec.get("game")}
    a = analyse_entry(e, cfg)
    e["best_name"], e["best_vic"] = round(a["best_k"], 3), round(a["best_v"], 3)
    return e


def _row_match(t, r, prev_f):
    """Similarity (0-100) of a tracked row and a row in the current OCR frame: killer text + victim text + weapon, with a bonus
    when the row's pixels did not change since the previous OCR frame at the same height (OCR noise on short names).
    An unreadable (empty) name only matches a track that is still at the same height; names whose length differs by 2+
    characters are never the same row ('ttwo' / 'tthree'). < 80 = a different row."""
    from rapidfuzz import fuzz
    if t["split"] == r["split"] == "icon" and t["gun"] != r["gun"]:
        return 0.0
    if t["iw"] and r["icon"] and abs(t["iw"] - r["icon"][2]) > 0.3 * max(t["iw"], r["icon"][2]):
        return 0.0
    same_y = abs(t["y"] - r["y"]) <= 0.5 * max(8.0, r["th"])
    ka, kb_ = _alnum(t["k"]), _alnum(r["ktext"].lower())
    va, vb = _alnum(t["v"]), _alnum(r["vtext"].lower())
    if (va and not vb) or (vb and not va) or (ka and not kb_) or (kb_ and not ka):
        if not same_y:
            return 0.0
    if va and vb and abs(len(va) - len(vb)) >= 2 and fuzz.ratio(va, vb) < 90:
        return 0.0
    sk = fuzz.ratio(t["k"], r["ktext"].lower()) if (ka and kb_) else 100.0
    sv = fuzz.ratio(t["v"], r["vtext"].lower()) if (va and vb) else 100.0
    sc = min(sk, sv)
    if t["last"] == prev_f and same_y and r.get("appear_max", 0) <= prev_f:
        sc += 15
    return sc


def _row_match_v4(t, r, prev_f):
    """FROZEN V4 row matcher (only for the V4-vs-V5 detection regression check). Similarity (0-100) of a tracked row and a row in the current OCR frame: killer text + victim text + weapon, with a bonus
    when the row's pixels did not change since the previous OCR frame at the same height (OCR noise on short names).
    < 80 = a different row."""
    from rapidfuzz import fuzz
    if t["split"] == r["split"] == "icon" and t["gun"] != r["gun"]:
        return 0.0
    if t["iw"] and r["icon"] and abs(t["iw"] - r["icon"][2]) > 0.3 * max(t["iw"], r["icon"][2]):
        return 0.0
    sk = fuzz.ratio(t["k"], r["ktext"].lower()) if (t["k"] or r["ktext"]) else 100.0
    sv = fuzz.ratio(t["v"], r["vtext"].lower()) if (t["v"] or r["vtext"]) else 100.0
    sc = min(sk, sv)
    if t["last"] == prev_f and abs(t["y"] - r["y"]) <= 0.5 * max(8.0, r["th"]) and r.get("appear_max", 0) <= prev_f:
        sc += 15
    return sc


def weapon_class(r, game=None):
    """gun / knife / util from the weapon icon. util = small or square icon (grenades, molotov, abilities); knife = thin, sparse
    and low icon (a blade) - Valorant only (V5.42B: CS2's AWP / Scout / rifle icons are long and thin too). Conservative:
    anything unclear stays 'gun'."""
    ic = r.get("icon")
    if not r.get("gun"):
        return "util"
    if (game or r.get("game")) == "cs2":
        return "gun"
    if r.get("split") == "icon" and ic and len(ic) >= 5 and ic[4] < 0.30 and ic[3] <= 0.75 * r.get("th", 20) and ic[2] >= 2.0 * ic[3]:
        return "knife"
    if r.get("split") == "icon" and ic and ic[2] >= 5.0 * ic[3] and ic[3] <= 1.0 * r.get("th", 20):
        return "knife"                                     # V5.42: Valorant blade, long and thin (guns are under 5:1)
    return "gun"


_OCR_CASE = {"I": "l", "|": "l", "1": "l", "O": "o", "0": "o", "D": "o"}          # V6.7 (CS2): OCR swaps l/I/1/| and O/0/D
_OCR_CYR = {"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "к": "k", "т": "t", "н": "h", "м": "m", "в": "b"}   # Cyrillic look-alikes


def ocr_norm(s):
    """V6.7 (CS2): a name after OCR-confusion normalisation: l/I/1/| -> l, O/0/D -> o, Cyrillic look-alikes -> Latin, rn -> m,
    vv -> w, case folded, spaces and punctuation dropped."""
    t = "".join(_OCR_CASE.get(c, c) for c in (s or ""))
    t = "".join(_OCR_CYR.get(c, c) for c in t.lower())
    return _alnum(t.replace("rn", "m").replace("vv", "w"))


def ocr_ratio(a, b):
    """Similarity 0-100 of two names after ocr_norm (inputs may be raw or already normalised). 0 when the difference touches a
    digit (two players called 'player1' / 'player2' are different players) or either name is shorter than 4 letters and not equal."""
    from rapidfuzz import fuzz
    from rapidfuzz.distance import Levenshtein
    a, b = ocr_norm(a), ocr_norm(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0
    if min(len(a), len(b)) < 4:
        return 0.0
    for tag, i1, i2, j1, j2 in Levenshtein.opcodes(a, b):
        if tag != "equal" and any(c.isdigit() for c in a[i1:i2] + b[j1:j2]):
            return 0.0
    return float(fuzz.ratio(a, b))


CS2_SAME_NAME = 82.0            # V6.7: ocr_ratio that joins two reads of one CS2 victim ('Dneelko' / 'Oneelkn' / 'Onee lke' = 86)
CS2_GAP_S = 1.5                # V6.7.2: a CS2 row track survives OCR misses / misreads this long
CS2_ROUND_S = 115.0             # V6.5-era round window (see the 5-kills cap): one victim dies once per round


def _noisy_name(raw):
    """A garbled OCR read: digits, spaces or mixed capitals inside the word ('OO TEKAAB', 'due TaKAan', 'aapa3kAeM')."""
    t = (raw or "").strip()
    inner = t[1:]
    return any(c.isdigit() for c in t) or " " in t or (sum(c.isupper() for c in inner) >= 2 and any(c.islower() for c in t))


_VOWELS = str.maketrans("aeiouy", "aaaaaa")
_CORE_MAP = str.maketrans({"3": "e", "з": "e", "З": "e", "4": "a", "ч": "a", "Ч": "a", "6": "b", "б": "b", "9": "a", "0": "o"})


def cs2_same_victim(a, b):
    """V6.7.2 (CS2): two reads of one victim. Clean reads: ocr_ratio >= CS2_SAME_NAME. Garbled reads (at least one is noisy: digits,
    spaces, mixed capitals): also the same when they share a long common core once vowels and the digit / Cyrillic look-alikes are
    folded together ('takaab' / 'takaan' / 'takaod'). Clean different names ('Kristof' / 'Kristina', 'Nika' / 'Mika') and names that
    differ in a digit ('player1' / 'player2') stay different."""
    if ocr_ratio(a, b) >= CS2_SAME_NAME:
        return True
    if not (_noisy_name(a) or _noisy_name(b)):
        return False
    from rapidfuzz import fuzz
    na, nb = ocr_norm(a), ocr_norm(b)
    if min(len(na), len(nb)) < 6:
        return False
    if len(na) == len(nb) and sum(x != y for x, y in zip(na, nb)) == 1 and any(x != y and (x.isdigit() or y.isdigit()) for x, y in zip(na, nb)):
        return False                                       # 'player1' / 'player2': one different digit = two different players
    fold = lambda t: t.translate(_CORE_MAP).translate(_VOWELS)
    fa, fb = fold(na), fold(nb)
    best = 0
    for i in range(len(fa)):
        for j in range(len(fb)):
            k = 0
            while i + k < len(fa) and j + k < len(fb) and fa[i + k] == fb[j + k]:
                k += 1
            best = max(best, k)
    return best >= 5 and best >= 0.6 * min(len(fa), len(fb)) and fuzz.ratio(fa, fb) >= 60


def _cs2_shift(tracks, cand, f, prev_f):
    """V6.7.2 (CS2): how far the whole killfeed list moved since the last OCR frame (a new row pushes the rows). Text independent:
    for every distance, count the live tracks that have a row exactly that far away; 0 only counts rows that were already on screen
    in the previous frame (a new row at an old height is not 'nothing moved'). A move needs more tracks than 'nothing moved', and
    two or more tracks - or one track whose text still reads alike. Returns dy (0.0 = no shift)."""
    from rapidfuzz import fuzz
    cnt, ds, sim = {}, {}, {}
    live = [t for t in tracks if f - t["last"] <= CS2_GAP_S * FPS]
    for ti, t in enumerate(live):
        for r, _ in cand:
            th = max(8.0, r["th"])
            d = r["y"] - t["y"]
            if abs(d) > 6 * th:
                continue
            if abs(d) <= 0.5 * th:
                if r.get("appear_max", 0) > prev_f:
                    continue
                key = 0
            else:
                key = round(d / (0.5 * th))
            if (key, ti) in sim:
                continue
            sim[(key, ti)] = True
            cnt[key] = cnt.get(key, 0) + 1
            ds.setdefault(key, []).append(d)
            if key and ocr_norm(t["v"]) and ocr_norm(r["vtext"]) and fuzz.ratio(ocr_norm(t["v"]), ocr_norm(r["vtext"])) >= 60:
                ds[key].append(d)
                sim[("txt", key)] = True
    moves = {k: c for k, c in cnt.items() if k}
    if not moves:
        return 0.0
    best = max(moves, key=lambda k: moves[k])
    if moves[best] <= cnt.get(0, 0) or (moves[best] < 2 and not sim.get(("txt", best))):
        return 0.0
    return float(sum(ds[best]) / len(ds[best]))


def _row_match_cs2(t, r, prev_f, f=None, shifted=False):
    """V6.7.2 (CS2 only): a row is TRACKED BY POSITION. t["y"] has been moved along with the list (see _cs2_shift); a row at the
    track's height that was already on screen in the previous OCR frame (appear_max <= prev_f) - or that came along with a shift of the
    whole list - is the same kill however OCR read it, and the track survives OCR misses up to CS2_GAP_S. Otherwise names are compared
    after OCR-confusion normalisation (cs2_same_victim)."""
    from rapidfuzz import fuzz
    if t["split"] == r["split"] == "icon" and t["gun"] != r["gun"]:
        return 0.0
    if t["iw"] and r["icon"] and abs(t["iw"] - r["icon"][2]) > 0.3 * max(t["iw"], r["icon"][2]):
        return 0.0
    th = max(8.0, r["th"])
    near = f is None or f - t["last"] <= CS2_GAP_S * FPS
    same_y = abs(t["y"] - r["y"]) <= 0.5 * th
    va, vb = ocr_norm(t["v"]), ocr_norm(r["vtext"])
    ka, kb_ = ocr_norm(t["k"]), ocr_norm(r["ktext"])
    if ((va and not vb) or (vb and not va) or (ka and not kb_) or (kb_ and not ka)) and not same_y:
        return 0.0
    if near and same_y and (r.get("appear_max", 0) <= prev_f or shifted):
        return 100.0                                       # already there (or moved with the list): the same row
    if va and vb and cs2_same_victim(t["v"], r["vtext"]):
        sv = max(ocr_ratio(va, vb), 85.0)
    else:
        sv = ocr_ratio(va, vb) if (va and vb) else 100.0
    sk = float(fuzz.ratio(ka, kb_)) if (ka and kb_) else 100.0
    return min(sk, sv)


def merge_variants(tracks, game=None):
    """OCR variants of one row ('ap15'/'apT5', 'Ryuk' seen twice) become one track: same killer side, victim names fuzzy >= 80
    or one edit apart, first sightings within 1.5 s - and NEVER seen in the same OCR frame (two rows on screen at the same
    time are two different kills, e.g. 'clean' and 'clean2')."""
    from rapidfuzz import fuzz
    from rapidfuzz.distance import Levenshtein
    tracks = sorted(tracks, key=lambda t: t["first"])
    out_ = []
    for t in tracks:
        hit = None
        for m in out_:
            a, b = _alnum(t["v"]), _alnum(m["v"])
            if (not a) != (not b) and not (t.get("frames", set()) & m.get("frames", set())) and \
                    min(t["first"], m["first"]) + 0 <= max(t["first"], m["first"]) <= min(t["last"], m["last"]) + 4.5 * FPS and \
                    (t["ks"] >= 0.8) == (m["ks"] >= 0.8) and (t["vs"] >= 0.8) == (m["vs"] >= 0.8) and \
                    fuzz.ratio(_alnum(t["k"]), _alnum(m["k"])) >= 70:
                hit = m                                    # the same row: its name was unreadable at first, read later
                break
            if abs(t["first"] - m["first"]) > 1.5 * FPS:
                continue
            same_v = (a == b) or fuzz.ratio(a, b) >= 80 or (min(len(a), len(b)) >= 4 and Levenshtein.distance(a, b) <= 1)
            if game == "cs2" and not same_v:                   # V6.7: OCR look-alike reads of one CS2 victim
                same_v = cs2_same_victim(t["v"], m["v"])
            same_k = fuzz.ratio(_alnum(t["k"]), _alnum(m["k"])) >= 70 or (t["ks"] >= 0.8 and m["ks"] >= 0.8)
            if a and b and same_v and same_k and (t["ks"] >= 0.8) == (m["ks"] >= 0.8) and (t["vs"] >= 0.8) == (m["vs"] >= 0.8) \
                    and not (t.get("frames", set()) & m.get("frames", set())):
                hit = m
                break
        if hit is None:
            out_.append(t)
            continue
        hit["hits"] += t["hits"]
        hit["first"], hit["last"] = min(hit["first"], t["first"]), max(hit["last"], t["last"])
        hit["seen"] = min(hit["seen"], t["seen"])
        hit["votes"] += t["votes"]
        hit["frames"] = hit.get("frames", set()) | t.get("frames", set())
        if not _alnum(hit["v"]) and _alnum(t["v"]):
            hit.update(v=t["v"], vtext=t["vtext"])
        hit["hs"] = hit["hs"] or t["hs"]
        hit["cjk"] = hit.get("cjk", False) and t.get("cjk", False)
        hit["ks"], hit["vs"] = max(hit["ks"], t["ks"]), max(hit["vs"], t["vs"])
    return out_


def resurrect_rows(tracks, dead_others):
    """V5.41 (Valorant): revive / resurrect rows with an ability icon that are not a kill and not a death (same rule as the
    Clove self-revive). Someone revives ME: an ability-icon row with FIREAXE as the victim while I am already dead (my death row
    >= 1.5 s earlier, no revive or kill of mine since) - nobody dies twice. I resurrect a TEAMMATE: FIREAXE + ability icon + a
    victim who already died earlier in the clip - nobody is killed twice. Returns {id(track): reason}."""
    from rapidfuzz import fuzz
    res, dead_me = {}, None
    for t in sorted(tracks, key=lambda t: t["first"]):
        tally = {}
        for v in t["votes"]:
            for a, _ in v:
                if a != "none":
                    tally[a] = tally.get(a, 0) + 1
        top = max(tally, key=tally.get) if tally else None
        if not t["gun"] and top == "death" and dead_me is not None and t["first"] - dead_me >= 1.5 * FPS:
            res[id(t)] = f"revive: '{t['ktext'] or '-'}' revived FIREAXE (ability icon while I was dead) - not a kill, not a death"
            dead_me = None
            continue
        vn = _alnum(t["vtext"]).lower()
        if not t["gun"] and top == "reject" and t["ks"] >= 0.8 and len(vn) >= 3 and \
                any(f0 <= t["first"] - FPS and fuzz.ratio(vn, n) >= 80 for n, f0 in dead_others.items()):
            res[id(t)] = f"revive: FIREAXE resurrected '{t['vtext']}' (ability icon, they died earlier) - not a kill"
            continue
        if top == "death":
            dead_me = t["first"]
        elif top in ("revive", "kill"):
            dead_me = None
    return res


def _killer_leftover(ktext):
    """V5.43: the killer side with MY name taken out - what is 'stuck' to it (another name read into my row)."""
    t = (ktext or "").lower()
    sc, st, nm_ = name_match(t, None, True)
    if sc >= NAME_MIN:
        t = t[:st] + t[st + len(nm_):]
    for c_ in names_split(None)[1]:
        t = t.replace(c_, "")
    return _alnum(t)


def drop_fake_kills(kills, rej, game, pre=(), revives=()):
    """V5.43 (Valorant + CS2): a real kill read again with jumbled text must not count as a new kill. Duplicates:
      - 1-2 sightings and the row text (killer leftover + victim side) contains a victim I killed in the last 4 s;
      - 1-2 sightings, an empty victim side and another name stuck to my name;
      - kills < 0.5 s apart with matching victim text are one kill (the better read stays);
      - V5.5: the same victim killed again within one fight (kills <= 10 s apart, pre-clip rows included) with no revive row
        between = a duplicate, whatever the sightings;
      - CS2: a round has 5 enemies - 6+ kills of mine inside one round's time, the weakest reads (1-2 sightings) go."""
    from rapidfuzz import fuzz
    cs2 = game == "cs2"                                        # V6.7: CS2 compares victims after OCR-confusion normalisation
    vname = (lambda x: ocr_norm(x)) if cs2 else (lambda x: _alnum(x).lower())
    kills.sort(key=lambda k: k["t"])
    keep = []
    pre = [dict(p, hits=9) for p in pre]                       # V5.5: kills whose row was already on screen at 0:00 are known kills too
    for k in kills:
        v = vname(k.get("victim") or "")
        seen = pre + keep
        left = _killer_leftover(k["row"].split("] ")[0][1:] if k.get("row") else "")
        why = None
        fight = []                                             # V5.5: the kills of this fight (each <= 10 s after the one before)
        edge = k["t"]
        for q in reversed(seen):
            if edge - q["t"] > 10.0:
                break
            fight.append(q)
            edge = q["t"]
        for q in fight:                                        # the same victim killed again = a duplicate, unless a revive came between
            qv = vname(q.get("victim") or "")
            if v and qv and len(qv) >= 3 and (cs2_same_victim(k.get("victim"), q.get("victim")) if cs2 else fuzz.ratio(v, qv) >= 85) and k["t"] > q["t"] and \
                    not any(q["t"] < rv < k["t"] for rv in revives):
                why = f"'{k.get('victim')}' was already killed {k['t'] - q['t']:.1f} s earlier in this fight, no revive between ({k['row']})"
                break
        if why is None and cs2:                                # V6.7: within one round the same victim cannot be killed twice
            for q in seen:
                qv = vname(q.get("victim") or "")
                if v and qv and len(qv) >= 4 and 0 < k["t"] - q["t"] <= CS2_ROUND_S and ocr_ratio(v, qv) >= 85:
                    why = f"'{k.get('victim')}' was already killed {k['t'] - q['t']:.1f} s earlier in this CS2 round ({k['row']})"
                    break
        for q in (seen if why is None else ()):
            qv = vname(q.get("victim") or "")
            if k["t"] - q["t"] < 0.5 and v and qv and (ocr_ratio(v, qv) >= 65 if cs2 else fuzz.ratio(v, qv) >= 70):
                why = f"same kill read twice ({q['row']} / {k['row']} {k['t'] - q['t']:.2f} s apart)"
                break
        if why is None and k["hits"] <= 2:
            text = _alnum(left + v).lower()
            for q in seen:
                qv = vname(q.get("victim") or "")
                if 0 < k["t"] - q["t"] <= 4.0 and len(qv) >= 3 and text and \
                        (fuzz.partial_ratio(qv, text) >= 85 or (len(text) >= 4 and fuzz.ratio(qv, text) >= 75)):
                    why = f"jumbled re-read of my kill on '{q.get('victim')}' {k['t'] - q['t']:.1f} s earlier ({k['row']})"
                    break
            if why is None and not v and len(left) >= 3:
                why = f"empty victim side with another name stuck to mine ({k['row']})"
        if why:
            rej.append({"t": k["t"], "reason": f"duplicate kill: {why}", "ks": k["ks"]})
            continue
        keep.append(k)
    if game == "cs2":
        weak = lambda k: (k["hits"], k["ks"])
        while True:
            over = next(([x for x in keep if 0 <= x["t"] - a["t"] <= 115.0] for a in keep
                         if len([x for x in keep if 0 <= x["t"] - a["t"] <= 115.0]) > 5), None)
            if not over:
                break
            cand = [x for x in over if x["hits"] <= 2]
            if not cand:
                break
            d = min(cand, key=weak)
            keep.remove(d)
            rej.append({"t": d["t"], "reason": f"duplicate kill: more than 5 of my kills in one CS2 round ({d['row']})", "ks": d["ks"]})
    kills[:] = keep


def analyse_entry(entry, cfg, game=None):
    """Raw OCR frames -> rows -> verdicts -> content-tracked rows (identity = killer text + victim text + weapon) -> kills /
    deaths / rejected rows with reasons. The ONE implementation behind Dry plan, Render, the sync report, Self-test and the
    killfeed crop view."""
    off = entry.get("v_off", 0.0)
    game = game or entry.get("game")
    bk = bv = 0.0
    tracks, mine, seen_rows, dead_others = [], [], 0, {}
    last_ocr = entry["ocr"][-1][0] if entry.get("ocr") else 0
    prev_f = -1
    for f, since, boxes, blobs in entry.get("ocr", []):
        rs = ocr_rows(boxes, blobs, game)
        seen_rows = max(seen_rows, len(rs))
        thr = float((cfg or {}).get("name_match", NAME_MIN))
        cand = []
        for r in rs:
            bk, bv = max(bk, r["ks"] / 100), max(bv, r["vs"] / 100)
            v = classify_row(r, cfg)
            if all(x[0] == "none" for x in v) and max(r["ks"], r["vs"]) < thr:
                if r.get("split") and len(_alnum(r["vtext"])) >= 3:      # someone else died: a later resurrect of them is no kill
                    dead_others.setdefault(_alnum(r["vtext"]).lower(), f)
                continue
            cand.append((r, v))
        if game == "cs2":                                      # V6.7: CS2 only - normalised names, position as identity, list shifts
            dy = _cs2_shift(tracks, cand, f, prev_f)
            if dy:
                for t in tracks:                               # the list moved: every live track moves with it
                    if f - t["last"] <= CS2_GAP_S * FPS:
                        t["y"] += dy
            pairs = sorted(((_row_match_cs2(t, r, prev_f, f, bool(dy)), i, j) for i, (r, v) in enumerate(cand) for j, t in enumerate(tracks)
                            if f - t["last"] <= TRACK_KEEP_S * FPS), reverse=True)
        else:
            pairs = sorted(((_row_match(t, r, prev_f), i, j) for i, (r, v) in enumerate(cand) for j, t in enumerate(tracks)
                            if f - t["last"] <= TRACK_KEEP_S * FPS), reverse=True)
        used_r, used_t, got = set(), set(), {}
        for sc, i, j in pairs:                                 # one-to-one: two rows in one frame are never the same row
            if sc >= 80 and i not in used_r and j not in used_t:
                used_r.add(i)
                used_t.add(j)
                got[i] = tracks[j]
        for i, (r, v) in enumerate(cand):
            hit = got.get(i)
            if hit:
                hit.update(last=f, y=r["y"], hits=hit["hits"] + 1, hs=hit["hs"] or (r["hs"] and f - hit["first"] <= 20))
                hit["cjk"] = hit.get("cjk", False) and bool(r.get("cjk"))         # recovered only if no frame read 'fireaxe'
                hit["votes"].append(v)
                hit["frames"].add(f)
            else:
                first = max(prev_f + 1, min(int(r["appear"]), f)) if prev_f >= 0 else f
                tracks.append({"first": first, "seen": f, "last": f, "y": r["y"], "hits": 1, "k": r["ktext"].lower(), "v": r["vtext"].lower(),
                               "gun": r["gun"], "split": r["split"], "iw": r["icon"][2] if r["icon"] else 0, "hs": r["hs"],
                               "ks": r["ks"] / 100, "vs": r["vs"] / 100, "votes": [v], "ktext": r["ktext"], "vtext": r["vtext"], "frames": {f},
                               "cjk": bool(r.get("cjk")), "weapon": weapon_class(r, game), "box": [min(b[0] for b in r["boxes"]), min(b[1] for b in r["boxes"]),
                                                                  max(b[2] for b in r["boxes"]), max(b[3] for b in r["boxes"])]})
        prev_f = f
    tracks = merge_variants(tracks, game)
    res_why = resurrect_rows(tracks, dead_others) if game != "cs2" else {}      # V5.42B: Valorant only
    kills, deaths, revives, rej, vis, cjk, pre = [], [], [], [], [], {}, []
    for t in tracks:
        tt = round(t["first"] / FPS + off, 3)
        tally = {}
        for v in t["votes"]:
            for a, why in v:
                if a != "none":
                    tally.setdefault(a, [0, why])[0] += 1
        if id(t) in res_why:                                   # V5.41: any revive / resurrect row (Sage, Clove) is never a kill
            tally = {"revive": [len(t["votes"]), res_why[id(t)]]}
        if not tally:
            continue
        verdicts = [a for a in ("kill", "reject", "death") if a in tally]
        if "kill" in tally and "reject" in tally:              # OCR noise: majority wins between kill and reject
            verdicts.remove("reject" if tally["kill"][0] >= tally["reject"][0] else "kill")
        if "revive" in tally:                                  # a self-revive row misread now and then stays a revive
            verdicts = [a for a in verdicts if tally[a][0] > tally["revive"][0]] or ["revive"]
        row = f"[{t['ktext'] or '-'}] {'gun' if t['gun'] else 'util'} [{t['vtext'] or '-'}]"
        if t.get("cjk"):
            cjk[verdicts[0]] = cjk.get(verdicts[0], 0) + 1
            row += f" (my name by '{MY_NAME_CS2}')"
        for a in verdicts:
            why = tally[a][1]
            mine.append({"t": tt, "row": row, "verdict": a, "why": why, "hits": t["hits"]})
            need_shot = False
            if t["hits"] < 2:
                if a == "kill":
                    need_shot = t["ks"] < 0.9                  # 1 sighting, name < 90: a gunshot must confirm it
                elif t["seen"] < last_ocr - FPS:
                    rej.append({"t": tt, "reason": f"one-frame blip ({row})", "ks": t["ks"]})
                    continue
            if t["first"] <= 2:
                rej.append({"t": tt, "reason": f"pre-clip: row already on screen when the clip starts ({row})", "ks": max(t["ks"], t["vs"])})
                if a == "kill":
                    pre.append({"t": tt, "ks": t["ks"], "row": row, "victim": t["vtext"]})
            elif a == "kill":
                vis.append((tt, round(t["last"] / FPS + off + 0.3, 3)))
                kills.append({"t": tt, "ks": t["ks"], "hs": bool(t["hs"]), "row": row, "hits": t["hits"], "victim": t["vtext"],
                              "weapon": t.get("weapon", "gun"), "box": t.get("box"), "t_last": round(t["last"] / FPS + off, 3),
                              "needs_shot": need_shot, **({"cjk": True} if t.get("cjk") else {})})
            elif a == "death":
                deaths.append(tt)
                rej.append({"t": tt, "reason": f"{why} - not a kill", "ks": t["vs"]})
            elif a == "revive":
                revives.append(tt)
                rej.append({"t": tt, "reason": why, "ks": t["ks"]})
            else:
                vis.append((tt, round(t["last"] / FPS + off + 0.3, 3)))
                rej.append({"t": tt, "reason": why, "ks": t["ks"]})
    drop_fake_kills(kills, rej, game, pre, revives)            # V5.43 / V5.5
    return {"kills": kills, "deaths": sorted(deaths), "revives": sorted(revives), "rej": sorted(rej, key=lambda r: r["t"]),
            "vis": vis, "best_k": bk, "best_v": bv, "mine": sorted(mine, key=lambda m: m["t"]), "rows_n": len(tracks),
            "rows_max": seen_rows, "ocr_calls": len(entry.get("ocr", [])), "cjk": cjk}


def _analyse_entry_v4(entry, cfg):
    """FROZEN V4 logic (only used by the before/after detection regression check). Raw OCR frames -> rows -> verdicts -> content-tracked rows (identity = killer text + victim text + weapon) -> kills /
    deaths / rejected rows with reasons. The ONE implementation behind Dry plan, Render, the sync report, Self-test and the
    killfeed crop view."""
    off = entry.get("v_off", 0.0)
    bk = bv = 0.0
    tracks, mine, seen_rows, dead_others = [], [], 0, {}
    last_ocr = entry["ocr"][-1][0] if entry.get("ocr") else 0
    prev_f = -1
    for f, since, boxes, blobs in entry.get("ocr", []):
        rs = ocr_rows(boxes, blobs)
        seen_rows = max(seen_rows, len(rs))
        thr = float((cfg or {}).get("name_match", NAME_MIN))
        cand = []
        for r in rs:
            bk, bv = max(bk, r["ks"] / 100), max(bv, r["vs"] / 100)
            v = classify_row(r, cfg)
            if all(x[0] == "none" for x in v) and max(r["ks"], r["vs"]) < thr:
                if r.get("split") and len(_alnum(r["vtext"])) >= 3:      # someone else died: a later resurrect of them is no kill
                    dead_others.setdefault(_alnum(r["vtext"]).lower(), f)
                continue
            cand.append((r, v))
        pairs = sorted(((_row_match_v4(t, r, prev_f), i, j) for i, (r, v) in enumerate(cand) for j, t in enumerate(tracks)
                        if f - t["last"] <= TRACK_KEEP_S * FPS), reverse=True)
        used_r, used_t, got = set(), set(), {}
        for sc, i, j in pairs:                                 # one-to-one: two rows in one frame are never the same row
            if sc >= 80 and i not in used_r and j not in used_t:
                used_r.add(i)
                used_t.add(j)
                got[i] = tracks[j]
        for i, (r, v) in enumerate(cand):
            hit = got.get(i)
            if hit:
                hit.update(last=f, y=r["y"], hits=hit["hits"] + 1, hs=hit["hs"] or (r["hs"] and f - hit["first"] <= 20))
                hit["votes"].append(v)
            else:
                first = max(prev_f + 1, min(int(r["appear"]), f)) if prev_f >= 0 else f
                tracks.append({"first": first, "seen": f, "last": f, "y": r["y"], "hits": 1, "k": r["ktext"].lower(), "v": r["vtext"].lower(),
                               "gun": r["gun"], "split": r["split"], "iw": r["icon"][2] if r["icon"] else 0, "hs": r["hs"],
                               "ks": r["ks"] / 100, "vs": r["vs"] / 100, "votes": [v], "ktext": r["ktext"], "vtext": r["vtext"]})
        prev_f = f
    kills, deaths, rej, vis = [], [], [], []
    for t in tracks:
        tt = round(t["first"] / FPS + off, 3)
        tally = {}
        for v in t["votes"]:
            for a, why in v:
                if a != "none":
                    tally.setdefault(a, [0, why])[0] += 1
        if not tally:
            continue
        verdicts = [a for a in ("kill", "reject", "death") if a in tally]
        if "kill" in tally and "reject" in tally:              # OCR noise: majority wins between kill and reject
            verdicts.remove("reject" if tally["kill"][0] >= tally["reject"][0] else "kill")
        row = f"[{t['ktext'] or '-'}] {'gun' if t['gun'] else 'util'} [{t['vtext'] or '-'}]"
        for a in verdicts:
            why = tally[a][1]
            mine.append({"t": tt, "row": row, "verdict": a, "why": why, "hits": t["hits"]})
            if t["hits"] < 2 and t["seen"] < last_ocr - FPS:
                rej.append({"t": tt, "reason": f"one-frame blip ({row})", "ks": t["ks"]})
            elif t["first"] <= 2:
                rej.append({"t": tt, "reason": f"pre-clip: row already on screen when the clip starts ({row})", "ks": max(t["ks"], t["vs"])})
            elif a == "kill":
                vis.append((tt, round(t["last"] / FPS + off + 0.3, 3)))
                kills.append({"t": tt, "ks": t["ks"], "hs": bool(t["hs"]), "row": row, "hits": t["hits"]})
            elif a == "death":
                deaths.append(tt)
                rej.append({"t": tt, "reason": f"{why} - not a kill", "ks": t["vs"]})
            else:
                vis.append((tt, round(t["last"] / FPS + off + 0.3, 3)))
                rej.append({"t": tt, "reason": why, "ks": t["ks"]})
    kills.sort(key=lambda k: k["t"])
    return {"kills": kills, "deaths": sorted(deaths), "rej": sorted(rej, key=lambda r: r["t"]), "vis": vis, "best_k": bk, "best_v": bv,
            "mine": sorted(mine, key=lambda m: m["t"]), "rows_n": len(tracks), "rows_max": seen_rows,
            "ocr_calls": len(entry.get("ocr", []))}


def compute_kills(entry, cfg, game=None):
    a = analyse_entry(entry, cfg, game)
    return a["kills"], a["deaths"]


# ======================================================================= CS2 RED-BORDER ROW TRACKER (V6.8.1)
# In CS2 every killfeed row that involves the local player has a red outline; other rows have none. Detection through the NAME alone
# (OCR: fireaxo, flreaxe, 火茶 ...) misses kills and invents new ones from re-reads. This tracker finds the outlined rows by COLOUR (no
# OCR), tracks each one as ONE event, and only then reads its text (a few clear frames per row) to say kill / assist / death / utility.
# Everything here runs only for game == "cs2". Results live in a SEPARATE sidecar cache (montage_data\cs2_rows_v1\), so the existing kill
# cache entries and keys stay valid. Without a sidecar the V6.7.2 name-based list is used unchanged.
BORDER_DIR = DATA / "cs2_rows_v1"
BORDER_V = 1                     # bump when the tracker / sidecar format changes (old sidecars are then rebuilt lazily)
BORDER_FPS = 30                  # decode rate of the killfeed region for the tracker (every 2nd frame of a 60 fps clip)
BORDER_GAP_S = 1.0               # a row track survives this long without a detected border (compression flicker, fade)
BORDER_VOTES = 3                 # clear frames per row that are read with OCR
BORDER_LINE_MIN = 60             # px (1920-wide normalised space): shortest horizontal red line that can be part of an outline
BORDER_H = (16, 90)              # px: outer height of an outlined row (1920x1080 space; the clip is stretched into it)
BORDER_PRE_F = 3                 # a track already there in the first frames = on screen when the clip starts (pre-clip)
BORDER_FAILED = set()            # clips whose sidecar could not be built in this process (not retried every time)


def border_dm(fr):
    """(mask, d): d = R - max(G, B) (uint8, saturating) and the red-outline mask. V6.8.2, calibrated on the real killfeed screenshots (the
    outline is a thin BRIGHT red line, about BGR (14-52, 30-54, 173-190)): R >= 80, R - max(G, B) >= 40 and R >= 2.0 x max(G, B). The 2.0
    ratio keeps orange / brown map backgrounds (R about 1.6-1.9 x G) and yellow / orange team names out; a faded or 4:2:0-smeared 1 px line
    still passes. Colour never identifies the player (team colours differ per clip) - only the red outline is used here."""
    import cv2
    b, g, r = cv2.split(fr)
    mx = cv2.max(g, b)
    d = cv2.subtract(r, mx)
    return (r >= 80) & (d >= 40) & (cv2.addWeighted(r, 1.0, mx, -2.0, 0) > 0), d


def border_mask(fr):
    return border_dm(fr)[0]


def border_rects(fr):
    """Outlined rows in one killfeed frame: [{x0, y0, x1, y1}]. Horizontal red lines (gaps of compression bridged) are paired top /
    bottom (same left / right end, outer height BORDER_H) and each pair must have red on its left and right side."""
    import cv2
    import numpy as np
    mb, dd = border_dm(fr)
    m = mb.astype(np.uint8)
    if int(m.sum()) < 2 * BORDER_LINE_MIN:
        return []
    mh = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((1, 7), np.uint8))
    hl = cv2.morphologyEx(mh, cv2.MORPH_OPEN, np.ones((1, BORDER_LINE_MIN), np.uint8))
    if not hl.any():
        return []
    n, _, st, _ = cv2.connectedComponentsWithStats(hl, connectivity=8)
    lines = sorted((int(st[i][1]), int(st[i][1] + st[i][3] - 1), int(st[i][0]), int(st[i][0] + st[i][2] - 1))
                   for i in range(1, n) if st[i][2] >= BORDER_LINE_MIN and st[i][3] <= 14)          # (y_top, y_bot, x0, x1)
    thin = sorted(l[1] - l[0] + 1 for l in lines if l[1] - l[0] + 1 <= 5)
    lt = thin[len(thin) // 2] if thin else 3                       # typical thickness of one outline line
    rects = []
    for i, (ya, yb, xa0, xa1) in enumerate(lines):
        a_thick = yb - ya + 1 > 5                                  # two touching rows (bottom line + top line) blurred into one thick line
        y0 = yb - (lt - 1) if a_thick else ya                      # such a line is the TOP of the row below it ...
        for yc, yd, xb0, xb1 in lines[i + 1:]:
            b_thick = yd - yc + 1 > 5
            y1 = yc + (lt - 1) if b_thick else yd                  # ... and the BOTTOM of the row above it
            if y1 - y0 < BORDER_H[0] or yc - yb < 3:
                continue
            if y1 - y0 > BORDER_H[1]:
                break
            if abs(xa1 - xb1) > 12:
                continue
            if a_thick or b_thick:                                 # a merged line is as wide as the wider of its two rows: the clean line decides x0
                x0 = xb0 if a_thick and not b_thick else xa0 if b_thick and not a_thick else max(xa0, xb0)
                if a_thick != b_thick and (xa0 if a_thick else xb0) > x0 + 12:
                    continue                                       # the merged line must reach at least as far left as the clean one
            elif abs(xa0 - xb0) > 12 and min(xa1 - xa0, xb1 - xb0) < 0.5 * max(xa1 - xa0, xb1 - xb0):
                continue                                           # (a weak line may be shorter, but not less than half as long)
            else:
                x0 = min(xa0, xb0)
            x1 = max(xa1, xb1)
            side = m[y0:y1 + 1, :]
            fl = float(side[:, max(0, x0 - 3):x0 + 9].any(axis=1).mean())
            fr_ = float(side[:, max(0, x1 - 9):x1 + 3].any(axis=1).mean())
            if max(fl, fr_) >= 0.5 and min(fl, fr_) >= 0.25:
                band = np.concatenate([dd[y0:y0 + lt, x0:x1 + 1].ravel(), dd[max(y0, y1 - lt + 1):y1 + 1, x0:x1 + 1].ravel()])
                band = band[band >= 40]
                rects.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "str": float(band.mean()) if band.size else 0.0})
            break                                                  # the nearest matching line below closes this row
    out_ = []
    for r in sorted(rects, key=lambda r: r["y1"] - r["y0"]):       # smallest first: of two rects with one bottom edge only the row itself stays
        if any(abs(r["y1"] - o["y1"]) <= 4 and abs(r["x1"] - o["x1"]) <= 12 and o["y0"] > r["y0"] + 8 for o in out_):
            continue
        twin = next((o for o in out_ if abs(r["y0"] - o["y0"]) <= 8 and abs(r["y1"] - o["y1"]) <= 8 and abs(r["x1"] - o["x1"]) <= 12), None)
        if twin is None:
            out_.append(r)
        elif r["x0"] < twin["x0"] - 4:                             # the same outline found twice: the wider one has the full top line
            out_[out_.index(twin)] = r
    return sorted(out_, key=lambda r: r["y0"])


def _border_inner(fr, rc, ins=3):
    return fr[rc["y0"] + ins:rc["y1"] - ins + 1, rc["x0"] + ins:rc["x1"] - ins + 1]


def border_desc(fr, rc):
    """Text-independent appearance of a row: the stroke energy of its text / icons along x (high-pass grey, collapsed vertically, 160 bins,
    zero mean, unit norm). Collapsing makes it insensitive to a few pixels of vertical misalignment and to fade (contrast) and compression;
    a different row of the same width reads clearly lower (about 0.3-0.8) than the same row again (0.85-1.0). None = empty / too small."""
    import cv2
    import numpy as np
    inner = _border_inner(fr, rc, 5)
    if inner.shape[0] < 4 or inner.shape[1] < 8:
        return None
    g = cv2.cvtColor(inner, cv2.COLOR_BGR2GRAY).astype(np.float32)
    prof = np.abs(g - cv2.GaussianBlur(g, (0, 0), 1.5)).mean(axis=0)
    d = cv2.resize(prof.reshape(1, -1), (160, 1), interpolation=cv2.INTER_AREA).ravel()
    d = d - d.mean()
    nrm = float(np.linalg.norm(d))
    return (d / nrm).astype(np.float32) if nrm > 1e-3 else None


def border_quality(fr, rc):
    """How clear a row is for OCR: white text / icon pixels inside the outline."""
    inner = _border_inner(fr, rc)
    return int(bright_mask(inner).sum()) if inner.size else 0


class BorderTracker:
    """Tracks outlined rows over the frames of one clip. A row is identified by its outline width, its appearance (text independent)
    and its position; when the list shifts (a new row pushes the others down) the shift is measured from the rows that agree on it. A
    track survives BORDER_GAP_S without a detected outline; after that the same row appearing again is a NEW track (= a new kill)."""

    def __init__(self, fps=BORDER_FPS, keep_crops=True):
        self.fps, self.tracks, self.n, self.keep = fps, [], 0, keep_crops
        self.gap = int(round(BORDER_GAP_S * fps))
        self.pairs_dy = []
        self.blob_n = 0

    def feed(self, f, fr):
        import numpy as np
        self.n = f + 1
        rects = border_rects(fr)
        live = [t for t in self.tracks if f - t["last"] <= self.gap]
        descs = [border_desc(fr, rc) if live else None for rc in rects]
        pairs = []
        for t in live:
            for i, rc in enumerate(rects):
                w = rc["x1"] - rc["x0"]
                if abs(w - t["w"]) > 6:
                    continue
                c = 0.5 if (t["desc"] is None or descs[i] is None) else float(np.dot(t["desc"], descs[i]))
                pairs.append((c, rc["y0"] - t["y0"], t, i))
        vote = {}
        for c, dy, t, i in pairs:                                  # the shift of the whole list: the distance most rows agree on
            if c >= 0.8:
                vote.setdefault(round(dy / 4.0), []).append(dy)
        shift = 0.0
        if vote:
            k = max(vote, key=lambda k: (len(vote[k]), -abs(k)))
            shift = float(sum(vote[k]) / len(vote[k]))
        sc = []
        for c, dy, t, i in pairs:
            pos_ok = abs(dy - shift) <= max(6.0, 0.35 * (t["y1"] - t["y0"]))
            if c >= 0.8 or (pos_ok and c >= 0.35):
                sc.append((c + (0.5 if pos_ok else 0.0) - 0.002 * abs(dy - shift), id(t), i, t))
        sc.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        used_t, used_r, got = set(), set(), {}
        for s_, _tid, i, t in sc:
            if id(t) in used_t or i in used_r:
                continue
            used_t.add(id(t))
            used_r.add(i)
            got[i] = t
        for i, rc in enumerate(rects):
            t = got.get(i)
            d = descs[i] if live else border_desc(fr, rc)
            if t is None:
                t = {"id": len(self.tracks), "first": f, "last": f, "hits": 0, "y0": rc["y0"], "y1": rc["y1"], "x0": rc["x0"], "x1": rc["x1"],
                     "w": rc["x1"] - rc["x0"], "desc": d, "slots": [[f, rc["y0"]]], "crops": {}, "s0": rc.get("str", 0.0), "smax": rc.get("str", 0.0)}
                self.tracks.append(t)
            else:
                if abs(rc["y0"] - t["y0"]) >= 2:
                    t["slots"].append([f, rc["y0"]])
                t.update(y0=rc["y0"], y1=rc["y1"], x0=rc["x0"], x1=rc["x1"], w=rc["x1"] - rc["x0"], desc=d if d is not None else t["desc"])
            t["last"] = f
            t["hits"] += 1
            t["smax"] = max(t.get("smax", 0.0), rc.get("str", 0.0))
            if self.keep:
                q = border_quality(fr, rc)
                b = f // 4
                if b not in t["crops"] or q > t["crops"][b][0]:
                    t["crops"][b] = (q, f, _border_inner(fr, rc, 0).copy(), dict(rc))
                    if len(t["crops"]) > 10:
                        t["crops"].pop(min(t["crops"], key=lambda k: t["crops"][k][0]))

    def finish(self):
        """Tracks seen at least BORDER_MIN_HITS frames (or still on screen at the very end), each with its clearest crops."""
        raw = [t for t in self.tracks if not (t["hits"] < 2 and t["last"] < self.n - 2)]
        res, blobs = border_shape_filter(raw, self.n)
        self.blob_n = len(blobs) + len(self.tracks) - len(raw)
        for t in res:
            t["op0"] = round(min(1.0, t["s0"] / t["smax"]), 3) if t.get("smax") else None      # outline strength at the first frame / its best (fade-in)
            ranked = sorted(t["crops"].items(), key=lambda kv: -kv[1][0])
            late = [kv for kv in ranked if kv[1][1] >= t["first"] + 2] or ranked      # skip the slide-in frames when there are later ones
            pick = []
            for b, cr in late:                                     # clearest first, spread over time
                if all(abs(b - pb) >= 2 for pb, _ in pick):
                    pick.append((b, cr))
            for b, cr in late:
                if len(pick) >= BORDER_VOTES:
                    break
                if all(b != pb for pb, _ in pick):
                    pick.append((b, cr))
            t["picked"] = [cr for _, cr in pick[:BORDER_VOTES]]
        ys = sorted({s[1] for t in res for s in t["slots"]})
        hs = sorted(t["y1"] - t["y0"] for t in res)
        pitch = (hs[len(hs) // 2] + 2) if hs else 36
        diffs = [b - a for a, b in zip(ys, ys[1:]) if b - a >= 0.6 * pitch]
        if diffs:
            pitch = min(diffs)
        top = ys[0] if ys else 0
        for t in res:
            t["slots"] = [[f, y, int(round((y - top) / float(max(8, pitch))))] for f, y in t["slots"]]
        return res


def border_ocr(crop):
    """OCR one row crop (outline cut off, upscaled when small, padded) -> (boxes, blobs) of ocr_frame()."""
    import cv2
    import numpy as np
    img = crop
    if img.shape[0] < 60:
        k = 2 if img.shape[0] >= 24 else 3
        img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
    img = cv2.copyMakeBorder(img, 14, 14, 20, 20, cv2.BORDER_REPLICATE)
    boxes, blobs = ocr_frame(np.ascontiguousarray(img))
    return [[int(b[0]), int(b[1]), int(b[2]), int(b[3]), str(b[4]), float(b[5])] + [x for x in b[6:] if isinstance(x, str)] for b in boxes], \
        [[int(v) if i < 4 else float(v) for i, v in enumerate(g)] for g in blobs]


def border_path(rec, det):
    key = f"{file_key(rec['path'])}|cs2|{det.d['stamp']}|" + (hashlib.md5(rec.get("bar_sig", "").encode()).hexdigest()[:6] if rec.get("bars") else "nb")
    stem = re.sub(r"[^\w.-]+", "_", Path(rec["path"]).stem)[:48]
    return BORDER_DIR / f"{stem}_{hashlib.md5(key.encode()).hexdigest()[:12]}.json", key


def border_load(rec, det=None):
    """The sidecar of a clip (valid: same tracker version, file, killfeed region and bar crop) or None."""
    try:
        det = det or Detector("cs2")
        p, key = border_path(rec, det)
        j = json.loads(p.read_text(encoding="utf-8"))
        return j if j.get("v") == BORDER_V and j.get("key") == key else None
    except Exception:
        return None


def border_build(rec, det, cfg, write=True, keep_images=False):
    """Decode the killfeed region of one CS2 clip at BORDER_FPS, track the outlined rows, read each row's clearest frames with OCR, and
    write the sidecar. Returns the sidecar dict (with "secs", "decode_secs", "ocr_secs", "ms_per_frame" = the cost)."""
    t0 = time.time()
    tr = BorderTracker(BORDER_FPS, keep_crops=True)
    for f, fr in enumerate(frame_stream(rec["path"], rec, det, cfg, BORDER_FPS)):
        tr.feed(f, fr)
    if CANCEL.is_set():
        raise RuntimeError("cancelled")
    if tr.n == 0:
        raise RuntimeError("no frames decoded")
    t1 = time.time()
    tracks = tr.finish()
    if tracks:
        ocr_engine()
    out_tracks, images = [], {}
    for t in tracks:
        votes = []
        for q, f, crop, rc in t["picked"]:
            boxes, blobs = border_ocr(crop)
            votes.append({"f": f, "q": q, "boxes": boxes, "blobs": blobs})
            if len(votes) >= 2:                                    # two clear reads that name me and agree are enough
                vs_ = [cs2_vote_verdict(r, cfg) if r else ("empty", 0, "") for _, r in cs2_track_rows({"votes": votes[-2:]})]
                if vs_[0][0] == vs_[1][0] and vs_[0][1] >= 3 and vs_[0][0] in ("kill", "assist", "utility"):
                    break
        best = t["picked"][0] if t["picked"] else None
        out_tracks.append({"id": t["id"], "first": t["first"], "last": t["last"], "hits": t["hits"], "x0": t["x0"], "x1": t["x1"],
                           "y0": t["y0"], "y1": t["y1"], "slots": t["slots"], "votes": votes, "op0": t.get("op0"),
                           "best_f": best[1] if best else None, "best_rect": best[3] if best else None})
        if keep_images and best:
            images[t["id"]] = best[2]
    t2 = time.time()
    p, key = border_path(rec, det)
    sc = {"v": BORDER_V, "ext": 2, "blobs": tr.blob_n, "key": key, "stamp": det.d["stamp"], "fps": BORDER_FPS, "frames": tr.n, "size": [det.dw, det.dh],
          "v_off": rec.get("v_off", 0.0), "built": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "tracks": out_tracks,
          "secs": round(t2 - t0, 2), "decode_secs": round(t1 - t0, 2), "ocr_secs": round(t2 - t1, 2),
          "ms_per_frame": round(1000 * (t1 - t0) / max(1, tr.n), 2)}
    if write:
        BORDER_DIR.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(sc, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
    if keep_images:
        sc["_images"] = images
    return sc


def border_build_many(recs, cfg, det, label="CS2 row borders", force=False):
    """Build the missing sidecars of `recs` (a few clips in parallel). Returns {path: sidecar or None}."""
    todo = [r for r in recs if force or (border_load(r, det) is None and r["path"] not in BORDER_FAILED)]
    res = {}
    if not todo:
        return res
    out(f"{label}: building {len(todo)} sidecar(s) in montage_data\\cs2_rows_v1 (the killfeed region is decoded at {BORDER_FPS} fps and "
        "the outlined rows are tracked, once per clip) ...")

    def work(r):
        try:
            return r, border_build(r, det, cfg), None
        except Exception as ex:
            return r, None, f"{type(ex).__name__}: {ex}"
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, int(cfg.get("scan_workers", 2)))) as ex:
        for r, sc, err in ex.map(work, todo):
            done += 1
            progress(done / len(todo), f"{label} {done}/{len(todo)}")
            if err:
                BORDER_FAILED.add(r["path"])
                out(f"[{done}/{len(todo)}] {label}: {Path(r['path']).name} FAILED ({err}); the name-based kills are used for it")
            else:
                res[r["path"]] = sc
                out(f"[{done}/{len(todo)}] {Path(r['path']).name}: {len(sc['tracks'])} outlined rows, {sc['frames']} frames in {sc['secs']}s "
                    f"(decode+track {sc['decode_secs']}s = {sc['ms_per_frame']} ms/frame, OCR {sc['ocr_secs']}s)")
    return res


# ---- classification of one track (names / OCR confusion normalisation) -------------------------------------------------------
def cs2_norm_match(text):
    """(score 0-100, start index in the OCR-normalised text) of my Latin name in `text` after the CS2 OCR-confusion normalisation
    (l/I/1/|, O/0/D, Cyrillic look-alikes, rn -> m ...), so 'flreaxe' / 'f1reaxe' / 'fireaxo' still match 'fireaxe'."""
    from rapidfuzz import fuzz
    t = ocr_norm(text)
    best = (0.0, 0)
    for nm_ in names_split("cs2")[0] or [MY_NAME]:
        n2 = ocr_norm(nm_)
        if len(n2) < 4 or len(t) < 3:
            continue
        if len(t) <= len(n2):
            s = float(fuzz.ratio(t, n2)) if len(t) >= 5 else (100.0 if t == n2 else 0.0)
            st = 0
        else:
            al = fuzz.partial_ratio_alignment(n2, t)
            s, st = float(al.score), int(al.dest_start)
        if s > best[0]:
            best = (s, st)
    return best


def _cs2_prefix(text, st):
    """The raw text in front of normalised position `st` ('mate +' in 'mate + fireaxe'); '' when it is no other name / no '+'."""
    i = next((i for i in range(len(text) + 1) if len(ocr_norm(text[:i])) >= st), len(text))
    pre = text[:i]
    return pre.strip() if ("+" in pre or len(_alnum(pre)) >= 3) else ""


def cs2_lenient_me(text):
    """True when `text` looks a LITTLE like my name (OCR-normalised partial match >= 62, or one of the CJK name characters)."""
    from rapidfuzz import fuzz
    if any(c in (text or "") for n in names_split("cs2")[1] for c in n):
        return True
    t = ocr_norm(text)
    return len(t) >= 3 and any(len(ocr_norm(n)) >= 4 and fuzz.partial_ratio(ocr_norm(n), t) >= 62 for n in names_split("cs2")[0])


def cs2_vote_verdict(r, cfg=None):
    """One OCR read of a bordered row -> (verdict, weight, why). Verdicts: kill, assist, death, utility, none, nosplit, kill?
    (kill, name unreadable). weight 3 = my name was found, 1 = decided without a readable name."""
    thr = float((cfg or {}).get("name_match", NAME_MIN))
    kt, vt = r.get("ktext", ""), r.get("vtext", "")
    if r.get("split") is None:
        return "nosplit", 0, "no weapon icon / gap to split the row"
    ks, vs, before = float(r.get("ks", 0)), float(r.get("vs", 0)), r.get("before", "")
    k_how = v_how = "name"
    if ks < thr:
        s, st = cs2_norm_match(kt)
        if s >= thr:
            ks, before, k_how = s, _cs2_prefix(kt, st), "OCR-normalised name"
    if vs < thr:
        s, _ = cs2_norm_match(vt)
        if s >= thr:
            vs, v_how = s, "OCR-normalised name"
    cj = "".join(names_split("cs2")[1])
    if ks < thr and cj and any(c in kt for c in cj):               # 火茶 / 火年: part of my CJK name is there
        i = min(kt.find(c) for c in cj if c in kt)
        j = kt.rfind("+", 0, i)
        ks, before, k_how = 100.0, (kt[:j + 1].strip() if j >= 0 else ""), "partial CJK name"
    if vs < thr and cj and any(c in vt for c in cj):
        vs, v_how = 100.0, "partial CJK name"
    me_k, me_v, gun = ks >= thr, vs >= thr, bool(r.get("gun"))
    if me_k and me_v:
        return "none", 3, f"my name on both sides ('{kt}' / '{vt}')"
    if me_v:
        return "death", 3, f"my name on the victim side ('{vt}', {v_how} {vs:.0f})"
    if me_k:
        if not gun:
            return "utility", 3, f"utility: small / square icon ('{kt}')"
        if before:
            return "assist", 3, f"assist: '{before}' comes before my name ('{kt}')"
        return "kill", 3, f"kill: my name first on the killer side ('{kt}', {k_how} {ks:.0f})"
    if not gun or not (r.get("killer") or r.get("victim")):
        return "none", 0, "no readable name and no weapon icon"
    if vt and cs2_lenient_me(vt):
        return "death", 1, f"death (name unreadable: '{vt}' looks like my name)"
    if "+" in kt:
        a, b = kt.split("+", 1)
        if cs2_lenient_me(b) and not cs2_lenient_me(a):
            return "assist", 1, f"assist (name unreadable: '{b.strip()}' after '+' looks like my name)"
    return "kill?", 1, f"kill (name unreadable, border confirmed; '{kt or '-'}' -> '{vt or '-'}')"


def cs2_track_rows(track):
    """The best OCR row of each stored vote of a track: [(vote dict, row dict | None)]."""
    res = []
    for v in track.get("votes", []):
        try:
            rows = ocr_rows(v["boxes"], v["blobs"], "cs2")
        except Exception:
            rows = []
        rows = [r for r in rows if r.get("killer") or r.get("victim")] or rows
        res.append((v, max(rows, key=lambda r: (r.get("split") is not None, sum(b[2] - b[0] for b in r["boxes"]))) if rows else None))
    return res


BORDER_ASPECT = 4.0              # V6.8.2: an outlined row is at least this many times wider than high (real rows: 5-12)
BORDER_REF_HITS = 20             # frames a track needs to serve as the reference for the row grid / right edge
BORDER_PRE_S = 0.6               # a row first seen this early at full opacity was already on screen (pre-clip)


def _slot_at(t, f):
    sl = t.get("slots") or [[t["first"], t["y0"], 0]]
    cur = sl[0]
    for s in sl:
        if s[0] <= f:
            cur = s
    return cur[2] if len(cur) > 2 else int(round(cur[1] / 40.0))


def border_shape_filter(tracks, n):
    """V6.8.2 ROW SHAPE VALIDATION -> (rows, blobs). An outlined track is a killfeed row only when it is a closed thin rectangle at least
    BORDER_ASPECT x wider than high with a valid row height, lasts at least 3 frames (or is still there at the very end of the clip), ends at the
    killfeed's right edge (rows are right-aligned; the edge is taken from the long-lived tracks) and sits on the row slot grid (pitch and phase
    from the long-lived tracks). Anything else - a bomb-site marker, a map icon, an explosion, a red wall - is a non-row blob."""
    def shape(t):
        h, w = t["y1"] - t["y0"], t["x1"] - t["x0"]
        return BORDER_H[0] <= h <= BORDER_H[1] and w >= BORDER_ASPECT * h and (t["hits"] >= 3 or (t["last"] >= n - 2 and t["hits"] >= 1))
    cand = [t for t in tracks if shape(t)]
    refs = [t for t in cand if t["hits"] >= BORDER_REF_HITS]
    x1ref = pitch = anchor = None
    if refs:
        x1ref = max(refs, key=lambda a: sum(b["hits"] for b in refs if abs(b["x1"] - a["x1"]) <= 12))["x1"]
        refs = [t for t in refs if abs(t["x1"] - x1ref) <= 14]
        lv = []
        for y in sorted(s[1] for t in refs for s in t["slots"]):
            if not lv or y - lv[-1] > 3:
                lv.append(y)
        h = sorted(t["y1"] - t["y0"] for t in refs)[len(refs) // 2] if refs else 30
        d = [b - a for a, b in zip(lv, lv[1:]) if b - a >= 0.6 * h]
        if d:
            pitch, anchor = min(d), lv[0]
    rows, blobs = [], [t for t in tracks if not shape(t)]
    for t in cand:
        ok = x1ref is None or abs(t["x1"] - x1ref) <= 14
        if ok and pitch:
            for y in (t["slots"][0][1], t["slots"][-1][1]):
                off = ((y - anchor + pitch / 2.0) % pitch) - pitch / 2.0
                ok = ok and abs(off) <= 0.3 * pitch
        (rows if ok else blobs).append(t)
    return rows, blobs


def _clear_other(text):
    """The first name of a killer side if it is a clearly readable name that is NOT mine (4+ letters, similarity to every player name
    below 40, no CJK name character), else ''."""
    from rapidfuzz import fuzz
    first = (text or "").split("+")[0]
    t = ocr_norm(first)
    if len(t) < 4 or any(c in first for n in names_split("cs2")[1] for c in n):
        return ""
    sims = [fuzz.partial_ratio(ocr_norm(n), t) if len(t) > len(ocr_norm(n)) else fuzz.ratio(ocr_norm(n), t) for n in names_split("cs2")[0] or [MY_NAME]]
    return t if max(sims) < 40 else ""


def cs2_classify_track(track, cfg=None):
    """Vote over the clearest frames of one OUTLINED row (V6.8.2: the outline marks rows where the player is the killer or the assister, never
    the victim, so a border track is a kill or an assist, never a death). Returns {verdict, name_read, why, ktext, vtext, gun, hs, ks, vs, votes,
    sus (suspicious side reads)}. verdict: kill | assist | utility | other (a stable, readable OTHER name first) | none (text could not be split)."""
    tally, votes, sus, rows_, others = {}, [], [], cs2_track_rows(track), []
    for v, r in rows_:
        if r is None:
            votes.append(("empty", 0, "OCR found nothing", "", ""))
            continue
        ver, w, why = cs2_vote_verdict(r, cfg)
        if ver == "death":                                         # my name on the victim side of an outlined row: a misread
            sus.append(why)
            if _clear_other(r.get("ktext", "")):
                ver, w, why = "none", 0, f"suspicious side read ({why}); the killer side is another readable name: not a kill"
            else:
                ver, w, why = "kill?", 1, f"suspicious side read ({why}): an outlined row is never a death, kept as a kill"
        votes.append((ver, w, why, r.get("ktext", ""), r.get("vtext", "")))
        if ver == "kill?" and r.get("gun"):
            o = _clear_other(r.get("ktext", ""))
            if o:
                others.append(o)
        if ver in ("nosplit", "empty") or (ver == "none" and not w):
            continue
        key = "kill" if ver == "kill?" else ver
        t = tally.setdefault(key, [0, 0, why, r])
        t[0] += w
        t[1] += 1 if w >= 3 else 0
        if w >= 3 or t[1] == 0:
            t[2], t[3] = why, r
    from rapidfuzz import fuzz
    if len(others) >= 3 and not any(k in tally and tally[k][1] for k in ("kill", "assist", "utility")) and \
            all(fuzz.ratio(others[0], o) >= 90 for o in others):
        r = next(r for _, r in rows_ if r)
        return {"verdict": "other", "name_read": True, "why": f"other player's row: '{others[0]}' first on the killer side in {len(others)} reads, nothing like my names",
                "ktext": r.get("ktext", ""), "vtext": r.get("vtext", ""), "gun": bool(r.get("gun")), "hs": False, "ks": 0.0, "vs": 0.0, "votes": votes, "sus": sus}
    if not tally:
        return {"verdict": "none", "name_read": False, "why": "border row, but its text could not be split into killer / weapon / victim",
                "ktext": "", "vtext": "", "gun": False, "hs": False, "ks": 0.0, "vs": 0.0, "votes": votes, "sus": sus}
    top = max(tally, key=lambda k: (tally[k][0], tally[k][1]))
    wsum, definite, why, r = tally[top]
    return {"verdict": top, "name_read": definite > 0, "why": why, "ktext": r.get("ktext", ""), "vtext": r.get("vtext", ""),
            "gun": bool(r.get("gun")), "hs": any(x.get("hs") for _, x in rows_ if x), "ks": float(r.get("ks", 0)),
            "vs": float(r.get("vs", 0)), "votes": votes, "sus": sus}


def _border_relation(a, b, ca, cb):
    """'same' | 'distinct' for two tracks (a first). V6.8.2 FRAGMENT MERGE: distinct = visible at the same time in different slots, or the first
    row was gone for more than 1.0 s before the second appeared. Same = overlapping in one slot (a twin outline), or a gap of at most 1.0 s with
    matching victim texts (CS2 normalisation / common core), or first seen within 0.35 s on one slot lineage, or the same slot and outline width."""
    gap_max, fps = int(round(BORDER_GAP_S * BORDER_FPS)), BORDER_FPS
    lo, hi = max(a["first"], b["first"]), min(a["last"], b["last"])
    if lo <= hi:
        for f in {lo, hi, (lo + hi) // 2}:
            if _slot_at(a, f) != _slot_at(b, f):
                return "distinct"
        return "same"
    if b["first"] - a["last"] > gap_max:
        return "distinct"
    va, vb = ca["vtext"], cb["vtext"]
    if ocr_norm(va) and ocr_norm(vb) and cs2_same_victim(va, vb):
        return "same"
    la = {s[2] for s in a["slots"]}
    lb = {s[2] for s in b["slots"]}
    if abs(a["first"] - b["first"]) <= int(0.35 * fps) and la & lb:
        return "same"
    if _slot_at(a, a["last"]) == _slot_at(b, b["first"]) and abs((a["x1"] - a["x0"]) - (b["x1"] - b["x0"])) <= 6:
        return "same"
    return "distinct"


def border_merge(tracks, cfg):
    """Fragments of one row (the tracker lost it and found it again) become ONE track. Returns [(merged track, classification, [member ids])]."""
    cls = {t["id"]: cs2_classify_track(t, cfg) for t in tracks}
    groups = []
    for t in sorted(tracks, key=lambda t: t["first"]):
        hit = None
        for g in groups:
            rel = [_border_relation(m, t, cls[m["id"]], cls[t["id"]]) if m["first"] <= t["first"] else _border_relation(t, m, cls[t["id"]], cls[m["id"]]) for m in g]
            if "same" in rel and "distinct" not in rel:
                hit = g
                break
        if hit is None:
            groups.append([t])
        else:
            hit.append(t)
    res = []
    for g in groups:
        if len(g) == 1:
            res.append((g[0], cls[g[0]["id"]], [g[0]["id"]]))
            continue
        g = sorted(g, key=lambda t: t["first"])
        m = dict(g[0])
        m.update(first=g[0]["first"], last=max(t["last"] for t in g), hits=sum(t["hits"] for t in g), x0=g[-1]["x0"], x1=g[-1]["x1"],
                 slots=sorted((s for t in g for s in t["slots"]), key=lambda s: s[0]), votes=sorted((v for t in g for v in t.get("votes", [])), key=lambda v: v["f"]))
        res.append((m, cs2_classify_track(m, cfg), [t["id"] for t in g]))
    return res


def border_analysis(sc, cfg, deaths=None):
    """Sidecar -> kills / rejected rows, in the format of analyse_entry() (V6.8.2). The stored tracks are interpreted at load time (nothing is
    rebuilt): shape validation (non-row blobs are discarded), fragment merge, then classification. ONE kill per distinct outlined-row event, time =
    the FIRST frame it appeared; no kills-per-round cap and no same-victim rule (they stay in the name-based fallback only). Pre-clip: a row first
    seen within the first 0.6 s at full opacity (sidecars without opacity data: not the newest slot) was on screen already. Deaths are never
    outlined: `deaths` comes from the normal name rule (analyse_entry) and keeps its 8 s lock."""
    off, fps, n = sc.get("v_off", 0.0), float(sc.get("fps", BORDER_FPS)), int(sc.get("frames", 0))
    legacy = sc.get("ext", 1) < 2
    rows_t, blob_t = border_shape_filter(sc.get("tracks", []), n)
    kills, rej, vis, mine, det_rows, sus, others, merges = [], [], [], [], [], [], [], []
    blobs_n = len(blob_t) + int(sc.get("blobs", 0))
    tok = hashlib.md5((sc.get("key") or "").encode()).hexdigest()[:4]       # an unreadable victim gets a name unique to this clip and row
    for t, c, ids in sorted(border_merge(rows_t, cfg), key=lambda x: x[0]["first"]):
        tt = round(t["first"] / fps + off, 3)
        last = round(t["last"] / fps + off, 3)
        if c["verdict"] == "none":
            if c["sus"]:                                           # a readable row, but my name on its victim side and another name first: not a kill
                for s_ in c["sus"]:
                    sus.append((tt, s_))
                rej.append({"t": tt, "reason": c["why"] if c["why"].startswith("suspicious") else f"suspicious side read: {c['sus'][0]}", "ks": 0.0})
                det_rows.append({"track": t, "cls": c, "t": tt, "merged": ids})
            else:
                blobs_n += 1                                       # outlined, but nothing that reads as a killfeed row
            continue
        row = f"[{c['ktext'] or '-'}] {'gun' if c['gun'] else 'util'} [{c['vtext'] or '-'}]"
        v = c["verdict"]
        if len(ids) > 1:
            merges.append((tt, ids))
        for s in c["sus"]:
            sus.append((tt, s))
        if v == "other":
            others.append((tt, c["why"]))
        mine.append({"t": tt, "row": row, "verdict": "kill" if v == "kill" else "reject", "why": c["why"], "hits": t["hits"]})
        det_rows.append({"track": t, "cls": c, "t": tt, "merged": ids})
        op0 = t.get("op0")
        pre = t["first"] <= BORDER_PRE_F or (t["first"] <= int(BORDER_PRE_S * fps) and
                                              ((op0 is not None and op0 >= 0.85) or (op0 is None and _slot_at(t, t["first"]) > 0)))
        if pre:
            rej.append({"t": tt, "reason": f"pre-clip: row already on screen when the clip starts ({row})", "ks": max(c["ks"], c["vs"]) / 100})
        elif v == "kill":
            vis.append((tt, round(last + 0.3, 3)))
            kills.append({"t": tt, "ks": (c["ks"] / 100) if c["name_read"] else 0.6, "hs": bool(c["hs"]), "row": row, "hits": t["hits"],
                          "victim": c["vtext"] or f"(unread {tok}{t['id']})", "weapon": "gun", "box": None, "t_last": last, "needs_shot": False,
                          "border": True, "name_read": c["name_read"], "track": t["id"], "why": c["why"], "frags": len(ids)})
        elif v == "other":
            rej.append({"t": tt, "reason": c["why"], "ks": 0.0})
        else:
            vis.append((tt, round(last + 0.3, 3)))
            rej.append({"t": tt, "reason": c["why"], "ks": c["ks"] / 100})
    victims = [ocr_norm(k["victim"]) for k in kills if k["name_read"] and ocr_norm(k["victim"])]
    rep = any(cs2_same_victim(a, b) for i, a in enumerate(victims) for b in victims[i + 1:])
    return {"kills": kills, "deaths": sorted(deaths or []), "revives": [], "rej": sorted(rej, key=lambda r: r["t"]), "vis": vis,
            "best_k": max([d["cls"]["ks"] for d in det_rows], default=0.0) / 100, "best_v": max([d["cls"]["vs"] for d in det_rows], default=0.0) / 100,
            "mine": sorted(mine, key=lambda m: m["t"]), "rows_n": len(det_rows), "rows_max": len(det_rows),
            "ocr_calls": sum(len(t.get("votes", [])) for t in sc.get("tracks", [])), "cjk": {}, "border": True, "rows": det_rows,
            "blobs": blobs_n, "sus": sus, "others": others, "merges": merges, "legacy": legacy,
            "dm": len(kills) > 6 or rep}


def analyse_clip_entry(rec, entry, cfg, game=None, build=False):
    """analyse_entry() plus the CS2 red-border list: when the clip's sidecar exists (or `build` creates it), the border-based list replaces the
    name-based one (deaths stay the name-based ones); otherwise - and for every other game - this IS analyse_entry(). A clip whose sidecar holds
    no outlined row at all keeps the name-based list (the border colour was not found: nothing is dropped on that evidence)."""
    a = analyse_entry(entry, cfg, game)
    if (game or entry.get("game")) != "cs2" or not rec:
        return a
    try:
        det = Detector("cs2")
        sc = border_load(rec, det)
        if sc is None and build and rec["path"] not in BORDER_FAILED:
            sc = border_build(rec, det, cfg)
    except Exception as ex:
        BORDER_FAILED.add(rec.get("path"))
        out(f"CS2 row borders: {Path(rec.get('path', '?')).name}: {ex} - name-based kills used")
        return a
    if sc is None:
        return a
    b = border_analysis(sc, cfg, a["deaths"])
    if not sc.get("tracks") and not sc.get("blobs"):
        a["border_note"] = "no red-outlined row found in this clip: the name-based list is kept"
        return a
    b["old"] = a
    return b


# ---- commands: bordercache / rowdebug ----------------------------------------------------------------------------------------
def _cs2_recs(cfg, only_scanned=False, det=None):
    det = det or Detector("cs2")
    store = load_kills_cache() if only_scanned else None
    return [r for r in scan_clips(cfg) if r.get("game") == "cs2" and not r.get("error") and r.get("w")
            and (store is None or kills_key(r, "cs2", det) in store)]


def cmd_bordercache(args):
    """V6.8.1: python montage.py bordercache cs2 [--all]. Builds the red-border sidecars (montage_data\\cs2_rows_v1) of the CS2 clips that have a
    kill-cache entry and no sidecar. --all: every CS2 clip in the clip folders, existing sidecars rebuilt too. Prints the cost per clip."""
    cfg = load_config()
    det = Detector("cs2")
    recs = _cs2_recs(cfg, only_scanned=not args.all, det=det)
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found")
    t0 = time.time()
    res = border_build_many(recs, cfg, det, force=bool(args.all))
    done = [sc for sc in res.values() if sc]
    out(f"bordercache cs2: {len(recs)} clips in scope, {len(done)} sidecars built in {time.time() - t0:.0f}s"
        + (f"; per clip: decode+track {sum(s['decode_secs'] for s in done) / len(done):.1f}s on average "
           f"({sum(s['ms_per_frame'] for s in done) / len(done):.1f} ms per decoded frame at {BORDER_FPS} fps), "
           f"OCR of the rows {sum(s['ocr_secs'] for s in done) / len(done):.1f}s on average; "
           f"outlined rows per clip {sum(len(s['tracks']) for s in done) / len(done):.1f}" if done else "")
        + f"; failed {len([r for r in recs if r['path'] in BORDER_FAILED])}")


def grab_region_frame(rec, det, cfg, t):
    """One killfeed-region frame (BGR, 1920x1080 space) at stream time t, or None."""
    import numpy as np
    r = run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", rec["path"], "-frames:v", "1", "-vf", region_filter(rec, det, cfg),
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], timeout=60)
    n = det.dw * det.dh * 3
    if len(r.stdout) < n:
        return None
    return np.frombuffer(r.stdout[:n], np.uint8).reshape(det.dh, det.dw, 3).copy()


def _kill_diff(old_ts, new_ts, tol=1.0):
    """(only in the old list, only in the new list, matched pairs): kills match when they are within `tol` s."""
    old_ts, new_ts, used, only_old, pairs = sorted(old_ts), sorted(new_ts), set(), [], []
    for o in old_ts:
        j = next((j for j, n in enumerate(new_ts) if j not in used and abs(n - o) <= tol), None)
        if j is None:
            only_old.append(o)
        else:
            used.add(j)
            pairs.append((o, new_ts[j]))
    return only_old, [n for j, n in enumerate(new_ts) if j not in used], pairs


def rowdebug_clip(rec, cfg, det, store, images=False, rebuild=False, write=True):
    """V6.8.2: everything rowdebug prints about one CS2 clip. Reads the sidecar (builds it when missing / --rebuild); never writes the real
    kill cache or region files. Non-row blobs are counted and collapsed. Returns a dict with the lines and the numbers the --all table uses."""
    import cv2
    name = Path(rec["path"]).name
    lines = [f"=== {name}"]
    sc = None if rebuild else border_load(rec, det)
    imgs, how = {}, "loaded from the sidecar"
    if sc is None:
        sc = border_build(rec, det, cfg, write=write, keep_images=images)
        imgs = sc.pop("_images", {})
        how = "built now" + (" and saved" if write else " (not saved)")
    lines.append(f"border sidecar {how}: {sc['frames']} frames at {sc['fps']} fps, decode+track {sc['decode_secs']}s ({sc['ms_per_frame']} ms/frame), "
                 f"OCR of the rows {sc['ocr_secs']}s" + ("" if sc.get("ext", 1) >= 2 else "  [older sidecar: no fade-in data, pre-clip uses the slot rule]"))
    e = store.get(kills_key(rec, "cs2", det)) if store is not None else None
    old = analyse_entry(e, cfg, "cs2") if e and not e.get("error") else None
    b = border_analysis(sc, cfg, old["deaths"] if old else [])
    lines.append(f"border tracks: {len(b['rows'])} rows" + (f", discarded {b['blobs']} non-row blobs" if b["blobs"] else "") +
                 (f", {len(b['merges'])} merged fragment group(s)" if b["merges"] else ""))
    for i, d in enumerate(b["rows"], 1):
        t, c = d["track"], d["cls"]
        sl = [s[2] for s in t["slots"]]
        slot = f"slot {sl[0]}" + (f"->{sl[-1]}" if sl[-1] != sl[0] else "") + (f" (moved {len(sl) - 1}x)" if len(sl) > 1 else "")
        frag = f"  [{len(d['merged'])} fragments merged]" if len(d["merged"]) > 1 else ""
        lines.append(f"  #{i}  first {ts(t['first'] / sc['fps'] + sc['v_off'])}  last {ts(t['last'] / sc['fps'] + sc['v_off'])}  frames {t['hits']}  {slot}{frag}"
                     f"  -> {c['verdict'].upper()}{'' if c['name_read'] or c['verdict'] in ('none',) else ' (name unreadable, border confirmed)'}")
        lines.append(f"       killer side: '{c['ktext']}'   victim side: '{c['vtext']}'   {'gun' if c['gun'] else 'util'}{' HS' if c['hs'] else ''}   {c['why']}")
        lines.append("       votes: " + "; ".join(f"{v[0]}({v[1]}) '{v[3]}' > '{v[4]}'" for v in c["votes"]))
        if images and t.get("best_f") is not None:
            try:
                img = imgs.get(t["id"])
                if img is None:
                    fr = grab_region_frame(rec, det, cfg, t["best_f"] / sc["fps"])
                    rc = t["best_rect"]
                    img = fr[max(0, rc["y0"] - 2):rc["y1"] + 3, max(0, rc["x0"] - 2):rc["x1"] + 3] if fr is not None else None
                if img is not None:
                    d_ = HERE / "rowdebug_images" / re.sub(r"[^\w.-]+", "_", Path(rec["path"]).stem)
                    d_.mkdir(parents=True, exist_ok=True)
                    tm = t["best_f"] / sc["fps"] + sc["v_off"]
                    fp = d_ / f"row{i}_{int(tm // 60)}m{tm % 60:05.2f}s.png"
                    cv2.imencode(".png", img)[1].tofile(str(fp))
                    lines.append(f"       crop saved: {fp}")
            except Exception as ex:
                lines.append(f"       (crop not saved: {ex})")
    for tt, why in b["sus"]:
        lines.append(f"  SUSPICIOUS side read @ {ts(tt)}: {why}")
    for tt, why in b["others"]:
        lines.append(f"  OTHER PLAYER'S ROW @ {ts(tt)}: {why}")
    if b["dm"]:
        lines.append("  WARNING: possible Deathmatch/community server (more than 6 distinct kills or repeated victims) - all kills are kept, no per-round cap")
    new_t = [k["t"] for k in b["kills"]]
    old_t = [k["t"] for k in old["kills"]] if old else []
    lines.append(("old name-based kills: " + (", ".join(ts(t) for t in old_t) or "none")) if old else "old name-based kills: (clip has no cached scan)")
    lines.append("border-based kills:   " + (", ".join(ts(t) for t in new_t) or "none"))
    only_old, only_new, _ = _kill_diff(old_t, new_t)
    if old is not None:
        lines.append(f"difference: {len(new_t)} border kills vs {len(old_t)} name-based"
                     + (f"; only name-based: {', '.join(ts(t) for t in only_old)}" if only_old else "")
                     + (f"; only border-based: {', '.join(ts(t) for t in only_new)}" if only_new else "")
                     + ("" if only_old or only_new else "; same kills"))
    if not sc.get("tracks") and not sc.get("blobs"):
        lines.append("NOTE: no red-outlined row found in this clip, so the name-based list stays in use for it")
    for j in b["rej"]:
        lines.append(f"   not a kill @ {ts(j['t'])}: {j['reason']}")
    burst = max([sum(1 for u in new_t if 0 <= u - t < 2.0) for t in new_t], default=0)
    return {"name": name, "lines": lines, "old": old_t if old else None, "new": new_t, "only_old": only_old, "only_new": only_new,
            "cost": sc["secs"], "tracks": len(sc.get("tracks", [])), "blobs": b["blobs"], "sus": len(b["sus"]), "others": len(b["others"]),
            "burst": burst, "dm": b["dm"], "legacy": b["legacy"]}


def rowdebug_suspicion(d):
    """Sort key of the --all table (bigger = more suspicious): border vs name-based difference, 4+ kills within 2 s, 20+ discarded blobs,
    suspicious side reads, other players' rows."""
    return (len(d["only_old"]) + len(d["only_new"]) + (4 if d["burst"] >= 4 else 0) + (3 if d["blobs"] >= 20 else 0) + 2 * d["sus"] + 3 * d["others"],
            abs(len(d["new"]) - len(d["old"] or [])))


def cmd_rowdebug(args):
    """V6.8.2: python montage.py rowdebug cs2 <clip name or path> [--all] [--rebuild]. Diagnostic: border tracks, their classification and
    the OCR text of both sides, the old name-based kills and the difference; crops of each track in rowdebug_images\\<clip>\\. --all: one table
    of every cached CS2 clip sorted by suspicion, saved to rowdebug_cs2.txt. Never writes the real kill cache or region files."""
    cfg = load_config()
    det = Detector("cs2")
    store = load_kills_cache()
    if args.all:
        recs = _cs2_recs(cfg, only_scanned=True, det=det)
        rows = []
        for i, r in enumerate(recs, 1):
            try:
                d = rowdebug_clip(r, cfg, det, store, images=False, rebuild=args.rebuild)
            except Exception as ex:
                rows.append({"name": Path(r["path"]).name, "old": None, "new": [], "only_old": [], "only_new": [], "err": str(ex), "burst": 0, "blobs": 0,
                             "sus": 0, "others": 0, "dm": False, "legacy": False})
                continue
            rows.append(d)
            progress(i / len(recs), f"rowdebug {i}/{len(recs)}")
        rows.sort(key=rowdebug_suspicion, reverse=True)
        hdr = f"{'clip':58} {'name':>5} {'border':>6} {'diff':>5} {'burst':>5} {'blobs':>5} {'sus':>3} {'oth':>3}  notes"
        table = [f"rowdebug cs2 - {len(rows)} cached clips, sorted by suspicion (name-based = V6.7.2 list, border = V6.8.2 list; burst = most kills within 2 s)", hdr, "-" * len(hdr)]
        for d in rows:
            if d.get("err"):
                table.append(f"{d['name'][:58]:58} {'-':>5} {'-':>6} {'-':>5} {'-':>5} {'-':>5} {'-':>3} {'-':>3}  ERROR {d['err']}")
                continue
            notes = ([f"name-only {', '.join(ts(t) for t in d['only_old'])}"] if d["only_old"] else []) + \
                    ([f"border-only {', '.join(ts(t) for t in d['only_new'])}"] if d["only_new"] else []) + (["Deathmatch?"] if d["dm"] else [])
            table.append(f"{d['name'][:58]:58} {len(d['old'] or []):5d} {len(d['new']):6d} {len(d['new']) - len(d['old'] or []):+5d} {d['burst']:5d} {d['blobs']:5d} "
                         f"{d['sus']:3d} {d['others']:3d}  " + ("; ".join(notes) or "-"))
        leg = sum(1 for d in rows if d.get("legacy"))
        table.append(f"total: name-based {sum(len(d['old'] or []) for d in rows)} kills, border-based {sum(len(d['new']) for d in rows)} kills, "
                     f"clips that differ {sum(1 for d in rows if d['only_old'] or d['only_new'])}, discarded blobs {sum(d['blobs'] for d in rows)}")
        table.append(f"{leg} of {len(rows)} sidecars lack the fade-in (opacity) data (built by V6.8.1): their pre-clip rule uses the slot proxy; "
                     "python montage.py bordercache cs2 --all rebuilds them")
        txt = "\n".join(table)
        out(txt)
        (HERE / "rowdebug_cs2.txt").write_text(txt + "\n", encoding="utf-8")
        out(f"saved {HERE / 'rowdebug_cs2.txt'}")
        return
    if not args.clip:
        raise SystemExit("rowdebug cs2 <clip name or path> [--all]")
    q = args.clip.lower()
    recs = [r for r in _cs2_recs(cfg, det=det) if Path(r["path"]).name.lower() == q or r["path"].lower() == q]
    recs = recs or [r for r in _cs2_recs(cfg, det=det) if q in r["path"].lower()]
    if not recs and os.path.isfile(args.clip):
        rec = analyse_clip(os.path.abspath(args.clip), load_json(CLIPS_CACHE, {}), False, cfg.get("bar"))[1]
        rec["game"] = "cs2"
        recs = [rec]
    if not recs:
        raise SystemExit(f"no CS2 clip matches '{args.clip}' (give the file name, a part of it, or a full path)")
    for r in recs[:10]:
        for ln in rowdebug_clip(r, cfg, det, store, images=True, rebuild=args.rebuild)["lines"]:
            out(ln)


_CS2_STREAM = {}


def _cs2_stream(rec, cfg):
    """V6.7 (CS2 only): the audio track the clip actually has sound on - the very pick the plan uses (Settings > Audio mode and
    game audio track, a silent track is never chosen) - instead of track 1, which many CS2 replays leave silent."""
    key = (rec.get("path"), str((cfg or {}).get("audio_mode", "auto")), str(((cfg or {}).get("game_audio_track") or {}).get("cs2", "auto")))
    if key not in _CS2_STREAM:
        try:
            _CS2_STREAM[key] = int(resolve_clip_audio(rec, cfg or {}, "cs2", {}).get("stream") or 0)
        except Exception:
            _CS2_STREAM[key] = int(rec.get("a_stream", 0))
    return _CS2_STREAM[key]


def _onset_key(rec, cfg=None):
    """Onset-cache key. Valorant (and every other caller): unchanged '<file>o1' (track a_stream). CS2: '<file>o1c<track>'."""
    if rec.get("game") == "cs2":
        return file_key(rec["path"]) + f"o1c{_cs2_stream(rec, cfg)}"
    return file_key(rec["path"]) + "o1"


def cs2_no_gunshots(rec, ons):
    """V6.7 (CS2): True when no audio track of the clip has gunshots (no audio, every track silent, or none with an onset), so a
    missing gunshot says nothing about the kill."""
    if ons:
        return False
    m = load_json(LOUD_CACHE, {}).get(file_key(rec["path"]) + "|t2") or {}
    return not any((x or 0) > 0 for x in m.get("ons", []))


def gun_onsets(rec, cache=None, cfg=None):
    """Gunshot-like transients in the clip's game audio: [[t, strength], ...] on the container timeline. None = no audio."""
    if not rec.get("audio"):
        return None
    import numpy as np
    key = _onset_key(rec, cfg)
    stream = _cs2_stream(rec, cfg) if rec.get("game") == "cs2" else int(rec.get("a_stream", 0))
    cache = cache if cache is not None else load_json(ONSET_CACHE, {})
    if key in cache:
        return cache[key]
    import librosa
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", rec["path"], "-map", f"0:a:{stream}", "-vn", "-ac", "1", "-ar", "22050",
                        "-f", "f32le", "-"], capture_output=True, timeout=120)
    y = np.frombuffer(r.stdout, np.float32)
    ons = []
    if len(y) > 22050:
        hop = 256
        env = librosa.onset.onset_strength(y=y, sr=22050, hop_length=hop, fmin=500, fmax=9000)
        fr = librosa.onset.onset_detect(onset_envelope=env, sr=22050, hop_length=hop, units="frames", backtrack=False,
                                        pre_max=3, post_max=3, pre_avg=10, post_avg=10, delta=0.2, wait=5)
        thr = max(3.0 * float(np.median(env)), 0.15 * float(env.max()))
        ons = [[round(float(f * hop / 22050 + rec.get("a_off", 0.0)), 3), round(float(env[f]), 2)] for f in fr if env[f] >= thr]
    cache[key] = ons
    return ons


def verified_kills(pool_items, cfg):
    """Gunshot audio is a SOFT signal now: it refines each kill to the shot time and adds a score bonus, never rejects.
    The only hard rule here is the death lock. Returns stats; every rejection is logged with its reason."""
    cache = load_json(ONSET_CACHE, {})
    todo = [it["rec"] for it in pool_items if it["rec"].get("audio") and _onset_key(it["rec"], cfg) not in cache]
    if todo:
        out(f"  analysing gunshots in {len(todo)} clips ...")
        res = {}
        with ThreadPoolExecutor(max_workers=4) as ex:
            for i, (r, o) in enumerate(zip(todo, ex.map(lambda r: gun_onsets(r, {}, cfg), todo)), 1):
                res[_onset_key(r, cfg)] = o
                progress(i / len(todo), "gunshot analysis")
        cache.update(res)
        save_json(ONSET_CACHE, cache)
    st = {"raw": 0, "no_shot": 0, "death_lock": 0, "kept": 0}
    lock = float(cfg.get("death_lock_s", 8.0))
    for it in pool_items:
        ons = gun_onsets(it["rec"], cache, cfg)
        no_shots = it["rec"].get("game") == "cs2" and cs2_no_gunshots(it["rec"], ons)       # V6.7: nothing to confirm with
        keep = []
        name = Path(it["rec"]["path"]).name
        for k in it["kills"]:
            st["raw"] += 1
            shot = None
            if ons:
                cand = [o for o in ons if k["t"] - 0.6 <= o[0] <= k["t"] + 0.05]
                if cand:
                    shot = max(cand, key=lambda o: o[0])[0]
            if shot is None:
                st["no_shot"] += 1
                if k.get("needs_shot") and not (no_shots and len(_alnum(k.get("victim"))) >= 3):      # V6.7: CS2 clip without any gunshot: nothing to confirm with
                    it["rej"].append({"t": k["t"], "reason": "1 sighting, name < 90 and no gunshot to confirm it", "ks": k["ks"]})
                    continue
                it["rej"].append({"t": k["t"], "reason": "no gunshot heard (kept - audio is only a bonus)", "ks": k["ks"], "soft": True})
                k = dict(k, shot=False, lag=0.0)
            else:                                              # V5: the kill time stays the ROW time (that is what lands on the beat)
                k = dict(k, shot=True, lag=round(k["t"] - shot, 3), shot_t=round(shot, 3))
            if k.get("weak_hl"):
                it["rej"].append({"t": k["t"], "reason": "no highlight colour (kept - highlight is only a bonus)", "ks": k["ks"], "soft": True})
            if any(d < k["t"] <= d + lock and not any(d < rv <= k["t"] for rv in it.get("revives", []))
                   for d in it.get("deaths", [])):                     # a (Clove) revive ends the lock
                st["death_lock"] += 1
                it["rej"].append({"t": k["t"], "reason": f"within {lock:.0f}s after my death", "ks": k["ks"]})
                continue
            keep.append(k)
        it["kills"] = keep
        st["kept"] += len(keep)
    return st


def ts(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def kills_key(rec, game, det):
    b = hashlib.md5(rec.get("bar_sig", "").encode()).hexdigest()[:6] if rec.get("bars") else "nb"
    return f"{file_key(rec['path'])}|{game}|{det.d['stamp']}{ALGO}{b}"


def load_dets(only=None):
    d = {}
    for g in GAMES:
        if only and g != only:
            continue
        try:
            d[g] = Detector(g)
        except Exception as ex:
            out(f"detector {g} unusable: {ex}")
    return d


def clip_game(rec, dets=None, cache=None):
    return rec.get("game")                  # the game comes from the folder name only - no HUD guessing


# ------------------------------------------------------------------- bars
def measure_bars(cfg, paths=None, sample=60):
    """Find the black-border rectangle that repeats across clips (clusters of near-identical rects)."""
    if not paths:
        allp = sorted(walk_files(clip_roots(cfg), VIDEO_EXT, MIN_VIDEO, cfg))
        random.Random(7).shuffle(allp)
        paths = allp[:sample]
    out(f"measuring black bars on {len(paths)} clips ...")

    def one(p):
        try:
            info = probe_video(p)
            rect, note = detect_rect(p, info)
            return info, rect
        except Exception:
            return None, None
    found = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, (info, rect) in enumerate(ex.map(one, paths), 1):
            progress(i / len(paths), "measuring bars")
            if CANCEL.is_set():
                return None
            if not rect:
                continue
            sides = (rect[0], rect[1], info["w"] - rect[0] - rect[2], info["h"] - rect[1] - rect[3])
            if any(v > 8 for v in sides):
                found.append(((info["w"], info["h"]), rect))
    out(f"  {len(found)} of {len(paths)} measured clips have black bars")
    clusters = []
    for src, rect in found:
        for c in clusters:
            if c["src"] == src and max(abs(a - b) for a, b in zip(c["rect"], rect)) <= 16:
                c["m"].append(rect)
                break
        else:
            clusters.append({"src": src, "rect": rect, "m": [rect]})
    if not clusters:
        return None
    best = max(clusters, key=lambda c: len(c["m"]))
    if len(best["m"]) < 2 and len(paths) > 3:
        return None
    med = [int(statistics.median(m[i] for m in best["m"])) & ~1 for i in range(4)]
    out(f"  bar crop {best['src'][0]}x{best['src'][1]} -> x,y,w,h = {med}  ({len(best['m'])} clips agree)")
    return {"src": list(best["src"]), "rect": med, "n": len(best["m"])}


def ensure_bars(cfg, force=False):
    """First run: auto-measure once and store the fixed crop in config."""
    if cfg.get("bar_checked") and not force:
        return
    if not next(walk_files(clip_roots(cfg), VIDEO_EXT, MIN_VIDEO, cfg), None):
        return                                   # no clips yet: check again next time
    cfg["bar"] = measure_bars(cfg)
    cfg["bar_checked"] = True
    save_json(CONFIG_PATH, cfg)
    out("bars: " + ("fixed crop stored" if cfg["bar"] else "none found (all clips treated as full frame)"))


def cmd_calibrate_bars(args):
    cfg = load_config()
    bar = measure_bars(cfg, list(args.clips) or None, args.sample)
    if not bar:
        out("No repeating bar rectangle found. Name 2-3 clips with bars: calibrate-bars <clip> <clip> <clip>")
        return
    cfg["bar"], cfg["bar_checked"] = bar, True
    save_json(CONFIG_PATH, cfg)
    out("saved")


# ------------------------------------------------------------ calibration
def region_stamp(region):
    """The region hash stored in every kill-cache key ('ocr' + md5 of the rounded region); same formula as Detector."""
    return "ocr" + hashlib.md5(repr([round(float(v), 4) for v in region]).encode()).hexdigest()[:8]


def backup_region_file(game):
    """V6.7.6: a dated copy of detect_<game>.json (an empty record when there is none = default region) before every save / reset."""
    p = DATA / f"detect_{game}.json"
    DATA.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dst, n = DATA / f"detect_{game}_backup_{stamp}.json", 1
    while dst.exists():
        n += 1
        dst = DATA / f"detect_{game}_backup_{stamp}_{n}.json"
    if p.exists():
        shutil.copy2(p, dst)
    else:
        save_json(dst, {})
    return dst


VAL_BACKUP = DATA / "valorant_cache_backup.json"
_VAL_BACKUP_LOCK = threading.Lock()


def backup_valorant_entry(store, key):
    """V6.7.6: before a cached Valorant entry is overwritten, its old content goes into valorant_cache_backup.json. The first copy per
    clip is kept; an existing backup is never overwritten."""
    if not store._p(key).exists():
        return False
    e = store.get(key)
    if e is None:
        return False
    clip = "|".join(key.split("|")[:3])
    with _VAL_BACKUP_LOCK:
        b = load_json(VAL_BACKUP, {}) or {}
        if clip in b:
            return False
        b[clip] = {"saved": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "key": key, "e": e}
        save_json(VAL_BACKUP, b)
    return True


def _read_region(path):
    """The region of a detect_*.json style file: [x0,y0,x1,y1], None = default region (no 'region'), False = unreadable."""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return False
    reg = d.get("region") if isinstance(d, dict) else None
    if reg is None:
        return None
    try:
        reg = [float(v) for v in reg]
        return reg if len(reg) == 4 and 0 <= reg[0] < reg[2] <= 1 and 0 <= reg[1] < reg[3] <= 1 else False
    except Exception:
        return False


def region_backups(game):
    return sorted(DATA.glob(f"detect_{game}_backup_*.json"), key=lambda b: (b.stat().st_mtime_ns, b.name))


def region_groups(game):
    """{region hash: {"files", "clips", "times", "region"}} of the cached entries of a game (current cache format); region = the region the
    entry itself stored (None for entries written before entries kept it). Second value: entries of another cache format (unusable)."""
    groups, other = {}, 0
    for (name, size, mt, g), lst in _cache_index().items():
        if g != game:
            continue
        for p, _d, _path, stamp, algo, _bars in lst:
            if algo != ALGO[1:]:
                other += 1
                continue
            gr = groups.setdefault(stamp, {"files": [], "clips": set(), "times": [], "region": None})
            gr["files"].append(p)
            gr["clips"].add((name, size, mt))
            try:
                gr["times"].append(os.path.getmtime(p))
            except OSError:
                pass
    for gr in groups.values():
        for p in gr["files"][:8]:                             # the payload is only read for a few files per hash
            try:
                reg = json.loads(Path(p).read_text(encoding="utf-8")).get("e", {}).get("region")
            except Exception:
                continue
            if reg and len(reg) == 4:
                gr["region"] = [float(v) for v in reg]
                break
    return groups, other


def _fmt_t(t):
    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")


def region_report(game):
    """V6.7.6: everything regioncheck / regionrestore show, as data."""
    det = Detector(game)
    dflt = DEFAULT_REGION[game]
    groups, other = region_groups(game)
    sd = saved_default(game)
    return {"game": game, "current": det.d["region"], "current_hash": det.d["stamp"], "calibrated": det.calibrated,
            "default": list(dflt), "default_hash": region_stamp(dflt), "saved_default": sd, "saved_default_hash": region_stamp(sd) if sd else None,
            "backups": [(b, _read_region(b)) for b in region_backups(game)], "groups": groups, "other_format": other}


def _group_line(h, gr, rep):
    t = gr["times"]
    tag = " <- CURRENT region" if h == rep["current_hash"] else ""
    tag += " (= default region)" if h == rep["default_hash"] else ""
    return (f"  {h}  {len(gr['files']):5d} entries  {len(gr['clips']):5d} clips  scanned {_fmt_t(min(t)) if t else '?'} .. {_fmt_t(max(t)) if t else '?'}  "
            f"region {gr['region'] if gr['region'] else 'not stored in these entries'}{tag}{'' if h == rep['current_hash'] else '  STALE (kept, ignored)'}")


def cmd_regioncheck(args):
    """V6.7.6: python montage.py regioncheck <game>"""
    rep = region_report(args.game)
    out(f"== {args.game}: killfeed region ({DATA / ('detect_' + args.game + '.json')}) ==")
    out(f"current region  {rep['current']}  hash {rep['current_hash']}  ({'calibrated' if rep['calibrated'] else 'default'})")
    out(f"default region  {rep['default']}  hash {rep['default_hash']}  (built-in)")
    if rep["saved_default"]:
        out(f"saved default   {rep['saved_default']}  hash {rep['saved_default_hash']}  (Reset to default / --use default)")
    out(f"dated backups of the region file: {len(rep['backups'])}")
    for b, reg in rep["backups"]:
        out(f"  {b.name}  {_fmt_t(b.stat().st_mtime)}  region {reg if reg else 'default (none stored)' if reg is None else 'unreadable'}"
            + (f"  hash {region_stamp(reg if reg else DEFAULT_REGION[args.game])}" if reg is not False else ""))
    g = rep["groups"]
    out(f"region hashes in cached {args.game} entries ({sum(len(x['files']) for x in g.values())} entries, {len(g)} hash(es)"
        f"{', ' + str(rep['other_format']) + ' entries of an older cache format' if rep['other_format'] else ''}):")
    for h in sorted(g, key=lambda h: (h != rep["current_hash"], -len(g[h]["files"]))):
        out(_group_line(h, g[h], rep))
    if g and rep["current_hash"] not in g:
        out("  (no cached entry has the current region's hash)")
    elif g:
        out(f"  current hash {rep['current_hash']} matches {len(g[rep['current_hash']]['files'])} entries")


JOB_LOCK = DATA / "job_running.lock"                   # V6.8: present while a scan or render runs (regiontest refuses to start then)
_JOB_DEPTH = [0]
_JOB_MUTEX = threading.Lock()


def job_enter(name):
    with _JOB_MUTEX:
        _JOB_DEPTH[0] += 1
        try:
            JOB_LOCK.parent.mkdir(parents=True, exist_ok=True)
            JOB_LOCK.write_text(json.dumps({"pid": os.getpid(), "job": name, "t": time.time()}), encoding="utf-8")
        except OSError:
            pass


def job_exit():
    with _JOB_MUTEX:
        _JOB_DEPTH[0] = max(0, _JOB_DEPTH[0] - 1)
        if not _JOB_DEPTH[0]:
            try:
                JOB_LOCK.unlink()
            except OSError:
                pass


def _pid_alive(pid):
    try:
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))      # PROCESS_QUERY_LIMITED_INFORMATION
            if h:
                ctypes.windll.kernel32.CloseHandle(h)
                return True
            return False
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def job_active():
    """Name of the scan / render / task running in this or another Montager process, else None (a lock of a dead process is ignored)."""
    if _JOB_DEPTH[0]:
        return (load_json(JOB_LOCK, {}) or {}).get("job") or "a job"
    if JOB_LOCK.exists():
        d = load_json(JOB_LOCK, {}) or {}
        if d.get("pid") and _pid_alive(d["pid"]):
            return d.get("job") or "a job"
    return None


def with_job(name):
    def deco(fn):
        def w(*a, **k):
            job_enter(name)
            try:
                return fn(*a, **k)
            finally:
                job_exit()
        w.__name__, w.__doc__ = fn.__name__, fn.__doc__
        return w
    return deco


REGION_DEFAULTS = DATA / "region_defaults.json"      # V6.8: {game: [x0, y0, x1, y1]} the saved default the user chose (never set automatically)


def _valid_region(reg):
    try:
        reg = [float(v) for v in reg]
    except Exception:
        return None
    return [round(v, 4) for v in reg] if len(reg) == 4 and 0 <= reg[0] < reg[2] <= 1 and 0 <= reg[1] < reg[3] <= 1 else None


def saved_default(game):
    """V6.8: the user's saved default region of a game, or None (then the built-in DEFAULT_REGION is the default)."""
    return _valid_region((load_json(REGION_DEFAULTS, {}) or {}).get(game) or [])


def set_saved_default(game, region):
    reg = _valid_region(region)
    if not reg:
        raise ValueError("not a valid killfeed region")
    d = load_json(REGION_DEFAULTS, {}) or {}
    d[game] = reg
    save_json(REGION_DEFAULTS, d)
    return reg


def apply_default_region(game):
    """V6.8: 'Reset to default': the saved default when there is one (written as the game's region), else the built-in default (no region
    key = the built-in constants). Only Reset / --use default use the saved default; a game without a region file always reads the built-in one."""
    reg = saved_default(game)
    if reg:
        return save_region(game, reg)
    reset_region(game)
    return None


def _resolve_region(game, use):
    """(region|None for the built-in default, hash, source text) or (False, None, why). Never guesses: only what the user named."""
    rep = region_report(game)
    dflt_h = rep["default_hash"]
    if use == "builtin":
        return None, dflt_h, "the built-in default region"
    if use == "default":
        if rep["saved_default"]:
            return list(rep["saved_default"]), rep["saved_default_hash"], "the saved default region"
        return None, dflt_h, "the default region"
    for pre in ("backup:", "file:"):
        if use.startswith(pre):
            f = Path(use[len(pre):])
            if not f.is_absolute() and pre == "backup:" and (DATA / f).exists():
                f = DATA / f
            if not f.exists():
                return False, None, f"{f} does not exist"
            reg = _read_region(f)
            if reg is False:
                return False, None, f"{f} holds no readable region"
            return reg, region_stamp(reg if reg else DEFAULT_REGION[game]), f"{pre}{f.name}"
    h = use if use.startswith("ocr") else "ocr" + use
    if not re.fullmatch(r"ocr[0-9a-f]{8}", h):
        return False, None, f"'{use}' is not a hash, 'default', 'backup:<file>' or 'file:<path>'"
    if rep["saved_default"] and h == rep["saved_default_hash"]:
        return list(rep["saved_default"]), h, "the saved default region"
    if h == dflt_h:
        return None, h, "the default region"
    if h == rep["current_hash"]:
        return list(rep["current"]), h, "the current region"
    gr = rep["groups"].get(h)
    if gr and gr["region"]:
        return gr["region"], h, f"the region stored in the cached entries of {h}"
    for b, reg in rep["backups"]:
        if reg and region_stamp(reg) == h:
            return reg, h, f"backup {b.name}"
    return False, None, f"no region values are available for hash {h} (its entries do not store the region and no backup matches); nothing changed"


def region_effect(game, stamp):
    """(entries valid under this hash, clips valid, clips of the game's cache that would need a scan)."""
    groups, _ = region_groups(game)
    clips = set()
    for gr in groups.values():
        clips |= gr["clips"]
    mine = groups.get(stamp, {"files": [], "clips": set()})
    return len(mine["files"]), len(mine["clips"]), len(clips - mine["clips"])


def _valid_counts(game, stamp):
    v, _vc, need = region_effect(game, stamp)
    return v, need


def region_apply(game, use):
    """V6.8: the ONE code path behind 'regionrestore --use' and the Settings picker. Saves a dated backup of the current region file, sets
    the region named by `use`, verifies the hash, and returns (ok, [message lines], info). Never starts a scan."""
    reg, h, src = _resolve_region(game, use)
    if reg is False:
        return False, [f"regionrestore: {src}"], {}
    p = DATA / f"detect_{game}.json"
    keep = p.read_bytes() if p.exists() else None
    if reg is None:
        reset_region(game)
    else:
        save_region(game, reg)
    bk = region_backups(game)[-1].name
    new = Detector(game)
    if new.d["stamp"] != h:                                   # the values did not reproduce the hash: put everything back
        if keep is None:
            p.unlink(missing_ok=True)
        else:
            p.write_bytes(keep)
        return False, [f"regionrestore: the region from {src} gives hash {new.d['stamp']}, not {h}; the previous region was put back (backup {bk})"], {"backup": bk}
    valid, vclips, rescan = region_effect(game, h)
    return True, [f"{game} region set to {src}: {new.d['region']} hash {h} (backup of the previous region file: {bk})",
                  f"cached entries valid under this region: {valid}; clips that would need a rescan: {rescan} (their old entries stay on disk)"], \
        {"backup": bk, "hash": h, "valid": valid, "rescan": rescan}


def cmd_regionrestore(args):
    """V6.7.6: python montage.py regionrestore <game> [--use <hash|default|backup:<file>|file:<path>>]. Without --use: options only."""
    game = args.game
    rep = region_report(game)
    if not args.use:
        out(f"== {game}: region options (nothing is chosen for you, nothing was changed) ==")
        out(f"  --use default         {rep['saved_default'] or rep['default']}  hash {rep['saved_default_hash'] or rep['default_hash']}  "
            f"({'saved default' if rep['saved_default'] else 'built-in default'}; {_valid_counts(game, rep['saved_default_hash'] or rep['default_hash'])[0]} cached entries valid)")
        if rep["saved_default"]:
            out(f"  --use builtin         {rep['default']}  hash {rep['default_hash']}  (built-in default; {_valid_counts(game, rep['default_hash'])[0]} cached entries valid)")
        out(f"  (current)             {rep['current']}  hash {rep['current_hash']}  ({_valid_counts(game, rep['current_hash'])[0]} cached entries valid)")
        for b, reg in rep["backups"]:
            if reg is not False:
                h = region_stamp(reg if reg else DEFAULT_REGION[game])
                out(f"  --use backup:{b.name}   {reg if reg else 'default'}  hash {h}  saved {_fmt_t(b.stat().st_mtime)}  ({_valid_counts(game, h)[0]} cached entries valid)")
        for h, gr in sorted(rep["groups"].items(), key=lambda kv: -len(kv[1]["files"])):
            out(f"  --use {h}" + _group_line(h, gr, rep).strip()[len(h):])
            if not gr["region"]:
                out("      (these entries do not store their region: usable only if a backup or --use file:<path> provides the values)")
        out(f"run again with --use <option> to set one. A dated backup of the current region file is saved first.")
        return
    ok, lines, _info = region_apply(game, args.use)
    for ln in lines:
        out(ln)


REGIONTEST_WIDE = [0.50, 0.0, 1.0, 0.45]
REGIONTEST_MUST = ("Replay 2026-06-25 01-27-36.mov", "Counter-strike 2 2025.02.03 - 09.12.42.24.DVR.mp4",
                   "Counter-strike 2 2025.02.04 - 09.46.26.11.DVR.mp4")


def _vdc_order(n):
    """0..n-1 in an evenly spreading order (middle first, then the quarters, ...), so any prefix is spread over the whole list."""
    seen, order, i = set(), [], 0
    while len(order) < n and i < 4096:
        i += 1
        f, b, d = 0.0, 0.5, i
        while d:
            f += (d & 1) * b
            d >>= 1
            b /= 2
        k = min(n - 1, int(f * n))
        if k not in seen:
            seen.add(k)
            order.append(k)
    order += [k for k in range(n) if k not in seen]
    return order


def regiontest_pick(clips, n=15):
    """V6.8: the default clip set of regiontest from [{path, w, h, ...}] (existing CS2 clips): the three named clips (when present), then
    up to three .mov files, then clips spread over every resolution (round robin) up to n."""
    by = {os.path.basename(c["path"]).lower(): c for c in clips}
    sel = []
    for nm in REGIONTEST_MUST:
        c = by.get(nm.lower())
        if c and c not in sel:
            sel.append(c)
    rest = sorted((c for c in clips if c not in sel), key=lambda c: (c.get("w", 0), c.get("h", 0), c.get("mtime", 0), c["path"]))
    mov_all = [c for c in rest if c["path"].lower().endswith(".mov")]
    movs = [mov_all[k] for k in _vdc_order(len(mov_all))]
    for c in movs[:3]:
        if len(sel) < n:
            sel.append(c)
    groups = {}
    for c in rest:
        if c not in sel:
            groups.setdefault((c.get("w"), c.get("h")), []).append(c)
    queues = [[g[k] for k in _vdc_order(len(g))] for _, g in sorted(groups.items(), key=lambda kv: str(kv[0]))]
    while len(sel) < n and any(queues):
        for q in queues:
            if q and len(sel) < n:
                sel.append(q.pop(0))
    return sel


def regiontest_disagree(kill_lists, tol=0.5):
    """V6.8: True when the regions found different kills: another count, or a timestamp more than tol seconds apart."""
    ls = [sorted(k) for k in kill_lists]
    if any(len(x) != len(ls[0]) for x in ls):
        return True
    return any(abs(a - b) > tol for x in ls[1:] for a, b in zip(ls[0], x))


def _safe_name(n):
    return re.sub(r'[^A-Za-z0-9._ -]+', "_", n)[:80].strip(" .")


def cmd_regiontest(args):
    """V6.8: python montage.py regiontest cs2 [--clips <file>] [--regions calibrated,default,wide] [--out <folder>]: the normal CS2 scan of
    clips under several killfeed regions, in a temporary EMPTY data folder (the real montage_data is only read: never used for results,
    never written). Prints one table, saves regiontest_cs2.txt and regiontest_images\\<clip>_<region>.png."""
    game = args.game
    busy = job_active()
    if busy:
        out(f"regiontest: {busy} is running - refusing to start (finish or cancel it first)")
        raise SystemExit(1)
    import cv2
    import tempfile
    out_dir = Path(args.out) if getattr(args, "out", None) else HERE
    # --- read-only look at the real data
    real_cfg = load_json(CONFIG_PATH, {}) or {}
    real_clips = load_json(CLIPS_CACHE, {}) or {}
    cur_region = list(Detector(game).d["region"])
    avail = {"calibrated": cur_region, "default": list(DEFAULT_REGION[game]), "wide": list(REGIONTEST_WIDE)}
    names = [x.strip() for x in (args.regions or "calibrated,default,wide").split(",") if x.strip()]
    bad = [x for x in names if x not in avail]
    if bad:
        out(f"regiontest: unknown region {bad} (use calibrated, default, wide)")
        raise SystemExit(2)
    regions = [(x, avail[x]) for x in names]
    tmp = Path(tempfile.mkdtemp(prefix="regiontest_"))
    old = use_data_dir(tmp)
    try:
        save_json(CONFIG_PATH, real_cfg)
        cfg = load_config()
        recs = [dict(v) for v in real_clips.values() if isinstance(v, dict) and v.get("path") and not v.get("error") and v.get("w")]
        for r in recs:
            r["game"] = tag_game(r["path"], cfg)[0]
        recs = [r for r in recs if r["game"] == game and os.path.exists(r["path"])]
        if args.clips:
            wanted = [x.strip() for x in Path(args.clips).read_text(encoding="utf-8-sig").splitlines() if x.strip() and not x.strip().startswith("#")]
            byname = {os.path.basename(r["path"]).lower(): r for r in recs}
            sel, unknown = [], []
            for w in wanted:
                r = byname.get(os.path.basename(w).lower())
                if r is None and os.path.isfile(w):
                    r = dict(analyse_clip(w, {}, False, cfg.get("bar"))[1], game=game)
                (sel.append(r) if r else unknown.append(w))
        else:
            sel, unknown = regiontest_pick(recs, 15), []
            sel_names = {os.path.basename(c["path"]).lower() for c in sel}
            unknown = [m for m in REGIONTEST_MUST if m.lower() not in sel_names]
        for u in unknown:
            out(f"regiontest: unknown clip '{u}' (not in the clip cache / not found): skipped")
        if not sel:
            out("regiontest: no clips to test")
            raise SystemExit(1)
        out(f"regiontest {game}: {len(sel)} clips x {len(regions)} regions ({', '.join(f'{n} {r} {region_stamp(r)}' for n, r in regions)}), temporary data folder {tmp}")
        ocr_engine()
        img_dir = out_dir / "regiontest_images"
        img_dir.mkdir(parents=True, exist_ok=True)
        results, lines = [], []
        for ci, rec in enumerate(sel, 1):
            t_clip = time.time()
            per = {}
            for rn, reg in regions:
                save_json(DATA / f"detect_{game}.json", {"region": reg, "ocr": True})
                det = Detector(game)
                res = scan_clip(rec["path"], rec, det, cfg)
                a = analyse_entry(res, cfg, game)
                per[rn] = {"kills": [round(k["t"], 1) for k in a["kills"]], "rows": a["rows_max"], "rej": len(a["rej"])}
                if res.get("ocr"):
                    busiest = max(res["ocr"], key=lambda o: len(o[2]))
                    fr, _rows = grab_kill_crop(rec, det, cfg, {"t": busiest[0] / FPS - 0.3 + res.get("v_off", 0.0)})
                    if fr is not None:
                        cv2.imwrite(str(img_dir / f"{_safe_name(Path(rec['path']).stem)}_{rn}.png"), fr)
            secs = time.time() - t_clip
            dis = regiontest_disagree([v["kills"] for v in per.values()]) if len(per) > 1 else False
            results.append({"clip": os.path.basename(rec["path"]), "res": f"{rec.get('w')}x{rec.get('h')}", "per": per, "disagree": dis, "secs": secs})
            out(f"[{ci}/{len(sel)}] {os.path.basename(rec['path'])}  {secs:.0f} s")
        head = f"{'clip':50s} {'res':>9s}  " + "  ".join(f"{rn + ' (kills/rows/rej  times)':<58s}" for rn, _ in regions) + "  sec"
        lines.append(f"REGIONTEST {game} - regions: " + "; ".join(f"{n} {r} {region_stamp(r)}" for n, r in regions))
        lines.append(head)
        for r in results:
            cells = []
            for rn, _ in regions:
                v = r["per"][rn]
                cells.append(f"{len(v['kills'])}/{v['rows']}/{v['rej']}  {' '.join(ts(t) for t in v['kills']) or '-'}".ljust(58))
            lines.append(f"{r['clip'][:50]:50s} {r['res']:>9s}  " + "  ".join(cells) + f"  {r['secs']:.0f}" + ("   <-- REGIONS DISAGREE" if r["disagree"] else ""))
        nd = sum(1 for r in results if r["disagree"])
        lines.append(f"{nd} of {len(results)} clips where the regions disagree. Total time {sum(r['secs'] for r in results):.0f} s "
                     f"({sum(r['secs'] for r in results) / len(results):.0f} s per clip, {len(regions)} regions each).")
        txt = "\n".join(lines)
        (out_dir / f"regiontest_{game}.txt").write_text(txt + "\n", encoding="utf-8")
        for ln in lines:
            out(ln)
        out(f"saved {out_dir / ('regiontest_' + game + '.txt')} and the cropped images in {img_dir}")
        return results
    finally:
        restore_data_dir(old)
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_regiondefault(args):
    """V6.8: python montage.py regiondefault <game> <hash|current>: saves that region as the game's saved default (region_defaults.json)."""
    if args.target == "current":
        reg, h, src = list(Detector(args.game).d["region"]), Detector(args.game).d["stamp"], "the current region"
    else:
        reg, h, src = _resolve_region(args.game, args.target)
        if reg is False:
            out(f"regiondefault: {src}")
            return
        if reg is None:
            reg = list(DEFAULT_REGION[args.game])
    set_saved_default(args.game, reg)
    out(f"{args.game}: saved default region set to {reg} (hash {region_stamp(reg)}) from {src}; 'Reset to default' and '--use default' now use it. The current region is unchanged.")


def _hash_arg(h):
    h = str(h or "").strip().lower()
    return h if h.startswith("ocr") else "ocr" + h


def _entry_key(p):
    """The cache key stored at the start of a kill-entry file (the OCR payload is not loaded)."""
    with open(p, "rb") as f:
        head = f.read(3000).decode("utf-8", "ignore")
    return json.loads('"' + re.match(r'\{"key": "((?:[^"\\]|\\.)*)"', head).group(1) + '"')


def rescan_group_clips(game, h_old, cfg=None):
    """V6.8.1: the clips of a game that have a kill entry under region hash `h_old` and NO entry under the current region, found by
    their file (name, size, time) in the clip folders of Settings. Returns {"current", "recs", "old_keys" {path: key under h_old},
    "missing" (clips with an old entry whose file is no longer in the folders), "have_current" (already scanned under the current region)}."""
    cfg = cfg or load_config()
    cur = Detector(game).d["stamp"]
    det = Detector(game)
    store = load_kills_cache()
    idx = _cache_index()
    old, has_cur = {}, set()
    for (name, size, mt, g), lst in idx.items():
        if g != game:
            continue
        if any(e[3] == cur and e[4] == ALGO[1:] for e in lst):
            has_cur.add((name, size, mt))
        olds = [e for e in lst if e[3] == h_old and e[4] == ALGO[1:]]
        if olds:
            old[(name, size, mt)] = olds
    recs, old_keys, found = [], {}, set()
    for r in scan_clips(cfg):
        if r.get("error") or not r.get("w") or r.get("game") != game:
            continue
        try:
            path, size, mt = file_key(r["path"]).split("|")[:3]
        except OSError:
            continue
        k3 = (os.path.basename(path).lower(), size, mt)
        if k3 not in old:
            continue
        found.add(k3)
        if k3 in has_cur or kills_key(r, game, det) in store:
            continue
        recs.append(r)
        try:
            old_keys[r["path"]] = _entry_key(old[k3][0][0])
        except Exception:
            old_keys[r["path"]] = None
    return {"current": cur, "recs": recs, "old_keys": old_keys, "missing": len(set(old) - found), "have_current": len(found & has_cur)}


def rescan_group(game, h_old, cfg=None, info=None):
    """V6.8.1: scan ONLY the clips of rescan_group_clips() under the current region and ADD their entries (old entries are never deleted
    or overwritten). Valorant: the old entry is first copied into valorant_cache_backup.json (first copy per clip only); the caller has
    asked the user, which counts as the explicit confirmation. Cancel = CANCEL: clips already scanned keep their new entries."""
    cfg = cfg or load_config()
    info = info or rescan_group_clips(game, h_old, cfg)
    if not info["recs"]:
        out(f"rescan {h_old}: no clips to scan")
        return 0
    if game == "valorant":
        store = load_kills_cache()
        nb = sum(bool(info["old_keys"].get(r["path"]) and backup_valorant_entry(store, info["old_keys"][r["path"]])) for r in info["recs"])
        out(f"Valorant: {nb} old entries copied into valorant_cache_backup.json before the rescan")
    out(f"rescanning {len(info['recs'])} clips from {h_old} to the current region {info['current']} (old entries stay)")
    return run_scan(cfg, [game], [r["path"] for r in info["recs"]], 0, False, True)


def cmd_rescanhash(args):
    """V6.8.1: python montage.py rescanhash <game> <hash> [--confirm]. Without --confirm it only prints the clips and the count."""
    game, h = args.game, _hash_arg(args.hash)
    cfg = load_config()
    info = rescan_group_clips(game, h, cfg)
    n = len(info["recs"])
    if h == info["current"]:
        out(f"rescanhash: {h} is the current {game} region - nothing to do")
        return
    for r in info["recs"]:
        out(f"  {Path(r['path']).name}")
    extra = (f"; {info['missing']} clip(s) with an entry under {h} are not in the clip folders any more" if info["missing"] else "") + \
            (f"; {info['have_current']} already have an entry under the current region" if info["have_current"] else "")
    out(f"{n} {game} clips have an entry under {h} and none under the current region {info['current']}{extra}")
    if not args.confirm:
        out("Nothing was changed. Add --confirm to rescan these clips under the current region (old entries stay).")
        return
    if job_active():
        out(f"rescanhash: refused, {job_active()} is running")
        return
    out(f"Rescan {n} clips from {h} to the current region {info['current']}: --confirm given")
    rescan_group(game, h, cfg, info)


def region_options(game):
    """V6.8: every saved region of a game, as rows for the Settings picker (the data regioncheck prints): current, built-in default,
    saved default, dated backups, and each hash found in the cached entries."""
    rep = region_report(game)
    groups = rep["groups"]

    def row(kind, label, reg, h, use):
        gr = groups.get(h)
        t = gr["times"] if gr else []
        return {"kind": kind, "label": label, "region": reg, "hash": h, "use": use, "entries": len(gr["files"]) if gr else 0,
                "first": _fmt_t(min(t)) if t else "", "last": _fmt_t(max(t)) if t else ""}
    rows = [row("current", "current" + ("" if rep["calibrated"] else " (default)"), list(rep["current"]), rep["current_hash"], rep["current_hash"]),
            row("built-in default", "built-in default", list(rep["default"]), rep["default_hash"], "builtin")]
    if rep["saved_default"]:
        rows.append(row("saved default", "saved default", list(rep["saved_default"]), rep["saved_default_hash"], "default"))
    for b, reg in rep["backups"]:
        if reg is not False:
            r_ = reg if reg else list(DEFAULT_REGION[game])
            rows.append(row("backup", f"backup {b.name}", r_, region_stamp(r_), f"backup:{b.name}"))
    shown = {r["hash"] for r in rows}
    for h, gr in sorted(groups.items(), key=lambda kv: -len(kv[1]["files"])):
        if h not in shown:
            rows.append(row("cache", "cached entries", gr["region"], h, h))
    for r in rows:
        if r["kind"] == "cache":
            r["usable"] = _resolve_region(game, r["use"])[0] is not False
        else:
            r["usable"] = True
    return rows


def save_region(game, region_frac):
    """Optional calibration = only the killfeed REGION (fractions of the content rect). Other keys of an older file are kept."""
    x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in region_frac)
    if x1 - x0 < 0.05 or y1 - y0 < 0.03:
        raise ValueError("killfeed box too small")
    p = DATA / f"detect_{game}.json"
    d = load_json(p, {}) or {}
    backup_region_file(game)
    d["region"] = [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]
    d["ocr"] = True
    save_json(p, d)
    return d["region"]


def reset_region(game):
    p = DATA / f"detect_{game}.json"
    d = load_json(p, {}) or {}
    backup_region_file(game)
    d.pop("region", None)
    save_json(p, d)


def test_frame(game, img, cfg=None):
    """OCR one 1920x1080 normalised frame's killfeed: rows found + verdict per row (Calibrate / Self-test / crop view)."""
    det = Detector(game)
    boxes, blobs = ocr_frame(det.crop_norm(img).copy())
    rows = ocr_rows(boxes, blobs, game)
    return rows, boxes, blobs


def do_calibrate(game, img, region, row=None, name=None, hs=None, expand=True):
    """img: 1920x1080 normalised screenshot/frame. region: absolute x,y,w,h of the killfeed area in that space.
    (row/name/hs are accepted for old callers and ignored: OCR needs no name template.)"""
    rx, ry, rw, rh = region
    reg = save_region(game, (rx / NORM_W, ry / NORM_H, (rx + rw) / NORM_W, (ry + rh) / NORM_H))
    rows, boxes, _ = test_frame(game, img)
    kills = [r for r in rows if any(v == "kill" for v, _ in classify_row(r))]
    out(f"{game} killfeed region saved {reg}. OCR on this frame: {len(boxes)} text boxes, {len(rows)} rows, {len(kills)} FIREAXE kill row(s)")
    for r in rows:
        out("   " + row_desc(r))
    return {"hits": len(kills), "rows": len(rows), "name": max([r["ks"] / 100 for r in rows], default=0)}


def cmd_calibrate(args):
    cfg = load_config()
    img = norm_image(read_img(args.screenshot), cfg)
    if args.region:
        region = tuple(int(float(v)) for v in args.region.split(","))
    else:
        out(f"Calibrating {args.game}: drag a box around the whole killfeed area (the GUI Calibrate button is easier).")
        region = pick_roi(img, "drag a box around the WHOLE killfeed area (generous)")
    try:
        do_calibrate(args.game, img, region)
    except ValueError as ex:
        raise SystemExit(str(ex))


# ------------------------------------------------------------------- scan
def auto_scan_set(cfg, game):
    """Auto mode: uncached clips from the last N days, plus up to M older uncached ones per run (newest first)."""
    det = load_dets(game).get(game)
    if not det:
        return []
    cache = load_kills_cache()
    now = time.time()
    new, old = [], []
    for r in scan_clips(cfg):
        if r.get("game") != game or r.get("error") or not r.get("w") or kills_key(r, game, det) in cache:
            continue
        try:
            m = os.path.getmtime(r["path"])
        except OSError:
            continue
        (new if now - m <= cfg.get("auto_recent_days", 30) * 86400 else old).append((m, r["path"]))
    old.sort(reverse=True)
    return [p for _, p in new] + [p for _, p in old[:int(cfg.get("auto_old_per_run", 150))]]


@with_job("scan")
def run_scan(cfg, games=None, paths=None, limit=0, rescan=False, region_ok=False):
    """Scans only what is needed (paths) - or every uncached tagged clip if paths is None. Returns clips scanned."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found - open Troubleshoot > Selfcheck")
    ensure_bars(cfg)
    dets = load_dets()
    if games:
        dets = {g: d for g, d in dets.items() if g in games}
    if not dets:
        raise RuntimeError("OCR detector unavailable (Troubleshoot > Selfcheck lists what is missing)")
    recs = [r for r in scan_clips(cfg) if not r.get("error") and r.get("w") and r.get("game") in dets]
    if paths is not None:
        ps = set(paths)
        recs = [r for r in recs if r["path"] in ps]
    cache = load_kills_cache()
    jobs = [(r, r["game"]) for r in recs if rescan or kills_key(r, r["game"], dets[r["game"]]) not in cache]
    if jobs and rescan:
        out("rescanning: forced rescan (requested)")
    elif jobs:
        jobs = _relink_or_explain(jobs, dets, cache, cfg, region_ok)
    if limit:
        jobs = jobs[:limit]
    out(f"cached {len(recs) - len(jobs)}, scanning {len(jobs)}  (of {len(recs)} clips in scope)")
    if jobs:
        ocr_engine()                                       # load the OCR models once up front (clear error if missing)
    done, errs, t0 = 0, 0, time.time()

    def work(job):
        r, g = job
        if CANCEL.is_set():
            return r, g, None, "cancelled"
        try:
            res = scan_clip(r["path"], r, dets[g], cfg)
            if CANCEL.is_set():
                return r, g, None, "cancelled"             # half-scanned clips are never cached
            if g == "valorant":
                backup_valorant_entry(cache, kills_key(r, g, dets[g]))      # V6.7.6: an entry about to be overwritten is copied first
            cache.put(kills_key(r, g, dets[g]), res)           # saved the moment this clip finishes
            if g == "cs2" and not CANCEL.is_set():             # V6.8.1: the red-border sidecar of this clip (separate cache; failure keeps the name-based list)
                try:
                    if border_load(r, dets[g]) is None:
                        border_build(r, dets[g], cfg)
                except Exception as ex:
                    BORDER_FAILED.add(r["path"])
                    LOGONLY(f"CS2 row borders: {Path(r['path']).name}: {ex}")
            return r, g, res, None
        except Exception as ex:
            return r, g, None, f"{type(ex).__name__}: {ex}"
    with ThreadPoolExecutor(max_workers=int(cfg.get("scan_workers", 2))) as ex:
        for r, g, res, err in ex.map(work, jobs):
            done += 1
            progress(done / max(1, len(jobs)), f"scanning kills {done}/{len(jobs)}")
            if err == "cancelled":
                continue
            name = Path(r["path"]).name
            if err:
                errs += 1
                out(f"[{done}/{len(jobs)}] {g:8} ERROR {name}: {err}")
            else:
                a = analyse_clip_entry(r, res, cfg, g)
                out(f"[{done}/{len(jobs)}] {g:8} {len(a['kills'])} kills {' '.join(ts(k['t']) for k in a['kills']) or '-'}"
                    f" | rows found {a['rows_max']} max/frame, {a['ocr_calls']} OCR calls | best name killer-side {a['best_k']:.2f},"
                    f" victim-side {a['best_v']:.2f} | rect {content_rect(r, cfg)} crop {'yes' if r.get('bars') else 'no'} | {name} ({res['secs']}s)")
                for m in a["mine"]:
                    out(f"      my row @ {ts(m['t'])} {m['row']} -> {m['verdict'].upper()}: {m['why']} ({m['hits']} sightings)")
    out(f"scan finished: {done} in {time.time() - t0:.0f}s, errors {errs}")
    return done


def cmd_scan(args):
    run_scan(load_config(), [args.game] if args.game else None, None, args.limit, args.rescan, getattr(args, "confirm_region_rescan", False))


def game_pool(cfg, game, paths=None):
    """([{rec, kills, deaths, vis}], stats): same analyse_entry as the crop view / Self-test, then the soft audio + death-lock
    step. Every rejected row is logged with its reason."""
    det = load_dets(game).get(game)
    if not det:
        raise RuntimeError("OCR detector unavailable: Troubleshoot > Selfcheck (pip install rapidocr-onnxruntime)")
    cache = load_kills_cache()
    exc = []
    try:
        exc = [l.strip().lower() for l in (DATA / "exclude.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        pass
    ps = set(paths) if paths is not None else None
    stats = {"tagged": 0, "scanned": 0, "with_kills": 0}
    pool, allrej, cjk = [], [], {}
    cands = []
    for r in scan_clips(cfg):
        if r.get("error") or not r.get("w") or r.get("game") != game or (ps is not None and r["path"] not in ps):
            continue
        if any(x in r["path"].lower() for x in exc):
            continue
        stats["tagged"] += 1
        e = cache.get(kills_key(r, game, det))
        if not e or e.get("error"):
            continue
        cands.append((r, e))
    if game == "cs2" and cands:                            # V6.8.1: red-border row sidecars, built once per clip when missing
        try:
            border_build_many([r for r, _ in cands], cfg, det)
        except Exception as ex:
            out(f"CS2 row borders: {type(ex).__name__}: {ex} - name-based kills used where a sidecar is missing")
    for r, e in cands:
        stats["scanned"] += 1
        a = analyse_clip_entry(r, e, cfg, game)
        for k_, v_ in a.get("cjk", {}).items():
            cjk[k_] = cjk.get(k_, 0) + v_
        for j in a["rej"]:
            allrej.append((Path(r["path"]).name, j))
        if a["kills"]:
            pool.append({"rec": r, "kills": a["kills"], "deaths": a["deaths"], "revives": a["revives"], "vis": a["vis"], "rej": []})
    stats["with_kills"] = len(pool)
    if game == "cs2":
        stats["cjk"] = cjk
        out(f"CS2 name '{MY_NAME_CS2}': {sum(cjk.values())} rows recovered that 'fireaxe' alone missed"
            + (" (" + ", ".join(f"{v} {k}" for k, v in sorted(cjk.items())) + ")" if cjk else ""))
    stats["audio"] = verified_kills(pool, cfg) if pool else {"raw": 0, "no_shot": 0, "death_lock": 0, "kept": 0}
    for it in pool:
        nm = Path(it["rec"]["path"]).name
        allrej += [(nm, j) for j in it["rej"]]
    reasons = {}
    for nm, j in allrej:
        key = j["reason"].split(":")[0].split("(")[0].strip()
        reasons[key] = reasons.get(key, 0) + 1
    stats["rejected"] = reasons
    if allrej:
        out(f"REJECTED ROWS in {game}: " + ", ".join(f"{k}: {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])))
        for nm, j in allrej[:80]:
            out(f"   {nm} @ {ts(j['t'])}  name {j['ks']:.2f}  -> {j['reason']}")
        if len(allrej) > 80:
            out(f"   ... {len(allrej) - 80} more (see montage_data\\logs\\montage.log)")
            for nm, j in allrej[80:]:
                LOGONLY(f"   {nm} @ {ts(j['t'])}  name {j['ks']:.2f}  -> {j['reason']}")
    pool = [it for it in pool if it["kills"]]
    return pool, stats


def draw_rows(fr, rows):
    """Label every OCR row on a killfeed crop with the SAME classify_row() verdict the scanner uses."""
    import cv2
    for d in rows:
        verdicts = [x[0] for x in classify_row(d)]
        col = (0, 200, 0) if "kill" in verdicts else (0, 0, 255) if "death" in verdicts else \
            (0, 140, 255) if "reject" in verdicts else (160, 160, 160)
        for b in d["boxes"]:
            cv2.rectangle(fr, (b[0], b[1]), (b[2], b[3]), col, 2 if col != (160, 160, 160) else 1)
        if d["icon"]:
            x, y, w, h = d["icon"][:4]
            cv2.rectangle(fr, (x, y), (x + w, y + h), (255, 200, 0) if d["gun"] else (200, 0, 200), 1)
        cv2.putText(fr, row_desc(d)[:90], (4, max(10, d["y0"] - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1, cv2.LINE_AA)
    return fr


def grab_kill_crop(rec, det, cfg, k, scale=None):
    """Killfeed crop at a kill: live OCR, every row boxed and labelled with its verdict and reason. Returns (image, rows)."""
    import numpy as np
    vf = region_filter(rec, det, cfg)
    t = k["t"] - rec.get("v_off", 0.0) + 0.3
    r = run(["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", rec["path"], "-frames:v", "1", "-vf", vf,
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], timeout=60)
    n = det.dw * det.dh * 3
    if len(r.stdout) < n:
        return None, []
    fr = np.frombuffer(r.stdout[:n], np.uint8).reshape(det.dh, det.dw, 3).copy()
    boxes, blobs = ocr_frame(fr)
    rows = ocr_rows(boxes, blobs, rec.get("game"))
    draw_rows(fr, rows)
    import cv2
    cv2.putText(fr, f"{Path(rec['path']).name[-28:]} t={ts(k['t'])}" + (" HS" if k.get("hs") else ""),
                (4, det.dh - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    return fr, rows


def cmd_verify(args):
    import cv2
    import numpy as np
    cfg = load_config()
    det = load_dets(args.game).get(args.game)
    if not det:
        raise SystemExit("OCR detector unavailable")
    cache = load_kills_cache()
    items = []
    for r in scan_clips(cfg):
        e = cache.get(kills_key(r, args.game, det)) if r.get("game") == args.game and not r.get("error") else None
        if e and not e.get("error"):
            ks, _ = compute_kills(e, cfg, args.game)
            if ks:
                items.append((r, e, ks))
    if not items:
        raise SystemExit("no cached kills yet: run scan first")
    tiles = []
    for rec, e, ks in items[::max(1, len(items) // 6)][:6]:
        fr, _ = grab_kill_crop(rec, det, cfg, ks[0])
        if fr is not None:
            tiles.append(cv2.resize(fr, (480, max(1, int(480 * det.dh / det.dw)))))
    if not tiles:
        raise SystemExit("could not grab frames")
    h = max(t.shape[0] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 0, cv2.BORDER_CONSTANT) for t in tiles]
    while len(tiles) % 3:
        tiles.append(np.zeros_like(tiles[0]))
    sheet = np.vstack([np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)])
    p = DATA / f"verify_{args.game}.jpg"
    cv2.imencode(".jpg", sheet)[1].tofile(str(p))
    out(f"wrote {p}")


def synth_row_frame(left="fireaxe", right="enemy", w=720, h=360, y=120, icon_w=80, extra=()):
    """Generated killfeed crop: '<left> [white weapon icon] <right>' on a dark row (used by Self-test and smoketest).
    An extra row (y, (left, right, icon_w)) gets its own icon width (22 = square ability icon)."""
    import cv2
    import numpy as np
    img = np.full((h, w, 3), (70, 78, 86), np.uint8)
    for yy, (l2, r2, *iw_) in [(y, (left, right, icon_w))] + list(extra):
        icon_w = iw_[0] if iw_ else 80
        f, sc, th = cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2
        lw = cv2.getTextSize(l2, f, sc, th)[0][0]
        rw = cv2.getTextSize(r2, f, sc, th)[0][0]
        x0 = w - 24 - (lw + 20 + icon_w + 20 + rw)
        cv2.rectangle(img, (x0 - 10, yy - 28), (w - 12, yy + 10), (28, 28, 30), -1)
        cv2.putText(img, l2, (x0, yy), f, sc, (255, 255, 255), th, cv2.LINE_AA)
        ix = x0 + lw + 20
        cv2.rectangle(img, (ix, yy - 20), (ix + icon_w, yy + 2), (255, 255, 255), -1)
        cv2.putText(img, r2, (ix + icon_w + 20, yy), f, sc, (255, 255, 255), th, cv2.LINE_AA)
    return img


def ocr_synthetic_test(verbose=True):
    """Generated frames through the real OCR -> rows -> classify_row path AND the scan/track path.
    Expect: 'fireaxe [gun] enemy' = exactly 1 KILL, 'enemy [gun] fireaxe' = exactly 1 DEATH. Returns list of failures."""
    import numpy as np
    fails = []
    for left, right, want in (("fireaxe", "enemy", "kill"), ("enemy", "fireaxe", "death")):
        img = synth_row_frame(left, right)
        rows = ocr_rows(*ocr_frame(img))
        vs = [v for r in rows for v, _ in classify_row(r)]
        if verbose:
            for r in rows:
                out(f"  synthetic '{left} | {right}': " + row_desc(r))
        if vs.count(want) != 1 or len([v for v in vs if v in ("kill", "death")]) != 1:
            fails.append(f"single frame '{left} [icon] {right}': expected exactly one {want.upper()}, got {vs}")
        blank = np.full_like(img, (70, 78, 86))
        frames = [blank] * 12 + [img] * 40
        ocr, n = scan_frames(iter(frames))
        a = analyse_entry({"ocr": ocr, "frames": n, "v_off": 0.0}, {})
        got = len(a["kills"]) if want == "kill" else len(a["deaths"])
        other = len(a["deaths"]) if want == "kill" else len(a["kills"])
        t_ok = abs((a["kills"][0]["t"] if want == "kill" and a["kills"] else a["deaths"][0] if a["deaths"] else -1) - 12 / FPS) <= 1.5 / FPS
        if verbose:
            out(f"  synthetic clip '{left} | {right}': {len(ocr)} OCR calls for {n} frames, kills {[k['t'] for k in a['kills']]},"
                f" deaths {a['deaths']} (row appears at {12 / FPS:.3f}s)")
        if got != 1 or other != 0 or not t_ok:
            fails.append(f"scanned clip '{left} [icon] {right}': expected one {want.upper()} at {12 / FPS:.3f}s, got kills "
                         f"{[k['t'] for k in a['kills']]} deaths {a['deaths']}")
    for left, right, want in (("enemy + fireaxe", "victim", "reject"), ("fireaxe", "", "reject")):
        if not right:
            continue
        rows = ocr_rows(*ocr_frame(synth_row_frame(left, right)))
        vs = [v for r in rows for v, _ in classify_row(r)]
        if verbose:
            for r in rows:
                out(f"  synthetic '{left} | {right}': " + row_desc(r))
        if "kill" in vs:
            fails.append(f"assist row '{left} [icon] {right}' was counted as a KILL")
    return fails


def detection_regression(cfg=None, dirs=None, verbose=True):
    """Re-runs the classification on ALL cached OCR data with the frozen V4 rules and the current rules. No clip may lose a kill
    that V4 saw with 2+ sightings and a name score of 86+. Prints a before/after kill-count table. Returns (rows, lost)."""
    cfg = cfg or load_config()
    files = []
    for d in (dirs or [KillStore().dir]):
        files += sorted(Path(d).glob("*.json"))
    rows, lost = [], []
    for fp in files:
        try:
            j = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        e = j.get("e") or {}
        if not e.get("ocr"):
            continue
        name = Path(j.get("key", fp.name).split("|")[0]).name
        g_ = (j.get("key", "").split("|") + ["", ""])[1] or None
        a4, a5 = _analyse_entry_v4(e, cfg), analyse_entry(e, cfg, g_)
        from rapidfuzz.distance import Levenshtein
        must = [k for k in a4["kills"] if k.get("hits", 0) >= 2 and k["ks"] >= 0.86]
        vic = lambda row: _alnum(row.rsplit("[", 1)[-1].rstrip("]").lower())

        def kept(k):
            for k5 in a5["kills"]:
                if abs(k["t"] - k5["t"]) <= 0.3:
                    return True
                a_, b_ = vic(k["row"]), _alnum((k5.get("victim") or "").lower())
                if abs(k["t"] - k5["t"]) <= 1.5 and a_ and b_ and len(a_) == len(b_) and Levenshtein.distance(a_, b_) <= 1:
                    return True                          # merged OCR variant of the same row
            for k4 in a4["kills"]:                         # V4 counted one row twice (name unreadable at first, read later)
                if k4 is not k and 0 < k["t"] - k4["t"] <= TRACK_KEEP_S and not vic(k4["row"]) and \
                        any(abs(k4["t"] - k5["t"]) <= 0.3 for k5 in a5["kills"]):
                    return True
            return False
        miss = [k for k in must if not kept(k)]
        rows.append((name, len(a4["kills"]), len(a5["kills"]), len(must), len(miss)))
        lost += [(name, k["t"], k["row"]) for k in miss]
    if verbose:
        out("DETECTION REGRESSION (cached OCR data, V4 rules vs V5 rules)")
        out(f"  {'clip':44} {'V4 kills':>8} {'V5 kills':>8} {'V4 2+ seen & >=86':>18} {'lost':>5}")
        for r in rows:
            out(f"  {r[0][-44:]:44} {r[1]:8d} {r[2]:8d} {r[3]:18d} {r[4]:5d}")
        out(f"  total: V4 {sum(r[1] for r in rows)} kills, V5 {sum(r[2] for r in rows)} kills, {len(lost)} protected kill(s) lost"
            + ("" if not lost else ": " + "; ".join(f"{n} @ {ts(t)} {row}" for n, t, row in lost)))
    return rows, lost


def cmd_detectcheck(args):
    rows, lost = detection_regression()
    if lost:
        sys.exit(1)


def selftest_detection(cfg, per_game=20):
    """Same analyse_entry as Dry plan / Render. OCR engine check on generated frames, then per game: clips, zero-kill clips,
    name-score histograms, rejected rows by reason, and the OCR text + verdict of my rows."""
    out("== OCR engine check (generated frames) ==")
    try:
        fails = ocr_synthetic_test()
        out("  OK: 'fireaxe [gun] enemy' = 1 KILL, 'enemy [gun] fireaxe' = 1 DEATH" if not fails else "  FAIL: " + "; ".join(fails))
    except Exception as ex:
        out(f"  OCR not working: {ex}")
        return
    cache = load_kills_cache()
    shown = False
    for g in GAMES:
        det = load_dets(g).get(g)
        if not det:
            continue
        out(f"== {g}: killfeed region {det.d['region']} ({'calibrated' if det.calibrated else 'default top-right'}) ==")
        items = []
        for r in scan_clips(cfg):
            e = cache.get(kills_key(r, g, det)) if r.get("game") == g and not r.get("error") else None
            if e and not e.get("error"):
                items.append((r, e))
        if not items:
            out(f"{g}: no scanned clips yet (scan a few first)")
            continue
        shown = True
        sample = items[::max(1, len(items) // per_game)][:per_game]
        zero, kh, vh, reasons, nk = 0, [0] * 11, [0] * 11, {}, 0
        for r, e in items:
            a = analyse_entry(e, cfg, g)
            zero += 0 if a["kills"] else 1
            nk += len(a["kills"])
            kh[min(10, int(a["best_k"] * 10))] += 1
            vh[min(10, int(a["best_v"] * 10))] += 1
            for j in a["rej"]:
                key = j["reason"].split(":")[0].split("(")[0].strip()
                reasons[key] = reasons.get(key, 0) + 1
        out(f"  {len(items)} clips scanned, {zero} with 0 kills, {nk} kills in total (FIREAXE fuzzy match >= {NAME_MIN})")
        bins = "  ".join(f"{i / 10:.1f}:{n}" for i, n in enumerate(kh) if n)
        out(f"  best killer-side FIREAXE match per clip (bin:clips): {bins or '-'}")
        bins = "  ".join(f"{i / 10:.1f}:{n}" for i, n in enumerate(vh) if n)
        out(f"  best victim-side FIREAXE match per clip (bin:clips): {bins or '-'}")
        out("  rows rejected by reason: " + (", ".join(f"{k}: {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])) or "none"))
        for r, e in sample:
            a = analyse_entry(e, cfg, g)
            out(f"  {len(a['kills'])} kills, {len(a['deaths'])} deaths | rows found {a['rows_max']} max/frame, {a['ocr_calls']} OCR calls"
                f" | killer {a['best_k']:.2f} victim {a['best_v']:.2f} | {Path(r['path']).name}")
            for m in a["mine"]:
                out(f"      my row @ {ts(m['t'])} {m['row']} -> {m['verdict'].upper()}: {m['why']}")
    if not shown:
        out("no scanned clips yet")
    else:
        detection_regression(cfg)


# ======================================================================= SONGS
SONG_CACHE = DATA / "song_cache.json"
USED_CLIPS = DATA / "used_clips.json"
USED_FLAGS = DATA / "used_flags.json"      # V5.55 (GUI): {clip path: date of the montage it was used in}
USED_TITLES = DATA / "used_titles.json"    # V6.7.4: {clip path key: {"date", "title"}} the montage a flag came from (title "" = flagged by hand)
USED_SONGS = DATA / "used_songs.json"
SONG_ALGO = "s3"


def autodetect_dirs(cfg):
    """Fill mp3_dir / playlist_dir from the CLAUDECODE folder if the config points nowhere useful."""
    base, changed = HERE.parent, False
    if not (cfg.get("mp3_dir") and os.path.isdir(cfg["mp3_dir"])):
        best = (0, None)
        for root, dirs, files in os.walk(base):
            if Path(root).name.lower() in ("montage_data", ".git") or len(Path(root).parts) - len(base.parts) > 3:
                dirs[:] = []
                continue
            n = sum(1 for f in files if os.path.splitext(f)[1].lower() in AUDIO_EXT)
            if n > best[0]:
                best = (n, root)
        if best[1]:
            cfg["mp3_dir"], changed = best[1], True
    if not newest_csv(cfg):
        newest = None
        for root, dirs, files in os.walk(base):
            if Path(root).name.lower() in (".git",) or len(Path(root).parts) - len(base.parts) > 3:
                dirs[:] = []
                continue
            for f in files:
                if f.lower().endswith(".csv"):
                    pth = Path(root) / f
                    if newest is None or pth.stat().st_mtime > newest.stat().st_mtime:
                        newest = pth
        if newest:
            cfg["playlist_dir"], changed = str(newest.parent), True
    if changed:
        save_json(CONFIG_PATH, cfg)
        out(f"auto-detected folders: mp3={cfg['mp3_dir']}  csv={cfg['playlist_dir']}")
    return cfg


SONG_SR = 22050
SONGMAP_V = "map2"


def decode_mono(path, sr=SONG_SR):
    """Mono float32 samples. Sample 0 = the first DECODED sample (ffmpeg already skipped the MP3 encoder delay); the render
    uses the same origin (asetpts=N/SR/TB), so beat times are exact in the final mix."""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-af", f"aresample={sr},asetpts=N/SR/TB",
                        "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, timeout=300)
    return np.frombuffer(r.stdout, np.float32), sr


def smooth(a, w):
    import numpy as np
    w = max(1, int(w))
    return np.convolve(a, np.ones(w) / w, mode="same")


def ebur128_lufs(path, stream=None):
    """Integrated loudness (LUFS) of a file / audio stream, or None."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", path] + (["-map", f"0:a:{stream}"] if stream is not None else ["-vn"]) + \
          ["-af", "ebur128=framelog=quiet", "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        txt = r.stderr.decode(errors="replace")
        m = re.findall(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", txt)
        if m and m[-1] != "-inf":
            v = float(m[-1])
            return v if v > -70 else None
    except Exception:
        pass
    return None


def _norm01(x, lo=5, hi=95):
    import numpy as np
    x = np.asarray(x, float)
    if not len(x):
        return x
    a, b = np.percentile(x, lo), np.percentile(x, hi)
    return np.clip((x - a) / max(b - a, 1e-9), 0, 1)


def fit_grid(env, hop_t, bpm, dur):
    """Constant beat grid locked to `bpm` (period searched +-0.4 %), phase fitted to the onset envelope. Returns (period, phase, score)."""
    import numpy as np
    from scipy.ndimage import maximum_filter1d
    e = maximum_filter1d(env, 3)
    best = (-1.0, 60.0 / bpm, 0.0)
    for P in (60.0 / bpm) * (1 + np.linspace(-0.004, 0.004, 33)):
        ph = np.arange(0, P, hop_t)
        k = np.arange(int(dur / P) + 1)
        idx = np.round((ph[:, None] + P * k[None, :]) / hop_t).astype(int)
        idx = np.clip(idx, 0, len(e) - 1)
        sc = e[idx].mean(1)
        i = int(np.argmax(sc))
        if sc[i] > best[0]:
            best = (float(sc[i]), float(P), float(ph[i]))
    return best[1], best[2], best[0]


def build_song_map(path, csv_bpm=None, beats_override=None):
    """THE song map: beat grid locked to the CSV tempo, downbeats/bars, 4- and 8-bar phrases, sections (intro / verse / build /
    drop / breakdown / outro), ALL drops, strong accents, rhythm strength, loudness, waveform for the GUI view."""
    import numpy as np
    import librosa
    y, sr = decode_mono(path)
    if len(y) < sr * 20:
        raise RuntimeError("audio too short / undecodable")
    dur = len(y) / sr
    hop = 128
    hop_t = hop / sr
    oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    oenv_low = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[freqs < 160] + 1e-6), sr=sr, hop_length=512)
    bass_frames = S[freqs < 160].mean(0)
    rms_frames = librosa.feature.rms(S=S)[0]
    # 1) tempo + grid
    lib_tempo, lib_beats = librosa.beat.beat_track(onset_envelope=oenv, sr=sr, hop_length=hop, start_bpm=float(csv_bpm or 120),
                                                   tightness=400 if csv_bpm else 100)
    bpm0 = float(csv_bpm) if csv_bpm else float(np.atleast_1d(lib_tempo)[0])
    while bpm0 > 200:
        bpm0 /= 2
    while bpm0 < 60:
        bpm0 *= 2
    # high-resolution attack envelope (5.8 ms frames, 1.45 ms hop): rise of log energy, so beats sit on the ATTACK, not after it
    fr_ = librosa.util.frame(np.pad(y, (64, 64)), frame_length=128, hop_length=32)
    le = np.log(np.mean(fr_ ** 2, axis=0) + 1e-8)
    att = np.maximum(0, np.diff(le, prepend=le[0]))
    att = smooth(att, 3)
    hi_t = 32 / sr
    P, ph, gscore = fit_grid(oenv, hop_t, bpm0, dur)              # coarse: period + phase on the onset envelope
    phs = ph + np.arange(-0.03, 0.03, hi_t)                        # fine: phase on the attack envelope
    k_ = np.arange(int((dur - ph) / P))
    idx = np.clip(np.round((phs[:, None] + P * k_[None, :]) / hi_t).astype(int), 0, len(att) - 1)
    from scipy.ndimage import maximum_filter1d
    ph = float(phs[int(np.argmax(maximum_filter1d(att, 2)[idx].mean(1)))])
    while ph - P >= 0:
        ph -= P
    while ph < 0:
        ph += P
    bt = ph + P * np.arange(int((dur - ph) / P))
    tracker = "grid"
    if beats_override:
        bt = np.array(beats_override[0], float)
        P = float(np.median(np.diff(bt)))
        tracker = "beat_this"
    # small local corrections toward strong onsets (follows slight drift; never more than 12 ms)
    e = oenv / (np.median(oenv) + 1e-9)
    dev = np.zeros(len(bt))
    w = int(0.012 / hop_t)
    for i, t in enumerate(bt):
        c = int(round(t / hi_t))
        w2 = int(0.012 / hi_t)
        a, b = max(0, c - w2), min(len(att), c + w2 + 1)
        if b > a and att[a:b].max() >= 4 * (np.median(att) + 1e-9):
            dev[i] = (a + int(np.argmax(att[a:b])) - c) * hi_t
    from scipy.ndimage import median_filter
    bt = bt + median_filter(dev, size=9, mode="nearest")
    lb = librosa.frames_to_time(np.asarray(lib_beats, int), sr=sr, hop_length=hop)
    agree = float(np.median([np.min(np.abs(bt - t)) for t in lb])) * 1000 if len(lb) else None
    nb = len(bt)
    if nb < 16:
        raise RuntimeError("no steady beat found")
    # 2) per-beat features
    def per_beat(sig, t_per):
        idx = np.clip((bt / t_per).astype(int), 0, len(sig) - 1)
        nxt = np.clip(((bt + P) / t_per).astype(int), 0, len(sig))
        return np.array([sig[a:max(a + 1, b)].mean() for a, b in zip(idx, nxt)])
    st512 = 512 / sr
    rms_b = per_beat(rms_frames, st512)
    bass_b = per_beat(bass_frames, st512)
    kick_b = np.array([oenv_low[max(0, int(t / st512) - 1):int(t / st512) + 2].max(initial=0) for t in bt])
    on_b = np.array([e[max(0, int(t / hop_t) - w):int(t / hop_t) + w + 1].max(initial=0) for t in bt])
    # 3) downbeats: bar phase from low-frequency / kick onset energy
    rb = smooth(_norm01(rms_b), 2)
    jumps = np.abs(np.diff(_norm01(bass_b) + rb, prepend=0))          # sections change on downbeats
    phase = int(np.argmax([kick_b[p::4].mean() / (kick_b.mean() + 1e-9) + 0.3 * on_b[p::4].mean() / (on_b.mean() + 1e-9)
                           + 4.0 * jumps[p::4].mean() / (jumps.mean() + 1e-9) * 0.25 for p in range(4)]))
    down = [i for i in range(nb) if i % 4 == phase]
    # 4) bar features + novelty
    mel = librosa.feature.melspectrogram(S=S ** 2, sr=sr, n_mels=40)
    lm = np.log1p(mel)
    bars = [(down[i], down[i + 1] if i + 1 < len(down) else nb) for i in range(len(down))]
    if down[0] > 0:
        bars.insert(0, (0, down[0]))
    bar_feat = []
    for a, b in bars:
        fa, fb = int(bt[a] / st512), int((bt[b - 1] + P) / st512)
        v = lm[:, fa:max(fa + 1, fb)].mean(1)
        bar_feat.append(v / (np.linalg.norm(v) + 1e-9))
    nov = [0.0] + [float(1 - bar_feat[i] @ bar_feat[i - 1]) for i in range(1, len(bars))]
    rms_n, bass_n = _norm01(rms_b), _norm01(bass_b)
    dens = smooth((on_b >= 2.5).astype(float), 8)
    dens_n = _norm01(dens)
    level_b = 0.45 * rms_n + 0.35 * bass_n + 0.2 * dens_n
    # 5) phrases: 4-bar phase chosen where novelty peaks
    bar_down = [i for i, (a, b) in enumerate(bars) if a in down]
    q = int(np.argmax([sum(nov[i] for i in bar_down if (bar_down.index(i) - p) % 4 == 0) for p in range(4)])) if len(bar_down) >= 8 else 0
    ph4 = [bars[i][0] for k, i in enumerate(bar_down) if (k - q) % 4 == 0]
    q8 = int(np.argmax([sum(nov[bars.index(next(bb for bb in bars if bb[0] == b0))] for j, b0 in enumerate(ph4) if j % 2 == p)
                        for p in range(2)])) if len(ph4) >= 4 else 0
    ph8 = [b0 for j, b0 in enumerate(ph4) if j % 2 == q8]
    # 6) sections on 4-bar phrases (units)
    edges = ([0] if ph4 and ph4[0] > 0 else []) + ph4 + [nb]
    units = [(edges[i], edges[i + 1]) for i in range(len(edges) - 1) if edges[i + 1] > edges[i]]
    L = np.array([level_b[a:b].mean() for a, b in units])
    B = np.array([bass_n[a:b].mean() for a, b in units])
    lab = ["verse"] * len(units)
    # DROPS (selective): a big, sustained energy + bass jump after a lower build-up, holding for >= 4 bars, >= 16 bars apart.
    # Short bumps / fills fail the sustain test and stay accents.
    cands_d = []
    for i in range(1, len(units)):
        prev = L[max(0, i - 2):i]
        jump = L[i] - float(np.max(prev))
        bj = B[i] - float(np.max(B[max(0, i - 2):i]))
        if L[i] < 0.55 or jump < 0.2 or bj < 0.12:
            continue
        a, b = units[i]
        cands = [d for d in down if units[i - 1][0] + (units[i - 1][1] - units[i - 1][0]) // 2 <= d <= a + 4]
        dj = max(cands or [a], key=lambda d: bass_n[d:d + 4].mean() - bass_n[max(0, d - 4):d].mean())
        bars4 = [level_b[dj + 4 * q: dj + 4 * q + 4].mean() for q in range(4) if dj + 4 * q + 4 <= nb]
        if len(bars4) < 4 or min(bars4) < 0.45 or float(np.mean(bars4)) < 0.55:
            continue                                       # not sustained for 4 bars: a bump, not a drop
        cands_d.append({"beat": int(dj), "t": round(float(bt[dj]), 4),
                        "strength": round(float(jump + max(bj, 0) + L[i]), 3), "jump": round(float(jump), 3), "bass_jump": round(float(bj), 3)})
    drops = []
    for d in sorted(cands_d, key=lambda d: -d["strength"]):
        if all(abs(d["beat"] - x["beat"]) >= 64 for x in drops):
            drops.append(d)
    drops.sort(key=lambda d: d["beat"])
    unit_of = lambda beat: max([k for k, u in enumerate(units) if u[0] <= beat] or [0])
    for d in drops:
        k = unit_of(d["beat"] + 2)
        lab[k] = "drop"
        k += 1
        while k < len(units) and L[k] >= 0.5:
            lab[k] = "drop"
            k += 1
    has_later_drop = lambda i: any(lab[k] == "drop" for k in range(i + 1, len(units)))
    for i in range(1, len(units)):                         # breakdown: calm stretch after a drop, before another drop
        if lab[i] == "verse" and lab[i - 1] in ("drop", "breakdown") and L[i] < 0.5 and has_later_drop(i):
            lab[i] = "breakdown"
    for d in drops:                                        # build: the phrase before each drop (+ one more if rising)
        i = unit_of(d["beat"] + 2)
        if i - 1 >= 0 and lab[i - 1] in ("verse", "breakdown", "intro"):
            if not (lab[i - 1] == "breakdown" and (i - 2 < 0 or lab[i - 2] != "breakdown") and L[i - 1] < 0.08):
                lab[i - 1] = "build"
        k = i - 2
        if k >= 0 and lab[k] == "verse" and L[k] < L[k + 1] - 0.03 and L[k] > (L[k - 1] if k else 0) + 0.03:
            lab[k] = "build"
    uidx = {b0: j for j, (b0, _) in enumerate(bars)}
    unov = [nov[uidx[u[0]]] if u[0] in uidx else 0.0 for u in units]
    cut = float(np.percentile(unov[1:], 70)) if len(unov) > 2 else 1.0
    first = next((i for i in range(1, len(units)) if unov[i] >= cut or lab[i] != "verse"), 1)
    for i in range(first):
        if lab[i] == "verse" and L[i] <= np.median(L) + 0.05:
            lab[i] = "intro"
    last_drop = max([i for i in range(len(units)) if lab[i] == "drop"], default=-1)
    for i in range(len(units) - 1, last_drop, -1):
        if units[i][0] >= 0.72 * nb and L[i] < 0.5:
            lab[i] = "outro"
        else:
            break
    sections = []
    for (a, b), l, lv in zip(units, lab, L):
        if sections and sections[-1]["label"] == l:
            sections[-1].update(end=b, end_t=round(float(bt[b - 1] + P), 3))
        else:
            sections.append({"label": l, "start": int(a), "end": int(b), "start_t": round(float(bt[a]), 3),
                             "end_t": round(float(bt[b - 1] + P), 3), "level": round(float(lv), 3)})
    # 7) accents: big transients (kicks, snares, claps, bass hits, stabs) + rhythm strength
    from scipy.signal import find_peaks
    pk, pr = find_peaks(e, height=max(3.0, float(np.percentile(e, 97))), distance=int(0.09 / hop_t))
    low_e = oenv_low / (np.median(oenv_low) + 1e-9)
    accents = []
    for i in pk[np.argsort(-pr["peak_heights"])][:800]:
        t = float(i * hop_t)
        bass_hit = bool(low_e[min(len(low_e) - 1, int(t / st512))] >= 3.0)
        accents.append([round(t, 4), round(float(e[i]), 2), int(bass_hit)])
    accents.sort()
    # tick strength (beats + half-beats) and how REPEATING the rhythm is: the same position in the bar hit bar after bar
    ticks = np.sort(np.concatenate([bt, bt[:-1] + P / 2]))
    tick_on = np.array([e[max(0, int(t / hop_t) - w):int(t / hop_t) + w + 1].max(initial=0) for t in ticks])
    pos = np.array([(int(np.argmin(np.abs(bt - t))) - phase) % 4 * 2 + (0 if np.min(np.abs(bt - t)) < P / 4 else 1) for t in ticks])
    pat = np.array([np.median(tick_on[pos == k]) if np.any(pos == k) else 0 for k in range(8)])
    hit_rate = np.array([np.mean(tick_on[pos == k] >= 2.5) if np.any(pos == k) else 0 for k in range(8)])
    rhythm = float(np.clip(0.6 * hit_rate.max() + 0.4 * min(1.0, gscore / (np.mean(e) * 3 + 1e-9)), 0, 1))
    strength = []
    drop_beats = {d["beat"] for d in drops}
    ph4s, ph8s, downs = set(ph4), set(ph8), set(down)
    for i in range(nb):
        s_ = 0.3 + 0.25 * (i in downs) + 0.15 * (i in ph4s) + 0.15 * (i in ph8s) + 0.8 * (i in drop_beats)
        s_ += 0.35 * min(1.0, on_b[i] / 6.0) + 0.15 * min(1.0, kick_b[i] / (kick_b.mean() * 3 + 1e-9))
        strength.append(round(float(s_), 3))
    lvl_beat = np.zeros(nb, int)
    sec_beat = [""] * nb
    for sct in sections:
        for i in range(sct["start"], sct["end"]):
            sec_beat[i] = sct["label"]
            lvl_beat[i] = {"drop": 2, "build": 1, "breakdown": 1}.get(sct["label"], 0)
    big = max(drops, key=lambda d: d["strength"]) if drops else None
    env = np.abs(y[: len(y) // 2000 * 2000]).reshape(2000, -1).max(1) if len(y) >= 2000 else np.abs(y)
    bpm_fit = 1.0 if 100 <= bpm0 <= 180 else max(0.0, 1 - min(abs(bpm0 - 100), abs(bpm0 - 180)) / 40)
    steady = float(np.clip(1 - (agree or 30) / 60.0, 0, 1)) * 0.5 + 0.5 * rhythm
    try:
        st_ = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=start_time",
                              "-of", "json", path]).stdout or b"{}")
        start_time = float((st_.get("streams") or [{}])[0].get("start_time") or 0)
    except Exception:
        start_time = 0.0
    return {"v": SONGMAP_V, "tracker": tracker, "bpm": round(bpm0, 3), "bpm_src": "csv" if csv_bpm else "librosa",
            "bpm_librosa": round(float(np.atleast_1d(lib_tempo)[0]), 1), "period": round(P, 6), "grid_score": round(gscore, 3),
            "librosa_agree_ms": None if agree is None else round(agree, 1),
            "beats": [round(float(t), 4) for t in bt], "down": [int(i) for i in down], "phrase4": [int(i) for i in ph4],
            "phrase8": [int(i) for i in ph8], "sections": sections, "drops": drops, "accents": accents,
            "strength": strength, "energy": [round(float(v), 3) for v in level_b], "level": [int(v) for v in lvl_beat],
            "section_of_beat": sec_beat, "drop": big["beat"] if big else None,
            "drop_strength": round(big["strength"] / 3, 3) if big else 0.0, "rhythm": round(rhythm, 3),
            "pattern": [round(float(v), 2) for v in pat], "steady": round(steady, 3), "bpm_fit": round(bpm_fit, 2),
            "dur": round(dur, 3), "onsets": [a[0] for a in accents], "wave": [round(float(v), 3) for v in env],
            "lufs": ebur128_lufs(path), "start_time": round(start_time, 6),
            "origin": "first decoded sample (ffmpeg skips the encoder delay); render trims with asetpts=N/SR/TB"}


def synth_song(path, bpm=128.0, layout=(("intro", 8), ("verse", 8), ("build", 4), ("drop", 8), ("breakdown", 4), ("build", 4),
                                        ("drop", 8), ("outro", 4)), sr=44100, click=False):
    """Generated test song (bars per section): kicks / snares / hats by section, a bass line in drops, rising noise in builds.
    click=True: a plain click on every beat (used by the end-to-end sync test). Returns the true beat times (decoded origin)."""
    import numpy as np
    per = 60.0 / bpm
    nbeats = sum(n for _, n in layout) * 4
    dur = nbeats * per + 1.0
    t = np.arange(int(dur * sr)) / sr
    y = np.zeros_like(t, np.float32)
    rng = np.random.default_rng(5)
    beats, b = [], 0
    for name, bars in layout:
        for k in range(bars * 4):
            t0 = b * per
            s = int(t0 * sr)
            beats.append(t0)
            def add(sig, at=s):
                e = min(len(y), at + len(sig))
                y[at:e] += sig[:e - at]
            n = np.arange(int(0.15 * sr))
            if click:
                add((np.sin(2 * np.pi * 1500 * n[:int(0.03 * sr)] / sr) * np.exp(-n[:int(0.03 * sr)] / (0.004 * sr)) * 0.9).astype(np.float32))
            else:
                kick_amp = {"intro": 0.25, "verse": 0.5, "build": 0.6, "drop": 0.95, "bump": 0.95, "breakdown": 0.0, "outro": 0.3}[name]
                add((np.sin(2 * np.pi * (50 + 60 * np.exp(-n / 400)) * n / sr) * np.exp(-n / (0.05 * sr)) * kick_amp).astype(np.float32))
                if k % 2 == 1 and name in ("verse", "build", "drop", "bump"):
                    add((rng.standard_normal(len(n)) * np.exp(-n / (0.03 * sr)) * (0.5 if name == "drop" else 0.3)).astype(np.float32))
                hh = (rng.standard_normal(int(0.03 * sr)) * np.exp(-np.arange(int(0.03 * sr)) / 200) * 0.08).astype(np.float32)
                add(hh, s + int(per / 2 * sr))
                if name in ("drop", "bump"):
                    m = np.arange(int(per * sr))
                    add((np.sin(2 * np.pi * 55 * m / sr) * 0.35).astype(np.float32))
                if name == "build":
                    m = np.arange(int(per * sr))
                    add((rng.standard_normal(len(m)) * 0.02 * (1 + k / 4)).astype(np.float32))
                if name in ("intro", "breakdown", "outro"):
                    m = np.arange(int(per * sr))
                    add((np.sin(2 * np.pi * 330 * m / sr) * 0.08).astype(np.float32))
            b += 1
    y = np.clip(y, -1, 1)
    wav = str(path) + ".wav"
    import soundfile as sf
    sf.write(wav, y, sr)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", wav, "-c:a", "libmp3lame", "-b:a", "192k", str(path)], check=True)
    os.remove(wav)
    return beats


def _beat_this_beats(path):
    """Optional stronger beat tracker (pip install beat_this; CPU; offline once its model is cached). None if unavailable."""
    try:
        from beat_this.inference import File2Beats
    except Exception:
        return None
    try:
        f2b = File2Beats(checkpoint_path="final0", device="cpu", dbn=False)
        beats, downs = f2b(str(path))
        return [float(x) for x in beats], [float(x) for x in downs]
    except Exception as ex:
        out(f"  beat_this failed: {ex}")
        return None


def map_score(path, an):
    """How well a song map fits the audio: % of strong onsets within 30 ms of a grid beat (and of the half-beat grid), grid tempo
    vs CSV tempo, drops found and whether each is a real sustained energy + bass jump. Returns a dict with 'score' 0-100."""
    import numpy as np
    import librosa
    y, sr = decode_mono(path)
    strong = local_onsets(path)
    bt = np.array(an["beats"])
    half = np.sort(np.concatenate([bt, bt[:-1] + np.diff(bt) / 2]))
    near = lambda g, t: float(np.min(np.abs(g - t))) if len(g) else 9.0
    pb = 100.0 * np.mean([near(bt, t) <= 0.03 for t in strong]) if len(strong) else 0.0
    ph = 100.0 * np.mean([near(half, t) <= 0.03 for t in strong]) if len(strong) else 0.0
    grid_bpm = 60.0 / float(np.median(np.diff(bt)))
    csv_bpm = an.get("bpm") if an.get("bpm_src") == "csv" else None
    tempo_err = abs(grid_bpm - csv_bpm) / csv_bpm * 100 if csv_bpm else None
    rms = librosa.feature.rms(y=y, hop_length=512)[0]
    t_r = np.arange(len(rms)) * 512 / sr
    real = 0
    for d in an.get("drops", []):
        bar = 4 * float(np.median(np.diff(bt)))
        after = rms[(t_r >= d["t"]) & (t_r < d["t"] + 4 * bar)].mean()
        before = rms[(t_r >= d["t"] - 4 * bar) & (t_r < d["t"])].mean()
        real += 20 * np.log10((after + 1e-9) / (before + 1e-9)) >= 3.0
    nd = len(an.get("drops", []))
    drop_ok = 1.0 if nd == 0 else real / nd
    score = 0.6 * max(pb, 0.8 * ph) + 20 * (1.0 if tempo_err is None or tempo_err < 1 else 0.5 if tempo_err < 3 else 0) + 20 * drop_ok
    return {"score": round(float(score), 1), "onsets_on_beat": round(float(pb), 1), "onsets_on_8th": round(float(ph), 1),
            "grid_bpm": round(grid_bpm, 2), "csv_bpm": csv_bpm, "tempo_err_pct": None if tempo_err is None else round(tempo_err, 2),
            "drops": nd, "drops_real": int(real), "tracker": an.get("tracker", "grid")}


def song_check(paths=None, verbose=True):
    """songcheck: score every song's map; if a song scores low and beat_this is installed, try it and keep the better map."""
    cfg = load_config()
    if not paths:
        td = HERE / "testdata"
        paths = sorted(str(p) for p in td.rglob("*.mp3")) if td.is_dir() else []
        if not paths:
            paths = [a["path"] for a in scan_audio(cfg)]
    bpm_of = {}
    try:
        for s_ in song_pool(cfg)[0]:
            bpm_of[s_["path"]] = s_.get("csv_bpm")
    except Exception:
        pass
    res = []
    for pth in paths:
        try:
            an = analyse_song(pth, bpm_of.get(pth))
            sc = map_score(pth, an)
            if sc["score"] < 70:
                bt = _beat_this_beats(pth)
                if bt is None:
                    sc["note"] = "low score; beat_this not installed (pip install beat_this) - kept the grid"
                else:
                    alt = build_song_map(pth, bpm_of.get(pth), beats_override=bt)
                    sc2 = map_score(pth, alt)
                    if sc2["score"] > sc["score"]:
                        cache = load_json(SONG_CACHE, {})
                        st = os.stat(pth)
                        cache[f"{pth}|{int(st.st_mtime)}|{st.st_size}|{SONGMAP_V}|{round(float(bpm_of.get(pth) or 0), 3)}"] = alt
                        save_json(SONG_CACHE, cache)
                        sc2["note"] = f"beat_this map kept ({sc2['score']} > grid {sc['score']})"
                        sc = sc2
                    else:
                        sc["note"] = f"grid kept (beat_this scored {sc2['score']})"
            res.append((pth, sc))
        except Exception as ex:
            res.append((pth, {"score": 0, "error": str(ex)}))
    if verbose:
        out("SONGCHECK (score 0-100: onsets on the beat grid, tempo vs CSV, real drops)")
        for pth, sc in res:
            if "error" in sc:
                out(f"  {Path(pth).name[:50]:50}  ERROR {sc['error']}")
                continue
            out(f"  {Path(pth).name[:50]:50} score {sc['score']:5.1f} | strong onsets within 30 ms of a beat {sc['onsets_on_beat']:5.1f}% "
                f"(8th grid {sc['onsets_on_8th']:5.1f}%) | grid {sc['grid_bpm']} BPM vs CSV {sc['csv_bpm']} "
                f"({sc['tempo_err_pct']}%) | drops {sc['drops']} ({sc['drops_real']} real jumps) | {sc['tracker']}"
                + (f" | {sc['note']}" if sc.get("note") else ""))
    return res


def cmd_songcheck(args):
    song_check(list(args.paths) or None)


def local_onsets(path):
    """Strong hits of a song, judged against the loudness of their own part (quiet intros keep their kicks): attack-envelope peaks
    >= 30 % of the local (4 s) maximum, at least 90 ms apart."""
    import numpy as np
    from scipy.ndimage import maximum_filter1d
    from scipy.signal import find_peaks
    y, sr = decode_mono(path)
    hop = 32
    fr_ = np.lib.stride_tricks.sliding_window_view(np.pad(y, (64, 64)), 128)[::hop]
    le = np.log(np.mean(fr_ ** 2, axis=1) + 1e-8)
    att = np.maximum(0, np.diff(le, prepend=le[0]))
    att = np.convolve(att, np.ones(3) / 3, mode="same")
    loc = maximum_filter1d(att, int(4.0 * sr / hop)) + 1e-9
    pk, _ = find_peaks(att / loc, height=0.3, distance=int(0.09 * sr / hop))
    return pk * hop / sr


def analyse_song(path, csv_bpm=None):
    """Cached song map (key: path + mtime + size + CSV tempo). Same dict is used by the song pick, the planner, the render and
    the Song map view."""
    cache = load_json(SONG_CACHE, {})
    st = os.stat(path)
    key = f"{path}|{int(st.st_mtime)}|{st.st_size}|{SONGMAP_V}|{round(float(csv_bpm or 0), 3)}"
    if key in cache:
        return cache[key]
    an = build_song_map(path, csv_bpm)
    cache = load_json(SONG_CACHE, {})
    cache[key] = an
    save_json(SONG_CACHE, cache)
    return an


SONGMAP_DEFAULT = "v1"                   # V6.9.5: the default song map; switching the default to SONGMAPV2 is this one line ("v2")
SONGMAP_CHOICES = {"v1": "Songmap V1", "v2": "Songmap V2"}
SONGMAP_AUTO = "v2auto"                  # V6.9.5.2: per song, V2 only where its grid is confident and measurably better than V1, else the V1 map
SONGMAP_CHOICES_UI = dict(SONGMAP_CHOICES, **{SONGMAP_AUTO: "Songmap V2 (auto, V1 fallback)"})     # what the Settings dropdown offers
SONGMAP_V2_HOOK = [None]                 # tests only: called at the start of a V2 analysis (inject an error / a delay)


def songmap_version(cfg=None):
    v = str((cfg if cfg is not None else load_config()).get("songmap_version") or SONGMAP_DEFAULT).lower()
    if v in (SONGMAP_AUTO, SONGMAP_CHOICES_UI[SONGMAP_AUTO].lower()):
        return SONGMAP_AUTO
    return "v2" if v in ("v2", "songmap v2") else "v1"


def _peek_v1_bpm(path, csv_bpm=None):
    """BPM of the V1 map IF it is already in the V1 cache (read-only: never analyses, never writes), else None."""
    try:
        st = os.stat(path)
        hit = load_json(SONG_CACHE, {}).get(f"{path}|{int(st.st_mtime)}|{st.st_size}|{SONGMAP_V}|{round(float(csv_bpm or 0), 3)}")
        return float(hit["bpm"]) if hit and hit.get("bpm") else None
    except Exception:
        return None


class _V2Fail(Exception):
    """A V2 failure whose message already names the exception type (worker errors, timeouts)."""


def _songmap_v2_cached(path, csv_bpm, v1_bpm, name):
    """The V2 map from its own cache, or built now (cap ANALYSIS_CAP_S). Raises _V2Fail / any exception on a problem."""
    import songmap_v2
    cpath = DATA / songmap_v2.CACHE_NAME
    key = songmap_v2.cache_key(path, csv_bpm, v1_bpm)
    cache = load_json(cpath, {})
    hit = cache.get(key)
    if hit and not hit.get("fallback_marker"):
        return hit
    if hit:
        raise _V2Fail(hit["fallback_marker"] + " (cached: not retried until the V2 algorithm version changes)")
    box = {}
    deadline = time.monotonic() + songmap_v2.ANALYSIS_CAP_S

    def work():
        try:
            box["m"] = songmap_v2.build_songmap_v2(path, csv_bpm, deadline=deadline, hook=SONGMAP_V2_HOOK[0], v1_bpm=v1_bpm)
        except BaseException as ex:      # noqa: BLE001 - nothing may escape the worker
            box["err"] = f"{type(ex).__name__}: {ex}"
    t0 = time.time()
    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(songmap_v2.ANALYSIS_CAP_S)
    if th.is_alive() or "m" not in box:
        reason = "timeout (analysis cap %.0f s)" % songmap_v2.ANALYSIS_CAP_S if th.is_alive() or "cap reached" in box.get("err", "") else box.get("err", "no result")
        if reason.startswith("timeout"):
            c2 = load_json(cpath, {})
            c2[key] = {"fallback_marker": reason}
            save_json(cpath, c2)
        raise _V2Fail(reason)
    m = box["m"]
    c2 = load_json(cpath, {})
    c2[key] = m
    save_json(cpath, c2)
    out(f"songmap v2: {name} {time.time() - t0:.1f} s, bpm={m['bpm']}, grid_conf={m['v2']['grid_confidence']}, "
        f"{len(m['v2']['events'])} events, {len(m['drops'])} drops")
    return m


def _songmap_auto_pick(path, csv_bpm, v1m, m2, name):
    """'Songmap V2 (auto, V1 fallback)': V2 only if its grid confidence is >= 0.8, its kick-to-grid p95 <= 40 ms and its median is not worse than
    V1's; otherwise the V1 map. The decision and its numbers are cached in the V2 cache file (key + '|auto'), one log line per song."""
    import songmap_v2
    cpath = DATA / songmap_v2.CACHE_NAME
    akey = songmap_v2.cache_key(path, csv_bpm, v1m.get("bpm")) + "|auto"
    cache = load_json(cpath, {})
    dec = cache.get(akey)
    if not dec:
        dec = songmap_v2.build.auto_decision(v1m, m2)
        c2 = load_json(cpath, {})
        c2[akey] = dec
        save_json(cpath, c2)
    out(f"songmap auto: {name} -> " + songmap_v2.build.auto_line(dec))
    if dec["choice"] == "v2":
        return dict(m2, songmap_auto=dec)
    return dict(v1m, songmap_version="v1-auto", songmap_auto=dec)


def get_songmap(path, csv_bpm=None, version=None):
    """THE routing point for song map requests (V6.9.5): V1 = analyse_song() exactly as before; V2 = the isolated songmap_v2 package with its
    own cache file; V6.9.5.2 'v2auto' = V2 or V1 per song (see _songmap_auto_pick). Any V2 problem (error, timeout, missing module) logs
    'songmap v2 fallback: <song> (<reason>)' and returns the V1 map flagged songmap_version = 'v1-fallback', so a montage never fails because of V2."""
    v = version or songmap_version()
    if v not in ("v2", SONGMAP_AUTO):
        return analyse_song(path, csv_bpm)
    name = Path(path).name
    v1m = analyse_song(path, csv_bpm) if v == SONGMAP_AUTO else None          # auto always needs the V1 map; plain V2 only peeks at its cache
    try:
        m = _songmap_v2_cached(path, csv_bpm, float(v1m["bpm"]) if v1m else _peek_v1_bpm(path, csv_bpm), name)
        return _songmap_auto_pick(path, csv_bpm, v1m, m, name) if v1m else m
    except Exception as ex:
        why = str(ex) if isinstance(ex, _V2Fail) else f"{type(ex).__name__}: {ex}"
        out(f"songmap v2 fallback: {name} ({why})")
        m = dict(v1m or analyse_song(path, csv_bpm))
        m.update(songmap_version="v1-fallback", songmap_fallback_reason=why)
        return m


def analyse_song_v4(path, csv_bpm=None):
    """V4's song analysis (kept for synccompare / the 'v4' placement). Beat grid, downbeats, per-beat energy, section levels, drop. Cached per file. The CSV 'Tempo' is the PRIMARY BPM: librosa only
    refines the beat grid, and is snapped to the CSV tempo when it lands at about 2x or 0.5x (or within 4% on a steady grid)."""
    cache = load_json(SONG_CACHE, {})
    key = file_key(path) + "v4grid" + f"|{round(csv_bpm or 0)}"
    if key in cache:
        return cache[key]
    import numpy as np
    import librosa
    y, sr = decode_mono(path)
    if len(y) < sr * 20:
        raise RuntimeError("audio too short / undecodable")
    hop = 512
    oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    tempo, bf = librosa.beat.beat_track(onset_envelope=oenv, sr=sr, hop_length=hop, tightness=100)
    bf = np.asarray(bf, int)
    bt = librosa.frames_to_time(bf, sr=sr, hop_length=hop)
    if len(bt) < 16:
        raise RuntimeError("no steady beat found")
    bpm = float(np.atleast_1d(tempo)[0])
    if csv_bpm:                                   # librosa half/double-tempo errors: trust the CSV tempo
        ratio = bpm / csv_bpm
        if 1.8 < ratio < 2.2:
            st = oenv[np.clip(bf, 0, len(oenv) - 1)]
            ph = int(st[1::2].sum() > st[0::2].sum())
            bf, bt, bpm = bf[ph::2], bt[ph::2], bpm / 2
        elif 0.45 < ratio < 0.55:
            bt = np.sort(np.concatenate([bt, (bt[:-1] + bt[1:]) / 2]))
            bf = np.round(bt * sr / hop).astype(int)
            bpm *= 2
    ibi = np.diff(bt)
    steady = float(max(0.0, 1 - np.std(ibi) / max(np.mean(ibi), 1e-6) * 8))
    if steady >= 0.75:      # steady (electronic) track: replace the tracked beats by a clean grid over the whole song
        per = float(np.median(ibi))
        if csv_bpm and abs(60.0 / per - csv_bpm) / csv_bpm < 0.04:
            per = 60.0 / float(csv_bpm)                # grid period from the CSV tempo, phase from librosa
        off = float(np.median((bt - bt[0] + per / 2) % per - per / 2))
        t0 = (bt[0] + off) % per
        bt = t0 + per * np.arange(int((len(y) / sr - t0) / per))
        bf = np.round(bt * sr / hop).astype(int)
        bpm = 60.0 / per
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    edges = np.append(bf, min(len(rms) - 1, bf[-1] + int(np.median(np.diff(bf)))))
    en = np.array([rms[edges[i]:max(edges[i] + 1, edges[i + 1])].mean() for i in range(len(bf))])
    lo, hi = np.percentile(en, 5), np.percentile(en, 95)
    en = np.clip((en - lo) / max(hi - lo, 1e-9), 0, 1)
    en = smooth(en, 3)
    stren = oenv[np.clip(bf, 0, len(oenv) - 1)]
    phase = int(np.argmax([stren[p::4].mean() + 0.5 * en[p::4].mean() for p in range(4)]))
    down = [i for i in range(len(bt)) if i % 4 == phase]
    sm = smooth(en, 8)
    n = len(bt)
    best, drop, dstr = -1, None, 0.0
    for i in down:
        if 8 <= i <= n - 12:
            j = float(en[i:i + 8].mean() - en[i - 8:i].mean())
            if j > dstr:
                dstr, drop = j, i
    level = np.where(sm < 0.4, 0, np.where(sm < 0.7, 1, 2)).astype(int)
    if drop is not None and dstr > 0.12:
        level[max(0, drop - 16):drop] = np.maximum(level[max(0, drop - 16):drop], 1)
        level[drop:drop + 24] = 2
    else:
        drop = None
    onsets = librosa.onset.onset_detect(onset_envelope=oenv, sr=sr, hop_length=hop, units="time")
    grid_bpm = bpm
    if csv_bpm:
        bpm = float(csv_bpm)                           # CSV tempo is the primary value
    bpm_fit = 1.0 if 100 <= bpm <= 180 else max(0.0, 1 - min(abs(bpm - 100), abs(bpm - 180)) / 40)
    an = {"bpm": round(bpm, 1), "bpm_grid": round(float(grid_bpm), 1), "bpm_src": "csv" if csv_bpm else "librosa", "beats": [round(float(t), 4) for t in bt], "down": [int(i) for i in down],
          "energy": [round(float(e), 3) for e in en], "level": [int(l) for l in level],
          "drop": None if drop is None else int(drop), "drop_strength": round(dstr, 3), "steady": round(steady, 3),
          "bpm_fit": round(bpm_fit, 2), "dur": round(len(y) / sr, 1),
          "onsets": [round(float(t), 3) for t in onsets[:2000]]}
    cache[key] = an
    save_json(SONG_CACHE, cache)
    return an


def song_fit(an, energy=None, dance=None):
    """Montage fit, 0-55: steady beat 15 + clear drop/energy rise 20 + BPM 100-180 10 + energy 10 (CSV Energy, blended 70/30
    with CSV Danceability when present; librosa loudness only when the CSV has no Energy)."""
    rise = max(an["drop_strength"], 0.0)
    en = energy if energy is not None else (sum(an["energy"]) / max(1, len(an["energy"])))
    if dance is not None:
        en = 0.7 * en + 0.3 * dance
    return {"steady": round(15 * an["steady"], 1), "drop": round(20 * min(1.0, rise / 0.4), 1),
            "bpm": round(10 * an["bpm_fit"], 1), "energy": round(10 * max(0.0, min(1.0, en)), 1)}


def pick_window(an, target_s):
    """Best window of 60-120 s starting and ending on downbeats; drop sits ~60% in."""
    import numpy as np
    bt, down = np.array(an["beats"]), an["down"]
    target = min(120.0, max(60.0, float(target_s)))
    if an["dur"] < 60:
        return {"s": 0, "e": len(bt) - 1, "start_t": float(bt[0]), "end_t": float(bt[-1]), "score": 0, "note": "song shorter than 60 s"}
    best = None
    for s in down:
        ends = [e for e in down if e > s and bt[e] - bt[s] <= target]
        if not ends:
            continue
        e = max(ends)
        L = bt[e] - bt[s]
        if L < 60:
            continue
        sc = 2 * an["steady"] + L / 120
        d = an["drop"]
        if d is not None and s < d < e:
            pos = (bt[d] - bt[s]) / L
            sc += 2.5 * max(0.0, 1 - abs(pos - 0.6) / 0.6) + an["drop_strength"]
        en = np.array(an["energy"])
        sc += float(en[s:e].mean()) * 0.8
        if best is None or sc > best["score"]:
            best = {"s": int(s), "e": int(e), "start_t": float(bt[s]), "end_t": float(bt[e]), "score": round(float(sc), 3), "note": ""}
    if best is None:
        best = {"s": 0, "e": len(bt) - 1, "start_t": float(bt[0]), "end_t": float(bt[-1]), "score": 0, "note": "no downbeat window found, whole song"}
    return best


def parse_added(s):
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.datetime.strptime(s.strip(), fmt)
        except Exception:
            pass
    try:
        return datetime.datetime.fromisoformat(s.strip().replace("Z", ""))
    except Exception:
        return None


MATCH_CACHE = DATA / "match_cache.json"
MATCH_CACHE_VER = 2                  # V6.5: bump = every automatic match is recomputed once (manual matches live in the config)
SONG_STATE = ["none"]                 # V6.1.2: state of the last song_pool call: hit | incremental | full | stale (cached_only) | none (cached_only, no cache)


def _akey(a):
    return a.get("key") or a["path"]


def _folder_sig(audio):
    newest = 0
    for a in audio:
        try:
            newest = max(newest, int(_akey(a).rsplit("|", 1)[1]))
        except (IndexError, ValueError):
            pass
    return [len(audio), newest]


def match_cached(cfg, csvp, rows, audio, cached_only=False):
    """V6.1.2: song match with an on-disk cache keyed by the CSV (name, size, mtime) and the songs folder (file count, newest mtime).
    Same key: the saved matches are returned at once. Key changed: matches of unchanged files whose track is still in the CSV are
    reused and only the new / changed / unmatched files are matched against the free tracks. cached_only: never matches, returns what the
    cache holds for the files that exist now. Returns (matched, unmatched, state)."""
    if not rows or not audio:
        return [], list(rows), "none"
    try:
        st = csvp.stat()
        csv_sig = [csvp.name, st.st_size, int(st.st_mtime)]
    except (OSError, AttributeError):
        csv_sig = [str(csvp), 0, 0]
    ov = hashlib.md5(json.dumps([cfg.get("song_overrides", {}), cfg.get("match_floor", 60)], sort_keys=True).encode()).hexdigest()[:10]
    folder = _folder_sig(audio)
    cache = load_json(MATCH_CACHE, {})
    by_a = {_akey(a): a for a in audio}
    by_r = {}
    for r in rows:
        by_r.setdefault(_rank_key(r), []).append(r)
    kept, used_r = [], set()
    if isinstance(cache, dict) and cache.get("v") != MATCH_CACHE_VER:
        cache = {}                                                 # V6.5: an older matcher's results are never reused
    if isinstance(cache, dict) and cache.get("ov") == ov:
        SONG_DUPS.clear()
        SONG_DUPS.update(a_["path"] for a_ in (by_a.get(k_) for k_ in cache.get("dups", [])) if a_)
        for e in cache.get("pairs", []):
            a, cand = by_a.get(e.get("a")), by_r.get(e.get("r"))
            r = next((x for x in (cand or []) if id(x) not in used_r), None)
            if a is not None and r is not None:
                used_r.add(id(r))
                kept.append((r, a, int(e.get("s", 0))))
    exact = isinstance(cache, dict) and cache.get("csv") == csv_sig and cache.get("folder") == folder and cache.get("ov") == ov
    def unmatched_of(m):
        got = {id(r) for r, _, _ in m}
        return [r for r in rows if id(r) not in got]
    if exact:
        return kept, unmatched_of(kept), "hit"
    if cached_only:
        return kept, unmatched_of(kept), ("stale" if kept else "none")
    matched, _ = match_playlist(rows, audio, cfg)                  # V6.5: exact rule, cheap: everything is recomputed when the key changed
    try:
        save_json(MATCH_CACHE, {"v": MATCH_CACHE_VER, "csv": csv_sig, "folder": folder, "ov": ov,
                                "dups": [_akey(a) for a in audio if a["path"] in SONG_DUPS],
                                "pairs": [{"a": _akey(a), "r": _rank_key(r), "s": sc} for r, a, sc in matched]})
    except Exception as ex:
        out(f"songs: match cache not saved ({ex})")
    return matched, unmatched_of(matched), "full"


def song_pool(cfg, cached_only=False):
    """Matched playlist songs that have a file (plus the unmatched list). Falls back to every audio file."""
    audio = scan_audio(cfg)
    csvp, rows, col = read_playlist(cfg)
    songs, unmatched = {}, []
    SONG_STATE[0] = "none"
    if rows:
        matched, unmatched, SONG_STATE[0] = match_cached(cfg, csvp, rows, audio, cached_only)
        for r, a, sc in matched:
            added = parse_added(r["added"]) if r["added"] else None
            old = songs.get(a["path"])
            if old is None or (added and (old["added"] is None or added > old["added"])):
                songs[a["path"]] = {"path": a["path"], "artist": r["artist"], "title": r["title"], "added": added,
                                    "csv_bpm": r.get("tempo") or None, "energy": r.get("energy"), "dance": r.get("dance"), "score": sc}
        try:
            if not cached_only:
                write_song_matches(audio, matched)
        except Exception as ex:
            out(f"could not write song_matches.csv: {ex}")
    if rows and not cached_only:
        wk = [r for r in rows if r["added"] and parse_added(r["added"]) and (datetime.datetime.now() - parse_added(r["added"])).days < cfg.get("week_days", 7)]
        have = {id(r) for r, a, sc in matched}
        out(f"songs: {len(rows)} CSV tracks, {len(matched)} matched to an MP3, {len(unmatched)} unmatched; "
            f"this week: {len(wk)} added, {sum(1 for r in wk if id(r) in have)} with MP3")
    if not songs and cached_only and rows:
        return [], unmatched, (csvp.name if csvp else None)          # first show: the matcher is still running (status line says so)
    if not songs:
        out("no playlist matches: using every audio file in the MP3 folder")
        for a in audio:
            songs[a["path"]] = {"path": a["path"], "artist": a["artist"], "title": a["title"], "added": None}
    return list(songs.values()), unmatched, (csvp.name if csvp else None)


def hist_list(path, game):
    return load_json(path, {}).get(game, [])


def pick_song(cfg, game, songs, now=None, forced=None):
    """Recency (strongest) + montage fit - recently-used penalty. Newest week first; older only if none fit."""
    now = now or datetime.datetime.now()
    used = hist_list(USED_SONGS, game)
    last = used[-1]["path"] if used else None
    wd = cfg.get("week_days", 7)

    def score(s, an):
        d = (now - s["added"]).days if s["added"] else 999
        rec = 50.0 / (1 + max(d, 0) / 7.0) if s["added"] else 0.0
        fit = song_fit(an, s.get("energy"), s.get("dance"))
        pen = (30.0 if s["path"] == last else 0.0) + 8.0 * sum(1 for u in used[-4:] if u["path"] == s["path"])
        return {"recency": round(rec, 1), "fit": round(sum(fit.values()), 1), "fit_parts": fit, "penalty": pen,
                "total": round(rec + sum(fit.values()) - pen, 1), "days": None if d == 999 else d}
    if forced:
        s = next((x for x in songs if x["path"] == forced), None) or {"path": forced, "artist": "", "title": Path(forced).stem, "added": None}
        an = get_songmap(forced, (next((x for x in songs if x['path'] == forced), {}) or {}).get('csv_bpm'))
        return s, an, score(s, an), []
    week = sorted([s for s in songs if s["added"] and (now - s["added"]).days < wd], key=lambda s: s["added"], reverse=True)
    rest = sorted([s for s in songs if s not in week], key=lambda s: s["added"] or datetime.datetime(1970, 1, 1), reverse=True)
    for tier, name in ((week, "this week"), (rest, "older")):
        board = []
        for i, s in enumerate(tier[:15]):
            if CANCEL.is_set():
                raise RuntimeError("cancelled")
            progress(i / 15, f"analysing song {i + 1}")
            try:
                an = get_songmap(s["path"], s.get("csv_bpm"))
            except Exception as ex:
                out(f"  skip {Path(s['path']).name}: {ex}")
                continue
            board.append((s, an, score(s, an)))
        ok = [b for b in board if b[2]["fit"] >= 15] or ([] if tier is week else board)
        if ok:
            ok.sort(key=lambda b: -b[2]["total"])
            out(f"song tier: {name}")
            return ok[0][0], ok[0][1], ok[0][2], [(b[0], b[2]) for b in ok[1:6]]
    raise RuntimeError("no usable song (no audio with a steady beat found in the MP3 folder)")


# ======================================================================= EVENTS
FLICK_CACHE = DATA / "flick_cache.json"
REFINE_CACHE = DATA / "refine_cache.json"
LOUD_CACHE = DATA / "loud_cache.json"
_FN_TIME = re.compile(r"(20\d\d)[.\-_ ]?(\d\d)[.\-_ ]?(\d\d)\D{1,6}?(\d\d)[.\-_:h ]?(\d\d)[.\-_:m ]?(\d\d)")


def flick_value(rec, cfg, t):
    """Mean optical-flow magnitude in the centre 30% of the frame during the 0.4 s before the kill."""
    import cv2
    import numpy as np
    cache = load_json(FLICK_CACHE, {})
    key = f"{file_key(rec['path'])}|{t:.2f}"
    if key in cache:
        return cache[key]
    cx, cy, cw, ch = content_rect(rec, cfg)
    x, y, w, h = int(cx + 0.35 * cw) & ~1, int(cy + 0.35 * ch) & ~1, int(0.3 * cw) & ~1, int(0.3 * ch) & ~1
    t0 = max(0.0, t - 0.47)
    r = run(["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", "0.5", "-i", rec["path"], "-an",
             "-vf", f"fps=15,crop={w}:{h}:{x}:{y},scale=96:54,format=gray", "-f", "rawvideo", "-"], timeout=30)
    fr = np.frombuffer(r.stdout, np.uint8)
    n = len(fr) // (96 * 54)
    v = 0.0
    if n >= 2:
        fr = fr[:n * 96 * 54].reshape(n, 54, 96)
        for i in range(1, n):
            fl = cv2.calcOpticalFlowFarneback(fr[i - 1], fr[i], None, 0.5, 2, 9, 2, 5, 1.1, 0)
            v = max(v, float(np.hypot(fl[..., 0], fl[..., 1]).mean()))
    cache[key] = round(v, 3)
    save_json(FLICK_CACHE, cache)
    return cache[key]


def clip_time(path):
    """Recording time from the filename (ShadowPlay / Outplayed style 'YYYY.MM.DD - HH.MM.SS'), else the file mtime."""
    m = _FN_TIME.search(Path(path).name)
    if m:
        try:
            return datetime.datetime(*[int(x) for x in m.groups()]).timestamp()
        except ValueError:
            pass
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def refine_kill(rec, det, cfg, k, cache):
    """Frame-exact time of the FIRST frame a kill row is visible, at the clip's native frame rate (detection samples 15 fps).
    Bright killfeed pixels in the row's box (widened for slide-in) reach half of their final count = the row is visible."""
    import numpy as np
    key = f"{file_key(rec['path'])}|{k['t']:.3f}|{det.d['stamp']}|r3"
    if key in cache:
        return cache[key]
    box = k.get("box")
    t = float(k["t"])
    if not box:
        return t
    t0 = max(0.0, t - 0.4)
    vf = region_filter(rec, det, cfg).replace(",format=bgr24", ",format=gray,showinfo")
    r = run(["ffmpeg", "-hide_banner", "-ss", f"{t0:.4f}", "-i", rec["path"], "-t", "0.75", "-an", "-vf", vf, "-vsync", "0",
             "-f", "rawvideo", "-pix_fmt", "gray", "-"], timeout=60)
    n = det.dw * det.dh
    frames = np.frombuffer(r.stdout, np.uint8)
    pts = [float(x) for x in re.findall(r"pts_time:\s*(-?[\d.]+)", r.stderr.decode(errors="replace"))]
    cnt = min(len(frames) // n, len(pts))
    res = t
    if cnt >= 3:
        fr = frames[:cnt * n].reshape(cnt, det.dh, det.dw)
        x0, y0, x1, y1 = box
        x0, x1 = max(0, x0 - 40), min(det.dw, x1 + 40)
        y0, y1 = max(0, y0 - 2), min(det.dh, y1 + 2)
        c = (fr[:, y0:y1, x0:x1] >= 180).sum(axis=(1, 2)).astype(float)
        ref = np.median(c[-3:])
        base = np.median(c[:3])
        if ref > base + 20:
            half = base + 0.5 * (ref - base)
            for i in range(1, cnt):
                if c[i] >= half and c[i - 1] < half and all(c[j] >= half for j in range(i, min(cnt, i + 3))):
                    res = round(t0 + pts[i], 4)
            if res == t:
                above = [i for i in range(cnt) if c[i] >= half]
                res = round(t0 + pts[above[0]], 4) if above else t
    cache[key] = res
    return res


SILENT_LUFS = -55.0                       # a track quieter than this is silent: never used for the game sound


def _track_onsets(path, i):
    """Number of gunshot-like transients (same detector as gun_onsets) in audio track i of a clip."""
    import numpy as np
    import librosa
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-map", f"0:a:{i}", "-vn", "-ac", "1", "-ar", "22050", "-f", "f32le", "-"],
                       capture_output=True, timeout=120)
    y = np.frombuffer(r.stdout, np.float32)
    if len(y) <= 22050:
        return 0
    hop = 256
    env = librosa.onset.onset_strength(y=y, sr=22050, hop_length=hop, fmin=500, fmax=9000)
    fr = librosa.onset.onset_detect(onset_envelope=env, sr=22050, hop_length=hop, units="frames", backtrack=False,
                                    pre_max=3, post_max=3, pre_avg=10, post_avg=10, delta=0.2, wait=5)
    thr = max(3.0 * float(np.median(env)), 0.15 * float(env.max()))
    return int(sum(1 for f in fr if env[f] >= thr))


def choose_track(lufs, ons, setting="auto"):
    """Which audio track carries the game sound. lufs / ons: loudness and gunshot-onset count per track (None = silent).
    Settings 1 / 2 / 3 force that track (when it exists and is not silent); auto: one track = it, several = the one with the most
    gunshot onsets, unsure (no clear winner) = the first track that is not silent. A silent track is never chosen.
    Returns (index, note)."""
    n = len(lufs)
    live = [i for i, v in enumerate(lufs) if v is not None and v > SILENT_LUFS]
    if not live:
        return 0, f"track 1 of {n} (every track silent)"
    forced = ""
    if str(setting) in ("1", "2", "3"):
        k = int(setting) - 1
        if k in live:
            return k, f"track {k + 1} of {n} (set in Settings)"
        forced = f"track {setting} set but {'missing' if k >= n else 'silent'}; "
    if n == 1 or len(live) == 1:
        return live[0], f"{forced}track {live[0] + 1} of {n}" + ("" if n == 1 else " (the only one with sound)")
    top = max(ons[i] or 0 for i in live)
    best = [i for i in live if (ons[i] or 0) == top]
    cnt = "/".join(str(ons[i] or 0) for i in range(n))
    if top >= 3 and len(best) == 1:
        return best[0], f"{forced}track {best[0] + 1} of {n} (auto: most gunshots, onsets {cnt})"
    return live[0], f"{forced}track {live[0] + 1} of {n} (auto: unsure, first track; onsets {cnt})"


def clip_audio(rec, setting="auto"):
    """{'stream': audio track used for the game sound, 'lufs': its loudness, 'n': tracks, 'note': why} - measurements cached."""
    if not rec.get("audio"):
        return {"stream": None, "lufs": None}
    cache = load_json(LOUD_CACHE, {})
    key = file_key(rec["path"]) + "|t2"
    m = cache.get(key)
    if not m:
        try:
            j = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "json",
                                rec["path"]]).stdout or b"{}")
            ns = len(j.get("streams") or []) or 1
        except Exception:
            ns = 1
        ns = min(ns, 4)
        lufs = [ebur128_lufs(rec["path"], i) for i in range(ns)]
        live = [i for i, v in enumerate(lufs) if v is not None and v > SILENT_LUFS]
        ons = [None] * ns
        if len(live) > 1:
            for i in live:
                try:
                    ons[i] = _track_onsets(rec["path"], i)
                except Exception:
                    ons[i] = 0
        m = {"lufs": lufs, "ons": ons}
        cache = load_json(LOUD_CACHE, {})
        cache[key] = m
        save_json(LOUD_CACHE, cache)
    i, note = choose_track(m["lufs"], m["ons"], setting)
    return {"stream": i, "lufs": m["lufs"][i], "n": len(m["lufs"]), "note": note}


def clip_audio_legacy(rec):
    """V5.55 audio path, kept verbatim as a selectable code path (Settings > Audio mode > Legacy): the game sound is the audio track
    with the highest integrated loudness; the per-game 'game audio track' setting is ignored. Cached under the V5.55 key."""
    if not rec.get("audio"):
        return {"stream": None, "lufs": None}
    cache = load_json(LOUD_CACHE, {})
    key = file_key(rec["path"])
    if key in cache and isinstance(cache[key], dict) and "stream" in cache[key]:
        return {**cache[key], "note": "legacy V5.55: loudest track"}
    try:
        j = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "json",
                            rec["path"]]).stdout or b"{}")
        ns = len(j.get("streams") or []) or 1
    except Exception:
        ns = 1
    best = {"stream": 0, "lufs": None, "all": []}
    for i in range(min(ns, 4)):
        v = ebur128_lufs(rec["path"], i)
        best["all"].append(v)
        if v is not None and (best["lufs"] is None or v > best["lufs"]):
            best.update(stream=i, lufs=v)
    cache = load_json(LOUD_CACHE, {})
    cache[key] = best
    save_json(LOUD_CACHE, cache)
    return {**best, "note": "legacy V5.55: loudest track"}


def audio_unusable(rec, au):
    """Why an Auto audio pick can't be used (None = fine): a clip with sound must get a real, non-silent track."""
    if not rec.get("audio"):
        return None
    if au.get("stream") is None:
        return "no audio track chosen for a clip that has sound"
    if au.get("lufs") is None or au["lufs"] <= SILENT_LUFS:
        return f"chosen track {au['stream'] + 1} is silent"
    return None


def resolve_clip_audio(rec, cfg, game, state):
    """Audio pick for one clip by Settings > Audio mode. state (one per plan) collects 'mode' and 'fallback' reasons.
    Auto (V5.56) that raises or yields a silent / missing track uses the Legacy V5.55 path for THAT clip only (V6.0), logged."""
    mode = cfg.get("audio_mode", "auto")
    if not rec.get("audio"):
        return {"stream": None, "lufs": None}
    if mode == "legacy":
        state["mode"] = "legacy"
        return clip_audio_legacy(rec)
    state.setdefault("mode", "auto")
    try:
        au = clip_audio_auto(rec, (cfg.get("game_audio_track") or {}).get(game, "auto"))
        why = audio_unusable(rec, au)
    except Exception as ex:
        au, why = None, f"Auto audio path raised {type(ex).__name__}: {ex}"
    if why is None:
        return au
    state.setdefault("clip_fallback", []).append(f"{Path(rec['path']).name}: {why}")      # V6.0: this clip only; Auto stays for the rest
    out(f"audio fallback for {Path(rec['path']).name}: {why}")
    return clip_audio_legacy(rec)


clip_audio_auto = lambda rec, setting="auto": clip_audio(rec, setting)      # V5.56 path (looked up at call time: tests may swap clip_audio)


def refine_shot(rec, t_hint, row_t, cache):
    """Sample-exact time of the FATAL SHOT = the moment the kill happens on screen (the killfeed row appears ~0.1-0.2 s later).
    The last strong attack in the clip's game audio between 0.7 s before the row and the row itself. None = no shot heard."""
    import numpy as np
    if not rec.get("audio"):
        return None
    key = f"{file_key(rec['path'])}|shot|{row_t:.3f}|s1"
    if key in cache:
        return cache[key]
    sr = 48000
    t0 = max(0.0, row_t - 0.75)
    r = run(["ffmpeg", "-v", "error", "-ss", f"{t0:.4f}", "-i", rec["path"], "-t", f"{row_t + 0.05 - t0:.4f}",
             "-map", f"0:a:{int(rec.get('a_stream', 0))}", "-ac", "1", "-ar", str(sr), "-af", "highpass=f=400",
             "-f", "f32le", "-"], timeout=60)
    y = np.abs(np.frombuffer(r.stdout, np.float32))
    res = None
    if len(y) > sr // 10:
        hop = 48                                             # 1 ms
        env = np.maximum.reduceat(y, np.arange(0, len(y), hop))
        base = np.median(env) + 1e-6
        thr = max(6 * base, 0.15 * env.max())
        idx = np.flatnonzero((env[1:] >= thr) & (env[:-1] < thr)) + 1
        if len(idx):
            j = idx[-1]
            pk = env[j:j + 20].max()
            k = j
            while k > 0 and env[k - 1] >= 0.3 * pk:
                k -= 1
            res = round(t0 + k * hop / sr, 4)
    cache[key] = res
    return res


def _frames_at(path, t, n=7, fps=60):
    """n small grey frames centred on time t (native timing) + their times, for stitch alignment checks."""
    import numpy as np
    t0 = max(0.0, t - (n // 2) / fps - 0.004)
    r = run(["ffmpeg", "-hide_banner", "-ss", f"{t0:.4f}", "-i", path, "-t", f"{(n + 1) / fps:.4f}", "-an",
             "-vf", "scale=192:108,format=gray,showinfo", "-vsync", "0", "-f", "rawvideo", "-"], timeout=60)
    fr = np.frombuffer(r.stdout, np.uint8)
    pts = [t0 + float(x) for x in re.findall(r"pts_time:\s*(-?[\d.]+)", r.stderr.decode(errors="replace"))]
    m = min(len(fr) // (192 * 108), len(pts))
    return fr[:m * 192 * 108].reshape(m, 108, 192).astype(np.float32), pts[:m]


def verify_stitch(spans, cut):
    """Checks the cut between two stitched clips: the frame of clip A at the cut must equal clip B's frame at the same game moment
    (no repeated or skipped frames). Returns (ok, corrected shift of B, report)."""
    import numpy as np
    a, b = spans
    fa, ta = _frames_at(a["path"], cut - a["shift"])
    fb, tb = _frames_at(b["path"], cut - b["shift"])
    if not len(fa) or not len(fb):
        return False, b["shift"], "could not read frames around the cut"
    ia = int(np.argmin([abs(x - (cut - a["shift"])) for x in ta]))
    errs = [(float(np.abs(fa[ia] - fb[j]).mean()), j) for j in range(len(fb))]
    best, j = min(errs)
    ib = int(np.argmin([abs(x - (cut - b["shift"])) for x in tb]))
    others = sorted(e for e, jj in errs if abs(jj - j) >= 2)
    ref = others[len(others) // 2] if others else 99.0
    if best > 4.0 or best > 0.35 * ref:                    # the same game moment must match clearly better than its neighbours
        return False, b["shift"], f"no clearly matching frame at the cut (difference {best:.1f} vs {ref:.1f} for other frames)"
    new_shift = round(b["shift"] - (tb[j] - tb[ib]), 4) if j != ib else b["shift"]
    return True, new_shift, f"frames match at the cut (difference {best:.1f}, {'aligned' if j == ib else f'corrected by {j - ib} frame(s)'})"


def base_score(ev):
    """ace > 4k > 3k > fast double > flick or headshot single > plain kills."""
    n = ev["n"]
    if n >= 5:
        s = 100.0
    elif n == 4:
        s = 80.0
    elif n == 3:
        s = 60.0
    elif n == 2:
        s = 42.0 if ev["span"] <= 2.5 else 26.0
    else:
        s = 8.0 + (14 if (ev.get("flick") or ev["hs"]) else 0) + (4 if (ev.get("flick") and ev["hs"]) else 0)
    if n >= 2:
        s += min(6.0, 6.0 * n / (ev["span"] + 1.0) / 2) + 2 * min(ev["hs"], 2)
    return s


def _victim_offset(ka, kb, rf=None):
    """Timeline offset between two clips from a shared victim (fuzzy >= 80): t_in_a - t_in_b, or None. rf refines kill times to
    the exact frame so stitched clips line up without repeated or skipped frames."""
    from rapidfuzz import fuzz
    best = None
    for x in ka:
        for y in kb:
            a, b = _alnum((x.get("victim") or "").lower()), _alnum((y.get("victim") or "").lower())
            if a and b and fuzz.ratio(a, b) >= 80:
                sc = fuzz.ratio(a, b)
                if best is None or sc > best[0]:
                    best = (sc, (rf(x) - rf(y)) if rf else (x["t"] - y["t"]))
    return None if best is None else best[1]


def _same_kills(ia, ib, rf, cache):
    """V5.42B: do two clips show the SAME kills, whatever their file times say (a copy, a re-export, a trimmed duplicate)?
    Same victims at matching times: 2+ shared victims at one consistent offset (+-0.35 s), or one shared victim whose kill
    frame is the same footage in both files. Returns the timeline offset (t_in_a - t_in_b) or None."""
    from rapidfuzz import fuzz
    v = lambda k: _alnum((k.get("victim") or "").lower())
    pairs = [(x, y) for x in ia["kills"] for y in ib["kills"] if len(v(x)) >= 3 and len(v(y)) >= 3 and fuzz.ratio(v(x), v(y)) >= 80]
    if not pairs:
        return None
    best = None
    for x0, y0 in pairs:
        o = x0["t"] - y0["t"]
        grp = [(x, y) for x, y in pairs if abs(x["t"] - y["t"] - o) <= 0.35]
        n = min(len({id(x) for x, _ in grp}), len({id(y) for _, y in grp}))
        if best is None or n > best[0]:
            best = (n, x0, y0)
    n, x, y = best
    o = rf(x) - rf(y)
    if n >= 2:
        return o
    key = f"dup|{file_key(ia['rec']['path'])}|{file_key(ib['rec']['path'])}|{x['t']:.3f}|{y['t']:.3f}"
    if key not in cache:
        try:
            cache[key] = verify_stitch(({"path": ia["rec"]["path"], "shift": 0.0}, {"path": ib["rec"]["path"], "shift": o}),
                                       rf(x))[0]
        except Exception:
            cache[key] = False
    if cache[key]:
        return o
    # V5.43: frames can differ between two captures of one moment: a 1-2 kill clip whose victims ALL appear (same names, 90+) in
    # the other clip, recorded within 10 minutes, is that clip's duplicate - one kill is never placed twice
    small, big = (ia, ib) if len(ia["kills"]) <= len(ib["kills"]) else (ib, ia)
    names = lambda it: [v(k) for k in it["kills"]]
    if len(small["kills"]) <= 2 and abs(ia.get("ctime", 0) - ib.get("ctime", 0)) <= 600 and \
            all(len(x) >= 4 and any(fuzz.ratio(x, y) >= 90 for y in names(big)) for x in names(small)):
        return o
    return None


# ======================================================================= CLIP TIME ANCHORS + KILL LEDGER (V6.9.7)
# A clip's file-name time is NOT always its start: OBS replay names ("Replay 2026-09-11 17-00-37.mov", "VALORANT 2026-10-07 03-40.mov",
# "... 03-40 (2).mov") show the SAVE time = the END of the clip; ShadowPlay / Outplayed "... 22.55.31.02.DVR.mp4" names are start times (V6.9).
# clip_anchor() gives every clip an absolute [start, end] with the evidence used; the file's modified time (the moment OBS closed the file) is
# the cross-check. Nothing here changes detection: the anchors only decide which clips MAY be merged (proof rule below) and how the CS2 clip
# time index orders clips.
_OBS_NAME = re.compile(r"(20\d\d)-(\d\d)-(\d\d)[ _T](\d\d)-(\d\d)(?:-(\d\d))?(?:\s*\((\d+)\))?\s*\.[A-Za-z0-9]{2,4}$")
ANCHOR_TOL_S = 6.0                      # the file's modified time may differ from the name time by this much (name seconds, OBS flush)


def name_time_info(path):
    """{t, res ('sec' | 'min'), scheme ('obs' | 'dvr' | 'name'), default ('end' | 'start'), seq} from the file name, or None (unparsable: never guessed)."""
    name = Path(str(path)).name
    m = _OBS_NAME.search(name)
    try:
        if m:
            y, mo, d, h, mi, s, n = m.groups()
            return {"t": datetime.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s or 0)).timestamp(), "res": "sec" if s is not None else "min",
                    "scheme": "obs", "default": "end", "seq": int(n) if n else 1}
        m = _FN_TIME.search(name)
        if m:
            return {"t": datetime.datetime(*[int(x) for x in m.groups()]).timestamp(), "res": "sec", "scheme": "dvr" if "DVR" in name else "name",
                    "default": "start", "seq": 1}
    except ValueError:
        pass
    return None


def clip_anchor(path, dur=None, mtime=None):
    """Absolute time range of a clip: {start, end, side ('start' | 'end': what the name time means), verified (modified time agrees), provable
    (usable as proof evidence), how, scheme, res, name_t, seq} or None (unparsable name / no duration).
      second-resolution names: the scheme's default (OBS = save time = END, DVR / Outplayed = START) is checked against the modified time:
        mtime ~ name time -> END, mtime ~ name time + duration -> START (the evidence overrides the default); neither (a copied file) ->
        the default, marked unverified.
      minute-only names (OBS without seconds): the name only gives the minute, so the modified time (second precision) IS the save time = END,
        but only while it lies inside the named minute; a copied / touched file is NOT provable (never guessed).
    '(2)' suffixes are separate saves: ordering is by the anchored time (modified time), never by the name."""
    info = name_time_info(path)
    if info is None or not dur or float(dur) <= 0:
        return None
    dur = float(dur)
    if mtime is None:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
    T = info["t"]
    res = {"scheme": info["scheme"], "res": info["res"], "name_t": T, "seq": info["seq"], "mtime": mtime, "dur": dur}
    if info["res"] == "min":
        if mtime is not None and T - ANCHOR_TOL_S <= mtime < T + 60 + ANCHOR_TOL_S:
            return dict(res, start=mtime - dur, end=mtime, side="end", verified=True, provable=True,
                        how="minute-only name: the modified time (second precision) is the save time = the clip END")
        return dict(res, start=T + 30 - dur, end=T + 30, side="end", verified=False, provable=False,
                    how="minute-only name and the modified time is not inside that minute: time unknown (never guessed)")
    ev_end = mtime is not None and abs(mtime - T) <= ANCHOR_TOL_S
    ev_start = mtime is not None and abs(mtime - (T + dur)) <= ANCHOR_TOL_S
    if ev_end and not ev_start:
        side, ver, how = "end", True, "name time = save time (modified time agrees)"
    elif ev_start and not ev_end:
        side, ver, how = "start", True, "name time = start (modified time = name time + duration)"
    elif ev_end and ev_start:
        side, ver, how = info["default"], True, f"short clip: modified time fits both ends, scheme default ({info['default']})"
    else:
        side, ver, how = info["default"], False, f"modified time fits neither end, scheme default ({info['default']}) - unverified"
    st = T if side == "start" else T - dur
    return dict(res, start=st, end=st + dur, side=side, verified=ver, provable=True, how=how)


def clip_ctime(rec):
    """Anchored START of a clip (events are ordered by it); the old modified-time fallback for unparsable names."""
    a = clip_anchor(rec["path"], rec.get("dur"))
    return a["start"] if a else clip_time(rec["path"])


KILL_STATES = ("PLACED", "MERGED_DUP", "RANKED_OUT", "CLIP_UNUSABLE", "OVERRIDE_ADMITTED", "LOST")
GROUP_MAX_CLIPS = 4                     # the V6.9 fight-size limit (PAIR_MAX_EXTRA + 1)
DUP_WINDOW_S = 1.5                      # the existing duplicate window (same victim within 1.5 s = one kill)
PROOF_CAP_S = 5.0                       # the whole proof step of one build_events() call (frame matching included); then 'not proven'
PROOF_TEST_HOOK = [None]                # tests only: called inside a proof (inject an error / a delay)
LEDGER_TEST_HOOK = [None]               # tests only: called with (events, ledger) before the loss check (drop an event artificially)
CUR_LEDGER = [None]                     # the ledger of the build_events() call in progress
LAST_LEDGER = [None]                    # the ledger of the last top-level build_events() call (make_plan completes it with the plan)
LEDGER_SUBCALL = [False]                # build_events() called by pairing_replace_events(): partners are never planned alone, no safety net there


class KillLedger:
    """Every usable kill row gets an ID when selection starts and ends in exactly one state: PLACED, MERGED_DUP (survivor + proof), RANKED_OUT,
    CLIP_UNUSABLE or OVERRIDE_ADMITTED (utility override, part B); a row in none of them is LOST (and the safety net re-queues it once)."""

    def __init__(self, game=None):
        self.game, self.rows, self.idx, self.events = game, [], {}, {}
        self.released, self.lines, self.proofs, self.warn, self.splits = [], [], [], [], []
        self.final_events = []

    @staticmethod
    def rkey(path, t, victim):
        return (_pkey(path), round(float(t), 3), _alnum((victim or "").lower()))

    def add_pool(self, items):
        for it in items:
            for k in it["kills"]:
                key = self.rkey(it["rec"]["path"], k["t"], k.get("victim"))
                if key in self.idx:
                    continue
                row = {"id": len(self.rows) + 1, "clip": Path(it["rec"]["path"]).name, "path": it["rec"]["path"], "t": float(k["t"]),
                       "victim": k.get("victim") or "", "state": None, "info": {}, "tag": "util" if k.get("util") else "", "gone": None,
                       "unusable": None, "merged": None, "released": False, "k": k, "it": it}
                self.rows.append(row)
                self.idx[key] = row

    def row(self, it, k):
        return self.idx.get(self.rkey(it["rec"]["path"], k["t"], k.get("victim")))

    def row_of_cl(self, kd):
        return self.row(kd["src"], kd)

    @staticmethod
    def evkey(ev):
        return (ev["path"], tuple(ev["times"]))

    def note_event(self, ev, rows):
        self.events[self.evkey(ev)] = [r["id"] for r in rows if r]

    def reconcile(self, evs):
        """A duplicate row that an event covers while its survivor is in no event (the survivor's event was rebuilt without it, e.g. after a rejected stitch):
        the covered row becomes the survivor, so the kill is placed exactly once (never twice, never lost)."""
        cov = self.covered(evs)
        for d in self.rows:
            m = d["merged"]
            if m and d["id"] in cov and m["into"] not in cov:
                r = self.rows[m["into"] - 1]
                r["merged"] = dict(m, into=d["id"], pair=list(reversed(m.get("pair", []))))
                d["merged"] = None

    def covered(self, evs):
        got = set()
        for e in evs:
            got.update(self.events.get(self.evkey(e), []))
        return got

    def lost_rows(self, evs):
        cov = self.covered(evs)
        return [r for r in self.rows if r["id"] not in cov and not r["merged"] and not r["unusable"]]

    def label(self, r):
        return f"{r['clip']} @ {ts(r['t'])} -> {r['victim'] or '?'}"


def _proof_gate(budget, fn):
    """Runs fn() inside the proof budget: a hang / error / timeout is 'not proven' (the caller keeps the events separate)."""
    if budget["t0"] is None:
        budget["t0"] = time.monotonic()
    left = budget["cap"] - (time.monotonic() - budget["t0"])
    if budget["dead"] or left <= 0:
        budget["dead"] = True
        raise TimeoutError(f"proof step over its {budget['cap']:.0f} s cap")
    box = {}

    def work():
        try:
            if PROOF_TEST_HOOK[0]:
                PROOF_TEST_HOOK[0]()
            box["r"] = fn()
        except BaseException as ex:                          # noqa: BLE001
            box["e"] = ex
    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(left)
    if th.is_alive():
        budget["dead"] = True
        raise TimeoutError(f"proof step over its {budget['cap']:.0f} s cap")
    if "e" in box:
        raise box["e"]
    return box["r"]


def prove_same_fight(a, b, rf, budget):
    """PROOF that clip b continues / duplicates clip a (a starts first by its anchored time). Returns ({offset, ...proof}, '') or (None, why).
    ALL of: (a) the clips' absolute time ranges (corrected anchors) overlap; (b) the overlap is verified with the existing frame match
    (verify_stitch at the aligned offset, inside the overlap); (c) a same-victim kill pair agrees after applying the offset (the existing
    1.5 s duplicate window after the frame-verified offset is applied, and the offset itself within the 12 s continuation window of the clip times). Victim name alone, time proximity alone or a chain
    of such links never links two clips. offset = time in a - time in b of the same moment (the same convention as _victim_offset)."""
    from rapidfuzz import fuzz
    aa, ab = a.get("anc"), b.get("anc")
    if not aa or not ab or not aa["provable"] or not ab["provable"]:
        return None, "clip time not provable (" + (", ".join(Path(x["rec"]["path"]).name for x, an in ((a, aa), (b, ab)) if not an or not an["provable"])) + ")"
    ov = min(aa["end"], ab["end"]) - max(aa["start"], ab["start"])
    if ov < -PAIR_MAX_GAP_S:                                    # (a) the existing continuation window (V6.9): overlapping, or at most PAIR_MAX_GAP_S apart
        return None, f"time ranges neither overlap nor lie within the {PAIR_MAX_GAP_S:.0f} s continuation window (gap {-ov:.1f} s)"
    off_abs = ab["start"] - aa["start"]                         # a-time of a moment = b-time + off_abs
    win = PAIR_MAX_GAP_S                                        # the kill pair's offset must agree with the clip times within that same window
    cands = []
    for x in a["kills"]:
        for y in b["kills"]:
            va, vb = _alnum((x.get("victim") or "").lower()), _alnum((y.get("victim") or "").lower())
            if va and vb and fuzz.ratio(va, vb) >= 80:
                d = abs((x["t"] - y["t"]) - off_abs)
                if d <= win:
                    cands.append((d, -fuzz.ratio(va, vb), x, y))
    if not cands:
        return None, "no same-victim kill pair whose times agree with the clip times"
    cands.sort(key=lambda c: (c[0], c[1]))
    why = "no candidate"
    for d, _, x, y in cands[:2]:                                # frames decide: a bogus name match from another round never matches
        o = rf(x) - rf(y)
        va_, vb_ = a["rec"].get("v_off", 0.0), b["rec"].get("v_off", 0.0)
        ea, eb = a["rec"].get("dur", 0) - 0.08, o + b["rec"].get("dur", 0) - 0.08
        lo, hi = max(max(0.05, va_), o + max(0.05, vb_)), min(ea, eb)
        if hi - lo < 0.1:
            why = "overlap at the aligned offset is under 0.1 s"
            continue
        cut = round((lo + hi) / 2, 4)
        ok, nshift, vw = _proof_gate(budget, lambda: verify_stitch(({"path": a["rec"]["path"], "shift": 0.0}, {"path": b["rec"]["path"], "shift": o}), cut))
        if ok:
            m = re.search(r"difference ([\d.]+)", vw)
            return {"offset": float(nshift), "raw_offset": float(o), "cut": cut, "victim": x.get("victim") or "", "ax": float(x["t"]), "bx": float(y["t"]),
                    "agree_s": round(d, 2), "score": float(m.group(1)) if m else None, "match": vw, "overlap_s": round(ov, 1)}, ""
        why = "frames do not match: " + vw
    return None, why


def _ledger_gone(cl, ev, why):
    """Rows of cluster cl that the rebuilt event ev does not cover (all of them when ev is None) get the reason they would be lost."""
    led = CUR_LEDGER[0]
    if led is None:
        return
    cov = set(led.events.get(led.evkey(ev), [])) if ev else set()
    for kd in cl:
        r_ = led.row_of_cl(kd)
        if r_ and r_["id"] not in cov and not r_["gone"]:
            r_["gone"] = why


def ledger_safety_net(led, evs, game, cfg, det, refine, gap):
    """A4: rows that no event covers (removed by a rejected stitch / a failed group / an earlier stage) are re-queued ONCE as independent events
    (single clip, never stitched, the same make_event()), so ranking and planning treat them like any other event. A run in which nothing was lost
    is not touched. Rows still lost after the retry stay LOST and finish with a loud warning (ledger_finalize)."""
    led.reconcile(evs)
    lost = led.lost_rows(evs)
    if not lost:
        return
    by_clip = {}
    for r in lost:
        by_clip.setdefault(r["path"], []).append(r)
    made = []
    for path, rows in by_clip.items():
        it = rows[0]["it"]
        rows.sort(key=lambda r: r["t"])
        revs = sorted(it.get("revives", []))
        clusters, cur = [], [rows[0]]
        for r in rows[1:]:                                 # the same fight rule as build_events(): split only on a long gap with no revive in it
            if r["t"] - cur[-1]["t"] <= gap or any(cur[-1]["t"] < rv < r["t"] for rv in revs):
                cur.append(r)
            else:
                clusters.append(cur)
                cur = [r]
        clusters.append(cur)
        for cl_rows in clusters:
            cl = [dict(r["k"], tt=float(r["k"]["t"]), src=it, off=0.0) for r in cl_rows]
            try:
                ev = make_event(cl, [(it, 0.0)], det, cfg, refine)
            except Exception:                              # noqa: BLE001
                ev = None
            if ev:
                evs.append(ev)
                made.append((ev, cl_rows))
    for n_, (ev, cl_rows) in enumerate(made, 1):
        for r in cl_rows:
            r["released"] = True
        r0 = cl_rows[0]
        why = r0["gone"] or "removed between grouping and event building"
        extra = f" (+{len(cl_rows) - 1} more kill(s) of that fight)" if len(cl_rows) > 1 else ""
        line = f"safety net: released {len(made)} event(s): {led.label(r0)}{extra} (it would have been lost: {why})"
        led.lines.append(line)
        led.released.append(line)
        out(line)


def ledger_finalize(led, picked, planned, plan):
    """Ends every row in exactly one state (see KillLedger) from the events that were built, picked (weekly / pairing) and planned and the plan itself."""
    evmap = {}
    for e in list(led.final_events) + list(picked or []) + list(planned or []):
        evmap[KillLedger.evkey(e)] = e
    picked_k = {KillLedger.evkey(e) for e in (picked or [])}
    planned_k = {KillLedger.evkey(e) for e in (planned or [])}
    takes = plan.get("takes", [])
    skipped_names = [x[0] for x in (plan.get("fit") or {}).get("skipped", [])]

    def placed(e):
        for t in takes:
            for ts_ in (e["times"], e.get("times_v4") or e["times"]):
                if t["path"] == e["path"] and len(t.get("kills", [])) == len(ts_) and all(abs(a - b) < 2e-4 for a, b in zip(t["kills"], ts_)):
                    return True
        return False
    order = sorted(evmap, key=lambda k: -(evmap[k].get("score") or 0))
    rank = {k: i + 1 for i, k in enumerate(order)}
    row_ev = {}
    for k, ids in led.events.items():
        if k in evmap:
            for i in ids:
                row_ev.setdefault(i, []).append(k)
    for r in led.rows:
        r["state"], r["info"] = None, {}
        if r["merged"]:
            r["state"] = "MERGED_DUP"
            tgt = led.rows[r["merged"]["into"] - 1]
            pr = r["merged"].get("proof") or {}
            r["info"] = {"survivor": led.label(tgt), "survivor_id": tgt["id"], "pair": [Path(p).name for p in r["merged"].get("pair", [])],
                         "offset": round(pr["raw_offset"], 3) if pr else None, "score": pr.get("score") if pr else None, "match": pr.get("match") if pr else "same clip: existing 1.5 s duplicate rule"}
            continue
        keys = row_ev.get(r["id"], [])
        best = None
        for k in keys:
            e = evmap[k]
            nm = Path(e["path"]).name
            if placed(e):
                st, inf = ("OVERRIDE_ADMITTED" if r["tag"] == "util" else "PLACED"), {"take": nm}
            elif k in planned_k and nm in skipped_names:
                st, inf = "CLIP_UNUSABLE", {"reason": "cannot form a take: " + why_no_take(e)}
            elif k not in picked_k:
                st, inf = "RANKED_OUT", {"rank": rank.get(k), "reason": "not picked: already used in a montage / outside this week's pick"}
            elif k not in planned_k:
                st, inf = "CLIP_UNUSABLE", {"reason": "cut list repair: its kill row lies outside the take's footage"}
            else:
                st, inf = "RANKED_OUT", {"rank": rank.get(k), "reason": "left out by the target / length limit"}
            pri = {"PLACED": 0, "OVERRIDE_ADMITTED": 0, "CLIP_UNUSABLE": 1, "RANKED_OUT": 2}[st]
            if best is None or pri < best[0]:
                best = (pri, st, inf)
        if best:
            r["state"], r["info"] = best[1], best[2]
        elif r["unusable"]:
            r["state"], r["info"] = "CLIP_UNUSABLE", {"reason": r["unusable"]}
        else:
            r["state"], r["info"] = "LOST", {"reason": r["gone"] or "no event covers it"}
        if r["released"]:
            r["info"]["released"] = True
    return led


def ledger_summary(led):
    c = {s: sum(1 for r in led.rows if r["state"] == s) for s in KILL_STATES}
    ov = c["OVERRIDE_ADMITTED"]
    rel = sum(1 for r in led.rows if r["released"])
    line = (f"kill ledger: {len(led.rows)} usable, {c['PLACED'] + ov} placed, {c['MERGED_DUP']} merged as proven duplicates, {c['RANKED_OUT']} ranked out, "
            f"{c['CLIP_UNUSABLE']} unusable, {c['LOST']} lost, {rel} released by safety net")
    return line + (f" [{ov} of the placed via utility override]" if ov else "")


def ledger_report(led):
    """The ledger lines of one run: the summary, one line per MERGED_DUP with its proof, one per released event, the loud warning when rows are LOST."""
    lines = [ledger_summary(led)]
    for r in led.rows:
        if r["state"] == "MERGED_DUP":
            i = r["info"]
            lines.append(f"  merged duplicate: {led.label(r)} = {i['survivor']} (proof: {' / '.join(i['pair']) or 'same clip'}, offset "
                         f"{('%+.2f s' % i['offset']) if i['offset'] is not None else 'n/a'}, frame match {i['match']})")
    lines += ["  " + x for x in led.released]
    lines += ["  " + x for x in led.splits]
    lost = [r for r in led.rows if r["state"] == "LOST"]
    if lost:
        lines.append(f"!!! KILL LEDGER WARNING: {len(lost)} kill row(s) are LOST and could not be recovered by the safety net:")
        lines += [f"!!!   {led.label(r)} ({r['info'].get('reason')})" for r in lost]
    return lines


def ledger_save(led, plan=None):
    rows = [{"id": r["id"], "clip": r["clip"], "t": round(r["t"], 3), "victim": r["victim"], "state": r["state"], "info": r["info"], "tag": r["tag"],
             "released": r["released"]} for r in led.rows]
    obj = {"saved": time.strftime("%Y-%m-%d %H:%M:%S"), "game": led.game, "summary": ledger_summary(led), "lines": ledger_report(led), "rows": rows,
           "proofs": led.proofs, "splits": led.splits}
    save_json(DATA / "ledger_last.json", obj)


def cmd_timeanchor(args):
    """V6.9.7: python montage.py timeanchor. Read-only audit of what the time in a clip's file name means (START or END of the clip) per naming
    scheme, from the cached clip records (name time, duration) and the file's modified time (the cache key): prints one table, writes timeanchor.txt next to
    montage.py, changes no cache, flag or config file."""
    clips = load_json(CLIPS_CACHE, {})
    sch = {}
    for key, rec in clips.items():
        try:
            path, _size, mt = key.rsplit("|", 2)
            mt = float(mt)
        except ValueError:
            continue
        info, dur = name_time_info(path), rec.get("dur")
        label = "unparsable name" if info is None else {"obs": "OBS replay (YYYY-MM-DD HH-MM[-SS])", "dvr": "ShadowPlay / Outplayed DVR (YYYY.MM.DD - HH.MM.SS.cc)",
                                                        "name": "other name with a time"}[info["scheme"]] + (" [minute-only]" if info["res"] == "min" else "")
        d = sch.setdefault(label, {"n": 0, "end": 0, "start": 0, "both": 0, "neither": 0, "diffs_end": [], "diffs_start": [], "ex": []})
        d["n"] += 1
        if info is None or not dur:
            continue
        T, dur = info["t"], float(dur)
        e_end, e_start = abs(mt - T), abs(mt - (T + dur))
        d["diffs_end"].append(mt - T)
        d["diffs_start"].append(mt - (T + dur))
        ev_end, ev_start = e_end <= ANCHOR_TOL_S + (60 if info["res"] == "min" else 0), e_start <= ANCHOR_TOL_S
        d["end" if ev_end and not ev_start else "start" if ev_start and not ev_end else "both" if ev_end and ev_start else "neither"] += 1
        if len(d["ex"]) < 3:
            d["ex"].append(f"{Path(path).name}: dur {dur:.1f} s, modified {mt - T:+.1f} s from the name time, {mt - T - dur:+.1f} s from name time + duration")
    lines = ["timeanchor: what the file-name time means per naming scheme (modified time cross-check; END = the name time is the save time)"]
    for label, d in sorted(sch.items()):
        med = lambda v: statistics.median(v) if v else 0.0
        lines.append(f"  {label}: {d['n']} clips; modified time = name time (END): {d['end']}, = name time + duration (START): {d['start']}, both: {d['both']}, neither: {d['neither']}"
                     f" (median modified - name time {med(d['diffs_end']):+.1f} s, median modified - (name time + duration) {med(d['diffs_start']):+.1f} s)")
        lines += ["      e.g. " + x for x in d["ex"]]
    if not sch:
        lines.append("  no cached clip records: run a scan first")
    text = "\n".join(lines)
    (HERE / "timeanchor.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"(read-only; written to {HERE / 'timeanchor.txt'}; nothing else was changed)")


def cmd_ledger(args):
    """V6.9.7: python montage.py ledger. Read-only: reprints the last run's kill ledger from montage_data\\ledger_last.json (written by the run) or, failing
    that, from the log; writes ledger.txt next to montage.py; changes no cache, flag or config file."""
    obj = load_json(DATA / "ledger_last.json", None)
    if obj and obj.get("rows") is not None:
        lines = [f"last run's kill ledger ({obj.get('game')}, saved {obj.get('saved')}):"] + obj.get("lines", [])
        lines.append("")
        for r in obj["rows"]:
            inf = r.get("info") or {}
            det = inf.get("reason") or inf.get("survivor") or inf.get("take") or ""
            lines.append(f"  #{r['id']:<3} {r['state']:<18} {r['clip']} @ {ts(r['t'])} -> {r['victim'] or '?'}"
                         + (f"  [rank {inf['rank']}]" if inf.get("rank") else "") + ("  [util]" if r.get("tag") == "util" else "") + ("  [released]" if r.get("released") else "")
                         + (f"  ({det})" if det else ""))
    else:
        lines = []
        try:
            for l_ in (LOG_DIR / "montage.log").read_text(encoding="utf-8", errors="replace").splitlines():
                if "kill ledger:" in l_:
                    lines = ["(from montage.log; no ledger_last.json) " + l_]
        except OSError:
            pass
        lines = lines or ["no kill ledger saved yet: run a Dry plan first"]
    text = "\n".join(lines)
    (HERE / "ledger.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"(read-only; written to {HERE / 'ledger.txt'}; nothing else was changed)")


FIGHT_SPLIT_S = {"valorant": 10.0}     # kills of one clip are one fight unless this far apart (and no revive between them)


def fight_gap(cfg, game):
    return max(float(cfg["gap_s"][game]), FIGHT_SPLIT_S.get(game, 0.0))


def build_events(pool, game, cfg, rng, flick_budget=40):
    """Clip pool -> montage events. Knife / utility kills are excluded. Clips recorded within ~60 s of each other that share a
    victim are ONE event (union of kills): the clip covering most kills is used, or - if none shows them all - the clips are
    stitched back to back at the overlap. One event per clip, so no clip and no kill is ever used twice. Kill times are made
    frame-exact (first frame the row is visible)."""
    det = load_dets(game).get(game)
    gap = fight_gap(cfg, game)
    notes = []
    items = []
    for it in pool:
        ks = list(it["kills"])                             # V5.5: Valorant knife kills are normal kills
        if ks:
            items.append(dict(it, kills=sorted(ks, key=lambda k: k["t"]), ctime=clip_ctime(it["rec"]), anc=clip_anchor(it["rec"]["path"], it["rec"].get("dur"))))
    if LEDGER_SUBCALL[0] and LAST_LEDGER[0] is not None:   # partners (pairing_replace_events): known rows only, nothing new is 'usable' here
        led = LAST_LEDGER[0]
    else:
        led = KillLedger(game)                             # V6.9.7: every usable kill row gets an ID here (see KillLedger)
        led.add_pool(items)
    prev_led, CUR_LEDGER[0] = CUR_LEDGER[0], led
    try:
        return _build_events(items, game, cfg, rng, flick_budget, det, gap, notes, led)
    finally:
        CUR_LEDGER[0] = prev_led
        if not LEDGER_SUBCALL[0]:
            LAST_LEDGER[0] = led


def _build_events(items, game, cfg, rng, flick_budget, det, gap, notes, led):
    # duplicates / continuations
    refine = load_json(REFINE_CACHE, {})
    kref = {}
    for it in items:
        for k in it["kills"]:
            kref[id(k)] = it
    def rf(k):
        it = kref.get(id(k))
        if det is None or it is None or not k.get("box"):
            return k["t"]
        try:
            return refine_kill(it["rec"], det, cfg, k, refine)
        except Exception:
            return k["t"]
    items.sort(key=lambda i: i["ctime"])
    budget = {"cap": PROOF_CAP_S, "t0": None, "dead": False}
    proofs, links, memo = {}, set(), {}

    def proof_of(m, b):
        """Proof that clips m and b are the same fight (prove_same_fight), memoised; the offset is oriented m -> b (t_in_m - t_in_b)."""
        key = (id(m), id(b))
        if key in memo:
            return memo[key]
        sm, sb = (m["anc"] or {}).get("start", m["ctime"]), (b["anc"] or {}).get("start", b["ctime"])

        def attempt(x, y):
            try:
                pr_, why_ = prove_same_fight(x, y, rf, budget)
            except Exception as ex:                        # timeout / read error: NOT proven, the events stay separate
                return None, f"not proven ({type(ex).__name__}: {ex})"
            if pr_ and x is not m:                         # oriented m -> b
                pr_ = dict(pr_, offset=-pr_["offset"], raw_offset=-pr_["raw_offset"], ax=pr_["bx"], bx=pr_["ax"])
            return pr_, why_
        order = [(m, b), (b, m)] if sm <= sb else [(b, m), (m, b)]
        pr, why = attempt(*order[0])
        if not pr and abs(sm - sb) <= 1.0 and not budget["dead"]:      # one base time ('DVR', 'DVR_1', ...): which clip comes first is decided by the frame match
            pr2, why2 = attempt(*order[1])
            if pr2:
                pr, why = pr2, ""
        memo[key] = memo[(id(b), id(m))] = pr
        led.proofs.append({"a": Path(m["rec"]["path"]).name, "b": Path(b["rec"]["path"]).name, "proven": bool(pr), "why": why if not pr else "",
                           **({"offset": round(pr["raw_offset"], 3), "score": pr["score"], "match": pr["match"]} if pr else {})})
        return pr
    groups, used = [], set()
    for i, a in enumerate(items):
        if i in used:
            continue
        g = [(a, 0.0)]
        used.add(i)
        grew = True
        while grew:                                        # V6.9.6 (CS2): clips of one base time ('DVR', 'DVR_1', ...) sort in discovery order, so a clip
            grew = False                                   # scanned before the clip that links it to the group must be tried again
            for j in range(i + 1, len(items)):
                b = items[j]
                if j in used:
                    continue
                link = None
                for (m, mo) in g:                          # V6.9.7: a link needs PROOF (clip times overlap + frame match + kill times agree), per adjacent pair
                    if abs(b["ctime"] - m["ctime"]) > 60 + max(m["rec"].get("dur", 0), b["rec"].get("dur", 0)):
                        continue
                    pr = proof_of(m, b)
                    if pr:
                        link = (m, mo, pr)
                        break
                if link is None:
                    continue
                m, mo, pr = link
                if len(g) >= GROUP_MAX_CLIPS:              # the V6.9 fight-size limit: a longer chain splits; the boundary duplicate is merged by its pair proof
                    from rapidfuzz import fuzz
                    dups = {id(kb): (km, pr) for kb in b["kills"] for km in m["kills"]
                            if fuzz.ratio(_alnum((km.get("victim") or "").lower()), _alnum((kb.get("victim") or "").lower())) >= 80
                            and abs(km["t"] - (kb["t"] + pr["raw_offset"])) <= DUP_WINDOW_S}
                    b.setdefault("_dup", {}).update({k_: v_ for k_, v_ in dups.items()})
                    b["_dup_src"] = m
                    msg = (f"fight group limit: {Path(b['rec']['path']).name} is proven adjacent to {Path(m['rec']['path']).name} but the group "
                           f"already has {GROUP_MAX_CLIPS} clips - it starts a new group (chain split into proven adjacent pairs)")
                    led.splits.append(msg)
                    continue
                g.append((b, mo + pr["raw_offset"]))
                links.add((id(m), id(b)))
                links.add((id(b), id(m)))
                proofs[(id(m), id(b))] = proofs[(id(b), id(m))] = pr
                used.add(j)
                notes.append(f"clips proven to show the same fight: {Path(m['rec']['path']).name} / {Path(b['rec']['path']).name} "
                             f"(frames {pr['match'].split(' (')[-1].rstrip(')')}, clip times agree within {pr['agree_s']} s)")
                grew = game == "cs2"
        groups.append(g)
    evs = []
    for g in groups:
        # union of kills on the timeline of the group's first clip (kills of the same victim within 1.5 s are one kill) - V6.9.7: only kills of
        # the SAME clip or of a PROVEN adjacent pair (proofs of the group links) are ever merged; no chaining through a third clip
        allk = []
        for it, off in g:
            for k in it["kills"]:
                if id(k) in it.get("_dup", {}):            # duplicate of a kill in the previous group (chain split): never placed twice
                    km, pr = it["_dup"][id(k)]
                    srow, drow = led.row(it["_dup_src"], km), led.row(it, k)
                    if srow and drow and not drow["merged"]:
                        drow["merged"] = {"into": srow["id"], "proof": pr, "pair": [it["_dup_src"]["rec"]["path"], it["rec"]["path"]], "split": True}
                    continue
                tt = k["t"] + off
                dup = next((u for u in allk if abs(tt - u["tt"]) <= DUP_WINDOW_S and _alnum(u.get("victim", "").lower()) == _alnum(k.get("victim", "").lower())
                            and (u["src"] is it or (id(u["src"]), id(it)) in links)), None)
                if dup is None:
                    allk.append(dict(k, tt=tt, src=it, off=off))
                else:
                    srow, drow = led.row(dup["src"], dup), led.row(it, k)
                    pr = proofs.get((id(dup["src"]), id(it)))
                    if srow and drow and not drow["merged"]:
                        drow["merged"] = {"into": srow["id"], "proof": pr, "pair": [dup["src"]["rec"]["path"], it["rec"]["path"]]}
        if not allk:
            continue
        if len(g) > 1:
            notes.append("merged continuation/duplicate clips: " + " + ".join(Path(it["rec"]["path"]).name for it, _ in g)
                         + f" ({len(allk)} distinct kills)")
        # events by kill spacing on the group timeline
        allk.sort(key=lambda k: k["tt"])
        revs = sorted(rv + off for it, off in g for rv in it.get("revives", []))
        clusters, cur = [], [allk[0]]
        for k in allk[1:]:                                 # one fight = one event: split only on a long gap with no revive in it
            if k["tt"] - cur[-1]["tt"] <= gap or any(cur[-1]["tt"] < rv < k["tt"] for rv in revs):
                cur.append(k)
            else:
                clusters.append(cur)
                cur = [k]
        clusters.append(cur)
        best_ev, cands = None, []
        for cl in clusters:
            # which clips cover which kills (a clip covers a kill it detected itself)
            cover = {id(it): [k for k in cl if k["src"] is it or any(abs(k["tt"] - (x["t"] + off)) <= 0.3 for x in it["kills"])]
                     for it, off in g}
            it, off = max(g, key=lambda p: (len(cover[id(p[0])]), p[0]["rec"].get("dur", 0)))
            parts = [(it, off)]
            if len(cover[id(it)]) < len(cl):                     # stitch: add clips for the kills the main clip does not show
                missing = [k for k in cl if k not in cover[id(it)]]
                for it2, off2 in g:
                    if it2 is it or not any(k in cover[id(it2)] for k in missing):
                        continue
                    parts.append((it2, off2))
            ev = make_event(cl, parts, det, cfg, refine)
            if ev:
                cands.append((ev, cl))
                if best_ev is None or ev["score_pre"] > best_ev["score_pre"]:
                    best_ev = ev
            else:
                for kd in cl:
                    r_ = led.row_of_cl(kd)
                    if r_ and not r_["gone"]:
                        r_["gone"] = "no event could be built for its fight (stitch rejected and no single clip shows it, or it is outside the footage)"
        for ev, cl in cands:
            if ev is not best_ev:
                for kd in cl:
                    r_ = led.row_of_cl(kd)
                    if r_ and not r_["gone"] and not r_["unusable"]:
                        r_["unusable"] = "second fight of the same group: one event per clip / group (existing planner rule)"
        if best_ev:
            evs.append(best_ev)
    if LEDGER_TEST_HOOK[0]:
        LEDGER_TEST_HOOK[0](evs, led)
    if not LEDGER_SUBCALL[0]:
        try:
            ledger_safety_net(led, evs, game, cfg, det, refine, gap)
        except Exception as ex:                            # the safety net never fails a run
            led.lines.append(f"safety net skipped: {type(ex).__name__}: {ex}")
    for msg in led.splits:
        notes.append(msg)
    save_json(REFINE_CACHE, refine)
    singles = [e for e in evs if e["n"] == 1 and not e["hs"]]
    rng.shuffle(singles)
    for e in singles[:flick_budget]:
        try:
            e["flick"] = flick_value(e["rec"], cfg, e["first"]) >= 2.5
        except Exception:
            pass
    for e in evs:
        e["score"] = base_score(e) + 2.0 * e["shots"]
        e["plain"] = e["n"] == 1 and not e["hs"] and not e["flick"]
    evs.sort(key=lambda e: -e["score"])
    led.final_events = list(evs)
    return evs, notes


def make_event(cl, parts, det, cfg, refine, verify=True):
    """One event from a kill cluster. parts = [(pool item, timeline offset), ...]; >1 part = stitched continuation.
    times = the KILL MOMENTS (refined fatal shot; else the frame-exact row time minus this clip's measured shot->row lag);
    rows = frame-exact first frames of the killfeed rows; times_v4 = V4's kill times (for synccompare)."""
    main, moff = parts[0]
    raw = []
    for k in cl:
        src, off = k["src"], k["off"]
        row = k["t"]
        if det is not None and k.get("box"):
            try:
                row = refine_kill(src["rec"], det, cfg, k, refine)
            except Exception:
                pass
        shot = None
        if k.get("shot_t") is not None:
            try:
                shot = refine_shot(src["rec"], k["shot_t"], row, refine)
            except Exception:
                shot = None
            if shot is not None and not (row - 0.7 <= shot <= row + 0.02):
                shot = None
        v4t = k.get("shot_t", k["t"] - 0.1) if k.get("shot") else k["t"] - 0.1
        raw.append({"row": row + off - moff, "shot": None if shot is None else shot + off - moff, "v4": v4t + off - moff,
                    "victim": k.get("victim", ""), "hs": bool(k.get("hs")), "has_shot": bool(k.get("shot")), "k": k})
    lags = [r["row"] - r["shot"] for r in raw if r["shot"] is not None]
    lag = float(statistics.median(lags)) if lags else 0.10
    for r in raw:
        r["t"] = r["shot"] if r["shot"] is not None else r["row"] - lag
    raw.sort(key=lambda r: r["t"])
    times = [round(r["t"], 4) for r in raw]
    rows = [round(r["row"], 4) for r in raw]
    victims = [r["victim"] for r in raw]
    hs = sum(r["hs"] for r in raw)
    shots = sum(r["has_shot"] for r in raw)
    spans = []
    for it, off in parts:
        o = off - moff
        start = o + max(0.05, it["rec"].get("v_off", 0.0))
        end = o + it["rec"].get("dur", 0) - 0.08
        spans.append({"it": it, "shift": o, "start": start, "end": end, "path": it["rec"]["path"]})
    spans.sort(key=lambda s: s["start"])
    stitch_note = ""
    order_bad = ""
    if len(spans) > 1 and (spans[0]["it"]["rec"].get("game") == "cs2"):
        # V6.9.6: the order of a stitched CS2 group is CHRONOLOGICAL BY THE RECORDING TIME in the clip names (the 'pair partner' time index), not
        # whatever order the victim-matched offsets or the discovery order give. Clips of one base time ('DVR', 'DVR_1', 'DVR_1_1') tie: they keep
        # the offset order and the frame-match verification below decides between the two possible orders. Unparsable names: the old order.
        nts = [pair_clip_start(s_["path"]) for s_ in spans]
        if all(t_ is not None for t_ in nts):
            spans = [s_ for _, s_ in sorted(zip(range(len(spans)), spans), key=lambda x: (nts[x[0]], x[1]["start"], x[1]["end"]))]
            nts = sorted(nts)
            if any(spans[i + 1]["start"] < spans[i]["start"] - 0.5 and nts[i + 1] > nts[i] for i in range(len(spans) - 1)):
                order_bad = "the recording times in the clip names disagree with the kill offsets (order by name: " + \
                            " < ".join(Path(s_["path"]).name for s_ in spans) + ")"
    if len(spans) > 1:
        chain = [spans[0]]
        for s_ in spans[1:]:
            if s_["start"] <= chain[-1]["end"] - 0.1 and s_["end"] > chain[-1]["end"]:
                chain.append(s_)
        spans = chain
        ok_all = not order_bad
        if order_bad:
            stitch_note += order_bad + "; "
        for i in range(len(spans) - 1) if ok_all else ():
            cut = round((max(spans[i]["start"], spans[i + 1]["start"]) + spans[i]["end"]) / 2, 4)
            ok, nshift, why = verify_stitch((spans[i], spans[i + 1]), cut) if verify else (True, spans[i + 1]["shift"], "not checked")
            if not ok and verify and pair_clip_start(spans[i]["path"]) is not None and pair_clip_start(spans[i]["path"]) == pair_clip_start(spans[i + 1]["path"]):
                a_, b_ = dict(spans[i + 1]), dict(spans[i])                    # same base time: the frame match decides which one comes first
                cut2 = round((max(a_["start"], b_["start"]) + a_["end"]) / 2, 4)
                ok2, nshift2, why2 = verify_stitch((a_, b_), cut2)
                if ok2:
                    spans[i], spans[i + 1] = a_, b_
                    ok, nshift, why, cut = ok2, nshift2, why2 + " (order decided by the frame match)", cut2
            stitch_note += f"cut {i + 1}: {why}; "
            if not ok:
                ok_all = False
                break
            d_ = nshift - spans[i + 1]["shift"]
            spans[i + 1].update(shift=nshift, start=spans[i + 1]["start"] + d_, end=spans[i + 1]["end"] + d_)
        if not ok_all:                                      # fall back to the single clip with the most of these kills
            # V5.43B: the offsets between the clips are WRONG (that is why the stitch failed), so nothing of the joined timeline may
            # be kept: re-plan the event from scratch on the single clip, from the kills THAT clip read, in its own time.
            def own(s_):                                    # the kills of this cluster that THIS clip read itself, in its own time
                ob = s_["shift"] + moff
                return [dict(x, tt=x["t"], src=s_["it"], off=0.0) for x in s_["it"]["kills"]
                        if any(abs(k["tt"] - (x["t"] + ob)) <= 0.5 for k in cl)]
            best = max(spans, key=lambda s_: len(own(s_)))
            if own(best):
                note = stitch_note + "stitch rejected - re-planned on the single clip " + Path(best["path"]).name + \
                       f" ({len(own(best))} of {len(cl)} kills it shows)"
                ev = make_event(own(best), [(best["it"], 0.0)], det, cfg, refine, verify)
                if ev:
                    ev["stitch_note"] = note
                _ledger_gone(cl, ev, "its group's stitch was rejected (" + stitch_note.strip().rstrip(";").split(";")[-1].strip() + ") and the event was re-planned on " +
                             Path(best["path"]).name)
                return ev
            _ledger_gone(cl, None, "its group's stitch was rejected and no single clip shows these kills by itself")
            return None
    cover_start, cover_end = spans[0]["start"], spans[-1]["end"]
    keep = [i for i, (t, r) in enumerate(zip(times, rows)) if cover_start + 0.05 <= t and r <= cover_end - 0.05]
    led = CUR_LEDGER[0]
    if led is not None:                                     # V6.9.7: a row outside the footage of ONE clip cannot form a take (existing rule); in a stitched span it is only 'gone'
        for i, r_ in enumerate(raw):
            if i not in keep:
                row_ = led.row_of_cl(r_["k"])
                if row_ and len(spans) == 1:
                    row_["unusable"] = "kill / killfeed row outside the footage of its clip (needs 0.05 s margin)"
                elif row_ and not row_["gone"]:
                    row_["gone"] = "outside the footage of the stitched clips"
    if not keep:
        return None
    times, rows, victims = [times[i] for i in keep], [rows[i] for i in keep], [victims[i] for i in keep]
    v4times = sorted(r["v4"] for i, r in enumerate(raw) if i in keep)
    deaths = []
    for s_ in spans:
        deaths += [d + s_["shift"] for d in s_["it"].get("deaths", [])]
    last = times[-1]
    d_after = min([d - last for d in deaths if 0 < d - last <= 2.0], default=None)
    imp = len(times) - 1
    rec = spans[0]["it"]["rec"] if len(spans) == 1 else main["rec"]
    shift0 = spans[0]["shift"] if len(spans) == 1 else 0.0
    if len(spans) == 1 and shift0:                          # single clip other than the timeline's own: move to its own time
        times = [round(t - shift0, 4) for t in times]
        rows = [round(t - shift0, 4) for t in rows]
        v4times = [round(t - shift0, 4) for t in v4times]
        cover_start, cover_end = cover_start - shift0, cover_end - shift0
        spans = [dict(spans[0], shift=0.0, start=spans[0]["start"] - shift0, end=spans[0]["end"] - shift0)]
    ev = {"rec": rec, "path": rec["path"], "times": times, "rows": rows, "times_v4": v4times, "n": len(times), "victims": victims,
          "first": times[0], "last": times[-1], "span": times[-1] - times[0], "hs": hs, "flick": False,
          "shots": shots / max(1, len(cl)), "imp": imp, "lag": round(lag, 3),
          "pre": times[0] - cover_start, "post": cover_end - times[-1], "death_after": d_after,
          "parts": [{"path": s_["path"], "shift": round(s_["shift"], 4), "start": round(s_["start"], 4), "end": round(s_["end"], 4),
                     "rec": s_["it"]["rec"]} for s_ in spans],
          "stitched": len(spans) > 1, "stitch_note": stitch_note.strip(), "lags": [0.0] * len(times),
          "vis": spans[0]["it"].get("vis", []) if len(spans) == 1 else main.get("vis", [])}
    ev["score_pre"] = base_score(ev)
    if led is not None:
        led.note_event(ev, [led.row_of_cl(raw[i]["k"]) for i in keep])
    return ev



# ======================================================================= PLANNER
# V5.1: V4's planner (event-driven, song-anchored, best multikill on the drop, build-up before / the rest after) with V5's
# frame-exact timing, the kill moment = the fatal shot, short tails, a slow-mo ending, Optimal length and Auto style.
LEAD_MIN = 0.3                          # run-up before the first kill (V4: 1-2 beats)
SLOW_OUT = 0.4
MIN_TAKE_BEATS, MIN_TAKE_S, OUT_FPS = 2, 1.2, 60
TAIL = (0.2, 0.5)                       # after the last kill (no dead air)
ROW_TAIL, ROW_SLACK = 0.4, 0.3          # V5.42B: the take lasts >= 0.4 s after my last kill ROW appears (+ up to 0.3 s to a tick)
FADE_IN = 0.3                           # music + video fade-in at the very start
END_FADE = (2.0, 3.0)                   # final slow-mo + music + video fade, from the final kill
RECIPES = {                             # all within V4's effect strength; they change pacing, run-ups, zooms, slow-mo, transitions
    "hype":       {"zoom_p": 0.60, "zoom_amp": 0.08, "ramp_p": 0.35, "flash": True, "slow_max": 1, "lead": (1, 2),
                   "trans": {"hard": 0.6, "flash": 0.2, "zoom": 0.2}},
    "aggressive": {"zoom_p": 0.90, "zoom_amp": 0.10, "ramp_p": 0.55, "flash": True, "slow_max": 1, "lead": (1, 2),
                   "trans": {"hard": 0.7, "flash": 0.3}},
    "smooth":     {"zoom_p": 0.30, "zoom_amp": 0.06, "ramp_p": 0.20, "flash": False, "slow_max": 1, "lead": (2, 3),
                   "trans": {"hard": 0.8, "zoom": 0.2}},
    "cinematic":  {"zoom_p": 0.40, "zoom_amp": 0.07, "ramp_p": 0.10, "flash": True, "slow_max": 2, "lead": (2, 4),
                   "trans": {"hard": 0.75, "flash": 0.25}},
    "chill":      {"zoom_p": 0.15, "zoom_amp": 0.05, "ramp_p": 0.0, "flash": False, "slow_max": 1, "lead": (2, 4),
                   "trans": {"hard": 1.0}},
}
STYLE_CHOICES = ["auto"] + list(RECIPES) + ["mix", "random"]


def auto_style(an, song, rng, events=None):
    """Auto: the recipe that fits THIS song's map (energy, BPM, strong drops, how steady the rhythm is) and the material (how
    many multikills vs singles); the seed picks between close fits. Energy: the CSV value when present, else the song map."""
    e = song.get("energy")
    e_src = "CSV"
    if e is None:
        e, e_src = float(sum(an.get("energy", [0.5])) / max(1, len(an.get("energy", [1])))), "map"
    e = float(e)
    bpm = float(an.get("bpm") or 120)
    drop = min(1.0, float(an.get("drop_strength") or 0.0) / 0.6)
    n_drops = sum(1 for d in an.get("drops", []) if d.get("strength", 0) >= 1.5)
    steady = float(an.get("steady", 0.5))
    evs = events or []
    multi = sum(1 for x in evs if x.get("n", 1) >= 2)
    mr = multi / max(1, len(evs)) if evs else 0.3
    sc = {"aggressive": 2.0 * max(0, e - 0.7) + 1.2 * max(0, min(1, (bpm - 130) / 30)) + 0.6 * drop + 0.8 * max(0, mr - 0.4)
                        + 0.3 * steady,
          "hype": 1.5 * max(0, 1 - abs(e - 0.75) / 0.25) + 0.8 * drop + 0.6 * mr + 0.4 * steady,
          "cinematic": 1.2 * drop * max(0, 1 - abs(e - 0.6) / 0.3) + 0.8 * max(0, (105 - bpm) / 30) + 0.4 * (1 - steady)
                       + 0.2 * min(2, n_drops),
          "smooth": 1.2 * max(0, 1 - abs(e - 0.55) / 0.2) + 0.6 * (1 - mr) + 0.3 * steady,
          "chill": 2.0 * max(0, 0.5 - e) / 0.5 + 0.6 * max(0, (100 - bpm) / 30) + 0.4 * (1 - mr)}
    ranked = sorted(sc.items(), key=lambda x: -x[1])
    close = [n for n, v in ranked[:2] if v >= ranked[0][1] * 0.75]
    name = rng.choice(close) if close else ranked[0][0]
    runner = next(n for n, _ in ranked if n != name)
    why = (f"{name} (song energy {e:.2f} ({e_src}), {bpm:.0f} BPM, {n_drops} strong drop{'s' * (n_drops != 1)}, rhythm steady "
           f"{steady:.2f}, {multi} multikills / {len(evs) - multi} singles; runner-up: {runner}) - scores "
           + ", ".join(f"{n} {v:.2f}" for n, v in ranked))
    return name, why


def pick_recipe(rng, style, avoid, an=None, song=None, events=None):
    names = list(RECIPES)
    why = ""
    if style in (None, "", "auto") and an is not None:
        name, why = auto_style(an, song or {}, rng, events)
    elif style == "mix":
        rp = {"zoom_p": rng.uniform(.2, .9), "zoom_amp": rng.uniform(.05, .10), "ramp_p": rng.uniform(0, .5),
              "flash": rng.random() < .5, "slow_max": rng.randint(1, 2), "lead": rng.choice([(1, 2), (2, 3)]),
              "trans": {"hard": 0.7, "flash": 0.15, "zoom": 0.15}}
        return "mix", rp, "random mix"
    elif style in names:
        name = style
    else:
        name = rng.choice([n for n in names if n != avoid] or names)
    return name, dict(RECIPES[name]), why


def src_to_out(segs, src_t):
    """THE source-time -> output-time map of one take (seconds from the take's first frame). segs = [[a, b, speed, frames, ...], ...].
    Used for kill placement, effect placement and the sync report, so they can never disagree."""
    off = 0
    for sg in segs:
        a, b, sp, n = sg[:4]
        if b > a and a - 1e-6 <= src_t <= b + 1e-6:
            return (off + (src_t - a) / (b - a) * n) / OUT_FPS
        if b <= a and abs(src_t - a) < 1e-6:
            return off / OUT_FPS
        off += n
    if segs and src_t < segs[0][0]:
        return (src_t - segs[0][0]) / OUT_FPS
    return off / OUT_FPS


def vis_ok(ev, src_start):
    """True if no earlier own killer row is on screen at the take's first source frame."""
    return not any(t0 <= src_start <= t1 for t0, t1 in ev.get("vis", []))


def _ticks(bt):
    import numpy as np
    U = np.empty(2 * len(bt) - 1)
    U[0::2], U[1::2] = bt, bt[:-1] + np.diff(bt) / 2
    return U


GAP_ALLOW = (1.5, 2.0, 4.5)              # V5.41 multikill dead air (s): tight (builds / drops / hype) .. calm max
STYLE_CALM = {"chill": 1.0, "cinematic": 0.75, "smooth": 0.6, "hype": 0.15, "aggressive": 0.0}


def gap_allowance(an, rname, t_song):
    """The empty time allowed between two kills of a multikill at song time t_song: builds and drops stay tight (1.5-2 s),
    calm / moody sections of slow, chill songs breathe (up to 4.5 s). From the song map section + energy, the BPM and the
    style recipe."""
    import bisect
    bt = an["beats"]
    j = max(0, min(len(bt) - 1, bisect.bisect_right(bt, t_song) - 1))
    sec = (an.get("section_of_beat") or [""] * len(bt))[min(j, len(an.get("section_of_beat") or bt) - 1)]
    lv = an["level"][min(j, len(an["level"]) - 1)]
    en = an["energy"][min(j, len(an["energy"]) - 1)]
    slow_t = min(1.0, max(0.0, (130.0 - float(an.get("bpm") or 120)) / 50.0))
    calm_s = STYLE_CALM.get(rname, 0.4)
    if sec in ("build", "drop") or lv == 2:
        return GAP_ALLOW[0] + (GAP_ALLOW[1] - GAP_ALLOW[0]) * max(slow_t, calm_s) * 0.5 * (1 + slow_t)
    c = 0.35 * slow_t + 0.35 * calm_s + 0.3 * (1.0 - min(1.0, max(0.0, en)))
    return GAP_ALLOW[1] + (GAP_ALLOW[2] - GAP_ALLOW[1]) * c


def dead_air_cuts(ev, U, kb):
    """V5.41: jump-cuts over over-long empty time inside a multikill (first kill on song time U[kb]). A gap longer than its
    allowance (gap_allowance) is cut ON a beat 0.4 s+ after the kill, landing about 1 s before the next kill (on a beat when
    that lands within 0.85-1.15 s); kills stay 1.0x and every kill is shown. Returns (cuts, output span), cuts =
    [(output s from the first kill, source time the footage resumes at)]. No over-long gap: ([], the plain span)."""
    times = ev["times"]
    span = times[-1] - times[0]
    allow = ev.get("_allow")
    if allow is None or len(times) < 2 or max(b - a for a, b in zip(times, times[1:])) <= GAP_ALLOW[0]:
        return [], span
    import bisect
    cuts, o = [], 0.0                                      # o = output time of kill i, from the first kill
    T0, nt = float(U[kb]), len(U)
    rows = ev.get("rows") or times
    for i, (a, b) in enumerate(zip(times, times[1:])):
        g = b - a
        if g <= allow(T0 + o):
            o += g
            continue
        rd = max(0.0, rows[i] - a) if i < len(rows) else 0.0             # V5.42B: never cut before this kill's row is seen
        j0 = bisect.bisect_left(U, T0 + o + max(0.4, rd + ROW_TAIL) - 1e-6)
        ok = [j for j in range(j0, nt) if U[j] - (T0 + o) <= g - 1.0 - 0.25 and U[j] - (T0 + o) <= 2.5]
        cj = next((j for j in ok if j % 2 == 0), ok[0] if ok else None)
        if cj is None:
            o += g
            continue
        dc = float(U[cj]) - T0
        lead = 1.0
        nxt = [float(U[j]) - float(U[cj]) for j in range(cj + 1, min(nt, cj + 6)) if 0.85 <= U[j] - U[cj] <= 1.15]
        if nxt:
            lead = min(nxt, key=lambda x: abs(x - 1.0))
        cuts.append((dc, b - lead))
        o = dc + lead
    return cuts, (o if cuts else span)


def geom(ev, U, c, kb, end, ramp, slow, ending=False, ext=True):
    """One continuous take (ticks = beats + half-beats; kb = the beat tick where the first kill lands): run-up from tick c,
    1.0x from 1.0 s before the first kill through the last, speed-ups only before that, tail 0.2-0.5 s to the end tick
    (never into my death), slow-mo starts ON the last kill. ending=True: slow-mo from the final kill for the 2-3 s fade."""
    lead_t = float(U[kb] - U[c])
    if lead_t < LEAD_MIN - 1e-6 or lead_t > ev["pre"] + 1e-6:
        return None
    first, last = ev["times"][0], ev["times"][-1]
    span = last - first
    cuts, span = dead_air_cuts(ev, U, kb)
    r = 1.0
    if ramp > 1.0 and lead_t >= 1.6:
        app = lead_t - 1.0
        r = min(ramp, max(1.0, (ev["pre"] - 1.0) / app))
        r = r if r >= 1.15 else 1.0
    cover = lead_t if r == 1.0 else 1.0 + (lead_t - 1.0) * r
    if first - min(ev.get("rows") or ev["times"]) > cover - 0.05:                   # killfeed row must be inside the footage
        return None
    dmax = (ev["death_after"] - 0.05) if ev.get("death_after") is not None else 99.0
    post = min(ev["post"], dmax)
    if ending:
        if post < 0.1:
            return None
        return {"ev": ev, "c": c, "kb": kb, "end": None, "lead_t": lead_t, "ramp": r, "slow": True, "ending": True,
                "dur": lead_t + span + END_FADE[0], **({"cuts": cuts, "ospan": span} if cuts else {})}
    if end is None or end <= kb:
        return None
    D = float(U[end] - U[c])
    tail = D - (lead_t + span)
    win = (0.3, 0.5) if slow else TAIL
    if dmax < win[0]:
        win = (0.08, dmax)
    win = row_tail_window(ev, slow, win, post, ext)
    if win is None:
        return None
    if not (win[0] - 1e-6 <= tail <= win[1] + 1e-6):
        return None
    src_tail = tail * (0.5 if slow else 1.0)
    if src_tail > post + 1e-6:
        return None
    if end - c < 2 * MIN_TAKE_BEATS or D < MIN_TAKE_S:
        return None
    return {"ev": ev, "c": c, "kb": kb, "end": end, "lead_t": lead_t, "ramp": r, "slow": slow, "ending": False, "dur": D,
            **({"cuts": cuts, "ospan": span} if cuts else {})}


def row_tail_window(ev, slow, win, post, ext=True):
    """V5.42B: a take's tail is measured from the moment my last kill ROW appears on screen (not the estimated shot): it lasts
    >= 0.4 s after the row (up to 0.3 s more to reach a beat tick). If my death or the clip end comes sooner, as long as the
    footage allows - but the row is always seen. None = the row cannot be shown. Rows within the old window: unchanged.
    ext=False: only the old window's upper end (place() tries that first, so takes that already showed the row stay as they were)."""
    last = ev["times"][-1]
    spd = 0.5 if slow else 1.0
    rdo = max(0.0, max(ev.get("rows") or ev["times"]) - last) / spd      # output s from the last kill to its row
    need = rdo + ROW_TAIL
    if need <= win[0] + 1e-6:
        return win
    cap = max(0.0, post) / spd
    if cap < rdo + 0.05:
        return None
    lo = min(need, cap)
    if not ext:
        return (lo, win[1]) if lo <= win[1] + 1e-6 else None
    return (lo, max(win[1], lo + ROW_SLACK))


def place(ev, U, down, rp, c=None, kb=None, end=None, ramp=1.0, slow=False, ending=False, c_only=None, ext_only=None):
    """V4 placement on ticks: the first kill on a beat (downbeat preferred), run-up of the recipe's 1-4 beats (more only to keep
    earlier killfeed rows off the first frame), end tick 0.2-0.5 s after the last kill. V5.43: the kill-row tail may only extend
    the END (ext_only=False: the V5.42 window; True: the extended window) - the start / run-up is never moved later for it."""
    nt = len(U) - 1
    first = ev["times"][0]
    span = ev["times"][-1] - first
    lo, hi = rp.get("lead", (1, 2))
    if kb is not None:
        pairs = [(kb - k, kb, k) for k in range(1, min(kb, 16) + 1)]
    else:
        pairs = [(c, c + k, k) for k in range(1, 17) if c + k < nt and (c + k) % 2 == 0]
    if c_only is not None:
        pairs = [(c_only, kb, kb - c_only)] if kb is not None and kb > c_only else []
    pairs = [q for q in pairs if LEAD_MIN - 1e-6 <= U[q[1]] - U[q[0]] <= ev["pre"] + 1e-6]
    if ramp > 1.0:
        pairs = [q for q in pairs if U[q[1]] - U[q[0]] >= 1.6]
    pref = lambda q: (0 if 2 * lo <= q[2] <= 2 * hi else 1, abs(q[2] - (lo + hi)), q[1] // 2 not in down, q[0] % 2)
    good = sorted([q for q in pairs if vis_ok(ev, first - (U[q[1]] - U[q[0]]))], key=pref)
    bad = sorted([q for q in pairs if q not in good], key=lambda q: -(U[q[1]] - U[q[0]]))[:2]
    for ext, (cc, kk, _) in [(x, q) for x in ((True,) if ending else (False, True) if ext_only is None else (ext_only,)) for q in good + bad]:
        if ending:
            g = geom(ev, U, cc, kk, None, ramp, True, ending=True)
            if g:
                return g
            continue
        last_out = U[kk] + dead_air_cuts(ev, U, kk)[1]
        hi = max(TAIL[1], 2 * max(0.0, max(ev.get("rows") or ev["times"]) - ev["times"][-1]) + ROW_TAIL + ROW_SLACK)
        ends = [end] if end is not None else \
            sorted([j for j in range(kk + 1, min(nt + 1, kk + 40 + int(span / max(1e-3, float(U[1] - U[0]))) + 1))   # long fights too
                    if TAIL[0] - 0.12 <= U[j] - last_out <= hi + 0.01],
                   key=lambda j: (j % 2, abs(U[j] - last_out - 0.32)))
        for j in ends:
            g = geom(ev, U, cc, kk, j, ramp, slow, ext=ext)
            if g:
                return g
    return None


def optimal_length(events, bd, notes):
    """'Optimal': the strong material decides the length (no padding with weak kills), 30-150 s (V6.7.2; unused, optimal_fit decides)."""
    est = lambda e: 2 * bd + e["span"] + 0.4
    strong = [e for e in events if not e.get("plain")]
    L = sum(est(e) for e in strong)
    used = "strong events"
    if L < 30:
        L = sum(est(e) for e in events)
        used = "all events (little strong material)"
    L = max(30.0, min(float(LEN_MAX_S), L))
    notes.append(f"auto target {L:.0f} s from {used}")
    return L


OPT_RANGE = (80.0, 150.0)               # V5.42B Optimal: 80 s minimum (when the material allows), 150 s maximum, never past the song


def take_estimate(e, bd, rname):
    """Seconds one clip takes on screen at a style's pacing: the recipe's run-up, the fight (over-long dead air jump-cut to
    ~1.4 s), the tail to >= 0.4 s after the last kill row, rounded up to the half-beat grid."""
    rp = RECIPES.get(rname, RECIPES["hype"])
    lo, hi = rp.get("lead", (1, 2))
    allow = GAP_ALLOW[1] + (GAP_ALLOW[2] - GAP_ALLOW[1]) * STYLE_CALM.get(rname, 0.4) * 0.5
    t = e["times"]
    fight = sum(min(b - a, max(allow, 1.4)) for a, b in zip(t, t[1:]))
    rd = max(0.0, max(e.get("rows") or t) - t[-1])
    tail = max(0.32, rd + ROW_TAIL + 0.1)
    td = bd / 2
    return max(MIN_TAKE_S, math.ceil(((lo + hi) / 2 * bd + fight + tail) / td) * td)


def optimal_fit(clips, an, style):
    """V5.42B OPTIMAL - THE length rule, ONE shared function (Manual now; the weekly Auto mode can reuse it unchanged):
    (clips, song map, style) -> {"length", "start_beat", "end_beat", "drop_beat", "clips", "left", "max", "why"}.
      - range: 80 s minimum, 150 s maximum, never longer than the whole song;
      - all usable clips are used when they fit in min(150 s, song); otherwise the WEAKEST are left out (listed), never more;
      - fewer clips = a shorter montage (80 s+ when the material allows - nothing is padded);
      - the song section is chosen to fit that length (starting earlier in the song when needed) and ends on a phrase or
        section boundary (or the song end); the drop is placed inside it when it fits - a preference, never a reason to
        shorten the section."""
    import numpy as np
    rname = style if style in RECIPES else "hype"
    bt = np.array(an["beats"], float)
    bd = float(np.median(np.diff(bt)))
    song_end = float(an.get("dur") or (bt[-1] + bd)) - 0.1
    avail = song_end - float(bt[0])
    mx = min(OPT_RANGE[1], avail)
    est = {id(e): take_estimate(e, bd, rname) for e in clips}
    end_x = (END_FADE[0] + END_FADE[1]) / 2 - 0.4           # the slow-mo ending runs longer than a normal tail
    total = lambda lst: sum(est[id(e)] for e in lst) + (end_x if len(lst) >= 3 else 0.0)
    chosen = sorted(clips, key=lambda e: -e["score"])
    left = []
    while len(chosen) > 1 and total(chosen) > mx - bd:         # one beat of room for the drop alignment
        e = chosen.pop()
        left.append((e, f"don't fit in {mx:.0f} s ({'the whole song' if mx < OPT_RANGE[1] else 'the 150 s maximum'})"))
    L = min(mx, total(chosen))
    # song section: [S, E], E on a phrase / section boundary (or the song end), S = E - L; drop inside it preferred
    nb = len(bt)
    last_b = int(np.searchsorted(bt, song_end, side="right") - 1)
    sec_b = {int(x["start"]) for x in an.get("sections", [])}
    bounds = sorted({int(b) for b in an.get("phrase4", [])} | sec_b | {last_b})
    down = sorted(int(d) for d in an.get("down", [])) or list(range(0, nb, 4))
    drops = an.get("drops") or ([{"beat": an["drop"], "strength": 1.0}] if an.get("drop") is not None else [])
    main = an.get("drop")
    best = None
    for E in bounds:
        if E > last_b or bt[E] - bt[0] < L - 1e-6:
            continue
        s_t = float(bt[E]) - L
        S = max([d for d in down if bt[d] <= s_t + 1e-6] or [0])
        frac = lambda b: (bt[b] - bt[S]) / max(1e-6, bt[E] - bt[S])
        inside = [d for d in drops if 0.2 <= frac(d["beat"]) <= 0.6 and d["beat"] < E]
        sc = 0.0
        if main is not None and 0.2 <= frac(main) <= 0.6 and main < E:
            sc += 3.0 - 4.0 * abs(frac(main) - 0.38)       # V5.43: ~38% build-up before the drop (V5.42 order)
        elif inside:
            sc += 1.5
        sc += 0.5 * (E in sec_b) + 0.3 * (E == last_b) + 0.2 * float(np.mean(an["level"][S:E] if len(an.get("level", [])) >= E else [0]))
        if best is None or sc > best[0] + 1e-9:
            best = (sc, S, E, inside)
    if best is None:                                       # the material needs the whole song
        best = (0.0, 0, last_b, [d for d in drops if d["beat"] < last_b])
    _, S, E, inside = best
    fr = lambda b: (bt[b] - bt[S]) / max(1e-6, bt[E] - bt[S])
    if main is not None and 0.2 <= fr(main) <= 0.6:
        drop_b, dwhy = int(main), "the song's main drop"
    elif inside:
        d = max(inside, key=lambda d: d.get("strength", 0))
        drop_b, dwhy = int(d["beat"]), "the strongest drop inside the section"
    else:
        tgt = bt[S] + 0.38 * (bt[E] - bt[S])
        drop_b = min([d for d in down if S < d < E] or [S], key=lambda d: abs(bt[d] - tgt))
        dwhy = "no drop fits inside this section - a downbeat ~38% in"
    end_kind = "the song end" if E == last_b else "a section boundary" if E in sec_b else "a 4-bar phrase"
    rng_txt = (f"range {OPT_RANGE[0]:.0f}-{mx:.0f} s" if mx >= OPT_RANGE[0] else f"at most {mx:.0f} s") + \
        f" ({'the 150 s maximum' if mx >= OPT_RANGE[1] else 'the whole song is ' + format(avail, '.0f') + ' s'})"
    why = (f"OPTIMAL {L:.0f} s ({rname} pacing): {len(chosen)} of {len(clips)} usable clips ~ {total(chosen):.0f} s; {rng_txt}"
           + (f"; under {OPT_RANGE[0]:.0f} s because that is all the usable material (nothing is padded)"
              if L < min(OPT_RANGE[0], mx) - 0.5 and not left else "")
           + (f"; {len(left)} weakest didn't fit: " + ", ".join(Path(e["path"]).name for e, _ in left) if left else "")
           + f". Song section {ts(bt[S])}-{ts(bt[E])} ends on {end_kind}; drop at {ts(bt[drop_b])} ({dwhy}, {fr(drop_b):.0%} in)")
    return {"length": round(L, 2), "start_beat": int(S), "end_beat": int(E), "drop_beat": int(drop_b), "clips": chosen,
            "left": left, "max": mx, "why": why}


def why_no_take(ev):
    """Plain-language reason an event cannot form a take."""
    post = ev["post"] if ev.get("death_after") is None else min(ev["post"], ev["death_after"] - 0.05)
    if ev.get("death_after") is not None and ev["death_after"] < TAIL[0] + 0.05:
        return f"my death {ev['death_after']:.2f} s after the kill"
    if ev["pre"] < LEAD_MIN:
        return f"only {max(0.0, ev['pre']):.2f} s of footage before the kill"
    if post < TAIL[0]:
        return f"only {max(0.0, post):.2f} s of footage after the kill"
    return "no run-up / tail fits the song's beats"


def plan_montage(cfg, game, events, song, an, seed, style, target_s, hist_c, notes, lock=None, placement="v5", manual=False):
    """Event-driven, song-anchored layout (V4): the best multikill lands on the biggest drop's downbeat; build-up before it,
    the rest after it, a strong slow-mo ending last; takes on the song's beat grid, first kills on beats.
    manual=True (ticked clips): every usable event is used; Optimal = optimal_fit() (V5.42B: 80-150 s, never past the song,
    the section chosen to fit all of them, weakest left out only when they really don't fit, listed); a fixed length may
    trim (listed by name). Auto: Optimal / fixed length keeps the best events and leaves the lowest-ranked out.
    The montage never runs past the end of the song: the music covers every frame through the final fade."""
    import numpy as np
    rng = random.Random(seed)
    rname, rp, why = pick_recipe(rng, style, hist_c[-1].get("recipe") if hist_c else None, an, song, events)
    bt = np.array(an["beats"], float)
    U = _ticks(bt)
    down = set(an["down"])
    bd = float(np.median(np.diff(bt)))
    td = bd / 2
    evs = [dict(e) for e in events]
    if placement == "v4":
        for e in evs:
            e["times"] = list(e.get("times_v4") or e["times"])
            e["first"], e["last"], e["span"] = e["times"][0], e["times"][-1], e["times"][-1] - e["times"][0]
    for e in evs:                                          # V5.41: dead air allowed between kills follows the music
        e["_allow"] = None if e.get("_no_cuts") else (lambda t, _an=an, _r=rname: gap_allowance(_an, _r, t))
    song_end = float(an.get("dur") or (bt[-1] + bd)) - 0.1     # the montage's last frame stays inside the music
    optimal = target_s in (None, "", "optimal", 0)
    fitm = optimal                                         # V6.0: Auto Optimal uses optimal_fit() too (same rule as Manual)
    if fitm:                                               # V5.42B: optimal_fit() below decides (80-150 s, never past the song)
        target = min(OPT_RANGE[1], song_end - float(bt[0]))
    else:
        target = max(30.0, min(float(LEN_MAX_S), float(target_s)))      # V6.7.2: the slider's 150 s reaches the planner (was clamped to 120)
    strong = [e for e in evs if not e.get("plain")]
    plain = [e for e in evs if e.get("plain")]
    est = lambda e: 2 * bd + e["span"] + 0.4
    if manual:
        strong += plain                                    # Manual: every ticked clip counts
    elif fitm:
        pass                                               # V6.0 Auto Optimal: plain singles top up below until 80 s (best first)
    elif sum(est(e) for e in strong) < target and plain:
        strong += plain
        notes.append(f"{len(plain)} plain single kills used (not enough multikills / headshots)")
    elif plain:
        notes.append(f"{len(plain)} plain single kills left out (enough better material)")
    cap_t = int(min(float(LEN_MAX_S), target * 1.1) / td) if target else 10 ** 9      # V6.7.2: was min(120, ...)
    if fitm:                                 # ticked clips: optimal_fit() decides what fits
        cap_t = 10 ** 9
    nm = lambda e: Path(e["path"]).name
    phrase_ticks = {2 * int(b) for b in an.get("phrase4", [])} | {2 * int(x["start"]) for x in an.get("sections", [])}
    heads = {h.get("headline") for h in hist_c[-4:]}
    ev_sorted = sorted(strong, key=lambda e: -e["score"])
    total_ev = len(events)

    def nat(e):                                            # natural length in ticks
        L = 4 + int(math.ceil((e["span"] + 0.4) / td))
        L = ((L + 3) // 4) * 4
        return max(L, 2 * MIN_TAKE_BEATS)
    usable, skipped = [], []
    for e in ev_sorted:
        (usable if place(e, U, down, rp, c=16) else skipped).append(e)
    if skipped:
        notes.append(f"{len(skipped)} events cannot form a take: " + "; ".join(f"{nm(e)} ({why_no_take(e)})" for e in skipped))
    if not usable:
        raise RuntimeError("no kill event has enough footage around it to form a take")
    fit, n_usable = None, len(usable)
    if fitm:                                 # V5.42B: THE shared Optimal rule picks length, section and clips
        fit = optimal_fit(usable, an, rname)
        if not manual and plain:                           # V6.0: best multikills first, then best singles, until >= 80 s (never padded)
            need, added = min(OPT_RANGE[0], fit["max"]) - 0.5, 0
            for e in sorted(plain, key=lambda e: -e["score"]):
                if fit["length"] >= need:
                    break
                if place(e, U, down, rp, c=16):
                    usable.append(e)
                    added += 1
                    fit = optimal_fit(usable, an, rname)
            notes.append(f"{added} of {len(plain)} plain single kills added to reach {need + 0.5:.0f} s" if added else
                         f"{len(plain)} plain single kills left out (enough better material)")
        usable = [e for e in usable if any(e is c_ for c_ in fit["clips"])]
        notes.append(fit["why"])
    head_cands = [e for e in usable if e["path"] not in heads] or usable
    head = head_cands[0]
    rest = [e for e in usable if e is not head]
    ending = next((e for e in sorted(rest, key=lambda e: -e["score"]) if e["post"] >= 0.5), None)
    if ending is not None and len(rest) >= 2:
        rest.remove(ending)
    else:
        ending = None
    total = nat(head) + sum(nat(e) for e in rest) + (nat(ending) + 6 if ending else 0)
    cut_len = [e for e, _ in fit["left"]] if fit else []      # V5.42B: still tried in front below before being listed
    while total > cap_t and rest:                          # length-driven only: drop the lowest-ranked
        e = rest.pop()
        total -= nat(e)
        cut_len.append(e)
    if cut_len and not (fitm):
        notes.append(f"{len(cut_len)} lowest-ranked events left out to keep the montage near {target:.0f} s: "
                     + ", ".join(nm(e) for e in cut_len))
    nb = len(bt) - 1
    d0 = min(down)
    dr = an["drop"] if an.get("drop") is not None else int(0.45 * nb)
    dc = [i for i in sorted(down) if 12 <= i <= nb - 16] or sorted(down)
    dc8 = [i for i in dc if (i - d0) % 8 == 0]
    drop = 2 * min(dc8 or dc, key=lambda i: abs(i - dr))
    if fit:
        drop = 2 * fit["drop_beat"]
    fx = {}
    for e in rest:                                         # speed-ups only in the approach; slow-mo only after the headline
        fx[id(e)] = (rng.uniform(1.4, 1.9) if rng.random() < rp["ramp_p"] else 1.0, False)

    def place_fx(e, c=None, kb=None, end=None):
        ramp, sl = fx.get(id(e), (1.0, False))
        for rr in (ramp, 1.0):
            t = place(e, U, down, rp, c=c, kb=kb, end=end, ramp=rr, slow=sl)
            if t:
                return t
        return None
    head_take = None
    for e in head_cands[:10]:
        head_take = (place(e, U, down, rp, kb=drop, slow=True) if rp["slow_max"] > 0 else None) or place(e, U, down, rp, kb=drop)
        if head_take:
            if e is not head:
                rest = [x for x in rest if x is not e] + ([head] if head not in rest and head is not ending else [])
                head = e
            break
    if not head_take:
        raise RuntimeError("no clip could be placed on the drop")
    c_h = head_take["c"]
    jit = {id(e): rng.uniform(0.75, 1.25) for e in rest}  # seeded variety in the order (strong clips stay strong)
    asc = sorted(rest, key=lambda e: e["score"] * jit[id(e)])
    pre, acc = [], 0
    for e in asc:
        if acc >= 0.38 * total or acc + nat(e) > c_h:         # V5.42 order: ~38% build-up before the drop
            break
        pre.append(e)
        acc += nat(e)
    post = [e for e in sorted(rest, key=lambda e: -e["score"] * jit[id(e)]) if e not in pre]
    pre.sort(key=lambda e: (e["n"], e["score"] * jit[id(e)]))

    def run_pre(order, s):
        takes, c = [], s
        for e in order:
            t = place_fx(e, c=c)
            if t is None:
                return None, e
            takes.append(t)
            c = t["end"]
        return takes, c
    s0 = max(0, c_h - sum(nat(e) for e in pre))
    pre_takes = []
    for _ in range(16):
        if not pre:
            break
        res, c_end = run_pre(pre, s0)
        if res is None:
            pre.remove(c_end)
            post.insert(0, c_end)
            continue
        g = c_h - c_end
        if g == 0:
            pre_takes = res
            break
        if g < 0 or g <= 8:                                # let the headline's run-up meet the build-up exactly
            ht = place(head, U, down, rp, c=None, kb=drop, slow=head_take["slow"], c_only=c_end)
            if ht:
                head_take, c_h = ht, ht["c"]
                pre_takes = res
                break
        if s0 + g < 0:
            e = pre.pop()
            post.insert(0, e)
            s0 = max(0, c_h - sum(nat(x) for x in pre))
            continue
        s0 += g
    else:
        notes.append("build-up could not be aligned exactly; the montage starts at the headline lead-in")
        for e in pre:
            post.insert(0, e)
        pre, pre_takes = [], []
    if pre and not pre_takes:
        for e in pre:
            post.insert(0, e)
    takes = pre_takes + [head_take]
    # clean start: the first cut on a downbeat (a longer run-up for the first take) when the footage allows it
    t0 = takes[0]
    if t0["c"] % 2 or (t0["c"] // 2) not in down:
        for cc in sorted([2 * d for d in down if 0 < t0["c"] - 2 * d <= 8], reverse=True):
            g = geom(t0["ev"], U, cc, t0["kb"], t0["end"], t0["ramp"], t0["slow"])
            if g:
                takes[0] = g
                if t0 is head_take:
                    head_take = g
                break
    def place_end(e, c):
        """The ending take from tick c: its 2-3 s fade ends on a song phrase / section boundary when a run-up allows it, else
        on a beat; never past the end of the song."""
        lo, hi = rp.get("lead", (1, 2))
        cands = []
        for kk in range(c + 1, min(nt, c + 17)):
            if kk % 2:
                continue
            g = geom(e, U, c, kk, None, 1.0, True, ending=True)
            if not g:
                continue
            last_out = U[kk] + g.get("ospan", e["times"][-1] - e["times"][0])
            ends = [j for j in range(kk, len(U)) if END_FADE[0] <= U[j] - last_out <= END_FADE[1] and U[j] <= song_end]
            if not ends:
                continue
            ph = [j for j in ends if j in phrase_ticks]
            cands.append(((not vis_ok(e, e["times"][0] - (U[kk] - U[c])), not ph, abs(kk - c - (lo + hi))),
                          dict(g, fade_end=(ph or ends)[0], on_phrase=bool(ph))))
        return min(cands, key=lambda x: x[0])[1] if cands else None
    nt = len(U) - 1
    c = head_take["end"]
    left, left_song = [], []
    for e in post:
        if fit and U[c] + nat(e) * td + (8.0 if ending else 0) - U[takes[0]["c"]] > fit["max"]:
            left.append(e)                                 # V5.42B: never past min(150 s, song); tried in front below
            continue
        if target is not None and not fit and U[c] - U[takes[0]["c"]] > target - (6 if ending else 0):
            left.append(e)
            continue
        t = place_fx(e, c=c)
        if t and ending is not None and place_end(ending, t["end"]) is None:
            t = None                                       # keep room for the ending before the song ends
        if t:
            takes.append(t)
            c = t["end"]
        else:
            left_song.append(e)
    if left and not (fitm):
        notes.append(f"{len(left)} events left out to keep the montage near {target:.0f} s: " + ", ".join(nm(e) for e in left))
    if left_song and not (fitm):
        notes.append(f"SONG TOO SHORT: {len(left_song)} events did not fit before the song ends: " + ", ".join(nm(e) for e in left_song))
    end_take = None
    if ending is not None:
        end_take = place_end(ending, c)
        if end_take:
            takes.append(end_take)
        else:
            notes.append("the planned ending clip could not be placed before the song ends; the last take ends the montage")
            left_song.append(ending)
    if (fitm or target) and (cut_len or left or left_song) and takes:      # V6.7.2: a fixed length is filled the same way (it stopped at ~70-80% of the slider)
        # V5.41 Optimal fits the song: clips that did not fit after the drop go in front (the section starts earlier), strongest
        # first, while the montage stays within the 150 s / music-available target; the rest are listed as not fitting
        E = float(U[end_take["fade_end"]]) if end_take else float(U[takes[-1]["end"]])
        if fit:                                            # V5.42B: within min(150 s, song), never just for a 'nice' length
            target = fit["max"]
        for e in sorted(cut_len + left + left_song, key=lambda e: -e["score"]):
            c1, got = takes[0]["c"], None
            reach = 48 + (nat(e) + int(e["span"] / td) if fit else 0)     # V5.42B: long fights need more room in front
            cc_s = [cc for cc in range(c1 - 2 * MIN_TAKE_BEATS, max(-1, c1 - reach), -1) if E - U[cc] <= target + 1e-6]
            for xp in (False, True):                       # V5.43: the V5.42 tail window first; extending the end never shortens the run-up
                for cc in sorted(cc_s, key=lambda cc: (cc % 2, -cc)):
                    got = place(e, U, down, rp, c=cc, end=c1, ext_only=xp)
                    if got:
                        break
                if got:
                    break
            t0 = takes[0]
            for sh in ((1, 2, 3) if fit and not got and not t0.get("ending") else ()):
                # V5.42B repair: shift the neighbouring take's window (a slightly longer run-up) so this clip's tail can land
                g0 = geom(t0["ev"], U, t0["c"] - sh, t0["kb"], t0["end"], t0["ramp"], t0["slow"])
                if not g0:
                    continue
                for xp in (False, True):
                    for cc in sorted([cc - sh for cc in cc_s if cc - sh >= 0], key=lambda cc: (cc % 2, -cc)):
                        got = place(e, U, down, rp, c=cc, end=c1 - sh, ext_only=xp)
                        if got:
                            break
                    if got:
                        break
                if got:
                    takes[0] = g0
                    head_take = g0 if t0 is head_take else head_take
                    break
            if got:
                takes.insert(0, got)
                for lst in (cut_len, left, left_song):
                    if e in lst:
                        lst.remove(e)
        miss = cut_len + left + left_song
        if miss and fit:                                   # V5.42B: weakest first, grouped by reason
            why_m = {id(e): w for e, w in fit["left"]}
            by = {}
            for e in sorted(miss, key=lambda e: e["score"]):
                by.setdefault(why_m.get(id(e), f"no run-up / tail fits in front of the montage within {target:.0f} s, even with "
                                                "the next take shifted"), []).append(nm(e))
            notes.append(f"{len(miss)} ticked clips didn't fit in this song (weakest first): " +
                         "; ".join(f"{', '.join(v)} - {k}" for k, v in by.items()))
        elif miss:
            notes.append(f"{len(miss)} ticked clips didn't fit in this song: " + ", ".join(nm(e) for e in miss))
    for t in list(takes):
        if not t.get("ending") and (t["end"] - t["c"] < 2 * MIN_TAKE_BEATS or U[t["end"]] - U[t["c"]] < MIN_TAKE_S):
            i = takes.index(t)
            if manual:                                     # V5.42B repair: a longer run-up (the take before ends earlier)
                fixed = None
                for sh in range(1, 9):
                    g = geom(t["ev"], U, t["c"] - sh, t["kb"], t["end"], t["ramp"], t["slow"])
                    gp = geom(takes[i - 1]["ev"], U, takes[i - 1]["c"], takes[i - 1]["kb"], t["c"] - sh, takes[i - 1]["ramp"],
                              takes[i - 1]["slow"]) if i > 0 else True
                    if g and gp and (i == 0 or not takes[i - 1].get("ending")):
                        fixed = (g, gp)
                        break
                if fixed:
                    if t is head_take:
                        head_take = fixed[0]
                    elif i > 0 and takes[i - 1] is head_take:
                        head_take = fixed[1]
                    takes[i] = fixed[0]
                    if i > 0:
                        takes[i - 1] = fixed[1]
                    notes.append(f"cut list repair: {nm(t['ev'])} take extended to the minimum (longer run-up)")
                    continue
            takes.remove(t)
            notes.append(f"removed a take shorter than the minimum: {nm(t['ev'])}" +
                         (" (no longer run-up fits its footage or the take before)" if manual else ""))
    plan = finish_plan(cfg, game, takes, head_take, song, an, U, bt, seed, rname, rp, why, notes, total_ev, rng, placement, lock)
    D, S0 = plan["duration"], plan["song"]["start_t"]
    on_ph = bool(end_take and end_take.get("on_phrase"))
    plan["fit"] = {"usable": n_usable, "used": len(plan["takes"]), "skipped": [[nm(e), why_no_take(e)] for e in skipped],
                   "left_out": [] if fitm else [nm(e) for e in cut_len + left],
                   "song_short": [nm(e) for e in (cut_len + left + left_song if fitm else left_song)],
                   "section_s": plan["song"]["section_s"], "manual": manual, "optimal": optimal}
    plan["notes"].insert(1, f"{'OPTIMAL' if optimal else 'FIXED'} LENGTH {D:.0f} s = {len(plan['takes'])} "
                         f"{'usable ' if manual else ''}takes{'' if optimal else f' (slider {target:.0f} s)'}, ends on "
                         f"{'song phrase' if on_ph else 'a beat'} at {ts(S0 + D)} (song section {ts(S0)}-{ts(S0 + plan['song']['section_s'])} "
                         f"= {plan['song']['section_s']:.0f} s available)")
    return plan


def take_segments(tk, f_c, f_k, f_x):
    """Source segments with EXACT frame counts: the first kill shows on output frame f_k. 1.0x from 1.0 s before the first kill
    through the last; ramp only before that; slow-mo (or the ending's slow-mo) starts on the last kill frame."""
    ev = tk["ev"]
    k0, kl = ev["times"][0], ev["times"][-1]
    segs = []
    n_lead = f_k - f_c
    nr = 0
    if tk["ramp"] > 1.0 and n_lead > OUT_FPS + 6:
        n1 = OUT_FPS
        nr = n_lead - n1
        a1 = k0 - n1 / OUT_FPS
        segs.append([round(a1 - nr / OUT_FPS * tk["ramp"], 6), round(a1, 6), tk["ramp"], nr])
    else:
        a1 = k0 - n_lead / OUT_FPS
    cuts = tk.get("cuts") or []
    n_kill = int(round(tk.get("ospan", kl - k0) * OUT_FPS))

    def run_1x(n):                                         # 1.0x footage for n frames from a1, jump-cut over dead air (V5.41)
        pieces, at, done = [], a1, 0
        for dc, res in cuts:
            fb = (f_k + int(round(dc * OUT_FPS))) - (f_c + nr)
            if done < fb < n:
                pieces.append([round(at, 6), round(at + (fb - done) / OUT_FPS, 6), 1.0, fb - done])
                at, done = res, fb
        pieces.append([round(at, 6), round(at + (n - done) / OUT_FPS, 6), 1.0, n - done])
        return pieces, at + (n - done) / OUT_FPS
    if tk["slow"]:
        n_to_last = (f_k - f_c - nr) + n_kill
        if cuts:
            p1, kl2 = run_1x(n_to_last)
            segs += p1
        else:
            kl2 = a1 + n_to_last / OUT_FPS
            segs.append([round(a1, 6), round(kl2, 6), 1.0, n_to_last])
        rem = (f_x - f_c) - nr - n_to_last
        post = ev["post"] if ev.get("death_after") is None else min(ev["post"], ev["death_after"] - 0.05)
        src = rem / OUT_FPS * 0.5
        if src <= post + 1e-6:
            segs.append([round(kl2, 6), round(kl2 + src, 6), 0.5, rem])
        else:                                              # not enough footage: slow-mo as long as it lasts, then hold the frame
            ns = int(max(0.0, post) * 2 * OUT_FPS)
            if ns > 0:
                segs.append([round(kl2, 6), round(kl2 + ns / OUT_FPS * 0.5, 6), 0.5, ns])
            hold = round(kl2 + ns / OUT_FPS * 0.5, 6)
            segs.append([hold, hold, 0.0, rem - ns])
    else:
        n1 = (f_x - f_c) - nr
        if cuts:
            segs += run_1x(n1)[0]
        else:
            segs.append([round(a1, 6), round(a1 + n1 / OUT_FPS, 6), 1.0, n1])
    return [s for s in segs if s[3] > 0]


def split_parts(segs, ev):
    """Stitched continuation: split segments where the source switches clip (middle of each verified overlap) and tag each piece
    with its clip, so no frame repeats or jumps."""
    parts = ev.get("parts") or []
    if len(parts) <= 1:
        return [s + [0] for s in segs]
    cuts = [round((max(parts[i]["start"], parts[i + 1]["start"]) + parts[i]["end"]) / 2, 4) for i in range(len(parts) - 1)]
    out_ = []
    for a, b, sp, n in segs:
        pieces = [(a, b, n)]
        for cpt in cuts:
            nxt = []
            for pa, pb, pn in pieces:
                if pa < cpt < pb and sp > 0:
                    n1 = int(round((cpt - pa) / (pb - pa) * pn))
                    nxt += [(pa, pa + n1 / OUT_FPS * sp, n1), (pa + n1 / OUT_FPS * sp, pb, pn - n1)]
                else:
                    nxt.append((pa, pb, pn))
            pieces = nxt
        for pa, pb, pn in pieces:
            mid = (pa + pb) / 2 if pb > pa else pa
            pi = sum(1 for cpt in cuts if mid >= cpt)
            if pn > 0:
                out_.append([round(pa, 6), round(pb, 6), sp, pn, pi])
    return out_


def _game_gain(cfg, song_lufs, clip_lufs):
    """V4 balance (game under the music), slightly louder than V4; quiet clips (CS2) lifted by up to +8 dB, never lowered."""
    gv = float(cfg.get("game_audio_level", 0.6))
    base = 20 * math.log10(max(gv, 1e-3))
    lift = 0.0
    if clip_lufs is not None and song_lufs is not None:
        lift = max(0.0, min(8.0, (song_lufs - 12.0) - (clip_lufs + base)))
    return round(base + lift, 2), round(lift, 2)


def finish_plan(cfg, game, takes, head_take, song, an, U, bt, seed, rname, rp, why, notes, total_ev, rng, placement, lock):
    """Frame-exact take list + V4 effects (centred zoom punches on kills, ramps, slow-mo) + hard cuts (V5.2: no flashes)."""
    import numpy as np
    S0 = float(U[takes[0]["c"]])
    fr = lambda t: int(round((t - S0) * OUT_FPS))
    down, en, lv = set(an["down"]), an["energy"], an["level"]
    sec = an.get("section_of_beat") or []
    song_lufs = an.get("lufs")
    out_takes = []
    audio_state = {}                     # V5.57: audio mode used + Auto -> Legacy fallback reasons
    for i, tk in enumerate(takes):
        ev = tk["ev"]
        kb = tk["kb"]
        f_c, f_k = fr(U[tk["c"]]), fr(U[kb])
        if tk.get("ending"):
            osp = tk.get("ospan", ev["span"])
            last_k = f_k + int(round(osp * OUT_FPS))
            # fade 2-3 s from the final kill, ending on a beat tick when one falls inside that window
            room = float(an.get("dur") or 1e9) - 0.1 - (U[kb] + osp)     # never past the end of the song
            cand = [j for j in range(kb, len(U)) if END_FADE[0] <= U[j] - (U[kb] + osp) <= min(END_FADE[1], room)]
            if tk.get("fade_end") is not None:
                cand = [tk["fade_end"]]
            fade = (U[cand[0]] - (U[kb] + osp)) if cand else min(2.5, room)
            f_x = last_k + int(round(fade * OUT_FPS))
        else:
            f_x = fr(U[tk["end"]])
        if i + 1 < len(takes) and f_x != fr(U[takes[i + 1]["c"]]):
            f_x = fr(U[takes[i + 1]["c"]])
        segs = split_parts(take_segments(tk, f_c, f_k, f_x), ev)
        if tk.get("cuts"):
            notes.append(f"dead air: {Path(ev['path']).name} jump-cut over {len(tk['cuts'])} empty stretch"
                         f"{'es' * (len(tk['cuts']) > 1)} between its kills ({ev['span']:.1f} s of fight shown in {tk['ospan']:.1f} s)")
        nf = f_x - f_c
        if sum(s[3] for s in segs) != nf:
            segs[-1][3] += nf - sum(s[3] for s in segs)
        ko = [src_to_out(segs, t) for t in ev["times"]]
        ro = [src_to_out(segs, t) for t in ev.get("rows", ev["times"])]
        role = "ending" if tk.get("ending") else "headline" if tk is head_take else \
            ("drop" if lv[min(kb // 2, len(lv) - 1)] == 2 else "build" if lv[min(kb // 2, len(lv) - 1)] == 1 else "calm")
        strong = (kb // 2) in down or en[min(kb // 2, len(en) - 1)] >= 0.6
        frq = lambda x: round(x * OUT_FPS) / OUT_FPS
        pulses = []
        if role == "headline" or (strong and rng.random() < rp["zoom_p"]):                   # V4 zoom punch frequency
            pulses.append(frq(ko[0]))
        for k2 in ko[1:]:
            j = int(np.argmin(np.abs(bt - (U[tk["c"]] + k2))))
            if abs(bt[j] - (U[tk["c"]] + k2)) < 0.06 and (j in down or en[min(j, len(en) - 1)] >= 0.6) and len(pulses) < 3 \
                    and rng.random() < rp["zoom_p"] * 0.6:
                pulses.append(frq(k2))
        trans = "hard"                                     # V5.2: no flash / zoom cuts - every take starts on a hard cut
        slow_at = None
        o = 0
        for sg in segs:
            if sg[2] in (0.5, 0.0):
                slow_at = o / OUT_FPS
                break
            o += sg[3]
        parts = ev.get("parts") or [{"path": ev["path"], "shift": 0.0, "rec": ev["rec"]}]
        srcs = []
        for p in parts:
            r = p["rec"]
            au = resolve_clip_audio(r, cfg, game, audio_state)
            gdb, lift = _game_gain(cfg, song_lufs, au["lufs"])
            srcs.append({"path": p["path"], "shift": p.get("shift", 0.0), "rect": content_rect(r, cfg), "wh": [r["w"], r["h"]],
                         "audio": bool(r.get("audio")), "a_stream": au["stream"] or 0, "a_note": au.get("note", ""), "lufs": au["lufs"], "gain_db": gdb,
                         "lift_db": lift, "dur": r.get("dur", 0)})
        b0 = (tk["c"] - takes[0]["c"]) / 2
        out_takes.append({"path": ev["path"], "srcs": srcs, "rect": srcs[0]["rect"], "audio": srcs[0]["audio"], "wh": srcs[0]["wh"],
                          "segs": segs, "f0": f_c, "nf": nf, "out_start": round(f_c / OUT_FPS, 4), "dur": round(nf / OUT_FPS, 4),
                          "role": role, "section": sec[min(kb // 2, len(sec) - 1)] if sec else "",
                          "pulses": [round(p, 4) for p in pulses], "amp": round(rp["zoom_amp"], 3),
                          "flash": None, "trans": trans, "slow_at": slow_at,
                          "beat0": b0, "beat_end": b0 + nf / OUT_FPS / (2 * (U[1] - U[0])), "beat_kill": (kb - takes[0]["c"]) / 2,
                          "song_beat": tk["c"] // 2, "kill_down": kb % 2 == 0 and (kb // 2) in down, "locked": True,
                          "kills": [round(x, 6) for x in ev["times"]], "rows": [round(x, 6) for x in ev.get("rows", ev["times"])],
                          "kills_out": [round(x, 5) for x in ko], "rows_out": [round(x, 5) for x in ro],
                          "victims": ev.get("victims", []), "lags": [0.0] * ev["n"], "n": ev["n"], "score": round(ev["score"], 1),
                          "hs": ev["hs"], "ramp": round(tk["ramp"], 2), "slow": tk["slow"], "ending": bool(tk.get("ending")),
                          "snapped": 0, "stitched": ev.get("stitched", False), "stitch_note": ev.get("stitch_note", ""),
                          "death_after": ev.get("death_after"), "lag": ev.get("lag", 0.1), "level": int(lv[min(kb // 2, len(lv) - 1)]),
                          **({"jumps": len(tk["cuts"])} if tk.get("cuts") else {})})
    a_mode = audio_state.get("mode") or cfg.get("audio_mode", "auto")
    total_f = out_takes[-1]["f0"] + out_takes[-1]["nf"]
    total_s = total_f / OUT_FPS
    last = out_takes[-1]
    fade_st = round(last["out_start"] + last["kills_out"][-1], 4) if last["ending"] else round(max(0.0, total_s - 2.0), 4)
    notes.insert(0, f"MONTAGE LENGTH {total_s:.0f} s from {len(out_takes)} of {total_ev} kill events" +
                 (" - SHORTER THAN 30 s: not enough usable material" if total_s < 30 else ""))
    drop_beat = an.get("drop")
    bt0 = S0
    return {"game": game, "seed": seed, "recipe": rname, "recipe_why": why, "placement": placement,
            "params": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in rp.items()},
            "song": {"path": song["path"], "artist": song["artist"], "title": song["title"], "bpm": an["bpm"],
                     "start_t": round(bt0, 6), "drop_t": None if drop_beat is None else round(float(bt[drop_beat]) - bt0, 3),
                     "drop_beat": drop_beat, "fade_in": FADE_IN, "fade_out_start": fade_st, "lufs": an.get("lufs"),
                     "section_s": round(float(an.get("dur") or (bt[-1] + U[1] - U[0])) - bt0, 3)},
            "takes": out_takes, "duration": round(total_s, 4), "total_frames": total_f, "notes": notes,
            "beats_out": [round(float(t) - bt0, 4) for t in bt if bt0 - 1e-6 <= t <= bt0 + total_s + 1e-6],
            "drops_out": [round(d["t"] - bt0, 3) for d in an.get("drops", []) if bt0 <= d["t"] <= bt0 + total_s],
            "beats_n": int(round(total_s / (2 * (U[1] - U[0])))), "headline": head_take["ev"]["path"], "ending": last["ending"],
            "lock": 1.0, "audio_mode": a_mode, "audio_fallback": [], "audio_clip_fallback": audio_state.get("clip_fallback", [])}


def verify_cutlist(plan):
    """Final check before rendering: contiguous frames, segments add up, every take >= 2 beats and holds its kills (in order,
    inside its source windows), 1.0x from 1.0 s before the first kill through the last, tails 0.2-0.5 s (ending excepted),
    no clip and no kill used twice."""
    bad, pos, seen_clips = [], 0, set()
    for i, t in enumerate(plan["takes"], 1):
        if t["f0"] != pos:
            bad.append(f"take {i} starts at frame {t['f0']}, expected {pos}")
        if sum(sg[3] for sg in t["segs"]) != t["nf"]:
            bad.append(f"take {i} segment frames do not add up")
        if not t.get("ending") and (t["nf"] < MIN_TAKE_S * OUT_FPS - 1 or t["beat_end"] - t["beat0"] < MIN_TAKE_BEATS - 0.05):
            bad.append(f"take {i} is under the minimum ({t['nf']} frames)")
        if any(not (0 <= k < t["nf"] / OUT_FPS) for k in t["kills_out"]) or t["kills_out"] != sorted(t["kills_out"]):
            bad.append(f"take {i}: a kill is not inside the take (or out of order)")
        for r in t["rows"]:                                # every killfeed row's first frame must be inside the source windows
            if not any(sg[0] - 1e-3 <= r <= sg[1] + 1e-3 for sg in t["segs"] if sg[2] > 0):
                bad.append(f"take {i}: the kill row at {r:.2f}s is not inside the take's footage")
        k0, kl = t["kills"][0], t["kills"][-1]
        for sg in t["segs"]:
            a, b, sp = sg[:3]
            if sp != 1.0 and a < kl - 1.0 / OUT_FPS and b > k0 - 1.0 + 1.0 / OUT_FPS:
                bad.append(f"take {i}: speed {sp} between 1.0 s before the first kill and the last kill")
            src = t["srcs"][sg[4] if len(sg) > 4 else 0]
            if src.get("dur") and (b - src["shift"] > src["dur"] - 0.02 or a - src["shift"] < -0.01):
                bad.append(f"take {i}: footage {a:.2f}-{b:.2f}s is outside its clip")
        tail = t["dur"] - t["kills_out"][-1]
        row_tail = t["dur"] - max(t.get("rows_out") or t["kills_out"])
        tmax = max(TAIL[1], t["dur"] - row_tail - t["kills_out"][-1] + ROW_TAIL + ROW_SLACK)
        if not t.get("ending") and tail > tmax + 1.0 / OUT_FPS:
            bad.append(f"take {i}: tail {tail:.2f} s after the last kill (max {tmax:.2f})")
        sg_l = [sg for sg in t["segs"] if sg[2] > 0][-1:]                   # my death or the clip end may come sooner
        src_l = t["srcs"][sg_l[0][4] if sg_l and len(sg_l[0]) > 4 else 0] if sg_l else {}
        clip_end = bool(sg_l) and (src_l.get("dur") or 1e9) - (sg_l[0][1] - src_l.get("shift", 0.0)) <= 0.15
        if not t.get("ending") and row_tail < ROW_TAIL - 1.0 / OUT_FPS and t.get("death_after") is None and not clip_end:
            bad.append(f"take {i}: only {row_tail:.2f} s after the last kill row appears (min {ROW_TAIL})")
        if t["path"] in seen_clips:
            bad.append(f"take {i}: clip {Path(t['path']).name} used twice")
        seen_clips.add(t["path"])
        pos = t["f0"] + t["nf"]
    if plan["takes"] and pos != plan["total_frames"]:
        bad.append(f"frames {pos} != planned {plan['total_frames']}")
    return bad


def fmt_plan(plan, events, score_info, runners, unmatched, csvname):
    L = []
    sg = plan["song"]
    L.append(f"GAME     {plan['game']}      seed {plan['seed']}      style recipe: {plan['recipe']} {plan['params']}")
    L.append("AUDIO    " + AUDIO_TAGS.get(plan.get("audio_mode", "auto"), AUDIO_TAGS["auto"]) +
             ("   Auto audio failed, used Legacy V5.55: " + "; ".join(plan["audio_fallback"][:3]) if plan.get("audio_fallback") else "") +
             ("   Legacy audio for single clips (Auto kept for the others): " + "; ".join(plan["audio_clip_fallback"][:3])
              if plan.get("audio_clip_fallback") else ""))
    if plan.get("recipe_why"):
        L.append(f"AUTO STYLE {plan['recipe_why']}")
    L.append(f"SONG     {sg['artist']} - {sg['title']}   [{Path(sg['path']).name}]   BPM {sg['bpm']}   placement {plan['placement']}")
    L.append(f"TIMELINE song starts at {ts(sg['start_t'])} (music + video fade in {sg['fade_in']} s); {plan['duration']:.1f}s at 60 fps "
             f"({plan['total_frames']} frames); best multikill on the drop at {sg['drop_t']}s; "
             f"{'slow-mo ending, fades from ' + format(sg['fade_out_start'], '.2f') + 's' if plan['ending'] else 'fade-out over the last 2 s'}")
    if score_info:
        fp = score_info["fit_parts"]
        L.append(f"SONG SCORE total {score_info['total']} = recency {score_info['recency']} (added {score_info['days']} days ago)"
                 f" + fit {score_info['fit']} (steady {fp['steady']}, drop {fp['drop']}, bpm {fp['bpm']}, energy {fp.get('energy', 0)}) - used-penalty {score_info['penalty']}")
    for s2, sc in runners:
        L.append(f"   runner-up: {s2['artist']} - {s2['title']}  total {sc['total']} (recency {sc['recency']}, fit {sc['fit']}, penalty {sc['penalty']})")
    for n in plan["notes"]:
        L.append(f"NOTE     {n}")
    bad = verify_cutlist(plan)
    L.append("CUT LIST CHECK: " + ("OK - contiguous, kills inside every take, 1.0x through the kills, tails >= 0.4 s after the kill row, no clip twice"
                                   if not bad else "PROBLEMS: " + "; ".join(bad)))
    L.append("\nRANKED KILL EVENTS (top 20)")
    for i, ev in enumerate(events[:20], 1):
        L.append(f"  {i:2}. score {ev['score']:5.1f}  {ev['n']}k{' HS' * (ev['hs'] > 0)}{' flick' * bool(ev['flick'])}"
                 f"{' STITCHED' if ev.get('stitched') else ''}  {Path(ev['path']).name} @ {', '.join(ts(t) for t in ev['times'])}"
                 f"{'  [' + ev['stitch_note'] + ']' if ev.get('stitch_note') else ''}")
    L.append(f"\nCUT LIST ({len(plan['takes'])} takes)")
    for i, t in enumerate(plan["takes"], 1):
        tail = t["dur"] - t["kills_out"][-1]
        fx = (f"trans:{t['trans']} " if i > 1 and t["trans"] != "hard" else "") + ("slow-mo " if t["slow"] else "") + \
             (f"ramp x{t['ramp']} " if t["ramp"] > 1 else "") + (f"zoom@{','.join(f'{p:.2f}' for p in t['pulses'])} " if t["pulses"] else "") + \
             ("FLASH " if t["flash"] is not None else "") + \
             " | game " + ", ".join(f"{s_['gain_db']:+.1f} dB" + (f" (lift {s_['lift_db']:+.1f})" if s_.get("lift_db") else "") +
                                    (f" [{s_['a_note']}]" if s_.get("a_note") else "") for s_ in t["srcs"] if s_["audio"])
        L.append(f"  {i:2}. {t['f0'] / OUT_FPS:6.2f}s {t['nf']:4d}f [{t['role']:8}] first kill @{t['out_start'] + t['kills_out'][0]:6.2f}s"
                 f"{' (downbeat)' if t['kill_down'] else ''} tail {tail:.2f}s  {t['n']}k  {Path(t['path']).name} @ "
                 f"{', '.join(ts(k) for k in t['kills'])}{' (stitched)' if t['stitched'] else ''}  {fx}")
    L.append(f"\nPLAYLIST tracks with no MP3 yet: {len(unmatched)}" + (f" (CSV {csvname})" if csvname else ""))
    for r in unmatched[:15]:
        L.append(f"   {r['artist']} - {r['title']}")
    return "\n".join(L)


# ======================================================================= RENDER
FX_ALL = ("zoom", "flash", "slow", "transition")


def ff_has(kind, name):
    r = run(["ffmpeg", "-hide_banner", f"-{kind}"]).stdout.decode(errors="replace")
    return name in r


def _alimiter_latency():
    """alimiter's look-ahead delays the audio by its attack time unless 'latency' compensation exists (ffmpeg >= 5.1)."""
    return "latency" in run(["ffmpeg", "-hide_banner", "-h", "filter=alimiter"]).stdout.decode(errors="replace")


def amix_has_normalize():
    return "normalize" in run(["ffmpeg", "-hide_banner", "-h", "filter=amix"]).stdout.decode(errors="replace")


def slice_plan(plan, length=20.0):
    """Preview slice: ~20 s around the drop, cut at take boundaries (frame exact). A preview is SHORT on purpose."""
    takes = plan["takes"]
    centre = plan["song"]["drop_t"] if plan["song"].get("drop_t") is not None else plan["duration"] / 2
    t0 = max([t["f0"] for t in takes if t["f0"] <= (centre - 8.0) * OUT_FPS] or [0])
    sel = [t for t in takes if t["f0"] >= t0 and t["f0"] < t0 + length * OUT_FPS]
    nt = [dict(t, f0=t["f0"] - t0, out_start=round((t["f0"] - t0) / OUT_FPS, 4)) for t in sel]
    if nt:
        nt[0] = dict(nt[0], trans="hard")
    sg = dict(plan["song"], start_t=plan["song"]["start_t"] + t0 / OUT_FPS)
    tf = nt[-1]["f0"] + nt[-1]["nf"]
    sg["fade_out_start"] = max(0.0, min(sg["fade_out_start"] - t0 / OUT_FPS, tf / OUT_FPS - 1.0))
    return dict(plan, takes=nt, song=sg, duration=tf / OUT_FPS, total_frames=tf, preview=True)


def _sum_expr(terms):
    return "+".join(terms) if terms else "0"


def build_filter(plan, cfg, preview, fx=FX_ALL):
    """ONE filter graph (V4 engine). Effects sit on each take's own output timeline: centred V4 zoom punches on kills (overlaid
    only inside the punch), ramps before kills, V4 slow-mo (frame blending only inside slow-mo segments). V5.2: no flashes, no
    zoom / flash cuts - takes join on hard cuts. Music: never ducked, stretched or
    automated - sample-exact start, 0.3 s fade-in, fade-out from the final kill. Game audio: V4 balance + kill boost."""
    inputs, chains, k = [], [], 0
    takes = plan["takes"]
    exact = plan.get("placement", "v5") != "v4"
    vl = []
    for ti, t in enumerate(takes):
        srcs = t.get("srcs") or [{"path": t["path"], "shift": 0.0, "rect": t["rect"], "wh": t["wh"], "audio": t["audio"],
                                  "a_stream": 0, "gain_db": -6.0}]
        segs = [list(s) for s in t["segs"]]
        if "slow" not in fx:
            for s in segs:
                if s[2] in (0.5, 0.0):
                    s[1], s[2] = s[0] + s[3] / OUT_FPS, 1.0
        tv, ta = [], []
        off_f = 0
        for s in segs:
            a, b, sp, n = s[:4]
            src = srcs[s[4] if len(s) > 4 and s[4] < len(srcs) else 0]
            sa = a - src["shift"]
            dur_src = (b - a) if sp > 0 else 1.0 / OUT_FPS
            inputs += ["-threads", "2", "-ss", f"{max(0.0, sa):.4f}", "-t", f"{dur_src + 0.3:.4f}", "-i", src["path"]]
            cx, cy, cw, ch = src["rect"]
            crop = f"crop={cw}:{ch}:{cx}:{cy}," if [cx, cy, cw, ch] != [0, 0, src["wh"][0], src["wh"][1]] else ""
            scl = "scale=1920:1080:flags=lanczos," if (crop or list(src["wh"]) != [1920, 1080]) else ""
            v = f"[{k}:v:0]{crop}{scl}setsar=1,"
            if sp == 0.0:
                v += f"trim=end_frame=1,setpts=PTS-STARTPTS,fps=60,tpad=stop_mode=clone:stop_duration={n / OUT_FPS + 0.1:.4f}"
            elif sp < 1:
                v += f"setpts=(PTS-STARTPTS)/{sp:.4f},framerate=fps=60:scene=100"          # V4 slow-mo (blend only here)
            elif exact:
                v += f"setpts=PTS/{sp:.4f},fps=60:start_time=0"                            # real timestamps: frame-exact kills
            else:
                v += f"setpts=(PTS-STARTPTS)/{sp:.4f},fps=60"                              # V4 timing
            v += f",tpad=stop_mode=clone:stop_duration=0.3,trim=end_frame={n},setpts=PTS-STARTPTS[s{k}v]"
            chains.append(v)
            tv.append(f"[s{k}v]")
            out_len = n / OUT_FPS
            off = off_f / OUT_FPS
            if src["audio"] and sp > 0:
                gain = 10 ** (float(src.get("gain_db", -6.0)) / 20)
                boost = min(1.0, gain * 1.585)                                             # V4: about +4 dB around each kill
                at = f"atempo={min(2.0, max(0.5, sp)):.4f}," if abs(sp - 1.0) > 1e-3 else ""
                if sp > 2.0:
                    at = f"atempo=2.0,atempo={sp / 2:.4f},"
                kt = [f"between(t,{ko - off - 0.2:.3f},{ko - off + 0.2:.3f})" for ko in t["kills_out"] if -0.25 < ko - off < out_len + 0.25]
                vol = f"volume='{gain:.4f}+{max(0.0, boost - gain):.4f}*min(1,{_sum_expr(kt)})':eval=frame" if kt else f"volume={gain:.4f}"
                chains.append(f"[{k}:a:{int(src.get('a_stream') or 0)}]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                              f"{at}{vol},asetpts=PTS-STARTPTS,apad,atrim=duration={out_len:.4f}[s{k}a]")
            else:
                chains.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={out_len:.4f},asetpts=PTS-STARTPTS[s{k}a]")
            ta.append(f"[s{k}a]")
            off_f += n
            k += 1
        nf = off_f
        base = f"t{ti}"
        chains.append("".join(tv) + (f"concat=n={len(tv)}:v=1:a=0" if len(tv) > 1 else "null") + f"[{base}c]")
        chains.append("".join(ta) + (f"concat=n={len(ta)}:v=0:a=1" if len(ta) > 1 else "anull") + f"[{base}a]")
        # effects on the take's own timeline; frames outside an effect window stay untouched
        zt, wins = [], []
        tt = "(in/60)"                                                                     # take-timeline seconds inside perspective
        if "zoom" in fx:
            for p in t.get("pulses", []):                                                  # V4 punch: centred, peak on the kill, 0.45 s decay
                zt.append(f"between({tt},{p:.4f},{p + 0.45:.4f})*{t['amp']:.3f}*exp(-9*({tt}-{p:.4f}))")
                wins.append((p, p + 0.45))
        lab = f"[{base}c]"
        if zt:
            en_ = "+".join(f"between(t,{a_:.4f},{b_:.4f})" for a_, b_ in wins)
            m_ = f"(1-1/(1+{_sum_expr(zt)}))/2"                                            # inset of the sampled quad (fraction)
            chains.append(f"[{base}c]split=2[{base}m][{base}f]")
            chains.append(f"[{base}f]perspective=x0='W*{m_}':y0='H*{m_}':x1='W-W*{m_}':y1='H*{m_}':x2='W*{m_}':y2='H-H*{m_}':"
                          f"x3='W-W*{m_}':y3='H-H*{m_}':interpolation=cubic:eval=frame,format=yuv420p[{base}e]")
            chains.append(f"[{base}m]format=yuv420p[{base}m2]")
            chains.append(f"[{base}m2][{base}e]overlay=0:0:eof_action=pass:enable='{en_}'[{base}o]")
            lab = f"[{base}o]"
        chains.append(lab + f"format=yuv420p,trim=end_frame={nf},setpts=PTS-STARTPTS[{base}v]")
        vl.append(f"[{base}v][{base}a]")
    D = plan["duration"]
    fo = float(plan["song"].get("fade_out_start", max(0.0, D - 2.0)))
    fo = min(fo, D - 0.3)
    chains.append("".join(vl) + f"concat=n={len(takes)}:v=1:a=1[vc][gc]")
    chains.append(f"[vc]{'scale=1280:720:flags=bicubic,' if preview else ''}fade=t=in:st=0:d={FADE_IN},"
                  f"fade=t=out:st={fo:.3f}:d={max(0.3, D - fo):.3f},format=yuv420p[vout]")
    sidx = len([x for x in inputs if x == "-i"])
    inputs += ["-i", plan["song"]["path"]]
    head = 10 ** (-2.0 / 20)                               # 2 dB headroom on BOTH music and game (same balance), so the
    if exact:                                              # safety limiter almost never has to act -> no pumping
        chains.append(f"[{sidx}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB,"
                      f"atrim=start={plan['song']['start_t']:.6f}:duration={D + 0.05:.4f},asetpts=PTS-STARTPTS,volume={head:.4f}[sg]")
    else:
        inputs[-2:-2] = ["-ss", f"{plan['song']['start_t']:.3f}", "-t", f"{D + 0.6:.3f}"]
        chains.append(f"[{sidx}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,"
                      f"volume={head:.4f}[sg]")
    chains.append(f"[gc]volume={head:.4f}[gh]")
    mix = "amix=inputs=2:duration=first:normalize=0" if amix_has_normalize() else "amix=inputs=2:duration=first,volume=2"
    lim = "alimiter=limit=0.99:attack=2:release=40:level=disabled" + (":latency=1" if _alimiter_latency() else "")
    chains.append(f"[sg][gh]{mix},{lim},atrim=duration={D:.4f},afade=t=in:st=0:d={FADE_IN},"
                  f"afade=t=out:st={fo:.3f}:d={max(0.3, D - fo):.3f}[aout]")
    return inputs, ";\n".join(chains)


def enc_args(maxq, preview, nvenc):
    if preview:
        v = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "26", "-b:v", "0"] if nvenc else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "24"]
    elif maxq:
        v = ["-c:v", "libx264", "-crf", "15", "-preset", "slow"]
    elif nvenc:
        v = ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "16", "-b:v", "0", "-maxrate", "120M",
             "-bufsize", "240M", "-spatial-aq", "1", "-aq-strength", "8", "-rc-lookahead", "32", "-profile:v", "high"]
    else:
        v = ["-c:v", "libx264", "-crf", "17", "-preset", "medium"]
    return v + ["-pix_fmt", "yuv420p", "-r", "60", "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-movflags", "+faststart"]


def _run_ffmpeg(cmd, D, elog):
    with open(elog, "w", encoding="utf-8") as ef:
        pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ef, text=True)
        PROCS.append(pr)
        for line in pr.stdout:
            if line.startswith("out_time_us="):
                try:
                    fr = min(1.0, int(line.split("=")[1]) / 1e6 / D)
                    progress(fr, f"rendering {int(100 * fr)}%")
                except ValueError:
                    pass
            if CANCEL.is_set():
                pr.kill()
        pr.wait()
        if pr in PROCS:
            PROCS.remove(pr)
    return pr.returncode


def probe_duration(path):
    try:
        j = json.loads(run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,nb_frames,duration",
                            "-of", "json", str(path)]).stdout or b"{}")
        return float((j.get("format") or {}).get("duration") or 0)
    except Exception:
        return 0.0


# ======================================================================= V6.9.3 / V6.9.6: effective-fps interpolation at render time
# V6.9.6: container fps is the wrong basis (OBS .mov 50, DVR .mp4 60, some CS2 DVR clips are variable frame rate, game footage may be duplicated
# 30 fps, slow-mo shows every source frame twice). The decision is made per TAKE from the EFFECTIVE on-screen unique frame rate:
#   effective = min(timestamp fps, content fps (unique frames)) x playback speed, candidate when below 75% of the montage fps for
#   (a) slow-mo (speed < 1), (b) duplicated content / a low-fps source, (c) VFR gaps (>= 10% of the intervals above 1.5x the median, or a gap above 4 frames).
# Only the source ranges the takes use (+0.5 s margin) are converted to a temporary file that replaces the clip as that take's input (same timeline:
# the take's shift moves by the range start). The filter graph is NOT edited (the existing retime consumes the denser segment); everything that is not a
# candidate produces the byte-identical render command. Any problem uses the original clip. Hidden switch: config.json "interpolate_low_fps" (default true).
INTERP_FRAC = 0.75                      # candidate: effective fps below this share of the montage fps
INTERP_MARGIN_S = 0.5
INTERP_TIMEOUT_X = 4.0                  # a segment taking longer than this x its duration is abandoned
INTERP_MIN_TIMEOUT_S = 5.0              # (floor for very short segments)
INTERP_MIN_MEAN_SSIM, INTERP_MIN_FRAME_SSIM = 0.90, 0.75
INTERP_MCI = "minterpolate=fps=60:mi_mode=mci:mc_mode=obmc:me_mode=bidir:scd=fdiff:mb_size=8:search_param=8"      # conservative: smallest block / search, no vsbmc
INTERP_BLEND = "framerate=fps=60"                                                          # blend only (scene changes are duplicated)
INTERP_STATE = {"mci_slow": False}
INTERP_MAX_FPS = 240.0                  # never interpolate above this rate
INTERP_MAX_X = 4.0                      # nor above this multiple of the unique source rate
VFR_SHARE, VFR_GAP_FRAMES = 0.10, 4.0   # VFR candidate: >= 10% of the intervals above 1.5x the median, or any gap above 4 frames
DUP_MIN_MOTION = 0.6                    # mean abs grey difference (0-255) of the 75th percentile frame step below this = a static scene (not measurable)
CONTENT_WIN_S, CONTENT_MAX_S = 1.5, 4.0 # content fps window length / ranges longer than this are sampled in three windows


def _ratio(s):
    try:
        n, _, d = str(s).partition("/")
        return float(n) / float(d) if d and float(d) else (float(n) if not d else 0.0)
    except (TypeError, ValueError):
        return 0.0


def probe_fps(path):
    """{avg, r, nb, dur, eff, vfr} of the first video stream (ffprobe only). eff = frames / duration when known, else avg_frame_rate."""
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=avg_frame_rate,r_frame_rate,nb_frames,duration:format=duration", "-of", "json", str(path)], timeout=60)
    j = json.loads(r.stdout or b"{}")
    s = (j.get("streams") or [{}])[0]
    avg, rr = _ratio(s.get("avg_frame_rate")), _ratio(s.get("r_frame_rate"))
    try:
        nb = int(s.get("nb_frames"))
    except (TypeError, ValueError):
        nb = 0
    try:
        dur = float(s.get("duration") or (j.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    eff = nb / dur if nb > 1 and dur > 0 else (avg or rr)
    return {"avg": avg, "r": rr, "nb": nb, "dur": dur, "eff": eff, "vfr": bool(avg and rr and abs(avg - rr) > 0.5)}


def _run_timed(cmd, timeout):
    """(returncode, stderr text, stdout text); returncode None = timeout. Registered in PROCS so Cancel kills it."""
    pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    PROCS.append(pr)
    try:
        so, se = pr.communicate(timeout=timeout)
        return pr.returncode, se.decode(errors="replace"), so.decode(errors="replace")
    except subprocess.TimeoutExpired:
        pr.kill()
        pr.communicate()
        return None, "timeout", ""
    finally:
        if pr in PROCS:
            PROCS.remove(pr)


def interp_vf(method, fps):
    """The interpolation filter of `method` at output rate `fps` (the 60 fps strings are the V6.9.3 constants, byte for byte)."""
    base = INTERP_MCI if method == "mci" else INTERP_BLEND
    return base if abs(fps - OUT_FPS) < 1e-6 else base.replace("fps=60", f"fps={fps:g}", 1)


def interp_segment_cmd(src, s0, d, outp, method, fps=OUT_FPS, pre=""):
    """ffmpeg command for ONE segment [s0, s0+d) of `src`: `pre` (duplicate removal / retime, ends with a comma), then the interpolation to `fps`."""
    return ["ffmpeg", "-y", "-hide_banner", "-v", "error", "-ss", f"{s0:.4f}", "-t", f"{d:.4f}", "-i", str(src), "-map", "0:v:0", "-map", "0:a?",
            "-vf", f"{pre}tpad=stop_mode=clone:stop_duration={INTERP_MARGIN_S:.2f},{interp_vf(method, fps)},trim=end={d:.4f}", "-vsync", "0",
            "-c:v", "libx264", "-crf", "10", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", str(outp)]


def _ssim_values(a_chain, b_chain, a_in, b_in):
    cmd = ["ffmpeg", "-hide_banner", "-v", "error"] + a_in + b_in + ["-lavfi", f"[0:v]{a_chain}[a];[1:v]{b_chain}[b];[a][b]ssim,"
           "metadata=mode=print:key=lavfi.ssim.All:file=-", "-vsync", "0", "-f", "null", "-"]
    rc, err, so = _run_timed(cmd, 120)
    vals = [float(x) for x in re.findall(r"lavfi\.ssim\.All=([\d.]+)", so)]
    return rc, err, vals


def interp_validate(src, seg, s0, d, src_fps, out_fps=OUT_FPS):
    """None when the interpolated segment is sound, else the reason (see the V6.9.3 rules; V6.9.6: at the segment's own output rate)."""
    seg = Path(seg)
    if not seg.exists() or seg.stat().st_size < 1000:
        return "temp file missing"
    dur = probe_duration(seg)
    if abs(dur - d) > 1.0 / out_fps + 0.002:
        return f"duration {dur:.3f} s instead of {d:.3f} s"
    r = run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames,start_time",
             "-of", "json", str(seg)], timeout=120)
    try:
        st = json.loads(r.stdout or b"{}")["streams"][0]
        n, t0 = int(st["nb_read_frames"]), float(st.get("start_time") or 0)
    except Exception:
        return "frame count unreadable"
    want = int(round((d - t0) * out_fps))
    if abs(n - want) > (0 if t0 < 0.001 else 1):
        return f"{n} frames instead of {want}"
    ain, bin_ = ["-ss", "0", "-i", str(seg)], ["-ss", f"{s0:.4f}", "-t", f"{d:.4f}", "-i", str(src)]
    small = "scale=480:-2:flags=bilinear,format=yuv420p"
    rc, err, v60 = _ssim_values(f"{small}", f"{small},fps={out_fps:g}:round=near", ain, bin_)          # every frame vs its nearest source frame
    err = "\n".join(l for l in err.splitlines() if "non monotonically" not in l).strip()      # (a muxer remark of the null output, not a decode problem)
    if rc != 0 or err:
        return "decode error: " + err[:80]
    if not v60:
        return "SSIM not measurable"
    if min(v60) < INTERP_MIN_FRAME_SSIM:
        return f"a frame differs too much from its nearest source frame (SSIM {min(v60):.2f})"
    rc, err, vo = _ssim_values(f"{small},fps={src_fps:.4f}:round=near", small, ain, bin_)             # at the source frame times
    if rc != 0 or not vo:
        return "SSIM at the source times not measurable"
    if sum(vo) / len(vo) < INTERP_MIN_MEAN_SSIM:
        return f"mean SSIM {sum(vo) / len(vo):.2f} against the source frames"
    return None


# ---------------------------------------------------------------- V6.9.6: effective fps measurement (read-only, ffprobe / ffmpeg decode of small ranges)
def probe_timestamps(path, s0, e):
    """Packet timestamps (s, sorted) of the first video stream inside [s0, e] (ffprobe only, no decoding)."""
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-read_intervals", f"{s0:.3f}%{e:.3f}", "-show_entries", "packet=pts_time",
             "-of", "csv=p=0", str(path)], timeout=60)
    ts = []
    for l_ in (r.stdout or b"").decode(errors="replace").split():
        try:
            ts.append(float(l_.strip(",")))
        except ValueError:
            pass
    ts = sorted(t for t in ts if s0 - 1e-3 <= t <= e + 1e-3)
    return ts


def ts_stats(ts):
    """Timestamp fps and VFR gap statistics from sorted frame times."""
    import numpy as np
    if len(ts) < 3:
        return {"n": len(ts), "ts_fps": 0.0, "median_dt": 0.0, "gap_share": 0.0, "max_gap_frames": 0.0, "vfr": False}
    d = np.diff(np.asarray(ts))
    d = d[d > 1e-6]
    if not len(d):
        return {"n": len(ts), "ts_fps": 0.0, "median_dt": 0.0, "gap_share": 0.0, "max_gap_frames": 0.0, "vfr": False}
    med = float(np.median(d))
    share = float(np.mean(d > 1.5 * med))
    mg = float(d.max() / med)
    return {"n": len(ts), "ts_fps": float((len(ts) - 1) / (ts[-1] - ts[0])) if ts[-1] > ts[0] else 0.0, "median_dt": med, "gap_share": share,
            "max_gap_frames": mg, "vfr": bool(share >= VFR_SHARE or mg > VFR_GAP_FRAMES)}


def gray_frames(path, s0, d, w=160, h=90):
    """Small grey frames of the CENTRAL 60% of the picture (static HUD and black bars are outside it) of [s0, s0+d), every decoded frame, no resampling."""
    import numpy as np
    r = run(["ffmpeg", "-v", "error", "-ss", f"{s0:.4f}", "-t", f"{d:.4f}", "-i", str(path), "-an", "-vf",
             f"crop=iw*0.6:ih*0.6:iw*0.2:ih*0.2,scale={w}:{h}:flags=area,format=gray", "-vsync", "0", "-f", "rawvideo", "-"], timeout=180)
    a = np.frombuffer(r.stdout or b"", np.uint8)
    n = len(a) // (w * h)
    return a[:n * w * h].reshape(n, h, w).astype(np.float32)


def frame_uniqueness(fr):
    """(unique flags per frame step, motion level). Frame i is unique when it differs from frame i-1 by more than the duplicate threshold."""
    import numpy as np
    if len(fr) < 4:
        return None, 0.0
    d = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2))
    mot = float(np.percentile(d, 75))
    thr = max(0.25, 0.12 * mot)
    return d > thr, mot


def cadence_of(uniq):
    """Regular duplicate cadence from the unique flags of the frame steps: (period, phase) when >= 85% of the unique-to-unique distances are equal and
    the period is 2 or more frames, (1, 0) when nothing is duplicated, else None (irregular). phase = frame index mod period of the first frame of a new picture."""
    import numpy as np
    idx = np.where(uniq)[0] + 1                     # frame numbers (step i compares frame i+1 with frame i) that show a new picture
    if len(idx) < 4:
        return None
    g = np.diff(idx)
    per = int(np.bincount(g).argmax())
    if np.mean(g == per) < 0.85:
        return None
    return per, int(np.bincount(idx % per).argmax())


def measure_content(path, s0, e):
    """Content fps pieces for [s0, e]: unique share of the decoded frames (central region), regular cadence, static scene flag."""
    wins = [(s0, e - s0)] if e - s0 <= CONTENT_MAX_S else [(s0, CONTENT_WIN_S), ((s0 + e) / 2 - CONTENT_WIN_S / 2, CONTENT_WIN_S), (e - CONTENT_WIN_S, CONTENT_WIN_S)]
    n = u = 0
    mots, cads = [], []
    for w0, wd in wins:
        fr = gray_frames(path, max(0.0, w0), wd)
        uq, mot = frame_uniqueness(fr)
        if uq is None:
            continue
        n += len(uq)
        u += int(uq.sum())
        mots.append(mot)
        cads.append(cadence_of(uq))
    if not n:
        return {"unique_share": 1.0, "cadence": None, "static": True, "motion": 0.0, "frames": 0}
    cad = cads[0] if cads and all(c is not None and c[0] == cads[0][0] for c in cads if c is not None) and cads[0] is not None else None
    return {"unique_share": u / n, "cadence": cad, "static": bool(max(mots) < DUP_MIN_MOTION), "motion": max(mots), "frames": n}


def measure_range(path, lo, hi, dur, probe=None):
    """Everything fpscontent / the render needs about the source range [lo, hi] (+ margin) of one clip: timestamp fps and gaps, content fps, cadence."""
    s0 = max(0.0, lo - INTERP_MARGIN_S)
    e = hi + INTERP_MARGIN_S
    if dur > 0:
        e = min(e, dur)
    pr = probe or probe_fps(path)
    st = ts_stats(probe_timestamps(path, s0, e))
    ts_fps = st["ts_fps"] or pr["eff"] or pr["avg"]
    ct = measure_content(path, s0, e)
    cfps = ts_fps * ct["unique_share"] if not ct["static"] else ts_fps
    return {"s0": s0, "e": e, "container": pr, "ts": st, "ts_fps": ts_fps, "content": ct, "content_fps": cfps}


def classify_range(m, speed):
    """Reasons (list of 'slow-mo' / 'duplicated frames' / 'vfr gaps' / 'low fps') why a take that shows this range at `speed` is below 75% of the
    montage fps in EFFECTIVE unique frames per second; [] = fine. speed > 1 (ramps) never counts as slow-mo."""
    thr = INTERP_FRAC * OUT_FPS
    why = []
    base = min(m["ts_fps"], m["content_fps"]) if m["ts_fps"] else 0.0
    if m["ts"]["vfr"]:
        why.append("vfr gaps")
    elif 0 < m["ts_fps"] < thr:
        why.append("low fps")
    if m["ts_fps"] >= thr and 0 < m["content_fps"] < thr and not m["content"]["static"]:
        why.append("duplicated frames")
    if 0 < speed < 1 and 0 < base * speed < thr:
        why.append("slow-mo")
    return why


def take_source_ranges(t, srcs, fx=None):
    """Per source of a take: {"all": (lo, hi), "slow": [(lo, hi, speed)]} in the source's own time, with the SAME range maths the render uses
    (the no-slow-mo retry window included). Freeze frames (speed 0) are stills and are not measured."""
    out_ = {}
    for sg in t["segs"]:
        a, b, sp, n = sg[:4]
        if fx is not None and "slow" not in fx and sp in (0.5, 0.0):
            b, sp = a + n / OUT_FPS, 1.0
        si = sg[4] if len(sg) > 4 and sg[4] < len(srcs) else 0
        sa = a - srcs[si]["shift"]
        need = max((b - a) if sp > 0 else 1.0 / OUT_FPS, n / OUT_FPS) + 0.3
        rg = out_.setdefault(si, {"all": None, "slow": []})
        lo, hi = rg["all"] or (sa, sa + need)
        rg["all"] = (min(lo, sa), max(hi, sa + need))
        if 0 < sp < 1:
            rg["slow"].append((sa, sa + max((b - a), n / OUT_FPS * sp) + 0.3, sp))
    return out_


def analyse_takes(plan, fx=None, workers=4):
    """Measure every (take, source) of a plan. Returns [{"take": i, "si": si, "path", "range", "m", "speed", "why", ...}] (read-only)."""
    from concurrent.futures import ThreadPoolExecutor
    jobs = []
    probes = {}
    for ti, t in enumerate(plan["takes"]):
        srcs = t.get("srcs") or [{"path": t["path"], "shift": 0.0}]
        for si, rg in take_source_ranges(t, srcs, fx).items():
            if rg["all"] is None:
                continue
            jobs.append((ti, si, srcs[si], rg))

    def one(job):
        ti, si, src, rg = job
        pth = src["path"]
        try:
            if pth not in probes:
                probes[pth] = probe_fps(pth)
            pr = probes[pth]
            lo, hi = rg["all"]
            m = measure_range(pth, lo, hi, pr["dur"], pr)
            spd = min([s_[2] for s_ in rg["slow"]], default=1.0)
            return {"take": ti, "si": si, "path": pth, "range": (lo, hi), "slow": rg["slow"], "m": m, "speed": spd, "why": classify_range(m, spd)}
        except Exception as ex:
            return {"take": ti, "si": si, "path": pth, "range": rg["all"], "slow": rg["slow"], "m": None, "speed": 1.0, "why": [], "error": f"{type(ex).__name__}: {ex}"}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        return list(ex.map(one, jobs))


def detect_dup_chain(path, s0, d):
    """The duplicate-removal prefix for the segment [s0, s0+d) of `path`, measured on the SAME extraction the segment is cut from, plus the unique
    rate: (prefix filter, unique fps, how). Regular cadence: select by the detected phase and re-time to the exact original times; irregular: mpdecimate."""
    fr = gray_frames(path, s0, min(d, 3.0))
    uq, mot = frame_uniqueness(fr)
    if uq is None or mot < DUP_MIN_MOTION:
        return "", 0.0, "none"
    pr = probe_fps(path)
    f = pr["eff"] or pr["avg"] or float(OUT_FPS)
    cad = cadence_of(uq)
    if cad is not None and cad[0] >= 2:
        per, ph = cad
        return (f"select='eq(mod(n\\,{per})\\,{ph})',setpts=(N*{per}+{ph})/({f:.5f}*TB),", f / per, f"cadence {per} phase {ph}")
    if cad is not None and cad[0] == 1:
        return "", f, "none"
    share = float(uq.mean())
    return f"mpdecimate,setpts=N/({f * share:.5f}*TB),", f * share, "mpdecimate"


def interp_prepare(plan, cfg, tmpdir, fx=FX_ALL):
    """Returns the plan to build the filter from (the SAME plan object when nothing is interpolated)."""
    if not cfg.get("interpolate_low_fps", True):
        out("fps: interpolation disabled (interpolate_low_fps = false), no clips probed")
        return plan
    res = analyse_takes(plan, fx)
    n_takes = len(plan["takes"])
    bad_ = [r_ for r_ in res if r_.get("error")]
    cand = [r_ for r_ in res if r_["why"]]
    cnt = {k: sum(1 for r_ in cand if k in r_["why"]) for k in ("slow-mo", "duplicated frames", "vfr gaps", "low fps")}
    reasons = f"slow-mo {cnt['slow-mo']}, duplicated {cnt['duplicated frames']}, vfr {cnt['vfr gaps']}" + (f", low-fps {cnt['low fps']}" if cnt["low fps"] else "")
    if not cand:
        out(f"fps: {n_takes} takes probed, 0 low-effective-fps" + (f" ({len(bad_)} unreadable)" if bad_ else ""))
        return plan
    done, fell = 0, 0
    new_takes = list(plan["takes"])
    INTERP_STATE["mci_slow"] = False
    idx = 0
    by_take = {}
    for r_ in cand:
        by_take.setdefault(r_["take"], []).append(r_)
    for ti in sorted(by_take):
        t = plan["takes"][ti]
        srcs = [dict(s) for s in (t.get("srcs") or [{"path": t["path"], "shift": 0.0, "rect": t["rect"], "wh": t["wh"], "audio": t["audio"],
                                                       "a_stream": 0, "gain_db": -6.0}])]
        changed = False
        for r_ in by_take[ti]:
            if CANCEL.is_set():
                raise RuntimeError("cancelled")
            si, m = r_["si"], r_["m"]
            nm = Path(srcs[si]["path"]).name
            whole = any(k in r_["why"] for k in ("vfr gaps", "low fps", "duplicated frames"))
            lo, hi = r_["range"] if whole else (min(x[0] for x in r_["slow"]), max(x[1] for x in r_["slow"]))
            pr = m["container"]
            s0 = max(0.0, lo - INTERP_MARGIN_S)
            e = hi + INTERP_MARGIN_S
            if pr["dur"] > 0:
                e = min(e, pr["dur"])
            d = e - s0
            sp = r_["speed"]
            urate = min(m["ts_fps"], m["content_fps"]) or m["ts_fps"] or float(OUT_FPS)
            out(f"effective fps: {nm} {lo:.2f}-{hi:.2f} s container {pr['eff']:.0f}, content {m['content_fps']:.0f}, speed {sp:.2f} -> "
                f"{min(m['ts_fps'], m['content_fps']) * sp:.0f} effective -> interpolating ({' + '.join(r_['why'])})")
            if d < 0.2:
                continue
            pre, how = "", ""
            try:
                if "duplicated frames" in r_["why"]:
                    pre, urate, how = detect_dup_chain(srcs[si]["path"], s0, d)
                    urate = urate or float(OUT_FPS) / 2
            except Exception as ex:
                out(f"interpolation skipped: {nm} (duplicate detection failed: {type(ex).__name__}: {ex})")
                fell += 1
                continue
            target = float(OUT_FPS)
            if sp < 1:
                target = max(float(OUT_FPS), min(INTERP_MAX_FPS, OUT_FPS / sp, INTERP_MAX_X * max(urate, 1.0)))
                target = float(round(target))
            seg = Path(tmpdir) / f"seg{idx}.mov"
            idx += 1
            why = None
            t_start = time.time()
            method = "blend" if INTERP_STATE["mci_slow"] else "mci"
            for method in ((method,) if method == "blend" else ("mci", "blend")):
                Path(tmpdir).mkdir(parents=True, exist_ok=True)
                t_start = time.time()
                rc, err, _ = _run_timed(interp_segment_cmd(srcs[si]["path"], s0, d, seg, method, target, pre) if (target != OUT_FPS or pre)
                                        else interp_segment_cmd(srcs[si]["path"], s0, d, seg, method), max(INTERP_MIN_TIMEOUT_S, INTERP_TIMEOUT_X * d))
                if rc is None and method == "mci":
                    INTERP_STATE["mci_slow"] = True
                    out(f"interpolation: motion method needs more than {INTERP_TIMEOUT_X:.0f}x real time on this PC - blend is used instead")
                    continue
                why = "timeout (more than %gx the segment)" % INTERP_TIMEOUT_X if rc is None else (None if rc == 0 else "ffmpeg error: " + err.strip()[-120:])
                break
            if CANCEL.is_set():
                raise RuntimeError("cancelled")
            if why is None:
                why = interp_validate(srcs[si]["path"], seg, s0, d, pr["eff"] or pr["avg"] or float(OUT_FPS), target)
            if why:
                fell += 1
                out(f"interpolation skipped: {nm} ({why})")
                try:
                    seg.unlink()
                except OSError:
                    pass
                continue
            out(f"interpolated {nm} {s0:.2f}-{e:.2f} s {urate:.0f} -> {target:g} fps method={method}{' (' + how + ' removed first)' if pre else ''} "
                f"in {time.time() - t_start:.1f} s")
            srcs[si].update(path=str(seg), shift=round(srcs[si]["shift"] + s0, 6))
            done += 1
            changed = True
        if changed:
            new_takes[ti] = dict(t, srcs=srcs)
    out(f"fps: {n_takes} takes probed, {len(cand)} low-effective-fps ({reasons}), {done} interpolated, {fell} fell back")
    return dict(plan, takes=new_takes) if done else plan


def cmd_fpscheck(args):
    """V6.9.3: python montage.py fpscheck [game] [--limit N] [--all]. Read-only: the real frame rate (ffprobe) of the clips of the newest saved dry plan
    (montage_data\\plans), or with --all of every cached clip; how many would be interpolation candidates in a montage of OUT_FPS. Writes fpscheck.txt
    next to montage.py, never a cache."""
    game = getattr(args, "game", None)
    if getattr(args, "all", False):
        clips = load_json(CLIPS_CACHE, {})
        paths = sorted(r["path"] for r in clips.values() if isinstance(r, dict) and r.get("path") and os.path.exists(r["path"]) and not r.get("error"))
        if game:
            cfg = load_config()
            paths = [p_ for p_ in paths if tag_game(p_, cfg)[0] == game]
        what = f"all cached clips{' of ' + game if game else ''}"
    else:
        plans = sorted((DATA / "plans").glob("*.dry.json"), key=lambda p_: p_.stat().st_mtime) if (DATA / "plans").is_dir() else []
        plans = [p_ for p_ in plans if not game or load_json(p_, {}).get("game") == game]
        if not plans:
            print("fpscheck: no saved dry plan found - run a Dry plan first, or use --all")
            return
        pl = load_json(plans[-1], {})
        paths = []
        for t in pl.get("takes", []):
            for s_ in (t.get("srcs") or [{"path": t.get("path")}]):
                if s_.get("path") and s_["path"] not in paths and os.path.exists(s_["path"]):
                    paths.append(s_["path"])
        what = f"the clips of the newest dry plan ({plans[-1].name})"
    lim = int(getattr(args, "limit", 0) or 0)
    if lim:
        paths = paths[:lim]
    lines, n_cand = [], 0
    for p_ in paths:
        try:
            i = probe_fps(p_)
        except Exception as ex:
            lines.append(f"{p_}  unreadable ({ex})")
            continue
        cand = 0 < i["eff"] < INTERP_FRAC * OUT_FPS
        n_cand += cand
        lines.append(f"{Path(p_).name}  {i['eff']:.2f} fps (avg {i['avg']:.2f}, r {i['r']:.2f}, frames {i['nb']}{', variable' if i['vfr'] else ''})"
                     + ("  -> interpolation candidate" if cand else ""))
    head = f"fpscheck: {len(paths)} clips from {what}; {n_cand} would be interpolation candidates in a {OUT_FPS} fps montage (below {INTERP_FRAC * OUT_FPS:.0f} fps)"
    text = "\n".join([head] + lines)
    (HERE / "fpscheck.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"(written to {HERE / 'fpscheck.txt'}; nothing else was changed)")


def _fmt_range(m):
    return f"{m['s0']:.1f}-{m['e']:.1f} s"


def fpscontent_line(name, rng_txt, m, speed, why, extra=""):
    """One report line of fpscontent for a take / clip range."""
    pr, st, ct = m["container"], m["ts"], m["content"]
    cad = ("static scene (not measurable)" if ct["static"] else
           (f"cadence period {ct['cadence'][0]} phase {ct['cadence'][1]}" if ct["cadence"] and ct["cadence"][0] >= 2 else
            ("no duplicates" if ct["unique_share"] > 0.97 else "irregular duplicates")))
    eff = min(m["ts_fps"], m["content_fps"]) * speed
    info = ""
    if not why and 40 <= m["ts_fps"] < 0.9 * OUT_FPS and abs(m["ts_fps"] - 50) <= 2.5:
        info = f" | info: cadence {m['ts_fps']:.0f}->{OUT_FPS} (every 5th frame shown twice, no action)"
    return (f"{name} {rng_txt}: container avg {pr['avg']:.1f} / r {pr['r']:.1f}, timestamps {m['ts_fps']:.1f} fps, "
            f"gaps {st['gap_share']:.0%} above 1.5x median (largest {st['max_gap_frames']:.1f} frames), content {m['content_fps']:.1f} fps ({cad}), "
            f"speed {speed:.2f} -> effective {eff:.1f} fps -> " + ("ok" if not why else "LOW-EFFECTIVE-FPS: " + " + ".join(why)) + info + extra)


def cmd_fpscontent(args):
    """V6.9.6: python montage.py fpscontent [<montage.mp4> | <clip names...> | --all] [--limit N]. Read-only: the EFFECTIVE on-screen fps of every take of a
    montage (its .plan.json), of the named clips or (--all) of 2 s windows of the cached clips: timestamp fps, VFR gaps, content fps (unique frames),
    playback speed, verdict. Writes fpscontent.txt next to montage.py, never a cache / flag / config."""
    tg = list(getattr(args, "target", None) or [])
    lines, counts, n = [], {"slow-mo": 0, "duplicated frames": 0, "vfr gaps": 0, "low fps": 0}, 0
    lim = int(getattr(args, "limit", 0) or 0)
    pj = None
    if len(tg) == 1 and tg[0].lower().endswith(".mp4") and Path(tg[0]).exists() and not getattr(args, "all", False):
        f = Path(tg[0])
        pj = next((q for q in (f.parent / "logs" / (f.stem + ".plan.json"), f.with_suffix(".plan.json")) if q.exists()), None)
        if not pj and not _FN_TIME.search(f.name):                # a montage file (no recording time in its name): its newest plan
            cands = sorted(list(f.parent.glob("*.plan.json")) + list((f.parent / "logs").glob("*.plan.json")), key=lambda p_: p_.stat().st_mtime)
            pj = cands[-1] if cands else None
    if pj:
        plan = load_json(pj, {})
        head = f"fpscontent: takes of {f.name} (plan {pj.name}, {len(plan.get('takes', []))} takes, montage {OUT_FPS} fps)"
        for r_ in analyse_takes(plan):
            if lim and n >= lim:
                break
            n += 1
            nm = Path(r_["path"]).name
            if r_.get("error"):
                lines.append(f"take {r_['take'] + 1}: {nm} unreadable ({r_['error']})")
                continue
            sp_all = [sg[2] for sg in plan["takes"][r_["take"]]["segs"] if sg[2] > 0]
            spd = r_["speed"] if r_["speed"] < 1 else (max(sp_all) if sp_all else 1.0)
            why = r_["why"]
            for k in why:
                counts[k] += 1
            lines.append("take %d: " % (r_["take"] + 1) + fpscontent_line(nm, _fmt_range(r_["m"]), r_["m"], r_["speed"] if r_["speed"] < 1 else 1.0, why,
                                                                         f" | plan speed {spd:.2f}{' (slow-mo)' if r_['speed'] < 1 else ' (ramp)' if spd > 1.01 else ''}"))
    else:
        clips = load_json(CLIPS_CACHE, {})
        allp = sorted(r["path"] for r in clips.values() if isinstance(r, dict) and r.get("path") and os.path.exists(r["path"]) and not r.get("error"))
        if getattr(args, "all", False) or not tg:
            paths = allp
            if not getattr(args, "all", False):
                print("fpscontent: give a montage .mp4, clip names or --all")
                return
        else:
            paths = []
            for t_ in tg:
                paths += [q for q in ([t_] if os.path.exists(t_) else allp) if os.path.exists(q) and (q == t_ or t_.lower() in Path(q).name.lower())]
        paths = list(dict.fromkeys(paths))[:lim or (40 if getattr(args, "all", False) else 1000)]
        head = f"fpscontent: {len(paths)} clip(s), 2 s window in the middle of each (montage {OUT_FPS} fps)"
        for q in paths:
            try:
                pr = probe_fps(q)
                mid = max(0.0, pr["dur"] / 2 - 1.0)
                m = measure_range(q, mid + INTERP_MARGIN_S, mid + 2.0 - INTERP_MARGIN_S, pr["dur"], pr)
                why = classify_range(m, 1.0)
            except Exception as ex:
                lines.append(f"{Path(q).name} unreadable ({ex})")
                continue
            n += 1
            for k in why:
                counts[k] += 1
            lines.append(fpscontent_line(Path(q).name, _fmt_range(m), m, 1.0, why))
    summ = (f"summary: {n} measured, takes per reason: slow-mo {counts['slow-mo']}, duplicated frames {counts['duplicated frames']}, "
            f"vfr gaps {counts['vfr gaps']}, low fps {counts['low fps']}")
    text = "\n".join([head] + lines + [summ])
    (HERE / "fpscontent.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"(written to {HERE / 'fpscontent.txt'}; nothing else was changed)")


def cmd_interpbench(args):
    """V6.9.6: python montage.py interpbench [clip]. Seconds of ffmpeg time per source second for the motion (mci) and the blend interpolation on a 5 s
    sample, and the verdict the render will reach on THIS PC. Writes nothing into montage_data (a temp folder that is deleted)."""
    import tempfile
    q = getattr(args, "clip", None)
    cands = []
    if q and os.path.exists(q):
        cands = [q]
    else:
        clips = load_json(CLIPS_CACHE, {})
        allp = sorted(r["path"] for r in clips.values() if isinstance(r, dict) and r.get("path") and os.path.exists(r["path"]) and not r.get("error"))
        if q:
            allp = [p_ for p_ in allp if q.lower() in Path(p_).name.lower()]
        cands = allp
    if not cands:
        print("interpbench: no clip found (give a path or a name fragment)")
        return
    pick = cands[0]
    for p_ in cands[:12]:                                   # the first clip that would be a candidate, else the first clip
        try:
            pr = probe_fps(p_)
            if classify_range(measure_range(p_, 0.0, 2.0, pr["dur"], pr), 1.0):
                pick = p_
                break
        except Exception:
            continue
    pr = probe_fps(pick)
    s0 = max(0.0, min(pr["dur"] - 5.0, pr["dur"] / 3)) if pr["dur"] > 5.5 else 0.0
    d = min(5.0, pr["dur"] - s0) if pr["dur"] else 5.0
    res = {}
    with tempfile.TemporaryDirectory(prefix="interpbench_") as td:
        for method in ("mci", "blend"):
            t0 = time.time()
            rc, err, _ = _run_timed(interp_segment_cmd(pick, s0, d, Path(td) / f"{method}.mov", method), 600)
            res[method] = (time.time() - t0) / d if rc == 0 else None
    fmt = lambda v: "failed" if v is None else f"{v:.1f} s per source second"
    ok = res["mci"] is not None and res["mci"] <= INTERP_TIMEOUT_X
    print(f"interpbench: {Path(pick).name} ({pr['eff']:.1f} fps), {d:.1f} s sample from {s0:.1f} s")
    print(f"  motion (mci):  {fmt(res['mci'])}")
    print(f"  blend:         {fmt(res['blend'])}")
    print(f"  verdict: " + ("mci ok (a segment finishes within the %gx real-time limit)" % INTERP_TIMEOUT_X if ok else
                            "too slow, blend will be used (mci needs more than %gx real time on this PC)" % INTERP_TIMEOUT_X))
    print("(nothing was written into montage_data)")


def render_tmpdir(outfile):
    return Path(outfile).with_name(Path(outfile).stem + ".interp")


def render_plan(plan, outfile, cfg, maxq=False, preview=False, encoder=None, effects=True):
    """Encode with all effects; if ffmpeg fails, retry without the failing effect, then without all effects. NVENC -> x264.
    The finished file must last exactly as long as the plan (else it is reported as a failure, never silently kept)."""
    outfile = Path(outfile)
    outfile.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    p = slice_plan(plan) if preview else plan
    bad = verify_cutlist(p)
    for b_ in [x for x in bad if "kill row" in x]:
        out("WARNING (render continues): " + b_)
    bad = [x for x in bad if "kill row" not in x]
    if bad:
        raise RuntimeError("cut list problem, not rendering: " + "; ".join(bad))
    D = p["duration"]
    nvenc = ff_has("encoders", "h264_nvenc") if encoder is None else encoder == "nvenc"
    tmp = outfile.with_name(outfile.stem + ".part.mp4")
    elog = LOG_DIR / "last_render_stderr.txt"
    gp = LOG_DIR / "last_filter.txt"
    fx, failed = (set(FX_ALL) if effects else {"slow"}), []
    itmp = render_tmpdir(outfile)
    try:                                                   # V6.9.3: low-fps clips are interpolated first (only the ranges the plan uses)
        pr_ = interp_prepare(p, cfg, itmp, fx)
    except Exception as ex:
        if CANCEL.is_set():
            shutil.rmtree(itmp, ignore_errors=True)
            raise RuntimeError("cancelled")
        out(f"interpolation skipped: {type(ex).__name__}: {ex}")
        pr_ = p
    try:
        return _render_loop(plan, p, pr_, outfile, cfg, maxq, preview, encoder, effects, nvenc, tmp, elog, gp, fx, failed, D)
    finally:
        shutil.rmtree(itmp, ignore_errors=True)


def _render_loop(plan, p, pr_, outfile, cfg, maxq, preview, encoder, effects, nvenc, tmp, elog, gp, fx, failed, D):
    while True:
        inputs, graph = build_filter(pr_, cfg, preview, fx)
        gp.write_text(graph, encoding="utf-8")
        txt = ""
        for use_nv in ((nvenc, False) if nvenc else (False,)):
            cmd = (["ffmpeg", "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1"] + inputs +
                   ["-filter_complex_script", str(gp), "-map", "[vout]", "-map", "[aout]", "-t", f"{D:.4f}"] +
                   enc_args(maxq, preview, use_nv) + (["-preset", "veryfast"] if encoder == "fast" else []) + [str(tmp)])
            rc = _run_ffmpeg(cmd, D, elog)
            if CANCEL.is_set():
                raise RuntimeError("cancelled")
            if rc == 0 and tmp.exists():
                got = probe_duration(tmp)
                if abs(got - D) > 0.1:
                    txt = elog.read_text(encoding="utf-8", errors="replace")
                    out(f"rendered file lasts {got:.2f} s but the plan is {D:.2f} s - treating as a failure")
                    rc = 1
                else:
                    os.replace(tmp, outfile)
                    out(f"rendered {outfile} ({got:.2f} s = plan {D:.2f} s)" +
                        (f"   (effects that failed and were skipped: {', '.join(failed)})" if failed else ""))
                    plan["fx_failed"] = failed
                    plan["fx"] = sorted(fx)
                    return outfile
            txt = txt or elog.read_text(encoding="utf-8", errors="replace")
            out(f"ffmpeg failed ({'NVENC' if use_nv else 'x264'}): {txt[-500:]}")
            if not (use_nv and any(w in txt.lower() for w in ("nvenc", "cuda", "encoder", "driver"))):
                break
            out("retrying with libx264")
        if not fx:
            break
        low = txt.lower()
        culprit = next((n for key, n in (("overlay", "zoom"), ("drawbox", "flash"), ("framerate", "slow"), ("atempo", "slow"),
                                         ("tpad", "slow")) if key in low and n in fx), None) or \
            next(n for n in ("transition", "zoom", "flash", "slow") if n in fx)
        failed.append(culprit)
        fx.discard(culprit)
        out(f"effect '{culprit}' failed - retrying without it" + ("" if fx else " (no effects left)"))
    raise RuntimeError(f"render failed even without effects - see {elog} and {gp}")


def sync_report(plan, outfile, cfg):
    """Runs the kill detector on the finished montage; each first kill vs its beat, the drop, effects and tails."""
    import numpy as np
    game = plan["game"]
    det = load_dets(game).get(game)
    if not det:
        return
    out("SYNC REPORT: scanning the finished montage with the kill detector ...")
    rec = probe_video(str(outfile))
    rec.update(path=str(outfile), game=game, bars=False)
    entry = scan_clip(str(outfile), rec, det, cfg)
    seen = [k["t"] for k in analyse_entry(entry, cfg)["kills"]]
    beats = np.array(plan["beats_out"]) if plan["beats_out"] else np.zeros(1)
    out(f"SYNC REPORT  recipe {plan['recipe']}  seed {plan['seed']}  placement {plan['placement']}  "
        f"drop at {plan['song'].get('drop_t')}s  drops in the song window: {plan.get('drops_out')}")
    for i, t in enumerate(plan["takes"], 1):
        tp = t["out_start"] + t["kills_out"][0]
        kb = int(np.argmin(np.abs(beats - tp)))
        rows = [t["out_start"] + r for r in t["rows_out"]]
        found = sum(1 for r in rows if any(abs(x - r) <= 0.2 for x in seen))
        out(f"  take {i:2} [{t['role']:8}] first kill {tp:7.3f}s, beat {beats[kb]:7.3f}s, error {(tp - beats[kb]) * 1000:+5.0f} ms | "
            f"kill rows seen by the detector {found}/{len(rows)} | tail {t['dur'] - t['kills_out'][-1]:.2f}s | "
            f"zoom {len(t['pulses'])} flash {'yes' if t['flash'] is not None else 'no'} trans {t['trans']} "
            f"slow-mo {'yes' if t['slow'] else 'no'}")
    out(f"SYNC SUMMARY: detector found {len(seen)} kill rows for {sum(t['n'] for t in plan['takes'])} planned kills")


def quality_check(plan, outfile, cfg, preview=False):
    """SSIM of the rendered frames vs the source frames on one effect-free stretch (1.0x, no zoom/flash/transition, away from the
    fades). Target >= 0.97. Returns the value (or None when no clean stretch exists)."""
    takes = plan["takes"]
    D = plan["duration"]
    fo = plan["song"].get("fade_out_start", D)
    best = None
    for t in sorted(takes, key=lambda t: (t["trans"] != "hard", bool(t["pulses"]))):
        off = 0
        for sg in t["segs"]:
            a, b, sp, n = sg[:4]
            if sp == 1.0 and n >= 30:
                busy = list(t["pulses"]) + ([t["flash"]] if t["flash"] is not None else [])
                for start in (off / OUT_FPS + 0.45, off / OUT_FPS + 0.8):
                    if start + 0.5 > (off + n) / OUT_FPS or any(start - 0.5 < x < start + 0.6 for x in busy):
                        continue
                    g0 = t["out_start"] + start
                    if g0 < FADE_IN + 0.1 or g0 + 0.5 > fo - 0.05:
                        continue
                    src = t["srcs"][sg[4] if len(sg) > 4 else 0]
                    best = (g0, a + (start - off / OUT_FPS) - src["shift"], src)
                    break
            if best:
                break
            off += n
        if best:
            break
    if not best:
        out("QUALITY CHECK: no effect-free stretch to compare")
        return None
    g0, s0, src = best
    cx, cy, cw, ch = src["rect"]
    crop = f"crop={cw}:{ch}:{cx}:{cy}," if [cx, cy, cw, ch] != [0, 0, src["wh"][0], src["wh"][1]] else ""
    size = "1280:720" if preview else "1920:1080"
    ref = f"{crop}scale={size}:flags=lanczos," if (crop or preview or list(src["wh"]) != [1920, 1080]) else ""
    r = run(["ffmpeg", "-hide_banner", "-ss", f"{g0:.4f}", "-t", "0.5", "-i", str(outfile), "-ss", f"{max(0.0, s0):.4f}", "-t", "0.5",
             "-i", src["path"], "-filter_complex",
             f"[0:v]setpts=PTS-STARTPTS,format=yuv420p[a];[1:v]{ref}fps=60,setpts=PTS-STARTPTS,format=yuv420p[b];[a][b]ssim",
             "-f", "null", "-"], timeout=120)
    m = re.findall(r"SSIM Y:([\d.]+).*?All:([\d.]+)", r.stderr.decode(errors="replace"))
    if not m:
        out("QUALITY CHECK: could not measure SSIM")
        return None
    y, al = float(m[-1][0]), float(m[-1][1])
    out(f"QUALITY CHECK: SSIM {al:.4f} (luma {y:.4f}) output vs source on an effect-free stretch at {g0:.2f}s - "
        f"{'OK (>= 0.97)' if al >= 0.97 else 'BELOW 0.97'}")
    plan["ssim"] = round(al, 4)
    return al


# ======================================================================= ORCHESTRATION
GAME_DIR = {"valorant": "Valorant", "cs2": "CS2"}
LAST_PLAN = {}


def week_tag(now):
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


GAME_CODE = {"valorant": "VAL", "cs2": "CS2"}


def song_initials(title):
    """First letters of the song title's words (bracketed parts like '(feat. X)' dropped), max 5 characters."""
    words = re.findall(r"[^\W_]+", re.sub(r"[(\[].*?[)\]]", " ", title or ""))
    return "".join(w[0] for w in words).upper()[:5] or "SONG"


def montage_name(odir, plan, now):
    """<SONG INITIALS>_<GAME>_<APP VERSION>_<YYYY-MM-DD>, plus _2, _3 ... when that video already exists."""
    base = f"{song_initials(plan['song'].get('title') or Path(plan['song']['path']).stem)}_{GAME_CODE[plan['game']]}_" \
           f"{APP_VERSION}_{now.strftime('%Y-%m-%d')}"
    name, n = base, 1
    while (odir / (name + ".mp4")).exists():
        n += 1
        name = f"{base}_{n}"
    return name


def montage_videos(d, game):
    """Finished montages of a game in its output folder: V5.2 names (..._VAL_V5.2_2026-10-06[_2].mp4) and older
    ones (Valorant_2026-W40_<seed>.mp4), each with the date it was made."""
    vids = []
    if d.is_dir():
        new = re.compile(rf"_{GAME_CODE[game]}_[^_]+_(\d{{4}}-\d{{2}}-\d{{2}})(_\d+)?\.mp4$", re.I)
        old = re.compile(rf"^{GAME_DIR[game]}_(\d{{4}})-W(\d{{2}})_.*\.mp4$", re.I)
        for p in d.glob("*.mp4"):
            m, mo = new.search(p.name), old.match(p.name)
            try:
                if m:
                    vids.append((p, datetime.datetime.strptime(m.group(1), "%Y-%m-%d")))
                elif mo:
                    vids.append((p, datetime.datetime.fromisocalendar(int(mo.group(1)), int(mo.group(2)), 1)))
            except ValueError:
                pass
    return sorted(vids, key=lambda v: v[0].stat().st_mtime)


def weekly_existing(cfg, game, now=None):
    wk = week_tag(now or datetime.datetime.now())
    return [p for p, dt in montage_videos(Path(cfg["output_root"]) / GAME_DIR[game], game) if week_tag(dt) == wk]


WEEKLY_MIN_S = 60.0                      # V6.5.1: a weekly / Auto montage is never planned under 60 s while the library can reach it


def _ev_paths(e):
    return {e["path"]} | {x["path"] for x in e.get("srcs", []) if isinstance(x, dict) and x.get("path")}


def weekly_pick(events, cfg, target, style, now_ts=None, game=None):
    """V6.0 weekly / Auto clip pick: this week's (last 7 days) new clips come first; if they do not reach the minimum length, older
    UNUSED clips of the same game follow - best multikills first, then best singles - only as many as needed. V6.5.1: if the unused
    material cannot reach the 60 s minimum, previously used events are reused (best-scoring first among those whose last use is the oldest),
    never a clip of the game's previous montage and never a clip twice. Returns (events, notes)."""
    now_ts = now_ts or time.time()
    used = used_dates()
    unused = [e for e in events if _pkey(e["path"]) not in used]
    notes = []
    if len(unused) < len(events):
        notes.append(f"{len({e['path'] for e in events} - {e['path'] for e in unused})} clips already used in a montage are not reused")

    def mt(e):
        try:
            return os.path.getmtime(e["path"])
        except OSError:
            return 0.0
    new = [e for e in unused if now_ts - mt(e) <= 7 * 86400]
    old = sorted([e for e in unused if e not in new], key=lambda e: (bool(e.get("plain")), -e["score"]))
    optimal = target in (None, "", "optimal", 0)
    need = OPT_RANGE[0] + 8.0 if optimal else float(target) * 1.1
    rn = style if style in RECIPES else "hype"
    est = lambda lst: sum(take_estimate(e, 0.47, rn) for e in lst)
    pick = list(new)
    if est(pick) < need:
        for e in old:
            if est(pick) >= need:
                break
            pick.append(e)
    n_old = len(pick) - len(new)
    reused = []
    floor_need = WEEKLY_MIN_S * 1.1
    if est(pick) < floor_need:
        last = hist_list(USED_CLIPS, game)[-1:] if game else []
        prev = {_pkey(c) for h in last for c in h.get("clips", [])}              # the game's previous montage: never reused
        taken = set().union(*[_ev_paths(e) for e in pick]) if pick else set()
        cands = [e for e in events if e not in pick and _pkey(e["path"]) in used and not (_ev_paths(e) & taken)
                 and not any(_pkey(q) in prev for q in _ev_paths(e))]
        cands.sort(key=lambda e: (used.get(_pkey(e["path"]), ""), bool(e.get("plain")), -e["score"]))
        for e in cands:
            if est(pick) >= floor_need:
                break
            ps = _ev_paths(e)
            if ps & taken:
                continue
            pick.append(e)
            reused.append(e)
            taken |= ps
    notes.append(f"weekly pick: {len(new)} new clip event(s) this week + {n_old} older unused (best multikills first, then singles)"
                 + (f"; only ~{est(pick):.0f} s of unused material - the montage is shorter (nothing is padded)"
                    if not reused and est(pick) < (OPT_RANGE[0] if optimal else float(target)) - 0.5 else ""))
    if reused:
        notes.append(f"reused {len(reused)} previously used clip(s) to reach the {WEEKLY_MIN_S:.0f} s minimum")
    if est(pick) < WEEKLY_MIN_S:
        notes.append(f"the whole library only gives ~{est(pick):.0f} s ({len(pick) - len(reused)} unused + {len(reused)} reused usable event(s); "
                     f"the rest are clips of the previous montage or too short) - below the {WEEKLY_MIN_S:.0f} s minimum, so this is all there is; "
                     "nothing is padded")
    return pick, notes


def weekly_song_fit(song, an, sinfo, runners):
    """V6.5.1 (weekly / Auto): a chosen song whose section is under the 60 s minimum is replaced by the next best-ranked song that can."""
    sec = lambda a: float(a.get("dur") or 0) - float((a.get("beats") or [0])[0])
    if sec(an) >= WEEKLY_MIN_S:
        return song, an, sinfo, runners
    for s_, sc_ in runners:
        try:
            a2 = get_songmap(s_["path"], s_.get("csv_bpm"))
        except Exception:
            continue
        if sec(a2) >= WEEKLY_MIN_S:
            out(f"song {song.get('title') or Path(song['path']).stem} has only {sec(an):.0f} s (< {WEEKLY_MIN_S:.0f} s): using the next best-ranked "
                f"song {s_.get('title') or Path(s_['path']).stem} ({sec(a2):.0f} s)")
            return s_, a2, sc_, [r for r in runners if r[0] is not s_]
    out(f"song {song.get('title') or Path(song['path']).stem} has only {sec(an):.0f} s (< {WEEKLY_MIN_S:.0f} s) and no ranked song is longer")
    return song, an, sinfo, runners


# ======================================================================= V6.9: CS2 neighbour-clip pairing
# A fight recorded as a multikill can be split over 2-3 consecutive clips. After the selection and before the planner, the neighbours
# (by recording time) of a selected CS2 clip that shows a kill at its edge are added to the candidate pool as "pair partners". The
# planner's existing continuation / duplicate merge and frame-match stitch verification decide whether they are joined; a partner is
# never planned alone. Nothing here reads or decodes a clip: only file names, the cached clip records and the cached kill entries.
PAIR_EDGE_S = 3.0                       # a kill this close to either end of the clip makes it a candidate for a larger fight
PAIR_SINGLE_EDGE_S = 4.0                # a 1k clip: its single kill this close to either end
PAIR_MAX_GAP_S = 12.0                   # build_events() tests continuations inline (not reusable on a pair outside the selection)
PAIR_MAX_HOPS, PAIR_MAX_EXTRA = 2, 3    # per direction / per selected clip
PAIR_CAP_S = 2.0                        # hard cap for the whole step
PAIR_TEST_HOOK = [None]                 # tests only: called at the start of the step (inject an error / a delay)


def pair_clip_start(path):
    """Recording start from the file name ('Counter-strike 2 2025.02.08 - 19.48.57.15.DVR.mp4', 'Replay 2026-06-08 23-36-22.mov'; the
    '_1' / '_1_1' variants share the base time), or None. Never guessed: no mtime fallback."""
    m = _FN_TIME.search(Path(str(path)).name)
    if not m:
        return None
    try:
        return datetime.datetime(*[int(x) for x in m.groups()]).timestamp()
    except ValueError:
        return None


def pair_time_index(recs):
    """Sorted [(start, pkey, end, rec)] of the CS2 clips with a parsable name and a cached duration, plus the clips skipped."""
    idx, skipped = [], []
    for r in recs:
        if r.get("game", "cs2") != "cs2" or r.get("error") or not r.get("w"):
            continue
        dur = r.get("dur")
        anc = clip_anchor(r["path"], dur) if dur else None                 # V6.9.7: the name time is START for DVR names, END (save time) for OBS names
        if anc is None or not anc["provable"]:
            skipped.append(r["path"])
            continue
        idx.append((anc["start"], _pkey(r["path"]), anc["end"], r))
    idx.sort(key=lambda x: (x[0], x[1]))
    return idx, skipped


def pair_player_kills(rec, store, det, cfg):
    """None = no cached kill entry (never scanned); else the cached kill times of the player (no decoding, no scan)."""
    e = store.get(kills_key(rec, "cs2", det))
    if not e or e.get("error"):
        return None
    return [float(k["t"]) for k in analyse_clip_entry(rec, e, cfg, "cs2")["kills"]]


def pair_is_candidate(ts, dur):
    if not ts:
        return False
    if any(t <= PAIR_EDGE_S or t >= dur - PAIR_EDGE_S for t in ts):
        return True
    return len(ts) == 1 and (ts[0] <= PAIR_SINGLE_EDGE_S or ts[0] >= dur - PAIR_SINGLE_EDGE_S)


def pair_find(cfg, recs, selected, store, det, used, deadline=None, kills_fn=None):
    """Neighbour lookup for the selected CS2 clips. Returns {"partners": [(partner rec, selected clip path, gap s)], "checked": N,
    "lookups": L, "skip": {...}, "lines": [log lines]}. recs = cached clip records, selected = set of path keys."""
    kills_fn = kills_fn or (lambda r: pair_player_kills(r, store, det, cfg))
    idx, bad = pair_time_index(recs)
    pos = {k: i for i, (_, k, _, _) in enumerate(idx)}
    res = {"partners": [], "checked": 0, "lookups": 0, "lines": [], "skip": {"not scanned": 0, "used": 0, "no kills": 0, "no match": 0}}
    sk, lines = res["skip"], res["lines"]
    added = set()
    for key in sorted(selected):
        if deadline and time.monotonic() > deadline:
            raise TimeoutError("time cap reached")
        if key not in pos:
            if any(_pkey(r["path"]) == key and r.get("game", "cs2") == "cs2" for r in recs):
                sk["no match"] += 1                           # unparsable name / no duration: skipped, never guessed
            continue
        i0 = pos[key]
        t0, _, t1, rec = idx[i0]
        res["checked"] += 1
        ts = kills_fn(rec)
        if ts is None:
            sk["not scanned"] += 1
            continue
        if not pair_is_candidate(ts, t1 - t0):
            continue
        res["lookups"] += 1
        state = {-1: i0, 1: i0}                               # the far end of the chain in each direction
        alive = {-1: True, 1: True}
        n_extra = 0
        for _hop in range(PAIR_MAX_HOPS):
            for d in (-1, 1):
                if not alive[d] or n_extra >= PAIR_MAX_EXTRA:
                    continue
                cur = idx[state[d]]
                j = state[d] + d
                if not 0 <= j < len(idx):                         # no clip on that side at all
                    alive[d] = False
                    continue
                nb = idx[j]
                gap = (nb[0] - cur[2]) if d > 0 else (cur[0] - nb[2])
                nm = Path(nb[3]["path"]).name
                if gap > PAIR_MAX_GAP_S or nb[1] in selected or nb[1] in added:
                    alive[d] = False
                    sk["no match"] += 1
                    continue
                nk = kills_fn(nb[3])
                if nk is None:
                    alive[d] = False
                    sk["not scanned"] += 1
                    lines.append(f"neighbour not scanned: {nm}")
                    continue
                if nb[1] in used:
                    alive[d] = False
                    sk["used"] += 1
                    lines.append(f"neighbour already used: {nm}")
                    continue
                if not nk:
                    alive[d] = False
                    sk["no kills"] += 1
                    lines.append(f"neighbour has no kills of the player: {nm}")
                    continue
                added.add(nb[1])
                n_extra += 1
                state[d] = j
                res["partners"].append((nb[3], rec["path"], gap))
                lines.append(f"pair partner of {Path(rec['path']).name}: {nm} (gap {gap:.1f} s)")
    res["partners"].sort(key=lambda x: (pair_clip_start(x[0]["path"]) or 0.0, x[0]["path"]))       # V6.9.6: never in discovery order
    return res


def pair_summary(res):
    s = res["skip"]
    return (f"pairing: checked {res['checked']} clips, {len(res['partners'])} partner(s) added, {sum(s.values())} skipped "
            f"({s['not scanned']} not scanned / {s['used']} used / {s['no kills']} no kills / {s['no match']} no match; "
            f"neighbour window: gap <= {PAIR_MAX_GAP_S:.0f} s - the planner's continuation test is inline in build_events and not "
            "reusable outside the selection)")


def pairing_run(cfg, recs, selected_paths, quiet=False):
    """The whole neighbour step, guarded: any error / unparsable name / missing cache / more than PAIR_CAP_S = one 'pairing skipped:
    <reason>' line and None (the original selection stays). Runs in a helper thread so a hang cannot hold the plan up."""
    sel = {_pkey(p) for p in selected_paths}
    if not sel:
        return None
    box = {}

    def work():
        try:
            if PAIR_TEST_HOOK[0]:
                PAIR_TEST_HOOK[0]()
            det = Detector("cs2")
            store = load_kills_cache()
            box["res"] = pair_find(cfg, recs, sel, store, det, used_dates(), deadline=time.monotonic() + PAIR_CAP_S)
        except BaseException as ex:                          # noqa: BLE001 - nothing may escape the step
            box["err"] = f"{type(ex).__name__}: {ex}"
    log = LOGONLY if quiet else out
    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(PAIR_CAP_S)
    if th.is_alive():
        log(f"pairing skipped: timeout (more than {PAIR_CAP_S:.0f} s)")
        return None
    if "err" in box or "res" not in box:
        log(f"pairing skipped: {box.get('err', 'no result')}")
        return None
    res = box["res"]
    log(pair_summary(res))
    for l_ in res["lines"]:
        log(l_)
    return res


def pairing_result_line(res, plan):
    """After the planner: how many partners were stitched into a take, how many were rejected / left out."""
    if not res or not res["partners"]:
        return None
    in_takes = {_pkey(x["path"]) for t in plan["takes"] for x in t.get("srcs", [])} | {_pkey(t["path"]) for t in plan["takes"]}
    ok = [p for p, _, _ in res["partners"] if _pkey(p["path"]) in in_takes]
    return f"pairing result: {len(ok)} pair(s) stitched, {len(res['partners']) - len(ok)} rejected"


def pair_event_clips(e):
    return {_pkey(p) for p in _ev_paths(e)} | {_pkey(x["path"]) for x in e.get("parts", []) if x.get("path")}


def pairing_replace_events(res, pool, picked, game, cfg, seed):
    """Weekly / Auto pick: each picked event whose clip has partners is re-built from its clips + partners with the SAME build_events();
    the merged / stitched event replaces the single one in its slot (the pick's length and count are not recomputed). If the planner's
    stitch is rejected build_events() falls back to the single clip: the pick stays as it was."""
    by_clip = {}
    for p, of, _ in res["partners"]:
        by_clip.setdefault(_pkey(of), []).append(_pkey(p["path"]))
    from rapidfuzz import fuzz
    out_ev = list(picked)
    for i, e in enumerate(picked):
        mine = pair_event_clips(e)
        ps = {p for c in mine for p in by_clip.get(c, [])}
        if not ps:
            continue
        sub = sorted([it for it in pool if _pkey(it["rec"]["path"]) in mine | ps], key=lambda it: (pair_clip_start(it["rec"]["path"]) or 0.0, it["rec"]["path"]))
        if not any(_pkey(it["rec"]["path"]) in ps for it in sub):
            continue
        LEDGER_SUBCALL[0] = True
        try:
            evs2, _ = build_events(sub, game, cfg, random.Random(seed))
        finally:
            LEDGER_SUBCALL[0] = False
        # accepted: an event that uses a partner clip, was not a fallback after a rejected stitch, shows MORE kills than the single
        # event and still contains all of its kills (so it is that fight, not a separate event of the partner clip)
        have = lambda x: [_alnum((v or "").lower()) for v in x["victims"]]
        merged = [x for x in evs2 if {_pkey(q["path"]) for q in x.get("parts", [])} & ps
                  and "stitch rejected" not in x.get("stitch_note", "") and x["n"] > e["n"]
                  and all(any(fuzz.ratio(v, u) >= 80 for u in have(x)) for v in have(e) if v)]
        if merged:
            out_ev[i] = max(merged, key=lambda x: x["n"])
    return out_ev


def cmd_pairscan(args):
    """V6.9: python montage.py pairscan cs2 [--limit N]. Read-only: candidate pairs among ALL cached CS2 clips from the time index and the
    cached kill entries (no scan, no decoding, no cache or flag written; only pairscan_cs2.txt next to montage.py)."""
    cfg = load_config()
    det = Detector("cs2")
    store = load_kills_cache()
    clips = load_json(CLIPS_CACHE, {})
    recs = []
    for p in sorted(set(walk_files(clip_roots(cfg), VIDEO_EXT, MIN_VIDEO, cfg))):
        try:
            if tag_game(p, cfg)[0] != "cs2":
                continue
            rec = clips.get(file_key(p))
        except OSError:
            continue
        if rec and not rec.get("error"):
            recs.append(dict(rec, path=p, game="cs2"))
    lines, n_rows = pairscan_rows(cfg, recs, store, det, used_dates(), int(getattr(args, "limit", 0) or 30))
    text = "\n".join(lines)
    (HERE / "pairscan_cs2.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"({n_rows} neighbouring pairs; written to {HERE / 'pairscan_cs2.txt'}; nothing else was changed)")


def pair_group(recs, path, store, det, cfg, used):
    """The fight group of one CS2 clip as the pairing step sees it: the clip, then its neighbours in both directions (gap <= PAIR_MAX_GAP_S, an overlap is
    a negative gap), up to PAIR_MAX_HOPS per side and PAIR_MAX_EXTRA clips, each with the reason it is in or out. Reads caches only.
    Returns (members [(start, rec, kills|None, overlap_or_gap_to_previous)], notes)."""
    idx, _ = pair_time_index(recs)
    pos = {k: i for i, (_, k, _, _) in enumerate(idx)}
    key = _pkey(path)
    if key not in pos:
        return [], ["the clip is not in the time index (unparsable name, no cached duration or not a cached CS2 clip)"]
    notes, members, extra = [], [pos[key]], 0
    for d in (-1, 1):
        j = pos[key]
        for _hop in range(PAIR_MAX_HOPS):
            cur = idx[j]
            j += d
            if not 0 <= j < len(idx) or extra >= PAIR_MAX_EXTRA:
                break
            nb = idx[j]
            gap = (nb[0] - cur[2]) if d > 0 else (cur[0] - nb[2])
            nm = Path(nb[3]["path"]).name
            ks = pair_player_kills(nb[3], store, det, cfg)
            if gap > PAIR_MAX_GAP_S:
                notes.append(f"{nm}: not a partner (gap {gap:.1f} s > {PAIR_MAX_GAP_S:.0f} s)")
                break
            if ks is None:
                notes.append(f"{nm}: not scanned, the planner never uses it")
                break
            if nb[1] in used:
                notes.append(f"{nm}: already used in a montage")
                break
            if not ks:
                notes.append(f"{nm}: no kills of the player")
                break
            members.append(j)
            extra += 1
    members.sort(key=lambda i: (idx[i][0], idx[i][1]))
    rows = []
    for n_, i in enumerate(members):
        t0, k_, t1, r_ = idx[i]
        prev = idx[members[n_ - 1]] if n_ else None
        rows.append((t0, r_, pair_player_kills(r_, store, det, cfg), (t0 - prev[2]) if prev else None))
    return rows, notes


def cmd_grouporder(args):
    """V6.9.6: python montage.py grouporder cs2 "<clip name>". Read-only: the fight group of that clip (its pair partners), the start time of every clip,
    the overlap / gap to the previous one and the order the planner will use and why. Writes grouporder.txt next to montage.py, changes nothing."""
    cfg = load_config()
    det = Detector("cs2")
    store = load_kills_cache()
    clips = load_json(CLIPS_CACHE, {})
    recs = []
    for p_ in sorted(set(walk_files(clip_roots(cfg), VIDEO_EXT, MIN_VIDEO, cfg))):
        try:
            if tag_game(p_, cfg)[0] != "cs2":
                continue
            rec = clips.get(file_key(p_))
        except OSError:
            continue
        if rec and not rec.get("error"):
            recs.append(dict(rec, path=p_, game="cs2"))
    q = str(args.clip).lower()
    hit = [r_ for r_ in recs if Path(r_["path"]).name.lower() == q] or [r_ for r_ in recs if q in Path(r_["path"]).name.lower()]
    if not hit:
        lines = [f"grouporder: no cached CS2 clip matches '{args.clip}'"]
    else:
        lines = grouporder_lines(recs, hit[0], store, det, cfg, used_dates())
    text = "\n".join(lines)
    (HERE / "grouporder.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"(written to {HERE / 'grouporder.txt'}; nothing else was changed)")


def grouporder_lines(recs, rec, store, det, cfg, used):
    rows, notes = pair_group(recs, rec["path"], store, det, cfg, used)
    lines = [f"grouporder cs2: fight group of {Path(rec['path']).name}"]
    if not rows:
        return lines + ["  " + n_ for n_ in notes]
    base = rows[0][0]
    ties = {}
    for t0, r_, ks, _ in rows:
        ties.setdefault(t0, []).append(Path(r_["path"]).name)
    for n_, (t0, r_, ks, gap) in enumerate(rows, 1):
        rel = (f"{'overlaps the previous one by %.1f s' % -gap if gap < 0 else 'gap %.1f s after the previous one' % gap}" if gap is not None else "first")
        lines.append(f"  {n_}. {Path(r_['path']).name}  starts {datetime.datetime.fromtimestamp(t0):%H:%M:%S} (+{t0 - base:.1f} s), {float(r_.get('dur') or 0):.1f} s long, "
                     f"{len(ks) if ks is not None else '?'} kill(s), {rel}{'  <- the clip asked about' if _pkey(r_['path']) == _pkey(rec['path']) else ''}")
    lines.append("  order the planner will use: " + " -> ".join(str(i) for i in range(1, len(rows) + 1)) +
                 "  (chronological by the recording time in the clip names; the gap logic is not used because the clips overlap)")
    for t0, names in ties.items():
        if len(names) > 1:
            lines.append(f"  same base time {datetime.datetime.fromtimestamp(t0):%H:%M:%S}: {', '.join(names)} - their order is decided by the frame-match stitch verification at plan time, never by file-name sort")
    lines += ["  " + n_ for n_ in notes]
    return lines


def pairscan_rows(cfg, recs, store, det, used, limit=30):
    idx, bad = pair_time_index(recs)
    kc = {}

    def kills(r):
        if r["path"] not in kc:
            kc[r["path"]] = pair_player_kills(r, store, det, cfg)
        return kc[r["path"]]
    rows = []
    for a, b in zip(idx, idx[1:]):
        gap = b[0] - a[2]
        if gap > PAIR_MAX_GAP_S:
            continue
        ka, kb = kills(a[3]), kills(b[3])
        why = []
        if ka is None or kb is None:
            why.append("not scanned: " + ", ".join(Path(r["path"]).name for r, k in ((a[3], ka), (b[3], kb)) if k is None))
        else:
            if not ka or not kb:
                why.append("no kills of the player in " + ("both" if not ka and not kb else "the first" if not ka else "the second"))
            if not (pair_is_candidate(ka, a[2] - a[0]) or pair_is_candidate(kb, b[2] - b[0])):
                why.append("no kill within the edge window of either clip")
        used_b = [Path(r["path"]).name for _, k, _, r in (a, b) if k in used]
        if used_b:
            why.append("already used: " + ", ".join(used_b))
        rows.append((len(ka or []) + len(kb or []), a, b, gap, ka, kb, why))
    rows.sort(key=lambda r: (-r[0], r[1][0]))
    lines = [f"pairscan cs2: {len(idx)} clips in the time index ({len(bad)} with an unparsable name skipped), "
             f"{len(rows)} neighbouring pairs (gap <= {PAIR_MAX_GAP_S:.0f} s); top {min(limit, len(rows))} by combined kills"]
    for tot, a, b, gap, ka, kb, why in rows[:limit]:
        lines.append(f"{Path(a[3]['path']).name}  +  {Path(b[3]['path']).name}  gap {gap:.1f} s  kills {len(ka) if ka is not None else '?'} + "
                     f"{len(kb) if kb is not None else '?'}  -> " + ("qualifies" if not why else "no: " + "; ".join(why)))
    return lines, len(rows)


def make_plan(cfg, game, paths=None, song_path=None, target=None, style=None, seed=None, lock=None, placement=None, scan=True):
    """scan=False: plan from what is already scanned (the Manual status-line estimate runs exactly this, quietly)."""
    cfg = autodetect_dirs(cfg)
    if not load_dets(game).get(game):
        raise RuntimeError("OCR detector unavailable: Troubleshoot > Selfcheck (pip install rapidocr-onnxruntime)")
    tagged = [r for r in scan_clips(cfg) if r.get("game") == game]
    if not tagged:
        raise RuntimeError(f"No {game} clips found in {[d for d, _ in clip_dirs(cfg, game)]} "
                           f"(or clips are over {cfg['max_mb']} MB / {cfg['max_dur_s']} s). Check Settings > clip folders.")
    manual = paths is not None
    if paths is None and scan:
        paths = auto_scan_set(cfg, game)
        out(f"auto: {len(paths)} uncached clips to scan this run (last {cfg['auto_recent_days']} days + up to {cfg['auto_old_per_run']} older)")
    if paths and scan:
        run_scan(cfg, [game], paths)
    pair = None
    pool_paths = set(paths) if manual else None
    if game == "cs2" and manual and paths:                 # V6.9: neighbour clips of the ticked clips join the candidate pool
        pair = pairing_run(cfg, tagged, paths, quiet=not scan)
        if pair and pair["partners"]:
            pool_paths |= {p_["path"] for p_, _, _ in pair["partners"]}
    pool, st = game_pool(cfg, game, pool_paths)
    au = st["audio"]
    out(f"{game}: {st['tagged']} clips in included folders, {st['scanned']} scanned, {st['with_kills']} with detected kills; "
        f"{au['raw']} kills found, {au['no_shot']} without a heard gunshot (kept, audio is only a bonus), {au['death_lock']} dropped after my death, {au['kept']} usable")
    if not pool:
        raise RuntimeError(f"{st['tagged']} {game} clips, {st['scanned']} scanned, but 0 usable kills "
                           f"({au['raw']} found, {au['death_lock']} dropped after my death; rejected rows are listed above with their reasons). "
                           "Run Troubleshoot > Self-test detection to see the scores, or scan more clips.")
    seed = int(seed) if seed else random.randrange(1, 10 ** 6)
    if pair and pair["partners"]:                          # V6.9: the ticked clips are planned exactly as before; a partner only joins one of
        sel_ = {_pkey(p_) for p_ in paths}                 # their events when the planner's own merge + stitch accepts it (never its own take)
        events, notes = build_events([it for it in pool if _pkey(it["rec"]["path"]) in sel_], game, cfg, random.Random(seed))
        try:
            events = pairing_replace_events(pair, pool, events, game, cfg, seed)
        except Exception as ex:
            out(f"pairing skipped: {type(ex).__name__}: {ex}")
    else:
        events, notes = build_events(pool, game, cfg, random.Random(seed))
    if not events:
        raise RuntimeError("no usable kill events (utility kills are excluded)")
    if not manual:                                         # V6.0: weekly / Auto picks only unused clips, this week's first
        events, wk_notes = weekly_pick(events, cfg, cfg.get("length_s", "optimal") if target is None else target,
                                       cfg.get("style", "auto") if style is None else style, game=game)
        notes += wk_notes
        for n_ in wk_notes:
            out(n_)
        if game == "cs2":                                  # V6.9: neighbour clips of the picked CS2 clips (same slot, same count)
            sel_ = set().union(*[pair_event_clips(e) for e in events]) if events else set()
            pair = pairing_run(cfg, tagged, sel_, quiet=not scan)
            if pair and pair["partners"]:
                try:
                    events = pairing_replace_events(pair, pool, events, game, cfg, seed)
                except Exception as ex:
                    out(f"pairing skipped: {type(ex).__name__}: {ex}")
    songs, unmatched, csvname = song_pool(cfg)
    song, an, sinfo, runners = pick_song(cfg, game, songs, forced=song_path)
    if not manual and not song_path:
        song, an, sinfo, runners = weekly_song_fit(song, an, sinfo, runners)
    placement = placement or cfg.get("placement", "v5")
    if placement == "v4":
        an = analyse_song_v4(song["path"], song.get("csv_bpm"))
    if target is None:
        target = cfg.get("length_s", "optimal")
    if style is None:
        style = cfg.get("style", "auto")
    pool_ev, fixes, extended = list(events), [], set()
    for _try in range(6):                                  # never abort: drop the failing takes' events, re-plan the gap
        n2 = list(notes)
        plan = plan_montage(cfg, game, pool_ev, song, an, seed, style, target, hist_list(USED_CLIPS, game), n2, lock=lock,
                            placement=placement, manual=manual)
        bad = [b_ for b_ in verify_cutlist(plan) if "kill row" in b_]
        idx = {int(m.group(1)) for b_ in bad for m in [re.match(r"take (\d+):", b_)] if m}
        why_b = {plan["takes"][i - 1]["path"]: b_.split(":", 1)[1].strip() for b_ in bad for m in [re.match(r"take (\d+):", b_)]
                 if m and 0 < (i := int(m.group(1))) <= len(plan["takes"])}
        gone = {plan["takes"][i - 1]["path"] for i in idx if 0 < i <= len(plan["takes"])}
        if not gone:
            break
        if manual:                                         # V5.42B: first extend the take's window (no jump-cuts over its fight)
            ext = {p_ for p_ in gone if p_ not in extended}
            if ext:
                extended |= ext
                fixes += [f"cut list repair: {Path(p_).name} - {why_b.get(p_, 'kill row outside its footage')}; take window "
                          "extended (its whole fight shown, no jump-cut), re-planned" for p_ in ext]
                pool_ev = [dict(e, _no_cuts=True) if e["path"] in ext else e for e in pool_ev]
                continue
        fixes += [f"cut list repair: dropped {Path(p_).name} ({why_b.get(p_, 'kill row outside its footage')}"
                  f"{' even with its take window extended' if p_ in extended else ''}), re-planned with the next best events"
                  for p_ in gone]
        pool_ev = [e for e in pool_ev if e["path"] not in gone]
    plan["notes"] = list(plan["notes"]) + fixes
    for f_ in fixes:
        out(f_)
    if pair:
        pr_ = pairing_result_line(pair, plan)
        if pr_:
            (out if scan else LOGONLY)(pr_)
    try:                                                   # V6.9.7: the kill ledger of this run (never fails or changes a run)
        led_ = LAST_LEDGER[0]
        if led_ is not None and led_.rows:
            ledger_finalize(led_, events, pool_ev, plan)
            for l_ in ledger_report(led_):
                out(l_)
            if scan:
                ledger_save(led_, plan)
    except Exception as ex:                                # noqa: BLE001
        LOGONLY(f"kill ledger skipped: {type(ex).__name__}: {ex}")
    if plan["duration"] > plan["song"]["section_s"] + 1e-3:              # never render past the end of the music
        raise RuntimeError(f"plan is {plan['duration']:.1f} s but the song only has {plan['song']['section_s']:.1f} s from "
                           f"{ts(plan['song']['start_t'])} - not rendered")
    plan["song_score"] = sinfo
    if scan:
        LAST_PLAN[game] = plan
    return plan, fmt_plan(plan, events, sinfo, runners, unmatched, csvname)


def record_history(plan, title=None):
    game = plan["game"]
    now = datetime.datetime.now().strftime("%Y-%m-%d")
    uc, us = load_json(USED_CLIPS, {}), load_json(USED_SONGS, {})
    uc.setdefault(game, []).append({"date": now, "headline": plan["headline"], "recipe": plan["recipe"],
                                    "clips": sorted({t["path"] for t in plan["takes"]}), **({"title": title} if title else {})})
    us.setdefault(game, []).append({"date": now, "path": plan["song"]["path"]})
    uc[game], us[game] = uc[game][-12:], us[game][-12:]
    save_json(USED_CLIPS, uc)
    save_json(USED_SONGS, us)


def fmt_plan_audio(text, plan):
    """Plan text with the AUDIO line replaced after a fallback."""
    new = "AUDIO    " + AUDIO_TAGS["legacy"] + "   Auto audio failed, used Legacy V5.55: " + "; ".join(plan.get("audio_fallback", [])[:3])
    return re.sub(r"^AUDIO .*$", lambda m: new, text, count=1, flags=re.M)


def audio_guard(plan, outfile, cfg, redo):
    """V5.57: an Auto-audio render whose output is silent / has no audio stream is redone once on the Legacy V5.55 path.
    redo() re-renders the same plan (already switched to legacy). Returns True when the fallback ran."""
    if plan.get("audio_mode") != "auto" or not any(sd.get("audio") for tk in plan["takes"] for sd in tk["srcs"]):
        return False
    try:
        v = ebur128_lufs(str(outfile))
    except Exception:
        v = None
    if v is not None and v > SILENT_LUFS:
        return False
    why = "output has no audio" if v is None else f"output is silent ({v:.1f} LUFS)"
    for tk in plan["takes"]:
        for sd in tk["srcs"]:
            au = clip_audio_legacy({"path": sd["path"], "audio": sd["audio"]})
            sd["a_stream"], sd["a_note"], sd["lufs"] = au["stream"] or 0, au.get("note", ""), au["lufs"]
            sd["gain_db"], sd["lift_db"] = _game_gain(cfg, plan["song"].get("lufs"), au["lufs"])
    plan["audio_mode"] = "legacy"
    plan.setdefault("audio_fallback", []).append(why)
    out(f"Auto audio failed, used Legacy V5.55 ({why})")
    redo()
    return True


@with_job("render")
def run_job(game, mode="render", force=False, paths=None, song_path=None, target=None, style=None,
            seed=None, maxq=None, weekly=False, lock=None, encoder=None, outfile=None, placement=None, effects=True):
    """mode: dry | preview | render. weekly=True is Auto. Always prints a plan or a plain-language reason."""
    try:
        cfg = load_config()
        if maxq is None:
            maxq = cfg.get("quality") == "max"
        now = datetime.datetime.now()
        if weekly and mode == "render" and not force:
            ex = weekly_existing(cfg, game, now)
            if ex:
                out(f"{game}: this week's montage already exists ({ex[0].name}). Use 'Force new' to make another.")
                return None
        out(f"== {game} / {mode} ==")
        plan, text = make_plan(cfg, game, paths, song_path, target, style, seed, lock, placement)
        out(text)
        plans = DATA / "plans"
        plans.mkdir(parents=True, exist_ok=True)
        base = f"{GAME_DIR[game]}_{week_tag(now)}_{plan['seed']}"
        if mode == "dry":
            (plans / (base + ".dry.txt")).write_text(text, encoding="utf-8")
            save_json(plans / (base + ".dry.json"), plan)
            out(f"(dry plan only - nothing rendered; seed {plan['seed']}; saved to {plans})")
            return plan
        odir = Path(cfg["output_root"]) / GAME_DIR[game]
        if mode == "preview":
            pv = render_plan(plan, odir / f"preview_{GAME_DIR[game]}.mp4", cfg, maxq, True, encoder)
            quality_check(slice_plan(plan), pv, cfg, preview=True)
            return pv
        odir.mkdir(parents=True, exist_ok=True)
        outfile = Path(outfile) if outfile else odir / (montage_name(odir, plan, now) + ".mp4")
        render_plan(plan, outfile, cfg, maxq, False, encoder, effects)
        try:
            if audio_guard(plan, outfile, cfg, lambda: render_plan(plan, outfile, cfg, maxq, False, encoder, effects)):
                text = fmt_plan_audio(text, plan)
        except Exception as ex:
            out(f"Audio check skipped: {ex}")
        try:
            quality_check(plan, outfile, cfg)
        except Exception as ex:
            out(f"quality check skipped: {ex}")
        logs = outfile.parent / "logs"                     # only the video stays in the output folder
        logs.mkdir(parents=True, exist_ok=True)
        (logs / (outfile.stem + ".plan.txt")).write_text(text, encoding="utf-8")
        save_json(logs / (outfile.stem + ".plan.json"), plan)
        record_history(plan, outfile.stem)
        try:                                               # V6.0: flagged used only now, after the render succeeded
            mark_used({t["path"] for t in plan["takes"]} | {x["path"] for t in plan["takes"] for x in t.get("srcs", [])}, title=outfile.stem)
        except Exception as ex:
            out(f"Used flags not saved: {ex}")
        if cfg.get("sync_report", True):
            try:
                sync_report(plan, outfile, cfg)
            except Exception as ex:
                out(f"sync report skipped: {ex}")
        return outfile
    except RuntimeError as ex:
        out(f"CANNOT {mode.upper()} ({game}): {ex}")
    except Exception as ex:
        out(f"CANNOT {mode.upper()} ({game}): unexpected error: {ex}\n{traceback.format_exc()}")
    return None


# ------------------------------------------------------------------ commands
def ask(prompt, default=""):
    s = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip().strip('"')
    return s or default


def cmd_setup(args):
    DATA.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    cfg["playlist_dir"] = ask("Folder where you will drop the Exportify CSV", cfg["playlist_dir"])
    Path(cfg["playlist_dir"]).mkdir(parents=True, exist_ok=True)
    while True:
        m = ask("Path of your MP3 folder", cfg["mp3_dir"])
        if m and os.path.isdir(m):
            cfg["mp3_dir"] = m
            break
        out("  That folder does not exist. Try again (or Ctrl+C to skip and set it later by re-running setup).")
    save_json(CONFIG_PATH, cfg)
    out(f"Saved {CONFIG_PATH}")
    out("Next: python montage.py selfcheck")


def cmd_selfcheck(args):
    ok = True
    out("== binaries ==")
    for tool in ("ffmpeg", "ffprobe"):
        p = shutil.which(tool)
        if p:
            v = run([tool, "-version"]).stdout.decode(errors="replace").splitlines()[0]
            out(f"  OK   {tool}: {v}  ({p})")
        else:
            ok = False
            out(f"  MISSING {tool}")
    if not shutil.which("ffmpeg"):
        out("\n  Get ffmpeg without admin (pick one):")
        out("   A) winget install --id Gyan.FFmpeg -e --scope user   (then open a new terminal)")
        out("   B) Download 'ffmpeg-release-essentials' from https://www.gyan.dev/ffmpeg/builds/ ,")
        out("      extract it, and copy ffmpeg.exe + ffprobe.exe from its bin folder into")
        out(f"      {DATA / 'bin'}   (this script adds that folder to PATH itself).")
    else:
        out("== encoders / decoders ==")
        enc = run(["ffmpeg", "-hide_banner", "-encoders"]).stdout.decode(errors="replace")
        for e in ("h264_nvenc", "libx264", "aac"):
            has = e in enc
            out(f"  {'OK  ' if has else 'MISS'} encoder {e}")
            if e == "libx264" and not has:
                ok = False
        hw = run(["ffmpeg", "-hide_banner", "-hwaccels"]).stdout.decode(errors="replace")
        out(f"  {'OK  ' if 'cuda' in hw else 'MISS'} hwaccel cuda (NVDEC decode)")
        if "h264_nvenc" in enc:
            r = run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1280x720:r=30:d=0.2",
                     "-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "18",
                     "-f", "null", "-"])
            if r.returncode == 0:
                out("  OK   NVENC test encode (p7/hq/vbr/cq18)")
            else:
                out("  FAIL NVENC test encode: " + r.stderr.decode(errors="replace").strip()[-300:])
                out("       (update the NVIDIA driver; --max-quality will use libx264 instead)")
    out("== python ==")
    out(f"  Python {sys.version.split()[0]}")
    pk = [("numpy", "numpy"), ("cv2", "opencv-python"), ("librosa", "librosa"), ("soundfile", "soundfile"),
          ("scipy", "scipy"), ("mutagen", "mutagen"), ("rapidfuzz", "rapidfuzz"), ("rapidocr_onnxruntime", "rapidocr-onnxruntime"),
          ("tkinter", None)]
    missing = []
    for mod, pipname in pk:
        try:
            __import__(mod)
            out(f"  OK   {mod}")
        except Exception as ex:
            ok = False
            out(f"  MISSING {mod} ({type(ex).__name__})")
            if pipname:
                missing.append(pipname)
            else:
                out("       tkinter ships with python.org installer: re-run it, Modify, tick 'tcl/tk and IDLE'.")
    if missing:
        out(f"\n  Install: python -m pip install --user {' '.join(missing)}")
    else:
        out("== OCR kill detection ==")
        try:
            f = ocr_synthetic_test(verbose=False)
            out("  OK   RapidOCR reads generated killfeed rows: 1 KILL / 1 DEATH as expected" if not f else "  FAIL " + "; ".join(f))
            ok = ok and not f
        except Exception as ex:
            ok = False
            out(f"  FAIL RapidOCR: {ex}")
    out("\nSELFCHECK " + ("PASSED" if ok else "has problems (see above)"))


def human(n):
    return f"{n / 1e9:.1f} GB"


def cmd_inventory(args):
    cfg = load_config()
    if not shutil.which("ffprobe"):
        out("ffprobe not found - run selfcheck first.")
        return
    t0 = time.time()
    recs = scan_clips(cfg, args.rescan)
    out(f"\n== CLIPS ({len(recs)}) ==")
    by = {}
    for r in recs:
        by.setdefault(r["game"] or "UNKNOWN", []).append(r)
    for g in sorted(by):
        rs = by[g]
        tot = sum(os.path.getsize(r["path"]) for r in rs if os.path.exists(r["path"]))
        cnt = lambda key: ", ".join(f"{k}x{v}" for k, v in sorted(
            {x: sum(1 for r in rs if str(r.get(key)) == x) for x in {str(r.get(key)) for r in rs}}.items()))
        res = {}
        for r in rs:
            res[f"{r.get('w')}x{r.get('h')}"] = res.get(f"{r.get('w')}x{r.get('h')}", 0) + 1
        bars = sum(1 for r in rs if r.get("bars"))
        bad = [r for r in rs if r.get("error")]
        src = {}
        for r in rs:
            src[r["game_src"]] = src.get(r["game_src"], 0) + 1
        out(f"\n[{g.upper()}] {len(rs)} clips, {human(tot)}  (tagged by: {src})")
        out(f"  codecs : {cnt('codec')}")
        out(f"  res    : {', '.join(f'{k}x{v}' for k, v in sorted(res.items()))}")
        out(f"  fps    : {cnt('fps')}")
        out(f"  bar-fix needed: {bars}   unreadable: {len(bad)}")
        for r in bad[:10]:
            out(f"     UNREADABLE {r['path']}: {r.get('error')}")
        if g == "UNKNOWN":
            out("  -> these will use HUD detection in Stage 1, or: montage.py tag <folder> <valorant|cs2>")
    if args.list:
        out("\n== CLIP LIST ==")
        for r in sorted(recs, key=lambda r: r["path"].lower()):
            out(f"  [{r['game'] or '?':8}] {r.get('codec')} {r.get('w')}x{r.get('h')}@{r.get('fps')} "
                f"{r.get('dur', 0):.0f}s {'BARS' if r.get('bars') else ''}  {r['path']}")

    out("\n== AUDIO / PLAYLIST ==")
    audio = scan_audio(cfg, args.rescan)
    out(f"  audio files found: {len(audio)}")
    csv_path, rows, col = read_playlist(cfg)
    if not csv_path:
        out(f"  no Exportify CSV in {cfg['playlist_dir']} yet (drop one there).")
    else:
        out(f"  newest CSV: {csv_path.name}  columns used: { {k: v for k, v in col.items()} }")
        try:
            matched, unmatched = match_playlist(rows, audio, cfg)
        except ImportError:
            out("  rapidfuzz missing - run selfcheck.")
            return
        out(f"  playlist tracks: {len(rows)}   matched to a file: {len(matched)}   unmatched: {len(unmatched)}")
        for r, a, s in matched[:15]:
            out(f"     OK {s:3d}  {r['artist']} - {r['title']}  <-  {Path(a['path']).name}")
        if len(matched) > 15:
            out(f"     ... {len(matched) - 15} more matched")
        out(f"  UNMATCHED ({len(unmatched)}): no file in your MP3 folder for:")
        for r in unmatched:
            out(f"     {r['artist']} - {r['title']}")
    out(f"\ninventory done in {time.time() - t0:.0f}s. Nothing in your source folders was touched.")


def cmd_tag(args):
    cfg = load_config()
    ov = cfg.setdefault("game_overrides", {})
    if args.game == "auto":
        ov.pop(args.path, None)
    else:
        ov[args.path] = args.game
    save_json(CONFIG_PATH, cfg)
    out(f"override {args.path} -> {args.game}")


# ============================================================================ GUI
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except Exception:          # selfcheck reports this; CLI still works
    tk = None

PIP_PKGS = [("numpy", "numpy"), ("cv2", "opencv-python"), ("librosa", "librosa"), ("soundfile", "soundfile"),
            ("scipy", "scipy"), ("mutagen", "mutagen"), ("rapidfuzz", "rapidfuzz"), ("rapidocr_onnxruntime", "rapidocr-onnxruntime")]


def missing_packages():
    miss = []
    for mod, pipname in PIP_PKGS:
        try:
            with pstage(f"  import {mod}"):
                __import__(mod)
        except Exception:
            miss.append(pipname)
    return miss


def stop_all():
    CANCEL.set()
    for p in list(PROCS):
        try:
            p.kill()
        except Exception:
            pass


def to_photo(img, maxw=1280, maxh=720):
    import cv2
    h, w = img.shape[:2]
    s = min(maxw / w, maxh / h)
    if s != 1:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".png", img)
    return tk.PhotoImage(data=base64.b64encode(buf.tobytes())), s


def grab_norm_frame(path, t, cfg):
    import numpy as np
    rec = analyse_clip(path, load_json(CLIPS_CACHE, {}), False, cfg.get("bar"))[1]
    cx, cy, cw, ch = content_rect(rec, cfg)
    r = run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-vf",
             f"crop={cw}:{ch}:{cx}:{cy},scale={NORM_W}:{NORM_H}:flags=bicubic,format=bgr24", "-f", "rawvideo", "-"], timeout=60)
    n = NORM_W * NORM_H * 3
    if len(r.stdout) < n:
        raise RuntimeError("could not read that frame")
    return np.frombuffer(r.stdout[:n], np.uint8).reshape(NORM_H, NORM_W, 3).copy(), rec


class CalibDialog:
    """OPTIONAL: pick a clip (or screenshot), drag one box around the whole killfeed area. OCR then shows the rows it reads."""
    def __init__(self, app):
        self.app, self.cfg = app, load_config()
        self.win = app.reg(tk.Toplevel(app.root), "window")
        self.win.title("Killfeed region (optional - defaults to top-right)")
        self.win.configure(bg=app.pal["bg"])
        top = ttk.Frame(self.win)
        top.pack(fill="x", padx=6, pady=4)
        self.game = tk.StringVar(value="valorant")
        cb = ttk.Combobox(top, textvariable=self.game, values=list(GAMES), width=10, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: (self.show_game(), self.show_region()))
        ttk.Button(top, text="Open clip...", command=self.open_clip).pack(side="left", padx=4)
        ttk.Button(top, text="Open screenshot...", command=self.open_shot).pack(side="left")
        ttk.Button(top, text="Test OCR on this frame", command=self.test).pack(side="left", padx=8)
        ttk.Button(top, text="Reset to default", command=self.use_default).pack(side="left")
        self.save = ttk.Button(top, text="Save region", command=self.do_save, state="disabled")
        self.save.pack(side="right")
        self.big = tk.StringVar()                                    # V6.7.6: the game this box will be saved for, in large text
        ttk.Label(self.win, textvariable=self.big, font=("Segoe UI", F(22), "bold")).pack(anchor="w", padx=6)
        self.show_game()
        self.scale = ttk.Scale(self.win, from_=0, to=1, command=lambda v: None)
        self.scale.bind("<ButtonRelease-1>", lambda e: self.load_frame())
        self.msg = tk.StringVar(value="Open a clip (scrub to a moment with killfeed rows) or a screenshot, then drag a box around the "
                                      "WHOLE killfeed area. Yellow = current region.")
        ttk.Label(self.win, textvariable=self.msg, font=("Segoe UI", F(10), "bold"), wraplength=1260).pack(anchor="w", padx=6)
        self.cv = app.reg(tk.Canvas(self.win, width=1280, height=720, bg="#222", highlightthickness=1, highlightbackground="#888"), "fixed")
        self.cv.pack(padx=6, pady=6)
        self.cv.bind("<ButtonPress-1>", self.press)
        self.cv.bind("<B1-Motion>", self.drag)
        self.cv.bind("<ButtonRelease-1>", self.release)
        self.base, self.path, self.dur, self.region, self.rect_id, self.p0, self.view = None, None, 0, None, None, None, None

    def show_game(self):
        self.big.set(f"Killfeed region for: {self.game.get().upper()}")

    def open_clip(self):
        p = filedialog.askopenfilename(initialdir=self.cfg["clip_root"], filetypes=[("video", "*.mov *.mp4 *.mkv")])
        if not p:
            return
        try:
            g = tag_game(p, self.cfg)[0]                             # V6.7.6: a clip of the other game switches the selection (shown large)
            if g in GAMES and g != self.game.get():
                self.game.set(g)
                self.show_game()
            self.path = p
            self.dur = probe_video(p)["dur"]
            self.scale.config(to=max(1.0, self.dur))
            self.scale.pack(fill="x", padx=6, before=self.cv)
            self.scale.set(self.dur / 2)
            self.load_frame()
        except Exception as ex:
            messagebox.showerror("Killfeed region", str(ex))

    def load_frame(self):
        try:
            self.base, _ = grab_norm_frame(self.path, float(self.scale.get()), self.cfg)
            self.show_region()
        except Exception as ex:
            self.msg.set(str(ex))

    def open_shot(self):
        p = filedialog.askopenfilename(initialdir=str(HERE.parent), filetypes=[("image", "*.png *.jpg *.jpeg *.bmp")])
        if p:
            self.scale.pack_forget()
            self.base = norm_image(read_img(p), self.cfg)
            self.show_region()

    def show_region(self, img=None):
        if self.base is None:
            return
        self.photo, s = to_photo(self.base if img is None else img)
        self.view = {"s": s}
        self.cv.delete("all")
        self.cv.create_image(0, 0, anchor="nw", image=self.photo)
        x0, y0, x1, y1 = Detector(self.game.get()).d["region"]
        self.cv.create_rectangle(x0 * NORM_W * s, y0 * NORM_H * s, x1 * NORM_W * s, y1 * NORM_H * s, outline="#ff0", width=2, dash=(4, 2))
        self.rect_id = None

    def press(self, e):
        self.p0 = (e.x, e.y)
        if self.rect_id:
            self.cv.delete(self.rect_id)
        self.rect_id = self.cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#0f0", width=2)

    def drag(self, e):
        if self.p0 and self.rect_id:
            self.cv.coords(self.rect_id, self.p0[0], self.p0[1], e.x, e.y)

    def release(self, e):
        if not self.p0 or self.base is None or not self.view:
            return
        s = self.view["s"]
        x0, x1 = sorted((self.p0[0], e.x))
        y0, y1 = sorted((self.p0[1], e.y))
        self.p0 = None
        if x1 - x0 < 10 or y1 - y0 < 10:
            return
        self.region = (int(x0 / s), int(y0 / s), int((x1 - x0) / s), int((y1 - y0) / s))
        self.save.config(state="normal")
        self.msg.set(f"Killfeed box {self.region}. Press Save region (it is tested with OCR right away).")

    def test(self):
        if self.base is None:
            messagebox.showinfo("Killfeed region", "Open a clip or screenshot first.")
            return
        g = self.game.get()
        det = Detector(g)
        rows, _, _ = test_frame(g, self.base)
        crop = draw_rows(det.crop_norm(self.base).copy(), rows)
        out(f"{g}: OCR found {len(rows)} rows in the killfeed region")
        for r in rows:
            out("   " + row_desc(r))
        img = self.base.copy()
        x0, y0 = int(det.d["region"][0] * NORM_W), int(det.d["region"][1] * NORM_H)
        img[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]] = crop
        self.show_region(img)
        self.msg.set(f"{len(rows)} rows read, {sum(1 for r in rows if any(v == 'kill' for v, _ in classify_row(r)))} FIREAXE kill row(s) - details in the log.")

    def use_default(self):
        if not messagebox.askyesno("Killfeed region", f"Reset the {self.game.get().upper()} killfeed region to the default?"):
            return
        g = self.game.get()
        reg = apply_default_region(g)                                # V6.8: the saved default when there is one, else the built-in default
        out(f"{g}: {'saved' if reg else 'built-in'} default killfeed region {reg or DEFAULT_REGION[g]}")
        self.show_region()
        self.app.refresh_auto()

    def do_save(self):
        try:
            if not self.region:
                return
            if not messagebox.askyesno("Killfeed region", f"Save this box as the {self.game.get().upper()} killfeed region?"):
                return                                               # V6.7.6: nothing is saved without a Yes
            res = do_calibrate(self.game.get(), self.base, self.region)
            self.show_region()
            messagebox.showinfo("Killfeed region", f"{self.game.get()} region saved. OCR read {res['rows']} rows, "
                                                   f"{res['hits']} FIREAXE kill row(s) on this frame (details in the log).")
            self.app.refresh_auto()
        except Exception as ex:
            messagebox.showerror("Killfeed region", str(ex))


# ------------------------------------------------------------ V5.55 GUI helpers (used flags, random pick)
def _pkey(p):
    return os.path.normcase(os.path.normpath(str(p)))


def used_dates():
    """{clip path key: date (YYYY-MM-DD) of the last montage that used it}: the flags the GUI writes plus the older history."""
    d = {}
    for game_hist in load_json(USED_CLIPS, {}).values():
        for h in game_hist if isinstance(game_hist, list) else []:
            for c in h.get("clips", []):
                d[_pkey(c)] = max(d.get(_pkey(c), ""), h.get("date", ""))
    for c, dt in load_json(USED_FLAGS, {}).items():
        d[c] = max(d.get(c, ""), dt)
    return d


HAND_LABEL = "flagged by hand"


def mark_used(paths, date=None, title=None):
    """A montage rendered successfully: every clip in it is 'used' as of that date. V6.7.4: the montage title (output file name without
    extension) is stored with the flag in used_titles.json; no title = flagged by hand."""
    date = date or datetime.datetime.now().strftime("%Y-%m-%d")
    flags = load_json(USED_FLAGS, {})
    titles = load_json(USED_TITLES, {})
    for p_ in paths:
        flags[_pkey(p_)] = date
        titles[_pkey(p_)] = {"date": date, "title": title or ""}
    save_json(USED_FLAGS, flags)
    save_json(USED_TITLES, titles)


def used_info():
    """V6.7.4: {clip path key: (date, label)} for the Manual list's Used column. label = the title of the montage that set the date
    (stored with the flag, else found in the montage history), 'flagged by hand' for a hand flag, else the date itself."""
    dates = used_dates()
    titles = load_json(USED_TITLES, {})
    hist = {}
    for game_hist in load_json(USED_CLIPS, {}).values():
        for h in game_hist if isinstance(game_hist, list) else []:
            if h.get("title"):
                for c in h.get("clips", []):
                    hist[(_pkey(c), h.get("date", ""))] = h["title"]
    info = {}
    for k, d in dates.items():
        t = titles.get(k) if isinstance(titles.get(k), dict) else None
        if t and t.get("date") == d:
            label = t.get("title") or HAND_LABEL
        else:
            label = hist.get((k, d)) or d
        info[k] = (d, label)
    return info


def backup_used_flags():
    """V6.5.1: a dated copy of the used-flags file (and of the montage history that also flags clips) next to it; returns the flags copy's name."""
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dst = None
    for src, tag in ((USED_FLAGS, "used_flags"), (USED_CLIPS, "used_clips"), (USED_TITLES, "used_titles")):
        d_ = src.with_name(f"{tag}_backup_{stamp}.json")
        if src.exists():
            shutil.copy2(src, d_)
        elif tag == "used_flags":
            save_json(d_, {})
        if tag == "used_flags":
            dst = d_
    return dst.name


def unflag_clips(paths=None):
    """V6.5.1: remove the used flag of the given clips (None = every clip), also from the montage history that would flag them again.
    Returns the number of clips that were flagged and are not any more."""
    keys = set(used_dates())
    if paths is not None:
        keys &= {_pkey(p_) for p_ in paths}
    flags = load_json(USED_FLAGS, {})
    save_json(USED_FLAGS, {k: v for k, v in flags.items() if k not in keys})
    if USED_TITLES.exists():
        save_json(USED_TITLES, {k: v for k, v in load_json(USED_TITLES, {}).items() if k not in keys})
    hist = load_json(USED_CLIPS, {})
    for lst in hist.values():
        for h in lst if isinstance(lst, list) else []:
            h["clips"] = [c for c in h.get("clips", []) if _pkey(c) not in keys]
    save_json(USED_CLIPS, hist)
    return len(keys)


def _shell_trash(path):
    """V6.7.4: Windows Recycle Bin through the shell API (SHFileOperationW with FOF_ALLOWUNDO: never a permanent delete)."""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _pack_ = 1 if ctypes.sizeof(ctypes.c_void_p) == 4 else 8
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0"                 # a second NUL ends the (single-entry) list
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0 or op.fAnyOperationsAborted:
        raise OSError(f"the Recycle Bin refused the file (shell error 0x{rc:X})")


def trash_file(path):
    """V6.7.4: move a file to the Recycle Bin (send2trash if importable, else the Windows shell API). Raises on failure; never deletes
    permanently."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"file not found: {path}")
    try:
        from send2trash import send2trash
    except ImportError:
        send2trash = None
    if send2trash is not None:
        send2trash(os.path.abspath(path))
    elif os.name == "nt":
        _shell_trash(path)
    else:
        raise OSError("no Recycle Bin available here (install send2trash)")
    if os.path.exists(path):
        raise OSError("the file is still there after the move")


def forget_clip(path, fk=None):
    """V6.7.4: drop everything stored about a clip file that is gone: its scan-cache entries (kills, clip record), its used flag and title.
    fk = file_key(path) taken BEFORE the file was moved (the key holds its size and time)."""
    if fk:
        load_kills_cache().drop_file(fk)
    cc = load_json(CLIPS_CACHE, {})
    keep = {k: v for k, v in cc.items() if k != fk and not (isinstance(v, dict) and v.get("path") and _pkey(v["path"]) == _pkey(path))}
    if len(keep) != len(cc):
        save_json(CLIPS_CACHE, keep)
    unflag_clips([path])


def default_song_map(dur=180.0, bpm=120.0):
    """A plain song map (steady beat, 4-beat bars, 4-bar phrases) for Optimal sizing when no song is chosen."""
    import numpy as np
    bd = 60.0 / bpm
    n = int(dur / bd)
    return {"beats": [i * bd for i in range(n)], "dur": dur, "down": list(range(0, n, 4)), "phrase4": list(range(0, n, 16)),
            "sections": [], "drops": [], "drop": None, "level": [0] * n, "energy": [0.5] * n, "bpm": bpm}


def random_pick(cands, an=None, style="auto", rng=None):
    """V5.55 Random pick: shuffle the candidate clips (dicts with path + ks = kill times), then ask the existing Optimal function
    (optimal_fit) which of them fit an Optimal-length montage for this song map and style. Returns (paths, fit)."""
    rng = rng or random.Random()
    an = an or default_song_map()
    pool = [{"path": c["path"], "times": list(c["ks"]), "rows": list(c["ks"]), "score": rng.random()} for c in cands if c.get("ks")]
    if not pool:
        return [], None
    fit = optimal_fit(pool, an, style)
    return [e["path"] for e in fit["clips"]], fit


# V5.57: accent colour (main, dark = selection / pressed, darkest, OpenCV hue 0-179) x base (grey | black)
ACCENT_DEF = {"lime": ("#a3e635", "#4c7a14", "#2c3d0c", 42), "yellow": ("#facc15", "#8a6d0a", "#4a3a05", 24),
              "orange": ("#fb923c", "#9a4f12", "#4f2808", 14), "red": ("#f87171", "#a62b2b", "#561515", 0),
              "pink": ("#f472b6", "#a3306f", "#521838", 164), "purple": ("#a78bfa", "#5b3fb0", "#2e2060", 129)}
BASE_DEF = {"grey": dict(bg="#343434", fg="#f2f2f2", field="#454545", head="#3d3d3d", dim="#b4b4b4", border="#5c5c5c", btn="#454545",
                         btn_act="#505050"),
            "black": dict(bg="#000000", fg="#f2f2f2", field="#1b1b1b", head="#141414", dim="#a8a8a8", border="#3a3a3a", btn="#1b1b1b",
                          btn_act="#2a2a2a")}


def _lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def contrast(a, b):
    """WCAG contrast ratio of two #rrggbb colours (4.5 = readable text)."""
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def make_palette(accent="lime", base="grey"):
    acc, dark, _, _ = ACCENT_DEF.get(accent, ACCENT_DEF["lime"])
    pal = dict(BASE_DEF.get(base, BASE_DEF["grey"]))
    pal.update(acc=acc, sel=dark, sel_fg="#ffffff", check=acc, acc_fg="#10200a" if contrast(acc, "#10200a") >= contrast(acc, "#ffffff") else "#ffffff")
    return pal


PAL = make_palette("lime", "grey")                  # the default theme (grey + lime)


UI_SCALE = [1.0]


def F(size):
    """Font size scaled by Settings > UI scale."""
    return max(7, int(round(size * UI_SCALE[0])))


SIMPLE_THEME = os.environ.get("MONTAGE_SIMPLE_THEME") == "1"      # V6.2: A/B test switch: built-in clam theme instead of Sun Valley
SV_THEME = [False]                                    # True when the Sun Valley ttk theme (sv-ttk) is active
THEME_VER = "t4"


def _neutral(v, base):
    """Sun Valley dark neutral grey level -> the grey (lifted) or black base."""
    if base == "black":
        return max(0, min(255, int(round((v - 28) * 250 / 222)))) if v > 28 else 0
    return max(0, min(255, int(round(52 + (v - 28) * (250 - 52) / (250 - 28))) if v > 28 else 52 - (28 - v) // 2))


def _tint_hex(m, accent="lime", base="grey"):
    """Sun Valley dark -> the chosen base + accent (colours in the theme's tcl files): neutrals are re-levelled, blues turn accent."""
    h = m.group(1)
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    if max(r, g, b) - min(r, g, b) < 12:
        v = _neutral(r, base)
        return f'"#{v:02x}{v:02x}{v:02x}"'
    acc, dark, darkest, _ = ACCENT_DEF[accent]
    return {"57c8ff": f'"{acc}"', "2f60d8": f'"{dark}"', "25536a": f'"{darkest}"'}.get(h.lower(), m.group(0))


def lime_theme_dir(accent="lime", base="grey"):
    """A copy of the sv-ttk package whose dark theme has the chosen base (grey | black) and accent colour (checkboxes, sliders, tabs,
    Accent buttons): the sprite sheet is recoloured once per combination (cached in montage_data\\theme_cache) and the colour
    constants of dark.tcl are replaced."""
    import sv_ttk
    import cv2
    import numpy as np
    src = Path(sv_ttk.__file__).parent
    dst = DATA / "theme_cache" / f"sv_{THEME_VER}_{accent}_{base}"
    if (dst / "ok").exists():
        return dst
    tmp = DATA / "theme_cache" / f"tmp_{os.getpid()}_{accent}_{base}"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.py", "py.typed"))
    im = cv2.imread(str(tmp / "theme" / "spritesheet_dark.png"), cv2.IMREAD_UNCHANGED)
    bgr, alpha = im[:, :, :3].astype(np.float32), im[:, :, 3:]
    mx, mn = bgr.max(axis=2), bgr.min(axis=2)
    grey = (mx - mn) < 12
    v0 = bgr[:, :, 0]
    if base == "black":
        lifted = np.where(v0 > 28, (v0 - 28) * 250 / 222, 0)
    else:
        lifted = np.where(v0 > 28, 52 + (v0 - 28) * (250 - 52) / (250 - 28), 52 - (28 - v0) / 2)
    out_ = bgr.copy()
    out_[grey] = lifted[grey][:, None]
    hsv = cv2.cvtColor(np.clip(bgr, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV)
    blue = (~grey) & (hsv[:, :, 0] >= 85) & (hsv[:, :, 0] <= 135)
    hsv2 = hsv.copy()
    hsv2[:, :, 0] = np.where(blue, ACCENT_DEF[accent][3], hsv[:, :, 0])
    tinted = cv2.cvtColor(hsv2, cv2.COLOR_HSV2BGR).astype(np.float32)
    out_[blue] = tinted[blue]
    cv2.imwrite(str(tmp / "theme" / "spritesheet_dark.png"), np.concatenate([np.clip(out_, 0, 255).astype(np.uint8), alpha], axis=2))
    sub = lambda m: _tint_hex(m, accent, base)
    tag = f"{accent}_{base}"
    for f_ in (tmp / "theme" / "dark.tcl", tmp / "sv.tcl"):
        txt_ = re.sub(r'"#([0-9a-fA-F]{6})"', sub, f_.read_text(encoding="utf-8"))
        # V5.58: a unique theme + namespace name per combination, fonts created once only: the running window can source another
        # combination (live theme switching) without "theme already exists" / "font already exists" errors
        txt_ = txt_.replace("sun-valley-dark", f"mt-{tag}").replace("sv_dark", f"sv_{tag}")
        if f_.name == "sv.tcl":
            txt_ = re.sub(r"^source \[file join \[file dirname \[info script\]\] theme light\.tcl\]\s*$", "", txt_, flags=re.M)
            txt_ = re.sub(r"^font create (.*)$", r"catch {font create \1}", txt_, flags=re.M)
            # V6.1.3: the <<ThemeChanged>> bindings are added once per window, not once per sourced variant (each extra one ran
            # configure_colors -> tk_setPalette over every widget again); the handlers themselves are unchanged
            txt_ = re.sub(r"^bind (\S+(?: \S+)*?) (<<ThemeChanged>>) (\{.*\})$",
                          lambda m_: "if {![info exists ::mt_bound(%s)]} {set ::mt_bound(%s) 1; bind %s %s %s}" % (
                              re.sub(r"\W", "_", m_.group(1)), re.sub(r"\W", "_", m_.group(1)), m_.group(1), m_.group(2), m_.group(3)), txt_, flags=re.M)
        f_.write_text(txt_, encoding="utf-8")
    (tmp / "ok").write_text(THEME_VER)
    shutil.rmtree(dst, ignore_errors=True)
    os.replace(tmp, dst)
    return dst


def apply_theme(root, scale=None, accent="lime", base="grey"):
    """V5.57: Sun Valley dark (pip: sv-ttk, offline) recoloured to a base (grey | black) and an accent colour; the plain clam
    fallback uses the same palette. Returns the palette (log, canvases, tags)."""
    if scale:
        UI_SCALE[0] = max(0.7, min(2.5, float(scale)))
    pal = make_palette(accent, base)
    if SIMPLE_THEME:                                               # V6.2 A/B: ttk "clam" + the same palette, no sv_ttk image elements
        SV_THEME[0] = False
        with pstage("apply_theme: clam theme_use + style configure/map"):
            return _apply_theme_clam(root, scale, pal)
    try:
        import tkinter.font as tkfont
        tname = f"mt-{accent}_{base}"
        if tname not in ttk.Style(root).theme_names():             # V5.58: every combination is sourced once per window, then reused
            with pstage("apply_theme: build/read theme dir + source sv.tcl"):
                root.tk.call("source", str(lime_theme_dir(accent, base) / "sv.tcl"))
        root._sv_ttk_loaded = True                                 # sv_ttk itself must not load its blue copy
        with pstage("apply_theme: ttk theme_use"):
            ttk.Style(root).theme_use(tname)
        SV_THEME[0] = True
        with pstage("apply_theme: named fonts configure"):
            for nm, sz, bold in (("TkDefaultFont", 10, 0), ("TkTextFont", 10, 0), ("TkMenuFont", 10, 0), ("TkHeadingFont", 10, 1),
                                 ("SunValleyBodyFont", 10, 0), ("SunValleyBodyStrongFont", 10, 1), ("SunValleyCaptionFont", 9, 0)):
                try:
                    tkfont.nametofont(nm, root).configure(size=F(sz))
                except Exception:
                    pass
        st = ttk.Style(root)
        with pstage("apply_theme: ttk style configure (10 calls)"):
            st.configure("Treeview", rowheight=int(26 * UI_SCALE[0]))
            st.configure("Treeview.Heading", font=("Segoe UI", F(10), "bold"))
            st.configure("TLabelframe.Label", font=("Segoe UI", F(10), "bold"), foreground=pal["acc"])
            st.configure("TNotebook.Tab", padding=(16, 5), font=("Segoe UI", F(10), "bold"))
            st.configure("Big.TButton", font=("Segoe UI", F(11), "bold"), padding=(14, 6))
            st.configure("Big.Accent.TButton", font=("Segoe UI", F(11), "bold"), padding=(14, 6))
            st.configure("Section.TLabel", font=("Segoe UI", F(11), "bold"), foreground=pal["acc"])
            st.configure("Dim.TLabel", foreground=pal["dim"])
        root.configure(bg=pal["bg"])
        root.option_add("*TCombobox*Listbox.background", pal["field"])
        root.option_add("*TCombobox*Listbox.foreground", pal["fg"])
        root.option_add("*TCombobox*Listbox.selectBackground", pal["acc"])
        root.option_add("*TCombobox*Listbox.selectForeground", pal["acc_fg"])
        return pal
    except Exception as ex:
        SV_THEME[0] = False
        LOGONLY(f"Sun Valley theme not available ({ex}) - plain dark theme")
        return _apply_theme_clam(root, scale, pal)


def _apply_theme_clam(root, scale=None, pal=None):
    """Plain dark theme with the same palette (used when sv-ttk is not installed)."""
    pal = dict(pal or PAL)
    if scale:
        UI_SCALE[0] = max(0.7, min(2.5, float(scale)))
    st = ttk.Style(root)
    st.theme_use("clam")
    root.configure(bg=pal["bg"])
    root.option_add("*Font", ("Segoe UI", F(10)))
    root.option_add("*TCombobox*Listbox.background", pal["field"])
    root.option_add("*TCombobox*Listbox.foreground", pal["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", pal["acc"])
    root.option_add("*TCombobox*Listbox.selectForeground", pal["acc_fg"])
    st.configure(".", background=pal["bg"], foreground=pal["fg"], fieldbackground=pal["field"], font=("Segoe UI", F(10)),
                 bordercolor=pal["border"], lightcolor=pal["bg"], darkcolor=pal["bg"], troughcolor=pal["head"],
                 selectbackground=pal["sel"], selectforeground=pal["sel_fg"], insertcolor=pal["fg"], focuscolor=pal["acc"])
    st.configure("Treeview", background=pal["field"], fieldbackground=pal["field"], foreground=pal["fg"], rowheight=int(24 * UI_SCALE[0]),
                 bordercolor=pal["border"], borderwidth=1)
    st.map("Treeview", background=[("selected", pal["sel"])], foreground=[("selected", pal["sel_fg"])])
    st.configure("Treeview.Heading", background=pal["head"], foreground=pal["fg"], font=("Segoe UI", F(10), "bold"), padding=5,
                 bordercolor=pal["border"], relief="raised")
    st.configure("TLabelframe", background=pal["bg"], bordercolor=pal["border"], padding=8, relief="solid", borderwidth=1)
    st.configure("TLabelframe.Label", background=pal["bg"], foreground=pal["fg"], font=("Segoe UI", F(10), "bold"))
    st.configure("TNotebook", background=pal["bg"], borderwidth=1, bordercolor=pal["border"])
    st.configure("TNotebook.Tab", background=pal["head"], foreground=pal["fg"], padding=(16, 7), font=("Segoe UI", F(10), "bold"),
                 bordercolor=pal["border"])
    st.map("TNotebook.Tab", background=[("selected", pal["acc"])], foreground=[("selected", pal["acc_fg"])])
    st.configure("TButton", padding=(10, 5), background=pal["btn"], foreground=pal["fg"], bordercolor=pal["border"],
                 lightcolor=pal["btn"], darkcolor=pal["btn"], borderwidth=1, relief="raised")
    st.map("TButton", background=[("disabled", pal["bg"]), ("pressed", pal["sel"]), ("active", pal["btn_act"])],
           foreground=[("disabled", pal["dim"])], bordercolor=[("focus", pal["acc"]), ("active", pal["acc"])])
    for w in ("TEntry", "TSpinbox", "TCombobox"):
        st.configure(w, padding=4, fieldbackground=pal["field"], foreground=pal["fg"], bordercolor=pal["border"],
                     lightcolor=pal["field"], darkcolor=pal["field"], arrowcolor=pal["fg"], background=pal["btn"], insertcolor=pal["fg"])
        st.map(w, bordercolor=[("focus", pal["acc"])], lightcolor=[("focus", pal["acc"])],
               fieldbackground=[("readonly", pal["field"]), ("disabled", pal["bg"])], foreground=[("readonly", pal["fg"]), ("disabled", pal["dim"])])
    for w in ("TCheckbutton", "TRadiobutton"):
        st.configure(w, background=pal["bg"], foreground=pal["fg"], indicatorbackground=pal["field"], indicatorforeground=pal["check"],
                     indicatorcolor=pal["field"], bordercolor=pal["border"], upperbordercolor=pal["border"], lowerbordercolor=pal["border"])
        st.map(w, indicatorcolor=[("selected", pal["check"]), ("pressed", pal["sel"])], background=[("active", pal["btn_act"])],
               indicatorbackground=[("selected", pal["check"])])
    st.configure("TProgressbar", background=pal["acc"], troughcolor=pal["head"], bordercolor=pal["border"])
    st.configure("Vertical.TScrollbar", background=pal["btn"], troughcolor=pal["head"], arrowcolor=pal["fg"], bordercolor=pal["border"])
    st.configure("Horizontal.TScale", background=pal["acc"], troughcolor=pal["head"], bordercolor=pal["border"])
    st.configure("Big.TButton", font=("Segoe UI", F(11), "bold"), padding=(14, 6))
    st.configure("Big.Accent.TButton", font=("Segoe UI", F(11), "bold"), padding=(14, 6), background=pal["acc"], foreground=pal["acc_fg"],
                 lightcolor=pal["acc"], darkcolor=pal["acc"], bordercolor=pal["acc"])
    st.map("Big.Accent.TButton", background=[("disabled", pal["head"]), ("active", pal["sel"]), ("pressed", pal["sel"])],
           foreground=[("disabled", pal["dim"]), ("active", pal["sel_fg"])])
    st.configure("Accent.TButton", background=pal["acc"], foreground=pal["acc_fg"], lightcolor=pal["acc"], darkcolor=pal["acc"],
                 bordercolor=pal["acc"])
    st.map("Accent.TButton", background=[("disabled", pal["head"]), ("active", pal["sel"]), ("pressed", pal["sel"])],
           foreground=[("disabled", pal["dim"]), ("active", pal["sel_fg"])])
    st.configure("Section.TLabel", font=("Segoe UI", F(11), "bold"), foreground=pal["acc"])
    st.configure("Dim.TLabel", foreground=pal["dim"])
    return pal


SECTION_COLORS = {"intro": "#9db4d6", "verse": "#a8d5a2", "build": "#f2c46d", "drop": "#ef6f6c", "breakdown": "#b49ad8",
                  "outro": "#9fa6ad", "": "#cccccc"}


class SongMapView:
    """Songs tab > Song map: waveform, energy curve, beat + downbeat ticks, coloured sections, drops and accents."""
    def __init__(self, app, path, csv_bpm=None):
        self.app, self.path, self.an, self.zoom = app, path, None, 1
        self.win = app.reg(tk.Toplevel(app.root), "window")
        self.win.title(f"Song map - {Path(path).name}")
        self.win.configure(bg=app.pal["bg"])
        top = ttk.Frame(self.win)
        top.pack(fill="x", padx=6, pady=4)
        self.info = tk.StringVar(value="analysing (cached after the first time) ...")
        ttk.Label(top, textvariable=self.info, wraplength=1100).pack(side="left")
        self.zv = tk.StringVar(value="1x")
        cb = ttk.Combobox(top, textvariable=self.zv, values=["1x", "2x", "4x", "8x"], width=5, state="readonly")
        cb.pack(side="right")
        cb.bind("<<ComboboxSelected>>", lambda e: self.draw())
        ttk.Label(top, text="Zoom").pack(side="right", padx=4)
        fr = ttk.Frame(self.win)
        fr.pack(fill="both", expand=True, padx=6, pady=4)
        self.cv = app.reg(tk.Canvas(fr, width=1300, height=int(360 * UI_SCALE[0]), bg="#ececec",
                                    highlightthickness=1, highlightbackground=app.pal["border"]), "fixed")
        sb = ttk.Scrollbar(fr, orient="horizontal", command=self.cv.xview)
        self.cv.configure(xscrollcommand=sb.set)
        self.cv.pack(fill="both", expand=True)
        sb.pack(fill="x")
        leg = ttk.Frame(self.win)
        leg.pack(fill="x", padx=6, pady=2)
        for k in ("intro", "verse", "build", "drop", "breakdown", "outro"):
            app.reg(tk.Label(leg, text=f"  {k}  ", bg=SECTION_COLORS[k], fg="#111"), "fixed").pack(side="left", padx=2)
        ttk.Label(leg, text="   red line = drop   | tall tick = downbeat   | dot = accent (filled = bass hit)   | line = energy").pack(side="left")
        self.cv.bind("<Configure>", lambda e: self.draw())

        def work():
            try:
                an = get_songmap(path, csv_bpm)
                self.app.q.put(("call", lambda: self.show(an)))
            except Exception as ex:
                msg = f"song map failed: {ex}"
                self.app.q.put(("call", lambda: self.info.set(msg)))
        threading.Thread(target=work, daemon=True).start()

    def show(self, an):
        self.an = an
        self.win.title(f"Song map ({SONGMAP_CHOICES.get(str(an.get('songmap_version', 'v1'))[:2], 'Songmap V1')}) - {Path(self.path).name}" if getattr(self, "path", None) else self.win.title())
        drops = ", ".join(f"{ts(d['t'])} ({d['strength']:.2f})" for d in an.get("drops", [])) or "none"
        self.info.set(f"BPM {an['bpm']} ({an.get('bpm_src')}, librosa {an.get('bpm_librosa')}, agree {an.get('librosa_agree_ms')} ms)   "
                      f"beats {len(an['beats'])}   rhythm {an.get('rhythm')}   loudness {an.get('lufs')} LUFS   drops: {drops}   "
                      f"sections: {' > '.join(s['label'] for s in an.get('sections', []))}")
        self.draw()

    def draw(self):
        if not self.an or not self.cv.winfo_exists():
            return
        an, cv = self.an, self.cv
        cv.delete("all")
        z = int(self.zv.get().rstrip("x") or 1)
        W = max(400, cv.winfo_width() - 4) * z
        H = max(200, cv.winfo_height() - 4)
        dur = an["dur"]
        X = lambda t: 2 + t / dur * W
        cv.configure(scrollregion=(0, 0, W + 4, H))
        top, mid = 18, H * 0.45
        for sct in an.get("sections", []):
            cv.create_rectangle(X(sct["start_t"]), top, X(sct["end_t"]), H - 18, fill=SECTION_COLORS.get(sct["label"], "#ccc"), outline="")
            cv.create_text(X(sct["start_t"]) + 4, top + 2, text=sct["label"], anchor="nw", font=("Segoe UI", F(9), "bold"), fill="#111")
        wave = an.get("wave") or []
        if wave:
            mx = max(wave) or 1
            pts = []
            for i, v in enumerate(wave):
                t = (i + 0.5) / len(wave) * dur
                pts.append((X(t), mid - v / mx * (mid - top - 18), mid + v / mx * (mid - top - 18)))
            for x, a, b in pts:
                cv.create_line(x, a, x, b, fill="#3d5a80")
        en = an.get("energy") or []
        bt = an["beats"]
        if en:
            pts = []
            for t, e in zip(bt, en):
                pts += [X(t), H - 22 - e * (H * 0.35)]
            if len(pts) >= 4:
                cv.create_line(*pts, fill="#d1495b", width=2)
        down = set(an.get("down", []))
        for i, t in enumerate(bt):
            x = X(t)
            if i in down:
                cv.create_line(x, H - 18, x, H - 4, fill="#111", width=2)
            elif z >= 2:
                cv.create_line(x, H - 12, x, H - 4, fill="#555")
        for t, s_, bass in an.get("accents", [])[:800]:
            r = 2 + min(4, s_ / 4)
            cv.create_oval(X(t) - r, top + 20 - r, X(t) + r, top + 20 + r, outline="#222", fill="#222" if bass else "")
        for d in an.get("drops", []):
            cv.create_line(X(d["t"]), top, X(d["t"]), H - 18, fill="#d00000", width=3)
            cv.create_text(X(d["t"]) + 3, H - 34, text=f"DROP {ts(d['t'])}", anchor="w", fill="#d00000", font=("Segoe UI", F(9), "bold"))
        for s in range(0, int(dur) + 1, 10 if z == 1 else 5):
            cv.create_text(X(s), H - 2, text=ts(s)[:-2], anchor="s", font=("Segoe UI", F(8)), fill="#444")


def make_tree(parent, cols, height=10, **kw):
    """Treeview with a vertical scrollbar; returns (frame, tree)."""
    fr = ttk.Frame(parent)
    tree = ttk.Treeview(fr, columns=cols, height=height, **kw)
    sb = ttk.Scrollbar(fr, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return fr, tree


APP_NAME = "Montager"
APP_ID = "fireaxe.montager"                           # explicit Windows AppUserModelID: own taskbar identity (not pythonw's)


def set_app_id():
    """Before the first window exists: give this process its own taskbar identity (Windows only)."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def set_window_icon(root):
    """montage.ico as the window / taskbar icon (iconbitmap) plus a PNG copy through iconphoto (other sizes, non-Windows)."""
    try:
        root.iconbitmap(default=str(HERE / "montage.ico"))
    except Exception:
        pass
    try:
        img = tk.PhotoImage(file=str(HERE / "montage.png"))
        root.iconphoto(True, img)
        root._icon_img = img
    except Exception:
        pass


MORE_LABEL = "More filters & actions"


class App:
    DATES = {"All dates": None, "Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}

    def __init__(self, start_tab=0, startup=True):
        pmark("App.__init__ start")
        set_app_id()
        with pstage("tk.Tk() creation"):
            self.root = tk.Tk()
        self.root.withdraw()                                       # V5.6: built hidden, shown once when every tab is laid out
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        set_window_icon(self.root)
        self.root.minsize(920, 640)
        self._resizing, self._rs_after, self._last_size, self._save_after, self._loading = False, None, None, None, False
        self.q, self.busy, self.buttons, self._imgs, self.pending = queue.Queue(), False, [], [], []
        REGION_PROMPT[0] = self.region_prompt                        # V6.7.6: a Valorant "calibration changed" rescan asks first
        self.named = {}                   # button registry (smoketest checks every required button)
        self._busy_btn, self._result = None, None
        self.sorts, self.sort_refill, self.sort_labels = {}, {}, {}
        self.clips, self.ticked, self.songs, self.bpm, self.last_video, self.byp = [], set(), [], {}, None, {}
        self._fill_token = {}
        self.scan_active, self._fill_pending = False, {}
        self._log_buf, self._log_flush_at, self._prog_val, self._prog_at = [], 0.0, None, 0.0
        LOG_SINK[0] = lambda m: self.q.put(("log", m))
        PROGRESS[0] = lambda f, t: self.q.put(("prog", (f, t)))
        self.cfg = load_config()
        with pstage("apply_theme (App.__init__)"):
            self.pal = apply_theme(self.root, self.cfg.get("ui_scale", 1.0), self.cfg.get("accent", "lime"), self.cfg.get("base", "grey"))
        sc = UI_SCALE[0]
        self._shown = False                                        # V6.1: the main window is shown once, after the first fill
        with pstage("splash build + paint"):
            self._splash_make()
        lay = self.cfg.get("ui_layout") or {}
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w0, h0 = int(1220 * sc), int(920 * sc)
        m_ = re.fullmatch(r"(\d+)x(\d+)", str(lay.get("geometry", "")))
        if m_:
            w0, h0 = int(m_.group(1)), int(m_.group(2))
        self.root.geometry(f"{max(920, min(w0, sw))}x{max(640, min(h0, sh - 60))}")      # V5.55: the size from the last run
        self.last_click = None
        # bottom area first so the panes can expand above it
        bot = self._bot = ttk.Frame(self.root, padding=(10, 4))
        bot.pack(side="bottom", fill="x")
        row = ttk.Frame(bot)
        row.pack(fill="x")
        self.pbar = ttk.Progressbar(row, maximum=1.0)
        self.pbar.pack(side="left", fill="x", expand=True)
        self.plabel = tk.StringVar(value="Idle")
        ttk.Label(row, textvariable=self.plabel, width=34).pack(side="left", padx=8)
        self.named["Cancel"] = ttk.Button(row, text="Cancel", command=stop_all)
        self.named["Cancel"].pack(side="left")
        res = ttk.Frame(bot)
        res.pack(fill="x", pady=(6, 0))
        self.vlabel = tk.StringVar(value="Last video: none yet")
        ttk.Label(res, textvariable=self.vlabel).pack(side="left")
        self.b_open = ttk.Button(res, text="Open video", command=self.safe(self.open_video), state="disabled")
        self.b_open.pack(side="right")
        self.b_folder = ttk.Button(res, text="Open folder", command=self.safe(self.open_vfolder))
        self.b_folder.pack(side="right", padx=6)
        self.named["Open video"], self.named["Open folder"] = self.b_open, self.b_folder
        # V5.55: tabs above, log below, with a drag divider between them (position remembered)
        self.vpane = self.make_pane(self.root, "vertical")
        self.vpane.pack(side="top", fill="both", expand=True, padx=10, pady=(8, 4))
        self.nb = ttk.Notebook(self.vpane)
        lf = ttk.Frame(self.vpane)
        self.log = tk.Text(lf, height=4, wrap="word", bg=self.pal["field"], fg=self.pal["fg"], insertbackground=self.pal["fg"],
                           relief="flat", bd=0, highlightthickness=1, highlightbackground=self.pal["border"], padx=10, pady=8,
                           font=("Consolas", F(10)), selectbackground=self.pal["sel"], selectforeground=self.pal["sel_fg"])
        self.reg(self.log, "text")
        lsb = ttk.Scrollbar(lf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set)
        self.log.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        self.vpane.add(self.nb, minsize=int(470 * sc), stretch="always")
        self.vpane.add(lf, minsize=int(56 * sc), stretch="never")
        self.tabs = {n: ttk.Frame(self.nb, padding=10) for n in ("Auto", "Manual", "Songs", "Troubleshoot", "Settings")}
        for n, f in self.tabs.items():
            self.nb.add(f, text=n)
        _wb = time.perf_counter()
        for _n, _b in (("Auto", self.build_auto), ("Manual", self.build_manual), ("Songs", self.build_songs),
                       ("Troubleshoot", self.build_trouble), ("Settings", self.build_settings)):
            with pstage(f"  widget build: {_n} tab"):
                _b()
        if PERF is not None:
            PERF.stage("widget build (all five tabs)", _wb)
        self.install_wheel_guard()
        for pw in (self.vpane, self.mpane):
            pw.bind("<ButtonRelease-1>", self.save_layout, add="+")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        if PERF is not None:
            PERF.attach(self.root)
        self._lay = lay
        with pstage("prerealize (layout of every tab)"):
            self.prerealize(start_tab, lay)                       # V5.58: every tab is laid out once before the window is visible
        self.switch_ms = []                                       # V5.58: (tab, ms) of every tab switch until the layout is idle again
        self._sw_t0 = None
        self.nb.bind("<<NotebookTabChanged>>", self.on_tab_changed, add="+")
        self.root.bind("<Configure>", self.on_root_configure, add="+")
        self.root.after(100, self.poll)
        self.first_show(startup)                                  # V6.1: startup work + first fill behind the splash, then show once

    # ---- tab switching (V5.58): all tabs are built once in __init__ and only shown / hidden afterwards
    def prerealize(self, start_tab, lay):
        """Lay out and map every tab (and the dividers) while the window is still invisible (alpha 0), so a later tab switch only raises
        an already laid-out frame: no widgets popping in, no re-layout after the tab is visible."""
        try:
            self.root.update_idletasks()
            for f in self.tabs.values():
                self.nb.select(f)
                self.root.update()
            if hasattr(self, "set_relayout"):
                self.set_relayout()                               # the Settings page is sized now, not 100 ms after it is first shown
            self.nb.select(start_tab)
            self.apply_layout(lay)
            self.root.update()
        except tk.TclError:
            pass

    # ---- V6.1 splash + first show: everything that changes visible widgets happens while the main window is still withdrawn
    def _splash_make(self):
        sp = self._splash = tk.Toplevel(self.root)
        sp.withdraw()
        sp.overrideredirect(True)
        sp.title(f"{APP_NAME} - loading")
        self._splash_lbl = tk.Label(sp, text=f"{APP_NAME} - loading", padx=40, pady=16, font=("Segoe UI", F(12)))
        self._splash_lbl.pack()
        self._splash_bar = ttk.Progressbar(sp, maximum=1.0, length=int(320 * UI_SCALE[0]))
        self._splash_bar.pack(padx=24, pady=(0, 18))
        self._splash_frame = sp
        self.reg(sp, "window")
        self.reg(self._splash_lbl, "label")
        sp.update_idletasks()
        w, h = sp.winfo_reqwidth(), sp.winfo_reqheight()
        sp.geometry(f"+{(sp.winfo_screenwidth() - w) // 2}+{(sp.winfo_screenheight() - h) // 3}")
        sp.deiconify()
        sp.update()                                               # painted now; the main window stays withdrawn
        pmark("splash painted")

    def splash_set(self, frac=None, text=None):
        try:
            if frac is not None and self._splash is not None:
                self._splash_bar["value"] = max(self._splash_bar["value"], min(1.0, frac))
            if text and self._splash is not None:
                self._splash_lbl.config(text=text)
        except tk.TclError:
            pass

    def first_show(self, startup):
        """Startup work, first cache load and first fill of the clip and song lists run behind the splash; the main window is shown only
        after that (or after 12 s, with a 'Loading...' status line, and fills when ready)."""
        late = False
        try:
            if startup:
                self.splash_set(0.05, f"{APP_NAME} - checking setup ...")
                self._splash.update()
                self._startup_t0 = time.monotonic()
                with pstage("App.startup (UI thread; run_task starts the scan threads)"):
                    self.startup()
                self.splash_set(0.15, f"{APP_NAME} - loading clips and songs ...")
                while not self.first_fill_done():
                    if time.monotonic() - self._startup_t0 > 12:
                        late = True
                        break
                    self.root.update()
                    time.sleep(0.02)
        except tk.TclError:
            pass
        finally:
            pmark("first fill done" + (" (TIMEOUT 12 s)" if late else ""))
            with pstage("show_main"):
                self.show_main(late)
            pmark("main window shown")

    def first_fill_done(self):
        return (getattr(self, "_clips_filled", False) and not getattr(self, "_auto_busy", False) and not self._fill_pending
                and self.q.empty() and not self._resizing)

    def show_main(self, late=False):
        self.splash_set(1.0, f"{APP_NAME} - ready")
        self._shown = True
        try:
            self.flush_log()
            if late:
                self.plabel.set("Loading...")
            self.root.update_idletasks()
            self.root.update()
            self._first_cfg_n, self._first_cfg_id = 0, self.nb.bind("<Configure>", self._first_configure, add="+")
            self.root.deiconify()                                 # first and only time the window becomes visible
        finally:
            try:
                self._splash.destroy()
            except tk.TclError:
                pass
            self._splash = None

    def reveal(self, win, over=None):
        """Popups are created withdrawn; lay them out, centre over the main window, then show once."""
        try:
            win.update_idletasks()
            over = over or self.root
            w, h = win.winfo_reqwidth(), win.winfo_reqheight()
            m = re.fullmatch(r"(\d+)x(\d+)", win.geometry().split("+")[0])
            if m and int(m.group(1)) > 1:
                w, h = int(m.group(1)), int(m.group(2))
            x = over.winfo_rootx() + max(0, (over.winfo_width() - w) // 2)
            y = over.winfo_rooty() + max(0, (over.winfo_height() - h) // 3)
            win.geometry(f"+{max(0, x)}+{max(0, y)}")
        except tk.TclError:
            pass
        win.deiconify()

    def on_tab_changed(self, _e=None):
        self._sw_t0 = time.perf_counter()
        self.root.after_idle(self._tab_idle)

    def _tab_idle(self):
        if self._sw_t0 is not None:
            self.switch_ms.append((self.nb.tab(self.nb.select(), "text"), (time.perf_counter() - self._sw_t0) * 1000))
            del self.switch_ms[:-200]
            self._sw_t0 = None

    # ---- mouse wheel (V5.57): never changes a value; scrolls the nearest scrollable container instead
    WHEEL_GUARDED = ("TCombobox", "TSpinbox", "TScale", "TMenubutton", "Spinbox", "Scale", "Menubutton")
    WHEEL_SELF = ("Treeview", "Text", "Listbox", "Scrollbar", "TScrollbar")
    WHEEL_SEQS = ("<MouseWheel>", "<Shift-MouseWheel>", "<Control-MouseWheel>", "<Button-4>", "<Button-5>", "<Shift-Button-4>",
                  "<Shift-Button-5>", "<Control-Button-4>", "<Control-Button-5>")

    def install_wheel_guard(self):
        for cls in self.WHEEL_GUARDED:
            for seq in self.WHEEL_SEQS:
                self.root.bind_class(cls, seq, self.on_wheel_guarded)       # replaces the class's own wheel-changes-value binding
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind_all(seq, self.on_wheel, add="+")

    @staticmethod
    def wheel_dir(e):
        return -1 if (getattr(e, "delta", 0) > 0 or getattr(e, "num", 0) == 4) else 1

    def scroll_container(self, w, e):
        """Scroll the nearest scrollable container (a Canvas page) above widget w by one wheel step. Returns True when one scrolled."""
        while w is not None:
            try:
                if w.winfo_class() == "Canvas" and str(w.cget("yscrollcommand")):
                    w.yview_scroll(self.wheel_dir(e), "units")
                    return True
            except (tk.TclError, AttributeError):
                pass
            w = getattr(w, "master", None)
        return False

    def on_wheel_guarded(self, e):
        self.scroll_container(e.widget, e)
        return "break"                                                     # the combobox / spinbox / slider keeps its value

    def on_wheel(self, e):
        try:
            if e.widget.winfo_class() in self.WHEEL_SELF:                 # lists and the log scroll themselves
                return None
        except (tk.TclError, AttributeError):
            return None
        self.scroll_container(e.widget, e)
        return None

    # ------------------------------------------------------------ plumbing
    def make_pane(self, parent, orient):
        """A drag divider between two areas (V5.55)."""
        pw = tk.PanedWindow(parent, orient=orient, sashwidth=9, sashrelief="flat", sashpad=1, bd=0, bg=self.pal["border"],
                            opaqueresize=False, showhandle=False)
        return self.reg(pw, "pane")         # V5.56: drag a thin line, lay out once on release

    def layout_state(self):
        """Window size + divider positions (as fractions of their pane, so they survive other window sizes)."""
        self.root.update_idletasks()
        st = {"v": 2, "geometry": f"{self.root.winfo_width()}x{self.root.winfo_height()}"}
        for k, pw in (("main", self.vpane), ("manual", getattr(self, "mpane", None))):
            try:
                st[k] = round(pw.sash_coord(0)[1] / max(1, pw.winfo_height()), 4)
            except Exception:
                pass
        return st

    def apply_layout(self, lay, tries=0):
        """Divider positions from the last run (or a default: the log gets ~150 px, the song list ~30% of the Manual tab)."""
        self.root.update_idletasks()
        est = not self._shown and self.vpane.winfo_height() < 200  # V6.1: withdrawn window: pane heights come from the geometry, no retry later
        if est:
            hv, hm = self._pane_heights_est()
        elif self.vpane.winfo_height() < 200 and tries < 30:       # the window is not laid out yet: try again shortly
            self.root.after(100, lambda: self.apply_layout(lay, tries + 1))
            return
        if lay.get("v") != 2:                                      # V5.56: the clip list got more room - forget the older divider
            lay = {k: v for k, v in lay.items() if k != "manual"}
        for k, pw, dflt in (("main", self.vpane, None), ("manual", getattr(self, "mpane", None), 0.8)):
            if pw is None:
                continue
            try:
                h = max(1, (hv if k == "main" else hm) if est else pw.winfo_height())
                frac = lay.get(k)
                y = int(h * frac) if isinstance(frac, (int, float)) and 0.1 < frac < 0.95 else \
                    (int(h * dflt) if dflt else h - int(100 * UI_SCALE[0]))
                pw.sash_place(0, 0, y)
                self._sash_want = getattr(self, "_sash_want", {})
                self._sash_want[k] = y
            except Exception:
                pass

    def _first_configure(self, _e=None):
        """The dividers are re-placed once, while the window gets its real size on the first map (before the first paint); then it unbinds."""
        if _e is not None and _e.widget is not self.nb:
            return
        self._first_cfg_n += 1
        want = getattr(self, "_sash_want", {}).get("main")
        try:
            ok = want is not None and abs(self.vpane.sash_coord(0)[1] - want) <= 2 and self.vpane.winfo_height() > 200
        except tk.TclError:
            ok = True
        if ok or self._first_cfg_n > 10:                           # the dividers sit where the saved layout says: done
            self.nb.unbind("<Configure>", self._first_cfg_id)
            return
        self.apply_layout(self._lay)

    def _pane_heights_est(self):
        """Heights the two dividers' panes will have once the window is shown, from the window geometry and the requested sizes."""
        m = re.match(r"(\d+)x(\d+)", self.root.geometry())
        H = int(m.group(2)) if m else 900
        hv = max(1, H - self._bot.winfo_reqheight() - 12)          # vpane: window minus the footer and the 8 + 4 px padding
        lay_y = self.cfg.get("ui_layout") or {}
        fr = lay_y.get("main") if lay_y.get("v") == 2 else None
        ny = int(hv * fr) if isinstance(fr, (int, float)) and 0.1 < fr < 0.95 else hv - int(100 * UI_SCALE[0])
        strip = self.nb.winfo_reqheight() - max(f.winfo_reqheight() for f in self.tabs.values())
        man = self.tabs["Manual"]
        s3 = next((c for c in man.winfo_children() if c.winfo_class() == "TLabelframe" and c is not self.mpane), None)
        hm = ny - strip - 20 - (s3.winfo_reqheight() + 8 if s3 is not None else 0)
        return hv, max(1, hm)

    def save_layout(self, *_):
        try:
            cfg = load_config()
            cfg["ui_layout"] = self.layout_state()
            save_json(CONFIG_PATH, cfg)
        except Exception:
            pass

    def on_close(self):
        if PERF is not None:
            PERF.write()
        self.flush_settings()
        self.save_layout()
        self.root.destroy()

    def on_root_configure(self, e):
        """V5.56: while the window is being resized, heavy work (list refills) waits; it continues ~150 ms after the last change."""
        if e.widget is not self.root or (e.width, e.height) == self._last_size:
            return
        self._last_size = (e.width, e.height)
        self._resizing = True
        if self._rs_after:
            self.root.after_cancel(self._rs_after)
        self._rs_after = self.root.after(150, self.resize_done)

    def resize_done(self):
        self._resizing, self._rs_after = False, None

    # ---- settings are saved on every change (V5.56) to the one absolute config file next to montage.py
    def collect_settings(self, cfg):
        """Fill cfg from every settings control (Manual and Settings tab share the length / style / quality controls)."""
        for k, v in self.sv.items():
            cfg[k] = v.get().strip()
        cfg["clip_dirs"] = {g: [x.strip() for x in v.get().split(";") if x.strip()] for g, v in self.sl.items()}
        for k, v in self.sn.items():
            try:
                cfg[k] = float(v.get()) if "." in v.get() else int(v.get())
            except ValueError:
                pass                                               # half-typed number: keep the old value
        cfg["length_s"] = "optimal" if self.set_opt.get() else max(LEN_MIN_S, min(LEN_MAX_S, int(self.set_len.get())))
        cfg["style"], cfg["placement"] = self.set_style.get(), self.set_place.get()
        cfg["songmap_version"] = next((k for k, lab in SONGMAP_CHOICES_UI.items() if lab == self.set_songmap.get()), SONGMAP_DEFAULT)
        cfg["quality"], cfg["sync_report"] = self.set_q.get(), bool(self.set_sync.get())
        cfg["update_on_start"] = bool(self.set_upd.get())
        cfg["game_audio_track"] = {g: v.get() for g, v in self.set_track.items()}
        if self.set_names:
            cfg["player_names"] = {g: norm_names(v.get(), g) for g, v in self.set_names.items()}
        cfg["audio_mode"] = next((k for k, lab in AUDIO_MODES.items() if lab == self.set_audio.get()), "auto")
        cfg["accent"] = next((k for k, lab in ACCENT_NAMES.items() if lab == self.set_accent.get()), "lime")
        cfg["base"] = "black" if self.set_base.get().lower() == "black" else "grey"
        return cfg

    def autosave(self, *_):
        if self._loading:
            return
        if self._save_after:
            self.root.after_cancel(self._save_after)
        self._save_after = self.root.after(200, self.flush_settings)
        if hasattr(self, "save_status"):
            self.save_status.set("Saving...")

    def flush_settings(self):
        if self._save_after:
            try:
                self.root.after_cancel(self._save_after)
            except Exception:
                pass
            self._save_after = None
        if not hasattr(self, "set_track"):                         # Settings tab not built yet
            return
        try:
            cfg = self.collect_settings(load_config())
            save_json(CONFIG_PATH, cfg)
            self.cfg = cfg
            if hasattr(self, "save_status"):
                self.save_status.set("All changes saved")
        except Exception as ex:
            out(f"Settings not saved: {ex}")
            if hasattr(self, "save_status"):
                self.save_status.set("Not saved: see the log")

    def btn(self, parent, text, cmd, big=False, name=None, primary=False, **kw):
        """A button with feedback (V5.57): hover / pressed come from the theme; while its action runs the button shows a busy
        state (all buttons are disabled, so no double clicks); afterwards it shows 'Done \u2713' (or the action's own short result)
        for about 1.5 s, and the full message goes to the status line."""
        st = ("Big.Accent.TButton" if primary else "Big.TButton") if big else None
        b = ttk.Button(parent, text=text, command=self.safe(lambda: self.click(b, text, cmd)), **({"style": st} if st else {}), **kw)
        self.buttons.append(b)
        self.named[name or text] = b
        return b

    def click(self, b, label, cmd):
        was_busy, self._result = self.busy, None
        cmd()
        if self.busy and not was_busy:                             # the action runs in the background: busy state until it is done
            self._busy_btn = (b, label)
            if len(label) >= 8:
                b.configure(text="Working...")
        else:
            self.flash_button(b, label, self._result)

    def flash_button(self, b, label, msg=None, ms=1500):
        """Short result on the button itself ('Done \u2713' / 'Ticked 12 clips'), restored after ~1.5 s; the longer text goes to the status line."""
        msg = msg or "Done \u2713"
        short = msg if len(msg) <= max(len(label), 8) else "Done \u2713"
        if msg != "Done \u2713":
            self.status_flash(msg)
        try:
            b.configure(text=short)
            self.root.after(ms, lambda: b.winfo_exists() and str(b.cget("text")) == short and b.configure(text=label))
        except tk.TclError:
            pass

    def status_flash(self, msg, ms=2500):
        """A short message in the status line (bottom bar), then back to 'Idle' unless a job is running."""
        self.plabel.set(msg)
        self.root.after(ms, lambda: None if self.busy else (self.plabel.get() == msg and self.plabel.set("Idle")))

    def safe(self, fn):
        def w(*a):
            try:
                fn(*a)
            except Exception:
                out("ERROR:\n" + traceback.format_exc())
        return w

    def set_buttons(self, on):
        for b in self.buttons:
            try:
                if isinstance(b, tk.Button):
                    b.config(state="normal" if on else "disabled")
                else:
                    b.state(["!disabled"] if on else ["disabled"])
            except tk.TclError:
                pass

    def snap_vars(self):
        """V6.1.2: plain values of the Tk variables a worker needs. Workers never call Tk (the main loop may not be running yet: during the
        splash a worker's Tk call waits ~1 s and fails with "main thread is not in main loop")."""
        sn = self.__dict__.setdefault("_snap", {})
        for key, var in (("m_game", "m_game"), ("t_game", "t_game")):
            try:
                sn[key] = getattr(self, var).get()
            except (AttributeError, tk.TclError):
                sn.setdefault(key, "valorant")
        return sn

    def run_task(self, name, fn, *a):
        if self.busy or getattr(self, "est_running", False):    # never next to the status-line estimate (shared caches)
            self.pending.append((name, fn, a))
            out(f"Queued: {name}")
            return
        self.snap_vars()                                           # V6.1.2: Tk variables are read here, on the UI thread; workers use the snapshot
        self.busy = True
        job_enter(name)                                            # V6.8: regiontest (another process) refuses to run next to a task
        self.scan_active = name == "clips"                         # V5.6: no list refills while clips are being scanned
        if self.scan_active:
            self._prog_ui(None, "Scanning ...")
        CANCEL.clear()
        self.set_buttons(False)

        def target():
            try:
                fn(*a)
            except Exception as ex:
                out(f"ERROR in {name}: {ex}\n{traceback.format_exc()}")
            finally:
                job_exit()
                self.q.put(("done", None))
        threading.Thread(target=target, daemon=True).start()

    def flush_log(self):
        """V5.6: log lines are collected and inserted as one block every 250 ms; the log keeps the last 2000 lines."""
        self._log_flush_at = time.monotonic()
        if not self._log_buf:
            return
        lines, self._log_buf = self._log_buf, []
        self.log.insert("end", "\n".join(lines) + "\n")
        n = int(self.log.index("end-1c").split(".")[0])
        if n > 2000:
            self.log.delete("1.0", f"{n - 2000}.0")
        self.log.see("end")

    def flush_prog(self, force=False):
        now = time.monotonic()
        if self._prog_val is not None and (force or now - self._prog_at >= 0.25):
            f_, txt = self._prog_val
            self._prog_ui(f_, txt)
            self._prog_val, self._prog_at = None, now

    def _prog_ui(self, frac, text):
        """Progress bar / label: before the main window is shown the splash carries it (the main bar never changes pre-show)."""
        if self._shown:
            if frac is not None:
                self.pbar["value"] = frac
            if text is not None:
                self.plabel.set(text)
        else:
            if frac is not None:
                self.splash_set(0.15 + 0.75 * max(0.0, min(1.0, float(frac))))
            if text and text != "Idle":
                self.splash_set(None, f"{APP_NAME} - {text}")

    def poll(self):
        try:
            for _ in range(200):
                k, v = self.q.get_nowait()
                if k == "log":
                    self._log_buf.append(v)
                    if "Auto audio failed, used Legacy V5.55" in v:
                        self.status_flash("Auto audio failed, used Legacy V5.55", 12000)
                elif k == "prog":
                    self._prog_val = v
                elif k == "call":
                    self.safe(v)()
                elif k == "done":
                    self.flush_log()
                    self._prog_val = None
                    self.busy = self.scan_active = False
                    self._prog_ui(0, "Idle")
                    self.set_buttons(True)
                    self.rp_state()
                    bb_, self._busy_btn = self._busy_btn, None
                    if bb_:
                        self.flash_button(*bb_)
                    self.flush_fills()
                    self.refresh_auto()
                    if self.pending:
                        n, fn, a = self.pending.pop(0)
                        self.run_task(n, fn, *a)
        except queue.Empty:
            pass
        self.flush_prog()
        if time.monotonic() - self._log_flush_at >= 0.25:
            self.flush_log()
        self.root.after(80, self.poll)

    def flush_fills(self):
        """Lists whose refill was held back during a scan are refilled once now (the latest data only)."""
        pend, self._fill_pending = self._fill_pending, {}
        for tree, rows in pend.items():
            self.fill_chunked(tree, rows)

    def startup(self):
        miss = missing_packages()
        if miss and messagebox.askyesno("Missing packages", "Install now (user scope, no admin)?\n\n" + ", ".join(miss)):
            def inst():
                out("Installing: " + " ".join(miss))
                r = subprocess.run([sys.executable, "-m", "pip", "install", "--user"] + miss, capture_output=True, text=True)
                out((r.stdout + r.stderr)[-1500:])
                out("Done. Close and reopen this program.")
            self.run_task("pip", inst)
            return
        if not shutil.which("ffmpeg"):
            out("ffmpeg not found. Troubleshoot > Selfcheck explains how to get it without admin.")
        self.cfg = autodetect_dirs(load_config())
        self.run_task("clips", self.load_clips)
        self.run_task("matches", self.load_matches)
        threading.Thread(target=self.bpm_worker, daemon=True).start()

    def fill_chunked(self, tree, rows, chunk=300):
        """V5.6: build every row while the list is unmapped, then show it once (no row-by-row growth in a visible list).
        Held back (latest rows kept) while a clip scan runs; refilled once when it ends."""
        sig = getattr(self, "_fill_sig", None)
        if sig is None:
            sig = self._fill_sig = {}
        if sig.get(tree) == rows and self._fill_token.get(tree) is not None:     # V5.58: same data as the last fill: leave the list alone
            self._fill_pending.pop(tree, None)
            return
        if self.scan_active:
            self._fill_pending[tree] = list(rows)
            return
        if self._resizing:                                         # V5.56: no list refills while the window is being resized
            self.root.after(100, self.fill_chunked, tree, rows)
            return
        sig[tree] = list(rows)
        self._fill_token[tree] = object()
        self._fill_pending.pop(tree, None)
        mgr = tree.winfo_manager()
        info = getattr(tree, f"{mgr}_info")() if mgr in ("pack", "grid", "place") else None
        if info:
            getattr(tree, f"{mgr}_forget" if mgr != "grid" else "grid_remove")()
        try:
            tree.delete(*tree.get_children())
            for iid, text, vals in rows:
                tree.insert("", "end", iid=iid, text=text, values=vals)
        finally:
            if info:
                if mgr == "pack":
                    tree.pack(**info)
                elif mgr == "grid":
                    tree.grid()
                else:
                    tree.place(**info)

    def open_path(self, p):
        p = Path(p)
        if os.name == "nt":
            os.startfile(str(p))
        else:
            out(f"(on Windows this opens) {p}")

    def set_video(self, path):
        self.last_video = Path(path)
        self.vlabel.set(f"Last video: {self.last_video.name}")
        self.b_open.state(["!disabled"])

    def open_video(self):
        if self.last_video and self.last_video.exists():
            self.open_path(self.last_video)

    def open_vfolder(self):
        self.open_path(self.last_video.parent if self.last_video else Path(load_config()["output_root"]))

    def job_video(self, game, **kw):
        def go():
            if kw.get("mode", "render") == "render":
                out("Render: plan first (same as Dry plan, printed below), then render")
            res = run_job(game, **kw)
            if isinstance(res, Path) and kw.get("mode", "render") == "render":      # V5.55: a rendered montage marks its clips used
                try:
                    pj = load_json(res.parent / "logs" / (res.stem + ".plan.json"), {})
                    used = {t["path"] for t in pj.get("takes", [])} | {x["path"] for t in pj.get("takes", []) for x in t.get("srcs", [])}
                    if used:
                        mark_used(used, title=res.stem)
                except Exception as ex:
                    out(f"Used flags not saved: {ex}")
            if isinstance(res, Path):
                self.q.put(("call", lambda: self.set_video(res)))
            self.q.put(("call", lambda: self.run_task("clips", self.load_clips)))
        return go

    # ------------------------------------------------------------ Auto tab
    def build_auto(self):
        f = self.tabs["Auto"]
        ttk.Label(f, text="One montage per game per week from all your clips, nothing to pick. Kills are read from the killfeed "
                          "with OCR (no calibration needed; the killfeed region can be adjusted in Troubleshoot).",
                  font=("Segoe UI", F(10)), wraplength=1100).pack(anchor="w", padx=8, pady=4)
        self.auto_status = {}
        for g in GAMES:
            lf = ttk.LabelFrame(f, text=GAME_DIR[g])
            lf.pack(fill="x", padx=8, pady=4)
            sv = tk.StringVar()
            self.auto_status[g] = sv
            self.btn(lf, "Make this week's montage", lambda g=g: self.run_task(f"{g} auto", self.job_video(g, weekly=True)),
                     big=True, primary=True, name=f"auto:{g}:make").pack(side="left", padx=10, pady=4)
            col = ttk.Frame(lf)
            col.pack(side="left", fill="x", expand=True, padx=8)
            ttk.Label(col, textvariable=sv, justify="left").pack(anchor="w")
            sm = ttk.Frame(col)
            sm.pack(anchor="w", pady=4)
            for text, kw in (("Force new", dict(weekly=True, force=True)), ("Dry plan", dict(mode="dry", weekly=True)),
                             ("Preview 720p / 20 s", dict(mode="preview", weekly=True))):
                self.btn(sm, text, lambda g=g, kw=kw, text=text: self.run_task(f"{g} {text}", self.job_video(g, **kw)),
                         name=f"auto:{g}:{text}").pack(side="left", padx=3)
        self.refresh_auto()

    def refresh_auto(self):
        """V6.1: the Auto status texts are collected in a worker thread (cache reads, detector, folder listings) and only the finished
        strings are applied on the UI thread. Not repeated when nothing it reads has changed."""
        if getattr(self, "_auto_busy", False):
            self._auto_again = True
            return
        self._auto_busy = True

        def work():
            res = None
            try:
                with pstage("refresh_auto: _auto_collect (worker)"):
                    res = self._auto_collect()
            except Exception:
                out("Status refresh failed: " + traceback.format_exc()[-300:])
            self.q.put(("call", lambda: self._auto_apply(res)))
        threading.Thread(target=work, daemon=True).start()

    def _auto_apply(self, res):
        self._auto_busy = False
        if res:
            self._auto_sig = res[0]
            for g, txt in res[1].items():
                if self.auto_status[g].get() != txt:
                    self.auto_status[g].set(txt)
        if getattr(self, "_auto_again", False):
            self._auto_again = False
            self.refresh_auto()

    def _auto_signature(self, cfg):
        sig = [week_tag(datetime.datetime.now()), repr({g: (v or {}).get("song") for g, v in LAST_PLAN.items()})]
        try:
            with os.scandir(DATA) as it:
                sig += [(e.name, e.stat().st_mtime_ns) for e in it]
        except OSError:
            pass
        for g in GAMES:
            try:
                sig.append(os.stat(Path(cfg["output_root"]) / GAME_DIR[g]).st_mtime_ns)
            except OSError:
                sig.append(None)
        return repr(sig)

    def _auto_collect(self):
        cfg = load_config()
        sig = self._auto_signature(cfg)
        if sig == getattr(self, "_auto_sig", None):
            return None                                            # nothing changed since the last collect
        recs = [v for v in load_json(CLIPS_CACHE, {}).values() if isinstance(v, dict) and v.get("path")]
        kc = load_kills_cache()
        texts = {}
        for g in GAMES:
            det = load_dets(g).get(g)
            mine = [r for r in recs if tag_game(r["path"], cfg)[0] == g and not r.get("error") and r.get("dur", 0) <= cfg["max_dur_s"] and os.path.exists(r["path"])]
            done = 0
            if det:
                for r in mine:
                    r.setdefault("game", g)
                    if kills_key(r, g, det) in kc:
                        done += 1
            ex = weekly_existing(cfg, g)
            d = Path(cfg["output_root"]) / GAME_DIR[g]
            allv = [p for p, _ in montage_videos(d, g)]
            lp = LAST_PLAN.get(g)
            song = f"{lp['song']['artist']} - {lp['song']['title']} ({lp['song']['bpm']} BPM)" if lp else "chosen when the montage is made (newest week first)"
            texts[g] = (
                f"Killfeed region: {('calibrated' if det.calibrated else 'default top-right (optional: Troubleshoot > Calibrate killfeed region)') if det else 'OCR unavailable - Troubleshoot > Selfcheck'}\n"
                f"Clips scanned: {done} / {len(mine)}\n"
                f"Song: {song}\n"
                f"This week ({week_tag(datetime.datetime.now())}): {ex[-1].name if ex else 'no montage yet'}    "
                f"Last montage: {allv[-1].name if allv else '-'}")
        return sig, texts

    # ------------------------------------------------------------ Manual tab
    def build_manual(self):
        f = self.tabs["Manual"]
        s3 = ttk.LabelFrame(f, text="Step 3: make it", padding=4)
        s3.pack(side="bottom", fill="x", padx=2, pady=(6, 2))          # packed FIRST so it can never be pushed off-screen
        bb = ttk.Frame(s3)
        bb.pack(fill="x", pady=(2, 6))
        for text, mode in (("Dry plan", "dry"), ("Preview (720p, 20 s)", "preview"), ("Render", "render")):
            self.btn(bb, text, lambda m=mode: self.manual(m), big=True, primary=(mode == "render"),
                     name=f"manual:{mode}").pack(side="left", expand=True, fill="x", padx=6)
        c3 = ttk.Frame(s3)
        c3.pack(fill="x", pady=2)
        ttk.Label(c3, text="Length").pack(side="left")
        L = self.cfg.get("length_s", "optimal")
        self.m_opt = tk.BooleanVar(value=not isinstance(L, (int, float)))
        cb = ttk.Checkbutton(c3, text="Optimal", variable=self.m_opt, command=self.update_status)
        cb.pack(side="left", padx=(4, 2))
        self.named["Optimal length"] = cb
        self.m_len = tk.IntVar(value=int(L) if isinstance(L, (int, float)) else LEN_MIN_S)
        self.m_len_sc = ttk.Scale(c3, from_=LEN_MIN_S, to=LEN_MAX_S, variable=self.m_len, length=150,
                                  command=lambda v: (self.m_len.set(int(float(v))), self.update_status()))
        self.m_len_sc.pack(side="left", padx=4)
        ttk.Label(c3, textvariable=self.m_len, width=4).pack(side="left")
        ttk.Label(c3, text="Style").pack(side="left", padx=(12, 2))
        st = self.cfg.get("style", "auto")
        self.m_style = tk.StringVar(value=st if st in STYLE_CHOICES else "auto")
        cbx = ttk.Combobox(c3, textvariable=self.m_style, values=STYLE_CHOICES, width=10, state="readonly")
        cbx.pack(side="left")
        self.named["Style"] = cbx
        ttk.Label(c3, text="Quality").pack(side="left", padx=(12, 2))
        self.m_q = tk.StringVar(value=self.cfg.get("quality", "nvenc"))
        ttk.Radiobutton(c3, text="Fast (NVENC)", variable=self.m_q, value="nvenc").pack(side="left")
        ttk.Radiobutton(c3, text="Max (x264 CRF15)", variable=self.m_q, value="max").pack(side="left", padx=4)
        ttk.Label(c3, text="Seed").pack(side="left", padx=(12, 2))
        self.m_seed = tk.StringVar()
        ttk.Entry(c3, textvariable=self.m_seed, width=8).pack(side="left")
        for v_ in (self.m_seed, self.m_style):
            v_.trace_add("write", lambda *_: self.update_status() if hasattr(self, "m_status") else None)
        self.m_status = tk.StringVar(value="Tick some clips.")       # V6.1.5: ONE short line (full text of the summary goes to the log)
        self.m_status_disp = tk.StringVar(value="Tick some clips.")
        self.m_status_lbl = ttk.Label(s3, textvariable=self.m_status_disp, font=("Segoe UI", F(10), "bold"), width=1, anchor="w")
        self.m_status_lbl.pack(anchor="w", fill="x", pady=2)
        self.m_status.trace_add("write", self.fit_status)
        self.m_status_lbl.bind("<Configure>", self.fit_status)
        self.mpane = mid = self.make_pane(f, "vertical")           # V5.55: drag divider between the clip list and the song list
        mid.pack(side="top", fill="both", expand=True)
        s1 = ttk.LabelFrame(mid, text="Step 1: tick the clips (click ticks, Shift+click a range)", padding=4)
        top = ttk.Frame(s1)
        top.pack(fill="x", pady=2)
        self.m_game = tk.StringVar(value="valorant")
        for g in GAMES:
            ttk.Radiobutton(top, text=GAME_DIR[g], variable=self.m_game, value=g,
                            command=lambda: self.run_task("clips", self.load_clips)).pack(side="left", padx=4)
        self.btn(top, "Reload list", lambda: self.run_task("clips", self.load_clips)).pack(side="left", padx=(12, 3))
        ttk.Label(top, text="Show").pack(side="left", padx=(12, 6))
        self.m_used = tk.StringVar(value="All clips")
        cbu = ttk.Combobox(top, textvariable=self.m_used, values=["All clips", "Used", "Unused"], width=9, state="readonly")
        cbu.pack(side="left")
        cbu.bind("<<ComboboxSelected>>", lambda e: self.apply_filter())
        self.named["Used filter"] = cbu
        # V5.57: the less used filters / actions are one dropdown (same widget + style as 'Show'); its list opens over the layout
        self.folder_names = ["All folders"]
        self.m_more = tk.StringVar(value=MORE_LABEL)
        self.b_more = ttk.Combobox(top, textvariable=self.m_more, values=[MORE_LABEL], width=24, state="readonly", height=14,
                                   postcommand=self.fill_more)
        self.b_more.pack(side="right", padx=3)
        self.b_more.bind("<<ComboboxSelected>>", self.more_selected)
        self.named["More filters"] = self.b_more
        self.m_folder = tk.StringVar(value="All folders")
        self.m_date = tk.StringVar(value="All dates")
        self.m_from, self.m_to = tk.StringVar(), tk.StringVar()
        for v in (self.m_from, self.m_to):
            v.trace_add("write", lambda *a: self.root.after(400, self.apply_filter))
        top2 = ttk.Frame(s1)
        top2.pack(fill="x", pady=2)
        self.btn(top2, "Tick all shown", lambda: self.tick("all")).pack(side="left", padx=3)
        self.btn(top2, "Untick all", lambda: self.tick("none")).pack(side="left", padx=3)
        self.btn(top2, "Tick clips with kills", lambda: self.tick("kills")).pack(side="left", padx=3)
        self.btn(top2, "Tick newest", lambda: self.tick("newest")).pack(side="left", padx=(12, 6))
        self.m_n = tk.StringVar(value="15")                         # 'Tick newest' count
        ttk.Spinbox(top2, from_=1, to=500, textvariable=self.m_n, width=5).pack(side="left")
        self.btn(top2, "Random pick", self.random_pick_ticks).pack(side="left", padx=(12, 6))
        self.m_rand_n = tk.StringVar(value="15")                    # V5.57: 'Random pick' has its own count (never shared with Tick newest)
        self.e_rand = ttk.Spinbox(top2, from_=1, to=500, textvariable=self.m_rand_n, width=5)
        self.e_rand.pack(side="left")
        self.m_incl_used = tk.BooleanVar(value=False)
        ttk.Checkbutton(top2, text="Include used clips", variable=self.m_incl_used).pack(side="left", padx=(12, 3))
        self.btn(top2, "Unflag all", self.unflag_all, name="manual:unflag_all").pack(side="left", padx=(12, 3))
        ttk.Label(top, text="Search clips").pack(side="left", padx=(14, 4))      # V6.8.1: on the first row of Step 1, right of 'Show'
        self.m_csearch = tk.StringVar()
        self.m_csearch.trace_add("write", lambda *a: self.csearch_changed())
        self.e_csearch = ttk.Entry(top, textvariable=self.m_csearch, width=28)
        self.e_csearch.pack(side="left")
        self.btn(top, "Clear", lambda: self.m_csearch.set(""), name="manual:clear_search").pack(side="left", padx=4)
        self.m_cshown = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.m_cshown, style="Dim.TLabel").pack(side="left", padx=8)
        fr, self.ctree = make_tree(s1, ("date", "len", "kills", "used", "open", "trash"), height=20, selectmode="none")
        fr.pack(fill="both", expand=True)
        for c, w, t in (("#0", 400, "Clip"), ("date", 100, "Date"), ("len", 64, "Length"), ("kills", 90, "Kills"), ("used", 230, "Used"),
                        ("open", 74, ""), ("trash", 40, "")):
            self.ctree.column(c, width=w, minwidth=(56 if c not in ("open", "trash") else 36 if c == "trash" else 64), stretch=(c == "#0"),
                              anchor="center" if c in ("open", "trash") else "w")
            self.ctree.heading(c, text=t)
        self.make_sortable(self.ctree, self.apply_filter, {"#0": "Clip", "date": "Date", "len": "Length", "kills": "Kills",
                                                           "used": "Used"})
        self.ctree.bind("<Button-1>", self.on_tree_click)
        self.ctree.bind("<Double-1>", self.on_tree_double)
        s2 = ttk.LabelFrame(mid, text="Step 2: choose the song (newest added first)", padding=4)
        mid.add(s1, minsize=int(180 * UI_SCALE[0]), stretch="always", padx=2, pady=2)
        mid.add(s2, minsize=int(84 * UI_SCALE[0]), stretch="never", padx=2, pady=2)
        r2 = ttk.Frame(s2)
        r2.pack(fill="x", pady=2)
        ttk.Label(r2, text="Search").pack(side="left")
        self.m_search = tk.StringVar()
        self.m_search.trace_add("write", lambda *a: self.refresh_songs())
        ttk.Entry(r2, textvariable=self.m_search, width=30).pack(side="left", padx=4)
        self.btn(r2, "Play selected song", self.play_song).pack(side="left", padx=8)
        self.btn(r2, "Song map", self.map_song, name="Song map (Manual)").pack(side="left")
        fr2, self.stree = make_tree(s2, ("bpm", "added"), height=2, selectmode="browse")
        fr2.pack(fill="both", expand=True)
        self.stree.column("#0", width=520)
        self.stree.column("bpm", width=70)
        self.stree.column("added", width=110)
        self.stree.heading("#0", text="Song")
        self.stree.heading("bpm", text="BPM")
        self.stree.heading("added", text="Added")
        self.make_sortable(self.stree, self.refresh_songs, {"#0": "Song", "bpm": "BPM", "added": "Added"})
        self.stree.bind("<<TreeviewSelect>>", lambda e: self.update_status())

    DATE_ITEMS = tuple(DATES)

    def fill_more(self):
        """Items of the 'More filters & actions' dropdown (a tick marks the active filter)."""
        def mark(on, text):
            return ("\u2713 " if on else "    ") + text
        items = [mark(self.m_date.get() == d, f"Date: {d}") for d in self.DATE_ITEMS]
        rng = bool(self.m_from.get().strip() or self.m_to.get().strip())
        items.append(mark(rng, "Date range..."))
        if rng:
            items.append("    Clear date range")
        items += [mark(self.m_folder.get() == fo, f"Folder: {fo}") for fo in self.folder_names]
        items += ["    Tick whole folder", "    Exclude ticked from montages"]
        self.b_more.configure(values=items)

    def more_selected(self, _e=None):
        """A dropdown item was chosen: run the action / set the filter, then show the plain label again (the list closes by itself)."""
        item = self.b_more.get().strip().lstrip("\u2713").strip()
        self.m_more.set(MORE_LABEL)
        self.b_more.selection_clear()
        self.root.focus_set()
        self.more_pick(item)

    def more_pick(self, item):
        if item.startswith("Date: "):
            self.m_date.set(item[6:])
            self.apply_filter()
        elif item.startswith("Folder: "):
            self.m_folder.set(item[8:])
            self.apply_filter()
        elif item == "Date range...":
            self.date_range_dialog()
        elif item == "Clear date range":
            self.m_from.set("")
            self.m_to.set("")
        elif item == "Tick whole folder":
            self.tick("folder")
        elif item == "Exclude ticked from montages":
            self.exclude_sel()

    def date_range_dialog(self):
        """Small window for the custom date range (From / to, YYYY-MM-DD)."""
        win = self.reg(tk.Toplevel(self.root), "window")
        win.withdraw()
        win.title("Date range")
        win.transient(self.root)
        win.configure(bg=self.pal["bg"])
        fr = ttk.Frame(win, padding=14)
        fr.pack(fill="both", expand=True)
        va, vb = tk.StringVar(value=self.m_from.get()), tk.StringVar(value=self.m_to.get())
        ttk.Label(fr, text="From").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Entry(fr, textvariable=va, width=14).grid(row=0, column=1, pady=6)
        ttk.Label(fr, text="To").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        ttk.Entry(fr, textvariable=vb, width=14).grid(row=1, column=1, pady=6)
        ttk.Label(fr, text="Format: YYYY-MM-DD", style="Dim.TLabel").grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 6))

        def ok():
            self.m_from.set(va.get().strip())
            self.m_to.set(vb.get().strip())
            win.destroy()
        bb = ttk.Frame(fr)
        bb.grid(row=3, column=0, columnspan=2, sticky="e", pady=(8, 0))
        ttk.Button(bb, text="Cancel", command=win.destroy).pack(side="left", padx=(0, 8))
        ttk.Button(bb, text="Apply", style="Accent.TButton", command=ok).pack(side="left")
        self.reveal(win)

    OPEN_COL = "#5"                                        # the "▶ Open" column
    TRASH_COL = "#6"                                       # V6.7.4: the Recycle Bin column (last)
    USED_COL = "#4"                                        # the Used column (V6.7.4: title of the montage the clip was used in)
    TRASH_GLYPH = "\U0001F5D1"

    def unflag_all(self):
        """V6.5.1: every used flag (Valorant and CS2) is cleared after a Yes; a dated backup of the flags file is written first."""
        n = len(used_dates())
        if not n:
            out("no used clips to unflag")
            return
        if not messagebox.askyesno("Unflag all", f"Unflag all {n} used clips (Valorant and CS2)?"):
            return
        try:
            bk = backup_used_flags()
            n = unflag_clips()
        except Exception as ex:
            out(f"Unflag all failed: {ex}")
            return
        for c in self.clips:
            c["used"] = c["used_label"] = ""
        self.apply_filter()
        out(f"unflagged {n} clips (backup: {bk})")

    def unflag_one(self, iid):
        c = self.byp.get(iid)
        if not c:
            return
        if not c.get("used"):                              # V6.5.2: an empty Used cell flags the clip (today, like a finished render)
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            try:
                mark_used([iid], today)
            except Exception as ex:
                out(f"Flag failed: {ex}")
                return
            c["used"], c["used_label"] = today, HAND_LABEL
            if self.ctree.exists(iid):
                self.ctree.set(iid, "used", HAND_LABEL)
            getattr(self, "_fill_sig", {}).pop(self.ctree, None)     # the cell changed by hand: the next refill must not be skipped as "same data"
            out(f"flagged {c.get('name') or Path(iid).name}")
            return
        try:
            unflag_clips([iid])
        except Exception as ex:
            out(f"Unflag failed: {ex}")
            return
        c["used"] = c["used_label"] = ""
        if self.ctree.exists(iid):
            self.ctree.set(iid, "used", "")
        getattr(self, "_fill_sig", {}).pop(self.ctree, None)
        out(f"unflagged {c.get('name') or Path(iid).name}")

    def trash_clip(self, iid):
        """V6.7.4: the trash cell: after a Yes the clip file goes to the Recycle Bin (never a permanent delete); the row, its scan-cache
        entries and its used flag go with it. Refused while a scan or render runs; on failure the error is shown and the row stays."""
        c = self.byp.get(iid)
        if not c:
            return
        name = c.get("name") or Path(iid).name
        if self.busy or getattr(self, "est_running", False) or getattr(self, "scan_active", False):
            self.status_flash("Busy (scan or render running) - try again when it is done")
            out(f"not moved to the Recycle Bin (a scan or render is running): {name}")
            return
        if not messagebox.askyesno("Recycle Bin", f"Move {name} to the Recycle Bin?"):
            return
        try:
            fk = file_key(iid)                             # the cache key needs the file's size / time: taken before it moves
        except OSError:
            fk = None
        try:
            trash_file(iid)
        except Exception as ex:
            out(f"Recycle Bin failed for {name}: {ex}")
            messagebox.showerror("Recycle Bin", f"Could not move {name} to the Recycle Bin:\n{ex}")
            return
        try:
            forget_clip(iid, fk)
        except Exception as ex:
            out(f"clip moved, but its cache entries were not all cleared: {ex}")
        self.clips = [x for x in self.clips if x["path"] != iid]
        self.byp.pop(iid, None)
        self.ticked.discard(iid)
        if self.last_click == iid:
            self.last_click = None
        getattr(self, "_fill_sig", {}).pop(self.ctree, None)
        self.apply_filter()
        out(f"moved to Recycle Bin: {name}")

    def open_clip_player(self, path):
        """Opens a clip in the default video player without waiting (Windows: os.startfile, Linux: xdg-open)."""
        try:
            if not os.path.exists(path):
                self.status_flash("Clip not found: " + Path(path).name)
            elif os.name == "nt":
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception as ex:
            self.status_flash(f"Could not open the clip: {ex}")

    def on_tree_double(self, e):
        if self.ctree.identify_region(e.x, e.y) in ("heading", "separator"):
            return None
        iid = self.ctree.identify_row(e.y)
        if iid and self.ctree.identify_column(e.x) == self.TRASH_COL:
            return "break"                                 # the trash cell never opens the clip
        if iid:
            self.open_clip_player(iid)
        return "break"

    def on_tree_click(self, e):
        if self.ctree.identify_region(e.x, e.y) in ("heading", "separator"):
            return None                                    # header click = sort
        iid = self.ctree.identify_row(e.y)
        if iid and self.ctree.identify_column(e.x) == self.USED_COL:
            self.unflag_one(iid)                           # the Used cell never ticks or unticks the row
            return "break"
        if iid and self.ctree.identify_column(e.x) == self.OPEN_COL:
            self.open_clip_player(iid)                     # the Open cell never ticks or unticks the row
            return "break"
        if iid and self.ctree.identify_column(e.x) == self.TRASH_COL:
            self.trash_clip(iid)                           # V6.7.4: the trash cell never ticks or unticks the row
            return "break"
        if iid:
            if (e.state & 0x1) and self.last_click and self.ctree.exists(self.last_click):
                vis = list(self.ctree.get_children())
                lo, hi = sorted((vis.index(self.last_click), vis.index(iid)))
                for x in vis[lo:hi + 1]:
                    self.ticked.add(x)
                    self.ctree.item(x, text=self.row_text(x))
            else:
                self.ticked.symmetric_difference_update({iid})
                self.ctree.item(iid, text=self.row_text(iid))
            self.last_click = iid
            self.update_status()
        return "break"

    def row_text(self, iid):
        c = self.byp.get(iid)
        return ("\u2611 " if iid in self.ticked else "\u2610 ") + (c["name"] if c else Path(iid).name)

    def tick(self, how):
        vis = list(self.ctree.get_children())
        if how == "newest":
            try:
                vis = vis[:max(1, int(self.m_n.get()))]
            except ValueError:
                vis = vis[:15]
        if how == "folder":
            fo = self.m_folder.get()
            if fo == "All folders" and self.last_click in self.byp:
                fo = self.byp[self.last_click]["folder"]
            vis = [c["path"] for c in self.clips if c["folder"] == fo]
            if not vis:
                messagebox.showinfo("Tick whole folder", "Pick a folder in the Folder box, or click a clip first.")
                return
        for iid in vis:
            c = self.byp.get(iid)
            if how in ("all", "newest", "folder") or (how == "kills" and c and c["kills"]):
                self.ticked.add(iid)
            elif how == "none":
                self.ticked.discard(iid)
        for iid in self.ctree.get_children():
            self.ctree.item(iid, text=self.row_text(iid))
        if how == "none":
            self.ticked.clear()
        self.update_status()
        self._result = "Unticked all" if how == "none" else f"Ticked {len(self.ticked)} clips"

    def load_clips(self):
        _t0 = time.perf_counter()
        cfg = load_config()
        with pstage("load_clips: missing_packages + ensure_bars"):
            if missing_packages() == [] and shutil.which("ffmpeg"):
                ensure_bars(cfg)
        g = self._snap.get("m_game", "valorant")                   # V6.1.2: snapshot taken on the UI thread by run_task
        with pstage("load_clips: Detector creation (load_dets)"):
            det = load_dets(g).get(g)
        with pstage("load_clips: read kills cache"):
            kc = load_kills_cache()
        with pstage("load_clips: used_dates"):
            ud = used_info()                                       # V5.55 / V6.7.4: (date, montage title) of the montage each clip was used in
        rows = []
        with pstage("load_clips: scan_clips (total)"):
            scanned = scan_clips(load_config())
        _t1 = time.perf_counter()
        for r in scanned:
            if r.get("error") or r.get("game") != g:
                continue
            e = kc.get(kills_key(r, g, det)) if det else None
            ks = None
            if e and not e.get("error"):
                ks = [k["t"] for k in analyse_clip_entry(r, e, cfg, g)["kills"]]
            try:
                mt = os.path.getmtime(r["path"])
            except OSError:
                continue
            rows.append({"path": r["path"], "name": Path(r["path"]).name, "folder": clip_folder(r["path"], cfg), "mtime": mt,
                         "dur": r.get("dur", 0), "kills": None if ks is None else len(ks), "ks": ks or [],
                         "used": ud.get(_pkey(r["path"]), ("", ""))[0], "used_label": ud.get(_pkey(r["path"]), ("", ""))[1]})
        rows.sort(key=lambda c: -c["mtime"])
        if PERF is not None:
            PERF.stages.append(((_t1 - PERF_T0) * 1000, (time.perf_counter() - _t1) * 1000, "load_clips: per-clip rows (kills lookup, compute_kills, getmtime)", threading.current_thread().name))
        with pstage("load_clips: song_pool (cached matches only)"):
            songs, _, _ = song_pool(load_config(), cached_only=True) if load_config().get("mp3_dir") else ([], [], None)
            songs.sort(key=lambda s: s["added"] or datetime.datetime(1970, 1, 1), reverse=True)
        _put = time.perf_counter()

        def fill():
            if PERF is not None:
                PERF.stages.append(((_put - PERF_T0) * 1000, (time.perf_counter() - _put) * 1000, "load_clips: hand-off wait (q.put -> UI poll runs fill)", "MainThread"))
                PERF.stages.append(((_t0 - PERF_T0) * 1000, (time.perf_counter() - _t0) * 1000, "load_clips: TOTAL until fill starts", "MainThread"))
            _f0 = time.perf_counter()
            self.scan_active = False                                # scan finished: the lists are filled exactly once, now
            self.clips, self.songs = rows, songs
            self.byp = {c["path"]: c for c in rows}
            self.ticked &= set(self.byp)
            self.folder_names = ["All folders"] + sorted({c["folder"] for c in rows})
            self.apply_filter()
            self.refresh_songs()
            self._clips_filled = True                               # V6.1.2: the first show waits for this, not for the song matcher
            if SONG_STATE[0] in ("none", "stale") and load_config().get("mp3_dir") and not getattr(self, "_matched_once", False):
                self.m_info.set("Matching songs...")
            if PERF is not None:
                PERF.stage("load_clips: fill() on UI thread (apply_filter + refresh_songs)", _f0)
        self.q.put(("call", fill))

    def csearch_changed(self):
        """V6.8: the search box filters live (a short pause after the last key, so typing stays smooth)."""
        if getattr(self, "_cs_after", None):
            self.root.after_cancel(self._cs_after)
        self._cs_after = self.root.after(120, self.apply_filter)

    def apply_filter(self):
        self._cs_after = None
        words = self.m_csearch.get().lower().split()
        fo, days = self.m_folder.get(), self.DATES.get(self.m_date.get())
        lim = time.time() - days * 86400 if days else 0
        hi = 9e18

        def pd(v, end=False):
            try:
                return time.mktime(time.strptime(v.strip(), "%Y-%m-%d")) + (86400 if end else 0)
            except ValueError:
                return None
        lo2, hi2 = pd(self.m_from.get()), pd(self.m_to.get(), True)
        lim = max(lim, lo2 or 0)
        hi = hi2 or hi
        rows = []
        for c in self.clips:
            if (fo != "All folders" and c["folder"] != fo) or c["mtime"] < lim or c["mtime"] > hi:
                continue
            uf = self.m_used.get()
            if (uf == "Used" and not c.get("used")) or (uf == "Unused" and c.get("used")):
                continue
            if words:                                               # V6.8: every word must be in the file name, date, montage title or folder
                hay = f"{c['name']} {time.strftime('%Y-%m-%d', time.localtime(c['mtime']))} {c.get('used_label') or ''} {c.get('used') or ''} {c['folder']}".lower()
                if not all(w in hay for w in words):
                    continue
            rows.append((c["path"], self.row_text(c["path"]),
                         (time.strftime("%Y-%m-%d", time.localtime(c["mtime"])), f"{int(c['dur'] // 60)}:{int(c['dur'] % 60):02d}",
                          "not scanned" if c["kills"] is None else str(c["kills"]), c.get("used_label") or c.get("used", ""), "\u25b6 Open",
                          self.TRASH_GLYPH)))
        self.fill_chunked(self.ctree, self.sorted_rows(self.ctree, rows))
        self.update_status()

    # ------------------------------------------------------------ column sorting (click a header; click again to reverse)
    def sort_key(self, tree, col, row):
        iid, text, vals = row
        cols = list(tree["columns"])
        v = text if col == "#0" else (vals[cols.index(col)] if cols.index(col) < len(vals) else "")
        v = str(v).strip()
        if col == "#0":
            return (1, 0.0, v.lstrip("\u2610\u2611\u2605 ").lower())
        if col == "used" and tree is getattr(self, "ctree", None):       # V6.7.4: the cell shows a title; the order is by date
            d = (getattr(self, "byp", {}).get(iid) or {}).get("used", "")
            return (1, 0.0, f"{d} {v.lower()}") if d else (-1, 0.0, "")
        m = re.fullmatch(r"(\d+):(\d\d)", v)
        if m:
            return (0, int(m.group(1)) * 60 + int(m.group(2)), "")
        try:
            return (0, float(v), "")
        except ValueError:
            return (1, 0.0, v.lower()) if v and v != "not scanned" else (-1, 0.0, "")

    def sorted_rows(self, tree, rows):
        st = self.sorts.get(str(tree))
        if not st:
            return rows
        col, desc = st
        pinned = [r for r in rows if r[0] == "auto"]
        rest = sorted([r for r in rows if r[0] != "auto"], key=lambda r: self.sort_key(tree, col, r), reverse=desc)
        return pinned + rest

    def make_sortable(self, tree, refill, labels):
        self.sort_refill[str(tree)] = refill
        self.sort_labels[str(tree)] = dict(labels)
        for c in labels:
            tree.heading(c, command=lambda c=c, tree=tree: self.sort_by(tree, c))

    def sort_by(self, tree, col):
        cur = self.sorts.get(str(tree))
        desc = (not cur[1]) if cur and cur[0] == col else col in ("date", "kills", "bpm", "added", "score", "len")
        self.sorts[str(tree)] = (col, desc)
        for c, lab in self.sort_labels[str(tree)].items():
            tree.heading(c, text=lab + ((" \u25bc" if desc else " \u25b2") if c == col else ""))
        self.sort_refill[str(tree)]()

    def refresh_songs(self):
        q = self.m_search.get().strip().lower()
        rows = [("auto", "★ Auto pick (this week's best fit)", ("", ""))]
        for s in self.songs:
            if q and q not in f"{s['artist']} {s['title']}".lower():
                continue
            rows.append((s["path"], f"{s['title']}  -  {s['artist']}" if s["artist"] else s["title"],
                         (self.song_bpm(s), s["added"].strftime("%Y-%m-%d") if s["added"] else "")))
        rows = self.sorted_rows(self.stree, rows)
        if getattr(self, "_fill_sig", {}).get(self.stree) == rows and self._fill_token.get(self.stree) is not None:
            return                                                  # V6.1: same data as the list shows: no refill, no selection reset
        keep = self.stree.selection()
        self.fill_chunked(self.stree, rows)
        self.root.after(50, lambda: self.stree.selection_set(keep[0]) if keep and self.stree.exists(keep[0]) else self.stree.selection_set("auto") if self.stree.exists("auto") else None)

    def song_bpm(self, s):
        """BPM shown in the song list: the CSV 'Tempo' immediately; librosa only for songs the CSV has no tempo for."""
        if s.get("csv_bpm"):
            return f"{float(s['csv_bpm']):.0f}"
        b = self.bpm.get(s["path"])
        return f"{float(b):.0f}" if b else ""

    def bpm_worker(self):
        """Quietly analyses the newest songs WITHOUT a CSV tempo (cached) so a BPM shows for them too; waits while a job runs."""
        for _ in range(600):
            if self.songs:
                break
            time.sleep(1)
        sc = load_json(SONG_CACHE, {})
        for s in [x for x in list(self.songs) if not x.get("csv_bpm")][:40]:
            while self.busy:
                time.sleep(2)
            try:
                key = file_key(s["path"]) + SONG_ALGO + f"|{round(s.get('csv_bpm') or 0)}"
                an = sc.get(key) or analyse_song(s["path"], s.get("csv_bpm"))
                self.bpm[s["path"]] = an["bpm"]
                self.q.put(("call", lambda p=s["path"], b=an["bpm"]: self.stree.exists(p) and self.stree.set(p, "bpm", f"{float(b):.0f}")))
            except Exception:
                pass

    def play_song(self):
        sel = self.stree.selection()
        if sel and sel[0] != "auto":
            self.open_path(sel[0])

    def exclude_sel(self):
        with open(DATA / "exclude.txt", "a", encoding="utf-8") as f:
            for p in self.ticked:
                f.write(p + "\n")
        out(f"Excluded {len(self.ticked)} clip(s) from montages (montage_data\\exclude.txt, one path per line)")

    def fit_status(self, *_):
        """V6.1.5: the Manual status is exactly one line: the short text is cut with an ellipsis to the width the label has."""
        try:
            import tkinter.font as tkfont
            full = self.m_status.get().replace("\n", " ")
            w = self.m_status_lbl.winfo_width() - 8
            if w > 40:
                f = tkfont.Font(root=self.root, font=self.m_status_lbl.cget("font"))
                if f.measure(full) > w:
                    lo, hi = 0, len(full)
                    while lo < hi:                                 # longest prefix that fits together with the ellipsis
                        mid = (lo + hi + 1) // 2
                        if f.measure(full[:mid].rstrip() + "\u2026") <= w:
                            lo = mid
                        else:
                            hi = mid - 1
                    full = full[:lo].rstrip() + "\u2026"
            if self.m_status_disp.get() != full:
                self.m_status_disp.set(full)
        except tk.TclError:
            pass

    def log_summary(self, head, msg=None):
        """V6.1.5: the full Manual summary (clips that didn't fit, clips that can't form a take and why, song section, usable events) as
        normal log lines each time it changes; an identical summary is not written twice in a row."""
        full = head if not msg else f"{head}, {msg}"
        if full == getattr(self, "_last_summary", None):
            return
        self._last_summary = full
        parts = re.split(r"  \|  |; (?=\d+ can't form|fixed length)", msg) if msg else []
        out("Manual: " + head)
        for p_ in parts:
            out("   " + p_)

    def update_status(self):
        """Status line. The length comes from the REAL planner (make_plan on the already-scanned ticked clips, same song, style
        and seed as the render), run quietly in the background after a short pause, so the estimate is the plan."""
        tk_ = [self.byp[p] for p in self.ticked if p in getattr(self, "byp", {})]
        self.m_cshown.set(f"{len(tk_)} ticked, {len(self.ctree.get_children())} shown")      # V6.8: ticks count hidden rows too
        kills = sum(c["kills"] or 0 for c in tk_)
        uns = sum(1 for c in tk_ if c["kills"] is None)
        self.m_len_sc.state(["disabled"] if self.m_opt.get() else ["!disabled"])
        sel = self.stree.selection()
        song = "auto pick"
        if sel and sel[0] != "auto":
            s = next((x for x in self.songs if x["path"] == sel[0]), None)
            if s:
                song = f"{s['title']} ({self.song_bpm(s) or '?'} BPM)"
        txt = f"{len(tk_)} clips ticked, {kills} kills found"
        if uns:
            txt += f" ({uns} not scanned yet - they get scanned first; the estimate leaves them out)"
        self.m_head = txt
        short = f"{len(tk_)} clips ticked \u00b7 {kills} kills" + (f" \u00b7 {uns} not scanned" if uns else "")
        self.m_short = short
        self.m_status.set(short + (" \u00b7 estimating ..." if kills else "") + f" \u00b7 song: {song}")
        if not kills:
            self.log_summary(txt + f", song: {song}")
        if getattr(self, "_est_after", None):
            self.root.after_cancel(self._est_after)
            self._est_after = None
        if kills:
            self._est_after = self.root.after(700, self.start_estimate)

    def est_seed(self):
        """The seed the estimate AND the render use (typed seed, else one kept until the next render)."""
        if self.m_seed.get().strip().isdigit():
            return int(self.m_seed.get())
        if not getattr(self, "_est_seed", None):
            self._est_seed = random.randrange(1, 10 ** 6)
        return self._est_seed

    def start_estimate(self):
        self._est_after = None
        if self.busy or getattr(self, "est_running", False):  # never next to a running job: retry shortly
            self._est_after = self.root.after(1500, self.start_estimate)
            return
        paths = [p for p in self.ticked if p in getattr(self, "byp", {}) and self.byp[p]["kills"]]
        if not paths:
            return
        sel = self.stree.selection()
        args = dict(paths=paths, song_path=None if not sel or sel[0] == "auto" else sel[0],
                    target="optimal" if self.m_opt.get() else int(self.m_len.get()), style=self.m_style.get(), seed=self.est_seed())
        game, head, short = self.m_game.get(), self.m_head, getattr(self, "m_short", "")
        self.est_gen = getattr(self, "est_gen", 0) + 1
        gen = self.est_gen
        self.est_running = True

        def go():
            QUIET.on = True
            try:
                plan, _ = make_plan(load_config(), game, scan=False, **args)
                msg = self.estimate_text(plan, len(paths))
                sg_ = plan["song"]
                msg_short = f"montage {plan['duration']:.0f} s \u00b7 song: {sg_['title'] or Path(sg_['path']).stem} \u00b7 {plan['recipe']}"
            except Exception as ex:
                msg = f"cannot plan yet: {ex}"
                msg_short = "cannot plan yet (see log)"
            finally:
                QUIET.on = False

            def show():
                self.est_running = False
                if gen == self.est_gen:
                    self.m_status.set(f"{short} \u00b7 {msg_short}")
                    self.log_summary(head, msg)
                if self.pending and not self.busy:
                    n, fn, a = self.pending.pop(0)
                    self.run_task(n, fn, *a)
            self.q.put(("call", show))
        threading.Thread(target=go, daemon=True).start()

    @staticmethod
    def estimate_text(plan, n_clips):
        fit, sg = plan.get("fit", {}), plan["song"]
        used = len({p["path"] for t in plan["takes"] for p in (t.get("srcs") or [t])})
        txt = (f"montage {plan['duration']:.0f} s from {used} of {n_clips} clips ({fit.get('usable', '?')} usable events, "
               f"song section {sg['section_s']:.0f} s), song: {sg['title'] or Path(sg['path']).stem}, style: {plan['recipe']}")
        if fit.get("song_short") and fit.get("optimal"):
            txt = (f"{len(fit['song_short'])} ticked clips didn't fit in this song: " + ", ".join(fit["song_short"][:4]) +
                   (" ..." if len(fit["song_short"]) > 4 else "") + "  |  " + txt)
        elif fit.get("song_short"):
            txt = (f"song too short: fits {fit['used']} of {fit['usable']} clips; pick a longer song or untick some  |  " + txt)
        if fit.get("left_out"):
            txt += f"; fixed length leaves out {len(fit['left_out'])}: " + ", ".join(fit["left_out"][:4]) + \
                   (" ..." if len(fit["left_out"]) > 4 else "")
        if fit.get("skipped"):
            txt += f"; {len(fit['skipped'])} can't form a take: " + ", ".join(f"{a} ({b})" for a, b in fit["skipped"][:3]) + \
                   (" ..." if len(fit["skipped"]) > 3 else "")
        return txt

    def pick_count(self):
        """N from the number box next to 'Random pick' (its own box, never the 'Tick newest' one); None = empty / not a number
        (then the Optimal estimate decides)."""
        t = self.m_rand_n.get().strip()
        if not t:
            return None
        try:
            return max(1, int(float(t)))
        except ValueError:
            out(f"Random pick: '{t}' is not a number, using the Optimal estimate")
            return None

    def random_pick_ticks(self):
        """V5.57 Random pick: tick exactly N random clips from the list as shown (game, folder / date / used filters; unused clips
        unless 'Include used clips'). N = its own number box (never the 'Tick newest' box). Fewer eligible than N: tick all of them and
        say so in the status line. Empty box: the Optimal estimate decides how many (V5.55)."""
        inc = self.m_incl_used.get()
        cands = [self.byp[i] for i in self.ctree.get_children()
                 if i in self.byp and self.byp[i].get("kills") and (inc or not self.byp[i].get("used"))]
        if not cands:
            messagebox.showinfo("Random pick", "No " + ("" if inc else "unused ") + "clips with kills in the list "
                                "(the game, folder and date filters apply; tick 'Include used clips' to allow used ones).")
            return
        n = self.pick_count()
        sel = self.stree.selection()
        song = next((x for x in self.songs if sel and x["path"] == sel[0]), None)
        style = self.m_style.get()

        def work():
            if n:
                paths = [c["path"] for c in random.sample(cands, min(n, len(cands)))]
                why = f"you asked for {n}" if n <= len(cands) else f"you asked for {n}, only {len(cands)} eligible, so all were ticked"
            else:
                an = None
                if song:
                    try:
                        an = get_songmap(song["path"], song.get("csv_bpm"))
                    except Exception as ex:
                        out(f"Random pick: song map unavailable ({ex}), sizing for a plain 120 BPM song")
                paths, fit = random_pick(cands, an, style)
                why = fit["why"] if fit else ""
            msg = f"Random pick: {len(paths)} of {len(cands)} {'' if inc else 'unused '}clips ticked ({why})"

            def apply():
                self.ticked = set(paths)
                for iid in self.ctree.get_children():
                    self.ctree.item(iid, text=self.row_text(iid))
                self.update_status()
                self.status_flash(msg, 4000)
            out(msg)
            self.q.put(("call", apply))
        self.run_task("random pick", work)

    def manual(self, mode):
        paths = list(self.ticked)
        if not paths:
            messagebox.showinfo("Manual", "Tick some clips first (Step 1).")
            return
        sel = self.stree.selection()
        song = None if not sel or sel[0] == "auto" else sel[0]
        seed = self.est_seed()                                     # the same plan the status line showed
        self._est_seed = None
        style = self.m_style.get()
        self.run_task("manual " + mode, self.job_video(
            self.m_game.get(), mode=mode, force=True, paths=paths, song_path=song,
            target="optimal" if self.m_opt.get() else int(self.m_len.get()), style=style, seed=seed, maxq=(self.m_q.get() == "max")))

    # ------------------------------------------------------------ Songs tab
    def build_songs(self):
        f = self.tabs["Songs"]
        ttk.Label(f, text="Which MP3 was matched to which playlist track (one-to-one). Rows under 85 are flagged - fix them with Change match. "
                          "Also saved as montage_data\\song_matches.csv.", wraplength=1100).pack(anchor="w", pady=4)
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=4)
        self.btn(bar, "Refresh", lambda: self.run_task("matches", self.load_matches)).pack(side="left", padx=3)
        self.btn(bar, "Change match for selected file...", self.change_match).pack(side="left", padx=3)
        self.btn(bar, "Play selected file", self.play_match).pack(side="left", padx=3)
        self.btn(bar, "Open song_matches.csv", lambda: self.open_path(DATA / "song_matches.csv")).pack(side="left", padx=3)
        self.btn(bar, "Song map of selected file...", self.map_match).pack(side="left", padx=3)
        self.m_info = tk.StringVar(value="")
        ttk.Label(f, textvariable=self.m_info).pack(anchor="w")
        fr, self.mtree = make_tree(f, ("track", "artist", "bpm", "score", "flag"), height=18, selectmode="browse")
        fr.pack(fill="both", expand=True)
        for c, w, t in (("#0", 420, "MP3 file"), ("track", 300, "Matched playlist track"), ("artist", 200, "Artist"),
                        ("bpm", 60, "BPM"), ("score", 70, "Score"), ("flag", 130, "Flag")):
            self.mtree.column(c, width=w, minwidth=50, stretch=(c in ("#0", "track")))
            self.mtree.heading(c, text=t)
        self.make_sortable(self.mtree, self.fill_matches, {"#0": "MP3 file", "track": "Matched playlist track", "artist": "Artist",
                                                            "bpm": "BPM", "score": "Score", "flag": "Flag"})
        self.mtree.tag_configure("weak", foreground="#ffc65c")
        self.mtree.tag_configure("none", foreground="#ff8a80")
        self.match_rows, self.match_audio = [], []

    def load_matches(self):
        cfg = load_config()
        with pstage("load_matches: scan_audio"):
            audio = scan_audio(cfg)
        with pstage("load_matches: read_playlist"):
            csvp, rows, col = read_playlist(cfg)
        with pstage("load_matches: match_playlist (cached / incremental)"):
            matched, unmatched, _st = match_cached(cfg, csvp, rows, audio) if rows and audio else ([], rows, "none")
        with pstage("load_matches: write_song_matches"):
            write_song_matches(audio, matched)
        by = {a["path"]: (r, sc) for r, a, sc in matched}
        items = []
        for a in sorted(audio, key=lambda a: a["path"].lower()):
            r, sc = by.get(a["path"], (None, 0))
            items.append((a["path"], Path(a["path"]).name, r["title"] if r else "", r["artist"] if r else "", sc,
                          match_flag(a["path"], r, sc),
                          f"{r['tempo']:.0f}" if r and r.get("tempo") else ""))
        weak = sum(1 for i in items if i[5] != "ok")
        songs = None
        if rows and cfg.get("mp3_dir"):
            with pstage("load_matches: song_pool (cache hit)"):
                songs = sorted(song_pool(cfg)[0], key=lambda s: s["added"] or datetime.datetime(1970, 1, 1), reverse=True)

        def fill():
            _f0 = time.perf_counter()
            self._matched_once = True
            if songs is not None and [(x["path"], x["title"], x["artist"]) for x in songs] != [(x["path"], x["title"], x["artist"]) for x in self.songs]:
                self.songs = songs                                  # V6.1.2: the new match result is applied once, in one batch
                self.refresh_songs()
            self.match_rows, self.match_audio, self.match_items = rows, audio, items
            self.fill_matches()
            self.m_info.set(f"{len(audio)} MP3 files, {len(rows)} playlist tracks, {len(matched)} matched, {weak} to check, {len(unmatched)} playlist tracks without a file")
            if PERF is not None:
                PERF.stage("load_matches: fill() on UI thread", _f0)
        self.q.put(("call", fill))

    def fill_matches(self):
        items = getattr(self, "match_items", [])
        rows = self.sorted_rows(self.mtree, [(pth, nm, (tr, ar, bpm, sc, fl)) for pth, nm, tr, ar, sc, fl, bpm in items])
        self.mtree.delete(*self.mtree.get_children())
        for pth, nm, vals in rows:
            fl = vals[4]
            self.mtree.insert("", "end", iid=pth, text=nm, values=vals, tags=("none" if fl == "NO MATCH" else "weak" if fl != "ok" else "",))

    def map_song(self):
        sel = self.stree.selection()
        if not sel or sel[0] == "auto":
            messagebox.showinfo("Song map", "Select a song in the list first.")
            return
        s = next((x for x in self.songs if x["path"] == sel[0]), {})
        return SongMapView(self, sel[0], s.get("csv_bpm"))

    def map_match(self):
        sel = self.mtree.selection()
        if not sel:
            messagebox.showinfo("Song map", "Select a file first (press Refresh if the list is empty).")
            return
        item = next((i for i in getattr(self, "match_items", []) if i[0] == sel[0]), None)
        bpm = None
        if item and item[2]:
            r = next((r for r in self.match_rows if r["title"] == item[2] and r["artist"] == item[3]), None)
            bpm = r.get("tempo") if r else None
        return SongMapView(self, sel[0], bpm or None)

    def play_match(self):
        sel = self.mtree.selection()
        if sel:
            self.open_path(sel[0])

    def change_match(self):
        sel = self.mtree.selection()
        if not sel or not self.match_rows:
            messagebox.showinfo("Songs", "Press Refresh, then select a file.")
            return
        path = sel[0]
        w = self.reg(tk.Toplevel(self.root), "window")
        w.withdraw()
        w.title("Pick the playlist track for " + Path(path).name)
        w.geometry("640x520")
        q = tk.StringVar(value=clean(Path(path).stem))
        ttk.Entry(w, textvariable=q).pack(fill="x", padx=8, pady=6)
        fr, tr = make_tree(w, ("artist",), height=18, selectmode="browse")
        fr.pack(fill="both", expand=True, padx=8)
        tr.column("#0", width=380)
        tr.heading("#0", text="Playlist track")
        tr.heading("artist", text="Artist")
        rk = lambda r: r.get("uri") or f"{r['artist']} - {r['title']}"

        def refill(*a):
            tr.delete(*tr.get_children())
            qq = q.get().lower().strip()
            for i, r in enumerate(self.match_rows):
                if not qq or qq in (r["title"] + " " + r["artist"]).lower():
                    tr.insert("", "end", iid=str(i), text=r["title"], values=(r["artist"],))
        q.trace_add("write", refill)
        refill()

        def ok():
            if tr.selection():
                cfg = load_config()
                cfg.setdefault("song_overrides", {})[path] = rk(self.match_rows[int(tr.selection()[0])])
                save_json(CONFIG_PATH, cfg)
                w.destroy()
                self.run_task("matches", self.load_matches)
        ttk.Button(w, text="Use this track", command=ok).pack(pady=8)
        self.reveal(w)

    # ------------------------------------------------------------ Troubleshoot tab
    def build_trouble(self):
        f = self.tabs["Troubleshoot"]
        r1 = ttk.LabelFrame(f, text="Checks and tools")
        r1.pack(fill="x", padx=8, pady=4)
        for text, cmd in (("Selfcheck (ffmpeg, NVENC, packages)", lambda: self.run_task("selfcheck", cmd_selfcheck, None)),
                          ("Calibrate killfeed region (optional)...", lambda: CalibDialog(self)),
                          ("Self-test detection", lambda: self.run_task("selftest", selftest_detection, load_config())),
                          ("Scan all clips now", lambda: self.run_task("scan all", run_scan, load_config(), None, None)),
                          ("Open logs", lambda: self.open_path(LOG_DIR)),
                          ("Clear kill cache", self.clear_cache)):
            if text == "Scan all clips now" or text.startswith("Selfcheck"):
                rowf = ttk.Frame(r1)
                rowf.pack(fill="x")
            self.btn(rowf, text, cmd).pack(side="left", padx=4, pady=3)
        r2 = ttk.LabelFrame(f, text="Black bars (measured once, fixed crop)")
        r2.pack(fill="x", padx=8, pady=4)
        self.bar_var = tk.StringVar()
        ttk.Label(r2, textvariable=self.bar_var).pack(anchor="w", padx=6)
        rr = ttk.Frame(r2)
        rr.pack(anchor="w", padx=6, pady=3)
        self.bar_e = [tk.StringVar() for _ in range(4)]
        for lab, v in zip("x y w h".split(), self.bar_e):
            ttk.Label(rr, text=lab).pack(side="left")
            ttk.Entry(rr, textvariable=v, width=6).pack(side="left", padx=2)
        self.btn(rr, "Apply override (selected clip's size)", self.bar_override).pack(side="left", padx=6)
        rr = ttk.Frame(r2)
        rr.pack(anchor="w", padx=6, pady=3)
        self.btn(rr, "Re-measure", lambda: self.run_task("bars", lambda: (ensure_bars(load_config(), True), self.q.put(("call", self.refresh_bar))))).pack(side="left")
        self.btn(rr, "No bars", self.bar_off).pack(side="left", padx=4)
        self.btn(rr, "Before/after preview", self.bar_preview).pack(side="left", padx=4)
        r3 = ttk.LabelFrame(f, text="Clips")
        r3.pack(fill="both", expand=True, padx=8, pady=4)
        top = ttk.Frame(r3)
        top.pack(fill="x")
        self.t_game = tk.StringVar(value="valorant")
        ttk.Combobox(top, textvariable=self.t_game, values=list(GAMES), width=10, state="readonly").pack(side="left", padx=4)
        self.btn(top, "Load clips", lambda: self.run_task("tclips", self.load_tclips)).pack(side="left")
        self.btn(top, "Kill timestamps + killfeed crop", self.show_kills).pack(side="left", padx=6)
        self.btn(top, "Rescan this clip", self.rescan_clip).pack(side="left")
        fr, self.ttree = make_tree(r3, (), height=7, selectmode="browse")
        fr.pack(fill="both", expand=True, pady=4)
        self.refresh_bar()

    def refresh_bar(self):
        b = load_config().get("bar")
        self.bar_var.set(f"Stored crop: source {b['src'][0]}x{b['src'][1]} -> x,y,w,h {b['rect']}" if b else "Stored crop: none (clips used as full frame)")
        if b:
            for v, x in zip(self.bar_e, b["rect"]):
                v.set(str(x))

    def load_tclips(self):
        g = self._snap.get("t_game", "valorant")
        items = [(r["path"], Path(r["path"]).name) for r in scan_clips(load_config()) if not r.get("error") and r.get("game") == g]
        items.sort(key=lambda x: x[1])
        self.q.put(("call", lambda: self.fill_chunked(self.ttree, [(p, n, ()) for p, n in items])))

    def sel_clip(self):
        s = self.ttree.selection()
        if not s:
            messagebox.showinfo("Clips", "Load clips and select one first.")
            return None
        return s[0]

    def show_kills(self):
        p = self.sel_clip()
        if not p:
            return
        g, cfg = self.t_game.get(), load_config()
        det = load_dets(g).get(g)
        if not det:
            out("OCR detector unavailable: Troubleshoot > Selfcheck")
            return
        rec = analyse_clip(p, load_json(CLIPS_CACHE, {}), False, cfg.get("bar"))[1]
        rec["game"] = g
        e = load_kills_cache().get(kills_key(rec, g, det))
        if not e:
            out("Not scanned yet: press Rescan this clip")
            return
        a = analyse_clip_entry(rec, e, cfg, g)
        ks, ds = a["kills"], a["deaths"]
        out(f"{Path(p).name}: {len(ks)} kills (before the gunshot check): " + ", ".join(ts(k['t']) + ("*HS" if k.get("hs") else "") for k in ks) +
            f"; my deaths at {', '.join(ts(d) for d in ds) or '-'}; rows found {a['rows_max']} max/frame, {a['ocr_calls']} OCR calls;"
            f" best FIREAXE match killer-side {a['best_k']:.2f} victim-side {a['best_v']:.2f}")
        for m in a["mine"]:
            out(f"   my row @ {ts(m['t'])} {m['row']} -> {m['verdict'].upper()}: {m['why']} ({m['hits']} sightings)")
        for j in a["rej"]:
            out(f"   rejected @ {ts(j['t'])}: {j['reason']}")
        pick = ks[0] if ks else ({"t": a["mine"][0]["t"]} if a["mine"] else None)
        if pick is None and e.get("ocr"):
            busiest = max(e["ocr"], key=lambda o: len(o[2]))
            pick = {"t": busiest[0] / FPS - 0.3 + e.get("v_off", 0)}
        if pick:
            fr, rows = grab_kill_crop(rec, det, cfg, pick)
            if fr is not None:
                out(f"   crop at {ts(pick['t'])}: {len(rows)} rows")
                for r in rows:
                    out("     " + row_desc(r))
                w = self.reg(tk.Toplevel(self.root), "window")
                w.title("Killfeed crop: green = KILL, red = DEATH, orange = rejected (assist/utility), grey = other rows")
                ph, _ = to_photo(fr, 1100, 700)
                self._imgs.append(ph)
                ttk.Label(w, image=ph).pack()

    def region_prompt(self, held, cur):
        """V6.7.6: called from a scan worker when Valorant clips are held back ('calibration changed'): asks on the UI thread, once per
        distinct set; only a Yes rescans them. The old entries are kept either way."""
        sig = (cur, tuple(sorted(p for p, _s, _c in held)))
        if sig == getattr(self, "_region_asked", None):
            return
        self._region_asked = sig

        def ask():
            if not messagebox.askyesno("Valorant killfeed region", region_hold_text(held, cur) +
                                       f"\n\nRescan these {len(held)} clips now? (No = nothing is rescanned; nothing is deleted.)"):
                out("Valorant rescan declined: the entries stay as they are")
                return

            def job():
                run_scan(load_config(), ["valorant"], [p for p, _s, _c in held], 0, False, True)
                self.q.put(("call", lambda: self.run_task("clips", self.load_clips)))
            self.run_task("rescan region", job)
        self.q.put(("call", ask))

    def rescan_clip(self):
        p = self.sel_clip()
        if not p:
            return

        g = self.t_game.get()

        def job():
            cache = load_kills_cache()
            fk = file_key(p) + "|"
            det = load_dets(g).get(g)
            if g == "valorant" and det:                        # V6.7.6: only the entry under the current region is replaced (after a backup);
                key = kills_key(analyse_clip(p, load_json(CLIPS_CACHE, {}), False, load_config().get("bar"))[1] | {"game": g}, g, det)
                backup_valorant_entry(cache, key)              # entries under other region hashes are kept
                cache._p(key).unlink(missing_ok=True)
            else:
                cache.drop_file("|".join(fk.split("|")[:3]))
            run_scan(load_config(), None, [p])
        self.run_task("rescan", job)

    def bar_override(self):
        p = self.sel_clip()
        if not p:
            return
        info = probe_video(p)
        cfg = load_config()
        cfg["bar"] = {"src": [info["w"], info["h"]], "rect": [int(v.get()) & ~1 for v in self.bar_e]}
        cfg["bar_checked"] = True
        save_json(CONFIG_PATH, cfg)
        out(f"Bar override saved: {cfg['bar']}")
        self.refresh_bar()

    def bar_off(self):
        cfg = load_config()
        cfg["bar"], cfg["bar_checked"] = None, True
        save_json(CONFIG_PATH, cfg)
        self.refresh_bar()

    def bar_preview(self):
        import cv2
        import numpy as np
        p = self.sel_clip()
        if not p:
            return
        cfg = load_config()
        info = probe_video(p)
        before = grab_gray_bgr(p, info["dur"] / 2, info["w"], info["h"])
        rec = analyse_clip(p, {}, True, cfg.get("bar"))[1]
        after, _ = grab_norm_frame(p, info["dur"] / 2, cfg)
        w = self.reg(tk.Toplevel(self.root), "window")
        w.title(f"before (left) / after (right)  bars applied: {rec.get('bars')}")
        ph, _ = to_photo(np.hstack([cv2.resize(before, (640, 360)), cv2.resize(after, (640, 360))]), 1300, 400)
        self._imgs.append(ph)
        ttk.Label(w, image=ph).pack()

    def clear_cache(self):
        if messagebox.askyesno("Clear kill cache", "Delete the kill cache? Every clip will be scanned again (slow)."):
            load_kills_cache().clear_all()
            for pth in (FLICK_CACHE, ONSET_CACHE, SCALES):
                try:
                    pth.unlink()
                except OSError:
                    pass
            out("Kill cache cleared")

    # ------------------------------------------------------------ Settings tab
    def build_settings(self):
        """V5.57 Settings: a fixed footer (Save settings + status) below a scrolled page laid out on one grid: section headers, a fixed
        label column, uniform row padding (6 px vertical, 12 px horizontal), extra space between sections."""
        host = self.tabs["Settings"]
        sc = UI_SCALE[0]
        foot = ttk.Frame(host)
        foot.pack(side="bottom", fill="x")                          # packed first: always visible, outside the scrolled area
        ttk.Separator(foot, orient="horizontal").pack(side="top", fill="x")
        fi = ttk.Frame(foot, padding=(12, 8))
        fi.pack(fill="x")
        self.b_save = self.btn(fi, "Save settings", self.save_settings, style="Accent.TButton")
        self.b_save.pack(side="right")
        self.save_status = tk.StringVar(value="All changes saved")
        self.save_label = ttk.Label(fi, textvariable=self.save_status, style="Dim.TLabel")
        self.save_label.pack(side="right", padx=(0, 12))
        self.btn(fi, "Changelog", self.show_changelog, name="Changelog").pack(side="left")     # always visible, next to Save
        body = ttk.Frame(host)
        body.pack(side="top", fill="both", expand=True)
        self.set_canvas = cv = self.reg(tk.Canvas(body, bg=self.pal["bg"], highlightthickness=0, bd=0), "window")
        vs = ttk.Scrollbar(body, orient="vertical", command=cv.yview)
        hs = ttk.Scrollbar(body, orient="horizontal", command=cv.xview)
        cv.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        vs.pack(side="right", fill="y")
        hs.pack(side="bottom", fill="x")
        cv.pack(side="left", fill="both", expand=True)
        f = self.set_inner = ttk.Frame(cv)
        win = cv.create_window((0, 0), window=f, anchor="nw")
        f.columnconfigure(0, minsize=int(340 * sc))               # fixed label column
        f.columnconfigure(1, weight=1)
        pend = []

        def relayout():
            pend.clear()
            w_ = max(1, cv.winfo_width(), f.winfo_reqwidth())          # never narrower than the content (a squeezed grid unmaps widgets)
            cv.itemconfigure(win, width=w_)
            cv.configure(scrollregion=(0, 0, w_, max(f.winfo_reqheight(), 1)))
            cv.yview_moveto(cv.yview()[0])                           # force a redraw so the embedded frame is mapped again

        def later(_e=None):                                          # debounced: one re-layout ~100 ms after the last resize event
            if not pend:
                pend.append(cv.after(100, relayout))
        cv.bind("<Configure>", later)
        f.bind("<Configure>", later)
        self.set_relayout = relayout
        self.sv, self.sl, self.sn, self.set_track, self.set_names = {}, {}, {}, {}, {}
        r = [0]
        LW = int(300 * sc)
        PX, PY = 12, 6

        def section(title):
            ttk.Label(f, text=title, style="Section.TLabel").grid(row=r[0], column=0, columnspan=3, sticky="w", padx=PX,
                                                                  pady=(6 if r[0] == 0 else 24, 2))
            ttk.Separator(f, orient="horizontal").grid(row=r[0] + 1, column=0, columnspan=3, sticky="ew", padx=PX, pady=(2, 4))
            r[0] += 2

        def label(text):
            ttk.Label(f, text=text, wraplength=LW).grid(row=r[0], column=0, sticky="w", padx=PX, pady=PY)

        def holder():
            """The cell of the current row (column 1) as a frame; its children are packed left with 12 px gaps."""
            h = ttk.Frame(f)
            h.grid(row=r[0], column=1, sticky="w", padx=(0, PX), pady=PY)
            return h

        def hint(parent, text):
            ttk.Label(parent, text=text, style="Dim.TLabel").pack(side="left", padx=(0, 0))

        def folder_row(text, var, btn_text, cmd):
            label(text)
            ttk.Entry(f, textvariable=var, width=12).grid(row=r[0], column=1, sticky="ew", padx=(0, PX), pady=PY)
            ttk.Button(f, text=btn_text, command=cmd, width=10).grid(row=r[0], column=2, padx=(0, PX), pady=PY, sticky="ew")
            r[0] += 1

        section("Folders")
        for k, lab in (("mp3_dir", "MP3 folder"), ("playlist_dir", "Exportify CSV folder"), ("output_root", "Output folder")):
            v = tk.StringVar(value=self.cfg.get(k, ""))
            self.sv[k] = v
            folder_row(lab, v, "Browse", lambda v=v: v.set(filedialog.askdirectory(initialdir=v.get() or None) or v.get()))
        for g, lab in (("valorant", "Valorant clip folders (separated by ;)"), ("cs2", "CS2 clip folders (separated by ;)")):
            v = tk.StringVar(value="; ".join((self.cfg.get("clip_dirs") or {}).get(g, [])))
            self.sl[g] = v
            folder_row(lab, v, "Add folder", lambda v=v: v.set("; ".join([x for x in v.get().split(";") if x.strip()] +
                                                                           [filedialog.askdirectory() or ""]).strip("; ")))
        section("Scanning and detection")
        for k, lab in (("max_mb", "Skip files larger than (MB)"), ("max_dur_s", "Skip clips longer than (s)"),
                       ("auto_recent_days", "Auto: scan new clips from the last (days)"),
                       ("auto_old_per_run", "Auto: plus up to this many older clips per run"),
                       ("name_match", "Detection: fuzzy name match needed (0-100)"),
                       ("death_lock_s", "No kills for this long after my death (s)"),
                       ("week_days", "'This week' means the last N days")):
            label(lab)
            v = tk.StringVar(value=str(self.cfg.get(k, "")))
            self.sn[k] = v
            ttk.Entry(f, textvariable=v, width=10).grid(row=r[0], column=1, sticky="w", padx=(0, PX), pady=PY)
            r[0] += 1
        section("Killfeed region")
        label("Game")
        self.rp_game = tk.StringVar(value="valorant")
        h = holder()
        cbg = ttk.Combobox(h, textvariable=self.rp_game, values=list(GAMES), width=10, state="readonly")
        cbg.pack(side="left", padx=(0, PX))
        cbg.bind("<<ComboboxSelected>>", lambda e: self.rp_refresh())
        hint(h, "applies at once (not part of Save settings); a dated backup of the region file is saved first")
        r[0] += 1
        self.rp_tree = ttk.Treeview(f, columns=("hash", "entries", "first", "last", "region"), height=7, selectmode="browse")
        for c, w_, t_ in (("#0", 190, "Saved region"), ("hash", 100, "Hash"), ("entries", 60, "Entries"), ("first", 120, "Earliest scan"),
                          ("last", 120, "Latest scan"), ("region", 260, "Region")):
            self.rp_tree.column(c, width=int(w_ * sc), minwidth=40, stretch=(c == "#0"), anchor="w")
            self.rp_tree.heading(c, text=t_)
        self.rp_tree.grid(row=r[0], column=0, columnspan=3, sticky="ew", padx=PX, pady=PY)
        self.rp_tree.bind("<<TreeviewSelect>>", lambda e: self.rp_select())
        r[0] += 1
        self.rp_info = tk.StringVar(value="Select a region to see how many cached clips it would keep valid.")
        ttk.Label(f, textvariable=self.rp_info, style="Dim.TLabel", wraplength=int(900 * sc)).grid(row=r[0], column=0, columnspan=3, sticky="w", padx=PX, pady=(0, PY))
        r[0] += 1
        h = holder()
        self.b_rp_use = self.btn(h, "Use this region", self.rp_use, name="region:use")
        self.b_rp_use.pack(side="left", padx=(0, PX))
        self.b_rp_def = self.btn(h, "Set as default", self.rp_set_default, name="region:default")
        self.b_rp_def.pack(side="left", padx=(0, PX))
        self.b_rp_resc = self.btn(h, "Rescan this group to the current region", self.rp_rescan, name="region:rescan")
        self.b_rp_resc.pack(side="left", padx=(0, PX))
        self.btn(h, "Refresh", self.rp_refresh, name="region:refresh").pack(side="left")
        r[0] += 1
        self.rp_rows, self._rp_loaded = {}, False
        self.rp_tree.bind("<Map>", lambda e: None if self._rp_loaded else (setattr(self, "_rp_loaded", True), self.root.after_idle(self.rp_refresh)))   # read the cache index when first shown, not at startup
        section("Game audio")
        label("Game audio level under the music (0-1)")
        v = tk.StringVar(value=str(self.cfg.get("game_audio_level", "")))
        self.sn["game_audio_level"] = v
        ttk.Entry(f, textvariable=v, width=10).grid(row=r[0], column=1, sticky="w", padx=(0, PX), pady=PY)
        r[0] += 1
        for g in GAMES:
            label(f"Game audio track: {GAME_DIR[g]}")
            cur = str((self.cfg.get("game_audio_track") or {}).get(g, "auto"))
            v = tk.StringVar(value=cur if cur in ("auto", "1", "2", "3") else "auto")
            self.set_track[g] = v
            h = holder()
            ttk.Combobox(h, textvariable=v, values=["auto", "1", "2", "3"], width=8, state="readonly").pack(side="left", padx=(0, PX))
            hint(h, "Auto = most gunshots; 1, 2 or 3 = fixed (ignored in Legacy audio mode)")
            r[0] += 1
        section("Player names")
        for g in GAMES:
            label(f"Player names: {GAME_DIR[g]}")
            v = tk.StringVar(value="; ".join(norm_names((self.cfg.get("player_names") or {}).get(g), g)))
            self.set_names[g] = v
            h = holder()
            e_ = ttk.Entry(h, textvariable=v, width=28)
            e_.pack(side="left", padx=(0, PX))
            e_.bind("<FocusOut>", self.names_changed)
            hint(h, "names / aliases separated by ';' (letters = fuzzy match, e.g. CJK = exact text)")
            r[0] += 1
        section("Montage")
        self.set_opt, self.set_len, self.set_style, self.set_q = self.m_opt, self.m_len, self.m_style, self.m_q    # shared with the Manual tab
        label("Default length")
        h = holder()
        ttk.Checkbutton(h, text="Optimal (from clips + song + style)", variable=self.set_opt, command=self.update_status).pack(side="left")
        r[0] += 1
        h = ttk.Frame(f)
        h.grid(row=r[0], column=1, sticky="w", padx=(0, PX), pady=PY)
        ttk.Scale(h, from_=LEN_MIN_S, to=LEN_MAX_S, variable=self.set_len, length=180,
                  command=lambda v: self.set_len.set(int(float(v)))).pack(side="left", padx=(0, PX))
        ttk.Label(h, textvariable=self.set_len, width=4).pack(side="left", padx=(0, 6))
        hint(h, "s (used when Optimal is off)")
        r[0] += 1
        label("Default style (auto = from the song)")
        ttk.Combobox(holder(), textvariable=self.set_style, values=STYLE_CHOICES, width=10, state="readonly").pack(side="left")
        r[0] += 1
        self.set_place = tk.StringVar(value=self.cfg.get("placement", "v5"))
        label("Kill placement (see synccompare)")
        ttk.Combobox(holder(), textvariable=self.set_place, values=["v5", "v4"], width=10, state="readonly").pack(side="left")
        r[0] += 1
        self.set_songmap = tk.StringVar(value=SONGMAP_CHOICES_UI[songmap_version(self.cfg)])
        label("Songmap version")
        ttk.Combobox(holder(), textvariable=self.set_songmap, values=list(SONGMAP_CHOICES_UI.values()), width=28, state="readonly").pack(side="left")
        r[0] += 1
        am = self.cfg.get("audio_mode", "auto")
        self.set_audio = tk.StringVar(value=AUDIO_MODES.get(am, AUDIO_MODES["auto"]))
        label("Audio mode")
        h = holder()
        ttk.Combobox(h, textvariable=self.set_audio, values=list(AUDIO_MODES.values()), width=16, state="readonly").pack(side="left")
        r[0] += 1
        self.set_sync = tk.BooleanVar(value=self.cfg.get("sync_report", True))
        label("Quality")
        h = holder()
        ttk.Radiobutton(h, text="NVENC p7 cq18 (fast)", variable=self.set_q, value="nvenc").pack(side="left", padx=(0, PX))
        ttk.Radiobutton(h, text="Max quality x264 CRF15", variable=self.set_q, value="max").pack(side="left")
        r[0] += 1
        label("Reports")
        ttk.Checkbutton(holder(), text="Print a sync report after each render", variable=self.set_sync).pack(side="left")
        r[0] += 1
        section("Appearance")
        self.set_accent = tk.StringVar(value=ACCENT_NAMES.get(self.cfg.get("accent", "lime"), "Lime green"))
        self.set_base = tk.StringVar(value=str(self.cfg.get("base", "grey")).capitalize())
        label("Accent colour")
        h = holder()
        cb_ = ttk.Combobox(h, textvariable=self.set_accent, values=list(ACCENT_NAMES.values()), width=14, state="readonly")
        cb_.pack(side="left", padx=(0, PX))
        r[0] += 1
        label("Base")
        h = holder()
        cb_ = ttk.Combobox(h, textvariable=self.set_base, values=["Grey", "Black"], width=14, state="readonly")
        cb_.pack(side="left", padx=(0, PX))
        r[0] += 1
        label("UI scale (font + row height)")
        h = holder()
        v = tk.StringVar(value=str(self.cfg.get("ui_scale", 1.0)))
        self.sn["ui_scale"] = v
        ttk.Entry(h, textvariable=v, width=10).pack(side="left", padx=(0, PX))
        hint(h, "Applies after restart")
        r[0] += 1
        section("General")
        self.set_upd = tk.BooleanVar(value=bool(self.cfg.get("update_on_start", False)))
        label("Updates")
        ttk.Checkbutton(holder(), text="Check for updates on start ('git pull' once; off by default)", variable=self.set_upd).pack(side="left")
        r[0] += 1
        ttk.Label(f, text=f"{APP_NAME} {APP_VERSION}   |   Config: {CONFIG_PATH}", style="Dim.TLabel").grid(
            row=r[0], column=0, columnspan=3, sticky="w", padx=PX, pady=(24, 12))
        self.set_last = f.grid_slaves(row=r[0], column=0)[0]
        ttk.Label(f, text="Every change is saved at once (montage_data\\config.json next to montage.py).", style="Dim.TLabel").grid(
            row=r[0] + 1, column=0, columnspan=3, sticky="w", padx=PX, pady=(0, 12))
        self.set_last = f.grid_slaves(row=r[0] + 1, column=0)[0]
        self.set_accent.trace_add("write", self.on_theme_pick)      # V5.58: the theme switches at once (the picker and code alike)
        self.set_base.trace_add("write", self.on_theme_pick)
        for v in [*self.sv.values(), *self.sl.values(), *self.sn.values(), *self.set_track.values(), *self.set_names.values(), self.set_opt, self.set_len,
                  self.set_style, self.set_q, self.set_place, self.set_songmap, self.set_sync, self.set_upd, self.set_audio, self.set_accent, self.set_base]:
            v.trace_add("write", self.autosave)

    def names_changed(self, *_):
        """V6.0: after editing player names, say how many cached clips were scanned with other names and ASK before rescanning."""
        cfg = self.collect_settings(dict(self.cfg))
        sig = json.dumps(cfg.get("player_names"), sort_keys=True)
        if sig == getattr(self, "_names_sig", json.dumps(self.cfg.get("player_names"), sort_keys=True)):
            return
        self._names_sig = sig
        self.flush_settings()
        try:
            n = len(stale_name_clips(load_config()))
        except Exception as ex:
            out(f"player names: could not check cached clips ({ex})")
            return
        if n and messagebox.askyesno("Player names", f"{n} clip(s) were scanned with other player names and are marked stale.\n\n"
                                     "Rescan them now? It runs in the background, can be cancelled and resumes later. "
                                     "Nothing is rescanned unless you say yes."):
            self.run_task("rescan", lambda: rescan_stale_names(load_config()))

    def rp_refresh(self):
        """V6.8: the Settings region picker: every saved region of the selected game (same data as regioncheck)."""
        g = self.rp_game.get()
        keep = self.rp_tree.selection()
        self.rp_tree.delete(*self.rp_tree.get_children())
        self.rp_rows = {}
        for i, row in enumerate(region_options(g)):
            iid = f"r{i}"
            self.rp_rows[iid] = row
            self.rp_tree.insert("", "end", iid=iid, text=row["label"],
                                values=(row["hash"], row["entries"] or "", row["first"], row["last"], ("[" + ", ".join(f"{v:g}" for v in row["region"]) + "]") if row["region"] else "values not stored in these entries"))
        if keep and self.rp_tree.exists(keep[0]):
            self.rp_tree.selection_set(keep[0])
            self.rp_state()
        else:
            self.rp_info.set("Select a region to see how many cached clips it would keep valid.")

    def rp_state(self):
        """V6.8.1: 'Rescan this group' is disabled for the row that is the current region (and while a task runs)."""
        try:
            row = self.rp_selected()
            off = self.busy or (row is not None and row["hash"] == Detector(self.rp_game.get()).d["stamp"])
            self.b_rp_resc.state(["disabled"] if off else ["!disabled"])
        except (tk.TclError, AttributeError):
            pass

    def rp_selected(self):
        sel = self.rp_tree.selection()
        return self.rp_rows.get(sel[0]) if sel else None

    def rp_select(self):
        row = self.rp_selected()
        if not row:
            return
        v, vc, need = region_effect(self.rp_game.get(), row["hash"])
        self.rp_state()
        self.rp_info.set(f"{row['label']} ({row['hash']}): {vc} cached clips ({v} entries) would be valid under it, {need} would need a scan."
                         + ("" if row["usable"] else "  Its region values are not stored: it cannot be used."))

    def rp_rescan(self):
        """V6.8.1: scan only the clips that have an entry under the selected hash and none under the current region (adds entries)."""
        row, g = self.rp_selected(), self.rp_game.get()
        if not row:
            messagebox.showinfo("Killfeed region", "Select a region first.")
            return
        cur = Detector(g).d["stamp"]
        if row["hash"] == cur:
            messagebox.showinfo("Killfeed region", "This is the current region - nothing to rescan.")
            return
        busy = job_active() or (self.busy and "a task") or None
        if busy:
            messagebox.showinfo("Killfeed region", f"Not now: {busy} is running. Wait for it to finish (or cancel it) first.")
            return
        info = rescan_group_clips(g, row["hash"], load_config())
        n = len(info["recs"])
        if not n:
            messagebox.showinfo("Killfeed region", f"No clips to rescan: every clip with an entry under {row['hash']} already has one under {cur}"
                                + (f" ({info['missing']} are not in the clip folders any more)." if info["missing"] else "."))
            return
        if not messagebox.askyesno("Killfeed region", f"Rescan {n} clips from {row['hash']} to the current region {cur}?\n\n"
                                   "The old entries stay; new ones are added. Cancel stops it, clips already scanned keep their new entries."
                                   + ("\nValorant: each old entry is first copied into valorant_cache_backup.json." if g == "valorant" else "")):
            return
        self.run_task("rescan", lambda: (rescan_group(g, row["hash"], load_config(), info), self.q.put(("call", self.rp_refresh))))

    def rp_use(self):
        """Same code path as 'regionrestore --use' (region_apply). Never starts a scan."""
        row, g = self.rp_selected(), self.rp_game.get()
        if not row:
            messagebox.showinfo("Killfeed region", "Select a region first.")
            return
        if not messagebox.askyesno("Killfeed region", f"Switch the {g.upper()} killfeed region to {row['hash']}?"):
            return
        ok, lines, _info = region_apply(g, row["use"])
        for ln in lines:
            out(ln)
        if not ok:
            messagebox.showerror("Killfeed region", lines[0])
        self.rp_refresh()
        self.refresh_auto()

    def rp_set_default(self):
        row, g = self.rp_selected(), self.rp_game.get()
        if not row or not row["region"]:
            messagebox.showinfo("Killfeed region", "Select a region with known values first.")
            return
        if not messagebox.askyesno("Killfeed region", f"Set {row['hash']} as the saved default {g.upper()} killfeed region?"):
            return
        reg = set_saved_default(g, row["region"])
        out(f"{g}: saved default region set to {reg} (hash {region_stamp(reg)}); the current region is unchanged")
        self.rp_refresh()

    def save_settings(self):
        self.flush_settings()
        self.save_status.set("Saved \u2713")
        self.root.after(1500, lambda: self.save_status.set("All changes saved"))
        out("Settings saved")
        self.run_task("clips", self.load_clips)

    # ---- live theme (V5.58): accent / base change applies at once, no restart
    COLOR_OPTS = {"bg": "bg", "background": "bg", "fg": "fg", "foreground": "fg", "highlightbackground": "bg", "highlightcolor": "acc",
                  "insertbackground": "fg", "selectbackground": "sel", "selectforeground": "sel_fg", "activebackground": "btn_act",
                  "activeforeground": "fg", "troughcolor": "head", "disabledforeground": "dim", "selectcolor": "field"}

    # V6.1: one registry for the classic tk widgets. A widget registers at creation with a role; retheme() walks every classic widget
    # (registered ones by their role, the rest - Tk's own combobox pop-downs, dialog frames - by their class) and applies the CURRENT palette.
    ROLE_OPTS = {
        "window": {"bg": "bg", "highlightbackground": "bg", "highlightcolor": "acc"},
        "label": {"bg": "bg", "fg": "fg", "highlightbackground": "bg", "highlightcolor": "acc", "activebackground": "bg", "activeforeground": "fg"},
        "text": {"bg": "field", "fg": "fg", "insertbackground": "fg", "highlightbackground": "border", "highlightcolor": "acc",
                 "selectbackground": "sel", "selectforeground": "sel_fg"},
        "entry": {"bg": "field", "fg": "fg", "insertbackground": "fg", "highlightbackground": "border", "highlightcolor": "acc",
                  "selectbackground": "sel", "selectforeground": "sel_fg"},
        "list": {"bg": "field", "fg": "fg", "highlightbackground": "border", "highlightcolor": "acc", "selectbackground": "acc",
                 "selectforeground": "acc_fg"},
        "pane": {"bg": "border", "highlightbackground": "border"},
        "menu": {"bg": "field", "fg": "fg", "activebackground": "acc", "activeforeground": "acc_fg"},
        "accent": {"bg": "acc", "fg": "acc_fg", "highlightbackground": "acc"},
        "fixed": {},                                              # data / image backdrops with their own fixed colours
    }
    CLASS_ROLE = {"Tk": "window", "Toplevel": "window", "Frame": "window", "Canvas": "window", "Label": "label", "Text": "text",
                  "Entry": "entry", "Spinbox": "entry", "Listbox": "list", "Panedwindow": "pane", "Menu": "menu"}

    def reg(self, w, role):
        """Register a classic tk widget with its colour role; returns the widget."""
        if not hasattr(self, "_reg"):
            self._reg = {}
        self._reg[str(w)] = role
        return w

    def role_of(self, w):
        return getattr(self, "_reg", {}).get(str(w)) or self.CLASS_ROLE.get(w.winfo_class())

    def _tk_widgets(self):
        """Every classic tk widget of the app (all windows, the pop-downs of the comboboxes included)."""
        out_, todo = [], [self.root]
        sp = getattr(self, "_splash", None)
        if sp is not None:
            todo.append(sp)
        while todo:
            w = todo.pop()
            try:
                todo.extend(w.winfo_children())
            except tk.TclError:
                continue
            if not w.winfo_class().startswith("T") or w.winfo_class() in ("Toplevel", "Tk", "Text", "TLabel"):
                out_.append(w)
        return out_

    def recolour(self):
        """Apply the current palette to every classic tk widget by role."""
        pal = self.pal
        for w in self._tk_widgets():
            if w.winfo_class() == "TLabel":
                # V6.1.3: a ttk Label created while Tk's option database held an old palette ("*background", set by sv.tcl's tk_setPalette)
                # carries that colour as its own -background, which overrides the theme: after Black -> Grey -> Black these were the
                # leftover grey / black boxes. Empty = the active Sun Valley variant draws it.
                try:
                    if str(w.cget("background")):
                        w.configure(background="")
                except tk.TclError:
                    pass
                continue
            role = self.role_of(w)
            for opt, key in self.ROLE_OPTS.get(role, {}).items():
                try:
                    if str(w.cget(opt)).lower() != pal[key].lower():
                        w.configure(**{opt: pal[key]})
                except tk.TclError:
                    pass                                          # the widget has no such option

    def retheme(self, accent=None, base=None):
        """Re-apply the Sun Valley theme (a unique theme per accent x base, sourced into the running window) and recolour every widget:
        ttk styles come from the theme; every classic tk widget is recoloured by its registered role (see recolour)."""
        cfg = self.cfg
        accent = accent or cfg.get("accent", "lime")
        base = base or cfg.get("base", "grey")
        old, tagsnap = dict(self.pal), []
        with pstage("retheme: snapshot Text tag colours"):
            for w in self._tk_widgets():
                if w.winfo_class() == "Text":
                    tags = {}
                    for t in w.tag_names():
                        for opt in ("foreground", "background", "selectbackground", "selectforeground"):
                            v = str(w.tag_cget(t, opt)).lower()
                            if v:
                                tags[(t, opt)] = v
                    tagsnap.append((w, tags))
        with pstage("retheme: apply_theme (total)"):
            self.pal = apply_theme(self.root, UI_SCALE[0], accent, base)     # the scale in use (a changed scale applies after restart)
        PAL.clear()
        PAL.update(self.pal)
        with pstage("retheme: registry recolour (classic tk widgets)"):
            self.recolour()
        old_to_key = {}
        for k, v in old.items():
            old_to_key.setdefault(str(v).lower(), k)
        for w, tags in tagsnap:
            for (t, opt), v in tags.items():
                k = old_to_key.get(v)
                if k is not None:
                    try:
                        w.tag_configure(t, **{opt: self.pal[k]})
                    except tk.TclError:
                        pass
        with pstage("retheme: update_idletasks that follows"):
            self.root.update_idletasks()

    def on_theme_pick(self, *_):
        """Accent colour / base picked in Settings: switch the running window at once."""
        acc = next((k for k, lab in ACCENT_NAMES.items() if lab == self.set_accent.get()), "lime")
        base = "black" if self.set_base.get().lower() == "black" else "grey"
        if (acc, base) == (self.cfg.get("accent", "lime"), self.cfg.get("base", "grey")):
            return
        self.cfg["accent"], self.cfg["base"] = acc, base
        try:
            self.retheme(acc, base)
        except Exception as ex:
            out(f"Theme not applied: {ex}")
        self.autosave()

    # ---- changelog popout (V5.57)
    def show_changelog(self):
        old = getattr(self, "cl_win", None)
        if old is not None and old.winfo_exists():
            old.deiconify()
            old.lift()
            return
        win = self.cl_win = self.reg(tk.Toplevel(self.root), "window")
        win.withdraw()
        win.title(f"{APP_NAME} changelog")
        win.configure(bg=self.pal["bg"])
        win.geometry("780x640")
        win.minsize(420, 300)
        set_window_icon(win)
        fr = ttk.Frame(win, padding=(12, 12, 12, 8))
        fr.pack(side="top", fill="both", expand=True)
        txt = tk.Text(fr, wrap="word", bg=self.pal["field"], fg=self.pal["fg"], insertbackground=self.pal["fg"], relief="flat", bd=0,
                      highlightthickness=1, highlightbackground=self.pal["border"], padx=16, pady=12, font=("Segoe UI", F(10)),
                      selectbackground=self.pal["sel"], selectforeground=self.pal["sel_fg"], spacing1=2, spacing3=2)
        self.reg(txt, "text")
        sb = ttk.Scrollbar(fr, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)
        txt.tag_configure("ver", font=("Segoe UI", F(14), "bold"), foreground=self.pal["acc"], spacing1=16, spacing3=4)
        txt.tag_configure("sub", font=("Segoe UI", F(10), "bold"), spacing1=6)
        txt.tag_configure("bul", lmargin1=14, lmargin2=28)
        for kind, line in changelog_lines():
            txt.insert("end", line + "\n", {"ver": "ver", "sub": "sub", "bul": "bul"}.get(kind, ""))
        txt.configure(state="disabled")
        bar = ttk.Frame(win, padding=(12, 0, 12, 12))
        bar.pack(side="bottom", fill="x")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
        self.cl_text = txt
        self.reveal(win)


ACCENT_NAMES = {"lime": "Lime green", "yellow": "Yellow", "orange": "Orange", "red": "Red", "pink": "Pink", "purple": "Purple"}
CHANGELOG_PATH = HERE / "CHANGELOG.md"          # next to montage.py (absolute): works from any working folder


def changelog_lines(path=None):
    """CHANGELOG.md as (kind, text) lines for the popout: ver = '## ' version heading, sub = '### ', bul = '- ' bullet, '' = text."""
    try:
        raw = Path(path or CHANGELOG_PATH).read_text(encoding="utf-8").splitlines()
    except OSError as ex:
        return [("", f"CHANGELOG.md was not found next to montage.py ({ex}).")]
    res = []
    for ln in raw:
        if not res and not ln.startswith("## "):
            continue                                              # the file title and intro; the popout starts at the newest version
        if ln.startswith("## "):
            res.append(("ver", ln[3:].strip()))
        elif ln.startswith("### "):
            res.append(("sub", ln[4:].strip()))
        elif ln.lstrip().startswith(("- ", "* ")):
            res.append(("bul", "\u2022 " + ln.lstrip()[2:].strip()))
        elif ln.strip():
            res.append(("", ln.strip()))
    return res


def grab_gray_bgr(path, t, w, h):
    import numpy as np
    r = run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], timeout=60)
    return np.frombuffer(r.stdout[:w * h * 3], np.uint8).reshape(h, w, 3).copy()


DATA_GLOBALS = ("DATA", "CONFIG_PATH", "CLIPS_CACHE", "AUDIO_CACHE", "KILLS_CACHE", "LOG_DIR", "SONG_CACHE", "USED_CLIPS", "USED_FLAGS", "USED_TITLES", "VAL_BACKUP", "REGION_DEFAULTS", "JOB_LOCK", "USED_SONGS",
                "FLICK_CACHE", "ONSET_CACHE", "SCALES", "REFINE_CACHE", "LOUD_CACHE", "BORDER_DIR")


def use_data_dir(d):
    """Point every cache / config path at another folder (tests). Returns the old values for restore_data_dir()."""
    g = globals()
    old = {k: g[k] for k in DATA_GLOBALS}
    d = Path(d)
    for k in DATA_GLOBALS:
        g[k] = d / ("logs" if k == "LOG_DIR" else Path(old[k]).name) if k != "DATA" else d
    d.mkdir(parents=True, exist_ok=True)
    return old


def restore_data_dir(old):
    globals().update(old)


SHOT_LAG = 0.12                         # generated clips: the killfeed row appears this long after the fatal shot


def synth_clip(path, kills, dur=7.0, fps=60, row_s=4.0, t0_frames=0, deaths=()):
    """Generated 1920x1080 clip: moving background, a gunshot SHOT_LAG before each killfeed row '<left> [gun] <right>', which
    appears at an exact FRAME. deaths = frames where an 'enemy [gun] fireaxe' row appears. A kill tuple may carry a 4th value,
    the icon width (22 = square ability icon, no gunshot)."""
    import numpy as np
    W, H = 1920, 1080
    n = int(dur * fps)
    sr = 48000
    a = (np.random.default_rng(1).standard_normal(int(dur * sr)) * 0.01).astype(np.float32)
    rng_ = np.random.default_rng(2)
    for kf, l, r, *iw in kills:
        if iw and iw[0] < 40:
            continue
        i0 = int((kf / fps - SHOT_LAG) * sr)
        if 0 <= i0 < len(a) - 4000:
            a[i0:i0 + 4000] += (rng_.standard_normal(4000) * 0.6 * np.exp(-np.arange(4000) / 600)).astype(np.float32)
    kills = list(kills) + [(df, "enemy", "fireaxe") for df in deaths]
    wav = str(path) + ".wav"
    import soundfile as sf
    sf.write(wav, np.stack([a, a], 1), sr)
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
                          "-i", wav, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-g", "30", "-pix_fmt", "yuv420p",
                          "-c:a", "aac", "-shortest", str(path)], stdin=subprocess.PIPE)
    x0, y0 = int(0.58 * W), int(0.05 * H)
    rows = {}
    yy, xx = np.mgrid[0:H, 0:W + 400]
    base = np.zeros((H, W + 400, 3), np.uint8)
    base[..., 0] = (40 + 30 * np.sin(xx / 200.0)).astype(np.uint8)
    base[..., 1] = 60
    base[..., 2] = (90 + 30 * np.cos(yy / 150.0)).astype(np.uint8)
    for f in range(n):
        sh = int((f + t0_frames) * 3) % 400
        img = np.ascontiguousarray(base[:, sh:sh + W])
        code = f + t0_frames                               # game-frame barcode (16 bits, bottom-left): continuity checks
        for bit in range(16):
            img[1040:1064, 20 + bit * 28:44 + bit * 28] = 255 if (code >> bit) & 1 else 0
        vis = [k for k in kills if k[0] <= f < k[0] + row_s * fps]
        if vis:
            key = tuple(vis)
            if key not in rows:
                rows[key] = synth_row_frame(vis[0][1], vis[0][2], icon_w=(vis[0][3] if len(vis[0]) > 3 else 80), w=int(0.42 * W), h=int(0.37 * H), y=60,
                                            extra=[(60 + 48 * (i + 1), tuple(k[1:])) for i, k in enumerate(vis[1:])])
            fr = rows[key]
            region = img[y0:y0 + fr.shape[0], x0:x0 + fr.shape[1]]
            m = fr.astype(int).sum(2) != (70 + 78 + 86)
            region[m] = fr[m]
        p.stdin.write(img.tobytes())
    p.stdin.close()
    p.wait()
    os.remove(wav)


def read_barcodes(outfile):
    """Game-frame numbers from the generated clips' barcode, per output frame (continuity check of stitched takes)."""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(outfile), "-an", "-vf", "crop=480:24:0:1040,format=gray", "-f", "rawvideo", "-"],
                       capture_output=True, timeout=120)
    fr = np.frombuffer(r.stdout, np.uint8)
    n = len(fr) // (480 * 24)
    fr = fr[:n * 480 * 24].reshape(n, 24, 480)
    vals = []
    for f in fr:
        bits = [f[6:18, 26 + b * 28:38 + b * 28].mean() > 128 for b in range(16)]
        vals.append(sum(1 << b for b, on in enumerate(bits) if on))
    return vals


def music_offset(outfile, song_path, start_t, dur=10.0, sr=12000):
    """Where the song really sits in a rendered file: cross-correlation of the output audio with the clean song (game audio is
    uncorrelated noise to it). Returns the measured offset in seconds (0 = exactly as planned)."""
    import numpy as np
    def dec(path, ss=None, t=None):
        cmd = ["ffmpeg", "-v", "error"] + (["-ss", f"{ss:.4f}"] if ss is not None else []) + ["-i", str(path)] + \
              (["-t", f"{t:.3f}"] if t else []) + ["-vn", "-ac", "1", "-af", f"aresample={sr},asetpts=N/SR/TB", "-f", "f32le", "-"]
        return np.frombuffer(subprocess.run(cmd, capture_output=True, timeout=120).stdout, np.float32)
    o = dec(outfile, None, dur + 1)
    full = dec(song_path)
    i0 = int(round(start_t * sr))
    ref = full[max(0, i0 - int(0.2 * sr)): i0 + int((dur + 0.2) * sr)]
    n = min(len(o), int(dur * sr))
    if n < sr or len(ref) < n:
        return None
    o = o[int(0.5 * sr):n]                                  # skip the fade-in
    best = (-1e9, 0)
    base = int(0.2 * sr) + int(0.5 * sr) if i0 >= int(0.2 * sr) else i0 + int(0.5 * sr)
    for lag in range(-int(0.05 * sr), int(0.05 * sr) + 1):
        j = base + lag
        if j < 0 or j + len(o) > len(ref):
            continue
        c = float(np.dot(o, ref[j:j + len(o)]))
        if c > best[0]:
            best = (c, lag)
    return -best[1] / sr


def song_click_onsets(song_path, sr=48000):
    """Attack times of the clicks / hits in the CLEAN song (decoded with the same origin as the render)."""
    import numpy as np
    y = np.abs(decode_mono(song_path, sr)[0])
    env = np.maximum.reduceat(y, np.arange(0, len(y), 24))
    thr = 0.35 * np.percentile(env, 99.5)
    on, last = [], -1e9
    for j in np.flatnonzero(env >= thr):
        t = j * 24 / sr
        if t - last > 0.2:
            pk = env[j:j + 40].max()
            k = j
            while k > max(0, j - 20) and env[k - 1] >= 0.15 * pk:
                k -= 1
            on.append(k * 24 / sr)
            last = t
    return np.array(on)


def measure_sync(outfile, plan, row_frames=None):
    """From the RENDERED FILE: each take's kill moment (first frame its kill row is visible, minus the shot->row lag) vs the beat
    onsets of the music as it actually sits in the file (located by cross-correlation with the clean song)."""
    import numpy as np
    off = music_offset(outfile, plan["song"]["path"], plan["song"]["start_t"]) or 0.0
    on = song_click_onsets(plan["song"]["path"]) - plan["song"]["start_t"] + off
    codes = read_barcodes(outfile)
    rows = []
    shot_lag = plan.get("_shot_lag", SHOT_LAG)
    for t in plan["takes"]:
        a = t["f0"]
        want = (row_frames or {}).get(Path(t["path"]).name)
        f_row = None
        if want is not None:
            # the source frame number of the kill row is known (generated clip); find where it sits in the output by reading the
            # barcode on clean frames of the 1.0x run-up (effects never touch those) and counting frames forward
            lo = a + max(0, int(round((t["kills_out"][0] - 0.9) * OUT_FPS)))
            hi = a + int(round((t["kills_out"][0] - 0.05) * OUT_FPS))
            vals = [(i, codes[i]) for i in range(lo, min(hi, len(codes))) if 0 < codes[i] < 60000]
            run_ = vals[-1:]                               # longest consistent run ending at the last clean frame
            for j in range(len(vals) - 2, -1, -1):
                if vals[j + 1][1] - vals[j][1] == vals[j + 1][0] - vals[j][0]:
                    run_.insert(0, vals[j])
                else:
                    break
            if len(run_) >= 10:
                i, c = run_[-1]
                f_row = i + (want - c)
        if f_row is None:
            rows.append((t, None, None, None))
            continue
        tk = f_row / OUT_FPS - shot_lag                     # kill moment = the row's first frame minus the shot->row lag
        near = on[np.argmin(np.abs(on - tk))] if len(on) else None
        rows.append((t, tk, near, None if near is None else (tk - near) * 1000))
    return rows, on


def _fx_windows(plan):
    """Per take (its own output timeline): the windows where zoom / flash / a zoom-or-flash cut move or hide the picture."""
    used = set(plan.get("fx", FX_ALL)) - set(plan.get("fx_failed") or [])
    res = []
    for ti, t in enumerate(plan["takes"]):
        w = [(p - 0.02, p + 0.47) for p in t.get("pulses", [])] if "zoom" in used else []
        if "flash" in used and t.get("flash") is not None:
            w.append((t["flash"] - 0.02, t["flash"] + 0.14))
        if "transition" in used and ti > 0 and t.get("trans") in ("zoom", "flash"):
            w.append((0.0, 0.28))
        res.append(w)
    return res


def speed_check(outfile, plan):
    """Generated clips only (they carry a game-frame barcode): from 1 s before each take's first kill (or the take start) through
    its last kill every output frame must show the NEXT game frame - 1.0x, no repeated or missing frame, also across a stitch.
    Returns (checked, list of problems); checked=False when the file has no readable barcode (real footage)."""
    codes = read_barcodes(outfile)
    ok = [0 < c < 60000 for c in codes]
    if sum(ok) < 0.6 * len(codes):
        return False, []
    fxw, probs = _fx_windows(plan), []
    fo = plan["song"].get("fade_out_start", plan["duration"])
    for ti, t in enumerate(plan["takes"]):
        a = t["f0"]
        lo = a + max(0, int(round((t["kills_out"][0] - 1.0) * OUT_FPS)))
        hi = a + int(round(t["kills_out"][-1] * OUT_FPS))
        clean = lambda i: i < len(codes) and ok[i] and i / OUT_FPS >= FADE_IN + 0.05 and i / OUT_FPS < fo - 0.02 and \
            not any(x - 1.5 / OUT_FPS <= (i - a) / OUT_FPS <= y + 1.5 / OUT_FPS for x, y in fxw[ti])
        pairs = [(codes[i], codes[i + 1]) for i in range(lo, hi) if clean(i) and clean(i + 1)]
        badp = [p for p in pairs if p[1] - p[0] != 1]
        if len(pairs) < 10 or badp:
            probs.append(f"take {ti + 1}: {len(badp)} of {len(pairs)} frame steps are not +1 game frame in the 1.0x stretch"
                         + (f" (e.g. {badp[0][0]} -> {badp[0][1]})" if badp else ""))
    return True, probs


def measure_render(outfile, plan, cfg, refine=True):
    """Measured from a RENDERED FILE with the kill detector: per take, the first frame each planned kill row is visible (native
    60 fps), the kill moment (row - the take's measured shot->row lag), where the music really sits (cross-correlation with the
    clean song) and the nearest beat / strong song onset. Also: duration, music audible from the start, music gaps, tails."""
    import numpy as np
    game = plan["game"]
    det = load_dets(game).get(game)
    rec = probe_video(str(outfile))
    rec.update(path=str(outfile), game=game, bars=False)
    entry = scan_clip(str(outfile), rec, det, cfg)
    kills_all = []
    fxw = _fx_windows(plan)
    kills_clean = []                                       # second pass without the effect frames (a zoomed row can be misread)
    for ti, t in enumerate(plan["takes"]):                 # a montage cut ends every killfeed row: one analysis per take
        fa, fb = int(math.ceil(t["out_start"] * FPS)), int(math.ceil((t["out_start"] + t["dur"]) * FPS))
        sub = [[f - fa, sn - fa, [b[:6] + [v if isinstance(v, str) else v - fa for v in b[6:]] for b in bx], bl]
               for f, sn, bx, bl in entry["ocr"] if fa <= f < fb]
        e = {"frames": fb - fa, "v_off": fa / FPS + entry.get("v_off", 0.0), "game": entry.get("game")}
        if sub:
            kills_all += analyse_entry(dict(e, ocr=sub), cfg)["kills"]
        sub = [x for x in sub if not any(a <= x[0] / FPS <= b for a, b in fxw[ti])]
        if sub and fxw[ti]:
            kills_clean += analyse_entry(dict(e, ocr=sub), cfg)["kills"]
    cache = {}
    def timed(ks):
        res = []
        for k in ks:
            t = k["t"]
            if refine and k.get("box"):
                try:
                    t2 = refine_kill(rec, det, cfg, k, cache)
                    t = t2 if abs(t2 - k["t"]) <= 1.5 / FPS else t   # a refinement must agree with the 15 fps sighting
                except Exception:
                    pass
            res.append(t)
        return res
    seen, seen_clean = timed(kills_all), timed(kills_clean)
    off = music_offset(outfile, plan["song"]["path"], plan["song"]["start_t"]) or 0.0
    an = get_songmap(plan["song"]["path"], plan["song"].get("bpm") if plan.get("placement") != "v4" else None)
    beats = np.array(an["beats"]) - plan["song"]["start_t"] + off
    strong = local_onsets(plan["song"]["path"]) - plan["song"]["start_t"] + off   # strong hits for THEIR part of the song
    rows = []
    for i, t in enumerate(plan["takes"], 1):
        t0, t1 = t["out_start"], t["out_start"] + t["dur"]
        planned = [t0 + r for r in t["rows_out"]]
        got, hid = [], []
        for pr in planned:                                 # a row that appears under an effect may be readable only after it
            late = max([0.35] + [b - (pr - t0) + 0.1 for a, b in fxw[i - 1] if a - 0.35 <= pr - t0 <= b])
            hid.append(any(a - 2 / FPS <= pr - t0 <= b for a, b in fxw[i - 1]))
            m = [x for x in seen if t0 - 0.05 <= x <= t1 + 0.05 and abs(x - pr) <= 0.35] or \
                [x for x in seen_clean if t0 - 0.05 <= x <= t1 + 0.05 and -0.35 <= x - pr <= late]
            got.append(min(m, key=lambda x: abs(x - pr)) if m else None)
        first = None if hid[0] else got[0]                 # its timing is then not measurable from this file
        dl = t["rows_out"][0] - t["kills_out"][0] if t.get("kills_out") else t.get("lag", 0.1)   # lag in OUTPUT time (slow-mo)
        km = None if first is None else first - dl
        eb = None if km is None else float(np.min(np.abs(beats - km))) * 1000
        eo = None if km is None or not len(strong) else float(np.min(np.abs(strong - km))) * 1000
        last_seen = max([g for g in got if g is not None], default=None)
        tail = None if last_seen is None else t1 - (last_seen - t.get("lag", 0.1))
        rows.append({"take": i, "role": t["role"], "kills": len(planned), "seen": sum(g is not None for g in got), "fx_hidden": hid[0],
                     "kill_moment": km, "err_beat_ms": eb, "err_onset_ms": eo, "tail": tail, "ending": t["ending"],
                     "inside": all(g is None or t0 - 0.02 <= g <= t1 for g in got)})
    # whole-file audio checks: level at the start, and music gaps = the output is >10 dB quieter than the song at that moment
    def dec(path, ss=None, t=None):
        cmd = ["ffmpeg", "-v", "error"] + (["-ss", f"{ss:.4f}"] if ss is not None else []) + ["-i", str(path)] + \
              (["-t", f"{t:.3f}"] if t else []) + ["-vn", "-ac", "1", "-af", "aresample=12000,asetpts=N/SR/TB", "-f", "f32le", "-"]
        return np.frombuffer(subprocess.run(cmd, capture_output=True, timeout=120).stdout, np.float32)
    au = dec(outfile)
    sg = dec(plan["song"]["path"])
    i0 = int(round((plan["song"]["start_t"] - off) * 12000))
    sg = sg[max(0, i0):max(0, i0) + len(au)]
    win = 1200
    db = lambda x: 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)
    fo = plan["song"].get("fade_out_start", plan["duration"])
    gaps = []
    for j in range(3 * win, min(len(au), len(sg), int(fo * 12000)) - win, win):
        so, oo = db(sg[j:j + win]), db(au[j:j + win])
        if so > -50 and oo < so - 10:
            gaps.append(round(j / 12000, 1))
    return {"rows": rows, "duration": probe_duration(outfile), "planned": plan["duration"], "music_offset_ms": off * 1000,
            "start_db": float(db(au[int(0.3 * 12000):int(0.5 * 12000)])) if len(au) > 6000 else -99,
            "gaps": gaps, "detected_kills": len(seen)}


def render_check(outfile, plan, cfg, verbose=True):
    """Checks a finished montage ON THE FILE: duration = plan, music audible within the first 0.5 s, no music gaps, every take
    shows its kills (detector run on the output), no tail longer than 0.5 s after a take's last kill (the ending excepted), and the
    ending's slow-mo + fades start on the final kill. Returns (fails, measurements)."""
    m = measure_render(outfile, plan, cfg)
    fails = []
    if abs(m["duration"] - m["planned"]) > 1.5 / OUT_FPS:
        fails.append(f"duration {m['duration']:.3f} s != plan {m['planned']:.3f} s")
    sec = plan["song"].get("section_s")
    if sec is not None and m["duration"] > sec + 1.5 / OUT_FPS:
        fails.append(f"duration {m['duration']:.3f} s is longer than the song section ({sec:.3f} s from {ts(plan['song']['start_t'])})")
    if m["start_db"] < -40:
        fails.append(f"music not audible at 0.3-0.5 s ({m['start_db']:.1f} dBFS)")
    if m["gaps"]:
        fails.append(f"music gaps at {m['gaps']} s")
    for r in m["rows"]:
        if r["seen"] < r["kills"]:
            fails.append(f"take {r['take']} ({r['role']}): only {r['seen']} of {r['kills']} kills visible in the output")
        if not r["inside"]:
            fails.append(f"take {r['take']}: a kill row shows outside its take")
        if not r["ending"] and r["tail"] is not None and r["tail"] > TAIL[1] + 1.5 / OUT_FPS:
            fails.append(f"take {r['take']}: tail {r['tail']:.2f} s after the last kill")
    chk, sp = speed_check(outfile, plan)
    m["speed_checked"] = chk
    fails += sp
    last = plan["takes"][-1]
    if plan.get("ending"):
        fo = plan["song"]["fade_out_start"]
        kend = last["out_start"] + last["kills_out"][-1]
        if abs(fo - kend) > 1.5 / OUT_FPS or not (END_FADE[0] - 0.05 <= plan["duration"] - fo <= END_FADE[1] + 0.05):
            fails.append("the ending fade does not run from the final kill to the end (2-3 s)")
    if verbose:
        print_measure(m, f"RENDER CHECK {Path(outfile).name}")
        out("  " + ("OK: duration = plan and <= the song section, music audible from the start, no gaps, every take shows its kills, tails <= 0.5 s, "
                    "slow-mo ending + fades from the final kill" + (", 1.0x frame-by-frame (barcode) from 1 s before each first kill "
                    "through the last kill" if m["speed_checked"] else "") if not fails else "FAIL: " + "; ".join(fails)))
    return fails, m


def cmd_rendercheck(args):
    """rendercheck <montage.mp4>: uses the .plan.json saved in logs\ next to it (older montages: next to the video)."""
    f = Path(args.file)
    pj = next((q for q in (f.parent / "logs" / (f.stem + ".plan.json"), f.with_suffix(".plan.json")) if q.exists()), None)
    if not pj:
        cands = sorted(list(f.parent.glob("*.plan.json")) + list((f.parent / "logs").glob("*.plan.json")),
                       key=lambda p: p.stat().st_mtime)
        pj = cands[-1] if cands else None
    if not pj:
        raise SystemExit("no .plan.json for the video (looked in logs\\ and next to it)")
    fails, _ = render_check(f, load_json(pj, {}), load_config())
    if fails:
        sys.exit(1)


def print_measure(m, title):
    out(title)
    out(f"  duration {m['duration']:.2f} s (plan {m['planned']:.2f} s) | music offset {m['music_offset_ms']:+.1f} ms | "
        f"music level 0.3-0.5 s {m['start_db']:.1f} dBFS | music gaps {m['gaps'] or 'none'}")
    out(f"  {'take':>4} {'role':9} {'kills':>5} {'seen':>4} {'kill moment':>11} {'vs beat':>9} {'vs onset':>9} {'tail':>6}")
    for r in m["rows"]:
        f = lambda v, u="ms": "   -" if v is None else (f"{v:+7.1f}{u}" if u == "ms" else f"{v:5.2f}s")
        out(f"  {r['take']:4d} {r['role']:9} {r['kills']:5d} {r['seen']:4d} "
            f"{('effect' if r.get('fx_hidden') else '-') if r['kill_moment'] is None else format(r['kill_moment'], '9.3f') + 's':>11} "
            f"{f(r['err_beat_ms'])} {f(r['err_onset_ms'])} "
            f"{f(r['tail'], 's')}{' (ending)' if r['ending'] else ''}")


def _summ(m):
    import numpy as np
    e = [abs(r["err_beat_ms"]) for r in m["rows"] if r["err_beat_ms"] is not None]
    return {"n": len(e), "mean": float(np.mean(e)) if e else 999.0, "max": max(e) if e else 999.0,
            "in_frame": 100.0 * sum(x <= 1000 / OUT_FPS for x in e) / len(e) if e else 0.0}


def sync_compare(cfg=None, game=None, seed=11, encoder=None, verbose=True):
    """synccompare: the same clips + song + seed planned and rendered with the V4 placement and with the V5 placement; each first
    kill measured from the rendered files against the beat. Picks V5 only if it is clearly better. Rendered WITHOUT zoom / flash /
    transitions (they never change timing, but they hide the killfeed row from the detector at exactly the kill moment)."""
    cfg = cfg or load_config()
    res = {}
    for g in ([game] if game else list(GAMES)):
        if not [r for r in scan_clips(cfg) if r.get("game") == g]:
            continue
        ms = {}
        for pl in ("v4", "v5"):
            outp = Path(cfg["output_root"]) / GAME_DIR[g] / f"synccompare_{pl}.mp4"
            f = run_job(g, "render", force=True, seed=seed, encoder=encoder, outfile=outp, placement=pl, effects=False)
            if not f:
                continue
            ms[pl] = measure_render(f, LAST_PLAN[g], cfg)
            if verbose:
                print_measure(ms[pl], f"SYNCCOMPARE {g} - {pl.upper()} placement ({Path(f).name}, effects off)")
        if len(ms) == 2:
            s4, s5 = _summ(ms["v4"]), _summ(ms["v5"])
            better = s5["mean"] < 0.7 * s4["mean"] and s5["in_frame"] >= s4["in_frame"]
            res[g] = {"v4": s4, "v5": s5, "winner": "v5" if better else "v4"}
            out(f"SYNCCOMPARE {g}: V4 mean {s4['mean']:.1f} ms / max {s4['max']:.1f} ms / {s4['in_frame']:.0f}% within 1 frame  |  "
                f"V5 mean {s5['mean']:.1f} ms / max {s5['max']:.1f} ms / {s5['in_frame']:.0f}% within 1 frame  ->  "
                f"{'V5 is clearly better' if better else 'V5 is NOT clearly better: keep V4'}")
    if res:
        win = "v5" if all(r["winner"] == "v5" for r in res.values()) else "v4"
        cfg2 = load_config()
        cfg2["placement"] = win
        save_json(CONFIG_PATH, cfg2)
        out(f"placement set to {win.upper()} (Settings > placement)")
    return res


def _testdata_cfg(base_cfg, root=None):
    """If testdata/ exists: clip folders, MP3s and CSV from it (game from the folder name), output to testdata/out."""
    td = Path(root) if root else HERE / "testdata"
    if not td.is_dir():
        return None
    own = lambda p: "out" in p.parts or "montage_data" in p.parts       # the app's own outputs / caches are never inputs
    vids = [p for p in td.rglob("*") if p.suffix.lower() in VIDEO_EXT and p.name.lower() != "good.mp4" and not own(p)]
    dirs = {"valorant": set(), "cs2": set()}
    for v in vids:
        low = str(v.parent).lower()
        dirs["valorant" if "valo" in low else "cs2"].add(str(v.parent))
    csvs = sorted(p for p in td.rglob("*.csv") if not own(p))
    mp3s = sorted(p for p in td.rglob("*.mp3") if not own(p))
    return dict(base_cfg, clip_dirs={k: sorted(v) for k, v in dirs.items()},
                mp3_dir=str(mp3s[0].parent) if mp3s else base_cfg.get("mp3_dir", ""),
                playlist_dir=str(csvs[0].parent) if csvs else base_cfg.get("playlist_dir", ""),
                output_root=str(td / "out"), bar_checked=base_cfg.get("bar_checked", False))


def cmd_synccompare(args):
    cfg = load_config()
    tdc = _testdata_cfg(cfg)
    old = None
    if tdc:
        old = use_data_dir(HERE / "testdata" / "montage_data")
        save_json(CONFIG_PATH, tdc)
        out("using testdata/ (real clips, MP3s, CSV)")
    try:
        sync_compare(game=args.game, seed=args.seed)
    finally:
        if old:
            restore_data_dir(old)


def sync_e2e_test(workdir=None, keep=False, verbose=True):
    """END-TO-END SYNC TEST: click-track song with known beats + 60 fps clips with kill rows at known frames -> real plan and render
    -> measured from the rendered file. Every first kill must be within 1 frame (17 ms) of its beat. Returns (fails, rows)."""
    import tempfile
    wd = Path(workdir or tempfile.mkdtemp(prefix="montage_sync_"))
    old = use_data_dir(wd / "montage_data")
    fails = []
    try:
        clips = wd / "clips" / "VALORANT"
        clips.mkdir(parents=True, exist_ok=True)
        mp3 = wd / "mp3"
        mp3.mkdir(exist_ok=True)
        t0 = time.time()
        specs = [(181, "fireaxe", "alpha"), (197, "fireaxe", "bravo"), (233, "fireaxe", "charlie"), (211, "fireaxe", "delta")]
        for i, (kf, l, r) in enumerate(specs):
            p = clips / f"VALORANT 2026.01.0{i + 1} - 20.1{i}.00.00.DVR.mp4"
            if not p.exists():
                synth_clip(p, [(kf, l, r)])
        song = mp3 / "Test Artist - Click Song.mp3"
        if not song.exists():
            synth_song(song, 120.0, layout=(("verse", 32),), click=True)
        with open(wd / "playlist.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Track URI", "Track Name", "Artist Name(s)", "Added At", "Duration (ms)", "Danceability", "Energy", "Tempo"])
            w.writerow(["u:1", "Click Song", "Test Artist", datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"), "65000", "0.7", "0.8", "120.000"])
        cfg = dict(DEFAULT_CONFIG, clip_dirs={"valorant": [str(clips)], "cs2": []}, mp3_dir=str(mp3), playlist_dir=str(wd),
                   output_root=str(wd / "out"), bar_checked=True, bar=None, sync_report=False, length_s=60)
        save_json(CONFIG_PATH, cfg)
        if verbose:
            out(f"  sync test material ready in {time.time() - t0:.0f}s")
        outfile = run_job("valorant", "render", force=True, seed=7, lock=1.0, encoder="fast", outfile=wd / "out" / "sync_test.mp4")
        if not outfile or not Path(outfile).exists():
            return ["sync test: the render failed"], []
        plan = LAST_PLAN["valorant"]
        sync_e2e_test.plan = plan
        rows, on = measure_sync(outfile, plan, {f"VALORANT 2026.01.0{i + 1} - 20.1{i}.00.00.DVR.mp4": kf
                                                 for i, (kf, l, r) in enumerate(specs)})
        for t, tk, near, err in rows:
            msg = f"  take at {t['out_start']:6.2f}s ({Path(t['path']).name[-28:]}): kill moment (row frame - {SHOT_LAG}s) " + \
                  (f"{tk:7.3f}s, beat onset {near:7.3f}s, error {err:+6.1f} ms" if err is not None else "NOT FOUND")
            if verbose:
                out(msg)
            if err is None or abs(err) > 1000 / OUT_FPS + 0.5:
                fails.append("sync: " + msg.strip())
        if len(rows) < 2:
            fails.append(f"sync: only {len(rows)} takes in the test montage")
        if plan.get("ssim") is not None and plan["ssim"] < 0.97:
            fails.append(f"quality: SSIM {plan['ssim']} < 0.97")
        return fails, rows
    finally:
        restore_data_dir(old)
        LAST_PLAN.pop("valorant", None)
        if not keep and workdir is None:
            shutil.rmtree(wd, ignore_errors=True)


def revive_fight_test(workdir=None, verbose=True):
    """CLOVE REVIVE TEST: one generated Valorant clip with kill, death, self-revive row (FIREAXE + ability icon, no victim),
    kill, kill. The revive must not be a kill, it must end the death lock and bridge the 10.5 s gap: ONE 3k event, ONE take."""
    import tempfile
    wd = Path(workdir or tempfile.mkdtemp(prefix="montage_revive_"))
    old = use_data_dir(wd / "montage_data")
    fails = []
    try:
        clips = wd / "clips" / "VALORANT"
        clips.mkdir(parents=True, exist_ok=True)
        mp3 = wd / "mp3"
        mp3.mkdir(exist_ok=True)
        clip = clips / "VALORANT 2026.01.05 - 20.15.00.00.DVR.mp4"
        # kill 1.5 s, death 5.0 s, revive 10.0 s, kill 12.0 s (inside the 8 s death lock), kill 13.5 s
        synth_clip(clip, [(90, "fireaxe", "alpha"), (600, "fireaxe", "", 22), (720, "fireaxe", "bravo"), (810, "fireaxe", "charlie")],
                   dur=16.0, deaths=(300,))
        song = mp3 / "Test Artist - Click Song.mp3"
        synth_song(song, 120.0, layout=(("verse", 32),), click=True)
        with open(wd / "playlist.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Track URI", "Track Name", "Artist Name(s)", "Added At", "Duration (ms)", "Danceability", "Energy", "Tempo"])
            w.writerow(["u:1", "Click Song", "Test Artist", datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"), "65000", "0.7", "0.8", "120.000"])
        cfg = dict(DEFAULT_CONFIG, clip_dirs={"valorant": [str(clips)], "cs2": []}, mp3_dir=str(mp3), playlist_dir=str(wd),
                   output_root=str(wd / "out"), bar_checked=True, bar=None, sync_report=False, length_s=60)
        save_json(CONFIG_PATH, cfg)
        plan, _ = make_plan(cfg, "valorant", seed=7, lock=1.0)
        pool, _ = game_pool(cfg, "valorant")
        it = pool[0] if pool else {"kills": [], "deaths": [], "revives": []}
        if verbose:
            out(f"  clip: kills {[k['t'] for k in it['kills']]}, deaths {it['deaths']}, revives {it['revives']}")
        if len(it.get("revives", [])) != 1:
            fails.append(f"revive: expected 1 revive row, got {it.get('revives')}")
        if len(it["kills"]) != 3:
            fails.append(f"revive: expected 3 kills (no kill from the revive row, none lost to the death lock), got {len(it['kills'])}")
        takes = [t for t in plan["takes"] if Path(t["path"]).name == clip.name]
        if verbose:
            out("  takes from the clip: " + ", ".join(f"{t['n']}k @ {t['out_start']:.2f}s" for t in takes))
        if len(takes) != 1 or takes[0]["n"] != 3:
            fails.append(f"revive: expected ONE 3k take from the clip, got {[t['n'] for t in takes]}")
        return fails
    finally:
        restore_data_dir(old)
        LAST_PLAN.pop("valorant", None)
        if workdir is None:
            shutil.rmtree(wd, ignore_errors=True)


def audio_tone_test(plan, workdir, verbose=True):
    """AUDIO TONE CHECK: the montage's song replaced by a steady 440 Hz tone, rendered with every effect and the game audio
    (gunshots on the kills). Outside the fade-in / fade-out the tone's level must stay within 1 dB: no ducking, no limiter pumping,
    no automation. Returns (fails, stats)."""
    import copy
    import numpy as np
    wd = Path(workdir)
    old = use_data_dir(wd / "montage_data")
    try:
        p = copy.deepcopy(plan)
        tone = wd / "tone440.mp3"
        dur = p["song"]["start_t"] + p["duration"] + 5
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={dur:.2f}",
             "-af", "volume=-3dB", "-ac", "2", "-b:a", "192k", str(tone)], timeout=120)
        p["song"]["path"] = str(tone)
        outf = wd / "out" / "tone_test.mp4"
        render_plan(p, outf, dict(load_config(), sync_report=False), encoder="fast")
        sr = 48000
        a = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(outf), "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                                         capture_output=True, timeout=120).stdout, np.float32)
        fo = float(p["song"].get("fade_out_start", p["duration"] - 2))
        # lock-in level of the 440 Hz tone (least-squares sine fit) in 250 ms windows every 50 ms: short enough for any ducking or
        # limiter pumping, narrow enough (4 Hz) that the white-noise gunshots barely leak into it
        win, hop = int(0.25 * sr), int(0.05 * sr)
        tt = np.arange(win) / sr
        basis = np.vstack([np.cos(2 * np.pi * 440 * tt), np.sin(2 * np.pi * 440 * tt)]).T
        lv, ts = [], []
        for i in range(int((FADE_IN + 0.1) * sr), int((fo - 0.1) * sr) - win, hop):
            x = np.linalg.lstsq(basis, a[i:i + win].astype(np.float64), rcond=None)[0]
            lv.append(20 * np.log10(np.hypot(*x) + 1e-12))
            ts.append(i / sr)
        lv = np.array(lv)
        kills = [t["out_start"] + k for t in p["takes"] for k in t["kills_out"]]
        near = [l for l, t in zip(lv, ts) if any(t - 0.05 <= k <= t + 0.3 for k in kills)]
        away = [l for l, t in zip(lv, ts) if not any(t - 0.05 <= k <= t + 0.3 for k in kills)]
        st = {"windows": len(lv), "from": FADE_IN + 0.1, "to": fo - 0.1, "spread_db": float(lv.max() - lv.min()) if len(lv) else 99.0,
              "kill_spread_db": float(max(near) - min(near)) if near else 0.0, "kills": len(kills),
              "away_spread_db": float(max(away) - min(away)) if away else 0.0,
              "median_db": float(np.median(lv)) if len(lv) else 0.0}
        fails = [] if st["spread_db"] <= 1.0 and len(lv) >= 20 else \
            [f"audio: the steady tone varies {st['spread_db']:.2f} dB between {st['from']:.1f} s and {st['to']:.1f} s (limit 1.0 dB)"]
        if verbose:
            out(f"  tone 440 Hz, {st['windows']} windows of 250 ms from {st['from']:.2f} s to {st['to']:.2f} s (outside the fades): "
                f"spread {st['spread_db']:.2f} dB; away from kills {st['away_spread_db']:.2f} dB; windows holding one of the {st['kills']} kills "
                f"(gunshots) {st['kill_spread_db']:.2f} dB")
        return fails, st
    finally:
        restore_data_dir(old)


def fake_events(n=26, seed=3):
    """Synthetic kill events (no clips needed) for planner tests."""
    rng = random.Random(seed)
    evs = []
    for i in range(n):
        k = rng.choice([1, 1, 1, 2, 2, 3, 4, 5])
        k0 = rng.uniform(4, 30)
        times = [k0]
        for _ in range(k - 1):
            times.append(times[-1] + rng.uniform(0.3, 1.5))
        rec = {"path": f"/fake/clip{i}.mp4", "w": 1920, "h": 1080, "dur": 45.0, "audio": False}
        ev = {"rec": rec, "path": rec["path"], "times": times, "rows": [t + 0.12 for t in times], "times_v4": [t + 0.02 for t in times],
              "n": k, "victims": [f"v{i}{j}" for j in range(k)], "first": k0, "last": times[-1], "span": times[-1] - k0,
              "hs": rng.random() < 0.3, "flick": False, "shots": 1.0, "imp": k - 1, "lag": 0.12, "pre": k0 - 0.05,
              "post": 45 - times[-1] - 0.3, "death_after": rng.uniform(0.25, 1.5) if rng.random() < 0.2 else None,
              "parts": None, "stitched": False, "lags": [0.0] * k, "vis": []}
        ev["score"] = base_score(ev)
        ev["plain"] = k == 1 and not ev["hs"]
        evs.append(ev)
    evs.sort(key=lambda e: -e["score"])
    return evs


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture_rows_test(verbose=True):
    """V5.42 real Valorant killfeed rows (fixtures/): knife kill = excluded, Clove self-revive and Sage resurrect (green victim
    side) = revive, never a kill or death; through the scan path a real kill AFTER a resurrect row is kept."""
    import cv2
    import numpy as np
    fails = []
    want = {"valorant_knife_kill.png": "knife kill", "valorant_clove_self_revive.png": "revive", "valorant_sage_resurrect.png": "revive"}
    for nm, w in want.items():
        im = cv2.imread(str(FIXTURES / nm))
        if im is None:
            fails.append(f"fixture {nm} missing")
            continue
        big = cv2.resize(im, None, fx=2.4, fy=2.4, interpolation=cv2.INTER_CUBIC)          # killfeed crops are scanned upscaled
        canvas = np.full((360, 1100, 3), (70, 78, 86), np.uint8)
        canvas[40:40 + big.shape[0], 1100 - 20 - big.shape[1]:1100 - 20] = big
        kill = synth_row_frame("fireaxe", "enemy", w=1100, h=360, y=220)
        frames = [np.full_like(canvas, (70, 78, 86))] * 12 + [canvas] * 24 + [np.where(kill != (70, 78, 86), kill, canvas)] * 30
        ocr, n = scan_frames(iter(frames))
        a = analyse_entry({"ocr": ocr, "frames": n, "v_off": 0.0}, {})
        ks = a["kills"] if w == "knife kill" else [k for k in a["kills"] if k.get("weapon", "gun") != "knife"]   # V5.5: knife = a kill
        if verbose:
            out(f"  {nm}: kills {[k['t'] for k in ks]}, knife kills {[k['t'] for k in a['kills'] if k.get('weapon') == 'knife']}, "
                f"deaths {a['deaths']}, revives {a['revives']}")
        if w == "knife kill":
            ok = len(ks) == 2 and ks[-1]["t"] > 1.0 and not a["deaths"] and not a["revives"]
        else:
            ok = len(ks) == 1 and ks[0]["t"] > 1.0 and not a["deaths"] and (len(a["revives"]) == 1 if w == "revive" else not a["revives"])
        if not ok:
            fails.append(f"fixture {nm}: expected {w} row ignored + the later real kill kept, got kills {[k['t'] for k in a['kills']]} "
                         f"deaths {a['deaths']} revives {a['revives']}")
    return fails


def synth_cs2_row(killer, victim, icons, kcol=(90, 200, 235), vcol=(230, 180, 110), w=1100, h=200, y=100):
    """Generated CS2 killfeed crop: coloured names (default T-yellow killer, CT-blue victim), my red row frame, white icons
    [(w, h, kind)] left to right: 'awp' (long thin rifle), 'smoke' (cloud), anything else a solid block."""
    import cv2
    import numpy as np
    img = np.full((h, w, 3), (70, 78, 86), np.uint8)
    f, sc, th = cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2
    lw, rw = cv2.getTextSize(killer, f, sc, th)[0][0], cv2.getTextSize(victim, f, sc, th)[0][0]
    x0 = w - 24 - (lw + 20 + sum(i[0] for i in icons) + 8 * (len(icons) - 1) + 20 + rw)
    cv2.rectangle(img, (x0 - 10, y - 28), (w - 12, y + 10), (28, 28, 30), -1)
    cv2.rectangle(img, (x0 - 10, y - 28), (w - 12, y + 10), (40, 40, 200), 2)
    cv2.putText(img, killer, (x0, y), f, sc, kcol, th, cv2.LINE_AA)
    ix = x0 + lw + 20
    for iw, ih, kind in icons:
        top = y - 9 - ih // 2
        if kind == "awp":
            cv2.rectangle(img, (ix, top + ih // 2 - 2), (ix + iw, top + ih // 2 + 1), (255, 255, 255), -1)
            cv2.rectangle(img, (ix + iw // 2, top), (ix + iw - 10, top + ih), (255, 255, 255), -1)
        elif kind == "smoke":
            r = ih // 3
            for cx, cy in ((ix + r, top + ih - r), (ix + iw // 2, top + r), (ix + iw - r, top + ih - r)):
                cv2.circle(img, (cx, cy), r, (255, 255, 255), -1)
        else:
            cv2.rectangle(img, (ix, top), (ix + iw, top + ih), (255, 255, 255), -1)
        ix += iw + 8
    cv2.putText(img, victim, (ix + 12, y), f, sc, vcol, th, cv2.LINE_AA)
    return img


def cs2_rows_test(verbose=True):
    """V5.42B: CS2 rows with long weapon icons (AWP) and modifier icons (through-smoke, no-scope, headshot) next to CT-blue /
    T-yellow names are MY GUN KILLS in CS2 - never knife, utility or revive (those rules are Valorant's)."""
    fails = []
    cases = {"AWP, CT victim": [(150, 22, "awp")], "rifle + through-smoke": [(96, 26, "rect"), (30, 26, "smoke")],
             "pistol + big smoke icon": [(40, 26, "rect"), (40, 34, "smoke")],
             "AWP no-scope + smoke + HS": [(150, 22, "awp"), (24, 24, "rect"), (30, 26, "smoke"), (24, 24, "rect")]}
    for nm, icons in cases.items():
        rows = ocr_rows(*ocr_frame(synth_cs2_row("fireaxe", "ctguy", icons)), "cs2")
        vs = [(v, why) for r in rows for v, why in classify_row(r)]
        wc = [weapon_class(r) for r in rows]
        if verbose:
            out(f"  CS2 {nm}: " + "; ".join(f"{v.upper()} ({why})" for v, why in vs) + f" | weapon {wc}")
        if [v for v, _ in vs] != ["kill"] or wc != ["gun"]:
            fails.append(f"CS2 {nm}: expected one gun KILL, got {vs} weapon {wc}")
    # my CS2 name 'fireaxe火斧' with the latin part garbled by OCR: '火斧' alone makes it my row (OCR boxes as the scanner stores them)
    for ktext, vtext, want in (("froxo火斧", "enemy", "kill"), ("enemy", "froxo火斧", "death"), ("enemy + froxo火斧", "victim", "reject")):
        boxes = lambda f: [[60, 20, 260, 50, ktext, 0.9, 12, ""], [420, 20, 540, 50, vtext, 0.9, 12, ""]]
        blobs = [[290, 24, 110, 22, 0.6]]
        rows = ocr_rows(boxes(0), blobs, "cs2")
        vs = [v for r in rows for v, _ in classify_row(r)]
        a = analyse_entry({"ocr": [[f, f, boxes(f), blobs] for f in range(12, 60, 4)], "frames": 60, "v_off": 0.0}, {}, "cs2")
        got = {"kill": len(a["kills"]), "death": len(a["deaths"])}
        if verbose:
            out(f"  CS2 name '{ktext}' -> '{vtext}': {vs}; scanned: kills {[k['t'] for k in a['kills']]} deaths {a['deaths']} "
                f"| recovered by '{MY_NAME_CS2}': {a['cjk']}")
        if vs != [want] or (want != "reject" and got[want] != 1) or a["cjk"] != {want: 1}:
            fails.append(f"CS2 name '{ktext}' -> '{vtext}': expected {want.upper()} via '{MY_NAME_CS2}', got {vs} {got} {a['cjk']}")
        if ocr_rows(boxes(0), blobs, "valorant") and any(v != "none" for r in ocr_rows(boxes(0), blobs, "valorant")
                                                          for v, _ in classify_row(r)):
            fails.append(f"Valorant: '{ktext}' must not count as my name")
    return fails


def planner_selftest(verbose=True):
    """V5.1 planner on a generated song (intro/verse/build/drop/breakdown/drop/outro) with synthetic events: cut-list rules,
    best multikill on the biggest drop, first kills on beats, tails 0.2-0.5 s, strong slow-mo ending with fades from the final
    kill, Optimal length 30-120 s, Auto style, variety between seeds."""
    import tempfile
    import numpy as np
    fails = []
    tmpd = Path(tempfile.mkdtemp(prefix="montage_plan_"))
    old = use_data_dir(tmpd / "data")
    real_ca = globals()["clip_audio"]
    globals()["clip_audio"] = lambda rec, *a, **k: {"stream": None, "lufs": None}
    try:
        sp_ = tmpd / "plan test.mp3"
        synth_song(sp_, 128.0)
        an = analyse_song(str(sp_), 128.0)
        evs = fake_events()
        song = {"path": str(sp_), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
        sigs = []
        for seed in (1, 2, 3, 4):
            plan = plan_montage(dict(DEFAULT_CONFIG), "valorant", evs, song, an, seed, "auto", "optimal", [], [])
            bad = verify_cutlist(plan)
            if bad:
                fails.append(f"seed {seed}: " + "; ".join(bad))
            takes = plan["takes"]
            beats = np.array(plan["beats_out"])
            errs = [abs(beats - (t["out_start"] + t["kills_out"][0])).min() * 1000 for t in takes]
            if max(errs) > 1000 / OUT_FPS / 2 + 0.5:
                fails.append(f"seed {seed}: a first kill is {max(errs):.1f} ms off its beat")
            hl = [t for t in takes if t["role"] == "headline"]
            best = max(e["score"] for e in evs)
            if not hl or hl[0]["score"] < 0.9 * best:
                fails.append(f"seed {seed}: the drop does not carry the best multikill")
            elif plan["song"]["drop_t"] is not None and abs(hl[0]["out_start"] + hl[0]["kills_out"][0] - plan["song"]["drop_t"]) > 0.02:
                fails.append(f"seed {seed}: the headline's first kill is not on the drop downbeat")
            last = takes[-1]
            if not last["ending"] or not last["slow"] or last["n"] < 2:
                fails.append(f"seed {seed}: the last take is not a strong slow-mo ending")
            elif abs(plan["song"]["fade_out_start"] - (last["out_start"] + last["kills_out"][-1])) > 0.02 or \
                    not (END_FADE[0] - 0.05 <= plan["duration"] - plan["song"]["fade_out_start"] <= END_FADE[1] + 0.05):
                fails.append(f"seed {seed}: the fades do not run from the final kill to the end (2-3 s)")
            if last["slow_at"] is None or abs(last["slow_at"] - last["kills_out"][-1]) > 1.5 / OUT_FPS:
                fails.append(f"seed {seed}: the ending slow-mo does not start on the final kill")
            if not (29.5 <= plan["duration"] <= 121):
                fails.append(f"seed {seed}: length {plan['duration']:.0f} s outside 30-120 s")
            if plan["recipe"] not in RECIPES:
                fails.append(f"seed {seed}: auto style picked '{plan['recipe']}'")
            sigs.append((plan["recipe"], tuple(Path(t["path"]).name for t in takes), tuple(t["trans"] for t in takes),
                         tuple(len(t["pulses"]) for t in takes)))
            if verbose:
                out(f"  seed {seed}: recipe {plan['recipe']}, {len(takes)} takes, {plan['duration']:.0f} s, first kills max "
                    f"{max(errs):.1f} ms off the beat, tails max {max(t['dur'] - t['kills_out'][-1] for t in takes[:-1]):.2f} s")
        if len({s[1] for s in sigs}) < 2 or len({s[1:] for s in sigs}) < 3:
            fails.append("variety: different seeds did not give clearly different montages")
        # V5.4 length rules: Manual uses every usable clip; a fixed length lists what it leaves out; a short song lists what
        # did not fit; never longer than the song section
        sp2 = tmpd / "short test.mp3"
        synth_song(sp2, 128.0, layout=(("intro", 4), ("verse", 8), ("build", 4), ("drop", 8), ("outro", 4)))
        an2 = analyse_song(str(sp2), 128.0)
        for a_, nm_, ev_, tg_, chk in ((an, "manual optimal, 26 clips (V5.42B rule)", evs, "optimal", "range"),
                                       (an, "manual optimal, 10 clips", fake_events(10), "optimal", "all"),
                                       (an, "manual fixed 40 s", evs, 40, "left"), (an2, "manual optimal, short song", evs, "optimal", "short")):
            p_ = plan_montage(dict(DEFAULT_CONFIG), "valorant", ev_, dict(song, path=str(sp2) if a_ is an2 else song["path"]), a_, 5,
                              "auto", tg_, [], [], manual=True)
            f_ = p_["fit"]
            if p_["duration"] > p_["song"]["section_s"]:
                fails.append(f"{nm_}: {p_['duration']:.1f} s is longer than the song section {p_['song']['section_s']:.1f} s")
            if verify_cutlist(p_):
                fails.append(f"{nm_}: " + "; ".join(verify_cutlist(p_)))
            if chk == "all" and f_["used"] != f_["usable"]:
                fails.append(f"{nm_}: only {f_['used']} of {f_['usable']} usable clips used")
            if chk == "left" and (not f_["left_out"] or f_["used"] + len(f_["left_out"]) != f_["usable"]):
                fails.append(f"{nm_}: left-out clips not listed ({f_})")
            if chk == "short" and (not f_["song_short"] or f_["used"] + len(f_["song_short"]) != f_["usable"]):
                fails.append(f"{nm_}: song-too-short clips not listed ({f_})")
            if chk == "range":                             # V5.42B: optimal_fit() - all clips unless they really don't fit
                mx_ = min(OPT_RANGE[1], f_["section_s"])
                if f_["used"] + len(f_["song_short"]) != f_["usable"] or p_["duration"] > mx_ + 0.05 or \
                        (f_["song_short"] and p_["duration"] < min(OPT_RANGE[0], mx_) - 8) or \
                        not any(n.startswith("OPTIMAL ") and "pacing" in n for n in p_["notes"]):
                    fails.append(f"{nm_}: {p_['duration']:.0f} s, {f_['used']} used, {len(f_['song_short'])} listed of "
                                 f"{f_['usable']} usable - Optimal must use them all or fill min(150 s, song) and say why")
                elif verbose:
                    out("  " + next(n for n in p_["notes"] if n.startswith("OPTIMAL ") and "pacing" in n))
            if verbose:
                out(f"  {nm_}: {p_['notes'][1]}")
    finally:
        globals()["clip_audio"] = real_ca
        restore_data_dir(old)
        shutil.rmtree(tmpd, ignore_errors=True)
    return fails


# button name -> (tab, task name / action it must trigger when clicked)
REQUIRED_BUTTONS = {}
for _g in GAMES:
    REQUIRED_BUTTONS[f"auto:{_g}:make"] = ("Auto", f"task:{_g} auto")
    REQUIRED_BUTTONS[f"auto:{_g}:Force new"] = ("Auto", f"task:{_g} Force new")
    REQUIRED_BUTTONS[f"auto:{_g}:Dry plan"] = ("Auto", f"task:{_g} Dry plan")
    REQUIRED_BUTTONS[f"auto:{_g}:Preview 720p / 20 s"] = ("Auto", f"task:{_g} Preview 720p / 20 s")
REQUIRED_BUTTONS.update({
    "manual:dry": ("Manual", "task:manual dry"), "manual:preview": ("Manual", "task:manual preview"),
    "manual:render": ("Manual", "task:manual render"),
    "Tick all shown": ("Manual", "ticked"), "Untick all": ("Manual", "unticked"), "Tick clips with kills": ("Manual", "ticked"),
    "Tick newest": ("Manual", "ticked"), "Reload list": ("Manual", "task:clips"),
    "Random pick": ("Manual", "task:random pick"), "Used filter": ("Manual", None),
    "Play selected song": ("Manual", "open:song.mp3"),
    "Refresh": ("Songs", "task:matches"), "Change match for selected file...": ("Songs", "info"),
    "Play selected file": ("Songs", "open:song.mp3"), "Open song_matches.csv": ("Songs", "open:song_matches.csv"),
    "Selfcheck (ffmpeg, NVENC, packages)": ("Troubleshoot", "task:selfcheck"),
    "Calibrate killfeed region (optional)...": ("Troubleshoot", "window"),
    "Self-test detection": ("Troubleshoot", "task:selftest"), "Scan all clips now": ("Troubleshoot", "task:scan all"),
    "Open logs": ("Troubleshoot", "open:logs"), "Clear kill cache": ("Troubleshoot", "ask"),
    "Load clips": ("Troubleshoot", "task:tclips"), "Kill timestamps + killfeed crop": ("Troubleshoot", "info"),
    "Rescan this clip": ("Troubleshoot", "info"), "Before/after preview": ("Troubleshoot", "info"),
    "Re-measure": ("Troubleshoot", "task:bars"),
    "Song map (Manual)": ("Manual", "window"), "Song map of selected file...": ("Songs", "window"),
    "Save settings": ("Settings", "write:config.json"), "Changelog": ("Settings", "window"),
    "Optimal length": ("Manual", None), "Style": ("Manual", None),
    "Open folder": (None, "open:"), "Open video": (None, None), "Cancel": (None, None),
})


def smoketest_gui(sizes=((1220, 920), (1920, 1040), (920, 640))):
    """Builds the real GUI (no startup jobs), checks that every required button exists, is visible inside the window at several
    window sizes, and that clicking it triggers the right action (jobs/dialogs/files are intercepted, nothing runs)."""
    fails = []
    g = globals()
    app = App(0, startup=False)
    root = app.root
    calls = []
    app.run_task = lambda name, fn, *a: calls.append(f"task:{name}")
    app.open_path = lambda p: calls.append(f"open:{Path(p).name}")
    saved = {k: g[k] for k in ("save_json",)}
    mb = {k: getattr(messagebox, k) for k in ("showinfo", "showerror", "askyesno")}
    real_open = open
    try:
        g["save_json"] = lambda p, obj: calls.append(f"write:{Path(p).name}")
        messagebox.showinfo = lambda *a, **k: calls.append("info")
        messagebox.showerror = lambda *a, **k: calls.append("error")
        messagebox.askyesno = lambda *a, **k: (calls.append("ask"), False)[1]
        g["open"] = lambda p, *a, **k: (calls.append(f"write:{Path(p).name}"), real_open(os.devnull, *a, **k))[1]
        tabs = {str(f): n for n, f in app.tabs.items()}

        def tab_of(w):
            while w is not None:
                if str(w) in tabs:
                    return tabs[str(w)]
                w = w.master
            return None
        app.nb.select(app.tabs["Manual"])
        root.update()
        if "More filters" not in app.named or app.named["More filters"].winfo_class() != "TCombobox":
            fails.append("'More filters & actions' is not a dropdown like 'Show'")
        root.geometry(f"{sizes[0][0]}x{sizes[0][1]}+0+0")
        for _ in range(8):
            root.update()
            time.sleep(0.1)
        app.apply_layout({})
        for _ in range(4):
            root.update()
            time.sleep(0.1)
        if app.ctree.winfo_height() < 260:
            fails.append(f"{sizes[0][0]}x{sizes[0][1]}: the clip list is only {app.ctree.winfo_height()} px high by default")
        for W, H in sizes:
            root.geometry(f"{W}x{H}+0+0")
            for tname in app.tabs:
                app.nb.select(app.tabs[tname])
                root.update()
                if tname == "Settings":
                    for _ in range(3):                             # the canvas lays itself out ~100 ms after a resize
                        root.update()
                        time.sleep(0.15)
                rx, ry, rw, rh = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
                for name, (want_tab, _) in REQUIRED_BUTTONS.items():
                    b = app.named.get(name)
                    if b is None:
                        if (W, H) == sizes[0] and tname == "Auto":
                            fails.append(f"button missing: {name}")
                        continue
                    t = tab_of(b)
                    if want_tab and t != want_tab:
                        if tname == "Auto" and (W, H) == sizes[0]:
                            fails.append(f"button {name} is on tab {t}, expected {want_tab}")
                        continue
                    if t not in (None, tname):
                        continue
                    bx, by, bw, bh = b.winfo_rootx(), b.winfo_rooty(), b.winfo_width(), b.winfo_height()
                    vis = b.winfo_viewable() and bw >= 20 and bh >= 15 and bx >= rx and by >= ry and \
                        bx + bw <= rx + rw + 1 and by + bh <= ry + rh + 1
                    if not vis:
                        fails.append(f"{W}x{H} {tname}: button '{name}' not fully visible (at {bx - rx},{by - ry} size {bw}x{bh})")
                if tname == "Settings":                            # the tab scrolls: its last setting is reachable
                    cv = app.set_canvas
                    cv.yview_moveto(1.0)
                    root.update()
                    last = app.set_last
                    ly, cy = last.winfo_rooty() + last.winfo_height(), cv.winfo_rooty() + cv.winfo_height()
                    if not last.winfo_viewable() or ly > cy + 1 or ly > ry + rh + 1:
                        fails.append(f"{W}x{H} Settings: the last setting is not reachable by scrolling (bottom at {ly}, view ends {cy})")
                    cv.yview_moveto(0.0)
                    root.update()
        root.geometry(f"{sizes[0][0]}x{sizes[0][1]}+0+0")
        # wiring: fake one clip and one song so the Manual buttons have something to act on
        fake = {"path": "x/clip.mp4", "name": "clip.mp4", "folder": "VALORANT", "mtime": time.time(), "dur": 20, "kills": 2, "ks": [3.0, 4.0]}
        app.clips, app.byp = [fake], {fake["path"]: fake}
        app.songs = [{"path": "x/song.mp3", "artist": "a", "title": "t", "added": None, "csv_bpm": 128.0}]
        app.apply_filter()
        app.refresh_songs()
        for _ in range(3):                                         # let the chunked fills and delayed re-selection finish
            root.update()
            time.sleep(0.1)
        root.update()
        for name, (want_tab, want) in REQUIRED_BUTTONS.items():
            b = app.named.get(name)
            if b is None or want is None:
                continue
            if want_tab:
                app.nb.select(app.tabs[want_tab])
            if name.startswith("manual:"):
                app.ticked = {fake["path"]}
            if name in ("Play selected song",):
                app.stree.selection_set("x/song.mp3")
            if name == "Play selected file":
                app.mtree.insert("", "end", iid="x/song.mp3", text="song.mp3", values=("t", "a", "128", 100, "ok"))
                app.mtree.selection_set("x/song.mp3")
            if name in ("Tick all shown", "Tick clips with kills", "Tick newest"):
                app.ticked = set()
                app.m_folder.set("VALORANT")
            root.update()
            calls.clear()
            nwin = len(root.winfo_children())
            try:
                b.invoke()
                root.update()
            except Exception as ex:
                fails.append(f"button '{name}' raised {type(ex).__name__}: {ex}")
                continue
            if want == "ticked":
                ok = app.ticked == {fake["path"]}
            elif want == "unticked":
                ok = not app.ticked
            elif want == "window":
                ok = len(root.winfo_children()) > nwin
                for w in root.winfo_children():
                    if isinstance(w, tk.Toplevel):
                        w.destroy()
            else:
                ok = any(c == want or (want.endswith(":") and c.startswith(want)) for c in calls)
            if not ok:
                fails.append(f"button '{name}' is not wired: expected {want}, got {calls or 'nothing'}")
            app.m_folder.set("All folders")
            if name == "Untick all":
                app.ticked = {fake["path"]}
        # V5.57: the dropdown items run their actions (Tick whole folder, Exclude ticked) and set filters
        app.nb.select(app.tabs["Manual"])
        app.ticked = set()
        app.m_folder.set("VALORANT")
        app.more_pick("Tick whole folder")
        if app.ticked != {fake["path"]}:
            fails.append("dropdown item 'Tick whole folder' did not tick the folder")
        calls.clear()
        app.more_pick("Exclude ticked from montages")
        if "write:exclude.txt" not in calls:
            fails.append("dropdown item 'Exclude ticked from montages' is not wired")
        app.m_folder.set("All folders")
        app.ticked = set()
        # Optimal length + Auto style: offered, default in a fresh config, and passed to the job by the Manual buttons
        if DEFAULT_CONFIG.get("length_s") != "optimal" or DEFAULT_CONFIG.get("style") != "auto":
            fails.append("defaults are not length Optimal + style Auto")
        if "auto" not in app.named["Style"].cget("values") or str(app.named["Optimal length"].cget("text")) != "Optimal":
            fails.append("Style 'auto' or the 'Optimal' length option is missing")
        got = []
        app.job_video = lambda game, **kw: (got.append(kw), (lambda: None))[1]
        app.nb.select(app.tabs["Manual"])
        app.ticked = {fake["path"]}
        for opt, ln, sty in ((True, 45, "auto"), (False, 45, "chill")):
            app.m_opt.set(opt)
            app.m_len.set(ln)
            app.m_style.set(sty)
            app.update_status()
            app.named["manual:dry"].invoke()
            root.update()
        want = [("optimal", "auto"), (45, "chill")]
        if [(k.get("target"), k.get("style")) for k in got] != want:
            fails.append(f"Manual length/style not passed on: {[(k.get('target'), k.get('style')) for k in got]} != {want}")
        app.m_opt.set(True)
        # sorting: click headers, check order, click again = reversed
        now = time.time()
        app.clips = [{"path": f"c{i}.mp4", "name": f"c{i}.mp4", "folder": "V", "mtime": now - i * 86400, "dur": 10 + 7 * ((i * 3) % 5),
                      "kills": (i * 7) % 4, "ks": []} for i in range(6)]
        app.byp = {c["path"]: c for c in app.clips}
        app.songs = [{"path": f"s{i}.mp3", "artist": "a", "title": f"t{i}", "added": None, "csv_bpm": 90.0 + (i * 37) % 80} for i in range(5)]
        for tree, col, refill, getv in ((app.ctree, "kills", app.apply_filter, lambda iid: app.byp[iid]["kills"]),
                                        (app.ctree, "len", app.apply_filter, lambda iid: app.byp[iid]["dur"]),
                                        (app.stree, "bpm", app.refresh_songs, lambda iid: next(x["csv_bpm"] for x in app.songs if x["path"] == iid))):
            for want_desc in (None, None):
                app.sort_by(tree, col)
                for _ in range(4):
                    root.update()
                    time.sleep(0.03)
                ids = [i for i in tree.get_children() if i != "auto"]
                vals = [getv(i) for i in ids]
                desc = app.sorts[str(tree)][1]
                if vals != sorted(vals, reverse=desc):
                    fails.append(f"sorting {col}: order {vals} is not {'descending' if desc else 'ascending'}")
        # V5.55: theme, dividers (move + remembered), used column / filter, Random pick
        try:
            import sv_ttk                                          # noqa: F401
            if not SV_THEME[0] or "mt-" not in ttk.Style(root).theme_use():
                fails.append(f"Sun Valley theme did not load (theme {ttk.Style(root).theme_use()})")
        except ImportError:
            out("  (sv-ttk not installed - the plain fallback theme is in use; pip install sv-ttk)")
        root.geometry("1220x920+0+0")
        app.nb.select(app.tabs["Manual"])
        root.update()
        app.apply_layout({"main": 0.7, "manual": 0.6})
        root.update()
        for nm_, pw in (("log", app.vpane), ("song list", app.mpane)):
            moved = []
            for dy in (-40, 40):                                   # one direction may be blocked by a pane's minimum size
                y0 = pw.sash_coord(0)[1]
                pw.sash_place(0, 0, y0 + dy)
                root.update()
                moved.append(pw.sash_coord(0)[1] - y0)
            if not any(abs(m_ - d_) <= 4 for m_, d_ in zip(moved, (-40, 40))):
                fails.append(f"divider above the {nm_}: dragging it 40 px moved it {moved} px")
        st = app.layout_state()
        if not all(k in st for k in ("geometry", "main", "manual")):
            fails.append(f"layout state incomplete: {st}")
        else:
            app.apply_layout(dict(st, main=0.55, manual=0.5))
            root.update()
            for k_, pw in (("main", app.vpane), ("manual", app.mpane)):
                want_y = (0.55 if k_ == "main" else 0.5) * pw.winfo_height()
                if abs(pw.sash_coord(0)[1] - want_y) > max(60 * UI_SCALE[0], 0.2 * pw.winfo_height()):
                    fails.append(f"divider '{k_}' not restored from the saved layout ({pw.sash_coord(0)[1]} vs {want_y:.0f})")
        now_ = time.time()
        app.clips = [{"path": f"u{i}.mp4", "name": f"u{i}.mp4", "folder": "V", "mtime": now_ - i * 86400, "dur": 20, "kills": 3,
                      "ks": [3.0, 4.0, 5.0], "used": "2026-10-01" if i % 2 else ""} for i in range(40)]
        app.byp = {c["path"]: c for c in app.clips}
        for uf, want_n in (("All clips", 40), ("Used", 20), ("Unused", 20)):
            app.m_used.set(uf)
            app.apply_filter()
            for _ in range(4):
                root.update()
                time.sleep(0.03)
            if len(app.ctree.get_children()) != want_n:
                fails.append(f"used filter '{uf}' shows {len(app.ctree.get_children())} clips, expected {want_n}")
        app.m_used.set("All clips")
        app.apply_filter()
        for _ in range(3):
            root.update()
            time.sleep(0.03)
        iid = next(i for i in app.ctree.get_children() if app.byp[i]["used"])
        if app.ctree.set(iid, "used") != "2026-10-01":
            fails.append(f"'used' column shows '{app.ctree.set(iid, 'used')}' instead of the montage date")
        unused = [c for c in app.clips if not c["used"]]
        for inc, pool in ((False, unused), (True, app.clips)):
            ps, fit = random_pick(pool, None, "auto", random.Random(7))
            if not ps or not fit or len(set(ps)) != len(ps) or any(p not in {c["path"] for c in pool} for p in ps):
                fails.append(f"random pick (include used={inc}) returned {len(ps)} clips")
            elif fit["length"] > OPT_RANGE[1] + 0.05:
                fails.append(f"random pick is {fit['length']:.0f} s - longer than the Optimal maximum")
        # V5.56: Random pick uses the number box (N), respects the filters and 'include used clips'; empty box = Optimal estimate
        app.nb.select(app.tabs["Manual"])
        app.m_used.set("All clips")
        app.apply_filter()

        def pump(n=6):
            for _ in range(n):
                root.update()
                time.sleep(0.12)
        pump()
        logged_rt = app.run_task
        app.run_task = lambda name, fn, *a: fn(*a)
        try:
            for inc, n_txt, want in ((False, "7", 7), (True, "7", 7), (False, "50", 20), (True, "50", 40)):
                app.m_incl_used.set(inc)
                app.m_rand_n.set(n_txt)
                app.ticked = set()
                app.random_pick_ticks()
                pump()
                if len(app.ticked) != want or (not inc and any(app.byp[p_]["used"] for p_ in app.ticked)):
                    fails.append(f"random pick N={n_txt} include used={inc}: ticked {len(app.ticked)} (expected {want}, unused only: {not inc})")
            app.m_incl_used.set(False)
            app.m_rand_n.set("")
            app.ticked = set()
            app.random_pick_ticks()
            pump()
            if not app.ticked or any(app.byp[p_]["used"] for p_ in app.ticked):
                fails.append("random pick with an empty number box did not use the Optimal estimate")
        finally:
            app.run_task = logged_rt
            app.m_rand_n.set("15")
            app.m_incl_used.set(False)
            app.ticked = set()
        # V5.56: no list refills while the window is being resized; dividers redraw on release only
        if str(app.vpane.cget("opaqueresize")).lower() not in ("0", "false", "no") or str(app.mpane.cget("opaqueresize")).lower() not in ("0", "false", "no"):
            fails.append("dividers still resize opaquely (laggy)")
        root.geometry("1010x705+0+0")
        root.update()
        app.apply_filter()
        root.update()
        n_during = len(app.ctree.get_children())
        pump(6)
        n_after = len(app.ctree.get_children())
        if n_during != 0 or n_after != 40 or app._resizing:
            fails.append(f"resize debounce: list had {n_during} rows during the resize (expected 0), {n_after} after (expected 40), resizing={app._resizing}")
        if not (PAL["bg"].startswith("#") and PAL["acc"].lower() == "#a3e635") or "theme" in load_config():
            fails.append("theme: not the single grey + lime theme")
        # song map view on a generated song
        import tempfile
        tmpd = Path(tempfile.mkdtemp(prefix="montage_map_"))
        old_d = use_data_dir(tmpd / "data")
        try:
            sp_ = tmpd / "map test.mp3"
            synth_song(sp_, 128.0, layout=(("intro", 4), ("build", 2), ("drop", 4), ("outro", 2)))
            v = SongMapView(app, str(sp_), 128.0)
            t_end = time.time() + 120
            while v.an is None and time.time() < t_end:
                root.update()
                time.sleep(0.05)
            root.update()
            n_items = len(v.cv.find_all())
            if v.an is None or n_items < 50:
                fails.append(f"song map view did not draw (items {n_items}, map {'missing' if v.an is None else 'ok'})")
            elif not v.an.get("drops"):
                fails.append("song map view: the generated song's drop was not found")
            v.win.destroy()
        finally:
            restore_data_dir(old_d)
            shutil.rmtree(tmpd, ignore_errors=True)
    finally:
        g.update(saved)
        g.pop("open", None)
        for k, v in mb.items():
            setattr(messagebox, k, v)
        LOG_SINK[0] = PROGRESS[0] = None
        root.destroy()
    return fails


def settings_persist_test():
    """V5.56: change settings in the real GUI, close it WITHOUT any save click, start the app again (same process) and the real
    command from another working folder: everything must be back, and the config path must be absolute (next to montage.py)."""
    import tempfile
    fails = []
    tmpd = Path(tempfile.mkdtemp(prefix="montage_cfg_"))
    other = Path(tempfile.mkdtemp(prefix="montage_cwd_"))
    old = use_data_dir(tmpd / "data")
    try:
        if not CONFIG_PATH.is_absolute() or not HERE.is_absolute():
            fails.append(f"config path is not absolute: {CONFIG_PATH}")
        want = {"length_s": 97, "style": "chill", "quality": "max", "update_on_start": True, "sync_report": False, "max_mb": 123,
                "mp3_dir": str(tmpd / "mp3")}
        app = App(0, startup=False)
        app.m_opt.set(False)
        app.m_len.set(97)
        app.m_style.set("chill")
        app.m_q.set("max")
        app.set_upd.set(True)
        app.set_sync.set(False)
        app.set_track["cs2"].set("2")
        app.sn["max_mb"].set("123")
        app.sv["mp3_dir"].set(want["mp3_dir"])
        for _ in range(8):
            app.root.update()
            time.sleep(0.08)
        app.root.destroy()                                         # no Save click, no on_close: only the save-on-change counts
        LOG_SINK[0] = PROGRESS[0] = None
        r = subprocess.run([sys.executable, str(HERE / "montage.py"), "cfgdump"], cwd=str(other), capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, MONTAGER_DATA=str(tmpd / "data")))
        try:
            d = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            return fails + [f"cfgdump from another folder failed: {(r.stdout + r.stderr)[-300:]}"]
        if not d.get("exists") or Path(d["config_path"]) != CONFIG_PATH:
            fails.append(f"config file not found from another working folder: {d.get('config_path')} exists={d.get('exists')}")
        for k, v in want.items():
            if d["cfg"].get(k) != v:
                fails.append(f"after a restart from another folder {k} = {d['cfg'].get(k)!r}, expected {v!r}")
        if (d["cfg"].get("game_audio_track") or {}).get("cs2") != "2" or "theme" in d["cfg"]:
            fails.append(f"game_audio_track / theme not as expected: {d['cfg'].get('game_audio_track')} {d['cfg'].get('theme')}")
        r0 = subprocess.run([sys.executable, str(HERE / "montage.py"), "cfgdump"], cwd=str(other), capture_output=True, text=True, timeout=120,
                            env={k: v for k, v in os.environ.items() if k != "MONTAGER_DATA"})
        p0 = json.loads(r0.stdout.strip().splitlines()[-1])["config_path"]
        if Path(p0) != HERE / "montage_data" / "config.json":
            fails.append(f"the default config path depends on the working folder: {p0}")
        app2 = App(0, startup=False)                               # the "reopened" app
        got = {"length_s": "optimal" if app2.m_opt.get() else int(app2.m_len.get()), "style": app2.m_style.get(), "quality": app2.m_q.get(),
               "update_on_start": app2.set_upd.get(), "sync_report": app2.set_sync.get(), "max_mb": int(app2.sn["max_mb"].get()),
               "mp3_dir": app2.sv["mp3_dir"].get()}
        for k, v in want.items():
            if got[k] != v:
                fails.append(f"reopened GUI shows {k} = {got[k]!r}, expected {v!r}")
        if app2.set_track["cs2"].get() != "2" or app2.m_opt.get():
            fails.append("reopened GUI lost the audio track / Optimal setting")
        app2.root.destroy()
        LOG_SINK[0] = PROGRESS[0] = None
    finally:
        restore_data_dir(old)
        shutil.rmtree(tmpd, ignore_errors=True)
        shutil.rmtree(other, ignore_errors=True)
    return fails


def audio_track_test():
    """choose_track rules + a real two-track clip (steady tone = louder, gunshot bursts = the game sound)."""
    import tempfile
    fails = []
    cases = [(([-20.0], [None], "auto"), 0), (([-20.0, -25.0], [2, 40], "auto"), 1), (([-20.0, -22.0], [1, 1], "auto"), 0),
             (([None, -30.0, -25.0], [None, 5, 50], "auto"), 2), (([-20.0, -25.0], [0, 0], "auto"), 0), (([-20.0, -25.0], [40, 2], "2"), 1),
             (([-20.0, -25.0], [40, 2], "3"), 0), (([-20.0, None], [40, None], "2"), 0), (([None, None], [None, None], "auto"), 0),
             (([-90.0, -20.0], [None, None], "auto"), 1), (([-20.0, -25.0, -30.0], [3, 3, 3], "auto"), 0)]
    for (lufs, ons, setting), want in cases:
        got = choose_track(lufs, ons, setting)[0]
        if got != want:
            fails.append(f"choose_track({lufs}, {ons}, {setting!r}) = {got}, expected {want}")
    tmpd = Path(tempfile.mkdtemp(prefix="montage_trk_"))
    old = use_data_dir(tmpd / "data")
    try:
        clip = tmpd / "two_tracks.mkv"
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=8",
                            "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=8",
                            "-f", "lavfi", "-i", "anoisesrc=d=8:c=white:r=48000:a=0.4,volume='if(lt(mod(t,1),0.07),1,0)':eval=frame",
                            "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "mpeg4", "-c:a", "aac", str(clip)],
                           capture_output=True, text=True, timeout=120)
        if not clip.exists():
            return fails + ["could not build the two-track test clip: " + r.stderr[-200:]]
        rec = {"path": str(clip), "audio": True}
        for setting, want in (("auto", 1), ("1", 0), ("2", 1), ("3", 1)):
            au = clip_audio(rec, setting)
            if au["stream"] != want or au.get("lufs") is None:
                fails.append(f"two-track clip, setting {setting}: used track {au['stream']} ({au.get('note')}), expected {want}")
    finally:
        restore_data_dir(old)
        shutil.rmtree(tmpd, ignore_errors=True)
    return fails


def cmd_smoketest(args):
    """Offline checks (no clips needed): GUI buttons exist/visible/wired + OCR detection on generated frames."""
    fails = []
    if not getattr(args, "no_gui", False):
        out("== GUI buttons ==")
        try:
            f = smoketest_gui()
            fails += f
            out("  OK: every required button exists, is visible at 1220x920, 1920x1040 and 920x640, and is wired" if not f else
                "\n".join("  FAIL " + x for x in f))
        except Exception as ex:
            fails.append(f"GUI could not be built: {ex}")
            out("  FAIL GUI: " + traceback.format_exc())
    out("== SETTINGS PERSIST (changed in the GUI, app closed, reopened - also from another working folder) ==")
    try:
        f = settings_persist_test()
        fails += f
        out("  OK: Optimal / length / style / quality / update-on-start / audio track / folders survive a restart; config path is absolute" if not f
            else "\n".join("  FAIL " + x for x in f))
    except Exception:
        fails.append("settings persist test crashed")
        out("  FAIL settings: " + traceback.format_exc())
    out("== GAME AUDIO TRACK (several tracks: the one with the gunshots; one track; unsure = first; never silent; Settings 1/2/3) ==")
    try:
        f = audio_track_test()
        fails += f
        out("  OK: auto picks the track with the gunshots (not the louder tone), forced tracks honoured, silent tracks never used" if not f
            else "\n".join("  FAIL " + x for x in f))
    except Exception:
        fails.append("audio track test crashed")
        out("  FAIL audio track: " + traceback.format_exc())
    out("== OCR detection (generated frames) ==")
    try:
        f = ocr_synthetic_test()
        fails += f
        out("  OK: one KILL for 'fireaxe [gun] enemy', one DEATH for 'enemy [gun] fireaxe'" if not f else "\n".join("  FAIL " + x for x in f))
    except Exception as ex:
        fails.append(f"OCR: {ex}")
        out("  FAIL OCR: " + traceback.format_exc())
    out("== REAL KILLFEED FIXTURES (knife kill, Clove self-revive, Sage resurrect + a real kill after each) ==")
    try:
        f = fixture_rows_test()
        fails += f
        out("  OK: knife kill counts, both revives ignored, the kill after each row kept" if not f else "\n".join("  FAIL " + x for x in f))
    except Exception:
        fails.append("fixture test crashed")
        out("  FAIL fixtures: " + traceback.format_exc())
    out("== CS2 killfeed rows (AWP, through-smoke, modifier icons, CT / T name colours) ==")
    try:
        f = cs2_rows_test()
        fails += f
        out("  OK: every CS2 row is a gun kill (no knife / utility / revive in CS2); '火斧' rows are mine" if not f else "\n".join("  FAIL " + x for x in f))
    except Exception:
        fails.append("CS2 row test crashed")
        out("  FAIL CS2 rows: " + traceback.format_exc())
    out("== Song-map planner (generated song, synthetic events, 4 seeds) ==")
    try:
        f = planner_selftest()
        fails += f
        out("  OK: cut-list rules, a strong clip on every drop, best multikill on the biggest drop, slow-mo ending, variety" if not f
            else "\n".join("  FAIL " + x for x in f))
    except Exception:
        fails.append("planner test crashed")
        out("  FAIL planner: " + traceback.format_exc())
    out("== CLOVE REVIVE (generated clip: kill, death, revive row, kill, kill -> one 3k take) ==")
    try:
        f = revive_fight_test()
        fails += f
        out("  OK: revive row is not a kill, it ends the death lock, one 3k event and one take from the clip" if not f
            else "\n".join("  FAIL " + x for x in f))
    except Exception:
        fails.append("revive test crashed")
        out("  FAIL revive test: " + traceback.format_exc())
    if not getattr(args, "no_render", False):
        out("== END-TO-END SYNC TEST (click-track song + clips with kill rows at known frames -> real render -> measured) ==")
        import tempfile
        wd = Path(tempfile.mkdtemp(prefix="montage_sync_"))
        try:
            try:
                sync_e2e_test.plan = None
                f, rows = sync_e2e_test(workdir=wd)
                fails += f
                errs = [abs(r[3]) for r in rows if r[3] is not None]
                out(f"  {'OK' if not f else 'FAIL'}: {len(errs)} first kills measured in the rendered file, max error "
                    f"{max(errs or [999]):.1f} ms (limit {1000 / OUT_FPS:.1f} ms = 1 frame)" + ("" if not f else "\n" + "\n".join("  FAIL " + x for x in f)))
            except Exception:
                fails.append("sync test crashed")
                out("  FAIL sync test: " + traceback.format_exc())
            out("== AUDIO TONE CHECK (song = steady 440 Hz tone, all effects + gunshots -> real render -> level within 1 dB) ==")
            try:
                if sync_e2e_test.plan is None:
                    raise RuntimeError("no plan from the sync test")
                f, st = audio_tone_test(sync_e2e_test.plan, wd)
                fails += f
                out(f"  {'OK' if not f else 'FAIL'}: music level varies {st['spread_db']:.2f} dB outside the fades (limit 1.0 dB)"
                    + ("" if not f else "\n" + "\n".join("  FAIL " + x for x in f)))
            except Exception:
                fails.append("audio tone test crashed")
                out("  FAIL audio tone test: " + traceback.format_exc())
        finally:
            shutil.rmtree(wd, ignore_errors=True)
    out("SMOKETEST " + ("PASSED" if not fails else f"FAILED ({len(fails)})"))
    if fails:
        sys.exit(1)


def cmd_cfgdump(args):
    """Prints where the config file is and what it holds (the settings-persistence test starts this from another working folder)."""
    print(json.dumps({"config_path": str(CONFIG_PATH), "exists": CONFIG_PATH.exists(), "cfg": load_config()}, ensure_ascii=False))


class _Stage:
    """V6.2: `with pstage("name"):` records the duration of a startup / theme stage in perflog (no-op without the perflog switch)."""
    __slots__ = ("n", "t")

    def __init__(self, n):
        self.n = n

    def __enter__(self):
        self.t = time.perf_counter()
        return self

    def __exit__(self, *a):
        if PERF is not None:
            PERF.stage(self.n, self.t)


def pstage(name):
    return _Stage(name)


def pmark(name):
    if PERF is not None:
        PERF.mark(name)


# ------------------------------------------------------------------ V6.0 perflog (timeline recorder, off unless asked for)
PERF = None


class PerfLog:
    """`python montage.py perflog` or MONTAGE_PERFLOG=1: records WHEN things run (ms since start): window built / first Map / deiconify /
    first Expose, after / after_idle callbacks, theme + style calls, list fills, update() / update_idletasks() (with caller), tab
    switches with the widget creates / configures in the 500 ms after, main-loop gaps > 50 ms. Everything after the first main-window
    <Map> is POST-SHOW. Writes perflog.txt next to montage.py on exit or Ctrl+Shift+P. Nothing is patched without the switch."""
    CAP = 5000

    def __init__(self):
        self.ev, self.post, self.sw_until, self.depth, self.dropped = [], False, 0.0, 0, 0
        self.hb_last, self.root, self.map_t, self.sw_name, self.counts = None, None, None, "", {}
        self.sw_log = []
        self.stages, self.marks, self.switches = [], [], []     # V6.2: stage table, absolute marks, theme-switch records
        self.samples, self.gap_stacks, self.main_id, self._lock = [], [], None, threading.Lock()
        self._th_pending = None

    def now(self):
        return (time.perf_counter() - PERF_T0) * 1000

    # ---- V6.2: stage table
    def stage(self, name, t0):
        d = (time.perf_counter() - t0) * 1000
        self.stages.append(((t0 - PERF_T0) * 1000, d, name, threading.current_thread().name))

    def mark(self, name):
        self.marks.append((self.now(), name))

    # ---- V6.2: stack sampler (daemon thread, every 10 ms, main thread only)
    def start_sampler(self):
        self.main_id = threading.get_ident()
        threading.Thread(target=self._sample_loop, daemon=True, name="perf-sampler").start()

    def _sample_loop(self):
        while True:
            time.sleep(0.01)
            try:
                f = sys._current_frames().get(self.main_id)
                st = []
                while f is not None and len(st) < 24:
                    st.append((f.f_code.co_name, f.f_code.co_filename, f.f_lineno))
                    f = f.f_back
                with self._lock:
                    self.samples.append((self.now(), tuple(st)))
                    if len(self.samples) > 40000:
                        del self.samples[:10000]
            except Exception:
                pass

    @staticmethod
    def _is_tk_file(fn):
        fn = fn.replace("\\", "/")
        return fn.endswith(("tkinter/__init__.py", "tkinter/ttk.py", "tkinter/simpledialog.py", "tkinter/filedialog.py", "tkinter/messagebox.py"))

    def _gap_stack(self, t0, t1):
        """Most frequent stack sampled in [t0, t1]: (key, label, share)."""
        with self._lock:
            inside = [s for t, s in self.samples if t0 <= t <= t1]
        if not inside:
            return None
        cnt = {}
        for s in inside:
            k = tuple(s[:6])
            cnt[k] = cnt.get(k, 0) + 1
        k, n = max(cnt.items(), key=lambda kv: kv[1])
        short = lambda fr: f"{fr[0]} ({os.path.basename(fr[1])}:{fr[2]})"
        top = k[0] if k else None
        c_level = bool(top) and (top[0] in ("mainloop", "update", "update_idletasks") or self._is_tk_file(top[1]))
        last_py = next((fr for fr in k if not self._is_tk_file(fr[1])), None)
        if c_level:
            lab = "[Tk C-level] last Python frame: " + (short(last_py) if last_py else "(none in top 6)")
            if top[0] not in ("mainloop", "update", "update_idletasks"):
                lab += f"  via tk call {top[0]}"
        else:
            lab = "[Python] "
        lab += "  <-  " + " < ".join(short(fr) for fr in k)
        return k, lab, n / len(inside)

    def add(self, kind, name, dur=0.0, depth=0, note=""):
        t = self.now() - dur
        if len(self.ev) >= self.CAP:
            self.dropped += 1
            return
        self.ev.append((t, kind, name, dur, self.post, depth, note, t < self.sw_until and self.post))

    def timed(self, kind, name_fn, note_fn=None):
        perf = self

        def deco(fn):
            @functools.wraps(fn)
            def w(*a, **k):
                t = time.perf_counter()
                perf.depth += 1
                try:
                    return fn(*a, **k)
                finally:
                    perf.depth -= 1
                    try:
                        nm = name_fn(fn, a, k)
                        perf.add(kind, nm, (time.perf_counter() - t) * 1000, perf.depth, note_fn(a, k) if note_fn else "")
                    except Exception:
                        pass
            return w
        return deco

    def install(self):
        perf = self
        T = self.timed
        self.start_sampler()
        tk.Misc.update = T("update", lambda f, a, k: "update() from " + _perf_caller(3))(tk.Misc.update)
        tk.Misc.update_idletasks = T("update", lambda f, a, k: "update_idletasks() from " + _perf_caller(3))(tk.Misc.update_idletasks)
        orig_after = tk.Misc.after

        def after(self_, ms, func=None, *args):
            if func is None:
                return orig_after(self_, ms)
            nm = getattr(func, "__qualname__", None) or getattr(func, "__name__", None) or repr(func)

            @functools.wraps(func)
            def cb(*a):
                t = time.perf_counter()
                perf.depth += 1
                try:
                    return func(*a)
                finally:
                    perf.depth -= 1
                    d = (time.perf_counter() - t) * 1000
                    if d >= 3 or not nm.endswith(("poll", "_hb")):
                        perf.add("after_idle" if ms == "idle" else "after", f"{nm} (scheduled {ms})", d, perf.depth)
            return orig_after(self_, ms, cb, *args)
        tk.Misc.after = after
        ttk.Style.theme_use = T("style", lambda f, a, k: "Style.theme_use" + (f"({a[1]})" if len(a) > 1 else "()"))(ttk.Style.theme_use)
        ttk.Style.configure = T("style", lambda f, a, k: f"Style.configure({a[1] if len(a) > 1 else ''})")(ttk.Style.configure)
        ttk.Style.map = T("style", lambda f, a, k: f"Style.map({a[1] if len(a) > 1 else ''})")(ttk.Style.map)
        try:
            import sv_ttk
            sv_ttk.set_theme = T("style", lambda f, a, k: "sv_ttk.set_theme")(sv_ttk.set_theme)
        except Exception:
            pass
        g = globals()
        g["apply_theme"] = T("theme", lambda f, a, k: "apply_theme")(apply_theme)
        for nm_, kind, nf in (("apply_layout", "layout", None), ("prerealize", "layout", None),
                              ("startup", "after", None), ("on_tab_changed", "tab", None)):
            setattr(App, nm_, T(kind, (lambda n: lambda f, a, k: "App." + n)(nm_))(getattr(App, nm_)))
        orig_retheme = T("theme", lambda f, a, k: "App.retheme")(App.retheme)

        def retheme(app, *a, **k):
            """V6.2: stage timing of one theme switch + the main-loop gaps in the 2 s after it."""
            i0, t0 = len(perf.stages), time.perf_counter()
            try:
                return orig_retheme(app, *a, **k)
            finally:
                t1 = time.perf_counter()
                sw = {"t": (t0 - PERF_T0) * 1000, "total": (t1 - t0) * 1000, "stages": [(x[2], x[1]) for x in perf.stages[i0:]],
                      "t_end": (t1 - PERF_T0) * 1000, "idle": None, "expose": None, "gaps": [], "args": a}
                perf.switches.append(sw)
                perf._th_pending = sw
                try:
                    app.root.after_idle(lambda: sw.__setitem__("idle", perf.now() - sw["t_end"]))
                except Exception:
                    pass
        App.retheme = retheme
        App.fill_chunked = T("list", lambda f, a, k: "list fill " + (getattr(a[1], "_w", str(a[1])) if len(a) > 1 else "?"),
                             lambda a, k: f"{len(a[2]) if len(a) > 2 else '?'} rows, container {'MAPPED' if _perf_mapped(a[1]) else 'unmapped'}")(App.fill_chunked)
        orig_setup = tk.BaseWidget._setup

        def _setup(self_, master, cnf):
            orig_setup(self_, master, cnf)
            if perf.post:
                try:                                              # V6.1.3: the Tk window does not exist yet here: no Tk call, never raises
                    perf.add("widget+", f"create {type(self_).__name__} {getattr(self_, '_w', '?')}", 0.0, perf.depth)
                except Exception:
                    pass
        tk.BaseWidget._setup = _setup
        orig_cfg = tk.Misc._configure

        def _configure(self_, cmd, cnf, kw):
            r = orig_cfg(self_, cmd, cnf, kw)
            if perf.post and (cnf or kw) and cmd == "configure":
                try:                                              # V6.1.3: the hook can never raise
                    perf.add("configure", f"{type(self_).__name__} {getattr(self_, '_w', '?')}", 0.0, perf.depth,
                             ",".join(map(str, list((kw or {}) if not isinstance(cnf, dict) else cnf)))[:60])
                except Exception:
                    pass
            return r
        tk.Misc._configure = _configure
        orig_dei = tk.Wm.wm_deiconify

        def dei(self_):
            perf.add("show", "deiconify", 0.0)
            return orig_dei(self_)
        tk.Wm.wm_deiconify = tk.Wm.deiconify = dei
        atexit.register(self.write)

    def attach(self, root):
        """After the main window exists: Map / Expose / tab switch / heartbeat / Ctrl+Shift+P."""
        self.root = root
        self.add("mark", "main window built (widgets created)")

        def on_map(e):
            if e.widget is root and self.map_t is None:
                self.map_t = self.now()
                self.add("mark", "FIRST <Map> of the main window")
                self.post = True

        def on_expose(e):
            if e.widget is root and not any(x[2] == "first <Expose>" for x in self.ev):
                self.add("mark", "first <Expose>")

        def th_expose(e):
            sw = self._th_pending
            if sw is not None and sw["expose"] is None:
                sw["expose"] = self.now() - sw["t_end"]
        root.bind_all("<Expose>", th_expose, add="+")
        root.bind("<Map>", on_map, add="+")
        root.bind("<Expose>", on_expose, add="+")
        root.bind_all("<<NotebookTabChanged>>", self.on_tab, add="+")
        root.bind_all("<Control-Shift-P>", lambda e: self.write(), add="+")
        root.bind_all("<Control-Shift-p>", lambda e: self.write(), add="+")
        self.hb_last = self.now()
        self._hb()

    def on_tab(self, e):
        try:
            self.sw_name = e.widget.tab(e.widget.select(), "text")
        except Exception:
            self.sw_name = "?"
        self.sw_until = self.now() + 500
        self.add("tab", f"TAB SWITCH to {self.sw_name} (widget creates / configures in the next 500 ms are tagged [switch])")

    def _hb(self):
        t = self.now()
        gap = t - self.hb_last - 20
        if gap > 50:
            self.add("gap", f"main-loop blocked {gap:.0f} ms", gap)
            try:
                gs = self._gap_stack(self.hb_last + 20, t)
                self.gap_stacks.append((gap, gs, t, self.sw_name if t < self.sw_until else ""))
                for sw in self.switches:
                    if sw["t_end"] - 50 <= t <= sw["t_end"] + 2000:
                        sw["gaps"].append((gap, gs[1] if gs else "(no samples)"))
            except Exception:
                pass
        self.hb_last = self.now()
        try:
            self.root.after(20, self._hb)
        except Exception:
            pass

    def header(self):
        """V6.2: one line with the environment facts that decide Tk drawing cost."""
        import platform
        r, bits = self.root, []
        def add(k, fn):
            try:
                bits.append(f"{k}={fn()}")
            except Exception as ex:
                bits.append(f"{k}=? ({type(ex).__name__})")
        add("OS", lambda: platform.platform() + (f" build {sys.getwindowsversion().build}" if os.name == "nt" else ""))
        add("Python", lambda: sys.version.split()[0] + f" {platform.architecture()[0]}")
        add("Tk", lambda: r.tk.call("info", "patchlevel"))
        def svv():
            import sv_ttk
            try:
                from importlib.metadata import version
                return version("sv-ttk")
            except Exception:
                return getattr(sv_ttk, "__version__", "installed")
        add("sv_ttk", svv)
        add("window", lambda: f"{r.winfo_width()}x{r.winfo_height()}")
        add("screen", lambda: f"{r.winfo_screenwidth()}x{r.winfo_screenheight()}")
        add("tk_scaling", lambda: r.tk.call("tk", "scaling"))
        add("ui_scale", lambda: UI_SCALE[0])
        add("theme", lambda: ("SIMPLE clam (MONTAGE_SIMPLE_THEME=1)" if SIMPLE_THEME else "Sun Valley") + f" [{ttk.Style(r).theme_use()}]")
        def dpi():
            if os.name != "nt":
                return "n/a (not Windows)"
            import ctypes
            names = {0: "UNAWARE", 1: "SYSTEM_AWARE", 2: "PER_MONITOR_AWARE"}
            out_ = []
            try:
                v = ctypes.c_int(-1)
                ctypes.windll.shcore.GetProcessDpiAwareness(0, ctypes.byref(v))
                out_.append("process=" + names.get(v.value, str(v.value)))
            except Exception as ex:
                out_.append(f"process=? ({type(ex).__name__})")
            try:
                out_.append("window_dpi=" + str(ctypes.windll.user32.GetDpiForWindow(r.winfo_id())))
            except Exception:
                pass
            try:
                out_.append("system_dpi=" + str(ctypes.windll.user32.GetDpiForSystem()))
            except Exception:
                pass
            return " ".join(out_)
        add("dpi_awareness", dpi)
        line = "ENV  " + "   ".join(bits)
        if "=? (" in line and getattr(self, "_hdr", None):      # window already destroyed (atexit write after on_close): keep the live one
            return self._hdr
        self._hdr = line
        return line

    def stage_table(self):
        L = ["STAGE TABLE (ms; start = ms since process start; thread shown; indent = nested inside the stage above)"]
        L += [f"  @{t:8.0f}  {d:8.1f} ms  {th:12.12}  {nm}" for t, d, nm, th in sorted(self.stages, key=lambda x: x[0])]
        L += ["MARKS (ms since process start)"] + [f"  @{t:8.0f}  {nm}" for t, nm in sorted(self.marks)]
        ocr = [x for x in self.stages if x[2].startswith("OCR engine creation")]
        L.append("OCR engine created before the window was shown: " + (
            "YES " + ", ".join(f"{x[1]:.0f} ms @{x[0]:.0f}" for x in ocr) if ocr and (self.map_t is None or ocr[0][0] < self.map_t) else "NO"))
        return L

    def gap_summary(self):
        agg = {}
        for gap, gs, t, swn in self.gap_stacks:
            k, lab = (gs[0], gs[1]) if gs else (None, "(no samples)")
            e = agg.setdefault(k, [0.0, 0, lab, []])
            e[0] += gap
            e[1] += 1
            if swn and swn not in e[3]:
                e[3].append(swn)
        L = [f"TOP 10 MAIN-LOOP GAP STACKS by total blocked time ({len(self.gap_stacks)} gaps > 50 ms; most frequent 10 ms sample in each gap, top 6 Python frames)"]
        for tot, n, lab, sw in sorted(agg.values(), key=lambda e: -e[0])[:10]:
            L.append(f"  {tot:7.0f} ms in {n:3d} gap(s){('  during tab switch to ' + '/'.join(sw)) if sw else ''}\n      {lab}")
        return L

    def switch_summary(self):
        L = ["THEME SWITCHES (stage durations in ms; 'idle' = first idle callback after retheme returned, 'Expose' = first <Expose> after it)"]
        for i, sw in enumerate(self.switches, 1):
            L.append(f"  #{i} @{sw['t']:.0f}: retheme total {sw['total']:.0f} ms; first idle after {sw['idle'] if sw['idle'] is None else round(sw['idle'])} ms; "
                     f"first Expose after {sw['expose'] if sw['expose'] is None else round(sw['expose'])} ms")
            L += [f"        {d:8.1f}  {nm}" for nm, d in sw["stages"]]
            L += [f"      gap in the 2 s after: {g:.0f} ms  {lab}" for g, lab in sw["gaps"]] or ["      (no main-loop gap > 50 ms in the 2 s after)"]
        return L if self.switches else L + ["  (none recorded: change accent / base in Settings while perflog runs)"]

    def write(self):
        try:
            ev = sorted(self.ev, key=lambda x: x[0])
            post = [x for x in ev if x[4]]
            top = sorted([x for x in ev if x[3] > 0], key=lambda x: -x[3])[:10]
            work = sum(x[3] for x in post if x[5] == 0 and x[1] != "gap")
            cnt = lambda kinds: sum(1 for x in post if x[1] in kinds)
            gaps = [x[3] for x in ev if x[1] == "gap"]
            sw = [x for x in post if x[7] and x[1] in ("widget+", "configure")]
            L = ["PERFLOG " + APP_VERSION + f"  (times in ms since module import; POST-SHOW = after the first main-window <Map> at "
                 + (f"{self.map_t:.0f} ms)" if self.map_t is not None else "never)"), self.header(), "", "SUMMARY"]
            L += self.stage_table() + [""] + self.gap_summary() + [""] + self.switch_summary() + ["", "Top 10 slowest events:"]
            L += [f"  {x[3]:8.1f} ms  @{x[0]:8.0f}  {x[1]:10} {x[2]} {x[6]}{'  POST-SHOW' if x[4] else ''}" for x in top]
            L += [f"Total POST-SHOW work: {work:.0f} ms (top-level events only, nested calls not double counted)",
                  f"POST-SHOW theme/style events: {cnt(('theme', 'style'))}   list fills: {cnt(('list',))}   after/after_idle: "
                  f"{cnt(('after', 'after_idle'))}   widget creates: {cnt(('widget+',))}   configures: {cnt(('configure',))}   "
                  f"layout calls: {cnt(('layout',))}   update calls: {cnt(('update',))}",
                  f"POST-SHOW widget creates/configures within 500 ms of a tab switch: {len(sw)}",
                  f"Longest main-loop blockage: {max(gaps) if gaps else 0:.0f} ms ({len(gaps)} gaps > 50 ms)", f"Events recorded: {len(ev)}"
                  + (f" (+{self.dropped} dropped past the cap)" if self.dropped else ""), "", "CHRONOLOGICAL"]
            body = [f"{x[0]:9.1f}  {'POST ' if x[4] else 'pre  '}{'[switch] ' if x[7] else ''}{x[1]:10} "
                    f"{(f'{x[3]:7.1f} ms ' if x[3] else '           ')}{'  ' * min(x[5], 4)}{x[2]} {x[6]}" for x in ev]
            txt = "\n".join(L + body)
            while len(txt.encode("utf-8", "replace")) > 290_000 and body:
                body = body[: int(len(body) * 0.9)]
                txt = "\n".join(L + body + ["... (truncated to stay under 300 KB)"])
            (HERE / "perflog.txt").write_text(txt, encoding="utf-8")
            return txt
        except Exception as ex:
            print("perflog write failed:", ex)


if os.environ.get("MONTAGE_PERFLOG") == "1" or (len(sys.argv) > 1 and sys.argv[1] == "perflog"):
    PERF = PerfLog()


def _perf_caller(depth=3):
    try:
        f = sys._getframe(depth)
        return f"{f.f_code.co_name}:{f.f_lineno}"
    except Exception:
        return "?"


def _perf_mapped(w):
    try:
        return bool(w.winfo_ismapped())
    except Exception:
        return False


def gui_main(start_tab=0):
    if tk is None:
        raise SystemExit("tkinter is missing. Re-run the python.org installer > Modify > tcl/tk and IDLE.")
    set_app_id()
    if PERF is not None:
        PERF.install()
    App(start_tab).root.mainloop()


def cmd_auto(args):
    mode = "dry" if (args.dry or args.plan_only) else "preview" if args.preview else "render"
    for g in ([args.game] if args.game else list(GAMES)):
        try:
            run_job(g, mode, args.force, seed=args.seed, maxq=True if args.max_quality else None, weekly=not args.plan_only)
        except Exception as ex:
            out(f"{g}: {ex}")


def _hide_child_consoles():
    """V5.5: started with pythonw (no console) every ffmpeg / git child would flash a console window - hide them. Only when
    there is no console of our own; 'python montage.py' is unchanged."""
    if os.name != "nt" or sys.stdout is not None:
        return
    flag = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    orig = subprocess.Popen.__init__

    def init(self, *a, **kw):
        kw["creationflags"] = kw.get("creationflags", 0) | flag
        orig(self, *a, **kw)
    subprocess.Popen.__init__ = init


def _lower_child_priority():
    """V6.1 (Windows only): ffmpeg / ffprobe children run at below-normal priority so the GUI stays responsive while a scan or render
    runs. No change on Linux, no change to worker counts or encoder settings."""
    flag = getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0x00004000)
    if os.name != "nt":
        return
    orig = subprocess.Popen.__init__

    def init(self, args, *a, **kw):
        try:
            exe = os.path.basename(str(args[0] if isinstance(args, (list, tuple)) else str(args).split()[0])).lower()
            if exe.startswith(("ffmpeg", "ffprobe")):
                kw["creationflags"] = kw.get("creationflags", 0) | flag
        except Exception:
            pass
        orig(self, args, *a, **kw)
    subprocess.Popen.__init__ = init


def update_on_start():
    """V5.5: optional (Settings > Check for updates on start, off by default): `git pull --ff-only` once, before the GUI opens;
    when the code changed the app restarts itself once on the new code. Nothing runs in the background."""
    if os.environ.get("MONTAGE_UPDATED") or not (HERE / ".git").exists() or not load_config().get("update_on_start"):
        return
    git = shutil.which("git")
    if not git:
        out("update on start: git not found - skipped")
        return

    def run(*a):
        return subprocess.run([git, "-C", str(HERE)] + list(a), capture_output=True, text=True, timeout=60,
                              stdin=subprocess.DEVNULL)
    try:
        before = run("rev-parse", "HEAD").stdout.strip()
        r = run("pull", "--ff-only")
        after = run("rev-parse", "HEAD").stdout.strip()
        out(f"update on start: git pull {'OK' if r.returncode == 0 else 'FAILED'} - "
            f"{'updated ' + before[:7] + ' -> ' + after[:7] if before != after else 'already up to date'}"
            + ("" if r.returncode == 0 else f" ({(r.stderr or r.stdout).strip()[:200]})"))
        if r.returncode == 0 and before != after:
            os.environ["MONTAGE_UPDATED"] = "1"
            os.execv(sys.executable, [sys.executable] + sys.argv)
    except SystemExit:
        raise
    except Exception as ex:
        out(f"update on start: skipped ({ex})")


def main():
    _hide_child_consoles()
    _lower_child_priority()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    setup_path()
    ap = argparse.ArgumentParser(prog="montage.py")
    sp = ap.add_subparsers(dest="cmd")
    sp.add_parser("gui").set_defaults(fn=lambda a: gui_main())
    sp.add_parser("pick").set_defaults(fn=lambda a: gui_main(1))
    sp.add_parser("perflog", help="V6.0: start the GUI with the timeline recorder; writes perflog.txt on exit / Ctrl+Shift+P").set_defaults(fn=lambda a: gui_main())
    sp.add_parser("setup").set_defaults(fn=cmd_setup)
    sp.add_parser("selfcheck").set_defaults(fn=cmd_selfcheck)
    sp.add_parser("selftest").set_defaults(fn=lambda a: selftest_detection(load_config()))
    i = sp.add_parser("inventory")
    i.add_argument("--list", action="store_true")
    i.add_argument("--rescan", action="store_true")
    i.set_defaults(fn=cmd_inventory)
    b = sp.add_parser("calibrate-bars")
    b.add_argument("clips", nargs="*")
    b.add_argument("--sample", type=int, default=30)
    b.set_defaults(fn=cmd_calibrate_bars)
    c = sp.add_parser("calibrate")
    c.add_argument("game", choices=GAMES)
    c.add_argument("screenshot")
    for o in ("--region", "--row", "--name"):
        c.add_argument(o, help="optional x,y,w,h in 1920x1080 px instead of dragging")
    c.set_defaults(fn=cmd_calibrate)
    sc = sp.add_parser("scan")
    sc.add_argument("--game", choices=GAMES)
    sc.add_argument("--limit", type=int, default=0)
    sc.add_argument("--rescan", action="store_true")
    sc.add_argument("--confirm-region-rescan", action="store_true", help="V6.7.6: also rescan Valorant clips whose entries were scanned with another killfeed region")
    sc.set_defaults(fn=cmd_scan)
    rg = sp.add_parser("regioncheck", help="V6.7.6: killfeed region of a game, its hash, backups, and the region hashes stored in the cache")
    rg.add_argument("game", choices=GAMES)
    rg.set_defaults(fn=cmd_regioncheck)
    rt = sp.add_parser("regiontest", help="V6.8: scan CS2 clips under several killfeed regions in a temporary data folder and compare")
    rt.add_argument("game", choices=["cs2"])
    rt.add_argument("--clips", help="file with clip names, one per line")
    rt.add_argument("--regions", help="calibrated,default,wide (default: all three)")
    rt.add_argument("--out", help="folder for regiontest_cs2.txt and regiontest_images (default: next to montage.py)")
    rt.set_defaults(fn=cmd_regiontest)
    rd = sp.add_parser("regiondefault", help="V6.8: save a region as the game's saved default (used by Reset to default / --use default)")
    rd.add_argument("game", choices=GAMES)
    rd.add_argument("target", help="<hash> | current | backup:<file> | file:<path>")
    rd.set_defaults(fn=cmd_regiondefault)
    bc = sp.add_parser("bordercache", help="V6.8.1: build the CS2 red-border row sidecars (montage_data\\cs2_rows_v1)")
    bc.add_argument("game", choices=["cs2"])
    bc.add_argument("--all", action="store_true", help="every CS2 clip in the clip folders, existing sidecars rebuilt (default: scanned clips without a sidecar)")
    bc.set_defaults(fn=cmd_bordercache)
    rw = sp.add_parser("rowdebug", help="V6.8.1: CS2 red-border tracks of a clip, their classification, the old name-based kills and the difference")
    rw.add_argument("game", choices=["cs2"])
    rw.add_argument("clip", nargs="?", help="clip file name (or part of it) or path")
    rw.add_argument("--all", action="store_true", help="one table of every cached CS2 clip, sorted by the largest difference (rowdebug_cs2.txt)")
    rw.add_argument("--rebuild", action="store_true", help="rebuild the sidecar(s) first")
    rw.set_defaults(fn=cmd_rowdebug)
    fc = sp.add_parser("fpscheck", help="V6.9.3: frame rate of the clips of the newest dry plan (or --all cached clips) and how many would be interpolated (read-only)")
    fc.add_argument("game", nargs="?", choices=GAMES)
    fc.add_argument("--limit", type=int, default=0)
    fc.add_argument("--all", action="store_true")
    fc.set_defaults(fn=cmd_fpscheck)
    fcc = sp.add_parser("fpscontent", help="V6.9.6: EFFECTIVE on-screen fps per take (timestamps, VFR gaps, duplicated frames, slow-mo); read-only, writes fpscontent.txt")
    fcc.add_argument("target", nargs="*", help="a montage .mp4 (uses its .plan.json), or clip names")
    fcc.add_argument("--all", action="store_true")
    fcc.add_argument("--limit", type=int, default=0)
    fcc.set_defaults(fn=cmd_fpscontent)
    ib = sp.add_parser("interpbench", help="V6.9.6: seconds per source second of the mci / blend interpolation on this PC (5 s sample, writes nothing)")
    ib.add_argument("clip", nargs="?")
    ib.set_defaults(fn=cmd_interpbench)
    sm = sp.add_parser("songmapcompare", help="V6.9.5: find the songs where SONGMAP V1 and V2 disagree most and write listening material (compare_out/)")
    sm.add_argument("target", nargs="?", help="a song file or a list.txt (default: choose songs automatically)")
    sm.add_argument("--auto", type=int, nargs="?", const=10, default=None, help="pick the N most suspicious songs (default 10)")
    sm.add_argument("--songs-dir", help="analyse this folder instead of the playlist / songs folder")
    sm.add_argument("--seed", type=int, help="seed of the random sample of the songs folder (printed on every run, reusable)")
    sm.add_argument("--song", action="append", help="analyse the songs whose file name contains this text (repeatable)")
    sm.add_argument("--out", help="output folder (default compare_out next to montage.py)")
    sm.set_defaults(fn=lambda a: __import__("songmap_compare").main(a))
    pc = sp.add_parser("pairscan", help="V6.9: candidate neighbour clip pairs among all cached CS2 clips (read-only, writes pairscan_cs2.txt)")
    pc.add_argument("game", choices=["cs2"])
    pc.add_argument("--limit", type=int, default=30)
    pc.set_defaults(fn=cmd_pairscan)
    go = sp.add_parser("grouporder", help="V6.9.6: the fight group (pair partners) of a CS2 clip and the order the planner will stitch it in (read-only, writes grouporder.txt)")
    go.add_argument("game", choices=["cs2"])
    go.add_argument("clip", help="clip file name (or part of it)")
    go.set_defaults(fn=cmd_grouporder)
    rh = sp.add_parser("rescanhash", help="V6.8.1: rescan only the clips that have an entry under <hash> and none under the current region")
    rh.add_argument("game", choices=GAMES)
    rh.add_argument("hash")
    rh.add_argument("--confirm", action="store_true", help="really scan (without it only the list and the count are printed)")
    rh.set_defaults(fn=cmd_rescanhash)
    rr = sp.add_parser("regionrestore", help="V6.7.6: list / set the killfeed region (never chosen automatically)")
    rr.add_argument("game", choices=GAMES)
    rr.add_argument("--use", help="<hash> | default | backup:<file> | file:<path>")
    rr.set_defaults(fn=cmd_regionrestore)
    v = sp.add_parser("verify")
    v.add_argument("game", choices=GAMES)
    v.set_defaults(fn=cmd_verify)
    for name in ("auto", "plan"):
        a_ = sp.add_parser(name)
        a_.add_argument("--game", choices=GAMES)
        a_.add_argument("--force", action="store_true")
        a_.add_argument("--dry", action="store_true")
        a_.add_argument("--preview", action="store_true")
        a_.add_argument("--max-quality", action="store_true")
        a_.add_argument("--seed", type=int)
        a_.set_defaults(fn=cmd_auto, plan_only=(name == "plan"))
    rcp = sp.add_parser("rendercheck", help="check a finished montage on the file (duration, music, kills, tails, ending)")
    rcp.add_argument("file")
    rcp.set_defaults(fn=cmd_rendercheck)
    scc = sp.add_parser("synccompare", help="V4 vs V5 kill placement, measured on rendered files (testdata/ if present)")
    scc.add_argument("--game", choices=GAMES)
    scc.add_argument("--seed", type=int, default=11)
    scc.set_defaults(fn=cmd_synccompare)
    scp = sp.add_parser("songcheck", help="score each song's beat grid / drops (testdata MP3s if present, else your MP3 folder)")
    scp.add_argument("paths", nargs="*")
    scp.set_defaults(fn=cmd_songcheck)
    sp.add_parser("cfgdump", help="print the config file path + contents").set_defaults(fn=cmd_cfgdump)
    sp.add_parser("timeanchor", help="V6.9.7: what the file-name time means (clip START or END) per naming scheme; read-only, writes timeanchor.txt").set_defaults(fn=cmd_timeanchor)
    sp.add_parser("ledger", help="V6.9.7: reprint the last run's kill ledger (read-only; writes ledger.txt only)").set_defaults(fn=cmd_ledger)
    sp.add_parser("detectcheck", help="V4 vs V5 kill classification on all cached OCR data").set_defaults(fn=cmd_detectcheck)
    st_ = sp.add_parser("smoketest", help="offline self-checks: GUI buttons + OCR on generated frames")
    st_.add_argument("--no-gui", action="store_true")
    st_.add_argument("--no-render", action="store_true", help="skip the end-to-end render sync test")
    st_.set_defaults(fn=cmd_smoketest)
    t = sp.add_parser("tag")
    t.add_argument("path")
    t.add_argument("game", choices=list(GAMES) + ["auto"])
    t.set_defaults(fn=cmd_tag)
    args = ap.parse_args()
    if not getattr(args, "fn", None) or args.cmd in ("gui", "pick"):
        update_on_start()
    if not getattr(args, "fn", None):
        gui_main()
        return
    try:
        args.fn(args)
    except SystemExit:
        raise
    except Exception as ex:
        out(f"ERROR: {ex}\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
