"""Explicitly installed, local-only PE adapter for the isolated media helper."""
import hashlib
from pathlib import Path
import subprocess
import sys

from ..domain.errors import ContractError
from .evidence_policy import PE_COMMIT, PE_SHA256


class PEEncoder:
    def __init__(self, source_root, checkpoint):
        source_root, checkpoint = Path(source_root).resolve(), Path(checkpoint).resolve()
        if not checkpoint.is_file():
            raise ContractError('pe_checkpoint_unavailable', 'model', 'Run explicit helper setup; jobs never download models.')
        with checkpoint.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest != PE_SHA256:
            raise ContractError('pe_checkpoint_hash_mismatch', 'model')
        result = subprocess.run(['git', '-C', str(source_root), 'rev-parse', 'HEAD'],
                                capture_output=True, text=True, check=False)
        dirty = subprocess.run(['git', '-C', str(source_root), 'diff', '--quiet', 'HEAD', '--', 'core'], check=False)
        if result.returncode or result.stdout.strip() != PE_COMMIT or dirty.returncode:
            raise ContractError('pe_code_revision_mismatch', 'model')
        import torch
        torch.set_num_threads(4)
        # This module lives in a dedicated process; it must not change the app
        # or WhisperX tensor runtime. No device/precision fallback is allowed.
        sys.path.insert(0, str(source_root))
        from core.vision_encoder.pe import CLIP
        from core.vision_encoder.transforms import get_image_transform
        self.torch = torch
        self.model = CLIP.from_config('PE-Core-S16-384', pretrained=False)
        state = torch.load(checkpoint, map_location='cpu', weights_only=True)
        state = state.get('state_dict', state.get('weights', state))
        state = {k.removeprefix('module.'): v for k, v in state.items()}
        self.model.load_state_dict(state, strict=True)
        self.model.eval().float()
        self.preprocess = get_image_transform(384, center_crop=False)
        self.batch_size = 8

    def encode(self, images):
        import numpy as np
        if not images:
            return np.empty((0, 512), dtype=np.float32)
        if len(images) > 16:
            raise ContractError('pe_queue_limit', 'frames')
        output, offset = [], 0
        while offset < len(images):
            group = images[offset:offset+self.batch_size]
            try:
                batch = self.torch.stack([self.preprocess(image) for image in group])
                with self.torch.inference_mode():
                    features = self.model.encode_image(batch, normalize=True).cpu().numpy()
            except (MemoryError, self.torch.OutOfMemoryError):
                if self.batch_size == 1:
                    raise ContractError('resource_limit_exhausted', 'pe_batch') from None
                self.batch_size //= 2
                continue
            if features.shape != (len(group), 512) or not np.isfinite(features).all():
                raise ContractError('pe_invalid_embeddings', 'frames')
            output.append(features)
            offset += len(group)
        return np.concatenate(output)
