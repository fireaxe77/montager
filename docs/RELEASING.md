# Releasing

1. Merge the version to main as usual (APP_VERSION = the title bar), tag it `vX.Y.Z`, push main and the tag.
2. Run `python packaging/make_release.py` (needs PyInstaller, Inno Setup 6, ffmpeg on PATH; `--no-upload` = build and check only).
3. It builds the EXE, `Montager-Setup.exe`, `Montager-Portable.zip` and `Montager-Python.zip` from a clean export of main, checks the app files against the tag, and creates or updates that tag's GitHub Release with notes from the newest `docs/CHANGELOG_SIMPLE.md` entry.
4. The README links use `releases/latest/download/...`, so they need no edits. Outputs and logs are in `build/` (git-ignored).
