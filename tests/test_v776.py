"""V7.7.6 tests (CS2 only). Sections (each prints ok / FAIL lines, the last line is ALL OK only when every check ran and passed):
  0) title-bar version V7.7.6, one entry on top of both changelogs
  1) BUG A, real frames: 2026.02.10 - 19.09.46.22 - the 'convulsive god' row is ONE row on screen from 0.5 s to 8.5 s (it shifts up when the rows above expire); the 2.8 s and 7.5 s
     'kills' are that row read again -> stale, no kill is left to open the take; the stale-row shift guard (unit variants on the real sidecar)
  2) BUG B, real frames: 2025.01.13 - 13.18.26.09 - the 4th kill's row first appears at ~5.7 s, the old time was 7.33 s; the dated time is the first appearance, the log says 'late read corrected'
  3) the second stale check (no gunshot before the row + victim of an early row) and the plan-time 'a kill row appears inside the take' assertion
  4) all cached CS2 clips: how many kill times moved by more than 0.5 s vs V7.7.5 (the 10 biggest listed), kill counts and merged-duplicate counts
  g) guards vs V7.7.5 (defaults): Valorant events / takes / cut lists identical; the real 7 Valorant clips; same-seed CS2 plans identical except for the clips named
Runs on a COPY of montage_data (V7_DATA_SRC picks the folder; the real folder is only read).   python tests\\test_v776.py   (parts: V776_PARTS=0,1,2,3,4,g)
The real Force New renders (CS2 + Valorant, sync report, transition check, the two clips of the bugs) are tests\\verify776.py."""
import copy
import json
import os
import random
import re
import shutil
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
from v696_common import check, section, FAILS, snapshot                                       # noqa: E402

REAL_DATA = ROOT / "montage_data"
T_ALL = time.time()
PARTS = {}
BASE_REF = "V7.7.5"
CLIP_A = "Counter-strike 2 2026.02.10 - 19.09.46.22.DVR.mp4"
CLIP_B1 = "Counter-strike 2 2025.01.13 - 13.18.16.08.DVR.mp4"
CLIP_B2 = "Counter-strike 2 2025.01.13 - 13.18.26.09.DVR.mp4"


def quiet(fn, *a, **k):
    keep = (M.out, M.LOGONLY)
    lines = []
    M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        return fn(*a, **k), lines
    finally:
        M.out, M.LOGONLY = keep


def load_base(ref, dst, tmp):
    """The montage.py of git ref `ref` as a second module, data folder = dst."""
    import importlib.util
    r = subprocess.run(["git", "show", f"{ref}:montage.py"], cwd=ROOT, capture_output=True)
    bdir = Path(tmp) / f"base_{ref}"
    bdir.mkdir(exist_ok=True)
    (bdir / "montage.py").write_bytes(r.stdout)
    env_old = os.environ.get("MONTAGER_DATA")
    os.environ["MONTAGER_DATA"] = str(dst)
    try:
        spec = importlib.util.spec_from_file_location(f"montage_base_{ref.replace('.', '')}", str(bdir / "montage.py"))
        B = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = B
        spec.loader.exec_module(B)
    finally:
        if env_old is None:
            os.environ.pop("MONTAGER_DATA", None)
        else:
            os.environ["MONTAGER_DATA"] = env_old
    return B


def rec_of(mod, name):
    cfg = mod.load_config()
    keep = (mod.out, mod.LOGONLY)
    mod.out = mod.LOGONLY = lambda *x: None
    try:
        return next((r for r in mod.scan_clips(cfg) if Path(r["path"]).name == name), None)
    finally:
        mod.out, mod.LOGONLY = keep


def row_presence(rec, tpl_t, tpl_box, times):
    """Frame-based: the grayscale patch of a row (killfeed region, 1920x1080 space) cut at tpl_t, searched in every frame of `times` (whole region): [(t, corr, y)]."""
    import cv2
    import numpy as np
    det = M.Detector("cs2")
    cfg = M.load_config()
    nb = det.dw * det.dh * 3

    def frame(t):
        r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", rec["path"], "-an", "-vf", M.region_filter(rec, det, cfg), "-frames:v", "1", "-f", "rawvideo",
                            "-pix_fmt", "bgr24", "-"], capture_output=True)
        return cv2.cvtColor(np.frombuffer(r.stdout[:nb], np.uint8).reshape(det.dh, det.dw, 3), cv2.COLOR_BGR2GRAY)
    x0, y0, x1, y1 = tpl_box
    tpl = frame(tpl_t)[y0:y1, x0:x1]
    res = []
    for t in times:
        g = frame(t)
        m = cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED)
        res.append((t, float(m.max()), int(np.unravel_index(int(m.argmax()), m.shape)[0])))
    return res


# ------------------------------------------------------------------------------------------------ 0) version + changelogs
def part_version(tmp):
    with section("0) title-bar version V7.7.6, one entry on top of both changelogs, readable history rules"):
        simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
        tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        hs, ht = re.findall(r"(?m)^## (.+)$", simple), re.findall(r"(?m)^## (.+)$", tech)
        check(M.APP_VERSION == "V7.7.6" and hs[0].startswith("V7.7.6") and ht[0].startswith("V7.7.6"), "APP_VERSION V7.7.6 and the entry on top of both files")
        blk = re.split(r"(?m)^## .+$", simple)[1]
        pts = [x for x in blk.splitlines() if x.startswith("- ")]
        check(1 <= len(pts) <= 4 and not re.search(r"KNOWN ISSUE|on hold|ABANDON", simple), f"readable entry: {len(pts)} plain points, no known-issue lines")
        check(len(hs[0].split(":", 1)[1].split()) in range(3, 9), "one headline of 3 to 8 words: " + hs[0].split(":", 1)[1].strip())
        check(not re.search(r"test_v|def |\.py|_|\(\)", blk), "no test names, function names or technical detail in the plain entry")
        check(sum(1 for h in hs if h.startswith("V7.7.6")) == 1 and sum(1 for h in ht if h.startswith("V7.7.6")) == 1, "one entry per version")


PARTS["0"] = part_version


# ------------------------------------------------------------------------------------------------ 1) BUG A
def part_bug_a(tmp):
    with section("1) BUG A: the 2026.02.10 opener - one row from 0.5 s to 8.5 s read as kills at 2.8 s and 7.5 s"):
        with PB.data_copy(M):
            cfg = M.load_config()
            rec = rec_of(M, CLIP_A)
            check(rec is not None, "the clip is in the library")
            if rec is None:
                return
            det = M.Detector("cs2")
            sc = M.border_load(rec, det)
            check(sc is not None, "its row sidecar exists")
            # frames: the row of 'convulsive god' (cut at 1.5 s, y 123..154 of the killfeed region) is absent at 0.0 / 0.25 s, then present in EVERY frame to 8.0 s (it slid up: several y positions)
            ts = [0.0, 0.25] + [0.75 + 0.25 * i for i in range(30)]
            pres = row_presence(rec, 1.5, (180, 123, 520, 154), ts)
            gone = [p for p in pres if p[0] < 0.4]
            there = [p for p in pres if 0.75 <= p[0] <= 8.0]
            check(all(p[1] < 0.8 for p in gone), f"frames 0.0 / 0.25 s: the row is not on screen yet ({[round(p[1], 2) for p in gone]})")
            check(all(p[1] >= 0.88 for p in there), f"frames 0.75 ... 8.0 s every 0.25 s: the SAME row on screen in every frame (min corr {min(p[1] for p in there):.2f})")
            ys = sorted({p[2] for p in there})
            check(len(ys) >= 3, f"... at {len(ys)} different feed positions {ys}: it shifted up as the rows above expired")
            late = [p for p in pres if p[0] > 8.6]
            check(not late, "(nothing after 8.5 s sampled: the row ends at 8.5 s)")
            # the analysis: neither 2.8 s nor 7.5 s is a kill
            b = M.border_analysis(sc, cfg, [])
            ts_ = [round(k["t"], 1) for k in b["kills"]]
            check(2.8 not in ts_ and 7.5 not in ts_ and 7.4 not in ts_, f"no kill at 2.8 s / 7.5 s any more: kills = {ts_}")
            stale = [r for r in b["rej"] if r["reason"].startswith("CS2 stale feed row")]
            check(len(stale) == 2 and {round(r["t"], 1) for r in stale} == {2.8, 7.5}, f"both re-reads are listed as stale: {[(round(r['t'], 1), r['reason'][:70]) for r in stale]}")
            check(not any(k["t"] < 10.0 for k in b["kills"]), "no kill is left in the first 10 s: nothing can open a take of this clip")
            # control: without the early (unshaped) tracks the 2.8 s row comes back -> the new rule is the cause
            sc2 = copy.deepcopy(sc)
            sc2["tracks"] = [t for t in sc2["tracks"] if t["id"] not in (1, 3)]
            b2 = M.border_analysis(sc2, cfg, [])
            check(2.8 in [round(k["t"], 1) for k in b2["kills"]], "control: without the early tracks of the row the 2.8 s kill is accepted (the stale match across positions is what rejects it)")
            # shift guard: the same victim read AFTER the row's life (> first + 10 s) is a new kill
            sc3 = copy.deepcopy(sc)
            for t in sc3["tracks"]:
                if t["id"] == 6:
                    t["first"] += int(4 * 30)
                    t["last"] += int(4 * 30)
            sc3["frames"] = int(sc3["frames"]) + 200
            b3 = M.border_analysis(sc3, cfg, [])
            check(any(abs(k["t"] - 11.47) < 0.1 for k in b3["kills"]), "the same name read 11 s into the clip (after the row's 10 s life) is a real new kill")
            # a different victim at a shifted position is untouched
            sc4 = copy.deepcopy(sc)
            for t in sc4["tracks"]:
                if t["id"] == 4:
                    for v in t["votes"]:
                        for bx in v["boxes"]:
                            if "convuls" in bx[4].lower() or "cowul" in bx[4].lower():
                                bx[4] = "Pingvinatorx"
            b4 = M.border_analysis(sc4, cfg, [])
            check(any(abs(k["t"] - 2.8) < 0.1 for k in b4["kills"]), "a different victim name at the shifted position is kept as a kill")


PARTS["1"] = part_bug_a


# ------------------------------------------------------------------------------------------------ 2) BUG B
def part_bug_b(tmp):
    with section("2) BUG B: the 4th kill of the 4k (13.18.16 + 13.18.26) is dated 7.3 s, its row first appears at ~5.7 s"):
        with PB.data_copy(M) as dst:
            cfg = M.load_config()
            B = load_base(BASE_REF, dst, tmp)
            rec, recb = rec_of(M, CLIP_B2), rec_of(B, CLIP_B2)
            check(rec is not None and recb is not None, "clip 2 is in the library")
            if rec is None:
                return
            det = M.Detector("cs2")
            # frames: the row (its right half cut at 7.63 s) is absent at 5.0 ... 5.5 s and on screen in every frame from 5.75 s to 8.0 s
            ts = [5.0, 5.25, 5.5] + [5.75 + 0.25 * i for i in range(10)]
            pres = row_presence(rec, 7.63, (300, 75, 520, 106), ts)
            check(all(p[1] < 0.7 for p in pres if p[0] <= 5.5), f"frames 5.0 / 5.25 / 5.5 s: the row is not on screen ({[round(p[1], 2) for p in pres if p[0] <= 5.5]})")
            check(all(p[1] >= 0.8 for p in pres if 5.75 <= p[0] <= 8.0), f"frames 5.75 ... 8.0 s: the row is on screen in every frame ({[round(p[1], 2) for p in pres if p[0] >= 5.75]})")
            sc = M.border_load(rec, det)
            tr = next(t for t in sc["tracks"] if t["id"] == 3)
            check(abs(tr["first"] / 30.0 - 7.33) < 0.05 and tr["hits"] <= 6, f"the tracker caught the row only at {tr['first'] / 30.0:.2f} s ({tr['hits']} frames): the first CLEAN read, not the first appearance")
            # old vs new analysis (the full pipeline: border list + dating)
            def kill_t(mod, r):
                e = mod.load_kills_cache().get(mod.kills_key(r, "cs2", mod.Detector("cs2")))
                a, lg = quiet(mod.analyse_clip_entry, r, e, mod.load_config(), "cs2")
                return [round(k["t"], 2) for k in a["kills"]], lg
            kb, _ = kill_t(B, recb)
            kn, lg = kill_t(M, rec)
            check(len(kb) == 1 and abs(kb[0] - 7.33) < 0.05, f"V7.7.5: the kill of clip 2 is at {kb} (7.33 s)")
            check(len(kn) == 1 and 5.5 < kn[0] <= 5.9, f"V7.7.6: the kill is at {kn} s = the first frame the row is in its slot")
            M.CS2_DATING_MEMO.clear()
            _dating = M.DATA / "cs2_dating_v7.json"
            if _dating.exists():
                _dating.unlink()
            M._DATING_LOGGED.clear()
            lg2 = kill_t(M, rec)[1]
            logs = [l for l in lg2 if "late read corrected" in l or "moved earlier" in l]
            check(any("late read corrected: 7.3 s -> 5." in l for l in logs), f"the log says it: {[l for l in logs if 'late' in l][:1]}")
            # the stitched 4k: kill 4 on the stitched timeline = seam offset + the new time
            seam = 15.33
            check(abs((seam + kn[0]) - 21.0) < 0.5, f"stitched: kill 4 at {seam + kn[0]:.1f} s (was {seam + kb[0]:.1f} s)")
            # clip 1: its three kills do not move
            r1, r1b = rec_of(M, CLIP_B1), rec_of(B, CLIP_B1)
            k1n, _ = kill_t(M, r1)
            k1b, _ = kill_t(B, r1b)
            check(len(k1n) == len(k1b) and all(abs(a - b) <= 0.5 for a, b in zip(k1n, k1b)), f"clip 1: the other kills stay put (V7.7.5 {k1b}, V7.7.6 {k1n})")


PARTS["2"] = part_bug_b


# ------------------------------------------------------------------------------------------------ 3) gunshot check + plan-time assertion
def part_checks(tmp):
    with section("3) second stale check (no shot before the row + victim of an early row) and the plan-time 'a kill row appears inside the take' assertion"):
        with PB.data_copy(M):
            keep_on = M.gun_onsets
            try:
                M.gun_onsets = lambda rec, cache=None, cfg=None: [[2.0, 5.0], [9.7, 5.0]]
                keep_key = M._onset_key
                M._onset_key = lambda r, c=None: "v776test"
                rec = {"path": "x.mp4", "game": "cs2", "audio": True, "a_stream": 0}
                mk = lambda t, vic, **kw: dict({"t": t, "victim": vic, "ks": 0.9, "hits": 10, "name_read": True, "border": True, "needs_shot": False}, **kw)
                it = {"rec": rec, "kills": [mk(5.0, "convulsive god", early_vic=True, seen_first=0.5),      # no shot within 1 s before, early victim -> stale
                                            mk(10.0, "convulsive god", early_vic=True, seen_first=0.5),     # a shot at 9.7 s -> kept
                                            mk(6.0, "Pingvin")],                                            # no shot, not an early victim -> kept (audio is only a bonus)
                      "rej": [], "deaths": [], "revives": []}
                keep_fn = M.cs2_no_gunshots
                M.cs2_no_gunshots = lambda r, o: False
                M.ONSET_CACHE_BACKUP = None
                M.verified_kills([it], M.load_config())
                M.cs2_no_gunshots = keep_fn
            finally:
                M.gun_onsets = keep_on
                M._onset_key = keep_key
            ts = sorted(round(k["t"], 1) for k in it["kills"])
            check(ts == [6.0, 10.0], f"the no-shot early-victim kill at 5.0 s is rejected, the one with a shot (10.0) and the unrelated one (6.0) stay: {ts}")
            check(any(r["reason"].startswith("CS2 stale feed row: no gunshot heard") for r in it["rej"]), "... and it is listed as a stale feed row")
        take = {"segs": [[4.0, 9.0, 1.0, 150]], "kills": [5.0], "victims": ["x"], "n": 1, "seen_lead": [4.5]}
        msgs = M.kill_window_audit(take)
        check(any("no kill row appears inside the take" in m_ for m_ in msgs), f"plan-time: a row already on screen 4.5 s before the kill, take starts at 4.0 s -> flagged: {msgs[:1]}")
        take2 = dict(take, seen_lead=[0.3])
        check(not any("no kill row appears" in m_ for m_ in M.kill_window_audit(take2)), "a row that appears inside the take (lead 0.3 s) is fine")
        take3 = {"segs": [[4.0, 9.0, 1.0, 150]], "kills": [5.0], "victims": ["x"], "n": 1}
        check(M.kill_window_audit(take3) == M.kill_window_audit(dict(take3, seen_lead=[0.0])), "takes without the field (Valorant, old events) are audited exactly as before")


PARTS["3"] = part_checks


# ------------------------------------------------------------------------------------------------ 4) corpus
def corpus(mod):
    cfg = mod.load_config()
    det = mod.Detector("cs2")
    kc = mod.load_kills_cache()
    res = {}
    keep = (mod.out, mod.LOGONLY)
    lines = []
    mod.out = mod.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        recs = [r for r in mod.scan_clips(cfg) if r.get("game") == "cs2" and not r.get("error")]
        from concurrent.futures import ThreadPoolExecutor

        def one(r):
            e = kc.get(mod.kills_key(r, "cs2", det))
            if not e or e.get("error"):
                return None
            try:
                a = mod.analyse_clip_entry(r, e, cfg, "cs2")
            except Exception:
                return None
            return {"kills": [(round(k["t"], 3), k.get("victim")) for k in a["kills"]], "rej": [x["reason"] for x in a["rej"]]}
        with ThreadPoolExecutor(4) as ex:
            for r, o in zip(recs, ex.map(one, recs)):
                if o is not None:
                    res[Path(r["path"]).name] = o
    finally:
        mod.out, mod.LOGONLY = keep
    return res, lines


def part_corpus(tmp):
    with section("4) all cached CS2 clips: kill times vs V7.7.5 (moved > 0.5 s, the 10 biggest), kill counts, merged duplicates"):
        with PB.data_copy(M) as dst:
            B = load_base(BASE_REF, dst, tmp)
            old, _ = corpus(B)
            new, _ = corpus(M)
            moved, lost, gained, dupe_old, dupe_new = [], [], [], 0, 0
            for name in sorted(set(old) & set(new)):
                ko, kn = old[name]["kills"], new[name]["kills"]
                dupe_old += sum(1 for r in old[name]["rej"] if "duplicate" in r.lower() or "same victim" in r.lower())
                dupe_new += sum(1 for r in new[name]["rej"] if "duplicate" in r.lower() or "same victim" in r.lower())
                if len(ko) != len(kn):
                    (lost if len(kn) < len(ko) else gained).append((name, len(ko), len(kn), [r for r in new[name]["rej"] if r.startswith("CS2 stale")][:2]))
                    continue
                for (a, va), (b, vb) in zip(ko, kn):
                    if abs(a - b) > 0.5:
                        moved.append((round(b - a, 2), name, a, b, va))
            nk = sum(len(v["kills"]) for v in old.values())
            print(f"   {len(old)} CS2 clips, {nk} kills in V7.7.5; kill times moved by more than 0.5 s: {len(moved)}; clips with a changed kill COUNT: {len(lost)} fewer / {len(gained)} more")
            for d, name, a, b, v in sorted(moved, key=lambda x: -abs(x[0]))[:10]:
                print(f"     {d:+.2f} s  {a:.2f} -> {b:.2f}  {name}  [{v}]")
            for name, a, b, why in lost + gained:
                print(f"     count {a} -> {b}  {name}  {why}")
            print(f"   merged / same-victim duplicate rejections: V7.7.5 {dupe_old}, V7.7.6 {dupe_new}")
            check(all(d < 0 for d, *_ in moved), "every moved kill moved EARLIER (to the first appearance of its row), none later")
            check(not gained, f"no clip gained a kill ({len(gained)})")
            check(all(w for _, _, _, w in lost), f"every clip that lost a kill lost it to a stale-row rejection ({len(lost)} clips)")
            check(dupe_new <= dupe_old + 2, "the duplicate-merge counts do not change unexpectedly")
            Path(os.environ.get("V776_CORPUS_OUT", str(tmp / "corpus776.json"))).write_text(
                json.dumps({"moved": moved, "lost": lost, "clips": len(old), "kills": nk}, ensure_ascii=False, default=str), encoding="utf-8")


PARTS["4"] = part_corpus


# ------------------------------------------------------------------------------------------------ g) guards
def part_guards(tmp):
    import test_v73 as T73
    import test_v761 as T761
    with section(f"g) guards vs {BASE_REF} (defaults): Valorant identical, same-seed CS2 plans identical except the clips named"):
        with PB.data_copy(M) as dst:
            B = load_base(BASE_REF, dst, tmp)
            cfg_ = M.load_config()
            cfg_["lower_music_clips"] = False
            M.save_json(M.CONFIG_PATH, cfg_)
            for game in ("valorant", "cs2"):
                files = T73.make_files(tmp / f"g50_{game}", 50, "VALORANT" if game == "valorant" else "Replay")
                rnd = random.Random(7 if game == "valorant" else 8)
                kills = []
                for _ in files:
                    n = rnd.choice([1, 1, 2, 2, 3, 3, 4, 5])
                    t, ks = rnd.uniform(3.0, 5.0), []
                    for _k in range(n):
                        ks.append(round(t, 2))
                        t += rnd.uniform(0.7, 2.6)
                    kills.append(ks)
                its_m, its_b = T73.build_pool(M, game, files, kills, seed=21), T73.build_pool(B, game, files, kills, seed=21)
                ev_m, _ = T73.events_of(M, game, its_m)
                ev_b, _ = T73.events_of(B, game, its_b)
                check(len(ev_m) > 40 and T73.ev_view(ev_m) == T73.ev_view(ev_b), f"{game}: {len(ev_m)} events of the 50 generated clips identical to {BASE_REF}")
                for bpm, drop_s, seed in ((128.0, 64.0, 5), (150.0, 40.0, 12)):
                    an_m, an_b = T73.song_map(M, bpm, 300.0, drop_s), T73.song_map(B, bpm, 300.0, drop_s)
                    p_new = T73.plan_of(M, game, ev_m, an_m, seed)
                    p_b = T73.plan_of(B, game, ev_b, an_b, seed)
                    check(T761.kill_set(p_new) == T761.kill_set(p_b) and [t["segs"] for t in p_new["takes"]] == [t["segs"] for t in p_b["takes"]] and p_new.get("drop_sync") == p_b.get("drop_sync"),
                          f"{game} bpm {bpm:.0f}: kills, cut lists, drops identical to {BASE_REF}")
                    check([{k: v for k, v in t.items() if k != "trans"} for t in p_new["takes"]] == [{k: v for k, v in t.items() if k != "trans"} for t in p_b["takes"]],
                          f"{game} bpm {bpm:.0f}: every take identical")
                    check(not M.verify_cutlist(p_new), f"{game} bpm {bpm:.0f}: cut list valid")
            sets = PB.take_sets(M)
            song = next(x["path"] for x in M.song_pool(M.load_config())[0] if "Silicon XX" in str(x["path"]))
            M.HEADLINE_RULES_V73 = True
            for tag in ("val7", "cs2trio", "cs2singles"):
                game, paths = sets[tag]
                plan_n, l_n = PB.run_plan(M, game, paths, song, "v2")
                plan_b, _lb = PB.run_plan(B, game, paths, song, "v2")
                strip = lambda p: [{k: v for k, v in t.items() if k not in ("trans",)} for t in p["takes"]]
                same = strip(plan_n) == strip(plan_b) and plan_n.get("drop_sync") == plan_b.get("drop_sync") and plan_n["song"] == plan_b["song"]
                if game == "valorant":
                    check(same, f"{tag}: {len(plan_n['takes'])} takes, cut lists, drops, song identical to {BASE_REF}")
                else:
                    diff = sorted({Path(a["path"]).name for a, b in zip(strip(plan_n), strip(plan_b)) if a != b} | ({"(take count differs)"} if len(plan_n["takes"]) != len(plan_b["takes"]) else set()))
                    print(f"   {tag}: {len(plan_n['takes'])} takes (V7.7.5: {len(plan_b['takes'])}); clips whose take differs from {BASE_REF}: {diff or 'none'}")
                    check(True, f"{tag}: same-seed plan compared; changed clips listed above")
                    check(not [m for m in M.verify_cutlist(plan_n)], f"{tag}: cut list valid")
                if tag == "val7":
                    check(not M.verify_cutlist(plan_n), f"{tag}: cut list valid")
                    led = next(l for l in l_n if l.startswith("kill ledger:"))
                    check(len(plan_n["takes"]) == 4 and "11 placed" in led and "3 merged" in led and "0 lost" in led, f"7 real Valorant clips: 4 events; '{led[:100]}'")


PARTS["g"] = part_guards


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t776_"))
    only = set(filter(None, os.environ.get("V776_PARTS", "").split(",")))
    for key in ("0", "1", "2", "3", "4", "g"):
        if (not only or key in only) and key in PARTS:
            PARTS[key](tmp)
    after = snapshot(REAL_DATA)
    if before == after:
        check(True, f"real montage_data byte-identical after the tests ({len(before)} files)")
    else:
        names_ = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        print("   NOTE (nothing was touched by the tests, the Montager app writes there): real montage_data differs in " + ", ".join(names_[:12]))
    print(f"total test time {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}): " + "; ".join(FAILS))
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
