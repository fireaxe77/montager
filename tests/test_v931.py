"""V9.3.1 tests (fast; no render):
  0) title-bar version V9.3.1, both changelogs carry V9.3.1 on top, the Settings changelog has no developer-facing lines left (no 'unchanged' lines, no tool / function names)
  1) CS2 never shows my death: a trade (death dated at / a hair before the last kill) and a death up to 4 s after it limit the footage; other games as before
  2) render set-up: audio_prefetch reads every clip's packet list and 60 fps check once, in parallel, and leaves the values build_filter would read one by one
  3) real data (needs MONTAGER_DATA = a COPY of montage_data): the 2024.01.28 - 21.02.33.15 clip (the death at 2:08 of FS_CS2_V9.3.0_2026-10-28) forms no event with a tail
python tests\\test_v931.py   (parts: V931_PARTS=0,1,2,3)"""
import os
import random
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="v931_"))
os.environ.setdefault("MONTAGER_DATA", str(TMP / "data"))
import montage as M                                                                           # noqa: E402

PARTS = [x for x in os.environ.get("V931_PARTS", "0,1,2").split(",") if x]
FAILS = []


def check(msg, ok, extra=""):
    print(("  ok   " if ok else "  FAIL ") + msg + ("" if ok else f"   {extra}"))
    if not ok:
        FAILS.append(msg)


def part0():
    print("0) version and changelogs")
    check("title-bar version V9.3.1", M.APP_VERSION == "V9.3.1")
    for f in ("CHANGELOG.md", "docs/CHANGELOG_SIMPLE.md"):
        txt = (ROOT / f).read_text(encoding="utf-8")
        i_ = txt.find("## V9.3.1")
        check(f"{f}: V9.3.1 is the newest entry", 0 <= i_ < txt.find("## V9.3.0"))
    simple = (ROOT / "docs/CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    low = simple.lower()
    for bad in ("unchanged", "not affected", "stay exactly as they were", "stays exactly", "dropcheck", "dropsave", "drop check tool", "comparison tool", "repo cleanup work"):
        check(f"Settings changelog has no '{bad}'", bad not in low)
    entries = [e for e in simple.split("\n## ")[1:]]
    check("every Settings changelog entry still has a point", all(len([l for l in e.splitlines()[1:] if l.startswith("- ")]) >= 1 for e in entries))
    check("all versions kept (V1 ... V9.3.1)", len(entries) >= 100 and entries[-1].startswith("V1 ") and entries[0].startswith("V9.3.1"))


def part1():
    print("1) CS2 death never shown")
    f = M.death_after_for
    check("a trade (death dated at the last kill) -> 0.0 (no take can end before it)", f("cs2", [12.867], 12.867) == 0.0)
    check("death 0.27 s before the last kill is the same moment -> 0.0", f("cs2", [14.467], 14.733) == 0.0)
    check("death 0.5 s after the kill -> 0.5", abs(f("cs2", [13.0], 12.5) - 0.5) < 1e-9)
    check("death 3.5 s after the kill limits the tail (was 2.0 s)", abs(f("cs2", [16.0], 12.5) - 3.5) < 1e-9)
    check("death 5 s after the kill: none", f("cs2", [17.5], 12.5) is None)
    check("death 2 s before the last kill: none (the death lock handles kills after a death)", f("cs2", [10.5], 12.5) is None)
    check("nearest death wins", abs(f("cs2", [12.9, 13.4], 12.5) - 0.4) < 1e-9)
    for g in ("valorant", "r6s", None):
        check(f"{g}: a trade is not a 'death after' (as before)", f(g, [12.867], 12.867) is None)
        check(f"{g}: death 0.5 s after -> 0.5 (as before)", abs(f(g, [13.0], 12.5) - 0.5) < 1e-9)
        check(f"{g}: death 3.5 s after -> none (as before)", f(g, [16.0], 12.5) is None)
    M.CS2_DEATH_TAIL_ON[0] = False
    try:
        check("switch off: CS2 as V9.3.0", f("cs2", [12.867], 12.867) is None and f("cs2", [16.0], 12.5) is None)
    finally:
        M.CS2_DEATH_TAIL_ON[0] = True
    ev = {"death_after": 0.0, "post": 0.68, "times": [12.867], "rows": [12.867], "pre": 12.0}
    check("an event with death_after 0.0 has no usable tail (why_no_take names the death)", "my death" in M.why_no_take(ev))


def part2():
    print("2) render set-up: audio_prefetch")
    takes = [{"srcs": [{"path": f"c{i % 5}.mp4", "audio": True, "a_stream": 0}, {"path": "m.mp4", "audio": True, "mute": True}]} for i in range(12)]
    takes.append({"path": "solo.mp4", "audio": True})
    calls, fps_calls, live, peak = [], [], [0], [0]
    lock = threading.Lock()
    orig_a, orig_f = M._audio_packets, M.src_is_60

    def fake_a(path, a_stream):
        with lock:
            calls.append((path, a_stream))
            live[0] += 1
            peak[0] = max(peak[0], live[0])
        time.sleep(0.05)
        with lock:
            live[0] -= 1
        M._APKT[(str(path), int(a_stream))] = [0.0, 0.02]
        return [0.0, 0.02]

    def fake_f(path):
        with lock:
            fps_calls.append(path)
        M._FPS60_CACHE[str(path)] = True
        return True
    M._audio_packets, M.src_is_60 = fake_a, fake_f
    saved_a, saved_f = dict(M._APKT), dict(M._FPS60_CACHE)
    M._APKT.clear()
    M._FPS60_CACHE.clear()
    try:
        t0 = time.time()
        M.audio_prefetch(takes)
        dt = time.time() - t0
    finally:
        M._audio_packets, M.src_is_60 = orig_a, orig_f
        M._APKT.clear()
        M._APKT.update(saved_a)
        M._FPS60_CACHE.clear()
        M._FPS60_CACHE.update(saved_f)
    check("every clip with sound read once (5 clips + the single-clip take; the muted one not)", sorted(calls) == sorted({(f"c{i}.mp4", 0) for i in range(5)} | {("solo.mp4", 0)}), str(sorted(calls)))
    check("the 60 fps check ran once per clip file (incl. the muted one)", sorted(fps_calls) == sorted({f"c{i}.mp4" for i in range(5)} | {"m.mp4", "solo.mp4"}), str(sorted(fps_calls)))
    check("the reads ran together (not one after the other)", peak[0] > 1 and dt < 0.05 * len(calls) * 0.8, f"peak {peak[0]}, {dt:.2f} s")


def part3():
    print("3) real data: the clip with my death at the kill")
    cfg = M.load_config()
    paths = [p["path"] for p in M.scan_clips(cfg) if p.get("game") == "cs2" and "2024.01.28 - 21.02.33.15" in p["path"]]
    if not paths:
        check("the clip is in the data copy", False, "not found")
        return
    pool, _st = M.game_pool(cfg, "cs2", paths=paths)
    check("the clip has its kill and its death at the same time", bool(pool) and pool[0]["deaths"] and abs(pool[0]["deaths"][0] - pool[0]["kills"][-1]["t"]) < 0.1, str(pool and (pool[0]["kills"], pool[0]["deaths"])))
    evs = M.build_events(pool, "cs2", cfg, random.Random(1))
    evs = evs[0] if isinstance(evs, tuple) else evs
    check("its event has no tail (death_after 0.0)", len(evs) == 1 and evs[0].get("death_after") == 0.0, str([e.get("death_after") for e in evs]))
    check("...so it forms no take", len(evs) == 1 and "my death" in M.why_no_take(evs[0]))


if __name__ == "__main__":
    for p_ in PARTS:
        {"0": part0, "1": part1, "2": part2, "3": part3}[p_]()
    print("\nFAILED: " + "; ".join(FAILS) if FAILS else "\nall ok")
    sys.exit(1 if FAILS else 0)
