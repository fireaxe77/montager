"""V6.1.2 checks (no render, no smoketest):  xvfb-run -a -s "-screen 0 1920x1200x24" python3 test_v612.py [workers audio match theme]
Without arguments every section runs. Exit code 1 when anything fails."""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="montager_v612_"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tkinter as tk

import montage as M

FAILS = []


def check(ok, msg):
    print(("  ok   " if ok else "  FAIL ") + msg)
    if not ok:
        FAILS.append(msg)


# ---------------------------------------------------------------- 1a: workers never touch Tk
def t_workers():
    print("[1a] workers never touch Tk during startup")
    main = threading.main_thread()
    bad = []
    orig = {}

    def guard(cls, name):
        fn = getattr(cls, name)
        orig[(cls, name)] = fn

        def w(self, *a, **k):
            if threading.current_thread() is not main and threading.current_thread().name != "perf-sampler":
                bad.append(f"{cls.__name__}.{name} from {threading.current_thread().name}")
            return fn(self, *a, **k)
        setattr(cls, name, w)
    for nm in ("get", "set"):
        guard(tk.Variable, nm)
    for nm in ("configure", "cget", "winfo_exists", "after", "update_idletasks"):
        guard(tk.Misc, nm)
    guard(tk.Text, "insert")
    M.messagebox.askyesno = lambda *a, **k: False
    app = M.App(0)
    deadline = time.time() + 20
    while (app.busy or app.pending) and time.time() < deadline:
        app.root.update()
        time.sleep(0.02)
    for _ in range(20):
        app.root.update()
        time.sleep(0.02)
    for (cls, name), fn in orig.items():
        setattr(cls, name, fn)
    app.flush_log()
    log = app.log.get("1.0", "end")
    check(not bad, "no worker thread called a Tk variable / widget method" + (": " + "; ".join(sorted(set(bad))[:5]) if bad else ""))
    check("ERROR in clips" not in log and "main thread is not in main loop" not in log, "the first clip load (load_clips) ran without an error")
    check(isinstance(getattr(app, "clips", None), list) and hasattr(app, "byp"), "load_clips handed its result to the UI (app.clips / byp set)")
    check(app._snap.get("m_game") in M.GAMES, f"m_game snapshot = {app._snap.get('m_game')}")
    app.root.destroy()


# ---------------------------------------------------------------- 1b: audio files that are still being written
def t_audio():
    print("[1b] scan_audio and files still being written")
    d = Path(tempfile.mkdtemp(prefix="mt_mp3_"))
    M.AUDIO_CACHE = d / "audio_cache.json"
    M.AUDIO_STABLE_WAIT_S = 0.3
    cfg = dict(M.load_config(), mp3_dir=str(d), output_root=str(d / "_out"))
    old = time.time() - 600
    stable = d / "Artist - Stable.mp3"
    stable.write_bytes(b"\0" * 5000)
    os.utime(stable, (old, old))
    fresh = d / "Artist - Fresh.mp3"
    fresh.write_bytes(b"\0" * 5000)                          # mtime = now
    empty = d / "Artist - Empty.mp3"
    empty.touch()
    os.utime(empty, (old, old))
    growing = d / "Artist - Growing.mp3"
    growing.write_bytes(b"\0" * 1000)
    os.utime(growing, (old, old))
    stop = threading.Event()

    def grow():
        while not stop.is_set():
            with open(growing, "ab") as f:
                f.write(b"\0" * 4096)
            time.sleep(0.05)
    th = threading.Thread(target=grow, daemon=True)
    th.start()
    try:
        recs = M.scan_audio(cfg)
    except Exception as ex:
        recs = None
        check(False, f"scan_audio raised {type(ex).__name__}: {ex}")
    stop.set()
    th.join()
    names = sorted(Path(r["path"]).name for r in (recs or []))
    check(names == ["Artist - Stable.mp3"], f"only the stable file is returned: {names}")
    cache = json.loads(M.AUDIO_CACHE.read_text(encoding="utf-8"))
    check(len(cache) == 1 and all(Path(v["path"]).name == "Artist - Stable.mp3" for v in cache.values()), "only the stable file is cached (no partial file)")
    check(recs and recs[0].get("key") in cache, "the stored key is the cache key (computed once)")
    # a file that disappears between listing and reading must not raise
    real_stat = os.stat
    gone = str(stable)
    calls = {"n": 0}

    def flaky(p, *a, **k):
        if str(p) == gone:
            calls["n"] += 1
            if calls["n"] > 1:
                raise FileNotFoundError(p)
        return real_stat(p, *a, **k)
    os.stat = flaky
    try:
        r2 = M.scan_audio(cfg)
        check(True, f"a file that vanishes after listing does not raise ({len(r2)} record(s))")
    except Exception as ex:
        check(False, f"vanishing file raised {type(ex).__name__}: {ex}")
    finally:
        os.stat = real_stat
    os.utime(fresh, (old, old))                              # no longer fresh -> picked up next time
    r3 = M.scan_audio(cfg)
    check("Artist - Fresh.mp3" in [Path(r["path"]).name for r in r3], "a skipped file is picked up on the next run")


SECTIONS = {"workers": t_workers, "audio": t_audio}

if __name__ == "__main__":
    want = sys.argv[1:] or list(SECTIONS)
    for k in want:
        SECTIONS[k]()
    print("\nFAILED: %d" % len(FAILS) if FAILS else "\nALL OK")
    sys.exit(1 if FAILS else 0)
