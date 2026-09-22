"""Run in the isolated helper; no downloads or providers are permitted."""
from pathlib import Path
import pytest

np = pytest.importorskip('numpy', reason='VALIDATION GAP: run isolated flash-cut helper tests')


def test_actual_pe_retains_every_supplied_frame_and_is_deterministic():
    from PIL import Image
    from modules.factory.analysis.frame_encoder import PEEncoder
    root = Path(__file__).resolve().parents[2]
    encoder = PEEncoder(root/'vendor/flashcut-perception-models',
                        root/'vendor/flashcut-helper/models/PE-Core-S16-384.pt')
    images = [Image.new('RGB', (72, 128), color) for color in ('red', 'green', 'red')]
    features = encoder.encode(images)
    assert features.shape == (3, 512)
    assert np.allclose(features[0], features[2], atol=1e-6)
    assert not np.allclose(features[0], features[1], atol=1e-3)
    assert np.allclose(np.linalg.norm(features, axis=1), 1, atol=1e-5)


@pytest.mark.parametrize('maximum',[2,0])
def test_allocation_recovery_reduces_batches_never_frame_coverage(maximum):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from modules.factory.analysis.frame_encoder import PEEncoder
    from modules.factory.domain.errors import ContractError
    calls=[]
    def encode(batch,normalize):
        calls.append(len(batch))
        if len(batch)>maximum:raise MemoryError('synthetic allocation failure')
        values=np.zeros((len(batch),512),dtype=np.float32)
        values[:,0]=batch
        return SimpleNamespace(cpu=lambda:SimpleNamespace(numpy=lambda:values))
    encoder=PEEncoder.__new__(PEEncoder)
    encoder.torch=SimpleNamespace(stack=lambda x:x,inference_mode=nullcontext,OutOfMemoryError=MemoryError)
    encoder.model=SimpleNamespace(encode_image=encode)
    encoder.preprocess=lambda x:x;encoder.batch_size=8
    if maximum:
        result=encoder.encode(list(range(8)))
        assert result[:,0].tolist()==list(range(8))
        assert calls==[8,4,2,2,2,2]
    else:
        with pytest.raises(ContractError,match='resource_limit_exhausted'):
            encoder.encode(list(range(8)))
        assert calls==[8,4,2,1]
