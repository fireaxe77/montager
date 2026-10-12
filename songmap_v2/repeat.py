"""V7.6.1: drops found by REPEATED PATTERN. Identical repeated sections of a song have identical build-ups, so a known drop (labelled or confidently detected) is a template:
about 8 s before to 2 s after it, the energy envelope, the onset density and the band energies. The same pattern elsewhere is the same drop, refined to the sample by waveform
correlation. ADDITIVE: this module only ever returns NEW drops; it never removes or moves a known one.

    find_repeat_drops(y, sr, known_times) -> [{"t": seconds, "conf": 0..1, "from": known drop time, "ncc": ..., "wave": ...}]
"""
import numpy as np

HOP = 512
PRE_S, POST_S = 8.0, 2.0
MIN_SEP_S = 10.0                    # candidates closer than this to each other / to a known drop are the same place
NCC_MIN = 0.80                      # pattern correlation needed to be a candidate
WAVE_MIN = 0.35                     # waveform correlation needed for the sample-accurate refinement
STRETCH = (1.0, 0.985, 1.015)       # tolerance to a small tempo drift between the two places


def features(y, sr):
    """(T x 5) frame features at HOP: low / mid / high band log-energy, RMS (dB), onset density (spectral flux), smoothed over 3 frames."""
    import librosa
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=HOP)) ** 2
    fr = librosa.fft_frequencies(sr=sr, n_fft=2048)
    band = lambda lo, hi: 10 * np.log10(S[(fr >= lo) & (fr < hi)].sum(axis=0) + 1e-10)
    F = [band(30, 150), band(150, 2000), band(2000, 8000), 10 * np.log10(S.sum(axis=0) + 1e-10)]
    flux = np.maximum(0, np.diff(np.log1p(np.sqrt(S)), axis=1, prepend=np.log1p(np.sqrt(S[:, :1])))).sum(axis=0)
    F.append(flux)
    F = np.stack(F, axis=1)
    k = np.ones(3) / 3
    return np.stack([np.convolve(F[:, i], k, mode="same") for i in range(F.shape[1])], axis=1)


def _ncc_track(F, ref):
    """Pearson correlation of the reference window `ref` (L x 5) with every window of F (per feature, averaged)."""
    L = ref.shape[0]
    T = F.shape[0]
    if T < L + 2:
        return np.zeros(0)
    out = np.zeros(T - L + 1)
    for i in range(F.shape[1]):
        r = ref[:, i] - ref[:, i].mean()
        rn = np.sqrt((r ** 2).sum()) + 1e-9
        x = F[:, i]
        n = 1
        while n < T + L:
            n *= 2
        c = np.fft.irfft(np.fft.rfft(x, n) * np.conj(np.fft.rfft(r, n)), n)[:T - L + 1]
        cs = np.concatenate([[0], np.cumsum(x)])
        cs2 = np.concatenate([[0], np.cumsum(x ** 2)])
        s1 = cs[L:L + T - L + 1] - cs[:T - L + 1]
        s2 = cs2[L:L + T - L + 1] - cs2[:T - L + 1]
        var = np.maximum(s2 - s1 ** 2 / L, 1e-9)
        out += c / (rn * np.sqrt(var))
    return out / F.shape[1]


def _stretch(ref, f):
    L = ref.shape[0]
    n = max(8, int(round(L * f)))
    idx = np.linspace(0, L - 1, n)
    return np.stack([np.interp(idx, np.arange(L), ref[:, i]) for i in range(ref.shape[1])], axis=1)


def snap_to_onset(y, sr, t, win=0.4):
    """The strongest low-band (35-130 Hz) attack within +-win s of t: the kick that IS the drop (a hand label or a map time is only good to a few tenths of a second)."""
    import librosa
    a, b = max(0, int((t - win - 0.05) * sr)), min(len(y), int((t + win + 0.05) * sr))
    if b - a < 2048:
        return float(t)
    S = np.abs(librosa.stft(y[a:b], n_fft=1024, hop_length=64)) ** 2
    fr = librosa.fft_frequencies(sr=sr, n_fft=1024)
    lo = 10 * np.log10(S[(fr >= 35) & (fr <= 130)].sum(axis=0) + 1e-10)
    rise = np.maximum(0, np.diff(lo, prepend=lo[0]))
    k = np.convolve(rise, np.ones(3) / 3, mode="same")
    tt = a / sr + np.arange(len(k)) * 64 / sr
    m = (tt >= t - win) & (tt <= t + win)
    if not m.any():
        return float(t)
    return float(tt[m][int(np.argmax(k[m]))])


def _refine(y, sr, ref_t, cand_t, search=0.12):
    """Sample-accurate drop time near cand_t: waveform correlation of 0.9 s around the known drop with the same stretch of the candidate. Returns (t, correlation)."""
    a0, a1 = int((ref_t - 0.3) * sr), int((ref_t + 0.6) * sr)
    if a0 < 0 or a1 > len(y):
        return cand_t, 0.0
    ref = y[a0:a1].astype(np.float64)
    ref -= ref.mean()
    rn = np.sqrt((ref ** 2).sum()) + 1e-9
    sh = int(search * sr)
    c0 = int(cand_t * sr) - int(0.3 * sr)
    best = (-1.0, 0)
    for lag in range(-sh, sh + 1, 4):                       # coarse (4 samples), then fine
        j = c0 + lag
        if j < 0 or j + len(ref) > len(y):
            continue
        seg = y[j:j + len(ref)].astype(np.float64)
        seg = seg - seg.mean()
        c = float(np.dot(ref, seg) / (rn * (np.sqrt((seg ** 2).sum()) + 1e-9)))
        if c > best[0]:
            best = (c, lag)
    for lag in range(best[1] - 4, best[1] + 5):
        j = c0 + lag
        if j < 0 or j + len(ref) > len(y):
            continue
        seg = y[j:j + len(ref)].astype(np.float64)
        seg = seg - seg.mean()
        c = float(np.dot(ref, seg) / (rn * (np.sqrt((seg ** 2).sum()) + 1e-9)))
        if c > best[0]:
            best = (c, lag)
    return cand_t + best[1] / sr, best[0]


def find_repeat_drops(y, sr, known, F=None, ncc_min=NCC_MIN, wave_min=WAVE_MIN, snap=False):
    """New drops from the patterns of the known drop times `known` (seconds). Never returns a time within MIN_SEP_S of a known drop or of another returned drop."""
    known = sorted(float(t) for t in known)
    if not known:
        return []
    F = features(y, sr) if F is None else F
    fps = sr / HOP
    L0 = int((PRE_S + POST_S) * fps)
    found = []
    for kt in known:
        f0 = int(round((kt - PRE_S) * fps))
        if f0 < 0 or f0 + L0 > F.shape[0]:
            continue
        snap_off = snap_to_onset(y, sr, kt) - kt if snap else 0.0     # label -> the actual kick (the pattern offset is then exact for the kick)
        for st in STRETCH:
            ref = F[f0:f0 + L0]
            ref = ref if st == 1.0 else _stretch(ref, st)
            tr = _ncc_track(F, ref)
            if not len(tr):
                continue
            Lr = ref.shape[0]
            # local maxima above the threshold
            pk = [i for i in range(1, len(tr) - 1) if tr[i] >= ncc_min and tr[i] >= tr[i - 1] and tr[i] >= tr[i + 1]]
            for i in pk:
                cand = (i + PRE_S * fps * (Lr / L0)) / fps + snap_off     # the template's kick, found in the candidate
                if any(abs(cand - k2) < MIN_SEP_S for k2 in known):
                    continue
                found.append((float(tr[i]), cand, kt, st))
    found.sort(key=lambda x: -x[0])
    out, taken = [], list(known)
    for ncc, cand, kt, st in found:
        if any(abs(cand - t) < MIN_SEP_S for t in taken):
            continue
        t_ref, wc = _refine(y, sr, kt + (cand - 0.0) * 0 + (snap_to_onset(y, sr, kt) - kt if snap else 0.0), cand)
        if wc >= wave_min:
            cand_final, how = t_ref, "waveform"
        else:
            cand_final, how = cand, "pattern"
        conf = float(max(0.0, min(1.0, 0.6 * ncc + 0.4 * max(0.0, wc) + (0.0 if how == "waveform" else -0.15))))
        out.append({"t": round(cand_final, 4), "conf": round(conf, 3), "from": round(kt, 3), "ncc": round(ncc, 3), "wave": round(wc, 3), "how": how})
        taken.append(cand_final)
    return out
