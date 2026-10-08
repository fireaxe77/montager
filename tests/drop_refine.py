"""Independent drop-onset refiner (V7.4.5). NOT imported by songmap_v2. For a typed label it finds the nearest real drop onset within +-1.0 s on
render-timebase audio: the time where the low band (20-150 Hz) steps up after a break / build (largest dB step of the next 0.5 s vs the previous 0.5 s),
then the strongest low-band attack within +-0.25 s of that step. No beat grid, no V2 code."""
import numpy as np
from scipy.signal import butter, sosfiltfilt

HOP = 0.01
STEP_DB_MIN = 5.0


def low_env(y, sr):
    y = np.asarray(y, np.float64)
    low = sosfiltfilt(butter(4, [20, 150], "band", fs=sr, output="sos"), y)
    n = int(HOP * sr)
    m = len(low) // n
    e = np.sqrt((low[:m * n].reshape(m, n) ** 2).mean(1) + 1e-12)
    return e


def refine(env, t, win=1.0, span=0.4):
    """(refined_time or None, step_db). env = low_env(). Among the steps within 70 % of the strongest one (and >= STEP_DB_MIN) the one nearest the typed time wins."""
    k = int(round(span / HOP))
    lo, hi = int(round((t - win) / HOP)), int(round((t + win) / HOP))
    steps = []
    for c in range(max(lo, k), min(hi, len(env) - k)):
        a = float(env[c:c + k].mean())
        b = float(env[c - k:c].mean())
        steps.append((20 * np.log10((a + 1e-9) / (b + 1e-9)), c))
    if not steps:
        return None, 0.0
    top = max(x[0] for x in steps)
    if top < STEP_DB_MIN:
        return None, round(float(top), 1)
    good = [x for x in steps if x[0] >= max(STEP_DB_MIN, 0.7 * top)]
    step, c = min(good, key=lambda x: (abs(x[1] * HOP - t), -x[0]))
    d = np.diff(env, prepend=env[0])
    a, b = max(0, c - 15), min(len(d), c + 16)
    j = a + int(np.argmax(d[a:b]))
    return round(j * HOP, 2), round(float(step), 1)
