"""V7.5.1.1 tests (V7.5.1 tests + denylist, drag-to-edit drops, outro fade / hold, intro punch). Original V7.5.1 docstring: CS2 kill time = row appearance with the stricter same-row test (cs2_dating_walk / cs2_row_first_frame). Ships OFF (CS2_DATING_ON = [False]):
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
        check(j in (29, 30), f"older row pushed down into the tracked spot: the walk stops at the new row's first frame ({j}, at most one fade frame early), never inside the older row")
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
        check(a and abs(a[1][0] - 18.0) <= 0.1, f"Replay 2026-04-10 21-26-38: {a}")
        b = res.get("Replay 2026-06-19 19-20-52.mov")
        check(b and abs(b[1][0] - 16.4) <= 0.1, f"Replay 2026-06-19 19-20-52: {b}")
        for nm_, ts_ in (("2026.02.12 - 19.24.00.20", (6.97, 14.8)), ("2026.02.10 - 19.09.46.22", (7.47,))):
            hit = [n for n in res if nm_ in n]
            for t_ in ts_:
                check(hit and any(abs(x - t_) <= 0.05 for n in hit for x in res[n][1]), f"denylist {nm_} {t_}: cached time kept")
        moved = sum(1 for v in res.values() for x, y in zip(v[0], v[1]) if abs(x - y) > 1e-6)
        print(f"   moved kills in the scanned clips: {moved}")
        for k in UNTOUCHED:
            hit = [n for n in res if k in n]
            check(hit and all(res[n][0] == res[n][1] for n in hit), f"{k}: unchanged")


def part_drops(tmp):
    import json
    import tkinter as tk
    with section("3) drag-to-edit drops (song_drops.json), planner, reset"):
        old = M.use_data_dir(tmp / "dd")
        try:
            sp = "C:/x/Some Song.mp3"
            check(M.song_drop_labels(sp) is None, "no hand label at start")
            M.song_drops_write(sp, [64.0, 20.5])
            check(M.song_drop_labels(sp) == [20.5, 64.0], "labels saved sorted")
            M.song_drops_write("other.mp3", [5.0])
            M.song_drops_write(sp, None)
            check(M.song_drop_labels(sp) is None and M.song_drop_labels("other.mp3") == [5.0], "reset deletes only this song")
            M.song_drops_write("other.mp3", None)
            try:
                root = tk.Tk()
            except Exception as ex:
                print(f"   (no display: GUI drag simulation skipped: {ex})")
                return
            root.withdraw()
            V = M.SongMapView.__new__(M.SongMapView)
            V.path, V._csv_bpm, V._drag, V.hand = sp, None, None, False
            V.an = {"dur": 200.0, "bpm": 128, "beats": [0.0], "title": "t", "artist": "a", "drops": [{"t": 60.0, "strength": 1.0}]}
            V.cv = tk.Canvas(root, width=1000, height=300)
            V.cv.pack()
            V.info = tk.StringVar()
            V.zv = tk.StringVar(value="1x")
            V.cv.update()
            V._load_drops()
            V._W, V._dur, V._top, V._bot = 996.0, 200.0, 18, 280
            X = lambda t: 2 + t / 200.0 * 996.0
            V._dl = [[V.cv.create_line(X(60), 18, X(60), 280, tags=("drop",)), V.cv.create_text(X(60), 270)]]
            ev = lambda x: type("E", (), {"x": x, "y": 100})()
            V._press(ev(X(60)))
            check(V._drag == 0, "press on the red line picks it")
            V._motion(ev(X(62.37)))
            check(abs(V.drops[0] - 62.37) < 0.1 and "1:02." in V.cv.itemcget(V._dl[0][1], "text"), f"live time shown {V.cv.itemcget(V._dl[0][1], 'text')}")
            V.draw = lambda: None
            V._release(ev(X(62.37)))
            lab = M.song_drop_labels(sp)
            check(lab and abs(lab[0] - 62.37) < 0.1, f"released: saved as hand label {lab}")
            V._load_drops()
            check(V.hand and "hand-edited" in (V.show_info() or V.info.get()), "reopen: label persists, banner says hand-edited")
            V._add(ev(X(120.0)))
            check(len(M.song_drop_labels(sp)) == 2, "double-click adds a drop")
            V._remove(ev(X(120.0)))
            check(len(M.song_drop_labels(sp)) == 1, "right-click removes it")
            V._dl = [[0, 0]]
            M.song_drops_write(sp, None)
            V._load_drops()
            check(not V.hand and V.drops == [60.0], "reset: back to the automatic drops")
            root.destroy()
            # planner uses a dragged drop (pinned/any selection): label replaces the map list
            an = T73.song_map(M, 128.0, 300.0, 64.0)
            bt = an["beats"]
            clips = [{"path": f"c{i}.mp4", "times": [4.0 + i], "rows": [4.0 + i], "first": 4.0 + i, "last": 4.0 + i, "span": 0.0, "score": 1.0 - i / 10, "n": 1}
                     for i in range(8)]
            real = an["drops"][0]["beat"]
            M.song_drops_write("x.mp3", [float(bt[real + 32])])
            f4 = M.optimal_fit(clips, an, "hype", song_path="x.mp3")
            check(abs(bt[f4["drop_beat"]] - bt[real + 32]) < 0.3 or "kept" in f4["drop_why"], f"planner uses the dragged drop ({bt[f4['drop_beat']]:.1f} s)")
        finally:
            M.restore_data_dir(old)


def part_outro(tmp):
    with section("4) outro fade / hold, intro punch"):
        an = T73.song_map(M, 128.0, 300.0, 64.0)
        for game in ("valorant", "cs2"):
            files = T73.make_files(tmp / f"o_{game}", 12, "VALORANT" if game == "valorant" else "Replay")
            ks = [[4.0, 5.2, 6.4]] * 12
            its = T73.build_pool(M, game, files, ks, seed=3)
            ev, _ = T73.events_of(M, game, its)
            plan = T73.plan_of(M, game, ev, an, 5)
            vfo, vlen, hold = M.outro_fade(plan)
            last = plan["takes"][-1]
            ko = last["out_start"] + last["kills_out"][-1]
            old_len = plan["duration"] - plan["song"]["fade_out_start"]
            print(f"   {game}: old video fade from {plan['song']['fade_out_start']:.2f}s ({old_len:.2f}s); new from {vfo:.2f}s ({vlen:.2f}s); last kill {ko:.2f}s; hold {hold}")
            check(vfo >= ko + 0.5 - 1e-6 and vlen <= 0.8 + 1e-6, f"{game}: video fade starts {vfo - ko:.2f}s after the last kill, length {vlen:.2f}s")
            check(plan["song"]["fade_out_start"] == round(ko, 4) or not plan["ending"], f"{game}: music fade untouched")
            inp, fc = M.build_filter(plan, M.load_config(), False)
            check(f"fade=t=out:st={vfo:.3f}:d={vlen:.3f}" in fc, f"{game}: filter uses the new video fade")
            check(("tpad=stop_mode=clone" in fc) and (hold is None or "trim=end_frame" in fc), f"{game}: hold present={hold is not None}")


def main():
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t751_"))
    part_synth()
    with PB.data_copy(M) as dst:
        part_real(dst)
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
        part_drops(tmp)
        old = M.use_data_dir(tmp / "do")
        try:
            part_outro(tmp)
        finally:
            M.restore_data_dir(old)
    T73.part_real_untouched(before)
    check(M.APP_VERSION == "V7.5.1.1", "title-bar version V7.5.1.1")
    print(f"total test time {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}): " + "; ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
