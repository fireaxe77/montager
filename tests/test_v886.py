"""V8.8.6 tests (fast; no montage render, no library scan).
  0) title-bar version V8.8.6; V8.8.6 on top of V8.8.5 in both changelogs
  1) sky: more candidates (the last kill of every other take after the role candidates), the sky colour smoothed only over samples of the same surface, a warm surface is a wall
     in every frame, the sky ends with a fade where the camera leaves it (instead of the take losing its sky)
  2) CS2 stale rows: a kill is linked to an earlier row of its victim only while that row stayed on screen; a 'stale feed row' rejection comes back when the earlier row had gone;
     a row on screen from the first frames (name scan) is pre-clip even when the outline was found later, and so are the rows found in that same frame
  3) song fill: the length estimate is corrected by what the last plan filled, a fill round offers one take more, a montage that still ends short says why
  4) drop: the hit and the gunshot lift give way to the music (compressor keyed by music + game); the music and the game sound pass unchanged; real ffmpeg: no music dip
  5) pick order: every multikill (unused, then used) before any single; the game's previous montage never; Manual pulls companions in every game
  6) everything V8.8.5 checked (tests/test_v885.py parts 1 - 6: sky, mask, patterns, the V1 .. V8.8.4 regression list, identity, Settings)
  (real data: tests/dropaudio886.py, tests/render885.py, tests/skymask885.py, tests/fill883.py)
python tests\\test_v886.py   (parts: V886_PARTS=0,1,2,3,4,5,6)"""
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_src = (HERE / "test_v885.py").read_text(encoding="utf-8")
_ns = {"__file__": str(HERE / "test_v885.py"), "__name__": "test_v885_parts"}
exec(compile(_src[:_src.index('if __name__ == "__main__":')], str(HERE / "test_v885.py"), "exec"), _ns)
V5 = types.SimpleNamespace(**_ns)
T = V5.T
M = T.M
ROOT = T.ROOT
check = T.check
PARTS = [x for x in os.environ.get("V886_PARTS", "0,1,2,3,4,5,6").split(",") if x]
import numpy as np                                                                            # noqa: E402


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.8.6", M.APP_VERSION == "V8.8.6")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.8.6 above V8.8.5", cl[0].startswith("## V8.8.6") and cl[1].startswith("## V8.8.5"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.8.6 above V8.8.5", sm[0].startswith("## V8.8.6") and sm[1].startswith("## V8.8.5"), str(sm[:2]))
    seg = body[body.index("## V8.8.6"):body.index("## V8.8.5")]
    pts = [l for l in seg.splitlines() if l.startswith("- ")]
    head = seg.splitlines()[0].split(":", 1)[-1].strip()
    check(f"simple entry: a 3-8 word headline ('{head}'), 1-4 points", 3 <= len(head.split()) <= 8 and 1 <= len(pts) <= 4)
    check("simple entry is plain", not any(w in seg.lower() for w in ("test", "known issue", "on hold", "def ", "ffmpeg", "cache", "()", "planner", "ledger", "regression", "limiter")))


def part1():
    print("1) sky found more often, never on a wall")
    s = [{"lab": np.array([222.0, 126.0, 112.0]), "std": np.array([3.0, 1.0, 1.0]), "area": 900.0}] * 6 + \
        [{"lab": np.array([101.0, 140.0, 160.0]), "std": np.array([3.0, 1.0, 1.0]), "area": 900.0}] * 18
    sm = M.sky_smooth_samples(s)
    check(f"smoothing keeps the sky's colour while the sky is in the picture (frames 0-5 L {[round(float(x['lab'][0])) for x in sm[:6]]})", all(float(x["lab"][0]) > 200 for x in sm[:6]))
    check("... and never mixes the wall's colour into it (frame 10 stays the wall's own)", abs(float(sm[10]["lab"][0]) - 101.0) < 1)
    b_ = V5.body_of("sky_take_mask")
    check("a warm surface is a wall in every mask frame (the probe's rule)", 'SKY_WARM_FRAME[0] and float(sp["lab"][2]) - 128.0 > 8.0' in b_ and M.SKY_WARM_FRAME[0])
    # the camera leaves the sky after 0.4 s: the take keeps its sky up to there (fading out) instead of losing it
    H, W = M.SKY_H, M.SKY_W
    wall = np.zeros((H, W, 3), np.uint8)
    g_ = np.linspace(0.85, 1.0, H)[:, None, None]
    wall = np.clip(g_ * np.array([215.0, 150.0, 90.0])[None, None, :] * np.ones((H, W, 1)), 0, 255).astype(np.uint8)        # a smooth warm wall (bright orange): the probe's 'warm: a wall'
    seq = [V5._sky_img("sky", seed=i) for i in range(26)] + [wall.copy() for _i in range(30)]
    tk = {"nf": 56, "segs": [[10.0, 10.933, 1.0, 56, 0]], "path": "a.mp4", "rect": [0, 0, W, H], "wh": [W, H], "srcs": [{"path": "a.mp4", "shift": 0.0, "rect": [0, 0, W, H], "wh": [W, H]}]}
    keep_f = M.sky_take_frames
    M.sky_take_frames = lambda plan_, t_, f0_, f1_, size=None: seq[f0_:f1_]
    try:
        xs = {"t0": 2 / 60, "t1": 0.93, "anim": M.sky_anim_params(0.8, 128, "hype"), "seed": 3, "beats": [], "fam": "orange", "pattern": "bands"}
        mp = Path(tempfile.mkdtemp()) / "cut.raw"
        st = M.sky_take_mask(tk, xs, None, mp, ramp=True, plan={"song": {}})
    finally:
        M.sky_take_frames = keep_f
    raw = np.fromfile(mp, np.uint8)
    ys = [raw[f * H * W * 4:f * H * W * 4 + H * W].reshape(H, W) for f in range(56)]
    check(f"the take keeps its sky (bad {st['bad']} of window {st['window']}, cut at {st.get('cut')})", st["bad"] <= M.SKY_MAX_BAD * max(1, st["window"]) and st.get("cut") is not None)
    check("painted while the sky is there", float((ys[10][:150] > 128).mean()) > 0.8)
    check("fades out before the wall (never on it)", max(int(ys[f].max()) for f in range(28, 56)) == 0 and int(ys[25].max()) < int(ys[12].max()))
    # more candidates: after the role candidates, the last kill of every other take (not the first, not calm)
    for more in (False, True):
        M.SKY_MORE_CANDS[0] = more
        p_, _c = T.mk(M, "cs2", "hype", 3, eff={"cs2": "extra"})
        for t_ in p_["takes"]:
            t_.pop("xfx", None)
            if t_.get("role") == "calm" and len(t_.get("kills_out") or []) == 1:
                t_["role"] = "build"                       # ordinary single-kill takes outside a calm part: not a role candidate
        M.assign_extra_fx(p_, "cs2", 3, [], energy=0.8, sky_on=True)
        cand = [(ti, x) for ti, t in enumerate(p_["takes"]) for x in (t.get("xfx") or []) if x["k"] == "sky"]
        if more:
            extra = [(ti, x) for ti, x in cand if x["why"] == "kill"]
            check(f"more sky candidates: {len(cand) - len(extra)} role candidates + {len(extra)} other takes' last kills", len(extra) > 0 and all(x["prio"] == 0 for _ti, x in extra))
            check("never the first take or a middle kill", all(ti != 0 and abs(x["p"] - p_["takes"][ti]["kills_out"][-1]) < 0.01 for ti, x in extra))
            calm_ = [i_ for i_, (ti, x) in enumerate(extra) if p_["takes"][ti].get("role") == "calm"]
            check("takes in calm parts of the song come last", not calm_ or min(calm_) >= len(extra) - len(calm_))
        else:
            n_role = len(cand)
    check("the role candidates are the same as before", n_role == len([1 for t in p_["takes"] for x in (t.get("xfx") or []) if x["k"] == "sky" and x["why"] != "kill"]))


def _presence_case(times_by_victim, a, b):
    keep = M.cs2_victim_times
    M.cs2_victim_times = lambda entry, v: next((ts for k_, ts in times_by_victim.items() if M.cs2_same_victim(k_, v)), [])
    try:
        return M.cs2_presence_check({"ocr": []}, a, b, {})
    finally:
        M.cs2_victim_times = keep


def part2():
    print("2) CS2 stale kill rows")
    on = [x * 0.27 for x in range(0, 22)]                  # the victim's row read from 0.0 to ~5.7 s (it expires)
    again = [12.1 + x * 0.27 for x in range(12)]          # a respawned bot killed again at 12.1 s: a new row
    k = {"t": 12.17, "victim": "BOT Buckshot", "seen_first": 0.0, "seen_strict": True, "seen_lead": 12.17, "row": "[fireaxe] gun [BOT Buckshot]", "ks": 1.0}
    b = {"kills": [k], "rej": []}
    _presence_case({"BOT Buckshot": on + again}, {"rej": []}, b)
    check("a new kill of a respawned victim (the old row gone for 6 s) is not linked to the old row (no 'already on screen' drop)", "seen_first" not in b["kills"][0] and b["kills"][0].get("seen_gone"))
    k2 = {"t": 3.0, "victim": "BOT Rip", "seen_first": 0.0, "row": "[fireaxe] gun [BOT Rip]", "ks": 1.0}
    b = {"kills": [k2], "rej": []}
    _presence_case({"BOT Rip": [x * 0.27 for x in range(14)]}, {"rej": []}, b)
    check("a row that stayed on screen keeps the link", b["kills"][0].get("seen_first") == 0.0)
    rk = {"t": 5.63, "victim": "BOT Rip", "row": "[fireaxe] gun [BOT Rip]", "ks": 1.0}
    b = {"kills": [], "rej": [{"t": 5.63, "reason": "CS2 stale feed row: ...", "ks": 1.0, "_kill": rk, "_ef": 0.0}]}
    _presence_case({"BOT Rip": [x * 0.27 for x in range(10)] + [5.6 + x * 0.27 for x in range(10)]}, {"rej": []}, b)
    check("a 'stale feed row' rejection comes back when the earlier row had gone (new row at 5.6 s)", len(b["kills"]) == 1 and not b["rej"])
    a = {"rej": [{"t": 0.0, "reason": 'pre-clip: row already on screen when the clip starts ([fireaxe] gun [60d1s"CS.PR0"])'}]}
    b = {"kills": [{"t": 1.133, "victim": '60d1s"CS.PR0"', "row": "[fireaxe] gun [60d1s]", "ks": 1.0}, {"t": 1.133, "victim": "(unread a3301)", "row": "[fireaxe] gun [-]", "ks": 0.8},
                   {"t": 14.07, "victim": "Vlad ik -", "row": "[fireaxe] gun [Vlad ik -]", "ks": 1.0}], "rej": []}
    n = _presence_case({'60d1s"CS.PR0"': [x * 0.27 for x in range(20)], "Vlad ik -": [14.0 + x * 0.27 for x in range(5)]}, a, b)
    check(f"rows on screen from the first frame are pre-clip even when the outline was found at 1.13 s (removed {n}); the real kill stays",
          n == 2 and [round(k_["t"], 2) for k_ in b["kills"]] == [14.07] and all(r["reason"].startswith("pre-clip") for r in b["rej"]))
    check("the presence check runs in the CS2 analysis (no rescan: cached name scan)", "cs2_presence_check(entry, a, b, cfg)" in V5.body_of("analyse_clip_entry") and M.CS2_PRESENCE_ON[0])
    check("continuity: gaps over 1.5 s mean the row had gone", M.cs2_continuous([0, 0.3, 0.6, 0.9], 0.0, 0.9) and not M.cs2_continuous([0, 0.3, 3.0], 0.0, 3.0))


def part3():
    print("3) song fill reaches the end")
    import copy
    an = T.an()
    evs = copy.deepcopy(M.fake_events()) + [dict(e, path=e["path"] + ".b.mp4") for e in copy.deepcopy(M.fake_events())] + [dict(e, path=e["path"] + ".c.mp4") for e in copy.deepcopy(M.fake_events())]
    M.FULL_CTX.update(on=False)
    f1 = M.optimal_fit(evs, an, "hype")
    n1 = len(f1["clips"])
    M.FULL_CTX["est_scale"] = 0.75
    f2 = M.optimal_fit(evs, an, "hype")
    M.FULL_CTX["fill_over"] = True
    f3 = M.optimal_fit(evs, an, "hype")
    for k_ in ("est_scale", "fill_over", "last_est"):
        M.FULL_CTX.pop(k_, None)
    check(f"a corrected estimate keeps more clips ({n1} -> {len(f2['clips'])}), a fill round one more ({len(f3['clips'])})", len(f2["clips"]) >= n1 and len(f3["clips"]) >= len(f2["clips"]) and len(f3["clips"]) > n1)
    b_ = V5.body_of("_make_plan")
    check("each fill round corrects the estimate by what the last plan filled", 'FULL_CTX["est_scale"] = round(max(0.5' in b_ and 'FULL_CTX["fill_over"] = True' in b_ and M.SONG_FILL_SCALE[0])
    check("a montage that still ends short says why (the reasons of the clips not placed)", "song fill: the montage still ends" in b_)
    check("the fill context never leaks into the next plan", all(f'FULL_CTX.pop("{k_}", None)' in V5.body_of("make_plan") for k_ in ("est_scale", "fill_over", "last_est")))


def part4():
    print("4) the drop never lowers the music")
    p_, c_ = T.mk(M, "cs2", "hype", 3, eff={"cs2": "extra"})
    gr = M.build_filter(p_, c_, False)[1]
    if "[bm]" in gr:
        check("drop extras go through a compressor keyed by music + game", "sidechaincompress=" in gr and "[sgm]" in gr and "[dxc]" in gr)
        check("the music path is the plain song (no volume automation)", any(l_.strip().endswith("[sg]") and "eval=frame" not in l_ for l_ in gr.split(";")))
    else:
        check("synthetic plan has a drop moment", False)
    # real ffmpeg: loud music (-2 dBFS square-ish tone) + a full-scale hit at 2.0 s through the montage's own mix chains
    d = Path(tempfile.mkdtemp(prefix="v886d_"))
    dr = [{"t": 2.0, "lift_db": 4.0, "boom_f0": 90, "boom_f1": 40, "boom_r": 6, "boom_dec": 5, "boom_db": -0.3}]
    _dip, lift, hits = M.drop_audio_filters(dr)
    LAT = ":latency=1" if M._alimiter_latency() else ""

    def mix(new):
        ch = ["[0:a]aformat=sample_fmts=fltp:channel_layouts=stereo,volume=0.7943[sg]", "[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo[gc]", f"{hits[0]}[bm]"]
        if new:
            ch += ["[gc]volume=0.7943,asplit=3[gh][gx][gk]", f"[gx]volume='{lift}-1':eval=frame[gl]", "[gl][bm]amix=inputs=2:duration=first:normalize=0[dx]",
                   "[sg]asplit=2[sgm][sgk]", "[sgk][gk]amix=inputs=2:duration=first:normalize=0[dk]",
                   f"[dx][dk]sidechaincompress=threshold={M.DROP_GW[0]}:ratio={M.DROP_GW[1]}:attack={M.DROP_GW[2]}:release={M.DROP_GW[3]}:detection=peak:level_sc=1:makeup=1[dxc]",
                   "[sgm][gh][dxc]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.99:attack=2:release=40:level=disabled" + LAT + "[o]"]
        else:
            ch += [f"[gc]volume='0.7943*{lift}':eval=frame[gh]", "[sg][gh][bm]amix=inputs=3:duration=first:normalize=0,alimiter=limit=0.99:attack=2:release=40:level=disabled" + LAT + "[o]"]
        out_ = d / f"{int(new)}.wav"
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=4:r=48000,volume=6,aformat=channel_layouts=stereo", "-f", "lavfi", "-i",
                            "anoisesrc=d=4:r=48000:a=0.15,aformat=channel_layouts=stereo", "-filter_complex", ";".join(ch), "-map", "[o]", str(out_)], capture_output=True)
        if r.returncode:
            raise RuntimeError(r.stderr.decode("utf-8", "ignore")[-300:])
        return out_
    try:
        res = {}
        for new in (False, True):
            r = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", str(mix(new)), "-ac", "1", "-f", "f32le", "-"], capture_output=True).stdout, np.float32)
            s = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=4:r=48000,volume=6", "-af", "volume=0.7943", "-f", "f32le", "-"], capture_output=True).stdout, np.float32)
            n = min(len(r), len(s))
            w = 4800
            g = [20 * np.log10(max(1e-6, float(np.dot(r[i:i + w], s[i:i + w]) / max(1e-9, float(np.dot(s[i:i + w], s[i:i + w])))))) for i in range(0, n - w, w)]
            res[new] = float(np.mean(g[20:25])) - float(np.median(g[5:18]))
        check(f"real ffmpeg: the music at the hit was lowered {res[False]:+.2f} dB the old way, {res[True]:+.2f} dB now", res[False] < -0.3 and res[True] > -0.1)
    except Exception as ex:                                # noqa: BLE001
        check("drop mix renders", False, str(ex))


def part5():
    print("5) multikills and companions first")
    mk = lambda i, n, plain=False: {"path": f"/c/{i}.mp4", "n": n, "plain": plain, "score": 50.0 + n * 10 - i * 0.01, "times": [1.0 + j for j in range(n)], "span": n - 1.0, "rows": [1.1 + j for j in range(n)],
                                   "pre": 3.0, "post": 3.0, "parts": None}
    evs = [mk(1, 1, True), mk(2, 1, False), mk(3, 3), mk(4, 2), mk(5, 1, True), mk(6, 4), mk(7, 2)]
    used = {M._pkey("/c/4.mp4"): "2026-10-01", M._pkey("/c/6.mp4"): "2026-09-01", M._pkey("/c/7.mp4"): "2026-10-20"}
    keep_u, keep_h = M.used_dates, M.hist_list
    M.used_dates = lambda: dict(used)
    M.hist_list = lambda store, game=None: [{"clips": ["/c/7.mp4"]}]          # the previous montage
    try:
        pick, _n = M.weekly_pick(list(evs), dict(M.DEFAULT_CONFIG), "optimal", "hype", game="valorant", need_s=24.0)
        add, reused = M.weekly_more(list(evs), [], "hype", "valorant", 24.0)
    finally:
        M.used_dates, M.hist_list = keep_u, keep_h
    order = [e["path"][3] for e in pick]
    check(f"pick: the unused multikill, then the used ones (oldest use first), before any single ({order})", order[:3] == ["3", "6", "4"])
    check("the previous montage's clip is never taken", "7" not in order and all(e["path"] != "/c/7.mp4" for e in add))
    check(f"fill (weekly_more) uses the same order ({[e['path'][3] for e in add]})", [e["path"][3] for e in add][:3] == ["3", "6", "4"])
    keep_c = M.event_sky_cov
    M.event_sky_cov = lambda e, cfg: 0.2 if e["path"] in ("/c/4.mp4",) else 0.0
    M.FULL_CTX["sky_pick"] = dict(M.DEFAULT_CONFIG)
    try:
        sf = [e["path"][3] for e in M._sky_first([evs[2], evs[5], evs[3]])]
    finally:
        M.event_sky_cov = keep_c
        M.FULL_CTX.pop("sky_pick", None)
    check(f"with the sky on, a multikill with a clear sky on its last kill comes first within its group ({sf})", sf == ["4", "3", "6"])
    check("only when the job has the sky on (extra effects)", 'FULL_CTX["sky_pick"] = cfg' in V5.body_of("_make_plan") and M._sky_first([evs[2], evs[5]]) == [evs[2], evs[5]])
    check("Manual pulls in the companion clips of ticked clips in every game", "(game == \"cs2\" or MANUAL_PAIR_ALL[0]) and manual and paths" in V5.body_of("_make_plan")
          and "pairing_run(cfg, tagged, paths, quiet=not scan, game=game)" in V5.body_of("_make_plan") and M.MANUAL_PAIR_ALL[0])


def part6():
    print("6) everything V8.8.5 checked (sky, mask, patterns, the regression list, identity, Settings); the 'identical to v8.8.4' guards with this version's two look / sound switches off")
    M.SKY_MORE_CANDS[0] = M.DROP_GIVE_WAY[0] = False
    try:
        for p_ in ("1", "2", "3", "4", "5", "6"):
            V5.__dict__["part" + p_]()
    finally:
        M.SKY_MORE_CANDS[0] = M.DROP_GIVE_WAY[0] = True
    gone = "assign_extra_fx (sky candidates and placement) identical to v8.8.4"
    if gone in T.FAILS:                                    # V8.8.6 changed its source on purpose (the extra candidates): checked by behaviour instead
        T.FAILS.remove(gone)
        print("  (replaced: the source of assign_extra_fx changed in V8.8.6 - its output with the new candidates switched off is compared instead)")
    B = V5.prev()
    same = True
    M.SKY_MORE_CANDS[0] = M.SLOW_KEEP_FIRST[0] = False          # (and V8.8.5's ending beat fix, which moves the ending's effects with its kills)
    try:
        for g in ("valorant", "cs2", "r6s"):
            pa, _ = T.mk(M, g, "aggressive", 2, eff={g: "extra"})
            pb, _ = T.mk(B, g, "aggressive", 2, eff={g: "extra"})
            same = same and T.js([t.get("xfx") for t in pa["takes"]]) == T.js([t.get("xfx") for t in pb["takes"]])
    finally:
        M.SKY_MORE_CANDS[0] = M.SLOW_KEEP_FIRST[0] = True
    check("with the extra candidates off, every take's effects and sky candidates identical to v8.8.4", same)


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
    sys.exit(1 if T.FAILS else 0)
