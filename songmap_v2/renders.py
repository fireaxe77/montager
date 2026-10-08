"""V7.1 side-by-side renders (never imported by the app): the SAME 7-clip Valorant manual pick (VALORANT 2026-10-07 03-19 .. 03-40-20, the 03-31-20 override ON as
in the real data) with the same seed, once with the V1 map and once with the V2 map, into E:\Movies\Montages\_songmap_test\<song>_V1.mp4 / _V2.mp4 (new files only).
The normal render path (`render_plan`) is used unchanged, interpolation off. Plans, used flags, caches: a COPY of montage_data.
    python -m songmap_v2.renders "<song fragment>" ..."""
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
OUT_DIR = Path("E:/Movies/Montages/_songmap_test")


def main(frags):
    import montage as M
    from songmap_v2 import planbench as PB
    real_ov = json.loads((HERE / "montage_data" / "clip_overrides.json").read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    res = []
    for frag in frags:
        with PB.data_copy(M):
            M.save_json(M.DATA / "clip_overrides.json", real_ov)             # the real per-clip override for 03-31-20 (data_copy blanks it)
            files = sorted(Path(M.load_config().get("mp3_dir")).glob("*.mp3"))
            f = next(p for p in files if frag.lower() in p.name.lower())
            raw = {str(x["path"]).replace("\\", "/"): str(x["path"]) for x in M.song_pool(M.load_config(), cached_only=True)[0]}
            path = raw.get(str(f).replace("\\", "/"), str(f))
            game, paths = PB.take_sets(M)["val7"]
            cfg = dict(M.load_config(), interpolate_low_fps=False, sync_report=False)
            name = re.sub(r"[^\w\- ]+", "", f.stem)[:40].strip().replace(" ", "_")
            for mode in ("v1", "v2"):
                lines = []
                keep = (M.out, M.LOGONLY, M.songmap_version)
                M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
                M.songmap_version = lambda cfg=None, m=mode: m
                try:
                    plan, _ = M.make_plan(M.load_config(), game, [str(p) for p in paths], song_path=path, seed=1)
                    outfile = OUT_DIR / f"{name}_{mode.upper()}.mp4"
                    t0 = time.time()
                    M.render_plan(plan, outfile, cfg)
                    M.sync_report(plan, outfile, dict(cfg, sync_report=True))
                finally:
                    M.out, M.LOGONLY, M.songmap_version = keep
                summ = next((l for l in lines if l.startswith("SYNC SUMMARY")), "(no SYNC SUMMARY)")
                errs = [l for l in lines if "error" in l.lower() and "SYNC" not in l][:2]
                row = f"{name}_{mode.upper()}.mp4  {time.time() - t0:.0f} s  takes {len(plan['takes'])}  {summ}" + (f"  NOTE {errs}" if errs else "")
                print(row, flush=True)
                res.append({"song": f.stem, "mode": mode, "file": str(outfile), "summary": summ, "takes": len(plan["takes"]),
                            "section": [plan["song"]["start_t"], plan["song"]["start_t"] + plan["duration"]]})
    (HERE / "compare_out" / "renders.json").write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
