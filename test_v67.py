"""V6.7: CS2 kill registration (over- and under-counting). No render, no display needed:  python3 test_v67.py
Compares every CS2 change with the previous version (origin/main, read with `git show`) and proves Valorant did not change:
  * every Valorant clip in montage_data (kills cache) must give the identical kill count AND identical kill timestamps (any difference fails),
  * the same on 400 generated Valorant clips (garbled rows, shifting lists, pre-clip rows ...).
CS2 fixtures are built from the raw OCR reads quoted in the bug report (no clips needed)."""
import importlib.util
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import montage as M                                                                           # noqa: E402

FAILS = []


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


def load_old(ref="031cb64"):
    """A previous version as a second module, with its own empty data folder. Default: V6.5.2 (031cb64), the version V6.7 was
    measured against (origin/main now carries V6.7 itself)."""
    src = subprocess.run(["git", "show", ref + ":montage.py"], cwd=HERE, capture_output=True, check=True).stdout
    d = Path(tempfile.mkdtemp(prefix="montager_v67_old_"))
    (d / "montage_old.py").write_bytes(src)
    keep = os.environ.get("MONTAGER_DATA")
    os.environ["MONTAGER_DATA"] = str(d / "data")
    try:
        spec = importlib.util.spec_from_file_location("montage_old", d / "montage_old.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["montage_old"] = mod
        spec.loader.exec_module(mod)
    finally:
        if keep is None:
            os.environ.pop("MONTAGER_DATA", None)
        else:
            os.environ["MONTAGER_DATA"] = keep
    return mod


# ------------------------------------------------------------------ raw OCR fixtures
FPS = M.FPS
PITCH, RH = 34, 26


def _rows_frame(f, prev_ocr_f, rows, shift_mode):
    """rows: [{'start', 'end', 'k': [variants], 'v': [variants], 'slot'}] -> boxes, blobs of the OCR frame f."""
    boxes, blobs = [], []
    vis = sorted(((r["start"], n, r) for n, r in enumerate(rows) if r["start"] <= f < r["end"]), key=lambda x: x[:2])
    for idx, (_, n, r) in enumerate(vis):
        if shift_mode:                                     # newest row at the bottom, every newer row pushes the older ones up
            y = 40 + (4 - (len(vis) - 1 - idx)) * PITCH
        else:
            y = 40 + r["slot"] * PITCH
        kt = r["k"][(f // 3 + n) % len(r["k"])]
        vt = r["v"][(f // 3 + 2 * n) % len(r["v"])]
        first = prev_ocr_f is None or prev_ocr_f < r["start"]
        moved = r.get("_y") is not None and r["_y"] != y
        appear = f if (first or moved) else max(r["start"], prev_ocr_f)
        r["_y"] = y
        boxes.append([100, y - RH // 2, 100 + 14 * len(kt), y + RH // 2, kt, 0.95, "", appear])
        blobs.append([330, y - 10, 90, 20, 0.7])
        boxes.append([450, y - RH // 2, 450 + 14 * len(vt), y + RH // 2, vt, 0.9, "", appear])
    return boxes, blobs


def build_entry(rows, dur_s, shift_mode=False, game="cs2"):
    for r in rows:
        r.pop("_y", None)
    ocr, prev = [], None
    for f in range(0, int(dur_s * FPS), 4):                  # ~3.75 OCR calls a second, like the scanner
        b, g = _rows_frame(f, prev, rows, shift_mode)
        ocr.append([f, f, b, g])
        prev = f
    return {"ocr": ocr, "frames": int(dur_s * FPS), "v_off": 0.0, "game": game, "v": M.CACHE_V}


def row(start_s, end_s, victims, killers=("fireaxe",), slot=0):
    return {"start": int(start_s * FPS), "end": int(end_s * FPS), "k": list(killers), "v": list(victims), "slot": slot}


def replay_entry(shift):
    """'Replay 2026-06-25 01-27-36.mov': a 3k with a deagle; the rows are re-read with garbled killer and victim text."""
    rows = [row(10.6, 18.6, ["OO TEKAAB", "TEKAAB", "ouO TaKAOD", "TEKAAB"], ["fireaxm", "fireaxe", "fireaxn", "fireaxe"], 0),
            row(14.3, 22.3, ["Sergeant", "SergeanT", "Sergeant"], ["fireaxe", "fireaxe", "fireaxm"], 1),
            row(15.7, 23.7, ["Pandemic", "aapa3kAeM", "Pandemic", "PandemiC"], ["fireaxe", "fireaxn", "fireaxe"], 2)]
    return build_entry(rows, 26.0, shift)


def dvr_entry(shift):
    """'Counter-strike 2 2025.02.03 - 09.12.42.24.DVR.mp4': 'Dneelko' already on screen at 0:00 (pre-clip) and read as 'Oneelkn'
    / 'Oneelke' / 'Onee lke' later; another victim read 'AkaMaAkaTa' / 'AxkaMaikaTa' / 'AkaMaRKaTa'. Two real kills."""
    rows = [row(2.5, 9.0, ["Gus", "Gus"], ["Bob", "Bob"], 3),          # somebody else's kill arrives and pushes the list
            row(0.0, 6.0, ["Dneelko", "Dneelko", "Oneelkn", "Oneelke", "Onee lke"], ["fireaxe"], 0),
            row(4.0, 12.0, ["AkaMaAkaTa", "AxkaMaikaTa", "AkaMaRKaTa", "AkaMaAkaTa"], ["fireaxe", "fireaxe", "flreaxe"], 1),
            row(7.5, 15.5, ["Zhukov", "Zhukov", "Zhukoy"], ["fireaxe"], 2)]
    return build_entry(rows, 18.0, shift)


def kills_of(mod, entry, game):
    a = mod.analyse_entry(entry, {}, game)
    return [k["t"] for k in a["kills"]]


# ------------------------------------------------------------------ Valorant regression
def rand_entry(rng):
    names = ["fireaxe", "fireaxm", "flreaxe", "Ryuk", "clean", "clean2", "ap15", "apT5", "NightOwl", "xX_Kid_Xx", "Zeta", "Zeta1", "Shadow"]
    rows = []
    for _ in range(rng.randint(0, 7)):
        s = rng.uniform(0, 30)
        vs = [rng.choice(names) + rng.choice(["", "", "l", "0", " "]) for _ in range(rng.randint(1, 4))]
        ks = [rng.choice(["fireaxe", "fireaxe", "fireaxm", "Zeta", "fireaxe+Ryuk"]) for _ in range(rng.randint(1, 3))]
        rows.append(row(s, s + rng.uniform(1, 9), vs, ks, rng.randint(0, 4)))
    return build_entry(rows, 40.0, rng.random() < 0.5, "valorant")


def sig(a):
    return ([(k["t"], k["row"], k["hits"], k["victim"], round(k["ks"], 4), k["hs"]) for k in a["kills"]], a["deaths"], a["revives"],
            [(r["t"], r["reason"]) for r in a["rej"]])


def cached_entries():
    """[(key, entry)] of every scanned clip in the kills cache (montage_data/kills_v*/): the cached raw OCR rows."""
    import json
    out = []
    for f in sorted(M.DATA.glob("kills_v*/*.json")):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        e = j.get("e")
        if isinstance(e, dict) and e.get("ocr"):
            out.append((j.get("key", f.name), e))
    return out


def valorant_regression(old):
    diffs, n = [], 0
    real = [(k, e) for k, e in cached_entries() if e.get("game") == "valorant"]
    for key, e in real:
        n += 1
        a0, a1 = old.analyse_entry(e, {}, "valorant"), M.analyse_entry(e, {}, "valorant")
        if sig(a0) != sig(a1) or [k["t"] for k in a0["kills"]] != [k["t"] for k in a1["kills"]]:
            diffs.append(key)
    if real:
        check(not diffs, f"VALORANT cache: {n} real clips, kill count and every timestamp identical to origin/main ({len(diffs)} differ)")
    else:
        print(f"  NOTE  no Valorant clips in the kills cache here ({M.KILLS_CACHE}) - the real-cache regression ran on 0 clips; "
              "run this test on the machine with montage_data to cover it")
    rng = random.Random(67)
    bad, total, nk = 0, 400, 0
    for _ in range(total):
        e = rand_entry(rng)
        for g in ("valorant", None):
            a0, a1 = old.analyse_entry(e, {}, g), M.analyse_entry(e, {}, g)
            nk += len(a1["kills"])
            if sig(a0) != sig(a1):
                bad += 1
    check(bad == 0, f"VALORANT generated: {total} clips x 2 calls ({nk} kills): kills, timestamps, deaths, revives, rejection reasons identical ({bad} differ)")


# ------------------------------------------------------------------ audio
def make_two_track_clip(path, shot_at, shots_on_track2=True):
    """5 s clip, audio track 1 silent, audio track 2 = silence + (optionally) a gunshot burst at `shot_at` s."""
    import numpy as np
    import soundfile as sf
    sr = 44100
    n = 5 * sr
    rng = np.random.default_rng(3)
    t1 = np.zeros(n, np.float32)
    t2 = np.zeros(n, np.float32)
    if shots_on_track2:
        i0 = int(shot_at * sr)
        t2[i0:i0 + 4000] += (rng.standard_normal(4000) * 0.7 * np.exp(-np.arange(4000) / 600)).astype(np.float32)
    w1, w2 = str(path) + ".1.wav", str(path) + ".2.wav"
    sf.write(w1, t1, sr)
    sf.write(w2, t2, sr)
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=320x240:r=15:d=5", "-i", w1, "-i", w2,
                        "-map", "0:v", "-map", "1:a", "-map", "2:a", "-c:v", "mpeg4", "-c:a", "aac", "-t", "5", str(path)],
                       capture_output=True)
    return r.returncode == 0


def audio_tests(old):
    d = Path(tempfile.mkdtemp(prefix="mt_v67_clip_"))
    cfg = dict(M.DEFAULT_CONFIG, audio_mode="auto")
    k = {"t": 3.0, "ks": 0.85, "hs": False, "row": "[fireaxe] gun [Sergeant]", "hits": 1, "victim": "Sergeant", "needs_shot": True, "weapon": "gun"}

    def run(mod, clip, game):
        it = {"rec": {"path": str(clip), "audio": True, "game": game, "w": 320, "h": 240}, "kills": [dict(k)], "deaths": [], "revives": [],
              "vis": [], "rej": []}
        mod.verified_kills([it], cfg)
        return len(it["kills"]), [r["reason"] for r in it["rej"]]

    clips = {}
    for label, shots in (("gunshot on track 2, track 1 silent", True), ("every track silent (no gunshots anywhere)", False)):
        clip = d / (("shots" if shots else "noshots") + ".mp4")
        if not make_two_track_clip(clip, 2.9, shots):
            print("  NOTE  ffmpeg could not build the two-track test clip - audio test skipped")
            return
        clips[label] = clip
        b, a = run(old, clip, "cs2"), run(M, clip, "cs2")
        print(f"        {label}: before kept {b[0]} {b[1]} | after kept {a[0]} {a[1]}")
        check(a[0] == 1, f"CS2 1-sighting kill, {label}: kept after (before: {'kept' if b[0] else 'rejected - no gunshot to confirm it'})")
        check(b[0] == 0, "  (and the old version rejected it, so the test does exercise the bug)")
    for label, clip in clips.items():          # Valorant reads track 1 exactly as before
        b, a = run(old, clip, "valorant"), run(M, clip, "valorant")
        check(a == b, f"VALORANT gunshot step identical on the same clip, {label} (before {b} / after {a})")


# ------------------------------------------------------------------ main
def main():
    old = load_old()
    print("== name normalisation ==")
    same = [("Dneelko", "Oneelkn"), ("Dneelko", "Oneelke"), ("Dneelko", "Onee lke"), ("AkaMaAkaTa", "AxkaMaikaTa"), ("AkaMaAkaTa", "AkaMaRKaTa"),
            ("Sergeant", "Sergeаnt"), ("Hans", "Нans"), ("rnarco", "marco"), ("vvolf", "wolf"), ("IIya", "llya")]
    for a, b in same:
        check(M.ocr_ratio(a, b) >= M.CS2_SAME_NAME, f"same player: '{a}' ~ '{b}' ({M.ocr_ratio(a, b):.0f})")
    diff = [("Dneelko", "AkaMaAkaTa"), ("Kristof", "Kristina"), ("player1", "player2"), ("Zhukov", "Pandemic"), ("Sergeant", "Marcello"), ("Nika", "Mika")]
    for a, b in diff:
        check(M.ocr_ratio(a, b) < M.CS2_SAME_NAME, f"different players: '{a}' != '{b}' ({M.ocr_ratio(a, b):.0f})")

    print("== CS2 fixtures (before = origin/main, after = this version) ==")
    table = []
    for name, fn, want in (("Replay 2026-06-25 01-27-36.mov", replay_entry, 3),
                           ("Counter-strike 2 2025.02.03 - 09.12.42.24.DVR.mp4", dvr_entry, 2)):
        for shift in (False, True):
            e = fn(shift)
            b, a = kills_of(old, e, "cs2"), kills_of(M, e, "cs2")
            table.append((name + (" (list shifts)" if shift else ""), len(b), len(a), want))
            check(len(a) == want, f"{name}{' (list shifts)' if shift else ''}: {len(b)} -> {len(a)} kills (expected {want}) at {[round(t, 1) for t in a]}")

    print("== different players with similar-length names stay two kills ==")
    rows = [row(3.0, 11.0, ["Kristof"], ["fireaxe"], 0), row(6.0, 14.0, ["Kristina"], ["fireaxe"], 1)]
    for shift in (False, True):
        check(len(kills_of(M, build_entry(rows, 16.0, shift), "cs2")) == 2, f"Kristof / Kristina: two kills (list shifts: {shift})")
    rows = [row(3.0, 11.0, ["player1"], ["fireaxe"], 0), row(6.0, 14.0, ["player2"], ["fireaxe"], 1)]
    check(len(kills_of(M, build_entry(rows, 16.0, False), "cs2")) == 2, "player1 / player2: two kills")
    rows = [row(3.0, 11.0, ["Sergeant"], ["fireaxe"], 0), row(30.0, 38.0, ["Sergeant"], ["fireaxe"], 0)]
    check(len(kills_of(M, build_entry(rows, 42.0, False), "cs2")) == 1, "the same victim twice inside one round (30 s apart) is one kill")
    rows = [row(3.0, 11.0, ["Sergeant"], ["fireaxe"], 0), row(150.0, 158.0, ["Sergeant"], ["fireaxe"], 0)]
    check(len(kills_of(M, build_entry(rows, 162.0, False), "cs2")) == 2, "the same name in two different rounds (147 s apart) stays two kills")

    print("== audio: gunshot confirmation on the track the clip has sound on ==")
    audio_tests(old)

    print("== VALORANT regression ==")
    valorant_regression(old)

    print("== before / after kill counts ==")
    cache = cached_entries()
    for key, e in cache:
        if e.get("game") == "cs2":
            b, a = len(old.analyse_entry(e, {}, "cs2")["kills"]), len(M.analyse_entry(e, {}, "cs2")["kills"])
            if a != b:
                print(f"  {key.split('|')[0][-60:]:60s}  {b} -> {a}")
    if not cache:
        print("  (no kills cache in this environment - fixtures built from the report instead)")
    for nm, b, a, w in table:
        print(f"  {nm[:60]:60s}  {b} -> {a}   (expected {w})")
    print(("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED:\n  " + "\n  ".join(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
