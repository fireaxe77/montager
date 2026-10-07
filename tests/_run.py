"""Shared subprocess helper of the V6.9.x tests (V6.9.7).

Every test that starts a child process uses `run()` from here instead of subprocess.run:
  * text mode decodes as UTF-8 with errors="replace" (never the Windows console codepage: the CS2 default name
    '火斧' is bytes E7 81 AB, and byte 0x81 is undefined in cp1252 -> UnicodeDecodeError in the reader thread),
  * the child gets PYTHONIOENCODING=utf-8 and PYTHONUTF8=1 (so the child never fails to ENCODE either),
  * stdout / stderr are never None (empty str / bytes instead) and a timeout is a result, not an exception,
  * `require()` turns a bad result into a clear failure message instead of an AttributeError later.
Cloud reproduction of the Windows console: run the tests with LOCPATH=<dir with a CP1252 locale> LC_ALL=en_US.CP1252
PYTHONIOENCODING=cp1252 (the parent then decodes child output as cp1252 exactly like the user's PC unless the helper
forces UTF-8, which it does). `run(..., utf8=False)` leaves the child on cp1252 and exists only for that reproduction.
"""
import os
import subprocess
from dataclasses import dataclass


@dataclass
class Result:
    returncode: int
    stdout: object
    stderr: object
    timed_out: bool = False
    cmd: object = None

    @property
    def ok(self):
        return self.returncode == 0 and not self.timed_out

    def tail(self, n=300):
        s = self.stderr if isinstance(self.stderr, str) else self.stderr.decode("utf-8", "replace")
        o = self.stdout if isinstance(self.stdout, str) else self.stdout.decode("utf-8", "replace")
        return (o + s)[-n:]


def child_env(env=None, utf8=True):
    e = dict(os.environ if env is None else env)
    if utf8:
        e["PYTHONIOENCODING"], e["PYTHONUTF8"] = "utf-8", "1"
    else:
        e["PYTHONIOENCODING"], e["PYTHONUTF8"] = "cp1252", "0"
    return e


def run(cmd, text=False, cwd=None, env=None, timeout=None, input=None, check=False, utf8=True, **kw):
    kw.pop("capture_output", None)
    kw.pop("encoding", None)
    kw.pop("errors", None)
    if text and isinstance(input, bytes):
        input = input.decode("utf-8", "replace")
    try:
        p = subprocess.run(cmd, capture_output=True, cwd=None if cwd is None else str(cwd), env=child_env(env, utf8), timeout=timeout,
                           input=input, **({"encoding": "utf-8", "errors": "replace"} if text else {}), **kw)
        res = Result(p.returncode, p.stdout if p.stdout is not None else ("" if text else b""),
                     p.stderr if p.stderr is not None else ("" if text else b""), False, cmd)
    except subprocess.TimeoutExpired as ex:
        so, se = ex.stdout, ex.stderr
        dec = (lambda x: (x.decode("utf-8", "replace") if isinstance(x, bytes) else (x or ""))) if text else (lambda x: x or b"")
        res = Result(-1, dec(so), dec(se) if not text else dec(se) + f"\n[timeout after {timeout} s]", True, cmd)
    if check and not res.ok:
        raise RuntimeError(f"command failed ({res.returncode}): {cmd!r}: {res.tail()}")
    return res


def require(res, what=""):
    """(ok, message) for a check(): a clear text instead of 'NoneType has no attribute strip'."""
    if res.timed_out:
        return False, f"{what or res.cmd!r} timed out"
    if res.returncode != 0:
        return False, f"{what or res.cmd!r} exited {res.returncode}: {res.tail()}"
    return True, ""
