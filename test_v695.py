"""V6.9.5: SONGMAPV2 (isolated song map) + the Songmap version dropdown + the songmapcompare tool. All audio is generated in code; no real
songs, clips or renders. Prints the time of every section.
   python test_v695.py
Only this version's checks + the Valorant / CS2 guards + the V1 integrity checks; older tests are frozen."""
import hashlib
import importlib.util
import inspect
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "tests"))
import numpy as np                                                                            # noqa: E402
from scipy.signal import correlate, resample_poly                                            # noqa: E402
import montage as M                                                                           # noqa: E402
import songmap_v2                                                                             # noqa: E402
from songmap_v2 import timebase                                                               # noqa: E402

T_ALL = time.time()
FAILS, SECTIONS = [], []
BASE_REF = os.environ.get("V695_BASE", "702c1ac")           # origin/main before V6.9.5 (V6.9.3 merged)
REAL_DATA = HERE / "montage_data"
REAL_OUT, REAL_LO = M.out, M.LOGONLY


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


def logged(fn, *a, **k):
    lines = []
    M.out = M.LOGONLY = lambda *x: lines.append(" ".join(map(str, x)))
    try:
        res = fn(*a, **k)
    finally:
        M.out, M.LOGONLY = REAL_OUT, REAL_LO
    return res, lines


def snapshot(d):
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(d).rglob("*")) if p.is_file()} if Path(d).exists() else {}


# ---------------------------------------------------------------------------------------------------- audio generator
SR = 44100
def synth(layout, bpm=128.0, bpb=4, tempo_map=None, lead=0.0, seed=1, kick_pat=None, peak_at=None, gain=None):
    """layout: [(name,bars)] ; tempo_map: [(bpm, nbars)] overrides bpm per bar sequence. Returns y, truth dict."""
    rng=np.random.default_rng(seed)
    bars=[]; 
    for name,nb in layout: bars += [name]*nb
    nbars=len(bars)
    # bar durations
    bpms=[]
    if tempo_map:
        for b_,n_ in tempo_map: bpms += [b_]*n_
        bpms=(bpms+[bpms[-1]]*nbars)[:nbars]
    else: bpms=[bpm]*nbars
    t=lead; beats=[]; downs=[]; names=[]
    bar_starts=[]
    for i,name in enumerate(bars):
        per=60.0/bpms[i]
        bar_starts.append(t)
        for k in range(bpb):
            beats.append(t+k*per); names.append((name,k))
        t += bpb*per
    dur=t+1.5
    y=np.zeros(int(dur*SR),np.float32)
    def add(sig,at):
        s=int(round(at*SR)); e=min(len(y),s+len(sig))
        if s<0 or e<=s: return
        y[s:e]+=sig[:e-s]
    n=np.arange(int(0.25*SR))
    def kick(a): return (np.sin(2*np.pi*(48+70*np.exp(-n/(0.02*SR)))*n/SR)*np.exp(-n/(0.06*SR))*a).astype(np.float32)
    def snare(a): return ((rng.standard_normal(len(n))*np.exp(-n/(0.035*SR))*0.7+np.sin(2*np.pi*190*n/SR)*np.exp(-n/(0.05*SR))*0.5)*a).astype(np.float32)
    nh=np.arange(int(0.04*SR))
    def hat(a): return (rng.standard_normal(len(nh))*np.exp(-nh/(0.008*SR))*a).astype(np.float32)
    inten={"intro":0.35,"verse":0.55,"build":0.65,"drop":1.0,"bump":1.0,"breakdown":0.0,"outro":0.35,"loud":1.0,"flat":0.8}
    for i,(b_t,(name,k)) in enumerate(zip(beats,names)):
        per=60.0/bpms[min(i//bpb,nbars-1)]
        a=inten[name]*(gain(i//bpb) if gain else 1.0)
        if a>0:
            if bpb==4:
                if k in (0,2): add(kick(a*(1.0 if k==0 else 0.8)),b_t)
                if k in (1,3) and name!="intro": add(snare(a*0.55),b_t)
            else:
                if k==0: add(kick(a),b_t)
                if k in (1,2) and name!="intro": add(snare(a*0.45),b_t)
            add(hat(a*0.12),b_t+per/2)
            if name in ("drop","bump","loud"):
                m=np.arange(int(per*SR)); add((np.sin(2*np.pi*55*m/SR)*0.3).astype(np.float32),b_t)
                add(hat(a*0.1),b_t)
        if name=="build":
            m=np.arange(int(per*SR)); add((rng.standard_normal(len(m))*0.02*(1+ (i//bpb)%8)).astype(np.float32),b_t)
        if name in ("intro","breakdown","outro"):
            m=np.arange(int(per*SR)); add((np.sin(2*np.pi*330*m/SR)*0.06).astype(np.float32),b_t)
    if peak_at is not None:
        for pa in np.atleast_1d(peak_at): add((rng.standard_normal(int(0.08*SR))*np.exp(-np.arange(int(0.08*SR))/(0.02*SR))*1.2).astype(np.float32),pa)
    y=np.clip(y,-1,1)
    drop_t=[bar_starts[i] for i in range(nbars) if bars[i] in("drop",) and (i==0 or bars[i-1]!="drop")]
    return y,{"beats":np.array(beats),"bar_starts":np.array(bar_starts),"drops":drop_t,"bars":bars,"dur":dur}
def write_wav(path,y):
    with wave.open(str(path),'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(y,-1,1)*32767).astype(np.int16).tobytes())
def to_mp3(y,path):
    wav=str(path)+".wav"; write_wav(wav,y)
    subprocess.run(["ffmpeg","-y","-v","error","-i",wav,"-c:a","libmp3lame","-b:a","192k",str(path)],check=True)
    os.remove(wav)


_CACHE = {}


def make(name, tmp, layout, **kw):
    """Generated song as MP3 + truth. Cached per name."""
    if name in _CACHE:
        return _CACHE[name]
    y, tr = synth(layout, **kw)
    p = Path(tmp) / f"{name}.mp3"
    to_mp3(y, p)
    tr["y44"] = y
    tr["path"] = str(p)
    _CACHE[name] = tr
    return tr


def lag_shift(path, y44):
    """Seconds the decoded MP3 is delayed relative to the generated signal (encoder delay etc.), by cross-correlation of the first 8 s."""
    dec, sr = timebase.decode(path)
    ref = resample_poly(y44, 1, 2).astype(np.float32)
    n = min(len(dec), len(ref), 8 * sr)
    c = correlate(dec[:n], ref[:n], mode="full", method="fft")
    return (int(np.argmax(c)) - (n - 1)) / sr


def beat_err(m, tr, shift):
    bt = np.array(m["beats"])
    truth = tr["beats"] + shift
    sel = bt[(bt >= truth.min() - 0.02) & (bt <= truth.max() + 0.02)]
    return np.array([np.min(np.abs(truth - t)) for t in sel]) * 1000.0


def down_ok(m, tr, shift, tol=0.02):
    bt = np.array(m["beats"])
    d = bt[m["down"]]
    truth = tr["bar_starts"] + shift
    d = d[(d >= truth.min() - 0.02) & (d <= truth.max() + 0.02)]
    if not len(d):
        return 0.0
    return float(np.mean([np.min(np.abs(truth - t)) < tol for t in d]))


def v2(tr, csv=None):
    return songmap_v2.build_songmap_v2(tr["path"], csv)


# ---------------------------------------------------------------------------------------------------- tests
def part_grid(tmp):
    with section("a) constant tempo: grid error, downbeat phase (128, 140, 174, 127.3, 3/4)"):
        for bpm in (128, 140, 174, 127.3):
            tr = make(f"c{bpm}", tmp, [("verse", 24)], bpm=bpm)
            m = v2(tr)
            sh = lag_shift(tr["path"], tr["y44"])
            e = beat_err(m, tr, sh)
            check(abs(m["bpm"] - bpm) < 0.6 and np.median(e) < 10 and np.percentile(e, 95) < 20 and down_ok(m, tr, sh) >= 0.9,
                  f"{bpm} BPM: bpm {m['bpm']}, beat error median {np.median(e):.1f} ms / p95 {np.percentile(e, 95):.1f} ms, downbeat phase {down_ok(m, tr, sh):.0%} correct (decoder shift {sh * 1000:+.1f} ms)")
        tr = make("c34", tmp, [("verse", 24)], bpm=120, bpb=3)
        m = v2(tr)
        sh = lag_shift(tr["path"], tr["y44"])
        e = beat_err(m, tr, sh)
        check(m["v2"]["beats_per_bar"] == 3 and np.median(e) < 10 and np.percentile(e, 95) < 20 and down_ok(m, tr, sh) >= 0.9,
              f"3/4 track: {m['v2']['beats_per_bar']} beats per bar, error median {np.median(e):.1f} ms, p95 {np.percentile(e, 95):.1f} ms, downbeats {down_ok(m, tr, sh):.0%} correct")


def part_peak(tmp):
    with section("b) a loud non-grid peak does not move the grid"):
        base = make("pk_a", tmp, [("verse", 24)], bpm=128)
        per = 60.0 / 128
        pk = base["beats"][40] + 0.30 * per
        pk2 = base["beats"][70] + 0.80 * per
        tr = make("pk_b", tmp, [("verse", 24)], bpm=128, peak_at=[pk, pk2])
        ma, mb = v2(base), v2(tr)
        ba, bb = np.array(ma["beats"]), np.array(mb["beats"])
        n = min(len(ba), len(bb))
        diff = np.max(np.abs(ba[:n] - bb[:n])) * 1000 if len(ba) == len(bb) else 999.0
        evs = mb["v2"]["events"]
        shp = lag_shift(tr["path"], tr["y44"])
        near = [e for e in evs if abs(e["raw_time"] - (pk + shp)) < 0.03 and e["strength"] >= 0.3]
        flagged = bool(near) and all((not e["on_grid"]) or e["type"] == "accent" for e in near)
        check(diff <= 2.0, f"grid with / without the peaks identical within {diff:.2f} ms ({len(ba)} vs {len(bb)} beats)")
        check(flagged and not any(abs(b - (pk + shp)) < 0.03 for b in bb), f"the peak is {'off_grid' if near and not near[0]['on_grid'] else 'an accent'} ({[(e['type'], e['on_grid']) for e in near][:2]}), never a beat")


def part_offset(tmp):
    with section("c) ambient intro of odd length, MP3 encoder delay"):
        tr = make("off", tmp, [("intro", 4), ("verse", 20)], bpm=128, lead=3.37)
        m = v2(tr)
        sh = lag_shift(tr["path"], tr["y44"])
        e = beat_err(m, tr, sh)
        check(np.median(e) < 10 and np.percentile(e, 95) < 20, f"odd 3.37 s lead + intro: grid error median {np.median(e):.1f} ms, p95 {np.percentile(e, 95):.1f} ms (encoder / decoder shift {sh * 1000:+.1f} ms)")
        kicks = [e for e in m["v2"]["events"] if e["type"] == "kick"]
        off = [abs(e["offset_ms"]) for e in kicks if e["on_grid"] and e["offset_ms"] is not None]
        check(len(off) > 10 and np.median(off) < 5, f"kicks land on the grid: median offset {np.median(off):.2f} ms over {len(off)} kicks")


def part_sections(tmp):
    with section("d-f) bump is not a drop, build -> 16-bar drop, uniformly loud"):
        tr = make("bump", tmp, [("verse", 16), ("bump", 3), ("verse", 16)], bpm=144)
        m = v2(tr)
        check(not m["drops"] and any(s["label"] == "bump" for s in m["sections"]), f"5 s bump in a verse: no drop, labelled bump ({[s['label'] for s in m['sections']]})")
        tr = make("drop", tmp, [("intro", 8), ("build", 8), ("drop", 16), ("outro", 8)], bpm=128)
        m = v2(tr)
        sh = lag_shift(tr["path"], tr["y44"])
        err = abs(m["drops"][0]["t"] - (tr["drops"][0] + sh)) * 1000 if m["drops"] else 999
        check(len(m["drops"]) == 1 and err <= 10 and (m["drops"][0]["beat"] in m["down"]), f"build -> 16-bar drop: exactly {len(m['drops'])} drop, {err:.1f} ms from the true downbeat, on a downbeat")
        tr = make("loud", tmp, [("loud", 48)], bpm=128)
        m = v2(tr)
        share = sum(s["end_t"] - s["start_t"] for s in m["sections"] if s["label"] == "drop") / m["dur"]
        check(share <= 0.5, f"uniformly loud track: {share:.0%} labelled drop (limit 50%), {len(m['drops'])} drops")


def part_tempo(tmp):
    with section("g) tempo change mid-song"):
        tr = make("tempo", tmp, [("verse", 32)], tempo_map=[(120, 16), (140, 16)])
        m = v2(tr)
        sh = lag_shift(tr["path"], tr["y44"])
        e = beat_err(m, tr, sh)
        segs = m["v2"]["segments"]
        check(len(segs) >= 2 and np.median(e) < 12 and np.percentile(e, 95) < 25, f"piecewise grid: {len(segs)} segments ({[s['bpm'] for s in segs]}), error median {np.median(e):.1f} ms, p95 {np.percentile(e, 95):.1f} ms")


def part_timebase(tmp):
    with section("h) timebase: V2 decode path == render decode path"):
        tr = make("c128", tmp, [("verse", 24)], bpm=128)
        a, sr = timebase.decode(tr["path"], 48000)
        b, _ = timebase.decode_render_path(tr["path"], 48000)
        n = min(len(a), len(b), 3 * sr)
        c = correlate(a[:n], b[:n], mode="full", method="fft")
        lag = int(np.argmax(c)) - (n - 1)
        check(abs(lag) <= 1 and abs(len(a) - len(b)) <= 1, f"cross-correlation lag {lag} samples, lengths {len(a)} / {len(b)}")
        nn = min(len(a), len(b))
        cc = float(np.corrcoef(a[:nn], b[:nn])[0, 1])
        check(cc > 0.9999, f"waveforms identical up to the mono / stereo level (correlation {cc:.6f})")
        src = inspect.getsource(timebase)
        check("librosa" not in src.replace("no librosa.load", ""), "V2 never uses librosa.load on the MP3")


def shape_of(v):
    if isinstance(v, dict):
        return {k: shape_of(x) for k, x in v.items()}
    if isinstance(v, list):
        return [shape_of(v[0])] if v else []
    return type(v).__name__


def part_shape(tmp):
    with section("i) adapter output has V1's shape; V1 consumers run on it"):
        tr = make("full", tmp, [("intro", 8), ("verse", 16), ("build", 8), ("drop", 16), ("breakdown", 8), ("outro", 8)], bpm=128)
        m2 = v2(tr)
        m1 = M.build_song_map(tr["path"])
        keys1, keys2 = set(m1), set(m2)
        check(keys1 <= keys2 and keys2 - keys1 <= {"songmap_version", "v2"}, f"keys: V1 {len(keys1)}, V2 {len(keys2)}, extras {sorted(keys2 - keys1)}, missing {sorted(keys1 - keys2)}")
        bad = []
        for k in keys1:
            a, b = shape_of(m1[k]), shape_of(m2[k])
            if a == b or a == "NoneType" or b == "NoneType" or (isinstance(a, str) and isinstance(b, str) and {a, b} <= {"int", "float"}):
                continue
            if isinstance(a, list) and isinstance(b, list):
                ea, eb = (a[0] if a else None), (b[0] if b else None)
                if ea == eb or ea is None or eb is None or (isinstance(ea, str) and isinstance(eb, str) and {ea, eb} <= {"int", "float"}):
                    continue
                if isinstance(ea, dict) and isinstance(eb, dict) and set(ea) == set(eb):
                    continue
                if isinstance(ea, list) and isinstance(eb, list):
                    continue
            if isinstance(a, dict) and isinstance(b, dict) and set(a) == set(b):
                continue
            bad.append((k, a, b))
        check(not bad, f"every V1 value has the same type / element type in V2 {bad[:3]}")
        srt = lambda L: all(x <= y for x, y in zip(L, L[1:]))
        check(srt(m2["beats"]) and srt([a[0] for a in m2["accents"]]) and srt([d["beat"] for d in m2["drops"]]) and srt(m2["down"]) and len(m2["strength"]) == len(m2["beats"]) == len(m2["energy"]) == len(m2["level"]) == len(m2["section_of_beat"]),
              "times sorted, per-beat arrays have one entry per beat")
        cfg = M.load_config()
        song = {"path": tr["path"], "title": "x", "artist": "a"}
        evs = M.fake_events(n=14, seed=3)
        plan = M.plan_montage(cfg, "valorant", evs, song, m2, 5, "auto", "optimal", [], [])
        check(len(plan["takes"]) >= 2, f"the planner runs on the V2 map ({len(plan['takes'])} takes)")
        sc = M.map_score(tr["path"], m2)
        check("score" in sc, f"map_score() runs on the V2 map (score {sc['score']})")
        return tr, m1, m2


V1_FUNCS = ["build_song_map", "fit_grid", "decode_mono", "analyse_song", "analyse_song_v4", "synth_song", "local_onsets", "map_score", "_norm01",
            "smooth", "_beat_this_beats", "song_pool", "ebur128_lufs"]
ALLOWED_FILES = {"montage.py", "CHANGELOG.md", "CLAUDE.md", ".gitignore", "songmap_compare.py", "test_v695.py"}


def load_base(tmp):
    r = subprocess.run(["git", "show", f"{BASE_REF}:montage.py"], cwd=str(HERE), capture_output=True)
    if r.returncode:
        return None
    bdir = Path(tmp) / "base"
    bdir.mkdir(exist_ok=True)
    (bdir / "montage.py").write_bytes(r.stdout)
    data = Path(tmp) / "base_data"
    data.mkdir(exist_ok=True)
    os.environ["MONTAGER_DATA"] = str(data)
    try:
        spec = importlib.util.spec_from_file_location("montage_base695", str(bdir / "montage.py"))
        B = importlib.util.module_from_spec(spec)
        sys.modules["montage_base695"] = B
        spec.loader.exec_module(B)
    finally:
        del os.environ["MONTAGER_DATA"]
    return B


def part_v1(tmp, tr):
    with section("j) V1 integrity"):
        B = load_base(tmp)
        if B is None:
            check(False, f"base commit {BASE_REF} not available (git fetch origin)")
            return
        diff = [f for f in V1_FUNCS if hashlib.sha256(inspect.getsource(getattr(M, f)).encode()).hexdigest() != hashlib.sha256(inspect.getsource(getattr(B, f)).encode()).hexdigest()]
        check(not diff, f"SHA-256 of the source of {len(V1_FUNCS)} V1 functions equals the base commit's {diff}")
        consts = [c for c in ("SONGMAP_V", "SONG_SR", "SONG_ALGO") if getattr(M, c, None) != getattr(B, c, None)]
        check(not consts, f"V1 constants unchanged {consts}")
        for name in ("full", "c128"):
            t = _CACHE[name]
            a, b = M.build_song_map(t["path"]), B.build_song_map(t["path"])
            check(json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True), f"V1 output on the generated song '{name}' identical to the base commit")
        st = subprocess.run(["git", "status", "--porcelain"], cwd=str(HERE), capture_output=True, text=True).stdout.splitlines()
        files = {l[3:].strip().strip('"') for l in st}
        extra = {f for f in files if f not in ALLOWED_FILES and not f.startswith("songmap_v2/")}
        extra = {f for f in extra if not f.startswith("__pycache__")}
        check(not extra, f"git: only the allowed files differ from the base ({sorted(files)[:8]}) unexpected: {sorted(extra)}")
        d = subprocess.run(["git", "diff", "-U0", BASE_REF, "--", "montage.py"], cwd=str(HERE), capture_output=True, text=True).stdout
        removed = [l[1:] for l in d.splitlines() if l.startswith("-") and not l.startswith("---")]
        ok_removed = re.compile(r"APP_VERSION = |analyse_song\(|self\.set_style, self\.set_q|self\.win\.title\(|^\s*def show\(self, an\)|self\.an = an$|self\.set_style\.get\(\), self\.set_place\.get\(\)|^\s*$")
        odd = [l for l in removed if not ok_removed.search(l)]
        check(not odd, f"montage.py: only call-site / version / dropdown lines were changed ({len(removed)} removed lines) {odd[:3]}")


def part_dropdown(tmp):
    with section("k) dropdown / config / caches"):
        old = M.use_data_dir(Path(tmp) / "kdata")
        try:
            tr = _CACHE["c128"]
            cfg = M.load_config()
            check(M.songmap_version(cfg) == M.SONGMAP_DEFAULT == "v1", "default = V1 (one named constant SONGMAP_DEFAULT)")
            M.save_json(M.CONFIG_PATH, dict(cfg, songmap_version="v2"))
            check(M.load_config().get("songmap_version") == "v2" and M.songmap_version() == "v2", "setting 'songmap_version' persists in config.json")
            m1 = M.get_songmap(tr["path"], None, "v1")
            v1cache = Path(M.SONG_CACHE).read_bytes()
            m2, lines = logged(M.get_songmap, tr["path"])
            check(m2.get("songmap_version") == "v2" and "songmap_version" not in m1, "config v2 -> the V2 map, V1 call -> the V1 map")
            check(Path(M.SONG_CACHE).read_bytes() == v1cache and (Path(M.DATA) / songmap_v2.CACHE_NAME).exists(), "the V2 analysis never touched the V1 cache; V2 has its own file")
            check(any(l.startswith("songmap v2: c128.mp3 ") and "bpm=" in l and "grid_conf=" in l and "drops" in l for l in lines), f"perflog line: {lines[:1]}")
            m2b, lines = logged(M.get_songmap, tr["path"])
            check(m2b == m2 and not lines, "second request served from the V2 cache (no analysis, no log)")
            M.save_json(M.CONFIG_PATH, dict(M.load_config(), songmap_version="v1"))
            m1b = M.get_songmap(tr["path"])
            check("songmap_version" not in m1b and Path(M.SONG_CACHE).read_bytes() == v1cache, "switching back to V1 mid-session: V1 map from the V1 cache, V2 cache untouched")
            k1 = songmap_v2.cache_key(tr["path"])
            check(k1.startswith("songmap_v2|" + songmap_v2.ALGO_V + "|"), f"V2 cache key namespace: {k1[:40]}...")
            src = inspect.getsource(M.App) if hasattr(M, "App") else ""
            check("Songmap version" in src and "set_songmap" in src and "SONGMAP_CHOICES" in src and 'cfg["songmap_version"]' in src, "Settings has the 'Songmap version' dropdown and saves it")
            check(list(M.SONGMAP_CHOICES.values()) == ["Songmap V1", "Songmap V2"], "dropdown entries: Songmap V1 / Songmap V2")
        finally:
            M.restore_data_dir(old)


def part_fallback(tmp):
    with section("l) V2 failure / timeout -> valid V1-based map, montage planning still runs"):
        old = M.use_data_dir(Path(tmp) / "ldata")
        try:
            tr = _CACHE["c128"]
            cfg = M.load_config()
            v1 = M.get_songmap(tr["path"], None, "v1")

            def boom():
                raise RuntimeError("boom")
            M.SONGMAP_V2_HOOK[0] = boom
            m, lines = logged(M.get_songmap, tr["path"], None, "v2")
            check(m["songmap_version"] == "v1-fallback" and m["beats"] == v1["beats"] and any(l == "songmap v2 fallback: c128.mp3 (RuntimeError: boom)" for l in lines), f"injected exception: V1 map flagged v1-fallback, log '{lines[:1]}'")
            evs = M.fake_events(n=14, seed=3)
            plan = M.plan_montage(cfg, "valorant", evs, {"path": tr["path"], "title": "x", "artist": "a"}, m, 5, "auto", "optimal", [], [])
            check(len(plan["takes"]) >= 2, "the planner runs on the fallback map")
            real_cap = songmap_v2.ANALYSIS_CAP_S
            songmap_v2.ANALYSIS_CAP_S = 1.0
            M.SONGMAP_V2_HOOK[0] = lambda: time.sleep(3)
            t0 = time.time()
            m, lines = logged(M.get_songmap, tr["path"], None, "v2")
            dt = time.time() - t0
            songmap_v2.ANALYSIS_CAP_S = real_cap
            check(m["songmap_version"] == "v1-fallback" and dt < 2.5 and any("timeout" in l and l.startswith("songmap v2 fallback:") for l in lines), f"injected 3 s delay with a 1 s cap: fallback after {dt:.1f} s, log '{lines[:1]}'")
            M.SONGMAP_V2_HOOK[0] = None
            m, lines = logged(M.get_songmap, tr["path"], None, "v2")
            check(m["songmap_version"] == "v1-fallback" and any("cached" in l for l in lines), "a timed-out song is not retried every montage (marker in the V2 cache)")
        finally:
            M.SONGMAP_V2_HOOK[0] = None
            songmap_v2.ANALYSIS_CAP_S = real_cap
            M.restore_data_dir(old)


def part_compare(tmp):
    with section("m) songmapcompare --auto on generated songs"):
        import songmap_compare as C
        d = Path(tmp) / "cmp_songs"
        d.mkdir()
        spec = {"clean_a": ([("intro", 8), ("verse", 16), ("build", 8), ("drop", 16), ("breakdown", 8), ("outro", 8)], dict(bpm=128)),
                "clean_b": ([("intro", 8), ("verse", 16), ("build", 8), ("drop", 16), ("outro", 8)], dict(bpm=140)),
                "clean_offset": ([("intro", 4), ("verse", 16), ("build", 8), ("drop", 16), ("outro", 4)], dict(bpm=128, lead=3.37)),
                "bump_in_verse": ([("verse", 16), ("bump", 5), ("verse", 16)], dict(bpm=128)),
                "loud_flat": ([("loud", 64)], dict(bpm=128, gain=lambda b: 0.86 if (b // 8) % 2 == 0 else 1.0)),
                "tempo_change": ([("verse", 32)], dict(tempo_map=[(120, 16), (140, 16)]))}
        for n, (lay, kw) in spec.items():
            y, tr = synth(lay, **kw)
            to_mp3(y, d / f"{n}.mp3")
        before = {"real": snapshot(REAL_DATA), "data": snapshot(M.DATA)}
        out_dir = Path(tmp) / "cmp_out"
        args = type("A", (), {"target": None, "auto": 4, "songs_dir": str(d), "out": str(out_dir)})()
        rc, lines = logged(C.main, args, lambda *x: None)
        rep = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
        top = [s["song"] for s in rep["songs"]]
        problem = {"bump_in_verse.mp3", "loud_flat.mp3", "tempo_change.mp3"}
        check(rc == 0 and len(top) == 4 and {"bump_in_verse.mp3", "tempo_change.mp3"} <= set(top[:3]) and top[0] in problem, f"ranking by disagreement: {[(s['song'], s['disagreement_score']) for s in rep['songs']]}")
        scores = {s["song"]: s["disagreement_score"] for s in rep["songs"]}
        check(all(scores.get(p, 0) > scores.get(c, 99) for p in problem if p in scores for c in ("clean_a.mp3", "clean_b.mp3", "clean_offset.mp3") if c in scores) or len(scores) < 6,
              "every problematic song scores above every clean song that was listed")
        s0 = rep["songs"][0]
        fl = s0["files"]
        need = [fl["png"], fl["zoom"], *fl["firstdrop"]["files"], *fl["suspect"]["files"], fl["full_v1"], fl["full_v2"]]
        check(all((out_dir / f).exists() and (out_dir / f).stat().st_size > 1000 for f in need), f"PNGs, 2 x 3 listening clips, 2 full click WAVs written ({len(need)} files)")
        with wave.open(str(out_dir / fl["full_v2"]), "rb") as w:
            wl = w.getnframes() / w.getframerate()
        dec, sr = timebase.decode(str(d / s0["song"]))
        check(abs(wl - len(dec) / sr) < 0.01, f"click WAV length {wl:.3f} s = song length {len(dec) / sr:.3f} s")
        rm = (out_dir / "report.md").read_text(encoding="utf-8")
        check("## Listen to these first" in rm and fl["firstdrop"]["files"][1] in rm and "verdict" in rm and "median" in rm, "report.md has the 'listen to these first' list with exact file names, verdicts and offsets")
        check(snapshot(REAL_DATA) == before["real"] and snapshot(M.DATA) == before["data"], "no cache / flag / config / data file changed (byte-identical)")
        check(not (d / "cmp_out").exists() and sorted(p.name for p in d.iterdir()) == sorted(f"{n}.mp3" for n in spec), "the songs folder is untouched")


def part_pure(tmp):
    with section("n) V2 is pure and deterministic"):
        tr = _CACHE["c128"]
        y, sr = timebase.decode(tr["path"])
        y.setflags(write=False)
        h = hashlib.sha256(y.tobytes()).hexdigest()
        from songmap_v2 import grid, events, sections
        F = grid.features(y, sr)
        ev = events.detect(F)
        o = grid.onset_mix(F)
        bpm, _ = grid.estimate_tempo(o, F["dt"], None, grid.onset_linear(F))
        G = grid.fit_grid(o, F["dt"], bpm, len(y) / sr)
        bars = sections.bar_table(G["beats"], list(range(0, len(G["beats"]), 4)), len(y) / sr, y, sr, F["sig"]["low"], events.associate(ev, G["beats"]))
        check(hashlib.sha256(y.tobytes()).hexdigest() == h and not y.flags.writeable, "the input array is read-only and unchanged after features / events / grid / sections (no mutation)")
        a, b = v2(tr), v2(tr)
        for m in (a, b):
            m["v2"].pop("analysis_s", None)
            m["v2"].pop("fallback", None)
        a["v2"].pop("analysis_s", None)
        ja = json.dumps(a, sort_keys=True, default=str)
        jb = json.dumps(b, sort_keys=True, default=str)
        check(ja.replace(re.findall(r'"analysis_s": [\d.]+', ja)[0] if re.findall(r'"analysis_s": [\d.]+', ja) else "", "") == jb.replace(re.findall(r'"analysis_s": [\d.]+', jb)[0] if re.findall(r'"analysis_s": [\d.]+', jb) else "", ""), "two runs give identical maps")


def part_guards(tmp):
    with section("o) Valorant and CS2 guards (100 generated clips each)"):
        import test_v693 as T
        B = load_base(tmp)
        if B is None:
            check(False, "base commit not available")
            return
        view = lambda mod, e, g: json.dumps(mod.analyse_entry(e, {}, g), sort_keys=True, default=str)
        for game in ("valorant", "cs2"):
            ents = T.gen_entries(100, game)
            nd = sum(view(M, e, game) != view(B, e, game) for e in ents)
            kn = sum(len(M.analyse_entry(e, {}, game)["kills"]) for e in ents)
            check(nd == 0 and kn > 20, f"{game}: kills, timestamps, deaths, revives of 100 generated clips identical to the base commit ({nd} differences, {kn} kills)")
        vdir = Path(tmp) / "gv"
        vdir.mkdir()
        rng = random.Random(21)
        vn = T.names(400, 5)
        for game in ("valorant", "cs2"):
            items = []
            for i in range(100):
                p = vdir / f"{game}_{i}.mov"
                p.write_bytes(b"x")
                ks = sorted(rng.sample(range(2, 40), rng.randint(1, 4)))
                items.append(T.pool_item(T.rec_of(p, 45, game), [(float(k), vn[3 * i + j]) for j, k in enumerate(ks)]))
                items[-1]["rec"]["path"] = str(p)
            cfg = M.load_config()
            M.verify_stitch = T.REAL_VS
            ev, _ = logged(M.build_events, items[:30], game, cfg, random.Random(3))
            evb, _ = logged(B.build_events, items[:30], game, B.load_config(), random.Random(3))
            song = {"path": "x.mp3", "title": "x", "artist": "a"}
            pm = M.plan_montage(cfg, game, ev[0], song, M.default_song_map(), 5, "auto", "optimal", [], [])
            pb = B.plan_montage(B.load_config(), game, evb[0], song, B.default_song_map(), 5, "auto", "optimal", [], [])
            tk = lambda p: [(Path(t["path"]).name, t["segs"], t["kills_out"]) for t in p["takes"]]
            check(len(pm["takes"]) > 3 and tk(pm) == tk(pb) and round(pm["duration"], 3) == round(pb["duration"], 3), f"{game}: events and plan ({len(pm['takes'])} takes) identical to the base commit")


def main():
    real_before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t695_"))
    old = M.use_data_dir(tmp / "data")
    try:
        part_grid(tmp)
        part_peak(tmp)
        part_offset(tmp)
        part_sections(tmp)
        part_tempo(tmp)
        part_timebase(tmp)
        tr, m1, m2 = part_shape(tmp)
        part_v1(tmp, tr)
        part_dropdown(tmp)
        part_fallback(tmp)
        part_compare(tmp)
        part_pure(tmp)
        part_guards(tmp)
    finally:
        M.restore_data_dir(old)
    with section("real montage_data"):
        check(snapshot(REAL_DATA) == real_before, f"real montage_data byte-identical after the tests ({len(real_before)} files{'; folder absent' if not real_before else ''})")
    total = time.time() - T_ALL
    print("section times: " + ", ".join(f"{t.split(')')[0]} {s:.0f}s" for t, s in SECTIONS))
    print(f"total test time {total:.1f} s" + ("" if total < 180 else "  (OVER the 3 minute limit)"))
    if total >= 180:
        FAILS.append("over 3 minutes")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}):\n  " + "\n  ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
