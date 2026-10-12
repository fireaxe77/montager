"""V7.6.1 detector-independent timing audit of a REAL render (video file + its .plan.json).
 - VIDEO: for every kill in a 1.0x segment the output frame 8 frames before the planned kill frame (before any zoom punch) is matched against the source frames around
   the planned source time; the best match gives the frame error of the render (0 = the frame the plan says).
 - AUDIO: the music is subtracted from the rendered mix (least squares on its clean copy, aligned by cross-correlation) and the residual (= game audio) is cross-correlated with
   the source clip's own audio around the kill: the lag in ms is the render error of the gunshot; planned drop error (plan drop_sync) + that lag = error of the sound on the drop.
 - MUSIC DRIFT: the song's offset in the file at the start, middle and end of the montage.
   python tests\\audit761.py <montage.mp4> [<plan.json>]"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "montage.py").exists() else HERE.parent
sys.path.insert(0, str(ROOT))
import numpy as np                                                                            # noqa: E402

SR = 48000


def dec_audio(path, ss=None, t=None, stream=0, sr=SR):
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", f"{ss:.4f}"] if ss is not None else []) + ["-i", str(path)] + (["-t", f"{t:.4f}"] if t else []) + \
          ["-map", f"0:a:{stream}", "-ac", "1", "-af", f"aresample={sr},asetpts=N/SR/TB", "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.float32).astype(np.float64)


def gray_frames(path, ss, d, fps, w=256, h=144):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, ss):.4f}", "-t", f"{d:.4f}", "-i", str(path), "-an", "-vf", f"fps={fps},scale={w}:{h}:flags=bilinear,format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h * w).astype(np.float32)


def out_frame(video, n, w=256, h=144):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{n / 60.0:.5f}", "-i", str(video), "-an", "-frames:v", "1", "-vf", f"scale={w}:{h}:flags=bilinear,format=gray", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).astype(np.float32) if len(raw) == w * h else None


def src_of(take, si):
    srcs = take.get("srcs") or [{"path": take["path"], "shift": 0.0, "a_stream": 0}]
    return srcs[si if si < len(srcs) else 0]


def locate(take, k):
    """(segment, index into srcs, source-local time) of the kill's source time k, or None."""
    for s in take["segs"]:
        if s[0] - 1e-6 <= k <= s[1] + 1e-6:
            return s
    return None


def music_offsets(video, plan, n_win=3, dur=6.0, sr=12000):
    """Offset (s) of the song in the file at n_win positions (positive = later than planned)."""
    song = plan["song"]["path"]
    st = plan["song"]["start_t"]
    D = plan["duration"]
    full = dec_audio(song, sr=sr)
    res = []
    for w in range(n_win):
        t0 = 1.0 + (D - dur - 4.0) * w / max(1, n_win - 1)
        o = dec_audio(video, ss=t0, t=dur, sr=sr)
        i0 = int(round((st + t0) * sr))
        ref = full[max(0, i0 - int(0.2 * sr)): i0 + len(o) + int(0.2 * sr)]
        base = i0 - max(0, i0 - int(0.2 * sr))
        best = (-1e18, 0)
        for lag in range(-int(0.06 * sr), int(0.06 * sr) + 1):
            j = base + lag
            if j < 0 or j + len(o) > len(ref):
                continue
            c = float(np.dot(o, ref[j:j + len(o)]))
            if c > best[0]:
                best = (c, lag)
        res.append((t0, -best[1] / sr))
    return res


def xcorr_lag(a, b, max_lag):
    """Lag (samples) of `a` relative to `b` (positive: a is later), 'whitened' correlation, search within +-max_lag."""
    n = 1
    while n < len(a) + len(b):
        n *= 2
    A, B = np.fft.rfft(a, n), np.fft.rfft(b, n)
    X = A * np.conj(B)
    X /= np.abs(X) + 1e-9 * np.abs(X).max()
    c = np.fft.irfft(X, n)
    c = np.concatenate([c[-max_lag:], c[:max_lag + 1]])
    i = int(np.argmax(c))
    peak = float(c[i])
    srt = np.sort(c)
    return i - max_lag, peak, float(srt[-2]) if len(srt) > 1 else 0.0


def audit(video, plan, quiet=False):
    video = str(video)
    D = plan["duration"]
    mo = music_offsets(video, plan)
    mo0 = mo[0][1]
    out_a = dec_audio(video)
    song = dec_audio(plan["song"]["path"])
    st = plan["song"]["start_t"]
    rows = []
    cache = {}
    for ti, t in enumerate(plan["takes"]):
        for ki, k in enumerate(t["kills"]):
            sg = locate(t, k)
            if sg is None:
                continue
            a, b, sp, n = sg[:4]
            si = sg[4] if len(sg) > 4 else 0
            src = src_of(t, si)
            o = (sg_out := None)
            # output time of the kill
            off = 0.0
            for s2 in t["segs"]:
                if s2 is sg or s2 == sg:
                    break
                off += s2[3] / 60.0
            o_t = off + ((k - a) / sp if sp > 0 else 0.0)
            e = t["f0"] + int(round(o_t * 60))
            row = {"take": ti + 1, "kill": ki + 1, "speed": sp, "planned_out_s": e / 60.0, "v_err_frames": None, "a_lag_ms": None, "a_conf": None}
            if abs(sp - 1.0) > 1e-6 or a - src["shift"] < 0.4:
                rows.append(row)
                continue
            path = src["path"]
            # VIDEO
            m = 8
            if o_t - off >= m / 60.0 + 0.05 and not any(p - 0.05 <= (e - m) / 60.0 - t["f0"] / 60.0 <= p + 0.5 for p in t.get("pulses", [])):
                fr = out_frame(video, e - m)
                kk = (k - m / 60.0) - src["shift"]
                if fr is not None:
                    try:
                        fps = 120
                        sf = gray_frames(path, kk - 0.25, 0.5, fps)
                        d = np.abs(sf - fr[None, :]).mean(axis=1)
                        j = int(np.argmin(d))
                        lag_src = (kk - 0.25 + j / fps) - kk
                        row["v_err_frames"] = round(-lag_src * 60.0, 2)          # + = the render shows an EARLIER source moment than planned (picture late)
                        row["v_diff"] = round(float(d[j]), 2)
                    except Exception as ex:                                      # pragma: no cover
                        row["v_err_frames"] = None
            # AUDIO
            if t.get("audio") or src.get("audio"):
                try:
                    w0, w1 = 0.45, 0.45
                    seg_t0 = e / 60.0 - w0
                    if seg_t0 >= 0 and e / 60.0 + w1 < D - 0.1 and k - src["shift"] - w0 >= 0:
                        i0 = int(round(seg_t0 * SR))
                        n_ = int((w0 + w1) * SR)
                        seg = out_a[i0:i0 + n_]
                        mus = song[int(round((st + seg_t0 - mo0) * SR)): int(round((st + seg_t0 - mo0) * SR)) + n_]
                        if len(mus) == len(seg) == n_:
                            g = float(np.dot(seg, mus) / (np.dot(mus, mus) + 1e-12))
                            resid = seg - g * mus
                            key = (path, src.get("a_stream") or 0)
                            # reference: the source decoded EXACTLY like the render does (input seek to the segment start, timestamps as the file has them), so only the
                            # filter chain / encoder / muxer can show up as a lag. (A decode from 0 counted in samples differs by the recorder's own audio timestamp jitter,
                            # up to +-22 ms in real DVR clips - that is the source, not the render.)
                            s0 = max(0.0, a - src["shift"])
                            ck = (path, key[1], round(s0, 4))
                            if ck not in cache:
                                cache[ck] = dec_audio(path, ss=s0, t=(b - a) + 0.35, stream=key[1])
                            j0 = int(round((k - a - w0) * SR))
                            ref = cache[ck]
                            if j0 < 0:
                                sa = np.concatenate([np.zeros(-j0), ref[:n_ + j0]])
                            else:
                                sa = ref[j0:j0 + n_]
                            if len(sa) == n_ and np.abs(sa).max() > 1e-4 and np.abs(resid).max() > 1e-4:
                                lag, pk, second = xcorr_lag(resid, sa, int(0.06 * SR))
                                row["a_lag_ms"] = round(lag / SR * 1000.0, 2)
                                row["a_conf"] = round(pk / (second + 1e-9), 2)
                except Exception:                                                # pragma: no cover
                    pass
            rows.append(row)
    ds = {x["drop"]: x for x in (plan.get("drop_sync") or [])}
    drops = []
    for x in plan.get("drop_sync") or []:
        if not x.get("take"):
            continue
        r = next((q for q in rows if q["take"] == x["take"] and q["kill"] == x["kill"]), None)
        drops.append({"drop": x["drop"], "source": x.get("source"), "planned_err_ms": x.get("err_ms"), "render_audio_lag_ms": None if not r else r["a_lag_ms"],
                      "render_video_frames": None if not r else r["v_err_frames"], "music_offset_ms": round(mo0 * 1000, 2)})
    return {"music_offsets_ms": [(round(t, 1), round(o * 1000, 2)) for t, o in mo], "kills": rows, "drops": drops}


def summarize(res):
    v = [r["v_err_frames"] for r in res["kills"] if r["v_err_frames"] is not None and r.get("v_diff", 0) < 5]
    a = [r["a_lag_ms"] for r in res["kills"] if r["a_lag_ms"] is not None and (r["a_conf"] or 0) >= 1.5]
    s = {"music_offsets_ms": res["music_offsets_ms"], "kills": len(res["kills"]), "video_measured": len(v), "audio_measured": len(a)}
    if v:
        s["video_frames_min_max"] = (min(v), max(v))
        s["video_frames_median"] = float(np.median(v))
    if a:
        s["audio_ms_min_max"] = (min(a), max(a))
        s["audio_ms_median"] = float(np.median(a))
    return s


if __name__ == "__main__":
    vid = Path(sys.argv[1])
    pj = Path(sys.argv[2]) if len(sys.argv) > 2 else vid.parent / "logs" / (vid.stem + ".plan.json")
    plan = json.load(open(pj, encoding="utf-8"))
    res = audit(vid, plan)
    print(json.dumps(summarize(res), default=float))
    for r in res["kills"]:
        print(r)
    for d in res["drops"]:
        print("DROP", d)
