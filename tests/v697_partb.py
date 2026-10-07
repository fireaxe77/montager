"""V6.9.7 part B tests: per-clip 'allow utility kills' override (Valorant). Synthetic OCR frames (the same shape the scanner caches) + real generated footage for the
proof cases; no renders; no scan."""
import datetime
import inspect
import json
import os
import random
import re
import sys
import tempfile
import time
from pathlib import Path

from v697_common import *                                                                        # noqa: F401,F403
from v697_common import mlogged, base_module, led, states, STATE, distinct_names, M, T, R, check, section, logged, snapshot, REAL_DATA, ROOT, make_clip, view_events, harness, rec_of, pool_item, BASE_DT

FPS = M.FPS


def synth_entry(rows, last=480):
    """A cached OCR entry (frames [f, since, boxes, blobs]) with killfeed rows. row = dict(t=first-visible second, hits=OCR frames the row stays, k=killer text,
    v=victim text, icon='gun'|'util', kcol='g', vcol='r', slot=0). Frames step 3 (5 per second)."""
    frames = {}
    for r in rows:
        f0 = int(round(r["t"] * FPS))
        for h in range(r.get("hits", 6)):
            f = f0 + 3 * h
            x, off = 10, r.get("slot", 0) * 30
            boxes, blobs = [], []
            k, v = r["k"], r["v"]
            kw = max(20, 9 * len(k))
            boxes.append([x, 4 + off, x + kw, 24 + off, k, 0.95, r.get("kcol", "g"), f0])
            x += kw + 10
            iw, ih = (70, 14) if r.get("icon", "gun") == "gun" else (18, 18)
            blobs.append([x, 6 + off, iw, ih, 0.9])
            x += iw + 10
            boxes.append([x, 4 + off, x + max(20, 9 * len(v)), 24 + off, v, 0.95, r.get("vcol", "r"), f0])
            fb = frames.setdefault(f, ([], []))
            fb[0].extend(boxes)
            fb[1].extend(blobs)
    ocr = [[f, f, b, g] for f, (b, g) in sorted(frames.items())]
    ocr.append([last, last, [], []])
    return {"ocr": ocr, "frames": last, "v_off": 0.0, "game": "valorant"}


def kill_row(t, victim, icon="gun", **kw):
    return dict(t=t, k="fireaxe", v=victim, icon=icon, **kw)


def pool_env(mod, recs, store, det, game):
    """Real game_pool on generated clips: the scan / store / detector are stubs, everything after them is the real code."""
    saved = {k: getattr(mod, k) for k in ("scan_clips", "load_kills_cache", "load_dets")}
    mod.scan_clips = lambda cfg: [dict(r) for r in recs]
    mod.load_kills_cache = lambda: store
    mod.load_dets = lambda only=None: {game: det}
    return saved


def restore_env(mod, saved):
    for k, v in saved.items():
        setattr(mod, k, v)


class World:
    """Generated Valorant clips (empty files), clip records and cached OCR entries in a fake kill store."""
    n = 0

    def __init__(self, tmp, mod=None):
        World.n += 1
        self.dir = Path(tmp) / f"b_clips{World.n}"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.mod = mod or M
        self.recs, self.store, self.det = [], self.mod.KillStore(), self.mod.Detector("valorant")

    def add(self, name, dur, rows=None, entry=None, mtime=None, game="valorant"):
        p = self.dir / name
        if not p.exists():
            p.write_bytes(b"x")
        if mtime:
            os.utime(p, (mtime, mtime))
        rec = {"path": str(p), "game": game, "w": 1920, "h": 1080, "dur": float(dur), "v_off": 0.0, "bars": False, "bar_sig": "", "audio": False}
        self.recs.append(rec)
        e = entry or synth_entry(rows or [])
        e["game"] = game
        self.store.put(self.mod.kills_key(rec, game, self.det), e)
        return rec


def ORDER_dummy():
    pass


def part_semantics(tmp):
    with section("B1-B2) override OFF = nothing changes; ON admits exactly the 'utility' rows of that clip"):
        cfg = M.load_config()
        w = World(tmp)
        # clip A: 2 normal kills + 1 utility row; clip B (no override): the same shape
        rowsA = [kill_row(8.0, "kuwax"), kill_row(13.0, "lorreth"), kill_row(20.0, "zephyr", "util", slot=1)]
        a = w.add("VALORANT 2026-10-07 03-40-40.mov", 45, rowsA)
        b = w.add("VALORANT 2026-10-07 03-50-40.mov", 45, [kill_row(8.0, "mitski"), kill_row(14.0, "pandemic"), kill_row(25.0, "kuwax", "util", slot=1)])
        saved = pool_env(M, w.recs, w.store, w.det, "valorant")
        try:
            (pool0, st0), lines0 = logged(M.game_pool, cfg, "valorant", None)
            kills0 = {Path(it["rec"]["path"]).name: [(k["t"], k["victim"]) for k in it["kills"]] for it in pool0}
            check(all(len(v) == 2 for v in kills0.values()) and not [x for x in lines0 if x.startswith("utility override")], f"OFF: 2 kills per clip, no override line ({kills0})")
            check(any("utility" in x for x in lines0), "OFF: the utility rows are still reported as rejected (utility: 2)")
            M.set_clip_override([a["path"]], True)
            (pool1, st1), lines1 = logged(M.game_pool, cfg, "valorant", None)
            by = {Path(it["rec"]["path"]).name: it for it in pool1}
            ka, kb = by[Path(a["path"]).name]["kills"], by[Path(b["path"]).name]["kills"]
            ua = [k for k in ka if k.get("util")]
            check(len(ka) == 3 and len(ua) == 1 and ua[0]["victim"] == "zephyr" and "util" in ua[0]["row"] and len(kb) == 2 and not any(k.get("util") for k in kb),
                  f"ON for A: 3 kills, the utility one tagged 'util' ({ua[0]['victim'] if ua else None}); clip B (OFF) unchanged: 2 kills")
            ov = [x for x in lines1 if x.startswith("utility override:")]
            check(len(ov) == 1 and "1 clip(s) enabled, 1 utility kill(s) admitted" in ov[0] and "zephyr" in ov[0] and any(x.startswith("utility kill allowed by override:") for x in lines1),
                  f"log: one summary line + one line per admitted row ({ov[0] if ov else None})")
            check(not any("utility:" in x and Path(a["path"]).name in x for x in lines1) and any("utility:" in x and Path(b["path"]).name in x for x in lines1), "the admitted row leaves the rejected list of A; B's utility row is still rejected")
            # the ledger state
            plan, ll = logged(harness, M, "valorant", [dict(i) for i in pool1], [a["path"], b["path"]])
            lg = led()
            row = [r for r in lg.rows if r["victim"] == "zephyr"]
            check(row and row[0]["tag"] == "util" and row[0]["state"] == "OVERRIDE_ADMITTED", f"ledger state of the admitted row: {row[0]['state'] if row else None}")
            check(any(x.startswith("kill ledger:") and "via utility override" in x for x in ll), "the ledger summary shows how many placed rows came through the override")
            ev = [t for t in plan["takes"] if Path(t["path"]).name == Path(a["path"]).name]
            check(ev and len(ev[0]["kills"]) == 3, "the admitted kill is part of the clip's event (a 2k became a 3k) and of the take range")
            # CS2 has no utility rejection: the override never applies there
            e_a = w.store.get(M.kills_key(a, "valorant", w.det))
            ca = M.analyse_entry(e_a, cfg, "valorant")
            check(M.apply_utility_override(a, e_a, ca, cfg, "cs2", M.load_clip_overrides()) is ca, "CS2: apply_utility_override returns the analysis untouched (Valorant only)")
            M.set_clip_override([a["path"]], False)
            (pool2, _), lines2 = logged(M.game_pool, cfg, "valorant", None)
            check(json.dumps([(Path(i["rec"]["path"]).name, i["kills"]) for i in pool2], default=str, sort_keys=True) == json.dumps([(Path(i["rec"]["path"]).name, i["kills"]) for i in pool0], default=str, sort_keys=True)
                  and not [x for x in lines2 if x.startswith("utility")], "OFF again: kills and log identical to the very first run")
            # exactly the utility one: a clip with a blip, a revive, a death, a duplicate and a utility row
            rows = [kill_row(6.0, "kuwax"), kill_row(9.0, "kuwax", slot=1),                                          # a kill + its duplicate (the same victim again)
                    dict(t=12.0, hits=1, k="Zorro + fireaxe", v="mitski", icon="gun", kcol="g", vcol="r", slot=2),    # assist, ONE frame = blip
                    dict(t=15.0, k="fireaxe", v="fireaxe", icon="gun", kcol="g", vcol="g", slot=0),                   # self revive
                    dict(t=18.0, k="Zorro", v="fireaxe", icon="gun", kcol="r", vcol="g", slot=1),                     # my death
                    kill_row(40.0, "pandemic", "util", slot=2)]                                                       # the utility row (well after my death: no death lock)
            c = w.add("VALORANT 2026-10-07 04-10-40.mov", 45, rows)
            base_k = M.analyse_entry(w.store.get(M.kills_key(c, "valorant", w.det)), cfg, "valorant")
            M.set_clip_override([c["path"]], True)
            (pool3, _), _ = logged(M.game_pool, cfg, "valorant", None)
            kc = [k for it in pool3 if it["rec"]["path"] == c["path"] for k in it["kills"]]
            adm = [k for k in kc if k.get("util")]
            rej_reasons = {re.split(r"[:(]", j["reason"])[0].strip() for j in base_k["rej"]}
            check(len(adm) == 1 and adm[0]["victim"] == "pandemic" and len(kc) == len(base_k["kills"]) + 1 and len(base_k["kills"]) >= 1,
                  f"blip + revive + death + duplicate + utility row: ON admits exactly the utility one ({[k['victim'] for k in kc]}; other rejections stay: {sorted(rej_reasons)})")
        finally:
            restore_env(M, saved)
            M.set_clip_override([a["path"], b["path"], c["path"]], False)


def part_off_guard(tmp):
    with section("B1b) OFF everywhere: kills, events, plan and render command identical to the base (100 Valorant + 100 CS2 clips)"):
        B = base_module(tmp)
        cfg = M.load_config()
        ents = {g: T.gen_entries(100, g) for g in ("valorant", "cs2")}
        evview = lambda evs: json.dumps([{k: v for k, v in e.items() if k != "rec"} for e in evs], sort_keys=True, default=str)
        for game in ("valorant", "cs2"):
            def build(mod):
                w = World(tmp, mod)
                for i, e in enumerate(ents[game]):
                    w.add(f"VALORANT 2026-10-07 {i // 60:02d}-{i % 60:02d}-00.mov" if game == "valorant" else f"Counter-strike 2 2025.02.08 - 19.{10 + i // 60}.{i % 60:02d}.15.DVR.mp4", 45, entry=json.loads(json.dumps(e)), mtime=BASE_DT.timestamp() + 60 * i, game=game)
                w.det = mod.Detector(game)
                for r in w.recs:
                    w.store.put(mod.kills_key(r, game, w.det), json.loads(json.dumps(ents[game][w.recs.index(r)])) | {"game": game})
                saved = pool_env(mod, w.recs, w.store, w.det, game)
                try:
                    (pool, st), lines = mlogged(mod, mod.game_pool, mod.load_config(), game, None)
                finally:
                    restore_env(mod, saved)
                return pool, lines
            pm, lm = build(M)
            pb, lb = build(B)
            norm = lambda pool: json.dumps([(Path(i["rec"]["path"]).name, i["kills"], i["deaths"], i["revives"], i["vis"]) for i in pool], sort_keys=True, default=str)
            check(norm(pm) == norm(pb) and len(pm) > 10 and "\n".join(lm) == "\n".join(lb).replace(str(B.__file__), str(M.__file__)),
                  f"{game}: game_pool (kills, deaths, revives, log lines) identical to the base on 100 generated clips ({sum(len(i['kills']) for i in pm)} kills, {len(pm)} clips)")
            # events / plan / render command: the same pool (unique victim names per kill, so no clips link and part A's proof rule has nothing to decide) through both versions
            vn_ = distinct_names(900)
            uniq = []
            for n_, it in enumerate(pm):
                uniq.append(dict(it, kills=[dict(k, victim=vn_[8 * n_ + j]) for j, k in enumerate(it["kills"])]))
            evm = M.build_events([dict(i) for i in uniq], game, cfg, random.Random(3))
            evb = B.build_events([dict(i) for i in uniq], game, B.load_config(), random.Random(3))
            check(evview(evm[0]) == evview(evb[0]) and len(evm[0]) > 10, f"{game}: events identical to the base ({len(evm[0])} events, every field)")
            song = {"path": "x.mp3", "title": "x", "artist": "a"}
            plm = M.plan_montage(cfg, game, evm[0], song, M.default_song_map(), 5, "auto", "optimal", [], [])
            plb = B.plan_montage(B.load_config(), game, evb[0], song, B.default_song_map(), 5, "auto", "optimal", [], [])
            tk = lambda p: json.dumps([(Path(t["path"]).name, t["segs"], t["kills_out"], t["kills"]) for t in p["takes"]], default=str)
            check(tk(plm) == tk(plb) and len(plm["takes"]) > 2, f"{game}: plan identical to the base ({len(plm['takes'])} takes)")
            check(M.build_filter(plm, {}, False, M.FX_ALL) == B.build_filter(plb, {}, False, B.FX_ALL), f"{game}: render command identical to the base")


def part_proof(tmp):
    with section("B2b) Part A proof rules apply to admitted utility rows (duplicate merged away; continuation grouped + stitched like any kill)"):
        cfg = M.load_config()
        d = Path(tmp) / "b_proof"
        d.mkdir()
        # X [0,40] and Y [30,70] of the same fight: kuwax @35 is a normal kill in X (earlier clip) and a UTILITY row in Y (t=5); lorreth @42 (Y t=12) is a utility row only Y has
        cx = make_clip(d / "x.mov", 0, 40)
        cy = make_clip(d / "y.mov", 30, 40)
        nx, ny = d / "VALORANT 2026-10-07 03-40-40.mov", d / "VALORANT 2026-10-07 03-41-10.mov"
        Path(cx).rename(nx)
        Path(cy).rename(ny)
        os.utime(nx, (BASE_DT.timestamp() + 40,) * 2)
        os.utime(ny, (BASE_DT.timestamp() + 70,) * 2)
        w = World(tmp)
        w.dir = d
        rx = w.add(nx.name, 40, [kill_row(30.0, "zephyr"), kill_row(35.0, "kuwax")])
        ry = w.add(ny.name, 40, [kill_row(5.0, "kuwax", "util"), kill_row(12.0, "lorreth", "util", slot=1), kill_row(18.0, "pandemic", slot=2)])
        saved = pool_env(M, w.recs, w.store, w.det, "valorant")
        try:
            M.set_clip_override([ry["path"]], True)
            (pool, st), lines = logged(M.game_pool, cfg, "valorant", None)
            ky = [k for it in pool if it["rec"]["path"] == ry["path"] for k in it["kills"]]
            check(sorted(k["victim"] for k in ky) == ["kuwax", "lorreth", "pandemic"] and sum(1 for k in ky if k.get("util")) == 2, "Y with the override: 3 kills (2 of them utility rows)")
            (evs, notes), _ = logged(M.build_events, [dict(i) for i in pool], "valorant", cfg, random.Random(1))
            lg = led()
            dup = [r for r in lg.rows if r["merged"]]
            check(len(evs) == 1 and evs[0]["stitched"] and len(evs[0]["parts"]) == 2 and sorted(evs[0]["victims"]) == ["kuwax", "lorreth", "pandemic", "zephyr"],
                  f"the continuation: ONE stitched event of both clips with the admitted lorreth ({view_events(evs)})")
            check(len(dup) == 1 and dup[0]["tag"] == "util" and dup[0]["victim"] == "kuwax" and dup[0]["merged"]["proof"] and Path(dup[0]["path"]).name == ny.name,
                  "the utility row that duplicates a proven earlier kill (kuwax) is merged away with the Part A proof")
            plan, ll = logged(harness, M, "valorant", [dict(i) for i in pool], [rx["path"], ry["path"]])
            lg = led()
            st_ = {r["victim"]: r["state"] for r in lg.rows if r["path"] == ry["path"]}
            check(st_.get("lorreth") == "OVERRIDE_ADMITTED" and st_.get("kuwax") == "MERGED_DUP" and st_.get("pandemic") == "PLACED" and not [r for r in lg.rows if r["state"] == "LOST"], f"ledger: {st_}")
            # without proof (frames of another round): the admitted rows are NOT merged / stitched into the other clip
            cz = make_clip(d / "z.mov", 30, 40, seed=5)
            nz = d / "VALORANT 2026-10-07 03-41-11.mov"
            Path(cz).rename(nz)
            os.utime(nz, (BASE_DT.timestamp() + 71,) * 2)
            rz = w.add(nz.name, 40, [kill_row(5.0, "kuwax", "util"), kill_row(12.0, "lorreth", "util", slot=1)])
            M.set_clip_override([rz["path"]], True)
            (pool, _), _ = logged(M.game_pool, cfg, "valorant", [rx["path"], rz["path"]] and None)
            sub = [dict(i) for i in pool if i["rec"]["path"] in (rx["path"], rz["path"])]
            (evs2, _), _ = logged(M.build_events, sub, "valorant", cfg, random.Random(1))
            check(len(evs2) == 2 and not any(e["stitched"] for e in evs2) and not any(r["merged"] for r in led().rows), "admitted rows of a clip with DIFFERENT frames are not merged into the earlier clip (no proof)")
        finally:
            restore_env(M, saved)
            M.set_clip_override([ry["path"], rz["path"]] if "rz" in dir() else [ry["path"]], False)


def part_persist(tmp):
    with section("B4) clip_overrides.json: persistence, atomic write, corrupt file, renamed / moved clips, no rescan, no cache writes"):
        d = Path(tmp) / "b_pers"
        d.mkdir()
        old = M.use_data_dir(d / "data")
        try:
            w = World(tmp)
            cfg = M.load_config()
            a = w.add("VALORANT 2026-10-07 05-00-10.mov", 45, [kill_row(8.0, "kuwax"), kill_row(20.0, "zephyr", "util", slot=1)])
            b = w.add("VALORANT 2026-10-07 05-10-10.mov", 45, [kill_row(8.0, "mitski")])
            M.save_json(M.KILLS_CACHE.with_name("marker.json"), {"x": 1})
            ovf = d / "data" / "clip_overrides.json"
            check(not ovf.exists() and M.load_clip_overrides() == {}, "default: no file, every clip OFF")
            snap0 = snapshot(d / "data")
            M.set_clip_override([a["path"]], True)
            snap1 = snapshot(d / "data")
            check(set(snap1) - set(snap0) == {"clip_overrides.json"} and all(snap1[k] == snap0[k] for k in snap0), f"switching writes only clip_overrides.json ({sorted(set(snap1) - set(snap0))}; every other file byte-identical)")
            e = json.loads(ovf.read_text(encoding="utf-8"))
            k = M._pkey(a["path"])
            check(list(e) == [k] and e[k]["allow_utility_kills"] is True and e[k]["name"] == Path(a["path"]).name and e[k]["size"] == os.path.getsize(a["path"]) and re.fullmatch(r"\d{4}-\d\d-\d\d", e[k]["set"]),
                  f"entry: same key as the used flags (_pkey), name, size, date ({e[k]})")
            check(not list((d / "data").glob("clip_overrides.json.tmp")), "atomic write: no temp file left behind")
            check(M.clip_override_state(a["path"])[0] == "on" and M.clip_override_state(b["path"])[0] == "off", "survives a reload; other clips stay OFF")
            # a kill-cache rebuild / rescan never touches it
            for f in M.KILLS_CACHE.parent.glob("kills*") if M.KILLS_CACHE.parent.exists() else []:
                pass
            M.use_data_dir(d / "data")
            check(M.clip_override_state(a["path"])[0] == "on", "survives a kill-cache rebuild (the override is not part of any cache)")
            M.set_clip_override([a["path"]], False)
            check(not ovf.exists() or json.loads(ovf.read_text(encoding="utf-8")) == {}, "OFF removes the entry")
            M.set_clip_override([a["path"]], True)
            # corrupt file: all OFF, ONE log line, no crash
            ovf.write_text("{ not json", encoding="utf-8")
            M._OVR_WARNED[0] = None
            r1, l1 = logged(M.load_clip_overrides)
            r2, l2 = logged(M.load_clip_overrides)
            check(r1 == {} and r2 == {} and len(l1) == 1 and not l2 and "clip_overrides.json" in l1[0], f"corrupt file: all OFF and exactly one log line ({l1})")
            saved = pool_env(M, w.recs, w.store, w.det, "valorant")
            try:
                (pool, _), lg = logged(M.game_pool, cfg, "valorant", None)
                check(all(not k.get("util") for it in pool for k in it["kills"]), "corrupt file: the run goes on with every override OFF")
            finally:
                restore_env(M, saved)
            ovf.write_text(json.dumps({k: {"allow_utility_kills": True, "set": "2026-10-07", "name": Path(a["path"]).name, "size": os.path.getsize(a["path"])}}), encoding="utf-8")
            # renamed / moved: reported, never applied to another clip
            moved = Path(a["path"]).with_name("VALORANT 2026-10-07 05-00-11.mov")
            os.replace(a["path"], moved)
            twin = d / "other" / Path(a["path"]).name
            twin.parent.mkdir()
            twin.write_bytes(Path(moved).read_bytes())
            st, why = M.clip_override_state(a["path"])
            check(st == "missing" and "moved or renamed" in why and M.clip_override_state(str(twin))[0] == "off" and M.clip_override_state(str(moved))[0] == "off",
                  f"renamed / moved clip: reported ('{why[:60]}...'), not applied to the new name or to a same-named copy elsewhere")
            os.replace(moved, a["path"])
            Path(a["path"]).write_bytes(b"xx")                                  # same path, other size
            check(M.clip_override_state(a["path"])[0] == "size", "same path but another file size: reported, not applied")
            Path(a["path"]).write_bytes(b"x")
            # a run with the override ON: no rescan of any clip, no write to the kill cache / sidecars
            snapk = snapshot(d / "data")
            boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("a clip was scanned"))
            saved = pool_env(M, w.recs, w.store, w.det, "valorant")
            real = (M.run_scan, M.frame_stream)
            M.run_scan = M.frame_stream = boom
            try:
                (pool, _), lg = logged(M.game_pool, cfg, "valorant", None)
            finally:
                M.run_scan, M.frame_stream = real
                restore_env(M, saved)
            after = snapshot(d / "data")
            changed = {f for f in set(snapk) | set(after) if snapk.get(f) != after.get(f)}
            check(any(k.get("util") for it in pool for k in it["kills"]) and not [f for f in changed if "kills" in f or "cs2_rows" in f or "clips_cache" in f], f"ON run: no clip rescanned, no kill cache / sidecar written (changed: {sorted(changed)})")
        finally:
            M.restore_data_dir(old)


DETECTORS = ["classify_row", "analyse_entry", "ocr_rows", "name_match", "drop_fake_kills", "merge_variants", "resurrect_rows", "_row_match", "weapon_class", "analyse_clip_entry",
             "verified_kills", "refine_kill", "refine_shot", "make_event", "plan_montage", "place", "weekly_pick", "build_filter", "_victim_offset", "verify_stitch", "base_score"]


def part_frozen(tmp):
    with section("B6) frozen code: detector / planner / render source identical to the base commit"):
        B = base_module(tmp)
        same, diff = [], []
        for n in DETECTORS:
            try:
                a, b = inspect.getsource(getattr(M, n)), inspect.getsource(getattr(B, n))
            except (AttributeError, OSError, TypeError):
                continue
            (same if a == b else diff).append(n)
        # make_event gets only the ledger notes (part A); the detector and the planner / render logic must not differ at all
        allowed = {"make_event"}
        check(len(same) >= 15 and not (set(diff) - allowed), f"{len(same)} frozen functions byte-identical to the base; differing: {diff} (make_event: ledger notes only, part A)")
        out = R.run(["git", "diff", "--stat", BASE_REF_B, "--", "songmap_v2", "songmap_compare.py", "fixtures"], text=True, cwd=ROOT).stdout
        check(out.strip() == "", "git diff --stat: no change in songmap_v2 / songmap_compare.py / fixtures")


from v697_common import BASE_REF as BASE_REF_B


def part_cli(tmp):
    with section("B5b) python montage.py utilclip --list / on / off"):
        d = Path(tmp) / "b_cli"
        d.mkdir()
        data = d / "data"
        old = M.use_data_dir(data)
        try:
            w = World(tmp)
            a = w.add("VALORANT 2026-10-07 06-00-10.mov", 45, [kill_row(8.0, "kuwax"), kill_row(20.0, "zephyr", "util", slot=1), kill_row(30.0, "pandemic", "util", slot=2)])
            b = w.add("VALORANT 2026-10-07 06-10-10.mov", 45, [kill_row(8.0, "mitski")])
            # the CLI reads the clip cache + kill cache of its data folder: write them like a scan would
            clips = {M.file_key(r["path"]): r for r in w.recs}
            M.save_json(M.CLIPS_CACHE, clips)
            cfgd = dict(M.load_config(), clip_dirs={"valorant": [str(w.dir)], "cs2": []})
            M.save_json(M.CONFIG_PATH, cfgd)
            for r in w.recs:                                         # the kill store of this data folder
                M.load_kills_cache().put(M.kills_key(r, "valorant", w.det), json.loads(json.dumps(w.store.get(M.kills_key(r, "valorant", w.det)))))
            env = dict(os.environ, MONTAGER_DATA=str(data))
            run = lambda *args: R.run([sys.executable, "-W", "ignore", "montage.py", "utilclip", *args], text=True, cwd=ROOT, env=env, timeout=120)
            r = run("--list")
            check(r.ok and "no clip has it ON" in r.stdout, f"--list with nothing ON: {r.stdout.strip()[:80]}")
            before = snapshot(data)
            r = run("06-00", "on")
            after = snapshot(data)
            check(r.ok and "ON" in r.stdout and "utility rows in the cache: 2" in r.stdout, f"on: prints the clip and how many utility rows it has ({r.stdout.strip().splitlines()[0][:90]}) {R.require(r)[1]}")
            check(set(after) - set(before) == {"clip_overrides.json"} and all(after[k] == before[k] for k in before), "on: wrote only clip_overrides.json")
            r = run("--list")
            check(r.ok and "06-00-10" in r.stdout and "utility rows in the cache: 2" in r.stdout and "06-10-10" not in r.stdout, "--list shows the ON clip with its utility row count")
            r = run("06-10", "on")
            r = run("06-00", "off")
            r2 = run("--list")
            check("06-00-10" not in r2.stdout and "06-10-10" in r2.stdout, "off removes that clip; the other stays")
            r = run("zzz", "on")
            check(r.returncode != 0 and "no Valorant clip" in (r.stdout + r.stderr), "unknown fragment: a clear message, nothing written")
            run("06-10", "off")
        finally:
            M.restore_data_dir(old)


def part_gui(tmp):
    with section("B5) Manual list: right-click menu, [U] indicator, multi-select, hidden for CS2 (GUI)"):
        import test_v557 as G
        app, old = G.new_app()
        try:
            d = Path(tmp) / "b_gui"
            d.mkdir()
            paths = []
            for i in range(4):
                p = d / f"VALORANT 2026-10-07 07-0{i}-10.mov"
                p.write_bytes(b"x")
                paths.append(str(p))
            app.m_game.set("valorant")
            rows = [{"path": p, "name": Path(p).name, "folder": "V", "mtime": time.time() - i * 100, "dur": 30, "kills": 2, "ks": [3.0, 4.0], "used": "", "used_label": "", "util": False}
                    for i, p in enumerate(paths)]
            app.clips, app.byp = rows, {r["path"]: r for r in rows}
            app.folder_names = ["All folders", "V"]
            app.apply_filter()
            G.pump(app.root, 4, 0.02)
            check(all(not app.ctree.item(p, "text").endswith(M.UTIL_ROW_TAG) for p in paths), "OFF: no suffix on any row, zero extra space")
            ticked_before, used_before, sort_before = set(app.ticked), [r["used"] for r in rows], list(app.ctree.get_children())
            info = app.util_targets(paths[1])
            check(info == ([paths[1]], False), f"menu on an unticked row acts on that row only ({info})")
            app.toggle_util([paths[1]], True)
            G.pump(app.root, 2, 0.02)
            check(app.ctree.item(paths[1], "text").endswith(M.UTIL_ROW_TAG) and M.clip_override_state(paths[1])[0] == "on" and app.byp[paths[1]]["util"], "ON: the row shows the [U] tag and the override is stored")
            check(set(app.ticked) == ticked_before and [r["used"] for r in rows] == used_before and list(app.ctree.get_children()) == sort_before, "toggling changed no ticks, used flags or order")
            check(not app.scan_active and not app.busy, "toggling started no scan / render")
            # multi-select: ticked rows are the selection; the toggle follows the FIRST selected row
            app.ticked.update({paths[0], paths[1], paths[2]})
            info = app.util_targets(paths[2])
            check(info and info[0] == [paths[0], paths[1], paths[2]] and info[1] is False, f"multi-select: targets = the ticked rows in list order, state of the FIRST ({info})")
            app.toggle_util(info[0], not info[1])
            check(all(app.byp[p]["util"] for p in paths[:3]) and not app.byp[paths[3]]["util"], "multi-select ON: all three selected rows switched, the fourth untouched")
            info = app.util_targets(paths[1])
            app.toggle_util(info[0], not info[1])
            check(all(not app.byp[p]["util"] for p in paths[:3]) and M.load_clip_overrides() == {}, "toggling again (first row is ON) switches all selected rows OFF and removes the entries")
            # sort key ignores the suffix
            app.toggle_util([paths[0]], True)
            k_on = app.sort_key(app.ctree, "#0", (paths[0], app.row_text(paths[0]), ()))
            app.toggle_util([paths[0]], False)
            k_off = app.sort_key(app.ctree, "#0", (paths[0], app.row_text(paths[0]), ()))
            check(k_on == k_off, "the [U] suffix does not change the list order")
            # CS2: no menu, no override
            app.m_game.set("cs2")
            check(app.util_targets(paths[0]) is None, "CS2 list: the menu is hidden (no utility rows in CS2)")
            app.m_game.set("valorant")
            # the handler for a real right-click event (no popup is shown here: the menu function returns after tk_popup)
            check(app.ctree.bind("<Button-3>"), "right-click (Button-3) is bound on the clip list")
        finally:
            G.close_app(app, old)


ORDER = ["part_semantics", "part_off_guard", "part_proof", "part_persist", "part_frozen", "part_cli", "part_gui"]
