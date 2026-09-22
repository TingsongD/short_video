"""Complete future reference preparation with real services; remote I/O mocked."""
import hashlib
import json
import pytest
from pathlib import Path

from test_factory_autorun import (application, stack, make_seed, launch, autorun, EXPIRY)
from modules.factory.providers.catalog import CapabilityCatalog, CapabilitySnapshot, snapshot_id
from modules.factory.testing.durable import DiskGeneration
from modules.factory.testing.fixtures import _moving_mp4


@pytest.mark.parametrize('overlay_limit', [None, 0, 1])
def test_first_clip_reference_work_is_reused_across_worker_reentry(application, overlay_limit):
    s, _, act, worker, root = stack(application)
    class ReferenceRemote(DiskGeneration):
        def capabilities(self, model):
            return {**super().capabilities(model), 'references': {'image': 3},
                    'qualified_modes':['text','image_ref'], 'reference_enabled':True}
        def download(self, oid, destination=None):
            row = self.poll(oid)
            req = row['request']
            target = root / ('ref-' + oid + '.mp4')
            if not target.exists():
                _moving_mp4(target, req['duration_s'], size='180x320', color={'A':'red','B':'green','C':'blue','D':'yellow'}[req['variant_identity']])
            raw = target.read_bytes()
            return {'bytes':raw, 'sha256':hashlib.sha256(raw).hexdigest()}
    provider = ReferenceRemote(root, name='google_vertex')
    s.providers['google_vertex'] = provider
    for mode in ('text', 'image_ref'):
        CapabilityCatalog(s.db).put(CapabilitySnapshot(schema_version='capability_snapshot.v1',
            created_at='2026-09-21T00:00:00Z',
            id=snapshot_id('google_vertex','fixture-fast','',mode), provider='google_vertex', model='fixture-fast',
            input_mode=mode, support='qualified', capabilities=provider.capabilities('fixture-fast'), valid_until=EXPIRY))
    analyzer = s.providers['audiovisual_analysis']
    original = analyzer.transport
    def transport(method, url, payload, headers):
        body = json.loads(payload)
        text = ''.join(p.get('text','') for p in body['contents'][0]['parts'])
        if 'OVERLAY_QC_V1' in text:
            result = {'verdict':'pass','overlay':'none','notes':['Offline fixture is clean']}
            if overlay_limit is not None:
                result = {'verdict':'fail', 'overlay':'unwanted', 'notes':['Confirmed subtitles'],
                          'issues':[{'start_s':0, 'end_s':1, 'observation':'Superimposed title covering frame'}]}
            return 200, {}, json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(result)}]}}]}).encode()
        if 'Validate this extracted frame' not in text:
            return original(method, url, payload, headers)
        result = {'verdict':'pass','roles':['dog'],'notes':['Offline visual validator fixture']}
        return 200, {}, json.dumps({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(result)}]}}]}).encode()
    analyzer.transport = transport
    from modules.factory.autorun.policies import new_policies
    run = launch(act, make_seed(act, root), provider='vertex', generation_model='fixture-fast',
                 reference_policy='first_clip.v1', policies=new_policies(
                     {'overlay_repairs': overlay_limit} if overlay_limit is not None else None), generate_music=False)
    premature_checked = False
    for _ in range(400):
        out = worker.tick()
        if out is None:
            from datetime import timedelta
            due = s.scheduler.clock() + timedelta(seconds=30)
            s.scheduler.clock = lambda: due
        current = autorun(s, run['id'])
        if current.experiment_id and not current.state.get('reference_bindings') and not premature_checked:
            response = act('post', f'/api/experiments/{current.experiment_id}/quote', {}, rev=current.state['experiment_revision'])
            assert response.status_code == 400 and response.json()['error'] == 'reference_preparation_pending', response.text
            premature_checked = True
        if current.status == 'paused' or current.state.get('plan_id'):
            break
    if overlay_limit is not None:
        assert current.status == 'paused' and current.pause['code'] == 'reference_overlay_exhausted', current.pause
        assert len(list(provider.remote.glob('*.json'))) == overlay_limit + 1
        return
    assert current.state.get('plan_id') and current.status != 'paused', current.pause
    assert premature_checked
    repeated = act('post', f'/api/experiments/{current.experiment_id}/quote', {}, rev=current.state['experiment_revision'])
    assert repeated.status_code in (200,202), repeated.text
    assert len(current.state['reference_bindings']) == 12
    ops = [json.loads(p.read_text()) for p in provider.remote.glob('*.json')]
    assert len(ops) == 12
    for key in 'ABCD':
        by_scene = {o['request']['scene_id']: o['request'] for o in ops if o['request']['variant_identity'] == key}
        assert not by_scene['b0']['reference_artifact_ids']
        assert by_scene['b1']['reference_hashes'] == by_scene['b2']['reference_hashes']
        assert by_scene['b1']['reference_artifact_ids']
    refs = [o['request']['reference_hashes'] for o in ops if o['request']['scene_id'] == 'b1']
    assert len({json.dumps(r,sort_keys=True) for r in refs}) == 4
    from modules.factory.creative.references import prepare
    assert prepare(s.autorun, current) is None
    assert len(list(provider.remote.glob('*.json'))) == 12
    # A harmless draft revision adopts exact completed footage, with original
    # effect receipts intact, rather than charging for another twelve clips.
    s.autorun._pause(current, 'fixture_pause', 'Offline revision exercise', 'Resume after edit')
    edited = act('patch',f'/api/experiments/{current.experiment_id}/draft',
                 {'reason':'Offline metadata-only revision'},rev=current.state['experiment_revision'])
    assert edited.status_code == 200, edited.text
    resumed = act('post', f'/api/autoruns/{current.id}/resume', {})
    assert resumed.status_code == 200, resumed.text
    from test_factory_autorun import drive
    drive(s, worker)
    current = autorun(s, run['id'])
    assert current.status == 'succeeded', current.pause
    assert len(s.experiment_results(current.experiment_id)['variants']) == 4
    assert len(list(provider.remote.glob('*.json'))) == 12
    assert {b['adopted_into_revision'] for b in current.state['reference_bindings'].values()} == {current.state['experiment_revision']}
