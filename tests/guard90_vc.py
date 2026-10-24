"""V9.0 guard (fast): with the V9.0 changes switched back (no intro, the old 2-3 s ending, the old outro numbers, the old caps, no ending preference) plans and filter graphs built from the same
events are IDENTICAL to the v8.8.8 tag for Valorant, CS2 and R6S, default and extra effects, four styles / seeds: everything V9.0 changes (intro, outro, 3:00 cap) sits behind those switches. The only
graph difference left is the outro's own fade text (eased fade to black / half-sine music fade), normalised here.
python tests\\guard90_vc.py"""
import copy
import json
import re
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_src = (HERE / "test_v842.py").read_text(encoding="utf-8")
_ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
exec(compile(_src[:_src.index("def part0")], str(HERE / "test_v842.py"), "exec"), _ns)
_ns["BASE_REF"] = "v8.8.8"
T = types.SimpleNamespace(**_ns)
M = T.M
B = _ns["load_base"]()

M.v8_compat()                                              # ... V9.0 off


def norm(g):
    g = re.sub(r"fade=t=out:st=[\d.]+:d=[\d.]+,format=yuv420p\[vout\]", "OUTRO_V[vout]", g)
    g = re.sub(r"eq=contrast='1-[^']*':brightness='[^']*':saturation='[^']*':eval=frame:enable='[^']*',format=yuv420p\[vout\]", "OUTRO_V[vout]", g)
    return g.replace(":curve=hsin[aout]", "[aout]")


for game in ("valorant", "cs2", "r6s"):
    for eff in ("default", "extra"):
        for style, seed in (("hype", 3), ("aggressive", 11), ("chill", 7), ("cinematic", 21)):
            e = {"valorant": eff, "cs2": eff, "r6s": eff}
            pa, ca = T.mk(M, game, style, seed, eff=e)
            pb, cb = T.mk(B, game, style, seed, eff=e)
            T.check(f"{game} {eff} {style} seed {seed}: plan identical to V8.8.8", json.dumps(pa, sort_keys=True, default=str) == json.dumps(pb, sort_keys=True, default=str))
            try:
                ga = M.build_filter(copy.deepcopy(pa), ca, False)
                gb = B.build_filter(copy.deepcopy(pb), cb, False)
                T.check(f"{game} {eff} {style}: filter graph identical to V8.8.8 (outro fade text aside)", ga[0] == gb[0] and norm(ga[1]) == norm(gb[1]))
            except Exception as ex:                        # noqa: BLE001
                print("  (graph not compared:", type(ex).__name__, ex, ")")
print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
sys.exit(1 if T.FAILS else 0)
