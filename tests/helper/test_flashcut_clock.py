import subprocess
from fractions import Fraction
import pytest
pytest.importorskip('av', reason='VALIDATION GAP: run isolated helper tests')


def test_decoded_positions_use_actual_pts_and_clean_eof(tmp_path):
    from modules.factory.media.source_clock import source_clock, visual_batches
    clip = tmp_path/'fixture.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=72x128:r=30000/1001:d=1',
                    '-an', '-c:v', 'libx264', '-y', str(clip)], check=True)
    clock = source_clock(clip)
    batches = list(visual_batches(clip, clock, batch_size=8))
    frames = [frame for batch in batches[:-1] for frame in batch['frames']]
    assert batches[-1]['clean_decode'] is True
    assert batches[-1]['decoded_frames'] == 30
    assert [f['index'] for f in frames] == list(range(30))
    assert Fraction(frames[1]['pts']) * Fraction(clock['video']['time_base']) == Fraction(1001, 30000)
    assert clock['audio'] is None


def test_multiple_unselected_audio_tracks_are_not_guessed(tmp_path):
    from modules.factory.media.source_clock import source_clock
    from modules.factory.domain.errors import ContractError
    clip = tmp_path/'ambiguous.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=72x128:d=0.2',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=0.2', '-map', '0:v', '-map', '1:a', '-map', '1:a',
                    '-disposition:a:0', '0', '-disposition:a:1', '0', '-c:v', 'libx264', '-c:a', 'pcm_s16le', '-y', str(clip)], check=True)
    with pytest.raises(ContractError, match='ambiguous_source_stream'):
        source_clock(clip)
    assert source_clock(clip, audio_index=2)['audio']['index'] == 2


def test_audio_resampling_keeps_verified_sample_mapping(tmp_path):
    from modules.factory.media.source_clock import source_clock, extract_audio
    clip = tmp_path/'sound.mkv'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=72x128:d=1',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1:sample_rate=44100',
                    '-c:v', 'libx264', '-c:a', 'pcm_s16le', '-y', str(clip)], check=True)
    result = extract_audio(clip, source_clock(clip), tmp_path/'audio.f32')
    assert result['samples'] == 48000 and result['source_origin'] == '0'
    assert (tmp_path/'audio.f32').stat().st_size == 48000*4


def test_vfr_keeps_decode_positions_and_native_spacing(tmp_path):
    from modules.factory.media.source_clock import source_clock, visual_batches
    clip = tmp_path/'vfr.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:s=72x128:r=30:d=0.2',
                    '-vf',r'setpts=if(lt(N\,2)\,N\,N+3)/(30*TB)', '-fps_mode','vfr',
                    '-an','-c:v','libx264',str(clip)], check=True)
    batches = list(visual_batches(clip, source_clock(clip)))
    frames = [f for b in batches[:-1] for f in b['frames']]
    assert len(frames) == 6
    assert [Fraction(f['source_time']) for f in frames[:3]] == [0, Fraction(1,30), Fraction(1,6)]


def test_audio_sample_budget_stops_before_excess_write(tmp_path):
    from modules.factory.media.source_clock import source_clock, extract_audio
    from modules.factory.domain.errors import ContractError
    clip = tmp_path/'bounded.mkv'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:s=72x128:d=1',
                    '-f','lavfi','-i','sine=frequency=440:duration=1:sample_rate=48000',
                    '-c:v','libx264','-c:a','pcm_s16le',str(clip)], check=True)
    with pytest.raises(ContractError, match='resource_limit_exhausted'):
        extract_audio(clip, source_clock(clip), tmp_path/'audio.f32', max_samples=12000)
    assert (tmp_path/'audio.f32').stat().st_size <= 12000*4


def test_audio_offset_is_not_zeroed(tmp_path):
    from modules.factory.media.source_clock import source_clock, extract_audio
    clip = tmp_path/'offset.mkv'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=red:s=72x128:d=2',
                    '-itsoffset','0.25','-f','lavfi','-i','sine=frequency=440:duration=1:sample_rate=48000',
                    '-c:v','libx264','-c:a','pcm_s16le',str(clip)], check=True)
    result = extract_audio(clip,source_clock(clip),tmp_path/'audio.f32')
    assert Fraction(result['source_origin']) == Fraction(1,4)


@pytest.mark.parametrize('gap_samples',[48,4800,-48])
def test_explicit_small_audio_gap_keeps_later_source_timestamps(tmp_path,monkeypatch,gap_samples):
    import av
    from contextlib import contextmanager
    from types import SimpleNamespace
    from modules.factory.media.source_clock import extract_audio
    from modules.factory.domain.errors import ContractError
    def frame(pts):
        result=av.AudioFrame(format='fltp',layout='mono',samples=960)
        result.sample_rate=48000;result.pts=pts;result.time_base=Fraction(1,48000)
        for plane in result.planes:plane.update(bytes(plane.buffer_size))
        return result
    frames=[frame(0),frame(960+gap_samples),frame(1920+gap_samples)]
    stream=SimpleNamespace(codec_context=SimpleNamespace(channels=1,layout=frames[0].layout))
    @contextmanager
    def opened(_):
        yield SimpleNamespace(streams=[stream],decode=lambda _:iter(frames))
    monkeypatch.setattr(av,'open',opened)
    if gap_samples!=48:
        with pytest.raises(ContractError,match='audio_discontinuity'):
            extract_audio('unused',{'audio':{'index':0},'origin':'0'},tmp_path/'audio.f32')
    else:
        result=extract_audio('unused',{'audio':{'index':0},'origin':'0'},tmp_path/'audio.f32')
        assert result['samples']==2928
        assert result['padding_ranges']==[{'sample':960,'samples':48,'native_time':'1/50'}]
        assert result['native_pts_mapping'][1]['sample']==1008
        assert result['native_pts_mapping'][1]['native_time']=='21/1000'
