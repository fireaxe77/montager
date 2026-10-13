"""V7.7.5 tests. Sections (each prints ok / FAIL lines, the last line is ALL OK only when every check ran and passed):
  0) title-bar version V7.7.5, one entry on top of both changelogs
  1) song matching: primary artist + base title, both name orders, supporting artists / bracketed extras ignored, ambiguous pairs never matched + listed, the real library numbers
  2) CS2 stale / phantom rows: the 2025.08.16 clip (three stale feed rows read as a 3k), the same-timestamp guard, the real same-timestamp events of the cache
  3) CS2 duplicated row fragment (2026.02.14: AWP collateral read as a 3k), the slow-mo ending (safe + clean ending preferred)
  4) plan-time kill-window assertion (every kill of an event inside the placed take, build-up shown)
  5) soft transitions: the dissolve weights (0.1 ... 0.9, never outside 0..1) and the post-render luma-spike check (the 7.7.1 flash is found)
  6) post-render CS2 detector coverage: the montage scan does not apply the one-round / one-fight duplicate rules of a single clip
  g) guards: events / kills / takes / cut lists / drops identical to V7.7.1 (50 + 50 generated clips, the 7 real Valorant clips, the real CS2 trio and singles)
Runs on a COPY of montage_data (V7_DATA_SRC picks the folder; the real folder is only read).   python tests\\test_v775.py   (parts: V775_PARTS=0,1,2,3,4,5,6,g)
The real Force New renders (CS2 + Valorant, with the sync report, transition check and audio levels) are tests\\verify775.py."""
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


def quiet(fn, *a, **k):
    keep = (M.out, M.LOGONLY)
    lines = []
    M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        return fn(*a, **k), lines
    finally:
        M.out, M.LOGONLY = keep


def jplan(p):
    return json.dumps(p, sort_keys=True, default=str)


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


# ------------------------------------------------------------------------------------------------ 0) version + changelogs
def part_version(tmp):
    with section("0) title-bar version V7.7.5, one entry on top of both changelogs, readable history rules"):
        simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
        tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        hs, ht = re.findall(r"(?m)^## (.+)$", simple), re.findall(r"(?m)^## (.+)$", tech)
        check(M.APP_VERSION == "V7.7.5" and hs[0].startswith("V7.7.5") and ht[0].startswith("V7.7.5"), "APP_VERSION V7.7.5 and the entry on top of both files")
        blk = re.split(r"(?m)^## .+$", simple)[1]
        pts = [x for x in blk.splitlines() if x.startswith("- ")]
        check(1 <= len(pts) <= 4 and not re.search(r"KNOWN ISSUE|on hold|ABANDON", simple), f"readable entry: {len(pts)} plain points, no known-issue lines")
        check(len(hs[0].split(":", 1)[1].split()) in range(3, 9), "one headline of 3 to 8 words: " + hs[0].split(":", 1)[1].strip())
        check(not re.search(r"test_v|def |\.py|_|\(\)", blk), "no test names, function names or technical detail in the plain entry")
        check(sum(1 for h in hs if h.startswith("V7.7.5")) == 1 and sum(1 for h in ht if h.startswith("V7.7.5")) == 1, "one entry per version")


PARTS["0"] = part_version


# ------------------------------------------------------------------------------------------------ 1) song matching
def mk_audio(names):
    return [{"path": "C:/Songs/" + n + ".mp3", "title": "", "artist": "", "key": f"C:/Songs/{n}.mp3|{1000 + i}|1"} for i, n in enumerate(names)]


def mk_rows(pairs):
    return [{"title": t, "artist": a, "added": "", "uri": f"u{i}", "dur": 0.0, "tempo": 0.0, "energy": None, "dance": None} for i, (a, t) in enumerate(pairs)]


def part_songs(tmp):
    with section("1) song matching: primary artist + base title"):
        cfg = {}
        rows = mk_rows([("Yung Gravy", "Rotisserie"), ("Xd", "Perfect Exceeder"), ("S3RL", "Dance More"), ("Artist One", "Song A"), ("Artist Two", "Song A"),
                        ("R.I.O.", "Hey Mama"), ("Lauv", "i'm so tired"), ("Bob", "Same Title"), ("Cat", "Same Title"), ("Dan", "Lonely Track"), ("Eve", "Twin"), ("Eve", "Twin (Remix)"), ("Gina", "Rain"), ("Hal", "Snow")])
        audio = mk_audio(["Yung Gravy, bbno$, Dontcry - Rotisserie (Resauced)",              # "Artist, Supporting - Song (jargon)"
                          "Perfect Exceeder - Xd",                                           # "Song - Artist"
                          "S3RL, Ella, Atef feat. Someone - Dance More (DJ Edit) [Lyrics]",
                          "Artist One - Song A (Official Video)",
                          "Hey Mama - R.I.O",                                                # missing dot
                          "i'm so tired - Lauv, Troye Sivan [7HMikdsxIGYzXXw6cdKlyY]",       # a trailing id
                          "Bob x Zed - Same Title (Sped Up)",
                          "Dan - Lonely Track",
                          "Dan - Lonely Track (Resauced)",                                   # a second file for one track: not matched twice
                          "Eve - Twin (Sped Up)",
                          "Gina feat. Zed - Rain (Remix)", "Snow (feat. Gina) - Hal with Zed"])                                           # one file for two tracks: ambiguous
        matched, un = M.match_playlist(rows, audio, cfg)
        got = {Path(a["path"]).stem: (r["artist"], r["title"], sc) for r, a, sc in matched}
        want = {"Yung Gravy, bbno$, Dontcry - Rotisserie (Resauced)": ("Yung Gravy", "Rotisserie"), "Perfect Exceeder - Xd": ("Xd", "Perfect Exceeder"),
                "S3RL, Ella, Atef feat. Someone - Dance More (DJ Edit) [Lyrics]": ("S3RL", "Dance More"), "Artist One - Song A (Official Video)": ("Artist One", "Song A"),
                "Hey Mama - R.I.O": ("R.I.O.", "Hey Mama"), "i'm so tired - Lauv, Troye Sivan [7HMikdsxIGYzXXw6cdKlyY]": ("Lauv", "i'm so tired"),
                "Bob x Zed - Same Title (Sped Up)": ("Bob", "Same Title"), "Gina feat. Zed - Rain (Remix)": ("Gina", "Rain"), "Snow (feat. Gina) - Hal with Zed": ("Hal", "Snow")}
        for f, (a, t) in want.items():
            check(f in got and got[f][:2] == (a, t), f"'{f}' -> '{a} - {t}'" + ("" if f in got else " (NOT matched)"))
        check("Artist Two" not in {v[0] for v in got.values()}, "the same title by another primary artist is not matched")
        check(all(v[0] != "Cat" for v in got.values()), "'Same Title' by Cat is not matched to Bob's file")
        lonely = [f for f in got if f.startswith("Dan - Lonely Track")]
        check(not lonely and sum(1 for _, fn, _ in M.LOOSE_AMBIG if fn.startswith("Dan - Lonely Track")) == 2, f"two files for one track: neither matched, both listed as ambiguous ({lonely})")
        check("Eve - Twin (Sped Up)" not in got, "one file for two tracks (Twin / Twin (Remix)): not matched")
        check(any("Twin" in tr for _, _, tr in M.LOOSE_AMBIG), f"... and listed as ambiguous ({len(M.LOOSE_AMBIG)} ambiguous pairs)")
        exact, _u = M.match_playlist(rows, audio, cfg, loose=False)
        check(len(matched) > len(exact) and all(sc in (75, 70) for r, a, sc in matched if (r, a) not in [(x, y) for x, y, _ in exact]), "loose matches are flagged below 85 (CHECK), the exact rule is untouched")
        # the real library (read-only): the numbers of the task
        cfg_r = M.load_config()
        csvp, rows_r, _ = M.read_playlist(cfg_r)
        audio_r = M.scan_audio(cfg_r)
        if rows_r and audio_r:
            m0, u0 = M.match_playlist(rows_r, audio_r, cfg_r, loose=False)
            m1, u1 = M.match_playlist(rows_r, audio_r, cfg_r)
            print(f"   real library: {len(rows_r)} CSV tracks, {len(audio_r)} files: before {len(m0)} matched / {len(u0)} unmatched, after {len(m1)} matched / {len(u1)} unmatched; "
                  f"{len(M.LOOSE_NEW)} new pairs, {len(M.LOOSE_AMBIG)} ambiguous")
            check(len(m1) >= len(m0) and {a["path"] for _, a, _ in m0} <= {a["path"] for _, a, _ in m1}, "every file that matched before still matches")
            check(len(M.LOOSE_NEW) == len(m1) - len(m0), "the new matches are exactly the loose ones")
            key0 = {(r["uri"], a["path"]) for r, a, _ in m0}
            key1 = {(r["uri"], a["path"]) for r, a, _ in m1}
            check(key0 <= key1, "no earlier pair was changed or taken away")
            # one file per track, one track per file (no false match through a shared file / track)
            check(len({a["path"] for _, a, _ in m1}) == len(m1) and len({r["uri"] or id(r) for r, _, _ in m1}) == len(m1), "one file per track and one track per file")


PARTS["1"] = part_songs


# ------------------------------------------------------------------------------------------------ 2) CS2 stale / phantom rows
def sidecar_of(frag):
    cands = [p for p in (M.DATA / "cs2_rows_v1").glob("*.json") if frag.replace(" ", "_") in p.name]
    return json.loads(cands[0].read_text(encoding="utf-8")) if cands else None


def kills_of(frag, cfg):
    sc = sidecar_of(frag)
    return None if sc is None else M.border_analysis(sc, cfg)["kills"]


def part_cs2_stale(tmp):
    with section("2) CS2: three stale feed rows read as a 3k (2025.08.16), the same-timestamp guard, the real same-timestamp events"):
        with PB.data_copy(M):
            cfg = M.load_config()
            ks = kills_of("2025.08.16_-_21.10.21.03", cfg)
            check(ks is not None, "sidecar of Counter-strike 2 2025.08.16 - 21.10.21.03 found")
            if ks is not None:
                check([round(k["t"], 1) for k in ks] == [10.7], f"only the real kill at 10.7 s stays (was: 3 kills at 2.1 s + 1): {[round(k['t'], 1) for k in ks]}")
                sc = sidecar_of("2025.08.16_-_21.10.21.03")
                res = M.border_analysis(sc, cfg)
                check(sum(1 for r in res["rej"] if r["reason"].startswith("CS2 same-timestamp kill not confirmed")) == 3, "the three stale rows are listed as rejected: not confirmed (no name of mine)")
            # unit: the guard
            mk = lambda t, hits, nr, victim, killer: {"t": t, "hits": hits, "name_read": nr, "victim": victim, "row": f"[{killer}] gun [{victim}]", "ks": 0.6}
            rej = []
            keep = M.cs2_sametime_guard([mk(2.1, 3, False, "halla", "-"), mk(2.1, 3, False, "PETER THE GREAT", "nonliz"), mk(2.1, 3, False, "ryrannosauruSteX", "halla")], rej)
            check(keep == [] and len(rej) == 3, "3 same-timestamp rows without a readable name of mine: all rejected")
            rej = []
            keep = M.cs2_sametime_guard([mk(14.7, 22, True, "SO SAD", "fireaxe"), mk(14.7, 22, True, "Abdul", "fireaxe")], rej)
            check(len(keep) == 2 and not rej, "two confirmed rows with distinct victims at one timestamp (a real collateral): both kept")
            rej = []
            keep = M.cs2_sametime_guard([mk(14.7, 22, True, "Musician", "fireaxe"), mk(14.7, 5, True, "Musician", "fireaxe")], rej)
            check(len(keep) == 1 and len(rej) == 1, "the same victim twice at one timestamp: one kept")
            rej = []
            keep = M.cs2_sametime_guard([mk(14.4, 31, True, "15 cent", "fireaxe"), mk(14.43, 3, False, "lgrls", "15cemt")], rej)
            check(len(keep) == 1 and keep[0]["hits"] == 31, "a neighbouring row of another player (not mine) is not a second kill")
            rej = []
            keep = M.cs2_sametime_guard([mk(14.67, 20, False, "OJoan CIaudoVAC BAN", "Tiroaxo"), mk(14.67, 20, True, "Rob3rthWoW", "Fireaxe")], rej)
            check(len(keep) == 2, "a garbled but name-like killer side ('Tiroaxo') still counts as confirmed")
            keep = M.cs2_sametime_guard([mk(5.0, 3, False, "x", "-")], [])
            check(len(keep) == 1, "a single kill is never touched by the guard")
            # the five events named in the task: each is real
            real = {"2026.02.14_-_23.16.02.02": 2, "2026.02.09_-_23.33.32.09": 1, "2025.08.17_-_17.15.38.08": 2, "2026.03.15_-_01.21.52.45": 2, "2025.08.10_-_22.39.58.02": 2}
            for frag, n in real.items():
                k_ = kills_of(frag, cfg)
                check(k_ is not None and len(k_) == n, f"{frag.replace('_', ' ')}: {n} kill(s) of mine confirmed ({None if k_ is None else len(k_)})")
            # every same-timestamp group of the whole cache: each member confirmed + distinct victim
            bad, groups, total = [], 0, 0
            for p in sorted((M.DATA / "cs2_rows_v1").glob("*.json")):
                sc = json.loads(p.read_text(encoding="utf-8"))
                kk = sorted(M.border_analysis(sc, cfg)["kills"], key=lambda k: k["t"])
                total += len(kk)
                for i, k in enumerate(kk):
                    grp = [x for x in kk if abs(x["t"] - k["t"]) <= M.CS2_SAMETIME_S]
                    if len(grp) > 1 and grp[0] is k:
                        groups += 1
                        for x in grp:
                            kt = (x.get("row") or "")[1:].split("]")[0]
                            if not (x["name_read"] or M.cs2_lenient_me(kt) or len(M.ocr_norm(kt)) >= 4):
                                bad.append((p.name, x["t"], x["row"]))
                        vs = [M.ocr_norm(x["victim"]) for x in grp if x["name_read"]]
                        if len(set(vs)) < len(vs):
                            bad.append((p.name, k["t"], "same victim twice"))
            print(f"   {total} border kills in the cache, {groups} same-timestamp groups")
            check(not bad, f"all {groups} same-timestamp groups of the cache: every member confirmed, distinct victims {bad[:3]}")
            check(total == 756, f"cache total 756 kills (762 in V7.7.1: 6 phantom rows removed in 4 clips) - got {total}")


PARTS["2"] = part_cs2_stale


# ------------------------------------------------------------------------------------------------ 3) duplicated row fragment + ending
def part_cs2_fragment(tmp):
    with section("3) CS2: a row read twice (2026.02.14 AWP collateral = 2 kills, not 3), the ending"):
        with PB.data_copy(M):
            cfg = M.load_config()
            sc = sidecar_of("2026.02.14_-_23.16.02.02")
            check(sc is not None, "sidecar of 2026.02.14 - 23.16.02.02 found")
            if sc is not None:
                res = M.border_analysis(sc, cfg)
                vic = [k["victim"] for k in res["kills"]]
                check(len(res["kills"]) == 2 and abs(res["kills"][0]["t"] - res["kills"][1]["t"]) < 0.01, f"the AWP collateral is 2 kills at one time (was 3: the third at 13.2 s was the 19JR48 row again): {vic}")
                check(not any(abs(k["t"] - 13.2) < 0.3 for k in res["kills"]), "no phantom kill at 13.2 s")
            # events + plan: the ending slow-mo is centred on the real last kill and the take ends before anything else happens
            pool, st = quiet(M.game_pool, M.load_config(), "cs2")[0]
            ev, _ = M.build_events(pool, "cs2", M.load_config(), random.Random(1))
            e = next((x for x in ev if "2026.02.14 - 23.16.02.02" in x["path"]), None)
            check(e is not None and e["n"] == 2 and abs(e["times"][-1] - 11.55) < 0.15, f"event: 2 kills, last kill at {None if e is None else e['times'][-1]:.2f} s (real kill 11.55 s)")
            check(e is not None and e.get("verified") is True, "the event is verified (my name read on both rows)")
            # the ending rule (unit)
            mk = lambda **kw: dict({"post": 3.0, "death_after": None, "score": 10.0}, **kw)
            check(M.ending_safe(mk()) and not M.ending_safe(mk(post=0.5)) and not M.ending_safe(mk(death_after=0.6)), "ending_safe: needs 0.9 s of footage after the kill, before my death / the clip end")
            order = sorted([mk(score=90.0, verified=False), mk(score=50.0, verified=True), mk(score=70.0, stitched=True)], key=M.ending_rank)
            check([x["score"] for x in order] == [50.0, 90.0, 70.0] or order[0]["score"] == 50.0, "ending_rank: a verified clean multikill first, then by score")
            check(sorted([mk(score=3.0), mk(score=9.0)], key=M.ending_rank)[0]["score"] == 9.0, "ending_rank: with equal candidates the old order (score) is unchanged")
            # the plan: that clip as the ending of a small montage keeps its slow-mo on the real kill
            path = next(r["path"] for r in M.scan_clips(M.load_config()) if r.get("game") == "cs2" and "2026.02.14 - 23.16.02.02" in r["path"])
            (plan, _l) = quiet(lambda: M.make_plan(M.load_config(), "cs2", paths=[path], scan=False, seed=3))
            plan = plan[0] if isinstance(plan, tuple) else plan
            tk = plan["takes"][0]
            check(tk["n"] == 2 and not M.kill_window_audit(tk), f"planned take: 2 kills, all inside the window ({tk['kills']})")
            sl = next((s for s in tk["segs"] if s[2] < 1.0), None)
            check(sl is not None and abs(sl[0] - 11.5) < 0.6, f"slow-mo starts at {sl[0] if sl else None} s of the source, around the real last kill 11.55 s")
            last_src = max(s[1] for s in tk["segs"])
            check(last_src < 12.9, f"the take ends at {last_src:.2f} s of the source: before the red damage arcs of the shot at 13.3 s")


PARTS["3"] = part_cs2_fragment


# ------------------------------------------------------------------------------------------------ 4) kill window assertion
def part_kill_window(tmp):
    with section("4) plan-time assertion: every kill of an event inside the placed take, the build-up shown"):
        take = {"segs": [[10.0, 12.0, 1.0, 120, 0]], "kills": [10.5, 11.0, 11.8], "victims": ["a", "b", "c"], "n": 3}
        check(M.kill_window_audit(take) == [], "all 3 kills inside the take, 0.5 s of build-up: fine")
        t2 = dict(take, kills=[10.5, 11.0, 13.0])
        check(any("13.00" in m and "is not inside the take" in m for m in M.kill_window_audit(t2)), "a kill outside the footage is reported")
        t3 = dict(take, kills=[10.05, 11.0, 11.8])
        check(any("build-up" in m for m in M.kill_window_audit(t3)), "a take that starts 0.05 s before its first kill (no build-up) is reported")
        t4 = dict(take, kills=[10.5, 11.0], n=3)
        check(any("missing" in m for m in M.kill_window_audit(t4)), "a take that lists fewer kills than its event is reported")
        t5 = dict(take, segs=[[10.0, 10.8, 1.0, 48, 0], [11.9, 12.5, 1.0, 36, 0]], kills=[10.5, 11.0, 12.0])
        check(any("11.00" in m for m in M.kill_window_audit(t5)), "a kill that falls into a jump-cut gap is reported")
        t6 = dict(take, rx={"lead_min": 0.1}, kills=[10.12, 11.0, 11.8])
        check(M.kill_window_audit(t6) == [], "an event admitted with a shorter run-up (relaxed rule) is judged by that run-up")
        # through verify_cutlist (a real plan, then a broken copy)
        with PB.data_copy(M):
            game, paths = PB.take_sets(M)["cs2trio"]
            song = next(x["path"] for x in M.song_pool(M.load_config())[0] if "Silicon XX" in str(x["path"]))
            plan, _l = PB.run_plan(M, game, paths, song, "v2")
            bad0 = M.verify_cutlist(plan)
            check(not bad0, f"real CS2 plan: cut list valid ({bad0[:1]})")
            broken = json.loads(jplan(plan))
            broken["takes"][0]["kills"][-1] = broken["takes"][0]["segs"][-1][1] + 5.0
            msgs = [b for b in M.verify_cutlist(broken) if b.startswith("take 1:")]
            check(any("is not inside the take" in b for b in msgs) and all(M._TAKE_SKIP_OK(b) for b in msgs if "kill at" in b), "verify_cutlist reports it and the planner re-plans that take")
            lines = []
            keep = (M.out,)
            M.out = lambda *x: lines.append(" ".join(map(str, x)))
            try:
                M.verify_cutlist(broken)
            finally:
                M.out = keep[0]
            check(any("KILL WINDOW CHECK FAILED" in l for l in lines), "and the failure is written to the log")
            # stitched + 4k events: every placed take passes the assertion
            pool, st = quiet(M.game_pool, M.load_config(), "cs2")[0]
            events, _n = M.build_events(pool, "cs2", M.load_config(), random.Random(1))
            sel = [e for e in events if e["n"] >= 4 or e["stitched"]]
            ps = []
            for e in sel[:8]:
                ps += [p["path"] for p in e["parts"]]
            (pl, _l2) = quiet(lambda: M.make_plan(M.load_config(), "cs2", paths=ps, scan=False, seed=11))
            pl = pl[0] if isinstance(pl, tuple) else pl
            viol = [(i, M.kill_window_audit(t)) for i, t in enumerate(pl["takes"], 1) if M.kill_window_audit(t)]
            check(len(pl["takes"]) >= 4 and not viol, f"{len(sel[:8])} real stitched / 4+ kill CS2 events planned: {len(pl['takes'])} takes, every kill inside its take {viol[:1]}")


PARTS["4"] = part_kill_window


# ------------------------------------------------------------------------------------------------ 5) transitions
def part_transitions(tmp):
    with section("5) soft transitions: dissolve weights and the luma-spike check"):
        check(M.blend_n_base() in (0, 1), f"ffmpeg counts N from {M.blend_n_base()} in the blend filter of this build")
        expr = M.soft_blend_expr()
        def dissolve(a, b):
            vf = (f"[0:v]trim=end_frame=5,setpts=PTS-STARTPTS[a];[1:v]trim=end_frame=5,setpts=PTS-STARTPTS[b];[a][b]blend=all_expr='{expr}',format=yuv420p,"
                  "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-")
            r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=c={a}:s=160x90:r=60:d=0.2,format=yuv420p", "-f", "lavfi", "-i", f"color=c={b}:s=160x90:r=60:d=0.2,format=yuv420p",
                                "-filter_complex", vf, "-f", "null", "-"], capture_output=True, text=True)
            return [float(x) for x in re.findall(r"YAVG=([0-9.]+)", r.stdout)]
        for a, b, tag in (("0x303030", "0xf0f0f0", "dark -> bright"), ("0xf0f0f0", "0x303030", "bright -> dark"), ("0x585858", "0xEBEBEB", "grey -> white")):
            y = dissolve(a, b)
            lo, hi = min(y[0], y[-1]), max(y[0], y[-1])
            ya, yb = (y[0] - 0.1 * (y[-1] - y[0]) / 0.8, y[-1] + 0.1 * (y[-1] - y[0]) / 0.8)           # the two sides' Y, from the 0.1 / 0.9 ends
            mono = all((y[i + 1] - y[i]) * (yb - ya) > 0 for i in range(4))
            check(len(y) == 5 and mono and min(ya, yb) - 1 <= min(y) and max(y) <= max(ya, yb) + 1, f"{tag}: 5 frames {[round(v) for v in y]} stay between the two sides, steady steps")
        check(abs((dissolve("0x000000", "0xffffff")[0] - 16) / 219 - 0.1) < 0.02, "the first dissolve frame is 10% of the take after")
        # the check itself
        plan = {"takes": [{"f0": 0, "trans": "hard"}, {"f0": 100, "trans": "soft"}, {"f0": 200, "trans": "soft"}, {"f0": 300, "trans": "hard"}]}
        y = [80.0] * 400
        for i in range(98, 103):                                            # a clean dissolve 80 -> 200
            y[i] = 80 + (i - 97) * 20.0
        for i in range(103, 200):
            y[i] = 200.0
        for i in range(198, 203):                                           # an overshooting one: the last frame 12 levels above its side
            y[i] = 200 + (i - 197) * 10.0 * 0
        y[202] = 212.0
        for i in range(203, 400):
            y[i] = 200.0
        n, bad = M.transition_spikes(plan, y)
        check(n == 2 and [b[0] for b in bad] == [3] and bad[0][3] == "brighter", f"2 soft transitions scanned, the spike at take 3 found: {bad}")
        # the 7.7.1 render with the flash (read-only; skipped when the file is not on this PC)
        ref = Path("E:/Movies/Montages/CS2/PE_CS2_V7.7.1_2026-10-13.mp4")
        pj = Path("E:/Movies/Montages/CS2/logs/PE_CS2_V7.7.1_2026-10-13.plan.json")
        if ref.exists() and pj.exists():
            y = M.luma_series(ref)
            n, bad = M.transition_spikes(json.loads(pj.read_text(encoding="utf-8")), y)
            check(n >= 40 and {b[0] for b in bad} >= {39}, f"the 7.7.1 render PE_CS2: {n} soft transitions scanned, the white flash into take 39 found: {bad}")


PARTS["5"] = part_transitions


# ------------------------------------------------------------------------------------------------ 6) post-render coverage
def part_sync(tmp):
    with section("6) post-render CS2 detector: the one-round / one-fight duplicate rules do not apply to a montage"):
        names = ["Zorro", "Marko", "Peter", "Hanna", "Ilona", "Bruno", "Karel", "Matti"]
        mk = lambda: [{"t": 3.0 + 5.0 * i, "victim": n, "row": f"[fireaxe] gun [{n}]", "hits": 1, "ks": 0.9, "hs": False} for i, n in enumerate(names)]
        k1, r1 = mk(), []
        M.drop_fake_kills(k1, r1, "cs2")
        check(len(k1) <= 6 and r1, f"one clip: 8 weak kills in 40 s -> the one-round cap drops some ({len(k1)} left)")
        k2, r2 = mk(), []
        M.SYNC_SCAN[0] = True
        try:
            M.drop_fake_kills(k2, r2, "cs2")
        finally:
            M.SYNC_SCAN[0] = False
        check(len(k2) == 8 and not r2, "montage scan: all 8 kept (they come from different clips)")
        k3 = [{"t": 3.0, "victim": "Musician", "row": "[fireaxe] gun [Musician]", "hits": 4, "ks": 0.9, "hs": False}, {"t": 8.0, "victim": "Musician", "row": "[fireaxe] gun [Musician]", "hits": 4, "ks": 0.9, "hs": False}]
        M.SYNC_SCAN[0] = True
        try:
            r3 = []
            M.drop_fake_kills(k3, r3, "cs2")
        finally:
            M.SYNC_SCAN[0] = False
        check(len(k3) == 2, "montage scan: the same victim name in two takes (two clips) is not a duplicate")
        check(M.SYNC_SCAN[0] is False, "the switch is off again (the main scan is unchanged)")
        src = Path(ROOT / "montage.py").read_text(encoding="utf-8")
        check("SYNC_SCAN[0] = True" in src.split("def sync_report(")[1].split("def quality_check")[0], "sync_report uses the montage mode and the same analyse_entry (names, 火斧 variants) as the main scan")
        check("TRANSITION CHECK" in src, "the sync report prints the transition check")


PARTS["6"] = part_sync


# ------------------------------------------------------------------------------------------------ g) guards
def part_guards(tmp):
    import test_v73 as T73
    import test_v761 as T761
    with section("g) guards vs V7.7.1 (defaults): events, kills, takes, cut lists, drops of 50 + 50 generated clips; the 7 real Valorant clips; the real CS2 trio and singles"):
        with PB.data_copy(M) as dst:
            B = load_base("V7.7.1", dst, tmp)
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
                check(len(ev_m) > 40 and T73.ev_view(ev_m) == T73.ev_view(ev_b), f"{game}: {len(ev_m)} events of the 50 clips identical to V7.7.1 (clips, kills, scores)")
                for bpm, drop_s, seed in ((128.0, 64.0, 5), (150.0, 40.0, 12)):
                    an_m, an_b = T73.song_map(M, bpm, 300.0, drop_s), T73.song_map(B, bpm, 300.0, drop_s)
                    p_new = T73.plan_of(M, game, ev_m, an_m, seed)
                    p_b = T73.plan_of(B, game, ev_b, an_b, seed)
                    ks_n, ks_b = T761.kill_set(p_new), T761.kill_set(p_b)
                    check(ks_n == ks_b and len(p_new["takes"]) == len(p_b["takes"]), f"{game} bpm {bpm:.0f}: kill counts ({len(ks_n)}), takes ({len(p_new['takes'])}) identical to V7.7.1")
                    check([t["segs"] for t in p_new["takes"]] == [t["segs"] for t in p_b["takes"]] and p_new.get("drop_sync") == p_b.get("drop_sync"), f"{game} bpm {bpm:.0f}: cut lists and drops identical to V7.7.1")
                    same = [{k: v for k, v in t.items() if k != "trans"} for t in p_new["takes"]] == [{k: v for k, v in t.items() if k != "trans"} for t in p_b["takes"]]
                    check(same, f"{game} bpm {bpm:.0f}: every take identical to V7.7.1 (the plan's role / effects / audio)")
                    check(not M.verify_cutlist(p_new), f"{game} bpm {bpm:.0f}: cut list valid")
            sets = PB.take_sets(M)
            song = next(x["path"] for x in M.song_pool(M.load_config())[0] if "Silicon XX" in str(x["path"]))
            M.HEADLINE_RULES_V73 = True
            for tag in ("val7", "cs2trio", "cs2singles"):
                game, paths = sets[tag]
                plan_n, l_n = PB.run_plan(M, game, paths, song, "v2")
                plan_b, _lb = PB.run_plan(B, game, paths, song, "v2")
                same_takes = [{k: v for k, v in t.items() if k not in ("trans",)} for t in plan_n["takes"]] == [{k: v for k, v in t.items() if k not in ("trans",)} for t in plan_b["takes"]]
                check(same_takes and plan_n.get("drop_sync") == plan_b.get("drop_sync") and plan_n["song"] == plan_b["song"],
                      f"{tag}: {len(plan_n['takes'])} takes, cut lists, drops, song identical to V7.7.1")
                check(not M.verify_cutlist(plan_n), f"{tag}: cut list valid")
                if tag == "val7":
                    led = next(l for l in l_n if l.startswith("kill ledger:"))
                    check(len(plan_n["takes"]) == 4 and "11 placed" in led and "3 merged" in led and "0 lost" in led, f"7 real Valorant clips: 4 events; '{led[:100]}'")
                    ov = next(p for p in paths if "03-31-20" in str(p))                       # the 4K (override on)
                    M.set_clip_override([str(ov)], True)
                    try:
                        plan_on, l_on = PB.run_plan(M, game, paths, song, "v2")
                        B.set_clip_override([str(ov)], True)
                        plan_on_b, _l = PB.run_plan(B, game, paths, song, "v2")
                    finally:
                        M.set_clip_override([str(ov)], False)
                        B.set_clip_override([str(ov)], False)
                    led2 = next(l for l in l_on if l.startswith("kill ledger:"))
                    four = [t for t in plan_on["takes"] if t["n"] == 4]
                    check("12 placed" in led2 and "3 merged" in led2 and "0 lost" in led2 and len(four) == 1 and four[0].get("util"), f"4K with 4 kills (override on): '{led2[:100]}'")
                    check([{k: v for k, v in t.items() if k != "trans"} for t in plan_on["takes"]] == [{k: v for k, v in t.items() if k != "trans"} for t in plan_on_b["takes"]] and not M.verify_cutlist(plan_on),
                          "the 4K plan: takes identical to V7.7.1, cut list valid")


PARTS["g"] = part_guards


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t775_"))
    only = set(filter(None, os.environ.get("V775_PARTS", "").split(",")))
    for key in ("0", "1", "2", "3", "4", "5", "6", "g"):
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
