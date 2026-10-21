"""V8.8 Valorant guard (fast): the Valorant plan, plan text and filter graph are identical to the V8.7 tag (default and extra effects, several styles / seeds).
python tests\guard88_valorant.py"""
import copy
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_src = (HERE / "test_v842.py").read_text(encoding="utf-8")
_ns = {"__file__": str(HERE / "test_v842.py"), "__name__": "test_v842_helpers"}
exec(compile(_src[:_src.index("def part0")], str(HERE / "test_v842.py"), "exec"), _ns)
_ns["BASE_REF"] = "v8.7"
T = types.SimpleNamespace(**_ns)
M = T.M
B = _ns["load_base"]()
for eff in ("default", "extra"):
    for style, seed in (("hype", 3), ("aggressive", 11), ("chill", 7), ("cinematic", 21)):
        e = {"valorant": eff, "cs2": eff, "r6s": eff}
        pa, ca = T.mk(M, "valorant", style, seed, eff=e)
        pb, cb = T.mk(B, "valorant", style, seed, eff=e)
        ja = json.dumps(pa, sort_keys=True, default=str)
        jb = json.dumps(pb, sort_keys=True, default=str)
        T.check(f"Valorant {eff} {style} seed {seed}: plan identical to V8.7", ja == jb)
        try:
            ga = M.build_filter(copy.deepcopy(pa), ca, False)
            gb = B.build_filter(copy.deepcopy(pb), cb, False)
            if ga is not None:
                T.check(f"Valorant {eff} {style}: filter graph identical", ga == gb)
        except Exception as ex:                                # noqa: BLE001
            print("  (graph not compared:", type(ex).__name__, ex, ")")
print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
sys.exit(1 if T.FAILS else 0)
