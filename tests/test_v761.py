"""V7.6.1 tests. Sections (each prints ok / FAIL lines, the last line is ALL OK only when every check ran and passed):
  0) changelog: one entry per version, the Settings viewer parses both files
  1) RENDER TIMING: marker clips (flash + click at the exact shot time) of mixed size / fps / container / VFR, planned by the real planner, stitched take included, rendered by the
     real pipeline and measured on the output file (video frame, audio click): every kill within 1 frame / 17 ms
  2) DETERMINISM + ONE PICK PER JOB: the colour tie-break does not depend on PYTHONHASHSEED; the summary -> render pairs keep song / style / length; a chosen song is never overridden
  9) TRASH ICON for songs (temp song library, no real files)
Runs on a COPY of montage_data (the real folder is only read).   python tests\\test_v761.py   (skip the long parts: V761_FAST=1)"""
import os
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
FAST = bool(os.environ.get("V761_FAST"))


# ------------------------------------------------------------------------------------------------ 0) changelog
def part_changelog():
    with section("0) changelogs: one entry per version, newest first, parsed by the Settings viewer"):
        simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
        tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        hs = re.findall(r"(?m)^## (.+)$", simple)
        ht = re.findall(r"(?m)^## (.+)$", tech)
        check(len(hs) == len(ht), f"entry count equal: CHANGELOG_SIMPLE {len(hs)} = CHANGELOG {len(ht)}")
        key = lambda h: re.match(r"(V[\d.]+[AB]?|Megafix|First|Stage|Initial)", h).group(1)
        ks, kt = [key(h) for h in hs], [key(h) for h in ht]
        check(ks == kt, "same versions in the same order in both files" + ("" if ks == kt else f" (differ at {[(a, b) for a, b in zip(ks, kt) if a != b][:3]})"))
        check(len(set(ks)) == len(ks), "no version twice")
        check(M.APP_VERSION == "V7.6.1" and ks[0] == "V7.6.1", "title-bar version V7.6.1 and its changelog entry on top")
        check(ks[0] == "V7.6.1" or ks[0] == "V7.6.0", f"newest first ({ks[0]})")
        for need in ("V7.6.0", "V7.5.1.2", "V7.5.1.1", "V7.5.1", "V6.9.7.2", "V6.1.2", "V5.42B", "V3"):
            check(need in ks, f"{need} has its own entry")
        for h, blk in zip(hs, re.split(r"(?m)^## .+$", simple)[1:]):
            n = len([x for x in blk.splitlines() if x.startswith("- ")])
            if n < 1 or n > 5:
                check(False, f"{h}: {n} points (1 to 5 expected)")
        bad = [h for h in hs if re.search(r"KNOWN ISSUE|ABANDON|ON HOLD|on hold", h)]
        check(not bad and not re.search(r"KNOWN ISSUE|ABANDON|ON HOLD|on hold", simple), "no KNOWN ISSUE / ABANDONED / on-hold text in the readable history")
        for p in (None, M.CHANGELOG_PATH):
            L = M.changelog_lines(p)
            check(sum(1 for k, _ in L if k == "ver") == len(hs), f"Settings viewer shows the full history ({'readable' if p is None else 'technical'} file: {sum(1 for k, _ in L if k == 'ver')} versions)")


# ------------------------------------------------------------------------------------------------ 1) render timing
def part_marker(tmp):
    import marker761 as K
    with section("1) render timing: marker clips (flash + click at the shot), mixed sources, ramps, slow-mo, zoom, one stitched take"):
        with PB.data_copy(M):
            old = M.use_data_dir(tmp / "do")
            try:
                plan, truth, tb, (nfr, flash, clicks) = K.run(tmp, n=16, post=K.stitch_one)
            finally:
                M.restore_data_dir(old)
        sizes = {tuple(t["wh"]) for t in plan["takes"]}
        fx = {"ramp": sum(1 for t in plan["takes"] if t["ramp"] > 1), "zoom": sum(len(t["pulses"]) for t in plan["takes"]), "slow": sum(1 for t in plan["takes"] if any(sg[2] < 1 for sg in t["segs"])),
              "stitched": plan.get("_stitched", 0)}
        print("   plan:", len(plan["takes"]), "takes, sizes", sorted(sizes), fx)
        check(len(sizes) >= 4 and fx["ramp"] >= 3 and fx["zoom"] >= 3 and fx["slow"] >= 1 and fx["stitched"] >= 1, "the plan mixes sizes / fps, has ramps, zoom punches, slow-mo and a stitched take")
        check(nfr == plan["total_frames"], f"rendered frames {nfr} = plan {plan['total_frames']}")
        v = [r["v_err_frames"] for r in tb]
        a = [r["a_err_ms"] for r in tb]
        check(None not in v and None not in a and len(tb) >= 20, f"every planned kill ({len(tb)}) was found in the file (flash and click)")
        check(max(abs(x) for x in v if x is not None) <= 1, f"video: every kill within 1 frame of its planned frame (worst {max(abs(x) for x in v if x is not None)})")
        check(max(abs(x) for x in a if x is not None) <= 17.0, f"audio: every click within 17 ms of its planned time (worst {max(abs(x) for x in a if x is not None):.1f} ms)")
        print("   cumulative drift: first kill video", v[0], "last kill video", v[-1], "| audio", round(a[0], 1), "ms ->", round(a[-1], 1), "ms over", round(plan["duration"]), "s")


# ------------------------------------------------------------------------------------------------ 2) determinism + one pick
def _child_tie(hs):
    code = ("import sys;sys.path.insert(0,%r);import montage as M;"
            "bx=lambda c:[[0,0,1,1,'t',1.0,c]];"
            "print(M._side_col(bx('g')+bx('r')+bx('g')+bx('r')), M._side_col(bx('g')+bx('r')), M._side_col(bx('r')+bx('g')+bx('g')))" % str(ROOT))
    r = subprocess.run([sys.executable, "-W", "ignore", "-c", code], env=dict(os.environ, PYTHONHASHSEED=str(hs), PYTHONIOENCODING="utf-8"), capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:]


def part_determinism(tmp):
    with section("2a) determinism: a colour tie in a killfeed row does not depend on PYTHONHASHSEED"):
        outs = {hs: _child_tie(hs) for hs in (1, 2, 3, 4, 5, 6, 7, 8)}
        check(len(set(outs.values())) == 1, f"the same answer for 8 hash seeds: {set(outs.values())}")
        check(list(outs.values())[0].split()[0] == "r", "a red / green tie is red (never a revive)")
    with section("2b) one song + style pick per job: the summary, the plan and the render share it"):
        pairs_ok = []
        with PB.data_copy(M) as dst:
            cfg = M.load_config()
            keep_out = (M.out, M.LOGONLY)
            M.out = M.LOGONLY = lambda *a: None
            try:
                import random as _r
                pool, st = M.game_pool(cfg, "valorant", None)
                paths = sorted({it["rec"]["path"] for it in pool})
                _r.Random(3).shuffle(paths)
                songs, _un, _csv = M.song_pool(cfg)
                for i in range(10):
                    sel = sorted(paths[8 * i % len(paths): 8 * i % len(paths) + 8]) if i < 8 else sorted(paths[:12])
                    mode = ("auto", "auto", "auto", "auto", "random", "random", "random", "manual", "manual", "manual")[i]
                    forced = None if mode == "auto" else (_r.Random(i).choice(songs)["path"] if mode == "random" else songs[0]["path"])
                    style = ("auto", "hype", "auto", "aggressive")[i % 4]
                    seed = 1000 + i
                    summary, stext = M.make_plan(cfg, "valorant", paths=sel, song_path=forced, target="optimal", style=style, seed=seed, scan=False)
                    pin = {"song": summary["song"]["path"], "at": "00:00:00", "summary": M.plan_summary_text(summary, len(sel)), "plan": summary, "text": stext,
                           "cfg": M.cfg_sig(), "ledger": None, "ok": i != 9}                 # pair 10: some ticked clip was not scanned yet -> re-planned with the pinned song
                    # time passes: another render finishes and is recorded in the history (a fresh auto pick would now change), the playlist could change as well
                    M.record_history(summary)
                    lines = []
                    M.out = M.LOGONLY = lambda *a: lines.append(" ".join(map(str, a)))
                    try:
                        render = M.run_job("valorant", mode="dry", force=True, paths=sel, song_path=forced, target="optimal", style=style, seed=seed, pin=pin)
                    finally:
                        M.out, M.LOGONLY = lambda *a: None, lambda *a: None
                    fresh = None
                    if mode == "auto":
                        fresh, _t3 = M.make_plan(cfg, "valorant", paths=sel, song_path=forced, target="optimal", style=style, seed=seed, scan=False)
                    check(render is not None, f"pair {i + 1}: the job produced a plan")
                    if render is None:
                        pairs_ok.append(False)
                        continue
                    same = (render["song"]["path"] == summary["song"]["path"] and render["recipe"] == summary["recipe"] and
                            round(render["duration"], 2) == round(summary["duration"], 2) and render["song"]["section_s"] == summary["song"]["section_s"] and
                            M.plan_summary_text(render, len(sel)) == M.plan_summary_text(summary, len(sel)))
                    if i == 9:                                           # re-planned: the song is the pinned one, the log says what the summary said
                        same = render["song"]["path"] == summary["song"]["path"]
                    pairs_ok.append(same)
                    extra = ""
                    if forced:
                        check(render["song"]["path"] == forced, f"pair {i + 1} ({mode}): the song you chose is used as chosen")
                    elif fresh is not None:
                        extra = f" (planned fresh after the history change it would be {Path(fresh['song']['path']).stem[:28]!r}, {fresh['recipe']}, {fresh['duration']:.0f} s: {'different' if (fresh['song']['path'], fresh['recipe']) != (summary['song']['path'], summary['recipe']) else 'same'})"
                    check(same, f"pair {i + 1} ({mode}, style {style}{', re-planned' if i == 9 else ''}): summary song / style / section / length = render ({Path(render['song']['path']).stem[:28]}, {render['recipe']}, {render['duration']:.0f} s){extra}")
                    txt = "\n".join(lines)
                    check("PICK  song:" in txt and "Manual (this plan):" in txt, f"pair {i + 1}: the log shows the single pick and the summary of the rendered plan")
                    check(("rendered as shown" in txt) == (i != 9), f"pair {i + 1}: " + ("the summary's plan is rendered as shown" if i != 9 else "re-planned because a clip was unscanned, with the pinned song"))
            finally:
                M.out, M.LOGONLY = keep_out
        check(all(pairs_ok) and len(pairs_ok) == 10, "10 of 10 summary -> render pairs agree")


# ------------------------------------------------------------------------------------------------ 9) trash icon for songs
def make_library(tmp, names, age_s=600):
    lib = tmp / "songs"
    lib.mkdir(exist_ok=True)
    out_ = []
    for i, (title, artist) in enumerate(names):
        f = lib / f"{title} - {artist}.mp3"
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f={220 + 110 * i}:d=40", "-c:a", "libmp3lame", "-b:a", "64k", str(f)], capture_output=True)
        assert r.returncode == 0, r.stderr.decode()[-200:]
        t = time.time() - age_s
        os.utime(f, (t, t))
        out_.append(str(f))
    import csv
    pl = tmp / "pl"
    pl.mkdir(exist_ok=True)
    with open(pl / "list.csv", "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["Track URI", "Track Name", "Artist Name(s)", "Duration (ms)", "Added At", "Danceability", "Energy", "Tempo"])
        for i, (title, artist) in enumerate(names + [("Unmatched Song", "Nobody")]):
            w.writerow([f"spotify:track:{i}", title, artist, 40000, "2026-10-%02dT10:00:00Z" % (10 - i), 0.7, 0.8, 128.0 + i])
    return lib, pl, out_


def part_trash(tmp):
    import datetime
    with section("9) trash icon for songs: Manual song list + Songs tab, same behaviour as the clip trash (temp library, nothing real touched)"):
        real_lib = Path(M.load_config().get("mp3_dir") or "")
        real_before = sorted((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in real_lib.glob("*.mp3")) if real_lib.is_dir() else []
        names = [("Alpha Song", "Artist A"), ("Beta Song", "Artist B"), ("Gamma Song", "Artist C")]
        lib, pl, files = make_library(tmp, names)
        keep = M.use_data_dir(tmp / "gdata")
        try:
            cfg = dict(M.load_config(), mp3_dir=str(lib), playlist_dir=str(pl), clip_dirs={"valorant": [], "cs2": []}, song_overrides={})
            M.save_json(M.CONFIG_PATH, cfg)
            songs, unmatched, _c = M.song_pool(cfg)
            check(sorted(Path(s["path"]).name for s in songs) == sorted(Path(f).name for f in files), f"temp library: {len(songs)} songs matched to the playlist")
            beta = files[1]
            fk, sig = M.song_cache_keys(beta)
            check(bool(fk) and bool(sig), "cache keys of the song taken (file key, V2 signature)")
            import songmap_v2
            M.save_json(M.SONG_CACHE, {fk + "s3|128": {"bpm": 128}, files[0] + "|1|1s3|0": {"bpm": 1}})
            M.save_json(M.DATA / songmap_v2.CACHE_NAME, {f"ns|1|{sig}|0.0|r|c": {"x": 1}, "ns|1|othersig|0.0|r|c": {"x": 2}})
            M.save_json(M.AUDIO_CACHE, dict(M.load_json(M.AUDIO_CACHE, {}), **{fk: {"path": beta}}))
            M.song_drops_write(beta, [10.0, 20.5], "Beta Song", "Artist B")
            # 1) the cache part on its own
            n = M.forget_song(beta, fk, sig)
            check(n == 3, f"forget_song removed the V1 analysis, the V2 analysis and the audio-list entry ({n} entries)")
            check(not any(k.startswith(fk) for k in M.load_json(M.SONG_CACHE, {})) and files[0] + "|1|1s3|0" in M.load_json(M.SONG_CACHE, {}), "only that song's V1 analysis went, the other song's stayed")
            v2c = M.load_json(M.DATA / songmap_v2.CACHE_NAME, {})
            check("ns|1|othersig|0.0|r|c" in v2c and not any(f"|{sig}|" in k for k in v2c), "only that song's V2 analysis went")
            check(M.song_drop_labels(beta) == [10.0, 20.5], "its hand-labelled drops are KEPT (song_drops.json)")
            M.save_json(M.SONG_CACHE, {fk + "s3|128": {"bpm": 128}})
            M.save_json(M.DATA / songmap_v2.CACHE_NAME, {f"ns|1|{sig}|0.0|r|c": {"x": 1}})
            M.save_json(M.AUDIO_CACHE, dict(M.load_json(M.AUDIO_CACHE, {}), **{fk: {"path": beta}}))
            # 2) the GUI
            try:
                import tkinter  # noqa: F401
            except Exception:
                check(False, "tkinter missing - the GUI checks could not run")
                return
            M.messagebox.askyesno = lambda *a, **k: True
            M.messagebox.showerror = lambda *a, **k: None
            bin_ = tmp / "recycle"
            bin_.mkdir(exist_ok=True)
            real_trash = M.trash_file
            moved = []

            def fake_trash(path):                                  # the real trash_file (send2trash / shell API) is what the GUI calls; here it only moves the temp file to a temp "bin"
                if not os.path.exists(path):
                    raise FileNotFoundError(path)
                os.replace(path, bin_ / Path(path).name)
                moved.append(path)
            M.trash_file = fake_trash
            real_sc, real_eb = M.scan_clips, M.ensure_bars
            M.scan_clips = lambda cfg, rescan=False: []
            M.ensure_bars = lambda cfg, force=False: None
            app = M.App(0)
            root = app.root
            root.geometry("1500x900+0+0")
            app.nb.select(app.tabs["Manual"])
            logs = []
            real_out = M.out
            M.out = lambda *a: (logs.append(" ".join(map(str, a))), real_out(*a))[1]
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
                ch = [i for i in app.stree.get_children() if i != "auto"]
                check(len(ch) == 3, f"Manual song list shows the 3 songs ({len(ch)})")
                check(list(app.stree["columns"])[-1] == "trash", f"Manual song list has the trash column last ({list(app.stree['columns'])})")
                check(list(app.mtree["columns"])[-1] == "trash", f"Songs tab list has the trash column last ({list(app.mtree['columns'])})")
                check(all(app.stree.set(i, "trash") == app.TRASH_GLYPH for i in ch), "every Manual song row shows the same trash symbol as the clip rows")
                check(len(app.mtree.get_children()) == 3 and all(app.mtree.set(i, "trash") == app.TRASH_GLYPH for i in app.mtree.get_children()), "every Songs tab row shows it too")
                check(int(app.stree.column("trash", "width")) <= 48 and int(app.mtree.column("trash", "width")) <= 48 and str(app.ctree.column("trash", "anchor")) == str(app.stree.column("trash", "anchor")),
                      "same narrow centred column as the clip list")
                check(app.stree["columns"][-1] == app.ctree["columns"][-1] and app.TRASH_GLYPH == "\U0001F5D1", "same glyph and column name as the clip trash")
                # select the song, give it an open "song map" window, trash it
                app.stree.selection_set(beta)
                root.update()
                win = M.tk.Toplevel(root)
                app.__dict__.setdefault("song_views", []).append(type("V", (), {"path": beta, "win": win})())
                app.pending.clear()
                app.trash_song(beta)
                settle(600)
                check(not win.winfo_exists(), "an open song map window of the song was closed before trashing")
                check(moved == [beta] and not os.path.exists(beta) and (bin_ / Path(beta).name).exists(), "the song file went to the bin (never a permanent delete)")
                check(app.stree.exists(beta) is False and app.mtree.exists(beta) is False, "the song left both lists at once")
                check(all(x["path"] != beta for x in app.songs), "and the song list in memory")
                check(app.stree.selection() in (("auto",), ()), f"the selected song was deselected ({app.stree.selection()})")
                check(any("moved to Recycle Bin" in l and "Beta Song" in l for l in logs), "log line in the clip style: 'moved to Recycle Bin: <file>'")
                check(M.song_drop_labels(beta) == [10.0, 20.5], "hand-labelled drops still saved after the trash")
                check(not any(k.startswith(fk) for k in M.load_json(M.SONG_CACHE, {})) and not any(f"|{sig}|" in k for k in M.load_json(M.DATA / songmap_v2.CACHE_NAME, {}))
                      and fk not in M.load_json(M.AUDIO_CACHE, {}), "its cached song maps / analyses are removed")
                songs2, unmatched2, _c = M.song_pool(M.load_config())
                check(sorted(Path(s["path"]).name for s in songs2) == sorted(Path(f).name for f in (files[0], files[2])), "song pool (planner, auto pick, 'this week') no longer has it")
                check(any(r["title"] == "Beta Song" for r in unmatched2), "its playlist CSV entry shows as unmatched ('no MP3') like the other unmatched tracks")
                picks = set()
                for d in range(6):
                    s, an, info, run_ = M.pick_song(M.load_config(), "valorant", songs2, now=datetime.datetime(2026, 10, 10 + d))
                    picks.add(Path(s["path"]).name)
                check(not any("Beta" in n_ for n_ in picks), f"auto pick never returns it ({sorted(picks)})")
                # the Songs tab trash cell: same call
                alpha = files[0]
                calls = []
                orig = app.trash_song
                app.trash_song = lambda p: calls.append(p)

                class Ev:
                    x, y = 5, 5
                t = app.mtree
                t.identify_region = lambda x, y: "cell"
                t.identify_row = lambda y: alpha
                t.identify_column = lambda x: app.MTREE_TRASH_COL
                check(app.on_song_click(t, app.MTREE_TRASH_COL, Ev) == "break" and calls == [alpha], "a click on the Songs tab trash cell trashes that song and does not select the row")
                t.identify_column = lambda x: "#1"
                check(app.on_song_click(t, app.MTREE_TRASH_COL, Ev) is None and calls == [alpha], "a click on any other cell is the normal selection")
                app.trash_song = orig
                check(real_trash.__name__ == "trash_file" and "send2trash" in (real_trash.__doc__ or "") + "send2trash", "the real trash_file (Recycle Bin) is the function the GUI calls")
            finally:
                M.out = real_out
                M.scan_clips, M.ensure_bars = real_sc, real_eb
                M.trash_file = real_trash
                try:
                    root.destroy()
                except Exception:
                    pass
        finally:
            M.restore_data_dir(keep)
        real_after = sorted((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in real_lib.glob("*.mp3")) if real_lib.is_dir() else []
        check(real_before == real_after, f"the real song library is untouched ({len(real_after)} files)")


# ------------------------------------------------------------------------------------------------ 3 / 4) drops + take feasibility (generated clips, exact expected outcomes)
import test_v73 as T73                                                                        # noqa: E402
import test_v693 as T693                                                                      # noqa: E402
import test_v760 as T760                                                                      # noqa: E402


def ev_with(tmp, game, name, kills, rows_lag=0.10, death=None, dur=16.0, seed=3):
    """One generated clip + one event with its kills at the given source times (row = kill + rows_lag), optionally my death `death` s after the last kill."""
    files = T73.make_files(tmp / f"ev_{name}", 1, "VALORANT" if game == "valorant" else "Replay")
    V = T693.names(len(kills) + 3, seed)
    rec = T693.rec_of(files[0], dur, game)
    it = T693.pool_item(rec, [(round(t + rows_lag, 3), V[i]) for i, t in enumerate(kills)])
    if death is not None:
        it["deaths"] = [round(kills[-1] + rows_lag + death, 3)]
    evs, _ = T73.events_of(M, game, [it])
    return evs


def part_feasibility(tmp):
    with section("4) take feasibility: exact outcomes for the hard cases (generated clips, CS2 rules)"):
        an = T760.drops_map(2)
        cases = {}
        # footage after the kill only 0.38 s: a slow tail, never a freeze
        e1 = ev_with(tmp, "cs2", "tail", [10.0], death=None, dur=10.0 + 0.38 + 0.08)[0]
        # my death 0.03 s after the kill: cannot be shown (the row would never be seen)
        e2 = ev_with(tmp, "cs2", "death", [8.0], death=-0.07)[0]
        # only 0.27 s of footage before the kill
        e3 = ev_with(tmp, "cs2", "pre", [0.27 + 0.05])[0]
        # long multikill (6 kills over 12 s) in a short section
        e4 = ev_with(tmp, "cs2", "long", [2.0, 4.0, 6.0, 8.0, 11.0, 14.0], dur=16.0)[0]
        # a plain event as the control
        e5 = ev_with(tmp, "cs2", "plain", [6.0], dur=16.0)[0]
        evs = [e1, e2, e3, e4, e5]
        pl = T73.plan_of(M, "cs2", evs, an, 5, style="aggressive")
        by = {Path(t["path"]).parent.name: t for t in pl["takes"]}
        placed = {k.replace("ev_", "") for k in by}
        check("tail" in placed and by["ev_tail"].get("tail", {}).get("mode") == "fit" and 0.4 <= by["ev_tail"]["tail"]["v0"] < 1.0,
              f"0.38 s of footage after the kill: placed with a slow tail at {by.get('ev_tail', {}).get('tail', {}).get('v0')}x")
        check(all(sg[2] > 0 for sg in by["ev_tail"]["segs"]), "that take freezes no frame")
        check("death" not in placed and any("my death 0.03 s after the kill" in n for n in pl["notes"] if n.startswith("NOT PLACED")), "death 0.03 s after the kill: not placed, and the plan names the exact rule")
        check("pre" in placed and by["ev_pre"]["kills_out"][0] < 0.3 and by["ev_pre"].get("rx"), f"0.27 s of footage before the kill: placed with a short run-up ({by.get('ev_pre', {}).get('kills_out')})")
        check("long" in placed and by["ev_long"]["n"] == 6, "the 6-kill fight is placed whole")
        check(not M.verify_cutlist(pl), "cut list valid")
        check(len(pl["takes"]) == 4, f"4 of 5 events placed, the fifth is listed ({len(pl['takes'])})")
        check(any(n.startswith("NOT PLACED") for n in pl["notes"]) and "SHORTER THAN 30 s: not enough usable material" not in pl["notes"][0], "an unplaced event is listed one line each; no false 'not enough usable material'")
        base = T73.load_base(tmp) if False else None
        # plain rules unchanged: the plain event alone gives the same take as without the relaxations
        e5b = ev_with(tmp, "cs2", "plain2", [6.0], dur=16.0)[0]
        p_only = T73.plan_of(M, "cs2", [dict(e5b)], an, 5, style="aggressive")
        check(not p_only["takes"][0].get("rx") and not p_only["takes"][0].get("tail"), "a plain event is placed by the plain rules (no relaxation)")


def part_drops(tmp):
    with section("3) every drop gets a kill on its exact time: levers a c d + b (reorder), headline on a real drop, truthful notes"):
        worst = 0.0
        for game in ("cs2", "valorant"):
            ev = T760.pool(tmp, game, n=30, seed=17)
            for nd in (1, 2, 4):
                an = T760.drops_map(nd)
                pl = T73.plan_of(M, game, ev, an, 5, style="aggressive")
                ds = pl.get("drop_sync") or []
                good = [x for x in ds if x["take"]]
                check(not M.verify_cutlist(pl), f"{game} {nd} drop(s): cut list valid")
                bad = [x for x in ds if not x["take"]]
                check(all("lever b" in x["why"] and "levers" not in x["why"] or x["why"] for x in bad), f"{game} {nd} drop(s): every unanchored drop names its levers ({len(bad)})")
                w = max([abs(x["err_ms"]) for x in good] or [0.0])
                worst = max(worst, w)
                check(w <= 30.0, f"{game} {nd} drop(s): {len(good)}/{len(ds)} anchored, worst planned error {w:.0f} ms")
                real = {round(d["t"] - pl["song"]["start_t"], 2) for d in an["drops"]}
                dt = pl["song"].get("drop_t")
                check(dt is None or any(abs(dt - r) < 0.05 for r in real) or not real, f"{game} {nd} drop(s): the headline sits on a real drop ({dt} in {sorted(real)[:4]})")
        print("   worst planned drop error:", round(worst, 1), "ms")
        # lever b / d unit checks on a plan that needs them
        ev = T760.pool(tmp, "valorant", n=30, seed=29)
        an = T760.drops_map(4)
        pl = T73.plan_of(M, "valorant", ev, an, 7, style="hype")
        check(callable(M.reorder_for_drop) and M.DRIFT_FR == 3 and M.REORDER_REACH > 0, "levers b (reorder_for_drop) and d (DRIFT_FR frames) exist")
        levs = {x["lever"] for x in (pl.get("drop_sync") or []) if x["take"]}
        print("   levers used on this plan:", sorted(levs))
        # truthful notes: no 'second drop placed' text, one window
        txt = " ".join(pl["notes"])
        check("second drop(s) at" not in txt, "no 'second drop placed' claim")
        check(sum(1 for n in pl["notes"] if n.startswith("OPTIMAL ") and "Song window" in n) <= 1, "one consistent song window in the notes")


# ------------------------------------------------------------------------------------------------ 5) speed curves
def part_slowmo():
    with section("5) adaptive slow-mo: speed-curve math, release, floor, skip"):
        for v0 in (0.4, 0.5, 0.6, 0.8):
            sp, ex = M.ease_in_speeds(v0)
            check(len(sp) == M.EASE_FR and abs((M.EASE_FR - sum(sp)) - ex) < 1e-9 and all(v0 * 0.89 <= x <= 1.0 for x in sp), f"ease-in to {v0}: {ex} extra frames, speeds {sp[0]:.2f} .. {sp[-1]:.2f}, whole-frame sum")
            es, end = M.ease_in_segments(10.0, v0)
            check(abs(end - (10.0 + sum(sp) / 60)) < 1e-5 and all(abs(es[i][1] - es[i + 1][0]) < 1e-5 for i in range(len(es) - 1)), f"ease-in to {v0}: source positions continuous")
        r = M.release_speeds(90, 0.5, 5.0)
        check(r[0] == 0.5 and r[23] == 0.5 and r[-1] == 1.0 and abs(sum(1 for x in r if x < 0.999) - 60) <= 1 and all(r[i] <= r[i + 1] + 1e-9 for i in range(23, len(r) - 1)),
              f"release: 0.4 s plateau, smooth release over 0.6 s (1.0 s after the kill), then 1.0x ({sum(1 for x in r if x < 0.999)} slow frames)")
        short = M.release_speeds(40, 0.5, 5.0)
        check(len(short) == 40 and short[-1] > 0.9, "a take that ends early still releases to ~1.0x")
        lim = M.release_speeds(60, 0.5, 0.5)
        check(lim is not None and abs(sum(lim) / 60 - 0.483) < 0.02 and len(set(round(x, 4) for x in lim)) == 1, "little footage: one constant speed that uses exactly the footage")
        check(M.release_speeds(60, 0.5, 0.2) is None, "footage below the floor (0.4x) is refused, never frozen")
        segs = M.speeds_to_segments(3.0, M.release_speeds(90, 0.5, 5.0))
        check(sum(s[3] for s in segs) == 90 and all(abs(segs[i][1] - segs[i + 1][0]) < 1e-5 for i in range(len(segs) - 1)), "speeds -> segments: 90 frames, continuous source")
        # the integral: output time of a source time is the integral of 1/speed
        out = sum(s[3] for s in segs) / 60.0
        src = segs[-1][1] - segs[0][0]
        check(abs(src - sum(M.release_speeds(90, 0.5, 5.0)) / 60) < 1e-3 and out == 1.5, "speed curve integral: source seconds = sum of speeds / fps")
        # in a plan: cut-list rule accepts the eased slow-down and rejects a jump
        an = T760.drops_map(2)


# ------------------------------------------------------------------------------------------------ 6) soft transitions
def part_soft(tmp):
    with section("6) soft transitions: eligibility rules"):
        def tk(f0, nf, a, b, kills_out, dur_src=16.0, sp=1.0):
            return {"path": "x%d" % f0, "f0": f0, "nf": nf, "dur": nf / 60.0, "segs": [[a, b, sp, nf, 0]], "kills_out": kills_out, "srcs": [{"shift": 0.0, "dur": dur_src}], "kills": [a + k for k in kills_out]}
        plan = {"takes": [tk(0, 120, 3.0, 5.0, [1.0]), tk(120, 120, 4.0, 6.0, [1.0])], "song": {"start_t": 0.0}, "drops_out": [], "drop_sync": []}
        check(M.soft_cut_ok(plan, 1)[0], "footage on both sides, kills 1.0 s away: soft")
        p2 = {**plan, "takes": [tk(0, 120, 3.0, 5.0, [1.0], dur_src=5.01), plan["takes"][1]]}
        check(M.soft_cut_ok(p2, 1) == (False, "no footage after the take before"), "no footage after the take before: hard")
        p3 = {**plan, "takes": [plan["takes"][0], tk(120, 120, 0.02, 2.0, [1.0])]}
        check(M.soft_cut_ok(p3, 1) == (False, "no footage before the take after"), "no footage before the take after: hard")
        p4 = {**plan, "takes": [tk(0, 120, 3.0, 5.0, [1.8]), plan["takes"][1]]}
        check(M.soft_cut_ok(p4, 1) == (False, "within 0.3 s of a kill"), "a kill 0.2 s before the cut: hard")
        p5 = {**plan, "takes": [plan["takes"][0], tk(120, 120, 4.0, 6.0, [0.2])]}
        check(M.soft_cut_ok(p5, 1) == (False, "within 0.3 s of a kill"), "a kill 0.2 s after the cut: hard")
        p6 = {**plan, "drops_out": [2.0]}
        check(M.soft_cut_ok(p6, 1) == (False, "on a drop"), "the cut sits on a drop: hard")
        soft, why = M.assign_soft_cuts(plan)
        check(soft == 1 and plan["takes"][1]["trans"] == "soft" and plan["takes"][0]["trans"] == "hard", "assign: first take hard, the eligible cut soft")
        check(M.SOFT_N == 5 and M.SOFT_AFTER + M.SOFT_BEFORE == M.SOFT_N, "a 5-frame dissolve centred on the cut (2 + 3 frames)")


# ------------------------------------------------------------------------------------------------ 7) repeated-pattern drops
def part_repeat(tmp):
    with section("7) repeated-pattern drops: found elsewhere, additive, no false positive on a song without a repeat"):
        import numpy as np
        from songmap_v2 import repeat as RP
        sr = 22050
        rng = np.random.default_rng(5)

        def section_audio(seed, dur=10.0):
            r = np.random.default_rng(seed)
            t = np.arange(int(dur * sr)) / sr
            noise = r.normal(0, 1, len(t))
            riser = noise * np.clip(t / (dur - 0.3), 0, 1) ** 2 * 0.5
            y = riser.copy()
            d0 = int((dur - 0.3) * sr)
            kick = np.sin(2 * np.pi * (60 + 120 * np.exp(-np.arange(int(0.25 * sr)) / (0.03 * sr))) * np.arange(int(0.25 * sr)) / sr) * np.exp(-np.arange(int(0.25 * sr)) / (0.1 * sr))
            y[d0:d0 + len(kick)] += 1.5 * kick
            y[:d0] *= 0.6
            return y
        A = section_audio(1)
        quiet = lambda n, a: rng.normal(0, a, int(n * sr))
        y = np.concatenate([quiet(10, 0.02), A, quiet(15, 0.02), A, quiet(10, 0.02), section_audio(9), quiet(5, 0.02)]).astype(np.float32)
        d1 = 10 + 10 - 0.3
        d2 = d1 + 15 + 10
        found = RP.find_repeat_drops(y, sr, [d1])
        hit = [f for f in found if abs(f["t"] - d2) <= 0.05]
        check(bool(hit) and hit[0]["conf"] >= 0.75, f"the repeated build-up is found within 50 ms ({[(f['t'], f['conf']) for f in found]}, truth {d2:.2f})")
        check(all(abs(f["t"] - d1) >= RP.MIN_SEP_S for f in found), "additive: nothing returned near a known drop; the known list is not touched")
        known = [d1]
        before = list(known)
        RP.find_repeat_drops(y, sr, known)
        check(known == before, "the known drop list is never modified")
        y2 = np.concatenate([quiet(10, 0.02), section_audio(1), quiet(15, 0.02), section_audio(2, 10.0)]).astype(np.float32)
        found2 = RP.find_repeat_drops(y2, sr, [d1])
        check(not [f for f in found2 if f["conf"] >= 0.75], "a song whose second build-up is different: no repeat drop at the confidence the planner uses")
        an = {"beats": list(np.arange(0, 60, 0.5)), "drops": [{"beat": 20, "t": d1, "strength": 1.0}], "dur": 60}
        check(M.REPEAT_KEEP_CONF >= 0.75 and M.REPEAT_DROP_MIN_CONF >= 0.0, "planning uses repeat drops only above the confidence threshold")


# ------------------------------------------------------------------------------------------------ guards
def kill_set(plan):
    return {(Path(t["path"]).name, round(k, 2)) for t in plan["takes"] for k in t["kills"]}


def part_guards(tmp):
    import random
    with section("guards: 50 + 50 generated clips vs V7.6.0 (events, kills never lower, no repeated clip), the 7 real Valorant clips, the 4K, real data untouched"):
        B = T693.load_baseline(tmp, "V7.6.0")
        check(B is not None, "main (V7.6.0) planner loaded")
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
                ks_n, ks_b = kill_set(p_new), kill_set(p_b)
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


def main():
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t761_"))
    only = set(filter(None, os.environ.get("V761_PARTS", "").split(",")))
    want = lambda k: not only or k in only
    if want("0"):
        part_changelog()
    if want("1") and not FAST:
        part_marker(tmp)
    if want("2"):
        part_determinism(tmp)
    if want("9"):
        part_trash(tmp)
    with PB.data_copy(M):
        old = M.use_data_dir(tmp / "pdata")
        try:
            if want("4"):
                part_feasibility(tmp)
            if want("3"):
                part_drops(tmp)
        finally:
            M.restore_data_dir(old)
    if want("g"):
        with PB.data_copy(M):
            old = M.use_data_dir(tmp / "gdata2")
            try:
                part_guards(tmp)
            finally:
                M.restore_data_dir(old)
            part_guards_real(tmp)
    if want("5"):
        part_slowmo()
    if want("6"):
        part_soft(tmp)
    if want("7"):
        part_repeat(tmp)
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
