"""V7.7.0 tests. Sections (each prints ok / FAIL lines, the last line is ALL OK only when every check ran and passed):
  0) changelog: every real version (APP_VERSION bump in the git history) has an entry in both changelogs, the Settings viewer shows everything
  1) drop placement: a max-tail violation is repaired before a take is skipped, a skipped take is listed with its rule, ledger = cut list, header from the final plan,
     drop anchors refined to the audible onset
  2) the same fight saved twice is merged (never different fights)
  3) song length column + date-added sort in the Songs and Manual tabs
  4) music over gameplay detector (synthetic clips) and its OFF = byte-identical contract
  g) guards: 50 + 50 generated clips vs V7.6.1, the 7 real Valorant clips (4 / 11 / 3 / 0), the 4K
Runs on a COPY of montage_data (V7_DATA_SRC picks the folder; the real folder is only read).   python tests\\test_v770.py   (parts: V770_PARTS=0,1,2,3,4,g)"""
import os
import datetime
import json
import re
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


# ------------------------------------------------------------------------------------------------ 0) changelog
def part_changelog():
    with section("0) changelogs: every real version has an entry, both files agree, the Settings viewer shows everything"):
        simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
        tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        hs = re.findall(r"(?m)^## (.+)$", simple)
        ht = re.findall(r"(?m)^## (.+)$", tech)
        key = lambda h: re.match(r"(V[\d.]+[AB]?|Megafix|First|Stage|Initial)", h).group(1)
        ks, kt = [key(h) for h in hs], [key(h) for h in ht]
        check(ks == kt, "same versions in the same order in both files" + ("" if ks == kt else f" (differ at {[(a, b) for a, b in zip(ks, kt) if a != b][:3]})"))
        check(len(set(ks)) == len(ks), "no version twice")
        r = subprocess.run(["git", "log", "--all", "--format=%h", "-G", r"^APP_VERSION = ", "--", "montage.py"], cwd=ROOT, capture_output=True, text=True)
        revs = r.stdout.split()
        if not revs:
            check(True, "no git history here: the version bumps could not be listed (skipped)")
        else:
            bumps = set()
            for rv in revs:
                p = subprocess.run(["git", "show", f"{rv}:montage.py"], cwd=ROOT, capture_output=True)
                m = re.search(rb'(?m)^APP_VERSION = "([^"]+)"', p.stdout)
                if m:
                    bumps.add(m.group(1).decode())
            miss = sorted(v for v in bumps if v not in ks)
            check(not miss, f"all {len(bumps)} version bumps of the git history have an entry in both changelogs" + (f" (missing {miss})" if miss else ""))
        tags = subprocess.run(["git", "tag"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        vt = {re.sub(r"-good$", "", t).upper() for t in tags if re.match(r"(?i)v\d", t)}
        ksu = {k.upper() for k in ks}
        miss_t = sorted(v for v in vt if v not in ksu)
        check(not miss_t, f"every version tag ({len(vt)}) has an entry" + (f" (missing {miss_t})" if miss_t else ""))
        never = ("V5.45", "V5.50", "V5.54", "V6.3", "V6.4")
        check(not any(k in ksu for k in never), "versions that never existed (V5.45-V5.54, V6.3, V6.4) have no entry")
        bad = re.search(r"KNOWN ISSUE|ABANDON|ON HOLD|on hold", simple)
        check(not bad, "no KNOWN ISSUE / ABANDONED / on-hold text in the readable history")
        for h, blk in zip(hs, re.split(r"(?m)^## .+$", simple)[1:]):
            n = len([x for x in blk.splitlines() if x.startswith("- ")])
            if n < 1 or n > 5:
                check(False, f"{h}: {n} points (1 to 5 expected)")
        for p in (None, M.CHANGELOG_PATH):
            L = M.changelog_lines(p)
            n_ver = sum(1 for k, _ in L if k == "ver")
            check(n_ver == len(hs), f"Settings viewer shows the full history ({'readable' if p is None else 'technical'} file: {n_ver} versions)")
        try:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            root.destroy()
            gui = True
        except Exception:
            gui = False
        if gui:
            app = M.App(0)
            try:
                app.show_changelog()
                app.root.update()
                txt = app.cl_text.get("1.0", "end")
                first_ver, last_ver = hs[0], hs[-1]
                n_exp, n_txt = len(M.changelog_lines()), len(txt.strip().splitlines())
                check(first_ver in txt and last_ver in txt and n_txt == n_exp, f"the changelog window opens and holds the whole text ({n_txt} of {n_exp} lines, first and last entry present)")
            finally:
                try:
                    app.root.destroy()
                except Exception:
                    pass
        else:
            print("   (no display: the changelog window itself was not opened here)")


# ------------------------------------------------------------------------------------------------ 1) drop placement
import test_v73 as T73                                                                        # noqa: E402
import test_v760 as T760                                                                      # noqa: E402
import test_v761 as T761                                                                      # noqa: E402
import test_v693 as T693                                                                      # noqa: E402


def kill_times_of(plan):
    return [round(M.impact_time(plan, i, j), 4) for i, t in enumerate(plan["takes"]) for j in range(len(t["kills"]))]


def synth_song(path, impacts, dur=300.0, sr=44100, bed=0.002):
    """A wav with a quiet bed and a hit (60 Hz thump + noise burst, 5 ms attack) of the given strength at each (time, gain)."""
    import numpy as np
    import wave
    n = int(dur * sr)
    rng = np.random.default_rng(3)
    y = bed * rng.standard_normal(n)
    for tt, g in impacts:
        i0 = int(tt * sr)
        m = int(0.5 * sr)
        k = np.arange(m) / sr
        env = np.minimum(1.0, k / 0.005) * np.exp(-k / 0.12)
        hit = g * env * (np.sin(2 * np.pi * 60 * k) + 0.5 * rng.standard_normal(m))
        y[i0:i0 + m] += hit[:max(0, min(m, n - i0))]
    y = np.clip(y, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype("<i2").tobytes())
    return str(path)


def lengthen_tail(q, idx, frames):
    """Test setup: take idx ends `frames` later and the take after starts `frames` later (its run-up shorter): the tail of take idx grows, nothing else moves."""
    r = M.flex_tail(q["takes"][idx], frames, 60) or M.flex_lead(q["takes"][idx + 1], -frames, 60)
    M._relayout(q["takes"], 60)
    return r


def part_drop_placement(tmp):
    import copy
    with section("1a) tail repair: a take over the max tail is repaired (tail cut, the next take's run-up grows), no kill moves, nothing is skipped"):
        M.OUTRO_TRIM_ON[0] = False
        ev = T760.pool(tmp, "valorant", n=16, seed=23)
        an = T760.drops_map(2)
        pl = T73.plan_of(M, "valorant", ev, an, 5, style="hype")
        check(not M.verify_cutlist(pl), "base plan: cut list valid")
        idx = next(i for i, t in enumerate(pl["takes"][:-2]) if not t.get("ending") and not t.get("slow") and t["role"] != "headline")
        tail0, lo0, hi0 = M.take_tail_bounds(pl["takes"][idx])
        for extra in (3, 5, 9):
            q = copy.deepcopy(pl)
            fr = int(round((hi0 - tail0) * 60)) + extra
            r = lengthen_tail(q, idx, fr)
            check(not r, f"test setup: take {idx + 1} tail {tail0:.2f} s -> {M.take_tail_bounds(q['takes'][idx])[0]:.2f} s (max {hi0:.2f}) {r or ''}")
            bad0 = [b for b in M.verify_cutlist(q) if "tail" in b]
            check(bool(bad0), f"over the max tail by about {extra} frames: the cut-list check flags it ({bad0[:1]})")
            k0 = kill_times_of(q)
            lines = M.repair_tails(q, [])
            check(any(l.startswith("tail repaired") for l in lines) and not [b for b in M.verify_cutlist(q) if "tail" in b], f"repaired: {lines[:1]}")
            check(kill_times_of(q) == k0, "every kill of every take is on exactly the same time as before the repair")
            check(q["total_frames"] == pl["total_frames"] and len(q["takes"]) == len(pl["takes"]) and not M.verify_cutlist(q), "length, take count and the whole cut list unchanged / valid")
        q = copy.deepcopy(pl)
        lengthen_tail(q, idx, 40)
        lines = M.repair_tails(q, [])
        check(any("NOT repairable" in l for l in lines), f"a tail 40 frames too long has no repair: it says so ({lines[:1]})")
    with section("1b) the planner aims for the tail window the check allows (slow-mo headline, kill rows 0.1 - 0.9 s after the shot)"):
        an = T760.drops_map(1)
        for lag in (0.10, 0.30, 0.45, 0.60, 0.75, 0.90):
            evs = T761.ev_with(tmp, "valorant", f"lag{int(lag * 100)}", [4.0, 5.2, 6.4, 7.6, 8.8, 10.0], rows_lag=lag, dur=22.0)
            filler = T760.pool(tmp, "valorant", n=12, seed=31)
            pl = T73.plan_of(M, "valorant", evs + filler, an, 7, style="hype")
            nm = Path(evs[0]["path"]).name
            tk = [t for t in pl["takes"] if t["path"] == evs[0]["path"]]
            tails = [b for b in M.verify_cutlist(pl) if "tail" in b]
            check(bool(tk) and not tails and not M.verify_cutlist(pl), f"kill row {lag:.2f} s after the shot: the 4k is placed, no tail problem" + (f" ({tk[0]['role']}{' slow-mo' if tk[0].get('slow') else ''}, tail {M.take_tail_bounds(tk[0])[0]:.2f} s)" if tk else ""))
        gaps = {g: round(M.slow_out_gap(g), 3) for g in (0.1, 0.2, 0.4, 0.58, 0.9)}
        check(abs(gaps[0.1] - 0.2) < 1e-6 and 0.85 < gaps[0.58] < 0.95 and gaps[0.9] > gaps[0.58] > gaps[0.4], f"slow_out_gap follows the real speed curve (not a flat 0.5x): {gaps}")
    with section("1d) anchor on the audible onset: a stored drop >40 ms from the strongest onset within +-0.5 s is refined (anchor only), closer / weaker ones are not"):
        wav = synth_song(tmp / "onset.wav", [(60.000, 0.6), (60.250, 0.25), (120.050, 0.6), (180.000, 0.04)], bed=0.03)
        y, sr = M.decode_mono(wav, 44100)
        on, db = M.drop_onset_near(y, sr, 60.12)
        check(on is not None and abs(on - 60.000) < 0.012 and db > 15, f"strongest onset near 60.12 s: {on:.3f} s ({db:.0f} dB) - the 0.6 hit at 60.000, not the weaker one at 60.250")
        on2, db2 = M.drop_onset_near(y, sr, 120.07)
        check(on2 is not None and abs(on2 - 120.050) < 0.012, f"onset within 20 ms of the stored time found at {on2:.3f} s")
        on3, db3 = M.drop_onset_near(y, sr, 150.0)
        check(on3 is None, "no onset within +-0.5 s of a stretch of silence: nothing found")
        M._ONSET_MEMO.clear()
        new, lines = M.refine_drop_anchors(wav, [(60.12, 1.0, "map"), (120.07, 1.0, "map"), (150.0, 1.0, "map"), (180.2, 1.0, "map")])
        check(abs(new[0][0] - 60.000) < 0.012 and lines and lines[0].startswith("anchor refined: 60.120 -> 60.0"), f"60.120 refined to {new[0][0]:.3f}: '{lines[0][:60] if lines else ''}'")
        check(new[1][0] == 120.07 and new[2][0] == 150.0 and new[3][0] == 180.2 and len(lines) == 1, "20 ms away / no onset / a weak hit: kept exactly as stored")
        M.OUTRO_TRIM_ON[0] = False
        M._ONSET_MEMO.clear()
        ev = T760.pool(tmp, "valorant", n=24, seed=11)
        an = T760.drops_map(1, off=0.0)
        d_t = an["drops"][0]["t"]
        wav2 = synth_song(tmp / "onset2.wav", [(d_t - 0.13, 0.6)])
        an0 = copy.deepcopy(an)
        keep, _ = T73.quiet(M)
        try:
            pl = M.plan_montage(M.load_config(), "valorant", [dict(e) for e in ev], {"path": wav2, "title": "x", "artist": "a"}, an, 5, "hype", "optimal", [], [])
        finally:
            T73.unquiet(M, keep)
        got = [x for x in (pl.get("drop_sync") or []) if x["take"]]
        check(any(n.startswith("anchor refined: ") for n in pl["notes"]), "the plan logs 'anchor refined: <stored> -> <onset>'")
        check(bool(got) and abs(got[0]["drop"] - (d_t - 0.13)) < 0.015 and abs(got[0]["err_ms"]) <= 30, f"the kill is anchored on the onset {d_t - 0.13:.3f} (anchor {got[0]['drop'] if got else None}, error {got[0]['err_ms'] if got else None} ms)")
        check(an == an0, "the stored drop map (song analysis) was not changed")
        M.OUTRO_TRIM_ON[0] = True


def part_drop_real(tmp):
    with section("1c) re-plan after a skipped take: NOT PLACED with the exact rule, summary / ledger / header agree with the final cut list (7 real Valorant clips)"):
        game, paths = PB.take_sets(M)["val7"]
        song = next(x["path"] for x in M.song_pool(M.load_config())[0] if "Silicon XX" in str(x["path"]))
        plan0, _l0 = PB.run_plan(M, game, paths, song, "v2")
        victim = next(t["path"] for t in plan0["takes"] if t["role"] != "headline" and not t.get("util") and not t.get("ending"))
        orig_v = M.verify_cutlist

        def forced(plan):
            bad = list(orig_v(plan))
            for i, t in enumerate(plan["takes"], 1):
                if t["path"] == str(victim):
                    bad.append(f"take {i}: tail 9.99 s after the last kill (max 1.59)")
            return bad
        M.verify_cutlist = forced
        try:
            plan, lines = PB.run_plan(M, game, paths, song, "v2")
        finally:
            M.verify_cutlist = orig_v
        nm = Path(victim).name
        note = next((n for n in plan["notes"] if n.startswith("NOT PLACED " + nm)), "")
        check("tail 9.99 s after the last kill (max 1.59)" in note, f"the skipped clip is listed: '{note[:120]}'")
        check(any(a == nm for a, _b in plan["fit"]["unplaced"]) and nm in M.plan_summary_text(plan, len(paths)), "the plan summary lists it too")
        check(all(t["path"] != str(victim) for t in plan["takes"]) and not M.verify_cutlist(plan), "it is not in the cut list, which is valid")
        led = next(l for l in lines if l.startswith("kill ledger:"))
        n_pl = sum(len(t["kills"]) for t in plan["takes"])
        m = re.search(r"(\d+) placed", led)
        check(m and int(m.group(1)) == n_pl and not any(l.startswith("LEDGER CHECK") for l in lines), f"ledger '{led[:70]}' = the cut list ({n_pl} kills)")
        ok, txt, dt = M.headline_report(plan)
        hl = M.fmt_plan(plan, [], None, [], [], "")
        check(txt in hl, "the TIMELINE header is generated from the final plan: " + txt[:90])
        check((not ok) or any(x.get("take") is not None and abs(x["err_ms"]) <= 30 for x in plan["drop_sync"]), "'on the drop' only when a kill really sits on a drop")


def part_guards(tmp):
    import random
    import test_v693 as T693
    with section("guards: 50 + 50 generated clips vs V7.6.1 (events, kills never lower, no repeated clip), the 7 real Valorant clips, the 4K, real data untouched"):
        B = T693.load_baseline(tmp, "V7.6.1")
        check(B is not None, "main (V7.6.1) planner loaded")
        B.use_data_dir(tmp / "base_data2")
        moved = []
        for game in ("valorant", "cs2"):
            ents = T693.gen_entries(50, game)
            view = lambda mod, e, g=game: json.dumps(mod.analyse_entry(e, {}, g), sort_keys=True, default=str)
            nd = sum(view(M, e) != view(B, e) for e in ents)
            check(nd == 0, f"{game}: kills / timestamps / deaths / revives of 50 generated clips identical to main ({nd} differences)")
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
            check(len(ev_m) > 40 and T73.ev_view(ev_m) == T73.ev_view(ev_b), f"{game}: {len(ev_m)} events of the 50 clips identical to main (clips, kills, scores)")
            for bpm, drop_s, seed in ((128.0, 64.0, 5), (150.0, 40.0, 12)):
                an_m, an_b = T73.song_map(M, bpm, 300.0, drop_s), T73.song_map(B, bpm, 300.0, drop_s)
                p_new = T73.plan_of(M, game, ev_m, an_m, seed)
                p_b = T73.plan_of(B, game, ev_b, an_b, seed)
                ks_n, ks_b = T761.kill_set(p_new), T761.kill_set(p_b)
                check(ks_b <= ks_n and len(ks_n) >= len(ks_b), f"{game} bpm {bpm:.0f}: every kill of main is still in a take ({len(ks_b)} -> {len(ks_n)} kills)")
                check(not M.verify_cutlist(p_new), f"{game} bpm {bpm:.0f}: cut list valid, no clip used twice")
                moved.append((game, bpm, len({t['path'] for t in p_new['takes']} ^ {t['path'] for t in p_b['takes']}), len(p_new["takes"]) - len(p_b["takes"])))
        print("   takes that differ from main (game, bpm, clips differing, take count change):", moved)


def part_guards_real(tmp):
    with section("guards: the 7 real Valorant clips (4 events / 11 placed / 3 merged / 0 lost), the 4K with 4 kills"):
        game, paths = PB.take_sets(M)["val7"]
        song = next(x["path"] for x in M.song_pool(M.load_config())[0] if "Silicon XX" in str(x["path"]))
        M.HEADLINE_RULES_V73 = True
        plan_off, l_off = PB.run_plan(M, game, paths, song, "v2")
        led = next(l for l in l_off if l.startswith("kill ledger:"))
        check(len(plan_off["takes"]) == 4 and "11 placed" in led and "3 merged" in led and "0 lost" in led, f"7 real Valorant clips, override off: 4 events; '{led[:100]}'")
        ov = next(p for p in paths if "03-31-20" in str(p))
        M.set_clip_override([str(ov)], True)
        try:
            plan_on, l_on = PB.run_plan(M, game, paths, song, "v2")
        finally:
            M.set_clip_override([str(ov)], False)
        led2 = next(l for l in l_on if l.startswith("kill ledger:"))
        four = [t for t in plan_on["takes"] if t["n"] == 4]
        check("12 placed" in led2 and "3 merged" in led2 and "0 lost" in led2 and len(four) == 1 and four[0].get("util"), f"4K with 4 kills (override on): '{led2[:100]}'")
        check(not M.verify_cutlist(plan_off) and not M.verify_cutlist(plan_on), "both plans: cut list valid")


# ------------------------------------------------------------------------------------------------ 2) same fight saved twice
def fake_item(name, kills, dur=15.4, anc=None, game="cs2"):
    rec = {"path": "E:/x/" + name, "dur": dur, "game": game}
    return {"rec": rec, "kills": [{"t": t, "victim": v} for t, v in kills], "anc": anc}


def part_same_fight():
    with section("2a) the same fight saved twice: the rule (name suffix / equal kills, same victims, same time) and what must NEVER merge"):
        K3 = [(11.0, "Markusko"), (13.8, "chararacing"), (15.0, "Wolfgang")]
        anc = lambda s: {"start": s, "end": s + 15.4, "provable": True}
        a = fake_item("Counter-strike 2 2025.02.08 - 19.48.57.15.DVR.mp4", K3, 15.446)
        b = fake_item("Counter-strike 2 2025.02.08 - 19.48.57.15.DVR_1.mp4", [(t + 0.07, v) for t, v in K3], 15.45)
        check(M.clip_name_base(a["rec"]["path"]) == M.clip_name_base(b["rec"]["path"]) == M.clip_name_base("x/Counter-strike 2 2025.02.08 - 19.48.57.15.DVR_1_1.mp4"), "'_1' and '_1_1' suffixes are stripped from the name")
        r, _w = M.same_fight_pair(a, b, "cs2")
        check(bool(r), f"name differs by _1 and the 3 kills are within 0.3 s: same fight ({r})")
        d = M.find_duplicate_clips([a, b], "cs2")
        check(len(d) == 1 and d[0][0] is b and d[0][1] is a, "one copy stays: the one with more footage (15.45 s vs 15.446 s), the other is dropped")
        c = fake_item("Counter-strike 2 2025.02.08 - 19.48.57.15.DVR_1_1.mp4", K3[:2], 15.45)
        d = M.find_duplicate_clips([a, b, c], "cs2")
        check(len(d) == 2 and {x[1]["rec"]["path"] for x in d} == {a["rec"]["path"], c["rec"]["path"]} and all(x[0] is b for x in d), "three saves of the fight (_1_1 has 2 of 3 kills): exactly one stays, the one with all 3 kills")
        e = fake_item("Counter-strike 2 2025.02.08 - 19.48.57.15.DVR_2.mp4", [(11.0, "Zed"), (13.8, "Quill"), (15.0, "Bram")], 15.4)
        check(not M.same_fight_pair(a, e, "cs2")[0], "same name stem + same times but DIFFERENT victims: not merged")
        e2 = fake_item("Counter-strike 2 2025.02.08 - 19.48.57.15.DVR_3.mp4", [(t + 0.6, v) for t, v in K3], 15.4)
        check(not M.same_fight_pair(a, e2, "cs2")[0], "same name stem + same victims but kill times 0.6 s apart: not merged")
        e3 = fake_item("Counter-strike 2 2025.02.08 - 19.48.57.15.DVR_4.mp4", [(t + 0.31, v) for t, v in K3], 15.4)
        check(not M.same_fight_pair(a, e3, "cs2")[0], "0.31 s apart: not merged (the limit is 0.3 s)")
        f1 = fake_item("Replay 2026-07-19 20-31-37.mov", [(17.37, "Oparlsh")], 18.3, anc(1000.0))
        f2 = fake_item("Replay 2026-07-19 20-31-38.mov", [(17.4, "Oparlsh")], 19.4, anc(1001.0))
        r, _w = M.same_fight_pair(f1, f2, "cs2")
        check(bool(r), f"different names, one kill each, same victim, same time, saved a second apart: same fight ({r[:60]})")
        g1 = fake_item("Valorant 2025.10.15 - 23.05.50.14.DVR.mp4", [(14.4, "Killjoy")], 15.4, anc(50000.0), "valorant")
        g2 = fake_item("Valorant 2025.11.04 - 15.36.13.02.DVR.mp4", [(14.4, "Killjoy")], 15.4, anc(9000000.0), "valorant")
        r, w = M.same_fight_pair(g1, g2, "valorant")
        check(not r and "different times" in w, f"same agent, same clip time, a different match (weeks apart): NOT merged ({w})")
        g3 = fake_item("Valorant 2025.10.15 - 23.05.51.15.DVR.mp4", [(14.4, "Killjoy")], 15.4, None, "valorant")
        check(not M.same_fight_pair(g1, g3, "valorant")[0], "no saved time known: two unrelated names never merge")
        h1 = fake_item("Replay 2026-03-19 20-55-01.mov", [(7.5, "Fucku"), (20.2, "2orro")], 22.2, anc(2000.0))
        h2 = fake_item("Replay 2026-03-19 20-55-02.mov", [(7.5, "Fucku")], 23.7, anc(2001.0))
        check(not M.same_fight_pair(h1, h2, "cs2")[0], "different names and a different number of kills: not merged")
    with section("2b) over every cached clip of both games (real data copy): the merged pairs, and nothing else"):
        cfg = M.load_config()
        keep = (M.out, M.LOGONLY)
        M.out = M.LOGONLY = lambda *a, **k: None
        try:
            res = {}
            for game in ("valorant", "cs2"):
                pool, _st = M.game_pool(cfg, game, None)
                for it in pool:
                    it["anc"] = M.clip_anchor(it["rec"]["path"], it["rec"].get("dur"))
                dups = M.find_duplicate_clips(pool, game)
                res[game] = (pool, dups)
        finally:
            M.out, M.LOGONLY = keep
        for game, (pool, dups) in res.items():
            print(f"   {game}: {len(pool)} cached clips with kills, {len(dups)} merged")
            for s_, d_, rule in dups:
                print(f"     KEEP {Path(s_['rec']['path']).name} ({len(s_['kills'])}k)  DROP {Path(d_['rec']['path']).name} ({len(d_['kills'])}k)  [{rule[:70]}]")
        bad = 0
        for game, (pool, dups) in res.items():
            for s_, d_, rule in dups:
                ks, kd = sorted(s_["kills"], key=lambda k: k["t"]), sorted(d_["kills"], key=lambda k: k["t"])
                sm, bg = (ks, kd) if len(ks) <= len(kd) else (kd, ks)
                twin = all(any(abs(y["t"] - k["t"]) <= M.SAME_FIGHT_S for y in bg) for k in sm)
                by_name = M.clip_name_base(s_["rec"]["path"]) == M.clip_name_base(d_["rec"]["path"])
                a1, a2 = s_.get("anc"), d_.get("anc")
                same_time = bool(a1 and a2 and min(a1["end"], a2["end"]) - max(a1["start"], a2["start"]) >= 0.5 * min(a1["end"] - a1["start"], a2["end"] - a2["start"]))
                if not (twin and (by_name or (len(ks) == len(kd) and same_time))):
                    bad += 1
        check(bad == 0, "every merged pair has all its kills within 0.3 s of a twin and is a name-suffix copy or was recorded at the same time (0 exceptions)")
        look = 0
        for game, (pool, dups) in res.items():
            merged_ids = {id(d_) for _s, d_, _r in dups} | {id(s_) for s_, _d, _r in dups}
            by_n = {}
            for it in pool:
                by_n.setdefault(len(it["kills"]), []).append(it)
            for n, lst in by_n.items():
                for x in range(len(lst)):
                    for y in range(x + 1, len(lst)):
                        a_, b_ = lst[x], lst[y]
                        if id(a_) in merged_ids and id(b_) in merged_ids:
                            continue
                        ka, kb = sorted(a_["kills"], key=lambda k: k["t"]), sorted(b_["kills"], key=lambda k: k["t"])
                        if all(abs(p["t"] - q["t"]) <= M.SAME_FIGHT_S and M._same_fight_victim(game, p.get("victim"), q.get("victim")) for p, q in zip(ka, kb)):
                            look += 1
        print(f"   {look} clip pairs look alike (same kill count, same victims, same clip times) but were recorded at different times: refused")
        check(len(res["cs2"][1]) >= 2 and any("19.48.57.15.DVR" in str(s_["rec"]["path"]) for s_, _d, _r in res["cs2"][1]), "the 2025.02.08 - 19.48.57.15 DVR / DVR_1 pair of the report is among them")
    with section("2c) a plan places the fight once: CS2 selection with DVR, DVR_1 and DVR_1_1 ticked, ledger 0 lost, log line"):
        cfg = M.load_config()
        keep = (M.out, M.LOGONLY)
        lines = []
        M.out = M.LOGONLY = lambda *a, **k: lines.append(" ".join(map(str, a)))
        try:
            pool, _st = M.game_pool(cfg, "cs2", None)
            allp = {Path(i["rec"]["path"]).name: i["rec"]["path"] for i in pool}
            trio = [allp[n] for n in allp if "2025.02.08 - 19.48.57.15.DVR" in n]
            others = [i["rec"]["path"] for i in pool if len(i["kills"]) >= 2 and "19.48.57" not in i["rec"]["path"]][:12]
            songs, _u, _c = M.song_pool(cfg)
            plan, _t = M.make_plan(cfg, "cs2", paths=trio + others, song_path=songs[0]["path"], target="optimal", seed=7, scan=False)
        finally:
            M.out, M.LOGONLY = keep
        got = [t for t in plan["takes"] if "19.48.57.15.DVR" in Path(t["path"]).name]
        check(len(trio) == 3 and len(got) == 1 and len(got[0]["kills"]) == 3, f"the fight is in the cut list exactly once ({[Path(t['path']).name[-16:] for t in got]}, {len(got[0]['kills']) if got else 0} kills)")
        led = next((l for l in lines if l.startswith("kill ledger:")), "")
        check("0 lost" in led and "merged as proven duplicates" in led, f"ledger: '{led[:110]}'")
        check(any("merged duplicate: " in l and "same fight saved twice" in l for l in lines + plan["notes"]), "the log says 'merged duplicate: same fight saved twice'")
        check(not M.verify_cutlist(plan), "cut list valid")


# ------------------------------------------------------------------------------------------------ 3) song length + date-added sort
def make_lib_lengths(tmp, specs):
    """specs = [(title, artist, seconds, added 'YYYY-MM-DD')]: real mp3 files of these lengths + a playlist CSV with the 'Added At' dates."""
    import csv
    lib, pl = tmp / "songs3", tmp / "pl3"
    lib.mkdir(exist_ok=True)
    pl.mkdir(exist_ok=True)
    files = []
    for i, (title, artist, sec, _ad) in enumerate(specs):
        f = lib / f"{title} - {artist}.mp3"
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f={220 + 90 * i}:d={sec}", "-c:a", "libmp3lame", "-b:a", "32k", str(f)], capture_output=True)
        assert r.returncode == 0, r.stderr.decode()[-200:]
        t = time.time() - 900
        os.utime(f, (t, t))
        files.append(str(f))
    with open(pl / "list.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["Track URI", "Track Name", "Artist Name(s)", "Duration (ms)", "Added At", "Danceability", "Energy", "Tempo"])
        for i, (title, artist, sec, ad) in enumerate(specs):
            w.writerow([f"spotify:track:{i}", title, artist, int(sec * 1000), ad + "T10:00:00Z", 0.7, 0.8, 128.0 + i])
    return lib, pl, files


def part_song_columns(tmp):
    with section("3) song length (m:ss) in the Songs tab and the Manual song list, 'Added' sort in the Songs tab = the Manual tab's (temp library, nothing real touched)"):
        try:
            import tkinter  # noqa: F401
        except Exception:
            check(False, "tkinter missing - the GUI checks could not run")
            return
        check(M.fmt_mss(0) == "" and M.fmt_mss(None) == "" and M.fmt_mss(59.4) == "0:59" and M.fmt_mss(60) == "1:00" and M.fmt_mss(224.7) == "3:45" and M.fmt_mss(3725) == "62:05", "fmt_mss: 59.4 -> 0:59, 60 -> 1:00, 224.7 -> 3:45, unknown -> ''")
        specs = [("Alpha Song", "Artist A", 41, "2026-10-01"), ("Beta Song", "Artist B", 125, "2026-10-09"), ("Gamma Song", "Artist C", 63, "2026-10-05"), ("Delta Song", "Artist D", 200, "2026-10-03")]
        lib, pl, files = make_lib_lengths(tmp, specs)
        real_lib = Path(M.load_config().get("mp3_dir") or "")
        real_before = sorted((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in real_lib.glob("*.mp3")) if real_lib.is_dir() else []
        keep = M.use_data_dir(tmp / "d3")
        try:
            cfg = dict(M.load_config(), mp3_dir=str(lib), playlist_dir=str(pl), clip_dirs={"valorant": [], "cs2": []}, song_overrides={})
            M.save_json(M.CONFIG_PATH, cfg)
            aud = M.scan_audio(cfg)
            durs = {Path(a["path"]).name: a["dur"] for a in aud}
            check(all(abs(durs[f"{t} - {a}.mp3"] - s) < 1.0 for t, a, s, _d in specs), f"scan_audio reads each song's length from the mp3 ({ {k[:5]: round(v) for k, v in durs.items()} })")
            cache_before = M.load_json(M.AUDIO_CACHE, {})
            t0 = time.perf_counter()
            M.scan_audio(cfg)
            check(M.load_json(M.AUDIO_CACHE, {}) == cache_before and time.perf_counter() - t0 < 1.0, f"the length is cached with the tags: a second scan reads no file again ({time.perf_counter() - t0:.2f} s)")
            songs, _un, _c = M.song_pool(cfg)
            check({Path(s["path"]).name: M.fmt_mss(s["dur"]) for s in songs} == {"Alpha Song - Artist A.mp3": "0:41", "Beta Song - Artist B.mp3": "2:05", "Gamma Song - Artist C.mp3": "1:03", "Delta Song - Artist D.mp3": "3:20"}, "song_pool carries the length of every song")
            real_sc, real_eb = M.scan_clips, M.ensure_bars
            M.scan_clips = lambda cfg, rescan=False: []
            M.ensure_bars = lambda cfg, force=False: None
            app = M.App(0)
            root = app.root
            root.geometry("1500x900+0+0")
            app.nb.select(app.tabs["Manual"])
            try:
                def settle(n=300):
                    for _ in range(n):
                        root.update()
                        time.sleep(0.04)
                        if not app.busy and not app.pending:
                            break
                settle()
                app.run_task("matches", app.load_matches)
                settle(600)
                for _ in range(60):
                    root.update()
                    time.sleep(0.05)
                M.scan_clips, M.ensure_bars = real_sc, real_eb
                exp_len = {Path(f).name: M.fmt_mss(s) for f, (_t, _a, s, _d) in zip(files, specs)}
                exp_add = {Path(f).name: d for f, (_t, _a, _s, d) in zip(files, specs)}
                check("len" in app.stree["columns"] and "len" in app.mtree["columns"] and list(app.stree["columns"])[-1] == "trash" and list(app.mtree["columns"])[-1] == "trash",
                      f"both lists have a Length column and still end with the trash column ({list(app.stree['columns'])} / {list(app.mtree['columns'])})")
                check(app.stree.heading("len")["text"] == "Length" and app.mtree.heading("len")["text"] == "Length" and app.mtree.heading("added")["text"] == "Added", "headings: Length (both lists), Added (Songs tab)")
                ch = [i for i in app.stree.get_children() if i != "auto"]
                got_s = {Path(i).name: app.stree.set(i, "len") for i in ch}
                got_m = {Path(i).name: app.mtree.set(i, "len") for i in app.mtree.get_children()}
                check(got_s == exp_len and got_m == exp_len, f"Manual list and Songs tab show the same lengths: {sorted(got_m.values())}")
                add_s = {Path(i).name: app.stree.set(i, "added") for i in ch}
                add_m = {Path(i).name: app.mtree.set(i, "added") for i in app.mtree.get_children()}
                check(add_s == exp_add and add_m == exp_add, f"the Songs tab shows the same 'date added' as the Manual list ({sorted(add_m.values())})")
                check(app.MTREE_TRASH_COL == "#%d" % (list(app.mtree["columns"]).index("trash") + 1) and app.STREE_TRASH_COL == "#%d" % (list(app.stree["columns"]).index("trash") + 1), "the trash click columns follow the new layout")

                def order(tree):
                    return [Path(i).name for i in tree.get_children() if i != "auto"]

                def settle2():
                    for _ in range(80):
                        root.update()
                        time.sleep(0.02)
                by_add = sorted(exp_add, key=lambda n: exp_add[n])
                by_len = sorted(exp_len, key=lambda n: sum(int(x) * m for x, m in zip(exp_len[n].split(":"), (60, 1))))
                for tree, nm in ((app.stree, "Manual"), (app.mtree, "Songs")):
                    for col, exp in (("added", by_add), ("len", by_len)):
                        app.sorts.pop(str(tree), None)
                        app.sort_by(tree, col)
                        settle2()
                        o1 = order(tree)
                        app.sort_by(tree, col)
                        settle2()
                        o2 = order(tree)
                        check(o1 == list(reversed(exp)) and o2 == exp and app.sorts[str(tree)] == (col, False),
                              f"{nm}: click '{col}' = largest/newest first, click again = reversed ({[n[:5] for n in o1]} then {[n[:5] for n in o2]})")
                        h = tree.heading(col)["text"]
                        check(h.endswith("▲"), f"{nm}: the '{col}' heading shows the direction arrow ({h})")
                # same default + toggle as the Manual list: first click descending for 'added'
                app.sorts.pop(str(app.mtree), None)
                app.sort_by(app.mtree, "added")
                check(app.sorts[str(app.mtree)] == ("added", True), "Songs tab: the first click on 'Added' sorts newest first, like the Manual tab")
                # no lag with 1900+ songs
                app.songs = [{"path": f"s{i}.mp3", "artist": "a", "title": f"t{i}", "added": datetime.datetime(2026, 1, 1) + datetime.timedelta(days=i % 500), "csv_bpm": 90.0 + i % 80, "dur": 120 + i % 240} for i in range(2000)]
                app.sorts.pop(str(app.stree), None)
                app.sort_by(app.stree, "len")
                t0 = time.perf_counter()
                app.refresh_songs()
                t_s = time.perf_counter() - t0
                app.match_items = [(f"s{i}.mp3", f"s{i}.mp3", "t", "a", 100, "ok", "128", M.fmt_mss(120 + i % 240), "2026-01-01") for i in range(2000)]
                app.sort_by(app.mtree, "added")
                t0 = time.perf_counter()
                app.fill_matches()
                t_m = time.perf_counter() - t0
                check(t_s < 0.5 and t_m < 1.0, f"2000 songs: Manual list refill + sort {t_s * 1000:.0f} ms, Songs tab refill + sort {t_m * 1000:.0f} ms")
            finally:
                M.scan_clips, M.ensure_bars = real_sc, real_eb
                try:
                    root.destroy()
                except Exception:
                    pass
        finally:
            M.restore_data_dir(keep)
        real_after = sorted((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in real_lib.glob("*.mp3")) if real_lib.is_dir() else []
        check(real_before == real_after, f"the real song library is untouched ({len(real_after)} files)")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t770_"))
    only = set(filter(None, os.environ.get("V770_PARTS", "").split(",")))
    want = lambda k: not only or k in only
    if want("0"):
        part_changelog()
    if want("1"):
        with PB.data_copy(M):
            old = M.use_data_dir(tmp / "pdata")
            try:
                part_drop_placement(tmp)
            finally:
                M.restore_data_dir(old)
        with PB.data_copy(M):
            part_drop_real(tmp)
    if want("g"):
        with PB.data_copy(M):
            old = M.use_data_dir(tmp / "gdata2")
            try:
                part_guards(tmp)
            finally:
                M.restore_data_dir(old)
            part_guards_real(tmp)
    if want("2"):
        with PB.data_copy(M):
            part_same_fight()
    if want("3"):
        part_song_columns(tmp)
    after = snapshot(REAL_DATA)
    if before == after:
        check(True, f"real montage_data byte-identical after the tests ({len(before)} files)")
    else:
        names_ = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        print("   NOTE (nothing was touched by the tests, the Montager app writes there): real montage_data differs in " + ", ".join(names_[:12]))
    print(f"total test time {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}): " + "; ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
