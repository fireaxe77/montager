"""One command for a Montager release (Windows):  python packaging/make_release.py

For the version on main (APP_VERSION in montage.py = the title bar):
  1. exports origin/main with `git archive` into build/src (a clean copy: never your working folder or montage_data)
  2. checks that the app files there are identical to the git tag of that version (v9.3.0 for V9.3.0)
  3. builds Montager.exe + Montager-CLI.exe (PyInstaller, packaging/montager.spec) with FFmpeg and the OCR engine inside
  4. checks the app files inside the build: data files byte for byte, Python modules by their compiled code
  5. builds Montager-Portable.zip, Montager-Setup.exe (Inno Setup) and Montager-Python.zip (the plain Python version)
  6. creates or updates the GitHub Release of that tag: the three files (replaced when present) + notes from the newest
     entry of docs/CHANGELOG_SIMPLE.md. It never creates or moves a tag: tag the version first.

Options: --ref <git ref> (default origin/main)  --allow-untagged (app files may differ from the tag; listed in the notes)
         --no-upload (build and check only)  --max-gb 1.0 (stop before uploading a bigger file)
Needs: git, Python with the app's packages + PyInstaller, Inno Setup 6 (ISCC.exe), ffmpeg on PATH (or MONTAGER_FFMPEG_DIR),
a GitHub login in git's credential manager (or GITHUB_TOKEN).
"""
import argparse
import hashlib
import json
import marshal
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
SRC, DIST, WORK, OUT = BUILD / "src", BUILD / "dist", BUILD / "work", BUILD / "release"
REPO = "fireaxe77/montager"
# the app as the user runs it (bundled unchanged); everything else in the package is packaging
APP_FILES = ["montage.py", "intro90.py", "songmap_compare.py", "songmap_v2", "fonts/*.ttf", "fonts/README.txt", "fixtures", "montage.ico",
             "montage.png", "CHANGELOG.md", "docs/CHANGELOG_SIMPLE.md"]
PY_MODULES = ["montage", "intro90", "songmap_compare"]
OVERLAY = ["packaging", "setup_check.py", "first_run.py", "config.example.json", "LICENSE", "CREDITS.md"]
PY_ZIP_FILES = ["montage.py", "intro90.py", "songmap_compare.py", "songmap_v2", "fonts", "fixtures", "montage.ico", "montage.png",
                "Montager.vbs", "Montage.vbs", "Create_Desktop_Shortcut.vbs", "Set_Shortcut_AppId.ps1", "Start_Montager.bat",
                "setup_check.py", "first_run.py", "config.example.json", "START_HERE.txt", "README.md", "LICENSE", "CREDITS.md",
                "CHANGELOG.md", "docs/CHANGELOG_SIMPLE.md", "docs/guides", "docs/PROJECT_STRUCTURE.md"]
ASSETS = {"setup": "Montager-Setup.exe", "portable": "Montager-Portable.zip", "python": "Montager-Python.zip"}


def say(msg):
    print(msg, flush=True)


def git(*a, cwd=ROOT, check=True):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(a)} failed: {r.stderr.strip()}")
    return r.stdout


def fresh(d):
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)


def export(ref):
    say(f"1. export {ref} -> {SRC}")
    fresh(SRC)
    tar = BUILD / "src.tar"
    subprocess.run(["git", "archive", "--format=tar", "-o", str(tar), ref], cwd=ROOT, check=True)
    subprocess.run(["tar", "-xf", str(tar), "-C", str(SRC)], check=True)
    tar.unlink()
    for name in OVERLAY:                                  # packaging inputs from this checkout (same as main once committed)
        s = ROOT / name
        if s.is_dir():
            shutil.copytree(s, SRC / name, dirs_exist_ok=True, ignore=shutil.ignore_patterns("build", "__pycache__"))
        elif s.is_file():
            shutil.copy2(s, SRC / name)


def app_version():
    m = re.search(r'^APP_VERSION = "V([0-9][0-9.]*)"', (SRC / "montage.py").read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit("APP_VERSION not found in montage.py")
    return m.group(1)


def check_tag(ref, tag, allow):
    say(f"2. app files of {ref} vs tag {tag}")
    if not git("tag", "--list", tag).strip():
        raise SystemExit(f"tag {tag} does not exist: tag the version first (this script never creates tags)")
    diff = git("diff", "--stat", tag, ref, "--", *[f":(glob){f}" if "*" in f else f for f in APP_FILES]).strip()
    if diff and not allow:
        raise SystemExit(f"the app files on {ref} differ from {tag}:\n{diff}\nTag the new version, or run with --allow-untagged.")
    say("   identical" if not diff else f"   DIFFERENT (allowed with --allow-untagged):\n{diff}")
    return diff


def version_info(ver):
    nums = (ver.split(".") + ["0", "0", "0", "0"])[:4]
    t = ",".join(str(int(x)) for x in nums)
    txt = f"""VSVersionInfo(ffi=FixedFileInfo(filevers=({t}), prodvers=({t}), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0),
 kids=[StringFileInfo([StringTable('040904B0', [StringStruct('CompanyName', 'fireaxe77'), StringStruct('FileDescription', 'Montager'),
 StringStruct('FileVersion', '{ver}'), StringStruct('InternalName', 'Montager'), StringStruct('LegalCopyright', 'MIT License, fireaxe77'),
 StringStruct('OriginalFilename', 'Montager.exe'), StringStruct('ProductName', 'Montager'), StringStruct('ProductVersion', '{ver}')])]),
 VarFileInfo([VarStruct('Translation', [1033, 1200])])])"""
    p = SRC / "packaging" / "build" / "version_info.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")


def build_exe():
    say("3. PyInstaller build")
    for d in (DIST, WORK):
        if d.exists():
            shutil.rmtree(d)
    log = BUILD / "pyinstaller.log"
    with open(log, "w", encoding="utf-8") as f:
        r = subprocess.run([sys.executable, "-m", "PyInstaller", str(SRC / "packaging" / "montager.spec"), "--noconfirm",
                            "--distpath", str(DIST), "--workpath", str(WORK)], cwd=SRC, stdout=f, stderr=subprocess.STDOUT)
    if r.returncode:
        raise SystemExit(f"PyInstaller failed, see {log}")
    app = DIST / "Montager"
    say(f"   {app}  ({tree_size(app) / 2**20:.0f} MB)")
    return app


def tree_size(d):
    return sum(p.stat().st_size for p in Path(d).rglob("*") if p.is_file())


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def same_code(a, b):
    """Two code objects are the same program: bytecode, constants (recursively), names, line table, exception table.
    (marshal bytes are not a fair test: they also depend on how objects happen to be shared in memory.)"""
    if type(a) is not type(b):
        return False
    if not hasattr(a, "co_code"):
        if isinstance(a, (tuple, frozenset, list)):
            return len(a) == len(b) and all(same_code(x, y) for x, y in zip(sorted(a, key=repr) if isinstance(a, frozenset) else a,
                                                                             sorted(b, key=repr) if isinstance(b, frozenset) else b))
        return a == b or (a != a and b != b)              # NaN constants
    for f in ("co_code", "co_names", "co_varnames", "co_freevars", "co_cellvars", "co_name", "co_qualname", "co_firstlineno",
              "co_linetable", "co_exceptiontable", "co_argcount", "co_kwonlyargcount", "co_posonlyargcount", "co_flags", "co_stacksize"):
        if getattr(a, f, None) != getattr(b, f, None):
            return False
    return same_code(a.co_consts, b.co_consts)


def verify_inside(app):
    """Data files: byte for byte. Python modules: the code PyInstaller stored = the code compiled from the exported source."""
    say("4. app files inside the build")
    import warnings
    warnings.simplefilter("ignore", SyntaxWarning)
    internal = app / "_internal"
    bad, n = [], 0
    for rel in ("fonts", "fixtures", "montage.ico", "montage.png", "CHANGELOG.md", "docs/CHANGELOG_SIMPLE.md"):
        src = SRC / rel
        for s in ([src] if src.is_file() else [p for p in src.rglob("*") if p.is_file()]):
            r = s.relative_to(SRC)
            n += 1
            if not (internal / r).is_file() or sha(internal / r) != sha(s):
                bad.append(str(r))
    from PyInstaller.archive.readers import CArchiveReader
    pkg = CArchiveReader(str(app / "Montager.exe"))
    pyz = next(name for name in pkg.toc if name.endswith(".pyz") or name == "PYZ.pyz" or name.startswith("PYZ"))
    reader = pkg.open_embedded_archive(pyz)
    mods = PY_MODULES + ["songmap_v2." + p.stem if p.stem != "__init__" else "songmap_v2" for p in sorted((SRC / "songmap_v2").glob("*.py"))]
    for m in mods:
        n += 1
        try:
            code = reader.extract(m)
            code = marshal.loads(code) if isinstance(code, (bytes, bytearray)) else code
            rel = Path(*m.split(".")).with_suffix(".py") if m != "songmap_v2" else Path("songmap_v2/__init__.py")
            mine = compile((SRC / rel).read_bytes(), code.co_filename, "exec", dont_inherit=True)
            if not same_code(mine, code):
                bad.append(f"{m} (compiled code differs)")
        except Exception as ex:                            # noqa: BLE001
            bad.append(f"{m} ({type(ex).__name__}: {ex})")
    if bad:
        raise SystemExit("files inside the build differ from the source:\n  " + "\n  ".join(bad))
    say(f"   {n} app files identical to {SRC.name} (= the exported ref)")
    return n


def make_zip(zpath, base, files, prefix):
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in files:
            p = base / rel
            for f in ([p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())):
                z.write(f, f"{prefix}/{f.relative_to(base).as_posix()}")


def build_packages(app, ver):
    say("5. portable ZIP, installer, Python ZIP")
    fresh(OUT)
    portable = OUT / ASSETS["portable"]
    note = app / "README - Montager portable.txt"
    note.write_text(f"Montager {ver} (portable). Double-click Montager.exe.\r\n"
                    "Your settings, caches and logs are kept in %LOCALAPPDATA%\\Montager\\montage_data (not in this folder).\r\n"
                    "What is missing before the first montage: double-click Montager-CLI.exe (setup check).\r\n"
                    "Guide: https://github.com/fireaxe77/montager#readme\r\n", encoding="utf-8")
    make_zip(portable, app.parent, [app.name], "Montager")
    note.unlink()
    iscc = shutil.which("ISCC") or next((str(p) for p in (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
                                                          Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe")) if p.is_file()), None)
    if not iscc:
        raise SystemExit("Inno Setup 6 not found (winget install JRSoftware.InnoSetup)")
    r = subprocess.run([iscc, "/Q", f"/DAppVersion={ver}", f"/DSourceDir={app}", f"/DOutDir={OUT}", "/FMontager-Setup",
                        str(SRC / "packaging" / "montager.iss")], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit("Inno Setup failed:\n" + r.stdout[-2000:] + r.stderr[-2000:])
    make_zip(OUT / ASSETS["python"], SRC, [f for f in PY_ZIP_FILES if (SRC / f).exists()], f"Montager-V{ver}")
    files = {k: OUT / v for k, v in ASSETS.items()}
    for k, p in files.items():
        say(f"   {p.name}: {p.stat().st_size / 2**20:.0f} MB")
    return files


def newest_changelog(ver):
    txt = (SRC / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    parts = re.split(r"(?m)^## ", txt)
    entry = next((p for p in parts[1:] if p.startswith(f"V{ver}")), parts[1] if len(parts) > 1 else "")
    head, _, body = entry.partition("\n")
    return head.strip(), body.strip()


def notes(ver, untagged):
    head, body = newest_changelog(ver)
    base = f"https://github.com/{REPO}/releases/download/v{ver}"
    lines = [f"## {head}", "", body, "", "### Download (Windows 10 / 11, 64-bit)",
             f"- **[{ASSETS['setup']}]({base}/{ASSETS['setup']})**: the installer. Start menu entry, optional desktop shortcut; no admin needed. Recommended.",
             f"- [{ASSETS['portable']}]({base}/{ASSETS['portable']}): the same app without installing. Unzip, double-click `Montager.exe`.",
             f"- [{ASSETS['python']}]({base}/{ASSETS['python']}): the plain Python version (needs Python 3.12 + FFmpeg; see `START_HERE.txt`).",
             "", "Python, FFmpeg and the OCR engine are included in the installer and the portable ZIP. Your settings and caches live in "
             "`%LOCALAPPDATA%\\Montager` and survive updates and uninstalling.",
             "", "First start: Montager lists what is still missing (clip folders, songs + Exportify CSV, your in-game name). "
             "Guide: [README](https://github.com/fireaxe77/montager#readme)."]
    if untagged:
        lines += ["", f"_The download is built from main, which has small fixes after the v{ver} tag._"]
    return "\n".join(lines)


def token():
    t = os.environ.get("GITHUB_TOKEN")
    if t:
        return t
    r = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n", capture_output=True, text=True,
                       env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
    m = re.search(r"^password=(.+)$", r.stdout, re.M)
    if not m:
        raise SystemExit("no GitHub login: set GITHUB_TOKEN or log in once with git (push to the repo)")
    return m.group(1).strip()


def api(method, url, tok, data=None, ctype="application/json"):
    body = json.dumps(data).encode() if isinstance(data, dict) else data
    req = urllib.request.Request(url, data=body, method=method, headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                                                                          "Content-Type": ctype, "User-Agent": "montager-release"})
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as ex:
        return ex.code, json.loads(ex.read() or b"null")


def publish(ver, files, text, max_gb):
    say("6. GitHub release")
    for p in files.values():
        if p.stat().st_size > max_gb * 2**30:
            raise SystemExit(f"{p.name} is {p.stat().st_size / 2**30:.2f} GB (> {max_gb} GB): not uploaded. Re-run with --max-gb if intended.")
    tok, tag, api_ = token(), f"v{ver}", f"https://api.github.com/repos/{REPO}"
    st, rel = api("GET", f"{api_}/releases/tags/{tag}", tok)
    if st == 404:
        st, rel = api("POST", f"{api_}/releases", tok, {"tag_name": tag, "name": f"Montager V{ver}", "body": text, "make_latest": "true"})
        if st >= 300:
            raise SystemExit(f"release not created: {st} {rel}")
        say(f"   created {rel['html_url']}")
    else:
        api("PATCH", f"{api_}/releases/{rel['id']}", tok, {"body": text, "make_latest": "true"})
        say(f"   updated {rel['html_url']}")
    _, assets = api("GET", f"{api_}/releases/{rel['id']}/assets?per_page=100", tok)
    for p in files.values():
        for a in assets or []:
            if a["name"] == p.name:
                api("DELETE", f"{api_}/releases/assets/{a['id']}", tok)
        ctype = "application/zip" if p.suffix == ".zip" else "application/vnd.microsoft.portable-executable"
        st, a = api("POST", f"https://uploads.github.com/repos/{REPO}/releases/{rel['id']}/assets?name={p.name}", tok, p.read_bytes(), ctype)
        if st >= 300:
            raise SystemExit(f"upload of {p.name} failed: {st} {a}")
        say(f"   {a['browser_download_url']}")
    return rel["html_url"]


def main():
    ap = argparse.ArgumentParser(description="Build and publish a Montager release (see the top of this file).")
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--allow-untagged", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--max-gb", type=float, default=1.0)
    a = ap.parse_args()
    if a.ref.startswith("origin/"):
        git("fetch", "-q", "origin")
    export(a.ref)
    ver = app_version()
    say(f"   version V{ver} (title bar), tag v{ver}")
    untagged = check_tag(a.ref, f"v{ver}", a.allow_untagged)
    version_info(ver)
    app = build_exe()
    verify_inside(app)
    files = build_packages(app, ver)
    text = notes(ver, bool(untagged))
    (OUT / "release_notes.md").write_text(text, encoding="utf-8")
    if a.no_upload:
        say(f"built (not uploaded): {OUT}")
        return 0
    url = publish(ver, files, text, a.max_gb)
    say(f"done: {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
