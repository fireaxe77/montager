"""V7 plan-level test harness (read-only, nothing here is used by the app). Runs the EXISTING planner (`make_plan`, the real dry planner, no render) on a
pinned set of takes with a pinned song, once per song-map mode, and measures where the planned kills land against an INDEPENDENT low-band kick
detector (bench.py) on the render-timebase audio. Works on a COPY of montage_data."""
import contextlib
import os
import random
import shutil
import tempfile
from pathlib import Path

import numpy as np

from . import bench

VAL_DIR = Path("E:/Movies/VALORANT/Clips")
CS2_TRIO_DIR = Path("E:/Movies/LEGACY/Counter-strike 2")
VAL7 = [VAL_DIR / f"VALORANT 2026-10-07 {k}.mov" for k in ("03-19", "03-21", "03-31-12", "03-31-20", "03-35-20", "03-40-15", "03-40-20")]
CS2_TRIO_NAMES = [f"Counter-strike 2 2025.02.04 - 09.46.{n}.DVR.mp4" for n in ("13.09", "20.10", "26.11")]
N_SINGLES = 15
HERE = Path(__file__).resolve().parent.parent


@contextlib.contextmanager
def data_copy(M, tmp=None):
    """montage_data copied to a temp folder (logs / plans / theme_cache left out) and every data path of montage.py pointed at it."""
    tmp = Path(tmp or tempfile.mkdtemp(prefix="v7data_"))
    dst = tmp / "data"
    src = Path(os.environ.get("V7_DATA_SRC") or M.DATA)        # V7.1: a frozen snapshot of montage_data (the real data keeps changing while the Montager app runs)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("logs", "plans", "theme_cache"))
    M.save_json(dst / "clip_overrides.json", {})
    old = M.use_data_dir(dst)
    env_old = os.environ.get("MONTAGER_DATA")
    os.environ["MONTAGER_DATA"] = str(dst)              # sub-processes (sidecar builders) import montage fresh and must see the copy too
    try:
        yield dst
    finally:
        if env_old is None:
            os.environ.pop("MONTAGER_DATA", None)
        else:
            os.environ["MONTAGER_DATA"] = env_old
        M.restore_data_dir(old)
        shutil.rmtree(tmp, ignore_errors=True)


def cs2_sets(M):
    """(trio paths, [15 single-kill clips spread over the cached CS2 clips, deterministic])."""
    cfg = M.load_config()
    keep = (M.out, M.LOGONLY)
    M.out = M.LOGONLY = lambda *x: None
    try:
        pool = M.game_pool(cfg, "cs2")[0]
    finally:
        M.out, M.LOGONLY = keep
    trio = [CS2_TRIO_DIR / n for n in CS2_TRIO_NAMES]
    singles = sorted(str(i["rec"]["path"]) for i in pool if len(i["kills"]) == 1 and Path(i["rec"]["path"]).name not in CS2_TRIO_NAMES)
    step = max(1, len(singles) // N_SINGLES)
    return [str(p) for p in trio], singles[::step][:N_SINGLES]


def take_sets(M):
    trio, singles = cs2_sets(M)
    return {"val7": ("valorant", [str(p) for p in VAL7]), "cs2trio": ("cs2", trio), "cs2singles": ("cs2", singles)}


def run_plan(M, game, paths, song_path, mode, seed=1):
    """The real make_plan with the song pinned and the map mode forced (v1 / v2 / v2auto) through the dispatcher's own switch."""
    lines = []
    keep = (M.out, M.LOGONLY, M.songmap_version)
    M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
    M.songmap_version = lambda cfg=None: mode
    try:
        plan, _ = M.make_plan(M.load_config(), game, [str(p) for p in paths], song_path=song_path, seed=seed)
    finally:
        M.out, M.LOGONLY, M.songmap_version = keep
    return plan, lines


def kill_times(plan):
    """[(song_time, role, n_in_take)] role = 'first' (first kill of a take) / 'last' (last kill of a multikill take)."""
    s0 = float(plan["song"]["start_t"])
    res = []
    for t in plan["takes"]:
        ks = t.get("kills_out") or []
        if not ks:
            continue
        base = s0 + float(t["out_start"])
        res.append((base + float(ks[0]), "first", int(t["n"]), t))
        if len(ks) > 1:
            res.append((base + float(ks[-1]), "last", int(t["n"]), t))
    return res


def indep_drops(y, sr, n=3):
    """Independent drop finder: the biggest rises of the 2 s-smoothed low-band level (mean of the next 6 s minus the mean of the previous 6 s)."""
    b = bench.lowband(np.asarray(y, np.float64), sr)
    hop = int(0.5 * sr)
    from scipy.ndimage import uniform_filter1d
    r = np.sqrt(uniform_filter1d(b * b, hop, mode="nearest"))[::hop]
    k = 12
    if len(r) < 2 * k + 2:
        return []
    jump = np.array([r[i:i + k].mean() - r[max(0, i - k):i].mean() for i in range(len(r))])
    order = np.argsort(-jump)
    picks = []
    for i in order:
        if jump[i] <= 0.15 * jump.max():
            break
        if all(abs(i - j) * 0.5 > 10 for j in picks):
            picks.append(int(i))
        if len(picks) >= n:
            break
    return sorted(float(i * 0.5) for i in picks)


def chance_stats(kicks, dur, n=4000, seed=7):
    rnd = np.random.default_rng(seed)
    t = rnd.uniform(0, dur, n)
    d = np.abs(bench.nearest(t, kicks)) * 1000
    return {"median_ms": round(float(np.median(d)), 1), "within30": round(float(np.mean(d <= 30)), 3)}


def measure(plan, kicks, drops):
    """Per-plan numbers: distance of every beat-placed kill to the nearest independent kick, takes / events placed, headline multikill vs drop."""
    kt = kill_times(plan)
    d = np.array([abs(float(bench.nearest([t], kicks)[0])) * 1000 for t, _, _, _ in kt]) if len(kicks) else np.array([])
    best = max((x for x in kt if x[1] == "first"), key=lambda x: x[2], default=None)
    beat = None
    if plan.get("beats_out") and len(plan["beats_out"]) > 2:
        beat = float(np.median(np.diff(plan["beats_out"])))
    drop_d = None
    if best is not None and best[2] >= 2 and len(drops):
        drop_d = float(np.min(np.abs(np.asarray(drops) - best[0])))
    return {"n_pts": int(len(d)), "dists": [round(float(x), 1) for x in d], "takes": len(plan["takes"]),
            "events": int(sum(int(t["n"]) for t in plan["takes"])), "kills": int(sum(len(t.get("kills_out") or []) for t in plan["takes"])),
            "best_n": None if best is None else best[2], "best_vs_drop_s": None if drop_d is None else round(drop_d, 2), "beat_s": beat,
            "song_start": float(plan["song"]["start_t"])}


def summarize(dists):
    a = np.asarray(dists, float)
    if not len(a):
        return {"n": 0, "median_ms": None, "p95_ms": None, "within30": None}
    return {"n": int(len(a)), "median_ms": round(float(np.median(a)), 1), "p95_ms": round(float(np.percentile(a, 95)), 1), "within30": round(float(np.mean(a <= 30)), 3)}
