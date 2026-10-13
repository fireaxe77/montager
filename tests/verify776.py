"""V7.7.6 final verification: REAL Force New renders (CS2 and Valorant, Auto = weekly + force, default settings, the sync report ON) on a COPY of montage_data
(V7_DATA_SRC), output into a scratch folder (VERIFY_OUT; the real montage folders and the real history are not touched). For each render it prints: the file, its video / audio streams and
duration, the plan lines about transitions, the SYNC SUMMARY (kill rows found by the post-render detector) and the TRANSITION CHECK (luma spikes of the soft cuts: must be 0).
   VERIFY_OUT=C:\\scratch\\v776 python tests\\verify776.py        (VERIFY_GAMES=cs2,valorant  VERIFY_SEED=776)"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import montage as M                                                                           # noqa: E402
from songmap_v2 import planbench as PB                                                        # noqa: E402

OUT = Path(os.environ["VERIFY_OUT"])
PAIR1 = Path(r"E:\Movies\Movies 2025\Counter-strike 2\Counter-strike 2 2025.01.13 - 13.18.16.08.DVR.mp4")
PAIR2 = Path(r"E:\Movies\Movies 2025\Counter-strike 2\Counter-strike 2 2025.01.13 - 13.18.26.09.DVR.mp4")


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,duration,nb_frames", "-of", "json", str(path)], capture_output=True, text=True)
    st = json.loads(r.stdout or "{}").get("streams", [])
    return {s["codec_type"]: s for s in st}


def mean_volume(path):
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(path), "-vn", "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    import re
    m = re.search(r"mean_volume: (-?[0-9.]+) dB", r.stderr)
    mx = re.search(r"max_volume: (-?[0-9.]+) dB", r.stderr)
    return (float(m.group(1)) if m else None, float(mx.group(1)) if mx else None)


def sync_nums(lines):
    sm = next((l for l in lines if l.startswith("SYNC SUMMARY")), "")
    m = re.search(r"seen within 0.2 s: (\d+) of (\d+), within 0.5 s: (\d+) of (\d+)", sm)
    return tuple(int(x) for x in m.groups()) if m else None


def run_ref(ref, out_dir, game, paths=()):
    """tests\render776.py in its own process (ref = 'new' or a git ref): the lines of the sync report."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    r = subprocess.run([sys.executable, str(HERE / "render776.py"), ref, str(out_dir), game, *map(str, paths)], capture_output=True, text=True, encoding="utf-8", env=env)
    return [l for l in r.stdout.splitlines() if not l.startswith("Scanning")]


def base_module(dst):
    import importlib.util
    r = subprocess.run(["git", "show", "V7.7.5:montage.py"], cwd=ROOT, capture_output=True)
    d = OUT / "base_V775"
    d.mkdir(parents=True, exist_ok=True)
    (d / "montage.py").write_bytes(r.stdout)
    os.environ["MONTAGER_DATA"] = str(dst)
    spec = importlib.util.spec_from_file_location("montage_base_v775", str(d / "montage.py"))
    B = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = B
    spec.loader.exec_module(B)
    return B


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    games = os.environ.get("VERIFY_GAMES", "cs2,valorant").split(",")
    seed = int(os.environ.get("VERIFY_SEED", "776"))
    fails = []
    cov = {}
    with PB.data_copy(M):
        cfg = M.load_config()
        cfg.update(output_root=str(OUT), sync_report=True)
        M.save_json(M.CONFIG_PATH, cfg)
        for game in games:
            lines = []
            keep = (M.out, M.LOGONLY)

            def tee(*x, _l=lines, _o=keep[0]):
                _l.append(" ".join(map(str, x)))
                _o(*x)
            M.out = tee
            try:
                res = M.run_job(game, "render", weekly=True, force=True, seed=seed)
            finally:
                M.out, M.LOGONLY = keep
            outs = sorted((OUT / M.GAME_DIR[game]).glob("*.mp4"), key=lambda p: p.stat().st_mtime)
            f = outs[-1] if outs else None
            print(f"\n===== {game}: {f}")
            ok = bool(f and f.exists() and f.stat().st_size > 1_000_000)
            if ok:
                st = probe(f)
                dur = float(st.get("video", {}).get("duration") or 0)
                mv = mean_volume(f)
                ok = "video" in st and "audio" in st and dur > 20 and mv[0] is not None and mv[0] > -60
                print(f"   video {st.get('video', {}).get('codec_name')} {dur:.1f} s, audio {st.get('audio', {}).get('codec_name')} mean {mv[0]} dB max {mv[1]} dB, {f.stat().st_size / 1e6:.1f} MB")
            for l in lines:
                if l.startswith(("cuts:", "SYNC SUMMARY", "TRANSITION", "  TRANSITION", "KILL WINDOW", "CUT LIST CHECK", "rendered", "QUALITY CHECK", "songs:")) or "NOT PLACED" in l:
                    print("   " + l[:240])
            tc = next((l for l in lines if l.startswith("TRANSITION CHECK")), "")
            sm = next((l for l in lines if l.startswith("SYNC SUMMARY")), "")
            spikes_ok = "0 luma spikes" in tc
            print(f"   {'ok  ' if ok else 'FAIL'} finished with video + audio;  {'ok  ' if spikes_ok else 'FAIL'} {tc or 'no transition check'}")
            if not ok:
                fails.append(f"{game}: no finished video with audio")
            if not spikes_ok:
                fails.append(f"{game}: {tc or 'no transition check'}")
            print(f"   {sm}")
            cov[game] = sync_nums(lines)
    if "cs2" in cov and cov["cs2"]:                    # V7.7.5 and V7.7.6 render the SAME plan (same data, seed 776) in separate processes: the sync coverage must be no worse
        cb = sync_nums(run_ref("V7.7.5", OUT / "base", "cs2"))
        print(f"   CS2 sync coverage: V7.7.5 {cb}  V7.7.6 {cov['cs2']}  (seen within 0.2 s of N, within 0.5 s of N)")
        good = bool(cb) and cov["cs2"][1] >= cb[1] and cov["cs2"][2] >= cb[2]
        print(f"   {'ok  ' if good else 'FAIL'} CS2 sync coverage is no worse than V7.7.5")
        if not good:
            fails.append("cs2 sync coverage worse than V7.7.5")
    pair = [str(p) for p in (PAIR1, PAIR2) if Path(p).exists()]
    if len(pair) == 2:                                 # the two clips of the 4k bug, V7.7.5 vs V7.7.6 (frames of kill 4: tests\test_v776.py part 2; contact sheets by eye)
        lb = run_ref("V7.7.5", OUT / "pair_base", "cs2", pair)
        ln = run_ref("new", OUT / "pair_new", "cs2", pair)
        print("\n===== the 4k pair (13.18.16 + 13.18.26)")
        for tag, ls in (("V7.7.5", lb), ("V7.7.6", ln)):
            print(f"   {tag}: " + next((l for l in ls if l.startswith("SYNC SUMMARY")), "no sync summary"))
        nb, nn = sync_nums(lb), sync_nums(ln)
        ok4 = bool(nn) and bool(nb) and nn[2] >= nb[2] and nn[3] >= 4 and not any("KILL WINDOW" in l for l in ln)
        print(f"   {'ok  ' if ok4 else 'FAIL'} 4k pair: {nn[2] if nn else '?'} of {nn[3] if nn else '?'} rows seen (V7.7.5: {nb[2] if nb else '?'}), no kill-window failure")
        if not ok4:
            fails.append("the 4k pair is worse than V7.7.5")
    print("\nALL OK" if not fails else "FAILED: " + "; ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
