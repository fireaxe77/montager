"""V6.9.7 tests: part 0 (test encoding fix: shared subprocess helper), part A (kill ledger + proof-based merging + time anchors), part B (utility override),
part D (interpolation checkbox). Generated clips / rows only, no renders; prints the elapsed time per section; ends with ALL OK only if every check ran and passed.
Run from the repo root or tests/:  python tests\\test_v697.py   (cloud container: xvfb-run -a python3 tests/test_v697.py)"""
import importlib
import platform
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v697_common import M, check, section, snapshot, REAL_DATA, FAILS, SECTIONS, ROOT        # noqa: E402
import _run as R                                                                             # noqa: E402

T_ALL = time.time()


def main():
    print(f"where: {platform.system()} {platform.release()} ({'cloud container' if not sys.platform.startswith('win') else 'Windows PC'}), python {platform.python_version()}")
    real_before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t697_"))
    old = M.use_data_dir(tmp / "data")
    try:
        with section("0) shared subprocess helper"):
            r = R.run([sys.executable, "-c", "print('\\u706b\\u65a7')"], text=True, utf8=True)
            check(r.ok and r.stdout.strip() == "\\u706b\\u65a7".encode().decode("unicode_escape"), "a child printing the CS2 name is decoded as UTF-8 (cp1252 would crash on byte 0x81)")
            r = R.run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([0x81, 0xe7, 0x81]))"], text=True)
            check(r.ok and isinstance(r.stdout, str) and r.stderr == "", "undecodable bytes are replaced, never an exception")
            r = R.run([sys.executable, "-c", "import time; time.sleep(5)"], text=True, timeout=1)
            check(r.timed_out and R.require(r)[0] is False and "timed out" in R.require(r)[1], "a timeout is a result with a clear message")
            r = R.run([sys.executable, "-c", "import sys; sys.exit(3)"], text=True)
            ok, why = R.require(r, "child")
            check(not ok and "exited 3" in why, "a failing child gives a clear failure text (no NoneType.strip)")
        for name in ("v697_parta", "v697_partb", "v697_partd"):
            if (Path(__file__).resolve().parent / f"{name}.py").exists():
                mod = importlib.import_module(name)
                for fn in getattr(mod, "ORDER", None) or [f for f in ("part_anchor", "part_proof", "part_cap", "part_ledger", "part_commands", "part_guard", "part_real") if hasattr(mod, f)]:
                    getattr(mod, fn)(tmp)
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
