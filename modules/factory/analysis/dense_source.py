"""Local dense analysis, behind the durable source-evidence interface."""
from fractions import Fraction
from pathlib import Path
import tempfile

from ..domain.errors import ContractError
from ..media.source_clock import source_clock, visual_batches, extract_audio
from ..media.audio_events import analyze_audio, CORE
from .event_fusion import fuse_events, visual_recurrences
from .evidence_policy import validate_flashcut_policy


def analyze_source(evidence, evidence_id, source, encoder, *, binding, lease=None, progress=None):
    """Complete immutable evidence from a local decoder and injected encoder.

    A cheap clock pass establishes decoded ranges; one subsequent streamed
    pass feeds both pixel-change measurements and PE. Resumed chunks skip PE,
    never timestamps. The encoder cannot initiate hosted provider operations.
    """
    import numpy as np
    record = evidence.get(evidence_id)
    policy = validate_flashcut_policy(record['policy'])
    progress = progress or (lambda **kwargs: None)
    args = {'current_binding': binding, 'lease': lease}
    def scan():
        clock = source_clock(source)
        if clock['source_sha256'] != binding['source_sha256']:
            raise ContractError('source_evidence_stale', 'source_sha256')
        frames, clean = [], None
        for batch in visual_batches(source, clock):
            if batch.get('clean_decode'):
                clean = batch
            else:
                frames.extend(batch['frames'])
                progress(stage='clock', decoded_frames=len(frames))
                if len(frames) > policy['resources']['max_decoded_frames']:
                    raise ContractError('resource_limit_exhausted', 'frame_count', 'Maximum 18000 decoded positions per profile')
        if not clean or clean['decoded_frames'] != len(frames):
            raise ContractError('coverage_incomplete', 'clock')
        last = frames[-1]
        if not last['duration_pts'] or last['duration_pts'] <= 0:
            raise ContractError('clock_mapping_unavailable', 'last_frame_duration')
        duration = Fraction(last['source_time']) + Fraction(last['duration_pts'])*Fraction(last['time_base'])
        if duration > policy['resources']['max_media_seconds']:
            raise ContractError('resource_limit_exhausted', 'source_duration', 'Profile supports at most 600 seconds.')
        native = clock['video']
        if native['start_pts'] is not None and native['duration_pts'] is not None:
            declared = Fraction(native['start_pts']+native['duration_pts'])*Fraction(native['time_base'])-Fraction(clock['origin'])
            if declared-duration > Fraction(last['duration_pts'])*Fraction(last['time_base']):
                raise ContractError('decode_truncated', 'video_tail')
        return {**clock, 'frames': frames, 'duration': str(duration), **clean}
    clock = evidence.chunk(evidence_id, 'clock', 0, 1, scan, **args)['data']
    # Bind cached evidence to the actual bytes as well, not just a registry row.
    import hashlib
    with Path(source).open('rb') as file:
        if hashlib.file_digest(file, 'sha256').hexdigest() != binding['source_sha256']:
            raise ContractError('source_evidence_stale', 'source_sha256')
    total = clock['decoded_frames']
    clean = {}
    def inputs():
        for batch in visual_batches(source, clock):
            if batch.get('clean_decode'):
                clean.update(batch)
            else:
                yield from zip(batch['frames'], batch['images'])
    stream = iter(inputs())
    previous, all_frames, all_vectors, reused = None, [], [], 0
    for start in range(0, total, 256):
        end = min(start+256, total)
        def produce(start=start, end=end):
            nonlocal previous
            output, embeddings, image_batch, frame_batch = [], [], [], []
            def encode():
                nonlocal previous
                features = encoder.encode(image_batch)
                if features.shape != (len(frame_batch), 512) or not np.isfinite(features).all():
                    raise ContractError('pe_invalid_embeddings', 'frames')
                for frame, vector in zip(frame_batch, features):
                    novelty = 0 if previous is None else max(0, 1-float(np.dot(previous, vector)))
                    output.append({**frame, 'novelty': novelty})
                    embeddings.append(vector.tolist())
                    previous = vector
                progress(stage='visual', encoded_frames=output[-1]['index']+1, total_frames=total)
                image_batch.clear()
                frame_batch.clear()
            while len(output) + len(frame_batch) < end-start:
                try:
                    frame, image = next(stream)
                except StopIteration:
                    raise ContractError('coverage_incomplete', 'visual') from None
                if frame['index'] < start:
                    continue
                expected = clock['frames'][frame['index']]
                if frame['index'] != start+len(output)+len(frame_batch) or frame['pixel_sha256'] != expected['pixel_sha256'] or frame['source_time'] != expected['source_time']:
                    raise ContractError('source_evidence_stale', 'decoded_frame')
                frame_batch.append(frame)
                image_batch.append(image)
                if len(frame_batch) == 8:
                    encode()
            if frame_batch:
                encode()
            return {'frames': output, 'embeddings': embeddings, 'frame_count': len(output)}
        chunk = evidence.chunk(evidence_id, 'visual', start, end, produce, **args)
        data = chunk['data']
        if data['frame_count'] != end-start:
            raise ContractError('coverage_incomplete', 'visual')
        all_frames.extend(data['frames'])
        all_vectors.extend(data['embeddings'])
        previous = np.array(data['embeddings'][-1], dtype=np.float32)
        reused += int(chunk['reused'])
        progress(stage='visual', encoded_frames=end, total_frames=total, cache_reused_chunks=reused)
    # Validate full decode completion even when every embedding came from cache.
    for _ in stream:
        pass
    if clean.get('decoded_frames') != total:
        raise ContractError('coverage_incomplete', 'visual_eof')
    audio_events, audio_origin, audio_total = [], '0', 1
    if clock['audio'] is None:
        evidence.chunk(evidence_id, 'audio', 0, 1,
                       lambda: {'status': 'not_applicable_no_stream', 'events': [], 'processed_samples': 0}, **args)
    else:
        with tempfile.TemporaryDirectory(prefix='audio-', dir=evidence.blobs.root) as temporary:
            path = Path(temporary)/'audio.f32'
            audio = extract_audio(source, clock, path, max_samples=48000*policy['resources']['max_media_seconds'])
            audio_total, audio_origin = audio['samples'], audio['source_origin']
            samples = np.memmap(path, mode='r', dtype='<f4', shape=(audio_total, audio['channels']))
            for start in range(0, audio_total, CORE):
                end = min(start+CORE, audio_total)
                chunk = evidence.chunk(evidence_id, 'audio', start, end,
                    lambda start=start, end=end: {**analyze_audio(samples, core_start=start, core_end=end),
                                                  'source_origin': audio_origin, 'clock': audio}, **args)
                audio_events.extend(chunk['data']['events'])
                progress(stage='audio', processed_audio_samples=end, total_audio_samples=audio_total,
                         audio_status=chunk['data']['status'], rhythm_status=chunk['data']['rhythm_status'])
            del samples
    fusion = evidence.chunk(evidence_id, 'fusion', 0, 1,
                   lambda: fuse_events(all_frames, audio_events, audio_origin=audio_origin, duration=clock['duration'],
                                       recurrences=visual_recurrences(all_frames,all_vectors)), **args)['data']
    from .selected_media import materialize_selected
    from ..artifacts.registry import ArtifactStore
    row = evidence.db.conn.execute("SELECT value FROM meta WHERE key='artifact_root'").fetchone()
    artifacts = ArtifactStore(row[0] if row else evidence.blobs.root.parent/'artifacts', evidence.db)
    evidence.chunk(evidence_id, 'media', 0, 1,
                   lambda: materialize_selected(source,clock,fusion,artifacts,evidence.blobs.root,progress=progress), **args)
    return evidence.complete(evidence_id, {'clock': 1, 'visual': total, 'audio': audio_total, 'fusion': 1, 'media':1}, **args)
