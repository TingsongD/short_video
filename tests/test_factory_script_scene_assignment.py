"""Script ownership uses aligned word evidence rather than leading silence."""
from modules.factory.autorun import scripts
from modules.factory.autorun.service import AutoRun
from test_factory_api import env
from types import SimpleNamespace
import json


def test_cross_cut_sentence_belongs_where_its_words_are_spoken():
    beats = [{'id':'calf','start_s':0,'end_s':8},
             {'id':'deer','start_s':8,'end_s':12.8}]
    transcript = [{'text':'Excuse me, sir.', 'start_s':7.714, 'end_s':10.376,
        'words':[{'text':'Excuse','start_seconds':7.714,'end_seconds':8.855},
                 {'text':'me,','start_seconds':8.875,'end_seconds':9.035},
                 {'text':'sir.','start_seconds':10.096,'end_seconds':10.376}]}]
    result = scripts.adapt(beats, transcript)
    assert result['A'] == {'calf':'', 'deer':'Excuse me, sir.'}


def test_long_alignment_word_cannot_dominate_whole_sentence_ownership():
    beats = [{'id':'truck','start_s':44,'end_s':49},
             {'id':'goats','start_s':49,'end_s':55.8},
             {'id':'airpod','start_s':55.8,'end_s':62.369}]
    transcript = [{'text':'Are you really serious?', 'start_s':48.875,'end_s':58.016,
        'words':[{'text':'Are','start_s':48.875,'end_s':49.015},
                 {'text':'you','start_s':49.035,'end_s':56.656},
                 {'text':'really','start_s':56.716,'end_s':57.636},
                 {'text':'serious?','start_s':57.656,'end_s':58.016}]}]
    result = scripts.adapt(beats, transcript)
    assert result['A'] == {'truck':'','goats':'','airpod':'Are you really serious?'}
    assert result['timing_warnings'], 'Do not label anomalous alignment as repaired timing'


def test_partial_word_evidence_does_not_drop_or_move_source_text():
    beats = [{'id':'a','start_s':0,'end_s':4}, {'id':'b','start_s':4,'end_s':8}]
    result = scripts.adapt(beats, [{'text':'Keep this entire line.', 'start_s':3,'end_s':6,
        'words':[{'text':'line.','start_s':5,'end_s':6}]}])
    assert result['A'] == {'a':'Keep this entire line.','b':''}


def test_autorun_preserves_aligned_words_into_script_assignment(env, monkeypatch, tmp_path):
    _, _, _, s, _ = env
    passage = {'text':'Excuse me, sir.', 'start_seconds':7.714, 'end_seconds':10.376,
        'words':[{'text':'Excuse','start_seconds':7.714,'end_seconds':8.855},
                 {'text':'me,','start_seconds':8.875,'end_seconds':9.035},
                 {'text':'sir.','start_seconds':10.096,'end_seconds':10.376}]}
    path = tmp_path/'aligned.json'
    path.write_text(json.dumps({'passages':[passage], 'language':'en'}))
    analysis = SimpleNamespace(source_sha256='bound-source', documents={}, capabilities={},
        transcript={'status':'aligned', 'source_sha256':'bound-source', 'language':'en'})
    monkeypatch.setattr(s.ref_analysis, 'get', lambda _: analysis)
    monkeypatch.setattr(s.ref_analysis, '_doc_paths', lambda _: {'transcript_json':path})
    result = s.autorun._transcript(AutoRun(id='word-copy', seed_id='seed'))
    assert result[0]['words'] == passage['words']
    copy = scripts.adapt([{'id':'calf','start_s':0,'end_s':8},
                         {'id':'deer','start_s':8,'end_s':12.8}], result)
    assert copy['A']['deer'] == passage['text'] and copy['A']['calf'] == ''
