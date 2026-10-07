"""STAGE 0 - timebase. The renderer decodes the song with `aresample=<sr>,aformat=...,asetpts=N/SR/TB` (no -ss on the input: the music is
trimmed later with atrim on that same timeline), so sample 0 = the first DECODED sample (ffmpeg has already skipped the MP3 encoder delay).
V2 decodes with the same ffmpeg filter chain to a mono float array at a fixed rate; no librosa.load, no other resampler."""
import subprocess

import numpy as np

SR = 22050


def decode(path, sr=SR, timeout=300):
    """Mono float32 samples on the render timebase (identical filter chain to the render's music input)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-af", f"aresample={sr},asetpts=N/SR/TB",
                        "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, timeout=timeout)
    y = np.frombuffer(r.stdout, np.float32).copy()
    if not len(y):
        raise RuntimeError("song could not be decoded: " + r.stderr.decode(errors="replace")[-120:])
    return y, sr


def decode_render_path(path, sr=48000, timeout=300):
    """The render's own music chain (stereo at the render rate, same filters) averaged to mono: used only to verify `decode` is aligned."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-af",
                        f"aresample={sr},aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=N/SR/TB", "-ar", str(sr), "-ac", "2",
                        "-f", "f32le", "-"], capture_output=True, timeout=timeout)
    a = np.frombuffer(r.stdout, np.float32).reshape(-1, 2)
    return a.mean(1), sr
