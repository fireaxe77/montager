"""V6.9.6 part C tests: repository declutter round 2 (moved tests, root resolver, docs, .gitignore, history). Fast: no full test run except test_v69 (part B)."""
import os
import py_compile
import re
import subprocess
import _run as R                                                                              # noqa: E402  (V6.9.7 shared subprocess helper)
import sys
import tempfile
from pathlib import Path

from v696_common import M, check, section, ROOT, BASE_REF                                       # noqa: F401

MOVED = ["test_v67.py", "test_v672.py", "test_v674.py", "test_v676.py", "test_v68.py", "test_v681.py", "test_v682.py", "test_v69.py", "test_v695.py"]
RESOLVE = r'''
import sys, json, importlib.util, os
from pathlib import Path
out = {}
for f in sys.argv[1:]:
    f = Path(f).resolve()
    sys.path.insert(0, str(f.parent))
    spec = importlib.util.spec_from_file_location("t_" + f.stem, str(f))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    out[f.name] = {k: str(getattr(m, k)) for k in ("HERE", "REAL_DATA", "FIX") if hasattr(m, k)}
    out[f.name]["montage"] = str(Path(m.M.__file__).resolve())
    sys.path.pop(0)
print(json.dumps(out, sort_keys=True))
'''


def git(*a):
    return R.run(["git", *a], cwd=str(ROOT), capture_output=True, text=True).stdout


def part_layout(tmp):
    with section("9) repository declutter round 2"):
        import json
        tracked = [x for x in git("ls-files").split("\n") if x.endswith(".py")] + [x for x in git("ls-files", "-o", "--exclude-standard").split("\n") if x.endswith(".py")]
        bad = []
        for f in sorted(set(tracked)):
            try:
                py_compile.compile(str(ROOT / f), cfile=str(Path(tmp) / "pyc" / (f.replace("/", "_") + "c")), doraise=True)
            except py_compile.PyCompileError as ex:
                bad.append(f"{f}: {ex}")
        check(not bad and len(tracked) > 20, f"py_compile passes for every .py ({len(set(tracked))} files) {bad[:2]}")
        env = dict(os.environ, MONTAGER_DATA=str(Path(tmp) / "cfgdata"))
        r = R.run([sys.executable, "-c", "import montage; print(montage.APP_VERSION)"], cwd=str(ROOT), text=True, env=env)
        mv_ = re.match(r"V(\d+)\.(\d+)\.(\d+)", r.stdout.strip())
        check(r.returncode == 0 and mv_ and tuple(map(int, mv_.groups())) >= (6, 9, 6), f"import montage from the root works ({r.stdout.strip()}; V6.9.6 or newer)")
        r = R.run([sys.executable, "montage.py", "cfgdump"], cwd=str(ROOT), text=True, env=env, timeout=120)
        ok_, why_ = R.require(r, "python montage.py cfgdump")
        check(ok_ and r.stdout.strip(), f"python montage.py cfgdump starts from the root and prints the config ({len(r.stdout)} chars) {why_}")
        left = sorted(p.name for p in ROOT.glob("test_v*.py"))
        here = sorted(p.name for p in (ROOT / "tests").glob("test_v*.py"))
        check(not left and all(n in here for n in MOVED), f"no test left at the root; the {len(MOVED)} moved tests are in tests/ (root: {left})")
        check((ROOT / "tests" / "_root.py").exists() and 'find_root' in (ROOT / "tests" / "_root.py").read_text(), "tests/_root.py with find_root()")
        # root resolution: the same absolute repo root / montage_data / fixtures path from the root and from inside tests/ (and the same as before the move: the repo root)
        res = {}
        for label, cwd in (("root", ROOT), ("tests", ROOT / "tests")):
            files = [str((ROOT / "tests" / n)) for n in MOVED]
            r = R.run([sys.executable, "-c", RESOLVE] + files, cwd=str(cwd), capture_output=True, text=True, env=dict(env, PYTHONPATH=""), timeout=300)
            res[label] = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 and r.stdout.strip() else {"error": r.stderr[-300:]}
        want = {n: {"HERE": str(ROOT), "montage": str(ROOT / "montage.py")} for n in MOVED}
        for n in ("test_v682.py",):
            want[n].update(REAL_DATA=str(ROOT / "montage_data"), FIX=str(ROOT / "tests" / "fixtures" / "cs2_rows"))
        for n in ("test_v69.py", "test_v695.py"):
            want[n].update(REAL_DATA=str(ROOT / "montage_data"))
        ok = res["root"] == res["tests"] and all(all(res["root"].get(n, {}).get(k) == v for k, v in w.items()) for n, w in want.items())
        check(ok, f"every moved test resolves the same absolute repo root, montage_data and fixtures path from the root and from tests/ (as before the move: {len(MOVED)} tests; {res['root'].get('error', '')})")
        # the moved test runs from inside tests/ too (the fast pairing test)
        r = R.run([sys.executable, "test_v69.py"], cwd=str(ROOT / "tests"), capture_output=True, text=True, encoding="utf-8", errors="replace")
        check(r.returncode == 0 and r.stdout.strip().endswith("ALL OK"), "python test_v69.py from inside tests/ ends with ALL OK")
        # git: nothing deleted except by git mv, history intact
        st = git("diff", "-M", "--name-status", BASE_REF).split("\n") + ["A\t" + x for x in git("ls-files", "-o", "--exclude-standard").split("\n") if x]
        deleted = [x for x in st if x.startswith("D")]
        renames = [x for x in st if x.startswith("R")]
        check(not deleted and len(renames) >= len(MOVED), f"no tracked file deleted; {len(renames)} renames (git mv), deleted: {deleted}")
        mb = git("merge-base", BASE_REF, "HEAD").strip()
        n_new = len([x for x in git("rev-list", f"{BASE_REF}..HEAD").split() if x])
        anc = R.run(["git", "merge-base", "--is-ancestor", BASE_REF, "HEAD"], cwd=str(ROOT)).returncode == 0
        # V6.9.7: main has merged v6.9.5.x / v6.9.6 since BASE_REF, so the merge-free window starts at the V6.9.6 merge into main
        V696_MAIN = "76b2859"
        anc2 = R.run(["git", "merge-base", "--is-ancestor", V696_MAIN, "HEAD"], cwd=str(ROOT)).returncode == 0
        merges = [x for x in git("rev-list", "--merges", f"{V696_MAIN}..HEAD").split() if x] if anc2 else []
        n_new = len([x for x in git("rev-list", f"{V696_MAIN}..HEAD").split() if x]) if anc2 else n_new
        check(anc and mb.startswith(git("rev-parse", BASE_REF).strip()[:7]) and (not anc2 or (n_new <= 4 and not merges)),
              f"history intact: {BASE_REF} is an ancestor, {n_new} commit(s) since the V6.9.6 merge (max 4), no merge commits, no rewrite")
        gi = (ROOT / ".gitignore").read_text()
        check(all(x in gi for x in ("fpscontent.txt", "grouporder.txt", "fpscheck.txt", "pairscan_cs2.txt", "compare_out/")) and not git("ls-files", "fpscontent.txt", "grouporder.txt", "fpscheck.txt", "pairscan_cs2.txt").strip(),
              ".gitignore lists the generated files and none of them is tracked")
        br = (ROOT / "docs" / "BRANCHES.md").read_text(encoding="utf-8")
        remote = [x.strip()[len("origin/"):] for x in git("branch", "-r").split("\n") if x.strip() and "->" not in x and x.strip() not in ("origin/v6.9.6",)
                  and (R.run(["git", "merge-base", "--is-ancestor", "76b2859", x.strip()], cwd=str(ROOT)).returncode != 0 or x.strip() == "origin/main")]   # V6.9.7: branches made after the docs (they contain the V6.9.6 merge) are not listed
        miss = [b for b in remote if f"`{b}`" not in br]
        check(not miss and "git push origin --delete" in br and "Nothing was deleted" in br, f"docs/BRANCHES.md lists all {len(remote)} remote branches with delete commands for the merged ones, nothing deleted {miss[:3]}")
        cl = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        check("CS2 detection engine frozen (V6.9); only touch it on explicit request." in cl and "tests/_root.py" in cl, "CLAUDE.md keeps the CS2 frozen line and documents the final layout")
        lay = (ROOT / "docs" / "REPO_LAYOUT.md").read_text(encoding="utf-8")
        check("tests\\test_v696.py" in lay and "from inside `tests/`" in lay and (ROOT / "docs" / "REPO_AUDIT.md").read_text(encoding="utf-8").count("Round 2 (V6.9.6)") == 1 and
              "fixtures/" in (ROOT / "docs" / "REPO_AUDIT.md").read_text(encoding="utf-8").split("Round 2 (V6.9.6)")[1], "docs/REPO_LAYOUT.md and the round-2 audit are updated (fixtures decision stated)")


def run(tmp):
    part_layout(tmp)
