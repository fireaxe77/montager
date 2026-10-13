"""V7.7.1 final verification: three REAL renders on a COPY of montage_data (V7_DATA_SRC), output into a scratch folder (VERIFY_OUT):
  CS2 and Valorant with the music option ON at the default 12 dB, and a flagged clip at mute. Prints the plan lines about music, the output files and their audio levels."""
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
FLAG = {"cs2": r"E:\Movies\LEGACY\Counter-strike 2\Counter-strike 2 2025.02.11 - 20.13.01.05.DVR.mp4",
        "valorant": r"E:\Movies\VALORANT\Clips\Replay 2026-10-01 15-24-21.mov"}


def main():
    with PB.data_copy(M):
        cfg = M.load_config()
        cfg.update(output_root=str(OUT), lower_music_clips=True, music_lower_db=12, sync_report=False)
        M.save_json(M.CONFIG_PATH, cfg)
        song = next(x["path"] for x in M.song_pool(M.load_config())[0] if "Silicon XX" in str(x["path"]))
        sets = PB.take_sets(M)
        jobs = [("cs2", 12, "cs2_12dB"), ("valorant", 12, "valorant_12dB"), ("cs2", M.MUSIC_MUTE_DB, "cs2_mute")]
        for game, amount, tag in jobs:
            base = sets["val7"][1] if game == "valorant" else sets["cs2trio"][1] + sets["cs2singles"][1][:6]
            paths = [FLAG[game]] + [p for p in base if p != FLAG[game]]
            set_ = M.load_config()
            set_["music_lower_db"] = amount
            M.save_json(M.CONFIG_PATH, set_)
            outfile = OUT / f"{tag}.mp4"
            res = M.run_job(game, "render", paths=paths, song_path=song, outfile=str(outfile), seed=1)
            plan_json = OUT / "logs" / (outfile.stem + ".plan.json")
            low = muted = 0
            ok = outfile.exists() and outfile.stat().st_size > 100000
            lines = []
            if plan_json.exists():
                plan = json.loads(plan_json.read_text(encoding="utf-8"))
                lines = [n for n in plan["notes"] if n.startswith("music over gameplay:") and ": yes (" in n]
                muted = sum(1 for t in plan["takes"] for s in t["srcs"] if s.get("mute"))
                low = sum(1 for t in plan["takes"] for s in t["srcs"] if s.get("music_db"))
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "compact", str(outfile)], capture_output=True, text=True)
            print(f"VERIFY {tag}: render {'OK' if ok else 'FAILED'} ({outfile.stat().st_size / 1e6:.1f} MB if exists), lowered srcs {low}, muted srcs {muted}; {r.stdout.strip()[:140]}")
            for l in lines[:3]:
                print("   " + l[:200])


if __name__ == "__main__":
    main()
