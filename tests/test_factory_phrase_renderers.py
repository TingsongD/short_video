"""Readable captions through real local rendering and the pinned Hypit parser."""
import json
import subprocess
import time
import pytest
from pathlib import Path

from test_factory_composition import stack, _clip
from modules.factory.composition import HypitGate
from modules.factory.rendering import FastPathRenderer


def test_phrase_captions_render_through_actual_local_hypit(stack):
    """An absent or unusable renderer is an explicit gap, never a fake pass."""
    from modules.factory.rendering.hypit_build import HypitBuildRunner, LAUNCHER
    from modules.factory.studio.launcher import prepare_local
    if not (LAUNCHER.parent.parent / 'vendor/hypit-runtime/node_modules/.bin/hypit').exists():
        pytest.skip('VALIDATION GAP: pinned local Hypit runtime is unavailable')
    _, arts, compiler, root = stack
    art = _clip(arts, root, 1, 'hypit-caption-source')
    clock = {'width':720,'height':1280,'fps':30,'total_frames':30,'caption_preset':'phrases.v1'}
    captions = [{'id':'c0','text':'Look at this\nhorse!','start_frame':0,'end_frame':30}]
    compiled = compiler.compile('hypit-real','local-qa','A','local-qa-plan',
        [{'id':'s0','kind':'picture','artifact_id':art.id,'sha256':art.sha256,
          'in_frame':0,'out_frame':30,'source_in_s':0,'source_out_s':1}], captions, clock,
        renderer='hypit', now='2026-09-21T00:00:00Z')
    source = Path(compiled['files']['render.svrun'])
    workspace = source.parent
    prepare_local(workspace)
    runner = HypitBuildRunner()
    try:
        submitted = runner.submit(source)
        deadline = time.monotonic() + 150
        result = {}
        while time.monotonic() < deadline:
            result = runner.observe(submitted['build_id'], submitted['workspace'])
            if result['status'] in ('succeeded','failed'):
                break
            time.sleep(.5)
        assert result.get('status') == 'succeeded', result
        output = runner.retrieve(submitted['build_id'], 'final.video', root/'hypit-phrases.mp4', submitted['workspace'])
        result = subprocess.run(['ffprobe','-v','error','-of','json','-show_streams',str(output)],capture_output=True,text=True,check=True)
        video = next(s for s in json.loads(result.stdout)['streams'] if s['codec_type']=='video')
        assert (video['width'],video['height'],int(video['nb_frames'])) == (720,1280,30)
    finally:
        stopped = subprocess.run([str(LAUNCHER),'runtime','down','--workspace',str(workspace),'--json'],capture_output=True,text=True,timeout=45)
        assert stopped.returncode == 0, 'Local QA runtime cleanup could not be verified'


def test_phrase_layout_compiles_for_both_renderers_and_passes_hypit_check(stack):
    db, arts, compiler, root = stack
    art = _clip(arts, root, 1, 'caption-source')
    segments = [{'id':'s0','kind':'picture','artifact_id':art.id,'sha256':art.sha256,
                 'in_frame':0,'out_frame':30,'source_in_s':0,'source_out_s':1}]
    caps = [{'id':'c0','text':'Look at this\nhorse!','start_frame':0,'end_frame':30}]
    clock = {'width':720,'height':1280,'fps':30,'total_frames':30,'caption_preset':'phrases.v1'}
    compiled = compiler.compile('phrase-comp','fixture','A','fixture-plan',segments,caps,clock,renderer='hypit',now='2026-09-20T00:00:00Z')
    assert not compiled['diagnostics']
    svs = Path(compiled['files']['style.svs']).read_text()
    assert 'size: 48;' in svs and 'align: center;' in svs
    check = HypitGate().check(compiled['files']['video.svml'])
    assert check['ok'], check
    output = FastPathRenderer().render(root/'phrase-fast',
        [{'src':str(arts.path_for(art.id)), 'frames':30}],caps,[],clock)
    assert output.is_file()
    result = subprocess.run(['ffprobe','-v','error','-of','json','-show_streams',str(output)],capture_output=True,text=True,check=True)
    video = next(s for s in json.loads(result.stdout)['streams'] if s['codec_type']=='video')
    assert (video['width'],video['height'],int(video['nb_frames'])) == (720,1280,30)
