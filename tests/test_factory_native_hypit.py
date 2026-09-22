import json
from pathlib import Path
import subprocess
import time

import pytest
from test_factory_composition import stack, _clip
from modules.factory.audio import pcm
from modules.factory.domain.errors import ContractError


def native_fixture(stack, total_frames=30):
    _,arts,compiler,root=stack
    video=_clip(arts,root,total_frames/30,'source','red')
    flash=_clip(arts,root,1,'flash','blue')
    speech=arts.intake_bytes(pcm.write_wav(pcm.sine(total_frames/30,amp=7000)),provenance='manual',source_key='speech',requested_kind='audio')
    mix=arts.intake_bytes(pcm.write_wav(pcm.sine(total_frames/30,amp=3000)),provenance='manual',source_key='mix',requested_kind='audio')
    clips=[dict(id='clip',kind='picture',artifact_id=video.id,sha256=video.sha256,in_frame=0,out_frame=14,source_in_s=0,source_out_s=14/30),
           dict(id='micro',kind='picture',artifact_id=flash.id,sha256=flash.sha256,in_frame=14,out_frame=16,source_in_s=0,source_out_s=2/30,
                semantic_start='p0-word-1'),
           dict(id='tail',kind='picture',artifact_id=video.id,sha256=video.sha256,in_frame=16,out_frame=total_frames,source_in_s=0,source_out_s=(total_frames-16)/30)]
    premix=dict(id='premix',kind='audio',artifact_id=mix.id,sha256=mix.sha256,in_frame=0,out_frame=total_frames,source_in_s=0,source_out_s=total_frames/30)
    native={'version':'semantic_edits.v1','variant_key':'A','passages':[{
        'id':'p0','in_frame':0,'out_frame':total_frames,'artifact_id':speech.id,'sha256':speech.sha256,
        'speech_hash':'a'*64,'alignment_hash':'b'*64,'text':'Hello, world!',
        'words':[{'text':'Hello,','start_frame':1,'end_frame':10},{'text':'world!','start_frame':14,'end_frame':29}],
        'phrases':[[0,1]]}]}
    captions=[dict(id='c0',text='Hello, world!',start_frame=1,end_frame=29,placement='heading')]
    return clips,premix,native,captions


def test_native_fractional_second_premix_passes_real_hypit_check(stack):
    from modules.factory.composition.gate import HypitGate
    clips,premix,native,captions=native_fixture(stack,31)
    result=stack[2].compile('fractional-mix','fixture','A','plan',clips,captions,
        dict(fps=30,fps_num=30,fps_den=1,width=180,height=320,total_frames=31,caption_preset='phrases.v1'),
        renderer_policy='hypit_primary.v1',premix=premix,native_editorial=native,now='2026-09-22T00:00:00Z')
    assert result['diagnostics']==[]
    check=HypitGate().check(Path(result['files']['render.svrun']))
    assert check['ok'],check


def compile_native(stack, width=180, height=320, total_frames=30):
    clips,premix,native,captions=native_fixture(stack,total_frames)
    return stack[2].compile('native','fixture','A','plan',clips,captions,
        dict(fps=30,fps_num=30,fps_den=1,width=width,height=height,total_frames=total_frames,caption_preset='phrases.v1'),
        renderer_policy='hypit_primary.v1',premix=premix,native_editorial=native,now='2026-09-21T00:00:00Z')


def test_native_compilation_freezes_package_and_uses_frames_not_rounded_seconds(stack):
    result=compile_native(stack)
    assert result['diagnostics']==[]
    source=Path(result['files']['video.svml']).read_text()
    assert 'from="@factory/aligned-speech@1"' in source
    assert 'story.moment.p0-word-1' in source and 'story.selection.p0-phrase-0' in source
    assert '<time:Take source={take-p0.take}' in source and '<caption-fine:Track' in source
    assert 'end="30f"' in source and 'start="16f"' in source
    assert source.count('<audio:Item ')==1 and '<typo:Track' not in source
    assert result['composition']['clock']['author_package_hash']
    assert 'packages/aligned-speech/src/activation.js' in result['composition']['files']


def test_native_requires_valid_final_alignment_and_audio_identity(stack):
    clips,premix,native,captions=native_fixture(stack)
    native['passages'][0]['sha256']='f'*64
    with pytest.raises(ContractError,match='semantic_audio_mismatch'):
        stack[2].compile('native','fixture','A','plan',clips,captions,
            dict(fps=30,width=180,height=320,total_frames=30),renderer_policy='hypit_primary.v1',
            premix=premix,native_editorial=native)


def test_native_package_change_cannot_reuse_old_build_receipt(stack):
    from modules.factory.rendering.hypit_build import HypitBuildRunner
    from modules.factory.providers.state import DurableState
    result=compile_native(stack)
    source=Path(result['files']['render.svrun'])
    calls=[]
    def runner(argv):
        calls.append(argv[0])
        if argv[0]=='check':doc={'format':'hypit.cli-check@1','ok':True}
        elif argv[0]=='plan':doc={'format':'hypit.cli-plan@1','ok':True,'needs':[],'requestCount':0}
        else:doc={'format':'hypit.cli-build@1','build':{'id':'fixture-build'}}
        return subprocess.CompletedProcess(argv,0,json.dumps(doc),'')
    build=HypitBuildRunner(runner)
    first=build.submit(source)
    assert build.submit(source)==first
    module=source.parent/'packages/aligned-speech/src/activation.js'
    module.write_text(module.read_text()+'\n// changed fixture authoring\n')
    with pytest.raises(ContractError,match='build_revision_changed'):build.submit(source)
    assert calls==['check','plan','build']


def test_native_adapter_public_boundaries():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','--import','./scripts/hypit-node-bootstrap.mjs','--test',
        'tests/js/aligned-speech.test.mjs'],cwd=root,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('size',[(180,320),(720,1280)])
@pytest.mark.parametrize('total_frames',[30,31])
def test_native_hypit_real_render_without_speech_requests(stack,size,total_frames):
    from modules.factory.composition.gate import HypitGate
    from modules.factory.rendering.hypit_build import HypitBuildRunner, LAUNCHER
    from modules.factory.studio.launcher import prepare_local
    import math
    result=compile_native(stack,*size,total_frames)
    assert result['diagnostics']==[]
    source=Path(result['files']['render.svrun'])
    prepare_local(source.parent)
    runner=HypitBuildRunner()
    try:
        gate=HypitGate()
        assert (check:=gate.check(source))['ok'], check
        assert (plan:=gate.plan(source))['ok'], plan
        assert all('speech' not in n['capability'] and 'whisper' not in n['capability'] for n in plan['plan']['needs'])
        build=runner.submit(source)
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            state=runner.observe(build['build_id'],build['workspace'])
            if state['status'] in ('succeeded','failed'):break
            time.sleep(.5)
        assert state['status']=='succeeded', state
        output=runner.retrieve(build['build_id'],'final.video',stack[3]/'native.mp4',build['workspace'])
        samples=pcm.decode(output,pcm.RATE,1)
        rms=math.sqrt(sum(float(s)**2 for s in samples)/len(samples))
        assert 1900<rms<2350, rms
        probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-select_streams','v:0',
            '-show_entries','stream=nb_read_frames','-of','json',str(output)]))
        assert probe['streams'][0]['nb_read_frames']==str(total_frames)
        pixels=subprocess.check_output(['ffmpeg','-v','error','-i',str(output),'-vf','crop=2:2:0:0',
            '-f','rawvideo','-pix_fmt','rgb24','-'])
        blue=[i for i in range(total_frames) if pixels[i*12+2]>pixels[i*12]+100]
        assert blue==[14,15], blue
    finally:
        cleanup=subprocess.run([str(LAUNCHER),'runtime','down','--workspace',str(source.parent),'--json'],capture_output=True,text=True,timeout=45)
        assert cleanup.returncode==0, 'Fixture-owned Hypit cleanup could not be verified'
