"""V7.7.5 final verification: REAL Force New renders (CS2 and Valorant, Auto = weekly + force, default settings, the sync report ON) on a COPY of montage_data
(V7_DATA_SRC), output into a scratch folder (VERIFY_OUT; the real montage folders and the real history are not touched). For each render it prints: the file, its video / audio streams and
duration, the plan lines about transitions, the SYNC SUMMARY (kill rows found by the post-render detector) and the TRANSITION CHECK (luma spikes of the soft cuts: must be 0).
   VERIFY_OUT=C:\\scratch\\v775 python tests\\verify775.py        (VERIFY_GAMES=cs2,valorant  VERIFY_SEED=775)"""
import json
import os
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


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    games = os.environ.get("VERIFY_GAMES", "cs2,valorant").split(",")
    seed = int(os.environ.get("VERIFY_SEED", "775"))
    fails = []
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
    print("\nALL OK" if not fails else "FAILED: " + "; ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
