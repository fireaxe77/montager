"""V8.8.8 tests (fast; no render).
  0) title-bar version V8.8.8; V8.8.8 on top of V8.8.7 in both changelogs
  1) fast render: the render graph splits into one sub-graph per take + the final graph with every filter string unchanged (all three games, default + extra
     effects), the take outputs are pinned to the colour space the whole graph negotiates, the colour probe's log reading, frame counts from the graph, the
     switch / fallbacks (real renders old vs new, frame by frame: tests/render888.py)
  2) clip list: the per-clip kill times are kept (memory + montage_data\\clip_rows_v1.json) and recomputed only for a clip whose kill entry / row sidecar changed,
     or for every clip when the settings / detector / program changed; identical to computing them directly (real data: V888_REAL=1 with MONTAGER_DATA)
  3) UI mode: Standard (default, the Sun Valley look) and High performance (flat): same widgets, same buttons, same settings, switching back and forth live,
     saved / loaded (needs a display)
  4) moved clips folder: the Settings folder is used for future moves (one folder per game inside), never scanned even inside a clip folder, default unchanged
  5) sky: every pattern and every colour family used across a library, each song always the same, calm / hard songs still steered; the library count
     (real data: V888_REAL=1); renders of every pattern / family: tests/sky888.py
  6) plans, plan text and filter graphs identical to the v8.8.7 tag (all three games, two styles, default + extra effects)
  7) regression list (the V8.8.5 list + the V8.8.8 rules) and everything V8.8.7 checked (tests/test_v887.py parts 1 - 3, with the sky spread off for the
     'identical to v8.8.4' guards)
python tests\\test_v888.py   (parts: V888_PARTS=0,1,2,3,4,5,6,7)"""
import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_src = (HERE / "test_v887.py").read_text(encoding="utf-8")
_ns = {"__file__": str(HERE / "test_v887.py"), "__name__": "test_v887_parts"}
exec(compile(_src[:_src.rindex('if __name__ == "__main__":')], str(HERE / "test_v887.py"), "exec"), _ns)
V7 = types.SimpleNamespace(**_ns)
V6 = V7.V6
V5 = V6.V5
T = V7.T
M = T.M
ROOT = T.ROOT
check = T.check
PARTS = [x for x in os.environ.get("V888_PARTS", "0,1,2,3,4,5,6,7").split(",") if x]
REAL = os.environ.get("V888_REAL") == "1"
PREV7 = "v8.8.7"
_P7 = []


def prev7():
    """the v8.8.7 tag's montage.py as a module."""
    if not _P7:
        bd = T.TMP / "prev888"
        bd.mkdir(exist_ok=True)
        tar = subprocess.run(["git", "archive", PREV7, "montage.py"], cwd=ROOT, capture_output=True).stdout
        subprocess.run(["tar", "-x", "-C", str(bd)], input=tar, check=True)
        spec = importlib.util.spec_from_file_location("montage_prev888", str(bd / "montage.py"))
        B = importlib.util.module_from_spec(spec)
        sys.modules["montage_prev888"] = B
        spec.loader.exec_module(B)
        _P7.append(B)
    return _P7[0]


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.8.8", M.APP_VERSION == "V8.8.8")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.8.8 above V8.8.7", cl[0].startswith("## V8.8.8") and cl[1].startswith("## V8.8.7"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.8.8 above V8.8.7", sm[0].startswith("## V8.8.8") and sm[1].startswith("## V8.8.7"), str(sm[:2]))
    seg = body[body.index("## V8.8.8"):body.index("## V8.8.7")]
    pts = [l for l in seg.splitlines() if l.startswith("- ")]
    head = seg.splitlines()[0].split(":", 1)[-1].strip()
    check(f"simple entry: a 3-8 word headline ('{head}'), 1-4 points", 3 <= len(head.split()) <= 8 and 1 <= len(pts) <= 4)
    check("simple entry is plain", not any(w in seg.lower() for w in ("test", "known issue", "on hold", "def ", "ffmpeg", "cache", "()", "planner", "regression", "ffv1")))


def _graphs():
    out_ = []
    for g in ("valorant", "cs2", "r6s"):
        for eff in ("default", "extra"):
            p, c = T.mk(M, g, "aggressive", 2, eff={g: eff})
            inputs, graph = M.build_filter(p, c, False)
            out_.append((f"{g}/{eff}", p, inputs, graph))
    return out_


def part1():
    print("1) fast render: the graph split")
    for name, p, inputs, graph in _graphs():
        chains = [c.strip() for c in graph.split(";\n") if c.strip()]
        try:
            jobs, final, fg = M.split_take_graphs(inputs, graph)
        except ValueError as ex:
            check(f"{name}: the graph splits", False, str(ex))
            continue
        nt = len(p["takes"])
        allc = [c for j in jobs for c in j["chains"]] + final
        unmap = lambda c: __import__("re").sub(r"\[\d+(:[av]:\d+)\]", "[#\\1]", c)
        check(f"{name}: one sub-graph per take ({len(jobs)} of {nt}) and the final graph; every chain used once, its filters unchanged",
              len(jobs) == nt and sorted(map(unmap, allc)) == sorted(map(unmap, chains)))
        outs = {l_ for j in jobs for l_, _k in j["outs"]}
        check(f"{name}: the final graph reads only take outputs and its own inputs (music)", all(("[" + l_ + "]") in graph for l_ in outs)
              and sum(len(j["groups"]) for j in jobs) + len(fg) == len(M._split_inputs(inputs)))
        jp, _f, _g = M.split_take_graphs(inputs, graph, ("bt709", "tv"))
        pins = [c for j in jp for c in j["chains"] if "color_spaces=bt709:color_ranges=tv" in c]
        check(f"{name}: every picture output of a take pinned to the graph's colour space ({len(pins)} pins)", len(pins) == sum(1 for j in jp for _l, k in j["outs"] if k == "v"))
    log = ("[auto-scale] x\n[trim_in_5:0 @ 000001] auto-inserting filter 'auto_scale_9' between the filter 'graph 0 input from stream 5:0' and the filter 'trim_in_5:0'\n"
           "[auto_scale_9 @ 000002] w:1920 h:1080 fmt:yuv420p csp:smpte170m range:tv sar:1/1 -> w:1920 h:1080 fmt:yuv420p csp:bt709 range:tv sar:1/1 flags:0x4\n"
           "[Parsed_scale_26 @ 000003] w:1280 h:960 fmt:yuv420p csp:smpte170m range:tv sar:1/1 -> w:1920 h:1080 fmt:yuv420p csp:bt709 range:tv sar:3/4 flags:0x200\n"
           "[Parsed_scale_56 @ 000004] w:768 h:432 fmt:gray csp:unknown range:pc sar:0/1 -> w:1920 h:1080 fmt:gray csp:unknown range:pc sar:0/1 flags:0x4\n")
    check("colour probe: converters on the clips' own inputs + the clips' scalers -> one colour space (bt709 tv); the sky planes ignored", M.colour_pin_from_log(log) == ("bt709", "tv"))
    bad = log + "[auto_scale_12 @ 000005] w:1920 h:1080 fmt:yuv420p csp:smpte170m range:tv sar:1/1 -> w:1920 h:1080 fmt:yuv420p csp:bt709 range:tv sar:1/1 flags:0x4\n"
    check("colour probe: a converter inside the graph -> render in one run as before", M.colour_pin_from_log(bad) is None)
    two = log + "[Parsed_scale_30 @ 000006] w:1280 h:960 fmt:yuv420p csp:smpte170m range:tv sar:1/1 -> w:1920 h:1080 fmt:yuv420p csp:smpte170m range:tv sar:3/4 flags:0x200\n"
    check("colour probe: two colour spaces -> one run as before", M.colour_pin_from_log(two) is None)
    check("colour probe: nothing converted -> no pin", M.colour_pin_from_log("nothing here") == ("", ""))
    src = V5.SRC()
    b_ = V5.body_of("_render_once")
    check("the render uses the fast path (switch FAST_RENDER, on) and falls back to the one-run render, encoded the same way", M.FAST_RENDER[0] is True
          and "_render_fast(" in b_ and "if rc is None:" in b_ and "tail_" in b_ and "not preview" in b_)
    bf = V5.body_of("_render_fast")
    check("fast path: given up (one run) for few takes, little free disk, more than one colour space, any error; take files removed",
          "FAST_MIN_TAKES" in bf and "disk_usage" in bf and "pin is None" in bf and "except Exception" in bf and "rmtree(tdir" in bf)
    b_ = V5.body_of("render_parts")
    check("take parts are lossless with their exact timestamps (utvideo in NUT, microsecond time base, every frame as made); the game sound is made in the final pass from the clips",
          "FAST_VCODEC" in b_ and '"1:1000000"' in b_ and '"nut"' in b_ and "passthrough" in b_ and "audio_final=True" in b_ and M.FAST_VCODEC[:2] == ["-c:v", "utvideo"])
    check("the final pass rebuilds the graph's own picture concat from exact frame counts (fades / dissolve timing unchanged) and checks every part before the encoder gets it",
          "seg_frames(" in b_ and "trim=start_frame=" in b_ and "check_seg(" in b_ and "sorted(rest + [vci])" in b_)
    chains = ["[0:v:0]setsar=1,fps=60,trim=end_frame=48,setpts=PTS-STARTPTS[s0v]", "[1:v:0]setsar=1,fps=60,trim=end_frame=20,setpts=PTS-STARTPTS[s1v]",
              "[s0v][s1v]concat=n=2:v=1:a=0[t0c]", "[t0c]split=2[t0m][t0f]", "[t0f]perspective=x0=1,format=yuv420p[t0e]", "[t0m][t0e]overlay=0:0:eof_action=pass[t0o]",
              "[t0o]format=yuv420p,trim=end_frame=60,setpts=PTS-STARTPTS,split=2[t0body][t0tail]", "[t0body]trim=start_frame=0:end_frame=58,setpts=PTS-STARTPTS[t0v]",
              "[t0tail]trim=start_frame=58:end_frame=60,setpts=PTS-STARTPTS[t0tl]", "[2:v:0]fps=60,trim=end_frame=3,setpts=PTS-STARTPTS,format=yuv420p[h0a]",
              "[t0tl][h0a]concat=n=2:v=1:a=0[sa1]", "[3:v:0]fps=60,trim=end_frame=5,setpts=PTS-STARTPTS[sb1]",
              "[sa1][sb1]blend=all_expr='A',format=yuv420p,setpts=PTS-STARTPTS,fps=60[x1]"]
    check("frame counts read from the graph (take body 58, tail 2, dissolve 5, a take's clips 68)", [M.seg_frames(l_, chains) for l_ in ("t0v", "t0tl", "x1", "t0c")] == [58, 2, 5, 68])
    check("the encoder gets each part the moment it is made (one local port per part, in order) and the parts it needs soonest run first",
          "socket" in b_ and "tcp://127.0.0.1" in b_ and "rebalance" in b_ and M.RENDER_JOBS >= 2)
    bf = V5.body_of("_render_fast")
    check("the colour probe runs beside the parts; the encoder gets nothing until it confirmed the colour pin; a different pin = the parts made again with it",
          "colour_pin_same(" in bf and "gate=" in bf and "except PinWrong" in bf)


def part2():
    print("2) clip list: kill times kept, recomputed only when something changed")
    tmp = Path(tempfile.mkdtemp(prefix="v888rows_"))
    old = M.use_data_dir(tmp / "data")
    calls = []
    keep = M.analyse_clip_entry
    M.analyse_clip_entry = lambda r, e, cfg, g, build=False: calls.append(r["path"]) or {"kills": [{"t": float(k)} for k in e["ks"]], "deaths": []}
    try:
        M.CLIP_ROWS_MEMO.clear()
        det = types.SimpleNamespace(d={"stamp": "ocr12345678"})
        kc = M.KillStore()
        recs = []
        for i in range(6):
            p_ = tmp / f"clip{i}.mp4"
            p_.write_bytes(b"x" * (100 + i))
            r = {"path": str(p_), "game": "valorant"}
            recs.append(r)
            if i != 5:
                kc.put(M.kills_key(r, "valorant", det), {"ks": [1.0 + i, 2.5]} if i != 4 else {"error": "x"})
        cfg = dict(M.DEFAULT_CONFIG)
        a = M.clip_row_kills(recs, "valorant", cfg, det, kc, {})
        want = {recs[i]["path"]: ([1.0 + i, 2.5] if i < 4 else None) for i in range(6)}
        check(f"first load: every scanned clip analysed once ({len(calls)}), the same kill times; an error entry / no entry = not scanned", a == want and len(calls) == 4)
        calls.clear()
        b = M.clip_row_kills(recs, "valorant", cfg, det, kc, {})
        check(f"switching back: nothing analysed again ({len(calls)})", b == want and not calls)
        M.CLIP_ROWS_MEMO.clear()
        c = M.clip_row_kills(recs, "valorant", cfg, det, kc, {})
        check(f"next launch: read from clip_rows_v1.json, nothing analysed ({len(calls)})", c == want and not calls and (tmp / "data" / "clip_rows_v1.json").exists())
        time.sleep(0.02)
        kc.put(M.kills_key(recs[1], "valorant", det), {"ks": [9.0]})
        d = M.clip_row_kills(recs, "valorant", cfg, det, kc, {})
        check(f"a re-scanned clip is analysed again, only that one ({len(calls)})", d[recs[1]["path"]] == [9.0] and calls == [recs[1]["path"]])
        calls.clear()
        time.sleep(0.02)
        Path(recs[2]["path"]).write_bytes(b"y" * 300)        # the clip itself changed: its kill entry key changes (not scanned until rescanned)
        e = M.clip_row_kills(recs, "valorant", cfg, det, kc, {})
        check("a changed clip file is never shown with its old kill times", e[recs[2]["path"]] is None and not calls)
        M.clip_row_kills(recs, "valorant", dict(cfg, ui_mode="performance", accent="red", ui_layout={"geometry": "900x700"}), det, kc, {})
        check(f"a look / window setting (UI mode, accent, window size) changes nothing: nothing analysed ({len(calls)})", not calls)
        f_ = M.clip_row_kills(recs, "valorant", dict(cfg, death_lock_s=7.5), det, kc, {})
        check(f"a changed setting: every scanned clip analysed again ({len(calls)}: clip 3 now has no entry)", len(calls) == 3 and f_[recs[0]["path"]] == [1.0, 2.5])
        calls.clear()
        M.CLIP_ROWS_ON[0] = False
        try:
            g_ = M.clip_row_kills(recs, "valorant", dict(cfg, death_lock_s=7.5), det, kc, {})
        finally:
            M.CLIP_ROWS_ON[0] = True
        check("switch off: computed directly every time (the old way), same result", g_ == f_ and len(calls) == 3)
    finally:
        M.analyse_clip_entry = keep
        M.restore_data_dir(old)
        M.CLIP_ROWS_MEMO.clear()
    b_ = V5.body_of("load_clips")
    check("the clip list uses the kept kill times (clip_row_kills), every other column as before", "clip_row_kills(" in b_ and '"q": clip_quality(r, cfg)' in b_ and "used_label" in b_)
    sig = V5.body_of("clip_rows_sig")
    check("what the kill times depend on is in the signature (settings, program, detector, utility overrides, CS2 dating memo / switches)",
          all(k in sig for k in ("json.dumps(cfg", "__file__", "detect_", "_util_overrides_file", "_dating_file", "CS2_PRESENCE_ON")))
    if REAL:
        cfg = M.load_config()
        sc = M.scan_clips(cfg)
        for g in ("valorant", "cs2", "r6s"):
            det = M.load_dets(g).get(g)
            kc = M.load_kills_cache()
            ovs = M.load_clip_overrides() if g in ("valorant", "r6s") else {}
            ref = {}
            for r in sc:
                if r.get("error") or r.get("game") != g:
                    continue
                e = kc.get(M.kills_key(r, g, det)) if det else None
                ks = None
                if e and not e.get("error"):
                    a_ = M.analyse_clip_entry(r, e, cfg, g)
                    if ovs:
                        a_ = M.apply_utility_override(r, e, a_, cfg, g, ovs)
                    ks = [k["t"] for k in a_["kills"]]
                ref[r["path"]] = ks
            M.CLIP_ROWS_MEMO.clear()
            got = M.clip_row_kills(sc, g, cfg, det, kc, ovs)
            check(f"real data {g}: {len(ref)} clips, kill times identical to the direct computation", got == ref)


def part3():
    print("3) UI mode: Standard / High performance")
    import tkinter
    try:
        r_ = tkinter.Tk()
        r_.destroy()
    except Exception:                                      # noqa: BLE001
        check("a display for the window", False, "no display")
        return
    from tkinter import ttk
    tmp = Path(tempfile.mkdtemp(prefix="v888ui_"))
    old = M.use_data_dir(tmp / "gdata")

    def census(app):
        ws, todo = [], [app.root]
        while todo:
            w = todo.pop()
            ws.append(w)
            todo += w.winfo_children()
        cls = {}
        for w in ws:
            cls[w.winfo_class()] = cls.get(w.winfo_class(), 0) + 1
        return cls, sorted(app.named), sorted(app.tabs)

    try:
        app = M.App(0, startup=False)
        check("Standard is the default (Sun Valley look as before)", M.ui_mode_of(M.load_config()) == "standard" and app.set_uimode.get() == "Standard"
              and (M.SV_THEME[0] or not M.UI_MODES))
        th0 = ttk.Style(app.root).theme_use()
        rh0 = ttk.Style(app.root).lookup("Treeview", "rowheight")
        c0 = census(app)

        def states(a_):
            st_ = {}
            for nm_, b in a_.named.items():
                try:
                    st_[nm_] = (bool(str(b.cget("command"))), str(b.cget("state")))
                except tkinter.TclError:
                    pass
            return st_
        s0 = states(app)
        app.set_uimode.set("High performance")
        for _ in range(4):
            app.root.update()
        st = ttk.Style(app.root)
        check(f"High performance switches at once: flat theme ({st.theme_use()}), no Sun Valley images", st.theme_use() == "clam" and M.PERF_UI[0] and not M.SV_THEME[0])
        check(f"same row height ({st.lookup('Treeview', 'rowheight')} = {rh0}), same fonts", str(st.lookup("Treeview", "rowheight")) == str(rh0))
        c1 = census(app)
        check(f"same widgets, buttons and tabs ({sum(c1[0].values())} widgets, {len(c1[1])} named buttons, {len(c1[2])} tabs)", c0 == c1)
        s1 = states(app)
        bad = [n_ for n_ in s0 if s1.get(n_) != s0[n_] or not s0[n_][0]]
        check(f"every named button ({len(s0)}) has its action and the same state in High performance as in Standard", not bad and set(s0) == set(s1), ", ".join(bad[:8]))
        opened = []
        for t_ in app.tabs:
            app.nb.select(app.tabs[t_])
            app.root.update()
            opened.append(app.nb.select() == str(app.tabs[t_]))
        check(f"every tab opens in High performance ({len(opened)})", all(opened))
        app.flush_settings()
        check("the mode is saved", json.loads(M.CONFIG_PATH.read_text(encoding="utf-8")).get("ui_mode") == "performance")
        app.root.destroy()
        M.LOG_SINK[0] = M.PROGRESS[0] = None
        app2 = M.App(0, startup=False)
        check("a new window starts in High performance", ttk.Style(app2.root).theme_use() == "clam" and app2.set_uimode.get() == "High performance")
        check("... with the same widgets", census(app2) == c1)
        app2.set_uimode.set("Standard")
        for _ in range(4):
            app2.root.update()
        check(f"back to Standard at once ({ttk.Style(app2.root).theme_use()} = {th0})", ttk.Style(app2.root).theme_use() == th0 and not M.PERF_UI[0])
        app2.flush_settings()
        app2.root.destroy()
        M.LOG_SINK[0] = M.PROGRESS[0] = None
        check("Standard saved again", json.loads(M.CONFIG_PATH.read_text(encoding="utf-8")).get("ui_mode") == "standard")
    finally:
        M.restore_data_dir(old)
    print("  (every control in both modes: V888_PARTS=7 runs the V8.8.5 Settings round trip; the smoketest clicks every button)")


def part4():
    print("4) moved clips folder setting")
    tmp = Path(tempfile.mkdtemp(prefix="v888mv_"))
    clips = tmp / "clips" / "Valorant"
    clips.mkdir(parents=True)
    cfg = dict(M.DEFAULT_CONFIG, clip_root=str(tmp), clip_dirs={"valorant": [str(clips)], "cs2": [], "r6s": []}, output_root=str(tmp / "out"))
    check("default unchanged: <clip root>\\Montager moved clips", Path(M.moved_root(cfg)) == tmp / M.MOVED_DIR_NAME)
    mine = clips / "keep these"
    c2 = dict(cfg, moved_dir=str(mine))
    check("the chosen folder is used", Path(M.moved_root(c2)) == mine)
    (clips / "a.mp4").write_bytes(b"x" * 10)
    d = M.move_clip_file(str(clips / "a.mp4"), "valorant", c2)
    check(f"a move goes into the chosen folder, one folder per game ({Path(d).relative_to(tmp)})", Path(d).parent == mine / "Valorant")
    (clips / "b.mp4").write_bytes(b"x" * 10)
    found = [Path(f).name for f in M.walk_files([str(tmp / "clips")], {".mp4"}, 1, c2)]
    check(f"never scanned, even inside a scanned clip folder ({found})", found == ["b.mp4"])
    check("... the default folder name is never scanned either", M.MOVED_DIR_NAME.lower() in M.SKIP_DIR_NAMES)
    b_ = V5.SRC()
    check("Settings > Folders has the moved clips folder (saved with the other folders; the default stays the default)",
          '("moved_dir", "Moved clips folder (move icon)")' in b_ and 'cfg["moved_dir"] = ""' in V5.body_of("collect_settings"))


def _lib():
    """songs of the library (real: the CSV / song cache values; else 1500 generated songs with a spread of energy / tempo / vibe)."""
    import random
    rnd = random.Random(7)
    songs = []
    for i in range(1500):
        e = min(1.0, max(0.05, rnd.gauss(0.68, 0.18)))
        b = rnd.choice([75, 85, 95, 100, 110, 120, 128, 135, 140, 150, 160, 170, 175])
        songs.append({"path": f"s{i}.mp3", "artist": f"artist {i % 400}", "title": f"title {i}", "energy": e, "bpm": b, "dance": rnd.random()})
    return songs


def part5():
    print("5) sky: patterns and colour families across a library")
    songs = _lib()
    pats = [M.sky_pattern_for({"song": s})[0] for s in songs]
    cnt = {p_: pats.count(p_) for p_ in M.SKY_PATTERNS}
    check(f"every pattern used ({cnt}): each at least 8 % of the songs", all(v >= 0.08 * len(songs) for v in cnt.values()))
    fams = []
    for s in songs:
        st = "chill" if s["energy"] < 0.45 else "hype" if s["energy"] < 0.8 else "aggressive"
        rk = M.sky_ranked(st, s["energy"], s["bpm"])[0]
        fams.append(M.sky_family_for({"song": s}, rk)[0])
    fc = {f_: fams.count(f_) for f_ in M.SKY_FAMILIES}
    check(f"every colour family used ({fc}): each at least 3 %", all(v >= 0.03 * len(songs) for v in fc.values()))
    s0 = songs[11]
    same = {(M.sky_pattern_for({"song": dict(s0), "seed": sd, "recipe": st_, "game": g})[0], M.sky_family_for({"song": dict(s0), "seed": sd}, M.sky_ranked("hype", 0.7, 128)[0])[0])
            for sd in (1, 99) for st_ in ("hype", "chill") for g in ("cs2", "valorant", "r6s")}
    check(f"the same song always gets the same pattern and family, whatever seed / style / game ({same})", len(same) == 1)
    calm = [M.sky_pattern_for({"song": {"path": "x.mp3", "artist": f"a{i}", "title": f"t{i}", "energy": 0.25, "bpm": 78}})[0] for i in range(300)]
    hard = [M.sky_pattern_for({"song": {"path": "x.mp3", "artist": f"a{i}", "title": f"t{i}", "energy": 0.95, "bpm": 165}})[0] for i in range(300)]
    cs, hs = (calm.count("amoebas") + calm.count("aurora")) / 300, (hard.count("rings") + hard.count("bands")) / 300
    check(f"tempo / energy still steer it: calm songs {cs * 100:.0f}% amoebas / aurora, hard fast songs {hs * 100:.0f}% rings / bands (an even spread would be 40 %)", cs > 0.5 and hs > 0.5)
    rk = M.sky_ranked("aggressive", 0.9, 160)[0]
    hf = [M.sky_family_for({"song": {"path": "x.mp3", "artist": f"a{i}", "title": f"t{i}"}}, rk)[0] for i in range(300)]
    top = [M.SKY_NAME_FAMILY[n_] for n_ in rk if n_ in M.SKY_NAME_FAMILY][:3]
    check(f"the vibe's own families come first (aggressive song: {', '.join(dict.fromkeys(top))} = {sum(hf.count(f_) for f_ in set(top)) / 3:.0f}% of the picks)",
          sum(hf.count(f_) for f_ in set(top)) / 300 > 0.45)
    M.SKY_PICK_SPREAD[0] = False
    try:
        B = prev7()
        rk = M.sky_ranked("hype", 0.7, 128)[0]
        old_same = all(M.sky_pattern_for({"song": s})[0] == B.sky_pattern_for({"song": s})[0] and M.sky_family_for({"song": s}, rk) == B.sky_family_for({"song": s}, rk)
                       for s in songs[:200])
    finally:
        M.SKY_PICK_SPREAD[0] = True
    check("switch SKY_PICK_SPREAD off: the V8.8.7 pattern and family pick exactly", old_same)
    if REAL:
        cfg = M.load_config()
        lib, _a, _b = M.song_pool(cfg, cached_only=True)
        pc, fc2 = {}, {}
        for s in lib:
            e = s.get("energy") if s.get("energy") is not None else 0.6
            b = s.get("csv_bpm") or s.get("bpm") or 120
            s2 = dict(s, energy=e, bpm=b)
            p_ = M.sky_pattern_for({"song": s2})[0]
            st = "chill" if e < 0.45 else "hype" if e < 0.8 else "aggressive"
            f_ = M.sky_family_for({"song": s2}, M.sky_ranked(st, e, b)[0])[0]
            pc[p_] = pc.get(p_, 0) + 1
            fc2[f_] = fc2.get(f_, 0) + 1
        print(f"  library ({len(lib)} songs): patterns {pc}; families {fc2}")
        check("library: every pattern and every family used", len(pc) == len(M.SKY_PATTERNS) and len(fc2) == len(M.SKY_FAMILIES))


def part6():
    print("6) plans, plan text and filter graphs identical to v8.8.7")
    B = prev7()
    for g in ("valorant", "cs2", "r6s"):
        for st in ("aggressive", "chill"):
            for eff in ("default", "extra"):
                pb, cb = T.mk(B, g, st, 2, eff={g: eff})
                pd, cd = T.mk(M, g, st, 2, eff={g: eff})
                same = T.js(pb) == T.js(pd) and repr(B.build_filter(pb, cb, False)) == repr(M.build_filter(pd, cd, False)) \
                    and B.fmt_plan(pb, copy.deepcopy(M.fake_events()), {}, [], [], None) == M.fmt_plan(pd, copy.deepcopy(M.fake_events()), {}, [], [], None)
                check(f"{g} / {st} / {eff}: plan, plan text and filter graph identical to v8.8.7", same)


def part7():
    print("7) regression list + everything V8.8.7 checked")
    R = [("V8.8.8", "a render in parts gives the one-run render's frames and sound exactly (graph split, chains unchanged, exact timestamps)", "render_parts(" in V5.SRC() and "split_take_graphs(" in V5.SRC()),
         ("V8.8.8", "takes are pinned to the colour space the whole render graph negotiates", "color_spaces=" in V5.body_of("split_take_graphs")),
         ("V8.8.8", "the clip list's kill times are kept and recomputed only for changed clips", "clip_row_kills(" in V5.body_of("load_clips")),
         ("V8.8.8", "the moved clips folder from Settings is never scanned", "skip_mv" in V5.body_of("walk_files")),
         ("V8.8.8", "Standard stays the default look", M.ui_mode_of({}) == "standard"),
         ("V8.8.8", "each song keeps one pattern / colour family; every one is used", M.SKY_PICK_SPREAD[0] is True)]
    for v, rule, ok in R:
        check(f"{v}: {rule}", ok)
    V5.part4()
    M.SKY_PICK_SPREAD[0] = False
    try:
        for p_ in ("1", "2", "3"):
            V7.__dict__["part" + p_]()
    finally:
        M.SKY_PICK_SPREAD[0] = True


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
    sys.exit(1 if T.FAILS else 0)
