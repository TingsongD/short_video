"""Non-network verification of the locked isolated helper installation."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys

from ..domain.errors import ContractError
from .evidence_policy import PE_COMMIT, PE_SHA256


def verify_installation(root=None):
    root = Path(root or Path(__file__).resolve().parents[3])
    if sys.version_info[:2] != (3, 11):
        raise ContractError('helper_python_mismatch', 'helper', 'Requires isolated Python 3.11')
    lock = root/'config/flashcut-helper.lock'
    locked = dict(re.findall(r'^([A-Za-z0-9_.-]+)==([^\s\\]+)', lock.read_text(), re.MULTILINE))
    if not locked:
        raise ContractError('helper_lock_unavailable', 'dependencies')
    installed = {}
    for name, version in locked.items():
        try:
            installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            raise ContractError('helper_dependency_missing', name) from None
        if installed[name] != version:
            raise ContractError('helper_dependency_mismatch', name)
    source = root/'vendor/flashcut-perception-models'
    revision = subprocess.run(['git','-C',str(source),'rev-parse','HEAD'], capture_output=True, text=True)
    dirty = subprocess.run(['git','-C',str(source),'status','--porcelain','--untracked-files=all','--','core'], capture_output=True, text=True)
    if revision.returncode or revision.stdout.strip() != PE_COMMIT or dirty.returncode or dirty.stdout.strip():
        raise ContractError('pe_code_revision_mismatch', 'model')
    checkpoint = root/'vendor/flashcut-helper/models/PE-Core-S16-384.pt'
    if not checkpoint.is_file():
        raise ContractError('pe_checkpoint_unavailable', 'model', 'Explicit model setup required; automatic downloads are disabled')
    with checkpoint.open('rb') as file:
        if hashlib.file_digest(file, 'sha256').hexdigest() != PE_SHA256:
            raise ContractError('pe_checkpoint_hash_mismatch', 'model')
    return {'version': 'flashcut_helper.v1', 'python': sys.version.split()[0], 'dependencies': installed,
            'lock_sha256': hashlib.sha256(lock.read_bytes()).hexdigest(), 'pe_revision': PE_COMMIT,
            'checkpoint_sha256': PE_SHA256, 'network': 'not_used'}


if __name__ == '__main__':
    print(json.dumps(verify_installation(), sort_keys=True))
