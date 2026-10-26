"""V9.1.0 tests (fast, no render).
  0) title-bar version V9.1.0, the version in the packaging / START_HERE, the V9.1.0 entry on top of both changelogs
  1) drop kills are real: the CS2 dating gate ignores red in the row's slot that is not shaped like a row outline (a damage flash tinting the scene), so the row's first appearance is proven;
     the dating memo is re-seeded without the old gate's rejections / loose proofs; a kill whose first appearance is not proven (or whose name was not read) is never put on a drop
  2) strong beats: stored next to the drop labels (each list kept when the other changes); every strong beat gets a kill on its stored time (within one frame) in Valorant, CS2 and R6S,
     after the drops (no drop time or kill changes), the least valuable take first, never the headline / ending / a drop take, no drop moment effects; a strong beat on a drop is the
     drop's; a song without strong beats plans exactly as before
  3) sky: solid colour (no old sky showing through), ice white, every family with a visible tonal range, the pattern visible on a black family, sky only in drop / build / headline / ending takes
  4) pacing: in a high-energy song a speed-ramped run-up is never longer than the plain one: more energy gives shorter or equal run-ups and tails; no drop loses its kill
python tests\\test_v910.py   (parts: V910_PARTS=0,1,2,3,4)"""
import copy
import inspect
import json
import os
import statistics
import sys
import tempfile
import types
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
TMP = Path(tempfile.mkdtemp(prefix="v910_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
warnings.simplefilter("ignore")
import numpy as np                                                                           # noqa: E402
import montage as M                                                                          # noqa: E402

PARTS = [x for x in os.environ.get("V910_PARTS", "0,1,2,3,4").split(",") if x]
FAILS = []
FRAME_MS = 1000.0 / M.OUT_FPS + 0.05


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


_T = []


def helpers():
    if not _T:
        src = (HERE / "test_v842.py").read_text(encoding="utf-8")
        ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
        exec(compile(src[:src.index("def part0")], str(HERE / "test_v842.py"), "exec"), ns)
        _T.append(types.SimpleNamespace(**ns))
    return _T[0]


def part0():
    print("0) version, packaging, changelogs")
    check("APP_VERSION = V9.1.0", M.APP_VERSION == "V9.1.0", M.APP_VERSION)
    check("START_HERE names V9.1.0", (ROOT / "START_HERE.txt").read_text(encoding="utf-8").startswith("MONTAGER V9.1.0"))
    check("installer example names 9.1.0", "/DAppVersion=9.1.0 " in (ROOT / "packaging" / "montager.iss").read_text(encoding="utf-8"))
    check("release script example names v9.1.0", "(v9.1.0 for V9.1.0)" in (ROOT / "packaging" / "make_release.py").read_text(encoding="utf-8"))
    simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    check("Settings changelog: V9.1.0 on top of V9.0.3, headline names strong beats", 0 <= simple.index("## V9.1.0") < simple.index("## V9.0.3")
          and "strong beat" in simple[simple.index("## V9.1.0"):].split(chr(10))[0].lower().replace("-", " "))
    top = simple[simple.index("## V9.1.0"):simple.index("## V9.0.3")]
    check("Settings entry: plain points only (no KNOWN ISSUE / function names)", "KNOWN" not in top.upper() and "_" not in top and 1 <= top.count("\n- ") <= 4, top)
    check("CHANGELOG.md: V9.1.0 on top of V9.0.3", 0 <= tech.index("## V9.1.0") < tech.index("## V9.0.3"))


def _feed_frames(tint=True):
    """30 killfeed frames (BGR): a blue sky; my row (dark box, a red outline, text-like marks) fades in at frames 12-13 and stays; frames 8-10: a red damage flash over the scene
    (diagonal red streaks crossing the row's slot, like an orange crane tinted red), never a row outline."""
    h, w = 120, 600
    rng = np.random.RandomState(4)
    txt = (rng.rand(24, 440) > 0.6).astype(np.uint8) * 200
    rc = {"x0": 50, "x1": 500, "y0": 40, "y1": 72}
    frames = []
    for f in range(30):
        fr = np.zeros((h, w, 3), np.uint8)
        fr[:] = (235, 185, 95)                                                               # blue sky (BGR)
        if tint and 8 <= f <= 10:
            for k in range(6):                                                               # red streaks (the tinted scene)
                for y in range(h):
                    x = 60 + k * 75 + y // 3
                    fr[y, x:x + 8] = (30, 30, 205)
        if f >= 12:
            a = 0.5 if f == 12 else 1.0
            box = fr[rc["y0"]:rc["y1"], rc["x0"]:rc["x1"]].astype(np.float32)
            row = np.zeros_like(box)
            row[:] = (60, 40, 30)
            row[4:28, 5:445, :] += txt[:, :440, None]
            row[0:2, :] = row[-2:, :] = (30, 30, 205)                                        # the red outline (top, bottom, sides)
            row[:, 0:2] = row[:, -2:] = (30, 30, 205)
            fr[rc["y0"]:rc["y1"], rc["x0"]:rc["x1"]] = np.clip(box * (1 - a) + row * a, 0, 255).astype(np.uint8)
        frames.append(fr)
    return frames, rc


def part1():
    print("1) drop kills are real: the dating gate, the memo, clearly read drop kills")
    frames, rc = _feed_frames()
    m_row = M.border_dm(frames[20])[0]
    m_tint = M.border_dm(frames[9])[0]
    cov_row = M._outline_cover(m_row, rc["y0"], rc["y1"] - rc["y0"], rc["x0"] - 3, rc["x1"] + 4)
    cov_tint = M._outline_cover(m_tint, rc["y0"], rc["y1"] - rc["y0"], rc["x0"] - 3, rc["x1"] + 4)
    tint_px = int(m_tint[rc["y0"] - 3:rc["y1"] + 4, rc["x0"] - 3:rc["x1"] + 4].sum())
    ref = int(m_row[rc["y0"] - 3:rc["y1"] + 4, rc["x0"] - 3:rc["x1"] + 4].sum())
    check("a row outline covers both long edges, the red flash does not", cov_row >= 0.9 and cov_tint < M.CS2_GATE_EDGES, f"row {cov_row:.2f} tint {cov_tint:.2f}")
    check("the flash puts as much red in the slot as the old gate rejects on (>= 30 % of the row's outline)", tint_px >= 0.3 * ref, f"{tint_px} vs {ref}")
    keep = M.CS2_GATE_SHAPE[0]
    try:
        M.CS2_GATE_SHAPE[0] = False
        old = M.cs2_dating_walk(frames, rc, 20, 30.0)
        M.CS2_GATE_SHAPE[0] = True
        new = M.cs2_dating_walk(frames, rc, 20, 30.0)
    finally:
        M.CS2_GATE_SHAPE[0] = keep
    check("before: the flash made the gate reject the row's true start (the kill kept its late time)", old == M.CS2_GATE_REJECT, str(old))
    check("now: the row's first appearance is proven at its fade-in frame (12)", new in (12, 13), str(new))
    fr2, _ = _feed_frames(tint=False)
    fr2[9][rc["y0"]:rc["y1"], rc["x0"]:rc["x1"]] = frames[20][rc["y0"]:rc["y1"], rc["x0"]:rc["x1"]]       # the same row really on screen earlier (frame 9)
    check("a real row in the slot before the start still rejects it", M.cs2_dating_walk(fr2, rc, 20, 30.0) == M.CS2_GATE_REJECT)
    # the memo: v9 seeded from v8 without its rejections and loose proofs
    d8 = {"clipA|k#0": M.CS2_GATE_REJECT, "clipA|k#0~loose": False, "clipB|k#1": 90, "clipB|k#1~loose": True, "clipC|k#2": 44, "clipC|k#2~loose": False, "clipD|k#3": None}
    (M.DATA).mkdir(parents=True, exist_ok=True)
    (M.DATA / "cs2_dating_v8.json").write_text(json.dumps(d8), encoding="utf-8")
    for k in [k for k in M.CS2_DATING_MEMO]:
        M.CS2_DATING_MEMO.pop(k)
    M._dating_memo_load()
    have = {f"{k[0]}#{k[1]}" for k in M.CS2_DATING_MEMO if isinstance(k, tuple)}
    check("memo file is cs2_dating_v9.json", M._dating_file().name == "cs2_dating_v9.json")
    check("seeded from v8 without the gate rejections and the loose proofs (those rows are dated again)", have == {"clipC|k#2", "clipC|k#2~loose", "clipD|k#3"}, str(sorted(have)))
    # clearly read drop kills
    tk = {"kills": [1.0, 2.0, 3.0], "ev": {"unproven": [True, False, False], "unread": [False, True, False]}}
    check("drop_kill_clear: unproven / unread kills are not clear, the others are", [M.drop_kill_clear(tk, k) for k in range(3)] == [False, False, True])
    check("drop_kill_clear: an uncertain (lower edge) kill is not clear; a kill without flags is", not M.drop_kill_clear({"kills": [1.0], "ev": {"unsure": [True]}}, 0)
          and M.drop_kill_clear({"kills": [1.0], "ev": {"times": [1.0]}}, 0))
    check("the planner stores the flags on the take (drop_skip) only when a kill needs it", M.drop_skip_flags({"unproven": [False, True], "unread": [True, False]}, 2) == [True, True]
          and not any(M.drop_skip_flags({"times": [1, 2]}, 2)) and not M.drop_kill_clear({"kills": [1.0, 2.0], "drop_skip": [False, True]}, 1))
    T = helpers()
    M.INTRO_CTX.update({"on": False, "manual": False})
    plan, _ = T.mk(M, "cs2", "hype", 3)
    ds = [x for x in plan.get("drop_sync") or [] if x.get("take")]
    check("the synthetic CS2 plan anchors its drops", bool(ds), str(plan.get("drop_sync")))
    if ds:
        x0 = ds[0]
        q = copy.deepcopy({k: v for k, v in plan.items() if k != "takes"})
        q["takes"] = [dict(t) for t in plan["takes"]]
        tk0 = q["takes"][x0["take"] - 1]
        tk0["drop_skip"] = [i == x0["kill"] - 1 for i in range(len(tk0["kills"]))]          # what the planner stores for a kill whose first appearance is not proven
        q.pop("drop_sync", None)
        M.anchor_all_drops(q, [(float(y["drop"]), 2.0, "label") for y in plan["drop_sync"]], "cs2", [])
        got = next(y for y in q["drop_sync"] if abs(y["drop"] - x0["drop"]) < 1e-6)
        same_kill = got.get("take") and q["takes"][got["take"] - 1]["path"] == tk0["path"] and got["kill"] == x0["kill"]
        check(f"drop {x0['drop']:.3f}: its kill marked unproven is not used again (another clear kill or the reason is logged)", not same_kill and (got.get("take") or got.get("why")), str(got))
        if got.get("take"):
            check("... and the clear kill sits on the drop within half a frame", abs(float(got["err_ms"])) <= FRAME_MS / 2, str(got))


def _beats_for(plan, n=2):
    """strong beat times inside the montage window, on beat ticks, at least 1.5 s from every drop"""
    s0, D = float(plan["song"]["start_t"]), float(plan["duration"])
    drops = [float(x["drop"]) for x in plan.get("drop_sync") or []]
    bo = [s0 + b for b in plan.get("beats_out") or []]
    cand = [b for b in bo if s0 + 3.0 < b < s0 + D - 4.0 and all(abs(b - d) >= 1.5 for d in drops)]
    if not cand:
        return []
    return [round(cand[int(len(cand) * f)], 3) for f in ((0.3, 0.7) if n == 2 else (0.5,))]


def part2():
    print("2) strong beats")
    song = str(TMP / "songA.mp3")
    M.song_drops_write(song, [30.0, 60.0], "A", "B")
    M.song_drops_write(song, [45.5, 75.25], "A", "B", kind="strong_beats")
    check("stored next to the drop labels, both lists kept", M.song_drop_labels(song) == [30.0, 60.0] and M.song_strong_beats(song) == [45.5, 75.25])
    M.song_drops_write(song, [31.0], "A", "B")
    check("changing the drops keeps the strong beats", M.song_drop_labels(song) == [31.0] and M.song_strong_beats(song) == [45.5, 75.25])
    M.song_drops_write(song, None, kind="strong_beats")
    check("removing the strong beats keeps the drops", M.song_drop_labels(song) == [31.0] and M.song_strong_beats(song) is None)
    M.song_drops_write(song, None)
    check("removing both removes the song's entry", (Path(M.DATA) / "song_drops.json").exists() and Path(song).name not in json.loads((Path(M.DATA) / "song_drops.json").read_text(encoding="utf-8")))
    check("song map window: a 'strong beat' choice next to the drops, blue lines", "strong beat" in inspect.getsource(M.SongMapView) and "STRONG BEAT" in inspect.getsource(M.SongMapView))
    check("command line: strongbeatsave (like dropsave)", "strongbeatsave" in inspect.getsource(M.main) if hasattr(M, "main") else "strongbeatsave" in (ROOT / "montage.py").read_text(encoding="utf-8"))
    T = helpers()
    keep = M.song_strong_beats
    try:
        for game in ("valorant", "cs2", "r6s"):
            for style, seed in (("hype", 3), ("chill", 7)):
                M.INTRO_CTX.update({"on": False, "manual": False})
                M.song_strong_beats = lambda p: None
                base, _ = T.mk(M, game, style, seed, eff={"valorant": "extra", "cs2": "extra", "r6s": "extra"})
                beats = _beats_for(base)
                if not beats:
                    check(f"{game} {style}: room for strong beats in the synthetic plan", False)
                    continue
                M.song_strong_beats = lambda p, b=beats: list(b)
                pl, _ = T.mk(M, game, style, seed, eff={"valorant": "extra", "cs2": "extra", "r6s": "extra"})
                tag = f"{game} {style} seed {seed}"
                bs = pl.get("beat_sync") or []
                anch = [x for x in bs if x.get("take")]
                ok = len(bs) == len(beats) and anch and all(abs(float(x["err_ms"])) <= FRAME_MS for x in anch) and all(x.get("take") or x.get("why") for x in bs)
                check(f"{tag}: {len(anch)} of {len(beats)} strong beat(s) with a kill on the stored time (within one frame); any other one says why (never skipped silently)", ok, str(bs))
                key = lambda p: [(x["drop"], x.get("impact"), x.get("kill"), p["takes"][x["take"] - 1]["path"] if x.get("take") else None) for x in p.get("drop_sync") or []]
                check(f"{tag}: every drop keeps its time and its kill", key(pl) == key(base), f"{key(base)} vs {key(pl)}")
                drop_paths = {pl["takes"][x["take"] - 1]["path"] for x in pl.get("drop_sync") or [] if x.get("take")}
                bad = [x for x in bs if x.get("take") and (pl["takes"][x["take"] - 1]["path"] in drop_paths or pl["takes"][x["take"] - 1].get("role") == "headline"
                                                           or pl["takes"][x["take"] - 1].get("ending"))]
                check(f"{tag}: never the headline, the ending or a drop take", not bad, str(bad))
                first = next((x for x in bs if x.get("take")), None)
                if first is not None:                      # the first anchored strong beat: every smaller free take with a kill in reach could not move there (on the plan before the strong beats)
                    fps = round(base["total_frames"] / base["duration"])
                    smaller = []
                    for ti, t in enumerate(base["takes"]):
                        if t["path"] in drop_paths or t.get("role") == "headline" or t.get("ending") or not t.get("kills_out") or len(t["kills"]) >= first["n"]:
                            continue
                        for kj in range(len(t["kills"])):
                            if abs(M.impact_time(base, ti, kj) - first["beat"]) <= M.DROP_SEARCH and M.move_kill(base, ti, kj, first["beat"], fps, protected=drop_paths)[0] is not None:
                                smaller.append((ti + 1, len(t["kills"])))
                    check(f"{tag}: the least valuable take that fits is used ({first['n']}k; no smaller free take could move there)", not smaller, str(smaller))
                nd = sum(1 for x in pl.get("drop_sync") or [] if x.get("take"))
                check(f"{tag}: no drop moment on a strong beat ({len(pl.get('xfx_drop') or [])} drop moments for {nd} anchored drops)", len(pl.get("xfx_drop") or []) <= nd)
                drop_t = [float(x["drop"]) for x in base.get("drop_sync") or []]
                if drop_t:
                    M.song_strong_beats = lambda p, d=drop_t[0]: [d + 0.05]
                    p3, _ = T.mk(M, game, style, seed)
                    check(f"{tag}: a strong beat on a drop is that drop's (nothing placed again, the drop unchanged)", not [x for x in p3.get("beat_sync") or [] if x.get("take")]
                          and key(p3) == key(base))
                M.song_strong_beats = lambda p: None
                p4, _ = T.mk(M, game, style, seed, eff={"valorant": "extra", "cs2": "extra", "r6s": "extra"})
                check(f"{tag}: no strong beats = the plan exactly as before", json.dumps(p4, sort_keys=True, default=str) == json.dumps(base, sort_keys=True, default=str) and "beat_sync" not in p4)
    finally:
        M.song_strong_beats = keep


def part3():
    print("3) sky: solid, ice white, visible pattern, high-energy parts only")
    check("the family colour keeps none of the old sky's brightness and covers it fully inside the mask", M.SKY_FAM_EVEN == 0.0 and M.SKY_FAM_OPACITY == 1.0
          and "SKY_FAM_OPACITY if fam_" in inspect.getsource(M.sky_take_mask))
    g = M.sky_family_grade("orange", 150)
    check("every layer of the family look is the solid colour (no share of the sky's own brightness)", all(g[k]["y_mul"] == 0.0 for k in ("top", "bot", "dark", "jump")))
    top, bot, _j = M.SKY_FAMILIES["white"]
    yt, ut, vt = M._rgb_to_yuv(top)
    check("white = ice white: a pale ice blue top (blue chroma) to white", bot == 0xFFFFFF and ut > 135 and yt > 140, f"{top:06X} y {yt:.0f} u {ut:.0f}")
    rng_ = {f: M._rgb_to_yuv(b)[0] - M._rgb_to_yuv(t)[0] for f, (t, b, _x) in M.SKY_FAMILIES.items()}
    check("every family has a visible tonal range top -> bottom (>= 70 levels)", min(rng_.values()) >= 70, str({k: round(v) for k, v in rng_.items()}))
    gb = M.sky_family_grade("black", 150)
    check("black: the pattern shows in a lighter tone than the black top", gb["dark"]["y_add"] > gb["top"]["y_add"] + 30)
    roles = {r: M.sky_role_ok({"role": r}) for r in ("drop", "build", "headline", "calm")}
    check("sky only in drop / build / headline / ending takes, never in calm ones", roles == {"drop": True, "build": True, "headline": True, "calm": False}
          and M.sky_role_ok({"role": "calm", "ending": True}), str(roles))
    check("the render's sky choice leaves calm takes out before it ranks", "sky_role_ok(plan[\"takes\"][c[\"ti\"]])" in inspect.getsource(M.xfx_probe_sky))


def part4():
    print("4) pacing follows the energy")
    T = helpers()
    M.INTRO_CTX.update({"on": False, "manual": False})

    def stats(style, energy, flag=True):
        M.RAMP_NO_LONGER[0] = flag
        runs, tails = [], []
        for game in ("valorant", "cs2", "r6s"):
            for seed in (3, 7, 11):
                try:
                    p, _ = T.mk(M, game, style, seed, energy=energy)
                except RuntimeError:
                    continue
                for t in p["takes"]:
                    if t.get("ending") or t.get("role") == "headline" or not t.get("kills_out"):
                        continue
                    runs.append(t["kills_out"][0])
                    tails.append(t["dur"] - t["kills_out"][-1])
        M.RAMP_NO_LONGER[0] = True
        return statistics.median(runs), sorted(runs)[int(0.9 * len(runs))], statistics.median(tails)
    hi = {s_: stats(s_, 0.99) for s_ in ("aggressive", "hype")}
    lo = {s_: stats(s_, 0.6) for s_ in ("hype", "smooth", "chill")}
    old = {s_: stats(s_, 0.99, False) for s_ in ("aggressive", "hype")}
    f = lambda d: "; ".join(f"{k} {v[0]:.2f}/{v[1]:.2f} tail {v[2]:.2f}" for k, v in d.items())
    print("     run-up median / p90 (s): energy 0.99: " + f(hi) + " | energy 0.6: " + f(lo) + " | energy 0.99 before the fix: " + f(old))
    check("before the fix a high-energy song had longer run-ups (p90) than a chill song", max(v[1] for v in old.values()) > lo["chill"][1], str(old))
    check("energy 0.99 (aggressive / hype): run-ups (median and p90) shorter or equal to every style at energy 0.6",
          all(h[0] <= l[0] + 1e-6 and h[1] <= l[1] + 1e-6 for h in hi.values() for l in lo.values()), f"{hi} vs {lo}")
    check("the same style: more energy never gives longer run-ups or tails (hype 0.99 vs hype 0.6)", hi["hype"][0] <= lo["hype"][0] + 1e-6 and hi["hype"][1] <= lo["hype"][1] + 1e-6
          and hi["hype"][2] <= lo["hype"][2] + 1e-6)
    check("the fix never lengthens a run-up", all(hi[s_][0] <= old[s_][0] + 1e-6 and hi[s_][1] <= old[s_][1] + 1e-6 for s_ in hi))
    lost = 0
    for game in ("valorant", "cs2", "r6s"):
        for style, seed in (("hype", 3), ("aggressive", 11)):
            M.INTRO_CTX.update({"on": True, "text": None, "series": 1, "manual": False})
            p, _ = T.mk(M, game, style, seed, energy=0.99)
            lost += sum(1 for x in p.get("drop_sync") or [] if not x.get("take") and not x.get("intro_zone"))
    M.INTRO_CTX.update({"on": False, "series": None})
    check("the tighter pacing never costs a drop its kill (energy 0.99, intro on)", lost == 0, str(lost))


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall checks passed")
    sys.exit(1 if FAILS else 0)
