"""Durable state and conservative reservations, independent of provider credentials."""
import contextlib
import fcntl
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class Pause(RuntimeError):
    """An actionable checkpoint; retrying the controller never means retrying a charge."""


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(doc, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextlib.contextmanager
def exclusive(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "controller.lock").open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Pause("Another batch controller holds the lock") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


class Batch:
    def __init__(self, selection_dir):
        self.root = Path(selection_dir).resolve()
        self.folder = self.root / "batch-plan"
        self.path = self.folder / "run-state.json"
        self.selection = read(self.root / "next-15-video-plan.json")
        self.plan = read(self.folder / "batch-queue.json")
        if digest(self.root / "next-15-video-plan.json") != self.plan["selection_sha256"]:
            raise Pause("Product selection changed; reconcile it before continuing")
        self.data = read(self.path) if self.path.exists() else {
            "version": 1, "batch_id": self.plan["batch_id"], "status": "ready",
            "approval": {"basis": "User accepted the saved batch plan: implement",
                         "jimeng": self.plan["jimeng_batch_credit_ceiling"],
                         "tts": self.plan["proposed_tts_batch_credit_ceiling"],
                         "tts_per_video": self.plan["proposed_tts_credits_per_video"],
                         "other_api_usd": 0, "recorded_at": now()},
            "balance": None, "videos": {}, "events": [],
        }

    def save(self):
        write(self.path, self.data)

    def video(self, number):
        key = str(number)
        if key not in self.data["videos"]:
            self.data["videos"][key] = {
                "number": number, "state": "queued", "jobs": {}, "imports": {},
                "tts_jobs": {}, "spent_hold": 0, "reservation": 0,
            }
            self.save()
        return self.data["videos"][key]

    def directory(self, number):
        path = self.root / "productions" / f"haul-{number:02}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def selected(self, number):
        return next(v for v in self.selection["videos"] if v["video_number"] == number)

    def active_number(self):
        for n in range(1, len(self.plan["items"]) + 1):
            v = self.data["videos"].get(str(n), {})
            if v.get("state") != "done":
                return n
        return None

    def record_balance(self, amount, evidence):
        if type(amount) is not int or amount < 0 or not evidence.strip():
            raise Pause("A nonnegative observed balance and evidence are required")
        self.data["balance"] = {"amount": amount, "at": now(), "evidence": evidence,
                                "held_at_observation": self.spent()}
        self.save()

    def spent(self):
        return sum(v["spent_hold"] for v in self.data["videos"].values())

    def reserve_video(self, number, quotes):
        if number != self.active_number():
            raise Pause("Finish delivery and cleanup of the active video first")
        v = self.video(number)
        if not quotes or any(type(q) is not int or q < 0 for q in quotes.values()):
            raise Pause("Every generation requires a complete verified quote")
        if set(quotes) != set(v["jobs"]):
            raise Pause("Quote coverage does not match every planned job")
        balance = self.data["balance"]
        if not balance or (datetime.now(timezone.utc) - datetime.fromisoformat(balance["at"])).total_seconds() > 1800:
            raise Pause("Refresh the logged-in Jimeng balance before reserving a video")
        base = sum(quotes.values())
        reserve = base + self.plan["repair_allowance_credits_per_video"]
        other = sum(x["reservation"] for k, x in self.data["videos"].items() if k != str(number))
        live_remaining = balance["amount"] - (self.spent() - balance["held_at_observation"])
        if reserve + other > self.data["approval"]["jimeng"] or reserve - v["spent_hold"] > live_remaining:
            raise Pause("Insufficient credits for the next COMPLETE video and repair allowance")
        v.update(reservation=reserve, base_quotes=quotes, base_credits=base, state="reserved")
        self.save()

    def claim_visual(self, number, key, amount):
        v = self.video(number)
        j = v["jobs"][key]
        if j.get("authorized_credits") is not None:
            raise Pause("Submission already claimed; recover its saved ID without resubmitting")
        if not v["reservation"] or type(amount) is not int or amount < 0:
            raise Pause("A complete video reservation is required")
        if any(x.get("stage") in ("submitting", "submitted", "accepted", "pending", "unknown", "running")
               for x in v["jobs"].values()):
            raise Pause("Recover the active Jimeng operation before another submission")
        if v["spent_hold"] + amount > v["reservation"] or self.spent() + amount > self.data["approval"]["jimeng"]:
            raise Pause("Jimeng reservation exhausted")
        if amount > j["quoted_credits"]:
            raise Pause("Quote increased; re-quote the complete remaining video")
        j.update(stage="submitting", authorized_credits=amount, submitted_at=now())
        v["spent_hold"] += amount
        self.save()  # durable BEFORE the paid request

    def claim_tts(self, number, key, text):
        v = self.video(number)
        if key in v["tts_jobs"]:
            raise Pause("TTS request already reserved; inspect its receipt, never repeat automatically")
        count = len(text)
        total = sum(j["reserved_credits"] for x in self.data["videos"].values() for j in x["tts_jobs"].values())
        per_video = sum(j["reserved_credits"] for j in v["tts_jobs"].values())
        if total + count > self.data["approval"]["tts"] or per_video + count > self.data["approval"]["tts_per_video"]:
            raise Pause("Narration credit ceiling exceeded")
        v["tts_jobs"][key] = {"state": "requesting", "reserved_credits": count,
                                "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "at": now()}
        self.save()

    def complete(self, number):
        v = self.video(number)
        required = (v.get("qc", {}).get("status") == "passed",
                    v.get("delivery", {}).get("state") == "verified",
                    v.get("cleanup", {}).get("state") == "verified")
        if not all(required):
            raise Pause("Completion requires QC, verified Drive delivery AND verified cleanup")
        v.update(state="done", completed_at=now(), reservation=v["spent_hold"])
        self.data["balance"] = None  # fresh browser observation between videos
        self.save()
