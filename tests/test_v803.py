"""V8.0.3 tests: R6S utility (gadget) kills. FAST unit tests only (seconds; no render, no corpus, no real clips, no OCR engine).
  0) title-bar version V8.0.3; V8.0.3 / V8.0.2 on top of both changelogs
  1) utility template loader: 0 / 1 / 2 icons, missing folder, any file name; the old icons folder is not used for kills (logged once)
  2) a row with a utility icon in its weapon slot is rejected 'utility: gadget kill icon' (not a kill, listed in the rejects); a normal row is unaffected
  3) the per-clip override admits it (same functions / log lines as Valorant), planner flag + ledger note; the override is R6S + Valorant only in the GUI
  4) stale cached entries (error / other utility icon set) are scanned again when picked
  5) frozen: filter graphs + plan text (ramp take + slow-mo ending) identical to V8.0.2 for cs2 / valorant, r6s same builder; synthetic rows, tags, gaps, folders identical
  p) (V803_PLANS=1, slow) CS2 + Valorant dry plans, same seed, identical to V8.0.2
python tests\\test_v803.py   (parts: V803_PARTS=0,1,2,3,4,5)"""
import copy
import importlib.util
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("t802", str(ROOT / "tests" / "test_v802.py"))
T2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T2)
T = T2.T
M, check, section, TMP, LOG, cv2, np = T.M, T.check, T.section, T.TMP, T.LOG, T.cv2, T.np
PARTS = [x for x in os.environ.get("V803_PARTS", "0,1,2,3,4,5").split(",") if x]
CFG = copy.deepcopy(M.DEFAULT_CONFIG)
REFS = ("V8.0.2-good", "main")


def bx(x0, x1, t, col, y=100):
    return [x0, y, x1, y + 24, t, 0.95, col, 3]


def ocr_frames(victim="BuffSledge_25", frames=(30, 36, 42, 50, 60, 70, 80, 90)):
    """OCR frames of one row: [killer fireaxeO] <weapon slot x 260-330> [victim]."""
    return [[f, f, [bx(10, 150, "fireaxeO", "g"), bx(340, 520, victim, "r")], [[170, 98, 70, 28, 0.9]]] for f in frames]


def hit(first=28, last=95, x=250, y=112, hits=60, sc=0.98):
    return {"first": first, "last": last, "hits": hits, "x": x, "y": y, "w": 30, "h": 22, "sc": sc, "tpl": "kill_skull.png"}


def entry(util=None, victim="BuffSledge_25", util_sig=""):
    return {"ocr": ocr_frames(victim), "rows": [], "frames": 200, "v_off": 0.0, "game": "r6s", "util": util or [], "util_sig": util_sig}


def part0():
    section("0) version + changelog")
    check("APP_VERSION is V8.0.3", M.APP_VERSION == "V8.0.3")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.0.3, V8.0.2, V8.0.1", [x[:9] for x in cl[:3]] == ["## V8.0.3", "## V8.0.2", "## V8.0.1"], str(cl[:3]))
    sm = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8").splitlines()
    sh = [l for l in sm if l.startswith("## V")]
    check("simple changelog (Settings text): 'R6S utility kills' on top, then V8.0.2", "R6S utility kills" in sh[0] and sh[1].startswith("## V8.0.2"), str(sh[:2]))
    body = "\n".join(sm[sm.index(sh[0]):sm.index(sh[1])]).lower()
    check("V8.0.3 entry is plain (no test / function names, no on-hold blocks)", not any(w in body for w in ("test", "known issue", "abandoned", "on hold", "r6s_", "def ")))


def part1():
    section("1) utility template loader + the old icons folder")
    d = TMP / "ui"
    check("missing folder -> 0 icons, no crash", M.r6s_load_util_icons(d, log=False) == [])
    d.mkdir()
    check("empty folder -> 0 icons", M.r6s_load_util_icons(d, log=False) == [])
    T.mk_icon(d / "kill_skull.png", 41)
    check("1 icon", len(M.r6s_load_util_icons(d, log=False)) == 1)
    T.mk_icon(d / "any name at all.jpg", 42, 0.7)
    check("2 icons (png + jpg, any file name)", len(M.r6s_load_util_icons(d, log=False)) == 2)
    check("the default folder is montage_data\\r6s\\utility_icons", M.r6s_util_icon_dir().parts[-2:] == ("r6s", "utility_icons"))
    # scan without utility icons: no crash, no utility data, normal path unchanged
    data = TMP / "data1"
    (data / "r6s" / "icons").mkdir(parents=True)
    T.mk_icon(data / "r6s" / "icons" / "old.png", 43)                   # a V8.0.2 icon: must not be used for kills
    keep = M.DATA
    M.DATA = data
    M._R6S_ICON_CACHE.clear()
    M._R6S_UTIL_CACHE.clear()
    M._R6S_OLD_NOTE[0] = None
    try:
        det = M.Detector("r6s")
        frames = T2.T.M and [np.zeros((400, 806, 3), np.uint8) + 25 for _ in range(45)]
        for f in range(3, 41):
            cv2.rectangle(frames[f], (100, 100), (700, 128), (255, 255, 255), -1)

        def fake(fr):
            if int(fr.max()) < 200:
                return [], []
            return [bx(110, 250, "fireaxeO", "g"), bx(470, 650, "BuffSledge_25", "r")], [[300, 98, 70, 28, 0.9]]
        k = (M.frame_stream, M.ocr_frame)
        M.frame_stream, M.ocr_frame = (lambda *a, **kw: iter(frames)), fake
        try:
            e = M.scan_clip("x.mp4", {"game": "r6s", "v_off": 0.0}, det, CFG)
        finally:
            M.frame_stream, M.ocr_frame = k
        a = M.analyse_entry(e, CFG, "r6s")
        check("no utility icons: the scan works, 1 normal kill, no error, no utility data", not e.get("error") and len(a["kills"]) == 1 and e["util"] == [] and e["util_sig"] == "")
        check("the old icons folder produced no icon rows (not used for kills)", e["rows"] == [] and e["mode"] == "ocr")
        LOG.clear()
        M.r6s_old_icons_note()
        M.r6s_old_icons_note()
        check("the old folder note is logged once", sum("icons is unused (utility icons live in utility_icons)" in l for l in LOG) == 1, str(LOG))
        # utility icons present: the scan stores hits (a utility icon on the row from frame 3 to 40)
        (data / "r6s" / "utility_icons").mkdir()
        T.mk_icon(data / "r6s" / "utility_icons" / "u.png", 44)
        icon = cv2.imdecode(np.fromfile(str(data / "r6s" / "utility_icons" / "u.png"), np.uint8), cv2.IMREAD_GRAYSCALE)
        M._R6S_UTIL_CACHE.clear()
        fr2 = [np.zeros((400, 806, 3), np.uint8) + 25 for _ in range(45)]
        for f in range(3, 41):
            cv2.rectangle(fr2[f], (100, 100), (700, 128), (255, 255, 255), -1)
            T.paste(fr2[f], icon, 300, 100, seed=0) if False else fr2[f].__setitem__((slice(100, 100 + icon.shape[0]), slice(300, 300 + icon.shape[1])), cv2.cvtColor(icon, cv2.COLOR_GRAY2BGR))
        M.frame_stream, M.ocr_frame = (lambda *a, **kw: iter(fr2)), fake
        try:
            e2 = M.scan_clip("x.mp4", {"game": "r6s", "v_off": 0.0}, det, CFG)
        finally:
            M.frame_stream, M.ocr_frame = k
        check("with a utility icon template the scan stores a persistent hit and the icon-set signature", len(e2["util"]) >= 1 and max(h["hits"] for h in e2["util"]) >= 30 and e2["util_sig"] != "", str(e2["util"][:2]))
        a2 = M.analyse_entry(e2, CFG, "r6s")
        check("... and the row it sits in is rejected as utility (the weapon slot is between the killer and the victim names)", a2["kills"] == [] and any(r["reason"].startswith("utility: gadget kill icon") for r in a2["rej"]), str(a2["rej"][:2]))
    finally:
        M.DATA = keep
        M._R6S_ICON_CACHE.clear()
        M._R6S_UTIL_CACHE.clear()


def part2():
    section("2) utility row rejected; normal rows unaffected")
    a = M.analyse_entry(entry([hit()]), CFG, "r6s")
    check("a gadget kill row is NOT a kill", a["kills"] == [])
    rj = [r for r in a["rej"] if r["reason"].startswith("utility: gadget kill icon")]
    check("it is listed in the rejected rows with the utility reason", len(rj) == 1, str(a["rej"]))
    check("its visible window is kept like Valorant's utility rows (vis)", len(a["vis"]) == 1)
    a = M.analyse_entry(entry([]), CFG, "r6s")
    check("a normal row (no utility hit) is a kill", len(a["kills"]) == 1 and a["kills"][0]["weapon"] == "gun" and not a["kills"][0].get("util"))
    a = M.analyse_entry(entry([hit(x=700)]), CFG, "r6s")
    check("a utility icon NOT in the weapon slot (other place on the row's height) does not flag the row", len(a["kills"]) == 1)
    a = M.analyse_entry(entry([hit(y=300)]), CFG, "r6s")
    check("a utility icon on another row's height does not flag it", len(a["kills"]) == 1)
    a = M.analyse_entry(entry([hit(first=200, last=210)]), CFG, "r6s")
    check("a utility icon when the row is not on screen does not flag it", len(a["kills"]) == 1)
    a = M.analyse_entry(entry([hit(hits=3, first=40, last=42)]), CFG, "r6s")
    check("a 3-frame sighting (scenery noise) does not flag the row", len(a["kills"]) == 1)
    e = entry([hit()])
    e["ocr"] = [[f, f, [bx(10, 150, "BuffSledge_25", "g"), bx(340, 520, "fireaxeO", "r")], [[170, 98, 70, 28, 0.9]]] for f in (30, 36, 42, 50, 60, 70)]
    a = M.analyse_entry(e, CFG, "r6s")
    check("a death with the utility icon is still my death (not a kill, not utility)", a["kills"] == [] and len(a["deaths"]) == 1 and not any("utility" in r["reason"] for r in a["rej"]))


def part3():
    section("3) the per-clip override")
    e = entry([hit()])
    base = M.analyse_entry(e, CFG, "r6s")
    util = M.utility_kill_rows(e, CFG, "r6s", base)
    check("utility_kill_rows (same function as Valorant) returns the gadget kill, util=True", len(util) == 1 and util[0].get("util") and util[0]["weapon"] == "util" and "] util [" in util[0]["row"])
    keep = M.DATA
    M.DATA = TMP / "ovdata"
    M.DATA.mkdir(exist_ok=True)
    try:
        clip = TMP / "R6S clip.mp4"
        clip.write_bytes(b"0" * 64)
        rec = {"path": str(clip), "game": "r6s"}
        check("override OFF by default: the row stays rejected", M.apply_utility_override(rec, e, base, CFG, "r6s", M.load_clip_overrides())["kills"] == [])
        M.set_clip_override([str(clip)], True)
        ovs = M.load_clip_overrides()
        adm = {}
        a = M.apply_utility_override(rec, e, base, CFG, "r6s", ovs, adm)
        check("override ON: the gadget kill is admitted as a kill (same function as Valorant)", len(a["kills"]) == 1 and a["kills"][0].get("util"), str(a["kills"]))
        check("... and leaves the rejected list", not any(r["reason"].startswith("utility:") for r in a["rej"]))
        lines = M.utility_override_lines(adm)
        check("log lines are Valorant's: 'utility override: N clip(s) enabled, N utility kill(s) admitted' + 'utility kill allowed by override'",
              lines and lines[0].startswith("utility override: 1 clip(s) enabled, 1 utility kill(s) admitted") and any(l.startswith("utility kill allowed by override:") for l in lines), str(lines))
        normal = entry([])
        bn = M.analyse_entry(normal, CFG, "r6s")
        check("a normal clip with the override ON is unchanged", len(M.apply_utility_override(rec, normal, bn, CFG, "r6s", ovs)["kills"]) == 1)
        check("the override still does nothing for cs2", M.apply_utility_override(rec, e, base, CFG, "cs2", ovs) is base)
    finally:
        M.DATA = keep
    # planner / ledger: the admitted kill is a util event, a ledger placed-via-override note
    it = T2.item(0, 40, [(14.8, "BuffSledge_25")], name="u")
    it["kills"][0]["util"] = True
    cl = [dict(k, tt=k["t"], src=it, off=0.0) for k in it["kills"]]
    ev = M.make_event(cl, [(it, 0.0)], None, CFG, {}, verify=False)
    check("an event with an admitted gadget kill is flagged util (planner: no slow-mo, never the ending)", ev is not None and ev.get("util") is True)
    led = M.KillLedger("r6s")
    led.add_pool([it])
    led.rows[0]["state"], led.rows[0]["info"] = "OVERRIDE_ADMITTED", {"take": "t"}
    check("ledger summary: '[1 of the placed via utility override]'", "[1 of the placed via utility override]" in M.ledger_summary(led), M.ledger_summary(led))
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("GUI: the right-click override menu is R6S + Valorant (same control, nothing else added)", 'if self.m_game.get() not in ("valorant", "r6s") or iid not in self.byp:' in src)
    check("game_pool / Manual list load the overrides for R6S too", src.count('load_clip_overrides() if game in ("valorant", "r6s") else {}') == 1 and src.count('load_clip_overrides() if g in ("valorant", "r6s") else {}') == 1)


def part4():
    section("4) stale cached entries are scanned again")
    keep = M.DATA
    M.DATA = TMP / "data4"
    (M.DATA / "r6s" / "utility_icons").mkdir(parents=True)
    M._R6S_UTIL_CACHE.clear()
    try:
        check("no utility icons: an entry without util_sig is current", M.r6s_entry_stale({"ocr": []}) is False)
        check("an entry with an error is stale", M.r6s_entry_stale({"error": M.R6S_MISSING_MSG}) is True)
        check("a missing entry is not 'stale' (it is just uncached)", M.r6s_entry_stale(None) is False)
        T.mk_icon(M.DATA / "r6s" / "utility_icons" / "u.png", 45)
        M._R6S_UTIL_CACHE.clear()
        check("icons now exist: an entry scanned before them (no util_sig) is scanned again when picked", M.r6s_entry_stale({"ocr": []}) is True)
        sig = M.r6s_icons_sig(M.r6s_load_util_icons(log=False))
        check("... an entry scanned with the current icon set is current", M.r6s_entry_stale({"ocr": [], "util_sig": sig}) is False)
    finally:
        M.DATA = keep
        M._R6S_UTIL_CACHE.clear()


def part5():
    section("5) frozen vs V8.0.2")
    T2.part5(REFS)
    T.part9(REFS, "V8.0")


def partp():
    T.partp("V8.0.2-good")


if __name__ == "__main__":
    for k, fn in (("0", part0), ("1", part1), ("2", part2), ("3", part3), ("4", part4), ("5", part5)):
        if k in PARTS:
            try:
                fn()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                T.check(f"part {k} ran without an exception", False, repr(ex))
    if os.environ.get("V803_PLANS") == "1":
        partp()
    print(f"\n{len(T.FAILS)} FAIL" if T.FAILS else "\nALL OK", f"({time.time() - T.T0:.1f} s)")
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if T.FAILS else 0)
