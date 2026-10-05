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


def names_test():
    fails = []
    tmpd = Path(tempfile.mkdtemp(prefix="v60n_"))
    old = m.use_data_dir(tmpd / "data")
    blobs = [[290, 24, 110, 22, 0.6]]
    boxes = lambda k, v: [[60, 20, 260, 50, k, 0.9, 12, ""], [420, 20, 540, 50, v, 0.9, 12, ""]]

    def verdicts(k, v, game):
        rows = m.ocr_rows(boxes(k, v), blobs, game)
        return [vv for r in rows for vv, _ in m.classify_row(r)]
    try:
        m.set_player_names({})
        base = {g: [verdicts("fireaxe", "enemy", g), verdicts("enemy", "fireaxe", g), verdicts("enemy + fireaxe", "victim", g)]
                for g in ("valorant", "cs2")}
        if base["cs2"] != [["kill"], ["death"], ["reject"]] or base["valorant"] != base["cs2"]:
            fails.append(f"default names behave differently: {base}")
        m.set_player_names({"player_names": {"valorant": ["fireaxe", "zzalias"], "cs2": ["fireaxe", "火斧", "zzalias"]}})
        for g in ("valorant", "cs2"):
            got = [verdicts("zzalias", "enemy", g), verdicts("enemy", "zzalias", g), verdicts("enemy + zzalias", "victim", g)]
            if got != base[g]:
                fails.append(f"{g}: alias differs from default name: {got} vs {base[g]}")
        # cache: an old entry (no names record) is valid, not stale; a new scan records names; changed names => stale
        m.set_player_names({})
        st = m.load_kills_cache()
        st.put("/c/a.mov|1|2|cs2|ocrabcdef12v9nb", {"v": 9, "ocr": [[0, 0, [], []]]})
        st.put("/c/b.mov|1|2|cs2|ocrabcdef12v9nb", {"v": 9, "names": m.names_for_cache("cs2"), "ocr": [[0, 0, [], []]]})
        ka, kb = "/c/a.mov|1|2|cs2|ocrabcdef12v9nb", "/c/b.mov|1|2|cs2|ocrabcdef12v9nb"
        if m.cached_names(st, ka, "cs2") != m.names_for_cache("cs2") or m.cached_names(st, kb, "cs2") != m.names_for_cache("cs2"):
            fails.append("default-name cache entries must not be stale")
        if m.names_stale(st.get(ka), "cs2") or m.names_stale(st.get(kb), "cs2"):
            fails.append("names_stale true for default names")
        m.set_player_names({"player_names": {"cs2": ["fireaxe", "火斧", "zzalias"]}})
        if not (m.cached_names(st, ka, "cs2") != m.names_for_cache("cs2") and m.cached_names(st, kb, "cs2") != m.names_for_cache("cs2")):
            fails.append("changed names must mark both entries stale")
        if m.names_for_cache("valorant") != ["fireaxe"] or m.cached_names(st, ka, "valorant") != ["fireaxe"]:
            fails.append("valorant names unexpectedly changed")
    finally:
        m.set_player_names({})
    return fails


def main():
    fails = audio_clip_test() + names_test()
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
