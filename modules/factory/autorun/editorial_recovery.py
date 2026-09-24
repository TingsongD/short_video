"""Adopt a locally validated edit plan after a proven capped provider answer."""
import hashlib
import json
from ..analysis.editorial_planning import PlanningStore, conservative_editorial_response
from ..domain.errors import ContractError
from ..execution.effects import wire_hash
from ..services.editorial_work import planning_input


def completed_editorial_response(adapter, request, attempt_id):
    folder=adapter.root/('sync-'+hashlib.sha256(attempt_id.encode()).hexdigest()[:32])
    try:
        receipt_bytes=(folder/'receipt.json').read_bytes()
        response_bytes=(folder/'provider-response.json').read_bytes()
        receipt,saved=json.loads(receipt_bytes),json.loads(response_bytes)
        candidates=saved['response']['candidates']
        digest=wire_hash(request)
        if (request.get('task')!='plan_flashcut_edits' or request.get('model')!=adapter.model
                or receipt.get('status')!='unknown' or receipt.get('request')!=request
                or receipt.get('request_hash')!=digest or saved.get('request_hash')!=digest
                or saved.get('attempt_id')!=attempt_id or saved.get('http_status')!=200
                or len(candidates)!=1 or candidates[0].get('finishReason')!='MAX_TOKENS'
                or saved['response'].get('promptFeedback',{}).get('blockReason')
                or not isinstance(saved.get('response_sha256'),str) or len(saved['response_sha256'])!=64):
            raise ValueError()
        return {'attempt_id':attempt_id,'request_hash':digest,'response_sha256':saved['response_sha256'],
                'saved_response_sha256':hashlib.sha256(response_bytes).hexdigest(),
                'receipt_sha256':hashlib.sha256(receipt_bytes).hexdigest(),'finish_reason':'MAX_TOKENS'}
    except (OSError,ValueError,KeyError,TypeError):
        raise ContractError('editorial_response_unproven','completed_response') from None


def adopt_local_plan(auto,run,review):
    if (run.status!='paused' or run.stage!='quote' or not isinstance(review,dict)
            or review.get('reviewer_type') not in ('assistant','human')
            or not isinstance(review.get('reviewer'),str) or not review['reviewer'].strip()):
        raise ContractError('editorial_recovery_unavailable','run/reviewer')
    s=auto.s
    from ..domain.records import content_hash
    exp=s._current(run.experiment_id,run.state['experiment_revision'],True)
    inputs,binding,evidence=planning_input(s,exp)
    suffix=content_hash(binding)[:16]
    jobs=[j for tag in ('editorial_'+suffix,'editorial_v2_'+suffix) for j in run.state.get(tag+'_jobs',[])]
    if len(jobs)!=1:
        raise ContractError('editorial_response_unproven','job')
    jid=jobs[0];job=s.db.uow().jobs.get(jid)
    attempts=list(s.db.conn.execute("SELECT * FROM attempts WHERE job_id=? AND status NOT IN ('failed','cancelled','succeeded')",(jid,)))
    if (not job or job['status']!='failed' or len(attempts)!=1 or attempts[0]['status']!='unknown'
            or attempts[0]['remote_id'] or s.db.conn.execute('SELECT 1 FROM remote_holds WHERE job_id=?',(jid,)).fetchone()):
        raise ContractError('editorial_response_unproven','attempt')
    attempt=attempts[0];adapter=s.providers['audiovisual_analysis_flashcut']
    folder=adapter.root/('sync-'+hashlib.sha256(attempt['id'].encode()).hexdigest()[:32])
    try:request=json.loads((folder/'receipt.json').read_text())['request']
    except (OSError,ValueError,KeyError,TypeError):
        raise ContractError('editorial_response_unproven','receipt') from None
    if (request.get('editorial_input')!=inputs or request.get('editorial_binding')!=binding
            or request.get('binding')!=evidence or wire_hash(request)!=attempt['request_hash']):
        raise ContractError('editorial_evidence_mismatch','current_input')
    proof=completed_editorial_response(adapter,request,attempt['id'])
    adapter.prepared(request)
    response=conservative_editorial_response(inputs)
    audit={'version':'editorial_local_adoption.v1','job_id':jid,'binding':binding,'proof':proof,
           'reviewer':review['reviewer'],'reviewer_type':review['reviewer_type'],
           'origin':'local_conservative','accounting':'unknown_retained','new_requests':0}
    ref=s.source_evidence.blobs.put(audit)
    previous=run.state.get('editorial_local_adoption')
    if previous and previous!=ref:
        old_binding = s.source_evidence.blobs.read(previous).get('binding', {})
        if (old_binding.get('experiment_id') != binding.get('experiment_id')
                or type(old_binding.get('revision')) is not int
                or old_binding['revision'] >= binding['revision']):
            raise ContractError('editorial_recovery_changed','audit')
    response['local_recovery_evidence']=ref
    store=PlanningStore(s.db,s.source_evidence.blobs.root)
    saved=store.save(binding,inputs,response)
    with s.db.uow() as u:
        u.conn.execute("DELETE FROM capacity_holds WHERE job_id=? AND capacity='dispatch' AND retained_reason='unfinished_remote_op'",(jid,))
        if previous != ref:
            if previous:
                history = run.state.setdefault('editorial_local_adoption_history', [])
                if previous not in history:
                    history.append(previous)
            u.events.append('autorun:'+run.id,'editorial_local_plan_adopted',{'evidence':ref,'manifest':saved['manifest'],'accounting':'unknown_retained'})
        run.state.update(editorial_local_adoption=ref,editorial_intent=saved['manifest'],
                         editorial_plan_origin='local_conservative')
        auto._put(run)
