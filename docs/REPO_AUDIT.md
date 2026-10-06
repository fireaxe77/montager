# Repository audit (V6.9.3, before the declutter)

Every file and folder at the repository root, what it is, who references it, and what was done. Nothing was deleted; nothing was moved that the app
opens by a relative path. History is intact (git mv only, no rebase / force-push / filter-branch, tags untouched).

| Root item | What it is | Referenced by | Decision |
|---|---|---|---|
| `montage.py` | the whole app (GUI + engine) | every test, the launchers, README, CLAUDE.md | stays (entry point; `HERE`-relative paths for `montage_data`, `fixtures`, icons) |
| `CHANGELOG.md` | version history | `montage.py` (Settings > Changelog, `CHANGELOG_PATH`), CLAUDE.md rule, `test_v557` | stays |
| `README.md` | short intro | - | stays (one test command updated to the new path) |
| `CLAUDE.md` | project rules for Claude Code | read automatically from the root | stays (layout + test policy added) |
| `.gitignore` | ignore list | git | stays (generated diagnostics added) |
| `montage.ico`, `montage.png` | window / taskbar icon | `montage.py` (`HERE / "montage.ico"`, `HERE / "montage.png"`), `Create_Desktop_Shortcut.vbs` | stay (opened by relative path) |
| `fixtures/` (3 Valorant PNG) | real killfeed rows | `montage.py` (`FIXTURES = <montage.py folder>/fixtures`, used by `smoketest`) | stays (opened by relative path) |
| `Montager.vbs` | launcher (pythonw, no console) | `Create_Desktop_Shortcut.vbs`, `Montage.vbs`, the user's desktop shortcuts | stays (shortcuts point at the root path) |
| `Montage.vbs` | old launcher name (V5.5 shortcuts) | forwards to `Montager.vbs`; old user shortcuts | stays (user shortcuts) |
| `Create_Desktop_Shortcut.vbs` | creates the Desktop / Start menu shortcut | README | stays (README documents the root path) |
| `Set_Shortcut_AppId.ps1` | sets the taskbar AppUserModelID of the shortcut | `Create_Desktop_Shortcut.vbs` (same folder) | stays (called by relative path) |
| `CHECKLIST_V5_1.md` | V5.1 manual checklist | nobody | moved to `docs/` |
| `tests/` | `tests/fixtures/cs2_rows` (real CS2 killfeed screenshots) | `test_v682.py`, CHANGELOG | stays; now also holds the moved tests |
| `test_v557.py`, `test_v558.py`, `test_v60.py`, `test_v61.py`, `test_v612.py`, `test_v615.py`, `test_v65.py`, `test_v651.py`, `test_v652.py` | older tests; they only need `import montage` | CLAUDE.md, README, CHANGELOG | moved to `tests/` with ONE added line (repo-root path bootstrap) |
| `test_v693.py` | this version's test (written for the new layout) | CHANGELOG | in `tests/` |
| `test_v67.py`, `test_v672.py`, `test_v674.py`, `test_v676.py`, `test_v68.py`, `test_v681.py`, `test_v682.py`, `test_v69.py` | older tests that take `HERE = <test folder>` as the repo root (`HERE / "montage_data"`, `git show` / sibling tests run with `cwd=HERE`, `M.HERE = ...`) | each other (`test_v676` runs `test_v674`, `test_v68` runs siblings) | **kept at the root - risky**: moving them would silently skip their real-`montage_data` checks (they would look in `tests/montage_data`) or break sibling lookups, and the only allowed edit to a moved test is a one-line bootstrap |
| `__pycache__/`, `montage_data/` | local, untracked | `.gitignore` | untouched |

## Generated / local data
`rowdebug_images/`, `regiontest_images/`, `rowdebug_cs2.txt`, `regiontest_cs2.txt`, `pairscan_cs2.txt`, `fpscheck.txt`, `perflog*.txt`, `*.part.mp4`, `*.interp/` are now in `.gitignore`.
None of them was tracked (checked with `git ls-files`), so no `git rm --cached` was needed; the files on the PC are untouched.

## kept - unclear
- None unclear. The "kept at the root - risky" tests above are the only deliberate leftovers; a later version can move them together once each gets a repo-root constant (that needs edits to frozen tests, which this version did not make).

## Deleted
- No tracked file was deleted.
