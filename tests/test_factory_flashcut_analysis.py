import base64
import json
import pytest
from modules.factory.domain.errors import ContractError
from modules.factory.testing.fakes import ProviderError
from modules.factory.testing.fixtures import _color_mp4, _png
from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.store import Database


def test_flashcut_route_sends_actual_media_and_supported_generation_config(tmp_path):
    from modules.factory.analysis.flashcut_vertex import FlashcutAnalyzer, ROUTE_LIMITS
    db=Database(tmp_path/'db')
    try:
        artifacts=ArtifactStore(tmp_path/'artifacts',db)
        _color_mp4(tmp_path/'video.mp4',1,size='72x128')
        _png(tmp_path/'frame.png')
        video=artifacts.intake_file(tmp_path/'video.mp4','seed_source','clip')
        frame=artifacts.intake_file(tmp_path/'frame.png','seed_source','frame')
        from modules.factory.analysis.source_evidence import SourceEvidenceService
        from test_factory_source_evidence import binding
        store=SourceEvidenceService(db,tmp_path/'source_evidence')
        frozen={**binding(),'source_sha256':video.sha256,'source_artifact_id':video.id,'transcript_sha256':'c'*64}
        evidence=store.create('run',frozen,{'version':'test.v1'})
        for stage in ('clock','visual','audio','fusion'):
            store.chunk(evidence['id'],stage,0,1,lambda:{'duration':'1'},current_binding=frozen)
        selected={'images':[{'artifact_id':frame.id,'sha256':frame.sha256,'source_time':'0','frame_index':0}],
                  'windows':[{'artifact_id':video.id,'sha256':video.sha256,'source_start':'0','source_end':'1'}]}
        store.chunk(evidence['id'],'media',0,1,lambda:selected,current_binding=frozen)
        saved=store.complete(evidence['id'],{k:1 for k in ('clock','visual','audio','fusion','media')},current_binding=frozen)
        calls=[]
        class Auth:
            def bearer(self):return 'fake-token'
        def transport(method,url,body,headers):
            payload=json.loads(body)
            calls.append(payload)
            config=payload['generationConfig']
            assert 'temperature' not in config and config['thinkingConfig']['thinkingLevel']=='HIGH'
            media=[p['inlineData'] for p in payload['contents'][0]['parts'] if 'inlineData' in p]
            assert [m['mimeType'] for m in media]==['video/mp4','image/png']
            assert base64.b64decode(media[0]['data'])==(tmp_path/'video.mp4').read_bytes()
            result={'observations':[{'id':'o1','kind':'action','start_s':0,'end_s':.2,
                     'description':'A colored frame.','evidence_ids':['window-1','frame-1'],
                     'role_ids':[],'text_role':'none','confidence':'observed','time_basis':'source'}], 'essential_missing':[]}
            return 200,{},json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(result)}]}}]}).encode()
        adapter=FlashcutAnalyzer(tmp_path/'route',artifacts,Auth(),'test','test-project',
            {'input_usd_micros_per_million':750000,'output_usd_micros_per_million':3750000,
             'valid_until':'2099-01-01T00:00:00Z','evidence':'offline-fixture'},transport=transport)
        request={'task':'analyze_flashcut','model':'gemini-3.8-flash','prompt_version':'flashcut_understanding.v1',
                 'scope':'window','binding':{'source_sha256':video.sha256,'evidence_sha256':saved['manifest']['sha256'],'transcript_sha256':'c'*64},
                 'context':{'source_duration':'1','transcript':[],'candidates':[]},'limits':ROUTE_LIMITS,
                 'media':[{'id':'window-1','kind':'video','artifact_id':video.id,'sha256':video.sha256,
                           'source_start':'0','source_end':'1'},
                          {'id':'frame-1','kind':'image','artifact_id':frame.id,'sha256':frame.sha256,'source_time':'0'}]}
        price=adapter.price(request)
        assert price['reserve_amount']>0
        result=adapter.submit(request)
        assert result['result']['observations'][0]['start_s']==0
        assert len(calls)==1
        request['context']['source_duration']='2'
        with pytest.raises(ContractError,match='analysis_media_mismatch'):
            adapter.price(request)
        request['context']['source_duration']='1'
        request['media'][1]['source_time']='1/2'
        with pytest.raises(ContractError,match='analysis_media_mismatch'):
            adapter.price(request)
        request['media'][1]['source_time']='0'
        request['media'][0]['sha256']='f'*64
        with pytest.raises(ContractError,match='analysis_media_mismatch'):
            adapter.price(request)
        assert len(calls)==1
    finally:
        db.close()


def test_foreign_observation_ids_and_window_times_are_rejected():
    from modules.factory.analysis.flashcut_vertex import validate_observations
    request={'scope':'window','context':{'source_duration':'10'},
             'media':[{'id':'window','kind':'video','source_start':'5','source_end':'7'}]}
    item={'id':'o1','kind':'reveal','start_s':0,'end_s':1,'description':'A reveal.',
          'evidence_ids':['window'],'role_ids':[],'text_role':'none','confidence':'observed'}
    # Responses use source timestamps, never silently accepted window-relative times.
    with pytest.raises(ProviderError,match='malformed_flashcut_analysis'):
        validate_observations({'observations':[item],'essential_missing':[]},request)
    item.update(start_s=5,end_s=6)
    with pytest.raises(ProviderError,match='malformed_flashcut_analysis'):
        validate_observations({'observations':[item],'essential_missing':[]},request)
    item['time_basis']='source'
    assert validate_observations({'observations':[item],'essential_missing':[]},request)['observations'][0]['start_s']==5
    item.update(start_s=0,end_s=1,time_basis='window')
    mapped=validate_observations({'observations':[item],'essential_missing':[]},request)['observations'][0]
    assert mapped['start_s']==5 and mapped['end_s']==6 and mapped['original_time_basis']=='window'
    item['evidence_ids']=['foreign']
    with pytest.raises(ProviderError,match='malformed_flashcut_analysis'):
        validate_observations({'observations':[item],'essential_missing':[]},request)


@pytest.mark.parametrize('second_start,accepted', [('3', True), ('4', True), ('4.01', False)])
def test_observation_can_span_continuously_covered_cited_windows(second_start, accepted):
    from modules.factory.analysis.flashcut_vertex import validate_observations
    request = {'scope': 'window', 'context': {'source_duration': '14.1'}, 'media': [
        {'id': 'w0', 'kind': 'video', 'source_start': '0', 'source_end': '4'},
        {'id': 'w1', 'kind': 'video', 'source_start': second_start, 'source_end': '7'}]}
    item = {'id': 'cat', 'kind': 'cast', 'start_s': 0, 'end_s': 7,
            'time_basis': 'source', 'description': 'A cat remains on the bed.',
            'evidence_ids': ['w0', 'w1'], 'role_ids': ['cat'],
            'text_role': 'none', 'confidence': 'observed'}
    value = {'observations': [item], 'essential_missing': []}
    if accepted:
        result = validate_observations(value, request)['observations'][0]
        assert (result['start_s'], result['end_s']) == (0, 7)
        # Merely supplying a second window is not enough: it must be cited.
        item['evidence_ids'] = ['w0']
    with pytest.raises(ProviderError, match='malformed_flashcut_analysis'):
        validate_observations(value, request)


@pytest.mark.parametrize('bad', ['null_copy','unknown_role','duplicate_beat','null_visual','wrong_transcript_type'])
def test_whole_flashcut_analysis_rejects_invalid_nested_evidence(bad):
    from copy import deepcopy
    from modules.factory.analysis.flashcut_vertex import validate_observations
    from test_factory_autorun import ANALYZE
    analysis=deepcopy(ANALYZE)
    analysis['creative_context']={'version':'scene.v2','roles':[],'scenes':[
        {'beat_id':b['id'],'physical_scene':b['visual_event'],'cast':[],'wardrobe':{},
         'allowed_transition':'Planned change.','source_overlays':[],'environmental_text':[]} for b in analysis['beats']]}
    if bad=='null_copy':analysis['transcript'][0]['text']=None
    if bad=='unknown_role':analysis['beats'][0]['role']='invented'
    if bad=='duplicate_beat':analysis['beats'][1]['id']=analysis['beats'][0]['id']
    if bad=='null_visual':analysis['beats'][0]['visual_event']=None
    if bad=='wrong_transcript_type':analysis['transcript']='bad'
    request={'scope':'whole','context':{'source_duration':'9'},'media':[{'id':'source','kind':'video','source_start':'0','source_end':'9'}]}
    with pytest.raises(ProviderError,match='malformed_flashcut_analysis'):
        validate_observations({'observations':[],'essential_missing':[],'analysis':analysis},request)
def test_clarification_groups_missing_candidates_only_with_complete_media_coverage():
    from modules.factory.analysis.flashcut_requests import build_clarification_request
    candidates=[{'id':f'coverage:{i}','source_time':str(i)} for i in (2,8,10)]
    base={'context':{'candidates':candidates},'scope':'window'}
    plan={'requests':[
        {**base,'scope':'whole','media':[{'id':'source','kind':'video','source_start':'0','source_end':'12'}]},
        {**base,'media':[{'id':'first','kind':'video','source_start':'0','source_end':'4'}]},
        {**base,'media':[{'id':'last','kind':'video','source_start':'7','source_end':'12'}]}]}
    request=build_clarification_request(plan,['coverage:8','coverage:10'])
    assert request['context']['clarify_ids']==['coverage:8','coverage:10']
    assert request['media'][0]['id']=='last'
    assert request['response_contract']=='flashcut_structured.v1'
    request=build_clarification_request(plan,['coverage:2','coverage:8'])
    assert request['media'][0]['id']=='source'
    assert request['context']['clarify_ids']==['coverage:2','coverage:8']
    plan['candidate_index']=candidates
    source_request=build_clarification_request(plan,['source'])
    assert source_request['context']['clarify_ids']==['source']
    assert source_request['media'][0]['id']=='source'
    assert source_request['context']['candidates']==candidates


def test_dense_candidate_context_is_partitioned_without_dropping_evidence():
    """A long source must not copy every measured event into every request."""
    from modules.factory.analysis.flashcut_requests import build_analysis_plan

    candidates=[]
    for index in range(600):
        second=index % 60
        candidates.append({
            'id':f'audio:onset_candidate:{index}',
            'kind':'onset_candidate',
            'source_time':str(second),
            'mandatory':index in (0,599),
            'support':['spectral_change','dense_fixture_' + ('x' * 40)],
        })
    binding={'source_sha256':'a'*64,'transcript_sha256':'b'*64,
             'evidence_sha256':'c'*64}
    record={'binding':{**binding,'source_artifact_id':'source-artifact'},
            'manifest':{'sha256':'c'*64}}
    clock={'duration':'60','version':'clock.v1','origin':'source',
           'video':{},'audio':{},'decoded_frames':1800}
    fusion={'candidates':candidates}
    media={'version':'selected_media.v2',
           'overview':{'artifact_id':'overview-artifact',
                       'sha256':'2'*64},
           'images':[
        {'artifact_id':'image-a','sha256':'d'*64,'source_time':'10',
         'frame_index':300,'mime_type':'image/jpeg'},
        {'artifact_id':'image-b','sha256':'e'*64,'source_time':'50',
         'frame_index':1500,'mime_type':'image/jpeg'},
    ],'windows':[
        {'artifact_id':'window-a','sha256':'f'*64,
         'source_start':'0','source_end':'30'},
        {'artifact_id':'window-b','sha256':'1'*64,
         'source_start':'30','source_end':'60'},
    ]}

    class Blobs:
        values={'clock':clock,'fusion':fusion,'media':media}
        def read(self, value):
            return self.values[value]
    class Store:
        blobs=Blobs()
        def get(self, evidence_id):
            assert evidence_id=='evidence'
            return record
        def manifest(self, evidence_id):
            assert evidence_id=='evidence'
            return {'chunks':[{'stage':stage,'blob':stage}
                              for stage in ('clock','fusion','media')]}
    class Adapter:
        limits={'requests':20,'images':24,'windows':8,
                'media_seconds':600,'payload_bytes':20*1024**2,
                'context_bytes':64000,'input_tokens':1000000,
                'output_tokens':8192,'clarifications':2}
        pricing={'input_usd_micros_per_million':750000,
                 'output_usd_micros_per_million':3750000}
        def prepared(self, request):
            if len(json.dumps(request['context']).encode()) > 64000:
                raise ContractError('flashcut_request_limit','context')
            return None, {'images':sum(m['kind']=='image' for m in request['media']),
                'windows':sum(m['kind']=='video' for m in request['media']),
                'media_seconds':'30','payload_bytes':1000,
                'input_tokens_bound':2000,'output_tokens_bound':8192}
        def price(self, request):
            self.prepared(request)
            return {'reserve_amount':10}

    plan=build_analysis_plan(Store(),'evidence',Adapter(),[])
    assert plan['version']=='flashcut_analysis_plan.v2'
    assert plan['candidate_index']==candidates
    assert {c['id'] for c in plan['requests'][0]['context']['candidates']} == {
        candidates[0]['id'],candidates[-1]['id']}
    covered={c['id'] for request in plan['requests'][1:]
             for c in request['context']['candidates']}
    assert covered=={c['id'] for c in candidates}
