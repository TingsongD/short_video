import json
import pytest

from test_factory_production import stack, NOW
from modules.factory.domain.errors import ContractError


def planned(svc,ident,revision,variant='A',prompt='same'):
    return svc.plan(ident,'flash-exp',revision,[{'variant':variant,'slot':'s1','duration_s':4,
        'request':{'prompt':prompt,'settings':{},'refs':[]}}],
        'jimeng_canvas','seedance_2.0_fast_vip',[4,8],now=NOW,
        output_binding={'editorial_manifest':{'sha256':str(revision)*64},'policy_hash':'a'*64})


def picture(result):
    return next(n for n in result['nodes'].values() if n['kind']=='picture')


def test_changed_editorial_plan_reuses_verified_same_variant_footage(stack):
    db,_,_,_,arts,svc=stack
    original=picture(planned(svc,'first',1))
    clip=arts.intake_file(arts.root.parent/'clip.mp4','jimeng_canvas','generated-fixture')
    svc._set('first',original['node_key'],status='accepted',artifact_ids=[clip.id])
    revised=picture(planned(svc,'second',2))
    assert revised['status']=='manual'
    assert revised['artifact_ids']==[clip.id]
    assert revised['price']=={}
    assert planned(svc,'third',3)['plan']['total_price']=={}
    assert svc._node('first',original['node_key'])['status']=='accepted'


def test_reuse_never_crosses_variant_or_changed_generation_request(stack):
    _,_,_,_,arts,svc=stack
    original=picture(planned(svc,'first',1))
    clip=arts.intake_file(arts.root.parent/'clip.mp4','jimeng_canvas','generated-fixture')
    svc._set('first',original['node_key'],status='accepted',artifact_ids=[clip.id])
    assert picture(planned(svc,'second',2,variant='B'))['status']=='planned'
    assert picture(planned(svc,'third',3,prompt='changed'))['status']=='planned'


def test_corrupt_prior_footage_is_not_silently_regenerated(stack):
    _,_,_,_,arts,svc=stack
    original=picture(planned(svc,'first',1))
    clip=arts.intake_file(arts.root.parent/'clip.mp4','jimeng_canvas','generated-fixture')
    svc._set('first',original['node_key'],status='accepted',artifact_ids=[clip.id])
    arts.path_for(clip.id).write_bytes(b'corrupt fixture')
    with pytest.raises(ContractError):planned(svc,'second',2)


def test_new_editorial_revision_cannot_resubmit_unknown_footage(stack):
    from modules.factory.testing.authority import approve_production
    from modules.factory.execution.effects import EffectService
    from modules.factory.testing.fakes import ProviderError
    _,scheduler,provider,_,_,svc=stack
    original=picture(planned(svc,'first',1))
    authority=approve_production(svc,'first')
    svc.submit('first');job=scheduler.claim()
    attempt=EffectService(svc.db,svc.executor).prepare(authority,original['node_key']+':0',
        job['id'],job['fencing_token'],scheduler.worker_id,1)
    with pytest.raises(ProviderError):
        svc.executor.submit(attempt,lambda:provider.submit({'fixture':1},faults=('accept-then-timeout',)))
    with pytest.raises(ContractError,match='prior_footage_unresolved'):
        planned(svc,'second',2)


def test_legacy_plan_does_not_adopt_new_reuse_policy(stack):
    _,_,_,_,arts,svc=stack
    original=picture(planned(svc,'first',1))
    clip=arts.intake_file(arts.root.parent/'clip.mp4','jimeng_canvas','generated-fixture')
    svc._set('first',original['node_key'],status='accepted',artifact_ids=[clip.id])
    result=svc.plan('legacy','flash-exp',2,[{'variant':'A','slot':'s1','duration_s':4,
        'request':{'prompt':'same','settings':{},'refs':[]}}],
        'jimeng_canvas','seedance_2.0_fast_vip',[4,8],now=NOW)
    assert picture(result)['status']=='planned'
