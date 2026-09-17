"""Adversarial S4 media regression tests; real local processing, no services."""
import json
import subprocess
from pathlib import Path

import pytest

from modules.factory.audio import apply_fit, fit_plan, MixService, SpeechService, pcm
from modules.factory.artifacts.registry import ArtifactStore
from modules.factory.domain.clocks import FrameInterval
from modules.factory.domain.errors import ContractError
from modules.factory.planning.asset_graph import build_graph, expand_take
from modules.factory.quality import RegionGate, TechnicalQC, QualityService
from modules.factory.rendering import FastPathRenderer
from modules.factory.store import Database
from modules.factory.testing.fixtures import _color_mp4


def test_duration_and_handles_part_of_shared_identity():
    takes = [{"variant":v,"slot":"hook","duration_s":d,"handle_s":h,"request":{"prompt":"same"}}
             for v,d,h in [("A",4,0),("B",8,0),("C",4,1),("D",4,0)]]
    graph = build_graph("p", takes, "jimeng", "fast", [4,8])
    pics = [n for n in graph["nodes"].values() if n["kind"] == "picture"]
    assert len(pics) == 3
    for n in pics:
        assert sum(a["covers_s"] for a in n["allocations"]) >= max(t["duration_s"] + t.get("handle_s",0) for t in n["takes"])
    assert next(n for n in pics if "A" in n["consumers"])["consumers"] == ["A","D"]


def test_supported_remainder_can_trim():
    fit = expand_take(10, [4,8])
    assert fit["status"] == "ok"
    assert [a["duration_s"] for a in fit["allocations"]] == [8,4]
    assert fit["allocations"][-1]["over_s"] == 2


def test_speedup_divides_word_times():
    fit = fit_plan(11,10)
    assert apply_fit([{"w":"end","start_s":10,"end_s":11}],fit)[0]["end_s"] == pytest.approx(10)


def test_mix_resamples_and_never_extends_allocation(tmp_path):
    db = Database(tmp_path/'f.db'); arts = ArtifactStore(tmp_path/'arts',db)
    mix = MixService(db,arts); mix.freeze('mix','exp','bed',{},now='2026-09-17T00:00:00Z')
    art = arts.intake_bytes(pcm.write_wav(pcm.sine(1,rate=48000),48000),provenance='manual',source_key='raw',requested_kind='audio')
    result = mix.mix('mix',[{'artifact_id':art.id,'kind':'speech'}],1)
    assert result['exact_samples'] == pcm.RATE
    with pytest.raises(ContractError,match='track_exceeds_allocation'):
        mix.mix('mix',[{'samples':pcm.sine(2),'kind':'speech'}],1)


def test_mix_gain_not_clipped_before_headroom(tmp_path):
    db = Database(tmp_path/'f.db'); arts = ArtifactStore(tmp_path/'arts',db)
    mix = MixService(db,arts); mix.freeze('mix','exp','bed',{'music_gain_db':20},now='2026-09-17T00:00:00Z')
    out = mix.mix('mix',[{'samples':[4000,8000,12000,16000]*100,'kind':'music'}],400/pcm.RATE,artifact_name='headroom')
    _, samples = pcm.read_wav(arts.path_for(out['artifact_id']).read_bytes())
    assert samples[3] / samples[0] == pytest.approx(4,abs=.01)


def test_missing_region_evidence_blocks():
    gate = RegionGate()
    assert not gate.compare_intermediates({}, {}, [{'start_frame':0,'end_frame':30}])['ok']
    assert not gate.compare_audio_region([],[],{'start_s':0,'end_s':1})['ok']


def test_real_freeze_to_eof_is_found(tmp_path):
    path=tmp_path/'frozen.mp4'; _color_mp4(path,1,rate=30,size='360x640')
    out=TechnicalQC().inspect(path,{'frames':30,'fps':30,'width':360,'height':640,'has_audio':False})
    assert any(f['code']=='frozen_section' for f in out['findings'])


def test_wrong_frame_clock_blocks(tmp_path):
    path=tmp_path/'clock.mp4'; _color_mp4(path,1,rate=24,size='360x640')
    out=TechnicalQC().inspect(path,{'frames':24,'fps':30,'width':360,'height':640,'has_audio':False,'duration_s':2})
    assert {'wrong_fps','wrong_duration'} <= {f['code'] for f in out['findings']}


def test_changed_frame_away_from_midpoint_is_found(tmp_path):
    a=tmp_path/'a.mp4'; b=tmp_path/'b.mp4'
    _color_mp4(a,1,rate=30,size='360x640',color='blue')
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(a),'-vf',"drawbox=x=0:y=0:w=iw:h=ih:color=red:t=fill:enable='lt(n,3)'",'-c:v','libx264',str(b)],check=True)
    out=RegionGate().compare_finals(a,b,[{'start_frame':0,'end_frame':30}],30)
    assert not out['ok']


def test_nonzero_source_offset_and_clock(tmp_path):
    red=tmp_path/'red.mp4'; blue=tmp_path/'blue.mp4'
    _color_mp4(red,1,rate=24,size='360x640',color='red'); _color_mp4(blue,1,rate=24,size='360x640',color='blue')
    src=tmp_path/'two.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-i',str(red),'-i',str(blue),'-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]','-map','[v]',str(src)],check=True)
    final=FastPathRenderer().render(tmp_path/'render',[{'src':str(src),'frames':24,'source_in_s':1}],[],[],{'fps':24,'width':360,'height':640})
    out=RegionGate(ssim_threshold=.97).compare_finals(final,blue,[{'start_frame':0,'end_frame':24}],24)
    assert out['ok']


def test_missing_creative_review_never_accepts(tmp_path):
    f=tmp_path/'final.mp4'; f.write_bytes(b'fixture-bytes')
    import hashlib
    qc=QualityService(Database(tmp_path/'f.db'))
    qc.record_verdict('only-tech',hashlib.sha256(f.read_bytes()).hexdigest(),'technical','pass')
    with pytest.raises(ContractError,match='acceptance_blocked'):
        qc.accept(f,['only-tech'])


def test_real_speech_fit_and_raw_reuse_with_new_target(tmp_path):
    from modules.factory.execution import Executor
    from modules.factory.testing.fakes import FakeTTS, FakeAligner
    from modules.factory.testing.authority import approve_operation
    from modules.factory.audio import AlignmentService
    from modules.factory.domain.clocks import RationalRate
    db=Database(tmp_path/'f.db'); arts=ArtifactStore(tmp_path/'arts',db)
    tts=FakeTTS(tmp_path/'tts.json'); executor=Executor(db,provider=tts)
    svc=SpeechService(db,arts,tts=tts,executor=executor)
    voice={'voice_id':'fixture','model':'eleven_v3'}
    text='One two three four five six seven eight nine ten'  # 4.10s
    svc.plan_segment('s1','A',text,voice,FrameInterval(0,120),now='2026-09-17T00:00:00Z')
    req={'text':svc.get('s1')['text'],'voice_id':'fixture','model':'eleven_v3','language':'en','settings':{}}
    aid=approve_operation(db,executor,req,'job:speech')
    op=svc.synthesize('s1','job:speech',attempt_id=aid)['operation']['operation_id']
    svc.collect('s1',op);svc.collect('s1',op)
    raw=svc.get('s1'); al=AlignmentService(db,FakeAligner());al.align('s1',svc.get,now='2026-09-17T00:00:00Z')
    fitted=svc.fit('s1')
    assert fitted['duration_s']==4 and fitted['fit']['rate']>1
    assert fitted['audio_sha256']!=raw['audio_sha256']
    rate,samples=pcm.read_wav(arts.path_for(fitted['artifact_id']).read_bytes())
    assert rate==48000 and len(samples)==192000
    caps=al.captions('s1',svc.get,fitted['fit'],RationalRate(30,1),speech_hash=fitted['speech_hash'],now='2026-09-17T00:00:00Z')
    assert caps.cues[-1]['end_frame']<=120
    svc.approve('s1',fitted['speech_hash'],reviewer='fixture operator')
    svc.plan_segment('s2','B',text,voice,FrameInterval(0,150),now='2026-09-17T00:00:00Z')
    svc.reuse_from_cache('s2'); reused=svc.get('s2')
    assert reused['status']=='voiced' and reused['audio_sha256']==raw['audio_sha256'] and not reused['speech_hash']
    assert svc.fit('s2')['duration_s']==5
    assert len(tts.doc['ops'])==1


def test_frozen_duck_and_loudness_are_applied(tmp_path):
    db=Database(tmp_path/'f.db'); arts=ArtifactStore(tmp_path/'arts',db);mix=MixService(db,arts)
    cfg={'music_gain_db':0,'duck':{'enabled':True,'amount_db':12,'fps':30,'regions':[{'start_frame':30,'end_frame':60}]}}
    mix.freeze('duck','exp','bed',cfg,now='2026-09-17T00:00:00Z')
    result=mix.mix('duck',[{'samples':pcm.sine(2),'kind':'music'}],2,artifact_name='duck')
    rate,values=pcm.read_wav(arts.path_for(result['artifact_id']).read_bytes())
    assert pcm.measure(values[:rate])['rms_dbfs']-pcm.measure(values[rate:])['rms_dbfs']==pytest.approx(12,abs=.05)
    mix.freeze('loud','exp','bed',{'music_gain_db':0,'loudness_target':{'rms_dbfs':-20}},now='2026-09-17T00:00:00Z')
    assert mix.mix('loud',[{'samples':pcm.sine(1),'kind':'music'}],1)['measured']['rms_dbfs']==pytest.approx(-20,abs=.05)


def test_still_and_delayed_audio_fast_path(tmp_path):
    from modules.factory.testing.fixtures import _png
    image=tmp_path/'still.png'; _png(image,color='blue')
    audio=tmp_path/'speech.wav';audio.write_bytes(pcm.write_wav(pcm.sine(.5)))
    out=FastPathRenderer().render(tmp_path/'render',[{'src':str(image),'frames':48,'media_kind':'image'}],[],
                                  [{'src':str(audio),'offset_s':.5,'duration_s':.5}],{'fps':24,'width':360,'height':640})
    samples=pcm.decode(out,48000)
    assert pcm.measure(samples[:18000],48000)['peak_dbfs'] is None
    assert pcm.measure(samples[28000:42000],48000)['rms_dbfs']>-30
    assert 96000<=len(samples)<98048


def test_missing_detectors_are_blocking():
    class Result:
        returncode=1;stderr='';stdout=''
    qc=TechnicalQC(runner=lambda *a,**kw:Result())
    assert qc._black_freeze('x')[0]['code']=='detector_failed'
    assert qc._audio_levels('x')[0]['code']=='detector_failed'


def test_music_loop_cannot_stall(tmp_path):
    from modules.factory.audio import MusicService
    db=Database(tmp_path/'f.db'); arts=ArtifactStore(tmp_path/'arts',db)
    art=arts.intake_bytes(pcm.write_wav(pcm.sine(.1)),provenance='manual',source_key='short',requested_kind='audio')
    music=MusicService(db,arts);music.import_bed('short',art.id,license_ref='fixture',now='2026-09-17T00:00:00Z')
    with pytest.raises(ContractError,match='invalid_music_loop'):
        music.construct_bed('short',10,crossfade_s=.25)
