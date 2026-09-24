from copy import deepcopy
from types import SimpleNamespace
import json
from modules.factory.analysis.flashcut_vertex import FlashcutAnalyzer,ROUTE_LIMITS,MODEL
from modules.factory.domain.records import content_hash


def test_editorial_v2_preserves_semantics_and_binds_full_input(tmp_path,monkeypatch):
    import modules.factory.analysis.flashcut_vertex as route
    value={'observations':[{'id':'o','kind':'cut','start_s':1,'end_s':1.033,
        'description':'A scene change.','confidence':'observed','evidence_ids':['w'],
        'original_time_basis':'source','cut_frame_bracket':{'reported_source_time':'1'}}],
        'variants':{'A':{'passages':[{'id':'p0','text':'A word','words':[{'text':'A','start_frame':0,'end_frame':4}],
            'artifact_id':'art:abc','sha256':'a'*64,'speech_hash':'b'*64,'alignment_hash':'c'*64,
            'in_frame':0,'out_frame':30,'segment_id':'b','phrases':[[0]]}]}},
        'clock':{'num':30,'den':1},'total_frames':30}
    saved=deepcopy(value);binding={'source_sha256':'a'*64};ref={'sha256':'d'*64}
    monkeypatch.setattr(route,'SourceEvidenceService',lambda *_:SimpleNamespace(blobs=SimpleNamespace(
        read=lambda _: {'binding':binding,'observations':value['observations']})))
    adapter=FlashcutAnalyzer.__new__(FlashcutAnalyzer);adapter.limits=deepcopy(ROUTE_LIMITS)
    adapter._evidence=lambda _:None;adapter.artifacts=SimpleNamespace(db=None,root=tmp_path/'artifacts')
    request={'model':MODEL,'prompt_version':'flashcut_editorial.v2','output_policy':'flashcut_output.v2',
        'limits':ROUTE_LIMITS,'binding':binding,'understanding':ref,'editorial_input':value,
        'editorial_binding':{'understanding':ref['sha256'],'input_sha256':content_hash(value)}}
    parts,usage=adapter._editorial_prepared(request)
    wire=json.loads(parts[0]['text'].split('Input:\n',1)[1])
    assert wire['observations'][0]['description']==value['observations'][0]['description']
    assert wire['observations'][0]['evidence_ids']==['w']
    assert wire['variants']['A']['passages'][0]['words']==value['variants']['A']['passages'][0]['words']
    assert 'alignment_hash' not in wire['variants']['A']['passages'][0]
    assert usage['output_tokens_bound']==32768
    assert value==saved
    request.update(prompt_version='flashcut_editorial.v1');request.pop('output_policy')
    old,usage=adapter._editorial_prepared(request)
    assert json.loads(old[0]['text'].split('Input:\n',1)[1])==saved
    assert usage['output_tokens_bound']==8192
