"""Entry point of the packaged Montager (Montager.exe / Montager-CLI.exe, built by packaging/montager.spec).

It only prepares the environment and then starts the unchanged app exactly like `python montage.py` (montage.main()):
  - user data (settings, caches, logs) in a per-user folder: %LOCALAPPDATA%\\Montager\\montage_data (through MONTAGER_DATA,
    the app's own data-folder switch), never in the install folder
  - the bundled ffmpeg / ffprobe first on PATH
  - first run: the settings file is created from config.example.json (first_run.py), with empty clip folders
  - a setup check (setup_check.py): a plain-language list of what is missing, shown in a small window before the app opens
  - GPU fallback: when the NVIDIA encoder does not work on this PC, the app is told that the encoder is not there, so it takes
    its own x264 path (exactly what it does with an ffmpeg build without NVENC). On a PC where NVENC works nothing is changed.

Montager.exe (no console): the app.  Montager-CLI.exe (console): no arguments = the setup check; with arguments = the app's
command line (python montage.py <args>), e.g. `Montager-CLI.exe smoketest`.
"""
import io
import os
import subprocess
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
# Montager-CLI.exe is the console build; Montager.exe never acts as the CLI, even when started from a terminal that gives it a stdout
CONSOLE = Path(sys.executable).stem.lower().endswith("cli") if FROZEN else sys.stdout is not None


def user_data_dir():
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(root) / "Montager" / "montage_data"


def prepare_env():
    if FROZEN:
        os.environ.setdefault("MONTAGER_DATA", str(user_data_dir()))
        # librosa's numba functions cache their compiled code; inside the package there is no source folder for that cache
        os.environ.setdefault("NUMBA_CACHE_DIR", str(user_data_dir().parent / "numba_cache"))
    ff = BASE / "ffmpeg"
    if (ff / "ffmpeg.exe").is_file():
        os.environ["PATH"] = str(ff) + os.pathsep + os.environ.get("PATH", "")
    if str(BASE) not in sys.path:
        sys.path.insert(0, str(BASE))


def log(msg):
    try:
        d = Path(os.environ.get("MONTAGER_DATA") or (BASE / "montage_data")) / "logs"
        d.mkdir(parents=True, exist_ok=True)
        with open(d / "launcher.log", "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def nvenc_works():
    try:
        r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:r=30:d=0.1",
                            "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, timeout=30, creationflags=NO_WINDOW)
        return r.returncode == 0
    except Exception:                                      # noqa: BLE001
        return False


def gpu_fallback(montage):
    """No working NVIDIA encoder: the app sees no h264_nvenc encoder and encodes with x264 (its own non-NVENC path)."""
    if os.environ.get("MONTAGER_FORCE_NO_NVENC") != "1" and nvenc_works():
        log("GPU: NVIDIA encoder works - unchanged")
        return True
    orig = montage.ff_has

    def ff_has(kind, name):
        if kind == "encoders" and name == "h264_nvenc":
            return False
        return orig(kind, name)
    montage.ff_has = ff_has
    log("GPU: no working NVIDIA encoder - renders use x264 (CPU)")
    return False


def run_check(full):
    """(problem lines, warning lines, full text) from setup_check.py; full=False = settings only (fast, every start)."""
    import setup_check as sc
    sc.problems.clear()
    sc.warnings.clear()
    buf = io.StringIO()
    with redirect_stdout(buf):
        try:
            if full:
                sc.main()
            else:
                sc.check_settings()
        except Exception as ex:                            # noqa: BLE001
            print(f"  [WARN]    the setup check itself failed: {type(ex).__name__}: {ex}")
    return list(sc.problems), list(sc.warnings), buf.getvalue()


def show_check(text, n_problems, first):
    """A small window with the PROBLEM / WARN lines and their fixes. True = open Montager."""
    import tkinter as tk
    from tkinter import ttk
    keep = []
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if "[PROBLEM]" in ln or "[WARN]" in ln:
            keep.append(ln.replace("[PROBLEM]", "PROBLEM:").replace("[WARN]   ", "Note:").strip())
            j = i + 1
            while j < len(lines) and lines[j].startswith("            "):
                keep.append("      " + lines[j].strip())
                j += 1
            keep.append("")
    res = {"open": False}
    root = tk.Tk()
    root.title("Montager - setup check")
    try:
        root.iconbitmap(str(BASE / "montager.ico"))
    except Exception:                                      # noqa: BLE001
        pass
    root.geometry("820x520")
    head = ("Welcome to Montager! A few things are still missing before it can make a montage.\n"
            "Most are filled in on Montager's Settings tab (you can open it now)." if first else
            f"{n_problems} thing(s) still need fixing before Montager can make a montage (most are in Settings).")
    ttk.Label(root, text=head, wraplength=780, justify="left", font=("Segoe UI", 11)).pack(anchor="w", padx=14, pady=(12, 6))
    bar = ttk.Frame(root)                                  # packed first at the bottom: a small window never hides the buttons
    bar.pack(side="bottom", fill="x", padx=14, pady=10)
    ttk.Label(root, text=f"Your settings and caches: {os.environ.get('MONTAGER_DATA', '')}\n"
                         "Full check any time: Start menu > Montager setup check.",
              font=("Segoe UI", 9), foreground="#666").pack(side="bottom", anchor="w", padx=14, pady=(6, 0))
    box = tk.Text(root, wrap="word", font=("Segoe UI", 10), relief="flat", padx=8, pady=6, height=12)
    box.insert("1.0", "\n".join(keep) or "Everything is ready.")
    box.configure(state="disabled")
    box.pack(fill="both", expand=True, padx=14)

    def go():
        res["open"] = True
        root.destroy()
    ttk.Button(bar, text="Quit", command=root.destroy).pack(side="right", padx=(6, 0))
    b = ttk.Button(bar, text="Open Montager", command=go)
    b.pack(side="right")
    b.focus_set()
    root.bind("<Return>", lambda e: go())
    root.lift()
    root.attributes("-topmost", True)
    root.after(400, lambda: root.attributes("-topmost", False))
    root.mainloop()
    return res["open"]


def gui_start():
    import first_run
    cfg_new = not (Path(os.environ.get("MONTAGER_DATA") or (BASE / "montage_data")) / "config.json").exists()
    first_run.main()
    probs, warns, text = run_check(full=cfg_new)
    log(f"start: first run {cfg_new}, {len(probs)} problem(s), {len(warns)} warning(s)")
    if probs and os.environ.get("MONTAGER_NO_CHECK_WINDOW") != "1":
        if not show_check(text, len(probs), cfg_new):
            return 0
    import montage
    gpu_fallback(montage)
    sys.argv = [sys.argv[0]]
    montage.main()
    return 0


def cli(args):
    if args and args[0].lower().endswith("montage.py"):        # the app's own tests start `<python> <HERE>\\montage.py <cmd>`
        args = args[1:]
    if not args:
        import setup_check as sc
        rc = sc.main()
        try:
            input("\nPress Enter to close.")
        except EOFError:
            pass
        return rc
    import montage
    gpu_fallback(montage)
    sys.argv = [sys.argv[0]] + list(args)
    montage.main()
    return 0


def main():
    prepare_env()
    if CONSOLE:                                            # Montager-CLI.exe
        return cli(sys.argv[1:])
    if len(sys.argv) > 1:                                  # Montager.exe <args>: the app's command line, without a console
        return cli(sys.argv[1:])
    return gui_start()


if __name__ == "__main__":
    sys.exit(main())
