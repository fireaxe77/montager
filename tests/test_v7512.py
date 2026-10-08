"""V7.5.1.2 tests (gate without denylist, every-drop anchoring, outro fade). Original V7.5.1 docstring: CS2 kill time = row appearance with the stricter same-row test (cs2_dating_walk / cs2_row_first_frame). Ships OFF (CS2_DATING_ON = [False]):
the confirmed-good clips 2026.02.12 - 19.24.00.20 and 2026.02.10 - 19.09.46.22 still get moved times that are not the row's first appearance.
(1) generated frame sets: an older row pushed down into the tracked spot must not move; a fade-in row moves to its first faint frame;
(2) real clips (switch forced on): kill counts identical, Replay 2026-04-10 21-26-38 -> ~18.0, Replay 2026-06-19 19-20-52 -> ~16.4, untouched clips unchanged, switch default off;
(3) guards: 50+50 generated clips, the 7 real Valorant clips, the 4K.
Runs on a COPY of montage_data.   python tests\test_v751.py   (full 528-clip scan: V751_FULL_SCAN=1)"""
import os
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
FULL = bool(os.environ.get("V751_FULL_SCAN"))
UNTOUCHED = ["09.46.13", "09.46.20", "09.46.26", "2026.02.12 - 20.19.37", "2026.02.12 - 20.19.40", "2026.02.12 - 20.19.42", "2026.02.14 - 23.16.02.02",
             "2025.02.08 - 19.48.57.15.DVR_1.mp4", "2026.02.23 - 18.50.59.07", "Replay 2026-06-21 23-24-16", "2025.02.05 - 07.04.22.03", "2026.02.15 - 03.09.09.06"]


def synth():
    import cv2
    import numpy as np
    H, W = 272, 534
    rng = np.random.RandomState(3)

    def bg():
        return np.clip(rng.normal(120, 6, (H, W, 3)), 0, 255).astype(np.uint8)

    def row(fr, text, y, alpha=1.0, outline=True):
        r = fr.copy()
        cv2.rectangle(r, (265, y), (528, y + 27), (40, 40, 40), -1)
        cv2.putText(r, text, (275, y + 19), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (240, 240, 240), 1, cv2.LINE_AA)
        if outline:
            cv2.rectangle(r, (265, y), (528, y + 27), (30, 40, 190), 2)
        return cv2.addWeighted(r, alpha, fr, 1 - alpha, 0)
    return H, W, bg, row


def part_synth():
    with section("1) generated frame sets (cs2_dating_walk)"):
        H, W, bg, row = synth()
        rc = {"x0": 265, "x1": 528, "y0": 60, "y1": 87}
        # (a) an older row A stands at y=60; at frame 30 a new row B arrives at y=60 and A is pushed down to y=96. B (tracked, first=40) must not walk back into A.
        fr = []
        for j in range(60):
            b = bg()
            if j < 30:
                b = row(b, "alpha  Dron", 60)
            else:
                b = row(b, "alpha  Dron", 96)
                b = row(b, "fireaxe  Szantosz", 60)
            fr.append(b)
        j = M.cs2_dating_walk(fr, rc, 40, 30)
        check(j == M.CS2_GATE_REJECT or j is None, f"older row pushed down into the tracked spot: the gate rejects ({j})")
        # (b) the same row but with the old row gone: appears with a 3-frame fade-in (alpha .3 / .6 / .85)
        fr = []
        for j in range(60):
            b = bg()
            if j >= 33:
                b = row(b, "fireaxe  Szantosz", 60)
            elif j >= 30:
                b = row(b, "fireaxe  Szantosz", 60, alpha=(0.3, 0.6, 0.85)[j - 30])
            fr.append(b)
        j = M.cs2_dating_walk(fr, rc, 40, 30)
        check(j in (30, 31, 32), f"fade-in row: moves to its first faint frame with the outline in the mask ({j})")
        # (c) a row that is there from the start of the window is not moved
        fr = [row(bg(), "fireaxe  Szantosz", 60) for _ in range(60)]
        check(M.cs2_dating_walk(fr, rc, 40, 30) is None, "row on screen at the window start: not moved")
        fr = []
        for j in range(60):
            b = bg()
            b = row(b, "fireaxe  Szantosz" if j >= 30 else "fireaxe  Szantosx 7", 60)
            fr.append(b)
        j = M.cs2_dating_walk(fr, rc, 40, 30)
        check(j == M.CS2_GATE_REJECT or j is None, f"row still visible before the walk end: rejected ({j})")


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
            nm = Path(r["path"]).name
            if not FULL and not any(k in nm for k in UNTOUCHED + ["21-26-38", "19-20-52", "2026.02.12 - 19.24.00.20", "2026.02.10 - 19.09.46.22"]):
                continue
            M.CS2_DATING_ON[0] = False
            b0 = M.analyse_clip_entry(r, e, cfg, "cs2")
            M.CS2_DATING_ON[0] = True
            b1 = M.analyse_clip_entry(r, e, cfg, "cs2")
            res[nm] = ([round(k["t"], 2) for k in b0["kills"]], [round(k["t"], 2) for k in b1["kills"]])
        return res
    finally:
        M.CS2_DATING_ON[0] = True
        M.restore_data_dir(old)


def part_real(dst):
    with section("2) real CS2 clips (switch forced on for the scan)"):
        res = scan(dst)
        check(M.CS2_DATING_ON[0] is True, "item A ships ON")
        check(len(res) >= (400 if FULL else 8), f"{len(res)} clips scanned")
        check(all(len(v[0]) == len(v[1]) for v in res.values()), "kill count identical in every scanned clip")
        a = res.get("Replay 2026-04-10 21-26-38.mov")
        check(a and abs(a[1][0] - 18.0) <= 0.15, f"Replay 2026-04-10 21-26-38 accepted: {a}")
        b = res.get("Replay 2026-06-19 19-20-52.mov")
        check(b and abs(b[1][0] - 16.4) <= 0.15, f"Replay 2026-06-19 19-20-52 accepted: {b}")
        for nm_, ts_ in (("2026.02.12 - 19.24.00.20", (6.97, 14.8)), ("2026.02.10 - 19.09.46.22", (7.47,))):
            hit = [n for n in res if nm_ in n]
            for t_ in ts_:
                check(hit and any(abs(x - t_) <= 0.05 for n in hit for x in res[n][1]), f"gate (no denylist) keeps {nm_} {t_}")
        for k in UNTOUCHED:
            hit = [n for n in res if k in n]
            check(hit and all(res[n][0] == res[n][1] for n in hit), f"{k}: unchanged")


def part_item_b(tmp):
    with section("3) item B: every drop in the montage on its exact time (synthetic songs, auto drops, no labels)"):
        old = M.use_data_dir(tmp / "db")
        try:
            files = T73.make_files(tmp / "b_cs2", 24, "Replay")
            import random
            rnd = random.Random(11)
            ks = []
            for _ in files:
                n = rnd.choice([1, 2, 2, 3, 4])
                t, k = rnd.uniform(3.0, 5.0), []
                for _k in range(n):
                    k.append(round(t, 2))
                    t += rnd.uniform(0.7, 2.2)
                ks.append(k)
            its = T73.build_pool(M, "cs2", files, ks, seed=5)
            ev, _ = T73.events_of(M, "cs2", its)
            for nd in (1, 2, 4):
                an = T73.song_map(M, 128.0, 300.0, 64.0)
                bt = an["beats"]
                base = an["drops"][0]["beat"]
                an["drops"] = [{"beat": base + 32 * i, "t": float(bt[base + 32 * i]) + 0.21 + 0.03 * i, "strength": 1.0 - 0.1 * i} for i in range(nd)]
                an["drop"] = base
                M.DROP_ANCHOR_ON[0] = False
                p0 = T73.plan_of(M, "cs2", ev, an, 5)
                M.DROP_ANCHOR_ON[0] = True
                p1 = T73.plan_of(M, "cs2", ev, an, 5)
                lines = [n_ for n_ in p1["notes"] if n_.startswith("drop ")]
                nk = lambda p: sum(len(t["kills"]) for t in p["takes"])
                check(nk(p0) == nk(p1) and [t["path"] for t in p0["takes"]] == [t["path"] for t in p1["takes"]] and p0["total_frames"] == p1["total_frames"],
                      f"{nd} auto drops: same takes, same kills ({nk(p1)}), same length")
                check(len({t["path"] for t in p1["takes"]}) == len(p1["takes"]), f"{nd} drops: no repeated clip")
                s0 = p1["song"]["start_t"]
                inside = [d["t"] for d in an["drops"] if s0 + 0.5 < d["t"] < s0 + p1["duration"] - 1.0]
                check(len(lines) == len(inside), f"{nd} drops: {len(inside)} inside the montage, {len(lines)} log lines")
                for ln in lines:
                    if " anchored: " in ln:
                        err = float(ln.split("error ")[1].split(" ms")[0])
                        check(err <= 30.0, f"   {ln}")
                    else:
                        check("not anchorable:" in ln and len(ln.split("not anchorable:")[1].strip()) > 3, f"   {ln}")
                check(all(t["kills_out"][-1] < t["nf"] / 60 for t in p1["takes"] if t["kills_out"]), f"{nd} drops: every kill still inside its take")
                print("   " + "; ".join(lines))
            an = T73.song_map(M, 128.0, 300.0, 64.0)
            an["drops"] = [{"beat": an["drops"][0]["beat"], "t": float(an["beats"][an["drops"][0]["beat"]]) + 0.3, "strength": 1.0}]
            M.DROP_ANCHOR_ON[0] = False
            q0 = T73.plan_of(M, "cs2", ev, an, 5)
            M.DROP_ANCHOR_ON[0] = True
            M.DROP_ANCHOR_MAX = 0.0001
            q1 = T73.plan_of(M, "cs2", ev, an, 5)
            M.DROP_ANCHOR_MAX = 1.0
            check([t["segs"] for t in q0["takes"]] == [t["segs"] for t in q1["takes"]], "unanchorable drop: cut lists unchanged")
            check(any("not anchorable" in n_ for n_ in q1["notes"]), "unanchorable drop: reason logged")
        finally:
            M.DROP_ANCHOR_ON[0] = True
            M.DROP_ANCHOR_MAX = 1.0
            M.restore_data_dir(old)


def part_outro(tmp):
    with section("4) item C: outro fade math (no hold, last 0.5 s, short tail)"):
        mk = lambda D, ko: {"duration": D, "takes": [{"out_start": D - 6.0, "kills_out": [ko - (D - 6.0)], "nf": 360}]}
        v, l = M.outro_fade(mk(60.0, 56.5))
        check(abs(l - 0.5) < 1e-6 and abs(v - 59.5) < 1e-6, f"long tail: fade {v:.2f} s over {l:.2f} s")
        v, l = M.outro_fade(mk(60.0, 59.4))
        check(0.3 <= l < 0.5 and v >= 59.4 - 1e-6, f"tail 0.6 s: fade {v:.2f} over {l:.2f} (not before the kill)")
        v, l = M.outro_fade(mk(60.0, 59.9))
        check(abs(l - 0.3) < 1e-6, f"tail 0.1 s: minimum fade {l:.2f}")
        an = T73.song_map(M, 128.0, 300.0, 64.0)
        for game in ("valorant", "cs2"):
            files = T73.make_files(tmp / f"o_{game}", 12, "VALORANT" if game == "valorant" else "Replay")
            its = T73.build_pool(M, game, files, [[4.0, 5.2, 6.4]] * 12, seed=3)
            ev, _ = T73.events_of(M, game, its)
            plan = T73.plan_of(M, game, ev, an, 5)
            vfo, vlen = M.outro_fade(plan)
            inp, fc = M.build_filter(plan, M.load_config(), False)
            check(f"fade=t=out:st={vfo:.3f}:d={vlen:.3f}" in fc, f"{game}: filter uses fade {vfo:.2f}/{vlen:.2f}")
            check("stop_duration=" in fc and fc.count("trim=end_frame={}".format(plan["takes"][-1]["nf"])) >= 1, f"{game}: last take cut to its planned length, no hold chain")
            last = plan["takes"][-1]
            check(vlen <= 0.5 + 1e-6 and vfo >= last["out_start"] + last["kills_out"][-1] - 1e-6, f"{game}: fade length {vlen:.2f}, starts after the last kill")


def main():
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t751_"))
    part_synth()
    with PB.data_copy(M) as dst:
        part_real(dst)
        M.DROP_ANCHOR_ON[0] = False
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
        M.DROP_ANCHOR_ON[0] = True
        old = M.use_data_dir(tmp / "do")
        try:
            part_item_b(tmp)
            part_outro(tmp)
        finally:
            M.restore_data_dir(old)
    T73.part_real_untouched(before)
    check(M.APP_VERSION == "V7.5.1.2", "title-bar version V7.5.1.2")
    print(f"total test time {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}): " + "; ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
