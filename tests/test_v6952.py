"""V6.9.5.2: SONGMAPV2 tempo lock + honest grid confidence + the "Songmap V2 (auto, V1 fallback)" option. All audio generated in code.
   python tests/test_v6952.py
Only this version's checks + V1 integrity + the Valorant / CS2 guards (older suites are run separately: test_v695.py)."""
import hashlib
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
import warnings
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402
import songmap_v2                                                                             # noqa: E402
from songmap_v2 import build as B2, grid                                                      # noqa: E402
import songmap_compare as C                                                                   # noqa: E402
import test_v695 as T5                                                                        # noqa: E402  (mp3 helper only; its main() is not run)

T_ALL = time.time()
FAILS, SECTIONS = [], []
BASE_REF = os.environ.get("V6952_BASE", "082229c")          # V6.9.5.1 (V1 + Valorant / CS2 reference)
REAL_DATA = ROOT / "montage_data"
SR = 22050


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


class section:
    def __init__(self, title):
        self.title = title

    def __enter__(self):
        self.t = time.time()
        print(f"== {self.title} ==")

    def __exit__(self, *a):
        SECTIONS.append((self.title, time.time() - self.t))
        print(f"   [{self.title}: {time.time() - self.t:.1f} s]")


def gen(bpm, dur=45.0, pattern="every", seed=1, jitter=0.0, lead=0.3, rand_hits=None):
    """Mono 22.05 kHz track. pattern 'every': a kick on every beat; 'alt': kick / snare alternating (kicks every other beat); hats on the off-beats.
    rand_hits=<mean gap s>: kicks at random times (no tempo). Returns (y, true kick times)."""
    rng = np.random.default_rng(seed)
    y = np.zeros(int((dur + lead) * SR) + SR, np.float32)
    n = np.arange(int(0.25 * SR))

    def add(sig, at):
        s = int(round(at * SR))
        e = min(len(y), s + len(sig))
        if 0 <= s < e:
            y[s:e] += sig[:e - s]
    kick = (np.sin(2 * np.pi * (48 + 70 * np.exp(-n / (0.02 * SR))) * n / SR) * np.exp(-n / (0.06 * SR))).astype(np.float32)
    snare = ((rng.standard_normal(len(n)) * np.exp(-n / (0.035 * SR)) * 0.7 + np.sin(2 * np.pi * 190 * n / SR) * np.exp(-n / (0.05 * SR)) * 0.5) * 0.55).astype(np.float32)
    nh = np.arange(int(0.04 * SR))
    hat = (rng.standard_normal(len(nh)) * np.exp(-nh / (0.008 * SR)) * 0.12).astype(np.float32)
    if rand_hits:
        t = lead
        while t < dur:
            add(kick * rng.uniform(0.5, 1.0), t)
            t += rng.exponential(rand_hits) + 0.08
        return np.clip(y, -1, 1), np.array([])
    per = 60.0 / bpm
    truth, k = [], 0
    while lead + k * per < dur + lead - 0.5:
        t = lead + k * per
        tj = t + (rng.normal(0, jitter) if jitter else 0.0)
        if pattern == "every" or k % 2 == 0:
            add(kick * (1.0 if pattern == "every" or k % 4 == 0 else 0.8), tj)
            truth.append(t)
        else:
            add(snare, tj)
        add(hat, t + per / 2)
        k += 1
    return np.clip(y, -1, 1), np.array(truth)


def write_wav(path, y):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())


def finite(o):
    if isinstance(o, dict):
        return all(finite(v) for v in o.values())
    if isinstance(o, (list, tuple)):
        return all(finite(v) for v in o)
    return not isinstance(o, float) or bool(np.isfinite(o))


def build(tmp, y, name="t.wav", **kw):
    p = Path(tmp) / name
    write_wav(p, y)
    return songmap_v2.build_songmap_v2(str(p), **kw)


def octave_of(a, b, tol=0.01):
    return any(abs(a / (b * f) - 1) <= tol for f in (1.0, 0.5, 2.0))


def part_known(tmp):
    with section("1) known BPM tracks: tempo, confidence, kick offset"):
        for bpm, pat, true_oct in [(87, "every", False), (100, "alt", False), (128, "alt", False), (140, "every", False), (175, "alt", False),
                                   (208, "alt", True), (127.3, "every", False), (127.3, "alt", False)]:
            y, tr = gen(bpm, pattern=pat)
            m = build(tmp, y)
            off = np.abs(grid.kick_offsets(np.array(m["beats"]), tr, 0.2)) * 1000
            got = m["bpm"]
            ok_t = (abs(got / bpm - 1) <= 0.01) or (true_oct and abs(got / (bpm / 2) - 1) <= 0.01)
            check(ok_t and 60 <= got <= 200, f"{bpm} BPM ({pat}): tempo {got}" + (" (true 208 -> exact octave 104 allowed, never above 200)" if true_oct else ""))
            check(m["v2"]["grid_confidence"] >= 0.8 and len(off) and np.median(off) < 10,
                  f"{bpm} BPM ({pat}): confidence {m['v2']['grid_confidence']}, kick median offset {np.median(off):.2f} ms; {m['v2']['confidence_log']}")


def part_hints(tmp):
    with section("2) wrong CSV / V1 tempo (half, double, unrelated)"):
        y, tr = gen(128, pattern="alt")
        for kw in ({"csv_bpm": 64.0}, {"csv_bpm": 256.0}, {"csv_bpm": 192.0}, {"v1_bpm": 64.0}, {"v1_bpm": 256.0}, {"v1_bpm": 90.0},
                   {"csv_bpm": 64.0, "v1_bpm": 200.0}):
            m = build(tmp, y, **kw)
            check(abs(m["bpm"] / 128 - 1) < 0.01, f"true 128, hints {kw}: final tempo {m['bpm']}; candidates {[(c['bpm_in'], c['score']) for c in m['v2']['lock']['candidates']]}")
        # the lock itself, with a wrong estimate AND wrong hints: kicks decide among the harmonic candidates
        yy, tr = gen(100, pattern="alt")
        p = Path(tmp) / "h.wav"
        write_wav(p, yy)
        from songmap_v2 import timebase, events
        yd, sr = timebase.decode(str(p))
        F = grid.features(yd, sr)
        ev = events.detect(F)
        kt = np.array([e["raw_time"] for e in ev if e["type"] in ("kick", "bass") and e["strength"] >= 0.5])
        ks = np.array([e["strength"] for e in ev if e["type"] in ("kick", "bass") and e["strength"] >= 0.5])
        ht = np.array([e["raw_time"] for e in ev if e["type"] in ("kick", "bass", "snare", "accent") and e["strength"] >= 0.15])
        for est, csv, v1 in [(200.0, 50.0, 200.0), (50.0, 200.0, 50.0), (200.0, None, 25.0), (50.0, 400.0, 200.0)]:
            beats, sid, segs, info = grid.lock_grid(kt, ks, ht, len(yd) / sr, est, v1, csv)
            check(abs(info["chosen_bpm"] / 100 - 1) < 0.01 and all(60 <= s["bpm"] <= 200 for s in segs), f"estimate {est}, V1 {v1}, CSV {csv} -> {info['chosen_bpm']}")


def part_irregular(tmp):
    with section("3) irregular rhythm: low confidence, tempo and segments in range, plausible beat count"):
        for seed, gap in [(1, 0.4), (2, 0.4), (3, 0.15), (4, 0.9)]:
            y, _ = gen(0, 90.0, rand_hits=gap, seed=seed)
            m = build(tmp, y)
            bt = np.array(m["beats"])
            iv = np.diff(bt)
            segs = m["v2"]["segments"]
            n_exp_lo, n_exp_hi = 90.0 * 60 / 60, 90.0 * 200 / 60
            check(m["v2"]["grid_confidence"] < 0.5, f"random hits seed {seed}: confidence {m['v2']['grid_confidence']} < 0.5 ({m['v2']['confidence_log']})")
            check(60 <= m["bpm"] <= 200 and all(60 <= s["bpm"] <= 200 for s in segs) and iv.min() >= 0.29 and iv.max() <= 1.01,
                  f"random hits seed {seed}: tempo {m['bpm']}, segments {[s['bpm'] for s in segs]}, beat intervals {iv.min():.2f}-{iv.max():.2f} s")
            check(n_exp_lo <= len(bt) <= n_exp_hi and abs(len(bt) - m["dur"] * m["bpm"] / 60) < 0.05 * len(bt) + 3, f"random hits seed {seed}: {len(bt)} beats for {m['dur']:.0f} s")
        # a tempo change keeps its segments, inside the range
        y, tr = T5.synth([("verse", 12), ("drop", 12)], bpm=100, tempo_map=[(100, 12), (120, 12)])
        from scipy.signal import resample_poly
        m = build(tmp, resample_poly(y, 1, 2).astype(np.float32), "tc.wav")
        check(all(60 <= s["bpm"] <= 200 for s in m["v2"]["segments"]) and 60 <= m["bpm"] <= 200, f"tempo change 100 -> 120: segments {[s['bpm'] for s in m['v2']['segments']]}")


def part_nasty(tmp):
    with section("4) silence, DC offset, clipping: no NaN, no crash"):
        y, _ = gen(128, 40.0, "alt")
        cases = {"silence": np.zeros(SR * 30, np.float32), "dc": np.full(SR * 30, 0.4, np.float32), "clip": np.clip(y * 4 + 0.25, -1, 1),
                 "dc+music": np.clip(y + 0.5, -1, 1), "half silence": np.concatenate([np.zeros(SR * 20, np.float32), y[:SR * 25]])}
        for name, a in cases.items():
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                try:
                    m, err = build(tmp, a, "n.wav"), None
                except Exception as ex:
                    m, err = None, f"{type(ex).__name__}: {ex}"
            ok = (m is None and err is not None and "steady beat" in err) or (m is not None and finite(m) and 60 <= m["bpm"] <= 200)
            check(ok, f"{name}: {'map, finite, tempo ' + str(m['bpm']) if m else err}")


def part_auto(tmp):
    with section("5) auto option: V2 / V1 per song, fallback, caches, dropdown"):
        old = M.use_data_dir(Path(tmp) / "adata")
        try:
            yc, _ = T5.synth([("intro", 4), ("verse", 8), ("drop", 6), ("outro", 4)], bpm=128)
            good = Path(tmp) / "good.mp3"
            T5.to_mp3(yc, good)
            yn, _ = gen(0, 60.0, rand_hits=0.4, seed=2)
            bad = Path(tmp) / "noisy.wav"
            write_wav(bad, yn)
            logged = T5.logged
            check(M.SONGMAP_DEFAULT == "v1" and M.songmap_version({}) == "v1", "default stays Songmap V1")
            check(list(M.SONGMAP_CHOICES.values()) == ["Songmap V1", "Songmap V2"] and M.SONGMAP_CHOICES_UI["v2auto"] == "Songmap V2 (auto, V1 fallback)", "'Songmap V1' / 'Songmap V2' entries unchanged, new entry added")
            M.save_json(M.CONFIG_PATH, dict(M.load_config(), songmap_version="v2auto"))
            check(M.load_config().get("songmap_version") == "v2auto" and M.songmap_version() == "v2auto", "config value songmap_version = 'v2auto' persists")
            src = inspect.getsource(M.App)
            check("SONGMAP_CHOICES_UI" in src and "set_songmap" in src, "Settings dropdown offers the new entry")
            m, lines = logged(M.get_songmap, str(good))
            au = [l for l in lines if l.startswith("songmap auto: good.mp3 -> ")]
            check(m.get("songmap_version") == "v2" and au and au[0].startswith("songmap auto: good.mp3 -> V2 (conf ") and " ms vs V1 " in au[0], f"confident track -> V2 chosen and logged: {au[:1]}")
            v1cache = Path(M.SONG_CACHE).read_bytes()
            v2file = Path(M.DATA) / songmap_v2.CACHE_NAME
            cj = json.loads(v2file.read_text())
            akeys = [k for k in cj if k.endswith("|auto")]
            check(len(akeys) == 1 and cj[akeys[0]]["choice"] == "v2" and "v2_median_ms" in cj[akeys[0]] and "v1_median_ms" in cj[akeys[0]], f"decision + numbers cached in the V2 cache: {cj[akeys[0]] if akeys else None}")
            m, lines = logged(M.get_songmap, str(good))
            check(m.get("songmap_version") == "v2" and any("songmap auto:" in l for l in lines) and not any(l.startswith("songmap v2:") for l in lines), "second request: V2 map + decision from the cache, no new analysis")
            m, lines = logged(M.get_songmap, str(bad))
            au = [l for l in lines if l.startswith("songmap auto: noisy.wav -> ")]
            check(m.get("songmap_version") == "v1-auto" and au and au[0].startswith("songmap auto: noisy.wav -> V1 (") and "confidence" in au[0], f"noisy track -> V1 chosen and logged: {au[:1]}")
            check(m["beats"] == M.get_songmap(str(bad), None, "v1")["beats"], "the auto-V1 map is the V1 map")
            check(Path(M.SONG_CACHE).exists() and not any("|auto" in k for k in json.loads(Path(M.SONG_CACHE).read_text())) and all("songmap_v2" not in k for k in json.loads(Path(M.SONG_CACHE).read_text())),
                  "V1 cache holds only V1 entries (V2 / auto entries live in the V2 cache)")
            n2 = len(json.loads(v2file.read_text()))
            m1 = M.get_songmap(str(good), None, "v1")
            check("songmap_version" not in m1 and len(json.loads(v2file.read_text())) == n2, "'Songmap V1' call: V1 map, V2 cache untouched")
            m2, lines = logged(M.get_songmap, str(good), None, "v2")
            check(m2.get("songmap_version") == "v2" and "songmap_auto" not in m2, "'Songmap V2' call: plain V2 map exactly as before (no auto field)")

            def hook():
                raise ValueError("boom")
            ex = Path(tmp) / "exc.mp3"
            T5.to_mp3(yc, ex)
            M.SONGMAP_V2_HOOK[0] = hook
            try:
                m, lines = logged(M.get_songmap, str(ex), None, "v2auto")
            finally:
                M.SONGMAP_V2_HOOK[0] = None
            check(m["songmap_version"] == "v1-fallback" and "songmap v2 fallback: exc.mp3 (ValueError: boom)" in lines, f"injected V2 exception -> V1 + fallback log: {lines[:2]}")
            check(len(Path(M.SONG_CACHE).read_bytes()) >= len(v1cache), "V1 cache only grew by V1 entries")
        finally:
            M.SONGMAP_V2_HOOK[0] = None
            M.restore_data_dir(old)


def part_compare(tmp):
    with section("6) compare tool: auto column + new numbers, same seed behaviour"):
        d = Path(tmp) / "songs"
        d.mkdir()
        yg, _ = gen(128, 45.0, "alt")
        yn, _ = gen(0, 45.0, rand_hits=0.4, seed=3)
        write_wav(d / "Good - A.wav", yg)
        write_wav(d / "Noisy - B.wav", yn)
        out = Path(tmp) / "cmp"
        state = C.run(M, [{"path": str(d / "Good - A.wav"), "why": "t"}, {"path": str(d / "Noisy - B.wav"), "why": "t"}], 5, out, say=lambda *a: None, seed=7)
        rs = {r["song"]: r for r in state["results"]}
        g, n = rs.get("Good - A.wav"), rs.get("Noisy - B.wav")
        check(g is not None and n is not None and not state["errors"], f"both songs analysed ({state['errors']})")
        if g and n:
            check(g["auto_would_pick"] == "V2" and n["auto_would_pick"] == "V1", f"auto would pick: good {g['auto_reason']} | noisy {n['auto_reason']}")
            check(g["chosen_tempo"] and g["tempo_candidates"] and g["confidence_parts"]["kick_on_grid"] is not None, "chosen tempo, candidate scores and confidence components in the entry")
        rep = (out / "report.md").read_text(encoding="utf-8")
        js = json.loads((out / "report.json").read_text())
        check("auto would pick" in rep and "| auto would pick |" in rep and "auto_would_pick" in js["all_scores"][0], "report.md and report.json carry the auto column")


V1_FUNCS = ["build_song_map", "fit_grid", "decode_mono", "analyse_song", "analyse_song_v4", "synth_song", "local_onsets", "map_score", "_norm01", "smooth",
            "_beat_this_beats", "song_pool", "ebur128_lufs", "pick_song"]
FROZEN_V2 = ["songmap_v2/events.py", "songmap_v2/sections.py", "songmap_v2/timebase.py", "songmap_v2/__init__.py"]


def part_v1(tmp):
    with section("7) V1 integrity + frozen files + Valorant / CS2 guards"):
        r = subprocess.run(["git", "show", f"{BASE_REF}:montage.py"], cwd=str(ROOT), capture_output=True)
        if r.returncode:
            check(False, f"base commit {BASE_REF} not available")
            return
        bdir = Path(tmp) / "base"
        bdir.mkdir()
        (bdir / "montage.py").write_bytes(r.stdout)
        os.environ["MONTAGER_DATA"] = str(Path(tmp) / "base_data")
        try:
            spec = importlib.util.spec_from_file_location("montage_base6952", str(bdir / "montage.py"))
            Bm = importlib.util.module_from_spec(spec)
            sys.modules["montage_base6952"] = Bm
            spec.loader.exec_module(Bm)
        finally:
            del os.environ["MONTAGER_DATA"]
        sha = lambda f: hashlib.sha256(inspect.getsource(f).encode()).hexdigest()
        diff = [n for n in V1_FUNCS if sha(getattr(M, n)) != sha(getattr(Bm, n))]
        check(not diff, f"SHA-256 of the source of {len(V1_FUNCS)} V1 functions equals the base commit's {diff}")
        t = Path(tmp) / "v1.mp3"
        y, _ = T5.synth([("intro", 4), ("verse", 8), ("drop", 6)], bpm=128)
        T5.to_mp3(y, t)
        check(json.dumps(M.build_song_map(str(t)), sort_keys=True) == json.dumps(Bm.build_song_map(str(t)), sort_keys=True), "V1 output on a generated song is identical to the base commit")
        ch = subprocess.run(["git", "diff", "--name-only", "origin/v6.9.5.1", "--"] + FROZEN_V2, cwd=str(ROOT), capture_output=True, text=True).stdout.split()
        check(not ch, f"events.py / sections.py / timebase.py / __init__.py unchanged vs V6.9.5.1 {ch}")
        import test_v693 as T
        view = lambda mod, e, g: json.dumps(mod.analyse_entry(e, {}, g), sort_keys=True, default=str)
        for game in ("valorant", "cs2"):
            ents = T.gen_entries(100, game)
            nd = sum(view(M, e, game) != view(Bm, e, game) for e in ents)
            kn = sum(len(M.analyse_entry(e, {}, game)["kills"]) for e in ents)
            check(nd == 0 and kn > 20, f"{game}: kills, timestamps, deaths, revives of 100 generated clips identical to the base ({nd} differences, {kn} kills)")


def main():
    real_before = T5.snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t6952_"))
    old = M.use_data_dir(tmp / "data")
    try:
        for part in (part_known, part_hints, part_irregular, part_nasty, part_auto, part_compare, part_v1):
            part(tmp)
    finally:
        M.restore_data_dir(old)
    with section("real montage_data"):
        check(T5.snapshot(REAL_DATA) == real_before, f"real montage_data byte-identical after the tests ({len(real_before)} files{'; folder absent' if not real_before else ''})")
    total = time.time() - T_ALL
    print("section times: " + ", ".join(f"{t.split(')')[0]} {s:.0f}s" for t, s in SECTIONS))
    print(f"total test time {total:.1f} s" + ("" if total < 180 else "  (OVER the 3 minute limit)"))
    if total >= 180:
        FAILS.append("over 3 minutes")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
