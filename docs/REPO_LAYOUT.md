# Repository layout (V6.9.3)

```
montage.py                 the app (GUI + engine) - run everything from the repo root
CHANGELOG.md  README.md  CLAUDE.md  .gitignore
Montager.vbs  Montage.vbs  Create_Desktop_Shortcut.vbs  Set_Shortcut_AppId.ps1     launchers / shortcut helpers (paths are relative to the root)
montage.ico  montage.png   window / taskbar icon (opened next to montage.py)
fixtures/                  Valorant killfeed PNGs used by `montage.py smoketest`
montage_data/              config, caches, logs, plans (local, untracked)
tests/                     V6.9.3 test + the older tests that only need `import montage`; tests/fixtures/cs2_rows = real CS2 rows
docs/                      REPO_AUDIT.md, REPO_LAYOUT.md, CHECKLIST_V5_1.md
test_v67*.py test_v68*.py test_v69.py   older tests that treat their own folder as the repo root: kept at the root (see docs/REPO_AUDIT.md)
```

## Run the app (unchanged)
`python montage.py` (GUI), `python montage.py fpscheck --all`, `python montage.py pairscan cs2`, `python montage.py smoketest` ... - always from the repo root.

## Run the tests
| Test | Command from the repo root |
|---|---|
| V6.9.3 (this version) | `python tests\test_v693.py` |
| V6.5 song matching | `python tests\test_v65.py` |
| V6.5.2 Used cell | `xvfb-run -a -s "-screen 0 1920x1200x24" python3 tests/test_v652.py` (Windows: `python tests\test_v652.py`) |
| other moved tests | `python tests\test_v557.py`, `test_v558.py`, `test_v60.py`, `test_v61.py`, `test_v612.py`, `test_v615.py`, `test_v651.py` |
| older tests kept at the root | `python test_v69.py`, `python test_v682.py`, ... (unchanged) |

CLAUDE.md test policy: run only the new version's test file plus the Valorant guard; older tests are frozen.
