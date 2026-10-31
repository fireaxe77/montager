"""V9.5: fetch songs the Exportify CSV lists but the songs folder lacks, from YouTube with yt-dlp.

Pure helpers (pick rules, file name, tags) + thin yt-dlp wrappers. montage.py (App.download_new_songs) does the matching against the
songs folder and the GUI. Nothing here touches detection, planning, effects or rendering.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

DUR_TOL_S = 5.0                          # a result must be within this many seconds of the Spotify length
SEARCH_N = 10                            # results read per search query
BANNED = ("slowed", "sped up", "speed up", "nightcore", "reverb", "8d", "live", "remix", "cover", "instrumental", "karaoke")
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _norm(s):
    s = unicodedata.normalize("NFKC", str(s or "")).casefold()
    return re.sub(r"\s+", " ", s).strip()


def _has_word(text, word):
    return re.search(r"(?<![^\W_])" + re.escape(word).replace(r"\ ", r"[\s_-]+") + r"(?![^\W_])", text) is not None


def banned_words(video_title, spotify_title):
    """Banned words in the video title that the Spotify title does not have too."""
    v, s = _norm(video_title), _norm(spotify_title)
    return [w for w in BANNED if _has_word(v, w) and not _has_word(s, w)]


def channel_kind(channel, artists):
    """'topic' (auto-generated 'Artist - Topic' album audio) | 'artist' (official channel of one of the artists) | 'other'."""
    c = _norm(channel)
    if c.endswith(" - topic"):
        return "topic"
    cn = re.sub(r"[^\w]+", "", c)
    for a in artists:
        an = re.sub(r"[^\w]+", "", _norm(a))
        if an and (cn == an or cn in (an + "official", an + "vevo", an + "music", "official" + an) or cn.startswith(an) and cn.endswith(("official", "vevo", "music"))):
            return "artist"
    return "other"


KIND_RANK = {"topic": 0, "artist": 1, "other": 2}


def judge(cand, title, artists, want_dur):
    """None when the result passes every rule, else the reason it was rejected."""
    d = cand.get("duration")
    if not d:
        return "no length"
    if abs(d - want_dur) > DUR_TOL_S:
        return f"length {fmt_len(d)} vs expected {fmt_len(want_dur)}"
    bad = banned_words(cand.get("title", ""), title)
    if bad:
        return "title has: " + ", ".join(bad)
    return None


def fmt_len(sec):
    sec = int(round(sec or 0))
    return f"{sec // 60}:{sec % 60:02d}"


def pick(cands, title, artists, want_dur):
    """(best passing result or None, nearest-miss description). Order: Topic upload, official channel, anything else; then the closest
    length, then the search order."""
    ok, seen = [], []
    for i, c in enumerate(cands):
        why = judge(c, title, artists, want_dur)
        k = channel_kind(c.get("channel", ""), artists)
        if why is None:
            ok.append((KIND_RANK[k], abs(c["duration"] - want_dur), i, c, k))
        else:
            seen.append((why, c))
    if ok:
        ok.sort(key=lambda x: x[:3])
        best = ok[0]
        return dict(best[3], kind=best[4]), ""
    return None, nearest_miss(seen, want_dur)


def nearest_miss(seen, want_dur):
    """The best candidate that was seen, as text: title, channel, length vs expected length, and why it failed."""
    if not seen:
        return "no results"
    def key(x):
        why, c = x
        return (0 if not why.startswith("length") else 1, abs((c.get("duration") or 0) - want_dur))
    why, c = sorted(seen, key=key)[0]
    return (f"best candidate: \"{c.get('title', '')}\" | {c.get('channel', '')} | {fmt_len(c.get('duration'))} "
            f"(expected {fmt_len(want_dur)}) | rejected: {why}")


_FN_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def song_filename(title, artist):
    """'Title - Artist1, Artist2.mp3': the app's song match splits the name on its LAST ' - ' (title / artists) and drops the characters
    a file name cannot hold on both sides, so the name always matches the CSV row it came from."""
    t = re.sub(r"\s+", " ", _FN_BAD.sub("", title)).strip(" .")
    a = re.sub(r"\s+", " ", _FN_BAD.sub("", artist)).strip(" .")
    t, a = t[:120], a[:80]
    return f"{t} - {a}.mp3" if a else f"{t}.mp3"


# ------------------------------------------------------------------ yt-dlp
def frozen():
    return bool(getattr(sys, "frozen", False))


def _module_ok():
    if frozen():
        return False
    try:
        import yt_dlp  # noqa: F401
        return True
    except Exception:
        return False


def exe_path(data_dir):
    return Path(data_dir) / "yt-dlp.exe"


def base_cmd(data_dir):
    """The command that runs yt-dlp: the installed Python module, else a yt-dlp on PATH, else montage_data\\yt-dlp.exe."""
    if _module_ok():
        return [sys.executable, "-m", "yt_dlp"]
    p = shutil.which("yt-dlp")
    if p:
        return [p]
    e = exe_path(data_dir)
    if e.is_file():
        return [str(e)]
    return None


def _run(cmd, timeout):
    r = subprocess.run(cmd, capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    return r.returncode, r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")


def update(data_dir, log=print):
    """Update yt-dlp before a run. (True, text) or (False, the real error text)."""
    try:
        if not frozen():
            cmd = [sys.executable, "-m", "pip", "install", "--user", "--upgrade", "yt-dlp"]     # the Python package (installed here if missing)
        elif shutil.which("yt-dlp"):
            cmd = [shutil.which("yt-dlp"), "-U"]
        else:
            e = exe_path(data_dir)
            if not e.is_file():
                url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
                import urllib.request
                log(f"yt-dlp not installed: downloading {url}")
                Path(data_dir).mkdir(parents=True, exist_ok=True)
                tmp = e.with_suffix(".part")
                with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
                    shutil.copyfileobj(r, f)
                os.replace(tmp, e)
            cmd = [str(e), "-U"]
        rc, so, se = _run(cmd, 300)
    except Exception as ex:
        return False, f"{type(ex).__name__}: {ex}"
    txt = (so.strip() + "\n" + se.strip()).strip()
    if rc != 0:
        return False, f"{' '.join(cmd)} failed (exit {rc}): {txt[-600:]}"
    if not base_cmd(data_dir):
        return False, "yt-dlp is still not available after the update: " + txt[-300:]
    lines = [x for x in txt.splitlines() if x.strip() and not x.startswith("[notice]")]
    return True, lines[-1] if lines else "ok"


def version(data_dir):
    b = base_cmd(data_dir)
    if not b:
        return "not installed"
    try:
        rc, so, se = _run(b + ["--version"], 60)
        return so.strip() or se.strip()
    except Exception as ex:
        return f"unknown ({ex})"


def search(data_dir, query, n=SEARCH_N):
    """Result list [{id, title, channel, duration}] of a YouTube search, without downloading. Raises RuntimeError with yt-dlp's own text."""
    b = base_cmd(data_dir)
    if not b:
        raise RuntimeError("yt-dlp is not installed")
    rc, so, se = _run(b + ["--flat-playlist", "--no-warnings", "-J", f"ytsearch{n}:{query}"], 120)
    if rc != 0 or not so.strip():
        raise RuntimeError(f"yt-dlp search failed (exit {rc}): {se.strip()[-600:]}")
    try:
        entries = json.loads(so).get("entries") or []
    except ValueError as ex:
        raise RuntimeError(f"yt-dlp search returned unreadable output ({ex}): {so[:200]}")
    res = []
    for e in entries:
        if not e or not e.get("id"):
            continue
        res.append({"id": e["id"], "title": e.get("title") or "", "channel": e.get("channel") or e.get("uploader") or "",
                    "duration": e.get("duration") or 0})
    return res


def find_candidates(data_dir, title, artist, search_fn=None):
    """Two searches (artist + title, and the same with 'topic' so the auto-generated album audio shows up), merged, no duplicates."""
    sf = search_fn or (lambda q: search(data_dir, q))
    first = artist.split(", ")[0] if artist else ""
    seen, res, errs = set(), [], []
    for q in (f"{artist} {title}".strip(), f"{first} {title} topic".strip()):
        try:
            for c in sf(q):
                if c["id"] not in seen:
                    seen.add(c["id"])
                    res.append(c)
        except RuntimeError as ex:
            errs.append(str(ex))
    if not res and errs:
        raise RuntimeError(errs[0])
    return res


def download_mp3(data_dir, video_id, tmp_dir):
    """Best audio of one video -> MP3 (VBR quality 0) in tmp_dir. Returns the path. Raises RuntimeError with yt-dlp's text."""
    b = base_cmd(data_dir)
    if not b:
        raise RuntimeError("yt-dlp is not installed")
    tmp_dir = Path(tmp_dir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / f"{video_id}.%(ext)s"
    cmd = b + ["--no-playlist", "--no-warnings", "-f", "bestaudio/best", "-x", "--audio-format", "mp3", "--audio-quality", "0",
               "--no-embed-metadata", "--no-embed-thumbnail", "-o", str(out), f"https://www.youtube.com/watch?v={video_id}"]
    rc, so, se = _run(cmd, 900)
    p = tmp_dir / f"{video_id}.mp3"
    if rc != 0 or not p.is_file():
        raise RuntimeError(f"yt-dlp download failed (exit {rc}): {(se.strip() or so.strip())[-600:]}")
    return p


def write_tags(path, title, artist):
    """ID3 title + artist from the Spotify / CSV data (replaces every tag YouTube's file carried)."""
    from mutagen.id3 import ID3, TIT2, TPE1, ID3NoHeaderError
    try:
        t = ID3(str(path))
        t.delete()
    except ID3NoHeaderError:
        pass
    t = ID3()
    t.add(TIT2(encoding=3, text=[title]))
    t.add(TPE1(encoding=3, text=[artist]))
    t.save(str(path), v2_version=3)


def place(tmp_mp3, songs_dir, title, artist):
    """Tag the MP3 and move it into the songs folder under its CSV-based name. Never overwrites: returns (path, None), or (None, why)."""
    dest = Path(songs_dir) / song_filename(title, artist)
    if dest.exists():
        return None, f"file already exists: {dest.name}"
    write_tags(tmp_mp3, title, artist)
    shutil.move(str(tmp_mp3), str(dest))
    # the app's song scan skips files modified in the last 15 s (maybe still being written); this one is finished
    old = time.time() - 60
    os.utime(dest, (old, old))
    return dest, None


def fetch_new(rows, songs_dir, data_dir, n, sort_key, progress=print, search_fn=None, download_fn=None, tmp_dir=None):
    """rows: CSV tracks without an MP3 ({title, artist, dur, added}). The `n` newest (by sort_key, newest first) are searched; a track is
    downloaded only when a result passes every rule. Returns {"downloaded": [...], "notfound": [...], "failed": [...]}."""
    tmp_dir = Path(tmp_dir or Path(data_dir) / "yt_tmp")
    todo = sorted(rows, key=sort_key, reverse=True)[:max(0, int(n))]
    rep = {"downloaded": [], "notfound": [], "failed": [], "checked": len(todo)}
    dl = download_fn or (lambda vid: download_mp3(data_dir, vid, tmp_dir))
    for i, r in enumerate(todo, 1):
        t, a, want = r["title"], r["artist"], float(r.get("dur") or 0)
        name = f"{a} - {t}"
        progress(f"{i}/{len(todo)} searching: {name}")
        if want <= 0:
            rep["notfound"].append({"title": t, "artist": a, "reason": "the CSV has no track length, so no result can be checked"})
            continue
        try:
            cands = find_candidates(data_dir, t, a, search_fn)
        except RuntimeError as ex:
            rep["failed"].append({"title": t, "artist": a, "reason": f"search failed: {ex}"})
            continue
        best, miss = pick(cands, t, [x.strip() for x in a.split(",")], want)
        if not best:
            rep["notfound"].append({"title": t, "artist": a, "reason": miss})
            continue
        progress(f"{i}/{len(todo)} downloading: {name}  <-  {best['channel']}")
        try:
            tmp = dl(best["id"])
            dest, why = place(tmp, songs_dir, t, a)
        except Exception as ex:
            rep["failed"].append({"title": t, "artist": a, "reason": f"download failed: {ex}"})
            continue
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if dest is None:
            rep["failed"].append({"title": t, "artist": a, "reason": why})
        else:
            rep["downloaded"].append({"title": t, "artist": a, "video": best["title"], "channel": best["channel"], "kind": best["kind"],
                                      "length": fmt_len(best["duration"]), "id": best["id"], "file": str(dest)})
    return rep


def report_text(rep, update_msg=""):
    L = [f"Checked {rep['checked']} newest missing song(s): {len(rep['downloaded'])} downloaded, {len(rep['notfound'])} not found, "
         f"{len(rep['failed'])} failed.", ""]
    if update_msg:
        L += [f"yt-dlp: {update_msg}", ""]
    if rep["downloaded"]:
        L.append("DOWNLOADED")
        for d in rep["downloaded"]:
            L.append(f"  {d['title']} - {d['artist']}\n      video: \"{d['video']}\" ({d['length']}) | channel: {d['channel']} | https://youtu.be/{d['id']}")
        L.append("")
    if rep["notfound"]:
        L.append("NOT FOUND (nothing downloaded; check by hand)")
        for d in rep["notfound"]:
            L.append(f"  {d['title']} - {d['artist']}\n      {d['reason']}")
        L.append("")
    if rep["failed"]:
        L.append("FAILED")
        for d in rep["failed"]:
            L.append(f"  {d['title']} - {d['artist']}\n      {d['reason']}")
    return "\n".join(L).rstrip() + "\n"
