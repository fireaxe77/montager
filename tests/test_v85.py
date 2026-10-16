"""V8.5 fast tests (no render): python tests/test_v85.py"""
import random
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import montage as M                                                                           # noqa: E402

FAILS = []


def check(name, ok, info=""):
    print(("PASS " if ok else "FAIL ") + name + (f"  {info}" if info else ""))
    if not ok:
        FAILS.append(name)


def clips(n, rng):
    return [{"path": f"c{i}.mp4", "times": [5.0 + rng.random(), 6.0 + rng.random()], "rows": [5.2, 6.2], "score": rng.random(), "n": 2, "span": 1.0} for i in range(n)]


def main():
    check("version", M.APP_VERSION == "V8.5", M.APP_VERSION)
    rng = random.Random(4)
    for dur, label in ((120, "short"), (300, "long")):
        an = M.default_song_map(float(dur), 128.0)
        pool = clips(60, rng)
        base = M.optimal_fit(pool, an, "hype")
        M.FULL_CTX["on"] = True
        try:
            fit = M.optimal_fit(pool, an, "hype")
        finally:
            M.FULL_CTX["on"] = False
        sec = (an["beats"][fit["end_beat"]] - an["beats"][fit["start_beat"]])
        if label == "short":
            check("short song: the whole song", sec >= dur - 8, f"section {sec:.0f} s of {dur}")
        else:
            check("long song: 90-150 s section", 89 <= sec <= 150.5, f"section {sec:.0f} s")
        check(f"{label}: default fit unchanged cap 180", base["max"] == min(180, dur - 0.1 - an["beats"][0]) or base["max"] <= 180, f"max {base['max']:.0f}")
    check("FULL_CTX reset", M.FULL_CTX["on"] is False)
    an = M.default_song_map(300.0, 128.0)
    cands = [{"path": f"c{i}", "ks": [4.0, 5.0], "used": "" if i % 2 else "2026-01-01"} for i in range(80)]
    paths, info = M.auto_fill_pick(cands, an, "hype", random.Random(1))
    check("auto fill: unused first", all(not c.get("used") for c in cands if c["path"] in paths[:20]) and len(paths) >= 10, f"{len(paths)} clips, est {info['est']:.0f} s for {info['length']:.0f} s")
    check("auto fill: length capped at 150 s", info["length"] <= M.FULL_CAP_S)
    hues = {n: M._hue_deg(c) for n, c in M.SKY_PALETTE.items()}
    check("sky palette: no yellow / green / neon", all(not (50 <= h <= 170) for h in hues.values()), str({k: round(v) for k, v in hues.items()}))
    check("sky mask row limit", M.SKY_MAX_ROW <= 0.5)
    check("flash weights back in every profile", all("flash" in p["w"] for k, p in M.FEEL_PROFILES.items() if k != "mix"))
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL PASS")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
