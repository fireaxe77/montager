"""V9.5.5: PUBLISHED montages. The clips of a montage that was uploaded and made public are moved out of every scanned folder and are never used again
(stronger than the normal 'used' flag).

Records: when a montage finishes rendering, `save_record` keeps (output file, game, song, date, the clip files actually in its final cut list, every file of
a stitched take included) in montage_data\\montage_records.json. For older montages `find_record` rebuilds the same list from the montage's .plan.json (complete),
else from the CUT LIST printed in montage.log right before its 'rendered <file>' line (file NAMES only: resolved against the clip library, stitched takes list only their first file).

`preview` changes nothing. `apply` MOVES the clip files into <published folder>\\<game>\\ (never overwrites: a taken name gets ' (2)', ' (3)'), keeps a record of every move
(montage_data\\published.json) and writes montage_data\\logs\\published.log. `unmark` moves them back to the original paths. `excluded` is what the clip scan and the pools use.
Nothing here touches the clip analysis caches (the kill / clip caches stay as they are, so a moved clip needs no new analysis when it comes back)."""
import json
import os
import re
import shutil
import time
from pathlib import Path

REC_FILE = "montage_records.json"
PUB_FILE = "published.json"
LOG_NAME = "published.log"
_CUT_ROW = re.compile(r"^\s*\d+\.\s+[\d.]+s\s+\d+f\s+\[.*?\].*?\stail\s+[\d.]+s\s+\d+k\s+(.+?)\s+@\s+\d+:\d")
_RENDERED = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d rendered (.+?)(?: \(\d+(?:\.\d+)? s = plan .*)?$")


def norm(p):
    return os.path.normcase(os.path.normpath(str(p)))


def _load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def log_line(data, text):
    p = Path(data) / "logs" / LOG_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")


# ------------------------------------------------------------------------------------------------------------------ records
def plan_clips(plan):
    """The clip files a plan really places: every take's file and every file of a stitched take (not clips that were only ticked / ranked)."""
    s = set()
    for t in plan.get("takes") or []:
        if t.get("path"):
            s.add(t["path"])
        for x in t.get("srcs") or []:
            if x.get("path"):
                s.add(x["path"])
    return sorted(s)


def record_of_plan(plan, video, source="render"):
    song = plan.get("song") or {}
    return {"video": str(video), "game": plan.get("game"), "song": song.get("title") or Path(song.get("path") or "").stem,
            "date": time.strftime("%Y-%m-%d"), "headline": plan.get("headline"), "clips": plan_clips(plan), "source": source,
            "plan_s": round(sum(float(t.get("dur") or t.get("len") or 0) for t in plan.get("takes") or []), 2) or None}


def save_record(data, plan, video):
    """At the end of a render: one small record per montage (called after the used flags are saved)."""
    recs = _load(Path(data) / REC_FILE, {})
    recs[norm(video)] = record_of_plan(plan, video)
    _save(Path(data) / REC_FILE, recs)


def _log_files(data):
    d = Path(data) / "logs"
    return sorted(d.glob("montage.log*"), key=lambda p: p.stat().st_mtime) if d.is_dir() else []


def parse_log_cutlist(log_path, video):
    """(names of the last CUT LIST block printed before the 'rendered <video>' line, the line's text) or None. Streams the log (it is large)."""
    want, stem = norm(video), Path(video).stem.lower()
    block, cur, found = [], None, None
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if line.startswith("CUT LIST ("):
                    cur = []
                    continue
                if cur is not None:
                    m = _CUT_ROW.match(line)
                    if m:
                        cur.append(m.group(1).strip())
                        continue
                    if cur:
                        block, cur = cur, None
                    elif not line.startswith("   "):
                        cur = None
                m = _RENDERED.match(line)
                if m and (norm(m.group(1)) == want or Path(m.group(1)).stem.lower() == stem):
                    found = (list(block), line)
    except OSError:
        return None
    return found


def resolve_names(names, clip_paths, game_hint=None):
    """Clip file names -> full paths from the clip library list. A name that exists twice is left unresolved (never a guess). Returns (paths, unresolved names)."""
    by = {}
    for p in clip_paths:
        by.setdefault(os.path.basename(p).lower(), []).append(p)
    got, bad = [], []
    for n in dict.fromkeys(names):
        c = by.get(n.lower(), [])
        (got if len(c) == 1 else bad).append(c[0] if len(c) == 1 else n)
    return sorted(set(got)), bad


def find_record(data, video, clip_paths=(), game_dirs=None):
    """The record of a montage video: the saved record, else its .plan.json, else the CUT LIST in montage.log. None when nothing is found."""
    data, video = Path(data), Path(video)
    recs = _load(data / REC_FILE, {})
    r = recs.get(norm(video)) or next((v for v in recs.values() if Path(v["video"]).stem.lower() == video.stem.lower()), None)
    if r:
        return dict(r, found_by="saved record")
    pj = next((q for q in (video.parent / "logs" / (video.stem + ".plan.json"), video.with_suffix(".plan.json")) if q.exists()), None)
    if pj:
        plan = _load(pj, None)
        if plan and plan.get("takes"):
            return dict(record_of_plan(plan, video, "plan.json"), date=time.strftime("%Y-%m-%d", time.localtime(pj.stat().st_mtime)), found_by=f"plan file {pj.name}")
    for lg in reversed(_log_files(data)):
        got = parse_log_cutlist(lg, video)
        if got and got[0]:
            names, line = got
            paths, bad = resolve_names(names, clip_paths)
            return {"video": str(video), "game": None, "song": "", "date": line[:10], "clips": paths, "unresolved": bad, "source": "montage.log",
                    "found_by": f"CUT LIST in {lg.name} (file names only; a stitched take lists its first file only)"}
    return None


# ------------------------------------------------------------------------------------------------------------------ published store
def store(data):
    s = _load(Path(data) / PUB_FILE, {})
    s.setdefault("montages", {})
    return s


_EX = {}


def excluded(data):
    """(set of normalised original paths, set of 'file name|size' keys) of every published clip that is moved away (and not restored). Read once per change of the file."""
    p = Path(data) / PUB_FILE
    try:
        st = p.stat()
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        return set(), set()
    c = _EX.get(str(p))
    if c and c[0] == sig:
        return c[1], c[2]
    paths, keys = set(), set()
    for m in store(data)["montages"].values():
        for mv in m.get("moves", []):
            paths.add(norm(mv["orig"]))
            keys.add(f"{os.path.basename(mv['orig']).lower()}|{mv.get('size', 0)}")
    _EX[str(p)] = (sig, paths, keys)
    return paths, keys


def is_published(data, path, size=None):
    paths, keys = excluded(data)
    if not paths:
        return False
    if norm(path) in paths:
        return True
    try:
        sz = size if size is not None else os.path.getsize(path)
    except OSError:
        return False
    return f"{os.path.basename(path).lower()}|{sz}" in keys


def keep_cache_keys(data):
    """Originals of published clips: their scan-cache entries are kept when the clip cache is cleaned of vanished files (so Unmark needs no new analysis)."""
    return excluded(data)[0]


def _dest(root, game_dir, path):
    d = Path(root) / game_dir
    d.mkdir(parents=True, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(path))
    dest, n = d / (stem + ext), 2
    while dest.exists():
        dest = d / f"{stem} ({n}){ext}"
        n += 1
    return str(dest)


def preview(data, rec, root, game_dirs):
    """Changes nothing. Returns {'moves': [(orig, planned dest)], 'missing': [...], 'already': [...], 'unresolved': [...]}."""
    gd = game_dirs.get(rec.get("game"), rec.get("game") or "Other")
    pub_paths, _k = excluded(data)
    res = {"moves": [], "missing": [], "already": [], "unresolved": list(rec.get("unresolved") or []), "game_dir": gd}
    for c in rec.get("clips", []):
        if norm(c) in pub_paths:
            res["already"].append(c)
        elif not os.path.isfile(c):
            res["missing"].append(c)
        else:
            res["moves"].append((c, str(Path(root) / gd / os.path.basename(c))))
    return res


def apply(data, rec, root, game_dirs):
    """MOVES the clip files of the record (never overwrites, never deletes) and records every move. Returns {'moved': [(orig, new)], 'failed': [(orig, why)], ...}."""
    pv = preview(data, rec, root, game_dirs)
    key = norm(rec["video"])
    s = store(data)
    ent = s["montages"].setdefault(key, {"video": rec["video"], "game": rec.get("game"), "song": rec.get("song"), "date": time.strftime("%Y-%m-%d %H:%M:%S"), "moves": []})
    moved, failed = [], []
    for orig, _plan_dest in pv["moves"]:
        try:
            size = os.path.getsize(orig)
            dest = _dest(root, pv["game_dir"], orig)
            shutil.move(orig, dest)
        except Exception as ex:                                            # noqa: BLE001
            failed.append((orig, f"{type(ex).__name__}: {ex}"))
            log_line(data, f"APPLY FAILED {orig}: {ex}")
            continue
        ent["moves"].append({"orig": orig, "new": dest, "size": size})
        moved.append((orig, dest))
        log_line(data, f"APPLY {rec['video']} | {orig} -> {dest}")
        _save(Path(data) / PUB_FILE, s)                                   # saved after every file: a crash never loses a move
    if not ent["moves"]:
        s["montages"].pop(key, None)
    _save(Path(data) / PUB_FILE, s)
    log_line(data, f"APPLY done: {rec['video']} ({rec.get('game')}): {len(moved)} moved, {len(failed)} failed, {len(pv['missing'])} missing, {len(pv['already'])} already published")
    return dict(pv, moved=moved, failed=failed)


def unmark(data, video):
    """Moves the clips of a published montage back to their original paths (a path that is taken again is NOT overwritten: that clip stays where it is and stays excluded)."""
    s = store(data)
    key = norm(video)
    ent = s["montages"].get(key) or next((v for k, v in s["montages"].items() if Path(v["video"]).stem.lower() == Path(video).stem.lower()), None)
    if not ent:
        return {"restored": [], "failed": [], "found": False}
    restored, failed, left = [], [], []
    for mv in ent["moves"]:
        if os.path.exists(mv["orig"]):
            failed.append((mv["orig"], "the original path is taken again: not overwritten"))
            left.append(mv)
        elif not os.path.isfile(mv["new"]):
            failed.append((mv["orig"], f"the moved file is not at {mv['new']}"))
            left.append(mv)
        else:
            try:
                os.makedirs(os.path.dirname(mv["orig"]), exist_ok=True)
                shutil.move(mv["new"], mv["orig"])
                restored.append((mv["new"], mv["orig"]))
                log_line(data, f"UNMARK {ent['video']} | {mv['new']} -> {mv['orig']}")
            except Exception as ex:                                        # noqa: BLE001
                failed.append((mv["orig"], f"{type(ex).__name__}: {ex}"))
                left.append(mv)
                log_line(data, f"UNMARK FAILED {mv['orig']}: {ex}")
    ent["moves"] = left
    if not left:
        for k in [k for k, v in s["montages"].items() if v is ent]:
            s["montages"].pop(k)
    _save(Path(data) / PUB_FILE, s)
    log_line(data, f"UNMARK done: {ent['video']}: {len(restored)} restored, {len(failed)} not restored")
    return {"restored": restored, "failed": failed, "found": True}


def published_list(data):
    return [(v["video"], v.get("game"), v.get("date"), len(v.get("moves", []))) for v in store(data)["montages"].values()]
