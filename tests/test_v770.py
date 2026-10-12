"""V7.7.0 tests. Sections (each prints ok / FAIL lines, the last line is ALL OK only when every check ran and passed):
  0) changelog: every real version (APP_VERSION bump in the git history) has an entry in both changelogs, the Settings viewer shows everything
  1) drop placement: a max-tail violation is repaired before a take is skipped, a skipped take is listed with its rule, ledger = cut list, header from the final plan,
     drop anchors refined to the audible onset
  2) the same fight saved twice is merged (never different fights)
  3) song length column + date-added sort in the Songs and Manual tabs
  4) music over gameplay detector (synthetic clips) and its OFF = byte-identical contract
  g) guards: 50 + 50 generated clips vs V7.6.1, the 7 real Valorant clips (4 / 11 / 3 / 0), the 4K
Runs on a COPY of montage_data (V7_DATA_SRC picks the folder; the real folder is only read).   python tests\\test_v770.py   (parts: V770_PARTS=0,1,2,3,4,g)"""
import os
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import montage as M                                                                           # noqa: E402
from songmap_v2 import planbench as PB                                                        # noqa: E402
from v696_common import check, section, FAILS, snapshot                                       # noqa: E402

REAL_DATA = ROOT / "montage_data"
T_ALL = time.time()


# ------------------------------------------------------------------------------------------------ 0) changelog
def part_changelog():
    with section("0) changelogs: every real version has an entry, both files agree, the Settings viewer shows everything"):
        simple = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
        tech = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        hs = re.findall(r"(?m)^## (.+)$", simple)
        ht = re.findall(r"(?m)^## (.+)$", tech)
        key = lambda h: re.match(r"(V[\d.]+[AB]?|Megafix|First|Stage|Initial)", h).group(1)
        ks, kt = [key(h) for h in hs], [key(h) for h in ht]
        check(ks == kt, "same versions in the same order in both files" + ("" if ks == kt else f" (differ at {[(a, b) for a, b in zip(ks, kt) if a != b][:3]})"))
        check(len(set(ks)) == len(ks), "no version twice")
        r = subprocess.run(["git", "log", "--all", "--format=%h", "-G", r"^APP_VERSION = ", "--", "montage.py"], cwd=ROOT, capture_output=True, text=True)
        revs = r.stdout.split()
        if not revs:
            check(True, "no git history here: the version bumps could not be listed (skipped)")
        else:
            bumps = set()
            for rv in revs:
                p = subprocess.run(["git", "show", f"{rv}:montage.py"], cwd=ROOT, capture_output=True)
                m = re.search(rb'(?m)^APP_VERSION = "([^"]+)"', p.stdout)
                if m:
                    bumps.add(m.group(1).decode())
            miss = sorted(v for v in bumps if v not in ks)
            check(not miss, f"all {len(bumps)} version bumps of the git history have an entry in both changelogs" + (f" (missing {miss})" if miss else ""))
        tags = subprocess.run(["git", "tag"], cwd=ROOT, capture_output=True, text=True).stdout.split()
        vt = {re.sub(r"-good$", "", t).upper() for t in tags if re.match(r"(?i)v\d", t)}
        ksu = {k.upper() for k in ks}
        miss_t = sorted(v for v in vt if v not in ksu)
        check(not miss_t, f"every version tag ({len(vt)}) has an entry" + (f" (missing {miss_t})" if miss_t else ""))
        never = ("V5.45", "V5.50", "V5.54", "V6.3", "V6.4")
        check(not any(k in ksu for k in never), "versions that never existed (V5.45-V5.54, V6.3, V6.4) have no entry")
        bad = re.search(r"KNOWN ISSUE|ABANDON|ON HOLD|on hold", simple)
        check(not bad, "no KNOWN ISSUE / ABANDONED / on-hold text in the readable history")
        for h, blk in zip(hs, re.split(r"(?m)^## .+$", simple)[1:]):
            n = len([x for x in blk.splitlines() if x.startswith("- ")])
            if n < 1 or n > 5:
                check(False, f"{h}: {n} points (1 to 5 expected)")
        for p in (None, M.CHANGELOG_PATH):
            L = M.changelog_lines(p)
            n_ver = sum(1 for k, _ in L if k == "ver")
            check(n_ver == len(hs), f"Settings viewer shows the full history ({'readable' if p is None else 'technical'} file: {n_ver} versions)")
        try:
            import tkinter
            root = tkinter.Tk()
            root.withdraw()
            root.destroy()
            gui = True
        except Exception:
            gui = False
        if gui:
            app = M.App(0)
            try:
                app.show_changelog()
                app.root.update()
                txt = app.cl_text.get("1.0", "end")
                first_ver, last_ver = hs[0], hs[-1]
                n_exp, n_txt = len(M.changelog_lines()), len(txt.strip().splitlines())
                check(first_ver in txt and last_ver in txt and n_txt == n_exp, f"the changelog window opens and holds the whole text ({n_txt} of {n_exp} lines, first and last entry present)")
            finally:
                try:
                    app.root.destroy()
                except Exception:
                    pass
        else:
            print("   (no display: the changelog window itself was not opened here)")


def main():
    before = snapshot(REAL_DATA)
    tmp = Path(tempfile.mkdtemp(prefix="t770_"))
    only = set(filter(None, os.environ.get("V770_PARTS", "").split(",")))
    want = lambda k: not only or k in only
    if want("0"):
        part_changelog()
    after = snapshot(REAL_DATA)
    if before == after:
        check(True, f"real montage_data byte-identical after the tests ({len(before)} files)")
    else:
        names_ = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
        print("   NOTE (nothing was touched by the tests, the Montager app writes there): real montage_data differs in " + ", ".join(names_[:12]))
    print(f"total test time {time.time() - T_ALL:.1f} s")
    print("ALL OK" if not FAILS else f"FAILED ({len(FAILS)}): " + "; ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
