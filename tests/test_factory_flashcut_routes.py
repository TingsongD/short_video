import json
import pytest
from test_factory_autorun import application,stack,launch,make_seed
from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.providers.configured import configured_auxiliary
from modules.factory.store import Database


def test_new_routes_cannot_inherit_legacy_qualification(tmp_path):
    db=Database(tmp_path/'db')
    try:
        artifacts=ArtifactStore(tmp_path/'artifacts',db)
        base={'account_id':'test@example.invalid','project':'test','model':'gemini-3.8-flash',
              'qualified_until':'2099-01-01T00:00:00Z','contract_evidence':'fixture','live_evidence':'fixture',
              'pricing':{'estimate_usd_micros':100,'reserve_usd_micros':100,'evidence':'fixture','valid_until':'2099-01-01T00:00:00Z'}}
        data={'enabled':['audiovisual_analysis','audiovisual_analysis_flashcut','jev_decisions'],
              'audiovisual_analysis':base}
        (tmp_path/'connections.json').write_text(json.dumps(data))
        routes,_,_,_=configured_auxiliary(tmp_path,tmp_path,'live',artifacts)
        assert set(routes)=={'audiovisual_analysis'}
        new={**base,'pricing':{'input_usd_micros_per_million':750000,'output_usd_micros_per_million':3750000,
                              'evidence':'fixture','valid_until':'2099-01-01T00:00:00Z'}}
        data['audiovisual_analysis_flashcut']=new
        data['jev_decisions']={**base,'model':'jev-1.13.0','pricing':{
            'input_usd_micros_per_million':42000,'evidence':'fixture','valid_until':'2099-01-01T00:00:00Z'}}
        (tmp_path/'connections.json').write_text(json.dumps(data))
        routes,_,_,_=configured_auxiliary(tmp_path,tmp_path,'live',artifacts)
        assert set(routes)=={'audiovisual_analysis','audiovisual_analysis_flashcut','jev_decisions'}
        assert routes['audiovisual_analysis_flashcut'].transport.capability=='audiovisual_analysis_flashcut'
        assert configured_auxiliary(tmp_path,tmp_path,'offline',artifacts)[0]=={}
    finally:
        db.close()


def test_first_live_qualification_is_not_inherited_by_other_runs(application):
    from modules.factory.providers.preflight import RequestNotSent
    from modules.factory.autorun.readiness import provider_ready
    s,_,act,_,root=stack(application)
    seed=make_seed(act,root);run=launch(act,seed,profile_id='flashcut_hypit.v1')
    art=s.db.uow().artifacts.get(s.seeds.get(seed).source_asset_id)
    connection={'account_id':'fixture','project':'fixture','model':'gemini-3.8-flash',
        'contract_evidence':'offline-fixture','pricing':{'input_usd_micros_per_million':1,'output_usd_micros_per_million':1},
        'acceptance_scope':{'run_id':run['id'],'seed_id':seed,'source_sha256':art['sha256'],'valid_until':'2099-01-01T00:00:00Z'}}
    (root/'connections.json').write_text(json.dumps({'enabled':['audiovisual_analysis_flashcut'],
        'audiovisual_analysis_flashcut':connection}))
    routes,*_=configured_auxiliary(root,root,'live',s.artifacts)
    route=routes['audiovisual_analysis_flashcut']
    assert route.qualified is False
    assert route.acceptance_run_id==run['id']
    # A known completed source record from another run cannot be substituted.
    from modules.factory.analysis.source_evidence import SourceEvidenceService
    from test_factory_source_evidence import binding
    store=SourceEvidenceService(s.db,root/'source_evidence')
    frozen={**binding(),'source_sha256':art['sha256'],'seed_id':seed}
    evidence=store.create('other-run',frozen,{'version':'test.v1'})
    for stage in ('clock','visual','audio','fusion'):
        store.chunk(evidence['id'],stage,0,1,lambda:{},current_binding=frozen)
    saved=store.complete(evidence['id'],{s:1 for s in ('clock','visual','audio','fusion')},current_binding=frozen)
    with pytest.raises(RequestNotSent,match='flashcut_acceptance_scope_mismatch'):
        route.acceptance_guard({'binding':{'evidence_sha256':saved['manifest']['sha256'],
            'source_sha256':art['sha256'],'transcript_sha256':frozen['transcript_sha256']}})
    oldmode=s.config['mode'];s.config['mode']='live'
    try:
        s.providers.update(routes)
        assert provider_ready(s,route.name,run_id='other-run')[1]=='flashcut_acceptance_scope_mismatch'
    finally:s.config['mode']=oldmode
    connection['acceptance_scope']['valid_until']='2000-01-01T00:00:00Z'
    (root/'connections.json').write_text(json.dumps({'enabled':[route.name],route.name:connection}))
    assert route.name not in configured_auxiliary(root,root,'live',s.artifacts)[0]


def test_contract_evidence_alone_never_enables_first_paid_request(tmp_path):
    db=Database(tmp_path/'db')
    try:
        artifacts=ArtifactStore(tmp_path/'artifacts',db)
        connection={'account_id':'fixture','project':'fixture','model':'gemini-3.8-flash',
            'contract_evidence':'offline-only','qualified_until':'2099-01-01T00:00:00Z','pricing':{}}
        (tmp_path/'connections.json').write_text(json.dumps({'enabled':['audiovisual_analysis_flashcut'],
            'audiovisual_analysis_flashcut':connection}))
        assert configured_auxiliary(tmp_path,tmp_path,'live',artifacts)[0]=={}
    finally:db.close()


@pytest.mark.parametrize('dotenv,expected_key',[
    ('JEV_API_KEY=fake-alias-key\n','fake-alias-key'),
    ('TYPESAFE_API_KEY=fake-existing-key\n','fake-existing-key'),
    ('TYPESAFE_API_KEY=fake-existing-key\nJEV_API_KEY=fake-alias-key\n','fake-existing-key'),
    ('TYPESAFE_API_KEY=\nJEV_API_KEY=fake-alias-key\n','fake-alias-key'),
])
def test_jev_configured_credentials_reach_readiness_and_authorized_transport(tmp_path, monkeypatch, dotenv, expected_key):
    from modules.factory.execution.context import dispatch_context
    from modules.factory.providers.preflight import RequestNotSent
    from test_factory_jev import request

    monkeypatch.delenv('JEV_API_KEY', raising=False)
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    (tmp_path/'.env').write_text(dotenv)
    connection={'account_id':'offline-fixture','model':'jev-1.13.0',
        'qualified_until':'2099-01-01T00:00:00Z','contract_evidence':'fixture',
        'live_evidence':'fixture','pricing':{'input_usd_micros_per_million':42000}}
    (tmp_path/'connections.json').write_text(json.dumps({
        'enabled':['jev_decisions'],'jev_decisions':connection}))
    routes,*_=configured_auxiliary(tmp_path,tmp_path,'live')
    route=routes['jev_decisions']
    calls=[]

    def transport(method,url,body,headers):
        calls.append(1)
        assert headers['Authorization']=='Bearer '+expected_key
        return 200,{},json.dumps({'model':'jev-1.13.0','answers':{'audio:1':{
            'type':'choice','choice':'retain','probabilities':{'retain':1,'optional':0},
            'confidence':1}},'usage':{'input_tokens':100,'output_tokens':20}}).encode()

    route.transport=transport
    readiness=route.readiness()
    assert readiness['credential_present'] is True
    assert readiness['authenticated'] is False and calls==[]
    with pytest.raises(RequestNotSent,match='authority_required'):
        route.execute(request())
    assert calls==[]
    with dispatch_context({'provider':'jev_decisions'}):
        result,_,_=route.execute(request())
    assert result['decisions']=={'audio:1':'retain'} and calls==[1]
