"""Source speech detection must stay independent of the output language."""
import json
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.factory.analysis.deep import HypitTransport
from modules.factory.analysis import local_transcript
from modules.factory.domain.errors import ContractError
from modules.factory.testing.fixtures import _moving_mp4
from test_factory_analysis_gate import env, _seed, _complete
from test_factory_application import FakeHypit


class ChineseSpeech(FakeHypit):
    def __init__(self):
        super().__init__()
        self.languages = []

    def transcribe(self, src, language, dest):
        self.languages.append(language)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_text(json.dumps({
            'format': 'hypit.transcript@1', 'source': str(src),
            'language': 'zh', 'audio_seconds': 3.0,
            'passages': [{
                'text': '这只猫喜欢拥抱', 'start_seconds': 0., 'end_seconds': 1.,
                'words': [{'text': '这只猫喜欢拥抱', 'start_seconds': 0.,
                           'end_seconds': 1.}],
            }],
        }))
        return SimpleNamespace(returncode=0, stdout='', stderr='')


def test_unlabeled_source_detects_chinese_before_english_narration(env, monkeypatch):
    s = env['s']
    seed, _ = _seed(env)
    transport = ChineseSpeech()
    s.ref_analysis.hypit = transport
    s.ref_analysis.start(seed.id, 'qa')
    analysis = s.ref_analysis.run_machine_stages(seed.id)
    assert transport.languages == ['auto']
    assert analysis.status == 'evidence_ready'
    assert analysis.transcript['language'] == 'zh'
    assert analysis.transcript['settings']['language'] == 'auto'
    run = SimpleNamespace(seed_id=seed.id, state={'blueprint_id': 'bp'}, params={'language': 'en'})
    transcript = s.autorun._transcript(run)
    assert transcript[0]['text'] == '这只猫喜欢拥抱'
    assert run.state['source_language'] == 'zh'
    assert run.params['language'] == 'en'
    monkeypatch.setattr(s.analysis, 'get', lambda _: SimpleNamespace(
        clock=SimpleNamespace(num=30, den=1), beats=[],
        provenance={'source_clock': {'num': 30, 'den': 1}}))
    s.providers['audiovisual_analysis'] = SimpleNamespace(account='offline', model='offline')
    requests = []
    def capture(*args):
        requests.extend(args[4])
        return 'translation_queued'
    monkeypatch.setattr(s.autorun, '_run_effect', capture)
    assert s.autorun._stage_script(run) == 'translation_queued'
    assert requests[0]['task'] == 'translate'
    assert requests[0]['translation_input'] == {
        'source_language': 'zh', 'target_language': 'en',
        'passages': [{'index': 0, 'text': '这只猫喜欢拥抱'}]}
    # A restart reuses completed local evidence, including detected language.
    s.ref_analysis.run_machine_stages(seed.id)
    assert transport.languages == ['auto']


@pytest.mark.parametrize('metadata', [
    {'source_language': 'zh', 'language': 'en'},
    {'language': 'zh'},
    {'captions': '这只猫喜欢拥抱'},
])
def test_known_source_language_remains_explicit(env, metadata):
    s = env['s']
    seed, _ = _seed(env)
    with s.db.uow() as u:
        seed = s.seeds.get(seed.id)
        seed.metadata = metadata
        seed.revision += 1
        u.records.put(seed)
    s.ref_analysis.hypit = ChineseSpeech()
    s.ref_analysis.start(seed.id, 'qa')
    analysis = s.ref_analysis.run_machine_stages(seed.id)
    assert s.ref_analysis.hypit.languages == ['zh']
    assert analysis.status == 'evidence_ready'


def test_new_analysis_does_not_reuse_old_forced_english_transcript(env):
    s = env['s']
    seed, _ = _seed(env)
    # Reproduce the old service default, without editing its saved evidence.
    s.ref_analysis.language = 'en'
    completed = _complete(env, seed)
    historical = completed.to_dict()
    prior_file = Path(completed.transcript['file'])
    prior_bytes = prior_file.read_bytes()
    s.ref_analysis.language = 'auto'
    s.ref_analysis.hypit = ChineseSpeech()
    fresh = s.ref_analysis.start(seed.id, 'new run')
    assert fresh.revision == completed.revision + 1
    assert fresh.status == 'in_progress'
    assert s.ref_analysis.get(seed.id, completed.revision).to_dict() == historical
    fresh = s.ref_analysis.run_machine_stages(seed.id)
    assert fresh.transcript['language'] == 'zh'
    assert Path(fresh.transcript['file']) != prior_file
    assert prior_file.read_bytes() == prior_bytes


@pytest.mark.parametrize('language', [None, 'auto', 'und', 'unknown', 'en'])
def test_missing_or_inconsistent_detection_blocks_before_script(env, language):
    class BadDetection(ChineseSpeech):
        def transcribe(self, src, language, dest):
            result = super().transcribe(src, language, dest)
            document = json.loads(Path(dest).read_text())
            document['language'] = detected
            Path(dest).write_text(json.dumps(document))
            return result
    detected = language
    s = env['s']
    seed, _ = _seed(env)
    s.ref_analysis.hypit = BadDetection()
    s.ref_analysis.start(seed.id, 'qa')
    analysis = s.ref_analysis.run_machine_stages(seed.id)
    assert analysis.status == 'blocked'
    assert analysis.blocking[0]['code'] == 'transcript_suspect'
    assert not analysis.stages.get('transcript', {}).get('done')


def test_auto_transport_preserves_local_detection_text_and_missing_word_times(tmp_path, monkeypatch):
    source = tmp_path / 'source.mp4'
    _moving_mp4(source, 1, size='180x320', audio=True)
    destination = tmp_path / 'transcript.json'
    requests = []
    staged = []
    class LocalEndpoint:
        def open(self, request, timeout):
            requests.append(request)
            if isinstance(request, str):
                return io.BytesIO(json.dumps({'ok': True, 'protocol': 'hypit.whisperx-service@1'}).encode())
            payload = json.loads(request.data)
            assert request.full_url == 'http://127.0.0.1:8765/transcribe'
            assert payload['language'] == 'auto'
            audio = Path(payload['audio_path'])
            staged.append(audio)
            assert audio.is_file()
            return io.BytesIO(json.dumps({'language': 'zh', 'segments': [{
                'text': '这只猫喜欢拥抱', 'start': 0., 'end': 1.,
                'words': [{'text': '这只猫', 'start': 0., 'end': .4}, {'text': '喜欢拥抱'}],
            }]}).encode())
    monkeypatch.setattr(local_transcript, 'build_opener', lambda *args: LocalEndpoint())
    def no_cli(*args, **kwargs):
        pytest.fail('Automatic detection must not invoke the CLI with an unsupported language')
    result = HypitTransport('unused', runner=no_cli).transcribe(source, 'auto', destination)
    assert result.returncode == 0
    document = json.loads(destination.read_text())
    assert document['language'] == 'zh'
    assert document['audio_seconds'] == pytest.approx(1, abs=.05)
    assert document['passages'][0] == {'text': '这只猫喜欢拥抱',
        'start_seconds': 0., 'end_seconds': 1.,
        'words': [{'text': '这只猫', 'start_seconds': 0., 'end_seconds': .4}, {'text': '喜欢拥抱'}]}
    assert not staged[0].exists()
    prior = destination.read_bytes()
    assert HypitTransport('unused', runner=no_cli).transcribe(source, 'auto', destination).returncode == 1
    assert destination.read_bytes() == prior and len(requests) == 2


@pytest.mark.parametrize('url', [
    'https://provider.example', 'http://127.0.0.1@provider.example',
    'http://127.0.0.1:8765?redirect=1', 'http://127.0.0.1:8765/elsewhere',
])
def test_detection_cannot_route_to_remote_provider(tmp_path, monkeypatch, url):
    monkeypatch.setattr(local_transcript, 'build_opener', lambda *args: pytest.fail('No connection allowed'))
    with pytest.raises(ContractError, match='local_transcription_required'):
        local_transcript.transcribe_auto('unused', tmp_path / 'transcript.json', url)


@pytest.mark.parametrize('failure', ['unavailable', 'wrong_protocol', 'redirect'])
def test_local_failure_never_falls_back_to_forced_english(tmp_path, monkeypatch, failure):
    class Endpoint:
        def open(self, *args, **kwargs):
            if failure == 'unavailable':
                raise OSError('offline endpoint')
            return io.BytesIO(b'{"ok": true, "protocol": "wrong"}')
    def opener(*handlers):
        if failure == 'redirect':
            handlers[-1].redirect_request(None, None, 302, '', {}, 'https://provider.example')
        return Endpoint()
    monkeypatch.setattr(local_transcript, 'build_opener', opener)
    calls = []
    transport = HypitTransport('unused', runner=lambda *args, **kwargs: calls.append(args))
    destination = tmp_path / 'transcript.json'
    result = transport.transcribe('unused', 'auto', destination)
    assert result.returncode == 1
    assert not calls and not destination.exists()


def test_character_alignment_does_not_trigger_false_repair_or_wrong_scene(tmp_path):
    from modules.factory.autorun.source_timing import SourceTimingService
    from modules.factory.autorun import scripts
    from modules.factory.store import Database
    passage = {'text': '猫喜欢拥抱', 'start_s': 0., 'end_s': 3.,
        'words': [{'text': char, 'start_s': 1.1 + i * .3, 'end_s': 1.3 + i * .3}
                  for i, char in enumerate('猫喜欢拥抱')]}
    beats = [{'id': 'first', 'start_s': 0., 'end_s': 1.},
             {'id': 'spoken', 'start_s': 1., 'end_s': 3.}]
    db = Database(tmp_path / 'timing.db')
    def no_repair(*args):
        pytest.fail('Complete Chinese alignment must not be discarded for character spacing')
    result = SourceTimingService(db, no_repair).review('r', 'sha', [passage], beats, 3, 'zh')
    assert result['passages'][0]['quality'] == 'word_aligned'
    assert result['passages'][0]['attempts'] == 0
    assert scripts.adapt(beats, result['transcript'])['A'] == {
        'first': '', 'spoken': passage['text']}


def test_character_spacing_does_not_hide_missing_or_changed_speech():
    from modules.factory.autorun.source_timing import words_ok
    passage = {'text': '猫喜欢拥抱', 'start_s': 0., 'end_s': 3.}
    for chars in ('猫喜欢抱', '猫讨厌拥抱', '猫欢喜拥抱'):
        words = [{'text': char, 'start_s': i * .3, 'end_s': .2 + i * .3}
                 for i, char in enumerate(chars)]
        assert not words_ok(words, passage)
