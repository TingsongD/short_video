"""Minimal 16-bit PCM/WAV utilities for F20: real bytes, exact sample
counts, deterministic output. Mono 16-bit only at this layer — stereo
widening happens by duplication at write time.
"""
import io
import math
import struct
import wave

RATE = 22050


def read_wav(data):
    """→ (rate, [int16 samples])."""
    with wave.open(io.BytesIO(data), "rb") as w:
        assert w.getsampwidth() == 2, "16-bit PCM only"
        frames = w.readframes(w.getnframes())
        samples = list(struct.unpack(f"<{len(frames)//2}h", frames))
        if w.getnchannels() == 2:
            samples = [(samples[i] + samples[i + 1]) // 2
                       for i in range(0, len(samples), 2)]
        return w.getframerate(), samples


def write_wav(samples, rate=RATE, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        if channels == 2:
            out = []
            for s in samples:
                out += [s, s]
            samples = out
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buf.getvalue()


def gain_db(samples, db):
    f = 10 ** (db / 20.0)
    return [max(-32768, min(32767, int(round(s * f)))) for s in samples]


def overlay(base, add, offset_samples):
    out = list(base)
    if len(out) < offset_samples + len(add):
        out += [0] * (offset_samples + len(add) - len(out))
    for i, s in enumerate(add):
        v = out[offset_samples + i] + s
        out[offset_samples + i] = max(-32768, min(32767, v))
    return out


def crossfade(a, b, n):
    """Join a→b over n samples (linear), returns combined list."""
    if n <= 0:
        return a + b
    head, tail_a, tail_b = a[:-n] if n <= len(a) else [], \
        a[-n:] if n <= len(a) else a, b[:n]
    m = min(len(tail_a), len(tail_b))
    mid = [int(round(tail_a[i] * (1 - (i + 1) / (m + 1))
                     + tail_b[i] * ((i + 1) / (m + 1))))
           for i in range(m)]
    return head + mid + b[m:]


def measure(samples, rate=RATE):
    """→ {"peak_dbfs","rms_dbfs","clipped","samples","duration_s"} —
    measured facts, not an invented target."""
    if not samples:
        return {"peak_dbfs": None, "rms_dbfs": None, "clipped": False,
                "samples": 0, "duration_s": 0.0}
    peak = max(abs(s) for s in samples)
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    db = lambda v: None if v == 0 else round(20 * math.log10(v / 32768), 2)
    return {"peak_dbfs": db(peak), "rms_dbfs": db(rms),
            "clipped": peak >= 32767, "samples": len(samples),
            "duration_s": round(len(samples) / rate, 4)}


def sine(duration_s, freq=110.0, rate=RATE, amp=9000):
    n = int(duration_s * rate)
    return [int(amp * math.sin(2 * math.pi * freq * i / rate))
            for i in range(n)]
