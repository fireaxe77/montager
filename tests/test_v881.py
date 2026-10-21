"""V8.8.1 tests (fast; no montage render, no OCR).
  0) title-bar version V8.8.1; V8.8.1 on top of V8.8 in both changelogs
  1) render command length: 150 takes with very long file names stay under the limit (hard links / folder links / copies), the same files are read, a short command is unchanged
     (so CS2 / Valorant renders keep their exact command), the helper folders are removed without touching a clip; a real ffmpeg launch with more than 600 long-named inputs
  2) R6S utility icons: every image of the utility folder in a killfeed row is rejected (icon at any place of the row, a long name, name text over the icon, an old / unstamped
     scan); normal gun kills are still accepted; a stamped scan is skipped; the audit lists a kill that still holds an icon (and is empty after the re-check)
python tests\\test_v881.py   (parts: V881_PARTS=0,1,2)"""
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_src = (HERE / "test_v842.py").read_text(encoding="utf-8")
_ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
exec(compile(_src[:_src.index("def part0")], str(HERE / "test_v842.py"), "exec"), _ns)
T = types.SimpleNamespace(**_ns)
M = T.M
ROOT = T.ROOT
check = T.check
PARTS = [x for x in os.environ.get("V881_PARTS", "0,1,2").split(",") if x]
import numpy as np                                                                            # noqa: E402


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.8.1", M.APP_VERSION == "V8.8.1")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.8.1 above V8.8", cl[0].startswith("## V8.8.1") and cl[1].startswith("## V8.8 "), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.8.1 above V8.8", sm[0].startswith("## V8.8.1") and sm[1].startswith("## V8.8"), str(sm[:2]))
    seg = body[body.index("## V8.8.1"):body.index("## V8.8", body.index("## V8.8.1") + 5)].lower()
    check("simple entry is plain", not any(w in seg for w in ("test", "known issue", "on hold", "def ", "xfx", "ffmpeg", "sidecar", "cache", "()", "winerror")))


def _inputs(files, n):
    """n takes, each with 4 inputs (the way a stitched, ramped take opens its clip several times), like build_filter's input list."""
    inp = []
    for i in range(n):
        for j in range(4):
            inp += ["-threads", "2", "-ss", f"{1 + (i % 9) + j * 0.123:.4f}", "-t", f"{1.5 + j * 0.0333:.4f}", "-i", str(files[i % len(files)])]
    return inp


def _tree(root):
    """(files, total size) of a folder tree, not following links."""
    n = 0
    for dp, _dn, fn in os.walk(root):
        n += len(fn)
    return n


def part1():
    print("1) render command length")
    tmp = Path(tempfile.mkdtemp(prefix="v881c_"))
    clips = tmp / ("clips " + "x" * 40)
    clips.mkdir()
    files = []
    for i in range(12):
        p = clips / (f"Tom Clancy's Rainbow Six  Siege 2023.11.{i + 1:02d} - 17.18.21.06.DVR " + "very long name " * 8 + f"{i}.mp4")
        p.write_bytes(os.urandom(2000) + bytes([i]))
        files.append(p)
    gp = tmp / "graph.txt"
    gp.write_text("[0:v]null[vout];[0:a]anull[aout]", encoding="utf-8")
    out_ = tmp / "out.mp4"
    cmd = ["ffmpeg", "-y", "-hide_banner", "-v", "error", "-nostats", "-progress", "pipe:1"] + _inputs(files, 150) + \
          ["-filter_complex_script", str(gp), "-map", "[vout]", "-map", "[aout]", "-t", "90.0000", "-c:v", "libx264", str(out_)]
    n_in = sum(1 for c in cmd if c == "-i")
    check(f"the test command is over the Windows limit ({M._cmd_len(cmd)} characters, {n_in} inputs)", M._cmd_len(cmd) > 32767)
    short = ["ffmpeg", "-i", str(files[0]), str(out_)]
    s2, cwd, ex = M.fit_cmd(short, tmp / "al0")
    check("a short command comes back unchanged (CS2 / Valorant renders keep their exact command)", s2 is short and cwd is None and ex == [] and not (tmp / "al0").exists())

    def run_fit(label, block=()):
        keep = {}
        for nm in block:
            keep[nm] = getattr(os, nm)
            setattr(os, nm, lambda *a, **k: (_ for _ in ()).throw(OSError("blocked")))
        keepcopy = shutil.copyfile
        try:
            work = tmp / ("al_%d" % abs(hash(label)))
            c2, cw, ex_ = M.fit_cmd(cmd, work)
        finally:
            for nm, f in keep.items():
                setattr(os, nm, f)
        ok_len = M._cmd_len(c2) <= M.CMD_LIMIT
        ins = [c2[i + 1] for i, c in enumerate(c2[:-1]) if c == "-i"]
        data_ok = all((Path(cw) / a).read_bytes() == Path(o).read_bytes() for a, o in zip(ins, [cmd[i + 1] for i, c in enumerate(cmd[:-1]) if c == "-i"]))
        check(f"[{label}] 150 takes / {n_in} inputs / names of {len(files[0].name)} characters: {M._cmd_len(cmd)} -> {M._cmd_len(c2)} characters (limit {M.CMD_LIMIT})", ok_len)
        check(f"[{label}] every input reads the same bytes as its original, and the other arguments are untouched", data_ok and
              [c for i, c in enumerate(c2) if i == 0 or c2[i - 1] != "-i"] == [c for i, c in enumerate(cmd) if i == 0 or cmd[i - 1] != "-i"])
        M.clean_alias(work, ex_)
        check(f"[{label}] the alias folder and the helper folders are gone, every clip is still there with its bytes",
              not work.exists() and not any(Path(e).exists() for e in ex_) and all(f.exists() and f.stat().st_size == 2001 for f in files))
        return c2

    run_fit("hard links")
    run_fit("no hard links (other disk): symbolic links / folder links", block=("link",))
    run_fit("neither links", block=("link", "symlink"))
    # a real ffmpeg process with all the inputs (600 long-named files would not even start without the fix)
    mk = tmp / "real"
    mk.mkdir()
    real = []
    for i in range(3):
        p = mk / (f"clip {i} " + "a" * 150 + ".mp4")
        r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=30:d=2", "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
                            "-shortest", "-c:v", "mpeg4", "-c:a", "aac", str(p)], capture_output=True)
        if r.returncode == 0:
            real.append(p)
    if len(real) == 3:
        g2 = tmp / "g2.txt"
        g2.write_text("[0:v]null[vout];[0:a]anull[aout]", encoding="utf-8")
        cmd2 = ["ffmpeg", "-y", "-hide_banner", "-v", "error", "-nostats"] + _inputs(real, 160) + \
               ["-filter_complex_script", str(g2), "-map", "[vout]", "-map", "[aout]", "-t", "1.0", "-c:v", "mpeg4", str(tmp / "real_out.mp4")]
        n2 = sum(1 for c in cmd2 if c == "-i")
        check(f"real ffmpeg: {n2} inputs, command {M._cmd_len(cmd2)} characters", M._cmd_len(cmd2) > 32767)
        c2, cw, ex_ = M.fit_cmd(cmd2, tmp / "al_real")
        try:
            r = subprocess.run(c2, cwd=cw, capture_output=True, timeout=300)
            check(f"real ffmpeg starts and renders with the shortened command ({M._cmd_len(c2)} characters)", r.returncode == 0 and (tmp / "real_out.mp4").exists() and M.probe_duration(tmp / "real_out.mp4") > 0.5,
                  r.stderr.decode("utf-8", "ignore")[-300:])
        finally:
            M.clean_alias(cw, ex_)
    else:
        print("  (ffmpeg could not make the test clips: real launch skipped)")
    shutil.rmtree(tmp, ignore_errors=True)


def _icons_dir():
    return M.r6s_util_icon_dir()


def part2():
    print("2) R6S utility icons")
    import cv2
    tmp = Path(tempfile.mkdtemp(prefix="v881u_"))
    old = M.use_data_dir(tmp / "data")
    try:
        icd = M.r6s_util_icon_dir()
        icd.mkdir(parents=True, exist_ok=True)
        real = ROOT / "montage_data" / "r6s" / "utility_icons"
        srcs = sorted(p for p in real.glob("*") if p.suffix.lower() in (".png", ".jpg")) if real.is_dir() else []
        for p in srcs:
            shutil.copy(p, icd / p.name)
        if not srcs:                                     # no real folder here (cloud): four drawn icons of different shapes
            for i, shape in enumerate(("skull", "ring", "cross", "bars")):
                g = np.zeros((26, 34), np.uint8)
                if shape == "skull":
                    cv2.circle(g, (17, 11), 9, 255, -1)
                    cv2.rectangle(g, (11, 17), (23, 24), 255, -1)
                    cv2.circle(g, (13, 10), 3, 0, -1)
                    cv2.circle(g, (21, 10), 3, 0, -1)
                elif shape == "ring":
                    cv2.circle(g, (17, 13), 11, 255, 3)
                    cv2.line(g, (6, 24), (28, 2), 255, 2)
                elif shape == "cross":
                    cv2.line(g, (4, 4), (30, 22), 255, 4)
                    cv2.line(g, (30, 4), (4, 22), 255, 4)
                else:
                    for x in range(4, 32, 6):
                        cv2.rectangle(g, (x, 3 + (x % 3) * 3), (x + 3, 23), 255, -1)
                cv2.imwrite(str(icd / f"icon{i}.png"), g)
        M._R6S_UTIL_CACHE.clear()
        icons = M.r6s_load_util_icons(log=False)
        check(f"the utility folder holds {len(icons)} icon(s), all loaded", len(icons) >= 4 and len(icons) == len([p for p in icd.iterdir()]))
        cfg = dict(M.DEFAULT_CONFIG)
        FPS = M.FPS
        keep_fs, keep_an = M.frame_stream, M.r6s_analyse_entry
        cur = {}

        def frames(path, rec, det, cfg_, fps, use_hw=True):
            for f in range(90):
                fr = np.full((220, 900, 3), 40, np.uint8)
                if 30 <= f <= 70:
                    # the killfeed row: names as bright blocks, the icon at x, a gun silhouette when cur['gun']
                    x, y = cur["x"], 100
                    fr[y - 10:y + 10, 20:cur["name_r"]] = 200
                    if cur.get("gun"):
                        fr[y - 8:y + 8, x:x + 70] = 230
                        fr[y - 3:y + 3, x + 10:x + 60] = 90
                    else:
                        ic = cur["icon"]
                        fr[y - ic.shape[0] // 2:y - ic.shape[0] // 2 + ic.shape[0], x:x + ic.shape[1]] = cv2.cvtColor(ic, cv2.COLOR_GRAY2BGR)
                        if cur.get("over"):                        # name text running over the icon's left third
                            ox = x + 3
                            fr[y - 10:y + 10, ox:ox + cur["over"]] = 200
                yield fr
        M.frame_stream = frames
        M.r6s_analyse_entry = lambda e, c: M._r6s_core(e["rows"], e, c)

        def entry(x, name_l, sig="old", gun=False):
            rows = [{"first": 30, "last": 70, "hits": 41, "y": 100, "h": 20, "x": 20, "w": 600, "gunv": [1] if gun else [],
                     "reads": [[f, [[20, name_l, "fireaxe0", 0.99]], [[x + 40, x + 200, "enemyname", 0.99]]] for f in (35, 45, 55, 65)]}]
            return {"util": [], "util_sig": sig, "v_off": 0.0, "frames": 90, "ocr": [], "rows": rows}

        res = []
        try:
            for ic in icons:
                for label, x, name_r, over in (("left", 120, 110, 0), ("middle", 300, 280, 0), ("right", 600, 560, 0), ("long name", 330, 320, 0), ("name text over the icon", 300, 280, 6)):
                    cur.clear()
                    cur.update(x=x, name_r=name_r, icon=ic["gray"], over=over)
                    e = entry(x, name_r - 5 if label != "long name" else x + 60)    # the long name's OCR box runs past the icon
                    for stamp, sig in (("scan with the old icon set", "old"), ("scan with no stamp", "")):
                        e2 = M.r6s_util_refresh({"path": "x.mp4"}, dict(e, util_sig=sig), None, cfg)
                        a = M._r6s_core(e["rows"], e2, cfg)
                        ur = [r for r in a["rej"] if "utility" in r["reason"]]
                        res.append((ic["name"], label, stamp, not a["kills"] and bool(ur)))
            bad = [r for r in res if not r[3]]
            check(f"every icon ({', '.join(i['name'] for i in icons)}) at 5 places / name positions, old and unstamped scans: all {len(res)} rows rejected as utility", not bad, str(bad[:4]))
            cur.clear()
            cur.update(x=300, name_r=280, gun=True)
            eg = entry(300, 275, gun=True)
            e2 = M.r6s_util_refresh({"path": "x.mp4"}, eg, None, cfg)
            ag = M._r6s_core(eg["rows"], e2, cfg)
            check("a normal gun kill (wide gun icon) is still accepted after the same check", len(ag["kills"]) == 1 and not any("utility" in r["reason"] for r in ag["rej"]), str(ag["rej"]))
            check("... and its scan is stamped as checked", e2.get("util_chk") == M.r6s_util_chk(icons))
            check("a stamped scan is skipped (no second pass)", M.r6s_util_refresh({"path": "x.mp4"}, e2, None, cfg) is e2)
            # the audit
            ic0 = icons[0]
            cur.clear()
            cur.update(x=300, name_r=280, icon=ic0["gray"])
            eu = entry(300, 275)
            chk = M.r6s_util_chk(icons)
            check("audit: an unchecked scan is listed", any("not re-checked" in b[2] for b in M.r6s_audit_entry(eu, cfg, chk)))
            hit = {"first": 31, "last": 69, "hits": 6, "x": 310, "y": 123, "w": 30, "h": 24, "sc": 0.95, "tpl": ic0["name"]}
            ghost = dict(entry(300, 275, gun=True), util=[hit], util_chk=chk)
            ghost["rows"][0]["gunv"] = [1]
            # a row the rule keeps (the hit sits 23 px from the row, the rule allows 17) is still listed by the audit's looser test
            check("audit: a kept kill with a clear icon hit just outside the rule's row height (a wider margin) is listed", len(M.r6s_audit_entry(ghost, cfg, chk)) == 1, str(M.r6s_audit_entry(ghost, cfg, chk)))
            e3 = M.r6s_util_refresh({"path": "x.mp4"}, dict(eu, util_chk="", util_sig="old"), None, cfg)
            hs_ = dict(ghost, util=[dict(hit, sc=0.905, hits=40)])
            check("the headshot crosshair (score 0.90-0.91 against an icon) is not utility: the kill stays and the audit does not list it",
                  len(M._r6s_core(hs_["rows"], hs_, cfg)["kills"]) == 1 and M.r6s_audit_entry(hs_, cfg, chk) == [])
            check("audit: after the re-check the same clip is empty (its kill is a rejected utility row)", M.r6s_audit_entry(e3, cfg, chk) == [])
        finally:
            M.frame_stream, M.r6s_analyse_entry = keep_fs, keep_an
    finally:
        M.restore_data_dir(old)
        M._R6S_UTIL_CACHE.clear()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
    sys.exit(1 if T.FAILS else 0)
