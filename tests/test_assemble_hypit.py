"""Optional installed-runtime regression; imports only, no network or generation."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "vendor/hypit-runtime/node_modules/@hypit/hypit"


@pytest.mark.skipif(not (DIST / "package.json").exists() or not shutil.which("node"),
                    reason="optional pinned Hypit installation is absent")
def test_caption_copy_round_trips_through_installed_markup_parser(tmp_path):
    """Assert the visible text, using the same parser that feeds typography."""
    from modules.assemble.hypit_markup import escape_markup_text

    captions = [
        "I'd keep the styling simple, then",
        "They're separate pieces; you're building outfits.",
        'She said "relaxed" — cotton & linen < $50 > $20.',
        "A literal entity: &#x27; and &apos;",
        "MsDressly’s looks\n夏日穿搭",
    ]
    documents = [f"<typo:Area>{escape_markup_text(text)}</typo:Area>" for text in captions]
    parser = (DIST / "packages/markup/src/syntax.ts").as_uri()
    code = f"""
import {{parseStructuredElement}} from {json.dumps(parser)};
const docs = JSON.parse(process.argv[1]);
const actual = docs.map(text => parseStructuredElement({{name:'caption', text}}, 0)
    .element.children.map(node => node.value ?? '').join(''));
console.log(JSON.stringify(actual));
"""
    env = {**os.environ, "NODE_OPTIONS": "--import=" + (ROOT / "scripts/hypit-node-bootstrap.mjs").as_uri()}
    result = subprocess.run([shutil.which("node"), "--input-type=module", "-e", code, json.dumps(documents)],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == captions


@pytest.mark.skipif(not (DIST / "package.json").exists() or not shutil.which("node"),
                    reason="optional pinned Hypit installation is absent")
def test_capture_child_inherits_distribution_resolution(tmp_path):
    """The real capture dependency tree must load outside a contributor checkout."""
    target = (DIST / "packages/provider-hyperframes-local/src/capture.ts").as_uri()
    # Spawn a new process like capture-process.ts; command-line preload flags
    # on the parent alone would fail to reach this child.
    child_code = f"await import({json.dumps(target)}); console.log('capture imports ready')"
    parent_code = """
import {spawnSync} from 'node:child_process';
const child = spawnSync(process.execPath, ['--input-type=module', '-e', process.argv[1]], {encoding:'utf8'});
process.stdout.write(child.stdout);
process.stderr.write(child.stderr);
process.exit(child.status ?? 1);
"""
    env = {**os.environ, "NODE_OPTIONS": "--import=" + (ROOT / "scripts/hypit-node-bootstrap.mjs").as_uri()}
    result = subprocess.run([shutil.which("node"), "--input-type=module", "-e", parent_code, child_code],
                            cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "capture imports ready" in result.stdout
