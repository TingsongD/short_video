from test_factory_autorun import application, stack, make_seed, launch
from modules.factory.analysis.evidence_policy import (
    legacy_flashcut_policy, new_flashcut_policy, validate_flashcut_policy)


def test_profile_is_frozen_only_on_new_explicit_flashcut_runs(application):
    s,_,act,_,root=stack(application)
    seed=make_seed(act,root)
    legacy=launch(act,seed)
    assert 'flashcut_policy' not in s.autorun.get(legacy['id']).params
    new=launch(act,seed,profile_id='flashcut_hypit.v1')
    saved=s.autorun.get(new['id'])
    assert saved.params['flashcut_policy']==new_flashcut_policy()
    assert saved.params['policies']['captions']=='phrases.v1'
    assert saved.params['workflow']['reference_policy']=='disabled'
    assert saved.params['policies']['variation']=='full_video'


def test_new_temporal_policy_does_not_invalidate_historical_v1_runs():
    current=new_flashcut_policy()
    assert current['version']=='flashcut_policy.v3'
    assert current['quality']=={
        'technical_temporal':'flashcut_temporal_qc.v1',
        'brief_event_max_frames':6,
        'caption_alignment':'final_speech_schedule.v1',
    }
    historical=legacy_flashcut_policy()
    assert historical['version']=='flashcut_policy.v1'
    assert 'quality' not in historical
    assert validate_flashcut_policy(historical)==historical


def test_unqualified_profile_does_not_replace_legacy_video_analysis(application):
    s,_,act,_,root=stack(application)
    run=launch(act,make_seed(act,root),profile_id='flashcut_hypit.v1')
    current=s.autorun.get(run['id'])
    result=s.autorun._stage_video_analysis(current)
    assert isinstance(result,tuple) and result[1]=='flashcut_route_unavailable'
    assert 'analysis' not in current.state
    assert not current.state.get('analysis_jobs')
