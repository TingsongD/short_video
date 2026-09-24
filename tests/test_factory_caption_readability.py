"""Check the exported pixels, including contrast against completely white footage."""
import io
import json
from pathlib import Path
import subprocess
import time

from PIL import Image
import pytest

from test_factory_composition import stack, _clip
from modules.factory.audio import pcm
from modules.factory.rendering import FastPathRenderer


@pytest.mark.parametrize('renderer,width', [('fast', 720), ('fast', 1080),
                                           ('hypit', 720), ('native', 720)])
def test_caption_pixels_are_readable_padded_and_inside_safe_area(stack, renderer, width):
    _, arts, compiler, root = stack
    height = width * 16 // 9
    art = _clip(arts, root, 1, 'white-background', 'white')
    caps = [dict(id='c0', text='Bright backgrounds\nstay readable.', start_frame=3, end_frame=27)]
    clock = dict(width=width, height=height, fps=30, total_frames=30, caption_preset='phrases.v1')
    segments = [dict(id='s0', kind='picture', artifact_id=art.id, sha256=art.sha256,
                     in_frame=0, out_frame=30, source_in_s=0, source_out_s=1)]
    if renderer == 'fast':
        output = FastPathRenderer().render(root/'render',
            [dict(src=str(arts.path_for(art.id)), frames=30)], caps, [], clock)
    else:
        options = {}
        if renderer == 'native':
            speech = arts.intake_bytes(pcm.write_wav(pcm.sine(1)), provenance='manual',
                                      source_key='speech', requested_kind='audio')
            options = dict(renderer_policy='hypit_primary.v1',
                premix=dict(id='premix', kind='audio', artifact_id=speech.id, sha256=speech.sha256,
                            in_frame=0, out_frame=30, source_in_s=0, source_out_s=1),
                native_editorial=dict(version='semantic_edits.v1', variant_key='A', passages=[dict(
                    id='p0', in_frame=0, out_frame=30, artifact_id=speech.id, sha256=speech.sha256,
                    speech_hash='a'*64, alignment_hash='b'*64,
                    text='Bright backgrounds stay readable.', phrases=[[0, 1, 2, 3]],
                    words=[dict(text=w, start_frame=3+i*6, end_frame=9+i*6)
                           for i,w in enumerate('Bright backgrounds stay readable.'.split())])]))
        compiled = compiler.compile('readable', 'fixture', 'A', 'plan', segments, caps,
                                    clock, renderer='hypit', now='2026-09-22T00:00:00Z', **options)
        assert compiled['diagnostics'] == []
        output = _render_hypit(Path(compiled['files']['render.svrun']), root/'caption.mp4')

    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,nb_frames,r_frame_rate', '-of', 'json', str(output)]))['streams'][0]
    assert (probe['width'], probe['height'], probe['nb_frames'], probe['r_frame_rate']) == (width, height, '30', '30/1')
    frame = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', '0.5', '-i', str(output),
                                    '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-'])
    (root/'caption.png').write_bytes(frame)
    image = Image.open(io.BytesIO(frame)).convert('L')
    box = image.point(lambda v: 255 if v < 100 else 0).getbbox()
    assert box is not None, 'White footage must still have a contrasting caption background'
    x0, y0, x1, y1 = box
    scale = width/720
    assert x0 >= .095*width and x1 <= .905*width
    assert .65*height <= y0 < y1 <= .79*height
    assert 105*scale <= y1-y0 <= 150*scale, 'Two lines must fit a compact background'
    inset = round(8*scale)
    glyphs = image.crop((x0+inset,y0+inset,x1-inset,y1-inset)).point(lambda v: 255 if v > 220 else 0)
    ink = glyphs.getbbox()
    assert ink is not None and ink[3]-ink[1] >= 70*scale
    assert ink[0] >= 2*scale and ink[2] <= glyphs.width-2*scale, 'Text must have horizontal breathing room'
    rows = [y for y in range(glyphs.height) if glyphs.crop((0,y,glyphs.width,y+1)).getbbox()]
    groups = 1 + sum(b-a > 1 for a,b in zip(rows,rows[1:]))
    assert groups == 2, 'No unexpected third line or clipped text'
    # The center of the inter-line gap is background only: over white it
    # should remain dark enough for white letter interiors to exceed 7:1.
    gaps = [(a,b) for a,b in zip(rows,rows[1:]) if b-a > 1]
    background = image.getpixel((width//2, y0+inset+sum(gaps[0])//2)) / 255
    luminance = background/12.92 if background <= .04045 else ((background+.055)/1.055)**2.4
    assert 1.05/(luminance+.05) >= 7


def _render_hypit(source, output):
    from modules.factory.composition.gate import HypitGate
    from modules.factory.rendering.hypit_build import HypitBuildRunner, LAUNCHER
    from modules.factory.studio.launcher import prepare_local
    prepare_local(source.parent)
    runner = HypitBuildRunner()
    try:
        assert (check := HypitGate().check(source))['ok'], check
        build = runner.submit(source)
        deadline = time.monotonic()+180
        state = {}
        while time.monotonic() < deadline:
            state = runner.observe(build['build_id'], build['workspace'])
            if state['status'] in ('succeeded', 'failed'):
                break
            time.sleep(.5)
        assert state.get('status') == 'succeeded', state
        return runner.retrieve(build['build_id'], 'final.video', output, build['workspace'])
    finally:
        cleanup = subprocess.run([str(LAUNCHER), 'runtime', 'down', '--workspace', str(source.parent), '--json'],
                                 capture_output=True, text=True, timeout=45)
        assert cleanup.returncode == 0, 'Caption QA runtime cleanup could not be verified'
