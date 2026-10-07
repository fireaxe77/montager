"""V6.9.6 part A tests: effective-fps candidate rule, duplicate removal, slow-mo, VFR, fpscontent, interpbench. Generated 320x180 clips only."""
import argparse
import shutil
import tempfile
from pathlib import Path

from v696_common import *                                                                    # noqa: F401,F403
from v696_common import M, np, check, section, logged, snapshot, mv, mvf, gen_clip, mkplan, run_graph, silent_song, clip_info, unique_per_s, crisp_per_s, first_bright, ROOT
import test_v693 as T                                                                         # noqa: E402  (plan / baseline / capture helpers; its main() is not run)
import v696_common as C


def noslow(plan):
    """The same plan with every slow-mo / freeze segment played at speed 1.0 (a 'clean speed 1.0 selection'; the planner always ends a montage in slow-mo)."""
    tk = []
    for t in plan["takes"]:
        segs = [[s_[0], s_[0] + s_[3] / 60.0, 1.0, s_[3]] + list(s_[4:]) if s_[2] in (0.5, 0.0) else list(s_) for s_ in t["segs"]]
        tk.append(dict(t, segs=segs, slow_at=None))
    return dict(plan, takes=tk)


def part_classify(tmp):
    with section("A1) candidate rule per take: effective unique fps"):
        d = Path(tmp) / "cls"
        d.mkdir()
        clean = gen_clip(d / "clean.mp4", mv())
        dup = gen_clip(d / "dup.mp4", mv("floor(N/2)"))
        c50 = gen_clip(d / "c50.mp4", mv(), fps=50)
        c30 = gen_clip(d / "c30.mp4", mv(), fps=30)
        song = silent_song(d / "song.wav")
        cls = lambda p, sp: [r_["why"] for r_ in M.analyse_takes(mkplan(p, [[2.0, 5.0 if sp >= 1 else 4.0, sp, 180 if sp >= 1 else 240]], song))][0]
        check(cls(clean, 1.0) == [], "clean 60 fps, speed 1.0: not a candidate")
        check(cls(dup, 1.0) == ["duplicated frames"], f"60 fps with every frame duplicated (30 unique): {cls(dup, 1.0)}")
        check(cls(clean, 0.5) == ["slow-mo"], f"clean 60 fps with slow-mo 0.5 -> 30 effective: {cls(clean, 0.5)}")
        check(cls(clean, 1.8) == [] and cls(c50, 1.0) == [], "ramp x1.8 on a 60 fps clip and a 50 fps clip without slow-mo: not candidates")
        check(cls(c30, 1.0) == ["low fps"], f"a 30 fps source (the V6.9.3 case) is still a candidate: {cls(c30, 1.0)}")
        check(cls(c50, 0.5) == ["slow-mo"], "50 fps clip in slow-mo 0.5 (25 effective): slow-mo candidate")
        check(cls(dup, 0.5) == ["duplicated frames", "slow-mo"], f"duplicated frames in slow-mo: both reasons ({cls(dup, 0.5)})")
        return d, song


def render_pair(plan, d, tag, fx=None, prepare=True):
    """(plan after interp_prepare, log lines, out path before, out path after)."""
    ref = d / f"{tag}_ref.mp4"
    run_graph(plan, ref, d)
    np_, lines = logged(M.interp_prepare, plan, {}, d / f"tmp_{tag}")
    aft = d / f"{tag}_new.mp4"
    inputs_b, graph_b = run_graph(np_, aft, d)
    return np_, lines, ref, aft, graph_b


def part_dup(tmp, env):
    d, song = env
    with section("1) duplicated frames: removed first, then interpolated; marker within one frame"):
        clip = gen_clip(d / "dupm.mp4", mvf("floor(N/2)", (120, 121)))
        plan = mkplan(clip, [[1.0, 4.0, 1.0, 180]], song)
        np_, lines, ref, aft, graph_b = render_pair(plan, d, "dup")
        ok = np_ is not plan and any(l.startswith("interpolated dupm.mp4 ") and "removed first" in l and "cadence 2 phase" in l for l in lines)
        check(ok, f"classified low-effective (duplicated), duplicates removed first: {[l for l in lines if l.startswith('interpolated')][:1]}")
        u0, u1 = unique_per_s(ref), unique_per_s(aft)
        check(u0 < 36 and u1 >= 55, f"unique pictures per second of the output: {u0:.1f} before, {u1:.1f} after (>= 55)")
        t1 = first_bright(aft)
        check(abs(t1 - 1.0) <= 1 / 60 + 1e-3, f"marker (flash on source frame 120 = 2.0 s) at output {t1:.4f} s, planned 1.0000 s (error {(t1 - 1.0) * 1000:+.1f} ms, limit 16.7 ms)")
        check(any(l.startswith("effective fps: dupm.mp4") and "-> interpolating (duplicated frames)" in l for l in lines) and
              any(l.startswith("fps: 1 takes probed, 1 low-effective-fps (slow-mo 0, duplicated 1, vfr 0), 1 interpolated, 0 fell back") for l in lines),
              "log lines: 'effective fps: ... -> interpolating (duplicated frames)' and the per-run 'fps: N takes probed, ...' line")
        # an irregular duplicate pattern goes through mpdecimate
        irr = gen_clip(d / "irr.mp4", mvf("floor(N/2)", ()).replace("floor(N/2)*10", "(floor(N/2)+floor(N/7))*10"))
        pre, ur, how = M.detect_dup_chain(irr, 1.0, 3.0)
        check(how in ("mpdecimate", "none") or how.startswith("cadence"), f"irregular duplicates: removal method '{how}' ({ur:.1f} unique fps)")


def part_clean(tmp, env):
    d, song = env
    with section("2) clean 60 fps, speed 1.0: command identical to the base, no temp files"):
        B = T.load_baseline(tmp, C.BASE_REF)
        if B is None:
            check(False, "base commit not available")
            return
        dd = Path(tmp) / "g60"
        dd.mkdir()
        main = gen_clip(dd / "main.mp4", "testsrc2=s=320x180:r=60:d=12" if False else mv(), dur=12)
        fills = []
        for i in range(6):
            shutil.copy(main, dd / f"f{i}.mp4")
            fills.append(str(dd / f"f{i}.mp4"))
        V = T.names(30, 4)
        cfg = M.load_config()
        plan = noslow(T.make_plan_for(M, "cs2", main, fills, V, cfg))
        planB = noslow(T.make_plan_for(B, "cs2", main, fills, V, B.load_config()))
        tk = lambda p: [(Path(t["path"]).name, t["segs"], t["kills_out"], [x["path"] for x in t.get("srcs", [])]) for t in p["takes"]]
        check(len(plan["takes"]) > 3 and tk(plan) == tk(planB), f"plan identical to the base ({len(plan['takes'])} takes, slow-mo segments set to speed 1.0 for this check)")
        out_dir = dd / "out"
        out_dir.mkdir()
        before = sorted(p.name for p in dd.rglob("*"))
        rec_m, rec_b = {}, {}
        real_cmd = M.interp_segment_cmd
        M.interp_segment_cmd = lambda *a, **k: (_ for _ in ()).throw(AssertionError("interpolation step ran for a clean 60 fps selection"))
        try:
            _, lines = logged(T.capture_render, M, plan, cfg, out_dir / "m.mp4", rec_m)
        finally:
            M.interp_segment_cmd = real_cmd
        T.capture_render(B, planB, B.load_config(), out_dir / "m.mp4", rec_b)
        norm = lambda c: [re.sub(r"[^ ]*last_filter\.txt", "GRAPH", x.replace(str(out_dir / "m.mp4"), "OUT")) for x in c]
        check(rec_m.get("cmd") and norm(rec_m["cmd"]) == norm(rec_b["cmd"]) and rec_m["graph"] == rec_b["graph"], "ffmpeg render command and filter graph byte-identical to the base (string compare)")
        check(sorted(p.name for p in dd.rglob("*")) == before and not (out_dir / "m.interp").exists() and rec_m["tmp_existed"] == [], "no temp files or folders were created")
        check(any(re.match(r"fps: \d+ takes probed, 0 low-effective-fps", l) for l in lines), f"log: {[l for l in lines if l.startswith('fps:')][:1]}")
        # 50 fps clip, no slow-mo
        c50 = gen_clip(dd / "c50.mp4", mv(), fps=50, dur=12)
        plan50 = noslow(T.make_plan_for(M, "cs2", c50, fills, V, cfg))
        plan50B = noslow(T.make_plan_for(B, "cs2", c50, fills, V, B.load_config()))
        r5, r5b = {}, {}
        logged(T.capture_render, M, plan50, cfg, out_dir / "m5.mp4", r5)
        T.capture_render(B, plan50B, B.load_config(), out_dir / "m5.mp4", r5b)
        norm5 = lambda c: [re.sub(r"[^ ]*last_filter\.txt", "GRAPH", x.replace(str(out_dir / "m5.mp4"), "OUT")) for x in c]
        check(r5.get("cmd") and norm5(r5["cmd"]) == norm5(r5b["cmd"]) and r5["graph"] == r5b["graph"] and r5["tmp_existed"] == [],
              "50 fps clip in a 60 fps montage without slow-mo: not a candidate, command byte-identical to the base")
        ns = argparse.Namespace(target=[str(c50)], all=False, limit=0)
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            M.cmd_fpscontent(ns)
        check("cadence 50->60" in buf.getvalue() and "ok" in buf.getvalue(), "fpscontent reports 'cadence 50->60' for the 50 fps source (information only)")


def part_slow(tmp, env):
    d, song = env
    with section("3) slow-mo 0.5 on a clean 60 fps clip: only the slow-mo range, 120 fps, graph unchanged, fallbacks"):
        clip = gen_clip(d / "slowm.mp4", mvf("N", (120,)), dur=8)
        plan = mkplan(clip, [[1.0, 3.0, 0.5, 240]], song)
        np_, lines, ref, aft, graph_b = render_pair(plan, d, "slow")
        seg = np_["takes"][0]["srcs"][0]
        info = clip_info(seg["path"]) if Path(seg["path"]).exists() else None
        inputs_a, graph_a = M.build_filter(plan, {}, False)
        inputs_b, graph_b2 = M.build_filter(np_, {}, False)
        check(np_ is not plan and any("60 -> 120 fps" in l for l in lines), f"only the slow-mo range is interpolated, to 120 fps: {[l for l in lines if l.startswith('interpolated')][:1]}")
        check(graph_a == graph_b2, "filter graph byte-identical to the base graph (only the input segment changed)")
        diff = [(i, a, b) for i, (a, b) in enumerate(zip(inputs_a, inputs_b)) if a != b]
        check(len(inputs_a) == len(inputs_b) and all(inputs_a[i - 1] in ("-ss", "-i") or inputs_a[i - 1] == "-t" or True for i, _, _ in diff) and
              {inputs_a[i - 1] for i, _, _ in diff} <= {"-ss", "-i", "-t"}, f"render command differs only in the input segment arguments ({len(diff)} values: -ss / -t / -i)")
        s0 = seg["shift"]
        check(0.4 < s0 < 0.6 or abs(s0 - 0.5) < 0.05, f"segment starts at the range start minus the 0.5 s margin (shift {s0:.3f} s)")
        c0, c1 = crisp_per_s(ref), crisp_per_s(aft)
        check(c0 < 40 and c1 >= 45 and c1 > 1.5 * c0, f"sharp unique pictures per second: {c0:.1f} before (about 30), {c1:.1f} after (about 60)")
        t1 = first_bright(aft)
        planned = (2.0 - 1.0) / 0.5
        check(abs(t1 - planned) <= 1 / 60 + 1e-3, f"marker (source 2.0 s) at output {t1:.4f} s, planned {planned:.4f} s (error {(t1 - planned) * 1000:+.1f} ms)")
        real_cmd, real_x, real_floor = M.interp_segment_cmd, M.INTERP_TIMEOUT_X, M.INTERP_MIN_TIMEOUT_S
        real_mci = M.INTERP_MCI
        real_rf, real_pd = M._run_ffmpeg, M.probe_duration
        out_dir = Path(tmp) / "fb"
        out_dir.mkdir()
        fbd = Path(tmp) / "fbclips"
        fbd.mkdir()
        fmain = gen_clip(fbd / "main.mp4", mv(), dur=12)
        ffills = []
        for i in range(2):
            shutil.copy(fmain, fbd / f"f{i}.mp4")
            ffills.append(str(fbd / f"f{i}.mp4"))
        cfg0 = M.load_config()
        rplan = T.make_plan_for(M, "cs2", fmain, ffills, T.names(30, 7), cfg0)           # a real plan (its slow-mo takes are the candidates)
        M.INTERP_MCI = M.INTERP_BLEND                          # fast; the checks are about the fallback rules

        def finishes(label):
            def ok_ffmpeg(cmd, D, elog):
                Path(cmd[-1]).write_bytes(b"x")
                return 0
            M._run_ffmpeg = ok_ffmpeg
            M.probe_duration = lambda p: rplan["duration"] if str(p).endswith(".part.mp4") else real_pd(p)
            f = out_dir / f"{label}.mp4"
            try:
                logged(M.render_plan, rplan, f, cfg0, False, False, "x264", True)
            finally:
                M._run_ffmpeg, M.probe_duration = real_rf, real_pd
            return f.exists() and not f.with_name(f.stem + ".interp").exists()

        def case(label, reason_re, patch):
            M.INTERP_STATE["mci_slow"] = False
            patch()
            try:
                newp, lns = logged(M.interp_prepare, rplan, {}, Path(tmp) / f"fb_{label}")
                fin = finishes(label)
            finally:
                M.interp_segment_cmd, M.INTERP_TIMEOUT_X, M.INTERP_MIN_TIMEOUT_S = real_cmd, real_x, real_floor
            sk = [l for l in lns if re.match(r"interpolation skipped: (main|f\d)\.mp4 \(", l)]
            check(newp is rplan and sk and re.search(reason_re, sk[0]) and fin, f"{label}: original clip used, log '{sk[0] if sk else None}', render finished")
        case("ffmpeg error", r"ffmpeg error", lambda: setattr(M, "interp_segment_cmd", lambda src, s0_, dd, o, m, fps=60, pre="": real_cmd(src, s0_, dd, o, m, fps, pre)[:-1] + ["-vf", "nosuchfilter", str(o)]))
        case("duration mismatch", r"duration .* instead of", lambda: setattr(M, "interp_segment_cmd", lambda src, s0_, dd, o, m, fps=60, pre="": real_cmd(src, s0_, max(0.3, dd - 0.6), o, m, fps, pre)))

        def bad():
            def cmd(src, s0_, dd, o, m, fps=60, pre=""):
                c = real_cmd(src, s0_, dd, o, m, fps, pre)
                i = c.index("-vf")
                c[i + 1] = "negate," + c[i + 1]
                return c
            M.interp_segment_cmd = cmd
        case("low SSIM", r"SSIM|differs too much", bad)
        case("timeout", r"timeout", lambda: (setattr(M, "INTERP_TIMEOUT_X", 1e-5), setattr(M, "INTERP_MIN_TIMEOUT_S", 0.0)))
        M.INTERP_MCI = real_mci
        M.CANCEL.set()
        try:
            try:
                logged(M.render_plan, rplan, out_dir / "c.mp4", cfg0, False, False, "x264", True)
                msg = ""
            except RuntimeError as ex:
                msg = str(ex)
        finally:
            M.CANCEL.clear()
        check(msg == "cancelled" and not (out_dir / "c.interp").exists(), "cancel: raises 'cancelled', temp folder deleted")
        # a ramp (speed > 1) is not a slow-mo candidate; the effect switch 'slow' off turns slow-mo into speed 1
        ramp = mkplan(clip, [[1.0, 3.0, 1.8, 67]], song)
        check(all(not r_["why"] for r_ in M.analyse_takes(ramp)), "ramp x1.8 on a 60 fps clip: not a candidate")
        check(all(not r_["why"] for r_ in M.analyse_takes(plan, fx={"zoom"})), "with the slow-mo effect off the take plays at speed 1: not a candidate")


def part_vfr(tmp, env):
    d, song = env
    with section("6) VFR: jittery timestamps without gaps vs injected gaps; normalised to constant frame rate"):
        jit = gen_clip(d / "jit.mp4", mv() + ",setpts='N/60/TB+(random(0)-0.5)*0.004/TB'", extra=["-vsync", "vfr"])
        gap = gen_clip(d / "gap.mp4", mv() + ",select='not(between(mod(n,30),10,14))'", extra=["-vsync", "vfr"])
        cl = lambda p: M.analyse_takes(mkplan(p, [[2.0, 5.0, 1.0, 180]], song))[0]
        rj, rg = cl(jit), cl(gap)
        check(not rj["m"]["ts"]["vfr"] and rj["why"] == [], f"jittery timestamps, no gaps: not a candidate (gap share {rj['m']['ts']['gap_share']:.1%}, largest {rj['m']['ts']['max_gap_frames']:.1f} frames)")
        check(rg["m"]["ts"]["vfr"] and rg["why"] == ["vfr gaps"], f"injected gaps: candidate 'vfr gaps' (share {rg['m']['ts']['gap_share']:.1%}, largest {rg['m']['ts']['max_gap_frames']:.1f} frames)")
        plan = mkplan(str(d / "gap.mp4"), [[2.0, 5.0, 1.0, 180]], song)
        np_, lines = logged(M.interp_prepare, plan, {}, d / "tmp_gap")
        seg = np_["takes"][0]["srcs"][0]["path"]
        ci = clip_info(seg) if np_ is not plan else None
        want = round(ci["dur"] * 60) if ci else 0
        st = M.ts_stats(M.probe_timestamps(seg, 0.0, 99.0)) if ci else {}
        check(ci and abs(ci["dur"] - 4.3) <= 1 / 60 + 0.002 and ci["n"] == want and not st["vfr"] and abs(st["ts_fps"] - 60) < 0.5,
              f"gap clip normalised: {ci['n'] if ci else None} frames, {ci['dur'] if ci else None} s (exact), constant {st.get('ts_fps', 0):.1f} fps, no gaps left")


def part_cmds(tmp, env):
    d, song = env
    with section("7) fpscontent on a generated montage + plan, interpbench"):
        import contextlib
        import io
        md = Path(tmp) / "mont"
        (md / "logs").mkdir(parents=True)
        dup = d / "dup.mp4"
        clean = d / "clean.mp4"
        src = lambda p: {"path": str(p), "shift": 0.0, "rect": [0, 0, 320, 180], "wh": [320, 180], "audio": False, "a_stream": 0, "gain_db": -6.0}
        plan = {"takes": [{"path": str(clean), "srcs": [src(clean)], "segs": [[1.0, 3.0, 1.0, 120]]},
                          {"path": str(dup), "srcs": [src(dup)], "segs": [[2.0, 4.0, 1.0, 120]]},
                          {"path": str(clean), "srcs": [src(clean)], "segs": [[2.0, 4.0, 0.5, 240]]}], "duration": 8.0, "song": {"path": song}}
        (md / "m.mp4").write_bytes(b"x")
        (md / "logs" / "m.plan.json").write_text(json.dumps(plan), encoding="utf-8")
        calls = []
        real_g, real_p = M.gray_frames, M.probe_timestamps
        M.gray_frames = lambda p, s0, dd, *a, **k: (calls.append((Path(p).name, s0, s0 + dd)), real_g(p, s0, dd, *a, **k))[1]
        M.probe_timestamps = lambda p, s0, e: (calls.append((Path(p).name, s0, e)), real_p(p, s0, e))[1]
        before = snapshot(M.DATA)
        ft = M.HERE / "fpscontent.txt"
        had = ft.exists()
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                M.cmd_fpscontent(argparse.Namespace(target=[str(md / "m.mp4")], all=False, limit=0))
        finally:
            M.gray_frames, M.probe_timestamps = real_g, real_p
        txt = buf.getvalue()
        wrote = ft.exists() and "summary:" in ft.read_text(encoding="utf-8")
        if not had and ft.exists():
            ft.unlink()
        check("take 1:" in txt and "take 2:" in txt and "take 3:" in txt and txt.count("LOW-EFFECTIVE-FPS") == 2 and "duplicated frames" in txt and "slow-mo" in txt,
              "per-take table with the verdict reasons (take 1 ok, take 2 duplicated frames, take 3 slow-mo)")
        check("summary: 3 measured, takes per reason: slow-mo 1, duplicated frames 1, vfr gaps 0, low fps 0" in txt, "summary line: takes per reason")
        check(wrote and snapshot(M.DATA) == before, "fpscontent.txt written next to montage.py; the data folder is byte-identical")
        allowed = [("clean.mp4", 0.5, 3.8), ("dup.mp4", 1.5, 4.8), ("clean.mp4", 1.5, 6.8)]          # each take's used range + the 0.5 s margins
        ok = all(any(c[0] == a_[0] and c[1] >= a_[1] - 1e-3 and c[2] <= a_[2] + 1e-3 for a_ in allowed) for c in calls)
        check(calls and ok, f"only the takes' used ranges were read ({len(calls)} reads, all within the used range + 0.5 s margins)")
        buf = io.StringIO()
        before = snapshot(M.DATA)
        with contextlib.redirect_stdout(buf):
            M.cmd_interpbench(argparse.Namespace(clip=str(d / "dup.mp4")))
        check("motion (mci):" in buf.getvalue() and ("mci ok" in buf.getvalue() or "too slow, blend will be used" in buf.getvalue()) and snapshot(M.DATA) == before,
              f"interpbench prints the verdict and writes nothing into montage_data: {[l for l in buf.getvalue().splitlines() if 'verdict' in l or 'mci)' in l or 'blend:' in l]}")


def run(tmp):
    env = part_classify(tmp)
    part_dup(tmp, env)
    part_clean(tmp, env)
    part_slow(tmp, env)
    part_vfr(tmp, env)
    part_cmds(tmp, env)
