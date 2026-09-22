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
    return [int(round(s * f)) for s in samples]


def overlay(base, add, offset_samples):
    out = list(base)
    if offset_samples < 0 or offset_samples+len(add)>len(out):
        raise ValueError("track_exceeds_allocation")
    for i,s in enumerate(add):
        out[offset_samples+i]+=s
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


def wav_rate(path, default=RATE):
    """Native sample rate of a WAV mix, or `default` for non-WAV media."""
    try:
        with wave.open(str(path), "rb") as w:
            rate = w.getframerate()
            if rate > 0:
                return rate
    except (wave.Error, FileNotFoundError, OSError, EOFError):
        pass
    return default


def samples_at_rate(path, rate, channels=1):
    """PCM at `rate` without resampling a WAV that is already that rate."""
    from pathlib import Path
    if wav_rate(path, 0) == rate:
        try:
            native, samples = read_wav(Path(path).read_bytes())
            if native == rate:
                return samples
        except (AssertionError, wave.Error, OSError, struct.error):
            pass
    return decode(path, rate, channels)


def decode(path, rate=RATE, channels=1):
    """Decode any supported media to interleaved floating-point PCM, at the output clock."""
    import array
    import subprocess
    import sys
    r = subprocess.run(['ffmpeg','-v','error','-i',str(path),'-vn','-ar',str(rate),
                        '-ac',str(channels),'-f','f32le','pipe:1'],capture_output=True,timeout=120)
    if r.returncode:
        raise ValueError('audio_decode_failed')
    values = array.array('f'); values.frombytes(r.stdout)
    if sys.byteorder != 'little':
        values.byteswap()
    return [v * 32768 for v in values]


def resample(samples, source_rate, target_rate):
    """Deterministic linear resampling for already decoded mono fixture samples."""
    if source_rate <= 0 or target_rate <= 0:
        raise ValueError('invalid_sample_rate')
    if source_rate == target_rate:
        return list(samples)
    size = round(len(samples)*target_rate/source_rate)
    result=[]
    for i in range(size):
        at=i*source_rate/target_rate; lo=int(at); hi=min(lo+1,len(samples)-1)
        result.append(samples[lo]*(1-(at-lo)) + samples[hi]*(at-lo))
    return result
