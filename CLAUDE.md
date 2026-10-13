# Montager - repo notes

- Single-file app: `montage.py` (GUI + engine). Data lives in `montage_data\` next to it.
- **Every version that is merged to main (or tagged) must add an entry to `CHANGELOG.md`** (newest first, at the top), with the code change; experiment branches that are not merged and do not bump `APP_VERSION` get a short entry marked "NOT merged". If you cannot tell what a version contained, write "Details not recorded" instead of guessing.
- Frozen unless a task says otherwise: detection, planner and render logic. GUI / config / test changes must not touch them.
- Tests: `python montage.py smoketest` (full, includes a real render; Windows). Fast GUI/audio-mode checks without rendering: `python tests/test_v557.py` (needs a display; on Linux use `xvfb-run -a python3 tests/test_v557.py`).
- V5.58 checks (live theme, tab switching, settings audit; no render): `xvfb-run -a -s "-screen 0 1920x1200x24" python3 tests/test_v558.py` (optional args: live tabs audit).
- Run only the new version's test file plus the Valorant guard; older tests are frozen and run only if the user asks.
- CS2 detection engine frozen (V6.9); only touch it on explicit request.
- Layout (V6.9.6, details in `docs/REPO_LAYOUT.md`, audit in `docs/REPO_AUDIT.md`, branch list in `docs/BRANCHES.md`): `montage.py`, `songmap_compare.py`, `songmap_v2/`, launchers, icons, `fixtures/` (used by `montage.py smoketest` by relative path), CHANGELOG / README / CLAUDE.md stay at the root and everything runs from the root. ALL tests live in `tests/` and run as `python tests\test_vXX.py` from the repo root or from inside `tests/` (`tests/_root.py` `find_root()` finds the repo root; env `MONTAGER_ROOT` overrides). Docs in `docs/`. Generated diagnostics (`rowdebug_*`, `regiontest_*`, `pairscan_cs2.txt`, `fpscheck.txt`, `fpscontent.txt`, `grouporder.txt`, `compare_out/`, `perflog*`) are git-ignored.
- Test policy: only the new version's test file (+ the Valorant / CS2 guards); older tests are frozen and run only on request; the only allowed edit to a moved test is a one-line repo-root bootstrap.
- SONGMAPV1 (`build_song_map`, `analyse_song`, `song_cache.json`) is frozen; SONGMAPV2 lives only in `songmap_v2/` and is reached only through `get_songmap()` (V6.9.5). Run `python test_v695.py` for it.
- V6.9.7: `tests/test_v697.py` (cloud: `xvfb-run -a python3 tests/test_v697.py`, needs python with tkinter) is the new version's test file; every test that starts a subprocess uses `tests/_run.py` (UTF-8 decoding, child PYTHONIOENCODING/PYTHONUTF8). Kill ledger + proof-based clip merging live in `build_events` / `KillLedger` (`python montage.py ledger`, `timeanchor`); the per-clip utility override is `clip_overrides.json` (`python montage.py utilclip`), Valorant only. Detection stays frozen.
- V7.6.1: `tests/test_v761.py` is the new version's test file (`V761_PARTS=0,1,2,3,4,5,6,7,9,g` picks parts, `V761_FAST=1` skips the render). Timing tools: `tests/marker761.py` (marker clips), `tests/audit761.py` / `ssim761b.py` (real renders). One song + style pick per job (`make_plan(pin=...)`, `run_job(pin=...)`); take feasibility has a relaxation ladder (`RX_LADDER`), drops are anchored by levers a c d b; slow-mo is an eased speed curve; soft cuts are decided by `soft_cut_ok`.
- docs/CHANGELOG_SIMPLE.md is the readable history shown in Settings. Each new version gets ONE headline (3 to 8 words) and 1 to 4 plain user-facing points; no function names, tests, timings or refactors. Technical details only in CHANGELOG.md. No KNOWN ISSUE or on-hold lists; one entry per version, newest first. Do not read either file unless asked.

## Release routine
- Work on a branch named `work-vXYZ` (never `vX.Y.Z`: it collides with the tag name on Windows); merge with `refs/heads/work-vXYZ`.
- Commit and push everything except videos, backups and `montage_data`. Title-bar version (`APP_VERSION`) = the version.
- `docs/CHANGELOG_SIMPLE.md`: one entry (see the rule above); `CHANGELOG.md`: short technical entry.
- Run only that version's test file plus the guards (50+50 generated clips, 7 real Valorant clips, the 4K).
- Tag the previous main `<prev>-good`, normal merge commit (`git merge --no-ff refs/heads/work-vXYZ`), tag the new version, push main and tags, remove extra worktrees, leave main clean.
- End with the line "done, main = <version>, safe to pull".
- V7.7.0: `tests/test_v770.py` is the new version's test file (`V770_PARTS=0,1,3,4,g`; point `V7_DATA_SRC`/`MONTAGER_DATA` at a COPY of montage_data). Tail repair (`repair_tails`), audible-onset drop anchors (`refine_drop_anchors`), music-over-gameplay option (default off, `musicscan`).
