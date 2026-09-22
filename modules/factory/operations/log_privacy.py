"""Explicit-file, dry-run-first credential cleanup. Never retains raw backups."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import gzip

from ..events.redact import redact_log


def sanitize_log(path, *, apply=False, writer_stopped=False, archive_to=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise ValueError('Expected a regular, non-linked log file')
    before = path.stat()
    raw = path.read_text(encoding='utf-8', errors='replace')
    clean = redact_log(raw)
    result = {'file': path.name, 'changed_lines': sum(a != b for a, b in
        zip(raw.splitlines(), clean.splitlines())), 'applied': False}
    if not apply: return result
    if not writer_stopped: raise RuntimeError('Stop and verify the affected log writer first')
    if archive_to:
        # Preserve an oversized legacy log as a private, sanitized archive,
        # allowing the new bounded writer to start with an empty active file.
        archive = Path(archive_to)
        fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as out:
            with gzip.GzipFile(fileobj=out, mode='wb', filename='') as compressed:
                compressed.write(clean.encode())
            out.flush(); os.fsync(out.fileno())
        clean = ''
    fd, temp = tempfile.mkstemp(prefix='.sanitized-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(clean); out.flush(); os.fsync(out.fileno())
        after = path.stat()
        if (before.st_ino, before.st_mtime_ns, before.st_size) != (after.st_ino, after.st_mtime_ns, after.st_size):
            raise RuntimeError('Log writer changed the file; cleanup refused')
        os.replace(temp, path)
        result['applied'] = True
        return result
    finally:
        Path(temp).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('paths', nargs='+')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--archive-to')
    args = parser.parse_args()
    paths = [Path(p).absolute() for p in args.paths]
    if args.archive_to and len(paths) != 1: parser.error('Archive exactly one explicit log at a time')
    # Refuse a live writer rather than trusting a command-line assertion.
    for path in paths:
        if args.apply:
            check = subprocess.run(['lsof', '-t', '--', str(path)], capture_output=True)
            if check.returncode not in (0, 1) or check.stdout.strip():
                raise RuntimeError('Log file still open, or writer check unavailable')
        print(json.dumps(sanitize_log(path, apply=args.apply, writer_stopped=args.apply, archive_to=args.archive_to)))


if __name__ == '__main__': main()
