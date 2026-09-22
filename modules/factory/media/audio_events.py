"""Bounded, phase-safe acoustic measurements, not semantic classifications.

Only the isolated helper imports NumPy/SciPy. All positions are source audio
sample coordinates. A detector window's localization uncertainty is explicit.
"""
from ..domain.errors import ContractError

RATE, HOP, CORE = 48000, 480, 480000


def _measure(samples, positions, window, spectral=False):
    import numpy as np
    # The caller supplies at most thirty seconds of context. Windows are views;
    # channel powers/spectra, never waveforms, are aggregated across channels.
    padded = np.pad(samples, ((window//2, window//2), (0, 0)))
    windows = np.lib.stride_tricks.sliding_window_view(padded, window, axis=0)
    output = []
    for offset in range(0, len(positions), 64):
        frames = windows[positions[offset:offset+64]]
        if not spectral:
            output.append(np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=(1, 2))))
        else:
            taper = np.hanning(window)
            spectra = np.abs(np.fft.rfft(frames * taper, axis=-1)) / (taper.sum() or 1)
            output.append(np.mean(spectra**2, axis=1))
    return np.concatenate(output)


def analyze_audio(samples, *, sample_rate=RATE, core_start=0, core_end=None):
    """Measure a PCM array/memmap (samples, channels) on fixed source cores.

    Optional core bounds select outputs, not detector context. Running adjacent
    cores separately therefore produces the same events as a whole-file call.
    """
    import numpy as np
    from scipy.ndimage import median_filter
    from scipy.signal import find_peaks
    if sample_rate != RATE or getattr(samples, 'ndim', None) != 2 or not 1 <= samples.shape[1] <= 8:
        raise ContractError('audio_format_unavailable', 'pcm', 'Expected 48 kHz PCM with one to eight channels')
    end = len(samples) if core_end is None else core_end
    if any(type(x) is not int for x in (core_start, end)) or not 0 <= core_start <= end <= len(samples):
        raise ContractError('invalid_audio_range', 'samples')
    events, envelope, chunks = [], [], []
    reliable, audible = False, False
    for core in range(core_start//CORE*CORE, end, CORE):
        until = min(core+CORE, len(samples))
        left, right = max(0, core-CORE), min(len(samples), until+CORE)
        block = np.asarray(samples[left:right], dtype=np.float32)
        if not np.isfinite(block).all():
            raise ContractError('invalid_audio_samples', 'pcm')
        positions = np.arange(0, len(block), HOP, dtype=np.int64)
        absolute = positions + left
        rms = _measure(block, positions, 960)
        spectrum = _measure(block, positions, 2048, spectral=True)
        # sqrt(mean(channel power)) cannot cancel opposite-phase channels.
        magnitude = np.sqrt(spectrum)
        flux = np.maximum(0, np.diff(magnitude, axis=0, prepend=np.zeros_like(magnitude[:1]))).sum(axis=1)
        bass_spectrum = _measure(block, positions, 4096, spectral=True)
        frequencies = np.fft.rfftfreq(4096, 1/RATE)
        bass = bass_spectrum[:, (frequencies >= 20) & (frequencies <= 200)].sum(axis=1)
        baseline = median_filter(flux, size=201, mode='nearest')
        deviation = median_filter(np.abs(flux-baseline), size=201, mode='nearest')
        threshold = np.maximum(.01, baseline + 4*deviation)
        peaks, _ = find_peaks(flux, height=threshold, distance=3)
        peaks = [int(p) for p in peaks if rms[p] >= .005]
        core_mask = (absolute >= max(core, core_start)) & (absolute < min(until, end))
        audible |= bool(np.any(rms[core_mask] > 1e-7))
        for i in np.flatnonzero(core_mask):
            envelope.append({'sample': int(absolute[i]), 'rms': float(rms[i]),
                             'onset_flux': float(flux[i]), 'bass_power': float(bass[i])})
        def event(kind, index, **extra):
            sample = int(absolute[index])
            if max(core, core_start) <= sample < min(until, end):
                events.append({'id': f'{kind}:{sample}', 'kind': kind, 'sample': sample,
                               'sample_rate': RATE, 'timestamp_convention': 'window_center',
                               'localization_samples': 1024, 'interpretation_status': 'unconfirmed', **extra})
        energy_floor = median_filter(rms, size=201, mode='nearest')
        energy_peaks, _ = find_peaks(rms, height=np.maximum(.025, energy_floor*1.8),
                                    prominence=.01, distance=3)
        for peak in energy_peaks:
            event('energy_spike', int(peak), strength=float(rms[peak]),
                  localization_samples=480, support=['short_term_energy_peak'])
        for peak in peaks:
            event('onset_candidate', peak, strength=float(flux[peak]), support=['spectral_change'])
            before, after = max(0, peak-200), min(len(positions), peak+200)
            if peak-before < 100 or after-peak < 100:
                continue
            pre_bass, post_bass = np.median(bass[before:peak]), np.median(bass[peak:after])
            pre_energy, post_energy = np.median(rms[before:peak]), np.median(rms[peak:after])
            pre_density = sum(before <= p < peak for p in peaks)/(max(1, peak-before)/100)
            post_density = sum(peak <= p < after for p in peaks)/(max(1, after-peak)/100)
            if (post_bass > max(.0001, pre_bass*2) and post_energy > max(.025, pre_energy*1.2)
                    and post_density > pre_density+.4):
                event('drop_candidate', peak, localization_samples=4096,
                      support=['sustained_bass_change', 'sustained_energy_change', 'onset_density_change'])
        # Four trailing one-second measurements on a SOURCE-anchored grid.
        # This is a possible buildup, not a genre/scene/drop determination.
        # The full trailing context is available across ten-second core seams.
        for index in np.flatnonzero(core_mask & (absolute % RATE == 0)):
            if index<400:
                continue
            energy=[float(np.median(rms[index-n*100:index-(n-1)*100])) for n in (4,3,2,1)]
            low_band=[float(np.median(bass[index-n*100:index-(n-1)*100])) for n in (4,3,2,1)]
            if (energy[-1]>.025 and energy[-1]>max(.005,energy[0])*1.5
                    and all(b>a*1.08 for a,b in zip(energy,energy[1:]))
                    and low_band[-1]>max(.00001,low_band[0])*1.5
                    and all(b>a*1.08 for a,b in zip(low_band,low_band[1:]))):
                event('buildup_candidate',int(index),context_start_sample=int(absolute[index]-4*RATE),
                      localization_samples=RATE,support=['sustained_energy_rise','sustained_low_band_rise'])
        # Require repeated stable support; never assign BPM to an isolated peak.
        intervals = np.diff(absolute[peaks])/RATE
        if len(intervals) >= 3:
            period = float(np.median(intervals))
            stable = float(np.median(np.abs(intervals-period))) / max(period, 1e-9)
            if .2 <= period <= 1.5 and stable <= .15 and max(intervals) < 1.75*period:
                reliable = True
                for peak in peaks:
                    event('rhythmic_beat_candidate', peak, period_s=period, support=['repeated_stable_onsets'])
        # Low energy is not a claim of absent speech. Context-bounded noise floor.
        db = 20*np.log10(np.maximum(rms, 1e-12))
        quiet_db = max(-60, min(-35, float(np.percentile(db, 20))+6))
        quiet = db < quiet_db
        starts = np.flatnonzero(quiet & ~np.r_[False, quiet[:-1]])
        stops = np.flatnonzero(quiet & ~np.r_[quiet[1:], False]) + 1
        for begin, stop in zip(starts, stops):
            low = max(int(absolute[begin]), core, core_start)
            high = min(left+int(stop)*HOP, until, end)
            if high-low >= RATE*.08:
                events.append({'id': f'low_energy:{low}:{high}', 'kind': 'low_energy',
                               'sample': low, 'end_sample': high, 'sample_rate': RATE,
                               'interpretation_status': 'unconfirmed', 'threshold_dbfs': quiet_db})
        chunks.append({'start_sample': max(core, core_start), 'end_sample': min(until, end)})
    return {'version': 'audio_events.v1', 'status': 'measured' if audible else 'measured_no_events',
            'processed_samples': end-core_start, 'sample_rate': RATE, 'channel_policy': 'aggregate_power',
            'rhythm_status': 'supported_candidates' if reliable else 'rhythm_unreliable',
            'events': sorted(events, key=lambda e: (e['sample'], e['id'])),
            'envelope': envelope, 'chunks': chunks}
