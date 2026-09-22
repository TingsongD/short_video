"""Flash-cut rendering at the existing composition and capability boundaries."""
import json

import pytest

from test_factory_composition import stack, _clip
from modules.factory.audio import pcm
from modules.factory.domain.errors import ContractError


def test_flashcut_composition_binds_only_the_frozen_mix(stack):
    _, arts, compiler, root = stack
    picture = _clip(arts, root, 1, 'picture')
    original = arts.intake_bytes(pcm.write_wav(pcm.sine(1, amp=7000)),
                                provenance='manual', source_key='original', requested_kind='audio')
    mixed = arts.intake_bytes(pcm.write_wav(pcm.sine(1, amp=3000)),
                             provenance='manual', source_key='premix', requested_kind='audio')
    def segment(ident, kind, asset):
        return dict(id=ident, kind=kind, artifact_id=asset.id, sha256=asset.sha256,
                    in_frame=0, out_frame=30, source_in_s=0, source_out_s=1)
    result = compiler.compile('flash', 'flash-exp', 'A', 'plan',
        [segment('picture', 'picture', picture), segment('speech', 'audio', original)],
        [], dict(fps=30, width=180, height=320, total_frames=30), renderer='ffmpeg_fast',
        renderer_policy='hypit_primary.v1', premix=segment('mixed', 'audio', mixed),
        now='2026-09-21T00:00:00Z')
    assert result['diagnostics'] == []
    composition = result['composition']
    assert composition['renderer'] == 'hypit'
    manifest = json.loads((root / 'comps/flash/r1/manifest.json').read_text())
    audio = [b for b in manifest['bindings'] if b['role'] == 'audio']
    assert [b['artifact_id'] for b in audio] == [mixed.id]
    source = (root / 'comps/flash/r1/video.svml').read_text()
    assert 'src-speech' not in source and 'src-mixed' in source


def test_flashcut_refuses_to_compile_without_authoritative_mix(stack):
    _, arts, compiler, root = stack
    picture = _clip(arts, root, 1, 'picture')
    with pytest.raises(ContractError, match='premix_required'):
        compiler.compile('flash', 'flash-exp', 'A', 'plan',
            [dict(id='picture', kind='picture', artifact_id=picture.id, sha256=picture.sha256,
                  in_frame=0, out_frame=30, source_in_s=0, source_out_s=1)], [],
            dict(fps=30, width=180, height=320, total_frames=30), renderer_policy='hypit_primary.v1')


def test_flashcut_template_routes_plain_cuts_to_hypit_without_changing_legacy():
    from types import SimpleNamespace
    from modules.factory.templates.capabilities import capability_report
    slot = SimpleNamespace(id='clip', effects=[], transition_out='cut')
    assert capability_report([slot])['preferred'] == 'ffmpeg_fast'
    assert capability_report([slot], renderer_policy='hypit_primary.v1')['preferred'] == 'hypit'


@pytest.mark.parametrize('renderer', ['hypit', 'ffmpeg_fast'])
def test_local_render_uses_measured_premix_without_doubled_audio(stack, renderer):
    import math
    import subprocess
    import time
    from pathlib import Path
    from modules.factory.rendering import FastPathRenderer
    from modules.factory.rendering.hypit_build import HypitBuildRunner, LAUNCHER
    from modules.factory.studio.launcher import prepare_local
    _, arts, compiler, root = stack
    picture = _clip(arts, root, 1, 'source')
    mixed = arts.intake_bytes(pcm.write_wav(pcm.sine(1, amp=3000)),
                             provenance='manual', source_key='premix', requested_kind='audio')
    sound = dict(id='mixed', kind='audio', artifact_id=mixed.id, sha256=mixed.sha256,
                 in_frame=0, out_frame=30, source_in_s=0, source_out_s=1,
                 src=str(arts.path_for(mixed.id)))
    picture_binding = dict(id='picture', kind='picture', artifact_id=picture.id, sha256=picture.sha256,
                           in_frame=0, out_frame=30, source_in_s=0, source_out_s=1)
    clock = dict(fps=30, width=180, height=320, total_frames=30)
    if renderer == 'ffmpeg_fast':
        output = FastPathRenderer().render(root / 'fast',
            [dict(src=str(arts.path_for(picture.id)), frames=30)], [], [sound], clock)
    else:
        if not (LAUNCHER.parent.parent / 'vendor/hypit-runtime/node_modules/.bin/hypit').exists():
            pytest.fail('VALIDATION GAP: pinned Hypit runtime is required')
        compiled = compiler.compile('mix-render', 'fixture', 'A', 'plan', [picture_binding], [], clock,
            now='2026-09-21T00:00:00Z', renderer_policy='hypit_primary.v1', premix=sound)
        source = Path(compiled['files']['render.svrun'])
        prepare_local(source.parent)
        runner = HypitBuildRunner()
        try:
            build = runner.submit(source)
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                result = runner.observe(build['build_id'], build['workspace'])
                if result['status'] in ('succeeded', 'failed'):
                    break
                time.sleep(.5)
            assert result['status'] == 'succeeded', result
            output = runner.retrieve(build['build_id'], 'final.video', root/'hypit-mix.mp4', build['workspace'])
        finally:
            stopped = subprocess.run([str(LAUNCHER), 'runtime', 'down', '--workspace', str(source.parent), '--json'],
                                     capture_output=True, text=True, timeout=45)
            assert stopped.returncode == 0, 'Unable to verify fixture runtime cleanup'
    samples = pcm.decode(output, pcm.RATE, 1)
    rms = math.sqrt(sum(float(s) ** 2 for s in samples) / len(samples))
    assert 1900 < rms < 2350, f'Premix should retain ~2121 RMS, not duplicate audio: {rms}'
