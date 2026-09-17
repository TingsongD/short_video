"""Explicit local retry and manual replacement; neither creates paid attempts."""
import json
from ..domain.errors import ContractError
from ..store.uow import utcnow


def unblock_descendants(u,root_id):
    """Only dependencies made satisfiable by this root advancing will
    leave 'blocked'; the walk is transitive so a whole chain reopens."""
    changed={root_id}
    while True:
        pending=u.conn.execute("SELECT id,depends_on FROM jobs WHERE status='blocked'").fetchall()
        children=[r['id'] for r in pending if set(json.loads(r['depends_on'])) & changed]
        if not children:break
        for child in children:u.conn.execute("UPDATE jobs SET status='waiting_dependencies',blocked_reason=NULL WHERE id=?",(child,))
        changed.update(children)
    return changed


def retry_local(s,jid,reviewer):
    if not reviewer:raise ContractError('reviewer_required','reviewer')
    job=s.db.uow().jobs.get(jid)
    if not job or job['status'] not in ('failed','blocked'):raise ContractError('job_not_retryable','job_id')
    if job['retry_count']>=5:raise ContractError('retries_exhausted','job_id')
    if s.db.conn.execute('SELECT 1 FROM attempts WHERE job_id=?',(jid,)).fetchone():
        raise ContractError('reconcile_original_required','job_id','Use observation of the original effect; paid replacement needs a new reviewed plan')
    if job['phase'] not in ('render','collect'):raise ContractError('new_plan_required','job_id')
    row=s.db.uow().records.get('workitem',jid)
    if row:
        node=json.loads(row['body']);plan=s.production._plan(node['plan_id'])
        s._current(plan['experiment_id'],plan['experiment_revision'],True)
        owners=[plan['experiment_id']+':'+v.lower() for v in node.get('consumers',[])]
        for owner in owners:
            receipt=s.cleanup.cleanup(owner)
            if receipt['state']!='verified':raise ContractError('cleanup_incomplete','retry')
    elif job['phase']=='render':
        # Speech fitting has no detached renderer; its worker-owned job may retry.
        command=s.commands.get(jid)['command']
        if not command or command['kind']!='speech_fit':raise ContractError('manual_recovery_required','job_id')
    with s.db.uow() as u:
        u.conn.execute('DELETE FROM meta WHERE key=?',('local_work:'+jid,))
        u.conn.execute('DELETE FROM capacity_holds WHERE job_id=?',(jid,))
        u.conn.execute("UPDATE jobs SET status='waiting_dependencies',lease_owner=NULL,lease_expires=NULL,next_attempt_at=NULL,blocked_reason=NULL,retry_count=retry_count+1 WHERE id=?",(jid,))
        unblock_descendants(u,jid)
        u.events.append('factory','local_retry_requested',{'job_id':jid,'reviewer':reviewer,'at':utcnow()})
    return {'job_id':jid,'accepted':True}


def manual_replace(s,eid,revision,body):
    s._current(eid,revision,True);plan=s.plan_for(eid)
    if not body.get('reviewer') or body.get('plan_hash')!=plan['plan_hash']:raise ContractError('approval_mismatch','reviewer/plan_hash')
    node=s.production._node(plan['id'],body.get('node_key',''))
    if not node or node['kind']!='picture':raise ContractError('unknown_picture_node','node_key')
    result=s.production.replace_manual(plan['id'],node['node_key'],body.get('artifact_id',''))
    with s.db.uow() as u:u.events.append('factory','manual_picture_replacement',{'reviewer':body['reviewer'],'plan_id':plan['id'],'node':node['node_key']})
    return result


def release_local(s,jid,reviewer):
    if not reviewer:raise ContractError('reviewer_required','reviewer')
    job=s.db.uow().jobs.get(jid)
    if not job or job['status'] not in ('failed','blocked') or job['phase']!='render':raise ContractError('job_not_releasable','job_id')
    node=s.detail('workitem',jid);plan=s.production._plan(node['plan_id']);receipts=[]
    for key in node['consumers']:
        receipt=s.cleanup.cleanup(plan['experiment_id']+':'+key.lower())
        if receipt['state']!='verified':raise ContractError('cleanup_incomplete','local_work')
        receipts.append(receipt)
    with s.db.uow() as u:
        u.conn.execute('DELETE FROM meta WHERE key=?',('local_work:'+jid,))
        u.conn.execute('DELETE FROM capacity_holds WHERE job_id=?',(jid,))
        u.events.append('factory','failed_local_work_released',{'job_id':jid,'reviewer':reviewer,'cleanup':receipts})
    return {'released':True,'job_id':jid,'cleanup':receipts}
