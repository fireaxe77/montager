r"""V9.5.2 search-only test of the candidate scoring (NO download): the pick, its channel and extra-word count for LUM!X - Halo, S3RL - Beat All The Odds (DJ Edit) and the songs of one day
(default 2026-10-31), next to the video the older rule had downloaded (read from montage.log). python tests/search952.py [YYYY-MM-DD]   (MONTAGER_DATA = a folder with a copy of config.json)"""
import datetime
import os
import re
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _root                                                                                  # noqa: E402
sys.path.insert(0, str(_root.find_root()))
warnings.simplefilter("ignore")
import montage as m                                                                           # noqa: E402
import ytsongs as y                                                                           # noqa: E402

day = sys.argv[1] if len(sys.argv) > 1 else "2026-10-31"
cfg = m.load_config()
csvp, rows, _ = m.read_playlist(cfg)
meta = y.read_meta(csvp)
data = os.environ["MONTAGER_DATA"]
audio = [a for a in m.scan_audio(cfg) if datetime.date.fromtimestamp(os.path.getmtime(a["path"])).isoformat() == day]
matched, _un = m.match_playlist(rows, audio, cfg, loose=False)
want = [r for r in rows if r["title"].startswith("Halo (feat. PIA MARIA)") or r["title"].startswith("Beat All The Odds - DJ Edit")] + [r for r, a, sc in matched]
old_ids = {}
logp = os.environ.get("MONTAGE_LOG", r"C:\Users\fireaxe\Desktop\CLAUDECODE\montager\montage_data\logs\montage.log")
try:
    for ln in open(logp, encoding="utf-8", errors="replace"):
        if "yt: Checked 10 newest" in ln:
            for tt, vid in re.findall(r"\|   (.+?) - .*? \| video: .*? https://youtu\.be/(\S+)", ln.replace("|       ", " | ")):
                old_ids[tt.strip()] = vid
except OSError:
    pass
for r in want:
    arts = [x.strip() for x in r["artist"].split(",")]
    tg = y.track_tags(r, meta)
    cands = y.find_candidates(data, r["title"], r["artist"])
    ranked, rej = y.rank(cands, r["title"], arts, r["dur"], tg["label"])
    print(f"\n{r['title']} | {r['artist']} | {y.fmt_len(r['dur'])} | label {tg['label']}")
    if not ranked:
        print("   NOT FOUND:", y.nearest_miss(rej, r["dur"]))
        continue
    print("   PICK  ", y.describe(ranked[0]), "| UNCERTAIN" if ranked[0]["uncertain"] else "| confident")
    if len(ranked) > 1:
        print("   2nd   ", y.describe(ranked[1]))
    ov = old_ids.get(r["title"])
    if ov:
        print(f"   older rule downloaded https://youtu.be/{ov}: {'SAME video' if ov == ranked[0]['id'] else 'different video'}")
