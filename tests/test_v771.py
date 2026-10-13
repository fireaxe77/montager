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
        app.set_songmap.set(M.SONGMAP_CHOICES_UI["v1"])
        want["songmap_version"] = "v1"
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
        app.set_smmode.set(M.SONGMAP_MODES["v2"])                    # V7.7.1: default 'V2 + V1 Fallback'
        want["songmap_mode"] = "v2"
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
            "songmap_version": next((k for k, lab in M.SONGMAP_CHOICES_UI.items() if lab == app2.set_songmap.get()), None),
            "audio_mode": next((k for k, lab in M.AUDIO_MODES.items() if lab == app2.set_audio.get()), None), "quality": app2.set_q.get(),
            "interpolate_low_fps": bool(app2.set_interp.get()), "lower_music_clips": bool(app2.set_music.get()), "sync_report": bool(app2.set_sync.get()),
            "update_on_start": bool(app2.set_upd.get()), "accent": next((k for k, lab in M.ACCENT_NAMES.items() if lab == app2.set_accent.get()), None),
            "base": app2.set_base.get().lower()}
        for k in nums:
            raw = app2.sn[k].get()
            read[k] = float(raw) if "." in raw else int(raw)
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
            calls = []
            kb = {n: getattr(M, n) for n in ("get_songmap",)}
            vs = {v: M.songmap_version(dict(base_cfg, songmap_version=v)) for v in ("v1", "v2")}
            row("Songmap version (V1 / V2)", sv("songmap_version"), ld("songmap_version"), "yes" if vs == {"v1": "v1", "v2": "v2"} else "NO", f"songmap_version(cfg) -> {vs}; get_songmap dispatches on it")
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
            row("Lower clips that already have music playing", sv("lower_music_clips"), ld("lower_music_clips"), "yes" if dd == [-12.0] else "NO",
                f"every clip flagged: game gain {dd} dB vs option off (the amount becomes a Settings value in this version)")
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


def map_used(m):
    v2 = m.get("v2") or {}
    return "V1 values" if (v2.get("fallback") or m.get("beat_source") == "v1") else "V2 grid"


def part_songmap(tmp):
    with section("2) SongMap mode dropdown: 'V2 + V1 Fallback' (= V7.7.0 byte for byte) and 'V2' (every song on its V2 map)"):
        with PB.data_copy(M) as dst:
            B = load_base("V7.7.0", dst, tmp)
            cfg = set_cfg(lower_music_clips=False)
            cfg.pop("songmap_mode", None)
            M.save_json(M.CONFIG_PATH, cfg)
            check(M.songmap_mode(cfg) == "v2_fallback" and list(M.SONGMAP_MODES.values()) == ["V2 + V1 Fallback", "V2"], "default mode is 'V2 + V1 Fallback'; the dropdown offers exactly two entries")
            pool = M.song_pool(M.load_config())[0]
            game_v, val7 = PB.take_sets(M)["val7"]
            songs = [song_by(n, pool) for n in LOWCONF + NORMAL]
            for sp_ in songs:
                nm = Path(sp_).name
                set_cfg(songmap_mode="v2_fallback")
                p_fb, l_fb = PB.run_plan(M, game_v, val7, sp_, "v2")
                p_old, _ = PB.run_plan(B, game_v, val7, sp_, "v2")
                m_fb, _ = quiet(M.get_songmap, sp_, None, "v2")
                set_cfg(songmap_mode="v2")
                p_v2, l_v2 = PB.run_plan(M, game_v, val7, sp_, "v2")
                m_v2, _ = quiet(M.get_songmap, sp_, None, "v2")
                set_cfg(songmap_mode="v2_fallback")
                check(jplan(p_fb) == jplan(p_old), f"{nm[:40]}: mode 'V2 + V1 Fallback' plan byte-identical to V7.7.0")
                check(map_used(m_v2) == "V2 grid", f"{nm[:40]}: mode 'V2' uses the V2 map (fallback mode used: {map_used(m_fb)}, grid confidence {(m_v2.get('v2') or {}).get('grid_confidence')})")
                if is_low(nm):
                    check(map_used(m_fb) == "V1 values", f"{nm[:40]}: the fallback mode really used V1 values here")
                    check(jplan(p_fb) != jplan(p_v2) or m_fb["beats"] == m_v2["beats"], f"{nm[:40]}: mode 'V2' gives its own plan / beats")
                else:
                    check(jplan(p_fb) == jplan(p_v2), f"{nm[:40]}: normal V2 song: both modes give the same plan")
                check(any(l.startswith("songmap:") and nm in l for l in l_v2), "the plan log names the map used")
                check(not M.verify_cutlist(p_v2), f"{nm[:40]}: mode 'V2' plan cut list valid")


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
    if want("1"):
        part_settings(tmp)
    for key in ("2", "3", "g"):
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
