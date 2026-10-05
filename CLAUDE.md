# Montager - repo notes

- Single-file app: `montage.py` (GUI + engine). Data lives in `montage_data\` next to it.
- **Every new version must add an entry to `CHANGELOG.md`** (newest first, at the top) in the same commit that bumps `APP_VERSION`. If you cannot tell what a version contained, write "Details not recorded" instead of guessing.
- Frozen unless a task says otherwise: detection, planner and render logic. GUI / config / test changes must not touch them.
- Tests: `python montage.py smoketest` (full, includes a real render; Windows). Fast GUI/audio-mode checks without rendering: `python test_v557.py` (needs a display; on Linux use `xvfb-run -a python3 test_v557.py`).
