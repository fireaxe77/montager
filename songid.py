"""V9.5.3: a stable identity for a song FILE that does not change when its tags or cover change.

The identity is made of the audio data only (an MP3's ID3v2 block at the start and its ID3v1 / APE block at the end are skipped) plus the duration. The song-map caches used the file's size,
its modified time and the bytes at its start and end: a tool that rewrites tags (embedded covers, album, year ...) made every file look like a new song and the maps were rebuilt.

audio_id(path)        'a1-<20 hex>-<duration in 0.1 s>'; computed once per file version and kept in montage_data\\song_identity.json (path -> size, modified time, id)
migrate_v2(...)       re-keys old cache entries (size-time-hash signature) to the new identity (used by montage.songdata_migrate)
Nothing here changes a song map, a hand label or the audio.
"""
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

ID_PREFIX = "a1-"
CHUNK = 64 * 1024
_lock = threading.RLock()
_INDEX = {}                       # str(data dir) -> {path: [size, mtime_ns, id]}
_DIRTY = {}


def audio_region(path):
    """(start, end) byte offsets of an MP3's audio: after the ID3v2 tag(s) at the start, before an ID3v1 / APE tag at the end. Other formats: the whole file."""
    size = os.path.getsize(path)
    if not str(path).lower().endswith(".mp3"):
        return 0, size
    with open(path, "rb") as f:
        start = 0
        for _ in range(4):                                  # (some files carry more than one ID3v2 block)
            f.seek(start)
            h = f.read(10)
            if len(h) == 10 and h[:3] == b"ID3" and all(b < 0x80 for b in h[6:10]):
                n = (h[6] << 21) | (h[7] << 14) | (h[8] << 7) | h[9]
                start += 10 + n + (10 if h[5] & 0x10 else 0)
            else:
                break
        end = size
        if end - start > 128:
            f.seek(end - 128)
            if f.read(3) == b"TAG":
                end -= 128
        if end - start > 32:
            f.seek(end - 32)
            ft = f.read(32)
            if ft[:8] == b"APETAGEX":
                total = int.from_bytes(ft[12:16], "little") + (32 if int.from_bytes(ft[20:24], "little") & (1 << 31) else 0)
                if 0 < total < end - start:
                    end -= total
    return min(start, size), max(min(start, size), end)


def audio_hash(path):
    """sha1 hex of the audio region's length and three 64 KB samples of it (start, middle, end); a short region is hashed whole"""
    s, e = audio_region(path)
    n = e - s
    h = hashlib.sha1(str(n).encode())
    with open(path, "rb") as f:
        if n <= 4 * CHUNK:
            f.seek(s)
            h.update(f.read(n))
        else:
            for off in (s, s + n // 2 - CHUNK // 2, e - CHUNK):
                f.seek(off)
                h.update(f.read(CHUNK))
    return h.hexdigest()[:20]


def duration_of(path):
    try:
        from mutagen import File
        f = File(path)
        return float(getattr(f.info, "length", 0) or 0) if f is not None else 0.0
    except Exception:                                        # noqa: BLE001
        return 0.0


def _index_path(data_dir):
    return Path(data_dir) / "song_identity.json"


def index_load(data_dir):
    key = str(data_dir)
    with _lock:
        if key not in _INDEX:
            try:
                _INDEX[key] = json.loads(_index_path(data_dir).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _INDEX[key] = {}
        return _INDEX[key]


def index_save(data_dir):
    with _lock:
        idx = _INDEX.get(str(data_dir))
        if idx is None or not _DIRTY.get(str(data_dir)):
            return
        p = _index_path(data_dir)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        for _ in range(6):
            try:
                tmp.write_text(json.dumps(idx, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, p)
                _DIRTY[str(data_dir)] = False
                return
            except OSError:
                time.sleep(0.25)


def audio_id(path, data_dir, dur=None):
    """The identity of a song file (see the module text). Known for a file version (path + size + modified time) = no read. None when the file cannot be read."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    idx = index_load(data_dir)
    k = str(path)
    with _lock:
        e = idx.get(k)
        if e and e[0] == st.st_size and e[1] == st.st_mtime_ns:
            return e[2]
    try:
        h = audio_hash(path)
    except OSError:
        return None
    d = float(dur) if dur else duration_of(path)
    aid = f"{ID_PREFIX}{h}-{int(round(d * 10))}"
    with _lock:
        idx[k] = [st.st_size, st.st_mtime_ns, aid]
        _DIRTY[str(data_dir)] = True
    return aid


_SIG = re.compile(r"^(?P<ns>[^|]+)\|(?P<alg>[^|]+)\|(?P<sig>\d+-\d+-[0-9a-f]+)\|(?P<rest>.*)$")


def split_v2_key(key):
    """(prefix up to and including the 'ns|alg|', old signature, rest) of a song_cache_v2 key, or None"""
    m = _SIG.match(key)
    if not m:
        return None
    return f"{m.group('ns')}|{m.group('alg')}|", m.group("sig"), m.group("rest")


def sig_parts(sig):
    size, mt, _h = sig.split("-", 2)
    return int(size), int(mt)


def tie_orphans(sigs, files, dur_tol=1.0):
    """Which current file does each OLD signature (size-modified time-hash) belong to? files = [{path, dur, mtime(int s), size}] (sigs given as {sig: duration or None}).
    A file's modified time is kept by a tag writer, so: the same modified time and a duration within dur_tol (the closest, when exactly one is clearly closest). Returns
    ({sig: file}, {sig: reason it could not be tied})."""
    by_mt = {}
    for f in files:
        by_mt.setdefault(int(f["mtime"]), []).append(f)
    ok, bad = {}, {}
    for sig, dur in sigs.items():
        size, mt = sig_parts(sig)
        cand = by_mt.get(mt, [])
        if not cand:
            bad[sig] = "no file in the songs folder has this modified time (the file was replaced, moved with a new time or deleted)"
            continue
        exact = [f for f in cand if f["size"] == size]
        if len(exact) == 1:
            ok[sig] = exact[0]
            continue
        if dur:
            near = sorted(cand, key=lambda f: abs(float(f.get("dur") or 0) - dur))
            d0 = abs(float(near[0].get("dur") or 0) - dur)
            d1 = abs(float(near[1].get("dur") or 0) - dur) if len(near) > 1 else 99.0
            if d0 <= dur_tol and (len(near) == 1 or d1 > max(2 * d0, d0 + 0.05)):
                ok[sig] = near[0]
                continue
            bad[sig] = ("two or more files have this modified time and a matching duration" if d0 <= dur_tol else "no file with this modified time has the same duration")
        else:
            bad[sig] = "the entry has no duration to tell files with the same modified time apart" if len(cand) > 1 else "the entry has no duration to check"
            if len(cand) == 1:
                ok[sig] = cand[0]
                bad.pop(sig, None)
    return ok, bad
