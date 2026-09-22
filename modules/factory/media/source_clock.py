"""Selected native streams and actual decoded presentation timestamps.

No rounded seeks or nominal-FPS reconstruction. Used only in the isolated
helper, leaving the legacy probe/thumbnail interface unchanged.
"""
from fractions import Fraction
import hashlib
from pathlib import Path

from ..domain.errors import ContractError


def _disposition(stream):
    return int(getattr(stream.disposition, 'value', stream.disposition))


def _select(streams, index, required):
    if index is not None:
        matches = [s for s in streams if s.index == index]
    elif len(streams) <= 1:
        matches = list(streams)
    else:
        matches = [s for s in streams if _disposition(s) & 1]
    if not matches and not streams and not required and index is None:
        return None
    if len(matches) != 1:
        raise ContractError('ambiguous_source_stream', 'stream', 'Save an explicit stream selection')
    return matches[0]


def source_clock(path, *, video_index=None, audio_index=None):
    import av
    with av.open(str(path)) as container:
        video = _select([s for s in container.streams.video if not _disposition(s) & 1024], video_index, True)
        audio = _select(list(container.streams.audio), audio_index, False)
        def describe(stream):
            if stream is None:
                return None
            if stream.time_base is None or stream.time_base <= 0:
                raise ContractError('clock_mapping_unavailable', 'time_base')
            return {'index': stream.index, 'time_base': str(stream.time_base),
                    'start_pts': stream.start_time, 'duration_pts': stream.duration,
                    'disposition': _disposition(stream), 'language': stream.metadata.get('language'),
                    'sample_rate': stream.codec_context.sample_rate if stream.type == 'audio' else None,
                    'channels': stream.codec_context.channels if stream.type == 'audio' else None}
        video_info, audio_info = describe(video), describe(audio)
    # Determine actual first decoded sample/frame, including decoder skip data.
    for stream in (video_info, audio_info):
        if stream is None:
            continue
        with av.open(str(path)) as container:
            selected = container.streams[stream['index']]
            first = next(container.decode(selected), None)
            if first is None or first.pts is None or first.time_base is None:
                raise ContractError('clock_mapping_unavailable', 'first_pts')
            stream['first_pts'] = first.pts
            stream['decoded_time_base'] = str(first.time_base)
    origin = Fraction(video_info['first_pts']) * Fraction(video_info['decoded_time_base'])
    with Path(path).open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    return {'version': 'source_clock.v1', 'source_sha256': digest,
            'origin': str(origin), 'video': video_info, 'audio': audio_info,
            'decoder': {'pyav': av.__version__, 'libraries': {k: list(v) for k, v in av.library_versions.items()}}}


def visual_batches(path, clock, *, batch_size=8):
    """One complete decode stream feeds visual-change and PE adapters.

    Resized full-frame RGB images are bounded transient inputs, not substitutes
    for the original-resolution frames later selected by exact frame identity.
    The final clean_decode sentinel is emitted only after decoder exhaustion.
    """
    import av
    import numpy as np
    from PIL import Image
    if type(batch_size) is not int or not 1 <= batch_size <= 16:
        raise ContractError('invalid_decode_batch', 'batch_size')
    previous_pts, previous_image, count, group, images = None, None, 0, [], []
    with av.open(str(path)) as container:
        stream = container.streams[clock['video']['index']]
        for frame in container.decode(stream):
            if getattr(frame, 'is_corrupt', False):
                raise ContractError('decode_failed', 'corrupt_frame', str(count))
            if frame.pts is None or frame.time_base is None:
                raise ContractError('clock_mapping_unavailable', 'frame', str(count))
            position = Fraction(frame.pts) * frame.time_base
            if previous_pts is not None and position < previous_pts:
                raise ContractError('invalid_frame_order', 'pts', str(count))
            if frame.width * frame.height * 3 > 256 * 1024**2:
                raise ContractError('resource_limit_exhausted', 'decoded_frame')
            image = frame.to_image().convert('RGB')
            small = np.asarray(image.resize((64, 64), Image.Resampling.BILINEAR), dtype=np.float32)
            change = 0 if previous_image is None else float(np.mean(np.abs(small-previous_image))/255)
            group.append({'index': count, 'pts': frame.pts, 'time_base': str(frame.time_base),
                          'duration_pts': frame.duration, 'width': image.width, 'height': image.height,
                          'source_time': str(position-Fraction(clock['origin'])),
                          'pixel_sha256': hashlib.sha256(image.tobytes()).hexdigest(), 'change': change})
            images.append(image.resize((384, 384), Image.Resampling.BILINEAR))
            previous_pts, previous_image, count = position, small, count+1
            if len(group) == batch_size:
                yield {'frames': group, 'images': images}
                group, images = [], []
        if group:
            yield {'frames': group, 'images': images}
    if count == 0:
        raise ContractError('decode_failed', 'video', 'No decoded frames')
    yield {'clean_decode': True, 'decoded_frames': count}


def extract_audio(path, clock, destination, *, max_samples=48000*600):
    """FFmpeg's PyAV decoder/resampler preserves selected-stream sample PTS.

    Writes bounded blocks of interleaved float PCM. Preserve an explicit gap
    of at most 1 ms as recorded zero padding, never collapse source time. Larger
    gaps, overlaps and more than 5 ms cumulative padding remain failures.
    """
    import av
    import numpy as np
    audio = clock['audio']
    if audio is None:
        return {'status': 'not_applicable_no_stream', 'samples': 0}
    total, first_time, expected_source, expected_output = 0, None, None, None
    source_origin, source_samples, mappings = None, 0, []
    padding, padded, native_rate = [], 0, None
    with av.open(str(path)) as container, Path(destination).open('xb') as output:
        stream = container.streams[audio['index']]
        channels = stream.codec_context.channels
        if not 1 <= channels <= 8:
            raise ContractError('audio_format_unavailable', 'channels')
        resampler = av.AudioResampler(format='fltp', layout=stream.codec_context.layout.name, rate=48000)
        def store(frame):
            nonlocal total, first_time, expected_output
            if frame.pts is None:
                raise ContractError('clock_mapping_unavailable', 'audio_pts')
            time = source_origin + Fraction(frame.pts) * frame.time_base
            if expected_output is not None and abs(time-expected_output) > Fraction(1, 48000):
                raise ContractError('clock_mapping_unavailable', 'audio_gap')
            if first_time is None:
                first_time = time
            data = frame.to_ndarray().T.astype('<f4', copy=False)
            if data.shape != (frame.samples, channels) or not np.isfinite(data).all():
                raise ContractError('invalid_audio_samples', 'pcm')
            if total+frame.samples > max_samples:
                raise ContractError('resource_limit_exhausted', 'audio_samples')
            output.write(data.tobytes())
            total += frame.samples
            expected_output = time+Fraction(frame.samples, 48000)
        for frame in container.decode(stream):
            if getattr(frame, 'is_corrupt', False):
                raise ContractError('decode_failed', 'corrupt_audio_frame')
            if frame.pts is None:
                raise ContractError('clock_mapping_unavailable', 'audio_pts')
            time = Fraction(frame.pts) * frame.time_base
            if native_rate is None:native_rate=frame.sample_rate
            if frame.sample_rate!=native_rate:
                raise ContractError('audio_format_unavailable','changing_sample_rate')
            if expected_source is not None and abs(time-expected_source) > max(Fraction(1, frame.sample_rate), frame.time_base):
                delta=time-expected_source
                count=delta*frame.sample_rate
                if (not 0<delta<=Fraction(1,1000) or count.denominator!=1
                        or Fraction(padded+int(count),frame.sample_rate)>Fraction(5,1000)):
                    raise ContractError('clock_mapping_unavailable', 'audio_discontinuity')
                count=int(count)
                blank=av.AudioFrame(format=frame.format.name,layout=frame.layout.name,samples=count)
                for plane in blank.planes:plane.update(bytes(plane.buffer_size))
                blank.sample_rate=frame.sample_rate;blank.pts=source_samples
                blank.time_base=Fraction(1,frame.sample_rate)
                padding.append({'sample':source_samples,'samples':count,'native_time':str(expected_source)})
                for converted in resampler.resample(blank):store(converted)
                source_samples+=count;padded+=count
            if source_origin is None:
                source_origin = time
            # Containers such as Matroska may quantize packet timestamps to
            # milliseconds. Preserve those observations but resample contiguous
            # decoded samples on their exact sample clock, not jittering PTS.
            mappings.append({'sample': source_samples, 'native_time': str(time),
                             'time_base': str(frame.time_base)})
            frame.pts = source_samples
            frame.time_base = Fraction(1, frame.sample_rate)
            source_samples += frame.samples
            expected_source = source_origin+Fraction(source_samples, frame.sample_rate)
            for converted in resampler.resample(frame):
                store(converted)
        for converted in resampler.resample(None):
            store(converted)
    if not total:
        raise ContractError('decode_failed', 'audio')
    return {'status': 'decoded', 'samples': total, 'sample_rate': 48000, 'channels': channels,
            'source_origin': str(first_time-Fraction(clock['origin'])), 'clean_decode': True,
            'native_pts_mapping': mappings, 'padding_ranges':padding,
            'resampling_policy': 'explicit_padding_1ms.v1'}
