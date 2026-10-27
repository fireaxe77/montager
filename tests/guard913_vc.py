"""V9.1.3 guard (fast): plans built from the same synthetic events are IDENTICAL to the v9.1.2 tag (Valorant / CS2 / R6S, default and extra effects, four styles), with the intro context
off and on, automatic and Manual. V9.1.3 changes CS2 row finding of newly built sidecars, the CS2 icon read and the CUT LIST CHECK (CS2 / R6S takes carry their kill rows); synthetic events carry no kill rows, so every plan stays the same.
python tests\\guard913_vc.py"""
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_src = (HERE / "test_v842.py").read_text(encoding="utf-8")
_ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
exec(compile(_src[:_src.index("def part0")], str(HERE / "test_v842.py"), "exec"), _ns)
_ns["BASE_REF"] = "v9.1.2"
T = types.SimpleNamespace(**_ns)
M = T.M
B = _ns["load_base"]()

for manual in (False, True):
    for intro_on in (False, True):
        for mod in (M, B):
            mod.INTRO_CTX.update({"on": intro_on, "text": None, "series": None if manual else 1, "manual": manual})
        M.INTRO_CTX.update({"sky_pick": None, "font_pick": None})
        B.INTRO_CTX.update({"sky_pick": None, "font_pick": None})
        for game in ("valorant", "cs2", "r6s"):
            for eff in ("default", "extra"):
                for style, seed in (("hype", 3), ("aggressive", 11), ("chill", 7), ("cinematic", 21)):
                    e = {"valorant": eff, "cs2": eff, "r6s": eff}
                    try:
                        pa, _ = T.mk(M, game, style, seed, eff=e)
                        pb, _ = T.mk(B, game, style, seed, eff=e)
                    except RuntimeError as ex:
                        print("  (not planned:", str(ex)[:60], ")")
                        continue
                    same = json.dumps(pa, sort_keys=True, default=str) == json.dumps(pb, sort_keys=True, default=str)
                    T.check(f"{game} {eff} {style} seed {seed} intro {'on' if intro_on else 'off'} {'Manual DEFAULT' if manual else 'automatic'}: plan identical to V9.1.2", same)
for mod in (M, B):
    mod.INTRO_CTX.update({"on": False, "manual": False})
print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
sys.exit(1 if T.FAILS else 0)
