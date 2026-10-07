"""Repo-root lookup for the tests (V6.9.6): find_root() walks up from a file until the folder that contains montage.py. The environment variable
MONTAGER_ROOT overrides it. A test that treats `find_root(__file__)` as the repo root works from the root and from inside tests/."""
import os
from pathlib import Path


def find_root(start=None):
    env = os.environ.get("MONTAGER_ROOT")
    if env:
        return Path(env).resolve()
    p = Path(start or __file__).resolve()
    for d in [p] + list(p.parents):
        if d.is_dir() and (d / "montage.py").exists():
            return d
    raise RuntimeError(f"repo root (a folder containing montage.py) not found above {p}")
