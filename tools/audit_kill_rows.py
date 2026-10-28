"""V9.1.3 one-off audit (not part of the app): every kill row of mine that the stored kill list lacks, grouped by the rule that dropped it.

    python tools/audit_kill_rows.py scan  --old <montage_old.py> --rows-new <dir> [--part i/n] [--clip <name part>] --out <part.jsonl>
    python tools/audit_kill_rows.py report <part.jsonl> ... [--sheets <dir>]

Run it on a COPY of montage_data (MONTAGER_DATA). `scan` imports two versions of montage.py side by side: the OLD one (the rules before the fix,
reading the existing row sidecars = the kills the planner used) and this checkout's (the rules after the fix; sidecars rebuilt into --rows-new,
the real cs2_rows_v1 is never written). For each cached CS2 / R6S clip it runs a PERMISSIVE row finder that ignores the acceptance rules:

  CS2: every outlined track of the rebuilt tracker (shape filter / row grid ignored, 2+ frames), read with OCR; a track is a row of mine unless my
       name reads on its victim side (an outline marks my kills and assists). Plus every name-scan row with my name (fuzzy) on the killer side.
  R6S: every OCR row track whose killer side fuzzy-matches my name (any frames-seen count, blank victim text allowed).

Each such row not matched to a stored kill is listed with the rule that dropped it (old rules = "before", new rules = "after").
`report` groups the rows by rule, prints before / after totals and the clips whose kill count changes, and (--sheets) writes up to 10
example crops per group (full-width killfeed band at the row's time) for checking on the frames."""
import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GROUPS = {          # rule key -> the user's rule name
    "finder": "row finder (no closed outline found)",
    "name": "name match / not mine",
    "icon": "weapon icon (utility)",
    "frames": "frames-seen minimum",
    "victim": "victim-text rule (death / suspicious read)",
    "pre": "pre-clip rule",
    "dup": "pushed-down / duplicate merge",
    "grid": "row-grid / shape check",
    "lock": "death lock",
    "namekeep": "name-scan row not kept (no border row)",
    "other": "other",
}


def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def rule_of(reason):
    r = (reason or "").lower()
    if "pre-clip" in r or "already on screen at clip start" in r:
        return "pre"
    if "shifted up" in r or "same victim as another row" in r or "same-timestamp" in r or "fragment" in r or "duplicate" in r:
        return "dup"
    if "utility" in r or "gadget" in r:
        return "icon"
    if "seen only" in r or "blip" in r:
        return "frames"
    if "death" in r or "suspicious" in r or "victim side" in r:
        return "victim"
    if "not mine" in r or "other player" in r or "assist" in r or "no readable name" in r:
        return "name"
    if "after my death" in r:
        return "lock"
    return "other"


def death_lock(kills, deaths, lock=8.0):
    keep, out = [], []
    for k in kills:
        if not k.get("util") and not (k.get("border") and k.get("name_read")) and any(d < k["t"] <= d + lock for d in deaths):     # as verified_kills (V9.1.3 CS2_LOCK_ROW_ON)
            out.append(k)
        else:
            keep.append(k)
    return keep, out


def vic_like(M, a, b):
    from rapidfuzz import fuzz
    x, y = M.ocr_norm(a or ""), M.ocr_norm(b or "")
    return bool(x and y and (x == y or M.cs2_same_victim(a, b) or (min(len(x), len(y)) >= 4 and fuzz.ratio(x, y) >= 70)))


def matched(M, row, kills):
    """A stored kill for this row: its time inside the row's life (first - 1.0 .. last), or the same victim within the row's life +- 1.5 s."""
    for k in kills:
        if row["first"] - 1.0 <= k["t"] <= row["last"] + 0.2:
            if not row.get("victim") or not k.get("victim") or k["victim"].startswith("(unread") or vic_like(M, row["victim"], k["victim"]) \
                    or abs(k["t"] - row["first"]) <= 0.4:
                return k
        if row.get("victim") and row["first"] - 1.5 <= k["t"] <= row["last"] + 1.5 and vic_like(M, row["victim"], k.get("victim")):
            return k
    return None


# ------------------------------------------------------------------------------------------------------------------------- CS2
def cs2_stored(M, rec, e, cfg, sc):
    """The kills the planner gets for this clip (analyse_clip_entry + death lock) and the explanation pieces."""
    a = M.analyse_clip_entry(rec, e, cfg, "cs2")
    kills, locked = death_lock(a["kills"], a.get("deaths", []), float(cfg.get("death_lock_s", 8.0)))
    return {"a": a, "kills": kills, "locked": locked}


def cs2_reason(M, row, st, sc, fps):
    """Why the stored list (st) lacks `row`: (rule key, text)."""
    a = st["a"]
    for k in st["locked"]:
        if row["first"] - 1.0 <= k["t"] <= row["last"]:
            return "lock", f"within the death lock after my death ({k['t']:.1f} s)"
    if not a.get("border"):
        for j in a.get("rej", []):
            if row["first"] - 1.0 <= j["t"] <= row["last"]:
                return rule_of(j["reason"]), "name scan: " + j["reason"]
        return ("finder", "no row sidecar and the name scan has no row here") if row["src"] == "border" else ("other", "name scan: not listed")
    near = [d for d in a.get("rows", []) if d["track"]["first"] / fps - 0.5 <= row["first"] <= d["track"]["last"] / fps
            and (abs(d["track"]["first"] / fps - row["first"]) <= 1.0 or vic_like(M, row.get("victim"), d["cls"]["vtext"]))]
    for d in sorted(near, key=lambda d: abs(d["track"]["first"] / fps - row["first"]))[:1]:       # the classified border row of the stored list that IS this row
        if True:
            for j in a.get("rej", []):
                if abs(j["t"] - d["t"]) <= 0.05:
                    return rule_of(j["reason"]), j["reason"]
            if d["cls"]["verdict"] == "kill":
                return "dup", f"border row at {d['t']:.1f} s is a kill but not in the list (stale / same-time / merged)"
            return rule_of(d["cls"]["why"]), d["cls"]["why"]
    tr = sc.get("tracks", []) if sc else []
    rows_t, _ = M.border_shape_filter(tr, int(sc.get("frames", 0)), **M.border_fix_kw(sc)) if sc else ([], [])
    ok = {id(t) for t in rows_t}
    for t in tr:
        if t["first"] / fps - 0.5 <= row["first"] <= t["last"] / fps and id(t) not in ok:
            return "grid", f"outlined track {t['first'] / fps:.1f}-{t['last'] / fps:.1f} s thrown out by the row shape / grid check"
    if row["src"] == "name":
        return "namekeep", "only the name scan has this row; the border list has no row here and the name-keep rule did not add it"
    return "finder", "no outlined track here in the row sidecar (" + ",".join(sorted(row.get("how") or ["closed outline"])) + ")"


def cs2_scan(M, O, rec, e, cfg, args):
    det, det_o = M.Detector("cs2"), O.Detector("cs2")
    fps = float(M.BORDER_FPS)
    sc_old = O.border_load(rec, det_o)
    st_old = cs2_stored(O, rec, e, cfg, sc_old)
    cap = {}

    class AuditTracker(M.BorderTracker):                       # keeps the raw tracks (before the shape filter) for the permissive pass
        def finish(self):
            cap["raw"] = [t for t in self.tracks if t["hits"] >= 2 or t["last"] >= self.n - 2]
            cap["n"] = self.n
            return super().finish()
    real = M.BorderTracker
    M.BorderTracker = AuditTracker
    try:
        sc_new = M.border_build(rec, det, cfg)               # written into --rows-new (M.BORDER_DIR was moved there)
    finally:
        M.BorderTracker = real
    st_new = cs2_stored(M, rec, e, cfg, sc_new)
    rows = []
    a_new = st_new["a"]
    if a_new.get("border"):
        for d in a_new["rows"]:                               # every classified row of the new list, whatever its verdict
            t, c = d["track"], d["cls"]
            if c["verdict"] == "death" or (c["verdict"] == "none" and not c["sus"]):
                continue
            rows.append({"src": "border", "first": t["first"] / fps, "last": t["last"] / fps, "victim": c["vtext"], "killer": c["ktext"],
                         "verdict": c["verdict"], "frames": t["hits"], "x0": t["x0"]})
    kept = {id(t) for t in M.border_shape_filter(cap.get("raw", []), cap.get("n", 0), fix=M.BORDER_FIX)[0]}
    for t in cap.get("raw", []):                              # tracks the shape filter dropped: read them permissively
        h, w = t["y1"] - t["y0"], t["x1"] - t["x0"]
        if id(t) in kept or not (M.BORDER_H[0] <= h <= M.BORDER_H[1] and w >= 3 * h) or not t["crops"]:
            continue
        if any(r["first"] - 0.3 <= t["first"] / fps <= r["last"] for r in rows):
            continue
        q, f, crop, rc = max(t["crops"].values(), key=lambda c: c[0])
        boxes, blobs = M.border_ocr(crop)
        c = M.cs2_classify_track({"votes": [{"f": f, "q": q, "boxes": boxes, "blobs": blobs}], "x0": t["x0"]}, cfg)
        if c["verdict"] in ("death",):
            continue
        rows.append({"src": "border", "first": t["first"] / fps, "last": t["last"] / fps, "victim": c["vtext"], "killer": c["ktext"],
                     "verdict": c["verdict"] + " (blob)", "frames": t["hits"], "x0": t["x0"]})
    for src_a in (st_old["a"].get("old") or st_old["a"], a_new.get("old") or a_new):      # the name scan's rows with my name on the killer side
        for m in src_a.get("mine", []):
            kt = (m.get("row") or "")[1:].split("]")[0]
            if m.get("verdict") == "kill" or (M.name_match(kt, "cs2")[0] >= 60 or M.cs2_lenient_me(kt)):
                if "death" in (m.get("why") or "").lower() and m.get("verdict") != "kill":
                    continue
                if any(r["first"] - 1.0 <= m["t"] <= r["last"] for r in rows):
                    continue
                vt = (m.get("row") or "").rsplit("[", 1)[-1].rstrip("]")
                rows.append({"src": "name", "first": m["t"], "last": m["t"] + 1.0, "victim": vt, "killer": kt, "verdict": "name " + m.get("verdict", ""),
                             "frames": m.get("hits", 0)})
    res = []
    for r in sorted(rows, key=lambda r: r["first"]):
        r = dict(r, first=round(r["first"], 3), last=round(r["last"], 3))
        ko, kn = matched(M, r, st_old["kills"]), matched(M, r, st_new["kills"])
        if ko is None:
            r["before"] = cs2_reason(O, r, st_old, sc_old, fps)
        elif r["src"] == "border" and ko["t"] - r["first"] > 0.5:
            r["before_late"] = round(ko["t"] - r["first"], 2)          # kept, but dated later than its row appears
        if kn is None:
            r["after"] = cs2_reason(M, r, st_new, sc_new, fps)
        elif r["src"] == "border" and kn["t"] - r["first"] > 0.5:
            r["after_late"] = round(kn["t"] - r["first"], 2)
        res.append(r)
    return {"game": "cs2", "clip": Path(rec["path"]).name, "path": rec["path"], "dur": rec.get("dur"), "rows": res,
            "old": [[round(k["t"], 3), k.get("victim")] for k in st_old["kills"]], "new": [[round(k["t"], 3), k.get("victim")] for k in st_new["kills"]],
            "old_ext": (sc_old or {}).get("ext"), "secs": sc_new.get("secs")}


# ------------------------------------------------------------------------------------------------------------------------- R6S
def r6s_scan(M, O, rec, e, cfg):
    from rapidfuzz import fuzz
    a_old, a_new = O.r6s_safe_analyse(e, cfg), M.r6s_safe_analyse(e, cfg)
    ko_, _ = death_lock(a_old["kills"], a_old["deaths"], float(cfg.get("death_lock_s", 8.0)))
    kn_, _ = death_lock(a_new["kills"], a_new["deaths"], float(cfg.get("death_lock_s", 8.0)))
    fpsr = float(M.FPS)
    rows = []
    for r in M.r6s_rows_from_ocr(e) if e.get("ocr") else []:
        best = 0.0
        kt = vt = ""
        vbest = 0.0
        for _f, left, right in r.get("reads", []):
            k_, v_ = " ".join(str(b[2]) for b in left), " ".join(str(b[2]) for b in right)
            s = max([M.r6s_name_score(b[2]) for b in left] or [0.0])
            if s > best:
                best, kt, vt = s, k_, v_
            vbest = max([vbest] + [M.r6s_name_score(b[2]) for b in right])
        if best < 60 or vbest >= 80:
            continue
        rows.append({"src": "ocr", "first": round(r["first"] / fpsr, 3), "last": round(r["last"] / fpsr, 3), "victim": vt, "killer": kt,
                     "verdict": f"name {best:.0f}", "frames": r["hits"]})
    res = []
    for r in rows:
        for lab, a, ks in (("before", a_old, ko_), ("after", a_new, kn_)):
            if matched(M, r, ks) is None:
                why = next((j["reason"] for j in a["rej"] if r["first"] - 0.6 <= j["t"] <= r["last"]), None)
                if why is None and any(r["first"] - 1.0 <= k["t"] <= r["last"] for k in a["kills"]):
                    why = "after my death"
                r[lab] = (rule_of(why), why) if why else ("name", "my name read below the kill threshold on every read")
        res.append(r)
    return {"game": "r6s", "clip": Path(rec["path"]).name, "path": rec["path"], "dur": rec.get("dur"), "rows": res,
            "old": [[round(k["t"], 3), k.get("victim")] for k in ko_], "new": [[round(k["t"], 3), k.get("victim")] for k in kn_]}


def cmd_scan(args):
    M = load_mod("montage", str(ROOT / "montage.py"))
    O = load_mod("montage_old", args.old)
    for m_ in (M, O):                                     # several audit processes side by side: a few OCR threads each
        def eng(m_=m_):
            if getattr(m_._OCR, "e", None) is None:
                from rapidocr_onnxruntime import RapidOCR
                m_._OCR.e = RapidOCR(intra_op_num_threads=args.threads, inter_op_num_threads=1)
            return m_._OCR.e
        m_.ocr_engine = eng
    M.BORDER_DIR = Path(args.rows_new)
    M.BORDER_DIR.mkdir(parents=True, exist_ok=True)
    cfg = M.load_config()
    cache = M.load_kills_cache()
    recs = [r for r in M.scan_clips(cfg) if r.get("game") in args.games and not r.get("error") and r.get("w")]
    if args.clip:
        recs = [r for r in recs if any(c in Path(r["path"]).name for c in args.clip)]
    i, n = (int(x) for x in args.part.split("/"))
    recs = [r for k, r in enumerate(sorted(recs, key=lambda r: r["path"])) if k % n == i]
    done = set()
    if os.path.exists(args.out):
        for l in open(args.out, encoding="utf-8"):
            try:
                done.add(json.loads(l)["path"])
            except Exception:
                pass
    with open(args.out, "a", encoding="utf-8") as fo:
        for k, r in enumerate(recs, 1):
            if r["path"] in done:
                continue
            g = r["game"]
            det = M.Detector(g)
            e = cache.get(M.kills_key(r, g, det))
            if not e or e.get("error"):
                continue
            t0 = time.time()
            try:
                d = cs2_scan(M, O, r, e, cfg, args) if g == "cs2" else r6s_scan(M, O, r, e, cfg)
            except Exception as ex:                       # noqa: BLE001
                d = {"game": g, "clip": Path(r["path"]).name, "path": r["path"], "error": f"{type(ex).__name__}: {ex}"}
            d["audit_secs"] = round(time.time() - t0, 1)
            fo.write(json.dumps(d, ensure_ascii=False) + "\n")
            fo.flush()
            print(f"[{i}/{n}] {k}/{len(recs)} {d['clip']}: old {len(d.get('old', []))} new {len(d.get('new', []))} ({d['audit_secs']} s)", flush=True)


# ------------------------------------------------------------------------------------------------------------------------- report
def cmd_report(args):
    ds = []
    for p in args.parts:
        for l in open(p, encoding="utf-8"):
            try:
                ds.append(json.loads(l))
            except ValueError:
                pass
    by = {}
    for d in ds:
        by[d["path"]] = d                                  # the newest line of a clip wins
    ds = list(by.values())
    M = load_mod("montage", str(ROOT / "montage.py"))
    noise = 0
    for d in ds:                                          # report-time clean-up: (a) a red blob with no readable text is not a row of anyone; (b) a stored kill of the
        keep = []                                         # same victim dated up to 4 s before the tracked row (rows entering at the region's lower edge are tracked late) IS that row
        for r in d.get("rows", []):
            if r["src"] == "border" and not M._alnum(r.get("killer") or "") and not M._alnum(r.get("victim") or ""):
                noise += 1
                continue
            for lab, ks in (("before", d.get("old", [])), ("after", d.get("new", []))):
                if lab in r and r.get("victim") and any(r["first"] - 4.0 <= t <= r["last"] and vic_like(M, r["victim"], v) for t, v in ks):
                    r.pop(lab)
            keep.append(r)
        d["rows"] = keep
    lines = [f"red blobs without any readable text (not a killfeed row, left out): {noise}",
             f"kill-row audit: {len(ds)} clips ({sum(d['game'] == 'cs2' for d in ds)} CS2, {sum(d['game'] == 'r6s' for d in ds)} R6S), "
             f"errors {sum(1 for d in ds if d.get('error'))}"]
    for lab in ("before", "after"):
        cnt = {}
        for d in ds:
            for r in d.get("rows", []):
                if lab in r:
                    cnt.setdefault((d["game"], r[lab][0]), []).append(r)
        lines.append(f"\nunmatched rows of mine {lab.upper()} the fix, by rule:")
        for (g, k), v in sorted(cnt.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
            lines.append(f"  {g:4} {GROUPS.get(k, k):45} {len(v):5}")
    for lab in ("before", "after"):
        late = [(d, r) for d in ds for r in d.get("rows", []) if r.get(lab + "_late")]
        lines.append(f"rows kept but dated > 0.5 s after the row appears ({lab}): {len(late)}"
                     + "".join(f"\n    {d['clip'][:60]} row {r['first']:.2f} s, kill {r['first'] + r[lab + '_late']:.2f} s" for d, r in late[:40]))
    ch = [d for d in ds if not d.get("error") and len(d["old"]) != len(d["new"])]
    lines.append(f"\nclips whose kill count changes: {len(ch)}")
    for d in sorted(ch, key=lambda d: (d["game"], d["clip"])):
        lines.append(f"  {d['game']:4} {d['clip'][:70]:70} {len(d['old'])} -> {len(d['new'])}   old {[k[0] for k in d['old']]}  new {[k[0] for k in d['new']]}")
    tm = [d for d in ds if not d.get("error") and len(d["old"]) == len(d["new"]) and any(abs(a[0] - b[0]) > 0.3 for a, b in zip(d["old"], d["new"]))]
    lines.append(f"\nclips with the same count but a kill time moved > 0.3 s: {len(tm)}")
    for d in sorted(tm, key=lambda d: d["clip"]):
        lines.append(f"  {d['game']:4} {d['clip'][:70]:70} old {[k[0] for k in d['old']]}  new {[k[0] for k in d['new']]}")
    for lab in ("before", "after"):
        lines.append(f"\nEXAMPLES {lab.upper()} (per rule, all rows):")
        for d in sorted(ds, key=lambda d: d["clip"]):
            for r in d.get("rows", []):
                if lab in r:
                    lines.append(f"  [{r[lab][0]:8}] {d['game']} {d['clip'][:60]:60} {r['first']:6.2f}-{r['last']:6.2f} {r['src']:6} '{r.get('killer', '')}' > '{r.get('victim', '')}' "
                                 f"({r.get('verdict')}, {r.get('frames')} f): {r[lab][1]}")
    txt = "\n".join(lines)
    Path(args.txt).write_text(txt, encoding="utf-8")
    print("\n".join(lines[:60]))
    if args.sheets:
        sheets(ds, args)


def sheets(ds, args):
    """Up to 10 example rows per rule (before the fix): one full-width killfeed band per row at a frame 0.5 s into the row."""
    import subprocess
    import cv2
    import numpy as np
    out = Path(args.sheets)
    out.mkdir(parents=True, exist_ok=True)
    groups = {}
    for d in ds:
        for r in d.get("rows", []):
            if "before" in r:
                groups.setdefault((d["game"], r["before"][0]), []).append((d, r))
    for (g, k), v in groups.items():
        step = max(1, len(v) // 10)
        tiles = []
        for d, r in v[::step][:10]:
            t = min(r["first"] + 0.5, max(r["first"], r["last"] - 0.1))
            p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", d["path"], "-frames:v", "1", "-vf",
                                "crop=iw*0.55:ih*0.32:iw*0.45:0,scale=960:-2", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
            img = cv2.imdecode(np.frombuffer(p.stdout, np.uint8), cv2.IMREAD_COLOR) if p.stdout else None
            if img is None:
                continue
            lab = f"{d['clip'][:46]} @{t:.2f} '{r.get('killer', '')[:16]}'>'{r.get('victim', '')[:16]}'"
            cv2.rectangle(img, (0, img.shape[0] - 26), (img.shape[1], img.shape[0]), (0, 0, 0), -1)
            cv2.putText(img, lab, (4, img.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            tiles.append(img)
        if tiles:
            w = max(t.shape[1] for t in tiles)
            tiles = [cv2.copyMakeBorder(t, 0, 4, 0, w - t.shape[1], cv2.BORDER_CONSTANT) for t in tiles]
            cv2.imencode(".png", np.vstack(tiles))[1].tofile(str(out / f"{g}_{k}.png"))
            print(f"sheet {g}_{k}.png: {len(tiles)} of {len(v)} rows")


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("scan")
    s.add_argument("--old", required=True)
    s.add_argument("--rows-new", required=True)
    s.add_argument("--part", default="0/1")
    s.add_argument("--clip", nargs="*")
    s.add_argument("--games", nargs="*", default=["cs2", "r6s"])
    s.add_argument("--out", required=True)
    s.add_argument("--threads", type=int, default=2)
    s.set_defaults(fn=cmd_scan)
    r = sp.add_parser("report")
    r.add_argument("parts", nargs="+")
    r.add_argument("--txt", default="audit_kill_rows.txt")
    r.add_argument("--sheets")
    r.set_defaults(fn=cmd_report)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
