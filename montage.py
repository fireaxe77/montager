r"""
montage.py - Valorant / CS2 multikill montage builder (personal use, local only).

COMMANDS (run from anywhere):
  python "C:\Users\fireaxe\Desktop\CLAUDECODE\montage.py" setup        # one-time: asks for CSV folder + MP3 folder
  python "C:\Users\fireaxe\Desktop\CLAUDECODE\montage.py" selfcheck    # ffmpeg / ffprobe / NVENC / pip packages
  python "C:\Users\fireaxe\Desktop\CLAUDECODE\montage.py" inventory    # read-only listing: clips, bars, audio, playlist match
  python "C:\Users\fireaxe\Desktop\CLAUDECODE\montage.py" inventory --list     # also list every clip
  python "C:\Users\fireaxe\Desktop\CLAUDECODE\montage.py" inventory --rescan   # ignore caches
  python "C:\Users\fireaxe\Desktop\CLAUDECODE\montage.py" tag <file-or-folder> <valorant|cs2|auto>   # manual game override
(Later stages add: verify, scan, plan, render, auto, pick.)

All data lives in montage_data\ next to this script. Source files are never modified.
"""
import argparse
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
CLIPS_CACHE = DATA / "clips_cache.json"
AUDIO_CACHE = DATA / "audio_cache.json"
SONGS_TO_GET = DATA / "songs_to_get.txt"

VIDEO_EXT = {".mov", ".mp4", ".mkv"}
AUDIO_EXT = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".opus"}
MIN_VIDEO = 5 * 1024 * 1024
MIN_AUDIO = 1 * 1024 * 1024
SKIP_DIR_NAMES = {"windows", "program files", "program files (x86)", "appdata", "programdata",
                  "$recycle.bin", "system volume information", "montage_data", "node_modules", ".git"}
BAR_THRESHOLD = 12        # pixel brightness (0-255) counted as content
BAR_FRAMES = 24
GAMES = ("valorant", "cs2")

DEFAULT_CONFIG = {
    "playlist_dir": str(DATA / "playlist"),
    "mp3_dir": "",
    "output_root": r"E:\Movies\Montages",
    "scan_roots": [],               # empty = all local drives
    "week_days": 7,
    "window_min_s": 45,
    "window_max_s": 90,
    "game_audio_level": 0.15,
    "gap_s": {"valorant": 6.0, "cs2": 5.0},
    "game_overrides": {},           # path prefix -> game
    "match_threshold": 85,
}


# ----------------------------------------------------------------- utilities
def out(*a):
    print(*a, flush=True)


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
def local_roots(cfg):
    if cfg.get("scan_roots"):
        return [r for r in cfg["scan_roots"] if os.path.isdir(r)]
    if os.name != "nt":
        return ["/"]
    import ctypes
    roots = []
    for i in range(26):
        d = f"{chr(65 + i)}:\\"
        if os.path.exists(d) and ctypes.windll.kernel32.GetDriveTypeW(d) in (2, 3):  # removable / fixed
            roots.append(d)
    return roots


def norm(p):
    return os.path.normcase(os.path.normpath(p))


def is_spotify_cache(path_l):
    return "spotify" in path_l and any(x in path_l for x in ("storage", "persistentcache", "\\data", "/data"))


def walk_files(roots, exts, min_size, cfg, audio=False):
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
                            if audio and is_spotify_cache(norm(e.path)):
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
    r = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name,width,height,avg_frame_rate,pix_fmt:format=duration",
             "-of", "json", path])
    j = json.loads(r.stdout or b"{}")
    s = (j.get("streams") or [{}])[0]
    n, _, d = (s.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(n) / float(d) if d and float(d) else 0.0
    return {"codec": s.get("codec_name"), "w": s.get("width"), "h": s.get("height"),
            "fps": round(fps, 2), "pix_fmt": s.get("pix_fmt"),
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


def analyse_clip(path, cache, rescan):
    key = file_key(path)
    if not rescan and key in cache:
        return path, cache[key]
    rec = {"path": path}
    try:
        info = probe_video(path)
        rec.update(info)
        rect, note = detect_rect(path, info)
        rec["rect"], rec["rect_note"] = rect, note
        if rect:
            w, h = info["w"], info["h"]
            rec["bars"] = any(abs(a) > 8 for a in (rect[0], rect[1], w - rect[0] - rect[2], h - rect[1] - rect[3]))
        else:
            rec["bars"] = False
    except Exception as ex:
        rec["error"] = f"{type(ex).__name__}: {ex}"
    cache[key] = rec
    return path, rec


def scan_clips(cfg, rescan=False):
    roots = local_roots(cfg)
    out(f"Scanning for clips on: {', '.join(roots)} ...")
    paths = list(walk_files(roots, VIDEO_EXT, MIN_VIDEO, cfg))
    out(f"  {len(paths)} video files found; analysing (cached after first time)")
    cache = {} if rescan else load_json(CLIPS_CACHE, {})
    recs = []
    todo = [p for p in paths if rescan or file_key(p) not in cache]
    if todo:
        out(f"  {len(todo)} new/changed clips to probe + bar-detect")
    with ThreadPoolExecutor(max_workers=6) as ex:
        for i, (p, rec) in enumerate(ex.map(lambda p: analyse_clip(p, cache, rescan), paths), 1):
            recs.append(rec)
            if todo and i % 25 == 0:
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
    roots = local_roots(cfg)
    mp3 = cfg.get("mp3_dir")
    paths = []
    if mp3 and os.path.isdir(mp3):
        paths += list(walk_files([mp3], AUDIO_EXT, 0, cfg, audio=True))
    out(f"Scanning for audio on: {', '.join(roots)} ...")
    paths += [p for p in walk_files(roots, AUDIO_EXT, MIN_AUDIO, cfg, audio=True)]
    paths = list(dict.fromkeys(paths))
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
    "uri": ["track uri", "uri", "spotify uri", "track id"],
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


def write_songs_to_get(unmatched):
    from urllib.parse import quote_plus
    lines = ["# Playlist tracks with no local audio file. Put the file in your MP3 folder; the next run picks it up.\n"]
    for r in unmatched:
        q = quote_plus(f"{r['artist']} {r['title']}".strip())
        lines.append(f"{r['artist']} - {r['title']}")
        lines.append(f"  https://bandcamp.com/search?q={q}")
        lines.append(f"  https://music.apple.com/search?term={q}")
        lines.append(f"  https://www.amazon.com/s?k={q}\n")
    DATA.mkdir(parents=True, exist_ok=True)
    SONGS_TO_GET.write_text("\n".join(lines), encoding="utf-8")


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
    for sub in ("freemusic",):
        (DATA / sub).mkdir(exist_ok=True)
    save_json(CONFIG_PATH, cfg)
    out(f"Saved {CONFIG_PATH}")
    out("Drop royalty-free fallback tracks in montage_data\\freemusic\\ (optional).")
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
        rej = [r for r in rs if r.get("rect") is None]
        src = {}
        for r in rs:
            src[r["game_src"]] = src.get(r["game_src"], 0) + 1
        out(f"\n[{g.upper()}] {len(rs)} clips, {human(tot)}  (tagged by: {src})")
        out(f"  codecs : {cnt('codec')}")
        out(f"  res    : {', '.join(f'{k}x{v}' for k, v in sorted(res.items()))}")
        out(f"  fps    : {cnt('fps')}")
        out(f"  bar-fix needed: {bars}   rejected (bad content box / probe error): {len(rej)}")
        for r in rej[:10]:
            out(f"     REJECT {r['path']}: {r.get('rect_note') or r.get('error')}")
        if g == "UNKNOWN":
            out("  -> these will use HUD detection in Stage 1, or: montage.py tag <folder> <valorant|cs2>")
    if args.list:
        out("\n== CLIP LIST ==")
        for r in sorted(recs, key=lambda r: r["path"].lower()):
            rect = r.get("rect")
            out(f"  [{r['game'] or '?':8}] {r.get('codec')} {r.get('w')}x{r.get('h')}@{r.get('fps')} "
                f"{r.get('dur', 0):.0f}s rect={rect} {'BARS' if r.get('bars') else ''}  {r['path']}")

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
        write_songs_to_get(unmatched)
        out(f"  wrote {SONGS_TO_GET} ({len(unmatched)} tracks with search links)")
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


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    setup_path()
    ap = argparse.ArgumentParser(prog="montage.py")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("setup").set_defaults(fn=cmd_setup)
    sp.add_parser("selfcheck").set_defaults(fn=cmd_selfcheck)
    i = sp.add_parser("inventory")
    i.add_argument("--list", action="store_true")
    i.add_argument("--rescan", action="store_true")
    i.set_defaults(fn=cmd_inventory)
    t = sp.add_parser("tag")
    t.add_argument("path")
    t.add_argument("game", choices=list(GAMES) + ["auto"])
    t.set_defaults(fn=cmd_tag)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
