# Repository layout (V6.9.6)

```
montage.py                 the app (GUI + engine) - run everything from the repo root
songmap_compare.py         `montage.py songmapcompare` (imported by montage.py by name, so it sits next to it)
songmap_v2/                the SONGMAPV2 package (reached only through get_songmap())
CHANGELOG.md  README.md  CLAUDE.md  .gitignore
Montager.vbs  Montage.vbs  Create_Desktop_Shortcut.vbs  Set_Shortcut_AppId.ps1     launchers / shortcut helpers (paths are relative to the root)
montage.ico  montage.png   window / taskbar icon (opened next to montage.py)
fixtures/                  Valorant killfeed PNGs used by `montage.py smoketest` (FIXTURES = <montage.py folder>/fixtures)
montage_data/              config, caches, logs, plans (local, untracked)
tests/                     EVERY test (test_v557 ... test_v696) + tests/_root.py + tests/fixtures/cs2_rows (real CS2 rows) + the V6.9.6 helper modules
docs/                      REPO_AUDIT.md, REPO_LAYOUT.md, BRANCHES.md, CHECKLIST_V5_1.md
```

## Run the app (unchanged)
`python montage.py` (GUI), `python montage.py fpscontent <montage.mp4>`, `python montage.py interpbench`, `python montage.py grouporder cs2 "<clip>"`, `python montage.py pairscan cs2`,
`python montage.py smoketest` ... - always from the repo root.

## Run the tests
Every test runs as `python tests\test_vXX.py` from the repo root AND from inside `tests/` (`cd tests` then `python test_vXX.py`): the tests that used to treat their own folder as the repo root
now ask `tests/_root.py` (`find_root(__file__)`: the folder above that contains `montage.py`; the environment variable `MONTAGER_ROOT` overrides it).

| Test | Command (from the repo root) |
|---|---|
| V6.9.6 (this version) | `python tests\test_v696.py` |
| V6.9.5 SONGMAPV2 | `python tests\test_v695.py` |
| V6.9 pairing | `python tests\test_v69.py` |
| V6.9.3 interpolation | `python tests\test_v693.py` |
| V6.5 song matching | `python tests\test_v65.py` |
| V6.5.2 Used cell | `xvfb-run -a -s "-screen 0 1920x1200x24" python3 tests/test_v652.py` (Windows: `python tests\test_v652.py`) |
| all other tests | `python tests\test_v557.py`, `test_v558.py`, `test_v60.py`, `test_v61.py`, `test_v612.py`, `test_v615.py`, `test_v651.py`, `test_v67.py`, `test_v672.py`, `test_v674.py`, `test_v676.py`, `test_v68.py`, `test_v681.py`, `test_v682.py` |

CLAUDE.md test policy: run only the new version's test file plus the Valorant / CS2 guards; older tests are frozen and run only on request.
