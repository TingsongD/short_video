"""Future-run safety at public application/service boundaries (offline)."""
import pytest

from modules.factory.domain.errors import ContractError
from test_factory_analysis_gate import env, _seed, _complete
from test_factory_application import FakeHypit


def test_analysis_editor_rejects_stale_and_wrong_seed_tokens(env):
    s = env['s']
    seed, _ = _seed(env)
    other, _ = _seed(env, url='https://youtu.be/lmnopqrstuv')
    s.ref_analysis.hypit = FakeHypit()
    s.ref_analysis.start(seed.id, 'qa')
    s.ref_analysis.start(other.id, 'qa')
    snapshot = s.analysis_for(seed.id)
    token = snapshot['edit_token']
    body = {'edit_token': token, 'reviewer': 'qa',
            'status': 'declared_nonverbal', 'note': 'local fixture has no speech'}
    with pytest.raises(ContractError, match='stale_revision'):
        s.declare_analysis(other.id, body)
    updated = s.declare_analysis(seed.id, body)
    assert updated['edit_token'] != token
    with pytest.raises(ContractError, match='stale_revision'):
        s.declare_analysis(seed.id, body)
    with pytest.raises(ContractError, match='analysis_edit_token_required'):
        s.declare_analysis(seed.id, {k: v for k, v in body.items() if k != 'edit_token'})


def test_completed_analysis_evidence_survives_later_transcript_import(env):
    from pathlib import Path
    s = env['s']
    seed, _ = _seed(env)
    completed = _complete(env, seed)
    prior = completed.to_dict()
    paths = {k: Path(v).read_bytes() for k, v in completed.documents['files'].items()}
    changed = s.ref_analysis.import_transcript(seed.id, {
        'provider': 'offline', 'provenance': 'corrected local transcript',
        'words': [{'word': 'cat', 'start_s': 0, 'end_s': .4},
                  {'word': 'ball', 'start_s': .5, 'end_s': 1}]}, 'qa')
    assert changed.transcript['file'] != completed.transcript['file']
    assert s.ref_analysis.get(seed.id, completed.revision).to_dict() == prior
    for key, old in paths.items():
        assert Path(completed.documents['files'][key]).read_bytes() == old
    assert s.ref_analysis.verified_transcript(changed).exists()


def test_future_run_copies_legacy_analysis_without_mutating_history(env):
    from pathlib import Path
    from test_factory_analysis_gate import _sections
    svc = env['s'].ref_analysis
    seed, _ = _seed(env)
    svc.hypit = FakeHypit()
    svc.start(seed.id, 'qa', evidence_policy='legacy')
    old = svc.run_machine_stages(seed.id)
    saved = old.to_dict()
    files = {p: Path(p).read_bytes() for p in old.documents['files'].values() if Path(p).is_file()}
    new = svc.start(seed.id, 'new run', evidence_policy='immutable.v2')
    assert new.revision == old.revision + 1
    assert new.capabilities['evidence_policy'] == 'immutable.v2'
    assert new.transcript['file'] != old.transcript['file']
    _sections(svc, seed.id)
    assert svc.get(seed.id, old.revision).to_dict() == saved
    assert all(Path(p).read_bytes() == data for p, data in files.items())


def test_worker_checkpoint_cannot_overwrite_newer_analysis_edit(env):
    svc = env['s'].ref_analysis
    seed, _ = _seed(env)
    svc.hypit = FakeHypit()
    svc.start(seed.id, 'qa')
    stale_worker = svc.get(seed.id)
    svc.declare(seed.id, 'declared_nonverbal', 'No speech in local fixture', 'qa')
    with pytest.raises(ContractError, match='stale'):
        svc._save(stale_worker, stage='evidence')
    assert svc.get(seed.id).transcript['status'] == 'declared_nonverbal'


def test_analysis_reruns_deduplicate_and_reject_late_editor_binding(env):
    from modules.factory.services.worker import ApplicationWorker
    s = env['s']
    seed, _ = _seed(env)
    s.ref_analysis.hypit = FakeHypit()
    s.ref_analysis.start(seed.id, 'qa')
    token = s.analysis_for(seed.id)['edit_token']
    first = s.rerun_analysis_stages(seed.id, {'edit_token': token})
    assert s.rerun_analysis_stages(seed.id, {'edit_token': token})['job_id'] == first['job_id']
    s.declare_analysis(seed.id, {'edit_token': token, 'reviewer':'qa',
        'status':'declared_nonverbal', 'note':'Nonverbal local fixture'})
    result = ApplicationWorker(s).tick()
    assert result['error'] == 'stale_revision'
    assert s.ref_analysis.get(seed.id).transcript['status'] == 'declared_nonverbal'


@pytest.mark.parametrize('intervening_edit', [False, True])
def test_queued_analysis_restart_accepts_only_its_own_checkpoints(env, intervening_edit):
    from modules.factory.services.worker import ApplicationWorker

    class InterruptedHypit(FakeHypit):
        def transcribe(self, src, language, dest):
            raise InterruptedError('Fixture worker stopped after acquisition')

    s = env['s']
    seed, _ = _seed(env)
    s.ref_analysis.hypit = InterruptedHypit()
    s.ref_analysis.start(seed.id, 'qa')
    token = s.analysis_for(seed.id)['edit_token']
    queued = s.rerun_analysis_stages(seed.id, {'edit_token': token})
    command = s.commands.get(queued['job_id'])['command']
    job = {'id': queued['job_id']}
    with pytest.raises(InterruptedError):
        ApplicationWorker(s).execute(command['kind'], command['input'], job)
    checkpoint = s.analysis_for(seed.id)
    assert checkpoint['stages']['acquire']['done']
    assert checkpoint['edit_token'] != token
    if intervening_edit:
        s.declare_analysis(seed.id, {'edit_token': checkpoint['edit_token'],
            'reviewer': 'qa', 'status': 'declared_nonverbal', 'note': 'Local correction'})
    s.ref_analysis.hypit = FakeHypit()
    if intervening_edit:
        with pytest.raises(ContractError, match='stale_revision'):
            ApplicationWorker(s).execute(command['kind'], command['input'], job)
        assert s.analysis_for(seed.id)['transcript']['status'] == 'declared_nonverbal'
    else:
        result = ApplicationWorker(s).execute(command['kind'], command['input'], job)
        assert result['analysis']['stages']['acquire'] == checkpoint['stages']['acquire']
        assert result['analysis']['stages']['documents']['done']


def test_analysis_edit_during_local_transcription_is_not_overwritten(env):
    from modules.factory.services.worker import ApplicationWorker
    s = env['s']
    seed, _ = _seed(env)

    class ConcurrentEditHypit(FakeHypit):
        def transcribe(self, src, language, dest):
            current = s.analysis_for(seed.id)
            s.declare_analysis(seed.id, {'edit_token': current['edit_token'],
                'reviewer': 'qa', 'status': 'declared_nonverbal', 'note': 'Concurrent correction'})
            return super().transcribe(src, language, dest)

    s.ref_analysis.hypit = ConcurrentEditHypit()
    s.ref_analysis.start(seed.id, 'qa')
    queued = s.rerun_analysis_stages(seed.id, {'edit_token': s.analysis_for(seed.id)['edit_token']})
    command = s.commands.get(queued['job_id'])['command']
    with pytest.raises(ContractError, match='stale_revision'):
        ApplicationWorker(s).execute(command['kind'], command['input'], {'id': queued['job_id']})
    assert s.analysis_for(seed.id)['transcript']['status'] == 'declared_nonverbal'


@pytest.mark.parametrize('passages', ['not-a-list', [None], [{'text':42,'start_seconds':0,'end_seconds':1}]])
def test_invalid_transcript_structure_is_not_repairable_word_timing(passages):
    from modules.factory.analysis.deep import transcript_problems
    assert transcript_problems({'passages':passages}, 3, 'en', require_words=False)


def test_future_word_defects_reach_repair_instead_of_breaking_evidence(env):
    import json
    class BadWords(FakeHypit):
        def transcribe(self, src, language, dest):
            result = super().transcribe(src, language, dest)
            doc = json.loads(dest.read_text())
            doc['passages'][0]['words'] = 42
            dest.write_text(json.dumps(doc))
            return result
        def tiles(self, src, dest_dir, every, **kwargs):
            assert kwargs.get('transcript') is None
            return super().tiles(src, dest_dir, every, **kwargs)
    s = env['s']
    seed, _ = _seed(env)
    s.ref_analysis.hypit = BadWords()
    s.ref_analysis.start(seed.id,'qa')
    a = s.ref_analysis.run_machine_stages(seed.id)
    assert a.status != 'blocked'
    assert a.transcript['timing_repair_needed'] and not a.transcript['word_timing_available']


@pytest.mark.parametrize('bad', [None, 'copy', 42, {'b1': None}, {'wrong': 'copy'}])
def test_script_response_rejects_malformed_variant_before_speech(bad):
    from modules.factory.analysis.scripts import validate_script_response
    response = {'variants': {key: {'b1': 'Complete sentence.'} for key in 'ABCD'}}
    response['variants']['B'] = bad
    with pytest.raises(ContractError, match='invalid_script_response'):
        validate_script_response(response, ['b1'], dict.fromkeys('BCD', 'b1'))


def test_visual_recheck_supersedes_without_erasing_history(env):
    q = env['s'].quality
    binding = {'artifact_sha256': 'a' * 64, 'artifact_id': 'final-a',
               'composition_id': 'comp-a', 'composition_revision': 1,
               'composition_hash': 'b' * 64, 'plan_hash': 'c' * 64, 'variant_key': 'A'}
    q.begin_visual(binding, 'scope-v2', 'first')
    failed = q.complete_visual(binding, 'scope-v2', 'first', 'fail', notes=['drift'])
    q.begin_visual(binding, 'scope-v2', 'second')
    assert q.visual_head(binding, 'scope-v2')['status'] == 'pending'
    passed = q.complete_visual(binding, 'scope-v2', 'second', 'pass')
    assert q.visual_head(binding, 'scope-v2')['review_id'] == passed['id']
    assert q.complete_visual(binding, 'scope-v2', 'second', 'pass')['id'] == passed['id']
    assert failed['id'] != passed['id']
    q.begin_visual(binding, 'scope-v2', 'third')
    q.complete_visual(binding, 'scope-v2', 'second', 'pass')
    assert q.visual_head(binding, 'scope-v2')['request_id'] == 'third'
    assert q.visual_head(binding, 'scope-v2')['status'] == 'pending'
    q.begin_visual(binding, 'scope-v2', 'fourth')
    with pytest.raises(ContractError, match='qc_request_superseded'):
        q.begin_visual(binding, 'scope-v2', 'third')
