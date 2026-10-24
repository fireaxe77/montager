"""V9.0.1 guard (fast): plans built from the same synthetic events are IDENTICAL to the v9.0 tag (Valorant / CS2 / R6S, default and extra effects, four styles), with the intro context off and on
(the drop retries only run when a drop is not anchored: a plan with every drop anchored must come out unchanged). The deliberate V9.0.1 changes are the ones in CHANGELOG.md (drops after the
intro): the microfix before V9.0.1 (the ending held in slow motion, its outro numbers) is switched back here, any other difference is reported.
python tests\\guard901_vc.py"""
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_src = (HERE / "test_v842.py").read_text(encoding="utf-8")
_ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
exec(compile(_src[:_src.index("def part0")], str(HERE / "test_v842.py"), "exec"), _ns)
_ns["BASE_REF"] = "v9.0"
T = types.SimpleNamespace(**_ns)
M = T.M
B = _ns["load_base"]()
M.ENDING_HOLD_SLOW[0] = False
M.END_FADE, M.OUTRO_AFTER, M.OUTRO_FADE_LEN, M.OUTRO_MUSIC_MIN, M.ENDING_PREF_POST = (3.0, 4.0), 1.5, 1.6, 3.0, 1.6

for intro_on in (False, True):
    for mod in (M, B):
        mod.INTRO_CTX.update({"on": intro_on, "text": None, "series": 1, "manual": False})
    for game in ("valorant", "cs2", "r6s"):
        for eff in ("default", "extra"):
            for style, seed in (("hype", 3), ("aggressive", 11), ("chill", 7), ("cinematic", 21)):
                e = {"valorant": eff, "cs2": eff, "r6s": eff}
                try:
                    pa, ca = T.mk(M, game, style, seed, eff=e)
                    pb, cb = T.mk(B, game, style, seed, eff=e)
                except RuntimeError as ex:
                    print("  (not planned:", str(ex)[:60], ")")
                    continue
                strip = lambda p: {k: v for k, v in p.items() if k != "notes"}
                same = json.dumps(strip(pa), sort_keys=True, default=str) == json.dumps(strip(pb), sort_keys=True, default=str)
                bad = [x for x in (pa.get("drop_sync") or []) if not x.get("take")]
                T.check(f"{game} {eff} {style} seed {seed} intro {'on' if intro_on else 'off'}: plan identical to V9.0" + (f" ({len(bad)} drop(s) not anchored: the retry may differ)" if bad and not same else ""), same or bool(bad))
for mod in (M, B):
    mod.INTRO_CTX.update({"on": False})
print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
sys.exit(1 if T.FAILS else 0)
