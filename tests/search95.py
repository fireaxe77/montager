"""V9.5: search-only run of the yt-dlp pick rules on 8 real tracks (no download). python tests/search95.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ytsongs as y

TRACKS = [("die for you", "Anna Marx", "2:17"), ("Иду за тобой", "Три дня дождя", "2:36"), ("Heartbreak", "BOVSKI, Paraçek", "2:09"),
          ("Отпуск в сентябре", "Три дня дождя", "3:07"), ("Вечная любовь (Трибьют Дениса ...)", "Три дня дождя, Майвл", "4:05"),
          ("Angels Fall", "Flerian", "1:31"), ("bpd gf", "EXODIA, AGONY, Silencee", "2:46"), ("Hey Mama", "Kanye West", "5:05")]


def secs(s):
    m, x = s.split(":")
    return int(m) * 60 + int(x)


if __name__ == "__main__":
    data = Path(__file__).resolve().parent.parent / "montage_data"
    for i, (t, a, l) in enumerate(TRACKS, 1):
        arts = a.split(", ")
        c = y.find_candidates(data, t, a)
        best, miss = y.pick(c, t, arts, secs(l))
        if best:
            print(f"{i}. {t} | {a} | {l}\n   -> \"{best['title']}\" | {best['channel']} | {y.fmt_len(best['duration'])} | {best['kind']} | https://youtu.be/{best['id']}")
        else:
            print(f"{i}. {t} | {a} | {l}\n   -> NOT FOUND ({len(c)} results) {miss}")
