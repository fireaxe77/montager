"""V9.4: short measurement of the 50 fps interpolation (interp_prepare) on REAL clips: a 50 fps clip is interpolated, a 60 fps clip is left alone.
python tests\interp94.py <50 fps clip> <60 fps clip> [seconds per take, default 4]. Writes nothing but a temp folder; the job's quiet mode (below-normal priority, cores left free) is switched on like a real job."""
import sys
import tempfile
import threading
import time
from pathlib import Path

from _root import find_root
ROOT = find_root()
sys.path.insert(0, str(ROOT))
import montage as M                                                                           # noqa: E402


def take(path, a, secs, n0=0):
    nf = int(round(secs * 60))
    src = {"path": path, "shift": 0.0, "rect": [0, 0, 1920, 1080], "wh": [1920, 1080], "audio": False, "a_stream": 0, "gain_db": -6.0}
    return {"path": path, "srcs": [src], "rect": src["rect"], "wh": src["wh"], "audio": False, "segs": [[a, a + secs, 1.0, nf]], "kills_out": [0.5], "pulses": [], "amp": 0.0,
            "f0": n0, "nf": nf, "out_start": n0 / 60, "dur": nf / 60}


def main():
    c50, c60 = sys.argv[1], sys.argv[2]
    secs = float(sys.argv[3]) if len(sys.argv) > 3 else 4.0
    nf = int(round(secs * 60))
    plan = {"takes": [take(c50, 3.0, secs), take(c60, 3.0, secs, nf)], "duration": 2 * secs, "song": {"path": "x", "start_t": 0.0, "fade_out_start": 0.0}}
    lines = []
    M.out = M.LOGONLY = lambda *a: lines.append(" ".join(map(str, a)))
    import psutil
    load, stop = [], threading.Event()

    def sample():
        while not stop.is_set():
            load.append(psutil.cpu_percent(interval=0.5))
    th = threading.Thread(target=sample, daemon=True)
    M.job_quiet(True)
    th.start()
    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix="interp94_") as td:
        newp = M.interp_prepare(plan, {"interpolate_low_fps": True}, Path(td) / "t")
        dt = time.time() - t0
        stop.set()
        th.join()
        M.job_quiet(False)
        for l in lines:
            print(l)
        ch = [i for i, (a, b) in enumerate(zip(plan["takes"], newp["takes"])) if a is not b]
        print(f"changed takes: {ch} (expected [0]: the 50 fps clip only; the 60 fps take must stay the same object)")
        print(f"interp_prepare wall time {dt:.1f} s for {secs:g} s of 50 fps footage; system CPU load mean {sum(load) / max(1, len(load)):.0f} % peak {max(load or [0]):.0f} % over {len(load)} samples")
    return 0 if ch == [0] else 1


if __name__ == "__main__":
    sys.exit(main())
