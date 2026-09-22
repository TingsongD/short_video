import pytest
np = pytest.importorskip('numpy', reason='VALIDATION GAP: run isolated helper tests')


def test_repeated_shot_is_retained_without_character_identity_claim():
    from modules.factory.analysis.event_fusion import visual_recurrences, fuse_events
    frames = [{'index':i,'source_time':str(i/10),'change':1 if i in (10,20) else 0,'novelty':0}
              for i in range(30)]
    vectors = np.zeros((30,512),dtype=np.float32)
    vectors[:10,0]=1
    vectors[10:20,1]=1
    vectors[20:,0]=1
    repeated = visual_recurrences(frames,vectors)
    assert repeated == [{'frame_index':20,'earlier_frame_index':0,'similarity':1.0,
                         'claim':'visual_resemblance_only'}]
    result = fuse_events(frames, [], duration='3', recurrences=repeated)
    candidates = [c for c in result['candidates'] if c['kind']=='recurrence_candidate']
    assert candidates[0]['mandatory'] and candidates[0]['source_time']=='2'
    assert 20 in result['selected_frame_indices']
