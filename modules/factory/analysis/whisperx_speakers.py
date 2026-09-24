"""Repository-owned extension of the installed WhisperX service, loaded lazily."""
import threading
import tomllib
from pathlib import Path

from .speakers import MODEL, POLICY, label_words


class SpeakerEngine:
    def __init__(self, engine, root, pipeline_factory=None):
        self.engine, self.root = engine, Path(root)
        self.factory, self.pipeline = pipeline_factory, None
        self.lock = threading.Lock()

    def identity(self):
        return {**self.engine.identity(), 'speakerPolicy': POLICY, 'diarizationModel': MODEL}

    def transcribe(self, audio, language):
        from hypit_whisperx_service.engine import InferenceBusyError
        if not self.lock.acquire(blocking=False):
            raise InferenceBusyError('The speech model is already processing a request.')
        try:
            result = self.engine.transcribe(audio, language)
            try:
                if self.pipeline is None:
                    with (self.root/'config/secrets.toml').open('rb') as stream:
                        token = tomllib.load(stream).get('HF_TOKEN')
                    if not token:
                        raise ValueError('diarization_credentials_missing')
                    if self.factory is None:
                        from whisperx.diarize import DiarizationPipeline
                        self.factory = DiarizationPipeline
                    self.pipeline = self.factory(model_name=MODEL, token=token,
                        device=self.engine.identity()['device'])
                import numpy as np
                samples = np.frombuffer(audio.pcm_s16le, dtype='<i2').astype(np.float32) / 32768.0
                frame = self.pipeline(samples)
                intervals = [{'start': float(row['start']), 'end': float(row['end']),
                              'speaker': str(row['speaker'])} for _, row in frame.iterrows()]
                return label_words(result, intervals)
            except Exception as error:
                # Preserve STT evidence, but never label plain ASR as diarized.
                # Provider errors may contain tokens/URLs: expose only the type.
                return {**result, 'diarization': {'policy': POLICY, 'model': MODEL,
                    'status': 'unavailable', 'error_type': type(error).__name__,
                    'issues': ['Configure HF_TOKEN and accepted pyannote model access; then rerun source evidence.']}}
        finally:
            self.lock.release()
