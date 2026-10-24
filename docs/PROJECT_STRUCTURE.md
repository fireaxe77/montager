# Project structure

Montager is one Python app that runs from the repository root. Developer details: [REPO_LAYOUT.md](REPO_LAYOUT.md).

## What you run

| File | What it does |
|---|---|
| `Start_Montager.bat` | Double-click launcher: first-run settings, read-only setup check, then starts Montager. |
| `Montager.vbs` | Starts Montager without a console window (`pythonw montage.py`). `Montage.vbs` is the old name and forwards to it. |
| `Create_Desktop_Shortcut.vbs` (+ `Set_Shortcut_AppId.ps1`) | Creates a "Montager" Desktop and Start menu shortcut with its own taskbar icon. |
| `setup_check.py` | Standalone read-only check of Python, packages, FFmpeg, OCR, GPU encoder, folders and player names. Not used by the app. |
| `first_run.py` | Creates `montage_data\config.json` from `config.example.json` when none exists. Not used by the app. |

## The app

| File / folder | What it does |
|---|---|
| `montage.py` | The whole app: GUI (tkinter), clip scanning and killfeed OCR, the planner (song map to cut list), effects and the FFmpeg render, plus the command line (`python montage.py --help`) and the built-in `smoketest`. |
| `intro90.py` | Intro / outro titles: text looks, title clean-up, speed profile. |
| `songmap_v2/` | Song analysis: beat grid, sections, drops (the "SongMap V2" used by default). Some modules are developer benchmark / diagnostic tools. |
| `songmap_compare.py` | Song map comparison tools, reached through `python montage.py songmapcompare` / `songmapcheck`. |
| `fonts/` | The six intro fonts (SIL OFL 1.1, see `fonts/OFL.txt`). |
| `fixtures/` | Small killfeed images used by `python montage.py smoketest`. |
| `montage.ico`, `montage.png` | App icon. |
| `config.example.json` | Example settings for a new install (copied to `montage_data\config.json` on first run). |

## Your data (never in the repository)

| Folder | What it holds |
|---|---|
| `montage_data\` | Settings (`config.json`), scan caches, song maps, used-clip flags, calibration, logs. Created next to `montage.py`. |
| Your clip folders | Only read. |
| Your songs folder + Exportify CSV | Only read. |
| Output folder | The montages and their plans. |

## Documentation and development

| File / folder | What it is |
|---|---|
| `README.md` | Start here. |
| `docs/guides/` | Install and troubleshooting guides. |
| `docs/images/` | README screenshots and demo GIF. |
| `CHANGELOG.md` | Technical version history. `docs/CHANGELOG_SIMPLE.md` is the readable one shown in Settings > Changelog. |
| `CREDITS.md` | Third-party credits and licenses. |
| `tests/` | Developer test scripts, one per version (`tests/test_vXYZ.py`). Not needed to use Montager. |
| `docs/proof_v*/`, `docs/*.md` | Developer notes and proof images from past versions. |
| `CLAUDE.md` | Notes for the AI coding assistant used in development. |
