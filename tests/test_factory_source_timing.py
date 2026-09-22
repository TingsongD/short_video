import copy
import pytest
from modules.factory.store import Database
from modules.factory.domain.errors import ContractError


def test_timing_repairs_are_bounded_across_restarts_and_fallback_is_honest(tmp_path):
    from modules.factory.autorun.source_timing import SourceTimingService
    db = Database(tmp_path/'timing.db')
    transcript = [{'text':'Keep this.', 'start_s':0., 'end_s':4.,
                   'words':[{'text':'Keep', 'start_s':0., 'end_s':3.5}]}]
    original = copy.deepcopy(transcript)
    calls = []
    def repair(*args): calls.append(args); return []
    service = SourceTimingService(db, repair)
    beats = [{'id':'b1','start_s':0.,'end_s':5.}]
    result = service.review('run', 'sha', transcript, beats, 5, 'en')
    assert result['transcript'][0]['words'] == []
    assert result['passages'][0]['quality'] == 'passage_only'
    assert result['passages'][0]['attempts'] == 2
    assert transcript == original
    db.close(); db = Database(tmp_path/'timing.db')
    result = SourceTimingService(db, repair).review('run', 'sha', transcript, beats, 5, 'en')
    assert len(calls) == 2
    with pytest.raises(ContractError, match='source_timing_unreliable'):
        SourceTimingService(db, repair).review('run', 'sha', transcript,
            [{'id':'a','start_s':0.,'end_s':2.},{'id':'b','start_s':2.,'end_s':5.}],5,'en')
    assert len(calls) == 2


def test_valid_repair_preserves_text_and_good_speech_without_extra_work(tmp_path):
    from modules.factory.autorun.source_timing import SourceTimingService
    db = Database(tmp_path/'timing.db'); calls = []
    def repair(p, *args):
        calls.append(p['text'])
        return [{'text':'Keep', 'start_s':0.2, 'end_s':0.6}, {'text':'this.', 'start_s':0.7, 'end_s':1.1}]
    transcript = [{'text':'Keep this.', 'start_s':0, 'end_s':2, 'words':[]},
                  {'text':'Done.', 'start_s':2, 'end_s':3, 'words':[{'text':'Done.', 'start_s':2.1,'end_s':2.8}]}]
    result = SourceTimingService(db, repair).review('r','sha',transcript,[{'id':'b','start_s':0,'end_s':3}],3,'en')
    assert calls == ['Keep this.']
    assert [p['quality'] for p in result['passages']] == ['repaired','word_aligned']
    assert result['transcript'][1] == transcript[1]


@pytest.mark.parametrize('words', [
    [{'text':'Changed.', 'start_s':0,'end_s':1}],
    [{'text':'Keep','start_s':0.8,'end_s':1}, {'text':'this.','start_s':0.2,'end_s':0.7}],
    [{'text':'Keep','start_s':-1,'end_s':0.5}, {'text':'this.','start_s':0.6,'end_s':1}],
])
def test_invalid_local_repair_does_not_certify_word_timing(tmp_path, words):
    from modules.factory.autorun.source_timing import SourceTimingService
    db = Database(tmp_path/'timing.db')
    result = SourceTimingService(db, lambda *args: words).review('r','sha',
        [{'text':'Keep this.','start_s':0,'end_s':2,'words':[]}],
        [{'id':'b','start_s':0,'end_s':2}],2,'en')
    assert result['passages'][0]['quality'] == 'passage_only'
    assert result['passages'][0]['attempts'] == 2


def test_interrupted_local_attempt_is_consumed_and_other_source_has_separate_evidence(tmp_path):
    from modules.factory.autorun.source_timing import SourceTimingService
    db = Database(tmp_path/'timing.db')
    transcript = [{'text':'Keep this.', 'start_s':0,'end_s':2,'words':[]}]
    beats = [{'id':'b','start_s':0,'end_s':2}]
    def interrupted(*args): raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        SourceTimingService(db, interrupted).review('r','source1',transcript,beats,2,'en')
    db.close(); db = Database(tmp_path/'timing.db')
    attempts = []
    def fail(p, attempt, *args): attempts.append(attempt); return []
    original = SourceTimingService(db,fail).review('r','source1',transcript,beats,2,'en')
    assert attempts == [2]
    replacement = SourceTimingService(db,fail).review('r','source2',transcript,beats,2,'en')
    assert replacement['binding'] != original['binding']
    assert attempts == [2,1,2]
    assert SourceTimingService(db,fail).receipt('r',original['binding']) == original


@pytest.mark.parametrize('start,end', [(0,5), (2,1), (float('nan'),2), ('invalid',2)])
def test_invalid_passage_bounds_pause_before_alignment(tmp_path,start,end):
    from modules.factory.autorun.source_timing import SourceTimingService
    db = Database(tmp_path/'timing.db')
    calls = []
    with pytest.raises(ContractError,match='source_timing_unreliable'):
        SourceTimingService(db,lambda *args:calls.append(args)).review('r','sha',
            [{'text':'Keep this.','start_s':start,'end_s':end,'words':[]}],
            [{'id':'b','start_s':0,'end_s':2}],2,'en')
    assert not calls
