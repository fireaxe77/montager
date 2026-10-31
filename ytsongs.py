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
import threading
import time
import unicodedata
from pathlib import Path

DUR_TOL_S = 5.0                          # a result must be within this many seconds of the Spotify length
SEARCH_N = 10                            # results read per search query
BANNED = ("slowed", "sped up", "speed up", "nightcore", "reverb", "8d", "live", "remix", "cover", "instrumental", "karaoke",
          "8-bit", "8 bit", "8bit", "chiptune", "emulation", "midi", "piano version", "acoustic", "tribute", "mashup", "bass boosted", "type beat", "reaction", "tutorial")
OK_WORDS = {"official", "audio", "video", "music", "lyric", "lyrics", "visualizer", "visualiser", "hd", "hq", "4k", "album", "version", "topic", "remastered",
            "feat", "ft", "featuring"}              # words of a video title that cost nothing
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


def _words(s):
    return re.findall(r"\w+", _norm(s))


def extra_words(video_title, title, artists):
    """The words of a video title that are neither the track title, nor an artist of the CSV, nor feat / ft / featuring, nor on the small allowlist (official, audio, video, ...). Fewer = cleaner."""
    known = set(_words(title)) | OK_WORDS
    for a in artists:
        known |= set(_words(a))
    return [w for w in _words(video_title) if w not in known]


def _alnum(s):
    return re.sub(r"[^\w]+", "", _norm(s))


def _is_name(channel, names, label=""):
    """True when a channel name is one of the artists (also 'X Official', 'X Music', 'XVEVO', 'X Records') or the CSV record label."""
    cn = _alnum(channel)
    if not cn:
        return False
    for a in list(names) + ([label] if label else []):
        an = _alnum(a)
        if not an:
            continue
        if cn == an:
            return True
        for suf in ("official", "music", "vevo", "records", "recordings", "topic"):
            if cn in (an + suf, suf + an):
                return True
    return False


# channel score, best first
CH_TOPIC_OWN, CH_NAMED, CH_VERIFIED, CH_OTHER = 0, 1, 2, 3
CH_TEXT = {0: "Topic channel of the artist / label", 1: "channel of the artist / label", 2: "verified channel", 3: "other channel"}


def channel_score(channel, artists, label="", verified=False):
    """0 an auto-generated '- Topic' channel whose name is an artist or the record label (a Topic channel of anybody else is no better than any channel), 1 a channel named like an artist
    or the label, 2 a verified channel, 3 anything else."""
    c = _norm(channel)
    if c.endswith(" - topic"):
        if _is_name(c[:-len(" - topic")], artists, label):
            return CH_TOPIC_OWN
    elif _is_name(channel, artists, label):
        return CH_NAMED
    return CH_VERIFIED if verified else CH_OTHER


def channel_kind(channel, artists):
    """'topic' | 'artist' | 'other' (the V9.5 words; kept for the older tests)."""
    c = _norm(channel)
    if c.endswith(" - topic"):
        return "topic"
    return "artist" if _is_name(channel, artists) else "other"


def judge(cand, title, artists, want_dur):
    """None when the result passes the HARD rules (length within DUR_TOL_S of the CSV length, none of the banned words unless the Spotify title has it), else the reason."""
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


def rank(cands, title, artists, want_dur, label=""):
    """(ranked, rejected): ranked = every result that passes the hard rules, best first by (fewest extra words, channel score, most views, search order), each as the result dict plus
    `extra` (the leftover words), `ch` (channel score), `kind` and `uncertain`; rejected = [(reason, result)]. A pick is UNCERTAIN when it still has extra words or comes from an 'other' channel."""
    ok, rej = [], []
    for i, c in enumerate(cands):
        why = judge(c, title, artists, want_dur)
        if why:
            rej.append((why, c))
            continue
        ex = extra_words(c.get("title", ""), title, artists)
        ch = channel_score(c.get("channel", ""), artists, label, bool(c.get("verified")))
        ok.append((len(ex), ch, -int(c.get("views") or 0), i, dict(c, extra=ex, ch=ch, kind=("topic" if ch == CH_TOPIC_OWN else "artist" if ch == CH_NAMED else "other"),
                                                                    uncertain=bool(ex) or ch == CH_OTHER)))
    ok.sort(key=lambda x: x[:4])
    return [x[4] for x in ok], rej


def pick(cands, title, artists, want_dur, label=""):
    """(best result or None, nearest-miss text). The best may be UNCERTAIN (see rank): the caller does not download those."""
    ranked, rej = rank(cands, title, artists, want_dur, label)
    if ranked:
        return ranked[0], ""
    return None, nearest_miss(rej, want_dur)


def describe(c):
    """one result as text: title, channel, length, views, extra words, link"""
    return (f"\"{c.get('title', '')}\" | {c.get('channel', '')} ({CH_TEXT.get(c.get('ch', 3))}) | {fmt_len(c.get('duration'))} | {int(c.get('views') or 0):,} views | "
            f"{len(c.get('extra') or [])} extra word(s)" + (f": {' '.join(c['extra'])}" if c.get("extra") else "") + f" | https://youtu.be/{c.get('id')}")


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
                    "duration": e.get("duration") or 0, "views": e.get("view_count") or 0, "verified": bool(e.get("channel_is_verified"))})
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


# ------------------------------------------------------------------ covers + tags (V9.5.1)
DEEZER_API = "https://api.deezer.com"
DEEZER_GAP_S = 0.34                      # at most ~3 Deezer requests a second (all threads together)
COVER_MIN_PX = 300                       # a smaller picture is not used as a cover
TAG_FIELDS = ("title", "artist", "album", "year", "genre", "label", "isrc")
_ID3 = {"title": "TIT2", "artist": "TPE1", "album": "TALB", "year": "TDRC", "genre": "TCON", "label": "TPUB", "isrc": "TSRC"}
_net_lock = threading.Lock()
_net_last = [0.0]
_cache_lock = threading.Lock()
_CACHES = {}


def http_get(url, timeout=30):
    """Bytes of a URL, at most DEEZER_GAP_S apart from the previous request. Raises RuntimeError with the real error text."""
    import urllib.request
    import urllib.error
    with _net_lock:
        wait = _net_last[0] + DEEZER_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _net_last[0] = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": "Montager/9.5 (+songs covers)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as ex:
        body = ""
        try:
            body = ex.read().decode("utf-8", "replace")[:200]
        except Exception:                                    # noqa: BLE001
            pass
        raise RuntimeError(f"HTTP {ex.code} {ex.reason} for {url} {body}".strip())
    except Exception as ex:                                  # noqa: BLE001
        raise RuntimeError(f"{type(ex).__name__}: {ex} ({url})")


def deezer_json(path):
    """JSON of a Deezer API call, or None when Deezer answers 'no data'. Quota answers are waited out (3 tries); other API errors raise RuntimeError with Deezer's own text."""
    url = DEEZER_API + path
    for attempt in range(3):
        raw = http_get(url)
        try:
            d = json.loads(raw.decode("utf-8", "replace"))
        except ValueError as ex:
            raise RuntimeError(f"Deezer returned unreadable data ({ex}): {raw[:120]!r} ({url})")
        err = d.get("error") if isinstance(d, dict) else None
        if not err:
            return d
        code = err.get("code")
        if code in (800, 404) or str(err.get("type")) == "DataException":
            return None
        if code == 4 and attempt < 2:                        # "Quota limit exceeded": slow down and ask again
            time.sleep(2.0 * (attempt + 1))
            continue
        raise RuntimeError(f"Deezer API error {code}: {err.get('message')} ({url})")
    return None


def _cache_path(data_dir):
    return Path(data_dir) / "deezer_cache.json"


def cache_load(data_dir):
    key = str(data_dir)
    with _cache_lock:
        if key not in _CACHES:
            try:
                _CACHES[key] = json.loads(_cache_path(data_dir).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _CACHES[key] = {}
        return _CACHES[key]


def cache_save(data_dir):
    """Saved in one piece after a batch (a refused write is retried and then kept in memory only)."""
    with _cache_lock:
        c = _CACHES.get(str(data_dir))
        if c is None:
            return
        p = _cache_path(data_dir)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        for _ in range(6):
            try:
                tmp.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, p)
                return
            except OSError:
                time.sleep(0.25)


def row_key(row):
    """Cache key of a track: its ISRC, else artist + title."""
    isrc = (row.get("isrc") or "").strip().upper()
    return isrc or "s:" + _norm(row.get("artist")) + "|" + _norm(row.get("title"))


def _album_cover(d):
    a = (d or {}).get("album") or {}
    url = a.get("cover_xl") or ""
    if not url or "/cover//" in url or not a.get("md5_image", "x"):          # Deezer's address of a track without art has no picture id in it
        return None
    return url


def cover_lookup(row, data_dir, tol=DUR_TOL_S, use_cache=True):
    """Deezer cover address for a CSV track: by its ISRC, else by an artist + title search whose result length is within `tol` s of the CSV length.
    Returns {"url", "match": "isrc" | "search"} or {"url": None, "match": None}. Answers (also 'nothing') are cached per ISRC on disk; network / API errors raise RuntimeError and are not cached."""
    c = cache_load(data_dir)
    k = row_key(row)
    if use_cache and k in c:
        return dict(c[k])
    res = {"url": None, "match": None}
    isrc = (row.get("isrc") or "").strip().upper()
    if isrc:
        d = deezer_json("/track/isrc:" + urllib_quote(isrc))
        u = _album_cover(d)
        if u:
            res = {"url": u, "match": "isrc"}
    if not res["url"]:
        want = float(row.get("dur") or 0)
        first = [x.strip() for x in str(row.get("artist") or "").split(",")][0]
        for q in (f'artist:"{first}" track:"{row.get("title", "")}"', f"{first} {row.get('title', '')}"):
            d = deezer_json("/search?q=" + urllib_quote(q) + "&limit=10")
            hit = None
            for e in ((d or {}).get("data") or []):
                u = _album_cover(e)
                if u and want > 0 and abs(float(e.get("duration") or 0) - want) <= tol:
                    hit = u
                    break
            if hit:
                res = {"url": hit, "match": "search"}
                break
    with _cache_lock:
        c[k] = res
    return dict(res)


def urllib_quote(s):
    from urllib.parse import quote
    return quote(s, safe="")


def image_size(data):
    try:
        from PIL import Image
        import io
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception:                                        # noqa: BLE001
        return None


def cover_image(url, key, data_dir):
    """The cover picture (bytes) for `url`; kept on disk per track key so a repeat is instant. Raises RuntimeError on a network error / a picture that is not an image or too small."""
    safe = re.sub(r"[^\w.-]+", "_", key)[:80]
    p = Path(data_dir) / "covers" / (safe + ".jpg")
    if p.is_file() and p.stat().st_size > 1000:
        return p.read_bytes()
    data = http_get(url, timeout=60)
    sz = image_size(data)
    if not sz or min(sz) < COVER_MIN_PX:
        raise RuntimeError(f"the cover picture is not usable (size {sz}) ({url})")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    except OSError:
        pass
    return data


def square_crop(data):
    """A YouTube thumbnail of a Topic upload is the album art on black bars (16:9): the art is cut out as a square. Returns JPEG bytes."""
    from PIL import Image
    import io
    im = Image.open(io.BytesIO(data)).convert("RGB")
    g = im.convert("L").point(lambda v: 255 if v > 16 else 0)
    bb = g.getbbox() or (0, 0) + im.size
    w, h = bb[2] - bb[0], bb[3] - bb[1]
    s = min(w, h)
    x0, y0 = bb[0] + (w - s) // 2, bb[1] + (h - s) // 2
    out = io.BytesIO()
    im.crop((x0, y0, x0 + s, y0 + s)).save(out, "JPEG", quality=92)
    return out.getvalue()


def topic_thumbnail(video_id):
    """The thumbnail of a video as a square JPEG (only used for a '- Topic' upload, whose thumbnail IS the album art). Raises RuntimeError."""
    last = None
    for name in ("maxresdefault", "hqdefault"):
        try:
            data = http_get(f"https://i.ytimg.com/vi/{video_id}/{name}.jpg", timeout=30)
            out = square_crop(data)
            sz = image_size(out)
            if sz and min(sz) >= 200:
                return out
            last = RuntimeError(f"thumbnail too small ({sz})")
        except RuntimeError as ex:
            last = ex
    raise last or RuntimeError("no thumbnail")


def cover_for(row, data_dir, topic_id=None):
    """The cover for a track: (jpeg bytes or None, source text, note). source: 'Deezer (ISRC)' | 'Deezer (search)' | 'Topic thumbnail' | 'none'. A network / API error is returned in
    `note` (its real text) and the next source is tried."""
    notes = []
    try:
        r = cover_lookup(row, data_dir)
        if r["url"]:
            return cover_image(r["url"], row_key(row), data_dir), "Deezer (" + ("ISRC" if r["match"] == "isrc" else "search") + ")", "; ".join(notes)
    except RuntimeError as ex:
        notes.append(f"Deezer: {ex}")
    if topic_id:
        try:
            return topic_thumbnail(topic_id), "Topic thumbnail", "; ".join(notes)
        except RuntimeError as ex:
            notes.append(f"thumbnail: {ex}")
    return None, "none", "; ".join(notes)


# CSV extras (album, release date, genres, label, ISRC): read here, so the app's own playlist reader stays as it is
def read_meta(csv_path):
    """{track key: {isrc, album, year, genre, label}} of the Exportify CSV; the key is the track URI, else 'artist - title' (same as the app's rank key)."""
    import csv
    out = {}
    if not csv_path:
        return out
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        heads = {h.strip().lower(): h for h in (rd.fieldnames or [])}
        g = lambda r, n: (r.get(heads[n]) or "").strip() if n in heads else ""
        for r in rd:
            title = g(r, "track name")
            if not title:
                continue
            artist = g(r, "artist name(s)").replace(";", ", ")
            m = re.match(r"\d{4}", g(r, "release date"))
            genres = [x.strip() for x in g(r, "genres").split(",") if x.strip()]
            d = {"isrc": g(r, "isrc").upper(), "album": g(r, "album name"), "year": m.group(0) if m else "", "genre": genres[0] if genres else "",
                 "label": g(r, "record label")}
            out[g(r, "track uri") or f"{artist} - {title}"] = d
    return out


def track_tags(row, meta):
    """Every tag value of a CSV row (title / artist as the app has them in the row)."""
    m = (meta or {}).get(row.get("uri") or f"{row['artist']} - {row['title']}", {})
    t = {"title": row["title"], "artist": row["artist"]}
    t.update({k: m.get(k, "") for k in ("album", "year", "genre", "label", "isrc")})
    return t


def read_state(path):
    """(has an embedded cover, {field: non-empty}) of an MP3's ID3 tag."""
    from mutagen.id3 import ID3, ID3NoHeaderError
    try:
        t = ID3(str(path))
    except ID3NoHeaderError:
        return False, {f: False for f in TAG_FIELDS}
    st = {}
    for f, fid in _ID3.items():
        fr = t.get(fid)
        st[f] = bool(fr and any(str(x).strip() for x in fr.text))
    return bool(t.getall("APIC")), st


def apply_tags(path, tags, cover=None, fresh=False):
    """Writes the tags (and the cover as the front cover) INTO the MP3's ID3 tag without touching the audio. Only what is missing is written (an existing cover and every non-empty
    field stay); fresh=True first removes the tag a new download carries. The file's modified time is kept. Returns the list of fields added ('cover' included)."""
    from mutagen.id3 import ID3, ID3NoHeaderError, APIC, TIT2, TPE1, TALB, TDRC, TCON, TPUB, TSRC
    path = str(path)
    st = os.stat(path)
    try:
        t = ID3(path)
        if fresh:
            t.delete()
            t = ID3()
    except ID3NoHeaderError:
        t = ID3()
    ver = 4 if getattr(t, "version", (2, 3, 0))[1] == 4 else 3
    cls = {"title": TIT2, "artist": TPE1, "album": TALB, "year": TDRC, "genre": TCON, "label": TPUB, "isrc": TSRC}
    added = []
    for f in TAG_FIELDS:
        v = str(tags.get(f) or "").strip()
        fr = t.get(_ID3[f])
        if v and not (fr and any(str(x).strip() for x in fr.text)):
            t.setall(_ID3[f], [cls[f](encoding=3, text=[v])])
            added.append(f)
    if cover and not t.getall("APIC"):
        t.add(APIC(encoding=3, mime="image/jpeg" if cover[:3] == b"\xff\xd8\xff" else "image/png", type=3, desc="Cover", data=cover))
        added.append("cover")
    if added:
        t.save(path, v2_version=ver)
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
    return added


def write_tags(path, tags, cover=None):
    """A new download: its tags are exactly the CSV's (and the cover). Same function as for existing songs, on an empty tag."""
    return apply_tags(path, tags, cover, fresh=True)


REPLACED_DIR = "_replaced"


def place(tmp_mp3, songs_dir, title, artist, old=None):
    """Move the finished MP3 into the songs folder under its CSV-based name. Never overwrites: returns (path, None), or (None, why). old = an existing file this one replaces: it is moved to
    songs_dir\\_replaced first (never deleted) and put back if the new file cannot be placed."""
    songs_dir = Path(songs_dir)
    dest = songs_dir / song_filename(title, artist)
    moved = None
    if old and Path(old).exists():
        if dest.exists() and os.path.normcase(str(dest)) != os.path.normcase(str(old)):
            return None, f"file already exists: {dest.name}"
        rep = songs_dir / REPLACED_DIR
        rep.mkdir(exist_ok=True)
        moved = rep / Path(old).name
        if moved.exists():
            moved = rep / (moved.stem + time.strftime(" %Y%m%d-%H%M%S") + moved.suffix)
        shutil.move(str(old), str(moved))
    elif dest.exists():
        return None, f"file already exists: {dest.name}"
    try:
        shutil.move(str(tmp_mp3), str(dest))
    except Exception:
        if moved:
            shutil.move(str(moved), str(old))
        raise
    # the app's song scan skips files modified in the last 15 s (maybe still being written); this one is finished
    old_t = time.time() - 60
    os.utime(dest, (old_t, old_t))
    return dest, None


def fetch_new(rows, songs_dir, data_dir, n, sort_key, progress=print, search_fn=None, download_fn=None, tmp_dir=None, meta=None, cover_fn=None, stop=None):
    """rows: CSV tracks to fetch ({title, artist, dur, added, uri}; a row with "_old" = the existing file it replaces). n = None: all of them, else the `n` newest (by sort_key). A track is
    downloaded only when a result passes every rule; its MP3 gets the CSV tags and a cover (Deezer, else a Topic upload's thumbnail). stop() true = stop after the current track.
    Returns {"downloaded": [...], "notfound": [...], "failed": [...], "stopped": bool}."""
    tmp_dir = Path(tmp_dir or Path(data_dir) / "yt_tmp")
    todo = sorted(rows, key=sort_key, reverse=True) if n is None else sorted(rows, key=sort_key, reverse=True)[:max(0, int(n))]
    rep = {"downloaded": [], "notfound": [], "failed": [], "uncertain": [], "checked": len(todo), "stopped": False}
    dl = download_fn or (lambda vid: download_mp3(data_dir, vid, tmp_dir))
    cf = cover_fn or (lambda row, topic_id: cover_for(row, data_dir, topic_id))
    for i, r in enumerate(todo, 1):
        if stop and stop():
            rep["stopped"] = True
            break
        t, a, want, old = r["title"], r["artist"], float(r.get("dur") or 0), r.get("_old")
        keep = " (the existing file is untouched)" if old else ""
        name = f"{a} - {t}"
        progress(f"{i}/{len(todo)} searching: {name}")
        if want <= 0:
            rep["notfound"].append({"title": t, "artist": a, "reason": "the CSV has no track length, so no result can be checked" + keep})
            continue
        try:
            cands = find_candidates(data_dir, t, a, search_fn)
        except RuntimeError as ex:
            rep["failed"].append({"title": t, "artist": a, "reason": f"search failed: {ex}" + keep})
            continue
        label = track_tags(r, meta).get("label", "")
        ranked, rej = rank(cands, t, [x.strip() for x in a.split(",")], want, label)
        if not ranked:
            rep["notfound"].append({"title": t, "artist": a, "reason": nearest_miss(rej, want) + keep})
            continue
        best = ranked[0]
        runner = ranked[1] if len(ranked) > 1 else None
        if best["uncertain"]:                              # still extra words in the title, or an unrelated channel: never downloaded in a batch, listed with the best 3
            rep["uncertain"].append({"title": t, "artist": a, "top": [describe(c) for c in ranked[:3]], "existing": bool(old)})
            continue
        progress(f"{i}/{len(todo)} downloading: {name}  <-  {best['channel']}")
        try:
            tmp = dl(best["id"])
            tg = track_tags(r, meta)
            cover, csrc, cnote = cf(dict(r, isrc=tg["isrc"]), best["id"] if best.get("kind") == "topic" else None)
            write_tags(tmp, tg, cover)
            dest, why = place(tmp, songs_dir, t, a, old=old)
        except Exception as ex:
            rep["failed"].append({"title": t, "artist": a, "reason": f"download failed: {ex}" + keep})
            continue
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if dest is None:
            rep["failed"].append({"title": t, "artist": a, "reason": (why or "") + keep})
        else:
            rep["downloaded"].append({"title": t, "artist": a, "video": best["title"], "channel": best["channel"], "kind": best["kind"],
                                      "length": fmt_len(best["duration"]), "id": best["id"], "file": str(dest), "cover": csrc, "cover_note": cnote,
                                      "replaced": Path(old).name if old else "", "chosen": describe(best), "runner": describe(runner) if runner else ""})
        cache_save(data_dir)
    return rep


def report_text(rep, update_msg=""):
    L = [f"Checked {rep['checked']} song(s): {len(rep['downloaded'])} downloaded, {len(rep.get('uncertain', []))} uncertain, {len(rep['notfound'])} not found, {len(rep['failed'])} failed."
         + ("  STOPPED early." if rep.get("stopped") else ""), ""]
    if update_msg:
        L += [f"yt-dlp: {update_msg}", ""]
    if rep["downloaded"]:
        L.append("DOWNLOADED")
        for d in rep["downloaded"]:
            L.append(f"  {d['title']} - {d['artist']}\n      chosen:    {d.get('chosen') or d['video']}\n      runner-up: {d.get('runner') or '(none passed the rules)'}\n"
                     f"      cover: {d.get('cover', 'none')}" + (f" ({d['cover_note']})" if d.get("cover_note") else "")
                     + (f"\n      replaced: {d['replaced']} (old file kept in {REPLACED_DIR})" if d.get("replaced") else ""))
        L.append("")
    if rep.get("uncertain"):
        L.append("UNCERTAIN (not downloaded: the best title still has extra words or comes from an unrelated channel; pick by hand)")
        for d in rep["uncertain"]:
            L.append(f"  {d['title']} - {d['artist']}" + ("  (the existing file is untouched)" if d.get("existing") else ""))
            for i, c in enumerate(d["top"], 1):
                L.append(f"      {i}. {c}")
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


# ------------------------------------------------------------------ covers + tags for the songs already there
def process_existing(pairs, meta, data_dir, apply, progress=print, stop=None, log=None):
    """pairs: [(CSV row, {"path"})] the app's exact title + artist match made. For each MP3: its missing cover (Deezer only) and its EMPTY tag fields (CSV values) are looked at;
    apply=False changes nothing (a preview), apply=True writes them with apply_tags (existing cover / non-empty tags are never touched, the audio and the file name never change).
    Returns the counts + lists."""
    rep = {"total": len(pairs), "cover": 0, "tags": 0, "no_deezer": 0, "complete": 0, "not_mp3": 0, "changed": [], "locked": [], "errors": [], "stopped": False, "done": 0}
    last_save = time.monotonic()
    for i, (row, a) in enumerate(pairs, 1):
        if stop and stop():
            rep["stopped"] = True
            break
        path = a["path"]
        progress(f"{i}/{len(pairs)}")
        rep["done"] = i
        if not path.lower().endswith(".mp3"):
            rep["not_mp3"] += 1
            continue
        try:
            has_cover, st = read_state(path)
        except Exception as ex:                              # noqa: BLE001
            rep["errors"].append(f"{Path(path).name}: cannot read the tag: {type(ex).__name__}: {ex}")
            continue
        tags = track_tags(row, meta)
        missing = [f for f in TAG_FIELDS if str(tags.get(f) or "").strip() and not st[f]]
        cover, csrc = None, ""
        need_cover = not has_cover
        if need_cover:
            try:
                lk = cover_lookup(dict(row, isrc=tags.get("isrc", "")), data_dir)
                if lk["url"]:
                    csrc = "Deezer (" + ("ISRC" if lk["match"] == "isrc" else "search") + ")"
                    if apply:
                        cover = cover_image(lk["url"], row_key(dict(row, isrc=tags.get("isrc", ""))), data_dir)
            except RuntimeError as ex:
                rep["errors"].append(f"{Path(path).name}: {ex}")
                need_cover = None                            # unknown this time (not counted as 'nothing on Deezer')
        if need_cover and not csrc:
            rep["no_deezer"] += 1
        if need_cover and csrc:
            rep["cover"] += 1
        if missing:
            rep["tags"] += 1
        if not missing and has_cover:
            rep["complete"] += 1
        if apply and (missing or cover):
            if not os.access(path, os.W_OK):
                rep["locked"].append(f"{Path(path).name}: read-only")
                continue
            try:
                added = apply_tags(path, {f: tags[f] for f in missing}, cover)
            except Exception as ex:                          # noqa: BLE001
                rep["locked"].append(f"{Path(path).name}: {type(ex).__name__}: {ex}")
                continue
            if added:
                line = f"{path} | added: {', '.join(added)}" + (f" | cover from {csrc}" if "cover" in added else "")
                rep["changed"].append(line)
                if log:
                    log(line)
        if time.monotonic() - last_save > 20:
            cache_save(data_dir)
            last_save = time.monotonic()
    cache_save(data_dir)
    return rep


def existing_report_text(rep, apply):
    L = [("APPLIED" if apply else "PREVIEW (nothing was changed)") + f" - {rep['done']} of {rep['total']} MP3 files looked at" + ("  (STOPPED early)" if rep.get("stopped") else ""), ""]
    if not apply:
        L.append("What the Apply button would do:")
    L += [f"  would get a cover from Deezer : {rep['cover']}" if not apply else f"  covers added                  : {len([c for c in rep['changed'] if 'cover' in c.split('|')[1]])}",
          f"  would get tags (fields empty) : {rep['tags']}" if not apply else f"  files that needed tags        : {rep['tags']}",
          f"  nothing on Deezer (no cover)  : {rep['no_deezer']}",
          f"  already complete              : {rep['complete']}",
          f"  not in the CSV (skipped)      : {rep.get('not_in_csv', 0)}"]
    if rep.get("not_mp3"):
        L.append(f"  not an MP3 (skipped)          : {rep['not_mp3']}")
    if apply:
        L += ["", f"files changed: {len(rep['changed'])}"]
    if rep["locked"]:
        L += ["", "SKIPPED (locked / read-only / could not be written):"] + ["  " + x for x in rep["locked"]]
    if rep["errors"]:
        L += ["", f"ERRORS ({len(rep['errors'])}, the run went on with the next file):"] + ["  " + x for x in rep["errors"][:60]]
        if len(rep["errors"]) > 60:
            L.append(f"  ... and {len(rep['errors']) - 60} more")
    return "\n".join(L) + "\n"
