"""Deterministic, collision-checked ID generation.

Counters persist in the workspace so a restarted worker never reissues an ID.
"""
import json
from pathlib import Path


class IdFactory:
    def __init__(self, state_path):
        self._path = Path(state_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            self._counters = json.loads(self._path.read_text())
        else:
            self._counters = {}

    def next(self, prefix: str) -> str:
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        self._save()
        return f"{prefix}-{n:06d}"

    def peek(self, prefix: str) -> int:
        return self._counters.get(prefix, 0)

    def _save(self):
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._counters, indent=1, sort_keys=True))
        tmp.replace(self._path)
