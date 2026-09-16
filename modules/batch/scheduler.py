"""One state writer, several remote jobs, and immediate creative-review handoffs."""
import time

from modules.assets.canvas_cli import CanvasError
from .state import Pause, ReviewReady, now, write

ACTIVE = {"submitting", "submitted", "accepted", "pending", "running", "unknown"}


class Scheduler:
    def __init__(self, runner, brief):
        self.runner, self.brief = runner, brief
        self.batch, self.v, self.folder = runner.batch, runner.v, runner.folder
        self.canvas = runner.canvas

    def selected(self, key):
        return self.v.get("selected_jobs", {}).get(key, key)

    def keys(self):
        return [self.selected(f"look-{p['slot']:02}") for p in self.brief["products"]] + [
            self.selected(t["id"]) for t in self.brief["takes"]]

    def pending_reviews(self):
        return [key for key in self.keys() if self.v["jobs"][key]["stage"] == "downloaded"
                and not self.runner.reviewed(key)]

    def progress(self):
        jobs = self.v["jobs"]
        pending = self.pending_reviews()
        doc = {"at": now(), "video": self.runner.number, "concurrency": self.batch.concurrency(),
               "in_flight": [k for k, j in jobs.items() if j["stage"] in ACTIVE],
               "downloaded": [k for k in self.keys() if jobs[k]["stage"] == "downloaded"],
               "review_ready": pending,
               "next_action": "Inspect ready artifacts now, record reviews, and rerun immediately" if pending
                              else "Observe existing operations; do not resubmit"}
        self.v["review_queue"] = pending
        self.v["review_required"] = pending[0] if pending else None
        write(self.folder / "progress.json", doc)
        self.batch.save()
        return doc

    def ready(self):
        # Fill available capacity with clips whose exact outfit has passed review.
        for take in self.brief["takes"]:
            key = self.selected(take["id"])
            look = self.selected(f"look-{take['slot']:02}")
            if self.v["jobs"][key]["stage"] == "saved" and self.runner.reviewed(look):
                yield key, take, look
        for product in self.brief["products"]:
            key = self.selected(f"look-{product['slot']:02}")
            if self.v["jobs"][key]["stage"] == "saved":
                yield key, None, None

    def cycle(self):
        errors = []
        # A slow first job must not hide completed later jobs.
        for key, job in self.v["jobs"].items():
            if job["stage"] in ACTIVE:
                try:
                    self.canvas.poll(key)
                except (Pause, CanvasError) as error:
                    errors.append(error)
        for key in self.keys():
            job = self.v["jobs"][key]
            if job["stage"] == "succeeded":
                try:
                    self.canvas.download(key)
                except (Pause, CanvasError) as error:
                    errors.append(error)
            if job["stage"] in ("failed", "cancelled", "rejected"):
                errors.append(Pause(f"{key} has a terminal failure; inspect before any correction"))
            if job["stage"] == "downloaded" and self.v.get("reviews", {}).get(key, {}).get("status") == "failed":
                errors.append(Pause(f"{key} failed review; use its explicit repair workflow"))
        if errors:
            self.progress()
            raise errors[0]
        for key, take, look in self.ready():
            active = sum(j["stage"] in ACTIVE for j in self.v["jobs"].values())
            if active >= self.batch.concurrency() or len(self.pending_reviews()) >= max(6, 2 * self.batch.concurrency()):
                break
            if take:
                self.canvas.bind_outfit(key, self.v["jobs"][look]["node_id"])
                voice = self.canvas.import_file("voice-" + take["id"], "audio", self.folder / "audio" / (take["id"] + ".wav"))
                self.canvas.attach_audio(key, voice, take["text"])
            self.canvas.submit(key)  # Persist each reservation before dispatch; never race state writes.
        doc = self.progress()
        if doc["review_ready"]:
            raise ReviewReady("Review ready: " + ", ".join(doc["review_ready"]) +
                              ". Continue this agent turn; other accepted jobs keep running.")
        if all(self.runner.reviewed(key) for key in self.keys()):
            return True
        if not doc["in_flight"]:
            raise Pause("No runnable jobs; inspect missing dependencies or unfinished drafts")
        print(f"Jimeng: {len(doc['in_flight'])} in flight; {len(doc['downloaded'])} downloaded", flush=True)
        return False

    def finish(self):
        while not self.cycle():
            time.sleep(5)
