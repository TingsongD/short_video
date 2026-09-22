#!/usr/bin/env python3
"""Explicit install/check command. Never imported by jobs or tests to download."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.factory.analysis.evidence_policy import PE_COMMIT, PE_REVISION, PE_SHA256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='Explicitly install the isolated locked environment and public PE source')
    parser.add_argument('--python', help='Existing Python 3.11 interpreter; required with --install')
    parser.add_argument('--download-model', action='store_true', help='Explicitly download the pinned public 349 MB checkpoint')
    args = parser.parse_args()
    env = ROOT/'vendor/flashcut-helper/.venv'
    source = ROOT/'vendor/flashcut-perception-models'
    if args.install:
        if not args.python:
            parser.error('--install requires --python pointing to an existing Python 3.11 interpreter')
        version = subprocess.check_output([args.python, '-c', 'import sys; print("%d.%d"%sys.version_info[:2])'], text=True).strip()
        if version != '3.11':
            parser.error('The helper requires Python 3.11; do not reuse the app or WhisperX environment')
        uv = shutil.which('uv')
        if not uv:
            parser.error('Install uv explicitly before setting up this helper')
        if not env.exists():
            subprocess.run([uv,'venv','--python',args.python,str(env)], check=True)
        subprocess.run([uv,'pip','sync','--python',str(env/'bin/python'),'--require-hashes',
                        str(ROOT/'config/flashcut-helper.lock')], check=True)
        if not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['git','clone','--no-checkout','https://github.com/facebookresearch/perception_models.git',str(source)], check=True)
            subprocess.run(['git','-C',str(source),'checkout','--detach',PE_COMMIT], check=True)
        actual = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'], text=True).strip()
        if actual != PE_COMMIT:
            parser.error('Existing PE checkout differs from the pinned version; left unchanged')
    model = ROOT/'vendor/flashcut-helper/models/PE-Core-S16-384.pt'
    if args.download_model and not model.exists():
        model.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        url = f'https://huggingface.co/facebook/PE-Core-S16-384/resolve/{PE_REVISION}/PE-Core-S16-384.pt'
        with tempfile.TemporaryDirectory(prefix='model-download-', dir=model.parent) as directory:
            staged = Path(directory)/model.name
            with urllib.request.urlopen(url, timeout=120) as response, staged.open('xb') as file:
                shutil.copyfileobj(response, file)
            with staged.open('rb') as file:
                if hashlib.file_digest(file,'sha256').hexdigest() != PE_SHA256:
                    raise RuntimeError('Checkpoint checksum mismatch; model not published')
            # Never replace an existing model, even if another setup raced us.
            import os
            os.link(staged, model)
    if not (env/'bin/python').is_file():
        parser.error('Helper is not installed. Use explicit --install; no download was attempted')
    subprocess.run([str(env/'bin/python'),'-m','modules.factory.analysis.helper_readiness'], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
