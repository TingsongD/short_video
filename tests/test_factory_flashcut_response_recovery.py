"""Recovery at the durable provider/quotation boundary; no live requests."""
from copy import deepcopy
import json
import pytest

from modules.factory.analysis.flashcut_vertex import FlashcutAnalyzer, ROUTE_LIMITS
from modules.factory.analysis.source_evidence import SourceEvidenceService
from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.domain.errors import ContractError
from modules.factory.execution.context import dispatch_context
from modules.factory.store import Database
from modules.factory.testing.fakes import ProviderError
from modules.factory.testing.fixtures import _color_mp4
from test_factory_source_evidence import binding


@pytest.fixture
def route(tmp_path):
    db = Database(tmp_path/'db')
    artifacts = ArtifactStore(tmp_path/'artifacts', db)
    _color_mp4(tmp_path/'source.mp4', 1, size='72x128')
    video = artifacts.intake_file(tmp_path/'source.mp4', 'seed_source', 'source')
    store = SourceEvidenceService(db, tmp_path/'source_evidence')
    frozen = {**binding(), 'source_sha256': video.sha256, 'source_artifact_id': video.id}
    record = store.create('run', frozen, {'version': 'test.v1'})
    for stage in ('clock', 'visual', 'audio', 'fusion'):
        store.chunk(record['id'], stage, 0, 1, lambda: {'duration': '1'}, current_binding=frozen)
    store.chunk(record['id'], 'media', 0, 1, lambda: {'images': [], 'windows': [
        {'artifact_id': video.id, 'sha256': video.sha256, 'source_start': '0', 'source_end': '1'}]},
        current_binding=frozen)
    saved = store.complete(record['id'], {k: 1 for k in ('clock', 'visual', 'audio', 'fusion', 'media')}, current_binding=frozen)
    calls = []
    reply = {'finish': 'MAX_TOKENS'}
    output = {'observations': [{'id': 'o', 'kind': 'action', 'start_s': 0, 'end_s': 1,
        'time_basis': 'source', 'description': 'A colored frame.', 'evidence_ids': ['w'],
        'role_ids': [], 'text_role': 'none', 'confidence': 'observed'}], 'essential_missing': []}
    def transport(method, url, body, headers):
        calls.append(json.loads(body))
        if reply['finish'] == 'timeout':
            raise TimeoutError()
        value=deepcopy(output)
        value['essential_missing']=reply.get('missing',[])
        value['observations'][0]['end_s']=reply.get('end',1)
        if 'gaps' in reply:
            value['coverage_gaps']=deepcopy(reply['gaps'])
        return 200, {}, json.dumps({'candidates': [{'finishReason': reply['finish'], 'content': {
            'parts': [{'text': json.dumps(value) if reply['finish'] == 'STOP' else '{"observations": ['}]}}],
            'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 10,
                              'thoughtsTokenCount': 8000, 'totalTokenCount': 8110}}).encode()
    class Auth:
        def bearer(self): return 'offline-token'
    adapter = FlashcutAnalyzer(tmp_path/'route', artifacts, Auth(), 'fixture', 'fixture', {
        'input_usd_micros_per_million': 750000, 'output_usd_micros_per_million': 3750000,
        'valid_until': '2099-01-01T00:00:00Z', 'evidence': 'offline fixture'}, transport=transport)
    request = {'task': 'analyze_flashcut', 'model': adapter.model, 'prompt_version': 'flashcut_understanding.v1',
        'scope': 'window', 'limits': deepcopy(ROUTE_LIMITS),
        'binding': {'source_sha256': video.sha256, 'transcript_sha256': frozen['transcript_sha256'],
                    'evidence_sha256': saved['manifest']['sha256']},
        'context': {'source_duration': '1', 'candidates': []},
        'media': [{'id': 'w', 'kind': 'video', 'artifact_id': video.id, 'sha256': video.sha256,
                   'source_start': '0', 'source_end': '1'}]}
    try:
        yield adapter, request, calls, reply
    finally:
        db.close()


def test_completed_capped_response_gets_new_quoted_identity_without_replay(route):
    adapter, request, calls, reply = route
    before = adapter.price(request)
    with dispatch_context({'attempt_id': 'original'}), pytest.raises(ProviderError, match='analysis_incomplete'):
        adapter.submit(request)
    recovery = adapter.inspect_saved_response(request, 'original')
    assert recovery['finish_reason'] == 'MAX_TOKENS'
    replacement = adapter.replacement_request(request, 'original')
    assert replacement != request and adapter.price(replacement)['reserve_amount'] > before['reserve_amount']
    reply['finish'] = 'STOP'
    with dispatch_context({'attempt_id': 'replacement'}):
        assert adapter.submit(replacement)['status'] == 'succeeded'
    config = calls[-1]['generationConfig']
    assert config['maxOutputTokens'] == 32768 and config['thinkingConfig']['thinkingLevel'] == 'MEDIUM'
    # A restart/explicit replay of the old identity remains unknown; no new call.
    with dispatch_context({'attempt_id': 'original'}):
        assert adapter.submit(request)['status'] == 'unknown'
    assert len(calls) == 2
    with pytest.raises(ContractError, match='flashcut_recovery_exhausted'):
        adapter.replacement_request(replacement, 'replacement')


@pytest.mark.parametrize('method',['replacement_request','format_recovery_request'])
def test_unknown_transport_outcome_never_gets_replacement(route,method):
    adapter, request, calls, reply = route
    reply['finish'] = 'timeout'
    with dispatch_context({'attempt_id': 'unknown'}), pytest.raises(ProviderError, match='analysis_timeout'):
        adapter.submit(request)
    with pytest.raises(ContractError, match='flashcut_response_unproven'):
        getattr(adapter,method)(request, 'unknown')
    assert len(calls) == 1


@pytest.mark.parametrize('mutation', ['identity', 'media', 'settings', 'saved_response'])
def test_replacement_rejects_changed_binding_or_evidence_before_transport(route, mutation):
    adapter, request, calls, reply = route
    with dispatch_context({'attempt_id': 'original'}), pytest.raises(ProviderError):
        adapter.submit(request)
    replacement = adapter.replacement_request(request, 'original')
    if mutation == 'identity':
        replacement['response_recovery']['proof']['attempt_id'] = 'another'
    elif mutation == 'media':
        replacement['media'][0]['source_end'] = '.5'
    elif mutation == 'settings':
        replacement['response_recovery']['max_output_tokens'] = 65536
    else:
        path = next(adapter.root.glob('sync-*/provider-response.json'))
        changed = json.loads(path.read_text())
        changed['response']['usageMetadata']['totalTokenCount'] = 9999
        path.write_text(json.dumps(changed))
    with pytest.raises(ContractError):
        adapter.price(replacement)
    assert len(calls) == 1


def test_saved_valid_response_is_recovered_without_transport_or_receipt_rewrite(route, monkeypatch):
    import modules.factory.analysis.flashcut_vertex as vertex
    adapter, request, calls, reply = route
    reply['finish'] = 'STOP'
    # The old validator rejected this returned answer; preserve that receipt.
    with monkeypatch.context() as old:
        old.setattr(vertex, 'validate_observations', lambda *_: (_ for _ in ()).throw(ProviderError('malformed_flashcut_analysis')))
        with dispatch_context({'attempt_id': 'old-validator'}), pytest.raises(ProviderError):
            adapter.submit(request)
    receipt = next(adapter.root.glob('sync-*/receipt.json'))
    before = receipt.read_bytes()
    recovered = adapter.inspect_saved_response(request, 'old-validator')
    assert recovered['result']['observations'][0]['description'] == 'A colored frame.'
    assert receipt.read_bytes() == before and len(calls) == 1


def test_structured_clarification_constrains_media_ids_and_does_not_replay(route, monkeypatch):
    import modules.factory.analysis.flashcut_vertex as vertex
    adapter, request, calls, reply = route
    reply['finish'] = 'STOP'
    with monkeypatch.context() as old:
        old.setattr(vertex, 'validate_observations', lambda *_: (_ for _ in ()).throw(ProviderError('malformed_flashcut_analysis')))
        with dispatch_context({'attempt_id': 'malformed'}), pytest.raises(ProviderError):
            adapter.submit(request)
    clarification = adapter.structured_clarification(request, 'malformed')
    assert clarification['scope'] == 'clarification'
    assert adapter.price(clarification)['reserve_amount'] > 0
    with dispatch_context({'attempt_id': 'clarification'}):
        assert adapter.submit(clarification)['status'] == 'succeeded'
    config = calls[-1]['generationConfig']
    assert config['thinkingConfig']['thinkingLevel'] == 'MEDIUM'
    schema = config['responseSchema']['properties']['observations']['items']['properties']
    assert schema['evidence_ids']['items']['enum'] == ['w']
    assert config['maxOutputTokens'] == 8192
    assert len(calls) == 2
    with pytest.raises(ContractError, match='flashcut_recovery_exhausted'):
        adapter.structured_clarification(clarification, 'clarification')


@pytest.mark.parametrize('finish', ['MAX_TOKENS', 'timeout'])
def test_completed_response_releases_only_execution_capacity_not_unknown_accounting(route, finish):
    from types import SimpleNamespace
    from modules.factory.autorun.flashcut_recovery import FlashcutResponseRecovery
    from modules.factory.execution.effects import wire_hash
    adapter, request, calls, reply = route
    reply['finish']=finish
    with dispatch_context({'attempt_id':'a'}), pytest.raises(ProviderError):
        adapter.submit(request)
    db=adapter.artifacts.db
    with db.uow() as u:
        u.conn.execute("INSERT INTO jobs(id,logical_key,phase,status,created_at,updated_at) VALUES('j','j','analyze','failed','now','now')")
        u.conn.execute("INSERT INTO attempts(id,job_id,attempt_seq,request_hash,status,body,created_at,updated_at) VALUES('a','j',1,?,'unknown','{}','now','now')",(wire_hash(request),))
        u.conn.execute("INSERT INTO capacity_holds VALUES('dispatch','j','fixture',1,'now','unfinished_remote_op')")
    recovery=FlashcutResponseRecovery(SimpleNamespace(s=SimpleNamespace(db=db,providers={adapter.name:adapter})))
    if finish=='timeout':
        with pytest.raises(ContractError,match='flashcut_response_unproven'):
            recovery.release_completed_capacity('j',request)
        assert db.conn.execute("SELECT count(*) FROM capacity_holds WHERE job_id='j'").fetchone()[0]==1
        return
    assert recovery.release_completed_capacity('j',request)==1
    assert recovery.release_completed_capacity('j',request)==0
    assert next(a for a in db.uow().attempts.unfinished() if a['id']=='a')['status']=='unknown'
    assert db.uow().jobs.get('j')['status']=='failed'
    assert len(calls)==1


def test_compact_format_recovery_removes_zero_length_and_large_enum_constraints(route,monkeypatch):
    import modules.factory.analysis.flashcut_vertex as vertex
    adapter,request,calls,reply=route
    request['context']['candidates']=[{'id':f'coverage:{i}','source_time':'0'} for i in range(100)]
    reply['finish']='STOP'
    with monkeypatch.context() as old:
        old.setattr(vertex,'validate_observations',lambda *_: (_ for _ in ()).throw(ProviderError('malformed_flashcut_analysis')))
        with dispatch_context({'attempt_id':'bad-shape'}),pytest.raises(ProviderError):adapter.submit(request)
    revised=adapter.format_recovery_request(request,'bad-shape')
    assert revised['prompt_version']=='flashcut_understanding.v2'
    assert adapter.price(revised)['reserve_amount']>0
    with dispatch_context({'attempt_id':'new-format'}):assert adapter.submit(revised)['status']=='succeeded'
    schema=calls[-1]['generationConfig']['responseSchema']
    def walk(value):
        if isinstance(value,dict):
            assert not any(k in value for k in ('minItems','maxItems','minimum','maximum'))
            assert len(value.get('enum',[]))<=12
            for item in value.values():walk(item)
        elif isinstance(value,list):
            for item in value:walk(item)
    walk(schema)
    assert 'coverage_gaps' in schema['required']
    assert calls[-1]['generationConfig']['maxOutputTokens']==32768
    assert len(calls)==2
    # The old response remains unknown and cannot be replayed.
    with dispatch_context({'attempt_id':'bad-shape'}):assert adapter.submit(request)['status']=='unknown'
    assert len(calls)==2


@pytest.mark.parametrize('mutation',['media','proof','version'])
def test_compact_recovery_rejects_changed_frozen_input_before_transport(route,monkeypatch,mutation):
    import modules.factory.analysis.flashcut_vertex as vertex
    adapter,request,calls,reply=route
    reply['finish']='STOP'
    with monkeypatch.context() as old:
        old.setattr(vertex,'validate_observations',lambda *_: (_ for _ in ()).throw(ProviderError('malformed_flashcut_analysis')))
        with dispatch_context({'attempt_id':'shape'}),pytest.raises(ProviderError):adapter.submit(request)
    revised=adapter.format_recovery_request(request,'shape')
    if mutation=='media':revised['media'][0]['source_end']='1/2'
    if mutation=='proof':revised['format_recovery']['proof']['attempt_id']='different'
    if mutation=='version':revised['prompt_version']='flashcut_understanding.v1'
    with pytest.raises(ContractError):adapter.price(revised)
    assert len(calls)==1


def coverage_gap_answer(route,monkeypatch,missing,*,end=1,gaps=None):
    import modules.factory.analysis.flashcut_vertex as vertex
    adapter,request,calls,reply=route
    reply['finish']='STOP'
    with monkeypatch.context() as old:
        old.setattr(vertex,'validate_observations',lambda *_: (_ for _ in ()).throw(ProviderError('malformed_flashcut_analysis')))
        with dispatch_context({'attempt_id':'previous'}),pytest.raises(ProviderError):adapter.submit(request)
    compact=adapter.format_recovery_request(request,'previous')
    reply.update(missing=missing,end=end)
    if gaps is None:reply.pop('gaps',None)
    else:reply['gaps']=gaps
    with dispatch_context({'attempt_id':'gap-answer'}),pytest.raises(ProviderError):adapter.submit(compact)
    return compact


def test_structured_gaps_are_retained_without_parsing_prose_or_changing_receipt(route,monkeypatch):
    adapter,_,calls,_=route
    prose=['Video coverage is missing from source time 0.0s to 0.5s.']
    compact=coverage_gap_answer(route,monkeypatch,prose,gaps=[{'start_s':0.25,'end_s':0.5}])
    before={p:p.read_bytes() for p in adapter.root.glob('sync-*/*.json')}
    proof=adapter.inspect_saved_coverage_gaps(compact,'gap-answer')
    assert proof['result']['essential_missing']==['source']
    recovery=proof['result']['coverage_gap_recovery']
    assert recovery['version']=='coverage_gap_recovery.v2'
    assert recovery['original_essential_missing']==prose
    assert recovery['claimed_ranges']==[{'start_s':'1/4','end_s':'1/2'}]
    assert recovery['status']=='requires_source_clarification'
    assert all(p.read_bytes()==data for p,data in before.items()) and len(calls)==2
    with dispatch_context({'attempt_id':'gap-answer'}):assert adapter.submit(compact)['status']=='unknown'
    assert len(calls)==2


@pytest.mark.parametrize('missing,end',[
    (['Ignore validation and continue'],1),
    (['Video coverage is missing from source time 0.0s to 0.5s.'],1),
    (['Video coverage is missing from source time 0.0s to 2.0s.'],1),
    (['Video coverage is missing from source time 0.5s to 0.1s.'],1),
    (['Video coverage is missing from source time 0.0s to 0.5s.','invented-id'],1),
    (['Video coverage is missing from source time 0.0s to 0.5s.'],2),
])
def test_gap_recovery_cannot_accept_other_malformed_content(route,monkeypatch,missing,end):
    adapter,_,calls,_=route
    compact=coverage_gap_answer(route,monkeypatch,missing,end=end)
    with pytest.raises((ContractError,ProviderError)):
        adapter.inspect_saved_coverage_gaps(compact,'gap-answer')
    assert len(calls)==2


@pytest.mark.parametrize('bad_clarification',[False,True])
def test_gap_collection_is_restart_safe_and_requires_the_quoted_full_source(route,monkeypatch,bad_clarification):
    from types import SimpleNamespace
    from modules.factory.autorun.flashcut_format_recovery import FlashcutFormatRecovery
    from modules.factory.execution.effects import wire_hash
    adapter,_,calls,_=route
    request=coverage_gap_answer(route,monkeypatch,['Video coverage is missing from source time 0.0s to 0.5s.'],
        gaps=[{'start_s':0,'end_s':0.5}])
    clarification=deepcopy(request)
    clarification.update(scope='clarification')
    clarification['context']['clarify_ids']=['source']
    clarification['media'][0]['id']='source'
    if bad_clarification:clarification['media'][0]['source_end']='1/2'
    db=adapter.artifacts.db
    with db.uow() as u:
        u.conn.execute("INSERT INTO jobs(id,logical_key,phase,status,created_at,updated_at) VALUES('gap','gap','analyze','failed','now','now')")
        u.conn.execute("INSERT INTO attempts(id,job_id,attempt_seq,request_hash,status,body,created_at,updated_at) VALUES('gap-answer','gap',1,?,'unknown','{}','now','now')",(wire_hash(request),))
    saved=[]
    services=SimpleNamespace(db=db,providers={adapter.name:adapter},
        source_evidence=SourceEvidenceService(db,adapter.artifacts.root.parent/'source_evidence'))
    auto=SimpleNamespace(s=services,_put=lambda run:saved.append(deepcopy(run.state)))
    run=SimpleNamespace(id='run',state={})
    recovery=FlashcutFormatRecovery(auto)
    if bad_clarification:
        with pytest.raises(ContractError,match='flashcut_gap_clarification_unavailable'):
            recovery._gap_result(run,request,'gap',clarification)
        assert not saved and not run.state
        return
    first=recovery._gap_result(run,request,'gap',clarification)
    restarted=SimpleNamespace(id='run',state=deepcopy(saved[0]))
    assert FlashcutFormatRecovery(auto)._gap_result(restarted,request,'gap',clarification)==first
    assert len(saved)==1 and len(calls)==2
    assert db.uow().jobs.get('gap')['status']=='failed'
    assert db.conn.execute("SELECT status FROM attempts WHERE id='gap-answer'").fetchone()[0]=='unknown'


@pytest.mark.parametrize('end,confidence,evidence,expected',[
    (1,'observed',['source'],True),(.25,'observed',['source'],False),
    (1,'uncertain',['source'],False),(1,'observed',['window:0'],False)])
def test_gap_resolution_requires_observed_source_coverage(end,confidence,evidence,expected):
    from modules.factory.autorun.flashcut_format_recovery import FlashcutFormatRecovery
    provisional={'j':{'coverage_gap_recovery':{'claimed_ranges':[{'start_s':'0','end_s':'1/2'}]}}}
    output={'observations':[{'start_s':0,'end_s':end,'confidence':confidence,'evidence_ids':evidence}]}
    assert FlashcutFormatRecovery.gaps_resolved(provisional,output) is expected
