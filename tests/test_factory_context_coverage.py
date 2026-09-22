"""Saved, validated source coverage can resolve window-local context gaps."""
from copy import deepcopy
import pytest
from modules.factory.domain.errors import ContractError


def evidence():
    binding={'source_sha256':'a'*64,'transcript_sha256':'b'*64,'evidence_sha256':'c'*64}
    context={'source_duration':'10','candidates':[{'id':'coverage:8','kind':'context',
        'mandatory':True,'source_time':'8','support':['baseline_coverage']}]}
    whole={'scope':'whole','binding':binding,'context':context,'media':[{'id':'source','kind':'video',
        'sha256':'a'*64,'source_start':'0','source_end':'10'}]}
    window={'scope':'window','binding':binding,'context':context,'media':[{'id':'window:0','kind':'video',
        'sha256':'d'*64,'source_start':'0','source_end':'4'}]}
    overview={'scope':'whole','binding':binding,'analysis':{'beats':[{'id':'b'}]},'essential_missing':[],
        'observations':[{'id':'observed-cat','kind':'cast','confidence':'observed','time_basis':'source',
            'start_s':0,'end_s':10,'evidence_ids':['source']}]}
    detail={'scope':'window','binding':binding,'observations':[],'essential_missing':['coverage:8']}
    return [whole,window],[overview,detail]


def test_whole_source_resolves_outside_window_context_with_auditable_evidence():
    from modules.factory.analysis.context_coverage import resolve_context_coverage
    requests,outputs=evidence();before=deepcopy(outputs)
    result=resolve_context_coverage(requests,outputs)
    assert result['pending']==[]
    assert result['resolutions'][0]['flag']=='coverage:8'
    assert result['resolutions'][0]['supporting_observation_ids']==['observed-cat']
    assert outputs==before


@pytest.mark.parametrize('defect',['uncertain','no_coverage','text_only','in_window','semantic_candidate','whole_uncertain','not_source'])
def test_context_reuse_cannot_clear_genuine_or_semantic_questions(defect):
    from modules.factory.analysis.context_coverage import resolve_context_coverage
    requests,outputs=evidence()
    if defect=='uncertain':outputs[0]['observations'][0]['confidence']='uncertain'
    if defect=='no_coverage':outputs[0]['observations'][0]['end_s']=7
    if defect=='text_only':outputs[0]['observations'][0]['kind']='text'
    if defect=='in_window':requests[1]['media'][0]['source_end']='10'
    if defect=='semantic_candidate':requests[1]['context']['candidates'][0]['kind']='visual_change_candidate'
    if defect=='whole_uncertain':outputs[0]['essential_missing']=['coverage:8']
    if defect=='not_source':requests[0]['media'][0]['sha256']='e'*64
    assert resolve_context_coverage(requests,outputs)['pending']


def test_gap_ranges_need_continuous_observed_coverage_and_preserve_claims():
    from modules.factory.analysis.context_coverage import resolve_context_coverage
    requests,outputs=evidence()
    outputs[1].update(essential_missing=['source'],coverage_gap_recovery={'version':'coverage_gap_recovery.v1',
        'claimed_ranges':[{'start_s':'4','end_s':'6'}]})
    assert resolve_context_coverage(requests,outputs)['pending']==[]
    obs=outputs[0]['observations'][0];obs['end_s']=5
    outputs[0]['observations'].append({**obs,'id':'later','start_s':5.1,'end_s':10})
    assert resolve_context_coverage(requests,outputs)['pending']==[{'response_index':1,'flag':'source'}]
    assert outputs[1]['essential_missing']==['source']


def test_cross_source_evidence_is_rejected_before_resolution():
    from modules.factory.analysis.context_coverage import resolve_context_coverage
    requests,outputs=evidence();outputs[0]['binding']={**outputs[0]['binding'],'source_sha256':'f'*64}
    with pytest.raises(ContractError,match='analysis_media_mismatch'):
        resolve_context_coverage(requests,outputs)


def test_visual_candidates_require_explicit_source_bound_local_observation():
    from modules.factory.analysis.context_coverage import resolve_context_coverage
    requests,outputs=evidence()
    requests[1]['context']['candidates'][0].update(id='visual:240',kind='visual_change_candidate',support=['pixel_change'])
    outputs[1]['essential_missing']=['visual:240']
    local={'binding':requests[0]['binding'],'observations':[{'candidate_id':'visual:240',
        'description':'The view shifts while the same subject remains present.','evidence_ids':['frame:239','frame:240','frame:241']}]}
    assert resolve_context_coverage(requests,outputs,local_evidence=local)['pending']==[]
    assert resolve_context_coverage(requests,outputs)['pending']


def test_normal_analysis_reuses_whole_video_context_and_keeps_other_flags():
    from modules.factory.analysis.context_coverage import analysis_pending
    requests,outputs=evidence()
    outputs[1]['essential_missing']=['coverage:8','visual:240']
    requests[1]['context']['candidates'].append({'id':'visual:240','kind':'visual_change_candidate','mandatory':True,
        'source_time':'1','support':['pixel_change']})
    pending,resolution=analysis_pending(requests,outputs)
    assert pending=={'visual:240'}
    assert resolution['resolutions'][0]['flag']=='coverage:8'
    assert outputs[1]['essential_missing']==['coverage:8','visual:240']


def test_mismatched_or_format_recovery_bundles_do_not_drop_flags():
    from modules.factory.analysis.context_coverage import analysis_pending
    requests,outputs=evidence()
    assert analysis_pending(requests,outputs,format_recovery=True)==(set(),None)
    assert analysis_pending(requests,outputs+[{'essential_missing':['kept']}])==(
        {'coverage:8','kept'},None)
