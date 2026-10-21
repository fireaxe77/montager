"""V8.8 tests (fast; no montage render, no OCR).
  0) title-bar version V8.8; V8.8 on top of V8.7 in both changelogs
  1) audio track: a real multi-track file with sound only on track 2 (Settings 1 / 2 / auto all use track 2, the gunshot analysis reads it, a track without gunshots
     falls back to the one with them); a file whose only track is digital silence stays silent; Valorant keeps the V8.7 pick
  2) full-song mode: dead silence at the start / end of the song is cut (CS2 / R6S), Valorant unchanged
  3) clip quality: 60 fps / 1080p / full frame first, a weighting (a poor-quality 4k still beats a clean 2k); Manual Auto order weighted for CS2 / R6S only
  4) sky: wilder and locked to the beat for CS2 / R6S (black hits on the beats, colour flips), more skies, drops first, every drop covered; Valorant identical
  5) song-end fill: longer run-ins after the drop, never with a gunshot / death / stitched clip, the later takes move by whole beats, the headline never moves
  6) R6S skull kills of the montage S_R6S_V8.6.2_2026-10-17_3 (saved scan data): both rejected as utility; a stale scan is re-matched against the current icons
  7) companions: a copied / touched file is matched by the time in its name, a created time only when it agrees with the modified or the name time
  8) CS2 deagle 3k (Replay 2026-06-25 01-27-36, old row sidecar): all 3 kills; real data (MONTAGER_DATA = the real folder): the 3k and the 4k clip CS2 2026-10-17 02-48-50
python tests\\test_v88.py   (parts: V88_PARTS=0,1,2,3,4,5,6,7,8)"""
import copy
import json
import os
import random
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_src = (HERE / "test_v842.py").read_text(encoding="utf-8")
_ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
exec(compile(_src[:_src.index("def part0")], str(HERE / "test_v842.py"), "exec"), _ns)
T = types.SimpleNamespace(**_ns)
M = T.M
ROOT = T.ROOT
check, mk = T.check, T.mk
DATA88 = HERE / "data_v88"
PARTS = [x for x in os.environ.get("V88_PARTS", "0,1,2,3,4,5,6,7,8").split(",") if x]
import numpy as np                                                                            # noqa: E402


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.8", M.APP_VERSION == "V8.8")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.8 above V8.7", cl[0].startswith("## V8.8") and cl[1].startswith("## V8.7"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.8 above V8.7", sm[0].startswith("## V8.8") and sm[1].startswith("## V8.7"), str(sm[:2]))
    seg = body[body.index("## V8.8"):body.index("## V8.7")].lower()
    check("simple entry is plain", not any(w in seg for w in ("test", "known issue", "on hold", "def ", "xfx", "ffmpeg", "sidecar", "cache", "()")))


def _ffmpeg_clip(path, tracks):
    """A 6 s clip with one audio stream per entry: 'silent' = digital silence, 'shots' = gunshot-like bursts, 'tone' = a steady tone."""
    src = {"silent": "anullsrc=r=48000:cl=stereo:d=6", "tone": "sine=frequency=300:sample_rate=48000:duration=6",
           "shots": "anoisesrc=d=6:c=white:r=48000:a=0.5,volume='if(lt(mod(t,0.8),0.06),1,0)':eval=frame"}
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=30:d=6"]
    for t in tracks:
        cmd += ["-f", "lavfi", "-i", src[t]]
    cmd += ["-map", "0:v"] + sum((["-map", f"{i + 1}:a"] for i in range(len(tracks))), []) + ["-c:v", "mpeg4", "-c:a", "aac", "-shortest", str(path)]
    subprocess.run(cmd, capture_output=True, timeout=120)
    return path.exists()


def part1():
    print("1) audio track")
    tmp = Path(tempfile.mkdtemp(prefix="v88a_"))
    old = M.use_data_dir(tmp / "data")
    M._CS2_STREAM.clear()
    try:
        clip = tmp / "track2_only.mkv"
        if not _ffmpeg_clip(clip, ["silent", "shots", "silent"]):
            check("multi-track test clip built", False)
            return
        rec = dict(M.probe_video(str(clip)), path=str(clip), game="cs2")
        for setting in ("auto", "1", "2", "3"):
            au = M.clip_audio(rec, setting)
            check(f"setting {setting}: track 2 is used (the only one with sound): {au.get('note')}", au["stream"] == 1 and au.get("lufs") is not None)
        for g, setting in (("cs2", "2"), ("cs2", "1"), ("r6s", "auto"), ("valorant", "2")):
            M._CS2_STREAM.clear()
            cfg = dict(M.DEFAULT_CONFIG, game_audio_track={**M.DEFAULT_CONFIG["game_audio_track"], g: setting})
            r_ = dict(rec, game=g)
            check(f"{g}, Settings track {setting}: gunshot analysis / shot timing / render read track 2", M._cs2_stream(r_, cfg) == 1 and M._shot_stream(r_, cfg) == 1
                  and M.resolve_clip_audio(r_, cfg, g, {})["stream"] == 1)
            ons = M.gun_onsets(r_, {}, cfg)
            check(f"{g}: gunshots heard on track 2 ({len(ons or [])})", bool(ons) and len(ons) >= 4)
        M._CS2_STREAM.clear()
        check("CS2 without a config: the Settings pick, never a blind track 1", M._shot_stream(dict(rec, game="cs2"), None) == 1)
        sil = tmp / "silent_only.mkv"
        _ffmpeg_clip(sil, ["silent"])
        rs = dict(M.probe_video(str(sil)), path=str(sil), game="cs2")
        au = M.clip_audio(rs, "2")
        check(f"one digitally silent track stays silent: {au.get('note')}", au["stream"] == 0 and au.get("lufs") is None and M.audio_unusable(rs, au) is not None)
        two = tmp / "tone_and_shots.mkv"
        _ffmpeg_clip(two, ["tone", "shots"])
        rt = dict(M.probe_video(str(two)), path=str(two), game="cs2")
        M.clip_audio(rt, "auto")
        key = M.file_key(str(two)) + "|t2"
        lc = M.load_json(M.LOUD_CACHE, {})
        lc[key] = {"lufs": lc[key]["lufs"], "ons": [0, 9]}
        M.save_json(M.LOUD_CACHE, lc)
        M._CS2_STREAM.clear()
        cfg1 = dict(M.DEFAULT_CONFIG, game_audio_track={**M.DEFAULT_CONFIG["game_audio_track"], "cs2": "1"})
        check("Settings track 1 has sound but no gunshot, track 2 has them: the gunshot analysis reads track 2, the mix keeps track 1",
              M._shot_stream(rt, cfg1) == 1 and M._cs2_stream(rt, cfg1) == 0)
        M._CS2_STREAM.clear()
        check("Valorant: the V8.7 pick (no gunshot fallback)", M._shot_stream(dict(rt, game="valorant"), dict(cfg1, game_audio_track={"valorant": "1"})) == 0)
    finally:
        M.restore_data_dir(old)
        M._CS2_STREAM.clear()


def _an_dead(lead_s=4.0, tail_s=5.0):
    a = copy.deepcopy(T.an())
    dur = float(a["dur"])
    w = list(a["wave"])
    n = len(w)
    for i in range(n):
        t = (i + 0.5) * dur / n
        if t < lead_s or t > dur - tail_s:
            w[i] = 0.0
        else:
            w[i] = max(w[i], 0.05)
    a["wave"] = w
    return a


def part2():
    print("2) full-song mode: dead silence cut")
    a = _an_dead()
    t0, t1 = M.song_live_range(a)
    check(f"live range found: {t0:.2f} - {t1:.2f} of {a['dur']:.1f} s", 3.8 <= t0 <= 4.2 and a["dur"] - 5.2 <= t1 <= a["dur"] - 4.8)
    check("a song without dead edges keeps its whole length", M.song_live_range(dict(a, wave=[0.3] * 2000)) == (0.0, float(a["dur"])))
    evs = M.fake_events()
    bt = np.array(a["beats"], float)
    for g in ("cs2", "r6s", "valorant"):
        M.FULL_CTX.update(on=True, game=g)
        try:
            fit = M.optimal_fit(copy.deepcopy(evs) * 3, a, "hype")
        finally:
            M.FULL_CTX.update(on=False)
            M.FULL_CTX.pop("live", None)
        s_t, e_t = float(bt[fit["start_beat"]]), float(bt[fit["end_beat"]])
        if g == "valorant":
            ref_fit = None
            M.FULL_CTX.update(on=True, game="valorant")
            try:
                ref_fit = M.optimal_fit(copy.deepcopy(evs) * 3, T.an(), "hype")
            finally:
                M.FULL_CTX.update(on=False)
            check("Valorant: section as before (the envelope is not used)", (fit["start_beat"], fit["end_beat"]) == (ref_fit["start_beat"], ref_fit["end_beat"]))
        else:
            check(f"{g}: the section starts after the dead start and ends before the dead end ({s_t:.2f} - {e_t:.2f})", s_t >= t0 - 0.05 and e_t <= t1)


def part3():
    print("3) clip quality")
    q = lambda **kw: M.clip_quality(dict({"w": 1920, "h": 1080, "fps": 60.0, "bars": False}, **kw), {"bar": {"rect": [0, 0, 1280, 960]}})
    full, f30, p360, box, f50 = q(), q(fps=30.0), q(w=640, h=360), q(bars=True, fps=50.0), q(fps=50.0)
    check(f"1080p60 full frame = 1.0, 50 fps {f50}, 30 fps {f30}, 360p {p360}, small box {box}", full == 1.0 and 0.8 < f50 < 0.9 and f30 < 0.5 and p360 < 0.35 and box < 0.6)
    s = M.quality_score
    check("unchanged at full quality", s(42.0, 1.0) == 42.0)
    check("a 4k on a 30 fps / 360p clip still beats a clean 2k", s(80.0, q(fps=30.0, w=640, h=360)) > s(50.0, 1.0))
    check("a clean 2k beats a 2k on a 30 fps clip; a clean 3k beats a boxed 3k", s(42.0, 1.0) > s(42.0, f30) and s(60.0, 1.0) > s(60.0, box))
    check("an ace on the worst clip still beats a clean 3k", s(100.0, 0.05) > s(62.0, 1.0))
    an_ = T.an()
    cands = [{"path": f"/c/{i}.mp4", "used": "", "ks": [1.0], "q": (1.0 if i % 2 else 0.3)} for i in range(400)]
    pv = M.auto_fill_pick(copy.deepcopy(cands), an_, "hype", random.Random(5), game="valorant")[0]
    pv0 = M.auto_fill_pick(copy.deepcopy(cands), an_, "hype", random.Random(5))[0]
    pc = M.auto_fill_pick(copy.deepcopy(cands), an_, "hype", random.Random(5), game="cs2")[0]
    hi = lambda ps: sum(1 for p in ps if int(Path(p).stem) % 2) / max(1, len(ps))
    check(f"Manual Auto: Valorant order as before, CS2 picks mostly the good clips ({hi(pc) * 100:.0f}% vs {hi(pv) * 100:.0f}%)", pv == pv0 and hi(pc) > hi(pv) + 0.15)


def part4():
    print("4) sky")
    for g in (None, "valorant"):
        check(f"game {g}: the V8.7 parameters", M.sky_anim_params(0.4, 100, "chill", False, game=g) == M.sky_anim_params(0.4, 100, "chill", False))
    calm_v = M.sky_anim_params(0.3, 95, "chill", False)
    calm_c = M.sky_anim_params(0.3, 95, "chill", False, game="cs2")
    check(f"CS2: a chill song's sky is still wild (hard {calm_c['hard']} vs {calm_v['hard']}), beat-locked", calm_c["hard"] >= M.SKY_HARD_FLOOR_88 and calm_c.get("sync")
          and calm_c["bd"] >= 0.7 and calm_c["jump"] >= 0.55)
    bpm = 128.0
    per = 60.0 / bpm
    x = {"seed": 3, "beats": [(round(0.2 + i * per, 4), 1.0 if i % 4 == 0 else 0.45) for i in range(8)]}
    nf = int(round((0.2 + 8 * per) * M.OUT_FPS))
    f0 = int(round(0.1 * M.OUT_FPS))
    sch = M.sky_anim_schedule(M.sky_anim_params(0.8, bpm, "hype", True, game="cs2"), x, f0, nf)
    hits = [int(round(b * M.OUT_FPS)) for b, _ in x["beats"]]
    check("a black hit on every beat", all(sch["black"][f] >= 0.3 for f in hits))
    check("deeper on the downbeats", all(sch["black"][hits[i]] > sch["black"][hits[i + 1]] for i in (0, 4)))
    check("colour flips on every other beat", all(sch["jump"][hits[i] + 3] > 0.3 for i in (1, 3, 5)) and sch["jump"][hits[2] + 3] < 0.05)
    check("nothing before the kill frame", float(sch["black"][:f0].max()) == 0.0 and float(sch["jump"][:f0].max()) == 0.0)
    check("more skies for CS2 / R6S (150 s: 10 vs 5), closer spacing", M.sky_max_for(150, "cs2") == 10 and M.sky_max_for(150) == 5 and M.sky_max_for(150, "valorant") == 5
          and M.sky_spacing_for("r6s") < M.sky_spacing_for("valorant"))
    p, _ = mk(M, "cs2", "aggressive", 3, eff={"cs2": "extra", "valorant": "extra", "r6s": "extra"})
    sky = [x_ for t in p["takes"] for x_ in t.get("xfx", []) if x_["k"] == "sky"]
    roles = {p["takes"][ti].get("role") for ti, t in enumerate(p["takes"]) for x_ in t.get("xfx", []) if x_["k"] == "sky"}
    check(f"CS2: sky candidates on the drops ({len(sky)} candidates, roles {sorted(roles)})", bool(sky) and ("drop" in roles or "headline" in roles))
    pv, _ = mk(M, "valorant", "aggressive", 3, eff={"cs2": "extra", "valorant": "extra", "r6s": "extra"})
    check("Valorant: no drop index on sky candidates (V8.7 order)", all(x_.get("drop_i") is None for t in pv["takes"] for x_ in t.get("xfx", []) if x_["k"] == "sky"))
    plan = {"drops_out": [20.0, 60.0], "xfx_sky_max": 2, "xfx_sky_space": 6.0, "game": "cs2", "takes": []}
    xs = [{"k": "sky", "p": 0.1, "gp": 22.0, "prio": 6, "sc": 2.0, "drop_i": 0}, {"k": "sky", "p": 0.1, "gp": 30.0, "prio": 6, "sc": 1.9, "drop_i": 0},
          {"k": "sky", "p": 0.1, "gp": 62.0, "prio": 5, "sc": 1.0, "drop_i": 1}]
    check("drop index of a moment", M._drop_index(plan, 25.0) == 0 and M._drop_index(plan, 61.0) == 1 and M._drop_index(plan, 10.0) is None)
    kept = []
    keep_g, keep_e, keep_m = M.sky_grab_frames, M.sky_eyedrop, M.sky_take_mask
    M.sky_grab_frames = lambda *a, **k: [np.zeros((4, 4, 3), np.uint8)]
    M.sky_eyedrop = lambda img: (None, {"ok": True, "cov": 0.2, "sky_rgb": 0x3060C0, "scene_hue": None})
    M.sky_take_mask = lambda t, x, zone, mp, ramp=False: (kept.append(x["gp"]), {"bad": 0, "window": 10, "cov": 0.2, "frames": 10, "held": 0, "horizon": 0.4})[1]
    try:
        for i, x_ in enumerate(xs):
            plan["takes"].append({"path": "a", "srcs": [{"path": "a", "shift": 0.0, "rect": [0, 0, 4, 4], "wh": [4, 4]}], "segs": [[0.0, 1.0, 1.0, 60]], "kills": [0.1],
                                  "out_start": x_["gp"] - 0.1, "dur": 1.0, "nf": 60, "xfx": [dict(x_)]})
        plan["song"] = {"path": "", "title": "t", "start_t": 0.0}
        M.xfx_probe_sky(plan, Path(tempfile.mkdtemp(prefix="v88s_")))
    finally:
        M.sky_grab_frames, M.sky_eyedrop, M.sky_take_mask = keep_g, keep_e, keep_m
    check(f"each drop gets a sky before a second one on the same drop ({sorted(kept)})", sorted(kept) == [22.0, 62.0])


def _stub_geom(ev, U, c, kb, end, ramp, slow, ending=False, ext=True, anchor="first", tailmode="plain"):
    lead = float(U[kb] - U[c])
    if lead < 0.3 or lead > ev["pre"] + 1e-6:
        return None
    if ending:
        return {"ev": ev, "c": c, "kb": kb, "end": None, "lead_t": lead, "ramp": 1.0, "slow": True, "ending": True, "dur": lead + 2.0}
    if end is None or end <= kb:
        return None
    return {"ev": ev, "c": c, "kb": kb, "end": end, "lead_t": lead, "ramp": 1.0, "slow": slow, "ending": False, "dur": float(U[end] - U[c])}


def part5():
    print("5) song-end fill")
    U = np.arange(0, 200) * 0.25
    mkev = lambda n, sc, pre, path, stitched=False: {"path": path, "rec": {"path": path, "audio": True, "game": "cs2"}, "times": [pre], "score": sc, "pre": pre, "n": 1,
                                                   "parts": [{}, {}] if stitched else [{}], "stitched": stitched}
    e_head, e_quiet, e_shot, e_late, e_end = mkev(1, 80, 3.0, "head"), mkev(1, 10, 4.0, "quiet"), mkev(1, 12, 4.0, "shot"), mkev(1, 30, 4.0, "late"), mkev(1, 40, 3.0, "end")
    takes = [_stub_geom(e_head, U, 0, 6, 10, 1.0, False), _stub_geom(e_quiet, U, 10, 14, 18, 1.0, False), _stub_geom(e_shot, U, 18, 22, 26, 1.0, False),
             _stub_geom(e_late, U, 26, 30, 34, 1.0, False), dict(_stub_geom(e_end, U, 34, 38, None, 1.0, True, ending=True), fade_end=46)]
    head = takes[0]
    ons = {"quiet": [[3.95, 5.0]], "shot": [[2.5, 5.0]], "late": [[3.95, 4.0]]}
    keep_g, keep_o = M.geom, M.gun_onsets
    M.geom = _stub_geom
    M.gun_onsets = lambda rec, cache=None, cfg=None: ons.get(rec["path"], [])
    notes = []
    try:
        out_ = M.fill_lead_ins(takes, head, U, 2.0, {}, notes, lambda e: e["path"], 999.0)
    finally:
        M.geom, M.gun_onsets = keep_g, keep_o
    k = {t["ev"]["path"]: t for t in out_}
    check("the headline never moves", k["head"] is takes[0])
    check("the calmest clean take got ~1 s more run-in (4 ticks = 1.0 s)", k["quiet"]["kb"] == takes[1]["kb"] + 4 and k["quiet"]["c"] == takes[1]["c"])
    check("a gunshot in the added run-in: not extended (only moved)", k["shot"]["kb"] - k["shot"]["c"] == takes[2]["kb"] - takes[2]["c"])
    check("every later take moved by whole beats, the ending's fade too", k["late"]["c"] == takes[3]["c"] + (k["late"]["c"] - takes[3]["c"]) and (k["late"]["c"] - takes[3]["c"]) % 2 == 0
          and k["end"]["fade_end"] - 46 == k["end"]["c"] - takes[4]["c"])
    check(f"logged: {notes[-1][:90] if notes else ''}", bool(notes) and "song filled to the end" in notes[-1])
    ok1, w1 = M.leadin_safe(mkev(1, 1, 4.0, "x", stitched=True), 1.0, 2.0, {})
    ok2, w2 = M.leadin_safe(dict(mkev(1, 1, 4.0, "x"), rec={"path": "x", "audio": False}), 1.0, 2.0, {})
    M.gun_onsets = lambda rec, cache=None, cfg=None: [[9.0, 5.0]]
    try:
        ok3, _ = M.leadin_safe(dict(mkev(1, 1, 4.0, "x"), deaths=[1.5]), 1.0, 2.0, {})
        ok4, _ = M.leadin_safe(mkev(1, 1, 4.0, "y"), 1.0, 2.0, {})
    finally:
        M.gun_onsets = keep_o
    check(f"no extra footage from stitched clips ({w1}), clips without sound ({w2}) or with my death in it; clean footage is fine", not ok1 and not ok2 and not ok3 and ok4)
    check("no fill when the montage is far short (missing clips, not run-ins) or too little short",
          M.fill_lead_ins(takes, head, U, 40.0, {}, [], lambda e: e["path"], 999.0) is takes and M.fill_lead_ins(takes, head, U, 0.2, {}, [], lambda e: e["path"], 999.0) is takes)


def part6():
    print("6) R6S skull / utility kills")
    fx = json.loads((DATA88 / "r6s_skull_kills.json").read_text(encoding="utf-8"))
    cfg = dict(M.DEFAULT_CONFIG)
    for name, d in fx.items():
        ent = {"util": d["util"], "v_off": d["v_off"], "frames": d["frames"]}
        a0 = M._r6s_core(d["rows"], dict(ent, util=[]), cfg)
        a1 = M._r6s_core(d["rows"], ent, cfg)
        ur = [r for r in a1["rej"] if "utility" in r["reason"]]
        check(f"{name[-28:]}: kill rows {[k['t'] for k in a0['kills']]} without icons; with the saved icon hits: kills {[k['t'] for k in a1['kills']]}, utility {[r['t'] for r in ur]}",
              a0["kills"] and not a1["kills"] and len(ur) >= len(a0["kills"]))
    d = fx["Tom Clancy's Rainbow Six  Siege 2023.11.01 - 15.14.59.04.DVR.mp4"]
    r = min(d["rows"], key=lambda r: abs(r["first"] - 181))
    xk = max(b[1] for _f, l, _r in r["reads"] for b in l)
    xv = min(b[0] for _f, _l, rr in r["reads"] for b in rr)
    check(f"the case: killer text runs past the icon (killer right {xk} > victim left {xv}) and the skull still counts", xk > xv and M.r6s_row_util(r, d["util"]))
    tmp = Path(tempfile.mkdtemp(prefix="v88r_"))
    old = M.use_data_dir(tmp / "data")
    try:
        import cv2
        icd = M.r6s_util_icon_dir()
        icd.mkdir(parents=True, exist_ok=True)
        skull = np.zeros((28, 38), np.uint8)
        cv2.circle(skull, (19, 12), 9, 255, -1)
        cv2.rectangle(skull, (13, 18), (25, 26), 255, -1)
        cv2.circle(skull, (15, 11), 3, 0, -1)
        cv2.circle(skull, (23, 11), 3, 0, -1)
        cv2.imwrite(str(icd / "kill_skull.png"), skull)
        M._R6S_UTIL_CACHE.clear()
        rows = [{"first": 30, "last": 60, "hits": 30, "y": 100, "h": 20, "x": 300, "w": 200, "gunv": [0],
                 "reads": [[f, [[200, 280, "fireaxe0", 0.99]], [[340, 420, "enemyone", 0.99]]] for f in (35, 45, 55)]}]
        stale = {"util": [], "util_sig": "old", "v_off": 0.0, "frames": 75, "ocr": [], "rows": rows}

        def frames(path, rec, det, cfg, fps, use_hw=True):
            for f in range(75):
                fr = np.full((200, 640, 3), 40, np.uint8)
                if 30 <= f <= 60:
                    fr[86:114, 291:329] = cv2.cvtColor(skull, cv2.COLOR_GRAY2BGR)
                yield fr
        keep_fs, keep_an = M.frame_stream, M.r6s_analyse_entry
        M.frame_stream = frames
        M.r6s_analyse_entry = lambda e, c: M._r6s_core(e["rows"], e, c)
        try:
            e2 = M.r6s_util_refresh({"path": "x.mp4"}, stale, None, cfg)
            a2 = M._r6s_core(rows, e2, cfg)
        finally:
            M.frame_stream, M.r6s_analyse_entry = keep_fs, keep_an
        check(f"a scan made with an older icon set is re-matched (sig {e2.get('util_sig')}, {len(e2.get('util') or [])} hit(s)) and the kill becomes utility",
              e2.get("util_sig") == M.r6s_icons_sig(M.r6s_load_util_icons(log=False)) and not a2["kills"] and any("utility" in r_["reason"] for r_ in a2["rej"]))
        check("a scan with the current icon set is left alone", M.r6s_util_refresh({"path": "x.mp4"}, e2, None, cfg) is e2)
        gun = dict(stale, rows=[dict(rows[0], gunv=[1, 1, 1])])
        M.frame_stream = frames
        M.r6s_analyse_entry = lambda e, c: M._r6s_core(e["rows"], e, c)
        try:
            check("a kill row always read as a gun is not re-matched (keeps the first run short)", M.r6s_util_refresh({"path": "x.mp4"}, gun, None, cfg) is gun)
        finally:
            M.frame_stream, M.r6s_analyse_entry = keep_fs, keep_an
    finally:
        M.restore_data_dir(old)
        M._R6S_UTIL_CACHE.clear()


def part7():
    print("7) companions by name and date")
    tmp = Path(tempfile.mkdtemp(prefix="v88c_"))
    import datetime
    t_name = datetime.datetime(2026, 2, 3, 20, 10, 5).timestamp()
    a = tmp / "Counter-strike 2 2026.02.03 - 20.10.05.01.DVR.mp4"
    b = tmp / "Counter-strike 2 2026.02.03 - 20.10.25.02.DVR.mp4"
    for p_ in (a, b):
        p_.write_bytes(b"x")
    os.utime(a, (t_name + 3600, t_name + 3600))                  # a copied / touched file: modified an hour later
    os.utime(b, (t_name + 20 + 20, t_name + 20 + 20))              # saved normally (DVR name = start, modified = end)
    ab = M.clip_anchor_best(str(a), 20.0, "cs2")
    check(f"touched file: the name time is its clock ({ab.get('how', '')[:60]})", ab.get("clock") == "name" and abs(ab["start"] - t_name) < 1)
    check("Valorant keeps the modified time", M.clip_anchor_best(str(a), 20.0, "valorant")["end"] == M.clip_anchor(str(a), 20.0)["end"])
    bb = M.clip_anchor_best(str(b), 20.0, "cs2")
    check("a file whose modified time agrees keeps it", bb.get("clock") is None and abs(bb["end"] - (t_name + 40)) < 1)
    M.PAIR_CTX.game = "cs2"
    lk, why = M.save_time_link({"anc": ab, "kills": [{"t": 18.0, "victim": "x1"}]}, {"anc": bb, "kills": [{"t": 2.0, "victim": "y2"}]})
    check(f"the two clips link by their name times ({why or lk['match']})", lk is not None)
    ca, cb = M.clip_anchor_created(str(a), 20.0), M.clip_anchor_created(str(b), 20.0)
    check("created time: trusted only when it agrees with the modified or the name time (the copy's created time is now: refused)", ca is None or abs(ca["end"] - os.stat(a).st_mtime) <= 120 or abs(ca["end"] - (t_name + 20)) <= 60)
    far = {"start": 0.0, "end": 20.0}
    near_c = [{"start": 1000.0, "end": 1020.0, "dur": 20.0}, {"start": 1021.0, "end": 1041.0, "dur": 20.0}]
    lk2, _ = M.save_time_link({"anc": far, "anc_c": near_c[0], "kills": []}, {"anc": {"start": 500.0, "end": 520.0}, "anc_c": near_c[1], "kills": []})
    check("modified times far apart, created times next to each other: linked by the created times", lk2 is not None and "created" in lk2["match"])
    lk3, _ = M.save_time_link({"anc": far, "kills": []}, {"anc": {"start": 500.0, "end": 520.0}, "kills": []})
    check("without created times: not linked (as before)", lk3 is None)
    M.PAIR_CTX.game = None


def part8():
    print("8) CS2 deagle 3k")
    fx = json.loads((DATA88 / "cs2_deagle3k.json").read_text(encoding="utf-8"))
    cfg = dict(M.DEFAULT_CONFIG)
    a = {"kills": fx["name"]["kills"], "deaths": fx["name"]["deaths"]}
    for on in (False, True):
        M.CS2_LATE_ROW_ON[0] = on
        b = M.border_analysis(copy.deepcopy(fx["sidecar"]), cfg, a["deaths"])
        M.cs2_late_rows_retime(a, b, fx["clip"])
        b["kills"] = sorted(b["kills"] + M.cs2_name_kills_kept(a, b, fx["sidecar"], fx["clip"]), key=lambda k: k["t"])
        ts = [round(k["t"], 2) for k in b["kills"]]
        if not on:
            check(f"the V8.7 result on this sidecar loses kills: {ts}", len(ts) < 3 or abs(ts[0] - 10.1) > 0.4)
        else:
            check(f"V8.8: all three kills at their real times {ts} (want {fx['want']})", len(ts) == 3 and all(abs(x - y) <= 0.4 for x, y in zip(ts, fx["want"])))
    M.CS2_LATE_ROW_ON[0] = True
    b = {"kills": [{"t": 5.0, "victim": "abc"}]}
    check("an unrelated victim is never re-timed", M.cs2_late_rows_retime({"kills": [{"t": 3.0, "victim": "zzzzz", "ks": 1.0}]}, b) == 0 and b["kills"][0]["t"] == 5.0)
    check("a re-read 12 s earlier is not this row", M.cs2_late_rows_retime({"kills": [{"t": 3.0, "victim": "abcd", "ks": 1.0}]}, {"kills": [{"t": 15.0, "victim": "abcd"}]}) == 0)
    cache = json.loads((M.DATA / "clips_cache3.json").read_text(encoding="utf-8")) if (M.DATA / "clips_cache3.json").exists() else {}
    det = None
    for frag, want in (("Replay 2026-06-25 01-27-36", 3), ("CS2 2026-10-17 02-48-50", 4)):
        rec = next((dict(v, game="cs2") for k, v in cache.items() if frag in k), None)
        if rec is None or not Path(rec["path"]).exists():
            print(f"  ({frag}: the clip or its scan is not in this data folder: skipped)")
            continue
        det = det or M.Detector("cs2")
        e = M.load_kills_cache().get(M.kills_key(rec, "cs2", det))
        if not e:
            print(f"  ({frag}: not scanned: skipped)")
            continue
        ks = [round(k["t"], 1) for k in M.analyse_clip_entry(rec, e, M.load_config(), "cs2")["kills"]]
        check(f"real data, {frag}: {want} kills {ks}", len(ks) == want)


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
    sys.exit(1 if T.FAILS else 0)
