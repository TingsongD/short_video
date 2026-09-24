"""Retire obsolete local queue entries without touching paid outcomes."""


def retire_local_jobs(db, job_ids, experiment_id, prior_revision, current_revision):
    if current_revision <= prior_revision:
        return []
    retired = []
    with db.uow() as u:
        for jid in set(job_ids):
            job = u.jobs.get(jid)
            if (not job or job['experiment_id'] != experiment_id
                    or job['revision'] != prior_revision
                    or job['status'] not in ('ready', 'waiting_dependencies', 'awaiting_review')
                    or job['lease_owner']):
                continue
            # Even a queued job can own an unresolved paid attempt after a
            # crash. Neither queue state nor missing remote id proves safety.
            if u.conn.execute(
                    "SELECT 1 FROM attempts WHERE job_id=? AND status NOT IN "
                    "('succeeded','downloaded','failed','cancelled')", (jid,)).fetchone():
                continue
            if any(u.conn.execute(f'SELECT 1 FROM {table} WHERE job_id=?', (jid,)).fetchone()
                   for table in ('capacity_holds', 'remote_holds')):
                continue
            u.conn.execute("UPDATE jobs SET status='cancelled', blocked_reason=? WHERE id=?",
                           (f'superseded_by_revision:{current_revision}', jid))
            u.events.append(f'job:{jid}', 'obsolete_local_work_retired', {
                'experiment_id': experiment_id, 'prior_revision': prior_revision,
                'current_revision': current_revision, 'previous_status': job['status']})
            retired.append(jid)
    return retired
