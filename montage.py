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
CLIPS_CACHE = DATA / "clips_cache2.json"
AUDIO_CACHE = DATA / "audio_cache.json"
KILLS_CACHE = DATA / "kills_cache.json"

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
    "game_audio_level": 0.15,
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


def tag_game(path, cfg):
    pl = norm(path)
    best = None
    for pre, g in cfg.get("game_overrides", {}).items():
        n = norm(pre)
        if (pl == n or pl.startswith(n + os.sep)) and (best is None or len(n) > best[0]):
            best = (len(n), g)
    if best and best[1] in GAMES:
        return best[1], "override"
    for part in reversed(Path(path).parts[:-1]):
        p = part.lower()
        if "valorant" in p:
            return "valorant", "folder"
        if re.search(r"\b(cs2|csgo|cs[ _-]?go|counter[ _-]?strike|cs)\b", p):
            return "cs2", "folder"
    return None, "unknown"


# --------------------------------------------------------------------- video
def probe_video(path):
    r = run(["ffprobe", "-v", "error", "-show_entries",
             "stream=codec_type,codec_name,width,height,avg_frame_rate,pix_fmt:format=duration",
             "-of", "json", path])
    j = json.loads(r.stdout or b"{}")
    st = j.get("streams") or []
    s = next((x for x in st if x.get("codec_type") == "video"), {})
    n, _, d = (s.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(n) / float(d) if d and float(d) else 0.0
    return {"codec": s.get("codec_name"), "w": s.get("width"), "h": s.get("height"),
            "fps": round(fps, 2), "pix_fmt": s.get("pix_fmt"),
            "audio": any(x.get("codec_type") == "audio" for x in st),
            "dur": float((j.get("format") or {}).get("duration") or 0)}


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
    paths = sorted(walk_files([root], VIDEO_EXT, MIN_VIDEO, cfg))
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
    for r in recs:
        r["game"], r["game_src"] = tag_game(r["path"], cfg)
    return recs


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
}


def newest_csv(cfg):
    d = Path(cfg["playlist_dir"])
    files = sorted(d.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True) if d.is_dir() else []
    return files[0] if files else None


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
                         "uri": (r.get(col["uri"]) or "").strip() if col["uri"] else ""})
    return p, rows, col


def clean(s):
    s = s.lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)
    s = re.sub(r"\b(feat|ft|featuring)\.?\b.*", " ", s)
    s = re.sub(r"[^a-z0-9\u00c0-\u024f\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def match_playlist(rows, audio, cfg):
    from rapidfuzz import fuzz
    thr = cfg["match_threshold"]
    prepared = [(a, clean(a["title"]), clean(a["artist"]), clean(a["artist"] + " " + a["title"])) for a in audio]
    matched, unmatched = [], []
    for r in rows:
        rt, ra = clean(r["title"]), clean(r["artist"])
        rfull = (ra + " " + rt).strip()
        best, bs = None, 0
        for a, at, aa, afull in prepared:
            ts = fuzz.token_set_ratio(rt, at)
            if ts < 80:
                continue
            if aa and ra:
                s = 0.6 * ts + 0.4 * max(fuzz.token_set_ratio(ra, aa), fuzz.partial_ratio(ra, aa))
            else:  # missing artist tag: judge on title + full string
                s = 0.5 * ts + 0.5 * fuzz.token_set_ratio(rfull, afull)
            if s > bs:
                best, bs = a, s
        (matched if best and bs >= thr else unmatched).append((r, best, round(bs)) if best and bs >= thr else r)
    return matched, unmatched


# ------------------------------------------------------------- kill detection
NORM_W, NORM_H = 1920, 1080     # every clip is normalised to this (content rect stretched)
FPS = 15
COARSE = [0.6, 0.7, 0.8, 0.9, 1.0, 1.12, 1.25, 1.4, 1.6]
TRACK_KEEP_S = 8.0              # a killfeed row is remembered this long (so it is never counted twice)
SAME_ROW_CORR = 0.90            # appearance match that means "same row as before" even if it moved (feed shift)
ALGO = "v2"                    # bump when the scan logic changes so cached results are redone
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


def row_band(gray, x, y, tw, th):
    """Right part of the row (weapon + victim): identifies a row regardless of where it has shifted to."""
    import cv2
    import numpy as np
    b = gray[y:y + th, x + tw:].astype(np.float32)
    if b.shape[1] < 8 or b.shape[0] < 4:
        return None
    return cv2.resize(b - cv2.GaussianBlur(b, (0, 0), 3), (192, 24), interpolation=cv2.INTER_AREA)   # high-pass: text/icon strokes only


def band_corr(a, b):
    import cv2
    r = float(cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)[0, 0])
    return 0.0 if r != r else r


class Detector:
    def __init__(self, game):
        import cv2
        import numpy as np
        d = load_json(DATA / f"detect_{game}.json", None)
        if not d:
            raise RuntimeError(f"{game} not calibrated: run  montage.py calibrate {game} <screenshot>")
        self.game, self.d = game, d
        self.tmpl = cv2.imdecode(np.fromfile(str(DATA / d["name_png"]), np.uint8), cv2.IMREAD_GRAYSCALE)
        self.hist = np.array(d["hist"], np.float32)
        hp = DATA / d["hs_png"] if d.get("hs_png") else None
        self.hs = cv2.imdecode(np.fromfile(str(hp), np.uint8), cv2.IMREAD_GRAYSCALE) if hp and hp.exists() else None
        self.dw = int(round((d["region"][2] - d["region"][0]) * NORM_W))
        self.dh = int(round((d["region"][3] - d["region"][1]) * NORM_H))
        self._t = {}

    def tmpl_at(self, sx, sy):
        import cv2
        k = (round(sx, 3), round(sy, 3))
        if k not in self._t:
            h, w = self.tmpl.shape
            self._t[k] = cv2.resize(self.tmpl, (max(4, int(round(w * sx))), max(4, int(round(h * sy)))),
                                    interpolation=cv2.INTER_AREA if sx * sy < 1 else cv2.INTER_CUBIC)
        return self._t[k]

    def response(self, gray, sx, sy):
        import cv2
        t = self.tmpl_at(sx, sy)
        if t.shape[0] >= gray.shape[0] or t.shape[1] >= gray.shape[1]:
            return None, t
        return cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED), t

    def best_score(self, gray, sx, sy):
        r, _ = self.response(gray, sx, sy)
        return float(r.max()) if r is not None else -1.0

    def has_hs(self, gray, x, y, tw, th, sx, sy):
        """Headshot icon somewhere right of the name inside this row (only if calibrated with one)."""
        import cv2
        if self.hs is None:
            return False
        t = cv2.resize(self.hs, (max(3, int(self.hs.shape[1] * sx)), max(3, int(self.hs.shape[0] * sy))))
        band = gray[max(0, y - 4):y + th + 4, x + tw:]
        if band.shape[0] <= t.shape[0] or band.shape[1] <= t.shape[1]:
            return False
        return float(cv2.matchTemplate(band, t, cv2.TM_CCOEFF_NORMED).max()) >= self.d.get("hs_thr", 0.7)

    def search_scale(self, gray):
        """Coarse isotropic search, then separate x/y refinement. Returns (score, sx, sy)."""
        best = (-1.0, 1.0, 1.0)
        for s in COARSE:
            sc = self.best_score(gray, s, s)
            if sc > best[0]:
                best = (sc, s, s)
        s0 = best[1]
        for fx in (0.92, 1.0, 1.08):
            for fy in (0.92, 1.0, 1.08):
                sc = self.best_score(gray, s0 * fx, s0 * fy)
                if sc > best[0]:
                    best = (sc, s0 * fx, s0 * fy)
        return best

    def detect(self, gray, bgr, sx, sy, hl_thr=None, loose=False):
        """Own-row candidates: FIREAXE name match AND highlight signature, killer position only.
        loose=True also returns name-only matches (flagged ok=False) so the tracker can follow a row whose
        highlight score flickers; only ok=True detections may start a new kill."""
        import numpy as np
        r, t = self.response(gray, sx, sy)
        if r is None:
            return []
        th, tw = t.shape
        ys, xs = np.where(r >= self.d["name_thr"])
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
            if gray.shape[1] - (x + tw) < self.d["min_right"] * sx:    # name at the victim end = my death row
                continue
            h = ring_hist(bgr, x, y, tw, th, self.d["ring"], sx, sy)
            hl = float(np.minimum(h, self.hist).sum()) if h is not None else 0.0
            ok = hl >= (self.d["hl_thr"] if hl_thr is None else hl_thr)
            if ok or loose:
                res.append({"score": sc, "hl": hl, "ok": ok, "x": x, "y": y, "w": tw, "h": th})
        return res


class Tracker:
    """Follows own rows frame to frame; a row never seen before (by appearance) is a new kill."""
    def __init__(self, det=None):
        self.tracks, self.kills, self.det = [], [], det

    def _hs(self, d, gray, sx, sy):
        try:
            return bool(self.det and self.det.has_hs(gray, d["x"], d["y"], d["w"], d["h"], sx, sy))
        except Exception:
            return False

    def update(self, f, dets, gray, sx=1.0, sy=1.0):
        for d in sorted(dets, key=lambda d: -d["score"]):
            band = row_band(gray, d["x"], d["y"], d["w"], d["h"])
            if band is None:
                continue
            hit, hc = None, 0.0
            for tr in self.tracks:
                c = band_corr(band, tr["band"])
                near = abs(d["x"] - tr["x"]) <= 6 and abs(d["y"] - tr["y"]) <= d["h"] // 2 and f - tr["last"] <= 6
                if (c >= SAME_ROW_CORR or (near and c >= 0.5)) and c > hc:
                    hit, hc = tr, c
            if hit:
                hit.update(last=f, x=d["x"], y=d["y"], band=band)
                k = hit.get("kill")
                if k is not None and not k["hs"] and f - hit["first"] <= 20:
                    k["hs"] = self._hs(d, gray, sx, sy)
            elif d["ok"]:
                k = None
                if f / FPS >= IGNORE_FIRST_S:
                    k = {"t": round(f / FPS, 2), "score": round(d["score"], 3), "hl": round(d["hl"], 3),
                         "hs": self._hs(d, gray, sx, sy)}
                    self.kills.append(k)
                self.tracks.append({"first": f, "last": f, "x": d["x"], "y": d["y"], "band": band, "kill": k})
        self.tracks = [t for t in self.tracks if f - t["last"] <= TRACK_KEEP_S * FPS]


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


def scan_clip(path, rec, det, cfg):
    import cv2
    t0 = time.time()
    lock_thr = det.d["name_thr"] + 0.08
    # pass 1: find this clip's HUD scale (rows stay on screen for seconds, so 3 fps is plenty); stop at first lock
    best, scale = -1.0, None
    for fr in frame_stream(path, rec, det, cfg, 3):
        sc, sx, sy = det.search_scale(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY))
        best = max(best, sc)
        if sc >= lock_thr:
            scale = (round(sx, 3), round(sy, 3))
            break
    sx, sy = scale or (1.0, 1.0)
    # pass 2: every frame at 15 fps, no pre-filtering
    tr, n = Tracker(det), 0
    for f, fr in enumerate(frame_stream(path, rec, det, cfg, FPS)):
        n += 1
        gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        dets = det.detect(gray, fr, sx, sy, loose=True)
        if dets:
            tr.update(f, dets, gray, sx, sy)
    return {"kills": tr.kills, "scale": [sx, sy], "locked": scale is not None,
            "disc_best": round(best, 3), "frames": n, "secs": round(time.time() - t0, 1)}


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


def clip_game(rec, dets, cache):
    """Folder tag, else HUD fallback: the game whose detector found more kills in the clip."""
    if rec.get("game"):
        return rec["game"]
    best = None
    for g, det in dets.items():
        e = cache.get(kills_key(rec, g, det))
        if e and e.get("kills"):
            sc = (len(e["kills"]), e.get("disc_best", 0))
            if best is None or sc > best[0]:
                best = (sc, g)
    return best[1] if best else None


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
         "min_right": max(40, int(0.35 * (ax + aw - (nx + nw)))),
         "name_thr": 0.62, "hl_thr": 0.30}
    if hs:
        hx, hy, hw, hh = hs
        cv2.imencode(".png", gray[hy:hy + hh, hx:hx + hw])[1].tofile(str(DATA / f"detect_{game}_hs.png"))
        d["hs_png"], d["hs_thr"] = f"detect_{game}_hs.png", 0.70
    d["stamp"] = hashlib.md5(buf.tobytes() + repr(region).encode() + repr(hs).encode()).hexdigest()[:10]
    save_json(DATA / f"detect_{game}.json", d)
    det = Detector(game)
    reg = img[int(d["region"][1] * NORM_H):int(d["region"][3] * NORM_H), int(d["region"][0] * NORM_W):int(d["region"][2] * NORM_W)]
    g = cv2.cvtColor(reg, cv2.COLOR_BGR2GRAY)
    hits, loose = det.detect(g, reg, 1.0, 1.0), det.detect(g, reg, 1.0, 1.0, hl_thr=0.0)
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
def run_scan(cfg, games=None, paths=None, limit=0, rescan=False):
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found - open Troubleshoot > Selfcheck")
    ensure_bars(cfg)
    dets = load_dets()
    if games:
        dets = {g: d for g, d in dets.items() if g in games}
    if not dets:
        raise RuntimeError("no calibrated game: use Troubleshoot > Calibrate")
    recs = [r for r in scan_clips(cfg) if not r.get("error") and r.get("w")]
    if paths:
        ps = set(paths)
        recs = [r for r in recs if r["path"] in ps]
    cache = load_json(KILLS_CACHE, {})
    jobs = []
    for r in recs:
        for g in ([r["game"]] if r["game"] else list(dets)):
            if g in dets and (rescan or kills_key(r, g, dets[g]) not in cache):
                jobs.append((r, g))
    if limit:
        jobs = jobs[:limit]
    out(f"{len(jobs)} clip scans to run ({len(recs)} clips; cached ones skipped)")
    done, errs, t0 = 0, 0, time.time()

    def work(job):
        r, g = job
        if CANCEL.is_set():
            return r, g, None, "cancelled"
        try:
            return r, g, scan_clip(r["path"], r, dets[g], cfg), None
        except Exception as ex:
            return r, g, None, f"{type(ex).__name__}: {ex}"
    with ThreadPoolExecutor(max_workers=3) as ex:
        for r, g, res, err in ex.map(work, jobs):
            done += 1
            progress(done / max(1, len(jobs)), f"scanning kills {done}/{len(jobs)}")
            name = Path(r["path"]).name
            if err == "cancelled":
                continue
            if err:
                errs += 1
                res = {"kills": [], "error": err}
                out(f"[{done}/{len(jobs)}] {g:8} ERROR {name}: {err}")
            else:
                ks = " ".join(ts(k["t"]) + ("*" if k.get("hs") else "") for k in res["kills"]) or "-"
                out(f"[{done}/{len(jobs)}] {g:8} {len(res['kills'])} kills  {ks}   ({name}, {res['secs']}s)")
            cache[kills_key(r, g, dets[g])] = res
            if done % 5 == 0:
                save_json(KILLS_CACHE, cache)
    save_json(KILLS_CACHE, cache)
    out(f"scan finished: {done} in {time.time() - t0:.0f}s, errors {errs}")
    return done


def cmd_scan(args):
    run_scan(load_config(), [args.game] if args.game else None, None, args.limit, args.rescan)


def game_pool(cfg, game):
    """[{rec, kills}] for one game only (folder tag or HUD fallback); excluded files removed."""
    dets = load_dets()
    if game not in dets:
        raise RuntimeError(f"{game} is not calibrated")
    cache = load_json(KILLS_CACHE, {})
    exc = []
    try:
        exc = [l.strip().lower() for l in (DATA / "exclude.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    except OSError:
        pass
    pool = []
    for r in scan_clips(cfg):
        if r.get("error") or not r.get("w") or clip_game(r, dets, cache) != game:
            continue
        if any(x in r["path"].lower() for x in exc):
            continue
        e = cache.get(kills_key(r, game, dets[game]))
        if e and e.get("kills"):
            pool.append({"rec": r, "kills": e["kills"]})
    return pool


def grab_kill_crop(rec, det, cfg, k, scale):
    import cv2
    import numpy as np
    vf = region_filter(rec, det, cfg)
    r = run(["ffmpeg", "-v", "error", "-ss", f"{k['t'] + 0.3:.3f}", "-i", rec["path"], "-frames:v", "1", "-vf", vf,
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], timeout=60)
    n = det.dw * det.dh * 3
    if len(r.stdout) < n:
        return None
    fr = np.frombuffer(r.stdout[:n], np.uint8).reshape(det.dh, det.dw, 3).copy()
    for d in det.detect(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), fr, scale[0], scale[1]):
        cv2.rectangle(fr, (d["x"], d["y"]), (d["x"] + d["w"], d["y"] + d["h"]), (0, 255, 0), 2)
    cv2.putText(fr, f"{Path(rec['path']).name[-24:]} t={ts(k['t'])} n={k['score']} hl={k['hl']}" + (" HS" if k.get("hs") else ""),
                (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    return fr


def cmd_verify(args):
    import cv2
    import numpy as np
    cfg = load_config()
    det = load_dets(args.game).get(args.game)
    if not det:
        raise SystemExit("not calibrated")
    cache = load_json(KILLS_CACHE, {})
    items = [(r, cache[kills_key(r, args.game, det)]) for r in scan_clips(cfg)
             if not r.get("error") and r.get("w") and kills_key(r, args.game, det) in cache
             and cache[kills_key(r, args.game, det)].get("kills")]
    if not items:
        raise SystemExit("no cached kills yet: run scan first")
    tiles = []
    for rec, v in items[::max(1, len(items) // 6)][:6]:
        fr = grab_kill_crop(rec, det, cfg, v["kills"][0], v["scale"])
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
            times = [max(0.0, k["t"] - 0.1) for k in g]      # the row appears just after the kill
            evs.append({"rec": item["rec"], "path": item["rec"]["path"], "times": times, "n": len(g),
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
LEAD_LO, LEAD_HI, TAIL_S, SLOW_OUT, MINB = 1.5, 2.5, 1.0, 0.4, 4
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
    """One take: lead-in of whole beats, kills, ~1 s tail; ends on a beat. Returns None if the clip can't supply it."""
    lead_t = float(bt[kb] - bt[c])
    if lead_t < 0.9:
        return None
    span = ev["last"] - ev["first"]
    D = float(bt[end] - bt[c])
    post = D - lead_t - span
    if post < 0.45:
        return None
    r = 1.0
    if ramp > 1.0:
        r = min(ramp, ev["first"] / lead_t)
        r = r if r >= 1.15 else 1.0
    if ev["first"] - lead_t * r < -1e-6:
        return None
    sl = bool(slow) and post >= SLOW_OUT + 0.45
    src_end = ev["first"] + (D - lead_t) - (0.2 if sl else 0.0)
    if src_end > ev["rec"]["dur"] - 0.08:
        return None
    segs = []
    if lead_t * r > 0.03:
        segs.append((ev["first"] - lead_t * r, ev["first"], r))
    if sl:
        if span > 0.04:
            segs.append((ev["first"], ev["last"], 1.0))
        segs.append((ev["last"], ev["last"] + 0.2, 0.5))
        segs.append((ev["last"] + 0.2, src_end, 1.0))
    else:
        segs.append((ev["first"], src_end, 1.0))
    return {"ev": ev, "c": c, "kb": kb, "end": end, "lead_t": lead_t, "dur": D, "segs": segs, "ramp": r, "slow": sl}


def place(ev, bt, down, c=None, kb=None, end=None, ramp=1.0, slow=False):
    nb = len(bt) - 1
    pairs = []
    if kb is not None:
        pairs = [(kb - k, kb) for k in range(1, kb + 1) if LEAD_LO <= bt[kb] - bt[kb - k] <= LEAD_HI]
    else:
        for k2 in range(c + 1, nb):
            lt = bt[k2] - bt[c]
            if lt > LEAD_HI:
                break
            if lt >= LEAD_LO:
                pairs.append((c, k2))
    pairs.sort(key=lambda p: (p[1] not in down, abs((bt[p[1]] - bt[p[0]]) - 2.0)))
    span = ev["last"] - ev["first"]
    for cc, kk in pairs:
        lead = bt[kk] - bt[cc]
        if end is not None:
            ends = [end]
        else:
            j0 = next((j for j in range(kk + 1, nb + 1) if bt[j] - bt[cc] >= lead + span + TAIL_S), nb)
            ends = [j for j in range(j0, kk, -1) if bt[j] - bt[cc] >= lead + span + 0.5]
        for j in ends:
            g = geom(ev, bt, cc, kk, j, ramp, slow)
            if g:
                return g
    return None


def plan_montage(cfg, game, events, song, an, win, seed, style, target_s, hist_c, notes):
    import numpy as np
    rng = random.Random(seed)
    avoid = hist_c[-1].get("recipe") if hist_c else None
    rname, rp = pick_recipe(rng, style, avoid)
    s, e = win["s"], win["e"]
    bt = np.array(an["beats"][s:e + 1]) - an["beats"][s]
    nb = len(bt) - 1
    down = {i - s for i in an["down"] if s <= i <= e}
    en, lv = an["energy"][s:e + 1], an["level"][s:e + 1]
    drop = an["drop"] - s if an["drop"] is not None and s + 10 <= an["drop"] <= e - 8 else int(0.6 * nb)
    dcand = [i for i in down if 10 <= i <= nb - 8] or list(down)
    drop = min(dcand, key=lambda i: abs(i - drop))
    heads = {h.get("headline") for h in hist_c[-4:]}
    lastclips = set(hist_c[-1].get("clips", [])) if hist_c else set()
    pool = [ev for ev in events if ev["path"] not in lastclips]
    if len(pool) < 12:
        pool = list(events)
    head_cands = [ev for ev in pool if ev["path"] not in heads] or pool

    def rank(used, lvl, prev):
        res = []
        for ev in pool:
            if id(ev) in used:
                continue
            n = ev["n"]
            pref = {0: 1.0 if n <= 2 else 0.35, 1: 1.0 if n in (2, 3) else 0.55, 2: 1.0 if n >= 3 else 0.5}[lvl]
            eff = ev["score"] * pref * rng.uniform(0.85, 1.15) * (0.6 if ev["path"] == prev else 1.0)
            res.append((eff, ev))
        res.sort(key=lambda x: -x[0])
        return [ev for _, ev in res]

    def fill(c, limit, takes, used, quota):
        for _ in range(120):
            if c >= limit:
                return c
            if limit - c < MINB:                                   # too short for a take: lengthen the previous one
                if takes:
                    p = takes[-1]
                    for sl in (p["slow"], False):
                        g = geom(p["ev"], bt, p["c"], p["kb"], limit, p["ramp"], sl)
                        if g:
                            takes[-1] = g
                            return limit
                return c
            lvl = lv[min(c, nb)]
            placed = None
            for ev in rank(used, lvl, takes[-1]["ev"]["path"] if takes else None)[:12]:
                ramp = rng.uniform(1.4, 1.9) if rng.random() < rp["ramp_p"] else 1.0
                slow_ok = quota[0] < rp["slow_max"] and lvl == 0 and ev["score"] >= 30
                for sl in ((True, False) if slow_ok else (False,)):
                    t = place(ev, bt, down, c=c, ramp=ramp, slow=sl)
                    if t and not (t["end"] <= limit - MINB or t["end"] == limit):
                        t = place(ev, bt, down, c=c, end=limit, ramp=ramp, slow=sl)
                    if t:
                        placed = t
                        break
                if placed:
                    break
            if not placed:
                return c
            if placed["slow"]:
                quota[0] += 1
            takes.append(placed)
            used.add(id(placed["ev"]))
            c = placed["end"]
        return c

    result = None
    for attempt in range(12):
        used, takes, quota = set(), [], [0]
        head = None
        for ev in head_cands[:10]:
            t = place(ev, bt, down, kb=drop)
            if t:
                head = t
                break
        if head is None:
            notes.append("no clip could be placed on the drop; plain fill")
            c = fill(0, nb, takes, used, quota)
            result = (takes, None, 0.0)
            break
        used.add(id(head["ev"]))
        c = fill(0, head["c"], takes, used, quota)
        if c == head["c"]:
            takes.append(head)
            fill(head["end"], nb, takes, used, quota)
            result = (takes, head, 0.0)
            break
    if result is None:                                           # last resort: start the montage at the headline
        notes.append("could not fill the build-up exactly; montage starts at the headline lead-in")
        used, takes, quota = set(), [head], [0]
        used.add(id(head["ev"]))
        fill(head["end"], nb, takes, used, quota)
        result = (takes, head, float(bt[head["c"]]))
    takes, head, off = result
    if not takes:
        raise RuntimeError("could not build any take from these clips")
    out_takes = []
    for t in takes:
        ev, kb = t["ev"], t["kb"]
        role = "headline" if t is head else ("drop" if lv[kb] == 2 else "build" if lv[kb] == 1 else "calm")
        strong = kb in down or en[kb] >= 0.6
        pulses = []
        if role == "headline" or (strong and rng.random() < rp["zoom_p"]):
            pulses.append(t["lead_t"])
        if rng.random() < rp["zoom_p"] * 0.6:
            for i in range(kb + 1, t["end"]):
                if i in down and en[i] >= 0.55:
                    pulses.append(float(bt[i] - bt[t["c"]]))
                    break
        out_takes.append({"path": ev["path"], "rect": content_rect(ev["rec"], cfg), "audio": ev["rec"].get("audio", True),
                          "segs": [[round(a, 3), round(b, 3), round(sp, 3)] for a, b, sp in t["segs"]],
                          "out_start": round(float(bt[t["c"]]) - off, 3), "dur": round(t["dur"], 3), "role": role,
                          "pulses": [round(p, 3) for p in pulses], "amp": round(rp["zoom_amp"], 3),
                          "flash": round(t["lead_t"], 3) if role == "headline" and rp["flash"] else None,
                          "wh": [ev["rec"]["w"], ev["rec"]["h"]], "beat0": t["c"], "beat_kill": kb, "kill_down": kb in down,
                          "kills": [round(x, 2) for x in ev["times"]], "n": ev["n"], "score": round(ev["score"], 1),
                          "hs": ev["hs"], "ramp": round(t["ramp"], 2), "slow": t["slow"], "level": int(lv[kb])})
    total = out_takes[-1]["out_start"] + out_takes[-1]["dur"]
    if total < 60:
        notes.append(f"montage is {total:.0f}s (<60 s): not enough usable material for a longer one")
    ss = an["beats"][s] + off
    return {"game": game, "seed": seed, "recipe": rname, "params": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in rp.items()},
            "song": {"path": song["path"], "artist": song["artist"], "title": song["title"], "bpm": an["bpm"],
                     "start_t": round(ss, 3), "drop_beat": drop - 0, "drop_t": round(float(bt[drop]) - off, 2)},
            "takes": out_takes, "duration": round(total, 3), "notes": notes,
            "headline": head["ev"]["path"] if head else out_takes[0]["path"]}


def fmt_plan(plan, events, score_info, runners, unmatched, csvname):
    L = []
    sg = plan["song"]
    L.append(f"GAME     {plan['game']}      seed {plan['seed']}      style recipe: {plan['recipe']} {plan['params']}")
    L.append(f"SONG     {sg['artist']} - {sg['title']}   [{Path(sg['path']).name}]   BPM {sg['bpm']}")
    L.append(f"WINDOW   starts {ts(sg['start_t'])} in the song, montage {plan['duration']:.1f}s, drop at {sg['drop_t']:.1f}s")
    if score_info:
        fp = score_info["fit_parts"]
        L.append(f"SONG SCORE total {score_info['total']} = recency {score_info['recency']} (added {score_info['days']} days ago)"
                 f" + fit {score_info['fit']} (steady {fp['steady']}, drop {fp['drop']}, bpm {fp['bpm']}) - used-penalty {score_info['penalty']}")
    for s2, sc in runners:
        L.append(f"   runner-up: {s2['artist']} - {s2['title']}  total {sc['total']} (recency {sc['recency']}, fit {sc['fit']}, penalty {sc['penalty']})")
    for n in plan["notes"]:
        L.append(f"NOTE     {n}")
    L.append("\nRANKED KILL EVENTS (top 20)")
    for i, ev in enumerate(events[:20], 1):
        L.append(f"  {i:2}. score {ev['score']:5.1f}  {ev['n']}k{' HS' * (ev['hs'] > 0)}{' flick' * bool(ev['flick'])}  "
                 f"{Path(ev['path']).name} @ {', '.join(ts(t) for t in ev['times'])}")
    L.append(f"\nCUT LIST ({len(plan['takes'])} takes)")
    for i, t in enumerate(plan["takes"], 1):
        src = t["segs"][0][0] + 0
        fx = ("slow-mo " if t["slow"] else "") + (f"ramp x{t['ramp']} " if t["ramp"] > 1 else "") + \
             (f"zoom@{','.join(f'{p:.1f}' for p in t['pulses'])} " if t["pulses"] else "") + ("FLASH" if t["flash"] is not None else "")
        L.append(f"  {i:2}. {t['out_start']:6.1f}s +{t['dur']:4.1f}s beats {t['beat0']}->{t['beat0'] + 0}  kill on beat {t['beat_kill']}"
                 f"{' (downbeat)' if t['kill_down'] else ''}  [{t['role']}] {t['n']}k  {Path(t['path']).name} @ "
                 f"{', '.join(ts(k) for k in t['kills'])}  {fx}")
    L.append(f"\nPLAYLIST tracks with no MP3 yet: {len(unmatched)}" + (f" (CSV {csvname})" if csvname else ""))
    for r in unmatched[:15]:
        L.append(f"   {r['artist']} - {r['title']}")
    return "\n".join(L)


# ======================================================================= RENDER
def ff_has(kind, name):
    r = run(["ffmpeg", "-hide_banner", f"-{kind}"]).stdout.decode(errors="replace")
    return name in r


def amix_has_normalize():
    return "normalize" in run(["ffmpeg", "-hide_banner", "-h", "filter=amix"]).stdout.decode(errors="replace")


def slice_plan(plan, length=20.0):
    """Preview slice: ~20 s centred on the drop, cut at take boundaries."""
    takes = plan["takes"]
    t0 = max([t["out_start"] for t in takes if t["out_start"] <= plan["song"]["drop_t"] - 8.0] or [0.0])
    sel = [t for t in takes if t["out_start"] >= t0 - 1e-6 and t["out_start"] < t0 + length]
    nt = [dict(t, out_start=round(t["out_start"] - t0, 3)) for t in sel]
    sg = dict(plan["song"], start_t=plan["song"]["start_t"] + t0)
    dur = nt[-1]["out_start"] + nt[-1]["dur"]
    return dict(plan, takes=nt, song=sg, duration=dur)


def build_filter(plan, cfg, preview):
    inputs, chains, vl, k = [], [], [], 0
    gv = float(cfg.get("game_audio_level", 0.15))
    for t in plan["takes"]:
        off = 0.0
        for a, b, sp in t["segs"]:
            src_len, out_len = b - a, (b - a) / sp
            i = k
            inputs += ["-threads", "2", "-ss", f"{a:.3f}", "-t", f"{src_len + 0.08:.3f}", "-i", t["path"]]
            cx, cy, cw, ch = t["rect"]
            crop = f"crop={cw}:{ch}:{cx}:{cy}," if [cx, cy, cw, ch] != [0, 0, t["wh"][0], t["wh"][1]] else ""
            v = f"[{i}:v:0]{crop}scale=1920:1080:flags=lanczos,setsar=1,setpts=(PTS-STARTPTS)/{sp:.4f},"
            v += "framerate=fps=60:scene=100" if sp < 1 else "fps=60"
            terms = []
            for p in t["pulses"]:
                pf = (p - off) * 60.0
                if -30 < pf < out_len * 60:
                    terms.append(f"between(in-({pf:.1f}),0,27)*exp(-0.15*(in-({pf:.1f})))")
            if terms:
                v += (f",zoompan=z='1+{t['amp']}*({'+'.join(terms)})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                      f":d=1:s=1920x1080:fps=60")
            if t["flash"] is not None and 0 <= t["flash"] - off < out_len:
                f0 = t["flash"] - off
                v += f",drawbox=x=0:y=0:w=iw:h=ih:color=white@0.8:t=fill:enable='between(t,{f0:.3f},{f0 + 0.12:.3f})'"
            v += f",tpad=stop_mode=clone:stop_duration=0.1,trim=duration={out_len:.4f},setpts=PTS-STARTPTS[v{k}]"
            chains.append(v)
            if t["audio"]:
                at = ""
                if sp != 1.0:
                    at = f"atempo={min(2.0, max(0.5, sp)):.4f},"
                chains.append(f"[{i}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,{at}volume={gv:.3f},"
                              f"asetpts=PTS-STARTPTS,apad,atrim=duration={out_len:.4f}[a{k}]")
            else:
                chains.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={out_len:.4f},asetpts=PTS-STARTPTS[a{k}]")
            vl.append(f"[v{k}][a{k}]")
            off += out_len
            k += 1
    D = plan["duration"]
    sidx = k
    inputs += ["-ss", f"{plan['song']['start_t']:.3f}", "-t", f"{D + 0.6:.3f}", "-i", plan["song"]["path"]]
    chains.append("".join(vl) + f"concat=n={k}:v=1:a=1[vc][gc]")
    chains.append(f"[vc]{'scale=1280:720:flags=bicubic,' if preview else ''}fade=t=out:st={max(0, D - 1.5):.3f}:d=1.5,format=yuv420p[vout]")
    chains.append(f"[{sidx}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[sg]")
    mix = "amix=inputs=2:duration=longest:normalize=0" if amix_has_normalize() else "amix=inputs=2:duration=longest,volume=2"
    chains.append(f"[sg][gc]{mix},atrim=duration={D:.3f},afade=t=out:st={max(0, D - 2):.3f}:d=2[aout]")
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


def render_plan(plan, outfile, cfg, maxq=False, preview=False):
    outfile = Path(outfile)
    outfile.parent.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    p = slice_plan(plan) if preview else plan
    inputs, graph = build_filter(p, cfg, preview)
    gp = LOG_DIR / "last_filter.txt"
    gp.write_text(graph, encoding="utf-8")
    D = min(p["duration"], 20.0) if preview else p["duration"]
    nvenc = ff_has("encoders", "h264_nvenc")
    tmp = outfile.with_name(outfile.stem + ".part.mp4")
    for attempt, use_nv in enumerate((nvenc, False) if nvenc else (False,)):
        cmd = (["ffmpeg", "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1"] + inputs +
               ["-filter_complex_script", str(gp), "-map", "[vout]", "-map", "[aout]", "-t", f"{D:.3f}"] +
               enc_args(maxq, preview, use_nv) + [str(tmp)])
        elog = LOG_DIR / "last_render_stderr.txt"
        with open(elog, "w", encoding="utf-8") as ef:
            pr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=ef, text=True)
            PROCS.append(pr)
            for line in pr.stdout:
                if line.startswith("out_time_us="):
                    try:
                        progress(min(1.0, int(line.split("=")[1]) / 1e6 / D), f"rendering {int(100 * min(1.0, int(line.split('=')[1]) / 1e6 / D))}%")
                    except ValueError:
                        pass
                if CANCEL.is_set():
                    pr.kill()
            pr.wait()
            if pr in PROCS:
                PROCS.remove(pr)
        if CANCEL.is_set():
            raise RuntimeError("cancelled")
        if pr.returncode == 0 and tmp.exists():
            os.replace(tmp, outfile)
            out(f"rendered {outfile}")
            return outfile
        out(f"ffmpeg failed ({'NVENC' if use_nv else 'x264'}): " + elog.read_text(encoding="utf-8", errors="replace")[-600:])
        if use_nv:
            out("retrying with libx264")
    raise RuntimeError(f"render failed - see {elog} and {gp}")


# ======================================================================= ORCHESTRATION
GAME_DIR = {"valorant": "Valorant", "cs2": "CS2"}


def week_tag(now):
    y, w, _ = now.isocalendar()
    return f"{y}-W{w:02d}"


def weekly_existing(cfg, game, now=None):
    d = Path(cfg["output_root"]) / GAME_DIR[game]
    pat = f"{GAME_DIR[game]}_{week_tag(now or datetime.datetime.now())}_*.mp4"
    return sorted(d.glob(pat)) if d.is_dir() else []


def make_plan(cfg, game, paths=None, song_path=None, target=None, style=None, seed=None):
    cfg = autodetect_dirs(cfg)
    run_scan(cfg, [game], paths)                       # finds kills in anything not scanned yet (cached forever after)
    pool = game_pool(cfg, game)
    if paths:
        ps = set(paths)
        pool = [x for x in pool if x["rec"]["path"] in ps]
    if not pool:
        raise RuntimeError(f"no {game} kills found in the chosen clips (is {game} calibrated? Troubleshoot > Calibrate)")
    seed = int(seed) if seed else random.randrange(1, 10 ** 6)
    events = build_events(pool, game, cfg, random.Random(seed))
    songs, unmatched, csvname = song_pool(cfg)
    song, an, sinfo, runners = pick_song(cfg, game, songs, forced=song_path)
    win = pick_window(an, target or cfg.get("length_s", 85))
    notes = [win["note"]] if win.get("note") else []
    plan = plan_montage(cfg, game, events, song, an, win, seed, style, target, hist_list(USED_CLIPS, game), notes)
    plan["song_score"] = sinfo
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
    """mode: dry | preview | render. weekly=True is Auto (skips if this week's montage exists)."""
    cfg = load_config()
    if maxq is None:
        maxq = cfg.get("quality") == "max"
    now = datetime.datetime.now()
    if weekly and mode == "render" and not force:
        ex = weekly_existing(cfg, game, now)
        if ex:
            out(f"{game}: this week's montage already exists ({ex[0].name}). Use Force to make another.")
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
    return outfile


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


class App:
    def __init__(self, start_tab=0):
        self.root = tk.Tk()
        self.root.title("Montage builder (Valorant / CS2)")
        self.root.geometry("1180x860")
        self.q, self.busy, self.buttons, self._imgs, self.pending = queue.Queue(), False, [], [], []
        LOG_SINK[0] = lambda m: self.q.put(("log", m))
        PROGRESS[0] = lambda f, t: self.q.put(("prog", (f, t)))
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=6, pady=6)
        self.tabs = {n: ttk.Frame(self.nb) for n in ("Auto", "Manual", "Troubleshoot", "Settings")}
        for n, f in self.tabs.items():
            self.nb.add(f, text=n)
        bot = ttk.Frame(self.root)
        bot.pack(fill="x", padx=6)
        self.pbar = ttk.Progressbar(bot, maximum=1.0)
        self.pbar.pack(side="left", fill="x", expand=True)
        self.plabel = tk.StringVar(value="idle")
        ttk.Label(bot, textvariable=self.plabel, width=34).pack(side="left", padx=6)
        ttk.Button(bot, text="Cancel", command=stop_all).pack(side="left")
        self.log = tk.Text(self.root, height=14, wrap="word", bg="#111", fg="#ddd")
        self.log.pack(fill="both", padx=6, pady=6)
        self.cfg = load_config()
        self.build_auto()
        self.build_manual()
        self.build_trouble()
        self.build_settings()
        self.nb.select(start_tab)
        self.root.after(100, self.poll)
        self.root.after(400, self.startup)

    # ---- plumbing
    def btn(self, parent, text, cmd, **kw):
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

    def run_task(self, name, fn, *a):
        if self.busy:
            self.pending.append((name, fn, a))
            out(f"queued: {name}")
            return
        self.busy = True
        CANCEL.clear()
        for b in self.buttons:
            b.state(["disabled"])

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
            while True:
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
                    for b in self.buttons:
                        b.state(["!disabled"])
                    self.refresh_auto()
                    if self.pending:
                        n, fn, a = self.pending.pop(0)
                        self.run_task(n, fn, *a)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def startup(self):
        miss = missing_packages()
        if miss and messagebox.askyesno("Missing packages", "Install now (user scope, no admin)?\n\n" + ", ".join(miss)):
            def inst():
                out("installing: " + " ".join(miss))
                r = subprocess.run([sys.executable, "-m", "pip", "install", "--user"] + miss, capture_output=True, text=True)
                out((r.stdout + r.stderr)[-1500:])
                out("done - close and reopen this program.")
            self.run_task("pip", inst)
        elif not shutil.which("ffmpeg"):
            out("ffmpeg not found. Open Troubleshoot > Selfcheck for how to get it without admin.")
        cfg = autodetect_dirs(load_config())
        self.cfg = cfg

    # ---- Auto tab
    def build_auto(self):
        f = self.tabs["Auto"]
        ttk.Label(f, text="One montage per game per week, from all clips in the clip folder. Nothing to select.",
                  font=("Segoe UI", 10)).pack(anchor="w", padx=8, pady=6)
        self.auto_status = {}
        for g in GAMES:
            lf = ttk.LabelFrame(f, text=GAME_DIR[g])
            lf.pack(fill="x", padx=8, pady=6)
            sv = tk.StringVar()
            self.auto_status[g] = sv
            ttk.Label(lf, textvariable=sv, justify="left").pack(anchor="w", padx=8, pady=4)
            row = ttk.Frame(lf)
            row.pack(anchor="w", padx=8, pady=4)
            for text, kw in (("Run", dict(weekly=True)), ("Force new", dict(weekly=True, force=True)),
                             ("Dry plan", dict(mode="dry")), ("Preview 720p/20s", dict(mode="preview"))):
                self.btn(row, text, lambda g=g, kw=kw, text=text: self.run_task(f"{g} {text}", lambda: run_job(g, **kw))).pack(side="left", padx=4)
        self.refresh_auto()

    def refresh_auto(self):
        cfg = load_config()
        cache = load_json(CLIPS_CACHE, {})
        for g in GAMES:
            n = sum(1 for v in cache.values() if tag_game(v["path"], cfg)[0] == g)
            unk = sum(1 for v in cache.values() if tag_game(v["path"], cfg)[0] is None)
            ex = weekly_existing(cfg, g)
            last = hist_list(USED_SONGS, g)
            self.auto_status[g].set(
                f"Calibrated: {'yes' if (DATA / f'detect_{g}.json').exists() else 'NO - Troubleshoot > Calibrate'}    "
                f"Clips known: {n} tagged (+{unk} untagged, HUD-detected)\n"
                f"This week ({week_tag(datetime.datetime.now())}): {ex[-1].name if ex else 'no montage yet'}\n"
                f"Last song used: {Path(last[-1]['path']).stem if last else '-'}   (song is picked at run time: newest week first)")

    # ---- Manual tab
    def build_manual(self):
        f = self.tabs["Manual"]
        top = ttk.Frame(f)
        top.pack(fill="x", padx=6, pady=4)
        self.m_game = tk.StringVar(value="valorant")
        for g in GAMES:
            ttk.Radiobutton(top, text=GAME_DIR[g], variable=self.m_game, value=g, command=lambda: self.run_task("clips", self.load_clips)).pack(side="left")
        self.btn(top, "Reload clips", lambda: self.run_task("clips", self.load_clips)).pack(side="left", padx=8)
        self.btn(top, "Tag selected as Valorant", lambda: self.tag_sel("valorant")).pack(side="left")
        self.btn(top, "Tag selected as CS2", lambda: self.tag_sel("cs2")).pack(side="left", padx=4)
        self.btn(top, "Exclude selected", self.exclude_sel).pack(side="left")
        mid = ttk.Frame(f)
        mid.pack(fill="both", expand=True, padx=6)
        self.ctree = ttk.Treeview(mid, columns=("kills", "best", "folder"), selectmode="extended", height=12)
        for c, w in (("#0", 300), ("kills", 60), ("best", 90), ("folder", 260)):
            self.ctree.column(c, width=w)
        self.ctree.heading("#0", text="clip")
        self.ctree.heading("kills", text="kills")
        self.ctree.heading("best", text="best")
        self.ctree.heading("folder", text="folder")
        self.ctree.pack(side="left", fill="both", expand=True)
        self.stree = ttk.Treeview(mid, columns=("bpm", "added"), selectmode="browse", height=12)
        self.stree.column("#0", width=280)
        self.stree.column("bpm", width=50)
        self.stree.column("added", width=90)
        self.stree.heading("#0", text="song (default: auto pick)")
        self.stree.heading("bpm", text="BPM")
        self.stree.heading("added", text="added")
        self.stree.pack(side="left", fill="both", expand=True, padx=(6, 0))
        ctl = ttk.Frame(f)
        ctl.pack(fill="x", padx=6, pady=6)
        ttk.Label(ctl, text="Length s").pack(side="left")
        self.m_len = tk.IntVar(value=self.cfg.get("length_s", 85))
        ttk.Scale(ctl, from_=60, to=120, variable=self.m_len, length=160).pack(side="left", padx=4)
        ttk.Label(ctl, textvariable=self.m_len, width=4).pack(side="left")
        ttk.Label(ctl, text="Style").pack(side="left", padx=(10, 2))
        self.m_style = tk.StringVar(value="random")
        ttk.Combobox(ctl, textvariable=self.m_style, values=["random"] + list(RECIPES) + ["mix"], width=9, state="readonly").pack(side="left")
        ttk.Label(ctl, text="Seed").pack(side="left", padx=(10, 2))
        self.m_seed = tk.StringVar()
        ttk.Entry(ctl, textvariable=self.m_seed, width=8).pack(side="left")
        self.m_max = tk.BooleanVar(value=self.cfg.get("quality") == "max")
        ttk.Checkbutton(ctl, text="Max quality (x264 CRF 15)", variable=self.m_max).pack(side="left", padx=10)
        for text, mode in (("Dry plan", "dry"), ("Preview", "preview"), ("Render", "render")):
            self.btn(ctl, text, lambda m=mode: self.manual(m)).pack(side="right", padx=3)
        self.run_task("clips", self.load_clips)

    def load_clips(self):
        cfg = load_config()
        if not cfg.get("bar_checked") and missing_packages() == [] and shutil.which("ffmpeg"):
            ensure_bars(cfg)
        recs = [r for r in scan_clips(load_config()) if not r.get("error") and r.get("w")]
        dets, cache, g = load_dets(), load_json(KILLS_CACHE, {}), self.m_game.get()
        rows = []
        for r in recs:
            cg = clip_game(r, dets, cache)
            if cg not in (g, None):
                continue
            e = cache.get(kills_key(r, g, dets[g])) if g in dets else None
            ks = e["kills"] if e else None
            best = ""
            if ks:
                gap, best_n, cur = cfg["gap_s"][g], 1, 1
                for a, b in zip(ks, ks[1:]):
                    cur = cur + 1 if b["t"] - a["t"] <= gap else 1
                    best_n = max(best_n, cur)
                best = f"{best_n}k"
            rows.append((r["path"], "?" if ks is None else len(ks), best if ks else ("not scanned" if ks is None else "-")))
        songs, _, _ = song_pool(load_config()) if (load_config().get("mp3_dir")) else ([], [], None)
        sc = load_json(SONG_CACHE, {})

        def fill():
            self.ctree.delete(*self.ctree.get_children())
            for p, k, b in sorted(rows, key=lambda x: x[0].lower()):
                self.ctree.insert("", "end", iid=p, text=Path(p).name, values=(k, b, Path(p).parent.name))
            self.stree.delete(*self.stree.get_children())
            self.stree.insert("", "end", iid="auto", text="(auto pick: this week's best)", values=("", ""))
            for s in sorted(songs, key=lambda s: s["added"] or datetime.datetime(1970, 1, 1), reverse=True):
                try:
                    bpm = sc.get(file_key(s["path"]) + SONG_ALGO, {}).get("bpm", "")
                except OSError:
                    bpm = ""
                self.stree.insert("", "end", iid=s["path"], text=f"{s['artist']} - {s['title']}",
                                  values=(bpm, s["added"].strftime("%Y-%m-%d") if s["added"] else ""))
            self.stree.selection_set("auto")
        self.q.put(("call", fill))

    def tag_sel(self, game):
        cfg = load_config()
        for p in self.ctree.selection():
            cfg.setdefault("game_overrides", {})[p] = game
        save_json(CONFIG_PATH, cfg)
        out(f"tagged {len(self.ctree.selection())} clip(s) as {game}")
        self.run_task("clips", self.load_clips)

    def exclude_sel(self):
        with open(DATA / "exclude.txt", "a", encoding="utf-8") as f:
            for p in self.ctree.selection():
                f.write(p + "\n")
        out(f"excluded {len(self.ctree.selection())} clip(s) (montage_data\\exclude.txt, one path per line)")

    def manual(self, mode):
        paths = list(self.ctree.selection())
        if not paths:
            messagebox.showinfo("Manual", "Select about 10-15 clips first.")
            return
        sel = self.stree.selection()
        song = None if not sel or sel[0] == "auto" else sel[0]
        seed = int(self.m_seed.get()) if self.m_seed.get().strip().isdigit() else None
        style = self.m_style.get()
        self.run_task("manual " + mode, run_job, self.m_game.get(), mode, True, paths, song, int(self.m_len.get()),
                      None if style == "random" else style, seed, self.m_max.get())

    # ---- Troubleshoot tab
    def build_trouble(self):
        f = self.tabs["Troubleshoot"]
        r1 = ttk.LabelFrame(f, text="Setup checks")
        r1.pack(fill="x", padx=8, pady=6)
        self.btn(r1, "Selfcheck (ffmpeg, NVENC, packages)", lambda: self.run_task("selfcheck", cmd_selfcheck, None)).pack(side="left", padx=4, pady=4)
        self.btn(r1, "Calibrate killfeed...", lambda: CalibDialog(self)).pack(side="left", padx=4)
        self.btn(r1, "Open logs", lambda: self.open_path(LOG_DIR)).pack(side="left", padx=4)
        self.btn(r1, "Open output folder", lambda: self.open_path(Path(load_config()["output_root"]))).pack(side="left", padx=4)
        self.btn(r1, "Clear kill cache", self.clear_cache).pack(side="left", padx=4)
        r2 = ttk.LabelFrame(f, text="Black bars (auto-measured once; fixed crop)")
        r2.pack(fill="x", padx=8, pady=6)
        self.bar_var = tk.StringVar()
        ttk.Label(r2, textvariable=self.bar_var).pack(anchor="w", padx=6)
        rr = ttk.Frame(r2)
        rr.pack(anchor="w", padx=6, pady=4)
        self.bar_e = [tk.StringVar() for _ in range(4)]
        for lab, v in zip("x y w h".split(), self.bar_e):
            ttk.Label(rr, text=lab).pack(side="left")
            ttk.Entry(rr, textvariable=v, width=6).pack(side="left", padx=2)
        self.btn(rr, "Apply override (uses selected clip's size)", self.bar_override).pack(side="left", padx=6)
        self.btn(rr, "Re-measure", lambda: self.run_task("bars", lambda: (ensure_bars(load_config(), True), self.q.put(("call", self.refresh_bar))))).pack(side="left")
        self.btn(rr, "No bars", self.bar_off).pack(side="left", padx=4)
        self.btn(rr, "Before/after preview of selected clip", self.bar_preview).pack(side="left", padx=4)
        r3 = ttk.LabelFrame(f, text="Clips")
        r3.pack(fill="both", expand=True, padx=8, pady=6)
        top = ttk.Frame(r3)
        top.pack(fill="x")
        self.t_game = tk.StringVar(value="valorant")
        ttk.Combobox(top, textvariable=self.t_game, values=list(GAMES), width=10, state="readonly").pack(side="left", padx=4)
        self.btn(top, "Load clips", lambda: self.run_task("tclips", self.load_tclips)).pack(side="left")
        self.btn(top, "Kill timestamps + killfeed crop", self.show_kills).pack(side="left", padx=6)
        self.btn(top, "Rescan this clip", self.rescan_clip).pack(side="left")
        self.ttree = ttk.Treeview(r3, selectmode="browse", height=8)
        self.ttree.pack(fill="both", expand=True, pady=4)
        self.refresh_bar()

    def refresh_bar(self):
        b = load_config().get("bar")
        self.bar_var.set(f"Stored crop: source {b['src'][0]}x{b['src'][1]} -> x,y,w,h {b['rect']}" if b else "Stored crop: none (clips used as full frame)")
        if b:
            for v, x in zip(self.bar_e, b["rect"]):
                v.set(str(x))

    def load_tclips(self):
        recs = [r for r in scan_clips(load_config()) if not r.get("error") and r.get("w")]
        items = [(r["path"], Path(r["path"]).name) for r in recs]

        def fill():
            self.ttree.delete(*self.ttree.get_children())
            for p, n in sorted(items, key=lambda x: x[1]):
                self.ttree.insert("", "end", iid=p, text=n)
        self.q.put(("call", fill))

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
        e = load_json(KILLS_CACHE, {}).get(kills_key(rec, g, det))
        if not e:
            out("not scanned yet: press Rescan this clip")
            return
        out(f"{Path(p).name}: {len(e['kills'])} kills: " + ", ".join(ts(k["t"]) + ("*HS" if k.get("hs") else "") for k in e["kills"]) +
            f"   (scale {e['scale']}, best match {e.get('disc_best')})")
        if e["kills"]:
            fr = grab_kill_crop(rec, det, cfg, e["kills"][0], e["scale"])
            if fr is not None:
                w = tk.Toplevel(self.root)
                w.title("Killfeed crop at first kill (green = detected row)")
                ph, _ = to_photo(fr, 900, 700)
                self._imgs.append(ph)
                ttk.Label(w, image=ph).pack()

    def rescan_clip(self):
        p = self.sel_clip()
        if not p:
            return

        def job():
            cache = load_json(KILLS_CACHE, {})
            fk = file_key(p)
            save_json(KILLS_CACHE, {k: v for k, v in cache.items() if not k.startswith(fk + "|")})
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
        out(f"bar override saved: {cfg['bar']} (cached clip probes refresh on next load; kills rescan automatically for bar clips)")
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
        b = cv2.resize(before, (640, 360))
        a = cv2.resize(after, (640, 360))
        w = tk.Toplevel(self.root)
        w.title(f"before (left) / after (right)  bars applied: {rec.get('bars')}")
        ph, _ = to_photo(np.hstack([b, a]), 1300, 400)
        self._imgs.append(ph)
        ttk.Label(w, image=ph).pack()

    def open_path(self, p):
        p = Path(p)
        p.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(p))
        else:
            out(f"folder: {p}")

    def clear_cache(self):
        if messagebox.askyesno("Clear kill cache", "Delete kills_cache.json? Every clip will be scanned again (slow)."):
            for pth in (KILLS_CACHE, FLICK_CACHE):
                try:
                    pth.unlink()
                except OSError:
                    pass
            out("kill cache cleared")

    # ---- Settings tab
    def build_settings(self):
        f = self.tabs["Settings"]
        self.sv = {}
        rows = (("clip_root", "Clips folder (recursive)"), ("mp3_dir", "MP3 folder"),
                ("playlist_dir", "Exportify CSV folder"), ("output_root", "Output folder"))
        for i, (k, lab) in enumerate(rows):
            ttk.Label(f, text=lab).grid(row=i, column=0, sticky="w", padx=8, pady=6)
            v = tk.StringVar(value=self.cfg.get(k, ""))
            self.sv[k] = v
            ttk.Entry(f, textvariable=v, width=70).grid(row=i, column=1, padx=4)
            ttk.Button(f, text="Browse", command=lambda v=v: v.set(filedialog.askdirectory(initialdir=v.get() or None) or v.get())).grid(row=i, column=2)
        n = len(rows)
        self.set_len = tk.IntVar(value=self.cfg.get("length_s", 85))
        self.set_aud = tk.IntVar(value=int(100 * self.cfg.get("game_audio_level", 0.15)))
        self.set_q = tk.StringVar(value=self.cfg.get("quality", "nvenc"))
        self.set_wk = tk.IntVar(value=self.cfg.get("week_days", 7))
        for i, (lab, var, lo, hi) in enumerate((("Default length (s)", self.set_len, 60, 120), ("Game audio level (%)", self.set_aud, 0, 100),
                                                  ("'This week' = last N days", self.set_wk, 1, 30))):
            ttk.Label(f, text=lab).grid(row=n + i, column=0, sticky="w", padx=8, pady=6)
            ttk.Scale(f, from_=lo, to=hi, variable=var, length=300).grid(row=n + i, column=1, sticky="w", padx=4)
            ttk.Label(f, textvariable=var).grid(row=n + i, column=2)
        ttk.Label(f, text="Quality").grid(row=n + 3, column=0, sticky="w", padx=8, pady=6)
        qf = ttk.Frame(f)
        qf.grid(row=n + 3, column=1, sticky="w")
        ttk.Radiobutton(qf, text="NVENC p7 hq cq18 (fast)", variable=self.set_q, value="nvenc").pack(side="left")
        ttk.Radiobutton(qf, text="Max quality x264 CRF15 slow", variable=self.set_q, value="max").pack(side="left", padx=10)
        ttk.Button(f, text="Save settings", command=self.safe(self.save_settings)).grid(row=n + 4, column=1, sticky="w", pady=14)

    def save_settings(self):
        cfg = load_config()
        for k, v in self.sv.items():
            cfg[k] = v.get().strip()
        cfg["length_s"], cfg["game_audio_level"] = int(self.set_len.get()), round(self.set_aud.get() / 100, 2)
        cfg["quality"], cfg["week_days"] = self.set_q.get(), int(self.set_wk.get())
        save_json(CONFIG_PATH, cfg)
        self.cfg = cfg
        out("settings saved")


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
