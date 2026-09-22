import hashlib
import subprocess
from fractions import Fraction
import pytest
pytest.importorskip('av',reason='VALIDATION GAP: run isolated helper tests')


def test_dense_candidates_cannot_merge_into_an_unbounded_reencoded_window():
    from modules.factory.analysis.selected_media import _ranges
    frames=[{'source_time':str(Fraction(i,30))} for i in range(600)]
    clock={'frames':frames,'duration':'20'}
    candidates=[{'id':str(i),'context_start':str(max(0,Fraction(i,2)-Fraction(1,2))),
        'context_end':str(min(20,Fraction(i,2)+Fraction(1,2)))} for i in range(40)]
    windows=_ranges(clock,{'candidates':candidates})
    assert len(windows)>1
    assert all(Fraction(w['source_end'])-Fraction(w['source_start'])<=4 for w in windows)
    assert {i for w in windows for i in range(w['first_frame'],w['end_frame'])}==set(range(600))
    for c in candidates:
        assert any(Fraction(w['source_start'])<=Fraction(c['context_start'])
            and Fraction(w['source_end'])>=Fraction(c['context_end']) for w in windows)


def test_selected_media_has_exact_frame_identity_and_audio_window(tmp_path):
    import av
    from modules.factory.media.source_clock import source_clock,visual_batches
    from modules.factory.analysis.selected_media import materialize_selected
    from modules.factory.artifacts.registry import ArtifactStore
    from modules.factory.store import Database
    clip=tmp_path/'source.mkv'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=72x128:r=30:d=2',
                    '-itsoffset','0.25','-f','lavfi','-i','sine=frequency=440:duration=1.5:sample_rate=48000',
                    '-c:v','libx264','-c:a','pcm_s16le',str(clip)],check=True)
    clock=source_clock(clip)
    frames=[f for b in visual_batches(clip,clock) for f in b.get('frames',[])]
    clock.update(frames=frames,duration='2')
    fusion={'selected_frame_indices':[10,11], 'candidates':[{'id':'flash','mandatory':True,
             'context_start':'1/3','context_end':'2/3','frame_indices':[10,11]}]}
    db=Database(tmp_path/'db')
    try:
        artifacts=ArtifactStore(tmp_path/'artifacts',db)
        result=materialize_selected(clip,clock,fusion,artifacts,tmp_path/'work')
        assert result['version']=='selected_media.v1' and 'overview' not in result
        assert [i['frame_index'] for i in result['images']]==[10,11]
        assert result['images'][0]['pixel_sha256']==frames[10]['pixel_sha256']
        assert len(result['windows'])==1
        window=result['windows'][0]
        assert window['audio_present'] is True
        assert window['first_frame']==10 and window['end_frame']==20
        assert Fraction(window['source_start'])==Fraction(frames[10]['source_time'])
        path=artifacts.verified_path(window['artifact_id'])
        with av.open(str(path)) as media:
            decoded=list(media.decode(video=0))
        assert len(decoded)==10
        assert decoded[0].pts==0
        for image in result['images']:
            assert artifacts.verified_path(image['artifact_id']).is_file()
    finally:
        db.close()


def test_v2_selected_media_is_compact_clock_bound_and_keeps_frame_resolution(tmp_path):
    import av
    from PIL import Image
    from modules.factory.media.source_clock import source_clock,visual_batches
    from modules.factory.analysis.selected_media import materialize_selected
    from modules.factory.artifacts.registry import ArtifactStore
    from modules.factory.store import Database

    clip=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
        'testsrc2=s=360x640:r=30:d=2','-f','lavfi','-i',
        'sine=frequency=440:duration=2:sample_rate=48000',
        '-c:v','libx264','-c:a','aac','-shortest',str(clip)],check=True)
    clock=source_clock(clip)
    frames=[f for batch in visual_batches(clip,clock)
            for f in batch.get('frames',[])]
    clock.update(frames=frames,duration='2')
    fusion={'selected_frame_indices':[15,45], 'candidates':[
        {'id':'a','mandatory':True,'context_start':'1/3',
         'context_end':'2/3','frame_indices':[15]},
        {'id':'b','mandatory':True,'context_start':'4/3',
         'context_end':'5/3','frame_indices':[45]}]}
    from modules.factory.analysis.selected_media import COMPACT_MEDIA_POLICY
    policy=COMPACT_MEDIA_POLICY
    db=Database(tmp_path/'db')
    try:
        artifacts=ArtifactStore(tmp_path/'artifacts',db)
        result=materialize_selected(clip,clock,fusion,artifacts,tmp_path/'work',
                                    policy=policy)
        assert result['version']=='selected_media.v2'
        assert result['policy']==policy
        assert all(item['mime_type']=='image/jpeg'
                   and item['encoding']=='jpeg_q88_444.v1'
                   for item in result['images'])
        with Image.open(artifacts.verified_path(result['images'][0]['artifact_id'])) as image:
            assert image.format=='JPEG' and image.size==(360,640)
        overview=result['overview']
        assert overview['source_start']=='0' and overview['source_end']=='2'
        assert overview['source_sha256']==clock['source_sha256']
        assert overview['bytes']<=policy['overview_max_bytes']
        with av.open(str(artifacts.verified_path(overview['artifact_id']))) as media:
            decoded=list(media.decode(video=0))
            assert len(decoded)==len(frames) and bool(media.streams.audio)
    finally:
        db.close()


def test_selected_window_preserves_delayed_audio_event_on_source_clock(tmp_path):
    import numpy as np
    from modules.factory.media.source_clock import source_clock,visual_batches,extract_audio
    from modules.factory.analysis.selected_media import materialize_selected
    from modules.factory.artifacts.registry import ArtifactStore
    from modules.factory.store import Database
    clip=tmp_path/'pulse.mkv'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:s=72x128:r=30:d=1',
        '-itsoffset','0.25','-f','lavfi','-i',r'aevalsrc=if(between(t\,0.25\,0.26)\,0.5\,0):s=48000:d=0.75',
        '-c:v','libx264','-c:a','pcm_s16le',str(clip)],check=True)
    clock=source_clock(clip)
    clock.update(frames=[f for b in visual_batches(clip,clock) for f in b.get('frames',[])],duration='1')
    fusion={'selected_frame_indices':[15],'candidates':[{'id':'pulse','mandatory':True,
        'context_start':'1/3','context_end':'2/3','frame_indices':[15]}]}
    db=Database(tmp_path/'db')
    try:
        arts=ArtifactStore(tmp_path/'artifacts',db)
        window=materialize_selected(clip,clock,fusion,arts,tmp_path/'work')['windows'][0]
        path=arts.verified_path(window['artifact_id'])
        audio=extract_audio(path,source_clock(path),tmp_path/'window.f32')
        samples=np.fromfile(tmp_path/'window.f32',dtype='<f4')
        onset=int(np.flatnonzero(abs(samples)>.2)[0])
        source_time=Fraction(window['source_start'])+Fraction(audio['source_origin'])+Fraction(onset,48000)
        assert abs(source_time-Fraction(1,2))<Fraction(1,1000)
    finally:db.close()
