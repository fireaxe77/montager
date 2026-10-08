"""V7: SONGMAP V2 improvement test. Genre suite with known truth, V1 byte-for-byte unchanged (generated AND real songs), V2 deterministic / V1-shaped /
valid, per-song gate and fallbacks, V2 cannot touch takes / kills / ledger, git diff limited to the allowed paths, Valorant / CS2 guards, and the
plan-level check on the real clips. Needs the Windows PC with the real songs (E:\\CLAUDECODE\\Songs) and clips (E:\\Movies).
   python tests\\test_v7.py          (from the repo root or from tests/)
Ends with ALL OK only if every check ran and passed."""
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
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
warnings.filterwarnings("ignore")
import numpy as np                                                                            # noqa: E402
import montage as M                                                                           # noqa: E402
import songmap_v2                                                                             # noqa: E402
from songmap_v2 import synth, planbench as PB, bench, build as B2                             # noqa: E402
import test_v693 as T                                                                         # noqa: E402
from test_v6952 import V1_FUNCS                                                               # noqa: E402

T_ALL = time.time()
FAILS, SECTIONS = [], []
BASE_REF = os.environ.get("V7_BASE", "d37059c")            # main when v7-songmapv2 was branched (V6.9.11 merge)
SONGS = Path(M.load_config().get("mp3_dir") or "E:/CLAUDECODE/Songs")
REAL_FRAGS = ["Silicon XX", "ALWAYS BEEN MINE", "(nendest)", "A Bar Song", "too much (hardtekk)"]
ALLOWED = ("songmap_v2/", "songmap_compare.py", "tests/test_v7.py", "docs/", "CHANGELOG.md")


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


def real_songs():
    out = []
    files = sorted(SONGS.glob("*.mp3"))
    for frag in REAL_FRAGS:
        f = next((p for p in files if frag.lower() in p.name.lower()), None)
        check(f is not None, f"real song present: {frag}")
        if f is not None:
            out.append(str(f).replace("\\", "/"))
    return out


def csv_of(path):
    pool = {str(s["path"]).replace("\\", "/"): s for s in M.song_pool(M.load_config(), cached_only=True)[0]}
    return (pool.get(path) or {}).get("csv_bpm")


VOLATILE = ("logs", "cs2_rows_v1", "kills_v5", "audio_cache.json", "clips_cache3.json", "kills_cache3.json", "theme_cache")      # caches the running Montager app itself refreshes


def snapshot(d):
    """sha1 of every file of montage_data EXCEPT the log and the scan caches a running Montager app rewrites on its own; config, used flags / titles /
    songs, song caches, detection regions and overrides are all covered."""
    out = {}
    for p in sorted(Path(d).rglob("*")):
        if p.is_file() and p.relative_to(d).parts[0] not in VOLATILE and p.name not in VOLATILE:
            out[str(p.relative_to(d))] = (p.stat().st_size, hashlib.sha1(p.read_bytes()).hexdigest())
    return out


def kind(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "num"
    return type(v).__name__


def stable(m):
    """The map without the wall-clock field."""
    m = json.loads(json.dumps(m, default=float))
    if isinstance(m.get("v2"), dict):
        m["v2"].pop("analysis_s", None)
    return json.dumps(m, sort_keys=True)


def part_genre(tmp):
    maps = {}
    with section("1) genre suite (generated, known truth): grid error, tempo, downbeats, NaN, ambient"):
        for name in synth.SUITE:
            p, tr = synth.make_song_file(name, tmp)
            if name == "ambient":
                try:
                    m = songmap_v2.build_songmap_v2(p, None)
                    check(m["v2"]["grid_confidence"] < 0.3, f"ambient: low confidence ({m['v2']['grid_confidence']}), never a fake grid")
                except RuntimeError as ex:
                    check("no steady beat" in str(ex), f"ambient (no percussion): V2 refuses to invent a grid ({ex}) -> the dispatcher uses V1")
                continue
            m = songmap_v2.build_songmap_v2(p, None)
            maps[name] = (m, p, tr)
            r = synth.eval_synth(m, tr)
            med_t, p95_t = synth.targets(name)
            check(not r["nan"], f"{name}: no NaN")
            check(r["median_ms"] < med_t and r["p95_ms"] < p95_t, f"{name}: grid error median {r['median_ms']} ms (< {med_t}), p95 {r['p95_ms']} ms (< {p95_t})")
            check(r["tempo_ok"] and 60 <= m["bpm"] <= 200, f"{name}: tempo {r['bpm']} vs truth {tr['bpm']} (within 1 % or the 0.5x / 2x octave, 60-200 only)")
            check(r["down_ok_frac"] >= 0.85, f"{name}: downbeat phase correct on {r['down_ok_frac']:.0%} of the bars (confidence {m['v2']['downbeat_confidence']})")
            seg = m["v2"]["segments"]
            check(all(60 <= s["bpm"] <= 200 for s in seg), f"{name}: every tempo segment inside 60-200 BPM ({[s['bpm'] for s in seg]})")
    return maps


def part_validity(tmp, maps, real):
    with section("2) V2 output: V1 shape, valid timestamps, no NaN, deterministic (3 runs)"):
        items = [(n, m, p) for n, (m, p, _) in maps.items()]
        for rp in real:
            items.append((Path(rp).stem, songmap_v2.build_songmap_v2(rp, csv_of(rp)), rp))
        bad_shape, bad_time, bad_nan = [], [], []
        for name, m2, p in items:
            m1 = M.build_song_map(p, None)
            if not (set(m1) <= set(m2) and all(kind(m1[k]) == kind(m2[k]) for k in m1 if m1[k] is not None and m2.get(k) is not None)):
                bad_shape.append(name)
            dur = float(m2["dur"])
            ts = list(m2["beats"]) + list(m2["onsets"]) + [d["t"] for d in m2["drops"]] + [s["start_t"] for s in m2["sections"]] + [s["end_t"] for s in m2["sections"]] + [a[0] for a in m2["accents"]]
            if any((t < -0.03 or t > dur + 0.05) for t in ts) or any(b2 <= b1 for b1, b2 in zip(m2["beats"], m2["beats"][1:])):
                bad_time.append(name)
            if not B2_finite(m2):
                bad_nan.append(name)
        check(not bad_shape, f"V2 map has every V1 key with the V1 value type ({len(items)} songs; bad: {bad_shape})")
        check(not bad_time, f"no negative / beyond-duration timestamps, beats strictly increasing ({len(items)} songs; bad: {bad_time})")
        check(not bad_nan, f"no NaN / inf anywhere in the maps ({len(items)} songs; bad: {bad_nan})")
        for p in [maps["dnb174"][1], real[0]]:
            runs = [stable(songmap_v2.build_songmap_v2(p, csv_of(p) if p in real else None)) for _ in range(3)]
            check(runs[0] == runs[1] == runs[2], f"deterministic: 3 runs identical ({Path(p).name})")


def B2_finite(o):
    if isinstance(o, dict):
        return all(B2_finite(v) for v in o.values())
    if isinstance(o, (list, tuple)):
        return all(B2_finite(v) for v in o)
    if isinstance(o, (float, np.floating)):
        return bool(np.isfinite(o))
    return True


def load_base(tmp):
    return T.load_baseline(tmp, BASE_REF)


def part_v1(tmp, Bm, real, maps):
    with section("3) V1 byte-for-byte unchanged: function SHA-256 + V1 output on generated AND real songs"):
        sha = lambda f: hashlib.sha256(inspect.getsource(f).encode()).hexdigest()
        diff = [n for n in V1_FUNCS if sha(getattr(M, n)) != sha(getattr(Bm, n))]
        check(not diff, f"SHA-256 of the source of {len(V1_FUNCS)} V1 functions equals main's ({BASE_REF}) {diff}")
        gen_paths = [maps[n][1] for n in ("house128", "hiphop87", "mp3delay")]
        same = []
        for p in gen_paths + real:
            a = json.dumps(M.build_song_map(p, csv_of(p) if p in real else None), sort_keys=True, default=float)
            b = json.dumps(Bm.build_song_map(p, csv_of(p) if p in real else None), sort_keys=True, default=float)
            same.append(a == b)
            check(a == b, f"V1 output identical to main: {Path(p).name}")
        check(all(same), f"V1 output identical on all {len(same)} songs ({len(gen_paths)} generated + {len(real)} real)")


def part_gate(tmp, maps):
    with section("4) per-song gate and fallbacks"):
        d = Path(tmp) / "gatedata"
        old = M.use_data_dir(d)
        lines = []
        keep = (M.out, M.LOGONLY)
        M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
        try:
            # a locked song whose CSV tempo is wrong (V1 trusts the CSV): V2 wins
            p = maps["house128"][1]
            m = M.get_songmap(p, 100.0, "v2auto")
            au = [l for l in lines if l.startswith("songmap auto: house128")]
            check(m.get("songmap_version") == "v2" and au and "-> V2 (conf" in au[-1], f"locked song with a wrong CSV tempo -> V2: {au[-1:] }")
            # an ambient / no-percussion song: V2 has no grid -> V1
            lines.clear()
            amb, _ = synth.make_song_file("ambient", tmp)
            m = M.get_songmap(amb, None, "v2auto")
            check(str(m.get("songmap_version", "")).startswith("v1") and any("songmap v2 fallback" in l or "-> V1" in l for l in lines), f"ambient song -> V1 map ({m.get('songmap_version')}): {lines[-1:]}")
            # injected V2 exception
            lines.clear()
            orig = songmap_v2.build_songmap_v2
            songmap_v2.build_songmap_v2 = lambda *a, **k: (_ for _ in ()).throw(ValueError("boom"))
            try:
                m = M.get_songmap(maps["hiphop87"][1], None, "v2auto")
            finally:
                songmap_v2.build_songmap_v2 = orig
            check(m.get("songmap_version") == "v1-fallback" and any("songmap v2 fallback" in l and "boom" in l for l in lines) and len(m["beats"]) > 10, f"injected exception -> V1 + log: {lines[-1:]}")
            # analysis-time cap
            lines.clear()
            cap = songmap_v2.ANALYSIS_CAP_S
            songmap_v2.ANALYSIS_CAP_S = 0.001
            try:
                m = M.get_songmap(maps["dnb174"][1], None, "v2auto")
            finally:
                songmap_v2.ANALYSIS_CAP_S = cap
            check(m.get("songmap_version") == "v1-fallback" and any("songmap v2 fallback" in l for l in lines) and len(m["beats"]) > 10, f"analysis-time cap -> V1 + log: {lines[-1:]}")
            # a noisy song never gets V2
            lines.clear()
            rng = np.random.default_rng(3)
            y = (rng.standard_normal(22050 * 40) * 0.2).astype(np.float32)
            nz = Path(tmp) / "noise.wav"
            synth.write_wav(nz, y)
            m = M.get_songmap(str(nz), None, "v2auto")
            check(str(m.get("songmap_version", "")).startswith("v1"), f"white noise -> V1 map ({m.get('songmap_version')})")
        finally:
            M.out, M.LOGONLY = keep
            M.restore_data_dir(old)


def part_plan(tmp, Bm, real):
    with section("5) V2 cannot modify takes / kills / selection / ledger; the 7 real Valorant clips: 4 takes, 11 placed, 3 merged, 0 lost"):
        song = real[0]
        pool_path = next(s["path"] for s in M.song_pool(M.load_config(), cached_only=True)[0] if str(s["path"]).replace("\\", "/") == song)
        res = {}
        with PB.data_copy(M):
            sets = PB.take_sets(M)
            game, paths = sets["val7"]
            for mode in ("v1", "v2auto", "v2"):
                plan, lines = PB.run_plan(M, game, paths, pool_path, mode)
                led = next((l for l in lines if l.startswith("kill ledger:")), "")
                res[mode] = (plan, led)
            for mode, (plan, led) in res.items():
                check(len(plan["takes"]) == 4 and "11 placed" in led and "3 merged" in led and "0 lost" in led and "utility override" not in led,
                      f"{mode}: 4 takes; ledger '{led[:110]}'")
            srcs = {m_: sorted((t["path"], tuple(round(k, 3) for k in t["kills"]), tuple(t["victims"])) for t in res[m_][0]["takes"]) for m_ in res}
            check(srcs["v1"] == srcs["v2auto"] == srcs["v2"], "the same clips, kill times and victims in the takes whatever the song map")
            check(res["v1"][1] == res["v2auto"][1] == res["v2"][1], "kill ledger identical for V1 / V2-auto / V2")
            check(len({json.dumps({k: v for k, v in res[m_][0].items() if k in ("game", "seed", "placement")}, sort_keys=True) for m_ in res}) == 1, "game / seed / placement version identical")
            kinds = {m_: sum(int(t["n"]) for t in res[m_][0]["takes"]) for m_ in res}
            check(len(set(kinds.values())) == 1, f"events placed identical: {kinds}")


def part_guards(tmp, Bm):
    with section("6) Valorant / CS2 guards: 50 generated clips each, V1 selected: events, plans and selection identical to main"):
        view = lambda mod, e, g: json.dumps(mod.analyse_entry(e, {}, g), sort_keys=True, default=str)
        for game in ("valorant", "cs2"):
            ents = T.gen_entries(50, game)
            nd = sum(view(M, e, game) != view(Bm, e, game) for e in ents)
            kn = sum(len(M.analyse_entry(e, {}, game)["kills"]) for e in ents)
            check(nd == 0 and kn > 10, f"{game}: kills / timestamps / deaths / revives of 50 generated clips identical to main ({nd} differences, {kn} kills)")
        # plans: the same pinned real clips with Songmap V1 selected -> the plan of this branch equals main's plan
        with PB.data_copy(M) as dst:
            sets = PB.take_sets(M)
            game, paths = sets["val7"]
            song = real_songs_cached()
            plan_a, la = PB.run_plan(M, game, paths, song, "v1")
            Mb = Bm
            keep = (Mb.out, Mb.LOGONLY)
            Mb.out = Mb.LOGONLY = lambda *x: None
            old = Mb.use_data_dir(dst)
            ksv = Mb.songmap_version
            Mb.songmap_version = lambda cfg=None: "v1"
            try:
                plan_b, _ = Mb.make_plan(Mb.load_config(), game, [str(p) for p in paths], song_path=song, seed=1)
            finally:
                Mb.songmap_version = ksv
                Mb.restore_data_dir(old)
                Mb.out, Mb.LOGONLY = keep
            strip = lambda pl: json.dumps({k: v for k, v in pl.items() if k not in ("notes",)}, sort_keys=True, default=str)
            if strip(plan_a) != strip(plan_b):
                print("   differing plan keys:", [k for k in plan_a if json.dumps(plan_a[k], sort_keys=True, default=str) != json.dumps(plan_b.get(k), sort_keys=True, default=str)])
            check(strip(plan_a) == strip(plan_b), "7 real Valorant clips, Songmap V1: the plan of this branch equals main's plan (takes, kills, song, params)")


def real_songs_cached():
    p = next(s["path"] for s in M.song_pool(M.load_config(), cached_only=True)[0] if "Silicon XX" in str(s["path"]))
    return p


def part_diff():
    with section("7) git diff limited to the allowed paths"):
        r = subprocess.run(["git", "diff", "--name-only", BASE_REF], cwd=str(ROOT), capture_output=True, text=True)
        u = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=str(ROOT), capture_output=True, text=True)
        files = [f for f in (r.stdout.split() + u.stdout.split()) if f and not f.startswith(("good.mp4", "montage_data_backup"))]
        bad = [f for f in files if not f.startswith(ALLOWED)]
        stat = subprocess.run(["git", "diff", "--stat", BASE_REF], cwd=str(ROOT), capture_output=True, text=True).stdout.strip().splitlines()
        print("   " + (stat[-1] if stat else "(no tracked changes)"))
        check(not bad, f"changed / new files all inside {ALLOWED} (outside: {bad})")
        check("montage.py" not in files and "tests/test_v7.py" in files + ["tests/test_v7.py"], "montage.py untouched")


def main():
    real_data = ROOT / "montage_data"
    before = snapshot(real_data)
    tmp = Path(tempfile.mkdtemp(prefix="t7_"))
    with PB.data_copy(M):                                   # EVERYTHING below runs on a copy of montage_data (song pool, caches, scans included)
        real = real_songs()
        old = M.use_data_dir(tmp / "data")
        try:
            maps = part_genre(tmp)
            part_validity(tmp, maps, real)
            Bm = load_base(tmp)
            check(Bm is not None, f"base module loaded from {BASE_REF}")
            part_v1(tmp, Bm, real, maps)
            part_gate(tmp, maps)
        finally:
            M.restore_data_dir(old)
        part_plan(tmp, Bm, real)
        part_guards(tmp, Bm)
        part_diff()
    with section("real montage_data"):
        after = snapshot(real_data)
        check(after == before, f"real montage_data byte-identical after the tests ({len(before)} files)")
    total = time.time() - T_ALL
    print("section times: " + ", ".join(f"{t.split(')')[0]} {s:.0f}s" for t, s in SECTIONS))
    print(f"total test time {total:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
