"""V6.8.1: CS2 red-border row tracking, rescan of one region group, search bar position (generated data, no real renders). Linux:
   xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v681.py        (Windows: python test_v681.py)
Only what this version changes + the Valorant guard (V6.8 code vs this code on the same generated / cached Valorant entries).
Older test files are frozen and are NOT run here. Every section prints its elapsed time. Optional on the user's PC: V681_REAL=0 skips the
real-clip part (rowdebug on the named clips + the before/after table of every cached CS2 clip that already has a sidecar)."""
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import montage as M                                                                           # noqa: E402
import cv2                                                                                    # noqa: E402
import numpy as np                                                                            # noqa: E402

T_ALL = time.time()
FAILS = []
SECTIONS = []


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
            dt = time.time() - self.t
            SECTIONS.append((title, dt))
            print(f"   [{title}: {dt:.1f} s]")
    return S()


def captured(fn, *a):
    lines, real = [], M.out
    M.out = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        res = fn(*a)
    finally:
        M.out = real
    return "\n".join(lines), res


# ===================================================================================================== generated killfeed data
W, H, PITCH, RH = 806, 400, 42, 38              # killfeed region in 1920x1080 space, row pitch, row height
FPS30 = 30


def draw_row(img, y0, killer, victim, icon_w=80, border=True, thick=2):
    f, sc, t = cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2
    lw = cv2.getTextSize(killer, f, sc, t)[0][0]
    rw = cv2.getTextSize(victim, f, sc, t)[0][0]
    x1 = W - 14
    x0 = x1 - (lw + 14 + icon_w + 14 + rw + 20)
    cv2.rectangle(img, (x0, y0), (x1, y0 + RH), (28, 28, 30), -1)
    if border:
        cv2.rectangle(img, (x0, y0), (x1, y0 + RH), (40, 40, 200), thick)
    ty = y0 + RH - 12
    cv2.putText(img, killer, (x0 + 10, ty), f, sc, (90, 200, 235), t, cv2.LINE_AA)
    ix = x0 + 10 + lw + 14
    cv2.rectangle(img, (ix, ty - 14), (ix + icon_w, ty - 3), (255, 255, 255), -1)
    cv2.putText(img, victim, (ix + icon_w + 14, ty), f, sc, (230, 180, 110), t, cv2.LINE_AA)


def render(rows, n, jpeg=None, seed=1):
    """Frames of a generated killfeed. rows = [{t0, t1, k, v, border, icon_w}]: the newest row is on top, older rows are pushed down."""
    rng = np.random.default_rng(seed)
    for f in range(n):
        t = f / FPS30
        img = np.full((H, W, 3), (70, 78, 86), np.uint8)
        img += rng.integers(0, 6, img.shape, dtype=np.uint8)
        vis = sorted([r for r in rows if r["t0"] <= t < r.get("t1", 1e9)], key=lambda r: -r["t0"])
        for slot, r in enumerate(vis):
            draw_row(img, 4 + slot * PITCH, r["k"], r["v"], r.get("icon_w", 80), r.get("border", True))
        if jpeg:
            img = cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, jpeg])[1], 1)
        yield img


def fake_vote(k, v, icon="gun", f=40, hs=False):
    """One OCR read of a row crop, as border_ocr() would return it: killer box, icon blob, victim box."""
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


def make_track(i, first, last, reads, icon="gun", hits=None):
    """reads = [(killer text, victim text), ...] = what the clearest frames said."""
    return {"id": i, "first": first, "last": last, "hits": hits or (last - first + 1), "x0": 400, "x1": 790, "y0": 4, "y1": 42,
            "slots": [[first, 4, 0]], "votes": [fake_vote(k, v, icon, first + 6 + j) for j, (k, v) in enumerate(reads)]}


def make_sidecar(tracks, frames=300):
    return {"v": M.BORDER_V, "fps": FPS30, "frames": frames, "v_off": 0.0, "tracks": tracks}


def kill_ts(a):
    return [k["t"] for k in a["kills"]]


def run_frames(rows, n, reads, jpeg=None, icon=None):
    """Generated frames -> BorderTracker -> tracks (a fake OCR read per bordered row, matched by first frame) -> border_analysis."""
    tr = M.BorderTracker(FPS30)
    for f, fr in enumerate(render(rows, n, jpeg)):
        tr.feed(f, fr)
    tracks = tr.finish()
    out_ = []
    bordered = [r for r in rows if r.get("border", True)]
    for t in tracks:
        r = min(bordered, key=lambda r: abs(r["t0"] * FPS30 - t["first"]))
        out_.append(make_track(t["id"], t["first"], t["last"], reads[rows.index(r)], (icon or {}).get(rows.index(r), "gun"), t["hits"]) | {"slots": t["slots"]})
    return tracks, M.border_analysis(make_sidecar(out_, n), {})


# ===================================================================================================== 1. border tracking
def part_border():
    with section("border tracking (generated frames, fake OCR reads)"):
        M.set_player_names({})
        # 3 outlined rows with garbled names = 3 kills
        rows = [dict(t0=1.0, k="flreaxo", v="ThePOstMen^^"), dict(t0=2.5, k="fireaxo 火茶", v="chara racing"), dict(t0=4.0, k="flreaxe 火年", v="Markusko")]
        reads = [[("flreaxo", "ThePOstMen^^")] * 2, [("fireaxo 火茶", "chara racing")] * 2, [("flreaxe 火年", "Markusko")] * 2]
        tracks, a = run_frames(rows, 210, reads)
        check(len(tracks) == 3 and len(a["kills"]) == 3, f"3 red-bordered rows with garbled names = 3 kills ({len(a['kills'])} kills, {len(tracks)} tracks)")
        check(all(abs(k["t"] - r["t0"]) <= 1.01 / FPS30 for k, r in zip(a["kills"], rows)), f"kill time = FIRST frame of each row {kill_ts(a)} vs {[r['t0'] for r in rows]}")
        check(all(not k["needs_shot"] and k["border"] for k in a["kills"]), "border kills never need a gunshot")
        # the same rows shifting down as new rows arrive (unbordered rows of other players push them too)
        rows = [dict(t0=0.8, k="enemyaa", v="victimaa", border=False), dict(t0=1.2, k="flreaxo", v="ThePOstMen^^"), dict(t0=1.9, k="foebbb", v="bystand", border=False),
                dict(t0=2.5, k="fireaxo 火茶", v="chara racing"), dict(t0=3.1, k="foeccc", v="bystand2", border=False), dict(t0=3.4, k="foeddd", v="bystand3", border=False),
                dict(t0=4.0, k="flreaxe 火年", v="Markusko")]
        reads = [[], [("flreaxo", "ThePOstMen^^")] * 2, [], [("fireaxo 火茶", "chara racing")] * 2, [], [], [("flreaxe 火年", "Markusko")] * 2]
        tracks, a = run_frames(rows, 240, reads)
        mv = [len({s[2] for s in t["slots"]}) for t in tracks]
        check(len(a["kills"]) == 3 and len(tracks) == 3 and max(mv) >= 3, f"rows shifting down as new rows arrive = still 3 kills (slots seen per track {mv})")
        check(all(abs(k["t"] - r["t0"]) <= 1.01 / FPS30 for k, r in zip(a["kills"], [rows[1], rows[3], rows[6]])), f"... and each keeps its first-appearance time {kill_ts(a)}")
        # compression + fade
        rows = [dict(t0=1.0, k="flreaxo", v="ThePOstMen^^"), dict(t0=2.0, k="fireaxo 火茶", v="chara racing")]
        tracks, a = run_frames(rows, 150, [[("flreaxo", "ThePOstMen^^")] * 2, [("fireaxo 火茶", "chara racing")] * 2], jpeg=35)
        check(len(a["kills"]) == 2, f"JPEG-compressed frames (quality 35): both rows tracked, {len(a['kills'])} kills")
        # a row visible only 2 frames at the end of the clip
        rows = [dict(t0=1.0, k="flreaxo", v="ThePOstMen^^"), dict(t0=148 / FPS30, k="fireaxo 火茶", v="Markusko")]
        tracks, a = run_frames(rows, 150, [[("flreaxo", "ThePOstMen^^")] * 2, [("fireaxo 火茶", "Markusko")]])
        check(len(a["kills"]) == 2 and abs(a["kills"][1]["t"] - 148 / FPS30) < 0.04, f"a row visible only 2 frames at the end is counted ({kill_ts(a)})")
        # fade-out: a row that fades away is still ONE track
        rows = [dict(t0=1.0, t1=4.0, k="flreaxo", v="ThePOstMen^^")]
        fr = list(render(rows, 130))
        for i in range(60, 90):                                                    # fade the whole killfeed to the background over 1 s
            al = 1.0 - (i - 59) / 30.0
            fr[i] = cv2.addWeighted(fr[i], max(al, 0.0), np.full_like(fr[i], (70, 78, 86)), 1 - max(al, 0.0), 0)
        tr = M.BorderTracker(FPS30)
        for f, x in enumerate(fr):
            tr.feed(f, x)
        check(len(tr.finish()) == 1, "a row fading out stays ONE track")
        # an unbordered row is ignored
        tracks, a = run_frames([dict(t0=1.0, k="fireaxe", v="enemy", border=False)], 100, [[]])
        check(len(tracks) == 0 and not a["kills"], "an unbordered row (even with my name) is no track and no kill")
        # orange / yellow names, white icons, no outline: no false track
        check(M.border_rects(next(render([dict(t0=0, k="orange", v="yellow", border=False)], 1))) == [], "yellow / blue team-coloured names and white icons without an outline: no border found")

        # the same rows through real H.264 4:2:0 at other outline widths / qualities / source resolutions (1280x960 / 1024 are stretched up)
        tdir = Path(tempfile.mkdtemp(prefix="t681h_"))
        for thick, crf, scale in ((1, 28, 1.875), (2, 23, 1.0), (3, 32, 1.875)):
            clip = tdir / f"t{thick}.mp4"
            pr = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "1920x1080", "-r", "30", "-i", "-", "-c:v", "libx264",
                                   "-preset", "ultrafast", "-crf", str(crf), "-pix_fmt", "yuv420p", str(clip)], stdin=subprocess.PIPE)
            rows_ = [dict(t0=1.0, k="fireaxe", v="ThePOstMen"), dict(t0=2.0, k="enemyx", v="other", border=False), dict(t0=2.8, k="fireaxe", v="Markusko")]
            rng_ = np.random.default_rng(3)
            for f in range(150):
                img = np.full((H, W, 3), (70, 78, 86), np.uint8) + rng_.integers(0, 6, (H, W, 3), dtype=np.uint8)
                vis = sorted([r for r in rows_ if r["t0"] <= f / FPS30], key=lambda r: -r["t0"])
                for slot, r in enumerate(vis):
                    draw_row(img, 4 + slot * PITCH, r["k"], r["v"], 80, r.get("border", True), thick)
                if scale != 1.0:
                    img = cv2.resize(cv2.resize(img, None, fx=1 / scale, fy=1 / scale, interpolation=cv2.INTER_AREA), (W, H), interpolation=cv2.INTER_CUBIC)
                canvas = np.full((1080, 1920, 3), (60, 70, 60), np.uint8)
                canvas[32:32 + H, 1112:1112 + W] = img
                pr.stdin.write(canvas.tobytes())
            pr.stdin.close()
            pr.wait()
            dec = subprocess.run(["ffmpeg", "-v", "error", "-i", str(clip), "-vf", f"crop={W}:{H}:1112:32,format=bgr24", "-f", "rawvideo", "-"], capture_output=True).stdout
            frs = np.frombuffer(dec, np.uint8).reshape(-1, H, W, 3)
            tr = M.BorderTracker(FPS30, keep_crops=False)
            for f in range(len(frs)):
                tr.feed(f, np.ascontiguousarray(frs[f]))
            tt = tr.finish()
            check([t["first"] for t in tt] == [30, 84] and [t["hits"] for t in tt] == [120, 66],
                  f"H.264 4:2:0 crf {crf}, outline {thick} px, source stretched x{scale}: exactly the 2 outlined rows, every frame ({[(t['first'], t['hits']) for t in tt]})")
        # classification of rows (fake reads)
        def one(k, v, icon="gun"):
            sc = make_sidecar([make_track(0, 20, 120, [(k, v)] * 2, icon)])
            return M.border_analysis(sc, {})
        a = one("enemy", "fireaxe")
        check(not a["kills"] and a["deaths"] == [round(20 / FPS30, 3)], "my name on the right = death, not a kill")
        a = one("enemy", "火斧")
        check(not a["kills"] and len(a["deaths"]) == 1, "'火斧' on the right = death")
        a = one("fireaxe + mate", "victim")
        check(len(a["kills"]) == 1, "'fireaxe + mate' = kill")
        a = one("mate + fireaxe", "victim")
        check(not a["kills"] and any("assist" in j["reason"] for j in a["rej"]), "'mate + fireaxe' = assist, not a kill")
        a = one("fireaxe 火斧 + mixani3m", "chara racing (supreme)")
        check(len(a["kills"]) == 1, "'fireaxe 火斧 + mixani3m' = kill")
        a = one("fireaxe", "victim", "util")
        check(not a["kills"] and any("utility" in j["reason"] for j in a["rej"]), "a small / square icon row = utility, not a kill")
        a = one("qwxzvbn", "Zorro")
        check(len(a["kills"]) == 1 and not a["kills"][0]["name_read"] and "unreadable" in a["kills"][0]["why"], "outlined row, weapon icon, no name match on the right = 'kill (name unreadable, border confirmed)'")
        a = one("Zorro", "f1reaxe")
        check(not a["kills"] and len(a["deaths"]) == 1, "'f1reaxe' on the right (OCR confusion) = death")
        a = one("火茶", "Zorro")
        check(len(a["kills"]) == 1, "'火茶' (garbled CJK name) first on the left = kill")
        sc = make_sidecar([make_track(0, 1, 100, [("fireaxe", "ThePOstMen")] * 2)])
        a = M.border_analysis(sc, {})
        check(not a["kills"] and any("pre-clip" in j["reason"] for j in a["rej"]), "a row on screen at the clip start = pre-clip, not a kill")
        sc = make_sidecar([make_track(0, 50, 100, [("fireaxe", "A1")] * 2), make_track(1, 60, 100, [("fireaxe", "B1")] * 2)])
        sc["tracks"][0]["votes"][0] = fake_vote("fireaxe", "Zorro")
        # re-reads with new spellings of ONE row = one kill
        sc = make_sidecar([make_track(0, 50, 150, [("fireaxe", "ThePOstMen"), ("flreaxe", "ThePOstMan"), ("fireaxo", "Th3POstMen")])])
        a = M.border_analysis(sc, {})
        check(len(a["kills"]) == 1, "a row read three times with new spellings = ONE kill (a track is one event)")
        # two rows of the same victim in one fight: > 1 s apart = two kills; < 1 s (border flicker) = one kill
        rows = [dict(t0=1.0, t1=3.0, k="fireaxe", v="ThePOstMen"), dict(t0=4.6, k="fireaxe", v="ThePOstMen")]
        tracks, a = run_frames(rows, 210, [[("fireaxe", "ThePOstMen")] * 2] * 2)
        check(len(a["kills"]) == 2, f"two rows of the same victim, first gone for 1.6 s = two kills ({kill_ts(a)})")
        rows = [dict(t0=1.0, t1=3.0, k="fireaxe", v="ThePOstMen"), dict(t0=3.5, k="fireaxe", v="ThePOstMen")]
        tracks, a = run_frames(rows, 210, [[("fireaxe", "ThePOstMen")] * 2] * 2)
        check(len(a["kills"]) == 1, f"the same row back after 0.5 s (border flicker) = one kill ({kill_ts(a)})")
        # kills-per-round cap keeps its rule: more than 5 kills in a round, weakest 1-2 frame reads go
        tr_ = [make_track(i, 40 + 60 * i, 100 + 60 * i, [("fireaxe", f"Victim{i}")] * 2) for i in range(6)]
        tr_[3]["hits"] = 2
        a = M.border_analysis(make_sidecar(tr_, 500), {})
        check(len(a["kills"]) == 5 and any("more than 5" in j["reason"] for j in a["rej"]), "more than 5 kills in one round: the weakest read goes (existing rule)")
        # a border-confirmed kill without a gunshot is kept; a death locks the 8 s after it
        pool_item = {"rec": {"path": __file__, "audio": True, "game": "cs2"}, "kills": M.border_analysis(make_sidecar([make_track(0, 60, 120, [("qwxzvbn", "Zorro")] * 2)]), {})["kills"],
                     "deaths": [], "revives": [], "vis": [], "rej": []}
        real_go, old_d = M.gun_onsets, M.use_data_dir(Path(tempfile.mkdtemp(prefix="t681v_")))      # verified_kills writes its onset cache: never the real one
        M.gun_onsets = lambda rec, cache=None, cfg=None: [[30.0, 5.0]]
        try:
            st = M.verified_kills([pool_item], {})
        finally:
            M.gun_onsets = real_go
            M.restore_data_dir(old_d)
        check(len(pool_item["kills"]) == 1 and st["kept"] == 1, "a border-confirmed kill with NO gunshot near it is never rejected")
        # fixtures of the named clips (3, 3, 2, 1 kills)
        fixtures = {
            "Counter-strike 2 2025.02.08 - 19.48.57.15.DVR_1.mp4": (3, [("flreaxo", "ThePOstMen^^"), ("f1reaxo 火茶", "chara racing (supreme)"), ("flreaxoo 火年", "Markusko")], None),
            "Counter-strike 2 2025.02.08 - 19.48.57.15.DVR_1_1.mp4": (3, [("flreaxo", "ThePOstMen^^"), ("f1reaxo 火茶", "chara racing (supreme)"), ("flreaxoo 火年", "Markusko")], None),
            "Counter-strike 2 2025.02.08 - 19.48.57.15.DVR.mp4": (3, [("fireaxe", "ThePOstMen^^"), ("fireaxe", "chara racing (supreme)"), ("flreaxo", "Markusko")], 2),
            "Counter-strike 2 2025.02.08 - 19.53.38.16.DVR.mp4": (2, [("fireaxe 火斧 + mixani3m", "chara racing (supreme)"), ("fireaxe 火斧 + iluHA(csgorun.com)", "шыбиди туолет")], None),
            "Counter-strike 2 2025.02.08 - 15.58.03.11.DVR.mp4": (1, [("flreaxo 火茶", "AWP victim")], None),
        }
        for name, (want, kr, old_want) in fixtures.items():
            tr_ = [make_track(i, 45 + 75 * i, 130 + 75 * i, [r] * 2) for i, r in enumerate(kr)]
            a = M.border_analysis(make_sidecar(tr_, 600), {})
            deaths = a["deaths"]
            old_txt = ""
            if old_want is not None or "DVR_1" in name:                                # the name-based list on the same rows (garbled reads)
                ocr = []
                for i, (k_, v_) in enumerate(kr):
                    n_ = 12 if (i < 2 or old_want is None) else 1                      # the third row of DVR.mp4 has ONE sighting
                    for s in range(n_):
                        f = 3 * (3 + 5 * i + s) + 12 * i
                        bx, bl = (lambda vv: (vv["boxes"], vv["blobs"]))(fake_vote(k_, v_))
                        ocr.append([f, f, [b + [f] for b in bx], bl])
                e = {"ocr": sorted(ocr, key=lambda o: o[0]), "frames": 600, "v_off": 0.0, "game": "cs2"}
                ao = M.analyse_entry(e, {}, "cs2")
                old_txt = f", name-based list on the same garbled reads: {len(ao['kills'])}"
                if old_want is not None:
                    check(len(ao["kills"]) == old_want, f"fixture {name[-24:]}: name-based list gives {old_want} (as on the real clip)")
                else:
                    check(len(ao["kills"]) == 0, f"fixture {name[-24:]}: name-based list gives 0 (as on the real clip)")
            check(len(a["kills"]) == want and not deaths, f"fixture {name[-30:]}: {len(a['kills'])} kills (expected {want}), no death{old_txt}")


# ===================================================================================================== 2. end to end on a generated clip
def part_e2e(tmp):
    with section("real decode + OCR on a generated CS2 clip (sidecar, lazy build, planner feed)"):
        old = M.use_data_dir(tmp / "e2e")
        real_sc, real_here = M.scan_clips, M.HERE
        M.HERE = tmp / "here"
        M.HERE.mkdir(exist_ok=True)
        try:
            M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir="", clip_dirs={"valorant": [], "cs2": [str(tmp / "cs2clips")]}))
            (tmp / "cs2clips").mkdir(parents=True, exist_ok=True)
            clip = tmp / "cs2clips" / "Counter-strike 2 2025.02.08 - 19.48.57.15.DVR_1.mp4"
            rows = [dict(t0=1.0, k="fireaxe", v="ThePOstMen"), dict(t0=2.0, k="randomguy", v="otherguy", border=False),
                    dict(t0=2.6, k="mate + fireaxe", v="Markusko"), dict(t0=3.4, k="qxzkvw", v="Zorrobanda"), dict(t0=6.0, k="enemyzed", v="fireaxe")]
            n = 8 * FPS30
            rx, ry = 1112, 32
            p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "1920x1080", "-r", str(FPS30), "-i", "-",
                                  "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18", "-pix_fmt", "yuv420p", str(clip)], stdin=subprocess.PIPE)
            for fr in render(rows, n):
                canvas = np.full((1080, 1920, 3), (60, 70, 60), np.uint8)
                canvas[ry:ry + H, rx:rx + W] = fr
                p.stdin.write(canvas.tobytes())
            p.stdin.close()
            p.wait()
            M.use_data_dir(tmp / "e2e")
            rec = M.probe_video(str(clip))
            rec.update(path=str(clip), game="cs2", bars=False, bar_sig="")
            det = M.Detector("cs2")
            M.ocr_engine()
            t0 = time.time()
            sc = M.border_build(rec, det, M.load_config())
            print(f"      cost of the border pass on this clip: {sc['frames']} frames at {sc['fps']} fps: decode+track {sc['decode_secs']}s "
                  f"= {sc['ms_per_frame']} ms/frame, OCR of {len(sc['tracks'])} rows {sc['ocr_secs']}s, total {sc['secs']}s")
            check(len(sc["tracks"]) == 4, f"4 outlined rows found in the decoded 4:2:0 clip (the unbordered row ignored): {len(sc['tracks'])}")
            a = M.border_analysis(sc, M.load_config())
            check(len(a["kills"]) == 2 and a["deaths"] and abs(a["deaths"][0] - 6.0) < 0.2, f"kills {kill_ts(a)}, death {a['deaths']} (2 kills, death at 6.0)")
            check(abs(a["kills"][0]["t"] - 1.0) <= 0.1 and abs(a["kills"][1]["t"] - 3.4) <= 0.1, "kill times = first appearance of the rows (1.0 s and 3.4 s)")
            check(any("assist" in j["reason"] for j in a["rej"]), "'mate + fireaxe' read from the video = assist")
            check([k["name_read"] for k in a["kills"]] == [True, False], "the clean row is read, the garbled one is 'name unreadable, border confirmed'")
            check(M.border_load(rec, det) is not None and (M.BORDER_DIR).exists() and len(list(M.BORDER_DIR.glob("*.json"))) == 1, "sidecar written to cs2_rows_v1 (one file)")
            check(not (M.DATA / "kills_v5").exists() or not list((M.DATA / "kills_v5").glob("*.json")), "the real kill cache was not written")
            # lazy build happens once
            t1 = time.time()
            res = M.border_build_many([rec], M.load_config(), det)
            check(res == {} and time.time() - t1 < 1.0, "a clip with a sidecar is not built again")
            # analyse_clip_entry: border list replaces the name list; without a sidecar the name list is used
            entry = {"ocr": [], "frames": 1, "v_off": 0.0, "game": "cs2", "names": ["fireaxe", "火斧"]}
            b = M.analyse_clip_entry(rec, entry, M.load_config(), "cs2")
            check(b.get("border") and len(b["kills"]) == 2, "with the sidecar the border list replaces the name-based list")
            rec2 = dict(rec, path=str(clip) + ".other.mp4")
            Path(rec2["path"]).write_bytes(b"x" * 100)
            b2 = M.analyse_clip_entry(rec2, entry, M.load_config(), "cs2")
            check(not b2.get("border") and b2["kills"] == [], "without a sidecar: the V6.7.2 name-based behaviour (unchanged)")
            # game_pool (planner input): the border kills come through, with the death lock applied by verified_kills
            M.scan_clips = lambda cfg, rescan=False: [dict(rec)]
            store = M.load_kills_cache()
            store.put(M.kills_key(rec, "cs2", det), entry)
            pool, st = captured(M.game_pool, M.load_config(), "cs2")[1]
            check(len(pool) == 1 and [round(k["t"], 1) for k in pool[0]["kills"]] == [1.0, 3.4] and pool[0]["deaths"] and pool[0]["kills"][0].get("shot") is False,
                  f"game_pool feeds the planner the border kills {[k['t'] for k in pool[0]['kills']] if pool else None} (no gunshot in the clip: kept)")
            # planner: the take covers EVERY kill of the fight; its end follows the last kill's FIRST row appearance
            ks = [dict(k, shot=False) for k in a["kills"]]
            cfg = M.load_config()
            it = {"rec": dict(rec, dur=8.0, v_off=0.0, audio=False), "kills": ks, "deaths": [], "revives": [], "vis": [], "rej": []}
            import random
            evs, _n = (lambda r: (r[0], r[1]) if isinstance(r, tuple) else (r, []))(M.build_events([it], "cs2", cfg, random.Random(1)))
            ev = evs[0] if evs else None
            check(ev is not None and ev["n"] == 2 and abs(ev["rows"][-1] - 3.4) < 0.02 and abs(ev["rows"][0] - 1.0) < 0.02,
                  f"planner event: both kills, rows = first appearance {ev['rows'] if ev else None}")
            win = M.row_tail_window(ev, False, (0.2, 0.5), 5.0)
            check(win is not None and win[0] >= (ev["rows"][-1] - ev["times"][-1]) + M.ROW_TAIL - 1e-6,
                  f"the take lasts >= {M.ROW_TAIL} s after the LAST kill row (tail window {win}); a kill already in the feed extends the take, it is not cut")
            # the diagnostics: rowdebug (one clip, --all) and bordercache; they never write the kill cache or region files
            snap = {str(q): q.stat().st_mtime_ns for q in (M.DATA).rglob("*") if q.is_file() and "kills_v" in str(q) or q.name.startswith("detect_")}
            txt, _ = captured(M.cmd_rowdebug, types.SimpleNamespace(game="cs2", clip=clip.name, all=False, rebuild=False))
            imgs = list((M.HERE / "rowdebug_images" / M.re.sub(r"[^\w.-]+", "_", clip.stem)).glob("row*.png"))
            check("border tracks (4)" in txt and "KILL" in txt and "DEATH" in txt and "old name-based kills" in txt and "difference:" in txt and "ThePOstMen" in txt,
                  "rowdebug prints the tracks, their classification with the OCR text of both sides, the old name-based kills and the difference")
            check(len(imgs) == 4 and all(cv2.imread(str(q)) is not None for q in imgs), f"rowdebug saved a crop per track at its clearest frame ({[q.name for q in imgs]})")
            txt, _ = captured(M.cmd_rowdebug, types.SimpleNamespace(game="cs2", clip=None, all=True, rebuild=False))
            check((M.HERE / "rowdebug_cs2.txt").exists() and clip.name[:40] in txt and "total:" in txt, "rowdebug --all prints one table and saves rowdebug_cs2.txt")
            txt, _ = captured(M.cmd_bordercache, types.SimpleNamespace(game="cs2", all=False))
            check("0 sidecars built" in txt, "bordercache cs2: nothing to build when the sidecar exists")
            now = {str(q): q.stat().st_mtime_ns for q in (M.DATA).rglob("*") if q.is_file() and "kills_v" in str(q) or q.name.startswith("detect_")}
            check(now == snap and not (M.DATA / "detect_cs2.json").exists(), "the diagnostics did not touch the kill cache or the region files")
        finally:
            M.scan_clips, M.HERE = real_sc, real_here
            M.restore_data_dir(old)


# ===================================================================================================== 3. rescan one region group
REG_A, REG_B = [0.58, 0.03, 1.0, 0.40], [0.56, 0.06, 1.0, 0.41]


def build_group_cache(tmp, game, n_b=83, n_a=2, n_none=4):
    d = tmp / f"grp_{game}"
    d.mkdir(parents=True, exist_ok=True)
    store, recs = M.load_kills_cache(), []
    HB = M.region_stamp(REG_B)
    for i in range(n_b + n_a + n_none):
        p = d / f"2025.10.{10 + i % 9} - 19.06.{i:02d}.mp4"
        p.write_bytes(b"x" * (50 + i))
        recs.append({"path": str(p), "game": game, "w": 1920, "h": 1080, "dur": 10.0, "bars": False, "bar_sig": ""})
        if i < n_b:
            store.put(f"{M.file_key(str(p))}|{game}|{HB}{M.ALGO}nb", {"ocr": [], "frames": 1, "game": game, "v_off": 0.0, "region": REG_B, "marker": f"old{i}"})
        elif i < n_b + n_a:
            store.put(f"{M.file_key(str(p))}|{game}|{M.Detector(game).d['stamp']}{M.ALGO}nb", {"ocr": [], "frames": 1, "game": game, "v_off": 0.0, "region": REG_A})
    return recs, HB


def part_rescan(tmp):
    with section("rescan one region group (engine, Valorant backup, CLI, GUI)"):
        for game in ("cs2", "valorant"):
            old = M.use_data_dir(tmp / f"rg_{game}")
            real = (M.scan_clips, M.scan_clip, M.ensure_bars, M.ocr_engine, M.border_build)
            try:
                M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir="", clip_dirs={"valorant": [], "cs2": []}))
                recs, HB = build_group_cache(tmp, game)
                HA = M.Detector(game).d["stamp"]
                M.scan_clips = lambda cfg, rescan=False: [dict(r) for r in recs]
                M.ensure_bars = lambda cfg, force=False: None
                M.ocr_engine = lambda: None
                scanned = []

                def fake_scan(path, rec, det, cfg, scale=None):
                    scanned.append(path)
                    return {"v": M.CACHE_V, "names": M.names_for_cache(rec.get("game")), "ocr": [], "frames": 1, "size": [det.dw, det.dh], "region": det.d["region"],
                            "v_off": 0.0, "ocr_calls": 0, "secs": 0.0, "game": rec.get("game")}
                M.scan_clip = fake_scan
                M.border_build = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no video in this test"))
                info = M.rescan_group_clips(game, HB)
                check(len(info["recs"]) == 83 and info["current"] == HA and info["missing"] == 0,
                      f"{game}: the list has exactly the 83 clips with an entry under {HB} and none under the current {HA} ({len(info['recs'])}; 2 clips already under {HA} and 4 never scanned are not in it)")
                before = {p.name for p in M.load_kills_cache().dir.glob("*.json")}
                # No: nothing scanned (the GUI's No never reaches rescan_group); CLI without --confirm changes nothing
                txt, _ = captured(M.cmd_rescanhash, types.SimpleNamespace(game=game, hash=HB, confirm=False))
                after = {p.name for p in M.load_kills_cache().dir.glob("*.json")}
                check(not scanned and before == after and "83" in txt and "Nothing was changed" in txt and not M.VAL_BACKUP.exists(),
                      "CLI without --confirm: prints the list and the count (83), changes nothing, scans nothing")
                # refused while a job runs
                M.job_enter("render")
                try:
                    txt, _ = captured(M.cmd_rescanhash, types.SimpleNamespace(game=game, hash=HB, confirm=True))
                finally:
                    M.job_exit()
                check(not scanned and "refused" in txt, "refused while a scan or render is running")
                # the current region's own hash: nothing to do
                txt, _ = captured(M.cmd_rescanhash, types.SimpleNamespace(game=game, hash=HA, confirm=True))
                check(not scanned and "current" in txt, "the current region's own row has nothing to rescan")
                # Yes: scans only the 83, adds entries, never deletes
                txt, _ = captured(M.cmd_rescanhash, types.SimpleNamespace(game=game, hash=HB, confirm=True))
                store = M.load_kills_cache()
                new_ok = sum(M.kills_key(r, game, M.Detector(game)) in store for r in info["recs"])
                old_ok = sum(store.get(f"{M.file_key(r['path'])}|{game}|{HB}{M.ALGO}nb", {}).get("marker", "").startswith("old") for r in info["recs"])
                check(len(scanned) == 83 and set(scanned) == {r["path"] for r in info["recs"]} and new_ok == 83 and old_ok == 83,
                      f"Yes: scans only those 83 clips ({len(scanned)}), adds 83 entries under {HA}, the 83 old entries under {HB} stay untouched")
                idx = M._cache_index()
                check(sum(1 for lst in idx.values() if any(e[3] == HB for e in lst)) == 83, "the old group still has 83 entries")
                if game == "valorant":
                    bk = M.load_json(M.VAL_BACKUP, {})
                    check(len(bk) == 83 and all(v["e"].get("marker", "").startswith("old") for v in bk.values()),
                          "Valorant: every old entry was copied into valorant_cache_backup.json first (83, once each)")
                    first = json.dumps(bk, sort_keys=True)
                    M.scan_clips = lambda cfg, rescan=False: [dict(r) for r in recs]
                    for r in info["recs"][:3]:                                           # a second pass must not touch the backup
                        M.backup_valorant_entry(M.load_kills_cache(), f"{M.file_key(r['path'])}|{game}|{HB}{M.ALGO}nb")
                    check(json.dumps(M.load_json(M.VAL_BACKUP, {}), sort_keys=True) == first, "the first copy per clip is kept; the backup is never overwritten")
                else:
                    check(not M.VAL_BACKUP.exists(), "CS2: no Valorant backup file")
                again = M.rescan_group_clips(game, HB)
                check(not again["recs"], "after the rescan nothing is left to rescan")
            finally:
                M.scan_clips, M.scan_clip, M.ensure_bars, M.ocr_engine, M.border_build = real
                M.restore_data_dir(old)
        # GUI: button, disabled on the current row, question text, No / Yes, refused while busy, cancel
        old = M.use_data_dir(tmp / "rg_gui")
        real = (M.scan_clips, M.scan_clip, M.ensure_bars, M.ocr_engine, M.messagebox.askyesno, M.messagebox.showinfo, M.messagebox.showerror)
        try:
            M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir="", clip_dirs={"valorant": [], "cs2": []}))
            M.ensure_bars = lambda cfg, force=False: None
            recs, HB = build_group_cache(tmp / "gui", "valorant", n_b=83, n_a=0, n_none=0)
            HA = M.Detector("valorant").d["stamp"]
            M.scan_clips = lambda cfg, rescan=False: [dict(r) for r in recs]
            M.ocr_engine = lambda: None
            scanned, asked, infos = [], [], []

            def fake_scan(path, rec, det, cfg, scale=None):
                scanned.append(path)
                return {"v": M.CACHE_V, "names": M.names_for_cache(rec.get("game")), "ocr": [], "frames": 1, "size": [det.dw, det.dh], "region": det.d["region"],
                        "v_off": 0.0, "ocr_calls": 0, "secs": 0.0, "game": rec.get("game")}
            M.scan_clip = fake_scan
            ans = [False]
            M.messagebox.askyesno = lambda t, m, **k: (asked.append(m), ans[0])[1]
            M.messagebox.showinfo = lambda t, m, **k: infos.append(m)
            M.messagebox.showerror = lambda *a, **k: None
            app = M.App(0)
            try:
                root = app.root
                root.update()
                app.nb.select(app.tabs["Settings"])
                for _ in range(10):
                    root.update()
                    time.sleep(0.05)
                app.rp_game.set("valorant")
                app.rp_refresh()
                ids = {v["hash"] + ":" + v["kind"]: i for i, v in app.rp_rows.items()}
                check("region:rescan" in app.named and "Rescan this group" in str(app.named["region:rescan"].cget("text")), "Settings > Killfeed region has the button 'Rescan this group to the current region'")
                app.rp_tree.selection_set(ids[f"{HB}:cache"])
                for _ in range(4):
                    root.update()
                check("disabled" not in app.b_rp_resc.state(), "enabled for an older group")
                cur_id = next(i for i, v in app.rp_rows.items() if v["kind"] == "current")
                app.rp_tree.selection_set(cur_id)
                for _ in range(4):
                    root.update()
                check("disabled" in app.b_rp_resc.state(), "disabled for the row that is the current region")
                app.rp_tree.selection_set(ids[f"{HB}:cache"])
                for _ in range(4):
                    root.update()
                asked.clear()
                app.rp_rescan()
                check(asked == [f"Rescan 83 clips from {HB} to the current region {HA}?" + asked[0][len(f'Rescan 83 clips from {HB} to the current region {HA}?'):]] and asked[0].startswith(f"Rescan 83 clips from {HB} to the current region {HA}?"),
                      "the question: 'Rescan N clips from <hash> to the current region <hash>?'")
                check(not scanned and not app.busy, "No: nothing is scanned")
                ans[0] = True
                app.busy = True                                                            # a scan / render is running
                infos.clear()
                asked.clear()
                app.rp_rescan()
                check(not asked and not scanned and infos and "running" in infos[-1], "refused while a scan or render is running (no question, no scan)")
                app.busy = False
                app.rp_rescan()
                for _ in range(600):
                    root.update()
                    time.sleep(0.02)
                    if not app.busy and len(scanned) >= 83:
                        break
                check(len(scanned) == 83 and len(M.load_json(M.VAL_BACKUP, {})) == 83, f"Yes: 83 clips scanned under the current region, 83 Valorant backups ({len(scanned)})")
                check(sum(1 for lst in M._cache_index().values() if any(e[3] == HB for e in lst)) == 83 and sum(1 for lst in M._cache_index().values() if any(e[3] == HA for e in lst)) == 83,
                      "old entries stay, 83 new entries added")
                # cancel: clips already scanned keep their entries
                for r in recs:
                    for e in list(M._cache_index().get((os.path.basename(r["path"]).lower(), str(os.stat(r["path"]).st_size), str(int(os.stat(r["path"]).st_mtime)), "valorant"), [])):
                        if e[3] == HA:
                            Path(e[0]).unlink()
                scanned.clear()

                def cancelling_scan(path, rec, det, cfg, scale=None):
                    r_ = fake_scan(path, rec, det, cfg)
                    if len(scanned) >= 5:
                        M.CANCEL.set()
                    return r_
                M.scan_clip = cancelling_scan
                M.CANCEL.clear()
                info = M.rescan_group_clips("valorant", HB)
                captured(M.rescan_group, "valorant", HB, M.load_config(), info)
                M.CANCEL.clear()
                done = sum(M.kills_key(r, "valorant", M.Detector("valorant")) in M.load_kills_cache() for r in recs)
                check(0 < done < 83 and sum(1 for lst in M._cache_index().values() if any(e[3] == HB for e in lst)) == 83,
                      f"Cancel: {done} clips scanned before it keep their new entries, old entries intact")
            finally:
                app.root.destroy()
        finally:
            M.scan_clips, M.scan_clip, M.ensure_bars, M.ocr_engine, M.messagebox.askyesno, M.messagebox.showinfo, M.messagebox.showerror = real
            M.restore_data_dir(old)


# ===================================================================================================== 4. search bar position
def part_search(tmp):
    with section("search bar on the Show row"):
        old = M.use_data_dir(tmp / "sdata")
        real = (M.scan_clips, M.ensure_bars, M.messagebox.showinfo, M.messagebox.showerror, M.messagebox.askyesno)
        try:
            M.save_json(M.CONFIG_PATH, dict(M.load_config(), mp3_dir="", clip_dirs={"valorant": [], "cs2": []}))
            M.ensure_bars = lambda cfg, force=False: None
            M.messagebox.showinfo = M.messagebox.showerror = lambda *a, **k: None
            M.messagebox.askyesno = lambda *a, **k: True
            d = tmp / "sclips"
            d.mkdir(exist_ok=True)
            specs = [("Apex ace round.mp4", "2026-09-01", 3, "Valorant/Ranked", "L_VAL_V6.7.4_2026-10-06"), ("clutch 1v3.mp4", "2026-09-03", 5, "Valorant/Ranked", ""),
                     ("Replay 2026-06-25.mov", "2026-06-25", 2, "Valorant/Replays", "S_VAL_V6.5_2026-09-01"), ("Plain kill.mp4", "2026-08-15", 1, "Valorant/Unranked", "")]
            clips = []
            for nm, day, k, folder, title in specs:
                p = d / nm
                p.write_bytes(b"\0" * 10)
                ts = time.mktime(time.strptime(day + " 12:00", "%Y-%m-%d %H:%M"))
                os.utime(p, (ts, ts))
                clips.append({"path": str(p), "name": nm, "folder": folder, "mtime": ts, "dur": 10, "kills": k, "ks": [], "used": "2026-10-06" if title else "", "used_label": title})
            recs = [{"path": c["path"], "game": "valorant", "dur": 10, "w": 1920, "h": 1080} for c in clips]
            M.scan_clips = lambda cfg, rescan=False: [dict(r) for r in recs]
            app = M.App(0)
            try:
                root = app.root
                root.geometry("1500x900+0+0")
                app.nb.select(app.tabs["Manual"])
                for _ in range(30):
                    root.update()
                    time.sleep(0.03)
                    if not app.busy and not app.pending:
                        break
                show = app.named["Used filter"]
                for w in (app.e_csearch, next(b for b in app.buttons if str(b.cget("text")) == "Clear")):
                    check(str(w.master) == str(show.master), f"{type(w).__name__} sits in the same row as the 'Show' dropdown")
                lbl = next(c for c in show.master.winfo_children() if str(c.cget("textvariable") if "textvariable" in c.keys() else "") == str(app.m_cshown))
                check(lbl is not None, "the 'N ticked, M shown' label is on that row too")
                root.update()
                check(app.e_csearch.winfo_rootx() > show.winfo_rootx() and abs(app.e_csearch.winfo_rooty() - show.winfo_rooty()) < 12,
                      "the search box is to the RIGHT of 'Show' on the same line")
                more = app.named["More filters"]
                check(more.winfo_rootx() > app.e_csearch.winfo_rootx() + app.e_csearch.winfo_width(), "it uses the empty space: the 'More' dropdown stays at the right")
                check(not any(str(getattr(w, "master", "")) != str(show.master) and "Search clips" in str(w.cget("text")) for w in app.root.winfo_children() if "text" in w.keys()),
                      "no separate search line")
                app.clips = [dict(c) for c in clips]
                app.byp = {c["path"]: c for c in app.clips}
                app.scan_active = False
                tree = app.ctree

                def shown(txt):
                    app.m_csearch.set(txt)
                    for _ in range(8):
                        root.update()
                        time.sleep(0.03)
                    return sorted(Path(i).name for i in tree.get_children())
                check(shown("ACE") == ["Apex ace round.mp4"], "name")
                check(shown("2026-06-25") == ["Replay 2026-06-25.mov"], "date")
                check(shown("l_val_v6.7.4") == ["Apex ace round.mp4"], "montage title")
                check(shown("unranked") == ["Plain kill.mp4"], "folder")
                shown("")
                app.ticked = {clips[0]["path"], clips[1]["path"]}
                check(shown("plain") == ["Plain kill.mp4"] and len(app.ticked) == 2 and app.m_cshown.get() == "2 ticked, 1 shown", f"hidden ticks stay; label '{app.m_cshown.get()}'")
            finally:
                app.root.destroy()
        finally:
            M.scan_clips, M.ensure_bars, M.messagebox.showinfo, M.messagebox.showerror, M.messagebox.askyesno = real
            M.restore_data_dir(old)


# ===================================================================================================== 5. Valorant guard
FROZEN = ["analyse_entry", "ocr_rows", "classify_row", "merge_variants", "drop_fake_kills", "kills_key", "Detector", "scan_frames", "scan_clip", "ocr_frame",
          "name_match", "_row_match", "_row_match_v4", "_analyse_entry_v4", "resurrect_rows", "verified_kills", "gun_onsets", "_relink_or_explain", "weapon_class",
          "side_colour", "weapon_blobs", "frame_stream", "region_filter", "region_px", "build_events", "make_event", "refine_kill", "place", "row_tail_window",
          "backup_valorant_entry", "KillStore", "bright_mask", "_appear", "_band_changed"]


def part_valorant(tmp):
    with section("Valorant guard (V6.8 code vs this code on the same entries)"):
        import inspect
        base_src = None
        for ref in ("origin/v6.8", "v6.8"):
            r = subprocess.run(["git", "show", f"{ref}:montage.py"], cwd=str(HERE), capture_output=True)
            if r.returncode == 0 and r.stdout:
                base_src, base_ref = r.stdout.decode("utf-8"), ref
                break
        if base_src is None:
            print("      git baseline (origin/v6.8) not available here: guard skipped (not a failure)")
            return
        bdir = tmp / "base"
        bdir.mkdir(exist_ok=True)
        (bdir / "montage.py").write_text(base_src, encoding="utf-8")
        os.environ["MONTAGER_DATA"] = str(tmp / "base_data")
        spec = importlib.util.spec_from_file_location("montage_base", str(bdir / "montage.py"))
        B = importlib.util.module_from_spec(spec)
        sys.modules["montage_base"] = B
        spec.loader.exec_module(B)
        del os.environ["MONTAGER_DATA"]
        diffs = []
        for nm in FROZEN:
            try:
                if inspect.getsource(getattr(M, nm)) != inspect.getsource(getattr(B, nm)):
                    diffs.append(nm)
            except Exception as ex:
                diffs.append(f"{nm} ({ex})")
        consts = [c for c in ("ALGO", "CACHE_V", "FPS", "NORM_W", "NORM_H", "NAME_MIN", "OCR_GAP", "TRACK_KEEP_S", "DEFAULT_REGION", "DEFAULT_PLAYER_NAMES") if getattr(M, c) != getattr(B, c)]
        check(not diffs and not consts, f"{len(FROZEN)} detection / planner / backup functions are source-identical to {base_ref}; constants equal (differences: {diffs + consts})")
        # same generated Valorant OCR entries through both: 0 differences
        rng = np.random.default_rng(7)
        names = ["fireaxe", "Zorro", "enemy1", "player2", "mate", "Kristof", "f1reaxe", "xX_pro_Xx"]
        entries = []
        for e_i in range(40):
            ocr = []
            for s in range(20):
                f = 3 * s + e_i
                rows = []
                for r_i in range(int(rng.integers(0, 4))):
                    k, v = names[int(rng.integers(0, len(names)))], names[int(rng.integers(0, len(names)))]
                    if rng.random() < 0.3:
                        k = k + " + " + names[int(rng.integers(0, len(names)))]
                    vv = fake_vote(k, v, "gun" if rng.random() < 0.8 else "util")
                    off = r_i * 30
                    rows.append((vv["boxes"], vv["blobs"], off))
                boxes, blobs = [], []
                for bx, bl, off in rows:
                    boxes += [[b[0], b[1] + off, b[2], b[3] + off, b[4], b[5], "r" if rng.random() < 0.5 else "g", f] for b in bx]
                    blobs += [[g[0], g[1] + off, g[2], g[3], g[4]] for g in bl]
                ocr.append([f, f, boxes, blobs])
            entries.append({"ocr": ocr, "frames": 70, "v_off": 0.0, "game": "valorant"})
        n_diff = 0
        for e in entries:
            a1 = json.dumps(M.analyse_entry(e, {}, "valorant"), sort_keys=True, default=str)
            a2 = json.dumps(B.analyse_entry(e, {}, "valorant"), sort_keys=True, default=str)
            a3 = json.dumps(M.analyse_clip_entry({"path": "x.mp4"}, e, {}, "valorant"), sort_keys=True, default=str)
            n_diff += (a1 != a2) + (a1 != a3)
        kills_n = sum(len(M.analyse_entry(e, {}, "valorant")["kills"]) for e in entries)
        check(n_diff == 0, f"Valorant: 0 differences on {len(entries)} generated entries ({kills_n} kills), analyse_entry and analyse_clip_entry vs {base_ref}")
        rec = {"path": str(tmp / "base" / "montage.py"), "w": 1920, "h": 1080, "bars": False, "bar_sig": ""}
        check(M.kills_key(rec, "valorant", M.Detector("valorant")) == B.kills_key(rec, "valorant", B.Detector("valorant")), "Valorant cache keys are identical")
        # the user's real Valorant cache (if there is one): same comparison
        real_dir = HERE / "montage_data" / f"kills_v{M.CACHE_V}"
        files = sorted(real_dir.glob("*.json"))[:4000] if real_dir.exists() else []
        if files:
            t0, n, nd = time.time(), 0, 0
            for fp in files:
                if time.time() - t0 > 40:
                    break
                try:
                    j = json.loads(fp.read_text(encoding="utf-8"))
                    e = j.get("e") or {}
                    if e.get("game") != "valorant" or "|valorant|" not in j.get("key", ""):
                        continue
                except Exception:
                    continue
                n += 1
                nd += json.dumps(M.analyse_entry(e, {}, "valorant"), sort_keys=True, default=str) != json.dumps(B.analyse_entry(e, {}, "valorant"), sort_keys=True, default=str)
            check(nd == 0, f"real cache: Valorant 0 differences on {n} cached entries ({time.time() - t0:.0f} s)")
        else:
            print("      (no real montage_data here: real-cache comparison skipped)")


# ===================================================================================================== 6. real clips (user's PC)
REAL_NAMES = ["Counter-strike 2 2025.02.08 - 19.48.57.15.DVR_1.mp4", "Counter-strike 2 2025.02.08 - 19.48.57.15.DVR.mp4",
              "Counter-strike 2 2025.02.08 - 19.53.38.16.DVR.mp4", "Counter-strike 2 2025.02.08 - 15.58.03.11.DVR.mp4", "Replay 2026-06-25 01-27-36.mov"]


def part_real():
    if os.environ.get("V681_REAL") == "0" or not list((HERE / "montage_data").glob("kills_v*/*.json")):
        print("== real clips: no montage_data here (or V681_REAL=0): skipped ==")
        return
    with section("real clips (printed only, never a failure)"):
        try:
            cfg = M.load_config()
            det = M.Detector("cs2")
            recs = M._cs2_recs(cfg, det=det)
            store = M.load_kills_cache()
            byname = {Path(r["path"]).name: r for r in recs}
            for nm in REAL_NAMES:
                r = byname.get(nm)
                if r is None:
                    print(f"      {nm}: not found in the CS2 clip folders")
                    continue
                d = M.rowdebug_clip(r, cfg, det, store, images=True)
                print(f"      {nm}: border kills {len(d['new'])} ({', '.join(M.ts(t) for t in d['new']) or '-'}), name-based {len(d['old']) if d['old'] is not None else 'not scanned'}, "
                      f"border pass {d['cost']}s")
            rows = []
            for r in recs:
                e = store.get(M.kills_key(r, "cs2", det))
                if not e or e.get("error"):
                    continue
                sc = M.border_load(r, det)
                old = [k["t"] for k in M.analyse_entry(e, cfg, "cs2")["kills"]]
                new = [k["t"] for k in M.border_analysis(sc, cfg)["kills"]] if sc else None
                rows.append((Path(r["path"]).name, len(old), None if new is None else len(new)))
            rows.sort(key=lambda x: -(abs(x[1] - x[2]) if x[2] is not None else -1))
            print(f"      before / after, {len(rows)} cached CS2 clips ({sum(1 for x in rows if x[2] is None)} without a sidecar yet: run python montage.py bordercache cs2 --all):")
            print(f"      {'clip':60} {'before':>6} {'after':>6}")
            for nm, o, n in rows:
                print(f"      {nm[:60]:60} {o:6d} {'-' if n is None else n:>6}")
            print(f"      total before {sum(x[1] for x in rows)}, after {sum(x[2] for x in rows if x[2] is not None)} (clips with a sidecar)")
        except Exception as ex:
            print(f"      real-clip part failed to run: {type(ex).__name__}: {ex}")


def main():
    tmp = Path(tempfile.mkdtemp(prefix="t681_"))
    part_border()
    part_e2e(tmp)
    part_rescan(tmp)
    part_search(tmp)
    part_valorant(tmp)
    part_real()
    print("\nsection times: " + ", ".join(f"{t.split(' (')[0]} {s:.0f}s" for t, s in SECTIONS))
    total = time.time() - T_ALL
    print(f"total test time {total:.0f} s" + ("" if total < 120 else "  (over the 2 minute target)"))
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
