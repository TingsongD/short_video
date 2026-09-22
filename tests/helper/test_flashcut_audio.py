import pytest
np = pytest.importorskip('numpy', reason='VALIDATION GAP: run isolated helper tests')


def test_antiphase_stereo_is_not_silence_and_peak_is_not_a_drop():
    from modules.factory.media.audio_events import analyze_audio
    signal = np.zeros(48000 * 3, dtype=np.float32)
    signal[48000:48480] = .8 * np.sin(np.arange(480) * 2*np.pi*100/48000)
    result = analyze_audio(np.stack([signal, -signal], axis=1))
    assert result['status'] == 'measured'
    assert max(point['rms'] for point in result['envelope']) > .3
    assert any(event['kind'] == 'onset_candidate' for event in result['events'])
    assert any(event['kind'] == 'energy_spike' for event in result['events'])
    assert not any(event['kind'] == 'drop_candidate' for event in result['events'])
    assert result['rhythm_status'] == 'rhythm_unreliable'


def test_valid_silence_is_not_failed_or_invented_rhythm():
    from modules.factory.media.audio_events import analyze_audio
    result = analyze_audio(np.zeros((48000, 2), dtype=np.float32))
    assert result['status'] == 'measured_no_events'
    assert not any(e['kind'] in ('onset_candidate', 'rhythmic_beat_candidate', 'drop_candidate') for e in result['events'])
    assert result['processed_samples'] == 48000


def test_chunk_restart_preserves_detector_context_and_events():
    from modules.factory.media.audio_events import analyze_audio
    signal = np.zeros((48000*21, 1), dtype=np.float32)
    for second in (9.9, 10.1, 19.9, 20.1):
        start = round(second*48000)
        signal[start:start+480, 0] = .7*np.sin(np.arange(480)*2*np.pi*150/48000)
    whole = analyze_audio(signal)
    parts = [analyze_audio(signal, core_start=start, core_end=min(start+480000, len(signal)))
             for start in range(0, len(signal), 480000)]
    assert whole['events'] == [event for part in parts for event in part['events']]
    assert whole['envelope'] == [point for part in parts for point in part['envelope']]


def test_sustained_buildup_is_distinct_from_single_spike_and_not_a_confirmed_drop():
    from modules.factory.media.audio_events import analyze_audio
    time=np.arange(48000*7)/48000
    signal=((.02+.06*time)*np.sin(2*np.pi*90*time)).astype(np.float32)[:,None]
    result=analyze_audio(signal)
    buildup=[e for e in result['events'] if e['kind']=='buildup_candidate']
    assert buildup and all(e['interpretation_status']=='unconfirmed' for e in buildup)
    assert all(e['context_start_sample']<e['sample'] for e in buildup)
    assert not any(e['kind']=='drop_candidate' for e in result['events'])
