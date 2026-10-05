r"""
montage.py - Valorant / CS2 kill-montage builder synced to a song. One file + montage_data\ folder. Personal use.
Never modifies source clips. No network at runtime (only the optional one-click pip install). No admin needed.

GET IT RUNNING (Windows 11, Python 3.12) - in cmd.exe:
    cd C:\Users\fireaxe\Desktop\CLAUDECODE
    git clone https://github.com/fireaxe77/montager.git montager      (later updates: cd montager && git pull origin main)
    cd montager
    python -m pip install --user numpy opencv-python librosa soundfile scipy mutagen rapidfuzz rapidocr-onnxruntime
    python montage.py                    <- opens the GUI (the app also offers a one-click install of missing packages)
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

APP_VERSION = "V5.5"
HERE = Path(__file__).resolve().parent
DATA = HERE / "montage_data"
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
    "length_s": "optimal",          # "optimal" (default) or seconds (30-120)
    "update_on_start": False,       # V5.5: run `git pull` when the app starts (Settings; off by default)
    "style": "auto",                # auto (default) | hype | aggressive | smooth | cinematic | chill | mix | random
    "placement": "v5",              # v5 = frame-exact kill moments on the song-map grid; v4 = V4 timing (see synccompare)
    "quality": "nvenc",             # nvenc | max
    "theme": "light",               # light (default) | dark | auto
    "scan_workers": 2,              # clips OCR-scanned in parallel
    # V5: explicit clip folders; the game comes from the list a folder is in (replaces folder-name matching)
    "clip_dirs": {"valorant": [r"E:\Movies\VALORANT\Clips", r"E:\Movies\LEGACY\Valorant"],
                  "cs2": [r"E:\Movies\2026\Counter-strike 2", r"E:\Movies\2026\cs clips",
                          r"E:\Movies\Movies 2025\Counter-strike 2", r"E:\Movies\LEGACY\Counter-strike 2"]},
    "game_under_music_db": 4.0,     # loudness-normalised game audio sits this many dB under the music
    "duck_db": 4.0,                 # music ducked this many dB around each kill
    "ui_scale": 1.0,                # GUI font / row height scale
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
    if cfg.get("cfg_version", 1) < 3:                 # V4: light theme is the default (dark stays optional in Settings)
        if cfg.get("theme") in (None, "auto"):
            cfg["theme"] = "light"
        cfg["cfg_version"] = 3
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
    for p in sorted(set(walk_files(roots, VIDEO_EXT, MIN_VIDEO, cfg))):
        try:
            if tag_game(p, cfg)[0] and os.path.getsize(p) <= max_b:
                paths.append(p)
        except OSError:
            pass
    paths.sort()
    cache = {} if rescan else load_json(CLIPS_CACHE, {})
    todo = [p for p in paths if rescan or file_key(p) not in cache or cache[file_key(p)].get("bar_sig") != json.dumps(cfg["bar"])]
    out(f"  {len(paths)} clips found" + (f", {len(todo)} new/changed to probe" if todo else " (all cached)"))
    recs = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, (p, rec) in enumerate(ex.map(lambda p: analyse_clip(p, cache, rescan, cfg["bar"]), paths), 1):
            recs.append(rec)
            if todo and i % 50 == 0:
                out(f"    {i}/{len(paths)}")
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


def scan_audio(cfg, rescan=False):
    mp3 = cfg.get("mp3_dir")
    paths = sorted(walk_files([mp3], AUDIO_EXT, 0, cfg)) if mp3 and os.path.isdir(mp3) else []
    cache = {} if rescan else load_json(AUDIO_CACHE, {})
    recs = []
    for p in paths:
        try:
            k = file_key(p)
        except OSError:
            continue
        if k not in cache:
            a, t, d = read_tags(p)
            if not t:
                fa, ft = parse_filename(p)
                a, t = a or fa, ft
            cache[k] = {"path": p, "artist": a, "title": t, "dur": d}
        recs.append(cache[k])
    save_json(AUDIO_CACHE, {file_key(r["path"]): cache[file_key(r["path"])] for r in recs})
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


def match_playlist(rows, audio, cfg):
    """ONE-TO-ONE best global assignment of MP3 files to CSV rows. Each file (ID3 title if present, else the filename) is compared
    with 'Track', 'Artist - Track' and 'Track - Artist' using rapidfuzz WRatio; duration within 3 s adds a little."""
    import numpy as np
    from rapidfuzz import fuzz, process
    from scipy.optimize import linear_sum_assignment
    if not rows or not audio:
        return [], list(rows)
    names = []
    for a in audio:
        stem = re.sub(r"^\s*\d{1,3}[\s._-]+", "", Path(a["path"]).stem)
        names.append(clean(a.get("title", "")) or clean(stem) or stem.lower())
    t1 = [clean(r["title"]) or r["title"].lower() for r in rows]
    t2 = [clean(f"{r['artist']} - {r['title']}") for r in rows]
    t3 = [clean(f"{r['title']} - {r['artist']}") for r in rows]
    M = np.zeros((len(audio), len(rows)))
    for i, nm in enumerate(names):
        M[i] = np.maximum.reduce([process.cdist([nm], t, scorer=fuzz.WRatio)[0] for t in (t1, t2, t3)])
        da = audio[i].get("dur") or 0
        if da:
            for j, r in enumerate(rows):
                if r.get("dur") and abs(da - r["dur"]) <= 3:
                    M[i, j] += 2.0
    rk = lambda r: r.get("uri") or f"{r['artist']} - {r['title']}"
    idx = {a["path"]: i for i, a in enumerate(audio)}
    for path, key in cfg.get("song_overrides", {}).items():              # manual overrides from the Songs view
        i = idx.get(path)
        j = next((k for k, r in enumerate(rows) if rk(r) == key), None)
        if i is not None and j is not None:
            M[i, :], M[:, j] = -1, -1
            M[i, j] = 1000
    ri, ci = linear_sum_assignment(-M)
    matched, got = [], set()
    for i, j in zip(ri, ci):
        sc = M[i, j]
        if sc >= cfg.get("match_floor", 60):
            matched.append((rows[j], audio[i], int(min(sc, 100) if sc < 1000 else 100)))
            got.add(j)
    return matched, [r for j, r in enumerate(rows) if j not in got]


def write_song_matches(audio, matched):
    """montage_data\\song_matches.csv: file, matched track, score, flag (under 85 = check it)."""
    by = {a["path"]: (r, sc) for r, a, sc in matched}
    with open(DATA / "song_matches.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["file", "matched track", "artist", "score", "flag"])
        for a in sorted(audio, key=lambda a: a["path"].lower()):
            r, sc = by.get(a["path"], (None, 0))
            w.writerow([a["path"], r["title"] if r else "", r["artist"] if r else "", sc,
                        "NO MATCH" if not r else "CHECK (under 85)" if sc < 85 else "ok"])


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


def name_match(text):
    """(score 0-100, start index in text) of the best FIREAXE match. rapidfuzz partial_ratio, case-insensitive; a text shorter
    than 5 letters must match as a whole (so 'fire' or 'axe' alone never counts)."""
    from rapidfuzz import fuzz
    t = (text or "").lower()
    if len(_alnum(t)) < 5:
        return float(fuzz.ratio(_alnum(t), MY_NAME)), 0
    if len(t) <= len(MY_NAME):
        return float(fuzz.ratio(t, MY_NAME)), 0
    al = fuzz.partial_ratio_alignment(MY_NAME, t)
    return float(al.score), int(al.dest_start)


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
        d["ks"], kpos = name_match(d["ktext"]) if d["killer"] else (0.0, 0)
        d["vs"], _ = name_match(d["vtext"]) if d["victim"] else (0.0, 0)
        if game == "cs2":                                  # V5.42B: '火斧' is my name too (garbled 'fireaxe' before it is part of it)
            for side in ("k", "v"):
                txt = d[side + "text"]
                i = txt.find(MY_NAME_CS2)
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


def _relink_or_explain(jobs, dets, cache, cfg):
    """V5.5: a kill cache survives updates. For every clip with no entry under today's key: a cached entry of the same file
    (name, size, time) with the same calibration + bars (the clip folder moved) is re-linked, not rescanned; the rest are
    rescanned and the log says WHY (calibration changed / black-bar crop changed / cache format changed / clip file changed /
    new clip). Returns the jobs that really need a scan."""
    idx = _cache_index()
    paths = {e[2].lower() for v in idx.values() for e in v}
    todo, why, linked = [], {}, 0
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
        why.setdefault(reason, []).append(Path(path).name)
        todo.append((r, g))
    if linked:
        out(f"kill cache: {linked} clip(s) re-linked (same file, new folder / path) - not rescanned")
    if why:
        out("rescanning: " + "; ".join(f"{k} ({len(v)})" for k, v in why.items()))
        for k, v in why.items():
            for n in v[:15]:
                out(f"  rescanning {n}: {k}")
    return todo


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
    e = {"v": CACHE_V, "ocr": ocr, "frames": n, "size": [det.dw, det.dh], "region": det.d["region"],
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


def merge_variants(tracks):
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
    sc, st = name_match(t)
    if sc >= NAME_MIN:
        t = t[:st] + t[st + len(MY_NAME):]
    t = t.replace(MY_NAME_CS2, "")
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
    kills.sort(key=lambda k: k["t"])
    keep = []
    pre = [dict(p, hits=9) for p in pre]                       # V5.5: kills whose row was already on screen at 0:00 are known kills too
    for k in kills:
        v = _alnum(k.get("victim") or "").lower()
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
            qv = _alnum(q.get("victim") or "").lower()
            if v and qv and len(qv) >= 3 and fuzz.ratio(v, qv) >= 85 and k["t"] > q["t"] and \
                    not any(q["t"] < rv < k["t"] for rv in revives):
                why = f"'{k.get('victim')}' was already killed {k['t'] - q['t']:.1f} s earlier in this fight, no revive between ({k['row']})"
                break
        for q in (seen if why is None else ()):
            qv = _alnum(q.get("victim") or "").lower()
            if k["t"] - q["t"] < 0.5 and v and qv and fuzz.ratio(v, qv) >= 70:
                why = f"same kill read twice ({q['row']} / {k['row']} {k['t'] - q['t']:.2f} s apart)"
                break
        if why is None and k["hits"] <= 2:
            text = _alnum(left + v).lower()
            for q in seen:
                qv = _alnum(q.get("victim") or "").lower()
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
    tracks = merge_variants(tracks)
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


def gun_onsets(rec, cache=None):
    """Gunshot-like transients in the clip's game audio: [[t, strength], ...] on the container timeline. None = no audio."""
    if not rec.get("audio"):
        return None
    import numpy as np
    key = file_key(rec["path"]) + "o1"
    cache = cache if cache is not None else load_json(ONSET_CACHE, {})
    if key in cache:
        return cache[key]
    import librosa
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", rec["path"], "-map", f"0:a:{int(rec.get('a_stream', 0))}", "-vn", "-ac", "1", "-ar", "22050",
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
    todo = [it["rec"] for it in pool_items if it["rec"].get("audio") and file_key(it["rec"]["path"]) + "o1" not in cache]
    if todo:
        out(f"  analysing gunshots in {len(todo)} clips ...")
        res = {}
        with ThreadPoolExecutor(max_workers=4) as ex:
            for i, (r, o) in enumerate(zip(todo, ex.map(lambda r: gun_onsets(r, {}), todo)), 1):
                res[file_key(r["path"]) + "o1"] = o
                progress(i / len(todo), "gunshot analysis")
        cache.update(res)
        save_json(ONSET_CACHE, cache)
    st = {"raw": 0, "no_shot": 0, "death_lock": 0, "kept": 0}
    lock = float(cfg.get("death_lock_s", 8.0))
    for it in pool_items:
        ons = gun_onsets(it["rec"], cache)
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
                if k.get("needs_shot"):
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
def save_region(game, region_frac):
    """Optional calibration = only the killfeed REGION (fractions of the content rect). Other keys of an older file are kept."""
    x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in region_frac)
    if x1 - x0 < 0.05 or y1 - y0 < 0.03:
        raise ValueError("killfeed box too small")
    p = DATA / f"detect_{game}.json"
    d = load_json(p, {}) or {}
    d["region"] = [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]
    d["ocr"] = True
    save_json(p, d)
    return d["region"]


def reset_region(game):
    p = DATA / f"detect_{game}.json"
    d = load_json(p, {}) or {}
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


def run_scan(cfg, games=None, paths=None, limit=0, rescan=False):
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
        jobs = _relink_or_explain(jobs, dets, cache, cfg)
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
            cache.put(kills_key(r, g, dets[g]), res)           # saved the moment this clip finishes
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
                a = analyse_entry(res, cfg, g)
                out(f"[{done}/{len(jobs)}] {g:8} {len(a['kills'])} kills {' '.join(ts(k['t']) for k in a['kills']) or '-'}"
                    f" | rows found {a['rows_max']} max/frame, {a['ocr_calls']} OCR calls | best name killer-side {a['best_k']:.2f},"
                    f" victim-side {a['best_v']:.2f} | rect {content_rect(r, cfg)} crop {'yes' if r.get('bars') else 'no'} | {name} ({res['secs']}s)")
                for m in a["mine"]:
                    out(f"      my row @ {ts(m['t'])} {m['row']} -> {m['verdict'].upper()}: {m['why']} ({m['hits']} sightings)")
    out(f"scan finished: {done} in {time.time() - t0:.0f}s, errors {errs}")
    return done


def cmd_scan(args):
    run_scan(load_config(), [args.game] if args.game else None, None, args.limit, args.rescan)


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
    for r in scan_clips(cfg):
        if r.get("error") or not r.get("w") or r.get("game") != game or (ps is not None and r["path"] not in ps):
            continue
        if any(x in r["path"].lower() for x in exc):
            continue
        stats["tagged"] += 1
        e = cache.get(kills_key(r, game, det))
        if not e or e.get("error"):
            continue
        stats["scanned"] += 1
        a = analyse_entry(e, cfg, game)
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


def song_pool(cfg):
    """Matched playlist songs that have a file (plus the unmatched list). Falls back to every audio file."""
    audio = scan_audio(cfg)
    csvp, rows, col = read_playlist(cfg)
    songs, unmatched = {}, []
    if rows:
        matched, unmatched = match_playlist(rows, audio, cfg)
        for r, a, sc in matched:
            added = parse_added(r["added"]) if r["added"] else None
            old = songs.get(a["path"])
            if old is None or (added and (old["added"] is None or added > old["added"])):
                songs[a["path"]] = {"path": a["path"], "artist": r["artist"], "title": r["title"], "added": added,
                                    "csv_bpm": r.get("tempo") or None, "energy": r.get("energy"), "dance": r.get("dance"), "score": sc}
        try:
            write_song_matches(audio, matched)
        except Exception as ex:
            out(f"could not write song_matches.csv: {ex}")
    if rows:
        wk = [r for r in rows if r["added"] and parse_added(r["added"]) and (datetime.datetime.now() - parse_added(r["added"])).days < cfg.get("week_days", 7)]
        have = {id(r) for r, a, sc in matched}
        out(f"songs: {len(rows)} CSV tracks, {len(matched)} matched to an MP3, {len(unmatched)} unmatched; "
            f"this week: {len(wk)} added, {sum(1 for r in wk if id(r) in have)} with MP3")
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
        an = analyse_song(forced, (next((x for x in songs if x['path'] == forced), {}) or {}).get('csv_bpm'))
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
                an = analyse_song(s["path"], s.get("csv_bpm"))
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


def clip_audio(rec):
    """{'stream': index of the audio stream with the most game sound (loudest), 'lufs': its loudness} - cached."""
    if not rec.get("audio"):
        return {"stream": None, "lufs": None}
    cache = load_json(LOUD_CACHE, {})
    key = file_key(rec["path"])
    if key in cache:
        return cache[key]
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
    return best


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
            items.append(dict(it, kills=sorted(ks, key=lambda k: k["t"]), ctime=clip_time(it["rec"]["path"])))
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
    groups, used = [], set()
    for i, a in enumerate(items):
        if i in used:
            continue
        g = [(a, 0.0)]
        used.add(i)
        for j in range(i + 1, len(items)):
            b = items[j]
            if j in used:
                continue
            near = b["ctime"] - a["ctime"] <= 60 + a["rec"].get("dur", 0)
            off = None
            for (m, mo) in g:
                o = _victim_offset(m["kills"], b["kills"], rf) if near else None
                if o is not None and abs(b["ctime"] - m["ctime"]) <= 60 + max(m["rec"].get("dur", 0), b["rec"].get("dur", 0)):
                    off = mo + o
                    break
                o = _same_kills(m, b, rf, refine)          # V5.42B: same kills = same event, whatever the file times say
                if o is not None:
                    off = mo + o
                    notes.append(f"same kills in two files: {Path(m['rec']['path']).name} = {Path(b['rec']['path']).name} "
                                 "(one event, never placed twice)")
                    break
            if off is not None:
                g.append((b, off))
                used.add(j)
        groups.append(g)
    evs = []
    for g in groups:
        # union of kills on the timeline of the group's first clip (kills of the same victim within 1.5 s are one kill)
        allk = []
        for it, off in g:
            for k in it["kills"]:
                tt = k["t"] + off
                if not any(abs(tt - u["tt"]) <= 1.5 and _alnum(u.get("victim", "").lower()) == _alnum(k.get("victim", "").lower())
                           for u in allk):
                    allk.append(dict(k, tt=tt, src=it, off=off))
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
        best_ev = None
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
            if ev and (best_ev is None or ev["score_pre"] > best_ev["score_pre"]):
                best_ev = ev
        if best_ev:
            evs.append(best_ev)
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
                    "victim": k.get("victim", ""), "hs": bool(k.get("hs")), "has_shot": bool(k.get("shot"))})
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
    if len(spans) > 1:
        chain = [spans[0]]
        for s_ in spans[1:]:
            if s_["start"] <= chain[-1]["end"] - 0.1 and s_["end"] > chain[-1]["end"]:
                chain.append(s_)
        spans = chain
        ok_all = True
        for i in range(len(spans) - 1):
            cut = round((max(spans[i]["start"], spans[i + 1]["start"]) + spans[i]["end"]) / 2, 4)
            ok, nshift, why = verify_stitch((spans[i], spans[i + 1]), cut) if verify else (True, spans[i + 1]["shift"], "not checked")
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
                return ev
            return None
    cover_start, cover_end = spans[0]["start"], spans[-1]["end"]
    keep = [i for i, (t, r) in enumerate(zip(times, rows)) if cover_start + 0.05 <= t and r <= cover_end - 0.05]
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
    """'Optimal': the strong material decides the length (no padding with weak kills), 30-120 s."""
    est = lambda e: 2 * bd + e["span"] + 0.4
    strong = [e for e in events if not e.get("plain")]
    L = sum(est(e) for e in strong)
    used = "strong events"
    if L < 30:
        L = sum(est(e) for e in events)
        used = "all events (little strong material)"
    L = max(30.0, min(120.0, L))
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
    if optimal and manual:                                 # V5.42B: optimal_fit() below decides (80-150 s, never past the song)
        target = min(OPT_RANGE[1], song_end - float(bt[0]))
    elif optimal:
        target = optimal_length([e for e in evs], bd, notes)
    else:
        target = max(30.0, min(120.0, float(target_s)))
    strong = [e for e in evs if not e.get("plain")]
    plain = [e for e in evs if e.get("plain")]
    est = lambda e: 2 * bd + e["span"] + 0.4
    if manual:
        strong += plain                                    # Manual: every ticked clip counts
    elif sum(est(e) for e in strong) < target and plain:
        strong += plain
        notes.append(f"{len(plain)} plain single kills used (not enough multikills / headshots)")
    elif plain:
        notes.append(f"{len(plain)} plain single kills left out (enough better material)")
    cap_t = int(min(120.0, target * 1.1) / td) if target else 10 ** 9
    if manual and optimal:                                 # ticked clips: optimal_fit() decides what fits
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
    if manual and optimal:                                 # V5.42B: THE shared Optimal rule picks length, section and clips
        fit = optimal_fit(usable, an, rname)
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
    if cut_len and not (manual and optimal):
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
    if left and not (manual and optimal):
        notes.append(f"{len(left)} events left out to keep the montage near {target:.0f} s: " + ", ".join(nm(e) for e in left))
    if left_song and not (manual and optimal):
        notes.append(f"SONG TOO SHORT: {len(left_song)} events did not fit before the song ends: " + ", ".join(nm(e) for e in left_song))
    end_take = None
    if ending is not None:
        end_take = place_end(ending, c)
        if end_take:
            takes.append(end_take)
        else:
            notes.append("the planned ending clip could not be placed before the song ends; the last take ends the montage")
            left_song.append(ending)
    if manual and optimal and (cut_len or left or left_song) and takes:
        # V5.41 Optimal fits the song: clips that did not fit after the drop go in front (the section starts earlier), strongest
        # first, while the montage stays within the 120 s / music-available target; the rest are listed as not fitting
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
                   "left_out": [] if manual and optimal else [nm(e) for e in cut_len + left],
                   "song_short": [nm(e) for e in (cut_len + left + left_song if manual and optimal else left_song)],
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
            au = clip_audio(r) if r.get("audio") else {"stream": None, "lufs": None}
            gdb, lift = _game_gain(cfg, song_lufs, au["lufs"])
            srcs.append({"path": p["path"], "shift": p.get("shift", 0.0), "rect": content_rect(r, cfg), "wh": [r["w"], r["h"]],
                         "audio": bool(r.get("audio")), "a_stream": au["stream"] or 0, "lufs": au["lufs"], "gain_db": gdb,
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
            "lock": 1.0}


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
             " | game " + ", ".join(f"{s_['gain_db']:+.1f} dB" + (f" (lift {s_['lift_db']:+.1f})" if s_.get("lift_db") else "")
                                    for s_ in t["srcs"] if s_["audio"])
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
    while True:
        inputs, graph = build_filter(p, cfg, preview, fx)
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
    pool, st = game_pool(cfg, game, set(paths) if manual else None)
    au = st["audio"]
    out(f"{game}: {st['tagged']} clips in included folders, {st['scanned']} scanned, {st['with_kills']} with detected kills; "
        f"{au['raw']} kills found, {au['no_shot']} without a heard gunshot (kept, audio is only a bonus), {au['death_lock']} dropped after my death, {au['kept']} usable")
    if not pool:
        raise RuntimeError(f"{st['tagged']} {game} clips, {st['scanned']} scanned, but 0 usable kills "
                           f"({au['raw']} found, {au['death_lock']} dropped after my death; rejected rows are listed above with their reasons). "
                           "Run Troubleshoot > Self-test detection to see the scores, or scan more clips.")
    seed = int(seed) if seed else random.randrange(1, 10 ** 6)
    events, notes = build_events(pool, game, cfg, random.Random(seed))
    if not events:
        raise RuntimeError("no usable kill events (utility kills are excluded)")
    songs, unmatched, csvname = song_pool(cfg)
    song, an, sinfo, runners = pick_song(cfg, game, songs, forced=song_path)
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
    if plan["duration"] > plan["song"]["section_s"] + 1e-3:              # never render past the end of the music
        raise RuntimeError(f"plan is {plan['duration']:.1f} s but the song only has {plan['song']['section_s']:.1f} s from "
                           f"{ts(plan['song']['start_t'])} - not rendered")
    plan["song_score"] = sinfo
    if scan:
        LAST_PLAN[game] = plan
    return plan, fmt_plan(plan, events, sinfo, runners, unmatched, csvname)


def record_history(plan):
    game = plan["game"]
    now = datetime.datetime.now().strftime("%Y-%m-%d")
    uc, us = load_json(USED_CLIPS, {}), load_json(USED_SONGS, {})
    uc.setdefault(game, []).append({"date": now, "headline": plan["headline"], "recipe": plan["recipe"],
                                    "clips": sorted({t["path"] for t in plan["takes"]})})
    us.setdefault(game, []).append({"date": now, "path": plan["song"]["path"]})
    uc[game], us[game] = uc[game][-12:], us[game][-12:]
    save_json(USED_CLIPS, uc)
    save_json(USED_SONGS, us)


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
            quality_check(plan, outfile, cfg)
        except Exception as ex:
            out(f"quality check skipped: {ex}")
        logs = outfile.parent / "logs"                     # only the video stays in the output folder
        logs.mkdir(parents=True, exist_ok=True)
        (logs / (outfile.stem + ".plan.txt")).write_text(text, encoding="utf-8")
        save_json(logs / (outfile.stem + ".plan.json"), plan)
        record_history(plan)
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
        self.win = tk.Toplevel(app.root)
        self.win.title("Killfeed region (optional - defaults to top-right)")
        self.win.configure(bg=app.pal["bg"])
        top = ttk.Frame(self.win)
        top.pack(fill="x", padx=6, pady=4)
        self.game = tk.StringVar(value="valorant")
        cb = ttk.Combobox(top, textvariable=self.game, values=list(GAMES), width=10, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.show_region())
        ttk.Button(top, text="Open clip...", command=self.open_clip).pack(side="left", padx=4)
        ttk.Button(top, text="Open screenshot...", command=self.open_shot).pack(side="left")
        ttk.Button(top, text="Test OCR on this frame", command=self.test).pack(side="left", padx=8)
        ttk.Button(top, text="Use default region", command=self.use_default).pack(side="left")
        self.save = ttk.Button(top, text="Save region", command=self.do_save, state="disabled")
        self.save.pack(side="right")
        self.scale = ttk.Scale(self.win, from_=0, to=1, command=lambda v: None)
        self.scale.bind("<ButtonRelease-1>", lambda e: self.load_frame())
        self.msg = tk.StringVar(value="Open a clip (scrub to a moment with killfeed rows) or a screenshot, then drag a box around the "
                                      "WHOLE killfeed area. Yellow = current region.")
        ttk.Label(self.win, textvariable=self.msg, font=("Segoe UI", F(10), "bold"), wraplength=1260).pack(anchor="w", padx=6)
        self.cv = tk.Canvas(self.win, width=1280, height=720, bg="#222", highlightthickness=1, highlightbackground="#888")
        self.cv.pack(padx=6, pady=6)
        self.cv.bind("<ButtonPress-1>", self.press)
        self.cv.bind("<B1-Motion>", self.drag)
        self.cv.bind("<ButtonRelease-1>", self.release)
        self.base, self.path, self.dur, self.region, self.rect_id, self.p0, self.view = None, None, 0, None, None, None, None

    def open_clip(self):
        p = filedialog.askopenfilename(initialdir=self.cfg["clip_root"], filetypes=[("video", "*.mov *.mp4 *.mkv")])
        if not p:
            return
        try:
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
        reset_region(self.game.get())
        out(f"{self.game.get()}: default killfeed region {DEFAULT_REGION[self.game.get()]}")
        self.show_region()
        self.app.refresh_auto()

    def do_save(self):
        try:
            if not self.region:
                return
            res = do_calibrate(self.game.get(), self.base, self.region)
            self.show_region()
            messagebox.showinfo("Killfeed region", f"{self.game.get()} region saved. OCR read {res['rows']} rows, "
                                                   f"{res['hits']} FIREAXE kill row(s) on this frame (details in the log).")
            self.app.refresh_auto()
        except Exception as ex:
            messagebox.showerror("Killfeed region", str(ex))


PALETTES = {
    "light": dict(bg="#eef0f3", fg="#111418", field="#ffffff", acc="#1f6feb", acc_fg="#ffffff", head="#dfe3e8", dim="#5b6370",
                  border="#8a929e", sel="#c9defc", sel_fg="#0b1f3a", btn="#f8f9fb", btn_act="#e3ecfb", check="#1f6feb"),
    "dark": dict(bg="#2b2e34", fg="#f1f3f5", field="#3a3e46", acc="#4b8df8", acc_fg="#ffffff", head="#454a53", dim="#b0b6bf",
                 border="#8d949e", sel="#3d5f99", sel_fg="#ffffff", btn="#3f444d", btn_act="#4f5662", check="#7fb0ff"),
}


UI_SCALE = [1.0]


def F(size):
    """Font size scaled by Settings > UI scale."""
    return max(7, int(round(size * UI_SCALE[0])))


def apply_theme(root, mode="light", scale=None):
    """Light by default (clear contrast: visible borders on buttons and inputs, clear selection and checkbox colours).
    'dark' is optional in Settings; 'auto' follows Windows."""
    dark = mode == "dark"
    if mode == "auto":
        try:
            import winreg
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            dark = winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 0
        except Exception:
            dark = False
    pal = dict(PALETTES["dark" if dark else "light"])
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
    return pal


SECTION_COLORS = {"intro": "#9db4d6", "verse": "#a8d5a2", "build": "#f2c46d", "drop": "#ef6f6c", "breakdown": "#b49ad8",
                  "outro": "#9fa6ad", "": "#cccccc"}


class SongMapView:
    """Songs tab > Song map: waveform, energy curve, beat + downbeat ticks, coloured sections, drops and accents."""
    def __init__(self, app, path, csv_bpm=None):
        self.app, self.path, self.an, self.zoom = app, path, None, 1
        self.win = tk.Toplevel(app.root)
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
        self.cv = tk.Canvas(fr, width=1300, height=int(360 * UI_SCALE[0]), bg="#ffffff" if app.pal["bg"] != PALETTES["dark"]["bg"] else "#1e1f22",
                            highlightthickness=1, highlightbackground=app.pal["border"])
        sb = ttk.Scrollbar(fr, orient="horizontal", command=self.cv.xview)
        self.cv.configure(xscrollcommand=sb.set)
        self.cv.pack(fill="both", expand=True)
        sb.pack(fill="x")
        leg = ttk.Frame(self.win)
        leg.pack(fill="x", padx=6, pady=2)
        for k in ("intro", "verse", "build", "drop", "breakdown", "outro"):
            tk.Label(leg, text=f"  {k}  ", bg=SECTION_COLORS[k], fg="#111").pack(side="left", padx=2)
        ttk.Label(leg, text="   red line = drop   | tall tick = downbeat   | dot = accent (filled = bass hit)   | line = energy").pack(side="left")
        self.cv.bind("<Configure>", lambda e: self.draw())

        def work():
            try:
                an = analyse_song(path, csv_bpm)
                self.app.q.put(("call", lambda: self.show(an)))
            except Exception as ex:
                msg = f"song map failed: {ex}"
                self.app.q.put(("call", lambda: self.info.set(msg)))
        threading.Thread(target=work, daemon=True).start()

    def show(self, an):
        self.an = an
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


class App:
    DATES = {"All dates": None, "Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}

    def __init__(self, start_tab=0, startup=True):
        self.root = tk.Tk()
        self.root.title(f"Montage builder {APP_VERSION} (Valorant / CS2)")
        try:
            self.root.iconbitmap(str(HERE / "montage.ico"))      # V5.5 app icon (Windows)
        except Exception:
            pass
        sc = UI_SCALE[0]
        self.root.geometry(f"{min(int(1220 * sc), self.root.winfo_screenwidth())}x{min(int(920 * sc), self.root.winfo_screenheight() - 60)}")
        self.root.minsize(920, 640)
        self.q, self.busy, self.buttons, self._imgs, self.pending = queue.Queue(), False, [], [], []
        self.named = {}                   # button registry (smoketest checks every required button)
        self.sorts, self.sort_refill, self.sort_labels = {}, {}, {}
        self.clips, self.ticked, self.songs, self.bpm, self.last_video, self.byp = [], set(), [], {}, None, {}
        self._fill_token = {}
        LOG_SINK[0] = lambda m: self.q.put(("log", m))
        PROGRESS[0] = lambda f, t: self.q.put(("prog", (f, t)))
        self.cfg = load_config()
        self.pal = apply_theme(self.root, self.cfg.get("theme", "light"), self.cfg.get("ui_scale", 1.0))
        self.last_click = None
        # bottom area first so the notebook can expand above it
        bot = ttk.Frame(self.root)
        bot.pack(side="bottom", fill="x", padx=6, pady=4)
        row = ttk.Frame(bot)
        row.pack(fill="x")
        self.pbar = ttk.Progressbar(row, maximum=1.0)
        self.pbar.pack(side="left", fill="x", expand=True)
        self.plabel = tk.StringVar(value="idle")
        ttk.Label(row, textvariable=self.plabel, width=34).pack(side="left", padx=6)
        self.named["Cancel"] = ttk.Button(row, text="Cancel", command=stop_all)
        self.named["Cancel"].pack(side="left")
        res = ttk.Frame(bot)
        res.pack(fill="x", pady=3)
        self.vlabel = tk.StringVar(value="Last video: none yet")
        ttk.Label(res, textvariable=self.vlabel).pack(side="left")
        self.b_open = ttk.Button(res, text="Open video", command=self.safe(self.open_video), state="disabled")
        self.b_open.pack(side="right")
        self.b_folder = ttk.Button(res, text="Open folder", command=self.safe(self.open_vfolder))
        self.b_folder.pack(side="right", padx=4)
        self.named["Open video"], self.named["Open folder"] = self.b_open, self.b_folder
        lf = ttk.Frame(bot)
        lf.pack(fill="x")
        self.log = tk.Text(lf, height=8, wrap="word", bg=self.pal["field"], fg=self.pal["fg"], insertbackground=self.pal["fg"],
                           relief="solid", bd=1, highlightthickness=0, padx=8, pady=6, font=("Consolas", F(10)),
                           selectbackground=self.pal["sel"], selectforeground=self.pal["sel_fg"])
        lsb = ttk.Scrollbar(lf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set)
        self.log.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(side="top", fill="both", expand=True, padx=6, pady=6)
        self.tabs = {n: ttk.Frame(self.nb, padding=6) for n in ("Auto", "Manual", "Songs", "Troubleshoot", "Settings")}
        for n, f in self.tabs.items():
            self.nb.add(f, text=n)
        self.build_auto()
        self.build_manual()
        self.build_songs()
        self.build_trouble()
        self.build_settings()
        self.nb.select(start_tab)
        self.root.bind("<Configure>", self.fit_log, add="+")
        self.root.after(100, self.poll)
        if startup:
            self.root.after(400, self.startup)

    # ------------------------------------------------------------ plumbing
    def fit_log(self, e=None):
        """Small windows give the log fewer lines so the tabs (and their buttons) keep their room."""
        h = self.root.winfo_height()
        lines = 4 if h < 760 else 6 if h < 880 else 8
        if int(self.log.cget("height")) != lines:
            self.log.configure(height=lines)

    def btn(self, parent, text, cmd, big=False, name=None, **kw):
        if big:
            b = tk.Button(parent, text=text, command=self.safe(cmd), font=("Segoe UI", F(12), "bold"), height=2, bg=self.pal["acc"],
                          fg=self.pal["acc_fg"], activebackground=self.pal["btn_act"], activeforeground=self.pal["fg"],
                          disabledforeground="#d0d6de", relief="raised", bd=2, highlightthickness=1,
                          highlightbackground=self.pal["border"], cursor="hand2", padx=14, **kw)
        else:
            b = ttk.Button(parent, text=text, command=self.safe(cmd), **kw)
        self.buttons.append(b)
        self.named[name or text] = b
        return b

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

    def run_task(self, name, fn, *a):
        if self.busy or getattr(self, "est_running", False):    # never next to the status-line estimate (shared caches)
            self.pending.append((name, fn, a))
            out(f"queued: {name}")
            return
        self.busy = True
        CANCEL.clear()
        self.set_buttons(False)

        def target():
            try:
                fn(*a)
            except Exception as ex:
                out(f"ERROR in {name}: {ex}\n{traceback.format_exc()}")
            finally:
                self.q.put(("done", None))
        threading.Thread(target=target, daemon=True).start()

    def poll(self):
        try:
            for _ in range(200):
                k, v = self.q.get_nowait()
                if k == "log":
                    self.log.insert("end", v + "\n")
                    self.log.see("end")
                elif k == "prog":
                    self.pbar["value"] = v[0]
                    self.plabel.set(v[1])
                elif k == "call":
                    self.safe(v)()
                elif k == "done":
                    self.busy = False
                    self.pbar["value"] = 0
                    self.plabel.set("idle")
                    self.set_buttons(True)
                    self.refresh_auto()
                    if self.pending:
                        n, fn, a = self.pending.pop(0)
                        self.run_task(n, fn, *a)
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

    def startup(self):
        miss = missing_packages()
        if miss and messagebox.askyesno("Missing packages", "Install now (user scope, no admin)?\n\n" + ", ".join(miss)):
            def inst():
                out("installing: " + " ".join(miss))
                r = subprocess.run([sys.executable, "-m", "pip", "install", "--user"] + miss, capture_output=True, text=True)
                out((r.stdout + r.stderr)[-1500:])
                out("done - close and reopen this program.")
            self.run_task("pip", inst)
            return
        if not shutil.which("ffmpeg"):
            out("ffmpeg not found. Troubleshoot > Selfcheck explains how to get it without admin.")
        self.cfg = autodetect_dirs(load_config())
        self.run_task("clips", self.load_clips)
        self.run_task("matches", self.load_matches)
        threading.Thread(target=self.bpm_worker, daemon=True).start()

    def fill_chunked(self, tree, rows, chunk=300):
        """Insert thousands of rows without freezing the window."""
        token = object()
        self._fill_token[tree] = token
        tree.delete(*tree.get_children())

        def step(i=0):
            if self._fill_token.get(tree) is not token:
                return
            for iid, text, vals in rows[i:i + chunk]:
                tree.insert("", "end", iid=iid, text=text, values=vals)
            if i + chunk < len(rows):
                self.root.after(5, step, i + chunk)
        step()

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
            res = run_job(game, **kw)
            if isinstance(res, Path):
                self.q.put(("call", lambda: self.set_video(res)))
            self.q.put(("call", lambda: self.run_task("clips", self.load_clips)))
        return go

    # ------------------------------------------------------------ Auto tab
    def build_auto(self):
        f = self.tabs["Auto"]
        ttk.Label(f, text="One montage per game per week from all your clips - nothing to pick. Kills are read from the killfeed "
                          "with OCR (no calibration needed; the killfeed region can be adjusted in Troubleshoot).",
                  font=("Segoe UI", F(10)), wraplength=1100).pack(anchor="w", padx=8, pady=4)
        self.auto_status = {}
        for g in GAMES:
            lf = ttk.LabelFrame(f, text=GAME_DIR[g])
            lf.pack(fill="x", padx=8, pady=4)
            sv = tk.StringVar()
            self.auto_status[g] = sv
            self.btn(lf, "Make this week's montage", lambda g=g: self.run_task(f"{g} auto", self.job_video(g, weekly=True)),
                     big=True, name=f"auto:{g}:make").pack(side="left", padx=10, pady=4)
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
        try:
            cfg = load_config()
            recs = [v for v in load_json(CLIPS_CACHE, {}).values() if isinstance(v, dict) and v.get("path")]
            kc = load_kills_cache()
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
                self.auto_status[g].set(
                    f"Killfeed region: {('calibrated' if det.calibrated else 'default top-right (optional: Troubleshoot > Calibrate killfeed region)') if det else 'OCR unavailable - Troubleshoot > Selfcheck'}\n"
                    f"Clips scanned: {done} / {len(mine)}\n"
                    f"Song: {song}\n"
                    f"This week ({week_tag(datetime.datetime.now())}): {ex[-1].name if ex else 'no montage yet'}    "
                    f"Last montage: {allv[-1].name if allv else '-'}")
        except Exception:
            out("status refresh failed: " + traceback.format_exc()[-300:])

    # ------------------------------------------------------------ Manual tab
    def build_manual(self):
        f = self.tabs["Manual"]
        s3 = ttk.LabelFrame(f, text="Step 3 - make it")
        s3.pack(side="bottom", fill="x", padx=8, pady=4)          # packed FIRST so it can never be pushed off-screen
        bb = ttk.Frame(s3)
        bb.pack(fill="x", pady=(2, 6))
        for text, mode in (("Dry plan", "dry"), ("Preview (720p, 20 s)", "preview"), ("Render", "render")):
            self.btn(bb, text, lambda m=mode: self.manual(m), big=True, name=f"manual:{mode}").pack(side="left", expand=True, fill="x", padx=6)
        c3 = ttk.Frame(s3)
        c3.pack(fill="x", pady=2)
        ttk.Label(c3, text="Length").pack(side="left")
        L = self.cfg.get("length_s", "optimal")
        self.m_opt = tk.BooleanVar(value=not isinstance(L, (int, float)))
        cb = ttk.Checkbutton(c3, text="Optimal", variable=self.m_opt, command=self.update_status)
        cb.pack(side="left", padx=(4, 2))
        self.named["Optimal length"] = cb
        self.m_len = tk.IntVar(value=int(L) if isinstance(L, (int, float)) else 60)
        self.m_len_sc = ttk.Scale(c3, from_=30, to=120, variable=self.m_len, length=150,
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
        self.m_status = tk.StringVar(value="Tick some clips.")
        ttk.Label(s3, textvariable=self.m_status, font=("Segoe UI", F(10), "bold"), wraplength=1100).pack(anchor="w", pady=2)
        mid = ttk.Frame(f)                                         # grid: steps 1 and 2 shrink instead of being cut off
        mid.pack(side="top", fill="both", expand=True)
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=5)
        mid.rowconfigure(1, weight=2)
        s1 = ttk.LabelFrame(mid, text="Step 1 - tick the clips (click a row to tick it)")
        s1.grid(row=0, column=0, sticky="nsew", padx=8, pady=4)
        top = ttk.Frame(s1)
        top.pack(fill="x", pady=2)
        self.m_game = tk.StringVar(value="valorant")
        for g in GAMES:
            ttk.Radiobutton(top, text=GAME_DIR[g], variable=self.m_game, value=g,
                            command=lambda: self.run_task("clips", self.load_clips)).pack(side="left", padx=4)
        ttk.Label(top, text="Folder").pack(side="left", padx=(12, 2))
        self.m_folder = tk.StringVar(value="All folders")
        self.cb_folder = ttk.Combobox(top, textvariable=self.m_folder, values=["All folders"], width=18, state="readonly")
        self.cb_folder.pack(side="left")
        self.cb_folder.bind("<<ComboboxSelected>>", lambda e: self.apply_filter())
        ttk.Label(top, text="Date").pack(side="left", padx=(8, 2))
        self.m_date = tk.StringVar(value="All dates")
        cb = ttk.Combobox(top, textvariable=self.m_date, values=list(self.DATES), width=12, state="readonly")
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", lambda e: self.apply_filter())
        ttk.Label(top, text="From").pack(side="left", padx=(10, 2))
        self.m_from = tk.StringVar()
        ttk.Entry(top, textvariable=self.m_from, width=11).pack(side="left")
        ttk.Label(top, text="to").pack(side="left", padx=3)
        self.m_to = tk.StringVar()
        ttk.Entry(top, textvariable=self.m_to, width=11).pack(side="left")
        ttk.Label(top, text="(YYYY-MM-DD)").pack(side="left", padx=3)
        top3 = ttk.Frame(s1)
        for v in (self.m_from, self.m_to):
            v.trace_add("write", lambda *a: self.root.after(400, self.apply_filter))
        top2 = ttk.Frame(s1)
        top2.pack(fill="x", pady=2)
        self.btn(top2, "Tick all shown", lambda: self.tick("all")).pack(side="left", padx=3)
        self.btn(top2, "Untick all", lambda: self.tick("none")).pack(side="left", padx=3)
        self.btn(top2, "Tick clips with kills", lambda: self.tick("kills")).pack(side="left", padx=3)
        self.btn(top2, "Tick newest", lambda: self.tick("newest")).pack(side="left", padx=(12, 2))
        self.m_n = tk.StringVar(value="15")
        ttk.Spinbox(top2, from_=1, to=500, textvariable=self.m_n, width=5).pack(side="left")
        self.btn(top2, "Tick whole folder", lambda: self.tick("folder")).pack(side="left", padx=(12, 3))
        top3.pack(fill="x", pady=2, after=top2)
        self.btn(top3, "Reload list", lambda: self.run_task("clips", self.load_clips)).pack(side="left", padx=3)
        self.btn(top3, "Exclude ticked from montages", self.exclude_sel).pack(side="left", padx=3)
        ttk.Label(top3, text="(Shift+click ticks a range)").pack(side="left", padx=10)
        fr, self.ctree = make_tree(s1, ("date", "len", "kills"), height=12, selectmode="none")
        fr.pack(fill="both", expand=True)
        for c, w, t in (("#0", 430, "clip"), ("date", 110, "date"), ("len", 70, "length"), ("kills", 110, "kills")):
            self.ctree.column(c, width=w, minwidth=60, stretch=(c == "#0"))
            self.ctree.heading(c, text=t)
        self.make_sortable(self.ctree, self.apply_filter, {"#0": "clip", "date": "date", "len": "length", "kills": "kills"})
        self.ctree.bind("<Button-1>", self.on_tree_click)
        s2 = ttk.LabelFrame(mid, text="Step 2 - choose the song (newest added first)")
        s2.grid(row=1, column=0, sticky="nsew", padx=8, pady=4)
        r2 = ttk.Frame(s2)
        r2.pack(fill="x", pady=2)
        ttk.Label(r2, text="Search").pack(side="left")
        self.m_search = tk.StringVar()
        self.m_search.trace_add("write", lambda *a: self.refresh_songs())
        ttk.Entry(r2, textvariable=self.m_search, width=30).pack(side="left", padx=4)
        self.btn(r2, "Play selected song", self.play_song).pack(side="left", padx=8)
        self.btn(r2, "Song map", self.map_song, name="Song map (Manual)").pack(side="left")
        fr2, self.stree = make_tree(s2, ("bpm", "added"), height=4, selectmode="browse")
        fr2.pack(fill="both", expand=True)
        self.stree.column("#0", width=520)
        self.stree.column("bpm", width=70)
        self.stree.column("added", width=110)
        self.stree.heading("#0", text="song")
        self.stree.heading("bpm", text="BPM")
        self.stree.heading("added", text="added")
        self.make_sortable(self.stree, self.refresh_songs, {"#0": "song", "bpm": "BPM", "added": "added"})
        self.stree.bind("<<TreeviewSelect>>", lambda e: self.update_status())

    def on_tree_click(self, e):
        if self.ctree.identify_region(e.x, e.y) in ("heading", "separator"):
            return None                                    # header click = sort
        iid = self.ctree.identify_row(e.y)
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

    def load_clips(self):
        cfg = load_config()
        if missing_packages() == [] and shutil.which("ffmpeg"):
            ensure_bars(cfg)
        g = self.m_game.get()
        det = load_dets(g).get(g)
        kc = load_kills_cache()
        rows = []
        for r in scan_clips(load_config()):
            if r.get("error") or r.get("game") != g:
                continue
            e = kc.get(kills_key(r, g, det)) if det else None
            ks = None
            if e and not e.get("error"):
                ks = [k["t"] for k in compute_kills(e, cfg, g)[0]]
            try:
                mt = os.path.getmtime(r["path"])
            except OSError:
                continue
            rows.append({"path": r["path"], "name": Path(r["path"]).name, "folder": clip_folder(r["path"], cfg), "mtime": mt,
                         "dur": r.get("dur", 0), "kills": None if ks is None else len(ks), "ks": ks or []})
        rows.sort(key=lambda c: -c["mtime"])
        songs, _, _ = song_pool(load_config()) if load_config().get("mp3_dir") else ([], [], None)
        songs.sort(key=lambda s: s["added"] or datetime.datetime(1970, 1, 1), reverse=True)

        def fill():
            self.clips, self.songs = rows, songs
            self.byp = {c["path"]: c for c in rows}
            self.ticked &= set(self.byp)
            self.cb_folder.config(values=["All folders"] + sorted({c["folder"] for c in rows}))
            self.apply_filter()
            self.refresh_songs()
        self.q.put(("call", fill))

    def apply_filter(self):
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
            rows.append((c["path"], self.row_text(c["path"]),
                         (time.strftime("%Y-%m-%d", time.localtime(c["mtime"])), f"{int(c['dur'] // 60)}:{int(c['dur'] % 60):02d}",
                          "not scanned" if c["kills"] is None else str(c["kills"]))))
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
        keep = self.stree.selection()
        self.fill_chunked(self.stree, self.sorted_rows(self.stree, rows))
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
        out(f"excluded {len(self.ticked)} clip(s) from montages (montage_data\\exclude.txt, one path per line)")

    def update_status(self):
        """Status line. The length comes from the REAL planner (make_plan on the already-scanned ticked clips, same song, style
        and seed as the render), run quietly in the background after a short pause, so the estimate is the plan."""
        tk_ = [self.byp[p] for p in self.ticked if p in getattr(self, "byp", {})]
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
        self.m_status.set(txt + (", montage length: estimating ..." if kills else "") + f", song: {song}")
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
        game, head = self.m_game.get(), self.m_head
        self.est_gen = getattr(self, "est_gen", 0) + 1
        gen = self.est_gen
        self.est_running = True

        def go():
            QUIET.on = True
            try:
                plan, _ = make_plan(load_config(), game, scan=False, **args)
                msg = self.estimate_text(plan, len(paths))
            except Exception as ex:
                msg = f"cannot plan yet: {ex}"
            finally:
                QUIET.on = False

            def show():
                self.est_running = False
                if gen == self.est_gen:
                    self.m_status.set(f"{head}, {msg}")
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
        for c, w, t in (("#0", 420, "MP3 file"), ("track", 300, "matched playlist track"), ("artist", 200, "artist"),
                        ("bpm", 60, "BPM"), ("score", 70, "score"), ("flag", 130, "flag")):
            self.mtree.column(c, width=w, minwidth=50, stretch=(c in ("#0", "track")))
            self.mtree.heading(c, text=t)
        self.make_sortable(self.mtree, self.fill_matches, {"#0": "MP3 file", "track": "matched playlist track", "artist": "artist",
                                                            "bpm": "BPM", "score": "score", "flag": "flag"})
        dark = self.pal["bg"] == PALETTES["dark"]["bg"]
        self.mtree.tag_configure("weak", foreground="#ffc65c" if dark else "#9a5b00")
        self.mtree.tag_configure("none", foreground="#ff8a80" if dark else "#c62828")
        self.match_rows, self.match_audio = [], []

    def load_matches(self):
        cfg = load_config()
        audio = scan_audio(cfg)
        csvp, rows, col = read_playlist(cfg)
        matched, unmatched = match_playlist(rows, audio, cfg) if rows and audio else ([], rows)
        write_song_matches(audio, matched)
        by = {a["path"]: (r, sc) for r, a, sc in matched}
        items = []
        for a in sorted(audio, key=lambda a: a["path"].lower()):
            r, sc = by.get(a["path"], (None, 0))
            items.append((a["path"], Path(a["path"]).name, r["title"] if r else "", r["artist"] if r else "", sc,
                          "NO MATCH" if not r else "CHECK (under 85)" if sc < 85 else "ok",
                          f"{r['tempo']:.0f}" if r and r.get("tempo") else ""))
        weak = sum(1 for i in items if i[5] != "ok")

        def fill():
            self.match_rows, self.match_audio, self.match_items = rows, audio, items
            self.fill_matches()
            self.m_info.set(f"{len(audio)} MP3 files, {len(rows)} playlist tracks, {len(matched)} matched, {weak} to check, {len(unmatched)} playlist tracks without a file")
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
        w = tk.Toplevel(self.root)
        w.title("Pick the playlist track for " + Path(path).name)
        w.geometry("640x520")
        q = tk.StringVar(value=clean(Path(path).stem))
        ttk.Entry(w, textvariable=q).pack(fill="x", padx=8, pady=6)
        fr, tr = make_tree(w, ("artist",), height=18, selectmode="browse")
        fr.pack(fill="both", expand=True, padx=8)
        tr.column("#0", width=380)
        tr.heading("#0", text="playlist track")
        tr.heading("artist", text="artist")
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
        g = self.t_game.get()
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
            out("not scanned yet: press Rescan this clip")
            return
        a = analyse_entry(e, cfg, g)
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
                w = tk.Toplevel(self.root)
                w.title("Killfeed crop: green = KILL, red = DEATH, orange = rejected (assist/utility), grey = other rows")
                ph, _ = to_photo(fr, 1100, 700)
                self._imgs.append(ph)
                ttk.Label(w, image=ph).pack()

    def rescan_clip(self):
        p = self.sel_clip()
        if not p:
            return

        def job():
            cache = load_kills_cache()
            fk = file_key(p) + "|"
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
        out(f"bar override saved: {cfg['bar']}")
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
        w = tk.Toplevel(self.root)
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
            out("kill cache cleared")

    # ------------------------------------------------------------ Settings tab
    def build_settings(self):
        f = self.tabs["Settings"]
        self.sv = {}
        self.btn(f, "Save settings", self.save_settings).grid(row=0, column=1, sticky="w", pady=6)
        r = 1
        for k, lab in (("mp3_dir", "MP3 folder"),
                       ("playlist_dir", "Exportify CSV folder"), ("output_root", "Output folder")):
            ttk.Label(f, text=lab).grid(row=r, column=0, sticky="w", padx=8, pady=4)
            v = tk.StringVar(value=self.cfg.get(k, ""))
            self.sv[k] = v
            ttk.Entry(f, textvariable=v, width=70).grid(row=r, column=1, padx=4)
            ttk.Button(f, text="Browse", command=lambda v=v: v.set(filedialog.askdirectory(initialdir=v.get() or None) or v.get())).grid(row=r, column=2)
            r += 1
        self.sl = {}
        for g, lab in (("valorant", "Valorant clip folders (; separated)"), ("cs2", "CS2 clip folders (; separated)")):
            ttk.Label(f, text=lab).grid(row=r, column=0, sticky="w", padx=8, pady=4)
            v = tk.StringVar(value="; ".join((self.cfg.get("clip_dirs") or {}).get(g, [])))
            self.sl[g] = v
            ttk.Entry(f, textvariable=v, width=70).grid(row=r, column=1, padx=4)
            ttk.Button(f, text="Add folder", command=lambda v=v: v.set("; ".join([x for x in v.get().split(";") if x.strip()] +
                                                                                   [filedialog.askdirectory() or ""]).strip("; "))).grid(row=r, column=2)
            r += 1
        self.sn = {}
        for k, lab in (("max_mb", "Skip files larger than (MB)"), ("max_dur_s", "Skip clips longer than (s)"),
                       ("auto_recent_days", "Auto: scan every new clip from the last (days)"),
                       ("auto_old_per_run", "Auto: plus up to this many older clips per run"),
                       ("name_match", "Detection: FIREAXE OCR fuzzy match needed (0-100)"),
                       ("death_lock_s", "No kills for this long after my death (s)"),
                       ("game_audio_level", "Game audio level under the music (0-1, V4 was 0.5; no music ducking)"),
                       ("ui_scale", "UI scale (font + row height, restart to apply)"),
                       ("week_days", "'This week' means the last N days")):
            ttk.Label(f, text=lab).grid(row=r, column=0, sticky="w", padx=8, pady=3)
            v = tk.StringVar(value=str(self.cfg.get(k, "")))
            self.sn[k] = v
            ttk.Entry(f, textvariable=v, width=10).grid(row=r, column=1, sticky="w", padx=4)
            r += 1
        L = self.cfg.get("length_s", "optimal")
        self.set_opt = tk.BooleanVar(value=not isinstance(L, (int, float)))
        self.set_len = tk.IntVar(value=int(L) if isinstance(L, (int, float)) else 60)
        ttk.Label(f, text="Default length").grid(row=r, column=0, sticky="w", padx=8, pady=4)
        lf = ttk.Frame(f)
        lf.grid(row=r, column=1, sticky="w")
        ttk.Checkbutton(lf, text="Optimal (Manual: 80-150 s from clips + song + style; Auto: 30-120 s)", variable=self.set_opt).pack(side="left")
        ttk.Scale(lf, from_=30, to=120, variable=self.set_len, length=220,
                  command=lambda v: self.set_len.set(int(float(v)))).pack(side="left", padx=6)
        ttk.Label(lf, textvariable=self.set_len, width=4).pack(side="left")
        ttk.Label(lf, text="s (used when Optimal is off)").pack(side="left")
        r += 1
        st = self.cfg.get("style", "auto")
        self.set_style = tk.StringVar(value=st if st in STYLE_CHOICES else "auto")
        ttk.Label(f, text="Default style (auto = from the song)").grid(row=r, column=0, sticky="w", padx=8, pady=4)
        ttk.Combobox(f, textvariable=self.set_style, values=STYLE_CHOICES, width=10, state="readonly").grid(row=r, column=1, sticky="w", padx=4)
        r += 1
        self.set_place = tk.StringVar(value=self.cfg.get("placement", "v5"))
        ttk.Label(f, text="Kill placement (see synccompare)").grid(row=r, column=0, sticky="w", padx=8, pady=4)
        ttk.Combobox(f, textvariable=self.set_place, values=["v5", "v4"], width=10, state="readonly").grid(row=r, column=1, sticky="w", padx=4)
        r += 1
        self.set_q = tk.StringVar(value=self.cfg.get("quality", "nvenc"))
        self.set_sync = tk.BooleanVar(value=self.cfg.get("sync_report", True))
        self.set_theme = tk.StringVar(value=self.cfg.get("theme", "light"))
        ttk.Label(f, text="Quality").grid(row=r, column=0, sticky="w", padx=8, pady=4)
        qf = ttk.Frame(f)
        qf.grid(row=r, column=1, sticky="w")
        ttk.Radiobutton(qf, text="NVENC p7 cq18 (fast)", variable=self.set_q, value="nvenc").pack(side="left")
        ttk.Radiobutton(qf, text="Max quality x264 CRF15", variable=self.set_q, value="max").pack(side="left", padx=10)
        r += 1
        ttk.Checkbutton(f, text="Print a sync report after each render (re-scans the finished montage)", variable=self.set_sync).grid(row=r, column=1, sticky="w")
        r += 1
        self.set_upd = tk.BooleanVar(value=bool(self.cfg.get("update_on_start", False)))
        ttk.Checkbutton(f, text="Check for updates on start (runs 'git pull' once when the app opens; off by default)",
                        variable=self.set_upd).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="Theme (restart to apply)").grid(row=r, column=0, sticky="w", padx=8, pady=4)
        ttk.Combobox(f, textvariable=self.set_theme, values=["light", "dark", "auto"], width=8, state="readonly").grid(row=r, column=1, sticky="w")
        r += 1

    def save_settings(self):
        cfg = load_config()
        for k, v in self.sv.items():
            cfg[k] = v.get().strip()
        cfg["clip_dirs"] = {g: [x.strip() for x in v.get().split(";") if x.strip()] for g, v in self.sl.items()}
        for k, v in self.sn.items():
            try:
                cfg[k] = float(v.get()) if "." in v.get() else int(v.get())
            except ValueError:
                out(f"ignored invalid number for {k}")
        cfg["length_s"] = "optimal" if self.set_opt.get() else int(self.set_len.get())
        cfg["style"], cfg["placement"] = self.set_style.get(), self.set_place.get()
        cfg["quality"], cfg["sync_report"] = self.set_q.get(), bool(self.set_sync.get())
        cfg["theme"] = self.set_theme.get()
        cfg["update_on_start"] = bool(self.set_upd.get())
        save_json(CONFIG_PATH, cfg)
        self.cfg = cfg
        out("settings saved")
        self.run_task("clips", self.load_clips)


def grab_gray_bgr(path, t, w, h):
    import numpy as np
    r = run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], timeout=60)
    return np.frombuffer(r.stdout[:w * h * 3], np.uint8).reshape(h, w, 3).copy()


DATA_GLOBALS = ("DATA", "CONFIG_PATH", "CLIPS_CACHE", "AUDIO_CACHE", "KILLS_CACHE", "LOG_DIR", "SONG_CACHE", "USED_CLIPS", "USED_SONGS",
                "FLICK_CACHE", "ONSET_CACHE", "SCALES", "REFINE_CACHE", "LOUD_CACHE")


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
    an = analyse_song(plan["song"]["path"], plan["song"].get("bpm") if plan.get("placement") != "v4" else None)
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
    globals()["clip_audio"] = lambda rec: {"stream": None, "lufs": None}
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
    "Exclude ticked from montages": ("Manual", "write:exclude.txt"),
    "manual:dry": ("Manual", "task:manual dry"), "manual:preview": ("Manual", "task:manual preview"),
    "manual:render": ("Manual", "task:manual render"),
    "Tick all shown": ("Manual", "ticked"), "Untick all": ("Manual", "unticked"), "Tick clips with kills": ("Manual", "ticked"),
    "Tick newest": ("Manual", "ticked"), "Tick whole folder": ("Manual", "ticked"), "Reload list": ("Manual", "task:clips"),
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
    "Save settings": ("Settings", "write:config.json"),
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
        for W, H in sizes:
            root.geometry(f"{W}x{H}+0+0")
            for tname in app.tabs:
                app.nb.select(app.tabs[tname])
                root.update()
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
            if name in ("Tick all shown", "Tick clips with kills", "Tick newest", "Tick whole folder"):
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


def gui_main(start_tab=0):
    if tk is None:
        raise SystemExit("tkinter is missing. Re-run the python.org installer > Modify > tcl/tk and IDLE.")
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
    sc.set_defaults(fn=cmd_scan)
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
