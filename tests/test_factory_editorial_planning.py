from copy import deepcopy
import pytest
from modules.factory.domain.errors import ContractError


def case():
    passage={'id':'p0','segment_id':'b0','text':'Now look.','in_frame':0,'out_frame':90,
             'words':[{'text':'Now','start_frame':0,'end_frame':12},
                      {'text':'look.','start_frame':45,'end_frame':60}]}
    inputs={'version':'editorial_input.v1','clock':{'num':30,'den':1},'total_frames':90,
        'observations':[{'id':'o1','kind':'cut','start_s':1,'end_s':1.067,'confidence':'observed'}],
        'variants':{k:{'passages':[deepcopy(passage)],'footage':[{'id':'b0','in_frame':0,'out_frame':90}]} for k in 'ABCD'}}
    event={'id':'e0','observation_id':'o1','kind':'cut','required':True,'source_time':'1',
        'anchor':{'kind':'speech','passage_id':'p0','word_index':1,'text':'look.','edge':'start'},
        'duration_frames':2,'footage_id':'b0','source_in_frame':70}
    response={'variants':{k:{'events':[deepcopy(event)],'coverage':[{'observation_id':'o1','event_id':'e0'}]} for k in 'ABCD'}}
    return inputs,response


def test_editorial_plan_binds_all_variants_to_final_words_and_explicit_clip_ranges():
    from modules.factory.analysis.editorial_planning import validate_editorial_response
    inputs,response=case()
    result=validate_editorial_response(response,inputs)
    assert result['B']['events'][0]['start_frame']==45
    assert result['B']['events'][0]['end_frame']==47
    assert result['B']['events'][0]['variant_key']=='B'


@pytest.mark.parametrize('mutation', ['word','missing_variant','omitted_cut','range','overlap','noop'])
def test_editorial_planner_refuses_ambiguous_or_ineffective_work(mutation):
    from modules.factory.analysis.editorial_planning import validate_editorial_response
    inputs,response=case();branch=response['variants']['A']
    if mutation=='word':branch['events'][0]['anchor']['text']='else'
    if mutation=='missing_variant':response['variants'].pop('D')
    if mutation=='omitted_cut':branch['events']=[];branch['coverage']=[{'observation_id':'o1','beat_id':'b0'}]
    if mutation=='range':branch['events'][0]['source_in_frame']=89
    if mutation=='overlap':branch['events'].append({**deepcopy(branch['events'][0]),'id':'e1'})
    if mutation=='noop':branch['events'][0]['source_in_frame']=45
    with pytest.raises(ContractError):validate_editorial_response(response,inputs)


def test_semantic_plan_refuses_to_reuse_a_different_revision_or_speech_binding(tmp_path):
    from modules.factory.analysis.editorial_planning import PlanningStore
    from modules.factory.store import Database
    db=Database(tmp_path/'db')
    try:
        store=PlanningStore(db,tmp_path/'evidence');inputs,response=case()
        binding={'experiment_id':'exp','revision':1,'speech':'a'*64,'understanding':'b'*64}
        saved=store.save(binding,inputs,response)
        assert store.get(binding)['manifest']==saved['manifest']
        assert store.get({**binding,'revision':2}) is None
        assert store.get({**binding,'speech':'c'*64}) is None
        assert store.load(saved)['plans']['A']['events'][0]['start_frame']==45
    finally:db.close()


def test_conservative_fallback_preserves_observed_cuts_without_inventing_words():
    from modules.factory.analysis.editorial_planning import (
        conservative_editorial_response, validate_editorial_response)
    inputs,_ = case()
    fallback = conservative_editorial_response(inputs)
    resolved = validate_editorial_response(fallback, inputs)
    assert set(resolved) == set('ABCD')
    for key in 'ABCD':
        event = fallback['variants'][key]['events'][0]
        assert event['observation_id'] == 'o1'
        assert event['anchor'] == {
            'kind': 'visual', 'target_time': '1', 'evidence_id': 'o1'}
        assert event['source_in_frame'] != 30


def test_conservative_fallback_pauses_when_required_events_conflict():
    from modules.factory.analysis.editorial_planning import conservative_editorial_response
    inputs,_ = case()
    inputs['observations'].append({
        'id': 'o2', 'kind': 'cut', 'start_s': 1, 'end_s': 1.067,
        'confidence': 'observed'})
    with pytest.raises(ContractError, match='editorial_fallback_unsafe'):
        conservative_editorial_response(inputs)


def test_flashcut_route_uses_local_fallback_only_for_completed_invalid_editorial_json():
    from modules.factory.analysis.flashcut_vertex import FlashcutAnalyzer
    inputs,_ = case()
    adapter = FlashcutAnalyzer.__new__(FlashcutAnalyzer)
    adapter.live = False
    adapter.prepared = lambda request: ([], {'payload_bytes': 1})
    adapter._output_settings = lambda request: (100, 'LOW')
    adapter._response_schema = lambda request: None
    adapter._generate = lambda *args, **kwargs: {'variants': {}}
    result, payload, extra = adapter.execute({
        'task': 'plan_flashcut_edits', 'editorial_input': inputs,
        'editorial_binding': {'input_sha256': 'fixture'}})
    assert payload is None and extra == {}
    assert result['plan_origin'] == 'local_conservative'
    assert result['editorial_recovery'] == {
        'kind': 'deterministic_conservative.v1',
        'reason': 'invalid_editorial_response',
    }
    assert result['editorial']['variants']['A']['events'][0]['id'] == 'fallback-o1'


def test_valid_editorial_response_records_provider_origin():
    from modules.factory.analysis.flashcut_vertex import FlashcutAnalyzer
    inputs, response = case()
    adapter = FlashcutAnalyzer.__new__(FlashcutAnalyzer)
    adapter.live = False
    adapter.prepared = lambda request: ([], {'payload_bytes': 1})
    adapter._output_settings = lambda request: (100, 'LOW')
    adapter._response_schema = lambda request: None
    adapter._generate = lambda *args, **kwargs: response
    result, payload, extra = adapter.execute({
        'task': 'plan_flashcut_edits', 'editorial_input': inputs,
        'editorial_binding': {'input_sha256': 'fixture'}})
    assert payload is None and extra == {}
    assert result['plan_origin'] == 'provider'
    assert 'editorial_recovery' not in result
