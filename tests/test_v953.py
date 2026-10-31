r"""V9.5.3 tests (fast; synthetic songs, no network): the audio identity, the one-time migration of the song caches, hand labels, no rebuild after a tag / cover rewrite.
python tests/test_v953.py        V953_PARTS=0,1,2,3,4,5"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _root import find_root
ROOT = find_root(__file__)
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MONTAGER_DATA", tempfile.mkdtemp(prefix="v953data_"))
import montage as M
import songid
import ytsongs as y

PARTS = os.environ.get("V953_PARTS", "0,1,2,3,4,5").split(",")
FAILS = []


def check(name, cond, info=""):
    print(("ok   " if cond else "FAIL ") + name + (f"  {info}" if info and not cond else ""))
    if not cond:
        FAILS.append(name)


def make_mp3(path, freq=440, secs=3):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={secs}", "-c:a", "libmp3lame", "-q:a", "5", "-map_metadata", "-1", "-id3v2_version", "0",
                    "-write_id3v1", "0", "-y", str(path)], check=True)


def jpeg(c=(200, 30, 30)):
    from PIL import Image
    import io
    b = io.BytesIO()
    Image.new("RGB", (500, 500), c).save(b, "JPEG")
    return b.getvalue()


def main():
    td = Path(tempfile.mkdtemp(prefix="v953_"))
    data = td / "data"
    songs = td / "songs"
    data.mkdir()
    songs.mkdir()
    old = M.use_data_dir(data)
    try:
        if "0" in PARTS:
            check("0 APP_VERSION is V9.5.3", 'APP_VERSION = "V9.5.3"' in (ROOT / "montage.py").read_text(encoding="utf-8"))
            check("0 songid.py ships with the installers", "songid" in (ROOT / "packaging" / "make_release.py").read_text(encoding="utf-8") and "songid" in (ROOT / "packaging" / "montager.spec").read_text(encoding="utf-8"))

        if "1" in PARTS:
            a, b, c = songs / "a.mp3", songs / "b.mp3", songs / "c.mp3"
            make_mp3(a)
            make_mp3(c, freq=880)
            shutil.copy2(a, b)
            ida = songid.audio_id(a, data)
            y.apply_tags(b, {"title": "T", "artist": "A", "album": "Alb", "year": "2020"}, jpeg(), fresh=True)
            idb = songid.audio_id(b, data)
            check("1 two files with identical audio but different tags / cover have the same identity", ida == idb, (ida, idb))
            check("1 the files really differ (size, first bytes)", a.stat().st_size != b.stat().st_size and a.read_bytes()[:64] != b.read_bytes()[:64])
            check("1 different audio = a different identity", songid.audio_id(c, data) != ida)
            y.apply_tags(b, {"genre": "pop"}, None)
            check("1 rewriting the tags again keeps it", songid.audio_id(b, data) == ida)
            raw = b.read_bytes()
            (songs / "v1.mp3").write_bytes(raw + b"TAG" + b"\x00" * 125)           # an ID3v1 block at the end
            check("1 an ID3v1 block at the end does not change it", songid.audio_id(songs / "v1.mp3", data) == ida)
            ape = b"APETAGEX" + (2000).to_bytes(4, "little") + (1024 + 32).to_bytes(4, "little") + (1).to_bytes(4, "little") + (1 << 31).to_bytes(4, "little") + b"\0" * 8
            (songs / "ape.mp3").write_bytes(raw + b"\x01" * 1024 + b"APETAGEX" + (2000).to_bytes(4, "little") + (1024 + 32).to_bytes(4, "little") + (1).to_bytes(4, "little") + (0).to_bytes(4, "little") + b"\0" * 8)
            check("1 an APE block at the end does not change it", songid.audio_id(songs / "ape.mp3", data) == ida)
            check("1 the identity carries the duration", ida.endswith("-30"), ida)
            t0 = os.stat(a).st_mtime_ns
            check("1 the second call reads nothing (index)", songid.audio_id(a, data) == ida and os.stat(a).st_mtime_ns == t0 and str(a) in songid.index_load(data))

        if "2" in PARTS:                                     # migration of an old-form cache + no rebuild after a tag rewrite
            import songmap_v2
            import songmap_v2.build as B
            orig = B.file_signature
            d2 = td / "d2"
            s2 = td / "s2"
            d2.mkdir()
            s2.mkdir()
            M.restore_data_dir(old)
            old2 = M.use_data_dir(d2)
            try:
                f1, f2, f3 = s2 / "One - X.mp3", s2 / "Two - Y.mp3", s2 / "Gone - Z.mp3"
                make_mp3(f1, 440)
                make_mp3(f2, 660, 4)
                make_mp3(f3, 990, 5)
                for i, f in enumerate((f1, f2, f3)):
                    os.utime(f, (1_700_000_000 + i * 100, 1_700_000_000 + i * 100))
                osig = {f: orig(str(f)) for f in (f1, f2, f3)}                     # the OLD signatures (size - time - bytes)
                code = songmap_v2.build._code_sig()
                mk = lambda sig, suffix="": f"songmap_v2|v2.0|{sig}|0.0|v7.1|{code}{suffix}"
                v2 = {mk(osig[f1]): {"dur": 3.0, "beats": [1, 2, 3], "marker": "one"}, mk(osig[f2], "|v1:120.0"): {"dur": 4.0, "beats": [9], "marker": "two"},
                      mk("999-1699999999-deadbeef0000"): {"dur": 9.0, "marker": "orphan with no file"}}
                (d2 / "song_cache_v2.json").write_text(json.dumps(v2), encoding="utf-8")
                (d2 / "repeat_cache.json").write_text(json.dumps({f"r1|{osig[f1]}|10.00,20.00": [{"t": 1}]}), encoding="utf-8")
                (d2 / "song_drops.json").write_text(json.dumps({"One - X.mp3": {"title": "", "artist": "", "drops": [10.5, 30.0], "strong_beats": [5.0]}, "Gone - Z.mp3": {"drops": [1.0]}}), encoding="utf-8")
                hand_before = (d2 / "song_drops.json").read_bytes()
                # tags + cover are written (sizes and first bytes change, modified times stay) BEFORE the new version first runs: the situation after the Apply
                for f in (f1, f2):
                    st = os.stat(f)
                    y.apply_tags(f, {"title": "t", "album": "al", "year": "2000"}, jpeg(), fresh=True)
                    os.utime(f, (st.st_atime, st.st_mtime))
                check("2 (setup) the old signatures no longer match the tagged files", all(orig(str(f)) != osig[f] for f in (f1, f2)))
                cfg = {"mp3_dir": str(s2), "output_root": str(td / "out"), "skip_dirs": []}
                txt = M.songdata_migrate(cfg)
                check("2 the migration ran and made a backup first", txt and "backup of" in txt and list(d2.glob("backup_songdata_*")))
                bk = next(d2.glob("backup_songdata_*"))
                check("2 the backup holds the original caches", json.loads((bk / "song_cache_v2.json").read_text(encoding="utf-8")) == v2)
                new = json.loads((d2 / "song_cache_v2.json").read_text(encoding="utf-8"))
                M.songid_install()
                calls = []
                real_build = B.build_songmap_v2
                B.build_songmap_v2 = lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(RuntimeError("rebuild!"))
                try:
                    k1 = songmap_v2.cache_key(str(f1), None, None)
                    k2 = songmap_v2.cache_key(str(f2), None, 120.0)
                    check("2 the tagged files' cache keys now find the OLD maps (no rebuild)", new.get(k1, {}).get("marker") == "one" and new.get(k2, {}).get("marker") == "two", (k1, list(new)[:3]))
                    # retag AGAIN (another change): the key stays
                    st = os.stat(f1)
                    y.apply_tags(f1, {"genre": "rock", "label": "L"}, None)
                    check("2 tags rewritten once more: the same key", songmap_v2.cache_key(str(f1), None, None) == k1)
                finally:
                    B.build_songmap_v2 = real_build
                check("2 no song map was rebuilt", not calls)
                check("2 the unreachable entry (no file) is kept as it was", any(v.get("marker") == "orphan with no file" for v in new.values()))
                check("2 the repeat-drop cache is re-keyed", any(k.startswith("r1|a1-") for k in json.loads((d2 / "repeat_cache.json").read_text(encoding="utf-8"))))
                check("2 hand labels are byte-identical", (d2 / "song_drops.json").read_bytes() == hand_before)
                lab = json.loads((d2 / "song_label_ids.json").read_text(encoding="utf-8"))
                check("2 label identities recorded for the labelled songs that exist", "One - X.mp3" in lab and "Gone - Z.mp3" in lab, lab)
                check("2 the V1 bpm that was part of a key is recorded per identity", any(v == 120.0 for v in json.loads((d2 / "song_v1bpm.json").read_text(encoding="utf-8")).values()))
                check("2 the V1 peek finds it for the re-tagged file", M._peek_v1_bpm(str(f2), None) == 120.0)
                check("2 it runs once: flag set, a second run does nothing", M.load_config().get(M.SONGDATA_FLAG) is True and M.songdata_migrate(M.load_config()) is None)
                # hand labels: by name as before; a RENAMED file keeps them through the identity
                check("2 hand labels still found for the retagged file", M.song_drop_labels(str(f1)) == [10.5, 30.0] and M.song_strong_beats(str(f1)) == [5.0])
                f1b = s2 / "Renamed - X.mp3"
                f1.rename(f1b)
                check("2 a renamed file keeps its labels (found by audio identity)", M.song_drop_labels(str(f1b)) == [10.5, 30.0])
                check("2 a song with no labels has none", M.song_drop_labels(str(f2)) is None)
            finally:
                M.restore_data_dir(old2)
            old = M.use_data_dir(data)

        if "3" in PARTS:                                     # two entries of the same audio: the older map stays the map
            import songmap_v2
            d3, s3 = td / "d3", td / "s3"
            d3.mkdir()
            s3.mkdir()
            M.restore_data_dir(old)
            old3 = M.use_data_dir(d3)
            try:
                import songmap_v2.build as B
                f = s3 / "S - A.mp3"
                make_mp3(f, 500)
                os.utime(f, (1_700_000_500, 1_700_000_500))
                orig = B.file_signature if not M._SONGID["done"] else M._SONGID["orig"]
                s_old = orig(str(f))
                st = os.stat(f)
                y.apply_tags(f, {"title": "x", "album": "y"}, jpeg(), fresh=True)
                os.utime(f, (st.st_atime, st.st_mtime))
                s_new = orig(str(f))
                code = songmap_v2.build._code_sig()
                mk = lambda sig: f"songmap_v2|v2.0|{sig}|0.0|v7.1|{code}"
                (d3 / "song_cache_v2.json").write_text(json.dumps({mk(s_old): {"dur": 3.0, "marker": "OLD (made before the tags)"}, mk(s_new): {"dur": 3.0, "marker": "rebuilt after"}}), encoding="utf-8")
                M._SONGID["ensured"] = False
                M.songdata_migrate({"mp3_dir": str(s3), "output_root": str(td / "o"), "skip_dirs": []})
                new = json.loads((d3 / "song_cache_v2.json").read_text(encoding="utf-8"))
                main = [v for k, v in new.items() if not k.endswith("|alt")]
                alt = [v for k, v in new.items() if k.endswith("|alt")]
                check("3 the map made before the tags stays the map, the other is kept as '|alt'", len(main) == 1 and main[0]["marker"].startswith("OLD") and len(alt) == 1 and alt[0]["marker"] == "rebuilt after", new)
            finally:
                M.restore_data_dir(old3)
            old = M.use_data_dir(data)

        if "4" in PARTS:                                     # the label writer records identities; the match cache follows the file name + tags
            f = songs / "L - Q.mp3"
            make_mp3(f, 300)
            M.song_drops_write(str(f), [12.0, 40.0], "t", "a")
            ids = json.loads((data / "song_label_ids.json").read_text(encoding="utf-8"))
            check("4 saving a hand label records the song's audio identity", ids.get("L - Q.mp3") == songid.audio_id(f, data), ids)
            g = songs / "Renamed L - Q.mp3"
            f.rename(g)
            check("4 and the label follows the audio to a new file name", M.song_drop_labels(str(g)) == [12.0, 40.0])
            M.song_drops_write(str(g), None)

        if "5" in PARTS:                                     # an unreadable path never raises
            check("5 an unreadable file has no identity (and no exception)", songid.audio_id(songs / "nope.mp3", data) is None)
            check("5 non-MP3 files are hashed whole", songid.audio_region(str(songs / "a.mp3"))[0] >= 0)
    finally:
        try:
            M.restore_data_dir(old)
        except Exception:                                    # noqa: BLE001
            pass
        shutil.rmtree(td, ignore_errors=True)
    print("\nALL OK" if not FAILS else f"\n{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
