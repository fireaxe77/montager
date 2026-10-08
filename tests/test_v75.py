"""V7.5 tests: (A) CS2 kill time = the row's first visible frame (cs2_kill_times_earlier), (B) headline finisher on the kick when the map drop is off the beat grid
(head_kick_time / headline_on_kick). (1) item A (shipped OFF, switch CS2_DATING_ON) before / after on the diagnosed clips and an impact scan (kill counts never change, untouched clips identical),
(2) item B synthetic rules + the pinned Три дня дождя selection vs the V7.4.9 tag (only the headline take differs; Silicon XX / Beautiful Now identical),
(3) guards: 50+50 generated clips, the 7 real Valorant clips, the 4K.
Runs on a COPY of montage_data.   python tests\\test_v75.py"""
import json
import os
import subprocess
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
SONG = "E:/CLAUDECODE/Songs/Молодость моя - Три дня дождя.mp3"
SONGS_CTRL = ["Silicon XX - S3RL, Nikolett.mp3", "Beautiful Now - Zedd, Jon Bellion.mp3"]
PLAN_JSON = next(iter(Path("E:/Movies/Montages/Valorant/logs").glob("*V7.4.9_2026-10-08.plan.json")), None)
FULL = bool(os.environ.get("V75_FULL_SCAN"))          # the full impact scan (cs2_dating_scan.txt, ~5 min) is run by hand
UNTOUCHED = ["09.46.13", "09.46.20", "09.46.26", "2026.02.12 - 20.19.37", "2026.02.12 - 20.19.40", "2026.02.12 - 20.19.42", "2025.02.08 - 19.48.57.15.DVR_1.mp4",
             "2026.02.23 - 18.50.59.07", "Replay 2026-06-21 23-24-16", "2025.02.05 - 07.04.22.03"]


def scan(dst):
    old = M.use_data_dir(dst)
    try:
        cfg = M.load_config()
        det = M.Detector("cs2")
        store = M.load_kills_cache()
        res = {}
        for r in M._cs2_recs(cfg, only_scanned=True, det=det):
            e = store.get(M.kills_key(r, "cs2", det))
            if not e or e.get("error"):
                continue
            if not FULL and not any(k in Path(r["path"]).name for k in UNTOUCHED + ["21-26-38", "19.24.00.20", "19-20-52"]):
                continue
            M.CS2_DATING_ON[0] = False
            b0 = M.analyse_clip_entry(r, e, cfg, "cs2")
            M.CS2_DATING_ON[0] = True
            b1 = M.analyse_clip_entry(r, e, cfg, "cs2")
            res[Path(r["path"]).name] = ([round(k["t"], 2) for k in b0["kills"]], [round(k["t"], 2) for k in b1["kills"]])
        return res
    finally:
        M.CS2_DATING_ON[0] = False
        M.restore_data_dir(old)


def part_a(dst):
    with section("1) item A: CS2 kill time = row appearance (impact scan over all cached CS2 clips)"):
        res = scan(dst)
        check(M.CS2_DATING_ON[0] is False, "item A ships OFF (moved times in 2026.02.12 - 19.24.00.20 not confirmed on frames; impact scan in cs2_dating_scan.txt)")
        check(len(res) > (400 if FULL else 8), f"{len(res)} cached CS2 clips scanned")
        check(all(len(v[0]) == len(v[1]) for v in res.values()), "kill count identical in every clip")
        check(all(b <= a + 1e-6 and a - b <= M.CS2_DATING_MAX_S + 1e-6 for v in res.values() for a, b in zip(*v)), "times only move earlier, never more than 2.0 s")
        c = res.get("Replay 2026-04-10 21-26-38.mov")
        check(c and abs(c[0][0] - 19.6) < 0.02 and abs(c[1][0] - 18.13) < 0.12, f"Replay 2026-04-10 21-26-38: {c}")
        for k in UNTOUCHED:
            hit = [n for n in res if k in n]
            check(hit and all(res[n][0] == res[n][1] for n in hit), f"{k}: unchanged ({len(hit)} clip(s))")


def part_b_synth():
    with section("2a) item B rules (synthetic)"):
        import numpy as np
        bt = np.arange(0, 200, 0.6)
        drops_off = [{"beat": 183, "t": 110.11}]
        drops_on = [{"beat": 183, "t": 109.84}]
        real = M.song_kicks
        try:
            M.song_kicks = lambda p: [109.761, 110.016, 110.364]
            check(M.head_kick_time("x", bt, 183, drops_off) == 110.016, "off-grid map drop with a kick within 0.15 s: anchored on the kick")
            check(M.head_kick_time("x", bt, 183, drops_on) is None, "map drop on the grid: today's behaviour")
            M.song_kicks = lambda p: [109.3, 110.6]
            check(M.head_kick_time("x", bt, 183, drops_off) is None, "no kick within 0.15 s: today's behaviour")
            M.song_kicks = lambda p: [110.016]
            M.HEAD_KICK_ON[0] = False
            check(M.head_kick_time("x", bt, 183, drops_off) is None, "switch off: today's behaviour")
            M.HEAD_KICK_ON[0] = True
        finally:
            M.song_kicks = real
            M.HEAD_KICK_ON[0] = True
        plan = {"total_frames": 600, "duration": 10.0, "song": {"start_t": 100.0, "drop_t": 9.813}, "drop_anchor": {"anchor": "first", "drop_t": 109.813},
                "takes": [{"role": "headline", "kills": [5.0, 12.0], "kills_out": [2.4, 3.9], "rows_out": [2.5, 4.1], "slow_at": 3.9, "out_start": 7.413, "srcs": [{"dur": 30.0}],
                           "segs": [[3.0, 6.0, 1.0, 180, 0], [11.1, 12.0, 1.0, 54, 0], [12.0, 12.45, 0.5, 54, 0]]},
                          {"role": "drop", "kills": [1.0], "kills_out": [1.0], "rows_out": [1.1], "out_start": 0.0, "srcs": [{"dur": 9}], "segs": [[0.0, 2.0, 1.0, 120, 0]]}]}
        before = json.dumps(plan["takes"][1])
        notes = []
        ok = M.headline_on_kick(plan, 110.016, notes)
        h = plan["takes"][0]
        check(ok and abs(100.0 + h["out_start"] + h["kills_out"][0] - 110.016) < 0.03, f"finisher within 30 ms of the kick: {100.0 + h['out_start'] + h['kills_out'][0]:.3f}")
        check(sum(s[3] for s in h["segs"]) == 288 and abs(h["kills_out"][1] - 4.1) < 1e-6, "take length unchanged, later kill moves with it")
        check(json.dumps(plan["takes"][1]) == before and notes == ["headline anchored on kick: 110.016"], "other take byte-identical, note logged")


def run_plan_proc(root, data, song, seed, outp):
    env = dict(os.environ, PYTHONHASHSEED="0", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    code = ("import sys, json; sys.path.insert(0, sys.argv[1]); import montage as M; M.use_data_dir(sys.argv[2]); pj = json.load(open(sys.argv[3], encoding='utf-8')); "
            "L = []; M.out = M.LOGONLY = lambda *x: L.append(' '.join(map(str, x))); M.songmap_version = lambda cfg=None: 'v2'; "
            "plan, _ = M.make_plan(M.load_config(), 'valorant', [t['path'] for t in pj['takes']], song_path=sys.argv[4], seed=int(sys.argv[5])); "
            "json.dump(plan, open(sys.argv[6], 'w', encoding='utf-8'), default=str, ensure_ascii=False)")
    subprocess.run([sys.executable, "-W", "ignore", "-c", code, str(root), str(data), str(PLAN_JSON), song, str(seed), str(outp)], check=True, env=env, capture_output=True)
    return json.load(open(outp, encoding="utf-8"))


def part_b_real(dst, tmp):
    with section("2b) item B pinned selection vs the V7.4.9 tag"):
        if PLAN_JSON is None:
            check(False, "V7.4.9 Valorant plan json not found")
            return
        base = tmp / "base"
        base.mkdir()
        import io
        import tarfile
        raw = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", "refs/tags/V7.4.9"], check=True, capture_output=True).stdout
        tarfile.open(fileobj=io.BytesIO(raw)).extractall(base)
        keys = ("path", "segs", "out_start", "dur", "kills", "kills_out", "rows_out", "slow_at", "f0", "nf", "role")
        for i, sg in enumerate([SONG] + [f"E:/CLAUDECODE/Songs/{n}" for n in SONGS_CTRL]):
            d0, d1 = tmp / f"d0_{i}", tmp / f"d1_{i}"
            import shutil
            shutil.copytree(dst, d0)
            shutil.copytree(dst, d1)
            a = run_plan_proc(base, d0, sg, 507012, tmp / f"a{i}.json")
            b = run_plan_proc(ROOT, d1, sg, 507012, tmp / f"b{i}.json")
            diff = [j for j, (x, y) in enumerate(zip(a["takes"], b["takes"])) if any(x.get(k) != y.get(k) for k in keys)]
            if i == 0:
                hi = [j for j, t in enumerate(b["takes"]) if t["role"] == "headline"]
                h = b["takes"][hi[0]]
                fin = b["song"]["start_t"] + h["out_start"] + h["kills_out"][0 if (b.get("drop_anchor") or {}).get("anchor") != "last" else -1]
                check(diff == hi and len(a["takes"]) == len(b["takes"]), f"only the headline take differs (takes {diff})")
                check(abs(fin - 110.016) <= 0.03, f"finisher at {fin:.3f}, kick 110.016")
                check(any("headline anchored on kick" in n for n in b["notes"]), "log line 'headline anchored on kick' in the plan notes")
            else:
                check(not diff and a["song"] == b["song"], f"{Path(sg).name}: unchanged")


def main():
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t75_"))
    with PB.data_copy(M) as dst:
        part_a(dst)
        part_b_synth()
        part_b_real(dst, tmp)
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
    check(M.APP_VERSION == "V7.5", "title-bar version V7.5")
    print(f"total test time {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}): " + "; ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
