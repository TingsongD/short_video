"""Identify launcher processes by command, working directory and project root.

Only prints process IDs. Stop mode rechecks process birth before signalling.
"""
import argparse
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys

from ...batch.local import process_table, same_process


def matches(command, cwd, root, component):
    root, cwd = Path(root).resolve(), Path(cwd).resolve()
    marker = ' -m modules.factory.cli '
    if marker not in command:
        return False
    executable, args = command.split(marker, 1)
    # ps does not quote executable paths that contain spaces.
    permitted = {str(root / '.venv/bin/python'), '.venv/bin/python',
                 str((root / '.venv/bin/python').resolve())}
    if executable.strip('"\'') not in permitted or cwd != root:
        return False
    try:
        words = shlex.split(args)
        target = cwd
        if words[:1] == ['--root']:
            target = (cwd / words[1]).resolve()
            words = words[2:]
        elif words and words[0].startswith('--root='):
            target = (cwd / words[0].split('=', 1)[1]).resolve()
            words = words[1:]
        return target == root and bool(words) and words[0] == component
    except (ValueError, IndexError):
        return False


def working_directory(pid):
    if sys.platform != 'darwin':
        return Path(f'/proc/{pid}/cwd').resolve(strict=True)
    result = subprocess.run(['lsof', '-a', '-p', str(pid), '-d', 'cwd', '-Fn'],
                            capture_output=True, text=True, timeout=10)
    paths = [line[1:] for line in result.stdout.splitlines() if line.startswith('n/')]
    if result.returncode or len(paths) != 1:
        raise OSError('process working directory unavailable')
    return Path(paths[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root')
    parser.add_argument('component', choices=['serve', 'worker'])
    parser.add_argument('--pid', type=int)
    parser.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    for pid, row in process_table().items():
        if pid == os.getpid() or args.pid is not None and pid != args.pid:
            continue
        if ' -m modules.factory.cli ' not in row['command']:
            continue
        try:
            if not matches(row['command'], working_directory(pid), args.root, args.component):
                continue
            if args.stop:
                current = process_table().get(pid)
                if not same_process(row, current) or not matches(current['command'], working_directory(pid), args.root, args.component):
                    continue
                os.kill(pid, signal.SIGTERM)
            print(pid)
        except (OSError, subprocess.SubprocessError):
            # An unreadable or exited process cannot establish ownership.
            continue


if __name__ == '__main__':
    main()
