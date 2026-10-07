# Repository audit (V6.9.3 declutter; round 2 in V6.9.6 at the end)

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
| `test_v67.py`, `test_v672.py`, `test_v674.py`, `test_v676.py`, `test_v68.py`, `test_v681.py`, `test_v682.py`, `test_v69.py` | older tests that take `HERE = <test folder>` as the repo root (`HERE / "montage_data"`, `git show` / sibling tests run with `cwd=HERE`, `M.HERE = ...`) | each other (`test_v676` runs `test_v674`, `test_v68` runs siblings) | **kept at the root - risky (superseded: moved in V6.9.6, see Round 2 below)**: moving them would silently skip their real-`montage_data` checks (they would look in `tests/montage_data`) or break sibling lookups, and the only allowed edit to a moved test is a one-line bootstrap |
| `__pycache__/`, `montage_data/` | local, untracked | `.gitignore` | untouched |

## Generated / local data
`rowdebug_images/`, `regiontest_images/`, `rowdebug_cs2.txt`, `regiontest_cs2.txt`, `pairscan_cs2.txt`, `fpscheck.txt`, `perflog*.txt`, `*.part.mp4`, `*.interp/` are now in `.gitignore`.
None of them was tracked (checked with `git ls-files`), so no `git rm --cached` was needed; the files on the PC are untouched.

## kept - unclear
- None unclear. The "kept at the root - risky" tests above are the only deliberate leftovers; a later version can move them together once each gets a repo-root constant (that needs edits to frozen tests, which this version did not make).

## Deleted
- No tracked file was deleted.


---

# Round 2 (V6.9.6)

## Cause of the leftovers
The tests left at the root in V6.9.3 (`test_v67.py`, `test_v672.py`, `test_v674.py`, `test_v676.py`, `test_v68.py`, `test_v681.py`, `test_v682.py`, `test_v69.py`) took `HERE = Path(__file__).resolve().parent` as the repo root
(`HERE / "montage_data"`, `HERE / "tests" / "fixtures"`, `git show` with `cwd=HERE`, sibling runs `HERE / "test_v67.py"`). `test_v695.py` (V6.9.5) was written at the root the same way.

## What was done
| Item | Decision |
|---|---|
| `tests/_root.py` | new: `find_root(start)` walks up from the file to the folder that contains `montage.py`; env `MONTAGER_ROOT` overrides |
| the 9 tests above (+ `test_v695.py`) | `git mv` into `tests/`; the ONE edit in each: `HERE = __import__("_root").find_root(__file__)` instead of `Path(__file__).resolve().parent`. Three tests start a sibling test by file name (`test_v672` -> `test_v67`, `test_v676` -> `test_v674`, `test_v68` -> `test_v676` / `test_v557` / `test_v558`): that path got `"tests"` inserted (the same root lookup, one word) |
| root resolution before / after | recorded before the move (the repo root, `montage_data`, `tests/fixtures/cs2_rows` each test resolves) and asserted identical after the move (`tests/test_v696.py`, section 9): the real-`montage_data` checks of those tests keep running against the same absolute folder, no test was run in full |
| `fixtures/` (3 Valorant PNG) | **kept at the root**: `montage.py` opens it as `Path(__file__).resolve().parent / "fixtures"` (`smoketest`); moving it needs a code edit in `montage.py`, which is outside this round's allowed areas (file moves and docs). A later version can move it together with that one constant |
| `songmap_compare.py`, `songmap_v2/` | kept: they are imported by `montage.py` by module name / package name (code, not tests) |
| `.gitignore` | added `fpscontent.txt`, `grouporder.txt`, `interpbench_*/` next to the existing `fpscheck.txt`, `pairscan_cs2.txt`, `compare_out/`, `*.part.mp4`, `*.interp/`, `perflog*`; none of them was tracked (`git ls-files` checked) so no `git rm --cached` was needed |
| `docs/BRANCHES.md` | new: every remote branch with its last commit date, merged-into-main flag, ahead / behind counts and ready-to-copy delete commands for the merged ones. No branch was deleted, tags untouched, no history rewritten |
| `docs/REPO_LAYOUT.md`, `CLAUDE.md` | updated with the final layout (all tests in `tests/`, run from the root or from inside `tests/`) |

## Kept at the root (final)
`montage.py`, `songmap_compare.py`, `songmap_v2/`, `Montager.vbs`, `Montage.vbs`, `Create_Desktop_Shortcut.vbs`, `Set_Shortcut_AppId.ps1`, `montage.ico`, `montage.png`, `fixtures/`, `README.md`, `CHANGELOG.md`, `CLAUDE.md`, `.gitignore`.
(There is no requirements file in the repository.)

## Ignored on purpose
`__pycache__/`, `montage_data/` (local), the generated diagnostics listed in `.gitignore`; the old per-version branches (listed in `docs/BRANCHES.md`, not deleted).

## Deleted
- No tracked file was deleted; the moved tests keep their history (`git mv`).
