"""Shared helpers of the V6.9.7 tests: generated 'game footage' whose frames depend on the ABSOLUTE time (two clips of one moment show the same
frames, two different moments never do), the 7-clip incident replica, a make_plan harness with stubbed scan / songs, the base-commit loader."""
import datetime
import json
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import numpy as np                                                                             # noqa: E402
import _run as R                                                                               # noqa: E402
import montage as M                                                                            # noqa: E402
from v696_common import check, section, FAILS, SECTIONS, snapshot, logged, REAL_DATA, silent_song   # noqa: E402,F401
import test_v693 as T                                                                          # noqa: E402

FPS = 30
BASE_DT = datetime.datetime(2026, 10, 7, 3, 40, 0)


def abs_frames(a0, n, seed=0):
    """n gray 320x180 frames starting at absolute time a0 (s): frame f = coarse random blocks seeded by the ABSOLUTE frame index."""
    for i in range(n):
        f = int(round(a0 * FPS)) + i
        r = np.random.RandomState((f * 2654435761 + seed) % (2 ** 32 - 1))
        yield np.kron(r.randint(0, 256, (18, 32)).astype(np.uint8), np.ones((10, 10), np.uint8))


def make_clip(path, a0, dur=40, seed=0, mtime=None):
    """A real small video file of the footage [a0, a0 + dur) (absolute seconds); mtime = the save time (END) like OBS leaves it."""
    n = int(dur * FPS)
    p = R.subprocess.Popen if hasattr(R, "subprocess") else None
    import subprocess
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "gray", "-s", "320x180", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "ultrafast",
           "-crf", "14", "-pix_fmt", "yuv420p", str(path)]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for fr in abs_frames(a0, n, seed):
        pr.stdin.write(fr.tobytes())
    pr.stdin.close()
    err = pr.stderr.read()
    assert pr.wait() == 0, err.decode()[-300:]
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return str(path)


def obs_minute_name(end_dt, taken):
    """OBS naming of the incident: the SAVE time down to the minute; a second save in the same minute gets ' (2)'."""
    base = f"VALORANT {end_dt:%Y-%m-%d %H-%M}"
    n = taken.get(base, 0) + 1
    taken[base] = n
    return base + (f" ({n})" if n > 1 else "") + ".mov"


def rec_of(path, dur=40.0, game="valorant"):
    return T.rec_of(path, dur, game)


def pool_item(rec, kills):
    return T.pool_item(rec, kills)


# ---- the incident: 7 clips of ~40 s, OBS save-time names (minute resolution, two '(2)' files), consecutive clips overlap in absolute time
# (start, kills [(abs time, victim)]) - names recur across rounds; the footage of one moment is the same frames in both clips.
INCIDENT = [
    (0, []),                                                                                          # c1: 0 kills
    (35, [(55.0, "kuwax")]),                                                                          # c2: the 1K
    (70, [(87.0, "kuwax"), (96.0, "lorreth"), (104.5, "mitski")]),                                    # c3: first half of the 4K
    (100, [(104.5, "mitski"), (113.0, "pandemic"), ("util", 121.0, "zephyr")]),                       # c4: second half (mitski = boundary duplicate) + 1 utility row
    (135, [(150.0, "pandemic"), (158.0, "zephyr")]),                                                  # c5: the 2K
    (170, [(198.0, "kuwax"), (207.0, "mitski")]),                                                     # c6: first half of the Ace
    (203, [(207.0, "mitski"), (214.0, "lorreth"), (221.0, "pandemic"), (228.0, "zephyr")]),           # c7: second half (mitski = boundary duplicate)
]


def build_incident(d, with_util=False, seed=0):
    """Writes the 7 clips to folder d; returns [(item, util_rows)] for the clips with kills (c1 has none). Save time = start + 40 s (END)."""
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    taken, items, names = {}, [], []
    for i, (a0, ks) in enumerate(INCIDENT):
        end_dt = BASE_DT + datetime.timedelta(seconds=a0 + 40)
        p = d / obs_minute_name(end_dt, taken)
        names.append(p.name)
        make_clip(p, a0, 40, seed, mtime=end_dt.timestamp()) if ks else (p.write_bytes(b"x"), os.utime(p, (end_dt.timestamp(),) * 2))
        if not ks:
            continue
        rows = [(k[1] - a0, k[2]) for k in ks if k[0] != "util"] if False else None
        normal = [(k[0] - a0, k[1]) for k in ks if k[0] != "util"]
        util = [(k[1] - a0, k[2]) for k in ks if k[0] == "util"]
        it = pool_item(rec_of(p, 40.0), normal)
        items.append((it, util))
    return items, names


def view_events(evs):
    return [(Path(e["path"]).name, e["n"], [round(t, 3) for t in e["times"]], list(e["victims"]), e["stitched"]) for e in evs]


def harness(mod, game, items, paths, cfg=None, plan_stub=False, song_an=None):
    """make_plan with a stubbed scan / pool / songs (the same shape as test_v69's harness); the REAL planner unless plan_stub. Returns (plan, events_seen)."""
    seen = {}
    song = {"path": "x.mp3", "title": "x", "artist": "a"}
    an = song_an or mod.default_song_map()
    stubs = dict(autodetect_dirs=lambda c: c, load_dets=lambda g=None: {game: object()}, scan_clips=lambda c: [dict(i["rec"], game=game) for i in items],
                 auto_scan_set=lambda c, g: [], run_scan=lambda *a, **k: None, hist_list=lambda *a: [],
                 game_pool=lambda c, g, ps=None: ([i for i in items if ps is None or i["rec"]["path"] in ps],
                                                  {"tagged": len(items), "scanned": len(items), "with_kills": len(items),
                                                   "audio": {"raw": 0, "no_shot": 0, "death_lock": 0, "kept": 0}}),
                 song_pool=lambda c: ([], [], ""), pick_song=lambda *a, **k: (song, an, 0, []), weekly_song_fit=lambda s, a, i, r: (s, a, i, r),
                 verify_cutlist=lambda p: [], fmt_plan=lambda *a: "")
    old = {k: getattr(mod, k) for k in stubs}
    for k, v in stubs.items():
        setattr(mod, k, v)
    try:
        plan, _ = mod.make_plan(cfg or mod.load_config(), game, paths, seed=7)
    finally:
        for k, v in old.items():
            setattr(mod, k, v)
    return plan
