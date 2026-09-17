"""Drive adapter boundary (F25): upload/list/stat through the existing
authorized `gdrive` CLI. Injectable transport; credentials live in the
CLI's own store — never logged, never in project state.
"""
import hashlib
import json
import re
import subprocess


class DriveAdapter:
    name = "google_drive"

    def list_files(self, parent_id):
        """→ [{id,name,md5,size,parent}] — remote truth."""
        raise NotImplementedError

    def upload(self, parent_id, path, name):
        """→ {"id": file_id}. A lost acknowledgement raises AFTER the
        remote file may exist — callers reconcile, never assume."""
        raise NotImplementedError

    def stat(self, file_id):
        """→ {id,name,md5,size,parent} or None."""
        raise NotImplementedError

    def link(self, file_id):
        return f"https://drive.google.com/file/d/{file_id}/view"


class GdriveCLI(DriveAdapter):
    """Real adapter over `gdrive files …` (existing authorized CLI)."""

    def __init__(self, runner=None, binary="gdrive"):
        self.binary = binary
        self.runner = runner or (
            lambda argv, timeout=300: subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout))

    def list_files(self, parent_id):
        r = self.runner([self.binary, "files", "list", "--parent",
                         parent_id, "--max", "1000"])
        if r.returncode != 0:
            raise RuntimeError(f"list failed: {r.stderr[-200:]}")
        files = []
        for line in r.stdout.splitlines():
            parts = re.split(r"\s{2,}", line.strip())
            if len(parts) >= 2 and parts[0] \
                    and not parts[0].lower().startswith("id"):
                files.append({"id": parts[0], "name": parts[1]})
        return files

    def upload(self, parent_id, path, name):
        # delivery copy keeps the descriptive name; source stays put
        r = self.runner([self.binary, "files", "upload", "--parent",
                         parent_id, "--print-only-id", str(path)])
        if r.returncode != 0:
            raise RuntimeError(f"upload failed: {r.stderr[-200:]}")
        fid = r.stdout.strip().splitlines()[-1].strip()
        if not fid:
            raise RuntimeError("upload returned no file id")
        return {"id": fid}

    def stat(self, file_id):
        r = self.runner([self.binary, "files", "info", file_id])
        if r.returncode != 0:
            return None
        info = {}
        for line in r.stdout.splitlines():
            m = re.match(r"^(\w[\w ]*?):\s+(.+)$", line.strip())
            if m:
                k = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_",
                           m.group(1).strip()).lower()
                info[k.replace(" ", "_")] = m.group(2).strip()
        return {"id": file_id, "name": info.get("name"),
                "md5": info.get("md5_checksum"),
                "size": int(info.get("size", "0") or 0),
                "parent": (info.get("parents") or "").split(",")[0]}


def local_md5(path):
    import hashlib as h
    return h.md5(open(path, "rb").read()).hexdigest()
