from types import SimpleNamespace
from modules.factory.analysis.evidence_policy import new_flashcut_policy
from modules.factory.analysis.source_evidence import SourceEvidenceService
from modules.factory.domain.errors import ContractError
from modules.factory.domain.clocks import RationalRate
from modules.factory.testing.fixtures import _color_mp4
from test_factory_speech import stack, _voiced, NOW
import pytest


def test_existing_final_speech_flows_into_immutable_native_plan(stack,tmp_path):
    from modules.factory.services.editorial_work import prepare_editorial
    db,arts,_,_,speech,alignment=stack
    _voiced(speech,text='Hello world.')
    alignment.align('seg-1',speech.get,now=NOW)
    fitted=speech.fit('seg-1')
    final=alignment.final_alignment('seg-1',speech.get,RationalRate(30,1),fitted['speech_hash'])
    _color_mp4(tmp_path/'clip.mp4',4)
    clip=arts.intake_file(tmp_path/'clip.mp4','manual','clip')
    segment={'id':'b0','copy':'Hello world.','target':{'start_frame':0,'end_frame':120},
             'speech':{'speech_id':'seg-1',**{k:final[k] for k in ('artifact_id','speech_hash','alignment_hash')}}}
    variant=SimpleNamespace(variant_key='B',target_frames=120,segments=[segment])
    exp=SimpleNamespace(experiment_id='exp',revision=4,output_clock={'num':30,'den':1},packaging={
        'flashcut_policy':new_flashcut_policy(),'flashcut_editorial':{'events':{'B':[]},'evidence_sha256':'c'*64}})
    s=SimpleNamespace(db=db,artifacts=arts,audio_work=SimpleNamespace(speech=speech,alignment=alignment),
        source_evidence=SourceEvidenceService(db,tmp_path/'evidence'))
    pictures=[{'id':'b0-0','kind':'picture','artifact_id':clip.id,'sha256':clip.sha256,
               'in_frame':0,'out_frame':120,'source_in_s':0,'source_out_s':4}]
    record,resolved,captions=prepare_editorial(s,exp,variant,pictures,{'sha256':'d'*64})
    assert record['variant_key']=='B'
    assert resolved['passages'][0]['alignment_hash']==final['alignment_hash']
    assert captions[0]['text']=='Hello world.'
    segment['speech']['alignment_hash']='f'*64
    with pytest.raises(ContractError,match='stale_alignment'):
        prepare_editorial(s,exp,variant,pictures,{'sha256':'d'*64})
