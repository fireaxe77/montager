"""V8.4.5 tool: audio facts of every source clip of a saved plan json (streams, channels, rate, start time, first / last packet, video start, duration).
python tests/audioinfo845.py <plan.json>"""
import json
import subprocess
import sys
from pathlib import Path


def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=index,codec_type,codec_name,channels,channel_layout,sample_rate,start_time,duration,nb_frames:format=start_time,duration",
                        "-of", "json", str(path)], capture_output=True)
    return json.loads(r.stdout.decode("utf-8", "ignore") or "{}")


def first_last_packet(path, stream):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", f"a:{stream}", "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(path)], capture_output=True)
    v = [float(x) for x in r.stdout.decode().split() if x.replace(".", "", 1).replace("-", "", 1).isdigit()]
    return (v[0], v[-1], len(v)) if v else (None, None, 0)


def main(plan_json):
    plan = json.load(open(plan_json, encoding="utf-8"))
    for i, t in enumerate(plan["takes"], 1):
        for sr in t.get("srcs") or [{"path": t["path"], "audio": t.get("audio"), "a_stream": 0}]:
            pr = probe(sr["path"])
            st = pr.get("streams", [])
            vs = [s for s in st if s["codec_type"] == "video"]
            au = [s for s in st if s["codec_type"] == "audio"]
            fl = first_last_packet(sr["path"], 0) if au else (None, None, 0)
            print(f"take {i:2d} {Path(sr['path']).name[-34:]:34s} audio flag {sr.get('audio')} a_stream {sr.get('a_stream')} shift {sr.get('shift')} gain {sr.get('gain_db')} mute {sr.get('mute')} music_db {sr.get('music_db')} | "
                  f"video start {vs[0].get('start_time') if vs else None} | audio streams {[(s['codec_name'], s.get('channels'), s.get('sample_rate'), s.get('start_time'), s.get('duration')) for s in au]} | packets first/last/n {fl}")


if __name__ == "__main__":
    main(sys.argv[1])
