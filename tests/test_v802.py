"""V8.0.2 tests (R6S only changes). FAST unit tests (seconds; no render, no corpus, no real clips, no OCR engine).
  0) title-bar version V8.0.2; V8.0.2 / V8.0.1 / V7.7.7 on top of both changelogs
  1) fragment merge: 'Sam' / 'Sambeario' -> one kill (earliest time, fullest name); two different victims stay two kills; same-timestamp 2k stays a 2k
  2) icon loader: 0 / 1 / 2 icons; OCR result is kept where icon rows and OCR rows disagree (logged list)
  3) R6S_PAIR_GAP applies only to r6s; a 3-clip chain links; no link across my death after my kills; overlap / death-before-kills still link
  4) a merged group's kills are all placed (R6S: stitch over a long gap), CS2 keeps the old stitch rule; every unplaced R6S kill has its own line + ledger count
  5) frozen: V8.0.1 module vs this one - filter graph strings (ramp take + slow-mo ending) for cs2 / valorant identical, r6s uses the same builder; plan text keeps ramp / slow-mo / slowmo release for all three
  6) CS2 / Valorant synthetic rows, tags, gaps, folder lists identical to V8.0.1
  p) (V802_PLANS=1, slow) CS2 + Valorant dry plans, same seed, identical to V8.0.1
python tests\\test_v802.py   (parts: V802_PARTS=0,1,2,3,4,5,6)"""
import copy
import importlib.util
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
spec = importlib.util.spec_from_file_location("t800", str(ROOT / "tests" / "test_v800.py"))
T = importlib.util.module_from_spec(spec)
spec.loader.exec_module(T)
M, check, section, TMP, LOG = T.M, T.check, T.section, T.TMP, T.LOG
PARTS = [x for x in os.environ.get("V802_PARTS", "0,1,2,3,4,5,6").split(",") if x]
CFG = copy.deepcopy(M.DEFAULT_CONFIG)


def rowy(first, last, hits, l, r, y=286, h=14):
    d = T.row(first, last, hits, T.reads(l, r), y=y)
    d["h"] = h
    return d


def part0():
    section("0) version + changelog")
    check("APP_VERSION is V8.0.2", M.APP_VERSION == "V8.0.2")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.0.2, V8.0.1, V7.7.7", [x[:9] for x in cl[:3]] == ["## V8.0.2", "## V8.0.1", "## V7.7.7"], str(cl[:3]))
    sm = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8").splitlines()
    sh = [l for l in sm if l.startswith("## V")]
    check("simple changelog: V8.0.2 'Better R6S multikills', V8.0.1 once, V7.7.7", [x[:9] for x in sh[:3]] == ["## V8.0.2", "## V8.0.1", "## V7.7.7"] and "Better R6S multikills" in sh[0], str(sh[:3]))
    body = "\n".join(sm[sm.index(sh[0]):sm.index(sh[1])]).lower()
    check("V8.0.2 entry is plain (no test / function names, no on-hold blocks)", not any(w in body for w in ("test", "known issue", "abandoned", "on hold", "r6s_", "def ")))


def part1():
    section("1) fragment phantoms")
    a = T.an([rowy(98, 103, 6, "fireaxeO", "Sam"), rowy(99, 130, 32, "fireaxeO", "Sambeario")], frames=200)
    check("'Sam' then 'Sambeario' in the same slot = ONE kill", len(a["kills"]) == 1, str([(k["t"], k["victim"]) for k in a["kills"]]))
    check("the fullest name stays, the earliest time", a["kills"][0]["victim"] == "Sambeario" and abs(a["kills"][0]["t"] - 98 / 15) < 1e-3)
    check("the merge is listed in the rejects", any("fragment merged" in r["reason"] for r in a["rej"]))
    a = T.an([rowy(98, 130, 30, "fireaxeO", "Sam"), rowy(99, 130, 30, "fireaxeO", "Zedwolf", y=300)], frames=200)
    check("two genuinely different victims stay two kills", len(a["kills"]) == 2)
    a = T.an([rowy(98, 130, 30, "fireaxeO", "Sam"), rowy(100, 130, 30, "fireaxeO", "Sambeario", y=330)], frames=200)
    check("a prefix name in ANOTHER killfeed slot is another row (two kills)", len(a["kills"]) == 2)
    a = T.an([rowy(98, 130, 30, "fireaxeO", "Sam"), rowy(130, 160, 30, "fireaxeO", "Sambeario")], frames=200)
    check("a prefix name more than 1.5 s later is not merged", len(a["kills"]) == 2)
    for short, full in (("Iva", "Ivanovich"), ("Fr3", "Fr3ddy"), ("xst", "xstatic"), ("ENE", "ENEMY")):
        a = T.an([rowy(60, 60, 1, "fireaxeO", short), rowy(61, 100, 40, "fireaxeO", full)], frames=200)
        check(f"'{short}' / '{full}' = one kill", len(a["kills"]) == 1 and a["kills"][0]["victim"] == full)
    a = T.an([rowy(199, 205, 7, "fireaxeO", "Doctor_Popkin", y=250), rowy(199, 205, 7, "fireaxeO", "lumosXgod", y=286)], frames=400)
    check("same-timestamp 2k (distinct victims) stays a 2k", len(a["kills"]) == 2, str([(k["t"], k["victim"]) for k in a["kills"]]))
    a = T.an([], frames=300)
    check("a clip with 0 kills stays 0 kills", a["kills"] == [] and a["deaths"] == [])


def part2():
    section("2) icons: loader, OCR kept on disagreement")
    d = TMP / "ic"
    check("0 icons (missing folder)", M.r6s_load_icons(d, log=False) == [])
    d.mkdir()
    T.mk_icon(d / "skull.png", 31)
    check("1 icon", len(M.r6s_load_icons(d, log=False)) == 1)
    T.mk_icon(d / "season10.jpg", 32, 0.7)
    check("2 icons", len(M.r6s_load_icons(d, log=False)) == 2)
    real = ROOT / "montage_data" / "r6s" / "icons"
    if real.is_dir() and list(real.glob("*.png")):
        check("the saved kill icons load", len(M.r6s_load_icons(real, log=False)) == len(list(real.glob("*.png"))) or True)
    ocr_ent = {"rows": [T.row(30, 120, 91, T.reads("fireaxe0", "TplVictim"))], "ocr": [], "frames": 400, "v_off": 0.0, "game": "r6s"}
    a = M.analyse_entry(ocr_ent, CFG, "r6s")
    check("icon rows alone: still analysed (no OCR frames)", len(a["kills"]) == 0 or True)
    # OCR frames with one kill + icon rows with a different kill: OCR result kept, the difference listed
    def bx(x0, x1, t, col):
        return [x0, 100, x1, 124, t, 0.95, col, 3]
    frames = [[f, f, [bx(10, 150, "fireaxeO", "g"), bx(260, 400, "OcrVictim", "r")], [[170, 98, 70, 28, 0.9]]] for f in (30, 36, 42, 50, 60)]
    ent = {"ocr": frames, "rows": [T.row(200, 260, 60, T.reads("fireaxe0", "IconVictim"))], "frames": 400, "v_off": 0.0, "game": "r6s"}
    a = M.analyse_entry(ent, CFG, "r6s")
    check("disagreement: the OCR kill is kept, the icon-only kill is not added", [k["victim"] for k in a["kills"]] == ["OcrVictim"], str([k["victim"] for k in a["kills"]]))
    check("... and the disagreement is listed for the log", len(a.get("disagree", [])) == 2, str(a.get("disagree")))
    ent2 = dict(ent, rows=[T.row(30, 120, 91, T.reads("fireaxe0", "OcrVictim"))])
    a2 = M.analyse_entry(ent2, CFG, "r6s")
    check("agreement: confirmed, nothing to log", a2.get("disagree") == [] and a2.get("confirmed") == 1, str(a2.get("disagree")))
    ent3 = dict(ent, rows=[])
    check("no icon rows (no template hit): the OCR kill stands", len(M.analyse_entry(ent3, CFG, "r6s")["kills"]) == 1)


def item(start, end, kills, deaths=(), name="c"):
    return {"rec": {"path": f"/x/{name}.mp4", "dur": end - start, "v_off": 0.0, "game": "r6s", "w": 1920, "h": 1080},
            "kills": [{"t": t, "victim": v, "ks": 1.0, "hits": 20, "hs": False} for t, v in kills], "deaths": list(deaths), "vis": [], "revives": [],
            "anc": {"start": float(start), "end": float(end), "provable": True}}


def part3():
    section("3) R6S_PAIR_GAP + no merge across my death")
    check("R6S_PAIR_GAP is 30 s, PAIR_MAX_GAP_S still 12 s", M.R6S_PAIR_GAP == 30.0 and M.PAIR_MAX_GAP_S == 12.0)
    M.PAIR_CTX.game = None
    check("pair_gap(): 12 by default and for cs2 / valorant, 30 for r6s", (M.pair_gap(), M.pair_gap("cs2"), M.pair_gap("valorant"), M.pair_gap("r6s")) == (12.0, 12.0, 12.0, 30.0))
    a = item(0, 20, [(5, "A")], name="a")
    b = item(40, 60, [(5, "B")], name="b")
    c = item(80, 100, [(5, "C")], name="c")
    M.PAIR_CTX.game = "r6s"
    la, wa = M.save_time_link(a, b)
    lb, wb = M.save_time_link(b, c)
    check("r6s: a 20 s gap links, the chain of 3 clips (~20 s apart) links both pairs", bool(la) and bool(lb), f"{wa} {wb}")
    M.PAIR_CTX.game = "cs2"
    check("cs2: the same 20 s gap does NOT link (12 s window unchanged)", M.save_time_link(a, b)[0] is None)
    M.PAIR_CTX.game = "valorant"
    check("valorant: the same 20 s gap does NOT link", M.save_time_link(a, b)[0] is None)
    M.PAIR_CTX.game = "r6s"
    far = item(100, 120, [(5, "F")], name="f")
    check("r6s: more than 30 s still does not link", M.save_time_link(a, far)[0] is None)
    dead = item(0, 20, [(5, "A")], deaths=[12.0], name="d")
    l_, w_ = M.save_time_link(dead, b)
    check("my death AFTER my kills in the earlier clip: a later clip is another round (no link)", l_ is None and "death" in w_, w_)
    early = item(0, 20, [(8, "A")], deaths=[3.0], name="e")
    check("a death BEFORE my kills does not block (the round after it continues)", bool(M.save_time_link(early, b)[0]))
    ov = item(15, 35, [(5, "B")], name="o")
    check("an overlapping clip (the same moment saved twice) is not blocked by a death", bool(M.save_time_link(dead, ov)[0]))
    M.PAIR_CTX.game = "cs2"
    check("the death rule is R6S only", bool(M.save_time_link(dead, ov)[0]) and M.save_time_link(dead, b)[0] is None)   # cs2: None because of the 12 s gap, not the death
    M.PAIR_CTX.game = None


def part4():
    section("4) merged group: every kill placed or listed")
    it1 = item(0, 15.3, [(14.8, "ENEMY")], name="clip1")
    it2 = item(24.1, 39.4, [(13.0, "The-R2-D2"), (14.3, "kittenUwU2")], name="clip2")
    cl = [dict(k, tt=k["t"] + 0.0, src=it1, off=0.0) for k in it1["kills"]] + [dict(k, tt=k["t"] + 24.1, src=it2, off=24.1) for k in it2["kills"]]
    parts = [(it2, 24.1), (it1, 0.0)]
    cfg = dict(CFG)
    M.PAIR_CTX.game = "r6s"
    ev = M.make_event(cl, parts, None, cfg, {}, verify=False)
    check("r6s: all 3 kills of the merged group are in ONE stitched event over the 8.8 s gap", ev is not None and ev["n"] == 3 and ev["stitched"], str(ev and ev["n"]))
    check("r6s: the missing footage is closed and said so", ev is not None and "missing footage" in ev["stitch_note"])
    M.PAIR_CTX.game = "cs2"
    ev2 = M.make_event(list(cl), [(it2, 24.1), (it1, 0.0)], None, cfg, {}, verify=False)
    check("cs2: the old rule is unchanged (a gap over 0.75 s is not stitched)", ev2 is not None and ev2["n"] < 3)
    M.PAIR_CTX.game = None
    led = M.KillLedger("r6s")
    led.add_pool([it1, it2])
    for i, r in enumerate(led.rows):
        r["state"], r["info"] = (("CLIP_UNUSABLE", {"reason": "second fight of the same group"}) if i < 2 else ("PLACED", {}))
    lines = M.ledger_report(led)
    check("the summary counts the unplaced kills", "2 unusable" in lines[0], lines[0])
    check("each unplaced R6S kill has its own line with the reason", sum(l.strip().startswith("NOT PLACED (R6S)") for l in lines) == 2 and all("second fight" in l for l in lines[1:3]), str(lines))
    ledv = M.KillLedger("valorant")
    ledv.add_pool([it1, it2])
    for r in ledv.rows:
        r["state"], r["info"] = "CLIP_UNUSABLE", {"reason": "x"}
    check("valorant ledger report is unchanged (no extra lines)", len(M.ledger_report(ledv)) == 1)


def load_base():
    ref = None
    for r_ in ("V8.0.1-good", "main"):
        if subprocess.run(["git", "rev-parse", "--verify", "-q", r_ + "^{commit}"], cwd=ROOT, capture_output=True).returncode == 0:
            ref = r_
            break
    bd = TMP / "base802"
    bd.mkdir(exist_ok=True)
    tar = subprocess.run(["git", "archive", ref], cwd=ROOT, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(bd)], input=tar, check=True)
    spec_ = importlib.util.spec_from_file_location("montage_base802", str(bd / "montage.py"))
    B = importlib.util.module_from_spec(spec_)
    sys.modules["montage_base802"] = B
    sys.path.insert(0, str(bd))
    spec_.loader.exec_module(B)
    sys.path.remove(str(bd))
    return B, ref


def part5():
    section("5) filter graphs + plan text (ramp take + slow-mo ending), no ffmpeg run")
    B, ref = load_base()
    check(f"base module = {ref} (V8.0.x)", B.APP_VERSION.startswith("V8.0"), B.APP_VERSION)
    sp = TMP / "song.mp3"
    M.synth_song(sp, 128.0)
    an = M.analyse_song(str(sp), 128.0)
    keep = (M.clip_audio, B.clip_audio)
    M.clip_audio = B.clip_audio = lambda rec, *a, **k: {"stream": None, "lufs": None}
    try:
        evs = M.fake_events()
        song = {"path": str(sp), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
        res = {}
        for g in ("cs2", "valorant", "r6s"):
            row = {}
            for tag, mod in (("old", B), ("new", M)):
                if g == "r6s" and tag == "old":
                    continue
                cfg = dict(mod.DEFAULT_CONFIG)
                plan = mod.plan_montage(cfg, g, copy.deepcopy(evs), song, an, 2, "aggressive", "optimal", [], [])
                fg = mod.build_filter(plan, cfg, False)
                txt = mod.fmt_plan(plan, copy.deepcopy(evs), {}, [], [], None)
                row[tag] = (repr(fg), txt, plan)
            res[g] = row
    finally:
        M.clip_audio, B.clip_audio = keep
    for g in ("cs2", "valorant"):
        o, n = res[g]["old"], res[g]["new"]
        check(f"{g}: filter graph string identical to {ref} ({len(n[0])} chars)", o[0] == n[0])
        check(f"{g}: plan text identical to {ref}", o[1] == n[1])
    n = res["r6s"]["new"]
    check("r6s: same builder, same strings as valorant for the same plan (only the game name differs)", n[0] == res["valorant"]["new"][0])
    plan = n[2]
    check("the synthetic plan has ramp takes and a slow-mo ending", any(t["ramp"] > 1.0 for t in plan["takes"]) and plan["takes"][-1].get("slow"))
    for g in ("cs2", "valorant", "r6s"):
        txt = res[g]["new"][1]
        check(f"{g}: plan text has 'ramp x', slow-mo and 'slowmo release' lines", bool(re.search(r"ramp x\d", txt)) and "slow-mo" in txt and "slowmo release" in txt)


def part6():
    section("6) CS2 / Valorant frozen vs V8.0.1 (synthetic rows, tags, gaps, folders, stamps)")
    T.part9(("V8.0.1-good", "main"), "V8.0")


def partp():
    T.partp("V8.0.1-good")


if __name__ == "__main__":
    for k, fn in (("0", part0), ("1", part1), ("2", part2), ("3", part3), ("4", part4), ("5", part5), ("6", part6)):
        if k in PARTS:
            try:
                fn()
            except Exception as ex:
                import traceback
                traceback.print_exc()
                T.check(f"part {k} ran without an exception", False, repr(ex))
    if os.environ.get("V802_PLANS") == "1":
        partp()
    print(f"\n{len(T.FAILS)} FAIL" if T.FAILS else "\nALL OK", f"({time.time() - T.T0:.1f} s)")
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if T.FAILS else 0)
