"""Public API + worker reconciliation over local provider fixtures only."""
from test_factory_autorun import application, stack, make_seed, launch, drive
from modules.factory.diagnostics import service_logging
from modules.factory.domain.errors import ContractError
import json
import pytest


@pytest.mark.parametrize('stale_during_verify', [False, True])
def test_future_external_delivery_updates_queue_without_upload_or_creative_approval(application, stale_during_verify):
    s,c,act,w,root = stack(application)
    poll = s.providers['elevenlabs'].poll
    waiting = [True]
    def remote_poll(oid):
        if waiting[0]:
            waiting[0] = False
            raise ContractError('remote_unfinished', 'operation')
        return poll(oid)
    s.providers['elevenlabs'].poll = remote_poll
    run = launch(act, make_seed(act, root), generate_music=False)
    with service_logging(root, 'worker'):
        drive(s,w)
    logs = [json.loads(line) for line in (root/'.run/factory-worker.jsonl').read_text().splitlines()]
    assert any(r['event']=='job_waiting' for r in logs)
    assert not any(r['event']=='job_blocked' and r.get('code')=='remote_unfinished' for r in logs)
    current = s.autorun.get(run['id'])
    assert current.status == 'succeeded', current.pause
    variant = s.experiment_results(current.experiment_id)['variants'][0]
    final = variant['final']
    remote = s.delivery.drive
    path = s.artifacts.verified_path(final['artifact_id'])
    fid = remote.upload('folder', path, 'external-final.mp4')['id']
    count = len(remote.list_files('folder'))
    body = {'file_id':fid, 'name':'external-final.mp4', 'folder_id':'folder',
        'account':'fixture-drive', 'artifact_id':final['artifact_id'], 'target_hash':final['sha256']}
    route = f'/api/variants/{variant["id"]}/delivery/reconcile'
    stale = act('post', route, body, rev=0)
    assert stale.status_code == 409
    accepted = act('post', route, body, rev=variant['experiment_revision'], key='verify-once')
    assert accepted.status_code == 202, accepted.text
    if stale_during_verify:
        stat = remote.stat
        edited = []
        def change_revision(fid):
            if not edited:
                edited.append(True)
                response = act('patch',f'/api/experiments/{current.experiment_id}/draft',
                    {'reason':'new revision while remote verification is in flight'},rev=variant['experiment_revision'])
                assert response.status_code == 200, response.text
            return stat(fid)
        remote.stat = change_revision
    drive(s,w)
    assert act('post',route,body,rev=variant['experiment_revision'],key='verify-once').json() == accepted.json()
    receipts = c.get('/api/collections/deliveries').json()['items']
    assert len(receipts) == 1
    if stale_during_verify:
        assert receipts[0]['status'] != 'verified'
        assert len(remote.list_files('folder')) == count
        return
    assert receipts[0]['status'] == 'verified' and receipts[0]['provenance'] == 'external_verified'
    assert len(remote.list_files('folder')) == count
    assert not [r for r in s.collection('reviews') if r['check_type']=='creative']
    queue = c.get('/api/collections/queue').json()['items']['jobs']
    delivery_job = next(j for j in queue if j['id'] == final['plan_id']+':del:'+variant['variant_key'])
    assert delivery_job['status'] == 'succeeded'
