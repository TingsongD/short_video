from types import SimpleNamespace
from modules.factory.autorun.flashcut import FlashcutAnalysis
from modules.factory.store import Database


def test_analysis_status_reads_current_retry_time_and_clears_finished_wait(tmp_path):
    db=Database(tmp_path/'db')
    with db.uow() as u:
        u.conn.execute("INSERT INTO jobs(id,logical_key,phase,status,blocked_reason,next_attempt_at,created_at,updated_at) VALUES('j','j','analyze','ready','analysis_throttled','current','now','now')")
    run=SimpleNamespace(status='running',state={'provider_wait':{
        'job_id':'j','reason':'analysis_throttled','next_attempt_at':'stale'}})
    analysis=FlashcutAnalysis(SimpleNamespace(s=SimpleNamespace(db=db)))
    assert analysis.status(run)['next_attempt_at']=='current'
    with db.uow() as u:u.conn.execute("UPDATE jobs SET status='succeeded' WHERE id='j'")
    status=analysis.status(run)
    assert 'next_attempt_at' not in status and status['state']=='processing'
    assert run.state['provider_wait']['next_attempt_at']=='stale'
    db.close()
