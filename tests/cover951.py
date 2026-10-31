r"""V9.5.1 lookup only (no file is changed): Deezer cover for the songs in the songs folder that were modified on a given day (default: 2026-10-31).
python tests/cover951.py [YYYY-MM-DD]   (needs network; MONTAGER_DATA = a folder holding a copy of config.json, the Deezer cache goes there)"""
import datetime
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _root import find_root
sys.path.insert(0, str(find_root(__file__)))
import montage as m
import ytsongs as y


def main():
    day = sys.argv[1] if len(sys.argv) > 1 else "2026-10-31"
    cfg = m.load_config()
    csvp, rows, _ = m.read_playlist(cfg)
    meta = y.read_meta(csvp)
    audio = [a for a in m.scan_audio(cfg) if datetime.date.fromtimestamp(os.path.getmtime(a["path"])).isoformat() == day]
    matched, _un = m.match_playlist(rows, audio, cfg, loose=False)
    data = os.environ["MONTAGER_DATA"]
    print(f"{len(audio)} songs of {day}, {len(matched)} matched to the CSV")
    for r, a, sc in matched:
        tg = y.track_tags(r, meta)
        row = dict(r, isrc=tg["isrc"])
        try:
            lk = y.cover_lookup(row, data)
            if lk["url"]:
                img = y.cover_image(lk["url"], y.row_key(row), data)
                print(f"- {r['title']} | {r['artist']}: Deezer by {lk['match'].upper()}, image {y.image_size(img)}, {len(img) // 1024} KB, ISRC {tg['isrc'] or '-'}")
            else:
                print(f"- {r['title']} | {r['artist']}: NO Deezer cover (isrc {tg['isrc'] or '-'})")
        except RuntimeError as ex:
            print(f"- {r['title']} | {r['artist']}: ERROR {ex}")
    y.cache_save(data)


if __name__ == "__main__":
    main()
