r"""
montage.py - Valorant / CS2 kill-montage builder synced to a song. One file + montage_data\ folder. Personal use.
Never modifies source clips. No network at runtime (only the optional one-click pip install). No admin needed.

GET IT RUNNING (Windows 11, Python 3.13) - in cmd.exe:
    cd C:\Users\fireaxe\Desktop\CLAUDECODE
    git clone https://github.com/fireaxe77/montager.git montager      (later updates: cd montager && git pull origin main)
    cd montager
    python -m pip install --user numpy opencv-python librosa soundfile scipy mutagen rapidfuzz
    python montage.py                    <- opens the GUI (the app also offers a one-click install of missing packages)
    ffmpeg missing?  winget install --id Gyan.FFmpeg -e --scope user   (open a new terminal afterwards)

FIRST 3 THINGS TO CLICK:
  1. Troubleshoot > "Selfcheck"  -> every line should say OK (ffmpeg, NVENC, packages).
  2. Troubleshoot > "Calibrate killfeed..." once per game: Open clip, scrub to a frame where your FIREAXE kill row
     is visible, drag a box over that row, then a tight box over the text FIREAXE (optionally the headshot icon).
     Self-test must say "1 own row". (Or "Open screenshot..." if you have one.)
  3. Auto tab > "Dry plan" for a game: first run scans every clip once (cached forever), then prints the song with
     its score breakdown, ranked kills, and the cut list. Then "Preview" (720p, 20 s around the drop) and "Run".

CLI (same engine):  python montage.py auto [--game valorant|cs2] [--force] [--dry] [--preview] [--max-quality] [--seed N]
                    python montage.py plan --game cs2        (dry plan only)     python montage.py pick   (GUI, Manual tab)
                    python montage.py selfcheck | inventory | scan | verify <game> | calibrate-bars | tag <path> <game>
Data: montage_data\ (config.json, caches, calibration, plans, logs\montage.log). Output: E:\Movies\Montages\<Game>\.
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
    "game_audio_level": 0.5,        # linear gain of game audio under the music (0.5 = -6 dB); +4 dB boost around kills
    "cfg_version": 2,
    "include_valorant": ["VALORANT"],   # only folders whose name matches are used (any depth under clip_root)
    "include_cs": ["CS", "COUNTER STRIKE"],
    "max_mb": 60,
    "max_dur_s": 60,
    "auto_recent_days": 30,
    "auto_old_per_run": 150,
    "thr_name": 0.60,
    "thr_hl": 0.30,
    "thr_left": 0.80,               # a row whose left edge continues past FIREAXE = assist/other killer -> rejected
    "death_lock_s": 8.0,            # no kills counted this long after my own death
    "sync_report": True,
    "gap_s": {"valorant": 6.0, "cs2": 5.0},
    "game_overrides": {},           # path prefix -> game
    "match_threshold": 85,
    "length_s": 85,
    "quality": "nvenc",             # nvenc | max
}


# ----------------------------------------------------------------- utilities
LOG_DIR = DATA / "logs"
LOG_SINK = [None]       # GUI sets callable(str)
PROGRESS = [None]       # GUI sets callable(frac, text)
CANCEL = threading.Event()
PROCS = []              # running ffmpeg processes, killed on cancel


def out(*a):
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
        print(msg, flush=True)


def progress(frac, text=""):
    if PROGRESS[0]:
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
    return cfg


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
    """Game from the nearest folder name under clip_root that matches the include lists; None = ignored clip."""
    pl = norm(path)
    best = None
    for pre, g in cfg.get("game_overrides", {}).items():
        n = norm(pre)
        if (pl == n or pl.startswith(n + os.sep)) and (best is None or len(n) > best[0]):
            best = (len(n), g)
    if best and best[1] in GAMES:
        return best[1], "override"
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


def scan_clips(cfg, rescan=False):
    root = cfg["clip_root"]
    out(f"Scanning {root} ...")
    max_b = int(cfg.get("max_mb", 60)) * 1024 * 1024
    paths = []
    for p in walk_files([root], VIDEO_EXT, MIN_VIDEO, cfg):
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
}


def newest_csv(cfg):
    d = Path(cfg["playlist_dir"])
    files = sorted(d.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True) if d.is_dir() else []
    return files[0] if files else None


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
                         "dur": _ms(r.get(col["dur"])) if col["dur"] else 0.0})
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
    """CSV track name vs MP3 title (artist not needed): token_set_ratio >= threshold, ties by duration (+-3 s)."""
    from rapidfuzz import fuzz
    thr = cfg["match_threshold"]
    prepared = [(a, audio_titles(a)) for a in audio]
    matched, unmatched = [], []
    for r in rows:
        rt = clean(r["title"]) or re.sub(r"\W+", " ", r["title"].lower()).strip()
        best = None
        for a, titles in prepared:
            sc = max((fuzz.token_set_ratio(rt, t) for t in titles), default=0)
            if sc < thr:
                continue
            rr = max(fuzz.ratio(rt, t) for t in titles)
            dd = abs(a.get("dur", 0) - r.get("dur", 0)) if a.get("dur") and r.get("dur") else 99.0
            key = (round(sc), dd <= 3.0, -dd, rr)
            if best is None or key > best[0]:
                best = (key, a, sc)
        if best:
            matched.append((r, best[1], round(best[2])))
        else:
            unmatched.append(r)
    return matched, unmatched


# ------------------------------------------------------------- kill detection
NORM_W, NORM_H = 1920, 1080     # every clip is normalised to this (content rect stretched)
FPS = 15
COARSE = [0.6, 0.7, 0.8, 0.9, 1.0, 1.12, 1.25, 1.4, 1.6]
TRACK_KEEP_S = 8.0              # a killfeed row is remembered this long (so it is never counted twice)
SAME_ROW_CORR = 0.90            # appearance match that means "same row as before" even if it moved (feed shift)
CACHE_V = 3                     # bump when the cached per-frame format changes
ALGO = f"v{CACHE_V}"
IGNORE_FIRST_S = 0.5            # rows already on screen when the clip starts are not kills


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


def ring_hist(bgr, x, y, tw, th, ring, sx, sy):
    """Colour histogram of the strips just above and below the name = the row highlight signature."""
    import cv2
    import numpy as np
    H, W = bgr.shape[:2]
    pad, ht, hb = int(ring["pad"] * sx), max(2, int(ring["ht"] * sy)), max(2, int(ring["hb"] * sy))
    x0, x1 = max(0, x - pad), min(W, x + tw + pad)
    parts = [p.reshape(-1, 3) for p in (bgr[max(0, y - ht):y, x0:x1], bgr[y + th:min(H, y + th + hb), x0:x1]) if p.size]
    if not parts:
        return None
    hsv = cv2.cvtColor(np.concatenate(parts).reshape(-1, 1, 3), cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256]).flatten()
    return h / max(h.sum(), 1)


def hp_img(gray):
    import cv2
    import numpy as np
    g = gray.astype(np.float32)
    return g - cv2.GaussianBlur(g, (0, 0), 3)


def row_band(gray, x, y, tw, th):
    """Right part of the row (weapon + victim) as a compact high-pass signature (hex): identifies a row wherever it moved."""
    import cv2
    import numpy as np
    b = gray[y:y + th, x + tw:].astype(np.float32)
    if b.shape[1] < 8 or b.shape[0] < 4:
        return ""
    b = cv2.resize(b - cv2.GaussianBlur(b, (0, 0), 3), (48, 6), interpolation=cv2.INTER_AREA)
    m = float(np.abs(b).max()) or 1.0
    return np.clip(b / m * 127, -127, 127).astype(np.int8).tobytes().hex()


_SIGS = {}


def sig_corr(a, b):
    import numpy as np
    if not a or not b:
        return 0.0
    for k in (a, b):
        if k not in _SIGS:
            if len(_SIGS) > 20000:
                _SIGS.clear()
            v = np.frombuffer(bytes.fromhex(k), np.int8).astype(np.float32)
            _SIGS[k] = v - v.mean()
    va, vb = _SIGS[a], _SIGS[b]
    d = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb / d) if d > 1e-6 else 0.0


def band_corr(a, b):
    import cv2
    r = float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0])
    return 0.0 if r != r else r


SCALE_GRID = [0.6, 0.7, 0.8, 0.9, 1.0, 1.12, 1.25, 1.4, 1.6]


class Detector:
    def __init__(self, game):
        import cv2
        import numpy as np
        d = load_json(DATA / f"detect_{game}.json", None)
        if not d:
            raise RuntimeError(f"{game} not calibrated: use Troubleshoot > Calibrate killfeed")
        self.game, self.d = game, d
        self.tmpl = cv2.imdecode(np.fromfile(str(DATA / d["name_png"]), np.uint8), cv2.IMREAD_GRAYSCALE)
        self.hist = np.array(d["hist"], np.float32)
        hp = DATA / d["hs_png"] if d.get("hs_png") else None
        self.hs = cv2.imdecode(np.fromfile(str(hp), np.uint8), cv2.IMREAD_GRAYSCALE) if hp and hp.exists() else None
        self.lg = int(d.get("left_gap", 0))
        self.dw = int(round((d["region"][2] - d["region"][0]) * NORM_W))
        self.dh = int(round((d["region"][3] - d["region"][1]) * NORM_H))
        self._t = {}

    def tmpl_at(self, sx, sy):
        import cv2
        k = (round(sx, 3), round(sy, 3))
        if k not in self._t:
            h, w = self.tmpl.shape
            t = cv2.resize(self.tmpl, (max(4, int(round(w * sx))), max(4, int(round(h * sy)))),
                           interpolation=cv2.INTER_AREA if sx * sy < 1 else cv2.INTER_CUBIC)
            self._t[k] = (t, hp_img(t))
        return self._t[k][0]

    def _resp(self, gray, hp, sx, sy):
        """Name match = max(raw, high-pass) normalised correlation: robust to the translucent row background."""
        import cv2
        import numpy as np
        t = self.tmpl_at(sx, sy)
        if t.shape[0] >= gray.shape[0] or t.shape[1] >= gray.shape[1]:
            return None, t
        r1 = np.nan_to_num(cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED))
        r2 = np.nan_to_num(cv2.matchTemplate(hp, self._t[(round(sx, 3), round(sy, 3))][1], cv2.TM_CCOEFF_NORMED))
        return np.maximum(r1, r2), t

    def score_at(self, gray, hp, sx, sy):
        r, _ = self._resp(gray, hp, sx, sy)
        return float(r.max()) if r is not None else -1.0

    def search_scale(self, gray, hp):
        """x and y scale searched separately (0.6-1.6): coarse grid at half resolution, then full-res refinement."""
        import cv2
        g2 = cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        h2 = hp_img(g2)
        base = Detector.__new__(Detector)
        base.__dict__.update(self.__dict__)
        base.tmpl = cv2.resize(self.tmpl, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        base._t = {}
        best = (-1.0, 1.0, 1.0)
        for sx in SCALE_GRID:
            for sy in SCALE_GRID:
                sc = base.score_at(g2, h2, sx, sy)
                if sc > best[0]:
                    best = (sc, sx, sy)
        bx, by = best[1], best[2]
        for fx in (0.94, 1.0, 1.06):
            for fy in (0.94, 1.0, 1.06):
                sc = self.score_at(gray, hp, bx * fx, by * fy)
                if sc > best[0]:
                    best = (sc, bx * fx, by * fy)
        return best

    def has_hs(self, gray, x, y, tw, th, sx, sy):
        import cv2
        if self.hs is None:
            return False
        t = cv2.resize(self.hs, (max(3, int(self.hs.shape[1] * sx)), max(3, int(self.hs.shape[0] * sy))))
        band = gray[max(0, y - 4):y + th + 4, x + tw:]
        if band.shape[0] <= t.shape[0] or band.shape[1] <= t.shape[1]:
            return False
        return float(cv2.matchTemplate(band, t, cv2.TM_CCOEFF_NORMED).max()) >= self.d.get("hs_thr", 0.7)

    def detect(self, gray, hp, bgr, sx, sy, floor=0.45):
        """All FIREAXE-name candidates >= floor with raw scores: name, highlight, victim-side flag, left-edge evidence."""
        import numpy as np
        r, t = self._resp(gray, hp, sx, sy)
        if r is None:
            return []
        th, tw = t.shape
        ys, xs = np.where(r >= floor)
        if not len(xs):
            return []
        picked = []
        for i in np.argsort(-r[ys, xs])[:300]:
            x, y = int(xs[i]), int(ys[i])
            if any(abs(x - p[2]) < tw // 2 and abs(y - p[3]) < th // 2 for p in picked):
                continue
            picked.append((float(r[y, x]), 0, x, y))
            if len(picked) >= 8:
                break
        res = []
        for sc, _, x, y in picked:
            victim = gray.shape[1] - (x + tw) < self.d["min_right"] * sx       # my name at the victim end = my death
            h = ring_hist(bgr, x, y, tw, th, self.d["ring"], sx, sy)
            hl = float(np.minimum(h, self.hist).sum()) if h is not None else 0.0
            lf = 0.0
            if not victim and self.lg >= 3:                                    # does the row continue left of my name?
                xs0 = int(x - self.lg * sx - 14 * sx)
                if xs0 >= 0:
                    hh = ring_hist(bgr, xs0, y, 12, th, dict(self.d["ring"], pad=0), sx, sy)
                    lf = float(np.minimum(hh, self.hist).sum()) if hh is not None else 0.0
            res.append({"score": sc, "hl": hl, "x": x, "y": y, "w": tw, "h": th, "v": int(victim), "lf": lf,
                        "hs": self.has_hs(gray, x, y, tw, th, sx, sy), "sig": row_band(gray, x, y, tw, th)})
        return res


def accept(n, h, tn, th):
    return (n >= tn and h >= th) or (h >= 0.9 and n >= 0.6)


def region_filter(rec, det, cfg):
    """ffmpeg filter that cuts the killfeed region out of the content rect and stretches it to 1920x1080 space."""
    cx, cy, cw, ch = content_rect(rec, cfg)
    x0, y0, x1, y1 = det.d["region"]
    rx, ry = int(cx + x0 * cw) & ~1, int(cy + y0 * ch) & ~1
    rw, rh = max(2, int((x1 - x0) * cw) & ~1), max(2, int((y1 - y0) * ch) & ~1)
    rw, rh = min(rw, rec["w"] - rx), min(rh, rec["h"] - ry)
    return f"crop={rw}:{rh}:{rx}:{ry},scale={det.dw}:{det.dh}:flags=bicubic,format=bgr24"


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


SCALES = DATA / "scales.json"
ONSET_CACHE = DATA / "onsets_cache.json"
_scale_lock = threading.Lock()


def scale_key(game, det, rec, cfg):
    return f"{game}|{det.d['stamp']}|{rec['w']}x{rec['h']}|{content_rect(rec, cfg)}"


def get_scale(det, game, rec, cfg, peers=()):
    """x/y HUD scale solved once per (game, resolution, content rect) and cached (scales.json)."""
    import cv2
    with _scale_lock:
        cache = load_json(SCALES, {})
        k = scale_key(game, det, rec, cfg)
        e = cache.get(k)
        if e and (e["solved"] or e.get("tries", 0) >= 4):
            return e
        best = (-1.0, 1.0, 1.0)
        for r in ([rec] + list(peers))[:3]:
            for fr in frame_stream(r["path"], r, det, cfg, 2):
                g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
                sc = det.search_scale(g, hp_img(g))
                if sc[0] > best[0]:
                    best = sc
                if best[0] >= 0.85 or CANCEL.is_set():
                    break
            if best[0] >= 0.85 or CANCEL.is_set():
                break
        solved = best[0] >= 0.5
        e = {"sx": round(best[1], 3) if solved else 1.0, "sy": round(best[2], 3) if solved else 1.0,
             "score": round(best[0], 3), "solved": solved, "tries": (e or {}).get("tries", 0) + 1}
        cache[k] = e
        save_json(SCALES, cache)
        out(f"  scale solved for {rec['w']}x{rec['h']} rect {content_rect(rec, cfg)}: x{e['sx']} y{e['sy']} (match {e['score']})"
            + ("" if solved else "  UNSOLVED - no killfeed row seen yet, using 1.0"))
        return e


def scan_clip(path, rec, det, cfg, scale):
    """Full 15 fps scan. Stores RAW per-frame candidates (name, highlight, slot...) so thresholds can change without rescanning."""
    import cv2
    t0 = time.time()
    sx, sy = scale
    dets, bn, bh, n = [], 0.0, 0.0, 0
    for f, fr in enumerate(frame_stream(path, rec, det, cfg, FPS)):
        n += 1
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        for c in det.detect(g, hp_img(g), fr, sx, sy):
            dets.append([f, round(c["score"], 3), round(c["hl"], 3), c["x"], c["y"], int(c["hs"]), c["sig"], c["v"], round(c["lf"], 3)])
            if not c["v"]:
                bn, bh = max(bn, c["score"]), max(bh, c["hl"])
    return {"v": CACHE_V, "dets": dets, "scale": [sx, sy], "frames": n, "row_h": det.tmpl_at(sx, sy).shape[0],
            "v_off": rec.get("v_off", 0.0), "best_name": round(bn, 3), "best_hl": round(bh, 3), "secs": round(time.time() - t0, 1)}


def load_kills_cache():
    c = load_json(KILLS_CACHE, {})
    return c if c.get("__version__") == CACHE_V else {"__version__": CACHE_V}


def compute_kills(entry, cfg):
    """Raw frames -> (kills, deaths). A kill = a NEW row where FIREAXE is the first name; persisting/shifting rows,
    my deaths (name on the victim side), assists (row continues left of my name) and double counts are excluded."""
    tn, th, tl = cfg.get("thr_name", 0.60), cfg.get("thr_hl", 0.30), cfg.get("thr_left", 0.80)
    rh, off = entry.get("row_h", 30), entry.get("v_off", 0.0)
    nf = entry.get("frames", 0)
    by, dth = {}, []
    for f, n, h, x, y, hs, sig, v, lf in entry.get("dets", []):
        if not accept(n, h, tn, th):
            continue
        if v:
            dth.append(f / FPS + off)
        elif lf < tl:
            by.setdefault(f, []).append((n, h, x, y, hs, sig))
    deaths, lastd = [], -9.0
    for t in sorted(dth):
        if t - lastd > 1.0:
            deaths.append(round(t, 2))
        lastd = t
    tracks, cnt, hist = [], {}, {}
    for f in sorted(by):
        keep = []
        for d in sorted(by[f], key=lambda d: -d[0]):
            if all(abs(d[3] - k[3]) > 0.6 * rh or abs(d[2] - k[2]) > 6 for k in keep):
                keep.append(d)
        cnt[f], hist[f] = len(keep), [d[3] for d in keep]
        prev = max([cnt.get(g, 0) for g in range(f - 4, f)] or [0])
        recent = [y for g in range(f - 4, f) for y in hist.get(g, [])] + [t["y"] for t in tracks if f - t["last"] <= 8]
        for n, h, x, y, hs, sig in keep:
            hit, hc = None, -1.0
            for t in tracks:
                if f - t["last"] > TRACK_KEEP_S * FPS:
                    continue
                c = sig_corr(sig, t["sig"])
                pos = abs(x - t["x"]) <= 6 and abs(y - t["y"]) <= 0.5 * rh and f - t["last"] <= 8
                if (pos or c >= 0.85) and c > hc:
                    hit, hc = t, c
            if hit:
                hit.update(last=f, x=x, y=y, sig=sig, hits=hit["hits"] + 1)
                if hs and hit["kill"] is not None and f - hit["first"] <= 20:
                    hit["kill"]["hs"] = True
                continue
            maxc = max([sig_corr(sig, t["sig"]) for t in tracks if f - t["last"] <= 8] or [0.0])
            is_new = len(keep) > prev or (all(abs(y - py) > 0.6 * rh for py in recent) and maxc < 0.6)
            k = None
            if is_new and f / FPS >= IGNORE_FIRST_S:
                k = {"t": round(f / FPS + off, 3), "name": n, "hl": h, "hs": bool(hs)}
            tracks.append({"first": f, "last": f, "x": x, "y": y, "sig": sig, "kill": k, "hits": 1})
    kills = [t["kill"] for t in tracks if t["kill"] and (t["hits"] >= 2 or t["first"] >= nf - 2)]
    kills.sort(key=lambda k: k["t"])
    return kills, deaths


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
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", rec["path"], "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "22050",
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
    """Apply the gunshot rule (a strong audio transient within 0.5 s before the kill row), refine each kill time with
    the shot, and drop kills inside the death lock. Returns stats."""
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
        for k in it["kills"]:
            st["raw"] += 1
            if ons is not None:
                cand = [o for o in ons if k["t"] - 0.6 <= o[0] <= k["t"] + 0.05]
                if not cand:
                    st["no_shot"] += 1
                    continue
                shot = max(cand, key=lambda o: o[0])[0]
                k = dict(k, lag=round(k["t"] - shot, 3), t=round(shot, 3))
            else:
                k = dict(k, lag=0.1, t=round(k["t"] - 0.1, 3))
            if any(d < k["t"] <= d + lock for d in it.get("deaths", [])):
                st["death_lock"] += 1
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
        if (only and g != only) or not (DATA / f"detect_{g}.json").exists():
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
        allp = sorted(walk_files([cfg["clip_root"]], VIDEO_EXT, MIN_VIDEO, cfg))
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
    if not next(walk_files([cfg["clip_root"]], VIDEO_EXT, MIN_VIDEO, cfg), None):
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
def do_calibrate(game, img, region, row, name, hs=None, expand=True):
    """img: 1920x1080 normalised screenshot/frame. Boxes are absolute x,y,w,h in that space."""
    import cv2
    (rx, ry, rw, rh), (ax, ay, aw, ah), (nx, ny, nw, nh) = region, row, name
    if not (rx <= ax and ry <= ay and ax + aw <= rx + rw and ay + ah <= ry + rh and
            ax <= nx and ay <= ny and nx + nw <= ax + aw and ny + nh <= ay + ah):
        raise ValueError("boxes must nest: name inside row inside killfeed region")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    tmpl = gray[ny:ny + nh, nx:nx + nw]
    if tmpl.std() < 15:
        raise ValueError("name box has almost no contrast - drag tighter around the FIREAXE letters")
    ex = int(0.10 * rw) if expand else 0
    rx2 = max(0, rx - ex)
    rw2 = min(NORM_W, rx + rw) - rx2
    rh2 = min(NORM_H - ry, int(rh * (1.10 if expand else 1.0)))
    ring = {"pad": int(0.25 * nw), "ht": max(3, ny - ay), "hb": max(3, ay + ah - (ny + nh))}
    hist = ring_hist(img, nx, ny, nw, nh, ring, 1.0, 1.0)
    png = f"detect_{game}_name.png"
    DATA.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", tmpl)
    buf.tofile(str(DATA / png))
    cv2.imencode(".png", img[ay:ay + ah, ax:ax + aw])[1].tofile(str(DATA / f"detect_{game}_row.png"))
    d = {"region": [rx2 / NORM_W, ry / NORM_H, (rx2 + rw2) / NORM_W, (ry + rh2) / NORM_H],
         "name_png": png, "ring": ring, "hist": [float(v) for v in hist],
         "min_right": max(40, int(0.35 * (ax + aw - (nx + nw)))), "left_gap": int(nx - ax)}
    if hs:
        hx, hy, hw, hh = hs
        cv2.imencode(".png", gray[hy:hy + hh, hx:hx + hw])[1].tofile(str(DATA / f"detect_{game}_hs.png"))
        d["hs_png"], d["hs_thr"] = f"detect_{game}_hs.png", 0.70
    d["stamp"] = hashlib.md5(buf.tobytes() + repr(region).encode() + repr(hs).encode()).hexdigest()[:10]
    save_json(DATA / f"detect_{game}.json", d)
    det = Detector(game)
    reg = img[int(d["region"][1] * NORM_H):int(d["region"][3] * NORM_H), int(d["region"][0] * NORM_W):int(d["region"][2] * NORM_W)]
    g = cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY)
    cfg = load_config()
    loose = [c for c in det.detect(g, hp_img(g), reg, 1.0, 1.0, floor=0.3) if not c["v"]]
    hits = [c for c in loose if accept(c["score"], c["hl"], cfg["thr_name"], cfg["thr_hl"]) and c["lf"] < cfg["thr_left"]]
    res = {"hits": len(hits), "name": max([h["score"] for h in loose], default=0), "hl": max([h["hl"] for h in loose], default=0)}
    out(f"{game} calibrated. self-test: {res['hits']} own row(s) found (name {res['name']:.2f}, highlight {res['hl']:.2f})")
    return res


def cmd_calibrate(args):
    cfg = load_config()
    img = norm_image(read_img(args.screenshot), cfg)
    if args.region and args.row and args.name:
        box = lambda s: tuple(int(float(v)) for v in s.split(","))
        region, row, name, hs = box(args.region), box(args.row), box(args.name), None
    else:
        out(f"Calibrating {args.game}: drags on your screenshot (the GUI Calibrate button is easier).")
        region = pick_roi(img, "1/3 drag a box around the WHOLE killfeed area (generous)")
        r = pick_roi(img[region[1]:region[1] + region[3], region[0]:region[0] + region[2]], "2/3 drag around YOUR kill row")
        row = (region[0] + r[0], region[1] + r[1], r[2], r[3])
        n = pick_roi(img[row[1]:row[1] + row[3], row[0]:row[0] + row[2]], "3/3 drag a TIGHT box around the text FIREAXE")
        name, hs = (row[0] + n[0], row[1] + n[1], n[2], n[3]), None
    try:
        do_calibrate(args.game, img, region, row, name, hs)
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
        raise RuntimeError("no calibrated game: use Troubleshoot > Calibrate killfeed")
    recs = [r for r in scan_clips(cfg) if not r.get("error") and r.get("w") and r.get("game") in dets]
    if paths is not None:
        ps = set(paths)
        recs = [r for r in recs if r["path"] in ps]
    cache = load_kills_cache()
    jobs = [(r, r["game"]) for r in recs if rescan or kills_key(r, r["game"], dets[r["game"]]) not in cache]
    if limit:
        jobs = jobs[:limit]
    groups = {}
    for r, g in jobs:
        groups.setdefault(scale_key(g, dets[g], r, cfg), []).append(r)
    out(f"{len(jobs)} clips to scan ({len(recs)} candidates; cached ones skipped)")
    done, errs, t0 = 0, 0, time.time()

    def work(job):
        r, g = job
        if CANCEL.is_set():
            return r, g, None, "cancelled", None
        try:
            sc = get_scale(dets[g], g, r, cfg, groups[scale_key(g, dets[g], r, cfg)][:3])
            return r, g, scan_clip(r["path"], r, dets[g], cfg, (sc["sx"], sc["sy"])), None, sc
        except Exception as ex:
            return r, g, None, f"{type(ex).__name__}: {ex}", None
    with ThreadPoolExecutor(max_workers=3) as ex:
        for r, g, res, err, sc in ex.map(work, jobs):
            done += 1
            progress(done / max(1, len(jobs)), f"scanning kills {done}/{len(jobs)}")
            if err == "cancelled":
                continue
            name = Path(r["path"]).name
            if err:
                errs += 1
                res = {"kills": [], "error": err}
                out(f"[{done}/{len(jobs)}] {g:8} ERROR {name}: {err}")
            else:
                ks, ds = compute_kills(res, cfg)
                out(f"[{done}/{len(jobs)}] {g:8} {len(ks)} kills {' '.join(ts(k['t']) for k in ks) or '-'}"
                    f" | best name {res['best_name']:.2f} hl {res['best_hl']:.2f} | scale {res['scale'][0]}x{res['scale'][1]}"
                    f"{'' if sc['solved'] else ' (UNSOLVED)'} | rect {content_rect(r, cfg)} crop {'yes' if r.get('bars') else 'no'} | {name} ({res['secs']}s)")
            cache[kills_key(r, g, dets[g])] = res
            if done % 5 == 0:
                save_json(KILLS_CACHE, cache)
    save_json(KILLS_CACHE, cache)
    out(f"scan finished: {done} in {time.time() - t0:.0f}s, errors {errs}")
    return done


def cmd_scan(args):
    run_scan(load_config(), [args.game] if args.game else None, None, args.limit, args.rescan)


def game_pool(cfg, game, paths=None):
    """([{rec, kills, deaths}], stats) from cached scans for one game; kills computed now from raw frames, then audio-verified."""
    det = load_dets(game).get(game)
    if not det:
        raise RuntimeError(f"{game} is not calibrated yet: Troubleshoot > Calibrate killfeed")
    cache = load_kills_cache()
    exc = []
    try:
        exc = [l.strip().lower() for l in (DATA / "exclude.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        pass
    ps = set(paths) if paths is not None else None
    stats = {"tagged": 0, "scanned": 0, "with_kills": 0}
    pool = []
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
        ks, ds = compute_kills(e, cfg)
        if ks:
            pool.append({"rec": r, "kills": ks, "deaths": ds})
    stats["with_kills"] = len(pool)
    stats["audio"] = verified_kills(pool, cfg) if pool else {"raw": 0, "no_shot": 0, "death_lock": 0, "kept": 0}
    pool = [it for it in pool if it["kills"]]
    return pool, stats


def grab_kill_crop(rec, det, cfg, k, scale):
    import cv2
    import numpy as np
    vf = region_filter(rec, det, cfg)
    t = k["t"] - rec.get("v_off", 0.0) + 0.3
    r = run(["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", rec["path"], "-frames:v", "1", "-vf", vf,
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], timeout=60)
    n = det.dw * det.dh * 3
    if len(r.stdout) < n:
        return None
    fr = np.frombuffer(r.stdout[:n], np.uint8).reshape(det.dh, det.dw, 3).copy()
    g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
    for d in det.detect(g, hp_img(g), fr, scale[0], scale[1], floor=0.45):
        ok = accept(d["score"], d["hl"], cfg["thr_name"], cfg["thr_hl"])
        col = (0, 255, 0) if ok and not d["v"] else (0, 0, 255)
        cv2.rectangle(fr, (d["x"], d["y"]), (d["x"] + d["w"], d["y"] + d["h"]), col, 2)
        cv2.putText(fr, f"{d['score']:.2f}/{d['hl']:.2f}{' DEATH' if d['v'] else ''} lf{d['lf']:.2f}", (d["x"], max(10, d["y"] - 3)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1, cv2.LINE_AA)
    cv2.putText(fr, f"{Path(rec['path']).name[-24:]} t={ts(k['t'])}" + (" HS" if k.get("hs") else ""),
                (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    return fr


def cmd_verify(args):
    import cv2
    import numpy as np
    cfg = load_config()
    det = load_dets(args.game).get(args.game)
    if not det:
        raise SystemExit("not calibrated")
    cache = load_kills_cache()
    items = []
    for r in scan_clips(cfg):
        e = cache.get(kills_key(r, args.game, det)) if r.get("game") == args.game and not r.get("error") else None
        if e and not e.get("error"):
            ks, _ = compute_kills(e, cfg)
            if ks:
                items.append((r, e, ks))
    if not items:
        raise SystemExit("no cached kills yet: run scan first")
    tiles = []
    for rec, e, ks in items[::max(1, len(items) // 6)][:6]:
        fr = grab_kill_crop(rec, det, cfg, ks[0], e["scale"])
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


def selftest_detection(cfg, per_game=20):
    """Runs the kill logic on up to 20 cached clips per game and prints score distributions to judge thresholds."""
    import numpy as np
    cache = load_kills_cache()
    shown = False
    for g in GAMES:
        det = load_dets(g).get(g)
        if not det:
            out(f"{g}: not calibrated")
            continue
        items = []
        for r in scan_clips(cfg):
            e = cache.get(kills_key(r, g, det)) if r.get("game") == g and not r.get("error") else None
            if e and not e.get("error"):
                items.append((r, e))
        if not items:
            out(f"{g}: no scanned clips yet (scan a few first)")
            continue
        items = items[::max(1, len(items) // per_game)][:per_game]
        shown = True
        bn = [e["best_name"] for _, e in items]
        bh = [e["best_hl"] for _, e in items]
        nk = []
        out(f"== {g}: {len(items)} cached clips, thresholds name>={cfg['thr_name']} hl>={cfg['thr_hl']} (or hl>=0.9 & name>=0.6), left<{cfg['thr_left']} ==")
        for r, e in items:
            ks, ds = compute_kills(e, cfg)
            nk.append(len(ks))
            out(f"  {len(ks)} kills, {len(ds)} deaths | best name {e['best_name']:.2f} hl {e['best_hl']:.2f} | scale {e['scale']} | {Path(r['path']).name}")
        pc = lambda a: ", ".join(f"p{q}={np.percentile(a, q):.2f}" for q in (10, 50, 90))
        out(f"  best-name scores: {pc(bn)}   best-highlight: {pc(bh)}")
        out(f"  clips with 0 kills: {sum(1 for k in nk if k == 0)}/{len(nk)}; clips with name<0.5 everywhere (likely detector/scale miss): {sum(1 for b in bn if b < 0.5)}")
        sc = load_json(SCALES, {})
        for k, v in sc.items():
            if k.startswith(g + "|"):
                out(f"  scale {k.split('|', 2)[2]}: x{v['sx']} y{v['sy']} match {v['score']} {'' if v['solved'] else 'UNSOLVED'}")
    if not shown:
        out("nothing to test yet")


# ======================================================================= SONGS
SONG_CACHE = DATA / "song_cache.json"
USED_CLIPS = DATA / "used_clips.json"
USED_SONGS = DATA / "used_songs.json"
SONG_ALGO = "s2"


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


def decode_mono(path, sr=22050):
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                       capture_output=True, timeout=300)
    return np.frombuffer(r.stdout, np.float32), sr


def smooth(a, w):
    import numpy as np
    w = max(1, int(w))
    return np.convolve(a, np.ones(w) / w, mode="same")


def analyse_song(path):
    """BPM, beat grid, downbeats, per-beat energy, section levels, drop. Cached per file."""
    cache = load_json(SONG_CACHE, {})
    key = file_key(path) + SONG_ALGO
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
    ibi = np.diff(bt)
    steady = float(max(0.0, 1 - np.std(ibi) / max(np.mean(ibi), 1e-6) * 8))
    if steady >= 0.75:      # steady (electronic) track: replace the tracked beats by a clean grid over the whole song
        per = float(np.median(ibi))
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
    bpm_fit = 1.0 if 100 <= bpm <= 180 else max(0.0, 1 - min(abs(bpm - 100), abs(bpm - 180)) / 40)
    an = {"bpm": round(bpm, 1), "beats": [round(float(t), 4) for t in bt], "down": [int(i) for i in down],
          "energy": [round(float(e), 3) for e in en], "level": [int(l) for l in level],
          "drop": None if drop is None else int(drop), "drop_strength": round(dstr, 3), "steady": round(steady, 3),
          "bpm_fit": round(bpm_fit, 2), "dur": round(len(y) / sr, 1),
          "onsets": [round(float(t), 3) for t in onsets[:2000]]}
    cache[key] = an
    save_json(SONG_CACHE, cache)
    return an


def song_fit(an):
    """Montage fit, 0-45: steady beat 15 + clear drop/energy rise 20 + BPM 100-180 10."""
    rise = max(an["drop_strength"], 0.0)
    return {"steady": round(15 * an["steady"], 1), "drop": round(20 * min(1.0, rise / 0.4), 1),
            "bpm": round(10 * an["bpm_fit"], 1)}


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
                songs[a["path"]] = {"path": a["path"], "artist": r["artist"], "title": r["title"], "added": added}
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
        fit = song_fit(an)
        pen = (30.0 if s["path"] == last else 0.0) + 8.0 * sum(1 for u in used[-4:] if u["path"] == s["path"])
        return {"recency": round(rec, 1), "fit": round(sum(fit.values()), 1), "fit_parts": fit, "penalty": pen,
                "total": round(rec + sum(fit.values()) - pen, 1), "days": None if d == 999 else d}
    if forced:
        s = next((x for x in songs if x["path"] == forced), None) or {"path": forced, "artist": "", "title": Path(forced).stem, "added": None}
        an = analyse_song(forced)
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
                an = analyse_song(s["path"])
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


def base_score(ev):
    n = ev["n"]
    if n >= 5:
        s = 100.0
    elif n == 4:
        s = 80.0
    elif n == 3:
        s = 60.0
    elif n == 2:
        s = 42.0 if ev["span"] <= 2.5 else 30.0
    else:
        s = 8.0 + (14 if ev.get("flick") else 0) + (12 if ev["hs"] else 0)
    if n >= 2:
        s += min(10.0, 10.0 * n / (ev["span"] + 1.0) / 2) + 4 * ev["hs"]
    return s


def build_events(pool, game, cfg, rng, flick_budget=40):
    gap = cfg["gap_s"][game]
    evs = []
    for item in pool:
        ks = sorted(item["kills"], key=lambda k: k["t"])
        groups, cur = [], [ks[0]]
        for k in ks[1:]:
            if k["t"] - cur[-1]["t"] <= gap:
                cur.append(k)
            else:
                groups.append(cur)
                cur = [k]
        groups.append(cur)
        for g in groups:
            times = [k["t"] for k in g]                      # already refined to the gunshot
            evs.append({"rec": item["rec"], "path": item["rec"]["path"], "times": times, "n": len(g),
                        "lags": [k.get("lag", 0.1) for k in g],
                        "first": times[0], "last": times[-1], "span": times[-1] - times[0],
                        "hs": sum(1 for k in g if k.get("hs")), "flick": False})
    singles = [e for e in evs if e["n"] == 1 and not e["hs"]]
    rng.shuffle(singles)
    for e in singles[:flick_budget]:
        try:
            e["flick"] = flick_value(e["rec"], cfg, e["first"]) >= 2.5
        except Exception:
            pass
    for e in evs:
        e["score"] = base_score(e)
    evs.sort(key=lambda e: -e["score"])
    return evs


# ======================================================================= PLANNER
LEAD_LO, LEAD_HI, LEAD_MIN, TAIL_S, SLOW_OUT = 1.5, 2.5, 1.2, 1.0, 0.4
MIN_TAKE_BEATS, MIN_TAKE_S, OUT_FPS = 2, 1.2, 60
RECIPES = {
    "hardcut": {"zoom_p": 0.15, "zoom_amp": 0.05, "ramp_p": 0.0, "flash": False, "slow_max": 1},
    "ramp": {"zoom_p": 0.30, "zoom_amp": 0.06, "ramp_p": 0.7, "flash": False, "slow_max": 1},
    "zoom": {"zoom_p": 0.95, "zoom_amp": 0.11, "ramp_p": 0.1, "flash": False, "slow_max": 1},
    "flash": {"zoom_p": 0.50, "zoom_amp": 0.08, "ramp_p": 0.15, "flash": True, "slow_max": 1},
    "slowmo": {"zoom_p": 0.40, "zoom_amp": 0.07, "ramp_p": 0.0, "flash": False, "slow_max": 4},
}


def pick_recipe(rng, style, avoid):
    names = list(RECIPES) + ["mix"]
    name = style if style in names else rng.choice([n for n in names if n != avoid] or names)
    if name == "mix":
        return name, {"zoom_p": rng.uniform(.2, .9), "zoom_amp": rng.uniform(.05, .10), "ramp_p": rng.uniform(0, .5),
                      "flash": rng.random() < .5, "slow_max": rng.randint(1, 3)}
    return name, dict(RECIPES[name])


def geom(ev, bt, c, kb, end, ramp, slow):
    """One continuous take: starts lead_t (1.5-2.5 s, whole beats) before the FIRST kill, keeps every kill in view,
    ends on a beat ~1 s after the LAST kill. Later kills are nudged onto beats with 0.85-1.15x speed. None if infeasible."""
    import numpy as np
    lead_t = float(bt[kb] - bt[c])
    D = float(bt[end] - bt[c])
    if lead_t < LEAD_MIN or end - c < MIN_TAKE_BEATS or D < MIN_TAKE_S:
        return None
    times = ev["times"]
    first, last = times[0], times[-1]
    r = 1.0
    if ramp > 1.0:
        r = min(ramp, first / lead_t)
        r = r if r >= 1.15 else 1.0
    if first - lead_t * r < -1e-6:
        return None
    segs, kills_out = [], [lead_t]
    if lead_t * r > 0.03:
        segs.append((first - lead_t * r, first, r))
    cur_out, cur_src, snapped = lead_t, first, 0
    t0 = float(bt[c])
    for tk in times[1:]:
        ds = tk - cur_src
        if ds < 0.04:
            kills_out.append(cur_out)
            continue
        sp, tgt = 1.0, cur_out + ds
        k = int(np.argmin(np.abs(bt - (t0 + tgt))))
        cand = float(bt[k] - t0)
        if cand > cur_out + 0.05 and 0.85 <= ds / (cand - cur_out) <= 1.15:
            sp, tgt, snapped = ds / (cand - cur_out), cand, snapped + 1
        segs.append((cur_src, tk, sp))
        kills_out.append(tgt)
        cur_out, cur_src = tgt, tk
    post = D - cur_out
    if post < 0.45:
        return None
    sl = bool(slow) and post >= SLOW_OUT + 0.45
    src_end = last + post - (0.2 if sl else 0.0)
    if src_end > ev["rec"]["dur"] - 0.08:
        return None
    if sl:
        segs += [(last, last + 0.2, 0.5), (last + 0.2, src_end, 1.0)]
    else:
        segs.append((last, src_end, 1.0))
    return {"ev": ev, "c": c, "kb": kb, "end": end, "lead_t": lead_t, "dur": D, "segs": segs, "ramp": r, "slow": sl,
            "kills_out": kills_out, "snapped": snapped}


def place(ev, bt, down, c=None, kb=None, end=None, ramp=1.0, slow=False):
    """Try lead-ins of 1.5-2.5 s (relaxed to 1.2 s only if the clip starts too close), whole-beat lengths,
    preferring 4-beat multiples and a downbeat for the first kill."""
    nb = len(bt) - 1
    pairs = []
    for lo, hi in ((LEAD_LO, LEAD_HI), (LEAD_MIN, LEAD_LO - 1e-6)):
        if kb is not None:
            pairs = [(kb - k, kb) for k in range(1, kb + 1) if lo <= bt[kb] - bt[kb - k] <= hi]
        else:
            for k2 in range(c + 1, nb):
                lt = bt[k2] - bt[c]
                if lt > hi:
                    break
                if lt >= lo:
                    pairs.append((c, k2))
        if pairs:
            break
    pairs.sort(key=lambda p: (p[1] not in down, (p[1] - p[0]) % 4 != 0, abs((bt[p[1]] - bt[p[0]]) - 2.0)))
    span = ev["times"][-1] - ev["times"][0]
    for cc, kk in pairs:
        lead = bt[kk] - bt[cc]
        if end is not None:
            ends = [end]
        else:
            j0 = next((j for j in range(kk + 1, nb + 1) if bt[j] - bt[cc] >= lead + span + TAIL_S), nb)
            jmin = next((j for j in range(kk + 1, nb + 1) if bt[j] - bt[cc] >= lead + span + 0.5), nb)
            up = list(range(j0, min(nb, j0 + 7) + 1))
            dn = list(range(j0 - 1, jmin - 1, -1))
            ends = ([j for j in up if (j - cc) % 4 == 0] + [j for j in up if (j - cc) % 4 and (j - cc) % 2 == 0] +
                    [j for j in up if (j - cc) % 2] + [j for j in dn if (j - cc) % 4 == 0] + [j for j in dn if (j - cc) % 4])
        for j in ends:
            g = geom(ev, bt, cc, kk, j, ramp, slow)
            if g:
                return g
    return None


def plan_montage(cfg, game, events, song, an, seed, style, target_s, hist_c, notes):
    """Event-driven, song-anchored layout: every usable event is placed (never dropped for build-up reasons); the best
    multikill lands on the drop downbeat; takes are whole beats (4-beat phrases preferred); length follows the material."""
    import numpy as np
    rng = random.Random(seed)
    rname, rp = pick_recipe(rng, style, hist_c[-1].get("recipe") if hist_c else None)
    bt = np.array(an["beats"], float)
    N = len(bt) - 1
    down, en, lv = set(an["down"]), an["energy"], an["level"]
    bd = float(np.median(np.diff(bt)))
    cap_b = int(min(120.0, max(60.0, float(target_s or 85)) * 1.1) / bd)
    heads = {h.get("headline") for h in hist_c[-4:]}
    ev_sorted = sorted(events, key=lambda e: -e["score"])
    total_ev = len(ev_sorted)

    def nat(e):
        lead = min(max(int(math.ceil(LEAD_LO / bd)), 2), int(LEAD_HI / bd))
        if e["times"][0] < lead * bd:
            lead = max(int(math.ceil(LEAD_MIN / bd)), 2)
        span = e["times"][-1] - e["times"][0]
        L = lead + int(math.ceil((span + TAIL_S) / bd))
        L = ((L + 3) // 4) * 4
        avail = int((e["rec"]["dur"] - 0.1 - e["times"][0]) / bd) + lead
        if L > avail:
            L = max(avail // 2 * 2, lead + int(math.ceil((span + 0.5) / bd)))
        return max(L, MIN_TAKE_BEATS)
    usable, skipped = [], []
    for e in ev_sorted:
        (usable if place(e, bt, down, c=8) else skipped).append(e)
    if skipped:
        notes.append(f"{len(skipped)} events cannot form a take (clip too short around the kill)")
    if not usable:
        raise RuntimeError("no kill event has enough footage around it to form a take")
    head_cands = [e for e in usable if e["path"] not in heads] or usable
    head = head_cands[0]
    rest = [e for e in usable if e is not head]
    total = nat(head) + sum(nat(e) for e in rest)
    cut_len = []
    while total > cap_b and rest:                          # length-driven only: drop the lowest-ranked
        e = rest.pop()
        total -= nat(e)
        cut_len.append(e)
    if cut_len:
        notes.append(f"{len(cut_len)} lowest-ranked events left out to keep the montage near {target_s or 85:.0f} s")
    d0 = min(down)
    dr = an["drop"] if an["drop"] is not None else int(0.45 * N)
    dc = [i for i in sorted(down) if 12 <= i <= N - 16] or sorted(down)
    dc8 = [i for i in dc if (i - d0) % 8 == 0]             # drop on an 8-beat phrase boundary
    drop = min(dc8 or dc, key=lambda i: abs(i - dr))
    fx = {}
    slow_ids = [id(e) for e in sorted(rest, key=lambda e: -e["score"]) if e["score"] >= 30][:rp["slow_max"]]
    for e in rest:
        fx[id(e)] = (rng.uniform(1.4, 1.9) if rng.random() < rp["ramp_p"] else 1.0, id(e) in slow_ids)

    def place_fx(e, c=None, kb=None, end=None):
        ramp, sl = fx.get(id(e), (1.0, False))
        for rr, ss in ((ramp, sl), (1.0, sl), (1.0, False)):
            t = place(e, bt, down, c=c, kb=kb, end=end, ramp=rr, slow=ss)
            if t:
                if t["slow"] and not (lv[t["kb"]] == 0 or en[t["kb"]] < 0.45):
                    t = place(e, bt, down, c=c, kb=kb, end=end, ramp=rr, slow=False) or t
                return t
        return None
    head_take = None
    for e in head_cands[:10]:
        head_take = place(e, bt, down, kb=drop)
        if head_take:
            if e is not head:
                rest = [x for x in rest if x is not e] + ([head] if head not in rest else [])
                head = e
            break
    if not head_take:
        raise RuntimeError("no clip could be placed on the drop")
    c_h = head_take["c"]
    avail_pre = c_h
    asc = sorted(rest, key=lambda e: e["score"])
    pre, acc = [], 0
    for e in asc:
        if acc >= 0.38 * total or acc + nat(e) > avail_pre:
            break
        pre.append(e)
        acc += nat(e)
    post = [e for e in sorted(rest, key=lambda e: -e["score"]) if e not in pre]
    singles = [e for e in post if e["n"] == 1]
    if len(post) >= 4 and singles:                         # a quiet single as the outro
        post.remove(singles[0])
        post.append(singles[0])
    pre.sort(key=lambda e: (e["n"], e["score"]))

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
    for _ in range(12):
        if not pre:
            break
        res, c_end = run_pre(pre, s0)
        if res is None:                                    # that event cannot sit here: it goes after the drop instead
            pre.remove(c_end)
            post.insert(0, c_end)
            continue
        g = c_h - c_end
        if g == 0:
            pre_takes = res
            break
        if s0 + g < 0:
            e = pre.pop()
            post.insert(0, e)
            s0 = max(0, c_h - sum(nat(x) for x in pre))
            continue
        s0 += g                                            # start later/earlier so the build-up ends exactly on the headline
    else:
        notes.append("build-up could not be aligned exactly; the montage starts at the headline lead-in")
        for e in pre:
            post.insert(0, e)
        pre, pre_takes = [], []
    if pre and not pre_takes:
        notes.append("build-up events moved after the drop (could not be aligned)")
        for e in pre:
            post.insert(0, e)
    takes = pre_takes + [head_take]
    c = head_take["end"]
    left = []
    for e in post:
        t = place_fx(e, c=c)
        if t:
            takes.append(t)
            c = t["end"]
        else:
            left.append(e)
    for e in left[:]:
        t = place_fx(e, c=c)
        if t:
            takes.append(t)
            c = t["end"]
            left.remove(e)
    if left:
        notes.append(f"{len(left)} events did not fit before the song ended")
    for t in list(takes):                                  # no fragments
        if t["end"] - t["c"] < MIN_TAKE_BEATS or bt[t["end"]] - bt[t["c"]] < MIN_TAKE_S:
            takes.remove(t)
            notes.append("removed a take shorter than the minimum")
    bt0 = float(bt[takes[0]["c"]])
    c0 = takes[0]["c"]

    def cf(i):
        return int(round((float(bt[i]) - bt0) * OUT_FPS))
    out_takes = []
    for t in takes:
        ev, kb = t["ev"], t["kb"]
        role = "headline" if t is head_take else ("drop" if lv[kb] == 2 else "build" if lv[kb] == 1 else "calm")
        f0, nf = cf(t["c"]), cf(t["end"]) - cf(t["c"])
        cum, bounds = 0.0, [0]
        for a, b, sp in t["segs"]:
            cum += (b - a) / sp
            bounds.append(int(round(cum * OUT_FPS)))
        bounds[-1] = nf
        segs = []
        for i, (a, b, sp) in enumerate(t["segs"]):
            n = bounds[i + 1] - bounds[i]
            if n > 0:
                segs.append([round(a, 3), round(b, 3), round(sp, 4), n])
        strong = kb in down or en[kb] >= 0.6
        ko = t["kills_out"]
        pulses = []
        if role == "headline" or (strong and rng.random() < rp["zoom_p"]):
            pulses.append(ko[0])
        for k2 in ko[1:]:
            j = int(np.argmin(np.abs(bt - (bt[t["c"]] + k2))))
            if abs(bt[j] - (bt[t["c"]] + k2)) < 0.06 and (j in down or en[j] >= 0.6) and len(pulses) < 3 \
                    and rng.random() < rp["zoom_p"] * 0.6:
                pulses.append(k2)
        out_takes.append({"path": ev["path"], "rect": content_rect(ev["rec"], cfg), "audio": ev["rec"].get("audio", True),
                          "wh": [ev["rec"]["w"], ev["rec"]["h"]], "segs": segs, "f0": f0, "nf": nf,
                          "out_start": round(f0 / OUT_FPS, 3), "dur": round(nf / OUT_FPS, 3), "role": role,
                          "pulses": [round(p, 3) for p in pulses], "amp": round(rp["zoom_amp"], 3),
                          "flash": round(ko[0], 3) if role == "headline" and rp["flash"] else None,
                          "beat0": int(t["c"] - c0), "beat_end": int(t["end"] - c0), "beat_kill": int(kb - c0),
                          "song_beat": int(t["c"]), "kill_down": kb in down,
                          "kills": [round(x, 2) for x in ev["times"]], "kills_out": [round(x, 3) for x in ko],
                          "lags": [round(x, 3) for x in ev["lags"]], "n": ev["n"], "score": round(ev["score"], 1),
                          "hs": ev["hs"], "ramp": round(t["ramp"], 2), "slow": t["slow"], "snapped": t["snapped"],
                          "level": int(lv[kb])})
    total_f = out_takes[-1]["f0"] + out_takes[-1]["nf"]
    total_s = total_f / OUT_FPS
    notes.insert(0, f"MONTAGE LENGTH {total_s:.0f} s from {len(out_takes)} of {total_ev} kill events" +
                 (" - UNDER 60 s: not enough usable material, this is the longest good montage possible" if total_s < 60 else ""))
    return {"game": game, "seed": seed, "recipe": rname,
            "params": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in rp.items()},
            "song": {"path": song["path"], "artist": song["artist"], "title": song["title"], "bpm": an["bpm"],
                     "start_t": round(bt0, 4), "drop_t": round(cf(drop) / OUT_FPS, 2), "drop_beat": int(drop - c0)},
            "takes": out_takes, "duration": round(total_s, 3), "total_frames": total_f, "notes": notes,
            "beats_out": [round(float(bt[i]) - bt0, 4) for i in range(c0, takes[-1]["end"] + 1)],
            "beats_n": int(takes[-1]["end"] - c0), "headline": head_take["ev"]["path"]}


def verify_cutlist(plan):
    """Final check before rendering: contiguous frames, every take >= 2 beats and >= 1.2 s, segments add up."""
    bad, pos = [], 0
    for i, t in enumerate(plan["takes"], 1):
        if t["f0"] != pos:
            bad.append(f"take {i} starts at frame {t['f0']}, expected {pos}")
        if t["nf"] < MIN_TAKE_S * OUT_FPS or t["beat_end"] - t["beat0"] < MIN_TAKE_BEATS:
            bad.append(f"take {i} is under the minimum ({t['nf']} frames, {t['beat_end'] - t['beat0']} beats)")
        if sum(sg[3] for sg in t["segs"]) != t["nf"]:
            bad.append(f"take {i} segment frames do not add up")
        pos = t["f0"] + t["nf"]
    return bad


def fmt_plan(plan, events, score_info, runners, unmatched, csvname):
    L = []
    sg = plan["song"]
    L.append(f"GAME     {plan['game']}      seed {plan['seed']}      style recipe: {plan['recipe']} {plan['params']}")
    L.append(f"SONG     {sg['artist']} - {sg['title']}   [{Path(sg['path']).name}]   BPM {sg['bpm']}")
    L.append(f"TIMELINE song starts at {ts(sg['start_t'])}; {plan['beats_n']} beats = {plan['duration']:.1f}s at 60 fps "
             f"({plan['total_frames']} frames); best multikill on the drop: beat {sg['drop_beat']} at {sg['drop_t']:.1f}s")
    if score_info:
        fp = score_info["fit_parts"]
        L.append(f"SONG SCORE total {score_info['total']} = recency {score_info['recency']} (added {score_info['days']} days ago)"
                 f" + fit {score_info['fit']} (steady {fp['steady']}, drop {fp['drop']}, bpm {fp['bpm']}) - used-penalty {score_info['penalty']}")
    for s2, sc in runners:
        L.append(f"   runner-up: {s2['artist']} - {s2['title']}  total {sc['total']} (recency {sc['recency']}, fit {sc['fit']}, penalty {sc['penalty']})")
    for n in plan["notes"]:
        L.append(f"NOTE     {n}")
    bad = verify_cutlist(plan)
    L.append("CUT LIST CHECK: " + ("OK - no take under 2 beats / 1.2 s, contiguous frames" if not bad else "PROBLEMS: " + "; ".join(bad)))
    L.append("\nRANKED KILL EVENTS (top 20)")
    for i, ev in enumerate(events[:20], 1):
        L.append(f"  {i:2}. score {ev['score']:5.1f}  {ev['n']}k{' HS' * (ev['hs'] > 0)}{' flick' * bool(ev['flick'])}  "
                 f"{Path(ev['path']).name} @ {', '.join(ts(t) for t in ev['times'])}")
    L.append(f"\nCUT LIST ({len(plan['takes'])} takes; 'beat' = beat number in the montage, [song beat])")
    for i, t in enumerate(plan["takes"], 1):
        fx = ("slow-mo " if t["slow"] else "") + (f"ramp x{t['ramp']} " if t["ramp"] > 1 else "") + \
             (f"snap{t['snapped']} " if t["snapped"] else "") + (f"zoom@{','.join(f'{p:.2f}' for p in t['pulses'])} " if t["pulses"] else "") + \
             ("FLASH" if t["flash"] is not None else "")
        L.append(f"  {i:2}. cut at beat {t['beat0']:3d} [{t['song_beat']}] {t['f0'] / OUT_FPS:6.2f}s  {t['nf']:4d}f = {t['beat_end'] - t['beat0']:2d} beats  "
                 f"first kill on beat {t['beat_kill']}{' (downbeat)' if t['kill_down'] else ''}  [{t['role']}] {t['n']}k  "
                 f"{Path(t['path']).name} @ {', '.join(ts(k) for k in t['kills'])}  {fx}")
    L.append(f"\nPLAYLIST tracks with no MP3 yet: {len(unmatched)}" + (f" (CSV {csvname})" if csvname else ""))
    for r in unmatched[:15]:
        L.append(f"   {r['artist']} - {r['title']}")
    return "\n".join(L)


# ======================================================================= RENDER
FX_ALL = ("zoom", "flash", "slow")


def ff_has(kind, name):
    r = run(["ffmpeg", "-hide_banner", f"-{kind}"]).stdout.decode(errors="replace")
    return name in r


def amix_has_normalize():
    return "normalize" in run(["ffmpeg", "-hide_banner", "-h", "filter=amix"]).stdout.decode(errors="replace")


def slice_plan(plan, length=20.0):
    """Preview slice: ~20 s centred on the drop, cut at take boundaries (frame exact)."""
    takes = plan["takes"]
    t0 = max([t["f0"] for t in takes if t["f0"] <= (plan["song"]["drop_t"] - 8.0) * OUT_FPS] or [0])
    sel = [t for t in takes if t["f0"] >= t0 and t["f0"] < t0 + length * OUT_FPS]
    nt = [dict(t, f0=t["f0"] - t0, out_start=round((t["f0"] - t0) / OUT_FPS, 3)) for t in sel]
    sg = dict(plan["song"], start_t=plan["song"]["start_t"] + t0 / OUT_FPS)
    tf = nt[-1]["f0"] + nt[-1]["nf"]
    return dict(plan, takes=nt, song=sg, duration=tf / OUT_FPS, total_frames=tf)


def build_filter(plan, cfg, preview, fx=FX_ALL):
    """One filter graph. Every effect is placed on the OUTPUT timeline of its take (after speed ramps/trims)."""
    inputs, chains, vl, k = [], [], [], 0
    gv = float(cfg.get("game_audio_level", 0.5))
    boost = min(1.0, gv * 1.585)                                   # about +4 dB around each kill
    for t in plan["takes"]:
        off_f, shift = 0, 0.0
        for si, (a, b, sp, n) in enumerate(t["segs"]):
            out_len = n / OUT_FPS
            if "slow" not in fx and sp == 0.5:                       # slow-mo disabled: play that stretch at normal speed
                b2 = a + out_len
                shift = b2 - b
                b, sp = b2, 1.0
            elif shift:
                a, b = a + shift, b + shift
            src_len = (b - a)
            off = off_f / OUT_FPS
            i = k
            inputs += ["-threads", "2", "-ss", f"{a:.3f}", "-t", f"{src_len + 0.1:.3f}", "-i", t["path"]]
            cx, cy, cw, ch = t["rect"]
            crop = f"crop={cw}:{ch}:{cx}:{cy}," if [cx, cy, cw, ch] != [0, 0, t["wh"][0], t["wh"][1]] else ""
            v = f"[{i}:v:0]{crop}scale=1920:1080:flags=lanczos,setsar=1,setpts=(PTS-STARTPTS)/{sp:.4f},"
            v += "framerate=fps=60:scene=100" if sp < 1 else "fps=60"
            terms = []
            if "zoom" in fx:
                for p in t["pulses"]:
                    pf = (p - off) * OUT_FPS
                    if -30 < pf < n:
                        terms.append(f"between(in-({pf:.1f}),0,27)*exp(-0.15*(in-({pf:.1f})))")
            if terms:
                v += (f",zoompan=z='1+{t['amp']}*({'+'.join(terms)})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                      f":d=1:s=1920x1080:fps=60")
            if "flash" in fx and t["flash"] is not None and 0 <= t["flash"] - off < out_len:
                f0 = t["flash"] - off
                v += f",drawbox=x=0:y=0:w=iw:h=ih:color=white@0.8:t=fill:enable='between(t,{f0:.3f},{f0 + 0.12:.3f})'"
            v += f",tpad=stop_mode=clone:stop_duration=0.2,trim=end_frame={n},setpts=PTS-STARTPTS[v{k}]"
            chains.append(v)
            if t["audio"]:
                at = f"atempo={min(2.0, max(0.5, sp)):.4f}," if abs(sp - 1.0) > 1e-3 else ""
                kt = [f"between(t,{ko - off - 0.2:.3f},{ko - off + 0.2:.3f})" for ko in t["kills_out"] if -0.25 < ko - off < out_len + 0.25]
                vol = f"volume='{gv:.3f}+{boost - gv:.3f}*min(1,{'+'.join(kt)})':eval=frame" if kt else f"volume={gv:.3f}"
                chains.append(f"[{i}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,{at}{vol},"
                              f"asetpts=PTS-STARTPTS,apad,atrim=duration={out_len:.4f}[a{k}]")
            else:
                chains.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={out_len:.4f},asetpts=PTS-STARTPTS[a{k}]")
            vl.append(f"[v{k}][a{k}]")
            off_f += n
            k += 1
    D = plan["duration"]
    sidx = k
    inputs += ["-ss", f"{plan['song']['start_t']:.3f}", "-t", f"{D + 0.6:.3f}", "-i", plan["song"]["path"]]
    chains.append("".join(vl) + f"concat=n={k}:v=1:a=1[vc][gc]")
    chains.append(f"[vc]{'scale=1280:720:flags=bicubic,' if preview else ''}fade=t=out:st={max(0, D - 1.5):.3f}:d=1.5,format=yuv420p[vout]")
    chains.append(f"[{sidx}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[sg]")
    mix = "amix=inputs=2:duration=longest:normalize=0" if amix_has_normalize() else "amix=inputs=2:duration=longest,volume=2"
    chains.append(f"[sg][gc]{mix},alimiter=limit=0.97,atrim=duration={D:.3f},afade=t=out:st={max(0, D - 2):.3f}:d=2[aout]")
    return inputs, ";\n".join(chains)


def enc_args(maxq, preview, nvenc):
    if preview:
        v = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "26", "-b:v", "0"] if nvenc else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "24"]
    elif maxq:
        v = ["-c:v", "libx264", "-crf", "15", "-preset", "slow"]
    elif nvenc:
        v = ["-c:v", "h264_nvenc", "-preset", "p7", "-tune", "hq", "-rc", "vbr", "-cq", "18", "-b:v", "0", "-rc-lookahead", "32"]
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


def render_plan(plan, outfile, cfg, maxq=False, preview=False):
    """Encode with all effects; if ffmpeg fails, retry without the failing effect, then without all effects."""
    outfile = Path(outfile)
    outfile.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    p = slice_plan(plan) if preview else plan
    bad = verify_cutlist(p)
    if bad:
        raise RuntimeError("cut list problem, not rendering: " + "; ".join(bad))
    D = min(p["duration"], 20.0) if preview else p["duration"]
    nvenc = ff_has("encoders", "h264_nvenc")
    tmp = outfile.with_name(outfile.stem + ".part.mp4")
    elog = LOG_DIR / "last_render_stderr.txt"
    gp = LOG_DIR / "last_filter.txt"
    fx, failed = set(FX_ALL), []
    while True:
        inputs, graph = build_filter(p, cfg, preview, fx)
        gp.write_text(graph, encoding="utf-8")
        txt = ""
        for use_nv in ((nvenc, False) if nvenc else (False,)):
            cmd = (["ffmpeg", "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1"] + inputs +
                   ["-filter_complex_script", str(gp), "-map", "[vout]", "-map", "[aout]", "-t", f"{D:.3f}"] +
                   enc_args(maxq, preview, use_nv) + [str(tmp)])
            rc = _run_ffmpeg(cmd, D, elog)
            if CANCEL.is_set():
                raise RuntimeError("cancelled")
            if rc == 0 and tmp.exists():
                os.replace(tmp, outfile)
                out(f"rendered {outfile}" + (f"   (effects that failed and were skipped: {', '.join(failed)})" if failed else ""))
                plan["fx_failed"] = failed
                return outfile
            txt = elog.read_text(encoding="utf-8", errors="replace")
            out(f"ffmpeg failed ({'NVENC' if use_nv else 'x264'}): {txt[-500:]}")
            if not (use_nv and any(w in txt.lower() for w in ("nvenc", "cuda", "encoder", "driver"))):
                break
            out("retrying with libx264")
        if not fx:
            break
        low = txt.lower()
        culprit = next((n for key, n in (("zoompan", "zoom"), ("drawbox", "flash"), ("framerate", "slow"), ("atempo", "slow"))
                        if key in low and n in fx), None) or next(n for n in FX_ALL if n in fx)
        failed.append(culprit)
        fx.discard(culprit)
        out(f"effect '{culprit}' failed - retrying without it" + ("" if fx else " (no effects left)"))
    raise RuntimeError(f"render failed even without effects - see {elog} and {gp}")


def sync_report(plan, outfile, cfg):
    """Runs the kill detector on the finished montage; each kill vs the nearest beat, in ms (target < 40 ms)."""
    import numpy as np
    game = plan["game"]
    det = load_dets(game).get(game)
    if not det:
        return
    out("SYNC REPORT: scanning the finished montage with the kill detector ...")
    rec = probe_video(str(outfile))
    rec.update(path=str(outfile), game=game, bars=False)
    sc = get_scale(det, game, rec, cfg)
    entry = scan_clip(str(outfile), rec, det, cfg, (sc["sx"], sc["sy"]))
    seen, _ = compute_kills(entry, cfg)
    seen = [k["t"] for k in seen]
    beats = np.array(plan["beats_out"])
    rows, errs_first, errs_all = [], [], []
    for i, t in enumerate(plan["takes"], 1):
        for j, ko in enumerate(t["kills_out"]):
            tp = t["f0"] / OUT_FPS + ko
            kb = int(np.argmin(np.abs(beats - tp)))
            err = (tp - beats[kb]) * 1000
            lag = t["lags"][j] if j < len(t["lags"]) else 0.1
            m = [x for x in seen if abs(x - (tp + lag)) < 0.45]
            drift = (min(m, key=lambda x: abs(x - (tp + lag))) - (tp + lag)) * 1000 if m else None
            errs_all.append(abs(err))
            if j == 0:
                errs_first.append(abs(err))
            rows.append(f"  take {i:2} kill {j + 1}: at {tp:7.3f}s  nearest beat #{kb} ({beats[kb]:7.3f}s)  error {err:+6.0f} ms"
                        f"{' (first kill, on beat by design)' if j == 0 else ' (nudged)' if t['snapped'] else ''}"
                        f"   detector saw the row {'%+.0f ms vs plan' % drift if drift is not None else 'NOT FOUND'}")
    out("SYNC REPORT (planned kill times on the output timeline vs beats; detector drift is +-33 ms resolution)")
    for r in rows:
        out(r)
    ok = sum(1 for e in errs_all if e < 40)
    okf = sum(1 for e in errs_first if e < 40)
    out(f"SYNC SUMMARY: first kills within 40 ms of a beat: {okf}/{len(errs_first)}; all kills: {ok}/{len(errs_all)}; "
        f"detector found {len(seen)} kill rows in the montage for {len(errs_all)} planned kills")


# ======================================================================= ORCHESTRATION
GAME_DIR = {"valorant": "Valorant", "cs2": "CS2"}
LAST_PLAN = {}


def week_tag(now):
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


def weekly_existing(cfg, game, now=None):
    d = Path(cfg["output_root"]) / GAME_DIR[game]
    pat = f"{GAME_DIR[game]}_{week_tag(now or datetime.datetime.now())}_*.mp4"
    return sorted(d.glob(pat)) if d.is_dir() else []


def make_plan(cfg, game, paths=None, song_path=None, target=None, style=None, seed=None):
    cfg = autodetect_dirs(cfg)
    if not load_dets(game).get(game):
        raise RuntimeError(f"{game} is not calibrated yet. Open Troubleshoot > Calibrate killfeed and mark your FIREAXE row once.")
    tagged = [r for r in scan_clips(cfg) if r.get("game") == game]
    if not tagged:
        inc = cfg["include_valorant"] if game == "valorant" else cfg["include_cs"]
        raise RuntimeError(f"No {game} clips found: no folder under {cfg['clip_root']} has a name containing {inc} "
                           f"(or clips are over {cfg['max_mb']} MB / {cfg['max_dur_s']} s). Check Settings.")
    manual = paths is not None
    if paths is None:
        paths = auto_scan_set(cfg, game)
        out(f"auto: {len(paths)} uncached clips to scan this run (last {cfg['auto_recent_days']} days + up to {cfg['auto_old_per_run']} older)")
    if paths:
        run_scan(cfg, [game], paths)
    pool, st = game_pool(cfg, game, set(paths) if manual else None)
    au = st["audio"]
    out(f"{game}: {st['tagged']} clips in included folders, {st['scanned']} scanned, {st['with_kills']} with detected kills; "
        f"gunshot check: {au['raw']} detected kills -> {au['no_shot']} had no gunshot, {au['death_lock']} after my death, {au['kept']} kept")
    if not pool:
        raise RuntimeError(f"{st['tagged']} {game} clips, {st['scanned']} scanned, but 0 usable kills "
                           f"({au['raw']} detected, {au['no_shot']} without a gunshot, {au['death_lock']} after my death). "
                           "Run Troubleshoot > Self-test detection to see the scores, or scan more clips.")
    seed = int(seed) if seed else random.randrange(1, 10 ** 6)
    events = build_events(pool, game, cfg, random.Random(seed))
    songs, unmatched, csvname = song_pool(cfg)
    song, an, sinfo, runners = pick_song(cfg, game, songs, forced=song_path)
    notes = []
    plan = plan_montage(cfg, game, events, song, an, seed, style, target or cfg.get("length_s", 85), hist_list(USED_CLIPS, game), notes)
    plan["song_score"] = sinfo
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
            seed=None, maxq=None, weekly=False):
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
        plan, text = make_plan(cfg, game, paths, song_path, target, style, seed)
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
            return render_plan(plan, odir / f"preview_{GAME_DIR[game]}.mp4", cfg, maxq, True)
        outfile = odir / (base + ".mp4")
        render_plan(plan, outfile, cfg, maxq, False)
        (odir / (base + ".plan.txt")).write_text(text, encoding="utf-8")
        save_json(odir / (base + ".plan.json"), plan)
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
          ("scipy", "scipy"), ("mutagen", "mutagen"), ("rapidfuzz", "rapidfuzz"), ("tkinter", None)]
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
            ("scipy", "scipy"), ("mutagen", "mutagen"), ("rapidfuzz", "rapidfuzz")]


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
    """Pick a clip (or screenshot), scrub to one of your kills, drag over your killfeed row, then over FIREAXE."""
    def __init__(self, app):
        self.app, self.cfg = app, load_config()
        self.win = tk.Toplevel(app.root)
        self.win.title("Calibrate killfeed (one time per game)")
        top = ttk.Frame(self.win)
        top.pack(fill="x", padx=6, pady=4)
        self.game = tk.StringVar(value="valorant")
        ttk.Combobox(top, textvariable=self.game, values=list(GAMES), width=10, state="readonly").pack(side="left")
        ttk.Button(top, text="Open clip...", command=self.open_clip).pack(side="left", padx=4)
        ttk.Button(top, text="Open screenshot...", command=self.open_shot).pack(side="left")
        ttk.Button(top, text="Restart selection", command=self.reset).pack(side="left", padx=8)
        self.skip = ttk.Button(top, text="Skip headshot icon", command=self.finish_ready)
        self.save = ttk.Button(top, text="Save calibration", command=self.do_save, state="disabled")
        self.save.pack(side="right")
        self.skip.pack(side="right", padx=6)
        self.scale = ttk.Scale(self.win, from_=0, to=1, command=lambda v: None)
        self.scale.bind("<ButtonRelease-1>", lambda e: self.load_frame())
        self.msg = tk.StringVar(value="Open a clip (scrub to a moment your FIREAXE kill row is visible) or a screenshot.")
        ttk.Label(self.win, textvariable=self.msg, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=6)
        self.cv = tk.Canvas(self.win, width=1280, height=720, bg="#222")
        self.cv.pack(padx=6, pady=6)
        self.cv.bind("<ButtonPress-1>", self.press)
        self.cv.bind("<B1-Motion>", self.drag)
        self.cv.bind("<ButtonRelease-1>", self.release)
        self.base, self.path, self.dur = None, None, 0
        self.reset()

    def reset(self):
        self.stage, self.row, self.name, self.hs, self.rect_id, self.p0 = 0, None, None, None, None, None
        self.view = None
        self.save.config(state="disabled")
        if self.base is not None:
            self.show(self.base, (0, 0))
            self.msg.set("1/2  Drag a box around YOUR kill row (the row with FIREAXE as the killer), including its highlight border.")

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
            messagebox.showerror("Calibrate", str(ex))

    def load_frame(self):
        try:
            self.base, _ = grab_norm_frame(self.path, float(self.scale.get()), self.cfg)
            self.reset()
        except Exception as ex:
            self.msg.set(str(ex))

    def open_shot(self):
        p = filedialog.askopenfilename(initialdir=str(HERE.parent), filetypes=[("image", "*.png *.jpg *.jpeg *.bmp")])
        if p:
            self.scale.pack_forget()
            self.base = norm_image(read_img(p), self.cfg)
            self.reset()

    def show(self, img, origin):
        self.photo, s = to_photo(img)
        self.view = {"s": s, "o": origin}
        self.cv.delete("all")
        self.cv.create_image(0, 0, anchor="nw", image=self.photo)
        for r, col in ((self.row, "#0f0"), (self.name, "#ff0"), (self.hs, "#0ff")):
            if r and self.stage == 0 and r is self.row:
                self.box(r, col)

    def box(self, r, col):
        s, o = self.view["s"], self.view["o"]
        self.cv.create_rectangle((r[0] - o[0]) * s, (r[1] - o[1]) * s, (r[0] + r[2] - o[0]) * s, (r[1] + r[3] - o[1]) * s, outline=col, width=2)

    def press(self, e):
        self.p0 = (e.x, e.y)
        if self.rect_id:
            self.cv.delete(self.rect_id)
        self.rect_id = self.cv.create_rectangle(e.x, e.y, e.x, e.y, outline="#f0f", width=2)

    def drag(self, e):
        if self.p0 and self.rect_id:
            self.cv.coords(self.rect_id, self.p0[0], self.p0[1], e.x, e.y)

    def release(self, e):
        if not self.p0 or self.base is None or not self.view:
            return
        s, o = self.view["s"], self.view["o"]
        x0, x1 = sorted((self.p0[0], e.x))
        y0, y1 = sorted((self.p0[1], e.y))
        self.p0 = None
        if x1 - x0 < 4 or y1 - y0 < 4:
            return
        r = (int(x0 / s + o[0]), int(y0 / s + o[1]), int((x1 - x0) / s), int((y1 - y0) / s))
        if self.stage == 0:
            self.row = r
            crop = self.base[r[1]:r[1] + r[3], r[0]:r[0] + r[2]]
            self.stage = 1
            self.show_zoom(crop, (r[0], r[1]))
            self.msg.set("2/2  Drag a TIGHT box around just the text FIREAXE.")
        elif self.stage == 1:
            self.name = r
            self.stage = 2
            self.msg.set("Optional: drag over the HEADSHOT icon in a row where you got a headshot (or press Skip). Then Save.")
            self.save.config(state="normal")
        elif self.stage == 2:
            self.hs = r
            self.msg.set("Headshot icon set. Press Save calibration.")

    def show_zoom(self, crop, origin):
        import cv2
        z = min(1200 / crop.shape[1], 400 / crop.shape[0])
        big = cv2.resize(crop, None, fx=z, fy=z, interpolation=cv2.INTER_CUBIC)
        self.photo, s = to_photo(big, 1280, 720)
        self.view = {"s": z * s, "o": origin}
        self.cv.delete("all")
        self.cv.create_image(0, 0, anchor="nw", image=self.photo)
        self.rect_id = None

    def finish_ready(self):
        if self.name:
            self.do_save()

    def do_save(self):
        try:
            rw = self.row
            region = (max(0, int(rw[0] - 0.25 * rw[2])), max(0, int(rw[1] - 6 * rw[3])), 0, 0)
            x1, y1 = min(NORM_W, int(rw[0] + 1.1 * rw[2])), min(NORM_H, int(rw[1] + 9 * rw[3]))
            region = (region[0], region[1], x1 - region[0], y1 - region[1])
            res = do_calibrate(self.game.get(), self.base, region, self.row, self.name, self.hs, expand=False)
            msg = f"{self.game.get()} calibrated. Self-test found {res['hits']} own row(s)."
            if res["hits"] != 1:
                msg += "\nExpected exactly 1: try again with a tighter FIREAXE box."
            messagebox.showinfo("Calibrate", msg)
            self.app.refresh_auto()
        except Exception as ex:
            messagebox.showerror("Calibrate", str(ex))


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

    def __init__(self, start_tab=0):
        self.root = tk.Tk()
        self.root.title("Montage builder (Valorant / CS2)")
        self.root.geometry("1220x920")
        self.root.minsize(920, 640)
        self.q, self.busy, self.buttons, self._imgs, self.pending = queue.Queue(), False, [], [], []
        self.clips, self.ticked, self.songs, self.bpm, self.last_video, self.byp = [], set(), [], {}, None, {}
        self._fill_token = {}
        LOG_SINK[0] = lambda m: self.q.put(("log", m))
        PROGRESS[0] = lambda f, t: self.q.put(("prog", (f, t)))
        self.cfg = load_config()
        # bottom area first so the notebook can expand above it
        bot = ttk.Frame(self.root)
        bot.pack(side="bottom", fill="both", padx=6, pady=4)
        row = ttk.Frame(bot)
        row.pack(fill="x")
        self.pbar = ttk.Progressbar(row, maximum=1.0)
        self.pbar.pack(side="left", fill="x", expand=True)
        self.plabel = tk.StringVar(value="idle")
        ttk.Label(row, textvariable=self.plabel, width=34).pack(side="left", padx=6)
        ttk.Button(row, text="Cancel", command=stop_all).pack(side="left")
        res = ttk.Frame(bot)
        res.pack(fill="x", pady=3)
        self.vlabel = tk.StringVar(value="Last video: none yet")
        ttk.Label(res, textvariable=self.vlabel).pack(side="left")
        self.b_open = ttk.Button(res, text="Open video", command=self.safe(self.open_video), state="disabled")
        self.b_open.pack(side="right")
        self.b_folder = ttk.Button(res, text="Open folder", command=self.safe(self.open_vfolder))
        self.b_folder.pack(side="right", padx=4)
        lf = ttk.Frame(bot)
        lf.pack(fill="both", expand=True)
        self.log = tk.Text(lf, height=9, wrap="word", bg="#111", fg="#ddd")
        lsb = ttk.Scrollbar(lf, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=lsb.set)
        self.log.pack(side="left", fill="both", expand=True)
        lsb.pack(side="right", fill="y")
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(side="top", fill="both", expand=True, padx=6, pady=6)
        self.tabs = {n: ttk.Frame(self.nb) for n in ("Auto", "Manual", "Troubleshoot", "Settings")}
        for n, f in self.tabs.items():
            self.nb.add(f, text=n)
        self.build_auto()
        self.build_manual()
        self.build_trouble()
        self.build_settings()
        self.nb.select(start_tab)
        self.root.after(100, self.poll)
        self.root.after(400, self.startup)

    # ------------------------------------------------------------ plumbing
    def btn(self, parent, text, cmd, big=False, **kw):
        if big:
            b = tk.Button(parent, text=text, command=self.safe(cmd), font=("Segoe UI", 12, "bold"), height=2, **kw)
        else:
            b = ttk.Button(parent, text=text, command=self.safe(cmd), **kw)
        self.buttons.append(b)
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
        if self.busy:
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
        ttk.Label(f, text="One montage per game per week from all your clips - nothing to pick. "
                          "Calibrate each game once (Troubleshoot tab).", font=("Segoe UI", 10)).pack(anchor="w", padx=8, pady=8)
        self.auto_status = {}
        for g in GAMES:
            lf = ttk.LabelFrame(f, text=GAME_DIR[g])
            lf.pack(fill="x", padx=8, pady=8)
            sv = tk.StringVar()
            self.auto_status[g] = sv
            self.btn(lf, "Make this week's montage", lambda g=g: self.run_task(f"{g} auto", self.job_video(g, weekly=True)),
                     big=True).pack(side="left", padx=10, pady=10)
            col = ttk.Frame(lf)
            col.pack(side="left", fill="x", expand=True, padx=8)
            ttk.Label(col, textvariable=sv, justify="left").pack(anchor="w")
            sm = ttk.Frame(col)
            sm.pack(anchor="w", pady=4)
            for text, kw in (("Force new", dict(weekly=True, force=True)), ("Dry plan", dict(mode="dry", weekly=True)),
                             ("Preview 720p / 20 s", dict(mode="preview", weekly=True))):
                self.btn(sm, text, lambda g=g, kw=kw, text=text: self.run_task(f"{g} {text}", self.job_video(g, **kw))).pack(side="left", padx=3)
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
                allv = sorted([p for p in d.glob(f"{GAME_DIR[g]}_*.mp4")], key=lambda p: p.stat().st_mtime) if d.is_dir() else []
                lp = LAST_PLAN.get(g)
                song = f"{lp['song']['artist']} - {lp['song']['title']} ({lp['song']['bpm']} BPM)" if lp else "chosen when the montage is made (newest week first)"
                self.auto_status[g].set(
                    f"Calibrated: {'yes' if det else 'NO - Troubleshoot > Calibrate killfeed'}\n"
                    f"Clips scanned: {done} / {len(mine)}\n"
                    f"Song: {song}\n"
                    f"This week ({week_tag(datetime.datetime.now())}): {ex[-1].name if ex else 'no montage yet'}    "
                    f"Last montage: {allv[-1].name if allv else '-'}")
        except Exception:
            out("status refresh failed: " + traceback.format_exc()[-300:])

    # ------------------------------------------------------------ Manual tab
    def build_manual(self):
        f = self.tabs["Manual"]
        s1 = ttk.LabelFrame(f, text="Step 1 - tick the clips (click a row to tick it)")
        s1.pack(fill="both", expand=True, padx=8, pady=4)
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
        top2 = ttk.Frame(s1)
        top2.pack(fill="x", pady=2)
        self.btn(top2, "Tick all", lambda: self.tick("all")).pack(side="left", padx=3)
        self.btn(top2, "Untick all", lambda: self.tick("none")).pack(side="left", padx=3)
        self.btn(top2, "Tick clips with kills", lambda: self.tick("kills")).pack(side="left", padx=3)
        self.btn(top2, "Reload list", lambda: self.run_task("clips", self.load_clips)).pack(side="left", padx=12)
        self.btn(top2, "Exclude ticked from montages", self.exclude_sel).pack(side="left")
        fr, self.ctree = make_tree(s1, ("date", "len", "kills"), height=9, selectmode="none")
        fr.pack(fill="both", expand=True)
        for c, w, t in (("#0", 380, "clip"), ("date", 110, "date"), ("len", 60, "length"), ("kills", 90, "kills")):
            self.ctree.column(c, width=w)
            self.ctree.heading(c, text=t)
        self.ctree.bind("<Button-1>", self.on_tree_click)
        s2 = ttk.LabelFrame(f, text="Step 2 - choose the song (newest added first)")
        s2.pack(fill="both", expand=True, padx=8, pady=4)
        r2 = ttk.Frame(s2)
        r2.pack(fill="x", pady=2)
        ttk.Label(r2, text="Search").pack(side="left")
        self.m_search = tk.StringVar()
        self.m_search.trace_add("write", lambda *a: self.refresh_songs())
        ttk.Entry(r2, textvariable=self.m_search, width=30).pack(side="left", padx=4)
        self.btn(r2, "Play selected song", self.play_song).pack(side="left", padx=8)
        fr2, self.stree = make_tree(s2, ("bpm", "added"), height=6, selectmode="browse")
        fr2.pack(fill="both", expand=True)
        self.stree.column("#0", width=520)
        self.stree.column("bpm", width=70)
        self.stree.column("added", width=110)
        self.stree.heading("#0", text="song")
        self.stree.heading("bpm", text="BPM")
        self.stree.heading("added", text="added")
        self.stree.bind("<<TreeviewSelect>>", lambda e: self.update_status())
        s3 = ttk.LabelFrame(f, text="Step 3 - make it")
        s3.pack(fill="x", padx=8, pady=4)
        c3 = ttk.Frame(s3)
        c3.pack(fill="x", pady=2)
        ttk.Label(c3, text="Length (s)").pack(side="left")
        self.m_len = tk.IntVar(value=self.cfg.get("length_s", 85))
        ttk.Scale(c3, from_=60, to=120, variable=self.m_len, length=170, command=lambda v: self.update_status()).pack(side="left", padx=4)
        ttk.Label(c3, textvariable=self.m_len, width=4).pack(side="left")
        ttk.Label(c3, text="Style").pack(side="left", padx=(12, 2))
        self.m_style = tk.StringVar(value="random")
        ttk.Combobox(c3, textvariable=self.m_style, values=["random"] + list(RECIPES) + ["mix"], width=9, state="readonly").pack(side="left")
        ttk.Label(c3, text="Quality").pack(side="left", padx=(12, 2))
        self.m_q = tk.StringVar(value=self.cfg.get("quality", "nvenc"))
        ttk.Radiobutton(c3, text="Fast (NVENC)", variable=self.m_q, value="nvenc").pack(side="left")
        ttk.Radiobutton(c3, text="Max (x264 CRF15)", variable=self.m_q, value="max").pack(side="left", padx=4)
        ttk.Label(c3, text="Seed").pack(side="left", padx=(12, 2))
        self.m_seed = tk.StringVar()
        ttk.Entry(c3, textvariable=self.m_seed, width=8).pack(side="left")
        self.m_status = tk.StringVar(value="Tick some clips.")
        ttk.Label(s3, textvariable=self.m_status, font=("Segoe UI", 10, "bold"), wraplength=1100).pack(anchor="w", pady=4)
        bb = ttk.Frame(s3)
        bb.pack(fill="x", pady=4)
        for text, mode in (("Dry plan", "dry"), ("Preview (720p, 20 s)", "preview"), ("Render", "render")):
            self.btn(bb, text, lambda m=mode: self.manual(m), big=True).pack(side="left", expand=True, fill="x", padx=6)

    def on_tree_click(self, e):
        iid = self.ctree.identify_row(e.y)
        if iid:
            self.ticked.symmetric_difference_update({iid})
            self.ctree.item(iid, text=self.row_text(iid))
            self.update_status()
        return "break"

    def row_text(self, iid):
        c = self.byp.get(iid)
        return ("☑ " if iid in self.ticked else "☐ ") + (c["name"] if c else Path(iid).name)

    def tick(self, how):
        vis = self.ctree.get_children()
        for iid in vis:
            c = self.byp.get(iid)
            if how == "all" or (how == "kills" and c and c["kills"]):
                self.ticked.add(iid)
            elif how == "none":
                self.ticked.discard(iid)
            self.ctree.item(iid, text=self.row_text(iid))
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
                ks = [k["t"] for k in compute_kills(e, cfg)[0]]
            try:
                mt = os.path.getmtime(r["path"])
            except OSError:
                continue
            rel = os.path.relpath(r["path"], cfg["clip_root"])
            rows.append({"path": r["path"], "name": Path(r["path"]).name, "folder": str(Path(rel).parent), "mtime": mt,
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
        rows = []
        for c in self.clips:
            if (fo != "All folders" and c["folder"] != fo) or c["mtime"] < lim:
                continue
            rows.append((c["path"], self.row_text(c["path"]),
                         (time.strftime("%Y-%m-%d", time.localtime(c["mtime"])), f"{int(c['dur'] // 60)}:{int(c['dur'] % 60):02d}",
                          "not scanned" if c["kills"] is None else str(c["kills"]))))
        self.fill_chunked(self.ctree, rows)
        self.update_status()

    def refresh_songs(self):
        q = self.m_search.get().strip().lower()
        rows = [("auto", "★ Auto pick (this week's best fit)", ("", ""))]
        for s in self.songs:
            if q and q not in f"{s['artist']} {s['title']}".lower():
                continue
            rows.append((s["path"], f"{s['title']}  -  {s['artist']}" if s["artist"] else s["title"],
                         (self.bpm.get(s["path"], ""), s["added"].strftime("%Y-%m-%d") if s["added"] else "")))
        keep = self.stree.selection()
        self.fill_chunked(self.stree, rows)
        self.root.after(50, lambda: self.stree.selection_set(keep[0]) if keep and self.stree.exists(keep[0]) else self.stree.selection_set("auto") if self.stree.exists("auto") else None)

    def bpm_worker(self):
        """Quietly analyses the newest songs (cached) so BPM shows in the list; waits while a job is running."""
        sc = load_json(SONG_CACHE, {})
        for s in list(self.songs)[:40] or []:
            while self.busy:
                time.sleep(2)
            try:
                key = file_key(s["path"]) + SONG_ALGO
                an = sc.get(key) or analyse_song(s["path"])
                self.bpm[s["path"]] = an["bpm"]
                self.q.put(("call", lambda p=s["path"], b=an["bpm"]: self.stree.exists(p) and self.stree.set(p, "bpm", b)))
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
        cfg = self.cfg
        gap = cfg["gap_s"][self.m_game.get()]
        tk_ = [self.byp[p] for p in self.ticked if p in getattr(self, "byp", {})]
        kills = sum(c["kills"] or 0 for c in tk_)
        uns = sum(1 for c in tk_ if c["kills"] is None)
        est = 0.0
        for c in tk_:
            ks = c["ks"]
            i = 0
            while i < len(ks):
                j = i
                while j + 1 < len(ks) and ks[j + 1] - ks[j] <= gap:
                    j += 1
                est += 2.0 + (ks[j] - ks[i]) + 1.0
                i = j + 1
        est = min(est, int(self.m_len.get()) * 1.1) if est else 0
        sel = self.stree.selection()
        song = "auto pick"
        if sel and sel[0] != "auto":
            s = next((x for x in self.songs if x["path"] == sel[0]), None)
            if s:
                song = f"{s['title']} ({self.bpm.get(s['path'], '? ')} BPM)"
        txt = f"{len(tk_)} clips ticked, {kills} kills found"
        if uns:
            txt += f" ({uns} not scanned yet - they get scanned first)"
        txt += f", montage will be about {est:.0f} s" if est else ""
        if est and est < 60:
            txt += " (under 60 s: little material)"
        self.m_status.set(txt + f", song: {song}")

    def manual(self, mode):
        paths = list(self.ticked)
        if not paths:
            messagebox.showinfo("Manual", "Tick some clips first (Step 1).")
            return
        sel = self.stree.selection()
        song = None if not sel or sel[0] == "auto" else sel[0]
        seed = int(self.m_seed.get()) if self.m_seed.get().strip().isdigit() else None
        style = self.m_style.get()
        self.run_task("manual " + mode, self.job_video(
            self.m_game.get(), mode=mode, force=True, paths=paths, song_path=song, target=int(self.m_len.get()),
            style=None if style == "random" else style, seed=seed, maxq=(self.m_q.get() == "max")))

    # ------------------------------------------------------------ Troubleshoot tab
    def build_trouble(self):
        f = self.tabs["Troubleshoot"]
        r1 = ttk.LabelFrame(f, text="Checks and tools")
        r1.pack(fill="x", padx=8, pady=4)
        for text, cmd in (("Selfcheck (ffmpeg, NVENC, packages)", lambda: self.run_task("selfcheck", cmd_selfcheck, None)),
                          ("Calibrate killfeed...", lambda: CalibDialog(self)),
                          ("Self-test detection", lambda: self.run_task("selftest", selftest_detection, load_config())),
                          ("Scan all clips now", lambda: self.run_task("scan all", run_scan, load_config(), None, None)),
                          ("Open logs", lambda: self.open_path(LOG_DIR)),
                          ("Clear kill cache", self.clear_cache)):
            self.btn(r1, text, cmd).pack(side="left", padx=4, pady=4)
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
            out(f"{g} is not calibrated")
            return
        rec = analyse_clip(p, load_json(CLIPS_CACHE, {}), False, cfg.get("bar"))[1]
        rec["game"] = g
        e = load_kills_cache().get(kills_key(rec, g, det))
        if not e:
            out("not scanned yet: press Rescan this clip")
            return
        ks, ds = compute_kills(e, cfg)
        out(f"{Path(p).name}: {len(ks)} kills (before the gunshot check): " + ", ".join(ts(k['t']) + ("*HS" if k.get("hs") else "") for k in ks) +
            f"; my deaths at {', '.join(ts(d) for d in ds) or '-'}; best name {e['best_name']} hl {e['best_hl']}; scale {e['scale']}")
        pick = ks[0] if ks else None
        if pick is None and e.get("dets"):
            best = max(e["dets"], key=lambda d: d[1])
            pick = {"t": best[0] / FPS - 0.3 + e.get("v_off", 0)}
        if pick:
            fr = grab_kill_crop(rec, det, cfg, pick, e["scale"])
            if fr is not None:
                w = tk.Toplevel(self.root)
                w.title("Killfeed crop (green = accepted own row, red = rejected/death) with name/highlight scores")
                ph, _ = to_photo(fr, 900, 700)
                self._imgs.append(ph)
                ttk.Label(w, image=ph).pack()

    def rescan_clip(self):
        p = self.sel_clip()
        if not p:
            return

        def job():
            cache = load_kills_cache()
            fk = file_key(p) + "|"
            save_json(KILLS_CACHE, {k: v for k, v in cache.items() if not k.startswith(fk)})
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
            for pth in (KILLS_CACHE, FLICK_CACHE, ONSET_CACHE, SCALES):
                try:
                    pth.unlink()
                except OSError:
                    pass
            out("kill cache cleared")

    # ------------------------------------------------------------ Settings tab
    def build_settings(self):
        f = self.tabs["Settings"]
        self.sv = {}
        r = 0
        for k, lab in (("clip_root", "Clips folder (searched recursively)"), ("mp3_dir", "MP3 folder"),
                       ("playlist_dir", "Exportify CSV folder"), ("output_root", "Output folder")):
            ttk.Label(f, text=lab).grid(row=r, column=0, sticky="w", padx=8, pady=4)
            v = tk.StringVar(value=self.cfg.get(k, ""))
            self.sv[k] = v
            ttk.Entry(f, textvariable=v, width=70).grid(row=r, column=1, padx=4)
            ttk.Button(f, text="Browse", command=lambda v=v: v.set(filedialog.askdirectory(initialdir=v.get() or None) or v.get())).grid(row=r, column=2)
            r += 1
        self.sl = {}
        for k, lab in (("include_valorant", "Valorant folder names (comma separated)"), ("include_cs", "CS2 folder names (comma separated)")):
            ttk.Label(f, text=lab).grid(row=r, column=0, sticky="w", padx=8, pady=4)
            v = tk.StringVar(value=", ".join(self.cfg.get(k, [])))
            self.sl[k] = v
            ttk.Entry(f, textvariable=v, width=70).grid(row=r, column=1, padx=4)
            r += 1
        self.sn = {}
        for k, lab in (("max_mb", "Skip files larger than (MB)"), ("max_dur_s", "Skip clips longer than (s)"),
                       ("auto_recent_days", "Auto: scan every new clip from the last (days)"),
                       ("auto_old_per_run", "Auto: plus up to this many older clips per run"),
                       ("thr_name", "Detection: name threshold"), ("thr_hl", "Detection: highlight threshold"),
                       ("thr_left", "Detection: assist rejection (lower = stricter)"), ("death_lock_s", "No kills for this long after my death (s)"),
                       ("week_days", "'This week' means the last N days")):
            ttk.Label(f, text=lab).grid(row=r, column=0, sticky="w", padx=8, pady=3)
            v = tk.StringVar(value=str(self.cfg.get(k, "")))
            self.sn[k] = v
            ttk.Entry(f, textvariable=v, width=10).grid(row=r, column=1, sticky="w", padx=4)
            r += 1
        self.set_len = tk.IntVar(value=self.cfg.get("length_s", 85))
        self.set_aud = tk.IntVar(value=int(100 * self.cfg.get("game_audio_level", 0.5)))
        for lab, var, lo, hi in (("Default length (s)", self.set_len, 60, 120), ("Game audio level under the music (%)", self.set_aud, 0, 100)):
            ttk.Label(f, text=lab).grid(row=r, column=0, sticky="w", padx=8, pady=4)
            ttk.Scale(f, from_=lo, to=hi, variable=var, length=300).grid(row=r, column=1, sticky="w", padx=4)
            ttk.Label(f, textvariable=var).grid(row=r, column=2)
            r += 1
        self.set_q = tk.StringVar(value=self.cfg.get("quality", "nvenc"))
        self.set_sync = tk.BooleanVar(value=self.cfg.get("sync_report", True))
        ttk.Label(f, text="Quality").grid(row=r, column=0, sticky="w", padx=8, pady=4)
        qf = ttk.Frame(f)
        qf.grid(row=r, column=1, sticky="w")
        ttk.Radiobutton(qf, text="NVENC p7 cq18 (fast)", variable=self.set_q, value="nvenc").pack(side="left")
        ttk.Radiobutton(qf, text="Max quality x264 CRF15", variable=self.set_q, value="max").pack(side="left", padx=10)
        r += 1
        ttk.Checkbutton(f, text="Print a sync report after each render (re-scans the finished montage)", variable=self.set_sync).grid(row=r, column=1, sticky="w")
        r += 1
        self.btn(f, "Save settings", self.save_settings).grid(row=r, column=1, sticky="w", pady=12)

    def save_settings(self):
        cfg = load_config()
        for k, v in self.sv.items():
            cfg[k] = v.get().strip()
        for k, v in self.sl.items():
            cfg[k] = [x.strip() for x in v.get().split(",") if x.strip()]
        for k, v in self.sn.items():
            try:
                cfg[k] = float(v.get()) if "." in v.get() else int(v.get())
            except ValueError:
                out(f"ignored invalid number for {k}")
        cfg["length_s"], cfg["game_audio_level"] = int(self.set_len.get()), round(self.set_aud.get() / 100, 2)
        cfg["quality"], cfg["sync_report"] = self.set_q.get(), bool(self.set_sync.get())
        save_json(CONFIG_PATH, cfg)
        self.cfg = cfg
        out("settings saved")
        self.run_task("clips", self.load_clips)


def grab_gray_bgr(path, t, w, h):
    import numpy as np
    r = run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], timeout=60)
    return np.frombuffer(r.stdout[:w * h * 3], np.uint8).reshape(h, w, 3).copy()


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


def main():
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
    t = sp.add_parser("tag")
    t.add_argument("path")
    t.add_argument("game", choices=list(GAMES) + ["auto"])
    t.set_defaults(fn=cmd_tag)
    args = ap.parse_args()
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
