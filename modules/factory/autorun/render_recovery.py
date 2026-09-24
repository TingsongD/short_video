"""Re-quote a repaired native author package without rebuying unchanged media."""
from ..domain.errors import ContractError


def rebind_author_package(auto, run, current):
    if (run.stage != 'compose' or run.pause.get('code') != 'render_failed'
            or run.params.get('workflow', {}).get('version') != 2
            or not current.packaging.get('flashcut_policy')
            or not run.state.get('plan_id')):
        return
    s, prior_id = auto.s, run.state['plan_id']
    bindings = [n.get('request', {}).get('output_binding')
                for n in s.production._nodes(prior_id).values() if n['kind'] == 'compose']
    if not bindings or not bindings[0] or any(b != bindings[0] for b in bindings):
        raise ContractError('stale_editorial_plan', 'output_binding')
    from ..services.editorial_work import output_binding
    prior, current_binding = bindings[0], output_binding(s, current)
    if prior == current_binding:
        return
    if ({k:v for k,v in prior.items() if k != 'author_package_hash'} !=
            {k:v for k,v in current_binding.items() if k != 'author_package_hash'}):
        raise ContractError('stale_editorial_plan', 'output_binding',
                            'Only an author package repair can resume the same draft.')
    jobs = s.db.conn.execute('SELECT * FROM jobs WHERE experiment_id=? AND id LIKE ?',
                            (run.state['experiment_id'], prior_id + ':%')).fetchall()
    retire = []
    for job in jobs:
        uncertain = s.db.conn.execute("SELECT 1 FROM attempts WHERE job_id=? AND status NOT IN "
            "('succeeded','downloaded','failed','cancelled')", (job['id'],)).fetchone()
        held = any(s.db.conn.execute(f'SELECT 1 FROM {table} WHERE job_id=?',
                   (job['id'],)).fetchone() for table in ('capacity_holds', 'remote_holds'))
        queued = (job['phase'] in ('render','deliver') and job['status'] in
                  ('ready','waiting_dependencies','blocked') and not job['lease_owner'])
        if uncertain or held or (not queued and job['status'] not in
                                ('succeeded','failed','cancelled')):
            raise ContractError('prior_render_inflight', 'job_id', job['id'])
        if queued:
            retire.append(job['id'])
    with s.db.uow() as u:
        for jid in retire:
            u.conn.execute("UPDATE jobs SET status='cancelled',blocked_reason='author_package_replaced' WHERE id=?", (jid,))
            u.events.append('job:' + jid, 'obsolete_local_work_retired',
                            {'prior_plan_id': prior_id, 'reason': 'author_package_repair'})
        proof = {'prior_plan_id': prior_id, 'prior_binding': prior, 'current_binding': current_binding}
        u.events.append('plan:' + prior_id, 'author_package_requote_requested', proof)
    for key in ('quote_job','plan_id','authorize_job','run_job','production_jobs',
                'qc_submitted','qc_resubmitted','qc_rechecks','qc_flagged','qc_human_accepted',
                'qc_human_bindings','qc_human_reviews','delivery_jobs','completion_phases'):
        run.state.pop(key, None)
    for key in list(run.state):
        if key.startswith('qc_verdict_') or (key.startswith('qc_') and key.endswith(('_jobs','_plan','_auth'))):
            run.state.pop(key, None)
    run.state.setdefault('author_package_rebuilds', []).append(proof)
    run.stage = 'quote'
    run.notes.append('Renderer package repaired; re-quote the same draft and verified selected footage before rendering again.')
