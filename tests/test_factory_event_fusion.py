from modules.factory.analysis.event_fusion import fuse_events


def test_flash_and_delayed_sound_keep_their_own_times_and_callbacks():
    frames = [dict(index=i, source_time=str(i/30), change=.9 if i in (10, 12, 70, 72) else 0,
                   novelty=.8 if i in (10, 12, 70, 72) else 0) for i in range(90)]
    events = [dict(id='sound', kind='onset_candidate', sample=19200, sample_rate=48000)]
    result = fuse_events(frames, events, audio_origin='0', duration='3')
    assert {10, 12, 70, 72} <= set(result['selected_frame_indices'])
    assert 0 in result['selected_frame_indices'] and 89 in result['selected_frame_indices']
    sound = next(c for c in result['candidates'] if c['id'] == 'audio:sound')
    assert sound['source_time'] == '2/5'
    assert sound['kind'] == 'onset_candidate', 'An audio spike is not a visual cut'


def test_dense_audio_keeps_all_events_but_bounds_redundant_optional_stills():
    from fractions import Fraction
    frames=[dict(index=i,source_time=str(Fraction(i,30)),change=0,novelty=0) for i in range(300)]
    events=[dict(id=str(i),kind='energy_spike',sample=i*4800,sample_rate=48000) for i in range(100)]
    result=fuse_events(frames,events,duration='10')
    assert len([c for c in result['candidates'] if c['id'].startswith('audio:')])==100
    mandatory={i for c in result['candidates'] if c['mandatory'] for i in c['frame_indices']}
    assert mandatory<=set(result['selected_frame_indices'])
    assert len(set(result['selected_frame_indices'])-mandatory)<=10
    assert result['optional_still_policy']=='one_per_second.v1'
    assert all(Fraction(c['context_end'])>Fraction(c['context_start']) for c in result['candidates'])
