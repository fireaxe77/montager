"""V8.8.7 tests (fast; no render).
  0) title-bar version V8.8.7; V8.8.7 on top of V8.8.6 in both changelogs
  1) Valorant rows with an unreadable name: a new row in a slot whose old row had gone (the feed empty for seconds) is a new row (_row_match), an unreadable row is merged with a
     later named row only when that row starts within EMPTY_NAME_GAP_S of its last sighting, and one unreadable row seen at two heights / re-read in missed frames is one row
     (merge_variants); CS2 untouched. Real data (when the scan is in montage_data): 'Valorant 2025.10.10 - 23.10.09.04' = kills at ~5.9, ~13.3, ~14.3 s; the Valorant library
     changes in exactly that clip and 'Valorant 2024.08.16 - 22.08.02.08' (a phantom 8.7 s kill removed)
  2) the move icon: moved_root (never inside a scanned clip folder, never scanned), move_clip_file (per game folder, never overwrites), the clip list's move column
  3) everything V8.8.6 checked (tests/test_v886.py parts 1 - 6)
python tests\\test_v887.py   (parts: V887_PARTS=0,1,2,3)"""
import os
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
_src = (HERE / "test_v886.py").read_text(encoding="utf-8")
_ns = {"__file__": str(HERE / "test_v886.py"), "__name__": "test_v886_parts"}
exec(compile(_src[:_src.rindex('if __name__ == "__main__":')], str(HERE / "test_v886.py"), "exec"), _ns)
V6 = types.SimpleNamespace(**_ns)
T = V6.T
M = T.M
ROOT = T.ROOT
check = T.check
PARTS = [x for x in os.environ.get("V887_PARTS", "0,1,2,3").split(",") if x]


def part0():
    print("0) version, changelogs")
    check("APP_VERSION is V8.8.7", M.APP_VERSION == "V8.8.7")
    cl = [l for l in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines() if l.startswith("## V")]
    check("CHANGELOG.md: V8.8.7 above V8.8.6", cl[0].startswith("## V8.8.7") and cl[1].startswith("## V8.8.6"), str(cl[:2]))
    body = (ROOT / "docs" / "CHANGELOG_SIMPLE.md").read_text(encoding="utf-8")
    sm = [l for l in body.splitlines() if l.startswith("## V")]
    check("simple changelog: V8.8.7 above V8.8.6", sm[0].startswith("## V8.8.7") and sm[1].startswith("## V8.8.6"), str(sm[:2]))
    seg = body[body.index("## V8.8.7"):body.index("## V8.8.6")]
    pts = [l for l in seg.splitlines() if l.startswith("- ")]
    head = seg.splitlines()[0].split(":", 1)[-1].strip()
    check(f"simple entry: a 3-8 word headline ('{head}'), 1-4 points", 3 <= len(head.split()) <= 8 and 1 <= len(pts) <= 4)
    check("simple entry is plain", not any(w in seg.lower() for w in ("test", "known issue", "on hold", "def ", "ffmpeg", "cache", "()", "planner", "regression")))


def _tr(first, last, k, v, y, frames, ks=1.0, vs=0.0):
    return {"first": first, "last": last, "seen": first, "k": k, "v": v, "ktext": k, "vtext": v, "ks": ks, "vs": vs, "y": y, "frames": set(frames), "hits": len(frames),
            "votes": [], "hs": False, "cjk": False, "split": "icon", "gun": True, "iw": 0}


def part1():
    print("1) Valorant rows with an unreadable name")
    F = M.FPS
    t = _tr(89, 161, "fireaxe", "", 24, [89, 161])
    r = {"ktext": "fireaxe", "vtext": "Veto", "y": 24, "th": 20, "icon": None, "appear_max": 0, "split": "icon", "gun": True}
    check("a named row in the slot of an unreadable row seen 0.5 s ago is still that row", M._row_match(t, r, 168, 168) >= 80)
    check("... but not once the old row had been gone for 2.7 s (the feed was empty)", M._row_match(t, r, 200, 201) == 0.0)
    check("without the frame number the old rule is unchanged (other callers)", M._row_match(t, r, 200) >= 80)
    a = _tr(89, 161, "fireaxe", "", 24, [89, 161])
    b = _tr(201, 227, "fireaxe", "veto", 24, [201, 227], vs=0.18)
    out_ = M.merge_variants([dict(a), dict(b)], "valorant")
    check("an unreadable row and a named row starting 2.7 s after it ended stay two kills", len(out_) == 2)
    c = _tr(165, 180, "fireaxe", "veto", 24, [165, 180], vs=0.18)
    check("... a named row right after it (0.3 s) is the same row read at last", len(M.merge_variants([dict(a), dict(c)], "valorant")) == 1)
    d = _tr(134, 149, "fireaxe", "", 24, [137, 149])
    check("an unreadable row re-read at its own height in frames the track missed is one row", len(M.merge_variants([dict(a), dict(d)], "valorant")) == 1)
    e = _tr(125, 140, "fireaxe", "", 5, [125, 140])
    a2 = _tr(89, 121, "fireaxe", "", 24, [89, 121])
    check("an unreadable row that moved up when the row above expired (0.3 s later) is one row", len(M.merge_variants([dict(a2), dict(e)], "valorant")) == 1)
    f2 = _tr(140, 160, "fireaxe", "", 60, [140, 160])
    check("two unreadable rows on screen at different heights at the same time stay two kills", len(M.merge_variants([dict(a), dict(f2)], "valorant")) == 2)
    check("CS2 keeps its rule (4.5 s, no empty-row merge)", len(M.merge_variants([dict(a), dict(b)], "cs2")) == 1)
    # real data
    real = ROOT / "montage_data"
    e_, old = None, None
    if (real / "config.json").exists():
        old = M.use_data_dir(real)                          # read only: the clip record and its stored scan
    try:
        cfg = M.load_config()
        clips_ = M.load_json(M.CLIPS_CACHE, {})
        rec = next((dict(v) for v in clips_.values() if isinstance(v, dict) and "Valorant 2025.10.10 - 23.10.09.04" in str(v.get("path", ""))), None)
        if rec:
            rec["game"] = "valorant"
            e_ = M.load_kills_cache().get(M.kills_key(rec, "valorant", M.Detector("valorant")))
    except Exception:                                      # noqa: BLE001
        e_ = None
    finally:
        if old is not None:
            M.restore_data_dir(old)
    if not e_:
        print("  (the clip's scan is not in this montage_data: real-data check skipped)")
        return
    ks = [round(k["t"], 1) for k in M.analyse_entry(e_, cfg, "valorant")["kills"]]
    check(f"Valorant 2025.10.10 - 23.10.09.04: kills {ks} (КИРИЛЛ ~5.9, Veto ~13.3, melanholia ~14.3; no kill at 8.9)", len(ks) == 3 and abs(ks[0] - 5.9) < 0.2 and abs(ks[1] - 13.3) < 0.3 and abs(ks[2] - 14.3) < 0.3)


def part2():
    print("2) the move icon")
    tmp = Path(tempfile.mkdtemp(prefix="v887m_"))
    clips = tmp / "clips" / "Valorant"
    clips.mkdir(parents=True)
    cfg = dict(M.DEFAULT_CONFIG, clip_root=str(tmp), clip_dirs={"valorant": [str(clips)], "cs2": [], "r6s": []}, output_root=str(tmp / "out"))
    root = M.moved_root(cfg)
    check(f"moved clips go to <clip root>\\{M.MOVED_DIR_NAME} ({root})", Path(root) == tmp / M.MOVED_DIR_NAME)
    inside = dict(cfg, clip_root=str(clips))
    check("never inside a scanned clip folder (then next to montage_data)", not M.norm(M.moved_root(inside)).startswith(M.norm(str(clips))))
    src = clips / "a.mp4"
    src.write_bytes(b"x" * 10)
    d1 = M.move_clip_file(str(src), "valorant", cfg)
    src.write_bytes(b"y" * 10)
    d2 = M.move_clip_file(str(src), "valorant", cfg)
    check(f"moved into the game's folder, nothing overwritten ({Path(d1).name}, {Path(d2).name})", Path(d1).parent == Path(root) / "Valorant" and Path(d2).name == "a (2).mp4"
          and Path(d1).read_bytes() == b"x" * 10 and not src.exists())
    check("one folder per game", M.MOVED_GAME_DIR == {"valorant": "Valorant", "cs2": "CS2", "r6s": "Rainbow Six"})
    (tmp / "clips" / M.MOVED_DIR_NAME).mkdir()
    (tmp / "clips" / M.MOVED_DIR_NAME / "b.mp4").write_bytes(b"z" * 10)
    found = list(M.walk_files([str(tmp / "clips")], {".mp4"}, 1, cfg))
    check("a folder with that name is never scanned, even inside a clip folder", not any(M.MOVED_DIR_NAME in f for f in found))
    src_ = V6.V5.SRC()
    check("the clip list has a move column next to the trash column; a click moves, never ticks", '("open", "move", "trash")' in src_ and M.App.MOVE_COL == "#6" and M.App.TRASH_COL == "#7"
          and "self.move_clip(iid)" in V6.V5.body_of("on_tree_click") if hasattr(M, "App") else False)
    check("the trash icon works as before (Recycle Bin)", "trash_file(iid)" in src_ and "self.trash_clip(iid)" in src_)


def part3():
    print("3) everything V8.8.6 checked")
    for p_ in ("1", "2", "3", "4", "5", "6"):
        V6.__dict__["part" + p_]()


if __name__ == "__main__":
    for p_ in PARTS:
        globals()["part" + p_]()
    print("\nFAILED: " + ", ".join(T.FAILS) if T.FAILS else "\nall checks passed")
    sys.exit(1 if T.FAILS else 0)
