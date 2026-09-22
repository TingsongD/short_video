"""Offline response timing, evidence retention and billable-failure recovery."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from modules.factory.analysis.vertex import VertexAnalyzer
from modules.factory.domain.errors import ContractError
from modules.factory.execution import Executor
from modules.factory.execution.context import dispatch_context
from modules.factory.providers.vertex_auth import VertexAuth
from modules.factory.testing.authority import approve_operation
from modules.factory.testing.fakes import ProviderError
from test_factory_api import env, mut


def test_analysis_response_wait_is_bounded_and_does_not_retry(tmp_path,monkeypatch):
    from modules.factory.execution.policy import ExecutionPolicy
    from modules.factory.integrations.http import BoundedHTTP
    policy=ExecutionPolicy('live',frozenset({'audiovisual_analysis','other'}))
    ad=VertexAnalyzer(tmp_path/'receipts',None,None,'a','p','m',{},policy=policy)
    waits=[]
    class Opener:
        def open(self,request,timeout):
            waits.append(timeout)
            raise TimeoutError('offline wait')
    monkeypatch.setattr('urllib.request.build_opener',lambda *args:Opener())
    with pytest.raises(TimeoutError):
        ad.transport('POST','https://example.invalid',b'{}')
    assert waits==[180]
    with pytest.raises(TimeoutError):
        BoundedHTTP('other',policy)('GET','https://example.invalid')
    assert waits==[180,60]


def payload():
    return {"beats": [{"id": "b1", "start_s": 0, "end_s": 4,
        "role": "hook", "confidence": "uncertain", "visual_event": "Motion"}],
        "transcript": [{"id": "t1", "start_s": 0, "end_s": 4,
            "text": "One small step", "words": [
                {"text": "One", "start_s": 0, "end_s": 1},
                {"text": "small", "start_s": 3, "end_s": 3},
                {"text": "step", "start_s": 3.1, "end_s": 3.8}]}],
        "music": {"role": "bed"}, "uncertainty": []}


def analyzer(tmp_path, monkeypatch, response):
    src = tmp_path / "source.mp4"
    src.write_bytes(b"offline video bytes")
    sha = hashlib.sha256(src.read_bytes()).hexdigest()
    arts = SimpleNamespace(
        verified_path=lambda _: src, path_for=lambda _: src,
        db=SimpleNamespace(uow=lambda: SimpleNamespace(artifacts=SimpleNamespace(
            get=lambda _: {"kind": "video", "sha256": sha}))))
    monkeypatch.setattr("modules.factory.media.probe.probe", lambda _: SimpleNamespace(
        format_name="mp4", duration_s=4))
    calls = []
    def transport(method, url, body, headers):
        calls.append(json.loads(body))
        return 200, {}, json.dumps({"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": json.dumps(response)}]}}],
            "usageMetadata": {"totalTokenCount": 100}}).encode()
    auth = VertexAuth(lambda: {"kind": "oauth", "access_token": "offline-token",
        "project": "p", "scopes": ["cloud-platform"]}, "p")
    ad = VertexAnalyzer(tmp_path / "receipts", arts, auth, "a", "p", "m",
        {"estimate_usd_micros": 250000, "reserve_usd_micros": 250000,
         "evidence": "offline", "valid_until": "2999-01-01"}, transport=transport)
    req = {"task": "analyze", "model": "m", "artifact_id": "art",
           "artifact_sha256": sha}
    return ad, req, calls


def test_zero_duration_optional_words_do_not_invent_timing(tmp_path, monkeypatch):
    original = payload()
    ad, req, calls = analyzer(tmp_path, monkeypatch, original)
    with dispatch_context({"attempt_id": "att:timing:1"}):
        result = ad.submit(req)["result"]
    assert result["beats"] == original["beats"]
    assert result["transcript"][0]["text"] == "One small step"
    assert result["transcript"][0]["words"] == []
    assert any("word timing" in note and "zero-duration" in note for note in result["uncertainty"])
    assert len(calls) == 1
    prompt = calls[0]["contents"][0]["parts"][-1]["text"]
    assert "4.000" in prompt and "end_s > start_s" in prompt
    assert "word-level" in prompt


def test_removed_scene_review_cannot_be_quoted_or_executed(tmp_path,monkeypatch):
    response={'scenes':[],'transcript':[{'id':'t1','start_s':0,'end_s':4,'text':'One small step'}]}
    ad,req,calls=analyzer(tmp_path,monkeypatch,response)
    req.update(task='review_blueprint',review_input={'source_sha256':req['artifact_sha256'],
        'mode':'correct','duration_s':4})
    for action in (ad.price, ad.execute):
        with pytest.raises(ContractError, match='scene_review_removed'):
            action(req)
    assert not calls


@pytest.mark.parametrize("which", ["beats", "transcript", "reversed_word", "outside_word"])
def test_invalid_required_timing_is_rejected_and_response_preserved(tmp_path, monkeypatch, which):
    data = payload()
    if which in ("beats", "transcript"):
        data[which][0].update(start_s=3, end_s=3)
    elif which == "reversed_word":
        data["transcript"][0]["words"][2].update(start_s=3.8, end_s=3.1)
    else:
        data["transcript"][0]["words"][2]["end_s"] = 4.1
    ad, req, calls = analyzer(tmp_path, monkeypatch, data)
    with dispatch_context({"attempt_id": "att:invalid:1"}), pytest.raises(ProviderError) as exc:
        ad.submit(req)
    assert exc.value.code == "malformed_analysis"
    assert (which if which in ("beats", "transcript") else "transcript.words") in exc.value.detail
    saved = list(ad.root.glob("sync-*/provider-response.json"))
    assert len(saved) == 1
    evidence = json.loads(saved[0].read_text())
    assert evidence["attempt_id"] == "att:invalid:1"
    assert evidence["http_status"] == 200
    assert evidence["response"]["usageMetadata"]["totalTokenCount"] == 100
    assert saved[0].stat().st_mode & 0o777 == 0o600
    receipt = json.loads(saved[0].with_name("receipt.json").read_text())
    assert evidence["request_hash"] == receipt["request_hash"]
    assert receipt["status"] == "unknown" and "not_sent" not in receipt
    with dispatch_context({"attempt_id": "att:invalid:1"}):
        assert ad.submit(req)["status"] == "unknown"
    assert len(calls) == 1


def test_response_evidence_excludes_credentials(tmp_path, monkeypatch):
    data = payload()
    data["authorization"] = "Bearer secret-fixture-token"
    ad, req, _ = analyzer(tmp_path, monkeypatch, data)
    with dispatch_context({"attempt_id": "att:redaction:1"}):
        ad.submit(req)
    saved = next(ad.root.glob("sync-*/provider-response.json")).read_text()
    assert "secret-fixture-token" not in saved and "offline-token" not in saved


def test_valid_word_alignment_is_preserved(tmp_path, monkeypatch):
    data = payload()
    data['transcript'][0]['words'][1]['end_s'] = 3.05
    ad, req, _ = analyzer(tmp_path, monkeypatch, data)
    result = ad.execute(req)[0]
    assert [w['text'] for w in result['transcript'][0]['words']] == ['One', 'small', 'step']
    assert result['uncertainty'] == []


def test_empty_placeholder_removed_without_losing_actual_speech(tmp_path, monkeypatch):
    data = payload()
    data['transcript'][0]['words'] = []
    data['transcript'].insert(0, {'id': 'empty', 'start_s': 0, 'end_s': 0, 'text': '', 'words': []})
    ad, req, calls = analyzer(tmp_path, monkeypatch, data)
    result = ad.execute(req)[0]
    assert len(result['transcript']) == 1
    assert result['transcript'][0]['text'] == 'One small step'
    assert any('empty transcript placeholder' in note for note in result['uncertainty'])
    assert len(calls) == 1


def test_saved_completed_response_can_be_revalidated_without_transport(tmp_path, monkeypatch):
    import modules.factory.analysis.vertex as vertex
    data = payload()
    data['transcript'][0]['words'] = []
    data['transcript'].insert(0, {'id': 'empty', 'start_s': 0, 'end_s': 0, 'text': '', 'words': []})
    ad, req, calls = analyzer(tmp_path, monkeypatch, data)
    # Replay the old validator at the actual submit boundary to reproduce
    # the captured production shape and preserve an unknown receipt.
    with monkeypatch.context() as old:
        old.setattr(vertex, '_optional_word_timing', lambda value: value)
        with dispatch_context({'attempt_id': 'att:replay:1'}), pytest.raises(ProviderError):
            ad.submit(req)
    def no_transport(*args):
        raise AssertionError('Local response recovery must never submit')
    ad.transport = no_transport
    result = ad.revalidate_analysis_response(req, 'att:replay:1')
    assert len(result['analysis']['transcript']) == 1
    assert result['analysis']['transcript'][0]['text'] == 'One small step'
    assert result['evidence']['request_hash']
    assert len(calls) == 1
    assert json.loads(next(ad.root.glob('sync-*/receipt.json')).read_text())['status'] == 'unknown'
    with pytest.raises(ContractError):
        ad.revalidate_analysis_response({**req, 'artifact_sha256': 'different'}, 'att:replay:1')


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True])
def test_invalid_word_bounds_cannot_hide_behind_zero_word(tmp_path, monkeypatch, value):
    data = payload()
    data['transcript'][0]['words'][2]['end_s'] = value
    ad, req, _ = analyzer(tmp_path, monkeypatch, data)
    with pytest.raises(ProviderError, match='malformed_analysis'):
        ad.execute(req)


def failed_attempt(db, cause="malformed_analysis", provider="audiovisual_analysis"):
    ex = Executor(db)
    req = {"task": "analyze", "model": "m", "artifact_id": "art", "artifact_sha256": "sha"}
    aid = approve_operation(db, ex, req, "invalid-job", kind="analysis",
        provider=provider, model="m", unit="usd_micros", amount=250000)
    def call():
        raise ProviderError(cause, detail="malformed_analysis: entry 14: end 3.0 <= start 3.0")
    with pytest.raises(ProviderError):
        ex.submit(aid, call=call)
    event = db.conn.execute("SELECT seq FROM events WHERE stream=? AND type='ack_lost'", ("attempt:"+aid,)).fetchone()[0]
    rid = json.loads(db.conn.execute("SELECT body FROM attempts WHERE id=?", (aid,)).fetchone()[0])["reservation_id"]
    return aid, event, rid


def test_recovery_exposes_unknown_after_a_closed_predecessor(env):
    from modules.factory.autorun.recovery import AnalysisRecovery
    from modules.factory.autorun.service import AutoRun
    _, _, db, services, _ = env
    aid, event, _ = failed_attempt(db)
    # An older rejected attempt must not hide the current unknown outcome.
    db.conn.execute("""INSERT INTO attempts(id,job_id,attempt_seq,request_hash,status,body,created_at,updated_at)
        SELECT 'att:closed',job_id,0,request_hash,'failed',body,created_at,updated_at FROM attempts WHERE id=?""", (aid,))
    run = AutoRun(schema_version='autorun.v1', id='recovery-multi', status='paused',
                  stage='video_analysis', state={'analysis_jobs':['invalid-job']})
    result = AnalysisRecovery(services).describe(run)
    assert result['attempt_id'] == aid
    assert result['event_seq'] == event
    assert result['kind'] == 'response_invalid'


def test_operator_reconciliation_settles_estimate_without_refund_or_retry(env):
    client, csrf, db, services, _ = env
    aid, event, rid = failed_attempt(db)
    db.conn.execute("INSERT OR REPLACE INTO capacity_holds(capacity,job_id,holder,fencing,expires_at,retained_reason) VALUES('dispatch','invalid-job','fixture',0,'2000-01-01','unfinished_remote_op')")
    body = {"reviewer": "operator", "evidence": "Reviewed single synchronous response-validation path", "event_seq": event}
    path = f"/api/attempts/{aid}/reconcile-invalid-analysis"
    response = mut(client, csrf, "post", path, key="reconcile-invalid", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "failed"
    assert db.conn.execute("SELECT status FROM reservations WHERE id=?", (rid,)).fetchone()[0] == "settled"
    assert all(row[0] == 250000 and row[1] == "usage_estimate" for row in db.conn.execute(
        "SELECT settled_amount,kind FROM reservation_lines WHERE reservation_id=?", (rid,)))
    assert db.conn.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM capacity_holds WHERE job_id='invalid-job'").fetchone()[0] == 0
    count = db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert mut(client, csrf, "post", path, key="reconcile-invalid", json=body).json() == response.json()
    assert db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == count
    # The original unknown receipt is historical evidence, not a reason to
    # reopen an operator-resolved, settled failure during stale reconciliation.
    def should_not_poll(**kwargs):
        raise AssertionError('Resolved attempt must not be reopened')
    assert Executor(db, SimpleNamespace(reconcile=should_not_poll)).reconcile(aid)['status'] == 'failed'


@pytest.mark.parametrize("bad", ["transport", "provider", "event", "reviewer", "remote", "wrong_task"])
def test_reconciliation_refuses_unproven_or_unreviewed_outcomes(env, bad):
    client, csrf, db, _, _ = env
    aid, event, rid = failed_attempt(db, cause="response_lost" if bad == "transport" else "malformed_analysis",
        provider="analysis" if bad == "provider" else "audiovisual_analysis")
    if bad == 'remote':
        db.conn.execute('UPDATE attempts SET remote_id=? WHERE id=?', ('remote-operation', aid))
    elif bad == 'wrong_task':
        db.conn.execute("UPDATE intents SET body=json_set(body,'$.request.task','review_final') WHERE json_extract(body,'$.attempt_id')=?", (aid,))
    body = {"reviewer": "" if bad == "reviewer" else "operator", "evidence": "reviewed",
            "event_seq": event+1 if bad == "event" else event}
    response = mut(client, csrf, "post", f"/api/attempts/{aid}/reconcile-invalid-analysis", json=body)
    assert response.status_code == 400
    assert db.conn.execute("SELECT status FROM attempts WHERE id=?", (aid,)).fetchone()[0] == "unknown"
    assert db.conn.execute("SELECT status FROM reservations WHERE id=?", (rid,)).fetchone()[0] == "ambiguous"


def test_dashboard_recovery_does_not_suggest_free_retry():
    from modules.factory.providers.recovery import analysis_recovery
    message = analysis_recovery("malformed_analysis")
    assert "potentially billable" in message
    assert "settle" in message and "Resume" in message
    assert analysis_recovery("loader_failed") is None


@pytest.mark.parametrize('reason,sibling', [('unfinished_local_work', False), ('unfinished_remote_op', True)])
def test_resolution_preserves_unrelated_local_or_unfinished_sibling_capacity(env, reason, sibling):
    client, csrf, db, _, _ = env
    aid, event, _ = failed_attempt(db)
    db.conn.execute("INSERT INTO capacity_holds(capacity,job_id,holder,fencing,expires_at,retained_reason) VALUES('dispatch','invalid-job','fixture',0,'2000-01-01',?)", (reason,))
    if sibling:
        db.conn.execute("""INSERT INTO attempts(id,job_id,attempt_seq,request_hash,remote_id,status,body,created_at,updated_at)
            SELECT 'att:sibling',job_id,2,request_hash,NULL,'unknown',body,created_at,updated_at
            FROM attempts WHERE id=?""", (aid,))
    response = mut(client, csrf, 'post', f'/api/attempts/{aid}/reconcile-invalid-analysis',
        json={'reviewer': 'operator', 'evidence': 'Reviewed validation event', 'event_seq': event})
    assert response.status_code == 200, response.text
    assert db.conn.execute("SELECT COUNT(*) FROM capacity_holds WHERE job_id='invalid-job'").fetchone()[0] == 1


@pytest.mark.parametrize('bad', [None, 'evidence', 'reviewer', 'event', 'source', 'response'])
def test_autorun_adopts_revalidated_response_without_starting_a_paid_retry(env, monkeypatch, bad):
    from modules.factory.autorun.service import AutoRun
    client, csrf, db, services, _ = env
    aid, event, rid = failed_attempt(db)
    db.conn.execute("UPDATE jobs SET status='failed',blocked_reason='malformed_analysis' WHERE id='invalid-job'")
    recovered = {'analysis': {'beats': [{'id': 'b', 'start_s': 0, 'end_s': 4,
        'role': 'hook', 'confidence': 'uncertain'}], 'transcript': [], 'uncertainty': []},
        'evidence': {'attempt_id': aid, 'request_hash': 'h', 'response_sha256': 's', 'receipt_sha256': 'r'}}
    def revalidate(req, att):
        if bad == 'response':
            raise ContractError('analysis_response_mismatch', 'attempt_id')
        return recovered
    services.providers['audiovisual_analysis'] = SimpleNamespace(revalidate_analysis_response=revalidate)
    monkeypatch.setattr(services.seeds, 'get', lambda _: SimpleNamespace(
        source_asset_id='wrong' if bad == 'source' else 'art', analysis_asset_id=''))
    run = AutoRun(schema_version='autorun.v1', id='auto-recovery', status='paused',
        stage='video_analysis', seed_id='seed', params={'budget_ids': []},
        state={'analysis_jobs': ['invalid-job']}, pause={'code': 'analysis_failed'})
    services.autorun._put(run)
    body = {'reviewer': 'operator', 'event_seq': event, 'evidence': 'Reviewed saved response'}
    if bad in ('evidence', 'reviewer'):
        body[bad] = ''
    elif bad == 'event':
        body['event_seq'] = event + 1
    response = mut(client, csrf, 'post', '/api/autoruns/auto-recovery/recover-analysis-response', json=body)
    if bad:
        assert response.status_code == 400, response.text
        assert services.autorun.get('auto-recovery').to_dict() == run.to_dict()
        assert db.conn.execute('SELECT status FROM attempts WHERE id=?', (aid,)).fetchone()[0] == 'unknown'
        assert db.conn.execute('SELECT status FROM reservations WHERE id=?', (rid,)).fetchone()[0] == 'ambiguous'
        return
    assert response.status_code == 200, response.text
    current = services.autorun.get('auto-recovery')
    assert current.status == 'paused' and current.pause['code'] == 'analysis_recovered'
    assert current.state['analysis'] == recovered['analysis']
    assert 'analysis_jobs' not in current.state
    assert db.conn.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 1
    assert db.conn.execute('SELECT status FROM reservations WHERE id=?', (rid,)).fetchone()[0] == 'settled'
    # A restarted browser can use a fresh HTTP key without adopting or
    # settling the same saved result twice.
    count = db.conn.execute('SELECT COUNT(*) FROM events').fetchone()[0]
    again = mut(client, csrf, 'post', '/api/autoruns/auto-recovery/recover-analysis-response',
                key='recover-after-restart', json=body)
    assert again.status_code == 200
    assert services.autorun.get('auto-recovery').to_dict() == current.to_dict()
    assert db.conn.execute('SELECT COUNT(*) FROM events').fetchone()[0] == count
