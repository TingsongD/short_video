"""Real service/worker dialogue integration with scripted external transports."""
import copy
import json
from pathlib import Path

from test_factory_autorun import application, stack, launch, make_seed, drive, Hypit9, SCRIPT


class DialogueHypit(Hypit9):
    def transcribe(self, src, language, dest):
        result = super().transcribe(src, language, dest)
        doc = json.loads(Path(dest).read_text())
        doc['diarization']['speakers'] = ['SPEAKER_00', 'SPEAKER_01']
        doc['passages'][1]['speaker'] = 'SPEAKER_01'
        for word in doc['passages'][1]['words']: word['speaker'] = 'SPEAKER_01'
        Path(dest).write_text(json.dumps(doc))
        return result


def test_two_characters_same_words_use_distinct_voices_and_render_all_variants(application):
    script = copy.deepcopy(SCRIPT)
    script['variants']['A']['b1'] = script['variants']['A']['b0']
    s, c, act, w, root = stack(application, script_result=script)
    s.ref_analysis.hypit = DialogueHypit()
    run = launch(act, make_seed(act, root), generate_music=False,
        speaker_voices={'SPEAKER_00':'voice-fixture', 'SPEAKER_01':'voice-second'})
    drive(s, w)
    run = s.autorun.get(run['id'])
    assert run.status == 'succeeded', (run.stage, run.pause)
    requests = [op['request'] for op in json.loads((root/'tts.json').read_text())['ops'].values()]
    identical = [r for r in requests if r['text'] == 'watch this dog now']
    assert {r['voice_id'] for r in identical} == {'voice-fixture', 'voice-second'}
    for key in 'ABCD':
        for seg in s.experiments._variant(run.experiment_id, key).segments:
            expected = 'voice-second' if seg['id'] == 'b1' else 'voice-fixture'
            assert seg['voice_id'] == seg['speech']['voice_id'] == expected
            assert seg['speaker'] == seg['speech']['speaker']
            assert seg['captions']
    assert len(s.experiment_results(run.experiment_id)['variants']) == 4


def test_plain_transcription_blocks_before_any_paid_analysis_or_tts(application):
    class PlainHypit(Hypit9):
        def transcribe(self, src, language, dest):
            result = super().transcribe(src, language, dest)
            doc = json.loads(Path(dest).read_text()); doc.pop('diarization')
            Path(dest).write_text(json.dumps(doc)); return result
    s, c, act, w, root = stack(application)
    s.ref_analysis.hypit = PlainHypit()
    run = launch(act, make_seed(act, root))
    drive(s, w)
    run = s.autorun.get(run['id'])
    assert run.pause['code'] == 'speaker_review_required'
    assert not s.db.conn.execute('select 1 from attempts').fetchone()
    prior = s.ref_analysis.get(run.seed_id).transcript['sha256']
    s.ref_analysis.hypit = Hypit9()
    resumed = act('post', f'/api/autoruns/{run.id}/resume', {})
    assert resumed.status_code in (200, 202), resumed.text
    drive(s, w)
    recovered = s.autorun.get(run.id)
    assert recovered.status == 'succeeded', recovered.pause
    assert recovered.state['speaker_evidence']['transcript_sha256'] != prior


def test_two_speakers_inside_one_visual_scene_keep_separate_audio_and_captions(application):
    class TurnsHypit(Hypit9):
        def transcribe(self, src, language, dest):
            result=super().transcribe(src,language,dest)
            doc=json.loads(Path(dest).read_text())
            def passage(text,start,end,speaker):
                return {'text':text,'start_seconds':start,'end_seconds':end,'speaker':speaker,
                    'words':[{'text':text,'start_seconds':start,'end_seconds':end,
                              'speaker':speaker,'speaker_status':'assigned'}]}
            doc['passages'][1:2]=[passage('Hello.',3.2,4.0,'SPEAKER_00'),passage('Welcome.',4.8,5.6,'SPEAKER_01')]
            doc['diarization']['speakers']=['SPEAKER_00','SPEAKER_01']
            Path(dest).write_text(json.dumps(doc));return result
    script={'variants':{
        'A':{'b0':'watch this dog now','b1-speaker-0':'Hello.','b1-speaker-1':'Welcome.','b2':'good boy wins'},
        'B':{'b0':'look at this dog'},'C':{'b1-speaker-1':'Welcome back.'},'D':{'b2':'good boy wins again'}},
        'hypotheses':{'B':'opening','C':'reply','D':'ending'}}
    s,c,act,w,root=stack(application,script_result=script)
    s.ref_analysis.hypit=TurnsHypit()
    run=launch(act,make_seed(act,root),generate_music=False,
        speaker_voices={'SPEAKER_00':'voice-fixture','SPEAKER_01':'voice-second'})
    drive(s,w);run=s.autorun.get(run['id'])
    assert run.status=='succeeded',(run.stage,run.pause)
    for key in 'ABCD':
        segments={x['id']:x for x in s.experiments._variant(run.experiment_id,key).segments}
        first,second=segments['b1-speaker-0'],segments['b1-speaker-1']
        assert first['speech']['voice_id']=='voice-fixture'
        assert second['speech']['voice_id']=='voice-second'
        assert first['target']['end_frame']==second['target']['start_frame']
        assert first['captions'] and second['captions']
