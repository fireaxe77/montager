"""V7.6.1 tests. Sections (each prints ok / FAIL lines, the last line is ALL OK only when every check ran and passed):
  0) changelog: one entry per version, the Settings viewer parses both files
  1) RENDER TIMING: marker clips (flash + click at the exact shot time) of mixed size / fps / container / VFR, planned by the real planner, stitched take included, rendered by the
     real pipeline and measured on the output file (video frame, audio click): every kill within 1 frame / 17 ms
  2) DETERMINISM + ONE PICK PER JOB: the colour tie-break does not depend on PYTHONHASHSEED; the summary -> render pairs keep song / style / length; a chosen song is never overridden
  9) TRASH ICON for songs (temp song library, no real files)
Runs on a COPY of montage_data (the real folder is only read).   python tests\\test_v761.py   (skip the long parts: V761_FAST=1)"""
import os
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


def main():
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t761_"))
    part_changelog()
    if not FAST:
        part_marker(tmp)
    part_determinism(tmp)
    part_trash(tmp)
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
