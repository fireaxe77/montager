"""V6.8.2: CS2 border tracking fixes (non-row blobs, fragment merge, pre-clip, sides, no caps, rowdebug) + the Valorant guard. Generated rows plus
the real screenshots in tests/fixtures/cs2_rows (kill_row, assist_row, death_row, kill_row_single; false_red_b_sign is generated when missing).
   xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v682.py        (Windows: python test_v682.py)
Only this version's checks + the Valorant guard; older tests are frozen and NOT run. V682_REAL=0 skips the real-clip part."""
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

HERE = __import__("_root").find_root(__file__)          # repo root (tests/_root.py); this file lives in tests/
sys.path.insert(0, str(HERE))
import montage as M                                                                           # noqa: E402
import cv2                                                                                    # noqa: E402
import numpy as np                                                                            # noqa: E402

T_ALL = time.time()
FAILS, SECTIONS = [], []
FIX = HERE / "tests" / "fixtures" / "cs2_rows"
REAL_DATA = HERE / "montage_data"


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def section(title):
    class S:
        def __enter__(self):
            self.t = time.time()
            print(f"== {title} ==")

        def __exit__(self, *a):
            SECTIONS.append((title, time.time() - self.t))
            print(f"   [{title}: {time.time() - self.t:.1f} s]")
    return S()


def captured(fn, *a):
    lines, real = [], M.out
    M.out = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        res = fn(*a)
    finally:
        M.out = real
    return "\n".join(lines), res


def snapshot(d):
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(d).rglob("*"))
            if p.is_file() and "cs2_rows_v1" not in p.parts} if Path(d).exists() else {}


REAL_BEFORE = snapshot(REAL_DATA)
FPS = 30


# ===================================================================================================== generated data
def fake_vote(k, v, icon="gun", f=40):
    x, boxes, blobs = 10, [], []
    if k:
        kw = max(20, 9 * len(k))
        boxes.append([x, 4, x + kw, 24, k, 0.95, ""])
        x += kw + 10
    iw, ih = (70, 14) if icon == "gun" else (18, 18)
    blobs.append([x, 6, iw, ih, 0.9])
    x += iw + 10
    if v:
        boxes.append([x, 4, x + max(20, 9 * len(v)), 24, v, 0.95, ""])
    return {"f": f, "q": 100, "boxes": boxes, "blobs": blobs}


def track(i, first, last, reads, slot=0, icon="gun", op0=1.0, w=300, hits=None):
    y = 4 + 42 * slot
    t = {"id": i, "first": first, "last": last, "hits": hits or (last - first + 1), "x0": 790 - w, "x1": 790, "y0": y, "y1": y + 38,
         "slots": [[first, y, slot]], "votes": [fake_vote(k, v, icon, first + 6 + j) for j, (k, v) in enumerate(reads)]}
    if op0 is not None:
        t["op0"] = op0
    return t


def sidecar(tracks, frames=400, ext=2):
    sc = {"v": M.BORDER_V, "fps": FPS, "frames": frames, "v_off": 0.0, "tracks": tracks, "key": "k"}
    if ext >= 2:
        sc["ext"] = 2
    return sc


def kills(sc, deaths=None):
    return M.border_analysis(sc, {}, deaths)


def part_fixtures():
    with section("real screenshots (outline colour, shape) + generated B marker"):
        M.set_player_names({})
        fx = {n: cv2.imread(str(FIX / f"{n}.png")) for n in ("kill_row", "assist_row", "death_row", "kill_row_single")}
        miss = [n for n, im in fx.items() if im is None]
        check(not miss, f"fixtures present in tests/fixtures/cs2_rows ({'missing: ' + ', '.join(miss) if miss else 'kill_row, assist_row, death_row, kill_row_single'}); false_red_b_sign.png is not in the repo: generated")
        for n, im in fx.items():
            if im is None:
                continue
            b, g, r = [c.astype(int) for c in cv2.split(im)]
            core = (r >= 150) & (g <= 90) & (b <= 90)
            rc = M.border_rects(im)
            med = np.median(im[core], axis=0).astype(int).tolist() if core.sum() else None
            print(f"      {n}: {im.shape[1]}x{im.shape[0]}, outline pixels {int(core.sum())}, median BGR {med}, rects {[(x['x1'] - x['x0'], x['y1'] - x['y0']) for x in rc]} (width x height), strength {[round(x['str']) for x in rc]}")
        # the B marker: a small reddish diamond, no row shape, plus a red square outline
        bsign = np.full((90, 400, 3), (45, 50, 55), np.uint8)
        cv2.fillConvexPoly(bsign, np.array([[200, 20], [225, 45], [200, 70], [175, 45]]), (40, 40, 200))
        cv2.rectangle(bsign, (300, 20), (350, 70), (40, 40, 200), 2)
        check(M.border_rects(fx["kill_row"]) and len(M.border_rects(fx["kill_row"])) == 3, "kill_row: 3 outlined rows")
        check(len(M.border_rects(fx["assist_row"])) == 1, "assist_row: 1 outlined row")
        check(len(M.border_rects(fx["kill_row_single"])) == 1, "kill_row_single: 1 outlined row")
        check(len(M.border_rects(fx["death_row"])) == 0, "death_row (orange background, no outline): 0 outlined rows")
        check(len(M.border_rects(bsign)) == 0, "false_red_b_sign (diamond + red square): 0 rows")

        def run_image(im, n_on=40):
            tr = M.BorderTracker(FPS)
            blank = np.zeros_like(im)
            for f in range(20 + n_on):
                tr.feed(f, blank if f < 20 else im)
            trs = tr.finish()
            out_ = []
            for t in trs:
                votes = []
                for q, f, crop, rc in t["picked"][:2]:
                    bx, bl = M.border_ocr(crop)
                    votes.append({"f": f, "q": q, "boxes": bx, "blobs": bl})
                out_.append({"id": t["id"], "first": t["first"], "last": t["last"], "hits": t["hits"], "x0": t["x0"], "x1": t["x1"], "y0": t["y0"], "y1": t["y1"],
                             "slots": t["slots"], "votes": votes, "op0": t.get("op0")})
            return M.border_analysis(sidecar(out_, 20 + n_on), {})
        a = run_image(fx["kill_row"])
        print("      kill_row reads: " + " | ".join(m["row"] for m in a["mine"]))
        check(len(a["kills"]) == 3, f"kill_row: 3 kills ({len(a['kills'])})")
        a = run_image(fx["assist_row"])
        print("      assist_row reads: " + " | ".join(m["row"] + " -> " + m["verdict"] for m in a["mine"]))
        check(len(a["kills"]) == 0 and a["rows_n"] == 1, f"assist_row: 1 row, 0 kills ({len(a['kills'])} kills)")
        a = run_image(fx["kill_row_single"])
        check(len(a["kills"]) == 1, f"kill_row_single: 1 kill ({len(a['kills'])})")
        a = run_image(bsign)
        check(not a["kills"] and a["rows_n"] == 0, "B marker: nothing classified, nothing counted")
        # the normal name rule still reads the death
        rows = M.ocr_rows(*M.ocr_frame(fx["death_row"]), "cs2")
        v = [x for r in rows for x, _ in M.classify_row(r, None, 0.0, "cs2")]
        print("      death_row reads: " + " | ".join(M.row_desc(r) for r in rows))
        check(v.count("death") == 1 and "kill" not in v, f"death_row: the existing name rule reads exactly 1 death ({v})")


def draw_row(img, y0, killer, victim, icon_w=80, border=True, thick=2):
    f, sc, t = cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2
    lw, rw = cv2.getTextSize(killer, f, sc, t)[0][0], cv2.getTextSize(victim, f, sc, t)[0][0]
    x1 = 792
    x0 = x1 - (lw + 14 + icon_w + 14 + rw + 20)
    cv2.rectangle(img, (x0, y0), (x1, y0 + 38), (28, 28, 30), -1)
    if border:
        cv2.rectangle(img, (x0, y0), (x1, y0 + 38), (40, 40, 200), thick)
    cv2.putText(img, killer, (x0 + 10, y0 + 26), f, sc, (90, 200, 235), t, cv2.LINE_AA)
    ix = x0 + 10 + lw + 14
    cv2.rectangle(img, (ix, y0 + 12), (ix + icon_w, y0 + 23), (255, 255, 255), -1)
    cv2.putText(img, victim, (ix + icon_w + 14, y0 + 26), f, sc, (230, 180, 110), t, cv2.LINE_AA)


def part_blobs():
    with section("non-row blobs, pre-clip, fragments (generated)"):
        # 71 generated red blobs + 2 real rows = 2 kills
        rng = np.random.default_rng(5)
        rows = [(1.5, "fireaxe", "ThePOstMen"), (3.0, "fireaxe", "Markusko")]
        blobs = []
        for i in range(71):
            f0 = int(rng.integers(10, 270))
            w, h = int(rng.integers(20, 300)), int(rng.integers(10, 60))
            blobs.append((f0, f0 + int(rng.integers(2, 6)), int(rng.integers(0, 500)), int(rng.integers(0, 300)), w, h))
        tr = M.BorderTracker(FPS, keep_crops=False)
        for f in range(300):
            img = np.full((400, 806, 3), (70, 78, 86), np.uint8)
            vis = sorted([r for r in rows if r[0] <= f / FPS], key=lambda r: -r[0])
            for slot, (_, k, v) in enumerate(vis):
                draw_row(img, 4 + 42 * slot, k, v)
            for f0, f1, x, y, w, h in blobs:
                if f0 <= f <= f1:
                    cv2.rectangle(img, (x, y), (x + w, y + h), (40, 40, 200), 2)
            tr.feed(f, img)
        trs = tr.finish()
        raw = len(tr.tracks)
        out_ = [{"id": t["id"], "first": t["first"], "last": t["last"], "hits": t["hits"], "x0": t["x0"], "x1": t["x1"], "y0": t["y0"], "y1": t["y1"], "slots": t["slots"],
                 "votes": [fake_vote("fireaxe", "ThePOstMen" if t["first"] < 100 else "Markusko")] * 2, "op0": t.get("op0")} for t in trs]
        a = kills(sidecar(out_, 300) | {"blobs": tr.blob_n})
        check(raw >= 50 and len(a["kills"]) == 2 and a["blobs"] >= raw - 3, f"71 generated blobs + 2 real rows: {raw} outlined tracks found, {len(a['kills'])} kills, {a['blobs']} blobs discarded")
        # the same on a stored (V6.8.1-style) sidecar that still contains the blobs with their votes: filtered at load time
        stored = [track(100 + i, f0, f1, [("x", "y")], icon="gun", w=w, hits=f1 - f0 + 1) | {"y0": y, "y1": y + h, "x1": x + w, "x0": x} for i, (f0, f1, x, y, w, h) in enumerate(blobs)]
        a = kills(sidecar([track(0, 45, 250, [("fireaxe", "ThePOstMen")] * 2, slot=1), track(1, 90, 250, [("fireaxe", "Markusko")] * 2, slot=0)] + stored, 300, ext=1))
        check(len(a["kills"]) == 2, f"an existing sidecar with the 71 blobs stored in it: {len(a['kills'])} kills, {a['blobs']} discarded, no rebuild")
        # a row visible only 2 frames at the end of the clip is counted
        a = kills(sidecar([track(0, 40, 200, [("fireaxe", "ThePOstMen")] * 2), track(1, 298, 299, [("fireaxe", "Markusko")], hits=2)], 300))
        check(len(a["kills"]) == 2, "a row visible only 2 frames at the end of the clip is counted")
        a = kills(sidecar([track(0, 40, 200, [("fireaxe", "ThePOstMen")] * 2), track(1, 150, 151, [("fireaxe", "Markusko")], hits=2)], 300))
        check(len(a["kills"]) == 1, "... while a 2-frame outline in the middle of the clip is a blob")
        # pre-clip
        a = kills(sidecar([track(0, 9, 150, [("fireaxe", "Dono")] * 2, op0=1.0)]))
        check(not a["kills"] and any("pre-clip" in j["reason"] for j in a["rej"]), "a track first seen at 0.3 s at full opacity = pre-clip")
        a = kills(sidecar([track(0, 9, 150, [("fireaxe", "Dono")] * 2, op0=0.4)]))
        check(len(a["kills"]) == 1, "... but the same row fading IN at 0.3 s is a real kill")
        a = kills(sidecar([track(0, 20, 150, [("fireaxe", "Dono")] * 2, op0=1.0)]))
        check(len(a["kills"]) == 1, "a full-opacity row first seen after 0.6 s is a kill")
        a = kills(sidecar([track(0, 10, 200, [("fireaxe", "Hogo Rush|5ggcs.ru")] * 2, op0=1.0, slot=1), track(1, 12, 200, [("fireaxe", "XynTaHOuKa A")] * 2, op0=1.0, slot=0)]))
        check(len(a["kills"]) == 0 or len(a["kills"]) == 2, f"two victims at 0:00.3 read many ways: pre-clip or 2 kills ({len(a['kills'])})")
        # old sidecar without opacity data: the slot rule (a row that is not the newest slot at 0.3 s was already there)
        a = kills(sidecar([track(0, 9, 150, [("fireaxe", "Dono")] * 2, op0=None, slot=1)], ext=1))
        check(not a["kills"], "older sidecar (no fade-in data): a row first seen at 0.3 s on an older slot is pre-clip")
        # fragments: 'dono' x6 within 0.8 s
        reads = ["dono", "done<3", "dono c3", "dono3", "dono", "done<3"]
        frs = [track(i, 30 + 6 * i, 34 + 6 * i, [("fireaxe", r)] * 2, slot=0, hits=5) for i, r in enumerate(reads)]
        a = kills(sidecar(frs))
        check(len(a["kills"]) <= 2, f"victim 'dono' x6 in 0.8 s: {len(a['kills'])} kill(s) (at most 2)")
        # five fragments of 2 victims at 0.2-0.6 s, read many ways
        fr2 = [track(i, 6 + 3 * i, 8 + 3 * i, [("fireaxe", r)] * 2, slot=s, hits=3, op0=0.5) for i, (r, s) in enumerate([("Hogo Rush|5ggcs.ru", 1), ("Hogo Rush 5ggcs.ru", 1), ("H0g0 Rush|5ggcs.ru", 1), ("XynTaHOuKa A", 0), ("XynTaH0uKa A", 0)])]
        a = kills(sidecar(fr2))
        check(len(a["kills"]) <= 2, f"5 fragments of 2 victims at 0:00.2-0:00.6: {len(a['kills'])} kill(s) (2 distinct events at most)")
        # ThePOstMon split into 4 tracks in one slot (DVR_1: a 3k)
        parts = [track(i, 60 + 40 * i // 4 * 0 + 8 * i, 66 + 8 * i, [("fireaxe", v)] * 2, slot=2, hits=7) for i, v in enumerate(["ThePOstMon", "ThePOstMen^^", "ThePOstMo", "ThePOstMen"])]
        rest = [track(10, 200, 330, [("flreaxo", "chara racing (supreme)")] * 2, slot=1), track(11, 280, 390, [("flreaxo", "Markusko")] * 2, slot=0)]
        a = kills(sidecar(parts + rest))
        check(len(a["kills"]) == 3, f"DVR_1: ThePOstMon split into 4 tracks in slot 2 + 2 more victims = 3 kills ({len(a['kills'])})")
        # two real rows visible at the same time in different slots with the SAME victim text stay two kills
        a = kills(sidecar([track(0, 60, 200, [("fireaxe", "Zorro")] * 2, slot=1), track(1, 90, 200, [("fireaxe", "Zorro")] * 2, slot=0)]))
        check(len(a["kills"]) == 2, "two rows visible at once in different slots = 2 kills (even with one victim text)")
        # the same victim killed twice, the first row gone for 2 s
        a = kills(sidecar([track(0, 60, 140, [("fireaxe", "Zorro")] * 2), track(1, 200, 330, [("fireaxe", "Zorro")] * 2)]))
        check(len(a["kills"]) == 2, "the same victim twice, first row gone for 2 s = 2 kills (no same-victim rule)")
        a = kills(sidecar([track(0, 60, 140, [("fireaxe", "Zorro")] * 2), track(1, 150, 330, [("fireaxe", "Zorro")] * 2)]))
        check(len(a["kills"]) == 1, "the same row back after 0.3 s = 1 kill")
        # 8 distinct kills of 8 victims: no cap
        names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo7", "Foxtrot", "Golfer", "Hotel9"]
        a = kills(sidecar([track(i, 60 + 40 * i, 140 + 40 * i, [("fireaxe", n)] * 2, slot=i % 5) for i, n in enumerate(names)], 600))
        check(len(a["kills"]) == 8 and a["dm"], f"8 kills of 8 victims in one clip: all {len(a['kills'])} kept, Deathmatch warning set")


def part_sides():
    with section("sides: assist / kill / suspicious / other player"):
        M.set_player_names({})
        one = lambda k, v, n=2: kills(sidecar([track(0, 60, 200, [(k, v)] * n)]))
        a = one("Kiz + fireaxe 火斧", "halfhand")
        check(not a["kills"] and any("assist" in j["reason"] for j in a["rej"]), "'Kiz + fireaxe 火斧' = assist, not a kill")
        a = one("fireaxe + mate", "victim")
        check(len(a["kills"]) == 1, "'fireaxe + mate' = kill")
        a = one("flreaxo", "Zorro")
        check(len(a["kills"]) == 1 and not a["kills"][0]["name_read"], "garbled killer side = kill (name unreadable, border confirmed)")
        a = one("ThePOstMen^^ + chara racing (supreme)", "fireaxe 火斧")
        check(not any(k for k in a["kills"]) or a["sus"], "outlined track with my name on the VICTIM side with another readable name first: not a kill")
        check(not a["kills"] and a["sus"] and not a["deaths"], f"... listed as a suspicious side read, never a death ({[s[1][:40] for s in a['sus']]})")
        a = one("flreaxo", "fireaxe")
        check(len(a["kills"]) == 1 and a["sus"] and not a["deaths"], "my name on the victim side, killer side not another readable name: kept as a kill, listed suspicious, not a death")
        a = kills(sidecar([track(0, 60, 200, [("Zhukovsky", "Zorro")] * 3)]))
        check(not a["kills"] and a["others"], f"a stable, readable other name first (3 reads) = other player's row ({[o[1][:50] for o in a['others']]})")
        a = kills(sidecar([track(0, 60, 200, [("Zhukovsky", "Zorro"), ("Zhukovsky", "Zorro")])]))
        check(len(a["kills"]) == 1, "... only with 3+ reads (2 reads: still a kill)")
        a = kills(sidecar([track(0, 60, 200, [("fireaxe", "Zorro")] * 2)]), deaths=[12.5])
        check(a["deaths"] == [12.5], "deaths come from the name-based rule (passed through)")
        e = {"ocr": [], "frames": 1, "v_off": 0.0, "game": "cs2"}
        tmp = Path(tempfile.mkdtemp(prefix="t682s_"))
        old = M.use_data_dir(tmp)
        try:
            clip = tmp / "c.mp4"
            clip.write_bytes(b"x" * 100)
            rec = {"path": str(clip), "w": 1920, "h": 1080, "game": "cs2", "bars": False, "bar_sig": ""}
            det = M.Detector("cs2")
            p, key = M.border_path(rec, det)
            M.BORDER_DIR.mkdir(parents=True, exist_ok=True)
            legacy = sidecar([track(0, 60, 200, [("fireaxe", "Zorro")] * 2, op0=None)], ext=1) | {"key": key}
            p.write_text(json.dumps(legacy), encoding="utf-8")
            check(M.border_load(rec, det) is not None and M.border_build_many([rec], {}, det) == {}, "an existing (V6.8.1) sidecar loads and is not rebuilt")
            a = M.analyse_clip_entry(rec, e, {}, "cs2")
            check(a.get("border") and len(a["kills"]) == 1 and a["legacy"], "... and is interpreted with the new rules at load time")
            txt, _ = captured(lambda: None)
        finally:
            M.restore_data_dir(old)


# ===================================================================================================== rowdebug
def part_rowdebug():
    with section("rowdebug output"):
        sc = sidecar([track(0, 60, 200, [("fireaxe", "Zorro")] * 2), track(1, 100, 101, [("x", "y")], hits=2), track(2, 120, 400, [("fireaxe", "Alpha")] * 2, slot=1)]
                     + [track(10 + i, 150 + i, 152 + i, [("x", "y")], w=100, hits=3) for i in range(25)], 400, ext=1) | {"secs": 1, "decode_secs": 1, "ocr_secs": 0, "ms_per_frame": 1}
        tmp = Path(tempfile.mkdtemp(prefix="t682r_"))
        old = M.use_data_dir(tmp)
        real_here = M.HERE
        M.HERE = tmp
        try:
            clip = tmp / "Counter-strike 2 2025.02.08 - 19.48.57.15.DVR_1.mp4"
            clip.write_bytes(b"x" * 100)
            rec = {"path": str(clip), "w": 1920, "h": 1080, "game": "cs2", "bars": False, "bar_sig": ""}
            det = M.Detector("cs2")
            p, key = M.border_path(rec, det)
            M.BORDER_DIR.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(sc | {"key": key}), encoding="utf-8")
            store = M.load_kills_cache()
            store.put(M.kills_key(rec, "cs2", det), {"ocr": [], "frames": 1, "v_off": 0.0, "game": "cs2"})
            d = M.rowdebug_clip(rec, {}, det, store)
            txt = "\n".join(d["lines"])
            check("discarded 26 non-row blobs" in txt and txt.count("votes:") == 2, "rowdebug prints 'discarded N non-row blobs' once and collapses them (2 rows listed)")
            check("older sidecar" in txt, "rowdebug marks a sidecar without fade-in data")
            M.scan_clips = lambda cfg, rescan=False: [dict(rec)]
            real_sc = M.scan_clips
            txt, _ = captured(M.cmd_rowdebug, types.SimpleNamespace(game="cs2", clip=None, all=True, rebuild=False))
            check((tmp / "rowdebug_cs2.txt").exists() and "1 of 1 sidecars lack the fade-in" in txt and "blobs" in txt, "rowdebug --all: one table sorted by suspicion, saved, counts sidecars lacking the data")
            check(M.rowdebug_suspicion({"only_old": [1], "only_new": [], "burst": 0, "blobs": 0, "sus": 0, "others": 0, "new": [], "old": []})
                  > M.rowdebug_suspicion({"only_old": [], "only_new": [], "burst": 0, "blobs": 0, "sus": 0, "others": 0, "new": [], "old": []}), "the table sorts differences / bursts / blobs / suspicious reads / other rows first")
        finally:
            M.HERE = real_here
            M.restore_data_dir(old)


# ===================================================================================================== Valorant guard
def gen_entries(n=100):
    rng = np.random.default_rng(11)
    names = ["fireaxe", "Zorro", "enemy1", "player2", "mate", "Kristof", "f1reaxe", "xX_pro_Xx", "Slop"]
    entries = []
    for e_i in range(n):
        ocr = []
        for s in range(24):
            f = 3 * s + e_i % 5
            boxes, blobs = [], []
            for r_i in range(int(rng.integers(0, 4))):
                k, v = names[int(rng.integers(0, len(names)))], names[int(rng.integers(0, len(names)))]
                if rng.random() < 0.3:
                    k += " + " + names[int(rng.integers(0, len(names)))]
                vv = fake_vote(k, v, "gun" if rng.random() < 0.85 else "util")
                off = r_i * 30
                boxes += [[b[0], b[1] + off, b[2], b[3] + off, b[4], b[5], "r" if rng.random() < 0.5 else "g", f] for b in vv["boxes"]]
                blobs += [[g[0], g[1] + off, g[2], g[3], g[4]] for g in vv["blobs"]]
            ocr.append([f, f, boxes, blobs])
        entries.append({"ocr": ocr, "frames": 80, "v_off": 0.0, "game": "valorant"})
    return entries


def load_baseline(tmp, ref):
    r = subprocess.run(["git", "show", f"{ref}:montage.py"], cwd=str(HERE), capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    bdir = tmp / "base"
    bdir.mkdir(exist_ok=True)
    (bdir / "montage.py").write_bytes(r.stdout)
    data = tmp / "base_data"
    data.mkdir(exist_ok=True)
    for f in REAL_DATA.glob("detect_*.json"):                      # the baseline must read the SAME killfeed region files (V6.8.1's test did not)
        (data / f.name).write_bytes(f.read_bytes())
    os.environ["MONTAGER_DATA"] = str(data)
    try:
        spec = importlib.util.spec_from_file_location("montage_base031", str(bdir / "montage.py"))
        B = importlib.util.module_from_spec(spec)
        sys.modules["montage_base031"] = B
        spec.loader.exec_module(B)
    finally:
        del os.environ["MONTAGER_DATA"]
    return B


def valorant_view(mod, e):
    a = mod.analyse_entry(e, {}, "valorant")
    return json.dumps({"kills": [(k["t"], k.get("victim"), k.get("hs")) for k in a["kills"]], "deaths": a["deaths"], "revives": a["revives"],
                       "rej": [(j["t"], j["reason"]) for j in a["rej"]], "vis": a["vis"]}, sort_keys=True, default=str)


def part_valorant(tmp):
    with section("Valorant guard (commit 031cb64 vs this code)"):
        B = load_baseline(tmp, "031cb64")
        if B is None:
            check(False, "git baseline 031cb64 not available (git fetch origin)")
            return
        entries = gen_entries(100)
        nd = sum(valorant_view(M, e) != valorant_view(B, e) for e in entries)
        kn = sum(len(M.analyse_entry(e, {}, "valorant")["kills"]) for e in entries)
        check(nd == 0 and kn > 50, f"100 generated Valorant clips: kills, timestamps, deaths, revives identical to 031cb64 ({nd} differences, {kn} kills)")
        check(M.Detector("valorant").d["stamp"] == B.Detector("valorant").d["stamp"] and M.ALGO == B.ALGO,
              f"Valorant region hash {M.Detector('valorant').d['stamp']} and cache format {M.ALGO} identical (the baseline reads the same detect_valorant.json)")
        # cache keys + validity: entries stored under the baseline's keys are all valid for this code (no rescan prompt)
        old = M.use_data_dir(tmp / "guard")
        try:
            d = tmp / "gclips"
            d.mkdir(exist_ok=True)
            for f in REAL_DATA.glob("detect_*.json"):                  # same killfeed region files as the baseline reads
                (M.DATA / f.name).write_bytes(f.read_bytes())
            store = M.load_kills_cache()
            recs = []
            for i in range(30):
                p = d / f"2025.10.1{i % 9} - 19.06.{i:02d}.mp4"
                p.write_bytes(b"x" * (60 + i))
                rec = {"path": str(p), "game": "valorant", "w": 1920, "h": 1080, "dur": 10.0, "bars": i % 3 == 0, "bar_sig": "sig" if i % 3 == 0 else ""}
                recs.append(rec)
                store.put(B.kills_key(rec, "valorant", B.Detector("valorant")), {"ocr": [], "frames": 1, "game": "valorant", "v_off": 0.0})
            det = M.Detector("valorant")
            same = all(M.kills_key(r, "valorant", det) == B.kills_key(r, "valorant", B.Detector("valorant")) for r in recs)
            jobs = [(r, "valorant") for r in recs if M.kills_key(r, "valorant", det) not in store]
            held = []
            M.REGION_PROMPT[0] = lambda h, c: held.append(h)
            todo = M._relink_or_explain(jobs, {"valorant": det}, store, {}, False) if jobs else []
            check(same and not jobs and not todo and not held, "cache keys identical; every existing entry is valid; no rescan and no region prompt")
        finally:
            M.REGION_PROMPT[0] = None
            M.restore_data_dir(old)
        # the user's real Valorant cache
        files = sorted((REAL_DATA).glob(f"kills_v{M.CACHE_V}/*.json")) if REAL_DATA.exists() else []
        if files:
            t0, n, nd = time.time(), 0, 0
            for fp in files:
                if time.time() - t0 > 25:
                    break
                try:
                    j = json.loads(fp.read_text(encoding="utf-8"))
                    e = j.get("e") or {}
                    if e.get("game") != "valorant" or "|valorant|" not in j.get("key", ""):
                        continue
                except Exception:
                    continue
                n += 1
                nd += valorant_view(M, e) != valorant_view(B, e)
            check(nd == 0, f"real cache: {n} cached Valorant clips, {nd} differences (kills, timestamps, deaths, revives)")
        else:
            print("      (no real montage_data here: real-cache comparison skipped)")


# ===================================================================================================== real clips (user's PC)
REAL = ["Counter-strike 2 2025.02.08 - 19.48.57.15.DVR_1.mp4", "Counter-strike 2 2025.02.08 - 19.53.38.16.DVR.mp4", "Counter-strike 2 2026.02.12 - 18.11.53.16.DVR.mp4",
        "Counter-strike 2 2026.02.11 - 18.37.08.05.DVR.mp4", "Replay 2026-04-29 02-02-30.mov", "Replay 2026-06-25 01-27-36.mov"]


def part_real():
    if os.environ.get("V682_REAL") == "0" or not list(REAL_DATA.glob("kills_v*/*.json")):
        print("== real clips: no montage_data here (or V682_REAL=0): skipped ==")
        return
    with section("real clips (printed only, never a failure)"):
        try:
            cfg = M.load_config()
            det = M.Detector("cs2")
            recs = M._cs2_recs(cfg, det=det)
            store = M.load_kills_cache()
            byname = {Path(r["path"]).name: r for r in recs}
            for nm in REAL:
                r = byname.get(nm)
                if r is None:
                    print(f"      {nm}: not found in the CS2 clip folders")
                    continue
                d = M.rowdebug_clip(r, cfg, det, store, images=True)
                print(f"      {nm}: old {len(d['old']) if d['old'] is not None else 'not scanned'} -> new {len(d['new'])} ({', '.join(M.ts(t) for t in d['new']) or '-'}), "
                      f"blobs discarded {d['blobs']}, suspicious {d['sus']}, other rows {d['others']}, border pass {d['cost']}s")
            rows = []
            for r in recs:
                e = store.get(M.kills_key(r, "cs2", det))
                if not e or e.get("error"):
                    continue
                sc = M.border_load(r, det)
                a = M.analyse_entry(e, cfg, "cs2")
                new = len(M.border_analysis(sc, cfg, a["deaths"])["kills"]) if sc else None
                rows.append((Path(r["path"]).name, len(a["kills"]), new))
            rows.sort(key=lambda x: -(abs(x[1] - x[2]) if x[2] is not None else -1))
            print(f"      before / after, {len(rows)} cached CS2 clips ({sum(1 for x in rows if x[2] is None)} without a sidecar yet: python montage.py bordercache cs2 --all):")
            print(f"      {'clip':60} {'before':>6} {'after':>6}")
            for nm, o, n in rows:
                print(f"      {nm[:60]:60} {o:6d} {'-' if n is None else n:>6}")
            print(f"      total before {sum(x[1] for x in rows)}, after {sum(x[2] for x in rows if x[2] is not None)} (clips with a sidecar)")
        except Exception as ex:
            print(f"      real-clip part failed to run: {type(ex).__name__}: {ex}")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="t682_"))
    part_fixtures()
    part_blobs()
    part_sides()
    part_rowdebug()
    part_valorant(tmp)
    part_real()
    with section("real montage_data untouched"):
        after = snapshot(REAL_DATA)
        if os.environ.get("V682_REAL") == "0" or not REAL_BEFORE:
            check(after == REAL_BEFORE, "no real montage_data was created or changed by this test")
        else:
            changed = [k for k in set(after) | set(REAL_BEFORE) if after.get(k) != REAL_BEFORE.get(k) and not k.startswith("rowdebug")]
            check(not changed, f"real montage_data byte-identical apart from the sidecar folder ({len(REAL_BEFORE)} files; changed: {changed[:5]})")
    print("\nsection times: " + ", ".join(f"{t.split(' (')[0]} {s:.0f}s" for t, s in SECTIONS))
    total = time.time() - T_ALL
    print(f"total test time {total:.0f} s" + ("" if total < 90 else "  (over the 90 s target)"))
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
