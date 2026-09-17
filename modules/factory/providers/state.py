"""Private, atomic adapter receipts; provider payloads and credentials stay out."""
import json
import os
import fcntl
import threading
from contextlib import contextmanager
from pathlib import Path
from ..events.redact import redact
from ..domain.errors import ContractError


class DurableState(dict):
    def __init__(self, path):
        self.path = Path(path)
        self._mutex = threading.RLock()
        self._depth = 0
        super().__init__(json.loads(self.path.read_text()) if self.path.exists() else {})

    @contextmanager
    def locked(self):
        with self._mutex:
            if self._depth:
                yield
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix(".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                self._depth += 1
                try:
                    if self.path.exists():
                        saved = json.loads(self.path.read_text())
                        self.clear()
                        self.update(saved)
                    yield
                finally:
                    self._depth -= 1
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def flush(self):
        if redact(dict(self)) != dict(self):
            raise ContractError("sensitive_adapter_state", "state")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(self, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)


def receipt_locked(method):
    """Serialize receipt mutation across adapter instances and worker processes.

    Remote generation remains concurrent; only short submission/observation
    commands hold this lock. A second process reloads the latest receipt first.
    """
    from functools import wraps
    @wraps(method)
    def call(self, *args, **kwargs):
        state = self.state
        if not isinstance(state, DurableState):
            return method(self, *args, **kwargs)
        with state.locked():
            return method(self, *args, **kwargs)
    return call
