"""QA workspace lifecycle (F01).

A workspace is an isolated directory holding fixtures, fake-remote state,
run records and evidence. It contains only generated QA data and lives
under git-ignored data/factory-qa/.
"""
import json
import sys
from pathlib import Path

from ..testing.fixtures import manifest, materialize
from ..testing.ids import IdFactory
from ..testing.clock import FakeClock, utcnow_iso

SCHEMA = "factory.qa_workspace.v1"
SUBDIRS = ("fixtures", "fake_remote", "runs", "evidence", "artifacts",
           "media", "db", "tmp")


class WorkspaceError(RuntimeError):
    pass


def init(path, fixture):
    """Create a workspace; refuse an occupied root. Returns metadata."""
    path = Path(path)
    if path.exists() and any(path.iterdir()):
        raise WorkspaceError(
            f"workspace {path} is occupied; choose a new path or pass "
            "an explicit resume command — init never deletes files")
    path.mkdir(parents=True, exist_ok=True)
    for d in SUBDIRS:
        (path / d).mkdir(exist_ok=True)

    known = manifest()["fixtures"]
    if fixture not in known:
        raise WorkspaceError(
            f"unknown fixture {fixture!r}; known: {', '.join(sorted(known))}")

    meta = {"schema_version": SCHEMA, "fixture": fixture,
            "created_at": utcnow_iso(),
            "python": sys.version.split()[0]}
    lock = materialize(fixture, path)
    _write(path / "workspace.json", meta)
    _write(path / "fixture-lock.json", lock)
    return meta


def open_workspace(path):
    path = Path(path)
    meta_path = path / "workspace.json"
    if not meta_path.exists():
        raise WorkspaceError(f"no QA workspace at {path} — run `init` first")
    return Workspace(path)


def _write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True))
    tmp.replace(path)


class Workspace:
    def __init__(self, path):
        self.path = Path(path)
        self.meta = json.loads((self.path / "workspace.json").read_text())
        self.ids = IdFactory(self.path / "fake_remote" / "ids.json")

    @property
    def fixture(self):
        return self.meta["fixture"]

    def dir(self, name):
        d = self.path / name
        d.mkdir(exist_ok=True)
        return d

    def clock(self, run_dir=None):
        """Fresh deterministic clock; run records may persist a later offset."""
        return FakeClock()

    def run_dir(self, case_id, run_id):
        d = self.path / "runs" / case_id / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d
