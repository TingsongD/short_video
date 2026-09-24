import pytest
from test_factory_speech import stack, _voiced, NOW, FPS30
from modules.factory.domain.errors import ContractError


def test_final_alignment_is_bound_to_fitted_waveform_without_realigning(stack):
    _,_,_,_,speech,alignment=stack
    _voiced(speech,text='Hello world.')
    alignment.align('seg-1',speech.get,now=NOW)
    fitted=speech.fit('seg-1')
    alignment.aligner=None
    output=alignment.final_alignment('seg-1',speech.get,FPS30,fitted['speech_hash'])
    assert output['artifact_id']==fitted['artifact_id'] and output['sha256']==fitted['audio_sha256']
    assert output['words'] and output['alignment_hash']
    assert all(0<=w['start_frame']<w['end_frame']<=120 for w in output['words'])
    caps=alignment.captions('seg-1',speech.get,fitted['fit'],FPS30,fitted['speech_hash'],now=NOW,preset='phrases.v1',exact=True)
    assert caps.cues[0]['start_frame']==output['words'][0]['start_frame']
    assert caps.cues[-1]['end_frame']==output['words'][-1]['end_frame']
    with pytest.raises(ContractError,match='stale_alignment'):
        alignment.final_alignment('seg-1',speech.get,FPS30,'f'*64)


def test_final_alignment_never_clips_invalid_word_times(stack):
    db,_,_,_,speech,alignment=stack
    _voiced(speech,text='Hello world.')
    original=alignment.align('seg-1',speech.get,now=NOW)
    fitted=speech.fit('seg-1')
    original.words[0]['start_s']=-.2
    row=db.uow().records.get('wordalignment',original.id)
    with db.uow() as u:u.records.put(original,expected_version=row['version'])
    with pytest.raises(ContractError,match='semantic_word_timing_invalid'):
        alignment.final_alignment('seg-1',speech.get,FPS30,fitted['speech_hash'])


def _measured_alignment(words, *, rate=1.0, end=714):
    from modules.factory.audio.alignment import AlignmentService
    service = AlignmentService(None, None)
    text = ' '.join(w['w'] for w in words)
    aligned = {'words': words, 'audio_sha256': 'raw'}
    speech = {'status': 'fitted', 'fit': {'fits': True, 'rate': rate},
              'speech_hash': 'speech', 'raw_audio_sha256': 'raw',
              'audio_sha256': 'final', 'artifact_id': 'audio',
              'text': text, 'target': {'start_frame': 0, 'end_frame': end}}
    service.get = lambda _: aligned
    return service.final_alignment('seg', lambda _: speech, FPS30, 'speech')


def test_final_alignment_accepts_machine_precision_at_fitted_end():
    result = _measured_alignment(
        [{'w': 'members.', 'start_s': 8.22, 'end_s': 9.04}],
        rate=9.04 / 8.8, end=264)
    assert result['words'][-1]['end_frame'] == 264
    with pytest.raises(ContractError, match='semantic_word_timing_invalid'):
        _measured_alignment([{'w': 'members.', 'start_s': 8.22, 'end_s': 9.04001}],
                            rate=9.04 / 8.8, end=264)


def test_final_alignment_preserves_short_measured_word_on_available_frame():
    result = _measured_alignment([
        {'w': 'is', 'start_s': 11.4, 'end_s': 11.64},
        {'w': 'a', 'start_s': 11.66, 'end_s': 11.68},
        {'w': 'vacation', 'start_s': 11.72, 'end_s': 12.1}])
    assert result['words'][1] == {'text': 'a', 'start_frame': 349, 'end_frame': 351}
    assert result['words'][0]['end_frame'] <= result['words'][1]['start_frame']
    assert result['words'][1]['end_frame'] <= result['words'][2]['start_frame']


def test_final_alignment_still_rejects_unresolvable_subframe_collision():
    with pytest.raises(ContractError, match='semantic_word_timing_invalid'):
        _measured_alignment([
            {'w': 'is', 'start_s': 11.4, 'end_s': 11.66},
            {'w': 'a', 'start_s': 11.66, 'end_s': 11.68}])
