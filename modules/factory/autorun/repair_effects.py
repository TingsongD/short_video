"""A paid repair with an uncertain outcome needs reconciliation, not replay."""


def check(service, run, jobs, failure):
    for jid in jobs:
        row = service.s.db.conn.execute("SELECT id FROM attempts WHERE job_id=? AND status IN ('unknown','dispatching')", (jid,)).fetchone()
        if row:
            return ('pause', 'repair_outcome_unknown', f'Attempt {row[0]} has an uncertain provider outcome.',
                    'Reconcile this existing operation before resuming. No replacement request will be submitted.')
    return service._jobs(run, jobs, failure)
