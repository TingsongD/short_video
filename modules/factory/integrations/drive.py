"""Drive adapter boundary (F25): upload/list/stat through the existing
authorized `gdrive` CLI. Injectable transport; credentials live in the
CLI's own store — never logged, never in project state.
"""
import hashlib
import json
import re
import subprocess
import tempfile
import shutil
from pathlib import Path


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

    def __init__(self, runner=None, binary="gdrive", policy=None, expected_account=None):
        from ..execution.policy import live_transport
        if runner is None:
            runner = live_transport(subprocess.run, "drive", policy)
            if not expected_account:
                from ..domain.errors import ContractError
                raise ContractError('delivery_account_required','account')
            real_runner = runner
            runner = lambda argv, timeout=300: real_runner(
                argv, capture_output=True, text=True, timeout=timeout)
        self.binary = binary
        self.expected_account = expected_account
        self.runner = runner or (
            lambda argv, timeout=300: subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout))

    def _check_account(self, submitting=False):
        if not self.expected_account:
            return  # injected protocol fixtures; configured live routes require it
        if submitting:
            from ..execution.context import current_effect
            from ..domain.errors import ContractError
            grant=current_effect.get()
            if not grant or grant.get('provider')!='drive' or grant.get('account')!=self.expected_account:
                raise ContractError('delivery_account_scope_mismatch','account')
        result=self.runner([self.binary,'account','current'])
        if result.returncode or result.stdout.strip()!=self.expected_account:
            raise RuntimeError('drive_account_mismatch')

    def list_files(self, parent_id):
        self._check_account()
        # gdrive paginates internally up to --max. Grow that bound until the
        # returned count proves exhaustion; never treat a full page as complete.
        maximum = 1000
        while maximum <= 128000:
            r = self.runner([self.binary, "files", "list", "--parent", parent_id,
                "--max", str(maximum), "--skip-header", "--full-name", "--field-separator", "\t"])
            if r.returncode:
                raise RuntimeError("drive_list_failed")
            files = []
            for line in r.stdout.splitlines():
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) < 2 or not re.fullmatch(r"[A-Za-z0-9_-]+", parts[0]):
                    raise RuntimeError("drive_listing_malformed")
                files.append({"id": parts[0], "name": parts[1]})
            if len({f["id"] for f in files}) != len(files):
                raise RuntimeError("drive_listing_duplicates")
            if len(files) < maximum:
                return files
            maximum *= 2
        raise RuntimeError("drive_listing_incomplete")

    def upload(self, parent_id, path, name):
        self._check_account(submitting=True)
        if not name or name != Path(name).name or any(c in name for c in "\r\n\t"):
            raise ValueError("invalid_delivery_name")
        with tempfile.TemporaryDirectory(prefix="factory-drive-") as temporary:
            copy = Path(temporary) / name
            shutil.copyfile(path, copy)
            r = self.runner([self.binary, "files", "upload", "--parent", parent_id,
                             "--print-only-id", str(copy)])
        if r.returncode:
            raise RuntimeError("drive_upload_failed_reconcile_before_retry")
        fid = r.stdout.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]+", fid):
            raise RuntimeError("drive_upload_identity_unknown")
        return {"id": fid}

    def stat(self, file_id):
        self._check_account()
        r = self.runner([self.binary, "files", "info", "--size-in-bytes", file_id])
        if r.returncode != 0:
            return None
        info = {}
        for line in r.stdout.splitlines():
            m = re.match(r"^(\w[\w ]*?):\s+(.+)$", line.strip())
            if m:
                k = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_",
                           m.group(1).strip()).lower()
                info[k.replace(" ", "_")] = m.group(2).strip()
        if not info.get("size", "").isdigit():
            raise RuntimeError("drive_metadata_size_invalid")
        parents = re.findall(r"[A-Za-z0-9_-]+", info.get("parents", ""))
        return {"id": file_id, "name": info.get("name"),
                "md5": info.get("md5") or info.get("md5_checksum"),
                "size": int(info.get("size", "0") or 0),
                "parent": parents[0] if len(parents) == 1 else None, "parents": parents}


def local_md5(path):
    import hashlib as h
    return h.md5(open(path, "rb").read()).hexdigest()
