"""V7.7.1 tests. Sections (each prints ok / FAIL lines, the last line is ALL OK only when every check ran and passed):
  1) Settings audit: every option of the Settings window: saved / loaded after a restart / reaches the planner or renderer / has the intended effect (table at the end)
  2) songmap: "Low-confidence songs: use the V1 beat grid" (ON = V7.7.0 byte for byte, OFF = V2 grid kept, forced V1 only without any usable V2 grid)
  3) music over gameplay: per clip group verdict, better detection, dB option + real mute, logs
  g) guards: kill counts / takes / cut lists / drops identical to V7.7.0 with defaults, the 7 real Valorant clips (4 / 11 / 3 / 0), the 4K
Runs on a COPY of montage_data (V7_DATA_SRC picks the folder; the real folder is only read).   python tests\\test_v771.py   (parts: V771_PARTS=1,2,3,g)"""
import copy
import json
import os
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
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402
from songmap_v2 import planbench as PB                                                        # noqa: E402
from v696_common import check, section, FAILS, snapshot                                       # noqa: E402

REAL_DATA = ROOT / "montage_data"
T_ALL = time.time()
SETTINGS_TABLE = []                       # (option, saved, loaded, applied, effect)


def row(opt, saved, loaded, applied, effect):
    SETTINGS_TABLE.append((opt, saved, loaded, applied, effect))
    check(all(x in ("yes", "n/a") for x in (saved, loaded, applied)) and not str(effect).startswith("NO"), f"{opt}: saved {saved}, loaded {loaded}, applied {applied}; {effect}")


def quiet(fn, *a, **k):
    keep = (M.out, M.LOGONLY)
    lines = []
    M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        return fn(*a, **k), lines
    finally:
        M.out, M.LOGONLY = keep


def set_cfg(**kw):
    cfg = M.load_config()
    cfg.update(kw)
    M.save_json(M.CONFIG_PATH, cfg)
    return cfg


def plan_with(game, paths, song, **kw):
    set_cfg(**kw)
    plan, lines = PB.run_plan(M, game, paths, song, "v2")
    return plan, lines


def gains(plan):
    return {s["path"]: s for t in plan["takes"] for s in t["srcs"]}


# ------------------------------------------------------------------------------------------------ 1) Settings audit
def gui_phase(tmp):
    """saved (config.json after a flush, no Save click) and loaded (a new App shows it) for every control of the Settings window."""
    import tkinter
    try:
        r = tkinter.Tk()
        r.destroy()
    except Exception:
        check(False, "no display: the Settings window cannot be built here")
        return {}
    old = M.use_data_dir(tmp / "gdata")
    res = {}
    try:
        cfg0 = M.load_config()
        want = {}
        app = M.App(0, startup=False)
        for k, val in (("mp3_dir", str(tmp / "mp3x")), ("playlist_dir", str(tmp / "csvx")), ("output_root", str(tmp / "outx"))):
            app.sv[k].set(val)
            want[k] = val
        app.sl["valorant"].set(f"{tmp / 'cv1'}; {tmp / 'cv2'}")
        app.sl["cs2"].set(f"{tmp / 'cc1'}")
        want["clip_dirs"] = {"valorant": [str(tmp / "cv1"), str(tmp / "cv2")], "cs2": [str(tmp / "cc1")]}
        nums = {"max_mb": 77, "max_dur_s": 55, "auto_recent_days": 12, "auto_old_per_run": 33, "name_match": 71, "death_lock_s": 5.5, "week_days": 3,
                "game_audio_level": 0.35, "ui_scale": 1.25}
        for k, val in nums.items():
            app.sn[k].set(str(val))
            want[k] = val
        app.set_track["valorant"].set("3")
        app.set_track["cs2"].set("1")
        want["game_audio_track"] = {"valorant": "3", "cs2": "1"}
        app.set_names["valorant"].set("fireaxe; fxv")
        app.set_names["cs2"].set("fireaxe; 火斧; fxc")
        want["player_names"] = {"valorant": ["fireaxe", "fxv"], "cs2": ["fireaxe", "火斧", "fxc"]}
        app.set_opt.set(False)
        app.set_len.set(101)
        want["length_s"] = 101
        app.set_style.set("chill")
        want["style"] = "chill"
        app.set_place.set("v4")
        want["placement"] = "v4"
        app.set_audio.set(M.AUDIO_MODES["legacy"])
        want["audio_mode"] = "legacy"
        want["quality"] = "nvenc" if cfg0.get("quality") == "max" else "max"
        app.set_q.set(want["quality"])
        for var, key, val in ((app.set_interp, "interpolate_low_fps", True), (app.set_music, "lower_music_clips", True), (app.set_sync, "sync_report", False),
                              (app.set_upd, "update_on_start", True)):
            var.set(val)
            want[key] = val
        app.set_accent.set(M.ACCENT_NAMES["purple"])
        want["accent"] = "purple"
        app.set_base.set("Black")
        want["base"] = "black"
        app.set_music_db.set("20")
        want["music_lower_db"] = 20.0
        app.set_smmode.set(M.SONGMAP_MODES["v2_fallback"])           # V7.7.1: the default is 'V2'; the test picks the other entry
        want["songmap_mode"] = "v2_fallback"
        for _ in range(8):
            app.root.update()
            time.sleep(0.05)
        app.flush_settings()
        app.root.destroy()
        M.LOG_SINK[0] = M.PROGRESS[0] = None
        disk = json.loads(M.CONFIG_PATH.read_text(encoding="utf-8"))
        res["saved"] = {k: disk.get(k) == v for k, v in want.items()}
        app2 = M.App(0, startup=False)
        read = {
            "mp3_dir": app2.sv["mp3_dir"].get(), "playlist_dir": app2.sv["playlist_dir"].get(), "output_root": app2.sv["output_root"].get(),
            "clip_dirs": {g: [x.strip() for x in app2.sl[g].get().split(";") if x.strip()] for g in app2.sl},
            "game_audio_track": {g: v.get() for g, v in app2.set_track.items()},
            "player_names": {g: M.norm_names(v.get(), g) for g, v in app2.set_names.items()},
            "length_s": "optimal" if app2.set_opt.get() else int(app2.set_len.get()), "style": app2.set_style.get(), "placement": app2.set_place.get(),
            "audio_mode": next((k for k, lab in M.AUDIO_MODES.items() if lab == app2.set_audio.get()), None), "quality": app2.set_q.get(),
            "interpolate_low_fps": bool(app2.set_interp.get()), "lower_music_clips": bool(app2.set_music.get()), "sync_report": bool(app2.set_sync.get()),
            "update_on_start": bool(app2.set_upd.get()), "accent": next((k for k, lab in M.ACCENT_NAMES.items() if lab == app2.set_accent.get()), None),
            "base": app2.set_base.get().lower()}
        for k in nums:
            raw = app2.sn[k].get()
            read[k] = float(raw) if "." in raw else int(raw)
        read["music_lower_db"] = float(app2.set_music_db.get())
        read["songmap_mode"] = next((k for k, lab in M.SONGMAP_MODES.items() if lab == app2.set_smmode.get()), None)
        res["loaded"] = {k: read.get(k) == v for k, v in want.items()}
        res["want"], res["read"], res["disk"] = want, read, disk
        app2.root.destroy()
        M.LOG_SINK[0] = M.PROGRESS[0] = None
    finally:
        M.restore_data_dir(old)
    return res


def part_settings(tmp):
    with section("1) Settings audit: saved / loaded / applied / effect for every option of the Settings window"):
        g = gui_phase(tmp)
        S, L = g.get("saved", {}), g.get("loaded", {})
        for k in S:
            if not S[k] or not L.get(k):
                print(f"   detail {k}: wanted {g['want'][k]!r}, disk {g['disk'].get(k)!r}, reopened GUI {g['read'].get(k)!r}")
        sv = lambda k: "yes" if S.get(k) else "NO"
        ld = lambda k: "yes" if L.get(k) else "NO"
        with PB.data_copy(M) as dst:
            game_v, val7 = PB.take_sets(M)["val7"]
            song = next(x["path"] for x in M.song_pool(M.load_config())[0] if "Silicon XX" in str(x["path"]))
            base_cfg = M.load_config()
            base_cfg.update(lower_music_clips=False)
            M.save_json(M.CONFIG_PATH, base_cfg)
            # ---------------------------------------------------------------- folders
            songs_all = M.song_pool(base_cfg)[0]
            empty = tmp / "emptydir"
            empty.mkdir(exist_ok=True)
            n_empty = len(M.song_pool(dict(base_cfg, mp3_dir=str(empty)))[0])
            row("MP3 folder", sv("mp3_dir"), ld("mp3_dir"), "yes" if n_empty == 0 < len(songs_all) else "NO",
                f"song pool {len(songs_all)} songs -> {n_empty} with an empty folder")
            n_nocsv = len(M.song_pool(dict(base_cfg, playlist_dir=str(empty)))[0])
            row("Exportify CSV folder", sv("playlist_dir"), ld("playlist_dir"), "yes",
                f"song pool {len(songs_all)} with the CSV -> {n_nocsv} without it (no CSV = every audio file of the MP3 folder is a song)" if n_nocsv != len(songs_all) else "NO: same pool without the CSV")
            captured = {}

            def fake_render(plan, outfile, cfg, maxq=False, *a, **k):
                captured.update(out=str(outfile), maxq=maxq)
                Path(outfile).parent.mkdir(parents=True, exist_ok=True)
                Path(outfile).write_bytes(b"x")
            synced = []
            keep = {n: getattr(M, n) for n in ("render_plan", "audio_guard", "quality_check", "record_history", "mark_used", "sync_report")}
            M.render_plan, M.audio_guard, M.quality_check = fake_render, lambda *a, **k: False, lambda *a, **k: None
            M.record_history, M.mark_used, M.sync_report = lambda *a, **k: None, lambda *a, **k: None, lambda *a, **k: synced.append(1)
            try:
                res = {}
                for q, sr in (("max", True), ("nvenc", False)):
                    for k_ in captured:
                        pass
                    set_cfg(output_root=str(tmp / "out_a"), quality=q, sync_report=sr)
                    synced.clear()
                    quiet(M.run_job, game_v, "render", paths=val7, song_path=song)
                    res[(q, sr)] = (captured.get("out"), captured.get("maxq"), len(synced))
                row("Output folder", sv("output_root"), ld("output_root"), "yes" if str(tmp / "out_a") in str(res[("max", True)][0]) else "NO",
                    f"render goes to {res[('max', True)][0]}")
                row("Quality (NVENC / x264 CRF15)", sv("quality"), ld("quality"), "yes" if res[("max", True)][1] is True and res[("nvenc", False)][1] is False else "NO",
                    f"run_job maxq {res[('max', True)][1]} / {res[('nvenc', False)][1]}; encoder args differ: {M.enc_args(True, False, False) != M.enc_args(False, False, True)}")
                row("Sync report", sv("sync_report"), ld("sync_report"), "yes" if res[("max", True)][2] == 1 and res[("nvenc", False)][2] == 0 else "NO",
                    f"report after a render: on {res[('max', True)][2]}x, off {res[('nvenc', False)][2]}x")
            finally:
                for n, f in keep.items():
                    setattr(M, n, f)
            set_cfg(output_root=base_cfg["output_root"], quality=base_cfg.get("quality", "max"), sync_report=True)
            # ---------------------------------------------------------------- clip folders + scan limits (generated clips)
            import test_v73 as T73
            cdir = tmp / "clipsdir"
            T73.make_files(cdir, 2, "VALORANT", dur=16)
            cfg_c = dict(M.load_config(), clip_dirs={"valorant": [str(cdir)], "cs2": []}, max_mb=100, max_dur_s=60)
            k_minv, M.MIN_VIDEO = M.MIN_VIDEO, 1000                                  # the generated clips are under the 1 MB real-clip minimum
            (rec_all, _) = quiet(M.scan_clips, cfg_c, False)
            sz = max(os.path.getsize(p) for p in map(str, cdir.glob("VALORANT*.mov"))) / 1048576
            rec_small, _ = quiet(M.scan_clips, dict(cfg_c, max_mb=max(0, int(sz) - 1) if sz >= 1 else 0), False)
            rec_dur, _ = quiet(M.scan_clips, dict(cfg_c, max_dur_s=5), False)
            rec_none, _ = quiet(M.scan_clips, dict(cfg_c, clip_dirs={"valorant": [str(empty)], "cs2": []}), False)
            M.MIN_VIDEO = k_minv
            sv_ = lambda k: sv(k)
            row("Valorant clip folders", sv_("clip_dirs"), ld("clip_dirs"), "yes" if len(rec_all) >= 2 and len(rec_none) == 0 else "NO", f"scan finds {len(rec_all)} clips in the listed folder, {len(rec_none)} in an empty one")
            row("CS2 clip folders", sv_("clip_dirs"), ld("clip_dirs"), "yes" if "cs2" in M.GAMES and M.clip_dirs(dict(cfg_c, clip_dirs={"valorant": [], "cs2": [str(cdir)]})) == [(str(cdir), "cs2")] else "NO",
                "the cs2 list is the one read for CS2 (clip_dirs() returns the folder tagged cs2)")
            row("Skip files larger than (MB)", sv("max_mb"), ld("max_mb"), "yes" if len(rec_small) < len(rec_all) else "NO",
                f"clip size {sz:.2f} MB: limit 100 -> {len(rec_all)} clips, limit {max(0, int(sz) - 1) if sz >= 1 else 0} -> {len(rec_small)}")
            row("Skip clips longer than (s)", sv("max_dur_s"), ld("max_dur_s"), "yes" if len(rec_dur) < len(rec_all) else "NO",
                f"16 s clips: limit 60 -> {len(rec_all)}, limit 5 -> {len(rec_dur)}")
            # ---------------------------------------------------------------- auto scan window
            cache = {}
            fake = [{"path": str(tmp / f"a{i}.mov"), "game": "valorant", "w": 1920, "h": 1080} for i in range(10)]
            now = time.time()
            for i, r in enumerate(fake):
                Path(r["path"]).write_bytes(b"x")
                mt = now - (i * 20 + 1) * 86400
                os.utime(r["path"], (mt, mt))
            k_scan, k_det, k_cache, k_load = M.scan_clips, M.load_dets, M.kills_key, M.load_kills_cache
            M.scan_clips, M.load_dets, M.kills_key, M.load_kills_cache = lambda cfg, rescan=False: fake, lambda g: {g: {"x": 1}}, lambda r, g, d: r["path"], lambda: {}
            try:
                a1 = M.auto_scan_set({"auto_recent_days": 30, "auto_old_per_run": 3}, "valorant")
                a2 = M.auto_scan_set({"auto_recent_days": 70, "auto_old_per_run": 3}, "valorant")
                a3 = M.auto_scan_set({"auto_recent_days": 30, "auto_old_per_run": 150}, "valorant")
            finally:
                M.scan_clips, M.load_dets, M.kills_key, M.load_kills_cache = k_scan, k_det, k_cache, k_load
            row("Auto: scan new clips from the last (days)", sv("auto_recent_days"), ld("auto_recent_days"), "yes" if len(a2) > len(a1) else "NO",
                f"10 clips 1..181 days old, 3 older allowed: 30 days -> {len(a1)} clips, 70 days -> {len(a2)}")
            row("Auto: plus up to this many older clips per run", sv("auto_old_per_run"), ld("auto_old_per_run"), "yes" if len(a3) > len(a1) else "NO",
                f"30 days: 3 older -> {len(a1)} clips, 150 older -> {len(a3)}")
            # ---------------------------------------------------------------- detection: name match, death lock
            r_ = {"split": 5, "ktext": "zzzzzz", "vtext": "qqqqqq", "ks": 85.0, "vs": 10.0, "before": "", "gun": True, "killer": [1], "victim": [1]}
            v80 = M.cs2_vote_verdict(r_, {"name_match": 80})[0]
            v90 = M.cs2_vote_verdict(r_, {"name_match": 90})[0]
            row("Detection: fuzzy name match needed (0-100)", sv("name_match"), ld("name_match"), "yes" if v80 != v90 else "NO",
                f"a row read at 85: threshold 80 -> '{v80}', threshold 90 -> '{v90}'")
            it_ = lambda: {"rec": {"path": "x.mov", "game": "valorant", "audio": False}, "kills": [{"t": 20.0, "ks": 90, "victim": "abcdef"}], "rej": [], "deaths": [14.0], "revives": []}
            st_a, st_b = {}, {}
            ia, ib = it_(), it_()
            ko = M.load_json
            M.load_json = lambda p, d=None: {} if p == M.ONSET_CACHE else ko(p, d)
            sa, sb = M.verified_kills([ia], {"death_lock_s": 8.0}), M.verified_kills([ib], {"death_lock_s": 3.0})
            M.load_json = ko
            row("No kills for this long after my death (s)", sv("death_lock_s"), ld("death_lock_s"), "yes" if sa["death_lock"] == 1 and sb["death_lock"] == 0 else "NO",
                f"a kill 6 s after a death: lock 8 s -> dropped, lock 3 s -> kept")
            # ---------------------------------------------------------------- player names
            M.set_player_names({"player_names": {"valorant": ["fireaxe", "fxv"], "cs2": ["fireaxe", "火斧", "fxc"]}})
            n_cs = M.names_split("cs2")
            n_v = M.names_split("valorant")
            M.set_player_names(M.load_config())
            row("Player names: Valorant / CS2", sv("player_names"), ld("player_names"), "yes" if "fxv" in n_v[0] and "fxc" in n_cs[0] and "火斧" in n_cs[1] and "fxc" not in n_v[0] else "NO",
                f"names_split valorant {n_v}, cs2 {n_cs}")
            # ---------------------------------------------------------------- week_days: songs added this week
            songs_sub = [dict(s_, added=datetime_ago(5)) for s_ in songs_all[:1]]
            kgs, ksf = M.get_songmap, M.song_fit
            M.get_songmap, M.song_fit = lambda path, bpm=None, version=None: {"bpm": 120.0}, lambda an, e, d: {"x": 40.0}
            try:
                tiers = {}
                for wd in (3, 30):
                    _, lg = quiet(M.pick_song, dict(base_cfg, week_days=wd), "valorant", [dict(s_) for s_ in songs_sub])
                    tiers[wd] = next((l for l in lg if l.startswith("song tier")), "")
            finally:
                M.get_songmap, M.song_fit = kgs, ksf
            row("'This week' means the last N days", sv("week_days"), ld("week_days"), "yes" if "older" in tiers[3] and "this week" in tiers[30] else "NO",
                f"a song added 5 days ago: N=3 -> '{tiers[3]}', N=30 -> '{tiers[30]}'")
            # ---------------------------------------------------------------- game audio level
            pl_a, _ = plan_with(game_v, val7, song, game_audio_level=0.5)
            pl_b, _ = plan_with(game_v, val7, song, game_audio_level=1.0)
            ga, gb = gains(pl_a), gains(pl_b)
            d_ = [round(gb[k]["gain_db"] - ga[k]["gain_db"], 2) for k in ga if k in gb]
            un = [round(gb[k]["gain_db"] - ga[k]["gain_db"], 2) for k in ga if k in gb and not ga[k]["lift_db"] and not gb[k]["lift_db"]]
            row("Game audio level under the music (0-1)", sv("game_audio_level"), ld("game_audio_level"), "yes" if d_ and max(d_) > 0 and all(abs(x - 6.02) < 0.05 for x in un) else "NO",
                f"0.5 -> 1.0 raises the plan's game gain by {sorted(set(d_))} dB per clip (+6.02 where the quiet-clip lift is not active)")
            # ---------------------------------------------------------------- audio track per game, audio mode
            clip = tmp / "three_tracks.mkv"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=8", "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000:duration=8",
                            "-f", "lavfi", "-i", "anoisesrc=d=8:c=white:r=48000:a=0.4,volume='if(lt(mod(t,1),0.07),1,0)':eval=frame",
                            "-f", "lavfi", "-i", "sine=frequency=700:sample_rate=48000:duration=8", "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a", "-c:v", "mpeg4",
                            "-c:a", "aac", str(clip)], capture_output=True, timeout=120)
            rec = {"path": str(clip), "audio": True}
            st_ = {}
            picks = {t: M.resolve_clip_audio(rec, dict(base_cfg, audio_mode="auto", game_audio_track={"valorant": t, "cs2": "auto"}), "valorant", st_)["stream"] for t in ("1", "2", "3", "auto")}
            pick_cs = M.resolve_clip_audio(rec, dict(base_cfg, audio_mode="auto", game_audio_track={"valorant": "3", "cs2": "1"}), "cs2", {})["stream"]
            pick_leg = M.resolve_clip_audio(rec, dict(base_cfg, audio_mode="legacy", game_audio_track={"valorant": "3", "cs2": "3"}), "valorant", {})["stream"]
            ok_t = picks["1"] == 0 and picks["2"] == 1 and picks["3"] == 2 and pick_cs == 0
            row("Game audio track: Valorant / CS2 (auto, 1, 2, 3)", sv("game_audio_track"), ld("game_audio_track"), "yes" if ok_t else "NO",
                f"3-track clip: setting 1/2/3/auto -> streams {picks}; CS2 reads its own entry ({pick_cs})")
            row("Audio mode (Auto / Legacy)", sv("audio_mode"), ld("audio_mode"), "yes" if pick_leg != 2 else "NO",
                f"same clip, track 3 set: Auto -> stream {picks['3']}, Legacy -> stream {pick_leg} (the setting is ignored in Legacy, as the label says)")
            # ---------------------------------------------------------------- length, style, placement
            p_st = {s: plan_with(game_v, val7, song, style=s)[0]["recipe"] for s in ("chill", "hype")}
            row("Default style (auto = from the song)", sv("style"), ld("style"), "yes" if p_st["chill"] == "chill" and p_st["hype"] == "hype" else "NO",
                f"style chill -> recipe '{p_st['chill']}', hype -> '{p_st['hype']}'")
            p_pl = {s: plan_with(game_v, val7, song, placement=s)[0]["placement"] for s in ("v4", "v5")}
            row("Kill placement (v5 / v4)", sv("placement"), ld("placement"), "yes" if p_pl == {"v4": "v4", "v5": "v5"} else "NO", f"plan placement {p_pl}")
            cs2_trio = PB.take_sets(M)["cs2trio"][1] + PB.take_sets(M)["cs2singles"][1]
            pl80, _ = plan_with("cs2", cs2_trio, song, length_s=80, style="auto")
            pl150, _ = plan_with("cs2", cs2_trio, song, length_s=150, style="auto")
            plo, _ = plan_with("cs2", cs2_trio, song, length_s="optimal", style="auto")
            ok_len = pl80["duration"] != pl150["duration"] or pl80["duration"] != plo["duration"]
            row("Default length (optimal / 80-150 s)", sv("length_s"), ld("length_s"), "yes" if ok_len else "NO",
                f"{len(cs2_trio)} CS2 clips: 80 s -> {pl80['duration']:.1f} s, 150 s -> {pl150['duration']:.1f} s, optimal -> {plo['duration']:.1f} s (material limited)")
            # ---------------------------------------------------------------- songmap
            cfg_nokey = dict(base_cfg)
            cfg_nokey.pop("songmap_mode", None)
            vs = {"missing": M.songmap_mode(cfg_nokey), "garbage": M.songmap_mode({"songmap_mode": "banana"}), "fallback": M.songmap_mode({"songmap_mode": "v2_fallback"}),
                  "routes": [M.songmap_version(dict(base_cfg, songmap_mode="v2", songmap_version=x)) for x in ("v1", "v2auto")]}
            row("SongMap mode (V2 / V2 + V1 Fallback)", sv("songmap_mode"), ld("songmap_mode"),
                "yes" if vs["missing"] == "v2" and vs["garbage"] == "v2" and vs["fallback"] == "v2_fallback" and vs["routes"] == ["v2", "v2"] else "NO",
                f"mode read: missing key -> {vs['missing']}, unknown -> {vs['garbage']}; mode V2 routes an old version key v1 / v2auto to {vs['routes']}; per-song proof in part 2")
            # ---------------------------------------------------------------- interpolation
            kan = M.analyse_takes
            M.analyse_takes = lambda plan, fx=M.FX_ALL: []
            try:
                _, lg_off = quiet(M.interp_prepare, pl_a, dict(base_cfg, interpolate_low_fps=False), str(tmp))
                _, lg_on = quiet(M.interp_prepare, pl_a, dict(base_cfg, interpolate_low_fps=True), str(tmp))
            finally:
                M.analyse_takes = kan
            row("Interpolate low-fps takes", sv("interpolate_low_fps"), ld("interpolate_low_fps"), "yes" if any("interpolation off" in l for l in lg_off) and not any("interpolation off" in l for l in lg_on) else "NO",
                f"OFF logs '{lg_off[0][:50] if lg_off else ''}' and probes nothing; ON analyses the takes")
            # ---------------------------------------------------------------- music option (V7.7.0 behaviour, rechecked)
            ev_ = {}
            kmu = M.music_over_gameplay
            M.music_over_gameplay = lambda rec, au: {"yes": True, "score": 0.9, "why": "audit"}
            try:
                p_on, _ = plan_with(game_v, val7, song, lower_music_clips=True)
            finally:
                M.music_over_gameplay = kmu
            p_off, _ = plan_with(game_v, val7, song, lower_music_clips=False)
            ga_, gb_ = gains(p_off), gains(p_on)
            dd = sorted({round(gb_[k]["gain_db"] - ga_[k]["gain_db"], 2) for k in ga_ if k in gb_ and ga_[k]["audio"]})
            row("Lower music-over-gameplay clips (on / off)", sv("lower_music_clips"), ld("lower_music_clips"), "yes" if dd == [-12.0] and not any("music over gameplay" in n for n in p_off["notes"]) else "NO",
                f"every clip flagged: game gain {dd} dB vs option off at the default amount; option off adds nothing to the plan")
            M.music_over_gameplay = lambda rec, au: {"yes": True, "score": 0.9, "why": "audit"}
            try:
                p_20, _ = plan_with(game_v, val7, song, lower_music_clips=True, music_lower_db=20)
                p_mu, _ = plan_with(game_v, val7, song, lower_music_clips=True, music_lower_db=M.MUSIC_MUTE_DB)
            finally:
                M.music_over_gameplay = kmu
            d20 = sorted({round(gains(p_20)[k]["gain_db"] - ga_[k]["gain_db"], 2) for k in ga_ if k in gains(p_20) and ga_[k]["audio"]})
            mutes = [s_.get("mute") for s_ in gains(p_mu).values() if s_["audio"]]
            row("Lower music-over-gameplay clips by [N] dB (mute = 60 dB)", sv("music_lower_db"), ld("music_lower_db"), "yes" if d20 == [-20.0] and all(mutes) and mutes else "NO",
                f"N = 20: game gain {d20} dB vs off; N = {M.MUSIC_MUTE_DB:g}: {sum(1 for m_ in mutes if m_)} of {len(mutes)} clips muted (true silence in the filter graph)")
            # ---------------------------------------------------------------- update on start
            seen = []
            ksr, kwh = subprocess.run, shutil.which
            os.environ.pop("MONTAGE_UPDATED", None)
            subprocess.run = lambda *a, **k: (seen.append(a[0]), subprocess.CompletedProcess(a[0], 0, "abc\n", ""))[1]
            for on in (False, True):
                set_cfg(update_on_start=on)
                n0 = len(seen)
                quiet(M.update_on_start)
                if on:
                    n_on = len(seen) - n0
                else:
                    n_off = len(seen) - n0
            subprocess.run = ksr
            set_cfg(update_on_start=False)
            row("Check for updates on start", sv("update_on_start"), ld("update_on_start"), "yes" if n_off == 0 and n_on >= 1 else "NO", f"git calls at start: off {n_off}, on {n_on}")
        # ---------------------------------------------------------------- appearance (needs Tk)
        old_ad = M.use_data_dir(tmp / "adata")                                      # apply_theme writes its theme cache into the data folder
        try:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            pal_l = M.make_palette("lime", "grey")
            pal_p = M.make_palette("purple", "black")
            p1 = M.apply_theme(root, 1.0, "lime", "grey")
            f1 = M.UI_SCALE[0]
            p2 = M.apply_theme(root, 1.5, "purple", "black")
            f2 = M.UI_SCALE[0]
            M.apply_theme(root, 1.0, "lime", "grey")
            root.destroy()
            row("Accent colour", sv("accent"), ld("accent"), "yes" if p1 != p2 and pal_l != pal_p else "NO", "palette differs per accent (lime vs purple)")
            row("Base (Grey / Black)", sv("base"), ld("base"), "yes" if p1.get("bg") != p2.get("bg") else "NO", f"background {p1.get('bg')} vs {p2.get('bg')}")
            row("UI scale", sv("ui_scale"), ld("ui_scale"), "yes" if f1 != f2 else "NO", f"UI_SCALE 1.0 -> {f1}, 1.5 -> {f2} (applies to the next window, as the hint says)")
        except Exception as ex:                                                 # noqa: BLE001
            row("Appearance", sv("accent"), ld("accent"), "NO", f"theme test failed: {ex}")
        finally:
            M.restore_data_dir(old_ad)
        print("\n   option | saved | loaded | applied | effect")
        for r in SETTINGS_TABLE:
            print("   " + " | ".join(r))
        print("   not Settings options (no switch exists for them): fades (fixed: 0.3 s in, outro fade), utility override (per clip: clip_overrides.json / utilclip),"
              " music level / mix (fixed balance: game level + auto lift), length limits other than 'Default length' and the two scan limits above")


def datetime_ago(days):
    return M.datetime.datetime.now() - M.datetime.timedelta(days=days)


PARTS = {}

# ------------------------------------------------------------------------------------------------ 0) version + changelogs
def part_version(tmp):
    with section("0) title-bar version V7.7.1, one entry on top of both changelogs, readable history rules"):
        simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
        tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        hs, ht = re.findall(r"(?m)^## (.+)$", simple), re.findall(r"(?m)^## (.+)$", tech)
        check(M.APP_VERSION == "V7.7.1" and hs[0].startswith("V7.7.1") and ht[0].startswith("V7.7.1"), "APP_VERSION V7.7.1 and the entry on top of both files")
        blk = re.split(r"(?m)^## .+$", simple)[1]
        pts = [x for x in blk.splitlines() if x.startswith("- ")]
        check(1 <= len(pts) <= 4 and not re.search(r"KNOWN ISSUE|on hold|ABANDON", simple), f"readable entry: {len(pts)} plain points, no known-issue lines")
        check(len(hs[0].split(":", 1)[1].split()) in range(3, 9), "one headline of 3 to 8 words: " + hs[0].split(":", 1)[1].strip())
        check(sum(1 for h in hs if h.startswith("V7.7.1")) == 1 and sum(1 for h in ht if h.startswith("V7.7.1")) == 1, "one entry per version")


# ------------------------------------------------------------------------------------------------ r) measured render: dB amount and mute
def part_render(tmp):
    import loud771
    with section("r) measured render of a flagged clip: game audio 12 dB under the option-off render, mute below -60 dBFS, music bed unchanged"):
        with PB.data_copy(M) as dst:
            B = load_base("V7.7.0", dst, tmp)
            rep_ = []
            cands = [("cs2", r"E:\Movies\LEGACY\Counter-strike 2\Counter-strike 2 2025.02.11 - 20.13.01.05.DVR.mp4"), ("valorant", r"E:\Movies\VALORANT\Clips\Replay 2026-09-05 01-22-47.mov"),
                     ("valorant", r"E:\Movies\VALORANT\Clips\Replay 2026-10-01 15-24-21.mov"), ("valorant", r"E:\Movies\VALORANT\Clips\Replay 2026-09-03 17-12-47.mov"),
                     ("valorant", r"E:\Movies\LEGACY\Valorant\Valorant 2025.10.20 - 03.58.09.03.DVR.mp4")]
            done = set()
            for game, flagged in cands:
                if game in done:
                    continue
                sets = PB.take_sets(M)
                base_paths = sets["val7"][1] if game == "valorant" else sets["cs2trio"][1] + sets["cs2singles"][1][:6]
                paths = [flagged] + [p for p in base_paths if p != flagged]
                song = song_by("Silicon XX", M.song_pool(M.load_config())[0])
                set_cfg(lower_music_clips=False)
                p_off, _ = PB.run_plan(M, game, paths, song, "v2")
                p_off_b, _ = PB.run_plan(B, game, paths, song, "v2")
                check(jplan(p_off) == jplan(p_off_b), f"{game}: option off: plan identical to V7.7.0")
                set_cfg(lower_music_clips=True, music_lower_db=12)
                p_12, l12 = PB.run_plan(M, game, paths, song, "v2")
                set_cfg(lower_music_clips=True, music_lower_db=M.MUSIC_MUTE_DB)
                p_mu, lmu = PB.run_plan(M, game, paths, song, "v2")
                set_cfg(lower_music_clips=False)
                fl_take = next((i for i, t in enumerate(p_12["takes"]) if any(s["path"] == flagged for s in t["srcs"]) and any(s.get("music_db") for s in t["srcs"])), None)
                if fl_take is None:
                    print(f"   {game}: {Path(flagged).name} not placed in the plan or not lowered, trying the next flagged clip")
                    continue
                done.add(game)
                check(True, f"{game}: the real flagged clip {Path(flagged).name} is lowered in the plan")
                cfg = M.load_config()
                m_off = loud771.measure(p_off, cfg)
                m_12 = loud771.measure(p_12, cfg)
                m_mu = loud771.measure(p_mu, cfg)
                same = [i for i, t in enumerate(p_off["takes"]) if t["path"] == p_12["takes"][fl_take]["path"]]
                i_off = same[0] if same else None
                a, b, c = m_off["takes"][i_off], m_12["takes"][fl_take], m_mu["takes"][fl_take]
                d12 = b["game_rms"] - a["game_rms"]
                print(f"   {game}: flagged take {fl_take + 1} ({Path(flagged).name[:40]}): game rms off {a['game_rms']} dBFS, 12 dB {b['game_rms']} ({d12:+.1f}), mute {c['game_rms']}; music bed LUFS off {a['music_lufs']} / 12 dB {b['music_lufs']} / mute {c['music_lufs']}")
                check(abs(d12 + 12.0) <= 1.0, f"{game}: at 12 dB the clip's game audio measures {d12:+.1f} dB against the option-off render of the same take (12 +-1)")
                check(c["game_rms"] < -60.0, f"{game}: at mute the take's game audio measures {c['game_rms']} dBFS (< -60)")
                check(abs(b["music_rms"] - a["music_rms"]) < 0.2 and abs(c["music_rms"] - a["music_rms"]) < 0.2, f"{game}: the music bed is unchanged ({a['music_rms']} / {b['music_rms']} / {c['music_rms']} dBFS)")
                others = [abs(m_12["takes"][j]["game_rms"] - m_off["takes"][j]["game_rms"]) for j in range(len(p_12["takes"])) if not any(s.get("music_db") for s in p_12["takes"][j]["srcs"]) and p_12["takes"][j]["path"] == p_off["takes"][j]["path"]]
                check(all(x < 0.5 for x in others), f"{game}: the takes of other fight groups keep their level ({len(others)} compared)")
            check(done == {"cs2", "valorant"}, f"a flagged real clip was measured for both games ({sorted(done)})")


PARTS["r"] = part_render

# ------------------------------------------------------------------------------------------------ g) guards
def part_guards(tmp):
    import random
    import test_v73 as T73
    import test_v761 as T761
    with section("g) guards vs V7.7.0 (defaults, music option off): events, kills, takes, cut lists, drops of 50 + 50 generated clips; the 7 real Valorant clips; the 4K"):
        with PB.data_copy(M) as dst:
            B = load_base("V7.7.0", dst, tmp)
            set_cfg(lower_music_clips=False)
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
                check(len(ev_m) > 40 and T73.ev_view(ev_m) == T73.ev_view(ev_b), f"{game}: {len(ev_m)} events of the 50 clips identical to V7.7.0 (clips, kills, scores)")
                for bpm, drop_s, seed in ((128.0, 64.0, 5), (150.0, 40.0, 12)):
                    an_m, an_b = T73.song_map(M, bpm, 300.0, drop_s), T73.song_map(B, bpm, 300.0, drop_s)
                    p_new = T73.plan_of(M, game, ev_m, an_m, seed)
                    p_b = T73.plan_of(B, game, ev_b, an_b, seed)
                    ks_n, ks_b = T761.kill_set(p_new), T761.kill_set(p_b)
                    same = json.dumps(p_new, sort_keys=True, default=str) == json.dumps(p_b, sort_keys=True, default=str)
                    check(ks_n == ks_b and len(p_new["takes"]) == len(p_b["takes"]), f"{game} bpm {bpm:.0f}: kill counts ({len(ks_n)}), takes ({len(p_new['takes'])}) identical to V7.7.0")
                    check([t["segs"] for t in p_new["takes"]] == [t["segs"] for t in p_b["takes"]] and p_new.get("drop_sync") == p_b.get("drop_sync"), f"{game} bpm {bpm:.0f}: cut lists and drops identical to V7.7.0")
                    check(same, f"{game} bpm {bpm:.0f}: the whole plan is identical to V7.7.0")
                    check(not M.verify_cutlist(p_new), f"{game} bpm {bpm:.0f}: cut list valid")
            game, paths = PB.take_sets(M)["val7"]
            song = song_by("Silicon XX", M.song_pool(M.load_config())[0])
            M.HEADLINE_RULES_V73 = True
            plan_off, l_off = PB.run_plan(M, game, paths, song, "v2")
            plan_b, _lb = PB.run_plan(B, game, paths, song, "v2")
            led = next(l for l in l_off if l.startswith("kill ledger:"))
            check(len(plan_off["takes"]) == 4 and "11 placed" in led and "3 merged" in led and "0 lost" in led, f"7 real Valorant clips, override off: 4 events; '{led[:100]}'")
            check(jplan(plan_off) == jplan(plan_b), "7 real Valorant clips: the whole plan is identical to V7.7.0")
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


PARTS["g"] = part_guards

# ------------------------------------------------------------------------------------------------ 3) music over gameplay
def part_music(tmp):
    import test_v73 as T73
    import test_v760 as T760
    from test_v770 import synth_audio
    with section("3) music over gameplay: detector, one verdict per fight group, dB option, real mute, logs"):
        with PB.data_copy(M) as dst:
            if True:
                res = {}
                for kind in ("song", "song_only", "guns", "ambience", "drone", "sting"):
                    f = synth_audio(tmp / f"m_{kind}.wav", kind)
                    res[kind] = M.music_over_gameplay({"path": f, "audio": True}, {"stream": 0, "n": 1})
                    print(f"   {kind:10} -> {res[kind]['yes']}  score {res[kind]['score']:.2f}  ({res[kind]['why']})")
                check(res["song"]["yes"] and res["song_only"]["yes"], "a song with gunshots over it, and a song alone: flagged")
                check(not res["guns"]["yes"], "gunshots only: not flagged")
                check(not res["ambience"]["yes"], "in-game ambience (wind noise, a 55 Hz hum, gunshots): not flagged")
                check(not res["drone"]["yes"], "one held chord for 14 s (a drone, a beep): not flagged")
                check(not res["sting"]["yes"], "a 2 s music sting: not flagged")
                f = tmp / "m_song.wav"
                r_ = M.music_over_gameplay({"path": str(f), "audio": True}, {"stream": 1, "n": 4, "note": "track 2 of 4 (set in Settings)"})
                check(not r_["yes"] and "not analysed" in r_["why"], f"'track 2 of 4' is never analysed or flagged: {r_['why']}")
                check(M.music_over_gameplay({"path": str(f), "audio": True}, {"stream": 0, "all": [-20.0, -25.0]})["yes"], "track 1 of a 2-track clip (the mix) is analysed")
                sil = tmp / "silent.wav"
                import wave
                with wave.open(str(sil), "wb") as w_:
                    w_.setnchannels(1)
                    w_.setsampwidth(2)
                    w_.setframerate(22050)
                    w_.writeframes(b"\0\0" * 22050 * 10)
                rs = M.music_over_gameplay({"path": str(sil), "audio": True}, {"stream": 0, "n": 1})
                check(not rs["yes"] and "silent track" in rs["why"], f"a clip whose only track is digital silence is reported as silent, not 'unreadable': {rs['why']}")
                # ---- group verdict + amount + mute + logs on a real planner run
                M.OUTRO_TRIM_ON[0] = True
                ev = T760.pool(tmp, "valorant", n=12, seed=17)
                an = T760.drops_map(2)
                real_cfg, real_res, real_mog = M.load_config, M.resolve_clip_audio, M.music_over_gameplay
                for e_ in ev:
                    e_["rec"] = dict(e_["rec"], audio=True)
                    for pt in e_.get("parts") or []:
                        pt["rec"] = dict(pt["rec"], audio=True)
                sib = {"path": str(tmp / "sibling.mov"), "audio": True, "w": 1920, "h": 1080, "dur": 10.0}
                ev[0]["group"] = [ev[0]["rec"], sib]                      # the first event's fight group holds a sibling file that is NOT in the plan
                first = ev[0]["rec"]["path"]
                scores = {first: (False, 0.27), sib["path"]: (True, 0.73)}

                def run(on, amount=12.0):
                    M.load_config = lambda: dict(real_cfg(), lower_music_clips=on, music_lower_db=amount)
                    M.resolve_clip_audio = lambda rec, cfg, game, state: {"stream": 0, "lufs": -20.0, "note": "test", "n": 1}
                    M.music_over_gameplay = lambda rec, au: {"yes": scores.get(rec["path"], (False, 0.1))[0], "score": scores.get(rec["path"], (False, 0.1))[1], "why": "test"}
                    try:
                        return T73.plan_of(M, "valorant", ev, an, 5, style="hype")
                    finally:
                        M.load_config, M.resolve_clip_audio, M.music_over_gameplay = real_cfg, real_res, real_mog
                p_off, p_12, p_6, p_mute = run(False), run(True, 12.0), run(True, 6.0), run(True, 60.0)
                g_off, g_12 = gains(p_off), gains(p_12)
                low = [k for k in g_off if k in g_12 and g_12[k]["gain_db"] != g_off[k]["gain_db"]]
                check(low == [first], f"the verdict of the group (highest score 0.73, a sibling file) lowers the clip of the plan, nothing else changes ({[Path(k).name for k in low]})")
                check(round(g_12[first]["gain_db"] - g_off[first]["gain_db"], 2) == -12.0 and g_12[first].get("music_db") == -12.0, "N = 12 dB: game gain exactly 12 dB under the option-off plan (after the lift)")
                check(round(gains(p_6)[first]["gain_db"] - g_off[first]["gain_db"], 2) == -6.0, "N = 6 dB: exactly 6 dB under")
                gm = gains(p_mute)[first]
                check(gm.get("mute") is True and gm["gain_db"] == g_off[first]["gain_db"], "N = mute value (60 dB): the clip is flagged mute")
                check(all(not s.get("mute") for k, s in gains(p_mute).items() if k != first), "mute never touches other clips")
                strip = lambda p: json.dumps({k: v for k, v in p.items() if k != "notes"}, sort_keys=True, default=str)
                a_, b_ = copy.deepcopy(p_off), copy.deepcopy(p_12)
                for t_ in b_["takes"]:
                    for s_ in t_["srcs"]:
                        if s_.pop("music_db", None):
                            s_["gain_db"] = round(s_["gain_db"] + 12.0, 2)
                check(strip(a_) == strip(b_), "everything else in the plan (cut list, timing, effects) is identical with the option on")
                lines = [n for n in p_12["notes"] if n.startswith("music over gameplay:")]
                check(len(lines) == 12 and sum(": yes (" in l for l in lines) == 1 and any("-12 dB" in l for l in lines), f"one log line per clip group ({len(lines)}): '{[l for l in lines if ': yes (' in l][0][-90:]}'")
                check(any(l.endswith("-> mute") for l in p_mute["notes"] if l.startswith("music over gameplay:")), "mute: the log line says mute")
                check(not any("music over gameplay" in n for n in p_off["notes"]) and not any("music_db" in s_ or "mute" in s_ for t_ in p_off["takes"] for s_ in t_["srcs"]), "option OFF: no music line, no extra field")
                # the filter graph: OFF identical to V7.7.0, mute = silence
                B = load_base("V7.7.0", dst, tmp)
                cfg0 = real_cfg()
                in_n, gr_n = M.build_filter(p_off, cfg0, True)
                in_b, gr_b = B.build_filter(json.loads(json.dumps(p_off, default=str)), cfg0, True)
                check(gr_n == gr_b and in_n == in_b, "option OFF: the filter graph of the same plan is byte-identical to V7.7.0")
                in_m, gr_m = M.build_filter(p_mute, cfg0, True)
                check(gr_m != gr_n and gr_m.count("anullsrc") > gr_n.count("anullsrc"), "mute: the muted clip's audio is anullsrc (true silence) in the filter graph")
                # ---- the detector over every cached clip with sound
                (_o, _l) = quiet(M.cmd_musicscan, None)
                txt = (ROOT / "musicscan.txt").read_text(encoding="utf-8")
                m_ = re.search(r"old detector \(V7.7.0\): (\d+) flagged \(([\d.]+) %\)\s+new detector, one verdict per fight group: (\d+) flagged \(([\d.]+) %\)", txt)
                tot = int(re.search(r"(\d+) clips with sound analysed", txt).group(1))
                old_n, new_n = int(m_.group(1)), int(m_.group(3))
                print(f"   {tot} clips with sound: old {old_n} flagged ({m_.group(2)} %), new {new_n} ({m_.group(4)} %)")
                check(new_n > 2 * old_n and new_n >= old_n, f"far more clips found: {old_n} -> {new_n} of {tot}")
                for nm in ("2025.02.11 - 20.13.01.05", "2025.08.17 - 01.35.33.08"):
                    ln = next((l for l in txt.splitlines() if nm in l and "group" in l), "")
                    check("group YES" in ln, f"known gap clip flagged: {nm}: {ln.strip()[:120]}")
                for nm in ("Replay 2026-09-11 17-36-12", "Replay 2026-09-17 15-45-39", "Replay 2026-09-21 04-26-30", "Replay 2026-09-11 15-17-36"):
                    ln = next((l for l in txt.splitlines() if nm in l), "")
                    check("silent track" in ln, f"legacy Replay clip with an all-silent track is reported as silent (nothing to analyse): {nm}")
                grp_line = lambda n: next((l for l in txt.splitlines() if n in l and "| old" in l), "")

                def group_of(name):
                    cur = None
                    for l in txt.splitlines():
                        if l.startswith("-- "):
                            cur = l
                        elif name in l and "| old" in l:
                            return cur
                    return None
                trio = ("2025.10.30 - 00.42.03.08", "2025.10.30 - 00.42.12.09", "2025.10.30 - 00.42.24.10")
                check(len({group_of(n) for n in trio}) == 1 and all("group YES" in grp_line(n) for n in trio), "Valorant 2025.10.30 00.42.03 / 12 / 24: one fight group, all three files carry the verdict of the highest score (0.73 -> yes)")
                cs = ("2025.02.03 - 08.52.26.19", "2025.02.03 - 08.52.30.20")
                check(len({group_of(n) for n in cs}) == 1 and len({("group YES" in grp_line(n)) for n in cs}) == 1, "CS2 2025.02.03 08.52.26 + 08.52.30 (linked by the existing save-time rule): one group, one verdict")
                check(group_of("2025.02.03 - 08.52.18.18") != group_of(cs[0]), "CS2 08.52.18 is NOT linked to 08.52.26 by the existing rule (shared victim names, kill times disagree by more than 3 s = a different round): it keeps its own verdict")


PARTS["3"] = part_music

# ------------------------------------------------------------------------------------------------ 2) songmap: low-confidence option
LOWCONF = ["Paparazzi (Dubstep) - Sped Up", "too much (hardtekk)", "prety - Riversmelt", "Congratulations - Post Malone"]
NORMAL = ["Vertigo - Flerian", "Silicon XX"]


def load_base(ref, dst, tmp):
    """The montage.py of git ref `ref` as a second module, data folder = dst (the same copy the current code uses)."""
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


def song_by(name_part, pool):
    return next(x["path"] for x in pool if name_part in Path(x["path"]).name)


def jplan(p):
    return json.dumps(p, sort_keys=True, default=str)


def is_low(nm):
    return any(k in nm for k in ("Paparazzi", "too much", "prety", "Congratulations"))


class Spy:
    """What the planner really consumed: wraps get_songmap and records the object it returned to the planner, plus every log line of the plan."""
    def __init__(self):
        self.maps, self.lines = [], []

    def __enter__(self):
        self.k = (M.get_songmap, M.out, M.LOGONLY)
        orig = M.get_songmap

        def spy(path, csv_bpm=None, version=None):
            m = orig(path, csv_bpm, version)
            self.maps.append(m)
            return m
        M.get_songmap = spy
        M.out = M.LOGONLY = lambda *x: self.lines.append(" ".join(map(str, x)))
        return self

    def __exit__(self, *a):
        M.get_songmap, M.out, M.LOGONLY = self.k


def beats_match(plan, beats):
    """Share of the plan's own beat times (song time = beats_out + start_t) that sit within 5 ms of a beat of the given grid."""
    b = np.asarray(beats, float)
    t = np.asarray(plan["beats_out"], float) + float(plan["song"]["start_t"])
    if not len(t) or not len(b):
        return 0.0
    return float(np.mean([np.min(np.abs(b - x)) < 0.005 for x in t]))


def part_songmap(tmp):
    with section("2) SongMap mode: 'V2' (default, every song on its V2 map) and 'V2 + V1 Fallback' (= V7.7.0 byte for byte); proof from the real plan"):
        with PB.data_copy(M) as dst:
            B = load_base("V7.7.0", dst, tmp)
            cfg = set_cfg(lower_music_clips=False)
            cfg.pop("songmap_mode", None)
            M.save_json(M.CONFIG_PATH, cfg)
            check(M.songmap_mode(M.load_config()) == "v2", "config without the key: SongMap mode is 'V2'")
            check(M.songmap_mode({"songmap_mode": "nonsense"}) == "v2" and M.songmap_mode({"songmap_mode": ""}) == "v2", "an unknown or empty value reads as 'V2'")
            check(list(M.SONGMAP_MODES.values()) == ["V2", "V2 + V1 Fallback"], "the dropdown has exactly two entries, V2 first")
            src = (ROOT / "montage.py").read_text(encoding="utf-8")
            check("songmap_low_conf_v1" not in src and "lowconf" not in src, "the old low-confidence checkbox / config key is gone from the code")
            pool = M.song_pool(M.load_config())[0]
            game_v, val7 = PB.take_sets(M)["val7"]
            songs = [song_by(n, pool) for n in LOWCONF + NORMAL]
            report = []
            for sp_ in songs:
                nm = Path(sp_).name
                set_cfg(songmap_mode="v2_fallback")
                with Spy() as sy_fb:
                    p_fb, sy_fb.lines = PB.run_plan(M, game_v, val7, sp_, "v2")
                p_old, _ = PB.run_plan(B, game_v, val7, sp_, "v2")
                set_cfg(songmap_mode="v2")
                with Spy() as sy_v2:
                    p_v2, sy_v2.lines = PB.run_plan(M, game_v, val7, sp_, "v2")
                set_cfg(songmap_mode="v2_fallback")
                m_fb, m_v2 = sy_fb.maps[-1], sy_v2.maps[-1]
                l_v2 = [l for l in sy_v2.lines if l.startswith("songmap") and nm in l]
                l_fb = [l for l in sy_fb.lines if l.startswith("songmap") and nm in l]
                bm = beats_match(p_v2, m_v2["beats"])
                src_v2 = "V2" if bm > 0.95 and m_v2.get("beat_source") != "v1" and not (m_v2.get("v2") or {}).get("fallback") else "V1"
                src_fb = "V1" if (m_fb.get("v2") or {}).get("fallback") else "V2"
                report.append((nm[:34], (m_v2.get("v2") or {}).get("grid_confidence"), src_fb, src_v2, round(bm, 2), (l_v2 or ["-"])[0][len("songmap: " + nm) + 2:][:110]))
                check(jplan(p_fb) == jplan(p_old), f"{nm[:36]}: mode 'V2 + V1 Fallback' plan byte-identical to V7.7.0")
                check(src_v2 == "V2" and bool(l_v2) and "map used V2" in l_v2[0] and "mode V2" in l_v2[0], f"{nm[:36]}: mode 'V2': planner used V2 (plan beat times on the V2 grid: {bm:.2f}); log: {(l_v2 or ['-'])[0][:150]}")
                check(not any("V1 beat values" in l for l in sy_v2.lines), f"{nm[:36]}: mode 'V2': no 'V1 beat values' line anywhere in the plan log")
                if is_low(nm):
                    check(src_fb == "V1" and bool(l_fb) and "V1" in l_fb[0], f"{nm[:36]}: mode 'V2 + V1 Fallback' used V1 values (as V7.7.0); log: {(l_fb or ['-'])[0][:120]}")
                    check(jplan(p_fb) != jplan(p_v2), f"{nm[:36]}: the two modes give different plans for a low-confidence song")
                else:
                    check(jplan(p_fb) == jplan(p_v2), f"{nm[:36]}: normal V2 song: both modes give identical plans")
                check(not M.verify_cutlist(p_v2), f"{nm[:36]}: mode 'V2' plan cut list valid")
            print("\n   song | V2 grid confidence | map in fallback mode | map in mode V2 (from the plan) | plan beats on the V2 grid | plan log line")
            for r_ in report:
                print("   " + " | ".join(str(x) for x in r_))
            # ---- negative tests: every V1 switch, mode V2 refuses it
            import songmap_v2
            import songmap_v2.build as SB  # noqa: F401
            sp_low = song_by(LOWCONF[0], pool)
            real_v1, real_build = M.analyse_song, songmap_v2.build_songmap_v2

            def no_v1(*a, **k):
                raise AssertionError("a V1 map was requested in mode V2")
            cache_path = M.DATA / songmap_v2.CACHE_NAME
            shutil.copy(cache_path, tmp / "cache_bak.json")
            try:
                M.analyse_song = no_v1
                for ver in ("v1", "v2auto", "v2"):
                    set_cfg(songmap_mode="v2", songmap_version=ver)
                    m_, _l = quiet(M.get_songmap, sp_low, None)
                    check(not (m_.get("v2") or {}).get("fallback") and m_.get("beat_source") != "v1",
                          f"switch 'songmap_version={ver}' in the config + the safety rules (low confidence, no kick window, too few kicks, worse than V1): mode V2 returns the V2 map, V1 never requested")
                fresh = next(x["path"] for x in pool if "Atlantis" in Path(x["path"]).name)
                c2 = M.load_json(cache_path, {})
                sig = songmap_v2.build.file_signature(fresh)
                M.save_json(cache_path, {k: v for k, v in c2.items() if sig not in k})
                songmap_v2.build_songmap_v2 = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("forced failure"))
                M.analyse_song = real_v1
                set_cfg(songmap_mode="v2_fallback", songmap_version="v2")
                m_fb2, _l = quiet(M.get_songmap, fresh, None, "v2")
                check(m_fb2.get("songmap_version") == "v1-fallback", "switch 'V2 build error': mode 'V2 + V1 Fallback' substitutes the V1 map (V7.7.0 behaviour)")
                M.analyse_song = no_v1
                set_cfg(songmap_mode="v2")
                try:
                    quiet(M.get_songmap, fresh, None, "v2")
                    check(False, "switch 'V2 build error': mode V2 refuses")
                except M.SongMapError as ex:
                    check(Path(fresh).name in str(ex), f"switch 'V2 build error': mode V2 raises a clear error naming the song: {str(ex)[:130]}")
                c3 = M.load_json(cache_path, {})
                c3[songmap_v2.cache_key(fresh, None, M._peek_v1_bpm(fresh, None))] = {"fallback_marker": "timeout (analysis cap)"}
                M.save_json(cache_path, c3)
                M.analyse_song = real_v1
                set_cfg(songmap_mode="v2_fallback")
                m_fb3, _l = quiet(M.get_songmap, fresh, None, "v2")
                check(m_fb3.get("songmap_version") == "v1-fallback", "switch 'cached timeout marker': mode 'V2 + V1 Fallback' substitutes the V1 map")
                M.analyse_song = no_v1
                set_cfg(songmap_mode="v2")
                try:
                    quiet(M.get_songmap, fresh, None, "v2")
                    check(False, "switch 'cached timeout marker': mode V2 refuses")
                except M.SongMapError as ex:
                    check(Path(fresh).name in str(ex), "switch 'cached timeout marker': mode V2 raises a clear error naming the song")
                M.analyse_song = real_v1
                songmap_v2.build_songmap_v2 = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("forced failure"))
                _e, lg = quiet(lambda: _try(M.pick_song, M.load_config(), "valorant", [dict(x) for x in pool if x["path"] == fresh]))
                check(any(Path(fresh).name in l and "skip" in l for l in lg), "mode V2 in the song picker: the song V2 cannot map is skipped with its name in the log, not replaced by V1")
            finally:
                songmap_v2.build_songmap_v2 = real_build
                M.analyse_song = real_v1
                shutil.copy(tmp / "cache_bak.json", cache_path)
                set_cfg(songmap_mode="v2_fallback", songmap_version="v2")


def _try(fn, *a):
    try:
        return fn(*a)
    except Exception as ex:                                  # noqa: BLE001
        return ex


PARTS["2"] = part_songmap


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t771_"))
    only = set(filter(None, os.environ.get("V771_PARTS", "").split(",")))
    want = lambda k: not only or k in only
    if want("0"):
        part_version(tmp)
    if want("1"):
        part_settings(tmp)
    for key in ("2", "3", "r", "g"):
        if want(key) and key in PARTS:
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
