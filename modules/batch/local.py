"""Local command ownership, media checks and verified Google Drive delivery."""
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

from .state import Pause, digest, now, read, write


def process_table():
    r = subprocess.run(["ps", "-axo", "pid=,ppid=,lstart=,command="], capture_output=True, text=True, check=True)
    result = {}
    for line in r.stdout.splitlines():
        parts = line.strip().split(None, 7)
        if len(parts) == 8:
            pid, parent = map(int, parts[:2])
            result[pid] = {"pid": pid, "ppid": parent, "birth": " ".join(parts[2:7]), "command": parts[7]}
    return result


def descendants(table, roots):
    found = set(roots)
    while True:
        extra = {pid for pid, row in table.items() if row["ppid"] in found} - found
        if not extra:
            return found
        found |= extra


def same_process(saved, current):
    return bool(current and saved["pid"] == current["pid"] and saved["birth"] == current["birth"]
                and saved["command"] == current["command"])


class Local:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.receipt = self.folder / "process-ownership.json"
        self.owned = read(self.receipt) if self.receipt.exists() else {"processes": {}, "ports": []}

    def capture(self, roots=()):
        table = process_table()
        previous = {int(pid) for pid, saved in self.owned["processes"].items()
                    if same_process(saved, table.get(int(pid)))}
        # Project-specific runtime paths identify reparented workers after CLI exit.
        marked = {pid for pid, row in table.items()
                  if str(self.folder / ".hypit") in row["command"] and pid != os.getpid()}
        for pid in descendants(table, set(roots) | previous | marked):
            if pid in table and pid != os.getpid():
                self.owned["processes"][str(pid)] = table[pid]
        write(self.receipt, self.owned)

    def run(self, argv, timeout=180, json_output=False, stderr_output=False):
        # Arguments/errors are deliberately not echoed: provider CLIs can include private data.
        with subprocess.Popen(list(map(str, argv)), cwd=self.folder, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, start_new_session=True) as proc:
            self.capture([proc.pid])
            started = time.monotonic()
            while True:
                try:
                    out, err = proc.communicate(timeout=5)
                    break
                except subprocess.TimeoutExpired:
                    self.capture([proc.pid])
                    if time.monotonic() - started > timeout:
                        os.killpg(proc.pid, signal.SIGTERM)
                        try:
                            proc.communicate(timeout=5)
                        except subprocess.TimeoutExpired:
                            os.killpg(proc.pid, signal.SIGKILL)
                            proc.communicate()
                        raise Pause(f"Local {Path(str(argv[0])).name} timed out; recover saved operation") from None
        self.capture()
        if proc.returncode:
            raise Pause(f"Local {Path(str(argv[0])).name} failed (exit {proc.returncode})")
        if json_output:
            try:
                return json.loads(out)
            except ValueError:
                raise Pause("Malformed local command response") from None
        return err if stderr_output else out

    def cleanup(self, hypit=None):
        self.capture()
        if hypit and (self.folder / "hypit.runtime.json").exists():
            try:
                self.run([hypit, "runtime", "down", "--runtime", "hypit.runtime.json", "--json"], timeout=40)
            except Pause:
                pass  # verify and stop only recorded surviving processes below
        self.capture()
        recorded = self.owned["processes"]
        table = process_table()
        live = [s for s in recorded.values() if same_process(s, table.get(s["pid"]))]
        ports = set(self.owned["ports"])
        for saved in live:
            r = subprocess.run(["lsof", "-nP", "-a", "-p", str(saved["pid"]), "-iTCP", "-sTCP:LISTEN", "-Fn"], capture_output=True, text=True)
            ports.update(int(x) for x in re.findall(r":(\d+)\s*$", r.stdout, re.M))
        self.owned["ports"] = sorted(ports)
        write(self.receipt, self.owned)
        for sig in (signal.SIGTERM, signal.SIGKILL):
            table = process_table()
            survivors = [s for s in live if same_process(s, table.get(s["pid"]))]
            for saved in survivors:
                try:
                    os.kill(saved["pid"], sig)
                except ProcessLookupError:
                    pass
            if survivors:
                time.sleep(2)
        table = process_table()
        survivors = [s["pid"] for s in live if same_process(s, table.get(s["pid"]))]
        occupied = []
        for port in ports:
            r = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True)
            if r.stdout.strip():
                occupied.append(port)  # do not kill an unrelated owner
        health = self.health()
        free_percent, free_disk = health["memory_free_percent"], health["disk_free_bytes"]
        result = {"state": "verified" if not survivors and not occupied and free_percent is not None
                  and free_percent >= 15 and free_disk >= 25 * 1024**3 else "blocked",
                  "at": now(), "remaining_owned_pids": survivors, "occupied_ports": occupied,
                  "recorded_ports": sorted(ports), **health}
        write(self.folder / "cleanup-receipt.json", result)
        return result

    def health(self):
        pressure = subprocess.run(["memory_pressure"], capture_output=True, text=True, timeout=10)
        match = re.search(r"System-wide memory free percentage:\s*(\d+)%", pressure.stdout)
        free_percent = int(match.group(1)) if match else None
        free_disk = shutil.disk_usage(self.folder).free
        return {"memory_free_percent": free_percent, "disk_free_bytes": free_disk}


def probe(local, path):
    return local.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path], json_output=True)


def verify_media(local, path, kind, duration=0, final=False):
    info = probe(local, path)
    picture = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    if not picture or picture["width"] < 720 or picture["height"] < 1280:
        raise Pause("Media resolution/type failed")
    is_image = picture["codec_name"] in ("mjpeg", "png", "webp") and info["format"]["format_name"] in ("image2", "jpeg_pipe", "png_pipe", "webp_pipe")
    if (kind == "image") != is_image:
        raise Pause("Image/video type mismatch")
    if kind == "video" and float(info["format"].get("duration", 0)) + .04 < duration:
        raise Pause("Generated clip cannot cover its assigned duration")
    if final:
        if (picture["width"], picture["height"], picture["avg_frame_rate"], int(picture.get("nb_frames", 0))) != (1080, 1920, "30/1", 5091):
            raise Pause("Final video dimensions, frame rate or frame count failed")
        if abs(float(info["format"]["duration"]) - 169.7) > .05 or not any(s["codec_type"] == "audio" for s in info["streams"]):
            raise Pause("Final audio/duration failed")
    local.run(["ffmpeg", "-v", "error", "-i", path, "-f", "null", "-"], timeout=240)
    return {"sha256": digest(path), "bytes": Path(path).stat().st_size, "probe": info}


class Drive:
    def __init__(self, local, folder_id):
        self.local, self.folder_id = local, folder_id

    def info(self, file_id):
        raw = self.local.run(["gdrive", "files", "info", "--size-in-bytes", file_id])
        return dict(line.split(": ", 1) for line in raw.splitlines() if ": " in line)

    def matches(self, remote, path):
        return (remote.get("Name") == path.name and remote.get("Mime") == "video/mp4"
                and self.folder_id in remote.get("Parents", "").split(", ")
                and remote.get("Size") == str(path.stat().st_size) and remote.get("MD5") == digest(path, "md5"))

    def upload(self, path, receipt):
        path, receipt = Path(path), Path(receipt)
        doc = read(receipt) if receipt.exists() else {"state": "prepared", "name": path.name,
                "sha256": digest(path), "md5": digest(path, "md5"), "bytes": path.stat().st_size,
                "folder_id": self.folder_id}
        if doc["sha256"] != digest(path):
            raise Pause("Final changed since delivery began; create an intentional new version")
        if doc.get("drive_file_id"):
            if not self.matches(self.info(doc["drive_file_id"]), path):
                raise Pause("Drive file verification failed")
        else:
            quoted_name = path.name.replace("\\", "\\\\").replace("'", "\\'")
            query = f"'{self.folder_id}' in parents and trashed = false and name = '{quoted_name}'"
            rows = self.local.run(["gdrive", "files", "list", "--query", query, "--max", "100", "--skip-header", "--full-name"]).splitlines()
            candidates = [row.split()[0] for row in rows if row.strip()]
            verified = [fid for fid in candidates if self.matches(self.info(fid), path)]
            if len(verified) == 1:
                doc["drive_file_id"] = verified[0]
            elif candidates:
                raise Pause("Conflicting or duplicate Drive delivery; reconcile without reuploading")
            elif doc["state"] == "uploading":
                raise Pause("Upload response was ambiguous; wait and recover by filename, do not upload twice")
            else:
                doc.update(state="uploading", started_at=now())
                write(receipt, doc)
                fid = self.local.run(["gdrive", "files", "upload", "--parent", self.folder_id, "--print-only-id", path], timeout=600).strip()
                if not re.fullmatch(r"[A-Za-z0-9_-]+", fid):
                    raise Pause("Upload response ambiguous; recover existing Drive file")
                doc["drive_file_id"] = fid
                write(receipt, doc)
                if not self.matches(self.info(fid), path):
                    raise Pause("Uploaded file failed Drive checksum, size, parent or name verification")
        doc.update(state="verified", verified_at=now(), web_url=f"https://drive.google.com/file/d/{doc['drive_file_id']}/view")
        write(receipt, doc)
        return doc
