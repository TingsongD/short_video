"""Compare decoded exports with their bound mix without undoing timing drift.

AAC is lossy and can append a final codec packet. Compare at the export's
48 kHz clock and zero offset in short windows; never align a shifted export
to pass. Downsampling an export back to the narration's 22.05 kHz clock
filters its near-Nyquist consonants a second time, unlike the original WAV.
"""
import math
import subprocess

from ..audio import pcm

COMPARISON_VERSION = 'export_audio.v2'


def compare_export_audio(final, mix, rate=48000):
    try:
        expected = pcm.samples_at_rate(mix, rate)
        actual = pcm.samples_at_rate(final, rate)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'ok': False, 'code': 'export_audio_unreadable', 'comparison_version': COMPARISON_VERSION}
    # A terminal AAC packet may pad the output, but never excuse truncation.
    if not expected or len(actual) < len(expected) - round(rate * .01) or len(actual) > len(expected) + round(rate * .1):
        return {'ok': False, 'code': 'export_audio_length_mismatch',
                'comparison_version': COMPARISON_VERSION,
                'expected_samples': len(expected), 'actual_samples': len(actual)}
    failed = []
    window = rate // 4
    size = min(len(expected), len(actual))
    for start in range(0, size, window):
        end = min(start + window, size)
        # Codec boundary transients are not representative of content.
        lo, hi = max(start, round(rate * .005)), min(end, size - round(rate * .005))
        if hi <= lo:
            continue
        a, b = expected[lo:hi], actual[lo:hi]
        aa = sum(v * v for v in a)
        bb = sum(v * v for v in b)
        ab = sum(x * y for x, y in zip(a, b))
        error = sum((x - y) ** 2 for x, y in zip(a, b))
        rms = math.sqrt(aa / len(a))
        if rms < 48:
            ok = math.sqrt(error / len(a)) <= 64
        else:
            correlation = ab / math.sqrt(aa * bb) if bb else 0
            gain = math.sqrt(bb / aa)
            ok = correlation >= .93 and .8 <= gain <= 1.2 and error / aa <= .25
        if not ok:
            failed.append(round(start / rate, 3))
    return {'ok': not failed, 'code': 'export_audio_matches_mix' if not failed else 'export_audio_content_mismatch',
            'comparison_version': COMPARISON_VERSION,
            'rate': rate, 'compared_samples': size, 'failed_windows_s': failed}
