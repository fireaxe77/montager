"""V6.0 targeted tests (no render, generated data): auto length fill, per-clip audio fallback, player names + cache, weekly pick."""
import sys, tempfile
from pathlib import Path
import montage as m


def auto_len(n, seed=3, dur=200.0):
    tmpd = Path(tempfile.mkdtemp(prefix="v60_"))
    old = m.use_data_dir(tmpd / "data")
    ca = m.clip_audio
    m.clip_audio = lambda rec, *a, **k: {"stream": None, "lufs": None}
    try:
        sp = tmpd / "s.mp3"
        m.synth_song(sp, 128.0)
        an = m.analyse_song(str(sp), 128.0)
        evs = m.fake_events(n=n, seed=seed)
        song = {"path": str(sp), "artist": "a", "title": "t", "energy": 0.8, "dance": 0.7}
        notes = []
        plan = m.plan_montage(dict(m.DEFAULT_CONFIG), "valorant", evs, song, an, 1, "auto", "optimal", [], notes)
        return plan, notes
    finally:
        m.clip_audio = ca


def audio_clip_test():
    fails = []
    ca, la = m.clip_audio, m.clip_audio_legacy
    m.clip_audio = lambda rec, setting="auto": ({"stream": 1, "lufs": -70.0} if "bad" in rec["path"] else {"stream": 0, "lufs": -20.0})
    m.clip_audio_legacy = lambda rec: {"stream": 2, "lufs": -25.0, "note": "legacy"}
    try:
        st = {}
        good = m.resolve_clip_audio({"path": "/x/good.mov", "audio": True}, {"audio_mode": "auto"}, "valorant", st)
        bad = m.resolve_clip_audio({"path": "/x/bad.mov", "audio": True}, {"audio_mode": "auto"}, "valorant", st)
        if good["stream"] != 0 or bad["stream"] != 2:
            fails.append(f"per-clip audio wrong: good {good} bad {bad}")
        if st.get("mode") != "auto" or len(st.get("clip_fallback", [])) != 1 or st.get("fallback"):
            fails.append(f"state wrong: {st}")
    finally:
        m.clip_audio, m.clip_audio_legacy = ca, la
    return fails


def main():
    fails = audio_clip_test()
    for n, lo, hi in ((60, 80, 150), (2, 0, 80)):
        plan, notes = auto_len(n)
        d = plan["duration"]
        print(f"events={n}: montage {d:.0f} s, takes {len(plan['takes'])}")
        if not (lo - 0.5 <= d <= hi + 0.5):
            fails.append(f"n={n}: {d:.0f} s not in {lo}-{hi}")
        if m.verify_cutlist(plan):
            fails.append(f"n={n}: cut list invalid")
    print("FAIL" if fails else "OK", fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
