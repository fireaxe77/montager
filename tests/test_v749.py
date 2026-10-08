"""V7.4.9 tests: CS2 name-list kills the border list lacks (cs2_name_kills_kept). (1) the Replay 2026-06-21 23-24-16 case before / after and the impact scan over all
cached CS2 clips (exactly the two expected clips change, the listed clips do not), (2) synthetic rule cases (settled third row kept; pre-clip / stale / unsupported /
near-duplicate not added), (3) guards: 50+50 generated clips identical to V7.2 (headline rules off), the 7 real Valorant clips, the 4K.
Runs on a COPY of montage_data.   python tests\test_v749.py"""
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import montage as M                                                                           # noqa: E402
from songmap_v2 import planbench as PB                                                        # noqa: E402
import test_v73 as T73                                                                        # noqa: E402
from v696_common import check, section, FAILS, snapshot                                       # noqa: E402

REAL_DATA = ROOT / "montage_data"
T_ALL = time.time()

LISTED = ["09.46.13", "09.46.20", "09.46.26", "2026.02.12 - 20.19.37", "2026.02.12 - 20.19.40", "2026.02.12 - 20.19.42", "2026.02.14 - 23.16.02.02",
          "2026.02.12 - 19.24.00.20", "2025.02.08 - 19.48.57.15", "2025.01.06 - 23.13.44.05", "2026.02.23 - 18.50.59.07", "2026.02.10 - 19.09.46.22"]


def scan_all():
    cfg = M.load_config()
    det = M.Detector("cs2")
    store = M.load_kills_cache()
    res = {}
    for r in M._cs2_recs(cfg, only_scanned=True, det=det):
        e = store.get(M.kills_key(r, "cs2", det))
        if not e or e.get("error"):
            continue
        M.CS2_NAMEKEEP_ON[0] = False
        b0 = M.analyse_clip_entry(r, e, cfg, "cs2")
        M.CS2_NAMEKEEP_ON[0] = True
        b1 = M.analyse_clip_entry(r, e, cfg, "cs2")
        res[Path(r["path"]).name] = ([round(k["t"], 2) for k in b0["kills"]], [round(k["t"], 2) for k in b1["kills"]])
    return res


def part_real(dst):
    with section("1) the 23-24-16 case and the impact scan over all cached CS2 clips"):
        old = M.use_data_dir(dst)
        try:
            res = scan_all()
        finally:
            M.restore_data_dir(old)
        ch = {k: v for k, v in res.items() if v[0] != v[1]}
        check(len(res) > 400, f"{len(res)} cached CS2 clips scanned")
        c = res.get("Replay 2026-06-21 23-24-16.mov")
        check(c and len(c[0]) == 2 and len(c[1]) == 3 and abs(c[1][2] - 17.13) < 0.05, f"Replay 2026-06-21 23-24-16.mov: kills {c[0] if c else None} -> {c[1] if c else None}")
        check(set(ch) == {"Replay 2026-06-21 23-24-16.mov", "Counter-strike 2 2025.01.11 - 20.45.28.10.DVR.mp4"}, f"exactly the 2 expected clips change: {sorted(ch)}")
        listed = [k for k in res if any(x in k for x in LISTED)]
        check(len(listed) >= 8 and all(res[k][0] == res[k][1] for k in listed), f"{len(listed)} listed / confirmed clips unchanged")
        check(all(len(v[1]) == len(v[0]) + 1 for v in ch.values()) and all(v[1][:0] == [] and all(t in v[1] for t in v[0]) for v in ch.values()),
              "every border kill kept at its time; one kill added per changed clip (both confirmed visible on frames: Dron / Szantosz / GhOst row at 17.1 s, '_SeX_' row at 10.5 s)")


def part_synth():
    with section("2) synthetic rule cases (cs2_name_kills_kept)"):
        def kill(t, v="Alpha", ks=0.9, hits=5):
            return {"t": t, "victim": v, "ks": ks, "hits": hits, "row": "", "hs": False, "weapon": "gun", "box": None, "t_last": t + 1, "needs_shot": False}

        def trk(first, hits=20, y0=119, h=32):
            return {"id": 9, "first": first, "last": first + 60, "hits": hits, "best_rect": {"x0": 250, "y0": y0, "x1": 528, "y1": y0 + h}, "slots": [[first, y0, 2]],
                    "x0": 250, "x1": 528, "y0": y0, "y1": y0 + h}
        sc = lambda tracks: {"v_off": 0.0, "fps": 30, "frames": 600, "tracks": tracks}
        real = M.border_shape_filter
        try:
            M.border_shape_filter = lambda tracks, n: ([], list(tracks))              # every track is a (shape-valid) blob: the row-spacing filter dropped it
            B = lambda ks, rej=(): {"kills": list(ks), "rows": [], "rej": list(rej)}
            A = lambda *ks: {"kills": list(ks)}
            one = M.cs2_name_kills_kept(A(kill(12.0), kill(15.0), kill(17.1)), B([kill(12.0), kill(15.0)]), sc([trk(int(17.1 * 30))]), "x")
            check(len(one) == 1 and abs(one[0]["t"] - 17.1) < 1e-6, "settled third row dropped by the border list: kept")
            check(not M.cs2_name_kills_kept(A(kill(12.0), kill(15.0), kill(17.1)), B([kill(12.0), kill(15.0)]), sc([]), "x"), "no outlined track at that time: not added")
            check(not M.cs2_name_kills_kept(A(kill(12.0), kill(15.0), kill(17.1, ks=0.5)), B([kill(12.0), kill(15.0)]), sc([trk(int(17.1 * 30))]), "x"), "unstable name read: not added")
            check(not M.cs2_name_kills_kept(A(kill(12.0), kill(15.0), kill(17.1, hits=1)), B([kill(12.0), kill(15.0)]), sc([trk(int(17.1 * 30))]), "x"), "single read: not added")
            check(not M.cs2_name_kills_kept(A(kill(0.9), kill(12.0), kill(15.0)), B([kill(12.0), kill(15.0)]), sc([trk(int(0.9 * 30))]), "x"), "pre-clip row (first 1.6 s): not added")
            check(not M.cs2_name_kills_kept(A(kill(6.0), kill(12.0), kill(15.0)), B([kill(12.0), kill(15.0)], [{"t": 0.2, "reason": "pre-clip: row already on screen"}]), sc([trk(int(6.0 * 30))]), "x"),
                  "stale row (a pre-clip row in the clip, kill in its first 10 s): not added")
            check(not M.cs2_name_kills_kept(A(kill(12.0), kill(15.0), kill(15.6)), B([kill(12.0), kill(15.0)]), sc([trk(int(15.6 * 30))]), "x"), "within 1.0 s of a kept kill (duplicate): not added")
            check(not M.cs2_name_kills_kept(A(kill(12.0), kill(15.0), kill(17.1)), B([kill(12.0), kill(15.0)], [{"t": 17.0, "reason": "suspicious side read"}]), sc([trk(int(17.1 * 30))]), "x"),
                  "the border analysis classified a row there (rejected): not added")
            check(not M.cs2_name_kills_kept(A(kill(12.0), kill(15.0)), B([kill(12.0), kill(15.0), kill(17.1)]), sc([trk(int(17.1 * 30))]), "x"), "border list not shorter: nothing added")
        finally:
            M.border_shape_filter = real


def main():
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t749_"))
    with PB.data_copy(M) as dst:
        part_real(dst)
        part_synth()
        old = M.use_data_dir(tmp / "data")
        try:
            T73.BASE_REF = "V7.2-good"
            B2 = T73.load_base(tmp)
            check(B2 is not None, "V7.2 baseline planner loaded")
            B2.use_data_dir(tmp / "data_b")
            T73.part_guards(tmp, B2)
        finally:
            M.restore_data_dir(old)
        T73.part_util_real(tmp, B2, dst)
    T73.part_real_untouched(before)
    check(M.APP_VERSION == "V7.4.9", "title-bar version V7.4.9")
    print(f"total test time {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}): " + "; ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
