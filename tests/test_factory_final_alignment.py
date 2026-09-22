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
