"""V8.21 tests. FAST unit tests only (no render, no OCR, no real clips needed).
  0) title-bar version + both changelogs
  1) CS2: a short outlined row the OCR could not split no longer hides a kill: the name-kill fallback keeps a single read of my name when a settled (>= 10 frames) unread row stands there;
     nothing else about the fallback changes (no unread row / short unread row / two reads without an unread row behave as in V8.2)
  2) game audio level: 0-1 per game; default (no per-game key) = the one old level (0.6); the -30 dB music rule still subtracts after it; V8.2 dB setting is gone
python tests\\test_v821.py   (parts: V821_PARTS=0,1,2)"""
import copy
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.argv = [sys.argv[0]]
import montage as M  # noqa: E402

PARTS = [x for x in os.environ.get("V821_PARTS", "0,1,2").split(",") if x]
FAILS = []


def check(name, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        FAILS.append(name)


def section(t):
    print("\n" + t)


CFG = copy.deepcopy(M.DEFAULT_CONFIG)


def part0():
    section("0) version + changelog")
    check("APP_VERSION is V8.21", M.APP_VERSION == "V8.21")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.21 on top, then V8.2", cl[0].startswith("## V8.21") and cl[1].startswith("## V8.2 "), str(cl[:2]))
    sm = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8").splitlines()
    sh = [l for l in sm if l.startswith("## V")]
    check("simple changelog: V8.21 headline on top, then V8.2", "CS2 clutch kills no longer cut short" in sh[0] and sh[1].startswith("## V8.2 "), str(sh[:2]))
    body = "\n".join(sm[sm.index(sh[0]):sm.index(sh[1])])
    check("V8.21 entry has the 2 plain points", body.count("\n- ") == 2, body)


def name_kill(t=14.667, hits=1, ks=1.0):
    return {"t": t, "victim": "-P2W-", "ks": ks, "hits": hits}


def part1():
    section("1) CS2 name-kill fallback with an unread outlined row")
    sc = {"tracks": [], "frames": 462, "fps": 30, "v_off": 0.0}
    a = {"kills": [name_kill(2.333, 14), name_kill(9.067, 21), name_kill(14.667, 1)]}

    def run(unread, hits=1):
        aa = {"kills": [dict(k) for k in a["kills"]]}
        aa["kills"][2]["hits"] = hits
        b = {"kills": [{"t": 2.333}, {"t": 9.067}], "rows": [], "rej": [], "unread": unread}
        return M.cs2_name_kills_kept(aa, b, sc, "unit")
    check("settled unread row (20 frames) + 1 read of my name: the kill is kept", [k["t"] for k in run([(14.733, 20)])] == [14.667])
    check("unread row of only 5 frames: not kept", run([(14.733, 5)]) == [])
    check("no unread row: not kept (as before)", run([]) == [])
    check("unread row far from the kill: not kept", run([(11.0, 20)]) == [])
    check("2 reads but no unread row: still not kept (needs a shaped outlined track, as before)", run([], hits=2) == [])
    check("name-based list not longer than the border list: nothing added",
          M.cs2_name_kills_kept({"kills": [name_kill(2.3, 5)]}, {"kills": [{"t": 2.3}], "rows": [], "rej": [], "unread": [(14.7, 20)]}, sc, "unit") == [])


def part2():
    section("2) game audio level 0-1 per game")
    check("V8.2 dB setting removed", not hasattr(M, "game_level_db") and not hasattr(M, "GAME_LEVEL_RANGE"))
    cfg = dict(CFG)
    base = M._game_gain(cfg, -14.0, -30.0)
    check("default: every game gets exactly the old gain", all(M._game_gain(cfg, -14.0, -30.0, g) == base for g in M.GAMES))
    check("default level is the one old key (0.6)", all(abs(M.game_level(cfg, g) - float(cfg["game_audio_level"])) < 1e-9 for g in M.GAMES))
    cfg2 = dict(cfg, game_audio_level_cs2=0.3, game_audio_level_r6s="0.9")
    check("per-game key is used for that game only", M.game_level(cfg2, "cs2") == 0.3 and M.game_level(cfg2, "r6s") == 0.9 and M.game_level(cfg2, "valorant") == cfg["game_audio_level"])
    g_cs, _l = M._game_gain(cfg2, None, None, "cs2")
    g_def, _l = M._game_gain(cfg2, None, None, "valorant")
    check("lower level = lower gain in dB", g_cs < g_def)
    check("garbage per-game value falls back to the old level", M.game_level(dict(cfg, game_audio_level_cs2="oops"), "cs2") == cfg["game_audio_level"])
    src = (ROOT / "montage.py").read_text(encoding="utf-8")
    check("music-over-gameplay lowering still subtracts after the gain", 'gdb = round(gdb - amt, 2)' in src and src.index("_game_gain(cfg, song_lufs, au[\"lufs\"], game)") < src.index("gdb = round(gdb - amt, 2)"))
    check("Settings: one 0-1 entry per game, no dB spinbox", 'self.sn[f"game_audio_level_{g_}"]' in src and "set_glv" not in src)


for p in PARTS:
    globals()["part" + p]()
print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nALL OK")
sys.exit(1 if FAILS else 0)
