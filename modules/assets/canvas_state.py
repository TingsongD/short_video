"""Private, atomic recovery state and a process lock for Canvas operations."""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .canvas_cli import CanvasError


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def generation_lock(base):
    path = Path(base) / ".jimeng-canvas.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CanvasError("another_canvas_command_running") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def read_state(path):
    try:
        doc = json.loads(Path(path).read_text())
        if doc.get("version") != 1 or not isinstance(doc.get("shots"), list):
            raise ValueError()
        return doc
    except FileNotFoundError:
        raise CanvasError("job_not_prepared", "run assets prepare first") from None
    except (ValueError, TypeError, AttributeError):
        raise CanvasError("job_state_corrupt", "retain the file and inspect the canvas") from None
