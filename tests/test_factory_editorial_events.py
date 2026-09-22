from copy import deepcopy
import pytest
from modules.factory.domain.errors import ContractError


def inputs():
    passages=[{'id':'p0','in_frame':0,'out_frame':90,'alignment_hash':'a'*64,'words':[
        {'text':'Here','start_frame':0,'end_frame':9},
        {'text':'look','start_frame':54,'end_frame':63},
        {'text':'look','start_frame':66,'end_frame':75}]}]
    footage=[{'id':'clip-0','variant_key':'B','kind':'picture','artifact_id':'art-1','sha256':'b'*64,
        'in_frame':0,'out_frame':90,'source_in_s':0,'source_out_s':3,'available_frames':120}]
    specs=[{'id':'reveal','kind':'reveal','required':True,'source_time':'6/5',
        'anchor':{'kind':'speech','passage_id':'p0','word_index':1,'text':'look','edge':'start'},
        'duration_frames':2,'footage_id':'clip-0','source_in_frame':90}]
    return footage,passages,specs


def test_seed_reveal_moves_to_final_word_and_preserves_two_frames():
    from modules.factory.analysis.editorial_events import resolve_edits
    footage,passages,specs=inputs()
    result=resolve_edits(footage,passages,specs,{'num':30,'den':1},'B',90)
    assert [(p['in_frame'],p['out_frame']) for p in result['pictures']]==[(0,54),(54,56),(56,90)]
    assert result['pictures'][1]['semantic_start']=='p0-word-1'
    assert result['pictures'][1]['source_in_s']==3
    assert result['events'][0]['source_time']=='6/5' and result['events'][0]['start_frame']==54
    assert [w['text'] for w in passages[0]['words']]==['Here','look','look']


def test_rejects_removed_anchor_cross_variant_footage_overlaps_and_short_clips():
    from modules.factory.analysis.editorial_events import resolve_edits
    footage,passages,specs=inputs()
    for mutate in [lambda f,p,s:s[0]['anchor'].update(text='gone'),
                   lambda f,p,s:f[0].update(variant_key='C'),
                   lambda f,p,s:s.append({**s[0],'id':'collision'}),
                   lambda f,p,s:s[0].update(source_in_frame=119)]:
        f,p,s=deepcopy((footage,passages,specs));mutate(f,p,s)
        with pytest.raises(ContractError):resolve_edits(f,p,s,{'num':30,'den':1},'B',90)


def test_wordless_visual_anchor_is_explicit_and_never_guessed_from_speech():
    from modules.factory.analysis.editorial_events import resolve_edits
    footage,_,specs=inputs()
    specs[0]['anchor']={'kind':'visual','target_time':'1/3','evidence_id':'observed-reveal'}
    result=resolve_edits(footage,[],specs,{'num':30,'den':1},'B',90)
    assert result['events'][0]['start_frame']==10
    assert 'semantic_start' not in result['pictures'][1]


def test_single_frame_quantization_records_exact_signed_error():
    from modules.factory.analysis.editorial_events import resolve_edits
    footage,_,specs=inputs()
    specs[0]['anchor']={'kind':'music','target_time':'101/100','evidence_id':'music-onset'}
    result=resolve_edits(footage,[],specs,{'num':30,'den':1},'B',90)
    event=result['events'][0]
    assert event['start_frame']==30
    assert event['target_time_before_quantization']=='101/100'
    assert event['quantization_error_seconds']=='-1/100'


def test_editorial_revisions_are_immutable_and_depend_on_final_alignment(tmp_path):
    from modules.factory.analysis.editorial_events import EditorialService
    from modules.factory.store import Database
    db=Database(tmp_path/'db')
    try:
        service=EditorialService(db,tmp_path/'evidence')
        f,p,s=inputs()
        one=service.freeze('exp',3,'B',{'num':30,'den':1},90,f,p,s,{'source_evidence':'c'*64})
        assert service.freeze('exp',3,'B',{'num':30,'den':1},90,f,p,s,{'source_evidence':'c'*64})['id']==one['id']
        p[0]['words'][1].update(start_frame=57);p[0]['alignment_hash']='d'*64
        two=service.freeze('exp',4,'B',{'num':30,'den':1},90,f,p,s,{'source_evidence':'c'*64})
        assert two['id']!=one['id']
        assert service.load(one['id'])['events'][0]['start_frame']==54
        assert service.load(two['id'])['events'][0]['start_frame']==57
    finally:db.close()
