"""V6.9.5.1: SONGMAPV2 bugfix round (length-mismatch crash, NaN loudness) + compare tool robustness. All audio generated in code.
   python tests/test_v6951.py
Only this version's checks + V1 integrity + the Valorant / CS2 guards. The older tests/test_v695 + root test_v695.py are run separately."""
import hashlib
import importlib.util
import inspect
import json
import math
import os
import random
import re
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
from scipy.signal import resample_poly                                                       # noqa: E402
import montage as M                                                                           # noqa: E402
import songmap_v2                                                                             # noqa: E402
import songmap_compare as C                                                                   # noqa: E402
from songmap_v2 import grid, sections, timebase                                               # noqa: E402
import test_v695 as T5                                                                        # noqa: E402  (generator helpers; its main() is not run)

T_ALL = time.time()
FAILS, SECTIONS = [], []
BASE_REF = os.environ.get("V6951_BASE", "88a9710")          # v6.9.5
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


def write_wav22(path, y):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())


def base_song(bars=11, bpm=128):
    y, tr = T5.synth([("verse", bars)], bpm=bpm)
    return resample_poly(y, 1, 2).astype(np.float32), tr


def finite_walk(o, path="map"):
    """Paths of every non-finite float inside a nested dict / list."""
    bad = []
    if isinstance(o, dict):
        for k, v in o.items():
            bad += finite_walk(v, f"{path}.{k}")
    elif isinstance(o, (list, tuple)):
        for i, v in enumerate(o):
            bad += finite_walk(v, f"{path}[{i}]")
            if len(bad) > 5:
                break
    elif isinstance(o, float) and not math.isfinite(o):
        bad.append(path)
    return bad


def part_lengths(tmp):
    with section("1) length sweep: no exception for any song length"):
        y22, tr = base_song()
        n0 = len(y22)
        fails = []
        residues = set()
        for k in range(0, 66):                                  # 66 consecutive lengths: every residue mod 32 (hop) twice, odd and even
            y = y22[:n0 - k]
            residues.add(len(y) % grid.HOP)
            try:
                F = grid.features(y, SR)
                n = F["n"]
                for a in list(F["A"].values()) + list(F["R"].values()) + list(F["E"].values()):
                    assert len(a) == n, "band array length"
                assert len(grid.onset_mix(F)) == n and len(grid.onset_linear(F)) == n
            except Exception as ex:
                fails.append((len(y), f"{type(ex).__name__}: {ex}"))
        check(not fails and len(residues) == grid.HOP, f"stage arrays consistent for 66 lengths ({len(residues)} residues mod {grid.HOP}, odd and even) {fails[:2]}")
        per = 60.0 / 128 * 4
        lens = [n0, n0 - 1, n0 - 2, n0 - 16, n0 - 31, int(per * SR * 5) // grid.HOP * grid.HOP, int(per * SR * 5) // grid.HOP * grid.HOP + 1,
                int(per * SR * 5) // grid.HOP * grid.HOP - 1, int(per * SR * 4.5), 20 * SR + 1, 20 * SR]
        bad = []
        for n in lens:
            y = y22[:n] if n <= n0 else y22
            p = Path(tmp) / f"len_{n}.wav"
            write_wav22(p, y)
            try:
                m = songmap_v2.build_songmap_v2(str(p))
                assert len(m["beats"]) == len(m["strength"]) == len(m["energy"])
            except RuntimeError as ex:
                if "too short" not in str(ex) and "steady beat" not in str(ex):
                    bad.append((n, f"RuntimeError: {ex}"))
            except Exception as ex:
                bad.append((n, f"{type(ex).__name__}: {ex}"))
        check(not bad, f"full V2 analysis for {len(lens)} lengths around bar / hop boundaries: no exception {bad[:2]}")
        p = Path(tmp) / "short.wav"
        write_wav22(p, y22[:5 * SR])
        try:
            songmap_v2.build_songmap_v2(str(p))
            ok = False
        except RuntimeError:
            ok = True
        except Exception as ex:
            ok = False
        check(ok, "a 5 s song is refused with a clean RuntimeError (the dispatcher turns it into a fallback), not a numpy error")
        big = np.tile(y22, 17)
        p = Path(tmp) / "long.wav"
        write_wav22(p, big)
        m = songmap_v2.build_songmap_v2(str(p))
        check(m["dur"] > 360 and len(m["beats"]) > 700 and not finite_walk(m), f"{m['dur']:.0f} s (6 min) song analysed ({len(m['beats'])} beats)")
        # V1 and V2 timelines agree to one sample of the render timebase
        y2, _ = timebase.decode(str(Path(tmp) / f"len_{n0 - 1}.wav"))
        y1, _ = M.decode_mono(str(Path(tmp) / f"len_{n0 - 1}.wav"))
        check(abs(len(y1) - len(y2)) <= 1 and len(y2) == n0 - 1, f"V1 decode_mono {len(y1)} vs V2 decode {len(y2)} samples (render timebase, +-1)")


def part_nan(tmp):
    with section("2) digital silence, DC offset, clipped peaks: no NaN, no RuntimeWarning"):
        y22, tr = base_song(bars=14)
        y = y22.copy()
        y[3 * SR:8 * SR] = 0.0                                    # 5 s of digital silence
        y = y * 3.0                                               # hard clipping on the loud parts
        y = np.clip(y + 0.25, -1.0, 1.0)                          # DC offset + clipped peaks
        y[3 * SR:8 * SR] = 0.0
        p = Path(tmp) / "nasty.wav"
        write_wav22(p, y)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            try:
                m = songmap_v2.build_songmap_v2(str(p))
                err = None
            except Exception as ex:
                m, err = None, f"{type(ex).__name__}: {ex}"
        check(err is None or isinstance(err, str) and "steady beat" in err, f"warnings-as-errors analysis of the nasty track ({err})")
        if m is not None:
            check(not finite_walk(m), f"no NaN / inf in any output field {finite_walk(m)[:3]}")
        # the original bug: running-sum differences over digital silence are slightly negative
        z = np.zeros(SR * 12, np.float32)
        z[SR * 6:] = 0.3 * np.sin(np.arange(SR * 6) * 0.05)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            beats = np.arange(0.0, 11.0, 0.5)
            bars = sections.bar_table(beats, list(range(0, len(beats), 4)), 12.0, z, SR, z, [])
            res = sections.analyse(bars, 2.0)
        vals = [b[k] for b in bars for k in ("loud", "low", "act")]
        check(np.all(np.isfinite(vals)) and np.all(np.isfinite(res["S"])), "bar features and bar scores are finite on digital silence (rms clamped at 0 before the log)")
        nb = [dict(b) for b in bars]
        nb[2]["loud"] = float("nan")
        nb[3]["low"] = float("inf")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            res = sections.analyse(nb, 2.0)
        check(np.all(np.isfinite(res["S"])), "even NaN / inf fed into the section logic cannot reach the change-point detection")


def part_determinism(tmp):
    with section("3) determinism, dedupe, reproducible sampling"):
        y22, tr = base_song(bars=14)
        p = Path(tmp) / "det.wav"
        write_wav22(p, y22)
        runs = []
        for _ in range(3):
            m = songmap_v2.build_songmap_v2(str(p))
            m["v2"].pop("analysis_s", None)
            runs.append(json.dumps(m, sort_keys=True, default=str))
        check(runs[0] == runs[1] == runs[2], "three runs on the same file give identical maps")
        d = Path(tmp) / "pool"
        (d / "a").mkdir(parents=True)
        (d / "b").mkdir()
        for i in range(60):
            f = d / f"song{i:02d} - artist{i}.mp3"
            f.write_bytes(b"x")
            os.utime(f, (1.6e9, 1.6e9))                         # old files: only the seeded random sample orders them
        (d / "a" / "Everytime - LIZOT, Rivendale, Axel Cooper.mp3").write_bytes(b"x")
        (d / "b" / "Everytime - LIZOT, Rivendale, Axel Cooper.mp3").write_bytes(b"xy")
        (d / "b" / "everytime  -  lizot rivendale axel cooper.mp3").write_bytes(b"xyz")
        for f in (d / "a").iterdir():
            os.utime(f, (1.6e9, 1.6e9))
        for f in (d / "b").iterdir():
            os.utime(f, (1.6e9, 1.6e9))
        args = lambda seed: type("A", (), {"target": None, "auto": 10, "songs_dir": str(d), "out": None, "seed": seed, "song": None})()
        notes = []
        pool1, s1 = C.collect_songs(M, args(5), notes)
        pool2, s2 = C.collect_songs(M, args(5), [])
        pool3, s3 = C.collect_songs(M, args(6), [])
        names = lambda P: [Path(e["path"]).name for e in P]
        ev = [e for e in pool1 if "everytime" in e["key"]]
        check(len(ev) == 1 and len(ev[0]["paths"]) == 3, f"duplicates of one title + artist are ONE candidate and keep all paths ({len(ev)} entry, {len(ev[0]['paths']) if ev else 0} paths)")
        check(names(pool1) == names(pool2) and s1 == s2 == 5, "same seed -> the same pool in the same order")
        check(names(pool1) != names(pool3), "another seed -> another random sample")
        check(len(pool1) == C.POOL_CAP, f"pool capped at {C.POOL_CAP} ({len(pool1)})")
        a = type("A", (), {"target": None, "auto": 10, "songs_dir": str(d), "out": None, "seed": 1, "song": ["SONG07", "lizot", "nothing here"]})()
        notes = []
        pool4, _ = C.collect_songs(M, a, notes)
        check(sorted(Path(e["path"]).name for e in pool4)[0].lower().startswith("everytime") and len(pool4) == 2 and any("nothing here" in n for n in notes),
              f"--song picks songs by name fragment ({names(pool4)}) and reports a fragment that matches nothing")


_MEMO = {}


def make_songs(tmp, n=5):
    d = Path(tmp) / "tool_songs"
    d.mkdir(exist_ok=True)
    out = []
    for i in range(n):
        y, tr = T5.synth([("intro", 2), ("verse", 4), ("build", 2), ("drop", 4), ("outro", 2)], bpm=120 + 6 * i, seed=i + 1)
        p = d / f"song{i + 1}.mp3"
        if not p.exists():
            T5.to_mp3(y, p)
        out.append({"path": str(p), "why": "test", "paths": [str(p)], "key": f"song{i + 1}"})
    return out


def memo_analyse():
    real = C.analyse_pair

    def f(M_, path, csv=None):
        if path not in _MEMO:
            _MEMO[path] = real(M_, path, csv)
        v1, v2, y, sr, e = _MEMO[path]
        return v1, v2, y, sr, dict(e)
    return real, f


class Boom(Exception):
    pass


def part_tool(tmp):
    pool = make_songs(tmp, 5)
    real, memo = memo_analyse()
    C.analyse_pair = memo
    try:
        with section("4) matplotlib missing: tool still finishes, clips + report written, install hint printed"):
            out = Path(tmp) / "out_noplt"
            sys.modules["matplotlib"] = None
            sys.modules.pop("matplotlib.pyplot", None)
            lines = []
            try:
                args = type("A", (), {"target": None, "auto": 2, "songs_dir": str(Path(tmp) / "tool_songs"), "out": str(out), "seed": 3, "song": None})()
                st = C.run(M, pool[:2], 2, out, lines.append, [], 3)
                rc = C.main(args, lambda *x: lines.append(" ".join(map(str, x))))
            finally:
                del sys.modules["matplotlib"]
            rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
            check(rc == 0 and sum("PNG maps skipped: run pip install matplotlib to enable them" in l for l in lines) >= 1, "exit code 0 and the hint 'PNG maps skipped: run pip install matplotlib to enable them' is printed")
            check(len(rep["songs"]) == 2 and all((out / f).exists() for s in rep["songs"] for f in s["files"]["firstdrop"]["files"] + s["files"]["suspect"]["files"]) and not list(out.glob("*.png")),
                  "listening clips (2 x 3 per song) and the report exist, no PNGs")
            check(rep["summary"]["png"] is False and "PNG maps skipped" in (out / "report.md").read_text(encoding="utf-8"), "report.md says the PNGs were skipped")
        with section("5) crash isolation: song 3 of 5 raises, the other four are fully written"):
            out = Path(tmp) / "out_crash"
            real_b = songmap_v2.build_songmap_v2
            bad_name = Path(pool[2]["path"]).stem

            def boom(path, *a, **k):
                if Path(path).stem == bad_name:
                    raise ValueError("operands could not be broadcast together with shapes (138481,) (138480,) (138481,)")
                return real_b(path, *a, **k)
            C.analyse_pair = real
            _MEMO.clear()
            songmap_v2.build_songmap_v2 = boom
            try:
                lines = []
                st = C.run(M, pool, 5, out, lines.append, [], 1)
            finally:
                songmap_v2.build_songmap_v2 = real_b
                C.analyse_pair = memo
            rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
            done = sorted(s["song"] for s in rep["songs"])
            check(done == ["song1.mp3", "song2.mp3", "song4.mp3", "song5.mp3"], f"songs 1, 2, 4, 5 written ({done})")
            allf = [f for s in rep["songs"] for k in ("firstdrop", "suspect") for f in s["files"][k]["files"]] + [s["files"][k] for s in rep["songs"] for k in ("full_v1", "full_v2")]
            check(all((out / f).exists() and (out / f).stat().st_size > 1000 for f in allf), f"all {len(allf)} clips / click WAVs of the four songs exist")
            err = rep["errors"]
            md = (out / "report.md").read_text(encoding="utf-8")
            check(len(err) == 1 and err[0]["song"] == "song3.mp3" and "ValueError" in err[0]["error"] and err[0].get("v1") and "song3.mp3" in md and "Songs with problems" in md,
                  f"song 3 is listed with its exception and its V1 result ({err[0]['error'][:60] if err else None})")
            check(rep["summary"]["analysed"] == 4 and rep["summary"]["skipped"] == 1 and rep["summary"]["written"] == 4, f"summary {rep['summary']}")
            verdicts = {r["verdict"] for r in rep["songs"]}
            check(verdicts <= {"V1 better", "V2 better", "tie", "needs listening"}, f"verdict words {verdicts}")
            check(all("median" in r["verdict_why"] and "p95" in r["verdict_why"] and "drops V1" in r["verdict_why"] for r in rep["songs"]), "every verdict carries its numbers (median / p95 offsets, drops)")
        with section("6) incremental output: killed after song 2, songs 1 and 2 are complete"):
            out = Path(tmp) / "out_kill"
            C.analyse_pair = memo

            def kill(i, state):
                if i == 2:
                    raise Boom("killed")
            try:
                C.run(M, pool, 5, out, lambda *x: None, [], 1, after_song=kill)
            except Boom:
                pass
            rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
            md = (out / "report.md").read_text(encoding="utf-8")
            ok = len(rep["songs"]) == 2 and all((out / f).exists() for s in rep["songs"] for f in s["files"]["firstdrop"]["files"] + s["files"]["suspect"]["files"])
            check(ok and "song1.mp3" in md and "song2.mp3" in md, "report.json / report.md and the listening clips of songs 1 and 2 exist after the 'kill'")
        with section("6b) clips are written for tie / needs-listening verdicts too"):
            out = Path(tmp) / "out_all"
            st = C.run(M, pool, 5, out, lambda *x: None, [], 1)
            rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
            check(len(rep["songs"]) == 5 and all(s["files"]["firstdrop"]["files"] for s in rep["songs"]), f"all 5 songs have their clips (verdicts: {sorted({s['verdict'] for s in rep['songs']})})")
    finally:
        C.analyse_pair = real


def part_dispatch(tmp):
    with section("7) dispatcher: the exact ValueError falls back to V1, planning runs"):
        old = M.use_data_dir(Path(tmp) / "ddata")
        try:
            y, tr = T5.synth([("verse", 11)], bpm=128)
            p = Path(tmp) / "disp.mp3"
            T5.to_mp3(y, p)
            msg = "operands could not be broadcast together with shapes (138481,) (138480,) (138481,)"

            def hook():
                raise ValueError(msg)
            M.SONGMAP_V2_HOOK[0] = hook
            lines = []
            M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
            try:
                m = M.get_songmap(str(p), None, "v2")
            finally:
                M.out, M.LOGONLY = T5.REAL_OUT, T5.REAL_LO
                M.SONGMAP_V2_HOOK[0] = None
            check(m["songmap_version"] == "v1-fallback" and lines == [f"songmap v2 fallback: disp.mp3 (ValueError: {msg})"], f"log: {lines[:1]}")
            plan = M.plan_montage(M.load_config(), "valorant", M.fake_events(n=14, seed=3), {"path": str(p), "title": "x", "artist": "a"}, m, 5, "auto", "optimal", [], [])
            check(len(plan["takes"]) >= 2, f"the montage plan runs on the fallback map ({len(plan['takes'])} takes)")
            check(m["beats"] == M.get_songmap(str(p), None, "v1")["beats"], "the fallback map is the V1 map")
        finally:
            M.SONGMAP_V2_HOOK[0] = None
            M.restore_data_dir(old)


V1_FUNCS = ["build_song_map", "fit_grid", "decode_mono", "analyse_song", "analyse_song_v4", "synth_song", "local_onsets", "map_score", "_norm01", "smooth",
            "_beat_this_beats", "song_pool", "ebur128_lufs", "pick_song"]
ALLOWED = {"montage.py", "CHANGELOG.md", "songmap_compare.py", "tests/test_v6951.py"}


def part_v1(tmp):
    with section("8) V1 integrity + allowed files + guards"):
        r = subprocess.run(["git", "show", f"{BASE_REF}:montage.py"], cwd=str(ROOT), capture_output=True)
        if r.returncode:
            check(False, f"base commit {BASE_REF} not available")
            return
        bdir = Path(tmp) / "base"
        bdir.mkdir()
        (bdir / "montage.py").write_bytes(r.stdout)
        os.environ["MONTAGER_DATA"] = str(Path(tmp) / "base_data")
        try:
            spec = importlib.util.spec_from_file_location("montage_base6951", str(bdir / "montage.py"))
            B = importlib.util.module_from_spec(spec)
            sys.modules["montage_base6951"] = B
            spec.loader.exec_module(B)
        finally:
            del os.environ["MONTAGER_DATA"]
        sha = lambda f: hashlib.sha256(inspect.getsource(f).encode()).hexdigest()
        diff = [n for n in V1_FUNCS if sha(getattr(M, n)) != sha(getattr(B, n))]
        check(not diff, f"SHA-256 of the source of {len(V1_FUNCS)} V1 functions equals the base commit's {diff}")
        t = Path(tmp) / "v1.mp3"
        y, _ = T5.synth([("intro", 4), ("verse", 8), ("drop", 6)], bpm=128)
        T5.to_mp3(y, t)
        check(json.dumps(M.build_song_map(str(t)), sort_keys=True) == json.dumps(B.build_song_map(str(t)), sort_keys=True), "V1 output on a generated song is identical to the base commit")
        files = set(subprocess.run(["git", "diff", "--name-only", BASE_REF], cwd=str(ROOT), capture_output=True, text=True).stdout.split())
        files |= set(subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=str(ROOT), capture_output=True, text=True).stdout.split())
        extra = {f for f in files if f not in ALLOWED and not f.startswith("songmap_v2/") and not f.startswith("__pycache__") and "__pycache__" not in f}
        check(not extra, f"git: only allowed files differ from the base ({sorted(files)}) unexpected {sorted(extra)}")
        d = subprocess.run(["git", "diff", "-U0", BASE_REF, "--", "montage.py"], cwd=str(ROOT), capture_output=True, text=True).stdout
        removed = [l[1:] for l in d.splitlines() if l.startswith("-") and not l.startswith("---")]
        ok = re.compile(r"APP_VERSION = |except Exception as ex:|songmap v2 fallback|songmap_fallback_reason|raise RuntimeError\(|def get_songmap|^\s*$")
        odd = [l for l in removed if not ok.search(l)]
        check(not odd, f"montage.py: only the dispatcher fallback / version lines were changed ({len(removed)} removed lines) {odd[:3]}")
        import test_v693 as T
        view = lambda mod, e, g: json.dumps(mod.analyse_entry(e, {}, g), sort_keys=True, default=str)
        for game in ("valorant", "cs2"):
            ents = T.gen_entries(100, game)
            nd = sum(view(M, e, game) != view(B, e, game) for e in ents)
            kn = sum(len(M.analyse_entry(e, {}, game)["kills"]) for e in ents)
            check(nd == 0 and kn > 20, f"{game}: kills, timestamps, deaths, revives of 100 generated clips identical to the base ({nd} differences, {kn} kills)")


def main():
    real_before = T5.snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t6951_"))
    old = M.use_data_dir(tmp / "data")
    try:
        part_lengths(tmp)
        part_nan(tmp)
        part_determinism(tmp)
        part_tool(tmp)
        part_dispatch(tmp)
        part_v1(tmp)
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
