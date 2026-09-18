"""Mandatory deep reference analysis (Hypit-directed).

A ReferenceAnalysis is the work product the factory requires before a
source blueprint can be accepted for production. It is durable,
revisioned, resumable and bound to the exact source bytes:

- machine stages (worker command `analysis_evidence`) produce
  verifiable evidence: verified acquisition facts, transcript
  (WhisperX alignment when an endpoint is configured; YouTube captions
  attach as preliminary only; no audio → not_applicable), timed
  boundaries + transcript-linked grids, and the Hypit project
  documents (ANALYSIS/TIMELINE/BRIEF/TREATMENT/PROGRESS).
- operator stages supply the semantic reading: understanding,
  timed sections and the treatment — saved through the API, never
  hand-edited JSON.
- a human review completes it; any later edit opens a new revision
  that must be reviewed again.

analysis_gate() is the shared enforcement: BlueprintReview.accept
and every downstream production path must see status 'complete'
bound to the same source_sha256 and revision.
"""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from ..domain.errors import ContractError
from ..domain.records import ReferenceAnalysis
from ..media.probe import probe
from ..media.audio import audio_characteristics
from ..store.uow import utcnow

MACHINE_STAGES = ("acquire", "transcript", "evidence", "documents")
UNDERSTANDING_FIELDS = ("premise", "progression", "hook", "setups",
                        "payoffs", "ending", "replay_appeal",
                        "intended_response")
TREATMENT_FIELDS = ("summary", "preserves", "redesigns",
                    "script_direction")
TRANSCRIPT_OK = {"aligned", "not_applicable", "declared_nonverbal"}


def analysis_id_for(seed_id):
    return f"ra-{seed_id}"


def load_analysis(row):
    return ReferenceAnalysis(**json.loads(row["body"]))


def _hash(a):
    d = a.to_dict()
    for k in ("created_at", "revision", "content_hash", "status",
              "stage", "blocking"):
        d.pop(k, None)
    return hashlib.sha256(json.dumps(
        d, sort_keys=True, default=str).encode()).hexdigest()


def completeness_missing(a):
    """Substantive completeness — the review gate and the production
    gate both run this, so a populated status flag alone can never
    pass. Returns the list of missing pieces ([] = complete)."""
    missing = []
    for stage in MACHINE_STAGES:
        if not a.stages.get(stage, {}).get("done"):
            missing.append(f"stage:{stage}")
    if a.transcript.get("status") not in TRANSCRIPT_OK:
        missing.append("transcript")
    if not a.evidence.get("grids"):
        missing.append("grids")
    dur = a.acquisition.get("duration_s") or 0
    if dur and (a.evidence.get("coverage_s") or 0) < dur - 0.5:
        missing.append("coverage")
    for f in UNDERSTANDING_FIELDS:
        if not a.understanding.get(f):
            missing.append(f"understanding.{f}")
    if not a.understanding.get("observations") or \
            not a.understanding.get("interpretations"):
        missing.append("understanding.observed_vs_interpretation")
    if not a.timeline:
        missing.append("timeline")
    for f in TREATMENT_FIELDS:
        if not a.treatment.get(f):
            missing.append(f"treatment.{f}")
    return missing


def analysis_gate(db, seed_id, source_sha256):
    """Shared production gate. Returns the complete ReferenceAnalysis
    bound to these exact source bytes, or raises a typed ContractError
    that names the recovery path."""
    row = db.uow().records.get("referenceanalysis",
                               analysis_id_for(seed_id))
    if row is None:
        raise ContractError(
            "analysis_required", "seed_id",
            "Run Hypit-directed analysis before accepting a blueprint "
            "or starting production")
    a = load_analysis(row)
    if a.source_sha256 != source_sha256:
        raise ContractError(
            "analysis_stale", "source_sha256",
            "source media changed since analysis — reanalyze")
    if a.status == "blocked":
        raise ContractError(
            "analysis_blocked", "blocking",
            json.dumps(a.blocking or [{"code": "blocked"}]))
    if a.status != "complete":
        raise ContractError(
            "analysis_incomplete", "status",
            f"analysis status {a.status}; complete machine stages, "
            "understanding, treatment and review first")
    missing = completeness_missing(a)
    if missing:
        raise ContractError(
            "analysis_incomplete", "missing",
            ",".join(missing))
    return a


def bound_gate(db, seed_id, source_sha256, binding):
    """Downstream gate for an accepted blueprint: the stamped binding
    must still resolve to a complete analysis at the same revision
    and source bytes. Old acceptances (no binding) fail closed."""
    if not binding or not binding.get("id") or \
            binding.get("revision") is None:
        raise ContractError(
            "analysis_required", "blueprint",
            "acceptance predates mandatory analysis — reanalyze and "
            "re-accept the blueprint")
    a = analysis_gate(db, seed_id, source_sha256)
    if a.id != binding["id"] or a.revision != binding["revision"]:
        raise ContractError(
            "analysis_stale", "revision",
            f"analysis revised to r{a.revision} after acceptance bound "
            f"r{binding['revision']} — re-accept the blueprint")
    return a


class HypitTransport:
    """The pinned project Hypit executable behind a small runner
    seam (tests inject scripted output; production uses subprocess)."""

    def __init__(self, executable, runner=None):
        self.executable = str(executable)
        self.runner = runner or (
            lambda argv, timeout=600: subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout))

    def available(self):
        return Path(self.executable).exists()

    def _call(self, args, timeout=600):
        return self.runner([self.executable, *args], timeout=timeout)

    def _json(self, args, timeout=600):
        r = self._call(args, timeout=timeout)
        if getattr(r, "returncode", 1) != 0:
            return None
        try:
            return json.loads(r.stdout)
        except (json.JSONDecodeError, TypeError):
            return None

    def paths(self):
        return self._json(["paths", "--json"], timeout=60) or {}

    def transcribe_available(self):
        """A WhisperX endpoint exists only when a Runtime Profile is
        selected and declares one. No profile → definitely absent."""
        paths = self.paths()
        if not paths or paths.get("profileSource") in (None, "none"):
            return False
        # `runtime status` reports worker/program counts, never endpoint
        # names — `programs status` enumerates the profile's declared
        # endpoint instances (including ones not yet warmed up)
        status = self._json(["programs", "status", "--json"], timeout=60)
        programs = (status or {}).get("programs") or []
        return any("whisperx" in str(p.get("endpoint")
                   or p.get("id") or "").lower() for p in programs)

    def probe(self, src):
        return self._json(["media", "probe", str(src), "--json"],
                          timeout=120) or {}

    def transcribe(self, src, language, dest):
        return self._call(["transcribe", str(src), "--language", language,
                           "--to", str(dest)], timeout=1800)

    def boundaries(self, src):
        return self._json(["media", "boundaries", str(src), "--json"],
                          timeout=900) or {}

    def tiles(self, src, dest_dir, every, transcript=None,
              start=None, end=None, columns=4, rows=3):
        args = ["media", "tiles", str(src), "--every", str(every),
                "--columns", str(columns), "--rows", str(rows),
                "--to", str(dest_dir), "--json"]
        if start is not None:
            args += ["--start", str(start), "--end", str(end)]
        if transcript:
            args += ["--transcript", str(transcript)]
        return self._call(args, timeout=1800)


class ReferenceAnalysisService:
    MACHINE_STAGES = MACHINE_STAGES

    def __init__(self, db, registry, artifacts, project_root,
                 transport, language="en"):
        self.db = db
        self.registry = registry
        self.artifacts = artifacts
        self.project_root = Path(project_root)
        self.hypit = transport
        self.language = language

    # -------------------------------------------------- lifecycle

    def start(self, seed_id, reviewer=""):
        """Create or resume the analysis for a seed. A changed source
        supersedes the old record and opens a new revision — history
        is preserved, never rewritten."""
        if not reviewer.strip():
            raise ContractError("reviewer_required", "reviewer")
        seed = self.registry.get(seed_id)
        if seed.evidence_status != "media_ready" or \
                not seed.source_asset_id:
            raise ContractError("source_not_ready", "seed_id")
        art = self.db.uow().artifacts.get(seed.source_asset_id)
        sha = art["sha256"]
        row = self.db.uow().records.get("referenceanalysis",
                                       analysis_id_for(seed_id))
        if row:
            a = load_analysis(row)
            if a.source_sha256 == sha:
                return a                       # resume, idempotent
            self._supersede(a, f"source changed to {sha[:12]}")
        now = utcnow()
        a = ReferenceAnalysis(
            schema_version="referenceanalysis.v1",
            id=analysis_id_for(seed_id), created_at=now, seed_id=seed_id,
            revision=(row["revision"] + 1) if row else 1,
            status="in_progress", source_asset_id=seed.source_asset_id,
            source_sha256=sha,
            capabilities=self._capabilities())
        a.content_hash = _hash(a)
        a.validate_or_raise()
        with self.db.uow() as u:
            u.records.put(a)
            u.events.append(f"analysis:{a.id}", "started",
                            {"revision": a.revision, "reviewer": reviewer,
                             "source": sha[:12]})
        return a

    def get(self, seed_id, revision=None):
        row = self.db.uow().records.get("referenceanalysis",
                                       analysis_id_for(seed_id),
                                       revision=revision)
        if row is None:
            raise ContractError("unknown_analysis", "seed_id", seed_id)
        return load_analysis(row)

    # --------------------------------------------- machine stages

    def run_machine_stages(self, seed_id):
        """Durable stage runner — each stage checkpoints into the
        record, so an interrupted run resumes after the last completed
        stage and never repeats finished (potentially paid) work."""
        a = self.get(seed_id)
        if a.status in ("complete", "awaiting_review"):
            return a
        if a.status == "blocked":
            # retrying — a stage that fails again re-blocks with a
            # fresh reason; a stage that succeeds clears it
            a.status = "in_progress"
            a.blocking = []
        for stage in MACHINE_STAGES:
            if a.stages.get(stage, {}).get("done"):
                continue
            # documents describe finished work — they wait for every
            # earlier stage; evidence still runs under a transcript
            # block so the operator has frames to judge the recovery
            if stage == "documents" and any(
                    not a.stages.get(s, {}).get("done")
                    for s in ("acquire", "transcript", "evidence")):
                continue
            a = getattr(self, f"_stage_{stage}")(a)
        if a.status != "blocked":
            a.blocking = []        # no live blocker after a clean run
            a = self._save(a, status="evidence_ready",
                           stage="documents")
        return a

    def _stage_acquire(self, a):
        src = self.artifacts.verified_path(a.source_asset_id)
        info = probe(src)
        audio = audio_characteristics(src)
        v = info.video
        fps = v.avg_frame_rate or v.r_frame_rate
        seed = self.registry.get(a.seed_id)
        a.acquisition = {
            "url": seed.canonical_url, "artifact_id": a.source_asset_id,
            "sha256": a.source_sha256, "duration_s": info.duration_s,
            "width": v.width, "height": v.height,
            "fps": f"{fps.numerator}/{fps.denominator}" if fps else "",
            "audio_present": audio["present"], "via": "hypit media fetch",
            "verified_at": utcnow()}
        a.stages["acquire"] = {"done": True, "at": utcnow()}
        return self._save(a, stage="acquire")

    def _stage_transcript(self, a):
        project = self._project(a)
        dest = project / "references" / a.seed_id / "transcript.json"
        if not a.acquisition.get("audio_present"):
            a.transcript = {"status": "not_applicable",
                            "provider": "none", "word_count": 0,
                            "provenance": "no audio stream",
                            "preliminary": False}
            a.stages["transcript"] = {"done": True, "at": utcnow()}
            return self._save(a, stage="transcript")
        caps = self._capabilities()
        a.capabilities = caps
        if caps.get("whisperx") and self.hypit.available():
            dest.parent.mkdir(parents=True, exist_ok=True)
            r = self.hypit.transcribe(src=self.artifacts.verified_path(
                a.source_asset_id), language=self.language, dest=dest)
            if getattr(r, "returncode", 1) == 0 and dest.exists():
                words = self._transcript_words(dest)
                a.transcript = {
                    "status": "aligned", "provider": "whisperx",
                    "confidence": "word-level",
                    "provenance": f"hypit transcribe ({self.language})",
                    "word_count": len(words), "file": str(dest),
                    "preliminary": False}
                a.stages["transcript"] = {"done": True, "at": utcnow()}
                return self._save(a, stage="transcript")
            a.blocking = [{"code": "transcript_failed",
                           "detail": _cli_error(r)[:300]
                                     or "hypit transcribe failed",
                           "recovery": ["retry analysis evidence stage",
                                        "import an aligned transcript",
                                        "declare non-verbal or music-only"]}]
            return self._save(a, status="blocked", stage="transcript")
        preliminary = (self.registry.get(a.seed_id).metadata or {}) \
            .get("captions")
        a.transcript = {
            "status": "unavailable", "provider": "",
            "word_count": 0, "preliminary": True,
            "provenance": "no whisperx endpoint configured",
            "captions_preview": preliminary or ""}
        a.blocking = [{"code": "transcript_unavailable",
                       "detail": "speech needs word-level alignment; "
                                 "YouTube captions are preliminary "
                                 "evidence only, not proof of timing",
                       "recovery": ["configure a WhisperX endpoint "
                                    "(local prep or hosted), then "
                                    "re-run the evidence stage",
                                    "import an aligned transcript "
                                    "with declared provenance",
                                    "declare non-verbal or music-only "
                                    "with supporting evidence"]}]
        return self._save(a, status="blocked", stage="transcript")

    def _stage_evidence(self, a):
        if not self.hypit.available():
            a.blocking = [{"code": "hypit_missing",
                           "detail": "pinned hypit executable not found",
                           "recovery": ["restore vendor/hypit-runtime "
                                        "per docs, then retry"]}]
            return self._save(a, status="blocked", stage="evidence")
        src = self.artifacts.verified_path(a.source_asset_id)
        dur = a.acquisition.get("duration_s") or probe(src).duration_s
        project = self._project(a)
        ev_dir = project / "references" / a.seed_id / "evidence"
        ev_dir.mkdir(parents=True, exist_ok=True)
        transcript = a.transcript.get("file") \
            if a.transcript.get("status") == "aligned" else None
        bounds = self.hypit.boundaries(src)
        cuts = self._parse_boundaries(bounds)
        grids, coverage = [], 0.0
        every = max(1.0, round(dur / 24, 1))
        specs = [("overview", None, None, every)]
        for i, c in enumerate(cuts[:6]):
            specs.append((f"cut-{i:02d}", max(0.0, c["t"] - 1.0),
                          min(dur, c["t"] + 1.0), 0.25))
        for name, start, end, step in specs:
            out = ev_dir / name
            if out.exists():
                shutil.rmtree(out)   # hypit refuses to write into an
                                     # existing destination
            args = {"transcript": transcript}
            if start is not None:
                args.update(start=start, end=end)
            r = self.hypit.tiles(src, out, step, **args)
            if getattr(r, "returncode", 1) != 0:
                a.blocking = [{"code": "evidence_failed",
                               "detail": _cli_error(r) or "tiles failed",
                               "recovery": ["retry analysis evidence "
                                            "stage"]}]
                return self._save(a, status="blocked", stage="evidence")
            files = sorted(out.glob("*.jpg")) + sorted(out.glob("*.png"))
            if not files:
                a.blocking = [{"code": "evidence_empty",
                               "detail": f"tiles produced nothing for {name}",
                               "recovery": ["retry analysis evidence "
                                            "stage"]}]
                return self._save(a, status="blocked", stage="evidence")
            for f in files:
                art = self.artifacts.intake_bytes(
                    f.read_bytes(), provenance="derived:analysis",
                    source_key=f"{a.source_sha256}@{name}:{f.stem}",
                    source_detail=f"seed:{a.seed_id} {name} grid",
                    requested_kind="image")
                grids.append({"artifact_id": art.id,
                              "start_s": round(start or 0.0, 3),
                              "end_s": round(end if end is not None
                                             else dur, 3),
                              "every_s": step,
                              "transcript_linked": bool(transcript)})
                f.unlink(missing_ok=True)
            coverage = max(coverage, end if end is not None else dur)
        a.evidence = {"boundaries": cuts, "grids": grids,
                      "coverage_s": round(coverage, 3)}
        a.stages["evidence"] = {"done": True, "at": utcnow(),
                                "grids": len(grids)}
        return self._save(a, stage="evidence")

    def _stage_documents(self, a):
        project = self._project(a)
        ref = project / "references" / a.seed_id
        prod = project / "productions" / a.seed_id
        (ref / "evidence").mkdir(parents=True, exist_ok=True)
        prod.mkdir(parents=True, exist_ok=True)
        files = {
            "analysis_md": ref / "ANALYSIS.md",
            "timeline_md": ref / "TIMELINE.md",
            "brief_md": prod / "BRIEF.md",
            "treatment_md": prod / "TREATMENT.md",
            "progress_md": prod / "PROGRESS.md",
            "transcript_json": ref / "transcript.json",
            "manifest": ref / "evidence" / "manifest.json"}
        self._write_docs(a, files)
        a.documents = {
            "root": str(project),
            "files": {k: str(v) for k, v in files.items()
                      if v.exists()},
            "hashes": {k: hashlib.sha256(v.read_bytes()).hexdigest()
                       for k, v in files.items() if v.exists()}}
        a.stages["documents"] = {"done": True, "at": utcnow()}
        return self._save(a, stage="documents")

    # ---------------------------------------------- operator API

    def save_understanding(self, seed_id, fields, reviewer):
        a = self._editable(seed_id, reviewer)
        missing = [f for f in UNDERSTANDING_FIELDS
                   if not str(fields.get(f, "")).strip()]
        if missing:
            raise ContractError("understanding_incomplete", "fields",
                                ",".join(missing))
        observations = fields.get("observations") or []
        interpretations = fields.get("interpretations") or []
        if not observations or not interpretations:
            raise ContractError(
                "observed_vs_interpretation_required", "fields",
                "separate observed facts from interpretation")
        a.understanding = {f: str(fields[f]).strip()
                           for f in UNDERSTANDING_FIELDS}
        a.understanding["observations"] = observations
        a.understanding["interpretations"] = interpretations
        a.understanding["uncertainties"] = fields.get(
            "uncertainties") or []
        return self._after_edit(a, "understanding")

    def save_timeline(self, seed_id, sections, reviewer):
        a = self._editable(seed_id, reviewer)
        if not isinstance(sections, list) or not sections:
            raise ContractError("timeline_required", "sections")
        dur = a.acquisition.get("duration_s") or 0
        clean = []
        for s in sections:
            start, end = float(s.get("start_s", -1)), float(s.get("end_s", -1))
            if not (0 <= start < end <= dur + 0.05) or \
                    not str(s.get("phase", "")).strip() or \
                    not str(s.get("summary", "")).strip():
                raise ContractError(
                    "timeline_section_invalid", "sections",
                    "each section needs 0<=start<end<=duration, "
                    "a phase name and a summary")
            clean.append({"start_s": start, "end_s": end,
                          "phase": str(s["phase"]).strip(),
                          "summary": str(s["summary"]).strip(),
                          "evidence_ids": list(s.get("evidence_ids") or [])})
        covered = all(any(s["start_s"] <= t < s["end_s"] for s in clean)
                      for t in (0, dur / 2, max(0.0, dur - 0.01))) \
            if dur else bool(clean)
        if not covered:
            raise ContractError("timeline_coverage_required", "sections",
                                "sections must span the whole reference")
        a.timeline = sorted(clean, key=lambda s: s["start_s"])
        return self._after_edit(a, "timeline")

    def save_treatment(self, seed_id, fields, reviewer):
        a = self._editable(seed_id, reviewer)
        missing = [f for f in TREATMENT_FIELDS
                   if not str(fields.get(f, "")).strip()]
        if missing:
            raise ContractError("treatment_incomplete", "fields",
                                ",".join(missing))
        a.treatment = {f: str(fields[f]).strip() for f in TREATMENT_FIELDS}
        a.treatment["prompt_notes"] = str(
            fields.get("prompt_notes") or "").strip()
        return self._after_edit(a, "treatment")

    def import_transcript(self, seed_id, payload, reviewer):
        """Operator-supplied aligned transcript — the alternate route
        when no WhisperX endpoint exists. Provenance is mandatory and
        word times must be monotonic inside the source duration."""
        a = self._editable(seed_id, reviewer)
        words = payload.get("words")
        provider = str(payload.get("provider") or "").strip()
        provenance = str(payload.get("provenance") or "").strip()
        if not provider or not provenance:
            raise ContractError("transcript_provenance_required",
                                "provider/provenance")
        if not isinstance(words, list):
            raise ContractError("transcript_words_required", "words")
        dur = a.acquisition.get("duration_s") or 0
        last = 0.0
        for w in words:
            s, e = float(w.get("start_s", -1)), float(w.get("end_s", -1))
            if not (0 <= s <= e <= dur + 0.05) or s < last - 0.001 \
                    or not str(w.get("word", "")).strip():
                raise ContractError("transcript_words_invalid", "words",
                                    "word times must be monotonic and "
                                    "inside the source duration")
            last = e
        project = self._project(a)
        dest = project / "references" / a.seed_id / "transcript.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(
            _hypit_transcript(words, source=self.artifacts.verified_path(
                a.source_asset_id), language=payload.get(
                "language", self.language), audio_seconds=dur,
                provider=provider), indent=1))
        a.transcript = {"status": "aligned", "provider": provider,
                        "confidence": payload.get("confidence",
                                                  "imported"),
                        "provenance": provenance,
                        "word_count": len(words), "file": str(dest),
                        "preliminary": False}
        a.blocking = [b for b in a.blocking
                      if b.get("code") not in ("transcript_unavailable",
                                          "transcript_failed")]
        a.stages["transcript"] = {"done": True, "at": utcnow()}
        # regenerate grids — they can now be transcript-linked
        a.stages.pop("evidence", None)
        a.stages.pop("documents", None)
        self._write_docs(a, self._doc_paths(a))
        return self._save(a, status="in_progress"
                        if a.status == "blocked" else a.status,
                        stage="transcript")

    def declare(self, seed_id, status, note, reviewer):
        """Declare non-verbal / music-only / silent sources. Evidence
        for the declaration is required — never an invented transcript."""
        a = self._editable(seed_id, reviewer)
        if status not in ("declared_nonverbal",):
            raise ContractError("unsupported_declaration", "status")
        if not str(note or "").strip():
            raise ContractError("declaration_evidence_required", "note")
        a.transcript = {"status": status, "provider": "operator",
                        "confidence": "declared", "provenance": note.strip(),
                        "word_count": 0, "preliminary": False}
        a.blocking = [b for b in a.blocking
                      if b.get("code") not in ("transcript_unavailable",
                                          "transcript_failed")]
        a.stages["transcript"] = {"done": True, "at": utcnow()}
        self._write_docs(a, self._doc_paths(a))
        return self._save(a, status="in_progress"
                        if a.status == "blocked" else a.status,
                        stage="transcript")

    def invalidate_evidence(self, seed_id):
        """Force the evidence/documents stages to rebuild on the next
        machine run (e.g. after a hypit/parser upgrade). Local compute
        only — transcripts and operator content are untouched."""
        a = self.get(seed_id)
        if a.status == "complete":
            raise ContractError("analysis_locked", "status",
                                "edit opens a new revision instead")
        a.stages.pop("evidence", None)
        a.stages.pop("documents", None)
        a.evidence = {}
        return self._save(a, status="in_progress"
                        if a.status != "blocked" else a.status,
                        stage="evidence")

    def review(self, seed_id, reviewer, verdict, notes=""):
        if not reviewer.strip():
            raise ContractError("reviewer_required", "reviewer")
        a = self.get(seed_id)
        problems = self._completeness(a)
        if problems:
            raise ContractError("analysis_not_reviewable", "missing",
                                ",".join(problems))
        if verdict != "accept":
            raise ContractError("unsupported_verdict", "verdict")
        a.review = {"reviewer": reviewer, "at": utcnow(),
                    "verdict": "accept", "notes": notes}
        a = self._save(a, status="complete", stage="review")
        self._write_docs(a, self._doc_paths(a))
        return a

    # --------------------------------------------------- internals

    def _capabilities(self):
        return {"hypit": self.hypit.available(),
                "whisperx": self.hypit.transcribe_available()
                if self.hypit.available() else False,
                "transcript_import": True}

    def _project(self, a):
        return self.project_root / a.seed_id

    def _doc_paths(self, a):
        project = self._project(a)
        ref = project / "references" / a.seed_id
        prod = project / "productions" / a.seed_id
        return {"analysis_md": ref / "ANALYSIS.md",
                "timeline_md": ref / "TIMELINE.md",
                "brief_md": prod / "BRIEF.md",
                "treatment_md": prod / "TREATMENT.md",
                "progress_md": prod / "PROGRESS.md",
                "transcript_json": ref / "transcript.json",
                "manifest": ref / "evidence" / "manifest.json"}

    def _editable(self, seed_id, reviewer):
        if not str(reviewer or "").strip():
            raise ContractError("reviewer_required", "reviewer")
        a = self.get(seed_id)
        if a.status == "complete":
            # post-approval content change → new revision requiring
            # a fresh review; edits before approval stay in-revision
            a = self._new_revision(a, f"edit by {reviewer}")
        return a

    def _new_revision(self, a, reason):
        prior = self.db.uow().records.get(
            "referenceanalysis", a.id, revision=a.revision)
        body = json.loads(prior["body"])
        body["status"] = "superseded"
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=? WHERE kind='referenceanalysis'"
                " AND id=? AND revision=?",
                (json.dumps(body), a.id, a.revision))
        a.revision += 1
        a.status = "evidence_ready"
        a.review = {}
        a.created_at = utcnow()
        return a

    def _supersede(self, a, reason):
        with self.db.uow() as u:
            u.conn.execute(
                "UPDATE records SET body=json_replace(body,'$.status',"
                "'superseded') WHERE kind='referenceanalysis' AND id=?"
                " AND revision=?", (a.id, a.revision))
            u.events.append(f"analysis:{a.id}", "superseded",
                            {"reason": reason, "revision": a.revision})

    def _after_edit(self, a, section):
        a.stages[section] = {"done": True, "at": utcnow()}
        missing = self._completeness(a)
        status = "awaiting_review" if not missing else a.status
        a = self._save(a, status=status, stage=section)
        self._write_docs(a, self._doc_paths(a))
        return a

    def _completeness(self, a):
        return completeness_missing(a)

    def _save(self, a, status=None, stage=None):
        if status:
            a.status = status
        if stage:
            a.stage = stage
        a.content_hash = _hash(a)
        with self.db.uow() as u:
            existing = u.records.get("referenceanalysis", a.id,
                                     revision=a.revision)
            u.records.put(a, expected_version=None if existing is None
                          else existing["version"])
        return a

    # --------------------------------------------------- documents

    def _write_docs(self, a, files):
        ref = self._project(a) / "references" / a.seed_id
        prod = self._project(a) / "productions" / a.seed_id
        (ref / "evidence").mkdir(parents=True, exist_ok=True)
        prod.mkdir(parents=True, exist_ok=True)
        acq = a.acquisition
        t = a.transcript
        files["analysis_md"].write_text(self._analysis_md(a, acq, t))
        files["timeline_md"].write_text(self._timeline_md(a))
        files["brief_md"].write_text(
            f"# Brief — {a.seed_id}\n\nAdapt the reference "
            f"`{acq.get('url','')}` into an original piece. See "
            f"../../references/{a.seed_id}/ANALYSIS.md for the source "
            "reading.\n")
        files["treatment_md"].write_text(
            "# Treatment\n\n" + "\n".join(
                f"## {k}\n\n{v or '_pending_'}\n"
                for k, v in {**{f: a.treatment.get(f, "")
                                for f in TREATMENT_FIELDS},
                             "prompt_notes": a.treatment.get(
                                 "prompt_notes", "")}.items()))
        files["progress_md"].write_text(
            f"# Progress\n\n- status: {a.status}\n- stage: {a.stage}\n"
            f"- blocking: {json.dumps(a.blocking)}\n"
            f"- transcript: {t.get('status','')} "
            f"({t.get('provider','')})\n- next: "
            f"{self._next_action(a)}\n")
        manifest = {
            "seed_id": a.seed_id, "revision": a.revision,
            "source_sha256": a.source_sha256,
            "grids": a.evidence.get("grids", []),
            "boundaries": a.evidence.get("boundaries", [])}
        files["manifest"].parent.mkdir(parents=True, exist_ok=True)
        files["manifest"].write_text(json.dumps(manifest, indent=1))

    def _analysis_md(self, a, acq, t):
        u = a.understanding
        obs = "\n".join(f"- {o}" for o in u.get("observations", [])) \
            or "- _pending_"
        interp = "\n".join(f"- {o}" for o in u.get("interpretations", [])) \
            or "- _pending_"
        unc = "\n".join(f"- {o}" for o in u.get("uncertainties", [])) \
            or "- none recorded"
        body = [f"# Analysis — {a.seed_id} (revision {a.revision})", "",
                "## Verified acquisition", "",
                f"- url: {acq.get('url','')}",
                f"- artifact: {acq.get('artifact_id','')}",
                f"- sha256: {acq.get('sha256','')}",
                f"- duration: {acq.get('duration_s','')}s · "
                f"{acq.get('width','')}x{acq.get('height','')} · "
                f"{acq.get('fps','')} fps · audio: "
                f"{acq.get('audio_present')}", "",
                "## Transcript", "",
                f"- status: {t.get('status','pending')} "
                f"(provider: {t.get('provider','—')}, "
                f"preliminary: {t.get('preliminary')})",
                f"- provenance: {t.get('provenance','—')}", "",
                "## Whole-piece understanding", ""]
        for f in UNDERSTANDING_FIELDS:
            body += [f"### {f}", "", u.get(f) or "_pending_", ""]
        body += ["## Observed facts", "", obs, "",
                 "## Interpretation", "", interp, "",
                 "## Uncertainties", "", unc, ""]
        return "\n".join(body)

    def _timeline_md(self, a):
        lines = [f"# Timeline — {a.seed_id}", ""]
        for s in a.timeline:
            lines += [f"## {s['start_s']}–{s['end_s']} · {s['phase']}", "",
                      s["summary"], ""]
            if s.get("evidence_ids"):
                lines += [f"evidence: {', '.join(s['evidence_ids'])}", ""]
        if not a.timeline:
            lines += ["_sections pending — save timed sections through "
                      "the dashboard_", ""]
        cuts = a.evidence.get("boundaries") or []
        if cuts:
            lines += ["## Detected cut candidates", "",
                      ", ".join(f"{c['t']}s" for c in cuts), ""]
        return "\n".join(lines)

    def _next_action(self, a):
        if a.status == "blocked":
            return "resolve a blocking issue via the dashboard recovery actions"
        missing = self._completeness(a)
        if not missing:
            return "human review"
        return f"complete: {', '.join(missing[:3])}"

    @staticmethod
    def _parse_boundaries(doc):
        items = (doc or {}).get("candidates") or \
            (doc or {}).get("boundaries") or (doc or {}).get("items") or []
        out = []
        for b in items:
            t = b.get("at", b.get("t", b.get("time_s",
                                           b.get("start_s"))))
            if t is None:
                continue
            out.append({"t": float(t), "score": b.get("score", 0.0)})
        return sorted(out, key=lambda x: -x["score"])[:12]

    @staticmethod
    def _transcript_words(path):
        try:
            doc = json.loads(Path(path).read_text())
        except (json.JSONDecodeError, OSError):
            return []
        if isinstance(doc, dict):
            if isinstance(doc.get("passages"), list):
                return [w for p in doc["passages"]
                        for w in (p.get("words") or [])]
            return doc.get("words") or doc.get("segments") or []
        return doc if isinstance(doc, list) else []


def _hypit_transcript(words, source, language, audio_seconds,
                      provider):
    """Write the hypit.transcript@1 file `hypit media tiles` reads.
    Imported word lists carry flat {word, start_s, end_s} entries;
    passages are split at >2s gaps so the file mirrors the utterance
    grouping a real WhisperX endpoint produces — no invented data."""
    passages, current = [], []
    for w in words:
        if current and w["start_s"] - current[-1]["end_s"] > 2.0:
            passages.append(current)
            current = []
        current.append(w)
    if current:
        passages.append(current)
    return {
        "format": "hypit.transcript@1", "source": str(source),
        "language": language, "audio_seconds": audio_seconds,
        "imported_by": provider,
        "passages": [{
            "text": " ".join(w["word"] for w in group),
            "start_seconds": group[0]["start_s"],
            "end_seconds": group[-1]["end_s"],
            "words": [{"text": w["word"],
                       "start_seconds": w["start_s"],
                       "end_seconds": w["end_s"]} for w in group]}
            for group in passages]}


def _cli_error(r):
    """hypit reports failures as JSON on stdout; stderr only carries
    Node warnings — read the real message first."""
    try:
        doc = json.loads(getattr(r, "stdout", "") or "")
        msg = (doc.get("error") or {}).get("message")
        if msg:
            return str(msg)
    except (json.JSONDecodeError, AttributeError):
        pass
    return getattr(r, "stderr", "") or ""
