# PyInstaller spec: one folder (dist/Montager) with Montager.exe (no console) and Montager-CLI.exe (console), sharing _internal/.
# Build: python -m PyInstaller packaging/montager.spec --noconfirm --distpath build/dist --workpath build/work
# (packaging/make_release.py runs it). The app files are bundled unchanged; packaging/montager_app.py is the entry point.
import os
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).resolve().parent
PKG = ROOT / "packaging"

ff_dir = Path(os.environ.get("MONTAGER_FFMPEG_DIR") or Path(shutil.which("ffmpeg")).parent)
ff_root = ff_dir.parent if ff_dir.name.lower() == "bin" else ff_dir

datas = [
    (str(ROOT / "fonts"), "fonts"),
    (str(ROOT / "fixtures"), "fixtures"),
    (str(ROOT / "montage.ico"), "."),
    (str(ROOT / "montage.png"), "."),
    (str(ROOT / "CHANGELOG.md"), "."),
    (str(ROOT / "docs" / "CHANGELOG_SIMPLE.md"), "docs"),
    (str(ROOT / "config.example.json"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "CREDITS.md"), "."),
    (str(PKG / "THIRD_PARTY_LICENSES.md"), "."),
    (str(PKG / "assets" / "montager.ico"), "."),
    (str(ff_dir / "ffmpeg.exe"), "ffmpeg"),
    (str(ff_dir / "ffprobe.exe"), "ffmpeg"),
    (str(ff_root / "LICENSE"), "ffmpeg"),
    (str(ff_root / "README.txt"), "ffmpeg"),
    (str(PKG / "FFMPEG_SOURCE.txt"), "ffmpeg"),
]
datas = [(s, d) for s, d in datas if Path(s).exists()]
for pkg in ("sv_ttk", "rapidocr_onnxruntime", "librosa", "onnxruntime"):
    datas += collect_data_files(pkg)
for dist in ("numpy", "scipy", "opencv-python", "Pillow", "librosa", "soundfile", "mutagen", "rapidfuzz", "rapidocr-onnxruntime",
             "onnxruntime", "sv-ttk", "psutil", "fonttools", "numba", "llvmlite", "scikit-learn", "joblib", "audioread", "soxr",
             "lazy_loader", "pooch", "msgpack", "decorator", "threadpoolctl", "PyYAML", "shapely", "pyclipper", "six"):
    try:
        datas += copy_metadata(dist)
    except Exception:                                      # noqa: BLE001 - a package that is not installed is simply not credited twice
        pass

hidden = ["montage", "intro90", "songmap_compare", "setup_check", "first_run", "sv_ttk", "psutil", "fontTools.ttLib",
          "rapidocr_onnxruntime", "soundfile", "mutagen", "rapidfuzz", "PIL.ImageFont", "PIL.ImageFilter", "PIL.ImageChops"]
hidden += collect_submodules("songmap_v2")

a = Analysis([str(PKG / "montager_app.py")], pathex=[str(ROOT)], datas=datas, hiddenimports=hidden,
             excludes=["matplotlib", "IPython", "pytest", "notebook", "jupyter", "PyQt5", "PyQt6", "PySide6", "PyInstaller"],
             noarchive=False)
pyz = PYZ(a.pure)
icon = str(PKG / "assets" / "montager.ico")
version = str(PKG / "build" / "version_info.txt") if (PKG / "build" / "version_info.txt").exists() else None
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Montager", console=False, icon=icon, version=version,
          upx=False, disable_windowed_traceback=False)
cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Montager-CLI", console=True, icon=icon, version=version, upx=False)
coll = COLLECT(gui, cli, a.binaries, a.datas, name="Montager", upx=False)
