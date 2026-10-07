"""V6.9.7 part D tests: the Settings checkbox for low-fps interpolation (existing config key interpolate_low_fps, default true)."""
import inspect
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from v697_common import *                                                                        # noqa: F401,F403
from v697_common import M, T, R, check, section, logged, ROOT
from v697_common import base_module, mlogged
import v696_common as C


def cfg_file():
    return json.loads(M.CONFIG_PATH.read_text(encoding="utf-8"))


def part_checkbox(tmp):
    with section("D1) Settings checkbox 'Interpolate low-fps takes': loads from config, toggling writes only interpolate_low_fps"):
        import test_v557 as G
        # the checkbox reflects a hand-edited config.json on load (true / false / key missing = true)
        for val, want in ((False, False), (True, True), (None, True)):
            app, old = G.new_app({"interpolate_low_fps": val} if val is not None else None)
            try:
                if val is None:
                    cfg = M.load_json(M.CONFIG_PATH, {})
                    cfg.pop("interpolate_low_fps", None)
                    M.save_json(M.CONFIG_PATH, cfg)
                    app.root.tk.eval("foreach id [after info] {after cancel $id}")
                    app.root.destroy()
                    app = M.App(0, startup=False)
                    G.pump(app.root, 3, 0.02)
                check(app.set_interp.get() is want, f"config {'key missing' if val is None else 'interpolate_low_fps = ' + str(val).lower()}: the checkbox shows {'checked' if want else 'unchecked'}")
            finally:
                G.close_app(app, old)
        app, old = G.new_app()
        try:
            texts = [w.cget("text") for w in G.walk(app.root) if w.winfo_class() in ("TCheckbutton", "Checkbutton")]
            check("Interpolate low-fps takes (slow-mo, duplicated frames, VFR)" in texts, "the checkbox exists in the Settings tab with the requested text")
            app.flush_settings()
            before = cfg_file()
            check(before.get("interpolate_low_fps") is True, "default: the key is written as true (default behaviour unchanged)")
            app.set_interp.set(False)
            app.flush_settings()
            after = cfg_file()
            diff = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
            check(diff == {"interpolate_low_fps"} and after["interpolate_low_fps"] is False, f"unchecking writes the key and changes no other config key (diff: {sorted(diff)})")
            check(M.load_config()["interpolate_low_fps"] is False, "the next render reads it from config.json (no restart needed)")
            app.set_interp.set(True)
            app.flush_settings()
            check(cfg_file() == before, "checking it again restores the file exactly")
            # persists across a restart
            app.set_interp.set(False)
            app.flush_settings()
            app.root.tk.eval("foreach id [after info] {after cancel $id}")
            app.root.destroy()
            app2 = M.App(0, startup=False)
            G.pump(app2.root, 3, 0.02)
            check(app2.set_interp.get() is False, "persists across a restart")
            G.close_app(app2, old)
            old = None
        finally:
            if old is not None:
                G.close_app(app, old)


def part_render(tmp):
    with section("D2) unchecked = the hidden switch: nothing probed or interpolated, plan and render command identical to the base; checked = unchanged behaviour"):
        B = base_module(tmp)
        d = Path(tmp) / "d_render"
        d.mkdir()
        song = C.silent_song(d / "s.wav", 10)
        slow = C.gen_clip(d / "slow.mp4", C.mvf("N", (120,)), dur=8)
        dup = C.gen_clip(d / "dup.mp4", C.mvf("floor(N/2)", (120, 121)))
        p1 = C.mkplan(slow, [[1.0, 3.0, 0.5, 240]], song)
        p2 = C.mkplan(dup, [[1.0, 4.0, 1.0, 180]], song)
        t1, t2 = p1["takes"][0], dict(p2["takes"][0])
        t2.update(out_start=t1["dur"], f0=t1["nf"])
        plan = {"takes": [t1, t2], "duration": p1["duration"] + p2["duration"], "song": {"path": song, "start_t": 0.0, "fade_out_start": 3.0}}
        before = json.dumps(plan, sort_keys=True, default=str)
        probed = []
        real_pf = M.probe_fps
        M.probe_fps = lambda p: probed.append(p) or (_ for _ in ()).throw(AssertionError("probed although switched off"))
        try:
            newp, lines = logged(M.interp_prepare, plan, dict(M.load_config(), interpolate_low_fps=False), d / "off")
        finally:
            M.probe_fps = real_pf
        check(newp is plan and not probed and lines == ["fps: interpolation off (setting)"] and not (d / "off").exists() and json.dumps(plan, sort_keys=True, default=str) == before,
              f"unchecked: the very same plan comes back, nothing probed, no temp files, one log line {lines}")
        fm = M.build_filter(newp, {}, False, M.FX_ALL)
        fb = B.build_filter(json.loads(before), {}, False, B.FX_ALL)
        check(fm == fb, "unchecked: the render command (inputs + filter graph) is byte-identical to the base for a selection with a slow-mo and a duplicated-frame take")
        # checked (default): identical to the behaviour before this change (the base commit)
        tm, tb = d / "tmp_m", d / "tmp_b"
        npm, lm = logged(M.interp_prepare, json.loads(before), dict(M.load_config(), interpolate_low_fps=True), tm)
        npb, lb = mlogged(B, B.interp_prepare, json.loads(before), dict(B.load_config()), tb)
        san = lambda x, t: json.dumps(x, sort_keys=True, default=str).replace(str(t), "<T>")
        check(san(npm["takes"], tm) == san(npb["takes"], tb) and [re.sub(r" in [\d.]+ s", "", l.replace(str(tm), "<T>")) for l in lm] == [re.sub(r" in [\d.]+ s", "", l.replace(str(tb), "<T>")) for l in lb] and any(l.startswith("interpolated") for l in lm),
              f"checked: both takes are interpolated exactly like in the base commit ({[l[:60] for l in lm if l.startswith('interpolated')]})")
        gm = M.build_filter(npm, {}, False, M.FX_ALL)
        gb = B.build_filter(npb, {}, False, B.FX_ALL)
        check([str(x).replace(str(tm), "<T>") for x in gm[0]] == [str(x).replace(str(tb), "<T>") for x in gb[0]] and gm[1] == gb[1], "checked: the render command is identical to the base")
        # the only code difference: the log line of the switched-off path
        a, b = inspect.getsource(M.interp_prepare).splitlines(), inspect.getsource(B.interp_prepare).splitlines()
        dl = [(x, y) for x, y in zip(a, b) if x != y]
        check(len(a) == len(b) and len(dl) == 1 and "interpolation off (setting)" in dl[0][0], f"interp_prepare differs from the base in ONE line only (the log text): {len(dl)}")


ORDER = ["part_checkbox", "part_render"]
