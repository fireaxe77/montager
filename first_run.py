"""Montager first run: creates montage_data\\config.json from config.example.json, ONLY when no config.json exists yet.

Start_Montager.bat runs this before the setup check. An existing config.json is never read, changed or replaced, so an
installed Montager keeps every setting. %USERPROFILE% in the example is replaced by your user folder, and the songs folder
named there is created (empty) so you have a place to put your MP3s and the Exportify CSV. Not used by the app itself.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("MONTAGER_DATA") or (HERE / "montage_data")).resolve()     # the same rule as montage.py
CONFIG = DATA / "config.json"
EXAMPLE = HERE / "config.example.json"


def expand(v):
    if isinstance(v, str):
        return os.path.expandvars(v)
    if isinstance(v, list):
        return [expand(x) for x in v]
    if isinstance(v, dict):
        return {k: expand(x) for k, x in v.items()}
    return v


def main():
    if CONFIG.exists():
        return 0                                       # an existing setup: nothing to do, nothing touched
    if not EXAMPLE.is_file():
        print(f"first run: {EXAMPLE.name} not found, skipped")
        return 0
    cfg = expand(json.loads(EXAMPLE.read_text(encoding="utf-8")))
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CONFIG)
    songs = cfg.get("mp3_dir")
    if songs:
        try:
            Path(songs).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    print("first run: created your settings file from config.example.json:")
    print(f"  {CONFIG}")
    print(f"  songs folder (put your MP3s and the Exportify CSV here): {songs}")
    print("  Next: in Montager open Settings and add your clip folders and your in-game player names.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
