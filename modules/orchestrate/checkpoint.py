"""Private production checkpoint; derived artifacts are reused by content hash."""
import json
import fcntl
from contextlib import contextmanager
from pathlib import Path

from modules.assets.canvas import fingerprint
from modules.assets.canvas_state import atomic_json
from modules.assemble.materials import file_hash


@contextmanager
def production_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".production.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("this production is already running") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


class Checkpoint:
    def __init__(self, directory, video_id, idea_id):
        self.path = Path(directory) / "production_state.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {
            "version": 1, "video_id": video_id, "idea_id": idea_id}
        if (self.data.get("version") != 1 or self.data.get("video_id") != video_id
                or self.data.get("idea_id") != idea_id):
            raise ValueError("production checkpoint identity mismatch")

    def save(self, **fields):
        self.data.update(fields)
        atomic_json(self.path, self.data)

    def script(self, doc):
        digest = fingerprint(doc)
        if self.data.get("shot_list_hash", digest) != digest:
            raise ValueError("saved shot list changed; use a new video ID for a new production")
        self.save(shot_list_hash=digest)

    def valid_final(self, identity):
        saved = self.data.get("assembly", {})
        if saved.get("fingerprint") != identity or len(saved.get("finals", [])) != 1:
            return None
        for item in saved["finals"]:
            path = Path(item["path"]).resolve()
            if (not path.is_relative_to(self.path.parent.resolve()) or not path.is_file()
                    or file_hash(path) != item["sha256"]):
                return None
        return [Path(i["path"]) for i in saved["finals"]]
