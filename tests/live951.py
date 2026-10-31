r"""V9.5.1 real-data checks of the cover / tag tools (needs network). MONTAGER_DATA = a folder with a COPY of config.json (caches go there).
  python tests/live951.py preview        PREVIEW on the whole real library (reads only: no file is changed)
  python tests/live951.py apply20        Apply on 20 TEMPORARY COPIES (5 of them with a cover / tags of their own) - existing covers / tags / audio must stay
  python tests/live951.py batch2         Download / replace selected on 2 songs in a TEMPORARY songs folder (one replaces a copy of an existing MP3, one is new): real YouTube + Deezer
The real library is never written."""
import hashlib
import json
import os
import queue
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _root import find_root
sys.path.insert(0, str(find_root(__file__)))
import montage as m
import ytsongs as y


class Stub:
    def __init__(self):
        self.q = queue.Queue()
        self.tasks = []
        self.load_matches = None
        self.cov_preview = None
    def run_task(self, name, fn, *a):
        self.tasks.append(name)
    def say(self, t):
        if t.endswith("00/") or True:
            self.last = t
    def show_yt_report(self, title, text):
        print("=== " + title + "\n" + text)
    def drain(self):
        while not self.q.empty():
            k, fn = self.q.get()
            fn()


def audio_hash(path):
    """hash of everything after the ID3v2 tag (and without a trailing ID3v1 tag): the audio frames"""
    from mutagen.id3 import ID3
    b = Path(path).read_bytes()
    try:
        start = ID3(path).size
    except Exception:
        start = 0
    end = len(b) - 128 if b[-128:-125] == b"TAG" else len(b)
    return hashlib.sha1(b[start:end]).hexdigest()


def preview():
    st = Stub()
    t0 = time.time()
    m.App.covers_task(st, False)
    st.drain()
    print(f"preview took {time.time() - t0:.0f} s")


def apply20():
    from mutagen.id3 import ID3, TALB, TIT2, APIC
    cfg = m.load_config()
    csvp, rows, _ = m.read_playlist(cfg)
    audio = [a for a in m.scan_audio(cfg) if a["path"].lower().endswith(".mp3")]
    matched, _un = m.match_playlist(rows, audio, cfg, loose=False)
    exact = [(r, a) for r, a, sc in matched if sc >= 100]
    # prefer files that lack a cover (so Apply has work) and a few that already have one
    nocov = [(r, a) for r, a in exact if not y.read_state(a["path"])[0]][:15]
    withcov = [(r, a) for r, a in exact if y.read_state(a["path"])[0]][:5]
    pick = (nocov + withcov)[:20]
    td = Path(tempfile.mkdtemp(prefix="apply20_"))
    songs = td / "songs"
    songs.mkdir()
    tiny = bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f0000010501010101010100000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbfcffd9")
    before = {}
    for i, (r, a) in enumerate(pick):
        dst = songs / Path(a["path"]).name
        shutil.copy2(a["path"], dst)
        if i % 4 == 3:                                   # a copy with a cover and tags of its own (must stay exactly as they are)
            t = ID3(str(dst))
            t.setall("TALB", [TALB(encoding=3, text=["MY OWN ALBUM"])])
            t.setall("TIT2", [TIT2(encoding=3, text=["MY OWN TITLE"])])
            t.delall("APIC")
            t.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="mine", data=tiny))
            t.save(str(dst), v2_version=3)
            os.utime(dst, (time.time() - 3600, time.time() - 3600))
        before[dst.name] = {"hash": audio_hash(dst), "state": y.read_state(dst), "mtime": os.stat(dst).st_mtime_ns, "size": dst.stat().st_size,
                            "tags": {k: str(v) for k, v in ID3(str(dst)).items() if not k.startswith("APIC")},
                            "apic": [bytes(x.data) for x in ID3(str(dst)).getall("APIC")]}
    # the app code under test: covers_task with the temp songs folder
    c = m.load_config()
    c["mp3_dir"] = str(songs)
    m.save_json(m.CONFIG_PATH, c)
    st = Stub()
    m.App.covers_task(st, True)
    st.drain()
    bad = []
    for f in sorted(songs.iterdir()):
        b = before[f.name]
        a_ = audio_hash(f)
        if a_ != b["hash"]:
            bad.append(f"{f.name}: AUDIO CHANGED")
        t = ID3(str(f))
        for k, v in b["tags"].items():
            if str(t.get(k)) != v:
                bad.append(f"{f.name}: tag {k} changed {v!r} -> {str(t.get(k))!r}")
        if b["apic"] and [bytes(x.data) for x in t.getall("APIC")] != b["apic"]:
            bad.append(f"{f.name}: existing cover changed")
        if not b["state"][0] and not t.getall("APIC"):
            print(f"  (no Deezer cover for {f.name})")
    names_before, names_after = set(before), {f.name for f in songs.iterdir()}
    if names_before != names_after:
        bad.append(f"file names changed: {names_before ^ names_after}")
    print(f"{len(pick)} copies in {songs}: {len(bad)} problems")
    for x in bad:
        print("  PROBLEM", x)
    shutil.rmtree(td, ignore_errors=True)
    print("temporary copies deleted:", not td.exists())


def batch2():
    cfg = m.load_config()
    csvp, rows, _ = m.read_playlist(cfg)
    audio = [a for a in m.scan_audio(cfg) if a["path"].lower().endswith(".mp3")]
    matched, unmatched, _st = m.match_cached(cfg, csvp, rows, audio)
    have = next((r, a) for r, a, sc in matched if r["title"] == "Angels Fall")
    far = m.datetime.datetime(1970, 1, 1)
    new = sorted([r for r in unmatched if r.get("dur")], key=lambda r: (m.parse_added(r["added"]) or far) if r.get("added") else far, reverse=True)
    new = next((r for r in new if r["title"] == os.environ.get("BATCH2_NEW")), new[0]) if os.environ.get("BATCH2_NEW") else new[0]
    td = Path(tempfile.mkdtemp(prefix="batch2_"))
    songs = td / "songs"
    songs.mkdir()
    old = songs / Path(have[1]["path"]).name
    shutil.copy2(have[1]["path"], old)
    old_bytes = old.read_bytes()
    c = m.load_config()
    c["mp3_dir"] = str(songs)
    m.save_json(m.CONFIG_PATH, c)
    st = Stub()
    st.yt_ready = lambda cfg_, rows_: m.App.yt_ready(st, cfg_, rows_)
    st.yt_run = lambda *a: m.App.yt_run(st, *a)
    st.say = lambda t: print("STATUS:", t)
    todo = [dict(have[0], _old=str(old)), dict(new)]
    print("selected: 1 row WITH an MP3 (replace):", have[0]["title"], "| 1 row WITHOUT:", new["title"], "-", new["artist"])
    m.App.download_selected(st, todo)
    st.drain()
    print("songs folder now:", sorted(p.name for p in songs.rglob("*") if p.is_file()))
    rp = songs / "_replaced" / old.name
    print("old file kept in _replaced, byte-identical:", rp.is_file() and rp.read_bytes() == old_bytes)
    from mutagen.id3 import ID3
    for f in sorted(songs.glob("*.mp3")):
        t = ID3(str(f))
        print("  ", f.name, "| title", str(t.get("TIT2")), "| album", str(t.get("TALB")), "| cover", [(x.type, y.image_size(x.data)) for x in t.getall("APIC")], "| isrc", str(t.get("TSRC")))
    audio2 = m.scan_audio(dict(m.load_config()), rescan=True)
    mt, un = m.match_playlist(rows, audio2, m.load_config(), loose=False)
    print("the app's matching counts:", [(r["title"], sc) for r, a, sc in mt if r["title"] in (have[0]["title"], new["title"])], "| _replaced is not scanned:", all("_replaced" not in a["path"] for a in audio2))
    shutil.rmtree(td, ignore_errors=True)
    print("temporary folder deleted:", not td.exists())


if __name__ == "__main__":
    {"preview": preview, "apply20": apply20, "batch2": batch2}[sys.argv[1]]()
